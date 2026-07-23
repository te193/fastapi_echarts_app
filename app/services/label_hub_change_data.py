from __future__ import annotations

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
        self._base_day_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}

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
            old = evidence.get((previous_date, country, store, msku), {}) if unit in previous_grouped else {}
            new = evidence.get((current_date, country, store, msku), {}) if unit in current_grouped else {}
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
        layer_transition_from = str(filters.get("layer_transition_from") or "")
        layer_transition_to = str(filters.get("layer_transition_to") or "")
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
        reason_by_unit, reason_distribution = self._sales_role_reasons(changed | added | removed, previous_grouped, current_grouped, evidence, comparison["previous_date"], comparison["current_date"])

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

        rows = []
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
            current_metrics = metric_snapshot(current_rows_for_unit)
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
                "previous_matched": unit in previous_set,
                "current_matched": unit in current_set,
                "business_unit_count": 1,
                "previous_unit_scope": unit_scope(previous_rows_for_unit),
                "current_unit_scope": unit_scope(current_rows_for_unit),
                "fact_status": fact_status,
                "metric_profile": current_metrics,
                "sales_role_reason_code": reason["code"],
                "sales_role_reason": reason["summary"],
            })

        layer_transitions = {"entered": [], "left": []}
        if layer_parent and layer_bucket:
            def transition_rows(relation: str) -> list[dict[str, Any]]:
                counts = Counter(
                    (row["previous_layer_label"], row["current_layer_label"])
                    for row in rows
                    if row["change_type"] == relation
                )
                return [
                    {"previous_label": previous_label, "current_label": current_label, "count": count}
                    for (previous_label, current_label), count in counts.most_common()
                ]

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
