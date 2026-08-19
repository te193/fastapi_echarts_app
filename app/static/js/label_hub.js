(function () {
  var META_REQUEST_OPTIONS = { timeoutMs: 120000 };
  var CHANGE_REQUEST_OPTIONS = { timeoutMs: 90000 };
  "use strict";

  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var hasExplicitLabelPeriod = query.has("label_period");
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
    diagnostic_scope: query.get("diagnostic_scope") || "global",
    diagnostic_period: query.get("diagnostic_period") || query.get("metric_period") || "30d",
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
  var storedDetailView = "";
  try { storedDetailView = localStorage.getItem("labelHubDetailView") || ""; } catch (ignore) {}
  var detailState = {
    detail_view: storedDetailView === "country" ? "country" : "business_unit",
    identifiers: [], country_categories: [], stores: [], countries: [], detail_conditions: "",
    sales_roles: [], role_reason_ids: [], daily_sales_bands: [], margin_bands: [], ranking_bands: [], problems: [],
    current_stockout_only: false, stockout_before_role_period: "", stockout_before_role_ids: [],
    problem_mode: "any", page: 1, page_size: state.page_size,
    sort_field: "sales_amount", sort_dir: "desc"
  };
  var STOCKOUT_ROLE_PERIODS = ["7d", "14d", "30d", "90d"];
  var STOCKOUT_ROLE_LABELS = { "2001": "明星产品", "2002": "潜力产品", "2003": "瘦狗产品", "2004": "问题产品" };
  var stockoutRoleState = {
    open: false,
    period: normalizeStockoutRolePeriod(state.metric_period),
    payload: null,
    requestKey: "",
    requestToken: 0
  };
  var stockoutOperatingStatusState = {
    open: false,
    rulesOpen: false,
    period: normalizeStockoutRolePeriod(state.metric_period),
    payload: null,
    requestKey: "",
    requestToken: 0
  };
  var stockoutEvidenceState = {
    row: null,
    payload: null,
    activeTab: "timeline",
    requestToken: 0
  };
  var chartMeasure = query.get("measure") || "msku_count";
  var meta = null;
  var lastPayload = null;
  var elements = {};
  var requestToken = 0;
  var detailRequestToken = 0;
  var changeRequestToken = 0;
  var diagnosticRequestToken = 0;
  var diagnosticRequestKey = "";
  var diagnosticLoading = false;
  var roleDiagnosticState = {
    row: null,
    period: "30d",
    payload: null,
    focusCountry: "",
    openCountry: null,
    requestToken: 0
  };
  var changePage = 1;
  var lastChanges = null;
  var lastHighlights = null;
  var lastDetailPayload = null;
  var activeLayerChangeContext = null;
  var linkedSelectInstances = [];
  var detailFilterSelectInstances = [];
  var detailAdvancedOpen = false;
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
      "labelHubDetailView", "labelHubDetailIdentifiers", "labelHubIdentifierExpand", "labelHubIdentifierPopover", "labelHubIdentifierBatchInput",
      "labelHubIdentifierBatchClear", "labelHubIdentifierBatchClose", "labelHubIdentifierBatchSearch",
      "labelHubDetailLabels", "labelHubDetailLabelTrigger", "labelHubDetailLabelSummary", "labelHubDetailLabelPanel",
      "labelHubDetailLabelSearch", "labelHubDetailLabelGroups", "labelHubDetailLabelEmpty",
      "labelHubDetailCountries", "labelHubDetailCountryCategories",
      "labelHubDetailStores", "labelHubDetailProblems", "labelHubDetailProblemMode", "labelHubDetailSalesRoles", "labelHubDetailRoleReasons",
      "labelHubDetailDailyBands", "labelHubDetailMarginBands", "labelHubDetailRankingBands", "labelHubDetailApply", "labelHubDetailExport", "labelHubDetailClear", "labelHubIdentifierResolution",
      "labelHubDetailCountriesField", "labelHubCountryFilterHint", "labelHubDetailRankingField", "labelHubRankingFilterHint", "labelHubDetailToolbar", "labelHubDetailAdvanced",
      "labelHubDetailMore", "labelHubDetailMoreCount", "labelHubDetailActiveFilters", "labelHubDetailActiveFilterList", "labelHubRoleReasonScope",
      "labelHubRoleReasonTrigger", "labelHubRoleReasonSummary", "labelHubRoleReasonPanel", "labelHubRoleReasonGroups",
      "labelHubDrawerClose", "labelHubDrawerContent", "labelHubRuleDrawer", "labelHubRuleDrawerClose",
      "labelHubRuleDrawerTitle", "labelHubRuleDrawerContent"
      , "labelHubCountryProfileDrawer", "labelHubCountryProfileClose", "labelHubCountryProfileContent"
      , "labelHubChangeScope", "labelHubTransitionPeriod", "labelHubChangeType", "labelHubChangeContent",
      "labelHubChangeBrief", "labelHubOpenChanges", "labelHubChangeSubtitle", "labelHubSectionNav",
      "labelHubDiagnosticsSection", "labelHubDiagnosticsScope", "labelHubDiagnosticsPeriod",
      "labelHubDiagnosticsRoles", "labelHubDiagnosticsContent", "labelHubDiagnosticsCondition",
      "labelHubDiagnosticsSubtitle", "labelHubStockoutEvidenceModal", "labelHubStockoutEvidenceClose",
      "labelHubStockoutEvidenceContent"
    ].forEach(function (id) { elements[id] = document.getElementById(id); });
    setLoading(true);
    bindEvents();
    app.apiGet("/api/label-hub/meta", null, META_REQUEST_OPTIONS).then(function (payload) {
      meta = payload;
      normalizeStateFromMeta();
      state.metric_period = state.metric_period || meta.default_metric_period || "30d";
      state.parent_label_id = state.parent_label_id || firstAvailableCategory();
      if (!hasExplicitLabelPeriod) state.label_period = defaultLabelPeriod(state.parent_label_id);
      state.compare_parent_id = state.compare_parent_id || defaultCompareCategory();
      state.analysis_parent_ids = state.analysis_parent_ids || (meta.default_analysis_parent_ids || []).join("|");
      normalizeAnalysisPeriods();
      populateControls();
      syncDiagnosticsVisibility();
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
      detailState.page_size = state.page_size;
      detailState.page = 1;
      populateControls();
      renderDetails();
    });
    elements.labelHubTableView.addEventListener("change", function () {
      state.table_view = normalizeTableView(this.value);
      populateControls();
      app.writeQueryState(state);
      if (lastDetailPayload) renderTable(lastDetailPayload);
    });
    elements.labelHubDetailView.addEventListener("change", function () {
      detailState.detail_view = this.value === "country" ? "country" : "business_unit";
      detailState.role_reason_ids = [];
      detailState.page = 1;
      try { localStorage.setItem("labelHubDetailView", detailState.detail_view); } catch (ignore) {}
      populateControls();
      renderDetails();
    });
    elements.labelHubDetailSalesRoles.addEventListener("change", refreshRoleReasonControl);
    elements.labelHubDetailLabelTrigger.addEventListener("click", function (event) {
      event.stopPropagation();
      toggleDetailLabelPanel();
    });
    elements.labelHubDetailLabelSearch.addEventListener("input", function () {
      renderDetailLabelPanel(this.value);
    });
    elements.labelHubDetailLabelGroups.addEventListener("change", function (event) {
      var checkbox = event.target.closest("[data-detail-label-value]");
      if (!checkbox) return;
      var option = Array.from(elements.labelHubDetailLabels.options).find(function (item) {
        return String(item.value) === String(checkbox.dataset.detailLabelValue);
      });
      if (option) option.selected = checkbox.checked;
      updateDetailLabelTrigger();
    });
    elements.labelHubRoleReasonTrigger.addEventListener("click", function (event) {
      event.stopPropagation();
      toggleRoleReasonPanel();
    });
    elements.labelHubRoleReasonGroups.addEventListener("change", function (event) {
      var checkbox = event.target.closest("[data-role-reason-id]");
      if (!checkbox) return;
      var option = Array.from(elements.labelHubDetailRoleReasons.options).find(function (item) {
        return String(item.value) === String(checkbox.dataset.roleReasonId);
      });
      if (option) option.selected = checkbox.checked;
      detailState.role_reason_ids = selectedValues(elements.labelHubDetailRoleReasons).map(Number);
      updateRoleReasonTrigger();
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest(".label-hub-detail-label-control")) closeDetailLabelPanel();
      if (!event.target.closest(".label-hub-role-reason-control")) closeRoleReasonPanel();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDetailLabelPanel();
        closeRoleReasonPanel();
        closeStockoutBeforeEvidence();
      }
    });
    elements.labelHubDetailApply.addEventListener("click", function () { collectDetailFilters(); detailState.page = 1; renderDetailActiveFilters(); renderDetails(); });
    elements.labelHubDetailExport.addEventListener("click", exportDetails);
    elements.labelHubDetailClear.addEventListener("click", clearDetailFilters);
    elements.labelHubDetailMore.addEventListener("click", toggleDetailAdvancedFilters);
    elements.labelHubIdentifierExpand.addEventListener("click", function () {
      if (elements.labelHubIdentifierPopover.hidden) openIdentifierPopover();
      else closeIdentifierPopover(true);
    });
    elements.labelHubIdentifierBatchClear.addEventListener("click", function () {
      elements.labelHubIdentifierBatchInput.value = "";
      elements.labelHubIdentifierBatchInput.focus();
    });
    elements.labelHubIdentifierBatchClose.addEventListener("click", function () { closeIdentifierPopover(true); });
    elements.labelHubIdentifierBatchSearch.addEventListener("click", function () {
      elements.labelHubDetailIdentifiers.value = splitIdentifiers(elements.labelHubIdentifierBatchInput.value).join(", ");
      closeIdentifierPopover(false);
      elements.labelHubDetailApply.click();
    });
    elements.labelHubIdentifierBatchInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        elements.labelHubIdentifierBatchSearch.click();
      }
    });
    elements.labelHubDetailIdentifiers.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); elements.labelHubDetailApply.click(); }
    });
    elements.labelHubDetailActiveFilters.addEventListener("click", function (event) {
      var button = event.target.closest("[data-detail-filter-field]");
      if (button) removeDetailFilter(button.dataset.detailFilterField, button.dataset.detailFilterValue || "");
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
      var stockoutRoleToggle = event.target.closest("[data-stockout-role-toggle]");
      var stockoutRolePeriod = event.target.closest("[data-stockout-role-period]");
      var stockoutRole = event.target.closest("[data-stockout-role-id]");
      var stockoutOperatingStatusToggle = event.target.closest("[data-stockout-operating-status-toggle]");
      var stockoutOperatingStatusPeriod = event.target.closest("[data-stockout-operating-status-period]");
      var stockoutOperatingStatusRules = event.target.closest("[data-stockout-operating-status-rules]");
      var ruleButton = event.target.closest("[data-view-rules]");
      var stockoutFormula = event.target.closest("[data-operating-stockout-formula]");
      var returnAttribution = event.target.closest("[data-return-attribution]");
      var child = event.target.closest("[data-overview-child]");
      var parent = event.target.closest("[data-overview-parent]");
      if (stockoutRoleToggle) {
        toggleStockoutRolePanel();
      } else if (stockoutOperatingStatusToggle) {
        toggleStockoutOperatingStatusPanel();
      } else if (stockoutOperatingStatusRules) {
        toggleStockoutOperatingStatusRules();
      } else if (stockoutRolePeriod) {
        selectStockoutRolePeriod(stockoutRolePeriod.dataset.stockoutRolePeriod);
      } else if (stockoutOperatingStatusPeriod) {
        selectStockoutOperatingStatusPeriod(stockoutOperatingStatusPeriod.dataset.stockoutOperatingStatusPeriod);
      } else if (stockoutRole) {
        openStockoutRoleDetails(stockoutRole.dataset.stockoutRoleId || "");
      } else if (stockoutFormula) {
        toggleOperatingStockoutPopover(stockoutFormula);
      } else if (ruleButton) {
        openRuleDrawer(Number(ruleButton.dataset.viewRules));
      } else if (returnAttribution) {
        applyReturnAttributionFilter(returnAttribution.dataset.operationChild);
        document.querySelector(".label-hub-breakdown-section").scrollIntoView({ behavior: "smooth", block: "start" });
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
      detailState.problems = state.problem === "all" ? [] : [state.problem];
      detailState.problem_mode = "any";
      resetPageAndRender();
    });
    elements.labelHubDiagnosticsSection.addEventListener("toggle", function () {
      if (this.open && lastPayload) loadDiagnostics();
    });
    elements.labelHubDiagnosticsScope.addEventListener("click", function (event) {
      var button = event.target.closest("[data-diagnostic-scope]");
      if (!button) return;
      state.diagnostic_scope = button.dataset.diagnosticScope || "global";
      app.writeQueryState(state);
      loadDiagnostics();
    });
    elements.labelHubDiagnosticsPeriod.addEventListener("change", function () {
      state.diagnostic_period = this.value || "30d";
      app.writeQueryState(state);
      loadDiagnostics();
    });
    elements.labelHubDiagnosticsRoles.addEventListener("click", function (event) {
      var button = event.target.closest("[data-diagnostic-role]");
      if (!button) return;
      var values = parsedConditions();
      var role = button.dataset.diagnosticRole || "";
      if (role) values["1"] = [role];
      else delete values["1"];
      saveConditions(values);
      resetPageAndRender();
    });
    elements.labelHubDiagnosticsContent.addEventListener("click", function (event) {
      var button = event.target.closest("[data-diagnostic-child]");
      var roleRow = event.target.closest("[data-diagnostic-role-summary]");
      var countryRoleRow = event.target.closest("[data-diagnostic-country-role]");
      var detailButton = event.target.closest("[data-diagnostic-open-details]");
      if (countryRoleRow) {
        toggleCountryDiagnosticRole(countryRoleRow);
        return;
      }
      if (button) toggleCondition(button.dataset.diagnosticParent, button.dataset.diagnosticChild);
      if (roleRow) {
        var values = parsedConditions();
        values["1"] = [roleRow.dataset.diagnosticRoleSummary];
        saveConditions(values);
        resetPageAndRender();
      }
      if (detailButton) {
        document.getElementById("labelHubDetailSection").scrollIntoView({ behavior: "smooth", block: "start" });
      }
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
    elements.labelHubStockoutEvidenceClose.addEventListener("click", closeStockoutBeforeEvidence);
    elements.labelHubStockoutEvidenceModal.addEventListener("click", function (event) {
      if (event.target === elements.labelHubStockoutEvidenceModal) closeStockoutBeforeEvidence();
    });
    elements.labelHubStockoutEvidenceContent.addEventListener("click", function (event) {
      var tab = event.target.closest("[data-stockout-evidence-tab]");
      var close = event.target.closest("[data-stockout-evidence-close]");
      if (close) {
        closeStockoutBeforeEvidence();
        return;
      }
      if (!tab || !stockoutEvidenceState.payload) return;
      stockoutEvidenceState.activeTab = tab.dataset.stockoutEvidenceTab || "timeline";
      renderStockoutEvidenceModal(stockoutEvidenceState.payload);
    });
    elements.labelHubTransitionPeriod.addEventListener("change", function () { state.transition_period = this.value; changePage = 1; app.writeQueryState(state); loadChanges(); });
    elements.labelHubChangeType.addEventListener("change", function () { state.change_type = this.value; changePage = 1; app.writeQueryState(state); loadChanges(); });
    if (elements.labelHubChangeContent) elements.labelHubChangeContent.addEventListener("click", function (event) {
      var detailButton = event.target.closest("[data-current-combination-detail]");
      var pageButton = event.target.closest("[data-change-page]");
      var traceButton = event.target.closest("[data-change-msku]");
      if (detailButton) { openCurrentCombinationDetails(); return; }
      if (pageButton && !pageButton.disabled) { changePage = Number(pageButton.dataset.changePage); loadChanges(); }
      if (traceButton) openChangeDrawer(traceButton.dataset.changeMsku);
    });
    if (elements.labelHubOpenChanges) elements.labelHubOpenChanges.addEventListener("click", openCurrentCombinationDetails);
    elements.labelHubSectionNav.addEventListener("click", function (event) {
      var link = event.target.closest("[data-section-link]");
      if (!link) return;
      elements.labelHubSectionNav.querySelectorAll("a").forEach(function (item) { item.classList.toggle("active", item === link); });
    });
    elements.labelHubDrawerContent.addEventListener("click", function (event) {
      var pageButton = event.target.closest("[data-change-page]");
      var traceButton = event.target.closest("[data-change-msku]");
      var layerTypeButton = event.target.closest("[data-layer-change-type]");
      var transitionButton = event.target.closest("[data-layer-transition-type]");
      var diagnosticPeriodButton = event.target.closest("[data-role-diagnostic-period]");
      var diagnosticCountryButton = event.target.closest("[data-role-diagnostic-country]");
      if (diagnosticPeriodButton) {
        roleDiagnosticState.period = diagnosticPeriodButton.dataset.roleDiagnosticPeriod || "30d";
        roleDiagnosticState.openCountry = null;
        loadRoleDiagnosticDrawer();
        return;
      }
      if (diagnosticCountryButton && roleDiagnosticState.payload) {
        var country = diagnosticCountryButton.dataset.roleDiagnosticCountry || "";
        roleDiagnosticState.openCountry = roleDiagnosticState.openCountry === country ? "" : country;
        renderRoleDiagnosticDrawer(roleDiagnosticState.payload);
        return;
      }
      if (pageButton && !pageButton.disabled) {
        changePage = Number(pageButton.dataset.changePage);
        if (activeLayerChangeContext) loadLayerChangeDetails(activeLayerChangeContext);
        else loadChanges();
      }
      if (transitionButton && activeLayerChangeContext) {
        activeLayerChangeContext.change_type = transitionButton.dataset.layerTransitionType || "all";
        activeLayerChangeContext.transition_from = transitionButton.dataset.layerTransitionFrom || "";
        activeLayerChangeContext.transition_to = transitionButton.dataset.layerTransitionTo || "";
        activeLayerChangeContext.transition_parent = Number(transitionButton.dataset.layerTransitionParent || 0);
        activeLayerChangeContext.transition_previous = transitionButton.dataset.layerTransitionPrevious || "";
        activeLayerChangeContext.transition_current = transitionButton.dataset.layerTransitionCurrent || "";
        changePage = 1;
        loadLayerChangeDetails(activeLayerChangeContext);
        return;
      }
      if (layerTypeButton && activeLayerChangeContext) {
        activeLayerChangeContext.change_type = layerTypeButton.dataset.layerChangeType || "all";
        activeLayerChangeContext.transition_from = "";
        activeLayerChangeContext.transition_to = "";
        activeLayerChangeContext.transition_parent = 0;
        activeLayerChangeContext.transition_previous = "";
        activeLayerChangeContext.transition_current = "";
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
    document.addEventListener("click", function (event) {
      if (!elements.labelHubIdentifierPopover.hidden && !event.target.closest(".label-hub-detail-code-control")) {
        closeIdentifierPopover(false);
      }
      if (!event.target.closest(".label-hub-operating-stockout-rate")) {
        closeOperatingStockoutPopover();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeStockoutRolePanel();
        closeIdentifierPopover(true);
        closeOperatingStockoutPopover();
        closeDrawer();
        closeRuleDrawer();
      }
    });
  }

  function resetPageAndRender() { state.page = 1; stockoutRoleState.payload = null; stockoutRoleState.requestKey = ""; stockoutOperatingStatusState.payload = null; stockoutOperatingStatusState.requestKey = ""; populateControls(); render(); }
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

  function multiOptionList(items, selected) {
    var selectedMap = {};
    (selected || []).forEach(function (value) { selectedMap[String(value)] = true; });
    return (items || []).map(function (item) {
      var value = item.id !== undefined ? item.id : (item.key !== undefined ? item.key : item);
      var label = item.label !== undefined ? item.label : item;
      return '<option value="' + app.escapeHtml(String(value)) + '"' + (selectedMap[String(value)] ? " selected" : "") + '>' + app.escapeHtml(String(label)) + "</option>";
    }).join("");
  }

  function detailLabelGroups() {
    return (meta.categories || []).concat(meta.excluded_categories || []).map(function (category) {
      return {
        id: Number(category.id),
        label: String(category.label || ""),
        children: (category.children || []).map(function (child) {
          return {
            value: category.id + ":" + child.id,
            label: String(child.label || "")
          };
        })
      };
    }).filter(function (group) { return group.children.length > 0; });
  }

  function detailLabelOptions() {
    return detailLabelGroups().reduce(function (all, group) {
      return all.concat(group.children.map(function (child) {
        return { key: child.value, label: group.label + " · " + child.label };
      }));
    }, []);
  }

  function renderDetailLabelPanel(searchText) {
    var query = String(searchText || "").trim().toLocaleLowerCase();
    var selected = {};
    selectedValues(elements.labelHubDetailLabels).forEach(function (value) { selected[String(value)] = true; });
    var groups = detailLabelGroups();
    var html = [];
    groups.forEach(function (group) {
      var groupMatches = !query || group.label.toLocaleLowerCase().indexOf(query) >= 0;
      var children = group.children.filter(function (child) {
        return groupMatches || child.label.toLocaleLowerCase().indexOf(query) >= 0;
      });
      if (!children.length) return;
      html.push('<section class="label-hub-detail-label-section"><h4>' + app.escapeHtml(group.label) + "</h4>");
      html.push('<div class="label-hub-detail-label-options">');
      children.forEach(function (child) {
        var checked = selected[String(child.value)] ? " checked" : "";
        html.push('<label class="label-hub-detail-label-option" title="' + app.escapeHtml(child.label) + '">');
        html.push('<input type="checkbox" data-detail-label-value="' + app.escapeHtml(child.value) + '"' + checked + ">");
        html.push("<span>" + app.escapeHtml(child.label) + "</span></label>");
      });
      html.push("</div></section>");
    });
    elements.labelHubDetailLabelGroups.innerHTML = html.join("");
    elements.labelHubDetailLabelEmpty.textContent = groups.length ? "未找到匹配标签" : "暂无可用标签";
    elements.labelHubDetailLabelEmpty.hidden = html.length > 0;
  }

  function updateDetailLabelTrigger() {
    var selected = selectedValues(elements.labelHubDetailLabels);
    var label = "全部标签";
    if (selected.length === 1) label = selectedOptionLabel(elements.labelHubDetailLabels, selected[0]).split(" · ").pop();
    if (selected.length > 1) label = "已选 " + selected.length + " 项";
    elements.labelHubDetailLabelSummary.textContent = label;
    elements.labelHubDetailLabelTrigger.classList.toggle("has-value", selected.length > 0);
  }

  function syncDetailLabelControl() {
    elements.labelHubDetailLabelSearch.value = "";
    renderDetailLabelPanel("");
    updateDetailLabelTrigger();
  }

  function closeDetailLabelPanel() {
    if (!elements.labelHubDetailLabelPanel || elements.labelHubDetailLabelPanel.hidden) return;
    elements.labelHubDetailLabelPanel.hidden = true;
    elements.labelHubDetailLabelTrigger.classList.remove("is-open");
    elements.labelHubDetailLabelTrigger.setAttribute("aria-expanded", "false");
    elements.labelHubDetailLabelSearch.value = "";
    renderDetailLabelPanel("");
  }

  function toggleDetailLabelPanel() {
    var willOpen = elements.labelHubDetailLabelPanel.hidden;
    if (!willOpen) {
      closeDetailLabelPanel();
      return;
    }
    closeRoleReasonPanel();
    elements.labelHubDetailLabelPanel.hidden = false;
    elements.labelHubDetailLabelTrigger.classList.add("is-open");
    elements.labelHubDetailLabelTrigger.setAttribute("aria-expanded", "true");
    window.setTimeout(function () { elements.labelHubDetailLabelSearch.focus(); }, 0);
  }

  var ROLE_REASON_GROUPS = [
    { code: "star", label: "明星产品", matcher: /^(明星产品|已达到站点明星产品标准)/ },
    { code: "potential", label: "潜力产品", matcher: /^潜力产品/ },
    { code: "incubation", label: "瘦狗产品", matcher: /^瘦狗产品/ },
    { code: "eliminate", label: "问题产品", matcher: /^问题产品/ },
    { code: "missing", label: "数据异常", matcher: /^数据异常/ }
  ];

  function roleReasonCategory() {
    var parentId = detailState.detail_view === "country" ? 16 : 15;
    return (meta.categories || []).concat(meta.excluded_categories || []).find(function (category) {
      return Number(category.id) === parentId;
    }) || null;
  }

  function roleReasonDefinition(label) {
    return ROLE_REASON_GROUPS.find(function (definition) {
      return definition.matcher.test(String(label || ""));
    }) || null;
  }

  function roleReasonShortLabel(label) {
    if (String(label || "") === "已达到站点明星产品标准") return "已达标";
    return String(label || "").replace(/^(明星产品|潜力产品|瘦狗产品|问题产品)(\(站点\))?-/, "");
  }

  function roleReasonOptions() {
    var category = roleReasonCategory();
    var selectedRoles = {};
    detailState.sales_roles.forEach(function (role) { selectedRoles[role] = true; });
    return ((category && category.children) || []).map(function (child) {
      var definition = roleReasonDefinition(child.label);
      if (!definition || (detailState.sales_roles.length && !selectedRoles[definition.code])) return null;
      return {
        id: Number(child.id),
        label: roleReasonShortLabel(child.label),
        fullLabel: child.label,
        roleCode: definition.code,
        roleLabel: definition.label
      };
    }).filter(Boolean);
  }

  function reconcileRoleReasonSelections() {
    var allowed = {};
    roleReasonOptions().forEach(function (item) { allowed[String(item.id)] = true; });
    detailState.role_reason_ids = detailState.role_reason_ids.map(Number).filter(function (id) {
      return !!allowed[String(id)];
    });
  }

  function roleReasonOptionList() {
    var options = roleReasonOptions();
    var html = [];
    ROLE_REASON_GROUPS.forEach(function (group) {
      var children = options.filter(function (item) { return item.roleCode === group.code; });
      if (!children.length) return;
      html.push('<optgroup class="label-hub-role-reason-group" label="' + app.escapeHtml(group.label) + '">');
      children.forEach(function (item) {
        html.push('<option value="' + item.id + '" data-full-label="' + app.escapeHtml(item.fullLabel) + '">' + app.escapeHtml(item.label) + "</option>");
      });
      html.push("</optgroup>");
    });
    return html.join("");
  }

  function updateRoleReasonTrigger() {
    var selected = selectedValues(elements.labelHubDetailRoleReasons);
    var label = "全部角色原因";
    if (selected.length === 1) label = selectedOptionLabel(elements.labelHubDetailRoleReasons, selected[0]);
    if (selected.length > 1) label = "已选 " + selected.length + " 项";
    elements.labelHubRoleReasonSummary.textContent = label;
    elements.labelHubRoleReasonTrigger.classList.toggle("has-value", selected.length > 0);
  }

  function renderRoleReasonPanel() {
    var options = roleReasonOptions();
    var selected = {};
    detailState.role_reason_ids.forEach(function (id) { selected[String(id)] = true; });
    var html = [];
    ROLE_REASON_GROUPS.forEach(function (group) {
      var children = options.filter(function (item) { return item.roleCode === group.code; });
      if (!children.length) return;
      html.push('<section class="label-hub-role-reason-section">');
      html.push('<h4>' + app.escapeHtml(group.label) + "</h4>");
      html.push('<div class="label-hub-role-reason-options">');
      children.forEach(function (item) {
        var checked = selected[String(item.id)] ? " checked" : "";
        html.push('<label class="label-hub-role-reason-option">');
        html.push('<input type="checkbox" data-role-reason-id="' + item.id + '"' + checked + ">");
        html.push("<span>" + app.escapeHtml(item.label) + "</span>");
        html.push("</label>");
      });
      html.push("</div></section>");
    });
    if (!html.length) html.push('<p class="label-hub-role-reason-empty">当前角色暂无诊断原因</p>');
    elements.labelHubRoleReasonGroups.innerHTML = html.join("");
    updateRoleReasonTrigger();
  }

  function closeRoleReasonPanel() {
    if (!elements.labelHubRoleReasonPanel || elements.labelHubRoleReasonPanel.hidden) return;
    elements.labelHubRoleReasonPanel.hidden = true;
    elements.labelHubRoleReasonTrigger.classList.remove("is-open");
    elements.labelHubRoleReasonTrigger.setAttribute("aria-expanded", "false");
  }

  function toggleRoleReasonPanel() {
    var willOpen = elements.labelHubRoleReasonPanel.hidden;
    if (!willOpen) {
      closeRoleReasonPanel();
      return;
    }
    closeDetailLabelPanel();
    elements.labelHubRoleReasonPanel.hidden = false;
    elements.labelHubRoleReasonTrigger.classList.add("is-open");
    elements.labelHubRoleReasonTrigger.setAttribute("aria-expanded", "true");
  }

  function refreshRoleReasonControl() {
    detailState.sales_roles = selectedValues(elements.labelHubDetailSalesRoles);
    reconcileRoleReasonSelections();
    elements.labelHubDetailRoleReasons.innerHTML = roleReasonOptionList();
    syncDetailNativeSelections();
    renderRoleReasonPanel();
  }

  function populateControls() {
    if (!meta) return;
    destroyDetailFilterSelects();
    elements.labelHubMetricPeriod.innerHTML = optionList(meta.metric_periods || [], state.metric_period, "");
    elements.labelHubCountry.innerHTML = optionList(meta.country_categories || [], state.country_category, "全部国家类别");
    elements.labelHubStore.innerHTML = optionList(meta.stores || [], state.store, "全部店铺");
    elements.labelHubParent.innerHTML = optionList(meta.categories || [], state.parent_label_id, "");
    elements.labelHubCompare.innerHTML = optionList((meta.categories || []).filter(function (item) { return item.id !== state.parent_label_id; }), state.compare_parent_id, "");
    elements.labelHubKeyword.value = state.keyword;
    elements.labelHubPageSize.value = String(normalizePageSize(state.page_size));
    elements.labelHubTableView.value = normalizeTableView(state.table_view);
    elements.labelHubDetailView.value = detailState.detail_view;
    elements.labelHubDetailCountryCategories.innerHTML = multiOptionList(meta.country_categories || [], detailState.country_categories);
    elements.labelHubDetailStores.innerHTML = multiOptionList(meta.stores || [], detailState.stores);
    elements.labelHubDetailLabels.innerHTML = multiOptionList(detailLabelOptions(), detailConditionValues());
    reconcileRoleReasonSelections();
    elements.labelHubDetailRoleReasons.innerHTML = roleReasonOptionList();
    syncDetailNativeSelections();
    syncDetailLabelControl();
    initDetailFilterSelects();
    syncDetailViewControls();
    renderRoleReasonPanel();
    renderDetailActiveFilters();
    elements.labelHubTransitionPeriod.innerHTML = optionList(meta.metric_periods || [], state.transition_period, "");
    elements.labelHubChangeType.value = state.change_type;
    elements.labelHubDiagnosticsPeriod.value = state.diagnostic_period;
    syncDiagnosticControls();
    var category = categoryById(state.parent_label_id) || { children: [] };
    var periods = unique([].concat.apply([], (category.children || []).map(function (child) { return child.periods || []; })));
    elements.labelHubPeriodField.hidden = periods.length < 2;
    elements.labelHubPeriod.innerHTML = optionList(periods, state.label_period, "全部周期");
    renderMeasureTabs();
  }

  function defaultLabelPeriod(parentId) {
    return Number(parentId) === 1 ? "30d" : "all";
  }

  function selectParent(parentId) {
    state.parent_label_id = parentId;
    syncDiagnosticsVisibility();
    state.compare_parent_id = defaultCompareCategory();
    state.label_period = defaultLabelPeriod(parentId);
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

  function syncDiagnosticsVisibility() {
    if (!elements.labelHubDiagnosticsSection) return;
    elements.labelHubDiagnosticsSection.open = Number(state.parent_label_id) === 1;
  }

  function syncDiagnosticControls() {
    if (!elements.labelHubDiagnosticsScope) return;
    elements.labelHubDiagnosticsScope.querySelectorAll("[data-diagnostic-scope]").forEach(function (button) {
      button.classList.toggle("active", button.dataset.diagnosticScope === state.diagnostic_scope);
    });
    var conditionMap = parsedConditions();
    var selectedRoles = conditionMap["1"] || [];
    var role = selectedRoles.length === 1 ? selectedRoles[0] : "";
    elements.labelHubDiagnosticsRoles.querySelectorAll("[data-diagnostic-role]").forEach(function (button) {
      button.classList.toggle("active", button.dataset.diagnosticRole === role);
    });
    var roleLabels = { "101": "明星产品", "102": "潜力产品", "103": "瘦狗产品", "104": "问题产品" };
    var conditionLabels = [];
    if (role) conditionLabels.push("销售角色：" + (roleLabels[role] || role));
    if (state.country_category !== "all") conditionLabels.push("国家类别：" + state.country_category);
    if (state.store !== "all") conditionLabels.push("店铺：" + state.store);
    var conditionCount = Object.keys(conditionMap).reduce(function (total, parent) {
      return total + (conditionMap[parent] || []).length;
    }, 0);
    if (conditionCount > (role ? 1 : 0)) conditionLabels.push("其他标签条件 " + (conditionCount - (role ? 1 : 0)) + " 项");
    elements.labelHubDiagnosticsCondition.textContent = conditionLabels.join(" · ") || "当前未选择诊断条件";
    elements.labelHubDiagnosticsSubtitle.textContent = role
      ? "当前查看" + (roleLabels[role] || role) + "的诊断原因。"
      : "当前查看全部销售角色诊断。";
  }

  function diagnosticParams() {
    var params = buildParams();
    params.diagnostic_scope = state.diagnostic_scope;
    params.diagnostic_period = state.diagnostic_period;
    return params;
  }

  function loadDiagnostics() {
    if (!elements.labelHubDiagnosticsSection.open) return;
    var params = diagnosticParams();
    var requestKey = JSON.stringify(params);
    if (diagnosticLoading && diagnosticRequestKey === requestKey) return;
    var token = ++diagnosticRequestToken;
    diagnosticRequestKey = requestKey;
    diagnosticLoading = true;
    syncDiagnosticControls();
    elements.labelHubDiagnosticsContent.innerHTML = '<div class="empty-state compact">正在加载销售角色诊断…</div>';
    app.apiGet("/api/label-hub/sales-role-diagnostics", params).then(function (payload) {
      if (token !== diagnosticRequestToken) return;
      renderDiagnostics(payload);
    }).catch(function (error) {
      if (token !== diagnosticRequestToken) return;
      elements.labelHubDiagnosticsContent.innerHTML = '<div class="empty-state compact">诊断加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + "</div>";
    }).then(function () {
      if (token === diagnosticRequestToken) diagnosticLoading = false;
    });
  }

  function diagnosticDeltaMarkup(item) {
    if (item.delta === null || item.delta === undefined) return "<mark>--</mark>";
    var delta = Number(item.delta || 0);
    return '<mark class="' + (delta > 0 ? "is-up" : (delta < 0 ? "is-down" : "")) + '">' +
      (delta > 0 ? "+" : "") + formatNumber(delta) + "</mark>";
  }

  function diagnosticEvidenceMarkup(item) {
    return Number(item.country_record_count || item.business_unit_count || 0)
      ? '<span class="label-hub-diagnostic-proof">' + formatPercent(item.evidence_coverage || 0) + "</span>"
      : '<span class="label-hub-diagnostic-muted">--</span>';
  }

  function toggleCountryDiagnosticRole(row) {
    var role = row.dataset.diagnosticCountryRole || "";
    var expanded = row.getAttribute("aria-expanded") !== "true";
    elements.labelHubDiagnosticsContent.querySelectorAll("[data-diagnostic-country-role]").forEach(function (item) {
      var active = item === row && expanded;
      item.setAttribute("aria-expanded", active ? "true" : "false");
      item.classList.toggle("expanded", active);
    });
    elements.labelHubDiagnosticsContent.querySelectorAll("[data-diagnostic-country-detail]").forEach(function (item) {
      item.hidden = !(expanded && item.dataset.diagnosticCountryDetail === role);
    });
  }

  function renderCountryRoleDistribution(payload, selected, selectedRole, roleDefinitions) {
    var groups = payload.country_role_distribution || [];
    var selectedRoleDefinition = roleDefinitions.find(function (item) { return item.id === selectedRole; }) || {};
    var scopeLabel = selectedRole
      ? app.escapeHtml(selectedRoleDefinition.label || "当前角色") + " · 国家站点角色分布"
      : "全部销售角色 · 国家站点角色分布";
    var rows = groups.map(function (group) {
      var childRows = (group.children || []).map(function (item) {
        var active = (selected[String(item.parent_id)] || []).indexOf(String(item.child_id)) >= 0;
        var ratio = Number(group.country_record_count || 0)
          ? Number(item.country_record_count || 0) / Number(group.country_record_count)
          : 0;
        return '<tr hidden class="label-hub-diagnostic-child-row ' + (active ? "selected" : "") + '"' +
          ' data-diagnostic-country-detail="' + app.escapeHtml(group.role_id || "") + '"' +
          ' data-diagnostic-parent="' + Number(item.parent_id || 16) + '"' +
          ' data-diagnostic-child="' + Number(item.child_id || 0) + '" tabindex="0">' +
          '<td><strong>' + app.escapeHtml(item.label || "") + '</strong><small>点击筛选此诊断原因</small></td>' +
          '<td><b>' + formatNumber(item.country_record_count || 0) + '</b></td>' +
          '<td>' + formatNumber(item.business_unit_count || 0) + '</td>' +
          '<td><span>' + formatPercent(ratio) + '</span><i><em style="width:' + Math.max(2, Math.min(100, ratio * 100)) + '%"></em></i></td>' +
          '<td>' + diagnosticDeltaMarkup(item) + '</td>' +
          '<td>' + app.formatCompactCurrency(item.order_gross_profit || 0) + '</td>' +
          '<td>' + diagnosticEvidenceMarkup(item) + '</td></tr>';
      }).join("");
      return '<tr class="label-hub-diagnostic-role-row" data-diagnostic-country-role="' +
        app.escapeHtml(group.role_id || "") + '" aria-expanded="false" tabindex="0">' +
        '<td><strong><i aria-hidden="true">›</i>' + app.escapeHtml(group.label || "") +
        '</strong><small>' + ((group.children || []).length ? "点击展开诊断原因" : "当前没有诊断记录") + '</small></td>' +
        '<td><b>' + formatNumber(group.country_record_count || 0) + '</b></td>' +
        '<td>' + formatNumber(group.business_unit_count || 0) + '</td>' +
        '<td><span>' + formatPercent(group.ratio || 0) + '</span><i><em style="width:' +
        Math.max(2, Math.min(100, Number(group.ratio || 0) * 100)) + '%"></em></i></td>' +
        '<td>' + diagnosticDeltaMarkup(group) + '</td>' +
        '<td>' + app.formatCompactCurrency(group.order_gross_profit || 0) + '</td>' +
        '<td>' + diagnosticEvidenceMarkup(group) + '</td></tr>' + childRows;
    }).join("");
    var emptyRow = '<tr><td colspan="7"><div class="empty-state compact">当前范围和周期没有国家站点诊断事实。</div></td></tr>';
    elements.labelHubDiagnosticsContent.innerHTML =
      '<div class="label-hub-diagnostics-grid"><section class="label-hub-diagnostic-ledger"><header><strong>' +
      scopeLabel + '</strong><span>全站 ' + formatNumber(payload.business_unit_count || 0) +
      ' 个店铺商品 → ' + formatNumber(payload.country_record_count || 0) +
      ' 条国家记录</span></header><div class="label-hub-diagnostic-table-wrap"><table class="is-country-role-table">' +
      '<thead><tr><th>国家站点角色 / 诊断原因</th><th>国家记录</th><th>涉及 MSKU</th><th>国家记录占比</th><th>较上期</th><th>毛利润</th><th>证据</th></tr></thead><tbody>' +
      (rows || emptyRow) + '</tbody></table></div></section></div>' +
      '<footer class="label-hub-diagnostics-foot"><span>同一商品可在不同国家落入不同角色；点击站点角色展开具体原因。</span>' +
      '<button type="button" data-diagnostic-open-details>查看诊断明细与规则证据 ›</button></footer>';
  }

  function renderDiagnostics(payload) {
    var selected = parsedConditions();
    var buckets = payload.buckets || [];
    var roleDefinitions = [
      { id: "101", label: "明星产品", matcher: /明星/ },
      { id: "102", label: "潜力产品", matcher: /潜力/ },
      { id: "103", label: "瘦狗产品", matcher: /瘦狗/ },
      { id: "104", label: "问题产品", matcher: /问题/ }
    ];
    var selectedRoles = selected["1"] || [];
    var selectedRole = selectedRoles.length === 1 ? selectedRoles[0] : "";
    if (state.diagnostic_scope === "country") {
      renderCountryRoleDistribution(payload, selected, selectedRole, roleDefinitions);
      return;
    }
    var displayRows = buckets;
    if (!selectedRole) {
      displayRows = roleDefinitions.map(function (role) {
        var items = buckets.filter(function (item) { return role.matcher.test(String(item.label || "")); });
        if (!items.length) return null;
        var primary = items.slice().sort(function (a, b) {
          return Number(b.business_unit_count || 0) - Number(a.business_unit_count || 0);
        })[0];
        var businessCount = items.reduce(function (sum, item) { return sum + Number(item.business_unit_count || 0); }, 0);
        var evidenceBase = items.reduce(function (sum, item) { return sum + Number(item.business_unit_count || 0); }, 0);
        var deltasAvailable = items.every(function (item) { return item.delta !== null && item.delta !== undefined; });
        var reason = String(primary.label || "").replace(role.label, "").replace(/^[\s·-]+/, "") || "已达标";
        return {
          role_id: role.id,
          label: role.label + " · " + reason + "为主",
          business_unit_count: businessCount,
          ratio: items.reduce(function (sum, item) { return sum + Number(item.ratio || 0); }, 0),
          delta: deltasAvailable ? items.reduce(function (sum, item) { return sum + Number(item.delta || 0); }, 0) : null,
          order_gross_profit: items.reduce(function (sum, item) { return sum + Number(item.order_gross_profit || 0); }, 0),
          evidence_coverage: evidenceBase ? items.reduce(function (sum, item) {
            return sum + Number(item.evidence_coverage || 0) * Number(item.business_unit_count || 0);
          }, 0) / evidenceBase : 0
        };
      }).filter(Boolean);
    } else {
      var selectedRoleDefinition = roleDefinitions.find(function (role) { return role.id === selectedRole; });
      displayRows = selectedRoleDefinition
        ? buckets.filter(function (item) { return selectedRoleDefinition.matcher.test(String(item.label || "")); })
        : [];
    }
    var denominator = displayRows.reduce(function (sum, item) { return sum + Number(item.business_unit_count || 0); }, 0);
    var rows = displayRows.map(function (item) {
      var active = (selected[String(item.parent_id)] || []).indexOf(String(item.child_id)) >= 0;
      var rowAttributes = item.role_id
        ? ' data-diagnostic-role-summary="' + item.role_id + '"'
        : ' data-diagnostic-parent="' + item.parent_id + '" data-diagnostic-child="' + item.child_id + '"';
      var ratio = selectedRole ? Number(item.ratio || 0) : (denominator ? Number(item.business_unit_count || 0) / denominator : 0);
      return '<tr class="' + (active ? "selected" : "") + '"' + rowAttributes + ' tabindex="0">' +
        '<td><strong>' + app.escapeHtml(item.label || "") + '</strong><small>点击筛选该诊断群体</small></td>' +
        '<td><b>' + formatNumber(item.business_unit_count || 0) + '</b></td>' +
        '<td><span>' + formatPercent(ratio) + '</span><i><em style="width:' + Math.max(2, Math.min(100, ratio * 100)) + '%"></em></i></td>' +
        '<td>' + diagnosticDeltaMarkup(item) + '</td>' +
        '<td>' + app.formatCompactCurrency(item.order_gross_profit || 0) + '</td>' +
        '<td>' + diagnosticEvidenceMarkup(item) + '</td></tr>';
    }).join("");
    var role = roleDefinitions.find(function (item) { return item.id === selectedRole; }) || {};
    var scopeLabel = selectedRole ? app.escapeHtml(role.label || "当前角色") + " · 全站点问题构成" : "全部角色 · 全站点问题摘要";
    var totalRecords = displayRows.reduce(function (sum, item) { return sum + Number(item.business_unit_count || 0); }, 0);
    var emptyRow = '<tr><td colspan="6"><div class="empty-state compact">当前范围和周期没有诊断标签事实。</div></td></tr>';
    elements.labelHubDiagnosticsContent.innerHTML =
      '<div class="label-hub-diagnostics-grid"><section class="label-hub-diagnostic-ledger"><header><strong>' + scopeLabel +
      '</strong><span>共 ' + formatNumber(totalRecords) +
      ' 条店铺商品记录</span></header><div class="label-hub-diagnostic-table-wrap"><table><thead><tr><th>销售角色 / 问题</th><th>记录数</th><th>群体内占比</th><th>较上期</th><th>毛利润</th><th>证据</th></tr></thead><tbody>' +
      (rows || emptyRow) + '</tbody></table></div></section></div>' +
      '<footer class="label-hub-diagnostics-foot"><span>诊断结果跟随当前页面的全部公共筛选与联动条件。</span>' +
      '<button type="button" data-diagnostic-open-details>查看诊断明细与规则证据 ›</button></footer>';
  }

  function serializeConditions(value) { return String(value || ""); }
  function serializeCodes(value) { return String(value || ""); }
  function normalizeMskuDetailCopy(value) {
    return String(value || "")
      .replace(/\u540c\u4e00\u7ecf\u8425\u5355\u5143/g, "同一国家类别 + 店铺 + MSKU 组合")
      .replace(/\u7ecf\u8425\u5355\u5143/g, "店铺商品记录")
      .replace(/MSKU\u660e\u7ec6/g, "店铺商品记录");
  }
  function selectedValues(node) { return Array.from((node && node.selectedOptions) || []).map(function (option) { return option.value; }); }
  function splitIdentifiers(value) { return unique(String(value || "").split(/[\s,，;；]+/).map(function (item) { return item.trim(); }).filter(Boolean)); }
  function detailConditionValues() {
    var values = [];
    String(detailState.detail_conditions || "").split(";").filter(Boolean).forEach(function (group) {
      var pair = group.split(":");
      if (pair.length !== 2) return;
      pair[1].split("|").filter(Boolean).forEach(function (child) { values.push(pair[0] + ":" + child); });
    });
    return values;
  }

  function buildDetailPayload() {
    return {
      detail_view: detailState.detail_view,
      data_date: state.data_date,
      metric_period: state.metric_period,
      country_category: state.country_category,
      store: state.store,
      keyword: state.keyword,
      parent_label_id: state.parent_label_id,
      compare_parent_id: state.compare_parent_id,
      analysis_parent_ids: analysisIds(),
      analysis_periods: analysisPeriods(),
      conditions: serializeConditions(state.conditions),
      label_period: state.label_period,
      identifiers: detailState.identifiers,
      country_categories: detailState.country_categories,
      stores: detailState.stores,
      countries: detailState.countries,
      detail_conditions: detailState.detail_conditions,
      sales_roles: detailState.sales_roles,
      role_reason_ids: detailState.role_reason_ids,
      current_stockout_only: detailState.current_stockout_only,
      stockout_before_role_period: detailState.stockout_before_role_period,
      stockout_before_role_ids: detailState.stockout_before_role_ids,
      daily_sales_bands: detailState.daily_sales_bands,
      margin_bands: detailState.margin_bands,
      ranking_bands: detailState.ranking_bands,
      problems: detailState.problems,
      problem_mode: detailState.problem_mode,
      page: detailState.page,
      page_size: detailState.page_size,
      sort_field: detailState.sort_field,
      sort_dir: detailState.sort_dir
    };
  }

  function setDetailLoading(isLoading) {
    elements.labelHubDetailApply.disabled = isLoading;
    elements.labelHubDetailApply.setAttribute("aria-busy", String(isLoading));
    elements.labelHubDetailApply.textContent = isLoading ? "筛选中…" : "应用筛选";
  }

  function setDetailExportLoading(isLoading) {
    elements.labelHubDetailExport.disabled = isLoading;
    elements.labelHubDetailExport.setAttribute("aria-busy", String(isLoading));
    elements.labelHubDetailExport.textContent = isLoading ? "导出中…" : "导出 CSV";
  }

  function detailExportFilename(response) {
    var disposition = response.headers.get("Content-Disposition") || "";
    var encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (encoded && encoded[1]) {
      try { return decodeURIComponent(encoded[1]); } catch (ignore) {}
    }
    return "标签看板-" + (detailState.detail_view === "country" ? "国家明细" : "MSKU维度") + ".csv";
  }

  function downloadDetailExport(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function exportDetails() {
    collectDetailFilters();
    renderDetailActiveFilters();
    setDetailExportLoading(true);
    return fetch("/api/label-hub/details/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(buildDetailPayload())
    }).then(function (response) {
      if (response.ok) {
        var filename = detailExportFilename(response);
        return response.blob().then(function (blob) { downloadDetailExport(blob, filename); });
      }
      return response.json().then(function (payload) {
        throw new Error(payload.detail || ("Request failed: " + response.status));
      });
    }).catch(function (error) {
      elements.labelHubHint.textContent = "标签明细导出失败：" + ((error && error.message) || "请稍后重试");
    }).then(function () {
      setDetailExportLoading(false);
    });
  }

  function renderDetails() {
    var token = ++detailRequestToken;
    setDetailLoading(true);
    elements.labelHubTable.setAttribute("aria-busy", "true");
    elements.labelHubTableSummary.textContent = "正在加载明细…";
    fetch("/api/label-hub/details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(buildDetailPayload())
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) throw new Error(payload.detail || ("Request failed: " + response.status));
        return payload;
      });
    }).then(function (payload) {
      if (token !== detailRequestToken) return;
      lastDetailPayload = payload;
      detailState.page = payload.page || 1;
      renderTable(payload);
      renderIdentifierResolution(payload.identifier_resolution || {});
      updateCountryOptions(((payload.filter_options || {}).countries) || []);
    }).catch(function (error) {
      if (token !== detailRequestToken) return;
      elements.labelHubTable.innerHTML = '<div class="empty-state">明细加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + "</div>";
      elements.labelHubTableSummary.textContent = "明细暂不可用";
    }).then(function () {
      if (token === detailRequestToken) {
        elements.labelHubTable.setAttribute("aria-busy", "false");
        setDetailLoading(false);
      }
    });
  }

  function renderIdentifierResolution(resolution) {
    var matched = resolution.matched || [];
    var unmatched = resolution.unmatched || [];
    var parts = [];
    if (matched.length) parts.push("已识别 " + matched.length + " 个");
    if (unmatched.length) parts.push("未识别：" + unmatched.join("、"));
    elements.labelHubIdentifierResolution.textContent = parts.join("；") || "未输入批量编码";
    elements.labelHubIdentifierResolution.classList.toggle("has-unmatched", unmatched.length > 0);
  }

  function updateCountryOptions(countries) {
    if (!countries.length) return;
    destroyDetailFilterSelects();
    elements.labelHubDetailCountries.innerHTML = multiOptionList(countries, detailState.countries);
    initDetailFilterSelects();
  }
  function serializeDetailConditions(values) {
    var grouped = {};
    (values || []).forEach(function (value) {
      var pair = String(value).split(":");
      if (pair.length !== 2) return;
      (grouped[pair[0]] || (grouped[pair[0]] = [])).push(pair[1]);
    });
    return Object.keys(grouped).sort(function (a, b) { return Number(a) - Number(b); }).map(function (parent) {
      return parent + ":" + unique(grouped[parent]).join("|");
    }).join(";");
  }
  function collectDetailFilters() {
    detailState.identifiers = splitIdentifiers(elements.labelHubDetailIdentifiers.value);
    detailState.detail_conditions = serializeDetailConditions(selectedValues(elements.labelHubDetailLabels));
    detailState.country_categories = selectedValues(elements.labelHubDetailCountryCategories);
    detailState.stores = selectedValues(elements.labelHubDetailStores);
    detailState.countries = selectedValues(elements.labelHubDetailCountries);
    detailState.problems = selectedValues(elements.labelHubDetailProblems);
    detailState.problem_mode = elements.labelHubDetailProblemMode.value || "any";
    detailState.sales_roles = selectedValues(elements.labelHubDetailSalesRoles);
    detailState.role_reason_ids = selectedValues(elements.labelHubDetailRoleReasons).map(Number);
    reconcileRoleReasonSelections();
    detailState.daily_sales_bands = selectedValues(elements.labelHubDetailDailyBands);
    detailState.margin_bands = selectedValues(elements.labelHubDetailMarginBands);
    detailState.ranking_bands = selectedValues(elements.labelHubDetailRankingBands);
  }
  function openIdentifierPopover() {
    elements.labelHubIdentifierBatchInput.value = elements.labelHubDetailIdentifiers.value;
    elements.labelHubIdentifierPopover.hidden = false;
    elements.labelHubIdentifierExpand.classList.add("is-open");
    elements.labelHubIdentifierExpand.setAttribute("aria-expanded", "true");
    window.setTimeout(function () { elements.labelHubIdentifierBatchInput.focus(); }, 0);
  }
  function closeIdentifierPopover(restoreFocus) {
    if (elements.labelHubIdentifierPopover.hidden) return;
    elements.labelHubIdentifierPopover.hidden = true;
    elements.labelHubIdentifierExpand.classList.remove("is-open");
    elements.labelHubIdentifierExpand.setAttribute("aria-expanded", "false");
    if (restoreFocus) elements.labelHubIdentifierExpand.focus();
  }
  function clearDetailFilters() {
    detailState.identifiers = []; detailState.country_categories = []; detailState.stores = []; detailState.countries = [];
    detailState.detail_conditions = ""; detailState.problems = []; detailState.problem_mode = "any";
    detailState.sales_roles = []; detailState.role_reason_ids = []; detailState.daily_sales_bands = []; detailState.margin_bands = []; detailState.ranking_bands = [];
    detailState.current_stockout_only = false; detailState.stockout_before_role_period = ""; detailState.stockout_before_role_ids = [];
    detailState.page = 1;
    elements.labelHubDetailIdentifiers.value = "";
    elements.labelHubIdentifierBatchInput.value = "";
    closeIdentifierPopover(false);
    [elements.labelHubDetailLabels, elements.labelHubDetailCountryCategories, elements.labelHubDetailStores, elements.labelHubDetailCountries,
      elements.labelHubDetailProblems, elements.labelHubDetailSalesRoles, elements.labelHubDetailRoleReasons,
      elements.labelHubDetailDailyBands, elements.labelHubDetailMarginBands, elements.labelHubDetailRankingBands].forEach(function (select) {
        Array.from(select.options).forEach(function (option) { option.selected = false; });
      });
    elements.labelHubDetailProblemMode.value = "any";
    destroyDetailFilterSelects();
    initDetailFilterSelects();
    syncDetailLabelControl();
    closeDetailLabelPanel();
    renderRoleReasonPanel();
    closeRoleReasonPanel();
    renderDetailActiveFilters();
    renderDetails();
  }
  function syncDetailViewControls() {
    var countryActive = detailState.detail_view === "country";
    elements.labelHubRoleReasonScope.textContent = countryActive ? "国家明细 · 国家站点诊断" : "MSKU维度 · 全站诊断";
    elements.labelHubDetailCountriesField.classList.toggle("is-retained", !countryActive && detailState.countries.length > 0);
    elements.labelHubCountryFilterHint.textContent = countryActive ? "当前已生效" : (detailState.countries.length ? "已保留，当前未生效" : "仅国家明细视图生效");
    elements.labelHubDetailRankingField.classList.toggle("is-retained", !countryActive && detailState.ranking_bands.length > 0);
    elements.labelHubRankingFilterHint.textContent = countryActive ? "当前已生效" : (detailState.ranking_bands.length ? "已保留，当前未生效" : "仅国家明细视图生效");
    elements.labelHubRankingFilterHint.hidden = countryActive || !detailState.ranking_bands.length;
  }

  function detailFilterSelects() {
    return [
      elements.labelHubDetailCountryCategories, elements.labelHubDetailStores,
      elements.labelHubDetailCountries, elements.labelHubDetailSalesRoles,
      elements.labelHubDetailDailyBands, elements.labelHubDetailMarginBands,
      elements.labelHubDetailRankingBands
    ].filter(Boolean);
  }

  function destroyDetailFilterSelects() {
    detailFilterSelectInstances.forEach(function (instance) { instance.destroy(); });
    detailFilterSelectInstances = [];
  }

  function initDetailFilterSelects() {
    if (!window.SlimSelect) return;
    destroyDetailFilterSelects();
    detailFilterSelects().forEach(function (select) {
      detailFilterSelectInstances.push(new window.SlimSelect({
        select: select,
        settings: {
          placeholderText: select.dataset.placeholder || "全部",
          closeOnSelect: false,
          allowDeselect: true,
          showSearch: select.options.length > 7,
          searchPlaceholder: "搜索",
          searchText: "无匹配项",
          maxValuesShown: 1,
          maxValuesMessage: "已选 {number} 项",
          modal: "off",
          contentPosition: "absolute",
          openPosition: "auto"
        }
      }));
    });
  }

  function setNativeSelections(select, values) {
    var selectedMap = {};
    (values || []).forEach(function (value) { selectedMap[String(value)] = true; });
    Array.from((select && select.options) || []).forEach(function (option) { option.selected = !!selectedMap[String(option.value)]; });
  }

  function syncDetailNativeSelections() {
    setNativeSelections(elements.labelHubDetailLabels, detailConditionValues());
    setNativeSelections(elements.labelHubDetailCountryCategories, detailState.country_categories);
    setNativeSelections(elements.labelHubDetailStores, detailState.stores);
    setNativeSelections(elements.labelHubDetailCountries, detailState.countries);
    setNativeSelections(elements.labelHubDetailProblems, detailState.problems);
    setNativeSelections(elements.labelHubDetailSalesRoles, detailState.sales_roles);
    setNativeSelections(elements.labelHubDetailRoleReasons, detailState.role_reason_ids);
    setNativeSelections(elements.labelHubDetailDailyBands, detailState.daily_sales_bands);
    setNativeSelections(elements.labelHubDetailMarginBands, detailState.margin_bands);
    setNativeSelections(elements.labelHubDetailRankingBands, detailState.ranking_bands);
    elements.labelHubDetailProblemMode.value = detailState.problem_mode || "any";
  }

  function toggleDetailAdvancedFilters() {
    detailAdvancedOpen = !detailAdvancedOpen;
    if (!detailAdvancedOpen) closeRoleReasonPanel();
    elements.labelHubDetailAdvanced.hidden = !detailAdvancedOpen;
    elements.labelHubDetailMore.classList.toggle("is-open", detailAdvancedOpen);
    elements.labelHubDetailMore.setAttribute("aria-expanded", String(detailAdvancedOpen));
  }

  function selectedOptionLabel(select, value) {
    var option = Array.from((select && select.options) || []).find(function (item) { return String(item.value) === String(value); });
    return option ? (option.dataset.fullLabel || option.textContent.trim()) : String(value);
  }

  function detailFilterChip(field, value, label) {
    return '<button type="button" class="label-hub-detail-filter-chip" data-detail-filter-field="' + app.escapeHtml(field) + '" data-detail-filter-value="' + app.escapeHtml(String(value)) + '"><span>' + app.escapeHtml(label) + '</span><i aria-hidden="true">×</i></button>';
  }

  function renderDetailActiveFilters() {
    if (!elements.labelHubDetailActiveFilterList) return;
    var chips = [];
    if (detailState.identifiers.length) chips.push(detailFilterChip("identifiers", "", "编码 " + detailState.identifiers.length + " 个"));
    if (detailState.current_stockout_only) {
      var roleNames = detailState.stockout_before_role_ids.map(function (id) { return STOCKOUT_ROLE_LABELS[String(id)] || String(id); });
      var roleScopeLabel = "断货中 · " + stockoutRolePeriodLabel(detailState.stockout_before_role_period || "30d") + "断货前角色";
      if (roleNames.length) roleScopeLabel += " · " + roleNames.join("、");
      chips.push(detailFilterChip("stockout_before_role_scope", "", roleScopeLabel));
    }
    [
      ["problems", "问题", elements.labelHubDetailProblems],
      ["country_categories", "国家类别", elements.labelHubDetailCountryCategories],
      ["stores", "店铺", elements.labelHubDetailStores],
      ["countries", detailState.detail_view === "country" ? "国家" : "国家（已保留）", elements.labelHubDetailCountries],
      ["detail_conditions", "标签", elements.labelHubDetailLabels],
      ["sales_roles", "销售角色", elements.labelHubDetailSalesRoles],
      ["role_reason_ids", "角色原因", elements.labelHubDetailRoleReasons],
      ["daily_sales_bands", "日销段", elements.labelHubDetailDailyBands],
      ["margin_bands", "毛利段", elements.labelHubDetailMarginBands],
      ["ranking_bands", detailState.detail_view === "country" ? "排名" : "排名（已保留）", elements.labelHubDetailRankingBands]
    ].forEach(function (config) {
      var values = config[0] === "detail_conditions" ? detailConditionValues() : (detailState[config[0]] || []);
      values.forEach(function (value) { chips.push(detailFilterChip(config[0], value, config[1] + "：" + selectedOptionLabel(config[2], value))); });
    });
    elements.labelHubDetailActiveFilterList.innerHTML = chips.join("") || '<span class="label-hub-detail-empty-filter">暂无明细筛选</span>';
    var advancedCount = detailConditionValues().length + detailState.sales_roles.length + detailState.role_reason_ids.length + detailState.daily_sales_bands.length + detailState.margin_bands.length + detailState.ranking_bands.length;
    elements.labelHubDetailMoreCount.textContent = String(advancedCount);
    elements.labelHubDetailMoreCount.hidden = advancedCount === 0;
  }

  function removeDetailFilter(field, value) {
    if (field === "identifiers") {
      detailState.identifiers = [];
      elements.labelHubDetailIdentifiers.value = "";
      elements.labelHubIdentifierBatchInput.value = "";
    } else if (field === "stockout_before_role_scope") {
      detailState.current_stockout_only = false;
      detailState.stockout_before_role_period = "";
      detailState.stockout_before_role_ids = [];
    } else if (field === "detail_conditions") {
      detailState.detail_conditions = serializeDetailConditions(detailConditionValues().filter(function (item) { return item !== value; }));
    } else if (Array.isArray(detailState[field])) {
      detailState[field] = detailState[field].filter(function (item) { return String(item) !== String(value); });
    }
    detailState.page = 1;
    populateControls();
    renderDetails();
  }
  function parsedConditions() {
    var result = {};
    serializeConditions(state.conditions).split(";").filter(Boolean).forEach(function (group) {
      var pair = group.split(":");
      if (pair.length === 2) result[pair[0]] = pair[1].split("|").filter(Boolean);
    });
    return result;
  }
  function saveConditions(value) {
    var roles = value["1"] || [];
    if (roles.length === 1) {
      var allowedDiagnostics = {
        "101": { "15": ["1501"], "16": ["1601"] },
        "102": { "15": ["1502", "1503"], "16": ["1602", "1603", "1604", "1605", "1606"] },
        "103": { "15": ["1504", "1505", "1506"], "16": ["1607", "1608", "1609", "1610", "1611", "1612", "1613"] },
        "104": { "15": ["1507", "1508"], "16": ["1614", "1615", "1616", "1617", "1618"] }
      }[roles[0]] || {};
      ["15", "16"].forEach(function (parent) {
        if (!value[parent]) return;
        value[parent] = value[parent].filter(function (child) {
          return (allowedDiagnostics[parent] || []).indexOf(String(child)) >= 0;
        });
        if (!value[parent].length) delete value[parent];
      });
    }
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
  function applyReturnAttributionFilter(operationChildId) {
    var values = parsedConditions();
    values["3"] = [String(operationChildId)];
    values["5"] = ["501", "502", "503"];
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
    lastPayload = null;
    lastHighlights = null;
    detailState.page = 1;
    renderDetails();
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
      if (elements.labelHubDiagnosticsSection.open) loadDiagnostics();
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

  function currentCombinationLayer() {
    var conditions = parsedConditions();
    var keys = Object.keys(conditions).filter(function (parent) { return (conditions[parent] || []).length === 1; });
    var preferred = String(state.parent_label_id || "");
    var parent = keys.indexOf(preferred) >= 0 ? preferred : (keys.length ? keys[keys.length - 1] : "");
    if (!parent) return null;
    var category = categoryById(parent);
    var child = (conditions[parent] || [])[0];
    var childItem = category && (category.children || []).find(function (item) { return String(item.id) === String(child); });
    return {
      parent: Number(parent),
      bucket: child,
      period: Number(parent) === Number(state.parent_label_id) ? (state.label_period || "all") : "all",
      title: (category ? category.label + "：" : "") + (childItem ? childItem.label : child)
    };
  }

  function buildCurrentCombinationChangeParams() {
    var params = buildChangeParams();
    var layer = currentCombinationLayer();
    if (layer) {
      params.layer_change_parent = layer.parent;
      params.layer_change_bucket = layer.bucket;
      params.layer_change_period = layer.period;
    }
    return params;
  }

  function loadChanges() {
    if (!meta || !elements.labelHubChangeBrief) return;
    var comparison = meta.comparison || {};
    if (!comparison.available) {
      elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>暂无可比较数据</strong>';
      return;
    }
    var token = ++changeRequestToken;
    elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>正在核对各层级变化…</strong>';
    app.apiGet("/api/label-hub/changes", buildCurrentCombinationChangeParams(), CHANGE_REQUEST_OPTIONS).then(function (payload) {
      if (token !== changeRequestToken) return;
      lastHighlights = payload;
      renderChangeBrief(payload);
      applyChildChangeBadges(payload);
      if (lastPayload) renderBreakdowns(lastPayload);
    }).catch(function (error) {
      if (token !== changeRequestToken) return;
      elements.labelHubChangeBrief.innerHTML = '<span>较上期变化</span><strong>变化数据暂不可用</strong>';
    });
  }

  function formatRate(value) {
    if (value === null || value === undefined || !isFinite(Number(value))) return "新出现";
    var percentage = Number(value) * 100;
    return (percentage > 0 ? "+" : "") + percentage.toFixed(Math.abs(percentage) >= 10 ? 1 : 1) + "%";
  }

  function currentCombinationLabels() {
    var labels = Array.from(elements.labelHubConditions ? elements.labelHubConditions.querySelectorAll(".sales-role-chip") : []).map(function (node) {
      return String(node.textContent || "").replace(/×\s*$/, "").trim();
    }).filter(Boolean);
    return labels;
  }

  function transitionSummary(items, fallback, total, emptyLabel) {
    if (!items || !items.length) {
      var count = Number(total || 0);
      return '<span class="label-hub-combination-empty">' + (count ? (emptyLabel + ' ' + formatNumber(count) + '（暂无具体标签层可归类）') : fallback) + '</span>';
    }
    return items.slice(0, 3).map(function (item) {
      return '<span><b>' + app.escapeHtml(item.previous_label || "未命中") + '</b><i>→</i><b>' + app.escapeHtml(item.current_label || "未命中") + '</b><strong>' + formatNumber(item.count) + '</strong></span>';
    }).join("");
  }

  function renderCurrentCombinationChange(payload) {
    if (!payload.available) {
      elements.labelHubChangeScope.textContent = "当前远端只有一个标签日期，暂无可比较的上次数据。";
      elements.labelHubChangeSubtitle.textContent = "保留当前看板展示；有第二个标签日期后将自动启用。";
      elements.labelHubChangeContent.innerHTML = '<div class="empty-state compact">有第二个标签日期后将自动展示当前组合变化。</div>';
      elements.labelHubOpenChanges.disabled = true;
      return;
    }
    var scope = payload.scope || {};
    var summary = payload.combination_summary || payload.summary || {};
    var labels = currentCombinationLabels();
    var layer = currentCombinationLayer();
    var reasons = summary.reason_summary || [];
    var net = Number(summary.net || 0);
    var groupLabel = labels.length ? "当前组合" : "全部店铺商品记录";
    elements.labelHubChangeScope.textContent = "店铺商品记录口径 · 当前筛选条件两期独立重算";
    elements.labelHubChangeSubtitle.textContent = "固定当前组合，查看上次到今日进入、离开及主要流向 · " + (scope.comparison_label || "较上次数据") + " " + (scope.previous_date || "-") + " → " + (scope.current_date || "-");
    elements.labelHubOpenChanges.disabled = false;
    renderChangeBrief(payload);
    var detailHtml = layer ? '<div class="label-hub-combination-details">' +
        '<section><h3>进入来源</h3>' + transitionSummary(summary.entered, "本期没有进入", summary.added, "新增记录") + '</section>' +
        '<section><h3>离开去向</h3>' + transitionSummary(summary.left, "本期没有离开", summary.removed, "减少记录") + '</section>' +
        '<section class="label-hub-combination-reasons"><h3>简要说明</h3>' + (reasons.length ? reasons.map(function (item) { return '<span><b>' + app.escapeHtml(normalizeMskuDetailCopy(item.label || "标签事实变化")) + '</b><strong>' + formatNumber(item.count) + '</strong></span>'; }).join("") : '<span class="label-hub-combination-empty">当前仅确认标签事实进出，暂无可核实规则原因</span>') + '</section>' +
      '</div>' : '<div class="label-hub-combination-no-filter"><strong>未选择联动条件</strong><span>当前展示全部店铺商品记录的总量变化；选择标签后可继续查看进入来源、离开去向和简要原因。</span></div>';
    elements.labelHubChangeContent.innerHTML = '<div class="label-hub-combination-change">' +
      '<div class="label-hub-combination-chips"><span>' + groupLabel + '</span>' + labels.map(function (label) { return '<b>' + app.escapeHtml(label) + '</b>'; }).join('<i>+</i>') + '</div>' +
      '<div class="label-hub-combination-ledger">' +
        '<div class="label-hub-combination-volume"><small>上次</small><strong>' + formatNumber(summary.previous) + '</strong><i>→</i><small>今日</small><strong>' + formatNumber(summary.current) + '</strong></div>' +
        '<b class="label-hub-combination-net ' + (net > 0 ? "is-up" : (net < 0 ? "is-down" : "is-flat")) + '">净变化 ' + deltaText(net) + '</b>' +
        '<span class="label-hub-combination-flow">本期进入 <strong>' + formatNumber(summary.added) + '</strong><i>·</i>本期离开 <strong>' + formatNumber(summary.removed) + '</strong></span>' +
      '</div>' + detailHtml +
      '<div class="label-hub-combination-actions"><button type="button" data-current-combination-detail>查看变化明细 <b>›</b></button></div>' +
    '</div>';
  }

  function openCurrentCombinationDetails() {
    var layer = currentCombinationLayer();
    if (!layer) { openFullChangeDetailsDrawer(); return; }
    var context = {source: "remote_label", key: "remote:" + layer.parent, parent: layer.parent, bucket: layer.bucket, period: layer.period, change_type: "all", title: layer.title};
    context.combination_labels = layerChangeCombinationLabels(context);
    activeLayerChangeContext = context;
    setDrawerMode("layer-changes");
    elements.labelHubDrawer.hidden = false;
    loadLayerChangeDetails(context);
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
    if (!lastHighlights || !lastHighlights.available) return "";
    var index = breakdownDeltaIndex(lastHighlights);
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
      ? formatNumber(changed) + " 条记录的标签发生流转"
      : "当前群体标签结构保持稳定";
    var detail = "新增 " + formatNumber(summary.added) + " · 减少 " + formatNumber(summary.removed);
    if (reason) detail += " · 主要原因：" + normalizeMskuDetailCopy(reason.label);
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
    return '<section class="label-hub-change-sankey-card"><header><div><span>标签流向</span><h3>上次标签 → 今日标签</h3></div><small>线条越宽，流转的记录越多；悬停可查看具体数量</small></header>' +
      (hasFlow ? '<div class="label-hub-change-sankey" data-change-sankey role="img" aria-label="店铺商品记录的标签流向图"></div>' : '<div class="empty-state compact">当前筛选下暂无可展示的标签流向。</div>') +
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
              return app.escapeHtml(params.data.previousLabel) + " → " + app.escapeHtml(params.data.currentLabel) + "<br><b>" + formatNumber(params.value) + " 条记录</b>";
            }
            return app.escapeHtml(params.data.displayLabel || "") + "<br><b>" + formatNumber(params.value) + " 条记录</b>";
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
    var layerLabel = changeLayerLabel(context);
    var transitions = payload.layer_transitions || {};
    var routes = (transitions.entered || []).concat(transitions.left || []).slice().sort(function (a, b) {
      return Number(b.count || 0) - Number(a.count || 0);
    });
    var mainRoute = routes[0];
    var evidenceTotal = routes.reduce(function (sum, item) {
      var evidenceCounts = item.evidence_counts || {};
      return sum + Object.keys(evidenceCounts).reduce(function (inner, key) { return inner + Number(evidenceCounts[key] || 0); }, 0);
    }, 0);
    var confirmed = routes.reduce(function (sum, item) {
      return sum + Number((item.evidence_counts || {}).confirmed || 0);
    }, 0);
    var netText = net > 0 ? "净增加 " + formatNumber(net) : (net < 0 ? "净减少 " + formatNumber(Math.abs(net)) : "数量持平");
    var routeText = mainRoute
      ? (mainRoute.previous_label === mainRoute.current_label
        ? "主要变化来自其他联动条件进出，同维度标签仍为“" + (mainRoute.current_label || "无标签事实") + "”，共 " + formatNumber(mainRoute.count) + " 个。"
        : "主要流向：“" + (mainRoute.previous_label || "无标签事实") + "”→“" + (mainRoute.current_label || "无标签事实") + "”，共 " + formatNumber(mainRoute.count) + " 个。")
      : "本期没有 MSKU 进入或离开该层。";
    return '<section class="label-hub-layer-ledger label-hub-change-result">' +
      '<div class="label-hub-change-result-main"><span>本层变化结论</span><h3>' + app.escapeHtml(layerLabel) + '今日 ' + formatNumber(summary.current) + ' 个，较上次' + netText + '</h3><p>' + app.escapeHtml(routeText) + '</p></div>' +
      '<div class="label-hub-change-reconcile" aria-label="变化数量对账">' +
        '<span><small>上次</small><b>' + formatNumber(summary.previous) + '</b></span><i>+</i>' +
        '<span><small>进入</small><b>' + formatNumber(summary.added) + '</b></span><i>−</i>' +
        '<span><small>离开</small><b>' + formatNumber(summary.removed) + '</b></span><i>=</i>' +
        '<span class="is-current"><small>今日</small><b>' + formatNumber(summary.current) + '</b></span>' +
        '<strong class="is-' + (net > 0 ? "up" : (net < 0 ? "down" : "flat")) + '">' + netText + '</strong>' +
      '</div>' +
      '<div class="label-hub-change-proof"><span>口径：当前完整组合，两期独立重算</span><span>' + (evidenceTotal ? "规则证据已确认 " + formatNumber(confirmed) + " / " + formatNumber(evidenceTotal) : "当前仅有标签事实流转") + '</span></div>' +
      '</section>';
  }

  function layerLabelNeedsAttention(label) {
    return /(问题|负毛利|亏损|高库存|断货|停售|清仓|异常|风险|严重退货|高度依赖|日销\s*0|低毛利)/.test(String(label || ""));
  }

  function renderLayerTransitionSummary(payload, context) {
    var transitions = payload.layer_transitions || {};
    function renderRoute(item, direction) {
      var active = context &&
        context.change_type === direction &&
        context.transition_from === String(item.previous_label || "无标签事实") &&
        context.transition_to === String(item.current_label || "无标签事实") &&
        Number(context.transition_parent || 0) === Number(item.changed_parent_id || 0) &&
        context.transition_previous === String(item.changed_previous_label || "") &&
        context.transition_current === String(item.changed_current_label || "");
      var unchangedLabel = item.previous_label === item.current_label;
      var changedDimension = item.changed_dimension || (unchangedLabel ? "其他筛选条件" : context.title);
      var changedPrevious = item.changed_previous_label || item.previous_label || "未命中";
      var changedCurrent = item.changed_current_label || item.current_label || "未命中";
      var routeNote = unchangedLabel && (changedPrevious !== item.previous_label || changedCurrent !== item.current_label)
        ? changedDimension + "：" + changedPrevious + " → " + changedCurrent
        : changedDimension + "发生变化";
      var evidenceCounts = item.evidence_counts || {};
      var proof = Number(evidenceCounts.confirmed || 0);
      var impact = "销售额 " + app.formatCompactCurrency(item.sales_amount || 0) + " · 毛利润 " + app.formatCompactCurrency(item.order_gross_profit || 0);
      return '<button type="button" class="label-hub-route-ledger' + (active ? ' is-active' : '') + '" data-layer-transition-type="' + direction + '" data-layer-transition-from="' + app.escapeHtml(item.previous_label || "无标签事实") + '" data-layer-transition-to="' + app.escapeHtml(item.current_label || "无标签事实") + '" data-layer-transition-parent="' + Number(item.changed_parent_id || 0) + '" data-layer-transition-previous="' + app.escapeHtml(changedPrevious) + '" data-layer-transition-current="' + app.escapeHtml(changedCurrent) + '">' +
        '<span class="label-hub-route-path"><b>' + app.escapeHtml(item.previous_label || "未命中") + '</b><i>→</i><b>' + app.escapeHtml(item.current_label || "未命中") + '</b><em>' + formatNumber(item.count) + ' 个</em></span>' +
        '<span class="label-hub-route-cause">' + app.escapeHtml(routeNote) + '</span>' +
        '<small>' + app.escapeHtml(impact) + (proof ? ' · 已确认 ' + formatNumber(proof) : '') + '</small>' +
      '</button>';
    }

    function routeColumn(title, subtitle, items, direction) {
      var total = (items || []).reduce(function (sum, item) { return sum + Number(item.count || 0); }, 0);
      return '<article class="label-hub-route-column"><header><div><span>' + app.escapeHtml(subtitle) + '</span><h3>' + app.escapeHtml(title) + '</h3></div><b>' + formatNumber(total) + ' 个</b></header><div>' +
        ((items || []).map(function (item) { return renderRoute(item, direction); }).join("") || '<div class="label-hub-route-empty">本期没有' + app.escapeHtml(title) + '</div>') +
      '</div></article>';
    }

    var reasons = (payload.sales_role_reasons || []).filter(function (item) { return Number(item.count || 0) > 0; });
    var reasonHtml = reasons.length
      ? '<div class="label-hub-attribution-grid">' + reasons.map(function (item) {
        var tone = ["evidence_missing", "evidence_mismatch"].indexOf(item.key) >= 0 ? "pending" : "confirmed";
        return '<span class="is-' + tone + '"><small>' + app.escapeHtml(item.label) + '</small><b>' + formatNumber(item.count) + '</b></span>';
      }).join("") + '</div>'
      : '<div class="label-hub-route-empty">当前标签仅能确认事实流转，暂无可核对的规则指标。</div>';
    return '<section class="label-hub-layer-transition-summary label-hub-route-summary"><header><div><span>本层进出路径</span><h3>从哪里进入，离开后去了哪里</h3></div><small>点击任一路径查看对应 MSKU、指标前后值与证据状态。</small></header>' +
      '<div class="label-hub-route-columns">' +
        routeColumn("进入当前层", "本期新增成员", transitions.entered || [], "added") +
        routeColumn("离开当前层", "本期退出成员", transitions.left || [], "removed") +
      '</div>' +
      '<div class="label-hub-attribution-summary"><header><div><span>指标归因</span><h3>哪些规则指标跨过了阈值</h3></div><small>仅证据一致时作为确定原因，其余标记待核对。</small></header>' + reasonHtml + '</div>' +
    '</section>';
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
      var previousValue = row.previous_label || "未命中";
      var currentValue = row.current_label || "未命中";
      var typeLabel = row.change_type === "changed"
        ? (previousValue !== currentValue ? "标签切换" : "其他标签变化")
        : ({ added: "转入", removed: "转出", unchanged: "保持" }[row.change_type] || row.change_type_label);
      var triggerLabel = (row.trigger_dimensions || []).join(" / ");
      if (isLayerDetail) {
        var metric = row.metric_profile || {};
        var previousMetric = row.previous_metric_profile || {};
        var previousEvidence = row.previous_evidence || {};
        var currentEvidence = row.current_evidence || {};
        var profitClass = Number(metric.order_gross_profit || 0) < 0 ? ' is-negative' : '';
        var identity = '<button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button><small>' + app.escapeHtml(row.country_category || "-") + ' · ' + app.escapeHtml(row.store || "-") + '</small>';
        var labelChange = '<span class="label-hub-change-label-pair"><b>' + app.escapeHtml(row.previous_layer_label || "未命中") + '</b><i>→</i><b>' + app.escapeHtml(row.current_layer_label || "未命中") + '</b></span>';
        var reasonCodeLabel = {
          daily_cross: "日销跨线",
          margin_cross: "毛利率跨线",
          both_cross: "日销与毛利率同时跨线",
          rule_metric_change: "规则指标发生变化",
          business_unit_added: "新增记录",
          business_unit_removed: "记录消失",
          evidence_missing: "规则证据缺失",
          evidence_mismatch: "本地重算不一致"
        }[row.sales_role_reason_code] || "仅标签事实";
        var reason = '<div class="label-hub-change-reason-cell"><strong>' + app.escapeHtml(reasonCodeLabel) + '</strong><small title="' + app.escapeHtml(row.sales_role_reason || "") + '">' + app.escapeHtml(row.sales_role_reason || "暂不能确认具体规则原因") + '</small></div>';
        var daily = previousEvidence.daily_sales === undefined || currentEvidence.daily_sales === undefined
          ? '<span class="is-missing">--</span>'
          : '<span><b>' + formatNumber(previousEvidence.daily_sales) + '</b><i>→</i><b>' + formatNumber(currentEvidence.daily_sales) + '</b></span>';
        var margin = previousEvidence.margin_rate === undefined || currentEvidence.margin_rate === undefined
          ? '<span class="is-missing">--</span>'
          : '<span><b>' + formatPercent(previousEvidence.margin_rate) + '</b><i>→</i><b>' + formatPercent(currentEvidence.margin_rate) + '</b></span>';
        var ruleMetricRows = (row.rule_metric_changes || []).map(function (item) {
          function formatRuleMetric(value) {
            if (value === undefined || value === null || value === "") return "--";
            if (item.value_type === "percent_value") return formatNumber(value) + "%";
            if (item.value_type === "days") return formatNumber(value) + " 天";
            if (item.value_type === "money") return app.formatCompactCurrency(value);
            return formatNumber(value);
          }
          return '<div class="label-hub-rule-metric-row"><small>' + app.escapeHtml(item.label || item.key || "规则指标") + '</small><span><b>' + app.escapeHtml(formatRuleMetric(item.previous)) + '</b><i>→</i><b>' + app.escapeHtml(formatRuleMetric(item.current)) + '</b></span></div>';
        }).join("");
        var ruleMetricShift = ruleMetricRows
          ? '<div class="label-hub-change-metric-shift is-dynamic">' + ruleMetricRows + '</div>'
          : '<div class="label-hub-change-metric-shift"><small>日销</small>' + daily + '<small>毛利率</small>' + margin + '</div>';
        var proofLabel = { confirmed: "已确认", mismatch: "重算不一致", pending: "待核对", fact_only: "仅标签事实" }[row.evidence_state] || "仅标签事实";
        var evidence = '<div class="label-hub-change-evidence is-' + app.escapeHtml(row.evidence_state || "fact_only") + '"><span>' + app.escapeHtml(proofLabel) + '</span><small>' + app.escapeHtml(row.fact_status || "标签事实可比") + '</small></div>';
        var impact = '<div class="label-hub-change-impact"><span>销售额 <b>' + app.formatCompactCurrency(metric.sales_amount || 0) + '</b></span><span>毛利润 <b class="' + profitClass + '">' + app.formatCompactCurrency(metric.order_gross_profit || 0) + '</b></span><small>上次 ' + app.formatCompactCurrency(previousMetric.sales_amount || 0) + ' / ' + app.formatCompactCurrency(previousMetric.order_gross_profit || 0) + '</small></div>';
        return '<tr><td><div class="label-hub-change-identity">' + identity + '</div></td><td>' + labelChange + '</td><td>' + reason + '</td><td>' + ruleMetricShift + '</td><td>' + impact + '</td><td>' + evidence + '</td></tr>';
      }
      return '<tr><td>' + app.escapeHtml(row.country_category || "-") + '</td><td>' + app.escapeHtml(row.store || "-") + '</td><td><button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button></td><td>' + app.escapeHtml(previousValue) + '</td><td>' + app.escapeHtml(currentValue) + '</td><td><div class="label-hub-change-direction"><span class="label-hub-change-type is-' + app.escapeHtml(row.change_type) + '">' + app.escapeHtml(typeLabel) + '</span>' + (triggerLabel ? '<small>变化维度：' + app.escapeHtml(triggerLabel) + '</small>' : '') + '</div></td></tr>';
    }).join("");
    var pagination = '<div class="label-hub-change-pagination"><span>第 ' + payload.page + " / " + payload.total_pages + ' 页，共 ' + formatNumber(payload.total) + ' 条记录</span><div><button type="button" data-change-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><button type="button" data-change-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + '>下一页</button></div></div>';
    if (isLayerDetail) {
      return '<div class="label-hub-change-table-wrap label-hub-attention-table"><table><thead><tr><th>MSKU</th><th>同维度标签</th><th>变化原因</th><th>规则指标（上次→今日）</th><th>经营影响</th><th>证据状态</th></tr></thead><tbody>' + (rows || '<tr><td colspan="6"><div class="empty-state compact">当前变化项下没有 MSKU 记录。</div></td></tr>') + '</tbody></table></div>' + pagination;
    }
    return '<div class="label-hub-change-table-wrap"><table><thead><tr><th>国家类别</th><th>店铺</th><th>MSKU</th><th>当前大类上次标签</th><th>当前大类今日标签</th><th>实际变化</th></tr></thead><tbody>' + (rows || '<tr><td colspan="6"><div class="empty-state compact">当前筛选下没有变化的记录。</div></td></tr>') + '</tbody></table></div>' + pagination;
  }

  function renderChangeRows(payload) {
    var rows = (payload.rows || []).map(function (row) {
      var reason = row.sales_role_reason || "仅记录标签事实流转";
      return '<tr><td>' + app.escapeHtml(row.country_category || "-") + '</td><td>' + app.escapeHtml(row.store || "-") + '</td><td><button type="button" class="text-button label-hub-change-msku" data-change-msku="' + app.escapeHtml(row.msku) + '">' + app.escapeHtml(row.msku) + '</button></td><td>' + app.escapeHtml(row.previous_label || "未命中") + '</td><td>' + app.escapeHtml(row.current_label || "未命中") + '</td><td><span class="label-hub-change-type is-' + app.escapeHtml(row.change_type) + '">' + app.escapeHtml(row.change_type_label) + '</span></td><td>' + app.escapeHtml((row.trigger_dimensions || []).join(" / ") || "无标签维度变化") + '</td><td>' + (row.previous_matched ? "是" : "否") + '</td><td>' + (row.current_matched ? "是" : "否") + '</td><td title="' + app.escapeHtml(reason) + '">' + app.escapeHtml(reason) + '</td></tr>';
    }).join("");
    var pagination = '<div class="label-hub-change-pagination"><span>第 ' + payload.page + " / " + payload.total_pages + ' 页，共 ' + formatNumber(payload.total) + ' 条记录</span><div><button type="button" data-change-page="' + (payload.page - 1) + '"' + (payload.page <= 1 ? " disabled" : "") + '>上一页</button><button type="button" data-change-page="' + (payload.page + 1) + '"' + (payload.page >= payload.total_pages ? " disabled" : "") + '>下一页</button></div></div>';
    return '<div class="label-hub-change-table-wrap"><table><thead><tr><th>国家类别</th><th>店铺</th><th>MSKU</th><th>上次主标签</th><th>今日主标签</th><th>变化类型</th><th>触发维度</th><th>上次满足</th><th>今日满足</th><th>销售角色原因摘要</th></tr></thead><tbody>' + (rows || '<tr><td colspan="10"><div class="empty-state compact">当前变化类型下没有记录。</div></td></tr>') + '</tbody></table></div>' + pagination;
  }

  function changeContentHtml(payload, context) {
    if (!payload.available) return '<div class="empty-state compact">暂无可比较的上次标签数据。</div>';
    if (context) {
      var routeSelected = Boolean(context.transition_from || context.transition_to);
      return renderLayerChangeLedger(payload, context) + renderLayerTransitionSummary(payload, context) +
        (routeSelected
          ? '<article class="label-hub-change-detail label-hub-attention-detail"><header><div><span>变化 MSKU</span><h3>对应产品与经营表现</h3></div><small>点击 MSKU 查看两日标签画像</small></header>' + renderChangeList(payload, context) + '</article>'
          : '<div class="label-hub-change-detail-placeholder"><strong>选择上方一项变化查看 MSKU</strong><span>明细仅在需要时展开，避免把正常变化和问题记录混在一起。</span></div>');
    }
    return renderChangeConclusion(payload, context) +
      '<article class="label-hub-change-detail"><header><div><span>变化记录</span><h3>仅查看发生标签变化的记录</h3></div><small>点击 MSKU 查看两日标签画像</small></header>' +
      renderChangeList(payload, context) + '</article>';
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
      return '<article class="label-hub-category-card ' + app.escapeHtml(item.state || "") + active + '"><button type="button" class="label-hub-category-head" data-overview-parent="' + item.id + '" aria-pressed="' + (active ? "true" : "false") + '"><span><b>' + app.escapeHtml(item.label) + '</b><small>' + app.escapeHtml(stateLabel) + '</small></span><strong>' + formatNumber(uniqueCount) + '<small> MSKU</small></strong></button><div class="label-hub-category-meta label-hub-category-meta-single"><span>' + formatNumber(businessCount) + ' 条记录</span></div><div class="label-hub-category-foot"><span>' + app.escapeHtml(flags.join(" · ") || "单一口径") + '</span><button type="button" class="label-hub-rule-link" data-view-rules="' + item.id + '">查看划分规则</button></div></article>';
    }).join("");
  }

  function renderPopulationSummary(payload) {
    var summary = payload.population_summary || {};
    var cards = [
      { label: "去重 MSKU", value: summary.unique_msku_count, note: "合并跨店铺与国家类别后的商品规模" },
      { label: "店铺商品记录", value: summary.business_unit_count, note: "国家类别 + 店铺 + MSKU" },
      { label: "跨范围 MSKU", value: summary.cross_scope_msku_count, note: "同一 MSKU 出现在多个店铺或国家类别" }
    ];
    elements.labelHubPopulationSummary.innerHTML = cards.map(function (item, index) {
      return '<article class="label-hub-population-card tone-' + index + '"><span>' + app.escapeHtml(item.label) + '</span><strong>' + formatNumber(item.value || 0) + '</strong><small>' + app.escapeHtml(item.note) + '</small></article>';
    }).join("");
  }

  function closeOperatingStockoutPopover() {
    var popover = elements.labelHubCategoryDetail.querySelector("[data-operating-stockout-popover]");
    var trigger = elements.labelHubCategoryDetail.querySelector("[data-operating-stockout-formula]");
    if (popover) popover.hidden = true;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  }

  function toggleOperatingStockoutPopover(trigger) {
    var popover = elements.labelHubCategoryDetail.querySelector("[data-operating-stockout-popover]");
    if (!popover) return;
    var shouldOpen = popover.hidden;
    popover.hidden = !shouldOpen;
    trigger.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
  }

  function renderOperatingStockoutRate(payload, item) {
    var metric = payload.operating_stockout_rate;
    if (!metric || item.label !== "运营状态" || metric.rate === null || Number(metric.operating_count || 0) <= 0) return "";
    return '<footer class="label-hub-operating-stockout-rate">' +
      '<div class="label-hub-operating-stockout-anchor">' +
      '<span>在营断货率</span><strong>' + formatPercent(metric.rate) + '</strong>' +
      '</div>' +
      '<div class="label-hub-operating-stockout-details">' +
      '<span>有效断货 ' + formatNumber(metric.effective_stockout_count) + ' / 在营 ' + formatNumber(metric.operating_count) + '</span>' +
      '<i>·</i><span>返场再断货 ' + formatNumber(metric.return_restockout_count) + '</span>' +
      '<i>·</i><button type="button" data-operating-stockout-formula aria-expanded="false" aria-controls="labelHubOperatingStockoutPopover">查看口径</button>' +
      '</div>' +
      '<aside id="labelHubOperatingStockoutPopover" class="label-hub-operating-stockout-popover" data-operating-stockout-popover role="note" hidden>' +
      '<strong>在营断货率口径</strong>' +
      '<p><b>有效断货</b> = 断货中 − 返场期再次断货</p>' +
      '<p><b>在营记录</b> = 正常在售 + 测款扶持 + 返厂品 + 断货中</p>' +
      '<small>清仓中和停售不计入在营记录；返场再断货保留在分母中，仅从断货分子扣除。</small>' +
      '</aside>' +
      '</footer>';
  }

  function normalizeStockoutRolePeriod(value) {
    return STOCKOUT_ROLE_PERIODS.indexOf(String(value || "")) >= 0 ? String(value) : "30d";
  }

  function stockoutRolePeriodLabel(period) {
    return String(period || "30d").replace("d", "天");
  }

  function stockoutRoleScopeKey() {
    return [state.data_date, state.country_category, state.store, state.keyword, stockoutRoleState.period].join("|");
  }

  function stockoutRolePanelShell() {
    if (!stockoutRoleState.open) return "";
    return '<section id="labelHubStockoutRolePanel" class="label-hub-stockout-role-panel" aria-label="断货前销售角色汇总">' +
      '<header><div><strong>断货前销售角色</strong><span>按当前断货中的店铺商品记录统计</span></div>' +
      '<div class="label-hub-stockout-role-periods" aria-label="角色周期">' + STOCKOUT_ROLE_PERIODS.map(function (period) {
        var active = period === stockoutRoleState.period;
        return '<button type="button" data-stockout-role-period="' + period + '" class="' + (active ? "active" : "") + '" aria-pressed="' + active + '">' + stockoutRolePeriodLabel(period) + '</button>';
      }).join("") + '</div></header><div data-stockout-role-content class="label-hub-stockout-role-content"><div class="label-hub-stockout-role-loading">正在加载角色分布…</div></div></section>';
  }

  function renderStockoutRolePanelContent() {
    var content = elements.labelHubCategoryDetail.querySelector("[data-stockout-role-content]");
    if (!content || !stockoutRoleState.payload) return;
    var payload = stockoutRoleState.payload;
    var total = Number((payload.scope || {}).business_unit_count || 0);
    var coverage = payload.coverage || {};
    var rows = (payload.roles || []).map(function (role) {
      var share = Math.max(0, Math.min(1, Number(role.share || 0)));
      return '<button type="button" class="label-hub-stockout-role-row" data-stockout-role-id="' + role.id + '">' +
        '<span><b>' + app.escapeHtml(role.label || STOCKOUT_ROLE_LABELS[String(role.id)] || String(role.id)) + '</b><small>' + formatPercent(share) + '</small></span>' +
        '<i><em style="width:' + (share * 100).toFixed(1) + '%"></em></i>' +
        '<strong>' + formatNumber(role.business_unit_count) + '<small> 条</small></strong></button>';
    }).join("");
    content.innerHTML = '<div class="label-hub-stockout-role-summary"><span>当前断货 <strong>' + formatNumber(total) + '</strong> 条</span><span>角色覆盖 <strong>' + formatPercent(coverage.rate || 0) + '</strong></span><span>未识别 <strong>' + formatNumber(coverage.missing_count || 0) + '</strong></span><span>冲突 <strong>' + formatNumber(coverage.conflict_count || 0) + '</strong></span></div>' +
      '<div class="label-hub-stockout-role-list">' + rows + '</div>' +
      '<button type="button" class="label-hub-stockout-role-all" data-stockout-role-id="">查看全部断货明细 <span>→</span></button>';
  }

  function renderStockoutRolePanelError(error) {
    var content = elements.labelHubCategoryDetail.querySelector("[data-stockout-role-content]");
    if (!content) return;
    content.innerHTML = '<div class="label-hub-stockout-role-error">角色汇总暂不可用：' + app.escapeHtml((error && error.message) || "请稍后重试") + '<button type="button" data-stockout-role-period="' + stockoutRoleState.period + '">重试</button></div>';
  }

  function loadStockoutBeforeRoles() {
    if (!stockoutRoleState.open) return;
    var key = stockoutRoleScopeKey();
    if (stockoutRoleState.payload && stockoutRoleState.requestKey === key) {
      renderStockoutRolePanelContent();
      return;
    }
    var token = ++stockoutRoleState.requestToken;
    stockoutRoleState.requestKey = key;
    app.apiGet("/api/label-hub/stockout-before-roles", {
      data_date: state.data_date,
      role_period: stockoutRoleState.period,
      country_category: state.country_category,
      store: state.store,
      keyword: state.keyword
    }).then(function (payload) {
      if (token !== stockoutRoleState.requestToken || !stockoutRoleState.open) return;
      stockoutRoleState.payload = payload;
      renderStockoutRolePanelContent();
    }).catch(function (error) {
      if (token === stockoutRoleState.requestToken && stockoutRoleState.open) renderStockoutRolePanelError(error);
    });
  }

  function toggleStockoutRolePanel() {
    stockoutRoleState.open = !stockoutRoleState.open;
    if (stockoutRoleState.open && !stockoutRoleState.payload) stockoutRoleState.period = normalizeStockoutRolePeriod(state.metric_period);
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function closeStockoutRolePanel() {
    if (!stockoutRoleState.open) return;
    stockoutRoleState.open = false;
    stockoutRoleState.requestToken += 1;
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function selectStockoutRolePeriod(period) {
    stockoutRoleState.period = normalizeStockoutRolePeriod(period);
    stockoutRoleState.payload = null;
    stockoutRoleState.requestKey = "";
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function stockoutOperatingStatusScopeKey() {
    return [state.data_date, state.country_category, state.store, state.keyword, stockoutOperatingStatusState.period].join("|");
  }

  function stockoutOperatingStatusPanelShell() {
    if (!stockoutOperatingStatusState.open) return "";
    var rulesOpen = stockoutOperatingStatusState.rulesOpen;
    var rules = rulesOpen
      ? '<div id="labelHubStockoutOperatingStatusRules" class="label-hub-stockout-status-rules" data-stockout-operating-status-rules-panel role="note"><b>判断顺序（前项命中即停止）</b><ol><li>历史不可判：无对应周期角色，或缺少日销、周期起止；日销 = 0 且历史未覆盖完整周期。</li><li>低量补给待观察：历史可判断，且 FBA 在途 + 本地/采购补给 ≤ 5。</li><li>补给与动销不一致：历史完整、日销 = 0、补给总量 > 5。</li><li>明星 / 潜力 / 瘦狗：有销量、补给总量 > 5，沿用该周期断货前角色。</li><li>亏损问题：问题产品且毛利率 < 0；低毛利问题：问题产品且毛利率为 0%–5%。</li></ol></div>'
      : "";
    return '<section id="labelHubStockoutOperatingStatusPanel" class="label-hub-stockout-role-panel label-hub-stockout-status-panel" aria-label="断货经营状态汇总">' +
      '<header><div><strong>断货经营状态 <button type="button" class="label-hub-stockout-status-rules-trigger" data-stockout-operating-status-rules aria-expanded="' + rulesOpen + '" aria-controls="labelHubStockoutOperatingStatusRules" aria-label="查看断货经营状态判断条件">?</button></strong><span>结合断货前表现与当前补给证据，仅统计断货中产品</span></div>' +
      '<div class="label-hub-stockout-role-periods" aria-label="经营状态周期">' + STOCKOUT_ROLE_PERIODS.map(function (period) {
        var active = period === stockoutOperatingStatusState.period;
        return '<button type="button" data-stockout-operating-status-period="' + period + '" class="' + (active ? "active" : "") + '" aria-pressed="' + active + '">' + stockoutRolePeriodLabel(period) + '</button>';
      }).join("") + '</div></header>' + rules + '<div data-stockout-operating-status-content class="label-hub-stockout-role-content"><div class="label-hub-stockout-role-loading">正在加载经营状态分布…</div></div></section>';
  }

  function renderStockoutOperatingStatusPanelContent() {
    var content = elements.labelHubCategoryDetail.querySelector("[data-stockout-operating-status-content]");
    if (!content || !stockoutOperatingStatusState.payload) return;
    var payload = stockoutOperatingStatusState.payload;
    var total = Number((payload.scope || {}).business_unit_count || 0);
    var coverage = payload.coverage || {};
    var rows = (payload.statuses || []).map(function (status) {
      var share = Math.max(0, Math.min(1, Number(status.share || 0)));
      return '<div class="label-hub-stockout-role-row"><span><b>' + app.escapeHtml(status.label || status.code || "-") + '</b><small>' + formatPercent(share) + '</small></span><i><em style="width:' + (share * 100).toFixed(1) + '%"></em></i><strong>' + formatNumber(status.business_unit_count) + '<small> 条</small></strong></div>';
    }).join("");
    content.innerHTML = '<div class="label-hub-stockout-role-summary"><span>当前断货 <strong>' + formatNumber(total) + '</strong> 条</span><span>可评价 <strong>' + formatNumber(coverage.evaluable_count || 0) + '</strong> 条</span><span>不可直接评价 <strong>' + formatNumber(coverage.non_evaluable_count || 0) + '</strong> 条</span></div><div class="label-hub-stockout-role-list">' + rows + '</div><p class="label-hub-stockout-status-note">低量补给：当前 FBA 在途 + 本地/采购补给总量 ≤ ' + formatNumber((payload.supply || {}).low_supply_threshold || 5) + '。</p>';
  }

  function renderStockoutOperatingStatusPanelError(error) {
    var content = elements.labelHubCategoryDetail.querySelector("[data-stockout-operating-status-content]");
    if (!content) return;
    content.innerHTML = '<div class="label-hub-stockout-role-error">经营状态汇总暂不可用：' + app.escapeHtml((error && error.message) || "请稍后重试") + '<button type="button" data-stockout-operating-status-period="' + stockoutOperatingStatusState.period + '">重试</button></div>';
  }

  function loadStockoutOperatingStatus() {
    if (!stockoutOperatingStatusState.open) return;
    var key = stockoutOperatingStatusScopeKey();
    if (stockoutOperatingStatusState.payload && stockoutOperatingStatusState.requestKey === key) {
      renderStockoutOperatingStatusPanelContent();
      return;
    }
    var token = ++stockoutOperatingStatusState.requestToken;
    stockoutOperatingStatusState.requestKey = key;
    app.apiGet("/api/label-hub/stockout-operating-status", {
      data_date: state.data_date,
      role_period: stockoutOperatingStatusState.period,
      country_category: state.country_category,
      store: state.store,
      keyword: state.keyword
    }).then(function (payload) {
      if (token !== stockoutOperatingStatusState.requestToken || !stockoutOperatingStatusState.open) return;
      stockoutOperatingStatusState.payload = payload;
      renderStockoutOperatingStatusPanelContent();
    }).catch(function (error) {
      if (token === stockoutOperatingStatusState.requestToken && stockoutOperatingStatusState.open) renderStockoutOperatingStatusPanelError(error);
    });
  }

  function toggleStockoutOperatingStatusPanel() {
    stockoutOperatingStatusState.open = !stockoutOperatingStatusState.open;
    if (!stockoutOperatingStatusState.open) stockoutOperatingStatusState.rulesOpen = false;
    if (stockoutOperatingStatusState.open && !stockoutOperatingStatusState.payload) stockoutOperatingStatusState.period = normalizeStockoutRolePeriod(state.metric_period);
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function toggleStockoutOperatingStatusRules() {
    stockoutOperatingStatusState.rulesOpen = !stockoutOperatingStatusState.rulesOpen;
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function selectStockoutOperatingStatusPeriod(period) {
    stockoutOperatingStatusState.period = normalizeStockoutRolePeriod(period);
    stockoutOperatingStatusState.payload = null;
    stockoutOperatingStatusState.requestKey = "";
    if (lastPayload) renderCategoryDetail(lastPayload);
  }

  function openStockoutRoleDetails(roleId) {
    detailState.detail_view = "business_unit";
    detailState.identifiers = []; detailState.country_categories = []; detailState.stores = []; detailState.countries = [];
    detailState.detail_conditions = ""; detailState.sales_roles = []; detailState.role_reason_ids = [];
    detailState.daily_sales_bands = []; detailState.margin_bands = []; detailState.ranking_bands = []; detailState.problems = [];
    detailState.problem_mode = "any";
    detailState.current_stockout_only = true;
    detailState.stockout_before_role_period = stockoutRoleState.period;
    detailState.stockout_before_role_ids = roleId ? [Number(roleId)] : [];
    detailState.page = 1;
    populateControls();
    renderDetails();
    document.getElementById("labelHubDetailSection").scrollIntoView({ behavior: "smooth", block: "start" });
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
      var attributionCopy = item.id === 3 ? {
        "304": "返场期再次断货",
        "306": "返场期被判停售"
      }[String(child.id)] : "";
      var attributionCount = Number(scoped.return_stage_count || 0);
      var attribution = attributionCopy && attributionCount > 0
        ? '<button type="button" class="label-hub-return-attribution" data-return-attribution data-operation-child="' + child.id + '" title="查看当前运营状态中仍处于观察期、运营干预期或持续干预期的 MSKU"><span>' + app.escapeHtml(attributionCopy) + '</span><strong>' + formatNumber(attributionCount) + '</strong></button>'
        : "";
      var roleAction = Number(item.id) === 3 && Number(child.id) === 304
        ? '<div class="label-hub-stockout-role-actions"><button type="button" class="label-hub-stockout-role-toggle" data-stockout-role-toggle aria-expanded="' + stockoutRoleState.open + '" aria-controls="labelHubStockoutRolePanel"><span>查看断货前角色</span><i aria-hidden="true">' + (stockoutRoleState.open ? "收起" : "展开") + '</i></button><button type="button" class="label-hub-stockout-role-toggle" data-stockout-operating-status-toggle aria-expanded="' + stockoutOperatingStatusState.open + '" aria-controls="labelHubStockoutOperatingStatusPanel"><span>断货经营状态</span><i aria-hidden="true">' + (stockoutOperatingStatusState.open ? "收起" : "展开") + '</i></button></div>'
        : "";
      return '<article class="label-hub-child' + (checked ? " selected" : "") + '"><button type="button" class="label-hub-child-main" data-overview-child="' + child.id + '" data-parent-id="' + item.id + '" aria-pressed="' + checked + '" title="' + app.escapeHtml(child.rule || child.definition || child.label) + '"><span><b>' + app.escapeHtml(child.label) + '</b><small>' + formatPercent(scoped.share) + '</small></span><strong>' + formatNumber(scoped.count) + '<small> 条记录</small></strong></button>' + attribution + roleAction + '</article>';
    }).join("");
    var periods = (item.periods || []).join(" / ") || "无周期";
    var note = item.mutual_exclusion ? "同周期互斥" : "允许标签共现";
    elements.labelHubCategoryDetail.innerHTML = '<header><div><span class="section-kicker">当前分析标签</span><h3>' + app.escapeHtml(item.label) + '</h3></div><p>' + app.escapeHtml(periods) + " · " + app.escapeHtml(note) + '</p></header><div class="label-hub-children">' + children + "</div>" + stockoutRolePanelShell() + stockoutOperatingStatusPanelShell() + renderOperatingStockoutRate(payload, item);
    if (stockoutRoleState.open) loadStockoutBeforeRoles();
    if (stockoutOperatingStatusState.open) loadStockoutOperatingStatus();
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
      { key: "problem_role", label: "问题产品", local: false, tone: "warning" },
      { key: "zero_sales", label: "日销为 0", local: true, tone: "warning" },
      { key: "negative_profit", label: "订单毛利为负", local: true, tone: "danger" },
      { key: "missing_metrics", label: "暂无经营数据", local: true, tone: "" },
      { key: "conflict", label: "标签互斥冲突", local: false, tone: Number(counts.conflict || 0) ? "danger" : "" }
    ];
    var conditionText = conditionCount ? formatNumber(conditionCount) + " 个标签/联动条件" : "当前父标签全部店铺商品记录";
    var subjectHtml = '<div class="label-hub-diagnosis-subject"><span>当前分析对象</span><h3>' + app.escapeHtml(subject.parent_label || (payload.rules || {}).label || "当前标签") + '</h3><strong>' + formatNumber(total) + ' <small>条记录</small></strong><p>' + app.escapeHtml(conditionText) + ' · 指标覆盖 ' + formatPercent(coverageRate) + "</p></div>";
    var signalHtml = issues.map(function (item) {
      var available = !item.local || localAvailable;
      var count = Number(counts[item.key] || 0);
      var rate = total ? count / total : 0;
      var active = state.problem === item.key;
      return '<button type="button" class="label-hub-diagnosis-item ' + item.tone + (active ? " active" : "") + '"' + (available ? ' data-problem="' + item.key + '"' : " disabled") + ' aria-pressed="' + active + '"><span><b>' + app.escapeHtml(item.label) + '</b>' + (active ? '<em>已筛选</em>' : "") + '</span><strong>' + (available ? formatNumber(count) : "—") + '</strong><small>' + (available ? "占当前群体 " + formatPercent(rate) : "本地经营指标暂不可用") + "</small></button>";
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
        : "分析范围 " + formatNumber(panel.denominator) + " 条记录";
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
    elements.labelHubMatrix.innerHTML = '<div class="label-hub-matrix-legend"><span>记录数</span><small>低</small><i class="heat-level-1"></i><i class="heat-level-2"></i><i class="heat-level-3"></i><i class="heat-level-4"></i><small>高</small></div><div class="label-hub-matrix-table" style="grid-template-columns: 120px repeat(' + columns.length + ', minmax(96px, 1fr))"><div></div>' + columns.map(function (column) { return '<strong>' + app.escapeHtml(column.label) + "</strong>"; }).join("") + rows.map(function (row) { return '<strong>' + app.escapeHtml(row.label) + '</strong>' + columns.map(function (column) { var cell = cells[row.id + "|" + column.id] || { count: 0 }; return '<button type="button" class="heat-level-' + matrixHeatLevel(cell.count, maxCount) + '" data-matrix-row="' + row.id + '" data-matrix-col="' + column.id + '"><b>' + formatNumber(cell.count) + '</b><small>' + app.formatCompactCurrency(cell.sales_amount || 0) + "</small></button>"; }).join(""); }).join("") + "</div>";
  }

  function matrixHeatLevel(count, maxCount) {
    if (!count || !maxCount) return 0;
    var ratio = Number(count) / Number(maxCount);
    if (ratio <= 0.15) return 1;
    if (ratio <= 0.35) return 2;
    if (ratio <= 0.65) return 3;
    return 4;
  }

  function fallbackCopyText(value) {
    return new Promise(function (resolve, reject) {
      var textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        if (document.execCommand("copy")) resolve();
        else reject(new Error("copy command failed"));
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(textarea);
      }
    });
  }

  function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value).catch(function () {
        return fallbackCopyText(value);
      });
    }
    return fallbackCopyText(value);
  }

  function copyMsku(button, value) {
    if (!button || !value) return;
    var defaultLabel = "复制 MSKU " + value;
    copyText(value).then(function () {
      button.classList.add("is-success");
      button.setAttribute("aria-label", "MSKU " + value + " 已复制");
      button.title = "已复制";
    }).catch(function () {
      button.classList.add("is-error");
      button.setAttribute("aria-label", "MSKU " + value + " 复制失败");
      button.title = "复制失败";
    }).then(function () {
      window.setTimeout(function () {
        button.setAttribute("aria-label", defaultLabel);
        button.title = "复制 MSKU";
        button.classList.remove("is-success", "is-error");
      }, 1200);
    });
  }

  function renderMskuCell(params) {
    var value = String(params.value || "");
    return '<span class="label-hub-msku-cell"><span class="label-hub-msku-value">' +
      app.escapeHtml(value || "--") +
      '</span><button type="button" class="label-hub-msku-copy" data-copy-msku="' +
      app.escapeHtml(value) + '" aria-label="复制 MSKU ' + app.escapeHtml(value) +
      '" title="复制 MSKU"><svg class="label-hub-copy-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">' +
      '<rect x="5" y="5" width="8" height="8" rx="1"></rect><path d="M3 10V3h7"></path></svg></button></span>';
  }

  function renderLabelSummaryCell(params) {
    var labels = (params.data && params.data.labels) || [];
    var parents = {};
    var children = {};
    labels.forEach(function (item) {
      parents[String(item.parent_id)] = true;
      children[String(item.id)] = true;
    });
    return '<button type="button" class="label-summary-compact label-hub-label-profile-button" data-label-profile aria-label="查看标签画像"><b>' +
      Object.keys(parents).length + ' 个分类</b><small>' +
      Object.keys(children).length + ' 个标签 · 点击查看</small></button>';
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
    elements.labelHubRuleDrawerContent.innerHTML = '<div class="label-hub-rule-summary"><span>' + app.escapeHtml(stateLabel) + '</span><span>' + formatNumber(children.length) + ' 个子标签</span><span>' + app.escapeHtml(allPeriods.join(" / ") || "无周期配置") + '</span><span>' + app.escapeHtml(category.mutual_exclusion ? "同周期互斥" : "允许共现") + '</span></div><div class="label-hub-rule-table-head"><span>子标签</span><span>核心划分规则</span><span>周期</span><span>状态</span><span>操作</span></div><div class="label-hub-rule-detail-list">' + (ruleCards || '<div class="empty-state compact">该分类暂未配置子标签规则。</div>') + '</div>';
    elements.labelHubRuleDrawer.hidden = false;
    elements.labelHubRuleDrawerClose.focus();
  }

  function closeRuleDrawer() { elements.labelHubRuleDrawer.hidden = true; }

  function openStockoutBeforeEvidence(row) {
    if (!row || !row.stockout_before_role_id || !row.stockout_before_role_period) return;
    stockoutEvidenceState.row = row;
    stockoutEvidenceState.payload = null;
    stockoutEvidenceState.activeTab = "timeline";
    var token = ++stockoutEvidenceState.requestToken;
    elements.labelHubStockoutEvidenceContent.innerHTML = '<div class="label-hub-stockout-evidence-loading"><strong>正在读取断货前销售角色依据</strong><span>' + app.escapeHtml(row.country_category || "") + ' · ' + app.escapeHtml(row.store || "") + ' · ' + app.escapeHtml(row.msku || "") + '</span></div>';
    elements.labelHubStockoutEvidenceModal.hidden = false;
    document.body.classList.add("has-label-hub-stockout-evidence-modal");
    elements.labelHubStockoutEvidenceClose.focus();
    app.apiGet("/api/label-hub/stockout-before-role-evidence", {
      data_date: state.data_date,
      country_category: row.country_category,
      store: row.store,
      msku: row.msku,
      role_period: row.stockout_before_role_period,
      country: detailState.detail_view === "country" ? (row.country || "") : ""
    }).then(function (payload) {
      if (token !== stockoutEvidenceState.requestToken) return;
      stockoutEvidenceState.payload = payload || {};
      renderStockoutEvidenceModal(stockoutEvidenceState.payload);
    }).catch(function (error) {
      if (token !== stockoutEvidenceState.requestToken) return;
      elements.labelHubStockoutEvidenceContent.innerHTML = '<div class="label-hub-stockout-evidence-error"><strong>依据读取失败</strong><p>' + app.escapeHtml(error && error.message ? error.message : "请稍后重试") + '</p><button type="button" class="ghost-button" data-stockout-evidence-close>关闭</button></div>';
    });
  }

  function closeStockoutBeforeEvidence() {
    if (!elements.labelHubStockoutEvidenceModal || elements.labelHubStockoutEvidenceModal.hidden) return;
    stockoutEvidenceState.requestToken += 1;
    stockoutEvidenceState.row = null;
    stockoutEvidenceState.payload = null;
    elements.labelHubStockoutEvidenceModal.hidden = true;
    document.body.classList.remove("has-label-hub-stockout-evidence-modal");
  }

  function renderStockoutEvidenceModal(payload) {
    var identity = payload.identity || {};
    var role = payload.role || {};
    var evidence = payload.evidence || {};
    var isCountryScope = payload.scope === "country";
    var identityParts = isCountryScope
      ? [identity.country, identity.country_category, identity.store, identity.msku]
      : [identity.country_category, identity.store, identity.msku];
    var oos = evidence.oos || {};
    var startDate = oos.oos_start_date || "";
    var tabs = [
      ["timeline", "断货时间线"],
      ["performance", "断货前表现"],
      ["role", "角色判定"],
      ["calculation", "计算与来源"],
      ["raw", "原始 JSON"]
    ];
    elements.labelHubStockoutEvidenceContent.innerHTML = [
      '<header class="label-hub-stockout-evidence-head">',
      '<div><h2 id="labelHubStockoutEvidenceTitle">' + (isCountryScope ? '断货前销售角色依据（站点）' : '断货前销售角色依据') + '</h2><p>' + identityParts.map(function (value) { return app.escapeHtml(value || "-"); }).join(' · ') + '</p></div>',
      '<div class="label-hub-stockout-evidence-badges"><span class="is-role">' + app.escapeHtml(role.label || "暂无角色") + '</span><span>' + app.escapeHtml(role.period ? role.period.replace("d", "天") : "暂无周期") + '</span></div>',
      '</header>',
      '<div class="label-hub-stockout-evidence-summary">',
      evidenceSummaryItem("开始断货", startDate || "暂无"),
      evidenceSummaryItem("已断货", evidenceStockoutDays(startDate, identity.data_date)),
      '</div>',
      '<nav class="label-hub-stockout-evidence-tabs" aria-label="依据详情页签">',
      tabs.map(function (tab) {
        var active = stockoutEvidenceState.activeTab === tab[0];
        return '<button type="button" class="' + (active ? "active" : "") + '" data-stockout-evidence-tab="' + tab[0] + '" aria-selected="' + String(active) + '">' + tab[1] + '</button>';
      }).join(""),
      '</nav>',
      '<div class="label-hub-stockout-evidence-body">' + renderStockoutEvidenceTab(stockoutEvidenceState.activeTab, payload) + '</div>',
      '<footer class="label-hub-stockout-evidence-foot"><p>数据来自断货标签 evidence_json · 规则版本 ' + app.escapeHtml(evidence.rule_version || "暂无") + ' · schema ' + app.escapeHtml(evidence.schema_version || "暂无") + '</p><div><button type="button" class="ghost-button" data-stockout-evidence-close>关闭</button><button type="button" class="primary-button" data-stockout-evidence-tab="calculation">查看完整计算依据</button></div></footer>'
    ].join("");
  }

  function renderStockoutEvidenceTab(tab, payload) {
    var evidence = payload.evidence || {};
    var oos = evidence.oos || {};
    var metrics = evidence.metrics || {};
    var identity = payload.identity || {};
    if (tab === "performance") {
      return '<section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-section-head"><div><span>断货前表现</span><h3>' + app.escapeHtml((evidence.window || {}).period || (payload.role || {}).period || "观察窗口") + '经营快照</h3></div><p>' + app.escapeHtml(evidenceDateRange(evidence.window || {})) + '</p></div><div class="label-hub-stockout-evidence-kpis">' + [
        evidenceMetric("日均销量", evidenceNumber(metrics.daily_sales, 2)),
        evidenceMetric("周期销量", evidenceNumber(metrics.period_sales_qty, 0)),
        evidenceMetric("销售额", evidenceAmount(metrics.sales_amount)),
        evidenceMetric("标签毛利", evidenceAmount(metrics.tag_gross_profit)),
        evidenceMetric("标签毛利率", evidencePercent(metrics.tag_margin_rate)),
        evidenceMetric("观察天数", evidenceWindowDays(evidence.window || {}))
      ].join("") + '</div></section>';
    }
    if (tab === "role") {
      var matchedRule = evidence.matched_rule && typeof evidence.matched_rule === "object" ? evidence.matched_rule : {};
      return '<section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-role-result"><span>断货前销售角色</span><strong>' + app.escapeHtml((payload.role || {}).label || matchedRule.sales_role || "暂无") + '</strong><em>标签 ' + app.escapeHtml(String((payload.role || {}).id || "-")) + ' · ' + app.escapeHtml((payload.role || {}).period || "-") + '</em></div><div class="label-hub-stockout-evidence-pairs">' + evidenceObjectRows(matchedRule, {
        sales_role: "规则角色", daily_sales: "规则记录日均销量", tag_margin_rate: "规则记录毛利率"
      }) + '</div></section>';
    }
    if (tab === "calculation") {
      return '<div class="label-hub-stockout-evidence-source-grid"><section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-section-head"><div><span>计算信息</span><h3>标签如何生成</h3></div></div><div class="label-hub-stockout-evidence-pairs">' + evidenceObjectRows(evidence.calculation || {}, {
        mode: "计算方式", status: "计算状态", first_calculated_data_date: "首次计算日期", source_role_data_date: "沿用角色日期"
      }) + '</div></section><section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-section-head"><div><span>库存与来源</span><h3>断货时点状态</h3></div></div><div class="label-hub-stockout-evidence-pairs">' + evidenceObjectRows(oos, {
        inventory_source_fba: "FBA库存来源", current_fba_available: "当前FBA可售", current_fba_in_transit: "当前FBA在途", inventory_source_local: "本地库存来源", current_local_quantity: "当前本地库存", current_operation_status: "当前运营状态", current_status_data_date: "状态数据日期"
      }, ["inventory_source_fba", "current_fba_available", "current_fba_in_transit", "inventory_source_local", "current_local_quantity", "current_operation_status", "current_status_data_date"]) + '</div></section>' + (evidence.source_sales_role ? '<section class="label-hub-stockout-evidence-section is-wide"><div class="label-hub-stockout-evidence-section-head"><div><span>沿用来源</span><h3>前一日销售角色</h3></div></div><div class="label-hub-stockout-evidence-pairs">' + evidenceObjectRows(evidence.source_sales_role, { data_date: "数据日期", label_period: "标签周期", sub_label_id: "标签ID", sub_label_name: "标签名称" }) + '</div></section>' : "") + '</div>';
    }
    if (tab === "raw") {
      return '<section class="label-hub-stockout-evidence-section is-raw"><div class="label-hub-stockout-evidence-section-head"><div><span>审计数据</span><h3>原始 evidence_json</h3></div><p>仅用于核对字段与追溯计算</p></div><pre>' + app.escapeHtml(JSON.stringify(evidence, null, 2)) + '</pre></section>';
    }
    var timelineItems = [
      [oos.oos_start_date || "暂无", "断货开始", ""],
      [evidenceStockoutDays(oos.oos_start_date, identity.data_date), "已断货", identity.data_date ? "截至 " + identity.data_date : ""]
    ];
    return '<div class="label-hub-stockout-evidence-timeline-layout"><section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-section-head"><div><span>断货状态</span><h3>断货日期与累计天数</h3></div></div><ol class="label-hub-stockout-evidence-timeline">' + timelineItems.map(function (item, index) {
      return '<li class="' + (index === timelineItems.length - 1 ? "is-current" : "") + '"><time>' + app.escapeHtml(item[0]) + '</time><div><strong>' + app.escapeHtml(item[1]) + '</strong><p>' + app.escapeHtml(item[2] || "") + '</p></div></li>';
    }).join("") + '</ol></section><section class="label-hub-stockout-evidence-section"><div class="label-hub-stockout-evidence-section-head"><div><span>断货前表现</span><h3>' + app.escapeHtml((evidence.window || {}).period || (payload.role || {}).period || "观察窗口") + '核心指标</h3></div></div><div class="label-hub-stockout-evidence-kpis is-compact">' + [
      evidenceMetric("日均销量", evidenceNumber(metrics.daily_sales, 2)), evidenceMetric("周期销量", evidenceNumber(metrics.period_sales_qty, 0)), evidenceMetric("销售额", evidenceAmount(metrics.sales_amount)), evidenceMetric("标签毛利", evidenceAmount(metrics.tag_gross_profit)), evidenceMetric("标签毛利率", evidencePercent(metrics.tag_margin_rate))
    ].join("") + '</div><div class="label-hub-stockout-evidence-role-result is-compact"><span>角色判定</span><strong>' + app.escapeHtml((payload.role || {}).label || "暂无") + '</strong><em>' + app.escapeHtml(evidence.matched_rule ? "已保存规则命中依据" : "暂无规则命中字段") + '</em></div></section></div>';
  }

  function evidenceSummaryItem(label, value) {
    return '<div><span>' + app.escapeHtml(label) + '</span><strong>' + app.escapeHtml(value) + '</strong></div>';
  }

  function evidenceMetric(label, value) {
    return '<div><span>' + app.escapeHtml(label) + '</span><strong>' + app.escapeHtml(value) + '</strong></div>';
  }

  function evidenceValue(value) {
    return value === null || value === undefined || value === "" ? "暂无" : String(value);
  }

  function evidenceNumber(value, digits) {
    if (value === null || value === undefined || value === "") return "暂无";
    var number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString("zh-CN", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 }) : evidenceValue(value);
  }

  function evidenceAmount(value) {
    var formatted = evidenceNumber(value, 2);
    return formatted === "暂无" ? formatted : "¥" + formatted;
  }

  function evidencePercent(value) {
    if (value === null || value === undefined || value === "") return "暂无";
    var number = Number(value);
    if (!Number.isFinite(number)) return evidenceValue(value);
    if (Math.abs(number) <= 1) number *= 100;
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) + "%";
  }

  function evidenceStockoutDays(startDate, endDate) {
    var start = new Date(startDate || "");
    var end = new Date(endDate || "");
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "暂无";
    return Math.max(1, Math.floor((end.getTime() - start.getTime()) / 86400000) + 1) + "天";
  }

  function evidenceCalculationMode(mode) {
    return ({ historical_backtrack: "历史回溯", copy_previous_day_sales_role: "沿用前一日角色" })[mode] || evidenceValue(mode);
  }

  function evidenceOosMethod(method) {
    return ({ daily_status_transition: "根据每日库存状态变化识别", historical_backtrack: "根据历史库存回溯识别" })[method] || evidenceValue(method);
  }

  function evidenceDateRange(windowData) {
    var range = [windowData.start, windowData.end].filter(Boolean).join(" 至 ");
    return range || "暂无观察窗口日期";
  }

  function evidenceWindowDays(windowData) {
    return windowData.days === null || windowData.days === undefined || windowData.days === "" ? "暂无" : evidenceValue(windowData.days) + "天";
  }

  function evidenceObjectRows(source, labels, fields) {
    source = source && typeof source === "object" ? source : {};
    var keys = fields || Object.keys(source);
    var rows = keys.filter(function (key) {
      return Object.prototype.hasOwnProperty.call(source, key) && source[key] !== null && source[key] !== "";
    }).map(function (key) {
      var value = source[key];
      if (key === "mode") value = evidenceCalculationMode(value);
      if (key.indexOf("margin_rate") >= 0) value = evidencePercent(value);
      if (typeof value === "object") value = JSON.stringify(value);
      return '<div><span>' + app.escapeHtml(labels[key] || key) + '</span><strong>' + app.escapeHtml(evidenceValue(value)) + '</strong></div>';
    });
    return rows.length ? rows.join("") : '<p class="label-hub-stockout-evidence-empty">暂无对应字段</p>';
  }

  function renderTable(payload) {
    var counts = payload.counts || {};
    elements.labelHubTableSummary.textContent = "MSKU维度 " + formatNumber(counts.business_unit_count) + " · 国家明细 " + formatNumber(counts.country_unit_count) + " · 去重 MSKU " + formatNumber(counts.unique_msku_count) + " · 第 " + payload.page + " / " + payload.total_pages + " 页";
    window.kanbanGrid.makeGrid("labelHubTable", {
      rowData: payload.rows || [],
      domLayout: "normal",
      rowHeight: 52,
      headerHeight: 50,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前联动条件下没有 MSKU。</span>',
      columnDefs: tableColumns(state.table_view),
      onSortChanged: function (event) {
        var sorted = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
        if (!sorted || (detailState.sort_field === sorted.colId && detailState.sort_dir === sorted.sort)) return;
        detailState.sort_field = sorted.colId;
        detailState.sort_dir = sorted.sort;
        detailState.page = 1;
        renderDetails();
      },
      onCellClicked: function (event) {
        var target = event.event && event.event.target;
        var copyButton = target && target.closest("[data-copy-msku]");
        if (copyButton) {
          copyMsku(copyButton, copyButton.dataset.copyMsku || (event.data && event.data.msku) || "");
          if (event.event && event.event.detail > 0) copyButton.blur();
          return;
        }
        if (!event.data || !event.colDef) return;
        if (event.colDef.field === "stockout_before_evidence") openStockoutBeforeEvidence(event.data);
        if (event.colDef.field === "label_summary") openDrawer(event.data);
        if (event.colDef.field === "role_diagnostic_summary") openRoleDiagnosticDrawer(event.data);
        if (event.colDef.field === "country_profile") openCountryProfileDrawer(event.data);
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
    if (detailState.detail_view === "country") return countryIdentityColumns();
    return [
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 110 },
      { headerName: "店铺", field: "store", pinned: "left", width: 125 },
      { headerName: "MSKU", field: "msku", pinned: "left", width: 155, cellRenderer: renderMskuCell }
    ];
  }

  function countryIdentityColumns() {
    return [
      { headerName: "国家", field: "country", pinned: "left", width: 105, sort: detailState.sort_field === "country" ? detailState.sort_dir : null },
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 110, sort: detailState.sort_field === "country_category" ? detailState.sort_dir : null },
      { headerName: "店铺", field: "store", pinned: "left", width: 125, sort: detailState.sort_field === "store" ? detailState.sort_dir : null },
      { headerName: "MSKU", field: "msku", pinned: "left", width: 145, sort: detailState.sort_field === "msku" ? detailState.sort_dir : null, cellRenderer: renderMskuCell },
      { headerName: "SKU", field: "sku", pinned: "left", width: 135, sort: detailState.sort_field === "sku" ? detailState.sort_dir : null, cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value || "--", true); } },
      { headerName: "排名", field: "ranking", width: 92, sort: detailState.sort_field === "ranking" ? detailState.sort_dir : null, valueFormatter: function (params) { return params.value === null || params.value === undefined || Number(params.value) <= 0 ? "暂无" : window.kanbanGrid.number(params.value, 0); } }
    ];
  }

  function currentLabelColumn() {
    return { headerName: "当前标签", field: "current_label", width: 150, tooltipField: "current_label", cellClass: "label-text-cell" };
  }

  function stockoutBeforeEvidenceColumn() {
    return {
      headerName: "断货前依据",
      field: "stockout_before_evidence",
      width: detailState.detail_view === "country" ? 184 : 124,
      sortable: false,
      filter: false,
      cellClass: "label-hub-stockout-evidence-cell",
      cellRenderer: function (params) {
        var row = params.data || {};
        if (!row.stockout_before_role_id || !row.stockout_before_role_period) {
          return '<span class="ag-empty-copy">暂无依据</span>';
        }
        if (row.stockout_before_role_scope === "country") {
          return '<div class="label-hub-stockout-country-evidence"><span class="label-hub-stockout-country-role">' + app.escapeHtml(row.stockout_before_role || "暂无角色") + '</span><button type="button" class="label-hub-stockout-evidence-button" data-stockout-evidence>查看明细</button></div>';
        }
        return '<button type="button" class="label-hub-stockout-evidence-button" data-stockout-evidence>查看明细</button>';
      }
    };
  }

  function roleDiagnosticColumn() {
    return {
      headerName: "角色诊断",
      field: "role_diagnostic_summary",
      width: 120,
      tooltipField: "role_diagnostic_summary",
      cellClass: "label-summary-cell",
      cellRenderer: function (params) {
        var value = params.value || "";
        return value
          ? '<button type="button" class="label-hub-role-diagnostic-cell"><span>查看诊断</span><i aria-hidden="true">›</i></button>'
          : '<span class="ag-empty-copy">暂无诊断</span>';
      }
    };
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
      stockoutBeforeEvidenceColumn(),
      roleDiagnosticColumn(),
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
    var countryLabels = detailState.detail_view === "country" ? [
      { headerName: "国家销售角色", field: "country_sales_role_label", width: 130 },
      { headerName: "站点状态", field: "site_status_label", width: 120 },
      { headerName: "定价标签", field: "price_label", width: 120 },
      { headerName: "国家生命周期", field: "site_lifecycle_label", width: 135 }
    ] : [];
    return identityColumns().concat([
      currentLabelColumn(),
      stockoutBeforeEvidenceColumn(),
      roleDiagnosticColumn(),
      labelProfileColumn(),
      countryProfileColumn(),
    ]).concat(countryLabels).concat([
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
    Array.from(elements.labelHubPagination.querySelectorAll("[data-page]")).forEach(function (button) { button.addEventListener("click", function () { if (!this.disabled) { detailState.page = Number(this.dataset.page); renderDetails(); } }); });
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
      var metricItems = [["销量", metric.sales_qty], ["日均销量", metric.daily_sales], ["销售额", metric.sales_amount, "currency"], ["未税销售额", metric.sales_amount_ex_tax, "currency"], ["订单毛利润", metric.order_gross_profit, "currency"], ["订单毛利率", metric.order_gross_margin, "percent"], ["结算毛利润", metric.settlement_gross_profit, "currency"], ["广告花费", metric.ad_spend, "currency"], ["广告销售额", metric.ad_sales, "currency"], ["ACOS", metric.acos, "percent"], ["TACOS", metric.tacos, "percent"], ["退货数量", metric.return_count], ["退货金额", metric.return_amount, "currency"], ["净销售额", metric.net_amount, "currency"], ["期末可售库存", metric.ending_inventory_qty]];
      var metricsHtml = metricItems.map(function (item) { var value = item[1]; if (value === null || value === undefined) value = "暂无数据"; else if (item[2] === "currency") value = app.formatCompactCurrency(value); else if (item[2] === "percent") value = app.formatPercent(value); else value = formatNumber(value); return '<div><span>' + item[0] + '</span><strong>' + value + "</strong></div>"; }).join("");
      var identity = profile.identity || {};
      var status = profile.data_status || {};
      var metricWindowText = metricWindowLabel(status.metric_window || {});
      var metricStatusText = status.has_local_metric
        ? "经营指标来自本地周期快照"
        : (status.local_metrics_status === "available" ? "该 MSKU 暂无本地经营指标" : (status.local_metrics_status === "no_snapshot" ? "当前日期无本地经营快照" : "本地经营指标暂不可用"));
      elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">MSKU 画像</p><h2 id="labelHubDrawerTitle">' + app.escapeHtml(identity.msku || row.msku) + '</h2><p>' + app.escapeHtml(identity.country_category || "") + " · " + app.escapeHtml(identity.store || "") + '</p></div><section><h3>MSKU 口径标签</h3><div class="label-hub-profile-tags">' + analysisTags + '</div></section><section><div class="label-hub-profile-section-head"><h3>本地经营画像</h3><span class="label-hub-profile-period">' + app.escapeHtml(metricWindowText) + '</span></div><p class="summary-hint">' + app.escapeHtml(metricStatusText) + '</p><div class="label-hub-profile-metrics">' + metricsHtml + '</div></section>';
    }).catch(function (error) { elements.labelHubDrawerContent.innerHTML = '<div class="empty-state compact">画像加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + "</div>"; });
  }

  function openRoleDiagnosticDrawer(row) {
    setDrawerMode("diagnostics");
    elements.labelHubDrawer.hidden = false;
    var supported = ["7d", "14d", "30d", "90d"];
    var linkedPeriod = supported.indexOf(state.label_period) >= 0
      ? state.label_period
      : (supported.indexOf(state.diagnostic_period) >= 0 ? state.diagnostic_period : "30d");
    roleDiagnosticState.row = row;
    roleDiagnosticState.period = linkedPeriod;
    roleDiagnosticState.payload = null;
    roleDiagnosticState.focusCountry = detailState.detail_view === "country"
      ? String(row.country || "").trim()
      : "";
    roleDiagnosticState.openCountry = null;
    loadRoleDiagnosticDrawer();
  }

  function loadRoleDiagnosticDrawer() {
    var row = roleDiagnosticState.row;
    if (!row) return;
    var token = ++roleDiagnosticState.requestToken;
    elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-role-diagnostic-loading"><span></span><strong>正在读取规则证据</strong><small>计算当前指标、目标阈值和升级差距…</small></div>';
    app.apiGet("/api/label-hub/msku-role-diagnostics", {
      data_date: state.data_date,
      country_category: row.country_category || state.country_category,
      store: row.store || state.store,
      msku: row.msku,
      diagnostic_period: roleDiagnosticState.period
    }).then(function (payload) {
      if (token !== roleDiagnosticState.requestToken) return;
      roleDiagnosticState.payload = payload;
      renderRoleDiagnosticDrawer(payload);
    }).catch(function (error) {
      if (token !== roleDiagnosticState.requestToken) return;
      elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-role-diagnostic-error"><strong>诊断加载失败</strong><p>' +
        app.escapeHtml((error && error.message) || "请稍后重试") +
        '</p><button type="button" data-role-diagnostic-period="' + app.escapeHtml(roleDiagnosticState.period) + '">重新加载</button></div>';
    });
  }

  function roleDiagnosticTone(role) {
    if (/问题/.test(role || "")) return "risk";
    if (/瘦狗/.test(role || "")) return "warning";
    if (/潜力/.test(role || "")) return "potential";
    if (/明星/.test(role || "")) return "success";
    return "neutral";
  }

  function roleDiagnosticMetricCard(metric) {
    var statusLabel = metric.status === "met" ? "已达标" : (metric.status === "missing" ? "待判断" : "未达标");
    return '<article class="label-hub-role-metric is-' + app.escapeHtml(metric.status || "missing") + '">' +
      '<div><span>' + app.escapeHtml(metric.label || "") + '</span><em>' + app.escapeHtml(statusLabel) + '</em></div>' +
      '<strong>' + app.escapeHtml(metric.current_display || "--") + '</strong>' +
      '<p>目标 <b>' + app.escapeHtml(metric.target_display || "--") + '</b></p>' +
      '<div class="label-hub-role-metric-progress"><i style="width:' + Number(metric.progress || 0) + '%"></i></div>' +
      '<small>' + app.escapeHtml(metric.gap_display || "") + '</small></article>';
  }

  function roleDiagnosticMetricTable(metrics) {
    var rows = (metrics || []).map(function (metric) {
      var statusLabel = metric.status === "met" ? "已达标" : (metric.status === "missing" ? "待判断" : "未达标");
      return '<tr class="is-' + app.escapeHtml(metric.status || "missing") + '"><td><span class="label-hub-role-status-dot"></span>' +
        app.escapeHtml(metric.label || "") + '</td><td>' + app.escapeHtml(metric.current_display || "--") +
        '</td><td>' + app.escapeHtml(metric.target_display || "--") + '</td><td><b>' +
        app.escapeHtml(metric.gap_display || statusLabel) + '</b></td></tr>';
    }).join("");
    return '<div class="label-hub-role-country-table"><table><thead><tr><th>指标</th><th>当前值</th><th>达标规则</th><th>还差多少</th></tr></thead><tbody>' +
      rows + '</tbody></table></div>';
  }

  function prioritizeRoleDiagnosticCountry(countries, focusCountry) {
    var items = (countries || []).slice();
    var normalizedFocus = String(focusCountry || "").trim();
    if (!normalizedFocus) return items;
    var focusIndex = items.findIndex(function (item) {
      return String((item || {}).country || "").trim() === normalizedFocus;
    });
    if (focusIndex <= 0) return items;
    return [items[focusIndex]].concat(items.slice(0, focusIndex), items.slice(focusIndex + 1));
  }

  function renderRoleDiagnosticDrawer(payload) {
    var identity = payload.identity || {};
    var globalDiagnostic = payload.global_diagnostic;
    var countries = prioritizeRoleDiagnosticCountry(
      payload.country_diagnostics,
      roleDiagnosticState.focusCountry
    );
    var focusCountryVisible = Boolean(roleDiagnosticState.focusCountry) && countries.some(function (item) {
      return String((item || {}).country || "").trim() === roleDiagnosticState.focusCountry;
    });
    if (roleDiagnosticState.openCountry === null && countries.length) {
      roleDiagnosticState.openCountry = focusCountryVisible
        ? roleDiagnosticState.focusCountry
        : (countries[0].country || "");
    }
    var periods = ["7d", "14d", "30d", "90d"].map(function (period) {
      return '<button type="button" data-role-diagnostic-period="' + period + '" class="' +
        (roleDiagnosticState.period === period ? "active" : "") + '">' + period + "</button>";
    }).join("");
    var header = '<header class="label-hub-role-diagnostic-head"><div><p class="section-kicker">销售角色诊断</p>' +
      '<h2 id="labelHubDrawerTitle">' + app.escapeHtml(identity.msku || (roleDiagnosticState.row || {}).msku || "--") +
      '</h2><p>' + app.escapeHtml([identity.country_category, identity.store].filter(Boolean).join(" · ")) +
      '</p></div><div class="label-hub-role-periods" aria-label="诊断周期">' + periods + '</div></header>';

    var globalHtml = '<section class="label-hub-role-global"><div class="label-hub-role-section-title"><div><span>全站判断</span><h3>全站点销售角色</h3></div><small>证据周期 ' +
      app.escapeHtml(payload.period || roleDiagnosticState.period) + '</small></div>';
    if (globalDiagnostic) {
      var globalTone = roleDiagnosticTone(globalDiagnostic.current_role);
      globalHtml += '<div class="label-hub-role-upgrade"><div><small>当前角色</small><strong class="is-' + globalTone + '">' +
        app.escapeHtml(globalDiagnostic.current_role || "--") + '</strong></div><i>→</i><div><small>上一层目标</small><strong>' +
        app.escapeHtml(globalDiagnostic.target_role || "--") + '</strong></div></div>' +
        '<div class="label-hub-role-blocker"><span>未达标指标</span><strong>' +
        app.escapeHtml(globalDiagnostic.main_blocker || "--") + '</strong><p>' +
        app.escapeHtml(globalDiagnostic.rule_branch_text || "") + '</p></div>' +
        '<div class="label-hub-role-metrics">' + (globalDiagnostic.metrics || []).map(roleDiagnosticMetricCard).join("") + '</div>';
    } else {
      globalHtml += '<div class="empty-state compact">当前周期没有全站销售角色证据。</div>';
    }
    globalHtml += "</section>";

    var countryRows = countries.map(function (item) {
      var expanded = roleDiagnosticState.openCountry === item.country;
      var tone = roleDiagnosticTone(item.current_role);
      var details = expanded
        ? '<div class="label-hub-role-country-detail"><div class="label-hub-role-country-rule"><span>本次命中问题</span><strong>' +
          app.escapeHtml(item.issue_label || "--") + '</strong><p>' + app.escapeHtml(item.rule_branch_text || "") +
          '</p></div>' + roleDiagnosticMetricTable(item.metrics) +
          (item.tag_rule ? '<details class="label-hub-role-rule-source"><summary>查看原始分类规则</summary><p>' + app.escapeHtml(item.tag_rule) + '</p></details>' : "") +
          '</div>'
        : "";
      return '<article class="label-hub-role-country is-' + tone + (expanded ? " is-open" : "") + '">' +
        '<button type="button" data-role-diagnostic-country="' + app.escapeHtml(item.country || "") + '" aria-expanded="' + expanded + '">' +
        '<span class="label-hub-role-country-chevron">›</span><span class="label-hub-role-country-name"><b>' +
        app.escapeHtml(item.country || "未配置国家") + '</b><small>' + app.escapeHtml(item.issue_label || "") + '</small></span>' +
        '<span class="label-hub-role-country-path"><em class="is-' + tone + '">' + app.escapeHtml(item.current_role || "--") +
        '</em><i>→</i><em>' + app.escapeHtml(item.target_role || "--") + '</em></span>' +
        '<span class="label-hub-role-country-gap"><small>' + Number(item.unmet_count || 0) + ' 项待提升</small><b>' +
        app.escapeHtml(item.summary || "当前指标均已达标") + '</b></span></button>' + details + '</article>';
    }).join("");
    var countryOrderCopy = focusCountryVisible
      ? "当前国家优先 · 其余按问题优先级"
      : "按问题优先级排列";
    var countryHtml = '<section class="label-hub-role-countries"><div class="label-hub-role-section-title"><div><span>国家站点判断</span>' +
      '<h3>各国家子标签与问题情况</h3></div><small>' + countryOrderCopy + ' · ' + countries.length +
      ' 个国家</small></div><div class="label-hub-role-country-list">' +
      (countryRows || '<div class="empty-state compact">当前周期没有国家站点角色证据。</div>') + '</div></section>';

    elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-role-diagnostic">' + header + globalHtml + countryHtml +
      '<footer>判断来自标签证据 JSON；切换周期只读取对应周期证据，不改变页面筛选和分类规则。</footer></div>';
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

  function prioritizeCountryProfileCountries(countries, currentCountry) {
    var rows = (countries || []).slice();
    var target = String(currentCountry || "");
    if (!target) return rows;
    return rows.filter(function (item) { return String(item.country || "") === target; })
      .concat(rows.filter(function (item) { return String(item.country || "") !== target; }));
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
    var countries = prioritizeCountryProfileCountries(profile.countries || [], row.country);
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
      var currentClass = row.country && String(item.country || "") === String(row.country) ? " is-current-country" : "";
      var completeness = item.data_status === "complete" ? "标签完整" : "标签部分缺失";
      if (scope.listing_price_status === "unavailable") completeness += " · 价格服务不可用";
      else if (!item.price || !item.price.available) completeness += " · 缺少价格";
      if ((item.conflict_parent_ids || []).length) completeness += " · 存在冲突";
      return '<tr class="label-hub-country-profile-row' + currentClass + '"><td class="label-hub-country-identity">' + countryProfileCountryCell(item) + '</td><td class="label-hub-country-profile-price-cell">' + countryProfilePriceCell(item.price, scope.listing_price_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileRankCell(item.metrics, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileMetricsCell(item.metrics, scope.metric_period, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileTrafficCell(item.metrics, scope.local_metrics_status) + '</td><td class="label-hub-country-profile-metrics-cell">' + countryProfileLimitPriceCell(item.limit_prices, item.price, scope.limit_price_status) + '</td><td class="label-hub-country-profile-tag-cell">' + countryProfileCountryTagsCell(item) + '</td><td class="label-hub-country-profile-role-cell">' + countryProfileSalesRolesCell(salesRoles) + '</td></tr>';
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
    return '<article class="label-hub-trace-day"><header><span>' + app.escapeHtml(title) + '</span><strong>' + app.escapeHtml(day.data_date || "--") + '</strong><small>' + formatNumber(units.length) + ' 条记录</small></header><div>' + (units.map(function (unit) {
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
    elements.labelHubDrawerContent.innerHTML = '<div class="label-hub-drawer-head"><p class="section-kicker">标签变化追溯</p><h2 id="labelHubDrawerTitle">' + app.escapeHtml(msku) + '</h2><p>按去重 MSKU 汇总，店铺商品记录保留完整追溯</p></div><section id="labelHubDrawerChange" class="label-hub-drawer-change"><div class="empty-state compact">正在加载两日标签与规则证据…</div></section>';
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

  function openFullChangeDetailsDrawer() {
    activeLayerChangeContext = null;
    setDrawerMode("changes");
    elements.labelHubDrawer.hidden = false;
    elements.labelHubDrawerContent.innerHTML = '<div class="empty-state">正在加载完整变化明细…</div>';
    app.apiGet("/api/label-hub/changes", buildChangeParams(), CHANGE_REQUEST_OPTIONS).then(function (payload) {
      lastChanges = payload;
      if (!payload || !payload.available) {
        elements.labelHubDrawerContent.innerHTML = '<div class="empty-state">当前暂无可比较的标签变化。</div>';
        return;
      }
      openChangeDetailsDrawer();
    }).catch(function (error) {
      elements.labelHubDrawerContent.innerHTML = '<div class="empty-state">变化明细加载失败：' + app.escapeHtml((error && error.message) || "请稍后重试") + '</div>';
    });
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
    if (context.transition_parent !== undefined) params.layer_transition_parent = context.transition_parent;
    if (context.transition_previous) params.layer_transition_previous = context.transition_previous;
    if (context.transition_current) params.layer_transition_current = context.transition_current;
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
    if (context.source === "problem") {
      params.problem = context.bucket || "all";
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
      transition_parent: 0,
      transition_previous: "",
      transition_current: "",
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
    app.apiGet("/api/label-hub/changes", buildLayerChangeParams(context), CHANGE_REQUEST_OPTIONS).then(function (payload) {
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
