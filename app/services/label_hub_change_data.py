from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from etl.dashboard_daily_update import render_sql

from .label_hub_data import (
    CACHE_SECONDS,
    LOCAL_BREAKDOWN_DEFINITIONS,
    LOCAL_VALUE_PRIORITY,
    METRIC_PERIODS,
    REMOTE_PARENT_CHILD_PRIORITY,
    _business_unit_key,
    _parse_code_pipe,
    _parse_int_pipe,
    _parse_period_pipe,
    label_hub_service,
)


EVIDENCE_TABLE = "etl_datasync.dashboard_label_rule_evidence_snapshot"
CHANGE_TYPES = {"all", "added", "removed", "changed", "unchanged"}
CHANGE_SORT_FIELDS = {"change_type", "msku", "previous_label", "current_label", "business_unit_count"}
ROLE_LABELS = {101: "明星产品", 102: "潜力产品", 103: "瘦狗产品", 104: "问题产品"}
REASON_LABELS = {
    "daily_cross": "日销跨线",
    "margin_cross": "毛利率跨线",
    "both_cross": "日销与毛利率同时跨线",
    "business_unit_added": "新增记录",
    "business_unit_removed": "记录消失",
    "evidence_missing": "规则证据缺失",
    "evidence_mismatch": "本地重算与远端标签不一致",
}
RULE_METRIC_DEFINITIONS = {
    "daily_sales": ("日销", "number"),
    "tag_margin_rate": ("打标毛利率", "percent_value"),
    "margin_rate": ("毛利率", "percent_value"),
    "inventory_support_days": ("库存可支撑天数", "days"),
    "period_sales_qty": ("周期销量", "number"),
    "sales_qty": ("销量", "number"),
    "sales_amount": ("打标销售额", "money"),
    "tag_gross_profit": ("打标毛利润", "money"),
    "return_rate": ("退货率", "percent_value"),
    "natural_traffic_ratio": ("自然流量占比", "percent_value"),
    "ad_traffic_ratio": ("广告流量占比", "percent_value"),
    "tacos": ("TACOS", "percent_value"),
    "days_since_launch": ("上架天数", "days"),
}
BusinessUnitKey = tuple[str, str, str]


def classify_sales_role(daily_sales: float, gross_margin: float) -> int:
    if daily_sales > 5 and gross_margin > 0.15:
        return 101
    if 1 <= daily_sales <= 5 and gross_margin > 0.25:
        return 101
    if daily_sales > 5 and 0.05 <= gross_margin <= 0.15:
        return 102
    if 1 <= daily_sales <= 5 and 0.10 <= gross_margin <= 0.25:
        return 102
    if 1 <= daily_sales <= 5 and 0.05 <= gross_margin <= 0.10:
        return 103
    if 0 < daily_sales < 1 and gross_margin > 0.05:
        return 103
    return 104


class LabelHubChangeDataService:
    """Compare the latest two label snapshots without changing the current dashboard path."""

    def __init__(self) -> None:
        self._hub = label_hub_service
        self._result_cache: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = {}
        self._evidence_cache: dict[tuple[str, str, str], tuple[datetime, dict[tuple[str, str, str, str], dict[str, Any]]]] = {}
        self._remote_evidence_cache: dict[tuple[str, str, int, str], tuple[datetime, dict[tuple[str, str, str, str], list[dict[str, Any]]]]] = {}
        self._base_day_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
        self._hub.register_source_invalidation_callback(self._clear_remote_label_caches)

    def _clear_remote_label_caches(self) -> None:
        self._result_cache.clear()
        self._base_day_cache.clear()
        self._remote_evidence_cache.clear()

    @staticmethod
    def _decode_remote_evidence(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="replace")
        if not value:
            return {}
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def _fetch_remote_evidence(
        self,
        current_date: str,
        previous_date: str,
        parent_id: int,
        period: str,
        units: set[BusinessUnitKey] | None = None,
    ) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
        if not parent_id or units == set():
            return {}
        cache_key = (current_date, previous_date, parent_id, period)
        if units is None:
            cached = self._remote_evidence_cache.get(cache_key)
            if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
                return cached[1]

        child_ids = sorted({
            int(row.get("sub_label_id") or 0)
            for row in self._hub._cached_details()
            if int(row.get("label_id") or 0) == parent_id
            and int(row.get("sub_label_id") or 0)
        })
        if not child_ids:
            return {}

        period_sql = ""
        params: dict[str, Any] = {
            "current_date": current_date,
            "previous_date": previous_date,
        }
        child_placeholders = []
        for index, child_id in enumerate(child_ids):
            name = f"child_id_{index}"
            child_placeholders.append(f"%({name})s")
            params[name] = child_id
        if period and period != "all":
            period_sql = " and f.label_period = %(period)s"
            params["period"] = period

        unit_sql = ""
        if units is not None:
            unit_clauses = []
            for index, (country_category, store, msku) in enumerate(sorted(units)):
                unit_clauses.append(
                    "("
                    f"f.country_category = %(unit_cc_{index})s and "
                    f"f.store = %(unit_store_{index})s and "
                    f"f.msku = %(unit_msku_{index})s"
                    ")"
                )
                params[f"unit_cc_{index}"] = country_category
                params[f"unit_store_{index}"] = store
                params[f"unit_msku_{index}"] = msku
            unit_sql = " and (" + " or ".join(unit_clauses) + ")"

        try:
            with self._hub._source_connection() as conn, conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select f.data_date, f.country_category, f.store, f.msku,
                           f.label_id as sub_label_id, f.label_period, f.evidence_json
                    from dws_datasync.dws_标签表 f
                    where f.data_date in (%(current_date)s, %(previous_date)s)
                      and f.label_id in ({", ".join(child_placeholders)})
                      and f.msku not like 'Amazon.Found.%%'
                      and f.evidence_json is not null
                      {period_sql}
                      {unit_sql}
                    """,
                    params,
                )
                rows = cursor.fetchall()
        except Exception:
            rows = []
        result: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for source in rows:
            row = dict(source)
            row["evidence"] = self._decode_remote_evidence(row.get("evidence_json"))
            result[
                (
                    str(row.get("data_date") or ""),
                    str(row.get("country_category") or ""),
                    str(row.get("store") or ""),
                    str(row.get("msku") or ""),
                )
            ].append(row)
        resolved = dict(result)
        if units is None:
            self._remote_evidence_cache[cache_key] = (datetime.now(), resolved)
        return resolved

    @staticmethod
    def _select_remote_evidence(
        evidence: dict[tuple[str, str, str, str], list[dict[str, Any]]],
        data_date: str,
        unit: BusinessUnitKey,
        expected_sub_label_id: int | None,
        period: str,
    ) -> dict[str, Any]:
        candidates = evidence.get((data_date, unit[0], unit[1], unit[2]), [])
        if expected_sub_label_id:
            exact = [row for row in candidates if int(row.get("sub_label_id") or 0) == expected_sub_label_id]
            if exact:
                candidates = exact
        if period and period != "all":
            exact_period = [row for row in candidates if str(row.get("label_period") or "") == period]
            if exact_period:
                candidates = exact_period
        if not candidates:
            return {}
        return max(candidates, key=lambda row: (str(row.get("label_period") or ""), int(row.get("sub_label_id") or 0)))

    def _comparison(self) -> dict[str, Any]:
        return dict((self._hub.get_meta().get("comparison") or {}))

    def _common_kwargs(self, filters: dict[str, Any]) -> dict[str, Any]:
        metric_period = str(filters.get("metric_period") or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 不存在")
        return {
            "parent_label_id": int(filters.get("parent_label_id") or 0),
            "compare_parent_id": int(filters.get("compare_parent_id") or 0),
            "analysis_parent_ids": _parse_int_pipe(filters.get("analysis_parent_ids", "")),
            "analysis_periods": _parse_period_pipe(filters.get("analysis_periods", "")),
            "conditions": self._hub.parse_conditions(filters.get("conditions", "")),
            "label_period": str(filters.get("label_period") or "all"),
            "sales_roles": set(),
            "sales_trends": _parse_code_pipe(filters.get("sales_trends", ""), {"accelerating", "growing", "stable", "slowing", "declining", "stopped", "no_sales", "recent_start", "insufficient", "missing"}, "sales_trends"),
            "daily_sales_bands": _parse_code_pipe(filters.get("daily_sales_bands", ""), {"zero", "lt1", "1_5", "gt5", "missing"}, "daily_sales_bands"),
            "margin_bands": _parse_code_pipe(filters.get("margin_bands", ""), {"lt5", "5_10", "10_15", "15_25", "gt25", "missing"}, "margin_bands"),
            "problem": str(filters.get("problem") or "all"),
            "country_category": str(filters.get("country_category") or "all"),
            "store": str(filters.get("store") or "all"),
            "keyword": str(filters.get("keyword") or ""),
            "page": 1,
            "page_size": 20,
            "sort_field": "problem_priority",
            "sort_dir": "desc",
            "include_internal": True,
        }

    def _base_day_payload(self, data_date: str, metric_period: str) -> dict[str, Any]:
        cache_key = (data_date, metric_period)
        cached = self._base_day_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        try:
            metric_scope = self._hub._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}
        payload = self._hub.build_payload(
            details=self._hub._cached_details(),
            facts=self._hub._cached_facts(data_date),
            metrics=metric_scope.get("metrics") or {},
            metric_scope=metric_scope,
            data_date=data_date,
            parent_label_id=1,
            compare_parent_id=2,
            analysis_parent_ids=[2, 8, 9],
            analysis_periods=["all", "all", "all"],
            conditions={},
            label_period="all",
            sales_roles=set(),
            sales_trends=set(),
            daily_sales_bands=set(),
            margin_bands=set(),
            problem="all",
            country_category="all",
            store="all",
            keyword="",
            page=1,
            page_size=20,
            sort_field="problem_priority",
            sort_dir="desc",
            include_internal=True,
        )
        base = {"rows": payload.pop("_baseline_rows", []), "metric_scope": metric_scope}
        self._base_day_cache[cache_key] = (datetime.now(), base)
        return base

    def _day_payload(self, data_date: str, filters: dict[str, Any]) -> dict[str, Any]:
        metric_period = str(filters.get("metric_period") or "30d").lower()
        common = self._common_kwargs(filters)
        base = self._base_day_payload(data_date, metric_period)
        baseline_rows = list(base["rows"])
        metric_scope = base["metric_scope"]
        details = self._hub._cached_details()
        categories_list = self._hub._analysis_categories(details, {})
        categories = {int(item["id"]): item for item in categories_list}
        parent_id = int(common["parent_label_id"] or (categories_list[0]["id"] if categories_list else 0))
        if parent_id not in categories and categories_list:
            parent_id = int(categories_list[0]["id"])
        conditions = common["conditions"]
        child_parent = {
            int(child["id"]): int(category["id"])
            for category in categories_list
            for child in category.get("children", [])
        }
        for condition_parent, children in conditions.items():
            if condition_parent not in categories or any(child_parent.get(child) != condition_parent for child in children):
                raise ValueError("conditions 包含不存在或归属错误的标签")
        period_by_parent = {
            int(parent): str(common["analysis_periods"][index] or "all")
            for index, parent in enumerate(common["analysis_parent_ids"])
            if index < len(common["analysis_periods"])
        }

        country = common["country_category"]
        store = common["store"]
        keyword = str(common["keyword"] or "").strip().lower()
        public_rows = [
            row for row in baseline_rows
            if (country == "all" or row["country_category"] == country)
            and (store == "all" or row["store"] == store)
            and (not keyword or keyword in " ".join((row["country_category"], row["store"], row["msku"])).lower())
        ]

        def children_for(row: dict[str, Any], target_parent: int) -> set[int]:
            period = common["label_period"] if target_parent == parent_id else period_by_parent.get(target_parent, "all")
            if period != "all":
                return set(row.get("_by_parent_period", {}).get(target_parent, {}).get(period, set()))
            return set(row.get("_by_parent", {}).get(target_parent, set()))

        local_filters = (
            (common["sales_trends"], "sales_trend_code"),
            (common["daily_sales_bands"], "daily_sales_band_code"),
            (common["margin_bands"], "margin_band_code"),
        )

        def matches(row: dict[str, Any]) -> bool:
            if not children_for(row, parent_id):
                return False
            if any(not children_for(row, parent).intersection(children) for parent, children in conditions.items()):
                return False
            return all(not selected or row.get(field) in selected for selected, field in local_filters)

        pre_problem_rows = [row for row in public_rows if matches(row)]
        grouped = self._rows_by_business_unit(pre_problem_rows)

        def preferred_value(rows: list[dict[str, Any]], field: str) -> dict[BusinessUnitKey, str]:
            priority = LOCAL_VALUE_PRIORITY[field]
            rank = {value: index for index, value in enumerate(priority)}
            result = {}
            for unit, unit_rows in self._rows_by_business_unit(rows).items():
                values = {str(row.get(field) or "missing") for row in unit_rows if row.get("_metric_present")}
                if values:
                    result[unit] = min(values, key=lambda value: (rank.get(value, len(rank)), value))
            return result

        preferred_roles = preferred_value(pre_problem_rows, "sales_role_code")
        preferred_daily = preferred_value(pre_problem_rows, "daily_sales_band_code")
        profit_by_unit = {
            unit: sum(float(row.get("order_gross_profit") or 0) for row in rows if row.get("_metric_present"))
            for unit, rows in grouped.items()
        }
        local_available = metric_scope.get("status") == "available"
        issue_units = {
            "conflict": {unit for unit, rows in grouped.items() if any(row.get("conflict") for row in rows)},
            "missing_metrics": {unit for unit, rows in grouped.items() if local_available and not any(row.get("_metric_present") for row in rows)},
            "zero_sales": {unit for unit, value in preferred_daily.items() if value == "zero"},
            "negative_profit": {unit for unit, value in profit_by_unit.items() if value < 0},
            "problem_role": {unit for unit, value in preferred_roles.items() if value == "eliminate"},
        }
        problem = common["problem"]
        selected_rows = pre_problem_rows if problem in {"", "all"} else [row for row in pre_problem_rows if _business_unit_key(row) in issue_units.get(problem, set())]

        def breakdown_matches(row: dict[str, Any], *, skip_local: str = "", skip_parent: int = 0) -> bool:
            if not children_for(row, parent_id):
                return False
            for condition_parent, children in conditions.items():
                if condition_parent != skip_parent and not children_for(row, condition_parent).intersection(children):
                    return False
            for selected, field in local_filters:
                local_key = {
                    "sales_trend_code": "sales_trend",
                    "daily_sales_band_code": "daily_sales_band",
                    "margin_band_code": "margin_band",
                }[field]
                if local_key != skip_local and selected and row.get(field) not in selected:
                    return False
            return problem in {"", "all"} or _business_unit_key(row) in issue_units.get(problem, set())

        breakdowns = []
        # 分层变化抽屉要与看板卡片保持同一“主标签”口径：
        # 先在当前群体内按优先级归一，再把该层的 MSKU 集合交给两日比较使用。
        canonical_breakdown_units: dict[int, dict[str, set[BusinessUnitKey]]] = {}
        for breakdown_key, definition in LOCAL_BREAKDOWN_DEFINITIONS.items():
            candidates = [row for row in public_rows if breakdown_matches(row, skip_local=breakdown_key)]
            preferred = preferred_value(candidates, definition["field"])
            buckets = []
            for bucket_key, bucket_label in definition["buckets"]:
                buckets.append({"key": bucket_key, "label": bucket_label, "msku_count": sum(value == bucket_key for value in preferred.values())})
            missing = {
                _business_unit_key(row) for row in candidates if not row.get("_metric_present")
            } - {
                _business_unit_key(row) for row in candidates if row.get("_metric_present")
            }
            buckets.append({"key": "missing", "label": "暂无经营数据", "msku_count": len(missing)})
            breakdowns.append({"source": "local", "key": breakdown_key, "label": definition["label"], "parent_id": 0, "buckets": buckets})

        remote_ids = []
        for candidate in list(common["analysis_parent_ids"]) + [2, 8, 9, 11, 3] + list(categories):
            candidate = int(candidate)
            if candidate != parent_id and candidate in categories and candidate not in remote_ids:
                remote_ids.append(candidate)
            if len(remote_ids) == 3:
                break
        for remote_parent_id in remote_ids:
            candidates = [row for row in public_rows if breakdown_matches(row, skip_parent=remote_parent_id)]
            selected_period = period_by_parent.get(remote_parent_id, "all")
            preferred = self._primary_map(self._rows_by_business_unit(candidates), remote_parent_id, selected_period, categories)
            canonical_breakdown_units[remote_parent_id] = {
                str(child["id"]): {unit for unit, child_id in preferred.items() if child_id == child["id"]}
                for child in categories[remote_parent_id].get("children", [])
            }
            buckets = [
                {"key": str(child["id"]), "id": child["id"], "label": child["label"], "msku_count": sum(child_id == child["id"] for child_id in preferred.values())}
                for child in categories[remote_parent_id].get("children", [])
            ]
            breakdowns.append({"source": "remote_label", "key": f"label:{remote_parent_id}", "label": categories[remote_parent_id]["label"], "parent_id": remote_parent_id, "label_period": selected_period, "buckets": buckets})

        parent_units: dict[int, set[BusinessUnitKey]] = defaultdict(set)
        child_units: dict[tuple[int, int], set[BusinessUnitKey]] = defaultdict(set)
        for row in public_rows:
            unit = _business_unit_key(row)
            for overview_parent, child_ids in row.get("_by_parent", {}).items():
                parent_units[int(overview_parent)].add(unit)
                for child_id in child_ids:
                    child_units[(int(overview_parent), int(child_id))].add(unit)
        overview = [
            {
                "id": category["id"],
                "unique_msku_count": len(parent_units[category["id"]]),
                "children": [
                    {"id": child["id"], "unique_msku_count": len(child_units[(category["id"], child["id"])])}
                    for child in category.get("children", [])
                ],
            }
            for category in categories_list
        ]
        return {
            "parent_label_id": parent_id,
            "overview": overview,
            "issue_counts": {"all": len(grouped), **{key: len(values) for key, values in issue_units.items()}},
            "breakdowns": breakdowns,
            "_comparison_rows": selected_rows,
            "_baseline_rows": public_rows,
            "_canonical_breakdown_units": canonical_breakdown_units,
        }

    @staticmethod
    def _rows_by_business_unit(rows: list[dict[str, Any]]) -> dict[BusinessUnitKey, list[dict[str, Any]]]:
        result: dict[BusinessUnitKey, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            result[_business_unit_key(row)].append(row)
        return result

    @staticmethod
    def _primary_child(
        rows: list[dict[str, Any]], parent_id: int, period: str, priority: list[int]
    ) -> int | None:
        children: set[int] = set()
        for row in rows:
            if period == "all":
                children.update(row.get("_by_parent", {}).get(parent_id, set()))
            else:
                children.update(row.get("_by_parent_period", {}).get(parent_id, {}).get(period, set()))
        if not children:
            return None
        rank = {child_id: index for index, child_id in enumerate(priority)}
        return min(children, key=lambda child_id: (rank.get(child_id, len(rank)), child_id))

    def _primary_map(
        self,
        grouped: dict[BusinessUnitKey, list[dict[str, Any]]],
        parent_id: int,
        period: str,
        categories: dict[int, dict[str, Any]],
    ) -> dict[BusinessUnitKey, int]:
        priority = list(categories.get(parent_id, {}).get("aggregation_priority_ids") or REMOTE_PARENT_CHILD_PRIORITY.get(parent_id, []))
        result = {}
        for unit, rows in grouped.items():
            child = self._primary_child(rows, parent_id, period, priority)
            if child is not None:
                result[unit] = child
        return result

    def _signature_map(
        self,
        grouped: dict[BusinessUnitKey, list[dict[str, Any]]],
        categories: dict[int, dict[str, Any]],
        transition_period: str,
    ) -> dict[BusinessUnitKey, dict[int, int]]:
        result: dict[BusinessUnitKey, dict[int, int]] = defaultdict(dict)
        for parent_id in categories:
            period = transition_period if parent_id == 1 else "all"
            for unit, child_id in self._primary_map(grouped, parent_id, period, categories).items():
                result[unit][parent_id] = child_id
        return result

    @staticmethod
    def _delta_overview(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
        previous_by_parent = {int(item["id"]): item for item in previous}
        result = []
        for item in current:
            old = previous_by_parent.get(int(item["id"]), {})
            old_children = {int(child["id"]): child for child in old.get("children", [])}
            children = [
                {
                    "id": int(child["id"]),
                    "current_count": int(child.get("unique_msku_count") or 0),
                    "previous_count": int(old_children.get(int(child["id"]), {}).get("unique_msku_count") or 0),
                    "delta": int(child.get("unique_msku_count") or 0) - int(old_children.get(int(child["id"]), {}).get("unique_msku_count") or 0),
                }
                for child in item.get("children", [])
            ]
            current_count = int(item.get("unique_msku_count") or 0)
            previous_count = int(old.get("unique_msku_count") or 0)
            result.append({"id": int(item["id"]), "current_count": current_count, "previous_count": previous_count, "delta": current_count - previous_count, "children": children})
        return result

    @staticmethod
    def _delta_breakdowns(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compare the visible linked panels bucket-by-bucket using their stable keys."""
        previous_panels = {
            (str(panel.get("source") or ""), str(panel.get("key") or ""), int(panel.get("parent_id") or 0)): panel
            for panel in previous
        }
        result = []
        for panel in current:
            panel_key = (str(panel.get("source") or ""), str(panel.get("key") or ""), int(panel.get("parent_id") or 0))
            old_panel = previous_panels.get(panel_key, {})
            old_buckets = {
                str(bucket.get("id") or bucket.get("key") or ""): bucket
                for bucket in old_panel.get("buckets", [])
            }
            buckets = []
            for bucket in panel.get("buckets", []):
                bucket_key = str(bucket.get("id") or bucket.get("key") or "")
                current_count = int(bucket.get("msku_count") or 0)
                previous_count = int(old_buckets.get(bucket_key, {}).get("msku_count") or 0)
                buckets.append({
                    "key": bucket_key,
                    "label": bucket.get("label") or bucket_key,
                    "current_count": current_count,
                    "previous_count": previous_count,
                    "delta": current_count - previous_count,
                })
            result.append({
                "source": panel_key[0],
                "key": panel_key[1],
                "parent_id": panel_key[2],
                "label": panel.get("label") or panel_key[1],
                "label_period": panel.get("label_period") or "",
                "buckets": buckets,
            })
        return result

    def _evidence_table(self) -> str:
        schemas = getattr(self._hub._dashboard, "schemas", None)
        return render_sql(EVIDENCE_TABLE, schemas) if schemas is not None else EVIDENCE_TABLE

    def _fetch_evidence(self, current_date: str, previous_date: str, period: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        key = (current_date, previous_date, period)
        cached = self._evidence_cache.get(key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        try:
            with self._hub._dashboard.connect() as conn, conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select label_date, country_category, store, msku, label_period,
                           period_start, period_end, sales_qty, daily_sales, tag_sales_amount,
                           tag_gross_profit, tag_gross_margin, computed_sub_label_id,
                           remote_sub_label_id, rule_version, evidence_status
                    from {self._evidence_table()}
                    where label_date in (%(current_date)s, %(previous_date)s)
                      and parent_label_id = 1 and label_period = %(period)s
                    """,
                    {"current_date": current_date, "previous_date": previous_date, "period": period},
                )
                rows = cursor.fetchall()
        except Exception:
            rows = []
        evidence = {
            (str(row.get("label_date") or ""), str(row.get("country_category") or ""), str(row.get("store") or ""), str(row.get("msku") or "")): dict(row)
            for row in rows
        }
        self._evidence_cache[key] = (datetime.now(), evidence)
        return evidence

    @staticmethod
    def _reason_for_pair(previous: dict[str, Any], current: dict[str, Any]) -> tuple[str, str]:
        if not previous or not current:
            code = "business_unit_added" if current else "business_unit_removed"
            return code, REASON_LABELS[code]
        if previous.get("evidence_status") == "missing" or current.get("evidence_status") == "missing":
            return "evidence_missing", REASON_LABELS["evidence_missing"]
        if previous.get("evidence_status") != "matched" or current.get("evidence_status") != "matched":
            return "evidence_mismatch", REASON_LABELS["evidence_mismatch"]
        old_daily = float(previous.get("daily_sales") or 0)
        new_daily = float(current.get("daily_sales") or 0)
        old_margin = float(previous.get("tag_gross_margin") or 0)
        new_margin = float(current.get("tag_gross_margin") or 0)
        old_role = int(previous.get("remote_sub_label_id") or classify_sales_role(old_daily, old_margin))
        new_role = int(current.get("remote_sub_label_id") or classify_sales_role(new_daily, new_margin))
        def daily_zone(value: float) -> str:
            if value <= 0:
                return "zero"
            if value < 1:
                return "lt1"
            if value <= 5:
                return "1_5"
            return "gt5"

        def margin_zone(value: float) -> str:
            if value < 0.05:
                return "lt5"
            if value < 0.10:
                return "5_10"
            if value < 0.15:
                return "10_15"
            if value <= 0.25:
                return "15_25"
            return "gt25"

        daily_changed = daily_zone(old_daily) != daily_zone(new_daily)
        margin_changed = margin_zone(old_margin) != margin_zone(new_margin)
        if daily_changed and margin_changed:
            code = "both_cross"
        elif daily_changed:
            code = "daily_cross"
        elif margin_changed:
            code = "margin_cross"
        else:
            code = "both_cross" if old_role != new_role else "evidence_missing"
        summary = (
            f"{ROLE_LABELS.get(old_role, old_role)} → {ROLE_LABELS.get(new_role, new_role)}；"
            f"日销 {old_daily:.2f} → {new_daily:.2f}，打标毛利率 {old_margin:.1%} → {new_margin:.1%}；{REASON_LABELS[code]}"
        )
        return code, summary

    @staticmethod
    def _remote_reason_evidence(value: dict[str, Any]) -> dict[str, Any]:
        """Adapt remote evidence_json to the local sales-role reason schema."""
        if not value:
            return {}
        payload = value.get("evidence")
        if not isinstance(payload, dict):
            return {}
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            return {}

        daily_sales = metrics.get("daily_sales")
        margin_rate = metrics.get("tag_margin_rate")
        if margin_rate is None:
            margin_rate = metrics.get("margin_rate")
        if daily_sales is None or margin_rate is None:
            return {"evidence_status": "missing"}

        margin_value = float(margin_rate)
        if abs(margin_value) > 1:
            margin_value /= 100
        return {
            "daily_sales": float(daily_sales),
            "tag_gross_margin": margin_value,
            "remote_sub_label_id": int(value.get("sub_label_id") or 0),
            "evidence_status": "matched",
        }

    def _sales_role_reasons(
        self,
        units: set[BusinessUnitKey],
        previous_grouped: dict[BusinessUnitKey, list[dict[str, Any]]],
        current_grouped: dict[BusinessUnitKey, list[dict[str, Any]]],
        evidence: dict[tuple[str, str, str, str], dict[str, Any]],
        previous_date: str,
        current_date: str,
    ) -> tuple[dict[BusinessUnitKey, dict[str, str]], list[dict[str, Any]]]:
        by_unit: dict[BusinessUnitKey, dict[str, str]] = {}
        counts: Counter[str] = Counter()
        for unit in units:
            country, store, msku = unit
            had_previous_unit = unit in previous_grouped
            has_current_unit = unit in current_grouped
            old = evidence.get((previous_date, country, store, msku), {}) if had_previous_unit else {}
            new = evidence.get((current_date, country, store, msku), {}) if has_current_unit else {}
            if not had_previous_unit:
                chosen = ("business_unit_added", REASON_LABELS["business_unit_added"])
            elif not has_current_unit:
                chosen = ("business_unit_removed", REASON_LABELS["business_unit_removed"])
            elif not old or not new:
                chosen = ("evidence_missing", REASON_LABELS["evidence_missing"])
            else:
                chosen = self._reason_for_pair(old, new)
            by_unit[unit] = {"code": chosen[0], "summary": chosen[1]}
            counts[chosen[0]] += 1
        distribution = [{"key": code, "label": label, "count": counts.get(code, 0)} for code, label in REASON_LABELS.items()]
        return by_unit, distribution

    def get_changes(self, **filters: Any) -> dict[str, Any]:
        comparison = self._comparison()
        if not comparison.get("available"):
            return {"scope": comparison, "available": False, "summary": {}, "rows": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1}

        transition_period = str(filters.get("transition_period") or filters.get("metric_period") or "30d").lower()
        if transition_period not in METRIC_PERIODS:
            transition_period = "30d"
        change_type = str(filters.get("change_type") or "all")
        if change_type not in CHANGE_TYPES:
            raise ValueError("change_type 不存在")
        cache_key = tuple(sorted((str(key), str(value)) for key, value in filters.items())) + (comparison["current_date"], comparison["previous_date"], transition_period)
        cached = self._result_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]

        metric_period = str(filters.get("metric_period") or "30d").lower()
        wait_for_warmup = getattr(self._hub, "wait_for_comparison_warmup", None)
        if callable(wait_for_warmup):
            wait_for_warmup(comparison["previous_date"], metric_period)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="label-change") as executor:
            current_future = executor.submit(self._day_payload, comparison["current_date"], filters)
            previous_future = executor.submit(self._day_payload, comparison["previous_date"], filters)
            current = current_future.result()
            previous = previous_future.result()
        current_rows = current.pop("_comparison_rows", [])
        previous_rows = previous.pop("_comparison_rows", [])
        current_baseline = current.pop("_baseline_rows", [])
        previous_baseline = previous.pop("_baseline_rows", [])
        current_canonical_breakdowns = current.pop("_canonical_breakdown_units", {})
        previous_canonical_breakdowns = previous.pop("_canonical_breakdown_units", {})
        current_grouped = self._rows_by_business_unit(current_baseline)
        previous_grouped = self._rows_by_business_unit(previous_baseline)
        current_selected = self._rows_by_business_unit(current_rows)
        previous_selected = self._rows_by_business_unit(previous_rows)
        current_set = set(current_selected)
        previous_set = set(previous_selected)
        layer_parent = int(filters.get("layer_change_parent") or 0)
        layer_bucket = str(filters.get("layer_change_bucket") or "")
        layer_period = str(filters.get("layer_change_period") or "all")
        reason_parent = layer_parent or int(filters.get("parent_label_id") or 0)
        layer_transition_from = str(filters.get("layer_transition_from") or "")
        layer_transition_to = str(filters.get("layer_transition_to") or "")
        layer_transition_parent = int(filters.get("layer_transition_parent") or 0)
        layer_transition_previous = str(filters.get("layer_transition_previous") or "")
        layer_transition_current = str(filters.get("layer_transition_current") or "")
        if layer_parent and layer_bucket:
            # Keep every other selected label/local/problem condition in scope.  The
            # canonical bucket is only the clicked layer's membership, not a
            # replacement for the current combination.
            current_set &= set(current_canonical_breakdowns.get(layer_parent, {}).get(layer_bucket, set()))
            previous_set &= set(previous_canonical_breakdowns.get(layer_parent, {}).get(layer_bucket, set()))
        added = current_set - previous_set
        removed = previous_set - current_set
        kept = current_set & previous_set

        details = self._hub._cached_details()
        categories_list = self._hub._analysis_categories(details, {})
        categories = {int(item["id"]): item for item in categories_list}
        child_labels = {int(child["id"]): child["label"] for category in categories_list for child in category.get("children", [])}
        parent_labels = {int(item["id"]): item["label"] for item in categories_list}
        parent_id = int(current.get("parent_label_id") or filters.get("parent_label_id") or 0)
        parent_period = transition_period if parent_id == 1 else str(filters.get("label_period") or "all")
        current_primary = self._primary_map(current_grouped, parent_id, parent_period, categories)
        previous_primary = self._primary_map(previous_grouped, parent_id, parent_period, categories)
        layer_parent_id = layer_parent or parent_id
        layer_primary_period = layer_period if layer_parent else parent_period
        current_layer_primary = self._primary_map(current_grouped, layer_parent_id, layer_primary_period, categories)
        previous_layer_primary = self._primary_map(previous_grouped, layer_parent_id, layer_primary_period, categories)
        current_signatures = self._signature_map(current_grouped, categories, parent_period)
        previous_signatures = self._signature_map(previous_grouped, categories, parent_period)

        # The layer-change drawer compares a complete combination.  Expose the
        # actual state of every selected condition on each side of the
        # comparison so the UI does not reduce it to a vague "matched / not
        # matched" verdict.
        condition_map = self._hub.parse_conditions(str(filters.get("conditions") or ""))
        if layer_parent and layer_bucket:
            try:
                condition_map[layer_parent] = {int(layer_bucket)}
            except (TypeError, ValueError):
                pass
        analysis_parent_ids = _parse_int_pipe(filters.get("analysis_parent_ids"))
        analysis_periods = _parse_period_pipe(filters.get("analysis_periods"))
        period_by_parent = {
            parent: analysis_periods[index] if index < len(analysis_periods) else "all"
            for index, parent in enumerate(analysis_parent_ids)
        }
        if parent_id:
            period_by_parent[parent_id] = parent_period
        if layer_parent_id:
            period_by_parent[layer_parent_id] = layer_primary_period
        condition_primary_maps = {
            parent: (
                self._primary_map(previous_grouped, parent, period_by_parent.get(parent, "all"), categories),
                self._primary_map(current_grouped, parent, period_by_parent.get(parent, "all"), categories),
            )
            for parent in condition_map
            if parent in categories
        }

        changed = {unit for unit in kept if current_signatures.get(unit, {}) != previous_signatures.get(unit, {})}
        all_units = current_set | previous_set
        evidence = self._fetch_evidence(comparison["current_date"], comparison["previous_date"], transition_period)
        reason_period = layer_period if layer_parent else transition_period
        reason_units = (added | removed) if layer_parent and layer_bucket else (changed | added | removed)
        remote_evidence = self._fetch_remote_evidence(
            comparison["current_date"],
            comparison["previous_date"],
            reason_parent,
            reason_period,
            reason_units,
        )
        if reason_parent == 1:
            reason_by_unit, reason_distribution = self._sales_role_reasons(
                reason_units,
                previous_grouped,
                current_grouped,
                evidence,
                comparison["previous_date"],
                comparison["current_date"],
            )
        else:
            reason_by_unit, reason_distribution = {}, []

        def label_for(mapping: dict[BusinessUnitKey, int], unit: BusinessUnitKey) -> str:
            return child_labels.get(mapping.get(unit), "未命中")

        def unit_scope(rows: list[dict[str, Any]]) -> str:
            units = sorted({
                (str(row.get("country_category") or "-"), str(row.get("store") or "-"))
                for row in rows
            })
            if not units:
                return "无标签事实"
            labels = [f"{country} · {store}" for country, store in units]
            if len(labels) <= 2:
                return " / ".join(labels)
            return " / ".join(labels[:2]) + f" 等 {len(labels)} 个"

        def preferred_metric_label(rows: list[dict[str, Any]], code_field: str, label_field: str) -> str:
            measured = [row for row in rows if row.get("_metric_present")]
            if not measured:
                return "暂无经营数据"
            priority = LOCAL_VALUE_PRIORITY.get(code_field, [])
            rank = {value: index for index, value in enumerate(priority)}
            preferred = min(
                measured,
                key=lambda row: (rank.get(str(row.get(code_field) or "missing"), len(rank)), str(row.get(code_field) or "missing")),
            )
            return str(preferred.get(label_field) or "暂无数据")

        def preferred_metric_value(rows: list[dict[str, Any]], code_field: str, label_field: str) -> tuple[str, str]:
            measured = [row for row in rows if row.get("_metric_present")]
            if not measured:
                return "missing", "暂无经营数据"
            priority = LOCAL_VALUE_PRIORITY.get(code_field, [])
            rank = {value: index for index, value in enumerate(priority)}
            preferred = min(
                measured,
                key=lambda row: (rank.get(str(row.get(code_field) or "missing"), len(rank)), str(row.get(code_field) or "missing")),
            )
            return str(preferred.get(code_field) or "missing"), str(preferred.get(label_field) or "暂无数据")

        local_condition_definitions = (
            ("sales_trends", "sales_trend_code", "sales_trend", "动销趋势"),
            ("daily_sales_bands", "daily_sales_band_code", "daily_sales_band", "日销段"),
            ("margin_bands", "margin_band_code", "margin_band", "毛利段"),
        )

        def combination_condition_states(unit: BusinessUnitKey, source_rows: list[dict[str, Any]], is_current: bool) -> list[dict[str, Any]]:
            states: list[dict[str, Any]] = []
            for selected_parent, selected_children in condition_map.items():
                maps = condition_primary_maps.get(selected_parent)
                if not maps:
                    continue
                selected_code = (maps[1] if is_current else maps[0]).get(unit)
                states.append({
                    "dimension": parent_labels.get(selected_parent, str(selected_parent)),
                    "value": child_labels.get(selected_code, "无标签事实"),
                    "matched": selected_code in selected_children,
                    "target": " / ".join(child_labels.get(item, str(item)) for item in sorted(selected_children)),
            })
            for filter_key, code_field, label_field, dimension in local_condition_definitions:
                selected_codes = {
                    item for item in str(filters.get(filter_key) or "").split("|")
                    if item and item != "all"
                }
                if not selected_codes:
                    continue
                value_code, value_label = preferred_metric_value(source_rows, code_field, label_field)
                states.append({
                    "dimension": dimension,
                    "value": value_label,
                    "matched": value_code in selected_codes,
                    "target": " / ".join(selected_codes),
                })
            return states

        def metric_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
            measured = [row for row in rows if row.get("_metric_present")]
            sales_amount = sum(float(row.get("sales_amount") or 0) for row in measured)
            gross_profit = sum(float(row.get("order_gross_profit") or 0) for row in measured)
            return {
                "sales_trend": preferred_metric_label(rows, "sales_trend_code", "sales_trend"),
                "daily_sales_band": preferred_metric_label(rows, "daily_sales_band_code", "daily_sales_band"),
                "margin_band": preferred_metric_label(rows, "margin_band_code", "margin_band"),
                "sales_amount": round(sales_amount, 2),
                "order_gross_profit": round(gross_profit, 2),
                "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
                "data_status": "本地指标可用" if measured else "暂无经营数据",
            }

        def evidence_snapshot(value: dict[str, Any]) -> dict[str, Any]:
            if not value:
                return {}
            return {
                "daily_sales": round(float(value.get("daily_sales") or 0), 4),
                "margin_rate": round(float(value.get("tag_gross_margin") or 0), 4),
                "sales_qty": round(float(value.get("sales_qty") or 0), 2),
                "sales_amount": round(float(value.get("tag_sales_amount") or 0), 2),
                "gross_profit": round(float(value.get("tag_gross_profit") or 0), 2),
                "remote_sub_label_id": int(value.get("remote_sub_label_id") or 0),
                "computed_sub_label_id": int(value.get("computed_sub_label_id") or 0),
                "status": str(value.get("evidence_status") or "missing"),
            }

        def remote_evidence_snapshot(value: dict[str, Any]) -> dict[str, Any]:
            payload = value.get("evidence") if value else {}
            if not isinstance(payload, dict):
                return {}
            metrics = payload.get("metrics") or {}
            matched_rule = payload.get("matched_rule") or {}
            if not isinstance(metrics, dict):
                metrics = {}
            if not isinstance(matched_rule, dict):
                matched_rule = {}
            rule_metrics = []
            for key, raw_value in metrics.items():
                if raw_value is None:
                    continue
                label, value_type = RULE_METRIC_DEFINITIONS.get(
                    str(key),
                    (str(key).replace("_", " "), "number"),
                )
                rule_metrics.append({
                    "key": str(key),
                    "label": label,
                    "value": raw_value,
                    "value_type": value_type,
                    "matched_rule": str(matched_rule.get(key) or ""),
                })
            return {
                "rule_metrics": rule_metrics,
                "rule_version": str(payload.get("rule_version") or ""),
                "schema_version": str(payload.get("schema_version") or ""),
                "label_period": str(value.get("label_period") or ""),
                "status": "matched" if rule_metrics else "missing",
            }

        def rule_metric_changes(previous_value: dict[str, Any], current_value: dict[str, Any]) -> list[dict[str, Any]]:
            previous_by_key = {
                item["key"]: item for item in previous_value.get("rule_metrics", [])
            }
            current_by_key = {
                item["key"]: item for item in current_value.get("rule_metrics", [])
            }
            result = []
            for metric_key in list(current_by_key) + [key for key in previous_by_key if key not in current_by_key]:
                old = previous_by_key.get(metric_key, {})
                new = current_by_key.get(metric_key, {})
                result.append({
                    "key": metric_key,
                    "label": new.get("label") or old.get("label") or metric_key,
                    "previous": old.get("value"),
                    "current": new.get("value"),
                    "value_type": new.get("value_type") or old.get("value_type") or "number",
                    "previous_rule": old.get("matched_rule") or "",
                    "current_rule": new.get("matched_rule") or "",
                })
            return result

        def evidence_state(previous_value: dict[str, Any], current_value: dict[str, Any]) -> str:
            if not previous_value or not current_value:
                return "pending"
            if reason_parent != 1:
                return "confirmed"
            statuses = {str(previous_value.get("evidence_status") or "missing"), str(current_value.get("evidence_status") or "missing")}
            if statuses == {"matched"}:
                return "confirmed"
            if "mismatch" in statuses:
                return "mismatch"
            return "pending"

        rows = []
        generic_reason_counts: Counter[str] = Counter()
        for unit in all_units:
            country_category, store, msku = unit
            relation = "added" if unit in added else ("removed" if unit in removed else ("changed" if unit in changed else "unchanged"))
            trigger_parent_ids = sorted(parent_id for parent_id in set(previous_signatures.get(unit, {})) | set(current_signatures.get(unit, {})) if previous_signatures.get(unit, {}).get(parent_id) != current_signatures.get(unit, {}).get(parent_id))
            previous_rows_for_unit = previous_grouped.get(unit, [])
            current_rows_for_unit = current_grouped.get(unit, [])
            if not previous_rows_for_unit:
                fact_status = "上次无标签事实"
            elif not current_rows_for_unit:
                fact_status = "本次无标签事实"
            else:
                fact_status = "标签事实可比"
            reason = reason_by_unit.get(unit, {"code": "", "summary": ""})
            previous_evidence_raw = evidence.get((comparison["previous_date"], country_category, store, msku), {})
            current_evidence_raw = evidence.get((comparison["current_date"], country_category, store, msku), {})
            previous_remote_raw = self._select_remote_evidence(
                remote_evidence,
                comparison["previous_date"],
                unit,
                previous_signatures.get(unit, {}).get(reason_parent),
                reason_period,
            )
            current_remote_raw = self._select_remote_evidence(
                remote_evidence,
                comparison["current_date"],
                unit,
                current_signatures.get(unit, {}).get(reason_parent),
                reason_period,
            )
            evidence_state_previous = previous_evidence_raw
            evidence_state_current = current_evidence_raw
            if reason_parent == 1 and previous_remote_raw and current_remote_raw:
                remote_reason_previous = self._remote_reason_evidence(previous_remote_raw)
                remote_reason_current = self._remote_reason_evidence(current_remote_raw)
                evidence_state_previous = remote_reason_previous
                evidence_state_current = remote_reason_current
                reason_code, reason_summary = self._reason_for_pair(
                    remote_reason_previous,
                    remote_reason_current,
                )
                reason = {"code": reason_code, "summary": reason_summary}
            if reason_parent == 1 and (not previous_remote_raw or not current_remote_raw):
                previous_rule_evidence = evidence_snapshot(previous_evidence_raw)
                current_rule_evidence = evidence_snapshot(current_evidence_raw)
            else:
                previous_rule_evidence = remote_evidence_snapshot(previous_remote_raw)
                current_rule_evidence = remote_evidence_snapshot(current_remote_raw)
            metric_changes = rule_metric_changes(previous_rule_evidence, current_rule_evidence)
            if reason_parent != 1:
                if metric_changes:
                    primary_metric = metric_changes[0]
                    reason = {
                        "code": "rule_metric_change",
                        "summary": f"{primary_metric['label']}发生变化",
                    }
                    generic_reason_counts[str(primary_metric["label"])] += 1
                elif not previous_remote_raw or not current_remote_raw:
                    reason = {
                        "code": "evidence_missing",
                        "summary": "规则证据缺失，暂时只能确认标签事实变化",
                    }
                    generic_reason_counts["规则证据缺失"] += 1
            current_metrics = metric_snapshot(current_rows_for_unit)
            previous_metrics = metric_snapshot(previous_rows_for_unit)
            label_changes = [
                {
                    "parent_id": trigger_parent_id,
                    "dimension": parent_labels.get(trigger_parent_id, str(trigger_parent_id)),
                    "previous_label": child_labels.get(
                        previous_signatures.get(unit, {}).get(trigger_parent_id),
                        "未命中",
                    ),
                    "current_label": child_labels.get(
                        current_signatures.get(unit, {}).get(trigger_parent_id),
                        "未命中",
                    ),
                }
                for trigger_parent_id in trigger_parent_ids
            ]
            rows.append({
                "business_unit_key": "|".join(unit),
                "country_category": country_category,
                "store": store,
                "msku": msku,
                "previous_label": label_for(previous_primary, unit),
                "current_label": label_for(current_primary, unit),
                "previous_layer_label": label_for(previous_layer_primary, unit),
                "current_layer_label": label_for(current_layer_primary, unit),
                "previous_combination_conditions": combination_condition_states(unit, previous_rows_for_unit, False),
                "current_combination_conditions": combination_condition_states(unit, current_rows_for_unit, True),
                "change_type": relation,
                "change_type_label": {"added": "新增", "removed": "减少", "changed": "标签变化", "unchanged": "保持"}[relation],
                "trigger_dimensions": [parent_labels.get(item, str(item)) for item in trigger_parent_ids],
                "label_changes": label_changes,
                "previous_matched": unit in previous_set,
                "current_matched": unit in current_set,
                "business_unit_count": 1,
                "previous_unit_scope": unit_scope(previous_rows_for_unit),
                "current_unit_scope": unit_scope(current_rows_for_unit),
                "fact_status": fact_status,
                "previous_metric_profile": previous_metrics,
                "metric_profile": current_metrics,
                "sales_role_reason_code": reason["code"],
                "sales_role_reason": reason["summary"],
                "previous_evidence": previous_rule_evidence,
                "current_evidence": current_rule_evidence,
                "rule_metric_changes": metric_changes,
                "evidence_state": evidence_state(
                    evidence_state_previous if reason_parent == 1 else previous_remote_raw,
                    evidence_state_current if reason_parent == 1 else current_remote_raw,
                ),
            })

        if reason_parent == 1:
            refreshed_reason_counts = Counter(
                str(row.get("sales_role_reason_code") or "")
                for row in rows
                if row.get("sales_role_reason_code")
            )
            reason_distribution = [
                {"key": code, "label": label, "count": refreshed_reason_counts.get(code, 0)}
                for code, label in REASON_LABELS.items()
            ]
        else:
            reason_distribution = [
                {
                    "key": "evidence_missing" if label == "规则证据缺失" else "rule_metric_change",
                    "label": label if label == "规则证据缺失" else f"{label}变化",
                    "count": count,
                }
                for label, count in generic_reason_counts.most_common()
            ]

        layer_transitions = {"entered": [], "left": []}
        if layer_parent and layer_bucket:
            def display_change(row: dict[str, Any], relation: str) -> tuple[int, str, str, str]:
                if row["previous_layer_label"] != row["current_layer_label"]:
                    return (
                        layer_parent_id,
                        parent_labels.get(layer_parent_id, str(layer_parent_id)),
                        row["previous_layer_label"],
                        row["current_layer_label"],
                    )
                candidates = [
                    item for item in row.get("label_changes", [])
                    if int(item.get("parent_id") or 0) != layer_parent_id
                ]
                candidates.sort(
                    key=lambda item: (
                        0 if int(item.get("parent_id") or 0) in condition_map else 1,
                        int(item.get("parent_id") or 0),
                    )
                )
                if candidates:
                    item = candidates[0]
                    return (
                        int(item.get("parent_id") or 0),
                        str(item.get("dimension") or "其他标签"),
                        str(item.get("previous_label") or "未命中"),
                        str(item.get("current_label") or "未命中"),
                    )
                return (
                    0,
                    "其他筛选条件",
                    "上次不满足" if relation == "added" else "上次满足",
                    "今日满足" if relation == "added" else "今日不满足",
                )

            def transition_rows(relation: str) -> list[dict[str, Any]]:
                grouped: dict[tuple[str, str, int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    if row["change_type"] == relation:
                        changed_parent, changed_dimension, changed_previous, changed_current = display_change(row, relation)
                        grouped[
                            (
                                row["previous_layer_label"],
                                row["current_layer_label"],
                                changed_parent,
                                changed_dimension,
                                changed_previous,
                                changed_current,
                            )
                        ].append(row)
                result_rows = []
                for (
                    previous_label,
                    current_label,
                    changed_parent,
                    changed_dimension,
                    changed_previous,
                    changed_current,
                ), transition_items in grouped.items():
                    reasons = (
                        Counter(item.get("sales_role_reason_code") or "evidence_missing" for item in transition_items)
                        if layer_parent == 1
                        else Counter({"fact_only": len(transition_items)})
                    )
                    evidence_states = Counter(item.get("evidence_state") or "fact_only" for item in transition_items)
                    sales_amount = sum(float(item.get("metric_profile", {}).get("sales_amount") or 0) for item in transition_items)
                    gross_profit = sum(float(item.get("metric_profile", {}).get("order_gross_profit") or 0) for item in transition_items)
                    main_reason_code = reasons.most_common(1)[0][0] if reasons else "fact_only"
                    main_reason_label = REASON_LABELS.get(main_reason_code, "仅记录标签事实")
                    result_rows.append({
                        "previous_label": previous_label,
                        "current_label": current_label,
                        "changed_parent_id": changed_parent,
                        "changed_dimension": changed_dimension,
                        "changed_previous_label": changed_previous,
                        "changed_current_label": changed_current,
                        "count": len(transition_items),
                        "main_reason_code": main_reason_code,
                        "main_reason": main_reason_label,
                        "reason_counts": dict(reasons),
                        "evidence_counts": dict(evidence_states),
                        "sales_amount": round(sales_amount, 2),
                        "order_gross_profit": round(gross_profit, 2),
                    })
                result_rows.sort(key=lambda item: (-int(item["count"]), item["previous_label"], item["current_label"]))
                return result_rows

            layer_transitions = {
                "entered": transition_rows("added"),
                "left": transition_rows("removed"),
            }

        combination_summary = {
            "previous": len(previous_set),
            "current": len(current_set),
            "added": len(added),
            "removed": len(removed),
            "unchanged": len(kept),
            "net": len(added) - len(removed),
            "entered": layer_transitions["entered"][:3],
            "left": layer_transitions["left"][:3],
            "reason_summary": sorted(
                (item for item in reason_distribution if int(item.get("count") or 0) > 0),
                key=lambda item: int(item.get("count") or 0),
                reverse=True,
            )[:3],
        }

        previous_parent = Counter(label_for(previous_primary, unit) for unit in previous_grouped)
        current_parent = Counter(label_for(current_primary, unit) for unit in current_grouped)
        matrix_cells = Counter((label_for(previous_primary, unit), label_for(current_primary, unit)) for unit in set(previous_grouped) | set(current_grouped))
        transition_matrix = {
            "rows": [{"key": label, "label": label, "count": count} for label, count in previous_parent.items()],
            "columns": [{"key": label, "label": label, "count": count} for label, count in current_parent.items()],
            "cells": [{"row": row, "column": column, "count": count} for (row, column), count in matrix_cells.items()],
        }

        # “全部变化”只列出发生变化的记录；保持不变的记录用于两期数量对账，
        # 但不应混入分层变化明细，否则会掩盖当前层真正的转入、转出和标签切换。
        if change_type == "all":
            rows = [row for row in rows if row["change_type"] != "unchanged"]
        else:
            rows = [row for row in rows if row["change_type"] == change_type]
        if layer_transition_from or layer_transition_to:
            rows = [
                row for row in rows
                if (not layer_transition_from or row["previous_layer_label"] == layer_transition_from)
                and (not layer_transition_to or row["current_layer_label"] == layer_transition_to)
            ]
        if layer_transition_parent or layer_transition_previous or layer_transition_current:
            if layer_parent and layer_bucket:
                # Route cards are grouped with display_change(), which uses the
                # normalized primary label for the selected period.  Filtering
                # the detail rows against raw label_changes here can disagree
                # for multi-period labels and produce an empty table even when
                # the selected route has records.  Reuse the exact route
                # identity that produced the card so card totals and details
                # always reconcile.
                rows = [
                    row for row in rows
                    if (
                        (route := display_change(row, row["change_type"]))[0] == layer_transition_parent
                        and (not layer_transition_previous or route[2] == layer_transition_previous)
                        and (not layer_transition_current or route[3] == layer_transition_current)
                    )
                ]
            else:
                rows = [
                    row for row in rows
                    if (
                        layer_transition_parent == 0
                        and not row.get("label_changes")
                    ) or any(
                        int(item.get("parent_id") or 0) == layer_transition_parent
                        and (not layer_transition_previous or item.get("previous_label") == layer_transition_previous)
                        and (not layer_transition_current or item.get("current_label") == layer_transition_current)
                        for item in row.get("label_changes", [])
                    )
                ]
        sort_field = str(filters.get("sort_field") or "change_type")
        sort_field = sort_field if sort_field in CHANGE_SORT_FIELDS else "change_type"
        sort_dir = str(filters.get("sort_dir") or "asc").lower()
        change_rank = {"added": 0, "removed": 1, "changed": 2, "unchanged": 3}
        rows.sort(key=lambda row: (change_rank.get(row["change_type"], 9), row["country_category"], row["store"], row["msku"]) if sort_field == "change_type" else (row.get(sort_field) or "", row["country_category"], row["store"], row["msku"]), reverse=sort_dir == "desc")
        page_size = max(10, min(100, int(filters.get("page_size") or 20)))
        total_pages = max(1, math.ceil(len(rows) / page_size))
        page = min(max(1, int(filters.get("page") or 1)), total_pages)
        start = (page - 1) * page_size

        result = {
            "available": True,
            "scope": {
                **comparison,
                "transition_period": transition_period,
                "comparison_label": "较昨日" if comparison.get("gap_days") == 1 else "较上次数据",
                "layer_change_parent": layer_parent,
                "layer_change_bucket": layer_bucket,
                "combination_mode": bool(layer_parent and layer_bucket),
                "layer_transition_from": layer_transition_from,
                "layer_transition_to": layer_transition_to,
                "layer_transition_parent": layer_transition_parent,
                "layer_transition_previous": layer_transition_previous,
                "layer_transition_current": layer_transition_current,
            },
            "summary": {
                "current": len(current_set), "previous": len(previous_set),
                "added": len(added), "removed": len(removed),
                "unchanged": len(kept), "changed": len(changed),
                "net": len(added) - len(removed),
                "unique_msku_count": len({unit[2] for unit in all_units}),
            },
            "combination_summary": combination_summary,
            "overview_deltas": self._delta_overview(current.get("overview", []), previous.get("overview", [])),
            "breakdown_deltas": self._delta_breakdowns(current.get("breakdowns", []), previous.get("breakdowns", [])),
            "selected_group_delta": {"current": len(current_set), "previous": len(previous_set), "delta": len(current_set) - len(previous_set), "rate": round((len(current_set) - len(previous_set)) / len(previous_set), 4) if previous_set else None},
            "issue_deltas": {key: int(current.get("issue_counts", {}).get(key, 0)) - int(previous.get("issue_counts", {}).get(key, 0)) for key in set(current.get("issue_counts", {})) | set(previous.get("issue_counts", {}))},
            "issue_counts": {"current": current.get("issue_counts", {}), "previous": previous.get("issue_counts", {})},
            "transition_matrix": transition_matrix,
            "sales_role_reasons": reason_distribution,
            "layer_transitions": layer_transitions,
            "rows": rows[start : start + page_size],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
        self._result_cache[cache_key] = (datetime.now(), result)
        return result

    def get_msku_change(self, *, msku: str, transition_period: str = "30d") -> dict[str, Any]:
        comparison = self._comparison()
        if not comparison.get("available"):
            raise ValueError("当前只有一天标签数据，暂无变化追溯")
        transition_period = transition_period if transition_period in METRIC_PERIODS else "30d"
        details = self._hub._cached_details()
        detail_by_id = {int(item["sub_label_id"]): item for item in details}

        def day_profile(data_date: str) -> dict[str, Any]:
            facts = [fact for fact in self._hub._cached_facts(data_date) if str(fact.get("msku") or "") == msku]
            units: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for fact in facts:
                detail = detail_by_id.get(int(fact.get("label_id") or 0))
                if not detail:
                    continue
                units[(str(fact.get("country_category") or ""), str(fact.get("store") or ""))].append({
                    "parent_id": int(detail["label_id"]), "parent_label": detail.get("label_name") or "",
                    "id": int(fact["label_id"]), "label": detail.get("sub_label_name") or "",
                    "period": str(fact.get("label_period") or ""), "rule": detail.get("tag_rule") or "",
                })
            return {"data_date": data_date, "units": [{"country_category": key[0], "store": key[1], "labels": sorted(labels, key=lambda item: (item["parent_id"], item["period"], item["id"]))} for key, labels in sorted(units.items())]}

        evidence = self._fetch_evidence(comparison["current_date"], comparison["previous_date"], transition_period)
        evidence_rows = [dict(row) for key, row in evidence.items() if key[3] == msku]
        return {"identity": {"msku": msku}, "scope": {**comparison, "transition_period": transition_period}, "previous": day_profile(comparison["previous_date"]), "current": day_profile(comparison["current_date"]), "sales_role_evidence": evidence_rows}


label_hub_change_service = LabelHubChangeDataService()
