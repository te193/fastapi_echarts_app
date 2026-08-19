(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PriceReviewRoleGrid = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function call(formatters, name, value) {
    return typeof formatters[name] === "function" ? formatters[name](value) : String(value == null ? "—" : value);
  }

  function buildColumnDefs(formatters, gridState) {
    formatters = formatters || {};
    gridState = gridState || {};
    function sort(field) { return gridState.sortField === field ? gridState.sortDir : null; }
    return [
      { headerName: "国家", field: "country", pinned: "left", width: 104, sort: sort("country"), filter: "agTextColumnFilter" },
      {
        headerName: "店铺",
        field: "station_store",
        pinned: "left",
        width: 132,
        sort: sort("station_store"),
        filter: "agTextColumnFilter",
        valueGetter: function (params) { return params.data.station_store || params.data.store || "—"; }
      },
      {
        headerName: "MSKU",
        field: "msku",
        pinned: "left",
        width: 154,
        sort: sort("msku"),
        filter: "agTextColumnFilter",
        cellRenderer: function (params) { return call(formatters, "msku", params.value); }
      },
      { headerName: "调前角色", field: "role_before_label", width: 118, sort: sort("role_before_label"), filter: "agTextColumnFilter", cellRenderer: function (params) { return call(formatters, "role", params.value); } },
      { headerName: "调后角色", field: "role_after_label", width: 118, sort: sort("role_after_label"), filter: "agTextColumnFilter", cellRenderer: function (params) { return call(formatters, "role", params.value); } },
      { headerName: "变化", field: "role_change", width: 96, sort: sort("role_change"), filter: "agTextColumnFilter", cellRenderer: function (params) { return call(formatters, "change", params.value); } },
      { headerName: "调前日销", field: "pre_daily_sales", width: 112, sort: sort("pre_daily_sales"), filter: "agNumberColumnFilter", cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return call(formatters, "number", params.value); } },
      { headerName: "调后日销", field: "post_daily_sales", width: 112, sort: sort("post_daily_sales"), filter: "agNumberColumnFilter", cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return call(formatters, "number", params.value); } },
      { headerName: "调前毛利率", field: "pre_margin_rate", width: 124, sort: sort("pre_margin_rate"), filter: "agNumberColumnFilter", cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return call(formatters, "percent", params.value); } },
      { headerName: "调后毛利率", field: "post_margin_rate", width: 124, sort: sort("post_margin_rate"), filter: "agNumberColumnFilter", cellClass: "ag-grid-number-cell", valueFormatter: function (params) { return call(formatters, "percent", params.value); } },
      { headerName: "调前财务区间", field: "finance_band_before_label", width: 138, sort: sort("finance_band_before_label"), filter: "agTextColumnFilter" },
      { headerName: "调后财务区间", field: "finance_band_after_label", width: 138, sort: sort("finance_band_after_label"), filter: "agTextColumnFilter" },
      { headerName: "财务变化", field: "finance_change", width: 108, sort: sort("finance_change"), filter: "agTextColumnFilter", cellRenderer: function (params) { return call(formatters, "change", params.value); } },
      { headerName: "数据状态", field: "data_status", width: 120, sort: sort("data_status"), filter: "agTextColumnFilter", cellRenderer: function (params) { return call(formatters, "status", params.data); } }
    ];
  }

  function prepareRows(rows) {
    return (rows || []).map(function (row, index) {
      return Object.assign({}, row, { _roleDetailKey: String(index) });
    });
  }

  function buildGridOptions(rows, formatters, handlers) {
    handlers = handlers || {};
    var gridState = handlers.gridState || {};
    var rowData = prepareRows(rows);
    return {
      rowData: rowData,
      columnDefs: buildColumnDefs(formatters, gridState),
      domLayout: "normal",
      rowHeight: 50,
      headerHeight: 48,
      suppressCellFocus: false,
      initialState: { filter: { filterModel: gridState.filterModel || {} } },
      defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true,
        minWidth: 92,
        wrapHeaderText: true,
        autoHeaderHeight: true,
        filterParams: { buttons: ["reset", "apply"], closeOnApply: true }
      },
      getRowId: function (params) { return params.data._roleDetailKey; },
      getRowClass: function (params) {
        var activeKey = typeof handlers.activeKey === "function" ? handlers.activeKey() : "";
        return params.data._roleDetailKey === activeKey ? "is-detail-active" : "";
      },
      onRowClicked: function (params) {
        if (typeof handlers.handleCopy === "function" && handlers.handleCopy(params.event)) return;
        if (typeof handlers.openDetail === "function") handlers.openDetail(params.data._roleDetailKey);
      },
      onCellKeyDown: function (params) {
        if (!params.event || (params.event.key !== "Enter" && params.event.key !== " ")) return;
        if (typeof handlers.isCopyTarget === "function" && handlers.isCopyTarget(params.event)) return;
        params.event.preventDefault();
        if (typeof handlers.openDetail === "function") handlers.openDetail(params.data._roleDetailKey);
      },
      onSortChanged: function (event) {
        var sorted = (event.api.getColumnState() || []).find(function (column) { return column.sort; });
        if (typeof handlers.sortChanged === "function") handlers.sortChanged(sorted ? sorted.colId : "", sorted ? sorted.sort : "");
      },
      onFilterChanged: function (event) {
        if (typeof handlers.filterChanged === "function") handlers.filterChanged(event.api.getFilterModel ? event.api.getFilterModel() : {});
      },
      onFirstDataRendered: function () {
        if (typeof handlers.ready === "function") handlers.ready();
      }
    };
  }

  function buildPaginationModel(payload) {
    payload = payload || {};
    var page = Math.max(1, Number(payload.page || 1));
    var totalPages = Math.max(1, Number(payload.total_pages || 1));
    var total = Math.max(0, Number(payload.total || 0));
    var pageSize = [20, 50, 100].indexOf(Number(payload.page_size)) >= 0 ? Number(payload.page_size) : 20;
    var pages = [];
    for (var item = Math.max(1, page - 2); item <= Math.min(totalPages, page + 2); item += 1) pages.push(item);
    return {
      page: page,
      totalPages: totalPages,
      total: total,
      pageSize: pageSize,
      pageSizes: [20, 50, 100],
      pages: pages,
      info: "共 " + total.toLocaleString("zh-CN") + " 条，第 " + page + " / " + totalPages + " 页"
    };
  }

  return {
    buildColumnDefs: buildColumnDefs,
    buildGridOptions: buildGridOptions,
    buildPaginationModel: buildPaginationModel,
    prepareRows: prepareRows
  };
});
