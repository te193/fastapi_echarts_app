(function () {
  "use strict";

  var app = window.kanbanApp;
  var state = Object.assign({
    period: "30d",
    country_category: "all",
    seller_name_new: "all",
    sales_role: "all",
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
    eliminate: "日销为 0；或日销 > 0 且毛利率 < 5%；或毛利率为空/未命中以上规则。"
  };

  document.addEventListener("DOMContentLoaded", init);

  function readInitialState() {
    var params = new URLSearchParams(window.location.search);
    return {
      period: params.get("period") || "30d",
      country_category: params.get("country_category") || "all",
      seller_name_new: params.get("seller_name_new") || "all",
      sales_role: params.get("sales_role") || "all",
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
      "periodButtons", "countryCategorySelect", "sellerNameSelect", "salesRoleSelect", "keywordInput",
      "clearFiltersBtn", "activeFilterChips", "exportBtn", "summaryHint", "summaryGrid",
      "roleGrid", "matrixGrid", "tableSummary", "tableWrap", "pagination"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
    elements.detailPanel = document.querySelector(".detail-panel");
  }

  function bindEvents() {
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
      ["salesRoleSelect", "sales_role"]
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
      state.period = (meta && meta.default_period) || "30d";
      state.country_category = "all";
      state.seller_name_new = "all";
      state.sales_role = "all";
      state.daily_sales_band = "all";
      state.margin_band = "all";
      state.keyword = "";
      state.page = 1;
      state.page_size = 20;
      state.sort_field = "sales_amount";
      state.sort_dir = "desc";
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
  }

  function syncControls() {
    Array.from(elements.periodButtons.querySelectorAll("[data-period]")).forEach(function (button) {
      button.classList.toggle("active", button.dataset.period === state.period);
    });
    elements.countryCategorySelect.value = state.country_category;
    elements.sellerNameSelect.value = state.seller_name_new;
    elements.salesRoleSelect.value = state.sales_role;
    elements.keywordInput.value = state.keyword;
    renderChips();
  }

  function renderChips() {
    var chips = ["周期：" + periodLabel(state.period)];
    if (state.country_category !== "all") chips.push("国家类别：" + state.country_category);
    if (state.seller_name_new !== "all") chips.push("店铺：" + state.seller_name_new);
    if (state.sales_role !== "all") chips.push("销售角色：" + roleLabel(state.sales_role));
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
    app.apiGet("/api/sales-role", state).then(function (payload) {
      if (token !== renderToken) return;
      renderSummary(payload);
      renderRoles(payload.roles || []);
      renderMatrix(payload.matrix || {});
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

  function setLoading(isLoading) {
    var main = document.querySelector(".main-content");
    if (main) main.classList.toggle("page-loading", isLoading);
  }

  function renderSummary(payload) {
    var summary = payload.summary || {};
    var windowText = payload.window ? payload.window.label : "暂无数据";
    elements.summaryHint.textContent = "统计窗口：" + windowText;
    var cards = [
      ["总 MSKU 数", formatNumber(summary.sku_count), "primary"],
      ["销售额", app.formatCompactCurrency(summary.sales_amount || 0), "revenue"],
      ["销量", formatNumber(summary.sales_qty), "quantity"],
      ["订单毛利润", app.formatCompactCurrency(summary.order_gross_profit || 0), "value"],
      ["订单毛利率", app.formatPercent(summary.order_gross_margin || 0), "margin"],
      ["动销 MSKU", formatNumber(summary.active_sku_count), "context"],
      ["问题产品", formatNumber(summary.eliminate_count), "negative"]
    ];
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

  function renderMatrix(matrix) {
    var dailyBands = matrix.daily_sales_bands || [];
    var marginBands = matrix.margin_bands || [];
    var cells = {};
    var total = Number(matrix.total || 0);
    (matrix.cells || []).forEach(function (cell) {
      cells[cell.margin_band + "|" + cell.daily_sales_band] = cell;
    });
    var html = [
      '<div class="sales-role-matrix-shell">',
      '<p class="sales-role-matrix-copy">按毛利率与日销分层统计当前筛选范围内的 MSKU 数量及占比，点击单元格筛选下方明细。</p>',
      '<div class="sales-role-status-matrix" style="grid-template-columns: 200px repeat(' + dailyBands.length + ', minmax(150px, 1fr));">',
      '<span class="status-matrix-corner"></span>'
    ];
    dailyBands.forEach(function (band) {
      html.push([
        '<span class="status-matrix-head">',
        '<b>' + app.escapeHtml(band) + '</b>',
        '<small>' + app.escapeHtml(dailyBandDescription(band)) + '</small>',
        '</span>'
      ].join(""));
    });
    marginBands.forEach(function (margin) {
      html.push([
        '<span class="status-matrix-row-head">',
        '<b>' + app.escapeHtml(margin) + '</b>',
        '<small>' + app.escapeHtml(marginBandDescription(margin)) + '</small>',
        '</span>'
      ].join(""));
      dailyBands.forEach(function (daily) {
        var cell = cells[margin + "|" + daily] || { count: 0, ratio: 0, sales_amount: 0 };
        var active = state.daily_sales_band === daily && state.margin_band === margin ? " active" : "";
        var ratio = Number(cell.ratio || 0);
        var level = matrixRatioLevel(ratio);
        var ratioText = total ? app.formatPercent(ratio, 1) : "0%";
        var empty = Number(cell.count || 0) === 0 ? " empty" : "";
        html.push([
          '<button type="button" class="status-matrix-cell level-' + level + active + empty + '" data-daily="' + app.escapeHtml(daily) + '" data-margin="' + app.escapeHtml(margin) + '">',
          '<strong>' + formatNumber(cell.count || 0) + '</strong>',
          '<span>' + ratioText + '</span>',
          '<em>' + app.escapeHtml(margin) + ' / ' + app.escapeHtml(daily) + ' · ' + formatNumber(cell.count || 0) + ' 个 · ' + app.formatCompactCurrency(cell.sales_amount || 0) + '</em>',
          '</button>'
        ].join(""));
      });
    });
    html.push([
      '</div>',
      '<div class="sales-role-matrix-foot">',
      '<div class="sales-role-matrix-legend"><span>数量占比（%）</span><i class="level-0"></i><b>&lt; 2%</b><i class="level-1"></i><b>2%-5%</b><i class="level-2"></i><b>5%-10%</b><i class="level-3"></i><b>10%-15%</b><i class="level-4"></i><b>&gt; 15%</b></div>',
      '<span>占比基于当前筛选 MSKU 总数 ' + formatNumber(total) + ' 计算</span>',
      '</div>',
      '</div>'
    ].join(""));
    elements.matrixGrid.innerHTML = html.join("");
    Array.from(elements.matrixGrid.querySelectorAll("[data-daily]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var same = state.daily_sales_band === this.dataset.daily && state.margin_band === this.dataset.margin;
        state.daily_sales_band = same ? "all" : this.dataset.daily;
        state.margin_band = same ? "all" : this.dataset.margin;
        state.page = 1;
        state.page_size = 5000;
        pendingDetailFocus = true;
        syncControls();
        render();
      });
    });
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

  function renderTable(payload) {
    elements.tableSummary.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + payload.total + " 条";
    window.kanbanGrid.makeGrid("tableWrap", {
      rowData: payload.rows || [],
      domLayout: "normal",
      rowHeight: 48,
      headerHeight: 50,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前筛选条件下没有销售角色明细。</span>',
      columnDefs: [
        { headerName: "销售角色", field: "sales_role", pinned: "left", width: 116, sort: colSort("sales_role") },
        { headerName: "国家类别", field: "country_category", pinned: "left", width: 116, sort: colSort("country_category") },
        { headerName: "店铺新", field: "seller_name_new", pinned: "left", width: 128, sort: colSort("seller_name_new") },
        { headerName: "MSKU", field: "seller_sku_adj", pinned: "left", width: 130, sort: colSort("seller_sku_adj") },
        { headerName: "SKU示例", field: "local_sku_sample", width: 128 },
        { headerName: "覆盖国家数", field: "country_count", width: 118, sort: colSort("country_count"), cellClass: "ag-grid-number-cell" },
        { headerName: "销量", field: "sales_qty", width: 104, sort: colSort("sales_qty"), cellClass: "ag-grid-number-cell" },
        { headerName: "日均销量", field: "daily_sales", width: 116, sort: colSort("daily_sales"), cellClass: "ag-grid-number-cell" },
        { headerName: "销售额", field: "sales_amount", width: 126, sort: colSort("sales_amount"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
        { headerName: "订单毛利额", field: "order_gross_profit", width: 128, sort: colSort("order_gross_profit"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
        { headerName: "订单毛利率", field: "order_gross_margin", width: 126, sort: colSort("order_gross_margin"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter },
        { headerName: "日销分层", field: "daily_sales_band", width: 116, sort: colSort("daily_sales_band") },
        { headerName: "毛利率分层", field: "margin_band", width: 116, sort: colSort("margin_band") },
        { headerName: "广告花费", field: "ad_spend", width: 118, sort: colSort("ad_spend"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
        { headerName: "广告销售额", field: "ad_sales", width: 126, sort: colSort("ad_sales"), cellClass: "ag-grid-number-cell", valueFormatter: moneyFormatter },
        { headerName: "ACOS", field: "acos", width: 96, sort: colSort("acos"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter },
        { headerName: "TACOS", field: "tacos", width: 96, sort: colSort("tacos"), cellClass: "ag-grid-number-cell", valueFormatter: percentFormatter }
      ],
      onSortChanged: function (event) {
        var sorted = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
        state.sort_field = sorted ? sorted.colId : "sales_amount";
        state.sort_dir = sorted ? sorted.sort : "desc";
        state.page = 1;
        render();
      }
    });
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
    return state.sales_role !== "all" || state.daily_sales_band !== "all" || state.margin_band !== "all";
  }

  function clearLinkedFilters() {
    if (!hasLinkedFilter()) return false;
    state.sales_role = "all";
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

  function periodLabel(key) {
    var period = (meta.periods || []).find(function (item) { return item.key === key; });
    return period ? period.label : key;
  }

  function exportCsv() {
    var params = new URLSearchParams();
    [
      "period", "country_category", "seller_name_new", "sales_role",
      "daily_sales_band", "margin_band", "keyword", "sort_field", "sort_dir"
    ].forEach(function (key) {
      if (state[key] && state[key] !== "all") params.set(key, state[key]);
    });
    window.location.href = "/api/sales-role/export" + (params.toString() ? "?" + params.toString() : "");
  }
}());
