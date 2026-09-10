from datetime import date
from decimal import Decimal

from app.services.sp_recommendation_rules import (
    calculate_add_recommendation,
    calculate_bid_recommendation,
    calculate_negative_recommendation,
    classify_search_term,
    mature_window,
)
from etl.sp_advertising_recommendations import bid_cvr_benchmarks, bid_protection_values
from etl.sp_advertising_recommendations import extract_same_as_asins, existing_object_state


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


def test_add_term_separates_existing_inactive_object():
    result = calculate_add_recommendation(
        {"search_term": "alpha", "orders": 12, "cost": 5, "sales": 100, "existing_state": "inactive"}
    )

    assert result["status"] == "existing_inactive"
    assert result["reason_codes"] == ["existing_inactive"]


def test_existing_keyword_requires_exact_match_type_and_normalizes_text():
    keywords = {(1, 2, "water bottle", "EXACT"): "enabled"}

    assert existing_object_state(1, 2, " Water   Bottle ", keywords, {}) == "enabled"
    assert existing_object_state(1, 3, "water bottle", keywords, {}) is None
    assert existing_object_state(1, 2, "other term", keywords, {}) is None


def test_existing_product_target_uses_asin_same_as_expression():
    expressions = '[{"expression_item_type":"asinSameAs","expression_item_value":"B0ABC12345"},' \
                  '{"expression_item_type":"asinExpandedFrom","expression_item_value":"B0OTHER123"}]'
    products = {(1, 2, "B0ABC12345"): "inactive"}

    assert extract_same_as_asins(expressions) == {"B0ABC12345"}
    assert existing_object_state(1, 2, "b0abc12345", {}, products) == "inactive"


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


def test_negative_term_requires_manual_review_when_msku_is_missing():
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
    assert result["status"] == "manual_review"
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


def test_negative_term_requires_manual_review_for_incomplete_term_protection_context():
    result = calculate_negative_recommendation(
        {
            "search_term": "generic phrase",
            "clicks": 10,
            "orders": 0,
            "associated_msku_count": 1,
            "term_protection_complete": False,
            "protection_missing_codes": ["category_context_missing"],
        }
    )

    assert result["status"] == "manual_review"
    assert result["reason_codes"] == ["category_context_missing"]


def test_negative_term_requires_manual_review_for_brand_category_or_new_product():
    for field, reason in (
        ("is_brand_term", "brand_term"),
        ("is_core_category_term", "core_category_term"),
        ("is_new_product_term", "new_product_term"),
    ):
        result = calculate_negative_recommendation(
            {
                "search_term": "protected phrase",
                "clicks": 10,
                "orders": 0,
                "associated_msku_count": 1,
                "term_protection_complete": True,
                field: True,
            }
        )
        assert result["status"] == "manual_review"
        assert result["priority"] == "high"
        assert reason in result["reason_codes"]


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
            "clicks": 20,
            "orders": 1,
            "sales": "1.50",
            "cost": "1.00",
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
            "clicks": 20,
            "orders": 4,
            "sales": "100",
            "site_cvr_p75": "0.15",
            "site_cvr_avg": "0.10",
        }
    )
    assert result["theoretical_cpc"] == Decimal("1.4000")
    assert result["suggested_bid"] == Decimal("1.20")
    assert result["change_amount"] == Decimal("0.20")
    assert result["status"] == "increase"


def test_zero_order_bid_rule_forces_a_thirty_percent_decrease():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "clicks": 15,
            "orders": 0,
            "sales": 0,
            "associated_msku_count": 1,
            "price_mapped": True,
            "margin_ladder_complete": True,
        }
    )
    assert result["status"] == "decrease"
    assert result["suggested_bid"] == Decimal("0.70")
    assert "clicks_ge_15_orders_zero" in result["reason_codes"]


def test_high_acos_forces_direction_and_clips_decrease_to_rule_band():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "aov": "100",
            "cvr": "0.10",
            "margin_rate": "0.20",
            "clicks": 20,
            "orders": 2,
            "sales": "3.00",
            "cost": "2.00",
            "associated_msku_count": 1,
        }
    )
    assert result["status"] == "decrease"
    assert result["suggested_bid"] == Decimal("0.80")
    assert result["change_rate"] == Decimal("-0.2000")
    assert "acos_gt_50" in result["reason_codes"]


def test_bid_change_smaller_than_one_cent_is_kept_instead_of_labelled_as_decrease():
    result = calculate_bid_recommendation(
        {
            "current_bid": "0.05",
            "aov": "18.8792",
            "cvr": "0.05405405",
            "margin_rate": "0.10",
            "clicks": 222,
            "orders": 12,
            "sales": "226.55",
            "cost": "86.29",
            "associated_msku_count": 1,
        }
    )

    assert result["suggested_bid"] == Decimal("0.05")
    assert result["change_amount"] == Decimal("0.00")
    assert result["status"] == "keep"
    assert "minimum_bid_increment_blocks_change" in result["reason_codes"]


def test_inventory_or_exhausted_monthly_budget_only_blocks_an_increase():
    row = {
        "current_bid": "1.00",
        "aov": "20",
        "cvr": "0.20",
        "margin_rate": "0.35",
        "clicks": 20,
        "orders": 4,
        "sales": "100",
        "site_cvr_p75": "0.15",
        "site_cvr_avg": "0.10",
        "associated_msku_count": 1,
        "inventory_sufficient": False,
        "budget_sufficient": False,
    }
    result = calculate_bid_recommendation(row)
    assert result["status"] == "keep"
    assert result["suggested_bid"] == Decimal("1.00")
    assert result["reason_codes"] == ["inventory_blocks_increase", "budget_blocks_increase"]


def test_missing_bid_protection_snapshot_is_unknown_not_insufficient():
    assert bid_protection_values(None, "12.50") == {
        "inventory_sufficient": None,
        "budget_sufficient": None,
    }


def test_bid_protection_only_blocks_explicit_shortage():
    assert bid_protection_values(
        {"inventory_sufficient_flag": 0, "monthly_ad_budget_cny": "10"},
        "12.50",
    ) == {"inventory_sufficient": False, "budget_sufficient": False}
    assert bid_protection_values(
        {"inventory_sufficient_flag": 1, "monthly_ad_budget_cny": "20"},
        "12.50",
    ) == {"inventory_sufficient": True, "budget_sufficient": True}


def test_site_cvr_benchmarks_use_weighted_average_and_p75_per_bid_level():
    rows = [
        {"object_type": "keyword", "country_code": "DE", "clicks": 10, "orders": 1},
        {"object_type": "keyword", "country_code": "DE", "clicks": 30, "orders": 9},
        {"object_type": "keyword", "country_code": "DE", "clicks": 20, "orders": 4},
        {"object_type": "ad_group", "country_code": "DE", "clicks": 10, "orders": 5},
    ]
    result = bid_cvr_benchmarks(rows)
    assert result[("keyword", "DE")]["site_cvr_avg"] == Decimal("0.2333333333333333333333333333")
    assert result[("keyword", "DE")]["site_cvr_p75"] == Decimal("0.25")
    assert result[("ad_group", "DE")]["site_cvr_avg"] == Decimal("0.5")


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


def test_bid_mapping_uses_temporal_mapping_status_before_legacy_count():
    result = calculate_bid_recommendation(
        {
            "current_bid": "1.00",
            "associated_msku_count": 1,
            "msku_mapping_status": "msku_changed",
        }
    )

    assert result["status"] == "manual_review"
    assert result["reason_codes"] == ["msku_changed"]
