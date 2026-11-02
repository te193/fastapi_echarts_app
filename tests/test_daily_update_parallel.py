from datetime import datetime
from threading import Event, Lock

import pytest

from etl import daily_update_runner as runner




def test_cli_enables_parallel_pricing_and_removes_serial_control_from_child_args():
    assert runner.parse_args([]).parallel_pricing is True
    options = runner.parse_args(['--serial', '--dry-run', '--snapshot-date=2026-10-16'])
    assert options.parallel_pricing is False
    assert options.etl_args == ('--dry-run', '--snapshot-date=2026-10-16')


def test_real_acceptance_can_disable_messages_without_disabling_database_updates(tmp_path):
    options = runner.parse_args(['--no-notify', '--biz-date', '2026-10-15'])
    assert options.notifications_enabled is False
    assert options.etl_args == ('--biz-date', '2026-10-15')
    commands, notifications = [], []
    result = runner.run_daily_update(
        project_root=tmp_path, notifications_enabled=False,
        step_executor=lambda command, *_: commands.append(command) or 0,
        notifier=notifications.append, emit=lambda _: None,
    )
    assert result.exit_code == 0
    assert all('--dry-run' not in command for command in commands)
    assert notifications == []


@pytest.mark.parametrize('exit_code', [0, 7])
def test_real_run_persists_wall_time_step_results_and_console_log(tmp_path, exit_code):
    import json
    def execute(command, out, err, emit):
        emit('real child progress')
        return exit_code if command[2] == 'etl.replenishment_update' else 0
    result = runner.run_daily_update(
        project_root=tmp_path, step_executor=execute, notifications_enabled=False,
        now=lambda: datetime(2026, 10, 16, 18, 20), emit=lambda _: None,
    )
    folder = tmp_path / 'logs'
    summary = json.loads((folder / 'etl_run_summary_20261016_182000.json').read_text(encoding='utf-8'))
    assert summary['exit_code'] == exit_code == result.exit_code
    assert summary['dry_run'] is False
    assert summary['notifications_enabled'] is False
    assert summary['elapsed_seconds'] >= 0
    assert summary['steps'][2]['exit_code'] == exit_code
    assert summary['steps'][2]['started_at'] and summary['steps'][2]['finished_at']
    assert 'real child progress' in (folder / 'etl_orchestrator_run_20261016_182000.log').read_text(encoding='utf-8')


def test_parallel_pricing_overlaps_roles_but_strategy_waits_for_both_branches(tmp_path):
    pricing_started, roles_started, pricing_done, returns_done = (Event() for _ in range(4))
    events = []
    lock = Lock()
    def execute(command, out, err, emit):
        module = command[2]
        with lock:
            events.append(module)
        if module == 'etl.daily_pricing_update':
            pricing_started.set()
            assert roles_started.wait(3), 'pricing and roles must overlap'
            assert returns_done.wait(3), 'return goods must run while pricing is running'
            pricing_done.set()
        elif module == 'etl.sales_role_snapshot_update':
            roles_started.set()
            assert pricing_started.wait(3)
        elif module == 'etl.return_goods_update':
            returns_done.set()
        elif module == 'etl.return_goods_strategy_update':
            assert pricing_done.is_set() and returns_done.is_set()
        return 0
    result = runner.run_daily_update(
        project_root=tmp_path, parallel_pricing=True, step_executor=execute,
        notifier=lambda _: None, emit=lambda _: None,
    )
    assert result.exit_code == 0
    assert events[:5] == [s.module for s in runner.DEFAULT_STEPS[:5]]
    assert sorted(events) == sorted(s.module for s in runner.DEFAULT_STEPS)
    assert [r.step.key for r in result.step_results] == [s.key for s in runner.DEFAULT_STEPS]


@pytest.mark.parametrize('failed_module', ['etl.daily_pricing_update', 'etl.sales_role_snapshot_update',
                                         'etl.return_goods_update'])
def test_parallel_failure_drains_running_work_and_blocks_return_strategy(tmp_path, failed_module):
    pricing_started, roles_started, pricing_done = (Event() for _ in range(3))
    notifications, modules = [], []
    def execute(command, out, err, emit):
        module = command[2]
        modules.append(module)
        if module == 'etl.daily_pricing_update':
            pricing_started.set()
            assert roles_started.wait(3)
            pricing_done.set()
        if module == 'etl.sales_role_snapshot_update':
            roles_started.set()
            assert pricing_started.wait(3)
        return 7 if module == failed_module else 0
    result = runner.run_daily_update(
        project_root=tmp_path, parallel_pricing=True, step_executor=execute,
        notifier=notifications.append, emit=lambda _: None,
    )
    assert result.exit_code == 7
    assert pricing_done.is_set()
    assert 'etl.return_goods_strategy_update' not in modules
    assert not any(n.stage == 'all' for n in notifications)
    assert any(n.status == 'failed' for n in notifications)
    if failed_module == 'etl.sales_role_snapshot_update':
        assert 'etl.return_goods_update' not in modules


def test_parallel_mode_never_moves_pricing_ahead_of_history_or_early_failure(tmp_path):
    modules = []
    def execute(command, out, err, emit):
        modules.append(command[2])
        return 8 if command[2] == 'etl.product_performance_history_sync' else 0
    result = runner.run_daily_update(
        project_root=tmp_path, parallel_pricing=True, step_executor=execute,
        notifier=lambda _: None, emit=lambda _: None,
    )
    assert result.exit_code == 8
    assert modules == [s.module for s in runner.DEFAULT_STEPS[:5]]


def test_parallel_flag_preserves_custom_step_order(tmp_path):
    modules = []
    custom_steps = tuple(s for s in runner.DEFAULT_STEPS if s.key in ('product_history', 'pricing', 'sales_role'))
    result = runner.run_daily_update(
        project_root=tmp_path, steps=custom_steps, parallel_pricing=True,
        step_executor=lambda command, *_: modules.append(command[2]) or 0,
        notifier=lambda _: None, emit=lambda _: None,
    )
    assert result.exit_code == 0
    assert modules == [s.module for s in custom_steps]


def test_dry_run_true_cannot_write_even_when_no_child_flag_was_supplied(tmp_path):
    commands, notifications = [], []
    result = runner.run_daily_update(
        project_root=tmp_path, dry_run=True, parallel_pricing=True,
        step_executor=lambda command, *_: commands.append(command) or 0,
        notifier=notifications.append, emit=lambda _: None,
    )
    assert result.exit_code == 0
    assert all('--dry-run' in command[3:] for command in commands)
    assert notifications == []


def test_runner_filters_arguments_like_the_scheduled_powershell_entry(tmp_path):
    commands = []
    runner.run_daily_update(
        project_root=tmp_path, dry_run=True,
        etl_args=('--snapshot-date', '2026-10-16', '--biz-date', '2026-10-15',
                  '--batch-size', '200', '--periods', '7d,14d,30d,90d', '--cutoff-date=2026-10-16'),
        step_executor=lambda command, *_: commands.append(command) or 0,
        emit=lambda _: None,
    )
    args = {c[2]: c[3:] for c in commands}
    assert args['etl.sales_role_snapshot_update'] == [
        '--snapshot-date', '2026-10-16', '--periods', '7d,14d,30d,90d', '--dry-run']
    assert args['etl.replenishment_tracking_summary_update'] == ['--cutoff-date=2026-10-16', '--dry-run']
    assert args['etl.return_goods_strategy_update'] == ['--snapshot-date', '2026-10-15', '--dry-run']


def test_runner_keeps_notification_stdout_and_stderr_logs(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, stdout='sent\n', stderr=''))
    logs = runner.build_log_paths(tmp_path, '20261016_080001')
    request = runner.NotificationRequest('success', 'replenishment', 0, '20261016_080001')
    runner.send_dingtalk_notification(request, python_executable='python', project_root=tmp_path, logs=logs)
    folder = tmp_path / 'logs'
    assert (folder / 'dingtalk_notify_run_20261016_080001_replenishment_success.log').read_text() == 'sent\n'
    assert (folder / 'dingtalk_notify_run_20261016_080001_replenishment_success.err.log').read_text() == ''
