(function () {
  var app = window.kanbanApp;
  var elements = {};
  var loaded = false;
  var meta = null;
  var financeExpanded = false;
  var currentFinanceItems = [];
  var linkedFilter = null;
  var currentView = "performance";
  var performanceHero = null;
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
    page_size: 20
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
      "roleMigrationMatrix", "roleMigrationInsights", "financeMigrationMatrix", "financeMigrationToggleBtn",
      "roleMigrationCount", "roleMigrationTableBody", "rolePaginationInfo", "rolePaginationNumbers",
      "rolePrevPageBtn", "roleNextPageBtn", "roleRuleVersion", "roleWindowMeta",
      "roleCacheStatusMeta", "roleFinanceSnapshotMeta", "roleLinkedFilterBar", "roleLinkedFilterText",
      "clearRoleLinkedFiltersBtn", "pageTitle", "statSkuCount", "statCountryCount"
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
      });
    }
    if (elements.financeMigrationToggleBtn) {
      elements.financeMigrationToggleBtn.addEventListener("click", function () {
        financeExpanded = !financeExpanded;
        renderFinanceTransitions(currentFinanceItems);
      });
    }
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
      finance_before: "all", finance_after: "all", data_status: "all", keyword: "", page: 1
    });
    linkedFilter = null;
    financeExpanded = false;
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
    var query = Object.assign({}, state, { adjust_date: currentAdjustDate() });
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
      renderMigrationInsights(payload.summary || {}, payload.role_matrix || []);
      renderFinanceMatrix(payload.finance_matrix || []);
      renderRoleDetails(payload.rows || [], payload);
      renderPagination(payload);
      renderContextMeta(payload);
      renderRoleHero(payload);
      renderFilterState();
    }).catch(function (error) {
      console.error("Failed to load station role migration", error);
      elements.roleMigrationTableBody.innerHTML = '<tr><td colspan="15" class="empty-state">角色迁移数据加载失败</td></tr>';
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
    currentFinanceItems = items.slice().sort(function (a, b) { return Number(b.count || 0) - Number(a.count || 0); });
    renderFinanceTransitions(currentFinanceItems);
  }

  function renderFinanceTransitions(items) {
    if (!items.length) {
      elements.financeMigrationMatrix.innerHTML = '<div class="empty-state compact">当前筛选下暂无可归类的财务区间迁移</div>';
      elements.financeMigrationToggleBtn.hidden = true;
      return;
    }
    elements.financeMigrationToggleBtn.hidden = items.length <= 5;
    elements.financeMigrationToggleBtn.textContent = financeExpanded ? "收起" : "查看全部";
    elements.financeMigrationToggleBtn.setAttribute("aria-expanded", financeExpanded ? "true" : "false");
    var visibleItems = financeExpanded ? items : items.slice(0, 5);
    elements.financeMigrationMatrix.innerHTML = visibleItems.map(function (item) {
      var beforeLabel = item.before_label || item.before;
      var afterLabel = item.after_label || item.after;
      return '<button type="button" class="finance-path-row" data-finance-before="' + app.escapeHtml(item.before) + '" data-finance-after="' + app.escapeHtml(item.after) + '" data-before-label="' + app.escapeHtml(beforeLabel) + '" data-after-label="' + app.escapeHtml(afterLabel) + '"><span><strong>' + app.escapeHtml(beforeLabel) + '</strong><small>至 ' + app.escapeHtml(afterLabel) + '</small></span><b>' + Number(item.count || 0).toLocaleString("zh-CN") + '</b></button>';
    }).join("");
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
      local_v47: "本地重算"
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
    if (!rows.length) {
      elements.roleMigrationTableBody.innerHTML = '<tr><td colspan="15" class="empty-state">当前筛选下暂无数据</td></tr>';
      return;
    }
    elements.roleMigrationTableBody.innerHTML = rows.map(function (row) {
      var windowText = (row.pre_period_start || "--") + " 至 " + (row.pre_period_end || "--") + " / " + (row.post_period_start || "--") + " 至 " + (row.post_period_end || "--");
      return '<tr><td>' + text(row.country) + '</td><td>' + text(row.station_store || row.store) + '</td><td><strong>' + text(row.msku) + '</strong></td>' +
        '<td>' + roleBadge(row.role_before_label) + '</td><td>' + roleBadge(row.role_after_label) + '</td><td>' + changeBadge(row.role_change) + '</td>' +
        '<td class="number-cell">' + number(row.pre_daily_sales, 2) + '</td><td class="number-cell">' + number(row.post_daily_sales, 2) + '</td>' +
        '<td class="number-cell">' + percent(row.pre_margin_rate) + '</td><td class="number-cell">' + percent(row.post_margin_rate) + '</td>' +
        '<td>' + text(row.finance_band_before_label) + '</td><td>' + text(row.finance_band_after_label) + '</td><td>' + changeBadge(row.finance_change) + '</td>' +
        '<td>' + statusBadge(row.data_status, row.data_message) + '</td><td class="role-window-cell">' + app.escapeHtml(windowText) + '</td></tr>';
    }).join("");
  }

  function renderPagination(payload) {
    elements.rolePaginationInfo.textContent = "第 " + payload.page + " / " + payload.total_pages + " 页";
    elements.rolePrevPageBtn.disabled = payload.page <= 1;
    elements.roleNextPageBtn.disabled = payload.page >= payload.total_pages;
    elements.rolePrevPageBtn.onclick = function () { if (payload.page > 1) { state.page = payload.page - 1; loadRoleMigration(); } };
    elements.roleNextPageBtn.onclick = function () { if (payload.page < payload.total_pages) { state.page = payload.page + 1; loadRoleMigration(); } };
    var pages = [];
    for (var page = Math.max(1, payload.page - 2); page <= Math.min(payload.total_pages, payload.page + 2); page += 1) pages.push(page);
    elements.rolePaginationNumbers.innerHTML = pages.map(function (page) { return '<button type="button" class="page-number ' + (page === payload.page ? "active" : "") + '" data-role-page="' + page + '">' + page + '</button>'; }).join("");
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
