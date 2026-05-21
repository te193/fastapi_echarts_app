(function () {
  var app = window.kanbanApp;
  var charts = {};
  var elements = {};
  var topListData = {};
  var matrixData = {};
  var defaultAdjustDate = "";
  var initializedFromUrl = false;

  // Global filter state — passed to every API call
  var filterState = {
    adjust_date: "",
    compare_days: "7",
    country: "all",
    store: "all",
    drop_range: "all",
    risk_level: "all",
    price_band: "all",
    keyword: "",
    page: 1,
    page_size: 20,
  };

  var currentMatrix = "daily_sales";
  var currentTopTab = "sales_up";
  var countryData = [];
  var hiddenCountries = [];

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    initializeFiltersFromUrl();
    syncFilterInputs();
    bindEvents();
    loadCalendar().then(function () {
      refreshAll();
    });
  }

  function initializeFiltersFromUrl() {
    var params = new URLSearchParams(window.location.search || "");
    var urlAdjustDate = params.get("adjust_date");
    var urlCompareDays = params.get("compare_days");
    if (urlAdjustDate) {
      filterState.adjust_date = urlAdjustDate;
      initializedFromUrl = true;
    }
    if (["7", "14", "28"].indexOf(urlCompareDays) >= 0) {
      filterState.compare_days = urlCompareDays;
    }
  }

  function syncFilterInputs() {
    if (elements.adjustDateInput) elements.adjustDateInput.value = filterState.adjust_date || "";
    if (elements.compareDaysSelect) elements.compareDaysSelect.value = filterState.compare_days;
    if (elements.countrySelect) elements.countrySelect.value = filterState.country;
    if (elements.storeSelect) elements.storeSelect.value = filterState.store;
    if (elements.dropRangeSelect) elements.dropRangeSelect.value = filterState.drop_range;
    if (elements.riskLevelSelect) elements.riskLevelSelect.value = filterState.risk_level;
    if (elements.priceBandSelect) elements.priceBandSelect.value = filterState.price_band;
    if (elements.keywordInput) elements.keywordInput.value = filterState.keyword;
  }

  function cacheElements() {
    [
      // Hero
      "pageTitle", "statSkuCount", "statCountryCount", "kpiGrid",
      // Charts
      "dropRangeSkuChart", "dropRangeEffectChart",
      "matrixTabs", "matrixPanelTitle", "matrixChart",
      "countryChart", "countryTableBody",
      "topListTabs", "topListTableBody",
      // Filters
      "adjustDateInput", "compareDaysSelect",
      "countrySelect", "storeSelect", "dropRangeSelect", "riskLevelSelect", "priceBandSelect", "keywordInput",
      "applyFiltersBtn", "resetFiltersBtn",
      // SKU table
      "skuTableCountText", "skuTableBody", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn",
      // Export buttons
      "exportTopListBtn", "exportSkuListBtn",
      // Calendar
      "calendarToggleBtn", "calendarBody", "calendarGrid", "calendarSummary",
      // Country show-all
      "countryShowAllBtn",
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
  }

  function buildQuery(extra) {
    var q = Object.assign({}, filterState, extra || {});
    var parts = [];
    Object.keys(q).forEach(function (k) {
      if (q[k] !== "" && q[k] !== null && q[k] !== undefined) {
        parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(q[k]));
      }
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function refreshAll() {
    setLoading(true);
    updatePageTitle();
    Promise.all([
      loadOverview(),
      loadDropRange(),
      loadMatrices(),
      loadCountries(),
      loadTopLists(),
      loadSkuList(),
    ]).then(function () {
      setLoading(false);
    }).catch(function () {
      setLoading(false);
    });
  }

  function setLoading(isLoading) {
    var main = document.querySelector(".main-content");
    if (main) main.classList.toggle("page-loading", isLoading);
  }

  function updatePageTitle() {
    if (!elements.pageTitle) return;
    var d = filterState.adjust_date;
    var parts = d.split("-");
    var label = parts.length === 3 ? parts[1] + "." + parts[2] : d;
    elements.pageTitle.textContent = label + " 降价前后 " + filterState.compare_days + " 天追踪";
  }

  function bindEvents() {
    // Matrix tabs
    if (elements.matrixTabs) {
      elements.matrixTabs.addEventListener("click", function (event) {
        var button = event.target.closest("[data-matrix]");
        if (!button) return;
        currentMatrix = button.dataset.matrix;
        Array.from(elements.matrixTabs.querySelectorAll("[data-matrix]")).forEach(function (b) {
          b.classList.toggle("active", b.dataset.matrix === currentMatrix);
        });
        renderMatrix(currentMatrix);
      });
    }

    // Top list tabs
    if (elements.topListTabs) {
      elements.topListTabs.addEventListener("click", function (event) {
        var button = event.target.closest("[data-top]");
        if (!button) return;
        currentTopTab = button.dataset.top;
        Array.from(elements.topListTabs.querySelectorAll("[data-top]")).forEach(function (b) {
          b.classList.toggle("active", b.dataset.top === currentTopTab);
        });
        renderTopList(currentTopTab);
      });
    }

    // Apply filters
    if (elements.applyFiltersBtn) {
      elements.applyFiltersBtn.addEventListener("click", function () {
        filterState.adjust_date = elements.adjustDateInput ? elements.adjustDateInput.value : filterState.adjust_date;
        filterState.compare_days = elements.compareDaysSelect ? elements.compareDaysSelect.value : filterState.compare_days;
        filterState.country = elements.countrySelect ? elements.countrySelect.value : "all";
        filterState.store = elements.storeSelect ? elements.storeSelect.value : "all";
        filterState.drop_range = elements.dropRangeSelect ? elements.dropRangeSelect.value : "all";
        // 暂时移除风险等级筛选
        // filterState.risk_level = elements.riskLevelSelect ? elements.riskLevelSelect.value : "all";
        filterState.price_band = elements.priceBandSelect ? elements.priceBandSelect.value : "all";
        filterState.keyword = elements.keywordInput ? elements.keywordInput.value.trim() : "";
        filterState.page = 1;
        refreshAll();
      });
    }

    // Reset filters
    if (elements.resetFiltersBtn) {
      elements.resetFiltersBtn.addEventListener("click", function () {
        if (elements.adjustDateInput) elements.adjustDateInput.value = defaultAdjustDate;
        if (elements.compareDaysSelect) elements.compareDaysSelect.value = "7";
        if (elements.countrySelect) elements.countrySelect.value = "all";
        if (elements.storeSelect) elements.storeSelect.value = "all";
        if (elements.dropRangeSelect) elements.dropRangeSelect.value = "all";
        if (elements.riskLevelSelect) elements.riskLevelSelect.value = "all";
        if (elements.priceBandSelect) elements.priceBandSelect.value = "all";
        if (elements.keywordInput) elements.keywordInput.value = "";

        filterState.adjust_date = defaultAdjustDate;
        filterState.compare_days = "7";
        filterState.country = "all";
        filterState.store = "all";
        filterState.drop_range = "all";
        // 暂时移除风险等级筛选
        // filterState.risk_level = "all";
        filterState.price_band = "all";
        filterState.keyword = "";
        filterState.page = 1;
        refreshAll();
      });
    }

    // Keyword input — debounced auto-apply (SKU list only)
    if (elements.keywordInput) {
      var timer = null;
      elements.keywordInput.addEventListener("input", function () {
        clearTimeout(timer);
        timer = setTimeout(function () {
          filterState.keyword = elements.keywordInput.value.trim();
          filterState.page = 1;
          loadSkuList();
        }, 400);
      });
    }

    // Export buttons
    if (elements.exportTopListBtn) {
      elements.exportTopListBtn.addEventListener("click", function () {
        var url = "/api/price-review/top-lists/export" + buildQuery();
        window.open(url, "_blank");
      });
    }
    if (elements.exportSkuListBtn) {
      elements.exportSkuListBtn.addEventListener("click", function () {
        var extra = { page: null, page_size: null };
        var url = "/api/price-review/skus/export" + buildQuery(extra);
        window.open(url, "_blank");
      });
    }

    window.addEventListener("resize", function () {
      Object.keys(charts).forEach(function (key) {
        if (charts[key]) charts[key].resize();
      });
    });

    // Calendar toggle
    if (elements.calendarToggleBtn && elements.calendarBody) {
      elements.calendarToggleBtn.addEventListener("click", function () {
        var isHidden = elements.calendarBody.style.display === "none";
        elements.calendarBody.style.display = isHidden ? "block" : "none";
        elements.calendarToggleBtn.textContent = isHidden ? "收起" : "展开";
        if (isHidden && !elements.calendarBody.dataset.loaded) {
          elements.calendarBody.dataset.loaded = "1";
          loadCalendar();
        }
      });
    }

    // Country show-all button
    if (elements.countryShowAllBtn) {
      elements.countryShowAllBtn.addEventListener("click", function () {
        hiddenCountries = [];
        renderCountrySection();
      });
    }
  }

  // ===== Calendar =====

  function loadCalendar() {
    if (!elements.calendarGrid) return Promise.resolve();
    return app.apiGet("/api/price-adjustments/daily-counts?days=30")
      .then(function (payload) {
        var items = payload.items || [];
        applyDefaultAdjustDate(items);
        renderCalendar(items);
      })
      .catch(function (err) {
        console.error("Failed to load calendar:", err);
      });
  }

  function applyDefaultAdjustDate(items) {
    if (!items || !items.length) return;
    for (var i = items.length - 1; i >= 0; i -= 1) {
      if (items[i].clickable && items[i].count > 0) {
        defaultAdjustDate = items[i].date;
        if (initializedFromUrl || filterState.adjust_date) return;
        filterState.adjust_date = defaultAdjustDate;
        syncFilterInputs();
        return;
      }
    }
  }

  function renderCalendar(items) {
    if (!elements.calendarGrid) return;
    if (!items || !items.length) {
      elements.calendarGrid.innerHTML = '<div class="empty-state">暂无数据</div>';
      return;
    }

    var total = items.reduce(function (s, i) { return s + i.count; }, 0);
    var activeDays = items.filter(function (i) { return i.count > 0; }).length;

    if (elements.calendarSummary) {
      elements.calendarSummary.textContent = "最近 30 天累计调价 " + total + " 个，有调价天数 " + activeDays + " 天";
    }

    function heatClass(count) {
      if (count === 0) return "heat-0";
      if (count <= 50) return "heat-1";
      if (count <= 200) return "heat-2";
      if (count <= 400) return "heat-3";
      if (count <= 800) return "heat-4";
      return "heat-5";
    }

    var html = [];
    items.forEach(function (item) {
      var hClass = heatClass(item.count);
      var todayClass = item.is_today ? " today" : "";
      var weekendClass = item.is_weekend ? " weekend" : "";
      var href = "/price-review?adjust_date=" + encodeURIComponent(item.date);
      var tag = item.clickable ? "a" : "div";
      var hrefAttr = item.clickable ? ' href="' + href + '"' : "";
      var disabledClass = item.clickable ? "" : " disabled";

      html.push(
        '<' + tag + ' class="calendar-card ' + hClass + todayClass + weekendClass + disabledClass + '"' + hrefAttr + ' title="' + item.date + ' 调价 ' + item.count + ' 个产品">' +
        '  <span class="calendar-date">' + item.display_date + '</span>' +
        '  <span class="calendar-weekday">' + item.weekday + '</span>' +
        '  <span class="calendar-count">' + item.count + '</span>' +
        '  <span class="calendar-label">个产品调价</span>' +
        '</' + tag + '>'
      );
    });

    elements.calendarGrid.innerHTML = html.join("");
  }

  // ===== Overview / KPIs =====

  function loadOverview() {
    return app.apiGet("/api/price-review/overview" + buildQuery()).then(function (payload) {
      if (elements.statSkuCount) elements.statSkuCount.textContent = (payload.sku_count || 0).toLocaleString("zh-CN");
      if (elements.statCountryCount) elements.statCountryCount.textContent = (payload.country_count || 0).toLocaleString("zh-CN");
      renderKpis(payload.kpis || []);
    });
  }

  function renderKpis(kpis) {
    if (!elements.kpiGrid) return;
    elements.kpiGrid.innerHTML = kpis.map(function (item) {
      var beforeVal = formatValue(item.before, item.type);
      var afterVal = formatValue(item.after, item.type);
      var changePrefix = item.change > 0 ? "+" : "";
      var changeRateText = item.change_rate ? (" (" + changePrefix + app.formatPercent(item.change_rate, 1) + ")") : "";
      var tone = item.tone || "warning";
      var arrow = item.change > 0 ? "↑" : item.change < 0 ? "↓" : "→";
      return [
        '<div class="kpi-card">',
        '  <div class="kpi-topline"><span class="kpi-label">' + app.escapeHtml(item.label) + '</span><span class="tag ' + tagClassForKpi(item.key) + '">' + app.escapeHtml(interpretationLabel(item.key)) + '</span></div>',
        '  <div class="kpi-value">' + afterVal + '</div>',
        '  <div class="kpi-subline">',
        '    <span class="muted">前' + filterState.compare_days + '天: ' + beforeVal + '</span>',
        '    <span class="delta ' + tone + '" style="font-weight:800">' + arrow + " " + changePrefix + formatValue(item.change, item.type) + changeRateText + '</span>',
        '  </div>',
        '</div>'
      ].join("");
    }).join("");
  }

  function tagClassForKpi(key) {
    if (["sales", "revenue", "daily_sales"].indexOf(key) >= 0) return "band-high";
    if (["margin", "cvr", "ctr"].indexOf(key) >= 0) return "band-focus";
    if (["sessions", "acos", "tacos"].indexOf(key) >= 0) return "band-mid";
    return "band-low";
  }

  function interpretationLabel(key) {
    var map = { sales: "成交", revenue: "收入", margin: "效率", sessions: "流量", acos: "广告", tacos: "广告", ad_spend: "投放", daily_sales: "日销", cvr: "转化", ctr: "点击" };
    return map[key] || "指标";
  }

  function formatValue(value, type) {
    if (type === "currency") return app.formatCurrency(value);
    if (type === "percent") return app.formatPercent(value, 1);
    return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  // ===== Drop Range Analysis =====

  function loadDropRange() {
    return app.apiGet("/api/price-review/drop-range" + buildQuery()).then(function (payload) {
      renderDropRangeCharts(payload.items || []);
    });
  }

  function renderDropRangeCharts(items) {
    if (!items.length) return;
    var labels = items.map(function (i) { return i.label; });
    var skuCounts = items.map(function (i) { return i.sku_count; });
    var salesChangeRates = items.map(function (i) { return parseFloat((i.sales_change_rate * 100).toFixed(1)); });
    var marginsAfter = items.map(function (i) { return parseFloat((i.margin_after * 100).toFixed(1)); });

    if (elements.dropRangeSkuChart) {
      var chart1 = echarts.init(elements.dropRangeSkuChart);
      charts.dropRangeSku = chart1;
      chart1.setOption({
        tooltip: { trigger: "axis" },
        grid: { left: 20, right: 20, top: 20, bottom: 34 },
        xAxis: { type: "category", data: labels, axisLabel: { color: "#5f7086" } },
        yAxis: { type: "value", axisLabel: { color: "#5f7086" }, splitLine: { lineStyle: { color: "#e4ebf5" } } },
        series: [{
          type: "bar",
          data: skuCounts,
          itemStyle: { color: "#1769e0", borderRadius: [6, 6, 0, 0] },
          barWidth: "50%",
          label: { show: true, position: "top", color: "#132238" }
        }]
      });
    }

    if (elements.dropRangeEffectChart) {
      var chart2 = echarts.init(elements.dropRangeEffectChart);
      charts.dropRangeEffect = chart2;
      chart2.setOption({
        tooltip: {
          trigger: "axis",
          confine: true,
          axisPointer: { type: "shadow" }
        },
        legend: {
          data: ["销量变化率", "后毛利率"],
          top: 8,
          right: 16,
          textStyle: { color: "#5f7086" }
        },
        grid: { left: 64, right: 64, top: 72, bottom: 72, containLabel: false },
        xAxis: {
          type: "category",
          data: labels,
          axisLabel: { color: "#5f7086", interval: 0 },
          axisLine: { lineStyle: { color: "#d5deeb" } }
        },
        yAxis: [
          {
            type: "value",
            name: "销量变化率",
            position: "left",
            nameTextStyle: { color: "#5f7086", padding: [0, 0, 0, -8] },
            axisLabel: { color: "#5f7086", formatter: "{value}%" },
            splitLine: { lineStyle: { color: "#e4ebf5" } }
          },
          {
            type: "value",
            name: "店毛利率",
            position: "right",
            nameTextStyle: { color: "#5f7086", padding: [0, -8, 0, 0] },
            axisLabel: { color: "#5f7086", formatter: "{value}%" },
            splitLine: { show: false }
          }
        ],
        series: [
          { name: "销量变化率", type: "bar", data: salesChangeRates, itemStyle: { color: "#18a17d", borderRadius: [4, 4, 0, 0] }, barWidth: "30%" },
          { name: "后毛利率", type: "line", yAxisIndex: 1, data: marginsAfter, itemStyle: { color: "#cf4f5f" }, lineStyle: { width: 3 }, symbol: "circle", symbolSize: 8 }
        ]
      });
    }
  }

  // ===== Matrices =====

  function loadMatrices() {
    return app.apiGet("/api/price-review/matrices" + buildQuery()).then(function (payload) {
      matrixData = payload;
      renderMatrix(currentMatrix);
    });
  }

  function renderMatrix(type) {
    var data = matrixData[type];
    if (!data || !data.rows) return;
    var titleMap = { sales: "销量分层", daily_sales: "日销分层", margin: "毛利率分层", rank: "排名分层" };
    if (elements.matrixPanelTitle) {
      elements.matrixPanelTitle.textContent = titleMap[type] + " — 调价前后 SKU 数量与占比变化";
    }

    var rows = data.rows;
    var totalBefore = rows.reduce(function (s, r) { return s + r.sku_before; }, 0);
    var totalAfter = rows.reduce(function (s, r) { return s + r.sku_after; }, 0);

    var html = [
      '<table class="matrix-table">',
      '  <thead><tr><th>分层</th><th>调前 SKU</th><th>调前占比</th><th>调后 SKU</th><th>调后占比</th><th>SKU 变化</th></tr></thead>',
      '  <tbody>'
    ];

    rows.forEach(function (row) {
      var changeClass = row.sku_change > 0 ? "positive" : row.sku_change < 0 ? "negative" : "neutral";
      var changePrefix = row.sku_change > 0 ? "+" : "";
      html.push([
        '<tr>',
        '  <th class="matrix-axis">' + app.escapeHtml(row.band) + '</th>',
        '  <td><strong>' + row.sku_before + '</strong></td>',
        '  <td>' + app.formatPercent(row.sku_before_ratio, 1) + '</td>',
        '  <td><strong>' + row.sku_after + '</strong></td>',
        '  <td>' + app.formatPercent(row.sku_after_ratio, 1) + '</td>',
        '  <td><span class="' + changeClass + '" style="font-weight:800">' + changePrefix + row.sku_change + '</span></td>',
        '</tr>'
      ].join(""));
    });

    html.push([
      '<tr style="border-top:2px solid #d5deeb;font-weight:800">',
      '  <th class="matrix-axis">合计</th>',
      '  <td>' + totalBefore + '</td>',
      '  <td>100%</td>',
      '  <td>' + totalAfter + '</td>',
      '  <td>100%</td>',
      '  <td>' + (totalAfter - totalBefore) + '</td>',
      '</tr>'
    ].join(""));

    html.push('  </tbody></table>');
    if (elements.matrixChart) elements.matrixChart.innerHTML = html.join("");
  }

  // ===== Countries =====

  function loadCountries() {
    return app.apiGet("/api/price-review/countries" + buildQuery()).then(function (payload) {
      countryData = payload.items || [];
      renderCountrySection();
    });
  }

  function renderCountrySection() {
    var visible = countryData.filter(function (i) {
      return hiddenCountries.indexOf(i.country) === -1;
    });
    renderCountryChart(visible);
    renderCountryTable(visible);
    if (elements.countryShowAllBtn) {
      elements.countryShowAllBtn.style.display = hiddenCountries.length ? "inline-flex" : "none";
    }
  }

  function renderCountryChart(items) {
    if (!elements.countryChart) return;
    var chart = echarts.init(elements.countryChart);
    charts.country = chart;

    if (!items.length) {
      chart.setOption({ xAxis: { data: [] }, series: [{ data: [] }, { data: [] }, { data: [] }] }, true);
      return;
    }

    var countries = items.map(function (i) { return i.country; });
    var salesChanges = items.map(function (i) { return i.sales_change; });

    function makeBarData(values, color) {
      return values.map(function (v) {
        var r = v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4];
        return { value: v, itemStyle: { color: color, borderRadius: r } };
      });
    }
    var revenueChanges = makeBarData(items.map(function (i) { return parseFloat(i.revenue_change.toFixed(0)); }), "#d97706");
    var profitChanges = makeBarData(items.map(function (i) { return parseFloat(i.profit_change.toFixed(0)); }), "#18a17d");

    chart.off("click");
    chart.on("click", function (params) {
      if (params.componentType === "xAxis") {
        var country = params.value;
        var idx = hiddenCountries.indexOf(country);
        if (idx === -1) {
          hiddenCountries.push(country);
        } else {
          hiddenCountries.splice(idx, 1);
        }
        renderCountrySection();
      }
    });

    chart.setOption({
      tooltip: {
        trigger: "axis",
        confine: true,
        axisPointer: { type: "cross" }
      },
      legend: {
        data: [
          { name: "销量变化", icon: "circle" },
          { name: "销售额变化", icon: "roundRect" },
          { name: "毛利润变化", icon: "rect" }
        ],
        top: 8,
        right: 16,
        textStyle: { color: "#5f7086" }
      },
      grid: { left: 64, right: 88, top: 72, bottom: 64, containLabel: false },
      xAxis: {
        type: "category",
        data: countries,
        axisLabel: { color: "#5f7086", interval: 0 },
        axisLine: { lineStyle: { color: "#9aa8bc" } },
        axisTick: { alignWithLabel: true },
        triggerEvent: true
      },
      yAxis: [
        {
          type: "value",
          name: "金额变化（¥）",
          position: "right",
          nameTextStyle: { color: "#5f7086", padding: [0, -8, 0, 0] },
          axisLabel: {
            color: "#5f7086",
            formatter: function (v) {
              var absV = Math.abs(v);
              if (absV >= 10000) return "¥" + (v / 10000).toFixed(1) + "w";
              if (absV >= 1000) return "¥" + (v / 1000).toFixed(0) + "k";
              return "¥" + v;
            }
          },
          splitLine: { show: false }
        },
        {
          type: "value",
          name: "销量变化",
          position: "left",
          nameTextStyle: { color: "#5f7086", padding: [0, 0, 0, -8] },
          axisLabel: { color: "#5f7086" },
          splitLine: { lineStyle: { color: "#e4ebf5" } }
        }
      ],
      series: [
        {
          name: "销量变化",
          type: "line",
          data: salesChanges,
          itemStyle: { color: "#1769e0" },
          lineStyle: { width: 3 },
          symbol: "circle",
          symbolSize: 8,
          yAxisIndex: 1
        },
        {
          name: "销售额变化",
          type: "bar",
          yAxisIndex: 0,
          data: revenueChanges,
          barWidth: "28%",
          itemStyle: { color: "#d97706" },
          markLine: {
            data: [{ yAxis: 0 }],
            lineStyle: { color: "#9aa8bc", type: "dashed", width: 1 },
            symbol: "none",
            label: { show: false }
          }
        },
        {
          name: "毛利润变化",
          type: "bar",
          yAxisIndex: 0,
          data: profitChanges,
          barWidth: "28%",
          itemStyle: { color: "#18a17d" }
        }
      ]
    });
  }

  function renderCountryTable(items) {
    if (!elements.countryTableBody) return;
    if (!items.length) {
      elements.countryTableBody.innerHTML = '<tr><td colspan="13"><div class="empty-state">暂无数据</div></td></tr>';
      return;
    }
    elements.countryTableBody.innerHTML = items.map(function (item) {
      return [
        '<tr>',
        '<td><strong>' + app.escapeHtml(item.country) + '</strong></td>',
        '<td>' + item.sku_count + '</td>',
        '<td>' + (item.sales_change > 0 ? "+" : "") + item.sales_change + '</td>',
        '<td>' + app.formatCurrency(item.revenue_change) + '</td>',
        '<td>' + app.formatCurrency(item.profit_change) + '</td>',
        '<td>' + app.formatPercent(item.margin_after, 1) + '</td>',
        '<td>' + app.formatPercent(item.margin_before, 1) + '</td>',
        '<td>' + item.rank_worsen_count + '</td>',
        '<td>' + item.rank_improve_count + '</td>',
        '<td>' + item.out_of_stock_count + '</td>',
        '<td>' + item.profit_down_count + '</td>',
        '<td>' + app.formatPercent(item.rank_worsen_ratio, 1) + '</td>',
        '<td>' + app.formatPercent(item.rank_improve_ratio, 1) + '</td>',
        '</tr>'
      ].join("");
    }).join("");
  }

  // ===== Top Lists =====

  function loadTopLists() {
    return app.apiGet("/api/price-review/top-lists" + buildQuery()).then(function (payload) {
      topListData = payload;
      renderTopList(currentTopTab);
    });
  }

  function renderTopList(tab) {
    var items = topListData[tab] || [];
    if (!elements.topListTableBody) return;
    if (!items.length) {
      elements.topListTableBody.innerHTML = '<tr><td colspan="14"><div class="empty-state">暂无数据</div></td></tr>';
      return;
    }
    elements.topListTableBody.innerHTML = items.map(function (item) {
      var salesChangeClass = item.sales_change > 0 ? "positive" : item.sales_change < 0 ? "negative" : "neutral";
      var rankChangeClass = item.rank_change < 0 ? "positive" : item.rank_change > 0 ? "negative" : "neutral";
      return [
        '<tr>',
        '<td>' + app.escapeHtml(item.country) + '</td>',
        '<td>' + app.escapeHtml(item.store) + '</td>',
        '<td><strong>' + app.escapeHtml(item.msku) + '</strong></td>',
        '<td>' + item.sales_before + '</td>',
        '<td>' + item.sales_after + '</td>',
        '<td><span class="' + salesChangeClass + '" style="font-weight:800">' + (item.sales_change > 0 ? "+" : "") + item.sales_change + '</span></td>',
        '<td>' + Number(item.daily_sales_before).toFixed(2) + '</td>',
        '<td>' + Number(item.daily_sales_after).toFixed(2) + '</td>',
        '<td>' + (item.daily_sales_change > 0 ? "+" : "") + Number(item.daily_sales_change).toFixed(2) + '</td>',
        '<td>' + app.formatCurrency(item.profit_change) + '</td>',
        '<td>' + (item.margin_before ? app.formatPercent(item.margin_before, 1) : "—") + '</td>',
        '<td>' + (item.margin_after ? app.formatPercent(item.margin_after, 1) : "—") + '</td>',
        '<td><span class="' + rankChangeClass + '" style="font-weight:800">' + (item.rank_change > 0 ? "+" : "") + item.rank_change + '</span></td>',
        '<td>' + (item.rank_after || '—') + '</td>',
        '</tr>'
      ].join("");
    }).join("");
  }

  function riskTagHtml(level) {
    if (!level) return '—';
    var cls = level === "高" ? "priority-p0" : level === "中" ? "priority-p1" : level === "低" ? "priority-p2" : "";
    return '<span class="tag ' + cls + '">' + app.escapeHtml(level) + '</span>';
  }

  // ===== SKU List =====

  function loadSkuList() {
    return app.apiGet("/api/price-review/skus" + buildQuery()).then(function (payload) {
      populateFilters(payload.filters || {});
      renderSkuTable(payload.rows || [], payload.total);
      renderPagination(payload);
    });
  }

  function populateFilters(filters) {
    populateSelect(elements.countrySelect, filters.countries || [], filterState.country, "全部国家");
    populateSelect(elements.storeSelect, filters.stores || [], filterState.store, "全部店铺");
    populateSelect(elements.dropRangeSelect, filters.drop_ranges || [], filterState.drop_range, "全部幅度");
    // 暂时移除风险等级筛选（数据不完整）
    // populateSelect(elements.riskLevelSelect, filters.risk_levels || [], filterState.risk_level, "全部风险");
    populateSelect(elements.priceBandSelect, filters.price_bands || [], filterState.price_band, "全部价格");
  }

  function populateSelect(el, options, currentValue, defaultLabel) {
    if (!el) return;
    var html = '<option value="all">' + defaultLabel + '</option>';
    options.forEach(function (opt) {
      html += '<option value="' + app.escapeHtml(opt) + '"' + (opt === currentValue ? " selected" : "") + '>' + app.escapeHtml(opt) + '</option>';
    });
    el.innerHTML = html;
  }

  function renderSkuTable(rows, total) {
    if (elements.skuTableCountText) {
      elements.skuTableCountText.textContent = "共 " + total + " 条";
    }
    if (!elements.skuTableBody) return;
    if (!rows.length) {
      elements.skuTableBody.innerHTML = '<tr><td colspan="15"><div class="empty-state">当前筛选条件下无数据</div></td></tr>';
      return;
    }
    elements.skuTableBody.innerHTML = rows.map(function (item) {
      var salesChangeClass = item.sales_change > 0 ? "positive" : item.sales_change < 0 ? "negative" : "neutral";
      var marginChangeClass = item.margin_change > 0 ? "positive" : item.margin_change < 0 ? "negative" : "neutral";
      var dailySalesChangeClass = item.daily_sales_change > 0 ? "positive" : item.daily_sales_change < 0 ? "negative" : "neutral";
      return [
        '<tr>',
        '<td>' + app.escapeHtml(item.country) + '</td>',
        '<td>' + app.escapeHtml(item.store) + '</td>',
        '<td><strong>' + app.escapeHtml(item.msku) + '</strong></td>',
        '<td>' + item.price_before + '</td>',
        '<td>' + item.price_after + '</td>',
        '<td>' + app.formatPercent(item.drop_ratio, 1) + '</td>',
        '<td>' + item.sales_before + '</td>',
        '<td>' + item.sales_after + '</td>',
        '<td><span class="' + salesChangeClass + '" style="font-weight:800">' + (item.sales_change > 0 ? "+" : "") + item.sales_change + '</span></td>',
        '<td>' + Number(item.daily_sales_before || 0).toFixed(2) + '</td>',
        '<td>' + Number(item.daily_sales_after || 0).toFixed(2) + '</td>',
        '<td><span class="' + dailySalesChangeClass + '" style="font-weight:800">' + (item.daily_sales_change > 0 ? "+" : "") + Number(item.daily_sales_change || 0).toFixed(2) + '</span></td>',
        '<td>' + (item.margin_before ? app.formatPercent(item.margin_before, 1) : "—") + '</td>',
        '<td>' + (item.margin_after ? app.formatPercent(item.margin_after, 1) : "—") + '</td>',
        '<td><span class="' + marginChangeClass + '" style="font-weight:800">' + (item.margin_change > 0 ? "+" : "") + app.formatPercent(item.margin_change, 1) + '</span></td>',
        '</tr>'
      ].join("");
    }).join("");
  }

  function renderPagination(payload) {
    if (!elements.paginationInfo) return;
    elements.paginationInfo.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + payload.total + " 条";
    if (elements.prevPageBtn) elements.prevPageBtn.disabled = payload.page <= 1;
    if (elements.nextPageBtn) elements.nextPageBtn.disabled = payload.page >= payload.total_pages;

    if (elements.prevPageBtn) {
      elements.prevPageBtn.onclick = function () {
        if (payload.page <= 1) return;
        filterState.page = payload.page - 1;
        loadSkuList();
      };
    }
    if (elements.nextPageBtn) {
      elements.nextPageBtn.onclick = function () {
        if (payload.page >= payload.total_pages) return;
        filterState.page = payload.page + 1;
        loadSkuList();
      };
    }

    var startPage = Math.max(1, payload.page - 2);
    var endPage = Math.min(payload.total_pages, payload.page + 2);
    var pages = [];
    for (var i = startPage; i <= endPage; i++) pages.push(i);

    if (elements.paginationNumbers) {
      elements.paginationNumbers.innerHTML = pages.map(function (p) {
        return '<button type="button" class="page-number ' + (p === payload.page ? "active" : "") + '" data-page="' + p + '" data-source="sku">' + p + '</button>';
      }).join("");

      Array.from(elements.paginationNumbers.querySelectorAll('[data-source="sku"]')).forEach(function (btn) {
        btn.addEventListener("click", function () {
          filterState.page = Number(this.dataset.page);
          loadSkuList();
        });
      });
    }
  }
}());
