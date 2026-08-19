(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.priceReviewRoleDetailChart = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  function buildOption(payload, requestedView) {
    var points = (payload && payload.trend) || [];
    var view = requestedView === "rank" ? "rank" : "sales_margin";
    var labels = points.map(function (point) { return point.relative_day; });
    var adjustmentIndex = points.findIndex(function (point) { return point.period === "adjustment"; });
    var beforeEnd = adjustmentIndex > 0 ? labels[adjustmentIndex - 1] : null;
    var afterStart = adjustmentIndex >= 0 && adjustmentIndex < labels.length - 1 ? labels[adjustmentIndex + 1] : null;
    var markAreaData = [];
    if (labels.length && beforeEnd) markAreaData.push([{ name: "调前窗口", xAxis: labels[0], itemStyle: { color: "rgba(46, 119, 216, 0.06)" } }, { xAxis: beforeEnd }]);
    if (afterStart) markAreaData.push([{ name: "调后窗口", xAxis: afterStart, itemStyle: { color: "rgba(31, 166, 132, 0.06)" } }, { xAxis: labels[labels.length - 1] }]);

    var yAxis = view === "rank" ? rankAxes() : salesMarginAxes();
    var series = view === "rank" ? rankSeries(points) : salesMarginSeries(points);
    attachPeriodMarks(series[0], markAreaData);

    return {
      animationDuration: 280,
      color: view === "rank" ? ["#7659e8"] : ["#3f86da", "#f28a24"],
      grid: { left: 50, right: view === "rank" ? 58 : 62, top: 58, bottom: 38 },
      legend: view === "rank"
        ? { show: false }
        : { top: 10, right: 12, data: ["每日销量", "毛利率"], itemWidth: 14, itemHeight: 8, textStyle: { color: "#45607f", fontSize: 11 } },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(20, 42, 69, 0.94)",
        borderWidth: 0,
        textStyle: { color: "#fff" },
        formatter: function (items) {
          var point = points[items[0] ? items[0].dataIndex : 0] || {};
          if (view === "rank") return [point.date || point.relative_day, "小类排名：" + valueText(point.small_rank)].join("<br>");
          var margin = point.margin_rate == null ? "—" : (Number(point.margin_rate) * 100).toFixed(1) + "%";
          return [point.date || point.relative_day, "销量：" + valueText(point.sales_qty), "毛利率：" + margin].join("<br>");
        }
      },
      xAxis: {
        type: "category",
        data: labels,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#c9d8ea" } },
        axisLabel: { color: "#607895", fontSize: 10 }
      },
      yAxis: yAxis,
      series: series
    };
  }

  function salesMarginAxes() {
    return [
      { type: "value", name: "销量", min: 0, nameTextStyle: { color: "#607895" }, splitLine: { lineStyle: { color: "#e6eef7", type: "dashed" } }, axisLabel: { color: "#607895" } },
      { type: "value", name: "毛利率", min: 0, position: "right", nameTextStyle: { color: "#607895" }, splitLine: { show: false }, axisLabel: { color: "#607895", formatter: function (value) { return Math.round(value * 100) + "%"; } } }
    ];
  }

  function rankAxes() {
    return [
      { type: "value", name: "小类排名", min: 0, inverse: true, position: "left", nameTextStyle: { color: "#607895" }, splitLine: { lineStyle: { color: "#e6eef7", type: "dashed" } }, axisLabel: { color: "#607895" } }
    ];
  }

  function salesMarginSeries(points) {
    return [
      {
        name: "每日销量",
        type: "line",
        connectNulls: false,
        showSymbol: false,
        smooth: 0.12,
        data: points.map(function (point) { return point.sales_qty; }),
        lineStyle: { color: "#3f86da", width: 2.2 },
        itemStyle: { color: "#3f86da" },
        emphasis: { focus: "series" }
      },
      {
        name: "毛利率",
        type: "line",
        yAxisIndex: 1,
        connectNulls: true,
        showSymbol: true,
        symbolSize: 5,
        smooth: 0.16,
        data: points.map(function (point) { return point.margin_rate; }),
        lineStyle: { color: "#f28a24", width: 2 },
        itemStyle: { color: "#f28a24" },
        emphasis: { focus: "series" }
      }
    ];
  }

  function rankSeries(points) {
    return [{
      name: "小类排名",
      type: "line",
      connectNulls: true,
      showSymbol: false,
      smooth: 0.14,
      data: points.map(function (point) { return point.small_rank; }),
      lineStyle: { color: "#7659e8", width: 2.2 },
      itemStyle: { color: "#7659e8" },
      emphasis: { focus: "series" }
    }];
  }

  function attachPeriodMarks(series, markAreaData) {
    series.markLine = {
      symbol: "none",
      lineStyle: { color: "#2574df", type: "dashed", width: 1.5 },
      label: { color: "#2574df", formatter: "调价日" },
      data: [{ xAxis: "D", name: "调价日" }]
    };
    series.markArea = { silent: true, label: { color: "#6d819a", fontSize: 10 }, data: markAreaData };
  }

  function valueText(value) {
    return value === null || value === undefined ? "—" : String(value);
  }

  return { buildOption: buildOption };
});
