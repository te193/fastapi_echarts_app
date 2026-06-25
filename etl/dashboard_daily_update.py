from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

try:
    import pymysql
except ImportError as exc:  # pragma: no cover - operator-facing guard
    raise SystemExit("Missing dependency: pip install pymysql") from exc

from etl.price_review_update import PriceReviewStep, execute_price_review_step


DEFAULT_PERIOD_DAYS = 90
DEFAULT_PRODUCT_REFRESH_DAYS = 50
PERIOD_SNAPSHOT_RETENTION_DAYS = 2
MATRIX_ALL_VALUE = "__ALL__"
ANNUAL_SALES_GOAL = 135000000
ANNUAL_MARGIN_GOAL = 0.20
ANNUAL_SALES_GOAL_BUFFER = 1.01
DEFAULT_STEP_ORDER = [
    "product_performance_daily",
    "monthly_goal_actual_snapshot",
    "goal_dimension_snapshot",
    "annual_goal_snapshot",
    "restock_snapshot",
    "inventory_snapshot",
    "inventory_weekly_snapshot",
    "inventory_weekly_remote_snapshot",
    "listing_price_snapshot",
    "limit_price_snapshot",
    "period_preset_snapshots",
    "alert_comparison_snapshots",
    "alert_monthly_metric_snapshots",
    "opportunity_comparison_snapshots",
    "price_review_source_load",
    "price_review_tracking",
]


@dataclass(frozen=True)
class SqlStep:
    name: str
    statements: tuple[str, ...]


@dataclass(frozen=True)
class SourceLoadStep:
    name: str
    delete_statement: str
    source_select_statement: str
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True)
class PeriodPresetStep:
    name: str


@dataclass(frozen=True)
class AlertComparisonStep:
    name: str


@dataclass(frozen=True)
class AlertMonthlyMetricStep:
    name: str


@dataclass(frozen=True)
class OpportunityComparisonStep:
    name: str


@dataclass(frozen=True)
class SchemaConfig:
    target_schema: str
    etl_source_schema: str
    dwd_source_schema: str
    pricing_source_schema: str


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def default_biz_date() -> date:
    return date.today() - timedelta(days=1)


def connect_with_retry(label: str, **kwargs):
    max_attempts = int(os.getenv("DASHBOARD_DB_CONNECT_ATTEMPTS", "10"))
    permanent_error_codes = {1044, 1045, 1049}
    for attempt in range(1, max_attempts + 1):
        try:
            return pymysql.connect(**kwargs)
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] in permanent_error_codes:
                raise
            if attempt == max_attempts:
                raise
            print(f"[warn] {label} connection failed: {exc}; retrying...", file=sys.stderr)
            time.sleep(min(30, 3 * attempt))


def connect_target():
    return connect_with_retry(
        "target",
        host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
        password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        database=os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test")) or None,
        charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=20,
        read_timeout=3600,
        write_timeout=3600,
    )


def connect_source():
    return connect_with_retry(
        "source",
        host=os.getenv("DASHBOARD_SOURCE_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_SOURCE_DB_PORT", "3306")),
        user=os.getenv("DASHBOARD_SOURCE_DB_USER", ""),
        password=os.getenv("DASHBOARD_SOURCE_DB_PASSWORD", ""),
        database=os.getenv("DASHBOARD_SOURCE_DB_NAME", "") or None,
        charset=os.getenv("DASHBOARD_SOURCE_DB_CHARSET", os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4")),
        cursorclass=pymysql.cursors.SSDictCursor,
        autocommit=True,
        connect_timeout=20,
        read_timeout=3600,
        write_timeout=3600,
    )


def ensure_live_source_connection(source_conn) -> None:
    source_conn.ping(reconnect=True)


def source_load_retry_attempts() -> int:
    raw_attempts = os.getenv("DASHBOARD_SOURCE_LOAD_ATTEMPTS", "2")
    try:
        return max(1, int(raw_attempts))
    except ValueError:
        return 2


def clean_identifier(value: str, fallback: str) -> str:
    name = (value or fallback).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"Unsafe schema name: {name!r}")
    return name


def build_schema_config() -> SchemaConfig:
    default_database = os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "")) or "etl_datasync"
    return SchemaConfig(
        target_schema=clean_identifier(os.getenv("DASHBOARD_TARGET_SCHEMA", default_database), "etl_datasync"),
        etl_source_schema=clean_identifier(os.getenv("DASHBOARD_ETL_SOURCE_SCHEMA", "etl_datasync"), "etl_datasync"),
        dwd_source_schema=clean_identifier(os.getenv("DASHBOARD_DWD_SOURCE_SCHEMA", "dwd_datasync"), "dwd_datasync"),
        pricing_source_schema=clean_identifier(os.getenv("DASHBOARD_PRICING_SOURCE_SCHEMA", "temporary_dwd"), "temporary_dwd"),
    )


def render_sql(sql: str, schemas: SchemaConfig) -> str:
    rendered = sql
    rendered = rendered.replace("create schema if not exists etl_datasync", f"create schema if not exists {schemas.target_schema}")
    rendered = rendered.replace("etl_datasync.dashboard_", f"{schemas.target_schema}.dashboard_")
    rendered = rendered.replace("etl_datasync.etl_dispose_", f"{schemas.etl_source_schema}.etl_dispose_")
    rendered = rendered.replace("dwd_datasync.", f"{schemas.dwd_source_schema}.")
    rendered = rendered.replace("temporary_APP.", f"{schemas.pricing_source_schema}.")
    rendered = rendered.replace("temporary_dwd.", f"{schemas.pricing_source_schema}.")
    return rendered


CREATE_SCHEMA_SQL = "create schema if not exists etl_datasync default character set utf8mb4;"

CREATE_LOG_TABLE_SQL = """
create table if not exists etl_datasync.dashboard_etl_task_log (
    id bigint unsigned not null auto_increment primary key,
    task_name varchar(128) not null,
    biz_date date null,
    snapshot_date date null,
    period_start date null,
    period_end date null,
    status varchar(32) not null,
    affected_rows bigint not null default 0,
    started_at datetime not null,
    finished_at datetime not null,
    error_message text null,
    created_at datetime not null default current_timestamp,
    key idx_task_day (task_name, biz_date, snapshot_date),
    key idx_status_created (status, created_at)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_PRODUCT_DAILY_SQL = """
create table if not exists etl_datasync.dashboard_product_performance_daily (
    dt_year int not null,
    dt_week int not null,
    dt_month int not null,
    dt_date date not null,
    item_key varchar(512) not null,
    country varchar(64) not null,
    country_category varchar(64) not null,
    local_sku varchar(128) null,
    seller_name varchar(255) null,
    seller_name_new varchar(128) not null,
    seller_sku_adj varchar(128) not null,
    sales_qty decimal(18,4) not null default 0,
    sales_amount decimal(18,4) not null default 0,
    sales_amount_ex_tax decimal(18,4) not null default 0,
    raw_order_gross_profit decimal(18,4) not null default 0,
    order_gross_profit decimal(18,4) not null default 0,
    abnormal_flag_count int not null default 0,
    settlement_gross_profit decimal(18,4) not null default 0,
    afn_fulfillable_quantity decimal(18,4) not null default 0,
    ad_spend decimal(18,4) not null default 0,
    ad_orders decimal(18,4) not null default 0,
    ad_sales decimal(18,4) not null default 0,
    ad_clicks decimal(18,4) not null default 0,
    ad_impressions decimal(18,4) not null default 0,
    sessions_total decimal(18,4) not null default 0,
    ranking int not null default 0,
    return_count decimal(18,4) not null default 0,
    return_amount decimal(18,4) not null default 0,
    net_amount decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_day_item (dt_date, item_key),
    key idx_day_store (dt_date, seller_name_new),
    key idx_day_country (dt_date, country),
    key idx_period_group (dt_date, seller_name_new, seller_sku_adj, country_category, country, local_sku),
    key idx_price_review_lookup (seller_name, seller_sku_adj, dt_date),
    key idx_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_RESTOCK_SQL = """
create table if not exists etl_datasync.dashboard_restock_daily_snapshot (
    snapshot_date date not null,
    item_key varchar(512) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    seller_name_new varchar(128) not null,
    local_quantity decimal(18,4) not null default 0,
    purchase_shipping_quantity decimal(18,4) not null default 0,
    purchase_plan_quantity decimal(18,4) not null default 0,
    local_valid_quantity decimal(18,4) not null default 0,
    local_qc_quantity decimal(18,4) not null default 0,
    purchase_cost decimal(18,4) not null default 0,
    transport_cost decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_snapshot_item (snapshot_date, item_key),
    key idx_snapshot_store (snapshot_date, seller_name_new),
    key idx_snapshot_join (snapshot_date, country_category, seller_sku_adj, seller_name_new),
    key idx_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_INVENTORY_SQL = """
create table if not exists etl_datasync.dashboard_inventory_daily_snapshot (
    snapshot_date date not null,
    item_key varchar(512) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    seller_name_new varchar(128) not null,
    total decimal(18,4) not null default 0,
    total_price decimal(18,4) not null default 0,
    available_total decimal(18,4) not null default 0,
    available_price decimal(18,4) not null default 0,
    afn_fulfillable_quantity decimal(18,4) not null default 0,
    reserved_fc_transfers decimal(18,4) not null default 0,
    reserved_fc_processing decimal(18,4) not null default 0,
    reserved_customerorders decimal(18,4) not null default 0,
    afn_unsellable_quantity decimal(18,4) not null default 0,
    afn_inbound_working_quantity decimal(18,4) not null default 0,
    stock_up_num decimal(18,4) not null default 0,
    stock_up_num_price decimal(18,4) not null default 0,
    afn_researching_quantity decimal(18,4) not null default 0,
    total_fulfillable_quantity decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_snapshot_item (snapshot_date, item_key),
    key idx_snapshot_store (snapshot_date, seller_name_new),
    key idx_snapshot_join (snapshot_date, country_category, seller_sku_adj, seller_name_new),
    key idx_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_INVENTORY_WEEKLY_SQL = """
create table if not exists etl_datasync.dashboard_inventory_weekly_snapshot (
    snapshot_date date not null,
    week_start date not null,
    week_end date not null,
    item_key varchar(512) not null,
    country_category varchar(64) not null,
    seller_sku_adj varchar(128) not null,
    seller_name_new varchar(128) not null,
    available_quantity decimal(18,4) not null default 0,
    available_cost decimal(18,4) not null default 0,
    transit_quantity decimal(18,4) not null default 0,
    transit_cost decimal(18,4) not null default 0,
    warehouse_quantity decimal(18,4) not null default 0,
    warehouse_cost decimal(18,4) not null default 0,
    plan_quantity decimal(18,4) not null default 0,
    plan_cost decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (week_start, item_key),
    key idx_snapshot_date (snapshot_date),
    key idx_week_store (week_start, seller_name_new),
    key idx_week_country (week_start, country_category),
    key idx_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_LISTING_PRICE_SQL = """
create table if not exists etl_datasync.dashboard_listing_price_daily_snapshot (
    snapshot_date date not null,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    seller_name varchar(255) null,
    seller_sku varchar(128) not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    price decimal(18,4) null,
    org_currency_icon varchar(64) null,
    price_cny decimal(18,4) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_snapshot_item (snapshot_date, item_key),
    key idx_snapshot_store (snapshot_date, seller_name_new),
    key idx_snapshot_join (snapshot_date, country_category, seller_name_new, country, seller_sku),
    key idx_sku (seller_sku)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_LIMIT_PRICE_SQL = """
create table if not exists etl_datasync.dashboard_limit_price_daily_snapshot (
    snapshot_date date not null,
    item_key varchar(512) not null,
    local_sku varchar(128) null,
    seller_sku varchar(128) not null,
    seller_name_new varchar(128) not null,
    country varchar(64) not null,
    country_category varchar(64) not null,
    shipping_method varchar(64) null,
    target_margin decimal(10,4) null,
    currency varchar(64) null,
    tax_inclusive_price decimal(18,2) null,
    tax_inclusive_price_noad decimal(18,2) null,
    tax_inclusive_price_adj decimal(18,2) null,
    margin_price_35 decimal(18,2) null,
    margin_price_30 decimal(18,2) null,
    margin_price_25 decimal(18,2) null,
    margin_price_20 decimal(18,2) null,
    margin_price_15 decimal(18,2) null,
    margin_price_10 decimal(18,2) null,
    margin_price_5 decimal(18,2) null,
    margin_price_0 decimal(18,2) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_snapshot_item (snapshot_date, item_key),
    key idx_snapshot_store (snapshot_date, seller_name_new),
    key idx_snapshot_join (snapshot_date, country_category, seller_name_new, country, seller_sku, local_sku),
    key idx_sku (seller_sku)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_PERIOD_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_product_period_snapshot (
    snapshot_date date not null,
    period_start date not null,
    period_end date not null,
    item_key varchar(512) not null,
    stat_period varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_name varchar(255) null,
    seller_sku_adj varchar(128) not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    local_sku varchar(128) null,
    sales_qty decimal(18,4) not null default 0,
    sales_amount decimal(18,4) not null default 0,
    sales_amount_ex_tax decimal(18,4) not null default 0,
    order_gross_profit decimal(18,4) not null default 0,
    raw_order_gross_profit decimal(18,4) not null default 0,
    order_gross_margin decimal(10,4) null,
    margin_band varchar(64) not null,
    settlement_gross_profit decimal(18,4) not null default 0,
    filter_flag tinyint not null default 0,
    current_price_cny decimal(18,4) null,
    price_currency varchar(64) null,
    current_price decimal(18,4) null,
    limit_price decimal(18,2) null,
    limit_price_10 decimal(18,2) null,
    limit_price_adj decimal(18,2) null,
    over_limit_flag tinyint not null default 0,
    shipping_method varchar(64) null,
    target_margin decimal(10,4) null,
    limit_price_without_ad decimal(18,2) null,
    in_stock_days int not null default 0,
    stat_days int not null default 0,
    abnormal_days int not null default 0,
    all_abnormal_flag tinyint not null default 0,
    daily_sales decimal(18,6) null,
    daily_sales_in_stock_days decimal(18,6) null,
    daily_sales_in_stock_band varchar(64) not null,
    daily_sales_band varchar(64) not null,
    ad_spend decimal(18,4) not null default 0,
    ad_orders decimal(18,4) not null default 0,
    ad_sales decimal(18,4) not null default 0,
    ad_clicks decimal(18,4) not null default 0,
    ad_impressions decimal(18,4) not null default 0,
    acos decimal(10,4) null,
    tacos decimal(10,4) null,
    ctr decimal(10,4) null,
    fba_total_inventory decimal(18,4) not null default 0,
    fba_total_inventory_cost decimal(18,4) not null default 0,
    fba_available_inventory decimal(18,4) not null default 0,
    fba_available_inventory_cost decimal(18,4) not null default 0,
    fba_sellable_inventory decimal(18,4) not null default 0,
    pending_transfer decimal(18,4) not null default 0,
    transferring_qty decimal(18,4) not null default 0,
    pending_shipment decimal(18,4) not null default 0,
    unsellable_inventory decimal(18,4) not null default 0,
    planned_inbound decimal(18,4) not null default 0,
    actual_in_transit decimal(18,4) not null default 0,
    under_investigation decimal(18,4) not null default 0,
    total_available_inventory decimal(18,4) not null default 0,
    local_sellable_inventory decimal(18,4) not null default 0,
    local_stock_sellable_days int null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_period_item (snapshot_date, period_start, period_end, item_key),
    key idx_period_store (snapshot_date, period_start, period_end, seller_name_new),
    key idx_period_country (snapshot_date, period_start, period_end, country),
    key idx_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

PERIOD_PRESET_TABLES = {
    "last_7_days": "etl_datasync.dashboard_product_period_7d_snapshot",
    "last_14_days": "etl_datasync.dashboard_product_period_14d_snapshot",
    "last_30_days": "etl_datasync.dashboard_product_period_30d_snapshot",
    "last_90_days": "etl_datasync.dashboard_product_period_90d_snapshot",
    "last_month": "etl_datasync.dashboard_product_period_last_month_snapshot",
}

CREATE_MATRIX_PERIOD_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_product_matrix_period_snapshot (
    snapshot_date date not null,
    period_code varchar(32) not null,
    period_start date not null,
    period_end date not null,
    country varchar(64) not null default '__ALL__',
    seller_name_new varchar(128) not null default '__ALL__',
    over_limit_scope varchar(16) not null default 'all',
    margin_band varchar(64) not null,
    daily_sales_band varchar(64) not null,
    sku_count int not null default 0,
    over_limit_count int not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_matrix_period (
        snapshot_date, period_code, period_start, period_end,
        country, seller_name_new, over_limit_scope, margin_band, daily_sales_band
    ),
    key idx_matrix_lookup (
        snapshot_date, period_code, period_start, period_end,
        country, seller_name_new, over_limit_scope
    )
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_ALERT_COMPARISON_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_alert_comparison_snapshot (
    snapshot_date date not null,
    comparison_code varchar(64) not null,
    comparison_type varchar(32) not null,
    comparison_label varchar(128) not null,
    recent_start date not null,
    recent_end date not null,
    previous_start date not null,
    previous_end date not null,
    recent_days int not null,
    previous_days int not null,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    seller_name varchar(255) null,
    seller_sku_adj varchar(128) not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    local_sku varchar(128) null,
    filter_flag tinyint not null default 1,
    over_limit_flag tinyint not null default 0,
    daily_sales_band varchar(64) not null,
    margin_band varchar(64) not null,
    recent_sales_qty decimal(18,4) not null default 0,
    previous_sales_qty decimal(18,4) not null default 0,
    recent_daily_sales decimal(18,6) not null default 0,
    previous_daily_sales decimal(18,6) not null default 0,
    sales_change_rate decimal(12,6) not null default 0,
    recent_sales_amount decimal(18,4) not null default 0,
    previous_sales_amount decimal(18,4) not null default 0,
    recent_daily_sales_amount decimal(18,6) not null default 0,
    previous_daily_sales_amount decimal(18,6) not null default 0,
    recent_order_gross_profit decimal(18,4) not null default 0,
    previous_order_gross_profit decimal(18,4) not null default 0,
    recent_margin decimal(10,4) null,
    previous_margin decimal(10,4) null,
    recent_rank decimal(18,4) null,
    previous_rank decimal(18,4) null,
    rank_delta decimal(18,4) not null default 0,
    fba_sellable_inventory decimal(18,4) not null default 0,
    sellable_days decimal(18,4) not null default 0,
    sales_trend varchar(16) not null,
    rank_trend varchar(16) not null,
    margin_status varchar(16) not null,
    stock_status varchar(16) not null,
    sales_drop_flag tinyint not null default 0,
    sales_up_flag tinyint not null default 0,
    margin_low_flag tinyint not null default 0,
    rank_drop_flag tinyint not null default 0,
    stock_short_flag tinyint not null default 0,
    alert_types varchar(128) not null,
    alert_labels varchar(128) not null,
    primary_type varchar(32) not null,
    priority int not null default 9,
    has_alert tinyint not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_alert_comparison_item (snapshot_date, comparison_code, item_key),
    key idx_alert_lookup (snapshot_date, comparison_code, has_alert, country, seller_name_new),
    key idx_alert_filters (snapshot_date, comparison_code, sales_trend, rank_trend, margin_status, stock_status),
    key idx_alert_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_ALERT_COMPARISON_SUMMARY_SQL = """
create table if not exists etl_datasync.dashboard_alert_comparison_summary (
    snapshot_date date not null,
    comparison_code varchar(64) not null,
    country varchar(64) not null default '__ALL__',
    seller_name_new varchar(128) not null default '__ALL__',
    alert_type varchar(32) not null default '__ALL__',
    sales_trend varchar(16) not null default '__ALL__',
    rank_trend varchar(16) not null default '__ALL__',
    margin_status varchar(16) not null default '__ALL__',
    stock_status varchar(16) not null default '__ALL__',
    alert_count int not null default 0,
    total_sales_amount decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_alert_summary (
        snapshot_date, comparison_code, country, seller_name_new,
        alert_type, sales_trend, rank_trend, margin_status, stock_status
    ),
    key idx_alert_summary_lookup (snapshot_date, comparison_code, alert_type)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_opportunity_comparison_snapshot (
    snapshot_date date not null,
    comparison_code varchar(64) not null,
    comparison_mode varchar(32) not null,
    comparison_label varchar(128) not null,
    recent_start date null,
    recent_end date null,
    previous_start date null,
    previous_end date null,
    previous_month char(7) not null default '',
    recent_month char(7) not null default '',
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    seller_name varchar(255) null,
    seller_sku_adj varchar(128) not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    local_sku varchar(128) null,
    filter_flag tinyint not null default 1,
    over_limit_flag tinyint not null default 0,
    opportunity_types varchar(255) not null,
    primary_type varchar(32) not null,
    score int not null default 0,
    stock_status varchar(16) not null,
    recent_sales_qty decimal(18,4) not null default 0,
    previous_sales_qty decimal(18,4) not null default 0,
    recent_daily_sales decimal(18,6) not null default 0,
    previous_daily_sales decimal(18,6) not null default 0,
    sales_change_rate decimal(12,6) not null default 0,
    recent_sales_amount decimal(18,4) not null default 0,
    previous_sales_amount decimal(18,4) not null default 0,
    recent_order_gross_profit decimal(18,4) not null default 0,
    previous_order_gross_profit decimal(18,4) not null default 0,
    recent_margin decimal(10,4) null,
    previous_margin decimal(10,4) null,
    recent_rank decimal(18,4) null,
    previous_rank decimal(18,4) null,
    rank_delta decimal(18,4) not null default 0,
    fba_sellable_inventory decimal(18,4) not null default 0,
    sellable_days decimal(18,4) not null default 0,
    current_price decimal(18,4) not null default 0,
    limit_price decimal(18,4) not null default 0,
    limit_price_10 decimal(18,4) not null default 0,
    ad_spend decimal(18,4) not null default 0,
    ad_sales decimal(18,4) not null default 0,
    acos decimal(12,6) not null default 0,
    tacos decimal(12,6) not null default 0,
    estimated_boost_revenue decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_opportunity_comparison_item (snapshot_date, comparison_code, item_key),
    key idx_opportunity_lookup (snapshot_date, comparison_code, primary_type, country, seller_name_new),
    key idx_opportunity_filters (snapshot_date, comparison_code, stock_status, score),
    key idx_opportunity_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_OPPORTUNITY_COMPARISON_SUMMARY_SQL = """
create table if not exists etl_datasync.dashboard_opportunity_comparison_summary (
    snapshot_date date not null,
    comparison_code varchar(64) not null,
    country varchar(64) not null default '__ALL__',
    seller_name_new varchar(128) not null default '__ALL__',
    opportunity_type varchar(32) not null default '__ALL__',
    stock_status varchar(16) not null default '__ALL__',
    opportunity_count int not null default 0,
    estimated_boost_revenue decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_opportunity_summary (
        snapshot_date, comparison_code, country, seller_name_new, opportunity_type, stock_status
    ),
    key idx_opportunity_summary_lookup (snapshot_date, comparison_code, opportunity_type)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_alert_monthly_metric_snapshot (
    snapshot_date date not null,
    month_code char(7) not null,
    month_start date not null,
    month_end date not null,
    data_start date not null,
    data_end date not null,
    stat_days int not null,
    is_month_complete tinyint not null default 0,
    item_key varchar(512) not null,
    seller_name_new varchar(128) not null,
    seller_name varchar(255) null,
    seller_sku_adj varchar(128) not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    local_sku varchar(128) null,
    filter_flag tinyint not null default 1,
    over_limit_flag tinyint not null default 0,
    daily_sales_band varchar(64) not null,
    margin_band varchar(64) not null,
    sales_qty decimal(18,4) not null default 0,
    daily_sales decimal(18,6) not null default 0,
    sales_amount decimal(18,4) not null default 0,
    daily_sales_amount decimal(18,6) not null default 0,
    order_gross_profit decimal(18,4) not null default 0,
    margin decimal(10,4) null,
    avg_rank decimal(18,4) null,
    fba_sellable_inventory decimal(18,4) not null default 0,
    sellable_days decimal(18,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_alert_monthly_item (snapshot_date, month_code, item_key),
    key idx_alert_monthly_lookup (snapshot_date, month_code, country, seller_name_new),
    key idx_alert_monthly_filters (snapshot_date, month_code, filter_flag, daily_sales_band, margin_band),
    key idx_alert_monthly_sku (seller_sku_adj)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_ANNUAL_GOAL_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_annual_goal_snapshot (
    snapshot_date date not null,
    goal_year int not null,
    year_start date not null,
    data_end_date date not null,
    sales_goal decimal(18,2) not null,
    margin_goal decimal(10,4) not null,
    sales_goal_buffer decimal(10,4) not null,
    sales_amount_ytd decimal(18,2) not null default 0,
    sales_amount_ex_tax_ytd decimal(18,2) not null default 0,
    order_gross_profit_ytd decimal(18,2) not null default 0,
    order_gross_margin_ytd decimal(10,4) null,
    target_amount_to_date decimal(18,2) not null default 0,
    sales_goal_ratio decimal(10,4) not null default 0,
    current_goal_ratio decimal(10,4) not null default 0,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    unique key uk_snapshot_goal_year (snapshot_date, goal_year),
    key idx_goal_year (goal_year, snapshot_date)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_MONTHLY_GOAL_SQL = """
create table if not exists etl_datasync.dashboard_monthly_goal (
    goal_year int not null,
    goal_month tinyint not null,
    month_start date not null,
    sales_goal decimal(18,2) not null,
    margin_goal decimal(10,6) not null,
    gross_profit_goal decimal(18,2) not null,
    sales_volume_goal decimal(18,2) null,
    source_file varchar(255) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (goal_year, goal_month),
    key idx_month_start (month_start)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_monthly_goal_actual_snapshot (
    goal_year int not null,
    goal_month tinyint not null,
    data_end_date date null,
    sales_actual decimal(18,4) not null default 0,
    volume_actual decimal(18,4) not null default 0,
    profit_actual decimal(18,4) not null default 0,
    margin_actual decimal(10,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (goal_year, goal_month),
    key idx_data_end_date (data_end_date)
) engine=InnoDB default charset=utf8mb4;
"""

DELETE_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_monthly_goal_actual_snapshot
where goal_year = year(%(biz_date)s);
"""

INSERT_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_monthly_goal_actual_snapshot (
    goal_year, goal_month, data_end_date,
    sales_actual, volume_actual, profit_actual, margin_actual,
    created_at, updated_at
)
select
    year(dt_date) as goal_year,
    month(dt_date) as goal_month,
    max(dt_date) as data_end_date,
    round(sum(sales_amount), 4) as sales_actual,
    round(sum(sales_qty), 4) as volume_actual,
    round(sum(order_gross_profit), 4) as profit_actual,
    round(sum(order_gross_profit) / nullif(sum(sales_amount), 0), 6) as margin_actual,
    now() as created_at,
    now() as updated_at
from etl_datasync.dashboard_product_performance_daily
where dt_date between makedate(year(%(biz_date)s), 1) and str_to_date(concat(year(%(biz_date)s), '-12-31'), '%%Y-%%m-%%d')
  and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
  and char_length(seller_sku_adj) between 5 and 10
group by year(dt_date), month(dt_date);
"""

DELETE_INVENTORY_WEEKLY_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_inventory_weekly_snapshot
where week_start in (
    select week_start
    from (
        select distinct date_sub(snapshot_date, interval weekday(snapshot_date) day) as week_start
        from etl_datasync.dashboard_inventory_daily_snapshot
        where snapshot_date <= %(snapshot_date)s
        union
        select distinct date_sub(snapshot_date, interval weekday(snapshot_date) day) as week_start
        from etl_datasync.dashboard_restock_daily_snapshot
        where snapshot_date <= %(snapshot_date)s
    ) refresh_weeks
);
"""

INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_inventory_weekly_snapshot (
    snapshot_date, week_start, week_end, item_key, country_category, seller_sku_adj, seller_name_new,
    available_quantity, available_cost, transit_quantity, transit_cost,
    warehouse_quantity, warehouse_cost, plan_quantity, plan_cost,
    created_at, updated_at
)
with all_snapshot_dates as (
    select snapshot_date, 'inventory' as source_type from etl_datasync.dashboard_inventory_daily_snapshot
    union
    select snapshot_date, 'restock' as source_type from etl_datasync.dashboard_restock_daily_snapshot
),
dated_snapshot_dates as (
    select
        snapshot_date,
        source_type,
        date_sub(snapshot_date, interval weekday(snapshot_date) day) as week_start,
        date_add(date_sub(snapshot_date, interval weekday(snapshot_date) day), interval 6 day) as week_end
    from all_snapshot_dates
    where snapshot_date <= %(snapshot_date)s
),
week_dates as (
    select
        week_start,
        max(week_end) as week_end,
        max(snapshot_date) as snapshot_date
    from dated_snapshot_dates
    group by week_start
),
inventory_week_dates as (
    select
        week_start,
        max(snapshot_date) as inventory_snapshot_date
    from dated_snapshot_dates
    where source_type = 'inventory'
    group by week_start
),
restock_week_dates as (
    select
        week_start,
        max(snapshot_date) as restock_snapshot_date
    from dated_snapshot_dates
    where source_type = 'restock'
    group by week_start
),
base_keys as (
    select
        w.snapshot_date,
        w.week_start,
        w.week_end,
        i.item_key,
        i.country_category,
        i.seller_sku_adj,
        i.seller_name_new
    from week_dates w
    join inventory_week_dates iw
      on iw.week_start = w.week_start
    join etl_datasync.dashboard_inventory_daily_snapshot i
      on i.snapshot_date = iw.inventory_snapshot_date
    union
    select
        w.snapshot_date,
        w.week_start,
        w.week_end,
        r.item_key,
        r.country_category,
        r.seller_sku_adj,
        r.seller_name_new
    from week_dates w
    join restock_week_dates rw
      on rw.week_start = w.week_start
    join etl_datasync.dashboard_restock_daily_snapshot r
      on r.snapshot_date = rw.restock_snapshot_date
)
select
    b.snapshot_date,
    b.week_start,
    b.week_end,
    b.item_key,
    b.country_category,
    b.seller_sku_adj,
    b.seller_name_new,
    coalesce(i.available_total, 0) as available_quantity,
    coalesce(i.available_price, 0) as available_cost,
    coalesce(i.stock_up_num, 0) as transit_quantity,
    coalesce(i.stock_up_num_price, 0) as transit_cost,
    coalesce(r.local_quantity, 0) as warehouse_quantity,
    coalesce(r.local_quantity, 0) * (coalesce(r.purchase_cost, 0) + coalesce(r.transport_cost, 0)) as warehouse_cost,
    coalesce(r.purchase_shipping_quantity, 0) as plan_quantity,
    coalesce(r.purchase_shipping_quantity, 0) * (coalesce(r.purchase_cost, 0) + coalesce(r.transport_cost, 0)) as plan_cost,
    now() as created_at,
    now() as updated_at
from base_keys b
left join inventory_week_dates iw
  on iw.week_start = b.week_start
left join restock_week_dates rw
  on rw.week_start = b.week_start
left join etl_datasync.dashboard_inventory_daily_snapshot i
  on i.snapshot_date = iw.inventory_snapshot_date
 and i.item_key = b.item_key
left join etl_datasync.dashboard_restock_daily_snapshot r
  on r.snapshot_date = rw.restock_snapshot_date
 and r.item_key = b.item_key;
"""

DELETE_INVENTORY_WEEKLY_REMOTE_SQL = """
delete from etl_datasync.dashboard_inventory_weekly_snapshot
where week_start = date_sub(%(snapshot_date)s, interval weekday(%(snapshot_date)s) day);
"""

SELECT_INVENTORY_WEEKLY_REMOTE_SQL = """
with inventory as (
    select
        concat_ws('|', country_category, seller_name_new, seller_sku_adj) as item_key,
        country_category,
        seller_sku_adj,
        seller_name_new,
        sum(coalesce(available_total, 0)) as available_quantity,
        sum(coalesce(available_total_price, 0)) as available_cost,
        sum(coalesce(stock_up_num, 0)) as transit_quantity,
        sum(coalesce(stock_up_num_price, 0)) as transit_cost
    from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
    where create_time >= %(snapshot_date)s
      and create_time < %(next_snapshot_date)s
    group by country_category, seller_sku_adj, seller_name_new
),
restock as (
    select
        concat_ws('|', r.country_category, r.seller_name_new, r.seller_sku_adj) as item_key,
        r.country_category,
        r.seller_sku_adj,
        r.seller_name_new,
        coalesce(max(r.sc_quantity_local_valid), 0)
          + coalesce(max(r.sc_quantity_purchase_shipping), 0)
          + coalesce(max(r.sc_quantity_purchase_plan), 0)
          + coalesce(max(r.sc_quantity_local_qc), 0) as warehouse_quantity,
        (
          coalesce(max(r.sc_quantity_local_valid), 0)
          + coalesce(max(r.sc_quantity_purchase_shipping), 0)
          + coalesce(max(r.sc_quantity_purchase_plan), 0)
          + coalesce(max(r.sc_quantity_local_qc), 0)
        ) * (coalesce(max(c.cg_price), 0) + coalesce(max(c.cg_transport_costs), 0)) as warehouse_cost,
        coalesce(max(r.sc_quantity_purchase_shipping), 0) as plan_quantity,
        coalesce(max(r.sc_quantity_purchase_shipping), 0) * (coalesce(max(c.cg_price), 0) + coalesce(max(c.cg_transport_costs), 0)) as plan_cost
    from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking r
    left join etl_datasync.etl_dispose_lx_product_local_product_info c
      on substring_index(c.seller_sku, '-', 1) = r.seller_sku_adj
     and c.country_category = r.country_category
     and c.seller_name_new = r.seller_name_new
    where r.create_time >= %(snapshot_date)s
      and r.create_time < %(next_snapshot_date)s
    group by r.country_category, r.seller_sku_adj, r.seller_name_new
),
base_keys as (
    select item_key, country_category, seller_sku_adj, seller_name_new from inventory
    union
    select item_key, country_category, seller_sku_adj, seller_name_new from restock
)
select
    %(snapshot_date)s as snapshot_date,
    date_sub(%(snapshot_date)s, interval weekday(%(snapshot_date)s) day) as week_start,
    date_add(date_sub(%(snapshot_date)s, interval weekday(%(snapshot_date)s) day), interval 6 day) as week_end,
    b.item_key,
    b.country_category,
    b.seller_sku_adj,
    b.seller_name_new,
    coalesce(i.available_quantity, 0) as available_quantity,
    coalesce(i.available_cost, 0) as available_cost,
    coalesce(i.transit_quantity, 0) as transit_quantity,
    coalesce(i.transit_cost, 0) as transit_cost,
    coalesce(r.warehouse_quantity, 0) as warehouse_quantity,
    coalesce(r.warehouse_cost, 0) as warehouse_cost,
    coalesce(r.plan_quantity, 0) as plan_quantity,
    coalesce(r.plan_cost, 0) as plan_cost,
    now() as created_at,
    now() as updated_at
from base_keys b
left join inventory i
  on i.item_key = b.item_key
left join restock r
  on r.item_key = b.item_key;
"""

CREATE_GOAL_DIMENSION_SNAPSHOT_SQL = """
create table if not exists etl_datasync.dashboard_goal_dimension_snapshot (
    snapshot_date date not null,
    goal_year int not null,
    data_end_date date null,
    dimension_type varchar(32) not null,
    dimension_name varchar(128) not null,
    sales_amount_ytd decimal(18,4) not null default 0,
    sales_qty_ytd decimal(18,4) not null default 0,
    order_gross_profit_ytd decimal(18,4) not null default 0,
    order_gross_margin_ytd decimal(10,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, goal_year, dimension_type, dimension_name),
    key idx_dimension_lookup (goal_year, dimension_type, sales_amount_ytd)
) engine=InnoDB default charset=utf8mb4;
"""

DELETE_GOAL_DIMENSION_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_goal_dimension_snapshot
where snapshot_date = %(snapshot_date)s
  and goal_year = year(%(biz_date)s);
"""

INSERT_GOAL_DIMENSION_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_goal_dimension_snapshot (
    snapshot_date, goal_year, data_end_date, dimension_type, dimension_name,
    sales_amount_ytd, sales_qty_ytd, order_gross_profit_ytd, order_gross_margin_ytd,
    created_at, updated_at
)
select
    %(snapshot_date)s as snapshot_date,
    year(dt_date) as goal_year,
    max(dt_date) as data_end_date,
    dimension_type,
    dimension_name,
    round(sum(sales_amount), 4) as sales_amount_ytd,
    round(sum(sales_qty), 4) as sales_qty_ytd,
    round(sum(order_gross_profit), 4) as order_gross_profit_ytd,
    round(sum(order_gross_profit) / nullif(sum(sales_amount), 0), 6) as order_gross_margin_ytd,
    now() as created_at,
    now() as updated_at
from (
    select
        dt_date,
        country as dimension_name,
        'country' as dimension_type,
        sales_amount,
        sales_qty,
        order_gross_profit
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between makedate(year(%(biz_date)s), 1) and %(biz_date)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
    union all
    select
        dt_date,
        seller_name_new as dimension_name,
        'store' as dimension_type,
        sales_amount,
        sales_qty,
        order_gross_profit
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between makedate(year(%(biz_date)s), 1) and %(biz_date)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
) x
group by year(dt_date), dimension_type, dimension_name;
"""


def period_create_sql(table_name: str) -> str:
    return CREATE_PERIOD_SNAPSHOT_SQL.replace(
        "etl_datasync.dashboard_product_period_snapshot",
        table_name,
        1,
    )


def period_delete_sql(table_name: str) -> str:
    return DELETE_PERIOD_SNAPSHOT_SQL.replace(
        "etl_datasync.dashboard_product_period_snapshot",
        table_name,
        1,
    )


def period_insert_sql(table_name: str) -> str:
    return INSERT_PERIOD_SNAPSHOT_SQL.replace(
        "etl_datasync.dashboard_product_period_snapshot",
        table_name,
        1,
    )


def period_retention_sql(table_name: str) -> str:
    return f"""
delete from {table_name}
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from {table_name}
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""


DELETE_MATRIX_PERIOD_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_product_matrix_period_snapshot
where snapshot_date = %(snapshot_date)s
  and period_code = %(period_code)s
  and period_start = %(period_start)s
  and period_end = %(period_end)s;
"""

DELETE_OLD_MATRIX_PERIOD_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_product_matrix_period_snapshot
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_product_matrix_period_snapshot
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_ALERT_COMPARISON_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_alert_comparison_snapshot
where snapshot_date = %(snapshot_date)s
  and comparison_code = %(comparison_code)s;
"""

INSERT_ALERT_COMPARISON_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_alert_comparison_snapshot (
    snapshot_date, comparison_code, comparison_type, comparison_label,
    recent_start, recent_end, previous_start, previous_end, recent_days, previous_days,
    item_key, seller_name_new, seller_name, seller_sku_adj, country_category, country, local_sku,
    filter_flag, over_limit_flag, daily_sales_band, margin_band,
    recent_sales_qty, previous_sales_qty, recent_daily_sales, previous_daily_sales, sales_change_rate,
    recent_sales_amount, previous_sales_amount, recent_daily_sales_amount, previous_daily_sales_amount,
    recent_order_gross_profit, previous_order_gross_profit, recent_margin, previous_margin,
    recent_rank, previous_rank, rank_delta, fba_sellable_inventory, sellable_days,
    sales_trend, rank_trend, margin_status, stock_status,
    sales_drop_flag, sales_up_flag, margin_low_flag, rank_drop_flag, stock_short_flag,
    alert_types, alert_labels, primary_type, priority, has_alert,
    created_at, updated_at
)
with recent as (
    select
        item_key,
        max(seller_name_new) as seller_name_new,
        max(seller_name) as seller_name,
        max(seller_sku_adj) as seller_sku_adj,
        max(country_category) as country_category,
        max(country) as country,
        max(local_sku) as local_sku,
        sum(sales_qty) as sales_qty,
        sum(sales_amount) as sales_amount,
        sum(order_gross_profit) as order_gross_profit,
        avg(case when ranking > 0 then ranking end) as avg_rank,
        max(afn_fulfillable_quantity) as fba_sellable_inventory
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(recent_start)s and %(recent_end)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
    group by item_key
),
previous as (
    select
        item_key,
        max(seller_name_new) as seller_name_new,
        max(seller_name) as seller_name,
        max(seller_sku_adj) as seller_sku_adj,
        max(country_category) as country_category,
        max(country) as country,
        max(local_sku) as local_sku,
        sum(sales_qty) as sales_qty,
        sum(sales_amount) as sales_amount,
        sum(order_gross_profit) as order_gross_profit,
        avg(case when ranking > 0 then ranking end) as avg_rank,
        max(afn_fulfillable_quantity) as fba_sellable_inventory
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(previous_start)s and %(previous_end)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
    group by item_key
),
period_flags as (
    select item_key, max(over_limit_flag) as over_limit_flag, max(filter_flag) as filter_flag
    from etl_datasync.dashboard_product_period_90d_snapshot
    where snapshot_date = %(snapshot_date)s
    group by item_key
),
joined as (
    select
        coalesce(r.item_key, p.item_key) as item_key,
        coalesce(r.seller_name_new, p.seller_name_new) as seller_name_new,
        coalesce(r.seller_name, p.seller_name) as seller_name,
        coalesce(r.seller_sku_adj, p.seller_sku_adj) as seller_sku_adj,
        coalesce(r.country_category, p.country_category) as country_category,
        coalesce(r.country, p.country) as country,
        coalesce(r.local_sku, p.local_sku) as local_sku,
        coalesce(f.filter_flag, 1) as filter_flag,
        coalesce(f.over_limit_flag, 0) as over_limit_flag,
        coalesce(r.sales_qty, 0) as recent_sales_qty,
        coalesce(p.sales_qty, 0) as previous_sales_qty,
        coalesce(r.sales_amount, 0) as recent_sales_amount,
        coalesce(p.sales_amount, 0) as previous_sales_amount,
        coalesce(r.order_gross_profit, 0) as recent_order_gross_profit,
        coalesce(p.order_gross_profit, 0) as previous_order_gross_profit,
        r.avg_rank as recent_rank,
        p.avg_rank as previous_rank,
        coalesce(r.fba_sellable_inventory, p.fba_sellable_inventory, 0) as fba_sellable_inventory
    from recent r
    left join previous p on p.item_key = r.item_key
    left join period_flags f on f.item_key = r.item_key
    union all
    select
        p.item_key,
        p.seller_name_new,
        p.seller_name,
        p.seller_sku_adj,
        p.country_category,
        p.country,
        p.local_sku,
        coalesce(f.filter_flag, 1) as filter_flag,
        coalesce(f.over_limit_flag, 0) as over_limit_flag,
        0 as recent_sales_qty,
        coalesce(p.sales_qty, 0) as previous_sales_qty,
        0 as recent_sales_amount,
        coalesce(p.sales_amount, 0) as previous_sales_amount,
        0 as recent_order_gross_profit,
        coalesce(p.order_gross_profit, 0) as previous_order_gross_profit,
        null as recent_rank,
        p.avg_rank as previous_rank,
        coalesce(p.fba_sellable_inventory, 0) as fba_sellable_inventory
    from previous p
    left join recent r on r.item_key = p.item_key
    left join period_flags f on f.item_key = p.item_key
    where r.item_key is null
),
metrics as (
    select
        j.*,
        %(recent_days)s as recent_days,
        %(previous_days)s as previous_days,
        j.recent_sales_qty / nullif(%(recent_days)s, 0) as recent_daily_sales,
        j.previous_sales_qty / nullif(%(previous_days)s, 0) as previous_daily_sales,
        j.recent_sales_amount / nullif(%(recent_days)s, 0) as recent_daily_sales_amount,
        j.previous_sales_amount / nullif(%(previous_days)s, 0) as previous_daily_sales_amount,
        round(j.recent_order_gross_profit / nullif(j.recent_sales_amount, 0), 4) as recent_margin,
        round(j.previous_order_gross_profit / nullif(j.previous_sales_amount, 0), 4) as previous_margin
    from joined j
),
classified as (
    select
        m.*,
        case
            when %(comparison_type)s = 'month_to_date'
                then case
                    when m.previous_daily_sales <> 0 then (m.recent_daily_sales - m.previous_daily_sales) / abs(m.previous_daily_sales)
                    when m.recent_daily_sales > 0 then 1
                    else 0
                end
            else case
                when m.previous_sales_qty <> 0 then (m.recent_sales_qty - m.previous_sales_qty) / abs(m.previous_sales_qty)
                when m.recent_sales_qty > 0 then 1
                else 0
            end
        end as sales_change_rate,
        case
            when %(comparison_type)s = 'month_to_date'
                then m.previous_sales_qty >= 10 and m.recent_daily_sales <= m.previous_daily_sales * 0.7
            else m.previous_sales_qty >= 10 and m.recent_sales_qty <= m.previous_sales_qty * 0.7
        end as sales_drop_flag,
        case
            when %(comparison_type)s = 'month_to_date'
                then m.recent_sales_qty >= 10 and m.recent_daily_sales >= m.previous_daily_sales * 1.3
            else m.recent_sales_qty >= 10 and m.recent_sales_qty >= m.previous_sales_qty * 1.3
        end as sales_up_flag,
        (
            m.previous_rank is not null
            and m.recent_rank is not null
            and m.recent_rank >= m.previous_rank + 5
            and m.recent_rank >= m.previous_rank * 1.2
        ) as rank_drop_flag,
        (
            m.previous_rank is not null
            and m.recent_rank is not null
            and m.recent_rank <= greatest(m.previous_rank - 5, m.previous_rank * 0.8)
        ) as rank_up_flag,
        (m.recent_sales_amount >= 1000 and coalesce(m.recent_margin, 0) < 0.08) as margin_low_flag,
        (
            m.recent_daily_sales >= 1
            and m.fba_sellable_inventory > 0
            and m.fba_sellable_inventory / nullif(m.recent_daily_sales, 0) < 14
        ) as stock_short_flag
    from metrics m
)
select
    %(snapshot_date)s,
    %(comparison_code)s,
    %(comparison_type)s,
    %(comparison_label)s,
    %(recent_start)s,
    %(recent_end)s,
    %(previous_start)s,
    %(previous_end)s,
    recent_days,
    previous_days,
    item_key,
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    filter_flag,
    over_limit_flag,
    case
        when recent_daily_sales < 1 and recent_daily_sales > 0 then '日销 <1'
        when recent_daily_sales >= 1 and recent_daily_sales < 5 then '日销 1-5'
        when recent_daily_sales >= 5 then '日销 >5'
        else '日销 0'
    end as daily_sales_band,
    case
        when recent_margin >= 0.35 then '毛利率 >35%%'
        when recent_margin >= 0.25 and recent_margin < 0.35 then '毛利率 25-35%%'
        when recent_margin >= 0.15 and recent_margin < 0.25 then '毛利率 15-25%%'
        when recent_margin >= 0.10 and recent_margin < 0.15 then '毛利率 10-15%%'
        when recent_margin >= 0 and recent_margin < 0.10 then '毛利率 0-10%%'
        else '毛利率 <0%%'
    end as margin_band,
    recent_sales_qty,
    previous_sales_qty,
    recent_daily_sales,
    previous_daily_sales,
    sales_change_rate,
    recent_sales_amount,
    previous_sales_amount,
    recent_daily_sales_amount,
    previous_daily_sales_amount,
    recent_order_gross_profit,
    previous_order_gross_profit,
    recent_margin,
    previous_margin,
    recent_rank,
    previous_rank,
    case when previous_rank is not null and recent_rank is not null then previous_rank - recent_rank else 0 end,
    fba_sellable_inventory,
    case when recent_daily_sales > 0 then fba_sellable_inventory / recent_daily_sales else 0 end,
    case when sales_drop_flag then 'down' when sales_up_flag then 'up' else 'stable' end,
    case when rank_drop_flag then 'down' when rank_up_flag then 'up' else 'stable' end,
    case when margin_low_flag then 'low' else 'normal' end,
    case when stock_short_flag then 'short' else 'normal' end,
    sales_drop_flag,
    sales_up_flag,
    margin_low_flag,
    rank_drop_flag,
    stock_short_flag,
    concat_ws(',', if(sales_drop_flag, 'sales_drop', null), if(margin_low_flag, 'margin_low', null), if(rank_drop_flag, 'rank_drop', null), if(stock_short_flag, 'stock_short', null)),
    concat_ws(' / ', if(sales_drop_flag, '销量下滑', null), if(margin_low_flag, '低毛利', null), if(rank_drop_flag, '排名下滑', null), if(stock_short_flag, '库存偏低', null)),
    case
        when sales_drop_flag then 'sales_drop'
        when margin_low_flag then 'margin_low'
        when rank_drop_flag then 'rank_drop'
        when stock_short_flag then 'stock_short'
        else 'observe'
    end,
    case
        when sales_drop_flag then 0
        when margin_low_flag then 1
        when rank_drop_flag then 2
        when stock_short_flag then 3
        else 9
    end,
    (sales_drop_flag or margin_low_flag or rank_drop_flag or stock_short_flag),
    now(),
    now()
from classified;
"""

DELETE_ALERT_COMPARISON_SUMMARY_SQL = """
delete from etl_datasync.dashboard_alert_comparison_summary
where snapshot_date = %(snapshot_date)s
  and comparison_code = %(comparison_code)s;
"""

INSERT_ALERT_COMPARISON_SUMMARY_SQL = """
insert into etl_datasync.dashboard_alert_comparison_summary (
    snapshot_date, comparison_code, country, seller_name_new,
    alert_type, sales_trend, rank_trend, margin_status, stock_status,
    alert_count, total_sales_amount, created_at, updated_at
)
select
    snapshot_date,
    comparison_code,
    country,
    seller_name_new,
    alert_type,
    sales_trend,
    rank_trend,
    margin_status,
    stock_status,
    count(*) as alert_count,
    sum(recent_sales_amount) as total_sales_amount,
    now(),
    now()
from (
    select snapshot_date, comparison_code, country, seller_name_new, 'sales_drop' as alert_type, sales_trend, rank_trend, margin_status, stock_status, recent_sales_amount
    from etl_datasync.dashboard_alert_comparison_snapshot
    where snapshot_date = %(snapshot_date)s and comparison_code = %(comparison_code)s and sales_drop_flag = 1
    union all
    select snapshot_date, comparison_code, country, seller_name_new, 'margin_low' as alert_type, sales_trend, rank_trend, margin_status, stock_status, recent_sales_amount
    from etl_datasync.dashboard_alert_comparison_snapshot
    where snapshot_date = %(snapshot_date)s and comparison_code = %(comparison_code)s and margin_low_flag = 1
    union all
    select snapshot_date, comparison_code, country, seller_name_new, 'rank_drop' as alert_type, sales_trend, rank_trend, margin_status, stock_status, recent_sales_amount
    from etl_datasync.dashboard_alert_comparison_snapshot
    where snapshot_date = %(snapshot_date)s and comparison_code = %(comparison_code)s and rank_drop_flag = 1
    union all
    select snapshot_date, comparison_code, country, seller_name_new, 'stock_short' as alert_type, sales_trend, rank_trend, margin_status, stock_status, recent_sales_amount
    from etl_datasync.dashboard_alert_comparison_snapshot
    where snapshot_date = %(snapshot_date)s and comparison_code = %(comparison_code)s and stock_short_flag = 1
) alerts
group by
    snapshot_date, comparison_code, country, seller_name_new,
    alert_type, sales_trend, rank_trend, margin_status, stock_status;
"""

DELETE_OLD_ALERT_COMPARISON_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_alert_comparison_snapshot
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_alert_comparison_snapshot
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_OLD_ALERT_COMPARISON_SUMMARY_SQL = """
delete from etl_datasync.dashboard_alert_comparison_summary
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_alert_comparison_summary
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_opportunity_comparison_snapshot
where snapshot_date = %(snapshot_date)s
  and comparison_code = %(comparison_code)s;
"""

INSERT_OPPORTUNITY_COMPARISON_FROM_ALERT_SQL = """
insert into etl_datasync.dashboard_opportunity_comparison_snapshot (
    snapshot_date, comparison_code, comparison_mode, comparison_label,
    recent_start, recent_end, previous_start, previous_end, previous_month, recent_month,
    item_key, seller_name_new, seller_name, seller_sku_adj, country_category, country, local_sku,
    filter_flag, over_limit_flag, opportunity_types, primary_type, score, stock_status,
    recent_sales_qty, previous_sales_qty, recent_daily_sales, previous_daily_sales, sales_change_rate,
    recent_sales_amount, previous_sales_amount, recent_order_gross_profit, previous_order_gross_profit,
    recent_margin, previous_margin, recent_rank, previous_rank, rank_delta,
    fba_sellable_inventory, sellable_days, current_price, limit_price, limit_price_10,
    ad_spend, ad_sales, acos, tacos, estimated_boost_revenue, created_at, updated_at
)
with source_rows as (
    select
        a.*,
        coalesce(p.current_price, 0) as current_price,
        coalesce(p.limit_price, 0) as limit_price,
        coalesce(p.limit_price_10, 0) as limit_price_10,
        coalesce(p.over_limit_flag, a.over_limit_flag, 0) as current_over_limit_flag,
        coalesce(p.ad_spend, 0) as ad_spend,
        coalesce(p.ad_sales, 0) as ad_sales,
        coalesce(p.acos, 0) as acos,
        coalesce(p.tacos, 0) as tacos
    from etl_datasync.dashboard_alert_comparison_snapshot a
    left join (
        select
            item_key,
            max(current_price) as current_price,
            max(limit_price) as limit_price,
            max(limit_price_10) as limit_price_10,
            max(over_limit_flag) as over_limit_flag,
            max(ad_spend) as ad_spend,
            max(ad_sales) as ad_sales,
            max(acos) as acos,
            max(tacos) as tacos
        from etl_datasync.dashboard_product_period_90d_snapshot
        where snapshot_date = %(snapshot_date)s
        group by item_key
    ) p
      on p.item_key = a.item_key
    where a.snapshot_date = %(snapshot_date)s
      and a.comparison_code = %(comparison_code)s
      and a.filter_flag = 1
),
classified as (
    select
        s.*,
        case when coalesce(s.recent_daily_sales, 0) > 0 then coalesce(s.fba_sellable_inventory, 0) / s.recent_daily_sales else 0 end as calc_sellable_days,
        case when s.previous_rank is not null and s.recent_rank is not null then s.previous_rank - s.recent_rank else 0 end as calc_rank_delta,
        case when s.previous_rank is not null and s.previous_rank > 0 and s.recent_rank is not null then (s.previous_rank - s.recent_rank) / s.previous_rank else 0 end as rank_improve_ratio
    from source_rows s
),
opportunity as (
    select
        c.*,
        concat_ws(',',
            if(coalesce(c.recent_margin, 0) >= 0.25 and c.recent_daily_sales >= 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0, 'high_margin_scale', null),
            if(c.calc_rank_delta >= 5 and c.rank_improve_ratio >= 0.20 and c.calc_sellable_days >= 14, 'rank_improve', null),
            if(c.calc_sellable_days >= 30 and coalesce(c.recent_margin, 0) >= 0.15 and c.recent_daily_sales >= 0.5 and c.current_over_limit_flag = 0, 'inventory_push', null),
            if(coalesce(c.recent_margin, 0) >= 0.35 and c.recent_daily_sales < 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0, 'low_sales_high_margin', null),
            if((c.tacos <= 0.05 or (c.acos > 0 and c.acos <= 0.20)) and coalesce(c.recent_margin, 0) >= 0.20 and (c.recent_sales_amount > 0 or c.ad_spend > 0), 'ad_efficiency', null)
        ) as opportunity_types,
        case
            when coalesce(c.recent_margin, 0) >= 0.25 and c.recent_daily_sales >= 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0 then 'high_margin_scale'
            when c.calc_rank_delta >= 5 and c.rank_improve_ratio >= 0.20 and c.calc_sellable_days >= 14 then 'rank_improve'
            when c.calc_sellable_days >= 30 and coalesce(c.recent_margin, 0) >= 0.15 and c.recent_daily_sales >= 0.5 and c.current_over_limit_flag = 0 then 'inventory_push'
            when coalesce(c.recent_margin, 0) >= 0.35 and c.recent_daily_sales < 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0 then 'low_sales_high_margin'
            when (c.tacos <= 0.05 or (c.acos > 0 and c.acos <= 0.20)) and coalesce(c.recent_margin, 0) >= 0.20 and (c.recent_sales_amount > 0 or c.ad_spend > 0) then 'ad_efficiency'
            else 'observe'
        end as opportunity_primary_type,
        case when c.calc_sellable_days >= 21 then 'enough' else 'short' end as opportunity_stock_status,
        round(greatest(0, least(100,
            least(greatest(coalesce(c.recent_margin, 0), 0) / 0.35, 1) * 25
            + (least(greatest(c.sales_change_rate, 0), 1) * 0.4 + least(c.recent_daily_sales / 5, 1) * 0.35 + least(c.recent_sales_amount / 50000, 1) * 0.25) * 25
            + least(greatest(c.rank_improve_ratio, 0), 0.5) / 0.5 * 20
            + case when c.calc_sellable_days < 14 then 0 when c.calc_sellable_days <= 60 then least((c.calc_sellable_days - 14) / 46, 1) * 20 else 18 end
            - if(c.current_over_limit_flag = 1, 4, 0)
            - if(c.tacos > 0.12, 3, 0)
            - if(c.calc_sellable_days < 14, 2, 0)
            - if(coalesce(c.recent_margin, 0) < 0.15, 1, 0)
        ))) as score,
        round(greatest(c.recent_daily_sales, 0) * least(greatest(c.calc_sellable_days, 0), 30) * 0.15 * if(c.recent_sales_qty > 0, c.recent_sales_amount / c.recent_sales_qty, 0), 4) as estimated_boost_revenue
    from classified c
)
select
    snapshot_date,
    comparison_code,
    'days',
    comparison_label,
    recent_start,
    recent_end,
    previous_start,
    previous_end,
    '',
    '',
    item_key,
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    filter_flag,
    current_over_limit_flag,
    opportunity_types,
    opportunity_primary_type,
    score,
    opportunity_stock_status,
    recent_sales_qty,
    previous_sales_qty,
    recent_daily_sales,
    previous_daily_sales,
    sales_change_rate,
    recent_sales_amount,
    previous_sales_amount,
    recent_order_gross_profit,
    previous_order_gross_profit,
    recent_margin,
    previous_margin,
    recent_rank,
    previous_rank,
    calc_rank_delta,
    fba_sellable_inventory,
    calc_sellable_days,
    current_price,
    limit_price,
    limit_price_10,
    ad_spend,
    ad_sales,
    acos,
    tacos,
    estimated_boost_revenue,
    now(),
    now()
from opportunity
where opportunity_types <> '';
"""

INSERT_OPPORTUNITY_COMPARISON_FROM_MONTH_SQL = """
insert into etl_datasync.dashboard_opportunity_comparison_snapshot (
    snapshot_date, comparison_code, comparison_mode, comparison_label,
    recent_start, recent_end, previous_start, previous_end, previous_month, recent_month,
    item_key, seller_name_new, seller_name, seller_sku_adj, country_category, country, local_sku,
    filter_flag, over_limit_flag, opportunity_types, primary_type, score, stock_status,
    recent_sales_qty, previous_sales_qty, recent_daily_sales, previous_daily_sales, sales_change_rate,
    recent_sales_amount, previous_sales_amount, recent_order_gross_profit, previous_order_gross_profit,
    recent_margin, previous_margin, recent_rank, previous_rank, rank_delta,
    fba_sellable_inventory, sellable_days, current_price, limit_price, limit_price_10,
    ad_spend, ad_sales, acos, tacos, estimated_boost_revenue, created_at, updated_at
)
with joined as (
    select
        coalesce(r.item_key, p.item_key) as item_key,
        coalesce(r.seller_name_new, p.seller_name_new) as seller_name_new,
        coalesce(r.seller_name, p.seller_name) as seller_name,
        coalesce(r.seller_sku_adj, p.seller_sku_adj) as seller_sku_adj,
        coalesce(r.country_category, p.country_category) as country_category,
        coalesce(r.country, p.country) as country,
        coalesce(r.local_sku, p.local_sku) as local_sku,
        coalesce(r.filter_flag, p.filter_flag, 1) as filter_flag,
        coalesce(r.over_limit_flag, p.over_limit_flag, 0) as over_limit_flag,
        coalesce(r.data_start, p.data_start) as recent_start,
        coalesce(r.data_end, p.data_end) as recent_end,
        coalesce(p.data_start, r.data_start) as previous_start,
        coalesce(p.data_end, r.data_end) as previous_end,
        coalesce(r.sales_qty, 0) as recent_sales_qty,
        coalesce(p.sales_qty, 0) as previous_sales_qty,
        coalesce(r.daily_sales, 0) as recent_daily_sales,
        coalesce(p.daily_sales, 0) as previous_daily_sales,
        coalesce(r.sales_amount, 0) as recent_sales_amount,
        coalesce(p.sales_amount, 0) as previous_sales_amount,
        coalesce(r.order_gross_profit, 0) as recent_order_gross_profit,
        coalesce(p.order_gross_profit, 0) as previous_order_gross_profit,
        r.margin as recent_margin,
        p.margin as previous_margin,
        r.avg_rank as recent_rank,
        p.avg_rank as previous_rank,
        coalesce(r.fba_sellable_inventory, p.fba_sellable_inventory, 0) as fba_sellable_inventory
    from etl_datasync.dashboard_alert_monthly_metric_snapshot r
    left join etl_datasync.dashboard_alert_monthly_metric_snapshot p
      on p.snapshot_date = r.snapshot_date
     and p.item_key = r.item_key
     and p.month_code = %(previous_month)s
    where r.snapshot_date = %(snapshot_date)s
      and r.month_code = %(recent_month)s
    union all
    select
        p.item_key, p.seller_name_new, p.seller_name, p.seller_sku_adj, p.country_category, p.country, p.local_sku,
        p.filter_flag, p.over_limit_flag, p.data_start, p.data_end, p.data_start, p.data_end,
        0, p.sales_qty, 0, p.daily_sales, 0, p.sales_amount, 0, p.order_gross_profit,
        null, p.margin, null, p.avg_rank, p.fba_sellable_inventory
    from etl_datasync.dashboard_alert_monthly_metric_snapshot p
    left join etl_datasync.dashboard_alert_monthly_metric_snapshot r
      on r.snapshot_date = p.snapshot_date
     and r.item_key = p.item_key
     and r.month_code = %(recent_month)s
    where p.snapshot_date = %(snapshot_date)s
      and p.month_code = %(previous_month)s
      and r.item_key is null
),
source_rows as (
    select
        j.*,
        coalesce(ps.current_price, 0) as current_price,
        coalesce(ps.limit_price, 0) as limit_price,
        coalesce(ps.limit_price_10, 0) as limit_price_10,
        coalesce(ps.over_limit_flag, j.over_limit_flag, 0) as current_over_limit_flag,
        coalesce(ps.ad_spend, 0) as ad_spend,
        coalesce(ps.ad_sales, 0) as ad_sales,
        coalesce(ps.acos, 0) as acos,
        coalesce(ps.tacos, 0) as tacos
    from joined j
    left join (
        select
            item_key,
            max(current_price) as current_price,
            max(limit_price) as limit_price,
            max(limit_price_10) as limit_price_10,
            max(over_limit_flag) as over_limit_flag,
            max(ad_spend) as ad_spend,
            max(ad_sales) as ad_sales,
            max(acos) as acos,
            max(tacos) as tacos
        from etl_datasync.dashboard_product_period_90d_snapshot
        where snapshot_date = %(snapshot_date)s
        group by item_key
    ) ps
      on ps.item_key = j.item_key
    where j.filter_flag = 1
),
classified as (
    select
        s.*,
        case when coalesce(s.recent_daily_sales, 0) > 0 then coalesce(s.fba_sellable_inventory, 0) / s.recent_daily_sales else 0 end as calc_sellable_days,
        case when s.previous_rank is not null and s.recent_rank is not null then s.previous_rank - s.recent_rank else 0 end as calc_rank_delta,
        case when s.previous_rank is not null and s.previous_rank > 0 and s.recent_rank is not null then (s.previous_rank - s.recent_rank) / s.previous_rank else 0 end as rank_improve_ratio,
        case when s.previous_daily_sales <> 0 then (s.recent_daily_sales - s.previous_daily_sales) / abs(s.previous_daily_sales) when s.recent_daily_sales > 0 then 1 else 0 end as sales_change_rate
    from source_rows s
),
opportunity as (
    select
        c.*,
        concat_ws(',',
            if(coalesce(c.recent_margin, 0) >= 0.25 and c.recent_daily_sales >= 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0, 'high_margin_scale', null),
            if(c.calc_rank_delta >= 5 and c.rank_improve_ratio >= 0.20 and c.calc_sellable_days >= 14, 'rank_improve', null),
            if(c.calc_sellable_days >= 30 and coalesce(c.recent_margin, 0) >= 0.15 and c.recent_daily_sales >= 0.5 and c.current_over_limit_flag = 0, 'inventory_push', null),
            if(coalesce(c.recent_margin, 0) >= 0.35 and c.recent_daily_sales < 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0, 'low_sales_high_margin', null),
            if((c.tacos <= 0.05 or (c.acos > 0 and c.acos <= 0.20)) and coalesce(c.recent_margin, 0) >= 0.20 and (c.recent_sales_amount > 0 or c.ad_spend > 0), 'ad_efficiency', null)
        ) as opportunity_types,
        case
            when coalesce(c.recent_margin, 0) >= 0.25 and c.recent_daily_sales >= 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0 then 'high_margin_scale'
            when c.calc_rank_delta >= 5 and c.rank_improve_ratio >= 0.20 and c.calc_sellable_days >= 14 then 'rank_improve'
            when c.calc_sellable_days >= 30 and coalesce(c.recent_margin, 0) >= 0.15 and c.recent_daily_sales >= 0.5 and c.current_over_limit_flag = 0 then 'inventory_push'
            when coalesce(c.recent_margin, 0) >= 0.35 and c.recent_daily_sales < 1 and c.calc_sellable_days >= 21 and c.current_over_limit_flag = 0 then 'low_sales_high_margin'
            when (c.tacos <= 0.05 or (c.acos > 0 and c.acos <= 0.20)) and coalesce(c.recent_margin, 0) >= 0.20 and (c.recent_sales_amount > 0 or c.ad_spend > 0) then 'ad_efficiency'
            else 'observe'
        end as opportunity_primary_type,
        case when c.calc_sellable_days >= 21 then 'enough' else 'short' end as opportunity_stock_status,
        round(greatest(0, least(100,
            least(greatest(coalesce(c.recent_margin, 0), 0) / 0.35, 1) * 25
            + (least(greatest(c.sales_change_rate, 0), 1) * 0.4 + least(c.recent_daily_sales / 5, 1) * 0.35 + least(c.recent_sales_amount / 50000, 1) * 0.25) * 25
            + least(greatest(c.rank_improve_ratio, 0), 0.5) / 0.5 * 20
            + case when c.calc_sellable_days < 14 then 0 when c.calc_sellable_days <= 60 then least((c.calc_sellable_days - 14) / 46, 1) * 20 else 18 end
            - if(c.current_over_limit_flag = 1, 4, 0)
            - if(c.tacos > 0.12, 3, 0)
            - if(c.calc_sellable_days < 14, 2, 0)
            - if(coalesce(c.recent_margin, 0) < 0.15, 1, 0)
        ))) as score,
        round(greatest(c.recent_daily_sales, 0) * least(greatest(c.calc_sellable_days, 0), 30) * 0.15 * if(c.recent_sales_qty > 0, c.recent_sales_amount / c.recent_sales_qty, 0), 4) as estimated_boost_revenue
    from classified c
)
select
    %(snapshot_date)s,
    %(comparison_code)s,
    'month',
    %(comparison_label)s,
    recent_start,
    recent_end,
    previous_start,
    previous_end,
    %(previous_month)s,
    %(recent_month)s,
    item_key,
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    filter_flag,
    current_over_limit_flag,
    opportunity_types,
    opportunity_primary_type,
    score,
    opportunity_stock_status,
    recent_sales_qty,
    previous_sales_qty,
    recent_daily_sales,
    previous_daily_sales,
    sales_change_rate,
    recent_sales_amount,
    previous_sales_amount,
    recent_order_gross_profit,
    previous_order_gross_profit,
    recent_margin,
    previous_margin,
    recent_rank,
    previous_rank,
    calc_rank_delta,
    fba_sellable_inventory,
    calc_sellable_days,
    current_price,
    limit_price,
    limit_price_10,
    ad_spend,
    ad_sales,
    acos,
    tacos,
    estimated_boost_revenue,
    now(),
    now()
from opportunity
where opportunity_types <> '';
"""

DELETE_OPPORTUNITY_COMPARISON_SUMMARY_SQL = """
delete from etl_datasync.dashboard_opportunity_comparison_summary
where snapshot_date = %(snapshot_date)s
  and comparison_code = %(comparison_code)s;
"""

INSERT_OPPORTUNITY_COMPARISON_SUMMARY_SQL = """
insert into etl_datasync.dashboard_opportunity_comparison_summary (
    snapshot_date, comparison_code, country, seller_name_new,
    opportunity_type, stock_status, opportunity_count, estimated_boost_revenue,
    created_at, updated_at
)
select
    snapshot_date,
    comparison_code,
    country,
    seller_name_new,
    primary_type,
    stock_status,
    count(*) as opportunity_count,
    sum(estimated_boost_revenue) as estimated_boost_revenue,
    now(),
    now()
from etl_datasync.dashboard_opportunity_comparison_snapshot
where snapshot_date = %(snapshot_date)s
  and comparison_code = %(comparison_code)s
group by snapshot_date, comparison_code, country, seller_name_new, primary_type, stock_status;
"""

DELETE_OLD_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_opportunity_comparison_snapshot
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_opportunity_comparison_snapshot
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_OLD_OPPORTUNITY_COMPARISON_SUMMARY_SQL = """
delete from etl_datasync.dashboard_opportunity_comparison_summary
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_opportunity_comparison_summary
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_alert_monthly_metric_snapshot
where snapshot_date = %(snapshot_date)s
  and month_code = %(month_code)s;
"""

INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_alert_monthly_metric_snapshot (
    snapshot_date, month_code, month_start, month_end, data_start, data_end, stat_days, is_month_complete,
    item_key, seller_name_new, seller_name, seller_sku_adj, country_category, country, local_sku,
    filter_flag, over_limit_flag, daily_sales_band, margin_band,
    sales_qty, daily_sales, sales_amount, daily_sales_amount, order_gross_profit, margin,
    avg_rank, fba_sellable_inventory, sellable_days,
    created_at, updated_at
)
with monthly as (
    select
        item_key,
        max(seller_name_new) as seller_name_new,
        max(seller_name) as seller_name,
        max(seller_sku_adj) as seller_sku_adj,
        max(country_category) as country_category,
        max(country) as country,
        max(local_sku) as local_sku,
        sum(sales_qty) as sales_qty,
        sum(sales_amount) as sales_amount,
        sum(order_gross_profit) as order_gross_profit,
        avg(case when ranking > 0 then ranking end) as avg_rank,
        max(afn_fulfillable_quantity) as fba_sellable_inventory
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(data_start)s and %(data_end)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
    group by item_key
),
period_flags as (
    select item_key, max(over_limit_flag) as over_limit_flag, max(filter_flag) as filter_flag
    from etl_datasync.dashboard_product_period_90d_snapshot
    where snapshot_date = %(snapshot_date)s
    group by item_key
),
metrics as (
    select
        m.*,
        coalesce(f.filter_flag, 1) as filter_flag,
        coalesce(f.over_limit_flag, 0) as over_limit_flag,
        m.sales_qty / nullif(%(stat_days)s, 0) as daily_sales,
        m.sales_amount / nullif(%(stat_days)s, 0) as daily_sales_amount,
        round(m.order_gross_profit / nullif(m.sales_amount, 0), 4) as margin
    from monthly m
    left join period_flags f on f.item_key = m.item_key
)
select
    %(snapshot_date)s,
    %(month_code)s,
    %(month_start)s,
    %(month_end)s,
    %(data_start)s,
    %(data_end)s,
    %(stat_days)s,
    %(is_month_complete)s,
    item_key,
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    filter_flag,
    over_limit_flag,
    case
        when daily_sales < 1 and daily_sales > 0 then '日销 <1'
        when daily_sales >= 1 and daily_sales < 5 then '日销 1-5'
        when daily_sales >= 5 then '日销 >5'
        else '日销 0'
    end as daily_sales_band,
    case
        when margin >= 0.35 then '毛利率 >35%%'
        when margin >= 0.25 and margin < 0.35 then '毛利率 25-35%%'
        when margin >= 0.15 and margin < 0.25 then '毛利率 15-25%%'
        when margin >= 0.10 and margin < 0.15 then '毛利率 10-15%%'
        when margin >= 0 and margin < 0.10 then '毛利率 0-10%%'
        else '毛利率 <0%%'
    end as margin_band,
    sales_qty,
    daily_sales,
    sales_amount,
    daily_sales_amount,
    order_gross_profit,
    margin,
    avg_rank,
    fba_sellable_inventory,
    case when daily_sales > 0 then fba_sellable_inventory / daily_sales else 0 end,
    now(),
    now()
from metrics;
"""

DELETE_OLD_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_alert_monthly_metric_snapshot
where snapshot_date not in (
    select snapshot_date
    from (
        select distinct snapshot_date
        from etl_datasync.dashboard_alert_monthly_metric_snapshot
        order by snapshot_date desc
        limit %(period_snapshot_retention_days)s
    ) keep_dates
);
"""

DELETE_ANNUAL_GOAL_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_annual_goal_snapshot
where snapshot_date = %(snapshot_date)s
  and goal_year = year(%(snapshot_date)s);
"""

INSERT_ANNUAL_GOAL_SNAPSHOT_SQL = f"""
insert into etl_datasync.dashboard_annual_goal_snapshot (
    snapshot_date, goal_year, year_start, data_end_date,
    sales_goal, margin_goal, sales_goal_buffer,
    sales_amount_ytd, sales_amount_ex_tax_ytd, order_gross_profit_ytd, order_gross_margin_ytd,
    target_amount_to_date, sales_goal_ratio, current_goal_ratio,
    created_at, updated_at
)
with calendar as (
    select
        year(%(snapshot_date)s) as goal_year,
        makedate(year(%(snapshot_date)s), 1) as year_start,
        str_to_date(concat(year(%(snapshot_date)s), '-12-31'), '%%Y-%%m-%%d') as year_end
),
ytd as (
    select
        coalesce(sum(p.sales_amount), 0) as sales_amount_ytd,
        coalesce(sum(p.sales_amount_ex_tax), 0) as sales_amount_ex_tax_ytd,
        coalesce(sum(p.order_gross_profit), 0) as order_gross_profit_ytd,
        max(p.dt_date) as data_end_date
    from etl_datasync.dashboard_product_performance_daily p
    join calendar c
      on p.dt_date between c.year_start and %(biz_date)s
    where p.seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(p.seller_sku_adj) between 5 and 10
),
monthly_goal as (
    select
        c.goal_year,
        coalesce(sum(g.sales_goal), {ANNUAL_SALES_GOAL:.2f}) as sales_goal,
        coalesce(round(sum(g.gross_profit_goal) / nullif(sum(g.sales_goal), 0), 4), {ANNUAL_MARGIN_GOAL:.4f}) as margin_goal,
        coalesce(
            sum(
                case
                    when g.goal_month < month(coalesce(y.data_end_date, %(biz_date)s)) then g.sales_goal
                    when g.goal_month = month(coalesce(y.data_end_date, %(biz_date)s))
                        then round(
                            g.sales_goal
                            * day(coalesce(y.data_end_date, %(biz_date)s))
                            / day(last_day(coalesce(y.data_end_date, %(biz_date)s))),
                            2
                        )
                    else 0
                end
            ),
            round({ANNUAL_SALES_GOAL:.2f} / (datediff(c.year_end, c.year_start) + 1) * {ANNUAL_SALES_GOAL_BUFFER:.4f} * dayofyear(%(snapshot_date)s), 2)
        ) as target_amount_to_date
    from calendar c
    cross join ytd y
    left join etl_datasync.dashboard_monthly_goal g
      on g.goal_year = c.goal_year
    group by c.goal_year, c.year_start, c.year_end, y.data_end_date
)
select
    %(snapshot_date)s as snapshot_date,
    c.goal_year,
    c.year_start,
    coalesce(y.data_end_date, c.year_start) as data_end_date,
    m.sales_goal as sales_goal,
    m.margin_goal as margin_goal,
    1.0000 as sales_goal_buffer,
    round(y.sales_amount_ytd, 2) as sales_amount_ytd,
    round(y.sales_amount_ex_tax_ytd, 2) as sales_amount_ex_tax_ytd,
    round(y.order_gross_profit_ytd, 2) as order_gross_profit_ytd,
    round(y.order_gross_profit_ytd / nullif(y.sales_amount_ytd, 0), 4) as order_gross_margin_ytd,
    round(m.target_amount_to_date, 2) as target_amount_to_date,
    round(y.sales_amount_ytd / nullif(m.sales_goal, 0), 4) as sales_goal_ratio,
    round(y.sales_amount_ytd / nullif(m.target_amount_to_date, 0), 4) as current_goal_ratio,
    now() as created_at,
    now() as updated_at
from calendar c
cross join ytd y
join monthly_goal m
  on m.goal_year = c.goal_year;
"""


def matrix_insert_sql(period_table_name: str) -> str:
    base_where = f"""
        from {period_table_name} p
        where p.snapshot_date = %(snapshot_date)s
          and p.period_start = %(period_start)s
          and p.period_end = %(period_end)s
          and p.filter_flag = 1
    """
    return f"""
insert into etl_datasync.dashboard_product_matrix_period_snapshot (
    snapshot_date, period_code, period_start, period_end,
    country, seller_name_new, over_limit_scope,
    margin_band, daily_sales_band, sku_count, over_limit_count
)
select
    %(snapshot_date)s as snapshot_date,
    %(period_code)s as period_code,
    %(period_start)s as period_start,
    %(period_end)s as period_end,
    x.country,
    x.seller_name_new,
    x.over_limit_scope,
    x.margin_band,
    x.daily_sales_band,
    count(*) as sku_count,
    sum(case when x.over_limit_flag = 1 then 1 else 0 end) as over_limit_count
from (
    select p.country, p.seller_name_new, 'all' as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select '{MATRIX_ALL_VALUE}' as country, p.seller_name_new, 'all' as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select p.country, '{MATRIX_ALL_VALUE}' as seller_name_new, 'all' as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select '{MATRIX_ALL_VALUE}' as country, '{MATRIX_ALL_VALUE}' as seller_name_new, 'all' as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select p.country, p.seller_name_new,
           case when p.over_limit_flag = 1 then 'yes' else 'no' end as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select '{MATRIX_ALL_VALUE}' as country, p.seller_name_new,
           case when p.over_limit_flag = 1 then 'yes' else 'no' end as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select p.country, '{MATRIX_ALL_VALUE}' as seller_name_new,
           case when p.over_limit_flag = 1 then 'yes' else 'no' end as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
    union all
    select '{MATRIX_ALL_VALUE}' as country, '{MATRIX_ALL_VALUE}' as seller_name_new,
           case when p.over_limit_flag = 1 then 'yes' else 'no' end as over_limit_scope,
           p.margin_band, p.daily_sales_band, p.over_limit_flag
    {base_where}
) x
group by
    x.country,
    x.seller_name_new,
    x.over_limit_scope,
    x.margin_band,
    x.daily_sales_band;
"""

DELETE_PRODUCT_DAILY_SQL = """
delete from etl_datasync.dashboard_product_performance_daily
where %(product_full_load)s = 1
   or dt_date between %(product_start_date)s and %(product_end_date)s;
"""

INSERT_PRODUCT_DAILY_SQL = """
insert into etl_datasync.dashboard_product_performance_daily (
    dt_year, dt_week, dt_month, dt_date, item_key, country, country_category,
    local_sku, seller_name, seller_name_new, seller_sku_adj,
    sales_qty, sales_amount, sales_amount_ex_tax,
    raw_order_gross_profit, order_gross_profit, abnormal_flag_count,
    settlement_gross_profit, afn_fulfillable_quantity,
    ad_spend, ad_orders, ad_sales, ad_clicks, ad_impressions,
    sessions_total, ranking, return_count, return_amount, net_amount,
    created_at, updated_at
)
with src as (
    select
        year(start_date) as dt_year,
        yearweek(start_date, 1) as dt_week,
        month(start_date) as dt_month,
        date(start_date) as dt_date,
        country,
        case
            when country = '英国' then '英国站'
            when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end as country_category,
        local_sku,
        seller_name,
        case
            when locate('-', seller_name) > 0 then left(seller_name, locate('-', seller_name) - 1)
            else seller_name
        end as seller_name_new,
        if(
            length(substring_index(seller_sku, ',', 1)) > 16,
            replace(substring_index(substring_index(seller_sku, ',', 1), '-', 1), 'amzn.gr.', ''),
            substring_index(seller_sku, ',', 1)
        ) as seller_sku_adj,
        coalesce(volume, 0) as volume,
        coalesce(amount, 0) as amount,
        case
            when country = '德国' then coalesce(amount, 0) / 1.19
            when country = '法国' then coalesce(amount, 0) / 1.2
            when country = '瑞典' then coalesce(amount, 0) / 1.25
            when country = '西班牙' then coalesce(amount, 0) / 1.21
            when country = '意大利' then coalesce(amount, 0) / 1.22
            when country = '英国' then coalesce(amount, 0) / 1.2
            when country = '比利时' then coalesce(amount, 0) / 1.21
            when country = '荷兰' then coalesce(amount, 0) / 1.21
            when country = '爱尔兰' then coalesce(amount, 0) / 1.23
            when country = '波兰' then coalesce(amount, 0) / 1.23
            when country = '墨西哥' then coalesce(amount, 0) / 1.16
            when country = '土耳其' then coalesce(amount, 0) / 1.20
            else coalesce(amount, 0)
        end as amount_ex_tax,
        coalesce(predict_gross_profit, 0) as predict_gross_profit,
        coalesce(gross_profit, 0) as gross_profit,
        coalesce(afn_fulfillable_quantity, 0) as afn_fulfillable_quantity,
        coalesce(spend, 0) as spend,
        coalesce(ad_order_quantity, 0) as ad_order_quantity,
        coalesce(ad_sales_amount, 0) as ad_sales_amount,
        coalesce(clicks, 0) as clicks,
        coalesce(impressions, 0) as impressions,
        coalesce(sessions_total, 0) as sessions_total,
        coalesce(`rank`, 0) as ranking,
        coalesce(return_count, 0) as return_count,
        coalesce(return_amount, 0) as return_amount,
        coalesce(net_amount, 0) as net_amount
    from dwd_datasync.lx_statistics_product_performance
    where (
        %(product_full_load)s = 1
        or (
            start_date >= %(product_start_date)s
            and start_date < %(next_product_end_date)s
        )
    )
      and seller_sku not like 'Amazon.Found%%'
)
select
    dt_year,
    dt_week,
    dt_month,
    dt_date,
    concat_ws('|', country, seller_name_new, seller_sku_adj, coalesce(local_sku, '')) as item_key,
    country,
    country_category,
    local_sku,
    max(seller_name) as seller_name,
    seller_name_new,
    seller_sku_adj,
    sum(volume) as sales_qty,
    sum(amount) as sales_amount,
    sum(amount_ex_tax) as sales_amount_ex_tax,
    sum(predict_gross_profit) as raw_order_gross_profit,
    sum(case when volume = 0 then 0 else predict_gross_profit end) as order_gross_profit,
    sum(case when (volume = 0 and predict_gross_profit != 0) or (amount < abs(predict_gross_profit)) then 1 else 0 end) as abnormal_flag_count,
    sum(gross_profit) as settlement_gross_profit,
    max(afn_fulfillable_quantity) as afn_fulfillable_quantity,
    sum(spend) as ad_spend,
    sum(ad_order_quantity) as ad_orders,
    sum(ad_sales_amount) as ad_sales,
    sum(clicks) as ad_clicks,
    sum(impressions) as ad_impressions,
    sum(sessions_total) as sessions_total,
    max(ranking) as ranking,
    sum(return_count) as return_count,
    sum(return_amount) as return_amount,
    sum(net_amount) as net_amount,
    now() as created_at,
    now() as updated_at
from src
group by
    dt_year,
    dt_week,
    dt_month,
    dt_date,
    country,
    country_category,
    seller_name_new,
    seller_sku_adj,
    local_sku;
"""

DELETE_RESTOCK_SQL = """
delete from etl_datasync.dashboard_restock_daily_snapshot
where snapshot_date = %(snapshot_date)s;
"""

INSERT_RESTOCK_SQL = """
insert into etl_datasync.dashboard_restock_daily_snapshot (
    snapshot_date, item_key, country_category, seller_sku_adj, seller_name_new,
    local_quantity, purchase_shipping_quantity, purchase_plan_quantity,
    local_valid_quantity, local_qc_quantity, purchase_cost, transport_cost,
    created_at, updated_at
)
select
    date(r.create_time) as snapshot_date,
    concat_ws('|', r.country_category, r.seller_name_new, r.seller_sku_adj) as item_key,
    r.country_category,
    r.seller_sku_adj,
    r.seller_name_new,
    coalesce(max(r.sc_quantity_local_valid), 0)
      + coalesce(max(r.sc_quantity_purchase_shipping), 0)
      + coalesce(max(r.sc_quantity_purchase_plan), 0)
      + coalesce(max(r.sc_quantity_local_qc), 0) as local_quantity,
    coalesce(max(r.sc_quantity_purchase_shipping), 0) as purchase_shipping_quantity,
    coalesce(max(r.sc_quantity_purchase_plan), 0) as purchase_plan_quantity,
    coalesce(max(r.sc_quantity_local_valid), 0) as local_valid_quantity,
    coalesce(max(r.sc_quantity_local_qc), 0) as local_qc_quantity,
    coalesce(max(c.cg_price), 0) as purchase_cost,
    coalesce(max(c.cg_transport_costs), 0) as transport_cost,
    now() as created_at,
    now() as updated_at
from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking r
left join etl_datasync.etl_dispose_lx_product_local_product_info c
  on substring_index(c.seller_sku, '-', 1) = r.seller_sku_adj
 and c.country_category = r.country_category
 and c.seller_name_new = r.seller_name_new
where r.create_time >= %(snapshot_date)s
  and r.create_time < %(next_snapshot_date)s
group by
    date(r.create_time),
    r.country_category,
    r.seller_sku_adj,
    r.seller_name_new;
"""

DELETE_INVENTORY_SQL = """
delete from etl_datasync.dashboard_inventory_daily_snapshot
where snapshot_date = %(snapshot_date)s;
"""

INSERT_INVENTORY_SQL = """
insert into etl_datasync.dashboard_inventory_daily_snapshot (
    snapshot_date, item_key, country_category, seller_sku_adj, seller_name_new,
    total, total_price, available_total, available_price, afn_fulfillable_quantity,
    reserved_fc_transfers, reserved_fc_processing, reserved_customerorders,
    afn_unsellable_quantity, afn_inbound_working_quantity, stock_up_num,
    stock_up_num_price, afn_researching_quantity, total_fulfillable_quantity,
    created_at, updated_at
)
select
    date(create_time) as snapshot_date,
    concat_ws('|', country_category, seller_name_new, seller_sku_adj) as item_key,
    country_category,
    seller_sku_adj,
    seller_name_new,
    sum(coalesce(total, 0)) as total,
    sum(coalesce(total_price, 0)) as total_price,
    sum(coalesce(available_total, 0)) as available_total,
    sum(coalesce(available_total_price, 0)) as available_price,
    sum(coalesce(afn_fulfillable_quantity, 0)) as afn_fulfillable_quantity,
    sum(coalesce(reserved_fc_transfers, 0)) as reserved_fc_transfers,
    sum(coalesce(reserved_fc_processing, 0)) as reserved_fc_processing,
    sum(coalesce(reserved_customerorders, 0)) as reserved_customerorders,
    sum(coalesce(afn_unsellable_quantity, 0)) as afn_unsellable_quantity,
    sum(coalesce(afn_inbound_working_quantity, 0)) as afn_inbound_working_quantity,
    sum(coalesce(stock_up_num, 0)) as stock_up_num,
    sum(coalesce(stock_up_num_price, 0)) as stock_up_num_price,
    sum(coalesce(afn_researching_quantity, 0)) as afn_researching_quantity,
    sum(coalesce(total_fulfillable_quantity, 0)) as total_fulfillable_quantity,
    now() as created_at,
    now() as updated_at
from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
where create_time >= %(snapshot_date)s
  and create_time < %(next_snapshot_date)s
group by
    date(create_time),
    country_category,
    seller_sku_adj,
    seller_name_new;
"""

DELETE_LISTING_PRICE_SQL = """
delete from etl_datasync.dashboard_listing_price_daily_snapshot
where snapshot_date = %(snapshot_date)s;
"""

INSERT_LISTING_PRICE_SQL = """
insert into etl_datasync.dashboard_listing_price_daily_snapshot (
    snapshot_date, item_key, seller_name_new, seller_name, seller_sku,
    country_category, country, price, org_currency_icon, price_cny,
    created_at, updated_at
)
select
    l.dt_date as snapshot_date,
    concat_ws('|', l.country_category, l.marketplace, l.seller_name_new, l.seller_sku) as item_key,
    l.seller_name_new,
    max(l.seller_name) as seller_name,
    l.seller_sku,
    l.country_category,
    l.marketplace as country,
    max(l.price) as price,
    max(l.org_currency_icon) as org_currency_icon,
    max(round(l.price * c.rate_org, 2)) as price_cny,
    now() as created_at,
    now() as updated_at
from (
    select
        year(create_time) as dt_year,
        month(create_time) as dt_month,
        yearweek(create_time, 1) as dt_week,
        date(create_time) as dt_date,
        left(seller_name, locate('-', seller_name) - 1) as seller_name_new,
        seller_name,
        seller_sku,
        case
            when marketplace = '英国' then '英国站'
            when marketplace in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
            else '欧洲站'
        end as country_category,
        marketplace,
        cast(nullif(landed_price, '') as decimal(18,4)) as price,
        case
            when marketplace in ('德国', '法国', '荷兰', '比利时', '西班牙', '意大利', '爱尔兰') then '欧元'
            when marketplace = '波兰' then '波兰兹罗提'
            when marketplace = '瑞典' then '瑞典克朗'
            when marketplace = '土耳其' then '土耳其里拉'
            when marketplace = '英国' then '英镑'
            when marketplace = '美国' then '美元'
            when marketplace = '加拿大' then '加元'
            when marketplace = '墨西哥' then '墨西哥比索'
            when marketplace = '巴西' then '巴西雷亚尔'
            else null
        end as org_currency_icon
    from dwd_datasync.lx_sales_mws_listing
    where create_time >= %(snapshot_date)s
      and create_time < %(next_snapshot_date)s
) l
left join dwd_datasync.lx_basic_currency c
  on l.org_currency_icon = c.name
 and c.date = date_format(%(snapshot_date)s, '%%Y-%%m')
group by
    l.dt_date,
    l.country_category,
    l.marketplace,
    l.seller_name_new,
    l.seller_sku;
"""

DELETE_LIMIT_PRICE_SQL = """
delete from etl_datasync.dashboard_limit_price_daily_snapshot
where snapshot_date = %(snapshot_date)s;
"""

INSERT_LIMIT_PRICE_SQL = """
insert into etl_datasync.dashboard_limit_price_daily_snapshot (
    snapshot_date, item_key, local_sku, seller_sku, seller_name_new,
    country, country_category, shipping_method, target_margin, currency,
    tax_inclusive_price, tax_inclusive_price_noad, tax_inclusive_price_adj,
    margin_price_35, margin_price_30, margin_price_25, margin_price_20,
    margin_price_15, margin_price_10, margin_price_5, margin_price_0,
    created_at, updated_at
)
select
    %(snapshot_date)s as snapshot_date,
    concat_ws(
        '|',
        country_category,
        country,
        seller_name_new,
        seller_sku,
        coalesce(local_sku, '')
    ) as item_key,
    local_sku,
    seller_sku,
    seller_name_new,
    country,
    country_category,
    null as shipping_method,
    0.35 as target_margin,
    max(currency) as currency,
    round(max(margin_price_35), 2) as tax_inclusive_price,
    round(max(margin_price_35), 2) as tax_inclusive_price_noad,
    round(max(margin_price_35_adj), 2) as tax_inclusive_price_adj,
    round(max(margin_price_35), 2) as margin_price_35,
    round(max(margin_price_30), 2) as margin_price_30,
    round(max(margin_price_25), 2) as margin_price_25,
    round(max(margin_price_20), 2) as margin_price_20,
    round(max(margin_price_15), 2) as margin_price_15,
    round(max(margin_price_10), 2) as margin_price_10,
    round(max(margin_price_5), 2) as margin_price_5,
    round(max(margin_price_0), 2) as margin_price_0,
    now() as created_at,
    now() as updated_at
from (
    select
        sku as local_sku,
        msku as seller_sku,
        新店铺 as seller_name_new,
        国家 as country,
        国家类别 as country_category,
        币种 as currency,
        listing价格 as listing_price,
        `35毛利润价格` as margin_price_35,
        `30毛利润价格` as margin_price_30,
        `25毛利润价格` as margin_price_25,
        `20毛利润价格` as margin_price_20,
        `15毛利润价格` as margin_price_15,
        `10毛利润价格` as margin_price_10,
        `5毛利润价格` as margin_price_5,
        `0毛利润价格` as margin_price_0,
        `35毛利润含广告定价` as margin_price_35_adj
    from temporary_dwd.`在库节点_输出定价表`
) limit_price_source
where seller_sku is not null
  and seller_sku <> ''
  and seller_name_new is not null
  and seller_name_new <> ''
  and country is not null
  and country <> ''
  and country_category is not null
  and country_category <> ''
group by
    local_sku,
    seller_sku,
    seller_name_new,
    country,
    country_category;
"""

DELETE_PERIOD_SNAPSHOT_SQL = """
delete from etl_datasync.dashboard_product_period_snapshot
where snapshot_date = %(snapshot_date)s
  and period_start = %(period_start)s
  and period_end = %(period_end)s;
"""

INSERT_PERIOD_SNAPSHOT_SQL = """
insert into etl_datasync.dashboard_product_period_snapshot (
    snapshot_date, period_start, period_end, item_key, stat_period,
    seller_name_new, seller_name, seller_sku_adj, country_category, country, local_sku,
    sales_qty, sales_amount, sales_amount_ex_tax,
    order_gross_profit, raw_order_gross_profit, order_gross_margin, margin_band,
    settlement_gross_profit, filter_flag,
    current_price_cny, price_currency, current_price, limit_price, limit_price_10, limit_price_adj,
    over_limit_flag, shipping_method, target_margin, limit_price_without_ad,
    in_stock_days, stat_days, abnormal_days, all_abnormal_flag,
    daily_sales, daily_sales_in_stock_days, daily_sales_in_stock_band, daily_sales_band,
    ad_spend, ad_orders, ad_sales, ad_clicks, ad_impressions, acos, tacos, ctr,
    fba_total_inventory, fba_total_inventory_cost,
    fba_available_inventory, fba_available_inventory_cost,
    fba_sellable_inventory, pending_transfer, transferring_qty, pending_shipment,
    unsellable_inventory, planned_inbound, actual_in_transit, under_investigation,
    total_available_inventory, local_sellable_inventory, local_stock_sellable_days,
    created_at, updated_at
)
with product_period as (
    select
        concat_ws('|', country, seller_name_new, seller_sku_adj, coalesce(local_sku, '')) as item_key,
        country,
        country_category,
        local_sku,
        max(seller_name) as seller_name,
        seller_name_new,
        seller_sku_adj,
        sum(sales_qty) as sales_qty,
        sum(sales_amount) as sales_amount,
        sum(sales_amount_ex_tax) as sales_amount_ex_tax,
        sum(order_gross_profit) as order_gross_profit,
        sum(raw_order_gross_profit) as raw_order_gross_profit,
        round(sum(order_gross_profit) / nullif(sum(sales_amount), 0), 4) as order_gross_margin,
        sum(settlement_gross_profit) as settlement_gross_profit,
        max(afn_fulfillable_quantity) as period_afn_fulfillable_quantity,
        sum(case when afn_fulfillable_quantity <> 0 then 1 else 0 end) as in_stock_days,
        datediff(%(period_end)s, %(period_start)s) + 1 as stat_days,
        sum(sales_qty) / nullif(datediff(%(period_end)s, %(period_start)s) + 1, 0) as daily_sales,
        sum(abnormal_flag_count) as abnormal_days,
        sum(sales_qty) / nullif(sum(case when afn_fulfillable_quantity <> 0 then 1 else 0 end), 0) as daily_sales_in_stock_days,
        sum(ad_spend) as ad_spend,
        sum(ad_orders) as ad_orders,
        sum(ad_sales) as ad_sales,
        sum(ad_clicks) as ad_clicks,
        sum(ad_impressions) as ad_impressions,
        round(sum(ad_spend) / nullif(sum(ad_sales), 0), 4) as acos,
        round(sum(ad_spend) / nullif(sum(sales_amount), 0), 4) as tacos,
        round(sum(ad_clicks) / nullif(sum(ad_impressions), 0), 4) as ctr
    from etl_datasync.dashboard_product_performance_daily
    where dt_date between %(period_start)s and %(period_end)s
      and seller_name_new not regexp 'baihuiyi|Yuanoboo|Bailboo|Qianytyy'
      and char_length(seller_sku_adj) between 5 and 10
    group by
        seller_name_new,
        seller_sku_adj,
        country_category,
        country,
        local_sku
),
effective_snapshot_dates as (
    select
        (
            select max(snapshot_date)
            from etl_datasync.dashboard_restock_daily_snapshot
            where snapshot_date <= %(snapshot_date)s
        ) as restock_snapshot_date,
        (
            select max(snapshot_date)
            from etl_datasync.dashboard_inventory_daily_snapshot
            where snapshot_date <= %(snapshot_date)s
        ) as inventory_snapshot_date,
        (
            select max(snapshot_date)
            from etl_datasync.dashboard_listing_price_daily_snapshot
            where snapshot_date <= %(snapshot_date)s
        ) as listing_snapshot_date,
        (
            select max(snapshot_date)
            from etl_datasync.dashboard_limit_price_daily_snapshot
            where snapshot_date <= %(snapshot_date)s
        ) as limit_snapshot_date
),
joined as (
    select
        p.*,
        r.local_quantity,
        i.total as inv_total,
        i.total_price,
        i.available_total,
        i.available_price,
        i.afn_fulfillable_quantity,
        i.reserved_fc_transfers,
        i.reserved_fc_processing,
        i.reserved_customerorders,
        i.afn_unsellable_quantity,
        i.afn_inbound_working_quantity,
        i.stock_up_num,
        i.afn_researching_quantity,
        i.total_fulfillable_quantity,
        lp.price as current_price,
        lp.price_cny as current_price_cny,
        lp.org_currency_icon as price_currency,
        lim.tax_inclusive_price as limit_price,
        lim.margin_price_10 as limit_price_10,
        lim.tax_inclusive_price_noad as limit_price_without_ad,
        lim.tax_inclusive_price_adj as limit_price_adj,
        lim.shipping_method,
        lim.target_margin
    from product_period p
    cross join effective_snapshot_dates ed
    left join etl_datasync.dashboard_restock_daily_snapshot r
      on r.snapshot_date = ed.restock_snapshot_date
     and p.country_category = r.country_category
     and p.seller_sku_adj = r.seller_sku_adj
     and p.seller_name_new = r.seller_name_new
    left join etl_datasync.dashboard_inventory_daily_snapshot i
      on i.snapshot_date = ed.inventory_snapshot_date
     and p.country_category = i.country_category
     and p.seller_sku_adj = i.seller_sku_adj
     and p.seller_name_new = i.seller_name_new
    left join etl_datasync.dashboard_listing_price_daily_snapshot lp
      on lp.snapshot_date = ed.listing_snapshot_date
     and p.country_category = lp.country_category
     and binary p.seller_sku_adj = binary lp.seller_sku
     and p.seller_name_new = lp.seller_name_new
     and p.country = lp.country
    left join etl_datasync.dashboard_limit_price_daily_snapshot lim
      on lim.snapshot_date = ed.limit_snapshot_date
     and p.country_category = lim.country_category
     and p.seller_sku_adj = lim.seller_sku
     and p.seller_name_new = lim.seller_name_new
     and p.country = lim.country
     and coalesce(p.local_sku, '') = coalesce(lim.local_sku, '')
)
select
    %(snapshot_date)s as snapshot_date,
    %(period_start)s as period_start,
    %(period_end)s as period_end,
    item_key,
    concat(%(period_start)s, '-', %(period_end)s) as stat_period,
    seller_name_new,
    seller_name,
    seller_sku_adj,
    country_category,
    country,
    local_sku,
    sales_qty,
    sales_amount,
    sales_amount_ex_tax,
    order_gross_profit,
    raw_order_gross_profit,
    order_gross_margin,
    case
        when order_gross_margin >= 0.35 then '毛利率 >35%%'
        when order_gross_margin >= 0.25 and order_gross_margin < 0.35 then '毛利率 25-35%%'
        when order_gross_margin >= 0.15 and order_gross_margin < 0.25 then '毛利率 15-25%%'
        when order_gross_margin >= 0.10 and order_gross_margin < 0.15 then '毛利率 10-15%%'
        when order_gross_margin >= 0 and order_gross_margin < 0.10 then '毛利率 0-10%%'
        else '毛利率 <0%%'
    end as margin_band,
    settlement_gross_profit,
    case
        when sales_qty > 0 or (coalesce(local_quantity, 0) + coalesce(inv_total, 0)) > 0 then 1
        else 0
    end as filter_flag,
    current_price_cny,
    price_currency,
    current_price,
    limit_price,
    limit_price_10,
    limit_price_adj,
    case when current_price > nullif(limit_price, 0) then 1 else 0 end as over_limit_flag,
    shipping_method,
    target_margin,
    limit_price_without_ad,
    in_stock_days,
    stat_days,
    abnormal_days,
    case when stat_days = abnormal_days then 1 else 0 end as all_abnormal_flag,
    daily_sales,
    daily_sales_in_stock_days,
    case
        when daily_sales_in_stock_days < 1 and daily_sales_in_stock_days > 0 then '日销 <1'
        when daily_sales_in_stock_days >= 1 and daily_sales_in_stock_days < 5 then '日销 1-5'
        when daily_sales_in_stock_days >= 5 then '日销 >5'
        else '日销 0'
    end as daily_sales_in_stock_band,
    case
        when daily_sales < 1 and daily_sales > 0 then '日销 <1'
        when daily_sales >= 1 and daily_sales < 5 then '日销 1-5'
        when daily_sales >= 5 then '日销 >5'
        else '日销 0'
    end as daily_sales_band,
    ad_spend,
    ad_orders,
    ad_sales,
    ad_clicks,
    ad_impressions,
    acos,
    tacos,
    ctr,
    coalesce(inv_total, 0) as fba_total_inventory,
    coalesce(total_price, 0) as fba_total_inventory_cost,
    coalesce(available_total, 0) as fba_available_inventory,
    coalesce(available_price, 0) as fba_available_inventory_cost,
    coalesce(afn_fulfillable_quantity, 0) as fba_sellable_inventory,
    coalesce(reserved_fc_transfers, 0) as pending_transfer,
    coalesce(reserved_fc_processing, 0) as transferring_qty,
    coalesce(reserved_customerorders, 0) as pending_shipment,
    coalesce(afn_unsellable_quantity, 0) as unsellable_inventory,
    coalesce(afn_inbound_working_quantity, 0) as planned_inbound,
    coalesce(stock_up_num, 0) as actual_in_transit,
    coalesce(afn_researching_quantity, 0) as under_investigation,
    coalesce(total_fulfillable_quantity, 0) as total_available_inventory,
    coalesce(local_quantity, 0) as local_sellable_inventory,
    case
        when (coalesce(local_quantity, 0) + coalesce(inv_total, 0)) > 0
             and (sales_qty = 0 or in_stock_days = 0)
            then 99999
        when (coalesce(local_quantity, 0) + coalesce(inv_total, 0)) > 0
             and (sales_qty > 0 and in_stock_days > 0)
            then round((coalesce(local_quantity, 0) + coalesce(inv_total, 0)) / nullif(daily_sales_in_stock_days, 0), 0)
        when (coalesce(local_quantity, 0) + coalesce(inv_total, 0)) = 0
            then 0
    end as local_stock_sellable_days,
    now() as created_at,
    now() as updated_at
from joined;
"""

DDL_STATEMENTS = (
    CREATE_SCHEMA_SQL,
    CREATE_LOG_TABLE_SQL,
    CREATE_PRODUCT_DAILY_SQL,
    CREATE_RESTOCK_SQL,
    CREATE_INVENTORY_SQL,
    CREATE_INVENTORY_WEEKLY_SQL,
    CREATE_LISTING_PRICE_SQL,
    CREATE_LIMIT_PRICE_SQL,
    CREATE_PERIOD_SNAPSHOT_SQL,
    *(period_create_sql(table_name) for table_name in PERIOD_PRESET_TABLES.values()),
    CREATE_MATRIX_PERIOD_SNAPSHOT_SQL,
    CREATE_ALERT_COMPARISON_SNAPSHOT_SQL,
    CREATE_ALERT_COMPARISON_SUMMARY_SQL,
    CREATE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL,
    CREATE_OPPORTUNITY_COMPARISON_SUMMARY_SQL,
    CREATE_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL,
    CREATE_MONTHLY_GOAL_SQL,
    CREATE_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL,
    CREATE_GOAL_DIMENSION_SNAPSHOT_SQL,
    CREATE_ANNUAL_GOAL_SNAPSHOT_SQL,
)

TABLE_COMMENTS = {}
COLUMN_COMMENTS = {}

PRODUCT_DAILY_COLUMNS = (
    "dt_year", "dt_week", "dt_month", "dt_date", "item_key", "country", "country_category",
    "local_sku", "seller_name", "seller_name_new", "seller_sku_adj",
    "sales_qty", "sales_amount", "sales_amount_ex_tax",
    "raw_order_gross_profit", "order_gross_profit", "abnormal_flag_count",
    "settlement_gross_profit", "afn_fulfillable_quantity",
    "ad_spend", "ad_orders", "ad_sales", "ad_clicks", "ad_impressions",
    "sessions_total", "ranking", "return_count", "return_amount", "net_amount",
    "created_at", "updated_at",
)

RESTOCK_COLUMNS = (
    "snapshot_date", "item_key", "country_category", "seller_sku_adj", "seller_name_new",
    "local_quantity", "purchase_shipping_quantity", "purchase_plan_quantity",
    "local_valid_quantity", "local_qc_quantity", "purchase_cost", "transport_cost",
    "created_at", "updated_at",
)

INVENTORY_COLUMNS = (
    "snapshot_date", "item_key", "country_category", "seller_sku_adj", "seller_name_new",
    "total", "total_price", "available_total", "available_price", "afn_fulfillable_quantity",
    "reserved_fc_transfers", "reserved_fc_processing", "reserved_customerorders",
    "afn_unsellable_quantity", "afn_inbound_working_quantity", "stock_up_num", "stock_up_num_price",
    "afn_researching_quantity", "total_fulfillable_quantity",
    "created_at", "updated_at",
)

INVENTORY_WEEKLY_COLUMNS = (
    "snapshot_date", "week_start", "week_end", "item_key", "country_category", "seller_sku_adj", "seller_name_new",
    "available_quantity", "available_cost", "transit_quantity", "transit_cost",
    "warehouse_quantity", "warehouse_cost", "plan_quantity", "plan_cost",
    "created_at", "updated_at",
)

LISTING_PRICE_COLUMNS = (
    "snapshot_date", "item_key", "seller_name_new", "seller_name", "seller_sku",
    "country_category", "country", "price", "org_currency_icon", "price_cny",
    "created_at", "updated_at",
)

LIMIT_PRICE_COLUMNS = (
    "snapshot_date", "item_key", "local_sku", "seller_sku", "seller_name_new",
    "country", "country_category", "shipping_method", "target_margin", "currency",
    "tax_inclusive_price", "tax_inclusive_price_noad", "tax_inclusive_price_adj",
    "margin_price_35", "margin_price_30", "margin_price_25", "margin_price_20",
    "margin_price_15", "margin_price_10", "margin_price_5", "margin_price_0",
    "created_at", "updated_at",
)


def extract_source_select(insert_sql: str) -> str:
    match = re.search(r"\n\s*(with|select)\b", insert_sql, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Cannot find source SELECT in INSERT SQL")
    return insert_sql[match.start() + 1:]


STEPS = {
    "product_performance_daily": SourceLoadStep(
        "product_performance_daily",
        DELETE_PRODUCT_DAILY_SQL,
        extract_source_select(INSERT_PRODUCT_DAILY_SQL),
        "etl_datasync.dashboard_product_performance_daily",
        PRODUCT_DAILY_COLUMNS,
    ),
    "monthly_goal_actual_snapshot": SqlStep(
        "monthly_goal_actual_snapshot",
        (DELETE_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL, INSERT_MONTHLY_GOAL_ACTUAL_SNAPSHOT_SQL),
    ),
    "goal_dimension_snapshot": SqlStep(
        "goal_dimension_snapshot",
        (DELETE_GOAL_DIMENSION_SNAPSHOT_SQL, INSERT_GOAL_DIMENSION_SNAPSHOT_SQL),
    ),
    "annual_goal_snapshot": SqlStep(
        "annual_goal_snapshot",
        (DELETE_ANNUAL_GOAL_SNAPSHOT_SQL, INSERT_ANNUAL_GOAL_SNAPSHOT_SQL),
    ),
    "inventory_weekly_snapshot": SqlStep(
        "inventory_weekly_snapshot",
        (DELETE_INVENTORY_WEEKLY_SNAPSHOT_SQL, INSERT_INVENTORY_WEEKLY_SNAPSHOT_SQL),
    ),
    "inventory_weekly_remote_snapshot": SourceLoadStep(
        "inventory_weekly_remote_snapshot",
        DELETE_INVENTORY_WEEKLY_REMOTE_SQL,
        SELECT_INVENTORY_WEEKLY_REMOTE_SQL,
        "etl_datasync.dashboard_inventory_weekly_snapshot",
        INVENTORY_WEEKLY_COLUMNS,
    ),
    "restock_snapshot": SourceLoadStep(
        "restock_snapshot",
        DELETE_RESTOCK_SQL,
        extract_source_select(INSERT_RESTOCK_SQL),
        "etl_datasync.dashboard_restock_daily_snapshot",
        RESTOCK_COLUMNS,
    ),
    "inventory_snapshot": SourceLoadStep(
        "inventory_snapshot",
        DELETE_INVENTORY_SQL,
        extract_source_select(INSERT_INVENTORY_SQL),
        "etl_datasync.dashboard_inventory_daily_snapshot",
        INVENTORY_COLUMNS,
    ),
    "listing_price_snapshot": SourceLoadStep(
        "listing_price_snapshot",
        DELETE_LISTING_PRICE_SQL,
        extract_source_select(INSERT_LISTING_PRICE_SQL),
        "etl_datasync.dashboard_listing_price_daily_snapshot",
        LISTING_PRICE_COLUMNS,
    ),
    "limit_price_snapshot": SourceLoadStep(
        "limit_price_snapshot",
        DELETE_LIMIT_PRICE_SQL,
        extract_source_select(INSERT_LIMIT_PRICE_SQL),
        "etl_datasync.dashboard_limit_price_daily_snapshot",
        LIMIT_PRICE_COLUMNS,
    ),
    "period_snapshot": SqlStep(
        "period_snapshot",
        (DELETE_PERIOD_SNAPSHOT_SQL, INSERT_PERIOD_SNAPSHOT_SQL),
    ),
    "period_preset_snapshots": PeriodPresetStep("period_preset_snapshots"),
    "alert_comparison_snapshots": AlertComparisonStep("alert_comparison_snapshots"),
    "alert_monthly_metric_snapshots": AlertMonthlyMetricStep("alert_monthly_metric_snapshots"),
    "opportunity_comparison_snapshots": OpportunityComparisonStep("opportunity_comparison_snapshots"),
    "price_review_source_load": PriceReviewStep("price_review_source_load"),
    "price_review_tracking": PriceReviewStep("price_review_tracking"),
}

def escape_sql_comment(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")


def create_table_name(sql: str) -> str | None:
    match = re.search(
        r"create\s+table\s+if\s+not\s+exists\s+(?:`?[A-Za-z0-9_]+`?\.)?`?([A-Za-z0-9_]+)`?\s*\(",
        sql,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def with_mysql_comments(sql: str) -> str:
    table_name = create_table_name(sql)
    if not table_name:
        return sql

    lines = []
    for line in sql.splitlines():
        stripped = line.lstrip()
        column_match = re.match(r"`?([A-Za-z0-9_]+)`?\s+", stripped)
        column_name = column_match.group(1) if column_match else ""
        comment = COLUMN_COMMENTS.get(column_name)
        if comment and " comment " not in stripped.lower():
            comma = "," if line.rstrip().endswith(",") else ""
            body = line.rstrip()[:-1] if comma else line.rstrip()
            line = f"{body} comment '{escape_sql_comment(comment)}'{comma}"
        lines.append(line)

    rendered = "\n".join(lines)
    table_comment = TABLE_COMMENTS.get(table_name)
    if table_comment and " comment=" not in rendered.lower():
        rendered = re.sub(
            r"\)\s*engine=InnoDB\s+default\s+charset=utf8mb4\s*;",
            f") engine=InnoDB default charset=utf8mb4 comment='{escape_sql_comment(table_comment)}';",
            rendered,
            count=1,
            flags=re.IGNORECASE,
        )
    return rendered


def ensure_tables(conn, schemas: SchemaConfig) -> None:
    with conn.cursor() as cursor:
        for sql in DDL_STATEMENTS:
            cursor.execute(with_mysql_comments(render_sql(sql, schemas)))
        ensure_inventory_weekly_columns(cursor, schemas)
    conn.commit()


def ensure_inventory_weekly_columns(cursor, schemas: SchemaConfig) -> None:
    column_specs = {
        "dashboard_restock_daily_snapshot": [
            ("purchase_shipping_quantity", "decimal(18,4) not null default 0", "local_quantity"),
            ("purchase_plan_quantity", "decimal(18,4) not null default 0", "purchase_shipping_quantity"),
            ("local_valid_quantity", "decimal(18,4) not null default 0", "purchase_plan_quantity"),
            ("local_qc_quantity", "decimal(18,4) not null default 0", "local_valid_quantity"),
            ("purchase_cost", "decimal(18,4) not null default 0", "local_qc_quantity"),
            ("transport_cost", "decimal(18,4) not null default 0", "purchase_cost"),
        ],
        "dashboard_inventory_daily_snapshot": [
            ("stock_up_num_price", "decimal(18,4) not null default 0", "stock_up_num"),
        ],
        "dashboard_limit_price_daily_snapshot": [
            ("margin_price_30", "decimal(18,2) null", "margin_price_35"),
            ("margin_price_25", "decimal(18,2) null", "margin_price_30"),
            ("margin_price_20", "decimal(18,2) null", "margin_price_25"),
            ("margin_price_15", "decimal(18,2) null", "margin_price_20"),
            ("margin_price_5", "decimal(18,2) null", "margin_price_10"),
            ("margin_price_0", "decimal(18,2) null", "margin_price_5"),
        ],
    }
    for table_name, specs in column_specs.items():
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = %(schema)s
              and table_name = %(table)s
            """,
            {"schema": schemas.target_schema, "table": table_name},
        )
        existing = {
            next(iter(row.values())) if isinstance(row, dict) else row[0]
            for row in cursor.fetchall()
        }
        for column_name, definition, after_column in specs:
            if column_name in existing:
                continue
            comment = COLUMN_COMMENTS.get(column_name)
            comment_sql = f" comment '{escape_sql_comment(comment)}'" if comment else ""
            cursor.execute(
                f"alter table `{schemas.target_schema}`.`{table_name}` "
                f"add column `{column_name}` {definition}{comment_sql} after `{after_column}`"
            )
            existing.add(column_name)


def log_task(
    conn,
    schemas: SchemaConfig,
    task_name: str,
    params: dict[str, object],
    status: str,
    affected_rows: int,
    started_at: datetime,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                """
            insert into etl_datasync.dashboard_etl_task_log (
                task_name, biz_date, snapshot_date, period_start, period_end,
                status, affected_rows, started_at, finished_at, error_message
            )
            values (
                %(task_name)s, %(biz_date)s, %(snapshot_date)s, %(period_start)s, %(period_end)s,
                %(status)s, %(affected_rows)s, %(started_at)s, now(), %(error_message)s
            );
            """,
                schemas,
            ),
            {
                "task_name": task_name,
                "biz_date": params["biz_date"],
                "snapshot_date": params["snapshot_date"],
                "period_start": params["period_start"],
                "period_end": params["period_end"],
                "status": status,
                "affected_rows": affected_rows,
                "started_at": started_at,
                "error_message": (error_message or "")[:8000] if error_message else None,
            },
        )
    conn.commit()


def assert_source_select_only(sql: str) -> None:
    stripped = sql.lstrip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise RuntimeError("Source connection can only execute SELECT/WITH statements")
    blocked = ("insert ", "update ", "delete ", "drop ", "create ", "alter ", "truncate ", "replace ")
    if any(token in stripped for token in blocked):
        raise RuntimeError("Blocked non-read statement on source connection")


def build_target_insert_sql(table: str, columns: tuple[str, ...], schemas: SchemaConfig) -> str:
    rendered_table = render_sql(table, schemas)
    column_list = ", ".join(columns)
    placeholders = ", ".join(f"%({column})s" for column in columns)
    return f"insert into {rendered_table} ({column_list}) values ({placeholders})"


def execute_target_step(conn, schemas: SchemaConfig, step: SqlStep, params: dict[str, object]) -> None:
    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            for statement in step.statements:
                cursor.execute(render_sql(statement, schemas), params)
                if statement.lstrip().lower().startswith("insert"):
                    affected_rows += max(cursor.rowcount, 0)
        conn.commit()
        log_task(conn, schemas, step.name, params, "success", affected_rows, started_at)
        print(f"[success] {step.name}: affected_rows={affected_rows}")
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(conn, schemas, step.name, params, "failed", affected_rows, started_at, error)
        print(f"[failed] {step.name}", file=sys.stderr)
        raise


def build_period_preset_params(params: dict[str, object]) -> dict[str, dict[str, object]]:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")

    month_start = date(biz_date.year, biz_date.month, 1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = date(last_month_end.year, last_month_end.month, 1)

    presets = {
        "last_7_days": (biz_date - timedelta(days=6), biz_date),
        "last_14_days": (biz_date - timedelta(days=13), biz_date),
        "last_30_days": (biz_date - timedelta(days=29), biz_date),
        "last_90_days": (biz_date - timedelta(days=89), biz_date),
        "last_month": (last_month_start, last_month_end),
    }
    result: dict[str, dict[str, object]] = {}
    for preset_name, (period_start, period_end) in presets.items():
        next_params = dict(params)
        next_params["period_start"] = period_start
        next_params["period_end"] = period_end
        result[preset_name] = next_params
    return result


def build_previous_period_params(preset_name: str, preset_params: dict[str, object]) -> dict[str, object]:
    period_start = preset_params["period_start"]
    period_end = preset_params["period_end"]
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise RuntimeError("period_start and period_end must be dates")

    previous_end = period_start - timedelta(days=1)
    if preset_name == "last_month":
        previous_start = date(previous_end.year, previous_end.month, 1)
    else:
        days = (period_end - period_start).days + 1
        previous_start = previous_end - timedelta(days=days - 1)

    previous_params = dict(preset_params)
    previous_params["period_start"] = previous_start
    previous_params["period_end"] = previous_end
    return previous_params


def build_alert_comparison_params(params: dict[str, object]) -> list[dict[str, object]]:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")

    comparisons: list[dict[str, object]] = []
    for days in (7, 14, 30, 60, 90):
        recent_end = biz_date
        recent_start = recent_end - timedelta(days=days - 1)
        previous_end = recent_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)
        next_params = dict(params)
        next_params.update(
            {
                "comparison_code": f"d{days}",
                "comparison_type": "days",
                "comparison_label": f"近{days}天 vs 前{days}天",
                "recent_start": recent_start,
                "recent_end": recent_end,
                "previous_start": previous_start,
                "previous_end": previous_end,
                "recent_days": days,
                "previous_days": days,
            }
        )
        comparisons.append(next_params)

    return comparisons


def next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def build_alert_monthly_metric_params(params: dict[str, object]) -> list[dict[str, object]]:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")

    result: list[dict[str, object]] = []
    month_start = date(biz_date.year, 1, 1)
    current_month_start = date(biz_date.year, biz_date.month, 1)
    while month_start <= current_month_start:
        month_end = next_month_start(month_start) - timedelta(days=1)
        data_start = month_start
        data_end = min(month_end, biz_date)
        next_params = dict(params)
        next_params.update(
            {
                "month_code": f"{month_start.year}-{month_start.month:02d}",
                "month_start": month_start,
                "month_end": month_end,
                "data_start": data_start,
                "data_end": data_end,
                "stat_days": (data_end - data_start).days + 1,
                "is_month_complete": 1 if data_end == month_end else 0,
            }
        )
        result.append(next_params)
        month_start = next_month_start(month_start)

    return result


def build_opportunity_comparison_month_params(params: dict[str, object]) -> list[dict[str, object]]:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")

    month_codes = [f"{biz_date.year}-{month:02d}" for month in range(1, biz_date.month + 1)]
    result: list[dict[str, object]] = []
    for previous_month in month_codes:
        for recent_month in month_codes:
            if previous_month == recent_month:
                continue
            next_params = dict(params)
            next_params.update(
                {
                    "comparison_code": f"{previous_month}_vs_{recent_month}",
                    "comparison_label": f"{previous_month} vs {recent_month}",
                    "comparison_type": "month",
                    "comparison_mode": "month",
                    "previous_month": previous_month,
                    "recent_month": recent_month,
                }
            )
            result.append(next_params)
    return result


def execute_period_preset_step(
    conn,
    schemas: SchemaConfig,
    step: PeriodPresetStep,
    params: dict[str, object],
) -> None:
    min_product_date = product_daily_min_date(conn, schemas)
    touched_tables: set[str] = set()
    for preset_name, preset_params in build_period_preset_params(params).items():
        table_name = PERIOD_PRESET_TABLES[preset_name]
        touched_tables.add(table_name)
        preset_params["period_code"] = preset_name
        previous_params = build_previous_period_params(preset_name, preset_params)
        for suffix, run_params in (("current", preset_params), ("previous", previous_params)):
            if suffix == "previous" and min_product_date and run_params["period_start"] < min_product_date:
                print(
                    f"[skip] {step.name}.{preset_name}.previous: "
                    f"source data starts at {min_product_date}, "
                    f"previous period {run_params['period_start']}~{run_params['period_end']} is incomplete."
                )
                continue
            sub_step = SqlStep(
                f"{step.name}.{preset_name}.{suffix}",
                (
                    period_delete_sql(table_name),
                    period_insert_sql(table_name),
                    DELETE_MATRIX_PERIOD_SNAPSHOT_SQL,
                    matrix_insert_sql(table_name),
                ),
            )
            execute_target_step(conn, schemas, sub_step, run_params)
    cleanup_period_snapshot_retention(conn, schemas, touched_tables, params)


def execute_alert_comparison_step(
    conn,
    schemas: SchemaConfig,
    step: AlertComparisonStep,
    params: dict[str, object],
) -> None:
    for comparison_params in build_alert_comparison_params(params):
        sub_step = SqlStep(
            f"{step.name}.{comparison_params['comparison_code']}",
            (
                DELETE_ALERT_COMPARISON_SNAPSHOT_SQL,
                INSERT_ALERT_COMPARISON_SNAPSHOT_SQL,
                DELETE_ALERT_COMPARISON_SUMMARY_SQL,
                INSERT_ALERT_COMPARISON_SUMMARY_SQL,
            ),
        )
        execute_target_step(conn, schemas, sub_step, comparison_params)
    cleanup_alert_comparison_retention(conn, schemas, params)


def execute_alert_monthly_metric_step(
    conn,
    schemas: SchemaConfig,
    step: AlertMonthlyMetricStep,
    params: dict[str, object],
) -> None:
    for month_params in build_alert_monthly_metric_params(params):
        sub_step = SqlStep(
            f"{step.name}.{month_params['month_code']}",
            (
                DELETE_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL,
                INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL,
            ),
        )
        execute_target_step(conn, schemas, sub_step, month_params)
    cleanup_alert_monthly_metric_retention(conn, schemas, params)


def execute_opportunity_comparison_step(
    conn,
    schemas: SchemaConfig,
    step: OpportunityComparisonStep,
    params: dict[str, object],
) -> None:
    for comparison_params in build_alert_comparison_params(params):
        sub_step = SqlStep(
            f"{step.name}.{comparison_params['comparison_code']}",
            (
                DELETE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL,
                INSERT_OPPORTUNITY_COMPARISON_FROM_ALERT_SQL,
                DELETE_OPPORTUNITY_COMPARISON_SUMMARY_SQL,
                INSERT_OPPORTUNITY_COMPARISON_SUMMARY_SQL,
            ),
        )
        execute_target_step(conn, schemas, sub_step, comparison_params)

    for month_params in build_opportunity_comparison_month_params(params):
        sub_step = SqlStep(
            f"{step.name}.{month_params['comparison_code']}",
            (
                DELETE_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL,
                INSERT_OPPORTUNITY_COMPARISON_FROM_MONTH_SQL,
                DELETE_OPPORTUNITY_COMPARISON_SUMMARY_SQL,
                INSERT_OPPORTUNITY_COMPARISON_SUMMARY_SQL,
            ),
        )
        execute_target_step(conn, schemas, sub_step, month_params)

    cleanup_opportunity_comparison_retention(conn, schemas, params)


def cleanup_period_snapshot_retention(
    conn,
    schemas: SchemaConfig,
    period_tables: Iterable[str],
    params: dict[str, object],
) -> None:
    cleanup_params = dict(params)
    cleanup_params["period_snapshot_retention_days"] = PERIOD_SNAPSHOT_RETENTION_DAYS
    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            for table_name in sorted(period_tables):
                cursor.execute(render_sql(period_retention_sql(table_name), schemas), cleanup_params)
                affected_rows += max(cursor.rowcount, 0)
            cursor.execute(render_sql(DELETE_OLD_MATRIX_PERIOD_SNAPSHOT_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
        conn.commit()
        log_task(conn, schemas, "period_preset_snapshots.retention_cleanup", params, "success", affected_rows, started_at)
        print(
            "[success] period_preset_snapshots.retention_cleanup: "
            f"kept_latest_snapshot_dates={PERIOD_SNAPSHOT_RETENTION_DAYS}, affected_rows={affected_rows}"
        )
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(
            conn,
            schemas,
            "period_preset_snapshots.retention_cleanup",
            params,
            "failed",
            affected_rows,
            started_at,
            error,
        )
        print("[failed] period_preset_snapshots.retention_cleanup", file=sys.stderr)
        raise


def cleanup_alert_comparison_retention(conn, schemas: SchemaConfig, params: dict[str, object]) -> None:
    cleanup_params = dict(params)
    cleanup_params["period_snapshot_retention_days"] = PERIOD_SNAPSHOT_RETENTION_DAYS
    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(render_sql(DELETE_OLD_ALERT_COMPARISON_SNAPSHOT_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
            cursor.execute(render_sql(DELETE_OLD_ALERT_COMPARISON_SUMMARY_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
        conn.commit()
        log_task(conn, schemas, "alert_comparison_snapshots.retention_cleanup", params, "success", affected_rows, started_at)
        print(
            "[success] alert_comparison_snapshots.retention_cleanup: "
            f"kept_latest_snapshot_dates={PERIOD_SNAPSHOT_RETENTION_DAYS}, affected_rows={affected_rows}"
        )
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(
            conn,
            schemas,
            "alert_comparison_snapshots.retention_cleanup",
            params,
            "failed",
            affected_rows,
            started_at,
            error,
        )
        print("[failed] alert_comparison_snapshots.retention_cleanup", file=sys.stderr)
        raise


def cleanup_alert_monthly_metric_retention(conn, schemas: SchemaConfig, params: dict[str, object]) -> None:
    cleanup_params = dict(params)
    cleanup_params["period_snapshot_retention_days"] = PERIOD_SNAPSHOT_RETENTION_DAYS
    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(render_sql(DELETE_OLD_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
        conn.commit()
        log_task(conn, schemas, "alert_monthly_metric_snapshots.retention_cleanup", params, "success", affected_rows, started_at)
        print(
            "[success] alert_monthly_metric_snapshots.retention_cleanup: "
            f"kept_latest_snapshot_dates={PERIOD_SNAPSHOT_RETENTION_DAYS}, affected_rows={affected_rows}"
        )
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(
            conn,
            schemas,
            "alert_monthly_metric_snapshots.retention_cleanup",
            params,
            "failed",
            affected_rows,
            started_at,
            error,
        )
        print("[failed] alert_monthly_metric_snapshots.retention_cleanup", file=sys.stderr)
        raise


def cleanup_opportunity_comparison_retention(conn, schemas: SchemaConfig, params: dict[str, object]) -> None:
    cleanup_params = dict(params)
    cleanup_params["period_snapshot_retention_days"] = PERIOD_SNAPSHOT_RETENTION_DAYS
    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(render_sql(DELETE_OLD_OPPORTUNITY_COMPARISON_SNAPSHOT_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
            cursor.execute(render_sql(DELETE_OLD_OPPORTUNITY_COMPARISON_SUMMARY_SQL, schemas), cleanup_params)
            affected_rows += max(cursor.rowcount, 0)
        conn.commit()
        log_task(conn, schemas, "opportunity_comparison_snapshots.retention_cleanup", params, "success", affected_rows, started_at)
        print(
            "[success] opportunity_comparison_snapshots.retention_cleanup: "
            f"kept_latest_snapshot_dates={PERIOD_SNAPSHOT_RETENTION_DAYS}, affected_rows={affected_rows}"
        )
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(
            conn,
            schemas,
            "opportunity_comparison_snapshots.retention_cleanup",
            params,
            "failed",
            affected_rows,
            started_at,
            error,
        )
        print("[failed] opportunity_comparison_snapshots.retention_cleanup", file=sys.stderr)
        raise


def execute_source_load_step(
    target_conn,
    source_conn,
    schemas: SchemaConfig,
    step: SourceLoadStep,
    params: dict[str, object],
    batch_size: int,
) -> None:
    started_at = datetime.now()
    attempts = source_load_retry_attempts()
    last_error = ""
    for attempt in range(1, attempts + 1):
        affected_rows = 0
        try:
            source_sql = render_sql(step.source_select_statement, schemas)
            assert_source_select_only(source_sql)
            target_insert_sql = build_target_insert_sql(step.target_table, step.target_columns, schemas)

            with source_conn.cursor() as source_cursor, target_conn.cursor() as target_cursor:
                target_cursor.execute(render_sql(step.delete_statement, schemas), params)
                source_cursor.execute(source_sql, params)
                while True:
                    rows = source_cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    target_cursor.executemany(target_insert_sql, rows)
                    affected_rows += len(rows)

            target_conn.commit()
            log_task(target_conn, schemas, step.name, params, "success", affected_rows, started_at)
            print(f"[success] {step.name}: affected_rows={affected_rows}")
            return
        except Exception:
            target_conn.rollback()
            last_error = traceback.format_exc()
            if attempt >= attempts:
                log_task(target_conn, schemas, step.name, params, "failed", affected_rows, started_at, last_error)
                print(f"[failed] {step.name}", file=sys.stderr)
                raise
            print(
                f"[warn] {step.name}: source load attempt {attempt}/{attempts} failed; reconnecting source and retrying.",
                file=sys.stderr,
            )
            ensure_live_source_connection(source_conn)


def product_daily_is_empty(conn, schemas: SchemaConfig) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                "select count(*) as total from etl_datasync.dashboard_product_performance_daily;",
                schemas,
            )
        )
        row = cursor.fetchone()
    return int((row or {}).get("total") or 0) == 0


def product_daily_min_date(conn, schemas: SchemaConfig) -> date | None:
    with conn.cursor() as cursor:
        cursor.execute(
            render_sql(
                "select min(dt_date) as min_date from etl_datasync.dashboard_product_performance_daily;",
                schemas,
            )
        )
        row = cursor.fetchone() or {}
    return row.get("min_date")


def resolve_product_load_mode(
    conn,
    schemas: SchemaConfig,
    step_names: Iterable[str],
    params: dict[str, object],
    auto_full_load: bool,
) -> None:
    if "product_performance_daily" not in step_names:
        return
    if params["product_full_load"]:
        return
    if auto_full_load and product_daily_is_empty(conn, schemas):
        params["product_full_load"] = 1
        print("[info] product daily table is empty; switching product_performance_daily to full load.")


def parse_steps(raw_steps: str) -> list[str]:
    if raw_steps == "all":
        return DEFAULT_STEP_ORDER[:]
    names = [item.strip() for item in raw_steps.split(",") if item.strip()]
    unknown = [name for name in names if name not in STEPS]
    if unknown:
        raise SystemExit(f"Unknown step(s): {', '.join(unknown)}")
    return names


def build_params(args: argparse.Namespace) -> dict[str, object]:
    if args.period_days < 1:
        raise SystemExit("period_days must be at least 1")
    if args.product_refresh_days < 1:
        raise SystemExit("product_refresh_days must be at least 1")
    biz_date = parse_day(args.biz_date) if args.biz_date else default_biz_date()
    snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else date.today()
    period_end = parse_day(args.period_end) if args.period_end else biz_date
    period_start = (
        parse_day(args.period_start)
        if args.period_start
        else period_end - timedelta(days=args.period_days - 1)
    )
    if period_start > period_end:
        raise SystemExit("period_start cannot be later than period_end")
    product_end_date = biz_date
    product_start_date = product_end_date - timedelta(days=args.product_refresh_days - 1)
    return {
        "biz_date": biz_date,
        "snapshot_date": snapshot_date,
        "next_snapshot_date": snapshot_date + timedelta(days=1),
        "period_start": period_start,
        "period_end": period_end,
        "product_start_date": product_start_date,
        "product_end_date": product_end_date,
        "next_product_end_date": product_end_date + timedelta(days=1),
        "product_full_load": 1 if args.product_full_load else 0,
    }


def print_plan(step_names: Iterable[str], params: dict[str, object], schemas: SchemaConfig) -> None:
    product_load = (
        "full source table"
        if params["product_full_load"]
        else f"{params['product_start_date']} to {params['product_end_date']}"
    )
    print("Dashboard daily ETL plan")
    print(f"  biz_date      : {params['biz_date']}")
    print(f"  snapshot_date : {params['snapshot_date']}")
    print(f"  period_start  : {params['period_start']}")
    print(f"  period_end    : {params['period_end']}")
    print(f"  product_load  : {product_load}")
    print(f"  target_schema : {schemas.target_schema}")
    print(f"  etl_source    : {schemas.etl_source_schema}")
    print(f"  dwd_source    : {schemas.dwd_source_schema}")
    print(f"  pricing_source: {schemas.pricing_source_schema}")
    print(f"  steps         : {', '.join(step_names)}")


def test_connections() -> None:
    target_conn = connect_target()
    source_conn = connect_source()
    try:
        with target_conn.cursor() as cursor:
            cursor.execute("select 1 as ok;")
            cursor.fetchone()
        print("[success] target connection ok")

        with source_conn.cursor() as cursor:
            cursor.execute("select 1 as ok;")
            cursor.fetchone()
        print("[success] source read-only connection ok")
    finally:
        source_conn.close()
        target_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dashboard daily ETL.")
    parser.add_argument("--biz-date", help="Business date to load, format YYYY-MM-DD. Default: yesterday.")
    parser.add_argument("--snapshot-date", help="Snapshot date for price/inventory/limit price. Default: today.")
    parser.add_argument("--period-start", help="Dashboard default period start, format YYYY-MM-DD.")
    parser.add_argument("--period-end", help="Dashboard default period end, format YYYY-MM-DD. Default: biz-date.")
    parser.add_argument("--period-days", type=int, default=DEFAULT_PERIOD_DAYS, help="Default period length.")
    parser.add_argument(
        "--product-refresh-days",
        type=int,
        default=DEFAULT_PRODUCT_REFRESH_DAYS,
        help="Rolling days to refresh in product performance daily table. Default: 50.",
    )
    parser.add_argument(
        "--product-full-load",
        action="store_true",
        help="Reload product performance daily table from the full source table.",
    )
    parser.add_argument(
        "--no-auto-full-load",
        action="store_true",
        help="Do not auto-switch to full load when product performance daily table is empty.",
    )
    parser.add_argument(
        "--steps",
        default="all",
        help="Comma separated step names or all. "
        "Available: product_performance_daily, monthly_goal_actual_snapshot, goal_dimension_snapshot, annual_goal_snapshot, restock_snapshot, inventory_snapshot, inventory_weekly_snapshot, inventory_weekly_remote_snapshot, "
        "listing_price_snapshot, limit_price_snapshot, period_snapshot, period_preset_snapshots, "
        "alert_comparison_snapshots, alert_monthly_metric_snapshots, "
        "opportunity_comparison_snapshots, price_review_source_load, price_review_tracking.",
    )
    parser.add_argument("--skip-ddl", action="store_true", help="Do not create target tables before running.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per local bulk insert from read-only source.")
    parser.add_argument("--connection-test", action="store_true", help="Only test target/source database connections.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; do not connect or execute SQL.")
    args = parser.parse_args()

    if args.batch_size < 1:
        raise SystemExit("batch_size must be at least 1")

    step_names = parse_steps(args.steps)
    params = build_params(args)
    schemas = build_schema_config()
    print_plan(step_names, params, schemas)

    if args.dry_run:
        return

    if args.connection_test:
        test_connections()
        return

    target_conn = connect_target()
    needs_source = any(
        isinstance(STEPS[step_name], SourceLoadStep)
        or (isinstance(STEPS[step_name], PriceReviewStep) and step_name != "price_review_tracking")
        for step_name in step_names
    )
    source_conn = connect_source() if needs_source else None
    try:
        if not args.skip_ddl:
            ensure_tables(target_conn, schemas)
        resolve_product_load_mode(
            target_conn,
            schemas,
            step_names,
            params,
            auto_full_load=not args.no_auto_full_load,
        )
        for step_name in step_names:
            step = STEPS[step_name]
            if isinstance(step, SourceLoadStep):
                if source_conn is None:
                    raise RuntimeError("Source connection is required for source load steps")
                ensure_live_source_connection(source_conn)
                execute_source_load_step(target_conn, source_conn, schemas, step, params, args.batch_size)
            elif isinstance(step, PeriodPresetStep):
                execute_period_preset_step(target_conn, schemas, step, params)
            elif isinstance(step, AlertComparisonStep):
                execute_alert_comparison_step(target_conn, schemas, step, params)
            elif isinstance(step, AlertMonthlyMetricStep):
                execute_alert_monthly_metric_step(target_conn, schemas, step, params)
            elif isinstance(step, OpportunityComparisonStep):
                execute_opportunity_comparison_step(target_conn, schemas, step, params)
            elif isinstance(step, PriceReviewStep):
                if step.name != "price_review_tracking":
                    if source_conn is None:
                        raise RuntimeError(f"Source connection is required for {step.name}")
                    ensure_live_source_connection(source_conn)
                execute_price_review_step(
                    target_conn,
                    source_conn,
                    schemas.target_schema,
                    step,
                    params,
                    args.batch_size,
                    lambda conn, task_name, task_params, status, affected_rows, started_at, error_message=None: log_task(
                        conn,
                        schemas,
                        task_name,
                        task_params,
                        status,
                        affected_rows,
                        started_at,
                        error_message,
                    ),
                )
            else:
                execute_target_step(target_conn, schemas, step, params)
    finally:
        if source_conn is not None:
            source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()

