from __future__ import annotations

import math
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import combinations
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode

from etl.dashboard_daily_update import render_sql

from .label_hub_data import (
    CACHE_SECONDS, LABEL_DETAIL_TABLE, LABEL_FACT_TABLE, REFUND_MSKU_PREFIX,
    LabelHubDataService, _number, _period_order, label_hub_service,
)
from .label_hub_local_metrics import METRIC_PERIODS, _sales_trend


COUNTRY_PARENT_IDS = (4, 7, 13, 14)
COUNTRY_PARENT_SET = set(COUNTRY_PARENT_IDS)
# Country detail rows should remain predictable whenever the selected metric has
# the same value (especially the many zero-sales countries).  Keep the main
# European operating sequence first, then the remaining common sites.
COUNTRY_PROFILE_TIE_ORDER = (
    "德国", "法国", "意大利", "西班牙", "荷兰",
    "比利时", "波兰", "瑞典", "爱尔兰", "英国",
    "土耳其", "美国", "墨西哥", "加拿大",
    "日本", "澳大利亚", "阿联酋", "沙特阿拉伯", "巴西",
)
COUNTRY_PROFILE_TIE_PRIORITY = {
    country: index for index, country in enumerate(COUNTRY_PROFILE_TIE_ORDER)
}
# Keep this in one place: the limit-price snapshot can provide every standard
# target gross-margin tier, and the drawer should expose all populated values.
LIMIT_PRICE_MARGIN_TIERS = (35, 30, 25, 20, 15, 10, 5, 0)
COUNTRY_DETAIL_PRICE_FIELDS = (
    "listing_price", "listing_currency", "listing_price_cny",
    "price_snapshot_date", "limit_price_35", "limit_price_10",
    "price_margin_interval",
)
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


def _price_margin_interval(price: dict[str, Any] | None, limit_prices: dict[str, Any] | None) -> str:
    if not price or not price.get("available") or not limit_prices or not limit_prices.get("available"):
        return "--"
    price_value = _number(price.get("value"))
    if price_value is None:
        return "--"
    thresholds = {
        int(item["margin"]): _number(item.get("value"))
        for item in limit_prices.get("margin_prices") or []
        if _number(item.get("margin")) is not None
    }
    if any(thresholds.get(tier) is None for tier in LIMIT_PRICE_MARGIN_TIERS):
        return "--"
    if price_value >= thresholds[35]:
        return "≥35%"
    if price_value < thresholds[0]:
        return "<0%"
    ascending_tiers = tuple(reversed(LIMIT_PRICE_MARGIN_TIERS))
    for lower, upper in zip(ascending_tiers, ascending_tiers[1:]):
        if thresholds[lower] <= price_value < thresholds[upper]:
            return f"{lower}%–{upper}%"
    return "--"


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
        self._profile_facts_cache: dict[tuple[str, str, str, str], tuple[datetime, list[dict[str, Any]]]] = {}
        self._base_rows_cache: OrderedDict[tuple[Any, ...], tuple[datetime, list[dict[str, Any]]]] = OrderedDict()
        self._base_rows_lock = RLock()
        self._listing_price_cache: dict[tuple[str, str], tuple[datetime, str | None, dict[str, dict[str, Any]]]] = {}
        self._limit_price_cache: dict[tuple[str, str, str], tuple[datetime, str | None, dict[str, dict[str, Any]]]] = {}
        self._country_profile_metrics_cache: dict[tuple[str, str, str, str, str], tuple[datetime, dict[str, Any]]] = {}
        self._country_detail_metrics_cache: OrderedDict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = OrderedDict()
        self._country_detail_raw_metrics_cache: OrderedDict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = OrderedDict()
        self._country_detail_prices_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
        self._country_detail_count_cache: OrderedDict[tuple[Any, ...], tuple[datetime, dict[str, int]]] = OrderedDict()
        self._country_detail_metric_provider: Callable[..., dict[str, Any]] = self._country_detail_metrics_with_fallback
        self._country_detail_price_provider: Callable[..., dict[str, Any]] = self._cached_country_detail_prices
        register_callback = getattr(self._shared, "register_source_invalidation_callback", None)
        if callable(register_callback):
            register_callback(self._clear_remote_label_caches)

    def _clear_remote_label_caches(self) -> None:
        self._meta_cache = None
        self._facts_cache.clear()
        self._profile_facts_cache.clear()
        with self._base_rows_lock:
            self._base_rows_cache.clear()
        self._country_detail_count_cache.clear()

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

    def get_country_detail_base_rows(self, **filters: Any) -> dict[str, Any]:
        """Return country/SKU rows with country-level metrics for the shared detail API."""
        meta = self.get_meta()
        data_date = str(filters.get("data_date") or meta.get("default_data_date") or "")
        metric_period = str(filters.get("metric_period") or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 仅支持 7d、14d、30d、90d")

        details = self._shared._cached_details()
        categories = list(meta.get("categories") or [])
        category_by_id = {int(item["id"]): item for item in categories}
        child_detail = {
            int(item["sub_label_id"]): item
            for item in details
            if int(item["label_id"]) in COUNTRY_PARENT_SET
        }
        periods = self._resolve_periods(categories, {}, metric_period)
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for fact in self._cached_country_facts(data_date):
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

        label_rows = {
            key: self._make_row(
                key, label_facts, category_by_id, child_detail, periods,
                {"status": "unavailable", "metrics": {}, "window": {}},
            )
            for key, label_facts in grouped.items()
        }
        self._mark_cross_country_inconsistency(list(label_rows.values()))
        if str(filters.get("detail_view") or "country") == "business_unit" and not filters.get("identifiers"):
            metric_scope = {"status": "labels_only", "window": {}, "rows": []}
        else:
            try:
                metric_scope = self._country_detail_metric_provider(
                    data_date=data_date,
                    metric_period=metric_period,
                    country_category=str(filters.get("country_category") or "all"),
                    store=str(filters.get("store") or "all"),
                    keyword=str(filters.get("keyword") or ""),
                    identifiers=list(filters.get("identifiers") or []),
                )
            except Exception:
                metric_scope = {"status": "unavailable", "window": {}, "rows": []}

        metric_status = str(metric_scope.get("status") or "unavailable")
        metric_rows = list(metric_scope.get("rows") or [])
        result: list[dict[str, Any]] = []
        matched_label_keys: set[tuple[str, str, str, str]] = set()
        for metric in metric_rows:
            key = (
                str(metric.get("country") or "未配置国家"),
                str(metric.get("country_category") or ""),
                str(metric.get("store") or metric.get("seller_name_new") or ""),
                str(metric.get("msku") or metric.get("seller_sku_adj") or ""),
            )
            matched_label_keys.add(key)
            row = dict(label_rows.get(key) or {
                "country": key[0], "country_category": key[1], "store": key[2], "msku": key[3],
                "_primary": {}, "_by_parent_period": {}, "conflict": False,
                "conflict_parent_ids": [], "cross_country_inconsistent": False,
            })
            row.update(metric)
            row["store"] = key[2]
            row["msku"] = key[3]
            row["sku"] = str(metric.get("sku") or metric.get("local_sku") or "")
            row["_metric_present"] = True
            self._finish_country_detail_row(row, child_detail, metric_status)
            result.append(row)

        for key, source in label_rows.items():
            if key in matched_label_keys:
                continue
            row = dict(source)
            row["sku"] = ""
            row["_metric_present"] = False
            self._finish_country_detail_row(row, child_detail, metric_status)
            result.append(row)

        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().casefold()
        result = [
            row for row in result
            if (country_category == "all" or row.get("country_category") == country_category)
            and (store == "all" or row.get("store") == store)
            and (
                not keyword
                or keyword in " ".join(str(row.get(field) or "") for field in ("country", "country_category", "store", "msku", "sku")).casefold()
            )
        ]
        prices: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        if str(filters.get("detail_view") or "country") == "country":
            try:
                price_scope = self._country_detail_price_provider(
                    country_category=country_category,
                    store=store,
                )
                prices = dict(price_scope.get("prices") or {})
            except Exception:
                prices = {}
            for row in result:
                price_key = (
                    str(row.get("country") or ""),
                    str(row.get("country_category") or ""),
                    str(row.get("store") or ""),
                    str(row.get("msku") or ""),
                )
                row.update({field: None for field in COUNTRY_DETAIL_PRICE_FIELDS})
                row.update(prices.get(price_key) or {})
        warnings = [] if metric_status in {"available", "labels_only"} else ["国家经营指标暂不可用，当前仅展示标签明细"]
        return {
            "rows": result,
            "metric_status": metric_status,
            "metric_window": metric_scope.get("window") or {},
            "warnings": warnings,
        }

    def get_country_detail_count(self, **filters: Any) -> dict[str, int]:
        """Count country detail units without materializing all country label rows."""
        data_date = str(filters.get("data_date") or self.get_meta().get("default_data_date") or "")
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip()
        cache_key = (data_date, country_category, store, keyword.casefold())
        now = datetime.now()
        with self._base_rows_lock:
            cached = self._country_detail_count_cache.get(cache_key)
            if cached and (now - cached[0]).total_seconds() < CACHE_SECONDS:
                self._country_detail_count_cache.move_to_end(cache_key)
                return dict(cached[1])

        clauses = [
            "data_date = %(data_date)s",
            "msku not like %(refund_prefix)s",
            f"label_id in (select sub_label_id from {LABEL_DETAIL_TABLE} where label_id in ({','.join(map(str, COUNTRY_PARENT_IDS))}))",
        ]
        params: dict[str, Any] = {"data_date": data_date, "refund_prefix": f"{REFUND_MSKU_PREFIX}%"}
        if country_category != "all":
            clauses.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if store != "all":
            clauses.append("store = %(store)s")
            params["store"] = store
        if keyword:
            clauses.append("(msku like %(keyword)s or store like %(keyword)s)")
            params["keyword"] = f"%{keyword}%"

        with self._shared._source_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as country_unit_count
                from (
                    select country, country_category, store, msku
                    from {LABEL_FACT_TABLE}
                    where {' and '.join(clauses)}
                    group by country, country_category, store, msku
                ) scoped_country_units
                """,
                params,
            )
            count = int((cursor.fetchone() or {}).get("country_unit_count") or 0)
        result = {"country_unit_count": count}
        with self._base_rows_lock:
            self._country_detail_count_cache[cache_key] = (now, result)
            self._country_detail_count_cache.move_to_end(cache_key)
            while len(self._country_detail_count_cache) > 16:
                self._country_detail_count_cache.popitem(last=False)
        return dict(result)

    @staticmethod
    def _finish_country_detail_row(row: dict[str, Any], child_detail: dict[int, dict[str, Any]], metric_status: str) -> None:
        sales = _number(row.get("sales_amount"))
        profit = _number(row.get("order_gross_profit"))
        qty = _number(row.get("sales_qty"))
        inventory_days = int(_number(row.get("inventory_days")) or 0)
        if row.get("daily_sales") is None and row.get("_metric_present"):
            row["daily_sales"] = qty / inventory_days if qty is not None and inventory_days else 0.0
        if row.get("order_gross_margin") is None:
            row["order_gross_margin"] = profit / sales if profit is not None and sales else None
        ad_spend = _number(row.get("ad_spend"))
        ad_sales = _number(row.get("ad_sales"))
        row["acos"] = ad_spend / ad_sales if ad_spend is not None and ad_sales and ad_sales > 0 else None
        row["tacos"] = ad_spend / sales if ad_spend is not None and sales and sales > 0 else None
        daily = _number(row.get("daily_sales"))
        if daily is None:
            row["daily_sales_band_code"], row["daily_sales_band"] = "missing", "暂无经营数据"
        elif daily <= 0:
            row["daily_sales_band_code"], row["daily_sales_band"] = "zero", "日销 0"
        elif daily < 1:
            row["daily_sales_band_code"], row["daily_sales_band"] = "lt1", "日销 <1"
        elif daily <= 5:
            row["daily_sales_band_code"], row["daily_sales_band"] = "1_5", "日销 1–5"
        else:
            row["daily_sales_band_code"], row["daily_sales_band"] = "gt5", "日销 >5"
        margin = _number(row.get("order_gross_margin"))
        if margin is None:
            row["margin_band_code"], row["margin_band"] = "missing", "暂无经营数据"
        elif margin < 0.05:
            row["margin_band_code"], row["margin_band"] = "lt5", "<5%"
        elif margin < 0.10:
            row["margin_band_code"], row["margin_band"] = "5_10", "5%–10%"
        elif margin < 0.15:
            row["margin_band_code"], row["margin_band"] = "10_15", "10%–15%"
        elif margin < 0.25:
            row["margin_band_code"], row["margin_band"] = "15_25", "15%–25%"
        else:
            row["margin_band_code"], row["margin_band"] = "gt25", ">=25%"
        role_label = str(row.get("country_sales_role_label") or "")
        row["sales_role_code"] = next((code for word, code in (("明星", "star"), ("潜力", "potential"), ("孵化", "incubation"), ("问题", "eliminate")) if word in role_label), "missing")
        daily_7d = None
        daily_30d = None
        if row.get("_metric_present"):
            days_7d = int(_number(row.get("inventory_days_7d")) or 0)
            days_30d = int(_number(row.get("inventory_days_30d")) or 0)
            qty_7d = _number(row.get("sales_qty_7d"))
            qty_30d = _number(row.get("sales_qty_30d"))
            daily_7d = qty_7d / days_7d if qty_7d is not None and days_7d else 0.0
            daily_30d = qty_30d / days_30d if qty_30d is not None and days_30d else 0.0
        trend_code, trend_label, trend_ratio = _sales_trend(daily_7d, daily_30d)
        row["sales_trend_code"] = trend_code
        row["sales_trend"] = trend_label
        row["sales_trend_ratio"] = trend_ratio
        primary = row.get("_primary") or {}
        row["_by_parent"] = {
            int(parent): set().union(*periods.values()) if periods else set()
            for parent, periods in (row.get("_by_parent_period") or {}).items()
        }
        row["labels"] = [
            {
                "parent_id": int(parent), "id": int(child),
                "label": str(child_detail.get(int(child), {}).get("sub_label_name") or child),
            }
            for parent, child in primary.items() if child
        ]
        row["data_status"] = (
            "国家经营指标可用" if row.get("_metric_present")
            else ("暂无国家经营数据" if metric_status == "available" else "国家经营指标暂不可用")
        )

    def _cached_country_detail_metrics(self, **filters: Any) -> dict[str, Any]:
        cache_key = (
            str(filters.get("data_date") or ""), str(filters.get("metric_period") or "30d"),
            str(filters.get("country_category") or "all"), str(filters.get("store") or "all"),
            str(filters.get("keyword") or "").casefold(),
            tuple(sorted(str(item).strip().casefold() for item in filters.get("identifiers") or [] if str(item).strip())),
        )
        cached = self._country_detail_metrics_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            self._country_detail_metrics_cache.move_to_end(cache_key)
            return cached[1]
        data_date, metric_period, country_category, store, keyword, identifiers = cache_key
        table = render_sql("etl_datasync_test.dashboard_product_performance_daily", self._shared._dashboard.schemas)
        where = ["dt_date between %(query_start)s and %(period_end)s"]
        params: dict[str, Any] = {"data_date": data_date}
        if country_category != "all":
            where.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if store != "all":
            where.append("seller_name_new = %(store)s")
            params["store"] = store
        if keyword:
            where.append("(lower(seller_sku_adj) like %(keyword)s or lower(local_sku) like %(keyword)s)")
            params["keyword"] = f"%{keyword}%"
        if identifiers:
            names = []
            for index, value in enumerate(identifiers):
                name = f"identifier_{index}"
                names.append(f"%({name})s")
                params[name] = value
            where.append(f"(lower(seller_sku_adj) in ({', '.join(names)}) or lower(local_sku) in ({', '.join(names)}))")
        with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(f"select max(dt_date) as period_end from {table} where dt_date <= %(data_date)s", params)
            period_end = (cursor.fetchone() or {}).get("period_end")
            if not period_end:
                return {"status": "available", "window": {}, "rows": []}
            if isinstance(period_end, datetime):
                period_end = period_end.date()
            period_start = period_end - timedelta(days=int(metric_period[:-1]) - 1)
            trend_7_start = period_end - timedelta(days=6)
            trend_30_start = period_end - timedelta(days=29)
            query_start = min(period_start, trend_30_start)
            params.update({
                "period_start": period_start, "period_end": period_end, "query_start": query_start,
                "trend_7_start": trend_7_start, "trend_30_start": trend_30_start,
            })
            cursor.execute(
                f"""
                select country, country_category, seller_name_new as store,
                       seller_sku_adj as msku, local_sku as sku,
                       count(distinct case when dt_date >= %(period_start)s and afn_fulfillable_quantity > 0 then dt_date end) as inventory_days,
                       count(distinct case when dt_date >= %(trend_7_start)s and afn_fulfillable_quantity > 0 then dt_date end) as inventory_days_7d,
                       count(distinct case when dt_date >= %(trend_30_start)s and afn_fulfillable_quantity > 0 then dt_date end) as inventory_days_30d,
                       sum(case when dt_date >= %(period_start)s then coalesce(sales_qty, 0) else 0 end) as sales_qty,
                       sum(case when dt_date >= %(trend_7_start)s then coalesce(sales_qty, 0) else 0 end) as sales_qty_7d,
                       sum(case when dt_date >= %(trend_30_start)s then coalesce(sales_qty, 0) else 0 end) as sales_qty_30d,
                       sum(case when dt_date >= %(period_start)s then coalesce(sales_amount, 0) else 0 end) as sales_amount,
                       sum(case when dt_date >= %(period_start)s then coalesce(order_gross_profit, 0) else 0 end) as order_gross_profit,
                       sum(case when dt_date >= %(period_start)s then coalesce(ad_spend, 0) else 0 end) as ad_spend,
                       sum(case when dt_date >= %(period_start)s then coalesce(ad_sales, 0) else 0 end) as ad_sales,
                       sum(case when dt_date >= %(period_start)s then coalesce(sessions_total, 0) else 0 end) as sessions_total,
                       sum(case when dt_date >= %(period_start)s then coalesce(ad_clicks, 0) else 0 end) as ad_clicks,
                       sum(case when dt_date >= %(period_start)s then coalesce(return_count, 0) else 0 end) as return_count,
                       sum(case when dt_date >= %(period_start)s then coalesce(return_amount, 0) else 0 end) as return_amount,
                       max(case when dt_date = %(period_end)s then afn_fulfillable_quantity end) as ending_inventory_qty,
                       max(case when dt_date = %(period_end)s and ranking > 0 then ranking end) as ranking
                from {table}
                where {' and '.join(where)}
                group by country, country_category, seller_name_new, seller_sku_adj, local_sku
                """,
                params,
            )
            rows = cursor.fetchall()
        result = {
            "status": "available",
            "window": {
                "period_code": metric_period,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
            "rows": rows,
        }
        self._country_detail_metrics_cache[cache_key] = (datetime.now(), result)
        self._country_detail_metrics_cache.move_to_end(cache_key)
        while len(self._country_detail_metrics_cache) > 8:
            self._country_detail_metrics_cache.popitem(last=False)
        return result

    def _country_detail_metrics_with_fallback(self, **filters: Any) -> dict[str, Any]:
        try:
            return self._cached_country_detail_metrics(**filters)
        except Exception:
            return self._cached_country_detail_raw_metrics(**filters)

    def _cached_country_detail_raw_metrics(self, **filters: Any) -> dict[str, Any]:
        """Fallback to the existing yearly Lingxing product-performance fact table."""
        data_date = str(filters.get("data_date") or "")
        metric_period = str(filters.get("metric_period") or "30d")
        country_category = str(filters.get("country_category") or "all")
        store = str(filters.get("store") or "all")
        keyword = str(filters.get("keyword") or "").strip().casefold()
        identifiers = tuple(sorted(str(item).strip().casefold() for item in filters.get("identifiers") or [] if str(item).strip()))
        cache_key = (data_date, metric_period, country_category, store, keyword, identifiers)
        cached = self._country_detail_raw_metrics_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            self._country_detail_raw_metrics_cache.move_to_end(cache_key)
            return cached[1]
        year = data_date[:4]
        if not year.isdigit():
            raise ValueError("国家经营指标日期无效")
        table = render_sql(
            f"etl_datasync.etl_dispose_lx_statistics_product_performance_{year}",
            self._shared._dashboard.schemas,
        )
        period_end = datetime.strptime(data_date, "%Y-%m-%d").date()
        period_start = period_end - timedelta(days=int(metric_period[:-1]) - 1)
        trend_7_start = period_end - timedelta(days=6)
        trend_30_start = period_end - timedelta(days=29)
        query_start = min(period_start, trend_30_start)
        where = ["start_date between %(query_start)s and %(period_end)s"]
        params: dict[str, Any] = {
            "query_start": query_start, "period_start": period_start, "period_end": period_end,
            "trend_7_start": trend_7_start, "trend_30_start": trend_30_start,
        }
        if country_category != "all":
            where.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if store != "all":
            where.append("seller_name_new = %(store)s")
            params["store"] = store
        if keyword:
            where.append("(lower(seller_sku_adj) like %(keyword)s or lower(local_sku) like %(keyword)s)")
            params["keyword"] = f"%{keyword}%"
        if identifiers:
            names = []
            for index, value in enumerate(identifiers):
                name = f"raw_identifier_{index}"
                names.append(f"%({name})s")
                params[name] = value
            where.append(f"(lower(seller_sku_adj) in ({', '.join(names)}) or lower(local_sku) in ({', '.join(names)}))")
        with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select country, country_category, seller_name_new as store,
                       seller_sku_adj as msku, local_sku as sku,
                       count(distinct case when start_date >= %(period_start)s and afn_fulfillable_quantity > 0 then start_date end) as inventory_days,
                       count(distinct case when start_date >= %(trend_7_start)s and afn_fulfillable_quantity > 0 then start_date end) as inventory_days_7d,
                       count(distinct case when start_date >= %(trend_30_start)s and afn_fulfillable_quantity > 0 then start_date end) as inventory_days_30d,
                       sum(case when start_date >= %(period_start)s then coalesce(volume, 0) else 0 end) as sales_qty,
                       sum(case when start_date >= %(trend_7_start)s then coalesce(volume, 0) else 0 end) as sales_qty_7d,
                       sum(case when start_date >= %(trend_30_start)s then coalesce(volume, 0) else 0 end) as sales_qty_30d,
                       sum(case when start_date >= %(period_start)s then coalesce(amount, 0) else 0 end) as sales_amount,
                       sum(case when start_date >= %(period_start)s then coalesce(gross_profit, 0) else 0 end) as order_gross_profit,
                       sum(case when start_date >= %(period_start)s then coalesce(spend, 0) else 0 end) as ad_spend,
                       sum(case when start_date >= %(period_start)s then coalesce(ad_sales_amount, 0) else 0 end) as ad_sales,
                       sum(case when start_date >= %(period_start)s then coalesce(sessions_total, 0) else 0 end) as sessions_total,
                       sum(case when start_date >= %(period_start)s then coalesce(clicks, 0) else 0 end) as ad_clicks,
                       sum(case when start_date >= %(period_start)s then coalesce(return_count, 0) else 0 end) as return_count,
                       sum(case when start_date >= %(period_start)s then coalesce(return_amount, 0) else 0 end) as return_amount,
                       max(case when start_date = %(period_end)s then afn_fulfillable_quantity end) as ending_inventory_qty,
                       max(case when start_date = %(period_end)s and `rank` > 0 then `rank` end) as ranking
                from {table}
                where {' and '.join(where)}
                group by country, country_category, seller_name_new, seller_sku_adj, local_sku
                """,
                params,
            )
            rows = cursor.fetchall()
        result = {
            "status": "available",
            "window": {"period_code": metric_period, "period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
            "rows": rows,
        }
        self._country_detail_raw_metrics_cache[cache_key] = (datetime.now(), result)
        self._country_detail_raw_metrics_cache.move_to_end(cache_key)
        while len(self._country_detail_raw_metrics_cache) > 8:
            self._country_detail_raw_metrics_cache.popitem(last=False)
        return result

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

    def get_label_hub_country_profile(
        self,
        *,
        country_category: str,
        store: str,
        msku: str,
        metric_period: str = "30d",
    ) -> dict[str, Any]:
        """Return the latest country-level labels and listing prices for one hub row.

        This intentionally uses the country fact cache only after the drawer is opened;
        the standard label-hub payload must not load the much larger country dataset.
        """
        data_date = str(self.get_meta().get("default_data_date") or "")
        details = self._shared._cached_details()
        detail_by_id = {
            int(item["sub_label_id"]): item
            for item in details
            if int(item.get("label_id") or 0) in COUNTRY_PARENT_SET
        }
        categories = {
            int(item["id"]): item
            for item in self.get_meta().get("categories", [])
            if int(item.get("id") or 0) in COUNTRY_PARENT_SET
        }
        facts = [
            fact
            for fact in self._cached_profile_country_facts(data_date, country_category, store, msku)
            if int(fact.get("label_id") or 0) in detail_by_id
        ]
        if not facts:
            raise ValueError("未找到该店铺与国家类别下的国家标签画像")

        metric_period = str(metric_period or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            metric_period = "30d"

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="country-profile") as executor:
            price_future = executor.submit(self._cached_listing_prices, country_category, store, msku)
            limit_price_future = executor.submit(self._cached_limit_prices, country_category, store, msku)
            metric_future = executor.submit(
                self._cached_country_profile_metrics,
                data_date, country_category, store, msku, metric_period,
            )
            try:
                price_date, prices = price_future.result()
                price_status = "available"
            except Exception:
                price_date, prices, price_status = None, {}, "unavailable"
            try:
                limit_price_date, limit_prices = limit_price_future.result()
                limit_price_status = "available"
            except Exception:
                limit_price_date, limit_prices, limit_price_status = None, {}, "unavailable"
            try:
                metric_scope = metric_future.result()
                metric_status = "available"
            except Exception:
                metric_scope = {"window": {}, "metrics": {}, "sku": None}
                metric_status = "unavailable"

        by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            by_country[str(fact.get("country") or "未配置国家")].append(fact)

        countries = []
        complete_label_count = 0
        missing_price_count = 0
        for country in sorted(by_country):
            country_facts = by_country[country]
            labels_by_parent_period: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
            for fact in country_facts:
                detail = detail_by_id[int(fact["label_id"])]
                labels_by_parent_period[int(detail["label_id"])][str(fact.get("label_period") or "")].add(int(fact["label_id"]))

            def primary(parent_id: int, period: str | None = None) -> dict[str, Any] | None:
                candidates = (
                    labels_by_parent_period.get(parent_id, {}).get(str(period), set())
                    if period is not None
                    else set().union(*labels_by_parent_period.get(parent_id, {}).values())
                )
                if not candidates:
                    return None
                priority = (categories.get(parent_id) or {}).get("aggregation_priority_ids") or []
                child_id = next((item for item in priority if item in candidates), min(candidates))
                detail = detail_by_id[child_id]
                return {
                    "id": child_id,
                    "label": detail.get("sub_label_name") or str(child_id),
                    "period": str(period or ""),
                    "rule": detail.get("tag_rule") or "",
                    "definition": detail.get("business_definition") or "",
                    "owner": detail.get("business_owner") or "",
                    "multiple": len(candidates) > 1,
                }

            raw_labels = []
            conflict_parent_ids = []
            for parent_id, periods in labels_by_parent_period.items():
                category = categories.get(parent_id) or {}
                if category.get("mutual_exclusion") and any(len(children) > 1 for children in periods.values()):
                    conflict_parent_ids.append(parent_id)
                for period, child_ids in periods.items():
                    for child_id in sorted(child_ids):
                        detail = detail_by_id[child_id]
                        raw_labels.append({
                            "parent_id": parent_id,
                            "parent_label": detail.get("label_name") or str(parent_id),
                            "id": child_id,
                            "label": detail.get("sub_label_name") or str(child_id),
                            "period": period,
                            "rule": detail.get("tag_rule") or "",
                            "definition": detail.get("business_definition") or "",
                            "owner": detail.get("business_owner") or "",
                        })

            lifecycle = [primary(14, period) for period in sorted(labels_by_parent_period.get(14, {}), key=_period_order)]
            lifecycle = [item for item in lifecycle if item]
            sales_roles = {period: primary(13, period) for period in ("7d", "14d", "30d", "90d")}
            price = prices.get(country)
            limit_price = limit_prices.get(country) or {"available": False}
            country_metric = (metric_scope.get("metrics") or {}).get(country) or {}
            if not price:
                missing_price_count += 1
            required = (4, 7, 13, 14)
            if all(labels_by_parent_period.get(parent_id) for parent_id in required):
                complete_label_count += 1
            countries.append({
                "country": country,
                "price": price or {"available": False},
                "limit_prices": limit_price,
                "price_margin_interval": _price_margin_interval(price, limit_price),
                "metrics": country_metric,
                "pricing": primary(4),
                "site_status": primary(7),
                "site_lifecycle": lifecycle,
                "sales_roles": sales_roles,
                "raw_labels": sorted(raw_labels, key=lambda item: (item["parent_id"], _period_order(item["period"]), item["id"])),
                "conflict_parent_ids": conflict_parent_ids,
                "data_status": "complete" if all(labels_by_parent_period.get(parent_id) for parent_id in required) else "partial_labels",
            })
        countries.sort(
            key=lambda item: (
                -(_number((item.get("metrics") or {}).get("sales_qty")) or 0.0),
                COUNTRY_PROFILE_TIE_PRIORITY.get(str(item.get("country") or ""), len(COUNTRY_PROFILE_TIE_PRIORITY)),
                str(item.get("country") or ""),
            )
        )
        return {
            "identity": {
                "country_category": country_category,
                "store": store,
                "msku": msku,
                "sku": metric_scope.get("sku"),
            },
            "scope": {
                "label_date": data_date,
                "price_snapshot_date": price_date,
                "limit_price_snapshot_date": limit_price_date,
                "metric_period": metric_period,
                "metric_window": metric_scope.get("window") or {},
                "remote_labels_status": "available",
                "listing_price_status": price_status,
                "limit_price_status": limit_price_status,
                "local_metrics_status": metric_status,
            },
            "summary": {
                "country_count": len(countries),
                "complete_label_country_count": complete_label_count,
                "missing_price_country_count": missing_price_count,
            },
            "countries": countries,
        }

    def _cached_country_profile_metrics(
        self,
        data_date: str,
        country_category: str,
        store: str,
        msku: str,
        metric_period: str,
    ) -> dict[str, Any]:
        """Load per-country operating metrics for an already opened country drawer."""
        cache_key = (data_date, country_category, store, msku, metric_period)
        cached = self._country_profile_metrics_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        table = render_sql("etl_datasync_test.dashboard_product_performance_daily", self._shared._dashboard.schemas)
        with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select max(dt_date) as period_end
                from {table}
                where dt_date <= %(data_date)s
                """,
                {"data_date": data_date},
            )
            period_end = (cursor.fetchone() or {}).get("period_end")
            if not period_end:
                result = {"window": {}, "metrics": {}, "sku": None}
                self._country_profile_metrics_cache[cache_key] = (datetime.now(), result)
                return result
            if isinstance(period_end, datetime):
                period_end = period_end.date()
            period_start = period_end - timedelta(days=int(metric_period[:-1]) - 1)
            cursor.execute(
                f"""
                select country,
                       max(local_sku) as sku,
                       count(distinct case when afn_fulfillable_quantity > 0 then dt_date end) as inventory_days,
                       sum(coalesce(sales_qty, 0)) as sales_qty,
                       sum(coalesce(sales_amount, 0)) as sales_amount,
                       sum(coalesce(order_gross_profit, 0)) as order_gross_profit,
                       sum(coalesce(ad_spend, 0)) as ad_spend,
                       sum(coalesce(ad_sales, 0)) as ad_sales,
                       sum(coalesce(sessions_total, 0)) as sessions_total,
                       sum(coalesce(ad_clicks, 0)) as ad_clicks,
                       sum(coalesce(return_count, 0)) as return_count,
                       sum(coalesce(return_amount, 0)) as return_amount,
                       max(case when dt_date = %(period_end)s then afn_fulfillable_quantity end) as ending_inventory_qty,
                       max(case when dt_date = %(period_end)s and ranking > 0 then ranking end) as small_category_ranking
                from {table}
                where dt_date between %(period_start)s and %(period_end)s
                  and country_category = %(country_category)s
                  and seller_name_new = %(store)s
                  and seller_sku_adj = %(msku)s
                group by country
                """,
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "country_category": country_category,
                    "store": store,
                    "msku": msku,
                },
            )
            rows = cursor.fetchall()
        metrics = {}
        for row in rows:
            sales_amount = _number(row.get("sales_amount")) or 0.0
            profit = _number(row.get("order_gross_profit")) or 0.0
            inventory_days = int(_number(row.get("inventory_days")) or 0)
            sales_qty = _number(row.get("sales_qty")) or 0.0
            metrics[str(row.get("country") or "")] = {
                "sales_qty": sales_qty,
                "sales_amount": sales_amount,
                "order_gross_profit": profit,
                "order_gross_margin": profit / sales_amount if sales_amount else None,
                "inventory_days": inventory_days,
                "daily_sales": sales_qty / inventory_days if inventory_days else 0.0,
                "ad_spend": _number(row.get("ad_spend")),
                "ad_sales": _number(row.get("ad_sales")),
                "sessions_total": _number(row.get("sessions_total")),
                "ad_clicks": _number(row.get("ad_clicks")),
                "return_count": _number(row.get("return_count")),
                "return_amount": _number(row.get("return_amount")),
                "ending_inventory_qty": _number(row.get("ending_inventory_qty")),
                "small_category_ranking": _number(row.get("small_category_ranking")),
            }
        end_text = period_end.isoformat() if hasattr(period_end, "isoformat") else str(period_end)
        start_text = period_start.isoformat() if hasattr(period_start, "isoformat") else str(period_start)
        sku = max((str(row.get("sku") or "") for row in rows), default="") or None
        result = {
            "window": {"period_code": metric_period, "period_start": start_text, "period_end": end_text},
            "metrics": metrics,
            "sku": sku,
        }
        self._country_profile_metrics_cache[cache_key] = (datetime.now(), result)
        return result

    def _cached_listing_prices(self, country_category: str, store: str, msku: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
        cache_key = (country_category, store, msku)
        cached = self._listing_price_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1], cached[2]
        table = render_sql("etl_datasync_test.dashboard_listing_price_daily_snapshot", self._shared._dashboard.schemas)
        with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(f"select max(snapshot_date) as snapshot_date from {table}")
            snapshot_row = cursor.fetchone() or {}
            snapshot_date = snapshot_row.get("snapshot_date")
            snapshot_text = snapshot_date.isoformat() if hasattr(snapshot_date, "isoformat") else str(snapshot_date or "")
            if not snapshot_text:
                self._listing_price_cache[cache_key] = (datetime.now(), None, {})
                return None, {}
            cursor.execute(
                f"""
                select country_category, seller_name_new, country, seller_sku,
                       price, org_currency_icon, price_cny
                from {table}
                where snapshot_date = %(snapshot_date)s
                  and country_category = %(country_category)s
                  and seller_name_new = %(store)s
                  and seller_sku = %(msku)s
                """,
                {
                    "snapshot_date": snapshot_date,
                    "country_category": country_category,
                    "store": store,
                    "msku": msku,
                },
            )
            rows = cursor.fetchall()
        prices = {
            str(row.get("country") or ""): {
                "value": _number(row.get("price")),
                "currency": str(row.get("org_currency_icon") or ""),
                "value_cny": _number(row.get("price_cny")),
                "available": True,
            }
            for row in rows
        }
        self._listing_price_cache[cache_key] = (datetime.now(), snapshot_text, prices)
        return snapshot_text, prices

    def _cached_limit_prices(self, country_category: str, store: str, msku: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
        """Load the latest per-country gross-margin price thresholds on drawer demand."""
        cache_key = (country_category, store, msku)
        cached = self._limit_price_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1], cached[2]
        table = render_sql("etl_datasync_test.dashboard_limit_price_daily_snapshot", self._shared._dashboard.schemas)
        with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(f"select max(snapshot_date) as snapshot_date from {table}")
            snapshot_date = (cursor.fetchone() or {}).get("snapshot_date")
            snapshot_text = snapshot_date.isoformat() if hasattr(snapshot_date, "isoformat") else str(snapshot_date or "")
            if not snapshot_text:
                self._limit_price_cache[cache_key] = (datetime.now(), None, {})
                return None, {}
            cursor.execute(
                f"""
                select country, currency, {", ".join(f"margin_price_{tier}" for tier in LIMIT_PRICE_MARGIN_TIERS)}
                from {table}
                where snapshot_date = %(snapshot_date)s
                  and country_category = %(country_category)s
                  and seller_name_new = %(store)s
                  and seller_sku = %(msku)s
                """,
                {
                    "snapshot_date": snapshot_date,
                    "country_category": country_category,
                    "store": store,
                    "msku": msku,
                },
            )
            rows = cursor.fetchall()
        prices = {}
        for row in rows:
            values = [
                {"margin": tier, "value": _number(row.get(f"margin_price_{tier}"))}
                for tier in LIMIT_PRICE_MARGIN_TIERS
                if _number(row.get(f"margin_price_{tier}")) is not None
            ]
            prices[str(row.get("country") or "")] = {
                **{f"margin_price_{tier}": _number(row.get(f"margin_price_{tier}")) for tier in LIMIT_PRICE_MARGIN_TIERS},
                "margin_prices": values,
                "currency": str(row.get("currency") or ""),
                "available": True,
            }
        self._limit_price_cache[cache_key] = (datetime.now(), snapshot_text, prices)
        return snapshot_text, prices

    def _cached_country_detail_prices(self, *, country_category: str, store: str) -> dict[str, Any]:
        """Load current listing and margin prices once for a country-detail request scope."""
        cache_key = (country_category, store)
        cached = self._country_detail_prices_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]

        listing_date: str | None = None
        listing_rows: list[dict[str, Any]] = []
        try:
            listing_table = render_sql(
                "etl_datasync.dashboard_listing_price_daily_snapshot",
                self._shared._dashboard.schemas,
            )
            listing_where = ["snapshot_date = %(snapshot_date)s"]
            listing_params: dict[str, Any] = {}
            if country_category != "all":
                listing_where.append("country_category = %(country_category)s")
                listing_params["country_category"] = country_category
            if store != "all":
                listing_where.append("seller_name_new = %(store)s")
                listing_params["store"] = store
            with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
                cursor.execute(f"select max(snapshot_date) as snapshot_date from {listing_table}")
                snapshot_date = (cursor.fetchone() or {}).get("snapshot_date")
                if snapshot_date:
                    listing_date = snapshot_date.isoformat() if hasattr(snapshot_date, "isoformat") else str(snapshot_date)
                    listing_params["snapshot_date"] = snapshot_date
                    cursor.execute(
                        f"""
                        select country, country_category, seller_name_new, seller_sku,
                               price, org_currency_icon, price_cny
                        from {listing_table}
                        where {' and '.join(listing_where)}
                        """,
                        listing_params,
                    )
                    listing_rows = list(cursor.fetchall())
        except Exception:
            listing_date, listing_rows = None, []

        limit_rows: list[dict[str, Any]] = []
        try:
            limit_table = render_sql(
                "etl_datasync.dashboard_limit_price_daily_snapshot",
                self._shared._dashboard.schemas,
            )
            limit_where = ["snapshot_date = %(snapshot_date)s"]
            limit_params: dict[str, Any] = {}
            if country_category != "all":
                limit_where.append("country_category = %(country_category)s")
                limit_params["country_category"] = country_category
            if store != "all":
                limit_where.append("seller_name_new = %(store)s")
                limit_params["store"] = store
            with self._shared._dashboard.connect() as conn, conn.cursor() as cursor:
                cursor.execute(f"select max(snapshot_date) as snapshot_date from {limit_table}")
                snapshot_date = (cursor.fetchone() or {}).get("snapshot_date")
                if snapshot_date:
                    limit_params["snapshot_date"] = snapshot_date
                    cursor.execute(
                        f"""
                        select country, country_category, seller_name_new, seller_sku, currency,
                               {", ".join(f"margin_price_{tier}" for tier in LIMIT_PRICE_MARGIN_TIERS)}
                        from {limit_table}
                        where {' and '.join(limit_where)}
                        """,
                        limit_params,
                    )
                    limit_rows = list(cursor.fetchall())
        except Exception:
            limit_rows = []

        def row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
            return (
                str(row.get("country") or ""),
                str(row.get("country_category") or ""),
                str(row.get("seller_name_new") or ""),
                str(row.get("seller_sku") or ""),
            )

        listing_by_key = {row_key(row): row for row in listing_rows}
        limit_by_key = {row_key(row): row for row in limit_rows}
        prices: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for key in listing_by_key.keys() | limit_by_key.keys():
            listing = listing_by_key.get(key) or {}
            limit = limit_by_key.get(key) or {}
            listing_price = _number(listing.get("price"))
            price_payload = {"value": listing_price, "available": listing_price is not None}
            limit_payload = {
                "available": bool(limit),
                "margin_prices": [
                    {"margin": tier, "value": _number(limit.get(f"margin_price_{tier}"))}
                    for tier in LIMIT_PRICE_MARGIN_TIERS
                    if _number(limit.get(f"margin_price_{tier}")) is not None
                ],
            }
            interval = _price_margin_interval(price_payload, limit_payload)
            prices[key] = {
                "listing_price": listing_price,
                "listing_currency": str(listing.get("org_currency_icon") or limit.get("currency") or "") or None,
                "listing_price_cny": _number(listing.get("price_cny")),
                "price_snapshot_date": listing_date if listing else None,
                "limit_price_35": _number(limit.get("margin_price_35")),
                "limit_price_10": _number(limit.get("margin_price_10")),
                "price_margin_interval": None if interval == "--" else interval,
            }
        result = {"prices": prices}
        self._country_detail_prices_cache[cache_key] = (datetime.now(), result)
        return result

    def _cached_profile_country_facts(self, data_date: str, country_category: str, store: str, msku: str) -> list[dict[str, Any]]:
        cache_key = (data_date, country_category, store, msku)
        cached = self._profile_facts_cache.get(cache_key)
        if cached and (datetime.now() - cached[0]).total_seconds() < CACHE_SECONDS:
            return cached[1]
        country_cache = self._facts_cache.get(data_date)
        if country_cache and (datetime.now() - country_cache[0]).total_seconds() < CACHE_SECONDS:
            facts = [
                fact
                for fact in country_cache[1]
                if str(fact.get("country_category") or "") == country_category
                and str(fact.get("store") or "") == store
                and str(fact.get("msku") or "") == msku
            ]
        else:
            fetcher = getattr(self._shared, "_fetch_facts", None)
            facts = (
                fetcher(data_date, country_category=country_category, store=store, keyword=msku, parent_ids=COUNTRY_PARENT_IDS)
                if callable(fetcher)
                else [
                    fact
                    for fact in self._cached_country_facts(data_date)
                    if str(fact.get("country_category") or "") == country_category
                    and str(fact.get("store") or "") == store
                    and str(fact.get("msku") or "") == msku
                ]
            )
        facts = [fact for fact in facts if str(fact.get("msku") or "") == msku]
        self._profile_facts_cache[cache_key] = (datetime.now(), facts)
        return facts


country_label_hub_service = CountryLabelHubDataService()
