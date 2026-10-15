"""Ordinary sales roles and export review for replenishment only.

Country metrics contain the object's own sales, never follow/ASIN compensation.
SQL is shared by readers and ETL; independent sales-role modules are untouched.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable, Mapping

ROLE_PERIODS = {7, 14, 30, 90}
REVIEW_COUNTRIES = {
    "欧洲站": ("德国", "法国", "意大利", "西班牙", "荷兰"),
    "英国站": ("英国",),
    "北美站": ("美国",),
}
REVIEW_COLUMNS = (
    {"name": "low_margin_review_note", "label": "低毛利核查说明"},
    {"name": "qualifying_country_metrics", "label": "日均销量＞1件/天且毛利率＞5%的国家"},
)


def normalize_role_period(value: Any) -> int:
    try:
        period = int(value or 30)
    except (ValueError, TypeError):
        period = 30
    return period if period in ROLE_PERIODS else 30


def expression_period(expr: str) -> int:
    match = re.search(r"role_(?:daily_sales|margin_rate)_(\d+)d", expr)
    return normalize_role_period(match[1] if match else 30)


def role_case(daily: str, margin: str) -> str:
    """Unknown evidence remains unclassified; zero sales is a problem role."""
    return f"""case
        when ({daily}) is null then null
        when ({daily}) = 0 then '问题产品'
        when ({margin}) is null then null
        when ({daily}) > 5 and ({margin}) > 0.15 then '明星产品'
        when ({daily}) between 1 and 5 and ({margin}) > 0.25 then '明星产品'
        when ({daily}) > 5 and ({margin}) between 0.05 and 0.15 then '潜力产品'
        when ({daily}) between 1 and 5 and ({margin}) between 0.10 and 0.25 then '潜力产品'
        when ({daily}) between 1 and 5 and ({margin}) >= 0.05 and ({margin}) < 0.10 then '瘦狗产品'
        when ({daily}) > 0 and ({daily}) < 1 and ({margin}) >= 0.05 then '瘦狗产品'
        when ({daily}) > 1 and ({margin}) < 0.05 then '瘦狗产品'
        when ({daily}) > 0 and ({daily}) <= 1 and ({margin}) < 0.05 then '问题产品'
        else null end"""


def role_aggregate_sql(period: Any, date_params: Iterable[str] = (), *, snapshot_dates_sql: str | None = None) -> str:
    period = normalize_role_period(period)
    names = tuple(date_params)
    if any(not re.fullmatch(r"[a-z_]+", name) for name in names):
        raise ValueError("invalid snapshot parameter")
    dates = f"and snapshot_date in ({', '.join('%(' + name + ')s' for name in names)})" if names else ""
    if snapshot_dates_sql:
        dates += f" and snapshot_date in ({snapshot_dates_sql})"
    return f"""select snapshot_date, country_category, seller_name_new, seller_sku_adj,
        sum(sales_qty) / {period}.0 as role_daily_sales_{period}d,
        sum(order_gross_profit) / nullif(sum(sales_amount), 0) as role_margin_rate_{period}d
        from dashboard_replenishment_country_metrics
        where period_days = {period} {dates}
        group by snapshot_date, country_category, seller_name_new, seller_sku_adj"""


def replenishment_source_sql(period: Any, date_params: Iterable[str] = ()) -> str:
    period = normalize_role_period(period)
    return f"""(select role_base.*, role_agg.role_daily_sales_{period}d,
        role_agg.role_margin_rate_{period}d
        from dashboard_pur_plan_replenish_data role_base
        left join ({role_aggregate_sql(period, date_params)}) role_agg
          on role_agg.snapshot_date = role_base.cur_date
         and role_agg.country_category = role_base.country_category
         and role_agg.seller_name_new = role_base.seller_name_new
         and role_agg.seller_sku_adj = role_base.seller_sku_adj)"""


def tracking_summary_source_sql(period: Any) -> str:
    period = normalize_role_period(period)
    category = role_case(f"role_agg.role_daily_sales_{period}d", f"role_agg.role_margin_rate_{period}d")
    dates_sql = "select distinct latest_replenishment_date from dashboard_replenishment_tracking_summary where cutoff_date = %(cutoff_date)s"
    return f"""(select role_base.*, {category} as current_role_category
        from dashboard_replenishment_tracking_summary role_base
        left join ({role_aggregate_sql(period, snapshot_dates_sql=dates_sql)}) role_agg
          on role_agg.snapshot_date = role_base.latest_replenishment_date
         and role_agg.country_category = role_base.country_category
         and role_agg.seller_name_new = role_base.seller_name_new
         and role_agg.seller_sku_adj = role_base.seller_sku_adj
        where role_base.cutoff_date = %(cutoff_date)s)"""


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _day(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, date) else str(value or "")


def country_key(row: Mapping[str, Any], date_column: str) -> tuple[str, Any, Any, Any]:
    return (_day(row.get(date_column)), row.get("country_category"),
            row.get("seller_name_new"), row.get("seller_sku_adj"))


def low_margin_review(row: Mapping[str, Any], countries: Iterable[Mapping[str, Any]], period: Any) -> dict[str, str]:
    result = {"status": "", "low_margin_review_note": "", "qualifying_country_metrics": ""}
    daily, margin = _decimal(row.get("role_daily_sales")), _decimal(row.get("role_margin_rate"))
    if row.get("abcd_category") not in {"瘦狗产品", "问题产品"} or daily is None or margin is None or daily <= 1 or margin >= Decimal("0.05"):
        return result
    period = normalize_role_period(period)
    expected = REVIEW_COUNTRIES.get(str(row.get("country_category")), ())
    if not expected:
        return result
    key = country_key(row, "cur_date")
    records = {item.get("country"): item for item in countries
               if country_key(item, "snapshot_date") == key and item.get("period_days") == period
               and item.get("country") in expected}
    qualifying = []
    for name in expected:
        item = records.get(name, {})
        qty, amount, profit = (_decimal(item.get(field)) for field in ("sales_qty", "sales_amount", "order_gross_profit"))
        if qty is None or amount is None or profit is None or amount <= 0:
            # No evaluable country record is treated as not operated for this
            # export review, per the user's updated business convention.
            continue
        country_daily, country_margin = qty / period, profit / amount
        if country_daily > 1 and country_margin > Decimal("0.05"):
            qualifying.append(f"{name}：日销{country_daily:.2f}件/天，毛利率{country_margin * 100:.2f}%")
    if qualifying:
        result.update(status="qualified", low_margin_review_note="总日均销量＞1件/天且总毛利率＜5%；当前类别有国家站点日均销量＞1件/天且毛利率＞5%",
                      qualifying_country_metrics="；".join(qualifying))
    else:
        result.update(status="none", low_margin_review_note="总日均销量＞1件/天且总毛利率＜5%；当前类别无国家站点同时满足：日均销量＞1件/天且毛利率＞5%")
    return result
