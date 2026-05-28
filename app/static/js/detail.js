(function () {
  var app = window.kanbanApp;
  var state = app.readQueryState();
  var meta = null;
  var trendChart = null;
  var datePicker = null;
  var elements = {};
  var tableRenderToken = 0;
  var detailColumnFilters = {};

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
      renderTable();
      if (state.source && elements.detailSourceText) elements.detailSourceText.textContent = state.source;
    });
  }

  function cacheElements() {
    [
      "startDateInput", "endDateInput", "siteSelect", "storeSelect", "overLimitSelect",
      "dailySalesBandSelect", "marginBandSelect", "keywordInput",
      "clearFiltersBtn", "periodQuickButtons", "activeFilterChips", "tableCountText", "skuTableBody", "paginationInfo",
      "paginationNumbers", "prevPageBtn", "nextPageBtn", "detailSourceText", "detailDrawer",
      "drawerMask", "closeDrawerBtn", "drawerTitle", "drawerContent", "exportRawCsvBtn"
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
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = this.value;
        state.page = 1;
        syncControls();
        renderTable();
      });
    });

    elements.keywordInput.addEventListener("input", function () {
      state.keyword = this.value.trim();
      state.page = 1;
      syncControls();
      renderTable();
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
      detailColumnFilters = {};
      closeColumnFilterPopover();
      syncControls();
      renderTable();
    });

    elements.closeDrawerBtn.addEventListener("click", closeDrawer);
    elements.drawerMask.addEventListener("click", closeDrawer);
    if (elements.exportRawCsvBtn) {
      elements.exportRawCsvBtn.addEventListener("click", exportRawCsv);
    }
    bindDetailColumnFilters();
    window.addEventListener("resize", function () {
      if (trendChart) trendChart.resize();
    });
  }

  function applyQuickPeriod(period) {
    var range = app.resolveQuickPeriodRange(period, meta.default_end_date);
    if (!range) return;
    state.start_date = range.start_date;
    state.end_date = range.end_date;
    state.page = 1;
    syncControls();
    renderTable();
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
        renderTable();
      }
    });
  }

  function setLoading(isLoading) {
    var main = document.querySelector(".main-content");
    if (main) main.classList.toggle("page-loading", isLoading);
  }

  function buildDetailParams(extra) {
    var params = Object.assign({}, state, extra || {});
    Object.keys(detailColumnFilters).forEach(function (key) {
      var value = detailColumnFilters[key];
      if (value !== "" && value !== null && value !== undefined) {
        params["cf_" + key] = value;
      }
    });
    return params;
  }

  function bindDetailColumnFilters() {
    document.querySelectorAll("[data-detail-filter-key]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openColumnFilterPopover(button);
      });
    });

    document.addEventListener("click", function (event) {
      var popover = document.querySelector(".column-filter-popover");
      if (!popover) return;
      if (event.target.closest("[data-filter-apply]")) {
        event.preventDefault();
        applyColumnFilter(popover);
        return;
      }
      if (event.target.closest("[data-filter-clear]")) {
        event.preventDefault();
        clearColumnFilter(popover.dataset.filterKey, popover.dataset.filterType || "text");
        return;
      }
      if (popover.contains(event.target)) return;
      if (event.target.closest("[data-detail-filter-key]")) return;
      closeColumnFilterPopover();
    });
  }

  function activeColumnFilterValue(key, type) {
    if (type === "number") {
      return {
        min: detailColumnFilters[key + "_min"] || "",
        max: detailColumnFilters[key + "_max"] || "",
      };
    }
    return detailColumnFilters[key] || "";
  }

  function openColumnFilterPopover(button) {
    closeColumnFilterPopover();

    var key = button.dataset.detailFilterKey;
    var type = button.dataset.detailFilterType || "text";
    var rect = button.getBoundingClientRect();
    var value = activeColumnFilterValue(key, type);
    var popover = document.createElement("div");
    popover.className = "column-filter-popover";
    popover.dataset.filterKey = key;
    popover.dataset.filterType = type;

    if (type === "number") {
      popover.innerHTML = [
        '<label>最小值<input type="number" step="any" data-filter-min value="' + app.escapeHtml(value.min) + '"></label>',
        '<label>最大值<input type="number" step="any" data-filter-max value="' + app.escapeHtml(value.max) + '"></label>',
        '<div class="column-filter-actions">',
        '<button type="button" class="primary" data-filter-apply>筛选</button>',
        '<button type="button" data-filter-clear>清除</button>',
        '</div>',
      ].join("");
    } else {
      popover.innerHTML = [
        '<label>包含文本<input type="text" data-filter-text value="' + app.escapeHtml(value) + '" placeholder="输入关键词"></label>',
        '<div class="column-filter-actions">',
        '<button type="button" class="primary" data-filter-apply>筛选</button>',
        '<button type="button" data-filter-clear>清除</button>',
        '</div>',
      ].join("");
    }

    document.body.appendChild(popover);
    var top = rect.bottom + window.scrollY + 8;
    var left = rect.left + window.scrollX;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12;
    popover.style.top = top + "px";
    popover.style.left = Math.max(12 + window.scrollX, Math.min(left, maxLeft)) + "px";

    var firstInput = popover.querySelector("input");
    if (firstInput) {
      firstInput.focus();
      firstInput.select();
    }

    popover.addEventListener("keydown", function (event) {
      if (event.key === "Enter") applyColumnFilter(popover);
      if (event.key === "Escape") closeColumnFilterPopover();
    });
    popover.addEventListener("pointerdown", function (event) {
      if (event.target.closest("[data-filter-apply]")) {
        event.preventDefault();
        applyColumnFilter(popover);
      }
      if (event.target.closest("[data-filter-clear]")) {
        event.preventDefault();
        clearColumnFilter(key, type);
      }
    });
  }

  function closeColumnFilterPopover() {
    var popover = document.querySelector(".column-filter-popover");
    if (popover) popover.remove();
  }

  function applyColumnFilter(popover) {
    var key = popover.dataset.filterKey;
    var type = popover.dataset.filterType || "text";
    if (type === "number") {
      setColumnFilterValue(key + "_min", popover.querySelector("[data-filter-min]").value.trim());
      setColumnFilterValue(key + "_max", popover.querySelector("[data-filter-max]").value.trim());
    } else {
      setColumnFilterValue(key, popover.querySelector("[data-filter-text]").value.trim());
    }
    state.page = 1;
    closeColumnFilterPopover();
    renderTable();
  }

  function clearColumnFilter(key, type) {
    if (type === "number") {
      delete detailColumnFilters[key + "_min"];
      delete detailColumnFilters[key + "_max"];
    } else {
      delete detailColumnFilters[key];
    }
    state.page = 1;
    closeColumnFilterPopover();
    renderTable();
  }

  function setColumnFilterValue(key, value) {
    if (value === "") {
      delete detailColumnFilters[key];
    } else {
      detailColumnFilters[key] = value;
    }
  }

  function updateDetailColumnFilterButtons() {
    document.querySelectorAll("[data-detail-filter-key]").forEach(function (button) {
      var key = button.dataset.detailFilterKey;
      var type = button.dataset.detailFilterType || "text";
      var isActive = type === "number"
        ? Boolean(detailColumnFilters[key + "_min"] || detailColumnFilters[key + "_max"])
        : Boolean(detailColumnFilters[key]);
      button.classList.toggle("active", isActive);
    });
  }

  function formatOriginalPrice(value) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
  }

  function renderTable() {
    var token = ++tableRenderToken;
    setLoading(true);
    app.writeQueryState(state);
    app.apiGet("/api/detail", buildDetailParams({ page_size: 15 })).then(function (payload) {
      elements.tableCountText.textContent = "当前明细 " + payload.total + " 条";
      renderRows(payload.rows);
      renderPagination(payload);
      updateDetailColumnFilterButtons();
    }).catch(function (error) {
      console.error(error);
    }).then(function () {
      if (token === tableRenderToken) setLoading(false);
    });
  }

  function renderRows(rows) {
    if (!rows.length) {
      elements.skuTableBody.innerHTML = '<tr><td colspan="17"><div class="empty-state">当前筛选条件下没有产品，请调整条件后再查看。</div></td></tr>';
      return;
    }

    elements.skuTableBody.innerHTML = rows.map(function (item) {
      return [
        '<tr data-id="' + item.id + '">',
        "<td>" + item.country + "</td>",
        "<td>" + item.store + "</td>",
        "<td><strong>" + item.msku + "</strong></td>",
        "<td>" + item.daily_sales + "</td>",
        "<td>" + item.daily_sales_band + "</td>",
        "<td>" + app.formatPercent(item.order_gross_margin) + "</td>",
        "<td>" + item.margin_band + "</td>",
        "<td>" + item.sales_7d + "</td>",
        "<td>" + item.sales_30d + "</td>",
        "<td>" + app.formatCurrency(item.revenue_30d) + "</td>",
        "<td>" + formatOriginalPrice(item.current_price) + "</td>",
        "<td>" + formatOriginalPrice(item.limit_price_35 == null ? item.limit_price : item.limit_price_35) + "</td>",
        "<td>" + formatOriginalPrice(item.limit_price_10) + "</td>",
        "<td>" + formatOriginalPrice(item.price_gap) + "</td>",
        "<td>" + (item.over_limit ? "是" : "否") + "</td>",
        "<td>" + item.fba_sellable_inventory + "</td>",
        "<td>" + item.stock_days + "</td>",
        "</tr>"
      ].join("");
    }).join("");

    Array.from(elements.skuTableBody.querySelectorAll("[data-id]")).forEach(function (row) {
      row.addEventListener("click", function () {
        openDrawer(this.dataset.id, 30);
      });
    });
  }

  function renderPagination(payload) {
    elements.paginationInfo.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页，共 " + payload.total + " 条";
    elements.prevPageBtn.disabled = payload.page <= 1;
    elements.nextPageBtn.disabled = payload.page >= payload.total_pages;

    elements.prevPageBtn.onclick = function () {
      if (payload.page <= 1) return;
      state.page = payload.page - 1;
      renderTable();
    };

    elements.nextPageBtn.onclick = function () {
      if (payload.page >= payload.total_pages) return;
      state.page = payload.page + 1;
      renderTable();
    };

    var startPage = Math.max(1, payload.page - 2);
    var endPage = Math.min(payload.total_pages, payload.page + 2);
    var pages = [];
    for (var index = startPage; index <= endPage; index += 1) pages.push(index);

    elements.paginationNumbers.innerHTML = pages.map(function (page) {
      return '<button type="button" class="page-number ' + (page === payload.page ? "active" : "") + '" data-page="' + page + '">' + page + "</button>";
    }).join("");

    Array.from(elements.paginationNumbers.querySelectorAll("[data-page]")).forEach(function (button) {
      button.addEventListener("click", function () {
        state.page = Number(this.dataset.page);
        renderTable();
      });
    });
  }

  function exportRawCsv() {
    var params = new URLSearchParams();
    [
      "start_date",
      "end_date",
      "site",
      "store",
      "over_limit",
      "daily_sales_band",
      "margin_band",
      "keyword"
    ].forEach(function (key) {
      var value = state[key];
      if (value == null || value === "" || value === "all") return;
      params.set(key, value);
    });
    Object.keys(detailColumnFilters).forEach(function (key) {
      var value = detailColumnFilters[key];
      if (value == null || value === "") return;
      params.set("cf_" + key, value);
    });
    window.location.href = "/api/detail/export" + (params.toString() ? ("?" + params.toString()) : "");
  }

  function openDrawer(itemId, trendDays) {
    app.apiGet("/api/detail/" + encodeURIComponent(itemId), { trend_days: trendDays }).then(function (payload) {
      if (payload.error) return;
      elements.drawerTitle.textContent = payload.item.title;
      elements.drawerContent.innerHTML = [
        '<section class="drawer-block drawer-trend-block">',
        '  <div class="drawer-trend-head">',
        "    <div><h3>历史销售额变化趋势</h3><p class='drawer-trend-copy'>点击切换近 7 / 14 / 30 天趋势，查看这个 SKU 在当前站点下的销售额变化。</p></div>",
        '    <div class="drawer-trend-actions">',
        [7, 14, 30].map(function (days) {
          return '<button type="button" class="drawer-chip-button ' + (days === payload.trend.days ? "active" : "") + '" data-days="' + days + '" data-item="' + itemId + '">近' + days + "天</button>";
        }).join(""),
        "    </div>",
        "  </div>",
        '  <div class="metric-strip drawer-trend-metrics">',
        metric("区间销售额", app.formatCompactCurrency(payload.trend.total_revenue)),
        metric("日均销售额", app.formatCompactCurrency(payload.trend.average_revenue)),
        metric("最新单日", app.formatCompactCurrency(payload.trend.latest_revenue)),
        metric("趋势变化", (payload.trend.change_ratio >= 0 ? "上升 " : "下降 ") + app.formatPercent(Math.abs(payload.trend.change_ratio), 1)),
        "  </div>",
        '  <div id="drawerTrendChart" class="drawer-chart-panel"></div>',
        "</section>",
        '<section class="drawer-block"><h3>当前记录概览</h3><div class="info-grid">',
        info("国家", payload.item.country),
        info("店铺", payload.item.store),
        info("MSKU", payload.item.msku),
        info("统计周期", payload.item.stat_period),
        info("当前销售额", app.formatCurrency(payload.item.current_revenue)),
        info("当前日销", String(payload.item.current_daily_sales)),
        info("当前毛利率", app.formatPercent(payload.item.current_margin)),
        info("当前售价", formatOriginalPrice(payload.item.current_price)),
        info("FBA 可售", String(payload.item.fba_sellable_inventory)),
        info("库存周转天数", String(payload.item.stock_days)),
        "</div></section>"
      ].join("");

      bindDrawerButtons();
      elements.detailDrawer.classList.remove("hidden");
      elements.drawerMask.classList.remove("hidden");
      elements.detailDrawer.setAttribute("aria-hidden", "false");
      requestAnimationFrame(function () {
        renderTrendChart(payload.trend);
      });
    });
  }

  function bindDrawerButtons() {
    Array.from(elements.drawerContent.querySelectorAll("[data-days]")).forEach(function (button) {
      button.addEventListener("click", function () {
        openDrawer(this.dataset.item, Number(this.dataset.days));
      });
    });
  }

  function renderTrendChart(trend) {
    var chartHost = document.getElementById("drawerTrendChart");
    if (!chartHost) return;
    if (trendChart) trendChart.dispose();
    trendChart = echarts.init(chartHost);
    trendChart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 46, right: 20, top: 20, bottom: 34 },
      xAxis: {
        type: "category",
        data: trend.labels.map(function (label) { return label.slice(5).replace("-", "/"); }),
        axisLabel: { color: "#5f7086" }
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#5f7086",
          formatter: function (value) {
            if (value >= 10000) return (value / 10000).toFixed(1) + "万";
            return value;
          }
        },
        splitLine: { lineStyle: { color: "#e4ebf5" } }
      },
      series: [{
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 8,
        areaStyle: { color: "rgba(23, 105, 224, 0.12)" },
        lineStyle: { width: 3, color: "#1769e0" },
        itemStyle: { color: "#1769e0" },
        data: trend.values
      }]
    });
    trendChart.resize();
  }

  function metric(label, value) {
    return '<div class="metric-pill"><span class="label">' + label + "</span><strong>" + value + "</strong></div>";
  }

  function info(label, value) {
    return '<div class="info-item"><span class="label">' + label + "</span><strong>" + value + "</strong></div>";
  }

  function closeDrawer() {
    elements.detailDrawer.classList.add("hidden");
    elements.drawerMask.classList.add("hidden");
    elements.detailDrawer.setAttribute("aria-hidden", "true");
    if (trendChart) {
      trendChart.dispose();
      trendChart = null;
    }
  }
}());
