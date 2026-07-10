import json

from scripts.notify_daily_task_dingtalk import build_markdown


def test_failure_markdown_summarizes_traceback_noise_to_business_reason(tmp_path):
    stderr_log = tmp_path / "dashboard.err.log"
    stderr_log.write_text(
        "\n".join(
            [
                "python.exe : [warn] product_performance_daily: source load attempt 1/2 failed; reconnecting source and retrying.",
                "所在位置 D:\\py_code\\看板搭建\\fastapi_echarts_app\\scripts\\run_daily_update_task.ps1:74 字符: 1",
                "+ & $PythonExe -m etl.dashboard_daily_update @args > $StdoutLog 2> $StdoutLog",
                "    + CategoryInfo          : NotSpecified: ([warn] product_...e and retrying.:String) [], RemoteException",
                "    + FullyQualifiedErrorId : NativeCommandError",
                "[failed] product_performance_daily",
                "Traceback (most recent call last):",
                "  File \"<frozen runpy>\", line 198, in _run_module_as_main",
                "RuntimeError: Business result validation failed: product_performance_daily biz_date=2026-06-29 has 0 rows. The remote p",
                "roduct-performance source is not ready.",
            ]
        ),
        encoding="utf-8",
    )
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "\n".join(
            [
                "Dashboard daily ETL plan",
                "  biz_date      : 2026-06-29",
                "  snapshot_date : 2026-06-30",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed",
        stage="dashboard",
        exit_code=1,
        run_stamp="20260630_090002",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=stderr_log,
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert (
        "Business result validation failed: product_performance_daily biz_date=2026-06-29 "
        "has 0 rows. The remote product-performance source is not ready."
    ) in text
    assert "Traceback" not in text
    assert "所在位置" not in text
    assert "CategoryInfo" not in text
    assert "source load attempt" not in text


def test_failure_markdown_omits_log_paths(tmp_path):
    stderr_log = tmp_path / "dashboard.err.log"
    stderr_log.write_text(
        "RuntimeError: Business result validation failed: product_performance_daily biz_date=2026-06-29 has 0 rows.",
        encoding="utf-8",
    )
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "Dashboard daily ETL plan\n  biz_date      : 2026-06-29\n  snapshot_date : 2026-06-30\n",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed",
        stage="dashboard",
        exit_code=1,
        run_stamp="20260630_090002",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=stderr_log,
        replenishment_stdout=tmp_path / "logs" / "not-created-replenishment.log",
        replenishment_stderr=tmp_path / "logs" / "not-created-replenishment.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "#### 日志" not in text
    assert "logs\\" not in text
    assert "not-created" not in text
