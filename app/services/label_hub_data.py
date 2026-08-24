from __future__ import annotations

import json
import math
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .dashboard_db import dashboard_service
from .label_hub_local_metrics import METRIC_PERIODS, label_hub_local_metrics_service
from .stockout_historical_operating_data import (
    RESULT_TABLE as STOCKOUT_HISTORICAL_RESULT_TABLE,
    build_stockout_historical_summary,
    decorate_stockout_snapshot_status,
    filter_stockout_historical_members,
)
from .stockout_historical_operating import ROLE_LABELS as HISTORICAL_ROLE_LABELS


LABEL_DETAIL_TABLE = "etl_datasync_test.dashboard_label_detail_snapshot"
LABEL_FACT_TABLE = "etl_datasync_test.dashboard_label_fact_snapshot"
REFUND_MSKU_PREFIX = "Amazon.Found."
CACHE_SECONDS = 300
# The source snapshots are date-keyed and only change during the daily refresh.
# Keep them longer than the filter-result cache so ordinary navigation does not
# repeatedly reconnect to the remote warehouse.
SOURCE_CACHE_SECONDS = 1800
SOURCE_QUICK_CHECK_SECONDS = 15
SOURCE_CONTENT_CHECK_SECONDS = 21600
# The deep fingerprint scans both retained label snapshots.  Do not start that
# scan while the first dashboard and comparison requests are still warming.
SOURCE_INITIAL_CONTENT_CHECK_DELAY_SECONDS = 30
COUNTRY_SCOPE_PARENT_IDS = {4, 7, 13, 14}
DIAGNOSTIC_PARENT_IDS = {15, 16}
MSKU_ANALYSIS_HIDDEN_PARENT_IDS = {21}
EXCLUDED_ANALYSIS_PARENT_IDS = (
    COUNTRY_SCOPE_PARENT_IDS
    | DIAGNOSTIC_PARENT_IDS
    | MSKU_ANALYSIS_HIDDEN_PARENT_IDS
)
FACT_FETCH_EXCLUDED_PARENT_IDS = (
    COUNTRY_SCOPE_PARENT_IDS
    | MSKU_ANALYSIS_HIDDEN_PARENT_IDS
)
CURRENT_STOCKOUT_CHILD_ID = 304
STOCKOUT_BEFORE_ROLE_PARENT_ID = 20
STOCKOUT_BEFORE_ROLE_IDS = (2001, 2002, 2003, 2004)
COUNTRY_STOCKOUT_BEFORE_ROLE_IDS = (2101, 2102, 2103, 2104)
STOCKOUT_BEFORE_ROLE_PERIODS = ("7d", "14d", "30d", "90d")
STOCKOUT_BEFORE_ROLE_LABELS = {
    2001: "明星产品",
    2002: "潜力产品",
    2003: "瘦狗产品",
    2004: "问题产品",
}
STOCKOUT_OPERATING_STATUS_DEFINITIONS = (
    ("low_inventory_edge", "低量库存边缘断货", "not_evaluable"),
    ("pre_oos_evidence_insufficient", "断货前依据不足", "not_evaluable"),
    ("full_period_zero_sales", "完整周期零销量", "evaluable"),
    ("star", "明星产品", "evaluable"),
    ("potential", "潜力产品", "evaluable"),
    ("dog", "瘦狗产品", "evaluable"),
    ("loss_issue", "亏损问题", "evaluable"),
    ("low_margin_issue", "低毛利问题", "evaluable"),
)
STOCKOUT_LOW_SUPPLY_THRESHOLD = 5
STOCKOUT_EVIDENCE_REASON_LABELS = {
    "inventory_evidence_missing": "库存证据缺失",
    "inventory_evidence_conflict": "库存证据冲突",
    "role_missing": "缺少所选周期断货前角色",
    "role_evidence_incomplete": "断货前角色证据不完整",
    "history_coverage_insufficient": "断货前历史覆盖不足",
    "calculation_abnormal": "断货前角色计算状态异常",
    "role_evidence_conflict": "断货前角色与指标冲突",
}
HISTORICAL_ROLE_DISTRIBUTION_ORDER = (
    "star",
    "potential",
    "dog",
    "problem",
    "in_stock_zero_sales",
)
HISTORICAL_ROLE_NODE_REASON_LABELS = {
    "effective_operating_days_insufficient": "30天窗口有效经营日不足",
}
STOCKOUT_OPERATING_TREND_LABELS = {
    "stable": "断货前稳定",
    "accelerating": "断货前加速",
    "slowing": "断货前减速",
    "recent_start": "断货前启动",
    "stopped": "断货前临停",
    "volatile": "断货前波动",
    "unavailable": "趋势暂不可判",
}
STOCKOUT_ROLE_LEVELS = {
    2004: 0,
    2104: 0,
    2003: 1,
    2103: 1,
    2002: 2,
    2102: 2,
    2001: 3,
    2101: 3,
}
COUNTRY_STOCKOUT_BEFORE_ROLE_LABELS = {
    2101: "明星产品",
    2102: "潜力产品",
    2103: "瘦狗产品",
    2104: "问题产品",
}
SALES_ROLE_PARENT_ID = 1
PROBLEM_PRODUCT_CHILD_ID = 104
RETURN_STAGE_PARENT_ID = 5
ACTIVE_RETURN_STAGE_CHILD_IDS = frozenset({501, 502, 503})

REMOTE_PARENT_CHILD_PRIORITY = {
    1: [101, 102, 103, 104],
    2: [204, 203, 202, 201, 205],
    3: [301, 302, 303, 304, 305, 306],
    5: [501, 502, 503],
    6: [608, 607, 606, 605, 604, 603, 612, 602, 601, 611, 609, 610],
    8: [802, 801, 803],
    9: [904, 903, 902, 901],
    10: [1001, 1002, 1003, 1004],
    11: [1101, 1102, 1103, 1104],
    12: [1202, 1201, 1203],
}

LOCAL_VALUE_PRIORITY = {
    "sales_role_code": ["star", "potential", "incubation", "eliminate", "missing"],
    "sales_trend_code": ["accelerating", "growing", "recent_start", "stable", "slowing", "declining", "stopped", "no_sales", "insufficient", "missing"],
    "daily_sales_band_code": ["gt5", "1_5", "lt1", "zero", "missing"],
    "margin_band_code": ["gt25", "15_25", "10_15", "5_10", "lt5", "missing"],
}

LOCAL_BREAKDOWN_DEFINITIONS = {
    "sales_trend": {
        "label": "动销趋势",
        "field": "sales_trend_code",
        "description": "同一经营截止日的近7日日均销量与近30日日均销量对比，变化率 = (7日日均 - 30日日均) / 30日日均。",
        "buckets": [
            ("accelerating", "明显增长"), ("growing", "小幅增长"), ("stable", "基本稳定"),
            ("slowing", "动销放缓"), ("declining", "明显下滑"), ("stopped", "近期停销"),
            ("no_sales", "持续无销"), ("recent_start", "近期启动"), ("insufficient", "暂无趋势数据"),
        ],
        "rules": [
            {"label": "明显增长", "rule": "变化率 ≥ 30%"},
            {"label": "小幅增长", "rule": "10% ≤ 变化率 < 30%"},
            {"label": "基本稳定", "rule": "-10% < 变化率 < 10%"},
            {"label": "动销放缓", "rule": "-30% < 变化率 ≤ -10%"},
            {"label": "明显下滑", "rule": "变化率 ≤ -30%"},
            {"label": "近期停销", "rule": "30日日均 > 0，且7日日均 = 0"},
            {"label": "持续无销", "rule": "7日日均 = 0，且30日日均 = 0"},
            {"label": "近期启动", "rule": "7日日均 > 0，且30日日均 = 0"},
            {"label": "暂无趋势数据", "rule": "缺少同一截止日的7天或30天经营快照"},
        ],
    },
    "daily_sales_band": {
        "label": "日销段",
        "field": "daily_sales_band_code",
        "buckets": [("zero", "日销 0"), ("lt1", "日销 <1"), ("1_5", "日销 1–5"), ("gt5", "日销 >5")],
    },
    "margin_band": {
        "label": "毛利段",
        "field": "margin_band_code",
        "buckets": [("lt5", "<5%"), ("5_10", "5%–10%"), ("10_15", "10%–15%"), ("15_25", "15%–25%"), ("gt25", ">25%")],
    },
}


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _number(value: Any) -> float | None:
    return None if value is None or value == "" else float(value)


def _evidence_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _historical_role_history(value: Any) -> dict[str, Any]:
    evidence = _evidence_object(value)
    source_nodes = evidence.get("rolling_role_nodes")
    if not isinstance(source_nodes, list):
        source_nodes = []
    nodes = []
    for source in source_nodes:
        if not isinstance(source, dict):
            continue
        role = str(source.get("role") or "unavailable")
        if role not in HISTORICAL_ROLE_LABELS:
            role = "unavailable"
        reason = str(source.get("reason") or "")
        effective_operating_days = int(source.get("effective_operating_days") or 0)
        nodes.append(
            {
                "window_start": _date_text(source.get("window_start")),
                "window_end": _date_text(source.get("window_end")),
                "role": role,
                "label": HISTORICAL_ROLE_LABELS[role],
                "is_valid": role != "unavailable",
                "reason": reason,
                "reason_label": HISTORICAL_ROLE_NODE_REASON_LABELS.get(reason, "周期角色证据不足") if role == "unavailable" else "",
                "effective_operating_days": effective_operating_days,
                "minimum_effective_days": 21,
            }
        )
    nodes.sort(key=lambda item: (item["window_end"], item["window_start"]))
    counts = Counter(node["role"] for node in nodes if node["is_valid"])
    valid_count = sum(counts.values())
    distribution = [
        {
            "code": code,
            "label": HISTORICAL_ROLE_LABELS[code],
            "count": counts[code],
            "share": round(counts[code] / valid_count, 4) if valid_count else 0,
        }
        for code in HISTORICAL_ROLE_DISTRIBUTION_ORDER
    ]
    dominant_role = None
    if valid_count:
        dominant_role = max(
            distribution,
            key=lambda item: (item["count"], -HISTORICAL_ROLE_DISTRIBUTION_ORDER.index(item["code"])),
        )
    return {
        "status": "available" if valid_count >= 8 else ("insufficient" if nodes else "missing"),
        "valid_node_count": valid_count,
        "total_node_count": len(nodes),
        "unavailable_node_count": len(nodes) - valid_count,
        "dominant_role": dominant_role,
        "distribution": distribution,
        "nodes": nodes,
    }


def _period_order(value: str) -> tuple[int, str]:
    text = str(value or "")
    if text.endswith("d") and text[:-1].isdigit():
        return int(text[:-1]), text
    return 9999, text


def _parse_int_pipe(value: Any) -> list[int]:
    result: list[int] = []
    for item in str(value or "").split("|"):
        if not item:
            continue
        try:
            number = int(item)
        except ValueError as exc:
            raise ValueError("分类 ID 只能包含数字") from exc
        if number not in result:
            result.append(number)
    return result


def _parse_period_pipe(value: Any) -> list[str]:
    return [str(item or "all") for item in str(value or "").split("|")] if value else []


def _parse_code_pipe(value: Any, allowed: set[str], field: str) -> set[str]:
    values = {item for item in str(value or "").split("|") if item and item != "all"}
    if not values.issubset(allowed):
        raise ValueError(f"{field} 包含无效选项")
    return values


def _business_unit_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("country_category") or ""),
        str(row.get("store") or ""),
        str(row.get("msku") or ""),
    )


def _missing_metric_units(rows: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    all_units = {_business_unit_key(row) for row in rows}
    matched_units = {_business_unit_key(row) for row in rows if row.get("_metric_present")}
    return all_units - matched_units


def _public_business_row(row: dict[str, Any]) -> dict[str, Any]:
    stockout_before_roles = [
        {
            "id": int(item["label_id"]),
            "label": STOCKOUT_BEFORE_ROLE_LABELS[int(item["label_id"])],
            "period": item.get("label_period") or "",
        }
        for item in sorted(
            row.get("_label_facts") or [],
            key=lambda item: (
                str(item.get("label_period") or ""),
                int(item.get("label_id") or 0),
            ),
        )
        if int(item["detail"]["label_id"]) == STOCKOUT_BEFORE_ROLE_PARENT_ID
        and int(item.get("label_id") or 0) in STOCKOUT_BEFORE_ROLE_IDS
    ]
    role_diagnostics = [
        {
            "parent_id": int(item["detail"]["label_id"]),
            "parent_label": item["detail"].get("label_name") or "",
            "id": int(item["label_id"]),
            "label": item["detail"].get("sub_label_name") or "",
            "period": item.get("label_period") or "",
            "country": item.get("country") or "",
            "evidence_available": bool(item.get("evidence_available")),
        }
        for item in sorted(
            row.get("_label_facts") or [],
            key=lambda item: (
                int(item["detail"]["label_id"]),
                int(item["label_id"]),
                str(item.get("country") or ""),
            ),
        )
        if int(item["detail"]["label_id"]) in DIAGNOSTIC_PARENT_IDS
    ]
    labels = [
        {
            "parent_id": int(item["detail"]["label_id"]),
            "parent_label": item["detail"].get("label_name") or "",
            "id": int(item["label_id"]),
            "label": item["detail"].get("sub_label_name") or "",
            "period": item.get("label_period") or "",
        }
        for item in sorted(
            row.get("_label_facts") or [],
            key=lambda item: (
                int(item["detail"]["label_id"]),
                int(item["label_id"]),
                str(item.get("label_period") or ""),
            ),
        )
        if int(item["detail"]["label_id"]) not in EXCLUDED_ANALYSIS_PARENT_IDS
    ]
    summary_groups: dict[tuple[int, int], dict[str, Any]] = {}
    for item in labels:
        group = summary_groups.setdefault(
            (item["parent_id"], item["id"]),
            {"parent_label": item["parent_label"], "label": item["label"], "periods": []},
        )
        if item["period"] and item["period"] not in group["periods"]:
            group["periods"].append(item["period"])
    label_summary = " / ".join(
        f"{item['parent_label']}：{item['label']}"
        + (f"（{'/'.join(sorted(item['periods'], key=_period_order))}）" if item["periods"] else "")
        for item in summary_groups.values()
    )
    public = {key: value for key, value in row.items() if not key.startswith("_")}
    metric_present = row.get("_metric_present", row.get("metric_present", True))
    diagnostic_labels = list(dict.fromkeys(item["label"] for item in role_diagnostics))
    return {
        **public,
        "metric_present": bool(metric_present),
        "labels": labels,
        "label_summary": label_summary,
        "stockout_before_roles": stockout_before_roles,
        "role_diagnostics": role_diagnostics,
        "role_diagnostic_summary": " / ".join(diagnostic_labels),
        "role_diagnostic_count": len(role_diagnostics),
    }


class LabelHubDataService:
    """Read-only aggregation service for the dynamic label dashboard."""

    def __init__(self) -> None:
        self._dashboard = dashboard_service
        self._local_metrics = label_hub_local_metrics_service
        self._meta_cache: dict[str, Any] | None = None
        self._meta_cache_at: datetime | None = None
        self._details_cache: tuple[datetime, list[dict[str, Any]]] | None = None
        self._facts_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._facts_load_lock = threading.Lock()
        self._facts_load_events: dict[str, threading.Event] = {}
        self._diagnostic_facts_cache: dict[tuple[str, int], tuple[datetime, list[dict[str, Any]]]] = {}
        self._metrics_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
        self._payload_cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = {}
        self._diagnostic_rows_cache: dict[tuple[Any, ...], tuple[datetime, list[dict[str, Any]]]] = {}
        self._payload_cache_lock = threading.Lock()
        self._comparison_dates: list[str] = []
        self._comparison_warm_lock = threading.Lock()
        self._comparison_warm_events: dict[tuple[str, str], threading.Event] = {}
        self._source_state_lock = threading.Lock()
        self._source_validation_running = False
        self._source_quick_checked_at: datetime | None = None
        self._source_content_checked_at: datetime | None = None
        self._source_quick_fingerprint: tuple[Any, ...] | None = None
        self._source_content_fingerprint: tuple[Any, ...] | None = None
        self._source_validation_started_at = datetime.now()
        self._source_generation = 0
        self._source_invalidation_callbacks: list[Callable[[], None]] = []

    @staticmethod
    def _payload_cache_key(data_date: str, metric_period: str, filters: dict[str, Any]) -> tuple[Any, ...]:
        """Build a stable key for the public dashboard response."""
        keys = (
            "country_category", "store", "keyword", "parent_label_id", "compare_parent_id",
            "analysis_parent_ids", "analysis_periods", "conditions", "label_period",
            "sales_roles", "sales_trends", "daily_sales_bands", "margin_bands", "problem",
            "page", "page_size", "sort_field", "sort_dir",
        )
        return (data_date, metric_period, *(str(filters.get(key) or "") for key in keys))

    @staticmethod
    def _diagnostic_rows_cache_key(data_date: str, metric_period: str, filters: dict[str, Any]) -> tuple[Any, ...]:
        keys = (
            "country_category", "store", "keyword", "parent_label_id", "compare_parent_id",
            "analysis_parent_ids", "analysis_periods", "conditions", "label_period",
            "sales_roles", "sales_trends", "daily_sales_bands", "margin_bands", "problem",
        )
        return (data_date, metric_period, *(str(filters.get(key) or "") for key in keys))

    def _get_cached_payload(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        now = datetime.now()
        with self._payload_cache_lock:
            cached = self._payload_cache.get(key)
            if cached and (now - cached[0]).total_seconds() < CACHE_SECONDS:
                return cached[1]
            if cached:
                self._payload_cache.pop(key, None)
        return None

    def _cache_payload(self, key: tuple[Any, ...], payload: dict[str, Any]) -> None:
        with self._payload_cache_lock:
            self._payload_cache[key] = (datetime.now(), payload)
            if len(self._payload_cache) > 64:
                oldest_key = min(self._payload_cache, key=lambda item: self._payload_cache[item][0])
                self._payload_cache.pop(oldest_key, None)

    def register_source_invalidation_callback(self, callback: Callable[[], None]) -> None:
        self._source_invalidation_callbacks.append(callback)

    def _invalidate_remote_caches(self) -> None:
        self._meta_cache = None
        self._meta_cache_at = None
        self._details_cache = None
        self._facts_cache.clear()
        self._diagnostic_facts_cache.clear()
        self._comparison_dates = []
        with self._payload_cache_lock:
            self._payload_cache.clear()
            self._diagnostic_rows_cache.clear()
        with self._source_state_lock:
            self._source_generation += 1
        for callback in tuple(self._source_invalidation_callbacks):
            try:
                callback()
            except Exception:
                # A secondary view must not prevent the shared cache from refreshing.
                continue

    def _schedule_source_validation(self) -> None:
        now = datetime.now()
        with self._source_state_lock:
            if self._source_validation_running:
                return
            if (
                self._source_quick_checked_at
                and (now - self._source_quick_checked_at).total_seconds() < SOURCE_QUICK_CHECK_SECONDS
            ):
                return
            self._source_validation_running = True

        def validate() -> None:
            try:
                quick_fingerprint = self._fetch_quick_source_fingerprint()
                quick_changed = False
                run_content_check = False
                with self._source_state_lock:
                    quick_changed = (
                        self._source_quick_fingerprint is not None
                        and self._source_quick_fingerprint != quick_fingerprint
                    )
                    self._source_quick_fingerprint = quick_fingerprint
                    self._source_quick_checked_at = datetime.now()
                    initial_delay_elapsed = (
                        datetime.now() - self._source_validation_started_at
                    ).total_seconds() >= SOURCE_INITIAL_CONTENT_CHECK_DELAY_SECONDS
                    if initial_delay_elapsed and self._source_content_checked_at is None:
                        self._source_content_checked_at = datetime.now()
                    run_content_check = (
                        not quick_changed
                        and self._source_content_checked_at is not None
                        and (
                            datetime.now() - self._source_content_checked_at
                        ).total_seconds() >= SOURCE_CONTENT_CHECK_SECONDS
                    )
                    if quick_changed:
                        self._source_content_fingerprint = None
                if quick_changed:
                    self._invalidate_remote_caches()

                if run_content_check:
                    content_fingerprint = self._fetch_content_source_fingerprint()
                    content_changed = False
                    with self._source_state_lock:
                        content_changed = (
                            self._source_content_fingerprint is not None
                            and self._source_content_fingerprint != content_fingerprint
                        )
                        self._source_content_fingerprint = content_fingerprint
                        self._source_content_checked_at = datetime.now()
                    if content_changed:
                        self._invalidate_remote_caches()
            except Exception:
                # Validation is advisory. A temporary fingerprint failure must not
                # turn a valid cached dashboard into an error page.
                with self._source_state_lock:
                    self._source_quick_checked_at = datetime.now()
            finally:
                with self._source_state_lock:
                    self._source_validation_running = False

        threading.Thread(
            target=validate,
            name="label-hub-source-validation",
            daemon=True,
        ).start()

    def force_source_refresh(self) -> dict[str, Any]:
        quick_fingerprint = self._fetch_quick_source_fingerprint()
        self._invalidate_remote_caches()
        with self._source_state_lock:
            self._source_quick_fingerprint = quick_fingerprint
            self._source_quick_checked_at = datetime.now()
            # The next background validation rebuilds the deep fingerprint.
            # A manual refresh must not synchronously scan the full remote table.
            self._source_content_fingerprint = None
            self._source_content_checked_at = None
        return {"status": "refreshed", "generation": self._source_generation}

    def parse_conditions(self, value: str) -> dict[int, set[int]]:
        value = str(value or "").strip()
        if not value:
            return {}
        parsed: dict[int, set[int]] = {}
        for group in value.split(";"):
            parent_text, separator, children_text = group.partition(":")
            if not separator or not parent_text or not children_text:
                raise ValueError("conditions 格式应为 父标签:子标签|子标签")
            try:
                parent_id = int(parent_text)
                children = {int(item) for item in children_text.split("|") if item}
            except ValueError as exc:
                raise ValueError("conditions 只能包含数字标签 ID") from exc
            if not children or parent_id in parsed:
                raise ValueError("conditions 包含无效或重复的父标签")
            parsed[parent_id] = children
        return parsed

    def build_categories(self, details: list[dict[str, Any]], fact_stats: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in details:
            groups[int(item["label_id"])].append(item)
        result = []
        for label_id, children in sorted(groups.items()):
            children.sort(key=lambda item: int(item["sub_label_id"]))
            child_ids = [int(item["sub_label_id"]) for item in children]
            configured_priority = REMOTE_PARENT_CHILD_PRIORITY.get(label_id, [])
            priority_ids = [item for item in configured_priority if item in child_ids]
            priority_ids.extend(item for item in child_ids if item not in priority_ids)
            child_labels = {int(item["sub_label_id"]): item.get("sub_label_name") or str(item["sub_label_id"]) for item in children}
            stats = [fact_stats.get(int(item["sub_label_id"]), {}) for item in children]
            count = sum(int(item.get("fact_count") or 0) for item in stats)
            raw_states = {str(item.get("status") or "").strip().lower() for item in children}
            disabled = bool(raw_states) and all(state in {"未启用", "停用", "disabled", "inactive"} for state in raw_states)
            result.append(
                {
                    "id": label_id,
                    "label": children[0].get("label_name") or str(label_id),
                    "state": "disabled" if disabled else ("available" if count else "developing"),
                    "fact_count": count,
                    "latest_date": max((str(item.get("latest_date") or "") for item in stats), default=""),
                    "mutual_exclusion": any("互斥" in str(item.get("mutual_exclusion") or "") for item in children),
                    "aggregation_priority_ids": priority_ids,
                    "aggregation_priority_labels": [child_labels[item] for item in priority_ids],
                    "aggregation_rule": "同一国家类别 + 店铺 + MSKU 组合命中多个子标签时，按业务优先级只保留一个主标签。",
                    "children": [
                        {
                            "id": int(item["sub_label_id"]),
                            "label": item.get("sub_label_name") or str(item["sub_label_id"]),
                            "rule": item.get("tag_rule") or "",
                            "definition": item.get("business_definition") or "",
                            "owner": item.get("business_owner") or "",
                            "category": item.get("label_category") or "",
                            "frequency": item.get("update_frequency") or "",
                            "periods": sorted(fact_stats.get(int(item["sub_label_id"]), {}).get("periods") or [], key=_period_order),
                            "mutual_exclusion": item.get("mutual_exclusion") or "",
                            "status": item.get("status") or "",
                            "tagging_method": item.get("tagging_method") or "",
                        }
                        for item in children
                    ],
                }
            )
        return result

    def build_stockout_before_role_summary(
        self,
        *,
        details: list[dict[str, Any]],
        facts: list[dict[str, Any]],
        role_period: str,
    ) -> dict[str, Any]:
        if role_period not in STOCKOUT_BEFORE_ROLE_PERIODS:
            raise ValueError("role_period 不存在")

        stockout_keys = {
            _business_unit_key(fact)
            for fact in facts
            if int(fact.get("label_id") or 0) == CURRENT_STOCKOUT_CHILD_ID
            and str(fact.get("label_period") or "") == "current"
        }
        roles_by_key: dict[tuple[str, str, str], set[int]] = defaultdict(set)
        for fact in facts:
            role_id = int(fact.get("label_id") or 0)
            if role_id not in STOCKOUT_BEFORE_ROLE_IDS:
                continue
            if str(fact.get("label_period") or "") != role_period:
                continue
            key = _business_unit_key(fact)
            if key in stockout_keys:
                roles_by_key[key].add(role_id)

        role_keys: dict[int, set[tuple[str, str, str]]] = {
            role_id: set() for role_id in STOCKOUT_BEFORE_ROLE_IDS
        }
        conflict_keys: set[tuple[str, str, str]] = set()
        missing_keys: set[tuple[str, str, str]] = set()
        for key in stockout_keys:
            role_ids = roles_by_key.get(key, set())
            if len(role_ids) == 1:
                role_keys[next(iter(role_ids))].add(key)
            elif len(role_ids) > 1:
                conflict_keys.add(key)
            else:
                missing_keys.add(key)

        total = len(stockout_keys)
        identified_count = sum(len(keys) for keys in role_keys.values())
        return {
            "role_period": role_period,
            "available_periods": list(STOCKOUT_BEFORE_ROLE_PERIODS),
            "scope": {
                "business_unit_count": total,
                "unique_msku_count": len({key[2] for key in stockout_keys}),
            },
            "roles": [
                {
                    "id": role_id,
                    "label": STOCKOUT_BEFORE_ROLE_LABELS[role_id],
                    "business_unit_count": len(role_keys[role_id]),
                    "unique_msku_count": len({key[2] for key in role_keys[role_id]}),
                    "share": round(len(role_keys[role_id]) / total, 4) if total else 0,
                }
                for role_id in STOCKOUT_BEFORE_ROLE_IDS
            ],
            "coverage": {
                "identified_count": identified_count,
                "missing_count": len(missing_keys),
                "conflict_count": len(conflict_keys),
                "rate": round(identified_count / total, 4) if total else 0,
            },
        }

    def derive_stockout_operating_trend(
        self,
        period_evidence: dict[str, dict[str, Any]],
        *,
        baseline_role_id: int,
    ) -> dict[str, Any]:
        """Derive a pre-stockout trend from cumulative, stockout-anchored windows."""

        def unavailable(*reasons: str) -> dict[str, Any]:
            return {
                "trend_code": "unavailable",
                "trend_label": STOCKOUT_OPERATING_TREND_LABELS["unavailable"],
                "trend_reason": reasons[0] if reasons else "required_evidence_missing",
                "quality_reasons": list(dict.fromkeys(reasons or ("required_evidence_missing",))),
                "long_term_consistency": "unavailable",
                "baseline_metrics": {},
                "interval_metrics": {},
            }

        def parse_period(period: str) -> tuple[dict[str, Any] | None, str | None]:
            fact = period_evidence.get(period)
            if not fact:
                return None, "required_evidence_missing"
            evidence = _evidence_object(fact.get("evidence_json"))
            metrics = evidence.get("metrics") or {}
            window = evidence.get("window") or {}
            oos = evidence.get("oos") or {}
            try:
                days = int(period.removesuffix("d"))
                window_days = int(window.get("days"))
                window_start = date.fromisoformat(str(window.get("start") or ""))
                window_end = date.fromisoformat(str(window.get("end") or ""))
                oos_start = date.fromisoformat(str(oos.get("oos_start_date") or ""))
            except (TypeError, ValueError):
                return None, "window_evidence_incomplete"
            qty = _number(metrics.get("period_sales_qty"))
            if evidence.get("type") not in {"pre_oos_sales_role", "pre_oos_station_sales_role"} or qty is None or qty < 0:
                return None, "period_metrics_invalid"
            if (
                str(fact.get("label_period") or window.get("period") or "") != period
                or str(window.get("period") or "") != period
                or window_days != days
                or window_end != oos_start - timedelta(days=1)
                or window_start != window_end - timedelta(days=days - 1)
            ):
                return None, "window_not_anchored_before_stockout"
            return {
                "qty": qty,
                "role_id": int(fact.get("label_id") or 0),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }, None

        parsed: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for period in ("7d", "14d", "30d"):
            item, error = parse_period(period)
            if error:
                errors.append(error)
            elif item:
                parsed[period] = item
        if errors:
            return unavailable(*errors)

        q7 = parsed["7d"]["qty"]
        q14 = parsed["14d"]["qty"]
        q30 = parsed["30d"]["qty"]
        if q7 > q14 or q14 > q30:
            return unavailable("cumulative_metrics_non_monotonic")

        last7 = q7 / 7
        prior7 = (q14 - q7) / 7
        last14 = q14 / 14
        prior16 = (q30 - q14) / 16

        def change(current: float, previous: float) -> float | None:
            if previous == 0:
                return None
            return (current - previous) / previous

        short_change = change(last7, prior7)
        medium_change = change(last14, prior16)
        interval_metrics = {
            "last7_daily_sales": round(last7, 6),
            "prior7_daily_sales": round(prior7, 6),
            "last14_daily_sales": round(last14, 6),
            "prior16_daily_sales": round(prior16, 6),
            "last7_vs_prior7_change": round(short_change, 6) if short_change is not None else None,
            "last14_vs_prior16_change": round(medium_change, 6) if medium_change is not None else None,
        }

        if q30 > 0 and q7 == 0:
            trend_code = "stopped"
            trend_reason = "last_7_days_zero_sales"
        elif q7 > 0 and q14 - q7 == 0:
            trend_code = "recent_start"
            trend_reason = "sales_started_in_last_7_days"
        elif (
            short_change is not None
            and medium_change is not None
            and ((short_change >= 0.30 and medium_change <= -0.10)
                 or (short_change <= -0.30 and medium_change >= 0.10))
        ):
            trend_code = "volatile"
            trend_reason = "short_and_medium_signals_conflict"
        else:
            role7_level = STOCKOUT_ROLE_LEVELS.get(parsed["7d"]["role_id"])
            baseline_level = STOCKOUT_ROLE_LEVELS.get(int(baseline_role_id or 0))
            if (
                short_change is not None
                and medium_change is not None
                and short_change >= 0.30
                and medium_change >= 0.10
                and role7_level is not None
                and baseline_level is not None
                and role7_level >= baseline_level
            ):
                trend_code = "accelerating"
                trend_reason = "short_and_medium_sales_accelerated"
            elif (
                short_change is not None
                and medium_change is not None
                and short_change <= -0.30
                and medium_change <= -0.10
                and role7_level is not None
                and baseline_level is not None
                and role7_level <= baseline_level
            ):
                trend_code = "slowing"
                trend_reason = "short_and_medium_sales_slowed"
            else:
                trend_code = "stable"
                trend_reason = "no_material_directional_change"

        long_term_consistency = "unavailable"
        item90, error90 = parse_period("90d")
        if not error90 and item90 and item90["qty"] >= q30:
            baseline_level = STOCKOUT_ROLE_LEVELS.get(int(baseline_role_id or 0))
            long_level = STOCKOUT_ROLE_LEVELS.get(item90["role_id"])
            if baseline_level is not None and long_level is not None:
                if baseline_level == long_level:
                    long_term_consistency = "same"
                elif baseline_level > long_level:
                    long_term_consistency = "higher_than_long_term"
                else:
                    long_term_consistency = "lower_than_long_term"

        return {
            "trend_code": trend_code,
            "trend_label": STOCKOUT_OPERATING_TREND_LABELS[trend_code],
            "trend_reason": trend_reason,
            "quality_reasons": [],
            "long_term_consistency": long_term_consistency,
            "baseline_metrics": {"period_sales_qty": q30, "daily_sales": round(q30 / 30, 6)},
            "interval_metrics": interval_metrics,
        }

    def build_stockout_operating_status_summary(
        self,
        *,
        facts: list[dict[str, Any]],
        role_period: str,
        scope: str = "business_unit",
        include_members: bool = False,
    ) -> dict[str, Any]:
        if role_period not in STOCKOUT_BEFORE_ROLE_PERIODS:
            raise ValueError("断货经营状态周期不存在")
        if scope not in {"business_unit", "country"}:
            raise ValueError("断货经营状态维度不存在")

        business_stockout_by_key = {
            _business_unit_key(fact): fact
            for fact in facts
            if int(fact.get("label_id") or 0) == CURRENT_STOCKOUT_CHILD_ID
            and str(fact.get("label_period") or "") == "current"
        }
        role_ids = STOCKOUT_BEFORE_ROLE_IDS if scope == "business_unit" else COUNTRY_STOCKOUT_BEFORE_ROLE_IDS

        def record_key(fact: dict[str, Any]) -> tuple[str, ...]:
            if scope == "country":
                return (
                    str(fact.get("country_category") or ""),
                    str(fact.get("country") or ""),
                    str(fact.get("store") or ""),
                    str(fact.get("msku") or ""),
                )
            return _business_unit_key(fact)

        if scope == "country":
            excluded_universe_ids = {
                CURRENT_STOCKOUT_CHILD_ID,
                *STOCKOUT_BEFORE_ROLE_IDS,
                *COUNTRY_STOCKOUT_BEFORE_ROLE_IDS,
            }
            country_universe = {
                record_key(fact)
                for fact in facts
                if str(fact.get("country") or "")
                and int(fact.get("label_id") or 0) not in excluded_universe_ids
                and _business_unit_key(fact) in business_stockout_by_key
            }
            stockout_by_key = {
                key: business_stockout_by_key[(key[0], key[2], key[3])]
                for key in country_universe
            }
        else:
            stockout_by_key = business_stockout_by_key

        role_facts_by_key_period: dict[tuple[str, ...], dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for fact in facts:
            if int(fact.get("label_id") or 0) not in role_ids:
                continue
            period = str(fact.get("label_period") or "")
            if period in STOCKOUT_BEFORE_ROLE_PERIODS:
                role_facts_by_key_period[record_key(fact)][period].append(fact)
        role_by_key = {
            key: by_period["30d"][0]
            for key, by_period in role_facts_by_key_period.items()
            if len(by_period.get("30d") or []) == 1
        }
        status_keys = {code: set() for code, _, _ in STOCKOUT_OPERATING_STATUS_DEFINITIONS}
        insufficient_reason_keys = {code: set() for code in STOCKOUT_EVIDENCE_REASON_LABELS}
        problem_reason_keys: dict[str, set[tuple[str, ...]]] = {
            "loss": set(),
            "low_margin": set(),
            "invalid_rank": set(),
        }
        evaluable_codes = {
            "full_period_zero_sales",
            "star",
            "potential",
            "dog",
            "loss_issue",
            "low_margin_issue",
        }
        expected_days = 30
        trend_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        def mark_insufficient(key: tuple[str, ...], reason: str) -> None:
            status_keys["pre_oos_evidence_insufficient"].add(key)
            insufficient_reason_keys[reason].add(key)

        def parse_iso_date(value: Any) -> date | None:
            try:
                return date.fromisoformat(str(value or ""))
            except ValueError:
                return None

        for key, stockout_fact in stockout_by_key.items():
            stockout_metrics = _evidence_object(stockout_fact.get("evidence_json")).get("metrics") or {}
            fba_available = _number(stockout_metrics.get("fba_available"))
            fba_in_transit = _number(stockout_metrics.get("fba_in_transit"))
            local_quantity = _number(stockout_metrics.get("local_quantity"))
            if fba_available is None or fba_in_transit is None or local_quantity is None:
                mark_insufficient(key, "inventory_evidence_missing")
                continue
            if fba_available != 0 or fba_in_transit < 0 or local_quantity < 0:
                mark_insufficient(key, "inventory_evidence_conflict")
                continue
            supply_total = fba_in_transit + local_quantity
            if supply_total < STOCKOUT_LOW_SUPPLY_THRESHOLD:
                status_keys["low_inventory_edge"].add(key)
                continue

            role_fact = role_by_key.get(key)
            if not role_fact:
                mark_insufficient(key, "role_missing")
                continue

            evidence = _evidence_object(role_fact.get("evidence_json"))
            metrics = evidence.get("metrics") or {}
            oos = evidence.get("oos") or {}
            window = evidence.get("window") or {}
            calculation = evidence.get("calculation") or {}
            daily_sales = _number(metrics.get("daily_sales"))
            period_sales_qty = _number(metrics.get("period_sales_qty"))
            margin_rate = _number(metrics.get("tag_margin_rate"))
            window_start = parse_iso_date(window.get("start"))
            window_end = parse_iso_date(window.get("end"))
            oos_start = parse_iso_date(oos.get("oos_start_date"))
            window_days = _number(window.get("days"))
            if (
                evidence.get("type") not in {"pre_oos_sales_role", "pre_oos_station_sales_role"}
                or daily_sales is None
                or period_sales_qty is None
                or window_start is None
                or window_end is None
                or oos_start is None
                or window_days is None
            ):
                mark_insufficient(key, "role_evidence_incomplete")
                continue
            if (
                str(window.get("period") or "") != "30d"
                or int(window_days) != expected_days
                or window_start > window_end
                or window_end >= oos_start
                or daily_sales < 0
                or period_sales_qty < 0
            ):
                mark_insufficient(key, "role_evidence_conflict")
                continue

            calculation_mode = str(calculation.get("mode") or "")
            if calculation_mode == "historical_backtrack":
                is_station_evidence = evidence.get("type") == "pre_oos_station_sales_role"
                if not is_station_evidence and str(calculation.get("status") or "") != "matched":
                    mark_insufficient(key, "calculation_abnormal")
                    continue
                history_start = parse_iso_date(oos.get("history_start_date"))
                if history_start is None and not is_station_evidence:
                    mark_insufficient(key, "role_evidence_incomplete")
                    continue
                if history_start is not None and history_start > window_start and not is_station_evidence:
                    mark_insufficient(key, "history_coverage_insufficient")
                    continue
            elif calculation_mode == "copy_previous_day_sales_role":
                source_role = evidence.get("source_sales_role") or {}
                if not calculation.get("source_role_data_date") or not source_role.get("sub_label_id"):
                    mark_insufficient(key, "role_evidence_incomplete")
                    continue
            else:
                mark_insufficient(key, "calculation_abnormal")
                continue

            role_id = int(role_fact.get("label_id") or 0)
            if period_sales_qty == 0:
                status_code = "full_period_zero_sales"
            elif role_id in {2001, 2101}:
                status_code = "star"
            elif role_id in {2002, 2102}:
                status_code = "potential"
            elif role_id in {2003, 2103}:
                status_code = "dog"
            elif role_id == 2104:
                status_code = "loss_issue" if margin_rate is not None and margin_rate < 0 else "low_margin_issue"
            elif margin_rate is None:
                mark_insufficient(key, "role_evidence_incomplete")
                continue
            elif margin_rate < 0:
                status_code = "loss_issue"
            elif margin_rate <= 5:
                status_code = "low_margin_issue"
            else:
                mark_insufficient(key, "role_evidence_conflict")
                continue
            status_keys[status_code].add(key)
            if status_code == "loss_issue":
                problem_reason_keys["loss"].add(key)
            if status_code == "low_margin_issue" and margin_rate is not None and margin_rate <= 5:
                problem_reason_keys["low_margin"].add(key)
            if role_id == 2104:
                small_rank = _number(metrics.get("small_rank"))
                if small_rank is None or small_rank <= 0 or small_rank >= 99999:
                    problem_reason_keys["invalid_rank"].add(key)
            if status_code != "full_period_zero_sales":
                period_facts = role_facts_by_key_period.get(key) or {}
                if any(len(period_facts.get(period) or []) > 1 for period in STOCKOUT_BEFORE_ROLE_PERIODS):
                    trend_by_key[key] = {
                        "trend_code": "unavailable",
                        "trend_label": STOCKOUT_OPERATING_TREND_LABELS["unavailable"],
                        "trend_reason": "period_role_evidence_conflict",
                        "quality_reasons": ["period_role_evidence_conflict"],
                        "long_term_consistency": "unavailable",
                        "baseline_metrics": {},
                        "interval_metrics": {},
                    }
                else:
                    trend_by_key[key] = self.derive_stockout_operating_trend(
                        {
                            period: period_items[0]
                            for period, period_items in period_facts.items()
                            if len(period_items) == 1
                        },
                        baseline_role_id=role_id,
                    )

        total = len(stockout_by_key)
        evaluable_count = sum(len(status_keys[code]) for code in evaluable_codes)
        non_evaluable_count = total - evaluable_count
        group_totals = {
            "evaluable": evaluable_count,
            "not_evaluable": non_evaluable_count,
        }
        insufficient_count = len(status_keys["pre_oos_evidence_insufficient"])
        payload = {
            "role_period": role_period,
            "evidence_period": role_period,
            "baseline_period": "30d",
            "available_periods": list(STOCKOUT_BEFORE_ROLE_PERIODS),
            "scope_mode": scope,
            "scope": (
                {
                    "country_record_count": total,
                    "matched_business_unit_count": len({(key[0], key[2], key[3]) for key in stockout_by_key}),
                    "unique_msku_count": len({key[3] for key in stockout_by_key}),
                    "business_unit_count": total,
                }
                if scope == "country"
                else {
                    "business_unit_count": total,
                    "unique_msku_count": len({key[2] for key in stockout_by_key}),
                }
            ),
            "supply": {
                "low_supply_threshold": STOCKOUT_LOW_SUPPLY_THRESHOLD,
                "threshold_operator": "<",
                "formula": "fba_in_transit + local_quantity",
            },
            "statuses": [
                {
                    "code": code,
                    "label": label,
                    "group": group,
                    "record_count": len(status_keys[code]),
                    "business_unit_count": len(status_keys[code]),
                    "share": round(len(status_keys[code]) / total, 4) if total else 0,
                    "group_share": round(len(status_keys[code]) / group_totals[group], 4)
                    if group_totals[group]
                    else 0,
                }
                for code, label, group in STOCKOUT_OPERATING_STATUS_DEFINITIONS
            ],
            "insufficient_reasons": [
                {
                    "code": code,
                    "label": label,
                    "count": len(insufficient_reason_keys[code]),
                    "share": round(len(insufficient_reason_keys[code]) / insufficient_count, 4)
                    if insufficient_count
                    else 0,
                }
                for code, label in STOCKOUT_EVIDENCE_REASON_LABELS.items()
                if insufficient_reason_keys[code]
            ],
            "problem_reason_summary": [
                {
                    "code": code,
                    "label": {"loss": "亏损", "low_margin": "低毛利", "invalid_rank": "排名无效"}[code],
                    "count": len(members),
                }
                for code, members in problem_reason_keys.items()
                if members
            ],
            "display_insufficient_breakdown": (
                [
                    {
                        "code": "history_data_insufficient",
                        "label": "历史数据不足",
                        "count": len(insufficient_reason_keys["history_coverage_insufficient"]),
                        "share": round(
                            len(insufficient_reason_keys["history_coverage_insufficient"])
                            / insufficient_count,
                            4,
                        )
                        if insufficient_count
                        else 0,
                    }
                ]
                if insufficient_reason_keys["history_coverage_insufficient"]
                else []
            ),
            "coverage": {
                "evaluable_count": evaluable_count,
                "evaluable_rate": round(evaluable_count / total, 4) if total else 0,
                "non_evaluable_count": non_evaluable_count,
                "non_evaluable_rate": round(non_evaluable_count / total, 4) if total else 0,
                "role_evidence_rate": round(
                    sum(1 for key in stockout_by_key if key in role_by_key) / total,
                    4,
                ) if total else 0,
            },
            "trend_definitions": [
                {"code": code, "label": label}
                for code, label in STOCKOUT_OPERATING_TREND_LABELS.items()
            ],
            "trend_summary_by_status": {},
        }
        trend_status_codes = ("star", "potential", "dog", "loss_issue", "low_margin_issue")
        for status_code in trend_status_codes:
            members = status_keys[status_code]
            counts = {
                trend_code: sum(
                    1
                    for key in members
                    if (trend_by_key.get(key) or {}).get("trend_code") == trend_code
                )
                for trend_code in STOCKOUT_OPERATING_TREND_LABELS
            }
            payload["trend_summary_by_status"][status_code] = [
                {
                    "code": trend_code,
                    "label": STOCKOUT_OPERATING_TREND_LABELS[trend_code],
                    "count": count,
                    "share": round(count / len(members), 4) if members else 0,
                }
                for trend_code, count in counts.items()
                if count
            ]
        problem_members = status_keys["loss_issue"] | status_keys["low_margin_issue"]
        payload["trend_summary_by_status"]["problem"] = [
            {
                "code": trend_code,
                "label": STOCKOUT_OPERATING_TREND_LABELS[trend_code],
                "count": count,
                "share": round(count / len(problem_members), 4) if problem_members else 0,
            }
            for trend_code in STOCKOUT_OPERATING_TREND_LABELS
            if (
                count := sum(
                    1
                    for key in problem_members
                    if (trend_by_key.get(key) or {}).get("trend_code") == trend_code
                )
            )
        ]
        if include_members:
            payload["_status_members"] = status_keys
            payload["_insufficient_reason_members"] = insufficient_reason_keys
            payload["_trend_members"] = {
                (status_code, trend_code): {
                    key
                    for key in status_keys[status_code]
                    if (trend_by_key.get(key) or {}).get("trend_code") == trend_code
                }
                for status_code in trend_status_codes
                for trend_code in STOCKOUT_OPERATING_TREND_LABELS
            }
            payload["_trend_members"].update({
                ("problem", trend_code): {
                    key
                    for key in problem_members
                    if (trend_by_key.get(key) or {}).get("trend_code") == trend_code
                }
                for trend_code in STOCKOUT_OPERATING_TREND_LABELS
            })
            payload["_trend_by_key"] = trend_by_key
        return payload

    def get_stockout_before_role_evidence(
        self,
        *,
        data_date: str,
        country_category: str,
        store: str,
        msku: str,
        role_period: str,
        country: str = "",
    ) -> dict[str, Any]:
        if role_period not in STOCKOUT_BEFORE_ROLE_PERIODS:
            raise ValueError("断货前销售角色周期不存在")
        if not all(str(value or "").strip() for value in (data_date, country_category, store, msku)):
            raise ValueError("查看断货前销售角色依据需要完整的日期、国家类别、店铺和 MSKU")

        params = {
            "data_date": data_date,
            "country_category": country_category,
            "store": store,
            "msku": msku,
            "role_period": role_period,
            "scope_mode": "country" if str(country or "").strip() else "business_unit",
            "snapshot_country": str(country or "").strip(),
        }
        country_text = str(country or "").strip()
        role_ids = COUNTRY_STOCKOUT_BEFORE_ROLE_IDS if country_text else STOCKOUT_BEFORE_ROLE_IDS
        role_labels = COUNTRY_STOCKOUT_BEFORE_ROLE_LABELS if country_text else STOCKOUT_BEFORE_ROLE_LABELS
        country_clause = "and f.country = %(country)s" if country_text else ""
        if country_text:
            params["country"] = country_text
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select f.data_date, f.country, f.country_category, f.store, f.msku,
                       f.label_id, f.label_period,
                       uncompress(f.evidence_blob) as evidence_json,
                       s.evidence_json as historical_operating_evidence_json
                from {LABEL_FACT_TABLE} f
                left join {STOCKOUT_HISTORICAL_RESULT_TABLE} s
                  on s.data_date = f.data_date
                 and s.scope_mode = %(scope_mode)s
                 and s.country_category = f.country_category
                 and s.store = f.store
                 and s.msku = f.msku
                 and s.country = %(snapshot_country)s
                where f.data_date = %(data_date)s
                  and f.country_category = %(country_category)s
                  and f.store = %(store)s
                  and f.msku = %(msku)s
                  {country_clause}
                  and f.label_period = %(role_period)s
                  and f.label_id in ({','.join(str(item) for item in role_ids)})
                order by f.label_id
                limit 1
                """,
                params,
            )
            row = cursor.fetchone()

        if not row:
            raise ValueError("当前国家没有对应周期的断货前销售角色依据" if country_text else "当前 MSKU 没有对应周期的断货前销售角色依据")
        raw_evidence = row.get("evidence_json")
        if isinstance(raw_evidence, dict):
            evidence = raw_evidence
        else:
            if isinstance(raw_evidence, (bytes, bytearray)):
                raw_evidence = raw_evidence.decode("utf-8", errors="replace")
            try:
                evidence = json.loads(str(raw_evidence or ""))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("断货前销售角色依据 JSON 无法解析") from exc
        if not isinstance(evidence, dict):
            raise ValueError("断货前销售角色依据 JSON 结构无效")

        role_id = int(row.get("label_id") or 0)
        return {
            "scope": "country" if country_text else "msku",
            "identity": {
                "data_date": _date_text(row.get("data_date")),
                "country_category": str(row.get("country_category") or ""),
                "store": str(row.get("store") or ""),
                "msku": str(row.get("msku") or ""),
                "country": str(row.get("country") or country_text),
            },
            "role": {
                "id": role_id,
                "label": role_labels.get(role_id, ""),
                "period": str(row.get("label_period") or role_period),
            },
            "evidence": evidence,
            "historical_role_history": _historical_role_history(
                row.get("historical_operating_evidence_json")
            ),
        }

    def _analysis_categories(self, details: list[dict[str, Any]], fact_stats: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            category
            for category in self.build_categories(details, fact_stats)
            if category["id"] not in EXCLUDED_ANALYSIS_PARENT_IDS
        ]

    def _filterable_categories(self, details: list[dict[str, Any]], fact_stats: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            category
            for category in self.build_categories(details, fact_stats)
            if category["id"] not in COUNTRY_SCOPE_PARENT_IDS
        ]

    @staticmethod
    def _unique_msku_count(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool] | None = None) -> int:
        return len({row["msku"] for row in rows if predicate is None or predicate(row)})

    @staticmethod
    def _bucket_stats(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], total_rows: int) -> dict[str, Any]:
        matched = [row for row in rows if predicate(row)]
        matched_count = len(matched)
        unique_msku_count = LabelHubDataService._unique_msku_count(matched)
        sales_amount = sum(row.get("sales_amount") or 0 for row in matched)
        gross_profit = sum(row.get("order_gross_profit") or 0 for row in matched)
        total_sales = sum(row.get("sales_amount") or 0 for row in rows)
        return {
            "msku_count": matched_count,
            "business_unit_count": matched_count,
            "unique_msku_count": unique_msku_count,
            "share": round(matched_count / total_rows, 4) if total_rows else 0,
            "sales_amount": round(sales_amount, 2),
            "sales_share": round(sales_amount / total_sales, 4) if total_sales else 0,
            "order_gross_profit": round(gross_profit, 2),
            "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
        }

    def build_payload(
        self,
        *,
        details,
        facts,
        metrics,
        data_date,
        parent_label_id,
        compare_parent_id,
        conditions,
        label_period,
        country_category,
        store,
        keyword,
        page,
        page_size,
        sort_field,
        sort_dir,
        analysis_parent_ids=None,
        analysis_periods=None,
        sales_roles=None,
        sales_trends=None,
        daily_sales_bands=None,
        margin_bands=None,
        problem="all",
        metric_scope=None,
        include_internal=False,
    ) -> dict[str, Any]:
        sales_roles = set(sales_roles or set())
        sales_trends = set(sales_trends or set())
        daily_sales_bands = set(daily_sales_bands or set())
        margin_bands = set(margin_bands or set())
        metric_scope = metric_scope or {"status": "available" if metrics else "no_snapshot", "window": {}}
        local_metrics_available = metric_scope.get("status") == "available"
        detail_by_id = {int(item["sub_label_id"]): item for item in details}
        categories = self._analysis_categories(details, {})
        filterable_categories = self._filterable_categories(details, {})
        category_by_id = {item["id"]: item for item in categories}
        filterable_category_by_id = {item["id"]: item for item in filterable_categories}
        if not categories:
            return {
                "scope": metric_scope,
                "population_summary": {"business_unit_count": 0, "unique_msku_count": 0, "cross_scope_msku_count": 0},
                "overview": [],
                "breakdowns": [],
                "rows": [],
                "total": 0,
                "page": 1,
                "page_size": page_size,
                "total_pages": 1,
            }
        if parent_label_id not in category_by_id:
            parent_label_id = categories[0]["id"]
        if compare_parent_id not in category_by_id or compare_parent_id == parent_label_id:
            compare_parent_id = 2 if 2 in category_by_id and parent_label_id != 2 else next((item["id"] for item in categories if item["id"] != parent_label_id), 0)

        child_parent = {
            child["id"]: category["id"]
            for category in filterable_categories
            for child in category["children"]
        }
        for parent, children in conditions.items():
            if parent not in filterable_category_by_id or any(child_parent.get(child) != parent for child in children):
                raise ValueError("conditions 包含不存在或归属错误的标签")

        requested_ids = [int(item) for item in (analysis_parent_ids or []) if int(item) in category_by_id]
        requested_periods = [str(item or "all") for item in (analysis_periods or [])]
        remote_slots: list[int | None] = [None, None, None]
        for index, candidate in enumerate(requested_ids[:3]):
            if candidate != parent_label_id and candidate not in remote_slots:
                remote_slots[index] = candidate
        fallback_ids = requested_ids + [2, 8, 9, 11, 7, 3] + [item["id"] for item in categories]
        for candidate in fallback_ids:
            if candidate == parent_label_id or candidate in remote_slots or candidate not in category_by_id:
                continue
            empty_slot = next((index for index, value in enumerate(remote_slots) if value is None), None)
            if empty_slot is None:
                break
            remote_slots[empty_slot] = candidate
        remote_ids = [parent_id for parent_id in remote_slots if parent_id is not None]
        analysis_period_by_parent = {
            parent_id: (
                requested_periods[index]
                if index < len(requested_ids) and requested_ids[index] == parent_id and index < len(requested_periods)
                else "all"
            )
            for index, parent_id in enumerate(remote_slots)
            if parent_id is not None
        }

        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        keyword_text = str(keyword or "").lower().strip()
        for fact in facts:
            msku = str(fact.get("msku") or "")
            if msku.startswith(REFUND_MSKU_PREFIX) or str(fact.get("data_date") or "") != data_date:
                continue
            detail = detail_by_id.get(int(fact.get("label_id") or 0))
            if not detail:
                continue
            if int(detail["label_id"]) in COUNTRY_SCOPE_PARENT_IDS:
                continue
            key = (str(fact.get("country_category") or ""), str(fact.get("store") or ""), msku)
            if country_category != "all" and key[0] != country_category:
                continue
            if store != "all" and key[1] != store:
                continue
            if keyword_text and keyword_text not in " ".join(key).lower():
                continue
            grouped[key].append({**fact, "detail": detail})

        def scoped_parent_children(
            by_parent: dict[int, set[int]],
            by_parent_period: dict[int, dict[str, set[int]]],
            parent: int,
        ) -> set[int]:
            if parent == parent_label_id and label_period != "all":
                return by_parent_period.get(parent, {}).get(label_period, set())
            analysis_period = analysis_period_by_parent.get(parent, "all")
            if analysis_period != "all":
                return by_parent_period.get(parent, {}).get(analysis_period, set())
            return by_parent.get(parent, set())

        def preferred_remote_child(
            by_parent: dict[int, set[int]],
            by_parent_period: dict[int, dict[str, set[int]]],
            parent: int,
        ) -> int | None:
            children = scoped_parent_children(by_parent, by_parent_period, parent)
            if not children:
                return None
            priority = category_by_id.get(parent, {}).get("aggregation_priority_ids", [])
            rank = {child_id: index for index, child_id in enumerate(priority)}
            return min(children, key=lambda child_id: (rank.get(child_id, len(rank)), child_id))

        baseline_rows: list[dict[str, Any]] = []
        for key, label_facts in grouped.items():
            by_parent: dict[int, set[int]] = defaultdict(set)
            by_parent_period: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
            for fact in label_facts:
                parent = int(fact["detail"]["label_id"])
                child = int(fact["label_id"])
                period = str(fact.get("label_period") or "")
                by_parent[parent].add(child)
                by_parent_period[parent][period].add(child)
            conflict_parents = {
                category["id"]
                for category in categories
                if category["mutual_exclusion"]
                and any(len(children) > 1 for children in by_parent_period.get(category["id"], {}).values())
            }
            metric = metrics.get(key)
            sales_role_label_id = preferred_remote_child(
                by_parent,
                by_parent_period,
                SALES_ROLE_PARENT_ID,
            )
            lifecycle_labels = [detail_by_id[child].get("sub_label_name") or "" for child in sorted(by_parent.get(2, set())) if child in detail_by_id]
            current_labels = [
                detail_by_id[child].get("sub_label_name") or ""
                for child in sorted(scoped_parent_children(by_parent, by_parent_period, parent_label_id))
                if child in detail_by_id
            ]
            baseline_rows.append(
                {
                    "country_category": key[0],
                    "store": key[1],
                    "msku": key[2],
                    "_label_facts": label_facts,
                    "_by_parent": by_parent,
                    "_by_parent_period": by_parent_period,
                    "_metric": metric or {},
                    "_metric_present": metric is not None,
                    "_sales_role_label_id": sales_role_label_id,
                    "conflict": bool(conflict_parents),
                    "conflict_parent_ids": sorted(conflict_parents),
                    "current_label": " / ".join(current_labels) or "未命中",
                    "sales_qty": _number((metric or {}).get("sales_qty")),
                    "daily_sales": _number((metric or {}).get("daily_sales")),
                    "sales_amount": _number((metric or {}).get("sales_amount")),
                    "order_gross_profit": _number((metric or {}).get("order_gross_profit")),
                    "order_gross_margin": _number((metric or {}).get("order_gross_margin")),
                    "sales_role": (metric or {}).get("sales_role") or "暂无数据",
                    "sales_role_code": (metric or {}).get("sales_role_code") or "missing",
                    "sales_trend": (metric or {}).get("sales_trend") or "暂无数据",
                    "sales_trend_code": (metric or {}).get("sales_trend_code") or "missing",
                    "sales_trend_ratio": _number((metric or {}).get("sales_trend_ratio")),
                    "daily_sales_band": (metric or {}).get("daily_sales_band") or "暂无数据",
                    "daily_sales_band_code": (metric or {}).get("daily_sales_band_code") or "missing",
                    "margin_band": (metric or {}).get("margin_band") or "暂无数据",
                    "margin_band_code": (metric or {}).get("margin_band_code") or "missing",
                    "lifecycle_label": " / ".join(lifecycle_labels) or "暂无数据",
                    "data_status": (
                        "本地指标可用"
                        if metric is not None
                        else (
                            "暂无本地经营数据"
                            if local_metrics_available
                            else ("当前日期无本地经营快照" if metric_scope.get("status") == "no_snapshot" else "本地经营指标暂不可用")
                        )
                    ),
                }
            )
            row = baseline_rows[-1]
            for field in (
                "sales_amount_ex_tax",
                "ending_inventory_qty",
                "avg_inventory_qty",
                "settlement_gross_profit",
                "settlement_gross_margin",
                "ad_spend",
                "ad_sales",
                "ad_orders",
                "ad_clicks",
                "ad_impressions",
                "acos",
                "tacos",
                "sessions_total",
                "return_count",
                "return_amount",
                "net_amount",
            ):
                row[field] = _number((metric or {}).get(field))
            issue_pairs = []
            if row["conflict"]:
                issue_pairs.append(("conflict", "标签冲突"))
            if metric is None:
                issue_pairs.append(("missing_metrics", "指标缺失"))
            else:
                if (row.get("daily_sales") or 0) <= 0:
                    issue_pairs.append(("zero_sales", "日销为 0"))
                if (row.get("order_gross_profit") or 0) < 0:
                    issue_pairs.append(("negative_profit", "订单毛利为负"))
                if row.get("_sales_role_label_id") == PROBLEM_PRODUCT_CHILD_ID:
                    issue_pairs.append(("problem_role", "问题产品"))
            row["issue_codes"] = [code for code, _ in issue_pairs]
            row["issue_labels"] = [label for _, label in issue_pairs]

        overview = []
        base_count = len(baseline_rows)
        base_mskus = {row["msku"] for row in baseline_rows}
        base_unique_count = len(base_mskus)
        msku_scopes: dict[str, set[tuple[str, str]]] = defaultdict(set)
        parent_counts: dict[int, int] = defaultdict(int)
        child_counts: dict[tuple[int, int], int] = defaultdict(int)
        parent_mskus: dict[int, set[str]] = defaultdict(set)
        child_mskus: dict[tuple[int, int], set[str]] = defaultdict(set)
        parent_periods: dict[int, set[str]] = defaultdict(set)
        for row in baseline_rows:
            msku_scopes[row["msku"]].add((row["country_category"], row["store"]))
            for parent_id, child_ids in row["_by_parent"].items():
                parent_counts[parent_id] += 1
                parent_mskus[parent_id].add(row["msku"])
                for child_id in child_ids:
                    child_counts[(parent_id, child_id)] += 1
                    child_mskus[(parent_id, child_id)].add(row["msku"])
            for parent_id, periods in row["_by_parent_period"].items():
                parent_periods[parent_id].update(period for period in periods if period)
        for category in categories:
            parent_count = parent_counts[category["id"]]
            display_state = category["state"] if category["state"] == "disabled" else ("available" if parent_count else "developing")
            category["state"] = display_state
            child_rows = []
            for child in category["children"]:
                count = child_counts[(category["id"], child["id"])]
                unique_count = len(child_mskus[(category["id"], child["id"])])
                child_rows.append({
                    **child,
                    "msku_count": count,
                    "business_unit_count": count,
                    "unique_msku_count": unique_count,
                    "coverage_rate": round(count / base_count, 4) if base_count else 0,
                    "unique_msku_coverage_rate": round(unique_count / base_unique_count, 4) if base_unique_count else 0,
                })
            periods = sorted(parent_periods[category["id"]], key=_period_order)
            unique_count = len(parent_mskus[category["id"]])
            overview.append({
                **category,
                "msku_count": parent_count,
                "business_unit_count": parent_count,
                "unique_msku_count": unique_count,
                "coverage_rate": round(parent_count / base_count, 4) if base_count else 0,
                "unique_msku_coverage_rate": round(unique_count / base_unique_count, 4) if base_unique_count else 0,
                "periods": periods,
                "children": child_rows,
            })

        population_summary = {
            "business_unit_count": base_count,
            "unique_msku_count": base_unique_count,
            "cross_scope_msku_count": sum(1 for scopes in msku_scopes.values() if len(scopes) > 1),
        }

        for analysis_parent_id, analysis_period in list(analysis_period_by_parent.items()):
            if analysis_period != "all" and analysis_period not in parent_periods.get(analysis_parent_id, set()):
                analysis_period_by_parent[analysis_parent_id] = "all"

        def in_current_parent_scope(row: dict[str, Any]) -> bool:
            return bool(scoped_parent_children(row["_by_parent"], row["_by_parent_period"], parent_label_id))

        def row_parent_children(row: dict[str, Any], parent: int) -> set[int]:
            return scoped_parent_children(row["_by_parent"], row["_by_parent_period"], parent)

        def preferred_remote_children(source_rows: list[dict[str, Any]], parent: int) -> dict[tuple[str, str, str], int]:
            children_by_unit: dict[tuple[str, str, str], set[int]] = defaultdict(set)
            for row in source_rows:
                children_by_unit[_business_unit_key(row)].update(row_parent_children(row, parent))
            priority = category_by_id.get(parent, {}).get("aggregation_priority_ids", [])
            rank = {child_id: index for index, child_id in enumerate(priority)}
            return {
                unit: min(children, key=lambda child_id: (rank.get(child_id, len(rank)), child_id))
                for unit, children in children_by_unit.items()
                if children
            }

        def preferred_local_values(source_rows: list[dict[str, Any]], field: str) -> dict[tuple[str, str, str], str]:
            values_by_unit: dict[tuple[str, str, str], set[str]] = defaultdict(set)
            for row in source_rows:
                if row["_metric_present"]:
                    values_by_unit[_business_unit_key(row)].add(str(row.get(field) or "missing"))
            priority = LOCAL_VALUE_PRIORITY[field]
            rank = {value: index for index, value in enumerate(priority)}
            return {
                unit: min(values, key=lambda value: (rank.get(value, len(rank)), value))
                for unit, values in values_by_unit.items()
                if values
            }

        def row_matches(row: dict[str, Any], skip_local: str | None = None, skip_parent: int | None = None, include_problem: bool = True) -> bool:
            if not in_current_parent_scope(row):
                return False
            for parent, children in conditions.items():
                if parent == skip_parent:
                    continue
                if not row_parent_children(row, parent).intersection(children):
                    return False
            local_filters = {
                "sales_role": (sales_roles, "sales_role_code"),
                "sales_trend": (sales_trends, "sales_trend_code"),
                "daily_sales_band": (daily_sales_bands, "daily_sales_band_code"),
                "margin_band": (margin_bands, "margin_band_code"),
            }
            for key, (selected, field) in local_filters.items():
                if key != skip_local and selected and row.get(field) not in selected:
                    return False
            if not include_problem or problem in {"", "all"}:
                return True
            return {
                "conflict": row["conflict"],
                "missing_metrics": local_metrics_available and not row["_metric_present"],
                "zero_sales": row.get("daily_sales_band_code") == "zero",
                "negative_profit": (row.get("order_gross_profit") or 0) < 0 and row["_metric_present"],
                "problem_role": row.get("sales_role_code") == "eliminate",
            }.get(problem, False)

        pre_problem_rows = [row for row in baseline_rows if row_matches(row, include_problem=False)]
        pre_problem_units = {_business_unit_key(row) for row in pre_problem_rows}
        missing_metric_units = _missing_metric_units(pre_problem_rows)
        preferred_daily_sales = preferred_local_values(pre_problem_rows, "daily_sales_band_code")
        profit_by_unit: dict[tuple[str, str, str], float] = defaultdict(float)
        for row in pre_problem_rows:
            if row["_metric_present"]:
                profit_by_unit[_business_unit_key(row)] += row.get("order_gross_profit") or 0
        issue_units = {
            "conflict": {_business_unit_key(row) for row in pre_problem_rows if row["conflict"]},
            "missing_metrics": missing_metric_units if local_metrics_available else set(),
            "zero_sales": {unit for unit, value in preferred_daily_sales.items() if value == "zero"},
            "negative_profit": {unit for unit, value in profit_by_unit.items() if value < 0},
            "problem_role": {
                _business_unit_key(row)
                for row in pre_problem_rows
                if row.get("_sales_role_label_id") == PROBLEM_PRODUCT_CHILD_ID
            },
        }
        selected_problem_units = issue_units.get(problem, set())
        rows = [
            row for row in pre_problem_rows
            if problem in {"", "all"} or _business_unit_key(row) in selected_problem_units
        ]
        issue_counts = {
            "all": len(pre_problem_units),
            **{key: len(value) for key, value in issue_units.items()},
        }

        breakdowns = []
        for breakdown_key, definition in LOCAL_BREAKDOWN_DEFINITIONS.items():
            candidates = [row for row in baseline_rows if row_matches(row, skip_local=breakdown_key, include_problem=False)]
            if problem not in {"", "all"}:
                candidates = [row for row in candidates if _business_unit_key(row) in selected_problem_units]
            candidate_count = len(candidates)
            preferred_values = preferred_local_values(candidates, definition["field"])
            buckets = []
            for bucket_key, bucket_label in definition["buckets"]:
                bucket_units = {unit for unit, value in preferred_values.items() if value == bucket_key}
                stats = self._bucket_stats(candidates, lambda row, units=bucket_units: _business_unit_key(row) in units, candidate_count)
                buckets.append({"key": bucket_key, "label": bucket_label, **stats})
            missing_units = _missing_metric_units(candidates)
            missing_stats = self._bucket_stats(candidates, lambda row: _business_unit_key(row) in missing_units, candidate_count)
            missing_label = (
                "暂无经营数据"
                if local_metrics_available
                else ("当前日期无本地经营快照" if metric_scope.get("status") == "no_snapshot" else "本地经营指标暂不可用")
            )
            buckets.append({"key": "missing", "label": missing_label, **missing_stats})
            breakdowns.append({
                "key": breakdown_key,
                "label": definition["label"],
                "source": "local",
                "denominator": candidate_count,
                "description": definition.get("description", ""),
                "rules": definition.get("rules", []),
                "buckets": buckets,
            })

        for analysis_slot, remote_parent_id in enumerate(remote_slots):
            if remote_parent_id is None:
                continue
            category = category_by_id[remote_parent_id]
            candidates = [row for row in baseline_rows if row_matches(row, skip_parent=remote_parent_id, include_problem=False)]
            if problem not in {"", "all"}:
                candidates = [row for row in candidates if _business_unit_key(row) in selected_problem_units]
            candidate_count = len(candidates)
            preferred_children = preferred_remote_children(candidates, remote_parent_id)
            buckets = []
            for child in category["children"]:
                bucket_units = {unit for unit, child_id in preferred_children.items() if child_id == child["id"]}
                stats = self._bucket_stats(candidates, lambda row, units=bucket_units: _business_unit_key(row) in units, candidate_count)
                buckets.append({"key": str(child["id"]), "id": child["id"], "label": child["label"], **stats})
            breakdowns.append({
                "key": f"label:{remote_parent_id}",
                "parent_id": remote_parent_id,
                "analysis_slot": analysis_slot,
                "label": category["label"],
                "source": "remote_label",
                "denominator": candidate_count,
                "label_period": analysis_period_by_parent.get(remote_parent_id, "all"),
                "periods": sorted(parent_periods.get(remote_parent_id, set()), key=_period_order),
                "buckets": buckets,
            })

        def current_distribution(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result = []
            source_count = len(source_rows)
            preferred_children = preferred_remote_children(source_rows, parent_label_id)
            active_return_units = {
                _business_unit_key(row)
                for row in source_rows
                if row_parent_children(row, RETURN_STAGE_PARENT_ID).intersection(ACTIVE_RETURN_STAGE_CHILD_IDS)
            }
            for child in category_by_id[parent_label_id]["children"]:
                bucket_units = {unit for unit, child_id in preferred_children.items() if child_id == child["id"]}
                stats = self._bucket_stats(source_rows, lambda row, units=bucket_units: _business_unit_key(row) in units, source_count)
                result.append({
                    "id": child["id"],
                    "label": child["label"],
                    "count": stats["msku_count"],
                    "return_stage_count": len(bucket_units.intersection(active_return_units)),
                    **stats,
                })
            return result

        parent_children = category_by_id[parent_label_id]["children"]
        compare_children = category_by_id.get(compare_parent_id, {}).get("children", [])
        preferred_parent_children = preferred_remote_children(rows, parent_label_id)
        preferred_compare_children = preferred_remote_children(rows, compare_parent_id)
        cells = []
        for row_child in parent_children:
            for col_child in compare_children:
                matched_units = {
                    unit
                    for unit, child_id in preferred_parent_children.items()
                    if child_id == row_child["id"] and preferred_compare_children.get(unit) == col_child["id"]
                }
                stats = self._bucket_stats(rows, lambda row, units=matched_units: _business_unit_key(row) in units, len(rows))
                cells.append({"row_id": row_child["id"], "col_id": col_child["id"], "count": len(matched_units), "sales_amount": stats["sales_amount"], "order_gross_profit": stats["order_gross_profit"]})

        category_date_counts = {
            category["id"]: sum(category["id"] in row["_by_parent"] for row in baseline_rows)
            for category in categories
        }
        sales_amount = sum(row.get("sales_amount") or 0 for row in rows)
        gross_profit = sum(row.get("order_gross_profit") or 0 for row in rows)
        metric_count = self._unique_msku_count(rows, lambda row: row["_metric_present"])

        diagnosis_baseline_rows = [row for row in baseline_rows if in_current_parent_scope(row)]
        diagnosis_current_metric_rows = [row for row in rows if row["_metric_present"]]
        diagnosis_baseline_metric_rows = [row for row in diagnosis_baseline_rows if row["_metric_present"]]

        def diagnosis_item(
            key: str,
            label: str,
            problem_key: str,
            predicate: Callable[[dict[str, Any]], bool],
            *,
            metric_denominator: bool,
            available: bool = True,
        ) -> dict[str, Any]:
            current_source = diagnosis_current_metric_rows if metric_denominator else rows
            baseline_source = diagnosis_baseline_metric_rows if metric_denominator else diagnosis_baseline_rows
            current_denominator = len(current_source)
            baseline_denominator = len(baseline_source)
            current_count = sum(predicate(row) for row in current_source) if available else 0
            baseline_count = sum(predicate(row) for row in baseline_source) if available else 0
            current_rate = current_count / current_denominator if available and current_denominator else 0
            baseline_rate = baseline_count / baseline_denominator if available and baseline_denominator else 0
            return {
                "key": key,
                "label": label,
                "problem": problem_key,
                "current_count": current_count,
                "current_rate": round(current_rate, 4),
                "baseline_count": baseline_count,
                "baseline_rate": round(baseline_rate, 4),
                "delta_pp": round((current_rate - baseline_rate) * 100, 1),
                "available": available,
            }

        diagnosis_items = [
            diagnosis_item("zero_sales", "日销为 0", "zero_sales", lambda row: row.get("daily_sales_band_code") == "zero", metric_denominator=True, available=local_metrics_available),
            diagnosis_item(
                "problem_role",
                "问题产品",
                "problem_role",
                lambda row: row.get("_sales_role_label_id") == PROBLEM_PRODUCT_CHILD_ID,
                metric_denominator=False,
            ),
            diagnosis_item("negative_profit", "订单毛利为负", "negative_profit", lambda row: (row.get("order_gross_profit") or 0) < 0, metric_denominator=True, available=local_metrics_available),
            diagnosis_item("missing_metrics", "暂无经营数据", "missing_metrics", lambda row: not row["_metric_present"], metric_denominator=False, available=local_metrics_available),
            diagnosis_item("conflict", "标签互斥冲突", "conflict", lambda row: row["conflict"], metric_denominator=False),
        ]
        diagnosis = {
            "subject": {
                "parent_label": category_by_id[parent_label_id]["label"],
                "msku_count": len(rows),
                "baseline_msku_count": len(diagnosis_baseline_rows),
                "condition_count": (
                    sum(len(children) for children in conditions.values())
                    + len(sales_roles)
                    + len(sales_trends)
                    + len(daily_sales_bands)
                    + len(margin_bands)
                    + (0 if problem in {"", "all"} else 1)
                ),
            },
            "items": diagnosis_items,
            "business": {
                "sales_amount": round(sales_amount, 2),
                "order_gross_profit": round(gross_profit, 2),
                "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
            },
        }

        allowed_sorts = {"country_category", "store", "msku", "sales_qty", "daily_sales", "sales_amount", "order_gross_profit", "order_gross_margin", "sales_role", "lifecycle_label", "problem_priority"}
        sort_field = sort_field if sort_field in allowed_sorts else "problem_priority"
        reverse = str(sort_dir or "desc").lower() != "asc"
        if sort_field == "problem_priority":
            rows.sort(key=lambda row: (row["conflict"], (row.get("order_gross_profit") or 0) < 0, row.get("sales_role_code") == "eliminate", not row["_metric_present"], row.get("sales_amount") or 0), reverse=True)
        else:
            measured = [row for row in rows if row.get(sort_field) is not None]
            missing = [row for row in rows if row.get(sort_field) is None]
            measured.sort(key=lambda row: (row.get(sort_field), row["msku"]), reverse=reverse)
            missing.sort(key=lambda row: row["msku"])
            rows = measured + missing

        safe_page_size = max(10, min(500, int(page_size or 20)))
        total_pages = max(1, math.ceil(len(rows) / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        start = (safe_page - 1) * safe_page_size
        page_rows = [_public_business_row(row) for row in rows[start : start + safe_page_size]]

        scope = {
            "label_data_date": data_date,
            "local_metrics_status": metric_scope.get("status") or "unavailable",
            "metric_window": metric_scope.get("window") or {},
            "metric_msku_count": metric_count,
            "metric_coverage_rate": round(metric_count / self._unique_msku_count(rows), 4) if rows else 0,
        }
        distribution = current_distribution(rows)
        operating_stockout_rate = None
        if category_by_id[parent_label_id]["label"] == "运营状态":
            distribution_by_label = {item["label"]: item for item in distribution}
            stockout = distribution_by_label.get("断货中", {})
            return_restockout_count = int(stockout.get("return_stage_count") or 0)
            stockout_count = int(stockout.get("count") or 0)
            operating_count = sum(
                int((distribution_by_label.get(label) or {}).get("count") or 0)
                for label in ("正常在售", "测款扶持", "返厂品", "返场品", "断货中")
            )
            effective_stockout_count = max(0, stockout_count - return_restockout_count)
            operating_stockout_rate = {
                "effective_stockout_count": effective_stockout_count,
                "operating_count": operating_count,
                "return_restockout_count": return_restockout_count,
                "rate": round(effective_stockout_count / operating_count, 4) if operating_count else None,
            }
        return_stage_active_count = len({
            _business_unit_key(row)
            for row in rows
            if row_parent_children(row, RETURN_STAGE_PARENT_ID).intersection(ACTIVE_RETURN_STAGE_CHILD_IDS)
        })
        return_stage_reconciled_count = sum(item["return_stage_count"] for item in distribution)
        payload = {
            "data_date": data_date,
            "scope": scope,
            "population_summary": population_summary,
            "overview": overview,
            "parent_label_id": parent_label_id,
            "compare_parent_id": compare_parent_id,
            "analysis_parent_ids": remote_ids,
            "category_date_counts": category_date_counts,
            "kpis": {
                "sku_count": self._unique_msku_count(rows),
                "business_unit_count": len(rows),
                "metric_msku_count": metric_count,
                "metric_coverage_rate": scope["metric_coverage_rate"],
                "sales_qty": round(sum(row.get("sales_qty") or 0 for row in rows), 2),
                "sales_amount": round(sales_amount, 2),
                "order_gross_profit": round(gross_profit, 2),
                "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
            },
            "issue_counts": issue_counts,
            "health": {"mutual_exclusion_conflict_count": issue_counts["conflict"]},
            "diagnosis": diagnosis,
            "breakdowns": breakdowns,
            "distribution": distribution,
            "operating_stockout_rate": operating_stockout_rate,
            "return_stage_attribution": {
                "active_return_count": return_stage_active_count,
                "reconciled_count": return_stage_reconciled_count,
                "unmatched_count": max(0, return_stage_active_count - return_stage_reconciled_count),
            },
            "matrix": {"rows": parent_children, "columns": compare_children, "cells": cells, "total": sum(cell["count"] for cell in cells)},
            "rules": category_by_id.get(parent_label_id, {}),
            "rows": page_rows,
            "total": len(rows),
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
        }
        if include_internal:
            payload["_comparison_rows"] = rows
            payload["_baseline_rows"] = baseline_rows
        return payload

    def get_meta(self) -> dict[str, Any]:
        if self._meta_cache and self._meta_cache_at and (datetime.now() - self._meta_cache_at).total_seconds() < SOURCE_CACHE_SECONDS:
            self._schedule_source_validation()
            return self._meta_cache
        details, stats, dates, source_filters = self._fetch_meta_bundle()
        self._details_cache = (datetime.now(), details)
        default_date = dates[0] if dates else ""
        all_categories = self.build_categories(details, stats)
        categories = [item for item in all_categories if item["id"] not in EXCLUDED_ANALYSIS_PARENT_IDS]
        excluded_categories = [
            {**item, "exclusion_reason": "国家/站点细分口径，不参与 MSKU 驾驶舱聚合"}
            for item in all_categories
            if item["id"] in EXCLUDED_ANALYSIS_PARENT_IDS
        ]
        category_ids = {item["id"] for item in categories}
        defaults = [item for item in (2, 8, 9) if item in category_ids]
        defaults.extend(item["id"] for item in categories if item["id"] not in defaults and len(defaults) < 3)
        payload = {
            "default_data_date": default_date,
            "data_dates": dates,
            "categories": categories,
            "excluded_categories": excluded_categories,
            "metric_periods": [{"key": value, "label": value.replace("d", "天")} for value in ("7d", "14d", "30d", "90d")],
            "default_metric_period": "30d",
            "default_analysis_parent_ids": defaults[:3],
            "comparison": self._comparison_scope(),
            "local_breakdowns": [{
                "key": key,
                "label": item["label"],
                "description": item.get("description", ""),
                "rules": item.get("rules", []),
                "options": [{"key": code, "label": label} for code, label in item["buckets"]],
            } for key, item in LOCAL_BREAKDOWN_DEFINITIONS.items()],
            **source_filters,
            "health": {
                "available_category_count": sum(item["state"] == "available" for item in categories),
                "no_data_category_count": sum(item["state"] != "available" for item in categories),
            },
        }
        self._meta_cache, self._meta_cache_at = payload, datetime.now()
        self._schedule_source_validation()
        return payload

    def _comparison_scope(self) -> dict[str, Any]:
        dates = list(self._comparison_dates[:2])
        current_date = dates[0] if dates else ""
        previous_date = dates[1] if len(dates) > 1 else ""
        gap_days = 0
        if current_date and previous_date:
            try:
                gap_days = (date.fromisoformat(current_date) - date.fromisoformat(previous_date)).days
            except ValueError:
                gap_days = 0
        return {
            "current_date": current_date,
            "previous_date": previous_date,
            "gap_days": max(0, gap_days),
            "available": bool(current_date and previous_date),
        }

    def _cached_facts(self, data_date: str) -> list[dict[str, Any]]:
        cached = self._facts_cache.get(data_date)
        if cached and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS:
            return cached[1]
        with self._facts_load_lock:
            cached = self._facts_cache.get(data_date)
            if cached and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS:
                return cached[1]
            event = self._facts_load_events.get(data_date)
            owns_load = event is None
            if owns_load:
                event = threading.Event()
                self._facts_load_events[data_date] = event
        if not owns_load:
            event.wait()
            cached = self._facts_cache.get(data_date)
            if cached and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS:
                return cached[1]
        try:
            facts = self._fetch_facts(data_date, excluded_parent_ids=FACT_FETCH_EXCLUDED_PARENT_IDS)
            self._facts_cache[data_date] = (datetime.now(), facts)
            return facts
        finally:
            if owns_load:
                event.set()
                with self._facts_load_lock:
                    self._facts_load_events.pop(data_date, None)

    def _fetch_stockout_operating_status_facts(
        self,
        data_date: str,
        scope: str = "business_unit",
    ) -> list[dict[str, Any]]:
        if scope not in {"business_unit", "country"}:
            raise ValueError("断货经营状态维度不存在")
        role_ids = STOCKOUT_BEFORE_ROLE_IDS if scope == "business_unit" else COUNTRY_STOCKOUT_BEFORE_ROLE_IDS
        country_universe_clause = (
            f"or label_id in (select sub_label_id from {LABEL_DETAIL_TABLE} where label_id in (4,7,13,14))"
            if scope == "country"
            else ""
        )
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select data_date, country, country_category, store, msku, label_id, label_period,
                       uncompress(evidence_blob) as evidence_json
                from {LABEL_FACT_TABLE}
                where data_date = %(data_date)s
                  and msku not like %(refund_prefix)s
                  and (
                    (label_id = {CURRENT_STOCKOUT_CHILD_ID} and label_period = 'current')
                    or (label_id in ({','.join(str(item) for item in role_ids)}) and label_period in ({','.join(repr(item) for item in STOCKOUT_BEFORE_ROLE_PERIODS)}))
                    {country_universe_clause}
                  )
                """,
                {"data_date": data_date, "refund_prefix": f"{REFUND_MSKU_PREFIX}%"},
            )
            return list(cursor.fetchall())

    def _cached_diagnostic_facts(self, data_date: str, parent_id: int) -> list[dict[str, Any]]:
        cache_key = (data_date, parent_id)
        cached = self._diagnostic_facts_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS:
            return cached[1]
        facts = self._fetch_diagnostic_facts(data_date, parent_id)
        self._diagnostic_facts_cache[cache_key] = (datetime.now(), facts)
        return facts

    def _cached_details(self) -> list[dict[str, Any]]:
        if self._details_cache and (datetime.now() - self._details_cache[0]).total_seconds() < SOURCE_CACHE_SECONDS:
            return self._details_cache[1]
        details = self._fetch_details()
        self._details_cache = (datetime.now(), details)
        return details

    def _cached_metrics(self, data_date: str, metric_period: str) -> dict[str, Any]:
        cache_key = (data_date, metric_period)
        cached = self._metrics_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS:
            return cached[1]
        payload = self._local_metrics.fetch(data_date, metric_period)
        self._metrics_cache[cache_key] = (datetime.now(), payload)
        return payload

    def _start_comparison_warmup(self, metric_period: str) -> None:
        comparison = self._comparison_scope()
        previous_date = str(comparison.get("previous_date") or "")
        if not previous_date:
            return
        cache_key = (previous_date, metric_period)
        facts_cached = self._facts_cache.get(previous_date)
        metrics_cached = self._metrics_cache.get(cache_key)
        now = datetime.now()
        if (
            facts_cached
            and metrics_cached
            and (now - facts_cached[0]).total_seconds() < SOURCE_CACHE_SECONDS
            and (now - metrics_cached[0]).total_seconds() < SOURCE_CACHE_SECONDS
        ):
            return
        with self._comparison_warm_lock:
            if cache_key in self._comparison_warm_events:
                return
            event = threading.Event()
            self._comparison_warm_events[cache_key] = event

        def warm() -> None:
            try:
                self._cached_facts(previous_date)
                self._cached_metrics(previous_date, metric_period)
            except Exception:
                # 变化接口会按自己的错误语义重试；预热失败不能影响今日看板。
                pass
            finally:
                event.set()
                with self._comparison_warm_lock:
                    self._comparison_warm_events.pop(cache_key, None)

        threading.Thread(target=warm, name="label-hub-comparison-warmup", daemon=True).start()

    def wait_for_comparison_warmup(self, data_date: str, metric_period: str, timeout: float = 5.0) -> None:
        with self._comparison_warm_lock:
            event = self._comparison_warm_events.get((data_date, metric_period))
        if event:
            event.wait(timeout=max(0.0, timeout))

    def get_payload(self, **filters: Any) -> dict[str, Any]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        metric_period = str(filters.get("metric_period") or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 不存在")
        cacheable = not bool(filters.get("_include_internal"))
        cache_key = self._payload_cache_key(data_date, metric_period, filters)
        if cacheable:
            cached_payload = self._get_cached_payload(cache_key)
            if cached_payload is not None:
                self._start_comparison_warmup(metric_period)
                return cached_payload
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "")
        try:
            metric_scope = self._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}
        payload = self.build_payload(
            details=self._cached_details(),
            facts=self._cached_facts(data_date),
            metrics=metric_scope.get("metrics") or {},
            metric_scope=metric_scope,
            data_date=data_date,
            parent_label_id=int(filters.get("parent_label_id") or 0),
            compare_parent_id=int(filters.get("compare_parent_id") or 0),
            analysis_parent_ids=_parse_int_pipe(filters.get("analysis_parent_ids", "")),
            analysis_periods=_parse_period_pipe(filters.get("analysis_periods", "")),
            conditions=self.parse_conditions(filters.get("conditions", "")),
            label_period=str(filters.get("label_period") or "all"),
            sales_roles=_parse_code_pipe(filters.get("sales_roles", ""), {"star", "potential", "incubation", "eliminate", "missing"}, "sales_roles"),
            sales_trends=_parse_code_pipe(filters.get("sales_trends", ""), {"accelerating", "growing", "stable", "slowing", "declining", "stopped", "no_sales", "recent_start", "insufficient", "missing"}, "sales_trends"),
            daily_sales_bands=_parse_code_pipe(filters.get("daily_sales_bands", ""), {"zero", "lt1", "1_5", "gt5", "missing"}, "daily_sales_bands"),
            margin_bands=_parse_code_pipe(filters.get("margin_bands", ""), {"lt5", "5_10", "10_15", "15_25", "gt25", "missing"}, "margin_bands"),
            problem=str(filters.get("problem") or "all"),
            country_category=country_category,
            store=store,
            keyword=keyword,
            page=int(filters.get("page") or 1),
            page_size=int(filters.get("page_size") or 20),
            sort_field=str(filters.get("sort_field") or "problem_priority"),
            sort_dir=str(filters.get("sort_dir") or "desc"),
            include_internal=cacheable or bool(filters.get("_include_internal")),
        )
        if cacheable:
            base_rows = payload.pop("_comparison_rows", [])
            payload.pop("_baseline_rows", None)
            diagnostic_key = self._diagnostic_rows_cache_key(data_date, metric_period, filters)
            with self._payload_cache_lock:
                self._diagnostic_rows_cache[diagnostic_key] = (datetime.now(), base_rows)
            self._cache_payload(cache_key, payload)
        self._start_comparison_warmup(metric_period)
        return payload

    def get_stockout_before_role_summary(self, **filters: Any) -> dict[str, Any]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        role_period = str(filters.get("role_period") or "30d").lower()
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().casefold()
        facts = [
            fact
            for fact in self._cached_facts(data_date)
            if (country_category == "all" or str(fact.get("country_category") or "") == country_category)
            and (store == "all" or str(fact.get("store") or "") == store)
            and (
                not keyword
                or keyword in str(fact.get("msku") or "").casefold()
                or keyword in str(fact.get("store") or "").casefold()
            )
        ]
        payload = self.build_stockout_before_role_summary(
            details=self._cached_details(),
            facts=facts,
            role_period=role_period,
        )
        return {"data_date": data_date, **payload}

    def get_stockout_operating_status_summary(self, **filters: Any) -> dict[str, Any]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().casefold()
        scope = str(filters.get("scope") or "business_unit")
        if scope not in {"business_unit", "country"}:
            raise ValueError("断货经营状态维度不存在")
        rows = self._fetch_stockout_historical_rows(
            data_date=data_date,
            scope=scope,
            country_category=country_category,
            store=store,
            keyword=keyword,
        )
        payload = build_stockout_historical_summary(rows, scope_mode=scope, data_date=data_date)
        return decorate_stockout_snapshot_status(
            payload,
            requested_data_date=data_date,
            latest_result_date=self._fetch_stockout_historical_latest_date(),
            source_data_date=str(meta["default_data_date"]),
        )

    def _fetch_stockout_historical_latest_date(self) -> str:
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select max(data_date) as max_date from {STOCKOUT_HISTORICAL_RESULT_TABLE}")
            value = (cursor.fetchone() or {}).get("max_date")
        return str(value or "")

    def _fetch_stockout_historical_rows(
        self,
        *,
        data_date: str,
        scope: str,
        country_category: str = "all",
        store: str = "all",
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["data_date = %(data_date)s", "scope_mode = %(scope)s"]
        params: dict[str, Any] = {"data_date": data_date, "scope": scope}
        if country_category != "all":
            clauses.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if store != "all":
            clauses.append("store = %(store)s")
            params["store"] = store
        if keyword:
            clauses.append("(lower(msku) like %(keyword)s or lower(store) like %(keyword)s or lower(country) like %(keyword)s)")
            params["keyword"] = f"%{keyword}%"
        selected_columns = """
            data_date, scope_mode, country_category, store, msku, country,
            current_gate_status, current_gate_reason,
            historical_evaluable_status, historical_evaluable_reason,
            role_7d, role_14d, role_30d, role_90d,
            historical_operating_level, historical_stability,
            historical_role_pattern, pre_oos_role_change,
            low_stock_constrained, inventory_sales_conflict_flag,
            missing_date_gap_flag, few_selling_days_flag,
            single_day_concentrated_flag, extreme_single_day_concentrated_flag,
            event_boundary_incomplete_flag, one_day_recovery_then_oos_flag,
            rule_version
        """
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"select {selected_columns} from {STOCKOUT_HISTORICAL_RESULT_TABLE} where {' and '.join(clauses)}",
                params,
            )
            return list(cursor.fetchall())

    def get_stockout_historical_members(self, **filters: Any) -> set[tuple[str, ...]]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        scope = str(filters.get("scope") or "business_unit")
        rows = self._fetch_stockout_historical_rows(
            data_date=data_date,
            scope=scope,
            country_category=str(filters.get("country_category") or "all"),
            store=str(filters.get("store") or "all"),
            keyword=str(filters.get("keyword") or "").strip().casefold(),
        )
        return filter_stockout_historical_members(
            rows,
            str(filters.get("dimension") or ""),
            str(filters.get("code") or ""),
            period=str(filters.get("period") or ""),
        )

    def get_stockout_operating_status_members(self, **filters: Any) -> set[tuple[str, ...]]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        role_period = str(filters.get("role_period") or "30d").lower()
        status_code = str(filters.get("status_code") or "")
        reason_code = str(filters.get("reason_code") or "")
        trend_code = str(filters.get("trend_code") or "")
        scope = str(filters.get("scope") or "business_unit")
        if scope not in {"business_unit", "country"}:
            raise ValueError("断货经营状态维度不存在")
        valid_status_codes = {code for code, _, _ in STOCKOUT_OPERATING_STATUS_DEFINITIONS} | {"problem"}
        if status_code not in valid_status_codes:
            raise ValueError("断货经营状态不存在")
        if reason_code and (
            status_code != "pre_oos_evidence_insufficient"
            or reason_code != "history_data_insufficient"
        ):
            raise ValueError("断货前依据不足细分不存在")
        if trend_code and trend_code not in STOCKOUT_OPERATING_TREND_LABELS:
            raise ValueError("断货前经营趋势不存在")
        if trend_code and status_code in {
            "low_inventory_edge", "pre_oos_evidence_insufficient", "full_period_zero_sales"
        }:
            raise ValueError("当前断货经营状态不支持趋势筛选")

        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().casefold()
        source_facts = (
            self._fetch_stockout_operating_status_facts(data_date)
            if scope == "business_unit"
            else self._fetch_stockout_operating_status_facts(data_date, scope=scope)
        )
        facts = [
            fact for fact in source_facts
            if (country_category == "all" or str(fact.get("country_category") or "") == country_category)
            and (store == "all" or str(fact.get("store") or "") == store)
            and (
                not keyword
                or keyword in str(fact.get("msku") or "").casefold()
                or keyword in str(fact.get("store") or "").casefold()
                or keyword in str(fact.get("country") or "").casefold()
            )
        ]
        payload = self.build_stockout_operating_status_summary(
            facts=facts,
            role_period=role_period,
            scope=scope,
            include_members=True,
        )
        if reason_code == "history_data_insufficient":
            return set(payload["_insufficient_reason_members"]["history_coverage_insufficient"])
        if trend_code:
            return set(payload["_trend_members"][(status_code, trend_code)])
        if status_code == "problem":
            return set(payload["_status_members"]["loss_issue"]) | set(payload["_status_members"]["low_margin_issue"])
        return set(payload["_status_members"][status_code])

    def get_diagnostic_base_rows(self, **filters: Any) -> list[dict[str, Any]]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        metric_period = str(filters.get("metric_period") or "30d").lower()
        cache_key = self._diagnostic_rows_cache_key(data_date, metric_period, filters)
        with self._payload_cache_lock:
            cached = self._diagnostic_rows_cache.get(cache_key)
            if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
                return cached[1]
        payload = self.get_payload(**filters, _include_internal=True)
        rows = payload.pop("_comparison_rows", [])
        with self._payload_cache_lock:
            self._diagnostic_rows_cache[cache_key] = (datetime.now(), rows)
        return rows

    def get_business_detail_base_rows(self, **filters: Any) -> dict[str, Any]:
        """Return globally scoped business rows for the dedicated detail service."""
        payload = self.get_payload(**filters, _include_internal=True)
        metric_status = str(payload.get("scope", {}).get("local_metrics_status") or "unknown")
        rows = payload.pop("_comparison_rows", [])
        operating_status = str(filters.get("stockout_operating_status") or "")
        if operating_status:
            members = self.get_stockout_operating_status_members(
                data_date=filters.get("data_date", ""),
                role_period=filters.get("stockout_operating_status_period", ""),
                status_code=operating_status,
                reason_code=filters.get("stockout_insufficient_reason", ""),
                trend_code=filters.get("stockout_operating_trend", ""),
                scope="business_unit",
                country_category=filters.get("country_category", "all"),
                store=filters.get("store", "all"),
                keyword=filters.get("keyword", ""),
            )
            rows = [row for row in rows if _business_unit_key(row) in members]
            for row in rows:
                row["stockout_operating_baseline_status"] = operating_status
                row["stockout_operating_baseline_period"] = "30d"
                row["stockout_operating_trend"] = str(filters.get("stockout_operating_trend") or "")
        return {
            "rows": [_public_business_row(row) for row in rows],
            "metric_status": metric_status,
            "warnings": [] if metric_status == "available" else ["本地经营指标暂不完整"],
        }

    def get_msku_profile(self, **filters: Any) -> dict[str, Any]:
        data_date = str(self.get_meta()["default_data_date"])
        country = str(filters.get("country_category") or "")
        store = str(filters.get("store") or "")
        msku = str(filters.get("msku") or "")
        metric_period = str(filters.get("metric_period") or "30d")
        details = self._cached_details()
        detail_by_id = {int(item["sub_label_id"]): item for item in details}
        facts = [
            fact
            for fact in self._cached_facts(data_date)
            if str(fact.get("country_category") or "") == country
            and str(fact.get("store") or "") == store
            and str(fact.get("msku") or "") == msku
        ]
        if not facts:
            raise ValueError("未找到该 MSKU 标签画像")
        try:
            metric_scope = self._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}
        key = (country, store, msku)
        metric = (metric_scope.get("metrics") or {}).get(key)
        tags = []
        by_parent_period: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for fact in facts:
            detail = detail_by_id.get(int(fact.get("label_id") or 0))
            if not detail:
                continue
            parent = int(detail["label_id"])
            period = str(fact.get("label_period") or "")
            by_parent_period[parent][period].add(int(fact["label_id"]))
            tags.append(
                {
                    "parent_id": parent,
                    "parent_label": detail.get("label_name") or "",
                    "id": int(fact["label_id"]),
                    "label": detail.get("sub_label_name") or "",
                    "period": period,
                    "rule": detail.get("tag_rule") or "",
                    "definition": detail.get("business_definition") or "",
                    "owner": detail.get("business_owner") or "",
                }
            )
        mutual_parents = {
            int(detail["label_id"])
            for detail in details
            if "互斥" in str(detail.get("mutual_exclusion") or "")
        }
        conflicts = sorted(
            parent
            for parent, periods in by_parent_period.items()
            if parent not in EXCLUDED_ANALYSIS_PARENT_IDS
            and parent in mutual_parents
            and any(len(children) > 1 for children in periods.values())
        )
        sorted_tags = sorted(tags, key=lambda item: (item["parent_id"], item["id"], item["period"]))
        analysis_labels = [item for item in sorted_tags if item["parent_id"] not in EXCLUDED_ANALYSIS_PARENT_IDS]
        site_scope_labels = [item for item in sorted_tags if item["parent_id"] in EXCLUDED_ANALYSIS_PARENT_IDS]
        return {
            "identity": {"data_date": data_date, "country_category": country, "store": store, "msku": msku},
            "tag_profile": {
                "labels": sorted_tags,
                "analysis_labels": analysis_labels,
                "site_scope_labels": site_scope_labels,
                "conflict_parent_ids": conflicts,
            },
            "metric_profile": metric or {},
            "data_status": {"local_metrics_status": metric_scope.get("status") or "unavailable", "metric_window": metric_scope.get("window") or {}, "has_local_metric": metric is not None},
        }

    def _source_connection(self):
        return self._dashboard.connect(autocommit=True)

    def _fetch_quick_source_fingerprint(self) -> tuple[Any, ...]:
        """Read cheap table metadata plus the indexed latest label date.

        ``created_time`` is intentionally excluded: it has no remote index and a
        MAX scan currently costs several seconds. InnoDB UPDATE_TIME/table size
        catches normal reloads immediately; the slower content checksum remains
        a periodic fallback for rare same-size in-place edits.
        """
        fact_name = LABEL_FACT_TABLE.split(".", 1)[1]
        detail_name = LABEL_DETAIL_TABLE.split(".", 1)[1]
        source_schema = LABEL_FACT_TABLE.split(".", 1)[0]
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"select max(data_date) as latest_date from {LABEL_FACT_TABLE}"
            )
            facts = cursor.fetchone() or {}
            cursor.execute(
                """
                select table_name, table_rows, update_time, data_length, index_length
                from information_schema.tables
                where table_schema = %s
                  and table_name in (%s, %s)
                order by table_name
                """,
                (source_schema, fact_name, detail_name),
            )
            tables = cursor.fetchall()
        table_markers = tuple(
            (
                str(row.get("TABLE_NAME") or row.get("table_name") or ""),
                int(row.get("TABLE_ROWS") or row.get("table_rows") or 0),
                str(row.get("UPDATE_TIME") or row.get("update_time") or ""),
                int(row.get("DATA_LENGTH") or row.get("data_length") or 0),
                int(row.get("INDEX_LENGTH") or row.get("index_length") or 0),
            )
            for row in tables
        )
        return (_date_text(facts.get("latest_date")), *table_markers)

    def _fetch_content_source_fingerprint(self) -> tuple[Any, ...]:
        """Hash relevant content server-side so in-place edits are detected."""
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as row_count,
                       coalesce(bit_xor(row_hash), 0) as xor_hash,
                       coalesce(sum(row_hash), 0) as sum_hash
                from (
                    select crc32(concat_ws(
                        '|',
                        data_date,
                        coalesce(country, ''),
                        coalesce(country_category, ''),
                        coalesce(store, ''),
                        coalesce(msku, ''),
                        coalesce(label_id, ''),
                        coalesce(label_period, '')
                    )) as row_hash
                    from {LABEL_FACT_TABLE}
                    where data_date in (
                        select data_date
                        from (
                            select distinct data_date
                            from {LABEL_FACT_TABLE}
                            where msku not like %(refund_prefix)s
                            order by data_date desc
                            limit 2
                        ) recent_dates
                    )
                      and msku not like %(refund_prefix)s
                ) fact_rows
                """,
                {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"},
            )
            facts = cursor.fetchone() or {}
            cursor.execute(
                f"""
                select count(*) as row_count,
                       coalesce(bit_xor(row_hash), 0) as xor_hash,
                       coalesce(sum(row_hash), 0) as sum_hash
                from (
                    select crc32(concat_ws(
                        '|',
                        coalesce(label_id, ''),
                        coalesce(label_name, ''),
                        coalesce(sub_label_id, ''),
                        coalesce(sub_label_name, ''),
                        coalesce(tag_rule, ''),
                        coalesce(business_definition, ''),
                        coalesce(business_owner, ''),
                        coalesce(label_category, ''),
                        coalesce(update_frequency, ''),
                        coalesce(mutual_exclusion, ''),
                        coalesce(status, ''),
                        coalesce(tagging_method, '')
                    )) as row_hash
                    from {LABEL_DETAIL_TABLE}
                    where sub_label_id is not null
                ) detail_rows
                """
            )
            details = cursor.fetchone() or {}
        return (
            int(facts.get("row_count") or 0),
            str(facts.get("xor_hash") or "0"),
            str(facts.get("sum_hash") or "0"),
            int(details.get("row_count") or 0),
            str(details.get("xor_hash") or "0"),
            str(details.get("sum_hash") or "0"),
        )

    def _fetch_meta_bundle(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, label_name, sub_label_id, sub_label_name, tag_rule, business_definition, business_owner, label_category, update_frequency, mutual_exclusion, status, tagging_method from {LABEL_DETAIL_TABLE} where sub_label_id is not null order by label_id, sub_label_id")
            details = cursor.fetchall()
            # data_date has a remote index. Keep this lookup index-only; applying
            # an MSKU predicate here would force a large fact-table scan.
            cursor.execute(f"select distinct data_date from {LABEL_FACT_TABLE} order by data_date desc limit 2")
            comparison_dates = [_date_text(row.get("data_date")) for row in cursor.fetchall()]
            comparison_dates = [item for item in comparison_dates if item]
        self._comparison_dates = comparison_dates
        latest_date = comparison_dates[0] if comparison_dates else ""
        dates = [latest_date] if latest_date else []
        facts = (
            self._fetch_facts(latest_date, excluded_parent_ids=FACT_FETCH_EXCLUDED_PARENT_IDS)
            if latest_date
            else []
        )
        if latest_date:
            # The first dashboard request needs these same rows. Reusing them
            # avoids separate GROUP BY and DISTINCT scans during cold startup.
            self._facts_cache[latest_date] = (datetime.now(), facts)

        stats_by_child: dict[int, dict[str, Any]] = {}
        for row in facts:
            child_id = int(row.get("label_id") or 0)
            item = stats_by_child.setdefault(
                child_id,
                {"fact_count": 0, "latest_date": latest_date, "periods": set()},
            )
            item["fact_count"] += 1
            if row.get("label_period"):
                item["periods"].add(str(row["label_period"]))
        stats = {
            child_id: {**item, "periods": sorted(item["periods"], key=_period_order)}
            for child_id, item in stats_by_child.items()
        }

        pairs = {
            (str(row.get("country_category") or ""), str(row.get("store") or ""))
            for row in facts
            if row.get("country_category") and row.get("store")
        }
        stores_by_country: dict[str, set[str]] = defaultdict(set)
        for country_category, store_name in pairs:
            stores_by_country[country_category].add(store_name)
        source_filters = {
            "country_categories": sorted({item[0] for item in pairs}),
            "stores": sorted({item[1] for item in pairs}),
            "stores_by_country": {
                country_category: sorted(stores)
                for country_category, stores in stores_by_country.items()
            },
        }
        return details, stats, dates, source_filters

    def _fetch_details(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, label_name, sub_label_id, sub_label_name, tag_rule, business_definition, business_owner, label_category, update_frequency, mutual_exclusion, status, tagging_method from {LABEL_DETAIL_TABLE} where sub_label_id is not null order by label_id, sub_label_id")
            return cursor.fetchall()

    def _fetch_fact_stats(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, count(*) as fact_count, max(data_date) as latest_date, group_concat(distinct label_period order by label_period) as label_periods from {LABEL_FACT_TABLE} where data_date = (select max(data_date) from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s) and msku not like %(refund_prefix)s group by label_id", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            return {int(row["label_id"]): {"fact_count": row["fact_count"], "latest_date": _date_text(row["latest_date"]), "periods": [item for item in str(row.get("label_periods") or "").split(",") if item]} for row in cursor.fetchall()}

    def _fetch_dates(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select distinct data_date from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s order by data_date desc limit 2", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            return [item for item in (_date_text(row.get("data_date")) for row in cursor.fetchall()) if item]

    def _fetch_filters(self, data_date):
        with self._source_connection() as conn, conn.cursor() as cursor:
            params = {"data_date": data_date, "refund_prefix": f"{REFUND_MSKU_PREFIX}%"}
            cursor.execute(f"select distinct country_category from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and country_category is not null and country_category != '' order by country_category", params)
            countries = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute(f"select distinct store from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and store is not null and store != '' order by store", params)
            stores = [row["store"] for row in cursor.fetchall()]
        return {"country_categories": countries, "stores": stores}

    def _fetch_facts(self, data_date, country_category="all", store="all", keyword="", parent_ids=None, excluded_parent_ids=None):
        parent_ids = tuple(sorted({int(item) for item in (parent_ids or [])}))
        excluded_parent_ids = tuple(sorted({int(item) for item in (excluded_parent_ids or [])}))
        detail_scope = (
            f" where label_id in ({','.join(str(item) for item in parent_ids)})"
            if parent_ids
            else (
                f" where label_id not in ({','.join(str(item) for item in excluded_parent_ids)})"
                if excluded_parent_ids
                else ""
            )
        )
        clauses = [
            "data_date = %(data_date)s",
            "msku not like %(refund_prefix)s",
            f"label_id in (select sub_label_id from {LABEL_DETAIL_TABLE}{detail_scope})",
        ]
        params = {"data_date": data_date, "refund_prefix": f"{REFUND_MSKU_PREFIX}%"}
        if country_category != "all":
            clauses.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if store != "all":
            clauses.append("store = %(store)s")
            params["store"] = store
        if str(keyword or "").strip():
            params["keyword"] = f"%{str(keyword).strip()}%"
            clauses.append("(msku like %(keyword)s or store like %(keyword)s)")
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select data_date, country, country_category, store, msku,
                       group_concat(distinct concat(label_id, '@', coalesce(label_period, '')) order by label_id separator '|') as fact_tokens
                from {LABEL_FACT_TABLE}
                where {' and '.join(clauses)}
                group by data_date, country, country_category, store, msku
                """,
                params,
            )
            compact_rows = cursor.fetchall()
        facts = []
        for row in compact_rows:
            for token in str(row.get("fact_tokens") or "").split("|"):
                token_parts = token.split("@", 2)
                if len(token_parts) < 2 or not token_parts[0].isdigit():
                    continue
                facts.append({
                    "data_date": row.get("data_date"),
                    "country": row.get("country"),
                    "country_category": row.get("country_category"),
                    "store": row.get("store"),
                    "msku": row.get("msku"),
                    "label_id": int(token_parts[0]),
                    "label_period": token_parts[1],
                })
        return facts

    def _fetch_diagnostic_facts(self, data_date: str, parent_id: int) -> list[dict[str, Any]]:
        child_ids = [
            int(item["sub_label_id"])
            for item in self._cached_details()
            if int(item["label_id"]) == parent_id
        ]
        if not child_ids:
            return []
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select data_date, country, country_category, store, msku,
                       group_concat(
                         distinct concat(
                           label_id, '@', coalesce(label_period, ''), '@',
                           case when evidence_blob is null then '0' else '1' end
                         )
                         order by label_id separator '|'
                       ) as fact_tokens
                from {LABEL_FACT_TABLE}
                where data_date = %(data_date)s
                  and msku not like %(refund_prefix)s
                  and label_id in ({','.join(str(item) for item in sorted(child_ids))})
                group by data_date, country, country_category, store, msku
                """,
                {
                    "data_date": data_date,
                    "refund_prefix": f"{REFUND_MSKU_PREFIX}%",
                },
            )
            compact_rows = cursor.fetchall()
        facts = []
        for row in compact_rows:
            for token in str(row.get("fact_tokens") or "").split("|"):
                token_parts = token.split("@", 2)
                if len(token_parts) < 2 or not token_parts[0].isdigit():
                    continue
                facts.append({
                    "data_date": row.get("data_date"),
                    "country": row.get("country"),
                    "country_category": row.get("country_category"),
                    "store": row.get("store"),
                    "msku": row.get("msku"),
                    "label_id": int(token_parts[0]),
                    "label_period": token_parts[1],
                    "evidence_available": len(token_parts) == 3 and token_parts[2] == "1",
                })
        return facts

    def get_diagnostic_facts(
        self,
        *,
        data_date: str,
        parent_id: int,
        country_category: str = "all",
        store: str = "all",
        keyword: str = "",
        label_period: str = "all",
        cached_only: bool = False,
    ) -> list[dict[str, Any]]:
        child_details = {
            int(item["sub_label_id"]): item
            for item in self._cached_details()
            if int(item["label_id"]) == parent_id
        }
        if not child_details:
            return []
        cached = self._diagnostic_facts_cache.get((data_date, parent_id))
        if cached_only and (
            not cached
            or (datetime.now() - cached[0]).total_seconds() >= SOURCE_CACHE_SECONDS
        ):
            return []
        keyword_text = str(keyword or "").strip().lower()
        return [
            {
                **fact,
                "sub_label_name": child_details[int(fact["label_id"])].get("sub_label_name") or "",
            }
            for fact in self._cached_diagnostic_facts(data_date, parent_id)
            if int(fact.get("label_id") or 0) in child_details
            and (label_period == "all" or str(fact.get("label_period") or "") == label_period)
            and (country_category == "all" or str(fact.get("country_category") or "") == country_category)
            and (store == "all" or str(fact.get("store") or "") == store)
            and (
                not keyword_text
                or keyword_text in f"{fact.get('msku') or ''} {fact.get('store') or ''}".lower()
            )
        ]

    def has_cached_diagnostic_facts(self, data_date: str, parent_id: int) -> bool:
        cached = self._diagnostic_facts_cache.get((data_date, parent_id))
        return bool(
            cached
            and (datetime.now() - cached[0]).total_seconds() < SOURCE_CACHE_SECONDS
        )


label_hub_service = LabelHubDataService()
