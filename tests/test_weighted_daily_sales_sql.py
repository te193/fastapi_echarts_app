import re
from pathlib import Path


SQL_PATH = Path(__file__).resolve().parents[1] / "data" / "补货页面加权日销计算.sql"


def _sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _final_select(sql: str) -> str:
    match = re.search(
        r"\nselect\s+cast\(@biz_date\s+as\s+date\).*?\nfrom\s+[a-z_]+\s+as\s+[a-z]+",
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


def test_query_is_read_only_and_does_not_use_result_table():
    sql = _normalized_sql()

    assert "insert into" not in sql
    assert "dws_monthly_ad_budget_detail" not in sql


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


def test_final_query_exposes_exact_40_column_contract_in_order():
    assert _final_output_columns(_sql_text()) == [
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
    assert "greatest(a.total_budget_inventory, 0) * a.sales_share" in sql
    assert "or a.inventory_snapshot_date is null or a.restock_snapshot_date is null then null" in sql


def test_weekly_inventory_sufficient_flag_uses_seven_day_forecast():
    final_select = re.sub(r"\s+", " ", _final_select(_sql_text())).strip()

    assert (
        "when a.inventory_snapshot_date is null or a.restock_snapshot_date is null then 0 "
        "when a.total_weighted_daily_sales <= 0 then 1 "
        "when a.total_budget_inventory >= a.total_weighted_daily_sales * 7 then 1 "
        "else 0 end as weekly_inventory_sufficient_flag"
    ) in final_select


def test_total_budget_pool_sums_site_budgets_after_inventory_allocation():
    sql = _normalized_sql()

    assert "as total_inventory_allocated_qty" in sql
    assert "i.total_inventory_allocated_qty * i.listing_price_cny * 0.05" in sql
    assert "as site_total_budget_cny" in sql
    assert "sum(s.site_total_budget_cny) over" in sql
    assert "as total_budget_pool_cny_sum" in sql
    assert "round(a.total_budget_pool_cny_sum, 2)" in sql
    assert "a.weighted_price_cny_numerator / a.total_weighted_daily_sales" not in sql


def test_site_total_budget_returns_zero_for_zero_sales_before_price_checks():
    sql = _normalized_sql()

    assert (
        "case when i.daily_avg_sales <= 0 then 0 "
        "when i.listing_price_cny is null then null "
        "else i.total_inventory_allocated_qty * i.listing_price_cny * 0.05 "
        "end as site_total_budget_cny"
    ) in sql


def test_total_budget_pool_uses_full_precision_and_complete_inventory_partition():
    sql = _normalized_sql()
    site_budget_cte = sql.split("site_budget_metrics as (", 1)[1].split(
        "), budget_pool_metrics as (", 1
    )[0]

    assert "round(" not in site_budget_cte
    assert (
        "sum(s.site_total_budget_cny) over ( partition by "
        "s.country_category, s.seller_name_new, s.seller_sku_adj )"
    ) in sql
