"""Read approved business sources into an atomic, local V47 input batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from contextlib import suppress
import hashlib
import json
import re
import socket
from typing import Callable

from etl.label_local_sql import (
    SOURCE_TABLES,
    baseline_sql,
    checked_schema,
    identifier,
    quote,
    sql_tokens,
)
from etl.label_fba_source import (
    RAW_REFERENCE,
    NORMALIZATION_VERSION,
    fba_columns,
    fba_indexes,
    fba_select_sql,
)


# Tags and an adjustment queue may legitimately be empty. The complete business
# datasets below must exist before missing inventory can mean zero inventory.
OPTIONAL_EMPTY_SOURCES = {
    "dashboard_label_source_listing_tag",
    "dashboard_label_source_price_adjustment",
}


def validate_source_count(local_name: str, count: int) -> None:
    if count == 0 and local_name not in OPTIONAL_EMPTY_SOURCES:
        raise RuntimeError(f"required business source is empty: {local_name}")


@dataclass(frozen=True)
class SourceSpec:
    schema: str
    table: str
    local_name: str

    @property
    def reference(self) -> str:
        return f"{self.schema}.{self.table}"


def source_specs() -> tuple[SourceSpec, ...]:
    return tuple(
        SourceSpec(
            *(
                RAW_REFERENCE
                if local == "dashboard_label_source_fba"
                else (schema, table)
            ),
            local,
        )
        for (schema, table), local in SOURCE_TABLES.items()
    )


@lru_cache(maxsize=1)
def _rule_identifiers() -> set[str]:
    return {
        identifier(value).casefold()
        for kind, value in sql_tokens(baseline_sql())
        if kind in {"word", "quoted"}
    }


def project_columns(
    reference: str, columns: list[dict], indexes: list[dict]
) -> list[dict]:
    if reference == "dws_datasync.dws_标签详情表":
        return columns
    names = set(_rule_identifiers())
    # Preserve columns used by mandatory FORCE INDEX clauses and source primary keys.
    forced = {
        "primary",
        "idx_osp_performance_date_sync",
        "id1",
        "idx_date_store_site_wh_msku",
    }
    names.update(
        str(row["column_name"]).casefold()
        for row in indexes
        if row["index_name"].lower() in forced
    )
    return [row for row in columns if row["column_name"].casefold() in names]


def source_select_sql(
    spec: SourceSpec, columns: list[str], *, raw_fba_date=None
) -> tuple[str, tuple]:
    if spec not in source_specs():
        raise ValueError("source is not in the V47 allowlist")
    if spec.local_name == "dashboard_label_source_fba":
        return fba_select_sql(columns), ()
    sql = f"select {', '.join(quote(c) for c in columns)} from {quote(spec.schema)}.{quote(spec.table)}"
    params = ()
    if spec.local_name == "dashboard_label_source_raw_fba":
        if raw_fba_date is None:
            raise ValueError("raw FBA snapshot date is missing")
        sql += " where create_time >= %s"
        params = (raw_fba_date,)
    return sql, params


def read_metadata(source_conn, spec: SourceSpec) -> tuple[list[dict], list[dict]]:
    with source_conn.cursor() as cursor:
        cursor.execute(
            "select column_name, column_type, is_nullable, character_set_name, collation_name "
            "from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position",
            (spec.schema, spec.table),
        )
        columns = [{k.lower(): v for k, v in row.items()} for row in cursor.fetchall()]
        cursor.execute(
            "select index_name, non_unique, seq_in_index, column_name, sub_part "
            "from information_schema.statistics where table_schema=%s and table_name=%s order by index_name,seq_in_index",
            (spec.schema, spec.table),
        )
        indexes = [{k.lower(): v for k, v in row.items()} for row in cursor.fetchall()]
    if not columns:
        raise RuntimeError(f"source table missing or inaccessible: {spec.reference}")
    return columns, indexes


def source_table_ddl(qualified_name: str, columns: list[dict]) -> str:
    definitions = []
    for column in columns:
        # Metadata is data, not executable SQL. Reject unsupported type declarations.
        kind = column["column_type"].lower()
        if not re.fullmatch(r"[a-z0-9_ (),.]+", kind):
            raise ValueError(f"unsupported source type: {column['column_name']} {kind}")
        text = f"{quote(column['column_name'])} {kind}"
        for field, keyword in (
            ("character_set_name", "character set"),
            ("collation_name", "collate"),
        ):
            value = column.get(field)
            if value:
                if not re.fullmatch(r"[a-zA-Z0-9_]+", value):
                    raise ValueError(f"invalid source {field}")
                text += f" {keyword} {value}"
        text += " null" if column["is_nullable"] == "YES" else " not null"
        definitions.append(text)
    return f"create table {qualified_name} ({', '.join(definitions)}) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci"


def source_index_clauses(columns: list[dict], indexes: list[dict]) -> list[str]:
    names = {row["column_name"] for row in columns}
    groups: dict[str, list[dict]] = {}
    for row in indexes:
        groups.setdefault(row["index_name"], []).append(row)
    clauses = []
    for name, rows in groups.items():
        rows = sorted(rows, key=lambda row: int(row["seq_in_index"]))
        if not all(row["column_name"] in names for row in rows):
            continue
        key_columns = ", ".join(
            quote(row["column_name"])
            + (f"({int(row['sub_part'])})" if row.get("sub_part") else "")
            for row in rows
        )
        if name.lower() == "primary":
            clauses.append(f"add primary key ({key_columns})")
        else:
            kind = "key" if rows[0]["non_unique"] else "unique key"
            clauses.append(f"add {kind} {quote(name)} ({key_columns})")
    return clauses


def _json_value(value):
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    return str(value)


def configure_source_keepalive(source_conn) -> None:
    """Keep the read-only connection alive during local inserts/index builds."""
    sock = getattr(source_conn, "_sock", None)
    if sock is not None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
        else:
            for option, value in (
                ("TCP_KEEPIDLE", 30),
                ("TCP_KEEPINTVL", 10),
                ("TCP_KEEPCNT", 3),
            ):
                if hasattr(socket, option):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), value)
    with source_conn.cursor() as cursor:
        cursor.execute("set session net_write_timeout=600")


def staged_resume_manifest(items: list[dict] | None) -> dict[str, dict]:
    allowed = {
        s.local_name: s.reference
        for s in source_specs()
        if s.local_name
        in {"dashboard_label_source_listing", "dashboard_label_source_performance"}
    }
    result = {}
    for item in items or []:
        name = item.get("local_name")
        if name not in allowed or item.get("source") != allowed[name] or name in result:
            raise RuntimeError("invalid or duplicate completed stage for resume")
        if (
            not isinstance(item.get("rows"), int)
            or item["rows"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))
        ):
            raise RuntimeError("invalid completed stage manifest")
        result[name] = item
    return result


def validate_staged_resume(
    target_conn,
    schema: str,
    stage_name: str,
    manifest: dict,
    names: list[str],
    indexes: list[dict],
) -> None:
    if manifest.get("columns") != names:
        raise RuntimeError("completed stage source columns changed; resume blocked")
    with target_conn.cursor() as cursor:
        cursor.execute(
            "select column_name from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position",
            (schema, stage_name),
        )
        actual = [next(iter(r.values())) for r in cursor.fetchall()]
        if actual != names:
            raise RuntimeError("completed stage columns missing or changed")
        cursor.execute(
            "select distinct index_name from information_schema.statistics where table_schema=%s and table_name=%s",
            (schema, stage_name),
        )
        actual_indexes = {
            str(next(iter(r.values()))).casefold() for r in cursor.fetchall()
        }
        index_columns = {}
        for i in indexes:
            index_columns.setdefault(str(i["index_name"]).casefold(), []).append(
                i["column_name"]
            )
        needed = {
            name
            for name, cols in index_columns.items()
            if all(col in names for col in cols)
        }
        if not needed <= actual_indexes:
            raise RuntimeError("completed stage indexes missing; resume blocked")
        cursor.execute(f"select count(*) as n from {quote(schema)}.{quote(stage_name)}")
        if int(cursor.fetchone()["n"]) != manifest["rows"]:
            raise RuntimeError("completed stage row count mismatch; resume blocked")


def sync_sources(
    source_conn,
    target_conn,
    schema: str,
    batch_id: str,
    *,
    progress: Callable[[dict], None] = print,
    refresh_inventory_only: bool = False,
    resume_staged_sources: list[dict] | None = None,
) -> dict:
    """All remote statements are reads. All writes target dedicated local tables.

    Normal inputs use one repeatable-read transaction. Explicit recovery may
    retain validated completed stages from a failed transaction, and records
    this mixed snapshot provenance rather than claiming a single snapshot.
    """
    schema = checked_schema(schema)
    manifests = []
    staged = []
    previous = None
    resumed = staged_resume_manifest(resume_staged_sources)
    if resumed and refresh_inventory_only:
        raise RuntimeError(
            "staged resume cannot be combined with inventory-only refresh"
        )
    if refresh_inventory_only:
        with target_conn.cursor() as cursor:
            cursor.execute(
                f"select manifest_json from {quote(schema)}.dashboard_label_local_input where singleton=1"
            )
            row = cursor.fetchone()
        if not row:
            raise RuntimeError(
                "inventory-only refresh requires an existing complete label input batch"
            )
        previous = json.loads(row["manifest_json"])
        digest = hashlib.sha256(
            json.dumps(previous["sources"], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        expected = {s.local_name: s.reference for s in source_specs()}
        actual = {s["local_name"]: s["source"] for s in previous["sources"]}
        if (
            digest != previous["input_hash"]
            or len(actual) != len(previous["sources"])
            or actual.keys() != expected.keys()
        ):
            raise RuntimeError(
                "existing label input batch is incomplete or checksum failed"
            )
        if any(
            actual[k] != expected[k]
            for k in expected
            if k != "dashboard_label_source_fba"
        ):
            raise RuntimeError("existing non-FBA input contract differs")
        manifests = [
            item
            for item in previous["sources"]
            if item["local_name"] != "dashboard_label_source_fba"
        ]
    with target_conn.cursor() as cursor:
        cursor.execute(
            f"create table if not exists {quote(schema)}.dashboard_label_local_source_batch (batch_id varchar(36) not null, source_name varchar(180) not null, local_name varchar(64) not null, row_count bigint not null, content_sha256 char(64) not null, contract_json json not null, created_at datetime(6) not null default current_timestamp(6), primary key(batch_id,local_name)) engine=innodb"
        )
        cursor.execute(
            "select column_name from information_schema.statistics where table_schema=%s and table_name='dashboard_label_local_source_batch' and index_name='PRIMARY' order by seq_in_index",
            (schema,),
        )
        keys = [r.get("COLUMN_NAME", r.get("column_name")) for r in cursor.fetchall()]
        if keys == ["batch_id", "source_name"]:
            cursor.execute(
                f"alter table {quote(schema)}.dashboard_label_local_source_batch drop primary key, add primary key(batch_id,local_name)"
            )
        elif keys != ["batch_id", "local_name"]:
            raise RuntimeError("unexpected label source ledger primary key")
    target_conn.commit()
    source_conn.autocommit(False)
    try:
        configure_source_keepalive(source_conn)
        with source_conn.cursor() as cursor:
            cursor.execute(
                "select date(max(create_time)) as snapshot_date from dwd_datasync.lx_storage_fba_warehouse_detail"
            )
            raw_fba_date = cursor.fetchone()["snapshot_date"]
        for spec in source_specs():
            if (
                refresh_inventory_only
                and spec.local_name != "dashboard_label_source_fba"
            ):
                continue
            metadata, indexes = read_metadata(source_conn, spec)
            if spec.local_name == "dashboard_label_source_fba":
                columns, indexes = fba_columns(metadata), fba_indexes()
            else:
                columns = project_columns(spec.reference, metadata, indexes)
            names = [row["column_name"] for row in columns]
            stage_name = spec.local_name + "__load"
            stage = f"{quote(schema)}.{quote(stage_name)}"
            if spec.local_name in resumed:
                item = resumed[spec.local_name]
                validate_staged_resume(
                    target_conn, schema, stage_name, item, names, indexes
                )
                manifest = {
                    **item,
                    "reused_completed_stage": True,
                    "source_snapshot_origin": "previous_failed_sync",
                }
                manifests.append(manifest)
                staged.append((spec.local_name, stage_name))
                progress({"stage": "source_resumed", **manifest})
                continue
            progress(
                {
                    "stage": "source_start",
                    "source": spec.reference,
                    "columns": len(names),
                }
            )
            with target_conn.cursor() as cursor:
                cursor.execute(f"drop table if exists {stage}")
                cursor.execute(source_table_ddl(stage, columns))
            target_conn.commit()
            sql, params = source_select_sql(spec, names, raw_fba_date=raw_fba_date)
            insert = f"insert into {stage} ({', '.join(quote(c) for c in names)}) values ({','.join(['%s'] * len(names))})"
            digest = hashlib.sha256()
            count = 0
            with source_conn.cursor() as reader:
                reader.execute(sql, params or None)
                while rows := reader.fetchmany(5000):
                    values = [tuple(row[name] for name in names) for row in rows]
                    with target_conn.cursor() as writer:
                        writer.executemany(insert, values)
                    target_conn.commit()
                    for row in values:
                        digest.update(
                            json.dumps(
                                row,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                default=_json_value,
                            ).encode("utf-8")
                            + b"\n"
                        )
                    count += len(rows)
                    if count % 100000 == 0:
                        progress(
                            {
                                "stage": "source_copy",
                                "source": spec.reference,
                                "rows": count,
                            }
                        )
            validate_source_count(spec.local_name, count)
            clauses = source_index_clauses(columns, indexes)
            with target_conn.cursor() as cursor:
                if clauses:
                    cursor.execute(f"alter table {stage} " + ", ".join(clauses))
                cursor.execute(f"select count(*) as n from {stage}")
                if int(cursor.fetchone()["n"]) != count:
                    raise RuntimeError(f"source copy count mismatch: {spec.reference}")
            manifest = {
                "source": spec.reference,
                "local_name": spec.local_name,
                "rows": count,
                "sha256": digest.hexdigest(),
                "columns": names,
                "raw_fba_date": str(raw_fba_date),
            }
            if spec.local_name == "dashboard_label_source_fba":
                manifest.update(
                    normalization_version=NORMALIZATION_VERSION,
                    projection_sha256=hashlib.sha256(sql.encode()).hexdigest(),
                )
            manifests.append(manifest)
            staged.append((spec.local_name, stage_name))
            progress({"stage": "source_complete", **manifest})
        source_conn.commit()
        content_hash = hashlib.sha256(
            json.dumps(manifests, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        result = {
            "batch_id": batch_id,
            "input_hash": content_hash,
            "sources": manifests,
        }
        result["input_consistency"] = (
            "resumed_across_transactions" if resumed else "single_read_transaction"
        )
        if previous is not None:
            result["reused_input_batch"] = previous["batch_id"]
        # The marker travels in the same atomic rename as the input tables.
        # A crash must never associate a new table set with an older manifest.
        marker = f"{quote(schema)}.dashboard_label_local_input__load"
        with target_conn.cursor() as cursor:
            cursor.execute(f"drop table if exists {marker}")
            cursor.execute(
                f"create table {marker} (singleton tinyint primary key, manifest_json json not null) engine=innodb"
            )
            cursor.execute(
                f"insert into {marker} values (1,%s)",
                (json.dumps(result, ensure_ascii=False),),
            )
            for item in manifests:
                cursor.execute(
                    f"insert into {quote(schema)}.dashboard_label_local_source_batch (batch_id,source_name,local_name,row_count,content_sha256,contract_json) values (%s,%s,%s,%s,%s,%s)",
                    (
                        batch_id,
                        item["source"],
                        item["local_name"],
                        item["rows"],
                        item["sha256"],
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
        target_conn.commit()
        staged.append(
            ("dashboard_label_local_input", "dashboard_label_local_input__load")
        )
        # Publish every input table in one atomic MySQL rename, never a mixed batch.
        swaps = []
        old_tables = []
        with target_conn.cursor() as cursor:
            for local, stage in staged:
                cursor.execute(
                    "select count(*) as n from information_schema.tables where table_schema=%s and table_name=%s",
                    (schema, local),
                )
                if cursor.fetchone()["n"]:
                    old = f"{quote(schema)}.{quote(local + '__old')}"
                    cursor.execute(f"drop table if exists {old}")
                    swaps.append(f"{quote(schema)}.{quote(local)} to {old}")
                    old_tables.append(old)
                swaps.append(
                    f"{quote(schema)}.{quote(stage)} to {quote(schema)}.{quote(local)}"
                )
            cursor.execute("rename table " + ", ".join(swaps))
        target_conn.commit()
        with target_conn.cursor() as cursor:
            for old in old_tables:
                cursor.execute(f"drop table {old}")
        target_conn.commit()
        return result
    except Exception:
        # A broken socket must not mask the original error with InterfaceError
        # during rollback or autocommit restoration.
        with suppress(Exception):
            source_conn.rollback()
        with suppress(Exception):
            target_conn.rollback()
        raise
    finally:
        with suppress(Exception):
            source_conn.autocommit(True)
