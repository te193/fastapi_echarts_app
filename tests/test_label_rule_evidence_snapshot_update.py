from datetime import date

from etl.label_rule_evidence_snapshot_update import (
    CREATE_TABLE_SQL,
    LOCAL_LABEL_DETAIL_TABLE,
    LOCAL_LABEL_FACT_TABLE,
    SNAPSHOT_BATCH_SIZE,
    _replace_snapshot_dates,
    _same_source_fingerprint,
    _snapshot_sync_plan,
    _source_fingerprint_sql,
    classify_sales_role,
    fact_table_sql,
    parse_periods,
    refresh,
    run_update,
    snapshot_date_plan,
)
from etl.dashboard_daily_update import SchemaConfig


def test_sales_role_evidence_uses_remote_rule_thresholds():
    assert classify_sales_role(6, 0.20) == 101
    assert classify_sales_role(2, 0.12) == 102
    assert classify_sales_role(0.8, 0.08) == 103
    assert classify_sales_role(0, 0.30) == 104
    assert parse_periods("7d,14d,30d,90d") == (7, 14, 30, 90)
    assert "raw_order_gross_profit" not in CREATE_TABLE_SQL
    assert "最近两个标签日期" in CREATE_TABLE_SQL
    assert "idx_label_date" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "idx_date_unit" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "evidence_blob mediumblob" in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert "evidence_json json" not in fact_table_sql(LOCAL_LABEL_FACT_TABLE, include_indexes=True)
    assert LOCAL_LABEL_DETAIL_TABLE.endswith("dashboard_label_detail_snapshot")
    assert SNAPSHOT_BATCH_SIZE == 5000


def test_snapshot_date_plan_refreshes_latest_and_reuses_previous_local_date():
    latest = date(2026, 8, 17)
    previous = date(2026, 8, 16)

    remote_dates, reused_dates = snapshot_date_plan(
        (latest, previous),
        {latest, previous},
    )

    assert remote_dates == (latest,)
    assert reused_dates == (previous,)


def test_snapshot_date_plan_fetches_both_dates_when_local_snapshot_is_empty():
    dates = (date(2026, 8, 17), date(2026, 8, 16))

    remote_dates, reused_dates = snapshot_date_plan(dates, set())

    assert remote_dates == dates
    assert reused_dates == ()


def test_source_fingerprint_requires_matching_remote_content_and_local_count():
    fingerprint = {
        "source_row_count": 12,
        "source_max_created_time": None,
        "source_checksum_sum": 1234,
        "source_checksum_xor": 56,
    }

    assert _same_source_fingerprint(
        fingerprint,
        {**fingerprint, "local_row_count": 12},
    )
    assert not _same_source_fingerprint(
        fingerprint,
        {**fingerprint, "local_row_count": 11},
    )
    assert not _same_source_fingerprint(
        fingerprint,
        {**fingerprint, "local_row_count": 12, "source_checksum_sum": 1235},
    )
    assert "evidence_json" in _source_fingerprint_sql()
    assert "source_checksum_xor" in _source_fingerprint_sql()


def test_snapshot_sync_plan_skips_unchanged_latest_date():
    latest = date(2026, 8, 25)
    previous = date(2026, 8, 24)
    fingerprint = {
        "source_row_count": 10,
        "source_max_created_time": None,
        "source_checksum_sum": 100,
        "source_checksum_xor": 10,
    }
    local_state = {
        latest: {**fingerprint, "local_row_count": 10},
        previous: {"local_row_count": 9},
    }

    remote_dates, reused_dates = _snapshot_sync_plan(
        (latest, previous),
        local_state,
        fingerprint,
        supports_blob=True,
    )

    assert remote_dates == ()
    assert reused_dates == (latest, previous)


def test_snapshot_sync_plan_only_fetches_new_or_changed_latest_date():
    latest = date(2026, 8, 25)
    previous = date(2026, 8, 24)
    local_state = {previous: {"local_row_count": 9}}

    remote_dates, reused_dates = _snapshot_sync_plan(
        (latest, previous),
        local_state,
        None,
        supports_blob=True,
    )

    assert remote_dates == (latest,)
    assert reused_dates == (previous,)

    changed_source = {
        "source_row_count": 11,
        "source_max_created_time": None,
        "source_checksum_sum": 101,
        "source_checksum_xor": 11,
    }
    local_state[latest] = {
        "local_row_count": 10,
        "source_row_count": 10,
        "source_max_created_time": None,
        "source_checksum_sum": 100,
        "source_checksum_xor": 10,
    }
    remote_dates, reused_dates = _snapshot_sync_plan(
        (latest, previous),
        local_state,
        changed_source,
        supports_blob=True,
    )

    assert remote_dates == (latest,)
    assert reused_dates == (previous,)


class Cursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def executemany(self, sql, rows):
        self.executions.append((sql, rows))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_refresh_keeps_only_latest_two_label_dates():
    conn = Connection()
    schemas = SchemaConfig("etl_datasync_test", "etl_datasync", "dwd_datasync", "temporary_dwd")
    dates = (date(2026, 7, 19), date(2026, 7, 18))
    affected = refresh(conn, schemas, [], dates)

    assert affected == 0
    assert conn.committed
    delete_sql = [sql for sql, _ in conn.cursor_instance.executions if "delete from" in sql.lower()]
    assert any("label_date not in" in sql.lower() for sql in delete_sql)
    assert all("etl_datasync_test.dashboard_label_rule_evidence_snapshot" in sql for sql in delete_sql)


def test_replace_snapshot_dates_only_replaces_latest_and_retains_previous():
    conn = Connection()
    latest = date(2026, 8, 20)
    previous = date(2026, 8, 19)

    _replace_snapshot_dates(
        conn,
        "local_fact",
        "local_detail",
        "local_state",
        "fact_stage",
        "detail_stage",
        (latest, previous),
        (latest,),
        {
            latest: {
                "data_date": latest,
                "source_row_count": 10,
                "source_max_created_time": None,
                "source_checksum_sum": 100,
                "source_checksum_xor": 10,
            }
        },
    )

    executions = conn.cursor_instance.executions
    fact_deletes = [
        (sql, params)
        for sql, params in executions
        if "delete from local_fact" in sql.lower()
    ]
    assert fact_deletes[0][1] == (latest,)
    assert fact_deletes[1][1] == (latest, previous)
    assert any("insert into local_fact" in sql.lower() and "from fact_stage" in sql.lower() for sql, _ in executions)
    assert any("insert into local_state" in sql.lower() for sql, _ in executions)
    assert not any(
        "insert into fact_stage" in sql.lower() and "from local_fact" in sql.lower()
        for sql, _ in executions
    )
    assert conn.committed
    assert not conn.rolled_back


def test_replace_snapshot_dates_rolls_back_when_fact_insert_fails():
    class FailingCursor(Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "insert into local_fact" in sql.lower():
                raise RuntimeError("simulated insert failure")

    conn = Connection()
    conn.cursor_instance = FailingCursor()
    latest = date(2026, 8, 20)

    try:
        _replace_snapshot_dates(
            conn,
            "local_fact",
            "local_detail",
            "local_state",
            "fact_stage",
            "detail_stage",
            (latest,),
            (latest,),
            {
                latest: {
                    "data_date": latest,
                    "source_row_count": 10,
                    "source_max_created_time": None,
                    "source_checksum_sum": 100,
                    "source_checksum_xor": 10,
                }
            },
        )
    except RuntimeError as exc:
        assert str(exc) == "simulated insert failure"
    else:
        raise AssertionError("expected snapshot replacement to fail")

    assert conn.rolled_back
    assert not conn.committed


def test_run_update_returns_sync_summary_and_closes_connections(monkeypatch):
    target = Connection()
    source = Connection()
    target.closed = False
    source.closed = False
    target.close = lambda: setattr(target, "closed", True)
    source.close = lambda: setattr(source, "closed", True)
    dates = (date(2026, 8, 20), date(2026, 8, 19))

    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.apply_database_ini_env", lambda: None)
    monkeypatch.setattr(
        "etl.label_rule_evidence_snapshot_update.build_schema_config",
        lambda: SchemaConfig("etl_datasync_test", "etl_datasync", "dwd_datasync", "temporary_dwd"),
    )
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.connect_target", lambda: target)
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.connect_source", lambda: source)
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.latest_label_dates", lambda conn: dates)
    monkeypatch.setattr(
        "etl.label_rule_evidence_snapshot_update.sync_label_snapshots",
        lambda *args: {
            "fact_rows": 120,
            "remote_fact_rows": 70,
            "reused_fact_rows": 50,
            "detail_rows": 30,
        },
    )
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.remote_role_facts", lambda *args, **kwargs: {})
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.build_rows", lambda *args: [{"label_date": dates[0]}])
    monkeypatch.setattr("etl.label_rule_evidence_snapshot_update.refresh", lambda *args: 16)

    result = run_update((7, 30))

    assert result["latest_date"] == "2026-08-20"
    assert result["fact_rows"] == 120
    assert result["evidence_rows"] == 16
    assert result["periods"] == ["7d", "30d"]
    assert target.closed
    assert source.closed
