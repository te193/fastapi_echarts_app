from __future__ import annotations

import math
from collections import OrderedDict, defaultdict
from datetime import datetime
from itertools import combinations
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode

from .label_hub_data import CACHE_SECONDS, LabelHubDataService, _number, _period_order, label_hub_service
from .label_hub_local_metrics import METRIC_PERIODS


COUNTRY_PARENT_IDS = (4, 7, 13, 14)
COUNTRY_PARENT_SET = set(COUNTRY_PARENT_IDS)
PAGE_SIZES = {20, 50, 100}
SORT_FIELDS = {
    "problem_priority",
    "country",
    "country_category",
    "store",
    "msku",
    "sales_qty",
    "daily_sales",
    "sales_amount",
    "order_gross_profit",
    "order_gross_margin",
    "ending_inventory_qty",
}
LOCAL_FILTERS = {
    "sales_trends": {"accelerating", "growing", "stable", "slowing", "declining", "stopped", "no_sales", "recent_start", "insufficient", "missing"},
    "daily_sales_bands": {"zero", "lt1", "1_5", "gt5", "missing"},
    "margin_bands": {"lt5", "5_10", "10_15", "15_25", "gt25", "missing"},
}
ISSUES = {
    "all",
    "problem_product",
    "zero_sales",
    "negative_profit",
    "low_margin",
    "missing_metrics",
    "conflict",
    "site_status_abnormal",
    "pricing_risk",
    "cross_country_inconsistent",
}


def _parse_codes(value: Any, allowed: set[str], field: str) -> set[str]:
    values = {item for item in str(value or "").split("|") if item and item != "all"}
    if not values.issubset(allowed):
        raise ValueError(f"{field} 包含无效选项")
    return values


def _parse_periods(value: Any) -> dict[int, str]:
    result: dict[int, str] = {}
    for group in str(value or "").split(";"):
        if not group:
            continue
        parent_text, separator, period = group.partition(":")
        if not separator or not parent_text.isdigit() or int(parent_text) not in COUNTRY_PARENT_SET:
            raise ValueError("label_periods 格式应为 父标签:周期")
        result[int(parent_text)] = period or "all"
    return result


class CountryLabelHubDataService:
    """Country/store/MSKU label analysis built on the shared label fact cache."""

    def __init__(self, shared: LabelHubDataService = label_hub_service) -> None:
        self._shared = shared
        self._meta_cache: tuple[datetime, dict[str, Any]] | None = None
        self._facts_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._base_rows_cache: OrderedDict[tuple[Any, ...], tuple[datetime, list[dict[str, Any]]]] = OrderedDict()
        self._base_rows_lock = RLock()

    def get_meta(self) -> dict[str, Any]:
        if self._meta_cache and (datetime.now() - self._meta_cache[0]).total_seconds() < CACHE_SECONDS:
            return dict(self._meta_cache[1])
        shared_meta = self._shared.get_meta()
        categories = [item for item in shared_meta.get("excluded_categories", []) if item["id"] in COUNTRY_PARENT_SET]
        category_ids = {item["id"] for item in categories}
        missing = [parent for parent in COUNTRY_PARENT_IDS if parent not in category_ids]
        stores_by_country = {
            str(country): sorted({str(store) for store in stores if str(store)})
            for country, stores in (shared_meta.get("stores_by_country") or {}).items()
        }
        default_date = shared_meta.get("default_data_date", "")
        if default_date and not stores_by_country:
            fallback: dict[str, set[str]] = defaultdict(set)
            for fact in self._shared._cached_facts(default_date):
                country = str(fact.get("country_category") or "")
                store = str(fact.get("store") or "")
                if country and store:
                    fallback[country].add(store)
            stores_by_country = {country: sorted(stores) for country, stores in fallback.items()}
        payload = {
            "default_data_date": default_date,
            "data_dates": shared_meta.get("data_dates", []),
            "metric_periods": shared_meta.get("metric_periods", []),
            "default_metric_period": "30d",
            "country_categories": shared_meta.get("country_categories", []),
            "stores": shared_meta.get("stores", []),
            "stores_by_country": stores_by_country,
            "categories": categories,
            "missing_parent_ids": missing,
            "local_breakdowns": [item for item in shared_meta.get("local_breakdowns", []) if item.get("key") in {"sales_trend", "daily_sales_band", "margin_band"}],
            "source_status": {"remote_labels": "available", "local_metrics": "checked_per_request"},
        }
        self._meta_cache = (datetime.now(), payload)
        return dict(payload)

    def get_payload(self, **filters: Any) -> dict[str, Any]:
        meta = self.get_meta()
        data_date = str(meta.get("default_data_date") or "")
        metric_period = str(filters.get("metric_period") or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 仅支持 7d、14d、30d、90d")
        problem = str(filters.get("problem") or "all")
        if problem not in ISSUES:
            raise ValueError("problem 包含无效选项")
        page_size = int(filters.get("page_size") or 20)
        if page_size not in PAGE_SIZES:
            raise ValueError("page_size 仅支持 20、50、100")
        sort_field = str(filters.get("sort_field") or "problem_priority")
        if sort_field not in SORT_FIELDS:
            raise ValueError("sort_field 包含无效字段")
        sort_dir = str(filters.get("sort_dir") or "desc").lower()
        if sort_dir not in {"asc", "desc"}:
            raise ValueError("sort_dir 仅支持 asc 或 desc")

        conditions = self._shared.parse_conditions(filters.get("conditions", ""))
        if any(parent not in COUNTRY_PARENT_SET for parent in conditions):
            raise ValueError("conditions 包含非国家口径标签")
        selected_periods = _parse_periods(filters.get("label_periods", ""))
        local_filters = {
            "sales_trend_code": _parse_codes(filters.get("sales_trends", ""), LOCAL_FILTERS["sales_trends"], "sales_trends"),
            "daily_sales_band_code": _parse_codes(filters.get("daily_sales_bands", ""), LOCAL_FILTERS["daily_sales_bands"], "daily_sales_bands"),
            "margin_band_code": _parse_codes(filters.get("margin_bands", ""), LOCAL_FILTERS["margin_bands"], "margin_bands"),
        }
        country = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().lower()
        details = self._shared._cached_details()
        facts = self._cached_country_facts(data_date)
        try:
            metric_scope = self._shared._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}

        categories = list(meta.get("categories") or [])
        category_by_id = {item["id"]: item for item in categories}
        child_parent = {child["id"]: category["id"] for category in categories for child in category["children"]}
        child_detail = {int(item["sub_label_id"]): item for item in details if int(item["label_id"]) in COUNTRY_PARENT_SET}
        for parent, children in conditions.items():
            if parent not in category_by_id or any(child_parent.get(child) != parent for child in children):
                raise ValueError("conditions 包含不存在或归属错误的标签")

        periods = self._resolve_periods(categories, selected_periods, metric_period)
        base_rows = self._cached_base_rows(
            data_date,
            metric_period,
            periods,
            facts,
            category_by_id,
            child_detail,
            metric_scope,
        )
        rows = [
            row
            for row in base_rows
            if (country == "all" or row["country_category"] == country)
            and (store == "all" or row["store"] == store)
            and (not keyword or keyword in row["_search_text"])
        ]
        overview = self._overview(rows, categories, periods)
        final_rows = self._filter_rows(rows, conditions, local_filters, problem)
        country_comparison = self._country_comparison(final_rows, categories)
        kpis = self._kpis(final_rows)
        issue_scope_rows = self._filter_rows(rows, conditions, local_filters, "all")
        issue_counts = {issue: sum(self._matches_problem(row, issue) for row in issue_scope_rows) for issue in ISSUES if issue != "all"}
        issue_counts["all"] = len(issue_scope_rows)

        label_breakdowns = []
        for category in categories:
            panel_rows = self._filter_rows(rows, {parent: values for parent, values in conditions.items() if parent != category["id"]}, local_filters, problem)
            label_breakdowns.append(self._label_breakdown(panel_rows, category, periods.get(category["id"], "all")))
        metric_breakdowns = []
        for field, key, label in (
            ("sales_trend_code", "sales_trend", "销售趋势"),
            ("daily_sales_band_code", "daily_sales_band", "日销段"),
            ("margin_band_code", "margin_band", "毛利段"),
        ):
            panel_filters = {name: values for name, values in local_filters.items() if name != field}
            panel_rows = self._filter_rows(rows, conditions, panel_filters, problem)
            metric_breakdowns.append(self._local_breakdown(panel_rows, field, key, label))

        matrices = [
            self._matrix(final_rows, category_by_id, row_parent, col_parent, periods)
            for row_parent, col_parent in combinations((category["id"] for category in categories), 2)
        ]
        sorted_rows = self._sort_rows(final_rows, sort_field, sort_dir)
        total = len(sorted_rows)
        total_pages = max(1, math.ceil(total / page_size))
        page = max(1, min(int(filters.get("page") or 1), total_pages))
        start = (page - 1) * page_size
        public_rows = [self._public_row(row) for row in sorted_rows[start:start + page_size]]

        metric_count = sum(row["_metric_present"] for row in final_rows)
        return {
            "data_date": data_date,
            "scope": {
                "label_data_date": data_date,
                "local_metrics_status": metric_scope.get("status") or "unavailable",
                "metric_window": metric_scope.get("window") or {},
                "metric_coverage_rate": round(metric_count / len(final_rows), 4) if final_rows else 0,
                "label_periods": {str(key): value for key, value in periods.items()},
            },
            "kpis": kpis,
            "country_comparison": country_comparison,
            "overview": overview,
            "issue_counts": issue_counts,
            "label_breakdowns": label_breakdowns,
            "metric_breakdowns": metric_breakdowns,
            "matrices": matrices,
            "rows": public_rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def _cached_country_facts(self, data_date: str) -> list[dict[str, Any]]:
        cached = self._facts_cache.get(data_date)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        fetcher = getattr(self._shared, "_fetch_facts", None)
        facts = (
            fetcher(data_date, parent_ids=COUNTRY_PARENT_IDS)
            if callable(fetcher)
            else self._shared._cached_facts(data_date)
        )
        self._facts_cache[data_date] = (datetime.now(), facts)
        return facts

    def _cached_base_rows(self, data_date, metric_period, periods, facts, categories, child_detail, metric_scope):
        cache_key = (data_date, metric_period, tuple(sorted(periods.items())))
        now = datetime.now()
        with self._base_rows_lock:
            cached = self._base_rows_cache.get(cache_key)
            if cached and (now - cached[0]).total_seconds() < CACHE_SECONDS:
                self._base_rows_cache.move_to_end(cache_key)
                return cached[1]

            grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
            for fact in facts:
                detail = child_detail.get(int(fact.get("label_id") or 0))
                if not detail:
                    continue
                key = (
                    str(fact.get("country") or "未配置国家"),
                    str(fact.get("country_category") or ""),
                    str(fact.get("store") or ""),
                    str(fact.get("msku") or ""),
                )
                grouped[key].append({**fact, "detail": detail})

            rows = [
                self._make_row(key, label_facts, categories, child_detail, periods, metric_scope)
                for key, label_facts in grouped.items()
            ]
            self._mark_cross_country_inconsistency(rows)
            self._base_rows_cache[cache_key] = (now, rows)
            self._base_rows_cache.move_to_end(cache_key)
            while len(self._base_rows_cache) > 4:
                self._base_rows_cache.popitem(last=False)
            return rows

    def _resolve_periods(self, categories: list[dict[str, Any]], requested: dict[int, str], metric_period: str) -> dict[int, str]:
        resolved: dict[int, str] = {}
        for category in categories:
            available = sorted({period for child in category["children"] for period in child.get("periods", []) if period}, key=_period_order)
            request = requested.get(category["id"])
            if request and request != "all" and request not in available:
                raise ValueError(f"{category['label']} 不支持标签周期 {request}")
            if request:
                resolved[category["id"]] = request
            elif category["id"] in {13, 14} and metric_period in available:
                resolved[category["id"]] = metric_period
            else:
                resolved[category["id"]] = available[0] if len(available) == 1 else "all"
        return resolved

    def _make_row(self, key, label_facts, categories, child_detail, periods, metric_scope):
        by_parent_period: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for fact in label_facts:
            parent = int(fact["detail"]["label_id"])
            by_parent_period[parent][str(fact.get("label_period") or "")].add(int(fact["label_id"]))
        primary: dict[int, int | None] = {}
        conflicts = []
        for parent, category in categories.items():
            period = periods.get(parent, "all")
            selected = set().union(*by_parent_period.get(parent, {}).values()) if period == "all" else by_parent_period.get(parent, {}).get(period, set())
            primary[parent] = next((child for child in category.get("aggregation_priority_ids", []) if child in selected), min(selected) if selected else None)
            if category.get("mutual_exclusion") and any(len(values) > 1 for values in by_parent_period.get(parent, {}).values()):
                conflicts.append(parent)
        metric_key = (key[1], key[2], key[3])
        metric = (metric_scope.get("metrics") or {}).get(metric_key)
        labels = {parent: (child_detail.get(child, {}).get("sub_label_name") if child else "") for parent, child in primary.items()}
        row = {
            "country": key[0], "country_category": key[1], "store": key[2], "msku": key[3],
            "_label_facts": label_facts, "_by_parent_period": by_parent_period, "_primary": primary,
            "_metric": metric or {}, "_metric_key": metric_key, "_metric_present": metric is not None,
            "conflict": bool(conflicts), "conflict_parent_ids": conflicts,
            "price_label": labels.get(4) or "未命中", "site_status_label": labels.get(7) or "未命中",
            "country_sales_role_label": labels.get(13) or "未命中", "site_lifecycle_label": labels.get(14) or "未命中",
            "data_status": "本地指标可用" if metric is not None else ("暂无本地经营数据" if metric_scope.get("status") == "available" else "本地经营指标暂不可用"),
            "cross_country_inconsistent": False,
            "_search_text": " ".join(key).lower(),
        }
        for field in ("sales_qty", "daily_sales", "sales_amount", "order_gross_profit", "order_gross_margin", "ending_inventory_qty", "settlement_gross_profit", "ad_spend", "ad_sales", "acos", "tacos", "return_count", "return_amount", "net_amount", "sales_trend_ratio"):
            row[field] = _number((metric or {}).get(field))
        for field in ("sales_role_code", "sales_trend_code", "sales_trend", "daily_sales_band_code", "daily_sales_band", "margin_band_code", "margin_band"):
            row[field] = (metric or {}).get(field) or ("missing" if field.endswith("_code") else "暂无经营数据")
        return row

    def _mark_cross_country_inconsistency(self, rows):
        by_msku = defaultdict(list)
        for row in rows:
            by_msku[row["msku"]].append(row)
        for group in by_msku.values():
            if len({(row["country"], row["country_category"], row["store"]) for row in group}) < 2:
                continue
            inconsistent = any(len({row["_primary"].get(parent) for row in group if row["_primary"].get(parent)}) > 1 for parent in COUNTRY_PARENT_IDS)
            if inconsistent:
                for row in group:
                    row["cross_country_inconsistent"] = True

    def _matches_conditions(self, row, conditions):
        return all(row["_primary"].get(parent) in values for parent, values in conditions.items())

    def _filter_rows(self, rows, conditions, local_filters, problem):
        result = []
        for row in rows:
            if not self._matches_conditions(row, conditions):
                continue
            if any(values and str(row.get(field)) not in values for field, values in local_filters.items()):
                continue
            if problem != "all" and not self._matches_problem(row, problem):
                continue
            result.append(row)
        return result

    def _matches_problem(self, row, problem):
        if problem == "all": return True
        if problem == "problem_product": return "问题产品" in row.get("country_sales_role_label", "")
        if problem == "zero_sales": return row["_metric_present"] and float(row.get("daily_sales") or 0) <= 0
        if problem == "negative_profit": return row["_metric_present"] and float(row.get("order_gross_profit") or 0) < 0
        if problem == "low_margin": return row["_metric_present"] and float(row.get("order_gross_margin") or 0) < 0.05
        if problem == "missing_metrics": return not row["_metric_present"]
        if problem == "conflict": return row["conflict"]
        if problem == "site_status_abnormal": return any(word in row["site_status_label"] for word in ("部分", "异常", "停售", "断货"))
        if problem == "pricing_risk": return any(word in row["price_label"] for word in ("亏损", "低毛利", "清仓", "异常"))
        if problem == "cross_country_inconsistent": return row["cross_country_inconsistent"]
        return False

    def _stats(self, rows):
        metric_rows = self._unique_metric_rows(rows)
        sales = sum(row.get("sales_amount") or 0 for row in metric_rows)
        profit = sum(row.get("order_gross_profit") or 0 for row in metric_rows)
        return {"business_unit_count": len(rows), "msku_count": len(rows), "share": 0, "sales_amount": round(sales, 2), "order_gross_profit": round(profit, 2), "order_gross_margin": round(profit / sales, 4) if sales else 0}

    def _population(self, rows):
        return {
            "country_count": len({row["country"] for row in rows}),
            "country_category_count": len({row["country_category"] for row in rows}),
            "store_count": len({row["store"] for row in rows}),
            "business_unit_count": len(rows),
        }

    @staticmethod
    def _unique_metric_rows(rows):
        unique = {}
        for row in rows:
            if row.get("_metric_present"):
                unique.setdefault(row["_metric_key"], row)
        return list(unique.values())

    def _kpis(self, rows):
        stats = self._stats(rows)
        matched = sum(row["_metric_present"] for row in rows)
        metric_rows = self._unique_metric_rows(rows)
        inventory = defaultdict(list)
        for row in rows:
            if row.get("ending_inventory_qty") is not None:
                inventory[(row["store"], row["msku"])].append(row["ending_inventory_qty"])
        return {**self._population(rows), **stats, "metric_business_unit_count": matched, "metric_coverage_rate": round(matched / len(rows), 4) if rows else 0, "sales_qty": round(sum(row.get("sales_qty") or 0 for row in metric_rows), 2), "ending_inventory_qty": round(sum(max(values) for values in inventory.values()), 2)}

    def _overview(self, rows, categories, periods):
        result = []
        for category in categories:
            parent = category["id"]
            matched = [row for row in rows if row["_primary"].get(parent)]
            buckets = self._label_buckets(matched, category)
            result.append({**category, "selected_period": periods.get(parent, "all"), "business_unit_count": len(matched), "country_count": len({row["country"] for row in matched}), "coverage_rate": round(len(matched) / len(rows), 4) if rows else 0, "buckets": buckets})
        return result

    def _label_buckets(self, rows, category):
        grouped = defaultdict(list)
        parent = category["id"]
        for row in rows:
            grouped[row["_primary"].get(parent)].append(row)
        result = []
        for child in category.get("children", []):
            matched = grouped.get(child["id"], [])
            stats = self._stats(matched)
            result.append({"id": child["id"], "key": str(child["id"]), "label": child["label"], **stats})
        total = len(rows)
        for bucket in result:
            bucket["share"] = round(bucket["business_unit_count"] / total, 4) if total else 0
        return result

    def _label_breakdown(self, rows, category, period):
        return {"source": "remote_label", "parent_id": category["id"], "key": f"parent_{category['id']}", "label": category["label"], "selected_period": period, "business_unit_count": len(rows), "buckets": self._label_buckets(rows, category)}

    def _local_breakdown(self, rows, field, key, label):
        labels = {}
        grouped = defaultdict(list)
        for row in rows:
            code = str(row.get(field) or "missing")
            labels[code] = str(row.get(key) or "暂无经营数据")
            grouped[code].append(row)
        order = list(LOCAL_FILTERS[{"sales_trend_code": "sales_trends", "daily_sales_band_code": "daily_sales_bands", "margin_band_code": "margin_bands"}[field]])
        buckets = []
        for code in order:
            matched = grouped.get(code, [])
            stats = self._stats(matched)
            stats["share"] = round(len(matched) / len(rows), 4) if rows else 0
            buckets.append({"key": code, "label": labels.get(code, "暂无经营数据" if code == "missing" else code), **stats})
        return {"source": "local", "key": key, "label": label, "business_unit_count": len(rows), "buckets": buckets}

    def _matrix(self, rows, categories, row_parent, col_parent, periods):
        row_category, col_category = categories.get(row_parent), categories.get(col_parent)
        if not row_category or not col_category:
            return {"row_parent_id": row_parent, "col_parent_id": col_parent, "rows": [], "columns": [], "cells": []}
        grouped = defaultdict(list)
        for item in rows:
            grouped[(item["_primary"].get(row_parent), item["_primary"].get(col_parent))].append(item)
        cells = []
        for row_child in row_category["children"]:
            for col_child in col_category["children"]:
                matched = grouped.get((row_child["id"], col_child["id"]), [])
                stats = self._stats(matched)
                cells.append({"row_id": row_child["id"], "col_id": col_child["id"], "count": len(matched), "sales_amount": stats["sales_amount"], "order_gross_profit": stats["order_gross_profit"]})
        return {"row_parent_id": row_parent, "row_label": row_category["label"], "row_period": periods.get(row_parent, "all"), "col_parent_id": col_parent, "col_label": col_category["label"], "col_period": periods.get(col_parent, "all"), "rows": [{"id": item["id"], "label": item["label"]} for item in row_category["children"]], "columns": [{"id": item["id"], "label": item["label"]} for item in col_category["children"]], "cells": cells}

    def _country_comparison(self, rows, categories):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["country"]].append(row)
        result = []
        for country in sorted(grouped):
            group = grouped[country]
            item = {"country": country, "country_categories": sorted({row["country_category"] for row in group}), **self._kpis(group), "missing_metric_count": sum(not row["_metric_present"] for row in group), "conflict_count": sum(row["conflict"] for row in group)}
            item["coverage"] = {str(category["id"]): round(sum(bool(row["_primary"].get(category["id"])) for row in group) / len(group), 4) if group else 0 for category in categories}
            result.append(item)
        return sorted(result, key=lambda item: item["business_unit_count"], reverse=True)

    def _sort_rows(self, rows, field, direction):
        reverse = direction == "desc"
        if field == "problem_priority":
            return sorted(rows, key=lambda row: (row["conflict"], float(row.get("order_gross_profit") or 0) < 0, "问题产品" in row.get("country_sales_role_label", ""), not row["_metric_present"], float(row.get("sales_amount") or 0)), reverse=True)
        return sorted(rows, key=lambda row: (row.get(field) is not None, row.get(field) if row.get(field) is not None else ""), reverse=reverse)

    def _public_row(self, row):
        public = {key: value for key, value in row.items() if not key.startswith("_")}
        public["label_periods"] = {str(parent): sorted(periods, key=_period_order) for parent, periods in row["_by_parent_period"].items()}
        public["issue_codes"] = [issue for issue in ISSUES if issue not in {"all"} and self._matches_problem(row, issue)]
        labels = {}
        for fact in row["_label_facts"]:
            detail = fact.get("detail") or {}
            parent_id = int(detail.get("label_id") or 0)
            child_id = int(fact.get("label_id") or 0)
            labels[(parent_id, child_id)] = {
                "parent_id": parent_id,
                "parent_label": detail.get("label_name") or str(parent_id),
                "id": child_id,
                "label": detail.get("sub_label_name") or str(child_id),
            }
        public["labels"] = list(labels.values())
        public["label_summary"] = " / ".join(f"{item['parent_label']}：{item['label']}" for item in labels.values())
        return public

    def get_msku_profile(self, **filters: Any) -> dict[str, Any]:
        data_date = str(self.get_meta()["default_data_date"])
        country, country_category, store, msku = (str(filters.get(key) or "") for key in ("country", "country_category", "store", "msku"))
        metric_period = str(filters.get("metric_period") or "30d")
        details = self._shared._cached_details()
        detail_by_id = {int(item["sub_label_id"]): item for item in details if int(item["label_id"]) in COUNTRY_PARENT_SET}
        facts = [fact for fact in self._cached_country_facts(data_date) if str(fact.get("msku") or "") == msku and int(fact.get("label_id") or 0) in detail_by_id]
        selected = [fact for fact in facts if str(fact.get("country") or "未配置国家") == country and str(fact.get("country_category") or "") == country_category and str(fact.get("store") or "") == store]
        if not selected:
            raise ValueError("未找到该国家经营单元的标签画像")
        try:
            metric_scope = self._shared._cached_metrics(data_date, metric_period)
        except Exception as exc:
            metric_scope = {"status": "unavailable", "window": {}, "metrics": {}, "error": str(exc)}
        metrics = metric_scope.get("metrics") or {}

        def tag_rows(source):
            result = []
            for fact in source:
                detail = detail_by_id[int(fact["label_id"])]
                result.append({"parent_id": int(detail["label_id"]), "parent_label": detail.get("label_name") or "", "id": int(fact["label_id"]), "label": detail.get("sub_label_name") or "", "period": str(fact.get("label_period") or ""), "rule": detail.get("tag_rule") or "", "definition": detail.get("business_definition") or "", "owner": detail.get("business_owner") or ""})
            return sorted(result, key=lambda item: (item["parent_id"], _period_order(item["period"]), item["id"]))

        others = []
        other_keys = {
            (str(fact.get("country") or "未配置国家"), str(fact.get("country_category") or ""), str(fact.get("store") or ""), msku)
            for fact in facts
            if (str(fact.get("country") or "未配置国家"), str(fact.get("country_category") or ""), str(fact.get("store") or "")) != (country, country_category, store)
        }
        for other_key in sorted(other_keys):
            other_facts = [fact for fact in facts if (str(fact.get("country") or "未配置国家"), str(fact.get("country_category") or ""), str(fact.get("store") or ""), msku) == other_key]
            other_metric_key = (other_key[1], other_key[2], other_key[3])
            other_metric = metrics.get(other_metric_key) or {}
            others.append({"country": other_key[0], "country_category": other_key[1], "store": other_key[2], "labels": tag_rows(other_facts), "sales_amount": _number(other_metric.get("sales_amount")), "order_gross_profit": _number(other_metric.get("order_gross_profit")), "order_gross_margin": _number(other_metric.get("order_gross_margin"))})
        metric_key = (country_category, store, msku)
        return {"identity": {"data_date": data_date, "country": country, "country_category": country_category, "store": store, "msku": msku}, "tag_profile": {"labels": tag_rows(selected)}, "metric_profile": metrics.get(metric_key) or {}, "cross_country_profile": others, "data_status": {"local_metrics_status": metric_scope.get("status") or "unavailable", "metric_window": metric_scope.get("window") or {}, "has_local_metric": metric_key in metrics}, "navigation_links": {"global_label_hub": f"/label-hub?{urlencode({'metric_period': metric_period, 'country_category': country_category, 'store': store, 'keyword': msku})}"}}


country_label_hub_service = CountryLabelHubDataService()
