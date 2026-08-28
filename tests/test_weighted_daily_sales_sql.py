import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.skip(reason="补货加权日销 SQL 已暂时下线，恢复功能后再启用对应校验。")


SQL_PATH = Path(__file__).resolve().parents[1] / "data" / "补货页面加权日销计算.sql"

FINAL_OUTPUT_COLUMNS = [
    "biz_date",
    "country_category",
    "country",
    "seller_name_new",
    "seller_sku_adj",
    "max_brand_name",
    "receiving_cnt",
    "product_type",
    "sales_3",
    "r_3d_salable_days",
    "sales_7",
    "r_7d_salable_days",
    "sales_14",
    "r_14d_salable_days",
    "sales_30",
    "r_30d_salable_days",
    "daily_avg_sales",
    "listing_price",
    "currency_code",
    "exchange_rate_cny",
    "listing_price_cny",
    "available_total",
    "stock_up_num",
    "local_quantity",
    "total_budget_inventory",
    "month_max_inventory_qty",
    "total_weighted_daily_sales",
    "sales_share",
    "total_inventory_allocated_qty",
    "site_total_budget_cny",
    "monthly_forecast_qty",
    "monthly_allocated_qty",
    "monthly_ad_budget_original",
    "monthly_ad_budget_cny",
    "weekly_forecast_qty",
    "weekly_allocated_qty",
    "weekly_ad_budget_original",
    "weekly_ad_budget_cny",
    "total_budget_pool_cny",
    "inventory_sufficient_flag",
    "weekly_inventory_sufficient_flag",
]

BUSINESS_KEY_COLUMNS = {
    "country_category",
    "country",
    "seller_name_new",
    "seller_sku_adj",
}


def _sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _final_select(sql: str) -> str:
    match = re.search(
        r"\nselect\s+cast\(@run_date\s+as\s+date\).*?\nfrom\s+[a-z_]+\s+as\s+[a-z]+",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, "未找到最终加权日销 select"
    return match.group(0).lower()


def _normalized_sql() -> str:
    return re.sub(r"\s+", " ", _sql_text().lower()).strip()


def _final_output_columns(sql: str) -> list[str]:
    select_sql = _final_select(sql)
    body = select_sql.split("\nselect\n", 1)[1].rsplit("\nfrom ", 1)[0]
    expressions = []
    start = 0
    depth = 0
    for index, char in enumerate(body):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            expressions.append(body[start:index].strip())
            start = index + 1
    expressions.append(body[start:].strip())

    columns = []
    for expression in expressions:
        alias_match = re.search(r"\bas\s+([a-z_][a-z0-9_]*)\s*$", expression)
        columns.append(alias_match.group(1) if alias_match else expression.rsplit(".", 1)[-1])
    return columns


def test_final_select_keeps_period_inputs_but_only_exposes_weighted_daily_sales():
    final_select = _final_select(_sql_text())

    for alias in (
        "daily_sales_3d",
        "daily_sales_7d",
        "daily_sales_14d",
        "daily_sales_30d",
    ):
        assert f" as {alias}" not in final_select

    for column in (
        "sales_3",
        "r_3d_salable_days",
        "sales_7",
        "r_7d_salable_days",
        "sales_14",
        "r_14d_salable_days",
        "sales_30",
        "r_30d_salable_days",
        "daily_avg_sales",
    ):
        assert column in final_select


def test_sql_keywords_and_functions_are_lowercase():
    sql = re.sub(
        r"--.*?$|/\*.*?\*/|'(?:''|[^'])*'",
        " ",
        _sql_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    sql_words = {
        "add", "alter", "and", "as", "binary", "by", "case", "cast",
        "char", "charset", "coalesce", "count", "create", "date", "date_add",
        "date_format", "date_sub", "day", "decimal", "default", "desc",
        "drop", "else", "end", "engine", "exists", "force", "from",
        "greatest", "group", "if", "in", "index", "interval", "is",
        "join", "key", "leading", "least", "left", "length", "like",
        "locate", "max", "min", "not",
        "null", "nullif", "on", "or", "order", "over", "partition",
        "primary", "round", "row_number", "select", "set", "sum", "table",
        "substring_index", "temporary", "then", "trim", "upper", "when",
        "where", "with",
    }
    uppercase_tokens = [
        token
        for token in re.findall(r"\b[A-Za-z_]+\b", sql)
        if token.lower() in sql_words and token != token.lower()
    ]

    assert uppercase_tokens == []


def test_query_uses_reusable_upsert_with_explicit_aligned_columns():
    sql = _normalized_sql()

    assert "delete from" not in sql
    assert "create table" not in sql
    insert_match = re.search(
        r"insert into dws_datasync\.dws_monthly_ad_budget_detail\s*\((.*?)\)\s*with",
        sql,
    )
    assert insert_match is not None
    insert_columns = [
        column.strip()
        for column in insert_match.group(1).split(",")
    ]
    assert insert_columns == FINAL_OUTPUT_COLUMNS

    assert "from final_result as new" in sql
    assert "on duplicate key update" in sql
    assert "values(" not in sql
    update_sql = sql.split("on duplicate key update", 1)[1]
    update_pairs = re.findall(
        r"\b([a-z_][a-z0-9_]*)\s*=\s*new\.([a-z_][a-z0-9_]*)",
        update_sql,
    )
    expected_update_columns = [
        column for column in FINAL_OUTPUT_COLUMNS
        if column not in BUSINESS_KEY_COLUMNS
    ]
    assert update_pairs == [
        (column, column) for column in expected_update_columns
    ]

    outer_select = re.search(
        r"\) select (.*?) from final_result as new on duplicate key update",
        sql,
    )
    assert outer_select is not None
    assert re.findall(
        r"\bnew\.([a-z_][a-z0-9_]*)",
        outer_select.group(1),
    ) == FINAL_OUTPUT_COLUMNS

    assert "create temporary table dws_datasync.tmp_replenishment_previous_budget_state" in sql
    assert "from dws_datasync.dws_monthly_ad_budget_detail as p" in sql
    assert "p.biz_date = @previous_budget_date" in sql
    assert "@previous_state_has_month_max" in sql
    assert "p.month_max_inventory_qty" in sql
    assert "greatest(p.total_budget_inventory, 0) as month_max_inventory_qty" in sql
    assert sql.count(
        "dws_datasync.tmp_replenishment_previous_budget_state as p"
    ) == 1
    assert "create temporary table dws_datasync.tmp_replenishment_previous_missing_site" in sql
    assert sql.count(
        "dws_datasync.tmp_replenishment_weighted_sales_product_30d as p"
    ) == 1


def test_inventory_pool_uses_replenishment_support_inventory_components():
    sql = _normalized_sql()

    assert "create temporary table dws_datasync.tmp_replenishment_budget_inventory_latest" in sql
    assert "create temporary table dws_datasync.tmp_replenishment_budget_fba_latest" in sql
    assert "create temporary table dws_datasync.tmp_replenishment_budget_restock_latest" in sql
    assert "drop temporary table dws_datasync.tmp_replenishment_budget_fba_latest" in sql
    assert "drop temporary table dws_datasync.tmp_replenishment_budget_restock_latest" in sql
    assert "product_keys as" not in sql
    assert "from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail as f where" in sql
    assert "from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking as r where" in sql
    assert sql.count("cast(f.seller_name_new as char(64)) as seller_name_new") == 1
    assert sql.count("cast(r.seller_name_new as char(64)) as seller_name_new") == 1
    assert "inventory_keys as" not in sql
    assert "etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail" in sql
    assert "etl_datasync.etl_dispose_lx_replenishment_suggest_restocking" in sql
    assert "coalesce(f.available_total, 0) + coalesce(f.stock_up_num, 0) + coalesce(r.local_quantity, 0) as total_budget_inventory" in sql


def test_budget_allocation_only_includes_approved_country_sites():
    sql = _normalized_sql()

    assert "p.country in ('德国', '法国', '意大利', '西班牙', '荷兰', '美国', '英国')" in sql
    assert "w.country in ('德国', '法国', '意大利', '西班牙', '荷兰', '美国', '英国')" in sql


def test_final_query_exposes_inventory_constrained_monthly_and_weekly_budgets():
    final_select = _final_select(_sql_text())

    for column in (
        "total_budget_inventory",
        "total_weighted_daily_sales",
        "sales_share",
        "monthly_forecast_qty",
        "monthly_allocated_qty",
        "weekly_forecast_qty",
        "weekly_allocated_qty",
        "monthly_ad_budget_cny",
        "weekly_ad_budget_cny",
        "total_budget_pool_cny",
        "inventory_sufficient_flag",
    ):
        assert column in final_select


def test_final_query_hides_internal_inventory_snapshots_and_budget_status():
    final_select = _final_select(_sql_text())

    assert "\n    a.inventory_snapshot_date," not in final_select
    assert "\n    a.restock_snapshot_date," not in final_select
    assert "end as budget_data_status" not in final_select


def test_final_query_exposes_stateful_budget_contract_in_order():
    assert _final_output_columns(_sql_text()) == FINAL_OUTPUT_COLUMNS


def test_refresh_calendar_uses_execution_date_instead_of_lagging_source_date():
    sql = _normalized_sql()
    final_select = _final_select(_sql_text())

    assert "set @run_date = current_date()" in sql
    assert "cast(@run_date as date) as biz_date" in final_select
    assert "date_format(@run_date, '%y-%m')" in sql
    assert "weekday(@run_date) = 0" in sql


def test_monthly_and_weekly_modules_keep_previous_values_between_refreshes():
    sql = _normalized_sql()

    assert "monthly_budget_module as" in sql
    assert "weekly_budget_module as" in sql
    assert "p.previous_biz_date is null or date_format(p.previous_biz_date, '%y-%m') <> date_format(@run_date, '%y-%m')" in sql
    assert "else p.previous_monthly_allocated_qty" in sql
    assert "when m.previous_biz_date is null or weekday(@run_date) = 0" in sql
    assert "else m.previous_weekly_allocated_qty" in sql


def test_inventory_budget_module_only_adds_positive_growth_to_the_month_pool():
    sql = _normalized_sql()

    assert "inventory_budget_module as" in sql
    assert re.search(
        r"greatest\(\s*i\.total_budget_inventory\s*-\s*"
        r"i\.previous_month_max_inventory_qty,\s*0\s*\)",
        sql,
    )
    assert "i.previous_total_inventory_allocated_qty + i.inventory_growth_qty * i.sales_share" in sql
    assert "i.previous_site_total_budget_cny + i.inventory_growth_qty * i.sales_share * i.listing_price_cny * 0.05" in sql
    assert "else i.previous_month_max_inventory_qty" in sql


def test_high_water_comes_from_persisted_state_and_advances_without_sales_or_price():
    sql = _normalized_sql()
    growth_cte = sql.split("inventory_growth_base as (", 1)[1].split(
        "), inventory_budget_module as (", 1
    )[0]

    assert "max(coalesce(p.month_max_inventory_qty, 0)) over" in sql
    assert "sum(coalesce(p.total_inventory_allocated_qty, 0)) over" not in sql
    assert "total_weighted_daily_sales" not in growth_cte
    assert "missing_price_site_count" not in growth_cte


def test_zero_share_growth_preserves_previous_site_budget_before_multiplication():
    sql = _normalized_sql()

    zero_share = sql.index("and i.sales_share <= 0")
    multiplication = sql.index(
        "i.previous_site_total_budget_cny + i.inventory_growth_qty * i.sales_share"
    )
    assert zero_share < multiplication


def test_same_day_rerun_preserves_null_and_rounded_budget_pool_state():
    sql = _normalized_sql()

    assert "p.site_total_budget_cny as previous_site_total_budget_cny" in sql
    assert "coalesce(p.site_total_budget_cny, 0)" not in sql
    assert "p.total_budget_pool_cny" in sql
    assert "as previous_total_budget_pool_cny" in sql
    assert "round(i.site_total_budget_cny_raw, 2) as site_total_budget_cny" in sql
    assert "as site_budget_increment_cny" in sql
    assert "a.previous_total_budget_pool_cny" in sql
    assert "a.total_budget_increment_cny_sum" in sql


def test_new_site_in_existing_month_can_receive_inventory_growth_budget():
    sql = _normalized_sql()

    assert (
        "when i.previous_biz_date is null then case "
        "when i.daily_avg_sales <= 0 then 0 "
        "when i.missing_price_site_count > 0 then null "
        "else i.inventory_growth_qty * i.sales_share "
        "* i.listing_price_cny * 0.05 end"
    ) in sql
    new_site_increment = sql.index(
        "when i.previous_biz_date is null then round(i.site_total_budget_cny_raw, 2)"
    )
    prior_null_guard = sql.index(
        "when i.previous_site_total_budget_cny is null "
        "or i.site_total_budget_cny_raw is null then null"
    )
    assert new_site_increment < prior_null_guard


def test_allocation_formulas_use_30_and_7_day_inventory_caps():
    sql = _normalized_sql()

    assert "greatest(e.daily_avg_sales, 0) * 30 as monthly_forecast_qty" in sql
    assert "e.daily_avg_sales * least( 30, greatest(e.total_budget_inventory, 0) / e.total_weighted_daily_sales ) else 0 end as monthly_allocated_qty" in sql
    assert "greatest(e.daily_avg_sales, 0) * 7 as weekly_forecast_qty" in sql
    assert "e.daily_avg_sales * least( 7, greatest(e.total_budget_inventory, 0) / e.total_weighted_daily_sales ) else 0 end as weekly_allocated_qty" in sql
    assert "e.daily_avg_sales / e.total_weighted_daily_sales" in sql


def test_missing_inventory_snapshots_still_protect_allocations_and_budget_pool():
    sql = _normalized_sql()

    assert sql.count("e.inventory_snapshot_date is not null and e.restock_snapshot_date is not null") == 2
    assert sql.count(
        "when i.inventory_snapshot_date is null or i.restock_snapshot_date is null then 0"
    ) == 2
    assert "i.inventory_growth_qty * i.sales_share" in sql


def test_weekly_inventory_sufficient_flag_uses_seven_day_forecast():
    final_select = re.sub(r"\s+", " ", _final_select(_sql_text())).strip()

    assert (
        "when a.inventory_snapshot_date is null or a.restock_snapshot_date is null then 0 "
        "when a.total_weighted_daily_sales <= 0 then 1 "
        "when a.total_budget_inventory >= a.total_weighted_daily_sales * 7 then 1 "
        "else 0 end as weekly_inventory_sufficient_flag"
    ) in final_select


def test_total_budget_pool_sums_cumulative_site_budgets_after_growth_allocation():
    sql = _normalized_sql()

    assert "as total_inventory_allocated_qty" in sql
    assert "i.inventory_growth_qty * i.sales_share * i.listing_price_cny * 0.05" in sql
    assert "as site_total_budget_cny_raw" in sql
    assert "sum(i.site_budget_increment_cny) over" in sql
    assert "as total_budget_increment_cny_sum" in sql
    assert "a.previous_total_budget_pool_cny + coalesce(a.total_budget_increment_cny_sum, 0)" in sql
    assert "a.weighted_price_cny_numerator / a.total_weighted_daily_sales" not in sql


def test_new_month_zero_sales_returns_zero_before_price_checks():
    sql = _normalized_sql()

    assert (
        "then case when i.daily_avg_sales <= 0 then 0 "
        "when i.missing_price_site_count > 0 then null "
        "else i.inventory_growth_qty * i.sales_share "
        "* i.listing_price_cny * 0.05 end "
    ) in sql
    assert "else i.previous_site_total_budget_cny end as site_total_budget_cny_raw" in sql


def test_total_budget_pool_uses_stored_precision_and_complete_inventory_partition():
    sql = _normalized_sql()
    site_budget_cte = sql.split("inventory_budget_module as (", 1)[1].split(
        "), site_budget_storage_metrics as (", 1
    )[0]

    assert "round(" not in site_budget_cte
    assert (
        "sum(i.site_budget_increment_cny) over ( partition by "
        "i.country_category, i.seller_name_new, i.seller_sku_adj )"
    ) in sql
    assert "round(i.site_total_budget_cny_raw, 2) as site_total_budget_cny" in sql
