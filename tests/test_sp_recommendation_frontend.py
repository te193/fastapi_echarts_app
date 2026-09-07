from pathlib import Path


HTML = Path("app/templates/ad_performance.html")
JS = Path("app/static/js/ad_performance.js")
CSS = Path("app/static/css/ad_performance.css")


def test_recommendation_tabs_and_read_only_copy_exist():
    html = HTML.read_text(encoding="utf-8")
    assert "竞价优化" in html
    assert "加词建议" in html
    assert "否词建议" in html
    assert "产品诊断" in html
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


def test_hidden_overview_sections_cannot_be_overridden_by_layout_css():
    css = CSS.read_text(encoding="utf-8")
    for selector in ("#ap-window-bar[hidden]", "#ap-kpis[hidden]", "#ap-trend-panel[hidden]", "#ap-tabs[hidden]"):
        assert selector in css
