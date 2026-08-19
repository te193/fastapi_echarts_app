import json
import os
from pathlib import Path
from urllib.error import URLError
from unittest.mock import Mock, patch

from scripts.notify_daily_task_dingtalk import build_markdown, build_signed_webhook, send_markdown


def test_build_signed_webhook_adds_timestamp_and_signature():
    url = build_signed_webhook(
        "https://oapi.dingtalk.com/robot/send?access_token=abc",
        "SECtest",
        timestamp_ms=1234567890,
    )

    assert "access_token=abc" in url
    assert "timestamp=1234567890" in url
    assert "sign=" in url


def test_send_markdown_falls_back_to_curl_after_python_ssl_retries():
    curl_result = Mock(returncode=0, stdout='{"errcode":0,"errmsg":"ok"}', stderr="")

    with (
        patch(
            "scripts.notify_daily_task_dingtalk.request.urlopen",
            side_effect=URLError("SSL: UNEXPECTED_EOF_WHILE_READING"),
        ) as urlopen,
        patch("scripts.notify_daily_task_dingtalk.time.sleep"),
        patch("scripts.notify_daily_task_dingtalk.shutil.which", return_value="curl.exe"),
        patch("scripts.notify_daily_task_dingtalk.subprocess.run", return_value=curl_result) as run,
    ):
        send_markdown(
            "https://oapi.dingtalk.com/robot/send?access_token=abc",
            '{"msgtype":"markdown"}',
            "SECtest",
        )

    assert urlopen.call_count == 3
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[0] == "curl.exe"
    assert "--data-binary" in command


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

    assert "商品表现：已更新到 6月26日，当日约 1.9 万条" in text
    assert "补货结果：已重新计算，约 3,200 个补货 SKU" in text
    assert "补货追踪：7/14/30 天窗口各 182 个 MSKU" in text
    assert "7/7 个每日更新模块执行成功" in text


def test_success_markdown_reports_tracking_summary_result(tmp_path):
    tracking_log = tmp_path / "tracking-summary.log"
    tracking_log.write_text(
        (
            "[success] replenishment_tracking_summary cutoff_date=2026-07-10 "
            "summary_rows=719 level_history_rows=1021 purchase_order_rows=154 "
            "receipt_order_rows=81 qc_order_rows=60 elapsed=12.34s"
        ),
        encoding="utf-8",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260710_090000",
        project_root=tmp_path,
        dashboard_stdout=tmp_path / "dashboard.log",
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        tracking_stdout=tracking_log,
        tracking_stderr=tmp_path / "tracking-summary.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "补货追踪汇总：截至 7月10日，719 个 MSKU；历史分层 1,021 条" in text
    assert "7/7 个每日更新模块执行成功" in text


def test_success_markdown_reads_current_tracking_summary_log_format(tmp_path):
    tracking_log = tmp_path / "tracking-summary.log"
    tracking_log.write_text(
        "[success] cutoff_date=2026-07-21 summary_rows=862 "
        "level_history_rows=1311 purchase_source_rows=793 elapsed=53.14s",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260721_090002",
        project_root=tmp_path,
        dashboard_stdout=tmp_path / "dashboard.log",
        dashboard_stderr=tmp_path / "dashboard.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        tracking_stdout=tracking_log,
        tracking_stderr=tmp_path / "tracking-summary.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "862 \u4e2a MSKU" in text
    assert "\u5386\u53f2\u5206\u5c42 1,311 \u6761" in text


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


def test_success_markdown_covers_new_daily_modules_without_duplicate_acceptance(tmp_path):
    dashboard_log = tmp_path / "dashboard.log"
    sales_role_log = tmp_path / "sales-role.log"
    label_evidence_log = tmp_path / "label-evidence.log"
    return_goods_log = tmp_path / "return-goods.log"

    dashboard_log.write_text(
        "\n".join(
            [
                "  biz_date      : 2026-07-20",
                "  snapshot_date : 2026-07-21",
                "[success] limit_price_snapshot: affected_rows=38654",
                "[success] alert_comparison_snapshots.d7: affected_rows=18820",
                "[success] alert_comparison_snapshots.d14: affected_rows=19086",
                "[success] alert_comparison_snapshots.d30: affected_rows=19659",
                "[success] alert_comparison_snapshots.d60: affected_rows=21571",
                "[success] alert_comparison_snapshots.d90: affected_rows=22387",
                "[success] opportunity_comparison_snapshots.d7: affected_rows=2159",
                "[success] opportunity_comparison_snapshots.d14: affected_rows=2570",
                "[success] opportunity_comparison_snapshots.d30: affected_rows=2865",
                "[success] opportunity_comparison_snapshots.d60: affected_rows=3116",
                "[success] opportunity_comparison_snapshots.d90: affected_rows=3278",
            ]
        ),
        encoding="utf-8",
    )
    sales_role_log.write_text(
        "\n".join(
            [
                "  snapshot_date : 2026-07-21",
                "[success] 7d: 2026-07-14 ~ 2026-07-20, rows=3617",
                "[success] 14d: 2026-07-07 ~ 2026-07-20, rows=3617",
                "[success] 30d: 2026-06-21 ~ 2026-07-20, rows=3622",
                "[success] 90d: 2026-04-22 ~ 2026-07-20, rows=3807",
            ]
        ),
        encoding="utf-8",
    )
    label_evidence_log.write_text(
        "Label rule evidence snapshot updated\n"
        "  label_dates : 2026-07-20, 2026-07-19\n"
        "  periods     : 7d, 14d, 30d, 90d\n"
        "  rows        : 66214\n",
        encoding="utf-8",
    )
    return_goods_log.write_text(
        "Return goods ETL: snapshot_date=2026-07-20, lookback_days=180\n"
        "[success] dashboard_return_goods_events rows=789\n",
        encoding="utf-8",
    )

    payload = build_markdown(
        status="success",
        stage="all",
        exit_code=0,
        run_stamp="20260721_090002",
        project_root=tmp_path,
        dashboard_stdout=dashboard_log,
        dashboard_stderr=tmp_path / "dashboard.err.log",
        sales_role_stdout=sales_role_log,
        sales_role_stderr=tmp_path / "sales-role.err.log",
        label_evidence_stdout=label_evidence_log,
        label_evidence_stderr=tmp_path / "label-evidence.err.log",
        replenishment_stdout=tmp_path / "replenishment.log",
        replenishment_stderr=tmp_path / "replenishment.err.log",
        return_goods_stdout=return_goods_log,
        return_goods_stderr=tmp_path / "return-goods.err.log",
    )
    text = json.loads(payload)["markdown"]["text"]

    assert "\u9500\u552e\u89d2\u8272 / \u751f\u547d\u5468\u671f" in text
    assert "30\u5929 3,622 \u4e2a MSKU" in text
    assert "\u6807\u7b7e\u89c4\u5219\u8bc1\u636e" in text
    assert "66,214 \u6761" in text
    assert "\u8fd4\u5382\u54c1" in text
    assert "789 \u6761" in text
    assert "\u9650\u4ef7\u6570\u636e" in text
    assert "3.9 \u4e07\u6761" in text
    assert "\u5f02\u5e38\u9884\u8b66 / \u673a\u4f1a\u6c60" in text
    assert "5/5 \u4e2a\u5468\u671f" in text
    assert "\u8fd4\u5382\u54c1 ETL" in text
    assert "\u4e1a\u52a1\u9a8c\u6536" not in text


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
