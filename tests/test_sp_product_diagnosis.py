from datetime import date
from decimal import Decimal

import pytest

from app.services.sp_product_diagnosis_data import (
    ProductDiagnosisFilters,
    SUGGESTION_ACTION_STATUSES,
    _where,
    calculate_diagnosis_rates,
    product_key,
)
from etl.sp_product_diagnosis_update import (
    PERIOD_CODES,
    daily_insert_sql,
    diagnosis_ddl,
    period_bounds,
    period_insert_sql,
    budget_snapshot_fields,
)


def test_period_bounds_supports_four_fixed_periods():
    assert PERIOD_CODES == {"7d": 7, "14d": 14, "30d": 30, "90d": 90}
    assert period_bounds(date(2026, 9, 6), "30d") == (
        date(2026, 8, 8),
        date(2026, 9, 6),
    )


def test_product_key_separates_store_country_and_msku():
    assert product_key(" Store-DE ", "de", "Sku-1") != product_key(
        "Store-FR", "fr", "Sku-1"
    )
    assert product_key(" Store-DE ", "DE", "Sku-1") == product_key(
        "store-de", "de", "sku-1"
    )


def test_product_diagnosis_store_and_site_inputs_support_partial_matches():
    filters = ProductDiagnosisFilters({"store": "jingjie", "country": "US"})

    clause, params = _where(filters, 7)

    assert "coalesce(s.seller_name,'') like %s escape '!'" in clause
    assert "coalesce(s.country_code,'') like %s escape '!'" in clause
    assert params[-2:] == ["%jingjie%", "%US%"]


def test_rates_are_calculated_after_aggregation_and_zero_is_missing():
    rates = calculate_diagnosis_rates(
        {
            "impressions": 1000,
            "clicks": 20,
            "ad_cost": Decimal("12"),
            "ad_orders": 4,
            "ad_sales": Decimal("60"),
            "operating_sales": Decimal("120"),
            "operating_gross_profit": Decimal("24"),
        }
    )
    assert rates == {
        "ctr": Decimal("0.02"),
        "cpc": Decimal("0.6"),
        "cvr": Decimal("0.2"),
        "acos": Decimal("0.2"),
        "roas": Decimal("5"),
        "tacos": Decimal("0.1"),
        "operating_gross_margin": Decimal("0.2"),
    }
    assert calculate_diagnosis_rates({}) == {
        "ctr": None,
        "cpc": None,
        "cvr": None,
        "acos": None,
        "roas": None,
        "tacos": None,
        "operating_gross_margin": None,
    }


def test_filters_validate_period_window_action_and_page_size():
    filters = ProductDiagnosisFilters(
        {"period": "90d", "window": "30", "action": "negative", "page_size": "100"}
    )
    assert filters.period == "90d"
    assert filters.window == 30
    assert filters.action == "negative"
    with pytest.raises(ValueError):
        ProductDiagnosisFilters({"period": "31d"})
    with pytest.raises(ValueError):
        ProductDiagnosisFilters({"window": "3"})
    with pytest.raises(ValueError):
        ProductDiagnosisFilters({"action": "execute"})


def test_detail_only_loads_actionable_suggestion_statuses():
    assert SUGGESTION_ACTION_STATUSES == {
        "bid": ("increase", "decrease", "manual_review"),
        "add": ("recommended",),
        "negative": ("recommended", "manual_review"),
    }


def test_ddl_and_insert_sql_use_local_sources_and_preserve_all_windows():
    ddl = diagnosis_ddl().lower()
    daily_sql = daily_insert_sql().lower()
    period_sql = period_insert_sql().lower()
    for table in (
        "dashboard_sp_product_diagnosis_daily",
        "dashboard_sp_product_diagnosis_period_snapshot",
        "dashboard_sp_product_diagnosis_batch",
    ):
        assert table in ddl
    assert "dashboard_product_performance_daily" in daily_sql
    assert "dashboard_sp_product_ad_daily" in daily_sql
    assert "p.ad_spend" not in daily_sql
    assert "ad_present_flag" in ddl
    assert "union all" in daily_sql
    assert "coalesce(trim(seller_name),'')<>''" in daily_sql
    assert "coalesce(trim(country_code),'')<>''" in daily_sql
    assert "having sum(ad_present_flag)>0" in period_sql
    for window in (1, 7, 14, 30):
        assert f"ad_orders_{window}d" in ddl
        assert f"ad_sales_{window}d" in ddl
    assert "row_number() over" in period_sql
    assert "dashboard_sp_bid_recommendation" in period_sql
    assert "dashboard_sp_add_term_recommendation" in period_sql
    assert "dashboard_sp_negative_term_recommendation" in period_sql
    for column in (
        "targeting_type",
        "budget_snapshot_date",
        "budget_performance_date",
        "monthly_ad_budget_cny",
        "month_spend_cny",
        "remaining_budget_cny",
        "budget_usage_rate",
        "inventory_sufficient_flag",
        "budget_support_status",
    ):
        assert column in ddl


def test_budget_snapshot_fields_use_cny_spend_and_inventory_guards():
    fields = budget_snapshot_fields(
        {
            "monthly_ad_budget_cny": Decimal("1000"),
            "inventory_sufficient_flag": 1,
            "weekly_inventory_sufficient_flag": 1,
        },
        Decimal("250"),
        date(2026, 9, 8),
        date(2026, 9, 6),
    )
    assert fields["remaining_budget_cny"] == Decimal("750")
    assert fields["budget_usage_rate"] == Decimal("0.25")
    assert fields["budget_support_status"] == "支持提价"

    blocked = budget_snapshot_fields(
        {"monthly_ad_budget_cny": Decimal("100"), "inventory_sufficient_flag": 0},
        Decimal("120"),
        date(2026, 9, 8),
        date(2026, 9, 6),
    )
    assert blocked["remaining_budget_cny"] == Decimal("0")
    assert blocked["budget_support_status"] == "库存不足且预算已用尽"
