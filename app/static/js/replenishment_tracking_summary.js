(function () {
  var app = window.kanbanApp;
  var state = { active: false, page: 1, page_size: 20, level_filter: "all", history_level: "all", summary_stage: "all", level_flow_stage: "all", detail_stage: "", product_category: "all" };
  var el = {};
  var gridRenderSeq = 0;
  var summaryRowMap = {};
  var summaryLevelFlowMap = {};
  var DETAIL_NODE_CONFIG = {
    purchase_order: { label: "采购单", tone: "purchase", qtyLabel: "采购数量" },
    receipt_order: { label: "本地收货", tone: "receipt", qtyLabel: "到仓量" },
    qc_order: { label: "质检单", tone: "qc", qtyLabel: "良品数" },
    fba_plan: { label: "FBA计划", tone: "fba", qtyLabel: "计划数" },
    shipment_plan: { label: "FBA出库", tone: "shipment", qtyLabel: "发货数" },
    fba_shipment: { label: "FBA货件单", tone: "shipment", qtyLabel: "发货数" },
    candidate_fba_plan: { label: "候选FBA计划", tone: "candidate", qtyLabel: "计划数" },
    candidate_fba_shipment: { label: "候选FBA货件", tone: "shipment", qtyLabel: "发货数" }
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "dailyViewBtn", "summaryViewBtn", "dailyReplenishmentSection", "trackingSummarySection",
      "trackingSummaryTopCards", "trackingSummaryLevelTabs", "trackingSummaryCards", "trackingSummaryLevelFlow", "trackingSummaryTable", "trackingSummaryPaginationInfo",
      "trackingSummaryPageSizeSelect", "trackingSummaryPrevBtn", "trackingSummaryNextBtn", "summaryBatchSelect",
      "summaryPurchaseStatusSelect", "summaryFbaStatusSelect", "summaryTrackingDetailMask",
      "summaryTrackingDetailDrawer", "summaryTrackingDetailTitle", "summaryTrackingDetailSubtitle",
      "summaryTrackingDetailCloseBtn", "summaryTrackingDetailWrap"
    ].forEach(function (id) {
      el[id] = document.getElementById(id);
    });
    if (!el.summaryViewBtn) return;
    bind();
  }

  function bind() {
    el.dailyViewBtn.addEventListener("click", function () {
      state.active = false;
      el.dailyViewBtn.classList.add("active");
      el.summaryViewBtn.classList.remove("active");
      el.dailyReplenishmentSection.hidden = false;
      el.trackingSummarySection.hidden = true;
    });
    el.summaryViewBtn.addEventListener("click", function () {
      state.active = true;
      state.page = 1;
      el.summaryViewBtn.classList.add("active");
      el.dailyViewBtn.classList.remove("active");
      el.dailyReplenishmentSection.hidden = true;
      el.trackingSummarySection.hidden = false;
      render();
    });
    ["summaryBatchSelect", "summaryPurchaseStatusSelect", "summaryFbaStatusSelect"].forEach(function (id) {
      el[id].addEventListener("change", function () {
        resetLinkedFilter();
        state.page = 1;
        render();
      });
    });
    ["levelSelect", "categoryPeriodSelect", "siteSelect", "storeSelect"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) node.addEventListener("change", function () {
        if (state.active) {
          resetLinkedFilter();
          state.page = 1;
          render();
        }
      });
    });
    var keywordInput = document.getElementById("keywordInput");
    if (keywordInput) keywordInput.addEventListener("input", debounce(function () {
      if (state.active) {
        resetLinkedFilter();
        state.page = 1;
        render();
      }
    }, 300));
    var orderKeywordInput = document.getElementById("orderKeywordInput");
    if (orderKeywordInput) orderKeywordInput.addEventListener("input", debounce(function () {
      if (state.active) {
        resetLinkedFilter();
        state.page = 1;
        render();
      }
    }, 300));
    var clearFiltersBtn = document.getElementById("clearFiltersBtn");
    if (clearFiltersBtn) clearFiltersBtn.addEventListener("click", function () {
      if (!state.active) return;
      resetLinkedFilter();
      var orderKeywordInput = document.getElementById("orderKeywordInput");
      if (orderKeywordInput) orderKeywordInput.value = "";
      setTimeout(function () {
        state.page = 1;
        render();
      }, 0);
    });
    var dateValue = document.getElementById("datePickerValue");
    if (dateValue) new MutationObserver(function () {
      if (state.active) {
        state.page = 1;
        render();
      }
    }).observe(dateValue, { childList: true, characterData: true, subtree: true });
    el.trackingSummaryPrevBtn.addEventListener("click", function () {
      if (state.page > 1) {
        state.page -= 1;
        render();
      }
    });
    el.trackingSummaryNextBtn.addEventListener("click", function () {
      state.page += 1;
      render();
    });
    el.trackingSummaryPageSizeSelect.addEventListener("change", function () {
      state.page_size = Number(el.trackingSummaryPageSizeSelect.value) || 20;
      state.page = 1;
      render();
    });
    el.trackingSummaryLevelFlow.addEventListener("click", function (event) {
      var missingNode = event.target.closest("[data-summary-stage-missing]");
      if (missingNode) {
        event.stopPropagation();
        selectHistoryLevelStage(
          missingNode.dataset.summaryLevel || "all",
          missingNode.dataset.summaryStageMissing || "all",
          true
        );
        return;
      }
      var detailNode = event.target.closest("[data-summary-stage-detail]");
      if (detailNode) {
        event.stopPropagation();
        openStageDetail(detailNode.dataset.summaryLevel || "all", detailNode.dataset.summaryStage || "all");
        return;
      }
      var categoryNode = event.target.closest("[data-summary-category]");
      if (categoryNode) {
        selectHistoryLevel(categoryNode.dataset.summaryLevel || "all", categoryNode.dataset.summaryCategory || "all");
        return;
      }
      var node = event.target.closest("[data-summary-stage-complete]");
      if (!node) return;
      selectHistoryLevelCompletedStage(
        node.dataset.summaryLevel || "all",
        node.dataset.summaryStage || "all"
      );
    });
    el.trackingSummaryCards.addEventListener("click", function (event) {
      var node = event.target.closest("[data-summary-stage]");
      if (!node) return;
      state.level_filter = "all";
      state.history_level = "all";
      state.summary_stage = node.dataset.summaryStage || "all";
      state.level_flow_stage = node.dataset.summaryStage || "all";
      state.detail_stage = "";
      state.product_category = "all";
      state.page = 1;
      render();
    });
    el.trackingSummaryTopCards.addEventListener("click", function (event) {
      var node = event.target.closest("[data-summary-stage]");
      if (!node) return;
      state.level_filter = "all";
      state.history_level = "all";
      state.summary_stage = node.dataset.summaryStage || "all";
      state.level_flow_stage = node.dataset.summaryStage || "all";
      state.detail_stage = "";
      state.product_category = "all";
      state.page = 1;
      render();
    });
    el.trackingSummaryLevelTabs.addEventListener("click", function (event) {
      var node = event.target.closest("[data-summary-tab-level]");
      if (!node) return;
      selectHistoryLevel(node.dataset.summaryTabLevel || "all", "all");
    });
    el.trackingSummaryTable.addEventListener("click", function (event) {
      var clearDetailStage = event.target.closest("[data-clear-detail-stage]");
      if (clearDetailStage) {
        state.detail_stage = "";
        state.page = 1;
        render();
        return;
      }
      var button = event.target.closest("[data-summary-detail]");
      if (!button) return;
      var row = summaryRowMap[button.dataset.rowKey || ""];
      if (row) openDetail(row);
    });
    el.summaryTrackingDetailWrap.addEventListener("click", function (event) {
      var missingButton = event.target.closest("[data-summary-stage-missing-link]");
      if (missingButton) {
        event.preventDefault();
        event.stopPropagation();
        closeDetail();
        selectHistoryLevelStage(
          missingButton.dataset.summaryLevel || "all",
          missingButton.dataset.summaryStageMissing || "",
          true
        );
        return;
      }
      var button = event.target.closest("[data-summary-stage-filter]");
      if (!button) return;
      state.level_filter = "all";
      state.history_level = button.dataset.summaryLevel || "all";
      state.summary_stage = button.dataset.summaryStage || "all";
      state.product_category = "all";
      state.page = 1;
      closeDetail();
      render();
    });
    if (el.summaryTrackingDetailCloseBtn) el.summaryTrackingDetailCloseBtn.addEventListener("click", closeDetail);
    if (el.summaryTrackingDetailMask) el.summaryTrackingDetailMask.addEventListener("click", closeDetail);
  }

  function render(focusTable) {
    if (!state.active) return;
    el.trackingSummaryTable.innerHTML = '<div class="empty-state">加载中...</div>';
    app.apiGet("/api/replenishment-tracking-summary", buildParams())
      .then(function (payload) {
        state.page = payload.page || 1;
        renderCards(payload.summary || {}, payload.scoped_summary || payload.summary || {});
        renderLevelTabs(payload.level_flow || [], payload.summary || {});
        renderLevelFlow(payload.level_flow || [], payload.summary || {});
        renderTable(payload.items || [], payload.total || 0, payload.summary || {});
        renderPagination(payload);
        if (focusTable && el.trackingSummaryTable) {
          el.trackingSummaryTable.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      })
      .catch(function (error) {
        console.error(error);
        el.trackingSummaryTable.innerHTML = '<div class="empty-state">补货链路追踪汇总加载失败：' + escapeHtml(error.message || error) + '</div>';
      });
  }

  function buildParams() {
    return {
      cutoff_date: textOf("datePickerValue"),
      entry_batch_days: valueOf("summaryBatchSelect", "90"),
      level: state.level_filter && state.level_filter !== "all" ? state.level_filter : valueOf("levelSelect", "all"),
      purchase_status: valueOf("summaryPurchaseStatusSelect", "all"),
      fba_status: valueOf("summaryFbaStatusSelect", "all"),
      summary_stage: state.summary_stage || "all",
      level_flow_stage: state.level_flow_stage || "all",
      detail_stage: state.detail_stage || "",
      category_period_days: valueOf("categoryPeriodSelect", "30"),
      history_level: state.history_level || "all",
      product_category: state.product_category || "all",
      site: valueOf("siteSelect", "all"),
      store: valueOf("storeSelect", "all"),
      keyword: valueOf("keywordInput", ""),
      order_keyword: valueOf("orderKeywordInput", ""),
      page: state.page,
      page_size: state.page_size
    };
  }

  function renderCards(summary, scopedSummary) {
    scopedSummary = scopedSummary || summary || {};
    var topCards = [
      ["追踪MSKU", summary.msku_count || 0, "tone-0", "历史进入过补货范围", "all"],
      ["未建采购计划", summary.no_purchase_plan_count || 0, "tone-2", "未匹配到补货后的采购计划", "no_purchase_plan"],
      ["采购未在途", summary.supplier_not_shipped_count || 0, "tone-2", "采购计划已建但未确认在途", "supplier_not_shipped"],
      ["采购在途未到仓", summary.inbound_not_received_count || 0, "tone-2", "当前未同步本地收货链路", "inbound_not_received"],
      ["质检通过未建FBA", summary.no_fba_plan_count || 0, "tone-2", "可推进FBA计划", "no_fba_plan"],
      ["FBA未出库", summary.fba_not_shipped_count || 0, "tone-2", "已建FBA计划但未出库", "fba_not_shipped"],
      ["FBA未接收", summary.fba_not_receiving_count || 0, "tone-2", "FBA在途未接收", "fba_not_receiving"],
      ["FBA已接收", summary.fba_receiving_count || 0, "tone-1", "已开始接收，不等于货件关闭", "fba_receiving_done"],
      ["历史FBA在途", summary.historical_fba_in_transit_count || 0, "tone-2", "在途数量 " + formatNumber(summary.historical_fba_in_transit_qty || 0), "historical_fba_in_transit", "未归入本次采购链路、已实际发货且尚未全部接收或关闭的 FBA 货件。它会影响库存与预计到货，但不计入本次链路完成率。"],
      ["本次链路全部关闭", summary.fba_closed_count || 0, "tone-1", "本次关联货件均已关闭", "fba_closed"],
      ["历史FBA已完成", summary.historical_fba_completed_count || 0, "tone-1", "历史货件完成，不计入本次链路完成率", "historical_fba_completed"]
    ];
    el.trackingSummaryTopCards.innerHTML = topCards.map(function (card) {
      var active = state.summary_stage === card[4] ? " active" : "";
      return '<button type="button" class="alert-stat-card tracking-stat-card summary-stat-card ' + card[2] + active + '" data-summary-stage="' + escapeHtml(card[4]) + '"><span>' + escapeHtml(card[0]) + summaryHelp(card[5]) + '</span><strong>' + formatNumber(card[1]) + '</strong><small>' + escapeHtml(card[3]) + '</small></button>';
    }).join("");

    var sideCards = [
      ["采", "未建采购计划", scopedSummary.no_purchase_plan_count || 0, "采购端未响应", "no_purchase_plan"],
      ["途", "采购未在途", scopedSummary.supplier_not_shipped_count || 0, "采购计划后未确认在途", "supplier_not_shipped"],
      ["仓", "采购未到仓", scopedSummary.inbound_not_received_count || 0, "本地收货链路未确认", "inbound_not_received"],
      ["计", "未建FBA", scopedSummary.no_fba_plan_count || 0, "可推进FBA计划", "no_fba_plan"],
      ["出", "FBA未出库", scopedSummary.fba_not_shipped_count || 0, "已建计划未执行", "fba_not_shipped"],
      ["收", "FBA未接收", scopedSummary.fba_not_receiving_count || 0, "在途未接收", "fba_not_receiving"],
      ["历", "历史FBA在途", scopedSummary.historical_fba_in_transit_count || 0, "已实际发货、尚未全部接收", "historical_fba_in_transit", "未归入本次采购链路的在途货件；会影响库存和预计到货，但不影响本次链路完成率。"],
      ["待", "待归因FBA计划", scopedSummary.unattributed_fba_plan_count || 0, "仅有计划，尚未实际发货", "unattributed_fba_plan", "无法归入本次采购链路，且尚未找到实际 FBA 货件的计划。它不影响库存，也不影响本次链路完成率。"]
    ];
    el.trackingSummaryCards.innerHTML = sideCards.map(function (card) {
      var active = state.summary_stage === card[4] ? " active" : "";
      return [
        '<button class="summary-side-item' + active + '" type="button" data-summary-stage="' + escapeHtml(card[4]) + '">',
        '<span class="summary-side-icon">' + escapeHtml(card[0]) + '</span>',
        '<span class="summary-side-copy"><b>' + escapeHtml(card[1]) + summaryHelp(card[5]) + '</b><small>' + escapeHtml(card[3]) + '</small></span>',
        '<strong>' + formatNumber(card[2]) + '</strong>',
        '</button>'
      ].join("");
    }).join("");
  }

  function summaryHelp(text) {
    if (!text) return "";
    return '<span class="tracking-help-anchor"><i aria-hidden="true">?</i><span class="tracking-help-popover" role="tooltip">' + escapeHtml(text) + '</span></span>';
  }

  function renderLevelTabs(rows, summary) {
    var allActive = state.history_level === "all" && state.product_category === "all" ? "active" : "";
    var allButton = '<button type="button" class="' + allActive + '" data-summary-tab-level="all">全部 · ' + formatNumber(summary.msku_count || 0) + '</button>';
    el.trackingSummaryLevelTabs.innerHTML = [allButton].concat((rows || []).map(function (row) {
      var level = row.level || "未分层";
      var active = state.history_level === level && state.product_category === "all" ? "active" : "";
      return '<button type="button" class="' + active + '" data-summary-tab-level="' + escapeHtml(level) + '">' + escapeHtml(level) + ' · ' + formatNumber(row.msku_count || 0) + '</button>';
    })).join("");
  }

  function renderLevelFlow(rows, summary) {
    if (!rows.length) {
      summaryLevelFlowMap = {};
      el.trackingSummaryLevelFlow.innerHTML = "";
      return;
    }
    summaryLevelFlowMap = {};
    var scopeHint = renderLevelFlowScopeHint(summary || {});
    el.trackingSummaryLevelFlow.innerHTML = scopeHint + rows.map(function (row) {
      var level = row.level || "未分层";
      summaryLevelFlowMap[level] = row;
      var total = Number(row.msku_count || 0);
      var current = Number(row.current_count || 0);
      var sameDay = Number(row.same_day_count || 0);
      var width = total ? Math.round((sameDay / total) * 100) : 0;
      var rowActive = state.history_level === level ? " active" : "";
      var fbaPlanCount = Number(row.fba_plan_count || 0);
      var normalFbaPlanCount = Math.min(fbaPlanCount, Number(row.qc_passed_count || 0));
      var precreatedFbaPlanCount = Math.max(fbaPlanCount - normalFbaPlanCount, 0);
      var nodes = [
        ["建采购", row.purchase_plan_node_count, row.demand_count, "purchase_plan_done", "历史出现"],
        ["采购在途", row.supplier_shipped_count, row.purchase_plan_node_count, "supplier_shipped_done", "已建采购"],
        ["建FBA", row.fba_plan_count, row.qc_passed_count || row.purchase_plan_node_count, "fba_plan_done", "前置节点", row.historical_fba_plan_count, "正常链路 " + formatNumber(normalFbaPlanCount) + " 个 · 提前创建 " + formatNumber(precreatedFbaPlanCount) + " 个"],
        ["FBA出库", row.fba_shipped_count, row.fba_plan_count, "fba_shipped_done", "已建FBA"]
      ];
      return [
        '<article class="replenish-layer-row tracking-layer-row summary-layer-row level-' + levelSort(level) + rowActive + '" data-summary-level="' + escapeHtml(level) + '" data-summary-stage="all">',
        '<span class="layer-mark">' + escapeHtml(levelShort(level)) + '</span>',
        '<span class="layer-name"><b>' + escapeHtml(level) + '</b><small>历史 ' + formatNumber(total) + ' 个 · 当日 ' + formatNumber(sameDay) + ' 个</small>' + renderCategoryMix(row.category_mix || [], total, level) + '</span>',
        '<span class="tracking-stage-flow">',
        nodes.map(function (node) {
          var extra = node[5] ? " · 历史/待确认 " + formatNumber(node[5]) : "";
          return renderSummaryStage(node[0], ratioText(node[1], node[2]), node[4] + " " + formatNumber(node[2] || 0) + " · 未完成 " + formatNumber(Math.max(Number(node[2] || 0) - Number(node[1] || 0), 0)) + extra, ratioTone(node[1], node[2]), level, node[3], node[6], Math.max(Number(node[2] || 0) - Number(node[1] || 0), 0));
        }).join(""),
        '</span>',
        '<span class="layer-progress"><i style="width:' + width + '%"></i></span>',
        '</article>'
      ].join("");
    }).join("");
  }

  function renderTable(items, total, summary) {
    var detailFilter = renderDetailFilterHint(total, summary || {});
    if (!items.length) {
      el.trackingSummaryTable.innerHTML = '<div class="empty-state">当前筛选无补货链路追踪 MSKU。</div>';
      return;
    }
    summaryRowMap = items.reduce(function (map, item, index) {
      item.__rowKey = "summary-row-" + index;
      map[item.__rowKey] = item;
      return map;
    }, {});
    gridRenderSeq += 1;
    var gridId = "summaryAgGrid-" + gridRenderSeq;
    el.trackingSummaryTable.innerHTML = detailFilter + '<div id="' + gridId + '"></div>';
    var columns = [
      { headerName: "当前层级", field: "level", pinned: "left", width: 118, cellRenderer: function (params) { return '<span class="status-pill level-' + levelSort(params.value) + '">' + escapeHtml(params.value || "-") + '</span>'; } },
      { headerName: "MSKU / SKU", field: "msku", pinned: "left", width: 150, cellRenderer: function (params) { return window.kanbanGrid.subCell(params.data.msku || "-", params.data.sku || ""); } },
      { headerName: "店铺", field: "store", width: 120 },
      { headerName: "国家类别", field: "country", width: 112 },
      { headerName: "历史层级", field: "historical_replenishment_levels", width: 220, cellRenderer: function (params) { return splitTags(params.value, levelTone); } },
      { headerName: "销售角色", field: "product_category", width: 112, cellRenderer: function (params) { return tag(params.value, categoryTone(params.value)); } },
      { headerName: "首次进入", field: "first_replenishment_date", width: 116 },
      { headerName: "最近补货", field: "latest_replenishment_date", width: 116 },
      numberColumn("出现天数", "appearance_days", 104),
      { headerName: "标签", field: "replenishment_tags", width: 220, cellRenderer: function (params) { return splitTags(params.value, function () { return "positive"; }); } },
      numberColumn("建议数", "latest_replenishment_qty", 104),
      { headerName: "链路进度", field: "__chain", width: 330, filter: false, sortable: false, cellRenderer: function (params) { return renderChainProgress(params.data || {}); } },
      { headerName: "待推进节点", field: "current_node", width: 132, cellRenderer: function (params) { return renderNodePill(params.value); } },
      { headerName: "断点原因", field: "breakpoint_reason", width: 260, tooltipField: "breakpoint_reason", cellRenderer: function (params) { return renderReasonCell(params.value); } },
      numberColumn("采购计划数", "purchase_plan_qty", 112),
      numberColumn("采购在途", "purchase_inbound_qty", 104),
      numberColumn("到仓数", "local_received_qty", 104),
      numberColumn("质检良品", "qc_good_qty", 104),
      numberColumn("FBA计划数", "fba_plan_qty", 112),
      numberColumn("历史FBA计划", "historical_fba_plan_qty", 120),
      numberColumn("FBA已发", "fba_shipped_qty", 104),
      numberColumn("FBA已收", "fba_received_qty", 104),
      { headerName: "订单号摘要", field: "order_sn_summary", width: 220, tooltipField: "order_sn_summary", cellRenderer: function (params) { return renderOrderSummary(params.value); } },
      { headerName: "采购状态", field: "purchase_status_label", width: 134, cellRenderer: function (params) { return statusPill(params.value, statusTone(params.data.purchase_status)); } },
      numberColumn("本次采购在途", "current_purchase_shipping_qty", 126),
      numberColumn("历史采购在途", "historical_purchase_shipping_qty", 126),
      { headerName: "FBA状态", field: "fba_status_label", width: 144, cellRenderer: function (params) { return statusPill(params.value, statusTone(params.data.fba_status)); } },
      numberColumn("本次FBA在途", "current_fba_inbound_qty", 122),
      numberColumn("历史FBA在途", "historical_fba_inbound_qty", 122),
      { headerName: "预计到货", field: "nearest_fba_eta_text", width: 148, cellRenderer: function (params) { return renderEta(params.data || {}); } },
      { headerName: "最新状态", field: "latest_status", minWidth: 160 },
      { headerName: "操作", field: "__rowKey", pinned: "right", width: 108, filter: false, sortable: false, cellRenderer: function (params) { return '<button class="text-button" type="button" data-summary-detail data-row-key="' + escapeHtml(params.value) + '">查看明细</button>'; } }
    ];
    if (state.history_level && state.history_level !== "all") {
      columns.unshift({ headerName: "命中历史层级", field: "__matchedLevel", pinned: "left", width: 132, filter: false, cellRenderer: function () { return '<span class="status-pill level-' + levelSort(state.history_level) + '">' + escapeHtml(state.history_level) + '</span>'; } });
    }
    window.kanbanGrid.makeGrid(gridId, {
      rowData: items,
      domLayout: "normal",
      rowHeight: 58,
      overlayNoRowsTemplate: '<span class="ag-empty-copy">暂无补货链路追踪数据</span>',
      columnDefs: columns
    });
  }

  function openDetail(row) {
    if (!el.summaryTrackingDetailDrawer || !el.summaryTrackingDetailMask) return;
    el.summaryTrackingDetailMask.hidden = false;
    el.summaryTrackingDetailDrawer.hidden = false;
    el.summaryTrackingDetailDrawer.setAttribute("aria-hidden", "false");
    var cutoffDate = textOf("datePickerValue") || "-";
    el.summaryTrackingDetailTitle.textContent = (row.msku || "-") + " / " + (row.store || "-") + " / " + (row.country || "-");
    el.summaryTrackingDetailSubtitle.textContent = (row.sku || "-") + " · " + (row.level || "-") + " · 截止日期 " + cutoffDate + " · 最近补货 " + (row.latest_replenishment_date || "-") + " · 追踪窗口 30 天";
    el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">加载中...</div>';
    app.apiGet("/api/replenishment-tracking-summary/detail", {
      cutoff_date: cutoffDate,
      site: row.country,
      store: row.store,
      msku: row.msku
    }).then(function (payload) {
      renderDetailOverview(payload.rows || [], row);
    }).catch(function (error) {
      console.error(error);
      el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">明细加载失败。</div>';
    });
  }

  function openStageDetail(level, stage) {
    if (!el.summaryTrackingDetailDrawer || !el.summaryTrackingDetailMask) return;
    var row = summaryLevelFlowMap[level];
    if (!row) return;
    el.summaryTrackingDetailMask.hidden = false;
    el.summaryTrackingDetailDrawer.hidden = false;
    el.summaryTrackingDetailDrawer.setAttribute("aria-hidden", "false");
    el.summaryTrackingDetailTitle.textContent = (level || "全部") + " · 链路节点分布";
    el.summaryTrackingDetailSubtitle.textContent = "展示该分层当前仍在补货范围内的各链路 MSKU 数；点节点里的“查看MSKU”再联动下方列表。";
    el.summaryTrackingDetailTitle.textContent = (level || "全部") + " · 链路转化";
    el.summaryTrackingDetailSubtitle.textContent = "只展示链路转化；点击任一节点后联动下方 MSKU 表格查看明细。";
    renderStageDetailTable(row, stage);
  }

  function closeDetail() {
    if (!el.summaryTrackingDetailDrawer || !el.summaryTrackingDetailMask) return;
    el.summaryTrackingDetailMask.hidden = true;
    el.summaryTrackingDetailDrawer.hidden = true;
    el.summaryTrackingDetailDrawer.setAttribute("aria-hidden", "true");
  }

  function renderDetailOverview(rows, sourceRow) {
    if (!rows.length) {
      el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">暂无采购、FBA 或货件明细。</div>';
      return;
    }
    var batches = groupDetailRows(rows);
    var stats = buildDetailOverviewStats(batches);
    el.summaryTrackingDetailWrap.innerHTML = [
      '<section class="summary-detail-redesign">',
      renderDetailMilestoneStrip(stats),
      '<div class="summary-detail-layout">',
      '<section class="summary-detail-batches">',
      '<div class="summary-detail-section-head"><b>批次链路</b><span>每个采购计划单独成组，按采购、到仓质检、FBA 节点查看。</span></div>',
      batches.map(renderDetailBatchCard).join(""),
      '</section>',
      renderDetailAside(stats, batches),
      '</div>',
      '</section>'
    ].join("");
  }

  function buildDetailOverviewStats(batches) {
    var stats = {
      batchCount: batches.length,
      plannedQty: 0,
      purchaseOrderQty: 0,
      receiptQty: 0,
      fbaPlanQty: 0,
      purchaseOrderCount: 0,
      receiptCount: 0,
      qcCount: 0,
      fbaPlanCount: 0,
      normalFbaCount: 0,
      earlyFbaCount: 0,
      candidateFbaCount: 0,
      shipmentCount: 0,
      fbaReceivingCount: 0,
      fbaClosedCount: 0,
      fbaReceivedQty: 0,
      issueCount: 0,
      latestStage: "purchase_plan"
    };
    batches.forEach(function (batch) {
      stats.plannedQty += Number(batch.purchase_plan_qty || 0);
      stats.purchaseOrderQty += Number(batch.purchase_order_qty || 0);
      stats.receiptQty += Number(batch.receipt_qty || 0);
      stats.fbaPlanQty += Number(batch.fba_plan_qty || 0);
      var allLines = batch.order_summary || [];
      stats.purchaseOrderCount += countDetailLines(allLines, ["purchase_order"]);
      stats.receiptCount += countDetailLines(allLines, ["receipt_order"]);
      stats.qcCount += countDetailLines(allLines, ["qc_order"]);
      stats.fbaPlanCount += countDetailLines(allLines, ["fba_plan"]);
      stats.candidateFbaCount += (batch.historical_fba_summary || []).length;
      if (batch.has_current_fba_plan && batch.has_qc) stats.normalFbaCount += 1;
      else if (batch.has_current_fba_plan) stats.earlyFbaCount += 1;
      stats.shipmentCount += countDetailLines(allLines, ["shipment_plan", "fba_shipment"]);
      stats.fbaReceivingCount += Number(batch.fba_receiving_count || 0);
      stats.fbaClosedCount += Number(batch.fba_closed_count || 0);
      stats.fbaReceivedQty += Number(batch.fba_received_qty || 0);
      if (batch.quantity_match_tone === "warning" || batch.link_type_tone === "warning") stats.issueCount += 1;
      stats.latestStage = laterDetailStage(stats.latestStage, batchLatestStage(batch));
    });
    return stats;
  }

  function countDetailLines(lines, types) {
    return (lines || []).filter(function (line) { return types.indexOf(line.type) >= 0; }).length;
  }

  function laterDetailStage(a, b) {
    return detailStageRank(b) > detailStageRank(a) ? b : a;
  }

  function batchLatestStage(batch) {
    var lines = (batch.order_summary || []).concat(batch.historical_fba_summary || []);
    var latest = batch.purchase_plan_sn && batch.purchase_plan_sn !== "-" ? "purchase_plan" : "none";
    lines.forEach(function (line) {
      latest = laterDetailStage(latest, detailStageOfLine(line));
    });
    if (Number(batch.fba_receiving_count || 0) > 0) latest = laterDetailStage(latest, "fba_receiving");
    if (Number(batch.fba_closed_count || 0) > 0) latest = laterDetailStage(latest, "fba_closed");
    return latest;
  }

  function renderDetailMilestoneStrip(stats) {
    var nodes = [
      { stage: "purchase_plan", label: "采购计划", value: stats.batchCount, sub: "PP 批次" },
      { stage: "purchase_order", label: "采购单", value: stats.purchaseOrderCount, sub: "采购量 " + formatNumber(stats.purchaseOrderQty) },
      { stage: "receipt_order", label: "到本地仓", value: stats.receiptCount, sub: "到仓量 " + formatNumber(stats.receiptQty) },
      { stage: "qc_order", label: "质检", value: stats.qcCount, sub: "质检记录" },
      { stage: "fba_plan", label: "建FBA", value: stats.fbaPlanCount, sub: "计划数 " + formatNumber(stats.fbaPlanQty) },
      { stage: "shipment_plan", label: "FBA出库", value: stats.shipmentCount, sub: "货件/出库" },
      { stage: "fba_receiving", label: "FBA接收", value: stats.fbaReceivingCount, sub: "接收量 " + formatNumber(stats.fbaReceivedQty) },
      { stage: "fba_closed", label: "FBA完成", value: stats.fbaClosedCount, sub: "已关闭货件" }
    ];
    return [
      '<section class="summary-detail-rail-panel">',
      '<div class="summary-detail-section-head"><b>链路总览</b><span>绿色为已出现节点，浅色为暂未确认。</span></div>',
      '<div class="summary-detail-rail">',
      nodes.map(function (node) {
        var done = Number(node.value || 0) > 0;
        return [
          '<article class="summary-detail-rail-node ' + (done ? "done" : "todo") + '">',
          '<span>' + escapeHtml(node.label) + '</span>',
          '<strong>' + formatNumber(node.value || 0) + '</strong>',
          '<small>' + escapeHtml(node.sub || "") + '</small>',
          '</article>'
        ].join("");
      }).join(""),
      '</div>',
      '</section>'
    ].join("");
  }

  function renderDetailFocusPanel(stats, row) {
    return [
      '<section class="summary-detail-focus-grid">',
      renderDetailFocusCard("当前焦点", readableStage(stats.latestStage), row.current_node || "按右侧批次查看卡点", "blue"),
      renderDetailFocusCard("主链路数量", formatNumber(stats.plannedQty), "采购计划数量合计", "green"),
      renderDetailFocusCard("FBA 归因", "正常 " + formatNumber(stats.fbaPlanCount) + " / 候选 " + formatNumber(stats.candidateFbaCount), "提前创建或历史待确认会单独展示", "amber"),
      renderDetailFocusCard("需要复核", formatNumber(stats.issueCount), "数量不一致或归因待确认批次", stats.issueCount ? "red" : "green"),
      '</section>'
    ].join("");
  }

  function renderDetailFocusCard(label, value, sub, tone) {
    return [
      '<article class="summary-detail-focus-card ' + escapeHtml(tone || "blue") + '">',
      '<span>' + escapeHtml(label) + '</span>',
      '<strong>' + escapeHtml(String(value || "-")) + '</strong>',
      '<small>' + escapeHtml(sub || "") + '</small>',
      '</article>'
    ].join("");
  }

  function renderDetailBatchCard(batch, index) {
    var lines = (batch.order_summary || []).slice().sort(function (a, b) {
      return detailStageRank(detailStageOfLine(a)) - detailStageRank(detailStageOfLine(b));
    });
    var candidates = (batch.historical_fba_summary || []).slice().sort(compareDetailLines);
    var purchaseLines = lines.filter(function (line) { return detailStageOfLine(line) === "purchase_order"; });
    var localLines = lines.filter(function (line) {
      var stage = detailStageOfLine(line);
      return stage === "receipt_order" || stage === "qc_order";
    });
    var fbaLines = lines.filter(function (line) {
      var stage = detailStageOfLine(line);
      return stage === "fba_plan" || stage === "shipment_plan";
    });
    var fbaProgressCards = Number(batch.fba_shipment_count || 0) > 0
      ? renderFbaReceivingEvidenceCard(batch) + renderFbaCompletionEvidenceCard(batch)
      : "";
    var statusTone = batch.link_type_tone === "positive" ? "positive" : batch.link_type_tone === "warning" ? "warning" : "neutral";
    var statusText = batch.link_type || readableStage(batchLatestStage(batch));
    return [
      '<article class="summary-detail-batch-card ' + escapeHtml(statusTone) + '">',
      '<header class="summary-detail-batch-head">',
      '<div>',
      '<span>批次 ' + escapeHtml(String.fromCharCode(65 + (index || 0))) + '</span>',
      '<strong>' + escapeHtml(batch.purchase_plan_sn || "-") + ' · 计划 ' + formatNumber(batch.purchase_plan_qty || 0) + '</strong>',
      batch.combined_purchase_match ? '<small class="summary-detail-combined-note">合并采购计划：' + escapeHtml(batch.combined_purchase_qty_text || "") + '</small>' : '',
      '</div>',
      '<div class="summary-detail-batch-badges">',
      statusPill(statusText, statusTone),
      statusPill(batch.quantity_match || "待匹配", batch.quantity_match_tone || "neutral"),
      batch.stuck_days != null ? '<span class="status-pill neutral">卡点 ' + formatNumber(batch.stuck_days) + ' 天</span>' : '',
      '</div>',
      '</header>',
      '<div class="summary-detail-batch-body">',
      '<div class="summary-detail-time-rail">' + renderTimeSummary(batch.time_summary || []) + '</div>',
      '<div class="summary-detail-path-groups">',
      renderDetailPathGroup("采购", [renderPlanEvidenceCard(batch)].concat(purchaseLines.map(renderDetailEvidenceCard)).join(""), "purchase"),
      renderDetailPathGroup("到仓 / 质检", localLines.map(renderDetailEvidenceCard).join(""), "local"),
      renderDetailPathGroup("FBA", fbaLines.map(renderDetailEvidenceCard).join("") + fbaProgressCards, "fba"),
      '</div>',
      candidates.length ? '<div class="summary-detail-candidates"><b>历史 / 待确认 FBA</b><div>' + candidates.map(renderDetailEvidenceCard).join("") + '</div></div>' : '',
      '</div>',
      '</article>'
    ].join("");
  }

  function renderDetailPathGroup(label, content, tone) {
    return [
      '<section class="summary-detail-path-group ' + escapeHtml(tone || "neutral") + '">',
      '<div class="summary-detail-path-label">' + escapeHtml(label) + '</div>',
      '<div class="summary-detail-evidence-strip">',
      content || '<span class="muted">暂无节点</span>',
      '</div>',
      '</section>'
    ].join("");
  }

  function renderPlanEvidenceCard(batch) {
    return renderDetailEvidenceCard({
      type: "purchase_plan",
      order: batch.purchase_plan_sn || "-",
      status: batch.purchase_plan_status || "",
      quantity: batch.purchase_plan_qty || 0,
      quantity_label: "计划数",
      created_at: batch.purchase_plan_time || "",
      logistics: batch.purchase_expect_arrive_time ? "预计到达 " + batch.purchase_expect_arrive_time : ""
    });
  }

  function renderDetailEvidenceCard(line) {
    var stage = detailStageOfLine(line);
    var time = line.created_at ? '<span class="summary-detail-evidence-time">' + escapeHtml(line.created_at) + '</span>' : "";
    var note = line.note ? '<em>' + escapeHtml(line.note) + '</em>' : "";
    var logistics = line.logistics ? '<small>' + escapeHtml(line.logistics) + '</small>' : "";
    var status = line.status ? '<i class="summary-detail-evidence-status ' + escapeHtml(evidenceStatusTone(line.status)) + '">' + escapeHtml(line.status) + '</i>' : "";
    return [
      '<article class="summary-detail-evidence-card stage-' + escapeHtml(stage) + '">',
      '<span>' + escapeHtml(readableStage(stage)) + note + '</span>',
      '<strong>' + escapeHtml(line.order || "-") + '</strong>',
      logistics,
      '<b>' + escapeHtml(readableQtyLabel(line)) + ' ' + formatNumber(line.quantity || 0) + status + '</b>',
      time,
      '</article>'
    ].join("");
  }

  function renderFbaReceivingEvidenceCard(batch) {
    var shippedQty = Number(batch.fba_shipped_qty || 0);
    var receivedQty = Number(batch.fba_received_qty || 0);
    var hasReceiving = Number(batch.fba_receiving_count || 0) > 0;
    var fullyReceived = shippedQty > 0 && receivedQty >= shippedQty;
    var stateText = fullyReceived ? "已收齐" : hasReceiving ? "接收中" : "未接收";
    return renderDetailProgressEvidenceCard(
      "fba_receiving",
      "FBA接收",
      stateText,
      "已接收 " + formatNumber(receivedQty) + " / " + formatNumber(shippedQty),
      fullyReceived ? "positive" : hasReceiving ? "warning" : "neutral"
    );
  }

  function renderFbaCompletionEvidenceCard(batch) {
    var shipmentCount = Number(batch.fba_shipment_count || 0);
    var closedCount = Number(batch.fba_closed_count || 0);
    var allClosed = shipmentCount > 0 && closedCount === shipmentCount;
    var stateText = allClosed ? "已完成" : closedCount > 0 ? "部分完成" : "待完成";
    return renderDetailProgressEvidenceCard(
      "fba_closed",
      "FBA完成",
      stateText,
      "已关闭货件 " + formatNumber(closedCount) + " / " + formatNumber(shipmentCount),
      allClosed ? "positive" : "warning"
    );
  }

  function renderDetailProgressEvidenceCard(stage, label, stateText, metricText, tone) {
    return [
      '<article class="summary-detail-evidence-card summary-detail-progress-card stage-' + escapeHtml(stage) + '">',
      '<span>' + escapeHtml(label) + '</span>',
      '<strong>' + escapeHtml(stateText) + '</strong>',
      '<b>' + escapeHtml(metricText) + '<i class="summary-detail-evidence-status ' + escapeHtml(tone || "neutral") + '">' + escapeHtml(stateText) + '</i></b>',
      '</article>'
    ].join("");
  }

  function evidenceStatusTone(value) {
    var text = String(value || "");
    if (text.indexOf("驳回") >= 0 || text.indexOf("作废") >= 0 || text.indexOf("失败") >= 0) return "danger";
    if (text.indexOf("待") >= 0 || text.indexOf("审核") >= 0 || text.indexOf("处理中") >= 0) return "warning";
    if (text.indexOf("已") >= 0 || text.indexOf("完成") >= 0 || text.indexOf("通过") >= 0) return "positive";
    return "neutral";
  }

  function renderDetailAside(stats, batches) {
    var candidateLines = [];
    batches.forEach(function (batch) {
      (batch.historical_fba_summary || []).forEach(function (line) {
        candidateLines.push({
          batch: batch.purchase_plan_sn || "-",
          line: line
        });
      });
    });
    var rows = [
      ["批次数", stats.batchCount, "按采购计划或独立动作归并"],
      ["采购单", stats.purchaseOrderCount, "采购量 " + formatNumber(stats.purchaseOrderQty)],
      ["到仓", stats.receiptCount, "到仓量 " + formatNumber(stats.receiptQty)],
      ["正常FBA", stats.normalFbaCount, "到仓质检后创建"],
      ["提前FBA", stats.earlyFbaCount, "采购链路未走完已创建"],
      ["候选FBA", stats.candidateFbaCount, "历史或待确认"],
      ["待复核批次", stats.issueCount, "数量或归因异常"]
    ];
    return [
      '<aside class="summary-detail-side">',
      '<div class="summary-detail-section-head"><b>待确认 / 侧栏</b><span>先看归因和数量异常</span></div>',
      rows.map(function (item) {
        return '<article><span>' + escapeHtml(item[0]) + '</span><strong>' + formatNumber(item[1]) + '</strong><small>' + escapeHtml(item[2]) + '</small></article>';
      }).join(""),
      candidateLines.length ? '<div class="summary-detail-side-candidates"><b>候选 FBA</b>' + candidateLines.slice(0, 6).map(function (item) {
        return '<div><span>' + escapeHtml(item.batch) + '</span><strong>' + escapeHtml(item.line.order || "-") + '</strong><small>' + escapeHtml((item.line.note || "待确认") + " · " + readableQtyLabel(item.line) + " " + formatNumber(item.line.quantity || 0)) + '</small></div>';
      }).join("") + (candidateLines.length > 6 ? '<p>还有 ' + formatNumber(candidateLines.length - 6) + ' 条候选，展开批次卡可查看。</p>' : '') + '</div>' : '',
      batches.some(function (batch) { return (batch.historical_fba_summary || []).length; }) ? '<p class="summary-detail-side-note">候选 FBA 不直接并入主链路，避免把历史或重复计划误判成本次履约进度。</p>' : '',
      '</aside>'
    ].join("");
  }

  function detailStageOfLine(line) {
    var type = line && line.type;
    if (type === "purchase_order") return "purchase_order";
    if (type === "receipt_order") return "receipt_order";
    if (type === "qc_order") return "qc_order";
    if (type === "fba_plan" || type === "candidate_fba_plan") return "fba_plan";
    if (type === "shipment_plan" || type === "fba_shipment" || type === "candidate_fba_shipment") return "shipment_plan";
    return "purchase_plan";
  }

  function detailStageRank(stage) {
    return {
      none: 0,
      purchase_plan: 1,
      purchase_order: 2,
      receipt_order: 3,
      qc_order: 4,
      fba_plan: 5,
      shipment_plan: 6,
      fba_receiving: 7,
      fba_closed: 8
    }[stage] || 0;
  }

  function readableStage(stage) {
    return {
      purchase_plan: "采购计划",
      purchase_order: "采购单",
      receipt_order: "到本地仓",
      qc_order: "质检",
      fba_plan: "建FBA",
      shipment_plan: "FBA出库",
      fba_receiving: "FBA接收",
      fba_closed: "FBA完成",
      none: "待确认"
    }[stage] || "待确认";
  }

  function readableQtyLabel(line) {
    var stage = detailStageOfLine(line);
    if (stage === "receipt_order") return "到仓量";
    if (stage === "qc_order") return "良品数";
    if (stage === "fba_plan") return "计划数";
    if (stage === "shipment_plan") return "发货数";
    if (stage === "purchase_plan") return "计划数";
    return "采购数";
  }

  function renderDetailTable(rows) {
    if (!rows.length) {
      el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">暂无采购、FBA 或货件明细。</div>';
      return;
    }
    el.summaryTrackingDetailWrap.innerHTML = '<div id="summaryTrackingDetailAgGrid"></div>';
    window.kanbanGrid.makeGrid("summaryTrackingDetailAgGrid", {
      rowData: groupDetailRows(rows),
      domLayout: "normal",
      columnDefs: [
        { headerName: "节点时间", field: "time_summary", width: 260, autoHeight: true, wrapText: true, cellRenderer: function (params) { return renderTimeSummary(params.value); } },
        { headerName: "采购计划", field: "purchase_plan_sn", pinned: "left", width: 150 },
        { headerName: "链路归因", field: "link_attribution", width: 122, cellRenderer: function (params) { return renderAttribution(params.value); } },
        { headerName: "链路类型", field: "link_type", width: 124, cellRenderer: function (params) { return statusPill(params.value || "-", params.data.link_type_tone || "neutral"); } },
        { headerName: "卡点天数", field: "stuck_days", width: 104, cellRenderer: function (params) { return renderStuckDays(params.value); } },
        { headerName: "数量匹配", field: "quantity_match", width: 132, cellRenderer: function (params) { return statusPill(params.value || "-", params.data.quantity_match_tone || "neutral"); } },
        { headerName: "计划状态", field: "purchase_plan_status", width: 150 },
        numberColumn("计划数", "purchase_plan_qty", 96),
        { headerName: "链路节点明细", field: "order_summary", minWidth: 520, flex: 1, autoHeight: true, wrapText: true, cellRenderer: function (params) { return renderDetailLines(params.value); } },
        { headerName: "候选/重复FBA", field: "historical_fba_summary", minWidth: 260, autoHeight: true, wrapText: true, cellRenderer: function (params) { return renderDetailLines(params.value, "无候选FBA"); } },
        numberColumn("采购数量", "purchase_order_qty", 104),
        numberColumn("到仓量", "receipt_qty", 96),
        { headerName: "采购时间", field: "purchase_plan_time", width: 170 },
        { headerName: "预计到达", field: "purchase_expect_arrive_time", width: 170 }
      ]
    });
  }

  function groupDetailRows(rows) {
    var grouped = {};
    rows.forEach(function (row) {
      var key = row.detail_batch_key || row.purchase_plan_sn || row.order_sn || row.shipment_sn || row.source_type_label || "-";
      if (!grouped[key]) {
        var isCombinedPurchase = Boolean(row.combined_purchase_match);
        grouped[key] = {
          purchase_plan_sn: row.detail_batch_key || row.purchase_plan_sn || "-",
          link_attribution: row.link_attribution || "",
          purchase_plan_status: row.purchase_plan_status || "-",
          purchase_plan_qty: isCombinedPurchase ? 0 : row.purchase_plan_qty || 0,
          purchase_plan_time: row.purchase_plan_time || "",
          purchase_expect_arrive_time: row.purchase_expect_arrive_time || "",
          combined_purchase_match: isCombinedPurchase,
          combined_purchase_qty_text: row.combined_purchase_qty_text || "",
          purchase_order_qty: 0,
          receipt_qty: 0,
          fba_plan_qty: 0,
          fba_shipped_qty: 0,
          fba_received_qty: 0,
          fba_shipment_count: 0,
          fba_receiving_count: 0,
          fba_closed_count: 0,
          has_purchase_order: false,
          has_receipt: false,
          has_qc: false,
          has_fba_plan: false,
          has_current_fba_plan: false,
          time_summary: [],
          seenPlanKeys: {},
          seenOrderKeys: {},
          fba_plan_lines: [],
          order_summary: [],
          historical_fba_summary: []
        };
      }
      if (row.source_type === "purchase_plan") {
        if (grouped[key].combined_purchase_match) {
          var planKey = row.purchase_plan_sn || "-";
          if (!grouped[key].seenPlanKeys[planKey]) {
            grouped[key].seenPlanKeys[planKey] = true;
            grouped[key].purchase_plan_qty += Number(row.purchase_plan_qty || 0);
          }
        } else {
          grouped[key].purchase_plan_qty = row.purchase_plan_qty || grouped[key].purchase_plan_qty;
        }
        grouped[key].purchase_plan_status = row.purchase_plan_status || grouped[key].purchase_plan_status;
        grouped[key].purchase_plan_time = row.purchase_plan_time || grouped[key].purchase_plan_time;
        grouped[key].purchase_expect_arrive_time = row.purchase_expect_arrive_time || grouped[key].purchase_expect_arrive_time;
        return;
      }
      var orderKey = [row.source_type || "", row.order_sn || "", row.logistics_order || "", row.quantity_shipped || 0].join("|");
      if (grouped[key].seenOrderKeys[orderKey]) return;
      grouped[key].seenOrderKeys[orderKey] = true;
      var isReceipt = row.source_type === "receipt_order";
      var isQc = row.source_type === "qc_order";
      var isFbaPlan = row.source_type === "fba_plan";
      var isFbaShipment = row.source_type === "fba_shipment";
      var isHistoricalFba = isHistoricalFbaPlan(row);
      var detailQty = isFbaPlan ? Number(row.shipment_plan_quantity || row.purchase_plan_qty || 0) : isReceipt || isQc ? Number(row.quantity_received || 0) : Number(row.quantity_shipped || 0);
      var receivedQty = isFbaShipment ? Number(row.quantity_received || 0) : 0;
      if (isReceipt) {
        grouped[key].receipt_qty += detailQty;
        grouped[key].has_receipt = true;
      } else if (isQc) {
        grouped[key].has_qc = true;
      } else if (isFbaPlan) {
        grouped[key].has_fba_plan = true;
      } else if (!isQc && !isFbaPlan && !isFbaShipment) {
        grouped[key].purchase_order_qty += detailQty;
        grouped[key].has_purchase_order = true;
      }
      pushTimeSummary(grouped[key].time_summary, row);
      var detailLine = {
        type: row.source_type || "",
        source: row.source_type_label || row.source_type || "明细",
        order: isFbaShipment && row.shipment_sn ? (row.order_sn || "-") + " / " + row.shipment_sn : row.order_sn || row.shipment_sn || "-",
        logistics: row.logistics_order || row.logistics_channel_name || row.method_name || "",
	        status: row.purchase_plan_status || "",
	        quantity: detailQty,
	        shipped_quantity: isFbaShipment ? detailQty : 0,
	        received_quantity: receivedQty,
	        created_at: row.plan_create_time || row.shipment_time || row.purchase_plan_time || "",
	        is_historical_fba: (isFbaPlan || isFbaShipment) && isHistoricalFba,
	        quantity_label: isFbaShipment ? "发货数" : isFbaPlan ? "计划数" : isReceipt ? "到仓量" : isQc ? "良品数" : "采购数量"
	      };
	      if (isFbaPlan) grouped[key].fba_plan_lines.push(detailLine);
	      else if (isFbaShipment && isHistoricalFba) grouped[key].historical_fba_summary.push(Object.assign({}, detailLine, {
	        type: "candidate_fba_shipment",
	        note: "历史/待确认"
	      }));
	      else {
	        if (isFbaShipment) {
	          grouped[key].fba_shipment_count += 1;
	          grouped[key].fba_shipped_qty += detailQty;
	          grouped[key].fba_received_qty += receivedQty;
	          if (isFbaReceivingLine(detailLine)) grouped[key].fba_receiving_count += 1;
	          if (isFbaClosedLine(detailLine)) grouped[key].fba_closed_count += 1;
	        }
	        grouped[key].order_summary.push(detailLine);
	      }
    });
    return Object.keys(grouped).map(function (key) {
      delete grouped[key].seenPlanKeys;
      delete grouped[key].seenOrderKeys;
      finalizeFbaPlanLines(grouped[key]);
      delete grouped[key].fba_plan_lines;
      applyDetailDerivedFields(grouped[key]);
      return grouped[key];
    });
  }

  function isFbaReceivingLine(line) {
    if (Number(line && line.received_quantity || 0) > 0) return true;
    var status = String(line && line.status || "").toUpperCase();
    return status === "RECEIVING" || status === "CLOSED" || status.indexOf("接收") >= 0 || status.indexOf("完成") >= 0 || status.indexOf("关闭") >= 0;
  }

  function isFbaClosedLine(line) {
    var status = String(line && line.status || "").toUpperCase();
    return status === "CLOSED" || status.indexOf("已完成") >= 0 || status.indexOf("已关闭") >= 0;
  }

  function finalizeFbaPlanLines(row) {
    var fbaLines = row.fba_plan_lines || [];
    if (!fbaLines.length) return;
    var planQty = Number(row.purchase_plan_qty || 0);
    var historicalLines = fbaLines.filter(function (line) { return line.is_historical_fba; });
    var currentLines = fbaLines.filter(function (line) { return !line.is_historical_fba; });
    if (!currentLines.length) {
      historicalLines.forEach(function (line) {
        row.historical_fba_summary.push(Object.assign({}, line, {
          type: "candidate_fba_plan",
          note: candidateReason(line, planQty)
        }));
      });
      return;
    }
    var sorted = currentLines.slice().sort(function (a, b) {
      return fbaPlanLineScore(b, planQty) - fbaPlanLineScore(a, planQty);
    });
    var mainLine = sorted[0];
    mainLine.note = mainLine.note || "主链路";
    row.order_summary.push(mainLine);
    row.fba_plan_qty = Number(mainLine.quantity || 0);
    row.has_current_fba_plan = true;
    sorted.slice(1).concat(historicalLines).forEach(function (line) {
      var candidate = Object.assign({}, line, {
        type: "candidate_fba_plan",
        note: candidateReason(line, planQty)
      });
      row.historical_fba_summary.push(candidate);
    });
  }

  function fbaPlanLineScore(line, planQty) {
    var status = String(line.status || "");
    var qty = Number(line.quantity || 0);
    var score = 0;
    if (!line.is_historical_fba) score += 1000;
    if (status.indexOf("已处理") >= 0 || status.indexOf("已创建") >= 0) score += 500;
    if (status.indexOf("待") >= 0) score -= 200;
    if (planQty > 0) score -= Math.abs(qty - planQty);
    if (line.created_at) score -= Math.min(daysSince(line.created_at) || 0, 30) * 0.1;
    return score;
  }

  function candidateReason(line, planQty) {
    var status = String(line.status || "");
    var qty = Number(line.quantity || 0);
    if (planQty > 0 && Math.abs(qty - planQty) > Math.max(planQty * 0.2, 5)) return "数量不匹配";
    if (status.indexOf("待") >= 0) return "待处理候选";
    if (line.is_historical_fba) return "历史/待确认";
    return "重复候选";
  }

  function isHistoricalFbaPlan(row) {
    var attribution = row.link_attribution || "";
    return attribution === "historical" || attribution === "历史链路" || attribution === "历史/待确认";
  }

  function applyDetailDerivedFields(row) {
    var planQty = Number(row.purchase_plan_qty || 0);
    if (row.combined_purchase_match && row.has_current_fba_plan) {
      row.link_type = "合并采购匹配";
      row.link_type_tone = "positive";
    } else if (row.has_current_fba_plan && row.has_qc) {
      row.link_type = "正常链路";
      row.link_type_tone = "positive";
    } else if (row.has_current_fba_plan) {
      row.link_type = "提前建FBA";
      row.link_type_tone = "warning";
    } else if (row.historical_fba_summary && row.historical_fba_summary.length) {
      row.link_type = "历史/待确认FBA";
      row.link_type_tone = "warning";
    } else {
      row.link_type = "采购链路";
      row.link_type_tone = "neutral";
    }

    if (row.fba_plan_qty > 0 && planQty > 0) {
      setQuantityMatch(row, row.fba_plan_qty, planQty, "FBA");
    } else if (row.receipt_qty > 0 && row.purchase_order_qty > 0) {
      setQuantityMatch(row, row.receipt_qty, row.purchase_order_qty, "到仓");
    } else if (row.purchase_order_qty > 0 && planQty > 0) {
      setQuantityMatch(row, row.purchase_order_qty, planQty, "采购");
    } else {
      row.quantity_match = "待匹配";
      row.quantity_match_tone = "neutral";
    }

    row.stuck_days = daysSince(lastDetailTime(row.time_summary));
  }

  function setQuantityMatch(row, actual, expected, label) {
    if (actual === expected) {
      row.quantity_match = label + "匹配";
      row.quantity_match_tone = "positive";
    } else if (actual < expected) {
      row.quantity_match = label + "少 " + formatNumber(expected - actual);
      row.quantity_match_tone = "warning";
    } else {
      row.quantity_match = label + "多 " + formatNumber(actual - expected);
      row.quantity_match_tone = "warning";
    }
  }

  function lastDetailTime(items) {
    if (!items || !items.length) return "";
    var order = { "采购计划": 1, "采购单": 2, "到仓": 3, "质检": 4, "建FBA": 5, "FBA发货": 6 };
    var actualItems = items.filter(function (item) { return order[item.label]; });
    if (!actualItems.length) return "";
    return actualItems.slice().sort(function (a, b) {
      return (order[b.label] || 0) - (order[a.label] || 0);
    })[0].value || "";
  }

  function daysSince(value) {
    if (!value) return null;
    var start = new Date(String(value).replace(/-/g, "/"));
    var cutoff = new Date(String(textOf("datePickerValue") || "").replace(/-/g, "/"));
    if (Number.isNaN(start.getTime()) || Number.isNaN(cutoff.getTime())) return null;
    return Math.max(Math.floor((cutoff - start) / 86400000), 0);
  }

  function renderStuckDays(value) {
    if (value === null || value === undefined) return '<span class="muted">-</span>';
    return '<span class="ag-number-strong">' + formatNumber(value) + ' 天</span>';
  }

  function pushTimeSummary(target, row) {
    var items = [
      ["采购计划", row.purchase_plan_time],
      [row.source_type === "purchase_order" ? "采购单" : "", row.plan_create_time],
      [row.source_type === "receipt_order" ? "到仓" : "", row.shipment_time],
      [row.source_type === "qc_order" ? "质检" : "", row.plan_create_time],
      [row.source_type === "fba_plan" ? "建FBA" : "", row.plan_create_time],
      [row.source_type === "fba_plan" ? "FBA发货" : "", row.shipment_time],
      [row.source_type === "fba_shipment" ? "FBA货件" : "", row.shipment_time || row.plan_create_time],
      ["预计到达", row.expected_arrival_date || row.purchase_expect_arrive_time]
    ];
    items.forEach(function (item) {
      if (!item[0] || !item[1]) return;
      var key = item[0] + "|" + item[1];
      if (target.some(function (existing) { return existing.key === key; })) return;
      target.push({ key: key, label: item[0], value: item[1] });
    });
  }

  function renderTimeSummary(items) {
    if (!items || !items.length) return '<span class="muted">-</span>';
    var order = { "采购计划": 1, "采购单": 2, "到仓": 3, "质检": 4, "建FBA": 5, "FBA发货": 6, "预计到达": 7 };
    return '<span class="detail-time-list">' + items.slice().sort(function (a, b) {
      return (order[a.label] || 99) - (order[b.label] || 99);
    }).map(function (item) {
      return '<span><b>' + escapeHtml(item.label) + '</b><em>' + escapeHtml(item.value) + '</em></span>';
    }).join("") + '</span>';
  }

  function renderAttribution(value) {
    if (value === "current" || value === "本次链路") return statusPill("本次链路", "positive");
    if (value === "historical" || value === "历史链路") return statusPill("历史链路", "warning");
    if (value === "历史/待确认") return statusPill("历史/待确认", "warning");
    if (value === "pending") return statusPill("待确认", "warning");
    return statusPill("-", "neutral");
  }

  function renderDetailLines(lines, emptyText) {
    if (!lines || !lines.length) return '<span class="muted">' + escapeHtml(emptyText || "暂无采购单") + '</span>';
    return lines.slice().sort(compareDetailLines).map(function (line) {
      var config = DETAIL_NODE_CONFIG[line.type] || { label: line.source || "明细", tone: "neutral", qtyLabel: line.quantity_label || "数量" };
      var logistics = line.logistics ? '<span class="detail-node-meta">' + escapeHtml(line.logistics) + '</span>' : "";
      var note = line.note ? '<span class="detail-node-note">' + escapeHtml(line.note) + '</span>' : "";
      return [
        '<div class="detail-node-card ' + escapeHtml(config.tone) + '">',
        '<div class="detail-node-head">',
        '<span>' + escapeHtml(config.label) + note + '</span>',
        '<strong>' + escapeHtml(line.order) + '</strong>',
        '</div>',
        '<div class="detail-node-body">',
        logistics,
        '<em>' + escapeHtml(config.qtyLabel || line.quantity_label || "数量") + ' ' + formatNumber(line.quantity || 0) + '</em>',
        '</div>',
        '</div>'
      ].join("");
    }).join("");
  }

  function compareDetailLines(a, b) {
    var order = {
      purchase_order: 1,
      receipt_order: 2,
      qc_order: 3,
      fba_plan: 4,
      candidate_fba_plan: 4,
      candidate_fba_shipment: 5,
      shipment_plan: 5,
      fba_shipment: 5
    };
    var orderA = order[a.type] || 99;
    var orderB = order[b.type] || 99;
    if (orderA !== orderB) return orderA - orderB;
    return String(a.created_at || "").localeCompare(String(b.created_at || ""));
  }

  function renderOrderSummary(value) {
    var parts = String(value || "").split(/\s*\/\s*|,/).filter(Boolean);
    if (!parts.length) return '<span class="muted">-</span>';
    var shown = parts.slice(0, 2).join(" / ");
    var suffix = parts.length > 2 ? " 等" + parts.length + "个" : "";
    return '<span class="order-summary-cell" title="' + escapeHtml(value) + '">' + escapeHtml(shown + suffix) + '</span>';
  }

  function renderStageDetailTable(row, activeStage) {
    var nodes = chainNodeRows(row);
    if (!nodes.length) {
      el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">当前分层暂无链路节点。</div>';
      return;
    }
    el.summaryTrackingDetailWrap.innerHTML = '<div class="summary-node-grid">' + nodes.map(function (node) {
      var missing = Math.max(Number(node.total || 0) - Number(node.done || 0), 0);
      var active = activeStage === node.stage ? " active" : "";
      var hint = node.hint || (node.baseLabel + " " + formatNumber(node.total || 0) + " · 未完成 " + formatNumber(missing));
      return [
        '<article class="summary-node-card' + active + '">',
        '<span>' + escapeHtml(node.label) + '</span>',
        '<strong>' + ratioText(node.done, node.total) + '</strong>',
        '<small>' + escapeHtml(hint) + '</small>',
        '<button type="button" data-summary-stage-filter data-summary-level="' + escapeHtml(row.level || "all") + '" data-summary-stage="' + escapeHtml(node.stage) + '">查看MSKU</button>',
        '</article>'
      ].join("");
    }).join("") + '</div>';
  }

  function renderStageDetailTable(row, activeStage) {
    var nodes = chainNodeRows(row);
    if (!nodes.length) {
      el.summaryTrackingDetailWrap.innerHTML = '<div class="empty-state compact">当前分层暂无链路节点。</div>';
      return;
    }
    var demand = Number(row.demand_count || row.current_count || row.msku_count || 0);
    var maxCount = Math.max.apply(null, [demand].concat(nodes.map(function (node) {
      return Number(node.done || 0);
    })));
    var biggestMissingNode = nodes.slice().sort(function (a, b) {
      return nodeMissing(b) - nodeMissing(a);
    })[0];
    var diagnostic = biggestMissingNode && nodeMissing(biggestMissingNode) > 0
      ? "最大断点：" + biggestMissingNode.label + " 未完成 " + formatNumber(nodeMissing(biggestMissingNode)) + " 个"
      : "当前链路暂无明显断点";
    el.summaryTrackingDetailWrap.innerHTML = [
      '<section class="summary-conversion-panel">',
      '<div class="summary-conversion-head">',
      '<div><b>链路转化</b><small>' + escapeHtml(diagnostic) + '</small></div>',
      '<span>点击节点筛选下方 MSKU 明细</span>',
      '</div>',
      '<div class="summary-conversion-funnel">',
      renderConversionDemandRow(row, demand, maxCount, activeStage),
      nodes.map(function (node) {
        return renderConversionNodeRow(row, node, activeStage, maxCount);
      }).join(""),
      '</div>',
      '</section>'
    ].join("");
  }

  function renderConversionDemandRow(row, demand, maxCount, activeStage) {
    var active = activeStage === "all" ? " active" : "";
    var width = maxCount ? Math.max(Math.round((Number(demand || 0) / maxCount) * 100), 1) : 0;
    return [
      '<button type="button" class="summary-conversion-row demand' + active + '" data-summary-stage-filter data-summary-level="' + escapeHtml(row.level || "all") + '" data-summary-stage="all">',
      '<span class="conversion-name"><b>需要补货</b><small>历史进入该层级</small></span>',
      '<strong>' + formatNumber(demand || 0) + '</strong>',
      '<span class="conversion-bar"><i class="blue" style="width:' + width + '%"></i></span>',
      '<span class="conversion-meta ok">100%</span>',
      '<em>全部MSKU</em>',
      '</button>'
    ].join("");
  }

  function renderConversionNodeRow(row, node, activeStage, maxCount) {
    var done = Number(node.done || 0);
    var total = Number(node.total || 0);
    var missing = nodeMissing(node);
    var ratio = total > 0 ? done / total : 0;
    var width = maxCount ? Math.max(Math.round((done / maxCount) * 100), done > 0 ? 1 : 0) : 0;
    var active = activeStage === node.stage ? " active" : "";
    var tone = conversionTone(node, ratio, missing);
    var hint = node.hint || (node.baseLabel + " " + formatNumber(total) + " · 未完成 " + formatNumber(missing));
    var isSplitFba = node.stage === "fba_plan_done" && Number(node.precreatedDone || 0) > 0;
    var missingStage = stageMissingFilter(node.stage);
    var barHtml = isSplitFba ? renderFbaSplitBar(node, maxCount) : '<span class="conversion-bar"><i class="' + escapeHtml(tone) + '" style="width:' + width + '%"></i></span>';
    var missingAction = missing > 0 && missingStage ? '<button type="button" class="conversion-missing-link" data-summary-stage-missing-link data-summary-level="' + escapeHtml(row.level || "all") + '" data-summary-stage-missing="' + escapeHtml(missingStage) + '">查看未完成 ' + formatNumber(missing) + '</button>' : '';
    var resultHtml = isSplitFba ? [
      '<span class="conversion-result">',
      '<span class="conversion-breakdown">',
      '<span class="normal">正常 ' + formatNumber(node.normalDone || 0) + '</span>',
      '<span class="early">提前 ' + formatNumber(node.precreatedDone || 0) + '</span>',
      '</span>',
      missingAction,
      '</span>'
    ].join("") : (missingAction || '<em>已完成</em>');
    return [
      '<article class="summary-conversion-row ' + tone + (isSplitFba ? " split-fba" : "") + active + '" role="button" tabindex="0" data-summary-stage-filter data-summary-level="' + escapeHtml(row.level || "all") + '" data-summary-stage="' + escapeHtml(node.stage) + '">',
      '<span class="conversion-name"><b>' + escapeHtml(node.label) + '</b><small>' + escapeHtml(hint) + '</small></span>',
      '<strong>' + formatNumber(done) + '</strong>',
      barHtml,
      '<span class="conversion-meta ' + escapeHtml(tone) + '">' + formatPercent(ratio) + '</span>',
      resultHtml,
      '</article>'
    ].join("");
  }

  function renderFbaSplitBar(node, maxCount) {
    var normal = Number(node.normalDone || 0);
    var precreated = Number(node.precreatedDone || 0);
    var normalWidth = maxCount ? Math.max(Math.round((normal / maxCount) * 100), normal > 0 ? 1 : 0) : 0;
    var precreatedWidth = maxCount ? Math.max(Math.round((precreated / maxCount) * 100), precreated > 0 ? 1 : 0) : 0;
    return [
      '<span class="conversion-bar split" title="正常链路 ' + formatNumber(normal) + '，提前创建 ' + formatNumber(precreated) + '">',
      '<i class="normal-fba" style="width:' + normalWidth + '%"></i>',
      '<i class="early-fba" style="width:' + precreatedWidth + '%"></i>',
      '</span>'
    ].join("");
  }

  function nodeMissing(node) {
    return Math.max(Number(node.total || 0) - Number(node.done || 0), 0);
  }

  function formatPercent(value) {
    if (!Number.isFinite(value)) return "0%";
    return (Math.round(value * 1000) / 10).toFixed(value >= 1 ? 0 : 1).replace(/\.0$/, "") + "%";
  }

  function conversionTone(node, ratio, missing) {
    if (!Number(node.total || 0)) return "neutral";
    if (node.stage === "fba_receiving_done" && missing > 0) return "danger";
    if (missing <= 0 || ratio >= 1) return "ok";
    return "warn";
  }

  function renderPagination(payload) {
    var total = payload.total || 0;
    var page = payload.page || 1;
    var pages = payload.total_pages || 1;
    el.trackingSummaryPageSizeSelect.value = String(payload.page_size || state.page_size || 20);
    el.trackingSummaryPaginationInfo.textContent = "共 " + total + " 条，第 " + page + " / " + pages + " 页";
    el.trackingSummaryPrevBtn.disabled = page <= 1;
    el.trackingSummaryNextBtn.disabled = page >= pages;
  }

  function valueOf(id, fallback) {
    var node = document.getElementById(id);
    return node ? node.value || fallback : fallback;
  }

  function textOf(id) {
    var node = document.getElementById(id);
    return node ? (node.textContent || "").trim() : "";
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString("zh-CN");
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function tag(label, tone) {
    return '<span class="tag ' + escapeHtml(tone || "issue-hold") + '">' + escapeHtml(label || "-") + '</span>';
  }

  function statusPill(label, tone) {
    return '<span class="status-pill ' + escapeHtml(tone || "neutral") + '">' + escapeHtml(label || "-") + '</span>';
  }

  function numberColumn(headerName, field, width) {
    return {
      headerName: headerName,
      field: field,
      width: width,
      type: "numericColumn",
      cellRenderer: function (params) {
        return '<span class="ag-number-strong">' + formatNumber(params.value || 0) + '</span>';
      }
    };
  }

  function renderSummaryStage(label, value, hint, tone, level, stage, title, missingCount) {
    var active = state.history_level === level && (
      (state.summary_stage === stage && !state.detail_stage) ||
      state.detail_stage === stageCompletedDetailFilter(stage)
    ) ? " active" : "";
    var missingStage = stageMissingFilter(stage);
    var footer = Number(missingCount || 0) > 0 && missingStage
      ? '<button class="stage-missing-link" type="button" data-summary-level="' + escapeHtml(level || "all") + '" data-summary-stage-missing="' + escapeHtml(missingStage) + '">查看未完成 ' + formatNumber(missingCount) + '</button>'
      : '<em>' + escapeHtml(hint || "") + '</em>';
    return '<span class="tracking-stage-card ' + escapeHtml(tone || "neutral") + active + '" title="' + escapeHtml(title || hint || "") + '" role="button" tabindex="0" data-summary-stage-complete data-summary-level="' + escapeHtml(level || "all") + '" data-summary-stage="' + escapeHtml(stage || "all") + '"><small>' + escapeHtml(label) + '<button class="stage-detail-link" type="button" data-summary-stage-detail data-summary-level="' + escapeHtml(level || "all") + '" data-summary-stage="' + escapeHtml(stage || "all") + '">明细</button></small><strong>' + escapeHtml(String(value || 0)) + '</strong>' + footer + '</span>';
  }

  function stageMissingFilter(stage) {
    return {
      purchase_plan_done: "no_purchase_plan",
      supplier_shipped_done: "supplier_not_shipped",
      local_received_done: "inbound_not_received",
      fba_plan_done: "fba_plan_not_created",
      fba_shipped_done: "fba_not_shipped",
      fba_receiving_done: "fba_not_receiving"
    }[stage] || "";
  }

  function stageCompletedDetailFilter(stage) {
    return {
      purchase_plan_done: "purchase_plan_completed",
      supplier_shipped_done: "supplier_shipped_completed",
      local_received_done: "local_received_completed",
      qc_passed_done: "qc_passed_completed",
      fba_plan_done: "fba_plan_completed",
      fba_shipped_done: "fba_shipped_completed",
      fba_receiving_done: "fba_receiving_completed"
    }[stage] || "";
  }

  function renderChainProgress(row) {
    var nodes = [
      ["购", "建采购", row.purchase_plan_flag, row.purchase_plan_qty],
      ["途", "采购在途", row.supplier_shipped_flag, row.purchase_inbound_qty],
      ["仓", "到本地仓", row.local_received_flag, row.local_received_qty],
      ["检", "质检通过", row.qc_passed_flag, row.qc_good_qty],
      ["F", "建FBA", row.fba_plan_flag, row.fba_plan_qty],
      ["出", "FBA出库", row.fba_shipped_flag, row.fba_shipped_qty],
      ["收", "FBA接收", row.fba_receiving_flag, row.fba_received_qty],
      ["完", "完成", row.fba_closed_flag, row.fba_received_qty]
    ];
    return '<span class="summary-chain-progress">' + nodes.map(function (node) {
      var qty = Number(node[3] || 0);
      var done = Number(node[2] || 0) ? true : false;
      var hasLaterDone = nodes.slice(nodes.indexOf(node) + 1).some(function (nextNode) {
        return Number(nextNode[2] || 0) > 0;
      });
      var statusClass = done ? "done" : (hasLaterDone ? "gap" : "todo");
      var title = node[1] + "：" + formatNumber(qty);
      if (!done && hasLaterDone) title += "，后续节点已有动作，当前节点未确认";
      return '<span class="summary-chain-step ' + statusClass + '" title="' + escapeHtml(title) + '"><i>' + escapeHtml(node[0]) + '</i><em>' + formatNumber(qty) + '</em></span>';
    }).join("") + '</span>';
  }

  function renderNodePill(value) {
    return '<span class="chain-node-pill">' + escapeHtml(value || "-") + '</span>';
  }

  function renderReasonCell(value) {
    var text = String(value || "-").trim();
    var match = text.match(/^(.*?)[\s\u00a0]*(\d+(?:\.\d+)?)$/);
    var reason = match ? match[1].trim() : text;
    var qty = match ? match[2] : "";
    return [
      '<span class="breakpoint-reason-cell" title="' + escapeHtml(text) + '">',
      '<span>' + escapeHtml(reason || "-") + '</span>',
      qty ? '<b>' + escapeHtml(qty) + '</b>' : '',
      '</span>'
    ].join("");
  }

  function ratioText(value, total) {
    return formatNumber(value || 0) + "/" + formatNumber(total || 0);
  }

  function ratioTone(value, total) {
    if (Number(total || 0) <= 0) return "neutral";
    return Number(value || 0) >= Number(total || 0) ? "ok" : "warn";
  }

  function resetLinkedFilter() {
    state.level_filter = "all";
    state.history_level = "all";
    state.summary_stage = "all";
    state.level_flow_stage = "all";
    state.detail_stage = "";
    state.product_category = "all";
  }

  function selectHistoryLevel(level, productCategory) {
    state.level_filter = "all";
    state.history_level = level || "all";
    state.detail_stage = "";
    state.product_category = productCategory || "all";
    state.page = 1;
    render();
  }

  function selectHistoryLevelStage(level, stage, focusTable) {
    state.level_filter = "all";
    state.history_level = level || "all";
    state.detail_stage = stage || "";
    state.product_category = "all";
    state.page = 1;
    render(Boolean(focusTable));
  }

  function selectHistoryLevelCompletedStage(level, stage) {
    state.level_filter = "all";
    state.history_level = level || "all";
    state.detail_stage = stageCompletedDetailFilter(stage);
    state.product_category = "all";
    state.page = 1;
    render(true);
  }

  function renderLevelFlowScopeHint(summary) {
    if (!state.level_flow_stage || state.level_flow_stage === "all") return "";
    return '<div class="summary-flow-scope-hint"><strong>当前状态筛选：'
      + escapeHtml(stageLabel(state.level_flow_stage)) + ' ' + formatNumber(summary.msku_count || 0)
      + ' 个</strong><span>下方按历史补货层级展示，同一 MSKU 曾进入多个层级时可重复出现。</span></div>';
  }

  function renderDetailFilterHint(total, summary) {
    var hasTopStage = state.summary_stage && state.summary_stage !== "all";
    if (!state.detail_stage && !hasTopStage) return "";
    var parts = [];
    if (hasTopStage) {
      parts.push('<span>当前状态：</span><strong>' + escapeHtml(stageLabel(state.summary_stage))
        + ' ' + formatNumber(summary.msku_count || 0) + ' 个</strong>');
    }
    if (state.detail_stage) {
      parts.push('<span>明细筛选：</span><strong>'
        + escapeHtml(state.history_level === "all" ? "全部分层" : state.history_level)
        + ' · ' + escapeHtml(detailStageLabel(state.detail_stage))
        + '，命中 ' + formatNumber(total || 0) + ' 个</strong>');
    }
    return '<div class="summary-detail-filter-hint">' + parts.join('<i>｜</i>')
      + (state.detail_stage ? '<button type="button" data-clear-detail-stage>清除明细筛选</button>' : '')
      + '</div>';
  }

  function detailStageLabel(stage) {
    return {
      no_purchase_plan: "未建采购计划",
      purchase_plan_completed: "已建采购计划",
      supplier_not_shipped: "采购未在途",
      supplier_shipped_completed: "采购已在途",
      inbound_not_received: "采购在途未到仓",
      local_received_completed: "已到本地仓",
      qc_passed_completed: "已质检通过",
      no_fba_plan: "质检通过未建FBA",
      fba_plan_not_created: "未创建FBA",
      fba_plan_completed: "已创建FBA",
      fba_not_shipped: "FBA未出库",
      fba_shipped_completed: "FBA已出库",
      fba_not_receiving: "FBA未接收",
      fba_receiving_completed: "FBA已接收"
    }[stage] || "指定链路状态";
  }

  function renderCategoryMix(mix, total, level) {
    if (!mix.length) return "";
    return '<span class="summary-category-mix">' + mix.slice().sort(categoryOrder).map(function (item) {
      var active = state.history_level === level && state.product_category === item.category ? " active" : "";
      return '<button class="summary-category-chip ' + escapeHtml(categoryTone(item.category)) + active + '" type="button" data-summary-level="' + escapeHtml(level) + '" data-summary-category="' + escapeHtml(item.category) + '">' + escapeHtml(item.category) + ' <b>' + formatNumber(item.msku_count || 0) + '</b>' + (total ? ' <em>' + Math.round(Number(item.msku_count || 0) * 1000 / total) / 10 + '%</em>' : '') + '</button>';
    }).join("") + '</span>';
  }

  function renderEta(row) {
    if (!row.nearest_fba_eta_text || row.nearest_fba_eta_text === "-") return '<span class="muted">-</span>';
    return statusPill(row.nearest_fba_eta_text, Number(row.nearest_fba_eta_days) < 0 ? "warning" : "neutral");
  }

  function splitTags(value, toneFn) {
    var parts = String(value || "").split(/[、,]/).filter(Boolean);
    if (!parts.length) return "";
    return '<span class="summary-tag-list">' + parts.map(function (part) {
      return tag(part, toneFn(part));
    }).join("") + '</span>';
  }

  function levelTone(value) {
    if (value === "紧急补货") return "negative";
    if (value === "建议补货") return "warning";
    if (value === "计划补货") return "band-low";
    return "issue-hold";
  }

  function levelSort(value) {
    if (value === "紧急补货") return 1;
    if (value === "建议补货") return 2;
    if (value === "计划补货") return 3;
    return 6;
  }

  function levelShort(value) {
    if (value === "紧急补货") return "急";
    if (value === "建议补货") return "建";
    if (value === "计划补货") return "计";
    return "层";
  }

  function categoryTone(value) {
    if (value === "明星产品") return "positive";
    if (value === "潜力产品") return "band-low";
    if (value === "瘦狗产品") return "warning";
    return "negative";
  }

  function categoryOrder(a, b) {
    var order = {"明星产品": 1, "潜力产品": 2, "瘦狗产品": 3, "问题产品": 4};
    return (order[a.category] || 9) - (order[b.category] || 9);
  }

  function statusTone(value) {
    if (value === "none") return "warning";
    if (value === "current" || value === "mixed") return "positive";
    if (value === "historical") return "band-low";
    return "issue-hold";
  }

  function stageLabel(value) {
    var map = {
      no_purchase_plan: "未建采购计划",
      purchase_plan_done: "已建采购计划",
      supplier_not_shipped: "采购未在途",
      supplier_shipped_done: "采购在途",
      inbound_not_received: "采购在途未到仓",
      local_received_done: "已到本地仓",
      qc_pending: "质检未完成",
      qc_passed_done: "质检已通过",
      no_fba_plan: "未建FBA计划",
      fba_plan_done: "已建FBA计划",
      fba_not_shipped: "FBA未出库",
      fba_shipped_done: "FBA已出库",
      fba_not_receiving: "FBA未接收",
      fba_receiving_done: "FBA已接收",
      fba_closed: "FBA已完成"
    };
    return map[value] || "全部链路";
  }

  function chainNodeRows(row) {
    var demand = Number(row.demand_count || row.current_count || 0);
    var purchase = Number(row.purchase_plan_node_count || 0);
    var shipped = Number(row.supplier_shipped_count || 0);
    var local = Number(row.local_received_count || 0);
    var qc = Number(row.qc_passed_count || 0);
    var fbaPlan = Number(row.fba_plan_count || 0);
    var fbaOut = Number(row.fba_shipped_count || 0);
    var fbaReceive = Number(row.fba_receiving_count || 0);
    var fbaBase = qc || purchase;
    var normalFbaPlan = Math.min(fbaPlan, qc);
    var precreatedFbaPlan = Math.max(fbaPlan - qc, 0);
    var fbaPlanHint = precreatedFbaPlan > 0
      ? "正常链路 " + formatNumber(normalFbaPlan) + " · 提前创建 " + formatNumber(precreatedFbaPlan) + " · 未完成 " + formatNumber(Math.max(fbaBase - fbaPlan, 0))
      : "前置节点 " + formatNumber(fbaBase) + " · 未完成 " + formatNumber(Math.max(fbaBase - fbaPlan, 0));
    return [
      { label: "建采购", done: purchase, total: demand, baseLabel: "历史出现", stage: "purchase_plan_done" },
      { label: "采购在途", done: shipped, total: purchase, baseLabel: "已建采购", stage: "supplier_shipped_done" },
      { label: "到本地仓", done: local, total: shipped, baseLabel: "采购在途", stage: "local_received_done" },
      { label: "质检通过", done: qc, total: local, baseLabel: "已到仓", stage: "qc_passed_done" },
      { label: "建FBA", done: fbaPlan, total: fbaBase, baseLabel: "前置节点", hint: fbaPlanHint, stage: "fba_plan_done", normalDone: normalFbaPlan, precreatedDone: precreatedFbaPlan },
      { label: "FBA出库", done: fbaOut, total: fbaPlan, baseLabel: "已建FBA", stage: "fba_shipped_done" },
      { label: "FBA接收", done: fbaReceive, total: fbaOut, baseLabel: "已出库", stage: "fba_receiving_done" },
      { label: "完成", done: row.fba_closed_count || 0, total: fbaReceive, baseLabel: "已接收", stage: "fba_closed" }
    ];
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }
})();
