from datetime import date

from etl import price_review_update
from etl.station_sales_role_cache import CacheSyncResult


def test_station_role_tracking_never_backfills_before_august_2026():
    assert price_review_update._station_role_adjust_start(date(2026, 4, 23)) == date(2026, 8, 1)
    assert price_review_update._station_role_adjust_start(date(2026, 8, 10)) == date(2026, 8, 10)


def test_role_metrics_sql_uses_country_normalized_station_and_excludes_adjustment_day():
    sql = " ".join(price_review_update._station_role_metrics_sql("etl_datasync_test").split())

    assert "p.seller_name_new = coalesce(a.seller_name_new, substring_index(a.store, '-', 1))" in sql
    assert "p.country = a.country" in sql
    assert "p.seller_sku_adj = a.msku" in sql
    assert "p.dt_date <> a.adjust_date" in sql
    assert "sum(case when p.dt_date between date_sub(a.adjust_date, interval %(pre_days)s day) and date_sub(a.adjust_date, interval 1 day)" in sql
    assert "sum(case when p.dt_date between date_add(a.adjust_date, interval 1 day) and date_add(a.adjust_date, interval %(post_days)s day)" in sql
    assert "dashboard_limit_price_daily_snapshot" not in sql


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
    assert "c.data_date = date_sub(a.adjust_date, interval 1 day)" in sql
    assert "c.data_date = date_add(a.adjust_date, interval %(post_days)s day)" in sql


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
    )
    assert price_review_update._should_refresh_station_role_tracking(
        {"data_status": "pending"},
        recent_dates,
    )


class RecordingCursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

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
