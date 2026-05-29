(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  state.alert_type = new URLSearchParams(window.location.search).get("alert_type") || "all";
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
      "siteSelect", "storeSelect", "alertTypeSelect", "keywordInput", "clearFiltersBtn",
      "alertPeriodHint", "alertStatsGrid", "alertTypeTabs", "alertTableCard"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function populateFilters() {
    app.setSelectOptions(elements.siteSelect, meta.sites, "全部站点");
    app.setSelectOptions(elements.storeSelect, meta.stores, "全部店铺");
    elements.alertTypeSelect.innerHTML = alertDefs.map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</option>';
    }).join("");
  }

  function syncControls() {
    elements.siteSelect.value = state.site;
    elements.storeSelect.value = state.store;
    elements.alertTypeSelect.value = state.alert_type || "all";
    elements.keywordInput.value = state.keyword || "";
  }

  function bindEvents() {
    [
      ["siteSelect", "site"],
      ["storeSelect", "store"],
      ["alertTypeSelect", "alert_type"],
    ].forEach(function (pair) {
      if (!elements[pair[0]]) return;
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = this.value;
        syncControls();
        render();
      });
    });

    elements.keywordInput.addEventListener("input", function () {
      state.keyword = this.value.trim();
      render();
    });

    elements.clearFiltersBtn.addEventListener("click", function () {
      state.site = "all";
      state.store = "all";
      state.alert_type = "all";
      state.keyword = "";
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
        '  <span>' + app.escapeHtml(item.label) + '</span>',
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
      '  <span class="summary-badge">当前 <strong>' + items.length.toLocaleString("zh-CN") + '</strong> 条</span>',
      '</div>',
      '<div class="alert-table-wrap">',
      '<table class="alert-table">',
      '<thead><tr><th>类型</th><th>MSKU</th><th>店铺</th><th>国家</th><th>异常值</th><th>处理入口</th></tr></thead>',
      '<tbody>',
      items.map(renderRow).join(""),
      '</tbody></table>',
      '</div>',
    ].join("");
    Array.from(elements.alertTableCard.querySelectorAll("[data-alert-keyword]")).forEach(function (node) {
      node.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next.keyword = this.dataset.alertKeyword || "";
        next.source = "异常预警 / " + (this.dataset.alertLabel || "");
        delete next.alert_type;
        window.location.href = "/detail?" + new URLSearchParams(next).toString();
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
      '  <td>' + app.escapeHtml(item.detail || "-") + '</td>',
      '  <td><button class="text-button alert-detail-link" type="button" data-alert-keyword="' + app.escapeHtml(item.keyword || "") + '" data-alert-label="' + app.escapeHtml(item.label || "") + '">查看明细</button></td>',
      '</tr>',
    ].join("");
  }
})();
