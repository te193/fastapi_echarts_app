from datetime import date
from decimal import Decimal

from etl.sp_advertising_recommendations import (
    _group_products,
    _resolve_group_product,
    business_key,
    coverage_is_complete,
    margin_band_rate,
    recommendation_ddl,
)


def test_group_product_mapping_requires_same_single_msku_in_period_and_current_state():
    safe = _resolve_group_product(
        {"enabled_msku_count": 1, "msku": "SKU-A", "asin": "ASIN-A"},
        {"period_msku_count": 1, "msku": "sku-a", "asin": "ASIN-A"},
    )
    changed = _resolve_group_product(
        {"enabled_msku_count": 1, "msku": "SKU-B", "asin": "ASIN-B"},
        {"period_msku_count": 1, "msku": "SKU-A", "asin": "ASIN-A"},
    )
    historical_multi = _resolve_group_product(
        {"enabled_msku_count": 1, "msku": "SKU-B", "asin": "ASIN-B"},
        {"period_msku_count": 2, "msku": None, "asin": None},
    )
    current_multi = _resolve_group_product(
        {"enabled_msku_count": 2, "msku": None, "asin": None},
        {"period_msku_count": 1, "msku": "SKU-A", "asin": "ASIN-A"},
    )

    assert safe == {
        "associated_msku_count": 1,
        "msku": "sku-a",
        "asin": "ASIN-A",
        "msku_mapping_status": "mapped",
    }
    assert changed["msku"] is None
    assert changed["msku_mapping_status"] == "msku_changed"
    assert historical_multi["msku_mapping_status"] == "period_multiple_msku"
    assert current_multi["msku_mapping_status"] == "current_multiple_msku"


def test_group_products_cross_checks_current_enabled_and_period_products():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def fetchall(self):
            if len(self.calls) == 1:
                return [{
                    "profile_id": 1, "campaign_id": 2, "ad_group_id": 3,
                    "enabled_msku_count": 1, "msku": "SKU-A", "asin": "ASIN-A",
                }]
            return [{
                "profile_id": 1, "campaign_id": 2, "ad_group_id": 3,
                "period_msku_count": 1, "msku": "SKU-A", "asin": "ASIN-A",
            }]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    result = _group_products(connection, date(2026, 8, 1), date(2026, 8, 30))

    assert result[(1, 2, 3)]["msku"] == "SKU-A"
    assert result[(1, 2, 3)]["msku_mapping_status"] == "mapped"
    assert connection.cursor_instance.calls[1][1] == (
        date(2026, 8, 1),
        date(2026, 8, 30),
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
    assert "idx_bid_default_v2" in ddl
    assert "idx_add_default_v2" in ddl
    assert "protection_brand" in ddl
    assert "protection_category" in ddl
    assert "product_launch_date" in ddl


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


def test_business_key_normalizes_account_suffix_and_country_name():
    assert business_key("xinmu-eu-FR", "FR", "XM036a") == business_key(
        "xinmu", "法国", "XM036a"
    )
