from __future__ import annotations

import os
import re
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

import pymysql

from app.services.station_sales_role import (
    REMOTE_ROLE_PERIODS,
    SUPPORTED_ROLE_PERIODS,
    build_station_role_tracking_row,
    normalize_remote_role_snapshot,
)
from etl.station_sales_role_cache import station_role_recent_cache_ddl, sync_recent_station_role_cache
from etl.station_sales_role_drift_check import run_station_sales_role_drift_check


TRACKING_PERIODS = (3, 7, 14, 28)
STATION_ROLE_HISTORY_START = date(2026, 8, 1)
DEFAULT_LOOKBACK_DAYS = 80
DEFAULT_QUEUE_LOOKBACK_DAYS = 20

PRICE_REVIEW_TABLE_COMMENTS = {
    "price_review_adjustment_source": "调价复盘调价队列本地源表",
    "price_review_product_performance_source": "调价复盘产品表现源表",
    "price_review_listing_source": "调价复盘Listing排名价格源表",
    "price_review_sku_tracking": "调价复盘SKU前后对比结果表",
}

PRICE_REVIEW_COLUMN_COMMENTS = {
    "source_id": "远端调价队列ID",
    "adjust_date": "调价日期",
    "msku": "销售SKU",
    "local_sku": "本地SKU",
    "asin": "ASIN",
    "product_name": "产品名称",
    "store": "店铺",
    "seller_name_new": "新店铺名称",
    "country": "国家站点",
    "country_category": "国家类别",
    "currency": "币种",
    "price_before": "调价前价格",
    "price_after": "调价后价格",
    "drop_ratio": "调价幅度",
    "finish_time": "调价完成时间",
    "raw_updated_at": "源数据更新时间",
    "dt_date": "数据日期",
    "sku": "SKU",
    "raw_msku": "原始MSKU",
    "price": "售价",
    "rank_value": "排名",
    "sales_qty": "销量",
    "revenue": "销售额",
    "net_revenue": "净销售额",
    "clicks": "点击量",
    "impressions": "曝光量",
    "organic_clicks": "自然点击量",
    "ad_spend": "广告花费",
    "ad_sales": "广告销售额",
    "ad_orders": "广告订单数",
    "organic_orders": "自然订单数",
    "orders": "订单数",
    "order_profit": "订单利润",
    "settlement_profit": "结算利润",
    "returns_qty": "退货数量",
    "refund_amount": "退款金额",
    "sessions": "Sessions",
    "period_days": "复盘周期天数",
    "drop_range": "调价幅度分组",
    "price_band": "价格带",
    "period_start": "调价前周期开始日期",
    "period_end": "调价前周期结束日期",
    "period_after_start": "调价后周期开始日期",
    "period_after_end": "调价后周期结束日期",
    "sales_before": "调价前销量",
    "sales_after": "调价后销量",
    "sales_change": "销量变化",
    "sales_change_rate": "销量变化率",
    "daily_sales_before": "调价前日销",
    "daily_sales_after": "调价后日销",
    "daily_sales_change": "日销变化",
    "revenue_before": "调价前销售额",
    "revenue_after": "调价后销售额",
    "revenue_change": "销售额变化",
    "profit_before": "调价前毛利润",
    "profit_after": "调价后毛利润",
    "profit_change": "毛利润变化",
    "margin_before": "调价前毛利率",
    "margin_after": "调价后毛利率",
    "margin_change": "毛利率变化",
    "sessions_before": "调价前Sessions",
    "sessions_after": "调价后Sessions",
    "sessions_change": "Sessions变化",
    "conversion_before": "调价前转化率",
    "conversion_after": "调价后转化率",
    "ctr_before": "调价前点击率",
    "ctr_after": "调价后点击率",
    "ad_spend_before": "调价前广告花费",
    "ad_spend_after": "调价后广告花费",
    "ad_revenue_before": "调价前广告销售额",
    "ad_revenue_after": "调价后广告销售额",
    "acos_before": "调价前ACOS",
    "acos_after": "调价后ACOS",
    "tacos_before": "调价前TACOS",
    "tacos_after": "调价后TACOS",
    "cpc_before": "调价前CPC",
    "cpc_after": "调价后CPC",
    "rank_before": "调价前排名",
    "rank_after": "调价后排名",
    "rank_change": "排名变化",
    "sales_band_before": "调价前销量分层",
    "sales_band_after": "调价后销量分层",
    "daily_sales_band_before": "调价前日销分层",
    "daily_sales_band_after": "调价后日销分层",
    "margin_band_before": "调价前毛利率分层",
    "margin_band_after": "调价后毛利率分层",
    "rank_band_before": "调价前排名分层",
    "rank_band_after": "调价后排名分层",
    "risk_level": "风险等级",
    "issue_tags": "问题标签",
    "suggested_action": "建议动作",
    "created_at": "创建时间",
    "updated_at": "更新时间",
}


@dataclass(frozen=True)
class PriceReviewStep:
    name: str


def clean_identifier(value: str, fallback: str) -> str:
    name = (value or fallback).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError(f"Unsafe schema name: {name!r}")
    return name


def target_table(schema: str, table: str) -> str:
    return f"`{schema}`.`{table}`"


def source_table(schema_env: str, fallback_schema: str, table: str) -> str:
    schema = clean_identifier(os.getenv(schema_env, fallback_schema), fallback_schema)
    return f"`{schema}`.`{table}`"


def escape_sql_comment(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")


def create_table_name(sql: str) -> str:
    match = re.search(r"create\s+table\s+if\s+not\s+exists\s+`?[\w]+`?\.`?([\w]+)`?", sql, re.IGNORECASE)
    return match.group(1) if match else ""


def with_price_review_comments(sql: str) -> str:
    table_name = create_table_name(sql)
    if not table_name:
        return sql

    lines = []
    for line in sql.splitlines():
        stripped = line.lstrip()
        column_match = re.match(r"`?([A-Za-z0-9_]+)`?\s+", stripped)
        column_name = column_match.group(1) if column_match else ""
        comment = PRICE_REVIEW_COLUMN_COMMENTS.get(column_name)
        if comment and " comment " not in stripped.lower():
            comma = "," if line.rstrip().endswith(",") else ""
            body = line.rstrip()[:-1] if comma else line.rstrip()
            line = f"{body} comment '{escape_sql_comment(comment)}'{comma}"
        lines.append(line)

    rendered = "\n".join(lines)
    table_comment = PRICE_REVIEW_TABLE_COMMENTS.get(table_name)
    if table_comment and " comment=" not in rendered.lower():
        rendered = re.sub(
            r"\)\s*engine=InnoDB\s+default\s+charset=utf8mb4\s*;",
            f") engine=InnoDB default charset=utf8mb4 comment='{escape_sql_comment(table_comment)}';",
            rendered,
            count=1,
            flags=re.IGNORECASE,
        )
    return rendered


def _station_role_tracking_ddl(target_schema: str) -> str:
    return f"""
        create table if not exists {target_table(target_schema, "price_review_station_role_tracking")} (
            adjust_date date not null,
            post_period_days int not null,
            comparison_mode varchar(32) not null,
            country varchar(64) not null,
            station_store varchar(255) not null,
            store varchar(255) not null,
            msku varchar(128) not null,
            local_sku varchar(128) null,
            product_name varchar(512) null,
            currency varchar(32) null,
            price_before decimal(18,4) null,
            price_after decimal(18,4) null,
            drop_ratio decimal(10,6) null,
            pre_period_days int not null,
            pre_period_start date not null,
            pre_period_end date not null,
            post_period_start date not null,
            post_period_end date not null,
            pre_seen_days int not null default 0,
            post_seen_days int not null default 0,
            pre_sales_qty decimal(18,4) not null default 0,
            post_sales_qty decimal(18,4) not null default 0,
            pre_sales_amount decimal(18,4) not null default 0,
            post_sales_amount decimal(18,4) not null default 0,
            pre_order_profit decimal(18,4) not null default 0,
            post_order_profit decimal(18,4) not null default 0,
            pre_daily_sales decimal(18,6) not null default 0,
            post_daily_sales decimal(18,6) not null default 0,
            pre_margin_rate decimal(18,6) null,
            post_margin_rate decimal(18,6) null,
            pre_small_rank int null,
            post_small_rank int null,
            pre_small_rank_date date null,
            post_small_rank_date date null,
            role_before_code varchar(32) null,
            role_before_label varchar(32) null,
            role_before_rank int null,
            role_after_code varchar(32) null,
            role_after_label varchar(32) null,
            role_after_rank int null,
            role_change varchar(32) not null,
            pre_role_source varchar(32) not null default 'unavailable',
            post_role_source varchar(32) not null default 'unavailable',
            pre_source_freshness varchar(16) not null default 'fresh',
            post_source_freshness varchar(16) not null default 'fresh',
            pre_source_data_date date null,
            post_source_data_date date null,
            pre_source_created_time datetime null,
            post_source_created_time datetime null,
            data_status varchar(32) not null,
            data_message varchar(255) null,
            finance_snapshot_date date null,
            finance_band_before_code varchar(32) not null,
            finance_band_before_label varchar(32) not null,
            finance_band_after_code varchar(32) not null,
            finance_band_after_label varchar(32) not null,
            finance_change varchar(32) not null,
            station_sales_role_rule_version varchar(64) not null,
            station_sales_role_rule_source varchar(255) not null,
            created_at datetime not null default current_timestamp,
            updated_at datetime not null default current_timestamp on update current_timestamp,
            primary key (adjust_date, pre_period_days, post_period_days, country, station_store, msku),
            key idx_station_role_filter (adjust_date, pre_period_days, post_period_days, country, store),
            key idx_station_role_change (adjust_date, pre_period_days, post_period_days, role_change),
            key idx_station_role_msku (msku)
        ) engine=InnoDB default charset=utf8mb4;
    """


def _station_role_performance_index_sql(target_schema: str) -> str:
    return f"""
        alter table {target_table(target_schema, 'dashboard_product_performance_daily')}
        add index idx_station_role_lookup
            (seller_name_new, country, seller_sku_adj, dt_date)
    """


STATION_ROLE_SOURCE_COLUMN_DDL = {
    "pre_role_source": "varchar(32) not null default 'unavailable'",
    "post_role_source": "varchar(32) not null default 'unavailable'",
    "pre_source_freshness": "varchar(16) not null default 'fresh'",
    "post_source_freshness": "varchar(16) not null default 'fresh'",
    "pre_source_data_date": "date null",
    "post_source_data_date": "date null",
    "pre_source_created_time": "datetime null",
    "post_source_created_time": "datetime null",
}
STATION_ROLE_PRIMARY_COLUMNS = (
    "adjust_date",
    "pre_period_days",
    "post_period_days",
    "country",
    "station_store",
    "msku",
)


def _ensure_station_role_tracking_schema(cursor, target_schema: str) -> None:
    table = target_table(target_schema, "price_review_station_role_tracking")
    for column, definition in STATION_ROLE_SOURCE_COLUMN_DDL.items():
        cursor.execute(f"show columns from {table} like %s", (column,))
        if not cursor.fetchone():
            cursor.execute(f"alter table {table} add column `{column}` {definition}")

    cursor.execute(f"show index from {table} where Key_name = 'PRIMARY'")
    primary_rows = cursor.fetchall()
    primary_columns = tuple(
        row["Column_name"]
        for row in sorted(primary_rows, key=lambda item: int(item["Seq_in_index"]))
    )
    if primary_columns != STATION_ROLE_PRIMARY_COLUMNS:
        cursor.execute(f"delete from {table}")
        columns = ", ".join(STATION_ROLE_PRIMARY_COLUMNS)
        cursor.execute(f"alter table {table} drop primary key, add primary key ({columns})")


def ensure_price_review_tables(conn, target_schema: str) -> None:
    ddl = [
        f"""
        create table if not exists {target_table(target_schema, "price_review_adjustment_source")} (
            source_id bigint not null,
            adjust_date date not null,
            msku varchar(128) not null,
            local_sku varchar(128) null,
            asin varchar(128) null,
            product_name varchar(512) null,
            store varchar(255) not null,
            seller_name_new varchar(128) null,
            country varchar(64) null,
            currency varchar(32) null,
            price_before decimal(18,4) null,
            price_after decimal(18,4) null,
            drop_ratio decimal(10,6) null,
            finish_time datetime null,
            raw_updated_at datetime null,
            created_at datetime not null default current_timestamp,
            updated_at datetime not null default current_timestamp on update current_timestamp,
            primary key (adjust_date, store, msku),
            key idx_adjust_date (adjust_date),
            key idx_store_msku (store, msku, adjust_date)
        ) engine=InnoDB default charset=utf8mb4;
        """,
        f"""
        create table if not exists {target_table(target_schema, "price_review_product_performance_source")} (
            dt_date date not null,
            product_name varchar(512) null,
            sku varchar(128) null,
            raw_msku text null,
            msku varchar(128) not null,
            store varchar(255) not null,
            seller_name_new varchar(128) null,
            country varchar(64) null,
            country_category varchar(64) null,
            price decimal(18,4) null,
            sales_qty decimal(18,4) not null default 0,
            revenue decimal(18,4) not null default 0,
            net_revenue decimal(18,4) not null default 0,
            clicks decimal(18,4) not null default 0,
            impressions decimal(18,4) not null default 0,
            organic_clicks decimal(18,4) not null default 0,
            ad_spend decimal(18,4) not null default 0,
            ad_sales decimal(18,4) not null default 0,
            ad_orders decimal(18,4) not null default 0,
            organic_orders decimal(18,4) not null default 0,
            orders decimal(18,4) not null default 0,
            order_profit decimal(18,4) not null default 0,
            settlement_profit decimal(18,4) not null default 0,
            returns_qty decimal(18,4) not null default 0,
            refund_amount decimal(18,4) not null default 0,
            sessions decimal(18,4) not null default 0,
            created_at datetime not null default current_timestamp,
            updated_at datetime not null default current_timestamp on update current_timestamp,
            primary key (dt_date, store, msku),
            key idx_msku_store (msku, store),
            key idx_dt_date (dt_date)
        ) engine=InnoDB default charset=utf8mb4;
        """,
        f"""
        create table if not exists {target_table(target_schema, "price_review_listing_source")} (
            dt_date date not null,
            msku varchar(128) not null,
            store varchar(255) not null,
            country varchar(64) null,
            rank_value int null,
            price decimal(18,4) null,
            created_at datetime not null default current_timestamp,
            updated_at datetime not null default current_timestamp on update current_timestamp,
            primary key (dt_date, store, msku),
            key idx_msku_store (msku, store),
            key idx_dt_date (dt_date)
        ) engine=InnoDB default charset=utf8mb4;
        """,
        f"""
        create table if not exists {target_table(target_schema, "price_review_sku_tracking")} (
            adjust_date date not null,
            period_days int not null,
            country varchar(64) null,
            store varchar(255) not null,
            seller_name_new varchar(128) null,
            msku varchar(128) not null,
            product_name varchar(512) null,
            price_before decimal(18,4) null,
            price_after decimal(18,4) null,
            drop_ratio decimal(10,6) null,
            is_second_adjustment tinyint not null default 0,
            previous_adjust_date date null,
            drop_range varchar(32) not null,
            price_band varchar(32) not null,
            period_start date not null,
            period_end date not null,
            period_after_start date not null,
            period_after_end date not null,
            sales_before decimal(18,4) not null default 0,
            sales_after decimal(18,4) not null default 0,
            sales_change decimal(18,4) not null default 0,
            sales_change_rate decimal(10,6) not null default 0,
            daily_sales_before decimal(18,6) not null default 0,
            daily_sales_after decimal(18,6) not null default 0,
            daily_sales_change decimal(18,6) not null default 0,
            revenue_before decimal(18,4) not null default 0,
            revenue_after decimal(18,4) not null default 0,
            revenue_change decimal(18,4) not null default 0,
            profit_before decimal(18,4) not null default 0,
            profit_after decimal(18,4) not null default 0,
            profit_change decimal(18,4) not null default 0,
            margin_before decimal(10,6) not null default 0,
            margin_after decimal(10,6) not null default 0,
            margin_change decimal(10,6) not null default 0,
            sessions_before decimal(18,4) not null default 0,
            sessions_after decimal(18,4) not null default 0,
            sessions_change decimal(18,4) not null default 0,
            conversion_before decimal(10,6) not null default 0,
            conversion_after decimal(10,6) not null default 0,
            ctr_before decimal(10,6) not null default 0,
            ctr_after decimal(10,6) not null default 0,
            ad_spend_before decimal(18,4) not null default 0,
            ad_spend_after decimal(18,4) not null default 0,
            ad_revenue_before decimal(18,4) not null default 0,
            ad_revenue_after decimal(18,4) not null default 0,
            acos_before decimal(10,6) not null default 0,
            acos_after decimal(10,6) not null default 0,
            tacos_before decimal(10,6) not null default 0,
            tacos_after decimal(10,6) not null default 0,
            cpc_before decimal(18,6) not null default 0,
            cpc_after decimal(18,6) not null default 0,
            rank_before int null,
            rank_after int null,
            rank_change int not null default 0,
            sales_band_before varchar(32) not null,
            sales_band_after varchar(32) not null,
            daily_sales_band_before varchar(32) not null,
            daily_sales_band_after varchar(32) not null,
            margin_band_before varchar(32) not null,
            margin_band_after varchar(32) not null,
            rank_band_before varchar(32) not null,
            rank_band_after varchar(32) not null,
            risk_level varchar(32) not null,
            issue_tags varchar(512) null,
            suggested_action varchar(64) null,
            created_at datetime not null default current_timestamp,
            updated_at datetime not null default current_timestamp on update current_timestamp,
            primary key (adjust_date, period_days, store, msku),
            key idx_adjust_period (adjust_date, period_days),
            key idx_country_store (country, store),
            key idx_msku (msku)
        ) engine=InnoDB default charset=utf8mb4;
        """,
        station_role_recent_cache_ddl(target_schema),
        _station_role_tracking_ddl(target_schema),
    ]
    with conn.cursor() as cursor:
        for statement in ddl:
            cursor.execute(with_price_review_comments(statement))
        cursor.execute(f"show columns from {target_table(target_schema, 'price_review_sku_tracking')} like 'is_second_adjustment'")
        if not cursor.fetchone():
            cursor.execute(
                f"""
                alter table {target_table(target_schema, "price_review_sku_tracking")}
                add column is_second_adjustment tinyint not null default 0 after drop_ratio
                """
            )
        cursor.execute(f"show columns from {target_table(target_schema, 'price_review_sku_tracking')} like 'previous_adjust_date'")
        if not cursor.fetchone():
            cursor.execute(
                f"""
                alter table {target_table(target_schema, "price_review_sku_tracking")}
                add column previous_adjust_date date null after is_second_adjustment
                """
            )
        cursor.execute(f"show index from {target_table(target_schema, 'price_review_adjustment_source')} where Key_name = 'idx_store_msku_date'")
        if not cursor.fetchone():
            cursor.execute(
                f"""
                alter table {target_table(target_schema, "price_review_adjustment_source")}
                add index idx_store_msku_date (store, msku, adjust_date)
                """
            )
        _ensure_station_role_tracking_schema(cursor, target_schema)
        cursor.execute(
            f"show index from {target_table(target_schema, 'dashboard_product_performance_daily')} "
            "where Key_name = 'idx_station_role_lookup'"
        )
        if not cursor.fetchone():
            cursor.execute(_station_role_performance_index_sql(target_schema))
    conn.commit()


def _insert_sql(table: str, columns: Iterable[str]) -> str:
    cols = list(columns)
    column_list = ", ".join(f"`{col}`" for col in cols)
    placeholders = ", ".join(f"%({col})s" for col in cols)
    updates = ", ".join(f"`{col}`=values(`{col}`)" for col in cols if col not in {"created_at"})
    return f"insert into {table} ({column_list}) values ({placeholders}) on duplicate key update {updates}"


def _copy_rows(source_cursor, target_cursor, insert_sql: str, batch_size: int) -> int:
    affected = 0
    while True:
        rows = source_cursor.fetchmany(batch_size)
        if not rows:
            break
        target_cursor.executemany(insert_sql, rows)
        affected += len(rows)
    return affected


def _source_window(conn, target_schema: str, biz_date: date) -> tuple[date, date, date, date] | None:
    lookback = int(os.getenv("DASHBOARD_PRICE_REVIEW_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS)))
    adjust_start = biz_date - timedelta(days=max(lookback, 1) - 1)
    adjust_end = biz_date
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            select min(adjust_date) as min_date, max(adjust_date) as max_date
            from {target_table(target_schema, "price_review_adjustment_source")}
            where adjust_date between %(start)s and %(end)s
            """,
            {"start": adjust_start, "end": adjust_end},
        )
        row = cursor.fetchone() or {}
    if not row.get("min_date") or not row.get("max_date"):
        return None
    performance_start = row["min_date"] - timedelta(days=27)
    performance_end = row["max_date"] + timedelta(days=27)
    return adjust_start, adjust_end, performance_start, performance_end


def execute_price_review_source_load(
    target_conn,
    source_conn,
    target_schema: str,
    params: dict[str, object],
    batch_size: int,
) -> int:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")
    ensure_price_review_tables(target_conn, target_schema)

    lookback = int(os.getenv("DASHBOARD_PRICE_QUEUE_LOOKBACK_DAYS", str(DEFAULT_QUEUE_LOOKBACK_DAYS)))
    adjust_start = biz_date - timedelta(days=max(lookback, 1) - 1)
    adjust_end = biz_date
    affected = 0
    queue_table = source_table("DASHBOARD_PRICE_QUEUE_SOURCE_SCHEMA", "temporary_APP", "lx_sale_adjust_price_queue")
    adjustment_columns = (
        "source_id", "adjust_date", "msku", "local_sku", "asin", "product_name", "store",
        "seller_name_new", "country", "currency", "price_before", "price_after", "drop_ratio",
        "finish_time", "raw_updated_at",
    )

    select_sql = _select_price_review_adjustment_source_sql(queue_table)
    insert_sql = _insert_sql(target_table(target_schema, "price_review_adjustment_source"), adjustment_columns)

    with target_conn.cursor() as target_cursor:
        target_cursor.execute(
            f"""
            delete from {target_table(target_schema, "price_review_adjustment_source")}
            where adjust_date between %(adjust_start)s and %(adjust_end)s
            """,
            {"adjust_start": adjust_start, "adjust_end": adjust_end},
        )

        current_day = adjust_start
        while current_day <= adjust_end:
            day_start_at = datetime.combine(current_day, datetime.min.time())
            day_end_exclusive = datetime.combine(current_day + timedelta(days=1), datetime.min.time())
            with source_conn.cursor() as source_cursor:
                source_cursor.execute(
                    select_sql,
                    {"adjust_start_at": day_start_at, "adjust_end_exclusive": day_end_exclusive},
                )
                affected += _copy_rows(source_cursor, target_cursor, insert_sql, batch_size)
            current_day += timedelta(days=1)
    target_conn.commit()
    cache_result = sync_recent_station_role_cache(
        source_conn,
        target_conn,
        target_schema,
        batch_size=batch_size,
    )
    affected += cache_result.row_count
    return affected


def _select_price_review_adjustment_source_sql(queue_table: str) -> str:
    return f"""
        select
            id as source_id,
            date(finish_time) as adjust_date,
            msku,
            local_sku,
            asin,
            local_name as product_name,
            store_name as store,
            substring_index(store_name, '-', 1) as seller_name_new,
            marketplace as country,
            currency_icon as currency,
            cast(nullif(adjust_before_obj_standard_price, '') as decimal(18,4)) as price_before,
            cast(nullif(adjust_after_obj_standard_price, '') as decimal(18,4)) as price_after,
            round(
                (cast(nullif(adjust_after_obj_standard_price, '') as decimal(18,4))
                 - cast(nullif(adjust_before_obj_standard_price, '') as decimal(18,4)))
                / nullif(cast(nullif(adjust_before_obj_standard_price, '') as decimal(18,4)), 0),
                6
            ) as drop_ratio,
            cast(finish_time as datetime) as finish_time,
            coalesce(update_time, ods_update_time, backup_time) as raw_updated_at
        from {queue_table}
        where delete_flag = 0
          and finish_time is not null
          and finish_time <> ''
          and finish_time >= %(adjust_start_at)s
          and finish_time < %(adjust_end_exclusive)s
          and msku is not null
          and msku <> ''
          and store_name is not null
          and store_name <> ''
    """


STATION_ROLE_TRACKING_COLUMNS = (
    "adjust_date", "post_period_days", "comparison_mode", "country", "station_store", "store",
    "msku", "local_sku", "product_name", "currency", "price_before", "price_after", "drop_ratio",
    "pre_period_days", "pre_period_start", "pre_period_end", "post_period_start", "post_period_end",
    "pre_seen_days", "post_seen_days", "pre_sales_qty", "post_sales_qty", "pre_sales_amount",
    "post_sales_amount", "pre_order_profit", "post_order_profit", "pre_daily_sales", "post_daily_sales",
    "pre_margin_rate", "post_margin_rate", "pre_small_rank", "post_small_rank", "pre_small_rank_date",
    "post_small_rank_date", "role_before_code", "role_before_label", "role_before_rank", "role_after_code",
    "role_after_label", "role_after_rank", "role_change", "pre_role_source", "post_role_source",
    "pre_source_freshness", "post_source_freshness", "pre_source_data_date", "post_source_data_date",
    "pre_source_created_time", "post_source_created_time", "data_status", "data_message",
    "finance_snapshot_date", "finance_band_before_code", "finance_band_before_label",
    "finance_band_after_code", "finance_band_after_label", "finance_change",
    "station_sales_role_rule_version", "station_sales_role_rule_source",
)


def _station_role_adjust_start(adjust_start: date) -> date:
    return max(adjust_start, STATION_ROLE_HISTORY_START)


def _station_role_period_pairs() -> tuple[tuple[int, int], ...]:
    return tuple(
        (pre_days, post_days)
        for pre_days in SUPPORTED_ROLE_PERIODS
        for post_days in SUPPORTED_ROLE_PERIODS
    )


def _station_role_cached_roles_sql(target_schema: str) -> str:
    adjustments = target_table(target_schema, "price_review_adjustment_source")
    cache = target_table(target_schema, "station_sales_role_recent_cache")
    cached_columns = """
        c.data_date, c.period_days, c.label_period, c.country,
        c.station_store, c.msku, c.label_id, c.role_code, c.role_label,
        c.evidence_json, c.rule_version, c.source_created_time as created_time
    """
    return f"""
        select 'pre' as role_side, a.adjust_date, {cached_columns}
        from {adjustments} a
        join {cache} c
          on c.country = a.country
         and c.station_store = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))
         and c.msku = a.msku
         and c.period_days = %(pre_days)s
         and c.data_date = a.adjust_date
        where a.adjust_date between %(adjust_start)s and %(adjust_end)s
          and %(pre_days)s in (7, 14, 30, 90)
        union all
        select 'post' as role_side, a.adjust_date, {cached_columns}
        from {adjustments} a
        join {cache} c
          on c.country = a.country
         and c.station_store = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))
         and c.msku = a.msku
         and c.period_days = %(post_days)s
         and c.data_date = date_add(a.adjust_date, interval %(post_days)s day)
        where a.adjust_date between %(adjust_start)s and %(adjust_end)s
          and %(post_days)s in (7, 14, 30, 90)
    """


def _load_cached_station_roles(
    cursor,
    target_schema: str,
    adjust_start: date,
    adjust_end: date,
    pre_days: int,
    post_days: int,
) -> dict[tuple, dict]:
    cursor.execute(
        _station_role_cached_roles_sql(target_schema),
        {
            "adjust_start": adjust_start,
            "adjust_end": adjust_end,
            "pre_days": pre_days,
            "post_days": post_days,
        },
    )
    snapshots = {}
    for row in cursor.fetchall():
        snapshot = normalize_remote_role_snapshot(row)
        key = (
            row["role_side"],
            row["adjust_date"],
            row["country"],
            row["station_store"],
            row["msku"],
        )
        snapshots[key] = snapshot
    return snapshots


def _should_refresh_station_role_tracking(
    existing: dict | None,
    recent_cache_dates: set[date],
    pre_days: int | None = None,
    post_days: int | None = None,
) -> bool:
    if not existing or existing.get("data_status") != "complete":
        return True
    if existing.get("adjust_date") and existing.get("pre_period_end") != existing.get("adjust_date"):
        return True
    for side, period_days in (("pre", pre_days), ("post", post_days)):
        if period_days is not None and period_days not in REMOTE_ROLE_PERIODS:
            continue
        if existing.get(f"{side}_source_data_date") not in recent_cache_dates:
            continue
        if existing.get(f"{side}_role_source") in {"remote_dws", "local_recomputed"}:
            return True
    return False


def _load_existing_station_role_rows(
    cursor,
    target_schema: str,
    adjust_start: date,
    adjust_end: date,
    pre_days: int,
    post_days: int,
) -> dict[tuple, dict]:
    cursor.execute(
        f"""
        select adjust_date, country, station_store, msku, data_status,
               pre_period_end,
               pre_role_source, post_role_source,
               pre_source_data_date, post_source_data_date
        from {target_table(target_schema, 'price_review_station_role_tracking')}
        where adjust_date between %(adjust_start)s and %(adjust_end)s
          and pre_period_days = %(pre_days)s
          and post_period_days = %(post_days)s
        """,
        {
            "adjust_start": adjust_start,
            "adjust_end": adjust_end,
            "pre_days": pre_days,
            "post_days": post_days,
        },
    )
    return {
        (row["adjust_date"], row["country"], row["station_store"], row["msku"]): row
        for row in cursor.fetchall()
    }


def _station_role_metrics_sql(target_schema: str) -> str:
    adjustments = target_table(target_schema, "price_review_adjustment_source")
    performance = target_table(target_schema, "dashboard_product_performance_daily")
    return f"""
    select
        a.adjust_date,
        coalesce(a.country, '') as country,
        coalesce(a.seller_name_new, substring_index(a.store, '-', 1), '') as station_store,
        a.store as store,
        a.msku,
        a.local_sku,
        a.product_name,
        a.currency,
        a.price_before,
        a.price_after,
        a.drop_ratio,
        count(distinct case
            when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                               and a.adjust_date
            then p.dt_date end) as pre_seen_days,
        count(distinct case
            when p.dt_date between date_add(a.adjust_date, interval 1 day)
                               and date_add(a.adjust_date, interval %(post_days)s day)
            then p.dt_date end) as post_seen_days,
        coalesce(sum(case when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                                             and a.adjust_date
                          then p.sales_qty else 0 end), 0) as pre_sales_qty,
        coalesce(sum(case when p.dt_date between date_add(a.adjust_date, interval 1 day)
                                             and date_add(a.adjust_date, interval %(post_days)s day)
                          then p.sales_qty else 0 end), 0) as post_sales_qty,
        coalesce(sum(case when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                                             and a.adjust_date
                          then p.sales_amount else 0 end), 0) as pre_sales_amount,
        coalesce(sum(case when p.dt_date between date_add(a.adjust_date, interval 1 day)
                                             and date_add(a.adjust_date, interval %(post_days)s day)
                          then p.sales_amount else 0 end), 0) as post_sales_amount,
        coalesce(sum(case when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                                             and a.adjust_date
                          then p.order_gross_profit else 0 end), 0) as pre_order_profit,
        coalesce(sum(case when p.dt_date between date_add(a.adjust_date, interval 1 day)
                                             and date_add(a.adjust_date, interval %(post_days)s day)
                          then p.order_gross_profit else 0 end), 0) as post_order_profit,
        cast(nullif(substring_index(group_concat(case
            when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                               and a.adjust_date
             and p.ranking > 0 then p.ranking end order by p.dt_date desc, p.ranking asc separator ','), ',', 1), '') as unsigned)
            as pre_small_rank,
        cast(nullif(substring_index(group_concat(case
            when p.dt_date between date_add(a.adjust_date, interval 1 day)
                               and date_add(a.adjust_date, interval %(post_days)s day)
             and p.ranking > 0 then p.ranking end order by p.dt_date desc, p.ranking asc separator ','), ',', 1), '') as unsigned)
            as post_small_rank,
        max(case when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                                      and a.adjust_date
                  and p.ranking > 0 then p.dt_date end) as pre_small_rank_date,
        max(case when p.dt_date between date_add(a.adjust_date, interval 1 day)
                                       and date_add(a.adjust_date, interval %(post_days)s day)
                  and p.ranking > 0 then p.dt_date end) as post_small_rank_date
    from {adjustments} a
    left join {performance} p
      on p.seller_name_new = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))
     and p.country = a.country
     and p.seller_sku_adj = a.msku
     and p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day)
                       and date_add(a.adjust_date, interval %(post_days)s day)
    where a.adjust_date between %(adjust_start)s and %(adjust_end)s
    group by a.adjust_date, a.store, a.msku, a.country, a.seller_name_new, a.local_sku,
             a.product_name, a.currency, a.price_before, a.price_after, a.drop_ratio
    """


def _station_role_finance_sql(target_schema: str) -> str:
    adjustments = target_table(target_schema, "price_review_adjustment_source")
    finance_table = target_table(target_schema, "dashboard_limit_price_daily_snapshot")
    return f"""
    with adjustment_keys as (
        select distinct
            a.adjust_date,
            a.country,
            coalesce(a.seller_name_new, substring_index(a.store, '-', 1)) as station_store,
            a.seller_name_new,
            a.msku,
            a.local_sku,
            a.currency
        from {adjustments} a
        where a.adjust_date between %(adjust_start)s and %(adjust_end)s
    ), finance_dates as (
        select
            a.adjust_date,
            a.country,
            a.station_store,
            a.msku,
            max(fd.snapshot_date) as finance_snapshot_date
        from adjustment_keys a
        left join (
            select distinct snapshot_date
            from {finance_table}
        ) fd on fd.snapshot_date <= a.adjust_date
        group by a.adjust_date, a.country, a.station_store, a.msku
    )
    select
        a.adjust_date,
        a.country,
        a.station_store,
        a.msku,
        max(d.finance_snapshot_date) as finance_snapshot_date,
        count(distinct concat_ws('|', f.margin_price_0, f.margin_price_5, f.margin_price_10,
            f.margin_price_15, f.margin_price_20, f.margin_price_25, f.margin_price_30, f.margin_price_35))
            as finance_ladder_variants,
        max(f.margin_price_0) as margin_price_0,
        max(f.margin_price_5) as margin_price_5,
        max(f.margin_price_10) as margin_price_10,
        max(f.margin_price_15) as margin_price_15,
        max(f.margin_price_20) as margin_price_20,
        max(f.margin_price_25) as margin_price_25,
        max(f.margin_price_30) as margin_price_30,
        max(f.margin_price_35) as margin_price_35
    from adjustment_keys a
    left join finance_dates d
     on d.adjust_date = a.adjust_date
     and d.country = a.country
     and d.station_store = a.station_store
     and d.msku = a.msku
    left join {finance_table} f
      on f.snapshot_date = d.finance_snapshot_date
     and f.seller_name_new = a.seller_name_new
     and f.country = a.country
     and f.seller_sku = a.msku
     and (a.local_sku is null or a.local_sku = '' or f.local_sku = a.local_sku)
     and (
            a.currency is null
         or a.currency = ''
         or f.currency = case a.currency
                when '€' then 'EUR'
                when '£' then 'GBP'
                when '$' then 'USD'
                when '¥' then 'JPY'
                else a.currency
            end
     )
    group by a.adjust_date, a.country, a.station_store, a.msku
    """


def _load_station_role_finance(cursor, target_schema: str, adjust_start: date, adjust_end: date) -> dict:
    cursor.execute(
        _station_role_finance_sql(target_schema),
        {"adjust_start": adjust_start, "adjust_end": adjust_end},
    )
    return {
        (row["adjust_date"], row["country"], row["station_store"], row["msku"]): row
        for row in cursor.fetchall()
    }


def _execute_station_role_tracking(
    target_conn,
    target_schema: str,
    adjust_start: date,
    adjust_end: date,
    latest_data_date: date,
) -> int:
    tracking_table = target_table(target_schema, "price_review_station_role_tracking")
    insert_sql = _insert_sql(tracking_table, STATION_ROLE_TRACKING_COLUMNS)
    affected = 0
    with target_conn.cursor() as cursor:
        finance_rows = _load_station_role_finance(cursor, target_schema, adjust_start, adjust_end)
        cursor.execute(
            f"select distinct data_date from {target_table(target_schema, 'station_sales_role_recent_cache')}"
        )
        recent_cache_dates = {row["data_date"] for row in cursor.fetchall()}
        for pre_days, post_days in _station_role_period_pairs():
            params = {
                "adjust_start": adjust_start,
                "adjust_end": adjust_end,
                "pre_days": pre_days,
                "post_days": post_days,
            }
            cached_roles = _load_cached_station_roles(
                cursor,
                target_schema,
                adjust_start,
                adjust_end,
                pre_days,
                post_days,
            )
            existing_rows = _load_existing_station_role_rows(
                cursor,
                target_schema,
                adjust_start,
                adjust_end,
                pre_days,
                post_days,
            )
            cursor.execute(_station_role_metrics_sql(target_schema), params)
            rows = cursor.fetchall()
            payload = []
            for raw in rows:
                business_key = (
                    raw["adjust_date"],
                    raw["country"],
                    raw["station_store"],
                    raw["msku"],
                )
                if not _should_refresh_station_role_tracking(
                    existing_rows.get(business_key),
                    recent_cache_dates,
                    pre_days=pre_days,
                    post_days=post_days,
                ):
                    continue
                raw.update(finance_rows.get(business_key, {}))
                pre_snapshot = cached_roles.get(("pre", *business_key))
                post_snapshot = cached_roles.get(("post", *business_key))
                built = build_station_role_tracking_row(
                    raw,
                    pre_days,
                    post_days,
                    latest_data_date,
                    pre_snapshot=pre_snapshot,
                    post_snapshot=post_snapshot,
                )
                payload.append({column: built.get(column) for column in STATION_ROLE_TRACKING_COLUMNS})
            if payload:
                cursor.executemany(insert_sql, payload)
                affected += len(payload)
    return affected


def execute_price_review_tracking(target_conn, target_schema: str, params: dict[str, object]) -> int:
    biz_date = params["biz_date"]
    if not isinstance(biz_date, date):
        raise RuntimeError("biz_date must be a date")
    ensure_price_review_tables(target_conn, target_schema)
    lookback = int(os.getenv("DASHBOARD_PRICE_REVIEW_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_DAYS)))
    adjust_start = biz_date - timedelta(days=max(lookback, 1) - 1)
    adjust_end = biz_date
    affected = 0
    with target_conn.cursor() as cursor:
        cursor.execute(
            f"select max(dt_date) as max_date from {target_table(target_schema, 'dashboard_product_performance_daily')}"
        )
        local_max_data_date = (cursor.fetchone() or {}).get("max_date")
        if not local_max_data_date:
            return 0

        for period_days in TRACKING_PERIODS:
            cursor.execute(
                f"""
                delete from {target_table(target_schema, "price_review_sku_tracking")}
                where period_days = %(period_days)s
                  and adjust_date between %(adjust_start)s and %(adjust_end)s
                  and date_add(adjust_date, interval %(period_days)s day) > %(local_max_data_date)s
                """,
                {
                    "period_days": period_days,
                    "adjust_start": adjust_start,
                    "adjust_end": adjust_end,
                    "local_max_data_date": local_max_data_date,
                },
            )
            cursor.execute(
                f"""
                delete from {target_table(target_schema, "price_review_sku_tracking")}
                where period_days = %(period_days)s
                  and adjust_date between %(adjust_start)s and %(adjust_end)s
                  and date_add(adjust_date, interval %(period_days)s day) <= %(local_max_data_date)s
                """,
                {
                    "period_days": period_days,
                    "adjust_start": adjust_start,
                    "adjust_end": adjust_end,
                    "local_max_data_date": local_max_data_date,
                },
            )
            cursor.execute(
                _tracking_insert_sql(target_schema),
                {
                    "period_days": period_days,
                    "adjust_start": adjust_start,
                    "adjust_end": adjust_end,
                    "local_max_data_date": local_max_data_date,
                },
            )
            affected += max(cursor.rowcount, 0)
            cursor.execute(
                _second_adjustment_update_sql(target_schema),
                {
                    "period_days": period_days,
                    "adjust_start": adjust_start,
                    "adjust_end": adjust_end,
                    "local_max_data_date": local_max_data_date,
                },
            )
        affected += _execute_station_role_tracking(
            target_conn,
            target_schema,
            _station_role_adjust_start(adjust_start),
            adjust_end,
            local_max_data_date,
        )
    target_conn.commit()
    return affected


def _second_adjustment_update_sql(target_schema: str) -> str:
    tracking = target_table(target_schema, "price_review_sku_tracking")
    adjustments = target_table(target_schema, "price_review_adjustment_source")
    return f"""
    update {tracking} t
    left join (
        select
            curr.adjust_date,
            curr.store,
            curr.msku,
            max(prev.adjust_date) as previous_adjust_date
        from {adjustments} curr
        left join {adjustments} prev
          on prev.store = curr.store
         and prev.msku = curr.msku
         and prev.adjust_date < curr.adjust_date
        where curr.adjust_date between %(adjust_start)s and %(adjust_end)s
          and date_add(curr.adjust_date, interval %(period_days)s day) <= %(local_max_data_date)s
        group by curr.adjust_date, curr.store, curr.msku
    ) p
      on p.adjust_date = t.adjust_date
     and p.store = t.store
     and p.msku = t.msku
    set
        t.previous_adjust_date = p.previous_adjust_date,
        t.is_second_adjustment = case when p.previous_adjust_date is not null then 1 else 0 end
    where t.period_days = %(period_days)s
      and t.adjust_date between %(adjust_start)s and %(adjust_end)s
      and date_add(t.adjust_date, interval %(period_days)s day) <= %(local_max_data_date)s
    """


def _tracking_insert_sql(target_schema: str) -> str:
    tracking = target_table(target_schema, "price_review_sku_tracking")
    adjustments = target_table(target_schema, "price_review_adjustment_source")
    performance = target_table(target_schema, "dashboard_product_performance_daily")
    listing = target_table(target_schema, "dashboard_listing_price_daily_snapshot")
    return f"""
    insert into {tracking} (
        adjust_date, period_days, country, store, seller_name_new, msku, product_name,
        price_before, price_after, drop_ratio, drop_range, price_band,
        period_start, period_end, period_after_start, period_after_end,
        sales_before, sales_after, sales_change, sales_change_rate,
        daily_sales_before, daily_sales_after, daily_sales_change,
        revenue_before, revenue_after, revenue_change,
        profit_before, profit_after, profit_change,
        margin_before, margin_after, margin_change,
        sessions_before, sessions_after, sessions_change,
        conversion_before, conversion_after, ctr_before, ctr_after,
        ad_spend_before, ad_spend_after, ad_revenue_before, ad_revenue_after,
        acos_before, acos_after, tacos_before, tacos_after, cpc_before, cpc_after,
        rank_before, rank_after, rank_change,
        sales_band_before, sales_band_after,
        daily_sales_band_before, daily_sales_band_after,
        margin_band_before, margin_band_after,
        rank_band_before, rank_band_after,
        risk_level, issue_tags, suggested_action
    )
    with base as (
        select
            a.*,
            date_sub(a.adjust_date, interval (%(period_days)s - 1) day) as period_start,
            a.adjust_date as period_end,
            date_add(a.adjust_date, interval 1 day) as period_after_start,
            date_add(a.adjust_date, interval %(period_days)s day) as period_after_end
        from {adjustments} a
        where a.adjust_date between %(adjust_start)s and %(adjust_end)s
          and date_add(a.adjust_date, interval %(period_days)s day) <= %(local_max_data_date)s
    ),
    perf as (
        select
            b.adjust_date,
            b.store,
            b.msku,
            sum(case when p.dt_date between b.period_start and b.period_end then p.sales_qty else 0 end) as sales_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.sales_qty else 0 end) as sales_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.sales_amount else 0 end) as revenue_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.sales_amount else 0 end) as revenue_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.order_gross_profit else 0 end) as profit_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.order_gross_profit else 0 end) as profit_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.sessions_total else 0 end) as sessions_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.sessions_total else 0 end) as sessions_after,
            cast(0 as decimal(18,4)) as orders_before,
            cast(0 as decimal(18,4)) as orders_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.ad_clicks else 0 end) as clicks_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.ad_clicks else 0 end) as clicks_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.ad_impressions else 0 end) as impressions_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.ad_impressions else 0 end) as impressions_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.ad_spend else 0 end) as ad_spend_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.ad_spend else 0 end) as ad_spend_after,
            sum(case when p.dt_date between b.period_start and b.period_end then p.ad_sales else 0 end) as ad_revenue_before,
            sum(case when p.dt_date between b.period_after_start and b.period_after_end then p.ad_sales else 0 end) as ad_revenue_after,
            max(coalesce(b.product_name, p.local_sku)) as product_name,
            max(b.country) as country
        from base b
        left join {performance} p
          on p.seller_name = b.store
         and p.seller_sku_adj = b.msku
         and p.dt_date between b.period_start and b.period_after_end
        group by b.adjust_date, b.store, b.msku
    ),
    ranks as (
        select
            b.adjust_date,
            b.store,
            b.msku,
            max(case when p.dt_date = b.period_end then p.ranking end) as rank_before,
            max(case when p.dt_date = b.period_after_end then p.ranking end) as rank_after
        from base b
        left join {performance} p
          on p.seller_name = b.store
         and p.seller_sku_adj = b.msku
         and p.dt_date in (b.period_end, b.period_after_end)
        group by b.adjust_date, b.store, b.msku
    ),
    calc as (
        select
            b.adjust_date,
            %(period_days)s as period_days,
            coalesce(b.country, p.country, '') as country,
            b.store,
            b.seller_name_new,
            b.msku,
            coalesce(p.product_name, b.product_name, '') as product_name,
            b.price_before,
            b.price_after,
            coalesce(b.drop_ratio, (b.price_after - b.price_before) / nullif(b.price_before, 0), 0) as drop_ratio,
            b.period_start,
            b.period_end,
            b.period_after_start,
            b.period_after_end,
            coalesce(p.sales_before, 0) as sales_before,
            coalesce(p.sales_after, 0) as sales_after,
            coalesce(p.revenue_before, 0) as revenue_before,
            coalesce(p.revenue_after, 0) as revenue_after,
            coalesce(p.profit_before, 0) as profit_before,
            coalesce(p.profit_after, 0) as profit_after,
            coalesce(p.sessions_before, 0) as sessions_before,
            coalesce(p.sessions_after, 0) as sessions_after,
            coalesce(p.orders_before, 0) as orders_before,
            coalesce(p.orders_after, 0) as orders_after,
            coalesce(p.clicks_before, 0) as clicks_before,
            coalesce(p.clicks_after, 0) as clicks_after,
            coalesce(p.impressions_before, 0) as impressions_before,
            coalesce(p.impressions_after, 0) as impressions_after,
            coalesce(p.ad_spend_before, 0) as ad_spend_before,
            coalesce(p.ad_spend_after, 0) as ad_spend_after,
            coalesce(p.ad_revenue_before, 0) as ad_revenue_before,
            coalesce(p.ad_revenue_after, 0) as ad_revenue_after,
            r.rank_before,
            r.rank_after
        from base b
        left join perf p
          on p.adjust_date = b.adjust_date
         and p.store = b.store
         and p.msku = b.msku
        left join ranks r
          on r.adjust_date = b.adjust_date
         and r.store = b.store
         and r.msku = b.msku
    )
    select
        adjust_date,
        period_days,
        country,
        store,
        seller_name_new,
        msku,
        product_name,
        price_before,
        price_after,
        drop_ratio,
        case
            when drop_ratio < -0.30 then '降价>30%%'
            when drop_ratio < -0.20 then '降价20-30%%'
            when drop_ratio < -0.15 then '降价15-20%%'
            when drop_ratio < -0.10 then '降价10-15%%'
            when drop_ratio < -0.05 then '降价5-10%%'
            when drop_ratio < 0 then '降价0-5%%'
            when drop_ratio = 0 then '持平'
            when drop_ratio <= 0.05 then '涨价0-5%%'
            when drop_ratio <= 0.10 then '涨价5-10%%'
            when drop_ratio <= 0.15 then '涨价10-15%%'
            when drop_ratio <= 0.20 then '涨价15-20%%'
            when drop_ratio <= 0.30 then '涨价20-30%%'
            else '涨价>30%%'
        end as drop_range,
        concat('$', floor(coalesce(price_before, 0) / 20) * 20, '-', (floor(coalesce(price_before, 0) / 20) + 1) * 20) as price_band,
        period_start,
        period_end,
        period_after_start,
        period_after_end,
        sales_before,
        sales_after,
        sales_after - sales_before as sales_change,
        coalesce((sales_after - sales_before) / nullif(sales_before, 0), 0) as sales_change_rate,
        sales_before / nullif(period_days, 0) as daily_sales_before,
        sales_after / nullif(period_days, 0) as daily_sales_after,
        (sales_after - sales_before) / nullif(period_days, 0) as daily_sales_change,
        revenue_before,
        revenue_after,
        revenue_after - revenue_before as revenue_change,
        profit_before,
        profit_after,
        profit_after - profit_before as profit_change,
        coalesce(profit_before / nullif(revenue_before, 0), 0) as margin_before,
        coalesce(profit_after / nullif(revenue_after, 0), 0) as margin_after,
        coalesce(profit_after / nullif(revenue_after, 0), 0) - coalesce(profit_before / nullif(revenue_before, 0), 0) as margin_change,
        sessions_before,
        sessions_after,
        sessions_after - sessions_before as sessions_change,
        coalesce(orders_before / nullif(sessions_before, 0), 0) as conversion_before,
        coalesce(orders_after / nullif(sessions_after, 0), 0) as conversion_after,
        coalesce(clicks_before / nullif(impressions_before, 0), 0) as ctr_before,
        coalesce(clicks_after / nullif(impressions_after, 0), 0) as ctr_after,
        ad_spend_before,
        ad_spend_after,
        ad_revenue_before,
        ad_revenue_after,
        coalesce(ad_spend_before / nullif(ad_revenue_before, 0), 0) as acos_before,
        coalesce(ad_spend_after / nullif(ad_revenue_after, 0), 0) as acos_after,
        coalesce(ad_spend_before / nullif(revenue_before, 0), 0) as tacos_before,
        coalesce(ad_spend_after / nullif(revenue_after, 0), 0) as tacos_after,
        coalesce(ad_spend_before / nullif(clicks_before, 0), 0) as cpc_before,
        coalesce(ad_spend_after / nullif(clicks_after, 0), 0) as cpc_after,
        rank_before,
        rank_after,
        coalesce(rank_after, 0) - coalesce(rank_before, 0) as rank_change,
        case
            when sales_before = 0 then '0个'
            when sales_before <= 2 then '1-2个'
            when sales_before <= 5 then '3-5个'
            when sales_before <= 10 then '6-10个'
            when sales_before <= 20 then '11-20个'
            else '>20个'
        end as sales_band_before,
        case
            when sales_after = 0 then '0个'
            when sales_after <= 2 then '1-2个'
            when sales_after <= 5 then '3-5个'
            when sales_after <= 10 then '6-10个'
            when sales_after <= 20 then '11-20个'
            else '>20个'
        end as sales_band_after,
        case
            when sales_before / nullif(period_days, 0) = 0 then '日销 0'
            when sales_before / nullif(period_days, 0) < 1 then '日销 <1'
            when sales_before / nullif(period_days, 0) <= 5 then '日销 1-5'
            else '日销 >5'
        end as daily_sales_band_before,
        case
            when sales_after / nullif(period_days, 0) = 0 then '日销 0'
            when sales_after / nullif(period_days, 0) < 1 then '日销 <1'
            when sales_after / nullif(period_days, 0) <= 5 then '日销 1-5'
            else '日销 >5'
        end as daily_sales_band_after,
        case
            when sales_before = 0 then '无销售'
            when coalesce(profit_before / nullif(revenue_before, 0), 0) < 0 then '毛利率 <0%%'
            when coalesce(profit_before / nullif(revenue_before, 0), 0) < 0.10 then '毛利率 0-10%%'
            when coalesce(profit_before / nullif(revenue_before, 0), 0) < 0.15 then '毛利率 10-15%%'
            when coalesce(profit_before / nullif(revenue_before, 0), 0) < 0.25 then '毛利率 15-25%%'
            when coalesce(profit_before / nullif(revenue_before, 0), 0) < 0.35 then '毛利率 25-35%%'
            else '毛利率 >35%%'
        end as margin_band_before,
        case
            when sales_after = 0 then '无销售'
            when coalesce(profit_after / nullif(revenue_after, 0), 0) < 0 then '毛利率 <0%%'
            when coalesce(profit_after / nullif(revenue_after, 0), 0) < 0.10 then '毛利率 0-10%%'
            when coalesce(profit_after / nullif(revenue_after, 0), 0) < 0.15 then '毛利率 10-15%%'
            when coalesce(profit_after / nullif(revenue_after, 0), 0) < 0.25 then '毛利率 15-25%%'
            when coalesce(profit_after / nullif(revenue_after, 0), 0) < 0.35 then '毛利率 25-35%%'
            else '毛利率 >35%%'
        end as margin_band_after,
        case
            when coalesce(rank_before, 0) <= 0 then '无排名'
            when rank_before <= 50 then '1-50'
            when rank_before <= 100 then '51-100'
            when rank_before <= 200 then '101-200'
            when rank_before <= 500 then '201-500'
            else '>500'
        end as rank_band_before,
        case
            when coalesce(rank_after, 0) <= 0 then '无排名'
            when rank_after <= 50 then '1-50'
            when rank_after <= 100 then '51-100'
            when rank_after <= 200 then '101-200'
            when rank_after <= 500 then '201-500'
            else '>500'
        end as rank_band_after,
        case
            when sales_before > 0 and sales_after = 0 then '高'
            when sales_after < sales_before * 0.5 or profit_after < profit_before then '中'
            when coalesce(rank_after, 0) > coalesce(rank_before, 0) and coalesce(rank_before, 0) > 0 then '低'
            else '观察'
        end as risk_level,
        trim(both ', ' from concat(
            case when sales_after < sales_before * 0.5 then '销量下滑, ' else '' end,
            case when profit_after < profit_before then '利润下降, ' else '' end,
            case when sales_before > 0 and sales_after = 0 then '断销, ' else '' end,
            case when coalesce(ad_spend_after / nullif(ad_revenue_after, 0), 0) > coalesce(ad_spend_before / nullif(ad_revenue_before, 0), 0) * 1.2 then 'ACOS升高, ' else '' end,
            case when coalesce(rank_after, 0) > coalesce(rank_before, 0) and coalesce(rank_before, 0) > 0 then '排名恶化, ' else '' end
        )) as issue_tags,
        case
            when coalesce(ad_spend_after / nullif(ad_revenue_after, 0), 0) > coalesce(ad_spend_before / nullif(ad_revenue_before, 0), 0) * 1.2 then '优化广告'
            when sales_before > 0 and sales_after = 0 then '观察'
            when sales_after < sales_before * 0.5 and coalesce(rank_after, 0) > coalesce(rank_before, 0) then '降价'
            when profit_after < profit_before then '观察'
            else '观察'
        end as suggested_action
    from calc
    on duplicate key update
        country=values(country),
        seller_name_new=values(seller_name_new),
        product_name=values(product_name),
        price_before=values(price_before),
        price_after=values(price_after),
        drop_ratio=values(drop_ratio),
        drop_range=values(drop_range),
        price_band=values(price_band),
        period_start=values(period_start),
        period_end=values(period_end),
        period_after_start=values(period_after_start),
        period_after_end=values(period_after_end),
        sales_before=values(sales_before),
        sales_after=values(sales_after),
        sales_change=values(sales_change),
        sales_change_rate=values(sales_change_rate),
        daily_sales_before=values(daily_sales_before),
        daily_sales_after=values(daily_sales_after),
        daily_sales_change=values(daily_sales_change),
        revenue_before=values(revenue_before),
        revenue_after=values(revenue_after),
        revenue_change=values(revenue_change),
        profit_before=values(profit_before),
        profit_after=values(profit_after),
        profit_change=values(profit_change),
        margin_before=values(margin_before),
        margin_after=values(margin_after),
        margin_change=values(margin_change),
        sessions_before=values(sessions_before),
        sessions_after=values(sessions_after),
        sessions_change=values(sessions_change),
        conversion_before=values(conversion_before),
        conversion_after=values(conversion_after),
        ctr_before=values(ctr_before),
        ctr_after=values(ctr_after),
        ad_spend_before=values(ad_spend_before),
        ad_spend_after=values(ad_spend_after),
        ad_revenue_before=values(ad_revenue_before),
        ad_revenue_after=values(ad_revenue_after),
        acos_before=values(acos_before),
        acos_after=values(acos_after),
        tacos_before=values(tacos_before),
        tacos_after=values(tacos_after),
        cpc_before=values(cpc_before),
        cpc_after=values(cpc_after),
        rank_before=values(rank_before),
        rank_after=values(rank_after),
        rank_change=values(rank_change),
        sales_band_before=values(sales_band_before),
        sales_band_after=values(sales_band_after),
        daily_sales_band_before=values(daily_sales_band_before),
        daily_sales_band_after=values(daily_sales_band_after),
        margin_band_before=values(margin_band_before),
        margin_band_after=values(margin_band_after),
        rank_band_before=values(rank_band_before),
        rank_band_after=values(rank_band_after),
        risk_level=values(risk_level),
        issue_tags=values(issue_tags),
        suggested_action=values(suggested_action),
        updated_at=current_timestamp
    """


def execute_price_review_step(
    target_conn,
    source_conn,
    target_schema: str,
    step: PriceReviewStep,
    params: dict[str, object],
    batch_size: int,
    log_task,
) -> None:
    started_at = datetime.now()
    affected_rows = 0
    try:
        if step.name == "price_review_source_load":
            if source_conn is None:
                raise RuntimeError("Source connection is required for price_review_source_load")
            affected_rows = execute_price_review_source_load(
                target_conn,
                source_conn,
                target_schema,
                params,
                batch_size,
            )
        elif step.name == "price_review_tracking":
            affected_rows = execute_price_review_tracking(target_conn, target_schema, params)
            if source_conn is not None:
                try:
                    drift = run_station_sales_role_drift_check(
                        source_conn,
                        target_conn,
                        target_schema,
                        sample_limit=int(os.getenv("DASHBOARD_STATION_ROLE_DRIFT_SAMPLE", "4000")),
                        match_threshold=float(os.getenv("DASHBOARD_STATION_ROLE_DRIFT_THRESHOLD", "0.95")),
                    )
                    prefix = "success" if drift["status"] == "ok" else "warn"
                    print(
                        f"[{prefix}] station_role_drift: data_date={drift['data_date']} "
                        f"sample={drift['sample_count']} match_rate={drift['match_rate']:.2%} "
                        f"missing_rate={drift['missing_rate']:.2%}"
                    )
                except Exception as exc:
                    print(f"[warn] station_role_drift check failed: {exc}", file=os.sys.stderr)
        else:
            raise RuntimeError(f"Unknown price review step: {step.name}")
        log_task(target_conn, step.name, params, "success", affected_rows, started_at)
        print(f"[success] {step.name}: affected_rows={affected_rows}")
    except Exception:
        target_conn.rollback()
        error = traceback.format_exc()
        log_task(target_conn, step.name, params, "failed", affected_rows, started_at, error)
        print(f"[failed] {step.name}", file=os.sys.stderr)
        raise
