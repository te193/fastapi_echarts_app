(function () {
  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var state = app.readQueryState();
  state.compare_days = Number(query.get("compare_days") || 14);
  state.opportunity_type = query.get("opportunity_type") || "all";
  state.stock_status = query.get("stock_status") || "all";
  state.over_limit = query.get("over_limit") || "no";
  state.page_size = 20;
  var meta = null;
  var elements = {};
  var renderToken = 0;
  var typeDefs = [
    { key: "all", label: "全部机会", tone: "neutral" },
    { key: "high_margin_scale", label: "高毛利可放量", tone: "positive" },
    { key: "rank_improve", label: "排名改善", tone: "positive" },
    { key: "inventory_push", label: "库存充足待推", tone: "warning" },
    { key: "low_sales_high_margin", label: "低销高毛利", tone: "warning" },
    { key: "ad_efficiency", label: "广告效率可加码", tone: "positive" },
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
      "compareDaysSelect", "siteSelect", "storeSelect", "opportunityTypeSelect",
      "stockStatusSelect", "overLimitSelect", "keywordInput", "clearFiltersBtn",
      "opportunityPeriodHint", "opportunityStatsGrid", "opportunityTypeTabs",
      "opportunityTableCard", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn"
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
    elements.opportunityTypeSelect.innerHTML = typeDefs.map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</option>';
    }).join("");
    elements.stockStatusSelect.innerHTML = [
      '<option value="all">全部库存</option>',
      '<option value="enough">库存充足</option>',
      '<option value="short">库存不足</option>'
    ].join("");
    elements.overLimitSelect.innerHTML = [
      '<option value="no">未超限价</option>',
      '<option value="all">全部</option>',
      '<option value="yes">已超限价</option>'
    ].join("");
  }

  function syncControls() {
    elements.compareDaysSelect.value = String(state.compare_days || 14);
    elements.siteSelect.value = state.site || "all";
    elements.storeSelect.value = state.store || "all";
    elements.opportunityTypeSelect.value = state.opportunity_type || "all";
    elements.stockStatusSelect.value = state.stock_status || "all";
    elements.overLimitSelect.value = state.over_limit || "no";
    elements.keywordInput.value = state.keyword || "";
  }

  function bindEvents() {
    [
      ["compareDaysSelect", "compare_days"],
      ["siteSelect", "site"],
      ["storeSelect", "store"],
      ["opportunityTypeSelect", "opportunity_type"],
      ["stockStatusSelect", "stock_status"],
      ["overLimitSelect", "over_limit"],
    ].forEach(function (pair) {
      if (!elements[pair[0]]) return;
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = pair[1] === "compare_days" ? Number(this.value || 14) : this.value;
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
      state.opportunity_type = "all";
      state.compare_days = 14;
      state.stock_status = "all";
      state.over_limit = "no";
      state.keyword = "";
      state.page = 1;
      syncControls();
      render();
    });
  }

  function render() {
    var token = ++renderToken;
    app.writeQueryState(state);
    elements.opportunityTableCard.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/opportunities", state).then(function (payload) {
      if (token !== renderToken) return;
      typeDefs = payload.types || typeDefs;
      renderPeriod(payload);
      renderStats(payload);
      renderTabs(payload);
      renderTable(payload);
      renderPagination(payload);
    }).catch(function (error) {
      console.error(error);
      elements.opportunityTableCard.innerHTML = '<div class="empty-state compact">加载失败，请稍后重试。</div>';
    });
  }

  function renderPeriod(payload) {
    elements.opportunityPeriodHint.textContent = [
      payload.window || "",
      payload.comparison_window ? "对比 " + payload.comparison_window : "",
    ].filter(Boolean).join(" / ");
  }

  function renderStats(payload) {
    var stats = payload.stats || {};
    var cards = [
      ["当前机会", stats.total || payload.total_count || 0, "neutral", "all"],
      ["高毛利可放量", stats.high_margin_scale || 0, "positive", "high_margin_scale"],
      ["排名改善", stats.rank_improve || 0, "positive", "rank_improve"],
      ["库存充足", stats.inventory_push || 0, "warning", "inventory_push"],
      ["预计可加码销售额", formatCompactAmount(stats.estimated_boost_revenue || 0), "positive", "", "日销 × min(可售天数,30) × 15% × 平均售价"],
    ];
    elements.opportunityStatsGrid.innerHTML = cards.map(function (item) {
      var type = item[3] || "";
      var active = type && state.opportunity_type === type ? " active" : "";
      var dataAttr = type ? ' data-opportunity-stat-type="' + app.escapeHtml(type) + '"' : "";
      return [
        '<button type="button" class="alert-stat-card opportunity-stat-card ' + item[2] + active + '"' + dataAttr + '>',
        '  <span>' + app.escapeHtml(item[0]) + '</span>',
        '  <strong>' + (typeof item[1] === "number" ? item[1].toLocaleString("zh-CN") : app.escapeHtml(String(item[1]))) + '</strong>',
        item[4] ? '  <em class="opportunity-stat-note">' + app.escapeHtml(item[4]) + '</em>' : '',
        '</button>'
      ].join("");
    }).join("");
    Array.from(elements.opportunityStatsGrid.querySelectorAll("[data-opportunity-stat-type]")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.opportunity_type = this.dataset.opportunityStatType || "all";
        state.page = 1;
        syncControls();
        render();
      });
    });
  }

  function renderTabs(payload) {
    var rules = payload.types || [];
    elements.opportunityTypeTabs.innerHTML = typeDefs.map(function (item) {
      return '<button type="button" class="' + (state.opportunity_type === item.key ? "active" : "") + '" data-opportunity-type="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</button>';
    }).join("");
    elements.opportunityTypeTabs.innerHTML += '<span class="alert-rule-note">' + app.escapeHtml((rules.find(function (item) { return item.key === state.opportunity_type; }) || {}).rule || "展示所有机会类型，按机会分排序。") + '</span>';
    Array.from(elements.opportunityTypeTabs.querySelectorAll("[data-opportunity-type]")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.opportunity_type = this.dataset.opportunityType || "all";
        state.page = 1;
        syncControls();
        render();
      });
    });
  }

  function renderTable(payload) {
    var items = payload.items || [];
    if (!items.length) {
      elements.opportunityTableCard.innerHTML = '<div class="empty-state compact">' + app.escapeHtml(payload.empty_text || "当前没有机会 SKU。") + '</div>';
      return;
    }
    elements.opportunityTableCard.innerHTML = [
      '<div class="alert-table-head">',
      '  <div><p class="section-kicker">机会明细</p><h3>可加码 SKU 清单</h3></div>',
      '  <div class="alert-table-actions">',
      '    <span class="summary-badge">当前筛选共 <strong>' + Number(payload.total || items.length).toLocaleString("zh-CN") + '</strong> 条</span>',
      '    <button id="exportOpportunitiesBtn" class="ghost-button" type="button">导出当前明细</button>',
      '  </div>',
      '</div>',
      '<div class="alert-table-wrap opportunity-table-wrap">',
      '<table class="alert-table opportunity-table">',
      '<thead><tr><th>类型</th><th>分</th><th>MSKU</th><th>店铺</th><th>国家</th><th>日销/销量</th><th>销售额/毛利</th><th>排名/Sessions</th><th>库存</th><th>广告</th><th>价格</th><th>建议动作</th></tr></thead>',
      '<tbody>',
      items.map(renderRow).join(""),
      '</tbody></table>',
      '</div>',
    ].join("");
    document.getElementById("exportOpportunitiesBtn").addEventListener("click", exportOpportunities);
    Array.from(elements.opportunityTableCard.querySelectorAll("[data-opportunity-keyword]")).forEach(function (node) {
      node.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next.keyword = this.dataset.opportunityKeyword || "";
        next.source = "机会池 / " + (this.dataset.opportunityLabel || "");
        delete next.opportunity_type;
        window.location.href = "/detail?" + new URLSearchParams(next).toString();
      });
    });
  }

  function renderRow(item) {
    return [
      '<tr>',
      '  <td><span class="alert-label positive">' + app.escapeHtml(item.label || "-") + '</span></td>',
      '  <td><strong class="opportunity-score">' + Number(item.score || 0) + '</strong></td>',
      '  <td><strong>' + app.escapeHtml(item.msku || "-") + '</strong></td>',
      '  <td>' + app.escapeHtml(item.store || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.country || "-") + '</td>',
      '  <td><strong>' + formatNumber(item.daily_sales || 0, 2) + '</strong><span class="table-subtext">' + app.escapeHtml(item.sales_text || "-") + '</span></td>',
      '  <td><strong>' + formatCompactAmount(item.scoped_revenue || 0) + '</strong><span class="table-subtext">毛利率 ' + app.formatPercent(item.margin || 0, 1) + ' / 毛利 ' + formatCompactAmount(item.profit || 0) + '</span></td>',
      '  <td><strong>' + app.escapeHtml(item.rank_text || "-") + '</strong><span class="table-subtext">Sessions ' + Number(item.recent_sessions || 0).toLocaleString("zh-CN") + ' / CVR ' + app.formatPercent(item.conversion || 0, 1) + '</span></td>',
      '  <td><strong>' + Number(item.fba_sellable_inventory || 0).toLocaleString("zh-CN") + '</strong><span class="table-subtext">可售 ' + formatNumber(item.sellable_days || 0, 1) + ' 天</span></td>',
      '  <td><strong>TACOS ' + app.formatPercent(item.tacos || 0, 1) + '</strong><span class="table-subtext">ACOS ' + app.formatPercent(item.acos || 0, 1) + ' / 花费 ' + formatCompactAmount(item.ad_spend || 0) + '</span></td>',
      '  <td><strong>' + formatNumber(item.current_price || 0, 2) + '</strong><span class="table-subtext">35毛利 ' + formatNumber(item.limit_price_35 || 0, 2) + ' / ' + (item.over_limit ? "超限价" : "未超") + '</span></td>',
      '  <td><button class="text-button alert-detail-link" type="button" data-opportunity-keyword="' + app.escapeHtml(item.keyword || "") + '" data-opportunity-label="' + app.escapeHtml(item.label || "") + '">' + app.escapeHtml(item.suggested_action || "查看明细") + '</button></td>',
      '</tr>',
    ].join("");
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function formatCompactAmount(value) {
    var amount = Number(value || 0);
    var absAmount = Math.abs(amount);
    if (absAmount >= 100000000) {
      return (amount / 100000000).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }) + "亿";
    }
    if (absAmount >= 10000) {
      return (amount / 10000).toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }) + "万";
    }
    return amount.toLocaleString("zh-CN", {
      maximumFractionDigits: 0
    });
  }

  function exportOpportunities() {
    var params = new URLSearchParams();
    ["site", "store", "country", "over_limit", "keyword", "opportunity_type", "compare_days", "stock_status"].forEach(function (key) {
      var value = state[key];
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    });
    window.location.href = "/api/opportunities/export" + (params.toString() ? ("?" + params.toString()) : "");
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
})();
