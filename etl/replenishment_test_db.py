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


@dataclass(frozen=True)
class BaselineTable:
    table: str
    backup_table: str
    where_sql: str


@dataclass(frozen=True)
class PromotionTable:
    table: str
    date_column: str


COPY_TABLES = (
    CopyTable("dashboard_product_performance_daily", "dt_date >= %(product_start_date)s"),
    CopyTable("dashboard_inventory_daily_snapshot", "snapshot_date = %(snapshot_date)s"),
    CopyTable("dashboard_restock_daily_snapshot", "snapshot_date = %(snapshot_date)s"),
    CopyTable("dashboard_listing_price_daily_snapshot", "snapshot_date in (%(snapshot_date)s, %(biz_date)s)"),
    CopyTable("dashboard_limit_price_daily_snapshot", "snapshot_date in (%(snapshot_date)s, %(biz_date)s, %(previous_snapshot_date)s)"),
    CopyTable("dashboard_pur_plan_replenish_data", "cur_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"),
    CopyTable("dashboard_replenishment_country_metrics", "snapshot_date in (%(snapshot_date)s, %(previous_snapshot_date)s)"),
    CopyTable("pur_plan_prod_perf_salable_days_stat", "sta_dt in (%(biz_date)s, %(previous_biz_date)s)"),
    CopyTable(
        "dashboard_replenishment_history_daily_sync",
        "dt_date between %(history_start_date)s and %(history_end_date)s",
    ),
    CopyTable("dashboard_replenishment_self_asin_sync", "1 = 1"),
    CopyTable("dashboard_replenishment_supplier_moq_sync", "snapshot_date = %(snapshot_date)s"),
)

BASELINE_TABLES = (
    BaselineTable(
        "dashboard_pur_plan_replenish_data",
        "baseline_dashboard_pur_plan_replenish_data",
        "cur_date in (%(snapshot_date)s, %(previous_snapshot_date)s)",
    ),
    BaselineTable(
        "dashboard_replenishment_country_metrics",
        "baseline_dashboard_replenishment_country_metrics",
        "snapshot_date in (%(snapshot_date)s, %(previous_snapshot_date)s)",
    ),
)

PROMOTION_TABLES = (
    PromotionTable("dashboard_replenishment_supplier_moq_sync", "snapshot_date"),
    PromotionTable("dashboard_pur_plan_replenish_data", "cur_date"),
)


def build_promotion_sql(
    production_schema: str,
    test_schema: str,
    item: PromotionTable,
    columns: tuple[str, ...],
) -> tuple[str, str]:
    production_schema = clean_identifier(production_schema, "production schema")
    test_schema = clean_identifier(test_schema, "test schema")
    table = clean_identifier(item.table, "promotion table")
    date_column = clean_identifier(item.date_column, "promotion date column")
    column_sql = ", ".join(f"`{clean_identifier(column, 'promotion column')}`" for column in columns)
    delete_sql = (
        f"delete from `{production_schema}`.`{table}` "
        f"where `{date_column}` = %(snapshot_date)s"
    )
    insert_sql = (
        f"insert into `{production_schema}`.`{table}` ({column_sql}) "
        f"select {column_sql} from `{test_schema}`.`{table}` "
        f"where `{date_column}` = %(snapshot_date)s"
    )
    return delete_sql, insert_sql


def build_result_moq_update_sql(production_schema: str) -> str:
    production_schema = clean_identifier(production_schema, "production schema")
    calculated_qty = """
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then case when coalesce(r.max_cg_box_pcs, 0) > 0 then r.max_cg_box_pcs else 50 end
            else coalesce(r.replenish_qty, 0)
        end
    """.strip()
    calculated_box_qty = """
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then case when coalesce(r.max_cg_box_pcs, 0) > 0 then 1 else 0 end
            else coalesce(r.replenish_box_qty, 0)
        end
    """.strip()
    calculated_cost = f"""
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then ({calculated_qty})
                   * (coalesce(r.max_cg_price, 0) + coalesce(r.max_cg_transport_costs, 0))
            else coalesce(r.replenish_cost, 0)
        end
    """.strip()
    below_minimum = f"""
        ({calculated_qty}) > 0
        and m.supplier_moq > 0
        and ({calculated_qty}) < m.supplier_moq
    """.strip()
    return f"""
        update `{production_schema}`.`dashboard_pur_plan_replenish_data` r
        left join `{production_schema}`.`dashboard_replenishment_supplier_moq_sync` m
               on m.snapshot_date = r.cur_date
              and binary m.sku = binary r.max_sku
        set r.supplier_moq = m.supplier_moq,
            r.moq_status = case
                when ({calculated_qty}) <= 0 then 'not_applicable'
                when m.supplier_moq is null or m.supplier_moq <= 0 then 'unconfigured'
                when ({calculated_qty}) < m.supplier_moq then 'below_minimum'
                else 'met'
            end,
            r.calculated_replenish_qty = ({calculated_qty}),
            r.calculated_replenish_box_qty = ({calculated_box_qty}),
            r.calculated_replenish_cost = ({calculated_cost}),
            r.executable_replenish_qty = case when {below_minimum} then 0 else ({calculated_qty}) end,
            r.executable_replenish_box_qty = case when {below_minimum} then 0 else ({calculated_box_qty}) end,
            r.executable_replenish_cost = case when {below_minimum} then 0 else ({calculated_cost}) end,
            r.moq_shortfall_qty = case
                when {below_minimum} then greatest(m.supplier_moq - ({calculated_qty}), 0)
                else 0
            end
        where r.cur_date = %(snapshot_date)s
    """


def moq_invalid_condition(alias: str = "") -> str:
    prefix = f"{clean_identifier(alias, 'MOQ validation alias')}." if alias else ""
    return f"""
        {prefix}moq_status not in ('met', 'below_minimum', 'unconfigured', 'not_applicable')
        or ({prefix}calculated_replenish_qty <= 0 and {prefix}moq_status <> 'not_applicable')
        or ({prefix}calculated_replenish_qty > 0
            and ({prefix}supplier_moq is null or {prefix}supplier_moq <= 0)
            and {prefix}moq_status <> 'unconfigured')
        or ({prefix}calculated_replenish_qty > 0
            and {prefix}supplier_moq > 0
            and {prefix}calculated_replenish_qty < {prefix}supplier_moq
            and {prefix}moq_status <> 'below_minimum')
        or ({prefix}calculated_replenish_qty > 0
            and {prefix}supplier_moq > 0
            and {prefix}calculated_replenish_qty >= {prefix}supplier_moq
            and {prefix}moq_status <> 'met')
        or ({prefix}moq_status = 'below_minimum' and (
               coalesce({prefix}executable_replenish_qty, 0) <> 0
            or coalesce({prefix}executable_replenish_box_qty, 0) <> 0
            or coalesce({prefix}executable_replenish_cost, 0) <> 0
            or not ({prefix}moq_shortfall_qty <=>
                    ({prefix}supplier_moq - {prefix}calculated_replenish_qty))
        ))
        or ({prefix}moq_status <> 'below_minimum' and (
               not ({prefix}executable_replenish_qty <=> {prefix}calculated_replenish_qty)
            or {prefix}executable_replenish_box_qty is null
            or {prefix}executable_replenish_cost is null
            or coalesce({prefix}moq_shortfall_qty, 0) <> 0
        ))
    """.strip()


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
    history_year = biz_date.year - 1
    return {
        "snapshot_date": snapshot_date,
        "previous_snapshot_date": snapshot_date - timedelta(days=1),
        "biz_date": biz_date,
        "previous_biz_date": biz_date - timedelta(days=1),
        "product_start_date": biz_date - timedelta(days=179),
        "history_start_date": date(history_year, 1, 1) - timedelta(days=90),
        "history_end_date": date(history_year, 12, 31) + timedelta(days=90),
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


def copy_baseline_table(
    conn,
    production_schema: str,
    test_schema: str,
    item: BaselineTable,
    params: dict[str, date],
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            f"create table if not exists `{test_schema}`.`{item.backup_table}` "
            f"like `{production_schema}`.`{item.table}`"
        )
        cursor.execute(
            """
            select table_schema, table_name, column_name
            from information_schema.columns
            where (table_schema = %s and table_name = %s)
               or (table_schema = %s and table_name = %s)
            order by ordinal_position
            """,
            (production_schema, item.table, test_schema, item.backup_table),
        )
        rows = cursor.fetchall()
        source_columns = [
            row.get("column_name") or row.get("COLUMN_NAME")
            for row in rows
            if (row.get("table_schema") or row.get("TABLE_SCHEMA")) == production_schema
        ]
        backup_columns = {
            row.get("column_name") or row.get("COLUMN_NAME")
            for row in rows
            if (row.get("table_schema") or row.get("TABLE_SCHEMA")) == test_schema
        }
        columns = [column for column in source_columns if column in backup_columns]
        if not columns:
            raise RuntimeError(f"No common columns available for baseline table {item.table}")
        column_sql = ", ".join(f"`{clean_identifier(column, 'baseline column')}`" for column in columns)
        cursor.execute(
            f"insert ignore into `{test_schema}`.`{item.backup_table}` ({column_sql}) "
            f"select {column_sql} from `{production_schema}`.`{item.table}` where {item.where_sql}",
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
        for item in BASELINE_TABLES:
            copied = copy_baseline_table(conn, production_schema, test_schema, item, params)
            conn.commit()
            print(f"[success] backed up {item.table} -> {item.backup_table}: rows={copied}")
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


def build_verification_queries(production_schema: str, test_schema: str) -> dict[str, str]:
    return {
        "test_summary": f"""
            select count(*) as rows_count,
                   coalesce(sum(calculated_replenish_qty), 0) as calculated_replenish_qty,
                   coalesce(sum(executable_replenish_qty), 0) as executable_replenish_qty,
                   coalesce(sum(executable_replenish_cost), 0) as executable_replenish_cost,
                   sum(case when moq_status = 'below_minimum' then 1 else 0 end) as moq_warning_rows
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
        """,
        "moq_status_summary": f"""
            select moq_status,
                   count(*) as msku_count,
                   coalesce(sum(calculated_replenish_qty), 0) as calculated_replenish_qty,
                   coalesce(sum(executable_replenish_qty), 0) as executable_replenish_qty,
                   coalesce(sum(executable_replenish_cost), 0) as executable_replenish_cost
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
            group by moq_status
            order by moq_status
        """,
        "moq_gate_zero_check": f"""
            select count(*) as bad_rows
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
              and moq_status = 'below_minimum'
              and (
                    coalesce(executable_replenish_qty, 0) <> 0
                 or coalesce(executable_replenish_box_qty, 0) <> 0
                 or coalesce(executable_replenish_cost, 0) <> 0
                 or coalesce(calculated_replenish_qty, 0) >= coalesce(supplier_moq, 0)
              )
        """,
        "moq_equal_release_check": f"""
            select count(*) as equal_rows,
                   sum(case when moq_status = 'met'
                              and executable_replenish_qty = calculated_replenish_qty
                            then 1 else 0 end) as released_rows
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
              and calculated_replenish_qty = supplier_moq
              and supplier_moq > 0
        """,
        "lead_time_summary": f"""
            select count(*) as rows_count,
                   sum(effective_purchase_lead_days > 0) as configured_rows,
                   sum(lead_time_stockout_flag = 1) as stockout_rows,
                   coalesce(sum(lead_time_lost_sales_qty), 0) as lost_sales_qty,
                   coalesce(sum(calculated_replenish_qty), 0) as calculated_replenish_qty,
                   coalesce(sum(executable_replenish_qty), 0) as executable_replenish_qty
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
        """,
        "lead_time_formula_check": f"""
            select sum(case
                       when arrival_inventory_qty < -0.0001
                         or (arrival_inventory_support_days >= 0
                             and lead_adjusted_replenish_need_qty > 0
                             and abs(arrival_inventory_qty
                                     + lead_adjusted_replenish_need_qty
                                     - 120 * daily_avg_sales) > 0.02)
                         or (arrival_inventory_support_days < 0
                             and abs(lead_adjusted_replenish_need_qty
                                     - 120 * daily_avg_sales) > 0.02)
                         or (arrival_inventory_support_days < 0
                             and abs(lead_time_lost_sales_qty
                                     - (-arrival_inventory_support_days * daily_avg_sales)) > 0.02)
                       then 1 else 0
                   end) as bad_rows
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
              and daily_avg_sales > 0
              and asin_merge_flag = 0
        """,
        "lead_time_asin_inheritance_check": f"""
            select sum(case
                       when abs(coalesce(r.effective_purchase_lead_days, 0)
                                - coalesce(a.group_effective_purchase_lead_days, 0)) > 0.001
                         or abs(coalesce(r.arrival_inventory_qty, 0)
                                - coalesce(a.group_arrival_inventory_qty, 0)) > 0.02
                         or abs(coalesce(r.lead_adjusted_replenish_need_qty, 0)
                                - coalesce(a.group_lead_adjusted_replenish_need_qty, 0)) > 0.02
                       then 1 else 0
                   end) as bad_rows
            from `{test_schema}`.`dashboard_pur_plan_replenish_data` r
            inner join `{test_schema}`.`dashboard_replenishment_work_asin_merge_assignments_v3` a
                    on r.country_category = a.country_category
                   and r.seller_name_new = a.seller_name_new
                   and r.seller_sku_adj = a.seller_sku_adj
            where r.cur_date = %(snapshot_date)s
              and a.asin_merge_target_flag = 1
        """,
    }


def common_promotion_columns(conn, production_schema: str, test_schema: str, table: str) -> tuple[str, ...]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select table_schema, column_name, extra
            from information_schema.columns
            where table_schema in (%s, %s)
              and table_name = %s
            order by ordinal_position
            """,
            (production_schema, test_schema, table),
        )
        rows = cursor.fetchall()
    by_schema: dict[str, list[str]] = {production_schema: [], test_schema: []}
    auto_columns: set[str] = set()
    for row in rows:
        schema_name = row.get("table_schema") or row.get("TABLE_SCHEMA")
        column_name = row.get("column_name") or row.get("COLUMN_NAME")
        extra = str(row.get("extra") or row.get("EXTRA") or "").lower()
        if schema_name in by_schema and column_name:
            by_schema[schema_name].append(column_name)
        if "auto_increment" in extra:
            auto_columns.add(column_name)
    test_columns = set(by_schema[test_schema])
    return tuple(
        column
        for column in by_schema[production_schema]
        if column in test_columns and column not in auto_columns
    )


def validate_promotion_source(conn, test_schema: str, snapshot_date: date) -> None:
    params = {"snapshot_date": snapshot_date}
    checks = {
        "replenishment_rows": f"""
            select count(*) as value
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
        """,
        "supplier_moq_rows": f"""
            select count(*) as value
            from `{test_schema}`.`dashboard_replenishment_supplier_moq_sync`
            where snapshot_date = %(snapshot_date)s
        """,
        "missing_moq_status": f"""
            select count(*) as value
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s and moq_status is null
        """,
        "invalid_moq_gate": f"""
            select count(*) as value
            from `{test_schema}`.`dashboard_pur_plan_replenish_data`
            where cur_date = %(snapshot_date)s
              and ({moq_invalid_condition()})
        """,
    }
    with conn.cursor() as cursor:
        results: dict[str, int] = {}
        for name, sql in checks.items():
            cursor.execute(sql, params)
            row = cursor.fetchone() or {}
            results[name] = int(row.get("value") or 0)
        if results["replenishment_rows"] <= 0:
            raise RuntimeError("Test replenishment snapshot is empty; refusing production promotion")
        if results["supplier_moq_rows"] <= 0:
            raise RuntimeError("Test supplier MOQ snapshot is empty; refusing production promotion")
        if results["missing_moq_status"] or results["invalid_moq_gate"]:
            raise RuntimeError(f"Test MOQ validation failed: {results}")


def promote_test_database(
    production_schema: str = PRODUCTION_SCHEMA,
    test_schema: str = TEST_SCHEMA,
    snapshot_date: date | None = None,
) -> None:
    production_schema, test_schema = target_schemas(production_schema, test_schema)
    conn = connect_without_database()
    try:
        selected_snapshot = snapshot_date or default_snapshot_date(conn, production_schema)
        validate_promotion_source(conn, test_schema, selected_snapshot)
        ensure_tables(
            conn,
            SchemaConfig(
                target_schema=production_schema,
                etl_source_schema=os.getenv("DASHBOARD_ETL_SOURCE_SCHEMA", "etl_datasync"),
                dwd_source_schema=os.getenv("DASHBOARD_DWD_SOURCE_SCHEMA", "dwd_datasync"),
                pricing_source_schema=os.getenv("DASHBOARD_PRICING_SOURCE_SCHEMA", "temporary_dwd"),
            ),
        )
        params = {"snapshot_date": selected_snapshot}
        conn.begin()
        with conn.cursor() as cursor:
            for item in PROMOTION_TABLES:
                if item.table == "dashboard_pur_plan_replenish_data":
                    cursor.execute(build_result_moq_update_sql(production_schema), params)
                    cursor.execute(
                        f"""
                        select count(*) as rows_count,
                               sum(case when moq_status is not null then 1 else 0 end) as populated_rows,
                               sum(case when {moq_invalid_condition()}
                                        then 1 else 0 end) as invalid_rows
                        from `{production_schema}`.`dashboard_pur_plan_replenish_data`
                        where cur_date = %(snapshot_date)s
                        """,
                        params,
                    )
                    result = cursor.fetchone() or {}
                    rows_count = int(result.get("rows_count") or 0)
                    populated = int(result.get("populated_rows") or 0)
                    invalid_rows = int(result.get("invalid_rows") or 0)
                    if rows_count <= 0 or populated != rows_count or invalid_rows:
                        raise RuntimeError(
                            f"MOQ result promotion mismatch: rows={rows_count}, "
                            f"populated={populated}, invalid={invalid_rows}"
                        )
                    print(f"[verified] promote MOQ result fields only: rows={populated}")
                    continue
                columns = common_promotion_columns(conn, production_schema, test_schema, item.table)
                if not columns or item.date_column not in columns:
                    raise RuntimeError(f"No safe common columns for promotion table {item.table}")
                delete_sql, insert_sql = build_promotion_sql(
                    production_schema,
                    test_schema,
                    item,
                    columns,
                )
                cursor.execute(delete_sql, params)
                cursor.execute(insert_sql, params)
                copied = max(cursor.rowcount, 0)
                cursor.execute(
                    f"select count(*) as rows_count from `{test_schema}`.`{item.table}` "
                    f"where `{item.date_column}` = %(snapshot_date)s",
                    params,
                )
                expected = int((cursor.fetchone() or {}).get("rows_count") or 0)
                if copied != expected or expected <= 0:
                    raise RuntimeError(
                        f"Promotion row mismatch for {item.table}: copied={copied}, expected={expected}"
                    )
                print(f"[verified] promote {item.table}: rows={copied}")
        conn.commit()
        print(
            f"[success] promoted replenishment snapshot transactionally: "
            f"{test_schema} -> {production_schema} snapshot_date={selected_snapshot}"
        )
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
        queries.update(build_verification_queries(production_schema, test_schema))
        params = {"snapshot_date": selected_snapshot}
        with conn.cursor() as cursor:
            for name, sql in queries.items():
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                print(f"[{name}]")
                for row in rows:
                    print(row)
                if name in {
                    "followed_zero_check",
                    "moq_gate_zero_check",
                    "lead_time_formula_check",
                    "lead_time_asin_inheritance_check",
                }:
                    bad_rows = int((rows[0] if rows else {}).get("bad_rows") or 0)
                    if bad_rows:
                        raise RuntimeError(f"Verification {name} found {bad_rows} invalid rows")
                if name == "moq_equal_release_check" and rows:
                    equal_rows = int(rows[0].get("equal_rows") or 0)
                    released_rows = int(rows[0].get("released_rows") or 0)
                    if equal_rows != released_rows:
                        raise RuntimeError(
                            f"MOQ equality release mismatch: equal={equal_rows}, released={released_rows}"
                        )
        print(f"[success] replenishment test database verified: {test_schema} snapshot_date={selected_snapshot}")
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and seed the isolated replenishment test database.")
    parser.add_argument("--production-schema", default=PRODUCTION_SCHEMA)
    parser.add_argument("--test-schema", default=TEST_SCHEMA)
    parser.add_argument("--snapshot-date", help="Snapshot date to copy, YYYY-MM-DD. Default: latest replenishment date.")
    parser.add_argument("--verify-only", action="store_true", help="Verify test replenishment results without copying data.")
    parser.add_argument("--promote", action="store_true", help="Transactionally promote verified test outputs to production.")
    return parser.parse_args()


def main() -> None:
    apply_database_ini_env()
    args = parse_args()
    selected_snapshot = date.fromisoformat(args.snapshot_date) if args.snapshot_date else None
    if args.promote:
        promote_test_database(
            production_schema=args.production_schema,
            test_schema=args.test_schema,
            snapshot_date=selected_snapshot,
        )
    elif args.verify_only:
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
