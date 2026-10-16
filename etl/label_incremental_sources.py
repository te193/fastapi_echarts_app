"""Reconcile label input partitions without transferring unchanged history."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import hashlib
from itertools import groupby
import json
from time import sleep

from pymysql.err import OperationalError

from etl.label_fba_source import NORMALIZATION_VERSION, fba_columns, fba_indexes
from etl.label_local_sql import quote
from etl.label_local_sources import (
    SourceSpec,
    configure_source_keepalive,
    project_columns,
    read_metadata,
    source_select_sql,
    source_specs,
    source_table_ddl,
    validate_source_count,
)


FINGERPRINT_VERSION = "sha256_partition_sums_v1"
DATE_COLUMNS = {
    "dashboard_label_source_performance": "start_date",
    "dashboard_label_source_fba": "create_time",
    "dashboard_label_source_restock": "create_time",
    "dashboard_label_source_inventory": "\u6570\u636e\u65e5\u671f",
    "dashboard_label_source_price_history": "\u6570\u636e\u65e5\u671f",
}


def partition_expression(local_name: str) -> str:
    if local_name in DATE_COLUMNS:
        return (
            f"coalesce(cast(date({quote(DATE_COLUMNS[local_name])}) as char), "
            "'__NULL__')"
        )
    if local_name == "dashboard_label_source_orders":
        return "coalesce(cast(floor(`id` / 50000) as char), '__NULL__')"
    return "'all'"


def fingerprint_sql(spec: SourceSpec, names: list[str], select_sql: str) -> str:
    fields = ", ".join(quote(name) for name in names)
    # JSON preserves nulls, field boundaries and types; two independent 64-bit
    # sums plus count preserve duplicate multiplicity without depending on order.
    row_hash = f"sha2(cast(json_array({fields}) as char character set utf8mb4),256)"
    return (
        "select partition_key,count(*) as rows_count,"
        "sum(cast(conv(substr(row_hash,1,16),16,10) as decimal(20,0))) as hash_1,"
        "sum(cast(conv(substr(row_hash,17,16),16,10) as decimal(20,0))) as hash_2 "
        f"from (select {partition_expression(spec.local_name)} as partition_key,"
        f"{row_hash} as row_hash from ({select_sql}) projected) hashed "
        "group by partition_key"
    )


def read_fingerprints(conn, spec, names, select_sql, params=()) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(fingerprint_sql(spec, names, select_sql), params or None)
        return {
            str(row["partition_key"]): {
                "rows": int(row["rows_count"]),
                "hash_1": str(int(row["hash_1"] or 0)),
                "hash_2": str(int(row["hash_2"] or 0)),
            }
            for row in cursor.fetchall()
        }


def changed_partitions(previous: dict, current: dict) -> tuple[str, ...]:
    return tuple(
        key
        for key in sorted(previous.keys() | current.keys())
        if previous.get(key) != current.get(key)
    )


def delta_select_sql(spec, names, keys, *, raw_fba_date):
    sql, params = source_select_sql(spec, names, raw_fba_date=raw_fba_date)
    if not params:
        sql = sql.replace("%", "%%")
    placeholders = ",".join("%s" for _ in keys)
    return (
        f"select * from ({sql}) projected where "
        f"{partition_expression(spec.local_name)} in ({placeholders})",
        (*params, *keys),
    )


def validate_delta(expected: dict, actual: dict, keys) -> None:
    wanted = {key: expected[key] for key in keys if key in expected}
    if actual != wanted:
        raise RuntimeError("incremental staging fingerprint mismatch; inputs unchanged")


def manifest_hash(items: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate_fba_normalization(local_name: str, contract: dict) -> None:
    if (
        local_name == "dashboard_label_source_fba"
        and contract.get("normalization_version") != NORMALIZATION_VERSION
    ):
        raise RuntimeError("FBA normalization changed; use explicit full sync")


def validate_manifest(manifest: dict) -> None:
    if manifest_hash(manifest["sources"]) != manifest.get("input_hash"):
        raise RuntimeError("local input manifest checksum mismatch")
    expected = {(s.reference, s.local_name) for s in source_specs()}
    actual = {(s["source"], s["local_name"]) for s in manifest["sources"]}
    if actual != expected or len(manifest["sources"]) != len(expected):
        raise RuntimeError("local input manifest has an incomplete source contract")
    # Check the saved version before any database work or partition transfers.
    for item in manifest["sources"]:
        validate_fba_normalization(item["local_name"], item)


def validate_source_contract(spec, old: dict, names: list[str]) -> None:
    if old.get("source") != spec.reference:
        raise RuntimeError("source identity changed; use explicit full sync")
    if old.get("columns") != names:
        raise RuntimeError("source columns changed; use explicit full sync")
    validate_fba_normalization(spec.local_name, old)


def _column_contract(columns) -> list[tuple]:
    return [
        tuple(
            str(row.get(key) or "").lower()
            for key in (
                "column_name", "column_type", "is_nullable",
                "character_set_name", "collation_name",
            )
        )
        for row in columns
    ]


def _index_contract(indexes, names) -> dict:
    grouped = {}
    for row in indexes:
        grouped.setdefault(row["index_name"].lower(), []).append(row)
    return {
        name: [
            (int(r["non_unique"]), r["column_name"], r.get("sub_part"))
            for r in sorted(rows, key=lambda r: int(r["seq_in_index"]))
        ]
        for name, rows in grouped.items()
        if all(r["column_name"] in names for r in rows)
    }


def validate_local_table(conn, schema, spec, columns, indexes, old) -> None:
    local_columns, local_indexes = read_metadata(
        conn, SourceSpec(schema, spec.local_name, spec.local_name)
    )
    names = [row["column_name"] for row in columns]
    if _column_contract(local_columns) != _column_contract(columns):
        raise RuntimeError("local source types/collations changed; use explicit full sync")
    required = _index_contract(indexes, names)
    actual = _index_contract(local_indexes, names)
    if any(actual.get(name) != definition for name, definition in required.items()):
        raise RuntimeError("local source indexes changed; use explicit full sync")
    with conn.cursor() as cursor:
        cursor.execute(
            "select engine as engine_name from information_schema.tables "
            "where table_schema=%s and table_name=%s",
            (schema, spec.local_name),
        )
        if str(cursor.fetchone()["engine_name"]).lower() != "innodb":
            raise RuntimeError("incremental input publication requires InnoDB")
        cursor.execute(
            f"select count(*) as n from {quote(schema)}.{quote(spec.local_name)}"
        )
        if int(cursor.fetchone()["n"]) != int(old["rows"]):
            raise RuntimeError("local source row count mismatch; use explicit full sync")


def validate_control_tables(conn, schema) -> None:
    required = {
        "dashboard_label_local_input": {
            "columns": {"singleton": "tinyint", "manifest_json": "json"},
            "primary": ["singleton"],
        },
        "dashboard_label_local_source_batch": {
            "columns": {
                "batch_id": "varchar(36)", "source_name": "varchar(180)",
                "local_name": "varchar(64)", "row_count": "bigint",
                "content_sha256": "char(64)", "contract_json": "json",
            },
            "primary": ["batch_id", "local_name"],
        },
    }
    for name, contract in required.items():
        with conn.cursor() as cursor:
            cursor.execute(
                "select engine as engine_name from information_schema.tables "
                "where table_schema=%s and table_name=%s", (schema, name),
            )
            row = cursor.fetchone()
            if not row or str(row["engine_name"]).lower() != "innodb":
                raise RuntimeError("incremental control tables require InnoDB")
        columns, indexes = read_metadata(conn, SourceSpec(schema, name, name))
        by_name = {c["column_name"]: c for c in columns}
        for column, kind in contract["columns"].items():
            field = by_name.get(column, {})
            if field.get("column_type") != kind or field.get("is_nullable") != "NO":
                raise RuntimeError("control table columns changed; use explicit full sync")
        primary = sorted(
            [i for i in indexes if i["index_name"].lower() == "primary"],
            key=lambda i: int(i["seq_in_index"]),
        )
        if [i["column_name"] for i in primary] != contract["primary"]:
            raise RuntimeError("control table primary key changed; use explicit full sync")


def stage_delta(source, target, schema, spec, columns, keys, remote, raw_date, progress):
    names = [row["column_name"] for row in columns]
    stage = f"{quote(schema)}.{quote(spec.local_name + '__delta')}"
    with target.cursor() as cursor:
        cursor.execute(f"drop table if exists {stage}")
        cursor.execute(source_table_ddl(stage, columns))
    target.commit()
    count = 0
    if any(key in remote for key in keys):
        sql, params = delta_select_sql(spec, names, keys, raw_fba_date=raw_date)
        insert = (
            f"insert into {stage} ({','.join(quote(n) for n in names)}) "
            f"values ({','.join('%s' for _ in names)})"
        )
        with source.cursor() as reader:
            reader.execute(sql, params)
            while rows := reader.fetchmany(5000):
                with target.cursor() as writer:
                    writer.executemany(insert, [tuple(r[n] for n in names) for r in rows])
                target.commit()
                count += len(rows)
                progress({
                    "stage": "source_delta_copy",
                    "source": spec.reference, "rows": count,
                })
    actual = read_fingerprints(target, spec, names, f"select * from {stage}")
    validate_delta(remote, actual, keys)
    return stage, count


def publish_incremental(target, schema, previous, result, replacements) -> None:
    marker = f"{quote(schema)}.dashboard_label_local_input"
    try:
        # No DDL/commits in this transaction: all source replacements, the
        # manifest and batch ledger become visible together or not at all.
        with target.cursor() as cursor:
            cursor.execute(f"select manifest_json from {marker} where singleton=1 for update")
            current = json.loads(cursor.fetchone()["manifest_json"])
            if current.get("input_hash") != previous["input_hash"]:
                raise RuntimeError("input batch changed during incremental sync")
            for spec, names, keys, stage in replacements:
                live = f"{quote(schema)}.{quote(spec.local_name)}"
                placeholders = ",".join("%s" for _ in keys)
                cursor.execute(
                    f"delete from {live} where "
                    f"{partition_expression(spec.local_name)} in ({placeholders})", keys,
                )
                fields = ",".join(quote(n) for n in names)
                cursor.execute(f"insert into {live} ({fields}) select {fields} from {stage}")
            for item in result["sources"]:
                cursor.execute(
                    f"insert into {quote(schema)}.dashboard_label_local_source_batch "
                    "(batch_id,source_name,local_name,row_count,content_sha256,contract_json) "
                    "values (%s,%s,%s,%s,%s,%s)",
                    (
                        result["batch_id"], item["source"], item["local_name"],
                        item["rows"], item["sha256"],
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            cursor.execute(
                f"update {marker} set manifest_json=%s where singleton=1",
                (json.dumps(result, ensure_ascii=False),),
            )
        target.commit()
    except Exception:
        target.rollback()
        raise


def stage_source(source, target, schema, spec, old, raw_date, progress):
    metadata, indexes = read_metadata(source, spec)
    if spec.local_name == "dashboard_label_source_fba":
        columns, indexes = fba_columns(metadata), fba_indexes()
    else:
        columns = project_columns(spec.reference, metadata, indexes)
    names = [row["column_name"] for row in columns]
    validate_source_contract(spec, old, names)
    validate_local_table(target, schema, spec, columns, indexes, old)
    progress({
        "stage": "source_partition_check", "source": spec.reference,
        "local_name": spec.local_name,
    })
    sql, params = source_select_sql(spec, names, raw_fba_date=raw_date)
    remote = read_fingerprints(source, spec, names, sql, params)
    total = sum(p["rows"] for p in remote.values())
    validate_source_count(spec.local_name, total)
    adopted = old.get("fingerprint_version") != FINGERPRINT_VERSION
    if not adopted:
        if old.get("partition_expression") != partition_expression(spec.local_name):
            raise RuntimeError("partition contract changed; use explicit full sync")
    else:
        progress({"stage": "source_adopt_local", "local_name": spec.local_name})
    live = f"{quote(schema)}.{quote(spec.local_name)}"
    local = read_fingerprints(target, spec, names, f"select * from {live}")
    keys = changed_partitions(local, remote)
    progress({
        "stage": "source_partition_plan", "local_name": spec.local_name,
        "changed_partitions": len(keys),
        "planned_transfer_rows": sum(remote[k]["rows"] for k in keys if k in remote),
    })
    replacement, count = None, 0
    if keys:
        stage, count = stage_delta(
            source, target, schema, spec, columns, keys, remote, raw_date, progress
        )
        replacement = (spec, names, keys, stage)
    item = {
        **old, "rows": total, "partitions": remote,
        "fingerprint_version": FINGERPRINT_VERSION,
        "partition_expression": partition_expression(spec.local_name),
        "raw_fba_date": str(raw_date),
        "sha256": hashlib.sha256(
            json.dumps(remote, sort_keys=True).encode()
        ).hexdigest(),
    }
    complete = {
        "stage": "source_incremental_complete", "source": spec.reference,
        "local_name": spec.local_name, "rows": total,
        "transferred_rows": count, "changed_partitions": len(keys),
        "retained_rows": sum(p["rows"] for k, p in local.items() if k not in keys),
    }
    return item, replacement, count, adopted, complete


def sync_incremental_sources(source, target, schema, batch_id, previous, *, progress):
    validate_manifest(previous)
    validate_control_tables(target, schema)
    old_sources = {s["local_name"]: s for s in previous["sources"]}
    manifests, replacements = [], []
    transferred = 0
    adopted = False
    with target.cursor() as cursor:
        cursor.execute("set session time_zone='+08:00'")
    source.autocommit(True)
    with source.cursor() as cursor:
        cursor.execute("set session transaction isolation level repeatable read")
        cursor.execute("set session time_zone='+08:00'")
    source.autocommit(False)
    try:
        configure_source_keepalive(source)
        raw_date = None
        # Each physical source gets a fresh snapshot. Keep the adjacent raw FBA
        # and normalized projections together so they describe the same input.
        for reference, grouped in groupby(source_specs(), key=lambda s: s.reference):
            specs = tuple(grouped)
            for attempt in range(1, 4):
                try:
                    source.rollback()
                    for spec in specs:
                        if spec.local_name == "dashboard_label_source_raw_fba":
                            with source.cursor() as cursor:
                                cursor.execute(
                                    "select date(max(create_time)) as snapshot_date "
                                    f"from {quote(spec.schema)}.{quote(spec.table)}"
                                )
                                raw_date = cursor.fetchone()["snapshot_date"]
                    staged = [
                        stage_source(
                            source, target, schema, spec, old_sources[spec.local_name],
                            raw_date, progress,
                        )
                        for spec in specs
                    ]
                    source.commit()
                    break
                except OperationalError as exc:
                    if not exc.args or exc.args[0] != 1412:
                        raise
                    source.rollback()
                    target.rollback()
                    if attempt == 3:
                        raise OperationalError(
                            1412, f"source {reference}: table definition changed "
                            f"after {attempt} attempts; inputs unchanged",
                        ) from exc
                    progress({
                        "stage": "source_transaction_retry", "source": reference,
                        "attempt": attempt, "max_attempts": 3, "error_code": 1412,
                        "error": str(exc),
                    })
                    sleep(attempt)
            for item, replacement, count, was_adopted, complete in staged:
                manifests.append(item)
                if replacement is not None:
                    replacements.append(replacement)
                transferred += count
                adopted |= was_adopted
                progress(complete)
        for item in manifests:
            item["raw_fba_date"] = str(raw_date)
        if not replacements and not adopted and manifests == previous["sources"]:
            progress({"stage": "inputs_reused", "batch_id": previous["batch_id"],
                      "transferred_rows": 0})
            return previous
        result = {
            "batch_id": batch_id, "input_hash": manifest_hash(manifests),
            "sources": manifests, "sync_mode": "incremental",
            "input_consistency": "partition_reconciled_across_transactions",
            "reused_input_batch": previous["batch_id"],
            "transferred_rows": transferred,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        publish_incremental(target, schema, previous, result, replacements)
        for _, _, _, stage in replacements:
            try:
                with target.cursor() as cursor:
                    cursor.execute(f"drop table {stage}")
            except Exception as exc:
                progress({"stage": "source_cleanup_warning", "table": stage,
                          "error": str(exc)})
        with suppress(Exception):
            target.commit()
        return result
    except Exception:
        with suppress(Exception):
            source.rollback()
        with suppress(Exception):
            target.rollback()
        raise
    finally:
        with suppress(Exception):
            source.autocommit(True)
