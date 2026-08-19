from datetime import date

from etl.sales_role_snapshot_update import (
    CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL,
    DEFAULT_PERIODS,
    INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL,
    SALES_ROLE_RULE_VERSION,
    parse_periods,
    period_params,
)


def test_sales_role_snapshot_defaults_include_three_days():
    assert DEFAULT_PERIODS == (3, 7, 14, 30, 90)


def test_sales_role_snapshot_table_has_business_comments():
    assert "dashboard_sales_role_period_snapshot" in CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL
    assert "engine=InnoDB default charset=utf8mb4 comment='" in CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL
    for column in ("seller_sku_adj", "country_category", "sales_role_label", "sales_role_rule_version"):
        line = next(line for line in CREATE_SALES_ROLE_PERIOD_SNAPSHOT_SQL.splitlines() if column in line)
        assert " comment '" in line


def test_sales_role_snapshot_uses_full_daily_pool_and_target_grain():
    assert "from etl_datasync.dashboard_product_performance_daily p" in INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL
    assert "filter_flag" not in INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL
    assert "p.seller_sku_adj,\n            p.seller_name_new,\n            p.country_category" in INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL
    assert "p.dt_date between %(period_start)s and %(period_end)s" in INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL


def test_sales_role_snapshot_deduplicates_shared_country_inventory_at_period_end():
    sql = INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL

    assert (
        "max(case when p.dt_date = %(period_end)s "
        "then p.afn_fulfillable_quantity else 0 end) as ending_inventory_qty"
    ) in sql
    assert (
        "sum(case when p.dt_date = %(period_end)s "
        "then p.afn_fulfillable_quantity else 0 end) as ending_inventory_qty"
    ) not in sql


def test_sales_role_snapshot_contains_label_threshold_rules():
    sql = INSERT_SALES_ROLE_PERIOD_SNAPSHOT_SQL

    assert "agg.daily_sales > 5 and agg.order_gross_margin > 0.15" in sql
    assert "agg.daily_sales between 1 and 5 and agg.order_gross_margin > 0.25" in sql
    assert "agg.daily_sales > 5 and agg.order_gross_margin between 0.05 and 0.15" in sql
    assert "agg.daily_sales between 1 and 5 and agg.order_gross_margin between 0.10 and 0.25" in sql
    assert "agg.daily_sales between 1 and 5 and agg.order_gross_margin >= 0.05 and agg.order_gross_margin < 0.10" in sql
    assert "agg.daily_sales < 1 and agg.order_gross_margin > 0.05" in sql
    assert "'瘦狗产品'" in sql
    assert "'问题产品'" in sql


def test_period_params_defaults_match_snapshot_contract():
    params = period_params(date(2026, 7, 7), date(2026, 7, 6), 30)

    assert params["period_code"] == "30d"
    assert params["period_start"] == date(2026, 6, 7)
    assert params["period_end"] == date(2026, 7, 6)
    assert params["sales_role_rule_version"] == SALES_ROLE_RULE_VERSION


def test_parse_periods_accepts_days_and_d_suffix():
    assert parse_periods("7d,14,30d,30d") == (7, 14, 30)
