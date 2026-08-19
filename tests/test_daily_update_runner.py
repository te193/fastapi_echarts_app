from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys

from etl import daily_update_runner as runner


EXPECTED_MODULES = [
    "etl.dashboard_source_preflight",
    "etl.dashboard_daily_update",
    "etl.product_performance_history_sync",
    "etl.sales_role_snapshot_update",
    "etl.label_rule_evidence_snapshot_update",
    "etl.replenishment_update",
    "etl.replenishment_tracking_summary_update",
    "etl.return_goods_update",
]


def _fake_executor(exit_codes=None, commands=None):
    exit_codes = exit_codes or {}
    commands = commands if commands is not None else []

    def execute(command, stdout_path, stderr_path, emit):
        commands.append(tuple(command))
        stdout_path.write_text(f"ran {command[2]}\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        emit(f"child output: {command[2]}")
        return exit_codes.get(command[2], 0)

    return execute


def test_default_steps_match_daily_chain():
    assert [step.module for step in runner.DEFAULT_STEPS] == EXPECTED_MODULES
    assert runner.DEFAULT_STEPS[4].continue_on_failure is True
    assert all(
        not step.continue_on_failure
        for index, step in enumerate(runner.DEFAULT_STEPS)
        if index != 4
    )


def test_parse_args_keeps_all_etl_arguments():
    options = runner.parse_args(["--dry-run", "--biz-date", "2026-08-03"])

    assert options.dry_run is True
    assert options.etl_args == ("--dry-run", "--biz-date", "2026-08-03")


def test_load_dashboard_environment_uses_local_override_without_replacing_external_env(
    tmp_path,
    monkeypatch,
):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "dashboard_env.ps1").write_text(
        '$env:DASHBOARD_DB_HOST = "base-host"\n'
        '$env:DASHBOARD_DB_USER = "base-user"\n',
        encoding="utf-8",
    )
    (scripts_dir / "dashboard_env.local.ps1").write_text(
        '$env:DASHBOARD_DB_HOST = "local-host"\n'
        '$env:DASHBOARD_DINGTALK_SECRET = "local-secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_DB_USER", "external-user")
    monkeypatch.delenv("DASHBOARD_DB_HOST", raising=False)
    monkeypatch.delenv("DASHBOARD_DINGTALK_SECRET", raising=False)

    runner.load_dashboard_environment(tmp_path)

    assert os.environ["DASHBOARD_DB_HOST"] == "local-host"
    assert os.environ["DASHBOARD_DB_USER"] == "external-user"
    assert os.environ["DASHBOARD_DINGTALK_SECRET"] == "local-secret"


def test_success_runs_every_step_with_current_python_and_sends_success(tmp_path):
    commands = []
    notifications = []

    result = runner.run_daily_update(
        project_root=tmp_path,
        etl_args=("--biz-date", "2026-08-03"),
        python_executable=sys.executable,
        step_executor=_fake_executor(commands=commands),
        notifier=lambda request: notifications.append(request),
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=lambda message: None,
    )

    assert result.exit_code == 0
    assert [command[2] for command in commands] == EXPECTED_MODULES
    assert all(command[:2] == (sys.executable, "-m") for command in commands)
    assert all(command[3:] == ("--biz-date", "2026-08-03") for command in commands)
    assert [item.status for item in notifications] == ["success"]
    assert notifications[0].stage == "all"
    assert notifications[0].run_stamp == "20260804_090000"


def test_required_step_failure_stops_chain_and_returns_original_exit_code(tmp_path):
    commands = []
    notifications = []

    result = runner.run_daily_update(
        project_root=tmp_path,
        step_executor=_fake_executor(
            {"etl.replenishment_update": 7},
            commands,
        ),
        notifier=lambda request: notifications.append(request),
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=lambda message: None,
    )

    assert result.exit_code == 7
    assert [command[2] for command in commands] == EXPECTED_MODULES[:6]
    assert [item.status for item in notifications] == ["failed"]
    assert notifications[0].stage == "replenishment"
    assert notifications[0].exit_code == 7


def test_label_evidence_failure_warns_and_continues_to_final_success(tmp_path):
    commands = []
    notifications = []

    result = runner.run_daily_update(
        project_root=tmp_path,
        step_executor=_fake_executor(
            {"etl.label_rule_evidence_snapshot_update": 3},
            commands,
        ),
        notifier=lambda request: notifications.append(request),
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=lambda message: None,
    )

    assert result.exit_code == 0
    assert [command[2] for command in commands] == EXPECTED_MODULES
    assert [(item.status, item.stage) for item in notifications] == [
        ("failed", "label_evidence"),
        ("success", "all"),
    ]
    assert result.step_results[4].status == "warning"


def test_dry_run_passes_argument_and_skips_all_notifications(tmp_path):
    commands = []
    notifications = []

    result = runner.run_daily_update(
        project_root=tmp_path,
        etl_args=("--dry-run",),
        dry_run=True,
        step_executor=_fake_executor(commands=commands),
        notifier=lambda request: notifications.append(request),
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=lambda message: None,
    )

    assert result.exit_code == 0
    assert all(command[-1] == "--dry-run" for command in commands)
    assert notifications == []


def test_notification_failure_does_not_replace_successful_etl_result(tmp_path):
    output = []

    def broken_notifier(request):
        raise RuntimeError("notification unavailable")

    result = runner.run_daily_update(
        project_root=tmp_path,
        step_executor=_fake_executor(),
        notifier=broken_notifier,
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=output.append,
    )

    assert result.exit_code == 0
    assert any("notification unavailable" in line for line in output)


def test_progress_output_contains_step_numbers_status_and_summary(tmp_path):
    output = []

    result = runner.run_daily_update(
        project_root=tmp_path,
        step_executor=_fake_executor(),
        notifier=lambda request: None,
        now=lambda: datetime(2026, 8, 4, 9, 0, 0),
        monotonic=_incrementing_clock(),
        emit=output.append,
    )

    text = "\n".join(output)
    assert result.exit_code == 0
    assert "[1/8]" in text
    assert "远端数据完整性预检" in text
    assert "成功" in text
    assert "总耗时" in text
    assert "日志" in text


def test_notification_command_contains_all_daily_log_paths(tmp_path):
    logs = runner.build_log_paths(tmp_path, "20260804_090000")
    request = runner.NotificationRequest(
        status="failed",
        stage="replenishment_tracking",
        exit_code=2,
        run_stamp="20260804_090000",
        error_message="tracking failed",
    )

    command = runner.build_notification_command(
        request,
        python_executable=sys.executable,
        project_root=tmp_path,
        logs=logs,
    )
    command_text = " ".join(str(value) for value in command)

    assert command[:2] == [sys.executable, str(tmp_path / "scripts" / "notify_daily_task_dingtalk.py")]
    for option in (
        "--preflight-stdout",
        "--preflight-stderr",
        "--dashboard-stdout",
        "--dashboard-stderr",
        "--sales-role-stdout",
        "--sales-role-stderr",
        "--label-evidence-stdout",
        "--label-evidence-stderr",
        "--replenishment-stdout",
        "--replenishment-stderr",
        "--tracking-stdout",
        "--tracking-stderr",
        "--return-goods-stdout",
        "--return-goods-stderr",
    ):
        assert option in command
    assert "etl_replenishment_tracking_summary_run_20260804_090000.err.log" in command_text


def _incrementing_clock():
    value = -1.0

    def clock():
        nonlocal value
        value += 1.0
        return value

    return clock
