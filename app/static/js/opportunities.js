(function () {
  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var state = app.readQueryState();
  state.compare_days = Number(query.get("compare_days") || 14);
  state.opportunity_type = query.get("opportunity_type") || "all";
  state.stock_status = query.get("stock_status") || "all";
  state.over_limit = query.get("over_limit") || "no";
  state.transition_filter = query.get("transition_filter") || "";
  state.page_size = 20;
  state.sort_field = state.sort_field || "";
  state.sort_dir = state.sort_dir || "";
  var meta = null;
  var elements = {};
  var renderToken = 0;
  var charts = {};
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
      "opportunityAnalysisPanel", "opportunityTableCard", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn"
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
    elements.opportunityTableCard.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/opportunities", state).then(function (payload) {
      if (token !== renderToken) return;
      typeDefs = payload.types || typeDefs;
      renderPeriod(payload);
      renderStats(payload);
      renderTabs(payload);
      renderAnalysis(payload);
      renderTable(payload);
      renderPagination(payload);
      app.restoreReturnState();
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
        state.transition_filter = "";
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
        state.transition_filter = "";
        state.page = 1;
        syncControls();
        render();
      });
    });
  }

  function renderAnalysis(payload) {
    var analysis = payload.analysis || {};
    if (!elements.opportunityAnalysisPanel) return;
    disposeCharts();
    elements.opportunityAnalysisPanel.innerHTML = [
      '<section class="analysis-grid analysis-grid-top">',
      analysisCard("机会类型结构", "当前筛选下各类机会数量", "opportunityTypeChart"),
      analysisCard("加码空间排行", "按站点聚合预计可加码销售额", "opportunityBoostChart"),
      analysisCard("库存承接结构", "点击库存分布联动库存状态", "opportunityStockChart"),
      '</section>',
      '<section class="analysis-grid analysis-grid-wide">',
      transitionCard("opportunityTransitionType", "opportunitySankeyChart", "opportunityTransitionTable"),
      analysisCard("机会分分布", "按机会分段查看质量结构", "opportunityScoreChart"),
      '</section>',
      '<section class="analysis-grid analysis-grid-single">',
      analysisCard("机会质量散点", "X=毛利率，Y=日销，气泡=预计可加码销售额", "opportunityScatterChart"),
      '</section>'
    ].join("");
    bindTransitionTabs("opportunityTransitionType", "opportunitySankeyChart", "opportunityTransitionTable", analysis);
    renderDistributionChart("opportunityTypeChart", analysis.type_distribution || [], function (key) {
      state.opportunity_type = key || "all";
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderRankingChart("opportunityBoostChart", analysis.boost_ranking || analysis.site_ranking || [], "value", function (name) {
      state.site = name;
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderBandChart("opportunityStockChart", analysis.stock_distribution || [], function (label) {
      state.stock_status = label === "<14天" ? "short" : "enough";
      state.transition_filter = "";
      state.page = 1;
      syncControls();
      render();
    });
    renderBandChart("opportunityScoreChart", analysis.score_distribution || []);
    renderOpportunityScatterChart("opportunityScatterChart", analysis.opportunity_scatter || []);
  }

  function analysisCard(title, caption, chartId) {
    return [
      '<article class="panel chart-card analysis-card">',
      '  <div class="panel-head compact"><div><p class="section-kicker">汇总分析</p><h3>' + app.escapeHtml(title) + '</h3><span class="analysis-caption">' + app.escapeHtml(caption) + '</span></div></div>',
      '  <div id="' + app.escapeHtml(chartId) + '" class="analysis-chart"></div>',
      '</article>'
    ].join("");
  }

  function transitionCard(tabsId, chartId, tableId) {
    return [
      '<article class="panel chart-card analysis-card analysis-transition-card">',
      '  <div class="analysis-card-head">',
      '    <div><p class="section-kicker">分层迁移</p><h3>毛利 / 排名分层流向</h3><span class="analysis-caption">按近 N 天 vs 前 N 天展示机会 SKU 层级迁移</span></div>',
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
      grid: { left: 92, right: 30, top: 18, bottom: 30 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: formatCompactAmount },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#e4edf7" } } },
      yAxis: { type: "category", data: data.map(function (row) { return row.name; }) },
      series: [{ type: "bar", barMaxWidth: 18, data: data.map(function (row) { return row[valueKey] || 0; }), itemStyle: { color: "#14a386", borderRadius: [0, 8, 8, 0] } }]
    });
    chart.on("click", function (params) {
      var row = data[params.dataIndex];
      if (row && onClick) onClick(row.name);
    });
  }

  function renderBandChart(id, rows, onClick) {
    var chart = getChart(id);
    if (!chart) return;
    chart.setOption({
      grid: { left: 44, right: 20, top: 24, bottom: 38 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "category", data: rows.map(function (row) { return row.label; }) },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#e4edf7" } } },
      series: [{ type: "bar", barMaxWidth: 34, data: rows.map(function (row) { return row.count || 0; }), itemStyle: { color: "#1769e0", borderRadius: [8, 8, 0, 0] } }]
    });
    chart.on("click", function (params) {
      var row = rows[params.dataIndex];
      if (row && onClick) onClick(row.label);
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

  function renderOpportunityScatterChart(id, rows) {
    var chart = getChart(id);
    if (!chart) return;
    chart.setOption({
      grid: { left: 60, right: 28, top: 24, bottom: 45 },
      tooltip: { formatter: function (params) { return params.data[3] + "<br/>毛利率：" + app.formatPercent(params.data[0], 1) + "<br/>日销：" + params.data[1] + "<br/>预计加码：" + formatCompactAmount(params.data[2]); } },
      xAxis: { type: "value", axisLabel: { formatter: function (value) { return Math.round(value * 100) + "%"; } } },
      yAxis: { type: "value" },
      series: [{
        type: "scatter",
        symbolSize: function (data) { return Math.max(8, Math.min(36, Math.sqrt(Math.abs(data[2] || 0)) / 18)); },
        data: rows.map(function (row) { return [row.margin || 0, row.daily_sales || 0, row.estimated_boost_revenue || 0, row.name || "-", row.type_label || ""]; }),
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
    elements.opportunityTableCard.innerHTML = [
      '<div class="alert-table-head">',
      '  <div><p class="section-kicker">机会明细</p><h3>可加码 SKU 清单</h3></div>',
      '  <div class="alert-table-actions">',
      '    <span class="summary-badge">当前筛选共 <strong>' + Number(payload.total || items.length).toLocaleString("zh-CN") + '</strong> 条</span>',
      '    <button id="exportOpportunitiesBtn" class="ghost-button" type="button">导出当前明细</button>',
      '  </div>',
      '</div>',
      '<div class="alert-table-wrap opportunity-table-wrap ag-grid-shell">',
      '  <div id="opportunityAgGrid"></div>',
      '</div>'
    ].join("");
    document.getElementById("exportOpportunitiesBtn").addEventListener("click", exportOpportunities);
    window.kanbanGrid.makeGrid("opportunityAgGrid", {
      rowData: items,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">' + app.escapeHtml(payload.empty_text || "当前没有机会 SKU。") + '</span>',
      columnDefs: [
        { headerName: "类型", field: "label", pinned: "left", width: 150, sort: colSort("label"), cellRenderer: function (params) { return window.kanbanGrid.tag(params.value, "positive"); } },
        { headerName: "分", field: "score", pinned: "left", width: 86, sort: colSort("score"), cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<strong class="opportunity-score">' + Number(params.value || 0) + "</strong>"; } },
        { headerName: "MSKU", field: "msku", pinned: "left", width: 128, sort: colSort("msku"), cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } },
        { headerName: "店铺", field: "store", width: 128, sort: colSort("store") },
        { headerName: "国家", field: "country", width: 110, sort: colSort("country") },
        { headerName: "日销/销量", colId: "daily_sales", minWidth: 170, sort: colSort("daily_sales"), valueGetter: function (params) { return params.data.daily_sales || 0; }, cellRenderer: function (params) { return window.kanbanGrid.subCell(window.kanbanGrid.decimal(params.data.daily_sales, 2), params.data.sales_text || "-"); } },
        { headerName: "销售额/毛利", colId: "scoped_revenue", minWidth: 190, sort: colSort("scoped_revenue"), valueGetter: function (params) { return params.data.scoped_revenue || 0; }, cellRenderer: function (params) { return window.kanbanGrid.subCell(window.kanbanGrid.compactAmount(params.data.scoped_revenue), "毛利率 " + window.kanbanGrid.percent(params.data.margin, 1) + " / 毛利 " + window.kanbanGrid.compactAmount(params.data.profit)); } },
        { headerName: "排名/Sessions", colId: "rank_sessions", minWidth: 190, sort: colSort("rank_sessions"), cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.rank_text || "-", "Sessions " + window.kanbanGrid.number(params.data.recent_sessions) + " / CVR " + window.kanbanGrid.percent(params.data.conversion, 1)); } },
        { headerName: "库存", colId: "stock", minWidth: 160, sort: colSort("stock"), valueGetter: function (params) { return params.data.fba_sellable_inventory || 0; }, cellRenderer: function (params) { return window.kanbanGrid.subCell(window.kanbanGrid.number(params.data.fba_sellable_inventory), "可售 " + window.kanbanGrid.decimal(params.data.sellable_days, 1) + " 天"); } },
        { headerName: "广告", colId: "ad", minWidth: 180, sort: colSort("ad"), cellRenderer: function (params) { return window.kanbanGrid.subCell("TACOS " + window.kanbanGrid.percent(params.data.tacos, 1), "ACOS " + window.kanbanGrid.percent(params.data.acos, 1) + " / 花费 " + window.kanbanGrid.compactAmount(params.data.ad_spend)); } },
        { headerName: "价格", colId: "price", minWidth: 170, sort: colSort("price"), valueGetter: function (params) { return params.data.current_price || 0; }, cellRenderer: function (params) { return window.kanbanGrid.subCell(window.kanbanGrid.decimal(params.data.current_price, 2), "35毛利 " + window.kanbanGrid.decimal(params.data.limit_price_35, 2) + " / " + (params.data.over_limit ? "超限价" : "未超")); } },
        {
          headerName: "建议动作",
          colId: "action",
          minWidth: 170,
          pinned: "right",
          filter: false,
          sortable: false,
          cellClass: "ag-grid-action-cell",
          cellRenderer: function (params) { return window.kanbanGrid.action(params.data.suggested_action || "查看明细", "alert-detail-link"); }
        }
      ],
      onSortChanged: handleGridSortChanged,
      onCellClicked: function (event) {
        if (event.colDef.colId !== "action") return;
        var item = event.data || {};
        var next = Object.assign({}, state);
        next.keyword = item.keyword || "";
        next.source = "机会池 / " + (item.label || "");
        delete next.opportunity_type;
        app.navigateWithReturnState("/detail?" + new URLSearchParams(next).toString());
      }
    });
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
    ["site", "store", "country", "over_limit", "keyword", "opportunity_type", "compare_days", "stock_status", "transition_filter"].forEach(function (key) {
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
