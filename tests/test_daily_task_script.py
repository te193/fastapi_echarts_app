from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_update_task.ps1"


def test_daily_update_task_prioritizes_replenishment_and_keeps_label_consumer_last():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-m etl.dashboard_source_preflight" in script
    assert "-m etl.dashboard_daily_update" in script
    assert "-m etl.product_performance_history_sync" in script
    assert "-m etl.sales_role_snapshot_update" in script
    assert "-m etl.stockout_historical_operating_update" in script
    assert "-m etl.replenishment_update" in script
    assert "-m etl.replenishment_tracking_summary_update" in script
    assert "-m etl.replenishment_tracking_update" not in script
    assert "-m etl.return_goods_update" in script
    assert (
        script.index("-m etl.dashboard_source_preflight")
        < script.index("-m etl.dashboard_daily_update")
        < script.index("-m etl.replenishment_update")
        < script.index("-m etl.replenishment_tracking_summary_update")
        < script.index("-m etl.product_performance_history_sync")
        < script.index("-m etl.sales_role_snapshot_update")
        < script.index("-m etl.return_goods_update")
        < script.index("-m etl.daily_pricing_update")
        < script.index("-m etl.label_rule_evidence_snapshot_update")
        < script.index("-m etl.stockout_historical_operating_update")
    )
    assert "Replenishment tracking ETL is temporarily skipped." not in script


def test_daily_update_task_writes_separate_tracking_summary_logs():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "etl_source_preflight_run_$RunStamp.log" in script
    assert "etl_source_preflight_run_$RunStamp.err.log" in script
    assert "etl_replenishment_run_$RunStamp.log" in script
    assert "etl_replenishment_run_$RunStamp.err.log" in script
    assert "etl_sales_role_run_$RunStamp.log" in script
    assert "etl_sales_role_run_$RunStamp.err.log" in script
    assert "etl_stockout_historical_operating_run_$RunStamp.log" in script
    assert "etl_stockout_historical_operating_run_$RunStamp.err.log" in script
    assert "etl_replenishment_tracking_summary_run_$RunStamp.log" in script
    assert "etl_replenishment_tracking_summary_run_$RunStamp.err.log" in script
    assert "etl_return_goods_run_$RunStamp.log" in script
    assert "etl_return_goods_run_$RunStamp.err.log" in script


def test_daily_update_task_sends_dingtalk_notifications():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "notify_daily_task_dingtalk.py" in script
    assert 'Send-DashboardDingTalkNotification -Status "success"' in script
    assert 'Send-DashboardDingTalkNotification -Status "failed"' in script
    assert '-Stage "source_preflight"' in script
    assert '-Stage "dashboard"' in script
    assert '-Stage "stockout_historical_operating"' in script
    assert '-Stage "replenishment"' in script
    assert '-Stage "replenishment_tracking"' in script
    assert '-Stage "return_goods"' in script
    assert '"--preflight-stdout", $PreflightStdoutLog' in script
    assert '"--preflight-stderr", $PreflightStderrLog' in script
    assert '"--tracking-stdout", $ReplenishmentTrackingStdoutLog' in script
    assert '"--tracking-stderr", $ReplenishmentTrackingStderrLog' in script
    assert '"--return-goods-stdout", $ReturnGoodsStdoutLog' in script
    assert '"--return-goods-stderr", $ReturnGoodsStderrLog' in script
    assert '"--sales-role-stdout", $SalesRoleStdoutLog' in script
    assert '"--sales-role-stderr", $SalesRoleStderrLog' in script
    assert '"--label-evidence-stdout", $LabelEvidenceStdoutLog' in script
    assert '"--label-evidence-stderr", $LabelEvidenceStderrLog' in script


def test_daily_update_task_keeps_dingtalk_notification_logs():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'dingtalk_notify_run_$RunStamp.log' in script
    assert 'dingtalk_notify_run_$RunStamp.err.log' in script
    assert "> $DingTalkStdoutLog 2> $DingTalkStderrLog" in script
    assert "& $PythonExe @NotifyArgs | Out-Null" not in script
    assert "See $DingTalkStdoutLog and $DingTalkStderrLog." in script


def test_dingtalk_notification_does_not_replace_etl_exit_code():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "$PreviousNativeExitCode = $global:LASTEXITCODE" in script
    assert "$global:LASTEXITCODE = $PreviousNativeExitCode" in script


def test_daily_update_dry_run_skips_dingtalk_transmission():
    script = SCRIPT.read_text(encoding="utf-8")

    assert '$IsDryRun = $args -contains "--dry-run"' in script
    assert "if ($IsDryRun)" in script
    assert "DingTalk notification skipped in dry-run mode." in script


def test_daily_update_filters_arguments_for_each_downstream_stage():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "function Select-DashboardTaskArguments" in script
    assert "& $PythonExe -m etl.sales_role_snapshot_update @SalesRoleArgs" in script
    assert "& $PythonExe -m etl.label_rule_evidence_snapshot_update @LabelEvidenceArgs" in script
    assert "& $PythonExe -m etl.stockout_historical_operating_update @StockoutHistoricalArgs" in script
    assert "& $PythonExe -m etl.replenishment_update @ReplenishmentArgs" in script
    assert "& $PythonExe -m etl.replenishment_tracking_summary_update @ReplenishmentTrackingArgs" in script
    assert "& $PythonExe -m etl.return_goods_update @ReturnGoodsArgs" in script
    assert '-ValueOptions @("--snapshot-date", "--period-end", "--periods")' in script
    assert '-ValueOptions @("--biz-date", "--data-date")' in script
    assert '-ValueOptions @("--cutoff-date")' in script


def test_daily_update_runs_label_evidence_after_return_goods_before_its_consumer():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-m etl.label_rule_evidence_snapshot_update" in script
    assert (
        script.index("-m etl.return_goods_update")
        < script.index("-m etl.label_rule_evidence_snapshot_update")
        < script.index("-m etl.stockout_historical_operating_update")
    )


def test_daily_update_uses_dedicated_label_evidence_logs_and_stage():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "etl_label_rule_evidence_run_$RunStamp.log" in script
    assert "etl_label_rule_evidence_run_$RunStamp.err.log" in script
    assert '-Stage "label_evidence"' in script
    assert "LabelEvidenceStdoutLog" in script
    assert "LabelEvidenceStderrLog" in script


def test_label_evidence_failure_stops_dependent_daily_stage():
    script = SCRIPT.read_text(encoding="utf-8")
    failure_block = script.split("if ($LabelEvidenceExitCode -ne 0) {", 1)[1].split("} else {", 1)[0]

    assert "Write-Error" in failure_block
    assert '-Status "failed" -Stage "label_evidence"' in failure_block
    assert "exit $LabelEvidenceExitCode" in failure_block
    assert script.index(failure_block) < script.index("-m etl.stockout_historical_operating_update")


def test_stockout_historical_failure_notifies_and_stops_daily_chain():
    script = SCRIPT.read_text(encoding="utf-8")
    failure_block = script.split("if ($StockoutHistoricalExitCode -ne 0) {", 1)[1].split("}", 1)[0]

    assert '-Status "failed" -Stage "stockout_historical_operating"' in failure_block
    assert "exit $StockoutHistoricalExitCode" in failure_block
    assert script.index("exit $StockoutHistoricalExitCode") > script.index("-m etl.replenishment_update")


@pytest.mark.skipif(os.name != "nt", reason="Windows task entry")
@pytest.mark.parametrize("failed_module", ["", "etl.label_rule_evidence_snapshot_update", "etl.replenishment_update", "etl.daily_pricing_update"])
def test_powershell_task_notifies_at_publication_boundaries_and_stops_on_failure(tmp_path, failed_module):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    task = scripts / SCRIPT.name
    shutil.copyfile(SCRIPT, task)
    stub = scripts / "task_child.py"
    trace = tmp_path / "events.jsonl"
    stub.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "event={'module':args[1]} if args[0]=='-m' else "
        "{'status':args[args.index('--status')+1],'stage':args[args.index('--stage')+1]}\n"
        "with Path(os.environ['TASK_TEST_TRACE']).open('a',encoding='utf-8') as f: f.write(json.dumps(event)+'\\n')\n"
        "sys.exit(7 if event.get('module')==os.environ['TASK_TEST_FAIL'] else 0)\n",
        encoding="utf-8",
    )
    launcher = scripts / "task_python.cmd"
    launcher.write_text(f'@"{sys.executable}" "{stub}" %*\n', encoding="utf-8")
    (scripts / "notify_daily_task_dingtalk.py").touch()
    (scripts / "dashboard_env.ps1").write_text(
        f"function Get-DashboardProjectRoot {{ '{str(tmp_path).replace(chr(39), chr(39)*2)}' }}\n"
        f"function Get-DashboardPython {{ '{str(launcher).replace(chr(39), chr(39)*2)}' }}\n",
        encoding="utf-8-sig",
    )
    env = os.environ.copy()
    env.update(TASK_TEST_TRACE=str(trace), TASK_TEST_FAIL=failed_module)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(task)],
                            env=env, capture_output=True, timeout=30)
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    modules = [e['module'] for e in events if 'module' in e]
    notices = [(e['status'],e['stage']) for e in events if 'stage' in e]
    expected = ["etl.dashboard_source_preflight", "etl.dashboard_daily_update", "etl.replenishment_update",
                "etl.replenishment_tracking_summary_update", "etl.product_performance_history_sync",
                "etl.sales_role_snapshot_update", "etl.return_goods_update", "etl.daily_pricing_update", "etl.label_rule_evidence_snapshot_update",
                "etl.stockout_historical_operating_update"]
    if failed_module:
        assert result.returncode == 7
        assert modules == expected[:expected.index(failed_module)+1]
        assert notices == ([("success", "replenishment")] if failed_module != "etl.replenishment_update" else []) + [
            ("failed", {"etl.label_rule_evidence_snapshot_update":"label_evidence",
                        "etl.daily_pricing_update":"pricing"}.get(failed_module,"replenishment"))]
    else:
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert modules == expected
        assert notices == [("success", "replenishment"), ("success", "all")]
        notice_index = events.index({'status':'success','stage':'replenishment'})
        assert events[notice_index-1] == {'module':'etl.replenishment_update'}
        assert events[notice_index+1] == {'module':'etl.replenishment_tracking_summary_update'}


def test_source_preflight_failure_notifies_and_exits_before_dashboard_etl():
    script = SCRIPT.read_text(encoding="utf-8")
    failure_block = script.split("if ($PreflightExitCode -ne 0) {", 1)[1].split("}", 1)[0]

    assert '-Status "failed" -Stage "source_preflight"' in failure_block
    assert "exit $PreflightExitCode" in failure_block
    assert script.index("exit $PreflightExitCode") < script.index("-m etl.dashboard_daily_update")
