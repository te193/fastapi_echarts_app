"""Send DingTalk markdown notifications for the daily dashboard ETL task."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Iterable
from urllib import parse, request


MAX_MARKDOWN_CHARS = 15000
MAX_RESULT_LINES = 140
RESULT_PREFIXES = ("[success]", "[failed]", "[skip]", "[warn]", "[info]")
PLAN_LINE_RE = re.compile(r"^\s*([a-z_]+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
ROW_COUNT_RE = re.compile(r"(?:affected_rows|rows)=(-?\d+)")
LOG_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "gb18030")

TABLE_STEP_LABELS = (
    ("product_performance_daily", "dashboard_product_performance_daily"),
    ("monthly_goal_actual_snapshot", "dashboard_monthly_goal_actual_snapshot"),
    ("goal_dimension_snapshot", "dashboard_monthly_goal"),
    ("annual_goal_snapshot", "dashboard_annual_goal_snapshot"),
    ("restock_snapshot", "dashboard_restock_daily_snapshot"),
    ("inventory_snapshot", "dashboard_inventory_daily_snapshot"),
    ("inventory_weekly_snapshot", "dashboard_inventory_weekly_snapshot"),
    ("inventory_weekly_remote_snapshot", "dashboard_inventory_weekly_snapshot"),
    ("listing_price_snapshot", "dashboard_listing_price_daily_snapshot"),
    ("limit_price_snapshot", "dashboard_limit_price_daily_snapshot"),
    ("price_review_source_load", "dashboard_price_review_source"),
    ("price_review_tracking", "dashboard_price_review_tracking"),
    ("listing_basic_sync", "dashboard_replenishment_listing_basic_sync"),
    ("self_asin_sync", "dashboard_replenishment_self_asin_sync"),
    ("fba_shipment_sync", "dashboard_replenishment_fba_shipment_sync"),
    ("replenishment_result", "dashboard_pur_plan_replenish_data"),
    ("country_metrics", "dashboard_replenishment_country_metrics"),
)

CORE_RESULT_STEPS = {
    "product_performance": "product_performance_daily",
    "restock": "restock_snapshot",
    "inventory": "inventory_snapshot",
    "listing_price": "listing_price_snapshot",
    "replenishment_sku": "salable_days_stat",
    "country_metrics": "country_metrics",
    "price_review": "price_review_tracking",
}


def _read_lines(path: Path, limit: int | None = None) -> list[str]:
    if not path or not path.exists():
        return []
    raw = path.read_bytes()
    text = ""
    for encoding in LOG_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if limit is not None:
        return lines[-limit:]
    return lines


def _normalize_log_line(line: str) -> str:
    return line.strip().lstrip("\ufeff")


def _extract_failure_reason_lines(
    stderr_lines: list[str],
    error_message: str = "",
    *,
    limit: int = 8,
) -> list[str]:
    normalized = [_normalize_log_line(line) for line in stderr_lines if _normalize_log_line(line)]
    priority_markers = (
        "Remote source preflight failed:",
        "Business result validation failed:",
    )
    for marker in priority_markers:
        for index in range(len(normalized) - 1, -1, -1):
            line = normalized[index]
            if marker in line:
                if line.startswith(("RuntimeError:", "PreflightFailure:")):
                    line = line.split(":", 1)[1].strip()
                return [_join_wrapped_reason_line(line, normalized[index + 1 :])]

    skip_prefixes = (
        "Traceback (most recent call last):",
        "File ",
        "+",
        "CategoryInfo",
        "FullyQualifiedErrorId",
        "所在位置",
    )
    skip_contains = (
        "source load attempt",
        "NativeCommandError",
    )
    cleaned: list[str] = []
    for line in normalized:
        if any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        if any(fragment in line for fragment in skip_contains):
            continue
        cleaned.append(line)

    if cleaned:
        return cleaned[-limit:]
    if error_message:
        return [_normalize_log_line(error_message)]
    return []


def _join_wrapped_reason_line(line: str, following_lines: list[str]) -> str:
    reason = line
    for continuation in following_lines:
        if not continuation or continuation.startswith(("[", "Traceback", "File ", "+")):
            break
        if ":" in continuation[:30]:
            break
        reason += continuation
        if reason.rstrip().endswith("."):
            break
    return reason


def _parse_log(path: Path) -> dict[str, object]:
    lines = _read_lines(path)
    if not lines:
        return {
            "empty": True,
            "biz_date": "",
            "snapshot_date": "",
            "product_load": "",
            "target_schema": "",
            "steps": [],
            "result_lines": [],
            "affected_rows": 0,
        }

    plan: dict[str, str] = {}
    result_lines: list[str] = []
    affected_rows = 0

    for line in lines:
        plan_match = PLAN_LINE_RE.match(line)
        if plan_match:
            plan[plan_match.group(1).lower()] = plan_match.group(2)

        stripped = line.strip()
        if stripped.startswith(RESULT_PREFIXES):
            result_lines.append(stripped)
            for row_match in ROW_COUNT_RE.finditer(stripped):
                affected_rows += int(row_match.group(1))

    steps = [step.strip() for step in plan.get("steps", "").split(",") if step.strip()]
    return {
        "empty": False,
        "biz_date": plan.get("biz_date", ""),
        "snapshot_date": plan.get("snapshot_date", ""),
        "product_load": plan.get("product_load", ""),
        "target_schema": plan.get("target_schema", ""),
        "steps": steps,
        "result_lines": result_lines,
        "affected_rows": affected_rows,
    }


def _bullet_lines(lines: Iterable[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _first_present(*values: object) -> str:
    for value in values:
        if value:
            return str(value)
    return "-"


def _format_number(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _format_approx_count(value: int, unit: str = "条") -> str:
    if value <= 0:
        return f"0 {unit}"
    if value >= 10000:
        return f"{value / 10000:.1f} 万{unit}"
    if value >= 1000:
        rounded = int(round(value / 100.0) * 100)
        return f"{rounded:,} {unit}"
    return f"{value:,} {unit}"


def _format_month_day(value: object) -> str:
    text = str(value or "")
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return text or "-"
    return f"{int(match.group(2))}月{int(match.group(3))}日"


def _format_product_load(value: object) -> str:
    text = str(value or "")
    if " to " in text:
        start, end = text.split(" to ", 1)
        return f"{start} ~ {end}"
    return text or "-"


def _file_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    return path.stat().st_mtime


def _duration_seconds(start_path: Path, end_path: Path) -> int | None:
    start = _file_mtime(start_path)
    end = _file_mtime(end_path)
    if start is None or end is None or end < start:
        return None
    return int(end - start)


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "未捕获"
    if seconds < 60:
        return f"约 {max(seconds, 1)} 秒"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 10 and 20 <= remainder <= 40:
        return f"约 {minutes} 分半"
    rounded = int((seconds + 30) // 60)
    return f"约 {rounded} 分钟"


def _result_line_count(result_line: str) -> int:
    row_match = re.search(r"affected_rows=(-?\d+)", result_line)
    return int(row_match.group(1)) if row_match else 0


def _count_step(detail: dict[str, object], step_name: str) -> int:
    total = 0
    needle = f"[success] {step_name}:"
    for line in detail.get("result_lines") or []:
        if str(line).startswith(needle):
            total += _result_line_count(str(line))
    return total


def _core_count(detail: dict[str, object], step_key: str) -> int:
    return _count_step(detail, CORE_RESULT_STEPS[step_key])


def _count_step_prefix(detail: dict[str, object], step_prefix: str) -> int:
    total = 0
    needle = f"[success] {step_prefix}"
    for line in detail.get("result_lines") or []:
        text = str(line)
        if text.startswith(needle) and "retention_cleanup" not in text:
            total += _result_line_count(text)
    return total


def _business_result_count(detail: dict[str, object], step_name: str) -> int:
    needle = f"[success] {step_name}:"
    for line in detail.get("result_lines") or []:
        text = str(line)
        if not text.startswith(needle):
            continue
        match = re.search(r"\brows=(\d+)", text)
        if match:
            return int(match.group(1))
    return 0


def _tracking_window_counts(detail: dict[str, object]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for line in detail.get("result_lines") or []:
        text = str(line)
        if not text.startswith("[success] replenishment_tracking snapshot_date="):
            continue
        window_match = re.search(r"\btracking_window_days=(\d+)", text)
        rows_match = re.search(r"\bsnapshot_rows=(\d+)", text)
        if window_match and rows_match:
            counts[int(window_match.group(1))] = int(rows_match.group(1))
    return counts


def _format_table_rows(label: str, count: int) -> str | None:
    if count <= 0:
        return None
    return f"- {label}：{_format_number(count)} 条"


def _format_business_result_summary(
    preflight_detail: dict[str, object],
    dashboard_detail: dict[str, object],
    replenishment_detail: dict[str, object],
    tracking_detail: dict[str, object],
    preflight_stdout: Path,
    preflight_stderr: Path,
    dashboard_stdout: Path,
    dashboard_stderr: Path,
    replenishment_stdout: Path,
    replenishment_stderr: Path,
    tracking_stdout: Path,
    tracking_stderr: Path,
    return_goods_stdout: Path,
    return_goods_stderr: Path,
) -> list[str]:
    biz_date = _first_present(
        dashboard_detail.get("biz_date"), replenishment_detail.get("biz_date"), preflight_detail.get("biz_date")
    )
    snapshot_date = _first_present(
        dashboard_detail.get("snapshot_date"), replenishment_detail.get("snapshot_date"), preflight_detail.get("snapshot_date")
    )
    product_load = _format_product_load(dashboard_detail.get("product_load"))
    dashboard_seconds = _duration_seconds(dashboard_stderr, dashboard_stdout)
    replenishment_seconds = _duration_seconds(replenishment_stderr, replenishment_stdout)
    tracking_seconds = _duration_seconds(tracking_stderr, tracking_stdout)
    return_goods_seconds = _duration_seconds(return_goods_stderr, return_goods_stdout)
    preflight_seconds = _duration_seconds(preflight_stderr, preflight_stdout)
    total_seconds = _duration_seconds(preflight_stderr, return_goods_stdout)
    if total_seconds is None:
        total_seconds = _duration_seconds(preflight_stderr, tracking_stdout)
    if total_seconds is None:
        total_seconds = _duration_seconds(dashboard_stderr, replenishment_stdout)
    product_result = _business_result_count(
        dashboard_detail, "product_performance_business_result"
    ) or _core_count(dashboard_detail, "product_performance")
    replenishment_result = _business_result_count(
        replenishment_detail, "replenishment_business_result"
    ) or _core_count(replenishment_detail, "replenishment_sku")
    tracking_counts = _tracking_window_counts(tracking_detail)
    tracking_count = min(tracking_counts.values()) if tracking_counts else 0
    tracking_windows = "/".join(str(value) for value in sorted(tracking_counts))
    country_metrics = _core_count(replenishment_detail, "country_metrics")
    if country_metrics > 100000:
        country_metrics = round(country_metrics / 2)

    return [
        "#### 更新日期",
        f"- 业务数据：{biz_date}",
        f"- 快照数据：{snapshot_date}",
        f"- 商品表现区间：{product_load}",
        "",
        "#### 执行耗时",
        f"- 总耗时：{_format_duration(total_seconds)}",
        f"- 远端数据预检：{_format_duration(preflight_seconds)}",
        f"- 总 ETL：{_format_duration(dashboard_seconds)}",
        f"- 补货 ETL：{_format_duration(replenishment_seconds)}",
        f"- 补货追踪 ETL：{_format_duration(tracking_seconds)}",
        "",
        "#### 核心结果",
        (
            f"- 商品表现：已更新到 {_format_month_day(biz_date)}，当日约 "
            f"{_format_approx_count(product_result)}"
        ),
        (
            f"- 库存快照：已更新到 {_format_month_day(snapshot_date)}，约 "
            f"{_format_approx_count(_core_count(dashboard_detail, 'inventory'))}"
        ),
        (
            f"- 补货建议快照：已更新到 {_format_month_day(snapshot_date)}，约 "
            f"{_format_approx_count(_core_count(dashboard_detail, 'restock'))}"
        ),
        (
            f"- Listing 价格：已更新到 {_format_month_day(snapshot_date)}，约 "
            f"{_format_approx_count(_core_count(dashboard_detail, 'listing_price'))}"
        ),
        (
            f"- 补货结果：已重新计算，约 "
            f"{_format_approx_count(replenishment_result, '个补货 SKU')}"
        ),
        (
            f"- 补货追踪：{tracking_windows or '-'} 天窗口各 "
            f"{_format_number(tracking_count)} 个 MSKU"
        ),
        f"- 国家维度补货明细：已重新计算，约 {_format_approx_count(country_metrics)}",
        f"- 价格复盘：已更新，约 {_format_approx_count(_core_count(dashboard_detail, 'price_review'), '条结果')}",
        "",
        "#### 业务验收",
        f"- 商品表现：{_format_number(product_result)} 条",
        f"- 补货结果：{_format_number(replenishment_result)} 个 MSKU",
        (
            f"- 补货追踪：{tracking_windows or '-'} 天窗口各 "
            f"{_format_number(tracking_count)} 个 MSKU"
        ),
        "",
        "#### 数据健康",
        "- 远端源数据：已更新完整",
        "- 本地落库：成功",
        f"- 补货页面数据日期：{snapshot_date}",
        "- 错误日志：无",
        "",
        "#### 状态",
        "- 总 ETL：成功",
        "- 补货 ETL：成功",
        "- 补货追踪 ETL：成功",
    ]


def _stage_label(stage: str) -> str:
    labels = {
        "source_preflight": "远端数据预检",
        "dashboard": "总 ETL",
        "replenishment": "补货 ETL",
        "replenishment_tracking": "补货追踪 ETL",
        "all": "全部流程",
    }
    return labels.get(stage, stage)


def _format_failure_summary(
    *,
    stage: str,
    exit_code: int,
    dashboard_detail: dict[str, object],
    replenishment_detail: dict[str, object],
    dashboard_stdout: Path,
    dashboard_stderr: Path,
    replenishment_stdout: Path,
    replenishment_stderr: Path,
    reason_lines: list[str],
) -> list[str]:
    biz_date = _first_present(dashboard_detail.get("biz_date"), replenishment_detail.get("biz_date"))
    snapshot_date = _first_present(
        dashboard_detail.get("snapshot_date"), replenishment_detail.get("snapshot_date")
    )
    total_seconds = _duration_seconds(dashboard_stderr, replenishment_stdout)
    if total_seconds is None:
        total_seconds = _duration_seconds(dashboard_stderr, dashboard_stdout)

    completed_lines = []
    if stage == "source_preflight":
        completed_lines.append("- 远端数据预检：未通过，已停止后续 ETL")
    elif _core_count(dashboard_detail, "product_performance") > 0:
        completed_lines.append(f"- 商品表现：已更新到 {_format_month_day(biz_date)}")
    else:
        completed_lines.append("- 商品表现：未确认完成")

    if stage == "replenishment":
        completed_lines.extend(
            [
                "- 库存 / 补货快照：已完成前置校验后进入补货阶段",
                "- 补货结果：未确认生成完成",
            ]
        )
    elif stage == "replenishment_tracking":
        completed_lines.extend(
            [
                "- 库存 / 补货快照：已完成",
                "- 补货结果：已生成",
                "- 补货追踪：未确认生成完成",
            ]
        )
    else:
        completed_lines.extend(
            [
                "- 库存 / 补货快照：未确认完成",
                "- 补货结果：未生成",
            ]
        )

    return [
        "#### 本次目标日期",
        f"- 业务数据：{biz_date}",
        f"- 快照数据：{snapshot_date}",
        "",
        "#### 执行情况",
        f"- 已执行耗时：{_format_duration(total_seconds)}",
        f"- 失败阶段：{_stage_label(stage)}",
        f"- 退出码：{exit_code}",
        "",
        "#### 失败原因",
        "```text",
        "\n".join(reason_lines),
        "```",
        "",
        "#### 已完成数据",
        *completed_lines,
        "",
        "#### 处理建议",
        "- 先确认远端源数据是否已经生成到目标日期，再重跑 ETL。",
    ]


def _format_etl_detail(title: str, detail: dict[str, object]) -> list[str]:
    if detail.get("empty"):
        return [f"#### {title}", "- 日志为空或未生成。"]

    steps = detail.get("steps") or []
    result_lines = list(detail.get("result_lines") or [])
    shown_lines = result_lines[:MAX_RESULT_LINES]

    lines = [
        f"#### {title}",
        f"- 业务日期：{_first_present(detail.get('biz_date'))}",
        f"- 快照日期：{_first_present(detail.get('snapshot_date'))}",
        f"- 目标库：{_first_present(detail.get('target_schema'))}",
        f"- 执行步骤：{len(steps) if steps else len(result_lines)}",
        f"- 影响行数：{_format_number(detail.get('affected_rows'))}",
        "- 结果明细：",
    ]
    if shown_lines:
        lines.extend(f"  - {line}" for line in shown_lines)
        hidden_count = len(result_lines) - len(shown_lines)
        if hidden_count > 0:
            lines.append(f"  - ...还有 {hidden_count} 条结果明细，见日志。")
    else:
        lines.append("  - 未捕获到结果行，见日志。")
    return lines


def _relative_log(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def build_signed_webhook(
    webhook: str, secret: str | None = None, *, timestamp_ms: int | None = None
) -> str:
    if not secret:
        return webhook

    timestamp = str(timestamp_ms if timestamp_ms is not None else round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sign = parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def build_markdown(
    *,
    status: str,
    stage: str,
    exit_code: int,
    run_stamp: str,
    project_root: Path,
    preflight_stdout: Path | None = None,
    preflight_stderr: Path | None = None,
    dashboard_stdout: Path,
    dashboard_stderr: Path,
    replenishment_stdout: Path,
    replenishment_stderr: Path,
    tracking_stdout: Path | None = None,
    tracking_stderr: Path | None = None,
    return_goods_stdout: Path | None = None,
    return_goods_stderr: Path | None = None,
    error_message: str = "",
) -> str:
    preflight_stdout = preflight_stdout or project_root / "logs" / "source-preflight-not-created.log"
    preflight_stderr = preflight_stderr or project_root / "logs" / "source-preflight-not-created.err.log"
    tracking_stdout = tracking_stdout or project_root / "logs" / "tracking-not-created.log"
    tracking_stderr = tracking_stderr or project_root / "logs" / "tracking-not-created.err.log"
    return_goods_stdout = return_goods_stdout or project_root / "logs" / "return-goods-not-created.log"
    return_goods_stderr = return_goods_stderr or project_root / "logs" / "return-goods-not-created.err.log"
    is_success = status == "success"
    title = "看板定时任务执行成功" if is_success else "看板定时任务执行失败"
    icon = "✅" if is_success else "❌"
    preflight_detail = _parse_log(preflight_stdout)
    dashboard_detail = _parse_log(dashboard_stdout)
    replenishment_detail = _parse_log(replenishment_stdout)
    tracking_detail = _parse_log(tracking_stdout)
    biz_date = _first_present(
        dashboard_detail.get("biz_date"), replenishment_detail.get("biz_date"), preflight_detail.get("biz_date")
    )
    snapshot_date = _first_present(
        dashboard_detail.get("snapshot_date"), replenishment_detail.get("snapshot_date"), preflight_detail.get("snapshot_date")
    )

    lines = [f"### {icon} {title}", "", f"- 运行批次：{run_stamp}"]

    if is_success:
        lines.extend(
            [
                "",
                *_format_business_result_summary(
                    preflight_detail,
                    dashboard_detail,
                    replenishment_detail,
                    tracking_detail,
                    preflight_stdout,
                    preflight_stderr,
                    dashboard_stdout,
                    dashboard_stderr,
                    replenishment_stdout,
                    replenishment_stderr,
                    tracking_stdout,
                    tracking_stderr,
                    return_goods_stdout,
                    return_goods_stderr,
                ),
            ]
        )
    else:
        failed_stderr = {
            "source_preflight": preflight_stderr,
            "replenishment": replenishment_stderr,
            "replenishment_tracking": tracking_stderr,
            "return_goods": return_goods_stderr,
        }.get(stage, dashboard_stderr)
        reason_lines = _extract_failure_reason_lines(_read_lines(failed_stderr), error_message)
        if not reason_lines:
            reason_lines = [f"任务退出码为 {exit_code}，错误日志为空。"]

        lines.extend(
            [
                "",
                *_format_failure_summary(
                    stage=stage,
                    exit_code=exit_code,
                    dashboard_detail=preflight_detail if stage == "source_preflight" else dashboard_detail,
                    replenishment_detail=replenishment_detail,
                    dashboard_stdout=dashboard_stdout,
                    dashboard_stderr=dashboard_stderr,
                    replenishment_stdout=replenishment_stdout,
                    replenishment_stderr=replenishment_stderr,
                    reason_lines=reason_lines,
                ),
            ]
        )

    text = "\n".join(lines)
    if len(text) > MAX_MARKDOWN_CHARS:
        text = text[: MAX_MARKDOWN_CHARS - 40] + "\n\n...内容过长，已截断。"

    return json.dumps(
        {"msgtype": "markdown", "markdown": {"title": title, "text": text}},
        ensure_ascii=False,
    )


def send_markdown(webhook: str, payload: str, secret: str | None = None) -> None:
    signed_webhook = build_signed_webhook(webhook, secret)
    req = request.Request(
        signed_webhook,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=15) as response:
        body = response.read().decode("utf-8", errors="replace")

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DingTalk returned non-JSON response: {body[:200]}") from exc

    if result.get("errcode") != 0:
        raise RuntimeError(f"DingTalk send failed: {result}")


def print_utf8(text: str) -> None:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
        sys.stdout.flush()
    else:
        print(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", choices=("success", "failed"), required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--run-stamp", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--preflight-stdout", type=Path)
    parser.add_argument("--preflight-stderr", type=Path)
    parser.add_argument("--dashboard-stdout", type=Path, required=True)
    parser.add_argument("--dashboard-stderr", type=Path, required=True)
    parser.add_argument("--replenishment-stdout", type=Path, required=True)
    parser.add_argument("--replenishment-stderr", type=Path, required=True)
    parser.add_argument("--tracking-stdout", type=Path)
    parser.add_argument("--tracking-stderr", type=Path)
    parser.add_argument("--return-goods-stdout", type=Path)
    parser.add_argument("--return-goods-stderr", type=Path)
    parser.add_argument("--error-message", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_markdown(
        status=args.status,
        stage=args.stage,
        exit_code=args.exit_code,
        run_stamp=args.run_stamp,
        project_root=args.project_root,
        preflight_stdout=args.preflight_stdout,
        preflight_stderr=args.preflight_stderr,
        dashboard_stdout=args.dashboard_stdout,
        dashboard_stderr=args.dashboard_stderr,
        replenishment_stdout=args.replenishment_stdout,
        replenishment_stderr=args.replenishment_stderr,
        tracking_stdout=args.tracking_stdout,
        tracking_stderr=args.tracking_stderr,
        return_goods_stdout=args.return_goods_stdout,
        return_goods_stderr=args.return_goods_stderr,
        error_message=args.error_message,
    )

    if args.dry_run:
        print_utf8(payload)
        return 0

    webhook = os.environ.get("DASHBOARD_DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK")
    secret = os.environ.get("DASHBOARD_DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET")
    if not webhook:
        print("DingTalk webhook is not configured; notification skipped.")
        return 0

    send_markdown(webhook, payload, secret)
    print("DingTalk notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
