"""Retired label jobs must not appear in future daily run plans or reports."""
from datetime import datetime
from pathlib import Path
import json
import subprocess
import sys

import pytest

from etl import daily_update_runner as runner


MODULES = (
    'etl.dashboard_source_preflight', 'etl.dashboard_daily_update',
    'etl.replenishment_update', 'etl.replenishment_tracking_summary_update',
    'etl.product_performance_history_sync', 'etl.sales_role_snapshot_update',
    'etl.return_goods_update', 'etl.daily_pricing_update',
    'etl.return_goods_strategy_update',
)
KEYS = ('source_preflight','dashboard','replenishment','replenishment_tracking',
        'product_history','sales_role','return_goods','pricing','return_strategy')


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('frozen', [False, True])
def test_daily_plan_has_nine_real_steps_even_if_freeze_policy_changes(tmp_path, monkeypatch, parallel, frozen):
    monkeypatch.setattr(runner.label_update_policy,'LABEL_UPDATES_FROZEN',frozen)
    commands, notices, output = [], [], []
    result = runner.run_daily_update(
        project_root=tmp_path, parallel_pricing=parallel,
        step_executor=lambda command,*_: commands.append(command[2]) or 0,
        notifier=notices.append, emit=output.append,
        now=lambda:datetime(2026,10,21,8),
    )
    assert result.exit_code == 0
    assert tuple(r.step.module for r in result.step_results) == MODULES
    assert all(r.status=='success' for r in result.step_results)
    assert set(commands)==set(MODULES) and len(commands)==9
    assert '步骤数量：9' in output
    report=json.loads((tmp_path/'logs'/'etl_run_summary_20261021_080000.json').read_text(encoding='utf-8'))
    assert len(report['steps'])==9
    assert [(n.status,n.stage) for n in notices]==[('success','replenishment'),('success','all')]


def test_nine_step_notification_renders_without_retired_log_paths(tmp_path):
    logs=runner.DailyLogPaths({key:runner.StepLogPaths(tmp_path/(key+'.log'),tmp_path/(key+'.err')) for key in KEYS})
    project=Path(__file__).resolve().parents[1]
    command=runner.build_notification_command(
        runner.NotificationRequest('success','all',0,'20261021_080000'),
        python_executable=sys.executable,project_root=project,logs=logs,
    )
    assert '--label-evidence-stdout' not in command
    assert '--stockout-stdout' not in command
    assert '--label-analysis-stdout' not in command
    # The real file-only notification renderer runs, with transmission disabled.
    completed=subprocess.run([*command,'--dry-run'],capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert completed.returncode==0,completed.stderr
    assert '标签证据 ETL' not in completed.stdout


def test_notification_keeps_compatibility_with_an_already_running_twelve_step_run(tmp_path):
    logs=runner.build_log_paths(tmp_path,'20261020_165840')
    for key in ('label_evidence','stockout_historical_operating','label_analysis'):
        logs.by_step[key]=runner.StepLogPaths(tmp_path/(key+'.log'),tmp_path/(key+'.err'))
    command=runner.build_notification_command(
        runner.NotificationRequest('success','all',0,'20261020_165840'),
        python_executable=sys.executable,project_root=Path(__file__).resolve().parents[1],logs=logs,
    )
    assert '--label-evidence-stdout' in command
    assert '--stockout-stdout' in command
    assert '--label-analysis-stdout' in command
    rendered=subprocess.run([*command,'--dry-run'],capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert rendered.returncode==0,rendered.stderr
