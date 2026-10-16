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
    def __init__(self, batches):
        self.batches = iter(batches)
        self.query = ""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.query = sql
        self.params = params

    def fetchall(self):
        return next(self.batches)


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
    assert "max(id)" in connection.query


def test_pricing_gate_stops_at_deadline_when_upstream_failed():
    from etl.daily_pricing_update import wait_for_pricing_sources
    failed = ready_rows()
    failed[1]['status'] = 'failed'
    with pytest.raises(RuntimeError, match="pricing sources not ready"):
        wait_for_pricing_sources(PricingConnection([failed]), SchemaConfig('local','etl_datasync','dwd','pricing'),
                                 date(2026,10,14), now=lambda: datetime(2026,10,14,9,30),
                                 sleep=lambda _: pytest.fail('should stop at deadline'), emit=lambda _: None)


def test_pricing_dry_run_does_not_connect_or_wait(monkeypatch):
    from etl import daily_pricing_update
    monkeypatch.setattr(daily_pricing_update, 'connect_source',
                        lambda: pytest.fail('dry-run must not connect'))
    assert daily_pricing_update.main(['--dry-run', '--snapshot-date', '2026-10-14']) == 0
