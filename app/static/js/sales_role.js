(function () {
  "use strict";

  var app = window.kanbanApp;
  var state = Object.assign({
    view: "role",
    period: "30d",
    country_category: "all",
    seller_name_new: "all",
    sales_role: "all",
    lifecycle_label: "all",
    daily_sales_band: "all",
    margin_band: "all",
    keyword: "",
    page: 1,
    page_size: 20,
    sort_field: "sales_amount",
    sort_dir: "desc"
  }, readInitialState());
  var meta = null;
  var elements = {};
  var renderToken = 0;
  var pendingDetailFocus = false;
  var ROLE_RULES = {
    star: "日销 > 5 且毛利率 > 15%；或日销 1-5 且毛利率 > 25%。",
    potential: "日销 > 5 且毛利率 5%-15%；或日销 1-5 且毛利率 10%-25%。",
    incubation: "日销 1-5 且毛利率 5%-10%；或日销 < 1 且毛利率 > 5%。",
    eliminate: "日销为 0；或日销 > 0 且毛利率 < 5%；或毛利率为空、未命中以上规则。"
  };

  document.addEventListener("DOMContentLoaded", init);

  function readInitialState() {
    var params = new URLSearchParams(window.location.search);
    return {
      view: params.get("view") || "role",
      period: params.get("period") || "30d",
      country_category: params.get("country_category") || "all",
      seller_name_new: params.get("seller_name_new") || "all",
      sales_role: params.get("sales_role") || "all",
      lifecycle_label: params.get("lifecycle_label") || "all",
      daily_sales_band: params.get("daily_sales_band") || "all",
      margin_band: params.get("margin_band") || "all",
      keyword: params.get("keyword") || "",
      page: Number(params.get("page") || 1),
      page_size: Number(params.get("page_size") || 20),
      sort_field: params.get("sort_field") || "sales_amount",
      sort_dir: params.get("sort_dir") || "desc"
    };
  }

  function init() {
    cacheElements();
    bindEvents();
    app.apiGet("/api/sales-role/meta").then(function (payload) {
      meta = payload;
      if (!state.period) state.period = payload.default_period || "30d";
      populateFilters();
      syncControls();
      render();
    });
  }

  function cacheElements() {
    [
      "viewToggle", "periodButtons", "countryCategorySelect", "sellerNameSelect", "salesRoleSelect",
      "lifecycleField", "lifecycleSelect", "keywordInput", "clearFiltersBtn", "activeFilterChips",
      "exportBtn", "summaryHint", "summaryGrid", "roleGrid", "matrixGrid", "tableSummary", "tableWrap",
      "pagination", "summaryPanelKicker", "summaryPanelTitle", "distributionKicker", "distributionTitle",
      "matrixKicker", "matrixTitle", "detailKicker", "detailTitle"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
    elements.detailPanel = document.querySelector(".detail-panel");
  }

  function bindEvents() {
    elements.viewToggle.addEventListener("click", function (event) {
      var button = event.target.closest("[data-view]");
      if (!button || button.dataset.view === state.view) return;
      state.view = button.dataset.view;
      state.page = 1;
      state.page_size = 20;
      state.daily_sales_band = "all";
      state.margin_band = "all";
      state.lifecycle_label = "all";
      state.sort_field = "sales_amount";
      state.sort_dir = "desc";
      syncControls();
      render();
    });
    elements.periodButtons.addEventListener("click", function (event) {
      var button = event.target.closest("[data-period]");
      if (!button) return;
      state.period = button.dataset.period;
      state.page = 1;
      syncControls();
      render();
    });
    [
      ["countryCategorySelect", "country_category"],
      ["sellerNameSelect", "seller_name_new"],
      ["salesRoleSelect", "sales_role"],
      ["lifecycleSelect", "lifecycle_label"]
    ].forEach(function (pair) {
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = this.value;
        state.page = 1;
        syncControls();
        render();
      });
    });
    elements.keywordInput.addEventListener("input", function () {
      state.keyword = this.value.trim();
      state.page = 1;
      syncControls();
      render();
    });
    elements.clearFiltersBtn.addEventListener("click", function () {
      var currentView = state.view;
      state.period = (meta && meta.default_period) || "30d";
      state.country_category = "all";
      state.seller_name_new = "all";
      state.sales_role = "all";
      state.lifecycle_label = "all";
      state.daily_sales_band = "all";
      state.margin_band = "all";
      state.keyword = "";
      state.page = 1;
      state.page_size = 20;
      state.sort_field = "sales_amount";
      state.sort_dir = "desc";
      state.view = currentView;
      syncControls();
      render();
    });
    elements.exportBtn.addEventListener("click", exportCsv);
    document.addEventListener("click", handleBlankClear);
  }

  function populateFilters() {
    elements.periodButtons.innerHTML = (meta.periods || []).map(function (period) {
      return '<button class="sales-role-period-button" type="button" data-period="' + app.escapeHtml(period.key) + '">' + app.escapeHtml(period.label) + "</button>";
    }).join("");
    app.setSelectOptions(elements.countryCategorySelect, meta.country_categories || [], "全部国家类别");
    app.setSelectOptions(elements.sellerNameSelect, meta.stores || [], "全部店铺");
    elements.salesRoleSelect.innerHTML = ['<option value="all">全部销售角色</option>'].concat((meta.roles || []).map(function (role) {
      return '<option value="' + app.escapeHtml(role.key) + '">' + app.escapeHtml(role.label) + "</option>";
    })).join("");
    elements.lifecycleSelect.innerHTML = ['<option value="all">全部生命周期</option>'].concat((meta.lifecycle_labels || []).map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + "</option>";
    })).join("");
  }

  function syncControls() {
    Array.from(elements.viewToggle.querySelectorAll("[data-view]")).forEach(function (button) {
      button.classList.toggle("active", button.dataset.view === state.view);
    });
    Array.from(elements.periodButtons.querySelectorAll("[data-period]")).forEach(function (button) {
      button.classList.toggle("active", button.dataset.period === state.period);
    });
    elements.lifecycleField.hidden = state.view !== "lifecycle";
    elements.countryCategorySelect.value = state.country_category;
    elements.sellerNameSelect.value = state.seller_name_new;
    elements.salesRoleSelect.value = state.sales_role;
    elements.lifecycleSelect.value = state.lifecycle_label;
    elements.keywordInput.value = state.keyword;
    updateHeadings();
    renderChips();
  }

  function updateHeadings() {
    var lifecycle = state.view === "lifecycle";
    elements.summaryPanelKicker.textContent = "核心概览";
    elements.summaryPanelTitle.textContent = lifecycle ? "生命周期经营规模" : "经营规模";
    elements.distributionKicker.textContent = lifecycle ? "生命周期分布" : "角色分布";
    elements.distributionTitle.textContent = lifecycle ? "五类生命周期" : "四类销售角色";
    elements.matrixKicker.textContent = "二维矩阵";
    elements.matrixTitle.textContent = lifecycle ? "生命周期 × 销售角色" : "日销 × 毛利率";
    elements.detailKicker.textContent = "明细清单";
    elements.detailTitle.textContent = lifecycle ? "MSKU 生命周期明细" : "MSKU 销售角色明细";
  }

  function renderChips() {
    var chips = [(state.view === "lifecycle" ? "视图：生命周期" : "视图：销售角色"), "周期：" + periodLabel(state.period)];
    if (state.country_category !== "all") chips.push("国家类别：" + state.country_category);
    if (state.seller_name_new !== "all") chips.push("店铺：" + state.seller_name_new);
    if (state.sales_role !== "all") chips.push("销售角色：" + roleLabel(state.sales_role));
    if (state.lifecycle_label !== "all") chips.push("生命周期：" + lifecycleLabel(state.lifecycle_label));
    if (state.daily_sales_band !== "all") chips.push("日销：" + state.daily_sales_band);
    if (state.margin_band !== "all") chips.push("毛利率：" + state.margin_band);
    if (state.keyword) chips.push("关键词：" + state.keyword);
    elements.activeFilterChips.innerHTML = chips.map(function (chip) {
      return '<span class="sales-role-chip">' + app.escapeHtml(chip) + "</span>";
    }).join("");
  }

  function render() {
    var token = ++renderToken;
    setLoading(true);
    app.writeQueryState(state);
    app.apiGet(apiUrl(), requestParams()).then(function (payload) {
      if (token !== renderToken) return;
      renderSummary(payload);
      if (state.view === "lifecycle") {
        renderLifecycleCards(payload.lifecycle_distribution || []);
        renderLifecycleMatrix(payload.lifecycle_role_matrix || {});
      } else {
        renderRoles(payload.roles || []);
        renderSalesRoleMatrix(payload.matrix || {});
      }
      renderTable(payload);
      renderPagination(payload);
      if (pendingDetailFocus) {
        pendingDetailFocus = false;
        focusDetailPanel();
      }
    }).catch(function (error) {
      console.error(error);
    }).then(function () {
      if (token === renderToken) setLoading(false);
    });
  }

  function apiUrl() {
    return state.view === "lifecycle" ? "/api/sales-role/lifecycle" : "/api/sales-role";
  }

  function requestParams() {
    if (state.view === "lifecycle") {
      return {
        period: state.period,
        country_category: state.country_category,
        seller_name_new: state.seller_name_new,
        lifecycle_label: state.lifecycle_label,
        sales_role: state.sales_role,
        keyword: state.keyword,
        page: state.page,
        page_size: state.page_size,
        sort_field: state.sort_field,
        sort_dir: state.sort_dir
      };
    }
    return state;
  }

  function setLoading(isLoading) {
    var main = document.querySelector(".main-content");
    if (main) main.classList.toggle("page-loading", isLoading);
  }

  function renderSummary(payload) {
    var summary = payload.summary || {};
    if (state.view === "lifecycle") {
      elements.summaryHint.textContent = (payload.window && payload.window.label ? payload.window.label : "暂无生命周期标签数据") + "；销售角色周期：" + periodLabel(state.period);
      renderSummaryCards([
        ["总 MSKU 数", formatNumber(summary.sku_count), "primary"],
        ["销售额", app.formatCompactCurrency(summary.sales_amount || 0), "revenue"],
        ["销量", formatNumber(summary.sales_qty), "quantity"],
        ["订单毛利润", app.formatCompactCurrency(summary.order_gross_profit || 0), "value"],
        ["订单毛利率", app.formatPercent(summary.order_gross_margin || 0), "margin"],
        ["动销 MSKU", formatNumber(summary.active_sku_count), "context"],
        ["成熟期 MSKU", formatNumber(summary.mature_count), "context"],
        ["问题产品", formatNumber(summary.problem_count), "negative"]
      ]);
      return;
    }

    var windowText = payload.window ? payload.window.label : "暂无数据";
    elements.summaryHint.textContent = "统计窗口：" + windowText;
    renderSummaryCards([
      ["总 MSKU 数", formatNumber(summary.sku_count), "primary"],
      ["销售额", app.formatCompactCurrency(summary.sales_amount || 0), "revenue"],
      ["销量", formatNumber(summary.sales_qty), "quantity"],
      ["订单毛利润", app.formatCompactCurrency(summary.order_gross_profit || 0), "value"],
      ["订单毛利率", app.formatPercent(summary.order_gross_margin || 0), "margin"],
      ["动销 MSKU", formatNumber(summary.active_sku_count), "context"],
      ["问题产品", formatNumber(summary.eliminate_count), "negative"]
    ]);
  }

  function renderSummaryCards(cards) {
    elements.summaryGrid.innerHTML = cards.map(function (card) {
      return '<div class="sales-role-kpi ' + card[2] + '"><span>' + app.escapeHtml(card[0]) + '</span><strong>' + app.escapeHtml(card[1]) + "</strong></div>";
    }).join("");
  }

  function renderRoles(rows) {
    elements.roleGrid.innerHTML = rows.map(function (row) {
      var active = state.sales_role === row.key ? " active" : "";
      var rule = ROLE_RULES[row.key] || "";
      return [
        '<button type="button" class="sales-role-card ' + app.escapeHtml(row.tone || "neutral") + active + '" data-role="' + app.escapeHtml(row.key) + '">',
        '<span class="sales-role-card-title">' + app.escapeHtml(row.label),
        rule ? '<i class="sales-role-rule-help" tabindex="0" aria-label="' + app.escapeHtml(row.label + "规则") + '">?<b role="tooltip">' + app.escapeHtml(rule) + '</b></i>' : "",
        '</span>',
        '<strong>' + formatNumber(row.count || 0) + '</strong>',
        '<small>占比 ' + app.formatPercent(row.ratio || 0) + ' · 销售额 ' + app.formatCompactCurrency(row.sales_amount || 0) + '</small>',
        '<small>毛利率 ' + app.formatPercent(row.order_gross_margin || 0) + ' · 日均销量 ' + formatNumber(row.daily_sales || 0) + '</small>',
        '</button>'
      ].join("");
    }).join("");
    bindRoleCards();
  }

  function renderLifecycleCards(rows) {
    elements.roleGrid.innerHTML = rows.map(function (row) {
      var active = state.lifecycle_label === row.key ? " active" : "";
      var rule = row.rule || row.definition || "";
      return [
        '<button type="button" class="sales-role-card lifecycle-card ' + app.escapeHtml(row.tone || "neutral") + active + '" data-lifecycle="' + app.escapeHtml(row.key) + '">',
        '<span class="sales-role-card-title">' + app.escapeHtml(row.label),
        rule ? '<i class="sales-role-rule-help" tabindex="0" aria-label="' + app.escapeHtml(row.label + "规则") + '">?<b role="tooltip">' + app.escapeHtml(rule) + '</b></i>' : "",
        '</span>',
        '<strong>' + formatNumber(row.count || 0) + '</strong>',
        '<small>占比 ' + app.formatPercent(row.ratio || 0) + ' · 销售额 ' + app.formatCompactCurrency(row.sales_amount || 0) + '</small>',
        '<small>订单毛利率 ' + app.formatPercent(row.order_gross_margin || 0) + ' · 日均销量 ' + formatNumber(row.daily_sales || 0) + '</small>',
        '<small>上架天数 ' + app.escapeHtml(row.label_period || "") + '</small>',
        '</button>'
      ].join("");
    }).join("");
    Array.from(elements.roleGrid.querySelectorAll("[data-lifecycle]")).forEach(function (button) {
      button.addEventListener("click", function () {
        state.lifecycle_label = state.lifecycle_label === this.dataset.lifecycle ? "all" : this.dataset.lifecycle;
        state.page = 1;
        state.page_size = 5000;
        pendingDetailFocus = true;
        syncControls();
        render();
      });
    });
  }

  function bindRoleCards() {
    Array.from(elements.roleGrid.querySelectorAll("[data-role]")).forEach(function (button) {
      button.addEventListener("click", function () {
        state.sales_role = state.sales_role === this.dataset.role ? "all" : this.dataset.role;
        state.page = 1;
        state.page_size = 5000;
        pendingDetailFocus = true;
        syncControls();
        render();
      });
    });
  }

  function renderSalesRoleMatrix(matrix) {
    renderMatrixShell({
      total: Number(matrix.total || 0),
      copy: "按毛利率与日销分层统计当前筛选范围内的 MSKU 数量及占比，点击单元格筛选下方明细。",
      rows: matrix.margin_bands || [],
      cols: matrix.daily_sales_bands || [],
      rowLabel: "毛利率",
      colLabel: "日销分层",
      cellKey: function (cell) { return cell.margin_band + "|" + cell.daily_sales_band; },
      cellLookupKey: function (row, col) { return row + "|" + col; },
      rowDescription: marginBandDescription,
      colDescription: dailyBandDescription,
      active: function (row, col) { return state.margin_band === row && state.daily_sales_band === col; },
      onClickAttrs: function (row, col) { return ' data-margin="' + app.escapeHtml(row) + '" data-daily="' + app.escapeHtml(col) + '"'; },
      bindSelector: "[data-daily]",
      onBind: function (button) {
        var same = state.daily_sales_band === button.dataset.daily && state.margin_band === button.dataset.margin;
        state.daily_sales_band = same ? "all" : button.dataset.daily;
        state.margin_band = same ? "all" : button.dataset.margin;
      },
      cells: matrix.cells || []
    });
  }

  function renderLifecycleMatrix(matrix) {
    var labels = matrix.lifecycle_labels || [];
    var roles = matrix.roles || [];
    renderMatrixShell({
      total: Number(matrix.total || 0),
      copy: "按当前生命周期标签与销售角色交叉统计，销售角色跟随顶部周期。点击单元格筛选下方明细。",
      rows: labels.map(function (item) { return item.key; }),
      cols: roles.map(function (item) { return item.key; }),
      rowLabel: "生命周期",
      colLabel: "销售角色",
      cellKey: function (cell) { return String(cell.lifecycle_label_id) + "|" + cell.sales_role_code; },
      cellLookupKey: function (row, col) { return row + "|" + col; },
      rowTitle: lifecycleLabel,
      colTitle: roleLabel,
      rowDescription: lifecyclePeriod,
      colDescription: roleShortDescription,
      active: function (row, col) { return state.lifecycle_label === row && state.sales_role === col; },
      onClickAttrs: function (row, col) { return ' data-lifecycle="' + app.escapeHtml(row) + '" data-role="' + app.escapeHtml(col) + '"'; },
      bindSelector: "[data-lifecycle][data-role]",
      onBind: function (button) {
        var same = state.lifecycle_label === button.dataset.lifecycle && state.sales_role === button.dataset.role;
        state.lifecycle_label = same ? "all" : button.dataset.lifecycle;
        state.sales_role = same ? "all" : button.dataset.role;
      },
      cells: matrix.cells || []
    });
  }

  function renderMatrixShell(config) {
    var cells = {};
    (config.cells || []).forEach(function (cell) {
      cells[config.cellKey(cell)] = cell;
    });
    var html = [
      '<div class="sales-role-matrix-shell">',
      '<div class="sales-role-matrix-toolbar">',
      '<div><strong>' + formatNumber(config.total || 0) + '</strong><span>MSKU组合 · 点击矩阵筛选明细</span></div>',
      '<div class="sales-role-matrix-legend"><span>数量占比</span><i class="level-0"></i><b>&lt; 2%</b><i class="level-1"></i><b>2%-5%</b><i class="level-2"></i><b>5%-10%</b><i class="level-3"></i><b>10%-15%</b><i class="level-4"></i><b>&gt; 15%</b></div>',
      '</div>',
      '<p class="sales-role-matrix-copy">' + app.escapeHtml(config.copy) + '</p>',
      '<div class="sales-role-matrix-grid" style="grid-template-columns: 136px repeat(' + config.cols.length + ', minmax(150px, 1fr));">',
      '<span class="matrix-corner"><small>' + app.escapeHtml(config.rowLabel) + '<br>' + app.escapeHtml(config.colLabel) + '</small></span>'
    ];
    config.cols.forEach(function (col) {
      html.push('<span class="matrix-head"><b>' + app.escapeHtml(titleFor(config, "col", col)) + '</b><small>' + app.escapeHtml(config.colDescription ? config.colDescription(col) : "") + '</small></span>');
    });
    config.rows.forEach(function (row) {
      html.push('<span class="matrix-role"><b>' + app.escapeHtml(titleFor(config, "row", row)) + '</b><small>' + app.escapeHtml(config.rowDescription ? config.rowDescription(row) : "") + '</small></span>');
      config.cols.forEach(function (col) {
        var cell = cells[config.cellLookupKey(row, col)] || { count: 0, ratio: 0, sales_amount: 0 };
        var active = config.active(row, col) ? " active" : "";
        var ratio = Number(cell.ratio || 0);
        var level = matrixRatioLevel(ratio);
        var empty = Number(cell.count || 0) === 0 ? " empty" : "";
        html.push([
          '<button type="button" class="matrix-cell level-' + level + active + empty + '"' + config.onClickAttrs(row, col) + '>',
          '<strong>' + formatNumber(cell.count || 0) + '</strong>',
          '<span>' + (config.total ? app.formatPercent(ratio, 1) : "0%") + '</span>',
          '<small>' + app.formatCompactCurrency(cell.sales_amount || 0) + '</small>',
          '</button>'
        ].join(""));
      });
    });
    html.push('</div></div>');
    elements.matrixGrid.innerHTML = html.join("");
    Array.from(elements.matrixGrid.querySelectorAll(config.bindSelector)).forEach(function (button) {
      button.addEventListener("click", function () {
        config.onBind(this);
        state.page = 1;
        state.page_size = 5000;
        pendingDetailFocus = true;
        syncControls();
        render();
      });
    });
  }

  function titleFor(config, axis, key) {
    if (axis === "row" && config.rowTitle) return config.rowTitle(key);
    if (axis === "col" && config.colTitle) return config.colTitle(key);
    return key;
  }

  function renderTable(payload) {
    elements.tableSummary.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + payload.total + " 条";
    window.kanbanGrid.makeGrid("tableWrap", {
      rowData: payload.rows || [],
      domLayout: "normal",
      rowHeight: 48,
      headerHeight: 50,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前筛选条件下没有明细。</span>',
      columnDefs: state.view === "lifecycle" ? lifecycleColumns() : salesRoleColumns(),
      onSortChanged: function (event) {
        var sorted = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
        state.sort_field = sorted ? sorted.colId : "sales_amount";
        state.sort_dir = sorted ? sorted.sort : "desc";
        state.page = 1;
        render();
      },
      onCellClicked: function (event) {
        if (event.column && event.column.getColId() === "label_hub") viewLabelHub(event.data);
      }
    });
  }

  function viewLabelHub(row) {
    if (!row) return;
    var params = new URLSearchParams({
      country_category: row.country_category || "all",
      store: row.seller_name_new || "all",
      keyword: row.seller_sku_adj || ""
    });
    var href;
    href = "/label-hub?" + params.toString();
    window.location.href = href;
  }

  function salesRoleColumns() {
    return [
      { headerName: "销售角色", field: "sales_role", pinned: "left", width: 116, sort: colSort("sales_role") },
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 116, sort: colSort("country_category") },
      { headerName: "店铺新", field: "seller_name_new", pinned: "left", width: 128, sort: colSort("seller_name_new") },
      { headerName: "MSKU", field: "seller_sku_adj", pinned: "left", width: 130, sort: colSort("seller_sku_adj") },
      { headerName: "SKU示例", field: "local_sku_sample", width: 128 },
      { headerName: "覆盖国家数", field: "country_count", width: 118, sort: colSort("country_count"), cellClass: "ag-grid-number-cell" },
      { headerName: "销量", field: "sales_qty", width: 104, sort: colSort("sales_qty"), cellClass: "ag-grid-number-cell" },
      { headerName: "日均销量", field: "daily_sales", width: 116, sort: colSort("daily_sales"), cellClass: "ag-grid-number-cell" },
      { headerName: "销售额", field: "sales_amount", width: 126, sort: colSort("sales_amount"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "订单毛利润", field: "order_gross_profit", width: 128, sort: colSort("order_gross_profit"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "订单毛利率", field: "order_gross_margin", width: 126, sort: colSort("order_gross_margin"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter },
      { headerName: "日销分层", field: "daily_sales_band", width: 116, sort: colSort("daily_sales_band") },
      { headerName: "毛利率分层", field: "margin_band", width: 116, sort: colSort("margin_band") },
      { headerName: "广告花费", field: "ad_spend", width: 118, sort: colSort("ad_spend"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "广告销售额", field: "ad_sales", width: 126, sort: colSort("ad_sales"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "ACOS", field: "acos", width: 96, sort: colSort("acos"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter },
      { headerName: "TACOS", field: "tacos", width: 96, sort: colSort("tacos"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter }
      , { headerName: "标签", colId: "label_hub", width: 108, cellRenderer: function () { return window.kanbanGrid.action("查看全部标签"); } }
    ];
  }

  function lifecycleColumns() {
    return [
      { headerName: "生命周期", field: "lifecycle_label", pinned: "left", width: 116, sort: colSort("lifecycle_label") },
      { headerName: "销售角色", field: "sales_role", pinned: "left", width: 116, sort: colSort("sales_role") },
      { headerName: "国家类别", field: "country_category", pinned: "left", width: 116, sort: colSort("country_category") },
      { headerName: "店铺", field: "seller_name_new", pinned: "left", width: 128, sort: colSort("seller_name_new") },
      { headerName: "MSKU", field: "seller_sku_adj", pinned: "left", width: 130, sort: colSort("seller_sku_adj") },
      { headerName: "SKU示例", field: "local_sku_sample", width: 128 },
      { headerName: "销量", field: "sales_qty", width: 104, sort: colSort("sales_qty"), cellClass: "ag-grid-number-cell" },
      { headerName: "日均销量", field: "daily_sales", width: 116, sort: colSort("daily_sales"), cellClass: "ag-grid-number-cell" },
      { headerName: "销售额", field: "sales_amount", width: 126, sort: colSort("sales_amount"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "订单毛利润", field: "order_gross_profit", width: 128, sort: colSort("order_gross_profit"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
      { headerName: "订单毛利率", field: "order_gross_margin", width: 126, sort: colSort("order_gross_margin"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter },
      { headerName: "上架天数", field: "label_period", width: 128, sort: colSort("label_period") },
      { headerName: "销售角色周期", field: "sales_role_period", width: 128, sort: colSort("sales_role_period") }
      , { headerName: "标签", colId: "label_hub", width: 108, cellRenderer: function () { return window.kanbanGrid.action("查看全部标签"); } }
    ];
  }

  function renderPagination(payload) {
    var prevDisabled = payload.page <= 1 ? " disabled" : "";
    var nextDisabled = payload.page >= payload.total_pages ? " disabled" : "";
    var pageSize = Number(payload.page_size || state.page_size || 20);
    elements.pagination.innerHTML = [
      '<label class="sales-role-page-size">每页 <select data-page-size>',
      [20, 50, 100, 5000].map(function (size) {
        var label = size === 5000 ? "全部" : size;
        return '<option value="' + size + '"' + (pageSize === size ? " selected" : "") + '>' + label + '</option>';
      }).join(""),
      '</select> 条</label>',
      '<button type="button" data-page="' + (payload.page - 1) + '"' + prevDisabled + '>上一页</button>',
      '<span>第 ' + payload.page + ' / ' + payload.total_pages + ' 页</span>',
      '<button type="button" data-page="' + (payload.page + 1) + '"' + nextDisabled + '>下一页</button>'
    ].join("");
    var pageSizeSelect = elements.pagination.querySelector("[data-page-size]");
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener("change", function () {
        state.page_size = Number(this.value || 20);
        state.page = 1;
        render();
      });
    }
    Array.from(elements.pagination.querySelectorAll("[data-page]")).forEach(function (button) {
      button.addEventListener("click", function () {
        if (this.disabled) return;
        state.page = Number(this.dataset.page);
        render();
      });
    });
  }

  function colSort(field) {
    return state.sort_field === field ? state.sort_dir : null;
  }

  function moneyFormatter(params) {
    return app.formatCompactCurrency(params.value || 0);
  }

  function percentFormatter(params) {
    return app.formatPercent(params.value || 0);
  }

  function hasLinkedFilter() {
    if (state.view === "lifecycle") {
      return state.lifecycle_label !== "all" || state.sales_role !== "all";
    }
    return state.sales_role !== "all" || state.daily_sales_band !== "all" || state.margin_band !== "all";
  }

  function clearLinkedFilters() {
    if (!hasLinkedFilter()) return false;
    state.sales_role = "all";
    state.lifecycle_label = "all";
    state.daily_sales_band = "all";
    state.margin_band = "all";
    state.page = 1;
    syncControls();
    render();
    return true;
  }

  function handleBlankClear(event) {
    if (!hasLinkedFilter()) return;
    if (!event.target.closest(".sales-role-page")) return;
    if (event.target.closest("button, a, input, select, textarea, .sales-role-filter-panel, .sales-role-topbar, .detail-panel, .ag-popup")) return;
    clearLinkedFilters();
  }

  function focusDetailPanel() {
    var target = elements.detailPanel || elements.tableWrap;
    if (!target || typeof target.scrollIntoView !== "function") return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function roleLabel(key) {
    var role = (meta.roles || []).find(function (item) { return item.key === key; });
    return role ? role.label : key;
  }

  function roleShortDescription(key) {
    if (key === "star") return "高日销 / 高毛利";
    if (key === "potential") return "高日销 / 中低毛利";
    if (key === "incubation") return "低日销 / 中低毛利";
    if (key === "eliminate") return "零日销 / 低毛利";
    return "";
  }

  function lifecycleLabel(key) {
    var item = (meta.lifecycle_labels || []).find(function (entry) { return String(entry.key) === String(key); });
    return item ? item.label : key;
  }

  function lifecyclePeriod(key) {
    var item = (meta.lifecycle_labels || []).find(function (entry) { return String(entry.key) === String(key); });
    return item ? item.label_period : "";
  }

  function periodLabel(key) {
    var period = (meta.periods || []).find(function (item) { return item.key === key; });
    return period ? period.label : key;
  }

  function dailyBandDescription(band) {
    if (band === "日销 0") return "周期销量为 0";
    if (band === "日销 <1") return "0 < 日均销量 < 1";
    if (band === "日销 1-5") return "1 ≤ 日均销量 ≤ 5";
    if (band === "日销 >5") return "日均销量 > 5";
    return "";
  }

  function marginBandDescription(band) {
    if (band === "<5%") return "低毛利";
    if (band === "5%-10%") return "偏低毛利";
    if (band === "10%-15%") return "中低毛利";
    if (band === "15%-25%") return "健康毛利";
    if (band === ">25%") return "高毛利";
    return "";
  }

  function matrixRatioLevel(ratio) {
    var pct = Number(ratio || 0) * 100;
    if (pct >= 15) return 4;
    if (pct >= 10) return 3;
    if (pct >= 5) return 2;
    if (pct >= 2) return 1;
    return 0;
  }

  function exportCsv() {
    var params = new URLSearchParams();
    var endpoint = state.view === "lifecycle" ? "/api/sales-role/lifecycle/export" : "/api/sales-role/export";
    var keys = state.view === "lifecycle"
      ? ["period", "country_category", "seller_name_new", "lifecycle_label", "sales_role", "keyword", "sort_field", "sort_dir"]
      : ["period", "country_category", "seller_name_new", "sales_role", "daily_sales_band", "margin_band", "keyword", "sort_field", "sort_dir"];
    keys.forEach(function (key) {
      if (state[key] && state[key] !== "all") params.set(key, state[key]);
    });
    window.location.href = endpoint + (params.toString() ? "?" + params.toString() : "");
  }
}());
