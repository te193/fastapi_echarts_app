from __future__ import annotations

import base64
import hashlib
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pymysql

from etl.dashboard_daily_update import (
    DELETE_PERIOD_SNAPSHOT_SQL,
    INSERT_PERIOD_SNAPSHOT_SQL,
    PERIOD_PRESET_TABLES,
    SchemaConfig,
    period_delete_sql,
    period_insert_sql,
    render_sql,
)


DAILY_SALES_BANDS = ["日销 0", "日销 <1", "日销 1-5", "日销 >5"]
MARGIN_BANDS = ["毛利率 >35%", "毛利率 25-35%", "毛利率 15-25%", "毛利率 10-15%", "毛利率 0-10%", "毛利率 <0%"]
UNKNOWN_TEXT = "未维护"
SALES_GOAL = 135000000
SALES_GOAL_BUFFER = 1.01
MARGIN_GOAL = 0.20
DEFAULT_DASHBOARD_DAYS = int(os.getenv("DASHBOARD_DEFAULT_PERIOD_DAYS", "90"))
MATRIX_ALL_VALUE = "__ALL__"
MATRIX_PERIOD_TABLE = "etl_datasync.dashboard_product_matrix_period_snapshot"


@dataclass(frozen=True)
class PeriodWindow:
    start_date: date
    end_date: date
    snapshot_date: date
    period_table: str = "etl_datasync.dashboard_product_period_snapshot"
    period_code: str = "custom"

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_day(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_int(value: Any) -> int:
    return int(round(to_float(value)))


def format_percent(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def compact_currency(value: float) -> str:
    amount = to_float(value)
    absolute = abs(amount)
    if absolute >= 100000000:
        return f"¥{amount / 100000000:.2f}亿"
    if absolute >= 10000:
        return f"¥{amount / 10000:.2f}万"
    return f"¥{amount:,.0f}"


def days_in_year(current: date) -> int:
    return (date(current.year + 1, 1, 1) - date(current.year, 1, 1)).days


def day_of_year(current: date) -> int:
    return (current - date(current.year, 1, 1)).days + 1


def days_in_month(current: date) -> int:
    if current.month == 12:
        return 31
    return (date(current.year, current.month + 1, 1) - date(current.year, current.month, 1)).days


def iter_days(start: date, end: date) -> list[date]:
    count = (end - start).days + 1
    return [start + timedelta(days=index) for index in range(max(count, 0))]


def encode_item_id(snapshot_date: date, period_start: date, period_end: date, item_key: str) -> str:
    raw = "\x1f".join([format_day(snapshot_date), format_day(period_start), format_day(period_end), item_key])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_item_id(value: str) -> tuple[date, date, date, str] | None:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        snapshot_raw, start_raw, end_raw, item_key = raw.split("\x1f", 3)
        snapshot_date = parse_day(snapshot_raw)
        period_start = parse_day(start_raw)
        period_end = parse_day(end_raw)
        if not snapshot_date or not period_start or not period_end:
            return None
        return snapshot_date, period_start, period_end, item_key
    except Exception:
        return None


class DashboardDbService:
    def __init__(self) -> None:
        self.host = os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1"))
        self.port = int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306")))
        self.user = os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", ""))
        self.password = os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
        self.database = os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test"))
        self.charset = os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4")
        self.schemas = SchemaConfig(
            target_schema=os.getenv("DASHBOARD_TARGET_SCHEMA", self.database),
            etl_source_schema=self.database,
            dwd_source_schema=self.database,
            pricing_source_schema=self.database,
        )
        self._meta_cache: dict[str, Any] | None = None
        self._meta_cache_at: datetime | None = None

    def connect(self, autocommit: bool = False):
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset=self.charset,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=autocommit,
        )

    def get_meta(self) -> dict[str, Any]:
        if self._meta_cache and self._meta_cache_at:
            if (datetime.now() - self._meta_cache_at).total_seconds() < 300:
                return dict(self._meta_cache)

        with self.connect(autocommit=True) as conn:
            bounds = self._get_daily_bounds(conn)
            snapshot_date = self._get_latest_snapshot_date(conn)
            sites = self._fetch_distinct(conn, "country")
            stores = self._fetch_distinct(conn, "seller_name_new")

        start_date, end_date = self._default_range(bounds)
        payload = {
            "default_start_date": format_day(start_date),
            "default_end_date": format_day(end_date),
            "history_days": (end_date - start_date).days + 1,
            "latest_snapshot_date": format_day(snapshot_date),
            "daily_sales_bands": DAILY_SALES_BANDS,
            "margin_bands": MARGIN_BANDS,
            "sites": sites,
            "stores": stores,
            "data_source": "local_mysql",
        }
        self._meta_cache = payload
        self._meta_cache_at = datetime.now()
        return dict(payload)

    def get_dashboard_payload(self, filters: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            self._ensure_period_snapshot(conn, window)
            stats = self._fetch_dashboard_stats(conn, window, filters)
            daily_sales_chart = self._fetch_band_counts(conn, window, filters, "daily_sales_band", DAILY_SALES_BANDS)
            margin_chart = self._fetch_band_counts(conn, window, filters, "margin_band", MARGIN_BANDS)
            matrix = self._fetch_matrix_counts(conn, window, filters)
            series = self._fetch_kpi_series(conn, window, filters)
            annual_goal = self._fetch_latest_annual_goal(conn)
            goal_gap = self._fetch_goal_gap_breakdown(conn, annual_goal)

        return {
            "meta": self.get_meta(),
            "goal_overview": self._build_goal_overview_from_annual(annual_goal)
            if annual_goal
            else self._build_goal_overview_from_stats(stats),
            "summary_hint": self._build_summary_from_stats(stats, matrix),
            "kpis": self._build_kpis_from_stats(stats, series),
            "daily_sales_chart": daily_sales_chart,
            "margin_chart": margin_chart,
            "matrix": matrix,
            "goal_gap_breakdown": goal_gap,
        }

    def get_monthly_goals_payload(self) -> dict[str, Any]:
        metrics = [
            {"key": "sales", "label": "销售额", "type": "currency"},
            {"key": "volume", "label": "销量", "type": "number"},
            {"key": "profit", "label": "毛利润", "type": "currency"},
            {"key": "margin", "label": "毛利率", "type": "percent"},
        ]
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("select max(goal_year) as goal_year from dashboard_monthly_goal")
                    goal_year = to_int((cursor.fetchone() or {}).get("goal_year")) or date.today().year
                    cursor.execute(
                        """
                        select
                            goal_month,
                            sales_goal,
                            sales_volume_goal,
                            gross_profit_goal,
                            margin_goal
                        from dashboard_monthly_goal
                        where goal_year = %(goal_year)s
                        order by goal_month
                        """,
                        {"goal_year": goal_year},
                    )
                    goals = cursor.fetchall()
                    cursor.execute(
                        """
                        select
                            goal_month,
                            data_end_date,
                            sales_actual,
                            volume_actual,
                            profit_actual,
                            margin_actual
                        from dashboard_monthly_goal_actual_snapshot
                        where goal_year = %(goal_year)s
                        order by goal_month
                        """,
                        {"goal_year": goal_year},
                    )
                    actual_by_month = {to_int(row.get("goal_month")): row for row in cursor.fetchall()}
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return {"year": date.today().year, "data_end_date": None, "metrics": metrics, "months": []}
            raise

        data_end_date = max(
            (row.get("data_end_date") for row in actual_by_month.values() if row.get("data_end_date")),
            default=None,
        )
        current_month = data_end_date.month if data_end_date else 0
        current_day = data_end_date.day if data_end_date else 0
        months = []
        for goal in goals:
            month = to_int(goal.get("goal_month"))
            actual = actual_by_month.get(month, {})
            is_future = bool(data_end_date and month > current_month)
            is_current = bool(data_end_date and month == current_month)
            days_in_month_value = days_in_month(date(goal_year, month, 1))
            progress_ratio = current_day / days_in_month_value if is_current and days_in_month_value else 1
            month_metrics = {
                "sales": self._monthly_goal_metric(goal.get("sales_goal"), actual.get("sales_actual"), "currency", progress_ratio, is_future),
                "volume": self._monthly_goal_metric(goal.get("sales_volume_goal"), actual.get("volume_actual"), "number", progress_ratio, is_future),
                "profit": self._monthly_goal_metric(goal.get("gross_profit_goal"), actual.get("profit_actual"), "currency", progress_ratio, is_future),
                "margin": self._monthly_goal_metric(goal.get("margin_goal"), actual.get("margin_actual"), "percent", 1, is_future),
            }
            months.append(
                {
                    "month": month,
                    "label": f"{month}月",
                    "is_current": is_current,
                    "is_future": is_future,
                    "data_end_date": format_day(actual.get("data_end_date")) if actual.get("data_end_date") else None,
                    "metrics": month_metrics,
                }
            )

        return {
            "year": goal_year,
            "data_end_date": format_day(data_end_date) if data_end_date else None,
            "metrics": metrics,
            "months": months,
        }

    def get_alerts_payload(
        self,
        filters: dict[str, Any],
        alert_type: str = "all",
        compare_days: int = 7,
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            payload = self._fetch_alert_center(
                conn,
                window,
                filters,
                compare_days=compare_days,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
            )

        payload["total_count"] = len(payload["items"])
        total = len(payload["items"])
        safe_page_size = max(10, min(100, int(page_size or 20)))
        total_pages = max(1, math.ceil(total / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        start = (safe_page - 1) * safe_page_size
        payload["items"] = payload["items"][start:start + safe_page_size]
        payload["total"] = total
        payload["page"] = safe_page
        payload["page_size"] = safe_page_size
        payload["total_pages"] = total_pages
        valid_types = {"sales_drop", "margin_low", "rank_drop", "stock_short"}
        payload["selected_type"] = alert_type if alert_type in valid_types else "all"
        payload["rules"] = [
            {"type": "sales_drop", "label": "销量下滑", "rule": f"近{payload.get('compare_days', compare_days)}天销量较前一周期下滑超过30%，且前一周期销量不少于10。"},
            {"type": "margin_low", "label": "低毛利", "rule": "当前筛选周期销售额不少于1000，订单毛利率低于8%。"},
            {"type": "rank_drop", "label": "排名下滑", "rule": f"近{payload.get('compare_days', compare_days)}天平均排名较前一周期下滑至少5名，且下滑幅度不少于20%。"},
            {"type": "stock_short", "label": "库存偏低", "rule": "日销不少于1，FBA可售库存按当前日销测算不足14天。"},
        ]
        return payload

    def get_alerts_export_payload(
        self,
        filters: dict[str, Any],
        alert_type: str = "all",
        compare_days: int = 7,
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            payload = self._fetch_alert_center(
                conn,
                window,
                filters,
                compare_days=compare_days,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
            )
        return {
            "items": payload["items"],
            "window": payload["window"],
            "comparison_window": payload["comparison_window"],
            "compare_days": payload["compare_days"],
        }

    def get_opportunities_payload(
        self,
        filters: dict[str, Any],
        opportunity_type: str = "all",
        compare_days: int = 14,
        stock_status: str = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_opportunity_window(conn, filters, compare_days)
            payload = self._fetch_opportunity_pool(
                conn,
                window,
                filters,
                compare_days=compare_days,
                opportunity_type=opportunity_type,
                stock_status=stock_status,
            )

        total = len(payload["items"])
        safe_page_size = max(10, min(100, int(page_size or 20)))
        total_pages = max(1, math.ceil(total / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        start = (safe_page - 1) * safe_page_size
        payload["total_count"] = total
        payload["total"] = total
        payload["page"] = safe_page
        payload["page_size"] = safe_page_size
        payload["total_pages"] = total_pages
        payload["items"] = payload["items"][start:start + safe_page_size]
        return payload

    def get_opportunities_export_payload(
        self,
        filters: dict[str, Any],
        opportunity_type: str = "all",
        compare_days: int = 14,
        stock_status: str = "all",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_opportunity_window(conn, filters, compare_days)
            return self._fetch_opportunity_pool(
                conn,
                window,
                filters,
                compare_days=compare_days,
                opportunity_type=opportunity_type,
                stock_status=stock_status,
            )

    def _monthly_goal_metric(
        self,
        target_value: Any,
        actual_value: Any,
        metric_type: str,
        progress_ratio: float,
        is_future: bool,
    ) -> dict[str, Any]:
        target = to_float(target_value)
        actual = None if is_future else round(to_float(actual_value), 4)
        progress_target = round(target * progress_ratio, 4) if metric_type != "percent" else target
        ratio = None if actual is None or not progress_target else round(actual / progress_target, 4)
        gap = None if actual is None else round(actual - progress_target, 4)
        if ratio is None:
            status = "future"
        elif ratio >= 1:
            status = "done"
        elif ratio >= 0.8:
            status = "near"
        else:
            status = "behind"
        return {
            "target": round(target, 4),
            "progress_target": progress_target,
            "actual": actual,
            "ratio": ratio,
            "gap": gap,
            "status": status,
            "type": metric_type,
        }

    def get_detail_payload(self, filters: dict[str, Any], page: int, page_size: int) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            self._ensure_period_snapshot(conn, window)
            total = self._count_period_items(conn, window, filters)
            total_pages = max(1, math.ceil(total / page_size))
            safe_page = min(max(page, 1), total_pages)
            rows = self._fetch_period_items(
                conn,
                window,
                filters,
                limit=page_size,
                offset=(safe_page - 1) * page_size,
            )

        return {
            "meta": self.get_meta(),
            "rows": rows,
            "total": total,
            "page": safe_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "summary_hint": f"当前筛选共 {total} 个 SKU",
        }

    def get_detail_export_payload(self, filters: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            self._ensure_period_snapshot(conn, window)
            columns, rows = self._fetch_period_export_rows(conn, window, filters)

        return {
            "columns": columns,
            "rows": rows,
            "start_date": format_day(window.start_date),
            "end_date": format_day(window.end_date),
        }

    def get_detail_record(self, item_id: str, trend_days: int) -> dict[str, Any]:
        decoded = decode_item_id(item_id)
        if decoded is None:
            return {"error": "not_found"}
        snapshot_date, period_start, period_end, item_key = decoded

        with self.connect(autocommit=True) as conn:
            bounds = self._get_daily_bounds(conn)
            period_table = self._render_period_table(
                self._preset_table_for_range(bounds["max_date"], period_start, period_end)
            )
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from {period_table}
                    where snapshot_date = %(snapshot_date)s
                      and period_start = %(period_start)s
                      and period_end = %(period_end)s
                      and item_key = %(item_key)s
                      and filter_flag = 1
                    limit 1
                    """,
                    {
                        "snapshot_date": snapshot_date,
                        "period_start": period_start,
                        "period_end": period_end,
                        "item_key": item_key,
                    },
                )
                row = cursor.fetchone()
            if not row:
                return {"error": "not_found"}
            item = self._row_to_item(row)
            trend = self._fetch_item_trend(conn, row, period_end, trend_days)

        return {
            "item": {
                "id": item["id"],
                "title": f'{item["msku"]} / {item["store"]} / {item["country"]}',
                "site": item["site"],
                "country": item["country"],
                "store": item["store"],
                "sku": item["sku"],
                "msku": item["msku"],
                "asin": item["asin"],
                "brand": item["brand"],
                "category": item["category"],
                "stat_period": item["stat_period"],
                "current_revenue": item["scoped_revenue"],
                "current_daily_sales": item["daily_sales"],
                "current_margin": item["order_gross_margin"],
                "current_price": item["current_price"],
                "fba_sellable_inventory": item["fba_sellable_inventory"],
                "stock_days": item["stock_days"],
            },
            "trend": trend,
        }

    def _get_daily_bounds(self, conn) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select min(dt_date) as min_date, max(dt_date) as max_date
                from dashboard_product_performance_daily
                """
            )
            row = cursor.fetchone() or {}
        today = date.today()
        return {
            "min_date": row.get("min_date") or today,
            "max_date": row.get("max_date") or today,
        }

    def _default_range(self, bounds: dict[str, Any]) -> tuple[date, date]:
        end_date = bounds["max_date"]
        start_date = max(bounds["min_date"], end_date - timedelta(days=DEFAULT_DASHBOARD_DAYS - 1))
        return start_date, end_date

    def _get_latest_snapshot_date(self, conn) -> date:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select min(latest_date) as snapshot_date
                from (
                    select max(snapshot_date) as latest_date from dashboard_inventory_daily_snapshot
                    union all
                    select max(snapshot_date) as latest_date from dashboard_listing_price_daily_snapshot
                    union all
                    select max(snapshot_date) as latest_date from dashboard_limit_price_daily_snapshot
                ) s
                where latest_date is not null
                """
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date") or date.today()

    def _fetch_distinct(self, conn, column: str) -> list[str]:
        if column not in {"country", "country_category", "seller_name_new"}:
            return []
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select distinct {column} as value
                    from dashboard_product_period_90d_snapshot
                    where {column} is not null
                      and {column} <> ''
                      and filter_flag = 1
                    order by {column}
                    """
                )
                values = [row["value"] for row in cursor.fetchall()]
                if values:
                    return values
        except pymysql.MySQLError:
            pass

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select distinct {column} as value
                from dashboard_product_performance_daily
                where {column} is not null and {column} <> ''
                order by {column}
                """
            )
            return [row["value"] for row in cursor.fetchall()]

    def _resolve_window(self, conn, filters: dict[str, Any]) -> PeriodWindow:
        bounds = self._get_daily_bounds(conn)
        default_start, default_end = self._default_range(bounds)
        requested_start = parse_day(filters.get("start_date"))
        requested_end = parse_day(filters.get("end_date"))
        start_date = requested_start or default_start
        end_date = requested_end or default_end
        requested_days = (
            (requested_end - requested_start).days + 1
            if requested_start and requested_end and requested_start <= requested_end
            else None
        )
        start_date = max(bounds["min_date"], start_date)
        end_date = min(bounds["max_date"], end_date)
        if requested_days and requested_end and requested_end > bounds["max_date"]:
            start_date = max(bounds["min_date"], end_date - timedelta(days=requested_days - 1))
        if start_date > end_date:
            start_date, end_date = default_start, default_end
        period_table = self._preset_table_for_range(bounds["max_date"], start_date, end_date)
        period_code = {table: name for name, table in PERIOD_PRESET_TABLES.items()}.get(period_table, "custom")
        snapshot_date = self._get_period_snapshot_date(conn, period_table, start_date, end_date)
        return PeriodWindow(
            start_date=start_date,
            end_date=end_date,
            snapshot_date=snapshot_date,
            period_table=period_table,
            period_code=period_code,
        )

    def _resolve_opportunity_window(self, conn, filters: dict[str, Any], compare_days: int) -> PeriodWindow:
        bounds = self._get_daily_bounds(conn)
        days = 30 if compare_days >= 30 else 14 if compare_days >= 14 else 7
        scoped_filters = dict(filters)
        scoped_filters["end_date"] = format_day(bounds["max_date"])
        scoped_filters["start_date"] = format_day(max(bounds["min_date"], bounds["max_date"] - timedelta(days=days - 1)))
        return self._resolve_window(conn, scoped_filters)

    def _get_period_snapshot_date(
        self,
        conn,
        period_table: str,
        start_date: date,
        end_date: date,
    ) -> date:
        latest_snapshot_date = self._get_latest_snapshot_date(conn)
        if period_table == "etl_datasync.dashboard_product_period_snapshot":
            return latest_snapshot_date

        rendered_table = self._render_period_table(period_table)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select max(snapshot_date) as snapshot_date
                from {rendered_table}
                where period_start = %(period_start)s
                  and period_end = %(period_end)s
                """,
                {"period_start": start_date, "period_end": end_date},
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date") or latest_snapshot_date

    def _preset_table_for_range(self, biz_date: date, start_date: date, end_date: date) -> str:
        month_start = date(biz_date.year, biz_date.month, 1)
        last_month_end = month_start - timedelta(days=1)
        last_month_start = date(last_month_end.year, last_month_end.month, 1)
        presets = {
            "last_7_days": (biz_date - timedelta(days=6), biz_date),
            "last_14_days": (biz_date - timedelta(days=13), biz_date),
            "last_30_days": (biz_date - timedelta(days=29), biz_date),
            "last_90_days": (biz_date - timedelta(days=89), biz_date),
            "last_month": (last_month_start, last_month_end),
        }
        for name, (preset_start, preset_end) in presets.items():
            if start_date == preset_start and end_date == preset_end:
                return PERIOD_PRESET_TABLES[name]
        return "etl_datasync.dashboard_product_period_snapshot"

    def _render_period_table(self, table_name: str) -> str:
        allowed_tables = set(PERIOD_PRESET_TABLES.values()) | {"etl_datasync.dashboard_product_period_snapshot"}
        if table_name not in allowed_tables:
            raise RuntimeError(f"Unexpected period table: {table_name}")
        return render_sql(table_name, self.schemas)

    def _ensure_period_snapshot(self, conn, window: PeriodWindow) -> None:
        params = {
            "snapshot_date": window.snapshot_date,
            "period_start": window.start_date,
            "period_end": window.end_date,
        }
        period_table = self._render_period_table(window.period_table)
        lock_raw = f"{window.period_table}:{window.snapshot_date}:{window.start_date}:{window.end_date}"
        lock_name = "dashboard_period:" + hashlib.sha1(lock_raw.encode("utf-8")).hexdigest()
        lock_acquired = False
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                    select count(*) as total
                    from {period_table}
                    where snapshot_date = %(snapshot_date)s
                      and period_start = %(period_start)s
                      and period_end = %(period_end)s
                    """,
                    params,
                )
                exists = to_int((cursor.fetchone() or {}).get("total")) > 0
                if exists:
                    return

                cursor.execute("select get_lock(%s, 30) as locked", (lock_name,))
                lock_acquired = to_int((cursor.fetchone() or {}).get("locked")) == 1
                if not lock_acquired:
                    raise RuntimeError("Timed out waiting for period snapshot lock")

                cursor.execute(
                    f"""
                    select count(*) as total
                    from {period_table}
                    where snapshot_date = %(snapshot_date)s
                      and period_start = %(period_start)s
                      and period_end = %(period_end)s
                    """,
                    params,
                )
                exists = to_int((cursor.fetchone() or {}).get("total")) > 0
                if exists:
                    return

                if window.period_table == "etl_datasync.dashboard_product_period_snapshot":
                    delete_sql = DELETE_PERIOD_SNAPSHOT_SQL
                    insert_sql = INSERT_PERIOD_SNAPSHOT_SQL
                else:
                    delete_sql = period_delete_sql(window.period_table)
                    insert_sql = period_insert_sql(window.period_table)
                for attempt in range(3):
                    try:
                        cursor.execute(render_sql(delete_sql, self.schemas), params)
                        cursor.execute(render_sql(insert_sql, self.schemas), params)
                        conn.commit()
                        return
                    except pymysql.err.OperationalError as exc:
                        conn.rollback()
                        if exc.args and exc.args[0] in {1205, 1213} and attempt < 2:
                            time.sleep(0.4 * (attempt + 1))
                            continue
                        raise
            finally:
                if lock_acquired:
                    cursor.execute("select release_lock(%s)", (lock_name,))
                    conn.commit()

    def _base_period_params(self, window: PeriodWindow) -> dict[str, Any]:
        return {
            "snapshot_date": window.snapshot_date,
            "period_start": window.start_date,
            "period_end": window.end_date,
        }

    def _filter_clause(self, filters: dict[str, Any], alias: str = "p") -> tuple[str, dict[str, Any]]:
        clauses = [f"{alias}.filter_flag = 1"]
        params: dict[str, Any] = {}

        if filters.get("site", "all") != "all":
            clauses.append(f"{alias}.country = %(site)s")
            params["site"] = filters["site"]
        if filters.get("store", "all") != "all":
            clauses.append(f"{alias}.seller_name_new = %(store)s")
            params["store"] = filters["store"]
        if filters.get("over_limit") == "yes":
            clauses.append(f"{alias}.over_limit_flag = 1")
        elif filters.get("over_limit") == "no":
            clauses.append(f"{alias}.over_limit_flag = 0")
        if filters.get("daily_sales_band", "all") != "all":
            clauses.append(f"{alias}.daily_sales_band = %(daily_sales_band)s")
            params["daily_sales_band"] = filters["daily_sales_band"]
        if filters.get("margin_band", "all") != "all":
            clauses.append(f"{alias}.margin_band = %(margin_band)s")
            params["margin_band"] = filters["margin_band"]
        keyword = str(filters.get("keyword") or "").strip()
        if keyword:
            params["keyword"] = f"%{keyword}%"
            clauses.append(
                "("
                f"{alias}.seller_sku_adj like %(keyword)s "
                f"or coalesce({alias}.local_sku, '') like %(keyword)s "
                f"or coalesce({alias}.seller_name, '') like %(keyword)s "
                f"or {alias}.country like %(keyword)s"
                ")"
            )

        return " and ".join(clauses), params

    def _period_where(self, window: PeriodWindow, filters: dict[str, Any], alias: str = "p") -> tuple[str, dict[str, Any]]:
        clause, filter_params = self._filter_clause(filters, alias)
        params = self._base_period_params(window)
        params.update(filter_params)
        where_sql = (
            f"{alias}.snapshot_date = %(snapshot_date)s "
            f"and {alias}.period_start = %(period_start)s "
            f"and {alias}.period_end = %(period_end)s "
            f"and {clause}"
        )
        return where_sql, params

    def _detail_recent_join_sql(self, window: PeriodWindow, params: dict[str, Any]) -> str:
        params["recent_7_start"] = window.end_date - timedelta(days=6)
        params["recent_30_start"] = window.end_date - timedelta(days=29)
        params["recent_period_end"] = window.end_date
        return """
            left join (
                select
                    item_key,
                    sum(case when dt_date between %(recent_7_start)s and %(recent_period_end)s then sales_qty else 0 end) as sales_7d,
                    sum(case when dt_date between %(recent_30_start)s and %(recent_period_end)s then sales_qty else 0 end) as sales_30d,
                    sum(case when dt_date between %(recent_30_start)s and %(recent_period_end)s then sales_amount else 0 end) as revenue_30d
                from dashboard_product_performance_daily
                where dt_date between %(recent_30_start)s and %(recent_period_end)s
                group by item_key
            ) r on r.item_key = p.item_key
        """

    def _detail_column_filter_clause(self, filters: dict[str, Any], params: dict[str, Any]) -> tuple[str, bool]:
        column_filters = filters.get("column_filters") or {}
        if not column_filters:
            return "", False

        text_fields = {
            "country": "coalesce(p.country, '')",
            "store": "coalesce(p.seller_name_new, '')",
            "msku": "coalesce(p.seller_sku_adj, '')",
            "daily_sales_band": "coalesce(p.daily_sales_band, '')",
            "margin_band": "coalesce(p.margin_band, '')",
            "over_limit": "case when p.over_limit_flag = 1 then '是' else '否' end",
        }
        numeric_fields = {
            "daily_sales": "coalesce(p.daily_sales, 0)",
            "order_gross_margin": "coalesce(p.order_gross_margin, 0)",
            "sales_7d": "coalesce(r.sales_7d, 0)",
            "sales_30d": "coalesce(r.sales_30d, 0)",
            "revenue_30d": "coalesce(r.revenue_30d, 0)",
            "current_price": "coalesce(p.current_price, 0)",
            "limit_price_35": "coalesce(p.limit_price, 0)",
            "limit_price_10": "coalesce(p.limit_price_10, 0)",
            "price_gap": "(coalesce(p.current_price, 0) - coalesce(p.limit_price, 0))",
            "fba_sellable_inventory": "coalesce(p.fba_sellable_inventory, 0)",
            "stock_days": "coalesce(p.local_stock_sellable_days, 0)",
        }
        recent_fields = {"sales_7d", "sales_30d", "revenue_30d"}
        clauses: list[str] = []
        needs_recent_join = False

        for index, (key, raw_value) in enumerate(column_filters.items()):
            value = str(raw_value or "").strip()
            if not value:
                continue

            if key.endswith("_min") or key.endswith("_max"):
                field = key[:-4]
                if field not in numeric_fields:
                    continue
                op = ">=" if key.endswith("_min") else "<="
                param_key = f"cf_{index}"
                params[param_key] = to_float(value)
                clauses.append(f"{numeric_fields[field]} {op} %({param_key})s")
                needs_recent_join = needs_recent_join or field in recent_fields
                continue

            if key in numeric_fields:
                param_key = f"cf_{index}"
                params[param_key] = to_float(value)
                clauses.append(f"{numeric_fields[key]} = %({param_key})s")
                needs_recent_join = needs_recent_join or key in recent_fields
                continue

            if key in text_fields:
                param_key = f"cf_{index}"
                params[param_key] = f"%{value}%"
                clauses.append(f"{text_fields[key]} like %({param_key})s")

        return (" and " + " and ".join(clauses) if clauses else ""), needs_recent_join

    def _fetch_dashboard_stats(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> dict[str, float]:
        where_sql, params = self._period_where(window, filters)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(*) as sku_count,
                    sum(case when p.over_limit_flag = 1 then 1 else 0 end) as over_limit_count,
                    sum(p.sales_qty) as sales_qty,
                    sum(p.sales_amount) as sales_amount,
                    sum(p.sales_amount_ex_tax) as sales_amount_ex_tax,
                    sum(p.order_gross_profit) as order_gross_profit,
                    sum(p.ad_spend) as ad_spend,
                    sum(p.ad_sales) as ad_sales
                from {self._render_period_table(window.period_table)} p
                where {where_sql}
                """,
                params,
            )
            row = cursor.fetchone() or {}
            cursor.execute(
                f"""
                select
                    sum(x.fba_total_inventory) as fba_total_inventory,
                    sum(x.fba_sellable_inventory) as fba_sellable_inventory,
                    sum(x.actual_in_transit) as actual_in_transit,
                    sum(x.unsellable_inventory) as unsellable_inventory
                from (
                    select
                        p.seller_name_new,
                        p.seller_sku_adj,
                        p.country_category,
                        max(p.fba_total_inventory) as fba_total_inventory,
                        max(p.fba_sellable_inventory) as fba_sellable_inventory,
                        max(p.actual_in_transit) as actual_in_transit,
                        max(p.unsellable_inventory) as unsellable_inventory
                    from {self._render_period_table(window.period_table)} p
                    where {where_sql}
                    group by
                        p.seller_name_new,
                        p.seller_sku_adj,
                        p.country_category
                ) x
                """,
                params,
            )
            inventory_row = cursor.fetchone() or {}

        stat_days = max(window.days, 1)
        sales_amount = to_float(row.get("sales_amount"))
        order_gross_profit = to_float(row.get("order_gross_profit"))
        ad_spend = to_float(row.get("ad_spend"))
        ad_sales = to_float(row.get("ad_sales"))
        return {
            "sku_count": to_int(row.get("sku_count")),
            "over_limit_count": to_int(row.get("over_limit_count")),
            "sales_qty": to_float(row.get("sales_qty")),
            "sales_amount": sales_amount,
            "order_gross_margin": round(order_gross_profit / sales_amount, 4) if sales_amount else 0,
            "avg_daily_sales": round(to_float(row.get("sales_qty")) / stat_days, 2),
            "fba_total_inventory": to_float(inventory_row.get("fba_total_inventory")),
            "fba_sellable_inventory": to_float(inventory_row.get("fba_sellable_inventory")),
            "actual_in_transit": to_float(inventory_row.get("actual_in_transit")),
            "unsellable_inventory": to_float(inventory_row.get("unsellable_inventory")),
            "ad_spend": ad_spend,
            "ad_sales": ad_sales,
            "acos": round(ad_spend / ad_sales, 4) if ad_sales else 0,
            "tacos": round(ad_spend / sales_amount, 4) if sales_amount else 0,
        }

    def _fetch_band_counts(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
        column: str,
        bands: list[str],
    ) -> dict[str, Any]:
        if column not in {"daily_sales_band", "margin_band"}:
            raise RuntimeError(f"Unexpected band column: {column}")
        where_sql, params = self._period_where(window, filters)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    p.{column} as band,
                    count(*) as value,
                    sum(case when p.over_limit_flag = 1 then 1 else 0 end) as over_limit
                from {self._render_period_table(window.period_table)} p
                where {where_sql}
                group by p.{column}
                """,
                params,
            )
            by_band = {row["band"]: row for row in cursor.fetchall()}

        return {
            "items": [
                {
                    "name": band,
                    "value": to_int((by_band.get(band) or {}).get("value")),
                    "over_limit": to_int((by_band.get(band) or {}).get("over_limit")),
                }
                for band in bands
            ]
        }

    def _fetch_matrix_counts(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> dict[str, Any]:
        if not str(filters.get("keyword") or "").strip() and window.period_code != "custom":
            try:
                matrix = self._fetch_matrix_counts_from_summary(conn, window, filters)
                if matrix is not None:
                    return matrix
            except pymysql.MySQLError:
                pass
        return self._fetch_matrix_counts_from_period(conn, window, filters)

    def _fetch_matrix_counts_from_summary(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> dict[str, Any] | None:
        base_clauses = [
            "m.snapshot_date = %(snapshot_date)s",
            "m.period_code = %(period_code)s",
            "m.country = %(country)s",
            "m.seller_name_new = %(seller_name_new)s",
            "m.over_limit_scope = %(over_limit_scope)s",
        ]
        base_params: dict[str, Any] = {
            "snapshot_date": window.snapshot_date,
            "period_code": window.period_code,
            "country": filters.get("site") if filters.get("site", "all") != "all" else MATRIX_ALL_VALUE,
            "seller_name_new": filters.get("store") if filters.get("store", "all") != "all" else MATRIX_ALL_VALUE,
            "over_limit_scope": filters.get("over_limit") if filters.get("over_limit") in {"yes", "no"} else "all",
        }
        if filters.get("daily_sales_band", "all") != "all":
            base_clauses.append("m.daily_sales_band = %(daily_sales_band)s")
            base_params["daily_sales_band"] = filters["daily_sales_band"]
        if filters.get("margin_band", "all") != "all":
            base_clauses.append("m.margin_band = %(margin_band)s")
            base_params["margin_band"] = filters["margin_band"]

        current_counts = self._fetch_matrix_summary_raw_counts(
            conn,
            base_clauses,
            base_params,
            window.start_date,
            window.end_date,
        )
        if not current_counts:
            return None
        previous_start, previous_end = self._previous_period_range(window)
        bounds = self._get_daily_bounds(conn)
        previous_counts = None
        if previous_start >= bounds["min_date"] and previous_end <= bounds["max_date"]:
            previous_counts = self._fetch_matrix_summary_raw_counts(
                conn,
                base_clauses,
                base_params,
                previous_start,
                previous_end,
            )
        return self._build_matrix_from_raw_counts(current_counts, previous_counts)

    def _fetch_matrix_summary_raw_counts(
        self,
        conn,
        base_clauses: list[str],
        base_params: dict[str, Any],
        period_start: date,
        period_end: date,
    ) -> dict[tuple[str, str], int]:
        clauses = list(base_clauses)
        clauses.extend(
            [
                "m.period_start = %(period_start)s",
                "m.period_end = %(period_end)s",
            ]
        )
        params = dict(base_params)
        params.update({"period_start": period_start, "period_end": period_end})
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    m.margin_band,
                    m.daily_sales_band,
                    sum(m.sku_count) as count_value
                from {render_sql(MATRIX_PERIOD_TABLE, self.schemas)} m
                where {" and ".join(clauses)}
                group by m.margin_band, m.daily_sales_band
                """,
                params,
            )
            rows = cursor.fetchall()
        return {
            (row["margin_band"], row["daily_sales_band"]): to_int(row.get("count_value"))
            for row in rows
        }

    def _previous_period_range(self, window: PeriodWindow) -> tuple[date, date]:
        previous_end = window.start_date - timedelta(days=1)
        if window.period_code == "last_month":
            previous_start = date(previous_end.year, previous_end.month, 1)
        else:
            days = (window.end_date - window.start_date).days + 1
            previous_start = previous_end - timedelta(days=days - 1)
        return previous_start, previous_end

    def _fetch_matrix_counts_from_period(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> dict[str, Any]:
        where_sql, params = self._period_where(window, filters)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    p.margin_band,
                    p.daily_sales_band,
                    count(*) as count_value
                from {self._render_period_table(window.period_table)} p
                where {where_sql}
                group by p.margin_band, p.daily_sales_band
                """,
                params,
            )
            raw_counts = {
                (row["margin_band"], row["daily_sales_band"]): to_int(row.get("count_value"))
                for row in cursor.fetchall()
            }

        return self._build_matrix_from_raw_counts(raw_counts)

    def _build_matrix_from_raw_counts(
        self,
        raw_counts: dict[tuple[str, str], int],
        previous_counts: dict[tuple[str, str], int] | None = None,
    ) -> dict[str, Any]:
        total = max(sum(raw_counts.values()), 1)
        previous_total = max(sum((previous_counts or {}).values()), 1)
        has_previous = previous_counts is not None
        cells = []
        for margin in MARGIN_BANDS:
            for sales in DAILY_SALES_BANDS:
                count = raw_counts.get((margin, sales), 0)
                previous_count = (previous_counts or {}).get((margin, sales), 0)
                count_delta = count - previous_count if has_previous else None
                count_change_ratio = (
                    round(count_delta / previous_count, 4)
                    if has_previous and previous_count
                    else (1 if has_previous and count > 0 else 0 if has_previous else None)
                )
                previous_ratio = round(previous_count / previous_total, 4) if has_previous else None
                cells.append(
                    {
                        "margin_band": margin,
                        "daily_sales_band": sales,
                        "count": count,
                        "ratio": round(count / total, 4),
                        "previous_count": previous_count if has_previous else None,
                        "count_delta": count_delta,
                        "count_change_ratio": count_change_ratio,
                        "previous_ratio": previous_ratio,
                        "ratio_delta": round((count / total) - previous_ratio, 4) if has_previous else None,
                    }
                )
        return {
            "margin_bands": MARGIN_BANDS,
            "daily_sales_bands": DAILY_SALES_BANDS,
            "cells": cells,
        }

    def _fetch_period_items(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_sql, params = self._period_where(window, filters)
        limit_sql = ""
        if limit is not None:
            params["limit"] = limit
            params["offset"] = offset
            limit_sql = "limit %(limit)s offset %(offset)s"
        column_filter_sql, needs_recent_join = self._detail_column_filter_clause(filters, params)
        recent_join_sql = self._detail_recent_join_sql(window, params) if needs_recent_join else ""

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select p.*
                from {self._render_period_table(window.period_table)} p
                {recent_join_sql}
                where {where_sql}{column_filter_sql}
                order by p.sales_amount desc, p.daily_sales desc, p.seller_sku_adj
                {limit_sql}
                """,
                params,
            )
            rows = [self._row_to_item(row) for row in cursor.fetchall()]
            self._enrich_recent_sales_metrics(conn, window.end_date, rows)
            return rows

    def _fetch_period_export_rows(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        where_sql, params = self._period_where(window, filters)
        column_filter_sql, needs_recent_join = self._detail_column_filter_clause(filters, params)
        recent_join_sql = self._detail_recent_join_sql(window, params) if needs_recent_join else ""
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select p.*
                from {self._render_period_table(window.period_table)} p
                {recent_join_sql}
                where {where_sql}{column_filter_sql}
                order by p.sales_amount desc, p.daily_sales desc, p.seller_sku_adj
                """,
                params,
            )
            columns = [column[0] for column in cursor.description or ()]
            rows = cursor.fetchall()
        return columns, rows

    def _enrich_recent_sales_metrics(self, conn, period_end: date, items: list[dict[str, Any]]) -> None:
        item_keys = [item["item_key"] for item in items if item.get("item_key")]
        if not item_keys:
            return

        params: dict[str, Any] = {
            "recent_7_start": period_end - timedelta(days=6),
            "recent_30_start": period_end - timedelta(days=29),
            "period_end": period_end,
        }
        placeholders = []
        for index, item_key in enumerate(item_keys):
            key = f"item_key_{index}"
            params[key] = item_key
            placeholders.append(f"%({key})s")

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    item_key,
                    sum(case when dt_date between %(recent_7_start)s and %(period_end)s then sales_qty else 0 end) as sales_7d,
                    sum(case when dt_date between %(recent_30_start)s and %(period_end)s then sales_qty else 0 end) as sales_30d,
                    sum(case when dt_date between %(recent_30_start)s and %(period_end)s then sales_amount else 0 end) as revenue_30d
                from dashboard_product_performance_daily
                where dt_date between %(recent_30_start)s and %(period_end)s
                  and item_key in ({", ".join(placeholders)})
                group by item_key
                """,
                params,
            )
            metrics_by_key = {row["item_key"]: row for row in cursor.fetchall()}

        for item in items:
            metrics = metrics_by_key.get(item.get("item_key"))
            if not metrics:
                item["sales_7d"] = 0
                item["sales_30d"] = 0
                item["revenue_30d"] = 0
                continue
            item["sales_7d"] = round(to_float(metrics.get("sales_7d")))
            item["sales_30d"] = round(to_float(metrics.get("sales_30d")))
            item["revenue_30d"] = round(to_float(metrics.get("revenue_30d")), 2)

    def _count_period_items(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> int:
        where_sql, params = self._period_where(window, filters)
        column_filter_sql, needs_recent_join = self._detail_column_filter_clause(filters, params)
        recent_join_sql = self._detail_recent_join_sql(window, params) if needs_recent_join else ""
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from {self._render_period_table(window.period_table)} p
                {recent_join_sql}
                where {where_sql}{column_filter_sql}
                """,
                params,
            )
            return to_int((cursor.fetchone() or {}).get("total"))

    def _row_to_item(self, row: dict[str, Any]) -> dict[str, Any]:
        stat_days = max(to_int(row.get("stat_days")), 1)
        sales_qty = to_float(row.get("sales_qty"))
        sales_amount = to_float(row.get("sales_amount"))
        daily_sales = to_float(row.get("daily_sales"))
        current_price = to_float(row.get("current_price"))
        limit_price = to_float(row.get("limit_price"))
        limit_price_10 = to_float(row.get("limit_price_10"))
        period_start = row["period_start"]
        period_end = row["period_end"]
        snapshot_date = row["snapshot_date"]
        item_key = row["item_key"]

        return {
            "id": encode_item_id(snapshot_date, period_start, period_end, item_key),
            "item_key": item_key,
            "site": row.get("country") or "",
            "country": row.get("country") or "",
            "store": row.get("seller_name_new") or "",
            "sku": row.get("seller_sku_adj") or "",
            "msku": row.get("seller_sku_adj") or "",
            "asin": row.get("local_sku") or "",
            "product_name": f"{row.get('seller_sku_adj') or ''} / {row.get('country') or ''}",
            "brand": UNKNOWN_TEXT,
            "category": row.get("country") or row.get("country_category") or "",
            "current_price": current_price,
            "limit_price": limit_price,
            "limit_price_35": limit_price,
            "limit_price_10": limit_price_10,
            "price_gap": round(current_price - limit_price, 2) if limit_price else 0,
            "over_limit": bool(row.get("over_limit_flag")),
            "fba_sellable_inventory": to_int(row.get("fba_sellable_inventory")),
            "actual_in_transit": to_int(row.get("actual_in_transit")),
            "unsellable_inventory": to_int(row.get("unsellable_inventory")),
            "stock_days": to_int(row.get("local_stock_sellable_days")),
            "rating": 0,
            "review_count": 0,
            "scoped_sales": round(sales_qty),
            "scoped_revenue": round(sales_amount, 2),
            "daily_sales": round(daily_sales, 2),
            "daily_sales_band": row.get("daily_sales_band") or "日销 0",
            "order_gross_margin": round(to_float(row.get("order_gross_margin")), 4),
            "margin_band": row.get("margin_band") or "毛利率 <0%",
            "sales_7d": round(daily_sales * min(7, stat_days)),
            "sales_30d": round(daily_sales * min(30, stat_days)),
            "revenue_30d": round((sales_amount / stat_days) * min(30, stat_days), 2),
            "ad_spend": round(to_float(row.get("ad_spend")), 2),
            "ad_sales": round(to_float(row.get("ad_sales")), 2),
            "acos": round(to_float(row.get("acos")), 4),
            "tacos": round(to_float(row.get("tacos")), 4),
            "ctr": round(to_float(row.get("ctr")), 4),
            "stat_period": f"{format_day(period_start)} ~ {format_day(period_end)}",
        }

    def _fetch_kpi_series(self, conn, window: PeriodWindow, filters: dict[str, Any]) -> dict[str, list[float]]:
        trend_end = window.end_date
        trend_start = max(window.start_date, trend_end - timedelta(days=6))
        labels = iter_days(trend_start, trend_end)
        empty = {
            "active_sku": [0 for _ in labels],
            "revenue": [0.0 for _ in labels],
            "daily_sales": [0.0 for _ in labels],
            "margin": [0.0 for _ in labels],
            "ad_spend": [0.0 for _ in labels],
            "ad_sales": [0.0 for _ in labels],
            "acos": [0.0 for _ in labels],
            "tacos": [0.0 for _ in labels],
        }
        if not labels:
            return empty

        where_sql, params = self._period_where(window, filters, alias="p")
        params.update({"trend_start": trend_start, "trend_end": trend_end})
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    d.dt_date,
                    count(distinct case when d.sales_qty > 0 then d.item_key end) as active_sku,
                    sum(d.sales_qty) as sales_qty,
                    sum(d.sales_amount) as sales_amount,
                    sum(d.order_gross_profit) as order_gross_profit,
                    sum(d.sales_amount_ex_tax) as sales_amount_ex_tax,
                    sum(d.ad_spend) as ad_spend,
                    sum(d.ad_sales) as ad_sales
                from {self._render_period_table(window.period_table)} p
                join dashboard_product_performance_daily d
                  on d.dt_date between %(trend_start)s and %(trend_end)s
                 and d.item_key = p.item_key
                where {where_sql}
                group by d.dt_date
                """,
                params,
            )
            by_date = {row["dt_date"]: row for row in cursor.fetchall()}

        revenue = []
        daily_sales = []
        margin = []
        ad_spend = []
        ad_sales = []
        active_sku = []
        for day in labels:
            row = by_date.get(day, {})
            day_revenue = to_float(row.get("sales_amount"))
            day_units = to_float(row.get("sales_qty"))
            day_ad_spend = to_float(row.get("ad_spend"))
            day_ad_sales = to_float(row.get("ad_sales"))
            revenue.append(round(day_revenue, 2))
            daily_sales.append(round(day_units, 2))
            margin.append(round(to_float(row.get("order_gross_profit")) / to_float(row.get("sales_amount")), 4) if to_float(row.get("sales_amount")) else 0)
            ad_spend.append(round(day_ad_spend, 2))
            ad_sales.append(round(day_ad_sales, 2))
            active_sku.append(to_int(row.get("active_sku")))

        empty.update(
            {
                "active_sku": active_sku,
                "revenue": revenue,
                "daily_sales": daily_sales,
                "margin": margin,
                "ad_spend": ad_spend,
                "ad_sales": ad_sales,
                "acos": [round(spend / sale, 4) if sale else 0 for spend, sale in zip(ad_spend, ad_sales)],
                "tacos": [round(spend / sale, 4) if sale else 0 for spend, sale in zip(ad_spend, revenue)],
            }
        )
        return empty

    def _fetch_alert_center(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
        compare_days: int = 7,
        alert_type: str = "all",
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
    ) -> dict[str, Any]:
        table = self._render_period_table(window.period_table)
        where_sql, params = self._period_where(window, filters, alias="p")
        compare_days = 30 if compare_days >= 30 else 14 if compare_days >= 14 else 7
        recent_end = window.end_date
        recent_start = recent_end - timedelta(days=compare_days - 1)
        previous_end = recent_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=compare_days - 1)
        params.update(
            {
                "recent_start": recent_start,
                "recent_end": recent_end,
                "previous_start": previous_start,
                "previous_end": previous_end,
            }
        )
        items: list[dict[str, Any]] = []

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    p.seller_sku_adj, p.seller_name_new, p.country,
                    max(p.sales_amount) as sales_amount,
                    max(p.order_gross_margin) as order_gross_margin,
                    max(p.fba_sellable_inventory) as fba_sellable_inventory,
                    max(p.daily_sales) as daily_sales,
                    max(p.fba_sellable_inventory / nullif(p.daily_sales, 0)) as sellable_days,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.sales_qty else 0 end) as recent_sales_qty,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.sales_qty else 0 end) as previous_sales_qty,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.sales_amount else 0 end) as recent_sales_amount,
                    avg(case when d.dt_date between %(recent_start)s and %(recent_end)s and d.ranking > 0 then d.ranking end) as recent_rank,
                    avg(case when d.dt_date between %(previous_start)s and %(previous_end)s and d.ranking > 0 then d.ranking end) as previous_rank
                from {table} p
                left join dashboard_product_performance_daily d
                  on d.item_key = p.item_key
                 and d.dt_date between %(previous_start)s and %(recent_end)s
                where {where_sql}
                group by p.item_key, p.seller_sku_adj, p.seller_name_new, p.country
                """,
                params,
            )
            for row in cursor.fetchall():
                item = self._build_alert_metric_item(row, compare_days)
                if item["has_alert"]:
                    items.append(item)

        priority = {"sales_drop": 0, "margin_low": 1, "rank_drop": 2, "stock_short": 3}
        filtered = [
            item
            for item in items
            if self._alert_item_matches(
                item,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
            )
        ]
        filtered.sort(key=lambda item: (item["priority"], item["title"]))
        summary = {key: 0 for key in priority}
        for item in filtered:
            for key in item["alert_types"]:
                if key in summary:
                    summary[key] += 1
        return {
            "items": filtered,
            "summary": summary,
            "window": f"近{compare_days}天 {format_day(recent_start)} ~ {format_day(recent_end)}",
            "comparison_window": f"前{compare_days}天 {format_day(previous_start)} ~ {format_day(previous_end)}",
            "compare_days": compare_days,
            "empty_text": "当前筛选下没有明显异常。",
        }

    def _fetch_opportunity_pool(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
        compare_days: int = 14,
        opportunity_type: str = "all",
        stock_status: str = "all",
    ) -> dict[str, Any]:
        table = self._render_period_table(window.period_table)
        scoped_filters = dict(filters)
        scoped_filters["over_limit"] = scoped_filters.get("over_limit") or "no"
        where_sql, params = self._period_where(window, scoped_filters, alias="p")
        days = 30 if compare_days >= 30 else 14 if compare_days >= 14 else 7
        recent_end = window.end_date
        recent_start = recent_end - timedelta(days=days - 1)
        previous_end = recent_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)
        params.update(
            {
                "recent_start": recent_start,
                "recent_end": recent_end,
                "previous_start": previous_start,
                "previous_end": previous_end,
            }
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    p.item_key,
                    p.seller_sku_adj,
                    p.seller_name_new,
                    p.country,
                    p.sales_qty,
                    p.sales_amount,
                    p.order_gross_profit,
                    p.order_gross_margin,
                    p.daily_sales,
                    p.fba_sellable_inventory,
                    p.current_price,
                    p.limit_price,
                    p.limit_price_10,
                    p.over_limit_flag,
                    p.ad_spend,
                    p.ad_sales,
                    p.acos,
                    p.tacos,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.sales_qty else 0 end) as recent_sales_qty,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.sales_qty else 0 end) as previous_sales_qty,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.sessions_total else 0 end) as recent_sessions,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.sessions_total else 0 end) as previous_sessions,
                    avg(case when d.dt_date between %(recent_start)s and %(recent_end)s and d.ranking > 0 then d.ranking end) as recent_rank,
                    avg(case when d.dt_date between %(previous_start)s and %(previous_end)s and d.ranking > 0 then d.ranking end) as previous_rank
                from {table} p
                left join dashboard_product_performance_daily d
                  on d.item_key = p.item_key
                 and d.dt_date between %(previous_start)s and %(recent_end)s
                where {where_sql}
                  and coalesce(p.seller_sku_adj, '') <> ''
                  and (coalesce(p.sales_qty, 0) > 0 or coalesce(p.sales_amount, 0) > 0)
                group by p.item_key, p.seller_sku_adj, p.seller_name_new, p.country
                """,
                params,
            )
            rows = cursor.fetchall()

        items = [self._build_opportunity_item(row, days) for row in rows]
        items = [item for item in items if item["opportunity_types"]]
        if opportunity_type != "all":
            items = [item for item in items if opportunity_type in item["opportunity_types"]]
        if stock_status == "enough":
            items = [item for item in items if item["stock_status"] == "enough"]
        elif stock_status == "short":
            items = [item for item in items if item["stock_status"] == "short"]
        items.sort(key=lambda item: (-item["score"], -item["scoped_revenue"], item["msku"]))

        type_defs = self._opportunity_type_defs()
        summary = {item["key"]: 0 for item in type_defs if item["key"] != "all"}
        boost_revenue = 0.0
        for item in items:
            for key in item["opportunity_types"]:
                if key in summary:
                    summary[key] += 1
            boost_revenue += item["estimated_boost_revenue"]

        return {
            "items": items,
            "summary": summary,
            "stats": {
                "total": len(items),
                "high_margin_scale": summary.get("high_margin_scale", 0),
                "rank_improve": summary.get("rank_improve", 0),
                "inventory_push": summary.get("inventory_push", 0),
                "estimated_boost_revenue": round(boost_revenue, 2),
            },
            "types": type_defs,
            "window": f"近{days}天 {format_day(recent_start)} ~ {format_day(recent_end)}",
            "comparison_window": f"前{days}天 {format_day(previous_start)} ~ {format_day(previous_end)}",
            "compare_days": days,
            "empty_text": "当前筛选下没有符合加码条件的机会 SKU。",
        }

    def _opportunity_type_defs(self) -> list[dict[str, str]]:
        return [
            {"key": "all", "label": "全部机会", "rule": "展示所有满足机会规则的 SKU，按机会分从高到低排序。"},
            {"key": "high_margin_scale", "label": "高毛利可放量", "rule": "毛利率不低于25%，日销不低于1，可售天数不低于21天，且未超限价。"},
            {"key": "rank_improve", "label": "排名改善", "rule": "近 N 天平均排名较前 N 天改善至少5名，且改善幅度不低于20%。"},
            {"key": "inventory_push", "label": "库存充足待推", "rule": "可售天数不低于30天，毛利率不低于15%，日销不低于0.5。"},
            {"key": "low_sales_high_margin", "label": "低销高毛利", "rule": "毛利率不低于35%，日销低于1，可售天数不低于21天。"},
            {"key": "ad_efficiency", "label": "广告效率可加码", "rule": "TACOS不高于8%或ACOS不高于25%，毛利率不低于20%，且有销售或广告表现。"},
        ]

    def _build_opportunity_item(self, row: dict[str, Any], compare_days: int) -> dict[str, Any]:
        sales_qty = to_float(row.get("sales_qty"))
        sales_amount = to_float(row.get("sales_amount"))
        profit = to_float(row.get("order_gross_profit"))
        margin = to_float(row.get("order_gross_margin"))
        daily_sales = to_float(row.get("daily_sales"))
        fba_sellable = to_float(row.get("fba_sellable_inventory"))
        sellable_days = fba_sellable / daily_sales if daily_sales > 0 else 0.0
        previous_qty = to_float(row.get("previous_sales_qty"))
        recent_qty = to_float(row.get("recent_sales_qty"))
        sales_change_rate = (recent_qty - previous_qty) / previous_qty if previous_qty else (1.0 if recent_qty > 0 else 0.0)
        previous_sessions = to_float(row.get("previous_sessions"))
        recent_sessions = to_float(row.get("recent_sessions"))
        sessions_change_rate = (recent_sessions - previous_sessions) / previous_sessions if previous_sessions else (1.0 if recent_sessions > 0 else 0.0)
        previous_rank_raw = row.get("previous_rank")
        recent_rank_raw = row.get("recent_rank")
        previous_rank = int(round(to_float(previous_rank_raw))) if previous_rank_raw is not None else None
        recent_rank = int(round(to_float(recent_rank_raw))) if recent_rank_raw is not None else None
        rank_delta = (previous_rank - recent_rank) if previous_rank is not None and recent_rank is not None else 0
        rank_improve_ratio = (rank_delta / previous_rank) if previous_rank else 0.0
        ad_spend = to_float(row.get("ad_spend"))
        ad_sales = to_float(row.get("ad_sales"))
        acos = to_float(row.get("acos"))
        tacos = to_float(row.get("tacos"))
        over_limit = bool(row.get("over_limit_flag"))

        types: list[str] = []
        if margin >= 0.25 and daily_sales >= 1 and sellable_days >= 21 and not over_limit:
            types.append("high_margin_scale")
        if rank_delta >= 5 and rank_improve_ratio >= 0.20 and sellable_days >= 14:
            types.append("rank_improve")
        if sellable_days >= 30 and margin >= 0.15 and daily_sales >= 0.5 and not over_limit:
            types.append("inventory_push")
        if margin >= 0.35 and daily_sales < 1 and sellable_days >= 21 and not over_limit:
            types.append("low_sales_high_margin")
        if (tacos <= 0.08 or (acos > 0 and acos <= 0.25)) and margin >= 0.20 and (sales_amount > 0 or ad_spend > 0):
            types.append("ad_efficiency")

        stock_status = "enough" if sellable_days >= 21 else "short"
        score = self._opportunity_score(
            margin=margin,
            daily_sales=daily_sales,
            sales_amount=sales_amount,
            sales_change_rate=sales_change_rate,
            rank_improve_ratio=rank_improve_ratio,
            sessions_change_rate=sessions_change_rate,
            sellable_days=sellable_days,
            over_limit=over_limit,
            tacos=tacos,
        )
        primary_type = types[0] if types else "observe"
        avg_price = sales_amount / sales_qty if sales_qty else 0
        estimated_boost_revenue = round(max(daily_sales, 0) * min(max(sellable_days, 0), 30) * 0.15 * avg_price, 2)
        return {
            "type": primary_type,
            "opportunity_types": types,
            "label": self._opportunity_label(primary_type),
            "score": score,
            "msku": str(row.get("seller_sku_adj") or "-"),
            "store": str(row.get("seller_name_new") or "-"),
            "country": str(row.get("country") or "-"),
            "keyword": str(row.get("seller_sku_adj") or ""),
            "daily_sales": round(daily_sales, 2),
            "sales_change_rate": round(sales_change_rate, 4),
            "sales_text": f"{recent_qty:.0f} / {previous_qty:.0f} ({sales_change_rate:+.1%})",
            "scoped_revenue": round(sales_amount, 2),
            "profit": round(profit, 2),
            "margin": round(margin, 4),
            "rank_text": f"{previous_rank or '—'} -> {recent_rank or '—'}",
            "rank_delta": rank_delta,
            "recent_sessions": round(recent_sessions),
            "conversion": round(recent_qty / recent_sessions, 4) if recent_sessions else 0,
            "fba_sellable_inventory": round(fba_sellable),
            "sellable_days": round(sellable_days, 1),
            "stock_status": stock_status,
            "acos": round(acos, 4),
            "tacos": round(tacos, 4),
            "ad_spend": round(ad_spend, 2),
            "current_price": round(to_float(row.get("current_price")), 2),
            "limit_price_35": round(to_float(row.get("limit_price")), 2),
            "limit_price_10": round(to_float(row.get("limit_price_10")), 2),
            "over_limit": over_limit,
            "estimated_boost_revenue": estimated_boost_revenue,
            "suggested_action": self._opportunity_action(primary_type),
        }

    def _opportunity_score(
        self,
        margin: float,
        daily_sales: float,
        sales_amount: float,
        sales_change_rate: float,
        rank_improve_ratio: float,
        sessions_change_rate: float,
        sellable_days: float,
        over_limit: bool,
        tacos: float,
    ) -> int:
        margin_score = min(max(margin, 0) / 0.35, 1) * 25
        sales_score = (min(max(sales_change_rate, 0), 1) * 0.4 + min(daily_sales / 5, 1) * 0.35 + min(sales_amount / 50000, 1) * 0.25) * 25
        traffic_score = (min(max(rank_improve_ratio, 0), 0.5) / 0.5 * 0.55 + min(max(sessions_change_rate, 0), 1) * 0.45) * 20
        if sellable_days < 14:
            stock_score = 0
        elif sellable_days <= 60:
            stock_score = min((sellable_days - 14) / 46, 1) * 20
        else:
            stock_score = 18
        risk_penalty = 0
        if over_limit:
            risk_penalty += 4
        if tacos > 0.12:
            risk_penalty += 3
        if sellable_days < 14:
            risk_penalty += 2
        if margin < 0.15:
            risk_penalty += 1
        return max(0, min(100, int(round(margin_score + sales_score + traffic_score + stock_score - risk_penalty))))

    def _opportunity_label(self, key: str) -> str:
        return {
            "high_margin_scale": "高毛利可放量",
            "rank_improve": "排名改善",
            "inventory_push": "库存充足待推",
            "low_sales_high_margin": "低销高毛利",
            "ad_efficiency": "广告效率可加码",
        }.get(key, "机会观察")

    def _opportunity_action(self, key: str) -> str:
        return {
            "high_margin_scale": "建议加广告或重点推款",
            "rank_improve": "建议观察排名趋势并加资源承接",
            "inventory_push": "建议做促销、广告或调价测试",
            "low_sales_high_margin": "建议测试降价或提高曝光",
            "ad_efficiency": "建议提高预算或扩词",
        }.get(key, "建议人工复核后再处理")

    def _build_alert_metric_item(self, row: dict[str, Any], compare_days: int) -> dict[str, Any]:
        previous_qty = to_float(row.get("previous_sales_qty"))
        recent_qty = to_float(row.get("recent_sales_qty"))
        sales_change = (recent_qty - previous_qty) / previous_qty if previous_qty else (1 if recent_qty > 0 else 0)
        sales_down = previous_qty >= 10 and recent_qty <= previous_qty * 0.7
        sales_up = recent_qty >= 10 and recent_qty >= previous_qty * 1.3

        previous_rank_raw = row.get("previous_rank")
        recent_rank_raw = row.get("recent_rank")
        previous_rank = int(round(to_float(previous_rank_raw))) if previous_rank_raw is not None else None
        recent_rank = int(round(to_float(recent_rank_raw))) if recent_rank_raw is not None else None
        rank_down = (
            previous_rank is not None
            and recent_rank is not None
            and recent_rank >= previous_rank + 5
            and recent_rank >= previous_rank * 1.2
        )
        rank_up = (
            previous_rank is not None
            and recent_rank is not None
            and recent_rank <= max(previous_rank - 5, previous_rank * 0.8)
        )

        sales_amount = to_float(row.get("sales_amount"))
        margin = to_float(row.get("order_gross_margin"))
        margin_low = sales_amount >= 1000 and margin < 0.08

        daily_sales = to_float(row.get("daily_sales"))
        sellable_days = to_float(row.get("sellable_days"))
        has_sales_signal = daily_sales > 0 or previous_qty > 0 or recent_qty > 0
        stock_short = has_sales_signal and sellable_days < 14

        alert_types: list[str] = []
        labels: list[str] = []
        if sales_down:
            alert_types.append("sales_drop")
            labels.append("销量下滑")
        if margin_low:
            alert_types.append("margin_low")
            labels.append("低毛利")
        if rank_down:
            alert_types.append("rank_drop")
            labels.append("排名下滑")
        if stock_short:
            alert_types.append("stock_short")
            labels.append("库存偏低")

        priority_map = {"sales_drop": 0, "margin_low": 1, "rank_drop": 2, "stock_short": 3}
        priority = min((priority_map[key] for key in alert_types), default=9)
        primary_type = min(alert_types, key=lambda key: priority_map.get(key, 9)) if alert_types else "observe"
        tone = "negative" if sales_down or stock_short else "warning"
        return {
            "type": primary_type,
            "alert_types": alert_types,
            "label": " / ".join(labels) if labels else "观察",
            "labels": labels,
            "tone": tone,
            "title": str(row.get("seller_sku_adj") or "-"),
            "subtitle": f"{row.get('seller_name_new') or '-'} / {row.get('country') or '-'}",
            "store": str(row.get("seller_name_new") or "-"),
            "country": str(row.get("country") or "-"),
            "detail": "；".join(labels) if labels else "未触发预警",
            "keyword": str(row.get("seller_sku_adj") or ""),
            "priority": priority,
            "has_alert": bool(alert_types),
            "sales_trend": "down" if sales_down else "up" if sales_up else "stable",
            "rank_trend": "down" if rank_down else "up" if rank_up else "stable",
            "margin_status": "low" if margin_low else "normal",
            "stock_status": "short" if stock_short else "normal",
            "sales_text": f"近{compare_days}天 {recent_qty:.0f} / 前{compare_days}天 {previous_qty:.0f}（{sales_change:+.1%}）",
            "rank_text": f"{previous_rank or '—'} -> {recent_rank or '—'}",
            "margin_text": f"{margin:.1%} / {compact_currency(sales_amount)}",
            "stock_text": f"{sellable_days:.1f} 天 / 日销 {daily_sales:.1f}" if stock_short or daily_sales else "—",
        }

    def _alert_item_matches(
        self,
        item: dict[str, Any],
        alert_type: str,
        sales_trend: str,
        rank_trend: str,
        margin_status: str,
        stock_status: str,
    ) -> bool:
        if alert_type != "all" and alert_type not in item.get("alert_types", []):
            return False
        if sales_trend in {"down", "up", "stable"} and item.get("sales_trend") != sales_trend:
            return False
        if rank_trend in {"down", "up", "stable"} and item.get("rank_trend") != rank_trend:
            return False
        if margin_status in {"low", "normal"} and item.get("margin_status") != margin_status:
            return False
        if stock_status in {"short", "normal"} and item.get("stock_status") != stock_status:
            return False
        return True

    def _build_alert_item(
        self,
        alert_type: str,
        label: str,
        row: dict[str, Any],
        detail: str,
        tone: str,
    ) -> dict[str, Any]:
        return {
            "type": alert_type,
            "label": label,
            "tone": tone,
            "title": str(row.get("seller_sku_adj") or "-"),
            "subtitle": f"{row.get('seller_name_new') or '-'} / {row.get('country') or '-'}",
            "store": str(row.get("seller_name_new") or "-"),
            "country": str(row.get("country") or "-"),
            "detail": detail,
            "keyword": str(row.get("seller_sku_adj") or ""),
        }

    def _fetch_goal_gap_breakdown(self, conn, annual_goal: dict[str, Any] | None) -> dict[str, Any]:
        if not annual_goal:
            return {"summary": None, "groups": {"country": [], "store": []}}
        goal_year = to_int(annual_goal.get("goal_year"))
        actual = to_float(annual_goal.get("sales_amount_ytd"))
        target = to_float(annual_goal.get("target_amount_to_date"))
        gap = round(target - actual, 2)
        groups: dict[str, list[dict[str, Any]]] = {"country": [], "store": []}
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select max(snapshot_date) as snapshot_date
                    from dashboard_goal_dimension_snapshot
                    where goal_year = %(goal_year)s
                    """,
                    {"goal_year": goal_year},
                )
                snapshot_date = (cursor.fetchone() or {}).get("snapshot_date")
                if snapshot_date:
                    cursor.execute(
                        """
                        select
                            dimension_type,
                            dimension_name,
                            data_end_date,
                            sales_amount_ytd,
                            sales_qty_ytd,
                            order_gross_profit_ytd,
                            order_gross_margin_ytd
                        from dashboard_goal_dimension_snapshot
                        where goal_year = %(goal_year)s
                          and snapshot_date = %(snapshot_date)s
                          and dimension_type in ('country', 'store')
                        order by dimension_type, sales_amount_ytd desc
                        """,
                        {"goal_year": goal_year, "snapshot_date": snapshot_date},
                    )
                    for row in cursor.fetchall():
                        dimension_type = row.get("dimension_type")
                        if dimension_type not in groups:
                            continue
                        sales = to_float(row.get("sales_amount_ytd"))
                        share = sales / actual if actual else 0
                        groups[dimension_type].append(
                            {
                                "name": row.get("dimension_name") or "-",
                                "sales_amount": round(sales, 2),
                                "sales_qty": round(to_float(row.get("sales_qty_ytd")), 2),
                                "margin": round(to_float(row.get("order_gross_margin_ytd")), 4),
                                "share": round(share, 4),
                                "gap_contribution": round(gap * share, 2),
                            }
                        )
        except pymysql.err.ProgrammingError as exc:
            if not (exc.args and exc.args[0] == 1146):
                raise

        return {
            "summary": {
                "year": goal_year,
                "data_end_date": format_day(annual_goal.get("data_end_date")),
                "actual": round(actual, 2),
                "target_to_date": round(target, 2),
                "gap": gap,
                "ratio": round(actual / target, 4) if target else 0,
                "method": "说明：当前没有国家/店铺独立目标，这里仅按 2026 年实际销售占比分摊总目标缺口，用来判断缺口主要关联的业务板块，不代表该国家或店铺自己的目标完成率。",
            },
            "groups": {key: value[:8] for key, value in groups.items()},
        }

    def _fetch_item_trend(self, conn, row: dict[str, Any], period_end: date, trend_days: int) -> dict[str, Any]:
        days = max(7, min(30, trend_days))
        trend_start = period_end - timedelta(days=days - 1)
        labels = iter_days(trend_start, period_end)
        params = {
            "trend_start": trend_start,
            "trend_end": period_end,
            "item_key": row.get("item_key"),
        }
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select dt_date, sum(sales_amount) as sales_amount
                from dashboard_product_performance_daily
                where dt_date between %(trend_start)s and %(trend_end)s
                  and item_key = %(item_key)s
                group by dt_date
                """,
                params,
            )
            by_date = {item["dt_date"]: to_float(item.get("sales_amount")) for item in cursor.fetchall()}

        values = [round(by_date.get(day, 0.0), 2) for day in labels]
        total_revenue = round(sum(values), 2)
        average_revenue = round(total_revenue / max(days, 1), 2)
        first_value = values[0] if values else 0
        latest_value = values[-1] if values else 0
        change_ratio = ((latest_value - first_value) / first_value) if first_value else (1 if latest_value > 0 else 0)
        return {
            "days": days,
            "labels": [format_day(day) for day in labels],
            "values": values,
            "total_revenue": total_revenue,
            "average_revenue": average_revenue,
            "latest_revenue": latest_value,
            "change_ratio": round(change_ratio, 4),
        }

    def _build_summary_from_stats(self, stats: dict[str, float], matrix: dict[str, Any]) -> str:
        combo = 0
        for cell in matrix.get("cells", []):
            if cell.get("margin_band") == "毛利率 >35%" and cell.get("daily_sales_band") == "日销 <1":
                combo = int(cell.get("count") or 0)
                break
        return (
            f"当前筛选共 {int(stats['sku_count'])} 个 SKU，"
            f"其中“毛利率 >35% 且日销 <1”有 {combo} 个，"
            f"超限价 {int(stats['over_limit_count'])} 个。"
        )

    def _build_goal_overview_from_stats(self, stats: dict[str, float]) -> dict[str, Any]:
        current_revenue = round(stats["sales_amount"], 2)
        current_margin = round(stats["order_gross_margin"], 4)
        today = date.today()
        year_days = days_in_year(today)
        current_day = day_of_year(today)
        target_by_today = round(SALES_GOAL / year_days * SALES_GOAL_BUFFER * current_day, 2)
        return {
            "sales_goal": {
                "title": "销售额目标",
                "current_value": current_revenue,
                "target_value": SALES_GOAL,
                "ratio": round(current_revenue / SALES_GOAL, 4) if SALES_GOAL else 0,
                "detail_text": "当前筛选周期销售额 / 年度目标",
                "delta_text": f"距离目标还差 {SALES_GOAL - current_revenue:,.2f}",
            },
            "current_goal": {
                "title": "当前目标情况",
                "current_value": current_revenue,
                "target_value": target_by_today,
                "ratio": round(current_revenue / target_by_today, 4) if target_by_today else 0,
                "detail_text": f"{format_day(today)} / 1.35 亿 / {year_days} * 1.01 * 第 {current_day} 天",
                "delta_text": f"距离今日进度差 {target_by_today - current_revenue:,.2f}",
            },
            "margin_goal": {
                "title": "毛利率目标",
                "current_value": current_margin,
                "target_value": MARGIN_GOAL,
                "ratio": round(current_margin / MARGIN_GOAL, 4) if MARGIN_GOAL else 0,
                "detail_text": "当前筛选周期订单毛利率 / 目标值",
                "delta_text": f"距离目标差 {(MARGIN_GOAL - current_margin) * 100:.1f} 个百分点",
            },
        }

    def _fetch_latest_annual_goal(self, conn) -> dict[str, Any] | None:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        snapshot_date,
                        goal_year,
                        data_end_date,
                        sales_goal,
                        margin_goal,
                        sales_goal_buffer,
                        sales_amount_ytd,
                        order_gross_margin_ytd,
                        target_amount_to_date,
                        sales_goal_ratio,
                        current_goal_ratio
                    from dashboard_annual_goal_snapshot
                    order by snapshot_date desc, goal_year desc
                    limit 1
                    """
                )
                return cursor.fetchone()
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return None
            raise

    def _build_goal_overview_from_annual(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot_date = row.get("snapshot_date") or date.today()
        data_end_date = row.get("data_end_date") or snapshot_date
        sales_goal = to_float(row.get("sales_goal"))
        margin_goal = to_float(row.get("margin_goal"))
        current_revenue = round(to_float(row.get("sales_amount_ytd")), 2)
        current_margin = round(to_float(row.get("order_gross_margin_ytd")), 4)
        target_by_today = round(to_float(row.get("target_amount_to_date")), 2)
        sales_goal_ratio = round(to_float(row.get("sales_goal_ratio")), 4)
        current_goal_ratio = round(to_float(row.get("current_goal_ratio")), 4)
        return {
            "sales_goal": {
                "title": "销售额目标",
                "current_value": current_revenue,
                "target_value": sales_goal,
                "ratio": sales_goal_ratio,
                "detail_text": f"{row.get('goal_year')} 年累计销售额 / 年度目标",
                "delta_text": f"距离目标还差 {sales_goal - current_revenue:,.2f}",
            },
            "current_goal": {
                "title": "当前目标情况",
                "current_value": current_revenue,
                "target_value": target_by_today,
                "ratio": current_goal_ratio,
                "detail_text": f"{row.get('goal_year')} 年月度目标累计 / 截至 {format_day(data_end_date)}",
                "delta_text": f"数据截至 {format_day(data_end_date)}，距离累计目标差 {target_by_today - current_revenue:,.2f}",
            },
            "margin_goal": {
                "title": "毛利率目标",
                "current_value": current_margin,
                "target_value": margin_goal,
                "ratio": round(current_margin / margin_goal, 4) if margin_goal else 0,
                "detail_text": f"{row.get('goal_year')} 年累计订单毛利率 / 目标值",
                "delta_text": f"距离目标差 {(margin_goal - current_margin) * 100:.1f} 个百分点",
            },
        }

    def _build_kpis_from_stats(self, stats: dict[str, float], series: dict[str, list[float]]) -> list[dict[str, Any]]:
        revenue = round(stats["sales_amount"], 2)
        avg_daily_sales = round(stats["avg_daily_sales"], 2)
        avg_margin = round(stats["order_gross_margin"], 4)
        sellable = round(stats["fba_sellable_inventory"])
        in_transit = round(stats["actual_in_transit"])
        unsellable = round(stats["unsellable_inventory"])
        total_inventory = max(round(stats["fba_total_inventory"]), 1)
        ad_spend = round(stats["ad_spend"], 2)
        ad_sales = round(stats["ad_sales"], 2)
        acos = round(stats["acos"], 4)
        tacos = round(stats["tacos"], 4)
        trend_size = max(len(series.get("revenue", [])), 2)
        sellable_series = [sellable for _ in range(trend_size)]
        in_transit_series = [in_transit for _ in range(trend_size)]
        unsellable_series = [unsellable for _ in range(trend_size)]

        return [
            self._kpi("active_sku", "在售产品数", stats["sku_count"], "number", "结构", "当前筛选下的产品数", self._ratio_text(stats["sku_count"], max(stats["sku_count"], 1)), "positive", "#1769e0", series["active_sku"]),
            self._kpi("revenue", "区间销售额", revenue, "currency", "规模", "当前区间累计销售额", self._slope_text(series["revenue"]), self._slope_tone(series["revenue"]), "#18a17d", series["revenue"]),
            self._kpi("avg_daily_sales", "平均日销", avg_daily_sales, "number", "日销", "当前周期总销量 / 周期天数", self._daily_sales_hint(avg_daily_sales), self._daily_sales_tone(avg_daily_sales), "#4b86df", series["daily_sales"]),
            self._kpi("avg_margin", "平均订单毛利率", avg_margin, "percent", "毛利", "当前周期订单毛利率", self._margin_hint(avg_margin), self._margin_tone(avg_margin), "#cf4f5f", series["margin"]),
            self._kpi("fba_sellable", "FBA 可售", sellable, "number", "库存", "当前筛选下 FBA 可售库存", "占总库存 " + format_percent(sellable / total_inventory), "positive", "#4b86df", sellable_series),
            self._kpi("actual_in_transit", "实际在途", in_transit, "number", "补货", "当前筛选下实际在途", "占总库存 " + format_percent(in_transit / total_inventory), "warning", "#18a17d", in_transit_series),
            self._kpi("unsellable", "不可售库存", unsellable, "number", "风险库存", "当前筛选下不可售库存", "占总库存 " + format_percent(unsellable / total_inventory), "negative", "#cf4f5f", unsellable_series),
            self._kpi("ad_spend", "广告花费", ad_spend, "currency", "广告", "当前区间广告花费", self._slope_text(series["ad_spend"]), self._slope_tone(series["ad_spend"]), "#d97706", series["ad_spend"]),
            self._kpi("acos", "ACOS", acos, "percent", "投放效率", "广告花费 / 广告销售额", self._slope_text(series["acos"]), self._slope_tone(series["acos"]), "#cf4f5f", series["acos"]),
            self._kpi("tacos", "TACOS", tacos, "percent", "营收占比", "广告花费 / 总销售额", self._slope_text(series["tacos"]), self._slope_tone(series["tacos"]), "#4b86df", series["tacos"]),
        ]

    def _build_summary(self, items: list[dict[str, Any]]) -> str:
        combo = len([item for item in items if item["margin_band"] == "毛利率 >35%" and item["daily_sales_band"] == "日销 <1"])
        over_limit = len([item for item in items if item["over_limit"]])
        return f"当前筛选共 {len(items)} 个 SKU，其中“毛利率 >35% 且日销 <1”有 {combo} 个，超限价 {over_limit} 个。"

    def _build_goal_overview(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        current_revenue = round(sum(item["scoped_revenue"] for item in items), 2)
        weighted_margin = self._weighted_margin(items)
        today = date.today()
        year_days = days_in_year(today)
        current_day = day_of_year(today)
        target_by_today = round(SALES_GOAL / year_days * SALES_GOAL_BUFFER * current_day, 2)
        return {
            "sales_goal": {
                "title": "销售额目标",
                "current_value": current_revenue,
                "target_value": SALES_GOAL,
                "ratio": round(current_revenue / SALES_GOAL, 4) if SALES_GOAL else 0,
                "detail_text": "当前筛选周期销售额 / 年度目标",
                "delta_text": f"距离目标还差 {SALES_GOAL - current_revenue:,.2f}",
            },
            "current_goal": {
                "title": "当前目标情况",
                "current_value": current_revenue,
                "target_value": target_by_today,
                "ratio": round(current_revenue / target_by_today, 4) if target_by_today else 0,
                "detail_text": f"{format_day(today)} / 1.35 亿 / {year_days} * 1.01 * 第 {current_day} 天",
                "delta_text": f"距离今日进度差 {target_by_today - current_revenue:,.2f}",
            },
            "margin_goal": {
                "title": "毛利率目标",
                "current_value": weighted_margin,
                "target_value": MARGIN_GOAL,
                "ratio": round(weighted_margin / MARGIN_GOAL, 4) if MARGIN_GOAL else 0,
                "detail_text": "当前筛选周期订单毛利率 / 目标值",
                "delta_text": f"距离目标差 {(MARGIN_GOAL - weighted_margin) * 100:.1f} 个百分点",
            },
        }

    def _build_kpis(self, items: list[dict[str, Any]], series: dict[str, list[float]]) -> list[dict[str, Any]]:
        revenue = round(sum(item["scoped_revenue"] for item in items), 2)
        avg_daily_sales = round(sum(item["daily_sales"] for item in items) / max(len(items), 1), 2)
        avg_margin = self._weighted_margin(items)
        sellable = sum(item["fba_sellable_inventory"] for item in items)
        in_transit = sum(item["actual_in_transit"] for item in items)
        unsellable = sum(item["unsellable_inventory"] for item in items)
        ad_spend = round(sum(item["ad_spend"] for item in items), 2)
        ad_sales = round(sum(item["ad_sales"] for item in items), 2)
        acos = round(ad_spend / ad_sales, 4) if ad_sales else 0
        tacos = round(ad_spend / revenue, 4) if revenue else 0
        total_inventory = max(sellable + in_transit + unsellable, 1)
        sellable_series = [sellable for _ in series["revenue"]]
        in_transit_series = [in_transit for _ in series["revenue"]]
        unsellable_series = [unsellable for _ in series["revenue"]]

        return [
            self._kpi("active_sku", "在售产品数", len(items), "number", "结构", "当前筛选下的产品数", self._ratio_text(len(items), max(len(items), 1)), "positive", "#1769e0", series["active_sku"]),
            self._kpi("revenue", "区间销售额", revenue, "currency", "规模", "当前区间累计销售额", self._slope_text(series["revenue"]), self._slope_tone(series["revenue"]), "#18a17d", series["revenue"]),
            self._kpi("avg_daily_sales", "平均日销", avg_daily_sales, "number", "日销", "当前样本平均日销", self._daily_sales_hint(avg_daily_sales), self._daily_sales_tone(avg_daily_sales), "#4b86df", series["daily_sales"]),
            self._kpi("avg_margin", "平均订单毛利率", avg_margin, "percent", "毛利", "当前样本订单毛利率", self._margin_hint(avg_margin), self._margin_tone(avg_margin), "#cf4f5f", series["margin"]),
            self._kpi("fba_sellable", "FBA 可售", sellable, "number", "库存", "当前筛选下 FBA 可售库存", "可售占比 " + format_percent(sellable / total_inventory), "positive", "#4b86df", sellable_series),
            self._kpi("actual_in_transit", "实际在途", in_transit, "number", "补货", "当前筛选下实际在途", self._ratio_text(in_transit, total_inventory), "warning", "#18a17d", in_transit_series),
            self._kpi("unsellable", "不可售库存", unsellable, "number", "风险库存", "当前筛选下不可售库存", self._ratio_text(unsellable, total_inventory), "negative", "#cf4f5f", unsellable_series),
            self._kpi("ad_spend", "广告花费", ad_spend, "currency", "广告", "当前区间广告花费", self._slope_text(series["ad_spend"]), self._slope_tone(series["ad_spend"]), "#d97706", series["ad_spend"]),
            self._kpi("acos", "ACOS", acos, "percent", "投放效率", "广告花费 / 广告销售额", self._slope_text(series["acos"]), self._slope_tone(series["acos"]), "#cf4f5f", series["acos"]),
            self._kpi("tacos", "TACOS", tacos, "percent", "营收占比", "广告花费 / 总销售额", self._slope_text(series["tacos"]), self._slope_tone(series["tacos"]), "#4b86df", series["tacos"]),
        ]

    def _kpi(
        self,
        key: str,
        label: str,
        value: float,
        value_type: str,
        mini_label: str,
        description: str,
        delta_text: str,
        delta_tone: str,
        color: str,
        series: list[float],
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "value": value,
            "type": value_type,
            "mini_label": mini_label,
            "description": description,
            "delta_text": delta_text,
            "delta_tone": delta_tone,
            "color": color,
            "series": series or [0],
        }

    def _build_band_chart(self, items: list[dict[str, Any]], bands: list[str], key: str) -> dict[str, Any]:
        counts = []
        for band in bands:
            band_items = [item for item in items if item[key] == band]
            counts.append(
                {
                    "name": band,
                    "value": len(band_items),
                    "over_limit": len([item for item in band_items if item["over_limit"]]),
                }
            )
        return {"items": counts}

    def _build_matrix(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        total = max(len(items), 1)
        cells = []
        for margin in MARGIN_BANDS:
            for sales in DAILY_SALES_BANDS:
                count = len([item for item in items if item["margin_band"] == margin and item["daily_sales_band"] == sales])
                cells.append(
                    {
                        "margin_band": margin,
                        "daily_sales_band": sales,
                        "count": count,
                        "ratio": round(count / total, 4),
                    }
                )
        return {
            "margin_bands": MARGIN_BANDS,
            "daily_sales_bands": DAILY_SALES_BANDS,
            "cells": cells,
        }

    def _weighted_margin(self, items: list[dict[str, Any]]) -> float:
        gross_profit = sum(item["scoped_revenue"] * item["order_gross_margin"] for item in items)
        revenue = sum(item["scoped_revenue"] for item in items)
        return round(gross_profit / revenue, 4) if revenue else 0

    def _ratio_text(self, value: float, total: float) -> str:
        return "占比 " + format_percent(value / total if total else 0)

    def _daily_sales_hint(self, value: float) -> str:
        if value > 5:
            return "整体偏高"
        if value >= 1:
            return "集中在 1-5"
        if value > 0:
            return "整体偏慢"
        return "基本无动销"

    def _daily_sales_tone(self, value: float) -> str:
        if value > 5:
            return "positive"
        if value >= 1:
            return "warning"
        return "negative"

    def _margin_hint(self, value: float) -> str:
        if value > 0.35:
            return "整体毛利高"
        if value >= 0.25:
            return "毛利结构稳"
        if value >= 0.15:
            return "毛利中位"
        if value >= 0.10:
            return "毛利偏低"
        if value >= 0:
            return "毛利较低"
        return "存在负毛利"

    def _margin_tone(self, value: float) -> str:
        if value >= 0.25:
            return "positive"
        if value >= 0.10:
            return "warning"
        return "negative"

    def _slope_text(self, series: list[float]) -> str:
        if len(series) < 2:
            return "走势平稳"
        half = max(1, len(series) // 2)
        first = sum(series[:half]) / half
        second = sum(series[half:]) / max(len(series[half:]), 1)
        ratio = ((second - first) / first) if first else 0
        if ratio >= 0.06:
            return "后半段抬升"
        if ratio <= -0.06:
            return "后半段承压"
        return "走势平稳"

    def _slope_tone(self, series: list[float]) -> str:
        label = self._slope_text(series)
        if label == "后半段抬升":
            return "positive"
        if label == "后半段承压":
            return "negative"
        return "warning"


dashboard_service = DashboardDbService()
