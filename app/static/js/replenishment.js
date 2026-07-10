(function () {
  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var LEVEL_ALL = "\u5168\u90e8";
  var LEVEL_URGENT = "\u7d27\u6025\u8865\u8d27";
  var LEVEL_SUGGESTED = "\u5efa\u8bae\u8865\u8d27";
  var LEVEL_PLANNED = "\u8ba1\u5212\u8865\u8d27";
  var LEVEL_SUFFICIENT = "\u5e93\u5b58\u5145\u8db3";
  var LEVEL_ZERO_SALES = "\u65e5\u9500\u4e3a0";
  var LEVEL_HISTORY_RECOVERY = "\u5386\u53f2\u515c\u5e95";
  var CATEGORY_MIX_ORDER = [
    "\u95ee\u9898\u4ea7\u54c1",
    "\u7626\u72d7\u4ea7\u54c1",
    "\u6f5c\u529b\u4ea7\u54c1",
    "\u660e\u661f\u4ea7\u54c1"
  ];
  var LEVEL_HELP = {};
  LEVEL_HELP[LEVEL_URGENT] = [
    "\u5224\u5b9a\uff1a\u5e93\u5b58\u652f\u6491\u5929\u6570 <= 35 \u5929\u3002",
    "\u652f\u6491\u5929\u6570 = (\u53ef\u7528\u5e93\u5b58 + \u5728\u9014\u5e93\u5b58 + \u672c\u5730\u5e93\u5b58 + \u91c7\u8d2d\u8ba1\u5212\u6570) / \u65e5\u9500\u3002",
    "\u8865\u8d27\u6570\u91cf\u6309\u9700\u6c42\u91cf\u7ed3\u5408\u91c7\u8d2d\u7bb1\u89c4\u53d6\u6574\uff0c\u8865\u8d27\u8d27\u503c = \u8865\u8d27\u6570\u91cf * (\u91c7\u8d2d\u5355\u4ef7 + \u5934\u7a0b\u8fd0\u8d39)\u3002",
    "\u4ea7\u54c1\u5206\u7c7b\u5360\u6bd4 = \u8be5\u5206\u5c42\u5185\u5bf9\u5e94\u5206\u7c7b MSKU \u6570 / \u8be5\u5206\u5c42 MSKU \u603b\u6570\u3002"
  ];
  LEVEL_HELP[LEVEL_SUGGESTED] = [
    "\u5224\u5b9a\uff1a35 \u5929 < \u5e93\u5b58\u652f\u6491\u5929\u6570 <= 65 \u5929\u3002",
    "\u652f\u6491\u5929\u6570 = (\u53ef\u7528\u5e93\u5b58 + \u5728\u9014\u5e93\u5b58 + \u672c\u5730\u5e93\u5b58 + \u91c7\u8d2d\u8ba1\u5212\u6570) / \u65e5\u9500\u3002",
    "\u8865\u8d27\u6570\u91cf\u6309\u9700\u6c42\u91cf\u7ed3\u5408\u91c7\u8d2d\u7bb1\u89c4\u53d6\u6574\uff0c\u8865\u8d27\u8d27\u503c = \u8865\u8d27\u6570\u91cf * (\u91c7\u8d2d\u5355\u4ef7 + \u5934\u7a0b\u8fd0\u8d39)\u3002",
    "\u4ea7\u54c1\u5206\u7c7b\u5360\u6bd4 = \u8be5\u5206\u5c42\u5185\u5bf9\u5e94\u5206\u7c7b MSKU \u6570 / \u8be5\u5206\u5c42 MSKU \u603b\u6570\u3002"
  ];
  LEVEL_HELP[LEVEL_PLANNED] = [
    "\u5224\u5b9a\uff1a65 \u5929 < \u5e93\u5b58\u652f\u6491\u5929\u6570 <= 90 \u5929\u3002",
    "\u652f\u6491\u5929\u6570 = (\u53ef\u7528\u5e93\u5b58 + \u5728\u9014\u5e93\u5b58 + \u672c\u5730\u5e93\u5b58 + \u91c7\u8d2d\u8ba1\u5212\u6570) / \u65e5\u9500\u3002",
    "\u8865\u8d27\u6570\u91cf\u6309\u9700\u6c42\u91cf\u7ed3\u5408\u91c7\u8d2d\u7bb1\u89c4\u53d6\u6574\uff0c\u8865\u8d27\u8d27\u503c = \u8865\u8d27\u6570\u91cf * (\u91c7\u8d2d\u5355\u4ef7 + \u5934\u7a0b\u8fd0\u8d39)\u3002",
    "\u4ea7\u54c1\u5206\u7c7b\u5360\u6bd4 = \u8be5\u5206\u5c42\u5185\u5bf9\u5e94\u5206\u7c7b MSKU \u6570 / \u8be5\u5206\u5c42 MSKU \u603b\u6570\u3002"
  ];
  LEVEL_HELP[LEVEL_SUFFICIENT] = [
    "判断：原始补货分层不在紧急/建议/计划补货三层，且未触发日销为0或历史兜底。",
    "通常表示库存支撑天数 > 90 天，当前不进入补货计算。",
    "补货数量按 0 展示。"
  ];
  LEVEL_HELP[LEVEL_ZERO_SALES] = [
    "判断：用于计算库存支撑天数的日销 <= 0。",
    "日销为0时无法计算有效库存支撑天数，当前不进入补货计算。",
    "后续销量恢复后，会重新按库存支撑天数进入对应分层。"
  ];
  LEVEL_HELP[LEVEL_HISTORY_RECOVERY] = [
    "判断：正常补货需求数量 < 补货触发数量，且近30天可售天数 < 15，且近90天有货天数 >= 15，且近90天有货日销 > 1.5。",
    "同时要求：历史恢复需求数量 > 补货触发数量，才会进入历史兜底。",
    "白话解释：近30天可售天数太少，可能是缺货、断货或短期销量过低，直接按当前日销判断容易漏补。",
    "所以会参考近90天有货时的日销，如果历史有货表现能支撑一箱/50个以上的恢复需求，就单独放到历史兜底。",
    "用途：补充识别短期日销偏低或日销为0但历史销售能力还在的 SKU，不改变库存支撑分层结果。",
    "补货数量按恢复一箱展示：有采购箱规取一箱数量，无箱规按 50 个；补货货值 = 补货数量 * (采购单价 + 头程运费)。",
    "该层不计入需要补货 MSKU 三层合计，但补货数量和补货货值汇总会包含这批恢复数量。"
  ];
  var FLOW_HELP = [
    "\u6d41\u8f6c\u6307\u6807\u53e3\u5f84\uff1a\u6309\u5f53\u524d\u8865\u8d27\u65e5\u671f\u4e0e\u4e0a\u4e00\u4e2a\u5df2\u751f\u6210\u8865\u8d27\u7ed3\u679c\u65e5\u671f\u5bf9\u6bd4\u3002",
    "\u8f83\u4e0a\u671f = \u4eca\u5929\u8be5\u5c42 MSKU \u6570 - \u4e0a\u671f\u8be5\u5c42 MSKU \u6570\u3002",
    "\u6d41\u5165 = \u4e0a\u671f\u5728\u5176\u4ed6\u5c42\u7ea7\u6216\u65e0\u8bb0\u5f55\uff0c\u4eca\u5929\u8fdb\u5165\u8be5\u5c42\u7684 MSKU\u3002",
    "\u6d41\u51fa = \u4e0a\u671f\u5728\u8be5\u5c42\uff0c\u4eca\u5929\u8f6c\u5230\u5176\u4ed6\u5c42\u6216\u65e0\u8bb0\u5f55\u7684 MSKU\u3002",
    "\u9000\u51fa = \u4e0a\u671f\u5728\u7d27\u6025/\u5efa\u8bae/\u8ba1\u5212\u8865\u8d27\u4e09\u5c42\uff0c\u4eca\u5929\u8f6c\u5230\u5e93\u5b58\u5145\u8db3\u6216\u65e5\u9500\u4e3a0\u7684 MSKU\u3002",
    "\u65b0\u589e = \u4e0a\u671f\u5728\u5e93\u5b58\u5145\u8db3\u6216\u65e5\u9500\u4e3a0\uff0c\u4eca\u5929\u8fdb\u5165\u7d27\u6025/\u5efa\u8bae/\u8ba1\u5212\u8865\u8d27\u4e09\u5c42\u7684 MSKU\u3002"
  ];
  var DAILY_SALES_HELP = [
    "\u65e5\u9500\u53e3\u5f84\uff1a\u65b0\u54c1 = 3\u5929\u65e5\u9500 * 0.5 + 7\u5929\u65e5\u9500 * 0.5\uff1b\u8001\u54c1 = 7\u5929\u65e5\u9500 * 0.6 + 14\u5929\u65e5\u9500 * 0.2 + 30\u5929\u65e5\u9500 * 0.2\u3002",
    "\u5468\u671f\u65e5\u9500 = \u5468\u671f\u9500\u91cf / \u5468\u671f\u53ef\u552e\u5929\u6570\uff1b\u5f53\u53ef\u552e\u5929\u6570\u4e0d\u8db3\u65f6\uff0c\u4f1a\u7ed3\u540830\u5929\u65e5\u9500\u505a\u5e73\u6ed1\uff0c\u907f\u514d\u77ed\u5468\u671f\u7f3a\u8d27\u5bfc\u81f4\u65e5\u9500\u88ab\u653e\u5927\u3002",
    "\u5386\u53f290\u5929\u6709\u8d27\u65e5\u9500\u53ea\u7528\u4e8e\u8865\u8d27\u6570\u91cf\u515c\u5e95\u6807\u8bb0\uff0c\u4e0d\u53c2\u4e0e\u5e93\u5b58\u652f\u6491\u5929\u6570\u548c\u5206\u5c42\u5224\u65ad\u3002"
  ];
  var text = {
    loading: "\u52a0\u8f7d\u4e2d...",
    loadFailed: "\u52a0\u8f7d\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8865\u8d27\u7ed3\u679c\u8868\u3002",
    noRows: "\u5f53\u524d\u7b5b\u9009\u65e0\u8865\u8d27 SKU\u3002",
    noResult: "\u6682\u65e0\u8865\u8d27\u7ed3\u679c",
    replenishDate: "\u8865\u8d27\u65e5\u671f ",
    allSites: "\u5168\u90e8\u7ad9\u70b9",
    allStores: "\u5168\u90e8\u5e97\u94fa",
    replenishSku: "\u9700\u8981\u8865\u8d27 MSKU",
    replenishValue: "\u8865\u8d27\u8d27\u503c",
    skuCount: "\u5f53\u65e5\u603b MSKU",
    detailRows: "\u660e\u7ec6\u884c\u6570",
    calcMsku: "\u8fdb\u5165\u8865\u8d27\u8ba1\u7b97",
    replenishQty: "\u8865\u8d27\u6570\u91cf",
    avgSupportDays: "\u5e73\u5747\u652f\u6491\u5929\u6570",
    actionLayers: "\u8865\u8d27\u5206\u5c42",
    basePool: "\u6d4b\u7b97\u8303\u56f4\u5206\u5e03",
    layerRank: "\u5c42\u7ea7",
    allMsku: "\u5168\u91cf MSKU",
    calcQty: "\u9700\u8865 SKU",
    all: LEVEL_ALL,
    level: "\u5c42\u7ea7",
    store: "\u5e97\u94fa",
    site: "\u56fd\u5bb6\u7c7b\u522b",
    dailySales: "\u65e5\u9500",
    supportDays: "\u652f\u6491\u5929\u6570",
    available: "FBA\u53ef\u7528",
    inTransit: "FBA\u5728\u9014",
    local: "\u672c\u5730\u5728\u4ed3",
    purchasePlan: "\u8ba1\u5212\u91c7\u8d2d\u6570",
    sales30d: "30\u5929\u9500\u91cf",
    categoryPeriod: "\u5206\u7c7b\u5468\u671f",
    periodSalableDailySales: "\u5929\u53ef\u552e\u65e5\u9500",
    periodProfitRate: "\u5929\u8ba2\u5355\u6bdb\u5229\u7387",
    needQty: "\u9700\u6c42\u91cf",
    boxQty: "\u7bb1\u6570",
    followStatus: "\u662f\u5426\u8ddf\u5356",
    followOriginLink: "\u8ddf\u5356\u539f\u59cb\u94fe\u63a5",
    followedStatus: "\u662f\u5426\u88ab\u8ddf\u5356",
    followedByLinks: "\u88ab\u8ddf\u5356\u65b9",
    replenishBlockReason: "\u4e0d\u8865\u8d27\u539f\u56e0",
    asinMergeStatus: "\u662f\u5426ASIN\u5408\u5e76",
    asinMergeTarget: "ASIN\u5408\u5e76\u76ee\u6807",
    asinMergeReason: "ASIN\u5408\u5e76\u539f\u56e0",
    listingTags: "\u5546\u54c1\u6807\u7b7e",
    countryPerformance: "\u56fd\u5bb6\u8868\u73b0",
    countryDetail: "\u56fd\u5bb6\u660e\u7ec6",
    countryCount: "\u56fd\u5bb6\u6570",
    periodSales: "\u5468\u671f\u9500\u91cf",
    periodAmount: "\u5468\u671f\u9500\u552e\u989d",
    periodMargin: "\u5468\u671f\u8ba2\u5355\u6bdb\u5229\u7387",
    listingPrice: "\u4ef7\u683c",
    marginPrices: "\u6bdb\u5229\u5b9a\u4ef7",
    marginPrice35: "35\u6bdb\u5229\u5b9a\u4ef7",
    marginPrice10: "10\u6bdb\u5229\u5b9a\u4ef7",
    salableDailySales: "\u53ef\u552e\u65e5\u9500",
    salesAmount: "\u9500\u552e\u989d",
    profit: "\u8ba2\u5355\u6bdb\u5229\u6da6",
    avgRanking: "\u6700\u540e\u4e00\u5929\u6392\u540d",
    bestRanking: "\u6700\u597d\u6392\u540d",
    worstRanking: "\u6700\u5dee\u6392\u540d",
    conversionRate: "\u8f6c\u5316\u7387",
    adSpend: "\u5e7f\u544a\u82b1\u8d39",
    adSales: "\u5e7f\u544a\u9500\u552e\u989d",
    skuInfo: "SKU \u4fe1\u606f",
    replenishAdvice: "\u8865\u8d27\u5efa\u8bae",
    inventoryStructure: "\u5e93\u5b58\u7ed3\u6784",
    salesSupport: "\u9500\u552e\u652f\u6491",
    category: "\u4ea7\u54c1\u5206\u7c7b",
    margin: "\u8ba2\u5355\u6bdb\u5229\u7387\u533a\u95f4",
    flowChange: "\u8f83\u4e0a\u671f",
    flowNew: "\u65b0\u589e",
    flowIn: "\u6d41\u5165",
    flowOut: "\u6d41\u51fa",
    flowExit: "\u9000\u51fa",
    flowStay: "\u4fdd\u6301",
    flowDetail: "\u5c42\u7ea7\u6d41\u8f6c",
    flowReason: "\u53d8\u5316\u539f\u56e0",
    prevLevel: "\u6628\u5929\u5c42\u7ea7",
    curLevel: "\u4eca\u5929\u5c42\u7ea7",
    totalPrefix: "\u5171 ",
    totalMiddle: " \u6761\uff0c\u7b2c ",
    totalSuffix: " \u9875"
  };
  var state = {
    snapshot_date: query.get("snapshot_date") || "",
    level: query.get("level") || "all",
    category: query.get("category") || "all",
    site: query.get("site") || "all",
    store: query.get("store") || "all",
    keyword: query.get("keyword") || "",
    category_period_days: Number(query.get("category_period_days") || 30),
    sort_field: query.get("sort_field") || "",
    sort_dir: query.get("sort_dir") || "",
    page: Number(query.get("page") || 1),
    page_size: normalizePageSize(query.get("page_size"))
  };
  var elements = {};
  var meta = null;
  var token = 0;
  var datePickerMonth = null;
  var countryDrawer = {
    open: false,
    period_days: 30,
    row: null,
    sort_field: "",
    sort_dir: ""
  };
  var marginPricePopover = null;
  var flowDrawer = {
    open: false,
    level: "all",
    flow_type: "all",
    chart: null
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "datePickerBtn", "datePickerValue", "datePickerPanel", "levelSelect", "categoryPeriodSelect", "siteSelect", "storeSelect", "keywordInput", "orderKeywordInput", "clearFiltersBtn",
      "periodHint", "summaryGrid", "layerVizGrid", "levelTabs", "tableWrap", "paginationInfo", "paginationNumbers", "pageSizeSelect",
      "prevPageBtn", "nextPageBtn", "sortQtyBtn", "sortSupportBtn", "openTrackingBtn", "exportReplenishmentBtn",
      "countryDrawerMask", "countryDrawer", "countryDrawerTitle", "countryDrawerSubtitle", "countryDrawerCloseBtn",
      "countryPeriodTabs", "countrySummaryGrid", "countryMetricsWrap",
      "flowDrawerMask", "flowDrawer", "flowDrawerTitle", "flowDrawerSubtitle", "flowDrawerCloseBtn",
      "flowSummaryGrid", "flowSankeyChart", "flowDetailWrap"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
    bindEvents();
    render();
  }

  function bindEvents() {
    [
      ["levelSelect", "level"],
      ["categoryPeriodSelect", "category_period_days"],
      ["siteSelect", "site"],
      ["storeSelect", "store"]
    ].forEach(function (pair) {
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = pair[1] === "category_period_days" ? Number(this.value || 30) : this.value;
        state.page = 1;
        render();
      });
    });
    elements.datePickerBtn.addEventListener("click", function () {
      toggleDatePicker();
    });
    elements.datePickerPanel.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var action = event.target.closest("[data-date-action]");
      var dateButton = event.target.closest("[data-date-value]");
      if (action) {
        datePickerMonth = shiftMonth(datePickerMonth || monthStartFromValue(state.snapshot_date), Number(action.dataset.dateAction || 0));
        renderDatePicker();
        return;
      }
      if (dateButton && !dateButton.disabled) {
        selectDateValue(dateButton.dataset.dateValue);
      }
    });
    document.addEventListener("click", function (event) {
      if (!elements.datePickerPanel.hidden && !event.target.closest(".replenishment-date-control")) {
        closeDatePicker();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDatePicker();
        closeCountryDrawer();
        closeFlowDrawer();
      }
    });
    elements.keywordInput.addEventListener("input", function () {
      state.keyword = this.value.trim();
      state.page = 1;
      render();
    });
    elements.clearFiltersBtn.addEventListener("click", function () {
      state.level = "all";
      state.category = "all";
      state.site = "all";
      state.store = "all";
      state.keyword = "";
      state.category_period_days = 30;
      state.sort_field = "";
      state.sort_dir = "";
      state.page = 1;
      if (elements.orderKeywordInput) elements.orderKeywordInput.value = "";
      syncControls();
      render();
    });
    elements.prevPageBtn.addEventListener("click", function () {
      if (state.page > 1) {
        state.page -= 1;
        render();
      }
    });
    elements.nextPageBtn.addEventListener("click", function () {
      state.page += 1;
      render();
    });
    elements.pageSizeSelect.addEventListener("change", function () {
      state.page_size = normalizePageSize(this.value);
      state.page = 1;
      render();
    });
    elements.sortQtyBtn.addEventListener("click", function () {
      state.sort_field = "replenish_qty";
      state.sort_dir = state.sort_dir === "desc" ? "asc" : "desc";
      render();
    });
    elements.sortSupportBtn.addEventListener("click", function () {
      state.sort_field = "support_days";
      state.sort_dir = state.sort_dir === "asc" ? "desc" : "asc";
      render();
    });
    if (elements.openTrackingBtn) {
      elements.openTrackingBtn.addEventListener("click", openTrackingPage);
    }
    elements.exportReplenishmentBtn.addEventListener("click", exportReplenishment);
    elements.tableWrap.addEventListener("click", function (event) {
      var button = event.target.closest("[data-country-detail]");
      if (!button) return;
      var row = window.replenishmentCountryRowMap ? window.replenishmentCountryRowMap[button.dataset.rowKey || ""] : null;
      if (row) openCountryDrawer(row);
    });
    elements.countryDrawerCloseBtn.addEventListener("click", closeCountryDrawer);
    elements.countryDrawerMask.addEventListener("click", closeCountryDrawer);
    elements.flowDrawerCloseBtn.addEventListener("click", closeFlowDrawer);
    elements.flowDrawerMask.addEventListener("click", closeFlowDrawer);
    elements.countryPeriodTabs.addEventListener("click", function (event) {
      var button = event.target.closest("[data-country-period]");
      if (!button) return;
      countryDrawer.period_days = Number(button.dataset.countryPeriod || 30);
      fetchCountryMetrics();
    });
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-margin-price-key]");
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      toggleMarginPricePopover(button, button.dataset.marginPriceKey || "");
    }, true);
    document.addEventListener("click", function (event) {
      if (!marginPricePopover) return;
      if (event.target.closest(".margin-price-popover") || event.target.closest("[data-margin-price-key]")) return;
      closeMarginPricePopover();
    });
  }

  function render() {
    var current = ++token;
    writeQuery();
    elements.tableWrap.innerHTML = '<div class="empty-state compact">' + text.loading + '</div>';
    app.apiGet("/api/replenishment", state).then(function (payload) {
      if (current !== token) return;
      meta = payload.meta || meta || {};
      if (!state.snapshot_date && payload.snapshot_date) state.snapshot_date = payload.snapshot_date;
      populateFilters();
      syncControls();
      renderHeader(payload);
      renderSummary(payload);
      renderLayerViz(payload);
      renderTabs(payload);
      renderTable(payload);
      renderPagination(payload);
    }).catch(function (error) {
      console.error(error);
      elements.tableWrap.innerHTML = '<div class="empty-state compact">' + text.loadFailed + '</div>';
    });
  }

  function populateFilters() {
    if (!meta) return;
    if (!datePickerMonth) datePickerMonth = monthStartFromValue(state.snapshot_date || (meta.dates || [])[0]);
    renderDatePicker();
    elements.levelSelect.innerHTML = (meta.levels || []).map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</option>';
    }).join("");
    app.setSelectOptions(elements.siteSelect, meta.sites || [], text.allSites);
    app.setSelectOptions(elements.storeSelect, meta.stores || [], text.allStores);
  }

  function syncControls() {
    elements.datePickerValue.textContent = state.snapshot_date || "--";
    elements.levelSelect.value = state.level || "all";
    elements.categoryPeriodSelect.value = String(state.category_period_days || 30);
    elements.siteSelect.value = state.site || "all";
    elements.storeSelect.value = state.store || "all";
    elements.keywordInput.value = state.keyword || "";
    elements.pageSizeSelect.value = String(normalizePageSize(state.page_size));
  }

  function renderHeader(payload) {
    elements.periodHint.textContent = payload.snapshot_date ? text.replenishDate + payload.snapshot_date : text.noResult;
  }

  function renderSummary(payload) {
    var s = payload.summary || {};
    var cards = [
      [text.replenishSku, formatNumber(s.calc_msku_count), "primary", "\u8865", "\u7d27\u6025/\u5efa\u8bae/\u8ba1\u5212\u4e09\u5c42\u5408\u8ba1"],
      [text.replenishQty, formatNumber(s.replenish_qty), "quantity", "\u6570", "\u6309\u7bb1\u89c4\u6574\u540e\u7684\u8865\u8d27\u603b\u6570"],
      [text.replenishValue, formatCurrency(s.replenish_cost), "value", "\u00a5", "\u6309\u91c7\u8d2d\u4ef7\u805a\u5408"],
      [text.skuCount, formatNumber(s.all_msku_count || s.sku_count), "context", "\u603b", "\u53c2\u4e0e\u8865\u8d27\u6d4b\u7b97"],
      [LEVEL_SUFFICIENT + " / " + LEVEL_ZERO_SALES, formatNumber((s.sufficient_count || 0) + (s.zero_sales_count || 0)), "context", "\u4f59", "\u4e0d\u8fdb\u5165\u8865\u8d27\u8ba1\u7b97"]
    ];
    elements.summaryGrid.innerHTML = cards.map(function (card) {
      return [
        '<div class="action-kpi-card ' + card[2] + '">',
        '<i class="kpi-glyph">' + app.escapeHtml(card[3] || "") + '</i>',
        '<span>' + app.escapeHtml(card[0]) + '</span>',
        '<strong>' + app.escapeHtml(card[1]) + '</strong>',
        '<small>' + app.escapeHtml(card[4] || "") + '</small>',
        '</div>'
      ].join("");
    }).join("");
  }

  function renderLayerViz(payload) {
    var rows = payload.level_summary || [];
    if (!rows.length) {
      elements.layerVizGrid.innerHTML = "";
      return;
    }
    var actionRows = rows.filter(function (row) { return Number(row.sort || 0) <= 3; });
    var passiveRows = rows.filter(function (row) { return Number(row.sort || 0) > 3; });
    var maxQty = actionRows.reduce(function (max, row) {
      return Math.max(max, Number(row.replenish_qty || 0));
    }, 0) || 1;
    elements.layerVizGrid.innerHTML = [
      '<div class="panel replenish-action-panel">',
      '<div class="replenish-panel-title"><span>' + text.actionLayers + '</span><strong>' + text.replenishQty + '</strong><strong>' + text.replenishValue + '</strong></div>',
      actionRows.map(function (row) {
        var level = row.level || "";
        var width = Math.max(2, Math.round(Number(row.replenish_qty || 0) / maxQty * 100));
        var active = state.level === level ? " active" : "";
        return [
          '<div class="replenish-layer-row level-' + app.escapeHtml(String(row.sort || "")) + active + '" data-level="' + app.escapeHtml(level) + '" role="button" tabindex="0">',
          '<span class="layer-mark">' + layerGlyph(row.sort) + '</span>',
          '<span class="layer-name"><span class="layer-title"><span>' + app.escapeHtml(level) + '</span>' + renderLevelHelp(level) + '<button type="button" class="layer-tracking-button" data-tracking-level-entry="' + app.escapeHtml(level) + '">采购发货追踪</button></span><small>' + formatNumber(row.sku_count) + ' MSKU</small>' + renderFlowChips(row) + renderCategoryMix(row.category_mix, row.sku_count, level) + '</span>',
          '<strong>' + formatNumber(row.replenish_qty) + '</strong>',
          '<strong>' + formatCurrency(row.replenish_cost) + '</strong>',
          '<span class="layer-progress"><i style="width:' + width + '%"></i></span>',
          '</div>'
        ].join("");
      }).join(""),
      '</div>',
      '<div class="panel replenish-pool-panel">',
      '<div class="replenish-pool-title">' + text.basePool + '</div>',
      passiveRows.map(function (row) {
        return [
          '<button type="button" class="pool-chip level-' + app.escapeHtml(String(row.sort || "")) + '" data-level="' + app.escapeHtml(row.level || "") + '">',
          '<span class="mix-icon">' + layerGlyph(row.sort) + '</span>',
          '<span class="pool-chip-title">' + app.escapeHtml(row.level || "") + renderLevelHelp(row.level || "") + '</span>',
          '<strong>' + formatNumber(row.sku_count) + '</strong>',
          '<small>' + text.replenishQty + ' ' + formatNumber(row.replenish_qty) + '</small>',
          '</button>'
        ].join("");
      }).join(""),
      '<div class="pool-note">' + text.skuCount + ' ' + formatNumber((payload.summary || {}).all_msku_count || (payload.summary || {}).sku_count) + '</div>',
      '</div>'
    ].join("");
    Array.from(elements.layerVizGrid.querySelectorAll("[data-category]")).forEach(function (node) {
      node.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        selectLayerDetails(this.dataset.level || "all", this.dataset.category || "all");
      });
    });
    Array.from(elements.layerVizGrid.querySelectorAll("[data-flow-type]")).forEach(function (node) {
      node.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openLevelFlowDrawer(this.dataset.flowLevel || "all", this.dataset.flowType || "all");
      });
    });
    Array.from(elements.layerVizGrid.querySelectorAll("[data-tracking-level-entry]")).forEach(function (node) {
      node.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openTrackingPage(event, this.dataset.trackingLevelEntry || "all");
      });
    });
    Array.from(elements.layerVizGrid.querySelectorAll("[data-level]:not([data-category])")).forEach(function (node) {
      node.addEventListener("click", function (event) {
        if (event.target.closest(".layer-help, .layer-tracking-button")) return;
        selectLayerDetails(this.dataset.level || "all", "all");
      });
      node.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        selectLayerDetails(this.dataset.level || "all", "all");
      });
    });
  }

  function selectLayerDetails(level, category) {
    state.level = level || "all";
    state.category = category || "all";
    state.page = 1;
    render();
    window.setTimeout(function () {
      var detailSection = elements.tableWrap && elements.tableWrap.closest(".dashboard-section");
      if (detailSection) detailSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }

  function renderLevelHelp(level) {
    var lines = (LEVEL_HELP[level] || []).slice();
    if ([LEVEL_URGENT, LEVEL_SUGGESTED, LEVEL_PLANNED].indexOf(level) >= 0) {
      lines = lines.concat(DAILY_SALES_HELP, FLOW_HELP);
    }
    if (!lines.length) return "";
    var body = lines.map(function (line) {
      return '<span>' + app.escapeHtml(line) + '</span>';
    }).join("");
    return [
      '<span class="layer-help" tabindex="0" aria-label="' + app.escapeHtml(lines.join(" ")) + '">',
      '<span class="layer-help-icon">?</span>',
      '<span class="layer-help-popover" role="tooltip">' + body + '</span>',
      '</span>'
    ].join("");
  }

  function renderCategoryMix(rows, total, level) {
    var itemMap = {};
    (rows || []).forEach(function (row) {
      if (!row || !row.category) return;
      itemMap[row.category] = row;
    });
    var orderedItems = CATEGORY_MIX_ORDER.map(function (category) {
      return itemMap[category];
    }).filter(Boolean);
    var extraItems = (rows || []).filter(function (row) {
      return row && row.category && CATEGORY_MIX_ORDER.indexOf(row.category) < 0;
    });
    var items = orderedItems.concat(extraItems).filter(function (row) { return Number(row.sku_count || 0) > 0; });
    if (!items.length) return "";
    var denominator = Number(total || 0) || items.reduce(function (sum, row) {
      return sum + Number(row.sku_count || 0);
    }, 0) || 1;
    return '<span class="layer-category-mix">' + items.sort(categoryOrder).map(function (row) {
      var count = Number(row.sku_count || 0);
      var category = row.category || "-";
      var active = state.level === level && state.category === category ? " active" : "";
      return '<button type="button" class="' + categoryTone(category) + active + '" data-level="' + app.escapeHtml(level || "all") + '" data-category="' + app.escapeHtml(category) + '">' + app.escapeHtml(category) + ' ' + formatNumber(count) + '<b>' + formatPercent(count / denominator) + '</b></button>';
    }).join("") + '</span>';
  }

  function categoryTone(category) {
    if (category === "明星产品") return "positive";
    if (category === "潜力产品") return "band-low";
    if (category === "瘦狗产品") return "warning";
    if (category === "问题产品") return "negative";
    return "neutral";
  }

  function categoryOrder(a, b) {
    var order = {"明星产品": 1, "潜力产品": 2, "瘦狗产品": 3, "问题产品": 4};
    return (order[a.category] || 9) - (order[b.category] || 9);
  }

  function renderFlowChips(row) {
    var flow = row.flow || {};
    var level = row.level || "";
    var chips = [
      [text.flowChange, Number(flow.delta_count || 0), "all"],
      [text.flowIn, Number(flow.in_count || 0), "\u6d41\u5165"],
      [text.flowOut, Number(flow.out_count || 0), "\u6d41\u51fa"],
      [text.flowExit, Number(flow.exit_count || 0), "\u9000\u51fa"],
      [text.flowNew, Number(flow.new_count || 0), "\u65b0\u589e"]
    ];
    return '<span class="level-flow-chips">' + chips.map(function (chip) {
      var value = chip[1];
      var signed = chip[2] === "all";
      var tone = value > 0 ? "up" : (value < 0 ? "down" : "flat");
      var label = signed ? signedNumber(value) : formatNumber(value, 0);
      return [
        '<button type="button" class="level-flow-chip ' + tone + '" data-flow-level="' + app.escapeHtml(level) + '" data-flow-type="' + app.escapeHtml(chip[2]) + '">',
        '<span>' + app.escapeHtml(chip[0]) + '</span>',
        '<strong>' + app.escapeHtml(label) + '</strong>',
        '</button>'
      ].join("");
    }).join("") + '</span>';
  }

  function openLevelFlowDrawer(level, flowType) {
    flowDrawer.open = true;
    flowDrawer.level = level || "all";
    flowDrawer.flow_type = flowType || "all";
    elements.flowDrawer.hidden = false;
    elements.flowDrawerMask.hidden = false;
    elements.flowDrawer.setAttribute("aria-hidden", "false");
    elements.flowDrawerTitle.textContent = flowDrawer.level === "all" ? text.flowDetail : flowDrawer.level + " - " + text.flowDetail;
    elements.flowDrawerSubtitle.textContent = text.loading;
    elements.flowSummaryGrid.innerHTML = "";
    elements.flowSankeyChart.innerHTML = "";
    elements.flowDetailWrap.innerHTML = '<div class="empty-state compact">' + text.loading + '</div>';
    fetchLevelFlow();
  }

  function closeFlowDrawer() {
    if (!elements.flowDrawer) return;
    flowDrawer.open = false;
    elements.flowDrawer.hidden = true;
    elements.flowDrawerMask.hidden = true;
    elements.flowDrawer.setAttribute("aria-hidden", "true");
    if (flowDrawer.chart) {
      flowDrawer.chart.dispose();
      flowDrawer.chart = null;
    }
  }

  function fetchLevelFlow() {
    var level = flowDrawer.level;
    var flowType = flowDrawer.flow_type;
    app.apiGet("/api/replenishment/level-flow", {
      snapshot_date: state.snapshot_date,
      level: level,
      flow_type: flowType,
      category: state.category,
      site: state.site,
      store: state.store,
      keyword: state.keyword,
      category_period_days: state.category_period_days
    }).then(function (payload) {
      if (!flowDrawer.open || flowDrawer.level !== level || flowDrawer.flow_type !== flowType) return;
      renderFlowDrawer(payload);
    }).catch(function (error) {
      console.error(error);
      elements.flowDetailWrap.innerHTML = '<div class="empty-state compact">' + text.loadFailed + '</div>';
    });
  }

  function renderFlowDrawer(payload) {
    var dates = payload.dates || {};
    elements.flowDrawerSubtitle.textContent = (dates.prev_date || "--") + " \u2192 " + (dates.cur_date || "--");
    renderFlowSummary(payload.summary || {});
    renderFlowSankey(payload.sankey || {}, payload.summary || {});
    renderFlowDetailTable(payload.items || []);
  }

  function renderFlowSummary(summary) {
    var cards = [
      [text.skuInfo, formatNumber(summary.sku_count, 0)],
      [text.flowIn, formatNumber(summary.in_count, 0)],
      [text.flowOut, formatNumber(summary.out_count, 0)],
      [text.flowExit, formatNumber(summary.exit_count, 0)],
      [text.flowNew, formatNumber(summary.new_count, 0)],
      [text.replenishQty, signedNumber(summary.replenish_qty_delta || 0)],
      [text.replenishValue, signedCurrency(summary.replenish_cost_delta || 0)]
    ];
    elements.flowSummaryGrid.innerHTML = cards.map(function (card) {
      return '<div class="country-summary-card"><span>' + app.escapeHtml(card[0]) + '</span><strong>' + app.escapeHtml(card[1]) + '</strong></div>';
    }).join("");
  }

  function renderFlowSankey(sankey, summary) {
    if (typeof echarts === "undefined" || !elements.flowSankeyChart) return;
    var chartData = enrichFlowSankey(sankey, summary);
    if (flowDrawer.chart) flowDrawer.chart.dispose();
    flowDrawer.chart = echarts.init(elements.flowSankeyChart);
    flowDrawer.chart.setOption({
      backgroundColor: "#ffffff",
      tooltip: {
        trigger: "item",
        formatter: function (params) {
          if (!params.data || params.data.source == null) {
            return [
              app.escapeHtml(params.name || ""),
              "<br/>SKU\uff1a" + formatNumber(params.data && params.data.flow_count, 0),
              "<br/>\u5360\u6bd4\uff1a" + formatPercent(params.data && params.data.flow_percent)
            ].join("");
          }
          return [
            app.escapeHtml(params.data.source + " \u2192 " + params.data.target),
            "<br/>SKU\u6570\uff1a" + formatNumber(params.data.value, 0),
            "<br/>\u8865\u8d27\u6570\u91cf\uff1a" + formatNumber(params.data.replenish_qty, 0),
            "<br/>\u8865\u8d27\u8d27\u503c\uff1a" + formatCurrency(params.data.replenish_cost)
          ].join("");
        }
      },
      series: [{
        type: "sankey",
        left: 84,
        right: 128,
        top: 22,
        bottom: 24,
        nodeWidth: 16,
        nodeGap: 14,
        layoutIterations: 0,
        draggable: false,
        label: {
          color: "#10213a",
          fontWeight: 700,
          align: "center",
          lineHeight: 16,
          overflow: "break",
          width: 72,
          formatter: function (params) {
            return params.data && params.data.flow_label ? params.data.flow_label : params.name;
          }
        },
        itemStyle: { borderColor: "rgba(255,255,255,0.95)", borderWidth: 1 },
        lineStyle: { color: "gradient", opacity: 0.22, curveness: 0.5 },
        emphasis: { focus: "adjacency" },
        data: chartData.nodes,
        links: chartData.links
      }]
    });
    window.setTimeout(function () {
      if (flowDrawer.chart) flowDrawer.chart.resize();
    }, 80);
  }

  function enrichFlowSankey(sankey, summary) {
    var nodes = sankey.nodes || [];
    var links = sankey.links || [];
    var nodeTotals = {};
    var denominator = Number((summary || {}).sku_count || 0);
    links.forEach(function (link) {
      var value = Number(link.value || 0);
      if (link.source) nodeTotals[link.source] = (nodeTotals[link.source] || 0) + value;
      if (link.target) nodeTotals[link.target] = (nodeTotals[link.target] || 0) + value;
    });
    return {
      nodes: nodes.map(function (node) {
        var count = Number(nodeTotals[node.name] || 0);
        var percent = denominator ? count / denominator : 0;
        return Object.assign({}, node, {
          flow_count: count,
          flow_percent: percent,
          flow_label: node.name
        });
      }),
      links: links
    };
  }

  function renderFlowDetailTable(rows) {
    if (!rows.length) {
      elements.flowDetailWrap.innerHTML = '<div class="empty-state compact">\u6682\u65e0\u6d41\u8f6c\u660e\u7ec6</div>';
      return;
    }
    elements.flowDetailWrap.innerHTML = '<div id="flowDetailAgGrid"></div>';
    window.kanbanGrid.makeGrid("flowDetailAgGrid", {
      rowData: rows,
      rowHeight: 52,
      domLayout: "normal",
      columnDefs: [
        { headerName: "MSKU / SKU", field: "msku", pinned: "left", width: 150, cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.msku || "-", params.data.sku || ""); } },
        { headerName: text.store, field: "store", width: 120 },
        { headerName: text.site, field: "country", width: 110 },
        { headerName: text.prevLevel, field: "prev_level", width: 120 },
        { headerName: text.curLevel, field: "cur_level", width: 120 },
        { headerName: text.flowDetail, field: "flow_type", width: 96, cellRenderer: function (params) { return '<span class="status-pill">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: text.flowReason, field: "reason", width: 122 },
        numberColumn("\u6628\u652f\u6491\u5929", "prev_support_days", 112, 2),
        numberColumn("\u4eca\u652f\u6491\u5929", "cur_support_days", 112, 2),
        numberColumn("\u6628\u8865\u8d27\u6570", "prev_replenish_qty", 112, 0),
        numberColumn("\u4eca\u8865\u8d27\u6570", "cur_replenish_qty", 112, 0),
        { headerName: "\u6628\u8865\u8d27\u8d27\u503c", field: "prev_replenish_cost", width: 132, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: "\u4eca\u8865\u8d27\u8d27\u503c", field: "cur_replenish_cost", width: 132, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } }
      ]
    });
  }

  function renderTabs(payload) {
    var rows = payload.level_summary || [];
    var allButton = '<button type="button" class="' + (state.level === "all" ? "active" : "") + '" data-level="all">' + text.all + '</button>';
    elements.levelTabs.innerHTML = [allButton].concat(rows.map(function (row) {
      return '<button type="button" class="' + (state.level === row.level ? "active" : "") + '" data-level="' + app.escapeHtml(row.level) + '">' + app.escapeHtml(row.level) + ' &middot; ' + formatNumber(row.sku_count) + '</button>';
    })).join("");
    Array.from(elements.levelTabs.querySelectorAll("[data-level]")).forEach(function (node) {
      node.addEventListener("click", function () {
        selectLayerDetails(this.dataset.level || "all", "all");
      });
    });
  }

  function renderTable(payload) {
    var rows = payload.items || [];
    if (!rows.length) {
      elements.tableWrap.innerHTML = '<div class="empty-state compact">' + text.noRows + '</div>';
      return;
    }
    var categoryPeriod = Number(payload.category_period_days || state.category_period_days || 30);
    window.replenishmentCountryRowMap = rows.reduce(function (map, row) {
      map[countryRowKey(row)] = row;
      return map;
    }, {});
    elements.tableWrap.innerHTML = '<div id="replenishmentAgGrid"></div>';
    window.kanbanGrid.makeGrid("replenishmentAgGrid", {
      rowData: rows,
      domLayout: "normal",
      rowHeight: 58,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">' + app.escapeHtml(text.noRows) + '</span>',
      onFilterChanged: handleGridFilterChanged,
      columnDefs: [
        { headerName: text.level, field: "level", pinned: "left", width: 118, sort: colSort("level"), cellRenderer: function (params) { return '<span class="status-pill level-' + app.escapeHtml(String((params.data || {}).level_sort || "")) + '">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: "MSKU / SKU", field: "msku", pinned: "left", width: 150, sort: colSort("msku"), cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.msku || "-", params.data.sku || ""); } },
        { headerName: text.store, field: "store", width: 130, sort: colSort("store") },
        { headerName: text.site, field: "country", width: 110, sort: colSort("country") },
        { headerName: text.countryPerformance, field: "country_summary", width: 188, cellRenderer: renderCountrySummaryCell },
        { headerName: text.listingTags, field: "listing_tags", width: 190, minWidth: 150, maxWidth: 260, sort: colSort("listing_tags"), tooltipField: "listing_tags", cellClass: "ag-truncate-column listing-tags-column", cellRenderer: renderDashCell },
        numberColumn(text.dailySales, "daily_sales", 112, 2),
        numberColumn(categoryPeriod + text.periodSalableDailySales, "category_daily_sales_30d", 132, 2),
        { headerName: categoryPeriod + text.periodProfitRate, field: "profit_rate_30d", width: 120, type: "numericColumn", sort: colSort("profit_rate_30d"), cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); } },
        { headerName: text.category, field: "category", width: 118, sort: colSort("category") },
        numberColumn(text.supportDays, "support_days", 118, 2),
        numberColumn(text.available, "available_total", 104, 0),
        numberColumn(text.inTransit, "stock_up_num", 104, 0),
        numberColumn(text.local, "local_quantity", 104, 0),
        numberColumn(text.purchasePlan, "purchase_plan_quantity", 118, 0),
        numberColumn(text.sales30d, "sales_30d", 110, 0),
        numberColumn(text.needQty, "need_qty", 120, 2),
        numberColumn(text.replenishQty, "replenish_qty", 122, 0),
        numberColumn(text.boxQty, "box_qty", 96, 0),
        { headerName: text.replenishValue, field: "cost", width: 132, type: "numericColumn", sort: colSort("cost"), cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: text.followStatus, field: "follow_status", width: 112, sort: colSort("follow_status"), cellRenderer: function (params) { return '<span class="status-pill">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: text.followOriginLink, field: "follow_origin_link", width: 142, sort: colSort("follow_origin_link"), tooltipField: "follow_origin_link", cellClass: "ag-truncate-column", cellRenderer: renderDashCell },
        { headerName: text.followedStatus, field: "followed_status", width: 118, sort: colSort("followed_status"), cellRenderer: function (params) { return '<span class="status-pill">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: text.followedByLinks, field: "followed_by_links", width: 112, sort: colSort("followed_by_links"), tooltipField: "followed_by_links", cellRenderer: renderLinkSummaryCell },
        { headerName: text.replenishBlockReason, field: "replenish_block_reason", width: 136, sort: colSort("replenish_block_reason"), tooltipField: "replenish_block_reason", cellClass: "ag-truncate-column", cellRenderer: renderDashCell },
        { headerName: text.asinMergeStatus, field: "asin_merge_status", width: 118, sort: colSort("asin_merge_status"), cellRenderer: function (params) { return '<span class="status-pill">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: text.asinMergeTarget, field: "asin_merge_target", width: 132, sort: colSort("asin_merge_target"), tooltipField: "asin_merge_target", cellClass: "ag-truncate-column", cellRenderer: renderDashCell },
        { headerName: text.asinMergeReason, field: "asin_merge_reason", width: 144, sort: colSort("asin_merge_reason"), tooltipField: "asin_merge_reason", cellClass: "ag-truncate-column", cellRenderer: renderDashCell },
        { headerName: text.margin, field: "margin_range", width: 146, sort: colSort("margin_range") }
      ],
      onSortChanged: handleGridSortChanged
    });
  }

  function renderLinkSummaryCell(params) {
    var data = params.data || {};
    var value = params.value || "";
    if (!value) return "-";
    var count = Number(data.followed_by_count || 0);
    if (!count) {
      count = String(value).split("|").filter(function (part) { return part.trim(); }).length;
    }
    return app.escapeHtml(String(count)) + "个链接";
  }

  function renderDashCell(params) {
    return '<span class="ag-truncate-cell">' + app.escapeHtml(params.value || "-") + '</span>';
  }

  function renderCountrySummaryCell(params) {
    var data = params.data || {};
    var summary = data.country_summary || {};
    var countryCount = Number(summary.country_count || 0);
    var top = summary.top_countries || "";
    var label = countryCount ? (top || ("\u56fd\u5bb6 " + countryCount + " \u4e2a")) : "\u67e5\u770b\u660e\u7ec6";
    var key = countryRowKey(data);
    return [
      '<button type="button" class="country-summary-button" data-country-detail="1" data-row-key="' + app.escapeHtml(key) + '">',
      '<span>' + app.escapeHtml(label) + '</span>',
      '<small>' + app.escapeHtml(countryCount ? "\u0033\u0030\u5929\u9500\u91cf\u6700\u9ad8" : "\u70b9\u51fb\u67e5\u770b 7/14/30/90 \u5929") + '</small>',
      '</button>'
    ].join("");
  }

  function countryRowKey(row) {
    row = row || {};
    return [row.cur_date || "", row.country || "", row.store || "", row.msku || ""].map(function (part) {
      return encodeURIComponent(String(part));
    }).join("|");
  }

  function openCountryDrawer(row) {
    countryDrawer.open = true;
    countryDrawer.row = row;
    countryDrawer.period_days = 30;
    countryDrawer.sort_field = "";
    countryDrawer.sort_dir = "";
    elements.countryDrawer.hidden = false;
    elements.countryDrawerMask.hidden = false;
    elements.countryDrawer.setAttribute("aria-hidden", "false");
    elements.countryDrawerTitle.textContent = [row.msku || "-", row.store || "-", row.country || "-"].join(" / ");
    elements.countryDrawerSubtitle.textContent = (row.sku || "") + (row.level ? (" · " + row.level) : "");
    fetchCountryMetrics();
  }

  function closeCountryDrawer() {
    if (!elements.countryDrawer) return;
    countryDrawer.open = false;
    countryDrawer.row = null;
    elements.countryDrawer.hidden = true;
    elements.countryDrawerMask.hidden = true;
    elements.countryDrawer.setAttribute("aria-hidden", "true");
  }

  function fetchCountryMetrics() {
    var row = countryDrawer.row;
    if (!row) return;
    renderCountryPeriodTabs();
    elements.countryMetricsWrap.innerHTML = '<div class="empty-state compact">' + text.loading + '</div>';
    app.apiGet("/api/replenishment/country-metrics", {
      snapshot_date: state.snapshot_date,
      site: row.country,
      store: row.store,
      msku: row.msku,
      period_days: countryDrawer.period_days,
      sort_field: countryDrawer.sort_field,
      sort_dir: countryDrawer.sort_dir
    }).then(function (payload) {
      if (!countryDrawer.row || countryDrawer.row.msku !== row.msku) return;
      renderCountrySummary(payload);
      renderCountryMetricsTable(payload);
    }).catch(function (error) {
      console.error(error);
      elements.countryMetricsWrap.innerHTML = '<div class="empty-state compact">' + text.loadFailed + '</div>';
    });
  }

  function renderCountryPeriodTabs() {
    var periods = [7, 14, 30, 90];
    elements.countryPeriodTabs.innerHTML = periods.map(function (period) {
      var active = Number(countryDrawer.period_days) === period ? " active" : "";
      return '<button type="button" class="' + active + '" data-country-period="' + period + '">' + period + '\u5929</button>';
    }).join("");
  }

  function renderCountrySummary(payload) {
    var summary = payload.summary || {};
    var cards = [
      [text.countryCount, formatNumber(summary.country_count, 0)],
      [text.periodSales, formatNumber(summary.sales_qty, 0)],
      [text.periodAmount, formatCurrency(summary.sales_amount)],
      [text.periodMargin, window.kanbanGrid.percent(summary.order_gross_margin, 2)]
    ];
    elements.countrySummaryGrid.innerHTML = cards.map(function (card) {
      return [
        '<div class="country-summary-card">',
        '<span>' + app.escapeHtml(card[0]) + '</span>',
        '<strong>' + app.escapeHtml(card[1]) + '</strong>',
        '</div>'
      ].join("");
    }).join("");
  }

  function renderCountryMetricsTable(payload) {
    var rows = payload.items || [];
    if (!rows.length) {
      elements.countryMetricsWrap.innerHTML = '<div class="empty-state compact">\u6682\u65e0\u56fd\u5bb6\u660e\u7ec6</div>';
      return;
    }
    closeMarginPricePopover();
    window.replenishmentMarginPriceRowMap = {};
    rows.forEach(function (row, index) {
      row._margin_price_key = "margin-price-" + index;
      window.replenishmentMarginPriceRowMap[row._margin_price_key] = row;
    });
    elements.countryMetricsWrap.innerHTML = '<div id="countryMetricsAgGrid"></div>';
    window.kanbanGrid.makeGrid("countryMetricsAgGrid", {
      rowData: rows,
      rowHeight: 52,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">\u6682\u65e0\u56fd\u5bb6\u660e\u7ec6</span>',
      columnDefs: [
        { headerName: "\u56fd\u5bb6", field: "country", pinned: "left", width: 92 },
        { headerName: "Listing SKU", field: "local_sku_list", width: 150, cellRenderer: function (params) { return '<span class="sku-list-cell">' + app.escapeHtml(params.value || "-") + '</span>'; } },
        countryNumberColumn(text.periodSales, "sales_qty", 100, 0),
        countryNumberColumn(text.listingPrice, "listing_price", 100, 2),
        {
          headerName: text.marginPrices,
          field: "margin_price_35",
          width: 126,
          type: "numericColumn",
          cellRenderer: renderMarginPriceCell
        },
        countryNumberColumn(text.salableDailySales, "salable_daily_sales", 110, 2),
        { headerName: text.salesAmount, field: "sales_amount", width: 116, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: text.profit, field: "order_gross_profit", width: 112, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: "\u8ba2\u5355\u6bdb\u5229\u7387", field: "order_gross_margin", width: 120, type: "numericColumn", cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); } },
        countryNumberColumn(text.avgRanking, "avg_ranking", 104, 0),
        countryNumberColumn(text.bestRanking, "best_ranking", 104, 0),
        countryNumberColumn(text.worstRanking, "worst_ranking", 104, 0),
        countryNumberColumn("Sessions", "sessions_total", 110, 0),
        { headerName: text.conversionRate, field: "conversion_rate", width: 104, type: "numericColumn", cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); } },
        { headerName: text.adSpend, field: "ad_spend", width: 112, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: text.adSales, field: "ad_sales", width: 116, type: "numericColumn", cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: "ACOS", field: "acos", width: 92, type: "numericColumn", cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); } },
        {
          headerName: "TACOS",
          field: "tacos",
          width: 96,
          type: "numericColumn",
          valueGetter: function (params) {
            var data = params.data || {};
            var salesAmount = Number(data.sales_amount || 0);
            return salesAmount ? Number(data.ad_spend || 0) / salesAmount : 0;
          },
          cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); }
        }
      ]
    });
  }

  function countryNumberColumn(label, field, width, digits) {
    return {
      headerName: label,
      field: field,
      width: width,
      type: "numericColumn",
      cellRenderer: function (params) { return '<strong class="ag-number-strong">' + formatNumber(params.value, digits) + '</strong>'; }
    };
  }

  function renderMarginPriceCell(params) {
    var data = params.data || {};
    var prices = Array.isArray(data.margin_prices) ? data.margin_prices : [];
    var defaultItem = prices.find(function (item) { return Number(item.target) === 35; }) || prices[0] || null;
    var value = defaultItem ? defaultItem.price : data.margin_price_35;
    if (!prices.length && !value) return '<span class="muted-cell">-</span>';
    var label = defaultItem ? defaultItem.label : "35\u6bdb\u5229";
    return [
      '<button type="button" class="margin-price-trigger" data-margin-price-key="' + app.escapeHtml(data._margin_price_key || "") + '" title="\u67e5\u770b\u5168\u90e8\u6bdb\u5229\u5b9a\u4ef7">',
      '<strong>' + formatNumber(value, 2) + '</strong>',
      '<span>' + app.escapeHtml(label) + '</span>',
      '<i aria-hidden="true">\u2304</i>',
      '</button>'
    ].join("");
  }

  function toggleMarginPricePopover(button, key) {
    if (marginPricePopover && marginPricePopover.dataset.key === key) {
      closeMarginPricePopover();
      return;
    }
    var row = window.replenishmentMarginPriceRowMap ? window.replenishmentMarginPriceRowMap[key] : null;
    var prices = row && Array.isArray(row.margin_prices) ? row.margin_prices : [];
    closeMarginPricePopover();
    if (!prices.length) return;
    marginPricePopover = document.createElement("div");
    marginPricePopover.className = "margin-price-popover";
    marginPricePopover.dataset.key = key;
    marginPricePopover.innerHTML = [
      '<table>',
      '<thead><tr><th>\u6bdb\u5229\u6863\u4f4d</th><th>\u5b9a\u4ef7</th></tr></thead>',
      '<tbody>',
      prices.map(function (item) {
        return '<tr><td>' + app.escapeHtml(item.label || "") + '</td><td>' + formatNumber(item.price, 2) + '</td></tr>';
      }).join(""),
      '</tbody>',
      '</table>'
    ].join("");
    document.body.appendChild(marginPricePopover);
    positionMarginPricePopover(button);
  }

  function positionMarginPricePopover(button) {
    if (!marginPricePopover) return;
    var rect = button.getBoundingClientRect();
    var width = marginPricePopover.offsetWidth || 220;
    var left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
    var top = rect.bottom + 8;
    if (top + marginPricePopover.offsetHeight > window.innerHeight - 12) {
      top = Math.max(12, rect.top - marginPricePopover.offsetHeight - 8);
    }
    marginPricePopover.style.left = left + "px";
    marginPricePopover.style.top = top + "px";
  }

  function closeMarginPricePopover() {
    if (!marginPricePopover) return;
    marginPricePopover.remove();
    marginPricePopover = null;
  }

  function numberColumn(label, field, width, digits) {
    return {
      headerName: label,
      field: field,
      width: width,
      type: "numericColumn",
      sort: colSort(field),
      cellRenderer: function (params) { return '<strong class="ag-number-strong">' + formatNumber(params.value, digits) + '</strong>'; }
    };
  }

  function colSort(field) {
    return state.sort_field === field ? state.sort_dir : null;
  }

  function handleGridSortChanged(event) {
    var sortedColumn = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
    var nextField = sortedColumn ? sortedColumn.colId : "";
    var nextDir = sortedColumn ? sortedColumn.sort : "";
    if ((state.sort_field || "") === nextField && (state.sort_dir || "") === nextDir) return;
    state.sort_field = nextField;
    state.sort_dir = nextDir;
    state.page = 1;
    render();
  }

  function exportReplenishment() {
    var params = new URLSearchParams();
    ["snapshot_date", "level", "category", "category_period_days", "site", "store", "keyword", "sort_field", "sort_dir"].forEach(function (key) {
      var value = state[key];
      if (value !== undefined && value !== null && value !== "" && value !== "all") params.set(key, value);
    });
    window.location.href = "/api/replenishment/export" + (params.toString() ? ("?" + params.toString()) : "");
  }

  function openTrackingPage(event, level) {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    var targetLevel = level || state.level || "all";
    var params = new URLSearchParams();
    [
      ["snapshot_date", state.snapshot_date],
      ["level", targetLevel],
      ["site", state.site],
      ["store", state.store],
      ["keyword", state.keyword],
      ["tracking_window_days", 7],
      ["category_period_days", state.category_period_days]
    ].forEach(function (pair) {
      var value = pair[1];
      if (value !== undefined && value !== null && value !== "" && value !== "all") {
        params.set(pair[0], value);
      }
    });
    window.location.href = "/replenishment-tracking" + (params.toString() ? ("?" + params.toString()) : "");
  }

  function handleGridFilterChanged(event) {
    var model = event.api.getFilterModel ? event.api.getFilterModel() : {};
    var nextCategory = filterModelValue(model.category);
    if (!nextCategory) nextCategory = "all";
    if (nextCategory === state.category) return;
    state.category = nextCategory;
    state.page = 1;
    render();
  }

  function filterModelValue(model) {
    if (!model) return "";
    if (Array.isArray(model.values) && model.values.length === 1) return model.values[0];
    if (typeof model.filter === "string") return model.filter;
    return "";
  }

  function toggleDatePicker() {
    if (elements.datePickerPanel.hidden) {
      datePickerMonth = monthStartFromValue(state.snapshot_date || ((meta || {}).dates || [])[0]);
      renderDatePicker();
      elements.datePickerPanel.hidden = false;
      elements.datePickerBtn.setAttribute("aria-expanded", "true");
    } else {
      closeDatePicker();
    }
  }

  function closeDatePicker() {
    elements.datePickerPanel.hidden = true;
    elements.datePickerBtn.setAttribute("aria-expanded", "false");
  }

  function selectDateValue(value) {
    if (!value || state.snapshot_date === value) {
      closeDatePicker();
      return;
    }
    state.snapshot_date = value;
    state.page = 1;
    datePickerMonth = monthStartFromValue(value);
    closeDatePicker();
    syncControls();
    render();
  }

  function renderDatePicker() {
    if (!elements.datePickerPanel) return;
    var availableDates = (meta || {}).dates || [];
    var availableMap = availableDates.reduce(function (map, value) {
      map[value] = true;
      return map;
    }, {});
    var month = datePickerMonth || monthStartFromValue(state.snapshot_date || availableDates[0]);
    var firstDay = new Date(month.getFullYear(), month.getMonth(), 1);
    var daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    var leading = (firstDay.getDay() + 6) % 7;
    var todayValue = dateToValue(new Date());
    var cells = [];
    for (var blank = 0; blank < leading; blank += 1) {
      cells.push('<span class="calendar-day-spacer"></span>');
    }
    for (var day = 1; day <= daysInMonth; day += 1) {
      var date = new Date(month.getFullYear(), month.getMonth(), day);
      var value = dateToValue(date);
      var enabled = !!availableMap[value];
      var classes = ["calendar-day"];
      if (value === state.snapshot_date) classes.push("boundary");
      if (value === todayValue) classes.push("today");
      if (!enabled) classes.push("disabled");
      cells.push([
        '<button type="button" class="' + classes.join(" ") + '" data-date-value="' + app.escapeHtml(value) + '"' + (enabled ? "" : " disabled") + '>',
        day,
        '</button>'
      ].join(""));
    }
    elements.datePickerPanel.innerHTML = [
      '<div class="date-range-toolbar replenishment-calendar-toolbar">',
      '<button class="date-nav-button" type="button" data-date-action="-1" aria-label="上一月">&lsaquo;</button>',
      '<strong>' + app.escapeHtml(formatMonthTitle(month)) + '</strong>',
      '<button class="date-nav-button" type="button" data-date-action="1" aria-label="下一月">&rsaquo;</button>',
      '</div>',
      '<div class="calendar-month replenishment-calendar-month">',
      '<div class="calendar-weekdays">',
      ["一", "二", "三", "四", "五", "六", "日"].map(function (dayName) {
        return '<span class="calendar-weekday">' + dayName + '</span>';
      }).join(""),
      '</div>',
      '<div class="calendar-days">' + cells.join("") + '</div>',
      '</div>',
      '<div class="replenishment-calendar-foot">\u53ea\u663e\u793a\u5df2\u751f\u6210\u8865\u8d27\u7ed3\u679c\u7684\u65e5\u671f</div>'
    ].join("");
  }

  function parseDateValue(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }

  function monthStartFromValue(value) {
    var parsed = parseDateValue(value) || new Date();
    return new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  }

  function shiftMonth(value, offset) {
    var month = value || monthStartFromValue("");
    return new Date(month.getFullYear(), month.getMonth() + offset, 1);
  }

  function formatMonthTitle(value) {
    return value.getFullYear() + "\u5e74" + String(value.getMonth() + 1).padStart(2, "0") + "\u6708";
  }

  function dateToValue(value) {
    return [
      value.getFullYear(),
      String(value.getMonth() + 1).padStart(2, "0"),
      String(value.getDate()).padStart(2, "0")
    ].join("-");
  }

  function renderPagination(payload) {
    state.page = payload.page || 1;
    state.page_size = normalizePageSize(payload.page_size || state.page_size);
    elements.pageSizeSelect.value = String(state.page_size);
    elements.paginationInfo.textContent = text.totalPrefix + formatNumber(payload.total || 0) + text.totalMiddle + state.page + " / " + (payload.total_pages || 1) + text.totalSuffix;
    elements.prevPageBtn.disabled = state.page <= 1;
    elements.nextPageBtn.disabled = state.page >= (payload.total_pages || 1);
    elements.paginationNumbers.innerHTML = '<span>' + state.page + '</span>';
  }

  function writeQuery() {
    var params = new URLSearchParams();
    Object.keys(state).forEach(function (key) {
      var value = state[key];
      if (value == null || value === "" || value === "all") return;
      params.set(key, String(value));
    });
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? "?" + params.toString() : ""));
  }

  function normalizePageSize(value) {
    var pageSize = Number(value || 20);
    if (pageSize <= 20) return 20;
    if (pageSize <= 50) return 50;
    return 100;
  }

  function formatNumber(value, digits) {
    var options = { maximumFractionDigits: typeof digits === "number" ? digits : 2 };
    if (typeof digits === "number") options.minimumFractionDigits = digits;
    return Number(value || 0).toLocaleString("zh-CN", options);
  }

  function formatCurrency(value) {
    return "\u00a5" + Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function signedCurrency(value) {
    var amount = Number(value || 0);
    return (amount > 0 ? "+" : "") + formatCurrency(amount);
  }

  function signedNumber(value) {
    var amount = Number(value || 0);
    return (amount > 0 ? "+" : "") + amount.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  function flowTypeLabel(value) {
    if (value === "\u65b0\u589e") return text.flowNew;
    if (value === "\u6d41\u5165") return text.flowIn;
    if (value === "\u6d41\u51fa") return text.flowOut;
    if (value === "\u9000\u51fa") return text.flowExit;
    if (value === "\u4fdd\u6301") return text.flowStay;
    return text.flowDetail;
  }

  function formatPercent(value) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      style: "percent"
    });
  }

  function layerGlyph(sort) {
    var key = Number(sort || 0);
    if (key === 1) return "\u6025";
    if (key === 2) return "\u5efa";
    if (key === 3) return "\u8ba1";
    if (key === 4) return "\u8db3";
    if (key === 5) return "0";
    if (key === 6) return "\u53f2";
    return "-";
  }
})();
