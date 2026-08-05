from __future__ import annotations

import base64
import configparser
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql

from etl.dashboard_daily_update import (
    PERIOD_PRESET_TABLES,
    SchemaConfig,
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
MATRIX_PERIOD_TABLE = "etl_datasync_test.dashboard_product_matrix_period_snapshot"
ALERT_COMPARISON_TABLE = "etl_datasync_test.dashboard_alert_comparison_snapshot"
ALERT_MONTHLY_METRIC_TABLE = "etl_datasync_test.dashboard_alert_monthly_metric_snapshot"
OPPORTUNITY_COMPARISON_TABLE = "etl_datasync_test.dashboard_opportunity_comparison_snapshot"
ALERT_DAY_COMPARISONS = {7: "d7", 14: "d14", 30: "d30", 60: "d60", 90: "d90"}
MARGIN_TRANSITION_LAYERS = ["\u65e0\u6bdb\u5229", "<0%", "0-10%", "10-15%", "15-25%", "25-35%", ">35%"]
SALES_ROLE_PERIOD_TABLE = "etl_datasync_test.dashboard_sales_role_period_snapshot"
SALES_ROLE_PERIODS = {"7d", "14d", "30d", "90d"}
SALES_ROLE_SNAPSHOT_CODE_MAP = {
    "star": "star",
    "potential": "potential",
    "dog": "incubation",
    "problem": "eliminate",
}
SALES_ROLE_OPTIONS = [
    {"key": "star", "label": "明星产品", "tone": "positive"},
    {"key": "potential", "label": "潜力产品", "tone": "warning"},
    {"key": "incubation", "label": "瘦狗产品", "tone": "info"},
    {"key": "eliminate", "label": "问题产品", "tone": "negative"},
]
SALES_ROLE_BY_KEY = {option["key"]: option for option in SALES_ROLE_OPTIONS}
SALES_ROLE_DAILY_SALES_BANDS = ["日销 0", "日销 <1", "日销 1-5", "日销 >5"]
SALES_ROLE_MARGIN_BANDS = ["<5%", "5%-10%", "10%-15%", "15%-25%", ">25%"]
SALES_ROLE_DAILY_LOW = Decimal("1")
SALES_ROLE_DAILY_HIGH = Decimal("5")
SALES_ROLE_MARGIN_5 = Decimal("0.05")
SALES_ROLE_MARGIN_10 = Decimal("0.10")
SALES_ROLE_MARGIN_15 = Decimal("0.15")
SALES_ROLE_MARGIN_25 = Decimal("0.25")
LIFECYCLE_DETAIL_TABLE = "dws_datasync.dws_标签详情表"
LIFECYCLE_TAG_TABLE = "dws_datasync.dws_标签表"
LIFECYCLE_PARENT_LABEL_ID = 2
LIFECYCLE_LABEL_IDS = [201, 202, 203, 204, 205]
LIFECYCLE_WINDOW_BY_ID = {
    201: {"key": "trial", "label": "测款期", "label_period": "上架≤30天", "window_days": 30, "tone": "info"},
    202: {"key": "new", "label": "新品期", "label_period": "上架31-120天", "window_days": 90, "tone": "positive"},
    203: {"key": "growth", "label": "成长期", "label_period": "上架121-300天", "window_days": 180, "tone": "warning"},
    204: {"key": "mature", "label": "成熟期", "label_period": "上架>300天", "window_days": 180, "tone": "primary"},
    205: {"key": "decline", "label": "衰退期", "label_period": "人工判断", "window_days": 180, "tone": "negative"},
}


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def classify_sales_role(daily_sales: Any, margin_rate: Any) -> dict[str, str]:
    daily = _to_decimal_or_none(daily_sales) or Decimal("0")
    margin = _to_decimal_or_none(margin_rate)
    if daily <= 0 or margin is None:
        return SALES_ROLE_BY_KEY["eliminate"]

    if daily > SALES_ROLE_DAILY_HIGH and margin > SALES_ROLE_MARGIN_15:
        return SALES_ROLE_BY_KEY["star"]
    if SALES_ROLE_DAILY_LOW <= daily <= SALES_ROLE_DAILY_HIGH and margin > SALES_ROLE_MARGIN_25:
        return SALES_ROLE_BY_KEY["star"]

    if daily > SALES_ROLE_DAILY_HIGH and SALES_ROLE_MARGIN_5 <= margin <= SALES_ROLE_MARGIN_15:
        return SALES_ROLE_BY_KEY["potential"]
    if SALES_ROLE_DAILY_LOW <= daily <= SALES_ROLE_DAILY_HIGH and SALES_ROLE_MARGIN_10 <= margin <= SALES_ROLE_MARGIN_25:
        return SALES_ROLE_BY_KEY["potential"]

    if SALES_ROLE_DAILY_LOW <= daily <= SALES_ROLE_DAILY_HIGH and SALES_ROLE_MARGIN_5 <= margin < SALES_ROLE_MARGIN_10:
        return SALES_ROLE_BY_KEY["incubation"]
    if daily < SALES_ROLE_DAILY_LOW and margin > SALES_ROLE_MARGIN_5:
        return SALES_ROLE_BY_KEY["incubation"]

    return SALES_ROLE_BY_KEY["eliminate"]


def sales_role_daily_sales_band(value: Any) -> str:
    daily = _to_decimal_or_none(value) or Decimal("0")
    if daily <= 0:
        return "日销 0"
    if daily < SALES_ROLE_DAILY_LOW:
        return "日销 <1"
    if daily <= SALES_ROLE_DAILY_HIGH:
        return "日销 1-5"
    return "日销 >5"


def sales_role_margin_band(value: Any) -> str:
    margin = _to_decimal_or_none(value)
    if margin is None or margin < SALES_ROLE_MARGIN_5:
        return "<5%"
    if margin < SALES_ROLE_MARGIN_10:
        return "5%-10%"
    if margin < SALES_ROLE_MARGIN_15:
        return "10%-15%"
    if margin < SALES_ROLE_MARGIN_25:
        return "15%-25%"
    return ">25%"


@dataclass(frozen=True)
class PeriodWindow:
    start_date: date
    end_date: date
    snapshot_date: date
    period_table: str = "etl_datasync_test.dashboard_product_period_90d_snapshot"
    period_code: str = "last_90_days"

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


def normalize_alert_comparison_code(comparison_code: str | None, compare_days: int | None = 7) -> str:
    code = str(comparison_code or "").strip()
    if code.startswith("d") and code[1:].isdigit() and int(code[1:]) in ALERT_DAY_COMPARISONS:
        return code
    try:
        days = int(compare_days or 7)
    except (TypeError, ValueError):
        days = 7
    if days >= 90:
        return "d90"
    if days >= 60:
        return "d60"
    if days >= 30:
        return "d30"
    if days >= 14:
        return "d14"
    return "d7"


def normalize_alert_month_code(month_code: str | None) -> str:
    code = str(month_code or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", code):
        return ""
    year, month = code.split("-", 1)
    if 1 <= int(month) <= 12:
        return f"{int(year):04d}-{int(month):02d}"
    return ""


def is_alert_month_mode(comparison_mode: str | None) -> bool:
    return str(comparison_mode or "").strip().lower() == "month"


def alert_compare_days_from_code(comparison_code: str) -> int:
    if comparison_code.startswith("d") and comparison_code[1:].isdigit():
        return int(comparison_code[1:])
    return 0


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


def compact_amount(value: float) -> str:
    amount = to_float(value)
    absolute = abs(amount)
    if absolute >= 100000000:
        return f"{amount / 100000000:.2f}亿"
    if absolute >= 10000:
        return f"{amount / 10000:.2f}万"
    return f"{amount:,.0f}"


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
        config = self._load_database_config()
        target_config = config["target"] if config.has_section("target") else {}
        source_config = config["source"] if config.has_section("source") else {}
        self.host = os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1"))
        self.host = os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", target_config.get("host", self.host)))
        self.port = int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306")))
        self.port = int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", target_config.get("port", str(self.port)))))
        self.user = os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", ""))
        self.user = os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", target_config.get("user", self.user)))
        self.password = os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
        self.password = os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", target_config.get("password", self.password)))
        self.database = os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test"))
        self.database = os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", target_config.get("database", self.database)))
        self.charset = os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4")
        self.charset = os.getenv("DASHBOARD_DB_CHARSET", target_config.get("charset", self.charset))
        self.source_host = os.getenv("DASHBOARD_SOURCE_DB_HOST", source_config.get("host", self.host))
        self.source_port = int(os.getenv("DASHBOARD_SOURCE_DB_PORT", source_config.get("port", str(self.port))))
        self.source_user = os.getenv("DASHBOARD_SOURCE_DB_USER", source_config.get("user", self.user))
        self.source_password = os.getenv("DASHBOARD_SOURCE_DB_PASSWORD", source_config.get("password", self.password))
        self.source_database = os.getenv("DASHBOARD_SOURCE_DB_NAME", source_config.get("database", "")) or None
        self.source_charset = os.getenv("DASHBOARD_SOURCE_DB_CHARSET", source_config.get("charset", self.charset))
        self.schemas = SchemaConfig(
            target_schema=os.getenv("DASHBOARD_TARGET_SCHEMA", self.database),
            etl_source_schema=self.database,
            dwd_source_schema=self.database,
            pricing_source_schema=self.database,
        )
        self._meta_cache: dict[str, Any] | None = None
        self._meta_cache_at: datetime | None = None

    def _load_database_config(self) -> configparser.ConfigParser:
        config = configparser.ConfigParser()
        config_path = Path(__file__).resolve().parents[2] / "config" / "database.ini"
        if config_path.exists():
            config.read(config_path, encoding="utf-8")
        return config

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

    def source_connect(self, autocommit: bool = True):
        return pymysql.connect(
            host=self.source_host,
            port=self.source_port,
            user=self.source_user,
            password=self.source_password,
            database=self.source_database,
            charset=self.source_charset,
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

    def get_sales_role_meta(self) -> dict[str, Any]:
        default_period = "30d"
        period_table = self._render_sales_role_period_table(default_period)
        country_categories: list[str] = []
        stores: list[str] = []
        lifecycle_labels = self._default_lifecycle_options()
        window = None
        try:
            with self.connect() as conn:
                lifecycle_labels = self._fetch_lifecycle_options(conn)
                window = self._latest_sales_role_window(conn, period_table, default_period)
                if window:
                    params = {
                        "snapshot_date": window["snapshot_date"],
                        "period_code": window["period_code"],
                        "period_start": window["period_start"],
                        "period_end": window["period_end"],
                    }
                    with conn.cursor() as cursor:
                        cursor.execute(
                            f"""
                            select distinct country_category
                            from {period_table}
                            where snapshot_date = %(snapshot_date)s
                              and period_code = %(period_code)s
                              and period_start = %(period_start)s
                              and period_end = %(period_end)s
                              and country_category is not null
                              and country_category != ''
                            order by country_category
                            """,
                            params,
                        )
                        country_categories = [row["country_category"] for row in cursor.fetchall()]
                        cursor.execute(
                            f"""
                            select distinct seller_name_new
                            from {period_table}
                            where snapshot_date = %(snapshot_date)s
                              and period_code = %(period_code)s
                              and period_start = %(period_start)s
                              and period_end = %(period_end)s
                              and seller_name_new is not null
                              and seller_name_new != ''
                            order by seller_name_new
                            """,
                            params,
                        )
                        stores = [row["seller_name_new"] for row in cursor.fetchall()]
        except pymysql.err.ProgrammingError as exc:
            if not (exc.args and exc.args[0] == 1146):
                raise

        return {
            "default_period": default_period,
            "periods": [
                {"key": "7d", "label": "7天"},
                {"key": "14d", "label": "14天"},
                {"key": "30d", "label": "30天"},
                {"key": "90d", "label": "90天"},
            ],
            "country_categories": country_categories,
            "stores": stores,
            "roles": SALES_ROLE_OPTIONS,
            "lifecycle_labels": lifecycle_labels,
            "daily_sales_bands": SALES_ROLE_DAILY_SALES_BANDS,
            "margin_bands": SALES_ROLE_MARGIN_BANDS,
            "window": self._sales_role_window_payload(window),
        }

    def get_sales_role_payload(
        self,
        period: str = "30d",
        country_category: str = "all",
        seller_name_new: str = "all",
        sales_role: str = "all",
        daily_sales_band: str = "all",
        margin_band: str = "all",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        sort_field: str = "sales_amount",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            period_table = self._render_sales_role_period_table(period)
            window = self._latest_sales_role_window(conn, period_table, period)
            base_rows = self._fetch_sales_role_base_rows(
                conn,
                period_table,
                window,
                country_category=country_category,
                seller_name_new=seller_name_new,
                keyword=keyword,
            )

        filtered_rows = self._filter_sales_role_rows(base_rows, sales_role, daily_sales_band, margin_band)
        self._sort_sales_role_rows(filtered_rows, sort_field, sort_dir)
        safe_page_size = max(10, min(5000, int(page_size or 20)))
        total = len(filtered_rows)
        total_pages = max(1, math.ceil(total / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        start = (safe_page - 1) * safe_page_size
        return {
            "meta": self.get_sales_role_meta(),
            "window": self._sales_role_window_payload(window),
            "summary": self._build_sales_role_summary(base_rows),
            "roles": self._build_sales_role_distribution(base_rows),
            "matrix": self._build_sales_role_matrix(base_rows),
            "rows": filtered_rows[start:start + safe_page_size],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
        }

    def get_sales_role_export_payload(
        self,
        period: str = "30d",
        country_category: str = "all",
        seller_name_new: str = "all",
        sales_role: str = "all",
        daily_sales_band: str = "all",
        margin_band: str = "all",
        keyword: str = "",
        sort_field: str = "sales_amount",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            period_table = self._render_sales_role_period_table(period)
            window = self._latest_sales_role_window(conn, period_table, period)
            base_rows = self._fetch_sales_role_base_rows(
                conn,
                period_table,
                window,
                country_category=country_category,
                seller_name_new=seller_name_new,
                keyword=keyword,
            )
        filtered_rows = self._filter_sales_role_rows(base_rows, sales_role, daily_sales_band, margin_band)
        self._sort_sales_role_rows(filtered_rows, sort_field, sort_dir)
        return {"window": self._sales_role_window_payload(window), "rows": filtered_rows}

    def get_sales_role_lifecycle_payload(
        self,
        period: str = "30d",
        country_category: str = "all",
        seller_name_new: str = "all",
        lifecycle_label: str = "all",
        sales_role: str = "all",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        sort_field: str = "sales_amount",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            lifecycle_options = self._fetch_lifecycle_options(conn)
            period_table = self._render_sales_role_period_table(period)
            role_window = self._latest_sales_role_window(conn, period_table, period)
            lifecycle_date = self._latest_lifecycle_data_date(conn)
            base_rows = self._fetch_sales_role_lifecycle_rows(
                conn,
                period_table,
                role_window,
                lifecycle_date,
                lifecycle_options,
                country_category=country_category,
                seller_name_new=seller_name_new,
                keyword=keyword,
            )

        filtered_rows = self._filter_sales_role_lifecycle_rows(base_rows, lifecycle_label, sales_role)
        self._sort_sales_role_lifecycle_rows(filtered_rows, sort_field, sort_dir)
        safe_page_size = max(10, min(5000, int(page_size or 20)))
        total = len(filtered_rows)
        total_pages = max(1, math.ceil(total / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        start = (safe_page - 1) * safe_page_size
        return {
            "meta": {**self.get_sales_role_meta(), "lifecycle_labels": lifecycle_options},
            "window": {
                "lifecycle_data_date": format_day(lifecycle_date) if lifecycle_date else "",
                "sales_role": self._sales_role_window_payload(role_window),
                "label": f"生命周期标签：{format_day(lifecycle_date)}" if lifecycle_date else "暂无生命周期标签数据",
            },
            "summary": self._build_sales_role_lifecycle_summary(base_rows),
            "lifecycle_distribution": self._build_sales_role_lifecycle_distribution(base_rows, lifecycle_options),
            "lifecycle_role_matrix": self._build_sales_role_lifecycle_matrix(base_rows, lifecycle_options),
            "rows": filtered_rows[start:start + safe_page_size],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
        }

    def get_sales_role_lifecycle_export_payload(
        self,
        period: str = "30d",
        country_category: str = "all",
        seller_name_new: str = "all",
        lifecycle_label: str = "all",
        sales_role: str = "all",
        keyword: str = "",
        sort_field: str = "sales_amount",
        sort_dir: str = "desc",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            lifecycle_options = self._fetch_lifecycle_options(conn)
            period_table = self._render_sales_role_period_table(period)
            role_window = self._latest_sales_role_window(conn, period_table, period)
            lifecycle_date = self._latest_lifecycle_data_date(conn)
            base_rows = self._fetch_sales_role_lifecycle_rows(
                conn,
                period_table,
                role_window,
                lifecycle_date,
                lifecycle_options,
                country_category=country_category,
                seller_name_new=seller_name_new,
                keyword=keyword,
            )
        filtered_rows = self._filter_sales_role_lifecycle_rows(base_rows, lifecycle_label, sales_role)
        self._sort_sales_role_lifecycle_rows(filtered_rows, sort_field, sort_dir)
        return {
            "window": {
                "lifecycle_data_date": format_day(lifecycle_date) if lifecycle_date else "",
                "sales_role": self._sales_role_window_payload(role_window),
            },
            "rows": filtered_rows,
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

    def _sort_items(
        self,
        items: list[dict[str, Any]],
        sort_field: str,
        sort_dir: str,
        field_map: dict[str, str],
        default: list[tuple[str, bool]],
    ) -> None:
        sort_key = str(sort_field or "").strip()
        descending = str(sort_dir or "").lower() == "desc"
        mapped_key = field_map.get(sort_key)

        def normalized(value: Any) -> tuple[int, Any]:
            if value is None or value == "":
                return (1, "")
            if isinstance(value, (int, float)):
                return (0, float(value))
            return (0, str(value))

        if mapped_key:
            items.sort(key=lambda item: normalized(item.get(mapped_key)), reverse=descending)
            return

        for key, is_desc in reversed(default):
            items.sort(key=lambda item: normalized(item.get(key)), reverse=is_desc)

    def get_alerts_payload(
        self,
        filters: dict[str, Any],
        alert_type: str = "all",
        compare_days: int = 7,
        comparison_code: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
        sort_field: str = "",
        sort_dir: str = "",
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
                comparison_code=comparison_code,
                comparison_mode=comparison_mode,
                previous_month=previous_month,
                recent_month=recent_month,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
                transition_filter=transition_filter,
            )

        payload["total_count"] = len(payload["items"])
        self._sort_items(
            payload["items"],
            sort_field,
            sort_dir,
            {
                "label": "label",
                "title": "title",
                "store": "store",
                "country": "country",
                "sales_text": "recent_qty",
                "recent_qty": "recent_qty",
                "recent_daily_sales": "recent_daily_sales",
                "previous_qty": "previous_qty",
                "previous_daily_sales": "previous_daily_sales",
                "rank_text": "rank_delta",
                "margin_text": "recent_margin",
                "stock_text": "sellable_days",
            },
            default=[("priority", False), ("title", False)],
        )
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
        comparison_code: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            payload = self._fetch_alert_center(
                conn,
                window,
                filters,
                compare_days=compare_days,
                comparison_code=comparison_code,
                comparison_mode=comparison_mode,
                previous_month=previous_month,
                recent_month=recent_month,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
                transition_filter=transition_filter,
            )
        return {
            "items": payload["items"],
            "window": payload["window"],
            "comparison_window": payload["comparison_window"],
            "compare_days": payload["compare_days"],
            "comparison_code": payload.get("comparison_code"),
            "comparison_type": payload.get("comparison_type"),
            "comparison_label": payload.get("comparison_label"),
            "comparison_mode": payload.get("comparison_mode"),
            "previous_month": payload.get("previous_month"),
            "recent_month": payload.get("recent_month"),
        }

    def get_opportunities_payload(
        self,
        filters: dict[str, Any],
        opportunity_type: str = "all",
        compare_days: int = 14,
        comparison_code: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        stock_status: str = "all",
        transition_filter: str = "",
        sort_field: str = "",
        sort_dir: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            if is_alert_month_mode(comparison_mode):
                payload = self._fetch_opportunity_pool_monthly(
                    conn,
                    filters,
                    previous_month=previous_month,
                    recent_month=recent_month,
                    opportunity_type=opportunity_type,
                    stock_status=stock_status,
                    transition_filter=transition_filter,
                )
            else:
                selected_code = normalize_alert_comparison_code(comparison_code, compare_days)
                compare_days = alert_compare_days_from_code(selected_code) or compare_days
                available_months = self._fetch_alert_month_options(conn)
                payload = self._fetch_opportunity_pool_snapshot(
                    conn,
                    filters,
                    comparison_code=selected_code,
                    compare_days=compare_days,
                    opportunity_type=opportunity_type,
                    stock_status=stock_status,
                    transition_filter=transition_filter,
                    available_months=available_months,
                )
                if payload is None:
                    payload = self._fetch_opportunity_pool_precomputed(
                        conn,
                        filters,
                        comparison_code=selected_code,
                        compare_days=compare_days,
                        opportunity_type=opportunity_type,
                        stock_status=stock_status,
                        transition_filter=transition_filter,
                    )

        total = len(payload["items"])
        self._sort_items(
            payload["items"],
            sort_field,
            sort_dir,
            {
                "label": "label",
                "score": "score",
                "msku": "msku",
                "store": "store",
                "country": "country",
                "daily_sales": "daily_sales",
                "scoped_revenue": "scoped_revenue",
                "rank_sessions": "rank_delta",
                "stock": "sellable_days",
                "ad": "tacos",
                "price": "current_price",
            },
            default=[("score", True), ("scoped_revenue", True), ("msku", False)],
        )
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
        comparison_code: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            if is_alert_month_mode(comparison_mode):
                return self._fetch_opportunity_pool_monthly(
                    conn,
                    filters,
                    previous_month=previous_month,
                    recent_month=recent_month,
                    opportunity_type=opportunity_type,
                    stock_status=stock_status,
                    transition_filter=transition_filter,
                )
            selected_code = normalize_alert_comparison_code(comparison_code, compare_days)
            compare_days = alert_compare_days_from_code(selected_code) or compare_days
            payload = self._fetch_opportunity_pool_snapshot(
                conn,
                filters,
                comparison_code=selected_code,
                compare_days=compare_days,
                opportunity_type=opportunity_type,
                stock_status=stock_status,
                transition_filter=transition_filter,
            )
            if payload is not None:
                return payload
            return self._fetch_opportunity_pool_precomputed(
                conn,
                filters,
                comparison_code=selected_code,
                compare_days=compare_days,
                opportunity_type=opportunity_type,
                stock_status=stock_status,
                transition_filter=transition_filter,
            )

    def get_inventory_weekly_overview(self, filters: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            weeks = self._fetch_inventory_weekly_trends(conn, filters)
        return self._build_inventory_weekly_overview(weeks)

    def get_inventory_weekly_trends(self, filters: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            weeks = self._fetch_inventory_weekly_trends(conn, filters)
        return {
            "metrics": self._inventory_metric_defs(),
            "weeks": weeks,
            "overview": self._build_inventory_weekly_overview(weeks),
        }

    def get_inventory_weekly_details(
        self,
        filters: dict[str, Any],
        warning_status: str = "all",
        metric: str = "all",
        sort_field: str = "",
        sort_dir: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            weeks = self._fetch_inventory_weekly_trends(conn, filters)
            warning_weeks = {
                week["week_start"]
                for week in weeks
                if week.get("warning")
                and (metric == "all" or metric in week.get("warning_metrics", []))
            }
            rows, total = self._fetch_inventory_weekly_detail_rows(
                conn,
                filters,
                warning_status=warning_status,
                warning_weeks=warning_weeks,
                sort_field=sort_field,
                sort_dir=sort_dir,
                page=page,
                page_size=page_size,
            )

        total_pages = max(1, math.ceil(total / max(page_size, 1)))
        safe_page = min(max(page, 1), total_pages)
        return {
            "metrics": self._inventory_metric_defs(),
            "items": [self._build_inventory_weekly_detail_item(row, weeks, metric) for row in rows],
            "total": total,
            "page": safe_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "warning_status": warning_status,
            "metric": metric,
            "overview": self._build_inventory_weekly_overview(weeks),
        }

    def get_inventory_weekly_export_payload(
        self,
        filters: dict[str, Any],
        warning_status: str = "all",
        metric: str = "all",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            weeks = self._fetch_inventory_weekly_trends(conn, filters)
            warning_weeks = {
                week["week_start"]
                for week in weeks
                if week.get("warning")
                and (metric == "all" or metric in week.get("warning_metrics", []))
            }
            rows, total = self._fetch_inventory_weekly_detail_rows(
                conn,
                filters,
                warning_status=warning_status,
                warning_weeks=warning_weeks,
                page=1,
                page_size=50000,
            )
        return {
            "items": [self._build_inventory_weekly_detail_item(row, weeks, metric) for row in rows],
            "total": total,
            "overview": self._build_inventory_weekly_overview(weeks),
        }

    def _inventory_metric_defs(self) -> list[dict[str, str]]:
        return [
            {"key": "available", "label": "可用", "color": "#2563eb"},
            {"key": "transit", "label": "在途", "color": "#14a386"},
            {"key": "warehouse", "label": "在仓", "color": "#d97706"},
            {"key": "plan", "label": "采购", "color": "#7c3aed"},
        ]

    def _inventory_weekly_table(self) -> str:
        return render_sql("etl_datasync_test.dashboard_inventory_weekly_snapshot", self.schemas)

    def _inventory_weekly_where(
        self,
        filters: dict[str, Any],
        alias: str = "w",
        prefix: str = "",
    ) -> tuple[str, dict[str, Any]]:
        conditions = ["1=1"]
        params: dict[str, Any] = {}
        start_date = parse_day(filters.get("start_date"))
        end_date = parse_day(filters.get("end_date"))
        if start_date:
            conditions.append(f"{alias}.week_start >= %({prefix}start_date)s")
            params[f"{prefix}start_date"] = start_date
        if end_date:
            conditions.append(f"{alias}.week_start <= %({prefix}end_date)s")
            params[f"{prefix}end_date"] = end_date
        site = filters.get("site")
        if site and site != "all":
            conditions.append(f"{alias}.country_category = %({prefix}site)s")
            params[f"{prefix}site"] = site
        store = filters.get("store")
        if store and store != "all":
            conditions.append(f"{alias}.seller_name_new = %({prefix}store)s")
            params[f"{prefix}store"] = store
        keyword = str(filters.get("keyword") or "").strip()
        if keyword:
            conditions.append(
                f"({alias}.seller_sku_adj like %({prefix}keyword_like)s "
                f"or {alias}.seller_name_new like %({prefix}keyword_like)s "
                f"or {alias}.country_category like %({prefix}keyword_like)s)"
            )
            params[f"{prefix}keyword_like"] = f"%{keyword}%"
        return " and ".join(conditions), params

    def _fetch_inventory_weekly_trends(self, conn, filters: dict[str, Any]) -> list[dict[str, Any]]:
        table = self._inventory_weekly_table()
        where_sql, params = self._inventory_weekly_where(filters, alias="w")
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    w.week_start,
                    w.week_end,
                    max(w.snapshot_date) as snapshot_date,
                    sum(w.available_quantity) as available_quantity,
                    sum(w.available_cost) as available_cost,
                    sum(w.transit_quantity) as transit_quantity,
                    sum(w.transit_cost) as transit_cost,
                    sum(w.warehouse_quantity) as warehouse_quantity,
                    sum(w.warehouse_cost) as warehouse_cost,
                    sum(w.plan_quantity) as plan_quantity,
                    sum(w.plan_cost) as plan_cost,
                    count(*) as sku_count
                from {table} w
                where {where_sql}
                group by w.week_start, w.week_end
                order by w.week_start
                """,
                params,
            )
            rows = cursor.fetchall()

        weeks: list[dict[str, Any]] = []
        rate_history: dict[str, list[float]] = {}
        for row in rows:
            week = {
                "week_start": format_day(row["week_start"]),
                "week_end": format_day(row["week_end"]),
                "snapshot_date": format_day(row["snapshot_date"]),
                "sku_count": to_int(row.get("sku_count")),
                "metrics": {},
                "warning": False,
                "warning_metrics": [],
            }
            for metric in self._inventory_metric_defs():
                key = metric["key"]
                quantity = to_float(row.get(f"{key}_quantity"))
                cost = to_float(row.get(f"{key}_cost"))
                previous_week = weeks[-1] if weeks else None
                previous_quantity = (
                    to_float(previous_week["metrics"][key]["quantity"])
                    if previous_week and key in previous_week["metrics"]
                    else None
                )
                previous_cost = (
                    to_float(previous_week["metrics"][key]["cost"])
                    if previous_week and key in previous_week["metrics"]
                    else None
                )
                quantity_rate = self._safe_rate(quantity, previous_quantity)
                cost_rate = self._safe_rate(cost, previous_cost)
                history = rate_history.setdefault(key, [])
                historical_volatility = sum(history) / len(history) if history else 0
                warning = any(
                    abs(rate) > historical_volatility + 0.05
                    for rate in (quantity_rate, cost_rate)
                    if rate is not None
                )
                if quantity_rate is not None:
                    history.append(abs(quantity_rate))
                if cost_rate is not None:
                    history.append(abs(cost_rate))
                if warning:
                    week["warning"] = True
                    week["warning_metrics"].append(key)
                week["metrics"][key] = {
                    "quantity": round(quantity, 2),
                    "cost": round(cost, 2),
                    "previous_quantity": round(previous_quantity, 2) if previous_quantity is not None else None,
                    "previous_cost": round(previous_cost, 2) if previous_cost is not None else None,
                    "quantity_rate": round(quantity_rate, 4) if quantity_rate is not None else None,
                    "cost_rate": round(cost_rate, 4) if cost_rate is not None else None,
                    "historical_volatility": round(historical_volatility, 4),
                    "warning": warning,
                }
            weeks.append(week)
        return weeks

    def _safe_rate(self, current: float, previous: float | None) -> float | None:
        if previous is None or abs(previous) < 0.000001:
            return None
        return (current - previous) / abs(previous)

    def _build_inventory_weekly_overview(self, weeks: list[dict[str, Any]]) -> dict[str, Any]:
        if not weeks:
            return {"latest_week": None, "cards": [], "warning_count": 0, "warning_metrics": []}
        latest = weeks[-1]
        cards = []
        for metric in self._inventory_metric_defs():
            key = metric["key"]
            value = latest["metrics"].get(key, {})
            cards.append(
                {
                    "key": key,
                    "label": metric["label"],
                    "color": metric["color"],
                    "quantity": value.get("quantity", 0),
                    "cost": value.get("cost", 0),
                    "quantity_rate": value.get("quantity_rate"),
                    "cost_rate": value.get("cost_rate"),
                    "warning": bool(value.get("warning")),
                }
            )
        return {
            "latest_week": {
                "week_start": latest["week_start"],
                "week_end": latest["week_end"],
                "snapshot_date": latest["snapshot_date"],
                "sku_count": latest.get("sku_count", 0),
            },
            "cards": cards,
            "warning_count": sum(1 for week in weeks if week.get("warning")),
            "warning_metrics": latest.get("warning_metrics", []),
        }

    def _fetch_inventory_weekly_detail_rows(
        self,
        conn,
        filters: dict[str, Any],
        warning_status: str,
        warning_weeks: set[str],
        sort_field: str,
        sort_dir: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        table = self._inventory_weekly_table()
        where_sql, params = self._inventory_weekly_where(filters, alias="w")
        where_sql += """
            and (
                coalesce(w.available_quantity, 0) <> 0
                or coalesce(w.available_cost, 0) <> 0
                or coalesce(w.transit_quantity, 0) <> 0
                or coalesce(w.transit_cost, 0) <> 0
                or coalesce(w.warehouse_quantity, 0) <> 0
                or coalesce(w.warehouse_cost, 0) <> 0
                or coalesce(w.plan_quantity, 0) <> 0
                or coalesce(w.plan_cost, 0) <> 0
            )
        """
        if warning_status == "warning":
            if not warning_weeks:
                return [], 0
            placeholders = []
            for index, week_start in enumerate(sorted(warning_weeks)):
                key = f"warning_week_{index}"
                placeholders.append(f"%({key})s")
                params[key] = week_start
            where_sql += f" and w.week_start in ({', '.join(placeholders)})"
        safe_page_size = max(10, min(100, int(page_size or 20)))
        safe_page = max(1, int(page or 1))
        params["limit"] = safe_page_size
        params["offset"] = (safe_page - 1) * safe_page_size
        order_sql = self._inventory_weekly_order_sql(sort_field, sort_dir)
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) as total from {table} w where {where_sql}", params)
            total = to_int((cursor.fetchone() or {}).get("total"))
            cursor.execute(
                f"""
                select
                    w.week_start,
                    w.week_end,
                    w.snapshot_date,
                    w.country_category,
                    w.seller_name_new,
                    w.seller_sku_adj,
                    w.available_quantity,
                    w.available_cost,
                    w.transit_quantity,
                    w.transit_cost,
                    w.warehouse_quantity,
                    w.warehouse_cost,
                    w.plan_quantity,
                    w.plan_cost
                from {table} w
                where {where_sql}
                order by {order_sql}
                limit %(limit)s offset %(offset)s
                """,
                params,
            )
            rows = cursor.fetchall()
        return rows, total

    def _inventory_weekly_order_sql(self, sort_field: str, sort_dir: str) -> str:
        direction = "asc" if str(sort_dir or "").lower() == "asc" else "desc"
        sort_key = str(sort_field or "").strip()
        sortable_fields = {
            "week_start": "w.week_start",
            "site": "coalesce(w.country_category, '')",
            "store": "coalesce(w.seller_name_new, '')",
            "msku": "coalesce(w.seller_sku_adj, '')",
            "available": "coalesce(w.available_quantity, 0)",
            "transit": "coalesce(w.transit_quantity, 0)",
            "warehouse": "coalesce(w.warehouse_quantity, 0)",
            "plan": "coalesce(w.plan_quantity, 0)",
            "available_cost": "coalesce(w.available_cost, 0)",
            "transit_cost": "coalesce(w.transit_cost, 0)",
            "warehouse_cost": "coalesce(w.warehouse_cost, 0)",
            "plan_cost": "coalesce(w.plan_cost, 0)",
        }
        expression = sortable_fields.get(sort_key)
        if not expression:
            return "w.week_start desc, w.seller_name_new asc, w.seller_sku_adj asc"
        return f"{expression} {direction}, w.week_start desc, w.seller_name_new asc, w.seller_sku_adj asc"

    def _build_inventory_weekly_detail_item(
        self,
        row: dict[str, Any],
        weeks: list[dict[str, Any]],
        selected_metric: str,
    ) -> dict[str, Any]:
        week_start = format_day(row["week_start"])
        week_lookup = {week["week_start"]: week for week in weeks}
        week = week_lookup.get(week_start, {})
        warning_metrics = week.get("warning_metrics", [])
        if selected_metric != "all":
            warning_metrics = [key for key in warning_metrics if key == selected_metric]
        return {
            "week_start": week_start,
            "week_end": format_day(row["week_end"]),
            "snapshot_date": format_day(row["snapshot_date"]),
            "site": str(row.get("country_category") or "-"),
            "store": str(row.get("seller_name_new") or "-"),
            "msku": str(row.get("seller_sku_adj") or "-"),
            "available_quantity": round(to_float(row.get("available_quantity")), 2),
            "available_cost": round(to_float(row.get("available_cost")), 2),
            "transit_quantity": round(to_float(row.get("transit_quantity")), 2),
            "transit_cost": round(to_float(row.get("transit_cost")), 2),
            "warehouse_quantity": round(to_float(row.get("warehouse_quantity")), 2),
            "warehouse_cost": round(to_float(row.get("warehouse_cost")), 2),
            "plan_quantity": round(to_float(row.get("plan_quantity")), 2),
            "plan_cost": round(to_float(row.get("plan_cost")), 2),
            "warning": bool(warning_metrics),
            "warning_metrics": warning_metrics,
        }

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

    def get_detail_payload(
        self,
        filters: dict[str, Any],
        page: int,
        page_size: int,
        sort_field: str = "",
        sort_dir: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            window = self._resolve_window(conn, filters)
            total = self._count_period_items(conn, window, filters)
            total_pages = max(1, math.ceil(total / page_size))
            safe_page = min(max(page, 1), total_pages)
            rows = self._fetch_period_items(
                conn,
                window,
                filters,
                limit=page_size,
                offset=(safe_page - 1) * page_size,
                sort_field=sort_field,
                sort_dir=sort_dir,
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
            selected_table = self._preset_table_for_range(bounds["max_date"], period_start, period_end)
            if selected_table is None:
                return {"error": "not_found"}
            period_table = self._render_period_table(selected_table)
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
        if period_table is None:
            start_date, end_date = default_start, default_end
            period_table = self._preset_table_for_range(bounds["max_date"], start_date, end_date)
        if period_table is None:
            period_table = PERIOD_PRESET_TABLES["last_90_days"]
            start_date = max(bounds["min_date"], bounds["max_date"] - timedelta(days=89))
            end_date = bounds["max_date"]
        period_code = {table: name for name, table in PERIOD_PRESET_TABLES.items()}[period_table]
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

    def _preset_table_for_range(self, biz_date: date, start_date: date, end_date: date) -> str | None:
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
        return None

    def _render_period_table(self, table_name: str) -> str:
        allowed_tables = set(PERIOD_PRESET_TABLES.values())
        if table_name not in allowed_tables:
            raise RuntimeError(f"Unexpected period table: {table_name}")
        return render_sql(table_name, self.schemas)

    def _render_sales_role_period_table(self, period: str) -> str:
        return render_sql(SALES_ROLE_PERIOD_TABLE, self.schemas)

    def _sales_role_period_code(self, period: str) -> str:
        period_code = str(period or "").strip().lower()
        return period_code if period_code in SALES_ROLE_PERIODS else "30d"

    def _latest_sales_role_window(self, conn, period_table: str, period: str = "30d") -> dict[str, Any] | None:
        period_code = self._sales_role_period_code(period)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select snapshot_date, period_code, period_days, period_start, period_end
                from {period_table}
                where snapshot_date = (
                    select max(snapshot_date)
                    from {period_table}
                    where period_code = %(period_code)s
                )
                  and period_code = %(period_code)s
                group by snapshot_date, period_code, period_days, period_start, period_end
                order by period_end desc, period_start desc
                limit 1
                """,
                {"period_code": period_code},
            )
            return cursor.fetchone()

    def _sales_role_window_payload(self, window: dict[str, Any] | None) -> dict[str, Any] | None:
        if not window:
            return None
        return {
            "snapshot_date": format_day(window["snapshot_date"]),
            "period_code": window.get("period_code"),
            "period_days": to_int(window.get("period_days")),
            "period_start": format_day(window["period_start"]),
            "period_end": format_day(window["period_end"]),
            "label": f"{format_day(window['period_start'])} ~ {format_day(window['period_end'])}",
        }

    def _sales_role_base_filter_sql(
        self,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {}
        if country_category and country_category != "all":
            clauses.append("p.country_category = %(country_category)s")
            params["country_category"] = country_category
        if seller_name_new and seller_name_new != "all":
            clauses.append("p.seller_name_new = %(seller_name_new)s")
            params["seller_name_new"] = seller_name_new
        keyword = str(keyword or "").strip()
        if keyword:
            params["keyword"] = f"%{keyword}%"
            clauses.append(
                "("
                "p.seller_sku_adj like %(keyword)s "
                "or coalesce(p.local_sku_sample, '') like %(keyword)s "
                "or coalesce(p.seller_name_new, '') like %(keyword)s"
                ")"
            )
        return " and ".join(clauses), params

    def _fetch_sales_role_base_rows(
        self,
        conn,
        period_table: str,
        window: dict[str, Any] | None,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        if not window:
            return []
        where_sql, params = self._sales_role_base_filter_sql(country_category, seller_name_new, keyword)
        params.update(
            {
                "snapshot_date": window["snapshot_date"],
                "period_code": window["period_code"],
                "period_start": window["period_start"],
                "period_end": window["period_end"],
            }
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    p.seller_sku_adj,
                    p.seller_name_new,
                    p.country_category,
                    p.local_sku_sample,
                    p.country_count,
                    p.countries,
                    p.sales_qty,
                    p.daily_sales,
                    p.sales_amount,
                    p.sales_amount_ex_tax,
                    p.order_gross_profit,
                    p.order_gross_margin,
                    p.ad_spend,
                    p.ad_sales,
                    p.acos,
                    p.tacos,
                    p.sales_role_code as snapshot_sales_role_code,
                    p.sales_role_label,
                    p.sales_role_sub_label_id
                from {period_table} p
                where p.snapshot_date = %(snapshot_date)s
                  and p.period_code = %(period_code)s
                  and p.period_start = %(period_start)s
                  and p.period_end = %(period_end)s
                  and {where_sql}
                """,
                params,
            )
            rows = cursor.fetchall()

        result = []
        for row in rows:
            sales_qty = to_float(row.get("sales_qty"))
            sales_amount = to_float(row.get("sales_amount"))
            order_gross_profit = to_float(row.get("order_gross_profit"))
            daily_sales = to_float(row.get("daily_sales"))
            margin_rate = row.get("order_gross_margin")
            role_code = SALES_ROLE_SNAPSHOT_CODE_MAP.get(str(row.get("snapshot_sales_role_code") or ""), "eliminate")
            role = SALES_ROLE_BY_KEY.get(role_code, SALES_ROLE_BY_KEY["eliminate"])
            ad_spend = to_float(row.get("ad_spend"))
            ad_sales = to_float(row.get("ad_sales"))
            item = {
                "sales_role_key": f"{row.get('seller_name_new') or ''}|{row.get('seller_sku_adj') or ''}|{row.get('country_category') or ''}",
                "sales_role": role["label"],
                "sales_role_code": role["key"],
                "sales_role_tone": role["tone"],
                "country_category": row.get("country_category") or "",
                "seller_name_new": row.get("seller_name_new") or "",
                "seller_sku_adj": row.get("seller_sku_adj") or "",
                "local_sku_sample": row.get("local_sku_sample") or "",
                "country_count": to_int(row.get("country_count")),
                "countries": row.get("countries") or "",
                "sales_qty": round(sales_qty, 2),
                "daily_sales": round(daily_sales, 2),
                "sales_amount": round(sales_amount, 2),
                "sales_amount_ex_tax": round(to_float(row.get("sales_amount_ex_tax")), 2),
                "order_gross_profit": round(order_gross_profit, 2),
                "order_gross_margin": round(to_float(margin_rate), 4),
                "daily_sales_band": sales_role_daily_sales_band(daily_sales),
                "margin_band": sales_role_margin_band(margin_rate),
                "ad_spend": round(ad_spend, 2),
                "ad_sales": round(ad_sales, 2),
                "acos": round(to_float(row.get("acos")), 4),
                "tacos": round(to_float(row.get("tacos")), 4),
            }
            result.append(item)
        return result

    def _filter_sales_role_rows(
        self,
        rows: list[dict[str, Any]],
        sales_role: str = "all",
        daily_sales_band: str = "all",
        margin_band: str = "all",
    ) -> list[dict[str, Any]]:
        filtered = []
        for row in rows:
            if sales_role and sales_role != "all" and row["sales_role_code"] != sales_role:
                continue
            if daily_sales_band and daily_sales_band != "all" and row["daily_sales_band"] != daily_sales_band:
                continue
            if margin_band and margin_band != "all" and row["margin_band"] != margin_band:
                continue
            filtered.append(row)
        return filtered

    def _sort_sales_role_rows(self, rows: list[dict[str, Any]], sort_field: str, sort_dir: str) -> None:
        sort_key = sort_field if sort_field in {
            "sales_role",
            "country_category",
            "seller_name_new",
            "seller_sku_adj",
            "country_count",
            "sales_qty",
            "daily_sales",
            "sales_amount",
            "order_gross_profit",
            "order_gross_margin",
            "daily_sales_band",
            "margin_band",
            "ad_spend",
            "ad_sales",
            "acos",
            "tacos",
        } else "sales_amount"
        reverse = str(sort_dir or "desc").lower() != "asc"

        def normalized(row: dict[str, Any]) -> tuple[int, Any]:
            value = row.get(sort_key)
            if value is None or value == "":
                return (1, "")
            if isinstance(value, (int, float)):
                return (0, value)
            return (0, str(value))

        rows.sort(key=lambda row: (normalized(row), row.get("seller_sku_adj") or ""), reverse=reverse)

    def _build_sales_role_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        sales_amount = sum(to_float(row.get("sales_amount")) for row in rows)
        sales_qty = sum(to_float(row.get("sales_qty")) for row in rows)
        gross_profit = sum(to_float(row.get("order_gross_profit")) for row in rows)
        active_count = sum(1 for row in rows if to_float(row.get("sales_qty")) > 0)
        eliminate_count = sum(1 for row in rows if row.get("sales_role_code") == "eliminate")
        return {
            "sku_count": len(rows),
            "sales_amount": round(sales_amount, 2),
            "sales_qty": round(sales_qty, 2),
            "order_gross_profit": round(gross_profit, 2),
            "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
            "active_sku_count": active_count,
            "eliminate_count": eliminate_count,
        }

    def _build_sales_role_distribution(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        total = max(len(rows), 1)
        result = []
        for option in SALES_ROLE_OPTIONS:
            role_rows = [row for row in rows if row.get("sales_role_code") == option["key"]]
            sales_amount = sum(to_float(row.get("sales_amount")) for row in role_rows)
            sales_qty = sum(to_float(row.get("sales_qty")) for row in role_rows)
            gross_profit = sum(to_float(row.get("order_gross_profit")) for row in role_rows)
            result.append(
                {
                    **option,
                    "count": len(role_rows),
                    "ratio": round(len(role_rows) / total, 4),
                    "sales_amount": round(sales_amount, 2),
                    "daily_sales": round(sum(to_float(row.get("daily_sales")) for row in role_rows), 2),
                    "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
                }
            )
        return result

    def _build_sales_role_matrix(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        cells = []
        total = max(len(rows), 1)
        for margin in SALES_ROLE_MARGIN_BANDS:
            for daily in SALES_ROLE_DAILY_SALES_BANDS:
                cell_rows = [
                    row
                    for row in rows
                    if row.get("margin_band") == margin and row.get("daily_sales_band") == daily
                ]
                sales_amount = sum(to_float(row.get("sales_amount")) for row in cell_rows)
                cells.append(
                    {
                        "margin_band": margin,
                        "daily_sales_band": daily,
                        "count": len(cell_rows),
                        "ratio": round(len(cell_rows) / total, 4),
                        "sales_amount": round(sales_amount, 2),
                    }
                )
        return {
            "daily_sales_bands": SALES_ROLE_DAILY_SALES_BANDS,
            "margin_bands": SALES_ROLE_MARGIN_BANDS,
            "cells": cells,
            "total": len(rows),
        }

    def _default_lifecycle_options(self) -> list[dict[str, Any]]:
        return [
            {
                "id": label_id,
                "key": str(label_id),
                "label": config["label"],
                "label_period": config["label_period"],
                "window_days": config["window_days"],
                "tone": config["tone"],
                "rule": "",
                "definition": "",
            }
            for label_id, config in LIFECYCLE_WINDOW_BY_ID.items()
        ]

    def _fetch_lifecycle_options(self, conn) -> list[dict[str, Any]]:
        defaults = {option["id"]: option for option in self._default_lifecycle_options()}
        rows: list[dict[str, Any]] = []
        try:
            rows = self._query_lifecycle_options(conn)
        except pymysql.err.OperationalError as exc:
            if not (exc.args and exc.args[0] == 1049):
                raise
            with self.source_connect() as source_conn:
                rows = self._query_lifecycle_options(source_conn)
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                try:
                    with self.source_connect() as source_conn:
                        rows = self._query_lifecycle_options(source_conn)
                except pymysql.err.ProgrammingError as source_exc:
                    if source_exc.args and source_exc.args[0] == 1146:
                        return list(defaults.values())
                    raise
            else:
                raise

        for row in rows:
            label_id = to_int(row.get("sub_label_id"))
            if label_id not in defaults:
                continue
            defaults[label_id] = {
                **defaults[label_id],
                "label": row.get("sub_label_name") or defaults[label_id]["label"],
                "rule": row.get("tag_rule") or "",
                "definition": row.get("business_definition") or "",
            }
        return [defaults[label_id] for label_id in LIFECYCLE_LABEL_IDS if label_id in defaults]

    def _query_lifecycle_options(self, conn) -> list[dict[str, Any]]:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        sub_label_id,
                        sub_label_name,
                        tag_rule,
                        business_definition
                    from {LIFECYCLE_DETAIL_TABLE}
                    where label_id = %(label_id)s
                      and sub_label_id in %(label_ids)s
                    order by sub_label_id
                    """,
                    {"label_id": LIFECYCLE_PARENT_LABEL_ID, "label_ids": tuple(LIFECYCLE_LABEL_IDS)},
                )
                return cursor.fetchall()
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                raise
            raise
        except pymysql.err.OperationalError:
            raise

    def _latest_lifecycle_data_date(self, conn) -> date | None:
        try:
            return self._query_latest_lifecycle_data_date(conn)
        except pymysql.err.OperationalError as exc:
            if not (exc.args and exc.args[0] == 1049):
                raise
            with self.source_connect() as source_conn:
                return self._query_latest_lifecycle_data_date(source_conn)
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                try:
                    with self.source_connect() as source_conn:
                        return self._query_latest_lifecycle_data_date(source_conn)
                except pymysql.err.ProgrammingError as source_exc:
                    if source_exc.args and source_exc.args[0] == 1146:
                        return None
                    raise
            raise

    def _query_latest_lifecycle_data_date(self, conn) -> date | None:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select max(data_date) as data_date
                    from {LIFECYCLE_TAG_TABLE}
                    where label_id in %(label_ids)s
                    """,
                    {"label_ids": tuple(LIFECYCLE_LABEL_IDS)},
                )
                row = cursor.fetchone() or {}
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                raise
            raise
        except pymysql.err.OperationalError:
            raise
        return row.get("data_date")

    def _lifecycle_filter_sql(
        self,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {}
        if country_category and country_category != "all":
            clauses.append("t.country_category = %(country_category)s")
            params["country_category"] = country_category
        if seller_name_new and seller_name_new != "all":
            clauses.append("t.store = %(seller_name_new)s")
            params["seller_name_new"] = seller_name_new
        keyword = str(keyword or "").strip()
        if keyword:
            params["keyword"] = f"%{keyword}%"
            clauses.append("(coalesce(t.msku, '') like %(keyword)s or coalesce(t.store, '') like %(keyword)s)")
        return " and ".join(clauses), params

    def _fetch_lifecycle_label_rows(
        self,
        lifecycle_date: date,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        where_sql, params = self._lifecycle_filter_sql(country_category, seller_name_new, keyword)
        params.update({"data_date": lifecycle_date, "label_ids": tuple(LIFECYCLE_LABEL_IDS)})
        try:
            with self.source_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        select distinct
                            t.label_id as lifecycle_label_id,
                            t.country_category,
                            t.store as seller_name_new,
                            t.msku as seller_sku_adj,
                            case t.label_id
                                when 201 then 30
                                when 202 then 90
                                else 180
                            end as metric_days,
                            case t.label_id
                                when 201 then '上架≤30天'
                                when 202 then '上架31-120天'
                                when 203 then '上架121-300天'
                                when 204 then '上架>300天'
                                else '人工判断'
                            end as label_period
                        from {LIFECYCLE_TAG_TABLE} t
                        where t.data_date = %(data_date)s
                          and t.label_id in %(label_ids)s
                          and {where_sql}
                        """,
                        params,
                    )
                    return cursor.fetchall()
        except (pymysql.err.ProgrammingError, pymysql.err.OperationalError) as exc:
            code = exc.args[0] if exc.args else None
            if code in {1049, 1146}:
                return []
            raise

    def _fetch_sales_role_lifecycle_rows(
        self,
        conn,
        period_table: str,
        role_window: dict[str, Any] | None,
        lifecycle_date: date | None,
        lifecycle_options: list[dict[str, Any]],
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> list[dict[str, Any]]:
        if not lifecycle_date:
            return []
        label_rows = self._fetch_lifecycle_label_rows(
            lifecycle_date,
            country_category=country_category,
            seller_name_new=seller_name_new,
            keyword=keyword,
        )
        if not label_rows:
            return []
        return self._build_lifecycle_rows_from_period_snapshots(
            conn,
            period_table,
            role_window,
            lifecycle_date,
            label_rows,
            lifecycle_options,
        )

    def _build_lifecycle_rows_from_period_snapshots(
        self,
        conn,
        sales_role_period_table: str,
        role_window: dict[str, Any] | None,
        lifecycle_date: date,
        label_rows: list[dict[str, Any]],
        lifecycle_options: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lifecycle_by_id = {option["id"]: option for option in lifecycle_options}
        snapshot_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        result: list[dict[str, Any]] = []
        sku_values = sorted({row.get("seller_sku_adj") or "" for row in label_rows if row.get("seller_sku_adj")})
        if role_window and sku_values:
            params = {
                "snapshot_date": role_window["snapshot_date"],
                "period_code": role_window["period_code"],
                "period_start": role_window["period_start"],
                "period_end": role_window["period_end"],
            }
            for sku_chunk in self._chunks(sku_values, 300):
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        select
                            seller_sku_adj,
                            seller_name_new,
                            country_category,
                            local_sku_sample,
                            country_count,
                            countries,
                            sales_qty,
                            daily_sales,
                            sales_amount,
                            sales_amount_ex_tax,
                            order_gross_profit,
                            order_gross_margin,
                            ad_spend,
                            ad_sales,
                            sales_role_code
                        from {sales_role_period_table}
                        where snapshot_date = %(snapshot_date)s
                          and period_code = %(period_code)s
                          and period_start = %(period_start)s
                          and period_end = %(period_end)s
                          and seller_sku_adj in %(sku_values)s
                        """,
                        {**params, "sku_values": tuple(sku_chunk)},
                    )
                    for period_row in cursor.fetchall():
                        snapshot_rows[
                            (
                                period_row.get("seller_sku_adj") or "",
                                period_row.get("seller_name_new") or "",
                                period_row.get("country_category") or "",
                            )
                        ] = period_row

        for row in label_rows:
            label_id = to_int(row.get("lifecycle_label_id"))
            sku = row.get("seller_sku_adj") or ""
            store = row.get("seller_name_new") or ""
            country_category = row.get("country_category") or ""
            period_row = snapshot_rows.get((sku, store, country_category), {})
            lifecycle = lifecycle_by_id.get(label_id) or LIFECYCLE_WINDOW_BY_ID.get(label_id) or {}
            role_code = SALES_ROLE_SNAPSHOT_CODE_MAP.get(str(period_row.get("sales_role_code") or ""), "eliminate")
            role = SALES_ROLE_BY_KEY.get(role_code, SALES_ROLE_BY_KEY["eliminate"])
            sales_qty = to_float(period_row.get("sales_qty"))
            sales_amount = to_float(period_row.get("sales_amount"))
            order_gross_profit = to_float(period_row.get("order_gross_profit"))
            ad_spend = to_float(period_row.get("ad_spend"))
            ad_sales = to_float(period_row.get("ad_sales"))
            result.append(
                {
                    "lifecycle_label_id": label_id,
                    "lifecycle_label_key": str(label_id),
                    "lifecycle_label": lifecycle.get("label") or "",
                    "lifecycle_tone": lifecycle.get("tone") or "neutral",
                    "label_period": row.get("label_period") or lifecycle.get("label_period") or "",
                    "lifecycle_rule": lifecycle.get("rule") or "",
                    "metric_days": to_int(role_window.get("period_days")) if role_window else 0,
                    "sales_role": role["label"],
                    "sales_role_code": role["key"],
                    "sales_role_tone": role["tone"],
                    "sales_role_period": role_window.get("period_code") if role_window else "",
                    "country_category": country_category,
                    "seller_name_new": store,
                    "seller_sku_adj": sku,
                    "local_sku_sample": period_row.get("local_sku_sample") or "",
                    "country_count": to_int(period_row.get("country_count")),
                    "countries": period_row.get("countries") or "",
                    "sales_qty": round(sales_qty, 2),
                    "daily_sales": round(to_float(period_row.get("daily_sales")), 2),
                    "sales_amount": round(sales_amount, 2),
                    "sales_amount_ex_tax": round(to_float(period_row.get("sales_amount_ex_tax")), 2),
                    "order_gross_profit": round(order_gross_profit, 2),
                    "order_gross_margin": round(to_float(period_row.get("order_gross_margin")), 4)
                    if period_row
                    else 0,
                    "ad_spend": round(ad_spend, 2),
                    "ad_sales": round(ad_sales, 2),
                    "acos": round(ad_spend / ad_sales, 4) if ad_sales else 0,
                    "tacos": round(ad_spend / sales_amount, 4) if sales_amount else 0,
                }
            )
        return result

    def _lifecycle_metric_table(self, metric_days: int) -> str:
        if metric_days == 30:
            return "etl_datasync_test.dashboard_product_period_30d_snapshot"
        return "etl_datasync_test.dashboard_product_period_90d_snapshot"

    def _period_snapshot_window(
        self,
        conn,
        period_table: str,
        preferred_end: date,
        metric_days: int,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select snapshot_date, period_start, period_end
                from {period_table}
                where period_end <= %(preferred_end)s
                  and datediff(period_end, period_start) + 1 = %(metric_days)s
                order by period_end desc, snapshot_date desc
                limit 1
                """,
                {"preferred_end": preferred_end, "metric_days": metric_days},
            )
            return cursor.fetchone()

    def _fetch_sales_role_snapshot_map(
        self,
        conn,
        period_table: str,
        role_window: dict[str, Any] | None,
        sku_values: list[str],
    ) -> dict[tuple[str, str, str], str]:
        if not role_window or not sku_values:
            return {}
        role_map: dict[tuple[str, str, str], str] = {}
        params = {
            "snapshot_date": role_window["snapshot_date"],
            "period_code": role_window["period_code"],
            "period_start": role_window["period_start"],
            "period_end": role_window["period_end"],
        }
        for sku_chunk in self._chunks(sku_values, 300):
            chunk_params = {**params, "sku_values": tuple(sku_chunk)}
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        seller_sku_adj,
                        seller_name_new,
                        country_category,
                        sales_role_code
                    from {period_table}
                    where snapshot_date = %(snapshot_date)s
                      and period_code = %(period_code)s
                      and period_start = %(period_start)s
                      and period_end = %(period_end)s
                      and seller_sku_adj in %(sku_values)s
                    """,
                    chunk_params,
                )
                for row in cursor.fetchall():
                    role_map[
                        (
                            row.get("seller_sku_adj") or "",
                            row.get("seller_name_new") or "",
                            row.get("country_category") or "",
                        )
                    ] = row.get("sales_role_code") or ""
        return role_map

    def _chunks(self, values: list[Any], size: int) -> list[list[Any]]:
        return [values[index:index + size] for index in range(0, len(values), size)]

    def _filter_sales_role_lifecycle_rows(
        self,
        rows: list[dict[str, Any]],
        lifecycle_label: str = "all",
        sales_role: str = "all",
    ) -> list[dict[str, Any]]:
        filtered = []
        for row in rows:
            if lifecycle_label and lifecycle_label != "all" and str(row.get("lifecycle_label_id")) != str(lifecycle_label):
                continue
            if sales_role and sales_role != "all" and row.get("sales_role_code") != sales_role:
                continue
            filtered.append(row)
        return filtered

    def _sort_sales_role_lifecycle_rows(self, rows: list[dict[str, Any]], sort_field: str, sort_dir: str) -> None:
        sort_key = sort_field if sort_field in {
            "lifecycle_label",
            "sales_role",
            "country_category",
            "seller_name_new",
            "seller_sku_adj",
            "sales_qty",
            "daily_sales",
            "sales_amount",
            "order_gross_profit",
            "order_gross_margin",
            "label_period",
            "sales_role_period",
        } else "sales_amount"
        reverse = str(sort_dir or "desc").lower() != "asc"

        def normalized(row: dict[str, Any]) -> tuple[int, Any]:
            value = row.get(sort_key)
            if value is None or value == "":
                return (1, "")
            if isinstance(value, (int, float)):
                return (0, value)
            return (0, str(value))

        rows.sort(key=lambda row: (normalized(row), row.get("seller_sku_adj") or ""), reverse=reverse)

    def _build_sales_role_lifecycle_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        sales_amount = sum(to_float(row.get("sales_amount")) for row in rows)
        sales_qty = sum(to_float(row.get("sales_qty")) for row in rows)
        gross_profit = sum(to_float(row.get("order_gross_profit")) for row in rows)
        return {
            "sku_count": len(rows),
            "sales_amount": round(sales_amount, 2),
            "sales_qty": round(sales_qty, 2),
            "order_gross_profit": round(gross_profit, 2),
            "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
            "active_sku_count": sum(1 for row in rows if to_float(row.get("sales_qty")) > 0),
            "mature_count": sum(1 for row in rows if to_int(row.get("lifecycle_label_id")) == 204),
            "problem_count": sum(1 for row in rows if row.get("sales_role_code") == "eliminate"),
        }

    def _build_sales_role_lifecycle_distribution(
        self,
        rows: list[dict[str, Any]],
        lifecycle_options: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        total = max(len(rows), 1)
        result = []
        for option in lifecycle_options:
            lifecycle_rows = [row for row in rows if to_int(row.get("lifecycle_label_id")) == option["id"]]
            sales_amount = sum(to_float(row.get("sales_amount")) for row in lifecycle_rows)
            gross_profit = sum(to_float(row.get("order_gross_profit")) for row in lifecycle_rows)
            result.append(
                {
                    **option,
                    "count": len(lifecycle_rows),
                    "ratio": round(len(lifecycle_rows) / total, 4),
                    "sales_amount": round(sales_amount, 2),
                    "daily_sales": round(sum(to_float(row.get("daily_sales")) for row in lifecycle_rows), 2),
                    "order_gross_margin": round(gross_profit / sales_amount, 4) if sales_amount else 0,
                }
            )
        return result

    def _build_sales_role_lifecycle_matrix(
        self,
        rows: list[dict[str, Any]],
        lifecycle_options: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cells = []
        total = max(len(rows), 1)
        for lifecycle in lifecycle_options:
            for role in SALES_ROLE_OPTIONS:
                cell_rows = [
                    row
                    for row in rows
                    if to_int(row.get("lifecycle_label_id")) == lifecycle["id"]
                    and row.get("sales_role_code") == role["key"]
                ]
                cells.append(
                    {
                        "lifecycle_label_id": lifecycle["id"],
                        "lifecycle_label": lifecycle["label"],
                        "sales_role_code": role["key"],
                        "sales_role": role["label"],
                        "count": len(cell_rows),
                        "ratio": round(len(cell_rows) / total, 4),
                        "sales_amount": round(sum(to_float(row.get("sales_amount")) for row in cell_rows), 2),
                    }
                )
        return {
            "lifecycle_labels": lifecycle_options,
            "roles": SALES_ROLE_OPTIONS,
            "cells": cells,
            "total": len(rows),
        }

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

    def _detail_order_sql(self, sort_field: str, sort_dir: str) -> tuple[str, bool]:
        direction = "asc" if str(sort_dir or "").lower() == "asc" else "desc"
        sort_key = str(sort_field or "").strip()
        sortable_fields = {
            "country": ("coalesce(p.country, '')", False),
            "store": ("coalesce(p.seller_name_new, '')", False),
            "msku": ("coalesce(p.seller_sku_adj, '')", False),
            "daily_sales": ("coalesce(p.daily_sales, 0)", False),
            "daily_sales_band": ("coalesce(p.daily_sales_band, '')", False),
            "order_gross_margin": ("coalesce(p.order_gross_margin, 0)", False),
            "margin_band": ("coalesce(p.margin_band, '')", False),
            "sales_7d": ("coalesce(r.sales_7d, 0)", True),
            "sales_30d": ("coalesce(r.sales_30d, 0)", True),
            "revenue_30d": ("coalesce(r.revenue_30d, 0)", True),
            "current_price": ("coalesce(p.current_price, 0)", False),
            "limit_price_35_display": ("coalesce(p.limit_price, 0)", False),
            "limit_price_10": ("coalesce(p.limit_price_10, 0)", False),
            "price_gap": ("(coalesce(p.current_price, 0) - coalesce(p.limit_price, 0))", False),
            "over_limit": ("coalesce(p.over_limit_flag, 0)", False),
            "fba_sellable_inventory": ("coalesce(p.fba_sellable_inventory, 0)", False),
            "stock_days": ("coalesce(p.local_stock_sellable_days, 0)", False),
        }
        if not sort_key or sort_key not in sortable_fields:
            return "p.sales_amount desc, p.daily_sales desc, p.seller_sku_adj asc", False

        expression, needs_recent_join = sortable_fields[sort_key]
        return f"{expression} {direction}, p.seller_sku_adj asc, p.country asc, p.seller_name_new asc", needs_recent_join

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
        sort_field: str = "",
        sort_dir: str = "",
    ) -> list[dict[str, Any]]:
        where_sql, params = self._period_where(window, filters)
        limit_sql = ""
        if limit is not None:
            params["limit"] = limit
            params["offset"] = offset
            limit_sql = "limit %(limit)s offset %(offset)s"
        column_filter_sql, needs_recent_join = self._detail_column_filter_clause(filters, params)
        order_sql, sort_needs_recent_join = self._detail_order_sql(sort_field, sort_dir)
        recent_join_sql = self._detail_recent_join_sql(window, params) if needs_recent_join or sort_needs_recent_join else ""

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select p.*
                from {self._render_period_table(window.period_table)} p
                {recent_join_sql}
                where {where_sql}{column_filter_sql}
                order by {order_sql}
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
        comparison_code: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        alert_type: str = "all",
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        if is_alert_month_mode(comparison_mode):
            return self._fetch_alert_center_monthly(
                conn,
                filters,
                previous_month=previous_month,
                recent_month=recent_month,
                alert_type=alert_type,
                sales_trend=sales_trend,
                rank_trend=rank_trend,
                margin_status=margin_status,
                stock_status=stock_status,
                transition_filter=transition_filter,
            )

        analysis_focus_type = self._alert_analysis_focus_type(alert_type, sales_trend, rank_trend, margin_status, stock_status)
        selected_code = normalize_alert_comparison_code(comparison_code, compare_days)
        rendered_table = render_sql(ALERT_COMPARISON_TABLE, self.schemas)
        snapshot_date = self._latest_alert_comparison_snapshot(conn, selected_code)
        options = self._fetch_alert_comparison_options(conn, snapshot_date)
        available_months = self._fetch_alert_month_options(conn)
        compare_days = alert_compare_days_from_code(selected_code) or compare_days
        empty_summary = {"sales_drop": 0, "margin_low": 0, "rank_drop": 0, "stock_short": 0}
        if not snapshot_date:
            return {
                "items": [],
                "summary": empty_summary,
                "analysis": self._build_alert_analysis([], empty_summary, analysis_focus_type),
                "window": "",
                "comparison_window": "",
                "compare_days": compare_days,
                "comparison_code": selected_code,
                "comparison_type": "days" if selected_code.startswith("d") else "month_to_date",
                "comparison_label": selected_code,
                "available_comparisons": options,
                "comparison_mode": "days",
                "available_months": available_months,
                "empty_text": "当前还没有预警预计算数据，请先运行每日 ETL。",
            }

        filter_sql, params = self._filter_clause(filters, alias="a")
        params.update({"snapshot_date": snapshot_date, "comparison_code": selected_code})
        items: list[dict[str, Any]] = []
        first_row: dict[str, Any] = {}

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select a.*
                    from {rendered_table} a
                    where a.snapshot_date = %(snapshot_date)s
                      and a.comparison_code = %(comparison_code)s
                      and a.has_alert = 1
                      and {filter_sql}
                    """,
                    params,
                )
                for row in cursor.fetchall():
                    if not first_row:
                        first_row = row
                    items.append(self._build_precomputed_alert_item(row))

                if not first_row:
                    cursor.execute(
                        f"""
                        select a.*
                        from {rendered_table} a
                        where a.snapshot_date = %(snapshot_date)s
                          and a.comparison_code = %(comparison_code)s
                        limit 1
                        """,
                        {"snapshot_date": snapshot_date, "comparison_code": selected_code},
                    )
                    first_row = cursor.fetchone() or {}
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return self._fetch_alert_center_legacy(
                    conn,
                    window,
                    filters,
                    compare_days=compare_days,
                    alert_type=alert_type,
                    sales_trend=sales_trend,
                    rank_trend=rank_trend,
                    margin_status=margin_status,
                    stock_status=stock_status,
                    transition_filter=transition_filter,
                )
            raise

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
        filtered = self._apply_transition_filter(filtered, transition_filter)
        filtered.sort(key=lambda item: (item["priority"], item["title"]))
        summary = {key: 0 for key in priority}
        for item in filtered:
            for key in item["alert_types"]:
                if key in summary:
                    summary[key] += 1
        return {
            "items": filtered,
            "summary": summary,
            "analysis": self._build_alert_analysis(filtered, summary, analysis_focus_type),
            "window": self._alert_window_text(first_row, recent=True),
            "comparison_window": self._alert_window_text(first_row, recent=False),
            "compare_days": compare_days,
            "comparison_code": selected_code,
            "comparison_type": str(first_row.get("comparison_type") or ("days" if selected_code.startswith("d") else "month_to_date")),
            "comparison_label": str(first_row.get("comparison_label") or selected_code),
            "available_comparisons": options,
            "comparison_mode": "days",
            "available_months": available_months,
            "empty_text": "当前筛选下没有明显异常。",
        }

    def _fetch_alert_center_legacy(
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
        transition_filter: str = "",
    ) -> dict[str, Any]:
        table = self._render_period_table(window.period_table)
        where_sql, params = self._period_where(window, filters, alias="p")
        analysis_focus_type = self._alert_analysis_focus_type(alert_type, sales_trend, rank_trend, margin_status, stock_status)
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
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.sales_amount else 0 end) as previous_sales_amount,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.order_gross_profit else 0 end) as recent_order_gross_profit,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.order_gross_profit else 0 end) as previous_order_gross_profit,
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
        filtered = self._apply_transition_filter(filtered, transition_filter)
        filtered.sort(key=lambda item: (item["priority"], item["title"]))
        summary = {key: 0 for key in priority}
        for item in filtered:
            for key in item["alert_types"]:
                if key in summary:
                    summary[key] += 1
        return {
            "items": filtered,
            "summary": summary,
            "analysis": self._build_alert_analysis(filtered, summary, analysis_focus_type),
            "window": f"近{compare_days}天 {format_day(recent_start)} ~ {format_day(recent_end)}",
            "comparison_window": f"前{compare_days}天 {format_day(previous_start)} ~ {format_day(previous_end)}",
            "compare_days": compare_days,
            "empty_text": "当前筛选下没有明显异常。",
        }

    def _latest_alert_comparison_snapshot(self, conn, comparison_code: str) -> date | None:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select max(snapshot_date) as snapshot_date
                    from dashboard_alert_comparison_snapshot
                    where comparison_code = %(comparison_code)s
                    """,
                    {"comparison_code": comparison_code},
                )
                row = cursor.fetchone() or {}
            return row.get("snapshot_date")
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return None
            raise

    def _fetch_alert_comparison_options(self, conn, snapshot_date: date | None) -> list[dict[str, Any]]:
        if not snapshot_date:
            return []
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        comparison_code,
                        max(comparison_type) as comparison_type,
                        max(comparison_label) as comparison_label,
                        min(recent_start) as recent_start,
                        max(recent_end) as recent_end,
                        min(previous_start) as previous_start,
                        max(previous_end) as previous_end,
                        max(recent_days) as recent_days,
                        max(previous_days) as previous_days
                    from dashboard_alert_comparison_snapshot
                    where snapshot_date = %(snapshot_date)s
                      and comparison_type = 'days'
                    group by comparison_code
                    order by
                        case
                            when comparison_code = 'd7' then 1
                            when comparison_code = 'd14' then 2
                            when comparison_code = 'd30' then 3
                            when comparison_code = 'd60' then 4
                            when comparison_code = 'd90' then 5
                            else 20
                        end,
                        comparison_code
                    """,
                    {"snapshot_date": snapshot_date},
                )
                rows = cursor.fetchall()
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return []
            raise
        return [
            {
                "code": str(row.get("comparison_code") or ""),
                "type": str(row.get("comparison_type") or ""),
                "label": str(row.get("comparison_label") or row.get("comparison_code") or ""),
                "recent_start": format_day(row.get("recent_start")),
                "recent_end": format_day(row.get("recent_end")),
                "previous_start": format_day(row.get("previous_start")),
                "previous_end": format_day(row.get("previous_end")),
                "recent_days": to_int(row.get("recent_days")),
                "previous_days": to_int(row.get("previous_days")),
            }
            for row in rows
            if row.get("comparison_code")
        ]

    def _latest_alert_monthly_snapshot(self, conn) -> date | None:
        try:
            with conn.cursor() as cursor:
                cursor.execute("select max(snapshot_date) as snapshot_date from dashboard_alert_monthly_metric_snapshot")
                row = cursor.fetchone() or {}
            return row.get("snapshot_date")
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return None
            raise

    def _fetch_alert_month_options(self, conn, snapshot_date: date | None = None) -> list[dict[str, Any]]:
        snapshot_date = snapshot_date or self._latest_alert_monthly_snapshot(conn)
        if not snapshot_date:
            return []
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        month_code,
                        min(data_start) as data_start,
                        max(data_end) as data_end,
                        max(stat_days) as stat_days,
                        max(is_month_complete) as is_month_complete
                    from dashboard_alert_monthly_metric_snapshot
                    where snapshot_date = %(snapshot_date)s
                    group by month_code
                    order by month_code
                    """,
                    {"snapshot_date": snapshot_date},
                )
                rows = cursor.fetchall()
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return []
            raise
        return [
            {
                "code": str(row.get("month_code") or ""),
                "label": str(row.get("month_code") or ""),
                "data_start": format_day(row.get("data_start")),
                "data_end": format_day(row.get("data_end")),
                "stat_days": to_int(row.get("stat_days")),
                "is_month_complete": bool(row.get("is_month_complete")),
            }
            for row in rows
            if row.get("month_code")
        ]

    def _resolve_alert_month_pair(
        self,
        available_months: list[dict[str, Any]],
        previous_month: str,
        recent_month: str,
    ) -> tuple[str, str]:
        codes = [item["code"] for item in available_months]
        if not codes:
            return "", ""
        recent = normalize_alert_month_code(recent_month)
        previous = normalize_alert_month_code(previous_month)
        if recent not in codes:
            recent = codes[-1]
        if previous not in codes or previous == recent:
            recent_index = codes.index(recent)
            previous = codes[recent_index - 1] if recent_index > 0 else codes[0]
        return previous, recent

    def _fetch_alert_center_monthly(
        self,
        conn,
        filters: dict[str, Any],
        previous_month: str = "",
        recent_month: str = "",
        alert_type: str = "all",
        sales_trend: str = "all",
        rank_trend: str = "all",
        margin_status: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        snapshot_date = self._latest_alert_monthly_snapshot(conn)
        available_months = self._fetch_alert_month_options(conn, snapshot_date)
        previous_month, recent_month = self._resolve_alert_month_pair(available_months, previous_month, recent_month)
        analysis_focus_type = self._alert_analysis_focus_type(alert_type, sales_trend, rank_trend, margin_status, stock_status)
        empty_summary = {"sales_drop": 0, "margin_low": 0, "rank_drop": 0, "stock_short": 0}
        if not snapshot_date or not previous_month or not recent_month:
            return {
                "items": [],
                "summary": empty_summary,
                "analysis": self._build_alert_analysis([], empty_summary, analysis_focus_type),
                "window": "",
                "comparison_window": "",
                "compare_days": 0,
                "comparison_code": "",
                "comparison_mode": "month",
                "comparison_type": "month",
                "comparison_label": "",
                "previous_month": previous_month,
                "recent_month": recent_month,
                "available_comparisons": [],
                "available_months": available_months,
                "empty_text": "Month comparison data is not ready.",
            }

        filter_sql, params = self._filter_clause(filters, alias="a")
        params.update(
            {
                "snapshot_date": snapshot_date,
                "previous_month": previous_month,
                "recent_month": recent_month,
            }
        )
        rendered_table = render_sql(ALERT_MONTHLY_METRIC_TABLE, self.schemas)
        items: list[dict[str, Any]] = []
        first_row: dict[str, Any] = {}
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                with joined as (
                    select
                        coalesce(r.item_key, p.item_key) as item_key,
                        coalesce(r.seller_name_new, p.seller_name_new) as seller_name_new,
                        coalesce(r.seller_name, p.seller_name) as seller_name,
                        coalesce(r.seller_sku_adj, p.seller_sku_adj) as seller_sku_adj,
                        coalesce(r.country_category, p.country_category) as country_category,
                        coalesce(r.country, p.country) as country,
                        coalesce(r.local_sku, p.local_sku) as local_sku,
                        coalesce(r.filter_flag, p.filter_flag, 1) as filter_flag,
                        coalesce(r.over_limit_flag, p.over_limit_flag, 0) as over_limit_flag,
                        coalesce(r.daily_sales_band, '日销 0') as daily_sales_band,
                        coalesce(r.margin_band, p.margin_band, '毛利率<0%%') as margin_band,
                        coalesce(r.data_start, p.data_start) as recent_start,
                        coalesce(r.data_end, p.data_end) as recent_end,
                        coalesce(r.stat_days, 0) as recent_days,
                        coalesce(p.data_start, r.data_start) as previous_start,
                        coalesce(p.data_end, r.data_end) as previous_end,
                        coalesce(p.stat_days, 0) as previous_days,
                        coalesce(r.sales_qty, 0) as recent_sales_qty,
                        coalesce(p.sales_qty, 0) as previous_sales_qty,
                        coalesce(r.daily_sales, 0) as recent_daily_sales,
                        coalesce(p.daily_sales, 0) as previous_daily_sales,
                        coalesce(r.sales_amount, 0) as recent_sales_amount,
                        coalesce(p.sales_amount, 0) as previous_sales_amount,
                        coalesce(r.daily_sales_amount, 0) as recent_daily_sales_amount,
                        coalesce(p.daily_sales_amount, 0) as previous_daily_sales_amount,
                        coalesce(r.order_gross_profit, 0) as recent_order_gross_profit,
                        coalesce(p.order_gross_profit, 0) as previous_order_gross_profit,
                        r.margin as recent_margin,
                        p.margin as previous_margin,
                        r.avg_rank as recent_rank,
                        p.avg_rank as previous_rank,
                        coalesce(r.fba_sellable_inventory, p.fba_sellable_inventory, 0) as fba_sellable_inventory,
                        coalesce(r.sellable_days, 0) as sellable_days
                    from {rendered_table} r
                    left join {rendered_table} p
                      on p.snapshot_date = r.snapshot_date
                     and p.item_key = r.item_key
                     and p.month_code = %(previous_month)s
                    where r.snapshot_date = %(snapshot_date)s
                      and r.month_code = %(recent_month)s
                    union all
                    select
                        p.item_key, p.seller_name_new, p.seller_name, p.seller_sku_adj, p.country_category, p.country, p.local_sku,
                        p.filter_flag, p.over_limit_flag, '日销 0', p.margin_band,
                        p.data_start, p.data_end, 0,
                        p.data_start, p.data_end, p.stat_days,
                        0, p.sales_qty, 0, p.daily_sales, 0, p.sales_amount, 0, p.daily_sales_amount,
                        0, p.order_gross_profit, null, p.margin, null, p.avg_rank,
                        p.fba_sellable_inventory, 0
                    from {rendered_table} p
                    left join {rendered_table} r
                      on r.snapshot_date = p.snapshot_date
                     and r.item_key = p.item_key
                     and r.month_code = %(recent_month)s
                    where p.snapshot_date = %(snapshot_date)s
                      and p.month_code = %(previous_month)s
                      and r.item_key is null
                ),
                classified as (
                    select
                        j.*,
                        case
                            when j.previous_daily_sales <> 0 then (j.recent_daily_sales - j.previous_daily_sales) / abs(j.previous_daily_sales)
                            when j.recent_daily_sales > 0 then 1
                            else 0
                        end as sales_change_rate,
                        (j.previous_sales_qty >= 10 and j.recent_daily_sales <= j.previous_daily_sales * 0.7) as sales_drop_flag,
                        (j.recent_sales_qty >= 10 and j.recent_daily_sales >= j.previous_daily_sales * 1.3) as sales_up_flag,
                        (
                            j.previous_rank is not null
                            and j.recent_rank is not null
                            and j.recent_rank >= j.previous_rank + 5
                            and j.recent_rank >= j.previous_rank * 1.2
                        ) as rank_drop_flag,
                        (
                            j.previous_rank is not null
                            and j.recent_rank is not null
                            and j.recent_rank <= greatest(j.previous_rank - 5, j.previous_rank * 0.8)
                        ) as rank_up_flag,
                        (j.recent_sales_amount >= 1000 and coalesce(j.recent_margin, 0) < 0.08) as margin_low_flag,
                        (
                            j.recent_daily_sales >= 1
                            and j.fba_sellable_inventory > 0
                            and j.fba_sellable_inventory / nullif(j.recent_daily_sales, 0) < 14
                        ) as stock_short_flag
                    from joined j
                )
                select
                    %(snapshot_date)s as snapshot_date,
                    concat(%(previous_month)s, '_vs_', %(recent_month)s) as comparison_code,
                    'month' as comparison_type,
                    concat(%(previous_month)s, ' vs ', %(recent_month)s) as comparison_label,
                    a.*,
                    case when a.previous_rank is not null and a.recent_rank is not null then a.previous_rank - a.recent_rank else 0 end as rank_delta,
                    case when sales_drop_flag then 'down' when sales_up_flag then 'up' else 'stable' end as sales_trend,
                    case when rank_drop_flag then 'down' when rank_up_flag then 'up' else 'stable' end as rank_trend,
                    case when margin_low_flag then 'low' else 'normal' end as margin_status,
                    case when stock_short_flag then 'short' else 'normal' end as stock_status,
                    concat_ws(',', if(sales_drop_flag, 'sales_drop', null), if(margin_low_flag, 'margin_low', null), if(rank_drop_flag, 'rank_drop', null), if(stock_short_flag, 'stock_short', null)) as alert_types,
                    concat_ws(' / ', if(sales_drop_flag, '销量下滑', null), if(margin_low_flag, '低毛利', null), if(rank_drop_flag, '排名下滑', null), if(stock_short_flag, '库存偏低', null)) as alert_labels,
                    case
                        when sales_drop_flag then 'sales_drop'
                        when margin_low_flag then 'margin_low'
                        when rank_drop_flag then 'rank_drop'
                        when stock_short_flag then 'stock_short'
                        else 'observe'
                    end as primary_type,
                    case
                        when sales_drop_flag then 0
                        when margin_low_flag then 1
                        when rank_drop_flag then 2
                        when stock_short_flag then 3
                        else 9
                    end as priority,
                    (sales_drop_flag or margin_low_flag or rank_drop_flag or stock_short_flag) as has_alert
                from classified a
                where a.filter_flag = 1
                  and (sales_drop_flag or margin_low_flag or rank_drop_flag or stock_short_flag)
                  and {filter_sql}
                """,
                params,
            )
            for row in cursor.fetchall():
                if not first_row:
                    first_row = row
                items.append(self._build_precomputed_alert_item(row))

            if not first_row:
                cursor.execute(
                    f"""
                    select
                        %(snapshot_date)s as snapshot_date,
                        'month' as comparison_type,
                        %(recent_month)s as comparison_code,
                        %(recent_month)s as comparison_label,
                        data_start as recent_start,
                        data_end as recent_end,
                        stat_days as recent_days,
                        data_start as previous_start,
                        data_end as previous_end,
                        stat_days as previous_days
                    from {rendered_table}
                    where snapshot_date = %(snapshot_date)s
                      and month_code = %(recent_month)s
                    limit 1
                    """,
                    params,
                )
                first_row = cursor.fetchone() or {}

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
        filtered = self._apply_transition_filter(filtered, transition_filter)
        filtered.sort(key=lambda item: (item["priority"], item["title"]))
        summary = {key: 0 for key in priority}
        for item in filtered:
            for key in item["alert_types"]:
                if key in summary:
                    summary[key] += 1
        return {
            "items": filtered,
            "summary": summary,
            "analysis": self._build_alert_analysis(filtered, summary, analysis_focus_type),
            "window": self._alert_window_text(first_row, recent=True),
            "comparison_window": self._alert_window_text(first_row, recent=False),
            "compare_days": 0,
            "comparison_code": f"{previous_month}_vs_{recent_month}",
            "comparison_mode": "month",
            "comparison_type": "month",
            "comparison_label": f"{previous_month} vs {recent_month}",
            "previous_month": previous_month,
            "recent_month": recent_month,
            "available_comparisons": self._fetch_alert_comparison_options(conn, self._latest_alert_comparison_snapshot(conn, "d7")),
            "available_months": available_months,
            "empty_text": "当前筛选下没有明显异常。",
        }

    def _alert_window_text(self, row: dict[str, Any], recent: bool) -> str:
        if not row:
            return ""
        prefix = "当前" if recent else "对比"
        start_key = "recent_start" if recent else "previous_start"
        end_key = "recent_end" if recent else "previous_end"
        days_key = "recent_days" if recent else "previous_days"
        start = row.get(start_key)
        end = row.get(end_key)
        if not start or not end:
            return ""
        return f"{prefix} {format_day(start)} ~ {format_day(end)}（{to_int(row.get(days_key))}天）"

    def _build_precomputed_alert_item(self, row: dict[str, Any]) -> dict[str, Any]:
        alert_types = [item for item in str(row.get("alert_types") or "").split(",") if item]
        labels = [item for item in str(row.get("alert_labels") or "").split(" / ") if item]
        recent_qty = to_float(row.get("recent_sales_qty"))
        previous_qty = to_float(row.get("previous_sales_qty"))
        recent_daily_sales = to_float(row.get("recent_daily_sales"))
        previous_daily_sales = to_float(row.get("previous_daily_sales"))
        sales_change = to_float(row.get("sales_change_rate"))
        previous_rank_raw = row.get("previous_rank")
        recent_rank_raw = row.get("recent_rank")
        previous_rank = int(round(to_float(previous_rank_raw))) if previous_rank_raw is not None else None
        recent_rank = int(round(to_float(recent_rank_raw))) if recent_rank_raw is not None else None
        previous_margin_raw = row.get("previous_margin")
        recent_margin_raw = row.get("recent_margin")
        previous_margin = to_float(previous_margin_raw) if previous_margin_raw is not None else None
        recent_margin = to_float(recent_margin_raw) if recent_margin_raw is not None else None
        comparison_type = str(row.get("comparison_type") or "days")
        sales_text = (
            f"日均 {recent_daily_sales:.2f} / {previous_daily_sales:.2f}（总量 {recent_qty:.0f} / {previous_qty:.0f}，{sales_change:+.1%}）"
            if comparison_type in {"month_to_date", "month"}
            else f"{recent_qty:.0f} / {previous_qty:.0f}（{sales_change:+.1%}）"
        )
        sellable_days = to_float(row.get("sellable_days"))
        daily_sales = recent_daily_sales
        primary_type = str(row.get("primary_type") or "observe")
        tone = "negative" if primary_type in {"sales_drop", "stock_short"} else "warning"
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
            "priority": to_int(row.get("priority")),
            "has_alert": bool(row.get("has_alert")),
            "sales_trend": str(row.get("sales_trend") or "stable"),
            "rank_trend": str(row.get("rank_trend") or "stable"),
            "margin_status": str(row.get("margin_status") or "normal"),
            "stock_status": str(row.get("stock_status") or "normal"),
            "recent_qty": round(recent_qty, 2),
            "previous_qty": round(previous_qty, 2),
            "recent_daily_sales": round(recent_daily_sales, 2),
            "previous_daily_sales": round(previous_daily_sales, 2),
            "sales_change_rate": round(sales_change, 4),
            "sales_amount": round(to_float(row.get("recent_sales_amount")), 2),
            "recent_sales_amount": round(to_float(row.get("recent_sales_amount")), 2),
            "previous_sales_amount": round(to_float(row.get("previous_sales_amount")), 2),
            "recent_daily_sales_amount": round(to_float(row.get("recent_daily_sales_amount")), 2),
            "previous_daily_sales_amount": round(to_float(row.get("previous_daily_sales_amount")), 2),
            "previous_rank": previous_rank,
            "recent_rank": recent_rank,
            "rank_delta": round(to_float(row.get("rank_delta")), 2),
            "previous_margin": round(previous_margin, 4) if previous_margin is not None else None,
            "recent_margin": round(recent_margin, 4) if recent_margin is not None else None,
            "previous_margin_layer": self._margin_layer(previous_margin),
            "recent_margin_layer": self._margin_layer(recent_margin),
            "previous_rank_layer": self._rank_layer(previous_rank),
            "recent_rank_layer": self._rank_layer(recent_rank),
            "sellable_days": round(sellable_days, 1),
            "daily_sales": round(daily_sales, 2),
            "comparison_type": comparison_type,
            "sales_text": sales_text,
            "rank_text": f"{previous_rank or '—'} -> {recent_rank or '—'}",
            "margin_text": f"{(recent_margin or 0):.1%} / {compact_amount(to_float(row.get('recent_sales_amount')))}",
            "stock_text": f"{sellable_days:.1f} 天 / 日销 {daily_sales:.1f}" if sellable_days or daily_sales else "—",
        }

    def _fetch_opportunity_pool(
        self,
        conn,
        window: PeriodWindow,
        filters: dict[str, Any],
        compare_days: int = 14,
        opportunity_type: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
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
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.sales_amount else 0 end) as recent_sales_amount,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.sales_amount else 0 end) as previous_sales_amount,
                    sum(case when d.dt_date between %(recent_start)s and %(recent_end)s then d.order_gross_profit else 0 end) as recent_order_gross_profit,
                    sum(case when d.dt_date between %(previous_start)s and %(previous_end)s then d.order_gross_profit else 0 end) as previous_order_gross_profit,
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
        return self._build_opportunity_payload(
            items,
            opportunity_type=opportunity_type,
            stock_status=stock_status,
            transition_filter=transition_filter,
            window=f"近{days}天 {format_day(recent_start)} ~ {format_day(recent_end)}",
            comparison_window=f"前{days}天 {format_day(previous_start)} ~ {format_day(previous_end)}",
            compare_days=days,
            comparison_code=f"d{days}",
            comparison_mode="days",
        )

    def _build_opportunity_payload(
        self,
        items: list[dict[str, Any]],
        *,
        opportunity_type: str,
        stock_status: str,
        transition_filter: str,
        window: str,
        comparison_window: str,
        compare_days: int,
        comparison_code: str,
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        available_months: list[dict[str, Any]] | None = None,
        empty_text: str = "当前筛选下没有符合加码条件的机会 SKU。",
    ) -> dict[str, Any]:
        items = [item for item in items if item["opportunity_types"]]
        if opportunity_type != "all":
            items = [item for item in items if opportunity_type in item["opportunity_types"]]
        if stock_status == "enough":
            items = [item for item in items if item["stock_status"] == "enough"]
        elif stock_status == "short":
            items = [item for item in items if item["stock_status"] == "short"]
        items = self._apply_transition_filter(items, transition_filter)
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
            "analysis": self._build_opportunity_analysis(items, summary),
            "stats": {
                "total": len(items),
                "high_margin_scale": summary.get("high_margin_scale", 0),
                "rank_improve": summary.get("rank_improve", 0),
                "inventory_push": summary.get("inventory_push", 0),
                "estimated_boost_revenue": round(boost_revenue, 2),
            },
            "types": type_defs,
            "window": window,
            "comparison_window": comparison_window,
            "compare_days": compare_days,
            "comparison_code": comparison_code,
            "comparison_mode": comparison_mode,
            "comparison_type": comparison_mode,
            "previous_month": previous_month,
            "recent_month": recent_month,
            "available_comparisons": [
                {"code": "d7", "label": "近7天 vs 前7天", "type": "days"},
                {"code": "d14", "label": "近14天 vs 前14天", "type": "days"},
                {"code": "d30", "label": "近30天 vs 前30天", "type": "days"},
                {"code": "d60", "label": "近60天 vs 前60天", "type": "days"},
                {"code": "d90", "label": "近90天 vs 前90天", "type": "days"},
            ],
            "available_months": available_months or [],
            "empty_text": empty_text,
        }


    def _latest_opportunity_comparison_snapshot(self, conn, comparison_code: str) -> date | None:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select max(snapshot_date) as snapshot_date
                    from {render_sql(OPPORTUNITY_COMPARISON_TABLE, self.schemas)}
                    where comparison_code = %(comparison_code)s
                    """,
                    {"comparison_code": comparison_code},
                )
                row = cursor.fetchone() or {}
            return row.get("snapshot_date")
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return None
            raise

    def _fetch_opportunity_pool_snapshot(
        self,
        conn,
        filters: dict[str, Any],
        comparison_code: str,
        compare_days: int,
        opportunity_type: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
        comparison_mode: str = "days",
        previous_month: str = "",
        recent_month: str = "",
        available_months: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        snapshot_date = self._latest_opportunity_comparison_snapshot(conn, comparison_code)
        if not snapshot_date:
            return None

        filter_sql, params = self._filter_clause(filters, alias="o")
        params.update({"snapshot_date": snapshot_date, "comparison_code": comparison_code})
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select o.*
                    from {render_sql(OPPORTUNITY_COMPARISON_TABLE, self.schemas)} o
                    where o.snapshot_date = %(snapshot_date)s
                      and o.comparison_code = %(comparison_code)s
                      and o.filter_flag = 1
                      and {filter_sql}
                    order by o.score desc, o.recent_sales_amount desc, o.seller_sku_adj
                    """,
                    params,
                )
                rows = cursor.fetchall()
        except pymysql.err.ProgrammingError as exc:
            if exc.args and exc.args[0] == 1146:
                return None
            raise

        items = [self._build_precomputed_opportunity_item(row) for row in rows]
        first_row = rows[0] if rows else {}
        return self._build_opportunity_payload(
            items,
            opportunity_type=opportunity_type,
            stock_status=stock_status,
            transition_filter=transition_filter,
            window=self._opportunity_window_text(first_row, recent=True, fallback=f"近{compare_days}天"),
            comparison_window=self._opportunity_window_text(first_row, recent=False, fallback=f"前{compare_days}天"),
            compare_days=compare_days,
            comparison_code=comparison_code,
            comparison_mode=comparison_mode,
            previous_month=previous_month or str(first_row.get("previous_month") or ""),
            recent_month=recent_month or str(first_row.get("recent_month") or ""),
            available_months=available_months,
        )

    def _opportunity_window_text(self, row: dict[str, Any], recent: bool, fallback: str = "") -> str:
        if not row:
            return fallback
        if str(row.get("comparison_mode") or "") == "month":
            month = row.get("recent_month") if recent else row.get("previous_month")
            prefix = "观察月份" if recent else "对比月份"
            return f"{prefix} {month}" if month else fallback
        start = row.get("recent_start") if recent else row.get("previous_start")
        end = row.get("recent_end") if recent else row.get("previous_end")
        prefix = "观察" if recent else "对比"
        if start and end:
            return f"{prefix} {format_day(start)} ~ {format_day(end)}"
        return fallback

    def _build_precomputed_opportunity_item(self, row: dict[str, Any]) -> dict[str, Any]:
        primary_type = str(row.get("primary_type") or "observe")
        types = [item for item in str(row.get("opportunity_types") or "").split(",") if item]
        if not types and primary_type != "observe":
            types = [primary_type]
        comparison_mode = str(row.get("comparison_mode") or "days")
        previous_qty = to_float(row.get("previous_sales_qty"))
        recent_qty = to_float(row.get("recent_sales_qty"))
        previous_daily_sales = to_float(row.get("previous_daily_sales"))
        recent_daily_sales = to_float(row.get("recent_daily_sales"))
        sales_change_rate = to_float(row.get("sales_change_rate"))
        previous_rank_raw = row.get("previous_rank")
        recent_rank_raw = row.get("recent_rank")
        previous_rank = int(round(to_float(previous_rank_raw))) if previous_rank_raw is not None else None
        recent_rank = int(round(to_float(recent_rank_raw))) if recent_rank_raw is not None else None
        recent_sales_amount = to_float(row.get("recent_sales_amount"))
        recent_profit = to_float(row.get("recent_order_gross_profit"))
        margin = to_float(row.get("recent_margin"))
        previous_margin_raw = row.get("previous_margin")
        previous_margin = to_float(previous_margin_raw) if previous_margin_raw is not None else None
        recent_margin_raw = row.get("recent_margin")
        recent_margin = to_float(recent_margin_raw) if recent_margin_raw is not None else None
        sales_text = (
            f"日均 {recent_daily_sales:.2f} / {previous_daily_sales:.2f}（总量 {recent_qty:.0f} / {previous_qty:.0f}，{sales_change_rate:+.1%}）"
            if comparison_mode == "month"
            else f"{recent_qty:.0f} / {previous_qty:.0f} ({sales_change_rate:+.1%})"
        )
        return {
            "type": primary_type,
            "opportunity_types": types,
            "label": self._opportunity_label(primary_type),
            "score": to_int(row.get("score")),
            "msku": str(row.get("seller_sku_adj") or "-"),
            "store": str(row.get("seller_name_new") or "-"),
            "country": str(row.get("country") or "-"),
            "keyword": str(row.get("seller_sku_adj") or ""),
            "daily_sales": round(recent_daily_sales, 2),
            "sales_change_rate": round(sales_change_rate, 4),
            "recent_qty": round(recent_qty, 2),
            "previous_qty": round(previous_qty, 2),
            "sales_text": sales_text,
            "scoped_revenue": round(recent_sales_amount, 2),
            "profit": round(recent_profit, 2),
            "margin": round(margin, 4),
            "previous_margin": round(previous_margin, 4) if previous_margin is not None else None,
            "recent_margin": round(recent_margin, 4) if recent_margin is not None else None,
            "previous_margin_layer": self._margin_layer(previous_margin),
            "recent_margin_layer": self._margin_layer(recent_margin),
            "previous_rank": previous_rank,
            "recent_rank": recent_rank,
            "previous_rank_layer": self._rank_layer(previous_rank),
            "recent_rank_layer": self._rank_layer(recent_rank),
            "rank_text": f"{previous_rank or '—'} -> {recent_rank or '—'}",
            "rank_delta": to_float(row.get("rank_delta")),
            "recent_sessions": 0,
            "conversion": 0,
            "fba_sellable_inventory": round(to_float(row.get("fba_sellable_inventory"))),
            "sellable_days": round(to_float(row.get("sellable_days")), 1),
            "stock_status": str(row.get("stock_status") or "short"),
            "acos": round(to_float(row.get("acos")), 4),
            "tacos": round(to_float(row.get("tacos")), 4),
            "ad_spend": round(to_float(row.get("ad_spend")), 2),
            "current_price": round(to_float(row.get("current_price")), 2),
            "limit_price_35": round(to_float(row.get("limit_price")), 2),
            "limit_price_10": round(to_float(row.get("limit_price_10")), 2),
            "over_limit": bool(row.get("over_limit_flag")),
            "estimated_boost_revenue": round(to_float(row.get("estimated_boost_revenue")), 2),
            "suggested_action": self._opportunity_action(primary_type),
        }

    def _fetch_opportunity_pool_precomputed(
        self,
        conn,
        filters: dict[str, Any],
        comparison_code: str,
        compare_days: int,
        opportunity_type: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        snapshot_date = self._latest_alert_comparison_snapshot(conn, comparison_code)
        if not snapshot_date:
            return self._build_opportunity_payload(
                [],
                opportunity_type=opportunity_type,
                stock_status=stock_status,
                transition_filter=transition_filter,
                window="",
                comparison_window="",
                compare_days=compare_days,
                comparison_code=comparison_code,
                empty_text="当前比较口径暂无机会数据。",
            )

        period_snapshot_date = self._get_latest_snapshot_date(conn)
        period_table = self._render_period_table(PERIOD_PRESET_TABLES["last_90_days"])
        filter_sql, params = self._filter_clause(filters, alias="a")
        params.update({"snapshot_date": snapshot_date, "comparison_code": comparison_code, "period_snapshot_date": period_snapshot_date})
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    a.item_key,
                    a.seller_sku_adj,
                    a.seller_name_new,
                    a.country,
                    a.recent_sales_qty as sales_qty,
                    a.recent_sales_amount as sales_amount,
                    a.recent_order_gross_profit as order_gross_profit,
                    a.recent_margin as order_gross_margin,
                    a.recent_daily_sales as daily_sales,
                    coalesce(a.fba_sellable_inventory, 0) as fba_sellable_inventory,
                    coalesce(p.current_price, 0) as current_price,
                    coalesce(p.limit_price, 0) as limit_price,
                    coalesce(p.limit_price_10, 0) as limit_price_10,
                    coalesce(p.over_limit_flag, a.over_limit_flag, 0) as over_limit_flag,
                    coalesce(p.ad_spend, 0) as ad_spend,
                    coalesce(p.ad_sales, 0) as ad_sales,
                    coalesce(p.acos, 0) as acos,
                    coalesce(p.tacos, 0) as tacos,
                    a.recent_sales_qty as recent_sales_qty,
                    a.previous_sales_qty as previous_sales_qty,
                    a.recent_sales_amount as recent_sales_amount,
                    a.previous_sales_amount as previous_sales_amount,
                    a.recent_daily_sales as recent_daily_sales,
                    a.previous_daily_sales as previous_daily_sales,
                    a.recent_order_gross_profit as recent_order_gross_profit,
                    a.previous_order_gross_profit as previous_order_gross_profit,
                    a.recent_margin as recent_margin,
                    a.previous_margin as previous_margin,
                    a.recent_rank as recent_rank,
                    a.previous_rank as previous_rank,
                    0 as recent_sessions,
                    0 as previous_sessions,
                    'days' as comparison_type
                from {render_sql(ALERT_COMPARISON_TABLE, self.schemas)} a
                left join {period_table} p
                  on p.snapshot_date = %(period_snapshot_date)s
                 and p.item_key = a.item_key
                where a.snapshot_date = %(snapshot_date)s
                  and a.comparison_code = %(comparison_code)s
                  and a.filter_flag = 1
                  and {filter_sql}
                """,
                params,
            )
            rows = cursor.fetchall()

        items = [self._build_opportunity_item(row, compare_days) for row in rows]
        return self._build_opportunity_payload(
            items,
            opportunity_type=opportunity_type,
            stock_status=stock_status,
            transition_filter=transition_filter,
            window=f"近{compare_days}天",
            comparison_window=f"前{compare_days}天",
            compare_days=compare_days,
            comparison_code=comparison_code,
            comparison_mode="days",
        )

    def _fetch_opportunity_pool_monthly(
        self,
        conn,
        filters: dict[str, Any],
        previous_month: str = "",
        recent_month: str = "",
        opportunity_type: str = "all",
        stock_status: str = "all",
        transition_filter: str = "",
    ) -> dict[str, Any]:
        snapshot_date = self._latest_alert_monthly_snapshot(conn)
        available_months = self._fetch_alert_month_options(conn, snapshot_date)
        previous_month, recent_month = self._resolve_alert_month_pair(available_months, previous_month, recent_month)
        comparison_code = f"{previous_month}_vs_{recent_month}" if previous_month and recent_month else ""
        if comparison_code:
            payload = self._fetch_opportunity_pool_snapshot(
                conn,
                filters,
                comparison_code=comparison_code,
                compare_days=0,
                opportunity_type=opportunity_type,
                stock_status=stock_status,
                transition_filter=transition_filter,
                comparison_mode="month",
                previous_month=previous_month,
                recent_month=recent_month,
                available_months=available_months,
            )
            if payload is not None:
                return payload
        if not snapshot_date or not previous_month or not recent_month:
            return self._build_opportunity_payload(
                [],
                opportunity_type=opportunity_type,
                stock_status=stock_status,
                transition_filter=transition_filter,
                window="",
                comparison_window="",
                compare_days=0,
                comparison_code="",
                comparison_mode="month",
                previous_month=previous_month,
                recent_month=recent_month,
                available_months=available_months,
                empty_text="当前月度对比暂无机会数据。",
            )

        period_snapshot_date = self._get_latest_snapshot_date(conn)
        period_table = self._render_period_table(PERIOD_PRESET_TABLES["last_90_days"])
        filter_sql, params = self._filter_clause(filters, alias="a")
        params.update({
            "snapshot_date": snapshot_date,
            "previous_month": previous_month,
            "recent_month": recent_month,
            "period_snapshot_date": period_snapshot_date,
        })
        monthly_table = render_sql(ALERT_MONTHLY_METRIC_TABLE, self.schemas)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                with joined as (
                    select
                        coalesce(r.item_key, p.item_key) as item_key,
                        coalesce(r.seller_name_new, p.seller_name_new) as seller_name_new,
                        coalesce(r.seller_name, p.seller_name) as seller_name,
                        coalesce(r.seller_sku_adj, p.seller_sku_adj) as seller_sku_adj,
                        coalesce(r.country_category, p.country_category) as country_category,
                        coalesce(r.country, p.country) as country,
                        coalesce(r.local_sku, p.local_sku) as local_sku,
                        coalesce(r.filter_flag, p.filter_flag, 1) as filter_flag,
                        coalesce(r.over_limit_flag, p.over_limit_flag, 0) as over_limit_flag,
                        coalesce(r.daily_sales_band, '日销 0') as daily_sales_band,
                        coalesce(r.margin_band, p.margin_band, '毛利率 <0%') as margin_band,
                        coalesce(r.data_start, p.data_start) as recent_start,
                        coalesce(r.data_end, p.data_end) as recent_end,
                        coalesce(r.stat_days, 0) as recent_days,
                        coalesce(p.data_start, r.data_start) as previous_start,
                        coalesce(p.data_end, r.data_end) as previous_end,
                        coalesce(p.stat_days, 0) as previous_days,
                        coalesce(r.sales_qty, 0) as recent_sales_qty,
                        coalesce(p.sales_qty, 0) as previous_sales_qty,
                        coalesce(r.daily_sales, 0) as recent_daily_sales,
                        coalesce(p.daily_sales, 0) as previous_daily_sales,
                        coalesce(r.sales_amount, 0) as recent_sales_amount,
                        coalesce(p.sales_amount, 0) as previous_sales_amount,
                        coalesce(r.order_gross_profit, 0) as recent_order_gross_profit,
                        coalesce(p.order_gross_profit, 0) as previous_order_gross_profit,
                        r.margin as recent_margin,
                        p.margin as previous_margin,
                        r.avg_rank as recent_rank,
                        p.avg_rank as previous_rank,
                        coalesce(r.fba_sellable_inventory, p.fba_sellable_inventory, 0) as fba_sellable_inventory
                    from {monthly_table} r
                    left join {monthly_table} p
                      on p.snapshot_date = r.snapshot_date
                     and p.item_key = r.item_key
                     and p.month_code = %(previous_month)s
                    where r.snapshot_date = %(snapshot_date)s
                      and r.month_code = %(recent_month)s
                    union all
                    select
                        p.item_key, p.seller_name_new, p.seller_name, p.seller_sku_adj, p.country_category, p.country, p.local_sku,
                        p.filter_flag, p.over_limit_flag, '日销 0', p.margin_band,
                        p.data_start, p.data_end, 0,
                        p.data_start, p.data_end, p.stat_days,
                        0, p.sales_qty, 0, p.daily_sales, 0, p.sales_amount, 0, p.order_gross_profit,
                        null, p.margin, null, p.avg_rank, p.fba_sellable_inventory
                    from {monthly_table} p
                    left join {monthly_table} r
                      on r.snapshot_date = p.snapshot_date
                     and r.item_key = p.item_key
                     and r.month_code = %(recent_month)s
                    where p.snapshot_date = %(snapshot_date)s
                      and p.month_code = %(previous_month)s
                      and r.item_key is null
                )
                select
                    j.*,
                    coalesce(ps.current_price, 0) as current_price,
                    coalesce(ps.limit_price, 0) as limit_price,
                    coalesce(ps.limit_price_10, 0) as limit_price_10,
                    coalesce(ps.over_limit_flag, j.over_limit_flag, 0) as over_limit_flag,
                    coalesce(ps.ad_spend, 0) as ad_spend,
                    coalesce(ps.ad_sales, 0) as ad_sales,
                    coalesce(ps.acos, 0) as acos,
                    coalesce(ps.tacos, 0) as tacos,
                    0 as recent_sessions,
                    0 as previous_sessions,
                    'month' as comparison_type
                from joined j
                left join {period_table} ps
                  on ps.snapshot_date = %(period_snapshot_date)s
                 and ps.item_key = j.item_key
                where j.filter_flag = 1
                  and {filter_sql}
                """,
                params,
            )
            rows = cursor.fetchall()

        items = [self._build_opportunity_item(row, 0) for row in rows]
        return self._build_opportunity_payload(
            items,
            opportunity_type=opportunity_type,
            stock_status=stock_status,
            transition_filter=transition_filter,
            window=f"观察月份 {recent_month}",
            comparison_window=f"对比月份 {previous_month}",
            compare_days=0,
            comparison_code=f"{previous_month}_vs_{recent_month}",
            comparison_mode="month",
            previous_month=previous_month,
            recent_month=recent_month,
            available_months=available_months,
        )

    def _margin_layer(self, margin: float | None) -> str:
        if margin is None:
            return "\u65e0\u6bdb\u5229"
        if margin == 0:
            return "\u65e0\u6bdb\u5229"
        if margin < 0:
            return "<0%"
        if margin < 0.10:
            return "0-10%"
        if margin < 0.15:
            return "10-15%"
        if margin < 0.25:
            return "15-25%"
        if margin < 0.35:
            return "25-35%"
        return ">35%"

    def _rank_layer(self, rank: int | None) -> str:
        if not rank or rank <= 0:
            return "无排名"
        if rank <= 50:
            return "1-50"
        if rank <= 100:
            return "51-100"
        if rank <= 200:
            return "101-200"
        if rank <= 500:
            return "201-500"
        return ">500"

    def _apply_transition_filter(self, items: list[dict[str, Any]], raw_filter: str | None) -> list[dict[str, Any]]:
        if not raw_filter or ":" not in raw_filter or "|" not in raw_filter:
            return items
        kind, value = raw_filter.split(":", 1)
        previous_layer, recent_layer = value.split("|", 1)
        if kind == "margin":
            return [
                item for item in items
                if item.get("previous_margin_layer") == previous_layer
                and item.get("recent_margin_layer") == recent_layer
            ]
        if kind == "rank":
            return [
                item for item in items
                if item.get("previous_rank_layer") == previous_layer
                and item.get("recent_rank_layer") == recent_layer
            ]
        return items

    def _transition_analysis(
        self,
        items: list[dict[str, Any]],
        previous_key: str,
        recent_key: str,
        layers: list[str],
        improvement_order: list[str],
    ) -> dict[str, Any]:
        previous_counts = {layer: 0 for layer in layers}
        recent_counts = {layer: 0 for layer in layers}
        link_counts: dict[tuple[str, str], int] = {}
        improvement_index = {layer: index for index, layer in enumerate(improvement_order)}
        summary = {"improved": 0, "worsened": 0, "stable": 0, "missing": 0}

        for item in items:
            previous_layer = item.get(previous_key) or layers[0]
            recent_layer = item.get(recent_key) or layers[0]
            previous_counts.setdefault(previous_layer, 0)
            recent_counts.setdefault(recent_layer, 0)
            previous_counts[previous_layer] += 1
            recent_counts[recent_layer] += 1
            link_counts[(previous_layer, recent_layer)] = link_counts.get((previous_layer, recent_layer), 0) + 1

            if previous_layer not in improvement_index or recent_layer not in improvement_index:
                summary["missing"] += 1
            elif improvement_index[recent_layer] > improvement_index[previous_layer]:
                summary["improved"] += 1
            elif improvement_index[recent_layer] < improvement_index[previous_layer]:
                summary["worsened"] += 1
            else:
                summary["stable"] += 1

        total = max(len(items), 1)
        rows = []
        for layer in layers:
            previous_count = previous_counts.get(layer, 0)
            recent_count = recent_counts.get(layer, 0)
            rows.append(
                {
                    "layer": layer,
                    "previous_count": previous_count,
                    "recent_count": recent_count,
                    "delta": recent_count - previous_count,
                    "share": round(recent_count / total, 4),
                }
            )

        nodes = (
            [{"name": f"\u200b{layer}", "layer": layer, "period": "previous", "value": previous_counts.get(layer, 0)} for layer in layers]
            + [{"name": f"\u200c{layer}", "layer": layer, "period": "recent", "value": recent_counts.get(layer, 0)} for layer in layers]
        )
        nodes = [node for node in nodes if node["value"] > 0]
        links = [
            {
                "source": f"\u200b{source}",
                "target": f"\u200c{target}",
                "value": value,
                "transition_filter": f"{source}|{target}",
            }
            for (source, target), value in sorted(link_counts.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1]))
            if value > 0
        ]
        return {"nodes": nodes, "links": links, "rows": rows, "summary": summary}

    def _top_dimension(self, items: list[dict[str, Any]], key: str, value_key: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            name = str(item.get(key) or "-")
            bucket = grouped.setdefault(name, {"name": name, "count": 0, "value": 0.0})
            bucket["count"] += 1
            if value_key:
                bucket["value"] += to_float(item.get(value_key))
        return sorted(grouped.values(), key=lambda row: (-row["value"], -row["count"], row["name"]))[:limit]

    def _type_distribution(self, summary: dict[str, int], labels: dict[str, str], total: int) -> list[dict[str, Any]]:
        denominator = max(total, 1)
        return [
            {
                "key": key,
                "label": labels.get(key, key),
                "count": count,
                "share": round(count / denominator, 4),
            }
            for key, count in summary.items()
        ]

    def _alert_analysis_focus_type(
        self,
        alert_type: str,
        sales_trend: str,
        rank_trend: str,
        margin_status: str,
        stock_status: str,
    ) -> str:
        if alert_type in {"sales_drop", "margin_low", "rank_drop", "stock_short"}:
            return alert_type
        if sales_trend == "down":
            return "sales_drop"
        if rank_trend == "down":
            return "rank_drop"
        if margin_status == "low":
            return "margin_low"
        if stock_status == "short":
            return "stock_short"
        return "all"

    def _alert_combo_distribution(
        self,
        items: list[dict[str, Any]],
        selected_alert_type: str,
        labels: dict[str, str],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, ...], int] = {}
        ordered_types = ("sales_drop", "margin_low", "rank_drop", "stock_short")
        for item in items:
            types = tuple(key for key in ordered_types if key in item.get("alert_types", []))
            if selected_alert_type not in types:
                continue
            grouped[types] = grouped.get(types, 0) + 1

        denominator = max(sum(grouped.values()), 1)
        rows = []
        for types, count in grouped.items():
            other_types = [key for key in types if key != selected_alert_type]
            label = "\u4ec5" + labels.get(selected_alert_type, selected_alert_type) if not other_types else " + ".join(labels.get(key, key) for key in types)
            rows.append(
                {
                    "key": "combo:" + ",".join(types),
                    "label": label,
                    "count": count,
                    "share": round(count / denominator, 4),
                }
            )
        return sorted(rows, key=lambda row: (-row["count"], row["label"]))

    def _build_alert_analysis(self, items: list[dict[str, Any]], summary: dict[str, int], selected_alert_type: str = "all") -> dict[str, Any]:
        alert_labels = {
            "sales_drop": "\u9500\u91cf\u4e0b\u6ed1",
            "margin_low": "\u4f4e\u6bdb\u5229",
            "rank_drop": "\u6392\u540d\u4e0b\u6ed1",
            "stock_short": "\u5e93\u5b58\u504f\u4f4e",
        }
        sales_states = [("down", "\u9500\u91cf\u4e0b\u964d"), ("stable", "\u9500\u91cf\u7a33\u5b9a"), ("up", "\u9500\u91cf\u4e0a\u6da8")]
        rank_states = [("down", "\u6392\u540d\u4e0b\u964d"), ("stable", "\u6392\u540d\u7a33\u5b9a"), ("up", "\u6392\u540d\u4e0a\u6da8")]
        matrix = []
        for sales_key, sales_label in sales_states:
            for rank_key, rank_label in rank_states:
                count = sum(1 for item in items if item.get("sales_trend") == sales_key and item.get("rank_trend") == rank_key)
                matrix.append({"sales_trend": sales_key, "rank_trend": rank_key, "label": f"{sales_label} / {rank_label}", "count": count})

        margin_layers = MARGIN_TRANSITION_LAYERS
        rank_layers = ["\u65e0\u6392\u540d", "1-50", "51-100", "101-200", "201-500", ">500"]
        return {
            "type_distribution": self._alert_combo_distribution(items, selected_alert_type, alert_labels)
            if selected_alert_type in alert_labels
            else self._type_distribution(summary, alert_labels, len(items)),
            "type_distribution_mode": "combo" if selected_alert_type in alert_labels else "type",
            "site_ranking": self._top_dimension(items, "country"),
            "store_ranking": self._top_dimension(items, "store"),
            "margin_transition": self._transition_analysis(items, "previous_margin_layer", "recent_margin_layer", margin_layers, margin_layers),
            "rank_transition": self._transition_analysis(items, "previous_rank_layer", "recent_rank_layer", rank_layers, list(reversed(rank_layers))),
            "risk_matrix": matrix,
            "risk_scatter": [
                {
                    "name": item.get("title"),
                    "type": item.get("type"),
                    "type_label": item.get("label"),
                    "sales_change_rate": item.get("sales_change_rate", 0),
                    "rank_delta": item.get("rank_delta", 0),
                    "sales_amount": item.get("sales_amount", 0),
                }
                for item in items[:1000]
            ],
        }

    def _build_opportunity_analysis(self, items: list[dict[str, Any]], summary: dict[str, int]) -> dict[str, Any]:
        labels = {item["key"]: item["label"] for item in self._opportunity_type_defs()}
        margin_layers = MARGIN_TRANSITION_LAYERS
        rank_layers = ["无排名", "1-50", "51-100", "101-200", "201-500", ">500"]
        score_bands = [("0-40", 0, 40), ("40-60", 40, 60), ("60-80", 60, 80), ("80-100", 80, 101)]
        stock_bands = [("<14天", 0, 14), ("14-21天", 14, 21), ("21-60天", 21, 60), (">60天", 60, float("inf"))]
        return {
            "type_distribution": self._type_distribution(summary, labels, len(items)),
            "site_ranking": self._top_dimension(items, "country", "estimated_boost_revenue"),
            "store_ranking": self._top_dimension(items, "store", "estimated_boost_revenue"),
            "margin_transition": self._transition_analysis(items, "previous_margin_layer", "recent_margin_layer", margin_layers, margin_layers),
            "rank_transition": self._transition_analysis(items, "previous_rank_layer", "recent_rank_layer", rank_layers, list(reversed(rank_layers))),
            "score_distribution": [
                {"label": label, "count": sum(1 for item in items if low <= to_float(item.get("score")) < high)}
                for label, low, high in score_bands
            ],
            "boost_ranking": self._top_dimension(items, "country", "estimated_boost_revenue"),
            "stock_distribution": [
                {"label": label, "count": sum(1 for item in items if low <= to_float(item.get("sellable_days")) < high)}
                for label, low, high in stock_bands
            ],
            "opportunity_scatter": [
                {
                    "name": item.get("msku"),
                    "type": item.get("type"),
                    "type_label": item.get("label"),
                    "margin": item.get("margin", 0),
                    "daily_sales": item.get("daily_sales", 0),
                    "estimated_boost_revenue": item.get("estimated_boost_revenue", 0),
                }
                for item in items[:1000]
            ],
        }

    def _opportunity_type_defs(self) -> list[dict[str, str]]:
        return [
            {"key": "all", "label": "全部机会", "rule": "展示所有满足机会规则的 SKU，按机会分从高到低排序。"},
            {"key": "high_margin_scale", "label": "高毛利可放量", "rule": "毛利率不低于25%，日销不低于1，可售天数不低于21天，且未超限价。"},
            {"key": "rank_improve", "label": "排名改善", "rule": "近 N 天平均排名较前 N 天改善至少5名，且改善幅度不低于20%。"},
            {"key": "inventory_push", "label": "库存充足待推", "rule": "可售天数不低于30天，毛利率不低于15%，日销不低于0.5。"},
            {"key": "low_sales_high_margin", "label": "低销高毛利", "rule": "毛利率不低于35%，日销低于1，可售天数不低于21天。"},
            {"key": "ad_efficiency", "label": "广告效率可加码", "rule": "TACOS不高于5%或ACOS不高于20%，毛利率不低于20%，且有销售或广告表现。"},
        ]

    def _build_opportunity_item(self, row: dict[str, Any], compare_days: int) -> dict[str, Any]:
        comparison_type = str(row.get("comparison_type") or "days")
        sales_qty = to_float(row.get("sales_qty"))
        sales_amount = to_float(row.get("sales_amount"))
        profit = to_float(row.get("order_gross_profit"))
        margin = to_float(row.get("order_gross_margin", row.get("recent_margin")))
        daily_sales = to_float(row.get("daily_sales"))
        fba_sellable = to_float(row.get("fba_sellable_inventory"))
        sellable_days = fba_sellable / daily_sales if daily_sales > 0 else 0.0
        previous_qty = to_float(row.get("previous_sales_qty"))
        recent_qty = to_float(row.get("recent_sales_qty"))
        previous_daily_sales = to_float(row.get("previous_daily_sales"))
        recent_daily_sales = to_float(row.get("recent_daily_sales"))
        if comparison_type in {"month", "month_to_date"}:
            sales_change_rate = (recent_daily_sales - previous_daily_sales) / previous_daily_sales if previous_daily_sales else (1.0 if recent_daily_sales > 0 else 0.0)
        else:
            sales_change_rate = (recent_qty - previous_qty) / previous_qty if previous_qty else (1.0 if recent_qty > 0 else 0.0)
        previous_sessions = to_float(row.get("previous_sessions"))
        recent_sessions = to_float(row.get("recent_sessions"))
        sessions_change_rate = (recent_sessions - previous_sessions) / previous_sessions if previous_sessions else (1.0 if recent_sessions > 0 else 0.0)
        previous_rank_raw = row.get("previous_rank")
        recent_rank_raw = row.get("recent_rank")
        previous_rank = int(round(to_float(previous_rank_raw))) if previous_rank_raw is not None else None
        recent_rank = int(round(to_float(recent_rank_raw))) if recent_rank_raw is not None else None
        previous_sales_amount = to_float(row.get("previous_sales_amount"))
        recent_sales_amount = to_float(row.get("recent_sales_amount"))
        previous_margin = (
            to_float(row.get("previous_order_gross_profit")) / previous_sales_amount
            if previous_sales_amount
            else None
        )
        recent_margin = (
            to_float(row.get("recent_order_gross_profit")) / recent_sales_amount
            if recent_sales_amount
            else None
        )
        rank_delta = (previous_rank - recent_rank) if previous_rank is not None and recent_rank is not None else 0
        rank_improve_ratio = (rank_delta / previous_rank) if previous_rank else 0.0
        ad_spend = to_float(row.get("ad_spend"))
        ad_sales = to_float(row.get("ad_sales"))
        acos = to_float(row.get("acos"))
        tacos = to_float(row.get("tacos"))
        over_limit = bool(row.get("current_over_limit_flag", row.get("over_limit_flag")))

        types: list[str] = []
        if margin >= 0.25 and daily_sales >= 1 and sellable_days >= 21 and not over_limit:
            types.append("high_margin_scale")
        if rank_delta >= 5 and rank_improve_ratio >= 0.20 and sellable_days >= 14:
            types.append("rank_improve")
        if sellable_days >= 30 and margin >= 0.15 and daily_sales >= 0.5 and not over_limit:
            types.append("inventory_push")
        if margin >= 0.35 and daily_sales < 1 and sellable_days >= 21 and not over_limit:
            types.append("low_sales_high_margin")
        if (tacos <= 0.05 or (acos > 0 and acos <= 0.20)) and margin >= 0.20 and (sales_amount > 0 or ad_spend > 0):
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
        sales_text = (
            f"日均 {recent_daily_sales:.2f} / {previous_daily_sales:.2f}（总量 {recent_qty:.0f} / {previous_qty:.0f}，{sales_change_rate:+.1%}）"
            if comparison_type in {"month", "month_to_date"}
            else f"{recent_qty:.0f} / {previous_qty:.0f} ({sales_change_rate:+.1%})"
        )
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
            "recent_qty": round(recent_qty, 2),
            "previous_qty": round(previous_qty, 2),
            "sales_text": sales_text,
            "scoped_revenue": round(sales_amount, 2),
            "profit": round(profit, 2),
            "margin": round(margin, 4),
            "previous_margin": round(previous_margin, 4) if previous_margin is not None else None,
            "recent_margin": round(recent_margin, 4) if recent_margin is not None else None,
            "previous_margin_layer": self._margin_layer(previous_margin),
            "recent_margin_layer": self._margin_layer(recent_margin),
            "previous_rank": previous_rank,
            "recent_rank": recent_rank,
            "previous_rank_layer": self._rank_layer(previous_rank),
            "recent_rank_layer": self._rank_layer(recent_rank),
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
        previous_sales_amount = to_float(row.get("previous_sales_amount"))
        recent_sales_amount = to_float(row.get("recent_sales_amount"))
        previous_margin = (
            to_float(row.get("previous_order_gross_profit")) / previous_sales_amount
            if previous_sales_amount
            else None
        )
        recent_margin = (
            to_float(row.get("recent_order_gross_profit")) / recent_sales_amount
            if recent_sales_amount
            else None
        )
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
            "recent_qty": round(recent_qty, 2),
            "previous_qty": round(previous_qty, 2),
            "sales_change_rate": round(sales_change, 4),
            "sales_amount": round(sales_amount, 2),
            "previous_rank": previous_rank,
            "recent_rank": recent_rank,
            "rank_delta": (previous_rank - recent_rank) if previous_rank is not None and recent_rank is not None else 0,
            "previous_margin": round(previous_margin, 4) if previous_margin is not None else None,
            "recent_margin": round(recent_margin, 4) if recent_margin is not None else None,
            "previous_margin_layer": self._margin_layer(previous_margin),
            "recent_margin_layer": self._margin_layer(recent_margin),
            "previous_rank_layer": self._rank_layer(previous_rank),
            "recent_rank_layer": self._rank_layer(recent_rank),
            "sellable_days": round(sellable_days, 1),
            "daily_sales": round(daily_sales, 2),
            "sales_text": f"近{compare_days}天 {recent_qty:.0f} / 前{compare_days}天 {previous_qty:.0f}（{sales_change:+.1%}）",
            "rank_text": f"{previous_rank or '—'} -> {recent_rank or '—'}",
            "margin_text": f"{margin:.1%} / {compact_amount(sales_amount)}",
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
