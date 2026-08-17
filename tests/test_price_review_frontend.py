from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_price_review_uses_snapshot_style_adjust_date_calendar():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")

    assert 'id="adjustDateButton"' in template
    assert 'id="adjustDateValue"' in template
    assert 'id="adjustCalendarPanel"' in template
    assert 'id="adjustDateInput" type="hidden"' in template
    assert 'id="adjustDateInput" type="date"' not in template
    assert 'class="snapshot-calendar-panel"' in template


def test_price_review_filter_panel_stays_above_kpi_section():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="panel price-review-filter-panel"' in template
    assert "body[data-page=\"price_review\"] .price-review-filter-panel" in styles
    filter_rule = styles.split('body[data-page="price_review"] .price-review-filter-panel', 1)[1].split("}", 1)[0]
    assert "z-index: 2;" in filter_rule
    assert "z-index: 20;" in styles.split(".side-nav {", 1)[1].split("}", 1)[0]


def test_price_review_calendar_only_enables_dates_with_adjustment_data():
    script = (ROOT / "app" / "static" / "js" / "price_review.js").read_text(encoding="utf-8")

    assert "renderAdjustCalendar" in script
    assert "data-adjust-date" in script
    assert "item.clickable && item.count > 0" in script
    assert "只显示近30天有调价数据的日期" in script
    assert 'elements.adjustDateInput.value = selectedDate' in script


def test_price_review_calendar_shows_compact_daily_counts():
    script = (ROOT / "app" / "static" / "js" / "price_review.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "itemsByDate[item.date] = item" in script
    assert 'class="snapshot-calendar-day-number"' in script
    assert 'class="snapshot-calendar-day-count"' in script
    assert 'dayItem && dayItem.count > 0' in script
    assert 'body[data-page="price_review"] .snapshot-calendar-day-count' in styles
    assert 'body[data-page="price_review"] .snapshot-calendar-day.disabled .snapshot-calendar-day-count' in styles


def test_price_review_date_picker_loads_all_history_separately_from_recent_summary():
    script = (ROOT / "app" / "static" / "js" / "price_review.js").read_text(encoding="utf-8")

    assert 'app.apiGet("/api/price-adjustments/daily-counts?days=30")' in script
    assert 'app.apiGet("/api/price-adjustments/daily-counts?include_all=true")' in script
    assert "renderCalendar(recentItems)" in script
    assert "adjustCalendarItems = allItems" in script


def test_price_review_main_tables_use_scoped_scroll_containers():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")

    assert 'class="table-wrap ag-grid-shell price-review-grid-shell compact price-review-scroll-grid price-review-scroll-grid--compact"' in template
    assert 'class="table-wrap price-review-country-table-wrap price-review-scroll-table"' in template
    assert 'class="table-wrap ag-grid-shell price-review-grid-shell price-review-scroll-grid price-review-scroll-grid--top"' in template
    assert 'class="table-wrap ag-grid-shell price-review-scroll-grid price-review-scroll-grid--detail"' in template


def test_price_review_main_tables_use_fixed_viewports_and_sticky_headers():
    script = (ROOT / "app" / "static" / "js" / "price_review.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert script.count('domLayout: "normal"') == 3
    assert 'body[data-page="price_review"] .price-review-scroll-grid' in styles
    assert 'body[data-page="price_review"] .price-review-scroll-grid--compact' in styles
    assert 'body[data-page="price_review"] .price-review-scroll-grid--top' in styles
    assert 'body[data-page="price_review"] .price-review-scroll-grid--detail' in styles
    assert 'body[data-page="price_review"] .price-review-scroll-table' in styles
    country_scroll_rule = styles.split(
        'body[data-page="price_review"] .price-review-scroll-table', 1
    )[1].split("}", 1)[0]
    assert "overflow: auto;" in country_scroll_rule
    country_header_rule = styles.split(".price-review-country-table th {", 1)[1].split("}", 1)[0]
    assert "position: sticky;" in country_header_rule


def test_price_review_scroll_layout_assets_have_fresh_cache_versions():
    base_template = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    page_template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")

    assert "styles.css') }}?v=20260817tablescroll1" in base_template
    assert "price_review.js') }}?v=20260817tablescroll1" in page_template
