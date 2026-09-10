"""Build local SP product diagnosis facts and period snapshots."""
from __future__ import annotations

import argparse
import configparser
import json
import socket
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor

from etl.replenishment_update import apply_database_ini_env

from etl.sp_advertising_recommendations import business_key


PERIOD_CODES = {"7d": 7, "14d": 14, "30d": 30, "90d": 90}
TASK_NAME = "sp_product_diagnosis"


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def budget_snapshot_fields(
    budget: Mapping[str, Any] | None,
    month_spend_cny: Any,
    budget_date: date | None,
    performance_date: date | None,
) -> dict[str, Any]:
    if not budget:
        return {
            "budget_snapshot_date": budget_date,
            "budget_performance_date": performance_date,
            "monthly_ad_budget_cny": None,
            "month_spend_cny": _decimal(month_spend_cny),
            "remaining_budget_cny": None,
            "budget_usage_rate": None,
            "inventory_sufficient_flag": None,
            "weekly_inventory_sufficient_flag": None,
            "budget_support_status": "预算数据未匹配",
        }
    monthly = _decimal(budget.get("monthly_ad_budget_cny"))
    spend = _decimal(month_spend_cny)
    remaining = max(monthly - spend, Decimal(0)) if monthly is not None and spend is not None else None
    usage = spend / monthly if monthly is not None and monthly > 0 and spend is not None else None
    inventory = budget.get("inventory_sufficient_flag")
    weekly_inventory = budget.get("weekly_inventory_sufficient_flag")
    inventory_blocked = inventory is not None and not bool(inventory)
    budget_exhausted = monthly is not None and spend is not None and spend >= monthly
    if inventory_blocked and budget_exhausted:
        support = "库存不足且预算已用尽"
    elif inventory_blocked:
        support = "库存不足，禁止提价"
    elif budget_exhausted:
        support = "预算已用尽，禁止提价"
    elif monthly is None:
        support = "预算额度缺失"
    elif spend is None:
        support = "本月花费未匹配"
    else:
        support = "支持提价"
    return {
        "budget_snapshot_date": budget_date,
        "budget_performance_date": performance_date,
        "monthly_ad_budget_cny": monthly,
        "month_spend_cny": spend,
        "remaining_budget_cny": remaining,
        "budget_usage_rate": usage,
        "inventory_sufficient_flag": None if inventory is None else int(bool(inventory)),
        "weekly_inventory_sufficient_flag": None if weekly_inventory is None else int(bool(weekly_inventory)),
        "budget_support_status": support,
    }


def period_bounds(end_date: date, period: str) -> tuple[date, date]:
    if period not in PERIOD_CODES:
        raise ValueError("unsupported period")
    return end_date - timedelta(days=PERIOD_CODES[period] - 1), end_date


def diagnosis_ddl() -> str:
    return """
create table if not exists dashboard_sp_product_diagnosis_batch (
  batch_id bigint not null auto_increment primary key, task_name varchar(100) not null,
  data_start_90d date not null, data_end date not null, recommendation_batch_id bigint null,
  status varchar(30) not null, dry_run tinyint not null default 0,
  ad_product_keys bigint not null default 0, operating_matched_keys bigint not null default 0,
  unmatched_keys bigint not null default 0, daily_rows bigint not null default 0,
  period_rows bigint not null default 0, quality_json json null, error_message text null,
  host_name varchar(255) null, started_at datetime not null, finished_at datetime null,
  key idx_diag_batch_status(status,data_end,batch_id)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_sp_product_diagnosis_daily (
  id bigint not null auto_increment primary key, batch_id bigint not null,
  data_date date not null, diagnosis_key char(64) not null,
  seller_name varchar(255) not null, country_code varchar(20) not null,
  currency_code varchar(20) null, targeting_type varchar(20) null, msku varchar(100) not null, asin varchar(50) null,
  ad_present_flag tinyint not null default 1,
  operating_matched_flag tinyint not null default 0,
  operating_sales_qty decimal(20,4) null, operating_sales_amount decimal(20,4) null,
  operating_gross_profit decimal(20,4) null, operating_sessions decimal(20,4) null,
  operating_return_count decimal(20,4) null, operating_return_amount decimal(20,4) null,
  operating_net_amount decimal(20,4) null, operating_inventory_qty decimal(20,4) null,
  ad_impressions bigint not null default 0, ad_clicks bigint not null default 0,
  ad_cost decimal(20,4) not null default 0,
  ad_orders_1d decimal(20,4) not null default 0, ad_orders_7d decimal(20,4) not null default 0,
  ad_orders_14d decimal(20,4) not null default 0, ad_orders_30d decimal(20,4) not null default 0,
  ad_units_1d decimal(20,4) not null default 0, ad_units_7d decimal(20,4) not null default 0,
  ad_units_14d decimal(20,4) not null default 0, ad_units_30d decimal(20,4) not null default 0,
  ad_sales_1d decimal(20,4) not null default 0, ad_sales_7d decimal(20,4) not null default 0,
  ad_sales_14d decimal(20,4) not null default 0, ad_sales_30d decimal(20,4) not null default 0,
  created_at datetime not null default current_timestamp,
  unique key uq_diag_daily(batch_id,data_date,diagnosis_key),
  key idx_diag_daily_date(batch_id,data_date,currency_code),
  key idx_diag_daily_key(batch_id,diagnosis_key,data_date),
  key idx_diag_daily_product(batch_id,seller_name,country_code,msku)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_sp_product_diagnosis_period_snapshot (
  id bigint not null auto_increment primary key, batch_id bigint not null,
  diagnosis_key char(64) not null, period_code varchar(10) not null,
  period_start date not null, period_end date not null, recommendation_batch_id bigint null,
  seller_name varchar(255) not null, country_code varchar(20) not null,
  currency_code varchar(20) null, targeting_type varchar(20) null, msku varchar(100) not null, asin varchar(50) null,
  operating_matched_flag tinyint not null default 0, operating_matched_days int not null default 0,
  operating_sales_qty decimal(20,4) null, operating_sales_amount decimal(20,4) null,
  operating_gross_profit decimal(20,4) null, operating_sessions decimal(20,4) null,
  operating_return_count decimal(20,4) null, operating_return_amount decimal(20,4) null,
  operating_net_amount decimal(20,4) null, operating_inventory_qty decimal(20,4) null,
  ad_impressions bigint not null default 0, ad_clicks bigint not null default 0, ad_cost decimal(20,4) not null default 0,
  ad_orders_1d decimal(20,4) not null default 0, ad_orders_7d decimal(20,4) not null default 0,
  ad_orders_14d decimal(20,4) not null default 0, ad_orders_30d decimal(20,4) not null default 0,
  ad_units_1d decimal(20,4) not null default 0, ad_units_7d decimal(20,4) not null default 0,
  ad_units_14d decimal(20,4) not null default 0, ad_units_30d decimal(20,4) not null default 0,
  ad_sales_1d decimal(20,4) not null default 0, ad_sales_7d decimal(20,4) not null default 0,
  ad_sales_14d decimal(20,4) not null default 0, ad_sales_30d decimal(20,4) not null default 0,
  bid_increase_count int not null default 0, bid_decrease_count int not null default 0,
  bid_manual_review_count int not null default 0, bid_keep_count int not null default 0,
  bid_insufficient_count int not null default 0, add_recommended_count int not null default 0,
  add_existing_count int not null default 0, add_observe_count int not null default 0,
  negative_recommended_count int not null default 0, negative_manual_review_count int not null default 0,
  negative_existing_count int not null default 0, negative_observe_count int not null default 0,
  actionable_count int not null default 0, actionable_flag tinyint not null default 0,
  budget_snapshot_date date null, budget_performance_date date null,
  monthly_ad_budget_cny decimal(20,2) null, month_spend_cny decimal(20,4) null,
  remaining_budget_cny decimal(20,4) null, budget_usage_rate decimal(20,8) null,
  inventory_sufficient_flag tinyint null, weekly_inventory_sufficient_flag tinyint null,
  budget_support_status varchar(100) null,
  data_warning varchar(500) null, created_at datetime not null default current_timestamp,
  unique key uq_diag_period(batch_id,period_code,diagnosis_key),
  key idx_diag_period_default(batch_id,period_code,currency_code,actionable_flag,ad_cost,diagnosis_key),
  key idx_diag_period_product(batch_id,period_code,seller_name,country_code,msku)
) engine=InnoDB default charset=utf8mb4
""".strip()


def daily_insert_sql() -> str:
    return """
insert into dashboard_sp_product_diagnosis_daily (
 batch_id,data_date,diagnosis_key,seller_name,country_code,currency_code,targeting_type,msku,asin,ad_present_flag,
 operating_matched_flag,operating_sales_qty,operating_sales_amount,operating_gross_profit,
 operating_sessions,operating_return_count,operating_return_amount,operating_net_amount,operating_inventory_qty,
 ad_impressions,ad_clicks,ad_cost,ad_orders_1d,ad_orders_7d,ad_orders_14d,ad_orders_30d,
 ad_units_1d,ad_units_7d,ad_units_14d,ad_units_30d,ad_sales_1d,ad_sales_7d,ad_sales_14d,ad_sales_30d)
with ad_source as (
 select report_date data_date,lower(trim(seller_name)) seller_key,upper(trim(country_code)) country_key,lower(trim(msku)) msku_key,
 seller_name,country_code,currency_code,targeting_type,msku,asin,impressions,clicks,cost,
 orders_1d,orders_7d,orders_14d,orders_30d,units_1d,units_7d,units_14d,units_30d,sales_1d,sales_7d,sales_14d,sales_30d
 from dashboard_sp_product_ad_daily
 where report_date between %(start)s and %(end)s
   and coalesce(trim(msku),'')<>''
   and coalesce(trim(seller_name),'')<>''
   and coalesce(trim(country_code),'')<>''
), ad as (
 select data_date,sha2(concat_ws(char(31),seller_key,country_key,msku_key),256) diagnosis_key,
 max(seller_name) seller_name,country_key country_code,max(currency_code) currency_code,
 case when sum(coalesce(targeting_type,'')='auto')>0 and sum(coalesce(targeting_type,'')='manual')>0 then 'mixed'
      when sum(coalesce(targeting_type,'')='auto')>0 then 'auto'
      when sum(coalesce(targeting_type,'')='manual')>0 then 'manual' else null end targeting_type,
 max(msku) msku,max(asin) asin,sum(impressions) ad_impressions,sum(clicks) ad_clicks,sum(cost) ad_cost,
 sum(orders_1d) ad_orders_1d,sum(orders_7d) ad_orders_7d,sum(orders_14d) ad_orders_14d,sum(orders_30d) ad_orders_30d,
 sum(units_1d) ad_units_1d,sum(units_7d) ad_units_7d,sum(units_14d) ad_units_14d,sum(units_30d) ad_units_30d,
 sum(sales_1d) ad_sales_1d,sum(sales_7d) ad_sales_7d,sum(sales_14d) ad_sales_14d,sum(sales_30d) ad_sales_30d
 from ad_source group by data_date,seller_key,country_key,msku_key
), product_keys as (
 select diagnosis_key,max(seller_name) seller_name,max(country_code) country_code,max(currency_code) currency_code,max(msku) msku,max(asin) asin,
 lower(trim(max(seller_name))) seller_key,lower(trim(max(msku))) msku_key from ad group by diagnosis_key
), operating as (
 select p.dt_date,lower(trim(p.seller_name)) seller_key,lower(trim(p.seller_sku_adj)) msku_key,
 sum(p.sales_qty) sales_qty,sum(p.sales_amount) sales_amount,sum(p.order_gross_profit) gross_profit,
 sum(p.sessions_total) sessions,sum(p.return_count) return_count,sum(p.return_amount) return_amount,
 sum(p.net_amount) net_amount,max(p.afn_fulfillable_quantity) inventory_qty
 from product_keys k join dashboard_product_performance_daily p
   on p.seller_name=k.seller_name and p.seller_sku_adj=k.msku and p.dt_date between %(start)s and %(end)s
 group by p.dt_date,lower(trim(p.seller_name)),lower(trim(p.seller_sku_adj))
), combined as (
 select a.data_date,a.diagnosis_key,a.seller_name,a.country_code,a.currency_code,a.targeting_type,a.msku,a.asin,1 ad_present_flag,
 (o.dt_date is not null) operating_matched_flag,o.sales_qty,o.sales_amount,o.gross_profit,o.sessions,o.return_count,o.return_amount,o.net_amount,o.inventory_qty,
 a.ad_impressions,a.ad_clicks,a.ad_cost,a.ad_orders_1d,a.ad_orders_7d,a.ad_orders_14d,a.ad_orders_30d,
 a.ad_units_1d,a.ad_units_7d,a.ad_units_14d,a.ad_units_30d,a.ad_sales_1d,a.ad_sales_7d,a.ad_sales_14d,a.ad_sales_30d
 from ad a left join operating o on o.dt_date=a.data_date and o.seller_key=lower(trim(a.seller_name)) and o.msku_key=lower(trim(a.msku))
 union all
 select o.dt_date,k.diagnosis_key,k.seller_name,k.country_code,k.currency_code,null,k.msku,k.asin,0,1,
 o.sales_qty,o.sales_amount,o.gross_profit,o.sessions,o.return_count,o.return_amount,o.net_amount,o.inventory_qty,
 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
 from operating o join product_keys k on k.seller_key=o.seller_key and k.msku_key=o.msku_key
 left join ad a on a.data_date=o.dt_date and a.diagnosis_key=k.diagnosis_key where a.diagnosis_key is null
)
select %(batch_id)s,data_date,diagnosis_key,seller_name,country_code,currency_code,targeting_type,msku,asin,ad_present_flag,
 operating_matched_flag,sales_qty,sales_amount,gross_profit,sessions,return_count,return_amount,net_amount,inventory_qty,
 ad_impressions,ad_clicks,ad_cost,ad_orders_1d,ad_orders_7d,ad_orders_14d,ad_orders_30d,
 ad_units_1d,ad_units_7d,ad_units_14d,ad_units_30d,ad_sales_1d,ad_sales_7d,ad_sales_14d,ad_sales_30d from combined
""".strip()


def period_insert_sql() -> str:
    return """
insert into dashboard_sp_product_diagnosis_period_snapshot (
 batch_id,diagnosis_key,period_code,period_start,period_end,recommendation_batch_id,seller_name,country_code,currency_code,targeting_type,msku,asin,
 operating_matched_flag,operating_matched_days,operating_sales_qty,operating_sales_amount,operating_gross_profit,operating_sessions,
 operating_return_count,operating_return_amount,operating_net_amount,operating_inventory_qty,ad_impressions,ad_clicks,ad_cost,
 ad_orders_1d,ad_orders_7d,ad_orders_14d,ad_orders_30d,ad_units_1d,ad_units_7d,ad_units_14d,ad_units_30d,
 ad_sales_1d,ad_sales_7d,ad_sales_14d,ad_sales_30d,bid_increase_count,bid_decrease_count,bid_manual_review_count,
 bid_keep_count,bid_insufficient_count,add_recommended_count,add_existing_count,add_observe_count,
 negative_recommended_count,negative_manual_review_count,negative_existing_count,negative_observe_count,
 actionable_count,actionable_flag,data_warning)
with ranked as (
 select d.*,row_number() over(partition by diagnosis_key order by operating_matched_flag desc,data_date desc) inventory_rank
 from dashboard_sp_product_diagnosis_daily d where batch_id=%(batch_id)s and data_date between %(start)s and %(end)s
), base as (
 select diagnosis_key,max(seller_name) seller_name,max(country_code) country_code,max(currency_code) currency_code,
 case when sum(targeting_type in ('auto','mixed'))>0 and sum(targeting_type in ('manual','mixed'))>0 then 'mixed'
      when sum(targeting_type in ('auto','mixed'))>0 then 'auto'
      when sum(targeting_type in ('manual','mixed'))>0 then 'manual' else null end targeting_type,
 max(msku) msku,max(asin) asin,
 max(operating_matched_flag) operating_matched_flag,sum(operating_matched_flag) operating_matched_days,
 sum(operating_sales_qty) operating_sales_qty,sum(operating_sales_amount) operating_sales_amount,sum(operating_gross_profit) operating_gross_profit,
 sum(operating_sessions) operating_sessions,sum(operating_return_count) operating_return_count,sum(operating_return_amount) operating_return_amount,
 sum(operating_net_amount) operating_net_amount,max(case when inventory_rank=1 then operating_inventory_qty end) operating_inventory_qty,
 sum(ad_impressions) ad_impressions,sum(ad_clicks) ad_clicks,sum(ad_cost) ad_cost,
 sum(ad_orders_1d) ad_orders_1d,sum(ad_orders_7d) ad_orders_7d,sum(ad_orders_14d) ad_orders_14d,sum(ad_orders_30d) ad_orders_30d,
 sum(ad_units_1d) ad_units_1d,sum(ad_units_7d) ad_units_7d,sum(ad_units_14d) ad_units_14d,sum(ad_units_30d) ad_units_30d,
 sum(ad_sales_1d) ad_sales_1d,sum(ad_sales_7d) ad_sales_7d,sum(ad_sales_14d) ad_sales_14d,sum(ad_sales_30d) ad_sales_30d
 from ranked group by diagnosis_key having sum(ad_present_flag)>0
), bid as (
 select sha2(concat_ws(char(31),lower(trim(seller_name)),upper(trim(country_code)),lower(trim(msku))),256) diagnosis_key,
 sum(status='increase') bi,sum(status='decrease') bd,sum(status='manual_review') bm,sum(status='keep') bk,sum(status='insufficient_data') bx
 from dashboard_sp_bid_recommendation where batch_id=%(recommendation_batch_id)s and coalesce(trim(msku),'')<>'' group by diagnosis_key
), adds as (
 select sha2(concat_ws(char(31),lower(trim(seller_name)),upper(trim(country_code)),lower(trim(msku))),256) diagnosis_key,
 sum(status='recommended') ar,sum(status='existing') ae,sum(status='observe') ao
 from dashboard_sp_add_term_recommendation where batch_id=%(recommendation_batch_id)s and coalesce(trim(msku),'')<>'' group by diagnosis_key
), neg as (
 select sha2(concat_ws(char(31),lower(trim(seller_name)),upper(trim(country_code)),lower(trim(msku))),256) diagnosis_key,
 sum(status='recommended') nr,sum(status='manual_review') nm,sum(status='existing') ne,sum(status='observe') no
 from dashboard_sp_negative_term_recommendation where batch_id=%(recommendation_batch_id)s and coalesce(trim(msku),'')<>'' group by diagnosis_key
)
select %(batch_id)s,b.diagnosis_key,%(period)s,%(start)s,%(end)s,%(recommendation_batch_id)s,b.seller_name,b.country_code,b.currency_code,b.targeting_type,b.msku,b.asin,
 b.operating_matched_flag,b.operating_matched_days,b.operating_sales_qty,b.operating_sales_amount,b.operating_gross_profit,b.operating_sessions,
 b.operating_return_count,b.operating_return_amount,b.operating_net_amount,b.operating_inventory_qty,b.ad_impressions,b.ad_clicks,b.ad_cost,
 b.ad_orders_1d,b.ad_orders_7d,b.ad_orders_14d,b.ad_orders_30d,b.ad_units_1d,b.ad_units_7d,b.ad_units_14d,b.ad_units_30d,
 b.ad_sales_1d,b.ad_sales_7d,b.ad_sales_14d,b.ad_sales_30d,coalesce(bid.bi,0),coalesce(bid.bd,0),coalesce(bid.bm,0),
 coalesce(bid.bk,0),coalesce(bid.bx,0),coalesce(adds.ar,0),coalesce(adds.ae,0),coalesce(adds.ao,0),
 coalesce(neg.nr,0),coalesce(neg.nm,0),coalesce(neg.ne,0),coalesce(neg.no,0),
 coalesce(bid.bi,0)+coalesce(bid.bd,0)+coalesce(bid.bm,0)+coalesce(adds.ar,0)+coalesce(neg.nr,0)+coalesce(neg.nm,0),
 (coalesce(bid.bi,0)+coalesce(bid.bd,0)+coalesce(bid.bm,0)+coalesce(adds.ar,0)+coalesce(neg.nr,0)+coalesce(neg.nm,0)>0),
 case when b.operating_matched_flag=0 then '经营数据未匹配' else null end
from base b left join bid using(diagnosis_key) left join adds using(diagnosis_key) left join neg using(diagnosis_key)
""".strip()


def _settings() -> dict[str, Any]:
    apply_database_ini_env(Path("config/database.ini"))
    return dict(
        host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
        password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        database=os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test")),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        read_timeout=600,
        write_timeout=600,
    )


def ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        for statement in diagnosis_ddl().split(";"):
            if statement.strip():
                cur.execute(statement)
        cur.execute("select count(*) n from information_schema.columns where table_schema=database() and table_name='dashboard_sp_product_diagnosis_daily' and column_name='ad_present_flag'")
        if not cur.fetchone()["n"]:
            cur.execute("alter table dashboard_sp_product_diagnosis_daily add column ad_present_flag tinyint not null default 1 after asin")
        cur.execute("select count(*) n from information_schema.columns where table_schema=database() and table_name='dashboard_sp_product_diagnosis_daily' and column_name='targeting_type'")
        if not cur.fetchone()["n"]:
            cur.execute("alter table dashboard_sp_product_diagnosis_daily add column targeting_type varchar(20) null after currency_code")
        cur.execute("select count(*) n from information_schema.statistics where table_schema=database() and table_name='dashboard_sp_product_diagnosis_daily' and index_name='idx_diag_daily_key'")
        if not cur.fetchone()["n"]:
            cur.execute("alter table dashboard_sp_product_diagnosis_daily add key idx_diag_daily_key(batch_id,diagnosis_key,data_date)")
        period_columns = {
            "targeting_type": "varchar(20) null",
            "budget_snapshot_date": "date null",
            "budget_performance_date": "date null",
            "monthly_ad_budget_cny": "decimal(20,2) null",
            "month_spend_cny": "decimal(20,4) null",
            "remaining_budget_cny": "decimal(20,4) null",
            "budget_usage_rate": "decimal(20,8) null",
            "inventory_sufficient_flag": "tinyint null",
            "weekly_inventory_sufficient_flag": "tinyint null",
            "budget_support_status": "varchar(100) null",
        }
        for column, definition in period_columns.items():
            cur.execute("select count(*) n from information_schema.columns where table_schema=database() and table_name='dashboard_sp_product_diagnosis_period_snapshot' and column_name=%s", (column,))
            if not cur.fetchone()["n"]:
                cur.execute(f"alter table dashboard_sp_product_diagnosis_period_snapshot add column {column} {definition}")
        for table in ("dashboard_sp_bid_recommendation", "dashboard_sp_add_term_recommendation", "dashboard_sp_negative_term_recommendation"):
            name = "idx_diag_product_" + table.split("_")[2]
            cur.execute("select count(*) n from information_schema.statistics where table_schema=database() and table_name=%s and index_name=%s", (table, name))
            if not cur.fetchone()["n"]:
                cur.execute(f"alter table {table} add key {name}(batch_id,seller_name,country_code,msku,status)")
    conn.commit()


def _apply_budget_snapshot(conn, batch_id: int, cutoff: date) -> None:
    with conn.cursor() as cur:
        cur.execute("select max(biz_date) d from dashboard_ad_budget_snapshot")
        budget_date = (cur.fetchone() or {}).get("d")
        budget_rows = []
        if budget_date:
            cur.execute("select * from dashboard_ad_budget_snapshot where biz_date=%s", (budget_date,))
            budget_rows = cur.fetchall()
        cur.execute("select max(dt_date) d from dashboard_product_performance_daily where dt_date<=%s", (cutoff,))
        performance_date = (cur.fetchone() or {}).get("d")
        spend_rows = []
        if performance_date:
            cur.execute(
                """select seller_name_new,country,seller_sku_adj,sum(ad_spend) month_spend_cny
                   from dashboard_product_performance_daily
                   where dt_date between %s and %s
                   group by seller_name_new,country,seller_sku_adj""",
                (performance_date.replace(day=1), performance_date),
            )
            spend_rows = cur.fetchall()
        cur.execute("select id,seller_name,country_code,msku from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s", (batch_id,))
        diagnosis_rows = cur.fetchall()
    budgets = {business_key(r.get("seller_name_new"), r.get("country"), r.get("seller_sku_adj")): r for r in budget_rows}
    spends = {business_key(r.get("seller_name_new"), r.get("country"), r.get("seller_sku_adj")): r.get("month_spend_cny") for r in spend_rows}
    updates = []
    for row in diagnosis_rows:
        key = business_key(row.get("seller_name"), row.get("country_code"), row.get("msku"))
        fields = budget_snapshot_fields(budgets.get(key), spends.get(key), budget_date, performance_date)
        updates.append((*fields.values(), row["id"]))
    if updates:
        columns = list(budget_snapshot_fields(None, None, budget_date, performance_date))
        assignments = ",".join(f"{column}=%s" for column in columns)
        with conn.cursor() as cur:
            cur.executemany(f"update dashboard_sp_product_diagnosis_period_snapshot set {assignments} where id=%s", updates)


def build_product_diagnosis(cutoff: date | None = None, dry_run: bool = False, connection=None) -> dict[str, Any]:
    conn = connection or pymysql.connect(**_settings())
    own = connection is None
    lock_name = "dashboard_sp_product_diagnosis_update"
    batch_id = None
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute("select get_lock(%s,0) ok", (lock_name,))
            if cur.fetchone()["ok"] != 1:
                raise RuntimeError("产品诊断更新任务正在运行")
            if cutoff is None:
                cur.execute("select min(a) cutoff from (select max(report_date) a from dashboard_sp_product_ad_daily union all select max(dt_date) from dashboard_product_performance_daily) x")
                cutoff = cur.fetchone()["cutoff"]
            start_90, _ = period_bounds(cutoff, "90d")
            cur.execute("select batch_id from dashboard_sp_recommendation_batch where status='success' and cutoff_date<=%s order by cutoff_date desc,batch_id desc limit 1", (cutoff,))
            rec = cur.fetchone()
            rec_id = rec["batch_id"] if rec else None
            if rec_id is None:
                raise RuntimeError("没有可用的广告建议成功批次")
            if dry_run:
                cur.execute("select count(distinct sha2(concat_ws(char(31),lower(trim(seller_name)),upper(trim(country_code)),lower(trim(msku))),256)) n from dashboard_sp_product_ad_daily where report_date between %s and %s and coalesce(trim(msku),'')<>'' and coalesce(trim(seller_name),'')<>'' and coalesce(trim(country_code),'')<>''", (start_90, cutoff))
                return {"status": "dry_run", "data_start_90d": start_90, "data_end": cutoff, "ad_product_keys": cur.fetchone()["n"], "recommendation_batch_id": rec_id}
            now = datetime.now()
            cur.execute("insert into dashboard_sp_product_diagnosis_batch(task_name,data_start_90d,data_end,recommendation_batch_id,status,host_name,started_at) values(%s,%s,%s,%s,'running',%s,%s)", (TASK_NAME,start_90,cutoff,rec_id,socket.gethostname(),now))
            batch_id = cur.lastrowid
            conn.commit()
            cur.execute(daily_insert_sql(), {"batch_id": batch_id, "start": start_90, "end": cutoff})
            daily_rows = cur.rowcount
            for code in PERIOD_CODES:
                start, end = period_bounds(cutoff, code)
                cur.execute(period_insert_sql(), {"batch_id": batch_id, "recommendation_batch_id": rec_id, "period": code, "start": start, "end": end})
            _apply_budget_snapshot(conn, batch_id, cutoff)
            cur.execute("select count(*) rows_n,count(distinct diagnosis_key) keys_n,sum(operating_matched_flag) matched from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s and period_code='30d'", (batch_id,))
            check = cur.fetchone()
            row_count = int(check["rows_n"] or 0)
            key_count = int(check["keys_n"] or 0)
            matched_count = int(check["matched"] or 0)
            cur.execute("select count(*) n from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s", (batch_id,)); period_rows=cur.fetchone()["n"]
            cur.execute("select count(*) n from (select diagnosis_key from dashboard_sp_product_diagnosis_daily where batch_id=%s group by diagnosis_key having count(distinct coalesce(currency_code,''))>1) c", (batch_id,)); currency_conflicts=cur.fetchone()["n"]
            cur.execute("select sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,sum(orders_7d) orders_7d,sum(sales_7d) sales_7d from dashboard_sp_product_ad_daily where report_date between %s and %s and coalesce(trim(msku),'')<>'' and coalesce(trim(seller_name),'')<>'' and coalesce(trim(country_code),'')<>''", period_bounds(cutoff,"30d"))
            source_totals=cur.fetchone()
            cur.execute("select sum(ad_impressions) impressions,sum(ad_clicks) clicks,sum(ad_cost) cost,sum(ad_orders_7d) orders_7d,sum(ad_sales_7d) sales_7d from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s and period_code='30d'", (batch_id,)); snapshot_totals=cur.fetchone()
            quality = {"period_30d_rows": row_count, "duplicate_30d_keys": row_count-key_count,
                       "operating_unmatched_keys": key_count-matched_count, "currency_conflicts": currency_conflicts,
                       "ad_totals_match": source_totals == snapshot_totals}
            if quality["duplicate_30d_keys"]:
                raise RuntimeError("产品诊断快照存在重复业务键")
            if currency_conflicts or not quality["ad_totals_match"]:
                raise RuntimeError("产品诊断币种或广告指标核对失败")
            cur.execute("update dashboard_sp_product_diagnosis_batch set status='success',ad_product_keys=%s,operating_matched_keys=%s,unmatched_keys=%s,daily_rows=%s,period_rows=%s,quality_json=%s,finished_at=now() where batch_id=%s",
                        (key_count,matched_count,key_count-matched_count,daily_rows,period_rows,json.dumps(quality,ensure_ascii=False),batch_id))
        conn.commit()
        return {"status":"success","batch_id":batch_id,"data_start_90d":start_90,"data_end":cutoff,"recommendation_batch_id":rec_id,"daily_rows":daily_rows,"period_rows":period_rows,**quality}
    except Exception as exc:
        conn.rollback()
        if batch_id:
            with conn.cursor() as cur:
                cur.execute("update dashboard_sp_product_diagnosis_batch set status='failed',error_message=%s,finished_at=now() where batch_id=%s", (str(exc),batch_id))
            conn.commit()
        raise
    finally:
        try:
            with conn.cursor() as cur: cur.execute("select release_lock(%s)", (lock_name,))
        finally:
            if own: conn.close()


def main() -> int:
    parser=argparse.ArgumentParser(description="更新SP广告产品诊断本地结果")
    parser.add_argument("--cutoff-date", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    args=parser.parse_args()
    print(json.dumps(build_product_diagnosis(args.cutoff_date,args.dry_run),ensure_ascii=False,default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
