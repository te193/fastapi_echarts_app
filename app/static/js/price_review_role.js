(function () {
  var app = window.kanbanApp;
  var elements = {};
  var loaded = false;
  var meta = null;
  var linkedFilter = null;
  var currentView = "performance";
  var performanceHero = null;
  var rolePerformanceTrendChart = null;
  var roleDetailTrendChart = null;
  var roleDetailTrendView = "sales_margin";
  var roleDetailRows = {};
  var activeRoleDetailKey = "";
  var roleMigrationGridApi = null;
  var roleMigrationGridReady = false;
  var state = {
    pre_days: "30",
    post_days: "3",
    country: "all",
    store: "all",
    role_before: "all",
    role_after: "all",
    role_change: "all",
    finance_change: "all",
    finance_before: "all",
    finance_after: "all",
    data_status: "all",
    keyword: "",
    page: 1,
    page_size: 20,
    sort_field: "",
    sort_dir: "",
    column_filters: {}
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    bindEvents();
    syncFilterSurface(false);
  }

  function cacheElements() {
    [
      "priceReviewPerformanceView", "priceReviewRoleMigrationView", "priceReviewPerformanceFilters",
      "priceReviewRoleFilters", "priceReviewRoleHeader", "priceReviewFilterPanel", "adjustDateInput", "rolePreDaysSelect",
      "rolePostDaysSelect", "rolePreWindowText", "rolePostWindowText", "roleCountrySelect", "roleStoreSelect", "roleBeforeSelect",
      "roleAfterSelect", "roleChangeSelect", "financeChangeSelect", "roleDataStatusSelect",
      "roleKeywordInput", "applyRoleFiltersBtn", "resetRoleFiltersBtn", "roleAdvancedFiltersBtn",
      "roleAdvancedFilters", "roleAdvancedFilterCount", "roleActiveFilterChips", "roleMigrationKpis",
      "roleMigrationMatrix", "roleMigrationInsights", "financeMigrationMatrix",
      "rolePerformanceTrendSummary", "rolePerformanceTrendChart", "rolePerformanceTrendCoverage",
      "roleMigrationCount", "roleMigrationGrid", "rolePaginationInfo", "rolePaginationNumbers",
      "rolePageSizeSelect", "rolePrevPageBtn", "roleNextPageBtn", "roleRuleVersion", "roleWindowMeta",
      "roleCacheStatusMeta", "roleFinanceSnapshotMeta", "roleLinkedFilterBar", "roleLinkedFilterText",
      "clearRoleLinkedFiltersBtn", "pageTitle", "statSkuCount", "statCountryCount",
      "roleDetailDrawerMask", "roleDetailDrawer", "roleDetailTitle", "roleDetailSubtitle",
      "closeRoleDetailDrawerBtn", "roleDetailDrawerContent"
    ].forEach(function (id) { elements[id] = document.getElementById(id); });
  }

  function bindEvents() {
    document.querySelectorAll("[data-price-review-view]").forEach(function (button) {
      button.addEventListener("click", function () { activateView(button.dataset.priceReviewView); });
    });
    if (elements.applyRoleFiltersBtn) elements.applyRoleFiltersBtn.addEventListener("click", applyFilters);
    if (elements.resetRoleFiltersBtn) elements.resetRoleFiltersBtn.addEventListener("click", resetFilters);
    if (elements.roleAdvancedFiltersBtn) {
      elements.roleAdvancedFiltersBtn.addEventListener("click", toggleAdvancedFilters);
    }
    if (elements.roleActiveFilterChips) {
      elements.roleActiveFilterChips.addEventListener("click", function (event) {
        var button = event.target.closest("[data-clear-role-filter]");
        if (!button) return;
        clearFilterKey(button.dataset.clearRoleFilter);
      });
    }
    if (elements.clearRoleLinkedFiltersBtn) {
      elements.clearRoleLinkedFiltersBtn.addEventListener("click", clearLinkedFilters);
    }
    if (elements.roleMigrationKpis) {
      elements.roleMigrationKpis.addEventListener("click", function (event) {
        var roleButton = event.target.closest("[data-role-change]");
        var statusButton = event.target.closest("[data-data-status]");
        if (!roleButton && !statusButton) return;
        state.role_before = "all";
        state.role_after = "all";
        state.finance_before = "all";
        state.finance_after = "all";
        if (roleButton) {
          state.role_change = roleButton.dataset.roleChange;
          state.data_status = "all";
          linkedFilter = { type: "role_change", label: "角色变化：" + roleChangeLabel(state.role_change) };
        } else {
          state.role_change = "all";
          state.data_status = statusButton.dataset.dataStatus;
          linkedFilter = { type: "data_status", label: "数据状态：已成熟" };
        }
        state.page = 1;
        syncInputs();
        renderFilterState();
        loadRoleMigration();
      });
    }
    if (elements.roleMigrationMatrix) {
      elements.roleMigrationMatrix.addEventListener("click", function (event) {
        var cell = event.target.closest("[data-role-before][data-role-after]");
        if (!cell || cell.disabled) return;
        state.role_before = cell.dataset.roleBefore;
        state.role_after = cell.dataset.roleAfter;
        state.role_change = "all";
        linkedFilter = {
          type: "role_path",
          label: "角色路径：" + cell.dataset.beforeLabel + " 至 " + cell.dataset.afterLabel
        };
        state.page = 1;
        syncInputs();
        renderFilterState();
        loadRoleMigration();
      });
    }
    if (elements.financeMigrationMatrix) {
      elements.financeMigrationMatrix.addEventListener("click", function (event) {
        var row = event.target.closest("[data-finance-before][data-finance-after]");
        if (!row) return;
        selectFinancePath(row);
      });
      elements.financeMigrationMatrix.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        var row = event.target.closest("[data-finance-before][data-finance-after]");
        if (!row) return;
        event.preventDefault();
        selectFinancePath(row);
      });
    }
    window.addEventListener("resize", function () {
      if (rolePerformanceTrendChart) rolePerformanceTrendChart.resize();
      if (roleDetailTrendChart) roleDetailTrendChart.resize();
    });
    if (elements.rolePageSizeSelect) {
      elements.rolePageSizeSelect.addEventListener("change", function () {
        state.page_size = Number(this.value || 20);
        state.page = 1;
        loadRoleMigration();
      });
    }
    if (elements.closeRoleDetailDrawerBtn) elements.closeRoleDetailDrawerBtn.addEventListener("click", closeRoleDetail);
    if (elements.roleDetailDrawerMask) elements.roleDetailDrawerMask.addEventListener("click", closeRoleDetail);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeRoleDetail();
    });
  }

  function selectFinancePath(row) {
    state.finance_before = row.dataset.financeBefore;
    state.finance_after = row.dataset.financeAfter;
    state.finance_change = "all";
    linkedFilter = {
      type: "finance_path",
      label: "财务路径：" + row.dataset.beforeLabel + " 至 " + row.dataset.afterLabel
    };
    state.page = 1;
    renderFilterState();
    loadRoleMigration();
  }

  function activateView(view) {
    var roleActive = view === "role-migration";
    if (roleActive && currentView !== "role-migration") {
      performanceHero = {
        title: elements.pageTitle.textContent,
        skuCount: elements.statSkuCount.textContent,
        countryCount: elements.statCountryCount.textContent
      };
    }
    elements.priceReviewPerformanceView.hidden = roleActive;
    elements.priceReviewRoleMigrationView.hidden = !roleActive;
    syncFilterSurface(roleActive);
    document.querySelectorAll("[data-price-review-view]").forEach(function (button) {
      var active = button.dataset.priceReviewView === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (!roleActive && performanceHero) {
      elements.pageTitle.textContent = performanceHero.title;
      elements.statSkuCount.textContent = performanceHero.skuCount;
      elements.statCountryCount.textContent = performanceHero.countryCount;
    }
    currentView = view;
    if (roleActive && !loaded) loadRoleMigration();
    if (roleActive && loaded) loadRoleMigration();
  }

  function syncFilterSurface(roleActive) {
    elements.priceReviewPerformanceFilters.hidden = roleActive;
    elements.priceReviewRoleFilters.hidden = !roleActive;
    elements.priceReviewRoleHeader.hidden = !roleActive;
    elements.priceReviewFilterPanel.classList.toggle("is-role-mode", roleActive);
  }

  function toggleAdvancedFilters() {
    var willOpen = elements.roleAdvancedFilters.hidden;
    elements.roleAdvancedFilters.hidden = !willOpen;
    elements.roleAdvancedFiltersBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
    elements.roleAdvancedFiltersBtn.classList.toggle("is-active", willOpen);
  }

  function currentAdjustDate() {
    return elements.adjustDateInput ? elements.adjustDateInput.value : "";
  }

  function readInputs() {
    state.pre_days = elements.rolePreDaysSelect.value;
    state.post_days = elements.rolePostDaysSelect.value;
    state.country = elements.roleCountrySelect.value;
    state.store = elements.roleStoreSelect.value;
    state.role_before = elements.roleBeforeSelect.value;
    state.role_after = elements.roleAfterSelect.value;
    state.role_change = elements.roleChangeSelect.value;
    state.finance_change = elements.financeChangeSelect.value;
    state.data_status = elements.roleDataStatusSelect.value;
    state.keyword = elements.roleKeywordInput.value.trim();
  }

  function syncInputs() {
    elements.rolePreDaysSelect.value = state.pre_days;
    elements.rolePostDaysSelect.value = state.post_days;
    elements.roleCountrySelect.value = state.country;
    elements.roleStoreSelect.value = state.store;
    elements.roleBeforeSelect.value = state.role_before;
    elements.roleAfterSelect.value = state.role_after;
    elements.roleChangeSelect.value = state.role_change;
    elements.financeChangeSelect.value = state.finance_change;
    elements.roleDataStatusSelect.value = state.data_status;
    elements.roleKeywordInput.value = state.keyword;
  }

  function applyFilters() {
    readInputs();
    state.finance_before = "all";
    state.finance_after = "all";
    linkedFilter = null;
    state.page = 1;
    renderFilterState();
    loadRoleMigration();
  }

  function resetFilters() {
    state = Object.assign(state, {
      pre_days: "30", post_days: "3", country: "all", store: "all",
      role_before: "all", role_after: "all", role_change: "all", finance_change: "all",
      finance_before: "all", finance_after: "all", data_status: "all", keyword: "", page: 1,
      sort_field: "", sort_dir: "", column_filters: {}
    });
    linkedFilter = null;
    syncInputs();
    renderFilterState();
    loadRoleMigration();
  }

  function clearFilterKey(key) {
    if (!Object.prototype.hasOwnProperty.call(state, key)) return;
    state[key] = key === "keyword" ? "" : "all";
    if (key === "finance_before" || key === "finance_after") {
      state.finance_before = "all";
      state.finance_after = "all";
    }
    if (linkedFilter && linkedFilterUsesKey(linkedFilter.type, key)) linkedFilter = null;
    state.page = 1;
    syncInputs();
    renderFilterState();
    loadRoleMigration();
  }

  function linkedFilterUsesKey(type, key) {
    if (type === "role_path") return key === "role_before" || key === "role_after";
    if (type === "finance_path") return key === "finance_before" || key === "finance_after";
    return type === key;
  }

  function clearLinkedFilters() {
    if (!linkedFilter) return;
    if (linkedFilter.type === "role_path") {
      state.role_before = "all";
      state.role_after = "all";
    } else if (linkedFilter.type === "finance_path") {
      state.finance_before = "all";
      state.finance_after = "all";
    } else if (linkedFilter.type === "role_change") {
      state.role_change = "all";
    } else if (linkedFilter.type === "data_status") {
      state.data_status = "all";
    }
    linkedFilter = null;
    state.page = 1;
    syncInputs();
    renderFilterState();
    loadRoleMigration();
  }

  function buildQuery() {
    var query = Object.assign({}, state, {
      adjust_date: currentAdjustDate(),
      column_filters: Object.keys(state.column_filters || {}).length ? JSON.stringify(state.column_filters) : ""
    });
    return "?" + Object.keys(query).filter(function (key) {
      return query[key] !== "" && query[key] !== "all";
    }).map(function (key) {
      return encodeURIComponent(key) + "=" + encodeURIComponent(query[key]);
    }).join("&");
  }

  function loadRoleMigration() {
    elements.priceReviewRoleMigrationView.classList.add("is-loading");
    return app.apiGet("/api/price-review/role-migration" + buildQuery()).then(function (payload) {
      loaded = true;
      meta = payload.meta || meta || {};
      populateFilterOptions(payload);
      renderSummary(payload.summary || {});
      renderRoleMatrix(payload.role_matrix || []);
      renderRolePerformanceTrend(payload.performance_trend || {});
      renderMigrationInsights(payload.summary || {}, payload.role_matrix || []);
      renderFinanceMatrix(payload.finance_matrix || []);
      renderRoleDetails(payload.rows || [], payload);
      renderPagination(payload);
      renderContextMeta(payload);
      renderRoleHero(payload);
      renderFilterState();
    }).catch(function (error) {
      console.error("Failed to load station role migration", error);
      elements.roleMigrationGrid.innerHTML = '<div class="empty-state compact">角色迁移数据加载失败</div>';
    }).finally(function () {
      elements.priceReviewRoleMigrationView.classList.remove("is-loading");
    });
  }

  function populateFilterOptions(payload) {
    populatePeriodSelect(elements.rolePreDaysSelect, state.pre_days, payload.meta && payload.meta.periods);
    populatePeriodSelect(elements.rolePostDaysSelect, state.post_days, payload.meta && payload.meta.periods);
    populateSelect(elements.roleCountrySelect, payload.filter_options.countries || [], state.country, "全部国家");
    populateSelect(elements.roleStoreSelect, payload.filter_options.stores || [], state.store, "全部店铺");
    var roles = (meta.roles || []).map(function (item) { return { value: item.key, label: item.label }; });
    populateSelect(elements.roleBeforeSelect, roles, state.role_before, "全部角色");
    populateSelect(elements.roleAfterSelect, roles, state.role_after, "全部角色");
  }

  function populatePeriodSelect(select, current, periods) {
    if (!select || !periods || !periods.length) return;
    select.innerHTML = periods.map(function (item) {
      return '<option value="' + app.escapeHtml(item.key) + '">' + app.escapeHtml(item.label) + '</option>';
    }).join("");
    select.value = current;
  }

  function populateSelect(select, options, current, allLabel) {
    if (!select) return;
    var html = '<option value="all">' + allLabel + '</option>';
    options.forEach(function (item) {
      var value = typeof item === "string" ? item : item.value;
      var label = typeof item === "string" ? item : item.label;
      html += '<option value="' + app.escapeHtml(value) + '">' + app.escapeHtml(label) + '</option>';
    });
    select.innerHTML = html;
    select.value = current;
    if (select.value !== current) select.value = "all";
  }

  function renderSummary(summary) {
    var valid = Number(summary.valid || 0);
    var cards = [
      { label: "有效 SKU", value: valid, tone: "complete", status: "complete", note: "已完成调前后窗口" },
      { label: "角色上升", value: summary.up || 0, tone: "up", change: "up", note: ratioText(summary.up, valid) },
      { label: "角色保持", value: summary.stable || 0, tone: "stable", change: "stable", note: ratioText(summary.stable, valid) },
      { label: "角色下降", value: summary.down || 0, tone: "down", change: "down", note: ratioText(summary.down, valid) }
    ];
    elements.roleMigrationKpis.innerHTML = cards.map(function (card) {
      var data = card.change ? ' data-role-change="' + card.change + '"' : ' data-data-status="' + card.status + '"';
      return '<button type="button" class="role-kpi-card role-tone-' + card.tone + '"' + data + '><span>' + card.label + '</span><strong>' + Number(card.value).toLocaleString("zh-CN") + '</strong><small>' + card.note + '</small></button>';
    }).join("");
  }

  function renderRoleMatrix(items) {
    var roles = (meta && meta.roles) || [];
    var byKey = {};
    items.forEach(function (item) { byKey[item.before + "|" + item.after] = item.count || 0; });
    var html = '<table class="role-migration-matrix"><thead><tr><th>调前 \\ 调后</th>' + roles.map(function (role) { return '<th>' + app.escapeHtml(role.label) + '</th>'; }).join("") + '</tr></thead><tbody>';
    roles.forEach(function (before) {
      html += '<tr><th>' + app.escapeHtml(before.label) + '</th>';
      roles.forEach(function (after) {
        var count = byKey[before.key + "|" + after.key] || 0;
        var tone = roleTone(before.rank, after.rank);
        html += '<td><button type="button" data-role-before="' + before.key + '" data-role-after="' + after.key + '" data-before-label="' + app.escapeHtml(before.label) + '" data-after-label="' + app.escapeHtml(after.label) + '" class="role-matrix-cell ' + tone.className + '"' + (count ? '' : ' disabled') + '><span>' + tone.label + '</span><strong>' + count.toLocaleString("zh-CN") + '</strong></button></td>';
      });
      html += '</tr>';
    });
    elements.roleMigrationMatrix.innerHTML = html + '</tbody></table>';
  }

  function roleTone(beforeRank, afterRank) {
    if (afterRank > beforeRank) return { className: "is-up", label: "上升" };
    if (afterRank < beforeRank) return { className: "is-down", label: "下降" };
    return { className: "is-stable", label: "保持" };
  }

  function renderRolePerformanceTrend(trend) {
    var summary = trend.summary || {};
    var points = trend.points || [];
    var hasValues = points.some(function (point) {
      return point.sales_qty != null || point.margin_rate != null;
    });
    var trendApi = window.priceReviewRoleTrend;
    if (!trendApi || !window.echarts || !Number(trend.sku_count || 0) || !hasValues) {
      if (rolePerformanceTrendChart) {
        rolePerformanceTrendChart.dispose();
        rolePerformanceTrendChart = null;
      }
      elements.rolePerformanceTrendSummary.innerHTML = "";
      elements.rolePerformanceTrendChart.innerHTML = '<div class="empty-state compact">当前筛选下暂无销量与毛利率趋势数据</div>';
      elements.rolePerformanceTrendCoverage.textContent = "";
      return;
    }

    function salesText(value) {
      return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    }

    function marginText(value) {
      return value == null ? "—" : (Number(value) * 100).toFixed(1) + "%";
    }

    elements.rolePerformanceTrendSummary.innerHTML = [
      ["调前销量合计", salesText(summary.sales_before), "before"],
      ["调后销量合计", salesText(summary.sales_after), "after"],
      ["调前整体毛利率", marginText(summary.margin_before), "before"],
      ["调后整体毛利率", marginText(summary.margin_after), "after"]
    ].map(function (item) {
      return '<div class="role-performance-trend-stat is-' + item[2] + '"><span>' + item[0] + '</span><strong>' + item[1] + '</strong></div>';
    }).join("");

    var preCoverage = Number(summary.available_pre_days || 0) + "/" + Number(summary.expected_pre_days || 0);
    var postCoverage = Number(summary.available_post_days || 0) + "/" + Number(summary.expected_post_days || 0);
    elements.rolePerformanceTrendCoverage.textContent = "覆盖当前筛选的 " + Number(trend.sku_count || 0).toLocaleString("zh-CN") + " 个 SKU · 调前数据 " + preCoverage + " 天 · 调后数据 " + postCoverage + " 天";
    if (!rolePerformanceTrendChart) {
      elements.rolePerformanceTrendChart.innerHTML = "";
      rolePerformanceTrendChart = window.echarts.init(elements.rolePerformanceTrendChart);
    }
    rolePerformanceTrendChart.setOption(trendApi.buildOption(trend), true);
    rolePerformanceTrendChart.resize();
  }

  function largestRoleTransition(items) {
    return items.slice().sort(function (a, b) { return Number(b.count || 0) - Number(a.count || 0); })[0] || null;
  }

  function renderMigrationInsights(summary, roleItems) {
    var largest = largestRoleTransition(roleItems);
    var valid = Number(summary.valid || 0);
    var largestText = largest && Number(largest.count || 0) > 0
      ? text(largest.before_label || roleLabel(largest.before)) + ' 至 ' + text(largest.after_label || roleLabel(largest.after))
      : "暂无成熟角色迁移";
    elements.roleMigrationInsights.innerHTML =
      '<div class="role-insight-primary"><span>最大迁移路径</span><strong>' + largestText + '</strong><small>' + (largest ? Number(largest.count || 0).toLocaleString("zh-CN") + " 个 SKU" : "—") + '</small></div>' +
      '<div class="role-insight-primary is-risk"><span>角色下降占比</span><strong>' + ratioText(summary.down, valid) + '</strong><small>' + Number(summary.down || 0).toLocaleString("zh-CN") + " 个 SKU" + '</small></div>' +
      '<div class="role-insight-status-grid">' +
        insightStatus("待观察", summary.pending, "pending") + insightStatus("数据不足", summary.source_incomplete, "muted") +
        insightStatus("财务上移", summary.finance_up, "up") + insightStatus("财务下移", summary.finance_down, "down") +
      '</div>';
  }

  function insightStatus(label, value, tone) {
    return '<div class="role-insight-status is-' + tone + '"><span>' + label + '</span><strong>' + Number(value || 0).toLocaleString("zh-CN") + '</strong></div>';
  }

  function renderFinanceMatrix(items) {
    renderFinanceFlow(items);
  }

  function renderFinanceFlow(items) {
    var flowApi = window.priceReviewFinanceFlow;
    var bands = (meta && meta.finance_bands) || [];
    if (!flowApi || !bands.length) {
      elements.financeMigrationMatrix.innerHTML = '<div class="empty-state compact">财务定价区间加载失败</div>';
      return;
    }
    var model = flowApi.buildModel(bands, items || []);
    var width = 520;
    var height = Math.max(430, model.leftNodes.length * 44 + 50);
    var top = 42;
    var bottom = height - 22;
    var step = model.leftNodes.length > 1 ? (bottom - top) / (model.leftNodes.length - 1) : 0;
    var leftEdge = 112;
    var rightEdge = width - 112;
    var centerLeft = width * 0.42;
    var centerRight = width * 0.58;
    var totals = { up: 0, stable: 0, down: 0 };

    var links = model.links.map(function (link) {
      totals[link.direction] += link.count;
      var sourceY = top + link.sourceIndex * step;
      var targetY = top + link.targetIndex * step;
      var path = "M " + leftEdge + " " + sourceY.toFixed(1) +
        " C " + centerLeft.toFixed(1) + " " + sourceY.toFixed(1) +
        ", " + centerRight.toFixed(1) + " " + targetY.toFixed(1) +
        ", " + rightEdge + " " + targetY.toFixed(1);
      var beforeLabel = app.escapeHtml(link.beforeLabel);
      var afterLabel = app.escapeHtml(link.afterLabel);
      var count = Number(link.count || 0).toLocaleString("zh-CN");
      return '<path class="finance-flow-link is-' + link.direction + '" d="' + path + '" stroke-width="' + link.strokeWidth.toFixed(1) + '" tabindex="0" role="button" aria-label="' + beforeLabel + ' 至 ' + afterLabel + '，' + count + ' 个 SKU" data-finance-before="' + app.escapeHtml(link.before) + '" data-finance-after="' + app.escapeHtml(link.after) + '" data-before-label="' + beforeLabel + '" data-after-label="' + afterLabel + '"><title>' + beforeLabel + ' → ' + afterLabel + '：' + count + ' 个 SKU</title></path>';
    }).join("");

    function renderNode(node, side) {
      var y = top + node.index * step;
      var x = side === "left" ? 4 : width - 108;
      var labelX = side === "left" ? 14 : width - 98;
      var countX = side === "left" ? 102 : width - 10;
      return '<g class="finance-flow-node' + (node.count ? '' : ' is-empty') + '">' +
        '<rect x="' + x + '" y="' + (y - 15).toFixed(1) + '" width="104" height="30" rx="8"></rect>' +
        '<text class="finance-flow-node-label" x="' + labelX + '" y="' + (y + 4).toFixed(1) + '">' + app.escapeHtml(node.label) + '</text>' +
        '<text class="finance-flow-node-count" x="' + countX + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + Number(node.count || 0).toLocaleString("zh-CN") + '</text>' +
        '</g>';
    }

    var emptyMessage = model.links.length ? "" : '<text class="finance-flow-empty" x="' + (width / 2) + '" y="' + (height / 2) + '" text-anchor="middle">当前筛选下暂无可归类迁移</text>';
    elements.financeMigrationMatrix.innerHTML =
      '<div class="finance-flow-summary" aria-label="财务区间迁移汇总">' +
        '<span class="is-up">↑ 上移 <b>' + totals.up.toLocaleString("zh-CN") + '</b></span>' +
        '<span class="is-stable">→ 保持 <b>' + totals.stable.toLocaleString("zh-CN") + '</b></span>' +
        '<span class="is-down">↓ 下移 <b>' + totals.down.toLocaleString("zh-CN") + '</b></span>' +
      '</div>' +
      '<div class="finance-flow-scroll"><svg class="finance-flow-svg" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="财务定价区间调前调后迁移流向图">' +
        '<text class="finance-flow-axis-title" x="4" y="18">调前区间</text>' +
        '<text class="finance-flow-axis-title" x="' + (width - 4) + '" y="18" text-anchor="end">调后区间</text>' +
        '<g class="finance-flow-links">' + links + '</g>' +
        '<g class="finance-flow-nodes">' + model.leftNodes.map(function (node) { return renderNode(node, "left"); }).join("") + model.rightNodes.map(function (node) { return renderNode(node, "right"); }).join("") + '</g>' +
        emptyMessage +
      '</svg></div>';
  }

  function renderContextMeta(payload) {
    var row = payload.context || (payload.rows || [])[0] || {};
    var preWindow = row.pre_period_start && row.pre_period_end ? row.pre_period_start + " 至 " + row.pre_period_end : "—";
    var postWindow = row.post_period_start && row.post_period_end ? row.post_period_start + " 至 " + row.post_period_end : "—";
    elements.roleRuleVersion.textContent = (meta.rule_version || "规则版本 —") + " · " + (meta.role_scope || "站点销售角色");
    elements.roleWindowMeta.textContent = "调前 " + payload.pre_days + "天（" + sourceLabel(row.pre_role_source) + "） → 调后 " + payload.post_days + "天（" + sourceLabel(row.post_role_source) + "）";
    renderCacheStatus(payload.cache_status || {});
    elements.roleFinanceSnapshotMeta.textContent = "财务快照 " + (row.finance_snapshot_date || "—");
    renderWindowSelectorContext(preWindow, postWindow);
  }

  function renderRoleHero(payload) {
    var dateText = payload.adjust_date
      ? payload.adjust_date.slice(5).replace("-", ".") + " "
      : "";
    elements.pageTitle.textContent = dateText + "调价角色迁移复盘";
    elements.statSkuCount.textContent = Number((payload.summary || {}).total || 0).toLocaleString("zh-CN");
    elements.statCountryCount.textContent = Number(((payload.filter_options || {}).countries || []).length).toLocaleString("zh-CN");
  }

  function renderWindowSelectorContext(preWindow, postWindow) {
    elements.rolePreWindowText.textContent = preWindow === "—" ? "截至调价前一天" : preWindow;
    elements.rolePostWindowText.textContent = postWindow === "—" ? "从调价后一天开始" : postWindow;
  }

  function sourceLabel(value) {
    return ({
      remote_dws: "远端快照",
      remote_cache: "远端快照",
      local_recomputed: "本地重算",
      local_v47: "本地重算",
      mixed: "混合来源"
    })[value] || "等待数据";
  }

  function renderCacheStatus(status) {
    var dates = status.earliest_data_date && status.latest_data_date
      ? status.earliest_data_date + " 至 " + status.latest_data_date
      : "等待同步";
    elements.roleCacheStatusMeta.textContent = "角色快照 " + dates;
    elements.roleCacheStatusMeta.title = status.synced_at ? "本地缓存同步于 " + status.synced_at : "本地缓存尚无同步记录";
  }

  function renderFilterState() {
    renderActiveFilterChips();
    renderLinkedFilterBar();
  }

  function renderActiveFilterChips() {
    var filters = [
      ["role_before", "调前角色", selectLabel(elements.roleBeforeSelect, state.role_before)],
      ["role_after", "调后角色", selectLabel(elements.roleAfterSelect, state.role_after)],
      ["role_change", "角色变化", roleChangeLabel(state.role_change)],
      ["finance_change", "财务变化", financeChangeLabel(state.finance_change)],
      ["data_status", "数据状态", dataStatusLabel(state.data_status)]
    ].filter(function (item) { return state[item[0]] !== "all"; });
    if (state.finance_before !== "all" || state.finance_after !== "all") {
      filters.push(["finance_before", "财务路径", financeBandLabel(state.finance_before) + " 至 " + financeBandLabel(state.finance_after)]);
    }
    elements.roleAdvancedFilterCount.textContent = String(filters.length);
    elements.roleAdvancedFilterCount.hidden = filters.length === 0;
    elements.roleActiveFilterChips.hidden = filters.length === 0;
    elements.roleActiveFilterChips.innerHTML = filters.map(function (item) {
      return '<button type="button" class="role-filter-chip" data-clear-role-filter="' + item[0] + '" title="移除此筛选"><span>' + item[1] + '：' + text(item[2]) + '</span><b aria-hidden="true">×</b></button>';
    }).join("");
  }

  function renderLinkedFilterBar() {
    elements.roleLinkedFilterBar.hidden = !linkedFilter;
    elements.roleLinkedFilterText.textContent = linkedFilter ? linkedFilter.label : "";
  }

  function renderRoleDetails(rows, payload) {
    elements.roleMigrationCount.textContent = "共 " + Number(payload.total || 0).toLocaleString("zh-CN") + " 条";
    if (!window.PriceReviewRoleGrid || !window.kanbanGrid) {
      elements.roleMigrationGrid.innerHTML = '<div class="empty-state compact">表格组件加载失败，请刷新页面重试。</div>';
      return;
    }
    roleMigrationGridReady = false;
    var options = window.PriceReviewRoleGrid.buildGridOptions(rows, {
      msku: function (value) { return window.PriceReviewRoleCopy.renderMskuCell(value, text); },
      role: roleBadge,
      change: changeBadge,
      number: function (value) { return number(value, 2); },
      percent: percent,
      status: function (row) { return statusBadge(row.data_status, row.data_message); }
    }, {
      activeKey: function () { return activeRoleDetailKey; },
      handleCopy: function (event) { return window.PriceReviewRoleCopy.handleMskuCopyClick(event); },
      isCopyTarget: function (event) { return window.PriceReviewRoleCopy.isMskuCopyTarget(event); },
      openDetail: openRoleDetail,
      gridState: {
        sortField: state.sort_field,
        sortDir: state.sort_dir,
        filterModel: state.column_filters
      },
      sortChanged: function (field, direction) {
        if (!roleMigrationGridReady || (state.sort_field === field && state.sort_dir === direction)) return;
        state.sort_field = field;
        state.sort_dir = direction;
        state.page = 1;
        loadRoleMigration();
      },
      filterChanged: function (filterModel) {
        if (!roleMigrationGridReady || JSON.stringify(state.column_filters || {}) === JSON.stringify(filterModel || {})) return;
        state.column_filters = filterModel || {};
        state.page = 1;
        loadRoleMigration();
      },
      ready: function () { roleMigrationGridReady = true; }
    });
    roleDetailRows = options.rowData.reduce(function (map, row) {
      map[row._roleDetailKey] = row;
      return map;
    }, {});
    roleMigrationGridApi = window.kanbanGrid.makeGrid("roleMigrationGrid", options);
  }

  function openRoleDetail(detailKey) {
    var row = roleDetailRows[detailKey];
    if (!row) return;
    activeRoleDetailKey = detailKey;
    roleDetailTrendView = "sales_margin";
    if (roleMigrationGridApi && roleMigrationGridApi.redrawRows) roleMigrationGridApi.redrawRows();
    elements.roleDetailDrawerMask.classList.remove("hidden");
    elements.roleDetailDrawer.classList.remove("hidden");
    elements.roleDetailDrawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("role-detail-open");
    elements.roleDetailTitle.textContent = "单品调价诊断";
    elements.roleDetailSubtitle.textContent = [row.country, row.station_store || row.store, row.msku].filter(Boolean).join(" · ");
    elements.roleDetailDrawerContent.innerHTML = '<div class="role-detail-loading"><span></span><p>正在加载角色、定价和每日趋势证据...</p></div>';

    var query = new URLSearchParams({
      adjust_date: currentAdjustDate(),
      pre_days: state.pre_days,
      post_days: state.post_days,
      country: row.country || "",
      store: row.station_store || row.store || "",
      msku: row.msku || ""
    });
    app.apiGet("/api/price-review/role-migration/detail" + "?" + query.toString()).then(function (payload) {
      renderRoleDetail(payload);
    }).catch(function (error) {
      console.error("Failed to load role migration detail", error);
      elements.roleDetailDrawerContent.innerHTML = '<div class="empty-state">单品诊断加载失败，请稍后重试。</div>';
    });
  }

  function closeRoleDetail() {
    if (!elements.roleDetailDrawer || elements.roleDetailDrawer.classList.contains("hidden")) return;
    elements.roleDetailDrawerMask.classList.add("hidden");
    elements.roleDetailDrawer.classList.add("hidden");
    elements.roleDetailDrawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("role-detail-open");
    if (roleDetailTrendChart) {
      roleDetailTrendChart.dispose();
      roleDetailTrendChart = null;
    }
  }

  function renderRoleDetail(payload) {
    var identity = payload.identity || {};
    var windows = payload.windows || {};
    var checkpoints = payload.checkpoints || {};
    var roles = payload.roles || {};
    var evidence = payload.role_evidence || {};
    var finance = payload.finance || {};
    elements.roleDetailSubtitle.textContent = [identity.country, identity.store, identity.msku, identity.product_name].filter(Boolean).join(" · ");
    elements.roleDetailDrawerContent.innerHTML = [
      '<section class="role-detail-identity">',
        identityItem("国家", identity.country), identityItem("店铺", identity.store), identityItem("MSKU", identity.msku), identityItem("本地 SKU", identity.local_sku),
        '<div class="role-detail-role-transition"><span>调前角色</span>' + roleBadge((roles.before || {}).label) + '<b>→</b><span>调后角色</span>' + roleBadge((roles.after || {}).label) + changeBadge(identity.role_change) + '</div>',
      '</section>',
      '<section class="role-detail-checkpoint-grid">',
        checkpointCard("调价前窗口", windowLabel(windows.before), checkpoints.before || {}, "before"),
        checkpointCard("调价日", identity.adjust_date || "—", checkpoints.adjustment || {}, "adjustment"),
        checkpointCard("调价后窗口", windowLabel(windows.after), checkpoints.after || {}, "after"),
      '</section>',
      '<section class="role-detail-evidence-grid">',
        evidenceCard("调前", evidence.before || {}),
        '<div class="role-detail-evidence-arrow" aria-hidden="true">→</div>',
        evidenceCard("调后", evidence.after || {}),
      '</section>',
      financeCard(finance),
      '<section class="role-detail-trend-card">',
        '<div class="role-detail-section-head"><div><span>日度趋势</span><strong>' + text(windowLabel(windows.before) + " 至 " + windowLabel(windows.after)) + '</strong></div>',
          '<div class="role-detail-trend-controls" role="group" aria-label="趋势指标切换">',
            '<button type="button" class="is-active" data-role-detail-trend-view="sales_margin" aria-pressed="true">销量与毛利率</button>',
            '<button type="button" data-role-detail-trend-view="rank" aria-pressed="false">小类排名</button>',
          '</div>',
        '</div>',
        '<div id="roleDetailTrendChart" class="role-detail-trend-chart" role="img" aria-label="单品调价前后销量与毛利率趋势"></div>',
      '</section>',
      '<footer class="role-detail-actions"><span>规则版本：' + text(identity.rule_version) + '</span><button id="roleDetailLocateBtn" type="button" class="primary-button">定位到明细</button></footer>'
    ].join("");

    var locateButton = document.getElementById("roleDetailLocateBtn");
    if (locateButton) locateButton.addEventListener("click", function () {
      closeRoleDetail();
      if (roleMigrationGridApi && roleMigrationGridApi.ensureIndexVisible) {
        roleMigrationGridApi.ensureIndexVisible(Number(activeRoleDetailKey), "middle");
        if (roleMigrationGridApi.flashCells && roleMigrationGridApi.getRowNode) {
          var selectedNode = roleMigrationGridApi.getRowNode(activeRoleDetailKey);
          if (selectedNode) roleMigrationGridApi.flashCells({ rowNodes: [selectedNode] });
        }
      }
    });
    renderRoleDetailTrend(payload);
  }

  function identityItem(label, value) {
    return '<div><span>' + app.escapeHtml(label) + '</span><strong>' + text(value) + '</strong></div>';
  }

  function checkpointCard(title, subtitle, values, tone) {
    var isAdjustment = tone === "adjustment";
    var cells = isAdjustment
      ? metricCell("当天排名", rankText(values.small_rank)) + metricCell("价格", money(values.price_before) + " → " + money(values.price_after))
      : metricCell("日销（件/天）", number(values.daily_sales, 2)) + metricCell("毛利率", percent(values.margin_rate)) + metricCell("小类排名", rankText(values.small_rank));
    return '<article class="role-detail-checkpoint is-' + tone + '"><div><strong>' + app.escapeHtml(title) + '</strong><span>' + text(subtitle) + '</span></div><section>' + cells + '</section></article>';
  }

  function metricCell(label, value) {
    return '<div><span>' + app.escapeHtml(label) + '</span><strong>' + value + '</strong></div>';
  }

  function evidenceCard(periodLabel, evidence) {
    var isProblem = evidence.role_code === "problem";
    var rows = (evidence.items || []).map(function (item) {
      var matchedLabel = isProblem ? (item.matched ? "已触发" : "未触发") : (item.matched ? "满足" : "未满足");
      return '<tr><td>' + text(item.metric) + '</td><td>' + formatEvidenceActual(item) + '</td><td>' + text(item.condition) + '</td><td><span class="role-evidence-state ' + (item.matched ? 'is-match' : 'is-miss') + '">' + matchedLabel + '</span></td></tr>';
    }).join("");
    return '<article class="role-detail-evidence-card"><header><span>' + app.escapeHtml(periodLabel) + '角色证据</span><strong>' + text(evidence.role_label) + '</strong></header><div class="role-detail-evidence-table-wrap"><table><thead><tr><th>规则维度</th><th>实际表现</th><th>判定条件</th><th>结果</th></tr></thead><tbody>' + rows + '</tbody></table></div><footer class="' + (evidence.qualified ? 'is-qualified' : 'is-unqualified') + '">' + (evidence.qualified ? '结论：当前指标与角色判定一致' : '结论：当前指标与固化角色不一致，建议核查快照') + '</footer></article>';
  }

  function formatEvidenceActual(item) {
    var actual = item.actual;
    if (typeof actual === "string") return text(actual);
    if (actual && typeof actual === "object") {
      if (Object.prototype.hasOwnProperty.call(actual, "daily_sales") && Object.prototype.hasOwnProperty.call(actual, "margin_rate")) {
        return '日销 ' + number(actual.daily_sales, 2) + ' / 毛利率 ' + percent(actual.margin_rate);
      }
      return text(JSON.stringify(actual));
    }
    if (item.metric && item.metric.indexOf("毛利") >= 0) return percent(actual);
    if (item.metric && item.metric.indexOf("排名") >= 0) return rankText(actual);
    return number(actual, 2);
  }

  function financeCard(finance) {
    var ladder = (finance.ladder || []).filter(function (item) { return item.price !== null && item.price !== undefined; });
    var ladderText = ladder.length ? ladder.map(function (item) { return item.margin + '%=' + money(item.price, finance.currency); }).join(' · ') : '财务阶梯缺失';
    return '<section class="role-detail-finance"><div class="role-detail-finance-title"><span>财务快照</span><strong>' + text(finance.snapshot_date) + '</strong><small>' + text(ladderText) + '</small></div>' +
      financeMetric("调前价格", money(finance.price_before, finance.currency)) + financeMetric("调后价格", money(finance.price_after, finance.currency)) + financeMetric("调价幅度", signedPercent(finance.drop_ratio)) + financeMetric("调前区间", text((finance.band_before || {}).label)) + financeMetric("调后区间", text((finance.band_after || {}).label)) + '</section>';
  }

  function financeMetric(label, value) {
    return '<div><span>' + app.escapeHtml(label) + '</span><strong>' + value + '</strong></div>';
  }

  function renderRoleDetailTrend(payload) {
    var chartElement = document.getElementById("roleDetailTrendChart");
    var chartApi = window.priceReviewRoleDetailChart;
    if (!chartElement || !chartApi || !window.echarts || !(payload.trend || []).length) {
      if (chartElement) chartElement.innerHTML = '<div class="empty-state compact">暂无逐日趋势数据</div>';
      return;
    }
    if (roleDetailTrendChart) roleDetailTrendChart.dispose();
    roleDetailTrendChart = window.echarts.init(chartElement);

    function updateView(nextView) {
      roleDetailTrendView = nextView === "rank" ? "rank" : "sales_margin";
      document.querySelectorAll("[data-role-detail-trend-view]").forEach(function (button) {
        var isActive = button.dataset.roleDetailTrendView === roleDetailTrendView;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      chartElement.setAttribute("aria-label", roleDetailTrendView === "rank" ? "单品调价前后小类排名趋势" : "单品调价前后销量与毛利率趋势");
      roleDetailTrendChart.setOption(chartApi.buildOption(payload, roleDetailTrendView), true);
    }

    document.querySelectorAll("[data-role-detail-trend-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        updateView(button.dataset.roleDetailTrendView);
      });
    });
    updateView(roleDetailTrendView);
  }

  function windowLabel(value) {
    if (!value) return "—";
    return (value.start || "—") + " 至 " + (value.end || "—");
  }

  function rankText(value) {
    return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN");
  }

  function money(value, currency) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (currency ? " " + app.escapeHtml(currency) : "");
  }

  function signedPercent(value) {
    if (value === null || value === undefined) return "—";
    var numeric = Number(value) * 100;
    return (numeric > 0 ? "+" : "") + numeric.toFixed(1) + "%";
  }

  function renderPagination(payload) {
    var pagination = window.PriceReviewRoleGrid.buildPaginationModel(payload);
    state.page = pagination.page;
    state.page_size = pagination.pageSize;
    elements.rolePaginationInfo.textContent = pagination.info;
    elements.rolePageSizeSelect.value = String(pagination.pageSize);
    elements.rolePrevPageBtn.disabled = pagination.page <= 1;
    elements.roleNextPageBtn.disabled = pagination.page >= pagination.totalPages;
    elements.rolePrevPageBtn.onclick = function () { if (pagination.page > 1) { state.page = pagination.page - 1; loadRoleMigration(); } };
    elements.roleNextPageBtn.onclick = function () { if (pagination.page < pagination.totalPages) { state.page = pagination.page + 1; loadRoleMigration(); } };
    elements.rolePaginationNumbers.innerHTML = pagination.pages.map(function (page) { return '<button type="button" class="page-number ' + (page === pagination.page ? "active" : "") + '" data-role-page="' + page + '">' + page + '</button>'; }).join("");
    elements.rolePaginationNumbers.querySelectorAll("[data-role-page]").forEach(function (button) {
      button.addEventListener("click", function () { state.page = Number(button.dataset.rolePage); loadRoleMigration(); });
    });
  }

  function selectLabel(select, value) {
    if (!select || value === "all") return "";
    var option = Array.from(select.options).find(function (item) { return item.value === value; });
    return option ? option.textContent : value;
  }

  function roleLabel(key) {
    var role = ((meta && meta.roles) || []).find(function (item) { return item.key === key; });
    return role ? role.label : key;
  }

  function financeBandLabel(key) {
    var band = ((meta && meta.finance_bands) || []).find(function (item) { return item.key === key; });
    return band ? band.label : key;
  }

  function roleChangeLabel(value) { return ({ up: "上升", stable: "保持", down: "下降" })[value] || value; }
  function financeChangeLabel(value) { return ({ up: "上移", stable: "保持", down: "下移", unavailable: "无法归类" })[value] || value; }
  function dataStatusLabel(value) { return ({ complete: "已成熟", pending: "待观察", source_incomplete: "数据不足" })[value] || value; }
  function ratioText(value, total) { return total ? (Number(value || 0) / total * 100).toFixed(1) + "%" : "0.0%"; }
  function text(value) { return app.escapeHtml(value === null || value === undefined || value === "" ? "—" : String(value)); }
  function number(value, digits) { return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }); }
  function percent(value) { return value === null || value === undefined ? "—" : (Number(value) * 100).toFixed(1) + "%"; }
  function roleBadge(value) { return value ? '<span class="role-badge">' + app.escapeHtml(value) + '</span>' : "—"; }
  function changeBadge(value) {
    var labels = { up: "上升", down: "下降", stable: "保持", unavailable: "—" };
    return '<span class="role-change-badge is-' + app.escapeHtml(value || "unavailable") + '">' + (labels[value] || "—") + '</span>';
  }
  function statusBadge(value, message) {
    var labels = { complete: "已成熟", pending: "待观察", source_incomplete: "数据不足" };
    return '<span class="role-status-badge is-' + app.escapeHtml(value || "unknown") + '" title="' + app.escapeHtml(message || "") + '">' + (labels[value] || value || "—") + '</span>';
  }
})();
