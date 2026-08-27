from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from app.services.stockout_historical_operating import RULE_VERSION, evaluate_stockout_history
from etl.dashboard_daily_update import build_schema_config, connect_target, render_sql
from etl.replenishment_update import apply_database_ini_env


TABLE_NAME = "etl_datasync_test.dashboard_stockout_historical_operating_snapshot"
CURRENT_STOCKOUT_LABEL_ID = 304

CREATE_TABLE_SQL = """
create table if not exists etl_datasync_test.dashboard_stockout_historical_operating_snapshot (
    data_date date not null,
    scope_mode varchar(24) not null,
    country_category varchar(64) not null,
    store varchar(128) not null,
    msku varchar(255) not null,
    country varchar(64) not null default '',
    current_gate_status varchar(48) not null,
    current_gate_reason varchar(128) not null default '',
    current_oos_flag tinyint(1) not null default 0,
    oos_start_date date null,
    oos_start_method varchar(96) not null,
    oos_start_confidence varchar(48) not null,
    observed_oos_since_date date null,
    minimum_current_oos_days int not null default 0,
    history_window_start date null,
    history_window_end date null,
    history_span_days int not null default 0,
    expected_calendar_days int not null default 0,
    observed_daily_days int not null default 0,
    daily_coverage_rate decimal(10,6) not null default 0,
    effective_operating_days int not null default 0,
    effective_operating_weeks int not null default 0,
    historical_evaluable_status varchar(48) not null,
    historical_evaluable_reason varchar(128) not null,
    role_7d varchar(32) null,
    role_14d varchar(32) null,
    role_30d varchar(32) null,
    role_90d varchar(32) null,
    pre_oos_role varchar(32) null,
    role_evidence_status varchar(40) not null default 'no_valid_role',
    role_source_date date null,
    valid_window_count int not null default 0,
    dominant_role varchar(32) null,
    dominant_role_share decimal(10,6) not null default 0,
    role_switch_rate decimal(10,6) not null default 0,
    recent_trend varchar(40) null,
    daily_sales_trend varchar(40) null,
    margin_trend varchar(40) null,
    combined_label_code varchar(128) null,
    combined_label varchar(128) null,
    auxiliary_json json null,
    inventory_boundary_status varchar(48) null,
    historical_operating_level varchar(40) null,
    historical_stability varchar(40) null,
    role_stability varchar(24) null,
    sales_stability varchar(24) null,
    margin_stability varchar(24) null,
    historical_role_pattern varchar(40) null,
    pre_oos_role_change varchar(40) null,
    low_stock_constrained tinyint(1) not null default 0,
    inventory_sales_conflict_flag tinyint(1) not null default 0,
    missing_date_gap_flag tinyint(1) not null default 0,
    few_selling_days_flag tinyint(1) not null default 0,
    single_day_concentrated_flag tinyint(1) not null default 0,
    extreme_single_day_concentrated_flag tinyint(1) not null default 0,
    event_boundary_incomplete_flag tinyint(1) not null default 0,
    one_day_recovery_then_oos_flag tinyint(1) not null default 0,
    evidence_json json not null,
    rule_version varchar(96) not null,
    calculated_at datetime not null,
    primary key (data_date, scope_mode, country_category, store, msku, country),
    key idx_date_scope_level (data_date, scope_mode, historical_operating_level),
    key idx_date_scope_stability (data_date, scope_mode, historical_stability),
    key idx_date_scope_pattern (data_date, scope_mode, historical_role_pattern),
    key idx_date_scope_change (data_date, scope_mode, pre_oos_role_change),
    key idx_date_store_msku (data_date, store, msku),
    key idx_date_scope_country (data_date, scope_mode, country)
) engine=InnoDB default charset=utf8mb4 comment='当前断货商品的断货前历史经营每日结果快照';
"""
ENSURE_COUNTRY_INDEX_SQL = f"alter table {TABLE_NAME} add index idx_date_scope_country (data_date, scope_mode, country)"
ENSURE_V3_COLUMN_SQL = (
    f"alter table {TABLE_NAME} add column pre_oos_role varchar(32) null after role_90d",
    f"alter table {TABLE_NAME} add column role_evidence_status varchar(40) not null default 'no_valid_role' after pre_oos_role",
    f"alter table {TABLE_NAME} add column role_source_date date null after role_evidence_status",
    f"alter table {TABLE_NAME} add column valid_window_count int not null default 0 after role_source_date",
    f"alter table {TABLE_NAME} add column dominant_role varchar(32) null after valid_window_count",
    f"alter table {TABLE_NAME} add column dominant_role_share decimal(10,6) not null default 0 after dominant_role",
    f"alter table {TABLE_NAME} add column role_switch_rate decimal(10,6) not null default 0 after dominant_role_share",
    f"alter table {TABLE_NAME} add column recent_trend varchar(40) null after role_switch_rate",
    f"alter table {TABLE_NAME} add column daily_sales_trend varchar(40) null after recent_trend",
    f"alter table {TABLE_NAME} add column margin_trend varchar(40) null after daily_sales_trend",
    f"alter table {TABLE_NAME} add column combined_label_code varchar(128) null after margin_trend",
    f"alter table {TABLE_NAME} add column combined_label varchar(128) null after combined_label_code",
    f"alter table {TABLE_NAME} add column auxiliary_json json null after combined_label",
    f"alter table {TABLE_NAME} add column inventory_boundary_status varchar(48) null after auxiliary_json",
)

SNAPSHOT_COLUMNS = (
    "data_date", "scope_mode", "country_category", "store", "msku", "country",
    "current_gate_status", "current_gate_reason", "current_oos_flag", "oos_start_date",
    "oos_start_method", "oos_start_confidence", "observed_oos_since_date",
    "minimum_current_oos_days", "history_window_start", "history_window_end",
    "history_span_days", "expected_calendar_days", "observed_daily_days", "daily_coverage_rate",
    "effective_operating_days", "effective_operating_weeks", "historical_evaluable_status",
    "historical_evaluable_reason", "role_7d", "role_14d", "role_30d", "role_90d",
    "pre_oos_role", "role_evidence_status", "role_source_date", "valid_window_count",
    "dominant_role", "dominant_role_share", "role_switch_rate", "recent_trend",
    "daily_sales_trend", "margin_trend", "combined_label_code", "combined_label",
    "auxiliary_json", "inventory_boundary_status",
    "historical_operating_level", "historical_stability", "role_stability", "sales_stability",
    "margin_stability", "historical_role_pattern", "pre_oos_role_change", "low_stock_constrained",
    "inventory_sales_conflict_flag", "missing_date_gap_flag", "few_selling_days_flag",
    "single_day_concentrated_flag", "extreme_single_day_concentrated_flag",
    "event_boundary_incomplete_flag", "one_day_recovery_then_oos_flag", "evidence_json",
    "rule_version", "calculated_at",
)
INSERT_SQL = f"""
insert into {TABLE_NAME} ({', '.join(SNAPSHOT_COLUMNS)})
values ({', '.join(f'%({column})s' for column in SNAPSHOT_COLUMNS)})
"""


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("country_category") or ""),
        str(row.get("store", row.get("seller_name_new")) or ""),
        str(row.get("msku", row.get("seller_sku_adj")) or ""),
    )


def _performance_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dt_date": row["dt_date"],
        "country_category": str(row.get("country_category") or ""),
        "country": str(row.get("country") or ""),
        "store": str(row.get("store", row.get("seller_name_new")) or ""),
        "msku": str(row.get("msku", row.get("seller_sku_adj")) or ""),
        "sales_qty": float(row.get("sales_qty") or 0),
        "sales_amount": float(row.get("sales_amount") or 0),
        "order_gross_profit": float(row.get("order_gross_profit") or 0),
        "fba_available": None if row.get("fba_available", row.get("afn_fulfillable_quantity")) is None else float(row.get("fba_available", row.get("afn_fulfillable_quantity"))),
        "ranking": row.get("ranking"),
    }


def _inventory_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dt_date": row.get("dt_date", row.get("snapshot_date")),
        "country_category": str(row.get("country_category") or ""),
        "country": str(row.get("country") or ""),
        "store": str(row.get("store", row.get("seller_name_new")) or ""),
        "msku": str(row.get("msku", row.get("seller_sku_adj")) or ""),
        "fba_available": (
            None
            if row.get("fba_available", row.get("afn_fulfillable_quantity")) is None
            else float(row.get("fba_available", row.get("afn_fulfillable_quantity")))
        ),
    }


def _business_daily_rows(
    performance_rows: Iterable[Mapping[str, Any]],
    inventory_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    performance_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for source in performance_rows:
        row = _performance_row(source)
        performance_by_day[row["dt_date"]].append(row)
    inventory_by_day: dict[date, list[float]] = defaultdict(list)
    for source in inventory_rows:
        row = _inventory_row(source)
        if row["fba_available"] is not None:
            inventory_by_day[row["dt_date"]].append(row["fba_available"])
    result = []
    for day in sorted(inventory_by_day):
        items = performance_by_day.get(day, [])
        result.append(
            {
                "dt_date": day,
                "sales_qty": sum(row["sales_qty"] for row in items),
                "sales_amount": sum(row["sales_amount"] for row in items),
                "order_gross_profit": sum(row["order_gross_profit"] for row in items),
                "fba_available": max(inventory_by_day[day]),
                "ranking": None,
            }
        )
    return result


def _country_rows_with_business_inventory(
    rows: Iterable[Mapping[str, Any]], business_rows: Iterable[Mapping[str, Any]], country: str
) -> list[dict[str, Any]]:
    performance_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = _performance_row(source)
        if row["country"] == country:
            performance_by_day[row["dt_date"]].append(row)
    result = []
    for business_row in business_rows:
        items = performance_by_day.get(business_row["dt_date"], [])
        rankings = [row["ranking"] for row in items if row["ranking"] is not None]
        result.append(
            {
                "dt_date": business_row["dt_date"],
                "sales_qty": sum(row["sales_qty"] for row in items),
                "sales_amount": sum(row["sales_amount"] for row in items),
                "order_gross_profit": sum(row["order_gross_profit"] for row in items),
                "fba_available": business_row["fba_available"],
                "ranking": rankings[-1] if rankings else None,
            }
        )
    return result


def _snapshot_record(
    identity: Mapping[str, Any], result: Mapping[str, Any], *, data_date: date, scope_mode: str, country: str
) -> dict[str, Any]:
    periods = result.get("period_roles") or {}
    flags = result.get("sales_concentration_flags") or {}
    evidence = dict(result)
    evidence["inventory_scope"] = "inherited_business_unit" if scope_mode == "country" else "business_unit_aggregate"
    auxiliary = {
        "dominant_role": result.get("dominant_role"),
        "historical_stability": result.get("confirmed_historical_stability"),
        "role_evidence_status": result.get("role_evidence_status"),
        "role_source_date": result.get("role_source_date"),
        "auxiliary_metric": result.get("auxiliary_metric") or "",
    }
    return {
        "data_date": data_date,
        "scope_mode": scope_mode,
        "country_category": identity["country_category"],
        "store": identity["store"],
        "msku": identity["msku"],
        "country": country,
        "current_gate_status": result.get("current_gate_status") or "not_evaluable",
        "current_gate_reason": result.get("current_gate_reason") or "",
        "current_oos_flag": int(bool(result.get("current_oos_flag"))),
        "oos_start_date": result.get("oos_start_date"),
        "oos_start_method": result.get("oos_start_method") or "",
        "oos_start_confidence": result.get("oos_start_confidence") or "",
        "observed_oos_since_date": result.get("observed_oos_since_date"),
        "minimum_current_oos_days": int(result.get("minimum_current_oos_days") or 0),
        "history_window_start": result.get("history_window_start"),
        "history_window_end": result.get("history_window_end"),
        "history_span_days": int(result.get("history_span_days") or 0),
        "expected_calendar_days": int(result.get("expected_calendar_days") or 0),
        "observed_daily_days": int(result.get("observed_daily_days") or 0),
        "daily_coverage_rate": float(result.get("daily_coverage_rate") or 0),
        "effective_operating_days": int(result.get("effective_operating_days") or 0),
        "effective_operating_weeks": int(result.get("effective_operating_weeks") or 0),
        "historical_evaluable_status": result.get("historical_evaluable_status") or "historical_evidence_insufficient",
        "historical_evaluable_reason": result.get("historical_evaluable_reason") or "",
        "role_7d": (periods.get("7d") or {}).get("role"),
        "role_14d": (periods.get("14d") or {}).get("role"),
        "role_30d": (periods.get("30d") or {}).get("role"),
        "role_90d": (periods.get("90d") or {}).get("role"),
        "pre_oos_role": result.get("pre_oos_role"),
        "role_evidence_status": result.get("role_evidence_status") or "no_valid_role",
        "role_source_date": result.get("role_source_date"),
        "valid_window_count": int(result.get("valid_window_count") or 0),
        "dominant_role": result.get("dominant_role"),
        "dominant_role_share": float(result.get("dominant_role_share") or 0),
        "role_switch_rate": float(result.get("role_switch_rate") or 0),
        "recent_trend": result.get("recent_trend"),
        "daily_sales_trend": result.get("daily_sales_trend"),
        "margin_trend": result.get("margin_trend"),
        "combined_label_code": result.get("combined_label_code"),
        "combined_label": result.get("combined_label"),
        "auxiliary_json": json.dumps(auxiliary, ensure_ascii=False, default=str, separators=(",", ":")),
        "inventory_boundary_status": result.get("oos_start_confidence"),
        "historical_operating_level": result.get("historical_operating_level"),
        "historical_stability": result.get("confirmed_historical_stability"),
        "role_stability": result.get("role_stability"),
        "sales_stability": result.get("sales_stability"),
        "margin_stability": result.get("margin_stability"),
        "historical_role_pattern": result.get("historical_role_pattern"),
        "pre_oos_role_change": result.get("pre_oos_role_change"),
        "low_stock_constrained": int(bool(result.get("low_stock_constrained"))),
        "inventory_sales_conflict_flag": int(bool(result.get("inventory_sales_conflict_days"))),
        "missing_date_gap_flag": int(bool(result.get("missing_date_gap_count"))),
        "few_selling_days_flag": int(bool(flags.get("few_selling_days"))),
        "single_day_concentrated_flag": int(bool(flags.get("single_day_concentrated"))),
        "extreme_single_day_concentrated_flag": int(bool(flags.get("extreme_single_day_concentrated"))),
        "event_boundary_incomplete_flag": int(bool(result.get("event_boundary_incomplete"))),
        "one_day_recovery_then_oos_flag": int(bool(result.get("one_day_recovery_then_oos"))),
        "evidence_json": json.dumps(evidence, ensure_ascii=False, default=str, separators=(",", ":")),
        "rule_version": RULE_VERSION,
        "calculated_at": datetime.now(),
    }


def build_snapshot_rows(
    stockout_facts: Iterable[Mapping[str, Any]],
    performance_rows: Iterable[Mapping[str, Any]],
    inventory_rows: Iterable[Mapping[str, Any]],
    *,
    data_date: date,
) -> list[dict[str, Any]]:
    stockouts = {_key(row): {"country_category": _key(row)[0], "store": _key(row)[1], "msku": _key(row)[2]} for row in stockout_facts}
    grouped_performance: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in performance_rows:
        row = _performance_row(source)
        if _key(row) in stockouts:
            grouped_performance[_key(row)].append(row)
    grouped_inventory: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in inventory_rows:
        row = _inventory_row(source)
        if _key(row) in stockouts:
            grouped_inventory[_key(row)].append(row)
    snapshots = []
    for key, identity in sorted(stockouts.items()):
        source_rows = grouped_performance.get(key, [])
        business_rows = _business_daily_rows(
            source_rows,
            grouped_inventory.get(key, []),
        )
        business_result = evaluate_stockout_history(
            business_rows,
            current_date=data_date,
            current_gate_status="evaluable",
            current_gate_reason="",
            scope_mode="business_unit",
            current_oos_confirmed=True,
        )
        snapshots.append(_snapshot_record(identity, business_result, data_date=data_date, scope_mode="business_unit", country=""))
        for country in sorted({row["country"] for row in source_rows if row["country"]}):
            country_result = evaluate_stockout_history(
                _country_rows_with_business_inventory(source_rows, business_rows, country),
                current_date=data_date,
                current_gate_status="evaluable",
                current_gate_reason="",
                scope_mode="country",
                current_oos_confirmed=True,
            )
            snapshots.append(
                _snapshot_record(
                    identity,
                    country_result,
                    data_date=data_date,
                    scope_mode="country",
                    country=country,
                )
            )
    return snapshots


def replace_snapshot_date(conn, data_date: date, rows: list[dict[str, Any]]) -> None:
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"delete from {TABLE_NAME} where data_date = %(data_date)s", {"data_date": data_date})
            if rows:
                cursor.executemany(INSERT_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_result_table(conn, schemas: Mapping[str, str]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(render_sql(CREATE_TABLE_SQL, schemas))
        for statement in ENSURE_V3_COLUMN_SQL:
            try:
                cursor.execute(statement)
            except Exception as exc:
                if not exc.args or exc.args[0] != 1060:
                    raise
        try:
            cursor.execute(ENSURE_COUNTRY_INDEX_SQL)
        except Exception as exc:
            if not exc.args or exc.args[0] != 1061:
                raise
    conn.commit()


def _load_dates(conn) -> tuple[date | None, date | None, date | None]:
    with conn.cursor() as cursor:
        cursor.execute("select max(data_date) as max_date from etl_datasync_test.dashboard_label_fact_snapshot")
        label_date = (cursor.fetchone() or {}).get("max_date")
        cursor.execute("select max(dt_date) as max_date from etl_datasync_test.dashboard_product_performance_daily")
        performance_date = (cursor.fetchone() or {}).get("max_date")
        cursor.execute("select max(snapshot_date) as max_date from etl_datasync_test.dashboard_inventory_daily_snapshot")
        inventory_date = (cursor.fetchone() or {}).get("max_date")
    return label_date, performance_date, inventory_date


def _source_partition_presence(conn, data_date: date) -> tuple[bool, bool, bool]:
    with conn.cursor() as cursor:
        cursor.execute(
            "select exists(select 1 from etl_datasync_test.dashboard_label_fact_snapshot where data_date = %(data_date)s limit 1) as present",
            {"data_date": data_date},
        )
        label_present = bool((cursor.fetchone() or {}).get("present"))
        cursor.execute(
            "select exists(select 1 from etl_datasync_test.dashboard_product_performance_daily where dt_date = %(data_date)s limit 1) as present",
            {"data_date": data_date},
        )
        performance_present = bool((cursor.fetchone() or {}).get("present"))
        cursor.execute(
            "select exists(select 1 from etl_datasync_test.dashboard_inventory_daily_snapshot where snapshot_date = %(data_date)s limit 1) as present",
            {"data_date": data_date},
        )
        inventory_present = bool((cursor.fetchone() or {}).get("present"))
    return label_present, performance_present, inventory_present


def validate_source_dates(
    *,
    target_date: date,
    label_max_date: date | None,
    performance_max_date: date | None,
    inventory_max_date: date | None,
    label_partition_exists: bool,
    performance_partition_exists: bool,
    inventory_partition_exists: bool,
    allow_latest_mismatch: bool = False,
) -> None:
    if label_max_date is None or performance_max_date is None or inventory_max_date is None:
        raise RuntimeError("stockout historical operating source tables have no available date")
    if len({label_max_date, performance_max_date, inventory_max_date}) > 1 and not allow_latest_mismatch:
        raise RuntimeError(
            "latest source date mismatch: "
            f"label={label_max_date}, performance={performance_max_date}, inventory={inventory_max_date}"
        )
    latest_common_date = min(label_max_date, performance_max_date, inventory_max_date)
    if target_date > latest_common_date:
        raise RuntimeError(f"target source date is newer than latest ready date: target={target_date}, latest={latest_common_date}")
    if not label_partition_exists or not performance_partition_exists or not inventory_partition_exists:
        raise RuntimeError(
            "target source partition missing: "
            f"target={target_date}, label={label_partition_exists}, "
            f"performance={performance_partition_exists}, inventory={inventory_partition_exists}"
        )


def _load_facts(conn, data_date: date) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select data_date, country_category, country, store, msku, label_id, label_period,
                   uncompress(evidence_blob) as evidence_json
            from etl_datasync_test.dashboard_label_fact_snapshot
            where data_date = %(data_date)s
              and label_id = 304 and label_period = 'current'
              and msku not like 'Amazon.Found.%%'
            """,
            {"data_date": data_date},
        )
        return list(cursor.fetchall())


def _load_performance(conn, data_date: date) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select p.dt_date, p.country_category, p.country,
                   p.seller_name_new as store, p.seller_sku_adj as msku,
                   p.sales_qty, p.sales_amount, p.order_gross_profit,
                   p.ranking
            from etl_datasync_test.dashboard_product_performance_daily p
            inner join (
                select distinct country_category, store, msku
                from etl_datasync_test.dashboard_label_fact_snapshot
                where data_date = %(data_date)s and label_id = 304 and label_period = 'current'
            ) s on s.country_category = p.country_category
               and s.store = p.seller_name_new and s.msku = p.seller_sku_adj
            where p.dt_date between '2026-01-01' and %(data_date)s
            order by p.country_category, p.seller_name_new, p.seller_sku_adj, p.dt_date, p.country
            """,
            {"data_date": data_date},
        )
        return list(cursor.fetchall())


def _load_inventory(conn, data_date: date) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select i.snapshot_date as dt_date, i.country_category,
                   i.seller_name_new as store, i.seller_sku_adj as msku,
                   max(i.afn_fulfillable_quantity) as fba_available
            from etl_datasync_test.dashboard_inventory_daily_snapshot i
            inner join (
                select distinct country_category, store, msku
                from etl_datasync_test.dashboard_label_fact_snapshot
                where data_date = %(data_date)s and label_id = 304 and label_period = 'current'
            ) s on s.country_category = i.country_category
               and s.store = i.seller_name_new and s.msku = i.seller_sku_adj
            where i.snapshot_date between '2026-01-01' and %(data_date)s
            group by i.snapshot_date, i.country_category, i.seller_name_new, i.seller_sku_adj
            order by i.country_category, i.seller_name_new, i.seller_sku_adj, i.snapshot_date
            """,
            {"data_date": data_date},
        )
        return list(cursor.fetchall())


def run_update(conn, *, data_date: date, allow_latest_mismatch: bool = False) -> list[dict[str, Any]]:
    label_date, performance_date, inventory_date = _load_dates(conn)
    label_partition, performance_partition, inventory_partition = _source_partition_presence(conn, data_date)
    validate_source_dates(
        target_date=data_date,
        label_max_date=label_date,
        performance_max_date=performance_date,
        inventory_max_date=inventory_date,
        label_partition_exists=label_partition,
        performance_partition_exists=performance_partition,
        inventory_partition_exists=inventory_partition,
        allow_latest_mismatch=allow_latest_mismatch,
    )
    facts = _load_facts(conn, data_date)
    stockouts = [fact for fact in facts if int(fact.get("label_id") or 0) == CURRENT_STOCKOUT_LABEL_ID and fact.get("label_period") == "current"]
    rows = build_snapshot_rows(
        stockouts,
        _load_performance(conn, data_date),
        _load_inventory(conn, data_date),
        data_date=data_date,
    )
    expected_business_units = len({_key(fact) for fact in stockouts})
    actual_business_units = sum(row["scope_mode"] == "business_unit" for row in rows)
    if actual_business_units != expected_business_units:
        raise RuntimeError(
            f"stockout result reconciliation failed: label_304={expected_business_units}, result={actual_business_units}"
        )
    replace_snapshot_date(conn, data_date, rows)
    return rows


def resolve_target_date(data_date_value: str, biz_date_value: str, latest_label_date: date | None) -> date | None:
    value = data_date_value or biz_date_value
    return date.fromisoformat(value) if value else latest_label_date


def main() -> None:
    parser = argparse.ArgumentParser(description="Update current-stockout historical operating snapshots.")
    parser.add_argument("--data-date", help="Snapshot date, default: latest common source date.")
    parser.add_argument("--biz-date", help="Daily runner business date; used when --data-date is absent.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-source-max-mismatch",
        action="store_true",
        help="Allow an explicit historical backfill when both target partitions exist but source maxima differ.",
    )
    args, _unknown = parser.parse_known_args()
    apply_database_ini_env()
    schemas = build_schema_config()
    conn = connect_target()
    try:
        label_date, performance_date, inventory_date = _load_dates(conn)
        target_date = resolve_target_date(args.data_date or "", args.biz_date or "", label_date)
        if target_date is None or performance_date is None or inventory_date is None:
            raise RuntimeError("stockout historical operating source tables have no available date")
        if args.dry_run:
            print(
                "stockout historical operating plan: "
                f"data_date={target_date}, label={label_date}, "
                f"performance={performance_date}, inventory={inventory_date}"
            )
            return
        ensure_result_table(conn, schemas)
        rows = run_update(
            conn,
            data_date=target_date,
            allow_latest_mismatch=args.allow_source_max_mismatch,
        )
        business_count = sum(row["scope_mode"] == "business_unit" for row in rows)
        country_count = sum(row["scope_mode"] == "country" for row in rows)
        print(f"[success] stockout_historical_operating: data_date={target_date} business_units={business_count} countries={country_count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
