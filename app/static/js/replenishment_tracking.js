(function () {
  var app = window.kanbanApp;
  var query = new URLSearchParams(window.location.search);
  var state = {
    snapshot_date: query.get("snapshot_date") || "",
    tracking_window_days: Number(query.get("tracking_window_days") || 7),
    category_period_days: Number(query.get("category_period_days") || 30),
    level: query.get("level") || "all",
    site: query.get("site") || "all",
    store: query.get("store") || "all",
    keyword: query.get("keyword") || "",
    status: query.get("status") || "all",
    sort_field: query.get("sort_field") || "",
    sort_dir: query.get("sort_dir") || "",
    page: Number(query.get("page") || 1),
    page_size: normalizePageSize(query.get("page_size"))
  };
  var elements = {};
  var metaLoaded = false;
  var trackingMeta = {};
  var requestToken = 0;
  var gridRenderSeq = 0;
  var datePickerMonth = null;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "trackingDatePickerBtn", "trackingDatePickerValue", "trackingDatePickerPanel",
      "trackingWindowSelect", "trackingCategoryPeriodSelect", "trackingLevelSelect", "trackingStatusSelect",
      "trackingSiteSelect", "trackingStoreSelect", "trackingKeywordInput", "clearTrackingFiltersBtn",
      "trackingPeriodHint", "trackingSummaryGrid", "trackingLayerVizGrid", "trackingLevelTabs",
      "trackingSortPurchaseBtn", "trackingSortReplenishBtn", "trackingTableWrap",
      "trackingPaginationInfo", "trackingPageSizeSelect", "trackingPrevPageBtn",
      "trackingNextPageBtn", "trackingPaginationNumbers", "trackingDetailMask",
      "trackingDetailDrawer", "trackingDetailTitle", "trackingDetailSubtitle",
      "trackingDetailCloseBtn", "trackingDetailWrap"
    ].forEach(function (id) {
      elements[id] = document.getElementById(id);
    });
    bindEvents();
    render();
  }

  function bindEvents() {
    [
      ["trackingWindowSelect", "tracking_window_days"],
      ["trackingCategoryPeriodSelect", "category_period_days"],
      ["trackingLevelSelect", "level"],
      ["trackingStatusSelect", "status"],
      ["trackingSiteSelect", "site"],
      ["trackingStoreSelect", "store"]
    ].forEach(function (pair) {
      if (!elements[pair[0]]) return;
      elements[pair[0]].addEventListener("change", function () {
        state[pair[1]] = pair[1] === "tracking_window_days" || pair[1] === "category_period_days" ? Number(this.value || 30) : this.value;
        state.page = 1;
        render();
      });
    });
    elements.trackingDatePickerBtn.addEventListener("click", function () {
      toggleDatePicker();
    });
    elements.trackingDatePickerPanel.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var action = event.target.closest("[data-date-action]");
      var dateButton = event.target.closest("[data-date-value]");
      if (action) {
        datePickerMonth = shiftMonth(datePickerMonth || monthStartFromValue(state.snapshot_date), Number(action.dataset.dateAction || 0));
        renderDatePicker();
        return;
      }
      if (dateButton && !dateButton.disabled) {
        selectDateValue(dateButton.dataset.dateValue);
      }
    });
    document.addEventListener("click", function (event) {
      if (!elements.trackingDatePickerPanel.hidden && !event.target.closest(".replenishment-date-control")) {
        closeDatePicker();
      }
    });
    elements.trackingKeywordInput.addEventListener("input", debounce(function () {
      state.keyword = elements.trackingKeywordInput.value.trim();
      state.page = 1;
      render();
    }, 280));
    elements.clearTrackingFiltersBtn.addEventListener("click", function () {
      state.level = "all";
      state.site = "all";
      state.store = "all";
      state.keyword = "";
      state.status = "all";
      state.category_period_days = 30;
      state.sort_field = "";
      state.sort_dir = "";
      state.page = 1;
      syncControls();
      render();
    });
    elements.trackingSortPurchaseBtn.addEventListener("click", function () {
      setSort("purchase_plan_qty");
    });
    elements.trackingSortReplenishBtn.addEventListener("click", function () {
      setSort("replenishment_qty");
    });
    elements.trackingPrevPageBtn.addEventListener("click", function () {
      if (state.page > 1) {
        state.page -= 1;
        render();
      }
    });
    elements.trackingNextPageBtn.addEventListener("click", function () {
      state.page += 1;
      render();
    });
    elements.trackingPageSizeSelect.addEventListener("change", function () {
      state.page_size = normalizePageSize(this.value);
      state.page = 1;
      render();
    });
    elements.trackingTableWrap.addEventListener("click", function (event) {
      var button = event.target.closest("[data-tracking-detail]");
      if (!button) return;
      var row = window.trackingRowMap ? window.trackingRowMap[button.dataset.rowKey || ""] : null;
      if (row) openDetail(row);
    });
    elements.trackingDetailCloseBtn.addEventListener("click", closeDetail);
    elements.trackingDetailMask.addEventListener("click", closeDetail);
    elements.trackingLayerVizGrid.addEventListener("click", function (event) {
      var node = event.target.closest("[data-tracking-level]");
      if (!node) return;
      state.level = node.dataset.trackingLevel || "all";
      state.status = node.dataset.trackingStatus || state.status || "all";
      state.page = 1;
      render();
    });
    elements.trackingLevelTabs.addEventListener("click", function (event) {
      var button = event.target.closest("[data-level-tab]");
      if (!button) return;
      state.level = button.dataset.levelTab || "all";
      state.page = 1;
      render();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDatePicker();
        closeDetail();
      }
    });
  }

  function setSort(field) {
    state.sort_field = field;
    state.sort_dir = state.sort_field === field && state.sort_dir === "desc" ? "asc" : "desc";
    render();
  }

  function render() {
    var token = ++requestToken;
    writeQueryState();
    syncControls();
    elements.trackingSummaryGrid.innerHTML = '<div class="empty-state compact">加载中...</div>';
    elements.trackingLayerVizGrid.innerHTML = '<div class="empty-state compact">加载中...</div>';
    elements.trackingTableWrap.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/replenishment-tracking", state).then(function (payload) {
      if (token !== requestToken) return;
      renderPayload(payload);
    }).catch(function (error) {
      console.error(error);
      if (token !== requestToken) return;
      elements.trackingTableWrap.innerHTML = '<div class="empty-state compact">加载失败，请检查补货追踪表。</div>';
    });
  }

  function renderPayload(payload) {
    if (!metaLoaded) {
      fillMeta(payload.meta || {});
      metaLoaded = true;
    }
    state.snapshot_date = payload.snapshot_date || state.snapshot_date;
    state.page = Number(payload.page || 1);
    state.page_size = normalizePageSize(payload.page_size);
    syncControls();
    state.category_period_days = Number(payload.category_period_days || state.category_period_days || 30);
    elements.trackingPeriodHint.textContent = "补货日期 " + (payload.snapshot_date || "-") + "，追踪窗口 " + (payload.tracking_window_days || 30) + " 天，分类周期 " + state.category_period_days + " 天";
    renderSummary(payload.summary || {});
    renderLayerViz(payload.level_summary || [], payload.summary || {});
    renderLevelTabs(payload.level_summary || [], payload.summary || {});
    renderTable(payload.items || []);
    renderPagination(payload);
  }

  function fillMeta(meta) {
    trackingMeta = meta || {};
    var activeLevelOptions = (meta.levels || []).slice(0, 4);
    fillObjectSelect(elements.trackingLevelSelect, activeLevelOptions, "全部层级");
    if (!activeLevelOptions.some(function (item) { return item.key === state.level; })) {
      state.level = "all";
    }
    fillObjectSelect(elements.trackingStatusSelect, meta.statuses || [], "全部状态");
    fillSelect(elements.trackingSiteSelect, meta.sites || [], "全部站点");
    fillSelect(elements.trackingStoreSelect, meta.stores || [], "全部店铺");
    if (!state.snapshot_date && meta.dates && meta.dates.length) state.snapshot_date = meta.dates[0];
    if (!datePickerMonth) datePickerMonth = monthStartFromValue(state.snapshot_date || (meta.dates || [])[0]);
    renderDatePicker(meta);
  }

  function fillSelect(select, options, allLabel) {
    var html = [];
    if (allLabel) html.push('<option value="all">' + escapeHtml(allLabel) + '</option>');
    (options || []).forEach(function (item) {
      html.push('<option value="' + escapeHtml(item) + '">' + escapeHtml(item) + '</option>');
    });
    select.innerHTML = html.join("");
  }

  function fillObjectSelect(select, options, fallbackLabel) {
    var html = [];
    if (!options.length) html.push('<option value="all">' + escapeHtml(fallbackLabel) + '</option>');
    options.forEach(function (item) {
      html.push('<option value="' + escapeHtml(item.key) + '">' + escapeHtml(item.label) + '</option>');
    });
    select.innerHTML = html.join("");
  }

  function syncControls() {
    if (elements.trackingDatePickerValue) elements.trackingDatePickerValue.textContent = state.snapshot_date || "--";
    setValue(elements.trackingWindowSelect, String(state.tracking_window_days || 30));
    setValue(elements.trackingCategoryPeriodSelect, String(state.category_period_days || 30));
    setValue(elements.trackingLevelSelect, state.level || "all");
    setValue(elements.trackingStatusSelect, state.status || "all");
    setValue(elements.trackingSiteSelect, state.site || "all");
    setValue(elements.trackingStoreSelect, state.store || "all");
    elements.trackingKeywordInput.value = state.keyword || "";
    setValue(elements.trackingPageSizeSelect, String(state.page_size || 20));
  }

  function setValue(select, value) {
    if (!select) return;
    var target = String(value == null ? "" : value);
    if ([].some.call(select.options, function (option) { return option.value === target; })) {
      select.value = target;
    }
  }

  function toggleDatePicker() {
    if (elements.trackingDatePickerPanel.hidden) {
      datePickerMonth = monthStartFromValue(state.snapshot_date || (trackingMeta.dates || [])[0]);
      renderDatePicker();
      elements.trackingDatePickerPanel.hidden = false;
      elements.trackingDatePickerBtn.setAttribute("aria-expanded", "true");
    } else {
      closeDatePicker();
    }
  }

  function closeDatePicker() {
    if (!elements.trackingDatePickerPanel) return;
    elements.trackingDatePickerPanel.hidden = true;
    if (elements.trackingDatePickerBtn) elements.trackingDatePickerBtn.setAttribute("aria-expanded", "false");
  }

  function selectDateValue(value) {
    if (!value || state.snapshot_date === value) {
      closeDatePicker();
      return;
    }
    state.snapshot_date = value;
    state.page = 1;
    datePickerMonth = monthStartFromValue(value);
    closeDatePicker();
    syncControls();
    render();
  }

  function renderDatePicker(nextMeta) {
    if (!elements.trackingDatePickerPanel) return;
    if (nextMeta) trackingMeta = nextMeta;
    var availableDates = (trackingMeta || {}).dates || [];
    var availableMap = availableDates.reduce(function (map, value) {
      map[value] = true;
      return map;
    }, {});
    var month = datePickerMonth || monthStartFromValue(state.snapshot_date || availableDates[0]);
    var firstDay = new Date(month.getFullYear(), month.getMonth(), 1);
    var daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    var leading = (firstDay.getDay() + 6) % 7;
    var todayValue = dateToValue(new Date());
    var cells = [];
    for (var blank = 0; blank < leading; blank += 1) {
      cells.push('<span class="calendar-day-spacer"></span>');
    }
    for (var day = 1; day <= daysInMonth; day += 1) {
      var date = new Date(month.getFullYear(), month.getMonth(), day);
      var value = dateToValue(date);
      var enabled = !!availableMap[value];
      var classes = ["calendar-day"];
      if (value === state.snapshot_date) classes.push("boundary");
      if (value === todayValue) classes.push("today");
      if (!enabled) classes.push("disabled");
      cells.push([
        '<button type="button" class="' + classes.join(" ") + '" data-date-value="' + escapeHtml(value) + '"' + (enabled ? "" : " disabled") + '>',
        day,
        '</button>'
      ].join(""));
    }
    elements.trackingDatePickerPanel.innerHTML = [
      '<div class="date-range-toolbar replenishment-calendar-toolbar">',
      '<button class="date-nav-button" type="button" data-date-action="-1" aria-label="上一月">&lsaquo;</button>',
      '<strong>' + escapeHtml(formatMonthTitle(month)) + '</strong>',
      '<button class="date-nav-button" type="button" data-date-action="1" aria-label="下一月">&rsaquo;</button>',
      '</div>',
      '<div class="calendar-month replenishment-calendar-month">',
      '<div class="calendar-weekdays">',
      ["一", "二", "三", "四", "五", "六", "日"].map(function (dayName) {
        return '<span class="calendar-weekday">' + dayName + '</span>';
      }).join(""),
      '</div>',
      '<div class="calendar-days">' + cells.join("") + '</div>',
      '</div>',
      '<div class="replenishment-calendar-foot">只显示已生成追踪结果的补货日期</div>'
    ].join("");
  }

  function parseDateValue(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }

  function monthStartFromValue(value) {
    var parsed = parseDateValue(value) || new Date();
    return new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  }

  function shiftMonth(value, offset) {
    var month = value || monthStartFromValue("");
    return new Date(month.getFullYear(), month.getMonth() + offset, 1);
  }

  function formatMonthTitle(value) {
    return value.getFullYear() + "年" + String(value.getMonth() + 1).padStart(2, "0") + "月";
  }

  function dateToValue(value) {
    return [
      value.getFullYear(),
      String(value.getMonth() + 1).padStart(2, "0"),
      String(value.getDate()).padStart(2, "0")
    ].join("-");
  }

  function renderSummary(summary) {
    var purchaseRate = summary.msku_count ? summary.purchase_planned_msku_count / summary.msku_count : 0;
    var cards = [
      ["追踪 MSKU", summary.msku_count, "仅紧急/建议/计划三层"],
      ["已建采购计划 MSKU", summary.purchase_planned_msku_count, "占比 " + formatPercent(purchaseRate)],
      ["未建采购计划 MSKU", summary.purchase_unplanned_msku_count, "追踪窗口内未出现采购计划单"],
      ["后续采购总数", summary.purchase_plan_total_qty, "窗口内采购计划数量合计"],
      ["创建FBA货件数", summary.current_fba_shipment_plan_qty, "本次采购之后创建的FBA货件"],
      ["本次FBA在途数", summary.current_shipped_qty, "本次采购链路内FBA在途数量"],
      ["历史FBA在途数", summary.historical_shipped_qty, "窗口内在途但早于本次采购"],
      ["补货建议数", summary.replenishment_qty, "看板补货数量"]
    ];
    elements.trackingSummaryGrid.innerHTML = cards.map(function (card, index) {
      return [
        '<div class="alert-stat-card tracking-stat-card tone-' + (index % 3) + '">',
        '<span>' + escapeHtml(card[0]) + '</span>',
        '<strong>' + formatMaybeNumber(card[1]) + '</strong>',
        '<small>' + escapeHtml(card[2]) + '</small>',
        '</div>'
      ].join("");
    }).join("");
  }

  function renderLevelTabs(levels, summary) {
    if (!elements.trackingLevelTabs) return;
    var total = Number((summary || {}).msku_count || 0);
    var rows = [{ level: "all", label: "全部", count: total }].concat((levels || []).map(function (row) {
      return {
        level: row.level || "",
        label: row.level || "-",
        count: Number(row.msku_count || 0)
      };
    }));
    elements.trackingLevelTabs.innerHTML = rows.map(function (row) {
      var active = (state.level || "all") === row.level ? " active" : "";
      return [
        '<button class="' + active + '" type="button" data-level-tab="' + escapeHtml(row.level) + '">',
        escapeHtml(row.label),
        '<span>· ' + formatNumber(row.count, 0) + '</span>',
        '</button>'
      ].join("");
    }).join("");
  }

  function renderLayerViz(levels, summary) {
    if (!levels.length) {
      elements.trackingLayerVizGrid.innerHTML = '<div class="empty-state compact">暂无分层追踪数据</div>';
      return;
    }
    var actionRows = levels.filter(function (row) { return Number(row.sort || 0) <= 3; });
    elements.trackingLayerVizGrid.innerHTML = [
      '<div class="panel replenish-action-panel tracking-layer-panel">',
      '<div class="replenish-panel-title tracking-panel-title">',
      '<span class="tracking-panel-main-title">层级采购追踪</span><strong>链路断点诊断</strong>',
      '</div>',
      actionRows.map(function (row) {
        return renderTrackingLayerRow(row);
      }).join(""),
      '</div>',
      '<div class="panel layer-mix-panel tracking-side-panel">',
      '<div class="layer-mix-title">采购计划状态</div>',
      renderStatusRows(summary || {}),
      '<div class="layer-mix-foot">只统计紧急/建议/计划三层，点击状态可筛选明细</div>',
      '</div>'
    ].join("");
  }

  function renderTrackingLayerRow(row) {
    var level = row.level || "";
    var planned = Number(row.purchase_planned_msku_count || 0);
    var total = Number(row.msku_count || 0);
    var fbaPlanned = Number(row.fba_plan_msku_count || 0);
    var shipped = Number(row.shipped_msku_count || 0);
    var historicalShipped = Number(row.historical_shipped_msku_count || 0);
    var ratio = total ? planned / total : 0;
    var unplanned = Math.max(total - planned, 0);
    var missingFba = Math.max(planned - fbaPlanned, 0);
    var unshipped = Math.max(fbaPlanned - shipped, 0);
    var width = Math.max(2, Math.round(ratio * 100));
    var active = state.level === level ? " active" : "";
    return [
      '<div class="replenish-layer-row tracking-layer-row level-' + escapeHtml(String(row.sort || "")) + active + '" data-tracking-level="' + escapeHtml(level) + '" data-tracking-status="all" role="button" tabindex="0">',
      '<span class="layer-mark">' + layerGlyph(row.sort) + '</span>',
      '<span class="layer-name">',
      '<span class="layer-title"><span>' + escapeHtml(level) + '</span></span>',
      '<small>共 ' + formatNumber(total, 0) + ' 个 · 已建采购计划 ' + formatNumber(planned, 0) + ' 个 · 未建 ' + formatNumber(row.purchase_unplanned_msku_count, 0) + ' 个 · 覆盖率 ' + formatPercent(ratio) + '</small>',
      '<span class="tracking-purchase-chips">',
      '<button type="button" data-tracking-level="' + escapeHtml(level) + '" data-tracking-status="purchase_planned">已建采购 ' + formatNumber(planned, 0) + '</button>',
      '<button type="button" data-tracking-level="' + escapeHtml(level) + '" data-tracking-status="unplanned">未建采购 ' + formatNumber(row.purchase_unplanned_msku_count, 0) + '</button>',
      '</span>',
      renderCategoryPurchaseMix(row.category_purchase_mix || [], total),
      '</span>',
      '<span class="tracking-stage-flow">',
      renderTrackingStage(level, "建采购计划", formatNumber(planned, 0) + "/" + formatNumber(total, 0), unplanned ? "未建 " + formatNumber(unplanned, 0) : "全部已建", "purchase_planned", unplanned ? "warn" : "ok"),
      renderTrackingStage(level, "创建FBA货件", formatNumber(fbaPlanned, 0), "数量 " + formatNumber(row.current_fba_shipment_plan_qty, 0), "shipment_planned", missingFba ? "warn" : "ok"),
      renderTrackingStage(level, "本次FBA在途", formatNumber(shipped, 0), "数量 " + formatNumber(row.current_shipped_qty, 0), "shipped", unshipped ? "danger" : "ok"),
      renderTrackingStage(level, "历史FBA在途", formatNumber(historicalShipped, 0), "数量 " + formatNumber(row.historical_shipped_qty, 0), "historical_shipped", historicalShipped ? "warn" : "neutral"),
      '</span>',
      '<span class="layer-progress"><i style="width:' + width + '%"></i></span>',
      '</div>'
    ].join("");
  }

  function renderTrackingStage(level, label, value, hint, status, tone) {
    var active = state.level === level && state.status === status ? " active" : "";
    return [
      '<button class="tracking-stage-card ' + escapeHtml(tone || "neutral") + active + '" type="button" data-tracking-level="' + escapeHtml(level || "all") + '" data-tracking-status="' + escapeHtml(status) + '">',
      '<small>' + escapeHtml(label) + renderStageHelp(status) + '</small>',
      '<strong>' + escapeHtml(value) + '</strong>',
      '<em>' + escapeHtml(hint) + '</em>',
      '</button>'
    ].join("");
  }

  function renderStageHelp(status) {
    var help = {
      purchase_planned: "补货日期之后创建了采购计划的 MSKU 数；分母是该层级追踪 MSKU 总数。",
      shipment_planned: "本次采购之后创建的 FBA 货件；如果 FBA 计划早于本次采购，会归为历史链路。",
      shipped: "本次FBA在途：货件所属 FBA 计划晚于本次采购，且已有发货在途数量。",
      historical_shipped: "历史FBA在途：窗口内有在途发货，但所属 FBA 计划早于本次采购，或没有本次采购可关联。"
    }[status];
    if (!help) return "";
    return '<span class="stage-help" title="' + escapeHtml(help) + '" aria-label="' + escapeHtml(help) + '">?</span>';
  }

  function renderCategoryPurchaseMix(mix, levelTotal) {
    if (!mix.length) return "";
    return '<span class="tracking-category-mix">' + mix.map(function (item) {
      var planned = Number(item.purchase_planned_msku_count || 0);
      var total = Number(item.msku_count || 0);
      var ratio = total ? planned / total : 0;
      return [
        '<span class="tracking-category-chip" title="',
        escapeHtml(item.category || "-") + '：已建采购计划 ' + formatNumber(planned, 0) + ' / 共 ' + formatNumber(total, 0) + '，后续采购单数 ' + formatNumber(item.purchase_plan_count, 0) + '，后续采购总数 ' + formatNumber(item.purchase_plan_total_qty, 0) + '，待采购计划数 ' + formatNumber(item.purchase_plan_qty, 0),
        '">',
        escapeHtml(item.category || "-") + ' ',
        '<b>' + formatNumber(planned, 0) + '/' + formatNumber(total, 0) + '</b> ',
        '<em>' + formatPercent(ratio) + '</em>',
        '</span>'
      ].join("");
    }).join("") + '</span>';
  }

  function renderStatusRows(summary) {
    var rows = [
      { label: "已建采购计划", status: "purchase_planned", value: summary.purchase_planned_msku_count, sub: "追踪窗口内出现采购计划单" },
      { label: "未建采购计划", status: "unplanned", value: summary.purchase_unplanned_msku_count, sub: "未匹配窗口内采购计划单" },
      { label: "后续采购单数", status: "purchase_planned", value: summary.purchase_plan_count, sub: "后续采购总数 " + formatNumber(summary.purchase_plan_total_qty, 0) },
      { label: "创建FBA货件", status: "shipment_planned", value: summary.fba_plan_msku_count, sub: "本次FBA货件数量 " + formatNumber(summary.current_fba_shipment_plan_qty, 0) },
      { label: "本次FBA在途", status: "shipped", value: summary.shipped_msku_count, sub: "本次在途数量 " + formatNumber(summary.current_shipped_qty, 0) },
      { label: "历史FBA在途", status: "historical_shipped", value: summary.historical_shipped_msku_count, sub: "历史在途数量 " + formatNumber(summary.historical_shipped_qty, 0) },
      { label: "已收货", status: "received", value: summary.received_msku_count, sub: "已收数量 " + formatNumber(summary.received_qty, 0) }
    ];
    return rows.map(function (row, index) {
      return [
        '<button class="tracking-passive-row tracking-status-row" type="button" data-tracking-level="' + escapeHtml(state.level || "all") + '" data-tracking-status="' + escapeHtml(row.status) + '">',
        '<span class="layer-mark">' + ["采", "未", "单", "计", "发", "史", "收"][index] + '</span>',
        '<span><strong>' + escapeHtml(row.label) + '</strong><small>' + escapeHtml(row.sub) + '</small></span>',
        '<b>' + formatNumber(row.value, 0) + '</b>',
        '</button>'
      ].join("");
    }).join("");
  }

  function renderPassiveRow(row) {
    var planned = Number(row.purchase_planned_msku_count || 0);
    var total = Number(row.msku_count || 0);
    var ratio = total ? planned / total : 0;
    return [
      '<button class="tracking-passive-row" type="button" data-tracking-level="' + escapeHtml(row.level || "") + '" data-tracking-status="all">',
      '<span class="layer-mark">' + layerGlyph(row.sort) + '</span>',
      '<span><strong>' + escapeHtml(row.level || "-") + '</strong><small>已建采购计划 ' + formatNumber(planned, 0) + ' / ' + formatNumber(total, 0) + ' · 覆盖率 ' + formatPercent(ratio) + '</small></span>',
      '<b>' + formatNumber(row.purchase_plan_qty, 0) + ' / ' + formatNumber(row.purchase_shipping_qty, 0) + '</b>',
      '</button>'
    ].join("");
  }

  function layerGlyph(sort) {
    var map = { 1: "急", 2: "建", 3: "计", 4: "足", 5: "0", 6: "史" };
    return map[Number(sort)] || "层";
  }

  function renderTable(rows) {
    if (!rows.length) {
      elements.trackingTableWrap.innerHTML = '<div class="empty-state compact">当前筛选无追踪数据。</div>';
      return;
    }
    window.trackingRowMap = rows.reduce(function (map, row, index) {
      row.__rowKey = "tracking-row-" + index;
      map[row.__rowKey] = row;
      return map;
    }, {});
    gridRenderSeq += 1;
    var gridId = "trackingAgGrid-" + gridRenderSeq;
    elements.trackingTableWrap.innerHTML = '<div id="' + gridId + '"></div>';
    window.kanbanGrid.makeGrid(gridId, {
      rowData: rows,
      domLayout: "normal",
      rowHeight: 58,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">暂无追踪数据</span>',
      columnDefs: [
        { headerName: "层级", field: "level", pinned: "left", width: 118, cellRenderer: function (params) { return '<span class="status-pill level-' + escapeHtml(String(params.data.level_sort || "")) + '">' + escapeHtml(params.value || "") + '</span>'; } },
        { headerName: "MSKU / SKU", field: "msku", pinned: "left", width: 150, cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.msku || "-", params.data.sku || ""); } },
        { headerName: "店铺", field: "store", width: 120 },
        { headerName: "国家类别", field: "country", width: 112 },
        { headerName: "产品分类", field: "category", width: 112 },
        numberColumn("补货数", "replenishment_qty", 108, 0),
        moneyColumn("补货货值", "replenishment_value", 126),
        numberColumn("后续采购单数", "purchase_plan_count", 126, 0),
        numberColumn("后续采购总数", "purchase_plan_total_qty", 126, 0),
        numberColumn("待采购计划数", "purchase_plan_qty", 128, 0),
        numberColumn("采购在途数", "purchase_snapshot_shipping_qty", 120, 0),
        { headerName: "后续采购状态", field: "purchase_planned", width: 132, cellRenderer: function (params) { return statusPill(params.value ? "已建采购" : "未建采购", params.value ? "positive" : "warning"); } },
        { headerName: "发货判断", field: "shipment_attribution", width: 126, cellRenderer: function (params) { return renderShipmentJudgement(params.data || {}); } },
        numberColumn("创建FBA货件", "current_fba_shipment_plan_qty", 126, 0),
        numberColumn("本次FBA在途", "current_shipped_qty", 126, 0),
        numberColumn("历史FBA在途", "historical_shipped_qty", 126, 0),
        { headerName: "最近预计到货", field: "nearest_fba_eta_label", width: 156, cellRenderer: function (params) { return renderEtaLabel(params.data || {}); } },
        numberColumn("已收", "received_qty", 92, 0),
        { headerName: "运输方式", field: "main_shipping_method", width: 120 },
        { headerName: "物流渠道", field: "main_logistics_channel", width: 140 },
        { headerName: "最新状态", field: "latest_status", width: 142 },
        { headerName: "操作", field: "__rowKey", pinned: "right", width: 108, cellRenderer: function (params) { return '<button class="text-button" type="button" data-tracking-detail data-row-key="' + escapeHtml(params.value) + '">查看明细</button>'; } }
      ]
    });
  }

  function renderPagination(payload) {
    elements.trackingPaginationInfo.textContent = "共 " + formatNumber(payload.total || 0, 0) + " 条，第 " + (payload.page || 1) + " / " + (payload.total_pages || 1) + " 页";
    elements.trackingPrevPageBtn.disabled = Number(payload.page || 1) <= 1;
    elements.trackingNextPageBtn.disabled = Number(payload.page || 1) >= Number(payload.total_pages || 1);
    var totalPages = Number(payload.total_pages || 1);
    var current = Number(payload.page || 1);
    var pages = [];
    for (var page = Math.max(1, current - 2); page <= Math.min(totalPages, current + 2); page += 1) {
      pages.push('<button class="' + (page === current ? "active" : "") + '" type="button" data-page="' + page + '">' + page + '</button>');
    }
    elements.trackingPaginationNumbers.innerHTML = pages.join("");
    elements.trackingPaginationNumbers.querySelectorAll("[data-page]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.page = Number(button.dataset.page || 1);
        render();
      });
    });
  }

  function openDetail(row) {
    elements.trackingDetailMask.hidden = false;
    elements.trackingDetailDrawer.hidden = false;
    elements.trackingDetailDrawer.setAttribute("aria-hidden", "false");
    elements.trackingDetailTitle.textContent = (row.msku || "-") + " / " + (row.store || "-") + " / " + (row.country || "-");
    elements.trackingDetailSubtitle.textContent = (row.sku || "-") + " · " + (row.level || "-") + " · 追踪窗口 " + (row.tracking_window_days || state.tracking_window_days) + " 天";
    elements.trackingDetailWrap.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/replenishment-tracking/detail", {
      snapshot_date: row.snapshot_date,
      tracking_window_days: row.tracking_window_days,
      site: row.country,
      store: row.store,
      msku: row.msku
    }).then(function (payload) {
      renderDetailTable(payload.rows || []);
    }).catch(function () {
      elements.trackingDetailWrap.innerHTML = '<div class="empty-state compact">明细加载失败。</div>';
    });
  }

  function closeDetail() {
    elements.trackingDetailMask.hidden = true;
    elements.trackingDetailDrawer.hidden = true;
    elements.trackingDetailDrawer.setAttribute("aria-hidden", "true");
  }

  function renderDetailTable(rows) {
    if (!rows.length) {
      elements.trackingDetailWrap.innerHTML = '<div class="empty-state compact">暂无采购或发货明细。</div>';
      return;
    }
    elements.trackingDetailWrap.innerHTML = '<div id="trackingDetailAgGrid"></div>';
    window.kanbanGrid.makeGrid("trackingDetailAgGrid", {
      rowData: rows,
      domLayout: "normal",
      rowHeight: 52,
      columnDefs: [
        { headerName: "来源", field: "source_type_label", pinned: "left", width: 120, cellRenderer: function (params) { return escapeHtml(params.value || params.data.source_type || "-"); } },
        { headerName: "链路归因", field: "link_attribution", width: 112, cellRenderer: function (params) { return statusPill(params.value === "current" ? "本次链路" : params.value === "historical" ? "历史链路" : "-", params.value === "current" ? "positive" : params.value === "historical" ? "warning" : "neutral"); } },
        { headerName: "采购计划单", field: "purchase_plan_sn", width: 150 },
        { headerName: "采购状态", field: "purchase_plan_status", width: 140 },
        numberColumn("待采购计划数", "purchase_plan_qty", 128, 0),
        { headerName: "FBA计划单", field: "order_sn", width: 150 },
        { headerName: "货件号", field: "shipment_sn", width: 150 },
        { headerName: "运输方式", field: "method_name", width: 120 },
        { headerName: "物流渠道", field: "logistics_channel_name", width: 160 },
        numberColumn("FBA计划数", "shipment_plan_quantity", 120, 0),
        numberColumn("已发", "quantity_shipped", 92, 0),
        numberColumn("已收", "quantity_received", 92, 0),
        { headerName: "采购时间", field: "purchase_plan_time", width: 170 },
        { headerName: "计划时间", field: "plan_create_time", width: 170 },
        { headerName: "发货时间", field: "shipment_time_display", width: 170 },
        { headerName: "预计到达", field: "expected_arrival_date", width: 170 }
      ]
    });
  }

  function numberColumn(headerName, field, width, digits) {
    return {
      headerName: headerName,
      field: field,
      width: width,
      type: "numericColumn",
      cellRenderer: function (params) {
        return '<span class="ag-number-strong">' + formatNumber(params.value, digits) + '</span>';
      }
    };
  }

  function moneyColumn(headerName, field, width) {
    return {
      headerName: headerName,
      field: field,
      width: width,
      type: "numericColumn",
      cellRenderer: function (params) {
        return '<span class="ag-number-strong">' + formatCurrency(params.value) + '</span>';
      }
    };
  }

  function statusPill(label, tone) {
    return '<span class="status-pill ' + escapeHtml(tone || "neutral") + '">' + escapeHtml(label) + '</span>';
  }

  function renderShipmentJudgement(row) {
    var currentShipped = Number(row.current_shipped_qty || 0);
    var historicalShipped = Number(row.historical_shipped_qty || 0);
    if (currentShipped > 0 && historicalShipped > 0) {
      return statusPill("本次+历史在途", "warning");
    }
    if (currentShipped > 0) {
      return statusPill("本次在途", "positive");
    }
    if (historicalShipped > 0) {
      return statusPill("历史在途", "warning");
    }
    return statusPill("未在途", "neutral");
  }

  function renderEtaLabel(row) {
    var label = row.nearest_fba_eta_label || "";
    if (!label) return '<span class="muted">-</span>';
    var tone = Number(row.nearest_fba_eta_days) < 0 ? "warning" : "neutral";
    return '<span class="status-pill ' + tone + '">' + escapeHtml(label) + '</span>';
  }

  function writeQueryState() {
    var params = new URLSearchParams();
    Object.keys(state).forEach(function (key) {
      var value = state[key];
      if (value == null || value === "" || value === "all") return;
      if (key === "page" && Number(value) === 1) return;
      if (key === "page_size" && Number(value) === 20) return;
      params.set(key, String(value));
    });
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? "?" + params.toString() : ""));
  }

  function normalizePageSize(value) {
    var size = Number(value || 20);
    if (size <= 20) return 20;
    if (size <= 50) return 50;
    return 100;
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
    });
  }

  function formatMaybeNumber(value) {
    if (typeof value === "string") return value;
    return formatNumber(value, 0);
  }

  function formatCurrency(value) {
    return app.formatCurrency ? app.formatCurrency(value) : ("¥" + formatNumber(value, 0));
  }

  function formatPercent(value) {
    return (Number(value || 0) * 100).toFixed(1) + "%";
  }

  function escapeHtml(value) {
    return app.escapeHtml ? app.escapeHtml(value) : String(value == null ? "" : value);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      clearTimeout(timer);
      var args = arguments;
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, wait);
    };
  }
}());
