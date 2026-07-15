from __future__ import annotations

from datetime import date, datetime
from typing import Any

from etl.dashboard_daily_update import render_sql

from .dashboard_db import (
    SALES_ROLE_PERIOD_TABLE,
    SALES_ROLE_SNAPSHOT_CODE_MAP,
    dashboard_service,
)


METRIC_PERIODS = {"7d", "14d", "30d", "90d"}
ROLE_LABELS = {
    "star": "明星产品",
    "potential": "潜力产品",
    "incubation": "瘦狗产品",
    "eliminate": "问题产品",
}


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _daily_band(value: Any) -> tuple[str, str]:
    number = float(value or 0)
    if number <= 0:
        return "zero", "日销 0"
    if number < 1:
        return "lt1", "日销 <1"
    if number <= 5:
        return "1_5", "日销 1–5"
    return "gt5", "日销 >5"


def _margin_band(value: Any) -> tuple[str, str]:
    number = float(value or 0)
    if number < 0.05:
        return "lt5", "<5%"
    if number < 0.10:
        return "5_10", "5%–10%"
    if number < 0.15:
        return "10_15", "10%–15%"
    if number < 0.25:
        return "15_25", "15%–25%"
    return "gt25", ">25%"


def _sales_trend(daily_7d: Any, daily_30d: Any) -> tuple[str, str, float | None]:
    """Classify recent sales velocity using same-end-date 7d and 30d daily sales."""
    if daily_7d is None or daily_30d is None:
        return "insufficient", "暂无趋势数据", None
    recent = max(0.0, float(daily_7d))
    baseline = max(0.0, float(daily_30d))
    if recent == 0 and baseline == 0:
        return "no_sales", "持续无销", 0.0
    if recent == 0 and baseline > 0:
        return "stopped", "近期停销", -1.0
    if baseline == 0:
        return "recent_start", "近期启动", None
    ratio = round((recent - baseline) / baseline, 4)
    if ratio >= 0.30:
        return "accelerating", "明显增长", ratio
    if ratio >= 0.10:
        return "growing", "小幅增长", ratio
    if ratio > -0.10:
        return "stable", "基本稳定", ratio
    if ratio > -0.30:
        return "slowing", "动销放缓", ratio
    return "declining", "明显下滑", ratio


class LabelHubLocalMetricsService:
    """Read the complete local period snapshot used by the label dashboard."""

    def __init__(self, dashboard=dashboard_service) -> None:
        self._dashboard = dashboard

    def _table(self) -> str:
        schemas = getattr(self._dashboard, "schemas", None)
        return render_sql(SALES_ROLE_PERIOD_TABLE, schemas) if schemas is not None else SALES_ROLE_PERIOD_TABLE

    def fetch(
        self,
        data_date: str,
        metric_period: str = "30d",
        country_category: str = "all",
        store: str = "all",
        keyword: str = "",
    ) -> dict[str, Any]:
        metric_period = str(metric_period or "30d").lower()
        if metric_period not in METRIC_PERIODS:
            raise ValueError("metric_period 仅支持 7d、14d、30d、90d")

        table = self._table()
        with self._dashboard.connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                f"""
                select snapshot_date, period_code, period_days, period_start, period_end
                from {table}
                where period_code = %(metric_period)s
                  and period_end <= %(data_date)s
                order by period_end desc, snapshot_date desc
                limit 1
                """,
                {"metric_period": metric_period, "data_date": data_date},
            )
            window = cursor.fetchone()
            if not window:
                return {"status": "no_snapshot", "window": {}, "metrics": {}}

            clauses = [
                "snapshot_date = %(snapshot_date)s",
                "period_code = %(period_code)s",
                "period_start = %(period_start)s",
                "period_end = %(period_end)s",
            ]
            params = {
                "snapshot_date": window["snapshot_date"],
                "period_code": window["period_code"],
                "period_start": window["period_start"],
                "period_end": window["period_end"],
            }
            if country_category != "all":
                clauses.append("country_category = %(country_category)s")
                params["country_category"] = country_category
            if store != "all":
                clauses.append("seller_name_new = %(store)s")
                params["store"] = store
            if str(keyword or "").strip():
                clauses.append("(seller_sku_adj like %(keyword)s or seller_name_new like %(keyword)s)")
                params["keyword"] = f"%{str(keyword).strip()}%"

            cursor.execute(
                f"""
                select country_category, seller_name_new, seller_sku_adj, local_sku_sample,
                       country_count, countries, period_seen_days, sales_days, inventory_days,
                       sales_qty, daily_sales, sales_amount, sales_amount_ex_tax,
                       order_gross_profit, order_gross_margin,
                       settlement_gross_profit, settlement_gross_margin,
                       ending_inventory_qty, max_inventory_qty, avg_inventory_qty,
                       ad_spend, ad_sales, ad_orders, ad_clicks, ad_impressions,
                       acos, tacos, sessions_total, return_count, return_amount, net_amount,
                       sales_role_code, sales_role_label
                from {table}
                where {' and '.join(clauses)}
                """,
                params,
            )
            rows = cursor.fetchall()

            trend_clauses = [
                "snapshot_date = %(snapshot_date)s",
                "period_end = %(period_end)s",
                "period_code in ('7d', '30d')",
            ]
            trend_params = {
                "snapshot_date": window["snapshot_date"],
                "period_end": window["period_end"],
            }
            if country_category != "all":
                trend_clauses.append("country_category = %(country_category)s")
                trend_params["country_category"] = country_category
            if store != "all":
                trend_clauses.append("seller_name_new = %(store)s")
                trend_params["store"] = store
            if str(keyword or "").strip():
                trend_clauses.append("(seller_sku_adj like %(keyword)s or seller_name_new like %(keyword)s)")
                trend_params["keyword"] = f"%{str(keyword).strip()}%"
            cursor.execute(
                f"""
                select country_category, seller_name_new, seller_sku_adj,
                       period_code, daily_sales
                from {table}
                where {' and '.join(trend_clauses)}
                """,
                trend_params,
            )
            trend_rows = cursor.fetchall()

        trend_values: dict[tuple[str, str, str], dict[str, Any]] = {}
        for trend_row in trend_rows:
            trend_key = (
                str(trend_row.get("country_category") or ""),
                str(trend_row.get("seller_name_new") or ""),
                str(trend_row.get("seller_sku_adj") or ""),
            )
            trend_values.setdefault(trend_key, {})[str(trend_row.get("period_code") or "")] = trend_row.get("daily_sales")

        metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
        for source in rows:
            raw_role = str(source.get("sales_role_code") or "")
            role_code = SALES_ROLE_SNAPSHOT_CODE_MAP.get(raw_role, raw_role)
            if role_code not in ROLE_LABELS:
                role_code = "eliminate"
            daily_code, daily_label = _daily_band(source.get("daily_sales"))
            margin_code, margin_label = _margin_band(source.get("order_gross_margin"))
            key = (
                str(source.get("country_category") or ""),
                str(source.get("seller_name_new") or ""),
                str(source.get("seller_sku_adj") or ""),
            )
            trend_code, trend_label, trend_ratio = _sales_trend(
                trend_values.get(key, {}).get("7d"),
                trend_values.get(key, {}).get("30d"),
            )
            row = dict(source)
            row.update(
                {
                    "sales_role_code": role_code,
                    "sales_role": source.get("sales_role_label") or ROLE_LABELS[role_code],
                    "daily_sales_band_code": daily_code,
                    "daily_sales_band": daily_label,
                    "margin_band_code": margin_code,
                    "margin_band": margin_label,
                    "sales_trend_code": trend_code,
                    "sales_trend": trend_label,
                    "sales_trend_ratio": trend_ratio,
                    "daily_sales_7d": _float_or_none(trend_values.get(key, {}).get("7d")),
                    "daily_sales_30d": _float_or_none(trend_values.get(key, {}).get("30d")),
                    "negative_profit": float(source.get("order_gross_profit") or 0) < 0,
                }
            )
            for field in (
                "sales_qty", "daily_sales", "sales_amount", "sales_amount_ex_tax",
                "order_gross_profit", "order_gross_margin", "settlement_gross_profit",
                "settlement_gross_margin", "ending_inventory_qty", "max_inventory_qty",
                "avg_inventory_qty", "ad_spend", "ad_sales", "ad_orders", "ad_clicks",
                "ad_impressions", "acos", "tacos", "sessions_total", "return_count",
                "return_amount", "net_amount",
            ):
                row[field] = _float_or_none(source.get(field))
            metrics[key] = row

        window_payload = {key: _date_text(value) if "date" in key or key.endswith("start") or key.endswith("end") else value for key, value in window.items()}
        lag_days = 0
        try:
            lag_days = (date.fromisoformat(data_date) - date.fromisoformat(window_payload["period_end"])).days
        except (TypeError, ValueError, KeyError):
            pass
        window_payload["lag_days"] = max(0, lag_days)
        return {"status": "available", "window": window_payload, "metrics": metrics}


label_hub_local_metrics_service = LabelHubLocalMetricsService()
