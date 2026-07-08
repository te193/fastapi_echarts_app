from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_update_task.ps1"


def test_daily_update_task_runs_dashboard_replenishment_and_return_goods_etl_in_order():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-m etl.dashboard_source_preflight" in script
    assert "-m etl.dashboard_daily_update" in script
    assert "-m etl.replenishment_update" in script
    assert "-m etl.replenishment_tracking_update" not in script
    assert "-m etl.return_goods_update" in script
    assert (
        script.index("-m etl.dashboard_source_preflight")
        < script.index("-m etl.dashboard_daily_update")
        < script.index("-m etl.replenishment_update")
        < script.index("-m etl.return_goods_update")
    )
    assert "Replenishment tracking ETL is temporarily skipped." in script


def test_daily_update_task_writes_separate_replenishment_logs():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "etl_source_preflight_run_$RunStamp.log" in script
    assert "etl_source_preflight_run_$RunStamp.err.log" in script
    assert "etl_replenishment_run_$RunStamp.log" in script
    assert "etl_replenishment_run_$RunStamp.err.log" in script
    assert "etl_replenishment_tracking_run_$RunStamp.log" not in script
    assert "etl_replenishment_tracking_run_$RunStamp.err.log" not in script
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
    assert '-Stage "replenishment_tracking"' not in script
    assert '-Stage "return_goods"' in script
    assert '"--preflight-stdout", $PreflightStdoutLog' in script
    assert '"--preflight-stderr", $PreflightStderrLog' in script
    assert '"--tracking-stdout", $ReplenishmentTrackingStdoutLog' not in script
    assert '"--tracking-stderr", $ReplenishmentTrackingStderrLog' not in script
    assert '"--return-goods-stdout", $ReturnGoodsStdoutLog' in script
    assert '"--return-goods-stderr", $ReturnGoodsStderrLog' in script


def test_dingtalk_notification_does_not_replace_etl_exit_code():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "$PreviousNativeExitCode = $global:LASTEXITCODE" in script
    assert "$global:LASTEXITCODE = $PreviousNativeExitCode" in script
