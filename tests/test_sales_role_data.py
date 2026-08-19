from decimal import Decimal

import pytest

from app.services.dashboard_db import (
    SALES_ROLE_PERIOD_TABLE,
    SALES_ROLE_PERIODS,
    classify_sales_role,
    sales_role_daily_sales_band,
    sales_role_margin_band,
)


@pytest.mark.parametrize(
    ("daily_sales", "margin_rate", "expected_key"),
    [
        (Decimal("5.01"), Decimal("0.1501"), "star"),
        (Decimal("1"), Decimal("0.2501"), "star"),
        (Decimal("5"), Decimal("0.2501"), "star"),
        (Decimal("5.01"), Decimal("0.05"), "potential"),
        (Decimal("5.01"), Decimal("0.15"), "potential"),
        (Decimal("1"), Decimal("0.10"), "potential"),
        (Decimal("5"), Decimal("0.25"), "potential"),
        (Decimal("1"), Decimal("0.05"), "incubation"),
        (Decimal("5"), Decimal("0.0999"), "incubation"),
        (Decimal("0.99"), Decimal("0.0501"), "incubation"),
        (Decimal("0"), Decimal("0.90"), "eliminate"),
        (Decimal("0.99"), Decimal("0.05"), "eliminate"),
        (Decimal("2"), Decimal("0.0499"), "eliminate"),
        (Decimal("6"), None, "eliminate"),
    ],
)
def test_classify_sales_role_matches_label_thresholds(daily_sales, margin_rate, expected_key):
    assert classify_sales_role(daily_sales, margin_rate)["key"] == expected_key


def test_sales_role_bands_match_page_matrix_contract():
    assert sales_role_daily_sales_band(Decimal("0")) == "日销 0"
    assert sales_role_daily_sales_band(Decimal("0.5")) == "日销 <1"
    assert sales_role_daily_sales_band(Decimal("5")) == "日销 1-5"
    assert sales_role_daily_sales_band(Decimal("5.01")) == "日销 >5"

    assert sales_role_margin_band(None) == "<5%"
    assert sales_role_margin_band(Decimal("0.049")) == "<5%"
    assert sales_role_margin_band(Decimal("0.05")) == "5%-10%"
    assert sales_role_margin_band(Decimal("0.10")) == "10%-15%"
    assert sales_role_margin_band(Decimal("0.15")) == "15%-25%"
    assert sales_role_margin_band(Decimal("0.25")) == ">25%"


def test_sales_role_uses_full_pool_snapshot_table_and_fixed_periods():
    assert SALES_ROLE_PERIOD_TABLE == "etl_datasync_test.dashboard_sales_role_period_snapshot"
    assert SALES_ROLE_PERIODS == {"3d", "7d", "14d", "30d", "90d"}
