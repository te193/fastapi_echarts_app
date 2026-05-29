(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  var meta = null;
  var charts = {};
  var datePicker = null;
  var elements = {};
  var renderToken = 0;
  var monthlyGoalData = null;
  var currentMonthlyMetric = "sales";

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    bindEvents();
    app.apiGet("/api/meta").then(function (payload) {
      meta = payload;
      hydrateDefaults();
      populateFilters();
      initDateRangePicker();
      syncControls();
      render();
      loadMonthlyGoals();
    });
  }

  function cacheElements() {
    [
      "startDateInput", "endDateInput", "siteSelect", "storeSelect", "overLimitSelect",
      "dailySalesBandSelect", "marginBandSelect", "keywordInput",
      "clearFiltersBtn", "periodQuickButtons", "activeFilterChips", "summaryHint", "goalOverviewCard", "kpiGrid",
      "alertCenterCard", "goalGapCard", "monthlyGoalCard",
      "dailySalesSummary", "marginBandSummary", "dailySalesChart", "marginBandChart",
      "matrixSummary", "matrixChart"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function hydrateDefaults() {
    if (!state.start_date) state.start_date = meta.default_start_date;
    if (!state.end_date) state.end_date = meta.default_end_date;
    if (!state.page) state.page = 1;
  }

  function populateFilters() {
    app.setSelectOptions(elements.siteSelect, meta.sites, "全部站点");
    app.setSelectOptions(elements.storeSelect, meta.stores, "全部店铺");
    app.setSelectOptions(elements.dailySalesBandSelect, meta.daily_sales_bands, "全部日销分层");
    app.setSelectOptions(elements.marginBandSelect, meta.margin_bands, "全部毛利率分层");
    elements.overLimitSelect.innerHTML = [
      '<option value="all">全部</option>',
      '<option value="yes">仅看超限价</option>',
      '<option value="no">仅看未超限价</option>'
    ].join("");
  }

  function syncControls() {
    if (datePicker) {
      datePicker.sync(state.start_date || "", state.end_date || "");
    } else if (elements.startDateInput && elements.endDateInput) {
      elements.startDateInput.value = app.formatDisplayDate(state.start_date || "");
      elements.endDateInput.value = app.formatDisplayDate(state.end_date || "");
    }
    syncPeriodQuickButtons();
    elements.siteSelect.value = state.site;
    elements.storeSelect.value = state.store;
    elements.overLimitSelect.value = state.over_limit;
    elements.dailySalesBandSelect.value = state.daily_sales_band;
    elements.marginBandSelect.value = state.margin_band;
    elements.keywordInput.value = state.keyword;
    app.renderFilterChips(elements.activeFilterChips, state);
  }

  function bindEvents() {
    [
      ["siteSelect", "site"],
      ["storeSelect", "store"],
      ["overLimitSelect", "over_limit"],
      ["dailySalesBandSelect", "daily_sales_band"],
      ["marginBandSelect", "margin_band"]
    ].forEach(function (pair) {
      if (!elements[pair[0]]) return;
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

    if (elements.periodQuickButtons) {
      elements.periodQuickButtons.addEventListener("click", function (event) {
        var button = event.target.closest("[data-period]");
        if (!button) return;
        applyQuickPeriod(button.dataset.period);
      });
    }

    elements.clearFiltersBtn.addEventListener("click", function () {
      state.start_date = meta.default_start_date;
      state.end_date = meta.default_end_date;
      state.site = "all";
      state.store = "all";
      state.over_limit = "all";
      state.daily_sales_band = "all";
      state.margin_band = "all";
      state.keyword = "";
      state.page = 1;
      syncControls();
      render();
    });

    window.addEventListener("resize", function () {
      Object.keys(charts).forEach(function (key) {
        if (charts[key]) charts[key].resize();
      });
    });
  }

  function applyQuickPeriod(period) {
    var range = app.resolveQuickPeriodRange(period, meta.default_end_date);
    if (!range) return;
    state.start_date = range.start_date;
    state.end_date = range.end_date;
    state.page = 1;
    syncControls();
    render();
  }

  function syncPeriodQuickButtons() {
    if (!elements.periodQuickButtons || !meta) return;
    var activePeriod = app.getQuickPeriodForRange(state.start_date, state.end_date, meta.default_end_date);
    Array.from(elements.periodQuickButtons.querySelectorAll("[data-period]")).forEach(function (button) {
      button.classList.toggle("active", button.dataset.period === activePeriod);
    });
  }

  function initDateRangePicker() {
    if (datePicker || !elements.startDateInput || !elements.endDateInput) return;
    datePicker = app.createDateRangePicker({
      startInput: elements.startDateInput,
      endInput: elements.endDateInput,
      defaultEnd: meta.default_end_date,
      getStart: function () {
        return state.start_date;
      },
      getEnd: function () {
        return state.end_date;
      },
      onApply: function (startDate, endDate) {
        state.start_date = startDate || meta.default_start_date;
        state.end_date = endDate || meta.default_end_date;
        state.page = 1;
        syncControls();
        render();
      }
    });
  }

  function setLoading(isLoading) {
    var main = document.querySelector(".main-content");
    if (main) main.classList.toggle("page-loading", isLoading);
  }

  function render() {
    var token = ++renderToken;
    setLoading(true);
    app.writeQueryState(state);
    app.apiGet("/api/dashboard", state).then(function (payload) {
      if (elements.summaryHint) {
        elements.summaryHint.textContent = payload.summary_hint;
      }
      if (elements.goalOverviewCard) {
        renderGoalOverview(payload.goal_overview);
      }
      if (elements.kpiGrid) {
        renderKpis(payload.kpis);
      }
      if (elements.alertCenterCard) {
        renderAlertCenter(payload.alert_center);
      }
      if (elements.goalGapCard) {
        renderGoalGap(payload.goal_gap_breakdown);
      }
      if (elements.dailySalesChart && elements.dailySalesSummary) {
        renderBandListChart("dailySalesChart", "dailySalesSummary", payload.daily_sales_chart.items, state.daily_sales_band, "daily_sales_band", "日销分层");
      }
      if (elements.marginBandChart && elements.marginBandSummary) {
        renderBandListChart("marginBandChart", "marginBandSummary", payload.margin_chart.items, state.margin_band, "margin_band", "毛利率分层");
      }
      if (elements.matrixChart && elements.matrixSummary) {
        renderMatrix(payload.matrix);
      }
    }).catch(function (error) {
      console.error(error);
    }).then(function () {
      if (token === renderToken) setLoading(false);
    });
  }

  function renderGoalOverview(goal) {
    if (!elements.goalOverviewCard) return;
    elements.goalOverviewCard.innerHTML = [
      '<div class="panel goal-panel">',
      '  <div class="goal-panel-head">',
      "    <div>",
      '      <p class="section-kicker">目标管理</p>',
      "      <h3>目标达成概览</h3>",
      '      <p class="goal-panel-copy">按全量固定周期展示，不跟随下方筛选条件和时间框变化。</p>',
      "    </div>",
      '    <div class="goal-panel-meta">',
      '      <span class="summary-badge">销售目标 <strong>' + app.formatCompactCurrency(goal.sales_goal.target_value) + "</strong></span>",
      '      <span class="summary-badge">当前进度 <strong>月度累计</strong></span>',
      '      <span class="summary-badge">毛利率目标 <strong>' + app.formatPercent(goal.margin_goal.target_value) + "</strong></span>",
      "    </div>",
      "  </div>",
      '  <div class="goal-grid">',
      buildGoalCard(goal.sales_goal, "revenue", "当前值", "目标值", false),
      buildGoalCard(goal.current_goal, "current-progress", "当前累计", "累计目标", false),
      buildGoalCard(goal.margin_goal, "margin", "当前值", "目标值", true),
      "  </div>",
      "</div>"
    ].join("");
  }

  function buildGoalCard(item, colorClass, currentLabel, targetLabel, isPercent) {
    var ratio = Number(item.ratio || 0);
    var tone = app.toneFromRatio(ratio);
    var currentValue = isPercent ? app.formatPercent(item.current_value) : app.formatCompactCurrency(item.current_value);
    var targetValue = isPercent ? app.formatPercent(item.target_value) : app.formatCompactCurrency(item.target_value);
    var fillPercent = Math.min((ratio / 1.2) * 100, 100);
    var markerPercent = (1 / 1.2) * 100;
    return [
      '<article class="goal-metric-card ' + colorClass + '">',
      '  <div class="goal-metric-topline">',
      '    <span class="goal-metric-label">' + app.escapeHtml(item.title) + "</span>",
      '    <span class="tag ' + tone + '">' + app.goalStatusLabel(ratio) + "</span>",
      "  </div>",
      '  <div class="goal-metric-values">',
      "    <div><strong>" + currentValue + "</strong><span>" + currentLabel + "</span></div>",
      "    <div><strong>" + targetValue + "</strong><span>" + targetLabel + "</span></div>",
      "  </div>",
      '  <div class="goal-bullet-chart"><div class="goal-bullet-track">',
      '    <div class="goal-bullet-fill ' + colorClass + '" style="width:' + fillPercent.toFixed(1) + '%"></div>',
      '    <span class="goal-bullet-marker" style="left:' + markerPercent.toFixed(1) + '%"></span>',
      '  </div><div class="goal-bullet-axis"><span>0%</span><span>目标线</span><span>120%</span></div></div>',
      '  <div class="goal-metric-foot"><span class="muted">' + app.escapeHtml(item.detail_text) + '</span><span class="delta ' + tone + '">达成 ' + app.formatPercent(ratio) + "</span></div>",
      '  <div class="goal-metric-note">' + app.escapeHtml(item.delta_text) + "</div>",
      "</article>"
    ].join("");
  }

  function loadMonthlyGoals() {
    if (!elements.monthlyGoalCard) return;
    app.apiGet("/api/dashboard/monthly-goals").then(function (payload) {
      monthlyGoalData = payload;
      renderMonthlyGoals();
    }).catch(function (error) {
      console.error(error);
      elements.monthlyGoalCard.innerHTML = "";
    });
  }

  function renderMonthlyGoals() {
    if (!elements.monthlyGoalCard || !monthlyGoalData || !monthlyGoalData.months) return;
    disposeChartsByPrefix("monthly:");
    var metric = getMonthlyMetric(currentMonthlyMetric);
    elements.monthlyGoalCard.innerHTML = [
      '<section class="panel monthly-goal-panel">',
      '  <div class="monthly-goal-head">',
      '    <div>',
      '      <p class="section-kicker">目标管理</p>',
      '      <h3>月度目标完成情况</h3>',
      '      <p class="goal-panel-copy">按全量数据展示每月目标、实际完成与达成率。当前月按截至最新数据日的进度目标计算。</p>',
      '    </div>',
      '    <div id="monthlyGoalTabs" class="segmented-tabs monthly-goal-tabs">',
      monthlyGoalData.metrics.map(function (item) {
        return '<button type="button" class="' + (item.key === currentMonthlyMetric ? "active" : "") + '" data-monthly-metric="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</button>';
      }).join(""),
      "    </div>",
      "  </div>",
      buildMonthlyGoalLegend(),
      '  <div class="monthly-goal-chart-row">',
      '    <div id="monthlyGoalChart" class="monthly-goal-chart"></div>',
      buildMonthlyGoalSummary(metric),
      "  </div>",
      buildMonthlyGoalMatrix(),
      "</section>",
    ].join("");

    Array.from(elements.monthlyGoalCard.querySelectorAll("[data-monthly-metric]")).forEach(function (button) {
      button.addEventListener("click", function () {
        currentMonthlyMetric = this.dataset.monthlyMetric;
        renderMonthlyGoals();
      });
    });
    renderMonthlyGoalChart(metric);
  }

  function buildMonthlyGoalLegend() {
    return [
      '<div class="monthly-goal-legend" aria-label="月度目标图例">',
      '  <span><i class="monthly-legend-bars"><b></b><b></b><b></b></i>实际值：柱状，颜色随完成状态变化</span>',
      '  <span><i class="monthly-legend-line target"></i>目标值：深色实线</span>',
      '  <span><i class="monthly-legend-line rate"></i>完成率：蓝色虚线，右侧百分比轴</span>',
      '  <span><i class="monthly-legend-dot done"></i>已达标</span>',
      '  <span><i class="monthly-legend-dot near"></i>接近目标</span>',
      '  <span><i class="monthly-legend-dot behind"></i>仍需追赶</span>',
      '</div>',
    ].join("");
  }

  function getMonthlyMetric(key) {
    var metrics = monthlyGoalData.metrics || [];
    return metrics.find(function (item) { return item.key === key; }) || metrics[0] || { key: "sales", label: "销售额", type: "currency" };
  }

  function buildMonthlyGoalSummary(metric) {
    var months = monthlyGoalData.months || [];
    var started = months.filter(function (month) {
      return !month.is_future && month.metrics[metric.key] && month.metrics[metric.key].ratio !== null;
    });
    var done = started.filter(function (month) {
      return Number(month.metrics[metric.key].ratio || 0) >= 1;
    }).length;
    var current = months.find(function (month) { return month.is_current; });
    var currentMetric = current && current.metrics[metric.key];
    var ratioText = currentMetric && currentMetric.ratio !== null ? app.formatPercent(currentMetric.ratio) : "—";
    return [
      '<aside class="monthly-goal-summary">',
      '  <span class="label">当前指标</span>',
      '  <strong>' + app.escapeHtml(metric.label) + '</strong>',
      '  <div><span>已达标月份</span><b>' + done + ' / ' + started.length + '</b></div>',
      '  <div><span>当前月达成</span><b>' + ratioText + '</b></div>',
      '  <div><span>数据截至</span><b>' + app.escapeHtml(monthlyGoalData.data_end_date || "—") + '</b></div>',
      '</aside>',
    ].join("");
  }

  function buildMonthlyGoalMatrix() {
    var metrics = monthlyGoalData.metrics || [];
    var months = monthlyGoalData.months || [];
    return [
      '<div class="monthly-goal-matrix">',
      '  <div class="monthly-goal-matrix-head"><span>指标</span>' + months.map(function (month) { return '<span>' + app.escapeHtml(month.label) + '</span>'; }).join("") + '</div>',
      metrics.map(function (metric) {
        return [
          '<div class="monthly-goal-matrix-row">',
          '<button type="button" class="monthly-goal-metric-name ' + (metric.key === currentMonthlyMetric ? "active" : "") + '" data-monthly-metric="' + app.escapeHtml(metric.key) + '">' + app.escapeHtml(metric.label) + '</button>',
          months.map(function (month) {
            var item = month.metrics[metric.key] || {};
            return '<button type="button" class="monthly-goal-cell ' + monthlyStatusClass(item.status) + (metric.key === currentMonthlyMetric ? " active" : "") + '" data-monthly-metric="' + app.escapeHtml(metric.key) + '"><strong>' + (item.ratio === null || item.ratio === undefined ? "—" : app.formatPercent(item.ratio, 0)) + '</strong><span>' + app.escapeHtml(month.label) + '</span></button>';
          }).join(""),
          '</div>',
        ].join("");
      }).join(""),
      '</div>',
    ].join("");
  }

  function monthlyStatusClass(status) {
    if (status === "done") return "done";
    if (status === "near") return "near";
    if (status === "behind") return "behind";
    return "future";
  }

  function renderMonthlyGoalChart(metric) {
    var host = document.getElementById("monthlyGoalChart");
    if (!host || typeof echarts === "undefined") return;
    var months = monthlyGoalData.months || [];
    var labels = months.map(function (month) { return month.label; });
    var actual = months.map(function (month) {
      var item = month.metrics[metric.key] || {};
      return item.actual === null || item.actual === undefined ? null : Number(item.actual || 0);
    });
    var target = months.map(function (month) {
      var item = month.metrics[metric.key] || {};
      return Number(item.progress_target || item.target || 0);
    });
    var ratios = months.map(function (month) {
      var item = month.metrics[metric.key] || {};
      return item.ratio === null || item.ratio === undefined ? null : Number((item.ratio * 100).toFixed(1));
    });
    var chart = echarts.init(host);
    charts["monthly:goal"] = chart;
    chart.setOption({
      animationDuration: 300,
      grid: { left: 58, right: 54, top: 36, bottom: 36 },
      tooltip: {
        trigger: "axis",
        formatter: function (params) {
          var index = params[0].dataIndex;
          var month = months[index];
          var item = month.metrics[metric.key] || {};
          return [
            '<strong>' + app.escapeHtml(month.label) + " " + app.escapeHtml(metric.label) + '</strong>',
            '实际：' + formatMonthlyMetricValue(item.actual, metric.type),
            '目标：' + formatMonthlyMetricValue(item.progress_target, metric.type),
            '完成率：' + (item.ratio === null || item.ratio === undefined ? "—" : app.formatPercent(item.ratio)),
          ].join("<br>");
        }
      },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#53657d" } },
      yAxis: [
        {
          type: "value",
          axisLabel: {
            color: "#53657d",
            formatter: function (value) { return formatMonthlyAxisValue(value, metric.type); }
          },
          splitLine: { lineStyle: { color: "#e6edf6" } }
        },
        {
          type: "value",
          min: 0,
          max: 140,
          axisLabel: { color: "#53657d", formatter: "{value}%" },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          name: "实际",
          type: "bar",
          data: actual.map(function (value, index) {
            var item = months[index].metrics[metric.key] || {};
            return { value: value, itemStyle: { color: item.status === "done" ? "#18a17d" : item.status === "near" ? "#d97706" : item.status === "future" ? "#cbd5e1" : "#cf4f5f" } };
          }),
          barWidth: 24,
          itemStyle: { borderRadius: [6, 6, 0, 0] }
        },
        {
          name: "目标",
          type: "line",
          data: target,
          smooth: true,
          symbolSize: 7,
          lineStyle: { color: "#183456", width: 2 },
          itemStyle: { color: "#183456" }
        },
        {
          name: "完成率",
          type: "line",
          yAxisIndex: 1,
          data: ratios,
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#1769e0", width: 2, type: "dashed" },
          itemStyle: { color: "#1769e0" }
        }
      ]
    });
  }

  function formatMonthlyMetricValue(value, type) {
    if (value === null || value === undefined) return "—";
    if (type === "currency") return app.formatCompactCurrency(value);
    if (type === "percent") return app.formatPercent(value);
    return Number(value || 0).toLocaleString("zh-CN");
  }

  function formatMonthlyAxisValue(value, type) {
    if (type === "currency") return value >= 10000 ? (value / 10000).toFixed(0) + "万" : value;
    if (type === "percent") return (value * 100).toFixed(0) + "%";
    return value >= 10000 ? (value / 10000).toFixed(0) + "万" : value;
  }

  function renderKpis(kpis) {
    if (!elements.kpiGrid) return;
    disposeChartsByPrefix("kpi:");
    elements.kpiGrid.innerHTML = kpis.map(function (item) {
      var value = item.type === "currency"
        ? app.formatCurrency(item.value)
        : item.type === "percent"
          ? app.formatPercent(item.value)
          : Number(item.value || 0).toLocaleString("zh-CN");
      return [
        '<div class="kpi-card">',
        '  <div class="kpi-topline"><span class="kpi-label">' + app.escapeHtml(item.label) + '</span><span class="tag ' + tagClassForMiniLabel(item.mini_label) + '">' + app.escapeHtml(item.mini_label || "概览") + '</span></div>',
        '  <div class="kpi-value">' + value + "</div>",
        '  <div class="kpi-subline"><span class="muted">' + app.escapeHtml(item.description || "当前筛选口径") + '</span>' + (item.delta_text ? ('<span class="delta ' + (item.delta_tone || "warning") + '">' + app.escapeHtml(item.delta_text) + "</span>") : "") + "</div>",
        '  <div class="kpi-trend-chart" id="kpiTrend-' + app.escapeHtml(item.key) + '"></div>',
        "</div>"
      ].join("");
    }).join("");

    kpis.forEach(function (item) {
      var host = document.getElementById("kpiTrend-" + item.key);
      if (!host || typeof echarts === "undefined") return;
      var chartKey = "kpi:" + item.key;
      var chart = echarts.init(host);
      charts[chartKey] = chart;
      chart.setOption(buildKpiTrendOption(item.series || [], item.color || "#4b86df"));
    });
  }

  function tagClassForMiniLabel(label) {
    if (label === "毛利" || label === "风险库存" || label === "投放效率") return "band-focus";
    if (label === "规模" || label === "补货" || label === "广告") return "band-high";
    if (label === "日销") return "band-mid";
    if (label === "库存" || label === "营收占比") return "band-low";
    return "band-low";
  }

  function renderAlertCenter(payload) {
    if (!elements.alertCenterCard) return;
    var items = (payload && payload.items) || [];
    elements.alertCenterCard.innerHTML = [
      '<section class="panel insight-panel alert-panel">',
      '  <div class="insight-head">',
      '    <div>',
      '      <p class="section-kicker">经营预警</p>',
      '      <h3>异常预警中心</h3>',
      '      <p class="goal-panel-copy">跟随当前筛选，优先提示近7天销量下滑、低毛利、排名下滑和库存偏低 SKU。</p>',
      '    </div>',
      '    <span class="summary-badge">统计周期 <strong>' + app.escapeHtml((payload && payload.window) || "-") + '</strong></span>',
      '  </div>',
      items.length ? [
        '<div class="alert-workbench">',
        renderAlertSummary(items),
        '<div class="alert-list">',
        items.map(renderAlertItem).join(""),
        '</div>',
        '</div>',
      ].join("") : '<div class="empty-state compact">' + app.escapeHtml((payload && payload.empty_text) || "当前没有明显异常。") + '</div>',
      '</section>',
    ].join("");

    Array.from(elements.alertCenterCard.querySelectorAll("[data-alert-keyword]")).forEach(function (node) {
      node.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next.keyword = this.dataset.alertKeyword || "";
        next.source = "异常预警 / " + (this.dataset.alertLabel || "");
        next.page = 1;
        window.location.href = "/detail?" + new URLSearchParams(next).toString();
      });
    });
  }

  function renderAlertSummary(items) {
    var definitions = [
      { key: "sales_drop", label: "销量下滑", tone: "negative" },
      { key: "margin_low", label: "低毛利", tone: "warning" },
      { key: "rank_drop", label: "排名下滑", tone: "warning" },
      { key: "stock_short", label: "库存偏低", tone: "negative" },
    ];
    var counts = items.reduce(function (result, item) {
      result[item.type] = (result[item.type] || 0) + 1;
      return result;
    }, {});
    return [
      '<aside class="alert-summary-panel">',
      '  <span class="alert-summary-eyebrow">预警类型</span>',
      '  <strong>' + items.length + '</strong>',
      '  <span class="alert-summary-caption">当前需关注 SKU</span>',
      '  <div class="alert-summary-list">',
      definitions.map(function (item) {
        return [
          '<div class="alert-summary-item ' + app.escapeHtml(item.tone) + '">',
          '  <span>' + app.escapeHtml(item.label) + '</span>',
          '  <strong>' + Number(counts[item.key] || 0).toLocaleString("zh-CN") + '</strong>',
          '</div>',
        ].join("");
      }).join(""),
      '  </div>',
      '</aside>',
    ].join("");
  }

  function renderAlertItem(item) {
    return [
      '<button type="button" class="alert-row ' + app.escapeHtml(item.tone || "warning") + '" data-alert-keyword="' + app.escapeHtml(item.keyword || "") + '" data-alert-label="' + app.escapeHtml(item.label || "") + '">',
      '  <span class="alert-label">' + app.escapeHtml(item.label || "预警") + '</span>',
      '  <span class="alert-main"><strong>' + app.escapeHtml(item.title || "-") + '</strong><small>' + app.escapeHtml(item.subtitle || "-") + '</small></span>',
      '  <span class="alert-detail">' + app.escapeHtml(item.detail || "") + '</span>',
      '  <span class="alert-action">查看</span>',
      '</button>',
    ].join("");
  }

  function renderGoalGap(payload) {
    if (!elements.goalGapCard) return;
    var summary = payload && payload.summary;
    if (!summary) {
      elements.goalGapCard.innerHTML = "";
      return;
    }
    elements.goalGapCard.innerHTML = [
      '<section class="panel insight-panel goal-gap-panel">',
      '  <div class="insight-head">',
      '    <div>',
      '      <p class="section-kicker">缺口参考</p>',
      '      <h3>目标缺口关联板块</h3>',
      '      <p class="goal-panel-copy">' + app.escapeHtml(summary.method || "") + '</p>',
      '    </div>',
      '    <div class="goal-gap-summary">',
      '      <span>进度目标 <strong>' + app.formatCompactCurrency(summary.target_to_date) + '</strong></span>',
      '      <span>实际完成 <strong>' + app.formatCompactCurrency(summary.actual) + '</strong></span>',
      '      <span class="' + (summary.gap > 0 ? "negative" : "positive") + '">' + (summary.gap > 0 ? "总缺口 " : "总超额 ") + '<strong>' + app.formatCompactCurrency(Math.abs(summary.gap || 0)) + '</strong></span>',
      '    </div>',
      '  </div>',
      '  <div class="goal-gap-grid">',
      renderGoalGapGroup("国家站点", (payload.groups && payload.groups.country) || [], summary.gap),
      renderGoalGapGroup("店铺", (payload.groups && payload.groups.store) || [], summary.gap),
      '  </div>',
      '</section>',
    ].join("");
  }

  function renderGoalGapGroup(title, items, totalGap) {
    var maxValue = Math.max.apply(null, items.map(function (item) { return Math.abs(item.gap_contribution || 0); }).concat([1]));
    return [
      '<div class="goal-gap-group">',
      '  <div class="goal-gap-group-head"><strong>' + app.escapeHtml(title) + '</strong><span>按销售占比估算关联金额</span></div>',
      items.map(function (item) {
        var width = Math.max(4, Math.min(100, Math.abs(item.gap_contribution || 0) / maxValue * 100));
        return [
          '<div class="goal-gap-row">',
          '  <div class="goal-gap-name"><strong>' + app.escapeHtml(item.name || "-") + '</strong><span>占比 ' + app.formatPercent(item.share || 0, 1) + ' / 毛利率 ' + app.formatPercent(item.margin || 0, 1) + '</span></div>',
          '  <div class="goal-gap-bar"><i style="width:' + width.toFixed(1) + '%"></i></div>',
          '  <div class="goal-gap-value"><strong>' + app.formatCompactCurrency(Math.abs(item.gap_contribution || 0)) + '</strong><span>' + (totalGap > 0 ? "关联缺口" : "关联超额") + '</span></div>',
          '</div>',
        ].join("");
      }).join("") || '<div class="empty-state compact">暂无拆解数据</div>',
      '</div>',
    ].join("");
  }

  function disposeChartsByPrefix(prefix) {
    Object.keys(charts).forEach(function (key) {
      if (key.indexOf(prefix) !== 0) return;
      if (charts[key]) charts[key].dispose();
      delete charts[key];
    });
  }

  function buildKpiTrendOption(series, color) {
    var data = (series && series.length ? series : [0]).map(function (value) {
      return Number(value || 0);
    });
    var min = Math.min.apply(null, data);
    var max = Math.max.apply(null, data);
    var paddingBase = max - min || Math.abs(max) || 1;
    var padding = paddingBase * 0.18;
    return {
      animationDuration: 260,
      animationDurationUpdate: 180,
      grid: {
        top: 6,
        right: 0,
        bottom: 0,
        left: 0
      },
      tooltip: {
        show: false
      },
      xAxis: {
        type: "category",
        show: false,
        boundaryGap: false,
        data: data.map(function (_, index) {
          return String(index + 1);
        })
      },
      yAxis: {
        type: "value",
        show: false,
        min: min - padding,
        max: max + padding
      },
      series: [
        {
          type: "line",
          data: data,
          showSymbol: false,
          smooth: false,
          symbol: "none",
          silent: true,
          lineStyle: {
            color: color,
            width: 3.2,
            cap: "round",
            join: "round"
          }
        }
      ]
    };
  }

  function renderBandListChart(hostKey, summaryKey, counts, activeValue, stateKey, drillLabel) {
    var summaryHost = elements[summaryKey];
    var host = elements[hostKey];
    if (!summaryHost || !host) return;
    if (charts[hostKey]) {
      charts[hostKey].dispose();
      charts[hostKey] = null;
    }

    var totalItems = counts.reduce(function (sumValue, item) { return sumValue + item.value; }, 0);
    var totalOverLimit = counts.reduce(function (sumValue, item) { return sumValue + item.over_limit; }, 0);
    var highestBand = counts.slice().sort(function (a, b) {
      return b.over_limit - a.over_limit || b.value - a.value;
    })[0];
    var maxCount = Math.max.apply(null, counts.map(function (item) { return item.value; }).concat([1]));
    var maxOverLimit = Math.max.apply(null, counts.map(function (item) { return item.over_limit; }).concat([1]));

    summaryHost.innerHTML = [
      '<span class="summary-badge"><strong>' + totalItems + '</strong> 个 SKU</span>',
      '<span class="summary-badge"><strong>' + totalOverLimit + '</strong> 个超限价</span>',
      '<span class="summary-badge">问题最集中：<strong>' + app.escapeHtml(highestBand ? highestBand.name : "-") + "</strong></span>"
    ].join("");

    host.innerHTML = [
      '<div class="chart-legend-inline">',
      '  <span><i class="legend-swatch safe"></i>颜色越深，代表该指标越高</span>',
      '  <span><i class="legend-swatch risk"></i>风险指标看“超限价数 / 超限价率”</span>',
      "</div>",
      '<div class="heatmap-table">',
      '  <div class="heatmap-head"><div>分层</div><div>SKU 数</div><div>超限价数</div><div>超限价率</div></div>',
      counts.map(function (item) {
        var active = item.name === activeValue;
        var rate = item.value ? item.over_limit / item.value : 0;
        return [
          '<div class="heatmap-row ' + (active ? "active" : "") + '">',
          '  <div class="heatmap-label"><strong>' + app.escapeHtml(item.name) + '</strong><span>点击右侧数字查看明细</span></div>',
          '  <button type="button" class="heatmap-cell heatmap-action neutral" data-value="' + app.escapeHtml(item.name) + '" data-over-limit="all" style="background:' + heatCellColor(item.value / maxCount, "count") + '"><strong>' + item.value + '</strong><span>该层 SKU</span></button>',
          '  <button type="button" class="heatmap-cell heatmap-action risk" data-value="' + app.escapeHtml(item.name) + '" data-over-limit="yes" style="background:' + heatCellColor(item.over_limit / maxOverLimit, "risk") + '"><strong>' + item.over_limit + '</strong><span>超限价 SKU</span></button>',
          '  <div class="heatmap-cell risk" style="background:' + heatCellColor(rate, "rate") + '"><strong>' + app.formatPercent(rate) + '</strong><span>层内超限价率</span></div>',
          "</div>"
        ].join("");
      }).join(""),
      "</div>",
      '<p class="chart-caption">点击“该层 SKU”查看该分层全部明细；点击“超限价 SKU”只查看该分层中超限价的明细。</p>'
    ].join("");

    Array.from(host.querySelectorAll("[data-value][data-over-limit]")).forEach(function (node) {
      node.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next[stateKey] = this.dataset.value;
        next.over_limit = this.dataset.overLimit === "yes" ? "yes" : "all";
        next.source = drillLabel + " / " + this.dataset.value + (next.over_limit === "yes" ? " / 超限价" : " / 全部 SKU");
        next.page = 1;
        window.location.href = "/detail?" + new URLSearchParams(next).toString();
      });
    });
  }

  function heatCellColor(ratio, type) {
    var safe = Math.max(0, Math.min(1, ratio || 0));
    if (type === "count") {
      return "rgba(70, 118, 189, " + (0.10 + safe * 0.35).toFixed(2) + ")";
    }
    if (type === "risk") {
      return "rgba(207, 79, 95, " + (0.12 + safe * 0.42).toFixed(2) + ")";
    }
    return "rgba(217, 119, 6, " + (0.10 + safe * 0.42).toFixed(2) + ")";
  }

  function renderMatrix(matrix) {
    if (!elements.matrixSummary || !elements.matrixChart) return;
    if (charts.matrixChart) {
      charts.matrixChart.dispose();
      charts.matrixChart = null;
    }

    elements.matrixSummary.textContent = "点击矩阵中的任意格子，可以直接跳转到下面的产品明细。";

    var header = [
      "<thead><tr><th></th>",
      matrix.daily_sales_bands.map(function (band) {
        return '<th class="matrix-axis">' + app.escapeHtml(band) + "</th>";
      }).join(""),
      "</tr></thead>"
    ].join("");

    var body = [
      "<tbody>",
      matrix.margin_bands.map(function (marginBand) {
        return [
          "<tr>",
          '<th class="matrix-axis">' + app.escapeHtml(marginBand) + "</th>",
          matrix.daily_sales_bands.map(function (dailyBand) {
              var cell = matrix.cells.find(function (item) {
                return item.margin_band === marginBand && item.daily_sales_band === dailyBand;
              }) || { count: 0, ratio: 0 };
              var hasPrevious = typeof cell.previous_count === "number";
              var changeClass = hasPrevious && cell.count_change_ratio > 0 ? "positive" : hasPrevious && cell.count_change_ratio < 0 ? "negative" : "neutral";
              var active = state.daily_sales_band === dailyBand && state.margin_band === marginBand;
              return [
                "<td>",
                '<button type="button" class="matrix-cell-button ' + (active ? "active" : "") + '" data-daily-band="' + app.escapeHtml(dailyBand) + '" data-margin-band="' + app.escapeHtml(marginBand) + '" style="background:' + matrixCellColor(cell.ratio) + '">',
                '  <span class="matrix-cell-main">',
                '    <span class="matrix-cell-count">' + cell.count + "</span>",
                '    <span class="matrix-cell-meta">占比 ' + app.formatPercent(cell.ratio) + "</span>",
                "  </span>",
                hasPrevious ? '  <span class="matrix-cell-compare"><span>上期 ' + cell.previous_count + '</span><span class="' + changeClass + '">' + formatSignedPercent(cell.count_change_ratio) + "</span></span>" : "",
                "</button>",
                "</td>"
              ].join("");
          }).join(""),
          "</tr>"
        ].join("");
      }).join(""),
      "</tbody>"
    ].join("");

    elements.matrixChart.innerHTML = '<table class="matrix-table">' + header + body + "</table>";
    Array.from(elements.matrixChart.querySelectorAll("[data-daily-band]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var next = Object.assign({}, state);
        next.daily_sales_band = this.dataset.dailyBand;
        next.margin_band = this.dataset.marginBand;
        next.source = "矩阵 / " + this.dataset.marginBand + " × " + this.dataset.dailyBand;
        next.page = 1;
        window.location.href = "/detail?" + new URLSearchParams(next).toString();
      });
    });
  }

    function matrixCellColor(ratio) {
      var safe = Math.max(0, Math.min(1, ratio || 0));
      return "rgba(70, 118, 189, " + (0.10 + safe * 0.35).toFixed(2) + ")";
    }

    function formatSignedPercent(value) {
      if (typeof value !== "number" || !Number.isFinite(value)) return "-";
      if (value === 0) return "0.0%";
      return (value > 0 ? "+" : "") + app.formatPercent(value);
    }
  }());
