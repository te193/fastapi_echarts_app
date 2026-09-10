"""Build local SP advertising daily facts from read-only Lingxing source tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pymysql
from pymysql.cursors import DictCursor, SSDictCursor

from etl.replenishment_update import apply_database_ini_env


TASK_NAME = "sp_advertising_update"
DEFAULT_DAYS = 30
WINDOWS = (1, 7, 14, 30)
COUNT_METRICS = ("orders", "units", "same_orders", "same_units")
MONEY_METRICS = ("sales", "same_sales")
BASE_METRICS = ("impressions", "clicks", "cost")
FACTS = {
    "campaign": ("dashboard_sp_campaign_daily", "lx_advertising_sp_campaign_reports", "campaign_id"),
    "ad_group": ("dashboard_sp_ad_group_daily", "lx_advertising_sp_ad_group_reports", "ad_group_id"),
    "product_ad": ("dashboard_sp_product_ad_daily", "lx_advertising_sp_product_ad_reports", "ad_id"),
    "keyword": ("dashboard_sp_keyword_daily", "lx_advertising_sp_keyword_reports", "keyword_id"),
    "search_term": ("dashboard_sp_search_term_daily", "lx_advertising_sp_query_word_reports", "target_id"),
}

SITE_CURRENCY = {
    "AE": "AED", "AU": "AUD", "BE": "EUR", "CA": "CAD", "DE": "EUR",
    "ES": "EUR", "FR": "EUR", "IN": "INR", "IT": "EUR", "JP": "JPY",
    "MX": "MXN", "NL": "EUR", "PL": "PLN", "SA": "SAR", "SE": "SEK",
    "SG": "SGD", "TR": "TRY", "UK": "GBP", "US": "USD",
}


def date_range(start: str | None, end: str | None, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    end_day = date.fromisoformat(end) if end else today - timedelta(days=1)
    start_day = date.fromisoformat(start) if start else end_day - timedelta(days=DEFAULT_DAYS - 1)
    if start_day > end_day:
        raise ValueError("start date must not be after end date")
    if end_day >= today and not end:
        raise ValueError("default range must contain complete days only")
    return start_day, end_day


def _dt_rank(row: dict[str, Any]) -> tuple:
    return (row.get("update_time") or row.get("last_updated_date") or row.get("create_time") or datetime.min,
            int(row.get("id") or 0))


class Dimensions:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.maps: dict[str, dict[Any, dict[str, Any]]] = {}
        self.products_by_group: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        self.targets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)

    def add(self, kind: str, row: dict[str, Any]) -> None:
        self._rows[kind].append(row)

    def finish(self) -> None:
        specs = {
            "account": lambda r: str(r.get("profile_id") or ""),
            "campaign": lambda r: (r.get("profile_id"), r.get("campaign_id")),
            "ad_group": lambda r: (r.get("profile_id"), r.get("campaign_id"), r.get("ad_group_id")),
            "keyword": lambda r: (r.get("profile_id"), r.get("campaign_id"), r.get("ad_group_id"), r.get("keyword_id")),
            "product": lambda r: (r.get("profile_id"), r.get("campaign_id"), r.get("ad_group_id"), r.get("ad_id")),
            "portfolio": lambda r: (r.get("profile_id"), r.get("portfolio_id")),
        }
        for kind, key_fn in specs.items():
            result: dict[Any, dict[str, Any]] = {}
            for row in self._rows.get(kind, []):
                key = key_fn(row)
                if key not in result or _dt_rank(row) > _dt_rank(result[key]):
                    result[key] = row
            self.maps[kind] = result
        latest_products: dict[tuple, dict[str, Any]] = {}
        for row in self._rows.get("product", []):
            key = (row.get("profile_id"), row.get("campaign_id"), row.get("ad_group_id"), row.get("ad_id"))
            if key not in latest_products or _dt_rank(row) > _dt_rank(latest_products[key]):
                latest_products[key] = row
        for row in latest_products.values():
            self.products_by_group[(row.get("profile_id"), row.get("campaign_id"), row.get("ad_group_id"))].append(row)
        latest_targets: dict[tuple, dict[str, Any]] = {}
        for row in self._rows.get("target", []):
            key = (row.get("profile_id"), row.get("campaign_id"), row.get("ad_group_id"),
                   row.get("target_id"), row.get("expression_ordinal"), row.get("expression_item_type"))
            if key not in latest_targets or _dt_rank(row) > _dt_rank(latest_targets[key]):
                latest_targets[key] = row
        for row in latest_targets.values():
            self.targets[(row.get("profile_id"), row.get("campaign_id"), row.get("ad_group_id"), row.get("target_id"))].append(row)

    def get(self, kind: str, key: Any) -> dict[str, Any]:
        return self.maps.get(kind, {}).get(key, {})


def _exact_json(items: Iterable[dict[str, Any]]) -> str | None:
    values = [{k: r.get(k) for k in ("expression_ordinal", "expression_item_type", "expression_item_value",
              "resolved_expression_item_type", "resolved_expression_item_value")} for r in items]
    return json.dumps(values, ensure_ascii=False, default=str, separators=(",", ":")) if values else None


def _key_text(value: Any) -> str:
    return "" if value is None else str(value)


def _site_from_seller_name(seller_name: Any) -> str | None:
    """Infer a marketplace only from a recognized final store-name suffix."""
    if not seller_name:
        return None
    suffix = str(seller_name).strip().rsplit("-", 1)[-1].upper()
    return suffix if suffix in SITE_CURRENCY else None


def prepare_fact(kind: str, source: dict[str, Any], dims: Dimensions) -> dict[str, Any]:
    row = dict(source)
    profile = row.get("profile_id")
    campaign_id = row.get("campaign_id")
    ad_group_id = row.get("ad_group_id")
    campaign = dims.get("campaign", (profile, campaign_id))
    ad_group = dims.get("ad_group", (profile, campaign_id, ad_group_id))
    account = dims.get("account", str(profile or ""))
    keyword = dims.get("keyword", (profile, campaign_id, ad_group_id, row.get("keyword_id")))
    product = dims.get("product", (profile, campaign_id, ad_group_id, row.get("ad_id")))
    portfolio = dims.get("portfolio", (profile, campaign.get("portfolio_id")))
    products = dims.products_by_group.get((profile, campaign_id, ad_group_id), [])
    targets = dims.targets.get((profile, campaign_id, ad_group_id, row.get("target_id")), [])
    seller_name = row.get("seller_name") or account.get("name")
    country_code = account.get("country_code") or _site_from_seller_name(seller_name)
    currency_code = account.get("currency_code") or SITE_CURRENCY.get(country_code)
    required = {
        "campaign": (profile, campaign_id),
        "ad_group": (profile, campaign_id, ad_group_id),
        "product_ad": (profile, campaign_id, ad_group_id, row.get("ad_id")),
        "keyword": (profile, campaign_id, ad_group_id, row.get("keyword_id")),
        "search_term": (profile, campaign_id, ad_group_id, row.get("target_id"), row.get("query")),
    }[kind]
    missing_key = any(v is None or v == "" for v in required)
    identity = [kind, row.get("report_date"), *required]
    if kind in ("keyword", "search_term"):
        identity.extend((row.get("match_type"), row.get("keyword_text"), row.get("query"), row.get("target_text")))
    if missing_key:
        identity.append(row.get("id"))
    row_key = hashlib.sha256("\x1f".join(_key_text(v) for v in identity).encode("utf-8")).hexdigest()
    result: dict[str, Any] = {
        "row_key": row_key, "report_date": row.get("report_date"),
        "source_dwd_id": row.get("_source_dwd_id", row.get("id")),
        "source_ods_id": row.get("_source_ods_id") or row.get("relate_id"), "profile_id": profile,
        "sid": account.get("sid") or row.get("sid"), "seller_name": seller_name,
        "country_code": country_code, "currency_code": currency_code,
        "campaign_id": campaign_id, "campaign_name_current": campaign.get("name") or row.get("name"),
        "portfolio_id": campaign.get("portfolio_id"), "portfolio_name_current": portfolio.get("name"),
        "targeting_type": campaign.get("targeting_type") or row.get("targeting_type"),
        "campaign_state_current": campaign.get("state") or (row.get("state") if kind == "campaign" else None),
        "daily_budget_current": campaign.get("daily_budget") or row.get("daily_budget"),
        "bidding_strategy_current": campaign.get("bidding_strategy") or row.get("bidding"),
        "ad_group_id": ad_group_id, "ad_group_name_current": ad_group.get("name") or (row.get("name") if kind == "ad_group" else None),
        "ad_group_state_current": ad_group.get("state"), "default_bid_current": ad_group.get("default_bid") or row.get("default_bid"),
        "ad_id": row.get("ad_id"), "msku": row.get("sku") or product.get("sku"), "asin": row.get("asin") or product.get("asin"),
        "keyword_id": row.get("keyword_id"), "keyword_text": row.get("keyword_text") or keyword.get("keyword_text"),
        "match_type": row.get("match_type") or keyword.get("match_type"), "keyword_bid_current": keyword.get("bid") or row.get("bid"),
        "target_id": row.get("target_id"), "target_text": row.get("target_text"), "search_term": row.get("query"),
        "target_expressions": _exact_json(targets),
        "object_state_current": (targets[0].get("state") if targets else keyword.get("state") or product.get("state")),
        "associated_msku_count": len({p.get("sku") for p in products if p.get("sku")}),
        "missing_business_key": int(missing_key), "missing_account_dimension": int(not bool(account)),
        "missing_campaign_dimension": int(bool(campaign_id) and not bool(campaign)),
        "missing_ad_group_dimension": int(bool(ad_group_id) and not bool(ad_group)),
        "source_create_time": row.get("create_time"),
    }
    for name in BASE_METRICS:
        result[name] = row.get(name)
    for prefix in (*COUNT_METRICS, *MONEY_METRICS):
        result[prefix] = row.get(prefix)
        for days in WINDOWS:
            result[f"{prefix}_{days}d"] = row.get(f"{prefix}_{days}d")
    return result


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _ratio(numerator: Any, denominator: Any) -> Decimal | None:
    n, d = _decimal(numerator), _decimal(denominator)
    return None if n is None or d in (None, 0) else n / d


def calculate_rates(row: dict[str, Any]) -> dict[str, Decimal | None]:
    rates = {"ctr": _ratio(row.get("clicks"), row.get("impressions")), "cpc": _ratio(row.get("cost"), row.get("clicks"))}
    for days in WINDOWS:
        rates[f"cvr_{days}d"] = _ratio(row.get(f"orders_{days}d"), row.get("clicks"))
        rates[f"acos_{days}d"] = _ratio(row.get("cost"), row.get(f"sales_{days}d"))
        rates[f"roas_{days}d"] = _ratio(row.get(f"sales_{days}d"), row.get("cost"))
    return rates


DIM_COLUMNS = [
    "row_key", "report_date", "source_dwd_id", "source_ods_id", "profile_id", "sid", "seller_name",
    "country_code", "currency_code", "campaign_id", "campaign_name_current", "portfolio_id", "portfolio_name_current",
    "targeting_type", "campaign_state_current", "daily_budget_current", "bidding_strategy_current", "ad_group_id",
    "ad_group_name_current", "ad_group_state_current", "default_bid_current", "ad_id", "msku", "asin", "keyword_id",
    "keyword_text", "match_type", "keyword_bid_current", "target_id", "target_text", "search_term", "target_expressions",
    "object_state_current", "associated_msku_count", "missing_business_key", "missing_account_dimension",
    "missing_campaign_dimension", "missing_ad_group_dimension", "source_create_time"
]
METRIC_COLUMNS = list(BASE_METRICS)
for _prefix in (*COUNT_METRICS, *MONEY_METRICS):
    METRIC_COLUMNS.extend([_prefix, *(f"{_prefix}_{d}d" for d in WINDOWS)])
ALL_COLUMNS = DIM_COLUMNS + METRIC_COLUMNS


def _ddl(table: str) -> str:
    count_cols = ["impressions bigint null", "clicks bigint null"]
    count_cols += [f"{p}{suffix} bigint null" for p in COUNT_METRICS for suffix in ("", "_1d", "_7d", "_14d", "_30d")]
    money_cols = ["cost decimal(20,4) null"]
    money_cols += [f"{p}{suffix} decimal(20,4) null" for p in MONEY_METRICS for suffix in ("", "_1d", "_7d", "_14d", "_30d")]
    return f"""create table if not exists {table} (
      row_key char(64) not null, report_date date not null, source_dwd_id bigint null, source_ods_id bigint null,
      profile_id bigint null, sid bigint null, seller_name varchar(255) null, country_code varchar(20) null,
      currency_code varchar(20) null, campaign_id bigint null, campaign_name_current varchar(255) null,
      portfolio_id bigint null, portfolio_name_current varchar(255) null, targeting_type varchar(50) null,
      campaign_state_current varchar(50) null, daily_budget_current decimal(20,4) null,
      bidding_strategy_current varchar(100) null, ad_group_id bigint null, ad_group_name_current varchar(255) null,
      ad_group_state_current varchar(50) null, default_bid_current decimal(20,4) null, ad_id bigint null,
      msku varchar(100) null, asin varchar(50) null, keyword_id bigint null, keyword_text varchar(500) null,
      match_type varchar(100) null, keyword_bid_current decimal(20,4) null, target_id bigint null,
      target_text varchar(500) null, search_term varchar(500) null, target_expressions json null,
      object_state_current varchar(50) null, associated_msku_count int not null default 0,
      missing_business_key tinyint not null default 0, missing_account_dimension tinyint not null default 0,
      missing_campaign_dimension tinyint not null default 0, missing_ad_group_dimension tinyint not null default 0,
      source_create_time datetime null, {', '.join(count_cols + money_cols)}, batch_id bigint not null,
      created_at datetime not null default current_timestamp, updated_at datetime not null default current_timestamp on update current_timestamp,
      primary key (row_key), key idx_date_profile (report_date, profile_id), key idx_profile_date (profile_id, report_date),
      key idx_date_store (report_date, seller_name),
      key idx_campaign (campaign_id, report_date), key idx_ad_group (ad_group_id, report_date),
      key idx_msku (msku, report_date), key idx_keyword (keyword_id, report_date), key idx_target (target_id, report_date)
    ) engine=InnoDB default charset=utf8mb4"""


def connect_target(autocommit: bool = False):
    return pymysql.connect(host=os.environ["DASHBOARD_DB_HOST"], port=int(os.getenv("DASHBOARD_DB_PORT", "3306")),
        user=os.environ["DASHBOARD_DB_USER"], password=os.environ["DASHBOARD_DB_PASSWORD"],
        database=os.getenv("DASHBOARD_DB_NAME", "etl_datasync_test"), charset="utf8mb4", cursorclass=DictCursor,
        autocommit=autocommit, read_timeout=300, write_timeout=300)


def connect_source(stream: bool = False):
    return pymysql.connect(host=os.environ["DASHBOARD_SOURCE_DB_HOST"], port=int(os.getenv("DASHBOARD_SOURCE_DB_PORT", "3306")),
        user=os.environ["DASHBOARD_SOURCE_DB_USER"], password=os.environ["DASHBOARD_SOURCE_DB_PASSWORD"],
        charset="utf8mb4", cursorclass=SSDictCursor if stream else DictCursor, autocommit=True, read_timeout=600)


def ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""create table if not exists dashboard_sp_etl_batch (
          batch_id bigint not null auto_increment primary key, task_name varchar(100) not null, range_start date not null,
          range_end date not null, status varchar(30) not null, dry_run tinyint not null default 0,
          source_rows bigint not null default 0, result_rows bigint not null default 0, quality_json json null,
          error_message text null, host_name varchar(255) null, started_at datetime not null, finished_at datetime null,
          key idx_status_time(status, started_at)) engine=InnoDB default charset=utf8mb4""")
        cur.execute("""create table if not exists dashboard_sp_ad_group_msku_current (
          profile_id bigint not null, campaign_id bigint not null, ad_group_id bigint not null, ad_id bigint not null,
          msku varchar(100) null, asin varchar(50) null, state_current varchar(50) null, serving_status_current varchar(100) null,
          source_updated_at datetime null, batch_id bigint not null, primary key(profile_id,campaign_id,ad_group_id,ad_id),
          key idx_group(profile_id,campaign_id,ad_group_id), key idx_msku(msku)) engine=InnoDB default charset=utf8mb4""")
        for table, _, _ in FACTS.values():
            cur.execute(_ddl(table))
            cur.execute(f"create table if not exists {table}_stage like {table}")
            for source_table in (table, f"{table}_stage"):
                cur.execute(
                    "select is_nullable as nullable_flag from information_schema.columns "
                    "where table_schema=database() and table_name=%s and column_name='source_dwd_id'",
                    (source_table,),
                )
                source_column = cur.fetchone()
                if source_column and source_column["nullable_flag"] == "NO":
                    cur.execute(f"alter table {source_table} modify column source_dwd_id bigint null")
            cur.execute(
                "select count(*) n from information_schema.statistics "
                "where table_schema=database() and table_name=%s and index_name='idx_profile_date'",
                (table,),
            )
            if not cur.fetchone()["n"]:
                cur.execute(f"alter table {table} add key idx_profile_date (profile_id, report_date)")
    conn.commit()


def load_dimensions(conn) -> Dimensions:
    dims = Dimensions()
    queries = {
        "account": "select * from dwd_datasync.lx_advertising_account_list",
        "campaign": "select * from dwd_datasync.lx_advertising_sp_campaigns",
        "ad_group": "select * from dwd_datasync.lx_advertising_sp_ad_groups",
        "keyword": "select * from dwd_datasync.lx_advertising_sp_keywords",
        "product": "select * from dwd_datasync.lx_advertising_sp_product_ads where coalesce(delete_flag,0)=0",
        "target": "select * from dwd_datasync.lx_advertising_sp_targets",
        "portfolio": "select * from dwd_datasync.lx_advertising_portfolios",
    }
    with conn.cursor() as cur:
        for kind, sql in queries.items():
            cur.execute(sql)
            while True:
                rows = cur.fetchmany(5000)
                if not rows:
                    break
                for row in rows:
                    dims.add(kind, row)
    dims.finish()
    return dims


def _source_sql(kind: str, table: str) -> str:
    return (
        f"select o.*,null as _source_dwd_id,o.id as _source_ods_id "
        f"from ods_datasync.{table} o "
        "where o.report_date between %s and %s and coalesce(o.delete_flag,0)=0 "
        "order by o.id"
    )


def _insert_rows(conn, table: str, rows: list[dict[str, Any]], batch_id: int) -> None:
    if not rows:
        return
    cols = ALL_COLUMNS + ["batch_id"]
    sql = f"insert into {table}_stage ({','.join(cols)}) values ({','.join(['%s']*len(cols))}) on duplicate key update " + \
          ",".join(f"{c}=values({c})" for c in cols[1:])
    values = [[row.get(c) for c in ALL_COLUMNS] + [batch_id] for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, values)
    conn.commit()


def quality_for(conn, table: str, batch_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(f"""select count(*) rows_loaded, coalesce(sum(missing_business_key),0) missing_business_key,
            coalesce(sum(missing_account_dimension),0) missing_account_dimension,
            coalesce(sum(missing_campaign_dimension),0) missing_campaign_dimension,
            coalesce(sum(missing_ad_group_dimension),0) missing_ad_group_dimension,
            coalesce(sum(impressions),0) impressions,coalesce(sum(clicks),0) clicks,coalesce(sum(cost),0) cost
            from {table}_stage where batch_id=%s""", (batch_id,))
        return cur.fetchone()


def run(start: date, end: date, dry_run: bool = False) -> dict[str, Any]:
    apply_database_ini_env(Path("config/database.ini"))
    target = connect_target(False)
    source = None
    batch_id = None
    lock_name = f"{os.getenv('DASHBOARD_DB_NAME','etl_datasync_test')}.{TASK_NAME}"
    try:
        ensure_tables(target)
        with target.cursor() as cur:
            cur.execute("select get_lock(%s,0) acquired", (lock_name,))
            if not cur.fetchone()["acquired"]:
                raise RuntimeError("another SP advertising update is already running")
            cur.execute("insert into dashboard_sp_etl_batch(task_name,range_start,range_end,status,dry_run,host_name,started_at) values(%s,%s,%s,'running',%s,%s,now())",
                        (TASK_NAME, start, end, int(dry_run), socket.gethostname()))
            batch_id = cur.lastrowid
        target.commit()
        source = connect_source(True)
        dims = load_dimensions(source)
        source_rows = result_rows = 0
        quality: dict[str, Any] = {}
        for kind, (table, source_table, _) in FACTS.items():
            with target.cursor() as cur:
                cur.execute(f"delete from {table}_stage where batch_id=%s", (batch_id,))
            target.commit()
            buffer: list[dict[str, Any]] = []
            with source.cursor() as cur:
                cur.execute(_source_sql(kind, source_table), (start.isoformat(), end.isoformat()))
                while True:
                    rows = cur.fetchmany(2000)
                    if not rows:
                        break
                    source_rows += len(rows)
                    buffer.extend(prepare_fact(kind, row, dims) for row in rows)
                    if len(buffer) >= 2000:
                        _insert_rows(target, table, buffer, batch_id)
                        buffer.clear()
            _insert_rows(target, table, buffer, batch_id)
            q = quality_for(target, table, batch_id)
            quality[kind] = q
            result_rows += int(q["rows_loaded"])
        if not dry_run:
            target.begin()
            with target.cursor() as cur:
                for _, (table, _, _) in FACTS.items():
                    cur.execute(f"delete from {table} where report_date between %s and %s", (start, end))
                    cur.execute(f"insert into {table} select * from {table}_stage where batch_id=%s", (batch_id,))
                cur.execute("delete from dashboard_sp_ad_group_msku_current")
                product_rows = [r for rows in dims.products_by_group.values() for r in rows]
                cur.executemany("""insert into dashboard_sp_ad_group_msku_current(profile_id,campaign_id,ad_group_id,ad_id,msku,asin,state_current,serving_status_current,source_updated_at,batch_id)
                  values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [(r.get("profile_id"),r.get("campaign_id"),r.get("ad_group_id"),r.get("ad_id"),r.get("sku"),r.get("asin"),r.get("state"),r.get("serving_status"),r.get("update_time") or r.get("last_updated_date"),batch_id) for r in product_rows])
            target.commit()
        with target.cursor() as cur:
            cur.execute("update dashboard_sp_etl_batch set status=%s,source_rows=%s,result_rows=%s,quality_json=%s,finished_at=now() where batch_id=%s",
                        ("dry_run_success" if dry_run else "success", source_rows, result_rows, json.dumps(quality, ensure_ascii=False, default=str), batch_id))
        target.commit()
        return {"batch_id": batch_id, "range": [str(start), str(end)], "source_rows": source_rows, "result_rows": result_rows, "quality": quality, "dry_run": dry_run}
    except Exception as exc:
        target.rollback()
        if batch_id:
            with target.cursor() as cur:
                cur.execute("update dashboard_sp_etl_batch set status='failed',error_message=%s,finished_at=now() where batch_id=%s", (str(exc)[:4000], batch_id))
            target.commit()
        raise
    finally:
        if source:
            source.close()
        try:
            with target.cursor() as cur:
                cur.execute("select release_lock(%s)", (lock_name,))
        except Exception:
            pass
        target.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load SP advertising daily facts into local MySQL")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    start, end = date_range(args.start, args.end)
    print(json.dumps(run(start, end, args.dry_run), ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
