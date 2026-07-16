(function () {
  "use strict";

  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var state = {
    data_date: query.get("data_date") || "",
    metric_period: query.get("metric_period") || "30d",
    country_category: query.get("country_category") || "all",
    store: query.get("store") || "all",
    keyword: query.get("keyword") || "",
    parent_label_id: Number(query.get("parent_label_id") || 0),
    compare_parent_id: Number(query.get("compare_parent_id") || 0),
    analysis_parent_ids: query.get("analysis_parent_ids") || "",
    conditions: query.get("conditions") || "",
    label_period: query.get("label_period") || "all",
    sales_trends: query.get("sales_trends") || "",
    daily_sales_bands: query.get("daily_sales_bands") || "",
    margin_bands: query.get("margin_bands") || "",
    problem: query.get("problem") || "all",
    page: Number(query.get("page") || 1),
    page_size: normalizePageSize(query.get("page_size")),
    table_view: normalizeTableView(query.get("table_view")),
    sort_field: query.get("sort_field") || "problem_priority",
    sort_dir: query.get("sort_dir") || "desc"
  };
  var chartMeasure = query.get("measure") || "msku_count";
  var meta = null;
  var lastPayload = null;
  var elements = {};
  var requestToken = 0;
  var REMOTE_BUCKET_COLORS = [
    "#4e79a7", "#f28e2b", "#59a14f", "#7a5af8",
    "#e15759", "#00a6a6", "#8a9b3f", "#d65a9e",
    "#9c755f", "#2f6bde", "#b07aa1", "#c56a1a",
    "#76b7b2", "#edc948", "#6b778d", "#b44f72"
  ];

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "labelHubMetricPeriod", "labelHubCountry", "labelHubStore", "labelHubParent",
      "labelHubPeriod", "labelHubPeriodField", "labelHubKeyword", "labelHubClear", "labelHubScope",
      "labelHubPopulationSummary", "labelHubCategories", "labelHubCategoryDetail", "labelHubDiagnosis", "labelHubBreakdowns",
      "labelHubMeasureTabs", "labelHubCompare", "labelHubMatrix", "labelHubConditionRow", "labelHubConditions",
      "labelHubTable", "labelHubTableSummary", "labelHubTableView", "labelHubPageSize", "labelHubPagination", "labelHubHint", "labelHubDrawer",
      "labelHubDrawerClose", "labelHubDrawerContent", "labelHubRuleDrawer", "labelHubRuleDrawerClose",
      "labelHubRuleDrawerTitle", "labelHubRuleDrawerContent"
    ].forEach(function (id) { elements[id] = document.getElementById(id); });
    bindEvents();
    app.apiGet("/api/label-hub/meta").then(function (payload) {
      meta = payload;
      normalizeStateFromMeta();
      state.metric_period = state.metric_period || meta.default_metric_period || "30d";
      state.parent_label_id = state.parent_label_id || firstAvailableCategory();
      state.compare_parent_id = state.compare_parent_id || defaultCompareCategory();
      state.analysis_parent_ids = state.analysis_parent_ids || (meta.default_analysis_parent_ids || []).join("|");
      populateControls();
      render();
    }).catch(showError);
  }

  function normalizeStateFromMeta() {
    var dates = meta.data_dates || [];
    if (!state.data_date || dates.indexOf(state.data_date) < 0) {
      state.data_date = meta.default_data_date || dates[0] || "";
    }
  }

  function bindEvents() {
    elements.labelHubMetricPeriod.addEventListener("change", function () { state.metric_period = this.value; resetPageAndRender(); });
    elements.labelHubCountry.addEventListener("change", function () { state.country_category = this.value; resetPageAndRender(); });
    elements.labelHubStore.addEventListener("change", function () { state.store = this.value; resetPageAndRender(); });
    elements.labelHubParent.addEventListener("change", function () { selectParent(Number(this.value)); });
    elements.labelHubPeriod.addEventListener("change", function () { state.label_period = this.value; resetPageAndRender(); });
    elements.labelHubCompare.addEventListener("change", function () { state.compare_parent_id = Number(this.value); resetPageAndRender(); });
    elements.labelHubKeyword.addEventListener("change", function () { state.keyword = this.value.trim(); resetPageAndRender(); });
    elements.labelHubKeyword.addEventListener("keydown", function (event) { if (event.key === "Enter") { state.keyword = this.value.trim(); resetPageAndRender(); } });
    elements.labelHubPageSize.addEventListener("change", function () {
      state.page_size = normalizePageSize(this.value);
      state.page = 1;
      populateControls();
      render();
    });
    elements.labelHubTableView.addEventListener("change", function () {
      state.table_view = normalizeTableView(this.value);
      populateControls();
      app.writeQueryState(state);
      if (lastPayload) renderTable(lastPayload);
    });
    elements.labelHubClear.addEventListener("click", clearAllFilters);
    elements.labelHubMeasureTabs.addEventListener("click", function (event) {
      var button = event.target.closest("[data-measure]");
      if (!button) return;
      chartMeasure = button.dataset.measure;
      renderMeasureTabs();
      if (lastPayload) renderBreakdowns(lastPayload);
    });
    function handleOverviewClick(event) {
      var ruleButton = event.target.closest("[data-view-rules]");
      var child = event.target.closest("[data-overview-child]");
      var parent = event.target.closest("[data-overview-parent]");
      if (ruleButton) {
        openRuleDrawer(Number(ruleButton.dataset.viewRules));
      } else if (child) {
        toggleCondition(child.dataset.parentId, child.dataset.overviewChild);
        document.querySelector(".label-hub-breakdown-section").scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (parent) {
        selectParent(Number(parent.dataset.overviewParent));
      }
    }
    elements.labelHubCategories.addEventListener("click", handleOverviewClick);
    elements.labelHubCategoryDetail.addEventListener("click", handleOverviewClick);
    elements.labelHubBreakdowns.addEventListener("click", function (event) {
      var local = event.target.closest("[data-local-dimension]");
      var label = event.target.closest("[data-label-parent]");
      if (local) toggleLocalCondition(local.dataset.localDimension, local.dataset.localValue);
      if (label) toggleCondition(label.dataset.labelParent, label.dataset.labelChild);
    });
    elements.labelHubBreakdowns.addEventListener("change", function (event) {
      var select = event.target.closest("[data-analysis-slot]");
      if (!select) return;
      var ids = analysisIds();
      ids[Number(select.dataset.analysisSlot)] = Number(select.value);
      state.analysis_parent_ids = unique(ids).join("|");
      resetPageAndRender();
    });
    elements.labelHubConditions.addEventListener("click", function (event) {
      var label = event.target.closest("[data-remove-label]");
      var local = event.target.closest("[data-remove-local]");
      var clear = event.target.closest("[data-clear-linked]");
      if (label) toggleCondition(label.dataset.parentId, label.dataset.removeLabel);
      if (local) toggleLocalCondition(local.dataset.removeLocal, local.dataset.localValue);
      if (clear) clearLinkedFilters();
    });
    elements.labelHubDiagnosis.addEventListener("click", function (event) {
      var button = event.target.closest("[data-problem]");
      if (!button) return;
      state.problem = state.problem === button.dataset.problem ? "all" : button.dataset.problem;
      resetPageAndRender();
    });
    elements.labelHubMatrix.addEventListener("click", function (event) {
      var button = event.target.closest("[data-matrix-row]");
      if (!button) return;
      addMatrixConditions(button.dataset.matrixRow, button.dataset.matrixCol);
    });
    elements.labelHubDrawerClose.addEventListener("click", closeDrawer);
    elements.labelHubDrawer.addEventListener("click", function (event) { if (event.target === elements.labelHubDrawer) closeDrawer(); });
    elements.labelHubRuleDrawerClose.addEventListener("click", closeRuleDrawer);
    elements.labelHubRuleDrawer.addEventListener("click", function (event) { if (event.target === elements.labelHubRuleDrawer) closeRuleDrawer(); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") { closeDrawer(); closeRuleDrawer(); } });
  }

  function resetPageAndRender() { state.page = 1; populateControls(); render(); }
  function firstAvailableCategory() { var item = (meta.categories || []).find(function (category) { return category.state === "available"; }); return item ? item.id : ((meta.categories || [])[0] || {}).id || 0; }
  function defaultCompareCategory() { return state.parent_label_id !== 2 && categoryById(2) ? 2 : (((meta.categories || []).find(function (item) { return item.id !== state.parent_label_id; }) || {}).id || 0); }
  function categoryById(id) { return (meta.categories || []).find(function (item) { return item.id === Number(id); }); }
  function unique(items) { return items.filter(function (item, index) { return item && items.indexOf(item) === index; }); }
  function analysisIds() { return unique(String(state.analysis_parent_ids || "").split("|").map(Number).filter(Boolean)); }

  function optionList(items, selected, allLabel) {
    var prefix = allLabel ? '<option value="all">' + app.escapeHtml(allLabel) + "</option>" : "";
    return prefix + (items || []).map(function (item) {
      var value = item.id !== undefined ? item.id : (item.key !== undefined ? item.key : item);
      var label = item.label !== undefined ? item.label : item;
      return '<option value="' + app.escapeHtml(String(value)) + '"' + (String(value) === String(selected) ? " selected" : "") + ">" + app.escapeHtml(String(label)) + "</option>";
    }).join("");
  }

  function populateControls() {
    if (!meta) return;
    elements.labelHubMetricPeriod.innerHTML = optionList(meta.metric_periods || [], state.metric_period, "");
    elements.labelHubCountry.innerHTML = optionList(meta.country_categories || [], state.country_category, "全部国家类别");
    elements.labelHubStore.innerHTML = optionList(meta.stores || [], state.store, "全部店铺");
    elements.labelHubParent.innerHTML = optionList(meta.categories || [], state.parent_label_id, "");
    elements.labelHubCompare.innerHTML = optionList((meta.categories || []).filter(function (item) { return item.id !== state.parent_label_id; }), state.compare_parent_id, "");
    elements.labelHubKeyword.value = state.keyword;
    elements.labelHubPageSize.value = String(normalizePageSize(state.page_size));
    elements.labelHubTableView.value = normalizeTableView(state.table_view);
    var category = categoryById(state.parent_label_id) || { children: [] };
    var periods = unique([].concat.apply([], (category.children || []).map(function (child) { return child.periods || []; })));
    elements.labelHubPeriodField.hidden = periods.length < 2;
    elements.labelHubPeriod.innerHTML = optionList(periods, state.label_period, "全部周期");
    renderMeasureTabs();
  }

  function selectParent(parentId) {
    state.parent_label_id = parentId;
    state.compare_parent_id = defaultCompareCategory();
    state.label_period = "all";
    state.page = 1;
    populateControls();
    render();
  }

  function buildParams() {
    return {
      data_date: state.data_date,
      metric_period: state.metric_period,
      country_category: state.country_category,
      store: state.store,
      keyword: state.keyword,
      parent_label_id: state.parent_label_id,
      compare_parent_id: state.compare_parent_id,
      analysis_parent_ids: state.analysis_parent_ids,
      conditions: serializeConditions(state.conditions),
      label_period: state.label_period,
      sales_trends: serializeCodes(state.sales_trends),
      daily_sales_bands: serializeCodes(state.daily_sales_bands),
      margin_bands: serializeCodes(state.margin_bands),
      problem: state.problem,
      page: state.page,
      page_size: state.page_size,
      sort_field: state.sort_field,
      sort_dir: state.sort_dir
    };
  }

  function serializeConditions(value) { return String(value || ""); }
  function serializeCodes(value) { return String(value || ""); }
  function parsedConditions() {
    var result = {};
    serializeConditions(state.conditions).split(";").filter(Boolean).forEach(function (group) {
      var pair = group.split(":");
      if (pair.length === 2) result[pair[0]] = pair[1].split("|").filter(Boolean);
    });
    return result;
  }
  function saveConditions(value) {
    state.conditions = Object.keys(value).sort(function (a, b) { return Number(a) - Number(b); }).map(function (parent) {
      return parent + ":" + unique(value[parent]).sort(function (a, b) { return Number(a) - Number(b); }).join("|");
    }).join(";");
  }
  function toggleCondition(parentId, childId) {
    var values = parsedConditions();
    var parent = String(parentId);
    var child = String(childId);
    var children = values[parent] || [];
    values[parent] = children.indexOf(child) >= 0 ? children.filter(function (item) { return item !== child; }) : children.concat([child]);
    if (!values[parent].length) delete values[parent];
    saveConditions(values);
    resetPageAndRender();
  }
  function toggleLocalCondition(dimension, value) {
    var field = { sales_trend: "sales_trends", daily_sales_band: "daily_sales_bands", margin_band: "margin_bands" }[dimension];
    if (!field || value === "missing") {
      if (value === "missing") { state.problem = state.problem === "missing_metrics" ? "all" : "missing_metrics"; resetPageAndRender(); }
      return;
    }
    var values = serializeCodes(state[field]).split("|").filter(Boolean);
    state[field] = (values.indexOf(value) >= 0 ? values.filter(function (item) { return item !== value; }) : values.concat([value])).join("|");
    resetPageAndRender();
  }
  function addMatrixConditions(rowChild, colChild) {
    var values = parsedConditions();
    values[String(state.parent_label_id)] = unique((values[String(state.parent_label_id)] || []).concat([String(rowChild)]));
    values[String(state.compare_parent_id)] = unique((values[String(state.compare_parent_id)] || []).concat([String(colChild)]));
    saveConditions(values);
    resetPageAndRender();
  }
  function clearLinkedFilters() {
    state.conditions = "";
    state.sales_trends = "";
    state.daily_sales_bands = "";
    state.margin_bands = "";
    state.problem = "all";
    resetPageAndRender();
  }
  function clearAllFilters() {
    state.country_category = "all";
    state.store = "all";
    state.keyword = "";
    state.conditions = "";
    state.sales_trends = "";
    state.daily_sales_bands = "";
    state.margin_bands = "";
    state.problem = "all";
    state.label_period = "all";
    state.metric_period = meta.default_metric_period || "30d";
    state.page = 1;
    populateControls();
    render();
  }

  function render() {
    var token = ++requestToken;
    var main = document.querySelector(".main-content");
    if (main) main.classList.add("page-loading");
    app.writeQueryState(state);
    app.apiGet("/api/label-hub", buildParams()).then(function (payload) {
      if (token !== requestToken) return;
      lastPayload = payload;
      if ((payload.analysis_parent_ids || []).length) state.analysis_parent_ids = payload.analysis_parent_ids.join("|");
      renderScope(payload);
      renderPopulationSummary(payload);
      renderCategories(payload);
      renderCategoryDetail(payload);
      renderIssueOverview(payload);
      renderConditions();
      renderBreakdowns(payload);
      renderMatrix(payload);
      renderTable(payload);
      elements.labelHubHint.textContent = "当前大类：" + ((payload.rules || {}).label || "-");
    }).catch(showError).then(function () { if (main) main.classList.remove("page-loading"); });
  }

  function renderScope(payload) {
    var scope = payload.scope || {};
    var windowData = scope.metric_window || {};
    var localText = scope.local_metrics_status === "available"
      ? "经营指标 " + (windowData.period_start || "--") + " 至 " + (windowData.period_end || "--") + (windowData.lag_days ? " · 滞后 " + windowData.lag_days + " 天" : "")
      : (scope.local_metrics_status === "no_snapshot" ? "当前日期无本地经营快照" : "本地经营指标暂不可用");
    elements.labelHubScope.innerHTML = '<span>标签数据 ' + app.escapeHtml(scope.label_data_date || payload.data_date || "--") + '</span><span class="' + (scope.local_metrics_status === "available" ? "" : "warning") + '">' + app.escapeHtml(localText) + "</span>";
  }

  function renderCategories(payload) {
    elements.labelHubCategories.innerHTML = (payload.overview || []).map(function (item) {
      var active = item.id === payload.parent_label_id ? " active" : "";
      var stateLabel = { available: "可分析", disabled: "未启用", developing: "开发中" }[item.state] || "暂无数据";
      var flags = [];
      if ((item.periods || []).length > 1) flags.push("多周期");
      if (item.mutual_exclusion) flags.push("互斥配置");
      var uniqueCount = Number(item.unique_msku_count || 0);
      var businessCount = Number(item.business_unit_count || item.msku_count || 0);
      var uniqueCoverage = Number(item.unique_msku_coverage_rate || 0);
      return '<article class="label-hub-category-card ' + app.escapeHtml(item.state || "") + active + '"><button type="button" class="label-hub-category-head" data-overview-parent="' + item.id + '" aria-pressed="' + (active ? "true" : "false") + '"><span><b>' + app.escapeHtml(item.label) + '</b><small>' + app.escapeHtml(stateLabel) + '</small></span><strong>' + formatNumber(uniqueCount) + '<small> MSKU</small></strong></button><div class="label-hub-coverage"><i style="width:' + Math.round(uniqueCoverage * 100) + '%"></i></div><div class="label-hub-category-meta"><span>去重覆盖 ' + formatPercent(uniqueCoverage) + '</span><span>经营单元 ' + formatNumber(businessCount) + '</span></div><div class="label-hub-category-foot"><span>' + app.escapeHtml(flags.join(" · ") || "单一口径") + '</span><button type="button" class="label-hub-rule-link" data-view-rules="' + item.id + '">查看划分规则</button></div></article>';
    }).join("");
  }

  function renderPopulationSummary(payload) {
    var summary = payload.population_summary || {};
    var cards = [
      { label: "去重 MSKU", value: summary.unique_msku_count, note: "合并跨店铺与国家类别后的商品规模" },
      { label: "经营单元", value: summary.business_unit_count, note: "国家类别 + 店铺 + MSKU" },
      { label: "跨范围 MSKU", value: summary.cross_scope_msku_count, note: "存在于多个经营单元，标签可能不同" }
    ];
    elements.labelHubPopulationSummary.innerHTML = cards.map(function (item, index) {
      return '<article class="label-hub-population-card tone-' + index + '"><span>' + app.escapeHtml(item.label) + '</span><strong>' + formatNumber(item.value || 0) + '</strong><small>' + app.escapeHtml(item.note) + '</small></article>';
    }).join("");
  }

  function renderCategoryDetail(payload) {
    var selected = parsedConditions();
    var item = (payload.overview || []).find(function (category) { return Number(category.id) === Number(payload.parent_label_id); });
    if (!item) {
      elements.labelHubCategoryDetail.innerHTML = '<div class="empty-state compact">当前没有可分析的标签分类。</div>';
      return;
    }
    var distributionById = {};
    (payload.distribution || []).forEach(function (entry) {
      distributionById[String(entry.id)] = entry;
    });
    var children = (item.children || []).map(function (child) {
      var checked = (selected[String(item.id)] || []).indexOf(String(child.id)) >= 0;
      var scoped = distributionById[String(child.id)] || {};
      return '<button type="button" class="label-hub-child' + (checked ? " selected" : "") + '" data-overview-child="' + child.id + '" data-parent-id="' + item.id + '" aria-pressed="' + checked + '" title="' + app.escapeHtml(child.rule || child.definition || child.label) + '"><span><b>' + app.escapeHtml(child.label) + '</b><small>' + formatPercent(scoped.share) + '</small></span><strong>' + formatNumber(scoped.count) + '<small> MSKU</small></strong></button>';
    }).join("");
    var periods = (item.periods || []).join(" / ") || "无周期";
    var note = item.mutual_exclusion ? "同周期互斥" : "允许标签共现";
    var aggregationRule = item.aggregation_rule || "跨经营单元按业务优先级只保留一个主标签。";
    elements.labelHubCategoryDetail.innerHTML = '<header><div><span class="section-kicker">当前分析标签</span><h3>' + app.escapeHtml(item.label) + '</h3></div><p>' + app.escapeHtml(periods) + " · " + app.escapeHtml(note) + ' · ' + app.escapeHtml(aggregationRule) + '</p></header><div class="label-hub-children">' + children + "</div>";
  }

  function renderIssueOverview(payload) {
    var diagnosis = payload.diagnosis || {};
    var subject = diagnosis.subject || {};
    var business = diagnosis.business || {};
    var counts = payload.issue_counts || {};
    var total = Number(counts.all || 0);
    var localAvailable = (payload.scope || {}).local_metrics_status === "available";
    var conditionCount = Math.max(0, Number(subject.condition_count || 0) - (state.problem !== "all" ? 1 : 0));
    var coverageRate = total ? Math.max(0, 1 - Number(counts.missing_metrics || 0) / total) : 0;
    var issues = [
      { key: "problem_role", label: "问题产品", local: true, tone: "warning" },
      { key: "zero_sales", label: "日销为 0", local: true, tone: "warning" },
      { key: "negative_profit", label: "订单毛利为负", local: true, tone: "danger" },
      { key: "missing_metrics", label: "暂无经营数据", local: true, tone: "" },
      { key: "conflict", label: "标签互斥冲突", local: false, tone: Number(counts.conflict || 0) ? "danger" : "" }
    ];
    var conditionText = conditionCount ? formatNumber(conditionCount) + " 个标签/联动条件" : "当前父标签全部 MSKU";
    var subjectHtml = '<div class="label-hub-diagnosis-subject"><span>当前分析对象</span><h3>' + app.escapeHtml(subject.parent_label || (payload.rules || {}).label || "当前标签") + '</h3><strong>' + formatNumber(total) + ' <small>MSKU</small></strong><p>' + app.escapeHtml(conditionText) + ' · 指标覆盖 ' + formatPercent(coverageRate) + "</p></div>";
    var signalHtml = issues.map(function (item) {
      var available = !item.local || localAvailable;
      var count = Number(counts[item.key] || 0);
      var rate = total ? count / total : 0;
      var active = state.problem === item.key;
      return '<button type="button" class="label-hub-diagnosis-item ' + item.tone + (active ? " active" : "") + '"' + (available ? ' data-problem="' + item.key + '"' : " disabled") + ' aria-pressed="' + active + '"><span><b>' + app.escapeHtml(item.label) + '</b>' + (active ? '<em>已筛选</em>' : "") + '</span><strong>' + (available ? formatNumber(count) + ' <i>MSKU</i>' : "—") + '</strong><small>' + (available ? "占当前群体 " + formatPercent(rate) : "本地经营指标暂不可用") + "</small></button>";
    }).join("");
    var businessHtml = '<aside class="label-hub-diagnosis-business"><span>当前群体经营表现</span><div><small>销售额</small><strong>' + app.formatCompactCurrency(business.sales_amount || 0) + '</strong></div><div><small>订单毛利润</small><strong class="' + (Number(business.order_gross_profit || 0) < 0 ? "negative" : "") + '">' + app.formatCompactCurrency(business.order_gross_profit || 0) + '</strong></div><div><small>订单毛利率</small><strong class="' + (Number(business.order_gross_margin || 0) < 0 ? "negative" : "") + '">' + app.formatPercent(business.order_gross_margin || 0) + "</strong></div></aside>";
    elements.labelHubDiagnosis.innerHTML = subjectHtml + '<div class="label-hub-diagnosis-signals">' + signalHtml + "</div>" + businessHtml;
  }

  function renderMeasureTabs() {
    Array.from(elements.labelHubMeasureTabs.querySelectorAll("[data-measure]")).forEach(function (button) { button.classList.toggle("active", button.dataset.measure === chartMeasure); });
  }

  function renderBreakdowns(payload) {
    var selectedLabels = parsedConditions();
    var localSelections = {
      sales_trend: serializeCodes(state.sales_trends).split("|").filter(Boolean),
      daily_sales_band: serializeCodes(state.daily_sales_bands).split("|").filter(Boolean),
      margin_band: serializeCodes(state.margin_bands).split("|").filter(Boolean)
    };
    var selectedRemote = analysisIds();
    var panels = payload.breakdowns || [];
    elements.labelHubBreakdowns.innerHTML = [
      renderBreakdownGroup("经营表现", "本地周期快照", panels.filter(function (panel) { return panel.source === "local"; })),
      renderBreakdownGroup("远端标签结构", "标签事实 · 可切换维度", panels.filter(function (panel) { return panel.source === "remote_label"; }))
    ].join("");

    function renderBreakdownGroup(title, description, groupPanels) {
      if (!groupPanels.length) return "";
      return '<section class="label-hub-breakdown-group"><div class="label-hub-breakdown-group-head"><b>' + app.escapeHtml(title) + '</b><span>' + app.escapeHtml(description) + '</span><i></i></div><div class="label-hub-breakdown-grid">' + groupPanels.map(renderPanel).join("") + "</div></section>";
    }

    function renderPanel(panel) {
      var buckets = (panel.buckets || []).slice().sort(function (a, b) { return Math.abs(Number(b[chartMeasure] || 0)) - Math.abs(Number(a[chartMeasure] || 0)); });
      var missingBucket = buckets.find(function (bucket) { return String(bucket.key) === "missing"; });
      var matchedCount = Math.max(0, Number(panel.denominator || 0) - Number((missingBucket || {}).msku_count || 0));
      var scopeCopy = panel.key === "sales_trend"
        ? "同截止日 7天 / 30天日均对比"
        : panel.source === "local" && missingBucket
        ? formatNumber(matchedCount) + " 个有经营快照"
        : "分析口径 " + formatNumber(panel.denominator) + " MSKU";
      var header = '<div><span class="label-hub-source ' + panel.source + '">' + (panel.source === "local" ? "本地经营" : "远端标签") + '</span><h3>' + app.escapeHtml(panel.label) + '</h3><small>' + scopeCopy + "</small></div>";
      if (panel.source === "remote_label") {
        var slot = Math.max(0, selectedRemote.indexOf(Number(panel.parent_id)));
        var used = selectedRemote.filter(function (_, index) { return index !== slot; });
        var options = (meta.categories || []).filter(function (item) { return item.id !== state.parent_label_id && used.indexOf(item.id) < 0; });
        header += '<label class="label-hub-dimension-select"><span>切换维度</span><select aria-label="切换' + app.escapeHtml(panel.label) + '维度" data-analysis-slot="' + slot + '">' + optionList(options, panel.parent_id, "") + "</select></label>";
      }
      var dominant = dominantBreakdown(buckets);
      var dominantTone = dominant ? breakdownTone(panel, dominant) : "neutral";
      var finding = dominant
        ? '<div class="label-hub-breakdown-finding"><span>' + findingPrefix(dominantTone) + '</span><strong class="tone-' + dominantTone + '">' + app.escapeHtml(dominant.label) + " " + dominantMeasure(dominant) + "</strong></div>"
        : "";
      var composition = renderComposition(panel, buckets);
      var bars = buckets.map(function (bucket) {
        var selected = panel.source === "local"
          ? (localSelections[panel.key] || []).indexOf(String(bucket.key)) >= 0 || (bucket.key === "missing" && state.problem === "missing_metrics")
          : (selectedLabels[String(panel.parent_id)] || []).indexOf(String(bucket.id || bucket.key)) >= 0;
        var tone = breakdownTone(panel, bucket);
        var bucketColor = remoteBucketColor(panel, bucket);
        var bucketColorStyle = bucketColor ? ' style="--bucket-color:' + bucketColor + '"' : "";
        var attributes = panel.source === "local"
          ? 'data-local-dimension="' + panel.key + '" data-local-value="' + bucket.key + '"'
          : 'data-label-parent="' + panel.parent_id + '" data-label-child="' + (bucket.id || bucket.key) + '"';
        var label = String(bucket.key) === "missing" ? "未匹配经营快照" : bucket.label;
        var detail = String(bucket.key) === "missing" ? "当前归属键无快照" : breakdownDetail(bucket);
        return '<button type="button" class="label-hub-bar tone-' + tone + (selected ? " selected" : "") + '" ' + attributes + bucketColorStyle + ' data-negative="' + (Number(bucket.order_gross_profit || 0) < 0) + '" aria-pressed="' + selected + '"><span class="label-hub-bar-label"><b>' + app.escapeHtml(label) + (String(bucket.key) === "missing" ? '<i class="label-hub-info" title="标签归属键在当前经营周期内没有对应快照">i</i>' : "") + '</b><small>' + app.escapeHtml(detail) + '</small></span><strong>' + formatMeasure(bucket) + '</strong><small class="label-hub-bar-profit">' + auxiliaryMeasure(bucket) + "</small></button>";
      }).join("");
      var ruleDetails = (panel.rules || []).length
        ? '<details class="label-hub-breakdown-rules"><summary>查看趋势划分规则</summary><p>' + app.escapeHtml(panel.description || "") + '</p><dl>' + panel.rules.map(function (rule) { return '<div><dt>' + app.escapeHtml(rule.label) + '</dt><dd>' + app.escapeHtml(rule.rule) + "</dd></div>"; }).join("") + "</dl></details>"
        : "";
      return '<article class="label-hub-breakdown-card"><header>' + header + "</header>" + finding + composition + '<div class="label-hub-bars">' + bars + "</div>" + ruleDetails + "</article>";
    }
  }

  function dominantBreakdown(buckets) {
    return (buckets || []).reduce(function (winner, bucket) {
      if (!winner) return bucket;
      return Math.abs(Number(bucket[chartMeasure] || 0)) > Math.abs(Number(winner[chartMeasure] || 0)) ? bucket : winner;
    }, null);
  }

  function breakdownTone(panel, bucket) {
    var key = String(bucket.key || "").toLowerCase();
    var label = String(bucket.label || "");
    if (key === "missing") return "missing";
    if (Number(bucket.order_gross_profit || 0) < 0 && chartMeasure === "order_gross_profit") return "risk";
    if (panel.key === "sales_role") return key === "eliminate" ? "risk" : (key === "incubation" ? "attention" : (key === "star" ? "healthy" : "neutral"));
    if (panel.key === "sales_trend") return ["declining", "stopped", "no_sales"].indexOf(key) >= 0 ? "risk" : (key === "slowing" ? "attention" : (["accelerating", "growing", "recent_start"].indexOf(key) >= 0 ? "healthy" : "neutral"));
    if (panel.key === "daily_sales_band") return key === "zero" ? "risk" : (key === "lt1" ? "attention" : (key === "gt5" ? "healthy" : "neutral"));
    if (panel.key === "margin_band") return key === "lt5" ? "risk" : (key === "5_10" ? "attention" : (["15_25", "gt25"].indexOf(key) >= 0 ? "healthy" : "neutral"));
    if (/严重|高退货|高度依赖|停售|断货/.test(label)) return "risk";
    if (/中度|中库存|低库存|高库存|关注/.test(label)) return "attention";
    if (/自然流量|健康|正常|低退货|明星|高毛利/.test(label)) return "healthy";
    return "neutral";
  }

  function remoteBucketColor(panel, bucket) {
    if (panel.source !== "remote_label") return "";
    var bucketKey = String(bucket.id || bucket.key || "");
    var index = (panel.buckets || []).findIndex(function (item) {
      return String(item.id || item.key || "") === bucketKey;
    });
    return REMOTE_BUCKET_COLORS[(index < 0 ? 0 : index) % REMOTE_BUCKET_COLORS.length];
  }

  function renderComposition(panel, buckets) {
    var total = chartMeasure === "order_gross_profit"
      ? buckets.reduce(function (sum, bucket) { return sum + Math.abs(Number(bucket.order_gross_profit || 0)); }, 0)
      : 1;
    var used = 0;
    var segments = buckets.map(function (bucket) {
      var ratio = chartMeasure === "msku_count"
        ? Number(bucket.share || 0)
        : (chartMeasure === "sales_amount" ? Number(bucket.sales_share || 0) : (total ? Math.abs(Number(bucket.order_gross_profit || 0)) / total : 0));
      used += ratio;
      var bucketColor = remoteBucketColor(panel, bucket);
      return '<i class="tone-' + breakdownTone(panel, bucket) + '" style="' + (bucketColor ? "--bucket-color:" + bucketColor + ";" : "") + 'width:' + Math.max(0, ratio * 100).toFixed(2) + '%" title="' + app.escapeHtml(bucket.label) + " " + formatPercent(ratio) + '"></i>';
    });
    if (chartMeasure !== "order_gross_profit" && used < 0.999) {
      segments.push('<i class="tone-missing uncovered" style="width:' + Math.max(0, (1 - used) * 100).toFixed(2) + '%" title="未命中当前分类 ' + formatPercent(1 - used) + '"></i>');
    }
    return '<div class="label-hub-composition" aria-label="' + app.escapeHtml(panel.label) + '构成">' + segments.join("") + "</div>";
  }

  function findingPrefix(tone) {
    if (tone === "risk") return "首要关注项";
    if (tone === "attention") return "当前主要结构";
    if (tone === "healthy") return "当前优势结构";
    return "占比最高";
  }

  function dominantMeasure(bucket) {
    if (chartMeasure === "msku_count") return "占 " + formatPercent(bucket.share);
    return formatMeasure(bucket);
  }

  function breakdownDetail(bucket) {
    if (chartMeasure === "sales_amount") return "销售额贡献 " + formatPercent(bucket.sales_share);
    return "占当前群体 " + formatPercent(bucket.share);
  }

  function auxiliaryMeasure(bucket) {
    if (chartMeasure === "order_gross_profit") return "销售额 " + app.formatCompactCurrency(bucket.sales_amount || 0);
    if (chartMeasure === "sales_amount") return "毛利 " + app.formatCompactCurrency(bucket.order_gross_profit || 0);
    return "毛利 " + app.formatCompactCurrency(bucket.order_gross_profit || 0);
  }

  function formatMeasure(bucket) {
    if (chartMeasure === "sales_amount") return app.formatCompactCurrency(bucket.sales_amount || 0);
    if (chartMeasure === "order_gross_profit") return app.formatCompactCurrency(bucket.order_gross_profit || 0);
    return formatNumber(bucket.msku_count);
  }

  function renderConditions() {
    var chips = [];
    var values = parsedConditions();
    Object.keys(values).forEach(function (parent) {
      var category = categoryById(parent);
      values[parent].forEach(function (child) {
        var detail = ((category || {}).children || []).find(function (item) { return String(item.id) === String(child); });
        chips.push('<button type="button" class="sales-role-chip" data-remove-label="' + child + '" data-parent-id="' + parent + '">' + app.escapeHtml((category || {}).label || parent) + "：" + app.escapeHtml((detail || {}).label || child) + " ×</button>");
      });
    });
    [{ field: "sales_trends", key: "sales_trend", label: "动销趋势" }, { field: "daily_sales_bands", key: "daily_sales_band", label: "日销段" }, { field: "margin_bands", key: "margin_band", label: "毛利段" }].forEach(function (dimension) {
      var definition = (meta.local_breakdowns || []).find(function (item) { return item.key === dimension.key; }) || {};
      serializeCodes(state[dimension.field]).split("|").filter(Boolean).forEach(function (value) {
        var option = (definition.options || []).find(function (item) { return item.key === value; }) || { label: value };
        chips.push('<button type="button" class="sales-role-chip local" data-remove-local="' + dimension.key + '" data-local-value="' + value + '">' + dimension.label + "：" + app.escapeHtml(option.label) + " ×</button>");
      });
    });
    if (state.problem !== "all") chips.push('<button type="button" class="sales-role-chip warning" data-problem-chip>问题队列：' + app.escapeHtml(problemLabel(state.problem)) + " ×</button>");
    elements.labelHubConditionRow.hidden = !chips.length;
    elements.labelHubConditions.innerHTML = chips.length ? chips.join("") + '<button type="button" class="label-hub-clear-linked" data-clear-linked>清空联动</button>' : "";
    var problemChip = elements.labelHubConditions.querySelector("[data-problem-chip]");
    if (problemChip) problemChip.addEventListener("click", function () { state.problem = "all"; resetPageAndRender(); });
  }

  function renderMatrix(payload) {
    var matrix = payload.matrix || {};
    var cells = {};
    var maxCount = Math.max.apply(null, (matrix.cells || []).map(function (cell) { return Number(cell.count || 0); }).concat([1]));
    (matrix.cells || []).forEach(function (cell) { cells[cell.row_id + "|" + cell.col_id] = cell; });
    var columns = matrix.columns || [];
    var rows = matrix.rows || [];
    if (!columns.length || !rows.length) { elements.labelHubMatrix.innerHTML = '<div class="empty-state compact">当前分类没有可用的共现数据。</div>'; return; }
    elements.labelHubMatrix.innerHTML = '<div class="label-hub-matrix-legend"><span>MSKU 数</span><small>低</small><i class="heat-level-1"></i><i class="heat-level-2"></i><i class="heat-level-3"></i><i class="heat-level-4"></i><small>高</small></div><div class="label-hub-matrix-table" style="grid-template-columns: 120px repeat(' + columns.length + ', minmax(96px, 1fr))"><div></div>' + columns.map(function (column) { return '<strong>' + app.escapeHtml(column.label) + "</strong>"; }).join("") + rows.map(function (row) { return '<strong>' + app.escapeHtml(row.label) + '</strong>' + columns.map(function (column) { var cell = cells[row.id + "|" + column.id] || { count: 0 }; return '<button type="button" class="heat-level-' + matrixHeatLevel(cell.count, maxCount) + '" data-matrix-row="' + row.id + '" data-matrix-col="' + column.id + '"><b>' + formatNumber(cell.count) + '</b><small>' + app.formatCompactCurrency(cell.sales_amount || 0) + "</small></button>"; }).join(""); }).join("") + "</div>";
  }

  function matrixHeatLevel(count, maxCount) {
    if (!count || !maxCount) return 0;
    var ratio = Number(count) / Number(maxCount);
    if (ratio <= 0.15) return 1;
    if (ratio <= 0.35) return 2;
    if (ratio <= 0.65) return 3;
    return 4;
  }

  function renderLabelSummaryCell(params) {
    var labels = (params.data && params.data.labels) || [];
    var parents = {};
    var children = {};
    labels.forEach(function (item) {
      parents[String(item.parent_id)] = true;
      children[String(item.id)] = true;
    });
    return '<span class="label-summary-compact"><b>' + Object.keys(parents).length + ' 个分类</b><small>' + Object.keys(children).length + ' 个标签 · 点击查看</small></span>';
  }

  function openRuleDrawer(parentId) {
    var category = categoryById(parentId);
    if (!category) return;
    var stateLabel = { available: "可分析", disabled: "未启用", developing: "开发中" }[category.state] || "暂无数据";
    var children = category.children || [];
    var allPeriods = unique(children.reduce(function (result, child) { return result.concat(child.periods || []); }, []));
    var aggregationPriority = category.aggregation_priority_labels || [];
    var ruleCards = (category.children || []).map(function (child) {
      var periods = (child.periods || []).join(" / ") || "未配置";
      var definition = child.definition || "未配置";
      var rule = child.rule || "未配置";
      var taggingMethod = child.tagging_method || "未配置";
      var frequency = child.frequency || "未配置";
      var owner = child.owner || "未配置";
      var mutualExclusion = child.mutual_exclusion || (category.mutual_exclusion ? "同周期互斥" : "未配置");
      var status = child.status || "未配置";
      var index = children.indexOf(child);
      return '<details class="label-hub-rule-row"' + (index === 0 ? " open" : "") + '><summary class="label-hub-rule-row-main"><span class="label-hub-rule-name"><i>' + String(index + 1).padStart(2, "0") + '</i><b>' + app.escapeHtml(child.label || String(child.id)) + '</b></span><span class="label-hub-rule-core">' + app.escapeHtml(rule) + '</span><span class="label-hub-rule-period">' + app.escapeHtml(periods) + '</span><em>' + app.escapeHtml(status) + '</em><span class="label-hub-rule-toggle"><i class="closed">展开配置</i><i class="opened">收起配置</i></span></summary><div class="label-hub-rule-extra"><section><span>业务定义</span><p>' + app.escapeHtml(definition) + '</p></section><dl><div><dt>打标方式</dt><dd>' + app.escapeHtml(taggingMethod) + '</dd></div><div><dt>更新频率</dt><dd>' + app.escapeHtml(frequency) + '</dd></div><div><dt>负责人</dt><dd>' + app.escapeHtml(owner) + '</dd></div><div><dt>互斥配置</dt><dd>' + app.escapeHtml(mutualExclusion) + '</dd></div></dl></div></details>';
    }).join("");
    elements.labelHubRuleDrawerTitle.textContent = category.label;
    elements.labelHubRuleDrawerContent.innerHTML = '<div class="label-hub-rule-summary"><span>' + app.escapeHtml(stateLabel) + '</span><span>' + formatNumber(children.length) + ' 个子标签</span><span>' + app.escapeHtml(allPeriods.join(" / ") || "无周期配置") + '</span><span>' + app.escapeHtml(category.mutual_exclusion ? "同周期互斥" : "允许共现") + '</span></div><div class="label-hub-rule-priority"><b>主标签优先级</b><span>' + app.escapeHtml(aggregationPriority.join(" ＞ ") || "按标签详情表顺序") + '</span><small>同一 MSKU 跨经营单元命中多个子标签时，只保留优先级最高的一项用于上方聚合分析；底部明细保留原始事实。</small></div><div class="label-hub-rule-table-head"><span>子标签</span><span>核心划分规则</span><span>周期</span><span>状态</span><span>操作</span></div><div class="label-hub-rule-detail-list">' + (ruleCards || '<div class="empty-state compact">该分类暂未配置子标签规则。</div>') + '</div>';
    elements.labelHubRuleDrawer.hidden = false;
    elements.labelHubRuleDrawerClose.focus();
  }

  function closeRuleDrawer() { elements.labelHubRuleDrawer.hidden = true; }

  function renderTable(payload) {
    elements.labelHubTableSummary.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + formatNumber(payload.total) + " 条";
    window.kanbanGrid.makeGrid("labelHubTable", {
      rowData: payload.rows || [],
      domLayout: "normal",
      rowHeight: 52,
      headerHeight: 50,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前联动条件下没有 MSKU。</span>',
      columnDefs: tableColumns(state.table_view),
      onRowClicked: function (event) { if (event.data) openDrawer(event.data); }
    });
    renderPagination(payload);
  }

  function tableColumns(view) {
    if (view === "labels") return labelColumns();
    if (view === "metrics") return metricColumns();
    return overviewColumns();
  }

  function identityColumns() {
    return [
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 110 },
      { headerName: "店铺", field: "store", pinned: "left", width: 125 },
      { headerName: "MSKU", field: "msku", pinned: "left", width: 145, cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } }
    ];
  }

  function currentLabelColumn() {
    return { headerName: "当前标签", field: "current_label", width: 150, tooltipField: "current_label", cellClass: "label-text-cell" };
  }

  function labelProfileColumn() {
    return { headerName: "标签画像", field: "label_summary", width: 165, tooltipField: "label_summary", cellClass: "label-summary-cell", cellRenderer: renderLabelSummaryCell };
  }

  function numberColumn(headerName, field, width, digits) {
    return { headerName: headerName, field: field, width: width, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value === null || params.value === undefined ? "暂无" : window.kanbanGrid.number(params.value, digits || 0); } };
  }

  function amountColumn(headerName, field, width) {
    return { headerName: headerName, field: field, width: width, cellClass: function (params) { return "ag-grid-number-cell" + (Number(params.value || 0) < 0 ? " label-hub-negative-value" : ""); }, valueFormatter: function (params) { return params.value === null || params.value === undefined ? "暂无" : window.kanbanGrid.compactAmount(params.value); } };
  }

  function percentColumn(headerName, field, width) {
    return { headerName: headerName, field: field, width: width, cellClass: function (params) { var value = Number(params.value || 0); return "ag-grid-number-cell" + (value < 0.05 ? " label-hub-risk-value" : (value >= 0.15 ? " label-hub-healthy-value" : "")); }, valueFormatter: function (params) { return params.value === null || params.value === undefined ? "暂无" : window.kanbanGrid.percent(params.value, 1); } };
  }

  function rateColumn(headerName, field, width) {
    return { headerName: headerName, field: field, width: width, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value === null || params.value === undefined ? "暂无" : window.kanbanGrid.percent(params.value, 1); } };
  }

  function overviewColumns() {
    return identityColumns().concat([
      currentLabelColumn(),
      labelProfileColumn(),
      { headerName: "问题提示", field: "issue_labels", width: 190, sortable: false, filter: false, tooltipValueGetter: function (params) { return (params.value || []).join(" / ") || "当前未命中问题条件"; }, cellRenderer: renderIssueCell },
      { headerName: "动销趋势", field: "sales_trend", width: 135, cellRenderer: renderTrendCell },
      numberColumn("日均销量", "daily_sales", 105, 2),
      numberColumn(metricPeriodLabel() + "销量", "sales_qty", 105, 0),
      amountColumn(metricPeriodLabel() + "销售额", "sales_amount", 120),
      amountColumn("订单毛利润", "order_gross_profit", 125),
      percentColumn("订单毛利率", "order_gross_margin", 115),
      { headerName: "指标状态", field: "data_status", width: 125, cellRenderer: renderMetricStatusCell }
    ]);
  }

  function labelColumns() {
    return identityColumns().concat([
      currentLabelColumn(),
      labelProfileColumn(),
      { headerName: "销售角色", field: "sales_role", width: 115 },
      { headerName: "生命周期", field: "lifecycle_label", width: 110, tooltipField: "lifecycle_label", cellClass: "label-text-cell" },
      { headerName: "日销段", field: "daily_sales_band", width: 105 },
      { headerName: "毛利段", field: "margin_band", width: 100 },
      { headerName: "标签冲突", field: "conflict", width: 105, cellRenderer: renderConflictCell },
      { headerName: "指标状态", field: "data_status", width: 135, cellRenderer: renderMetricStatusCell }
    ]);
  }

  function metricColumns() {
    return identityColumns().concat([
      { headerName: "动销趋势", field: "sales_trend", width: 135, cellRenderer: renderTrendCell },
      numberColumn("日均销量", "daily_sales", 105, 2),
      numberColumn(metricPeriodLabel() + "销量", "sales_qty", 105, 0),
      amountColumn(metricPeriodLabel() + "销售额", "sales_amount", 120),
      amountColumn("订单毛利润", "order_gross_profit", 125),
      percentColumn("订单毛利率", "order_gross_margin", 115),
      numberColumn("期末库存", "ending_inventory_qty", 105, 0),
      amountColumn("广告花费", "ad_spend", 110),
      rateColumn("ACOS", "acos", 90),
      rateColumn("TACOS", "tacos", 90),
      numberColumn("退货数量", "return_count", 105, 0),
      amountColumn("净销售额", "net_amount", 115)
    ]);
  }

  function renderIssueCell(params) {
    var labels = (params.data && params.data.issue_labels) || [];
    var codes = (params.data && params.data.issue_codes) || [];
    if (!labels.length) return '<span class="label-hub-issue-pill is-clear">暂无问题</span>';
    var visible = labels.slice(0, 2).map(function (label, index) {
      return '<span class="label-hub-issue-pill issue-' + app.escapeHtml(codes[index] || "other") + '">' + app.escapeHtml(label) + "</span>";
    }).join("");
    if (labels.length > 2) visible += '<span class="label-hub-issue-more">+' + (labels.length - 2) + "</span>";
    return '<span class="label-hub-issue-cell">' + visible + "</span>";
  }

  function renderTrendCell(params) {
    var code = String((params.data && params.data.sales_trend_code) || "insufficient");
    var ratio = params.data && params.data.sales_trend_ratio;
    var ratioText = ratio === null || ratio === undefined ? "" : '<small>' + (Number(ratio) > 0 ? "+" : "") + formatPercent(ratio) + "</small>";
    return '<span class="label-hub-trend-pill trend-' + app.escapeHtml(code) + '"><b>' + app.escapeHtml(params.value || "暂无趋势数据") + "</b>" + ratioText + "</span>";
  }

  function renderMetricStatusCell(params) {
    var value = String(params.value || "");
    var tone = value === "本地指标可用" ? "available" : (value === "暂无本地经营数据" ? "missing" : "unavailable");
    var label = value === "本地指标可用" ? "指标可用" : (value === "暂无本地经营数据" ? "指标缺失" : value || "状态未知");
    return '<span class="label-hub-metric-status is-' + tone + '">' + app.escapeHtml(label) + "</span>";
  }

  function renderConflictCell(params) {
    return params.value ? '<span class="label-hub-metric-status is-risk">存在冲突</span>' : '<span class="label-hub-metric-status is-available">无冲突</span>';
  }

  function metricPeriodLabel() {
    return String(state.metric_period || "30d").replace("d", "天");
  }

  function metricWindowLabel(window) {
    var period = String(window.period_code || state.metric_period || "30d").replace("d", "天");
    var range = window.period_start && window.period_end ? " · " + window.period_start + " 至 " + window.period_end : "经营周期";
    var lag = Number(window.lag_days || 0) > 0 ? " · 滞后 " + formatNumber(window.lag_days) + " 天" : "";
    return period + range + lag;
  }

  function renderPagination(payload) {
    elements.labelHubPagination.innerHTML = '<button type="button" data-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><span>第 ' + payload.page + " / " + payload.total_pages + ' 页</span><button type="button" data-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + ">下一页</button>";
    Array.from(elements.labelHubPagination.querySelectorAll("[data-page]")).forEach(function (button) { button.addEventListener("click", function () { if (!this.disabled) { state.page = Number(this.dataset.page); render(); } }); });
  }

  function renderProfileTags(items, emptyText) {
    if (!items.length) return '<div class="empty-state compact">' + app.escapeHtml(emptyText) + '</div>';
    return items.map(function (item) { return '<article class="label-hub-profile-tag"><div><span>' + app.escapeHtml(item.parent_label) + '</span><strong>' + app.escapeHtml(item.label) + '</strong></div><small>' + app.escapeHtml(item.period || "无周期") + '</small><p>' + app.escapeHtml(item.rule || item.definition || "暂无规则说明") + "</p></article>"; }).join("");
  }

  function openDrawer(row) {
    elements.labelHubDrawer.hidden = false;
    elements.labelHubDrawerContent.innerHTML = '<div class="empty-state compact">正在加载 MSKU 画像…</div>';
    app.apiGet("/api/label-hub/msku", { data_date: state.data_date, metric_period: state.metric_period, country_category: row.country_category, store: row.store, msku: row.msku }).then(function (profile) {
      var tagProfile = profile.tag_profile || {};
      var analysisTags = renderProfileTags(tagProfile.analysis_labels || tagProfile.labels || [], "暂无 MSKU 口径标签");
      var metric = profile.metric_profile || {};
      var metricItems = [["销量", metric.sales_qty], ["日均销量", metric.daily_sales], ["销售额", metric.sales_amount, "currency"], ["未税销售额", metric.sales_amount_ex_tax, "currency"], ["订单毛利润", metric.order_gross_profit, "currency"], ["订单毛利率", metric.order_gross_margin, "percent"], ["结算毛利润", metric.settlement_gross_profit, "currency"], ["广告花费", metric.ad_spend, "currency"], ["广告销售额", metric.ad_sales, "currency"], ["ACOS", metric.acos, "percent"], ["TACOS", metric.tacos, "percent"], ["退货数量", metric.return_count], ["退货金额", metric.return_amount, "currency"], ["净销售额", metric.net_amount, "currency"], ["期末库存", metric.ending_inventory_qty], ["平均库存", metric.avg_inventory_qty]];
      var metricsHtml = metricItems.map(function (item) { var value = item[1]; if (value === null || value === undefined) value = "暂无数据"; else if (item[2] === "currency") value = app.formatCompactCurrency(value); else if (item[2] === "percent") value = app.formatPercent(value); else value = formatNumber(value); return '<div><span>' + item[0] + '</span><strong>' + value + "</strong></div>"; }).join("");
      var identity = profile.identity || {};
      var status = profile.data_status || {};
      var links = profile.navigation_links || {};
      var metricWindowText = metricWindowLabel(status.metric_window || {});
      var metricStatusText = status.has_local_metric
        ? "经营指标来自本地周期快照"
        : (status.local_metrics_status === "available" ? "该 MSKU 暂无本地经营指标" : (status.local_metrics_status === "no_snapshot" ? "当前日期无本地经营快照" : "本地经营指标暂不可用"));
      elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">MSKU 画像</p><h2 id="labelHubDrawerTitle">' + app.escapeHtml(identity.msku || row.msku) + '</h2><p>' + app.escapeHtml(identity.country_category || "") + " · " + app.escapeHtml(identity.store || "") + '</p></div><section><h3>MSKU 口径标签</h3><div class="label-hub-profile-tags">' + analysisTags + '</div></section><section><div class="label-hub-profile-section-head"><h3>本地经营画像</h3><span class="label-hub-profile-period">' + app.escapeHtml(metricWindowText) + '</span></div><p class="summary-hint">' + app.escapeHtml(metricStatusText) + '</p><div class="label-hub-profile-metrics">' + metricsHtml + '</div></section><div class="label-hub-profile-links"><a href="' + app.escapeHtml(links.sales_role || "#") + '">查看销售角色</a><a href="' + app.escapeHtml(links.lifecycle || "#") + '">查看生命周期</a></div>';
    }).catch(function (error) { elements.labelHubDrawerContent.innerHTML = '<div class="empty-state compact">画像加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + "</div>"; });
  }

  function closeDrawer() { elements.labelHubDrawer.hidden = true; }
  function normalizePageSize(value) {
    var pageSize = Number(value || 20);
    if (pageSize <= 20) return 20;
    if (pageSize <= 50) return 50;
    return 100;
  }
  function normalizeTableView(value) {
    return ["overview", "labels", "metrics"].indexOf(String(value || "")) >= 0 ? String(value) : "overview";
  }
  function formatNumber(value) { return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 }); }
  function formatPercent(value) { return (Number(value || 0) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%"; }
  function problemLabel(value) { return { conflict: "标签互斥冲突", missing_metrics: "暂无经营数据", zero_sales: "日销为 0", negative_profit: "订单毛利为负", problem_role: "问题产品" }[value] || value; }
  function showError(error) {
    elements.labelHubHint.textContent = "标签数据暂不可用：" + ((error && error.message) || "请稍后重试");
    if (elements.labelHubBreakdowns) elements.labelHubBreakdowns.innerHTML = '<div class="empty-state">加载失败，请检查远端标签连接后重试。</div>';
  }
}());
