from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode

from .dashboard_db import dashboard_service
from .label_hub_local_metrics import METRIC_PERIODS, label_hub_local_metrics_service


LABEL_DETAIL_TABLE = "dws_datasync.dws_标签详情表"
LABEL_FACT_TABLE = "dws_datasync.dws_标签表"
REFUND_MSKU_PREFIX = "Amazon.Found."
CACHE_SECONDS = 300
EXCLUDED_ANALYSIS_PARENT_IDS = {4, 7, 13, 14}

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


def _missing_metric_mskus(rows: list[dict[str, Any]]) -> set[str]:
    all_mskus: set[str] = set()
    matched_mskus: set[str] = set()
    for row in rows:
        msku = str(row["msku"])
        all_mskus.add(msku)
        if row["_metric_present"]:
            matched_mskus.add(msku)
    return all_mskus - matched_mskus


class LabelHubDataService:
    """Read-only aggregation service for the dynamic label dashboard."""

    def __init__(self) -> None:
        self._dashboard = dashboard_service
        self._local_metrics = label_hub_local_metrics_service
        self._meta_cache: dict[str, Any] | None = None
        self._meta_cache_at: datetime | None = None
        self._details_cache: tuple[datetime, list[dict[str, Any]]] | None = None
        self._facts_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._metrics_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}

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
                    "aggregation_rule": "同一 MSKU 跨经营单元命中多个子标签时，按业务优先级只保留一个主标签。",
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

    def _analysis_categories(self, details: list[dict[str, Any]], fact_stats: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            category
            for category in self.build_categories(details, fact_stats)
            if category["id"] not in EXCLUDED_ANALYSIS_PARENT_IDS
        ]

    @staticmethod
    def _unique_msku_count(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool] | None = None) -> int:
        return len({row["msku"] for row in rows if predicate is None or predicate(row)})

    @staticmethod
    def _bucket_stats(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], total_rows: int) -> dict[str, Any]:
        matched = [row for row in rows if predicate(row)]
        matched_count = LabelHubDataService._unique_msku_count(matched)
        sales_amount = sum(row.get("sales_amount") or 0 for row in matched)
        gross_profit = sum(row.get("order_gross_profit") or 0 for row in matched)
        total_sales = sum(row.get("sales_amount") or 0 for row in rows)
        return {
            "msku_count": matched_count,
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
    ) -> dict[str, Any]:
        sales_roles = set(sales_roles or set())
        sales_trends = set(sales_trends or set())
        daily_sales_bands = set(daily_sales_bands or set())
        margin_bands = set(margin_bands or set())
        metric_scope = metric_scope or {"status": "available" if metrics else "no_snapshot", "window": {}}
        local_metrics_available = metric_scope.get("status") == "available"
        detail_by_id = {int(item["sub_label_id"]): item for item in details}
        categories = self._analysis_categories(details, {})
        category_by_id = {item["id"]: item for item in categories}
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

        child_parent = {child["id"]: category["id"] for category in categories for child in category["children"]}
        for parent, children in conditions.items():
            if parent not in category_by_id or any(child_parent.get(child) != parent for child in children):
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
            if int(detail["label_id"]) in EXCLUDED_ANALYSIS_PARENT_IDS:
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
                "ad_spend",
                "acos",
                "tacos",
                "return_count",
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
                if row.get("sales_role_code") == "eliminate":
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

        def preferred_remote_children(source_rows: list[dict[str, Any]], parent: int) -> dict[str, int]:
            children_by_msku: dict[str, set[int]] = defaultdict(set)
            for row in source_rows:
                children_by_msku[row["msku"]].update(row_parent_children(row, parent))
            priority = category_by_id.get(parent, {}).get("aggregation_priority_ids", [])
            rank = {child_id: index for index, child_id in enumerate(priority)}
            return {
                msku: min(children, key=lambda child_id: (rank.get(child_id, len(rank)), child_id))
                for msku, children in children_by_msku.items()
                if children
            }

        def preferred_local_values(source_rows: list[dict[str, Any]], field: str) -> dict[str, str]:
            values_by_msku: dict[str, set[str]] = defaultdict(set)
            for row in source_rows:
                if row["_metric_present"]:
                    values_by_msku[row["msku"]].add(str(row.get(field) or "missing"))
            priority = LOCAL_VALUE_PRIORITY[field]
            rank = {value: index for index, value in enumerate(priority)}
            return {
                msku: min(values, key=lambda value: (rank.get(value, len(rank)), value))
                for msku, values in values_by_msku.items()
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
        pre_problem_mskus = {row["msku"] for row in pre_problem_rows}
        missing_metric_mskus = _missing_metric_mskus(pre_problem_rows)
        preferred_roles = preferred_local_values(pre_problem_rows, "sales_role_code")
        preferred_daily_sales = preferred_local_values(pre_problem_rows, "daily_sales_band_code")
        profit_by_msku: dict[str, float] = defaultdict(float)
        for row in pre_problem_rows:
            if row["_metric_present"]:
                profit_by_msku[row["msku"]] += row.get("order_gross_profit") or 0
        issue_mskus = {
            "conflict": {row["msku"] for row in pre_problem_rows if row["conflict"]},
            "missing_metrics": missing_metric_mskus if local_metrics_available else set(),
            "zero_sales": {msku for msku, value in preferred_daily_sales.items() if value == "zero"},
            "negative_profit": {msku for msku, value in profit_by_msku.items() if value < 0},
            "problem_role": {msku for msku, value in preferred_roles.items() if value == "eliminate"},
        }
        selected_problem_mskus = issue_mskus.get(problem, set())
        rows = [
            row for row in pre_problem_rows
            if problem in {"", "all"} or row["msku"] in selected_problem_mskus
        ]
        issue_counts = {
            "all": len(pre_problem_mskus),
            **{key: len(value) for key, value in issue_mskus.items()},
        }

        breakdowns = []
        for breakdown_key, definition in LOCAL_BREAKDOWN_DEFINITIONS.items():
            candidates = [row for row in baseline_rows if row_matches(row, skip_local=breakdown_key, include_problem=False)]
            if problem not in {"", "all"}:
                candidates = [row for row in candidates if row["msku"] in selected_problem_mskus]
            candidate_count = self._unique_msku_count(candidates)
            preferred_values = preferred_local_values(candidates, definition["field"])
            buckets = []
            for bucket_key, bucket_label in definition["buckets"]:
                bucket_mskus = {msku for msku, value in preferred_values.items() if value == bucket_key}
                stats = self._bucket_stats(candidates, lambda row, mskus=bucket_mskus: row["msku"] in mskus, candidate_count)
                buckets.append({"key": bucket_key, "label": bucket_label, **stats})
            missing_mskus = _missing_metric_mskus(candidates)
            missing_stats = self._bucket_stats(candidates, lambda row: row["msku"] in missing_mskus, candidate_count)
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
                candidates = [row for row in candidates if row["msku"] in selected_problem_mskus]
            candidate_count = self._unique_msku_count(candidates)
            preferred_children = preferred_remote_children(candidates, remote_parent_id)
            buckets = []
            for child in category["children"]:
                bucket_mskus = {msku for msku, child_id in preferred_children.items() if child_id == child["id"]}
                stats = self._bucket_stats(candidates, lambda row, mskus=bucket_mskus: row["msku"] in mskus, candidate_count)
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
            source_count = self._unique_msku_count(source_rows)
            preferred_children = preferred_remote_children(source_rows, parent_label_id)
            for child in category_by_id[parent_label_id]["children"]:
                bucket_mskus = {msku for msku, child_id in preferred_children.items() if child_id == child["id"]}
                stats = self._bucket_stats(source_rows, lambda row, mskus=bucket_mskus: row["msku"] in mskus, source_count)
                result.append({"id": child["id"], "label": child["label"], "count": stats["msku_count"], **stats})
            return result

        parent_children = category_by_id[parent_label_id]["children"]
        compare_children = category_by_id.get(compare_parent_id, {}).get("children", [])
        preferred_parent_children = preferred_remote_children(rows, parent_label_id)
        preferred_compare_children = preferred_remote_children(rows, compare_parent_id)
        cells = []
        for row_child in parent_children:
            for col_child in compare_children:
                matched_mskus = {
                    msku
                    for msku, child_id in preferred_parent_children.items()
                    if child_id == row_child["id"] and preferred_compare_children.get(msku) == col_child["id"]
                }
                stats = self._bucket_stats(rows, lambda row, mskus=matched_mskus: row["msku"] in mskus, self._unique_msku_count(rows))
                cells.append({"row_id": row_child["id"], "col_id": col_child["id"], "count": len(matched_mskus), "sales_amount": stats["sales_amount"], "order_gross_profit": stats["order_gross_profit"]})

        category_date_counts = {
            category["id"]: self._unique_msku_count(baseline_rows, lambda row, category_id=category["id"]: category_id in row["_by_parent"])
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
            current_denominator = self._unique_msku_count(current_source)
            baseline_denominator = self._unique_msku_count(baseline_source)
            current_count = self._unique_msku_count(current_source, predicate) if available else 0
            baseline_count = self._unique_msku_count(baseline_source, predicate) if available else 0
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
            diagnosis_item("problem_role", "问题产品", "problem_role", lambda row: row.get("sales_role_code") == "eliminate", metric_denominator=True, available=local_metrics_available),
            diagnosis_item("negative_profit", "订单毛利为负", "negative_profit", lambda row: (row.get("order_gross_profit") or 0) < 0, metric_denominator=True, available=local_metrics_available),
            diagnosis_item("missing_metrics", "暂无经营数据", "missing_metrics", lambda row: not row["_metric_present"], metric_denominator=False, available=local_metrics_available),
            diagnosis_item("conflict", "标签互斥冲突", "conflict", lambda row: row["conflict"], metric_denominator=False),
        ]
        diagnosis = {
            "subject": {
                "parent_label": category_by_id[parent_label_id]["label"],
                "msku_count": self._unique_msku_count(rows),
                "baseline_msku_count": self._unique_msku_count(diagnosis_baseline_rows),
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
        page_rows = []
        for row in rows[start : start + safe_page_size]:
            labels = [
                {
                    "parent_id": int(item["detail"]["label_id"]),
                    "parent_label": item["detail"].get("label_name") or "",
                    "id": int(item["label_id"]),
                    "label": item["detail"].get("sub_label_name") or "",
                    "period": item.get("label_period") or "",
                }
                for item in sorted(row["_label_facts"], key=lambda item: (int(item["detail"]["label_id"]), int(item["label_id"]), str(item.get("label_period") or "")))
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
            page_rows.append({**public, "labels": labels, "label_summary": label_summary})

        scope = {
            "label_data_date": data_date,
            "local_metrics_status": metric_scope.get("status") or "unavailable",
            "metric_window": metric_scope.get("window") or {},
            "metric_msku_count": metric_count,
            "metric_coverage_rate": round(metric_count / self._unique_msku_count(rows), 4) if rows else 0,
        }
        return {
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
            "distribution": current_distribution(rows),
            "matrix": {"rows": parent_children, "columns": compare_children, "cells": cells, "total": sum(cell["count"] for cell in cells)},
            "rules": category_by_id.get(parent_label_id, {}),
            "rows": page_rows,
            "total": len(rows),
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
        }

    def get_meta(self) -> dict[str, Any]:
        if self._meta_cache and self._meta_cache_at and (datetime.now() - self._meta_cache_at).total_seconds() < 300:
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
        return payload

    def _cached_facts(self, data_date: str) -> list[dict[str, Any]]:
        cached = self._facts_cache.get(data_date)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        facts = self._fetch_facts(data_date)
        self._facts_cache[data_date] = (datetime.now(), facts)
        return facts

    def _cached_details(self) -> list[dict[str, Any]]:
        if self._details_cache and (datetime.now() - self._details_cache[0]).total_seconds() < 300:
            return self._details_cache[1]
        details = self._fetch_details()
        self._details_cache = (datetime.now(), details)
        return details

    def _cached_metrics(self, data_date: str, metric_period: str) -> dict[str, Any]:
        cache_key = (data_date, metric_period)
        cached = self._metrics_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        payload = self._local_metrics.fetch(data_date, metric_period)
        self._metrics_cache[cache_key] = (datetime.now(), payload)
        return payload

    def get_payload(self, **filters: Any) -> dict[str, Any]:
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta["default_data_date"])
        if data_date not in meta["data_dates"]:
            raise ValueError("data_date 不存在")
        metric_period = str(filters.get("metric_period") or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 不存在")
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "")
        try:
            metric_scope = self._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}
        return self.build_payload(
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
        )

    def get_msku_profile(self, **filters: Any) -> dict[str, Any]:
        data_date = str(filters.get("data_date") or self.get_meta()["default_data_date"])
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
        query = {"period": metric_period, "country_category": country, "seller_name_new": store, "keyword": msku}
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
            "navigation_links": {
                "sales_role": f"/sales-role?{urlencode({**query, 'view': 'role'})}",
                "lifecycle": f"/sales-role?{urlencode({**query, 'view': 'lifecycle'})}",
            },
        }

    def _source_connection(self):
        return self._dashboard.source_connect()

    def _fetch_meta_bundle(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, label_name, sub_label_id, sub_label_name, tag_rule, business_definition, business_owner, label_category, update_frequency, mutual_exclusion, status, tagging_method from {LABEL_DETAIL_TABLE} where sub_label_id is not null order by label_id, sub_label_id")
            details = cursor.fetchall()
            cursor.execute(f"select label_id, count(*) as fact_count, max(data_date) as latest_date, group_concat(distinct label_period order by label_period) as label_periods from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s group by label_id", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            stats = {
                int(row["label_id"]): {
                    "fact_count": row["fact_count"],
                    "latest_date": _date_text(row["latest_date"]),
                    "periods": [item for item in str(row.get("label_periods") or "").split(",") if item],
                }
                for row in cursor.fetchall()
            }
            cursor.execute(f"select distinct data_date from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s order by data_date desc", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            dates = [_date_text(row["data_date"]) for row in cursor.fetchall()]
            source_filters = {"country_categories": [], "stores": []}
            if dates:
                params = {"data_date": dates[0], "refund_prefix": f"{REFUND_MSKU_PREFIX}%"}
                cursor.execute(f"select distinct country_category from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and country_category is not null and country_category != '' order by country_category", params)
                source_filters["country_categories"] = [row["country_category"] for row in cursor.fetchall()]
                cursor.execute(f"select distinct store from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and store is not null and store != '' order by store", params)
                source_filters["stores"] = [row["store"] for row in cursor.fetchall()]
        return details, stats, dates, source_filters

    def _fetch_details(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, label_name, sub_label_id, sub_label_name, tag_rule, business_definition, business_owner, label_category, update_frequency, mutual_exclusion, status, tagging_method from {LABEL_DETAIL_TABLE} where sub_label_id is not null order by label_id, sub_label_id")
            return cursor.fetchall()

    def _fetch_fact_stats(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select label_id, count(*) as fact_count, max(data_date) as latest_date, group_concat(distinct label_period order by label_period) as label_periods from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s group by label_id", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            return {int(row["label_id"]): {"fact_count": row["fact_count"], "latest_date": _date_text(row["latest_date"]), "periods": [item for item in str(row.get("label_periods") or "").split(",") if item]} for row in cursor.fetchall()}

    def _fetch_dates(self):
        with self._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(f"select distinct data_date from {LABEL_FACT_TABLE} where msku not like %(refund_prefix)s order by data_date desc", {"refund_prefix": f"{REFUND_MSKU_PREFIX}%"})
            return [_date_text(row["data_date"]) for row in cursor.fetchall()]

    def _fetch_filters(self, data_date):
        with self._source_connection() as conn, conn.cursor() as cursor:
            params = {"data_date": data_date, "refund_prefix": f"{REFUND_MSKU_PREFIX}%"}
            cursor.execute(f"select distinct country_category from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and country_category is not null and country_category != '' order by country_category", params)
            countries = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute(f"select distinct store from {LABEL_FACT_TABLE} where data_date = %(data_date)s and msku not like %(refund_prefix)s and store is not null and store != '' order by store", params)
            stores = [row["store"] for row in cursor.fetchall()]
        return {"country_categories": countries, "stores": stores}

    def _fetch_facts(self, data_date, country_category="all", store="all", keyword=""):
        clauses = [
            "data_date = %(data_date)s",
            "msku not like %(refund_prefix)s",
            f"label_id in (select sub_label_id from {LABEL_DETAIL_TABLE})",
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
                label_text, separator, period = token.partition("@")
                if not separator or not label_text.isdigit():
                    continue
                facts.append({"data_date": row.get("data_date"), "country": row.get("country"), "country_category": row.get("country_category"), "store": row.get("store"), "msku": row.get("msku"), "label_id": int(label_text), "label_period": period})
        return facts


label_hub_service = LabelHubDataService()
