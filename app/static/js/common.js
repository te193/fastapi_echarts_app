(function () {
  var WEEKDAY_LABELS = ["\u65e5", "\u4e00", "\u4e8c", "\u4e09", "\u56db", "\u4e94", "\u516d"];

  function toCurrency(value) {
    return "\u00a5" + Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
  }

  function toCompactCurrency(value) {
    var amount = Number(value || 0);
    var absolute = Math.abs(amount);
    if (absolute >= 100000000) return "\u00a5" + (amount / 100000000).toFixed(2) + "\u4ebf";
    if (absolute >= 10000) return "\u00a5" + (amount / 10000).toFixed(2) + "\u4e07";
    return toCurrency(amount);
  }

  function toPercent(value, digits) {
    var precision = typeof digits === "number" ? digits : 1;
    return (Number(value || 0) * 100).toFixed(precision) + "%";
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setSelectOptions(select, options, allLabel) {
    if (!select) return;
    var html = ['<option value="all">' + escapeHtml(allLabel) + '</option>'];
    options.forEach(function (option) {
      html.push('<option value="' + escapeHtml(option) + '">' + escapeHtml(option) + "</option>");
    });
    select.innerHTML = html.join("");
  }

  function formatDisplayDate(value) {
    return String(value || "").replace(/-/g, "/");
  }

  function renderFilterChips(host, state) {
    if (!host) return;
    var chips = [];
    if (state.start_date || state.end_date) {
      chips.push("\u5468\u671f\uff1a" + formatDisplayDate(state.start_date || "-") + " \u81f3 " + formatDisplayDate(state.end_date || "-"));
    }
    if (state.site !== "all") chips.push("\u7ad9\u70b9\uff1a" + state.site);
    if (state.store !== "all") chips.push("\u5e97\u94fa\uff1a" + state.store);
    if (state.over_limit === "yes") chips.push("\u8d85\u9650\u4ef7\uff1a\u4ec5\u770b\u8d85\u9650\u4ef7");
    if (state.over_limit === "no") chips.push("\u8d85\u9650\u4ef7\uff1a\u4ec5\u770b\u672a\u8d85\u9650\u4ef7");
    if (state.daily_sales_band !== "all") chips.push("\u65e5\u9500\u5206\u5c42\uff1a" + state.daily_sales_band);
    if (state.margin_band !== "all") chips.push("\u6bdb\u5229\u7387\u5206\u5c42\uff1a" + state.margin_band);
    if (state.keyword) chips.push("\u641c\u7d22\uff1a" + state.keyword);
    if (!chips.length) chips.push("\u5468\u671f\uff1a\u9ed8\u8ba4\u7a97\u53e3");
    host.innerHTML = chips.map(function (chip) {
      return '<span class="chip">' + escapeHtml(chip) + "</span>";
    }).join("");
  }

  function readQueryState() {
    var params = new URLSearchParams(window.location.search);
    return {
      start_date: params.get("start_date") || "",
      end_date: params.get("end_date") || "",
      site: params.get("site") || "all",
      store: params.get("store") || "all",
      over_limit: params.get("over_limit") || "all",
      daily_sales_band: params.get("daily_sales_band") || "all",
      margin_band: params.get("margin_band") || "all",
      keyword: params.get("keyword") || "",
      page: Number(params.get("page") || 1),
      source: params.get("source") || ""
    };
  }

  function writeQueryState(state) {
    var params = new URLSearchParams();
    Object.keys(state).forEach(function (key) {
      var value = state[key];
      if (value == null || value === "" || value === "all") return;
      params.set(key, String(value));
    });
    window.history.replaceState({}, "", window.location.pathname + (params.toString() ? ("?" + params.toString()) : ""));
  }

  function returnStateKey() {
    return "kanban:return-state:" + window.location.pathname + window.location.search;
  }

  function saveReturnState(extra) {
    if (!window.sessionStorage) return;
    try {
      var payload = Object.assign({
        scrollY: window.scrollY || window.pageYOffset || 0,
        savedAt: Date.now()
      }, extra || {});
      window.sessionStorage.setItem(returnStateKey(), JSON.stringify(payload));
    } catch (error) {
      // Ignore storage failures; navigation should never be blocked by state capture.
    }
  }

  function restoreReturnState(options) {
    if (!window.sessionStorage) return;
    var settings = Object.assign({ maxAgeMs: 30 * 60 * 1000, retries: 12, delayMs: 80 }, options || {});
    var raw = null;
    try {
      raw = window.sessionStorage.getItem(returnStateKey());
    } catch (error) {
      return;
    }
    if (!raw) return;

    var payload = null;
    try {
      payload = JSON.parse(raw);
    } catch (error) {
      window.sessionStorage.removeItem(returnStateKey());
      return;
    }
    if (!payload || Date.now() - Number(payload.savedAt || 0) > settings.maxAgeMs) {
      window.sessionStorage.removeItem(returnStateKey());
      return;
    }

    var targetY = Math.max(0, Number(payload.scrollY || 0));
    var attempts = 0;
    function tryScroll() {
      attempts += 1;
      var maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      if (maxScroll >= targetY || attempts >= settings.retries) {
        window.scrollTo({ top: Math.min(targetY, maxScroll), left: 0, behavior: "auto" });
        window.sessionStorage.removeItem(returnStateKey());
        return;
      }
      window.setTimeout(tryScroll, settings.delayMs);
    }
    window.setTimeout(tryScroll, settings.delayMs);
  }

  function navigateWithReturnState(url, extra) {
    saveReturnState(extra);
    window.location.href = url;
  }

  function apiGet(path, params) {
    var url = new URL(path, window.location.origin);
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value == null || value === "" || value === "all") return;
      url.searchParams.set(key, value);
    });
    var controller = window.AbortController ? new AbortController() : null;
    var timeoutId = setTimeout(function () {
      if (controller) controller.abort();
    }, 45000);
    return fetch(url.toString(), controller ? { signal: controller.signal } : {}).then(function (response) {
      if (!response.ok) throw new Error("Request failed: " + response.status);
      return response.json();
    }).finally(function () {
      clearTimeout(timeoutId);
    });
  }

  function initSideNavigation() {
    var root = document.querySelector(".nav-v2");
    if (!root) return;

    var groups = Array.from(root.querySelectorAll("[data-nav-group]"));
    var searchInput = root.querySelector(".nav-v2-search input");
    var clearButton = root.querySelector(".nav-v2-search-clear");
    var emptyState = root.querySelector(".nav-v2-empty");

    function syncGroup(group) {
      var toggle = group.querySelector(".nav-v2-group-toggle");
      if (!toggle) return;
      toggle.setAttribute("aria-expanded", group.classList.contains("open") ? "true" : "false");
    }

    function getSearchText(element) {
      return String(element ? element.textContent || "" : "").replace(/\s+/g, "").toLowerCase();
    }

    function resetSearch() {
      root.classList.remove("searching");
      groups.forEach(function (group) {
        group.hidden = false;
        group.classList.toggle("open", group.dataset.defaultOpen === "true");
        Array.from(group.querySelectorAll(".nav-v2-link")).forEach(function (link) {
          link.hidden = false;
        });
        syncGroup(group);
      });
      if (emptyState) emptyState.hidden = true;
    }

    function applySearch() {
      var keyword = searchInput ? searchInput.value.trim().replace(/\s+/g, "").toLowerCase() : "";
      if (clearButton) clearButton.hidden = !keyword;
      if (!keyword) {
        resetSearch();
        return;
      }

      root.classList.add("searching");
      var totalMatches = 0;
      groups.forEach(function (group) {
        var groupText = getSearchText(group.querySelector(".nav-v2-group-toggle"));
        var groupMatched = groupText.indexOf(keyword) >= 0;
        var groupMatches = 0;
        Array.from(group.querySelectorAll(".nav-v2-link")).forEach(function (link) {
          var matched = groupMatched || getSearchText(link).indexOf(keyword) >= 0;
          link.hidden = !matched;
          if (matched) groupMatches += 1;
        });
        group.hidden = groupMatches === 0;
        group.classList.toggle("open", groupMatches > 0);
        totalMatches += groupMatches;
        syncGroup(group);
      });
      if (emptyState) emptyState.hidden = totalMatches > 0;
    }

    groups.forEach(function (group) {
      var toggle = group.querySelector(".nav-v2-group-toggle");
      if (!toggle) return;
      group.dataset.defaultOpen = group.classList.contains("open") ? "true" : "false";

      toggle.addEventListener("click", function () {
        group.classList.toggle("open");
        if (!root.classList.contains("searching")) {
          group.dataset.defaultOpen = group.classList.contains("open") ? "true" : "false";
        }
        syncGroup(group);
      });

      syncGroup(group);
    });

    if (searchInput) {
      searchInput.addEventListener("input", applySearch);
      searchInput.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        searchInput.value = "";
        applySearch();
      });
    }
    if (clearButton && searchInput) {
      clearButton.addEventListener("click", function () {
        searchInput.value = "";
        applySearch();
        searchInput.focus();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", initSideNavigation);

  function addMonths(date, months) {
    return new Date(date.getFullYear(), date.getMonth() + months, 1);
  }

  function addDays(date, days) {
    var next = new Date(date);
    next.setDate(next.getDate() + days);
    return next;
  }

  function monthStart(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function parseDateValue(value) {
    if (!value) return new Date();
    var parsed = new Date(value + "T00:00:00");
    return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  }

  function formatDateInput(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function createDateRangePicker(config) {
    if (!config || !config.startInput || !config.endInput) {
      return { sync: function () {} };
    }

    var startInput = config.startInput;
    var endInput = config.endInput;
    var root = config.root || startInput.closest(".date-range-inputs");
    if (!root) {
      return { sync: function () {} };
    }

    var pickerState = {
      open: false,
      selecting: "start",
      draftStart: "",
      draftEnd: "",
      baseMonth: monthStart(parseDateValue(config.defaultEnd || formatDateInput(new Date())))
    };

    createPanel();
    var panel = root.querySelector(".date-range-panel");

    startInput.addEventListener("click", function (event) {
      event.stopPropagation();
      open("start");
    });

    endInput.addEventListener("click", function (event) {
      event.stopPropagation();
      open("end");
    });

    document.addEventListener("click", function (event) {
      if (!pickerState.open) return;
      if (root.contains(event.target)) return;
      close();
    });

    sync(config.getStart ? config.getStart() : "", config.getEnd ? config.getEnd() : "");

    return {
      close: close,
      open: open,
      sync: sync
    };

    function createPanel() {
      if (root.querySelector(".date-range-panel")) return;
      var nextPanel = document.createElement("div");
      nextPanel.className = "date-range-panel";
      nextPanel.hidden = true;
      nextPanel.innerHTML = [
        '<div class="date-range-panel-head">',
        '  <div class="date-range-panel-copy">',
        '    <strong id="dateRangePanelTitle">\u9009\u62e9\u65e5\u671f\u8303\u56f4</strong>',
        '    <span id="dateRangePanelHint">\u5148\u70b9\u5f00\u59cb\u65e5\u671f\uff0c\u518d\u70b9\u7ed3\u675f\u65e5\u671f</span>',
        "  </div>",
        '  <button class="icon-button date-range-close" type="button" data-date-action="close" aria-label="\u5173\u95ed">\u00d7</button>',
        "</div>",
        '<div class="date-range-quick" aria-label="\u5feb\u901f\u9009\u62e9\u65e5\u671f\u8303\u56f4">',
        '  <span class="date-range-quick-label">\u5feb\u6377\u9009\u62e9</span>',
        '  <button class="date-range-quick-button" type="button" data-date-quick-days="7">7\u5929</button>',
        '  <button class="date-range-quick-button" type="button" data-date-quick-days="14">14\u5929</button>',
        '  <button class="date-range-quick-button" type="button" data-date-quick-days="30">30\u5929</button>',
        '  <button class="date-range-quick-button" type="button" data-date-quick-days="90">90\u5929</button>',
        '  <button class="date-range-quick-button" type="button" data-date-quick-preset="last-month">\u4e0a\u6708</button>',
        "</div>",
        '<div class="date-range-toolbar">',
        '  <button class="icon-button date-nav-button" type="button" data-date-action="prev" aria-label="\u4e0a\u4e00\u4e2a\u6708">\u2039</button>',
        '  <span class="date-range-toolbar-label" id="dateRangeToolbarLabel">\u65e5\u671f\u8303\u56f4</span>',
        '  <button class="icon-button date-nav-button" type="button" data-date-action="next" aria-label="\u4e0b\u4e00\u4e2a\u6708">\u203a</button>',
        "</div>",
        '<div class="date-range-calendar" id="dateRangeCalendar"></div>'
      ].join("");
      root.appendChild(nextPanel);

      nextPanel.addEventListener("click", function (event) {
        event.stopPropagation();
        var action = event.target.closest("[data-date-action]");
        if (action) {
          var type = action.getAttribute("data-date-action");
          if (type === "close") {
            close();
            return;
          }
          if (type === "prev") {
            pickerState.baseMonth = addMonths(pickerState.baseMonth, -1);
            renderPanel();
            return;
          }
          if (type === "next") {
            pickerState.baseMonth = addMonths(pickerState.baseMonth, 1);
            renderPanel();
            return;
          }
        }

        var quickPreset = event.target.closest("[data-date-quick-preset]");
        if (quickPreset && quickPreset.getAttribute("data-date-quick-preset") === "last-month") {
          applyLastMonthRange();
          return;
        }

        var quickRange = event.target.closest("[data-date-quick-days]");
        if (quickRange) {
          applyQuickRange(Number(quickRange.getAttribute("data-date-quick-days")));
          return;
        }

        var dateCell = event.target.closest("[data-date-value]");
        if (!dateCell) return;
        handleDateSelection(dateCell.getAttribute("data-date-value"));
      });
    }

    function getRange() {
      return {
        start: config.getStart ? (config.getStart() || "") : "",
        end: config.getEnd ? (config.getEnd() || "") : ""
      };
    }

    function open(selecting) {
      var range = getRange();
      pickerState.open = true;
      pickerState.selecting = selecting || "start";
      pickerState.draftStart = range.start;
      pickerState.draftEnd = range.end;
      var fallback = config.defaultEnd || formatDateInput(new Date());
      var baseValue = pickerState.selecting === "end"
        ? (range.end || fallback)
        : (range.start || fallback);
      pickerState.baseMonth = monthStart(parseDateValue(baseValue));
      panel.hidden = false;
      renderPanel();
    }

    function close() {
      pickerState.open = false;
      panel.hidden = true;
    }

    function handleDateSelection(dateValue) {
      if (!dateValue) return;
      if (pickerState.selecting === "start") {
        pickerState.draftStart = dateValue;
        pickerState.draftEnd = "";
        pickerState.selecting = "end";
        renderPanel();
        return;
      }

      var startDate = pickerState.draftStart || dateValue;
      var endDate = dateValue;
      if (endDate < startDate) {
        var temp = startDate;
        startDate = endDate;
        endDate = temp;
      }
      if (typeof config.onApply === "function") {
        config.onApply(startDate, endDate);
      }
      close();
    }

    function applyQuickRange(days) {
      if (!days || days < 1) return;
      var range = getRange();
      var endDate = pickerState.draftEnd || range.end || config.defaultEnd || formatDateInput(new Date());
      var startDate = formatDateInput(addDays(parseDateValue(endDate), -(days - 1)));
      pickerState.draftStart = startDate;
      pickerState.draftEnd = endDate;
      pickerState.baseMonth = monthStart(parseDateValue(startDate));
      if (typeof config.onApply === "function") {
        config.onApply(startDate, endDate);
      }
      close();
    }

    function applyLastMonthRange() {
      var referenceDate = parseDateValue(config.defaultEnd || (getRange().end || "") || formatDateInput(new Date()));
      var currentMonthStart = new Date(referenceDate.getFullYear(), referenceDate.getMonth(), 1);
      var endDate = formatDateInput(addDays(currentMonthStart, -1));
      var endValue = parseDateValue(endDate);
      var startDate = formatDateInput(new Date(endValue.getFullYear(), endValue.getMonth(), 1));
      pickerState.draftStart = startDate;
      pickerState.draftEnd = endDate;
      pickerState.baseMonth = monthStart(parseDateValue(startDate));
      if (typeof config.onApply === "function") {
        config.onApply(startDate, endDate);
      }
      close();
    }

    function renderPanel() {
      if (!panel || !pickerState.open) return;

      var title = panel.querySelector("#dateRangePanelTitle");
      var hint = panel.querySelector("#dateRangePanelHint");
      var calendar = panel.querySelector("#dateRangeCalendar");
      var toolbarLabel = panel.querySelector("#dateRangeToolbarLabel");
      if (title) {
        title.textContent = pickerState.selecting === "start"
          ? "\u8bf7\u9009\u62e9\u5f00\u59cb\u65e5\u671f"
          : "\u8bf7\u9009\u62e9\u7ed3\u675f\u65e5\u671f";
      }
      if (hint) {
        hint.textContent = pickerState.selecting === "start"
          ? "\u7b2c\u4e00\u6b65\u5148\u786e\u5b9a\u5f00\u59cb\u65f6\u95f4"
          : "\u7b2c\u4e8c\u6b65\u518d\u786e\u5b9a\u7ed3\u675f\u65f6\u95f4";
      }
      if (toolbarLabel) {
        var range = getRange();
        var startLabel = formatDisplayDate(pickerState.draftStart || range.start || "");
        var endLabel = formatDisplayDate(pickerState.draftEnd || range.end || "");
        toolbarLabel.textContent = (startLabel || endLabel)
          ? (startLabel + " ~ " + endLabel)
          : "\u672a\u9009\u62e9\u65e5\u671f";
      }
      if (!calendar) return;

      var left = pickerState.baseMonth;
      var right = addMonths(left, 1);
      calendar.innerHTML = renderCalendarMonth(left) + renderCalendarMonth(right);
    }

    function renderCalendarMonth(monthDate) {
      var monthTitle = monthDate.getFullYear() + "\u5e74 " + (monthDate.getMonth() + 1) + "\u6708";
      var weekdays = WEEKDAY_LABELS.map(function (label) {
        return '<span class="calendar-weekday">' + label + "</span>";
      }).join("");

      var firstDay = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
      var totalDays = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
      var leading = firstDay.getDay();
      var cells = [];
      var index;
      for (index = 0; index < leading; index += 1) {
        cells.push('<span class="calendar-day-spacer"></span>');
      }
      for (var day = 1; day <= totalDays; day += 1) {
        var current = new Date(monthDate.getFullYear(), monthDate.getMonth(), day);
        var currentValue = formatDateInput(current);
        var classNames = ["calendar-day"];
        if (currentValue === formatDateInput(new Date())) classNames.push("today");
        if (isInDateRange(currentValue)) classNames.push("range");
        if (isBoundaryDate(currentValue)) classNames.push("boundary");
        cells.push('<button type="button" class="' + classNames.join(" ") + '" data-date-value="' + currentValue + '">' + day + "</button>");
      }

      return [
        '<section class="calendar-month">',
        '  <div class="calendar-month-head">' + monthTitle + "</div>",
        '  <div class="calendar-weekdays">' + weekdays + "</div>",
        '  <div class="calendar-days">' + cells.join("") + "</div>",
        "</section>"
      ].join("");
    }

    function isBoundaryDate(dateValue) {
      var range = getRange();
      var draftStart = pickerState.draftStart || range.start;
      var draftEnd = pickerState.draftEnd || range.end;
      return dateValue === draftStart || dateValue === draftEnd;
    }

    function isInDateRange(dateValue) {
      var range = getRange();
      var draftStart = pickerState.draftStart || range.start;
      var draftEnd = pickerState.draftEnd || range.end;
      if (!draftStart || !draftEnd) return false;
      return dateValue >= draftStart && dateValue <= draftEnd;
    }

    function sync(startValue, endValue) {
      startInput.value = formatDisplayDate(startValue || "");
      endInput.value = formatDisplayDate(endValue || "");
      if (!pickerState.open) return;
      pickerState.draftStart = startValue || "";
      pickerState.draftEnd = endValue || "";
      renderPanel();
    }
  }

  function toneFromRatio(ratio) {
    if (ratio >= 1) return "positive";
    if (ratio >= 0.75) return "warning";
    return "negative";
  }

  function goalStatusLabel(ratio) {
    if (ratio >= 1) return "\u5df2\u8fbe\u6807";
    if (ratio >= 0.75) return "\u63a5\u8fd1\u76ee\u6807";
    return "\u4ecd\u9700\u8ffd\u8d76";
  }

  function resolveQuickPeriodRange(period, defaultEnd) {
    var referenceValue = defaultEnd || formatDateInput(new Date());
    var referenceDate = parseDateValue(referenceValue);
    if (period === "last_month") {
      var currentMonthStart = new Date(referenceDate.getFullYear(), referenceDate.getMonth(), 1);
      var endDate = addDays(currentMonthStart, -1);
      var startDate = new Date(endDate.getFullYear(), endDate.getMonth(), 1);
      return {
        start_date: formatDateInput(startDate),
        end_date: formatDateInput(endDate)
      };
    }

    var days = Number(period || 0);
    if (!days || days < 1) return null;
    return {
      start_date: formatDateInput(addDays(referenceDate, -(days - 1))),
      end_date: formatDateInput(referenceDate)
    };
  }

  function getQuickPeriodForRange(startDate, endDate, defaultEnd) {
    var periods = ["7", "14", "30", "90", "last_month"];
    for (var index = 0; index < periods.length; index += 1) {
      var range = resolveQuickPeriodRange(periods[index], defaultEnd);
      if (range && range.start_date === startDate && range.end_date === endDate) {
        return periods[index];
      }
    }
    return "";
  }

  window.kanbanApp = {
    apiGet: apiGet,
    createDateRangePicker: createDateRangePicker,
    escapeHtml: escapeHtml,
    formatCurrency: toCurrency,
    formatCompactCurrency: toCompactCurrency,
    formatDateInput: formatDateInput,
    formatDisplayDate: formatDisplayDate,
    formatPercent: toPercent,
    goalStatusLabel: goalStatusLabel,
    getQuickPeriodForRange: getQuickPeriodForRange,
    navigateWithReturnState: navigateWithReturnState,
    readQueryState: readQueryState,
    renderFilterChips: renderFilterChips,
    restoreReturnState: restoreReturnState,
    resolveQuickPeriodRange: resolveQuickPeriodRange,
    saveReturnState: saveReturnState,
    setSelectOptions: setSelectOptions,
    toneFromRatio: toneFromRatio,
    writeQueryState: writeQueryState
  };
}());
