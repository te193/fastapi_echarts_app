(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  var query = new URLSearchParams(window.location.search);
  state.warning_status = query.get("warning_status") || "all";
  state.metric = query.get("metric") || "all";
  state.value_type = query.get("value_type") || "quantity";
  state.page_size = 20;

  var meta = null;
  var elements = {};
  var trendsPayload = null;
  var trendChart = null;
  var structureChart = null;
  var renderToken = 0;
  var metricDefs = [
    { key: "available", label: "可用", color: "#2563eb" },
    { key: "transit", label: "在途", color: "#14a386" },
    { key: "warehouse", label: "在仓", color: "#d97706" },
    { key: "plan", label: "计划", color: "#7c3aed" }
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
      "startDateInput", "endDateInput", "siteSelect", "storeSelect", "warningStatusSelect",
      "keywordInput", "clearFiltersBtn", "inventoryPeriodHint", "inventoryStatsGrid",
      "inventoryTrendChart", "inventoryStructureChart", "inventoryWarningCards",
      "inventoryTableCard", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn",
      "valueTypeTabs"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function populateFilters() {
    app.setSelectOptions(elements.siteSelect, meta.sites || [], "全部站点");
    app.setSelectOptions(elements.storeSelect, meta.stores || [], "全部店铺");
  }

  function syncControls() {
    elements.startDateInput.value = state.start_date || "";
    elements.endDateInput.value = state.end_date || "";
    elements.siteSelect.value = state.site || "all";
    elements.storeSelect.value = state.store || "all";
    elements.warningStatusSelect.value = state.warning_status || "all";
    elements.keywordInput.value = state.keyword || "";
    Array.from(elements.valueTypeTabs.querySelectorAll("button")).forEach(function (button) {
      button.classList.toggle("active", button.dataset.valueType === (state.value_type || "quantity"));
    });
  }

  function bindEvents() {
    [
      ["startDateInput", "start_date"],
      ["endDateInput", "end_date"],
      ["siteSelect", "site"],
      ["storeSelect", "store"],
      ["warningStatusSelect", "warning_status"]
    ].forEach(function (pair) {
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = this.value || (pair[1] === "warning_status" ? "all" : "");
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
      state.start_date = "";
      state.end_date = "";
      state.site = "all";
      state.store = "all";
      state.warning_status = "all";
      state.metric = "all";
      state.keyword = "";
      state.page = 1;
      syncControls();
      render();
    });
    elements.valueTypeTabs.addEventListener("click", function (event) {
      var button = event.target.closest("[data-value-type]");
      if (!button) return;
      state.value_type = button.dataset.valueType || "quantity";
      syncControls();
      renderCharts();
      app.writeQueryState(state);
    });
    window.addEventListener("resize", function () {
      if (trendChart) trendChart.resize();
      if (structureChart) structureChart.resize();
    });
  }

  function render() {
    var token = ++renderToken;
    app.writeQueryState(state);
    elements.inventoryTableCard.innerHTML = '<div class="empty-state compact">加载中...</div>';
    Promise.all([
      app.apiGet("/api/inventory-weekly/trends", state),
      app.apiGet("/api/inventory-weekly/details", state)
    ]).then(function (responses) {
      if (token !== renderToken) return;
      trendsPayload = responses[0] || {};
      metricDefs = trendsPayload.metrics || metricDefs;
      renderPeriod(trendsPayload);
      renderStats(trendsPayload);
      renderCharts();
      renderWarnings(trendsPayload);
      renderTable(responses[1] || {});
      renderPagination(responses[1] || {});
      app.restoreReturnState();
    }).catch(function (error) {
      console.error(error);
      elements.inventoryTableCard.innerHTML = '<div class="empty-state compact">库存周报加载失败，请稍后重试。</div>';
    });
  }

  function renderPeriod(payload) {
    var latest = ((payload.overview || {}).latest_week || {});
    if (!latest.week_start) {
      elements.inventoryPeriodHint.textContent = "暂无周度库存快照";
      return;
    }
    elements.inventoryPeriodHint.textContent = "最新周 " + latest.week_start + " ~ " + latest.week_end + " / 快照 " + latest.snapshot_date;
  }

  function renderStats(payload) {
    var overview = payload.overview || {};
    var cards = (overview.cards || []).map(function (card) {
      var active = state.metric === card.key ? " active" : "";
      var warning = card.warning ? " warning" : "";
      return [
        '<button type="button" class="alert-stat-card inventory-stat-card' + active + warning + '" data-inventory-metric="' + app.escapeHtml(card.key) + '">',
        '  <span>' + app.escapeHtml(card.label) + '</span>',
        '  <strong>' + formatQuantity(card.quantity) + '</strong>',
        '  <em>成本 ' + formatAmount(card.cost) + '</em>',
        '  <small>' + formatRate(card.quantity_rate) + ' / ' + formatRate(card.cost_rate) + '</small>',
        '</button>'
      ].join("");
    });
    elements.inventoryStatsGrid.innerHTML = cards.join("");
    Array.from(elements.inventoryStatsGrid.querySelectorAll("[data-inventory-metric]")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.metric = state.metric === this.dataset.inventoryMetric ? "all" : this.dataset.inventoryMetric;
        state.page = 1;
        render();
      });
    });
  }

  function renderCharts() {
    if (!trendsPayload) return;
    renderTrendChart(trendsPayload);
    renderStructureChart(trendsPayload);
  }

  function renderTrendChart(payload) {
    var weeks = payload.weeks || [];
    if (!trendChart) trendChart = echarts.init(elements.inventoryTrendChart);
    var valueType = state.value_type === "cost" ? "cost" : "quantity";
    var suffix = valueType === "cost" ? "成本" : "数量";
    var option = {
      color: metricDefs.map(function (item) { return item.color; }),
      tooltip: {
        trigger: "axis",
        formatter: function (params) {
          var index = params[0] ? params[0].dataIndex : 0;
          var week = weeks[index] || {};
          var lines = ["<strong>" + (week.week_start || "") + " ~ " + (week.week_end || "") + "</strong>", "快照：" + (week.snapshot_date || "-")];
          params.forEach(function (param) {
            var metric = metricDefs.find(function (item) { return item.label === param.seriesName; }) || {};
            var detail = ((week.metrics || {})[metric.key] || {});
            var rate = valueType === "cost" ? detail.cost_rate : detail.quantity_rate;
            lines.push(param.marker + param.seriesName + "：" + formatChartValue(param.value, valueType) + "，环比 " + formatRate(rate));
          });
          return lines.join("<br>");
        }
      },
      legend: { top: 0, right: 10 },
      grid: { left: 58, right: 28, top: 52, bottom: 40 },
      xAxis: { type: "category", data: weeks.map(function (item) { return item.week_end; }), axisLabel: { color: "#526783" } },
      yAxis: { type: "value", axisLabel: { color: "#526783", formatter: function (value) { return formatAxisValue(value, valueType); } }, splitLine: { lineStyle: { color: "#e4edf7" } } },
      series: metricDefs.map(function (metric) {
        return {
          name: metric.label,
          type: "line",
          smooth: true,
          symbolSize: 7,
          lineStyle: { width: 3 },
          data: weeks.map(function (week) {
            var detail = ((week.metrics || {})[metric.key] || {});
            return detail[valueType] || 0;
          })
        };
      })
    };
    trendChart.setOption(option, true);
    trendChart.off("click");
    trendChart.on("click", function (params) {
      var metric = metricDefs.find(function (item) { return item.label === params.seriesName; });
      if (!metric) return;
      state.metric = metric.key;
      state.page = 1;
      render();
    });
  }

  function renderStructureChart(payload) {
    var weeks = payload.weeks || [];
    if (!structureChart) structureChart = echarts.init(elements.inventoryStructureChart);
    var valueType = state.value_type === "cost" ? "cost" : "quantity";
    var option = {
      color: metricDefs.map(function (item) { return item.color; }),
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (value) { return formatChartValue(value, valueType); } },
      legend: { top: 0, right: 10 },
      grid: { left: 58, right: 24, top: 52, bottom: 40 },
      xAxis: { type: "category", data: weeks.map(function (item) { return item.week_end; }), axisLabel: { color: "#526783" } },
      yAxis: { type: "value", axisLabel: { color: "#526783", formatter: function (value) { return formatAxisValue(value, valueType); } }, splitLine: { lineStyle: { color: "#e4edf7" } } },
      series: metricDefs.map(function (metric) {
        return {
          name: metric.label,
          type: "bar",
          stack: "inventory",
          barMaxWidth: 38,
          data: weeks.map(function (week) {
            var detail = ((week.metrics || {})[metric.key] || {});
            return detail[valueType] || 0;
          })
        };
      })
    };
    structureChart.setOption(option, true);
  }

  function renderWarnings(payload) {
    var weeks = payload.weeks || [];
    var warningWeeks = weeks.filter(function (week) { return week.warning; }).slice(-4).reverse();
    if (!warningWeeks.length) {
      elements.inventoryWarningCards.innerHTML = '<div class="empty-state compact">当前筛选下暂无超过历史波动阈值的周度预警。</div>';
      return;
    }
    elements.inventoryWarningCards.innerHTML = warningWeeks.map(function (week) {
      var labels = (week.warning_metrics || []).map(metricLabel).join("、");
      return [
        '<button type="button" class="inventory-warning-card" data-warning-week="' + app.escapeHtml(week.week_start) + '">',
        '  <span>预警周 ' + app.escapeHtml(week.week_start) + ' ~ ' + app.escapeHtml(week.week_end) + '</span>',
        '  <strong>' + app.escapeHtml(labels || "库存波动") + '</strong>',
        '  <em>快照 ' + app.escapeHtml(week.snapshot_date || "-") + '</em>',
        '</button>'
      ].join("");
    }).join("");
    Array.from(elements.inventoryWarningCards.querySelectorAll("[data-warning-week]")).forEach(function (node) {
      node.addEventListener("click", function () {
        state.start_date = this.dataset.warningWeek;
        state.end_date = this.dataset.warningWeek;
        state.warning_status = "all";
        state.page = 1;
        syncControls();
        render();
      });
    });
  }

  function renderTable(payload) {
    var items = payload.items || [];
    if (!items.length) {
      elements.inventoryTableCard.innerHTML = '<div class="empty-state compact">当前筛选下没有库存周报明细。</div>';
      return;
    }
    elements.inventoryTableCard.innerHTML = [
      '<div class="alert-table-head">',
      '  <div><p class="section-kicker">明细表</p><h3>周度 SKU 库存明细</h3></div>',
      '  <div class="alert-table-actions">',
      '    <span class="summary-badge">当前筛选共 <strong>' + Number(payload.total || items.length).toLocaleString("zh-CN") + '</strong> 条</span>',
      '    <button id="exportInventoryBtn" class="ghost-button" type="button">导出当前明细</button>',
      '  </div>',
      '</div>',
      '<div class="alert-table-wrap inventory-table-wrap">',
      '<table class="alert-table inventory-table">',
      '<thead><tr><th>周</th><th>站点</th><th>店铺</th><th>MSKU</th><th>可用</th><th>在途</th><th>在仓</th><th>计划</th><th>预警</th></tr></thead>',
      '<tbody>', items.map(renderRow).join(""), '</tbody></table></div>'
    ].join("");
    document.getElementById("exportInventoryBtn").addEventListener("click", exportInventory);
  }

  function renderRow(item) {
    return [
      '<tr>',
      '  <td><strong>' + app.escapeHtml(item.week_start || "-") + '</strong><span class="table-subtext">快照 ' + app.escapeHtml(item.snapshot_date || "-") + '</span></td>',
      '  <td>' + app.escapeHtml(item.site || "-") + '</td>',
      '  <td>' + app.escapeHtml(item.store || "-") + '</td>',
      '  <td><strong>' + app.escapeHtml(item.msku || "-") + '</strong></td>',
      renderMetricCell(item, "available"),
      renderMetricCell(item, "transit"),
      renderMetricCell(item, "warehouse"),
      renderMetricCell(item, "plan"),
      '  <td>' + renderWarningLabel(item) + '</td>',
      '</tr>'
    ].join("");
  }

  function renderMetricCell(item, key) {
    return '<td><strong>' + formatQuantity(item[key + "_quantity"]) + '</strong><span class="table-subtext">成本 ' + formatAmount(item[key + "_cost"]) + '</span></td>';
  }

  function renderWarningLabel(item) {
    if (!item.warning) return '<span class="alert-label positive">正常</span>';
    return '<span class="alert-label warning">' + app.escapeHtml((item.warning_metrics || []).map(metricLabel).join("、") || "预警") + '</span>';
  }

  function renderPagination(payload) {
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

  function exportInventory() {
    var params = new URLSearchParams();
    ["start_date", "end_date", "site", "store", "keyword", "warning_status", "metric"].forEach(function (key) {
      var value = state[key];
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    });
    window.location.href = "/api/inventory-weekly/export" + (params.toString() ? ("?" + params.toString()) : "");
  }

  function metricLabel(key) {
    var metric = metricDefs.find(function (item) { return item.key === key; });
    return metric ? metric.label : key;
  }

  function formatQuantity(value) {
    return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  function formatAmount(value) {
    return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }

  function formatRate(value) {
    if (value === null || value === undefined) return "环比 -";
    return "环比 " + (Number(value || 0) * 100).toFixed(1) + "%";
  }

  function formatChartValue(value, type) {
    return type === "cost" ? formatAmount(value) : formatQuantity(value);
  }

  function formatAxisValue(value, type) {
    var amount = Number(value || 0);
    if (Math.abs(amount) >= 100000000) return (amount / 100000000).toFixed(1) + "亿";
    if (Math.abs(amount) >= 10000) return (amount / 10000).toFixed(0) + "万";
    return type === "cost" ? amount.toFixed(0) : amount.toFixed(0);
  }
}());
