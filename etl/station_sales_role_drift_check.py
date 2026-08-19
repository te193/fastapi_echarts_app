from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from typing import Iterable

from app.services.station_sales_role import STATION_ROLE_RULE_VERSION, classify_station_sales_role


LABEL_ROLE_MAP = {1301: "star", 1302: "potential", 1303: "dog", 1304: "problem"}
DRIFT_PERIODS = ("7d", "14d", "30d", "90d")


def remote_role_rows_sql(sample_limit: int) -> str:
    safe_limit = max(1, min(int(sample_limit), 20000))
    per_period_limit = max(1, (safe_limit + len(DRIFT_PERIODS) - 1) // len(DRIFT_PERIODS))
    return f"""
    with latest as (
        select max(data_date) as data_date
        from `dws_datasync`.`dws_标签表`
        where label_id in (1301, 1302, 1303, 1304)
          and label_period in ('7d', '14d', '30d', '90d')
    ), sampled as (
        select
            f.data_date,
            f.country,
            f.store,
            f.msku,
            f.label_period,
            f.label_id,
            row_number() over (
                partition by f.label_period
                order by f.country, f.store, f.msku
            ) as sample_row_number
        from `dws_datasync`.`dws_标签表` f
        join latest l on l.data_date = f.data_date
        where f.label_id in (1301, 1302, 1303, 1304)
          and f.label_period in ('7d', '14d', '30d', '90d')
          and f.country is not null
          and f.store is not null
          and f.msku is not null
    )
    select
        f.data_date,
        f.country,
        f.store,
        f.msku,
        f.label_period,
        case f.label_id
            when 1301 then 'star'
            when 1302 then 'potential'
            when 1303 then 'dog'
            when 1304 then 'problem'
        end as role_code
    from sampled f
    where f.sample_row_number <= {per_period_limit}
    order by f.label_period, f.country, f.store, f.msku
    limit {safe_limit}
    """


def _row_key(row: dict) -> tuple:
    return (
        row.get("data_date"),
        row.get("country"),
        row.get("store"),
        row.get("msku"),
        row.get("label_period"),
    )


def compare_role_rows(local_rows: Iterable[dict], remote_rows: Iterable[dict], sample_limit: int = 20) -> dict:
    local_by_key = {_row_key(row): row for row in local_rows}
    remote = list(remote_rows)
    matched = 0
    mismatch = 0
    missing = 0
    samples = []
    by_period: dict[str, Counter] = defaultdict(Counter)
    by_role: dict[str, Counter] = defaultdict(Counter)

    for expected in remote:
        actual = local_by_key.get(_row_key(expected))
        period = str(expected.get("label_period") or "missing")
        role = str(expected.get("role_code") or "missing")
        if actual is None:
            status = "local_missing"
            missing += 1
        elif actual.get("role_code") == expected.get("role_code"):
            status = "matched"
            matched += 1
        else:
            status = "mismatch"
            mismatch += 1
        by_period[period][status] += 1
        by_role[role][status] += 1
        if status != "matched" and len(samples) < max(0, int(sample_limit)):
            samples.append(
                {
                    "data_date": expected.get("data_date"),
                    "country": expected.get("country"),
                    "store": expected.get("store"),
                    "msku": expected.get("msku"),
                    "label_period": expected.get("label_period"),
                    "remote_role": expected.get("role_code"),
                    "local_role": actual.get("role_code") if actual else None,
                    "status": status,
                }
            )

    total = len(remote)
    return {
        "sample_count": total,
        "matched_count": matched,
        "mismatch_count": mismatch,
        "local_missing_count": missing,
        "match_rate": matched / total if total else 0.0,
        "missing_rate": missing / total if total else 0.0,
        "by_period": {key: dict(value) for key, value in by_period.items()},
        "by_role": {key: dict(value) for key, value in by_role.items()},
        "mismatch_samples": samples,
    }


def _load_remote_rows(source_conn, sample_limit: int) -> list[dict]:
    with source_conn.cursor() as cursor:
        cursor.execute(remote_role_rows_sql(sample_limit))
        return list(cursor.fetchall())


def _load_local_rows(target_conn, target_schema: str, remote_rows: list[dict]) -> list[dict]:
    if not remote_rows:
        return []
    performance = f"`{target_schema}`.`dashboard_product_performance_daily`"
    with target_conn.cursor() as cursor:
        cursor.execute("drop temporary table if exists tmp_station_role_drift_keys")
        cursor.execute(
            """
            create temporary table tmp_station_role_drift_keys (
                data_date date not null,
                country varchar(64) not null,
                store varchar(255) not null,
                msku varchar(255) not null,
                label_period varchar(8) not null,
                period_days smallint not null,
                primary key (data_date, country, store, msku, label_period)
            ) engine=InnoDB
            """
        )
        cursor.executemany(
            """
            insert ignore into tmp_station_role_drift_keys
                (data_date, country, store, msku, label_period, period_days)
            values (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    row["data_date"], row["country"], row["store"], row["msku"],
                    row["label_period"], int(str(row["label_period"]).removesuffix("d")),
                )
                for row in remote_rows
            ],
        )
        cursor.execute(
            f"""
            select
                k.data_date,
                k.country,
                k.store,
                k.msku,
                k.label_period,
                k.period_days,
                coalesce(sum(p.sales_qty), 0) as period_sales_qty,
                coalesce(sum(p.sales_amount), 0) as sales_amount,
                coalesce(sum(p.order_gross_profit), 0) as order_gross_profit,
                cast(nullif(substring_index(group_concat(
                    case when p.ranking > 0 then p.ranking end
                    order by p.dt_date desc, p.ranking asc separator ','
                ), ',', 1), '') as unsigned) as small_rank
            from tmp_station_role_drift_keys k
            left join {performance} p
              on p.country = k.country
             and p.seller_name_new = k.store
             and p.seller_sku_adj = k.msku
             and p.dt_date between date_sub(k.data_date, interval (k.period_days - 1) day) and k.data_date
            group by k.data_date, k.country, k.store, k.msku, k.label_period, k.period_days
            """
        )
        metric_rows = list(cursor.fetchall())
        cursor.execute("drop temporary table if exists tmp_station_role_drift_keys")

    local_rows = []
    for row in metric_rows:
        sales_amount = float(row.get("sales_amount") or 0)
        margin = float(row.get("order_gross_profit") or 0) / sales_amount if sales_amount else None
        role = classify_station_sales_role(
            float(row.get("period_sales_qty") or 0) / int(row["period_days"]),
            margin,
            row.get("small_rank"),
        )
        local_rows.append({**row, "role_code": role["code"]})
    return local_rows


def _ensure_audit_table(target_conn, target_schema: str) -> None:
    with target_conn.cursor() as cursor:
        cursor.execute(
            f"""
            create table if not exists `{target_schema}`.`station_sales_role_drift_audit` (
                id bigint unsigned not null auto_increment,
                data_date date null,
                checked_at datetime not null default current_timestamp,
                sample_count int not null,
                matched_count int not null,
                mismatch_count int not null,
                local_missing_count int not null,
                match_rate decimal(10,6) not null,
                missing_rate decimal(10,6) not null,
                threshold decimal(10,6) not null,
                status varchar(16) not null,
                rule_version varchar(64) not null,
                breakdown_json json null,
                mismatch_samples_json json null,
                primary key (id),
                key idx_data_date (data_date, checked_at)
            ) engine=InnoDB default charset=utf8mb4
            """
        )


def run_station_sales_role_drift_check(
    source_conn,
    target_conn,
    target_schema: str,
    sample_limit: int = 4000,
    match_threshold: float = 0.95,
) -> dict:
    remote_rows = _load_remote_rows(source_conn, sample_limit)
    local_rows = _load_local_rows(target_conn, target_schema, remote_rows)
    result = compare_role_rows(local_rows, remote_rows)
    result["data_date"] = remote_rows[0]["data_date"] if remote_rows else None
    result["rule_version"] = STATION_ROLE_RULE_VERSION
    result["status"] = "ok" if result["sample_count"] and result["match_rate"] >= match_threshold else "warning"
    _ensure_audit_table(target_conn, target_schema)
    with target_conn.cursor() as cursor:
        cursor.execute(
            f"""
            insert into `{target_schema}`.`station_sales_role_drift_audit` (
                data_date, sample_count, matched_count, mismatch_count, local_missing_count,
                match_rate, missing_rate, threshold, status, rule_version,
                breakdown_json, mismatch_samples_json
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result["data_date"], result["sample_count"], result["matched_count"],
                result["mismatch_count"], result["local_missing_count"], result["match_rate"],
                result["missing_rate"], match_threshold, result["status"], STATION_ROLE_RULE_VERSION,
                json.dumps({"by_period": result["by_period"], "by_role": result["by_role"]}, ensure_ascii=False, default=str),
                json.dumps(result["mismatch_samples"], ensure_ascii=False, default=str),
            ),
        )
    target_conn.commit()
    return result
