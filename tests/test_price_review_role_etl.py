from datetime import date

from etl import price_review_update
from etl.station_sales_role_cache import CacheSyncResult


def test_business_tracking_periods_include_three_day_first_observation():
    assert price_review_update.TRACKING_PERIODS == (3, 7, 14, 28)


def test_station_role_tracking_never_backfills_before_august_2026():
    assert price_review_update._station_role_adjust_start(date(2026, 4, 23)) == date(2026, 8, 1)
    assert price_review_update._station_role_adjust_start(date(2026, 8, 10)) == date(2026, 8, 10)


def test_role_metrics_sql_uses_country_normalized_station_and_includes_adjustment_day_in_pre_period():
    sql = " ".join(price_review_update._station_role_metrics_sql("etl_datasync_test").split())

    assert "p.seller_name_new = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))" in sql
    assert "p.country = a.country" in sql
    assert "p.seller_sku_adj = a.msku" in sql
    assert "p.dt_date <> a.adjust_date" not in sql
    assert "sum(case when p.dt_date between date_sub(a.adjust_date, interval (%(pre_days)s - 1) day) and a.adjust_date" in sql
    assert "sum(case when p.dt_date between date_add(a.adjust_date, interval 1 day) and date_add(a.adjust_date, interval %(post_days)s day)" in sql
    assert "dashboard_limit_price_daily_snapshot" not in sql


def test_all_period_role_metrics_scan_product_performance_once_for_every_period():
    sql = " ".join(price_review_update._station_role_all_period_metrics_sql("etl_datasync_test").split())

    assert sql.count("from `etl_datasync_test`.`dashboard_product_performance_daily`") == 0
    assert sql.count("left join `etl_datasync_test`.`dashboard_product_performance_daily`") == 1
    assert "interval 89 day" in sql
    assert "interval 90 day" in sql
    for period_days in (3, 7, 14, 30, 90):
        assert f"pre_seen_days_{period_days}" in sql
        assert f"post_seen_days_{period_days}" in sql
        assert f"pre_sales_qty_{period_days}" in sql
        assert f"post_small_rank_date_{period_days}" in sql


def test_pair_metrics_selects_requested_pre_and_post_windows_without_changing_values():
    raw = {
        "adjust_date": date(2026, 8, 19),
        "country": "德国",
        "station_store": "StoreA",
        "msku": "A1",
        "pre_sales_qty_7": 17,
        "pre_sales_qty_30": 41,
        "post_sales_qty_3": 6,
        "post_sales_qty_14": 24,
        "pre_seen_days_7": 7,
        "post_seen_days_3": 3,
    }

    paired = price_review_update._station_role_pair_metrics(raw, 7, 3)

    assert paired["pre_sales_qty"] == 17
    assert paired["post_sales_qty"] == 6
    assert paired["pre_seen_days"] == 7
    assert paired["post_seen_days"] == 3
    assert "pre_sales_qty_30" not in paired
    assert "post_sales_qty_14" not in paired


def test_role_performance_lookup_index_matches_station_join_dimensions():
    sql = " ".join(
        price_review_update._station_role_performance_index_sql("etl_datasync_test").split()
    )

    assert "dashboard_product_performance_daily" in sql
    assert "seller_name_new, country, seller_sku_adj, dt_date" in sql


def test_finance_ladders_are_loaded_by_a_separate_reusable_query():
    sql = " ".join(price_review_update._station_role_finance_sql("etl_datasync_test").split())

    assert "dashboard_limit_price_daily_snapshot" in sql
    assert "f.seller_name_new = a.seller_name_new" in sql
    assert "f.country = a.country" in sql
    assert "f.seller_sku = a.msku" in sql
    assert "max(fd.snapshot_date)" in sql
    assert "when '€' then 'EUR'" in sql


def test_role_tracking_table_uses_required_business_grain():
    ddl = price_review_update._station_role_tracking_ddl("etl_datasync_test")

    assert "price_review_station_role_tracking" in ddl
    assert "primary key (adjust_date, pre_period_days, post_period_days, country, station_store, msku)" in " ".join(ddl.split())
    assert "pre_role_source" in ddl
    assert "post_role_source" in ddl
    assert "pre_source_data_date" in ddl
    assert "post_source_data_date" in ddl
    assert "finance_snapshot_date" in ddl
    assert "station_sales_role_rule_version" in ddl


def test_station_role_period_pairs_cover_all_independent_choices_without_28_days():
    pairs = price_review_update._station_role_period_pairs()

    assert len(pairs) == 25
    assert (30, 3) in pairs
    assert (14, 7) in pairs
    assert all(pre in {3, 7, 14, 30, 90} and post in {3, 7, 14, 30, 90} for pre, post in pairs)


def test_cached_role_sql_only_joins_exact_adjustment_products_and_anchor_dates():
    sql = " ".join(price_review_update._station_role_cached_roles_sql("etl_datasync_test").split())

    assert "station_sales_role_recent_cache" in sql
    assert "c.country = a.country" in sql
    assert "c.station_store = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))" in sql
    assert "c.msku = a.msku" in sql
    assert "c.data_date = a.adjust_date" in sql
    assert "c.data_date = date_add(a.adjust_date, interval %(post_days)s day)" in sql


def test_all_cached_roles_are_loaded_in_one_query_with_each_cache_period_as_anchor():
    sql = " ".join(price_review_update._station_role_all_cached_roles_sql("etl_datasync_test").split())

    assert sql.count("station_sales_role_recent_cache") == 2
    assert "c.data_date = a.adjust_date" in sql
    assert "c.data_date = date_add(a.adjust_date, interval c.period_days day)" in sql
    assert "%(pre_days)s" not in sql
    assert "%(post_days)s" not in sql


def test_complete_solidified_rows_only_refresh_while_remote_source_is_in_recent_cache():
    recent_dates = {date(2026, 8, 15), date(2026, 8, 16)}

    assert not price_review_update._should_refresh_station_role_tracking(
        {
            "data_status": "complete",
            "pre_role_source": "local_recomputed",
            "post_role_source": "local_recomputed",
            "pre_source_data_date": date(2026, 8, 9),
            "post_source_data_date": date(2026, 8, 12),
        },
        recent_dates,
    )
    assert price_review_update._should_refresh_station_role_tracking(
        {
            "data_status": "complete",
            "pre_role_source": "remote_dws",
            "post_role_source": "local_recomputed",
            "pre_source_data_date": date(2026, 8, 16),
            "post_source_data_date": date(2026, 8, 19),
        },
        recent_dates,
        pre_days=7,
        post_days=7,
    )
    assert not price_review_update._should_refresh_station_role_tracking(
        {
            "data_status": "complete",
            "pre_role_source": "local_recomputed",
            "post_role_source": "local_recomputed",
            "pre_source_data_date": date(2026, 8, 16),
            "post_source_data_date": date(2026, 8, 16),
        },
        recent_dates,
        pre_days=3,
        post_days=3,
    )
    assert price_review_update._should_refresh_station_role_tracking(
        {
            "data_status": "complete",
            "pre_role_source": "local_recomputed",
            "post_role_source": "local_recomputed",
            "pre_source_data_date": date(2026, 8, 16),
            "post_source_data_date": date(2026, 8, 19),
        },
        recent_dates,
        pre_days=7,
        post_days=7,
    )
    assert price_review_update._should_refresh_station_role_tracking(
        {"data_status": "pending"},
        recent_dates,
    )


def test_existing_rows_with_old_pre_window_are_refreshed_for_adjustment_day_migration():
    assert price_review_update._should_refresh_station_role_tracking(
        {
            "adjust_date": date(2026, 8, 10),
            "pre_period_end": date(2026, 8, 9),
            "data_status": "complete",
            "pre_role_source": "local_recomputed",
            "post_role_source": "local_recomputed",
            "pre_source_data_date": date(2026, 8, 9),
            "post_source_data_date": date(2026, 8, 17),
        },
        set(),
        pre_days=7,
        post_days=7,
    )


class RecordingCursor:
    def __init__(self):
        self.executions = []
        self.executemany_calls = []
        self.result = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql, list(rows)))

    def fetchall(self):
        return list(self.result)

    def fetchmany(self, _batch_size):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1


def test_price_review_source_load_refreshes_recent_station_role_cache(monkeypatch):
    target = RecordingConnection()
    source = RecordingConnection()
    sync_calls = []
    monkeypatch.setenv("DASHBOARD_PRICE_QUEUE_LOOKBACK_DAYS", "1")
    monkeypatch.setattr(price_review_update, "ensure_price_review_tables", lambda *args: None)
    monkeypatch.setattr(price_review_update, "_copy_rows", lambda *args: 0)
    monkeypatch.setattr(
        price_review_update,
        "sync_recent_station_role_cache",
        lambda *args, **kwargs: sync_calls.append((args, kwargs))
        or CacheSyncResult((date(2026, 8, 15), date(2026, 8, 16)), 8, "batch"),
        raising=False,
    )

    price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": date(2026, 8, 17)},
        batch_size=1000,
    )

    assert sync_calls == [((source, target, "etl_datasync_test"), {"batch_size": 1000})]


def _source_fingerprint(
    adjust_date,
    row_count,
    checksum_sum,
    checksum_xor,
    updated_at=None,
):
    return {
        "adjust_date": adjust_date,
        "source_row_count": row_count,
        "source_max_updated_at": updated_at,
        "source_checksum_sum": checksum_sum,
        "source_checksum_xor": checksum_xor,
    }


def _prepare_incremental_source_load(monkeypatch, source_fingerprints, local_fingerprints):
    normalized_local_fingerprints = {
        current_day: {
            **fingerprint,
            "local_row_count": fingerprint.get(
                "local_row_count",
                fingerprint["source_row_count"],
            ),
        }
        for current_day, fingerprint in local_fingerprints.items()
    }
    monkeypatch.setenv("DASHBOARD_PRICE_QUEUE_LOOKBACK_DAYS", "2")
    monkeypatch.setattr(price_review_update, "ensure_price_review_tables", lambda *args: None)
    monkeypatch.setattr(
        price_review_update,
        "_load_price_review_source_fingerprints",
        lambda *args: source_fingerprints,
    )
    monkeypatch.setattr(
        price_review_update,
        "_load_price_review_local_fingerprints",
        lambda *args: normalized_local_fingerprints,
    )
    monkeypatch.setattr(
        price_review_update,
        "sync_recent_station_role_cache",
        lambda *args, **kwargs: CacheSyncResult((), 0, "batch"),
    )


def test_price_review_source_load_initial_run_refreshes_every_date(monkeypatch):
    first_day = date(2026, 8, 16)
    second_day = date(2026, 8, 17)
    source_fingerprints = {
        first_day: _source_fingerprint(first_day, 3, 101, 11),
        second_day: _source_fingerprint(second_day, 4, 202, 22),
    }
    _prepare_incremental_source_load(monkeypatch, source_fingerprints, {})
    copied_days = []
    monkeypatch.setattr(
        price_review_update,
        "_copy_rows",
        lambda source_cursor, target_cursor, insert_sql, batch_size:
        copied_days.append(source_cursor.executions[-1][1]["adjust_start_at"].date()) or 1,
    )
    target = RecordingConnection()
    source = RecordingConnection()

    affected = price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": second_day},
        batch_size=1000,
    )

    delete_dates = [
        params["adjust_date"]
        for sql, params in target.cursor_instance.executions
        if "delete from" in sql.lower() and "where adjust_date =" in sql.lower()
    ]
    assert affected == 2
    assert copied_days == [first_day, second_day]
    assert delete_dates == [first_day, second_day]
    assert target.cursor_instance.executemany_calls[0][1] == [
        source_fingerprints[first_day],
        source_fingerprints[second_day],
    ]


def test_price_review_source_load_skips_unchanged_dates(monkeypatch):
    first_day = date(2026, 8, 16)
    second_day = date(2026, 8, 17)
    fingerprints = {
        first_day: _source_fingerprint(first_day, 3, 101, 11),
        second_day: _source_fingerprint(second_day, 4, 202, 22),
    }
    _prepare_incremental_source_load(monkeypatch, fingerprints, dict(fingerprints))
    monkeypatch.setattr(
        price_review_update,
        "_copy_rows",
        lambda *args: (_ for _ in ()).throw(AssertionError("unchanged dates must not be copied")),
    )
    target = RecordingConnection()
    source = RecordingConnection()

    affected = price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": second_day},
        batch_size=1000,
    )

    assert affected == 0
    assert not any("delete from" in sql.lower() for sql, _ in target.cursor_instance.executions)
    assert target.cursor_instance.executemany_calls == []


def test_price_review_source_load_refreshes_only_changed_date(monkeypatch):
    first_day = date(2026, 8, 16)
    second_day = date(2026, 8, 17)
    source_fingerprints = {
        first_day: _source_fingerprint(first_day, 3, 101, 11),
        second_day: _source_fingerprint(second_day, 5, 303, 33),
    }
    local_fingerprints = {
        first_day: dict(source_fingerprints[first_day]),
        second_day: _source_fingerprint(second_day, 4, 202, 22),
    }
    _prepare_incremental_source_load(monkeypatch, source_fingerprints, local_fingerprints)
    copied_days = []
    monkeypatch.setattr(
        price_review_update,
        "_copy_rows",
        lambda source_cursor, target_cursor, insert_sql, batch_size:
        copied_days.append(source_cursor.executions[-1][1]["adjust_start_at"].date()) or 5,
    )
    target = RecordingConnection()
    source = RecordingConnection()

    affected = price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": second_day},
        batch_size=1000,
    )

    assert affected == 5
    assert copied_days == [second_day]
    assert target.cursor_instance.executemany_calls[0][1] == [source_fingerprints[second_day]]


def test_price_review_source_load_refreshes_when_state_matches_but_local_rows_are_missing(monkeypatch):
    first_day = date(2026, 8, 16)
    second_day = date(2026, 8, 17)
    source_fingerprints = {
        first_day: _source_fingerprint(first_day, 3, 101, 11),
        second_day: _source_fingerprint(second_day, 4, 202, 22),
    }
    local_fingerprints = {
        first_day: dict(source_fingerprints[first_day]),
        second_day: {
            **source_fingerprints[second_day],
            "local_row_count": 3,
        },
    }
    _prepare_incremental_source_load(monkeypatch, source_fingerprints, local_fingerprints)
    copied_days = []
    monkeypatch.setattr(
        price_review_update,
        "_copy_rows",
        lambda source_cursor, target_cursor, insert_sql, batch_size:
        copied_days.append(source_cursor.executions[-1][1]["adjust_start_at"].date()) or 4,
    )
    target = RecordingConnection()
    source = RecordingConnection()

    affected = price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": second_day},
        batch_size=1000,
    )

    assert affected == 4
    assert copied_days == [second_day]
    assert target.cursor_instance.executemany_calls[0][1] == [source_fingerprints[second_day]]


def test_price_review_source_load_deletes_local_rows_when_source_day_becomes_empty(monkeypatch):
    first_day = date(2026, 8, 16)
    second_day = date(2026, 8, 17)
    empty_fingerprint = price_review_update._empty_price_review_source_fingerprint(second_day)
    source_fingerprints = {
        first_day: _source_fingerprint(first_day, 3, 101, 11),
        second_day: empty_fingerprint,
    }
    local_fingerprints = {
        first_day: dict(source_fingerprints[first_day]),
        second_day: _source_fingerprint(second_day, 4, 202, 22),
    }
    _prepare_incremental_source_load(monkeypatch, source_fingerprints, local_fingerprints)
    monkeypatch.setattr(price_review_update, "_copy_rows", lambda *args: 0)
    target = RecordingConnection()
    source = RecordingConnection()

    affected = price_review_update.execute_price_review_source_load(
        target,
        source,
        "etl_datasync_test",
        {"biz_date": second_day},
        batch_size=1000,
    )

    delete_dates = [
        params["adjust_date"]
        for sql, params in target.cursor_instance.executions
        if "delete from" in sql.lower() and "where adjust_date =" in sql.lower()
    ]
    assert affected == 0
    assert delete_dates == [second_day]
    assert target.cursor_instance.executemany_calls[0][1] == [empty_fingerprint]
