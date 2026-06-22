(function () {
  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var LEVEL_ALL = "\u5168\u90e8";
  var LEVEL_URGENT = "\u7d27\u6025\u8865\u8d27";
  var LEVEL_SUGGESTED = "\u5efa\u8bae\u8865\u8d27";
  var LEVEL_PLANNED = "\u8ba1\u5212\u8865\u8d27";
  var LEVEL_SUFFICIENT = "\u5e93\u5b58\u5145\u8db3";
  var LEVEL_ZERO_SALES = "\u65e5\u9500\u4e3a0";
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
    skuCount: "\u57fa\u7840\u6c60 MSKU",
    detailRows: "\u660e\u7ec6\u884c\u6570",
    calcMsku: "\u8fdb\u5165\u8865\u8d27\u8ba1\u7b97",
    replenishQty: "\u8865\u8d27\u6570\u91cf",
    avgSupportDays: "\u5e73\u5747\u652f\u6491\u5929\u6570",
    actionLayers: "\u8865\u8d27\u5206\u5c42",
    basePool: "\u57fa\u7840\u6c60\u5206\u5e03",
    layerRank: "\u5c42\u7ea7",
    allMsku: "\u5168\u91cf MSKU",
    calcQty: "\u9700\u8865 SKU",
    all: LEVEL_ALL,
    level: "\u5c42\u7ea7",
    store: "\u5e97\u94fa",
    site: "\u7ad9\u70b9",
    dailySales: "\u65e5\u9500",
    supportDays: "\u652f\u6491\u5929\u6570",
    available: "\u53ef\u7528",
    inTransit: "\u5728\u9014",
    local: "\u672c\u5730",
    sales30d: "30\u5929\u9500\u91cf",
    needQty: "\u9700\u6c42\u91cf",
    boxQty: "\u7bb1\u6570",
    stockoutStatus: "\u7f3a\u8d27\u72b6\u6001",
    skuInfo: "SKU \u4fe1\u606f",
    replenishAdvice: "\u8865\u8d27\u5efa\u8bae",
    inventoryStructure: "\u5e93\u5b58\u7ed3\u6784",
    salesSupport: "\u9500\u552e\u652f\u6491",
    category: "\u4ea7\u54c1\u5206\u7c7b",
    margin: "\u5229\u6da6\u7387",
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
    sort_field: query.get("sort_field") || "",
    sort_dir: query.get("sort_dir") || "",
    page: Number(query.get("page") || 1),
    page_size: 20
  };
  var elements = {};
  var meta = null;
  var token = 0;
  var datePickerMonth = null;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "datePickerBtn", "datePickerValue", "datePickerPanel", "levelSelect", "siteSelect", "storeSelect", "keywordInput", "clearFiltersBtn",
      "periodHint", "summaryGrid", "layerVizGrid", "levelTabs", "tableWrap", "paginationInfo", "paginationNumbers",
      "prevPageBtn", "nextPageBtn", "sortQtyBtn", "sortSupportBtn", "exportReplenishmentBtn"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
    bindEvents();
    render();
  }

  function bindEvents() {
    [
      ["levelSelect", "level"],
      ["siteSelect", "site"],
      ["storeSelect", "store"]
    ].forEach(function (pair) {
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = this.value;
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
      if (event.key === "Escape") closeDatePicker();
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
      state.sort_field = "";
      state.sort_dir = "";
      state.page = 1;
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
    elements.exportReplenishmentBtn.addEventListener("click", exportReplenishment);
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
    elements.siteSelect.value = state.site || "all";
    elements.storeSelect.value = state.store || "all";
    elements.keywordInput.value = state.keyword || "";
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
      [text.skuCount, formatNumber(s.all_msku_count || s.sku_count), "context", "\u6c60", "\u5f53\u65e5\u57fa\u7840\u6c60"],
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
          '<span class="layer-name"><span class="layer-title"><span>' + app.escapeHtml(level) + '</span>' + renderLevelHelp(level) + '</span><small>' + formatNumber(row.sku_count) + ' MSKU</small>' + renderCategoryMix(row.category_mix, row.sku_count, level) + '</span>',
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
          '<span>' + app.escapeHtml(row.level || "") + '</span>',
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
        state.level = this.dataset.level || "all";
        state.category = this.dataset.category || "all";
        state.page = 1;
        render();
      });
    });
    Array.from(elements.layerVizGrid.querySelectorAll("[data-level]:not([data-category])")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.level = this.dataset.level || "all";
        state.category = "all";
        state.page = 1;
        render();
      });
      node.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        state.level = this.dataset.level || "all";
        state.category = "all";
        state.page = 1;
        render();
      });
    });
  }

  function renderLevelHelp(level) {
    var lines = LEVEL_HELP[level] || [];
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
    var items = (rows || []).filter(function (row) { return Number(row.sku_count || 0) > 0; });
    if (!items.length) return "";
    var denominator = Number(total || 0) || items.reduce(function (sum, row) {
      return sum + Number(row.sku_count || 0);
    }, 0) || 1;
    return '<span class="layer-category-mix">' + items.map(function (row) {
      var count = Number(row.sku_count || 0);
      var category = row.category || "-";
      var active = state.level === level && state.category === category ? " active" : "";
      return '<button type="button" class="' + active + '" data-level="' + app.escapeHtml(level || "all") + '" data-category="' + app.escapeHtml(category) + '">' + app.escapeHtml(category) + ' ' + formatNumber(count) + '<b>' + formatPercent(count / denominator) + '</b></button>';
    }).join("") + '</span>';
  }

  function renderTabs(payload) {
    var rows = payload.level_summary || [];
    var allButton = '<button type="button" class="' + (state.level === "all" ? "active" : "") + '" data-level="all">' + text.all + '</button>';
    elements.levelTabs.innerHTML = [allButton].concat(rows.map(function (row) {
      return '<button type="button" class="' + (state.level === row.level ? "active" : "") + '" data-level="' + app.escapeHtml(row.level) + '">' + app.escapeHtml(row.level) + ' &middot; ' + formatNumber(row.sku_count) + '</button>';
    })).join("");
    Array.from(elements.levelTabs.querySelectorAll("[data-level]")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.level = this.dataset.level || "all";
        state.category = "all";
        state.page = 1;
        render();
      });
    });
  }

  function renderTable(payload) {
    var rows = payload.items || [];
    if (!rows.length) {
      elements.tableWrap.innerHTML = '<div class="empty-state compact">' + text.noRows + '</div>';
      return;
    }
    elements.tableWrap.innerHTML = '<div id="replenishmentAgGrid"></div>';
    window.kanbanGrid.makeGrid("replenishmentAgGrid", {
      rowData: rows,
      rowHeight: 58,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">' + app.escapeHtml(text.noRows) + '</span>',
      onFilterChanged: handleGridFilterChanged,
      columnDefs: [
        { headerName: text.level, field: "level", pinned: "left", width: 118, sort: colSort("level"), cellRenderer: function (params) { return '<span class="status-pill level-' + app.escapeHtml(String((params.data || {}).level_sort || "")) + '">' + app.escapeHtml(params.value || "") + '</span>'; } },
        { headerName: "MSKU / SKU", field: "msku", pinned: "left", width: 150, sort: colSort("msku"), cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.msku || "-", params.data.sku || ""); } },
        { headerName: text.store, field: "store", width: 130, sort: colSort("store") },
        { headerName: text.site, field: "country", width: 110, sort: colSort("country") },
        numberColumn(text.dailySales, "daily_sales", 112, 2),
        numberColumn("30\u5929\u53ef\u552e\u65e5\u9500", "category_daily_sales_30d", 132, 2),
        { headerName: "30\u5929\u6bdb\u5229\u7387", field: "profit_rate_30d", width: 120, type: "numericColumn", sort: colSort("profit_rate_30d"), cellRenderer: function (params) { return window.kanbanGrid.percent(params.value, 2); } },
        { headerName: text.category, field: "category", width: 118, sort: colSort("category") },
        numberColumn(text.supportDays, "support_days", 118, 2),
        numberColumn(text.available, "available_total", 104, 0),
        numberColumn(text.inTransit, "stock_up_num", 104, 0),
        numberColumn(text.local, "local_quantity", 104, 0),
        numberColumn(text.sales30d, "sales_30d", 110, 0),
        numberColumn(text.needQty, "need_qty", 120, 2),
        numberColumn(text.replenishQty, "replenish_qty", 122, 0),
        numberColumn(text.boxQty, "box_qty", 96, 0),
        { headerName: text.replenishValue, field: "cost", width: 132, type: "numericColumn", sort: colSort("cost"), cellRenderer: function (params) { return formatCurrency(params.value); } },
        { headerName: text.stockoutStatus, field: "stockout_status", width: 126, sort: colSort("stockout_status") },
        { headerName: text.margin, field: "margin_range", width: 118, sort: colSort("margin_range") }
      ],
      onSortChanged: handleGridSortChanged
    });
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
    ["snapshot_date", "level", "category", "site", "store", "keyword", "sort_field", "sort_dir"].forEach(function (key) {
      var value = state[key];
      if (value !== undefined && value !== null && value !== "" && value !== "all") params.set(key, value);
    });
    window.location.href = "/api/replenishment/export" + (params.toString() ? ("?" + params.toString()) : "");
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

  function formatNumber(value, digits) {
    var options = { maximumFractionDigits: typeof digits === "number" ? digits : 2 };
    if (typeof digits === "number") options.minimumFractionDigits = digits;
    return Number(value || 0).toLocaleString("zh-CN", options);
  }

  function formatCurrency(value) {
    return "\u00a5" + Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
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
    return "-";
  }
})();
