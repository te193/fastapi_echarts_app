from __future__ import annotations

import json
import threading
import time
from typing import Any

from .dashboard_db import dashboard_service


SUPPORTED_PERIODS = {"7d", "14d", "30d", "90d"}
ROLE_PRIORITY = {"问题": 0, "瘦狗": 1, "潜力": 2, "明星": 3}
ROWS_CACHE_SECONDS = 180
ROWS_CACHE_MAX_ITEMS = 128


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact(value: float, digits: int = 2) -> str:
    return f"{round(value, digits):.{digits}f}".rstrip("0").rstrip(".")


def _role_kind(role: str) -> str:
    for kind in ("问题", "瘦狗", "潜力", "明星"):
        if kind in role:
            return kind
    return ""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _metric(
    *,
    key: str,
    label: str,
    current: float | None,
    target: float | None,
    comparator: str,
    unit: str = "",
    missing_gap: str = "暂无数据",
) -> dict[str, Any]:
    current_display = "暂无数据" if current is None else f"{_compact(current)}{unit}"
    if comparator == "valid_rank":
        target_display = "有效排名"
        met = current is not None and 0 < current < 99999
    else:
        operator = {"gt": ">", "gte": "≥", "lte": "≤"}[comparator]
        target_display = f"{operator} {_compact(float(target or 0))}{unit}"
        met = current is not None and (
            (comparator == "gt" and current > float(target or 0))
            or (comparator == "gte" and current >= float(target or 0))
            or (comparator == "lte" and current <= float(target or 0))
        )

    if current is None:
        status = "missing"
        gap_display = missing_gap
        progress = 0
    elif met:
        status = "met"
        gap_display = "已达标"
        progress = 100
    else:
        status = "unmet"
        if comparator == "lte":
            gap = max(0.0, current - float(target or 0))
            gap_display = f"需提升 {_compact(gap)} 位"
            progress = max(0, min(100, round(float(target or 0) / current * 100))) if current else 0
        else:
            gap = max(0.0, float(target or 0) - current)
            if key == "daily_sales" and current <= 0:
                gap_display = "需恢复销售"
            else:
                suffix = "pp" if key == "tag_margin_rate" else unit
                gap_display = f"还差 {_compact(gap)}{suffix}"
            progress = max(0, min(100, round(current / float(target or 1) * 100)))

    return {
        "key": key,
        "label": label,
        "current": current,
        "current_display": current_display,
        "target": target,
        "target_display": target_display,
        "status": status,
        "gap_display": gap_display,
        "progress": progress,
    }


class LabelHubRoleDiagnosticService:
    """Build display-ready role diagnostics from label evidence JSON."""

    def __init__(self, dashboard: Any = dashboard_service) -> None:
        self._dashboard = dashboard
        self._rows_cache: dict[tuple[str, str, str, str], tuple[float, list[dict[str, Any]]]] = {}
        self._rows_cache_lock = threading.Lock()

    def get_payload(
        self,
        *,
        data_date: str,
        country_category: str,
        store: str,
        msku: str,
        diagnostic_period: str,
    ) -> dict[str, Any]:
        period = str(diagnostic_period or "30d")
        if period not in SUPPORTED_PERIODS:
            raise ValueError("诊断周期只支持 7d、14d、30d、90d")
        if not all(str(item or "").strip() for item in (data_date, country_category, store, msku)):
            raise ValueError("缺少销售角色诊断所需的商品身份信息")

        cache_key = (data_date, country_category, store, msku)
        now = time.monotonic()
        with self._rows_cache_lock:
            cached = self._rows_cache.get(cache_key)
            rows = cached[1] if cached and now - cached[0] < ROWS_CACHE_SECONDS else None
            if cached and rows is None:
                self._rows_cache.pop(cache_key, None)
        if rows is None:
            rows = self._fetch_rows(
                data_date=data_date,
                country_category=country_category,
                store=store,
                msku=msku,
                diagnostic_period=period,
            )
            with self._rows_cache_lock:
                self._rows_cache[cache_key] = (time.monotonic(), rows)
                if len(self._rows_cache) > ROWS_CACHE_MAX_ITEMS:
                    oldest_key = min(self._rows_cache, key=lambda item: self._rows_cache[item][0])
                    self._rows_cache.pop(oldest_key, None)
        rows = [
            row
            for row in rows
            if not row.get("label_period") or str(row.get("label_period")) == period
        ]
        diagnostics = [self._build_diagnostic(row) for row in rows]
        global_diagnostic = next(
            (item for item in diagnostics if int(item["parent_id"]) == 15),
            None,
        )
        countries = [item for item in diagnostics if int(item["parent_id"]) == 16]
        countries.sort(
            key=lambda item: (
                ROLE_PRIORITY.get(_role_kind(item["current_role"]), 9),
                -int(item["unmet_count"]),
                str(item["country"]),
            )
        )
        role_counts: dict[str, int] = {}
        for item in countries:
            role = item["current_role"]
            role_counts[role] = role_counts.get(role, 0) + 1

        return {
            "identity": {
                "data_date": data_date,
                "country_category": country_category,
                "store": store,
                "msku": msku,
            },
            "period": period,
            "global_diagnostic": global_diagnostic,
            "country_diagnostics": countries,
            "meta": {
                "evidence_status": "available" if rows else "missing",
                "country_count": len(countries),
                "role_counts": role_counts,
            },
        }

    def _fetch_rows(
        self,
        *,
        data_date: str,
        country_category: str,
        store: str,
        msku: str,
        diagnostic_period: str,
    ) -> list[dict[str, Any]]:
        sql = """
            select
                d.label_id as parent_id,
                d.sub_label_id,
                d.sub_label_name,
                d.tag_rule,
                f.country,
                f.label_period,
                f.evidence_json
            from dws_datasync.dws_标签表 f force index (idx_label)
            inner join dws_datasync.dws_标签详情表 d
                on d.sub_label_id = f.label_id
            where f.label_id between 1501 and 1618
              and f.data_date = %s
              and f.country_category = %s
              and f.store = %s
              and f.msku = %s
              and f.label_period in ('7d', '14d', '30d', '90d')
              and d.label_id in (15, 16)
            order by f.label_period, d.label_id, f.country, d.sub_label_id
        """
        with self._dashboard.source_connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (data_date, country_category, store, msku),
                )
                return list(cursor.fetchall())

    def _build_diagnostic(self, row: dict[str, Any]) -> dict[str, Any]:
        evidence = _json_object(row.get("evidence_json"))
        issue = evidence.get("product_issue") or {}
        metrics = issue.get("metrics_used") or evidence.get("metrics") or {}
        current_role = str(
            (evidence.get("source_sales_role") or {}).get("sub_label_name")
            or self._role_from_issue(str(row.get("sub_label_name") or ""))
        )
        target_role = str(issue.get("benchmark_target") or self._default_target(current_role))
        is_country = int(row.get("parent_id") or 0) == 16
        metric_rows, branch_text = self._target_metrics(current_role, metrics, is_country)
        failed = [item for item in metric_rows if item["status"] != "met"]
        summary_parts: list[str] = []
        for item in failed:
            if item["key"] == "daily_sales" and item["gap_display"] == "需恢复销售":
                summary_parts.append(item["gap_display"])
            else:
                summary_parts.append(f"{item['label']}{item['gap_display']}")

        return {
            "parent_id": int(row.get("parent_id") or 0),
            "sub_label_id": int(row.get("sub_label_id") or 0),
            "country": str(row.get("country") or ""),
            "current_role": current_role,
            "target_role": target_role,
            "issue_label": str(issue.get("label") or row.get("sub_label_name") or ""),
            "main_blocker": "、".join(item["label"] for item in failed) or "当前指标均已达标",
            "summary": "；".join(summary_parts) or "当前指标均已达标",
            "unmet_count": len(failed),
            "metrics": metric_rows,
            "rule_branch_text": branch_text,
            "tag_rule": str(row.get("tag_rule") or ""),
            "rule_version": str(evidence.get("rule_version") or ""),
            "schema_version": str(evidence.get("schema_version") or ""),
        }

    @staticmethod
    def _role_from_issue(issue_label: str) -> str:
        return issue_label.split("-", 1)[0]

    @staticmethod
    def _default_target(role: str) -> str:
        kind = _role_kind(role)
        return {
            "问题": "退出问题产品",
            "瘦狗": "站点潜力" if "站点" in role else "潜力产品",
            "潜力": "站点明星" if "站点" in role else "明星产品",
            "明星": "保持当前层级",
        }.get(kind, "达到上一层级")

    def _target_metrics(
        self,
        role: str,
        values: dict[str, Any],
        is_country: bool,
    ) -> tuple[list[dict[str, Any]], str]:
        daily = _number(values.get("daily_sales"))
        margin = _number(values.get("tag_margin_rate"))
        rank = _number(values.get("small_rank"))
        kind = _role_kind(role)

        if is_country:
            if kind in {"明星", "潜力"}:
                high_sales = daily is not None and daily > 3
                daily_target, margin_target = (3, 15) if high_sales else (1, 25)
                branch = (
                    "冲刺站点明星：日销 > 3、毛利率 ≥ 15%、小类排名 ≤ 50"
                    if high_sales
                    else "冲刺站点明星：日销 ≥ 1、毛利率 ≥ 25%、小类排名 ≤ 50"
                )
                specs = [
                    ("daily_sales", "日销", daily, daily_target, "gt" if high_sales else "gte", ""),
                    ("tag_margin_rate", "毛利率", margin, margin_target, "gte", "%"),
                    ("small_rank", "小类排名", rank, 50, "lte", ""),
                ]
            elif kind == "瘦狗":
                margin_target = 10 if daily is None or daily <= 3 else 5
                branch = f"达到站点潜力：日销 ≥ 1、毛利率 ≥ {margin_target}%、小类排名 ≤ 100"
                specs = [
                    ("daily_sales", "日销", daily, 1, "gte", ""),
                    ("tag_margin_rate", "毛利率", margin, margin_target, "gte", "%"),
                    ("small_rank", "小类排名", rank, 100, "lte", ""),
                ]
            elif kind == "问题":
                branch = "退出问题产品：恢复销售、毛利率 ≥ 5%，并具备有效排名"
                specs = [
                    ("daily_sales", "日销", daily, 0, "gt", ""),
                    ("tag_margin_rate", "毛利率", margin, 5, "gte", "%"),
                    ("small_rank", "小类排名", rank, None, "valid_rank", ""),
                ]
            else:
                return [], "暂无可用的站点角色规则"
        else:
            high_sales = daily is not None and daily > 5
            if kind in {"明星", "潜力"}:
                daily_target, margin_target = (5, 15) if high_sales else (1, 25)
                branch = (
                    "冲刺明星产品：日销 > 5、毛利率 > 15%"
                    if high_sales
                    else "冲刺明星产品：日销 ≥ 1、毛利率 > 25%"
                )
            elif kind == "瘦狗":
                daily_target, margin_target = 1, 10
                branch = "达到潜力产品：日销 ≥ 1、毛利率 ≥ 10%"
            elif kind == "问题":
                daily_target, margin_target = 0, 5
                branch = "退出问题产品：恢复销售且毛利率 ≥ 5%"
            else:
                return [], "暂无可用的全站角色规则"
            specs = [
                ("daily_sales", "日销", daily, daily_target, "gt" if kind == "问题" or high_sales else "gte", ""),
                ("tag_margin_rate", "毛利率", margin, margin_target, "gt" if kind in {"明星", "潜力"} else "gte", "%"),
            ]

        rows = []
        for key, label, current, target, comparator, unit in specs:
            missing_gap = (
                "恢复销售后再判断"
                if key == "tag_margin_rate" and (daily is None or daily <= 0)
                else "暂无数据"
            )
            rows.append(
                _metric(
                    key=key,
                    label=label,
                    current=current,
                    target=target,
                    comparator=comparator,
                    unit=unit,
                    missing_gap=missing_gap,
                )
            )
        return rows, branch


label_hub_role_diagnostic_service = LabelHubRoleDiagnosticService()
