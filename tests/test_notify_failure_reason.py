import json

import pytest

from scripts.notify_daily_task_dingtalk import build_markdown


@pytest.mark.parametrize(
    "stage,stage_label",
    [
        ("return_strategy", "返场品运营策略预计算"),
        ("label_analysis", "标签综合分析预计算"),
    ],
)
def test_new_stage_without_logs_uses_fallback_instead_of_dashboard(tmp_path, stage, stage_label):
    dashboard_err = tmp_path / "dashboard.err.log"
    dashboard_err.write_text("stale dashboard warning", encoding="utf-8")

    payload = build_markdown(
        status="failed", stage=stage, exit_code=9,
        run_stamp="20261016_080000", project_root=tmp_path,
        dashboard_stdout=tmp_path / "dashboard.log", dashboard_stderr=dashboard_err,
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        error_message="new stage failed without an error log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "new stage failed without an error log" in text
    assert "stale dashboard warning" not in text
    assert f"失败阶段：{stage_label}" in text
    assert "退出码：9" in text


@pytest.mark.parametrize(
    "stage,stage_label",
    [
        ("return_strategy", "返场品运营策略预计算"),
        ("label_analysis", "标签综合分析预计算"),
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_new_stage_failure_markdown_reads_its_own_exception(
    tmp_path, stage, stage_label, encoding,
):
    dashboard_err = tmp_path / "dashboard.err.log"
    dashboard_err.write_text("stale dashboard warning", encoding="utf-8")
    strategy_err = tmp_path / "return-strategy.err.log"
    analysis_err = tmp_path / "label-analysis.err.log"
    strategy_err.write_text(
        "Traceback (most recent call last):\nRuntimeError: strategy evaluation failed\n",
        encoding=encoding,
    )
    analysis_err.write_text(
        "Traceback (most recent call last):\nRuntimeError: analysis publication failed\n",
        encoding=encoding,
    )
    repl = tmp_path / "replenishment.log"
    repl.write_text(
        "[success] replenishment_business_result: snapshot_date=2026-10-16 rows=80\n",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed", stage=stage, exit_code=9,
        run_stamp="20261016_080000", project_root=tmp_path,
        dashboard_stdout=tmp_path / "dashboard.log", dashboard_stderr=dashboard_err,
        replenishment_stdout=repl, replenishment_stderr=tmp_path / "replenishment.err.log",
        return_strategy_stderr=strategy_err, label_analysis_stderr=analysis_err,
        error_message="generic failure fallback",
    )
    text = json.loads(payload)["markdown"]["text"]

    expected, other = (
        ("strategy evaluation failed", "analysis publication failed")
        if stage == "return_strategy"
        else ("analysis publication failed", "strategy evaluation failed")
    )
    assert expected in text
    assert other not in text
    assert "stale dashboard warning" not in text
    assert "generic failure fallback" not in text
    assert "Traceback" not in text
    assert f"失败阶段：{stage_label}" in text
    assert "退出码：9" in text
    assert "补货结果：已生成" in text


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


def test_failure_markdown_explains_label_date_mismatch(tmp_path):
    stderr_log = tmp_path / "stockout.err.log"
    stderr_log.write_text(
        "RuntimeError: latest source date mismatch: "
        "label=2026-09-16, performance=2026-09-17, inventory=2026-09-18",
        encoding="utf-8",
    )
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "Dashboard daily ETL plan\n"
        "  biz_date      : 2026-09-17\n"
        "  snapshot_date : 2026-09-18\n",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed",
        stage="stockout_historical_operating",
        exit_code=1,
        run_stamp="20260918_120000",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        stockout_stderr=stderr_log,
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "断货前历史经营结果 ETL" in text
    assert "标签证据到 2026-09-16" in text
    assert "先确认本地标签生成并发布到 2026-09-17" in text
    assert "Traceback" not in text
    assert "```text" not in text


def test_failure_markdown_explains_remote_connection_loss(tmp_path):
    stderr_log = tmp_path / "label.err.log"
    stderr_log.write_text(
        "pymysql.err.OperationalError: (2013, "
        "'Lost connection to MySQL server during query')\n"
        "AttributeError: 'NoneType' object has no attribute 'settimeout'",
        encoding="utf-8",
    )
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "Dashboard daily ETL plan\n"
        "  biz_date      : 2026-09-17\n"
        "  snapshot_date : 2026-09-18\n",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed",
        stage="label_evidence",
        exit_code=1,
        run_stamp="20260918_120000",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        label_evidence_stderr=stderr_log,
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "数据库连接中断" in text
    assert "检查业务源同步和本地标签生成日志" in text
    assert "等待远端标签表" not in text
    assert "AttributeError" not in text


def test_late_failure_keeps_successful_replenishment_in_report(tmp_path):
    repl = tmp_path / 'replenishment.log'
    repl.write_text('[success] replenishment_business_result: snapshot_date=2026-10-14 rows=80\n', encoding='utf-8')
    payload = build_markdown(status='failed', stage='pricing', exit_code=1,
        run_stamp='20261014_080000', project_root=tmp_path,
        dashboard_stdout=tmp_path/'dashboard.log', dashboard_stderr=tmp_path/'dashboard.err',
        replenishment_stdout=repl, replenishment_stderr=tmp_path/'replenishment.err',
        error_message='pricing sources not ready')
    text = json.loads(payload)['markdown']['text']
    assert '补货结果：已生成' in text
    assert '补货结果：未生成' not in text
