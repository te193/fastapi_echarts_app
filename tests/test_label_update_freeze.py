"""Frozen labels must not write, even through manual refresh or explicit steps."""
import importlib
import sys
import runpy

import pytest
from fastapi import HTTPException

from etl import daily_update_runner as runner


@pytest.mark.parametrize('parallel', [False, True])
def test_daily_run_excludes_frozen_labels_and_keeps_business_updates(tmp_path, parallel):
    modules, notices = [], []
    result = runner.run_daily_update(
        project_root=tmp_path, parallel_pricing=parallel,
        step_executor=lambda command, *_: modules.append(command[2]) or 0,
        notifier=notices.append, emit=lambda _: None,
    )
    assert result.exit_code == 0
    assert set(modules) == {
        'etl.dashboard_source_preflight', 'etl.dashboard_daily_update',
        'etl.replenishment_update', 'etl.replenishment_tracking_summary_update',
        'etl.product_performance_history_sync', 'etl.sales_role_snapshot_update',
        'etl.return_goods_update', 'etl.daily_pricing_update',
        'etl.return_goods_strategy_update',
    }
    assert len(result.step_results) == 9
    assert all(r.status == 'success' for r in result.step_results)
    assert [(n.status, n.stage) for n in notices] == [
        ('success', 'replenishment'), ('success', 'all'),
    ]


def test_explicit_label_step_cannot_bypass_freeze(tmp_path):
    modules = []
    result = runner.run_daily_update(
        project_root=tmp_path, steps=(runner.EtlStep(
            'label_analysis','Retired analysis','etl.label_analysis_refresh',
            'etl_label_analysis_run','label_analysis'),),
        step_executor=lambda command, *_: modules.append(command[2]) or 0,
        notifications_enabled=False, emit=lambda _: None,
    )
    assert modules == []
    assert result.step_results[0].status == 'skipped'


def test_manual_refresh_returns_freeze_reason_without_starting_generation(monkeypatch):
    from app.main import api_label_hub_refresh
    from etl import label_rule_evidence_snapshot_update as evidence
    attempts = []

    def generate(*args, **kwargs):
        attempts.append('generation')
        raise RuntimeError('generation must not start')

    monkeypatch.setattr(evidence, 'run_update', generate)
    with pytest.raises(HTTPException) as caught:
        api_label_hub_refresh()
    assert caught.value.status_code == 409
    assert '冻结' in caught.value.detail
    assert attempts == []


@pytest.mark.parametrize(('name', 'work'), [
    ('label_rule_evidence_snapshot_update', 'run_update'),
    ('label_local_generation', 'run_generation'),
    ('stockout_historical_operating_update', 'apply_database_ini_env'),
])
def test_manual_cli_stops_before_database_work(monkeypatch, capsys, name, work):
    module = importlib.import_module('etl.' + name)
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(work)
        raise RuntimeError('database work must not start')

    monkeypatch.setattr(module, work, forbidden)
    monkeypatch.setattr(sys, 'argv', [name])
    try:
        module.main()
    except RuntimeError:
        pass
    assert attempts == []
    assert '冻结' in capsys.readouterr().out


def test_analysis_cli_cannot_start_workers_or_publish(monkeypatch, capsys):
    from etl import label_analysis_bounded_refresh as bounded
    attempts = []
    monkeypatch.setattr(bounded, 'refresh_bounded', lambda *a, **kw: attempts.append('refresh'))
    monkeypatch.setattr(sys, 'argv', ['label_analysis_refresh'])
    monkeypatch.delitem(sys.modules, 'etl.label_analysis_refresh', raising=False)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module('etl.label_analysis_refresh', run_name='__main__')
    assert stopped.value.code == 0
    assert attempts == []
    assert '冻结' in capsys.readouterr().out
