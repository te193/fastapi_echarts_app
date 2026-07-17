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
    assert 'window.kanbanGrid.makeGrid("labelHubTable"' in script
    assert 'metric_period: state.metric_period' in script
    assert 'analysis_parent_ids: state.analysis_parent_ids' in script
    assert 'sales_trends: serializeCodes(state.sales_trends)' in script
    assert 'daily_sales_bands: serializeCodes(state.daily_sales_bands)' in script
    assert 'margin_bands: serializeCodes(state.margin_bands)' in script
    assert 'class="label-hub-breakdown-rules"' in script
    assert "panel.rules" in script


def test_label_hub_template_exposes_overview_diagnosis_and_breakdowns():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")

    for element_id in (
        "labelHubMetricPeriod", "labelHubScope", "labelHubPopulationSummary", "labelHubCategories", "labelHubBreakdowns",
        "labelHubMeasureTabs", "labelHubDiagnosis", "labelHubMatrixPanel", "labelHubDrawerContent",
    ):
        assert f'id="{element_id}"' in template


def test_label_hub_reuses_sales_role_page_visual_structure():
    template = (ROOT / "app" / "templates" / "label_hub.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="sales-role-page label-hub-page"' in template
    assert 'class="sales-role-topbar label-hub-topbar"' in template
    assert template.count("sales-role-panel label-hub-section-panel") == 3
    assert template.count("label-hub-secondary-panel") == 2
    assert 'body[data-page="label_hub"] .page-shell' in styles
    assert 'class="sales-role-filter-main label-hub-filter-primary"' in template
    assert 'id="labelHubConditionRow" class="label-hub-condition-row" hidden' in template


def test_label_hub_uses_progressive_coverage_and_problem_first_analysis_layout():
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
    for label in ("去重 MSKU", "经营单元", "跨范围 MSKU"):
        assert label in script
    assert "renderCategoryDetail(payload);" in script
    assert ".label-hub-categories { display: grid; grid-template-columns: repeat(4" in label_styles
    assert "font-size: 9px" not in label_styles
    assert ".label-hub-filters .label-hub-filter-primary,\n  .label-hub-categories" in label_styles
    assert ".label-hub-overview-section .sales-role-section-head" in label_styles


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
    assert "?v=20260717" in template


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
    assert "占当前群体" in script
    assert 'data-problem="' in script


def test_label_hub_explains_primary_label_priority_for_aggregated_msku():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")

    assert "aggregation_priority_labels" in script
    assert "跨经营单元按业务优先级只保留一个主标签" in script
    assert "主标签优先级" in script


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
    assert "js/label_hub.js') }}?v=20260717labelloading1" in template


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


def test_sales_role_has_label_hub_return_link():
    script = (ROOT / "app" / "static" / "js" / "sales_role.js").read_text(encoding="utf-8")

    assert 'href = "/label-hub?" + params.toString();' in script
    assert '查看全部标签' in script
