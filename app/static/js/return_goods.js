(function () {
  var app = window.kanbanApp;
  var state = { page: 1, page_size: 20, snapshot_date: "", available_dates: [], calendar_month: "", quick_filter: "all", return_day: 0 };
  var el = {};
  var gridRenderSeq = 0;
  var scrollToTableAfterRender = false;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "snapshotDateButton", "snapshotDateValue", "snapshotCalendarPanel", "countrySelect", "storeSelect",
      "keywordInput", "clearFiltersBtn", "summaryGrid", "periodHint", "stageBusinessCompare", "stageChart", "warningList",
      "tableWrap", "paginationInfo", "pageSizeSelect", "prevPageBtn", "nextPageBtn",
      "returnGoodsDetailMask", "returnGoodsDetailDrawer", "returnGoodsDetailClose", "returnGoodsDetailTitle", "returnGoodsDetailSubtitle", "returnGoodsDetailBody"
    ].forEach(function (id) {
      el[id] = document.getElementById(id);
    });
    if (!el.summaryGrid) return;
    bind();
    render();
  }

  function bind() {
    ["countrySelect", "storeSelect", "pageSizeSelect"].forEach(function (id) {
      el[id].addEventListener("change", function () {
        state.return_day = 0;
        state.page = 1;
        state.page_size = Number(el.pageSizeSelect.value || 20);
        render();
      });
    });
    el.snapshotDateButton.addEventListener("click", function (event) {
      event.stopPropagation();
      toggleSnapshotCalendar();
    });
    el.snapshotCalendarPanel.addEventListener("click", function (event) {
      event.stopPropagation();
      var nav = event.target.closest("[data-calendar-nav]");
      var dateButton = event.target.closest("[data-snapshot-date]");
      if (nav) {
        state.calendar_month = addMonths(state.calendar_month, Number(nav.getAttribute("data-calendar-nav")));
        renderSnapshotCalendar();
      }
      if (dateButton) {
        state.snapshot_date = dateButton.getAttribute("data-snapshot-date");
        state.return_day = 0;
        closeSnapshotCalendar();
        setSnapshotDateLabel(state.snapshot_date);
        state.page = 1;
        render();
      }
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest(".snapshot-date-control")) {
        closeSnapshotCalendar();
      }
      clearQuickFilterOnBlankClick(event);
    });
    el.keywordInput.addEventListener("input", debounce(function () {
      state.page = 1;
      state.return_day = 0;
      render();
    }, 300));
    el.summaryGrid.addEventListener("click", handleQuickFilterClick);
    el.stageBusinessCompare.addEventListener("click", function (event) {
      var node = event.target.closest("[data-stage-detail]");
      if (!node) return;
      openStageDetail(node.getAttribute("data-stage-detail") || "observe", node.getAttribute("data-stage-title") || "");
    });
    el.stageChart.addEventListener("click", handleQuickFilterClick);
    el.warningList.addEventListener("click", handleQuickFilterClick);
    function handleQuickFilterClick(event) {
      if (event.target.closest(".return-goods-help-anchor")) return;
      var node = event.target.closest("[data-return-filter]");
      if (!node) return;
      state.quick_filter = node.getAttribute("data-return-filter") || "all";
      state.return_day = 0;
      state.page = 1;
      render();
    }
    el.clearFiltersBtn.addEventListener("click", function () {
      el.countrySelect.value = "all";
      el.storeSelect.value = "all";
      el.keywordInput.value = "";
      state.quick_filter = "all";
      state.return_day = 0;
      state.page = 1;
      render();
    });
    el.prevPageBtn.addEventListener("click", function () {
      if (state.page <= 1) return;
      state.page -= 1;
      render();
    });
    el.nextPageBtn.addEventListener("click", function () {
      state.page += 1;
      render();
    });
    if (el.returnGoodsDetailClose) {
      el.returnGoodsDetailClose.addEventListener("click", function (event) {
        event.stopPropagation();
        closeDetail();
      });
    }
    if (el.returnGoodsDetailMask) {
      el.returnGoodsDetailMask.addEventListener("click", function (event) {
        event.stopPropagation();
        closeDetail();
      });
    }
    if (el.returnGoodsDetailBody) {
      el.returnGoodsDetailBody.addEventListener("click", function (event) {
        var row = event.target.closest("[data-stage-return-day]");
        if (!row) return;
        filterDetailByStageDay(row.getAttribute("data-stage-key"), row.getAttribute("data-stage-return-day"));
      });
    }
  }

  function render() {
    el.tableWrap.innerHTML = '<div class="empty-state">加载中...</div>';
    app.apiGet("/api/return-goods", buildParams())
      .then(function (payload) {
        state.page = payload.page || 1;
        syncMeta(payload);
        renderSummary(payload);
        renderStageBusinessCompare(payload.stage_business_compare || []);
        renderStatusMatrix(payload.status_matrix || {});
        renderPriorityQueue(payload.priority_queue || []);
        renderTable(payload.items || []);
        renderPagination(payload);
        if (scrollToTableAfterRender) {
          scrollToTableAfterRender = false;
          el.tableWrap.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        el.periodHint.textContent = "总览、矩阵和明细均截至统计日 " + (payload.snapshot_date || "-") + "，按 MSKU 最新状态展示。";
      })
      .catch(function (error) {
        console.error(error);
        el.tableWrap.innerHTML = '<div class="empty-state">返场品数据加载失败：' + escapeHtml(error.message || error) + '</div>';
      });
  }

  function clearQuickFilterOnBlankClick(event) {
    if ((state.quick_filter || "all") === "all" && !state.return_day) return;
    if (event.target.closest([
      "button",
      "a",
      "input",
      "select",
      "textarea",
      ".snapshot-date-control",
      ".return-goods-help-anchor",
      ".return-goods-detail-drawer",
      ".drawer-mask",
      ".return-goods-ag-grid",
      ".pagination-bar",
      "[data-return-filter]",
      "[data-stage-detail]",
      "[data-stage-return-day]"
    ].join(","))) return;
    state.quick_filter = "all";
    state.return_day = 0;
    state.page = 1;
    render();
  }

  function buildParams() {
    return {
      snapshot_date: state.snapshot_date,
      period_days: "1",
      country_category: el.countrySelect.value || "all",
      seller_name_new: el.storeSelect.value || "all",
      keyword: el.keywordInput.value || "",
      stage: "all",
      warning_type: "all",
      quick_filter: state.quick_filter || "all",
      return_day: state.return_day || 0,
      page: state.page,
      page_size: state.page_size
    };
  }

  function syncMeta(payload) {
    var meta = payload.meta || {};
    syncSnapshotDates(meta.dates || [], payload.snapshot_date);
    setOptions(el.countrySelect, meta.country_categories || [], "全部国家类别");
    setOptions(el.storeSelect, meta.stores || [], "全部店铺");
  }

  function syncSnapshotDates(dates, selectedDate) {
    var options = dates.length ? dates : (selectedDate ? [selectedDate] : []);
    state.available_dates = options;
    if (options.indexOf(state.snapshot_date) < 0) {
      state.snapshot_date = selectedDate && options.indexOf(selectedDate) >= 0 ? selectedDate : (options[0] || selectedDate || "");
    }
    state.calendar_month = state.calendar_month || monthKey(state.snapshot_date || options[0]);
    if (state.snapshot_date && monthKey(state.snapshot_date) !== state.calendar_month && !el.snapshotCalendarPanel.hidden) {
      state.calendar_month = monthKey(state.snapshot_date);
    }
    setSnapshotDateLabel(state.snapshot_date);
    renderSnapshotCalendar();
  }

  function toggleSnapshotCalendar() {
    if (el.snapshotCalendarPanel.hidden) {
      state.calendar_month = monthKey(state.snapshot_date || state.available_dates[0]);
      renderSnapshotCalendar();
      el.snapshotCalendarPanel.hidden = false;
      el.snapshotDateButton.setAttribute("aria-expanded", "true");
    } else {
      closeSnapshotCalendar();
    }
  }

  function closeSnapshotCalendar() {
    el.snapshotCalendarPanel.hidden = true;
    el.snapshotDateButton.setAttribute("aria-expanded", "false");
  }

  function setSnapshotDateLabel(dateValue) {
    el.snapshotDateValue.textContent = dateValue ? dateValue.replace(/-/g, "/") : "--";
  }

  function renderSnapshotCalendar() {
    var month = state.calendar_month || monthKey(state.snapshot_date || state.available_dates[0]);
    if (!month) {
      el.snapshotCalendarPanel.innerHTML = '<div class="snapshot-calendar-empty">暂无已生成返场结果的日期</div>';
      return;
    }
    state.calendar_month = month;
    var parts = month.split("-");
    var year = Number(parts[0]);
    var monthIndex = Number(parts[1]) - 1;
    var firstDay = new Date(year, monthIndex, 1);
    var daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
    var leading = (firstDay.getDay() + 6) % 7;
    var available = {};
    state.available_dates.forEach(function (dateValue) {
      available[dateValue] = true;
    });

    var html = [
      '<div class="snapshot-calendar-head">',
      '<button type="button" class="snapshot-calendar-nav" data-calendar-nav="-1" aria-label="上个月">‹</button>',
      '<strong>' + year + '年' + pad2(monthIndex + 1) + '月</strong>',
      '<button type="button" class="snapshot-calendar-nav" data-calendar-nav="1" aria-label="下个月">›</button>',
      '</div>',
      '<div class="snapshot-calendar-weekdays">',
      ["一", "二", "三", "四", "五", "六", "日"].map(function (day) { return '<span>' + day + '</span>'; }).join(""),
      '</div>',
      '<div class="snapshot-calendar-days">'
    ];

    for (var i = 0; i < leading; i += 1) {
      html.push('<span class="snapshot-calendar-spacer"></span>');
    }
    for (var dayNumber = 1; dayNumber <= daysInMonth; dayNumber += 1) {
      var dateValue = year + "-" + pad2(monthIndex + 1) + "-" + pad2(dayNumber);
      var enabled = !!available[dateValue];
      var active = dateValue === state.snapshot_date;
      html.push(
        '<button type="button" class="snapshot-calendar-day' +
        (enabled ? "" : " disabled") +
        (active ? " active" : "") +
        '" ' +
        (enabled ? 'data-snapshot-date="' + dateValue + '"' : "disabled") +
        '>' + dayNumber + '</button>'
      );
    }
    html.push('</div><p class="snapshot-calendar-foot">只显示已生成返场结果的日期</p>');
    el.snapshotCalendarPanel.innerHTML = html.join("");
  }

  function monthKey(dateValue) {
    return dateValue ? String(dateValue).slice(0, 7) : "";
  }

  function addMonths(month, offset) {
    var parts = month.split("-");
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1 + offset, 1);
    return date.getFullYear() + "-" + pad2(date.getMonth() + 1);
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function setOptions(select, options, allLabel) {
    var value = select.value || "all";
    var html = ['<option value="all">' + escapeHtml(allLabel) + '</option>'];
    options.forEach(function (option) {
      html.push('<option value="' + escapeHtml(option) + '">' + escapeHtml(option) + '</option>');
    });
    select.innerHTML = html.join("");
    select.value = options.indexOf(value) >= 0 ? value : "all";
  }

  function renderSummary(payload) {
    var summary = payload.summary || {};
    var overview = payload.overview_summary || {};
    var stockoutMsku = Number(overview.stockout_msku_count || summary.total_return_msku_count || 0);
    var returnedMsku = Number(overview.returned_msku_count || 0);
    var observeItems = [
      ["D1-D3", "新返场", overview.observe_d1_3_msku_count, "info", "overview_observe_d1_3"],
      ["D4-D7", "待观察", overview.observe_d4_7_msku_count, "info", "overview_observe_d4_7"],
      ["已出单", "返场后有销量", overview.observe_ordered_msku_count, "success", "overview_observe_ordered"],
      ["仍未出单", "返场后销量为0", overview.observe_not_ordered_msku_count, "neutral", "overview_observe_not_ordered"]
    ];
    var operatingItems = [
      ["D8-D14", "早干预", overview.operating_d8_14_msku_count, "info", "overview_operating_d8_14"],
      ["D15-D21", "深干预", overview.operating_d15_21_msku_count, "info", "overview_operating_d15_21"],
      ["恢复达标", ">=70%", overview.operating_success_recovery_msku_count, "success", "overview_operating_success_recovery"],
      ["恢复率 < 50%", "重点复盘", overview.operating_low_recovery_msku_count, "danger", "overview_operating_low_recovery"],
      ["恢复不足", "50%-70%", overview.operating_recovery_insufficient_msku_count, "warn", "overview_operating_recovery_insufficient"],
      ["数据不足", "无法计算", overview.operating_data_insufficient_msku_count, "neutral", "overview_operating_data_insufficient"]
    ];
    var drillItems = [
      ["21天无恢复", overview.no_recovery_21d_msku_count, "danger", "返场开始后21天内销量合计 = 0", "overview_no_recovery_21d"],
      ["低恢复", overview.low_recovery_msku_count, "danger", "0 < 21天销量恢复率 < 30%", "overview_low_recovery"],
      ["弱恢复", overview.weak_recovery_msku_count, "warn", "30% <= 21天销量恢复率 < 50%", "overview_weak_recovery"],
      ["高价值未达标", overview.high_value_failed_msku_count, "danger", "明星/潜力产品，且21天销量恢复率 < 50%", "overview_high_value_failed"]
    ];
    var exitItems = [
      ["达标退出", overview.success_exit_msku_count, "success", "21天销量恢复率 >= 70%，按达标退出。", "overview_success_exit"],
      ["21天未达标运营持续干预", overview.failed_exit_msku_count, "danger", "21天销量恢复率 < 50%，需要持续运营干预。", "overview_failed_exit"],
      ["恢复不足", overview.recovery_insufficient_msku_count, "warn", "50% <= 21天销量恢复率 < 70%，需要复盘动作和补量。", "overview_recovery_insufficient"],
      ["数据不足", overview.data_insufficient_msku_count, "info", "断货前对比销量为0，无法进入恢复率分层。", "overview_data_insufficient"]
    ];

    el.summaryGrid.innerHTML = [
      '<section class="return-goods-command-panel">',
      '<article class="return-goods-command-main">',
      '<span class="return-goods-help-anchor">截至目前总览',
      '<button class="return-goods-help-button" type="button" aria-label="查看返场指标说明">?</button>',
      '<span class="return-goods-help-popover" role="tooltip">' + metricHelp("截至目前总览", [
        ["触发断货MSKU", "最近180天内周期销量 > 0，且出现过FBA可售库存 = 0的去重MSKU。按店铺 + 国家类别 + MSKU去重。"],
        ["已返场MSKU", "触发断货后，后续FBA可售库存恢复到 > 5并生成返场事件的去重MSKU。"],
        ["观察中", "最新一轮未退出，返场开始后1-7天。"],
        ["干预期", "最新一轮未退出，返场开始后8-21天。"],
        ["已退出", "最新一轮已在统计日前结束，包含达标、未达标、恢复不足、数据不足等分类。"]
      ]) + '</span>',
      '</span>',
      '<strong>' + formatNumber(returnedMsku) + '</strong>',
      '<small>已返场 MSKU</small>',
      '<div class="return-goods-main-metrics">',
      miniMetric("触发断货MSKU", stockoutMsku, false, "overview_stockout_msku"),
      miniMetric("观察中", overview.observe_msku_count, false, "overview_observe"),
      miniMetric("干预期", overview.operating_msku_count, false, "overview_operating"),
      miniMetric("已退出", overview.exited_msku_count, false, "overview_exited"),
      '</div>',
      '</article>',
      '<article class="return-goods-command-card">',
      '<div class="return-goods-command-head"><span class="return-goods-help-anchor">观察中明细</span><strong>' + formatNumber(overview.observe_msku_count) + '个</strong></div>',
      '<div class="return-goods-mini-grid">' + observeItems.map(function (item) { return miniTile(item[0], item[1], item[2], item[3], item[4]); }).join("") + '</div>',
      ratioBar("观察期出单覆盖", overview.observe_ordered_msku_count, overview.observe_msku_count, "info"),
      '</article>',
      '<article class="return-goods-command-card">',
      '<div class="return-goods-command-head"><span class="return-goods-help-anchor">干预期明细</span><strong>' + formatNumber(overview.operating_msku_count) + '个</strong></div>',
      '<div class="return-goods-mini-grid">' + operatingItems.map(function (item) { return miniTile(item[0], item[1], item[2], item[3], item[4]); }).join("") + '</div>',
      '</article>',
      '<article class="return-goods-command-card">',
      '<div class="return-goods-command-head"><span class="return-goods-help-anchor">已退出明细</span><strong>' + formatNumber(overview.exited_msku_count) + '个</strong></div>',
      '<div class="return-goods-mini-grid">' + exitItems.map(function (item) { return miniTile(item[0], item[3], item[1], item[2], item[4]); }).join("") + '</div>',
      stackedBar([
        ["success", overview.success_exit_msku_count],
        ["danger", overview.failed_exit_msku_count],
        ["warn", overview.recovery_insufficient_msku_count],
        ["info", overview.data_insufficient_msku_count]
      ], overview.exited_msku_count),
      '</article>',
      '<article class="return-goods-command-card return-goods-command-card-danger">',
      '<div class="return-goods-command-head"><span class="return-goods-help-anchor">21天未达标运营持续干预明细</span><strong>截至统计日</strong></div>',
      '<div class="return-goods-mini-grid">' + drillItems.map(function (item) { return miniTile(item[0], item[3], item[1], item[2], item[4]); }).join("") + '</div>',
      '</article>',
      '</section>'
    ].join("");
  }

  function renderStageBusinessCompare(rows) {
    if (!el.stageBusinessCompare) return;
    if (!rows.length) {
      el.stageBusinessCompare.innerHTML = '<div class="empty-state compact">暂无观察期 / 干预期经营对比。</div>';
      return;
    }
    el.stageBusinessCompare.innerHTML = rows.map(function (row) {
      var delta = Number(row.sales_delta || 0);
      var deltaClass = delta >= 0 ? "positive" : "negative";
      return [
        '<button class="return-goods-stage-business' + quickFilterClass(row.quick_filter) + '" type="button" data-stage-detail="' + escapeHtml(row.stage_key || "observe") + '" data-stage-title="' + escapeHtml(row.stage || "") + '">',
        '<span class="stage-business-title"><b>' + escapeHtml(row.stage || "-") + '</b><small>' + formatNumber(row.count || 0) + ' 个MSKU</small></span>',
        '<span><small>' + escapeHtml(row.baseline_label || "基准销量") + '</small><strong>' + formatDecimal(row.baseline_sales) + '</strong></span>',
        '<span><small>' + escapeHtml(row.current_label || "当前销量") + '</small><strong>' + formatDecimal(row.current_sales) + '</strong></span>',
        '<span><small>销量差值</small><strong class="' + deltaClass + '">' + formatSignedDecimal(row.sales_delta) + '</strong></span>',
        '<span><small>销量恢复率</small><strong>' + formatMaybePercent(row.sales_recovery_rate) + '</strong></span>',
        '</button>'
      ].join("");
    }).join("");
  }
  function miniMetric(label, value, raw, filter) {
    return '<button type="button" class="' + quickFilterClass(filter) + '" data-return-filter="' + escapeHtml(filter) + '"><b>' + escapeHtml(raw ? value : formatNumber(value)) + '</b><small>' + escapeHtml(label) + '</small></button>';
  }

  function miniTile(label, hint, value, tone, filter) {
    return [
      '<button type="button" class="return-goods-mini-tile ' + escapeHtml(tone || "neutral") + quickFilterClass(filter) + '" data-return-filter="' + escapeHtml(filter || "all") + '">',
      '<span><b>' + escapeHtml(label || "-") + '</b><small>' + escapeHtml(hint || "") + '</small></span>',
      '<strong>' + formatNumber(value || 0) + '</strong>',
      '</button>'
    ].join("");
  }

  function ratioBar(label, numerator, denominator, tone) {
    var total = Number(denominator || 0);
    var value = Number(numerator || 0);
    var ratio = total ? value / total : 0;
    var width = Math.max(0, Math.min(100, Math.round(ratio * 100)));
    return [
      '<div class="return-goods-ratio-bar ' + escapeHtml(tone || "info") + '">',
      '<span>' + escapeHtml(label) + '</span>',
      '<i><b style="width:' + width + '%"></b></i>',
      '<strong>' + formatPercent(ratio) + '</strong>',
      '</div>'
    ].join("");
  }

  function stackedBar(parts, total) {
    var safeTotal = Number(total || 0);
    return [
      '<div class="return-goods-stack-wrap"><span>退出结果</span>',
      '<div class="return-goods-stack">',
      parts.map(function (part) {
        var width = safeTotal ? Math.max(0, Number(part[1] || 0) / safeTotal * 100) : 0;
        return '<i class="' + escapeHtml(part[0]) + '" style="width:' + width + '%"></i>';
      }).join(""),
      '</div>',
      '<div class="return-goods-stack-labels">',
      parts.map(function (part) {
        return '<small>' + formatPercent(safeTotal ? Number(part[1] || 0) / safeTotal : 0) + '</small>';
      }).join(""),
      '</div></div>'
    ].join("");
  }

  function renderSalesRoleDistribution(rows) {
    var filters = { "明星产品": "role_star", "潜力产品": "role_potential", "瘦狗产品": "role_dog", "问题产品": "role_problem" };
    var order = ["问题产品", "瘦狗产品", "潜力产品", "明星产品"];
    var byRole = {};
    rows.forEach(function (row) { byRole[row.sales_role] = row; });
    return order.map(function (role) {
      var row = byRole[role] || { count: 0, ratio: 0 };
      return [
        '<button type="button" class="return-goods-role-chip' + quickFilterClass(filters[role]) + '" data-return-filter="' + filters[role] + '">',
        '<span>' + escapeHtml(role) + '</span>',
        '<b>' + formatNumber(row.count || 0) + '</b>',
        '<em>' + formatPercent(row.ratio || 0) + '</em>',
        '</button>'
      ].join("");
    }).join("");
  }

  function issueMetric(label, value, tone, hint, filter) {
    return [
      '<button class="return-goods-issue ' + tone + quickFilterClass(filter) + '" type="button" data-return-filter="' + escapeHtml(filter) + '">',
      '<span>' + escapeHtml(label) + '</span>',
      '<strong>' + formatNumber(value) + '</strong>',
      '<small>' + escapeHtml(hint) + '</small>',
      '</button>'
    ].join("");
  }

  function compactMetric(label, value, tone, filter, delta, raw) {
    var deltaHtml = delta === undefined || delta === null ? "" : '<small class="return-goods-period-delta">' + escapeHtml(deltaText(delta)) + '</small>';
    return '<button class="return-goods-compact ' + tone + quickFilterClass(filter) + '" type="button" data-return-filter="' + escapeHtml(filter) + '"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(raw ? value : formatNumber(value)) + '</strong>' + deltaHtml + '</button>';
  }

  function quickFilterClass(filter) {
    return (state.quick_filter || "all") === (filter || "all") ? " active" : "";
  }

  function metricHelp(title, rows) {
    return [
      '<strong>' + escapeHtml(title) + '指标说明</strong>',
      '<span class="return-goods-help-list">',
      rows.map(function (row) {
        return '<span><b>' + escapeHtml(row[0]) + '</b><small>' + escapeHtml(row[1]) + '</small></span>';
      }).join(""),
      '</span>'
    ].join("");
  }

  function renderStatusMatrix(matrix) {
    var roles = matrix.roles || [];
    var statuses = matrix.statuses || [];
    var cells = {};
    (matrix.cells || []).forEach(function (cell) {
      cells[cell.role_key + ":" + cell.status_key] = cell;
    });
    if (!roles.length || !statuses.length) {
      el.stageChart.innerHTML = '<div class="empty-state compact">暂无返场处置数据。</div>';
      return;
    }
    el.stageChart.innerHTML = [
      '<div class="return-goods-matrix-scroll">',
      '<div class="return-goods-matrix" style="grid-template-columns: 154px repeat(' + statuses.length + ', minmax(124px, 1fr));">',
      '<span class="matrix-corner"></span>',
      statuses.map(function (status) { return '<span class="matrix-head"><b>' + escapeHtml(status.label) + '</b><small>' + escapeHtml(statusHint(status.key)) + '</small></span>'; }).join(""),
      roles.map(function (role) {
        return [
          '<span class="matrix-role" title="' + escapeHtml(roleHint(role.key)) + '"><b>' + escapeHtml(role.label) + '</b><small>' + escapeHtml(roleShortHint(role.key)) + '</small></span>',
          statuses.map(function (status) {
            var cell = cells[role.key + ":" + status.key] || {};
            var level = Math.min(4, Math.ceil(Number(cell.ratio || 0) * 12));
            return [
              '<button type="button" class="matrix-cell level-' + level + quickFilterClass(cell.quick_filter) + '" data-return-filter="' + escapeHtml(cell.quick_filter || "all") + '">',
              '<strong>' + formatNumber(cell.count || 0) + '</strong>',
              '<small>' + formatPercent(cell.ratio || 0) + '</small>',
              '</button>'
            ].join("");
          }).join("")
        ].join("");
      }).join(""),
      '</div>',
      '</div>',
      '<div class="return-goods-matrix-legend">',
      '<span>数量占比（%）</span>',
      '<i class="legend-swatch level-0"></i><span>&lt; 2%</span>',
      '<i class="legend-swatch level-1"></i><span>2%-5%</span>',
      '<i class="legend-swatch level-2"></i><span>5%-10%</span>',
      '<i class="legend-swatch level-3"></i><span>10%-15%</span>',
      '<i class="legend-swatch level-4"></i><span>&gt; 15%</span>',
      '<em>占比基于当前筛选 MSKU 最新状态总数 ' + formatNumber(matrix.total || 0) + ' 计算</em>',
      '</div>'
    ].join("");
  }

  function renderPriorityQueue(rows) {
    if (!rows.length) {
      el.warningList.innerHTML = '<div class="empty-state compact">暂无优先处理项。</div>';
      return;
    }
    el.warningList.innerHTML = rows.map(function (row) {
      var meta = priorityMeta(row.quick_filter);
      return [
        '<button class="summary-side-item return-goods-warning-item' + quickFilterClass(row.quick_filter) + '" type="button" data-return-filter="' + escapeHtml(row.quick_filter || "all") + '">',
        '<span class="summary-side-icon ' + meta.tone + '">' + escapeHtml(meta.icon) + '</span>',
        '<span class="summary-side-copy"><b>' + escapeHtml(row.title || "-") + '</b><small>' + escapeHtml(row.hint || "") + '</small></span>',
        '<strong>' + formatNumber(row.count || 0) + '</strong>',
        '<i class="queue-arrow">›</i>',
        '</button>'
      ].join("");
    }).join("") + '<p class="return-goods-queue-note"><span>i</span>点击任意项，可筛选对应明细并查看详情</p>';
  }

  function statusHint(key) {
    return {
      not_arrived: "FBA可售=0 且在途>0",
      observe: "已返场<=7天且未退出",
      operating: "8-21天且未退出",
      recovery_insufficient: "50% <= 21天销量恢复率 < 70%",
      over21_low_recovery: ">21天且21天销量恢复率<50%"
    }[key] || "";
  }

  function roleHint(key) {
    return {
      problem: "日销=0；或日销>0且毛利率<5%",
      dog: "日销1-5且毛利率5%-10%；或日销<1且毛利率>5%",
      potential: "日销>5且毛利率5%-15%；或日销1-5且毛利率10%-25%",
      star: "日销>5且毛利率>15%；或日销1-5且毛利率>25%"
    }[key] || "";
  }

  function roleShortHint(key) {
    return {
      problem: "零日销 / 低毛利",
      dog: "低日销 / 中低毛利",
      potential: "中高日销 / 中毛利",
      star: "高日销 / 高毛利"
    }[key] || "";
  }

  function priorityMeta(filter) {
    return {
      priority_valuable_not_arrived: { icon: "!", tone: "danger" },
      priority_valuable_low_recovery: { icon: "!", tone: "warn" },
      priority_manual: { icon: "?", tone: "manual" },
      priority_today_operating: { icon: "↗", tone: "info" },
      overview_failed_exit: { icon: "!", tone: "danger" },
      overview_recovery_insufficient: { icon: "!", tone: "warn" },
      overview_not_arrived: { icon: "!", tone: "info" },
      overview_high_value_failed: { icon: "!", tone: "danger" }
    }[filter] || { icon: "!", tone: "danger" };
  }
  function renderTable(items) {
    if (!items.length) {
      el.tableWrap.innerHTML = '<div class="empty-state">当前筛选无返场 MSKU。</div>';
      return;
    }
    gridRenderSeq += 1;
    var gridId = "returnGoodsAgGrid-" + gridRenderSeq;
    el.tableWrap.innerHTML = '<div id="' + gridId + '" class="return-goods-ag-grid"></div>';
    window.kanbanGrid.makeGrid(gridId, {
      rowData: items,
      domLayout: "normal",
      rowHeight: 92,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">暂无返场明细</span>',
      onRowClicked: function (params) {
        openDetail(params.data || {});
      },
      columnDefs: [
        { headerName: "MSKU / SKU", field: "seller_sku_adj", pinned: "left", width: 160, tooltipField: "seller_sku_adj", cellRenderer: function (params) {
          return window.kanbanGrid.subCell(params.data.seller_sku_adj || "-", params.data.local_sku || "");
        } },
        { headerName: "店铺", field: "seller_name_new", pinned: "left", width: 120 },
        { headerName: "国家类别", field: "country_category", width: 110 },
        { headerName: "断货日期", field: "stockout_date", width: 116 },
        { headerName: "返场开始", field: "return_start_date", width: 116 },
        numberColumn("断货天数", "stockout_days", 104, 0),
        numberColumn("已返场天数", "return_days", 112, 0),
        { headerName: "阶段", field: "stage", width: 124, cellRenderer: function (params) { return statusPill(params.value || "-"); } },
        { headerName: "断货前角色", field: "pre_stockout_sales_role", width: 118, cellRenderer: function (params) { return statusPill(params.value || "-"); } },
        numberColumn("FBA可售", "current_fba_sellable", 104, 0),
        numberColumn("FBA在途", "current_fba_inbound", 104, 0),
        numberColumn("恢复统计天数", "recovery_window_days", 118, 0),
        numberColumn("断货前对比销量", "pre_recovery_sales_qty", 136, 0),
        numberColumn("返场后对比销量", "post_recovery_sales_qty", 136, 0),
        { headerName: "销量恢复率", field: "sales_recovery_rate_text", width: 112, type: "numericColumn", cellRenderer: function (params) { return '<span class="ag-number-strong">' + escapeHtml(params.value || "-") + '</span>'; } },
        { headerName: "国家售价 / 定价", field: "listing_preview", minWidth: 500, flex: 1.7, cellRenderer: function (params) { return renderListingPreviewCell(params.value || {}); } },
        { headerName: "广告概览", field: "listing_preview", width: 260, cellRenderer: function (params) { return renderAdPreviewCell(params.value || {}); } },
                { headerName: "退出原因", field: "exit_reason", width: 126, cellRenderer: function (params) { return statusPill(params.value || "-"); } },
        { headerName: "预警", field: "warning_type", minWidth: 150, tooltipField: "warning_type", cellRenderer: function (params) { return statusPill(params.value || "-"); } },
        { headerName: "详情", field: "return_event_id", pinned: "right", width: 92, sortable: false, filter: false, cellRenderer: function () { return '<button class="return-goods-detail-btn" type="button">详情</button>'; } }
      ]
    });
  }

  function openDetail(row) {
    if (!el.returnGoodsDetailDrawer || !row.return_event_id) return;
    el.returnGoodsDetailMask.hidden = false;
    el.returnGoodsDetailDrawer.hidden = false;
    el.returnGoodsDetailDrawer.setAttribute("aria-hidden", "false");
    el.returnGoodsDetailTitle.textContent = (row.seller_sku_adj || "-") + " / " + (row.seller_name_new || "-");
    el.returnGoodsDetailSubtitle.textContent = (row.country_category || "-") + " · 断货 " + (row.stockout_days == null ? "-" : formatNumber(row.stockout_days)) + " 天";
    el.returnGoodsDetailBody.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/return-goods/detail", {
      snapshot_date: state.snapshot_date,
      return_event_id: row.return_event_id
    }).then(function (payload) {
      renderDetail(payload.event || row, payload.daily || [], payload.country_metrics || {});
    }).catch(function (error) {
      console.error(error);
      el.returnGoodsDetailBody.innerHTML = '<div class="empty-state compact">明细加载失败。</div>';
    });
  }

  function openStageDetail(stageKey, stageTitle) {
    if (!el.returnGoodsDetailDrawer) return;
    el.returnGoodsDetailMask.hidden = false;
    el.returnGoodsDetailDrawer.hidden = false;
    el.returnGoodsDetailDrawer.setAttribute("aria-hidden", "false");
    el.returnGoodsDetailTitle.textContent = (stageTitle || "阶段") + "聚合明细";
    el.returnGoodsDetailSubtitle.textContent = "按返场 Day 聚合当前筛选下的 MSKU 池";
    el.returnGoodsDetailBody.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/return-goods/stage-detail", {
      snapshot_date: state.snapshot_date,
      period_days: "1",
      country_category: el.countrySelect.value || "all",
      seller_name_new: el.storeSelect.value || "all",
      keyword: el.keywordInput.value || "",
      stage_key: stageKey || "observe"
    }).then(function (payload) {
      renderStageDetail(payload || {});
    }).catch(function (error) {
      console.error(error);
      el.returnGoodsDetailBody.innerHTML = '<div class="empty-state compact">阶段明细加载失败。</div>';
    });
  }

  function closeDetail() {
    if (!el.returnGoodsDetailDrawer) return;
    el.returnGoodsDetailMask.hidden = true;
    el.returnGoodsDetailDrawer.hidden = true;
    el.returnGoodsDetailDrawer.setAttribute("aria-hidden", "true");
  }

  function renderListingPreviewCell(preview) {
    var countries = preview.top_countries || [];
    if (!countries.length) return '<span class="muted">-</span>';
    return [
      '<div class="return-goods-listing-preview">',
      countries.map(function (item) {
        return [
          '<div class="listing-country-line">',
          '<span class="listing-country-name">' + escapeHtml(item.country || "-") + '</span>',
          '<span class="listing-price-main">售价 ' + escapeHtml(formatDecimal(item.listing_price)) + '</span>',
          '<span class="listing-price-bench"><em>35% ' + escapeHtml(formatDecimal(item.margin_price_35)) + '</em><em>10% ' + escapeHtml(formatDecimal(item.margin_price_10)) + '</em></span>',
          '</div>'
        ].join("");
      }).join(""),
      (preview.country_count > countries.length ? '<small>共 ' + formatNumber(preview.country_count) + ' 国，详情查看全部</small>' : ''),
      '</div>'
    ].join("");
  }

  function renderAdPreviewCell(preview) {
    if (!preview || !preview.country_count) return '<span class="muted">-</span>';
    return [
      '<div class="return-goods-ad-preview">',
      '<span><small>花费</small><b>' + escapeHtml(formatDecimal(preview.ad_spend)) + '</b></span>',
      '<span><small>广告销售</small><b>' + escapeHtml(formatDecimal(preview.ad_sales)) + '</b></span>',
      '<span><small>TACOS</small><b>' + escapeHtml(preview.tacos_text || "-") + '</b></span>',
      '</div>'
    ].join("");
  }

  function renderCountryMetricsTable(rows) {
    if (!rows.length) return '<div class="empty-state compact">暂无国家售价与定价数据。</div>';
    return [
      '<div class="return-goods-detail-table-wrap"><table class="data-table return-goods-detail-table">',
      '<thead><tr><th>国家</th><th>SKU</th><th>当前售价</th><th>币种</th><th>35%定价</th><th>30%</th><th>25%</th><th>20%</th><th>15%</th><th>10%</th><th>5%</th><th>0%</th><th>价格风险</th></tr></thead>',
      '<tbody>',
      rows.map(function (row) {
        return [
          '<tr>',
          '<td>' + escapeHtml(row.country || "-") + '</td>',
          '<td>' + escapeHtml(row.local_sku_list || "-") + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.listing_price)) + '</td>',
          '<td>' + escapeHtml(row.currency || "-") + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_35)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_30)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_25)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_20)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_15)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_10)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_5)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.margin_price_0)) + '</td>',
          '<td>' + (row.price_risk ? '<span class="status-pill neutral">低于35%</span>' : '<span class="status-pill neutral">正常</span>') + '</td>',
          '</tr>'
        ].join("");
      }).join(""),
      '</tbody></table></div>'
    ].join("");
  }

  function renderAdMetrics(countryMetrics) {
    var summary = countryMetrics.summary || {};
    var rows = countryMetrics.items || [];
    if (!rows.length) return '<div class="empty-state compact">暂无广告与经营数据。</div>';
    var periodDays = countryMetrics.period_days || summary.period_days;
    var periodRange = [countryMetrics.period_start, countryMetrics.period_end].filter(Boolean).join(" 至 ") || "-";
    return [
      '<div class="return-goods-detail-grid compact">',
      detailMetric("返场窗口", periodDays ? formatNumber(periodDays) + "天" : "-"),
      detailMetric("窗口日期", periodRange),
      detailMetric("国家数", formatNumber(summary.country_count || 0)),
      detailMetric("价格风险国家", formatNumber(summary.price_risk_country_count || 0)),
      detailMetric("窗口销售额", formatDecimal(summary.sales_amount)),
      detailMetric("窗口毛利", formatDecimal(summary.order_gross_profit)),
      detailMetric("毛利率", formatMaybePercent(summary.order_gross_margin)),
      detailMetric("广告花费", formatDecimal(summary.ad_spend)),
      detailMetric("广告销售额", formatDecimal(summary.ad_sales)),
      detailMetric("TACOS", summary.tacos_text || "-"),
      '</div>',
      '<div class="return-goods-detail-table-wrap"><table class="data-table return-goods-detail-table">',
      '<thead><tr><th>国家</th><th>销量</th><th>销售额</th><th>毛利</th><th>毛利率</th><th>Session</th><th>转化率</th><th>广告花费</th><th>广告销售额</th><th>广告订单</th><th>点击</th><th>曝光</th><th>TACOS</th><th>CTR</th></tr></thead>',
      '<tbody>',
      rows.map(function (row) {
        return [
          '<tr>',
          '<td>' + escapeHtml(row.country || "-") + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.sales_qty)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.sales_amount)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.order_gross_profit)) + '</td>',
          '<td>' + escapeHtml(row.order_gross_margin_text || "-") + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.sessions_total)) + '</td>',
          '<td>' + escapeHtml(row.conversion_rate_text || "-") + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.ad_spend)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.ad_sales)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.ad_orders)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.ad_clicks)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.ad_impressions)) + '</td>',
          '<td>' + escapeHtml(row.tacos_text || "-") + '</td>',
          '<td>' + escapeHtml(row.ctr_text || "-") + '</td>',
          '</tr>'
        ].join("");
      }).join(""),
      '</tbody></table></div>'
    ].join("");
  }

  function renderDetail(event, dailyRows, countryMetrics) {
    countryMetrics = countryMetrics || {};
    el.returnGoodsDetailBody.innerHTML = [
      '<section class="drawer-block">',
      '<h3>事件概览</h3>',
      '<div class="return-goods-detail-grid">',
      detailMetric("阶段", event.stage),
      detailMetric("断货日期", event.stockout_date),
      detailMetric("返场开始", event.return_start_date),
      detailMetric("断货天数", event.stockout_days == null ? "-" : formatNumber(event.stockout_days)),
      detailMetric("已返场天数", event.return_days == null ? "-" : formatNumber(event.return_days)),
      detailMetric("断货前角色", event.pre_stockout_sales_role),
      detailMetric("FBA可售", formatNumber(event.current_fba_sellable)),
      detailMetric("FBA在途", formatNumber(event.current_fba_inbound)),
      detailMetric("恢复统计天数", formatNumber(event.recovery_window_days)),
      detailMetric("断货前对比销量", formatDecimal(event.pre_recovery_sales_qty)),
      detailMetric("返场后对比销量", formatDecimal(event.post_recovery_sales_qty)),
      detailMetric("销量恢复率", event.sales_recovery_rate_text || "-"),
      detailMetric("退出原因", event.exit_reason || "-"),
      detailMetric("预警", event.warning_type || "-"),
      '</div>',
      '</section>',
      '<section class="drawer-block">',
      '<h3>国家售价与毛利定价</h3>',
      renderCountryMetricsTable(countryMetrics.items || []),
      '</section>',
      '<section class="drawer-block">',
      '<h3>广告与经营指标</h3>',
      renderAdMetrics(countryMetrics),
      '</section>',
      '<section class="drawer-block">',
      '<h3>库存 / 销量日明细</h3>',
      renderDailyTable(dailyRows),
      '</section>'
    ].join("");
  }
  function renderStageDetail(payload) {
    var groups = payload.groups || [];
    el.returnGoodsDetailTitle.textContent = (payload.stage || "阶段") + "聚合明细";
    el.returnGoodsDetailSubtitle.textContent = "共 " + formatNumber(payload.event_count || 0) + " 个 MSKU，按返场 Day 聚合";
    el.returnGoodsDetailBody.innerHTML = [
      '<section class="drawer-block">',
      '<h3>口径</h3>',
      '<p class="summary-hint">观察段为返场后 D1-D7；干预段为返场后 D8-D21，并重新标记为干预Day1-Day14。</p>',
      '</section>',
      groups.map(function (group) {
        return [
          '<section class="drawer-block">',
          '<h3>' + escapeHtml(group.title || "-") + '</h3>',
          renderStageDailyTable(group.rows || [], payload.stage_key || "observe"),
          '</section>'
        ].join("");
      }).join("")
    ].join("");
  }

  function renderStageDailyTable(rows, stageKey) {
    if (!rows.length) return '<div class="empty-state compact">暂无阶段明细。</div>';
    var showCurrentColumns = rows.some(function (row) {
      return Number(row.observable_msku || 0) ||
        Number(row.ordered_msku || 0) ||
        Number(row.sales_qty || 0) ||
        Number(row.fba_sellable || 0);
    });
    var headers = ['<th>阶段Day</th><th>返场Day</th>'];
    if (showCurrentColumns) {
      headers.push('<th>处于该Day MSKU</th><th>当天出单MSKU</th><th>当天销量</th><th>FBA可售</th>');
    }
    headers.push('<th>累计销量</th><th>仍未出单</th>');
    return [
      '<div class="return-goods-detail-table-wrap"><table class="data-table return-goods-detail-table">',
      '<thead><tr>' + headers.join("") + '</tr></thead>',
      '<tbody>',
      rows.map(function (row) {
        var clickable = Number(row.observable_msku || 0) > 0;
        var cells = [
          '<tr' + (clickable ? ' class="return-goods-stage-day-row" data-stage-return-day="' + escapeHtml(row.return_day) + '" data-stage-key="' + escapeHtml(stageKey || "observe") + '" title="点击筛选下方明细"' : "") + '>',
          '<td>' + escapeHtml(row.stage_day_label || "-") + '</td>',
          '<td>' + escapeHtml(row.return_day_label || "-") + '</td>',
        ];
        if (showCurrentColumns) {
          cells.push(
            '<td>' + escapeHtml(formatNumber(row.observable_msku)) + '</td>',
            '<td>' + escapeHtml(formatNumber(row.ordered_msku)) + '</td>',
            '<td>' + escapeHtml(formatDecimal(row.sales_qty)) + '</td>',
            '<td>' + escapeHtml(formatNumber(row.fba_sellable)) + '</td>'
          );
        }
        cells.push(
          '<td>' + escapeHtml(formatDecimal(row.cumulative_sales_qty)) + '</td>',
          '<td>' + escapeHtml(formatNumber(row.not_ordered_msku)) + '</td>',
          '</tr>'
        );
        return cells.join("");
      }).join(""),
      '</tbody></table></div>'
    ].join("");
  }

  function filterDetailByStageDay(stageKey, returnDay) {
    var day = Number(returnDay || 0);
    if (!day) return;
    state.quick_filter = stageKey === "operating" ? "overview_operating" : "overview_observe";
    state.return_day = day;
    state.page = 1;
    closeDetail();
    scrollToTableAfterRender = true;
    render();
  }

  function detailMetric(label, value) {
    return '<span class="return-goods-detail-metric"><small>' + escapeHtml(label) + '</small><b>' + escapeHtml(value == null || value === "" ? "-" : value) + '</b></span>';
  }

  function renderDailyTable(rows) {
    if (!rows.length) return '<div class="empty-state compact">暂无每日明细。</div>';
    return [
      '<div class="return-goods-detail-table-wrap"><table class="data-table return-goods-detail-table">',
      '<thead><tr><th>日期</th><th>节点</th><th>FBA可售</th><th>FBA在途</th><th>销量</th><th>销售额</th><th>毛利率</th></tr></thead>',
      '<tbody>',
      rows.map(function (row) {
        return [
          '<tr>',
          '<td>' + escapeHtml(row.dt_date || "-") + '</td>',
          '<td>' + escapeHtml(row.day_tag || "-") + '</td>',
          '<td>' + escapeHtml(formatNumber(row.fba_sellable)) + '</td>',
          '<td>' + escapeHtml(formatNumber(row.fba_inbound)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.sales_qty)) + '</td>',
          '<td>' + escapeHtml(formatDecimal(row.sales_amount)) + '</td>',
          '<td>' + escapeHtml(row.gross_margin_rate_text || "-") + '</td>',
          '</tr>'
        ].join("");
      }).join(""),
      '</tbody></table></div>'
    ].join("");
  }

  function numberColumn(headerName, field, width, digits) {
    return {
      headerName: headerName,
      field: field,
      width: width,
      type: "numericColumn",
      cellRenderer: function (params) {
        var value = digits ? formatDecimal(params.value) : formatNumber(params.value);
        return '<span class="ag-number-strong">' + escapeHtml(value) + '</span>';
      }
    };
  }

  function statusPill(label) {
    if (!label || label === "-") return '<span class="muted">-</span>';
    return '<span class="status-pill neutral">' + escapeHtml(label) + '</span>';
  }

  function renderRow(item) {
    return [
      "<tr>",
      cell(item.seller_name_new),
      cell(item.country_category),
      cell(item.seller_sku_adj),
      cell(item.return_round),
      cell(item.stockout_date),
      cell(item.return_start_date),
      cell(item.return_days),
      cell(item.stage),
      cell(formatNumber(item.current_fba_sellable)),
      cell(formatNumber(item.current_fba_inbound)),
      cell(formatNumber(item.recovery_window_days)),
      cell(formatDecimal(item.pre_recovery_sales_qty)),
      cell(formatDecimal(item.post_recovery_sales_qty)),
      cell(item.sales_recovery_rate_text || "-"),
      cell(item.exit_reason || "-"),
      cell(item.warning_type || "-"),
      "</tr>"
    ].join("");
  }

  function renderPagination(payload) {
    var total = payload.total || 0;
    var page = payload.page || 1;
    var pages = payload.total_pages || 1;
    el.paginationInfo.textContent = "共 " + formatNumber(total) + " 条，第 " + page + " / " + pages + " 页";
    el.prevPageBtn.disabled = page <= 1;
    el.nextPageBtn.disabled = page >= pages;
  }

  function periodLabel(value) {
    var days = Number(value || 1);
    if (days === 1) return "今日";
    return "近" + days + "天";
  }

  function deltaText(value) {
    var number = Number(value || 0);
    if (number > 0) return "杈冧笂鍛ㄦ湡 +" + formatNumber(number);
    if (number < 0) return "杈冧笂鍛ㄦ湡 " + formatNumber(number);
    return "杈冧笂鍛ㄦ湡 0";
  }

  function cell(value) {
    return '<td>' + escapeHtml(value == null || value === "" ? "-" : value) + '</td>';
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString("zh-CN");
  }

  function formatDecimal(value) {
    if (value === null || value === undefined || value === "") return "-";
    return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function formatSignedDecimal(value) {
    if (value === null || value === undefined || value === "") return "-";
    var number = Number(value || 0);
    return (number > 0 ? "+" : "") + number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function formatPercent(value) {
    return (Number(value || 0) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%";
  }

  function formatMaybePercent(value) {
    if (value === null || value === undefined || value === "") return "-";
    return formatPercent(value);
  }

  function escapeHtml(value) {
    return app.escapeHtml(value);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }
})();
