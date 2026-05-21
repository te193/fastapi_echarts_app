(function () {
  "use strict";

  var app = window.kanbanApp;

  var elements = {
    calendarGrid: document.getElementById("calendarGrid"),
    statTotal: document.getElementById("statTotalAdjustments"),
    statActiveDays: document.getElementById("statActiveDays"),
    statAvg: document.getElementById("statAvgAdjustments"),
  };

  function getHeatClass(count) {
    if (count === 0) return "heat-0";
    if (count <= 50) return "heat-1";
    if (count <= 200) return "heat-2";
    if (count <= 400) return "heat-3";
    if (count <= 800) return "heat-4";
    return "heat-5";
  }

  function renderCalendar(items) {
    if (!elements.calendarGrid) return;
    if (!items || !items.length) {
      elements.calendarGrid.innerHTML = '<div class="empty-state">暂无数据</div>';
      return;
    }

    var total = items.reduce(function (sum, item) { return sum + item.count; }, 0);
    var activeDays = items.filter(function (item) { return item.count > 0; }).length;
    var avg = items.length > 0 ? (total / items.length).toFixed(1) : "0";

    if (elements.statTotal) elements.statTotal.textContent = total.toLocaleString("zh-CN");
    if (elements.statActiveDays) elements.statActiveDays.textContent = activeDays + " 天";
    if (elements.statAvg) elements.statAvg.textContent = avg + " 个";

    var html = [];
    items.forEach(function (item) {
      var heatClass = getHeatClass(item.count);
      var todayClass = item.is_today ? " today" : "";
      var weekendClass = item.is_weekend ? " weekend" : "";
      var href = "/price-review?adjust_date=" + encodeURIComponent(item.date);
      var tag = item.clickable ? "a" : "div";
      var hrefAttr = item.clickable ? ' href="' + href + '"' : "";
      var disabledClass = item.clickable ? "" : " disabled";

      html.push(
        '<' + tag + ' class="calendar-card ' + heatClass + todayClass + weekendClass + disabledClass + '"' + hrefAttr + ' title="' + item.date + ' 调价 ' + item.count + ' 个产品">' +
        '  <span class="calendar-date">' + item.display_date + '</span>' +
        '  <span class="calendar-weekday">' + item.weekday + '</span>' +
        '  <span class="calendar-count">' + item.count + '</span>' +
        '  <span class="calendar-label">个产品调价</span>' +
        '</' + tag + '>'
      );
    });

    elements.calendarGrid.innerHTML = html.join("");
  }

  function loadData() {
    app.apiGet("/api/price-adjustments/daily-counts?days=30")
      .then(function (payload) {
        renderCalendar(payload.items || []);
      })
      .catch(function (error) {
        console.error("Failed to load daily adjustment counts:", error);
        if (elements.calendarGrid) {
          elements.calendarGrid.innerHTML = '<div class="empty-state">加载失败，请刷新重试</div>';
        }
      });
  }

  loadData();
})();
