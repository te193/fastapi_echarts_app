(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  state.alert_type = new URLSearchParams(window.location.search).get("alert_type") || "all";
  state.compare_days = Number(new URLSearchParams(window.location.search).get("compare_days") || 7);
  state.comparison_code = new URLSearchParams(window.location.search).get("comparison_code") || ("d" + (state.compare_days || 7));
  state.sales_trend = new URLSearchParams(window.location.search).get("sales_trend") || "all";
  state.rank_trend = new URLSearchParams(window.location.search).get("rank_trend") || "all";
  state.margin_status = new URLSearchParams(window.location.search).get("margin_status") || "all";
  state.stock_status = new URLSearchParams(window.location.search).get("stock_status") || "all";
  state.transition_filter = new URLSearchParams(window.location.search).get("transition_filter") || "";
  state.page_size = 20;
  state.sort_field = state.sort_field || "";
  state.sort_dir = state.sort_dir || "";
  var meta = null;
  var elements = {};
  var renderToken = 0;
  var charts = {};
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
      "alertAnalysisPanel", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function populateFilters() {
    app.setSelectOptions(elements.siteSelect, meta.sites, "全部站点");
    app.setSelectOptions(elements.storeSelect, meta.stores, "全部店铺");
    elements.compareDaysSelect.innerHTML = [
      '<optgroup label="固定天数">',
      '<option value="d7">近7天 vs 前7天</option>',
      '<option value="d14">近14天 vs 前14天</option>',
      '<option value="d30">近30天 vs 前30天</option>',
      '<option value="d60">近60天 vs 前60天</option>',
      '<option value="d90">近90天 vs 前90天</option>',
      '</optgroup>'
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
    elements.compareDaysSelect.value = state.comparison_code || ("d" + (state.compare_days || 7));
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
      ["compareDaysSelect", "comparison_code"],
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
        if (pair[1] === "comparison_code") {
          state.comparison_code = this.value || "d7";
          if (/^d\d+$/.test(state.comparison_code)) state.compare_days = Number(state.comparison_code.slice(1));
        } else {
          state[pair[1]] = this.value;
        }
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
      state.comparison_code = "d7";
      state.sales_trend = "all";
      state.rank_trend = "all";
      state.margin_status = "all";
      state.stock_status = "all";
      state.transition_filter = "";
      state.keyword = "";
      state.page = 1;
      state.sort_field = "";
      state.sort_dir = "";
      syncControls();
      render();
    });
    window.addEventListener("resize", function () {
      Object.keys(charts).forEach(function (key) {
        if (charts[key]) charts[key].resize();
      });
    });
  }

  function render() {
    var token = ++renderToken;
    app.writeQueryState(state);
    elements.alertTableCard.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/alerts", state).then(function (payload) {
      if (token !== renderToken) return;
      try {
        renderComparisonOptions(payload);
        renderPeriod(payload);
        renderStats(payload);
        renderTabs(payload);
      } catch (error) {
        console.error("Failed to render alert header", error);
      }
      try {
        renderAnalysis(payload);
      } catch (error) {
        console.error("Failed to render alert analysis", error);
        if (elements.alertAnalysisPanel) elements.alertAnalysisPanel.innerHTML = '<div class="empty-state compact">分析图表加载失败，明细仍可查看。</div>';
      }
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

  function renderComparisonOptions(payload) {
    var options = payload.available_comparisons || [];
    if (!options.length || !elements.compareDaysSelect) return;
    var dayOptions = options.filter(function (item) { return item.type === "days"; });
    var monthOptions = options.filter(function (item) { return item.type === "month_to_date"; });
    var htmlParts = [];
    if (dayOptions.length) {
      htmlParts.push('<optgroup label="固定天数">');
      dayOptions.forEach(function (item) {
        htmlParts.push('<option value="' + app.escapeHtml(item.code) + '">' + app.escapeHtml(item.label) + '</option>');
      });
      htmlParts.push('</optgroup>');
    }
    if (monthOptions.length) {
      htmlParts.push('<optgroup label="月份对比">');
      monthOptions.forEach(function (item) {
        htmlParts.push('<option value="' + app.escapeHtml(item.code) + '">' + app.escapeHtml(item.label) + '</option>');
      });
      htmlParts.push('</optgroup>');
    }
    elements.compareDaysSelect.innerHTML = htmlParts.join("");
    state.comparison_code = payload.comparison_code || state.comparison_code || "d7";
    if (/^d\d+$/.test(state.comparison_code)) state.compare_days = Number(state.comparison_code.slice(1));
    syncControls();
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
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
  }

  function renderAnalysis(payload) {
    var analysis = payload.analysis || {};
    if (!elements.alertAnalysisPanel) return;
    disposeCharts();
    elements.alertAnalysisPanel.innerHTML = [
      '<section class="analysis-grid analysis-grid-top">',
      analysisCard("预警类型结构", "当前筛选下各类异常命中数量", "alertTypeChart"),
      analysisCard("站点风险集中度", "点击站点可联动筛选", "alertSiteChart"),
      analysisCard("店铺风险集中度", "点击店铺可联动筛选", "alertStoreChart"),
      '</section>',
      '<section class="analysis-grid analysis-grid-wide">',
      transitionCard("alertTransitionType", "alertSankeyChart", "alertTransitionTable"),
      riskMatrixCard("alertRiskMatrixSummary", "alertRiskMatrixChart"),
      '</section>',
      '<section class="analysis-grid analysis-grid-single">',
      analysisCard("经营风险散点", "X=销量变化率，Y=排名变化，气泡=销售额", "alertRiskScatterChart"),
      '</section>'
    ].join("");
    bindTransitionTabs("alertTransitionType", "alertSankeyChart", "alertTransitionTable", analysis);
    renderDistributionChart("alertTypeChart", analysis.type_distribution || [], function (key) {
      state.alert_type = key || "all";
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderRankingChart("alertSiteChart", analysis.site_ranking || [], "count", function (name) {
      state.site = name;
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderRankingChart("alertStoreChart", analysis.store_ranking || [], "count", function (name) {
      state.store = name;
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderRiskMatrixSummary("alertRiskMatrixSummary", analysis.risk_matrix || []);
    renderRiskMatrixChart("alertRiskMatrixChart", analysis.risk_matrix || []);
    renderRiskScatterChart("alertRiskScatterChart", analysis.risk_scatter || []);
  }

  function analysisCard(title, caption, chartId) {
    return [
      '<article class="panel chart-card analysis-card">',
      '  <div class="panel-head compact"><div><p class="section-kicker">汇总分析</p><h3>' + app.escapeHtml(title) + '</h3><span class="analysis-caption">' + app.escapeHtml(caption) + '</span></div></div>',
      '  <div id="' + app.escapeHtml(chartId) + '" class="analysis-chart"></div>',
      '</article>'
    ].join("");
  }

  function riskMatrixCard(summaryId, chartId) {
    return [
      '<article class="panel chart-card analysis-card risk-matrix-card">',
      '  <div class="panel-head compact"><div><p class="section-kicker">汇总分析</p><h3>销量 × 排名风险矩阵</h3><span class="analysis-caption">点击格子筛选组合风险，颜色越深代表命中越集中</span></div></div>',
      '  <div id="' + app.escapeHtml(summaryId) + '" class="risk-matrix-summary"></div>',
      '  <div id="' + app.escapeHtml(chartId) + '" class="analysis-chart risk-matrix-chart"></div>',
      '</article>'
    ].join("");
  }

  function transitionCard(tabsId, chartId, tableId) {
    return [
      '<article class="panel chart-card analysis-card analysis-transition-card">',
      '  <div class="analysis-card-head">',
      '    <div><p class="section-kicker">分层迁移</p><h3>毛利 / 排名分层流向</h3><span class="analysis-caption">按近 N 天 vs 前 N 天展示 SKU 层级迁移</span></div>',
      '    <div id="' + app.escapeHtml(tabsId) + '" class="segmented-tabs analysis-tabs">',
      '      <button type="button" class="active" data-transition-kind="margin">毛利分层</button>',
      '      <button type="button" data-transition-kind="rank">排名分层</button>',
      '    </div>',
      '  </div>',
      '  <div class="analysis-transition-layout">',
      '    <div id="' + app.escapeHtml(chartId) + '" class="analysis-sankey-chart"></div>',
      '    <div id="' + app.escapeHtml(tableId) + '" class="analysis-transition-table"></div>',
      '  </div>',
      '</article>'
    ].join("");
  }

  function bindTransitionTabs(tabsId, chartId, tableId, analysis) {
    var tabs = document.getElementById(tabsId);
    var activeKind = "margin";
    function draw(kind) {
      activeKind = kind;
      Array.from(tabs.querySelectorAll("[data-transition-kind]")).forEach(function (button) {
        button.classList.toggle("active", button.dataset.transitionKind === kind);
      });
      var data = kind === "rank" ? analysis.rank_transition : analysis.margin_transition;
      renderSankeyChart(chartId, data || {}, kind);
      renderTransitionTable(tableId, data || {});
    }
    tabs.addEventListener("click", function (event) {
      var button = event.target.closest("[data-transition-kind]");
      if (!button) return;
      draw(button.dataset.transitionKind || activeKind);
    });
    draw(activeKind);
  }

  function disposeCharts() {
    Object.keys(charts).forEach(function (key) {
      if (charts[key]) charts[key].dispose();
      charts[key] = null;
    });
  }

  function getChart(id) {
    var host = document.getElementById(id);
    if (!host || typeof echarts === "undefined") return null;
    charts[id] = echarts.init(host);
    return charts[id];
  }

  function renderDistributionChart(id, rows, onClick) {
    var chart = getChart(id);
    if (!chart) return;
    chart.setOption({
      tooltip: { trigger: "item", formatter: "{b}<br/>SKU：{c} ({d}%)" },
      legend: { bottom: 0, left: "center" },
      series: [{
        type: "pie",
        radius: ["48%", "72%"],
        center: ["50%", "44%"],
        data: rows.map(function (row) { return { name: row.label, value: row.count, key: row.key }; })
      }]
    });
    chart.on("click", function (params) {
      if (params.data && onClick) onClick(params.data.key);
    });
  }

  function renderRankingChart(id, rows, valueKey, onClick) {
    var chart = getChart(id);
    if (!chart) return;
    var data = rows.slice().reverse();
    chart.setOption({
      grid: { left: 92, right: 28, top: 18, bottom: 24 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#e4edf7" } } },
      yAxis: { type: "category", data: data.map(function (row) { return row.name; }) },
      series: [{ type: "bar", barMaxWidth: 18, data: data.map(function (row) { return row[valueKey] || 0; }), itemStyle: { color: "#1769e0", borderRadius: [0, 8, 8, 0] } }]
    });
    chart.on("click", function (params) {
      var row = data[params.dataIndex];
      if (row && onClick) onClick(row.name);
    });
  }

  function renderSankeyChart(id, data, kind) {
    var chart = getChart(id);
    if (!chart) return;
    var total = (data.links || []).reduce(function (sum, item) { return sum + Number(item.value || 0); }, 0) || 1;
    chart.setOption({
      tooltip: {
        trigger: "item",
        triggerOn: "mousemove",
        formatter: function (params) {
          if (params.dataType === "edge") {
            var share = Number(params.data.value || 0) / total;
            return [
              app.escapeHtml(params.data.source || ""),
              "→ " + app.escapeHtml(params.data.target || ""),
              "SKU：" + Number(params.data.value || 0).toLocaleString("zh-CN"),
              "占比：" + app.formatPercent(share, 1)
            ].join("<br>");
          }
          return [
            app.escapeHtml(params.name || ""),
            "SKU：" + Number(params.value || 0).toLocaleString("zh-CN"),
            "占比：" + app.formatPercent(Number(params.value || 0) / total, 1)
          ].join("<br>");
        }
      },
      series: [{
        type: "sankey",
        top: 14,
        bottom: 14,
        left: 12,
        right: 86,
        nodeWidth: 14,
        nodeGap: 14,
        layoutIterations: 24,
        emphasis: { focus: "adjacency" },
        label: {
          width: 112,
          overflow: "truncate",
          lineHeight: 16,
          formatter: function (params) {
            var name = String(params.name || "").replace(/^前期\s+/, "").replace(/^当前\s+/, "");
            var count = Number(params.value || 0);
            return name + "\n" + count.toLocaleString("zh-CN") + " · " + app.formatPercent(count / total, 1);
          }
        },
        lineStyle: { color: "gradient", curveness: 0.5, opacity: 0.38 },
        data: data.nodes || [],
        links: (data.links || []).map(function (link) {
          return Object.assign({}, link, {
            lineStyle: { opacity: Math.max(0.18, Math.min(0.58, Number(link.value || 0) / total + 0.18)) }
          });
        })
      }]
    }, true);
    chart.on("click", function (params) {
      if (params.dataType !== "edge" || !params.data || !params.data.transition_filter) return;
      state.transition_filter = kind + ":" + params.data.transition_filter;
      state.page = 1;
      render();
    });
  }

  function renderTransitionTable(id, data) {
    var host = document.getElementById(id);
    if (!host) return;
    var rows = data.rows || [];
    host.innerHTML = [
      '<div class="analysis-transition-summary">',
      '<span>改善 <strong>' + Number((data.summary || {}).improved || 0).toLocaleString("zh-CN") + '</strong></span>',
      '<span>恶化 <strong>' + Number((data.summary || {}).worsened || 0).toLocaleString("zh-CN") + '</strong></span>',
      '<span>持平 <strong>' + Number((data.summary || {}).stable || 0).toLocaleString("zh-CN") + '</strong></span>',
      '</div>',
      '<table><thead><tr><th>层级</th><th>前期</th><th>当前</th><th>占比</th><th>净变化</th></tr></thead><tbody>',
      rows.map(function (row) {
        return '<tr><td>' + app.escapeHtml(row.layer) + '</td><td>' + row.previous_count + '</td><td>' + row.recent_count + '</td><td>' + app.formatPercent(row.share || 0, 1) + '</td><td class="' + (row.delta >= 0 ? "positive" : "negative") + '">' + (row.delta > 0 ? "+" : "") + row.delta + '</td></tr>';
      }).join(""),
      '</tbody></table>'
    ].join("");
  }

  function renderRiskMatrixSummary(id, rows) {
    var host = document.getElementById(id);
    if (!host) return;
    var total = rows.reduce(function (sum, row) { return sum + Number(row.count || 0); }, 0);
    var maxRow = rows.slice().sort(function (a, b) { return Number(b.count || 0) - Number(a.count || 0); })[0] || {};
    var bothDown = rows.find(function (row) { return row.sales_trend === "down" && row.rank_trend === "down"; }) || {};
    host.innerHTML = [
      '<div class="risk-matrix-pill">',
      '  <span>总命中</span><strong>' + Number(total || 0).toLocaleString("zh-CN") + '</strong>',
      '</div>',
      '<div class="risk-matrix-pill warning">',
      '  <span>双降风险</span><strong>' + Number(bothDown.count || 0).toLocaleString("zh-CN") + '</strong><em>' + app.formatPercent(total ? Number(bothDown.count || 0) / total : 0, 1) + '</em>',
      '</div>',
      '<div class="risk-matrix-pill focus">',
      '  <span>最集中组合</span><strong>' + app.escapeHtml(maxRow.label || "-") + '</strong><em>' + app.formatPercent(total ? Number(maxRow.count || 0) / total : 0, 1) + '</em>',
      '</div>'
    ].join("");
  }

  function renderRiskMatrixChart(id, rows) {
    var chart = getChart(id);
    if (!chart) return;
    var sales = ["down", "stable", "up"];
    var ranks = ["down", "stable", "up"];
    var labelMap = { down: "下降", stable: "稳定", up: "上涨" };
    var total = rows.reduce(function (sum, row) { return sum + Number(row.count || 0); }, 0) || 1;
    var maxValue = Math.max.apply(null, rows.map(function (row) { return row.count; }).concat([1]));
    chart.setOption({
      tooltip: {
        formatter: function (params) {
          var count = Number(params.data[2] || 0);
          return [
            params.data[3],
            "SKU：" + count.toLocaleString("zh-CN"),
            "占比：" + app.formatPercent(count / total, 1),
            "点击筛选该组合"
          ].join("<br>");
        }
      },
      grid: { left: 92, right: 28, top: 30, bottom: 66 },
      xAxis: {
        type: "category",
        data: sales.map(function (key) { return "销量" + labelMap[key]; }),
        axisTick: { show: false },
        axisLabel: { color: "#526783", fontWeight: 800 },
        axisLine: { lineStyle: { color: "#d5e1ef" } }
      },
      yAxis: {
        type: "category",
        data: ranks.map(function (key) { return "排名" + labelMap[key]; }),
        axisTick: { show: false },
        axisLabel: { color: "#526783", fontWeight: 800 },
        axisLine: { lineStyle: { color: "#d5e1ef" } }
      },
      visualMap: {
        min: 0,
        max: maxValue,
        dimension: 2,
        show: false,
        orient: "horizontal",
        left: "center",
        bottom: 8,
        itemWidth: 120,
        itemHeight: 8,
        text: ["集中", "较少"],
        textStyle: { color: "#526783", fontSize: 11 },
        inRange: { color: ["#f2f7fd", "#cfe3fb", "#7fb4f1", "#1769e0"] }
      },
      series: [{
        type: "heatmap",
        data: rows.map(function (row) { return [sales.indexOf(row.sales_trend), ranks.indexOf(row.rank_trend), row.count, row.label, row.sales_trend, row.rank_trend]; }),
        label: {
          show: true,
          color: "#10233d",
          fontWeight: 900,
          formatter: function (params) {
            var count = Number(params.data[2] || 0);
            return count + "\n" + app.formatPercent(count / total, 0);
          }
        },
        itemStyle: {
          borderColor: "#ffffff",
          borderWidth: 4,
          borderRadius: 10
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 12,
            shadowColor: "rgba(23, 105, 224, 0.25)"
          }
        }
      }]
    });
    chart.on("click", function (params) {
      state.sales_trend = params.data[4];
      state.rank_trend = params.data[5];
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
  }

  function renderRiskScatterChart(id, rows) {
    var chart = getChart(id);
    if (!chart) return;
    var safeRows = (rows || []).filter(function (row) {
      return isFinite(Number(row.sales_change_rate || 0)) && isFinite(Number(row.rank_delta || 0));
    }).slice(0, 300);
    chart.setOption({
      grid: { left: 60, right: 28, top: 24, bottom: 45 },
      tooltip: { formatter: function (params) { return params.data[3] + "<br/>销量变化：" + app.formatPercent(params.data[0], 1) + "<br/>排名变化：" + params.data[1]; } },
      xAxis: { type: "value", axisLabel: { formatter: function (value) { return Math.round(value * 100) + "%"; } } },
      yAxis: { type: "value" },
      series: [{
        type: "scatter",
        symbolSize: function (data) { return Math.max(8, Math.min(34, Math.sqrt(Math.abs(data[2] || 0)) / 18)); },
        data: safeRows.map(function (row) {
          var salesChange = Math.max(-1, Math.min(5, Number(row.sales_change_rate || 0)));
          var rankDelta = Math.max(-2000, Math.min(2000, Number(row.rank_delta || 0)));
          return [salesChange, rankDelta, row.sales_amount || 0, row.name || "-", row.type_label || ""];
        }),
        itemStyle: { color: "#14a386", opacity: 0.72 }
      }]
    });
  }

  function colSort(colId) {
    return state.sort_field === colId ? state.sort_dir : null;
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

  function renderTable(payload) {
    var items = payload.items || [];
    elements.alertTableCard.innerHTML = [
      '<div class="alert-table-head">',
      '  <div><p class="section-kicker">预警明细</p><h3>待处理 SKU 清单</h3></div>',
      '  <div class="alert-table-actions">',
      '    <span class="summary-badge">当前筛选共 <strong>' + Number(payload.total || items.length).toLocaleString("zh-CN") + '</strong> 条</span>',
      '    <button id="exportAlertsBtn" class="ghost-button" type="button">导出当前明细</button>',
      '  </div>',
      '</div>',
      '<div class="alert-table-wrap ag-grid-shell">',
      '  <div id="alertAgGrid"></div>',
      '</div>'
    ].join("");
    var exportButton = document.getElementById("exportAlertsBtn");
    if (exportButton) exportButton.addEventListener("click", exportAlerts);
    window.kanbanGrid.makeGrid("alertAgGrid", {
      rowData: items,
      rowHeight: 62,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">' + app.escapeHtml(payload.empty_text || "当前没有明显异常。") + '</span>',
      columnDefs: [
        { headerName: "类型", field: "label", pinned: "left", width: 210, sort: colSort("label"), cellClass: "alert-type-cell", cellRenderer: renderAlertTypeTag },
        { headerName: "MSKU", field: "title", pinned: "left", width: 128, sort: colSort("title"), cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } },
        { headerName: "店铺", field: "store", width: 128, sort: colSort("store") },
        { headerName: "国家", field: "country", width: 110, sort: colSort("country") },
        { headerName: "销量趋势", field: "sales_text", minWidth: 260, sort: colSort("sales_text") },
        { headerName: "近期总量", field: "recent_qty", width: 118, type: "numericColumn", sort: colSort("recent_qty") },
        { headerName: "近期日均", field: "recent_daily_sales", width: 118, type: "numericColumn", sort: colSort("recent_daily_sales") },
        { headerName: "对比总量", field: "previous_qty", width: 118, type: "numericColumn", sort: colSort("previous_qty") },
        { headerName: "对比日均", field: "previous_daily_sales", width: 118, type: "numericColumn", sort: colSort("previous_daily_sales") },
        { headerName: "排名趋势", field: "rank_text", minWidth: 170, sort: colSort("rank_text") },
        { headerName: "毛利", field: "margin_text", minWidth: 150, sort: colSort("margin_text") },
        { headerName: "库存", field: "stock_text", minWidth: 160, sort: colSort("stock_text") },
        {
          headerName: "处理入口",
          colId: "action",
          width: 120,
          pinned: "right",
          filter: false,
          sortable: false,
          cellClass: "ag-grid-action-cell",
          cellRenderer: function () { return window.kanbanGrid.action("查看明细", "alert-detail-link"); }
        }
      ],
      onSortChanged: handleGridSortChanged,
      onCellClicked: function (event) {
        if (event.colDef.colId !== "action") return;
        var item = event.data || {};
        var next = Object.assign({}, state);
        next.keyword = item.keyword || "";
        next.source = "异常预警 / " + (item.label || "");
        delete next.alert_type;
        app.navigateWithReturnState("/detail?" + new URLSearchParams(next).toString());
      }
    });
  }

  function renderAlertTypeTag(params) {
    var labels = (params.data && params.data.labels && params.data.labels.length)
      ? params.data.labels
      : String(params.value || "-").split(/\s*\/\s*/);
    var tone = (params.data && params.data.tone) || "warning";
    return '<span class="alert-type-tags">' + labels.filter(Boolean).map(function (label) {
      return '<span class="alert-label ' + app.escapeHtml(tone) + '">' + app.escapeHtml(label) + '</span>';
    }).join("") + '</span>';
  }

  function exportAlerts() {
    var params = new URLSearchParams();
    [
      "start_date", "end_date", "site", "store", "over_limit", "daily_sales_band",
      "margin_band", "keyword", "alert_type", "compare_days", "comparison_code", "sales_trend",
      "rank_trend", "margin_status", "stock_status", "transition_filter"
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


})();
