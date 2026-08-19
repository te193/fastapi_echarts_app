from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
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


def _schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value or ""):
        raise ValueError(f"Unsafe schema name: {value!r}")
    return value


def _target_table(target_schema: str) -> str:
    return f"`{_schema_name(target_schema)}`.`station_sales_role_recent_cache`"


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
                    "data_dates": data_dates,
                },
            )
            periods_by_date: dict[date, set[int]] = {item: set() for item in data_dates}
            with target_conn.cursor() as target_cursor:
                target_cursor.execute(station_role_recent_cache_ddl(target_schema))
                target_cursor.execute(f"drop temporary table if exists {temporary}")
                target_cursor.execute(f"create temporary table {temporary} like {target}")
                insert_temp = f"insert into {temporary} ({columns}) values ({values})"
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
                target_cursor.execute(f"delete from {target}")
                target_cursor.execute(
                    f"insert into {target} ({columns}) select {columns} from {temporary}"
                )
                target_cursor.execute(f"drop temporary table {temporary}")
        target_conn.commit()
    except Exception:
        target_conn.rollback()
        raise
    return CacheSyncResult(data_dates=data_dates, row_count=row_count, sync_batch_id=sync_batch_id)
