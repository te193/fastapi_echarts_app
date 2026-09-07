from datetime import date
from decimal import Decimal

from etl.sp_advertising_recommendations import (
    coverage_is_complete,
    margin_band_rate,
    recommendation_ddl,
)


def test_recommendation_ddl_has_all_tables_and_business_keys():
    ddl = recommendation_ddl().lower()
    assert "dashboard_sp_recommendation_batch" in ddl
    assert "dashboard_sp_bid_recommendation" in ddl
    assert "dashboard_sp_add_term_recommendation" in ddl
    assert "dashboard_sp_negative_term_recommendation" in ddl
    assert ddl.count("unique key") >= 2
    assert "dashboard_sp_negative_term_recommendation like dashboard_sp_add_term_recommendation" in ddl
    assert "utf8mb4_bin" in ddl


def test_coverage_requires_every_day_in_mature_window():
    start, end = date(2026, 8, 1), date(2026, 8, 30)
    complete = [date(2026, 8, day) for day in range(1, 31)]
    assert coverage_is_complete(complete, start, end) is True
    assert coverage_is_complete(complete[1:], start, end) is False


def test_margin_band_uses_lower_interval():
    ladder = {
        0: Decimal("10"),
        5: Decimal("11"),
        10: Decimal("12"),
        15: Decimal("13"),
        20: Decimal("14"),
        25: Decimal("15"),
        30: Decimal("16"),
        35: Decimal("17"),
    }
    assert margin_band_rate(Decimal("14.99"), ladder) == Decimal("0.20")
    assert margin_band_rate(Decimal("17.99"), ladder) == Decimal("0.35")
    assert margin_band_rate(Decimal("9.99"), ladder) is None
