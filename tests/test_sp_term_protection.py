from datetime import date, datetime

from app.services.sp_term_protection import (
    build_protection_context_rows,
    classify_term_protection,
    strict_phrase_match,
)
from etl.sp_term_protection_update import protection_context_ddl, SOURCE_QUERIES


def test_strict_phrase_match_normalizes_case_and_punctuation_without_short_substrings():
    assert strict_phrase_match("Presse-ail", "presse ail cuisine") == "Presse-ail"
    assert strict_phrase_match("AI", "air fryer") is None
    assert strict_phrase_match("AI", "ai") == "AI"


def test_classification_identifies_brand_category_and_ninety_day_new_product():
    result = classify_term_protection(
        "Radianeroryi federmäppchen",
        {
            "product_brand": "Radianeroryi",
            "store_brands_json": '["Radianeroryi"]',
            "leaf_categories_json": '["Federmäppchen", "办公用品与文具"]',
            "launch_date": date(2026, 6, 20),
        },
        cutoff=date(2026, 9, 6),
    )

    assert result["term_protection_complete"] is True
    assert result["is_brand_term"] is True
    assert result["is_core_category_term"] is True
    assert result["is_new_product_term"] is True
    assert result["protection_brand"] == "Radianeroryi"
    assert result["protection_category"] == "Federmäppchen"
    assert result["product_age_days"] == 78


def test_classification_reports_each_missing_context_component():
    result = classify_term_protection(
        "generic term",
        {
            "product_brand": "",
            "store_brands_json": "[]",
            "leaf_categories_json": "[]",
            "launch_date": None,
        },
        cutoff=date(2026, 9, 6),
    )

    assert result["term_protection_complete"] is False
    assert result["protection_missing_codes"] == [
        "brand_context_missing",
        "category_context_missing",
        "launch_date_missing",
    ]


def test_context_builder_uses_latest_listing_and_title_leaf_category_fallback():
    listings = [
        {
            "id": 1,
            "seller_name": "Store-DE",
            "seller_sku": "SKU1",
            "asin": "B000000001",
            "marketplace": "德国",
            "seller_brand": "OldBrand",
            "small_1": "",
            "open_date_display": "2026-01-01",
            "first_order_time": "",
            "create_time": datetime(2026, 8, 1),
        },
        {
            "id": 2,
            "seller_name": "Store-DE",
            "seller_sku": "SKU1",
            "asin": "B000000001",
            "marketplace": "德国",
            "seller_brand": "NewBrand",
            "small_1": "12 - Schraubenschlüssel",
            "open_date_display": "2026-01-01",
            "first_order_time": "2026-06-10",
            "create_time": datetime(2026, 9, 1),
        },
    ]
    titles = [{"seller_name": "Store-DE", "msku": "SKU1", "leaf_category": "Werkzeug", "category": ""}]
    store_brands = [{"store_name": "Store", "brand_name": "NewBrand"}]

    rows = build_protection_context_rows(listings, titles, store_brands, title_run_id=3)

    assert len(rows) == 1
    assert rows[0]["product_brand"] == "NewBrand"
    assert rows[0]["country_code"] == "DE"
    assert rows[0]["leaf_categories"] == ["Schraubenschlüssel", "Werkzeug"]
    assert rows[0]["launch_date"] == date(2026, 6, 10)
    assert rows[0]["launch_date_source"] == "first_order_time"


def test_context_builder_keeps_same_store_and_msku_in_different_countries():
    base = {
        "id": 1,
        "seller_name": "SharedStore",
        "seller_sku": "SKU1",
        "seller_brand": "Brand",
        "create_time": datetime(2026, 9, 1),
    }
    rows = build_protection_context_rows(
        [{**base, "marketplace": "德国"}, {**base, "id": 2, "marketplace": "法国"}],
        [],
        [],
    )

    assert {(row["country_code"], row["msku"]) for row in rows} == {
        ("DE", "SKU1"),
        ("FR", "SKU1"),
    }


def test_context_builder_deduplicates_business_keys_case_insensitively():
    rows = build_protection_context_rows(
        [
            {
                "id": 1,
                "seller_name": "Store-DE",
                "seller_sku": "Sku-1",
                "marketplace": "德国",
                "seller_brand": "OldBrand",
                "create_time": datetime(2026, 8, 1),
            },
            {
                "id": 2,
                "seller_name": "store-de",
                "seller_sku": "sku-1",
                "marketplace": "德国",
                "seller_brand": "NewBrand",
                "create_time": datetime(2026, 9, 1),
            },
        ],
        [],
        [],
    )

    assert len(rows) == 1
    assert rows[0]["product_brand"] == "NewBrand"


def test_protection_sync_uses_listing_sources_and_never_budget_snapshot():
    ddl = protection_context_ddl().lower()
    source_sql = " ".join(SOURCE_QUERIES.values()).lower()
    assert "dashboard_sp_term_protection_current" in ddl
    assert "dwd_datasync.lx_sales_mws_listing" in source_sql
    assert "opt_db.store_brand_relation" in source_sql
    assert "opt_db.lyt_title_optimization_latest_detail" in source_sql
    assert "dashboard_ad_budget_snapshot" not in source_sql
