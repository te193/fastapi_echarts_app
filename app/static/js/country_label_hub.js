(function () {
  "use strict";

  var app = window.kanbanApp || {};
  var params = new URLSearchParams(window.location.search);
  var state = {
    data_date: params.get("data_date") || "",
    metric_period: params.get("metric_period") || "30d",
    country_category: params.get("country_category") || "all",
    store: params.get("store") || "all",
    keyword: params.get("keyword") || "",
    conditions: params.get("conditions") || "",
    label_periods: params.get("label_periods") || "",
    analysis_parent_ids: params.get("analysis_parent_ids") || "",
    matrix_parent_id: params.get("matrix_parent_id") || "",
    matrix_compare_parent_id: params.get("matrix_compare_parent_id") || "",
    sales_trends: params.get("sales_trends") || "",
    daily_sales_bands: params.get("daily_sales_bands") || "",
    margin_bands: params.get("margin_bands") || "",
    problem: params.get("problem") || "all",
    page: Math.max(1, Number(params.get("page") || 1)),
    page_size: [20, 50, 100].indexOf(Number(params.get("page_size"))) >= 0 ? Number(params.get("page_size")) : 20,
    table_view: normalizeTableView(params.get("table_view")),
    sort_field: params.get("sort_field") || "problem_priority",
    sort_dir: params.get("sort_dir") || "desc"
  };
  var meta = { categories: [], local_breakdowns: [] };
  var payload = {};
  var measure = "msku_count";
  var activeOverviewParentId = null;
  var keywordTimer = null;
  var linkedSelectInstances = [];
  var elements = {};

  var ISSUE_LABELS = {
    all: "全部链接", problem_product: "问题产品", zero_sales: "日销为 0",
    negative_profit: "订单毛利润为负", low_margin: "低毛利", missing_metrics: "暂无本地经营数据",
    conflict: "标签互斥冲突", site_status_abnormal: "站点状态异常",
    pricing_risk: "定价风险", cross_country_inconsistent: "跨国家标签不一致"
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    ["countryLabelScope", "countryLabelHint", "countryLabelClear", "countryMetricPeriod", "countryLabelPeriod", "countryCategory", "countryStore", "countryKeyword", "countryConditionRow", "countryConditions", "countryKpis", "countryOverview", "countryOverviewDetail", "countryIssues", "countryLabelBreakdowns", "countryMetricBreakdowns", "countryMatrices", "countryTableSummary", "countryTableView", "countryPageSize", "countryDetailTable", "countryPagination", "countryProfileDrawer", "countryProfileContent", "countryProfileClose", "countryRuleDrawer", "countryRuleContent", "countryRuleTitle", "countryRuleClose", "globalLabelHubLink"].forEach(function (id) { elements[id] = document.getElementById(id); });
    setLoading(true);
    bindStaticEvents();
    app.apiGet("/api/country-label-hub/meta").then(function (data) {
      meta = data || meta;
      state.data_date = state.data_date || meta.default_data_date || "";
      normalizeState();
      normalizeAnalysisParents();
      normalizeMatrixParents();
      if (!state.label_periods) applyGlobalLabelPeriod("all");
      renderFilters();
      loadData();
    }).catch(function (error) { setLoading(false); showError(error); });
  }

  function bindStaticEvents() {
    elements.countryLabelClear.addEventListener("click", function () {
      state.metric_period = "30d"; state.country_category = "all"; state.store = "all"; state.keyword = "";
      state.conditions = ""; state.label_periods = ""; state.sales_trends = ""; state.daily_sales_bands = "";
      state.margin_bands = ""; state.problem = "all"; state.analysis_parent_ids = "";
      state.matrix_parent_id = ""; state.matrix_compare_parent_id = ""; state.page = 1;
      normalizeAnalysisParents();
      normalizeMatrixParents();
      applyGlobalLabelPeriod("all");
      renderFilters(); loadData();
    });
    elements.countryMetricPeriod.addEventListener("change", function () { state.metric_period = this.value; refresh(); });
    elements.countryLabelPeriod.addEventListener("change", function () { applyGlobalLabelPeriod(this.value); state.page = 1; renderFilters(); loadData(); });
    elements.countryCategory.addEventListener("change", function () { state.country_category = this.value; state.store = "all"; state.page = 1; renderStoreOptions(); loadData(); });
    elements.countryStore.addEventListener("change", function () { state.store = this.value; refresh(); });
    elements.countryKeyword.addEventListener("input", function () { state.keyword = this.value; clearTimeout(keywordTimer); keywordTimer = setTimeout(refresh, 350); });
    elements.countryPageSize.addEventListener("change", function () { state.page_size = Number(this.value); refresh(); });
    elements.countryTableView.addEventListener("change", function () {
      state.table_view = normalizeTableView(this.value);
      syncUrl();
      renderTable();
    });
    elements.countryProfileClose.addEventListener("click", closeProfile);
    elements.countryRuleClose.addEventListener("click", closeRule);
    elements.countryProfileDrawer.addEventListener("click", function (event) { if (event.target === this) closeProfile(); });
    elements.countryRuleDrawer.addEventListener("click", function (event) { if (event.target === this) closeRule(); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") { closeProfile(); closeRule(); } });
    Array.from(document.querySelectorAll("[data-country-measure]")).forEach(function (button) {
      button.addEventListener("click", function () {
        measure = this.dataset.countryMeasure;
        Array.from(document.querySelectorAll("[data-country-measure]")).forEach(function (item) { item.classList.toggle("active", item === button); });
        renderBreakdowns(); renderMatrices();
      });
    });
  }

  function normalizeState() {
    if ((meta.data_dates || []).indexOf(state.data_date) < 0) state.data_date = meta.default_data_date || "";
    if (["7d", "14d", "30d", "90d"].indexOf(state.metric_period) < 0) state.metric_period = "30d";
    if (state.country_category !== "all" && (meta.country_categories || []).indexOf(state.country_category) < 0) state.country_category = "all";
  }

  function normalizeTableView(value) {
    return ["overview", "labels", "metrics"].indexOf(value) >= 0 ? value : "overview";
  }

  function normalizeAnalysisParents() {
    var available = (meta.categories || []).map(function (category) { return Number(category.id); });
    var selected = unique(String(state.analysis_parent_ids || "").split("|").map(Number).filter(function (id) { return available.indexOf(id) >= 0; }));
    available.forEach(function (id) { if (selected.length < 3 && selected.indexOf(id) < 0) selected.push(id); });
    state.analysis_parent_ids = selected.slice(0, 3).join("|");
  }

  function analysisParentIds() {
    return unique(String(state.analysis_parent_ids || "").split("|").map(Number).filter(Boolean));
  }

  function normalizeMatrixParents() {
    var available = (meta.categories || []).map(function (category) { return Number(category.id); });
    if (!available.length) return;
    var preferredCurrent = available.indexOf(13) >= 0 ? 13 : available[0];
    var current = Number(state.matrix_parent_id);
    if (available.indexOf(current) < 0) current = preferredCurrent;
    var compare = Number(state.matrix_compare_parent_id);
    if (available.indexOf(compare) < 0 || compare === current) {
      compare = available.indexOf(14) >= 0 && current !== 14 ? 14 : available.find(function (id) { return id !== current; });
    }
    state.matrix_parent_id = String(current);
    state.matrix_compare_parent_id = String(compare || "");
    activeOverviewParentId = String(current);
  }

  function renderFilters() {
    fillSelect(elements.countryMetricPeriod, meta.metric_periods || [], state.metric_period, "key", "label");
    renderGlobalLabelPeriod();
    fillSelect(elements.countryCategory, [{ key: "all", label: "全部国家类别" }].concat((meta.country_categories || []).map(function (value) { return { key: value, label: value }; })), state.country_category, "key", "label");
    renderStoreOptions();
    elements.countryKeyword.value = state.keyword;
    elements.countryTableView.value = normalizeTableView(state.table_view);
    elements.countryPageSize.value = String(state.page_size);
    updateSwitchLink();
  }

  function renderStoreOptions() {
    var stores = state.country_category === "all" ? (meta.stores || []) : (((meta.stores_by_country || {})[state.country_category]) || []);
    if (state.store !== "all" && stores.indexOf(state.store) < 0) state.store = "all";
    fillSelect(elements.countryStore, [{ key: "all", label: "全部店铺" }].concat(stores.map(function (value) { return { key: value, label: value }; })), state.store, "key", "label");
  }

  function fillSelect(select, items, selected, key, label) {
    select.innerHTML = items.map(function (item) { var value = String(item[key]); return '<option value="' + escape(value) + '"' + (value === String(selected) ? " selected" : "") + '>' + escape(item[label]) + "</option>"; }).join("");
  }

  function parsePeriods() {
    var values = {};
    String(state.label_periods || "").split(";").forEach(function (group) {
      var pair = group.split(":");
      if (pair.length === 2) values[pair[0]] = pair[1] || "all";
    });
    return values;
  }

  function globalLabelPeriodValue() {
    var values = parsePeriods();
    var multiPeriodCategories = (meta.categories || []).filter(function (category) {
      return categoryPeriods(category).filter(function (period) { return /^\d+d$/.test(period); }).length > 1;
    });
    if (!multiPeriodCategories.length) return "all";
    var selected = unique(multiPeriodCategories.map(function (category) { return values[String(category.id)] || "all"; }));
    if (selected.length === 1) return selected[0];
    var explicitPeriods = selected.filter(function (period) { return period !== "all"; });
    if (explicitPeriods.length !== 1) return "custom";
    var candidate = explicitPeriods[0];
    var compatible = multiPeriodCategories.every(function (category) {
      var value = values[String(category.id)] || "all";
      return value === candidate || (value === "all" && categoryPeriods(category).indexOf(candidate) < 0);
    });
    return compatible ? candidate : "custom";
  }

  function renderGlobalLabelPeriod() {
    var periods = unique((meta.categories || []).reduce(function (result, category) {
      return result.concat(categoryPeriods(category).filter(function (period) { return /^\d+d$/.test(period); }));
    }, [])).sort(function (left, right) { return Number(left.slice(0, -1)) - Number(right.slice(0, -1)); });
    var selected = globalLabelPeriodValue();
    var options = [{ key: "all", label: "全部周期" }].concat(periods.map(function (period) { return { key: period, label: period }; }));
    if (selected === "custom") options.push({ key: "custom", label: "自定义周期" });
    fillSelect(elements.countryLabelPeriod, options, selected, "key", "label");
  }

  function applyGlobalLabelPeriod(period) {
    if (period === "custom") return;
    var values = {};
    (meta.categories || []).forEach(function (category) {
      var available = categoryPeriods(category);
      values[String(category.id)] = period !== "all" && available.indexOf(period) >= 0 ? period : "all";
    });
    state.label_periods = Object.keys(values).sort(function (a, b) { return Number(a) - Number(b); }).map(function (parent) { return parent + ":" + values[parent]; }).join(";");
  }

  function refresh() { state.page = 1; loadData(); }

  function loadData() {
    setLoading(true); syncUrl();
    app.apiGet("/api/country-label-hub", state).then(function (data) {
      payload = data || {};
      renderAll();
      setLoading(false);
    }).catch(function (error) { setLoading(false); showError(error); });
  }

  function setLoading(active) {
    var main = document.querySelector(".main-content");
    if (main) {
      main.classList.toggle("page-loading", active);
      main.setAttribute("aria-busy", active ? "true" : "false");
    }
    document.body.classList.toggle("is-data-loading", active);
    if (active) elements.countryLabelHint.textContent = "正在汇总国家标签与本地经营指标…";
  }

  function syncUrl() {
    var query = new URLSearchParams();
    Object.keys(state).forEach(function (key) {
      var value = state[key];
      if (value !== "" && value !== "all" && value !== 1 && !(key === "page_size" && value === 20) && !(key === "sort_field" && value === "problem_priority") && !(key === "sort_dir" && value === "desc")) query.set(key, String(value));
    });
    window.history.replaceState(null, "", window.location.pathname + (query.toString() ? "?" + query.toString() : ""));
    updateSwitchLink();
  }

  function updateSwitchLink() {
    var query = new URLSearchParams();
    [["metric_period", state.metric_period], ["country_category", state.country_category], ["store", state.store], ["keyword", state.keyword]].forEach(function (pair) { if (pair[1] && pair[1] !== "all") query.set(pair[0], pair[1]); });
    elements.globalLabelHubLink.href = "/label-hub" + (query.toString() ? "?" + query.toString() : "");
  }

  function renderAll() {
    renderScope(); renderConditions(); renderKpis();
    renderOverview(); renderIssues(); renderBreakdowns(); renderMatrices(); renderTable();
  }

  function renderScope() {
    var scope = payload.scope || {};
    var windowData = scope.metric_window || {};
    var status = scope.local_metrics_status === "available" ? "本地指标可用" : (scope.local_metrics_status === "no_snapshot" ? "无本地快照" : "本地指标暂不可用");
    elements.countryLabelScope.innerHTML = '<span>标签数据 ' + escape(scope.label_data_date || "-") + '</span><span>经营指标 ' + escape(windowData.period_start || "-") + " 至 " + escape(windowData.period_end || "-") + '</span><span class="' + (scope.local_metrics_status === "available" ? "is-ok" : "is-warning") + '">' + status + "</span>";
    elements.countryLabelHint.textContent = Number(windowData.lag_days || 0) > 0 ? "本地经营快照较标签日期滞后 " + formatNumber(windowData.lag_days) + " 天" : "标签与经营指标使用不晚于标签日期的最近快照";
  }

  function renderKpis() {
    var kpi = payload.kpis || {};
    var items = [
      ["国家", kpi.country_count, "个"], ["国家类别", kpi.country_category_count, "个"],
      ["店铺", kpi.store_count, "个"], ["链接", kpi.business_unit_count, "个"],
      ["指标匹配率", formatPercent(kpi.metric_coverage_rate), ""],
      ["销售额", currency(kpi.sales_amount), ""], ["订单毛利润", currency(kpi.order_gross_profit), ""],
      ["订单毛利率", formatPercent(kpi.order_gross_margin), ""]
    ];
    elements.countryKpis.innerHTML = items.map(function (item) { return '<article><span>' + item[0] + '</span><strong>' + item[1] + (item[2] ? '<small>' + item[2] + "</small>" : "") + "</strong></article>"; }).join("");
  }

  function renderOverview() {
    var cards = payload.overview || [];
    if (!cards.length) {
      elements.countryOverview.innerHTML = empty("当前暂无国家标签分类");
      elements.countryOverviewDetail.innerHTML = "";
      return;
    }
    if (!cards.some(function (item) { return String(item.id) === String(activeOverviewParentId); })) {
      normalizeMatrixParents();
      activeOverviewParentId = state.matrix_parent_id || cards[0].id;
    }
    elements.countryOverview.innerHTML = cards.map(function (category) {
      var active = String(category.id) === String(activeOverviewParentId) ? " active" : "";
      var stateText = { available: "可分析", developing: "开发中", disabled: "未启用" }[category.state] || "暂无数据";
      var periods = categoryPeriods(category);
      var flags = [];
      if (periods.length > 1) flags.push("多周期");
      if (category.mutual_exclusion) flags.push("互斥配置");
      return '<article class="label-hub-category-card ' + escape(category.state || "") + active + '"><button type="button" class="label-hub-category-head" data-country-overview-parent="' + category.id + '" aria-pressed="' + (active ? "true" : "false") + '"><span><b>' + escape(category.label) + '</b><small>' + stateText + '</small></span><strong>' + formatNumber(category.business_unit_count) + '<small> 链接</small></strong></button><div class="label-hub-coverage"><i style="width:' + Math.round(Math.max(0, Number(category.coverage_rate || 0)) * 100) + '%"></i></div><div class="label-hub-category-meta"><span>覆盖 ' + formatPercent(category.coverage_rate) + '</span><span>国家 ' + formatNumber(category.country_count) + '</span></div><div class="label-hub-category-foot"><span>' + escape(flags.join(" · ") || "单一口径") + '</span><button type="button" class="label-hub-rule-link" data-rule-parent="' + category.id + '">查看划分规则</button></div></article>';
    }).join("");
    Array.from(elements.countryOverview.querySelectorAll("[data-country-overview-parent]")).forEach(function (button) {
      button.addEventListener("click", function () {
        activeOverviewParentId = this.dataset.countryOverviewParent;
        state.matrix_parent_id = String(activeOverviewParentId);
        normalizeMatrixParents();
        syncUrl();
        renderOverview();
        renderMatrices();
        renderTable();
      });
    });
    bindDynamicControls(elements.countryOverview);
    renderOverviewDetail(cards.find(function (item) { return String(item.id) === String(activeOverviewParentId); }));
  }

  function renderOverviewDetail(category) {
    if (!category) { elements.countryOverviewDetail.innerHTML = empty("当前暂无可分析标签"); return; }
    var periods = categoryPeriods(category);
    var periodControl = periods.length > 1 ? '<label class="country-period-control"><span>标签周期</span><select data-period-parent="' + category.id + '"><option value="all"' + (category.selected_period === "all" ? " selected" : "") + '>全部周期</option>' + periods.map(function (period) { return '<option value="' + escape(period) + '"' + (period === category.selected_period ? " selected" : "") + '>' + escape(period) + "</option>"; }).join("") + "</select></label>" : "";
    var children = (category.buckets || []).map(function (bucket) {
      var selected = conditionSelected(category.id, bucket.id);
      return '<button type="button" class="label-hub-child' + (selected ? " selected" : "") + '" data-label-parent="' + category.id + '" data-label-child="' + bucket.id + '" aria-pressed="' + selected + '"><span><b>' + escape(bucket.label) + '</b><small>' + formatPercent(bucket.share) + '</small></span><strong>' + formatNumber(bucket.business_unit_count) + '<small>链接</small></strong></button>';
    }).join("");
    var periodText = periods.join(" / ") || "无周期";
    var ruleText = category.mutual_exclusion ? "同周期互斥" : "允许标签共现";
    elements.countryOverviewDetail.innerHTML = '<header><div><span class="section-kicker">当前分析标签</span><h3>' + escape(category.label) + '</h3></div><div class="country-category-detail-tools"><p>' + escape(periodText) + ' · ' + escape(ruleText) + '</p>' + periodControl + '</div></header><div class="label-hub-children">' + (children || '<div class="empty-state compact">暂无标签事实</div>') + '</div>';
    bindDynamicControls(elements.countryOverviewDetail);
  }

  function renderIssues() {
    var counts = payload.issue_counts || {};
    elements.countryIssues.innerHTML = Object.keys(ISSUE_LABELS).map(function (key) { return '<button type="button" class="country-issue-card label-hub-issue' + (state.problem === key ? " active" : "") + '" data-problem="' + key + '"><span>' + ISSUE_LABELS[key] + '</span><strong>' + formatNumber(counts[key]) + '</strong><small>链接</small></button>'; }).join("");
    Array.from(elements.countryIssues.querySelectorAll("[data-problem]")).forEach(function (button) { button.addEventListener("click", function () { state.problem = this.dataset.problem; refresh(); }); });
  }

  function renderBreakdowns() {
    destroyLinkedSelects();
    var remotePanels = payload.label_breakdowns || [];
    var remoteByParent = {};
    remotePanels.forEach(function (panel) { remoteByParent[String(panel.parent_id)] = panel; });
    elements.countryLabelBreakdowns.innerHTML = analysisParentIds().map(function (parentId, slot) {
      var panel = remoteByParent[String(parentId)];
      return panel ? renderBreakdownCard(panel, slot) : "";
    }).join("");
    elements.countryMetricBreakdowns.innerHTML = (payload.metric_breakdowns || []).map(function (panel) { return renderBreakdownCard(panel, -1); }).join("");
    bindDynamicControls(elements.countryLabelBreakdowns); bindDynamicControls(elements.countryMetricBreakdowns);
    initLinkedSelects();
  }

  function renderBreakdownCard(panel, analysisSlot) {
    var buckets = panel.buckets || [];
    var totalMeasure = buckets.reduce(function (sum, item) { return sum + Math.abs(Number(item[measure] || 0)); }, 0) || 1;
    var segments = buckets.map(function (bucket, index) { var width = measure === "msku_count" ? Number(bucket.share || 0) * 100 : Math.abs(Number(bucket[measure] || 0)) / totalMeasure * 100; return '<i class="segment-' + (index % 6) + '" style="width:' + width.toFixed(2) + '%"></i>'; }).join("");
    var bars = buckets.map(function (bucket, index) {
      var selected = panel.source === "remote_label" ? conditionSelected(panel.parent_id, bucket.id) : localSelected(panel.key, bucket.key);
      var attrs = panel.source === "remote_label" ? 'data-label-parent="' + panel.parent_id + '" data-label-child="' + bucket.id + '"' : 'data-local-key="' + panel.key + '" data-local-value="' + escape(bucket.key) + '"';
      var selectedBadge = selected ? '<i class="country-breakdown-selected">已选</i>' : "";
      return '<button type="button" class="country-breakdown-row' + (selected ? " selected" : "") + '" ' + attrs + ' aria-pressed="' + selected + '" title="点击' + (selected ? "取消" : "加入") + '联动筛选"><i class="dot segment-' + (index % 6) + '"></i><span><b>' + escape(bucket.label) + selectedBadge + '</b><small>占当前群体 ' + formatPercent(bucket.share) + '</small></span><strong>' + displayMeasure(bucket) + '</strong><em class="' + negativeClass(bucket.order_gross_profit) + '">毛利 ' + currency(bucket.order_gross_profit) + "</em></button>";
    }).join("");
    var interactionHint = panel.source === "remote_label" ? " · 点击标签联动" : " · 点击分类联动";
    var selectors = "";
    if (panel.source === "remote_label" && analysisSlot >= 0) {
      var selectedParents = analysisParentIds();
      var usedParents = selectedParents.filter(function (_, slot) { return slot !== analysisSlot; });
      var dimensionOptions = (meta.categories || []).filter(function (category) { return Number(category.id) === Number(panel.parent_id) || usedParents.indexOf(Number(category.id)) < 0; });
      var dimensionHtml = dimensionOptions.map(function (category) { return '<option value="' + category.id + '"' + (Number(category.id) === Number(panel.parent_id) ? " selected" : "") + '>' + escape(category.label) + '</option>'; }).join("");
      var category = categoryById(panel.parent_id) || { children: [] };
      var periods = categoryPeriods(category).sort(function (left, right) { return Number(left.replace(/\D/g, "") || 9999) - Number(right.replace(/\D/g, "") || 9999); });
      var periodHtml = '<option value="all"' + (panel.selected_period === "all" ? " selected" : "") + '>全部周期</option>' + periods.map(function (period) { return '<option value="' + escape(period) + '"' + (period === panel.selected_period ? " selected" : "") + '>' + escape(period) + '</option>'; }).join("");
      selectors = '<div class="label-hub-card-selectors"><label class="label-hub-dimension-select"><span>联动维度</span><select aria-label="切换联动维度" data-country-analysis-slot="' + analysisSlot + '">' + dimensionHtml + '</select></label><label class="label-hub-period-select"><span>标签周期</span><select aria-label="切换' + escape(panel.label) + '标签周期" data-period-parent="' + panel.parent_id + '">' + periodHtml + '</select></label></div>';
    }
    return '<article class="country-breakdown-card label-hub-breakdown-card"><header><div><span class="label-hub-source ' + panel.source + '">' + (panel.source === "remote_label" ? "远端标签" : "本地经营") + '</span><h3>' + escape(panel.label) + '</h3><small>分析口径 ' + formatNumber(panel.business_unit_count) + ' 链接' + (panel.selected_period ? " · " + escape(panel.selected_period) : "") + interactionHint + '</small></div>' + selectors + '</header><div class="country-composition">' + segments + '</div><div class="country-breakdown-rows">' + bars + "</div></article>";
  }

  function destroyLinkedSelects() {
    linkedSelectInstances.forEach(function (instance) { if (instance && instance.destroy) instance.destroy(); });
    linkedSelectInstances = [];
  }

  function initLinkedSelects() {
    if (!window.SlimSelect) return;
    Array.from(elements.countryLabelBreakdowns.querySelectorAll("[data-country-analysis-slot], [data-period-parent]")).forEach(function (select) {
      linkedSelectInstances.push(new window.SlimSelect({
        select: select,
        settings: { showSearch: false, modal: "off", contentPosition: "absolute", openPosition: "auto" }
      }));
    });
  }

  function renderMatrices() {
    normalizeMatrixParents();
    var matrix = selectedMatrix(Number(state.matrix_parent_id), Number(state.matrix_compare_parent_id));
    if (!matrix || !(matrix.rows || []).length || !(matrix.columns || []).length) {
      elements.countryMatrices.innerHTML = '<article class="country-matrix-card">' + empty("当前暂无可用关系数据") + "</article>";
      return;
    }
    var values = (matrix.cells || []).map(function (cell) { return Math.abs(Number(matrixValue(cell))); });
    var max = Math.max.apply(null, values.concat([1]));
    var cells = {}; (matrix.cells || []).forEach(function (cell) { cells[cell.row_id + "|" + cell.col_id] = cell; });
    var compareOptions = (meta.categories || []).filter(function (category) { return Number(category.id) !== Number(state.matrix_parent_id); }).map(function (category) {
      return '<option value="' + category.id + '"' + (Number(category.id) === Number(state.matrix_compare_parent_id) ? " selected" : "") + '>' + escape(category.label) + "</option>";
    }).join("");
    var currentCategory = categoryById(state.matrix_parent_id) || { children: [] };
    var currentPeriods = categoryPeriods(currentCategory);
    var periodOptions = '<option value="all"' + (matrix.row_period === "all" ? " selected" : "") + '>全部周期</option>' + currentPeriods.map(function (period) {
      return '<option value="' + escape(period) + '"' + (String(period) === String(matrix.row_period) ? " selected" : "") + '>' + escape(period) + "</option>";
    }).join("");
    var legend = '<div class="country-matrix-legend-scale"><span>' + (measure === "msku_count" ? "链接数" : (measure === "sales_amount" ? "销售额" : "毛利润")) + '</span><small>低</small><i style="--heat:.08"></i><i style="--heat:.25"></i><i style="--heat:.45"></i><i style="--heat:.7"></i><i style="--heat:1"></i><small>高</small></div>';
    var controls = '<div class="country-matrix-controls"><label><span>标签周期</span><select data-country-matrix-period>' + periodOptions + '</select></label><label><span>对比大类</span><select data-country-matrix-compare>' + compareOptions + "</select></label>" + legend + "</div>";
    var grid = '<div class="country-matrix-table" style="grid-template-columns:120px repeat(' + matrix.columns.length + ', minmax(96px, 1fr))"><span></span>' + matrix.columns.map(function (item) { return '<strong>' + escape(item.label) + "</strong>"; }).join("");
    matrix.rows.forEach(function (row) { grid += '<strong>' + escape(row.label) + "</strong>"; matrix.columns.forEach(function (column) { var cell = cells[row.id + "|" + column.id] || { count: 0 }; var intensity = Math.abs(Number(matrixValue(cell))) / max; grid += '<button type="button" style="--heat:' + intensity.toFixed(3) + '" data-matrix-row-parent="' + matrix.row_parent_id + '" data-matrix-row="' + row.id + '" data-matrix-col-parent="' + matrix.col_parent_id + '" data-matrix-col="' + column.id + '"><b>' + displayMatrix(cell) + '</b><small>' + formatNumber(cell.count) + " 链接</small></button>"; }); });
    elements.countryMatrices.innerHTML = '<article class="country-matrix-card country-matrix-primary"><header><div><h3>' + escape(matrix.row_label) + ' × ' + escape(matrix.col_label) + '</h3><p>' + escape(matrix.row_period || "全部周期") + ' / ' + escape(matrix.col_period || "全部周期") + '</p></div>' + controls + '</header><div class="country-matrix-scroll">' + grid + "</div></div></article>";
    var compareSelect = elements.countryMatrices.querySelector("[data-country-matrix-compare]");
    if (compareSelect) compareSelect.addEventListener("change", function () { state.matrix_compare_parent_id = this.value; syncUrl(); renderMatrices(); });
    var periodSelect = elements.countryMatrices.querySelector("[data-country-matrix-period]");
    if (periodSelect) periodSelect.addEventListener("change", function () { setPeriod(state.matrix_parent_id, this.value); renderGlobalLabelPeriod(); refresh(); });
    Array.from(elements.countryMatrices.querySelectorAll("[data-matrix-row]")).forEach(function (button) { button.addEventListener("click", function () { setCondition(this.dataset.matrixRowParent, this.dataset.matrixRow, true); setCondition(this.dataset.matrixColParent, this.dataset.matrixCol, true); refresh(); }); });
  }

  function selectedMatrix(rowParent, colParent) {
    var matrices = payload.matrices || [];
    var direct = matrices.find(function (matrix) { return Number(matrix.row_parent_id) === rowParent && Number(matrix.col_parent_id) === colParent; });
    if (direct) return direct;
    var reverse = matrices.find(function (matrix) { return Number(matrix.row_parent_id) === colParent && Number(matrix.col_parent_id) === rowParent; });
    if (!reverse) return null;
    return {
      row_parent_id: reverse.col_parent_id, row_label: reverse.col_label, row_period: reverse.col_period,
      col_parent_id: reverse.row_parent_id, col_label: reverse.row_label, col_period: reverse.row_period,
      rows: reverse.columns || [], columns: reverse.rows || [],
      cells: (reverse.cells || []).map(function (cell) { return Object.assign({}, cell, { row_id: cell.col_id, col_id: cell.row_id }); })
    };
  }

  function renderTable() {
    elements.countryTableSummary.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + formatNumber(payload.total) + " 条";
    window.kanbanGrid.makeGrid("countryDetailTable", { rowData: payload.rows || [], domLayout: "normal", rowHeight: 52, headerHeight: 50, overlayNoRowsTemplate: '<span class="ag-empty-copy">当前联动条件下暂无国家链接</span>', columnDefs: tableColumns(state.table_view), onRowClicked: function (event) { if (event.data) openProfile(event.data); } });
    elements.countryPagination.innerHTML = '<button type="button" data-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><span>第 ' + payload.page + " / " + payload.total_pages + ' 页</span><button type="button" data-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + ">下一页</button>";
    Array.from(elements.countryPagination.querySelectorAll("[data-page]")).forEach(function (button) { button.addEventListener("click", function () { if (!this.disabled) { state.page = Number(this.dataset.page); loadData(); } }); });
  }

  function tableColumns(view) {
    function amount(name, field, width) { return { headerName: name, field: field, width: width, cellClass: function (p) { return "ag-grid-number-cell " + negativeClass(p.value); }, valueFormatter: function (p) { return p.value == null ? "暂无" : window.kanbanGrid.compactAmount(p.value); } }; }
    function number(name, field, width, digits) { return { headerName: name, field: field, width: width, cellClass: "ag-grid-number-cell", valueFormatter: function (p) { return p.value == null ? "暂无" : window.kanbanGrid.number(p.value, digits || 0); } }; }
    function marginRate(name, field, width) { return { headerName: name, field: field, width: width, cellClass: function (p) { var current = Number(p.value || 0); return "ag-grid-number-cell " + (current < 0.05 ? "label-hub-risk-value" : (current >= 0.15 ? "label-hub-healthy-value" : "")); }, valueFormatter: function (p) { return p.value == null ? "暂无" : window.kanbanGrid.percent(p.value, 1); } }; }
    function rate(name, field, width) { return { headerName: name, field: field, width: width, cellClass: "ag-grid-number-cell", valueFormatter: function (p) { return p.value == null ? "暂无" : window.kanbanGrid.percent(p.value, 1); } }; }
    function text(name, field, width) { return { headerName: name, field: field, width: width, tooltipField: field, cellClass: "label-text-cell" }; }
    var identity = [
      { headerName: "国家", field: "country", pinned: "left", width: 90 },
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 100 },
      { headerName: "店铺", field: "store", pinned: "left", width: 110 },
      { headerName: "MSKU", field: "msku", pinned: "left", width: 125, cellRenderer: function (p) { return window.kanbanGrid.textCell(p.value, true); } }
    ];
    var currentLabel = { headerName: "当前标签", field: "current_label", width: 150, tooltipValueGetter: function (p) { return currentCountryLabel(p.data); }, valueGetter: function (p) { return currentCountryLabel(p.data); }, cellClass: "label-text-cell" };
    var labelProfile = { headerName: "标签画像", field: "label_summary", width: 165, tooltipField: "label_summary", cellClass: "label-summary-cell", cellRenderer: renderCountryLabelSummaryCell };
    if (view === "labels") return identity.concat([currentLabel, labelProfile,
      text("定价标签", "price_label", 115), text("站点状态", "site_status_label", 115),
      text("国家销售角色", "country_sales_role_label", 140), text("站点生命周期", "site_lifecycle_label", 130),
      { headerName: "标签冲突", field: "conflict", width: 105, cellRenderer: renderCountryConflictCell },
      { headerName: "指标状态", field: "data_status", width: 125, cellRenderer: renderCountryMetricStatusCell }
    ]);
    if (view === "metrics") return identity.concat([
      { headerName: "动销趋势", field: "sales_trend", width: 135, cellRenderer: renderCountryTrendCell },
      number("日均销量", "daily_sales", 105, 2), number(metricPeriodLabel() + "销量", "sales_qty", 105),
      amount(metricPeriodLabel() + "销售额", "sales_amount", 120), amount("订单毛利润", "order_gross_profit", 125),
      marginRate("订单毛利率", "order_gross_margin", 115), number("期末库存", "ending_inventory_qty", 105),
      amount("广告花费", "ad_spend", 110), rate("ACOS", "acos", 90), rate("TACOS", "tacos", 90),
      number("退货数量", "return_count", 105), amount("净销售额", "net_amount", 115)
    ]);
    return identity.concat([currentLabel, labelProfile,
      { headerName: "问题提示", field: "issue_codes", width: 190, sortable: false, filter: false, tooltipValueGetter: function (p) { return countryIssueCodes(p.data).map(issueLabel).join(" / ") || "当前未命中问题条件"; }, cellRenderer: renderCountryIssueCell },
      { headerName: "动销趋势", field: "sales_trend", width: 135, cellRenderer: renderCountryTrendCell },
      number("日均销量", "daily_sales", 105, 2), number(metricPeriodLabel() + "销量", "sales_qty", 105),
      amount(metricPeriodLabel() + "销售额", "sales_amount", 120), amount("订单毛利润", "order_gross_profit", 125),
      marginRate("订单毛利率", "order_gross_margin", 115)
    ]);
  }

  function currentCountryLabel(row) {
    var field = { "4": "price_label", "7": "site_status_label", "13": "country_sales_role_label", "14": "site_lifecycle_label" }[String(activeOverviewParentId || state.matrix_parent_id || "13")];
    return (row && field && row[field]) || "未命中";
  }

  function renderCountryLabelSummaryCell(params) {
    var labels = (params.data && params.data.labels) || [];
    var parents = {}, children = {};
    labels.forEach(function (item) { parents[String(item.parent_id)] = true; children[String(item.id)] = true; });
    return '<span class="label-summary-compact"><b>' + Object.keys(parents).length + ' 个分类</b><small>' + Object.keys(children).length + ' 个标签 · 点击查看</small></span>';
  }

  function countryIssueCodes(row) {
    var selected = (row && row.issue_codes) || [];
    return ["negative_profit", "problem_product", "zero_sales", "low_margin", "missing_metrics", "conflict", "site_status_abnormal", "pricing_risk", "cross_country_inconsistent"].filter(function (code) { return selected.indexOf(code) >= 0; });
  }

  function issueLabel(code) { return ISSUE_LABELS[code] || code; }

  function renderCountryIssueCell(params) {
    var codes = countryIssueCodes(params.data);
    if (!codes.length) return '<span class="label-hub-issue-pill is-clear">暂无问题</span>';
    var visible = codes.slice(0, 2).map(function (code) { return '<span class="label-hub-issue-pill issue-' + escape(code) + '">' + escape(issueLabel(code)) + '</span>'; }).join("");
    if (codes.length > 2) visible += '<span class="label-hub-issue-more">+' + (codes.length - 2) + '</span>';
    return '<span class="label-hub-issue-cell">' + visible + '</span>';
  }

  function renderCountryTrendCell(params) {
    var code = String((params.data && params.data.sales_trend_code) || "insufficient");
    var ratio = params.data && params.data.sales_trend_ratio;
    var ratioText = ratio === null || ratio === undefined ? "" : '<small>' + (Number(ratio) > 0 ? "+" : "") + formatPercent(ratio) + '</small>';
    return '<span class="label-hub-trend-pill trend-' + escape(code) + '"><b>' + escape(params.value || "暂无趋势数据") + '</b>' + ratioText + '</span>';
  }

  function renderCountryMetricStatusCell(params) {
    var current = String(params.value || "");
    var tone = current === "本地指标可用" ? "available" : (current === "暂无本地经营数据" ? "missing" : "unavailable");
    var label = current === "本地指标可用" ? "指标可用" : (current === "暂无本地经营数据" ? "指标缺失" : current || "状态未知");
    return '<span class="label-hub-metric-status is-' + tone + '">' + escape(label) + '</span>';
  }

  function renderCountryConflictCell(params) {
    return params.value ? '<span class="label-hub-metric-status is-risk">存在冲突</span>' : '<span class="label-hub-metric-status is-available">无冲突</span>';
  }

  function metricPeriodLabel() { return String(state.metric_period || "30d").replace("d", "天"); }

  function bindDynamicControls(host) {
    Array.from(host.querySelectorAll("[data-label-parent]")).forEach(function (button) { button.addEventListener("click", function () { toggleCondition(this.dataset.labelParent, this.dataset.labelChild); refresh(); }); });
    Array.from(host.querySelectorAll("[data-local-key]")).forEach(function (button) { button.addEventListener("click", function () { toggleLocal(this.dataset.localKey, this.dataset.localValue); refresh(); }); });
    Array.from(host.querySelectorAll("[data-period-parent]")).forEach(function (select) { select.addEventListener("change", function () { setPeriod(this.dataset.periodParent, this.value); renderGlobalLabelPeriod(); refresh(); }); });
    Array.from(host.querySelectorAll("[data-country-analysis-slot]")).forEach(function (select) { select.addEventListener("change", function () {
      var selected = analysisParentIds();
      selected[Number(this.dataset.countryAnalysisSlot)] = Number(this.value);
      state.analysis_parent_ids = unique(selected).slice(0, 3).join("|");
      state.page = 1;
      syncUrl();
      window.setTimeout(renderBreakdowns, 0);
    }); });
    Array.from(host.querySelectorAll("[data-rule-parent]")).forEach(function (button) { button.addEventListener("click", function () { openRule(this.dataset.ruleParent); }); });
  }

  function renderConditions() {
    var chips = [];
    var conditions = parseConditions();
    Object.keys(conditions).forEach(function (parent) { conditions[parent].forEach(function (child) { var category = categoryById(parent); var detail = ((category || {}).children || []).find(function (item) { return String(item.id) === String(child); }); chips.push(chip((category || {}).label + "：" + ((detail || {}).label || child), 'data-remove-parent="' + parent + '" data-remove-child="' + child + '"')); }); });
    [["sales_trends", "sales_trend", "销售趋势"], ["daily_sales_bands", "daily_sales_band", "日销段"], ["margin_bands", "margin_band", "毛利段"]].forEach(function (item) { splitCodes(state[item[0]]).forEach(function (code) { chips.push(chip(item[2] + "：" + localOptionLabel(item[1], code), 'data-remove-local-key="' + item[1] + '" data-remove-local-value="' + code + '"')); }); });
    if (state.problem !== "all") chips.push(chip("问题队列：" + ISSUE_LABELS[state.problem], "data-remove-problem"));
    elements.countryConditionRow.hidden = !chips.length;
    elements.countryConditions.innerHTML = chips.join("") + (chips.length ? '<button type="button" class="label-hub-clear-linked" data-clear-linked>清空联动</button>' : "");
    Array.from(elements.countryConditions.querySelectorAll("[data-remove-parent]")).forEach(function (button) { button.addEventListener("click", function () { toggleCondition(this.dataset.removeParent, this.dataset.removeChild); refresh(); }); });
    Array.from(elements.countryConditions.querySelectorAll("[data-remove-local-key]")).forEach(function (button) { button.addEventListener("click", function () { toggleLocal(this.dataset.removeLocalKey, this.dataset.removeLocalValue); refresh(); }); });
    var problem = elements.countryConditions.querySelector("[data-remove-problem]"); if (problem) problem.addEventListener("click", function () { state.problem = "all"; refresh(); });
    var clear = elements.countryConditions.querySelector("[data-clear-linked]"); if (clear) clear.addEventListener("click", function () { state.conditions = ""; state.sales_trends = ""; state.daily_sales_bands = ""; state.margin_bands = ""; state.problem = "all"; refresh(); });
  }

  function openProfile(row) {
    elements.countryProfileDrawer.hidden = false;
    elements.countryProfileContent.innerHTML = empty("正在加载国家经营画像…");
    app.apiGet("/api/country-label-hub/msku", { data_date: state.data_date, metric_period: state.metric_period, country: row.country, country_category: row.country_category, store: row.store, msku: row.msku }).then(function (profile) {
      var identity = profile.identity || {}, status = profile.data_status || {}, metric = profile.metric_profile || {};
      var tags = (profile.tag_profile || {}).labels || [];
      var tagGroups = profileLabelGroups(tags);
      var tagHtml = tagGroups.map(renderProfileTagGroup).join("") || empty("暂无国家口径标签");
      var fields = [["销量", metric.sales_qty], ["日销量", metric.daily_sales], ["销售额", metric.sales_amount, "money"], ["订单毛利润", metric.order_gross_profit, "money"], ["订单毛利率", metric.order_gross_margin, "rate"], ["结算毛利润", metric.settlement_gross_profit, "money"], ["广告花费", metric.ad_spend, "money"], ["广告销售额", metric.ad_sales, "money"], ["ACOS", metric.acos, "rate"], ["TACOS", metric.tacos, "rate"], ["退货数量", metric.return_count], ["退货金额", metric.return_amount, "money"], ["净销售额", metric.net_amount, "money"], ["期末库存", metric.ending_inventory_qty]];
      var metrics = fields.map(function (item, index) { return '<div class="' + (index < 5 ? "is-primary" : "") + '"><span>' + item[0] + '</span><strong>' + value(item[1], item[2]) + "</strong></div>"; }).join("");
      var currentSignatures = profileLabelSignatures(tagGroups);
      var otherCountries = profile.cross_country_profile || [];
      var others = renderCrossCountryComparison(otherCountries, currentSignatures);
      var windowData = status.metric_window || {};
      elements.countryProfileContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">国家标签画像</p><h2 id="countryProfileTitle">' + escape(identity.msku) + '</h2><p class="country-profile-identity">' + escape(identity.country) + "<span>·</span>" + escape(identity.country_category) + "<span>·</span>" + escape(identity.store) + '</p><div class="country-profile-scope"><span>标签 ' + escape(identity.data_date) + '</span><span>经营 ' + escape(windowData.period_start || "-") + " 至 " + escape(windowData.period_end || "-") + '</span><span class="' + (status.has_local_metric ? "is-ok" : "is-warning") + '">' + (status.has_local_metric ? "本地指标已匹配" : "暂无本地经营数据") + '</span></div></div><section class="country-profile-section"><div class="country-profile-section-head"><div><h3>国家口径标签</h3><p>远端原始标签事实，按标签大类集中展示。</p></div><strong>' + formatNumber(tags.length) + ' 项</strong></div><div class="country-profile-tag-groups">' + tagHtml + '</div></section><section class="country-profile-section"><div class="country-profile-section-head"><div><h3>本地经营画像</h3><p>' + escape(state.metric_period.replace("d", " 天")) + '经营周期，本地快照指标。</p></div></div><div class="label-hub-profile-metrics">' + metrics + '</div></section><section class="country-profile-section"><div class="country-profile-section-head"><div><h3>同一 MSKU 的其他国家表现</h3><p>一行一个国家，直接横向比较标签差异与经营结果。</p></div><strong>' + formatNumber(otherCountries.length) + ' 个国家</strong></div>' + (others || empty("该 MSKU 暂无其他国家链接")) + "</section>";
    }).catch(function (error) { elements.countryProfileContent.innerHTML = empty("画像加载失败：" + ((error && error.message) || "请稍后重试")); });
  }

  function profileLabelGroups(labels) {
    var groups = {};
    (labels || []).forEach(function (item) {
      var key = String(item.parent_id || item.parent_label || "unknown");
      if (!groups[key]) groups[key] = { id: Number(item.parent_id || 0), label: item.parent_label || "未分类标签", items: [] };
      groups[key].items.push(item);
    });
    return Object.keys(groups).map(function (key) { return groups[key]; }).sort(function (a, b) { return a.id - b.id; });
  }

  function renderProfileTagGroup(group) {
    var rows = group.items.map(function (item) {
      return '<div class="country-profile-tag-row"><div class="country-profile-tag-main"><strong>' + escape(item.label || "未命名标签") + '</strong><span>' + escape(item.period || "无周期") + '</span></div><p>' + escape(item.rule || item.definition || "暂无规则说明") + '</p><div class="country-profile-tag-owner"><span>负责人</span><b>' + escape(item.owner || "未配置") + "</b></div></div>";
    }).join("");
    return '<article class="country-profile-tag-group"><header><div><span>远端标签</span><h4>' + escape(group.label) + '</h4></div><strong>' + formatNumber(group.items.length) + ' 项</strong></header><div>' + rows + "</div></article>";
  }

  function profileLabelSignatures(groups) {
    var signatures = {};
    (groups || []).forEach(function (group) {
      signatures[String(group.id || group.label)] = group.items.map(function (item) { return String(item.label || "") + "@" + String(item.period || ""); }).sort().join("|");
    });
    return signatures;
  }

  function renderCrossCountryComparison(items, currentSignatures) {
    if (!items.length) return "";
    var parentMap = {};
    var prepared = items.map(function (item) {
      var groups = profileLabelGroups(item.labels || []);
      groups.forEach(function (group) { parentMap[String(group.id || group.label)] = { id: group.id, label: group.label }; });
      return { item: item, groups: groups, signatures: profileLabelSignatures(groups) };
    });
    var parents = Object.keys(parentMap).map(function (key) { return parentMap[key]; }).sort(function (a, b) { return a.id - b.id; });
    var head = '<tr><th>国家 / 店铺</th>' + parents.map(function (parent) { return '<th>' + escape(parent.label) + '</th>'; }).join("") + '<th>销售额</th><th>毛利润</th><th>毛利率</th></tr>';
    var rows = prepared.map(function (entry) {
      var groupsById = {};
      entry.groups.forEach(function (group) { groupsById[String(group.id || group.label)] = group; });
      var labelCells = parents.map(function (parent) {
        var key = String(parent.id || parent.label);
        var group = groupsById[key];
        if (!group) return '<td><div class="country-profile-table-label is-empty"><strong>未命中</strong><small>—</small><em>不同</em></div></td>';
        var labels = unique(group.items.map(function (tag) { return tag.label || "未命中"; }));
        var periods = unique(group.items.map(function (tag) { return tag.period; }).filter(Boolean));
        var different = currentSignatures[key] !== entry.signatures[key];
        return '<td><div class="country-profile-table-label ' + (different ? "is-different" : "is-same") + '"><strong title="' + escape(labels.join(" / ")) + '">' + escape(labels.join(" / ") || "未命中") + '</strong><small>' + escape(periods.join(" / ") || "无周期") + '</small><em>' + (different ? "不同" : "一致") + "</em></div></td>";
      }).join("");
      return '<tr><th><strong>' + escape(entry.item.country) + '</strong><small>' + escape(entry.item.country_category) + " · " + escape(entry.item.store) + '</small></th>' + labelCells + '<td class="is-number">' + currency(entry.item.sales_amount) + '</td><td class="is-number ' + negativeClass(entry.item.order_gross_profit) + '">' + currency(entry.item.order_gross_profit) + '</td><td class="is-number">' + formatPercent(entry.item.order_gross_margin) + "</td></tr>";
    }).join("");
    return '<div class="country-profile-compare-table-wrap"><table class="country-profile-compare-table"><thead>' + head + '</thead><tbody>' + rows + "</tbody></table></div>";
  }

  function closeProfile() { elements.countryProfileDrawer.hidden = true; }

  function openRule(parentId) {
    var category = categoryById(parentId); if (!category) return;
    elements.countryRuleTitle.textContent = category.label;
    elements.countryRuleContent.innerHTML = '<div class="label-hub-rule-summary"><span>' + ({ available: "可分析", developing: "开发中", disabled: "未启用" }[category.state] || "暂无数据") + '</span><span>' + formatNumber((category.children || []).length) + ' 个子标签</span><span>' + escape(category.mutual_exclusion ? "同周期互斥" : "允许共现") + '</span></div><div class="label-hub-rule-detail-list">' + (category.children || []).map(function (child, index) { return '<details class="label-hub-rule-row"' + (index === 0 ? " open" : "") + '><summary class="label-hub-rule-row-main"><span class="label-hub-rule-name"><i>' + String(index + 1).padStart(2, "0") + '</i><b>' + escape(child.label) + '</b></span><span class="label-hub-rule-core">' + escape(child.rule || "未配置") + '</span><span class="label-hub-rule-period">' + escape((child.periods || []).join(" / ") || "无周期") + '</span><em>' + escape(child.status || "未配置") + '</em><span class="label-hub-rule-toggle"><i class="closed">展开配置</i><i class="opened">收起配置</i></span></summary><div class="label-hub-rule-extra"><section><span>业务定义</span><p>' + escape(child.definition || "未配置") + '</p></section><dl><div><dt>打标方式</dt><dd>' + escape(child.tagging_method || "未配置") + '</dd></div><div><dt>更新频率</dt><dd>' + escape(child.frequency || "未配置") + '</dd></div><div><dt>负责人</dt><dd>' + escape(child.owner || "未配置") + "</dd></div></dl></div></details>"; }).join("") + "</div>";
    elements.countryRuleDrawer.hidden = false;
  }

  function closeRule() { elements.countryRuleDrawer.hidden = true; }

  function parseConditions() {
    var result = {};
    String(state.conditions || "").split(";").forEach(function (group) { var pair = group.split(":"); if (pair.length === 2) result[pair[0]] = pair[1].split("|").filter(Boolean); });
    return result;
  }
  function serializeConditions(values) { return Object.keys(values).sort(function (a, b) { return Number(a) - Number(b); }).filter(function (key) { return values[key].length; }).map(function (key) { return key + ":" + values[key].join("|"); }).join(";"); }
  function setCondition(parent, child, force) { var values = parseConditions(); values[parent] = values[parent] || []; var index = values[parent].indexOf(String(child)); if (index < 0) values[parent].push(String(child)); else if (!force) values[parent].splice(index, 1); state.conditions = serializeConditions(values); }
  function toggleCondition(parent, child) { setCondition(String(parent), String(child), false); }
  function conditionSelected(parent, child) { return (parseConditions()[String(parent)] || []).indexOf(String(child)) >= 0; }
  function splitCodes(value) { return String(value || "").split("|").filter(Boolean); }
  function toggleLocal(key, value) { var field = { sales_trend: "sales_trends", daily_sales_band: "daily_sales_bands", margin_band: "margin_bands" }[key]; if (!field) return; var values = splitCodes(state[field]); var index = values.indexOf(String(value)); if (index < 0) values.push(String(value)); else values.splice(index, 1); state[field] = values.join("|"); }
  function localSelected(key, value) { var field = { sales_trend: "sales_trends", daily_sales_band: "daily_sales_bands", margin_band: "margin_bands" }[key]; return field && splitCodes(state[field]).indexOf(String(value)) >= 0; }
  function setPeriod(parent, period) { var values = {}; String(state.label_periods || "").split(";").forEach(function (group) { var pair = group.split(":"); if (pair.length === 2) values[pair[0]] = pair[1]; }); values[String(parent)] = period; state.label_periods = Object.keys(values).map(function (key) { return key + ":" + values[key]; }).join(";"); }
  function categoryPeriods(category) { return unique((category.children || []).reduce(function (items, child) { return items.concat(child.periods || []); }, [])); }
  function categoryById(id) { return (meta.categories || []).find(function (item) { return String(item.id) === String(id); }); }
  function localOptionLabel(key, code) { var definition = (meta.local_breakdowns || []).find(function (item) { return item.key === key; }) || {}; var option = (definition.options || []).find(function (item) { return item.key === code; }); return option ? option.label : code; }
  function unique(values) { return values.filter(function (value, index) { return value && values.indexOf(value) === index; }); }
  function matrixValue(cell) { return measure === "msku_count" ? cell.count : cell[measure]; }
  function displayMatrix(cell) { return measure === "msku_count" ? formatNumber(cell.count) : currency(cell[measure]); }
  function displayMeasure(bucket) { return measure === "msku_count" ? formatNumber(bucket.msku_count) : currency(bucket[measure]); }
  function chip(label, attrs) { return '<button type="button" class="sales-role-chip" ' + attrs + '>' + escape(label) + " ×</button>"; }
  function value(raw, type) { if (raw == null) return "暂无数据"; if (type === "money") return currency(raw); if (type === "rate") return formatPercent(raw); return formatNumber(raw); }
  function currency(value) { return app.formatCompactCurrency ? app.formatCompactCurrency(Number(value || 0)) : "¥" + formatNumber(value); }
  function formatNumber(value) { return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 }); }
  function formatPercent(value) { return (Number(value || 0) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%"; }
  function negativeClass(value) { return Number(value || 0) < 0 ? "is-negative" : ""; }
  function empty(text) { return '<div class="empty-state compact">' + escape(text) + "</div>"; }
  function escape(value) { return app.escapeHtml ? app.escapeHtml(String(value == null ? "" : value)) : String(value == null ? "" : value).replace(/[&<>\"]/g, function (character) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character]; }); }
  function showError(error) { elements.countryLabelHint.textContent = "国家标签数据暂不可用：" + ((error && error.message) || "请稍后重试"); [elements.countryOverview, elements.countryLabelBreakdowns, elements.countryMetricBreakdowns, elements.countryMatrices].forEach(function (host) { if (host) host.innerHTML = empty("加载失败，请检查远端标签连接后重试"); }); }
}());
