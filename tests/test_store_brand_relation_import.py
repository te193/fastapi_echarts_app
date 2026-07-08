from scripts.import_store_brand_relation import (
    build_brand_relations,
    clean_brand,
    normalize_store_name,
)


def test_clean_brand_filters_empty_like_values():
    for raw in ("", "  ", "#N/A", "N/A", "NULL", "None", "无", "-"):
        assert clean_brand(raw) is None


def test_normalize_store_name_strips_only_eu_and_uk_suffixes():
    assert normalize_store_name("pingter-eu") == "pingter"
    assert normalize_store_name("QINGLEE-EU") == "QINGLEE"
    assert normalize_store_name("Tboke-uk") == "Tboke"
    assert normalize_store_name("Zhuoleel") == "Zhuoleel"


def test_build_brand_relations_splits_distinct_uk_and_eu_brands():
    rows = [
        {
            "店铺名": "pingter-eu",
            "店铺ID": "A1",
            "英标": "Taipintee",
            "欧标": "PtuaTcsce",
            "是否补货": "是",
            "运营": "Alice",
            "亚马逊业务备注": "note",
        }
    ]

    relations = build_brand_relations(rows, source_file="data/店铺综合信息.xlsx")

    assert [(item.store_name, item.brand_name, item.brand_source) for item in relations] == [
        ("pingter", "Taipintee", "英标"),
        ("pingter", "PtuaTcsce", "欧标"),
    ]
    assert all(item.raw_store_name == "pingter-eu" for item in relations)
    assert all(item.store_id == "A1" for item in relations)


def test_build_brand_relations_deduplicates_same_uk_and_eu_brand():
    rows = [
        {
            "店铺名": "same-eu",
            "英标": "BrandX",
            "欧标": "BrandX",
            "是否补货": None,
            "运营": None,
        }
    ]

    relations = build_brand_relations(rows, source_file="source.xlsx")

    assert [(item.store_name, item.brand_name, item.brand_source) for item in relations] == [
        ("same", "BrandX", "英标欧标相同"),
    ]


def test_build_brand_relations_skips_rows_without_store_or_brand():
    rows = [
        {"店铺名": "missing-brand", "英标": "#N/A", "欧标": ""},
        {"店铺名": "", "英标": "Brand", "欧标": ""},
    ]

    assert build_brand_relations(rows, source_file="source.xlsx") == []
