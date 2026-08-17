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

    assert "styles.css') }}?v=20260817roletimelinec" in base_template
    assert "price_review.js') }}?v=20260817roletimelinec" in page_template
    assert "price_review_role.js') }}?v=20260817roletimelinec" in page_template


def test_price_review_has_performance_and_station_role_views():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")

    assert 'data-price-review-view="performance"' in template
    assert 'data-price-review-view="role-migration"' in template
    assert 'id="priceReviewPerformanceView"' in template
    assert 'id="priceReviewRoleMigrationView"' in template
    assert 'id="rolePreDaysSelect"' in template
    assert 'id="rolePostDaysSelect"' in template
    assert 'id="roleComparisonModeSelect"' not in template
    assert 'value="90">90天</option>' in template
    assert '30天 → 调后N天' not in template
    assert 'id="roleMigrationMatrix"' in template
    assert 'id="roleMigrationTableBody"' in template


def test_station_role_view_loads_api_and_renders_fixed_scroll_table():
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")

    assert 'app.apiGet("/api/price-review/role-migration"' in script
    assert "renderRoleMatrix" in script
    assert "renderFinanceMatrix" in script
    assert "renderRoleDetails" in script
    assert 'class="table-wrap price-review-role-table-wrap"' in template
    role_scroll_rule = styles.split('.price-review-role-table-wrap {', 1)[1].split('}', 1)[0]
    assert "overflow: auto;" in role_scroll_rule
    role_header_rule = styles.split('.price-review-role-table th {', 1)[1].split('}', 1)[0]
    assert "position: sticky;" in role_header_rule


def test_station_role_view_reuses_the_single_page_filter_surface():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")

    assert template.count('class="panel price-review-filter-panel') == 1
    assert 'id="priceReviewPerformanceFilters"' in template
    assert 'id="priceReviewRoleFilters"' in template
    assert 'price-review-role-filter-panel' not in template
    assert "syncFilterSurface" in script
    assert 'elements.priceReviewPerformanceFilters.hidden = roleActive' in script
    assert 'elements.priceReviewRoleFilters.hidden = !roleActive' in script


def test_station_role_periods_are_independent_and_explained_visually():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="price-review-role-window-compare"' in template
    assert 'id="rolePreWindowText"' in template
    assert 'id="rolePostWindowText"' in template
    assert "pre_days: \"30\"" in script
    assert "post_days: \"3\"" in script
    assert "comparison_mode" not in script
    assert "renderWindowSelectorContext" in script
    assert "renderRoleHero" in script
    assert "调价角色迁移复盘" in script
    assert ".price-review-role-window-compare {" in styles
    assert ".role-window-pivot {" in styles


def test_station_role_advanced_filters_are_inline_and_render_removable_chips():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")

    assert 'id="roleAdvancedFiltersBtn"' in template
    assert 'aria-controls="roleAdvancedFilters"' in template
    assert 'id="roleAdvancedFilters"' in template
    assert 'id="roleActiveFilterChips"' in template
    assert "toggleAdvancedFilters" in script
    assert "renderActiveFilterChips" in script
    assert "data-clear-role-filter" in script


def test_station_role_primary_kpis_and_deterministic_insight_panel():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")

    assert 'id="roleMigrationInsights"' in template
    assert 'id="financeMigrationToggleBtn"' in template
    assert 'id="roleWindowMeta"' in template
    assert 'id="roleFinanceSnapshotMeta"' in template
    assert 'id="roleCacheStatusMeta"' in template
    assert "renderMigrationInsights" in script
    assert "largestRoleTransition" in script
    assert "renderFinanceTransitions" in script
    assert "renderCacheStatus" in script
    assert "cards.length" not in script
    assert 'change: "up"' in script
    assert 'change: "stable"' in script
    assert 'change: "down"' in script


def test_station_role_linked_filters_are_visible_and_clearable():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "price_review_role.js").read_text(encoding="utf-8")

    assert 'id="roleLinkedFilterBar"' in template
    assert 'id="clearRoleLinkedFiltersBtn"' in template
    assert "renderLinkedFilterBar" in script
    assert "clearLinkedFilters" in script
    assert "data-finance-before" in script
    assert "data-finance-after" in script


def test_station_role_redesign_has_compact_responsive_layout_rules():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert '.price-review-role-analysis-grid {' in styles
    analysis_rule = styles.split('.price-review-role-analysis-grid {', 1)[1].split('}', 1)[0]
    assert "minmax(0, 2fr)" in analysis_rule
    assert "minmax(320px, 1fr)" in analysis_rule
    assert '.price-review-role-advanced-filters[hidden]' in styles
    assert '.price-review-role-filter-chips' in styles
    assert '.price-review-role-insights' in styles
    role_view_rule = styles.split('.price-review-role-view {', 1)[1].split('}', 1)[0]
    assert "grid-template-columns: minmax(0, 1fr);" in role_view_rule
    assert "min-width: 0;" in role_view_rule
    assert 'id="priceReviewFilterPanel"' in template
    assert '.price-review-filter-panel.is-role-mode .filters-grid.price-review-filters' in styles
    assert "repeat(8, minmax(0, 1fr))" in styles
    assert '@media (max-width: 1280px)' in styles


def test_station_role_filters_use_two_tier_timeline_workbench():
    template = (ROOT / "app" / "templates" / "price_review.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'class="role-filter-workbench"' in template
    assert 'class="role-filter-timeline"' in template
    assert 'class="role-filter-scope-bar"' in template
    assert 'role-filter-date-block' in template
    assert 'class="role-filter-data-status"' in template
    assert ".role-filter-workbench" in styles
    assert ".role-filter-timeline" in styles
    assert ".role-filter-scope-bar" in styles
    assert ".role-filter-date-block" in styles
    assert ".role-filter-data-status" in styles


def test_station_role_timeline_is_capped_on_wide_screens():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    role_grid_rule = styles.split(
        ".price-review-filter-panel.is-role-mode .filters-grid.price-review-filters {", 2
    )[2].split("}", 1)[0]

    assert "minmax(520px, 720px)" in role_grid_rule
    assert "minmax(300px, 1fr)" in role_grid_rule


def test_price_review_releases_global_min_width_on_narrow_screens():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert 'body[data-page="price_review"] { min-width: 0; }' in styles
