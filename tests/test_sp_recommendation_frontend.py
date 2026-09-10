from pathlib import Path


HTML = Path("app/templates/ad_performance.html")
JS = Path("app/static/js/ad_performance.js")
CSS = Path("app/static/css/ad_performance.css")


def test_recommendation_tabs_and_read_only_copy_exist():
    html = HTML.read_text(encoding="utf-8")
    assert "竞价优化" in html
    assert "加词建议" in html
    assert "否词建议" in html
    assert ">产品诊断</button>" in html
    assert 'data-mode="diagnosis"' in html
    assert 'href="/label-hub">产品诊断' not in html
    assert 'href="/ad-budget">预算管理' not in html
    assert "仅供人工决策参考" in html


def test_recommendation_filters_and_rule_bar_exist():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="ap-rec-status"' in html
    assert 'id="ap-rec-priority"' in html
    assert 'id="ap-rule-copy"' in html


def test_public_filters_are_searchable_and_split_by_object_type():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")

    assert '<input id="ap-store" type="search" list="ap-store-options"' in html
    assert '<datalist id="ap-store-options"></datalist>' in html
    assert '<input id="ap-country" type="search" list="ap-country-options"' in html
    assert '<datalist id="ap-country-options"></datalist>' in html
    for control in ("ap-campaign", "ap-ad-group", "ap-keyword-text", "ap-search-term"):
        assert f'id="{control}"' in html
    assert 'campaign: $("ap-campaign").value.trim()' in js
    assert 'ad_group: $("ap-ad-group").value.trim()' in js
    assert 'keyword_text: $("ap-keyword-text").value.trim()' in js
    assert 'search_term: $("ap-search-term").value.trim()' in js
    assert 'event.key==="Enter"' in js


def test_frontend_uses_read_only_recommendation_endpoints():
    js = JS.read_text(encoding="utf-8")
    assert "/recommendations/" in js
    assert "/execute" not in js
    assert "/apply" not in js


def test_product_diagnosis_controls_and_read_only_endpoints_exist():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    for control in ("ap-diagnosis-period", "ap-diagnosis-action", "ap-diagnosis-kpis"):
        assert f'id="{control}"' in html
    assert "/product-diagnosis/" in js
    assert "diagnosisColumns" in js
    assert "switchToRecommendation" in js
    assert "具体处理建议" in js
    assert "调整竞价 " in js
    assert "suggestion_counts" in js
    assert "(data.suggestions.bid||[]).length" not in js


def test_recommendation_tables_show_concrete_actions():
    js = JS.read_text(encoding="utf-8")
    for field in ("suggested_bid", "change_amount", "suggestion_value", "suggestion_type"):
        assert field in js


def test_recommendation_and_product_diagnosis_tables_show_campaign_targeting_type():
    js = JS.read_text(encoding="utf-8")

    assert 'headerName:"广告类型"' in js
    assert 'targetingLabel(p.value)' in js
    assert '混合投放' in js


def test_bid_table_explains_price_margin_budget_and_bid_ceiling():
    js = JS.read_text(encoding="utf-8")
    for field in (
        "cvr", "acos", "listing_price", "margin_rate", "listing_mapping_status",
        "monthly_ad_budget_cny", "month_spend_cny", "remaining_budget_cny",
        "budget_usage_rate", "budget_support_status", "max_allowed_bid",
    ):
        assert field in js
    assert "允许最高建议竞价" in js
    assert "关联多个MSKU，分别查看商品预算" in js
    assert "预算已用尽，仅禁止提价" in js
    assert "最小竞价单位限制，本次不调整" in js


def test_ad_amounts_use_the_selected_currency_symbol():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "js/ad_currency.js" in html
    assert "AdCurrency.format" in js
    assert "monthly_ad_budget_cny" in js
    assert "month_spend_cny" in js


def test_recommendation_pages_show_all_currencies_with_row_level_units_without_totals():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")

    assert 'id="ap-currency-label"' in html
    assert 'kind: state.mode, currency: ""' in js
    assert '$("ap-currency-label").hidden=recommendation' in js
    assert '{field:"currency_code",headerName:"币种"' in js
    assert "valueFormatter:rowMoney" in js


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


def test_recommendation_summary_exposes_clickable_status_distribution():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert 'id="ap-rec-summary-panel"' in html
    assert 'id="ap-rec-status-cards"' in html
    assert 'id="ap-rec-status-chart"' in html
    assert "status_breakdown" in js
    assert "data-rec-status" in js
    assert 'classList.toggle("active"' in js
    assert ".ap-rec-status-card" in css


def test_recommendation_summary_does_not_show_cross_currency_amount_totals():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")

    assert 'id="ap-rec-cost"' not in html
    assert 'id="ap-rec-sales"' not in html
    assert "function currencyAmounts(field)" not in js


def test_ad_performance_script_cache_key_changes_when_summary_nodes_are_removed():
    html = HTML.read_text(encoding="utf-8")

    assert "path='js/ad_performance.js') }}?v=20260910b" in html


def test_bid_insufficient_data_is_split_into_specific_user_facing_categories():
    js = JS.read_text(encoding="utf-8")

    assert '"no_order_below_threshold","无订单未达阈值"' in js
    assert '"with_order_below_threshold","有订单未达阈值"' in js
    assert '"current_bid_missing","当前竞价缺失"' in js
    assert '"calculation_input_missing","计算字段缺失"' in js
    assert '["insufficient_data","数据不足"' not in js


def test_term_observe_count_stays_in_cards_but_is_hidden_from_distribution_chart():
    js = JS.read_text(encoding="utf-8")

    assert '["add","negative"].indexOf(state.mode)>=0?meta.slice(1).filter(function(item){return item[0]!=="observe";}):meta.slice(1)' in js


def test_add_status_filter_includes_manual_review_category():
    js = JS.read_text(encoding="utf-8")
    assert '["manual_review","先核对商品归属"]' in js


def test_add_status_distinguishes_existing_inactive_objects():
    js = JS.read_text(encoding="utf-8")

    assert '["existing_inactive","已存在但未启用"' in js
    assert 'existing_inactive:"已存在但未启用"' in js


def test_recommendation_frontend_explains_temporal_msku_mapping_failures():
    js = JS.read_text(encoding="utf-8")

    assert 'period_multiple_msku:"成熟窗口内投放过多个MSKU"' in js
    assert 'current_multiple_msku:"当前同时启用多个MSKU"' in js
    assert 'msku_changed:"成熟窗口商品与当前启用商品不一致"' in js
