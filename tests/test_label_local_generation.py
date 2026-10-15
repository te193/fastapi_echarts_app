from datetime import date
import pytest

from etl.label_local_generation import calculation_dates, encode_history_chunk, decode_history_chunk


def test_daily_refresh_retains_published_lifecycle_coverage():
    from etl.label_local_generation import lifecycle_policy, LIFECYCLE_VERSION, RULE_VERSION
    assert lifecycle_policy(None, LIFECYCLE_VERSION) is True
    assert lifecycle_policy(None, RULE_VERSION) is False
    assert lifecycle_policy(None, None) is False
    assert lifecycle_policy(False, LIFECYCLE_VERSION) is False
    assert lifecycle_policy(True, RULE_VERSION) is True


def test_dates_replay_in_order_and_resume_after_last_success():
    assert calculation_dates(date(2026, 10, 7), date(2026, 10, 4), date(2026, 10, 5)) == [date(2026, 10, 6), date(2026, 10, 7)]
    assert calculation_dates(date(2026, 10, 7), date(2026, 10, 7), None) == [date(2026, 10, 7)]


def test_same_day_rerun_is_allowed_but_backwards_replay_needs_explicit_rebuild():
    assert calculation_dates(date(2026, 10, 7), date(2026, 1, 1), date(2026, 10, 7)) == [date(2026, 10, 7)]
    with pytest.raises(ValueError, match="earlier"):
        calculation_dates(date(2026, 10, 6), date(2026, 1, 1), date(2026, 10, 7))


def test_history_compression_roundtrips_null_country_and_chinese_json():
    rows = [["2026-10-07", "欧洲站", None, "store", "SKU", 304, "current", "2026-10-08 00:00:00", '{"标签":"断货中"}']]
    payload, checksum = encode_history_chunk(rows)
    assert decode_history_chunk(payload, checksum) == rows
    with pytest.raises(ValueError, match="checksum"):
        decode_history_chunk(payload, "wrong")


class FakeConnection:
    def __init__(self, available=(), locked=False):
        self.available = available
        self.locked = locked
        self.closed = False
        self.calls = []
        self.rows = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        self.calls.append(sql)
        if "get_lock" in sql:
            self.rows = [{"acquired": 0 if self.locked else 1}]
        elif "distinct date(start_date)" in sql:
            self.rows = [{"d": day} for day in self.available]
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def commit(self):
        pass

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.closed = True


def fake_runtime(monkeypatch, conn):
    from etl import label_local_generation as generation
    monkeypatch.setattr(generation, "apply_database_ini_env", lambda: None)
    monkeypatch.setattr(generation, "connect_target", lambda: conn)
    monkeypatch.setattr(generation, "prepare_tables", lambda *args: None)
    monkeypatch.setattr(generation, "complete_operations", lambda *args, **kwargs: None)
    monkeypatch.setattr(generation, "apply_receiving_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(generation, "preflight_remote_history", lambda *args: None)
    monkeypatch.setattr(generation, "load_inputs", lambda *args: {"batch_id": "batch", "input_hash": "hash"})
    return generation


def test_busy_generation_rejects_second_writer_and_does_not_release_owners_lock(monkeypatch):
    conn = FakeConnection(locked=True)
    generation = fake_runtime(monkeypatch, conn)
    with pytest.raises(RuntimeError, match="already running"):
        generation.run_generation(sync=False, schema="label_test")
    assert conn.closed
    assert not any("release_lock" in sql for sql in conn.calls)


def test_changed_input_batch_blocks_after_baseline_acceptance_before_any_work(monkeypatch):
    conn=FakeConnection()
    generation=fake_runtime(monkeypatch,conn)
    def unexpected_prepare(*args):
        raise AssertionError('work tables touched after input batch changed')
    monkeypatch.setattr(generation,'prepare_tables',unexpected_prepare)
    with pytest.raises(RuntimeError,match='changed after baseline acceptance'):
        generation.run_generation(sync=False,schema='label_test',expected_input_hash='accepted_hash')
    assert conn.closed
    assert not any('publication' in sql or sql.startswith('call ') for sql in conn.calls)


def test_history_gap_fails_before_calculation_or_publication(monkeypatch):
    conn = FakeConnection([date(2026, 10, 5), date(2026, 10, 7)])
    generation = fake_runtime(monkeypatch, conn)
    with pytest.raises(RuntimeError, match="missing product performance dates"):
        generation.run_generation(date(2026, 10, 7), date(2026, 10, 5), sync=False, schema="label_test")
    assert not any(sql.startswith("call ") or sql.startswith("delete ") for sql in conn.calls)
    assert conn.closed and any("release_lock" in sql for sql in conn.calls)


def test_first_publication_defaults_to_two_days_and_keeps_inventory_validation(monkeypatch):
    conn = FakeConnection([date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)])
    generation = fake_runtime(monkeypatch, conn)
    monkeypatch.setattr(generation, 'validate_local_dictionary', lambda *args: None)
    def inventory_guard(conn, schema, dates):
        assert dates == [date(2026, 10, 6), date(2026, 10, 7)]
        raise RuntimeError('inventory guard reached')
    monkeypatch.setattr(generation, 'validate_inventory_dates', inventory_guard)
    with pytest.raises(RuntimeError, match="inventory guard reached"):
        generation.run_generation(date(2026, 10, 7), sync=False, schema="label_test")
    assert not any(sql.startswith("call ") for sql in conn.calls)


def test_source_copy_failure_closes_both_connections_and_leaves_publication_alone(monkeypatch):
    conn = FakeConnection()
    source = FakeConnection()
    generation = fake_runtime(monkeypatch, conn)
    monkeypatch.setattr(generation, "connect_source", lambda: source)
    monkeypatch.setattr(generation, "assert_separate_servers", lambda *args: None)
    def failure(*args, **kwargs):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(generation, "sync_sources", failure)
    with pytest.raises(RuntimeError, match="source unavailable"):
        generation.run_generation(schema="label_test")
    assert source.closed and conn.closed
    assert not any("publication" in sql for sql in conn.calls)


@pytest.mark.parametrize('resume', [False, True])
def test_two_day_initialization_publishes_and_next_day_resumes_without_full_replay(monkeypatch, resume):
    from etl.label_local_sql import BASELINE_SHA256, RULE_VERSION
    start, end = date(2026, 10, 7), date(2026, 10, 8)
    class PublicationConnection(FakeConnection):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if 'select * from' in sql and 'dashboard_label_local_days' in sql and resume:
                self.rows = [{'data_date': start, 'history_start': start,
                              'baseline_sha256': BASELINE_SHA256, 'rule_version': RULE_VERSION}]
            elif 'select data_date from' in sql and 'dashboard_label_local_days' in sql:
                self.rows = [{'data_date': end}, {'data_date': start}]
        def nextset(self):
            return None
    conn = PublicationConnection([start, end])
    generation = fake_runtime(monkeypatch, conn)
    days = []
    operation_days = []
    monkeypatch.setattr(generation, 'complete_operations', lambda conn, schema, day, **kw: operation_days.append(day))
    monkeypatch.setattr(generation, 'validate_local_dictionary', lambda *a: None)
    monkeypatch.setattr(generation, 'validate_inventory_dates', lambda *a: None)
    monkeypatch.setattr(generation, 'compile_procedure', lambda *a, **kw: 'select 1')
    monkeypatch.setattr(generation, 'restore_work', lambda *a: None)
    monkeypatch.setattr(generation, 'archive_day', lambda conn, schema, day, *a, **kw: days.append(day))
    monkeypatch.setattr(generation, 'validate_day', lambda *a, **kw: {'fact_rows': 1, 'evidence_rows': 1})
    def publish(conn, schema, published_days, run_id, inputs, history_start, **kw):
        assert published_days == [end, start]
        assert history_start == start
        assert kw['complete_lifecycle'] is False
        return {'fact_rows': 2, 'evidence_rows': 2}
    monkeypatch.setattr(generation, 'publish_days', publish)
    result = generation.run_generation(end, sync=False, schema='label_test', progress=lambda r: None)
    assert days == ([end] if resume else [start, end])
    assert operation_days == days
    assert result['status'] == 'refreshed'
    assert result['history_coverage'] == 'recent_periods_only'
    assert result['historical_carry_complete'] is False
    assert result['rule_version'] == RULE_VERSION


def test_historical_source_gap_is_reported_before_copying_millions_of_rows(monkeypatch):
    conn = FakeConnection()
    source = FakeConnection()
    generation = fake_runtime(monkeypatch, conn)
    monkeypatch.setattr(generation, "connect_source", lambda: source)
    monkeypatch.setattr(generation, "assert_separate_servers", lambda *args: None)
    def blocked(*args):
        raise RuntimeError("historical inventory missing 2026-10-01")
    def unexpected_copy(*args, **kwargs):
        raise AssertionError("large source transfer started despite missing history")
    monkeypatch.setattr(generation, "preflight_remote_history", blocked)
    monkeypatch.setattr(generation, "sync_sources", unexpected_copy)
    with pytest.raises(RuntimeError, match="2026-10-01"):
        generation.run_generation(schema="label_test")
    assert source.closed and conn.closed
