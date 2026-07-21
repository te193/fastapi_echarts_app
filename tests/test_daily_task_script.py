from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_update_task.ps1"


def test_daily_update_task_runs_tracking_summary_between_replenishment_and_return_goods():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-m etl.dashboard_source_preflight" in script
    assert "-m etl.dashboard_daily_update" in script
    assert "-m etl.sales_role_snapshot_update" in script
    assert "-m etl.replenishment_update" in script
    assert "-m etl.replenishment_tracking_summary_update" in script
    assert "-m etl.replenishment_tracking_update" not in script
    assert "-m etl.return_goods_update" in script
    assert (
        script.index("-m etl.dashboard_source_preflight")
        < script.index("-m etl.dashboard_daily_update")
        < script.index("-m etl.sales_role_snapshot_update")
        < script.index("-m etl.replenishment_update")
        < script.index("-m etl.replenishment_tracking_summary_update")
        < script.index("-m etl.return_goods_update")
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
    assert '-Stage "replenishment"' in script
    assert '-Stage "replenishment_tracking"' in script
    assert '-Stage "return_goods"' in script
    assert '"--preflight-stdout", $PreflightStdoutLog' in script
    assert '"--preflight-stderr", $PreflightStderrLog' in script
    assert '"--tracking-stdout", $ReplenishmentTrackingStdoutLog' in script
    assert '"--tracking-stderr", $ReplenishmentTrackingStderrLog' in script
    assert '"--return-goods-stdout", $ReturnGoodsStdoutLog' in script
    assert '"--return-goods-stderr", $ReturnGoodsStderrLog' in script


def test_dingtalk_notification_does_not_replace_etl_exit_code():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "$PreviousNativeExitCode = $global:LASTEXITCODE" in script
    assert "$global:LASTEXITCODE = $PreviousNativeExitCode" in script


def test_daily_update_dry_run_skips_dingtalk_transmission():
    script = SCRIPT.read_text(encoding="utf-8")

    assert '$IsDryRun = $args -contains "--dry-run"' in script
    assert "if ($IsDryRun)" in script
    assert "DingTalk notification skipped in dry-run mode." in script


def test_daily_update_runs_label_evidence_after_sales_role_before_replenishment():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-m etl.label_rule_evidence_snapshot_update" in script
    assert (
        script.index("-m etl.sales_role_snapshot_update")
        < script.index("-m etl.label_rule_evidence_snapshot_update")
        < script.index("-m etl.replenishment_update")
    )


def test_daily_update_uses_dedicated_label_evidence_logs_and_stage():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "etl_label_rule_evidence_run_$RunStamp.log" in script
    assert "etl_label_rule_evidence_run_$RunStamp.err.log" in script
    assert '-Stage "label_evidence"' in script
    assert "LabelEvidenceStdoutLog" in script
    assert "LabelEvidenceStderrLog" in script


def test_label_evidence_failure_warns_and_continues_daily_chain():
    script = SCRIPT.read_text(encoding="utf-8")
    failure_block = script.split("if ($LabelEvidenceExitCode -ne 0) {", 1)[1].split("} else {", 1)[0]

    assert "Write-Warning" in failure_block
    assert '-Status "failed" -Stage "label_evidence"' in failure_block
    assert "exit $LabelEvidenceExitCode" not in failure_block
    assert script.index(failure_block) < script.index("-m etl.replenishment_update")


def test_source_preflight_failure_notifies_and_exits_before_dashboard_etl():
    script = SCRIPT.read_text(encoding="utf-8")
    failure_block = script.split("if ($PreflightExitCode -ne 0) {", 1)[1].split("}", 1)[0]

    assert '-Status "failed" -Stage "source_preflight"' in failure_block
    assert "exit $PreflightExitCode" in failure_block
    assert script.index("exit $PreflightExitCode") < script.index("-m etl.dashboard_daily_update")
