from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping
from uuid import uuid4

from app.services.station_sales_role import REMOTE_ROLE_PERIODS, normalize_remote_role_snapshot


REMOTE_ROLE_LABEL_IDS = (1301, 1302, 1303, 1304)
REMOTE_ROLE_PERIOD_LABELS = tuple(f"{days}d" for days in REMOTE_ROLE_PERIODS)
CACHE_COLUMNS = (
    "data_date",
    "period_days",
    "label_period",
    "country",
    "station_store",
    "msku",
    "label_id",
    "role_code",
    "role_label",
    "evidence_json",
    "rule_version",
    "source_created_time",
    "sync_batch_id",
)


@dataclass(frozen=True)
class CacheSyncResult:
    data_dates: tuple[date, ...]
    row_count: int
    sync_batch_id: str
    changed_dates: tuple[date, ...] = ()


def _schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value or ""):
        raise ValueError(f"Unsafe schema name: {value!r}")
    return value


def _target_table(target_schema: str) -> str:
    return f"`{_schema_name(target_schema)}`.`station_sales_role_recent_cache`"


def _state_table(target_schema: str) -> str:
    return f"`{_schema_name(target_schema)}`.`station_sales_role_cache_state`"


def station_role_recent_cache_ddl(target_schema: str) -> str:
    return f"""
        create table if not exists {_target_table(target_schema)} (
            data_date date not null,
            period_days int not null,
            label_period varchar(8) not null,
            country varchar(64) not null,
            station_store varchar(255) not null,
            msku varchar(128) not null,
            label_id int not null,
            role_code varchar(32) not null,
            role_label varchar(32) not null,
            evidence_json json null,
            rule_version varchar(64) null,
            source_created_time datetime null,
            sync_batch_id varchar(64) not null,
            synced_at datetime not null default current_timestamp,
            primary key (data_date, period_days, country, station_store, msku),
            key idx_role_cache_product (country, station_store, msku, data_date),
            key idx_role_cache_synced (synced_at)
        ) engine=InnoDB default charset=utf8mb4
    """


def station_role_cache_state_ddl(target_schema: str) -> str:
    return f"""
        create table if not exists {_state_table(target_schema)} (
            data_date date not null,
            source_row_count bigint not null,
            source_period_count int not null,
            source_max_created_time datetime null,
            source_checksum_sum decimal(30,0) not null,
            source_checksum_xor bigint unsigned not null,
            sync_batch_id varchar(64) not null,
            synced_at datetime not null default current_timestamp,
            primary key (data_date)
        ) engine=InnoDB default charset=utf8mb4
    """


def _source_fingerprints_sql() -> str:
    return """
        select
            data_date,
            count(*) as source_row_count,
            count(distinct label_period) as source_period_count,
            max(created_time) as source_max_created_time,
            sum(crc32(concat_ws(
                char(31),
                coalesce(country, ''),
                coalesce(store, ''),
                coalesce(msku, ''),
                coalesce(cast(label_id as char), ''),
                coalesce(label_period, ''),
                coalesce(date_format(created_time, '%%Y-%%m-%%d %%H:%%i:%%s.%%f'), ''),
                coalesce(cast(json_extract(evidence_json, '$.metrics') as char), ''),
                coalesce(cast(json_extract(evidence_json, '$.rule_version') as char), '')
            ))) as source_checksum_sum,
            bit_xor(crc32(concat_ws(
                char(31),
                coalesce(country, ''),
                coalesce(store, ''),
                coalesce(msku, ''),
                coalesce(cast(label_id as char), ''),
                coalesce(label_period, ''),
                coalesce(date_format(created_time, '%%Y-%%m-%%d %%H:%%i:%%s.%%f'), ''),
                coalesce(cast(json_extract(evidence_json, '$.metrics') as char), ''),
                coalesce(cast(json_extract(evidence_json, '$.rule_version') as char), '')
            ))) as source_checksum_xor
        from dws_datasync.`dws_标签表`
        where label_id in %(label_ids)s
          and label_period in %(periods)s
          and data_date in %(data_dates)s
        group by data_date
        order by data_date
    """


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, datetime):
        return value.replace(microsecond=value.microsecond)
    return value


def _same_fingerprint(source: Mapping[str, Any], local: Mapping[str, Any] | None) -> bool:
    if not local:
        return False
    fields = (
        "source_row_count",
        "source_period_count",
        "source_max_created_time",
        "source_checksum_sum",
        "source_checksum_xor",
    )
    return all(_fingerprint_value(source.get(field)) == _fingerprint_value(local.get(field)) for field in fields)


def _load_local_cache_state(target_cursor, target_schema: str) -> dict[date, dict[str, Any]]:
    target_cursor.execute(
        f"""
        select
            s.data_date,
            s.source_row_count,
            s.source_period_count,
            s.source_max_created_time,
            s.source_checksum_sum,
            s.source_checksum_xor,
            count(c.data_date) as local_row_count,
            count(distinct c.period_days) as local_period_count
        from {_state_table(target_schema)} s
        left join {_target_table(target_schema)} c
          on c.data_date = s.data_date
        group by
            s.data_date,
            s.source_row_count,
            s.source_period_count,
            s.source_max_created_time,
            s.source_checksum_sum,
            s.source_checksum_xor
        """
    )
    return {row["data_date"]: row for row in target_cursor.fetchall()}


def _cache_is_complete(source: Mapping[str, Any], local: Mapping[str, Any] | None) -> bool:
    return (
        _same_fingerprint(source, local)
        and int(local.get("local_row_count") or 0) == int(source.get("source_row_count") or 0)
        and int(local.get("local_period_count") or 0) == len(REMOTE_ROLE_PERIODS)
    )


def _period_days(row: Mapping[str, Any]) -> int:
    label = str(row.get("label_period") or "")
    if not label.endswith("d") or not label[:-1].isdigit():
        raise ValueError(f"Invalid label period: {label!r}")
    days = int(label[:-1])
    if days not in REMOTE_ROLE_PERIODS:
        raise ValueError(f"Unsupported remote role period: {label!r}")
    return days


def validate_remote_rows(rows: Iterable[Mapping[str, Any]], data_dates: Iterable[date]) -> list[Mapping[str, Any]]:
    materialized = list(rows)
    expected_dates = tuple(sorted(set(data_dates)))
    if not expected_dates:
        raise ValueError("No remote station role data dates")

    seen: set[tuple[Any, ...]] = set()
    periods_by_date: dict[date, set[int]] = {item: set() for item in expected_dates}
    for row in materialized:
        row_date = row.get("data_date")
        if row_date not in periods_by_date:
            raise ValueError(f"Unexpected remote station role date: {row_date!r}")
        country = str(row.get("country") or "").strip()
        store = str(row.get("store") or row.get("station_store") or "").strip()
        msku = str(row.get("msku") or "").strip()
        if not country or not store or not msku:
            raise ValueError("Remote station role business key is incomplete")
        period_days = _period_days(row)
        key = (row_date, period_days, country, store, msku)
        if key in seen:
            raise ValueError(f"Remote station role duplicate business key: {key!r}")
        seen.add(key)
        periods_by_date[row_date].add(period_days)

    required = set(REMOTE_ROLE_PERIODS)
    for row_date, actual in periods_by_date.items():
        if actual != required:
            raise ValueError(f"Remote station role missing periods for {row_date}: {sorted(required - actual)}")
    return materialized


def _cache_payload(row: Mapping[str, Any], sync_batch_id: str) -> dict[str, Any]:
    snapshot = normalize_remote_role_snapshot(row)
    evidence = row.get("evidence_json")
    if evidence is not None and not isinstance(evidence, str):
        evidence = json.dumps(evidence, ensure_ascii=False, default=str)
    return {
        "data_date": row["data_date"],
        "period_days": _period_days(row),
        "label_period": row["label_period"],
        "country": str(row["country"]).strip(),
        "station_store": str(row.get("store") or row.get("station_store")).strip(),
        "msku": str(row["msku"]).strip(),
        "label_id": int(row["label_id"]),
        "role_code": snapshot["role_code"],
        "role_label": snapshot["role_label"],
        "evidence_json": evidence,
        "rule_version": snapshot["rule_version"],
        "source_created_time": snapshot["source_created_time"],
        "sync_batch_id": sync_batch_id,
    }


def _chunks(rows: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), batch_size):
        yield rows[index:index + batch_size]


def sync_recent_station_role_cache(
    source_conn,
    target_conn,
    target_schema: str,
    batch_size: int = 1000,
) -> CacheSyncResult:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    sync_batch_id = uuid4().hex
    target = _target_table(target_schema)
    state_table = _state_table(target_schema)
    temporary = "`tmp_station_sales_role_recent_cache`"
    columns = ", ".join(f"`{column}`" for column in CACHE_COLUMNS)
    values = ", ".join(f"%({column})s" for column in CACHE_COLUMNS)
    row_count = 0
    try:
        with source_conn.cursor() as source_cursor:
            source_cursor.execute(
            """
            select distinct data_date
            from dws_datasync.`dws_标签表`
            where label_id in %(label_ids)s
            order by data_date desc
            limit 2
            """,
            {"label_ids": REMOTE_ROLE_LABEL_IDS},
        )
            data_dates = tuple(sorted(row["data_date"] for row in source_cursor.fetchall()))
            if not data_dates:
                raise ValueError("No remote station role data dates")

            source_cursor.execute(
                _source_fingerprints_sql(),
                {
                    "label_ids": REMOTE_ROLE_LABEL_IDS,
                    "periods": REMOTE_ROLE_PERIOD_LABELS,
                    "data_dates": data_dates,
                },
            )
            source_fingerprints = {
                row["data_date"]: row
                for row in source_cursor.fetchall()
            }
            if set(source_fingerprints) != set(data_dates):
                raise ValueError("Remote station role fingerprints are incomplete")
            for row_date, fingerprint in source_fingerprints.items():
                if int(fingerprint.get("source_period_count") or 0) != len(REMOTE_ROLE_PERIODS):
                    raise ValueError(f"Remote station role missing periods for {row_date}")

            with target_conn.cursor() as target_cursor:
                target_cursor.execute(station_role_recent_cache_ddl(target_schema))
                target_cursor.execute(station_role_cache_state_ddl(target_schema))
                local_state = _load_local_cache_state(target_cursor, target_schema)
                changed_dates = tuple(
                    row_date
                    for row_date in data_dates
                    if not _cache_is_complete(source_fingerprints[row_date], local_state.get(row_date))
                )

            if changed_dates:
                source_cursor.execute(
                    """
                select data_date, country, store, msku, label_id, label_period,
                       created_time,
                       json_object(
                           'metrics', json_extract(evidence_json, '$.metrics'),
                           'rule_version', json_extract(evidence_json, '$.rule_version')
                       ) as evidence_json
                from dws_datasync.`dws_标签表`
                where label_id in %(label_ids)s
                  and label_period in %(periods)s
                  and data_date in %(data_dates)s
                """,
                {
                    "label_ids": REMOTE_ROLE_LABEL_IDS,
                    "periods": REMOTE_ROLE_PERIOD_LABELS,
                    "data_dates": changed_dates,
                },
            )
            periods_by_date: dict[date, set[int]] = {item: set() for item in changed_dates}
            with target_conn.cursor() as target_cursor:
                target_cursor.execute(f"drop temporary table if exists {temporary}")
                target_cursor.execute(f"create temporary table {temporary} like {target}")
                insert_temp = f"insert into {temporary} ({columns}) values ({values})"
                if changed_dates:
                    while True:
                        remote_batch = source_cursor.fetchmany(batch_size)
                        if not remote_batch:
                            break
                        payload = []
                        for row in remote_batch:
                            row_date = row.get("data_date")
                            if row_date not in periods_by_date:
                                raise ValueError(f"Unexpected remote station role date: {row_date!r}")
                            country = str(row.get("country") or "").strip()
                            store = str(row.get("store") or row.get("station_store") or "").strip()
                            msku = str(row.get("msku") or "").strip()
                            if not country or not store or not msku:
                                raise ValueError("Remote station role business key is incomplete")
                            periods_by_date[row_date].add(_period_days(row))
                            payload.append(_cache_payload(row, sync_batch_id))
                        target_cursor.executemany(insert_temp, payload)
                        row_count += len(payload)

                required = set(REMOTE_ROLE_PERIODS)
                for row_date, actual in periods_by_date.items():
                    if actual != required:
                        raise ValueError(
                            f"Remote station role missing periods for {row_date}: "
                            f"{sorted(required - actual)}"
                        )
                target_cursor.execute(
                    f"delete from {target} where data_date not in %(data_dates)s",
                    {"data_dates": data_dates},
                )
                if changed_dates:
                    target_cursor.execute(
                        f"delete from {target} where data_date in %(changed_dates)s",
                        {"changed_dates": changed_dates},
                    )
                    target_cursor.execute(
                        f"insert into {target} ({columns}) select {columns} from {temporary}"
                    )
                target_cursor.execute(
                    f"delete from {state_table} where data_date not in %(data_dates)s",
                    {"data_dates": data_dates},
                )
                state_sql = f"""
                    insert into {state_table} (
                        data_date, source_row_count, source_period_count,
                        source_max_created_time, source_checksum_sum, source_checksum_xor,
                        sync_batch_id
                    ) values (
                        %(data_date)s, %(source_row_count)s, %(source_period_count)s,
                        %(source_max_created_time)s, %(source_checksum_sum)s, %(source_checksum_xor)s,
                        %(sync_batch_id)s
                    ) on duplicate key update
                        source_row_count=values(source_row_count),
                        source_period_count=values(source_period_count),
                        source_max_created_time=values(source_max_created_time),
                        source_checksum_sum=values(source_checksum_sum),
                        source_checksum_xor=values(source_checksum_xor),
                        sync_batch_id=values(sync_batch_id),
                        synced_at=current_timestamp
                """
                target_cursor.executemany(
                    state_sql,
                    [
                        {
                            **source_fingerprints[row_date],
                            "sync_batch_id": sync_batch_id,
                        }
                        for row_date in changed_dates
                    ],
                )
                target_cursor.execute(f"drop temporary table {temporary}")
        target_conn.commit()
    except Exception:
        target_conn.rollback()
        raise
    return CacheSyncResult(
        data_dates=data_dates,
        row_count=row_count,
        sync_batch_id=sync_batch_id,
        changed_dates=changed_dates,
    )
