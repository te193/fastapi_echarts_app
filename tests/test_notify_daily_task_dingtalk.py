import json
import os
from pathlib import Path

from scripts.notify_daily_task_dingtalk import build_markdown, build_signed_webhook


def test_build_signed_webhook_adds_timestamp_and_signature():
    url = build_signed_webhook(
        "https://oapi.dingtalk.com/robot/send?access_token=abc",
        "SECtest",
        timestamp_ms=1234567890,
    )

    assert "access_token=abc" in url
    assert "timestamp=1234567890" in url
    assert "sign=" in url


def test_build_success_markdown_uses_business_result_template(tmp_path):
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_err = tmp_path / "dashboard.err.log"
    replenishment_log = tmp_path / "replenishment.log"
    replenishment_err = tmp_path / "replenishment.err.log"
    dashboard_log.write_text(
        "\n".join(
            [
                "Dashboard daily ETL plan",
                "  biz_date      : 2026-06-23",
                "  snapshot_date : 2026-06-24",
                "  product_load  : 2026-05-05 to 2026-06-23",
                "  target_schema : etl_datasync_test",
                "  steps         : product_performance_daily, restock_snapshot, inventory_snapshot, listing_price_snapshot",
                "[success] product_performance_daily: affected_rows=907058",
                "[success] restock_snapshot: affected_rows=4573",
                "[success] inventory_snapshot: affected_rows=8124",
                "[success] listing_price_snapshot: affected_rows=61139",
                "[success] price_review_tracking: affected_rows=13909",
            ]
        ),
        encoding="utf-8",
    )
    dashboard_err.write_text("", encoding="utf-8")
    replenishment_log.write_text(
        "\n".join(
            [
                "Replenishment local ETL plan",
                "  biz_date        : 2026-06-23",
                "  snapshot_date   : 2026-06-24",
                "  target_schema   : etl_datasync_test",
                "  steps           : replenishment",
                "[success] salable_days_stat: affected_rows=3210",
                "[success] replenishment_result: affected_rows=82827",
                "[success] country_metrics: affected_rows=61213",
            ]
        ),
        encoding="utf-8",
    )
    replenishment_err.write_text("", encoding="utf-8")
    os.utime(dashboard_err, (1_000_000_000, 1_000_000_000))
    os.utime(dashboard_log, (1_000_001_200, 1_000_001_200))
    os.utime(replenishment_err, (1_000_001_200, 1_000_001_200))
    os.utime(replenishment_log, (1_000_001_350, 1_000_001_350))

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260624_100000",
        project_root=Path("D:/app"),
        dashboard_stdout=dashboard_log,
        dashboard_stderr=dashboard_err,
        replenishment_stdout=replenishment_log,
        replenishment_stderr=replenishment_err,
    )
    data = json.loads(payload)

    assert data["msgtype"] == "markdown"
    text = data["markdown"]["text"]
    assert "看板定时任务执行成功" in text
    assert "执行耗时" in text
    assert "总耗时：约 23 分钟" in text
    assert "总 ETL：约 20 分钟" in text
    assert "补货 ETL：约 2 分半" in text
    assert "业务数据：2026-06-23" in text
    assert "快照数据：2026-06-24" in text
    assert "商品表现区间：2026-05-05 ~ 2026-06-23" in text
    assert "商品表现：已更新到 6月23日，当日约 90.7 万条" in text
    assert "库存快照：已更新到 6月24日，约 8,100 条" in text
    assert "补货建议快照：已更新到 6月24日，约 4,600 条" in text
    assert "Listing 价格：已更新到 6月24日，约 6.1 万条" in text
    assert "补货结果：已重新计算，约 3,200 个补货 SKU" in text
    assert "国家维度补货明细：已重新计算，约 6.1 万条" in text
    assert "价格复盘：已更新，约 1.4 万条结果" in text
    assert "数据健康" in text
    assert "远端源数据：已更新完整" in text
    assert "本地落库：成功" in text
    assert "错误日志：无" in text
    assert "dashboard_" not in text
    assert "结果明细" not in text


def test_success_markdown_does_not_dump_every_result_line(tmp_path):
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "\n".join(f"[success] step_{index}: affected_rows={index}" for index in range(1, 16)),
        encoding="utf-8",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260624_100000",
        project_root=Path("D:/app"),
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "[success] step_1: affected_rows=1" not in text
    assert "[success] step_15: affected_rows=15" not in text


def test_build_markdown_reads_powershell_utf16_logs(tmp_path):
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "Dashboard daily ETL plan\n"
        "  biz_date      : 2026-06-23\n"
        "  snapshot_date : 2026-06-24\n"
        "  target_schema : etl_datasync_test\n"
        "  steps         : product_performance_daily\n"
        "[success] product_performance_daily: affected_rows=907058\n",
        encoding="utf-16",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260624_100000",
        project_root=Path("D:/app"),
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "业务数据：2026-06-23" in text
    assert "商品表现：已更新到 6月23日，当日约 90.7 万条" in text


def test_success_markdown_uses_validated_business_results_and_tracking_log(tmp_path):
    dashboard_log = tmp_path / "dashboard.log"
    replenishment_log = tmp_path / "replenishment.log"
    tracking_log = tmp_path / "tracking.log"
    dashboard_log.write_text(
        "\n".join(
            [
                "  biz_date      : 2026-06-26",
                "  snapshot_date : 2026-06-27",
                "[success] product_performance_business_result: biz_date=2026-06-26 rows=18520",
            ]
        ),
        encoding="utf-8",
    )
    replenishment_log.write_text(
        "\n".join(
            [
                "  biz_date        : 2026-06-26",
                "  snapshot_date   : 2026-06-27",
                "[success] replenishment_business_result: snapshot_date=2026-06-27 rows=3210",
            ]
        ),
        encoding="utf-8",
    )
    tracking_log.write_text(
        "\n".join(
            [
                "[success] replenishment_tracking snapshot_date=2026-06-27 tracking_window_days=7 snapshot_rows=182 detail_rows=311",
                "[success] replenishment_tracking snapshot_date=2026-06-27 tracking_window_days=14 snapshot_rows=182 detail_rows=311",
                "[success] replenishment_tracking snapshot_date=2026-06-27 tracking_window_days=30 snapshot_rows=182 detail_rows=311",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260627_090000",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=replenishment_log,
        replenishment_stderr=tmp_path / "replenishment.err.log",
        tracking_stdout=tracking_log,
        tracking_stderr=tmp_path / "tracking.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "商品表现：18,520 条" in text
    assert "补货结果：3,210 个 MSKU" in text
    assert "补货追踪：7/14/30 天窗口各 182 个 MSKU" in text
    assert "补货追踪 ETL：成功" in text


def test_tracking_failure_markdown_reads_tracking_stderr(tmp_path):
    tracking_err = tmp_path / "tracking.err.log"
    tracking_err.write_text("tracking business result has 0 rows", encoding="utf-8")

    payload = build_markdown(
        status="failed",
        stage="replenishment_tracking",
        exit_code=1,
        run_stamp="20260627_090000",
        project_root=tmp_path,
        dashboard_stdout=tmp_path / "dashboard.log",
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        tracking_stdout=tmp_path / "tracking.log",
        tracking_stderr=tracking_err,
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "补货追踪 ETL" in text
    assert "tracking business result has 0 rows" in text
    assert "补货结果：已生成" in text
    assert "补货追踪：未确认生成完成" in text


def test_source_preflight_failure_markdown_reads_preflight_stderr(tmp_path):
    preflight_log = tmp_path / "preflight.log"
    preflight_err = tmp_path / "preflight.err.log"
    preflight_log.write_text(
        "\n".join(
            [
                "Dashboard source preflight plan",
                "  biz_date      : 2026-06-26",
                "  snapshot_date : 2026-06-27",
                "[failed] source_preflight product_performance_daily_source rows=0 required_date=2026-06-26",
            ]
        ),
        encoding="utf-8",
    )
    preflight_err.write_text("product_performance_daily_source missing required_date=2026-06-26", encoding="utf-8")

    payload = build_markdown(
        status="failed",
        stage="source_preflight",
        exit_code=1,
        run_stamp="20260627_090000",
        project_root=tmp_path,
        preflight_stdout=preflight_log,
        preflight_stderr=preflight_err,
        dashboard_stdout=tmp_path / "dashboard.log",
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        tracking_stdout=tmp_path / "tracking.log",
        tracking_stderr=tmp_path / "tracking.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "远端数据预检" in text
    assert "product_performance_daily_source missing required_date=2026-06-26" in text
    assert "业务数据：2026-06-26" in text


def test_build_failure_markdown_uses_failed_stage_stderr(tmp_path):
    stderr_log = tmp_path / "replenishment.err.log"
    stderr_log.write_text("line 1\nreal failure reason\n", encoding="utf-8")
    dashboard_log = tmp_path / "dashboard.log"
    dashboard_log.write_text(
        "\n".join(
            [
                "Dashboard daily ETL plan",
                "  biz_date      : 2026-06-23",
                "  snapshot_date : 2026-06-24",
                "[success] product_performance_daily: affected_rows=907058",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_markdown(
        status="failed",
        stage="replenishment",
        exit_code=2,
        run_stamp="20260624_100000",
        project_root=Path("D:/app"),
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=stderr_log,
        error_message="fallback",
    )
    data = json.loads(payload)

    text = data["markdown"]["text"]
    assert "看板定时任务执行失败" in text
    assert "本次目标日期" in text
    assert "业务数据：2026-06-23" in text
    assert "快照数据：2026-06-24" in text
    assert "执行情况" in text
    assert "失败阶段：补货 ETL" in text
    assert "real failure reason" in text
    assert "已完成数据" in text
    assert "商品表现：已更新到 6月23日" in text
    assert "处理建议" in text
    assert "结果明细" not in text
