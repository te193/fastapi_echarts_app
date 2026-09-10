"""Refresh local SP term-protection context from read-only business sources."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.services.sp_term_protection import build_protection_context_rows
from etl.dashboard_daily_update import connect_source
from etl.replenishment_update import apply_database_ini_env


SOURCE_QUERIES = {
    "listings": """
        select id,seller_name,seller_sku,asin,marketplace,seller_brand,
               small_1,small_2,small_3,small_4,small_5,
               open_date_display,on_sale_time,first_order_time,create_time
        from dwd_datasync.lx_sales_mws_listing
        where nullif(seller_name,'') is not null and nullif(seller_sku,'') is not null
    """,
    "store_brands": """
        select `店铺名` store_name,`品牌名` brand_name
        from opt_db.store_brand_relation
        where nullif(`店铺名`,'') is not null and nullif(`品牌名`,'') is not null
    """,
    "titles": """
        select seller_name,msku,leaf_category,category
        from opt_db.lyt_title_optimization_latest_detail
        where run_id=%s
    """,
}


def protection_context_ddl() -> str:
    return """
create table if not exists dashboard_sp_term_protection_current (
  seller_name varchar(255) collate utf8mb4_bin not null,
  country_code varchar(20) not null default '',
  msku varchar(255) collate utf8mb4_bin not null,
  asin varchar(50) null,
  product_brand varchar(255) null,
  brand_source varchar(100) null,
  store_brands_json json not null,
  leaf_categories_json json not null,
  launch_date date null,
  launch_date_source varchar(50) null,
  listing_source_updated_at datetime null,
  title_run_id bigint null,
  refreshed_at datetime not null default current_timestamp,
  primary key (seller_name,country_code,msku),
  key idx_protection_country_msku(country_code,msku),
  key idx_protection_msku(msku)
) engine=InnoDB default charset=utf8mb4;
""".strip()


def _target_connection():
    return pymysql.connect(
        host=os.environ["DASHBOARD_DB_HOST"],
        port=int(os.getenv("DASHBOARD_DB_PORT", "3306")),
        user=os.environ["DASHBOARD_DB_USER"],
        password=os.environ["DASHBOARD_DB_PASSWORD"],
        database=os.getenv("DASHBOARD_DB_NAME", "etl_datasync_test"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        read_timeout=300,
        write_timeout=300,
    )


def ensure_protection_context_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(protection_context_ddl())
        cursor.execute(
            "select column_name as column_name_value,collation_name as collation_name_value "
            "from information_schema.columns "
            "where table_schema=database() and table_name='dashboard_sp_term_protection_current' "
            "and column_name in ('seller_name','msku')"
        )
        collations = {
            row["column_name_value"]: row["collation_name_value"]
            for row in cursor.fetchall()
        }
        for column in ("seller_name", "msku"):
            if collations.get(column) != "utf8mb4_bin":
                cursor.execute(
                    f"alter table dashboard_sp_term_protection_current modify {column} "
                    "varchar(255) collate utf8mb4_bin not null"
                )
    connection.commit()


def fetch_source_context(connection) -> tuple[list[dict], list[dict], list[dict], Any]:
    with connection.cursor() as cursor:
        cursor.execute(SOURCE_QUERIES["listings"])
        listings = cursor.fetchall()
        cursor.execute(SOURCE_QUERIES["store_brands"])
        brands = cursor.fetchall()
        cursor.execute("select max(run_id) run_id from opt_db.lyt_title_optimization_latest_detail limit 1")
        run_rows = cursor.fetchall()
        title_run_id = (run_rows[0] if run_rows else {}).get("run_id")
        cursor.execute(SOURCE_QUERIES["titles"], (title_run_id,))
        titles = cursor.fetchall()
    return listings, titles, brands, title_run_id


def refresh_term_protection_context(target_connection=None, source_connection=None) -> dict[str, Any]:
    apply_database_ini_env(Path("config/database.ini"))
    target = target_connection or _target_connection()
    source = source_connection or connect_source()
    owns_target = target_connection is None
    owns_source = source_connection is None
    try:
        listings, titles, brands, title_run_id = fetch_source_context(source)
        rows = build_protection_context_rows(
            listings, titles, brands, title_run_id=title_run_id
        )
        ensure_protection_context_table(target)
        columns = (
            "seller_name", "country_code", "msku", "asin", "product_brand", "brand_source",
            "store_brands_json", "leaf_categories_json", "launch_date", "launch_date_source",
            "listing_source_updated_at", "title_run_id",
        )
        sql = (
            f"insert into dashboard_sp_term_protection_current ({','.join(columns)}) "
            f"values ({','.join(['%s'] * len(columns))})"
        )
        with target.cursor() as cursor:
            cursor.execute("delete from dashboard_sp_term_protection_current")
            for start in range(0, len(rows), 2000):
                values = []
                for row in rows[start:start + 2000]:
                    prepared = dict(row)
                    prepared["store_brands_json"] = json.dumps(row["store_brands"], ensure_ascii=False)
                    prepared["leaf_categories_json"] = json.dumps(row["leaf_categories"], ensure_ascii=False)
                    values.append([prepared.get(column) for column in columns])
                cursor.executemany(sql, values)
        target.commit()
        return {
            "status": "success",
            "rows": len(rows),
            "listing_rows": len(listings),
            "title_rows": len(titles),
            "store_brand_rows": len(brands),
            "title_run_id": title_run_id,
        }
    except Exception:
        target.rollback()
        raise
    finally:
        if owns_source:
            source.close()
        if owns_target:
            target.close()


def main() -> int:
    print(json.dumps(refresh_term_protection_context(), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
