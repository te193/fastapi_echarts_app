"""Build read-only SP advertising recommendations in local MySQL."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

import pymysql
from pymysql.cursors import DictCursor

from app.services.sp_recommendation_rules import (
    calculate_add_recommendation,
    calculate_bid_recommendation,
    calculate_negative_recommendation,
    classify_search_term,
    mature_window,
)
from app.services.sp_governance_data import base_store_name
from app.services.sp_term_protection import classify_term_protection
from etl.replenishment_update import apply_database_ini_env
from etl.sp_term_protection_update import (
    ensure_protection_context_table,
    refresh_term_protection_context,
)


RULE_VERSION = "sp-recommendation-v9-existing-object-state"
TASK_NAME = "sp_advertising_recommendations"
MARGIN_STEPS = (0, 5, 10, 15, 20, 25, 30, 35)
COUNTRY_ALIASES = {
    "美国": "us", "加拿大": "ca", "墨西哥": "mx", "巴西": "br",
    "英国": "uk", "德国": "de", "法国": "fr", "意大利": "it",
    "西班牙": "es", "荷兰": "nl", "瑞典": "se", "波兰": "pl",
    "比利时": "be", "日本": "jp", "澳大利亚": "au", "阿联酋": "ae",
    "沙特阿拉伯": "sa", "沙特": "sa", "印度": "in", "新加坡": "sg",
    "土耳其": "tr",
}


def recommendation_ddl() -> str:
    return """
create table if not exists dashboard_sp_recommendation_batch (
  batch_id bigint not null auto_increment primary key,
  task_name varchar(100) not null, rule_version varchar(100) not null,
  cutoff_date date not null, mature_start date not null, mature_end date not null,
  status varchar(30) not null, dry_run tinyint not null default 0,
  source_days int not null default 0, bid_rows bigint not null default 0,
  add_rows bigint not null default 0, negative_rows bigint not null default 0,
  quality_json json null, error_message text null, host_name varchar(255) null,
  started_at datetime not null, finished_at datetime null,
  key idx_status_cutoff(status, cutoff_date, batch_id)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_sp_bid_recommendation (
  id bigint not null auto_increment primary key, batch_id bigint not null,
  recommendation_key char(64) not null, profile_id bigint null,
  seller_name varchar(255) null, country_code varchar(20) null, currency_code varchar(20) null,
  campaign_id bigint null, campaign_name_current varchar(255) null,
  ad_group_id bigint null, ad_group_name_current varchar(255) null,
  targeting_type varchar(50) null, object_type varchar(30) not null, object_id bigint null,
  object_text varchar(1000) collate utf8mb4_bin null, match_type varchar(100) null,
  object_state_current varchar(50) null, msku varchar(100) null, asin varchar(50) null,
  associated_msku_count int not null default 0, impressions bigint null, clicks bigint null,
  cost decimal(20,4) null, orders decimal(20,4) null, sales decimal(20,4) null,
  aov decimal(20,6) null, cvr decimal(20,8) null, current_bid decimal(20,6) null,
  listing_price decimal(20,6) null, margin_rate decimal(10,6) null,
  theoretical_cpc decimal(20,6) null, reference_cpc_20 decimal(20,6) null,
  reference_cpc_333 decimal(20,6) null, suggested_bid decimal(20,6) null,
  change_direction varchar(30) null, change_amount decimal(20,6) null,
  change_rate decimal(20,8) null, status varchar(30) not null, priority_rank int not null,
  reason_codes json not null, created_at datetime not null default current_timestamp,
  unique key uq_bid_batch_key(batch_id, recommendation_key),
  key idx_bid_filter(batch_id, currency_code, status, priority_rank, cost),
  key idx_bid_default(batch_id, currency_code, priority_rank, cost, id),
  key idx_bid_default_v2(batch_id, currency_code, priority_rank asc, cost desc, id asc),
  key idx_bid_store(batch_id, seller_name, country_code), key idx_bid_msku(batch_id, msku)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_sp_add_term_recommendation (
  id bigint not null auto_increment primary key, batch_id bigint not null,
  recommendation_key char(64) not null, profile_id bigint null,
  seller_name varchar(255) null, country_code varchar(20) null, currency_code varchar(20) null,
  campaign_id bigint null, campaign_name_current varchar(255) null,
  ad_group_id bigint null, ad_group_name_current varchar(255) null,
  target_id bigint null, targeting_type varchar(50) null, match_type varchar(100) null,
  search_term varchar(1000) collate utf8mb4_bin not null, target_text varchar(1000) null,
  msku varchar(100) null, asin varchar(50) null, associated_msku_count int not null default 0,
  protection_brand varchar(255) null, protection_category varchar(500) null,
  product_launch_date date null, product_age_days int null,
  impressions bigint null, clicks bigint null, cost decimal(20,4) null,
  orders decimal(20,4) null, sales decimal(20,4) null, acos decimal(20,8) null,
  suggestion_type varchar(50) not null, suggestion_value varchar(1000) collate utf8mb4_bin not null,
  status varchar(30) not null, priority varchar(30) not null, priority_rank int not null,
  reason_codes json not null, created_at datetime not null default current_timestamp,
  unique key uq_add_batch_key(batch_id, recommendation_key),
  key idx_add_filter(batch_id, currency_code, status, priority_rank, cost),
  key idx_add_default(batch_id, currency_code, priority_rank, cost, id),
  key idx_add_default_v2(batch_id, currency_code, priority_rank asc, cost desc, id asc),
  key idx_add_store(batch_id, seller_name, country_code), key idx_add_msku(batch_id, msku)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_sp_negative_term_recommendation like dashboard_sp_add_term_recommendation;
create table if not exists dashboard_sp_governance_ad_group_snapshot (
  batch_id bigint not null, profile_id bigint not null,
  base_store_name varchar(255) not null, seller_name varchar(255) null,
  country_code varchar(20) null, currency_code varchar(20) null,
  campaign_id bigint not null, campaign_name_current varchar(255) null,
  campaign_state_current varchar(50) null, targeting_type varchar(50) null,
  ad_group_id bigint not null, ad_group_name_current varchar(255) null,
  ad_group_state_current varchar(50) null,
  msku varchar(100) null, asin varchar(50) null,
  msku_mapping_status varchar(40) not null default 'mapping_missing',
  period_msku_count int not null default 0, current_msku_count int not null default 0,
  impressions bigint not null default 0, clicks bigint not null default 0,
  cost decimal(20,4) not null default 0, orders decimal(20,4) not null default 0,
  sales decimal(20,4) not null default 0,
  bid_increase_count int not null default 0, bid_decrease_count int not null default 0,
  bid_manual_review_count int not null default 0, bid_action_count int not null default 0,
  add_recommended_count int not null default 0, add_manual_review_count int not null default 0,
  add_action_count int not null default 0,
  negative_recommended_count int not null default 0, negative_manual_review_count int not null default 0,
  negative_action_count int not null default 0,
  manual_review_count int not null default 0, actionable_flag tinyint not null default 0,
  created_at datetime not null default current_timestamp,
  primary key(batch_id,profile_id,campaign_id,ad_group_id),
  key idx_governance_store(batch_id,base_store_name,ad_group_state_current,targeting_type),
  key idx_governance_campaign(batch_id,profile_id,campaign_id),
  key idx_governance_msku(batch_id,base_store_name,msku),
  key idx_governance_actions(batch_id,actionable_flag,manual_review_count)
) engine=InnoDB default charset=utf8mb4;
""".strip()


def coverage_is_complete(days: Iterable[date], start: date, end: date) -> bool:
    actual = set(days)
    expected = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    return actual == expected


def margin_band_rate(price: Decimal | None, ladder: Mapping[int, Decimal | None]) -> Decimal | None:
    if price is None or ladder.get(0) is None or price < Decimal(ladder[0]):
        return None
    matched = 0
    for step in MARGIN_STEPS:
        threshold = ladder.get(step)
        if threshold is not None and price >= Decimal(threshold):
            matched = step
    return Decimal(matched) / Decimal(100)


def business_key(store: Any, country: Any, msku: Any) -> tuple[str, str, str]:
    store_key = str(store or "").strip().casefold()
    store_key = re.sub(r"-(?:eu-)?[a-z]{2}$", "", store_key)
    country_text = str(country or "").strip().casefold().replace("站", "")
    country_key = COUNTRY_ALIASES.get(country_text, country_text)
    return store_key, country_key, str(msku or "").strip().casefold()


def _connect(autocommit: bool = False):
    return pymysql.connect(
        host=os.environ["DASHBOARD_DB_HOST"],
        port=int(os.getenv("DASHBOARD_DB_PORT", "3306")),
        user=os.environ["DASHBOARD_DB_USER"],
        password=os.environ["DASHBOARD_DB_PASSWORD"],
        database=os.getenv("DASHBOARD_DB_NAME", "etl_datasync_test"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=autocommit,
        read_timeout=300,
        write_timeout=300,
    )


def _source_connect():
    return pymysql.connect(
        host=os.getenv("DASHBOARD_SOURCE_DB_HOST", os.getenv("OPT_LYT_DB_HOST", os.environ["DASHBOARD_DB_HOST"])),
        port=int(os.getenv("DASHBOARD_SOURCE_DB_PORT", os.getenv("OPT_LYT_DB_PORT", "3306"))),
        user=os.getenv("DASHBOARD_SOURCE_DB_USER", os.getenv("OPT_LYT_DB_USER", os.environ["DASHBOARD_DB_USER"])),
        password=os.getenv("DASHBOARD_SOURCE_DB_PASSWORD", os.getenv("OPT_LYT_DB_PASSWORD", os.environ["DASHBOARD_DB_PASSWORD"])),
        database=os.getenv("DASHBOARD_SOURCE_DB_NAME") or None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        read_timeout=300,
    )


def ensure_recommendation_tables(conn) -> None:
    with conn.cursor() as cur:
        for statement in recommendation_ddl().split(";"):
            if statement.strip():
                cur.execute(statement)
        for table, index_name in (
            ("dashboard_sp_bid_recommendation", "idx_bid_default_v2"),
            ("dashboard_sp_add_term_recommendation", "idx_add_default_v2"),
            ("dashboard_sp_negative_term_recommendation", "idx_negative_default_v2"),
        ):
            cur.execute(
                "select count(*) n from information_schema.statistics "
                "where table_schema=database() and table_name=%s and index_name=%s",
                (table, index_name),
            )
            if not cur.fetchone()["n"]:
                cur.execute(
                    f"alter table {table} add key {index_name} "
                    "(batch_id,currency_code,priority_rank asc,cost desc,id asc)"
                )
        for table in (
            "dashboard_sp_add_term_recommendation",
            "dashboard_sp_negative_term_recommendation",
        ):
            for column, definition in (
                ("protection_brand", "varchar(255) null"),
                ("protection_category", "varchar(500) null"),
                ("product_launch_date", "date null"),
                ("product_age_days", "int null"),
            ):
                cur.execute(
                    "select count(*) n from information_schema.columns "
                    "where table_schema=database() and table_name=%s and column_name=%s",
                    (table, column),
                )
                if not cur.fetchone()["n"]:
                    cur.execute(f"alter table {table} add column {column} {definition}")
        for column, definition in (
            ("msku", "varchar(100) null"),
            ("asin", "varchar(50) null"),
            ("msku_mapping_status", "varchar(40) not null default 'mapping_missing'"),
            ("period_msku_count", "int not null default 0"),
            ("current_msku_count", "int not null default 0"),
        ):
            cur.execute(
                "select count(*) n from information_schema.columns "
                "where table_schema=database() and table_name='dashboard_sp_governance_ad_group_snapshot' and column_name=%s",
                (column,),
            )
            if not cur.fetchone()["n"]:
                cur.execute(f"alter table dashboard_sp_governance_ad_group_snapshot add column {column} {definition}")
        cur.execute(
            "select count(*) n from information_schema.statistics "
            "where table_schema=database() and table_name='dashboard_sp_governance_ad_group_snapshot' "
            "and index_name='idx_governance_msku'"
        )
        if not cur.fetchone()["n"]:
            cur.execute(
                "alter table dashboard_sp_governance_ad_group_snapshot "
                "add key idx_governance_msku(batch_id,base_store_name,msku)"
            )
    ensure_protection_context_table(conn)
    conn.commit()


def _key(*values: Any) -> str:
    return hashlib.sha256("\x1f".join("" if v is None else str(v) for v in values).encode("utf-8")).hexdigest()


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def bid_protection_values(
    budget: Mapping[str, Any] | None, month_spend_cny: Any
) -> dict[str, bool | None]:
    """Keep missing protection data unknown instead of treating it as insufficient."""
    if not budget:
        return {"inventory_sufficient": None, "budget_sufficient": None}
    inventory_flag = budget.get("inventory_sufficient_flag")
    monthly_budget = _dec(budget.get("monthly_ad_budget_cny"))
    month_spend = _dec(month_spend_cny)
    return {
        "inventory_sufficient": None if inventory_flag is None else bool(inventory_flag),
        "budget_sufficient": None
        if monthly_budget is None or month_spend is None
        else month_spend < monthly_budget,
    }


def bid_cvr_benchmarks(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Decimal]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        clicks = _dec(row.get("clicks")) or Decimal(0)
        orders = _dec(row.get("orders")) or Decimal(0)
        if clicks <= 0:
            continue
        key = (str(row.get("object_type") or ""), str(row.get("country_code") or "").upper())
        group = groups.setdefault(key, {"clicks": Decimal(0), "orders": Decimal(0), "cvrs": []})
        group["clicks"] += clicks
        group["orders"] += orders
        group["cvrs"].append(orders / clicks)
    result: dict[tuple[str, str], dict[str, Decimal]] = {}
    for key, group in groups.items():
        values = sorted(group["cvrs"])
        position = Decimal(len(values) - 1) * Decimal("0.75")
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        fraction = position - lower
        p75 = values[lower] + (values[upper] - values[lower]) * fraction
        result[key] = {"site_cvr_avg": group["orders"] / group["clicks"], "site_cvr_p75": p75}
    return result


def _resolve_group_product(
    current: Mapping[str, Any] | None,
    period: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current = current or {}
    period = period or {}
    current_count = int(current.get("enabled_msku_count") or 0)
    period_count = int(period.get("period_msku_count") or 0)
    current_msku = str(current.get("msku") or "").strip()
    period_msku = str(period.get("msku") or "").strip()
    result = {
        "associated_msku_count": max(current_count, period_count),
        "msku": None,
        "asin": None,
        "msku_mapping_status": "msku_missing",
    }
    if period_count == 0 or current_count == 0:
        return result
    if period_count > 1:
        result["msku_mapping_status"] = "period_multiple_msku"
        return result
    if current_count > 1:
        result["msku_mapping_status"] = "current_multiple_msku"
        return result
    if period_msku.casefold() != current_msku.casefold():
        result["msku_mapping_status"] = "msku_changed"
        return result
    result.update(
        associated_msku_count=1,
        msku=period_msku,
        asin=period.get("asin") or current.get("asin"),
        msku_mapping_status="mapped",
    )
    return result


def _group_products(conn, start: date, end: date) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""select profile_id,campaign_id,ad_group_id,
            count(distinct case when lower(coalesce(state_current,''))='enabled' then nullif(trim(msku),'') end) enabled_msku_count,
            case when count(distinct case when lower(coalesce(state_current,''))='enabled' then nullif(trim(msku),'') end)=1
                 then max(case when lower(coalesce(state_current,''))='enabled' then msku end) end msku,
            case when count(distinct case when lower(coalesce(state_current,''))='enabled' then nullif(trim(msku),'') end)=1
                 then max(case when lower(coalesce(state_current,''))='enabled' then asin end) end asin
            from dashboard_sp_ad_group_msku_current group by profile_id,campaign_id,ad_group_id""")
        current = {(r["profile_id"], r["campaign_id"], r["ad_group_id"]): r for r in cur.fetchall()}
        cur.execute("""select profile_id,campaign_id,ad_group_id,
            count(distinct nullif(trim(msku),'')) period_msku_count,
            case when count(distinct nullif(trim(msku),''))=1 then max(msku) end msku,
            case when count(distinct nullif(trim(msku),''))=1 then max(asin) end asin
            from dashboard_sp_product_ad_daily where report_date between %s and %s
            group by profile_id,campaign_id,ad_group_id""", (start, end))
        period = {(r["profile_id"], r["campaign_id"], r["ad_group_id"]): r for r in cur.fetchall()}
    return {
        key: _resolve_group_product(current.get(key), period.get(key))
        for key in current.keys() | period.keys()
    }


def _latest_snapshot_rows(conn, table: str, date_column: str, cutoff: date | None) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cutoff is None:
            cur.execute(f"select max({date_column}) d from {table}")
        else:
            cur.execute(f"select max({date_column}) d from {table} where {date_column}<=%s", (cutoff,))
        row = cur.fetchone()
        if not row or not row["d"]:
            return []
        cur.execute(f"select * from {table} where {date_column}=%s", (row["d"],))
        return cur.fetchall()


def _business_lookups(conn, cutoff: date) -> tuple[dict, dict, dict]:
    listings = {}
    for row in _latest_snapshot_rows(conn, "dashboard_listing_price_daily_snapshot", "snapshot_date", cutoff):
        for store in {row.get("seller_name"), row.get("seller_name_new")}:
            listings[business_key(store, row.get("country"), row.get("seller_sku"))] = row
    ladders = {}
    for row in _latest_snapshot_rows(conn, "dashboard_limit_price_daily_snapshot", "snapshot_date", cutoff):
        ladders[business_key(row.get("seller_name_new"), row.get("country"), row.get("seller_sku"))] = row
    budgets = {}
    for row in _latest_snapshot_rows(conn, "dashboard_ad_budget_snapshot", "biz_date", None):
        budgets[business_key(row.get("seller_name_new"), row.get("country"), row.get("seller_sku_adj"))] = row
    return listings, ladders, budgets


def _month_spend_lookups(conn, cutoff: date) -> dict[tuple[str, str, str], Decimal]:
    month_start = cutoff.replace(day=1)
    with conn.cursor() as cur:
        cur.execute(
            """select seller_name_new,country,seller_sku_adj,sum(ad_spend) month_spend_cny
               from dashboard_product_performance_daily
               where dt_date between %s and %s
               group by seller_name_new,country,seller_sku_adj""",
            (month_start, cutoff),
        )
        rows = cur.fetchall()
    return {
        business_key(row.get("seller_name_new"), row.get("country"), row.get("seller_sku_adj")): _dec(row.get("month_spend_cny")) or Decimal(0)
        for row in rows
    }


def _lookup(mapping: dict, store: Any, country: Any, msku: Any) -> dict[str, Any] | None:
    target = business_key(store, country, msku)
    if target in mapping:
        return mapping[target]
    store_key, country_key, sku_key = target
    candidates = [v for (s, c, k), v in mapping.items() if s == store_key and k == sku_key and (c == country_key or not c or not country_key)]
    return candidates[0] if len(candidates) == 1 else None


def _protection_contexts(conn) -> dict[tuple[str, str, str], dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("select * from dashboard_sp_term_protection_current")
        rows = cur.fetchall()
    return {
        business_key(row.get("seller_name"), row.get("country_code"), row.get("msku")): row
        for row in rows
    }


def _search_term_rows(conn, start: date, end: date) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""select profile_id,max(seller_name) seller_name,max(country_code) country_code,
            max(currency_code) currency_code,campaign_id,max(campaign_name_current) campaign_name_current,
            ad_group_id,max(ad_group_name_current) ad_group_name_current,target_id,
            max(targeting_type) targeting_type,max(match_type) match_type,
            max(search_term) search_term,max(target_text) target_text,
            sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,
            sum(orders_7d) orders,sum(sales_7d) sales
            from dashboard_sp_search_term_daily ignore index (idx_date_profile,idx_date_store)
            where report_date between %s and %s
            group by profile_id,campaign_id,ad_group_id,target_id,cast(search_term as binary),cast(match_type as binary)""", (start, end))
        return cur.fetchall()


def _normalized_term(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _existing_state_bucket(value: Any) -> str | None:
    state = str(value or "").strip().lower()
    if state in {"enabled", "enable"}:
        return "enabled"
    if state in {"paused", "pause", "archived", "archive"}:
        return "inactive"
    return None


def _remember_existing_state(mapping: dict, key: tuple, raw_state: Any) -> None:
    state = _existing_state_bucket(raw_state)
    if state == "enabled" or (state == "inactive" and key not in mapping):
        mapping[key] = state


def extract_same_as_asins(expressions: Any) -> set[str]:
    if isinstance(expressions, str):
        try:
            expressions = json.loads(expressions)
        except json.JSONDecodeError:
            return set()
    result: set[str] = set()
    for item in expressions or []:
        if not isinstance(item, Mapping):
            continue
        expression_type = str(item.get("expression_item_type") or "").strip().lower()
        asin = str(item.get("expression_item_value") or "").strip().upper()
        if expression_type == "asinsameas" and re.fullmatch(r"B[0-9A-Z]{9}", asin):
            result.add(asin)
    return result


def existing_object_state(
    profile_id: Any,
    ad_group_id: Any,
    term: str,
    keywords: Mapping[tuple[Any, Any, str, str], str],
    products: Mapping[tuple[Any, Any, str], str],
) -> str | None:
    if classify_search_term(term) == "product_target":
        return products.get((profile_id, ad_group_id, term.strip().upper()))
    return keywords.get((profile_id, ad_group_id, _normalized_term(term), "EXACT"))


def _existing_objects(conn) -> tuple[dict[tuple[Any, Any, str, str], str], dict[tuple[Any, Any, str], str]]:
    with conn.cursor() as cur:
        cur.execute("""select distinct profile_id,ad_group_id,keyword_text,object_state_current
            ,match_type from dashboard_sp_keyword_daily
            where keyword_text is not null and upper(coalesce(match_type,''))='EXACT'""")
        keywords: dict[tuple[Any, Any, str, str], str] = {}
        for row in cur.fetchall():
            key = (row["profile_id"], row["ad_group_id"], _normalized_term(row["keyword_text"]), "EXACT")
            _remember_existing_state(keywords, key, row.get("object_state_current"))
        cur.execute("""select distinct profile_id,ad_group_id,target_expressions,object_state_current
            from dashboard_sp_search_term_daily
            where target_id is not null and target_expressions is not null""")
        products: dict[tuple[Any, Any, str], str] = {}
        for row in cur.fetchall():
            for asin in extract_same_as_asins(row.get("target_expressions")):
                key = (row["profile_id"], row["ad_group_id"], asin)
                _remember_existing_state(products, key, row.get("object_state_current"))
    return keywords, products


def _bid_rows(conn, start: date, end: date) -> list[dict[str, Any]]:
    queries = [
        ("keyword", """select profile_id,max(seller_name) seller_name,max(country_code) country_code,max(currency_code) currency_code,
         campaign_id,max(campaign_name_current) campaign_name_current,ad_group_id,max(ad_group_name_current) ad_group_name_current,
         max(targeting_type) targeting_type,keyword_id object_id,max(keyword_text) object_text,max(match_type) match_type,
         max(object_state_current) object_state_current,max(keyword_bid_current) current_bid,
         sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,sum(orders_7d) orders,sum(sales_7d) sales
         from dashboard_sp_keyword_daily ignore index (idx_date_profile,idx_date_store) where report_date between %s and %s
         group by profile_id,campaign_id,ad_group_id,keyword_id,cast(keyword_text as binary),cast(match_type as binary)"""),
        ("ad_group", """select profile_id,max(seller_name) seller_name,max(country_code) country_code,max(currency_code) currency_code,
         campaign_id,max(campaign_name_current) campaign_name_current,ad_group_id,max(ad_group_name_current) object_text,
         max(ad_group_name_current) ad_group_name_current,max(targeting_type) targeting_type,ad_group_id object_id,
         null match_type,max(ad_group_state_current) object_state_current,max(default_bid_current) current_bid,
         sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,sum(orders_7d) orders,sum(sales_7d) sales
         from dashboard_sp_ad_group_daily ignore index (idx_date_profile,idx_date_store) where report_date between %s and %s
         and lower(coalesce(targeting_type,''))='auto' group by profile_id,campaign_id,ad_group_id"""),
    ]
    rows = []
    with conn.cursor() as cur:
        for object_type, sql in queries:
            cur.execute(sql, (start, end))
            for row in cur.fetchall():
                row["object_type"] = object_type
                rows.append(row)
    return rows


def _insert_many(conn, table: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    sql = f"insert into {table} ({','.join(columns)}) values ({','.join(['%s'] * len(columns))})"
    with conn.cursor() as cur:
        cur.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def deduplicate_governance_assets(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[int, int, int], dict[str, Any]] = {}
    for source in rows:
        if source.get("profile_id") is None or source.get("campaign_id") is None or source.get("ad_group_id") is None:
            continue
        key = (int(source["profile_id"]), int(source["campaign_id"]), int(source["ad_group_id"]))
        unique[key] = dict(source)
    return list(unique.values())


def classify_governance_msku_mapping(
    period_count: int,
    period_msku: Any,
    current_count: int,
    current_msku: Any,
) -> tuple[str, str | None]:
    """Expose an MSKU only when mature-period and current ownership are both unique and consistent."""
    if int(period_count or 0) > 1:
        return "period_multiple_msku", None
    if int(current_count or 0) > 1:
        return "current_multiple_msku", None
    if int(period_count or 0) == 0 or not str(period_msku or "").strip():
        return "period_record_missing", None
    if int(current_count or 0) == 0 or not str(current_msku or "").strip():
        return "current_record_missing", None
    period_value = str(period_msku).strip()
    current_value = str(current_msku).strip()
    if period_value.casefold() != current_value.casefold():
        return "msku_changed", None
    return "normal_mapping", current_value


def refresh_governance_snapshot(
    conn,
    batch_id: int,
    mature_start: date,
    mature_end: date,
    source_connection=None,
) -> int:
    """Materialize one compact ad-group snapshot after recommendation publication."""
    owns_source = source_connection is None
    source = source_connection or _source_connect()
    try:
        assets: list[dict[str, Any]] = []
        current_products: dict[tuple[int, int, int], dict[str, Any]] = {}
        with source.cursor() as cur:
            cur.execute(
                """select c.profile_id,coalesce(nullif(c.seller_name,''),a.name) seller_name,
                    a.country_code,a.currency_code,c.campaign_id,c.name campaign_name_current,
                    lower(c.state) campaign_state_current,lower(c.targeting_type) targeting_type,
                    g.ad_group_id,g.name ad_group_name_current,lower(g.state) ad_group_state_current
                    from dwd_datasync.lx_advertising_sp_campaigns c
                    join dwd_datasync.lx_advertising_sp_ad_groups g
                      on g.profile_id=c.profile_id and g.campaign_id=c.campaign_id
                     and coalesce(g.delete_flag,0)=0
                    left join dwd_datasync.lx_advertising_account_list a
                      on a.profile_id=c.profile_id and coalesce(a.delete_flag,0)=0
                    where coalesce(c.delete_flag,0)=0"""
            )
            while True:
                chunk = cur.fetchmany(5000)
                if not chunk:
                    break
                assets.extend(chunk)
            cur.execute(
                """select profile_id,campaign_id,ad_group_id,
                    count(distinct nullif(trim(sku),'')) current_msku_count,
                    min(nullif(trim(sku),'')) current_msku,
                    min(nullif(trim(asin),'')) current_asin
                    from dwd_datasync.lx_advertising_sp_product_ads
                    where coalesce(delete_flag,0)=0 and lower(state) in ('enabled','paused')
                    group by profile_id,campaign_id,ad_group_id"""
            )
            current_products = {
                (int(row["profile_id"]), int(row["campaign_id"]), int(row["ad_group_id"])): row
                for row in cur.fetchall()
                if row.get("profile_id") is not None and row.get("campaign_id") is not None and row.get("ad_group_id") is not None
            }

        metrics: dict[tuple[int, int, int], dict[str, Any]] = {}
        period_products: dict[tuple[int, int, int], dict[str, Any]] = {}
        action_rows: dict[tuple[int, int, int], dict[str, int]] = {}
        with conn.cursor() as cur:
            cur.execute(
                """select profile_id,campaign_id,ad_group_id,
                    sum(impressions) impressions,sum(clicks) clicks,sum(cost) cost,
                    sum(orders_7d) orders,sum(sales_7d) sales
                    from dashboard_sp_ad_group_daily
                    where report_date between %s and %s
                    group by profile_id,campaign_id,ad_group_id""",
                (mature_start, mature_end),
            )
            metrics = {
                (int(row["profile_id"]), int(row["campaign_id"]), int(row["ad_group_id"])): row
                for row in cur.fetchall()
                if row.get("profile_id") is not None and row.get("campaign_id") is not None and row.get("ad_group_id") is not None
            }
            cur.execute(
                """select profile_id,campaign_id,ad_group_id,
                    count(distinct nullif(trim(msku),'')) period_msku_count,
                    min(nullif(trim(msku),'')) period_msku,
                    min(nullif(trim(asin),'')) period_asin
                    from dashboard_sp_product_ad_daily
                    where report_date between %s and %s
                    group by profile_id,campaign_id,ad_group_id""",
                (mature_start, mature_end),
            )
            period_products = {
                (int(row["profile_id"]), int(row["campaign_id"]), int(row["ad_group_id"])): row
                for row in cur.fetchall()
                if row.get("profile_id") is not None and row.get("campaign_id") is not None and row.get("ad_group_id") is not None
            }
            action_queries = (
                (
                    "bid",
                    """select profile_id,campaign_id,ad_group_id,
                        sum(status='increase' and coalesce(change_amount,0)<>0) bid_increase_count,
                        sum(status='decrease' and coalesce(change_amount,0)<>0) bid_decrease_count,
                        sum(status='manual_review') bid_manual_review_count
                        from dashboard_sp_bid_recommendation where batch_id=%s
                        group by profile_id,campaign_id,ad_group_id""",
                ),
                (
                    "add",
                    """select profile_id,campaign_id,ad_group_id,
                        sum(status='recommended') add_recommended_count,
                        sum(status='manual_review') add_manual_review_count
                        from dashboard_sp_add_term_recommendation where batch_id=%s
                        group by profile_id,campaign_id,ad_group_id""",
                ),
                (
                    "negative",
                    """select profile_id,campaign_id,ad_group_id,
                        sum(status='recommended') negative_recommended_count,
                        sum(status='manual_review') negative_manual_review_count
                        from dashboard_sp_negative_term_recommendation where batch_id=%s
                        group by profile_id,campaign_id,ad_group_id""",
                ),
            )
            for _, query in action_queries:
                cur.execute(query, (batch_id,))
                for row in cur.fetchall():
                    if row.get("profile_id") is None or row.get("campaign_id") is None or row.get("ad_group_id") is None:
                        continue
                    key = (int(row["profile_id"]), int(row["campaign_id"]), int(row["ad_group_id"]))
                    target = action_rows.setdefault(key, {})
                    target.update({name: int(value or 0) for name, value in row.items() if name.endswith("_count")})

        rows: list[dict[str, Any]] = []
        for asset in deduplicate_governance_assets(assets):
            if asset.get("profile_id") is None or asset.get("campaign_id") is None or asset.get("ad_group_id") is None:
                continue
            key = (int(asset["profile_id"]), int(asset["campaign_id"]), int(asset["ad_group_id"]))
            metric = metrics.get(key, {})
            period_product = period_products.get(key, {})
            current_product = current_products.get(key, {})
            period_count = int(period_product.get("period_msku_count") or 0)
            current_count = int(current_product.get("current_msku_count") or 0)
            mapping_status, mapped_msku = classify_governance_msku_mapping(
                period_count,
                period_product.get("period_msku"),
                current_count,
                current_product.get("current_msku"),
            )
            action = action_rows.get(key, {})
            bid_increase = action.get("bid_increase_count", 0)
            bid_decrease = action.get("bid_decrease_count", 0)
            bid_manual = action.get("bid_manual_review_count", 0)
            add_recommended = action.get("add_recommended_count", 0)
            add_manual = action.get("add_manual_review_count", 0)
            negative_recommended = action.get("negative_recommended_count", 0)
            negative_manual = action.get("negative_manual_review_count", 0)
            manual_total = bid_manual + add_manual + negative_manual
            bid_actions = bid_increase + bid_decrease
            rows.append(
                {
                    "batch_id": batch_id,
                    **asset,
                    "base_store_name": base_store_name(asset.get("seller_name"), asset.get("country_code")),
                    "msku": mapped_msku,
                    "asin": (current_product.get("current_asin") or period_product.get("period_asin")) if mapped_msku else None,
                    "msku_mapping_status": mapping_status,
                    "period_msku_count": period_count,
                    "current_msku_count": current_count,
                    "impressions": metric.get("impressions") or 0,
                    "clicks": metric.get("clicks") or 0,
                    "cost": metric.get("cost") or 0,
                    "orders": metric.get("orders") or 0,
                    "sales": metric.get("sales") or 0,
                    "bid_increase_count": bid_increase,
                    "bid_decrease_count": bid_decrease,
                    "bid_manual_review_count": bid_manual,
                    "bid_action_count": bid_actions,
                    "add_recommended_count": add_recommended,
                    "add_manual_review_count": add_manual,
                    "add_action_count": add_recommended,
                    "negative_recommended_count": negative_recommended,
                    "negative_manual_review_count": negative_manual,
                    "negative_action_count": negative_recommended,
                    "manual_review_count": manual_total,
                    "actionable_flag": int(bool(bid_actions or add_recommended or negative_recommended or manual_total)),
                }
            )

        columns = [
            "batch_id", "profile_id", "base_store_name", "seller_name", "country_code", "currency_code",
            "campaign_id", "campaign_name_current", "campaign_state_current", "targeting_type",
            "ad_group_id", "ad_group_name_current", "ad_group_state_current",
            "msku", "asin", "msku_mapping_status", "period_msku_count", "current_msku_count",
            "impressions", "clicks", "cost", "orders", "sales",
            "bid_increase_count", "bid_decrease_count", "bid_manual_review_count", "bid_action_count",
            "add_recommended_count", "add_manual_review_count", "add_action_count",
            "negative_recommended_count", "negative_manual_review_count", "negative_action_count",
            "manual_review_count", "actionable_flag",
        ]
        with conn.cursor() as cur:
            cur.execute("delete from dashboard_sp_governance_ad_group_snapshot where batch_id=%s", (batch_id,))
        _insert_many(conn, "dashboard_sp_governance_ad_group_snapshot", columns, rows)
        with conn.cursor() as cur:
            cur.execute("delete from dashboard_sp_governance_ad_group_snapshot where batch_id<>%s", (batch_id,))
        return len(rows)
    finally:
        if owns_source:
            source.close()


def build_recommendations(cutoff: date | None = None, dry_run: bool = False, connection=None) -> dict[str, Any]:
    apply_database_ini_env(Path("config/database.ini"))
    conn = connection or _connect(False)
    owns_connection = connection is None
    batch_id = None
    lock_name = f"{os.getenv('DASHBOARD_DB_NAME','etl_datasync_test')}.{TASK_NAME}"
    try:
        ensure_recommendation_tables(conn)
        with conn.cursor() as cur:
            if cutoff is None:
                cur.execute("select max(report_date) d from dashboard_sp_product_ad_daily")
                cutoff = cur.fetchone()["d"]
            if cutoff is None:
                raise RuntimeError("no SP advertising data")
            start, end = mature_window(cutoff)
            cur.execute("select distinct report_date from dashboard_sp_product_ad_daily where report_date between %s and %s", (start, end))
            days = [r["report_date"] for r in cur.fetchall()]
        if not coverage_is_complete(days, start, end):
            return {"status": "incomplete", "cutoff_date": str(cutoff), "mature_start": str(start), "mature_end": str(end), "source_days": len(set(days))}

        products = _group_products(conn, start, end)
        listings, ladders, budgets = _business_lookups(conn, cutoff)
        month_spends = _month_spend_lookups(conn, cutoff)
        protection_contexts = _protection_contexts(conn)
        existing_keywords, existing_products = _existing_objects(conn)
        term_rows = _search_term_rows(conn, start, end)
        add_rows, negative_rows = [], []
        priority_rank = {"highest": 1, "high": 1, "medium": 2, "none": 9}
        for source in term_rows:
            group_key = (source.get("profile_id"), source.get("campaign_id"), source.get("ad_group_id"))
            product = products.get(group_key, _resolve_group_product(None, None))
            source.update(product)
            term = str(source.get("search_term") or "")
            source["existing_state"] = existing_object_state(
                source.get("profile_id"), source.get("ad_group_id"), term,
                existing_keywords, existing_products,
            )
            if source.get("msku_mapping_status") == "mapped":
                context = _lookup(
                    protection_contexts,
                    source.get("seller_name"),
                    source.get("country_code"),
                    source.get("msku"),
                )
                source.update(classify_term_protection(term, context, cutoff=cutoff))
            add_rule = calculate_add_recommendation(source)
            negative_rule = calculate_negative_recommendation(source)
            common = {**source, "batch_id": None, "recommendation_key": _key(*group_key, source.get("target_id"), term, source.get("match_type"))}
            for target, rule in ((add_rows, add_rule), (negative_rows, negative_rule)):
                target.append({**common, **rule, "priority_rank": priority_rank[rule["priority"]], "reason_codes": json.dumps(rule["reason_codes"], ensure_ascii=False), "suggestion_value": rule["suggestion_value"]})

        bid_rows = []
        bid_sources = _bid_rows(conn, start, end)
        benchmarks = bid_cvr_benchmarks(bid_sources)
        for source in bid_sources:
            group_key = (source.get("profile_id"), source.get("campaign_id"), source.get("ad_group_id"))
            product = products.get(group_key, _resolve_group_product(None, None))
            source.update(product)
            listing = _lookup(listings, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            ladder_row = _lookup(ladders, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            budget = _lookup(budgets, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            month_spend = month_spends.get(business_key(source.get("seller_name"), source.get("country_code"), source.get("msku")))
            price = _dec((listing or {}).get("price"))
            ladder = {step: _dec((ladder_row or {}).get(f"margin_price_{step}")) for step in MARGIN_STEPS}
            margin = margin_band_rate(price, ladder) if ladder_row else None
            orders = _dec(source.get("orders")) or Decimal(0)
            clicks = _dec(source.get("clicks")) or Decimal(0)
            sales = _dec(source.get("sales")) or Decimal(0)
            source.update(aov=sales / orders if orders else None, cvr=orders / clicks if clicks else None,
                          margin_rate=margin, price_mapped=listing is not None,
                          margin_ladder_complete=bool(ladder_row and all(ladder.values())),
                          below_zero_margin_price=bool(price is not None and ladder.get(0) is not None and price < ladder[0]),
                          **benchmarks.get((source.get("object_type") or "", str(source.get("country_code") or "").upper()), {}),
                          **bid_protection_values(budget, month_spend))
            rule = calculate_bid_recommendation(source)
            bid_rows.append({**source, **rule, "listing_price": price, "batch_id": None,
                             "recommendation_key": _key(source.get("object_type"), *group_key, source.get("object_id"), source.get("object_text"), source.get("match_type")),
                             "priority_rank": 1 if rule["status"] in {"increase", "decrease"} else 9,
                             "reason_codes": json.dumps(rule["reason_codes"], ensure_ascii=False)})

        result = {"status": "dry_run_success" if dry_run else "success", "cutoff_date": str(cutoff), "mature_start": str(start), "mature_end": str(end), "source_days": len(set(days)), "bid_rows": len(bid_rows), "add_rows": len(add_rows), "negative_rows": len(negative_rows)}
        if dry_run:
            return result

        with conn.cursor() as cur:
            cur.execute("select get_lock(%s,0) acquired", (lock_name,))
            if not cur.fetchone()["acquired"]:
                raise RuntimeError("another recommendation build is running")
            cur.execute("""insert into dashboard_sp_recommendation_batch(task_name,rule_version,cutoff_date,mature_start,mature_end,status,dry_run,source_days,host_name,started_at)
                values(%s,%s,%s,%s,%s,'running',0,%s,%s,now())""", (TASK_NAME, RULE_VERSION, cutoff, start, end, len(set(days)), socket.gethostname()))
            batch_id = cur.lastrowid
        conn.commit()
        common_columns = ["batch_id", "recommendation_key", "profile_id", "seller_name", "country_code", "currency_code", "campaign_id", "campaign_name_current", "ad_group_id", "ad_group_name_current"]
        bid_columns = common_columns + ["targeting_type", "object_type", "object_id", "object_text", "match_type", "object_state_current", "msku", "asin", "associated_msku_count", "impressions", "clicks", "cost", "orders", "sales", "aov", "cvr", "current_bid", "listing_price", "margin_rate", "theoretical_cpc", "reference_cpc_20", "reference_cpc_333", "suggested_bid", "change_direction", "change_amount", "change_rate", "status", "priority_rank", "reason_codes"]
        term_columns = common_columns + ["target_id", "targeting_type", "match_type", "search_term", "target_text", "msku", "asin", "associated_msku_count", "protection_brand", "protection_category", "product_launch_date", "product_age_days", "impressions", "clicks", "cost", "orders", "sales", "acos", "suggestion_type", "suggestion_value", "status", "priority", "priority_rank", "reason_codes"]
        for row in (*bid_rows, *add_rows, *negative_rows):
            row["batch_id"] = batch_id
        _insert_many(conn, "dashboard_sp_bid_recommendation", bid_columns, bid_rows)
        _insert_many(conn, "dashboard_sp_add_term_recommendation", term_columns, add_rows)
        _insert_many(conn, "dashboard_sp_negative_term_recommendation", term_columns, negative_rows)
        result["governance_ad_groups"] = refresh_governance_snapshot(conn, batch_id, start, end)
        with conn.cursor() as cur:
            cur.execute("update dashboard_sp_recommendation_batch set status='success',bid_rows=%s,add_rows=%s,negative_rows=%s,quality_json=%s,finished_at=now() where batch_id=%s", (len(bid_rows), len(add_rows), len(negative_rows), json.dumps(result, ensure_ascii=False), batch_id))
        conn.commit()
        result["batch_id"] = batch_id
        return result
    except Exception as exc:
        conn.rollback()
        if batch_id:
            with conn.cursor() as cur:
                cur.execute("update dashboard_sp_recommendation_batch set status='failed',error_message=%s,finished_at=now() where batch_id=%s", (str(exc)[:4000], batch_id))
            conn.commit()
        raise
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("select release_lock(%s)", (lock_name,))
        except Exception:
            pass
        if owns_connection:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local SP advertising recommendations")
    parser.add_argument("--cutoff-date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cutoff = date.fromisoformat(args.cutoff_date) if args.cutoff_date else None
    if not args.dry_run:
        print(json.dumps(refresh_term_protection_context(), ensure_ascii=False, default=str))
    print(json.dumps(build_recommendations(cutoff, args.dry_run), ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
