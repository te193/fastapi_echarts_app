(function () {
  var app = window.kanbanApp;
  var periodConfig = window.PriceReviewPeriod || {
    defaultDays: "3",
    isSupported: function (value) { return ["3", "7", "14", "28"].indexOf(String(value || "")) >= 0; }
  };
  var charts = {};
  var elements = {};
  var topListData = {};
  var matrixData = {};
  var defaultAdjustDate = "";
  var initializedFromUrl = false;
  var adjustCalendarItems = [];
  var adjustCalendarMonth = "";

  // Global filter state — passed to every API call
  var filterState = {
    adjust_date: "",
    compare_days: periodConfig.defaultDays,
    country: "all",
    store: "all",
    drop_range: "all",
    risk_level: "all",
    price_band: "all",
    adjustment_type: "all",
    keyword: "",
    page: 1,
    page_size: 20,
    sort_field: "",
    sort_dir: "",
  };

  var currentMatrix = "daily_sales";
  var currentTopTab = "sales_up";
  var countryData = [];
  var hiddenCountries = [];
  var skuColumnFilters = {};
  var expandedMatrixBand = "";
  var expandedCountry = "";

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
    if (periodConfig.isSupported(urlCompareDays)) {
      filterState.compare_days = urlCompareDays;
    }
  }

  function syncFilterInputs() {
    if (elements.adjustDateInput) elements.adjustDateInput.value = filterState.adjust_date || "";
    setAdjustDateLabel(filterState.adjust_date || "");
    if (elements.compareDaysSelect) elements.compareDaysSelect.value = filterState.compare_days;
    if (elements.countrySelect) elements.countrySelect.value = filterState.country;
    if (elements.storeSelect) elements.storeSelect.value = filterState.store;
    if (elements.dropRangeSelect) elements.dropRangeSelect.value = filterState.drop_range;
    if (elements.riskLevelSelect) elements.riskLevelSelect.value = filterState.risk_level;
    if (elements.priceBandSelect) elements.priceBandSelect.value = filterState.price_band;
    if (elements.adjustmentTypeSelect) elements.adjustmentTypeSelect.value = filterState.adjustment_type;
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
      "secondAdjustSummary", "secondAdjustDateChart", "secondAdjustGapChart", "secondAdjustGrid",
      "topListTabs", "topListGrid",
      // Filters
      "adjustDateButton", "adjustDateValue", "adjustDateInput", "adjustCalendarPanel", "compareDaysSelect",
      "countrySelect", "storeSelect", "dropRangeSelect", "riskLevelSelect", "priceBandSelect", "adjustmentTypeSelect", "keywordInput",
      "applyFiltersBtn", "resetFiltersBtn",
      // SKU table
      "skuTableCountText", "priceReviewSkuGrid", "paginationInfo", "paginationNumbers", "prevPageBtn", "nextPageBtn",
      // Export buttons
      "exportTopListBtn", "exportSkuListBtn",
      // Calendar
      "calendarToggleBtn", "calendarBody", "calendarGrid", "calendarSummary",
      // Country show-all
      "countryShowAllBtn",
      "priceReviewDrawerMask", "priceReviewDrawer", "closePriceReviewDrawerBtn", "priceReviewDrawerTitle", "priceReviewDrawerSubtitle", "priceReviewDrawerContent",
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

  function buildSkuQuery(extra) {
    var q = buildQuery(extra);
    var separator = q ? "&" : "?";
    var parts = [];
    Object.keys(skuColumnFilters).forEach(function (key) {
      var value = skuColumnFilters[key];
      if (value !== "" && value !== null && value !== undefined) {
        parts.push("cf_" + encodeURIComponent(key) + "=" + encodeURIComponent(value));
      }
    });
    return q + (parts.length ? separator + parts.join("&") : "");
  }

  function refreshAll() {
    setLoading(true);
    updatePageTitle();
    Promise.all([
      loadOverview(),
      loadDropRange(),
      loadMatrices(),
      loadCountries(),
      loadSecondAdjustments(),
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
    elements.pageTitle.textContent = label + " 调价前后 " + filterState.compare_days + " 天追踪";
  }

  function bindEvents() {
    // Matrix tabs
    if (elements.matrixTabs) {
      elements.matrixTabs.addEventListener("click", function (event) {
        var button = event.target.closest("[data-matrix]");
        if (!button) return;
        currentMatrix = button.dataset.matrix;
        expandedMatrixBand = "";
        Array.from(elements.matrixTabs.querySelectorAll("[data-matrix]")).forEach(function (b) {
          b.classList.toggle("active", b.dataset.matrix === currentMatrix);
        });
        renderMatrix(currentMatrix);
      });
    }

    if (elements.closePriceReviewDrawerBtn) elements.closePriceReviewDrawerBtn.addEventListener("click", closePriceReviewDrawer);
    if (elements.priceReviewDrawerMask) elements.priceReviewDrawerMask.addEventListener("click", closePriceReviewDrawer);

    if (elements.adjustDateButton && elements.adjustCalendarPanel) {
      elements.adjustDateButton.addEventListener("click", function (event) {
        event.stopPropagation();
        toggleAdjustCalendar();
      });
      elements.adjustCalendarPanel.addEventListener("click", function (event) {
        event.stopPropagation();
        var nav = event.target.closest("[data-adjust-calendar-nav]");
        var dateButton = event.target.closest("[data-adjust-date]");
        if (nav) {
          adjustCalendarMonth = shiftAdjustMonth(adjustCalendarMonth, Number(nav.getAttribute("data-adjust-calendar-nav")));
          renderAdjustCalendar();
          return;
        }
        if (dateButton) {
          var selectedDate = dateButton.getAttribute("data-adjust-date") || "";
          elements.adjustDateInput.value = selectedDate;
          setAdjustDateLabel(selectedDate);
          renderAdjustCalendar();
          closeAdjustCalendar();
        }
      });
      document.addEventListener("click", function (event) {
        if (!event.target.closest(".price-review-date-control")) closeAdjustCalendar();
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
        filterState.adjustment_type = elements.adjustmentTypeSelect ? elements.adjustmentTypeSelect.value : "all";
        filterState.keyword = elements.keywordInput ? elements.keywordInput.value.trim() : "";
        filterState.page = 1;
        filterState.sort_field = "";
        filterState.sort_dir = "";
        expandedMatrixBand = "";
        expandedCountry = "";
        refreshAll();
      });
    }

    // Reset filters
    if (elements.resetFiltersBtn) {
      elements.resetFiltersBtn.addEventListener("click", function () {
        if (elements.adjustDateInput) elements.adjustDateInput.value = defaultAdjustDate;
        setAdjustDateLabel(defaultAdjustDate);
        renderAdjustCalendar();
        if (elements.compareDaysSelect) elements.compareDaysSelect.value = periodConfig.defaultDays;
        if (elements.countrySelect) elements.countrySelect.value = "all";
        if (elements.storeSelect) elements.storeSelect.value = "all";
        if (elements.dropRangeSelect) elements.dropRangeSelect.value = "all";
        if (elements.riskLevelSelect) elements.riskLevelSelect.value = "all";
        if (elements.priceBandSelect) elements.priceBandSelect.value = "all";
        if (elements.adjustmentTypeSelect) elements.adjustmentTypeSelect.value = "all";
        if (elements.keywordInput) elements.keywordInput.value = "";

        filterState.adjust_date = defaultAdjustDate;
        filterState.compare_days = periodConfig.defaultDays;
        filterState.country = "all";
        filterState.store = "all";
        filterState.drop_range = "all";
        // 暂时移除风险等级筛选
        // filterState.risk_level = "all";
        filterState.price_band = "all";
        filterState.adjustment_type = "all";
        filterState.keyword = "";
        filterState.page = 1;
        filterState.sort_field = "";
        filterState.sort_dir = "";
        skuColumnFilters = {};
        expandedMatrixBand = "";
        expandedCountry = "";
        closeColumnFilterPopover();
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
        var url = "/api/price-review/skus/export" + buildSkuQuery(extra);
        window.open(url, "_blank");
      });
    }

    bindSkuColumnFilters();

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

    if (elements.calendarGrid) {
      elements.calendarGrid.addEventListener("click", function (event) {
        var noteButton = event.target.closest("[data-calendar-note-action='edit']");
        if (noteButton) {
          event.preventDefault();
          event.stopPropagation();
          openCalendarNoteEditor(noteButton);
          return;
        }

        var body = event.target.closest("[data-calendar-action='open']");
        if (body && body.dataset.href) {
          window.location.href = body.dataset.href;
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
    return Promise.all([
      app.apiGet("/api/price-adjustments/daily-counts?days=30"),
      app.apiGet("/api/price-adjustments/daily-counts?include_all=true")
    ])
      .then(function (payloads) {
        var recentItems = payloads[0].items || [];
        var allItems = payloads[1].items || [];
        adjustCalendarItems = allItems;
        applyDefaultAdjustDate(allItems);
        adjustCalendarMonth = adjustCalendarMonth || adjustMonthKey(filterState.adjust_date || defaultAdjustDate);
        renderAdjustCalendar();
        renderCalendar(recentItems);
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

  function toggleAdjustCalendar() {
    if (!elements.adjustCalendarPanel) return;
    if (elements.adjustCalendarPanel.hidden) {
      var selectedDate = elements.adjustDateInput ? elements.adjustDateInput.value : filterState.adjust_date;
      adjustCalendarMonth = adjustMonthKey(selectedDate || defaultAdjustDate);
      renderAdjustCalendar();
      elements.adjustCalendarPanel.hidden = false;
      elements.adjustDateButton.setAttribute("aria-expanded", "true");
      return;
    }
    closeAdjustCalendar();
  }

  function closeAdjustCalendar() {
    if (!elements.adjustCalendarPanel || !elements.adjustDateButton) return;
    elements.adjustCalendarPanel.hidden = true;
    elements.adjustDateButton.setAttribute("aria-expanded", "false");
  }

  function setAdjustDateLabel(dateValue) {
    if (!elements.adjustDateValue) return;
    elements.adjustDateValue.textContent = dateValue ? dateValue.replace(/-/g, "/") : "--";
  }

  function renderAdjustCalendar() {
    if (!elements.adjustCalendarPanel) return;
    var availableItems = adjustCalendarItems.filter(function (item) {
      return item.clickable && item.count > 0;
    });
    if (!availableItems.length) {
      elements.adjustCalendarPanel.innerHTML = '<div class="snapshot-calendar-empty">暂无可用调价日期</div>';
      return;
    }
    var selectedDate = elements.adjustDateInput ? elements.adjustDateInput.value : filterState.adjust_date;
    var month = adjustCalendarMonth || adjustMonthKey(selectedDate || availableItems[availableItems.length - 1].date);
    adjustCalendarMonth = month;
    var parts = month.split("-");
    var year = Number(parts[0]);
    var monthIndex = Number(parts[1]) - 1;
    var firstDay = new Date(year, monthIndex, 1);
    var daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
    var leading = (firstDay.getDay() + 6) % 7;
    var available = {};
    availableItems.forEach(function (item) { available[item.date] = true; });
    var itemsByDate = {};
    adjustCalendarItems.forEach(function (item) { itemsByDate[item.date] = item; });
    var html = [
      '<div class="snapshot-calendar-head">',
      '<button type="button" class="snapshot-calendar-nav" data-adjust-calendar-nav="-1" aria-label="上个月">‹</button>',
      '<strong>' + year + '年' + pad2(monthIndex + 1) + '月</strong>',
      '<button type="button" class="snapshot-calendar-nav" data-adjust-calendar-nav="1" aria-label="下个月">›</button>',
      '</div>',
      '<div class="snapshot-calendar-weekdays">',
      ["一", "二", "三", "四", "五", "六", "日"].map(function (day) { return '<span>' + day + '</span>'; }).join(""),
      '</div>',
      '<div class="snapshot-calendar-days">'
    ];
    for (var i = 0; i < leading; i += 1) html.push('<span class="snapshot-calendar-spacer"></span>');
    for (var dayNumber = 1; dayNumber <= daysInMonth; dayNumber += 1) {
      var dateValue = year + "-" + pad2(monthIndex + 1) + "-" + pad2(dayNumber);
      var enabled = !!available[dateValue];
      var dayItem = itemsByDate[dateValue];
      var countHtml = dayItem && dayItem.count > 0
        ? '<span class="snapshot-calendar-day-count">' + app.escapeHtml(String(dayItem.count)) + '个</span>'
        : "";
      html.push(
        '<button type="button" class="snapshot-calendar-day' +
        (enabled ? "" : " disabled") +
        (dateValue === selectedDate ? " active" : "") +
        '" ' + (enabled ? 'data-adjust-date="' + dateValue + '"' : "disabled") +
        '><span class="snapshot-calendar-day-number">' + dayNumber + '</span>' + countHtml + '</button>'
      );
    }
    html.push('</div><p class="snapshot-calendar-foot">只显示近30天有调价数据的日期</p>');
    elements.adjustCalendarPanel.innerHTML = html.join("");
  }

  function adjustMonthKey(dateValue) {
    var parts = String(dateValue || "").split("-");
    if (parts.length !== 3) return "";
    return parts[0] + "-" + parts[1];
  }

  function shiftAdjustMonth(monthValue, offset) {
    var parts = String(monthValue || "").split("-");
    if (parts.length !== 2) return monthValue;
    var dateValue = new Date(Number(parts[0]), Number(parts[1]) - 1 + offset, 1);
    return dateValue.getFullYear() + "-" + pad2(dateValue.getMonth() + 1);
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
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
      var hrefAttr = item.clickable ? ' data-href="' + app.escapeHtml(href) + '"' : "";
      var disabledClass = item.clickable ? "" : " disabled";
      var note = item.note || "";
      var noteClass = note ? " has-note" : "";
      var noteTitle = note ? ("调价说明：" + note) : "点击输入调价说明";
      var cardTitle = item.date + " 调价 " + item.count + " 个产品" + (note ? ("\n调价说明：" + note) : "");

      html.push(
        '<div class="calendar-card ' + hClass + todayClass + weekendClass + disabledClass + noteClass + '" data-date="' + app.escapeHtml(item.date) + '" data-note="' + app.escapeHtml(note) + '" title="' + app.escapeHtml(cardTitle) + '">' +
        '  <div class="calendar-card-body" data-calendar-action="open"' + hrefAttr + '>' +
        '  <span class="calendar-date">' + app.escapeHtml(item.display_date) + '</span>' +
        '  <span class="calendar-weekday">' + app.escapeHtml(item.weekday) + '</span>' +
        '  <span class="calendar-count">' + item.count + '</span>' +
        '  <span class="calendar-label">个产品调价</span>' +
        '  </div>' +
        '  <button class="calendar-note-trigger" type="button" data-calendar-note-action="edit" title="' + app.escapeHtml(noteTitle) + '">' + (note ? "说明" : "+ 说明") + '</button>' +
        '</div>'
      );
    });

    elements.calendarGrid.innerHTML = html.join("");
  }

  function openCalendarNoteEditor(button) {
    var card = button.closest(".calendar-card");
    if (!card) return;
    closeCalendarNoteEditor();
    card.classList.add("editing-note");

    var dateValue = card.dataset.date || "";
    var currentNote = card.dataset.note || "";
    var editor = document.createElement("div");
    editor.className = "calendar-note-editor";
    editor.innerHTML = [
      '<label class="calendar-note-editor-label">调价说明</label>',
      '<textarea maxlength="1000" rows="4" placeholder="输入调价原因，留空保存则清除说明">' + app.escapeHtml(currentNote) + '</textarea>',
      '<div class="calendar-note-editor-footer">',
      '  <span class="calendar-note-editor-status"></span>',
      '  <button class="ghost-button calendar-note-cancel" type="button">取消</button>',
      '  <button class="primary-button calendar-note-save" type="button">保存</button>',
      '</div>',
    ].join("");
    card.appendChild(editor);

    var textarea = editor.querySelector("textarea");
    var status = editor.querySelector(".calendar-note-editor-status");
    var saveBtn = editor.querySelector(".calendar-note-save");
    var cancelBtn = editor.querySelector(".calendar-note-cancel");
    if (textarea) {
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
    if (cancelBtn) cancelBtn.addEventListener("click", closeCalendarNoteEditor);
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var nextNote = (textarea ? textarea.value : "").trim();
        saveBtn.disabled = true;
        if (status) status.textContent = "保存中...";
        putJson("/api/price-adjustments/daily-notes/" + encodeURIComponent(dateValue), { note: nextNote })
          .then(function (payload) {
            updateCalendarCardNote(card, payload.note || "");
            closeCalendarNoteEditor();
          })
          .catch(function (err) {
            console.error("Failed to save calendar note:", err);
            if (status) status.textContent = "保存失败，请重试";
            saveBtn.disabled = false;
          });
      });
    }
  }

  function closeCalendarNoteEditor() {
    if (!elements.calendarGrid) return;
    var editor = elements.calendarGrid.querySelector(".calendar-note-editor");
    if (editor && editor.parentNode) {
      editor.parentNode.classList.remove("editing-note");
      editor.parentNode.removeChild(editor);
    }
  }

  function updateCalendarCardNote(card, note) {
    var dateValue = card.dataset.date || "";
    var countEl = card.querySelector(".calendar-count");
    var count = countEl ? countEl.textContent : "0";
    var button = card.querySelector(".calendar-note-trigger");
    card.dataset.note = note;
    card.classList.toggle("has-note", !!note);
    card.title = dateValue + " 调价 " + count + " 个产品" + (note ? ("\n调价说明：" + note) : "");
    if (button) {
      button.textContent = note ? "说明" : "+ 说明";
      button.title = note ? ("调价说明：" + note) : "点击输入调价说明";
    }
  }

  function putJson(path, payload) {
    return fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).then(function (response) {
      if (!response.ok) throw new Error("Request failed: " + response.status);
      return response.json();
    });
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
    if (type === "currency") return formatNumber(value, 2);
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
    var hintMap = {
      sales: "按销量区间观察调价前后 SKU 流向",
      daily_sales: "按日销层级观察调价前后 SKU 数量与占比变化",
      margin: "按毛利率层级观察经营质量迁移",
      rank: "按排名层级观察调价后的排名结构变化"
    };
    if (elements.matrixPanelTitle) {
      elements.matrixPanelTitle.textContent = (hintMap[type] || titleMap[type]);
    }

    var rows = data.rows;
    var totalBefore = rows.reduce(function (s, r) { return s + r.sku_before; }, 0);
    var totalAfter = rows.reduce(function (s, r) { return s + r.sku_after; }, 0);

    var html = [
      '<div class="matrix-list">',
      '  <div class="matrix-list-head">',
      '    <span>分层结构</span><span>调前 SKU</span><span>调前占比</span><span>调后 SKU</span><span>调后占比</span><span>SKU 净增减</span><span>操作</span>',
      '  </div>'
    ];

    rows.forEach(function (row) {
      var changeClass = row.sku_change > 0 ? "positive" : row.sku_change < 0 ? "negative" : "neutral";
      var changePrefix = row.sku_change > 0 ? "+" : "";
      var isExpanded = expandedMatrixBand === row.band;
      var insight = matrixBandInsight(type, row);
      html.push([
        '<div class="matrix-list-row ' + (isExpanded ? "expanded" : "") + '">',
        '  <div class="matrix-band-cell"><strong>' + app.escapeHtml(row.band) + '</strong><small>' + app.escapeHtml(insight) + '</small></div>',
        '  <div class="matrix-number"><strong>' + row.sku_before + '</strong></div>',
        '  <div class="matrix-muted">' + app.formatPercent(row.sku_before_ratio, 1) + '</div>',
        '  <div class="matrix-number"><strong>' + row.sku_after + '</strong></div>',
        '  <div class="matrix-muted">' + app.formatPercent(row.sku_after_ratio, 1) + '</div>',
        '  <div><span class="matrix-change-pill ' + changeClass + '">' + changePrefix + row.sku_change + '</span></div>',
        '  <div class="matrix-row-actions">',
        '    <button class="metric-toggle" type="button" data-matrix-band="' + app.escapeHtml(row.band) + '"><span>' + (isExpanded ? "收起指标" : "查看指标") + '</span><b>' + (isExpanded ? "⌃" : "⌄") + '</b></button>',
        '    <button class="matrix-flow-button" type="button" data-matrix-flow="' + app.escapeHtml(row.band) + '">流向图</button>',
        '  </div>',
        '</div>'
      ].join(""));
      if (isExpanded) {
        html.push([
          '<div class="matrix-detail-row">' + renderMetricDetailGrid(row) + '</div>'
        ].join(""));
      }
    });

    html.push([
      '<div class="matrix-list-row total">',
      '  <div class="matrix-band-cell"><strong>全系合计</strong></div>',
      '  <div class="matrix-number"><strong>' + formatNumber(totalBefore, 0) + '</strong></div>',
      '  <div class="matrix-muted">100%</div>',
      '  <div class="matrix-number"><strong>' + formatNumber(totalAfter, 0) + '</strong></div>',
      '  <div class="matrix-muted">100%</div>',
      '  <div></div>',
      '  <div></div>',
      '</div>'
    ].join(""));

    html.push('</div>');
    if (elements.matrixChart) {
      elements.matrixChart.innerHTML = html.join("");
      Array.from(elements.matrixChart.querySelectorAll("[data-matrix-band]")).forEach(function (button) {
        button.addEventListener("click", function () {
          var band = this.dataset.matrixBand || "";
          expandedMatrixBand = expandedMatrixBand === band ? "" : band;
          renderMatrix(currentMatrix);
        });
      });
      Array.from(elements.matrixChart.querySelectorAll("[data-matrix-flow]")).forEach(function (button) {
        button.addEventListener("click", function () {
          var band = this.dataset.matrixFlow || "";
          var row = rows.find(function (item) { return item.band === band; });
          if (row) openMatrixFlowDrawer(type, row, data);
        });
      });
    }
  }

  function openMatrixFlowDrawer(type, row, data) {
    if (!elements.priceReviewDrawer || !elements.priceReviewDrawerContent) return;
    var titleMap = { sales: "销量分层", daily_sales: "日销分层", margin: "毛利率分层", rank: "排名分层" };
    elements.priceReviewDrawerTitle.textContent = row.band + " 分层决策面板";
    elements.priceReviewDrawerSubtitle.textContent = (titleMap[type] || "分层") + "：调前 " + row.sku_before + " 个 → 调后 " + row.sku_after + " 个";
    elements.priceReviewDrawerContent.innerHTML = [
      '<section class="drawer-block">',
      '  <h3>分层迁移流向图</h3>',
      renderFlowDiagram(row, data),
      '</section>'
    ].join("");
    elements.priceReviewDrawerMask.classList.remove("hidden");
    elements.priceReviewDrawer.classList.remove("hidden");
    elements.priceReviewDrawer.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(function () {
      renderMatrixSankey(row, data);
    });
  }

  function closePriceReviewDrawer() {
    if (!elements.priceReviewDrawer || !elements.priceReviewDrawerMask) return;
    elements.priceReviewDrawerMask.classList.add("hidden");
    elements.priceReviewDrawer.classList.add("hidden");
    elements.priceReviewDrawer.setAttribute("aria-hidden", "true");
  }

  function renderFlowDiagram(row, data) {
    var allFlows = data.flows || [];
    var flows = allFlows.filter(function (flow) {
      return flow.source === row.band || flow.target === row.band;
    }).sort(function (a, b) { return b.value - a.value; });
    var retained = flows.find(function (flow) {
      return flow.source === row.band && flow.target === row.band;
    });
    var retainedValue = retained ? Number(retained.value || 0) : Math.min(Number(row.sku_before || 0), Number(row.sku_after || 0));
    var retainedRatio = row.sku_before ? retainedValue / row.sku_before : 0;
    var moveFlows = flows.filter(function (flow) {
      return flow.source !== flow.target;
    });
    var legend = moveFlows.slice(0, 8).map(function (flow) {
      return '<li><span>' + app.escapeHtml(flow.source) + ' → ' + app.escapeHtml(flow.target) + '</span><strong>' + flow.value + ' SKU</strong></li>';
    }).join("");
    if (!legend) legend = '<li><span>无跨分层迁移</span><strong>0 SKU</strong></li>';
    return [
      '<div class="flow-diagram-card">',
      '  <div class="flow-retention-strip">',
      '    <span>本层留存</span>',
      '    <strong>' + retainedValue.toLocaleString("zh-CN") + ' SKU</strong>',
      '    <em>' + app.formatPercent(retainedRatio, 1) + '</em>',
      '  </div>',
      '  <div id="matrixFlowSankey" class="flow-sankey-chart">',
      '  </div>',
      '  <ul class="flow-legend">' + legend + '</ul>',
      '</div>'
    ].join("");
  }

  function renderMatrixSankey(row, data) {
    var host = document.getElementById("matrixFlowSankey");
    if (!host || typeof echarts === "undefined") return;
    if (charts.matrixFlow) charts.matrixFlow.dispose();
    var allFlows = data.flows || [];
    var flows = allFlows.filter(function (flow) {
      return (flow.source === row.band || flow.target === row.band) && flow.source !== flow.target;
    });
    if (!flows.length) {
      host.innerHTML = '<div class="flow-empty-state">没有跨分层流入或流出，主要是本层留存。</div>';
      return;
    }
    var nodes = {};
    var links = flows.map(function (flow) {
      var source = flow.source + "（调前）";
      var target = flow.target + "（调后）";
      nodes[source] = { name: source, depth: 0 };
      nodes[target] = { name: target, depth: 1 };
      return { source: source, target: target, value: Number(flow.value || 0) };
    });
    var chart = echarts.init(host);
    charts.matrixFlow = chart;
    chart.setOption({
      tooltip: {
        trigger: "item",
        formatter: function (params) {
          if (params.dataType === "edge") {
            return params.data.source + " → " + params.data.target + "<br/>" + params.data.value + " SKU";
          }
          return params.name;
        }
      },
      series: [{
        type: "sankey",
        data: Object.keys(nodes).map(function (key) { return nodes[key]; }),
        links: links,
        left: 92,
        right: 96,
        top: 22,
        bottom: 22,
        nodeWidth: 12,
        nodeGap: 18,
        draggable: false,
        emphasis: { focus: "adjacency" },
        label: {
          color: "#dffefa",
          fontWeight: 800,
          fontSize: 12,
          formatter: function (params) {
            return String(params.name || "").replace("（调前）", "").replace("（调后）", "");
          }
        },
        itemStyle: {
          color: "#082a45",
          borderColor: "#27d7c2",
          borderWidth: 1,
          borderRadius: 4
        },
        lineStyle: {
          color: "gradient",
          curveness: 0.48,
          opacity: 0.72
        }
      }]
    });
  }

  function matrixBandInsight(type, row) {
    var change = Number(row.sku_change || 0);
    if (type === "daily_sales") {
      if (row.band === "日销 0") return "调价后流量骤降";
      if (row.band.indexOf("<1") >= 0) return "轻步回升分层";
      if (row.band.indexOf("1-5") >= 0) return "核心中坚销售层";
      return "调价观察的重销分层";
    }
    if (type === "margin") return change >= 0 ? "毛利结构承接层" : "毛利结构流出层";
    if (type === "rank") return change >= 0 ? "排名结构承接层" : "排名结构流出层";
    return change >= 0 ? "销量结构承接层" : "销量结构流出层";
  }

  function metricTone(value, lowerIsBetter) {
    var n = Number(value || 0);
    if (Math.abs(n) < 0.000001) return "neutral";
    return lowerIsBetter ? (n < 0 ? "positive" : "negative") : (n > 0 ? "positive" : "negative");
  }

  function formatNumber(value, digits) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function formatMetricValue(value, type) {
    if (type === "currency") return formatNumber(value, 2);
    if (type === "percent") return app.formatPercent(Number(value || 0), 1);
    if (type === "number0") return formatNumber(value, 0);
    return formatNumber(value, 2);
  }

  function renderBeforeAfterMetric(before, after, change, type, tone) {
    var prefix = Number(change || 0) > 0 ? "+" : "";
    return [
      '<div class="metric-compare-cell">',
      '  <span>' + formatMetricValue(before, type) + ' → ' + formatMetricValue(after, type) + '</span>',
      '  <strong class="' + tone + '">' + prefix + formatMetricValue(change, type) + '</strong>',
      '</div>'
    ].join("");
  }

  function renderMetricChange(change, type, tone) {
    var prefix = Number(change || 0) > 0 ? "+" : "";
    return '<span class="metric-change ' + tone + '">' + prefix + formatMetricValue(change, type) + '</span>';
  }

  function renderMetricDetailGrid(item) {
    var groups = [
      {
        title: "经营表现",
        metrics: [
          ["日销", item.daily_sales_before, item.daily_sales_after, item.daily_sales_change, "number", false],
          ["销量", item.sales_before, item.sales_after, item.sales_change, "number0", false],
          ["销售额", item.revenue_before, item.revenue_after, item.revenue_change, "currency", false],
          ["毛利润", item.profit_before, item.profit_after, item.profit_change, "currency", false],
          ["毛利率", item.margin_before, item.margin_after, item.margin_after - item.margin_before, "percent", false],
        ],
      },
      {
        title: "流量转化",
        metrics: [
          ["Sessions", item.sessions_before, item.sessions_after, item.sessions_change, "number0", false],
          ["转化率", item.conversion_before, item.conversion_after, item.conversion_after - item.conversion_before, "percent", false],
        ],
      },
      {
        title: "广告效率",
        metrics: [
          ["广告花费", item.ad_spend_before, item.ad_spend_after, item.ad_spend_change, "currency", true],
          ["ACOS", item.acos_before, item.acos_after, item.acos_after - item.acos_before, "percent", true],
          ["TACOS", item.tacos_before, item.tacos_after, item.tacos_after - item.tacos_before, "percent", true],
        ],
      },
    ];
    return '<div class="metric-detail-panel">' + groups.map(function (group) {
      return [
        '<section class="metric-detail-group">',
        '  <div class="metric-group-title">' + app.escapeHtml(group.title) + '</div>',
        '  <table class="metric-compare-table">',
        '    <thead><tr><th>指标</th><th>调前</th><th>调后</th><th>变化</th></tr></thead>',
        '    <tbody>',
        group.metrics.map(function (metric) {
          var tone = metricTone(metric[3], metric[5]);
          return [
            '<tr>',
            '  <th>' + app.escapeHtml(metric[0]) + '</th>',
            '  <td>' + formatMetricValue(metric[1], metric[4]) + '</td>',
            '  <td>' + formatMetricValue(metric[2], metric[4]) + '</td>',
            '  <td>' + renderMetricChange(metric[3], metric[4], tone) + '</td>',
            '</tr>'
          ].join("");
        }).join(""),
        '    </tbody>',
        '  </table>',
        '</section>'
      ].join("");
    }).join("") + '</div>';
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
      var revenueClass = metricTone(item.revenue_change);
      var profitClass = metricTone(item.profit_change);
      var isExpanded = expandedCountry === item.country;
      var rows = [
        '<tr>',
        '<td><strong>' + app.escapeHtml(item.country) + '</strong></td>',
        '<td>' + item.sku_count + '</td>',
        '<td>' + (item.sales_change > 0 ? "+" : "") + item.sales_change + '</td>',
        '<td><span class="' + revenueClass + '" style="font-weight:800">' + formatMetricValue(item.revenue_change, "currency") + '</span></td>',
        '<td><span class="' + profitClass + '" style="font-weight:800">' + formatMetricValue(item.profit_change, "currency") + '</span></td>',
        '<td>' + app.formatPercent(item.margin_after, 1) + '</td>',
        '<td>' + item.rank_worsen_count + '</td>',
        '<td>' + item.rank_improve_count + '</td>',
        '<td>' + item.out_of_stock_count + '</td>',
        '<td>' + item.profit_down_count + '</td>',
        '<td>' + app.formatPercent(item.rank_worsen_ratio, 1) + '</td>',
        '<td>' + app.formatPercent(item.rank_improve_ratio, 1) + '</td>',
        '<td><button class="metric-toggle" type="button" data-country-metric="' + app.escapeHtml(item.country) + '"><span>' + (isExpanded ? "收起" : "指标") + '</span><b>' + (isExpanded ? "−" : "+") + '</b></button></td>',
        '</tr>'
      ];
      if (isExpanded) {
        rows.push('<tr class="country-detail-row"><td colspan="13">' + renderMetricDetailGrid(item) + '</td></tr>');
      }
      return rows.join("");
    }).join("");
    Array.from(elements.countryTableBody.querySelectorAll("[data-country-metric]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var country = this.dataset.countryMetric || "";
        expandedCountry = expandedCountry === country ? "" : country;
        renderCountrySection();
      });
    });
  }

  // ===== Second Adjustments =====

  function loadSecondAdjustments() {
    return app.apiGet("/api/price-review/second-adjustments" + buildQuery()).then(function (payload) {
      renderSecondAdjustments(payload || {});
    });
  }

  function renderSecondAdjustments(payload) {
    var items = payload.items || [];
    var gapBuckets = payload.gap_buckets || [];
    if (elements.secondAdjustSummary) {
      elements.secondAdjustSummary.textContent = "二次调价 " + (payload.total || 0).toLocaleString("zh-CN") +
        " 个，上次调价日期 " + (payload.date_count || 0) + " 天，平均间隔 " + (payload.avg_gap_days || 0) + " 天";
    }
    renderSecondAdjustDateChart(items);
    renderSecondAdjustGapChart(gapBuckets);
    renderSecondAdjustTable(items);
  }

  function renderSecondAdjustDateChart(items) {
    if (!elements.secondAdjustDateChart) return;
    var chart = echarts.init(elements.secondAdjustDateChart);
    charts.secondAdjustDate = chart;
    if (!items.length) {
      chart.setOption({ xAxis: { data: [] }, series: [{ data: [] }] }, true);
      return;
    }
    var labels = items.map(function (i) { return i.previous_adjust_date; });
    var counts = items.map(function (i) { return i.sku_count; });
    chart.setOption({
      tooltip: { trigger: "axis", confine: true },
      grid: { left: 48, right: 20, top: 24, bottom: 52 },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#5f7086", interval: 0, rotate: labels.length > 8 ? 30 : 0 } },
      yAxis: { type: "value", axisLabel: { color: "#5f7086" }, splitLine: { lineStyle: { color: "#e4ebf5" } } },
      series: [{
        type: "bar",
        data: counts,
        itemStyle: { color: "#1769e0", borderRadius: [6, 6, 0, 0] },
        barMaxWidth: 34,
        label: { show: true, position: "top", color: "#132238" }
      }]
    });
  }

  function renderSecondAdjustGapChart(items) {
    if (!elements.secondAdjustGapChart) return;
    var chart = echarts.init(elements.secondAdjustGapChart);
    charts.secondAdjustGap = chart;
    var labels = items.map(function (i) { return i.label; });
    var counts = items.map(function (i) { return i.sku_count; });
    chart.setOption({
      tooltip: { trigger: "axis", confine: true },
      grid: { left: 48, right: 20, top: 24, bottom: 42 },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#5f7086" } },
      yAxis: { type: "value", axisLabel: { color: "#5f7086" }, splitLine: { lineStyle: { color: "#e4ebf5" } } },
      series: [{
        type: "bar",
        data: counts,
        itemStyle: { color: "#18a17d", borderRadius: [6, 6, 0, 0] },
        barMaxWidth: 42,
        label: { show: true, position: "top", color: "#132238" }
      }]
    });
  }

  function renderSecondAdjustTable(items) {
    if (!elements.secondAdjustGrid) return;
    window.kanbanGrid.makeGrid("secondAdjustGrid", {
      rowData: items || [],
      domLayout: "normal",
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前筛选条件下没有二次调价数据</span>',
      rowHeight: 44,
      columnDefs: [
        { headerName: "上次调价日期", field: "previous_adjust_date", pinned: "left", minWidth: 170, flex: 1.25, cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } },
        { headerName: "二次调价 SKU", field: "sku_count", minWidth: 150, flex: 1, cellClass: "ag-grid-number-cell" },
        { headerName: "平均间隔天数", field: "avg_gap_days", minWidth: 170, flex: 1, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.decimal(params.value, 1); } },
        { headerName: "涉及店铺", field: "store_count", minWidth: 135, flex: 0.85, cellClass: "ag-grid-number-cell" },
        { headerName: "涉及国家", field: "country_count", minWidth: 135, flex: 0.85, cellClass: "ag-grid-number-cell" }
      ]
    });
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
    if (!elements.topListGrid) return;
    window.kanbanGrid.makeGrid("topListGrid", {
      rowData: items,
      domLayout: "normal",
      overlayNoRowsTemplate: '<span class="ag-empty-copy">暂无数据</span>',
      columnDefs: [
        { headerName: "国家", field: "country", pinned: "left", width: 110 },
        { headerName: "店铺", field: "store", width: 128 },
        { headerName: "MSKU", field: "msku", pinned: "left", width: 128, cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } },
        { headerName: "前销量", field: "sales_before", width: 100, cellClass: "ag-grid-number-cell" },
        { headerName: "后销量", field: "sales_after", width: 100, cellClass: "ag-grid-number-cell" },
        { headerName: "销量变化", field: "sales_change", width: 116, cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<span class="' + window.kanbanGrid.toneClass(params.value) + '" style="font-weight:800">' + window.kanbanGrid.signed(params.value, 0) + '</span>'; } },
        { headerName: "前日销", field: "daily_sales_before", width: 105, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.decimal(params.value, 2); } },
        { headerName: "后日销", field: "daily_sales_after", width: 105, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.decimal(params.value, 2); } },
        { headerName: "日销变化", field: "daily_sales_change", width: 116, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.signed(params.value, 2); } },
        { headerName: "毛利润变化", field: "profit_change", width: 130, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return formatMetricValue(params.value, "currency"); } },
        { headerName: "前毛利率", field: "margin_before", width: 112, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value ? window.kanbanGrid.percent(params.value, 1) : "—"; } },
        { headerName: "后毛利率", field: "margin_after", width: 112, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value ? window.kanbanGrid.percent(params.value, 1) : "—"; } },
        { headerName: "排名变化", field: "rank_change", width: 112, cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<span class="' + window.kanbanGrid.toneClass(params.value, true) + '" style="font-weight:800">' + window.kanbanGrid.signed(params.value, 0) + '</span>'; } },
        { headerName: "最后一天排名", field: "rank_after", width: 132, cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value || "—"; } }
      ]
    });
  }


  function riskTagHtml(level) {
    if (!level) return '—';
    var cls = level === "高" ? "priority-p0" : level === "中" ? "priority-p1" : level === "低" ? "priority-p2" : "";
    return '<span class="tag ' + cls + '">' + app.escapeHtml(level) + '</span>';
  }

  function adjustmentTypeTag(type) {
    var label = type || "首次调价";
    var cls = label === "二次调价" ? "priority-p1" : "band-low";
    return '<span class="tag ' + cls + '">' + app.escapeHtml(label) + '</span>';
  }

  function bindSkuColumnFilters() {
    var buttons = document.querySelectorAll("[data-sku-filter-key]");
    buttons.forEach(function (button) {
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
      if (event.target.closest("[data-sku-filter-key]")) return;
      closeColumnFilterPopover();
    });
  }

  function activeColumnFilterValue(key, type) {
    if (type === "number") {
      return {
        min: skuColumnFilters[key + "_min"] || "",
        max: skuColumnFilters[key + "_max"] || "",
      };
    }
    return skuColumnFilters[key] || "";
  }

  function openColumnFilterPopover(button) {
    closeColumnFilterPopover();

    var key = button.dataset.skuFilterKey;
    var type = button.dataset.skuFilterType || "text";
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
    filterState.page = 1;
    closeColumnFilterPopover();
    loadSkuList();
  }

  function clearColumnFilter(key, type) {
    if (type === "number") {
      delete skuColumnFilters[key + "_min"];
      delete skuColumnFilters[key + "_max"];
    } else {
      delete skuColumnFilters[key];
    }
    filterState.page = 1;
    closeColumnFilterPopover();
    loadSkuList();
  }

  function setColumnFilterValue(key, value) {
    if (value === "") {
      delete skuColumnFilters[key];
    } else {
      skuColumnFilters[key] = value;
    }
  }

  function updateSkuColumnFilterButtons() {
    document.querySelectorAll("[data-sku-filter-key]").forEach(function (button) {
      var key = button.dataset.skuFilterKey;
      var type = button.dataset.skuFilterType || "text";
      var isActive = type === "number"
        ? Boolean(skuColumnFilters[key + "_min"] || skuColumnFilters[key + "_max"])
        : Boolean(skuColumnFilters[key]);
      button.classList.toggle("active", isActive);
    });
  }

  // ===== SKU List =====

  function loadSkuList() {
    return app.apiGet("/api/price-review/skus" + buildSkuQuery()).then(function (payload) {
      populateFilters(payload.filters || {});
      renderSkuTable(payload.rows || [], payload.total);
      renderPagination(payload);
      updateSkuColumnFilterButtons();
    });
  }

  function populateFilters(filters) {
    populateSelect(elements.countrySelect, filters.countries || [], filterState.country, "全部国家");
    populateSelect(elements.storeSelect, filters.stores || [], filterState.store, "全部店铺");
    populateSelect(elements.dropRangeSelect, filters.drop_ranges || [], filterState.drop_range, "全部幅度");
    // 暂时移除风险等级筛选（数据不完整）
    // populateSelect(elements.riskLevelSelect, filters.risk_levels || [], filterState.risk_level, "全部风险");
    populateSelect(elements.priceBandSelect, filters.price_bands || [], filterState.price_band, "全部价格");
    populateSelect(elements.adjustmentTypeSelect, filters.adjustment_types || [], filterState.adjustment_type, "全部类型");
  }

  function populateSelect(el, options, currentValue, defaultLabel) {
    if (!el) return;
    var html = '<option value="all">' + defaultLabel + '</option>';
    options.forEach(function (opt) {
      html += '<option value="' + app.escapeHtml(opt) + '"' + (opt === currentValue ? " selected" : "") + '>' + app.escapeHtml(opt) + '</option>';
    });
    el.innerHTML = html;
  }

  function skuColSort(colId) {
    return filterState.sort_field === colId ? filterState.sort_dir : null;
  }

  function handleSkuGridSortChanged(event) {
    var sortedColumn = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
    var nextField = sortedColumn ? sortedColumn.colId : "";
    var nextDir = sortedColumn ? sortedColumn.sort : "";
    if ((filterState.sort_field || "") === nextField && (filterState.sort_dir || "") === nextDir) return;
    filterState.sort_field = nextField;
    filterState.sort_dir = nextDir;
    filterState.page = 1;
    loadSkuList();
  }

  function renderSkuTable(rows, total) {
    if (elements.skuTableCountText) {
      elements.skuTableCountText.textContent = "共 " + total + " 条";
    }
    if (!elements.priceReviewSkuGrid) return;
    window.kanbanGrid.makeGrid("priceReviewSkuGrid", {
      rowData: rows || [],
      domLayout: "normal",
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前筛选条件下无数据</span>',
      columnDefs: [
        { headerName: "国家", field: "country", pinned: "left", width: 110, sort: skuColSort("country") },
        { headerName: "店铺", field: "store", pinned: "left", width: 128, sort: skuColSort("store") },
        { headerName: "MSKU", field: "msku", pinned: "left", width: 128, sort: skuColSort("msku"), cellRenderer: function (params) { return window.kanbanGrid.textCell(params.value, true); } },
        { headerName: "调价类型", field: "adjustment_type", width: 130, sort: skuColSort("adjustment_type"), cellRenderer: function (params) { return adjustmentTypeTag(params.value); } },
        { headerName: "上次调价", field: "previous_adjust_date", width: 120, sort: skuColSort("previous_adjust_date"), valueFormatter: function (params) { return params.value || "—"; } },
        { headerName: "调价前价格", field: "price_before", width: 128, sort: skuColSort("price_before"), cellClass: "ag-grid-number-cell" },
        { headerName: "调价后价格", field: "price_after", width: 128, sort: skuColSort("price_after"), cellClass: "ag-grid-number-cell" },
        { headerName: "调价幅度", field: "drop_ratio", width: 116, sort: skuColSort("drop_ratio"), cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.percent(params.value, 1); } },
        { headerName: "前销量", field: "sales_before", width: 100, sort: skuColSort("sales_before"), cellClass: "ag-grid-number-cell" },
        { headerName: "后销量", field: "sales_after", width: 100, sort: skuColSort("sales_after"), cellClass: "ag-grid-number-cell" },
        { headerName: "销量变化", field: "sales_change", width: 116, sort: skuColSort("sales_change"), cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<span class="' + window.kanbanGrid.toneClass(params.value) + '" style="font-weight:800">' + window.kanbanGrid.signed(params.value, 0) + '</span>'; } },
        { headerName: "前日销", field: "daily_sales_before", width: 105, sort: skuColSort("daily_sales_before"), cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.decimal(params.value, 2); } },
        { headerName: "后日销", field: "daily_sales_after", width: 105, sort: skuColSort("daily_sales_after"), cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return window.kanbanGrid.decimal(params.value, 2); } },
        { headerName: "日销变化", field: "daily_sales_change", width: 116, sort: skuColSort("daily_sales_change"), cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<span class="' + window.kanbanGrid.toneClass(params.value) + '" style="font-weight:800">' + window.kanbanGrid.signed(params.value, 2) + '</span>'; } },
        { headerName: "前毛利率", field: "margin_before", width: 112, sort: skuColSort("margin_before"), cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value ? window.kanbanGrid.percent(params.value, 1) : "—"; } },
        { headerName: "后毛利率", field: "margin_after", width: 112, sort: skuColSort("margin_after"), cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return params.value ? window.kanbanGrid.percent(params.value, 1) : "—"; } },
        { headerName: "毛利率变化", field: "margin_change", width: 128, sort: skuColSort("margin_change"), cellClass: "ag-grid-number-cell", cellRenderer: function (params) { return '<span class="' + window.kanbanGrid.toneClass(params.value) + '" style="font-weight:800">' + window.kanbanGrid.signedPercent(params.value, 1) + '</span>'; } }
      ],
      onSortChanged: handleSkuGridSortChanged
    });
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
