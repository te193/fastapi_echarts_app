from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date, timedelta

import pymysql

from etl.dashboard_daily_update import clean_identifier, connect_with_retry
from etl.replenishment_update import (
    SchemaConfig,
    apply_database_ini_env,
    ensure_tables,
)


PRODUCTION_SCHEMA = "etl_datasync_test"
TEST_SCHEMA = "etl_datasync_replenishment_test"


@dataclass(frozen=True)
class CopyTable:
    table: str
    where_sql: str


COPY_TABLES = (
    CopyTable("dashboard_product_performance_daily", "dt_date >= %(product_start_date)s"),
    CopyTable("dashboard_inventory_daily_snapshot", "snapshot_date = %(snapshot_date)s"),
    CopyTable("dashboard_restock_daily_snapshot", "snapshot_date = %(snapshot_date)s"),
    CopyTable("dashboard_listing_price_daily_snapshot", "snapshot_date in (%(snapshot_date)s, %(biz_date)s)"),
    CopyTable("dashboard_limit_price_daily_snapshot", "snapshot_date in (%(snapshot_date)s, %(biz_date)s, %(previous_snapshot_date)s)"),
    CopyTable("dashboard_pur_plan_replenish_data", "cur_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"),
    CopyTable("dashboard_replenishment_country_metrics", "snapshot_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"),
    CopyTable("pur_plan_prod_perf_salable_days_stat", "sta_dt in (%(biz_date)s, %(previous_biz_date)s)"),
)


def connect_without_database():
    return connect_with_retry(
        "target-server",
        host=os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1")),
        port=int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306"))),
        user=os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", "")),
        password=os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        charset=os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=20,
        read_timeout=3600,
        write_timeout=3600,
    )


def target_schemas(production_schema: str, test_schema: str) -> tuple[str, str]:
    production = clean_identifier(production_schema, PRODUCTION_SCHEMA)
    target = clean_identifier(test_schema, TEST_SCHEMA)
    if production == target:
        raise SystemExit("Refusing to copy replenishment test data into the production schema")
    return production, target


def default_snapshot_date(conn, production_schema: str) -> date:
    with conn.cursor() as cursor:
        cursor.execute(f"select max(cur_date) as cur_date from `{production_schema}`.`dashboard_pur_plan_replenish_data`")
        row = cursor.fetchone() or {}
    snapshot_date = row.get("cur_date")
    if not isinstance(snapshot_date, date):
        raise RuntimeError(f"No replenishment snapshot found in {production_schema}.dashboard_pur_plan_replenish_data")
    return snapshot_date


def build_params(snapshot_date: date) -> dict[str, date]:
    biz_date = snapshot_date - timedelta(days=1)
    return {
        "snapshot_date": snapshot_date,
        "previous_snapshot_date": snapshot_date - timedelta(days=1),
        "biz_date": biz_date,
        "previous_biz_date": biz_date - timedelta(days=1),
        "product_start_date": biz_date - timedelta(days=179),
    }


def common_columns(conn, production_schema: str, test_schema: str, table: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select p.column_name
            from information_schema.columns p
            inner join information_schema.columns t
                    on t.table_schema = %(test_schema)s
                   and t.table_name = p.table_name
                   and t.column_name = p.column_name
            where p.table_schema = %(production_schema)s
              and p.table_name = %(table)s
            order by p.ordinal_position
            """,
            {"production_schema": production_schema, "test_schema": test_schema, "table": table},
        )
        rows = cursor.fetchall()
    columns = [next(iter(row.values())) if isinstance(row, dict) else row[0] for row in rows]
    if not columns:
        raise RuntimeError(f"No common columns found for {production_schema}.{table} -> {test_schema}.{table}")
    return columns


def ensure_copy_table(conn, production_schema: str, test_schema: str, table: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select count(*) as table_count
            from information_schema.tables
            where table_schema = %(schema)s
              and table_name = %(table)s
            """,
            {"schema": test_schema, "table": table},
        )
        row = cursor.fetchone() or {}
        if int(row.get("table_count") or 0) == 0:
            cursor.execute(f"create table `{test_schema}`.`{table}` like `{production_schema}`.`{table}`")


def copy_table(conn, production_schema: str, test_schema: str, item: CopyTable, params: dict[str, date]) -> int:
    ensure_copy_table(conn, production_schema, test_schema, item.table)
    columns = common_columns(conn, production_schema, test_schema, item.table)
    column_sql = ", ".join(f"`{column}`" for column in columns)
    with conn.cursor() as cursor:
        cursor.execute(f"delete from `{test_schema}`.`{item.table}` where {item.where_sql}", params)
        cursor.execute(
            f"""
            insert into `{test_schema}`.`{item.table}` ({column_sql})
            select {column_sql}
            from `{production_schema}`.`{item.table}`
            where {item.where_sql}
            """,
            params,
        )
        return max(cursor.rowcount, 0)


def initialize_test_database(
    production_schema: str = PRODUCTION_SCHEMA,
    test_schema: str = TEST_SCHEMA,
    snapshot_date: date | None = None,
) -> None:
    production_schema, test_schema = target_schemas(production_schema, test_schema)
    conn = connect_without_database()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"create schema if not exists `{test_schema}` default character set utf8mb4")
        conn.commit()

        schemas = SchemaConfig(
            target_schema=test_schema,
            etl_source_schema=os.getenv("DASHBOARD_ETL_SOURCE_SCHEMA", "etl_datasync"),
            dwd_source_schema=os.getenv("DASHBOARD_DWD_SOURCE_SCHEMA", "dwd_datasync"),
            pricing_source_schema=os.getenv("DASHBOARD_PRICING_SOURCE_SCHEMA", "temporary_dwd"),
        )
        ensure_tables(conn, schemas)

        selected_snapshot = snapshot_date or default_snapshot_date(conn, production_schema)
        params = build_params(selected_snapshot)
        for item in COPY_TABLES:
            copied = copy_table(conn, production_schema, test_schema, item, params)
            conn.commit()
            print(f"[success] copied {item.table}: rows={copied}")
        print(f"[success] replenishment test database ready: {test_schema} snapshot_date={selected_snapshot}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_test_database(
    production_schema: str = PRODUCTION_SCHEMA,
    test_schema: str = TEST_SCHEMA,
    snapshot_date: date | None = None,
) -> None:
    production_schema, test_schema = target_schemas(production_schema, test_schema)
    conn = connect_without_database()
    try:
        selected_snapshot = snapshot_date or default_snapshot_date(conn, production_schema)
        queries = {
            "production_summary": f"""
                select count(*) as rows_count,
                       coalesce(sum(replenish_qty), 0) as replenish_qty,
                       coalesce(sum(replenish_cost), 0) as replenish_cost
                from `{production_schema}`.`dashboard_pur_plan_replenish_data`
                where cur_date = %(snapshot_date)s
            """,
            "test_summary": f"""
                select count(*) as rows_count,
                       coalesce(sum(replenish_qty), 0) as replenish_qty,
                       coalesce(sum(replenish_cost), 0) as replenish_cost,
                       sum(case when followed_flag = 1 then 1 else 0 end) as followed_rows
                from `{test_schema}`.`dashboard_pur_plan_replenish_data`
                where cur_date = %(snapshot_date)s
            """,
            "followed_zero_check": f"""
                select count(*) as bad_rows
                from `{test_schema}`.`dashboard_pur_plan_replenish_data`
                where cur_date = %(snapshot_date)s
                  and followed_flag = 1
                  and (
                      coalesce(replenish_qty, 0) <> 0
                   or coalesce(replenish_box_qty, 0) <> 0
                   or coalesce(replenish_cost, 0) <> 0
                   or replenish_block_reason <> '被跟卖点不补货'
                  )
            """,
            "followed_examples": f"""
                select country_category,
                       seller_name_new,
                       seller_sku_adj,
                       fllow_flag,
                       followed_flag,
                       followed_by_count,
                       left(followed_by_links, 160) as followed_by_links,
                       replenish_qty,
                       replenish_box_qty,
                       replenish_cost,
                       replenish_block_reason
                from `{test_schema}`.`dashboard_pur_plan_replenish_data`
                where cur_date = %(snapshot_date)s
                  and followed_flag = 1
                order by followed_by_count desc, seller_sku_adj
                limit 5
            """,
        }
        params = {"snapshot_date": selected_snapshot}
        with conn.cursor() as cursor:
            for name, sql in queries.items():
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                print(f"[{name}]")
                for row in rows:
                    print(row)
                if name == "followed_zero_check":
                    bad_rows = int((rows[0] if rows else {}).get("bad_rows") or 0)
                    if bad_rows:
                        raise RuntimeError(f"Found {bad_rows} followed origin rows that were not blocked correctly")
        print(f"[success] replenishment test database verified: {test_schema} snapshot_date={selected_snapshot}")
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and seed the isolated replenishment test database.")
    parser.add_argument("--production-schema", default=PRODUCTION_SCHEMA)
    parser.add_argument("--test-schema", default=TEST_SCHEMA)
    parser.add_argument("--snapshot-date", help="Snapshot date to copy, YYYY-MM-DD. Default: latest replenishment date.")
    parser.add_argument("--verify-only", action="store_true", help="Verify test replenishment results without copying data.")
    return parser.parse_args()


def main() -> None:
    apply_database_ini_env()
    args = parse_args()
    selected_snapshot = date.fromisoformat(args.snapshot_date) if args.snapshot_date else None
    if args.verify_only:
        verify_test_database(
            production_schema=args.production_schema,
            test_schema=args.test_schema,
            snapshot_date=selected_snapshot,
        )
    else:
        initialize_test_database(
            production_schema=args.production_schema,
            test_schema=args.test_schema,
            snapshot_date=selected_snapshot,
        )


if __name__ == "__main__":
    main()
