from datetime import date
from decimal import Decimal

import pytest

from app.services.sp_recommendation_data import (
    RecommendationFilters,
    csv_cell,
    order_by,
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
    assert order_by(filters) == "priority_rank asc,cost desc,id asc"
