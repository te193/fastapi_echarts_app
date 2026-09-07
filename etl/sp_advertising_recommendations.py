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
    mature_window,
)
from etl.replenishment_update import apply_database_ini_env


RULE_VERSION = "sp-recommendation-v2-negative-clicks-10"
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
    conn.commit()


def _key(*values: Any) -> str:
    return hashlib.sha256("\x1f".join("" if v is None else str(v) for v in values).encode("utf-8")).hexdigest()


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _group_products(conn) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""select profile_id,campaign_id,ad_group_id,count(distinct nullif(msku,'')) associated_msku_count,
            case when count(distinct nullif(msku,''))=1 then max(msku) end msku,
            case when count(distinct nullif(msku,''))=1 then max(asin) end asin
            from dashboard_sp_ad_group_msku_current group by profile_id,campaign_id,ad_group_id""")
        return {(r["profile_id"], r["campaign_id"], r["ad_group_id"]): r for r in cur.fetchall()}


def _latest_snapshot_rows(conn, table: str, date_column: str, cutoff: date) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
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
    for row in _latest_snapshot_rows(conn, "dashboard_ad_budget_snapshot", "biz_date", cutoff):
        budgets[business_key(row.get("seller_name_new"), row.get("country"), row.get("seller_sku_adj"))] = row
    return listings, ladders, budgets


def _lookup(mapping: dict, store: Any, country: Any, msku: Any) -> dict[str, Any] | None:
    target = business_key(store, country, msku)
    if target in mapping:
        return mapping[target]
    store_key, country_key, sku_key = target
    candidates = [v for (s, c, k), v in mapping.items() if s == store_key and k == sku_key and (c == country_key or not c or not country_key)]
    return candidates[0] if len(candidates) == 1 else None


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


def _existing_objects(conn) -> tuple[set[tuple[Any, Any, str]], set[tuple[Any, Any, str]]]:
    with conn.cursor() as cur:
        cur.execute("""select distinct profile_id,ad_group_id,keyword_text,object_state_current
            from dashboard_sp_keyword_daily where keyword_text is not null""")
        keywords = {(r["profile_id"], r["ad_group_id"], str(r["keyword_text"])) for r in cur.fetchall() if str(r.get("object_state_current") or "").lower() in {"enabled", "enable"}}
        cur.execute("select distinct profile_id,ad_group_id,asin,state_current from dashboard_sp_ad_group_msku_current where asin is not null")
        products = {(r["profile_id"], r["ad_group_id"], str(r["asin"]).upper()) for r in cur.fetchall() if str(r.get("state_current") or "").lower() in {"enabled", "enable"}}
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

        products = _group_products(conn)
        listings, ladders, budgets = _business_lookups(conn, cutoff)
        existing_keywords, existing_products = _existing_objects(conn)
        term_rows = _search_term_rows(conn, start, end)
        add_rows, negative_rows = [], []
        priority_rank = {"highest": 1, "high": 1, "medium": 2, "none": 9}
        for source in term_rows:
            group_key = (source.get("profile_id"), source.get("campaign_id"), source.get("ad_group_id"))
            product = products.get(group_key, {"associated_msku_count": 0, "msku": None, "asin": None})
            source.update(product)
            term = str(source.get("search_term") or "")
            source["existing_enabled"] = ((source.get("profile_id"), source.get("ad_group_id"), term) in existing_keywords or (source.get("profile_id"), source.get("ad_group_id"), term.upper()) in existing_products)
            budget = _lookup(budgets, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            source["protection_complete"] = budget is not None and bool(budget.get("max_brand_name"))
            brand = str((budget or {}).get("max_brand_name") or "").strip()
            source["is_brand_term"] = bool(brand and brand.casefold() in term.casefold())
            source["is_new_product_term"] = "新品" in str((budget or {}).get("product_type") or "")
            add_rule = calculate_add_recommendation(source)
            negative_rule = calculate_negative_recommendation(source)
            common = {**source, "batch_id": None, "recommendation_key": _key(*group_key, source.get("target_id"), term, source.get("match_type"))}
            for target, rule in ((add_rows, add_rule), (negative_rows, negative_rule)):
                target.append({**common, **rule, "priority_rank": priority_rank[rule["priority"]], "reason_codes": json.dumps(rule["reason_codes"], ensure_ascii=False), "suggestion_value": rule["suggestion_value"]})

        bid_rows = []
        for source in _bid_rows(conn, start, end):
            group_key = (source.get("profile_id"), source.get("campaign_id"), source.get("ad_group_id"))
            product = products.get(group_key, {"associated_msku_count": 0, "msku": None, "asin": None})
            source.update(product)
            listing = _lookup(listings, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            ladder_row = _lookup(ladders, source.get("seller_name"), source.get("country_code"), source.get("msku"))
            budget = _lookup(budgets, source.get("seller_name"), source.get("country_code"), source.get("msku"))
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
                          inventory_sufficient=bool((budget or {}).get("inventory_sufficient_flag")),
                          budget_sufficient=bool(budget and _dec(budget.get("monthly_ad_budget_original")) is not None and (_dec(budget.get("monthly_ad_budget_original")) or Decimal(0)) >= _dec(source.get("cost") or 0)))
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
        term_columns = common_columns + ["target_id", "targeting_type", "match_type", "search_term", "target_text", "msku", "asin", "associated_msku_count", "impressions", "clicks", "cost", "orders", "sales", "acos", "suggestion_type", "suggestion_value", "status", "priority", "priority_rank", "reason_codes"]
        for row in (*bid_rows, *add_rows, *negative_rows):
            row["batch_id"] = batch_id
        _insert_many(conn, "dashboard_sp_bid_recommendation", bid_columns, bid_rows)
        _insert_many(conn, "dashboard_sp_add_term_recommendation", term_columns, add_rows)
        _insert_many(conn, "dashboard_sp_negative_term_recommendation", term_columns, negative_rows)
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
    print(json.dumps(build_recommendations(cutoff, args.dry_run), ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
