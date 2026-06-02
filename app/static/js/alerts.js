(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  state.alert_type = new URLSearchParams(window.location.search).get("alert_type") || "all";
  state.compare_days = Number(new URLSearchParams(window.location.search).get("compare_days") || 7);
  state.sales_trend = new URLSearchParams(window.location.search).get("sales_trend") || "all";
  state.rank_trend = new URLSearchParams(window.location.search).get("rank_trend") || "all";
  state.margin_status = new URLSearchParams(window.location.search).get("margin_status") || "all";
  state.stock_status = new URLSearchParams(window.location.search).get("stock_status") || "all";
  state.page_size = 20;
  var meta = null;
  var elements = {};
  var renderToken = 0;
  var alertDefs = [
    { key: "all", label: "全部", tone: "neutral" },
    { key: "sales_drop", label: "销量下滑", tone: "negative" },
    { key: "margin_low", label: "低毛利", tone: "warning" },
    { key: "rank_drop", label: "排名下滑", tone: "warning" },
    { key: "stock_short", label: "库存偏低", tone: "negative" },
  ];

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    bindEvents();
    app.apiGet("/api/meta").then(function (payload) {
      meta = payload;
      populateFilters();
      syncControls();
      render();
    });
  }

  function cacheElements() {
    [
      "compareDaysSelect", "siteSelect", "storeSelect", "alertTypeSelect",
      "salesTrendSelect", "rankTrendSelect", "marginStatusSelect", "stockStatusSelect",
      "keywordInput", "clearFiltersBtn",
      "alertPeriodHint", "alertStatsGrid", "alertTypeTabs", "alertTableCard",
      "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function populateFilters() {
    app.setSelectOptions(elements.siteSelect, meta.sites, "全部站点");
    app.setSelectOptions(elements.storeSelect, meta.stores, "全部店铺");
    elements.compareDaysSelect.innerHTML = [
      '<option value="7">近7天 vs 前7天</option>',
      '<option value="14">近14天 vs 前14天</option>',
      '<option value="30">近30天 vs 前30天</option>'
    ].join("");
    elements.alertTypeSelect.innerHTML = alertDefs.map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</option>';
    }).join("");
    elements.salesTrendSelect.innerHTML = trendOptions("销量");
    elements.rankTrendSelect.innerHTML = trendOptions("排名");
    elements.marginStatusSelect.innerHTML = [
      '<option value="all">全部毛利</option>',
      '<option value="low">低毛利</option>',
      '<option value="normal">非低毛利</option>'
    ].join("");
    elements.stockStatusSelect.innerHTML = [
      '<option value="all">全部库存</option>',
      '<option value="short">库存偏低</option>',
      '<option value="normal">库存正常</option>'
    ].join("");
  }

  function trendOptions(label) {
    return [
      '<option value="all">全部' + label + '</option>',
      '<option value="down">' + label + '下降</option>',
      '<option value="up">' + label + '上涨</option>',
      '<option value="stable">' + label + '无明显变化</option>'
    ].join("");
  }

  function syncControls() {
    elements.compareDaysSelect.value = String(state.compare_days || 7);
    elements.siteSelect.value = state.site;
    elements.storeSelect.value = state.store;
    elements.alertTypeSelect.value = state.alert_type || "all";
    elements.salesTrendSelect.value = state.sales_trend || "all";
    elements.rankTrendSelect.value = state.rank_trend || "all";
    elements.marginStatusSelect.value = state.margin_status || "all";
    elements.stockStatusSelect.value = state.stock_status || "all";
    elements.keywordInput.value = state.keyword || "";
  }

  function bindEvents() {
    [
      ["compareDaysSelect", "compare_days"],
      ["siteSelect", "site"],
      ["storeSelect", "store"],
      ["alertTypeSelect", "alert_type"],
      ["salesTrendSelect", "sales_trend"],
      ["rankTrendSelect", "rank_trend"],
      ["marginStatusSelect", "margin_status"],
      ["stockStatusSelect", "stock_status"],
    ].forEach(function (pair) {
      if (!elements[pair[0]]) return;
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = pair[1] === "compare_days" ? Number(this.value || 7) : this.value;
        state.page = 1;
        syncControls();
        render();
      });
    });

    elements.keywordInput.addEventListener("input", function () {
      state.keyword = this.value.trim();
      state.page = 1;
      render();
    });

    elements.clearFiltersBtn.addEventListener("click", function () {
      state.site = "all";
      state.store = "all";
      state.alert_type = "all";
      state.compare_days = 7;
      state.sales_trend = "all";
      state.rank_trend = "all";
      state.margin_status = "all";
      state.stock_status = "all";
      state.keyword = "";
      state.page = 1;
      syncControls();
      render();
    });
  }

  function render() {
    var token = ++renderToken;
    app.writeQueryState(state);
    elements.alertTableCard.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/alerts", state).then(function (payload) {
      if (token !== renderToken) return;
      renderPeriod(payload);
      renderStats(payload);
      renderTabs(payload);
      renderTable(payload);
      renderPagination(payload);
      app.restoreReturnState();
    }).catch(function (error) {
      console.error(error);
      elements.alertTableCard.innerHTML = '<div class="empty-state compact">加载失败，请稍后重试。</div>';
    });
  }

  function renderPeriod(payload) {
    elements.alertPeriodHint.textContent = [
      payload.window || "",
      payload.comparison_window ? "对比 " + payload.comparison_window : "",
    ].filter(Boolean).join(" / ");
  }

  function renderStats(payload) {
    var summary = payload.summary || {};
    var total = Number(payload.total_count || (payload.items || []).length);
    elements.alertStatsGrid.innerHTML = alertDefs.map(function (item) {
      var value = item.key === "all" ? total : Number(summary[item.key] || 0);
      return [
        '<button type="button" class="alert-stat-card ' + app.escapeHtml(item.tone) + (state.alert_type === item.key ? " active" : "") + '" data-alert-type="' + app.escapeHtml(item.key) + '">',
        '  <span>' + app.escapeHtml(item.label === "全部" ? "当前命中" : item.label) + '</span>',
        '  <strong>' + value.toLocaleString("zh-CN") + '</strong>',
        '</button>',
      ].join("");
    }).join("");
    Array.from(elements.alertStatsGrid.querySelectorAll("[data-alert-type]")).forEach(bindTypeButton);
  }

  function renderTabs(payload) {
    var rules = payload.rules || [];
    elements.alertTypeTabs.innerHTML = alertDefs.map(function (item) {
      return '<button type="button" class="' + (state.alert_type === item.key ? "active" : "") + '" data-alert-type="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</button>';
    }).join("");
    elements.alertTypeTabs.innerHTML += '<span class="alert-rule-note">' + app.escapeHtml((rules.find(function (item) { return item.type === state.alert_type; }) || {}).rule || "展示所有预警类型，点击类型可聚焦处理。") + '</span>';
    Array.from(elements.alertTypeTabs.querySelectorAll("[data-alert-type]")).forEach(bindTypeButton);
  }

  function bindTypeButton(node) {
    node.addEventListener("click", function () {
      state.alert_type = this.dataset.alertType || "all";
      state.page = 1;
      syncControls();
      render();
    });
  }

  function renderTable(payload) {
    var items = payload.items || [];
    if (!items.length) {
      elements.alertTableCard.innerHTML = '<div class="empty-state compact">' + app.escapeHtml(payload.empty_text || "当前没有明显异常。") + '</div>';
      return;
    }
    elements.alertTableCard.innerHTML = [
      '<div class="alert-table-head">',
      '  <div><p class="section-kicker">预警明细</p><h3>待处理 SKU 清单</h3></div>',
      '  <div class="alert-table-actions">',
      '    <span class="summary-badge">当前筛选共 <strong>' + Number(payload.total || items.length).toLocaleString("zh-CN") + '</strong> 条</span>',
      '    <button id="exportAlertsBtn" class="ghost-button" type="button">导出当前明细</button>',
      '  </div>',
      '</div>',
      '<div class="alert-table-wrap">',
      '<table class="alert-table">',
      '<thead><tr><th>类型</th><th>MSKU</th><th>店铺</th><th>国家</th><th>销量趋势</th><th>排名趋势</th><th>毛利</th><th>库存</th><th>处理入口</th></tr></thead>',
      '<tbody>',
      items.map(renderRow).join(""),
      '</tbody></table>',
      '</div>',
    ].join("");
    var exportButton = document.getElementById("exportAlertsBtn");
    if (exportButton) {
      exportButton.addEventListener("click", exportAlerts);
    }
    Array.from(elements.alertTableCard.querySelectorAll("[data-alert-keyword]")).forEach(function (node) {
      node.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next.keyword = this.dataset.alertKeyword || "";
        next.source = "异常预警 / " + (this.dataset.alertLabel || "");
        delete next.alert_type;
        app.navigateWithReturnState("/detail?" + new URLSearchParams(next).toString());
      });
    });
  }

  function exportAlerts() {
    var params = new URLSearchParams();
    [
      "start_date", "end_date", "site", "store", "over_limit", "daily_sales_band",
      "margin_band", "keyword", "alert_type", "compare_days", "sales_trend",
      "rank_trend", "margin_status", "stock_status"
    ].forEach(function (key) {
      var value = state[key];
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, value);
      }
    });
    window.location.href = "/api/alerts/export" + (params.toString() ? ("?" + params.toString()) : "");
  }

  function renderPagination(payload) {
    if (!elements.paginationInfo) return;
    var page = Number(payload.page || 1);
    var totalPages = Number(payload.total_pages || 1);
    var total = Number(payload.total || 0);
    elements.paginationInfo.textContent = "第 " + page + " / " + totalPages + " 页，共 " + total.toLocaleString("zh-CN") + " 条";
    elements.prevPageBtn.disabled = page <= 1;
    elements.nextPageBtn.disabled = page >= totalPages;
    elements.prevPageBtn.onclick = function () {
      if (page <= 1) return;
      state.page = page - 1;
      render();
    };
    elements.nextPageBtn.onclick = function () {
      if (page >= totalPages) return;
      state.page = page + 1;
      render();
    };
    var startPage = Math.max(1, page - 2);
    var endPage = Math.min(totalPages, page + 2);
    var pages = [];
    for (var index = startPage; index <= endPage; index += 1) pages.push(index);
    elements.paginationNumbers.innerHTML = pages.map(function (item) {
      return '<button type="button" class="page-number ' + (item === page ? "active" : "") + '" data-page="' + item + '">' + item + '</button>';
    }).join("");
    Array.from(elements.paginationNumbers.querySelectorAll("[data-page]")).forEach(function (button) {
      button.addEventListener("click", function () {
        state.page = Number(this.dataset.page);
        render();
      });
    });
  }

  function renderRow(item) {
    return [
      '<tr>',
      '  <td><span class="alert-label ' + app.escapeHtml(item.tone || "warning") + '">' + app.escapeHtml(item.label || "-") + '</span></td>',
      '  <td><strong>' + app.escapeHtml(item.title || "-") + '</strong></td>',
      '  <td>' + app.escapeHtml(item.store || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.country || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.sales_text || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.rank_text || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.margin_text || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.stock_text || "-") + '</td>',
      '  <td><button class="text-button alert-detail-link" type="button" data-alert-keyword="' + app.escapeHtml(item.keyword || "") + '" data-alert-label="' + app.escapeHtml(item.label || "") + '">查看明细</button></td>',
      '</tr>',
    ].join("");
  }
})();
