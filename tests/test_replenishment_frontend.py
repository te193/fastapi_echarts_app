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

    assert "styles.css') }}?v=20260717countrymatrix2" in base_template
    assert "replenishment.js') }}?v=20260710fbaattribution1" in replenishment_template
    assert "replenishment_tracking_summary.js') }}?v=20260715fbashipment1" in replenishment_template


def test_replenishment_tracking_summary_entry_is_visible():
    template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert '<button id="summaryViewBtn" type="button">' in template
    assert '<button id="summaryViewBtn" type="button" hidden>' not in template


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
