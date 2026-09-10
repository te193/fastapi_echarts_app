from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.sp_recommendation_data import (
    RecommendationFilters,
    merge_bid_budget_context,
    bid_display_status,
    csv_cell,
    order_by,
    status_breakdown_expression,
    serialize,
    table_for_kind,
    _where,
)


def test_recommendation_kind_and_sort_are_whitelisted():
    with pytest.raises(ValueError):
        RecommendationFilters({"kind": "bad_table"})
    with pytest.raises(ValueError):
        RecommendationFilters({"kind": "bid", "sort": "cost desc;drop table x"})


def test_recommendation_page_size_is_whitelisted():
    assert RecommendationFilters({"page_size": 100}).page_size == 100
    with pytest.raises(ValueError):
        RecommendationFilters({"page_size": 75})


def test_recommendation_table_mapping_is_fixed():
    assert table_for_kind("bid") == "dashboard_sp_bid_recommendation"
    assert table_for_kind("add") == "dashboard_sp_add_term_recommendation"
    assert table_for_kind("negative") == "dashboard_sp_negative_term_recommendation"


@pytest.mark.parametrize("object_type", ["ad_group", "keyword"])
def test_bid_type_is_parameterized_for_shared_summary_rows_and_export(object_type):
    clause, params = _where(RecommendationFilters(kind="bid", object_type=object_type), 2)
    assert clause == "batch_id=%s and object_type=%s"
    assert params == [2, object_type]


def test_invalid_or_non_bid_object_type_is_rejected():
    with pytest.raises(ValueError):
        RecommendationFilters(object_type="keyword' or 1=1")
    with pytest.raises(ValueError):
        RecommendationFilters(kind="add", object_type="keyword")


def test_recommendation_ids_and_decimals_are_serialized_safely():
    payload = serialize({"campaign_id": 9007199254740999, "cost": Decimal("1.20")})
    assert payload == {"campaign_id": "9007199254740999", "cost": 1.2}


def test_recommendation_context_warnings_are_exposed_separately_from_action():
    payload = serialize(
        {"status": "recommended", "reason_codes": '["clicks_ge_10_orders_zero", "msku_missing"]'}
    )
    assert payload["status"] == "recommended"
    assert payload["data_warning"] == "未找到推广MSKU，需人工排查"


def test_negative_review_reason_includes_the_matched_protection_value():
    payload = serialize(
        {
            "status": "manual_review",
            "reason_codes": '["brand_term", "core_category_term", "new_product_term"]',
            "protection_brand": "Radianeroryi",
            "protection_category": "Federmäppchen",
            "product_launch_date": date(2026, 6, 20),
        }
    )
    assert payload["data_warning"] == (
        "品牌词：Radianeroryi；核心类目词：Federmäppchen；"
        "新品推广词：首单/开售日期 2026-06-20"
    )


def test_recommendation_csv_protects_ids_and_formulas():
    assert csv_cell("campaign_id", 9007199254740999) == "'9007199254740999"
    assert csv_cell("search_term", "=cmd()") == "'=cmd()"


def test_default_order_prioritizes_actionable_rows_before_cost():
    filters = RecommendationFilters({"kind": "bid", "sort": "cost", "direction": "desc"})
    assert order_by(filters) == (
        "case when status in ('increase','decrease') and coalesce(change_amount,0)=0 then 1 else 0 end asc,"
        "priority_rank asc,cost desc,id asc"
    )


def test_recommendation_object_filters_are_independent_and_combined():
    filters = RecommendationFilters({
        "kind": "add",
        "store": "jingjie",
        "country": "US",
        "campaign": "JJ068a",
        "ad_group": "KW",
        "keyword_text": "float switch",
        "search_term": "12volt",
    })

    clause, params = _where(filters, 9)

    assert "coalesce(seller_name,'') like %s escape '!'" in clause
    assert "coalesce(country_code,'') like %s escape '!'" in clause
    assert "coalesce(campaign_name_current,'') like %s escape '!'" in clause
    assert "coalesce(ad_group_name_current,'') like %s escape '!'" in clause
    assert "coalesce(target_text,'') like %s escape '!'" in clause
    assert "coalesce(search_term,'') like %s escape '!'" in clause
    assert params[-6:] == [
        "%jingjie%", "%US%", "%JJ068a%", "%KW%", "%float switch%", "%12volt%"
    ]


def test_recommendation_filters_accept_exact_governance_scope_ids():
    filters = RecommendationFilters({
        "kind": "negative", "base_store": "JkangMei", "profile_id": "11", "campaign_id": "22", "ad_group_id": "33"
    })

    clause, params = _where(filters, 9)

    assert "profile_id=%s" in clause
    assert "campaign_id=%s" in clause
    assert "ad_group_id=%s" in clause
    assert "regexp_replace" in clause
    assert params[-4:] == ["JkangMei", 11, 22, 33]


def test_unknown_targeting_filter_includes_blank_and_unrecognized_source_values():
    clause, params = _where(RecommendationFilters({"kind": "add", "targeting": "__unknown__"}), 9)

    assert "coalesce(targeting_type,'') not in ('auto','manual')" in clause
    assert params == [9]


def test_summary_query_keeps_currency_totals_separate():
    source = Path("app/services/sp_recommendation_data.py").read_text(encoding="utf-8")

    assert '"currency_totals": currency_totals' in source
    assert "group by coalesce(nullif(currency_code,''),'')" in source


def test_bid_rows_are_enriched_with_product_budget_and_explanation_fields():
    rows = [{
        "seller_name": "JkangMei-DE", "country_code": "DE", "msku": "JKM-012a",
        "associated_msku_count": 1, "status": "increase", "current_bid": Decimal("0.18"),
        "suggested_bid": Decimal("0.19"), "cost": Decimal("48.61"), "sales": Decimal("278.54"),
        "cvr": Decimal("0.1812"), "listing_price": Decimal("19.99"), "margin_rate": Decimal("0.15"),
        "reason_codes": '["site_avg_cvr_increase", "theoretical_cpc_guard"]',
    }]
    contexts = {("jkangmei-de", "DE", "jkm-012a"): {
        "monthly_ad_budget_cny": Decimal("8082.14"), "month_spend_cny": Decimal("2162.07"),
        "remaining_budget_cny": Decimal("5920.07"), "budget_usage_rate": Decimal("0.26751207"),
        "budget_support_status": "支持提价", "inventory_sufficient_flag": 1,
        "budget_snapshot_date": date(2026, 9, 8), "budget_performance_date": date(2026, 9, 6),
    }}

    enriched = merge_bid_budget_context(rows, contexts)[0]

    assert enriched["acos"] == Decimal("48.61") / Decimal("278.54")
    assert enriched["listing_mapping_status"] == "已匹配"
    assert enriched["monthly_ad_budget_cny"] == Decimal("8082.14")
    assert enriched["budget_context_status"] == "matched"
    assert enriched["max_allowed_bid"] == Decimal("0.19")


def test_multi_msku_ad_group_does_not_claim_one_products_budget():
    row = {
        "seller_name": "Store-DE", "country_code": "DE", "msku": "A,B",
        "associated_msku_count": 2, "status": "manual_review", "current_bid": Decimal("0.20"),
        "suggested_bid": None, "listing_price": None, "margin_rate": None,
    }

    enriched = merge_bid_budget_context([row], {})[0]

    assert enriched["budget_context_status"] == "multiple_msku"
    assert enriched["budget_support_status"] == "关联多个MSKU，分别查看商品预算"
    assert enriched["monthly_ad_budget_cny"] is None
    assert enriched["max_allowed_bid"] is None


def test_budget_or_inventory_guard_caps_allowed_bid_at_current_bid():
    row = {
        "seller_name": "Store-DE", "country_code": "DE", "msku": "SKU-1",
        "associated_msku_count": 1, "status": "keep", "current_bid": Decimal("0.26"),
        "suggested_bid": Decimal("0.26"), "listing_price": Decimal("9.99"),
        "margin_rate": Decimal("0.20"), "reason_codes": '["budget_blocks_increase"]',
    }

    enriched = merge_bid_budget_context([row], {})[0]

    assert enriched["max_allowed_bid"] == Decimal("0.26")


def test_legacy_zero_amount_bid_action_is_presented_as_keep():
    row = {
        "seller_name": "MuuWei-IT", "country_code": "IT", "msku": "MUW3006a",
        "associated_msku_count": 1, "status": "decrease", "current_bid": Decimal("0.05"),
        "suggested_bid": Decimal("0.05"), "change_amount": Decimal("0.00"),
        "reason_codes": '["acos_gt_333", "theoretical_cpc_guard"]',
    }

    enriched = merge_bid_budget_context([row], {})[0]

    assert enriched["status"] == "keep"
    assert "minimum_bid_increment_blocks_change" in enriched["reason_codes"]


def test_bid_status_breakdown_treats_zero_amount_actions_as_keep():
    expression = status_breakdown_expression("bid")
    assert "then 'keep'" in expression
    assert "then 'no_order_below_threshold'" in expression
    assert "then 'with_order_below_threshold'" in expression
    assert "then 'current_bid_missing'" in expression
    assert "then 'calculation_input_missing'" in expression
    assert status_breakdown_expression("add") == "status"
    assert status_breakdown_expression("negative") == "status"


def test_bid_status_filter_uses_the_same_normalized_status_as_breakdown():
    clause, params = _where(RecommendationFilters(kind="bid", status="decrease"), 9)

    assert clause == f"batch_id=%s and {status_breakdown_expression('bid')}=%s"
    assert params == [9, "decrease"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"status": "insufficient_data", "current_bid": None, "clicks": 8, "orders": 0}, "current_bid_missing"),
        ({"status": "insufficient_data", "current_bid": 0.2, "clicks": 8, "orders": 0}, "no_order_below_threshold"),
        ({"status": "insufficient_data", "current_bid": 0.2, "clicks": 12, "orders": 0}, "no_order_below_threshold"),
        ({"status": "insufficient_data", "current_bid": 0.2, "clicks": 8, "orders": 1}, "with_order_below_threshold"),
        ({"status": "insufficient_data", "current_bid": 0.2, "clicks": 16, "orders": 1}, "with_order_below_threshold"),
        ({"status": "insufficient_data", "current_bid": 0.2, "clicks": 20, "orders": 1}, "calculation_input_missing"),
        ({"status": "decrease", "current_bid": 0.2, "change_amount": 0}, "keep"),
    ],
)
def test_bid_display_status_splits_waiting_samples_from_missing_inputs(row, expected):
    assert bid_display_status(row) == expected


def test_bid_row_exposes_specific_waiting_reason_instead_of_data_insufficient():
    row = {
        "seller_name": "Store-DE", "country_code": "DE", "msku": "SKU-1",
        "associated_msku_count": 1, "status": "insufficient_data",
        "current_bid": Decimal("0.20"), "clicks": 14, "orders": Decimal("0"),
        "reason_codes": '["metric_missing"]',
    }

    enriched = merge_bid_budget_context([row], {})[0]

    assert enriched["status"] == "no_order_below_threshold"
    assert enriched["source_status"] == "insufficient_data"
    assert enriched["reason_codes"] == ["no_order_below_threshold"]
    assert enriched["suggested_bid"] == Decimal("0.20")
    assert enriched["change_direction"] == "keep"
    assert enriched["change_amount"] == Decimal("0")
    assert enriched["change_rate"] == Decimal("0")
