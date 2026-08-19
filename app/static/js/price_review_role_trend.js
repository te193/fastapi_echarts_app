(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.priceReviewRoleTrend = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function buildOption(payload) {
    var points = (payload && payload.points) || [];
    var marginValues = points.map(function (point) { return point.margin_rate; });
    var marginValueCount = marginValues.filter(function (value) { return value != null; }).length;
    var showMarginSymbols = points.length <= 32 || marginValueCount < points.length / 2;
    var before = points.filter(function (point) { return point.period === "before"; });
    var after = points.filter(function (point) { return point.period === "after"; });
    var markAreas = [];
    if (before.length) {
      markAreas.push([
        { name: "调前窗口", xAxis: before[0].relative_day, itemStyle: { color: "rgba(45, 112, 196, 0.055)" } },
        { xAxis: after.length ? after[0].relative_day : before[before.length - 1].relative_day }
      ]);
    }
    if (after.length) {
      markAreas.push([
        { name: "调后窗口", xAxis: after[0].relative_day, itemStyle: { color: "rgba(27, 160, 126, 0.055)" } },
        { xAxis: after[after.length - 1].relative_day }
      ]);
    }

    return {
      animationDuration: 320,
      color: ["#2d70c4", "#e08a32"],
      aria: {
        enabled: true,
        description: "调价前后每日总销量与订单毛利率趋势。调价日计入调前汇总。"
      },
      grid: { top: 48, right: 62, bottom: 44, left: 58, containLabel: false },
      legend: {
        top: 2,
        right: 0,
        itemWidth: 18,
        itemHeight: 8,
        textStyle: { color: "#526983", fontSize: 11 }
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(20, 43, 69, 0.94)",
        borderWidth: 0,
        padding: [10, 12],
        textStyle: { color: "#fff", fontSize: 12 },
        formatter: function (params) {
          var index = params && params.length ? params[0].dataIndex : 0;
          var point = points[index] || {};
          var periodLabel = point.period === "before" ? "调前窗口" : point.period === "after" ? "调后窗口" : "调价日（不计入汇总）";
          var sales = point.sales_qty == null ? "待观察" : Number(point.sales_qty).toLocaleString("zh-CN");
          var margin = point.margin_rate == null ? "—" : (Number(point.margin_rate) * 100).toFixed(1) + "%";
          return '<strong>' + point.date + ' · ' + point.relative_day + '</strong><br>' +
            '<span style="color:#a9bad0">' + periodLabel + '</span><br>' +
            '销量：' + sales + '<br>毛利率：' + margin;
        }
      },
      dataZoom: [{ type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: "ctrl" }],
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: points.map(function (point) { return point.relative_day; }),
        axisLine: { lineStyle: { color: "#cbd8e6" } },
        axisTick: { show: false },
        axisLabel: { color: "#708398", fontSize: 10, hideOverlap: true, margin: 12 }
      },
      yAxis: [
        {
          type: "value",
          name: "销量",
          nameTextStyle: { color: "#718399", fontSize: 10, padding: [0, 0, 0, -34] },
          min: 0,
          axisLabel: { color: "#718399", fontSize: 10 },
          splitLine: { lineStyle: { color: "#e7edf4", type: "dashed" } }
        },
        {
          type: "value",
          name: "毛利率",
          nameTextStyle: { color: "#718399", fontSize: 10, padding: [0, -34, 0, 0] },
          axisLabel: {
            color: "#718399",
            fontSize: 10,
            formatter: function (value) { return Math.round(value * 100) + "%"; }
          },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          name: "每日销量",
          type: "line",
          yAxisIndex: 0,
          data: points.map(function (point) { return point.sales_qty; }),
          showSymbol: points.length <= 32,
          symbolSize: 6,
          connectNulls: false,
          lineStyle: { width: 2.5 },
          areaStyle: { color: "rgba(45, 112, 196, 0.10)" },
          emphasis: { focus: "series" },
          markLine: {
            silent: true,
            symbol: "none",
            label: { formatter: "调价日", color: "#1769e0", fontWeight: 700 },
            lineStyle: { color: "#1769e0", width: 1.5, type: "dashed" },
            data: [{ xAxis: "D", name: "调价日" }]
          },
          markArea: {
            silent: true,
            label: { color: "#8192a5", fontSize: 10 },
            data: markAreas
          }
        },
        {
          name: "毛利率",
          type: "line",
          yAxisIndex: 1,
          data: marginValues,
          showSymbol: showMarginSymbols,
          symbolSize: 6,
          connectNulls: true,
          lineStyle: { width: 2.2 },
          emphasis: { focus: "series" }
        }
      ]
    };
  }

  return { buildOption: buildOption };
});
