from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_margin_price_popover_uses_document_capture_click_delegate():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert 'var button = event.target.closest("[data-margin-price-key]");' in script
    assert 'toggleMarginPricePopover(button, button.dataset.marginPriceKey || "");' in script
    assert 'elements.countryMetricsWrap.addEventListener("click", function (event) {\n      var button = event.target.closest("[data-margin-price-key]");' not in script
    assert 'document.addEventListener("click", function (event) {\n      var button = event.target.closest("[data-margin-price-key]");' in script
    assert "event.stopImmediatePropagation();" in script
    assert "}, true);" in script


def test_margin_price_assets_use_cache_busting_versions():
    base_template = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    replenishment_template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert "styles.css') }}?v=20260818rolegrid1" in base_template
    assert "replenishment.js') }}?v=20260827trackingbutton1" in replenishment_template
    assert "replenishment_tracking_summary.js') }}?v=20260727stagefilters1" in replenishment_template


def test_replenishment_has_sales_role_filter_with_existing_role_values():
    template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert '<select id="salesRoleSelect">' in template
    assert '<option value="all">&#20840;&#37096;&#38144;&#21806;&#35282;&#33394;</option>' in template
    assert '<option value="&#26126;&#26143;&#20135;&#21697;">&#26126;&#26143;&#20135;&#21697;</option>' in template
    assert '<option value="&#28508;&#21147;&#20135;&#21697;">&#28508;&#21147;&#20135;&#21697;</option>' in template
    assert '<option value="&#30246;&#29399;&#20135;&#21697;">&#30246;&#29399;&#20135;&#21697;</option>' in template
    assert '<option value="&#38382;&#39064;&#20135;&#21697;">&#38382;&#39064;&#20135;&#21697;</option>' in template


def test_replenishment_sales_role_filter_reuses_category_state_and_period_linkage():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert '"salesRoleSelect"' in script
    assert '["salesRoleSelect", "category"]' in script
    assert 'elements.salesRoleSelect.value = state.category || "all";' in script
    assert 'state.category = "all";' in script
    assert 'if (pair[1] === "category_period_days") state.category = "all";' not in script
    assert "category: state.category" in script
    assert '"snapshot_date", "level", "category", "category_period_days"' in script


def test_replenishment_tracking_summary_entry_is_visible():
    template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert '<button id="summaryViewBtn" type="button">' in template
    assert '<button id="summaryViewBtn" type="button" hidden>' not in template


def test_replenishment_layers_do_not_show_purchase_tracking_jump_button():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "layer-tracking-button" not in script
    assert "data-tracking-level-entry" not in script
    assert "openTrackingPage" not in script
    assert ".layer-tracking-button" not in styles


def test_replenishment_tracking_summary_allows_selecting_page_size():
    template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert '<select id="trackingSummaryPageSizeSelect"' in template
    assert '<option value="20">20条</option>' in template
    assert '<option value="50">50条</option>' in template
    assert '<option value="100">100条</option>' in template
    assert '"trackingSummaryPageSizeSelect"' in script
    assert 'state.page_size = Number(el.trackingSummaryPageSizeSelect.value) || 20;' in script
    assert 'state.page = 1;' in script


def test_tracking_summary_level_click_preserves_active_stage_filter():
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")
    level_click_start = script.index('var categoryNode = event.target.closest("[data-summary-category]");')
    level_click_end = script.index('el.trackingSummaryCards.addEventListener', level_click_start)
    level_click_block = script[level_click_start:level_click_end]
    helper_start = script.index("function selectHistoryLevel")
    helper_end = script.index("function selectHistoryLevelStage", helper_start)
    helper_block = script[helper_start:helper_end]

    assert "state.summary_stage" not in level_click_block
    assert "state.summary_stage" not in helper_block
    assert 'var active = state.summary_stage === card[4] ? " active" : "";' in script
    assert 'var rowActive = state.history_level === level ? " active" : "";' in script


def test_tracking_summary_missing_count_has_direct_filter_action():
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert 'data-summary-stage-missing' in script
    assert 'purchase_plan_done: "no_purchase_plan"' in script
    assert '查看未完成 ' in script
    assert 'function selectHistoryLevelStage(level, stage, focusTable)' in script
    assert 'state.detail_stage = stage || "";' in script
    assert 'detail_stage: state.detail_stage || ""' in script
    assert 'summary-detail-filter-hint' in script


def test_tracking_summary_completed_stage_keeps_the_selected_top_status_scope():
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")
    start = script.index("function selectHistoryLevelCompletedStage(level, stage)")
    end = script.index("\n  function ", start + 1)
    block = script[start:end]

    assert 'state.summary_stage = "all";' not in block


def test_tracking_summary_fba_missing_action_uses_the_displayed_not_created_scope():
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert 'fba_plan_done: "fba_plan_not_created"' in script


def test_tracking_summary_explains_top_status_scope_and_final_detail_count():
    script = (ROOT / "app" / "static" / "js" / "replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert "function renderLevelFlowScopeHint(summary)" in script
    assert "当前状态筛选：" in script
    assert "下方按历史补货层级展示" in script
    assert "function renderDetailFilterHint(total, summary)" in script
    assert "当前状态：" in script
    assert "命中" in script


def test_replenishment_grid_shows_followed_origin_columns():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert "followOriginLink" in script
    assert "followedStatus" in script
    assert "followedByLinks" in script
    assert "replenishBlockReason" in script
    assert "asinMergeStatus" in script
    assert "asinMergeTarget" in script
    assert "asinMergeReason" in script
    assert 'field: "follow_origin_link"' in script
    assert 'field: "followed_status"' in script
    assert 'field: "followed_by_links"' in script
    assert 'field: "replenish_block_reason"' in script
    assert 'field: "asin_merge_status"' in script
    assert 'field: "asin_merge_target"' in script
    assert 'field: "asin_merge_reason"' in script


def test_replenishment_grid_compacts_lead_time_metrics_into_one_column():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    table_block = script[script.index("function renderTable"):script.index("function renderLinkSummaryCell")]

    assert "function renderLeadTimeCell(params)" in script
    assert 'headerName: "库存 / 交期"' in table_block
    assert 'field: "support_days"' in table_block
    assert "cellRenderer: renderLeadTimeCell" in table_block
    assert 'numberColumn(text.supportDays, "support_days"' not in table_block
    assert 'field: "effective_purchase_lead_days"' not in table_block
    assert 'field: "arrival_inventory_support_days"' not in table_block
    assert "lead_time_demand_qty" in script
    assert "arrival_inventory_qty" in script
    assert "lead_time_stockout_days" in script
    assert "purchase_lead_status" in script
    assert ".replenishment-lead-time-cell" in styles
    assert ".lead-time-risk.safe" in styles
    assert ".lead-time-risk.danger" in styles
    assert ".lead-time-risk.neutral" in styles


def test_replenishment_lead_time_cell_opens_document_level_detail_popover():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert 'event.target.closest("[data-lead-time-key]")' in script
    assert "toggleLeadTimePopover" in script
    assert "replenishmentLeadTimeRowMap" in script
    assert "lead-time-popover" in script
    assert "closeLeadTimePopover" in script


def test_below_moq_is_an_independent_display_layer_without_duplicate_pool_card():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'var LEVEL_BELOW_MOQ = "\\u4f4e\\u4e8e\\u6700\\u5c0f\\u8d77\\u8ba2\\u91cf";' in script
    assert 'row.level !== LEVEL_BELOW_MOQ' in script
    assert 'Number(row.sort || 0) !== 7' in script
    assert 'state.level === LEVEL_BELOW_MOQ' in script
    assert "'<small>' + text.replenishQty + ' ' + formatNumber((payload.summary || {}).moq_warning_calculated_qty || 0) + '</small>'" in script
    assert 'if (key === 7) return "\\u8d77";' in script
    assert '.status-pill.level-7' in styles
    assert '#c2410c' in styles


def test_changing_level_filter_clears_moq_warning_filter():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    change_handler = script[script.index('["levelSelect", "level"]'):script.index('elements.datePickerBtn.addEventListener')]

    assert 'if (pair[1] === "level") state.moq_status = "all";' in change_handler


def test_replenishment_grid_compacts_long_followed_links():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert "renderLinkSummaryCell" in script
    assert 'cellRenderer: renderLinkSummaryCell' in script
    assert 'tooltipField: "followed_by_links"' in script
    assert 'return app.escapeHtml(String(count)) + "个链接";' in script


def test_replenishment_grid_truncates_long_merge_text_cells():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="ag-truncate-cell"' in script
    assert 'cellClass: "ag-truncate-column"' in script
    assert 'field: "asin_merge_target"' in script
    assert 'field: "asin_merge_reason"' in script
    assert ".ag-truncate-column .ag-cell-value" in styles
    assert ".ag-truncate-cell" in styles
    assert "text-overflow: ellipsis" in styles


def test_replenishment_grid_displays_listing_tags_as_compact_text_column():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert "listingTags" in script
    assert 'field: "listing_tags"' in script
    assert 'tooltipField: "listing_tags"' in script
    assert 'cellClass: "ag-truncate-column listing-tags-column"' in script
    assert 'width: 190' in script
    assert 'minWidth: 150' in script
    assert 'maxWidth: 260' in script


def test_replenishment_msku_and_sku_have_row_hover_copy_actions():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderReplenishmentCodeCell(params)" in script
    assert 'renderReplenishmentCopyButton("msku", msku)' in script
    assert 'renderReplenishmentCopyButton("sku", sku)' in script
    assert 'data-replenishment-copy="' in script
    assert '<svg class="replenishment-copy-icon"' in script
    assert 'var copyButton = event.target.closest("[data-replenishment-copy]");' in script
    assert "copyReplenishmentCode(copyButton);" in script
    assert ".replenishment-code-copy" in styles
    assert "#replenishmentAgGrid .ag-row:hover .replenishment-code-copy" in styles
    assert "pointer-events: none" in styles


def test_replenishment_copy_releases_mouse_focus_after_click():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")
    copy_click = script[
        script.index('var copyButton = event.target.closest("[data-replenishment-copy]");'):
        script.index('var button = event.target.closest("[data-country-detail]");')
    ]

    assert "copyButton.blur();" in copy_click
