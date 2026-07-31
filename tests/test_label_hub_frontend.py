from pathlib import Path
import json
import re


ROOT = Path(__file__).resolve().parents[1]


def test_label_hub_uses_url_conditions_and_profile_drawer_contract():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'app.apiGet("/api/label-hub/meta")' in script
    assert 'app.apiGet("/api/label-hub", buildParams())' in script
    assert 'app.writeQueryState(state);' in script
    assert 'conditions: serializeConditions(state.conditions)' in script
    assert '"/api/label-hub/msku"' in script
    assert '"/api/label-hub/msku-country-profile"' in script
    assert 'window.kanbanGrid.makeGrid("labelHubTable"' in script
    assert 'metric_period: state.metric_period' in script
    assert 'analysis_parent_ids: state.analysis_parent_ids' in script
    assert 'sales_trends: serializeCodes(state.sales_trends)' in script
    assert 'daily_sales_bands: serializeCodes(state.daily_sales_bands)' in script
    assert 'margin_bands: serializeCodes(state.margin_bands)' in script
    assert 'class="label-hub-breakdown-rules"' in script
    assert "panel.rules" in script


def test_operation_cards_render_active_return_attribution_and_linked_filter():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'data-return-attribution' in script
    assert '"返场期再次断货"' in script
    assert '"返场期被判停售"' in script
    assert "applyReturnAttributionFilter" in script
    assert ".label-hub-return-attribution" in styles


def test_operating_stockout_rate_renders_quiet_footer_and_formula_popover():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderOperatingStockoutRate" in script
    assert "data-operating-stockout-formula" in script
    for copy in ("在营断货率", "有效断货", "在营", "返场再断货", "查看口径"):
        assert copy in script
    assert "清仓中和停售不计入在营记录" in script
    assert ".label-hub-operating-stockout-rate" in styles
    assert ".label-hub-operating-stockout-popover" in styles


def test_label_hub_detail_workbench_uses_independent_post_flow_and_dual_views():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    for element_id in (
        "labelHubDetailView", "labelHubDetailIdentifiers", "labelHubDetailLabels",
        "labelHubDetailCountries", "labelHubDetailCountryCategories", "labelHubDetailStores",
        "labelHubDetailProblems", "labelHubDetailProblemMode", "labelHubDetailSalesRoles",
        "labelHubDetailRoleReasons", "labelHubDetailDailyBands", "labelHubDetailMarginBands",
        "labelHubDetailApply", "labelHubDetailClear", "labelHubIdentifierResolution",
    ):
        assert f'id="{element_id}"' in template
    assert 'fetch("/api/label-hub/details"' in script
    assert "function buildDetailPayload()" in script
    assert "function renderDetails()" in script
    assert "detail_view:" in script
    assert 'localStorage.getItem("labelHubDetailView")' in script
    assert 'localStorage.setItem("labelHubDetailView"' in script
    assert '<option value="business_unit">MSKU维度</option>' in template
    assert '"MSKU维度 " + formatNumber(counts.business_unit_count)' in script
    assert "renderTable(payload);" not in script.split('app.apiGet("/api/label-hub", buildParams())', 1)[1].split("}).catch", 1)[0]
    assert "countryIdentityColumns" in script
    assert 'headerName: "国家"' in script
    assert 'headerName: "SKU"' in script


def test_detail_apply_button_shows_loading_feedback_while_request_is_pending():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "function setDetailLoading(isLoading)" in script
    assert 'elements.labelHubDetailApply.textContent = isLoading ? "筛选中…" : "应用筛选";' in script
    assert 'elements.labelHubDetailApply.disabled = isLoading;' in script
    assert "setDetailLoading(true);" in script
    assert "setDetailLoading(false);" in script


def test_detail_role_reason_filter_replaces_sales_trend_and_follows_detail_scope():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'id="labelHubDetailRoleReasons"' in template
    assert 'data-placeholder="全部角色原因"' in template
    assert 'id="labelHubRoleReasonTrigger"' in template
    assert 'id="labelHubRoleReasonPanel"' in template
    assert 'id="labelHubRoleReasonGroups"' in template
    assert 'id="labelHubDetailRoleReasons" multiple hidden' in template
    assert 'id="labelHubDetailSalesTrends"' not in template
    assert 'id="labelHubRoleReasonScope"' in template
    assert "role_reason_ids: []" in script
    assert "role_reason_ids: detailState.role_reason_ids" in script
    assert "function roleReasonOptions()" in script
    assert "function reconcileRoleReasonSelections()" in script
    assert "function renderRoleReasonPanel()" in script
    assert "data-role-reason-id" in script
    assert '["role_reason_ids", "角色原因", elements.labelHubDetailRoleReasons]' in script
    assert "detailState.role_reason_ids = [];" in script
    assert ".label-hub-role-reason-scope" in styles
    assert ".label-hub-role-reason-panel" in styles
    assert ".label-hub-role-reason-section" in styles
    assert ".label-hub-role-reason-options" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in styles
    detail_selects = script.split("function detailFilterSelects()", 1)[1].split(
        "function destroyDetailFilterSelects()", 1
    )[0]
    assert "labelHubDetailRoleReasons" not in detail_selects


def test_detail_filters_use_compact_toolbar_and_collapsed_advanced_panel():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    for element_id in (
        "labelHubDetailToolbar", "labelHubDetailAdvanced", "labelHubDetailMore",
        "labelHubDetailActiveFilters", "labelHubDetailActiveFilterList",
    ):
        assert f'id="{element_id}"' in template
    assert 'id="labelHubDetailAdvanced" class="label-hub-detail-advanced" hidden' in template
    assert "function initDetailFilterSelects()" in script
    assert "function destroyDetailFilterSelects()" in script
    assert "function toggleDetailAdvancedFilters()" in script
    assert "function renderDetailActiveFilters()" in script
    assert "new window.SlimSelect" in script
    toolbar_index = template.index('id="labelHubDetailToolbar"')
    labels_index = template.index('id="labelHubDetailLabels"')
    advanced_index = template.index('id="labelHubDetailAdvanced"')
    problems_index = template.index('id="labelHubDetailProblems"')
    assert toolbar_index < labels_index < advanced_index < problems_index


def test_country_detail_exposes_ranking_filter_state_and_column():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'id="labelHubDetailRankingBands"' in template
    for value in ("top10", "11_20", "21_50", "51_100", "gt100", "missing"):
        assert f'value="{value}"' in template
    assert "ranking_bands: []" in script
    assert "ranking_bands: detailState.ranking_bands" in script
    assert '["ranking_bands", detailState.detail_view === "country" ? "排名" : "排名（已保留）"' in script
    assert 'headerName: "排名", field: "ranking"' in script


def test_detail_filters_match_compact_reference_visual_language():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")

    assert ".label-hub-detail-toolbar" in styles
    assert ".label-hub-detail-advanced" in styles
    assert ".label-hub-detail-active-filters" in styles
    assert ".label-hub-detail-filter-chip" in styles
    assert ".label-hub-detail-filter-control .ss-main:has(.ss-value)" in styles
    assert ".ss-value .ss-value-text" in styles
    assert "color: #155ba6;" in styles
    assert "styles.css') }}?v=20260731rolereason2" in template
    assert ".label-hub-detail-workbench select[multiple] { min-height: 64px" not in styles


def test_detail_filter_action_buttons_follow_primary_secondary_hierarchy():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert ".label-hub-detail-apply:hover" in styles
    assert ".label-hub-detail-apply:active" in styles
    assert ".label-hub-detail-clear:hover" in styles
    assert ".label-hub-detail-clear:active" in styles
    assert ".label-hub-detail-apply:focus-visible" in styles
    assert ".label-hub-detail-clear:focus-visible" in styles


def test_label_hub_template_exposes_overview_diagnosis_and_breakdowns():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")

    for element_id in (
        "labelHubMetricPeriod", "labelHubScope", "labelHubPopulationSummary", "labelHubCategories", "labelHubBreakdowns",
        "labelHubMeasureTabs", "labelHubDiagnosis", "labelHubMatrixPanel", "labelHubDrawerContent",
        "labelHubCountryProfileDrawer", "labelHubCountryProfileContent",
    ):
        assert f'id="{element_id}"' in template


def test_current_combination_change_reuses_changes_api_and_compact_ledger():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    for heading in ("上次", "今日", "本期进入", "本期离开", "简要说明"):
        assert heading in script
    assert "未选择联动条件" in script
    assert "新增记录" in script
    assert 'app.apiGet("/api/label-hub/changes"' in script
    assert 'app.apiGet("/api/label-hub/highlights"' not in script
    assert "renderCurrentCombinationChange" in script


def test_change_table_does_not_call_same_visible_label_a_switch():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'previousValue !== currentValue ? "标签切换" : "其他标签变化"' in script
    assert "row.trigger_dimensions" in script


def test_label_hub_reuses_sales_role_page_visual_structure():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="sales-role-page label-hub-page"' in template
    assert 'class="sales-role-topbar label-hub-topbar"' in template
    assert template.count("sales-role-panel label-hub-section-panel") == 4
    assert template.count("label-hub-secondary-panel") == 2
    assert 'body[data-page="label_hub"] .page-shell' in styles
    assert 'class="sales-role-filter-main label-hub-filter-primary"' in template
    assert 'id="labelHubConditionRow" class="label-hub-condition-row" hidden' in template


def test_label_hub_uses_clear_msku_counts_and_problem_first_analysis_layout():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    label_styles = styles.split("/* Unified label hub */", 1)[1]

    assert 'id="labelHubCategoryDetail"' in template
    assert 'class="label-hub-insight-grid"' in template
    assert 'id="labelHubRulesPanel"' not in template
    assert template.index('id="labelHubDiagnosis"') < template.index('id="labelHubBreakdowns"')
    assert "function renderCategoryDetail(payload)" in script
    assert "function renderPopulationSummary(payload)" in script
    assert "renderPopulationSummary(payload);" in script
    for label in ("去重 MSKU", "店铺商品记录", "跨范围 MSKU"):
        assert label in script
    assert "去重覆盖 " not in script
    assert '<div class="label-hub-coverage">' not in script
    assert "同一 MSKU 出现在多个店铺或国家类别" in script
    assert 'note: "国家类别 + 店铺 + MSKU"' in script
    assert "renderCategoryDetail(payload);" in script
    assert ".label-hub-categories { display: grid; grid-template-columns: repeat(4" in label_styles
    assert "font-size: 9px" not in label_styles
    assert ".label-hub-filters .label-hub-filter-primary,\n  .label-hub-categories" in label_styles
    assert ".label-hub-overview-section .sales-role-section-head" in label_styles


def test_label_hub_overview_cards_have_subtle_depth_and_hover_feedback():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert ".label-hub-overview-section .label-hub-population-card" in styles
    assert ".label-hub-overview-section .label-hub-category-card:hover" in styles
    assert "linear-gradient(145deg, #fff 0%, #fbfdff 100%)" in styles
    assert "transform: translateY(-2px);" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_label_hub_frontend_renders_six_linked_panels_and_structured_profile():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "function renderBreakdowns(payload)" in script
    assert "function renderIssueOverview(payload)" in script
    assert "function toggleLocalCondition(dimension, value)" in script
    assert "profile.tag_profile" in script
    assert "profile.metric_profile" in script
    assert "profile.navigation_links" in script
    assert 'data-negative="' in script
    assert "rowHeight: 52" in script


def test_label_hub_country_profile_is_a_separate_lazy_drawer_column():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function countryProfileColumn()" in script
    assert "function openCountryProfileDrawer(row)" in script
    assert "function countryProfilePriceCell(price, priceStatus)" in script
    assert "function countryProfileRankCell(metrics, metricStatus)" in script
    assert 'class="label-hub-country-rank-value"' in script
    assert "countryProfileMetricRow('小类排名', ranking)" not in script
    assert "function countryProfileLimitPriceCell(limitPrices, price, limitPriceStatus)" in script
    assert "limitPrices.margin_prices" in script
    assert "function countryProfileMetricsCell(metrics, metricPeriod, metricStatus)" in script
    assert "function countryProfileTrafficCell(metrics, metricStatus)" in script
    assert "function countryProfileCountryTagsCell(item)" in script
    assert 'var marginInterval = item.price_margin_interval || "--";' in script
    assert 'var pricingLabel = ((item.pricing || {}).label || "定价标签未命中");' not in script
    assert "function countryProfileSalesRolesCell(salesRoles)" in script
    assert "metric_period: state.metric_period || \"30d\"" in script
    assert "7d 国家销售角色" in script
    assert "小类排名" in script
    assert "毛利定价" in script
    assert "label-hub-country-profile-table-wrap" in styles
    assert "label-hub-country-profile-metrics" in styles
    assert ".label-hub-country-rank-value" in styles
    assert "label-hub-country-price-ladder" in styles
    assert "label-hub-country-role-grid" in styles


def test_label_hub_table_uses_explicit_profile_and_copy_actions():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderMskuCell(params)" in script
    assert 'data-copy-msku="' in script
    assert '<svg class="label-hub-copy-icon"' in script
    assert 'data-label-profile' in script
    assert "function copyMsku(button, value)" in script
    assert 'event.colDef.field === "label_summary"' in script
    assert "openDrawer(event.data)" in script
    assert "onRowClicked:" not in script
    assert ".label-hub-msku-copy" in styles
    assert "user-select: text" in styles
    assert "#labelHubTable .ag-row:hover .label-hub-msku-copy" in styles
    assert "#labelHubTable .label-hub-msku-copy:hover" in styles
    assert "pointer-events: none" in styles


def test_label_hub_copy_releases_mouse_focus_after_click():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    copy_click = script[
        script.index('var copyButton = target && target.closest("[data-copy-msku]");'):
        script.index("if (!event.data || !event.colDef) return;", script.index('var copyButton = target && target.closest("[data-copy-msku]");'))
    ]

    assert "copyButton.blur();" in copy_click


def test_msku_profile_does_not_show_average_inventory_metric():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert '["平均库存", metric.avg_inventory_qty]' not in script
    assert '["期末可售库存", metric.ending_inventory_qty]' in script


def test_label_hub_country_profile_uses_compact_full_height_table():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "<small>取经营窗口最后一天</small>" not in script
    assert "countryProfileMetricRow('TACOS', tacos)" in script
    assert ".label-hub-country-name { display: grid; justify-items: center;" in styles
    assert "<tr class=\"label-hub-country-profile-row" in script
    assert "<td class=\"label-hub-country-identity\">" in script
    assert ".label-hub-country-identity { display: table-cell; }" in styles
    assert ".label-hub-country-profile-table tbody td.label-hub-country-identity { vertical-align: middle; }" in styles
    assert "String(price.currency || \"\") + formatNumber(price.value)" not in script
    assert "var local = price.value === null || price.value === undefined ? \"--\" : formatNumber(price.value);" in script
    assert "#labelHubCountryProfileDrawer .label-hub-country-profile-table-wrap { max-height: min(78vh, 820px); overflow: auto; scrollbar-gutter: stable; }" in styles


def test_sales_role_diagnostics_module_is_lazy_and_filterable():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "labelHubDiagnosticsSection",
        "labelHubDiagnosticsScope",
        "labelHubDiagnosticsPeriod",
        "labelHubDiagnosticsRoles",
        "labelHubDiagnosticsContent",
    ):
        assert f'id="{element_id}"' in template
    assert 'app.apiGet("/api/label-hub/sales-role-diagnostics"' in script
    assert "diagnostic_scope" in script
    assert "diagnostic_period" in script
    assert "roleDiagnosticColumn" in script
    assert "openRoleDiagnosticDrawer" in script
    assert "selectedRoleDefinition.matcher.test" in script
    assert "#labelHubCountryProfileDrawer .label-hub-country-profile-table thead th { position: sticky; top: 0; z-index: 6; }" in styles
    assert ".label-hub-country-profile-table-wrap { overflow: visible;" in styles
    assert ".label-hub-country-profile-table tbody tr { height: 126px; }" not in styles


def test_role_diagnostics_visibility_follows_the_active_parent_category():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    start = script.index("function syncDiagnosticsVisibility()")
    end = script.index("function syncDiagnosticControls()", start)
    visibility_function = script[start:end]

    assert "elements.labelHubDiagnosticsSection.open = Number(state.parent_label_id) === 1;" in visibility_function
    assert "parsedConditions()" not in visibility_function
    assert script.count("syncDiagnosticsVisibility();") >= 2


def test_role_diagnostic_drawer_loads_evidence_and_supports_period_and_country_drilldown():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'app.apiGet("/api/label-hub/msku-role-diagnostics"' in script
    assert "function loadRoleDiagnosticDrawer()" in script
    assert "function renderRoleDiagnosticDrawer(payload)" in script
    assert "function roleDiagnosticMetricCard(metric)" in script
    assert 'data-role-diagnostic-period="' in script
    assert 'data-role-diagnostic-country="' in script
    assert "全站判断" in script
    assert "国家站点判断" in script
    assert "未达标指标" in script
    assert "还差多少" in script


def test_role_diagnostic_table_cell_uses_a_clear_action_button():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'tooltipField: "role_diagnostic_summary"' in script
    assert '<span>查看诊断</span><i aria-hidden="true">›</i>' in script
    assert ".label-hub-role-diagnostic-cell:hover" in styles
    assert ".label-hub-role-diagnostic-cell:focus-visible" in styles


def test_role_diagnostic_drawer_uses_structured_visual_hierarchy_and_responsive_layout():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert '#labelHubDrawer[data-drawer-mode="diagnostics"] .label-hub-drawer-card' in styles
    assert ".label-hub-role-global" in styles
    assert ".label-hub-role-upgrade" in styles
    assert ".label-hub-role-blocker" in styles
    assert ".label-hub-role-country.is-open" in styles
    assert ".label-hub-role-country-table" in styles
    assert "@media (max-width: 720px)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_label_hub_country_profile_uses_replenishment_detail_header():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="label-hub-country-profile-detail-head"' in script
    assert '<p class="section-kicker">国家明细</p>' in script
    assert "identity.sku || '--'" in script
    assert "summary.country_count || 0" in script
    assert "label-hub-country-profile-detail-subtitle" in script
    assert "label-hub-country-profile-detail-note" in script
    assert "label-hub-country-profile-basic-item" not in script
    assert ".label-hub-country-profile-detail-head" in styles


def test_layer_change_drawer_prioritizes_conclusion_attention_and_on_demand_details():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderLayerChangeLedger(payload, context)" in script
    assert "本层变化结论" in script
    assert "从哪里进入，离开后去了哪里" in script
    assert "哪些规则指标跨过了阈值" in script
    assert "label-hub-change-reconcile" in script
    assert "选择上方一项变化查看 MSKU" in script
    assert "label-hub-route-ledger" in script
    assert "changed_dimension" in script
    assert "changed_previous_label" in script
    assert "changed_current_label" in script
    assert "data-layer-transition-parent" in script
    assert "同维度标签未变，其他条件变化" not in script
    assert 'row.previous_layer_label' in script
    assert 'row.current_layer_label' in script
    assert 'row.fact_status' in script
    assert "layerChangeCombinationLabels" in script
    assert 'metric_profile' in script
    assert ".label-hub-route-summary" in styles
    assert ".label-hub-attribution-grid" in styles
    assert ".label-hub-change-detail-placeholder" in styles


def test_change_drawer_identifies_each_country_store_msku_business_unit():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'row.country_category' in script
    assert 'row.store' in script
    assert '<th>MSKU</th><th>同维度标签</th><th>变化原因</th><th>规则指标（上次→今日）</th><th>经营影响</th><th>证据状态</th>' in script
    assert '条记录' in script
    assert '变化记录' in script
    assert '对应产品与经营表现' in script
    assert 'metric.order_gross_profit' in script
    assert 'metric.sales_amount' in script
    assert "renderLayerRoutePanel" not in script
    assert ".label-hub-layer-ledger" in styles


def test_business_unit_aggregations_are_not_labeled_as_unique_msku_counts():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "这批店铺商品记录在其他分类中的表现" in template
    assert ">记录数</button>" in template
    assert "分析范围 \" + formatNumber(panel.denominator) + \" 条记录" in script
    assert '<span>记录数</span>' in script
    assert "经营单元" not in template
    assert "经营单元" not in script
    assert "MSKU明细" not in template
    assert "MSKU明细" not in script


def test_remote_breakdown_cards_keep_independent_label_periods_in_url_state():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'analysis_periods: query.get("analysis_periods") || ""' in script
    assert "function analysisPeriods()" in script
    assert "analysis_periods: state.analysis_periods" in script
    assert "panel.analysis_slot" in script
    assert 'data-analysis-period-slot="' in script
    assert 'class="label-hub-period-select"' in script
    assert 'class="label-hub-card-selectors"' in script
    assert "function destroyLinkedSelects()" in script
    assert "function initLinkedSelects()" in script
    assert "new window.SlimSelect" in script
    assert "window.setTimeout(resetPageAndRender, 0)" in script
    assert "vendor/slim-select/slimselect.css" in template
    assert "vendor/slim-select/slimselect.js" in template
    assert "cdn.jsdelivr.net/npm/slim-select" not in template
    assert ".label-hub-card-selectors" in styles
    assert ".label-hub-card-selectors .ss-main" in styles
    assert 'body[data-page="label_hub"],\n.label-hub-page { --ss-primary-color' in styles
    assert "--ss-primary-color" in styles


def test_label_hub_breakdowns_show_grouped_composition_and_semantic_status():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="label-hub-breakdown-group"' in script
    assert 'class="label-hub-composition"' in script
    assert 'class="label-hub-breakdown-finding"' in script
    assert "function breakdownTone(panel, bucket)" in script
    assert "function dominantBreakdown(buckets)" in script
    assert "未匹配经营快照" in script
    assert "当前归属键无快照" in script
    assert ".label-hub-breakdown-group" in styles
    assert ".label-hub-composition" in styles
    assert ".label-hub-bar.tone-risk" in styles
    assert ".label-hub-bar.tone-missing" in styles


def test_label_hub_breakdown_cards_use_layered_panel_surfaces():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "background: #f5f8fc;" in styles
    assert "box-shadow: 0 4px 14px rgba(31, 64, 104, .06);" in styles
    assert "align-items: stretch;" in styles
    assert ".label-hub-breakdown-card:hover" in styles


def test_label_hub_matrix_keeps_row_header_column_compact():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "grid-template-columns: 120px repeat(" in script
    assert "minmax(110px, 1.2fr)" not in script


def test_label_hub_matrix_uses_count_heat_scale_and_legend():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function matrixHeatLevel(count, maxCount)" in script
    assert 'class="label-hub-matrix-legend"' in script
    assert 'class="heat-level-' in script
    assert ".label-hub-matrix-table button.heat-level-4" in styles
    assert ".label-hub-matrix-legend" in styles


def test_label_hub_replaces_stale_url_date_with_latest_available_date():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "function normalizeStateFromMeta()" in script
    assert "dates.indexOf(state.data_date) < 0" in script
    assert "state.data_date = meta.default_data_date || dates[0] || \"\"" in script


def test_remote_breakdown_buckets_keep_distinct_stable_colors():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "var REMOTE_BUCKET_COLORS =" in script
    assert "function remoteBucketColor(panel, bucket)" in script
    assert 'style="--bucket-color:' in script
    assert "background: var(--bucket-color);" in styles


def test_label_date_is_read_only_scope_instead_of_redundant_filter():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "labelHubDatePicker" not in template
    assert 'type="date"' not in template
    assert "renderLabelDatePicker" not in script
    assert "normalizeStateFromMeta();" in script
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles


def test_label_hub_filters_use_one_compact_row_and_only_show_active_conditions():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    primary = template.split('class="sales-role-filter-main label-hub-filter-primary"', 1)[1].split("</div>", 1)[0]
    assert 'id="labelHubPeriodField"' in primary
    assert 'id="labelHubConditionRow"' in template
    assert 'id="labelHubConditionRow" class="label-hub-condition-row" hidden' in template
    assert 'elements.labelHubConditionRow.hidden = !chips.length;' in script
    assert '尚未叠加分析条件' not in script
    assert "grid-template-columns: minmax(132px, .65fr) minmax(132px, .65fr)" in styles


def test_remote_breakdown_nodes_have_enough_distinct_colors_for_long_status_lists():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    match = re.search(r"REMOTE_BUCKET_COLORS\s*=\s*(\[[^;]+\])", script)
    assert match
    colors = json.loads(match.group(1))
    assert len(colors) >= 12
    assert len(set(colors)) == len(colors)
    assert "remoteBucketColor(panel, bucket)" in script
    assert "?v=20260731rolereason2" in template


def test_label_hub_issue_overview_shows_selected_group_problem_counts():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'id="labelHubDiagnosis"' in template
    assert 'id="labelHubKpis"' not in template
    assert 'id="labelHubIssueQueue"' not in template
    assert "选中标签群体的问题概览" in template
    assert "突出偏差" not in template
    assert "基础池" not in template
    assert "function renderIssueOverview(payload)" in script
    assert "payload.issue_counts" in script
    for key in ("problem_role", "zero_sales", "negative_profit", "missing_metrics", "conflict"):
        assert f'"{key}"' in script
    assert re.search(r'\{\s*key:\s*"problem_role".*?local:\s*false', script)
    assert "占当前群体" in script
    assert 'data-problem="' in script
    diagnosis_handler = re.search(
        r'elements\.labelHubDiagnosis\.addEventListener\("click".*?\n\s*\}\);',
        script,
        re.S,
    )
    assert diagnosis_handler
    assert 'detailState.problems = state.problem === "all" ? [] : [state.problem]' in diagnosis_handler.group(0)
    assert 'detailState.problem_mode = "any"' in diagnosis_handler.group(0)


def test_label_hub_does_not_show_obsolete_primary_label_priority():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "aggregation_priority_labels" not in script
    assert "按业务优先级只保留一个主标签" not in script
    assert "主标签优先级" not in script
    assert "label-hub-rule-table-head" in script


def test_label_hub_profile_does_not_render_site_scope_labels():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "site_scope_labels" not in script
    assert "国家/站点口径标签" not in script
    assert "不参与当前驾驶舱聚合" not in script


def test_label_hub_coverage_cards_open_detail_table_rule_drawer():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'id="labelHubRuleDrawer"' in template
    assert 'id="labelHubRuleDrawerClose"' in template
    assert 'id="labelHubRuleDrawerContent"' in template
    assert 'data-view-rules="' in script
    assert "function openRuleDrawer(parentId)" in script
    assert "function closeRuleDrawer()" in script
    for field in ("definition", "rule", "periods", "tagging_method", "frequency", "owner", "mutual_exclusion", "status"):
        assert f"child.{field}" in script


def test_label_hub_rule_drawer_prioritizes_scanable_rules_and_collapses_metadata():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="label-hub-rule-table-head"' in script
    assert 'class="label-hub-rule-row"' in script
    assert 'class="label-hub-rule-row-main"' in script
    assert "<details" in script
    assert "展开配置" in script
    assert ".label-hub-rule-table-head" in styles
    assert ".label-hub-rule-row-main" in styles
    assert "grid-template-columns: minmax(110px" in styles


def test_label_hub_table_compacts_and_clips_the_full_label_summary():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderLabelSummaryCell(params)" in script
    assert 'cellClass: "label-summary-cell"' in script
    assert 'cellRenderer: renderLabelSummaryCell' in script
    assert "#labelHubTable .label-summary-cell" in styles
    assert "#labelHubTable .label-summary-cell .ag-cell-value" in styles


def test_label_hub_table_clips_multi_value_label_columns():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert '{ headerName: "当前标签", field: "current_label", width: 150, tooltipField: "current_label", cellClass: "label-text-cell" }' in script
    assert '{ headerName: "生命周期", field: "lifecycle_label", width: 110, tooltipField: "lifecycle_label", cellClass: "label-text-cell" }' in script
    assert "#labelHubTable .label-text-cell" in styles
    assert "#labelHubTable .label-text-cell .ag-cell-value" in styles


def test_label_hub_table_supports_page_size_and_fixed_header_viewport():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'id="labelHubPageSize"' in template
    for size in (20, 50, 100):
        assert f'<option value="{size}"' in template
    assert 'elements.labelHubPageSize.addEventListener("change"' in script
    assert "state.page_size = normalizePageSize(this.value);" in script
    assert "state.page = 1;" in script
    assert 'domLayout: "normal"' in script
    assert "function normalizePageSize(value)" in script
    assert "#labelHubTable {" in styles
    assert "height: min(680px, calc(100vh - 180px));" in styles


def test_label_hub_table_has_purpose_built_summary_label_and_metric_views():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'id="labelHubTableView"' in template
    for value, label in (("overview", "综合视图"), ("labels", "标签视图"), ("metrics", "经营视图")):
        assert f'<option value="{value}">{label}</option>' in template
    assert 'table_view: normalizeTableView(query.get("table_view"))' in script
    assert 'elements.labelHubTableView.addEventListener("change"' in script
    assert "function tableColumns(view)" in script
    assert "function overviewColumns()" in script
    assert "function labelColumns()" in script
    assert "function metricColumns()" in script
    for renderer in ("renderIssueCell", "renderTrendCell", "renderMetricStatusCell"):
        assert f"function {renderer}" in script
    for field in ("daily_sales", "ending_inventory_qty", "ad_spend", "acos", "tacos", "return_count", "net_amount"):
        assert f'"{field}"' in script
    assert 'amountColumn("未税销售额", "sales_amount_ex_tax"' not in script
    assert 'numberColumn("平均库存", "avg_inventory_qty"' not in script
    assert ".label-hub-issue-pill" in styles
    assert ".label-hub-trend-pill" in styles
    assert ".label-hub-metric-status" in styles


def test_label_hub_profile_marks_the_actual_local_metric_window():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function metricWindowLabel(window)" in script
    assert "status.metric_window" in script
    assert "period_start" in script
    assert "period_end" in script
    assert "lag_days" in script
    assert 'class="label-hub-profile-period"' in script
    assert ".label-hub-profile-period" in styles


def test_current_category_detail_uses_period_scoped_distribution():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    common = (ROOT / "app" / "static" / "js" / "common.js").read_text(encoding="utf-8")
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")

    assert "payload.distribution || []" in script
    assert "distributionById" in script
    assert 'cache: "no-store"' in common
    assert "js/common.js') }}?v=20260715cache2" in base
    assert "js/label_hub.js') }}?v=20260731rolereason2" in template


def test_country_detail_overview_matches_label_hub_information_structure():
    script = (ROOT / "app" / "static" / "js" / "country_label_hub.js").read_text(encoding="utf-8")

    for header in ("当前标签", "标签画像", "问题提示", "动销趋势"):
        assert f'headerName: "{header}"' in script
    for header in ("日均销量", "订单毛利润", "订单毛利率"):
        assert f'("{header}",' in script
    assert "renderCountryLabelSummaryCell" in script
    assert "renderCountryIssueCell" in script
    assert "renderCountryTrendCell" in script
    assert "profileLabelGroups" in script
    assert "renderCrossCountryComparison" in script
    assert "country-profile-compare-table" in script
    assert "一行一个国家，直接横向比较标签差异与经营结果" in script


def test_country_profile_drawer_uses_compact_grouped_table_layout():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function countryProfileCountryTagsCell(item)" in script
    assert "function countryProfileSalesRolesCell(salesRoles)" in script
    assert "label-hub-country-price-ladder" in styles
    assert "label-hub-country-role-grid" in styles


def test_country_detail_profile_keeps_comparison_and_prioritizes_clicked_country():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function prioritizeCountryProfileCountries(countries, currentCountry)" in script
    assert "prioritizeCountryProfileCountries(profile.countries || [], row.country)" in script
    assert '" is-current-country"' in script
    assert ".label-hub-country-profile-table tbody tr.is-current-country td" in styles


def test_main_dashboard_renders_before_change_tracking_request():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    render_block = script[script.index("  function render() {"):script.index("  function buildChangeParams() {")]

    assert render_block.index("lastPayload = payload;") < render_block.index("loadChanges();")


def test_sales_role_has_label_hub_return_link():
    script = (ROOT / "app" / "static" / "js" / "sales_role.js").read_text(encoding="utf-8")

    assert 'href = "/label-hub?" + params.toString();' in script
    assert '查看全部标签' in script


def test_detail_advanced_filters_use_balanced_responsive_layout():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in styles
    assert "elements.labelHubRankingFilterHint.hidden = countryActive || !detailState.ranking_bands.length;" in script


def test_identifier_input_has_expandable_batch_search_panel():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "labelHubIdentifierExpand",
        "labelHubIdentifierPopover",
        "labelHubIdentifierBatchInput",
        "labelHubIdentifierBatchClear",
        "labelHubIdentifierBatchClose",
        "labelHubIdentifierBatchSearch",
    ):
        assert f'id="{element_id}"' in template
    assert "function openIdentifierPopover()" in script
    assert "function closeIdentifierPopover(restoreFocus)" in script
    assert "elements.labelHubIdentifierBatchSearch.addEventListener" in script
    assert ".label-hub-identifier-popover" in styles


def test_sales_role_defaults_to_30d_label_period():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert 'function defaultLabelPeriod(parentId)' in script
    assert 'return Number(parentId) === 1 ? "30d" : "all";' in script
    assert 'var hasExplicitLabelPeriod = query.has("label_period");' in script
    assert 'if (!hasExplicitLabelPeriod) state.label_period = defaultLabelPeriod(state.parent_label_id);' in script
    assert 'state.label_period = defaultLabelPeriod(parentId);' in script


def test_country_diagnostics_use_expandable_role_distribution_without_attention_rail():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "payload.country_role_distribution" in script
    assert "data-diagnostic-country-role" in script
    assert "data-diagnostic-country-detail" in script
    assert "toggleCountryDiagnosticRole" in script
    assert "label-hub-diagnostic-role-row" in styles
    assert "label-hub-diagnostic-child-row" in styles
    assert ".label-hub-diagnostic-role-row.expanded td:first-child::after" in styles
    assert ".label-hub-diagnostic-child-row td:first-child::after" in styles
    assert ".label-hub-diagnostic-child-row td:first-child::before" in styles
    assert ".label-hub-diagnostic-child-row:has(+ .label-hub-diagnostic-role-row)" in styles
    assert ".is-country-role-table td:nth-child(4) i" in styles
    assert "label-hub-diagnostics-attention" not in script
