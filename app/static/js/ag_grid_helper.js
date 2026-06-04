(function () {
  var instances = {};
  var app = window.kanbanApp || {};

  function destroy(id) {
    var api = instances[id];
    if (api && typeof api.destroy === "function") api.destroy();
    delete instances[id];
  }

  function html(value) {
    return app.escapeHtml ? app.escapeHtml(value) : String(value == null ? "" : value);
  }

  function isBlank(value) {
    return value === null || value === undefined || value === "";
  }

  function number(value, digits) {
    if (isBlank(value)) return "-";
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
    });
  }

  function decimal(value, digits) {
    if (isBlank(value)) return "-";
    var precision = typeof digits === "number" ? digits : 2;
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision
    });
  }

  function percent(value, digits) {
    if (isBlank(value)) return "-";
    return (app.formatPercent || function (item, precision) {
      return (Number(item || 0) * 100).toFixed(typeof precision === "number" ? precision : 1) + "%";
    })(value, typeof digits === "number" ? digits : 1);
  }

  function signed(value, digits) {
    if (isBlank(value)) return "-";
    var amount = Number(value || 0);
    var text = decimal(amount, typeof digits === "number" ? digits : 0);
    return (amount > 0 ? "+" : "") + text;
  }

  function signedPercent(value, digits) {
    if (isBlank(value)) return "-";
    var amount = Number(value || 0);
    return (amount > 0 ? "+" : "") + percent(amount, typeof digits === "number" ? digits : 1);
  }

  function compactAmount(value) {
    if (isBlank(value)) return "-";
    var amount = Number(value || 0);
    var abs = Math.abs(amount);
    if (abs >= 100000000) return decimal(amount / 100000000, 2) + "亿";
    if (abs >= 10000) return decimal(amount / 10000, 2) + "万";
    return number(amount, 0);
  }

  function textCell(value, strong) {
    if (strong) return "<strong>" + html(value || "-") + "</strong>";
    return html(value || "-");
  }

  function subCell(main, sub) {
    return "<strong>" + html(main || "-") + '</strong><span class="table-subtext">' + html(sub || "") + "</span>";
  }

  function tag(label, tone) {
    return '<span class="alert-label ' + html(tone || "neutral") + '">' + html(label || "-") + "</span>";
  }

  function action(label, className) {
    return '<button class="text-button ' + html(className || "ag-grid-action") + '" type="button">' + html(label || "查看") + "</button>";
  }

  function toneClass(value, inverse) {
    var numberValue = Number(value || 0);
    if (numberValue === 0) return "neutral";
    var positive = inverse ? numberValue < 0 : numberValue > 0;
    return positive ? "positive" : "negative";
  }

  var localeText = {
    // Filter panel
    page: "页",
    more: "更多",
    to: "到",
    of: "共",
    next: "下一页",
    last: "末页",
    first: "首页",
    previous: "上一页",
    loadingOoo: "加载中...",
    selectAll: "全选",
    searchOoo: "搜索...",
    blanks: "空白",
    noMatches: "无匹配项",
    filterOoo: "筛选...",
    equals: "等于",
    notEqual: "不等于",
    blank: "空白",
    notBlank: "非空白",
    empty: "请选择",
    lessThan: "小于",
    greaterThan: "大于",
    lessThanOrEqual: "小于等于",
    greaterThanOrEqual: "大于等于",
    inRange: "介于",
    inRangeStart: "起始",
    inRangeEnd: "结束",
    contains: "包含",
    notContains: "不包含",
    startsWith: "开头是",
    endsWith: "结尾是",
    dateFormatOoo: "yyyy-mm-dd",
    andCondition: "并且",
    orCondition: "或者",
    applyFilter: "应用",
    resetFilter: "重置",
    clearFilter: "清空",
    cancelFilter: "取消",

    // Menu and columns
    pinColumn: "固定列",
    pinLeft: "固定到左侧",
    pinRight: "固定到右侧",
    noPin: "不固定",
    autosizeThisColumn: "自适应当前列",
    autosizeAllColumns: "自适应全部列",
    resetColumns: "重置列",
    noRowsToShow: "暂无数据",
    copy: "复制",
    copyWithHeaders: "复制含表头",
    paste: "粘贴",
    export: "导出",
    csvExport: "导出 CSV",
    excelExport: "导出 Excel",

    // Sort
    sortAscending: "升序",
    sortDescending: "降序",
    sortUnSort: "取消排序",

    // Column tool panel
    columns: "列",
    filters: "筛选",
    rowGroupColumnsEmptyMessage: "拖拽列到这里进行分组",
    valueColumnsEmptyMessage: "拖拽列到这里进行聚合",
    pivotMode: "透视模式",
    groups: "分组",
    values: "值",
    pivots: "透视",
    toolPanelButton: "工具面板"
  };

  function makeGrid(hostOrId, config) {
    var host = typeof hostOrId === "string" ? document.getElementById(hostOrId) : hostOrId;
    if (!host) return null;
    var id = host.id || ("ag-grid-" + Math.random().toString(36).slice(2));
    host.id = id;
    destroy(id);

    if (!window.agGrid) {
      host.innerHTML = '<div class="empty-state compact">表格组件加载失败，请刷新页面重试。</div>';
      return null;
    }

    host.classList.add("kanban-ag-grid", "ag-theme-quartz");
    var options = Object.assign({
      rowData: [],
      columnDefs: [],
      theme: "legacy",
      domLayout: "autoHeight",
      rowHeight: 48,
      headerHeight: 44,
      animateRows: false,
      suppressCellFocus: true,
      suppressMovableColumns: false,
      enableCellTextSelection: true,
      ensureDomOrder: true,
      localeText: localeText,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">当前筛选条件下暂无数据</span>',
      defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 96,
        wrapHeaderText: true,
        autoHeaderHeight: true
      }
    }, config || {});

    var api = window.agGrid.createGrid
      ? window.agGrid.createGrid(host, options)
      : new window.agGrid.Grid(host, options);
    instances[id] = api && api.destroy ? api : options.api;
    return instances[id];
  }

  window.kanbanGrid = {
    action: action,
    compactAmount: compactAmount,
    decimal: decimal,
    destroy: destroy,
    html: html,
    makeGrid: makeGrid,
    number: number,
    percent: percent,
    signed: signed,
    signedPercent: signedPercent,
    subCell: subCell,
    tag: tag,
    textCell: textCell,
    toneClass: toneClass
  };
}());
