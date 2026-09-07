from datetime import date
from decimal import Decimal

from app.services.sp_recommendation_rules import (
    calculate_add_recommendation,
    calculate_bid_recommendation,
    calculate_negative_recommendation,
    classify_search_term,
    mature_window,
)


def test_mature_window_excludes_latest_seven_days():
    assert mature_window(date(2026, 9, 6)) == (
        date(2026, 8, 1),
        date(2026, 8, 30),
    )


def test_search_term_classification_distinguishes_asin_from_text():
    assert classify_search_term("B0ABC12345") == "product_target"
    assert classify_search_term("wireless charger") == "keyword"


def test_add_term_thresholds_are_inclusive():
    highest = calculate_add_recommendation(
        {"search_term": "alpha", "orders": 10, "cost": 10, "sales": 100}
    )
    medium = calculate_add_recommendation(
        {"search_term": "beta", "orders": 10, "cost": 15, "sales": 100}
    )
    assert (highest["status"], highest["priority"], highest["suggestion_type"]) == (
        "recommended",
        "highest",
        "exact_keyword",
    )
    assert (medium["status"], medium["priority"]) == ("recommended", "medium")


def test_add_term_keeps_existing_object_out_of_the_action_list():
    existing = calculate_add_recommendation(
        {
            "search_term": "alpha",
            "orders": 12,
            "cost": 5,
            "sales": 100,
            "existing_enabled": True,
        }
    )
    assert existing["status"] == "existing"


def test_add_term_recommends_by_performance_and_flags_ambiguous_mapping():
    ambiguous = calculate_add_recommendation(
        {
            "search_term": "alpha",
            "orders": 12,
            "cost": 5,
            "sales": 100,
            "associated_msku_count": 2,
        }
    )
    assert ambiguous["status"] == "recommended"
    assert ambiguous["priority"] == "highest"
    assert "multiple_msku" in ambiguous["reason_codes"]


def test_negative_term_requires_10_clicks_and_zero_orders():
    below = calculate_negative_recommendation(
        {"search_term": "free sample", "clicks": 9, "orders": 0}
    )
    boundary = calculate_negative_recommendation(
        {"search_term": "free sample", "clicks": 10, "orders": 0}
    )
    with_order = calculate_negative_recommendation(
        {"search_term": "free sample", "clicks": 10, "orders": 1}
    )
    assert below["status"] == "observe"
    assert boundary["status"] == "recommended"
    assert boundary["priority"] == "high"
    assert boundary["suggestion_type"] == "negative_exact"
    assert boundary["reason_codes"] == ["clicks_ge_10_orders_zero"]
    assert with_order["status"] == "observe"


def test_negative_asin_uses_negative_product_target():
    result = calculate_negative_recommendation(
        {"search_term": "B0ABC12345", "clicks": 150, "orders": 0}
    )
    assert result["suggestion_type"] == "negative_product_target"


def test_negative_term_recommends_by_performance_and_flags_missing_msku_only():
    result = calculate_negative_recommendation(
        {
            "search_term": "brand phrase",
            "clicks": 100,
            "orders": 0,
            "associated_msku_count": 0,
            "protection_record_mapped": False,
            "brand_name_complete": False,
        }
    )
    assert result["status"] == "recommended"
    assert result["priority"] == "high"
    assert "msku_missing" in result["reason_codes"]
    assert "protection_record_missing" not in result["reason_codes"]
    assert "brand_name_missing" not in result["reason_codes"]


def test_negative_term_does_not_treat_budget_context_as_a_term_warning():
    result = calculate_negative_recommendation(
        {
            "search_term": "generic phrase",
            "clicks": 10,
            "orders": 0,
            "associated_msku_count": 1,
            "protection_record_mapped": False,
            "brand_name_complete": False,
        }
    )

    assert result["status"] == "recommended"
    assert result["reason_codes"] == ["clicks_ge_10_orders_zero"]


def test_bid_change_is_capped_and_rounded_safely():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "aov": "20",
            "cvr": "0.10",
            "margin_rate": "0.35",
            "inventory_sufficient": True,
            "budget_sufficient": True,
            "associated_msku_count": 1,
        }
    )
    assert result["theoretical_cpc"] == Decimal("0.7000")
    assert result["suggested_bid"] == Decimal("0.70")
    assert result["change_amount"] == Decimal("-0.30")
    assert result["change_rate"] == Decimal("-0.30")
    assert result["status"] == "decrease"


def test_bid_increase_is_limited_to_twenty_percent():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "aov": "20",
            "cvr": "0.20",
            "margin_rate": "0.35",
            "inventory_sufficient": True,
            "budget_sufficient": True,
            "associated_msku_count": 1,
        }
    )
    assert result["theoretical_cpc"] == Decimal("1.4000")
    assert result["suggested_bid"] == Decimal("1.20")
    assert result["change_amount"] == Decimal("0.20")
    assert result["status"] == "increase"


def test_bid_protection_blocks_price_when_mapping_is_ambiguous():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "aov": "20",
            "cvr": "0.10",
            "margin_rate": "0.20",
            "associated_msku_count": 2,
        }
    )
    assert result["status"] == "manual_review"
    assert result["suggested_bid"] is None
