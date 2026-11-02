from datetime import date, datetime

import pytest

from etl.dashboard_daily_update import DEFAULT_STEP_ORDER, SchemaConfig


def test_early_profile_loads_only_replenishment_inputs_and_preserves_all_other_steps():
    from etl.daily_pricing_update import EARLY_DASHBOARD_STEPS, PRICING_STEPS
    early = EARLY_DASHBOARD_STEPS.split(',')
    assert early == ["product_performance_daily", "restock_snapshot", "inventory_snapshot", "listing_price_snapshot"]
    assert set(early) | set(PRICING_STEPS.split(',')) == set(DEFAULT_STEP_ORDER)
    assert set(early).isdisjoint(PRICING_STEPS.split(','))
    assert {"product_performance_daily", "inventory_snapshot", "restock_snapshot", "listing_price_snapshot"} <= set(early)


class PricingConnection:
    def __init__(self, batches, *, snapshot=None, counts=None):
        self.batches = iter(batches)
        self.query = ""
        self.queries = []
        self.snapshot = snapshot if snapshot is not None else snapshot_row()
        self.counts = counts if counts is not None else {
            'source_rows': 12, 'source_day_rows': 12, 'snapshot_rows': 12,
        }

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.query = sql
        self.params = params
        self.queries.append((sql, params))

    def fetchall(self):
        return next(self.batches)

    def fetchone(self):
        if '每日快照_执行日志' in self.query:
            return self.snapshot or None
        return self.counts


def snapshot_row(**changes):
    row = {'status': 'success', 'end_time': datetime(2026, 10, 14, 7, 44),
           'source_date': date(2026, 10, 14), 'source_rows': 12,
           'written_rows': 12, 'verified_rows': 12}
    return {**row, **changes}


def ready_rows():
    return [{"proc_name": name, "status": "success", "end_time": datetime(2026,10,14,8,55)} for name in (
        "proc_在库节点_输出定价表", "proc_在库节点_输出定价表_每日快照", "proc_lx_sale_adjust_price_queue")]


def test_pricing_gate_waits_for_today_success_instead_of_nonempty_yesterday_data():
    from etl.daily_pricing_update import wait_for_pricing_sources
    stale = ready_rows()
    stale[0]['end_time'] = datetime(2026,10,13,8,55)
    connection = PricingConnection([stale, ready_rows()])
    waits = []
    wait_for_pricing_sources(connection, SchemaConfig('local','etl_datasync','dwd','pricing'),
                             date(2026,10,14), now=lambda: datetime(2026,10,14,8,30),
                             sleep=waits.append, emit=lambda _: None)
    assert waits == [60]
    assert any("max(id)" in sql for sql, _ in connection.queries)


def test_pricing_gate_stops_at_deadline_when_upstream_failed():
    from etl.daily_pricing_update import wait_for_pricing_sources
    failed = ready_rows()
    failed[0]['status'] = 'failed'
    with pytest.raises(RuntimeError, match="pricing sources not ready"):
        wait_for_pricing_sources(PricingConnection([failed]), SchemaConfig('local','etl_datasync','dwd','pricing'),
                                 date(2026,10,14), now=lambda: datetime(2026,10,14,9,30),
                                 sleep=lambda _: pytest.fail('should stop at deadline'), emit=lambda _: None)


def test_snapshot_ready_before_eight_is_not_blocked_by_stale_legacy_snapshot_log():
    from etl.daily_pricing_update import wait_for_pricing_sources
    rows = ready_rows()
    rows[1]['end_time'] = datetime(2026, 10, 13, 10)
    conn = PricingConnection([rows])
    wait_for_pricing_sources(conn, SchemaConfig('local', 'etl_datasync', 'dwd', 'pricing'),
                             date(2026, 10, 14), now=lambda: datetime(2026, 10, 14, 9, 40),
                             sleep=lambda _: pytest.fail('already ready'), emit=lambda _: None)
    assert any('每日快照_执行日志' in sql for sql, _ in conn.queries)
    legacy_params = next(params for sql, params in conn.queries if 'etl_execution_log' in sql)
    assert 'proc_在库节点_输出定价表_每日快照' not in legacy_params
    snapshot_sql = next(sql for sql, _ in conn.queries if '每日快照_执行日志' in sql)
    assert '`pricing`.' in snapshot_sql
    assert 'ORDER BY `日志ID` DESC LIMIT 1' in snapshot_sql


@pytest.mark.parametrize('procedures', [
    ('proc_在库节点_输出定价表_每日快照',), ('proc_lx_sale_adjust_price_queue',),
])
def test_pricing_gate_checks_only_requested_dependencies(procedures):
    from etl.daily_pricing_update import wait_for_pricing_sources
    conn = PricingConnection([ready_rows()])
    wait_for_pricing_sources(conn, SchemaConfig('local', 'etl_datasync', 'dwd', 'pricing'),
                             date(2026, 10, 14), procedures=procedures,
                             sleep=lambda _: pytest.fail('already ready'), emit=lambda _: None)
    snapshot_requested = 'proc_在库节点_输出定价表_每日快照' in procedures
    assert any('每日快照_执行日志' in sql for sql, _ in conn.queries) == snapshot_requested
    assert any('etl_execution_log' in sql for sql, _ in conn.queries) != snapshot_requested


@pytest.mark.parametrize('snapshot', [
    {}, snapshot_row(status='running'), snapshot_row(status='failed'),
    snapshot_row(end_time=None), snapshot_row(end_time=datetime(2026, 10, 13, 7, 44)),
    snapshot_row(source_date=date(2026, 10, 13)), snapshot_row(source_rows=0),
    snapshot_row(written_rows=11), snapshot_row(verified_rows=11),
])
def test_old_success_log_cannot_override_missing_or_incomplete_snapshot(snapshot):
    from etl.daily_pricing_update import wait_for_pricing_sources
    with pytest.raises(RuntimeError, match='pricing sources not ready'):
        wait_for_pricing_sources(PricingConnection([ready_rows()], snapshot=snapshot),
                                 SchemaConfig('local', 'etl_datasync', 'dwd', 'pricing'),
                                 date(2026, 10, 14), now=lambda: datetime(2026, 10, 14, 9, 30),
                                 sleep=lambda _: pytest.fail('deadline'), emit=lambda _: None)


@pytest.mark.parametrize('counts', [
    {'source_rows': 12, 'source_day_rows': 0, 'snapshot_rows': 12},
    {'source_rows': 13, 'source_day_rows': 12, 'snapshot_rows': 12},
    {'source_rows': 12, 'source_day_rows': 12, 'snapshot_rows': 11},
    {'source_rows': 13, 'source_day_rows': 13, 'snapshot_rows': 13},
])
def test_snapshot_success_requires_matching_physical_data(counts):
    from etl.daily_pricing_update import wait_for_pricing_sources
    with pytest.raises(RuntimeError, match='pricing sources not ready'):
        wait_for_pricing_sources(PricingConnection([ready_rows()], counts=counts),
                                 SchemaConfig('local', 'etl_datasync', 'dwd', 'pricing'),
                                 date(2026, 10, 14), now=lambda: datetime(2026, 10, 14, 9, 30),
                                 sleep=lambda _: pytest.fail('deadline'), emit=lambda _: None)


def test_pricing_dry_run_does_not_connect_or_wait(monkeypatch):
    from etl import daily_pricing_update
    monkeypatch.setattr(daily_pricing_update, 'connect_source',
                        lambda: pytest.fail('dry-run must not connect'))
    assert daily_pricing_update.main(['--dry-run', '--snapshot-date', '2026-10-14']) == 0


def test_pricing_runs_independent_work_before_original_complete_source_barrier(monkeypatch):
    from etl import daily_pricing_update as pricing
    events = []

    class Connection:
        def close(self):
            events.append(('close',))

    monkeypatch.setattr(pricing, 'connect_source', Connection)
    monkeypatch.setattr(pricing, 'wait_for_pricing_sources',
                        lambda conn, schemas, day, **kw: events.append(
                            ('wait', tuple(kw['procedures']), day)))
    monkeypatch.setattr(pricing.subprocess, 'call',
                        lambda command: events.append(
                            ('run', command[command.index('--steps') + 1])) or 0)
    assert pricing.main(['--snapshot-date', '2026-10-16']) == 0
    runs = [event[1].split(',') for event in events if event[0] == 'run']
    assert [name for group in runs for name in group] == pricing.PRICING_STEPS.split(',')
    assert runs[0][-1] == 'inventory_weekly_remote_snapshot'
    assert runs[1][0] == 'limit_price_snapshot'
    assert runs[1][-2:] == ['price_review_source_load', 'price_review_tracking']
    assert events == [
        ('run', ','.join(runs[0])),
        ('wait', pricing.PRICING_PROCEDURES, date(2026, 10, 16)), ('close',),
        ('run', ','.join(runs[1])),
    ]


@pytest.mark.parametrize('failed_phase', [0, 1])
def test_pricing_phase_failure_stops_later_work(monkeypatch, failed_phase):
    from etl import daily_pricing_update as pricing
    commands = []
    class Connection:
        def close(self):
            pass
    monkeypatch.setattr(pricing, 'connect_source', Connection)
    monkeypatch.setattr(pricing, 'wait_for_pricing_sources', lambda *a, **kw: None)
    def execute(command):
        commands.append(command)
        return 9 if len(commands) - 1 == failed_phase else 0
    monkeypatch.setattr(pricing.subprocess, 'call', execute)
    assert pricing.main([]) == 9
    assert len(commands) == failed_phase + 1


def test_incomplete_source_gate_prevents_limit_prices_and_dependents(monkeypatch):
    from etl import daily_pricing_update as pricing
    commands, closed = [], []
    class Connection:
        def close(self):
            closed.append(True)
    def unavailable(*args, **kwargs):
        raise RuntimeError('daily snapshot still running')
    monkeypatch.setattr(pricing, 'connect_source', Connection)
    monkeypatch.setattr(pricing, 'wait_for_pricing_sources', unavailable)
    monkeypatch.setattr(pricing.subprocess, 'call', lambda command: commands.append(command) or 0)
    with pytest.raises(RuntimeError, match='still running'):
        pricing.main([])
    assert len(commands) == 1
    assert 'limit_price_snapshot' not in commands[0][commands[0].index('--steps') + 1].split(',')
    assert closed == [True]
