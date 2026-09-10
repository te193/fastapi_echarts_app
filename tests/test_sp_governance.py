from pathlib import Path

from app.services.sp_governance_data import GovernanceFilters, base_store_name, governance_where
from etl.sp_advertising_recommendations import classify_governance_msku_mapping, deduplicate_governance_assets


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "app" / "templates" / "ad_performance.html"
JS = ROOT / "app" / "static" / "js" / "ad_performance.js"
CSS = ROOT / "app" / "static" / "css" / "ad_performance.css"
MAIN = ROOT / "app" / "main.py"
ETL = ROOT / "etl" / "sp_advertising_recommendations.py"


def test_store_subject_normalization_preserves_internal_hyphens():
    assert base_store_name("JkangMei-DE", "DE") == "JkangMei"
    assert base_store_name("Tboke-eu-DE", "DE") == "Tboke"
    assert base_store_name("North-Star-US", "US") == "North-Star"
    assert base_store_name("StoreWithoutSuffix", "DE") == "StoreWithoutSuffix"


def test_governance_asset_snapshot_deduplicates_remote_dimension_rows():
    rows = [
        {"profile_id": 1, "campaign_id": 2, "ad_group_id": 3, "ad_group_name_current": "旧名称"},
        {"profile_id": 1, "campaign_id": 2, "ad_group_id": 3, "ad_group_name_current": "新名称"},
        {"profile_id": 1, "campaign_id": 2, "ad_group_id": 4, "ad_group_name_current": "另一组"},
    ]

    result = deduplicate_governance_assets(rows)

    assert len(result) == 2
    assert result[0]["ad_group_name_current"] == "新名称"


def test_governance_filters_apply_targeting_state_action_and_exact_scope():
    filters = GovernanceFilters(
        {
            "base_store": "JkangMei",
            "store": "JkangMei-DE",
            "country": "DE",
            "targeting_type": "auto",
            "entity_state": "paused",
            "action_type": "negative",
            "keyword": "KW",
            "profile_id": 11,
            "campaign_id": 22,
            "ad_group_id": 33,
        }
    )

    clause, params = governance_where(filters)

    assert "base_store_name=%s" in clause
    assert "seller_name=%s" in clause
    assert "country_code=%s" in clause
    assert "targeting_type=%s" in clause
    assert "ad_group_state_current=%s" in clause
    assert "negative_action_count>0" in clause
    assert "profile_id=%s" in clause
    assert "campaign_id=%s" in clause
    assert "ad_group_id=%s" in clause
    assert "campaign_name_current" in clause and "ad_group_name_current" in clause
    assert params[:5] == ["JkangMei", "JkangMei-DE", "DE", "auto", "paused"]


def test_governance_accepts_msku_level_and_searches_product_identity():
    filters = GovernanceFilters({"level": "msku", "keyword": "JKM-012a"})

    clause, params = governance_where(filters)

    assert filters.level == "msku"
    assert "msku" in clause and "asin" in clause
    assert params == ["%JKM-012a%"] * 4


def test_governance_msku_mapping_only_exposes_one_consistent_product():
    assert classify_governance_msku_mapping(1, "JKM-012a", 1, "JKM-012a") == ("normal_mapping", "JKM-012a")
    assert classify_governance_msku_mapping(2, "JKM-012a", 1, "JKM-012a") == ("period_multiple_msku", None)
    assert classify_governance_msku_mapping(1, "JKM-012a", 0, None) == ("current_record_missing", None)
    assert classify_governance_msku_mapping(1, "JKM-012a", 1, "JKM-013a") == ("msku_changed", None)


def test_governance_ui_has_independent_tab_filters_and_master_detail_workspace():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert 'data-mode="governance"' in html
    assert html.index('data-mode="overview"') < html.index('data-mode="governance"') < html.index('data-mode="bid"')
    for control in (
        "ap-governance-targeting",
        "ap-governance-state",
        "ap-governance-action",
        "ap-governance-keyword",
        "ap-governance-store-list",
        "ap-governance-entity-grid",
    ):
        assert f'id="{control}"' in html
    assert "/api/ad-performance/governance/" in js
    assert "renderGovernanceStores" in js
    assert "renderGovernanceEntities" in js
    assert 'governanceFetch("stores",{base_store:""})' in js
    assert 'makeGrid("ap-governance-entity-grid",{rowData:rows,columnDefs:cols,domLayout:"normal"' in js
    assert "switchGovernanceRecommendation" in js
    assert "bid_manual_review_count" in js
    assert "add_manual_review_count" in js
    assert "negative_manual_review_count" in js
    assert 'data-bid-type=""' in html
    assert 'targeting=(row&&row.targeting_type)||$("ap-governance-targeting").value' in js
    assert "governanceStateLabel" in js
    assert 'data-level="msku"' in html
    assert "governanceMskuMappingLabel" in js
    assert "待确认归属" in js
    assert "先确认归属" in js
    assert ".ap-governance-workspace" in css


def test_governance_entities_expose_manual_review_source_counts():
    service = (ROOT / "app" / "services" / "sp_governance_data.py").read_text(encoding="utf-8")

    assert "sum(g.bid_manual_review_count)" in service
    assert "sum(g.add_manual_review_count)" in service
    assert "sum(g.negative_manual_review_count)" in service


def test_governance_routes_and_snapshot_refresh_are_registered():
    main = MAIN.read_text(encoding="utf-8")
    etl = ETL.read_text(encoding="utf-8")

    for endpoint in ("options", "summary", "stores", "entities"):
        assert f'/api/ad-performance/governance/{endpoint}' in main
    assert "dashboard_sp_governance_ad_group_snapshot" in etl
    assert "refresh_governance_snapshot" in etl
    assert "msku_mapping_status" in etl
    assert "period_msku_count" in etl
    assert "current_msku_count" in etl
