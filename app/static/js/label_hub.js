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
    analysis_periods: query.get("analysis_periods") || "",
    conditions: query.get("conditions") || "",
    label_period: query.get("label_period") || "all",
    sales_trends: query.get("sales_trends") || "",
    daily_sales_bands: query.get("daily_sales_bands") || "",
    margin_bands: query.get("margin_bands") || "",
    problem: query.get("problem") || "all",
    transition_period: query.get("transition_period") || query.get("metric_period") || "30d",
    change_type: query.get("change_type") || "all",
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
  var changeRequestToken = 0;
  var changePage = 1;
  var lastChanges = null;
  var activeLayerChangeContext = null;
  var linkedSelectInstances = [];
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
      , "labelHubCountryProfileDrawer", "labelHubCountryProfileClose", "labelHubCountryProfileContent"
      , "labelHubChangesPanel", "labelHubChangeScope", "labelHubTransitionPeriod", "labelHubChangeType", "labelHubChangeContent",
      "labelHubChangeBrief"
    ].forEach(function (id) { elements[id] = document.getElementById(id); });
    setLoading(true);
    bindEvents();
    app.apiGet("/api/label-hub/meta").then(function (payload) {
      meta = payload;
      normalizeStateFromMeta();
      state.metric_period = state.metric_period || meta.default_metric_period || "30d";
      state.parent_label_id = state.parent_label_id || firstAvailableCategory();
      state.compare_parent_id = state.compare_parent_id || defaultCompareCategory();
      state.analysis_parent_ids = state.analysis_parent_ids || (meta.default_analysis_parent_ids || []).join("|");
      normalizeAnalysisPeriods();
      populateControls();
      render();
    }).catch(function (error) { setLoading(false); showError(error); });
  }

  function normalizeStateFromMeta() {
    var dates = meta.data_dates || [];
    if (!state.data_date || dates.indexOf(state.data_date) < 0) {
      state.data_date = meta.default_data_date || dates[0] || "";
    }
  }

  function bindEvents() {
    elements.labelHubMetricPeriod.addEventListener("change", function () { state.metric_period = this.value; state.transition_period = this.value; resetPageAndRender(); });
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
      var layerChangeDetail = event.target.closest("[data-layer-change-detail]");
      var local = event.target.closest("[data-local-dimension]");
      var label = event.target.closest("[data-label-parent]");
      if (layerChangeDetail) {
        openLayerChangeDetails(layerChangeDetail.dataset);
        return;
      }
      if (local) toggleLocalCondition(local.dataset.localDimension, local.dataset.localValue);
      if (label) toggleCondition(label.dataset.labelParent, label.dataset.labelChild);
    });
    elements.labelHubBreakdowns.addEventListener("change", function (event) {
      var dimensionSelect = event.target.closest("[data-analysis-slot]");
      var periodSelect = event.target.closest("[data-analysis-period-slot]");
      if (!dimensionSelect && !periodSelect) return;
      if (dimensionSelect) {
        var ids = analysisIds();
        var dimensionSlot = Number(dimensionSelect.dataset.analysisSlot);
        ids[dimensionSlot] = Number(dimensionSelect.value);
        state.analysis_parent_ids = unique(ids).join("|");
        var dimensionPeriods = analysisPeriods();
        dimensionPeriods[dimensionSlot] = "all";
        saveAnalysisPeriods(dimensionPeriods);
      } else {
        var periods = analysisPeriods();
        periods[Number(periodSelect.dataset.analysisPeriodSlot)] = periodSelect.value || "all";
        saveAnalysisPeriods(periods);
      }
      window.setTimeout(resetPageAndRender, 0);
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
    elements.labelHubCountryProfileClose.addEventListener("click", closeCountryProfileDrawer);
    elements.labelHubCountryProfileDrawer.addEventListener("click", function (event) { if (event.target === elements.labelHubCountryProfileDrawer) closeCountryProfileDrawer(); });
    elements.labelHubRuleDrawerClose.addEventListener("click", closeRuleDrawer);
    elements.labelHubRuleDrawer.addEventListener("click", function (event) { if (event.target === elements.labelHubRuleDrawer) closeRuleDrawer(); });
    elements.labelHubTransitionPeriod.addEventListener("change", function () { state.transition_period = this.value; changePage = 1; app.writeQueryState(state); loadChanges(); });
    elements.labelHubChangeType.addEventListener("change", function () { state.change_type = this.value; changePage = 1; app.writeQueryState(state); loadChanges(); });
    elements.labelHubChangeContent.addEventListener("click", function (event) {
      var pageButton = event.target.closest("[data-change-page]");
      var traceButton = event.target.closest("[data-change-msku]");
      if (pageButton && !pageButton.disabled) { changePage = Number(pageButton.dataset.changePage); loadChanges(); }
      if (traceButton) openChangeDrawer(traceButton.dataset.changeMsku);
    });
    elements.labelHubDrawerContent.addEventListener("click", function (event) {
      var pageButton = event.target.closest("[data-change-page]");
      var traceButton = event.target.closest("[data-change-msku]");
      var layerTypeButton = event.target.closest("[data-layer-change-type]");
      var transitionButton = event.target.closest("[data-layer-transition-type]");
      if (pageButton && !pageButton.disabled) {
        changePage = Number(pageButton.dataset.changePage);
        if (activeLayerChangeContext) loadLayerChangeDetails(activeLayerChangeContext);
        else loadChanges();
      }
      if (transitionButton && activeLayerChangeContext) {
        activeLayerChangeContext.change_type = transitionButton.dataset.layerTransitionType || "all";
        activeLayerChangeContext.transition_from = transitionButton.dataset.layerTransitionFrom || "";
        activeLayerChangeContext.transition_to = transitionButton.dataset.layerTransitionTo || "";
        changePage = 1;
        loadLayerChangeDetails(activeLayerChangeContext);
        return;
      }
      if (layerTypeButton && activeLayerChangeContext) {
        activeLayerChangeContext.change_type = layerTypeButton.dataset.layerChangeType || "all";
        activeLayerChangeContext.transition_from = "";
        activeLayerChangeContext.transition_to = "";
        changePage = 1;
        loadLayerChangeDetails(activeLayerChangeContext);
      }
      if (traceButton) openChangeDrawer(traceButton.dataset.changeMsku);
    });
    elements.labelHubDrawerContent.addEventListener("change", function (event) {
      if (event.target.matches("[data-drawer-transition-period]")) {
        state.transition_period = event.target.value;
        changePage = 1;
        app.writeQueryState(state);
        loadChanges();
      }
      if (event.target.matches("[data-drawer-change-type]")) {
        state.change_type = event.target.value;
        changePage = 1;
        app.writeQueryState(state);
        loadChanges();
      }
    });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") { closeDrawer(); closeRuleDrawer(); } });
  }

  function resetPageAndRender() { state.page = 1; populateControls(); render(); }
  function firstAvailableCategory() { var item = (meta.categories || []).find(function (category) { return category.state === "available"; }); return item ? item.id : ((meta.categories || [])[0] || {}).id || 0; }
  function defaultCompareCategory() { return state.parent_label_id !== 2 && categoryById(2) ? 2 : (((meta.categories || []).find(function (item) { return item.id !== state.parent_label_id; }) || {}).id || 0); }
  function categoryById(id) { return (meta.categories || []).find(function (item) { return item.id === Number(id); }); }
  function unique(items) { return items.filter(function (item, index) { return item && items.indexOf(item) === index; }); }
  function analysisIds() { return unique(String(state.analysis_parent_ids || "").split("|").map(Number).filter(Boolean)); }
  function analysisPeriods() {
    var periods = String(state.analysis_periods || "").split("|").map(function (item) { return item || "all"; });
    while (periods.length < 3) periods.push("all");
    return periods.slice(0, 3);
  }
  function saveAnalysisPeriods(periods) {
    state.analysis_periods = (periods || []).slice(0, 3).map(function (item) { return item || "all"; }).join("|");
  }
  function categoryPeriods(parentId) {
    var category = categoryById(parentId) || { children: [] };
    return unique([].concat.apply([], (category.children || []).map(function (child) { return child.periods || []; })));
  }
  function normalizeAnalysisPeriods() {
    var ids = analysisIds();
    var periods = analysisPeriods();
    ids.forEach(function (parentId, index) {
      var available = categoryPeriods(parentId);
      if (periods[index] !== "all" && available.indexOf(periods[index]) < 0) periods[index] = "all";
    });
    saveAnalysisPeriods(periods);
  }

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
    elements.labelHubTransitionPeriod.innerHTML = optionList(meta.metric_periods || [], state.transition_period, "");
    elements.labelHubChangeType.value = state.change_type;
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
      analysis_periods: state.analysis_periods,
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
  function serializeConditionMap(value) {
    return Object.keys(value).sort(function (a, b) { return Number(a) - Number(b); }).map(function (parent) {
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
    state.transition_period = state.metric_period;
    state.change_type = "all";
    changePage = 1;
    state.page = 1;
    populateControls();
    render();
  }

  function render() {
    var token = ++requestToken;
    setLoading(true);
    app.writeQueryState(state);
    if (window.updateCountryLabelHubLink) window.updateCountryLabelHubLink();
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
      loadChanges();
    }).catch(showError).then(function () { if (token === requestToken) setLoading(false); });
  }

  function buildChangeParams() {
    var params = buildParams();
    params.transition_period = state.transition_period || state.metric_period || "30d";
    params.change_type = state.change_type || "all";
    params.page = changePage;
    params.page_size = 20;
    params.sort_field = "change_type";
    params.sort_dir = "asc";
    return params;
  }

  function loadChanges() {
    if (!meta || !elements.labelHubChangeContent) return;
    var comparison = meta.comparison || {};
    if (!comparison.available) {
      elements.labelHubChangeScope.textContent = "当前远端仅有一个标签日期，暂无可比较的上次数据。";
      elements.labelHubChangeContent.innerHTML = '<div class="empty-state compact">保留当前看板展示；远端出现第二个标签日期后将自动启用变化追踪。</div>';
      elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>暂无可比较数据</strong>';
      return;
    }
    var token = ++changeRequestToken;
    elements.labelHubChangeContent.classList.add("is-loading");
    elements.labelHubChangeContent.innerHTML = '<div class="empty-state compact">正在核对两日标签与联动条件…</div>';
    elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>正在核对各层级变化…</strong>';
    app.apiGet("/api/label-hub/changes", buildChangeParams()).then(function (payload) {
      if (token !== changeRequestToken) return;
      lastChanges = payload;
      renderChanges(payload);
      applyChildChangeBadges(payload);
      if (lastPayload) renderBreakdowns(lastPayload);
      refreshChangeDetailsDrawer();
    }).catch(function (error) {
      if (token !== changeRequestToken) return;
      elements.labelHubChangeScope.textContent = "当前看板不受影响";
      elements.labelHubChangeContent.innerHTML = '<div class="empty-state compact">变化数据加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + "</div>";
      elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>变化数据暂不可用</strong>';
    }).then(function () {
      if (token === changeRequestToken) elements.labelHubChangeContent.classList.remove("is-loading");
    });
  }

  function deltaText(value) {
    var number = Number(value || 0);
    return (number > 0 ? "+" : "") + formatNumber(number);
  }

  function deltaBadge(value, label) {
    var number = Number(value || 0);
    var tone = number > 0 ? "up" : (number < 0 ? "down" : "flat");
    return '<span class="label-hub-delta is-' + tone + '" title="' + app.escapeHtml(label || "较上次") + '">' + app.escapeHtml(label || "较上次") + " " + deltaText(number) + "</span>";
  }

  function applyChildChangeBadges(payload) {
    Array.from(document.querySelectorAll(".label-hub-child-delta[data-change-injected]")).forEach(function (node) { node.remove(); });
    (payload.overview_deltas || []).forEach(function (parent) {
      (parent.children || []).forEach(function (child) {
        var childButton = document.querySelector('[data-overview-child="' + child.id + '"][data-parent-id="' + parent.id + '"]');
        var share = childButton && childButton.querySelector(":scope > span > small");
        if (!share) return;
        var badge = document.createElement("i");
        var value = Number(child.delta || 0);
        badge.className = "label-hub-child-delta is-" + (value > 0 ? "up" : (value < 0 ? "down" : "flat"));
        badge.dataset.changeInjected = "1";
        badge.textContent = "较上期 " + deltaText(value);
        share.appendChild(badge);
      });
    });
  }

  function breakdownDeltaIndex(payload) {
    var index = {};
    ((payload || {}).breakdown_deltas || []).forEach(function (panel) {
      (panel.buckets || []).forEach(function (bucket) {
        index[[panel.source || "", panel.key || "", Number(panel.parent_id || 0), String(bucket.key || "")].join("|")] = bucket;
      });
    });
    return index;
  }

  function renderLayerDelta(panel, bucket) {
    if (!lastChanges || !lastChanges.available) return "";
    var index = breakdownDeltaIndex(lastChanges);
    var key = [panel.source || "", panel.key || "", Number(panel.parent_id || 0), String(bucket.id || bucket.key || "")].join("|");
    var item = index[key];
    if (!item) return "";
    var value = Number(item.delta || 0);
    var tone = value > 0 ? "up" : (value < 0 ? "down" : "flat");
    var title = panel.label + " · " + bucket.label;
    var period = panel.source === "remote_label" ? (panel.label_period || "all") : "";
    return '<button type="button" class="label-hub-layer-delta is-' + tone + '"' +
      ' data-layer-change-detail data-layer-change-source="' + app.escapeHtml(panel.source || "") + '"' +
      ' data-layer-change-key="' + app.escapeHtml(panel.key || "") + '"' +
      ' data-layer-change-parent="' + Number(panel.parent_id || 0) + '"' +
      ' data-layer-change-bucket="' + app.escapeHtml(String(bucket.id || bucket.key || "")) + '"' +
      ' data-layer-change-period="' + app.escapeHtml(period) + '"' +
      ' data-layer-change-title="' + app.escapeHtml(title) + '"' +
      ' title="查看 ' + app.escapeHtml(title) + ' 的上期变化明细">较上期 ' + deltaText(value) + '<span>明细</span></button>';
  }

  function renderChangeBrief(payload) {
    var scope = payload.scope || {};
    var summary = payload.summary || {};
    var changed = Number(summary.changed || 0);
    var reason = (payload.sales_role_reasons || []).find(function (item) { return Number(item.count || 0) > 0; });
    var headline = changed
      ? formatNumber(changed) + " 个经营单元标签发生流转"
      : "当前群体标签结构保持稳定";
    var detail = "新增 " + formatNumber(summary.added) + " · 减少 " + formatNumber(summary.removed);
    if (reason) detail += " · 主要原因：" + reason.label;
    elements.labelHubChangeBrief.innerHTML = '<span>' + app.escapeHtml(scope.comparison_label || "较上期") + '</span><strong>' + app.escapeHtml(headline) + '</strong><small>' + app.escapeHtml(detail) + '</small>';
  }

  function renderRankList(title, items, emptyText) {
    var maximum = Math.max.apply(null, [1].concat((items || []).map(function (item) { return Number(item.count || 0); })));
    var rows = (items || []).slice(0, 6).map(function (item) {
      return '<li><div><span>' + app.escapeHtml(item.label) + '</span><strong>' + formatNumber(item.count) + '</strong></div><i style="width:' + Math.round(Number(item.count || 0) / maximum * 100) + '%"></i></li>';
    }).join("");
    return '<article class="label-hub-change-rank"><h3>' + app.escapeHtml(title) + '</h3>' + (rows ? '<ol>' + rows + '</ol>' : '<div class="empty-state compact">' + app.escapeHtml(emptyText) + '</div>') + '</article>';
  }

  function renderTransitionMatrix(matrix) {
    var rows = matrix.rows || [];
    var columns = matrix.columns || [];
    var cellMap = {};
    (matrix.cells || []).forEach(function (cell) { cellMap[cell.row + "\u0000" + cell.column] = Number(cell.count || 0); });
    var maximum = Math.max.apply(null, [1].concat((matrix.cells || []).map(function (cell) { return Number(cell.count || 0); })));
    if (!rows.length || !columns.length) return '<div class="empty-state compact">当前周期暂无标签流转。</div>';
    return '<div class="label-hub-change-matrix-wrap"><table><thead><tr><th>上次 ＼ 今日</th>' + columns.map(function (item) { return '<th>' + app.escapeHtml(item.label) + '</th>'; }).join("") + '</tr></thead><tbody>' + rows.map(function (row) {
      return '<tr><th>' + app.escapeHtml(row.label) + '</th>' + columns.map(function (column) { var count = cellMap[row.key + "\u0000" + column.key] || 0; var alpha = count ? (0.08 + count / maximum * 0.42) : 0.03; return '<td style="--cell-alpha:' + alpha.toFixed(2) + '"><strong>' + formatNumber(count) + '</strong></td>'; }).join("") + '</tr>';
    }).join("") + '</tbody></table></div>';
  }

  function renderChangeSankeyShell(payload) {
    var matrix = payload.transition_matrix || {};
    var hasFlow = (matrix.cells || []).some(function (cell) { return Number(cell.count || 0) > 0; });
    return '<section class="label-hub-change-sankey-card"><header><div><span>标签流向</span><h3>上次标签 → 今日标签</h3></div><small>线条越宽，流转的经营单元越多；悬停可查看具体数量</small></header>' +
      (hasFlow ? '<div class="label-hub-change-sankey" data-change-sankey role="img" aria-label="上次标签到今日标签的经营单元流向图"></div>' : '<div class="empty-state compact">当前筛选下暂无可展示的标签流向。</div>') +
      '</section>';
  }

  function renderChangeSankeys(payload, root) {
    var scope = root || document;
    var hosts = scope.querySelectorAll ? scope.querySelectorAll("[data-change-sankey]") : [];
    if (!hosts.length || !window.echarts) return;
    var matrix = payload.transition_matrix || {};
    var rows = matrix.rows || [];
    var columns = matrix.columns || [];
    var cells = (matrix.cells || []).filter(function (cell) { return Number(cell.count || 0) > 0; });
    var labelOrder = [];
    rows.concat(columns).forEach(function (item) {
      if (labelOrder.indexOf(item.label) < 0) labelOrder.push(item.label);
    });
    var colorFor = function (label) {
      var index = Math.max(0, labelOrder.indexOf(label));
      return REMOTE_BUCKET_COLORS[index % REMOTE_BUCKET_COLORS.length];
    };
    var outgoing = {};
    var incoming = {};
    cells.forEach(function (cell) {
      outgoing[cell.row] = (outgoing[cell.row] || 0) + Number(cell.count || 0);
      incoming[cell.column] = (incoming[cell.column] || 0) + Number(cell.count || 0);
    });
    var nodes = [];
    rows.forEach(function (item) {
      if (!outgoing[item.key]) return;
      nodes.push({
        name: "previous::" + item.key,
        displayLabel: item.label,
        value: outgoing[item.key],
        itemStyle: { color: colorFor(item.label), borderColor: "#ffffff", borderWidth: 1 }
      });
    });
    columns.forEach(function (item) {
      if (!incoming[item.key]) return;
      nodes.push({
        name: "current::" + item.key,
        displayLabel: item.label,
        value: incoming[item.key],
        itemStyle: { color: colorFor(item.label), borderColor: "#ffffff", borderWidth: 1 }
      });
    });
    var links = cells.map(function (cell) {
      return {
        source: "previous::" + cell.row,
        target: "current::" + cell.column,
        value: Number(cell.count || 0),
        previousLabel: cell.row,
        currentLabel: cell.column
      };
    });
    hosts.forEach(function (host) {
      if (!host.clientWidth) return;
      if (host.__labelHubSankey) host.__labelHubSankey.dispose();
      var chart = window.echarts.init(host, null, { renderer: "canvas" });
      host.__labelHubSankey = chart;
      chart.setOption({
        animationDuration: 350,
        aria: { enabled: true, decal: { show: false } },
        tooltip: {
          trigger: "item",
          confine: true,
          borderColor: "#cbd9e8",
          backgroundColor: "rgba(255,255,255,.97)",
          textStyle: { color: "#173653", fontSize: 12 },
          formatter: function (params) {
            if (params.dataType === "edge") {
              return app.escapeHtml(params.data.previousLabel) + " → " + app.escapeHtml(params.data.currentLabel) + "<br><b>" + formatNumber(params.value) + " 个经营单元</b>";
            }
            return app.escapeHtml(params.data.displayLabel || "") + "<br><b>" + formatNumber(params.value) + " 个经营单元</b>";
          }
        },
        series: [{
          type: "sankey",
          left: 108,
          right: 108,
          top: 24,
          bottom: 24,
          nodeWidth: 12,
          nodeGap: 16,
          nodeAlign: "justify",
          layoutIterations: 32,
          draggable: false,
          emphasis: { focus: "adjacency" },
          data: nodes,
          links: links,
          label: {
            color: "#173653",
            fontSize: 12,
            lineHeight: 17,
            formatter: function (params) {
              return (params.data.displayLabel || "") + "\n" + formatNumber(params.value);
            }
          },
          lineStyle: { color: "gradient", curveness: 0.48, opacity: 0.3 },
          itemStyle: { borderRadius: 2 }
        }]
      });
    });
  }

  function scheduleChangeSankeyRender(payload, root) {
    window.requestAnimationFrame(function () { renderChangeSankeys(payload, root); });
  }

  function disposeChangeSankeys(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-change-sankey]").forEach(function (host) {
      if (host.__labelHubSankey) {
        host.__labelHubSankey.dispose();
        host.__labelHubSankey = null;
      }
    });
  }

  function renderReasonList(items) {
    var total = (items || []).reduce(function (sum, item) { return sum + Number(item.count || 0); }, 0);
    return '<div class="label-hub-change-reasons">' + (items || []).map(function (item) {
      var share = total ? Number(item.count || 0) / total : 0;
      return '<div><span>' + app.escapeHtml(item.label) + '</span><strong>' + formatNumber(item.count) + '</strong><i style="width:' + Math.round(share * 100) + '%"></i></div>';
    }).join("") + '</div>';
  }

  function flowLabel(value) {
    return String(value || "未命中") === "未命中" ? "未命中该层" : String(value || "未命中");
  }

  function renderFlowBridge(payload) {
    var matrix = payload.transition_matrix || {};
    var cells = (matrix.cells || []).map(function (cell) {
      return { previous: cell.row, current: cell.column, count: Number(cell.count || 0) };
    });
    var stable = cells.filter(function (item) { return item.previous === item.current; }).reduce(function (sum, item) { return sum + item.count; }, 0);
    var flows = cells.filter(function (item) { return item.previous !== item.current && item.count > 0; }).sort(function (a, b) { return b.count - a.count; }).slice(0, 6);
    var flowRows = flows.map(function (item) {
      var intoLayer = item.previous === "未命中";
      var outOfLayer = item.current === "未命中";
      var tone = intoLayer ? "in" : (outOfLayer ? "out" : "shift");
      return '<li class="is-' + tone + '"><span class="label-hub-flow-label">' + app.escapeHtml(flowLabel(item.previous)) + '</span><i>→</i><span class="label-hub-flow-label">' + app.escapeHtml(flowLabel(item.current)) + '</span><strong>' + formatNumber(item.count) + '</strong></li>';
    }).join("");
    return '<section class="label-hub-flow-board"><header><div><span>标签流转</span><h3>主要流转路径</h3></div><small>优先展示实际切换；稳定标签单独汇总</small></header><div class="label-hub-flow-stats"><span><b>' + formatNumber(stable) + '</b> 保持原标签</span><span><b>' + formatNumber(flows.reduce(function (sum, item) { return sum + item.count; }, 0)) + '</b> 发生主要流转</span></div>' + (flowRows ? '<ol>' + flowRows + '</ol>' : '<div class="empty-state compact">本期没有标签切换，群体结构保持稳定。</div>') + '</section>';
  }

  function renderAuditSignals(payload, context) {
    var summary = payload.summary || {};
    var reasons = payload.sales_role_reasons || [];
    var reasonCounts = {};
    reasons.forEach(function (item) { reasonCounts[item.key] = Number(item.count || 0); });
    var evidencePending = Number(reasonCounts.evidence_missing || 0) + Number(reasonCounts.evidence_mismatch || 0);
    var parentIsSalesRole = Number((context || {}).parent || 0) === 1 || String((context || {}).title || "").indexOf("销售角色") >= 0;
    var items = parentIsSalesRole
      ? [
        { label: "日销跨线", count: reasonCounts.daily_cross || 0, tone: "attention" },
        { label: "毛利率跨线", count: reasonCounts.margin_cross || 0, tone: "attention" },
        { label: "日销与毛利率同时跨线", count: reasonCounts.both_cross || 0, tone: "risk" },
        { label: "规则证据待确认", count: evidencePending, tone: evidencePending ? "risk" : "healthy" }
      ]
      : [
        { label: "转入当前层", count: summary.added || 0, tone: "healthy" },
        { label: "转出当前层", count: summary.removed || 0, tone: "risk" },
        { label: "标签发生切换", count: summary.changed || 0, tone: "attention" },
        { label: "规则证据待确认", count: evidencePending, tone: evidencePending ? "attention" : "healthy" }
      ];
    return '<aside class="label-hub-change-audit"><header><div><span>' + (parentIsSalesRole ? "销售角色原因" : "变化信号") + '</span><h3>' + (parentIsSalesRole ? "为什么发生变化" : "优先关注什么") + '</h3></div><small>' + (parentIsSalesRole ? "仅在证据匹配时可确认规则原因" : "非销售角色仅展示事实流转与证据状态") + '</small></header><div>' + items.map(function (item) { return '<article class="is-' + item.tone + '"><span>' + app.escapeHtml(item.label) + '</span><strong>' + formatNumber(item.count) + '</strong></article>'; }).join("") + '</div></aside>';
  }

  function changeLayerLabel(context) {
    var title = String((context || {}).title || "当前层");
    var parts = title.split(" · ");
    if (title !== "当前层") return parts[parts.length - 1] || title;
    var parent = categoryById(state.parent_label_id);
    return (parent && parent.label) || title;
  }

  function renderChangeConclusion(payload, context) {
    var summary = payload.summary || {};
    var net = Number(summary.net || 0);
    var layerLabel = changeLayerLabel(context);
    var tone = net < 0 ? "improved" : (net > 0 ? "worsened" : "flat");
    var netText = net < 0 ? "净减少 " + formatNumber(Math.abs(net)) : (net > 0 ? "净增加 " + formatNumber(net) : "数量持平");
    return '<section class="label-hub-change-conclusion"><div><span>' + app.escapeHtml(layerLabel) + '</span><strong>' + formatNumber(summary.previous) + '<i>→</i>' + formatNumber(summary.current) + '</strong></div><b class="is-' + tone + '">' + netText + '</b></section>';
  }

  function renderLayerChangeLedger(payload, context) {
    var summary = payload.summary || {};
    var net = Number(summary.net || 0);
    var netText = net > 0 ? "净增加 " + formatNumber(net) : (net < 0 ? "净减少 " + formatNumber(Math.abs(net)) : "数量持平");
    var labels = (context.combination_labels || [changeLayerLabel(context)]).map(function (label) {
      return '<b>' + app.escapeHtml(label) + '</b>';
    }).join('<i>+</i>');
    return '<section class="label-hub-layer-ledger">' +
      '<header><div><span>当前组合变化账</span><h3>本次组合命中变化</h3></div><p>上次命中组合 + 本期进入 − 本期离开 = 今日命中组合</p></header>' +
      '<div class="label-hub-change-combination"><span>当前组合</span><div>' + labels + '</div></div>' +
      '<div class="label-hub-layer-ledger-row">' +
        '<div><span>上次命中组合</span><strong>' + formatNumber(summary.previous) + '</strong></div><i>+</i>' +
        '<div><span>本期进入</span><strong>' + formatNumber(summary.added) + '</strong></div><i>−</i>' +
        '<div><span>本期离开</span><strong>' + formatNumber(summary.removed) + '</strong></div><i>=</i>' +
        '<div class="is-current"><span>今日命中组合</span><strong>' + formatNumber(summary.current) + '</strong></div>' +
        '<b class="is-' + (net > 0 ? "up" : (net < 0 ? "down" : "flat")) + '">' + netText + '</b>' +
      '</div></section>';
  }

  function renderLayerTransitionSummary(payload) {
    var transitions = payload.layer_transitions || {};
    function renderSide(items, direction, title) {
      var allRows = items || [];
      var rows = allRows;
      if (!rows.length) return '<section class="label-hub-layer-transition-side"><header><span>' + title + '</span><small>本期无记录</small></header><p>没有经营单元在本期发生这类变化。</p></section>';
      var total = allRows.reduce(function (sum, item) { return sum + Number(item.count || 0); }, 0);
      return '<section class="label-hub-layer-transition-side"><header><span>' + title + '</span><small>共 ' + formatNumber(total) + ' 个经营单元</small></header><div>' + rows.map(function (item) {
        return '<button type="button" data-layer-transition-type="' + direction + '" data-layer-transition-from="' + app.escapeHtml(item.previous_label || "无标签事实") + '" data-layer-transition-to="' + app.escapeHtml(item.current_label || "无标签事实") + '"><span>' + app.escapeHtml(item.previous_label || "无标签事实") + '</span><i>→</i><strong>' + app.escapeHtml(item.current_label || "无标签事实") + '</strong><b>' + formatNumber(item.count) + '</b></button>';
      }).join('') + '</div></section>';
    }
    return '<section class="label-hub-layer-transition-summary"><header><div><span>本层标签变化汇总</span><h3>从哪里进入，去了哪里</h3></div><small>仅统计当前组合中本期进入或离开的经营单元；点击一行查看对应明细。</small></header><div class="label-hub-layer-transition-grid">' +
      renderSide(transitions.entered, "added", "进入来源") + renderSide(transitions.left, "removed", "离开去向") +
      '</div></section>';
  }

  function renderLayerChangeFilters(payload, selectedType) {
    var summary = payload.summary || {};
    var items = [
      ["added", "查看进入", summary.added || 0],
      ["removed", "查看离开", summary.removed || 0]
    ];
    return '<div class="label-hub-change-filter-tabs" role="group" aria-label="变化明细筛选">' + items.map(function (item) {
      return '<button type="button" class="' + (selectedType === item[0] ? "active" : "") + '" data-layer-change-type="' + item[0] + '" aria-pressed="' + (selectedType === item[0]) + '">' + item[1] + ' <b>' + formatNumber(item[2]) + '</b></button>';
    }).join("") + '</div>';
  }

  function renderChangeList(payload, context) {
    var isLayerDetail = Boolean(context);
    var layerLabel = isLayerDetail ? changeLayerLabel(context) : "";
    var conditionStateHtml = function (conditions) {
      if (!conditions || !conditions.length) return '<span class="label-hub-change-condition-empty">无额外条件</span>';
      var inCombination = conditions.every(function (condition) { return Boolean(condition.matched); });
      return '<div class="label-hub-change-condition-list"><span class="label-hub-change-combination-state ' + (inCombination ? "is-in" : "is-out") + '">' + (inCombination ? "已进入组合" : "未进入组合") + '</span>' + conditions.map(function (condition) {
        var state = condition.matched ? "is-matched" : "is-unmatched";
        return '<div class="label-hub-change-condition ' + state + '">' +
          '<span>' + app.escapeHtml(condition.dimension || "条件") + '</span>' +
          '<strong>' + app.escapeHtml(condition.value || "无标签事实") + '</strong>' +
          '<em>' + (condition.matched ? "满足" : "未满足") + '</em>' +
        '</div>';
      }).join("") + '</div>';
    };
    var rows = (payload.rows || []).map(function (row) {
      var typeLabel = { added: "转入", removed: "转出", changed: "标签切换", unchanged: "保持" }[row.change_type] || row.change_type_label;
      var previousValue = row.previous_label || "未命中";
      var currentValue = row.current_label || "未命中";
      if (isLayerDetail) {
        var metric = row.metric_profile || {};
        var profitClass = Number(metric.order_gross_profit || 0) < 0 ? ' is-negative' : '';
        var metricProfile = '<div class="label-hub-change-metric-stack"><span>' + app.escapeHtml(metric.sales_trend || "暂无数据") + ' · ' + app.escapeHtml(metric.daily_sales_band || "暂无数据") + '</span><span>' + app.escapeHtml(metric.margin_band || "暂无数据") + '</span></div>';
        var performance = '<div class="label-hub-change-metric-stack"><strong>' + app.formatCompactCurrency(metric.sales_amount || 0) + '</strong><span class="' + profitClass + '">毛利 ' + app.formatCompactCurrency(metric.order_gross_profit || 0) + ' · ' + formatPercent(metric.order_gross_margin || 0) + '</span></div>';
        var scope = '<div class="label-hub-change-scope"><span title="' + app.escapeHtml(row.previous_unit_scope || "无标签事实") + '">上 ' + app.escapeHtml(row.previous_unit_scope || "无标签事实") + '</span><span title="' + app.escapeHtml(row.current_unit_scope || "无标签事实") + '">今 ' + app.escapeHtml(row.current_unit_scope || "无标签事实") + '</span></div>';
        return '<tr><td>' + app.escapeHtml(row.country_category || "-") + '</td><td>' + app.escapeHtml(row.store || "-") + '</td><td><button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button></td><td>' + conditionStateHtml(row.previous_combination_conditions) + '</td><td>' + conditionStateHtml(row.current_combination_conditions) + '</td><td>' + app.escapeHtml(row.previous_layer_label || "未命中") + '</td><td>' + app.escapeHtml(row.current_layer_label || "未命中") + '</td><td>' + scope + '</td><td>' + metricProfile + '</td><td>' + performance + '</td><td><span class="label-hub-change-status">' + app.escapeHtml(metric.data_status || "暂无经营数据") + '</span></td><td>' + app.escapeHtml(row.fact_status || "标签事实可比") + '</td></tr>';
      }
      return '<tr><td>' + app.escapeHtml(row.country_category || "-") + '</td><td>' + app.escapeHtml(row.store || "-") + '</td><td><button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button></td><td>' + app.escapeHtml(previousValue) + '</td><td>' + app.escapeHtml(currentValue) + '</td><td><span class="label-hub-change-type is-' + app.escapeHtml(row.change_type) + '">' + app.escapeHtml(typeLabel) + '</span></td></tr>';
    }).join("");
    var pagination = '<div class="label-hub-change-pagination"><span>第 ' + payload.page + " / " + payload.total_pages + ' 页，共 ' + formatNumber(payload.total) + ' 个经营单元</span><div><button type="button" data-change-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><button type="button" data-change-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + '>下一页</button></div></div>';
    if (isLayerDetail) {
      return '<div class="label-hub-change-table-wrap"><table><thead><tr><th>国家类别</th><th>店铺</th><th>MSKU</th><th>上次组合条件</th><th>今日组合条件</th><th>上次同维度标签</th><th>今日同维度标签</th><th>经营范围（上 / 今）</th><th>今日经营分层</th><th>今日经营表现</th><th>本地指标</th><th>标签事实状态</th></tr></thead><tbody>' + (rows || '<tr><td colspan="12"><div class="empty-state compact">当前组合下没有变化经营单元。</div></td></tr>') + '</tbody></table></div>' + pagination;
    }
    return '<div class="label-hub-change-table-wrap"><table><thead><tr><th>国家类别</th><th>店铺</th><th>MSKU</th><th>上次标签</th><th>今日标签</th><th>变化方向</th></tr></thead><tbody>' + (rows || '<tr><td colspan="6"><div class="empty-state compact">当前筛选下没有变化经营单元。</div></td></tr>') + '</tbody></table></div>' + pagination;
  }

  function renderChangeRows(payload) {
    var rows = (payload.rows || []).map(function (row) {
      var reason = row.sales_role_reason || "仅记录标签事实流转";
      return '<tr><td>' + app.escapeHtml(row.country_category || "-") + '</td><td>' + app.escapeHtml(row.store || "-") + '</td><td><button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button></td><td>' + app.escapeHtml(row.previous_label || "未命中") + '</td><td>' + app.escapeHtml(row.current_label || "未命中") + '</td><td><span class="label-hub-change-type is-' + app.escapeHtml(row.change_type) + '">' + app.escapeHtml(row.change_type_label) + '</span></td><td>' + app.escapeHtml((row.trigger_dimensions || []).join(" / ") || "无标签维度变化") + '</td><td>' + (row.previous_matched ? "是" : "否") + '</td><td>' + (row.current_matched ? "是" : "否") + '</td><td title="' + app.escapeHtml(reason) + '">' + app.escapeHtml(reason) + '</td></tr>';
    }).join("");
    var pagination = '<div class="label-hub-change-pagination"><span>第 ' + payload.page + " / " + payload.total_pages + ' 页，共 ' + formatNumber(payload.total) + ' 个经营单元</span><div><button type="button" data-change-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><button type="button" data-change-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + '>下一页</button></div></div>';
    return '<div class="label-hub-change-table-wrap"><table><thead><tr><th>国家类别</th><th>店铺</th><th>MSKU</th><th>上次主标签</th><th>今日主标签</th><th>变化类型</th><th>触发维度</th><th>上次满足</th><th>今日满足</th><th>销售角色原因摘要</th></tr></thead><tbody>' + (rows || '<tr><td colspan="10"><div class="empty-state compact">当前变化类型下没有经营单元。</div></td></tr>') + '</tbody></table></div>' + pagination;
  }

  function changeContentHtml(payload, context) {
    if (!payload.available) return '<div class="empty-state compact">暂无可比较的上次标签数据。</div>';
    return (context ? renderLayerChangeLedger(payload, context) + renderLayerTransitionSummary(payload) : renderChangeConclusion(payload, context)) +
      '<article class="label-hub-change-detail"><header><div><span>变化经营单元明细</span><h3>' + (context ? '仅查看进入或离开当前组合的经营单元' : '仅查看发生标签变化的经营单元') + '</h3></div><small>点击 MSKU 查看两日标签画像</small></header>' +
      (context ? renderLayerChangeFilters(payload, context.change_type || "all") : "") + renderChangeList(payload, context) + '</article>';
  }

  function renderChanges(payload) {
    if (!payload.available) {
      elements.labelHubChangeContent.innerHTML = changeContentHtml(payload);
      return;
    }
    var scope = payload.scope || {};
    var gapText = Number(scope.gap_days || 0) === 1 ? "相邻两次数据" : "间隔 " + formatNumber(scope.gap_days) + " 天";
    elements.labelHubChangeScope.textContent = (scope.comparison_label || "较上次数据") + "：" + scope.previous_date + " → " + scope.current_date + " · " + gapText + " · " + String(scope.transition_period || "30d").replace("d", "天") + "同周期比较";
    renderChangeBrief(payload);
    elements.labelHubChangeContent.innerHTML = changeContentHtml(payload);
  }

  function setLoading(active) {
    var main = document.querySelector(".main-content");
    if (!main) return;
    main.classList.toggle("page-loading", active);
    main.setAttribute("aria-busy", active ? "true" : "false");
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
      return '<button type="button" class="label-hub-child' + (checked ? " selected" : "") + '" data-overview-child="' + child.id + '" data-parent-id="' + item.id + '" aria-pressed="' + checked + '" title="' + app.escapeHtml(child.rule || child.definition || child.label) + '"><span><b>' + app.escapeHtml(child.label) + '</b><small>' + formatPercent(scoped.share) + '</small></span><strong>' + formatNumber(scoped.count) + '<small> 经营单元</small></strong></button>';
    }).join("");
    var periods = (item.periods || []).join(" / ") || "无周期";
    var note = item.mutual_exclusion ? "同周期互斥" : "允许标签共现";
    var aggregationRule = item.aggregation_rule || "同一经营单元按业务优先级只保留一个主标签。";
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
    var conditionText = conditionCount ? formatNumber(conditionCount) + " 个标签/联动条件" : "当前父标签全部经营单元";
    var subjectHtml = '<div class="label-hub-diagnosis-subject"><span>当前分析对象</span><h3>' + app.escapeHtml(subject.parent_label || (payload.rules || {}).label || "当前标签") + '</h3><strong>' + formatNumber(total) + ' <small>经营单元</small></strong><p>' + app.escapeHtml(conditionText) + ' · 指标覆盖 ' + formatPercent(coverageRate) + "</p></div>";
    var signalHtml = issues.map(function (item) {
      var available = !item.local || localAvailable;
      var count = Number(counts[item.key] || 0);
      var rate = total ? count / total : 0;
      var active = state.problem === item.key;
      return '<button type="button" class="label-hub-diagnosis-item ' + item.tone + (active ? " active" : "") + '"' + (available ? ' data-problem="' + item.key + '"' : " disabled") + ' aria-pressed="' + active + '"><span><b>' + app.escapeHtml(item.label) + '</b>' + (active ? '<em>已筛选</em>' : "") + '</span><strong>' + (available ? formatNumber(count) + ' <i>经营单元</i>' : "—") + '</strong><small>' + (available ? "占当前群体 " + formatPercent(rate) : "本地经营指标暂不可用") + "</small></button>";
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
    destroyLinkedSelects();
    elements.labelHubBreakdowns.innerHTML = [
      renderBreakdownGroup("经营表现", "本地周期快照", panels.filter(function (panel) { return panel.source === "local"; })),
      renderBreakdownGroup("远端标签结构", "标签事实 · 可切换维度", panels.filter(function (panel) { return panel.source === "remote_label"; }))
    ].join("");
    initLinkedSelects();

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
        : "分析口径 " + formatNumber(panel.denominator) + " 个经营单元";
      var header = '<div><span class="label-hub-source ' + panel.source + '">' + (panel.source === "local" ? "本地经营" : "远端标签") + '</span><h3>' + app.escapeHtml(panel.label) + '</h3><small>' + scopeCopy + "</small></div>";
      if (panel.source === "remote_label") {
        var slot = Number.isFinite(Number(panel.analysis_slot)) ? Number(panel.analysis_slot) : Math.max(0, selectedRemote.indexOf(Number(panel.parent_id)));
        var used = selectedRemote.filter(function (_, index) { return index !== slot; });
        var options = (meta.categories || []).filter(function (item) { return item.id !== state.parent_label_id && used.indexOf(item.id) < 0; });
        var activePeriod = panel.label_period || "all";
        header += '<div class="label-hub-card-selectors">' +
          '<label class="label-hub-dimension-select"><span>联动维度</span><select aria-label="切换' + app.escapeHtml(panel.label) + '维度" data-analysis-slot="' + slot + '">' + optionList(options, panel.parent_id, "") + "</select></label>" +
          '<label class="label-hub-period-select"><span>标签周期</span><select aria-label="切换' + app.escapeHtml(panel.label) + '标签周期" data-analysis-period-slot="' + slot + '">' + optionList(panel.periods || [], activePeriod, "全部周期") + "</select></label>" +
          "</div>";
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
        return '<div class="label-hub-bar tone-' + tone + (selected ? " selected" : "") + '"' + bucketColorStyle + ' data-negative="' + (Number(bucket.order_gross_profit || 0) < 0) + '><button type="button" class="label-hub-bar-filter" ' + attributes + ' aria-pressed="' + selected + '"><span class="label-hub-bar-label"><b>' + app.escapeHtml(label) + (String(bucket.key) === "missing" ? '<i class="label-hub-info" title="标签归属键在当前经营周期内没有对应快照">i</i>' : "") + '</b><small>' + app.escapeHtml(detail) + '</small></span></button><div class="label-hub-bar-value"><strong>' + formatMeasure(bucket) + '</strong>' + renderLayerDelta(panel, bucket) + '</div><small class="label-hub-bar-profit">' + auxiliaryMeasure(bucket) + "</small></div>";
      }).join("");
      var ruleDetails = (panel.rules || []).length
        ? '<details class="label-hub-breakdown-rules"><summary>查看趋势划分规则</summary><p>' + app.escapeHtml(panel.description || "") + '</p><dl>' + panel.rules.map(function (rule) { return '<div><dt>' + app.escapeHtml(rule.label) + '</dt><dd>' + app.escapeHtml(rule.rule) + "</dd></div>"; }).join("") + "</dl></details>"
        : "";
      return '<article class="label-hub-breakdown-card"><header>' + header + "</header>" + finding + composition + '<div class="label-hub-bars">' + bars + "</div>" + ruleDetails + "</article>";
    }
  }

  function destroyLinkedSelects() {
    linkedSelectInstances.forEach(function (instance) { instance.destroy(); });
    linkedSelectInstances = [];
  }

  function initLinkedSelects() {
    if (!window.SlimSelect) return;
    Array.from(elements.labelHubBreakdowns.querySelectorAll("[data-analysis-slot], [data-analysis-period-slot]")).forEach(function (select) {
      linkedSelectInstances.push(new window.SlimSelect({
        select: select,
        settings: {
          showSearch: false,
          modal: "off",
          contentPosition: "absolute",
          openPosition: "auto"
        }
      }));
    });
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
    elements.labelHubMatrix.innerHTML = '<div class="label-hub-matrix-legend"><span>经营单元数</span><small>低</small><i class="heat-level-1"></i><i class="heat-level-2"></i><i class="heat-level-3"></i><i class="heat-level-4"></i><small>高</small></div><div class="label-hub-matrix-table" style="grid-template-columns: 120px repeat(' + columns.length + ', minmax(96px, 1fr))"><div></div>' + columns.map(function (column) { return '<strong>' + app.escapeHtml(column.label) + "</strong>"; }).join("") + rows.map(function (row) { return '<strong>' + app.escapeHtml(row.label) + '</strong>' + columns.map(function (column) { var cell = cells[row.id + "|" + column.id] || { count: 0 }; return '<button type="button" class="heat-level-' + matrixHeatLevel(cell.count, maxCount) + '" data-matrix-row="' + row.id + '" data-matrix-col="' + column.id + '"><b>' + formatNumber(cell.count) + '</b><small>' + app.formatCompactCurrency(cell.sales_amount || 0) + "</small></button>"; }).join(""); }).join("") + "</div>";
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

  function renderCountryProfileCell(params) {
    if (!params.data || !params.data.country_category || !params.data.store || !params.data.msku) {
      return '<span class="label-hub-country-profile-empty">暂无国家画像</span>';
    }
    return '<button type="button" class="label-hub-country-profile-button" data-country-profile>查看国家画像</button>';
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
    elements.labelHubRuleDrawerContent.innerHTML = '<div class="label-hub-rule-summary"><span>' + app.escapeHtml(stateLabel) + '</span><span>' + formatNumber(children.length) + ' 个子标签</span><span>' + app.escapeHtml(allPeriods.join(" / ") || "无周期配置") + '</span><span>' + app.escapeHtml(category.mutual_exclusion ? "同周期互斥" : "允许共现") + '</span></div><div class="label-hub-rule-priority"><b>主标签优先级</b><span>' + app.escapeHtml(aggregationPriority.join(" ＞ ") || "按标签详情表顺序") + '</span><small>同一国家类别、店铺、MSKU 经营单元命中多个子标签时，只保留优先级最高的一项用于上方聚合分析；底部明细保留原始事实。</small></div><div class="label-hub-rule-table-head"><span>子标签</span><span>核心划分规则</span><span>周期</span><span>状态</span><span>操作</span></div><div class="label-hub-rule-detail-list">' + (ruleCards || '<div class="empty-state compact">该分类暂未配置子标签规则。</div>') + '</div>';
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
      onCellClicked: function (event) {
        if (event.colDef && event.colDef.field === "country_profile") openCountryProfileDrawer(event.data);
      },
      onRowClicked: function (event) {
        if (!event.data || (event.event && event.event.target.closest("[data-country-profile]"))) return;
        openDrawer(event.data);
      }
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

  function countryProfileColumn() {
    return { headerName: "国家画像", field: "country_profile", width: 132, sortable: false, filter: false, cellClass: "label-country-profile-cell", cellRenderer: renderCountryProfileCell };
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
      countryProfileColumn(),
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
      countryProfileColumn(),
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
    setDrawerMode("profile");
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

  function countryProfileCompactTag(title, item, emptyText) {
    if (!item) return '<span class="label-hub-country-compact-tag is-empty"><i>' + app.escapeHtml(title) + '</i><b>' + app.escapeHtml(emptyText || "未命中") + '</b></span>';
    var tone = /问题|风险|异常|停售|断货|清仓|亏损/.test(String(item.label || "")) ? " is-risk" : "";
    var extra = item.multiple ? '<small>多标签</small>' : "";
    return '<details class="label-hub-country-compact-tag' + tone + '"><summary><i>' + app.escapeHtml(title) + '</i><b>' + app.escapeHtml(item.label || "未命中") + '</b>' + (item.period ? '<em>' + app.escapeHtml(item.period) + '</em>' : "") + extra + '</summary><p><strong>规则：</strong>' + app.escapeHtml(item.rule || item.definition || "暂无规则说明") + '</p><span>负责人：' + app.escapeHtml(item.owner || "未配置") + '</span></details>';
  }

  function countryProfileCountryTagsCell(item) {
    var lifecycleItems = item.site_lifecycle || [];
    var lifecycle = lifecycleItems.length ? {
      label: lifecycleItems.map(function (entry) { return entry.label; }).join(" / "),
      period: lifecycleItems.map(function (entry) { return entry.period; }).filter(Boolean).join(" / "),
      rule: lifecycleItems[0].rule || lifecycleItems[0].definition,
      owner: lifecycleItems[0].owner,
      multiple: lifecycleItems.length > 1
    } : null;
    return '<div class="label-hub-country-tag-group">' +
      countryProfileCompactTag("定价", item.pricing) +
      countryProfileCompactTag("站点状态", item.site_status) +
      countryProfileCompactTag("站点生命周期", lifecycle) +
      '</div>';
  }

  function countryProfileSalesRolesCell(salesRoles) {
    return '<div class="label-hub-country-role-grid">' + ["7d", "14d", "30d", "90d"].map(function (period) {
      return countryProfileCompactTag(period, (salesRoles || {})[period], "暂无标签");
    }).join("") + '</div>';
  }

  function countryProfileCountryCell(item) {
    var marginInterval = item.price_margin_interval || "--";
    return '<div class="label-hub-country-name"><b>' + app.escapeHtml(item.country || "未配置国家") + '</b><small>' + app.escapeHtml(marginInterval) + '</small></div>';
  }

  function countryProfilePriceCell(price, priceStatus) {
    if (priceStatus === "unavailable") return '<span class="label-hub-country-price is-warning">价格服务暂不可用</span>';
    if (!price || !price.available) return '<span class="label-hub-country-price is-empty">暂无当前价格</span>';
    var local = price.value === null || price.value === undefined ? "--" : formatNumber(price.value);
    return '<span class="label-hub-country-price"><b>' + local + '</b></span>';
  }

  function countryProfileMoney(value) {
    return value === null || value === undefined ? "--" : "¥" + formatNumber(value);
  }

  function countryProfileValue(value, fallback) {
    return value === null || value === undefined ? (fallback || "--") : formatNumber(value);
  }

  function countryProfileMetricRow(label, value, tone) {
    return '<span class="label-hub-country-metric-row' + (tone ? " " + tone : "") + '"><i>' + app.escapeHtml(label) + '</i><b>' + value + '</b></span>';
  }

  function countryProfileRankCell(metrics, metricStatus) {
    if (metricStatus === "unavailable") return '<span class="label-hub-country-metrics is-empty">排名快照暂不可用</span>';
    if (!metrics || !Object.keys(metrics).length) return '<span class="label-hub-country-metrics is-empty">暂无排名快照</span>';
    var ranking = metrics.small_category_ranking === null || metrics.small_category_ranking === undefined || Number(metrics.small_category_ranking) <= 0
      ? "--"
      : formatNumber(metrics.small_category_ranking);
    return '<strong class="label-hub-country-rank-value">' + app.escapeHtml(ranking) + '</strong>';
  }

  function countryProfileLimitPriceCell(limitPrices, price, limitPriceStatus) {
    if (limitPriceStatus === "unavailable") return '<span class="label-hub-country-metrics is-empty">毛利定价暂不可用</span>';
    if (!limitPrices || !limitPrices.available) return '<span class="label-hub-country-metrics is-empty">暂无毛利定价</span>';
    var tiers = Array.isArray(limitPrices.margin_prices) ? limitPrices.margin_prices : [
      { margin: 35, value: limitPrices.margin_price_35 },
      { margin: 10, value: limitPrices.margin_price_10 }
    ];
    var rows = tiers.filter(function (item) {
      return item && item.value !== null && item.value !== undefined;
    }).map(function (item) {
      return countryProfileMetricRow(String(item.margin) + '% 毛利', formatNumber(item.value));
    });
    if (!rows.length) return '<span class="label-hub-country-metrics is-empty">暂无毛利定价</span>';
    return '<div class="label-hub-country-metrics is-limit-price label-hub-country-price-ladder">' +
      rows.join("") +
      '<small>按最新限价快照</small></div>';
  }

  function countryProfileMetricsCell(metrics, metricPeriod, metricStatus) {
    if (metricStatus === "unavailable") return '<span class="label-hub-country-metrics is-empty">经营快照暂不可用</span>';
    if (!metrics || !Object.keys(metrics).length) return '<span class="label-hub-country-metrics is-empty">暂无该国经营快照</span>';
    var margin = metrics.order_gross_margin === null || metrics.order_gross_margin === undefined ? "--" : formatPercent(metrics.order_gross_margin);
    var quantity = countryProfileValue(metrics.sales_qty, "0") + ' <em>· 日均 ' + countryProfileValue(metrics.daily_sales, "0") + '</em>';
    return '<div class="label-hub-country-metrics is-compact-operating">' +
      countryProfileMetricRow('销量', quantity) +
      countryProfileMetricRow('销售额', countryProfileMoney(metrics.sales_amount)) +
      countryProfileMetricRow('订单毛利', countryProfileMoney(metrics.order_gross_profit), Number(metrics.order_gross_profit || 0) < 0 ? 'is-negative' : '') +
      countryProfileMetricRow('订单毛利率', margin) +
      '</div>';
  }

  function countryProfileTrafficCell(metrics, metricStatus) {
    if (metricStatus === "unavailable" || !metrics || !Object.keys(metrics).length) return '<span class="label-hub-country-metrics is-empty">--</span>';
    var tacos = Number(metrics.sales_amount || 0) > 0 ? formatPercent(Number(metrics.ad_spend || 0) / Number(metrics.sales_amount || 0)) : "--";
    return '<div class="label-hub-country-metrics is-compact-traffic">' +
      countryProfileMetricRow('Sessions', countryProfileValue(metrics.sessions_total, "0")) +
      countryProfileMetricRow('广告花费', countryProfileMoney(metrics.ad_spend)) +
      countryProfileMetricRow('广告销售', countryProfileMoney(metrics.ad_sales)) +
      countryProfileMetricRow('TACOS', tacos) +
      countryProfileMetricRow('退货', countryProfileValue(metrics.return_count, "0") + ' <em>· ' + countryProfileMoney(metrics.return_amount) + '</em>') +
      countryProfileMetricRow('可售库存', countryProfileValue(metrics.ending_inventory_qty, "--")) +
      '</div>';
  }

  function countryProfileRiskSummary(countries) {
    var risk = { pricing: 0, status: 0, role: 0, lifecycle: 0, conflict: 0 };
    (countries || []).forEach(function (item) {
      var salesRoles = item.sales_roles || {};
      if (item.pricing && /清仓|风险|亏损|超额/.test(String(item.pricing.label || ""))) risk.pricing += 1;
      if (item.site_status && /异常|停售|断货|退品/.test(String(item.site_status.label || ""))) risk.status += 1;
      if (Object.keys(salesRoles).some(function (period) { return /问题|瘦狗/.test(String((salesRoles[period] || {}).label || "")); })) risk.role += 1;
      if ((item.site_lifecycle || []).some(function (entry) { return /衰退/.test(String(entry.label || "")); })) risk.lifecycle += 1;
      if ((item.conflict_parent_ids || []).length) risk.conflict += 1;
    });
    return risk;
  }

  function countryProfileOperatingSummary(countries) {
    var totals = { sales_qty: 0, sales_amount: 0, order_gross_profit: 0, ad_spend: 0, matched: 0 };
    (countries || []).forEach(function (item) {
      var metric = item.metrics || {};
      if (!Object.keys(metric).length) return;
      totals.matched += 1;
      ["sales_qty", "sales_amount", "order_gross_profit", "ad_spend"].forEach(function (field) {
        totals[field] += Number(metric[field] || 0);
      });
    });
    totals.tacos = totals.sales_amount > 0 ? totals.ad_spend / totals.sales_amount : null;
    return totals;
  }

  function countryProfileDetailHead(identity, summary, operating, scope, row) {
    var title = [
      identity.msku || row.msku || "--",
      identity.store || row.store || "--",
      identity.country_category || row.country_category || "--"
    ].map(function (value) { return app.escapeHtml(String(value)); }).join(" / ");
    var subtitle = [
      identity.sku || '--',
      "覆盖 " + formatNumber(summary.country_count || 0) + " 个国家",
      (scope.metric_period || "30d") + " 销量 " + formatNumber(operating.sales_qty)
    ].map(function (value) { return app.escapeHtml(String(value)); }).join(" · ");
    return '<section class="label-hub-country-profile-detail-head">' +
      '<p class="section-kicker">国家明细</p>' +
      '<h2>' + title + '</h2>' +
      '<p class="label-hub-country-profile-detail-subtitle">' + subtitle + '</p>' +
      '<div class="label-hub-country-profile-detail-note">该明细用于查看国家标签、价格与经营表现；日均销量按有库存天数计算。</div>' +
      '</section>';
  }

  function renderCountryProfileDrawer(profile, row) {
    var identity = profile.identity || {};
    var scope = profile.scope || {};
    var summary = profile.summary || {};
    var countries = profile.countries || [];
    var risk = countryProfileRiskSummary(countries);
    var operating = countryProfileOperatingSummary(countries);
    var tagCoverage = countries.length ? Math.round(Number(summary.complete_label_country_count || 0) / countries.length * 100) : 0;
    var riskNotes = [
      risk.pricing ? '<span class="is-risk">定价关注 ' + formatNumber(risk.pricing) + '</span>' : "",
      risk.status ? '<span class="is-risk">站点异常 ' + formatNumber(risk.status) + '</span>' : "",
      risk.role ? '<span class="is-risk">问题/瘦狗 ' + formatNumber(risk.role) + '</span>' : "",
      risk.lifecycle ? '<span class="is-warning">衰退期 ' + formatNumber(risk.lifecycle) + '</span>' : "",
      risk.conflict ? '<span class="is-warning">标签冲突 ' + formatNumber(risk.conflict) + '</span>' : ""
    ].filter(Boolean).join("") || '<span class="is-normal">当前未发现重点风险标签</span>';
    var rows = countries.map(function (item) {
      var salesRoles = item.sales_roles || {};
      var completeness = item.data_status === "complete" ? "标签完整" : "标签部分缺失";
      if (scope.listing_price_status === "unavailable") completeness += " · 价格服务不可用";
      else if (!item.price || !item.price.available) completeness += " · 缺少价格";
      if ((item.conflict_parent_ids || []).length) completeness += " · 存在冲突";
      return '<tr><td class="label-hub-country-identity">' + countryProfileCountryCell(item) + '</td><td class="label-hub-country-profile-price-cell">' + countryProfilePriceCell(item.price, scope.listing_price_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileRankCell(item.metrics, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileMetricsCell(item.metrics, scope.metric_period, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileTrafficCell(item.metrics, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileLimitPriceCell(item.limit_prices, item.price, scope.limit_price_status) + '</td><td class="label-hub-country-profile-tag-cell">' + countryProfileCountryTagsCell(item) + '</td><td class="label-hub-country-profile-role-cell">' + countryProfileSalesRolesCell(salesRoles) + '</td></tr>';
    }).join("");
    var priceDate = scope.price_snapshot_date || "暂无价格快照";
    var metricWindow = scope.metric_window || {};
    var metricTitle = app.escapeHtml(scope.metric_period || "30d") + ' 经营表现';
    var metricHint = metricWindow.period_start && metricWindow.period_end ? app.escapeHtml(metricWindow.period_start + ' 至 ' + metricWindow.period_end) : '经营快照暂不可用';
    var detailHead = countryProfileDetailHead(identity, summary, operating, scope, row);
    elements.labelHubCountryProfileContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">MSKU 国家画像</p><h2 id="labelHubCountryProfileTitle">' + app.escapeHtml(identity.msku || row.msku) + '</h2><p>' + app.escapeHtml(identity.country_category || row.country_category) + ' · ' + app.escapeHtml(identity.store || row.store) + '</p><div class="label-hub-country-profile-scope"><span>标签 ' + app.escapeHtml(scope.label_date || "--") + '</span><span>价格快照 ' + app.escapeHtml(priceDate) + '</span><span>经营窗口 ' + metricHint + '</span></div></div><section class="label-hub-country-profile-overview"><div class="label-hub-country-profile-metric"><span>覆盖国家</span><strong>' + formatNumber(summary.country_count || 0) + '</strong><small>当前店铺下同一 MSKU</small></div><div class="label-hub-country-profile-metric"><span>标签完整率</span><strong>' + tagCoverage + '%</strong><small>' + formatNumber(summary.complete_label_country_count || 0) + ' 个国家标签完整</small></div><div class="label-hub-country-profile-metric"><span>' + app.escapeHtml(scope.metric_period || "30d") + ' 销量汇总</span><strong>' + formatNumber(operating.sales_qty) + '</strong><small>' + formatNumber(operating.matched) + ' 个国家有经营快照</small></div><div class="label-hub-country-profile-metric"><span>销售额汇总</span><strong>' + app.formatCompactCurrency(operating.sales_amount) + '</strong><small>订单毛利 ' + app.formatCompactCurrency(operating.order_gross_profit) + '</small></div><div class="label-hub-country-profile-metric"><span>TACOS</span><strong>' + (operating.tacos === null ? "--" : formatPercent(operating.tacos)) + '</strong><small>广告花费 ÷ 销售额</small></div><div class="label-hub-country-profile-metric"><span>价格缺失</span><strong>' + formatNumber(summary.missing_price_country_count || 0) + '</strong><small>不影响标签展示</small></div></section><section class="label-hub-country-profile-alerts"><div><b>重点关注</b><span>基于当前国家标签自动汇总</span></div><p>' + riskNotes + '</p></section>' + detailHead + '<section class="label-hub-country-profile-section"><div class="label-hub-country-profile-section-head"><div><h3>逐国标签、价格与经营表现</h3><p>经营指标取本地 ' + metricTitle + '；小类排名取经营窗口最后一天，毛利定价取最新限价快照。</p></div><span class="label-hub-country-profile-table-hint">固定国家、价格与排名列</span></div><div class="label-hub-country-profile-table-wrap"><table class="label-hub-country-profile-table"><thead><tr><th>国家</th><th>当前 listing 价格</th><th>小类排名</th><th>' + metricTitle + '</th><th>流量与广告</th><th>毛利定价</th><th>定价标签</th><th>站点状态</th><th>站点生命周期</th><th>7d 国家销售角色</th><th>14d 国家销售角色</th><th>30d 国家销售角色</th><th>90d 国家销售角色</th><th>数据完整性</th></tr></thead><tbody>' + rows + '</tbody></table></div></section>';
    var countryProfileTable = elements.labelHubCountryProfileContent.querySelector(".label-hub-country-profile-table");
    if (countryProfileTable) {
      countryProfileTable.querySelector("thead tr").innerHTML = [
        "<th>国家</th>",
        "<th>当前 listing 价格</th>",
        "<th><span>小类排名<small>（经营窗口最后一天）</small></span></th>",
        "<th>" + metricTitle + "</th>",
        "<th>流量与广告</th>",
        "<th>毛利定价</th>",
        "<th>国家标签</th>",
        "<th><span>国家销售角色<small>（分周期）</small></span></th>"
      ].join("");
    }
  }

  function openCountryProfileDrawer(row) {
    if (!row) return;
    elements.labelHubCountryProfileDrawer.hidden = false;
    elements.labelHubCountryProfileContent.innerHTML = '<div class="empty-state compact">正在加载国家画像…</div>';
    app.apiGet("/api/label-hub/msku-country-profile", {
      country_category: row.country_category,
      store: row.store,
      msku: row.msku,
      metric_period: state.metric_period || "30d"
    }).then(function (profile) {
      renderCountryProfileDrawer(profile, row);
      elements.labelHubCountryProfileClose.focus();
    }).catch(function (error) {
      var message = (error && error.message) || "请稍后重试";
      elements.labelHubCountryProfileContent.innerHTML = '<div class="empty-state compact">国家画像加载失败：' + app.escapeHtml(message) + '</div>';
    });
  }

  function closeCountryProfileDrawer() {
    elements.labelHubCountryProfileDrawer.hidden = true;
  }

  function renderChangeDay(day, title) {
    var units = day.units || [];
    return '<article class="label-hub-trace-day"><header><span>' + app.escapeHtml(title) + '</span><strong>' + app.escapeHtml(day.data_date || "--") + '</strong><small>' + formatNumber(units.length) + ' 个经营单元</small></header><div>' + (units.map(function (unit) {
      var labels = (unit.labels || []).map(function (item) { return '<span><b>' + app.escapeHtml(item.parent_label) + '</b>' + app.escapeHtml(item.label) + '<i>' + app.escapeHtml(item.period || "无周期") + '</i></span>'; }).join("");
      return '<section><p>' + app.escapeHtml(unit.country_category) + ' · ' + app.escapeHtml(unit.store) + '</p><div>' + labels + '</div></section>';
    }).join("") || '<div class="empty-state compact">该日无标签事实</div>') + '</div></article>';
  }

  function renderEvidenceRows(rows) {
    if (!rows.length) return '<div class="label-hub-evidence-state is-missing"><strong>规则证据待同步</strong><span>当前只展示远端标签事实流转，不推断销售角色变化原因。</span></div>';
    return '<div class="label-hub-evidence-list">' + rows.map(function (row) {
      var status = String(row.evidence_status || "missing");
      var statusLabel = { matched: "证据一致", mismatch: "重算不一致", missing: "证据缺失" }[status] || status;
      var margin = row.tag_gross_margin === null || row.tag_gross_margin === undefined ? "暂无" : formatPercent(row.tag_gross_margin);
      return '<article class="is-' + app.escapeHtml(status) + '"><header><span>' + app.escapeHtml(String(row.label_date || "")) + ' · ' + app.escapeHtml(row.label_period || "") + '</span><strong>' + app.escapeHtml(statusLabel) + '</strong></header><p>' + app.escapeHtml(row.country_category || "") + ' · ' + app.escapeHtml(row.store || "") + '</p><div><span>日销 <b>' + (row.daily_sales === null || row.daily_sales === undefined ? "暂无" : formatNumber(row.daily_sales)) + '</b></span><span>打标毛利率 <b>' + margin + '</b></span><span>本地重算 <b>' + app.escapeHtml(String(row.computed_sub_label_id || "暂无")) + '</b></span><span>远端事实 <b>' + app.escapeHtml(String(row.remote_sub_label_id || "暂无")) + '</b></span></div></article>';
    }).join("") + '</div>';
  }

  function renderDrawerChange(profile) {
    var scope = profile.scope || {};
    return '<div class="label-hub-trace-scope"><span>' + app.escapeHtml(scope.previous_date || "--") + '</span><i>→</i><span>' + app.escapeHtml(scope.current_date || "--") + '</span><em>' + app.escapeHtml(String(scope.transition_period || "30d").replace("d", "天")) + '</em></div><div class="label-hub-trace-days">' + renderChangeDay(profile.previous || {}, "上次") + renderChangeDay(profile.current || {}, "今日") + '</div><div class="label-hub-trace-evidence"><h4>销售角色规则证据</h4>' + renderEvidenceRows(profile.sales_role_evidence || []) + '</div>';
  }

  function loadDrawerChange(msku) {
    var target = document.getElementById("labelHubDrawerChange");
    if (!target) return;
    app.apiGet("/api/label-hub/msku-change", { msku: msku, transition_period: state.transition_period || state.metric_period || "30d" }).then(function (profile) {
      if (!document.getElementById("labelHubDrawerChange")) return;
      target.innerHTML = '<h3>上次 → 今日</h3>' + renderDrawerChange(profile);
    }).catch(function (error) {
      target.innerHTML = '<h3>上次 → 今日</h3><div class="empty-state compact">变化追溯暂不可用：' + app.escapeHtml((error && error.message) || "请稍后重试") + '</div>';
    });
  }

  function openChangeDrawer(msku) {
    setDrawerMode("trace");
    elements.labelHubDrawer.hidden = false;
    elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">标签变化追溯</p><h2 id="labelHubDrawerTitle">' + app.escapeHtml(msku) + '</h2><p>按去重 MSKU 汇总，经营单元保留完整追溯</p></div><section id="labelHubDrawerChange" class="label-hub-drawer-change"><div class="empty-state compact">正在加载两日标签与规则证据…</div></section>';
    loadDrawerChange(msku);
  }

  function drawerOptionList(select, selectedValue) {
    return Array.from((select && select.options) || []).map(function (option) {
      return '<option value="' + app.escapeHtml(option.value) + '"' + (String(option.value) === String(selectedValue) ? " selected" : "") + '>' + app.escapeHtml(option.textContent) + '</option>';
    }).join("");
  }

  function setDrawerMode(mode) {
    elements.labelHubDrawer.dataset.drawerMode = mode;
    var card = elements.labelHubDrawer.querySelector(".label-hub-drawer-card");
    if (card) card.classList.toggle("label-hub-change-detail-drawer", mode === "changes" || mode === "layer-changes");
  }

  function changeDetailsHtml(payload, context) {
    var scope = (payload || lastChanges || {}).scope || {};
    var title = context ? context.title + " · 变化明细" : "标签变化明细";
    var scopeText = (scope.previous_date || "--") + " → " + (scope.current_date || "--") + " · " + (scope.comparison_label || "较上期数据");
    var contextHint = context
      ? '<div class="label-hub-layer-change-hint"><b>按当前完整组合比较</b><span>已固定当前点击层，其余标签、经营及问题筛选条件保持不变。</span></div>'
      : "";
    return '<div class="label-hub-drawer-head label-hub-change-drawer-head"><p class="section-kicker">每日变化</p><h2 id="labelHubDrawerTitle">' + app.escapeHtml(title) + '</h2><p>' + app.escapeHtml(scopeText) + '</p></div>' +
      (context ? contextHint : '<div class="label-hub-change-drawer-controls"><label><span>变化周期</span><select data-drawer-transition-period>' + drawerOptionList(elements.labelHubTransitionPeriod, state.transition_period) + '</select></label><label><span>变化类型</span><select data-drawer-change-type>' + drawerOptionList(elements.labelHubChangeType, state.change_type) + '</select></label></div>') +
      '<section class="label-hub-change-drawer-body">' + changeContentHtml(payload || lastChanges || {}, context) + '</section>';
  }

  function openChangeDetailsDrawer() {
    if (!lastChanges || !lastChanges.available) return;
    activeLayerChangeContext = null;
    setDrawerMode("changes");
    elements.labelHubDrawer.hidden = false;
    elements.labelHubDrawerContent.innerHTML = changeDetailsHtml(lastChanges);
  }

  function refreshChangeDetailsDrawer() {
    if (elements.labelHubDrawer.hidden || elements.labelHubDrawer.dataset.drawerMode !== "changes") return;
    elements.labelHubDrawerContent.innerHTML = changeDetailsHtml(lastChanges);
  }

  function buildLayerChangeParams(context) {
    var params = buildChangeParams();
    params.page = changePage;
    params.change_type = context.change_type || "all";
    if (context.transition_from) params.layer_transition_from = context.transition_from;
    if (context.transition_to) params.layer_transition_to = context.transition_to;
    if (context.source === "remote_label") {
      var parentId = Number(context.parent || 0);
      var conditions = parsedConditions();
      conditions[String(parentId)] = [String(context.bucket || "")];
      params.conditions = serializeConditionMap(conditions);
      params.layer_change_parent = parentId;
      params.layer_change_bucket = String(context.bucket || "");
      params.layer_change_period = context.period || "all";
      var currentIds = analysisIds();
      var currentPeriods = analysisPeriods();
      var periodByParent = {};
      currentIds.forEach(function (id, index) { periodByParent[id] = currentPeriods[index] || "all"; });
      periodByParent[state.parent_label_id] = state.label_period || "all";
      periodByParent[parentId] = context.period || "all";
      var ids = unique([parentId].concat(currentIds, [state.parent_label_id]));
      params.analysis_parent_ids = ids.join("|");
      params.analysis_periods = ids.map(function (id) { return periodByParent[id] || "all"; }).join("|");
      return params;
    }
    var localField = {
      sales_trend: "sales_trends",
      daily_sales_band: "daily_sales_bands",
      margin_band: "margin_bands"
    }[context.key];
    if (context.bucket === "missing") {
      params.problem = "missing_metrics";
    } else if (localField) {
      params[localField] = String(context.bucket || "");
    }
    return params;
  }

  function openLayerChangeDetails(dataset) {
    var context = {
      source: dataset.layerChangeSource || "",
      key: dataset.layerChangeKey || "",
      parent: Number(dataset.layerChangeParent || 0),
      bucket: dataset.layerChangeBucket || "",
      period: dataset.layerChangePeriod || "all",
      change_type: "added",
      transition_from: "",
      transition_to: "",
      title: dataset.layerChangeTitle || "当前层"
    };
    context.combination_labels = layerChangeCombinationLabels(context);
    activeLayerChangeContext = context;
    setDrawerMode("layer-changes");
    elements.labelHubDrawer.hidden = false;
    loadLayerChangeDetails(context);
  }

  function loadLayerChangeDetails(context) {
    if (!context || activeLayerChangeContext !== context) return;
    elements.labelHubDrawerContent.innerHTML = '<div class="empty-state compact">正在核对当前组合的两期变化…</div>';
    var token = ++changeRequestToken;
    app.apiGet("/api/label-hub/changes", buildLayerChangeParams(context)).then(function (payload) {
      if (token !== changeRequestToken || activeLayerChangeContext !== context) return;
      elements.labelHubDrawerContent.innerHTML = changeDetailsHtml(payload, context);
    }).catch(function (error) {
      if (token !== changeRequestToken || activeLayerChangeContext !== context) return;
      elements.labelHubDrawerContent.innerHTML = '<div class="empty-state compact">该层变化明细加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + '</div>';
    });
  }

  function closeDrawer() {
    elements.labelHubDrawer.hidden = true;
    activeLayerChangeContext = null;
    delete elements.labelHubDrawer.dataset.drawerMode;
    var card = elements.labelHubDrawer.querySelector(".label-hub-drawer-card");
    if (card) card.classList.remove("label-hub-change-detail-drawer");
  }
  function layerChangeCombinationLabels(context) {
    var labels = [];
    var seen = {};
    var add = function (value) {
      var label = String(value || "").replace(/×\s*$/, "").trim();
      var key = label.replace(/\s*[·•]\s*/g, "：").replace(/\s+/g, "");
      if (!key || seen[key]) return;
      seen[key] = true;
      labels.push(label.replace(/\s*[·•]\s*/g, "："));
    };
    add((context || {}).title || "当前层");
    Array.from(elements.labelHubConditions ? elements.labelHubConditions.querySelectorAll(".sales-role-chip") : []).forEach(function (node) {
      add(node.textContent || "");
    });
    if (state.country_category && state.country_category !== "all") add("国家类别：" + state.country_category);
    if (state.store && state.store !== "all") add("店铺：" + state.store);
    if (state.keyword) add("搜索：" + state.keyword);
    return labels;
  }
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

(function () {
  "use strict";
  var link = document.getElementById("countryLabelHubLink");
  if (!link) return;
  function updateCountryLink() {
    var query = new URLSearchParams();
    var values = [
      ["metric_period", document.getElementById("labelHubMetricPeriod")],
      ["country_category", document.getElementById("labelHubCountry")],
      ["store", document.getElementById("labelHubStore")],
      ["keyword", document.getElementById("labelHubKeyword")]
    ];
    values.forEach(function (item) {
      var value = item[1] && item[1].value;
      if (value && value !== "all") query.set(item[0], value);
    });
    link.href = "/country-label-hub" + (query.toString() ? "?" + query.toString() : "");
  }
  window.updateCountryLabelHubLink = updateCountryLink;
  ["labelHubMetricPeriod", "labelHubCountry", "labelHubStore", "labelHubKeyword"].forEach(function (id) {
    var control = document.getElementById(id);
    if (control) { control.addEventListener("change", updateCountryLink); control.addEventListener("input", updateCountryLink); }
  });
  setTimeout(updateCountryLink, 0);
}());
