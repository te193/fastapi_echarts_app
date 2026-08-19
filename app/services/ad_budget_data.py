from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Lock, Thread
from typing import Any

from .dashboard_db import dashboard_service


ANOMALY_THRESHOLDS = {
    "pace_gap": 0.20,
    "slow_min_month_progress": 0.25,
    "min_peer_size": 30,
    "min_impressions": 100,
    "min_clicks": 20,
    "min_spend": 50.0,
}
ANOMALY_ORDER = (
    "预算配置异常",
    "有花费但无月预算",
    "月预算超支",
    "近7天预算超支",
    "消耗过快",
    "有花费无广告销售",
    "低点击",
    "低转化",
    "高ACOS",
    "预算偏慢",
    "未启动",
)
SORT_FIELDS = {
    "product_name",
    "seller_sku_adj",
    "anomalies",
    "anomaly_priority",
    "budget_gap_amount",
    "site_total_budget_cny",
    "total_budget_pool_cny",
    "monthly_ad_budget_cny",
    "month_spend",
    "monthly_execution_rate",
    "weekly_ad_budget_cny",
    "spend_7d",
    "weekly_execution_rate",
    "ad_impressions",
    "ad_clicks",
    "ctr",
    "ad_orders",
    "ad_cvr",
    "ad_sales",
    "acos",
    "roas",
    "sessions_total",
    "sales_qty",
}
TEXT_SORT_FIELDS = {"product_name", "seller_sku_adj", "anomalies"}
COLUMN_FILTER_FIELDS = {
    "product_name",
    "seller_sku_adj",
    "anomaly_priority",
    "total_budget_pool_cny",
    "monthly_ad_budget_cny",
    "weekly_ad_budget_cny",
    "ad_impressions",
    "ad_orders",
    "tacos",
    "sessions_total",
    "anomalies",
}
SUPPORTED_BUDGET_COUNTRIES = frozenset({"德国", "法国", "意大利", "西班牙", "荷兰", "美国", "英国"})
CACHE_TTL_SECONDS = 600

logger = logging.getLogger(__name__)


def filter_budget_countries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("country") or "") in SUPPORTED_BUDGET_COUNTRIES]


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    return None if value is None else _float(value)


def _round(value: Any, digits: int = 2) -> float:
    return round(_float(value), digits)


def _iso(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value) if value else None


def _column_filter_value(row: dict[str, Any], field: str) -> Any:
    if field == "product_name":
        return " ".join(str(row.get(key) or "") for key in ("product_name", "country_category", "country", "seller_name_new"))
    if field == "seller_sku_adj":
        return " ".join(str(row.get(key) or "") for key in ("seller_sku_adj", "asin"))
    if field == "anomaly_priority":
        return " ".join([str(row.get("label") or ""), str(row.get("excess_level") or ""), *map(str, row.get("anomalies") or [])])
    if field == "anomalies":
        return " ".join(map(str, row.get("anomalies") or []))
    return row.get(field)


def _matches_column_condition(value: Any, model: dict[str, Any]) -> bool:
    conditions = model.get("conditions") or [item for item in (model.get("condition1"), model.get("condition2")) if item]
    if conditions:
        matches = [_matches_column_condition(value, condition) for condition in conditions]
        return all(matches) if str(model.get("operator") or "AND").upper() == "AND" else any(matches)
    if isinstance(model.get("values"), list):
        return str(value or "") in {str(item) for item in model["values"]}
    filter_type = str(model.get("filterType") or "text")
    operation = str(model.get("type") or "contains")
    if operation == "blank":
        return value is None or value == ""
    if operation == "notBlank":
        return value is not None and value != ""
    if filter_type == "number":
        if value is None or value == "":
            return False
        actual = _float(value)
        expected = _float(model.get("filter"))
        if operation == "equals":
            return actual == expected
        if operation == "notEqual":
            return actual != expected
        if operation == "lessThan":
            return actual < expected
        if operation == "lessThanOrEqual":
            return actual <= expected
        if operation == "greaterThan":
            return actual > expected
        if operation == "greaterThanOrEqual":
            return actual >= expected
        if operation == "inRange":
            return expected <= actual <= _float(model.get("filterTo"))
        return True
    actual_text = str(value or "").casefold()
    expected_text = str(model.get("filter") or "").casefold()
    if operation == "equals":
        return actual_text == expected_text
    if operation == "notEqual":
        return actual_text != expected_text
    if operation == "notContains":
        return expected_text not in actual_text
    if operation == "startsWith":
        return actual_text.startswith(expected_text)
    if operation == "endsWith":
        return actual_text.endswith(expected_text)
    return expected_text in actual_text


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def evaluate_budget_cap(row: dict[str, Any]) -> dict[str, Any]:
    weekly = _optional_float(row.get("weekly_ad_budget_cny"))
    monthly = _optional_float(row.get("monthly_ad_budget_cny"))
    site_total = _optional_float(row.get("site_total_budget_cny"))
    if weekly is None or monthly is None or site_total is None:
        return {"status": "incomplete", "label": "数据不完整", "excess_level": "", "excess_amount": 0.0}

    issues: list[str] = []
    excess = 0.0
    if monthly > site_total + 0.01:
        issues.append("月预算超过站点总预算")
        excess += monthly - site_total
    if weekly > monthly + 0.01:
        issues.append("周预算超过月预算")
        excess += weekly - monthly
    if issues:
        return {
            "status": "invalid",
            "label": "预算配置异常",
            "excess_level": "；".join(issues),
            "excess_amount": round(excess, 2),
        }
    return {"status": "valid", "label": "在总预算内", "excess_level": "", "excess_amount": 0.0}


def _derive_metrics(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    has_performance = int(item.get("performance_row_count") or 0) > 0
    clicks = _float(item.get("ad_clicks"))
    impressions = _float(item.get("ad_impressions"))
    orders = _float(item.get("ad_orders"))
    spend = _float(item.get("month_spend"))
    ad_sales = _float(item.get("ad_sales"))
    sales_amount = _float(item.get("sales_amount"))
    has_performance_7d = int(item.get("performance_7d_row_count") or 0) > 0
    clicks_7d = _float(item.get("ad_clicks_7d"))
    impressions_7d = _float(item.get("ad_impressions_7d"))
    orders_7d = _float(item.get("ad_orders_7d"))
    spend_7d = _float(item.get("spend_7d"))
    ad_sales_7d = _float(item.get("ad_sales_7d"))
    sales_amount_7d = _float(item.get("sales_amount_7d"))
    item.update(
        {
            "ctr": round(clicks / impressions, 4) if impressions else (0.0 if has_performance else None),
            "ad_cvr": round(orders / clicks, 4) if clicks else (0.0 if has_performance else None),
            "acos": round(spend / ad_sales, 4) if ad_sales else None,
            "roas": round(ad_sales / spend, 4) if spend else None,
            "tacos": round(spend / sales_amount, 4) if sales_amount else None,
            "ad_sales_share": round(ad_sales / sales_amount, 4) if sales_amount else None,
            "ctr_7d": round(clicks_7d / impressions_7d, 4) if impressions_7d else (0.0 if has_performance_7d else None),
            "ad_cvr_7d": round(orders_7d / clicks_7d, 4) if clicks_7d else (0.0 if has_performance_7d else None),
            "acos_7d": round(spend_7d / ad_sales_7d, 4) if ad_sales_7d else None,
            "roas_7d": round(ad_sales_7d / spend_7d, 4) if spend_7d else None,
            "tacos_7d": round(spend_7d / sales_amount_7d, 4) if sales_amount_7d else None,
            "ad_sales_share_7d": round(ad_sales_7d / sales_amount_7d, 4) if sales_amount_7d else None,
        }
    )
    return item


def apply_anomaly_rules(rows: list[dict[str, Any]], performance_date: date) -> list[dict[str, Any]]:
    prepared = [_derive_metrics(row) for row in rows]
    peers: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        peers[(str(row.get("country") or ""), str(row.get("product_type") or ""))].append(row)

    quartiles: dict[tuple[str, str], dict[str, float | None]] = {}
    for key, group in peers.items():
        if len(group) < ANOMALY_THRESHOLDS["min_peer_size"]:
            continue
        ctr_values = [_float(row.get("ctr")) for row in group if _float(row.get("ad_impressions")) > 0]
        cvr_values = [_float(row.get("ad_cvr")) for row in group if _float(row.get("ad_clicks")) > 0]
        acos_values = [_float(row.get("acos")) for row in group if row.get("acos") is not None]
        quartiles[key] = {
            "ctr_p25": (
                _percentile(ctr_values, 0.25)
                if len(ctr_values) >= ANOMALY_THRESHOLDS["min_peer_size"]
                else None
            ),
            "cvr_p25": (
                _percentile(cvr_values, 0.25)
                if len(cvr_values) >= ANOMALY_THRESHOLDS["min_peer_size"]
                else None
            ),
            "acos_p75": (
                _percentile(acos_values, 0.75)
                if len(acos_values) >= ANOMALY_THRESHOLDS["min_peer_size"]
                else None
            ),
        }

    month_days = (date(performance_date.year + (performance_date.month == 12), performance_date.month % 12 + 1, 1)
                  - date(performance_date.year, performance_date.month, 1)).days
    month_progress = performance_date.day / month_days
    priority_map = {label: index for index, label in enumerate(ANOMALY_ORDER)}
    result: list[dict[str, Any]] = []

    for row in prepared:
        anomalies: list[str] = []
        cap = evaluate_budget_cap(row)
        month_budget = _optional_float(row.get("monthly_ad_budget_cny"))
        week_budget = _optional_float(row.get("weekly_ad_budget_cny"))
        month_spend = _float(row.get("month_spend"))
        spend_7d = _float(row.get("spend_7d"))
        has_performance = int(row.get("performance_row_count") or 0) > 0
        month_rate = month_spend / month_budget if month_budget and month_budget > 0 else None
        week_rate = spend_7d / week_budget if week_budget and week_budget > 0 else None

        if cap["status"] == "invalid":
            anomalies.append("预算配置异常")
        if month_spend > 0 and (month_budget is None or month_budget <= 0):
            anomalies.append("有花费但无月预算")
        if month_budget is not None and month_budget > 0:
            if month_spend > month_budget + 0.01:
                anomalies.append("月预算超支")
            elif month_rate is not None and month_rate - month_progress >= ANOMALY_THRESHOLDS["pace_gap"]:
                anomalies.append("消耗过快")
            elif has_performance and month_spend == 0:
                anomalies.append("未启动")
            elif (
                month_progress >= ANOMALY_THRESHOLDS["slow_min_month_progress"]
                and month_rate is not None
                and month_progress - month_rate >= ANOMALY_THRESHOLDS["pace_gap"]
            ):
                anomalies.append("预算偏慢")
        if week_budget is not None and week_budget > 0 and spend_7d > week_budget + 0.01:
            anomalies.append("近7天预算超支")

        spend = month_spend
        ad_sales = _float(row.get("ad_sales"))
        if spend >= ANOMALY_THRESHOLDS["min_spend"] and ad_sales <= 0:
            anomalies.append("有花费无广告销售")
        peer = quartiles.get((str(row.get("country") or ""), str(row.get("product_type") or "")))
        if peer:
            if (
                _float(row.get("ad_impressions")) >= ANOMALY_THRESHOLDS["min_impressions"]
                and peer["ctr_p25"] is not None
                and _float(row.get("ctr")) <= _float(peer["ctr_p25"])
            ):
                anomalies.append("低点击")
            if (
                _float(row.get("ad_clicks")) >= ANOMALY_THRESHOLDS["min_clicks"]
                and peer["cvr_p25"] is not None
                and _float(row.get("ad_cvr")) <= _float(peer["cvr_p25"])
            ):
                anomalies.append("低转化")
            if (
                spend >= ANOMALY_THRESHOLDS["min_spend"]
                and row.get("acos") is not None
                and peer["acos_p75"] is not None
                and _float(row.get("acos")) >= _float(peer["acos_p75"])
            ):
                anomalies.append("高ACOS")

        item = dict(row)
        item.update(cap)
        item.update(
            {
                "anomalies": anomalies,
                "anomaly_priority": min((priority_map[label] for label in anomalies), default=len(ANOMALY_ORDER)),
                "month_progress": round(month_progress, 4),
                "monthly_execution_rate": round(month_rate, 4) if month_rate is not None else None,
                "weekly_execution_rate": round(week_rate, 4) if week_rate is not None else None,
                "monthly_remaining": round(month_budget - month_spend, 2) if month_budget is not None else None,
                "weekly_remaining": round(week_budget - spend_7d, 2) if week_budget is not None else None,
                "budget_gap_amount": round(
                    max(month_spend - (month_budget or 0), spend_7d - (week_budget or 0), cap["excess_amount"], 0), 2
                ),
            }
        )
        result.append(item)
    return result


def build_overview(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pool_values: dict[tuple[str, str, str], float] = {}
    for row in rows:
        key = (
            str(row.get("country_category") or ""),
            str(row.get("seller_name_new") or ""),
            str(row.get("seller_sku_adj") or ""),
        )
        if row.get("total_budget_pool_cny") is not None:
            pool_values[key] = _float(row.get("total_budget_pool_cny"))
    overview = {
        "market_pool_budget": round(sum(pool_values.values()), 2),
        "site_total_budget": round(sum(_float(row.get("site_total_budget_cny")) for row in rows), 2),
        "monthly_budget": round(sum(_float(row.get("monthly_ad_budget_cny")) for row in rows), 2),
        "month_spend": round(sum(_float(row.get("month_spend")) for row in rows), 2),
        "weekly_budget": round(sum(_float(row.get("weekly_ad_budget_cny")) for row in rows), 2),
        "spend_7d": round(sum(_float(row.get("spend_7d")) for row in rows), 2),
    }
    overview["monthly_execution_rate"] = round(overview["month_spend"] / overview["monthly_budget"], 4) if overview["monthly_budget"] else None
    overview["weekly_execution_rate"] = round(overview["spend_7d"] / overview["weekly_budget"], 4) if overview["weekly_budget"] else None
    return overview


class AdBudgetService:
    def __init__(self) -> None:
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_dates: tuple[date | None, date | None] = (None, None)
        self._cache_at: datetime | None = None
        self._cache_lock = Lock()
        self._refresh_lock = Lock()
        self._refreshing = False
        self._meta_cache: tuple[list[dict[str, Any]], date | None, date | None] | None = None
        self._meta_cache_at: datetime | None = None

    def connect(self):
        return dashboard_service.connect(autocommit=True)

    @staticmethod
    def _performance_start(performance_date: date) -> date:
        return min(date(performance_date.year, performance_date.month, 1), performance_date - timedelta(days=6))

    @staticmethod
    def _detail_trend_start(performance_date: date) -> date:
        return performance_date.replace(day=1)

    def _dates(self, conn) -> tuple[date | None, date | None]:
        with conn.cursor() as cursor:
            try:
                cursor.execute("select max(biz_date) as budget_date from dashboard_ad_budget_snapshot")
                budget_date = (cursor.fetchone() or {}).get("budget_date")
            except Exception:
                budget_date = None
            cursor.execute("select max(dt_date) as performance_date from dashboard_product_performance_daily")
            performance_date = (cursor.fetchone() or {}).get("performance_date")
        return budget_date, performance_date

    def _cached_rows(self) -> tuple[list[dict[str, Any]], date | None, date | None, float] | None:
        with self._cache_lock:
            if self._cache_rows is None or self._cache_at is None:
                return None
            age_seconds = (datetime.now() - self._cache_at).total_seconds()
            return [dict(row) for row in self._cache_rows], *self._cache_dates, age_seconds

    def _background_refresh(self) -> None:
        try:
            self._refresh_rows(force=True)
        except Exception:
            logger.exception("广告预算缓存后台刷新失败，继续使用最后成功快照")
        finally:
            with self._cache_lock:
                self._refreshing = False

    def _schedule_refresh(self) -> None:
        with self._cache_lock:
            if self._refreshing:
                return
            self._refreshing = True
        Thread(target=self._background_refresh, name="ad-budget-cache-refresh", daemon=True).start()

    def warm_cache(self) -> None:
        cached = self._cached_rows()
        if cached is None or cached[3] >= CACHE_TTL_SECONDS:
            self._schedule_refresh()

    def _load_rows(self, force: bool = False) -> tuple[list[dict[str, Any]], date | None, date | None]:
        cached = self._cached_rows()
        if not force and cached is not None:
            rows, budget_date, performance_date, age_seconds = cached
            if age_seconds >= CACHE_TTL_SECONDS:
                self._schedule_refresh()
            return rows, budget_date, performance_date
        return self._refresh_rows(force=force)

    def _refresh_rows(self, force: bool = False) -> tuple[list[dict[str, Any]], date | None, date | None]:
        with self._refresh_lock:
            cached = self._cached_rows()
            if not force and cached is not None and cached[3] < CACHE_TTL_SECONDS:
                return cached[0], cached[1], cached[2]
            return self._query_rows()

    def _query_rows(self) -> tuple[list[dict[str, Any]], date | None, date | None]:
        with self.connect() as conn:
            budget_date, performance_date = self._dates(conn)
            if performance_date is None and budget_date is None:
                rows: list[dict[str, Any]] = []
                with self._cache_lock:
                    self._cache_rows = rows
                    self._cache_dates = (budget_date, performance_date)
                    self._cache_at = datetime.now()
                return rows, budget_date, performance_date
            month_start = date(performance_date.year, performance_date.month, 1) if performance_date else budget_date
            seven_start = performance_date - timedelta(days=6) if performance_date else budget_date
            performance_start = self._performance_start(performance_date) if performance_date else budget_date
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    with budget as (
                        select * from dashboard_ad_budget_snapshot where biz_date = %(budget_date)s
                    ), performance as (
                        select country_category, country, seller_name_new, seller_sku_adj,
                               count(*) as performance_row_count,
                               sum(case when dt_date >= %(seven_start)s then 1 else 0 end) as performance_7d_row_count,
                               sum(case when dt_date >= %(month_start)s then ad_spend else 0 end) as month_spend,
                               sum(case when dt_date >= %(month_start)s then sales_amount else 0 end) as sales_amount,
                               sum(case when dt_date >= %(seven_start)s then ad_spend else 0 end) as spend_7d,
                               sum(case when dt_date >= %(seven_start)s then sales_amount else 0 end) as sales_amount_7d,
                               sum(case when dt_date >= %(month_start)s then ad_orders else 0 end) as ad_orders,
                               sum(case when dt_date >= %(month_start)s then ad_sales else 0 end) as ad_sales,
                               sum(case when dt_date >= %(month_start)s then ad_clicks else 0 end) as ad_clicks,
                               sum(case when dt_date >= %(month_start)s then ad_impressions else 0 end) as ad_impressions,
                               sum(case when dt_date >= %(seven_start)s then ad_orders else 0 end) as ad_orders_7d,
                               sum(case when dt_date >= %(seven_start)s then ad_sales else 0 end) as ad_sales_7d,
                               sum(case when dt_date >= %(seven_start)s then ad_clicks else 0 end) as ad_clicks_7d,
                               sum(case when dt_date >= %(seven_start)s then ad_impressions else 0 end) as ad_impressions_7d,
                               sum(case when dt_date >= %(seven_start)s then sessions_total else 0 end) as sessions_total_7d,
                               sum(case when dt_date >= %(seven_start)s then sales_qty else 0 end) as sales_qty_7d,
                               sum(case when dt_date >= %(month_start)s then sessions_total else 0 end) as sessions_total,
                               sum(case when dt_date >= %(month_start)s then sales_qty else 0 end) as sales_qty
                        from dashboard_product_performance_daily
                        where dt_date between %(performance_start)s and %(performance_date)s
                        group by country_category, country, seller_name_new, seller_sku_adj
                    ), identities as (
                        select country_category, country, seller_name_new, seller_sku_adj from budget
                        union
                        select country_category, country, seller_name_new, seller_sku_adj from performance
                    ), product_info as (
                        select country_category, seller_name_new, seller_sku_adj,
                               max(max_local_name) as product_name, max(max_asin) as asin,
                               max(max_brand_name) as product_brand, max(new_old_product) as replenishment_product_type
                        from dashboard_pur_plan_replenish_data
                        where cur_date = (select max(cur_date) from dashboard_pur_plan_replenish_data)
                        group by country_category, seller_name_new, seller_sku_adj
                    )
                    select i.country_category, i.country, i.seller_name_new, i.seller_sku_adj,
                           coalesce(pi.product_name, '') as product_name, coalesce(pi.asin, '') as asin,
                           coalesce(b.max_brand_name, pi.product_brand, '') as max_brand_name,
                           coalesce(b.product_type, pi.replenishment_product_type, '未分类') as product_type,
                           b.*, p.performance_row_count, p.performance_7d_row_count,
                           p.month_spend, p.sales_amount, p.spend_7d, p.sales_amount_7d,
                           p.ad_orders, p.ad_sales, p.ad_clicks, p.ad_impressions,
                           p.ad_orders_7d, p.ad_sales_7d, p.ad_clicks_7d, p.ad_impressions_7d,
                           p.sessions_total_7d, p.sales_qty_7d, p.sessions_total, p.sales_qty
                    from identities i
                    left join budget b on b.country_category=i.country_category and b.country=i.country
                                      and b.seller_name_new=i.seller_name_new and b.seller_sku_adj=i.seller_sku_adj
                    left join performance p on p.country_category=i.country_category and p.country=i.country
                                           and p.seller_name_new=i.seller_name_new and p.seller_sku_adj=i.seller_sku_adj
                    left join product_info pi on pi.country_category=i.country_category
                                             and pi.seller_name_new=i.seller_name_new and pi.seller_sku_adj=i.seller_sku_adj
                    """,
                    {
                        "budget_date": budget_date,
                        "performance_date": performance_date,
                        "month_start": month_start,
                        "seven_start": seven_start,
                        "performance_start": performance_start,
                    },
                )
                raw_rows = filter_budget_countries(cursor.fetchall())
        rows = apply_anomaly_rules(raw_rows, performance_date or budget_date or date.today())
        with self._cache_lock:
            self._cache_rows = [dict(row) for row in rows]
            self._cache_dates = (budget_date, performance_date)
            self._cache_at = datetime.now()
        return rows, budget_date, performance_date

    def _load_meta_options(self) -> tuple[list[dict[str, Any]], date | None, date | None]:
        with self._cache_lock:
            if self._meta_cache is not None and self._meta_cache_at is not None:
                if (datetime.now() - self._meta_cache_at).total_seconds() < CACHE_TTL_SECONDS:
                    rows, budget_date, performance_date = self._meta_cache
                    return [dict(row) for row in rows], budget_date, performance_date
        with self.connect() as conn:
            budget_date, performance_date = self._dates(conn)
            performance_start = self._performance_start(performance_date) if performance_date else budget_date
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select distinct country_category, country, seller_name_new, product_type
                    from dashboard_ad_budget_snapshot
                    where biz_date = %(budget_date)s
                    union
                    select distinct country_category, country, seller_name_new, null as product_type
                    from dashboard_product_performance_daily
                    where dt_date between %(performance_start)s and %(performance_date)s
                    """,
                    {
                        "budget_date": budget_date,
                        "performance_start": performance_start,
                        "performance_date": performance_date,
                    },
                )
                rows = filter_budget_countries(cursor.fetchall())
        with self._cache_lock:
            self._meta_cache = ([dict(row) for row in rows], budget_date, performance_date)
            self._meta_cache_at = datetime.now()
        return rows, budget_date, performance_date

    def get_meta(self) -> dict[str, Any]:
        rows, budget_date, performance_date = self._load_meta_options()
        lag_days = (performance_date - budget_date).days if budget_date and performance_date else None
        return {
            "budget_date": _iso(budget_date),
            "performance_date": _iso(performance_date),
            "budget_lag_days": lag_days,
            "budget_stale": lag_days is None or lag_days > 1,
            "country_categories": sorted({str(row.get("country_category")) for row in rows if row.get("country_category")}),
            "countries": sorted({str(row.get("country")) for row in rows if row.get("country")}),
            "stores": sorted({str(row.get("seller_name_new")) for row in rows if row.get("seller_name_new")}),
            "product_types": sorted({str(row.get("product_type")) for row in rows if row.get("product_type")}),
            "anomalies": list(ANOMALY_ORDER),
            "thresholds": dict(ANOMALY_THRESHOLDS),
        }

    def _filtered(self, rows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
        result = rows
        for key in ("country_category", "country", "seller_name_new", "product_type"):
            value = str(filters.get(key) or "all")
            if value != "all":
                result = [row for row in result if str(row.get(key) or "") == value]
        inventory_status = str(filters.get("inventory_status") or "all")
        if inventory_status == "monthly_sufficient":
            result = [row for row in result if int(row.get("inventory_sufficient_flag") or 0) == 1]
        elif inventory_status == "monthly_insufficient":
            result = [row for row in result if row.get("biz_date") is not None and int(row.get("inventory_sufficient_flag") or 0) == 0]
        elif inventory_status == "weekly_sufficient":
            result = [row for row in result if int(row.get("weekly_inventory_sufficient_flag") or 0) == 1]
        anomaly = str(filters.get("anomaly") or "all")
        if anomaly != "all":
            result = [row for row in result if anomaly in row.get("anomalies", [])]
        keyword = str(filters.get("keyword") or "").strip().lower()
        if keyword:
            result = [
                row for row in result
                if keyword in " ".join(str(row.get(key) or "") for key in ("seller_sku_adj", "product_name", "asin", "max_brand_name")).lower()
            ]
        return result

    def _column_filtered(self, rows: list[dict[str, Any]], raw_model: Any) -> list[dict[str, Any]]:
        if not raw_model:
            return rows
        try:
            model = raw_model if isinstance(raw_model, dict) else json.loads(str(raw_model))
        except (TypeError, ValueError, json.JSONDecodeError):
            return rows
        if not isinstance(model, dict):
            return rows
        active = {
            field: condition
            for field, condition in model.items()
            if field in COLUMN_FILTER_FIELDS and isinstance(condition, dict)
        }
        if not active:
            return rows
        return [
            row
            for row in rows
            if all(
                _matches_column_condition(_column_filter_value(row, field), condition)
                for field, condition in active.items()
            )
        ]

    def get_payload(self, **filters: Any) -> dict[str, Any]:
        rows, budget_date, performance_date = self._load_rows()
        filtered = self._filtered(rows, **filters)
        filtered = self._column_filtered(filtered, filters.get("column_filters"))
        sort_field = str(filters.get("sort_field") or "anomaly_priority")
        if sort_field not in SORT_FIELDS:
            sort_field = "anomaly_priority"
        reverse = str(filters.get("sort_dir") or "desc") == "desc"
        if sort_field == "anomaly_priority" and "sort_dir" not in filters:
            reverse = False
        if sort_field == "anomaly_priority":
            filtered.sort(
                key=lambda row: (
                    int(row["anomaly_priority"]) if row.get("anomaly_priority") is not None else 99,
                    -_float(row.get("budget_gap_amount")),
                )
            )
        else:
            present = [row for row in filtered if row.get(sort_field) is not None]
            missing = [row for row in filtered if row.get(sort_field) is None]
            if sort_field in TEXT_SORT_FIELDS:
                present.sort(
                    key=lambda row: str(_column_filter_value(row, sort_field) or "").casefold(),
                    reverse=reverse,
                )
            else:
                present.sort(key=lambda row: _float(row.get(sort_field)), reverse=reverse)
            filtered = present + missing
        page = max(1, int(filters.get("page") or 1))
        page_size = min(200, max(20, int(filters.get("page_size") or 50)))
        start = (page - 1) * page_size
        countries = defaultdict(lambda: {"monthly_budget": 0.0, "month_spend": 0.0, "weekly_budget": 0.0, "spend_7d": 0.0})
        for row in filtered:
            group = countries[str(row.get("country") or "未分类")]
            group["monthly_budget"] += _float(row.get("monthly_ad_budget_cny"))
            group["month_spend"] += _float(row.get("month_spend"))
            group["weekly_budget"] += _float(row.get("weekly_ad_budget_cny"))
            group["spend_7d"] += _float(row.get("spend_7d"))
        anomaly_counts = Counter(row["anomalies"][0] for row in filtered if row.get("anomalies"))
        return {
            "budget_date": _iso(budget_date),
            "performance_date": _iso(performance_date),
            "overview": build_overview(filtered),
            "country_comparison": [{"country": name, **{key: round(value, 2) for key, value in metrics.items()}} for name, metrics in countries.items()],
            "anomaly_distribution": [{"name": name, "count": anomaly_counts[name]} for name in ANOMALY_ORDER if anomaly_counts[name]],
            "rows": filtered[start:start + page_size],
            "total": len(filtered),
            "page": page,
            "page_size": page_size,
        }

    def get_detail(self, *, country_category: str, country: str, seller_name_new: str, seller_sku_adj: str) -> dict[str, Any]:
        rows, budget_date, performance_date = self._load_rows()
        matches = self._filtered(
            rows,
            country_category=country_category,
            country=country,
            seller_name_new=seller_name_new,
            product_type="all",
            keyword="",
        )
        row = next((item for item in matches if str(item.get("seller_sku_adj")) == seller_sku_adj), None)
        if row is None:
            raise ValueError("未找到对应的站点产品")
        trend: list[dict[str, Any]] = []
        if performance_date:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        select dt_date,
                               sum(ad_spend) as ad_spend, sum(ad_sales) as ad_sales,
                               sum(ad_orders) as ad_orders, sum(ad_clicks) as ad_clicks,
                               sum(ad_impressions) as ad_impressions,
                               sum(sessions_total) as sessions_total, sum(sales_qty) as sales_qty
                        from dashboard_product_performance_daily
                        where dt_date between %(start_date)s and %(end_date)s
                          and country_category=%(country_category)s and country=%(country)s
                          and seller_name_new=%(seller_name_new)s and seller_sku_adj=%(seller_sku_adj)s
                        group by dt_date order by dt_date
                        """,
                        {
                            "start_date": self._detail_trend_start(performance_date),
                            "end_date": performance_date,
                            "country_category": country_category,
                            "country": country,
                            "seller_name_new": seller_name_new,
                            "seller_sku_adj": seller_sku_adj,
                        },
                    )
                    cumulative_spend = 0.0
                    cumulative_sales = 0.0
                    for item in cursor.fetchall():
                        cumulative_spend += _float(item.get("ad_spend"))
                        cumulative_sales += _float(item.get("ad_sales"))
                        trend.append(
                            {
                                **item,
                                "dt_date": _iso(item.get("dt_date")),
                                "cumulative_ad_spend": round(cumulative_spend, 2),
                                "cumulative_ad_sales": round(cumulative_sales, 2),
                            }
                        )
        return {
            "budget_date": _iso(budget_date),
            "performance_date": _iso(performance_date),
            "identity": {
                "country_category": country_category,
                "country": country,
                "seller_name_new": seller_name_new,
                "seller_sku_adj": seller_sku_adj,
            },
            "row": row,
            "trend": trend,
        }


ad_budget_service = AdBudgetService()
