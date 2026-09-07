from pathlib import Path


HTML = Path("app/templates/ad_performance.html")
JS = Path("app/static/js/ad_performance.js")
CSS = Path("app/static/css/ad_performance.css")


def test_recommendation_tabs_and_read_only_copy_exist():
    html = HTML.read_text(encoding="utf-8")
    assert "竞价优化" in html
    assert "加词建议" in html
    assert "否词建议" in html
    assert "产品诊断（待建设）" in html
    assert 'data-pending-feature="product-diagnosis"' in html
    assert 'href="/label-hub">产品诊断' not in html
    assert "预算管理" in html
    assert "仅供人工决策参考" in html


def test_recommendation_filters_and_rule_bar_exist():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ap-rec-status"' in html
    assert 'id="ap-rec-priority"' in html
    assert 'id="ap-rule-copy"' in html


def test_frontend_uses_read_only_recommendation_endpoints():
    js = JS.read_text(encoding="utf-8")
    assert "/recommendations/" in js
    assert "/execute" not in js
    assert "/apply" not in js


def test_recommendation_tables_show_concrete_actions():
    js = JS.read_text(encoding="utf-8")
    for field in ("suggested_bid", "change_amount", "suggestion_value", "suggestion_type"):
        assert field in js


def test_add_recommendations_keep_all_rows_and_show_explicit_actions():
    js = JS.read_text(encoding="utf-8")
    assert '$("ap-rec-status").value="recommended"' not in js
    for label in ("建议新增", "无需新增（已存在）", "暂不新增（未达标准）", "建议动作", "数据提示"):
        assert label in js


def test_negative_recommendations_disclose_that_term_protection_is_not_connected():
    js = JS.read_text(encoding="utf-8")
    assert "品牌词、核心类目词和新品推广词命中后转人工审核" in js
    assert "protection_record_missing" not in js
    assert "brand_name_missing" not in js


def test_negative_recommendations_use_clear_manual_review_labels():
    js = JS.read_text(encoding="utf-8")
    assert 'manual_review:"人工审核"' in js
    assert 'kind==="negative"?"人工审核原因":"数据提示"' in js


def test_hidden_overview_sections_cannot_be_overridden_by_layout_css():
    css = CSS.read_text(encoding="utf-8")
    for selector in ("#ap-window-bar[hidden]", "#ap-kpis[hidden]", "#ap-trend-panel[hidden]", "#ap-tabs[hidden]"):
        assert selector in css


def test_long_recommendation_object_text_is_clipped_to_its_grid_cell():
    css = CSS.read_text(encoding="utf-8")
    assert ".ap-grid .ag-cell-wrapper,.ap-grid .ag-cell-value{min-width:0;max-width:100%;overflow:hidden}" in css
    assert ".ap-object{display:block;width:100%;min-width:0;max-width:100%;overflow:hidden" in css
