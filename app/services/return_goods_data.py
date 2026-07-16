import math
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pymysql

from etl.replenishment_update import apply_database_ini_env

SALES_ROLES = [("problem", "问题产品"), ("dog", "瘦狗产品"), ("potential", "潜力产品"), ("star", "明星产品")]
STATUS_COLUMNS = [
    ("not_arrived", "断货未到货"),
    ("observe", "观察中"),
    ("operating", "干预中"),
    ("followup_severe", "严重恢复不足"),
    ("followup_improving", "恢复提升中"),
    ("followup_data_insufficient", "数据不足"),
]


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_day(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def number_value(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric
    return value


def to_float(value: Any) -> float:
    numeric = number_value(value)
    if numeric is None:
        return 0.0
    try:
        return float(numeric)
    except (TypeError, ValueError):
        return 0.0


def to_int(value: Any) -> int:
    numeric = number_value(value)
    if numeric is None:
        return 0
    try:
        return int(numeric)
    except (TypeError, ValueError):
        return 0


class ReturnGoodsDataService:
    def __init__(self) -> None:
        apply_database_ini_env()
        self.host = os.getenv("DASHBOARD_DB_HOST", os.getenv("MYSQL_HOST", "127.0.0.1"))
        self.port = int(os.getenv("DASHBOARD_DB_PORT", os.getenv("MYSQL_PORT", "3306")))
        self.user = os.getenv("DASHBOARD_DB_USER", os.getenv("MYSQL_USER", ""))
        self.password = os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
        self.database = os.getenv("DASHBOARD_DB_NAME", os.getenv("MYSQL_DATABASE", "etl_datasync_test"))
        self.charset = os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4")

    def connect(self):
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset=self.charset,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    def get_payload(
        self,
        snapshot_date: str = "",
        period_days: int | str = 1,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
        stage: str = "all",
        warning_type: str = "all",
        quick_filter: str = "all",
        return_day: int | str = 0,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        safe_page = max(1, int(page or 1))
        safe_page_size = max(10, min(100, int(page_size or 20)))
        with self.connect() as conn:
            latest_snapshot = self._latest_snapshot_date(conn)
            if latest_snapshot is None:
                return self._empty_payload(safe_page, safe_page_size)
            safe_period_days = max(1, int(period_days or 1))
            requested_snapshot, period_start, period_end = self._resolve_period(snapshot_date, safe_period_days, latest_snapshot)
            snapshot_day = self._snapshot_for_period(conn, requested_snapshot) or latest_snapshot
            if snapshot_day != requested_snapshot:
                period_start = snapshot_day - timedelta(days=safe_period_days - 1)
                period_end = snapshot_day
            previous_start = period_start - timedelta(days=safe_period_days)
            previous_end = period_start - timedelta(days=1)
            filters, params = self._build_where(
                snapshot_day,
                country_category,
                seller_name_new,
                keyword,
                stage,
                warning_type,
                quick_filter,
                return_day,
            )
            params.update({"start_date": period_start, "end_date": period_end})
            overview_filters, overview_params = self._build_where(
                snapshot_day,
                country_category,
                seller_name_new,
                keyword,
                "all",
                "all",
                "all",
                0,
            )
            overview_params.update({"start_date": period_start, "end_date": period_end})
            overview_summary = self._overview_summary(conn, overview_filters, overview_params)
            overview_summary["stockout_msku_count"] = self._stockout_msku_count(
                conn,
                snapshot_day,
                country_category,
                seller_name_new,
                keyword,
            )
            summary = self._summary(conn, filters, params)
            previous_params = dict(params)
            previous_params.update({"start_date": previous_start, "end_date": previous_end})
            previous_summary = self._summary(conn, filters, previous_params)
            self._attach_period_comparison(summary, previous_summary)
            sales_role_distribution = self._sales_role_distribution(conn, filters, params)
            workbench_rows = self._workbench_rows(conn, filters, params)
            stage_distribution = self._stage_distribution(conn, filters, params)
            warnings = self._warnings(conn, filters, params)
            total = self._total(conn, filters, params)
            total_pages = max(1, math.ceil(total / safe_page_size))
            safe_page = min(safe_page, total_pages)
            items = self._items(conn, filters, params, safe_page, safe_page_size)
            self._attach_listing_previews(conn, snapshot_day, items)
            meta = self._meta(conn)
        return {
            "snapshot_date": format_day(snapshot_day),
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            "previous_start_date": previous_start.isoformat(),
            "previous_end_date": previous_end.isoformat(),
            "period_days": safe_period_days,
            "overview_summary": overview_summary,
            "summary": summary,
            "sales_role_distribution": sales_role_distribution,
            "status_matrix": self._status_matrix(workbench_rows, period_start, period_end),
            "stage_business_compare": self._stage_business_compare(workbench_rows, period_end),
            "priority_queue": self._priority_queue(workbench_rows, period_start, period_end),
            "stage_distribution": stage_distribution,
            "warnings": warnings,
            "items": items,
            "meta": meta,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
        }

    def get_detail(self, snapshot_date: str = "", return_event_id: str = "") -> dict[str, Any]:
        event_id = (return_event_id or "").strip()
        if not event_id:
            return {"event": None, "daily": []}
        with self.connect() as conn:
            snapshot_day = parse_day(snapshot_date) or self._latest_snapshot_date(conn)
            if snapshot_day is None:
                return {"event": None, "daily": []}
            event = self._event_detail(conn, snapshot_day, event_id)
            if not event:
                return {"event": None, "daily": []}
            daily = self._daily_detail(conn, event, snapshot_day)
            country_metrics = self._country_metrics(conn, snapshot_day, event)
        return {"event": event, "daily": daily, "country_metrics": country_metrics}

    def get_stage_detail(
        self,
        snapshot_date: str = "",
        period_days: int | str = 1,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
        stage_key: str = "observe",
    ) -> dict[str, Any]:
        safe_stage = "operating" if stage_key == "operating" else "observe"
        quick_filter = "overview_operating" if safe_stage == "operating" else "overview_observe"
        with self.connect() as conn:
            latest_snapshot = self._latest_snapshot_date(conn)
            if latest_snapshot is None:
                return {"stage_key": safe_stage, "event_count": 0, "groups": []}
            requested_snapshot, period_start, period_end = self._resolve_period(snapshot_date, period_days, latest_snapshot)
            snapshot_day = self._snapshot_for_period(conn, requested_snapshot) or latest_snapshot
            if snapshot_day != requested_snapshot:
                period_start = snapshot_day - timedelta(max(1, int(period_days or 1)) - 1)
                period_end = snapshot_day
            if country_category == "all" and seller_name_new == "all" and not keyword:
                groups = self._stage_daily_summary_groups(conn, snapshot_day, safe_stage)
                if groups:
                    return {
                        "stage_key": safe_stage,
                        "stage": "运营干预期" if safe_stage == "operating" else "观察期",
                        "event_count": self._stage_daily_summary_event_count(conn, snapshot_day, safe_stage),
                        "groups": groups,
                        "source": "summary",
                    }
            filters, params = self._build_where(
                snapshot_day,
                country_category,
                seller_name_new,
                keyword,
                "all",
                "all",
                quick_filter,
            )
            params.update({"start_date": period_start, "end_date": period_end})
            events = self._stage_events(conn, filters, params)
            daily_by_event = {event["return_event_id"]: self._daily_detail(conn, event, snapshot_day) for event in events}
        return {
            "stage_key": safe_stage,
            "stage": "运营干预期" if safe_stage == "operating" else "观察期",
            "event_count": len(events),
            "groups": self._stage_daily_groups(events, daily_by_event, safe_stage),
            "source": "live",
        }

    def _empty_payload(self, page: int, page_size: int) -> dict[str, Any]:
        return {
            "snapshot_date": None,
            "start_date": None,
            "end_date": None,
            "previous_start_date": None,
            "previous_end_date": None,
            "overview_summary": self._serialize_overview_summary({}),
            "summary": self._serialize_summary({}),
            "sales_role_distribution": [],
            "status_matrix": {"roles": [], "statuses": [], "cells": [], "total": 0},
            "stage_business_compare": [],
            "priority_queue": [],
            "stage_distribution": [],
            "warnings": [],
            "items": [],
            "meta": {"dates": [], "country_categories": [], "stores": [], "stages": [], "warning_types": []},
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
        }

    def _latest_snapshot_date(self, conn) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute("select max(snapshot_date) as snapshot_date from dashboard_return_goods_events")
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _snapshot_for_period(self, conn, period_end: date) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select max(snapshot_date) as snapshot_date
                from dashboard_return_goods_events
                where snapshot_date <= %(period_end)s
                """,
                {"period_end": period_end},
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _resolve_period(self, snapshot_date: str, period_days: int | str, latest_snapshot: date) -> tuple[date, date, date]:
        snapshot_day = parse_day(snapshot_date) or latest_snapshot
        safe_days = max(1, int(period_days or 1))
        start_day = snapshot_day - timedelta(days=safe_days - 1)
        return snapshot_day, start_day, snapshot_day

    def _build_where(
        self,
        snapshot_date: date,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
        stage: str = "all",
        warning_type: str = "all",
        quick_filter: str = "all",
        return_day: int | str = 0,
    ) -> tuple[str, dict[str, Any]]:
        clauses = [
            "snapshot_date = %(snapshot_date)s",
            "seller_sku_adj not like %(excluded_msku_pattern)s",
            "item_key in (select item_key from dashboard_return_goods_stockout_pool where snapshot_date = %(snapshot_date)s)",
        ]
        params: dict[str, Any] = {"snapshot_date": snapshot_date, "excluded_msku_pattern": "amzn.gr.%"}
        if country_category and country_category != "all":
            clauses.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if seller_name_new and seller_name_new != "all":
            clauses.append("seller_name_new = %(seller_name_new)s")
            params["seller_name_new"] = seller_name_new
        if keyword:
            clauses.append("(seller_sku_adj like %(keyword)s or coalesce(local_sku, '') like %(keyword)s)")
            params["keyword"] = f"%{keyword.strip()}%"
        if stage and stage != "all":
            clauses.append("stage = %(stage)s")
            params["stage"] = stage
        if warning_type and warning_type != "all":
            clauses.append("warning_type = %(warning_type)s")
            params["warning_type"] = warning_type
        safe_return_day = int(return_day or 0)
        if safe_return_day > 0:
            clauses.append("return_days = %(return_day)s")
            params["return_day"] = safe_return_day
        role_conditions = {
            "problem": "pre_stockout_sales_role = '问题产品'",
            "dog": "pre_stockout_sales_role = '瘦狗产品'",
            "potential": "pre_stockout_sales_role = '潜力产品'",
            "star": "pre_stockout_sales_role = '明星产品'",
        }
        status_conditions = {
            "not_arrived": "coalesce(current_fba_sellable, 0) = 0 and coalesce(current_fba_inbound, 0) > 0",
            "receiving": "coalesce(current_fba_sellable, 0) > 0 and coalesce(current_fba_sellable, 0) <= 5 and coalesce(current_fba_inbound, 0) > 0",
            "observe": "return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s) and stage = '观察期'",
            "operating": "return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s) and stage = '运营干预期'",
            "manual": "exit_date between %(start_date)s and %(end_date)s and exit_reason = '待人工判断'",
            "recovery_insufficient": "exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate >= 0.5 and sales_recovery_rate < 0.7",
            "over21_low_recovery": "exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate is not null and sales_recovery_rate < 0.5",
            "followup_improving": "recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate >= 0.5 and cumulative_avg_recovery_rate < 0.7",
            "followup_severe": "recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5",
            "followup_stable": "recovery_followup_flag = 1 and exit_date is null and current_stable_recovery_flag = 1",
            "followup_data_insufficient": "recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is null",
        }
        matrix_status_conditions = {
            "followup_severe": status_conditions["followup_severe"],
            "followup_improving": status_conditions["followup_improving"],
            "followup_data_insufficient": status_conditions["followup_data_insufficient"],
            "operating": status_conditions["operating"],
            "observe": status_conditions["observe"],
            "not_arrived": (
                status_conditions["not_arrived"]
                + " and not (" + status_conditions["followup_severe"] + ")"
                + " and not (" + status_conditions["followup_improving"] + ")"
                + " and not (" + status_conditions["followup_data_insufficient"] + ")"
                + " and not (" + status_conditions["operating"] + ")"
                + " and not (" + status_conditions["observe"] + ")"
            ),
        }
        active_condition = "return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s)"
        latest_event_filter = """
            return_event_id in (
                select return_event_id
                from (
                    select
                        return_event_id,
                        row_number() over (
                            partition by item_key
                            order by return_start_date desc, return_round desc
                        ) as latest_rank
                    from dashboard_return_goods_events
                    where snapshot_date = %(snapshot_date)s
                      and return_start_date <= %(end_date)s
                ) latest_events
                where latest_rank = 1
            )
        """
        in_stockout_pool_filter = """
            item_key in (
                select item_key
                from dashboard_return_goods_stockout_pool
                where snapshot_date = %(snapshot_date)s
            )
        """
        quick_filters = {
            "current_pool": active_condition,
            "receiving": status_conditions["receiving"],
            "not_arrived": status_conditions["not_arrived"],
            "new": "return_start_date between %(start_date)s and %(end_date)s",
            "exit": "exit_date between %(start_date)s and %(end_date)s",
            "success_exit": "exit_date between %(start_date)s and %(end_date)s and exit_reason = '达标退出'",
            "failed_exit": "exit_date between %(start_date)s and %(end_date)s and exit_reason = '未达标退出'",
            "manual_judgment": "exit_date between %(start_date)s and %(end_date)s and exit_reason = '待人工判断'",
            "secondary_stockout": "exit_date between %(start_date)s and %(end_date)s and exit_reason = '二次断货'",
            "overdue": "stage = '超期未处理'",
            "today_operating": "return_days = 8 and (exit_date is null or exit_date > %(end_date)s)",
            "recovery_rate": "sales_recovery_rate is not null",
            "priority_valuable_not_arrived": "pre_stockout_sales_role in ('明星产品', '潜力产品') and " + status_conditions["not_arrived"],
            "priority_valuable_low_recovery": "pre_stockout_sales_role in ('明星产品', '潜力产品') and " + status_conditions["operating"] + " and coalesce(sales_recovery_rate, 0) < 0.7",
            "priority_manual": "exit_reason = '待人工判断'",
            "priority_today_operating": "return_days = 8 and (exit_date is null or exit_date > %(end_date)s)",
            "overview_stockout_msku": in_stockout_pool_filter,
            "overview_returned_msku": latest_event_filter + " and " + in_stockout_pool_filter + " and return_start_date <= %(end_date)s",
            "overview_observe": latest_event_filter + " and " + in_stockout_pool_filter + " and " + active_condition + " and stage = '观察期'",
            "overview_operating": latest_event_filter + " and " + in_stockout_pool_filter + " and " + active_condition + " and stage = '运营干预期'",
            "overview_exited": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s",
            "overview_manual": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and exit_reason = '待人工判断'",
            "overview_secondary": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and exit_reason = '二次断货'",
            "overview_overdue": latest_event_filter + " and " + in_stockout_pool_filter + " and " + active_condition + " and stage = '超期未处理'",
            "overview_receiving": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["receiving"],
            "overview_not_arrived": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["not_arrived"],
            "overview_active": latest_event_filter + " and " + in_stockout_pool_filter + " and " + active_condition,
            "overview_observe_d1_3": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["observe"] + " and return_days between 1 and 3",
            "overview_observe_d4_7": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["observe"] + " and return_days between 4 and 7",
            "overview_observe_ordered": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["observe"] + " and coalesce(post_7d_sales_qty, 0) > 0",
            "overview_observe_not_ordered": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["observe"] + " and coalesce(post_7d_sales_qty, 0) = 0",
            "overview_operating_d8_14": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and return_days between 8 and 14",
            "overview_operating_d15_21": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and return_days between 15 and 21",
            "overview_operating_success_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and sales_recovery_rate >= 0.7",
            "overview_operating_low_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and sales_recovery_rate is not null and sales_recovery_rate < 0.5",
            "overview_operating_recovery_insufficient": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and sales_recovery_rate >= 0.5 and sales_recovery_rate < 0.7",
            "overview_operating_data_insufficient": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["operating"] + " and sales_recovery_rate is null",
            "overview_success_exit": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and exit_reason = '达标退出'",
            "overview_d21_standard_exit": latest_event_filter + " and " + in_stockout_pool_filter + " and coalesce(recovery_followup_flag, 0) = 0 and exit_date is not null and exit_date <= %(end_date)s and exit_reason = '达标退出'",
            "overview_failed_exit": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and exit_reason = '未达标退出'",
            "overview_recovery_insufficient": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate >= 0.5 and sales_recovery_rate < 0.7",
            "overview_no_recovery_21d": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and coalesce(post_recovery_sales_qty, 0) = 0",
            "overview_low_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate > 0 and sales_recovery_rate < 0.3",
            "overview_weak_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate >= 0.3 and sales_recovery_rate < 0.5",
            "overview_high_value_failed": latest_event_filter + " and " + in_stockout_pool_filter + " and pre_stockout_sales_role in ('明星产品', '潜力产品') and " + status_conditions["followup_severe"],
            "overview_data_insufficient": latest_event_filter + " and " + in_stockout_pool_filter + " and exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate is null",
            "overview_current_severe_low_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"],
            "overview_recovery_improving": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_improving"],
            "overview_started_stable_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and recovery_followup_flag = 1 and exit_date is null and stable_recovery_start_date is not null",
            "overview_current_stable_recovery": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_stable"],
            "overview_recovery_fallback": latest_event_filter + " and " + in_stockout_pool_filter + " and recovery_followup_flag = 1 and exit_date is null and recovery_fallback_flag = 1",
            "overview_late_standard_exit": latest_event_filter + " and " + in_stockout_pool_filter + " and recovery_followup_flag = 1 and exit_date is not null and exit_date <= %(end_date)s and recovery_followup_status = '21天后恢复达标'",
            "overview_followup_data_insufficient": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_data_insufficient"],
            "overview_followup_active": latest_event_filter + " and " + in_stockout_pool_filter + " and recovery_followup_flag = 1 and exit_date is null",
            "overview_followup_no_sales_since_return": latest_event_filter + " and " + in_stockout_pool_filter + " and recovery_followup_flag = 1 and exit_date is null and coalesce(post_cumulative_sales_qty, 0) = 0",
            "overview_severe_no_sales": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and coalesce(post_cumulative_sales_qty, 0) = 0",
            "overview_severe_rate_0_10": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and cumulative_avg_recovery_rate > 0 and cumulative_avg_recovery_rate < 0.1",
            "overview_severe_rate_10_30": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and cumulative_avg_recovery_rate >= 0.1 and cumulative_avg_recovery_rate < 0.3",
            "overview_severe_rate_30_50": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and cumulative_avg_recovery_rate >= 0.3 and cumulative_avg_recovery_rate < 0.5",
            "overview_severe_recovery_fallback": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and coalesce(post_cumulative_sales_qty, 0) > 0 and recovery_fallback_flag = 1",
            "overview_severe_current_stable": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and coalesce(post_cumulative_sales_qty, 0) > 0 and coalesce(recovery_fallback_flag, 0) = 0 and current_stable_recovery_flag = 1",
            "overview_severe_never_stable": latest_event_filter + " and " + in_stockout_pool_filter + " and " + status_conditions["followup_severe"] + " and coalesce(post_cumulative_sales_qty, 0) > 0 and coalesce(recovery_fallback_flag, 0) = 0 and coalesce(current_stable_recovery_flag, 0) = 0",
        }
        for role_key, role_sql in role_conditions.items():
            quick_filters[f"role_{role_key}"] = role_sql
            for status_key, _ in STATUS_COLUMNS:
                status_sql = matrix_status_conditions[status_key]
                quick_filters[f"matrix_{role_key}_{status_key}"] = f"{role_sql} and {status_sql}"
        if quick_filter in quick_filters:
            clauses.append(quick_filters[quick_filter])
        return " and ".join(clauses), params

    def _summary(self, conn, filters: str, params: dict[str, Any]) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(distinct item_key) as total_return_msku_count,
                    count(*) as total_return_event_count,
                    sum(case when return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s) then 1 else 0 end) as current_pool_count,
                    count(distinct case when return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s) then item_key end) as current_pool_msku_count,
                    sum(case when coalesce(current_fba_sellable, 0) > 0 and coalesce(current_fba_sellable, 0) <= 5 and coalesce(current_fba_inbound, 0) > 0 then 1 else 0 end) as receiving_count,
                    sum(case when coalesce(current_fba_sellable, 0) = 0 and coalesce(current_fba_inbound, 0) > 0 then 1 else 0 end) as not_arrived_count,
                    sum(case when return_start_date between %(start_date)s and %(end_date)s then 1 else 0 end) as new_count,
                    sum(case when exit_date between %(start_date)s and %(end_date)s then 1 else 0 end) as exit_count,
                    sum(case when exit_date between %(start_date)s and %(end_date)s and exit_reason = '达标退出' then 1 else 0 end) as success_exit_count,
                    sum(case when exit_date between %(start_date)s and %(end_date)s and exit_reason = '未达标退出' then 1 else 0 end) as failed_exit_count,
                    sum(case when exit_date between %(start_date)s and %(end_date)s and exit_reason = '待人工判断' then 1 else 0 end) as manual_judgment_count,
                    sum(case when stage = '超期未处理' then 1 else 0 end) as overdue_count,
                    sum(case when return_days = 8 and (exit_date is null or exit_date > %(end_date)s) then 1 else 0 end) as today_observe_to_operating_count,
                    sum(case when exit_date between %(start_date)s and %(end_date)s and exit_reason = '二次断货' then 1 else 0 end) as secondary_stockout_count,
                    avg(case when sales_recovery_rate is not null then sales_recovery_rate end) as avg_sales_recovery_rate
                from dashboard_return_goods_events
                where {filters}
                  and {self._latest_event_filter()}
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return self._serialize_summary(row)

    def _overview_summary(self, conn, filters: str, params: dict[str, Any]) -> dict[str, Any]:
        active_condition = "return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s)"
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(distinct item_key) as stockout_msku_count,
                    count(distinct case when return_start_date <= %(end_date)s then item_key end) as returned_msku_count,
                    count(distinct case when {active_condition} and stage = '观察期' then item_key end) as observe_msku_count,
                    count(distinct case when {active_condition} and stage = '观察期' and return_days between 1 and 3 then item_key end) as observe_d1_3_msku_count,
                    count(distinct case when {active_condition} and stage = '观察期' and return_days between 4 and 7 then item_key end) as observe_d4_7_msku_count,
                    count(distinct case when {active_condition} and stage = '观察期' and coalesce(post_7d_sales_qty, 0) > 0 then item_key end) as observe_ordered_msku_count,
                    count(distinct case when {active_condition} and stage = '观察期' and coalesce(post_7d_sales_qty, 0) = 0 then item_key end) as observe_not_ordered_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' then item_key end) as operating_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and return_days between 8 and 14 then item_key end) as operating_d8_14_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and return_days between 15 and 21 then item_key end) as operating_d15_21_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and sales_recovery_rate >= 0.7 then item_key end) as operating_success_recovery_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and sales_recovery_rate is not null and sales_recovery_rate < 0.5 then item_key end) as operating_low_recovery_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and sales_recovery_rate >= 0.5 and sales_recovery_rate < 0.7 then item_key end) as operating_recovery_insufficient_msku_count,
                    count(distinct case when {active_condition} and stage = '运营干预期' and sales_recovery_rate is null then item_key end) as operating_data_insufficient_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s then item_key end) as exited_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and exit_reason = '达标退出' then item_key end) as success_exit_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and exit_reason = '未达标退出' then item_key end) as failed_exit_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate >= 0.5 and sales_recovery_rate < 0.7 then item_key end) as recovery_insufficient_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and coalesce(post_recovery_sales_qty, 0) = 0 then item_key end) as no_recovery_21d_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate > 0 and sales_recovery_rate < 0.3 then item_key end) as low_recovery_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate >= 0.3 and sales_recovery_rate < 0.5 then item_key end) as weak_recovery_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and pre_stockout_sales_role in ('明星产品', '潜力产品') and sales_recovery_rate < 0.5 then item_key end) as high_value_failed_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and sales_recovery_rate is null then item_key end) as data_insufficient_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and exit_reason = '待人工判断' then item_key end) as manual_judgment_msku_count,
                    count(distinct case when exit_date is not null and exit_date <= %(end_date)s and exit_reason = '二次断货' then item_key end) as secondary_stockout_msku_count,
                    count(distinct case when {active_condition} and stage = '超期未处理' then item_key end) as overdue_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5 then item_key end) as current_severe_low_recovery_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate >= 0.5 and cumulative_avg_recovery_rate < 0.7 then item_key end) as recovery_improving_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null then item_key end) as followup_active_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and stable_recovery_start_date is not null then item_key end) as started_stable_recovery_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and current_stable_recovery_flag = 1 then item_key end) as current_stable_recovery_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and recovery_fallback_flag = 1 then item_key end) as recovery_fallback_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is not null and exit_date <= %(end_date)s and recovery_followup_status = '21天后恢复达标' then item_key end) as late_standard_exit_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is null then item_key end) as followup_data_insufficient_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and coalesce(post_cumulative_sales_qty, 0) = 0 then item_key end) as followup_no_sales_since_return_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5 and coalesce(post_cumulative_sales_qty, 0) = 0 then item_key end) as severe_no_sales_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate > 0 and cumulative_avg_recovery_rate < 0.1 then item_key end) as severe_rate_0_10_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate >= 0.1 and cumulative_avg_recovery_rate < 0.3 then item_key end) as severe_rate_10_30_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate >= 0.3 and cumulative_avg_recovery_rate < 0.5 then item_key end) as severe_rate_30_50_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5 and coalesce(post_cumulative_sales_qty, 0) > 0 and coalesce(recovery_fallback_flag, 0) = 0 and coalesce(current_stable_recovery_flag, 0) = 0 then item_key end) as severe_never_stable_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5 and coalesce(post_cumulative_sales_qty, 0) > 0 and recovery_fallback_flag = 1 then item_key end) as severe_recovery_fallback_msku_count,
                    count(distinct case when recovery_followup_flag = 1 and exit_date is null and cumulative_avg_recovery_rate is not null and cumulative_avg_recovery_rate < 0.5 and coalesce(post_cumulative_sales_qty, 0) > 0 and coalesce(recovery_fallback_flag, 0) = 0 and current_stable_recovery_flag = 1 then item_key end) as severe_current_stable_msku_count,
                    count(distinct case when coalesce(current_fba_sellable, 0) > 0 and coalesce(current_fba_sellable, 0) <= 5 and coalesce(current_fba_inbound, 0) > 0 then item_key end) as receiving_msku_count,
                    count(distinct case when coalesce(current_fba_sellable, 0) = 0 and coalesce(current_fba_inbound, 0) > 0 then item_key end) as not_arrived_msku_count,
                    avg(case when sales_recovery_rate is not null then sales_recovery_rate end) as avg_sales_recovery_rate
                from (
                    select latest_rows.*
                    from (
                        select
                            e.*,
                            row_number() over (
                                partition by e.item_key
                                order by e.return_start_date desc, e.return_round desc
                            ) as latest_rank
                        from dashboard_return_goods_events e
                        where {filters}
                    ) latest_rows
                    inner join dashboard_return_goods_stockout_pool p
                            on p.snapshot_date = latest_rows.snapshot_date
                           and p.item_key = latest_rows.item_key
                    where latest_rows.latest_rank = 1
                ) latest_events
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return self._serialize_overview_summary(row)

    def _stockout_pool_where(
        self,
        snapshot_date: date,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["snapshot_date = %(snapshot_date)s", "seller_sku_adj not like %(excluded_msku_pattern)s"]
        params: dict[str, Any] = {"snapshot_date": snapshot_date, "excluded_msku_pattern": "amzn.gr.%"}
        if country_category and country_category != "all":
            clauses.append("country_category = %(country_category)s")
            params["country_category"] = country_category
        if seller_name_new and seller_name_new != "all":
            clauses.append("seller_name_new = %(seller_name_new)s")
            params["seller_name_new"] = seller_name_new
        if keyword:
            clauses.append("(seller_sku_adj like %(keyword)s or coalesce(local_sku, '') like %(keyword)s)")
            params["keyword"] = f"%{keyword.strip()}%"
        return " and ".join(clauses), params

    def _stockout_msku_count(
        self,
        conn,
        snapshot_date: date,
        country_category: str = "all",
        seller_name_new: str = "all",
        keyword: str = "",
    ) -> int:
        filters, params = self._stockout_pool_where(snapshot_date, country_category, seller_name_new, keyword)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as stockout_msku_count
                from dashboard_return_goods_stockout_pool
                where {filters}
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return int(row.get("stockout_msku_count") or 0)

    def _serialize_summary(self, row: dict[str, Any]) -> dict[str, int]:
        new_count = int(row.get("new_count") or 0)
        exit_count = int(row.get("exit_count") or 0)
        return {
            "total_return_msku_count": int(row.get("total_return_msku_count") or 0),
            "total_return_event_count": int(row.get("total_return_event_count") or 0),
            "current_pool_count": int(row.get("current_pool_count") or 0),
            "current_pool_msku_count": int(row.get("current_pool_msku_count") or 0),
            "receiving_count": int(row.get("receiving_count") or 0),
            "not_arrived_count": int(row.get("not_arrived_count") or 0),
            "new_count": new_count,
            "exit_count": exit_count,
            "net_count": new_count - exit_count,
            "success_exit_count": int(row.get("success_exit_count") or 0),
            "failed_exit_count": int(row.get("failed_exit_count") or 0),
            "manual_judgment_count": int(row.get("manual_judgment_count") or 0),
            "overdue_count": int(row.get("overdue_count") or 0),
            "today_observe_to_operating_count": int(row.get("today_observe_to_operating_count") or 0),
            "secondary_stockout_count": int(row.get("secondary_stockout_count") or 0),
            "avg_sales_recovery_rate": number_value(row.get("avg_sales_recovery_rate")),
            "avg_sales_recovery_rate_text": self._rate_text(row.get("avg_sales_recovery_rate")),
        }

    def _serialize_overview_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "stockout_msku_count": int(row.get("stockout_msku_count") or 0),
            "returned_msku_count": int(row.get("returned_msku_count") or 0),
            "observe_msku_count": int(row.get("observe_msku_count") or 0),
            "observe_d1_3_msku_count": int(row.get("observe_d1_3_msku_count") or 0),
            "observe_d4_7_msku_count": int(row.get("observe_d4_7_msku_count") or 0),
            "observe_ordered_msku_count": int(row.get("observe_ordered_msku_count") or 0),
            "observe_not_ordered_msku_count": int(row.get("observe_not_ordered_msku_count") or 0),
            "operating_msku_count": int(row.get("operating_msku_count") or 0),
            "operating_d8_14_msku_count": int(row.get("operating_d8_14_msku_count") or 0),
            "operating_d15_21_msku_count": int(row.get("operating_d15_21_msku_count") or 0),
            "operating_success_recovery_msku_count": int(row.get("operating_success_recovery_msku_count") or 0),
            "operating_low_recovery_msku_count": int(row.get("operating_low_recovery_msku_count") or 0),
            "operating_recovery_insufficient_msku_count": int(row.get("operating_recovery_insufficient_msku_count") or 0),
            "operating_data_insufficient_msku_count": int(row.get("operating_data_insufficient_msku_count") or 0),
            "exited_msku_count": int(row.get("exited_msku_count") or 0),
            "success_exit_msku_count": int(row.get("success_exit_msku_count") or 0),
            "failed_exit_msku_count": int(row.get("failed_exit_msku_count") or 0),
            "recovery_insufficient_msku_count": int(row.get("recovery_insufficient_msku_count") or 0),
            "no_recovery_21d_msku_count": int(row.get("no_recovery_21d_msku_count") or 0),
            "low_recovery_msku_count": int(row.get("low_recovery_msku_count") or 0),
            "weak_recovery_msku_count": int(row.get("weak_recovery_msku_count") or 0),
            "high_value_failed_msku_count": int(row.get("high_value_failed_msku_count") or 0),
            "data_insufficient_msku_count": int(row.get("data_insufficient_msku_count") or 0),
            "manual_judgment_msku_count": int(row.get("manual_judgment_msku_count") or 0),
            "secondary_stockout_msku_count": int(row.get("secondary_stockout_msku_count") or 0),
            "overdue_msku_count": int(row.get("overdue_msku_count") or 0),
            "current_severe_low_recovery_msku_count": int(row.get("current_severe_low_recovery_msku_count") or 0),
            "recovery_improving_msku_count": int(row.get("recovery_improving_msku_count") or 0),
            "followup_active_msku_count": int(row.get("followup_active_msku_count") or 0),
            "started_stable_recovery_msku_count": int(row.get("started_stable_recovery_msku_count") or 0),
            "current_stable_recovery_msku_count": int(row.get("current_stable_recovery_msku_count") or 0),
            "recovery_fallback_msku_count": int(row.get("recovery_fallback_msku_count") or 0),
            "late_standard_exit_msku_count": int(row.get("late_standard_exit_msku_count") or 0),
            "followup_data_insufficient_msku_count": int(row.get("followup_data_insufficient_msku_count") or 0),
            "followup_no_sales_since_return_msku_count": int(row.get("followup_no_sales_since_return_msku_count") or 0),
            "severe_no_sales_msku_count": int(row.get("severe_no_sales_msku_count") or 0),
            "severe_rate_0_10_msku_count": int(row.get("severe_rate_0_10_msku_count") or 0),
            "severe_rate_10_30_msku_count": int(row.get("severe_rate_10_30_msku_count") or 0),
            "severe_rate_30_50_msku_count": int(row.get("severe_rate_30_50_msku_count") or 0),
            "severe_never_stable_msku_count": int(row.get("severe_never_stable_msku_count") or 0),
            "severe_recovery_fallback_msku_count": int(row.get("severe_recovery_fallback_msku_count") or 0),
            "severe_current_stable_msku_count": int(row.get("severe_current_stable_msku_count") or 0),
            "receiving_msku_count": int(row.get("receiving_msku_count") or 0),
            "not_arrived_msku_count": int(row.get("not_arrived_msku_count") or 0),
            "avg_sales_recovery_rate": number_value(row.get("avg_sales_recovery_rate")),
            "avg_sales_recovery_rate_text": self._rate_text(row.get("avg_sales_recovery_rate")),
        }

    def _attach_period_comparison(self, summary: dict[str, Any], previous_summary: dict[str, Any]) -> None:
        for key in ("new_count", "exit_count", "net_count"):
            previous_key = f"previous_{key}"
            delta_key = f"{key}_delta"
            previous_value = int(previous_summary.get(key) or 0)
            summary[previous_key] = previous_value
            summary[delta_key] = int(summary.get(key) or 0) - previous_value

    def _stage_distribution(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select stage, count(*) as count
                from dashboard_return_goods_events
                where {filters}
                  and return_start_date <= %(end_date)s
                  and (exit_date is null or exit_date > %(end_date)s)
                group by stage
                order by field(stage, '观察期', '运营干预期', '持续干预期', '超期未处理', '已退出'), stage
                """,
                params,
            )
            rows = cursor.fetchall()
        return [{"stage": row["stage"], "count": int(row.get("count") or 0)} for row in rows]

    def _sales_role_distribution(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select sales_role, count(*) as count
                from (
                    select coalesce(pre_stockout_sales_role, '问题产品') as sales_role
                    from dashboard_return_goods_events
                    where {filters}
                ) role_rows
                group by sales_role
                order by field(sales_role, '问题产品', '瘦狗产品', '潜力产品', '明星产品')
                """,
                params,
            )
            rows = cursor.fetchall()
        total = sum(int(row.get("count") or 0) for row in rows)
        return [
            {
                "sales_role": row["sales_role"],
                "count": int(row.get("count") or 0),
                "ratio": (int(row.get("count") or 0) / total) if total else 0,
            }
            for row in rows
        ]

    def _workbench_rows(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select item_key, pre_stockout_sales_role, current_fba_sellable, current_fba_inbound,
                       return_start_date, exit_date, exit_reason, return_days, stage, sales_recovery_rate,
                       d21_recovery_rate, recovery_followup_flag, post_cumulative_sales_qty,
                       cumulative_avg_recovery_rate, recovery_followup_status, stable_recovery_start_date,
                       current_stable_recovery_flag, recovery_fallback_flag, days_to_standard,
                       pre_7d_sales_qty, observe_7d_sales_qty, post_7d_sales_qty,
                       pre_7d_sales_avg, observe_7d_sales_avg, post_7d_sales_avg, pre_7d_gross_margin_rate
                from dashboard_return_goods_events
                where {filters}
                  and {self._latest_event_filter()}
                """,
                params,
            )
            return cursor.fetchall()

    def _stage_business_compare(self, rows: list[dict[str, Any]], end_date: date) -> list[dict[str, Any]]:
        stages = [("observe", "观察期", "overview_observe"), ("operating", "运营干预期", "overview_operating")]
        result = []
        for stage_key, stage, quick_filter in stages:
            stage_rows = [row for row in rows if self._is_active(row, end_date) and row.get("stage") == stage]
            baseline_key = "observe_7d_sales_qty" if stage == "运营干预期" else "pre_7d_sales_qty"
            baseline_label = "观察期7天销量" if stage == "运营干预期" else "断货前7天销量"
            baseline_sales = self._sum_numeric(stage_rows, baseline_key)
            current_sales = self._sum_numeric(stage_rows, "post_7d_sales_qty")
            recovery_rate = current_sales / baseline_sales if baseline_sales and current_sales is not None else None
            result.append(
                {
                    "stage": stage,
                    "stage_key": stage_key,
                    "quick_filter": quick_filter,
                    "count": len({row.get("item_key") for row in stage_rows if row.get("item_key")}),
                    "baseline_label": baseline_label,
                    "baseline_sales": baseline_sales,
                    "current_label": "返场后近7天销量",
                    "current_sales": current_sales,
                    "sales_delta": (current_sales - baseline_sales) if baseline_sales is not None and current_sales is not None else None,
                    "sales_recovery_rate": recovery_rate,
                }
            )
        return result

    def _sum_numeric(self, rows: list[dict[str, Any]], key: str) -> float:
        return sum(float(value) for row in rows if (value := number_value(row.get(key))) is not None)

    def _avg_numeric(self, rows: list[dict[str, Any]], key: str) -> float | None:
        values = [float(value) for row in rows if (value := number_value(row.get(key))) is not None]
        return sum(values) / len(values) if values else None

    def _status_matrix(self, rows: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
        total = sum(
            1
            for row in rows
            if any(self._matrix_status_matches(row, status_key, start_date, end_date) for status_key, _ in STATUS_COLUMNS)
        )
        cells = []
        for role_key, role_label in SALES_ROLES:
            for status_key, status_label in STATUS_COLUMNS:
                count = sum(
                    1
                    for row in rows
                    if (row.get("pre_stockout_sales_role") or "问题产品") == role_label
                    and self._matrix_status_matches(row, status_key, start_date, end_date)
                )
                cells.append(
                    {
                        "role_key": role_key,
                        "role": role_label,
                        "status_key": status_key,
                        "status": status_label,
                        "count": count,
                        "ratio": count / total if total else 0,
                        "quick_filter": f"matrix_{role_key}_{status_key}",
                        "priority": role_key in {"star", "potential"} and status_key in {"not_arrived", "operating", "followup_severe"},
                    }
                )
        return {
            "roles": [{"key": key, "label": label} for key, label in SALES_ROLES],
            "statuses": [{"key": key, "label": label} for key, label in STATUS_COLUMNS],
            "cells": cells,
            "total": total,
        }

    def _priority_queue(self, rows: list[dict[str, Any]], start_date: date, end_date: date) -> list[dict[str, Any]]:
        valuable_roles = {"明星产品", "潜力产品"}
        items = [
            (
                "截至目前严重恢复不足",
                "累计平均恢复率 < 50%，优先复盘动作和补量",
                "overview_current_severe_low_recovery",
                lambda row: self._status_matches(row, "followup_severe", start_date, end_date),
            ),
            (
                "恢复提升中",
                "累计平均恢复率已到 50%-70%，继续跟踪至达标",
                "overview_recovery_improving",
                lambda row: self._status_matches(row, "followup_improving", start_date, end_date),
            ),
            (
                "恢复后回落",
                "曾连续 3 天稳定恢复，但最近 3 天未保持",
                "overview_recovery_fallback",
                lambda row: bool(row.get("recovery_followup_flag"))
                and self._is_active(row, end_date)
                and bool(row.get("recovery_fallback_flag")),
            ),
            (
                "高价值持续低恢复",
                "明星/潜力产品，累计平均恢复率仍低于 50%",
                "overview_high_value_failed",
                lambda row: (row.get("pre_stockout_sales_role") or "") in valuable_roles
                and self._status_matches(row, "followup_severe", start_date, end_date),
            ),
        ]
        return [
            {"title": title, "hint": hint, "quick_filter": quick_filter, "count": sum(1 for row in rows if matcher(row))}
            for title, hint, quick_filter, matcher in items
        ]

    def _status_matches(self, row: dict[str, Any], status_key: str, start_date: date, end_date: date) -> bool:
        sellable = number_value(row.get("current_fba_sellable")) or 0
        inbound = number_value(row.get("current_fba_inbound")) or 0
        if status_key == "not_arrived":
            return sellable == 0 and inbound > 0
        if status_key == "receiving":
            return 0 < sellable <= 5 and inbound > 0
        if status_key == "observe":
            return self._is_active(row, end_date) and row.get("stage") == "观察期"
        if status_key == "operating":
            return self._is_active(row, end_date) and row.get("stage") == "运营干预期"
        if status_key == "manual":
            exit_date = row.get("exit_date")
            return row.get("exit_reason") == "待人工判断" and exit_date is not None and start_date <= exit_date <= end_date
        if status_key == "recovery_insufficient":
            exit_date = row.get("exit_date")
            rate = number_value(row.get("sales_recovery_rate"))
            return exit_date is not None and exit_date <= end_date and rate is not None and 0.5 <= rate < 0.7
        if status_key == "over21_low_recovery":
            exit_date = row.get("exit_date")
            rate = number_value(row.get("sales_recovery_rate"))
            return exit_date is not None and exit_date <= end_date and rate is not None and rate < 0.5
        if status_key == "followup_improving":
            rate = number_value(row.get("cumulative_avg_recovery_rate"))
            return bool(row.get("recovery_followup_flag")) and self._is_active(row, end_date) and rate is not None and 0.5 <= rate < 0.7
        if status_key == "followup_severe":
            rate = number_value(row.get("cumulative_avg_recovery_rate"))
            return bool(row.get("recovery_followup_flag")) and self._is_active(row, end_date) and rate is not None and rate < 0.5
        if status_key == "followup_stable":
            return bool(row.get("recovery_followup_flag")) and self._is_active(row, end_date) and bool(row.get("current_stable_recovery_flag"))
        if status_key == "followup_data_insufficient":
            return bool(row.get("recovery_followup_flag")) and self._is_active(row, end_date) and row.get("cumulative_avg_recovery_rate") is None
        return False

    def _matrix_status_matches(self, row: dict[str, Any], status_key: str, start_date: date, end_date: date) -> bool:
        ordered_statuses = ("followup_severe", "followup_improving", "followup_data_insufficient", "operating", "observe", "not_arrived")
        for candidate in ordered_statuses:
            if self._status_matches(row, candidate, start_date, end_date):
                return candidate == status_key
        return False

    def _is_active(self, row: dict[str, Any], end_date: date) -> bool:
        return row.get("return_start_date") <= end_date and (row.get("exit_date") is None or row.get("exit_date") > end_date)

    def _warnings(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select warning_type, count(*) as count
                from dashboard_return_goods_events
                where {filters}
                  and warning_type is not null and warning_type <> ''
                group by warning_type
                order by field(warning_type, '二次断货', '严重超期', '干预期严重低恢复', '干预期未恢复'), warning_type
                """,
                params,
            )
            rows = cursor.fetchall()
        return [{"warning_type": row["warning_type"], "count": int(row.get("count") or 0)} for row in rows]

    def _total(self, conn, filters: str, params: dict[str, Any]) -> int:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from dashboard_return_goods_events
                where {filters}
                  and {self._latest_event_filter()}
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return int(row.get("total") or 0)

    def _latest_event_filter(self) -> str:
        return """
            return_event_id in (
                select return_event_id
                from (
                    select
                        return_event_id,
                        row_number() over (
                            partition by item_key
                            order by return_start_date desc, return_round desc
                        ) as latest_rank
                    from dashboard_return_goods_events
                    where snapshot_date = %(snapshot_date)s
                      and return_start_date <= %(end_date)s
                ) latest_events
                where latest_rank = 1
            )
        """

    def _items(self, conn, filters: str, params: dict[str, Any], page: int, page_size: int) -> list[dict[str, Any]]:
        params = dict(params)
        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    return_event_id, item_key, seller_name_new, country_category, seller_sku_adj, local_sku,
                    return_round, stockout_date, return_start_date,
                    datediff(return_start_date, stockout_date) as stockout_days,
                    exit_date, exit_reason,
                    return_days, stage, pre_7d_sales_avg, pre_7d_gross_margin_rate, pre_stockout_sales_role,
                    post_7d_sales_avg, recovery_window_days, pre_recovery_sales_qty, post_recovery_sales_qty, sales_recovery_rate,
                    pre_21d_sales_qty, post_first_21d_sales_qty, d21_recovery_rate,
                    recovery_followup_flag, post_cumulative_sales_qty, cumulative_avg_recovery_rate,
                    recovery_followup_status, stable_recovery_start_date, current_stable_recovery_flag,
                    recovery_fallback_flag, days_to_standard,
                    current_fba_sellable, current_fba_inbound, warning_type
                from dashboard_return_goods_events
                where {filters}
                  and {self._latest_event_filter()}
                order by
                    case when return_start_date <= %(end_date)s and (exit_date is null or exit_date > %(end_date)s) then 0 else 1 end,
                    case warning_type
                        when '二次断货' then 1
                        when '严重超期' then 2
                        when '干预期严重低恢复' then 3
                        when '干预期未恢复' then 4
                        else 9
                    end,
                    return_start_date desc,
                    seller_name_new,
                    seller_sku_adj
                limit %(limit)s offset %(offset)s
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._serialize_item(row) for row in rows]

    def _stage_events(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    return_event_id, item_key, seller_name_new, country_category, seller_sku_adj, local_sku,
                    return_round, stockout_date, return_start_date,
                    datediff(return_start_date, stockout_date) as stockout_days,
                    exit_date, exit_reason, return_days, stage,
                    pre_stockout_sales_role, current_fba_sellable, current_fba_inbound,
                    recovery_window_days, pre_recovery_sales_qty, post_recovery_sales_qty, sales_recovery_rate, warning_type
                    , pre_21d_sales_qty, post_first_21d_sales_qty, d21_recovery_rate
                    , recovery_followup_flag, post_cumulative_sales_qty, cumulative_avg_recovery_rate
                    , recovery_followup_status, stable_recovery_start_date, current_stable_recovery_flag
                    , recovery_fallback_flag, days_to_standard
                from dashboard_return_goods_events
                where {filters}
                order by return_start_date desc, seller_name_new, seller_sku_adj
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._serialize_item(row) for row in rows]

    def _stage_daily_groups(
        self,
        events: list[dict[str, Any]],
        daily_by_event: dict[str, list[dict[str, Any]]],
        stage_key: str,
    ) -> list[dict[str, Any]]:
        specs = [("观察段", 1, 7, "观察Day")]
        if stage_key == "operating":
            specs.append(("干预段", 8, 21, "干预Day"))
        groups = []
        for title, start_day, end_day, day_label in specs:
            rows = [
                self._stage_daily_row(events, daily_by_event, return_day, start_day, day_label)
                for return_day in range(start_day, end_day + 1)
            ]
            groups.append({"title": title, "rows": rows})
        return groups

    def _stage_daily_summary_groups(self, conn, snapshot_date: date, stage_key: str) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    segment_key, segment_name, stage_day, return_day,
                    observable_msku, ordered_msku, cumulative_ordered_msku,
                    sales_qty, cumulative_sales_qty, fba_sellable, not_ordered_msku
                from dashboard_return_goods_stage_daily_summary
                where snapshot_date = %(snapshot_date)s
                  and stage_key = %(stage_key)s
                order by return_day
                """,
                {"snapshot_date": snapshot_date, "stage_key": stage_key},
            )
            rows = cursor.fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row["segment_key"]
            group = grouped.setdefault(key, {"title": row["segment_name"], "rows": []})
            group["rows"].append(self._serialize_stage_summary_row(row))
        return self._pad_stage_summary_groups(grouped, stage_key)

    def _pad_stage_summary_groups(self, grouped: dict[str, dict[str, Any]], stage_key: str) -> list[dict[str, Any]]:
        specs = [("observe", "观察段", 1, 7, "观察Day")]
        if stage_key == "operating":
            specs.append(("operating", "干预段", 8, 21, "干预Day"))
        groups = []
        for key, title, start_day, end_day, label in specs:
            existing = {int(row.get("return_day") or 0): row for row in grouped.get(key, {}).get("rows", [])}
            rows = [
                existing.get(return_day) or self._empty_stage_summary_row(return_day, start_day, label)
                for return_day in range(start_day, end_day + 1)
            ]
            groups.append({"title": grouped.get(key, {}).get("title") or title, "rows": rows})
        return groups

    def _empty_stage_summary_row(self, return_day: int, phase_start_day: int, day_label: str) -> dict[str, Any]:
        stage_day = return_day - phase_start_day + 1
        return {
            "stage_day": stage_day,
            "stage_day_label": f"{day_label}{stage_day}",
            "return_day": return_day,
            "return_day_label": f"D{return_day}",
            "observable_msku": 0,
            "ordered_msku": 0,
            "cumulative_ordered_msku": 0,
            "sales_qty": 0,
            "cumulative_sales_qty": 0,
            "fba_sellable": 0,
            "not_ordered_msku": 0,
        }

    def _stage_daily_summary_event_count(self, conn, snapshot_date: date, stage_key: str) -> int:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select coalesce(sum(observable_msku), 0) as event_count
                from dashboard_return_goods_stage_daily_summary
                where snapshot_date = %(snapshot_date)s
                  and stage_key = %(stage_key)s
                """,
                {"snapshot_date": snapshot_date, "stage_key": stage_key},
            )
            row = cursor.fetchone() or {}
        return int(row.get("event_count") or 0)

    def _serialize_stage_summary_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "stage_day": int(row.get("stage_day") or 0),
            "stage_day_label": ("干预Day" if int(row.get("return_day") or 0) > 7 else "观察Day") + str(int(row.get("stage_day") or 0)),
            "return_day": int(row.get("return_day") or 0),
            "return_day_label": "D" + str(int(row.get("return_day") or 0)),
            "observable_msku": int(row.get("observable_msku") or 0),
            "ordered_msku": int(row.get("ordered_msku") or 0),
            "cumulative_ordered_msku": int(row.get("cumulative_ordered_msku") or 0),
            "sales_qty": number_value(row.get("sales_qty")) or 0,
            "cumulative_sales_qty": number_value(row.get("cumulative_sales_qty")) or 0,
            "fba_sellable": number_value(row.get("fba_sellable")) or 0,
            "not_ordered_msku": int(row.get("not_ordered_msku") or 0),
        }

    def _stage_daily_row(
        self,
        events: list[dict[str, Any]],
        daily_by_event: dict[str, list[dict[str, Any]]],
        return_day: int,
        phase_start_day: int,
        day_label: str,
    ) -> dict[str, Any]:
        observable = ordered_today = cumulative_ordered = 0
        sales_today = cumulative_sales = fba_sellable = 0.0
        for event in events:
            daily_rows = daily_by_event.get(event.get("return_event_id") or "", [])
            by_day = self._daily_rows_by_return_day(event, daily_rows)
            if int(event.get("return_days") or 0) == return_day:
                observable += 1
                today = by_day.get(return_day, {})
                today_sales = float(number_value(today.get("sales_qty")) or 0)
                sales_today += today_sales
                fba_sellable += float(number_value(today.get("fba_sellable")) or 0)
                if today_sales > 0:
                    ordered_today += 1
            event_cumulative_sales = sum(
                float(number_value((by_day.get(day) or {}).get("sales_qty")) or 0)
                for day in range(phase_start_day, return_day + 1)
            )
            cumulative_sales += event_cumulative_sales
            if event_cumulative_sales > 0:
                cumulative_ordered += 1
        return {
            "stage_day": return_day - phase_start_day + 1,
            "stage_day_label": f"{day_label}{return_day - phase_start_day + 1}",
            "return_day": return_day,
            "return_day_label": f"D{return_day}",
            "observable_msku": observable,
            "ordered_msku": ordered_today,
            "cumulative_ordered_msku": cumulative_ordered,
            "sales_qty": sales_today,
            "cumulative_sales_qty": cumulative_sales,
            "fba_sellable": fba_sellable,
            "not_ordered_msku": max(len(events) - cumulative_ordered, 0),
        }

    def _daily_rows_by_return_day(self, event: dict[str, Any], daily_rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        start_day = parse_day(event.get("return_start_date"))
        if start_day is None:
            return {}
        result = {}
        for row in daily_rows:
            row_day = parse_day(row.get("dt_date"))
            if row_day is None:
                continue
            return_day = (row_day - start_day).days + 1
            if 1 <= return_day <= 21:
                result[return_day] = row
        return result

    def _event_detail(self, conn, snapshot_date: date, return_event_id: str) -> dict[str, Any] | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    return_event_id, item_key, seller_name_new, country_category, seller_sku_adj, local_sku,
                    return_round, stockout_date, return_start_date,
                    datediff(return_start_date, stockout_date) as stockout_days,
                    exit_date, exit_reason, return_days, stage,
                    pre_7d_sales_avg, post_7d_sales_avg, recovery_window_days, pre_recovery_sales_qty, post_recovery_sales_qty, sales_recovery_rate,
                    pre_21d_sales_qty, post_first_21d_sales_qty, d21_recovery_rate,
                    recovery_followup_flag, post_cumulative_sales_qty, cumulative_avg_recovery_rate,
                    recovery_followup_status, stable_recovery_start_date, current_stable_recovery_flag,
                    recovery_fallback_flag, days_to_standard,
                    current_fba_sellable, current_fba_inbound, warning_type,
                    pre_stockout_sales_role
                from dashboard_return_goods_events
                where snapshot_date = %(snapshot_date)s
                  and return_event_id = %(return_event_id)s
                limit 1
                """,
                {"snapshot_date": snapshot_date, "return_event_id": return_event_id},
            )
            row = cursor.fetchone()
        return self._serialize_item(row) if row else None

    def _daily_detail(self, conn, event: dict[str, Any], snapshot_date: date) -> list[dict[str, Any]]:
        stockout_day = parse_day(event.get("stockout_date"))
        if stockout_day is None:
            return []
        exit_day = parse_day(event.get("exit_date"))
        source_end_date = min(snapshot_date, exit_day) if exit_day else snapshot_date
        params = {
            "source_start_date": stockout_day - timedelta(days=21),
            "source_end_date": source_end_date,
            "seller_name_new": event.get("seller_name_new"),
            "country_category": event.get("country_category"),
            "seller_sku_adj": event.get("seller_sku_adj"),
        }
        with conn.cursor() as cursor:
            cursor.execute(
                """
                with product_daily as (
                    select
                        dt_date,
                        sum(coalesce(sales_qty, 0)) as sales_qty,
                        sum(coalesce(sales_amount, 0)) as sales_amount,
                        sum(coalesce(order_gross_profit, 0)) as order_gross_profit,
                        max(coalesce(afn_fulfillable_quantity, 0)) as fba_sellable
                    from dashboard_product_performance_daily
                    where dt_date between %(source_start_date)s and %(source_end_date)s
                      and seller_name_new = %(seller_name_new)s
                      and country_category = %(country_category)s
                      and seller_sku_adj = %(seller_sku_adj)s
                    group by dt_date
                )
                select
                    p.dt_date,
                    p.sales_qty,
                    p.sales_amount,
                    p.order_gross_profit,
                    p.fba_sellable,
                    coalesce(i.stock_up_num, 0) as fba_inbound
                from product_daily p
                left join dashboard_inventory_daily_snapshot i
                       on i.snapshot_date = p.dt_date
                      and i.seller_name_new = %(seller_name_new)s
                      and i.country_category = %(country_category)s
                      and i.seller_sku_adj = %(seller_sku_adj)s
                order by p.dt_date
                """,
                params,
            )
            rows = cursor.fetchall()
        serialized = [self._serialize_daily_detail(row, event) for row in rows]
        self._attach_followup_trend(serialized, event)
        return serialized

    def _empty_listing_preview(self) -> dict[str, Any]:
        return {
            "period_days": None,
            "period_start": None,
            "period_end": None,
            "country_count": 0,
            "price_risk_country_count": 0,
            "top_countries": [],
            "ad_spend": 0,
            "ad_sales": 0,
            "acos": None,
            "acos_text": "-",
            "tacos": None,
            "tacos_text": "-",
        }

    def _empty_country_metrics(self, snapshot_date: date | None, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_date": format_day(snapshot_date),
            "period_days": event.get("recovery_window_days") or min(event.get("return_days") or 1, 21),
            "period_start": None,
            "period_end": None,
            "parent": {
                "site": event.get("country_category"),
                "store": event.get("seller_name_new"),
                "msku": event.get("seller_sku_adj"),
            },
            "summary": {
                "country_count": 0,
                "price_risk_country_count": 0,
                "sales_qty": 0,
                "sales_amount": 0,
                "order_gross_profit": 0,
                "order_gross_margin": 0,
                "ad_spend": 0,
                "ad_sales": 0,
                "acos": None,
                "acos_text": "-",
                "tacos": None,
                "tacos_text": "-",
            },
            "items": [],
        }

    def _listing_key(self, row: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (row.get("country_category"), row.get("seller_name_new"), row.get("seller_sku_adj"))

    def _event_key(self, row: dict[str, Any]) -> Any:
        return row.get("return_event_id")

    def _latest_listing_snapshot(self, conn, snapshot_date: date) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select max(snapshot_date) as snapshot_date
                from dashboard_replenishment_country_metrics
                where snapshot_date <= %(snapshot_date)s
                  and period_days = 30
                """,
                {"snapshot_date": snapshot_date},
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _latest_price_snapshot(self, conn, snapshot_date: date) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select max(snapshot_date) as snapshot_date
                from dashboard_limit_price_daily_snapshot
                where snapshot_date <= %(snapshot_date)s
                """,
                {"snapshot_date": snapshot_date},
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _latest_listing_price_snapshot(self, conn, snapshot_date: date) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select max(snapshot_date) as snapshot_date
                from dashboard_listing_price_daily_snapshot
                where snapshot_date <= %(snapshot_date)s
                """,
                {"snapshot_date": snapshot_date},
            )
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _listing_rows_for_keys(
        self,
        conn,
        snapshot_date: date,
        keys: list[tuple[Any, Any, Any]],
    ) -> list[dict[str, Any]]:
        unique_keys = [key for index, key in enumerate(keys) if key and key not in keys[:index]]
        if not unique_keys:
            return []
        metrics_snapshot = self._latest_listing_snapshot(conn, snapshot_date)
        price_snapshot = self._latest_price_snapshot(conn, snapshot_date)
        listing_price_snapshot = self._latest_listing_price_snapshot(conn, snapshot_date)
        params: dict[str, Any] = {
            "metrics_snapshot": metrics_snapshot,
            "price_snapshot": price_snapshot,
            "listing_price_snapshot": listing_price_snapshot,
        }
        predicates = []
        valid_keys = []
        for index, (country_category, seller_name_new, seller_sku_adj) in enumerate(unique_keys):
            if not country_category or not seller_name_new or not seller_sku_adj:
                continue
            valid_keys.append((country_category, seller_name_new, seller_sku_adj))
            params[f"country_category_{index}"] = country_category
            params[f"seller_name_new_{index}"] = seller_name_new
            params[f"seller_sku_adj_{index}"] = seller_sku_adj
            predicates.append(
                "("
                f"m.country_category = %(country_category_{index})s "
                f"and m.seller_name_new = %(seller_name_new_{index})s "
                f"and m.seller_sku_adj = %(seller_sku_adj_{index})s"
                ")"
            )
        if not predicates:
            return []
        rows: list[dict[str, Any]] = []
        with conn.cursor() as cursor:
            if metrics_snapshot is not None:
                cursor.execute(
                    f"""
                    select
                        m.period_start,
                        m.period_end,
                        m.country_category,
                        m.country,
                        m.seller_name_new,
                        m.seller_sku_adj,
                        m.local_sku_list,
                        coalesce(nullif(m.listing_price, 0), lp.price) as listing_price,
                        coalesce(p.currency, lp.org_currency_icon) as currency,
                        p.margin_price_35,
                        p.margin_price_30,
                        p.margin_price_25,
                        p.margin_price_20,
                        p.margin_price_15,
                        p.margin_price_10,
                        p.margin_price_5,
                        p.margin_price_0,
                        m.sales_qty,
                        m.natural_daily_sales,
                        m.salable_days,
                        m.salable_daily_sales,
                        m.sales_amount,
                        m.order_gross_profit,
                        m.order_gross_margin,
                        m.avg_ranking,
                        m.best_ranking,
                        m.worst_ranking,
                        m.sessions_total,
                        m.conversion_rate,
                        m.ad_spend,
                        m.ad_orders,
                        m.ad_sales,
                        m.ad_clicks,
                        m.ad_impressions,
                        m.acos,
                        m.ctr
                    from dashboard_replenishment_country_metrics m
                    left join (
                        select
                            country_category,
                            country,
                            seller_name_new,
                            seller_sku,
                            max(currency) as currency,
                            max(margin_price_35) as margin_price_35,
                            max(margin_price_30) as margin_price_30,
                            max(margin_price_25) as margin_price_25,
                            max(margin_price_20) as margin_price_20,
                            max(margin_price_15) as margin_price_15,
                            max(margin_price_10) as margin_price_10,
                            max(margin_price_5) as margin_price_5,
                            max(margin_price_0) as margin_price_0
                        from dashboard_limit_price_daily_snapshot
                        where snapshot_date = %(price_snapshot)s
                        group by country_category, country, seller_name_new, seller_sku
                    ) p
                      on p.country_category = m.country_category
                     and p.country = m.country
                     and p.seller_name_new = m.seller_name_new
                     and p.seller_sku = m.seller_sku_adj
                    left join (
                        select
                            country_category,
                            country,
                            seller_name_new,
                            seller_sku,
                            max(price) as price,
                            max(org_currency_icon) as org_currency_icon
                        from dashboard_listing_price_daily_snapshot
                        where snapshot_date = %(listing_price_snapshot)s
                        group by country_category, country, seller_name_new, seller_sku
                    ) lp
                      on lp.country_category = m.country_category
                     and lp.country = m.country
                     and lp.seller_name_new = m.seller_name_new
                     and lp.seller_sku = m.seller_sku_adj
                    where m.snapshot_date = %(metrics_snapshot)s
                      and m.period_days = 30
                      and ({' or '.join(predicates)})
                    order by m.country_category, m.seller_name_new, m.seller_sku_adj, m.sales_qty desc, m.country
                    """,
                    params,
                )
                rows = list(cursor.fetchall())

            present_keys = {
                (row.get("country_category"), row.get("seller_name_new"), row.get("seller_sku_adj"))
                for row in rows
            }
            missing_keys = [key for key in valid_keys if key not in present_keys]
            if missing_keys and listing_price_snapshot is not None:
                fallback_params: dict[str, Any] = {
                    "price_snapshot": price_snapshot,
                    "listing_price_snapshot": listing_price_snapshot,
                }
                fallback_predicates = []
                for index, (country_category, seller_name_new, seller_sku_adj) in enumerate(missing_keys):
                    fallback_params[f"country_category_{index}"] = country_category
                    fallback_params[f"seller_name_new_{index}"] = seller_name_new
                    fallback_params[f"seller_sku_adj_{index}"] = seller_sku_adj
                    fallback_predicates.append(
                        "("
                        f"lp.country_category = %(country_category_{index})s "
                        f"and lp.seller_name_new = %(seller_name_new_{index})s "
                        f"and lp.seller_sku = %(seller_sku_adj_{index})s"
                        ")"
                    )
                cursor.execute(
                    f"""
                    select
                        null as period_start,
                        null as period_end,
                        lp.country_category,
                        lp.country,
                        lp.seller_name_new,
                        lp.seller_sku as seller_sku_adj,
                        null as local_sku_list,
                        lp.price as listing_price,
                        coalesce(p.currency, lp.org_currency_icon) as currency,
                        p.margin_price_35,
                        p.margin_price_30,
                        p.margin_price_25,
                        p.margin_price_20,
                        p.margin_price_15,
                        p.margin_price_10,
                        p.margin_price_5,
                        p.margin_price_0,
                        0 as sales_qty,
                        null as natural_daily_sales,
                        null as salable_days,
                        null as salable_daily_sales,
                        0 as sales_amount,
                        0 as order_gross_profit,
                        null as order_gross_margin,
                        null as avg_ranking,
                        null as best_ranking,
                        null as worst_ranking,
                        null as sessions_total,
                        null as conversion_rate,
                        0 as ad_spend,
                        0 as ad_orders,
                        0 as ad_sales,
                        0 as ad_clicks,
                        0 as ad_impressions,
                        null as acos,
                        null as ctr
                    from dashboard_listing_price_daily_snapshot lp
                    left join (
                        select
                            country_category,
                            country,
                            seller_name_new,
                            seller_sku,
                            max(currency) as currency,
                            max(margin_price_35) as margin_price_35,
                            max(margin_price_30) as margin_price_30,
                            max(margin_price_25) as margin_price_25,
                            max(margin_price_20) as margin_price_20,
                            max(margin_price_15) as margin_price_15,
                            max(margin_price_10) as margin_price_10,
                            max(margin_price_5) as margin_price_5,
                            max(margin_price_0) as margin_price_0
                        from dashboard_limit_price_daily_snapshot
                        where snapshot_date = %(price_snapshot)s
                        group by country_category, country, seller_name_new, seller_sku
                    ) p
                      on p.country_category = lp.country_category
                     and p.country = lp.country
                     and p.seller_name_new = lp.seller_name_new
                     and p.seller_sku = lp.seller_sku
                    where lp.snapshot_date = %(listing_price_snapshot)s
                      and ({' or '.join(fallback_predicates)})
                    order by lp.country_category, lp.seller_name_new, lp.seller_sku, lp.price desc, lp.country
                    """,
                    fallback_params,
                )
                rows.extend(cursor.fetchall())
        return rows

    def _listing_rows_for_events(
        self,
        conn,
        snapshot_date: date,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        valid_events = [
            event
            for event in events
            if event.get("return_event_id")
            and event.get("country_category")
            and event.get("seller_name_new")
            and event.get("seller_sku_adj")
        ]
        if not valid_events:
            return []
        price_snapshot = self._latest_price_snapshot(conn, snapshot_date)
        listing_price_snapshot = self._latest_listing_price_snapshot(conn, snapshot_date)
        params: dict[str, Any] = {
            "snapshot_date": snapshot_date,
            "price_snapshot": price_snapshot,
            "listing_price_snapshot": listing_price_snapshot,
        }
        event_predicates = []
        for index, event in enumerate(valid_events):
            params[f"return_event_id_{index}"] = event.get("return_event_id")
            event_predicates.append(f"c.return_event_id = %(return_event_id_{index})s")

        rows: list[dict[str, Any]] = []
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    c.snapshot_date,
                    c.return_event_id,
                    c.item_key,
                    c.country_category,
                    c.country,
                    c.seller_name_new,
                    c.seller_sku_adj,
                    c.local_sku_list,
                    c.metric_window_days,
                    c.pre_window_start,
                    c.pre_window_end,
                    c.post_window_start,
                    c.post_window_end,
                    coalesce(nullif(lp.price, 0), 0) as listing_price,
                    coalesce(p.currency, lp.org_currency_icon) as currency,
                    p.margin_price_35,
                    p.margin_price_30,
                    p.margin_price_25,
                    p.margin_price_20,
                    p.margin_price_15,
                    p.margin_price_10,
                    p.margin_price_5,
                    p.margin_price_0,
                    c.pre_sales_qty,
                    c.pre_sales_amount,
                    c.pre_order_gross_profit,
                    c.post_sales_qty,
                    c.post_sales_amount,
                    c.post_order_gross_profit,
                    c.post_order_gross_margin,
                    c.sales_recovery_rate,
                    c.sales_amount_recovery_rate,
                    c.sessions_total,
                    c.conversion_rate,
                    c.ad_spend,
                    c.ad_orders,
                    c.ad_sales,
                    c.ad_clicks,
                    c.ad_impressions,
                    c.acos,
                    c.ctr
                from dashboard_return_goods_country_metrics c
                left join (
                    select
                        country_category,
                        country,
                        seller_name_new,
                        seller_sku,
                        max(currency) as currency,
                        max(margin_price_35) as margin_price_35,
                        max(margin_price_30) as margin_price_30,
                        max(margin_price_25) as margin_price_25,
                        max(margin_price_20) as margin_price_20,
                        max(margin_price_15) as margin_price_15,
                        max(margin_price_10) as margin_price_10,
                        max(margin_price_5) as margin_price_5,
                        max(margin_price_0) as margin_price_0
                    from dashboard_limit_price_daily_snapshot
                    where snapshot_date = %(price_snapshot)s
                    group by country_category, country, seller_name_new, seller_sku
                ) p
                  on p.country_category = c.country_category
                 and p.country = c.country
                 and p.seller_name_new = c.seller_name_new
                 and p.seller_sku = c.seller_sku_adj
                left join (
                    select
                        country_category,
                        country,
                        seller_name_new,
                        seller_sku,
                        max(price) as price,
                        max(org_currency_icon) as org_currency_icon
                    from dashboard_listing_price_daily_snapshot
                    where snapshot_date = %(listing_price_snapshot)s
                    group by country_category, country, seller_name_new, seller_sku
                ) lp
                  on lp.country_category = c.country_category
                 and lp.country = c.country
                 and lp.seller_name_new = c.seller_name_new
                 and lp.seller_sku = c.seller_sku_adj
                where c.snapshot_date = %(snapshot_date)s
                  and ({' or '.join(event_predicates)})
                order by c.return_event_id, c.post_sales_qty desc, c.country
                """,
                params,
            )
            rows = list(cursor.fetchall())

            present_event_ids = {row.get("return_event_id") for row in rows}
            missing_events = [event for event in valid_events if event.get("return_event_id") not in present_event_ids]
            if missing_events and listing_price_snapshot is not None:
                fallback_params: dict[str, Any] = {
                    "price_snapshot": price_snapshot,
                    "listing_price_snapshot": listing_price_snapshot,
                }
                fallback_predicates = []
                event_lookup = {}
                for index, event in enumerate(missing_events):
                    event_lookup[(event.get("country_category"), event.get("seller_name_new"), event.get("seller_sku_adj"))] = event
                    fallback_params[f"country_category_{index}"] = event.get("country_category")
                    fallback_params[f"seller_name_new_{index}"] = event.get("seller_name_new")
                    fallback_params[f"seller_sku_adj_{index}"] = event.get("seller_sku_adj")
                    fallback_predicates.append(
                        "("
                        f"lp.country_category = %(country_category_{index})s "
                        f"and lp.seller_name_new = %(seller_name_new_{index})s "
                        f"and lp.seller_sku = %(seller_sku_adj_{index})s"
                        ")"
                    )
                cursor.execute(
                    f"""
                    select
                        lp.country_category,
                        lp.country,
                        lp.seller_name_new,
                        lp.seller_sku as seller_sku_adj,
                        lp.price as listing_price,
                        coalesce(p.currency, lp.org_currency_icon) as currency,
                        p.margin_price_35,
                        p.margin_price_30,
                        p.margin_price_25,
                        p.margin_price_20,
                        p.margin_price_15,
                        p.margin_price_10,
                        p.margin_price_5,
                        p.margin_price_0
                    from dashboard_listing_price_daily_snapshot lp
                    left join (
                        select
                            country_category,
                            country,
                            seller_name_new,
                            seller_sku,
                            max(currency) as currency,
                            max(margin_price_35) as margin_price_35,
                            max(margin_price_30) as margin_price_30,
                            max(margin_price_25) as margin_price_25,
                            max(margin_price_20) as margin_price_20,
                            max(margin_price_15) as margin_price_15,
                            max(margin_price_10) as margin_price_10,
                            max(margin_price_5) as margin_price_5,
                            max(margin_price_0) as margin_price_0
                        from dashboard_limit_price_daily_snapshot
                        where snapshot_date = %(price_snapshot)s
                        group by country_category, country, seller_name_new, seller_sku
                    ) p
                      on p.country_category = lp.country_category
                     and p.country = lp.country
                     and p.seller_name_new = lp.seller_name_new
                     and p.seller_sku = lp.seller_sku
                    where lp.snapshot_date = %(listing_price_snapshot)s
                      and ({' or '.join(fallback_predicates)})
                    order by lp.country_category, lp.seller_name_new, lp.seller_sku, lp.price desc, lp.country
                    """,
                    fallback_params,
                )
                for row in cursor.fetchall():
                    event = event_lookup.get((row.get("country_category"), row.get("seller_name_new"), row.get("seller_sku_adj")))
                    if not event:
                        continue
                    rows.append(
                        {
                            **row,
                            "snapshot_date": snapshot_date,
                            "return_event_id": event.get("return_event_id"),
                            "item_key": event.get("item_key"),
                            "local_sku_list": event.get("local_sku") or "",
                            "metric_window_days": event.get("recovery_window_days") or min(event.get("return_days") or 1, 21),
                            "pre_window_start": None,
                            "pre_window_end": None,
                            "post_window_start": event.get("return_start_date"),
                            "post_window_end": None,
                            "pre_sales_qty": 0,
                            "pre_sales_amount": 0,
                            "pre_order_gross_profit": 0,
                            "post_sales_qty": 0,
                            "post_sales_amount": 0,
                            "post_order_gross_profit": 0,
                            "post_order_gross_margin": None,
                            "sales_recovery_rate": None,
                            "sales_amount_recovery_rate": None,
                            "sessions_total": 0,
                            "conversion_rate": None,
                            "ad_spend": 0,
                            "ad_orders": 0,
                            "ad_sales": 0,
                            "ad_clicks": 0,
                            "ad_impressions": 0,
                            "acos": None,
                            "ctr": None,
                        }
                    )
        return rows

    def _serialize_country_metric(self, row: dict[str, Any]) -> dict[str, Any]:
        listing_price = to_float(row.get("listing_price"))
        margin_price_35 = to_float(row.get("margin_price_35"))
        margin_price_10 = to_float(row.get("margin_price_10"))
        ad_spend = to_float(row.get("ad_spend"))
        ad_sales = to_float(row.get("ad_sales"))
        acos = number_value(row.get("acos"))
        if acos is None and ad_sales:
            acos = ad_spend / ad_sales
        sales_qty = to_float(row.get("post_sales_qty", row.get("sales_qty")))
        sales_amount = to_float(row.get("post_sales_amount", row.get("sales_amount")))
        tacos = ad_spend / sales_amount if sales_amount else None
        order_gross_profit = to_float(row.get("post_order_gross_profit", row.get("order_gross_profit")))
        order_gross_margin = number_value(row.get("post_order_gross_margin", row.get("order_gross_margin")))
        if order_gross_margin is None and sales_amount:
            order_gross_margin = order_gross_profit / sales_amount
        conversion_rate = number_value(row.get("conversion_rate"))
        ctr = number_value(row.get("ctr"))
        price_risk = bool(listing_price and margin_price_35 and listing_price < margin_price_35)
        margin_prices = [
            {"target": target, "label": f"{target}%毛利", "price": round(to_float(row.get(f"margin_price_{target}")), 4)}
            for target in (35, 30, 25, 20, 15, 10, 5, 0)
            if row.get(f"margin_price_{target}") is not None
        ]
        return {
            "return_event_id": row.get("return_event_id"),
            "country": row.get("country") or "-",
            "local_sku_list": row.get("local_sku_list") or "",
            "currency": row.get("currency") or "",
            "metric_window_days": to_int(row.get("metric_window_days")) or 30,
            "pre_window_start": format_day(row.get("pre_window_start")),
            "pre_window_end": format_day(row.get("pre_window_end")),
            "post_window_start": format_day(row.get("post_window_start")),
            "post_window_end": format_day(row.get("post_window_end")),
            "listing_price": round(listing_price, 4),
            "margin_price_35": round(margin_price_35, 4),
            "margin_price_30": round(to_float(row.get("margin_price_30")), 4),
            "margin_price_25": round(to_float(row.get("margin_price_25")), 4),
            "margin_price_20": round(to_float(row.get("margin_price_20")), 4),
            "margin_price_15": round(to_float(row.get("margin_price_15")), 4),
            "margin_price_10": round(margin_price_10, 4),
            "margin_price_5": round(to_float(row.get("margin_price_5")), 4),
            "margin_price_0": round(to_float(row.get("margin_price_0")), 4),
            "margin_prices": margin_prices,
            "price_risk": price_risk,
            "price_gap_to_35": round(listing_price - margin_price_35, 4) if listing_price and margin_price_35 else None,
            "pre_sales_qty": round(to_float(row.get("pre_sales_qty")), 2),
            "pre_sales_amount": round(to_float(row.get("pre_sales_amount")), 2),
            "pre_order_gross_profit": round(to_float(row.get("pre_order_gross_profit")), 2),
            "sales_qty": round(sales_qty, 2),
            "natural_daily_sales": round(to_float(row.get("natural_daily_sales")), 4),
            "salable_days": to_int(row.get("salable_days")),
            "salable_daily_sales": round(to_float(row.get("salable_daily_sales")), 4),
            "sales_amount": round(sales_amount, 2),
            "order_gross_profit": round(order_gross_profit, 2),
            "order_gross_margin": round(order_gross_margin or 0, 6),
            "order_gross_margin_text": self._rate_text(order_gross_margin),
            "country_sales_recovery_rate": round(to_float(row.get("sales_recovery_rate")), 6) if row.get("sales_recovery_rate") is not None else None,
            "country_sales_recovery_rate_text": self._rate_text(row.get("sales_recovery_rate")),
            "sales_amount_recovery_rate": round(to_float(row.get("sales_amount_recovery_rate")), 6) if row.get("sales_amount_recovery_rate") is not None else None,
            "sales_amount_recovery_rate_text": self._rate_text(row.get("sales_amount_recovery_rate")),
            "avg_ranking": round(to_float(row.get("avg_ranking")), 2),
            "best_ranking": round(to_float(row.get("best_ranking")), 2),
            "worst_ranking": round(to_float(row.get("worst_ranking")), 2),
            "sessions_total": round(to_float(row.get("sessions_total")), 2),
            "conversion_rate": round(conversion_rate or 0, 6),
            "conversion_rate_text": self._rate_text(conversion_rate),
            "ad_spend": round(ad_spend, 2),
            "ad_orders": round(to_float(row.get("ad_orders")), 2),
            "ad_sales": round(ad_sales, 2),
            "ad_clicks": round(to_float(row.get("ad_clicks")), 2),
            "ad_impressions": round(to_float(row.get("ad_impressions")), 2),
            "acos": round(acos, 6) if acos is not None else None,
            "acos_text": self._rate_text(acos),
            "tacos": round(tacos, 6) if tacos is not None else None,
            "tacos_text": self._rate_text(tacos),
            "ctr": round(ctr or 0, 6),
            "ctr_text": self._rate_text(ctr),
        }

    def _listing_preview_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return self._empty_listing_preview()
        serialized = [self._serialize_country_metric(row) for row in rows]
        sales_amount = sum(item["sales_amount"] for item in serialized)
        ad_spend = sum(item["ad_spend"] for item in serialized)
        ad_sales = sum(item["ad_sales"] for item in serialized)
        acos = ad_spend / ad_sales if ad_sales else None
        tacos = ad_spend / sales_amount if sales_amount else None
        return {
            "period_days": serialized[0].get("metric_window_days") or 30,
            "period_start": serialized[0].get("post_window_start"),
            "period_end": serialized[0].get("post_window_end"),
            "country_count": len(serialized),
            "price_risk_country_count": sum(1 for item in serialized if item["price_risk"]),
            "top_countries": serialized[:3],
            "ad_spend": round(ad_spend, 2),
            "ad_sales": round(ad_sales, 2),
            "acos": round(acos, 6) if acos is not None else None,
            "acos_text": self._rate_text(acos),
            "tacos": round(tacos, 6) if tacos is not None else None,
            "tacos_text": self._rate_text(tacos),
            "sales_amount": round(sales_amount, 2),
        }

    def _attach_listing_previews(self, conn, snapshot_date: date, items: list[dict[str, Any]]) -> None:
        for item in items:
            item["listing_preview"] = self._empty_listing_preview()
        rows = self._listing_rows_for_events(conn, snapshot_date, items)
        grouped: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(self._event_key(row), []).append(row)
        for item in items:
            item["listing_preview"] = self._listing_preview_from_rows(grouped.get(self._event_key(item), []))

    def _country_metrics(self, conn, snapshot_date: date, event: dict[str, Any]) -> dict[str, Any]:
        rows = self._listing_rows_for_events(conn, snapshot_date, [event])
        if not rows:
            return self._empty_country_metrics(snapshot_date, event)
        items = [self._serialize_country_metric(row) for row in rows]
        sales_amount = sum(item["sales_amount"] for item in items)
        order_gross_profit = sum(item["order_gross_profit"] for item in items)
        ad_spend = sum(item["ad_spend"] for item in items)
        ad_sales = sum(item["ad_sales"] for item in items)
        acos = ad_spend / ad_sales if ad_sales else None
        tacos = ad_spend / sales_amount if sales_amount else None
        return {
            "snapshot_date": format_day(snapshot_date),
            "period_days": items[0].get("metric_window_days") or 30,
            "period_start": items[0].get("post_window_start"),
            "period_end": items[0].get("post_window_end"),
            "parent": {
                "site": event.get("country_category"),
                "store": event.get("seller_name_new"),
                "msku": event.get("seller_sku_adj"),
            },
            "summary": {
                "country_count": len(items),
                "price_risk_country_count": sum(1 for item in items if item["price_risk"]),
                "sales_qty": round(sum(item["sales_qty"] for item in items), 2),
                "sales_amount": round(sales_amount, 2),
                "order_gross_profit": round(order_gross_profit, 2),
                "order_gross_margin": round(order_gross_profit / sales_amount, 6) if sales_amount else 0,
                "ad_spend": round(ad_spend, 2),
                "ad_sales": round(ad_sales, 2),
                "acos": round(acos, 6) if acos is not None else None,
                "acos_text": self._rate_text(acos),
                "tacos": round(tacos, 6) if tacos is not None else None,
                "tacos_text": self._rate_text(tacos),
            },
            "items": items,
        }
    def _serialize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item = {
            **{key: number_value(value) for key, value in row.items()},
            "stockout_date": format_day(row.get("stockout_date")),
            "return_start_date": format_day(row.get("return_start_date")),
            "exit_date": format_day(row.get("exit_date")),
            "stable_recovery_start_date": format_day(row.get("stable_recovery_start_date")),
            "sales_recovery_rate_text": self._rate_text(row.get("sales_recovery_rate")),
            "d21_recovery_rate_text": self._rate_text(row.get("d21_recovery_rate")),
            "cumulative_avg_recovery_rate_text": self._rate_text(row.get("cumulative_avg_recovery_rate")),
        }
        if row.get("recovery_followup_flag"):
            item["recovery_statistics_days"] = number_value(row.get("days_to_standard")) or number_value(
                row.get("return_days")
            )
        else:
            item["recovery_statistics_days"] = number_value(row.get("recovery_window_days"))
        for key in ("recovery_followup_flag", "current_stable_recovery_flag", "recovery_fallback_flag"):
            if key in row:
                item[key] = bool(row.get(key))
        return item

    def _serialize_daily_detail(self, row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        sales_amount = number_value(row.get("sales_amount")) or 0
        gross_profit = number_value(row.get("order_gross_profit")) or 0
        gross_margin_rate = gross_profit / sales_amount if sales_amount else None
        day = format_day(row.get("dt_date"))
        return {
            "dt_date": day,
            "sales_qty": number_value(row.get("sales_qty")) or 0,
            "sales_amount": sales_amount,
            "order_gross_profit": gross_profit,
            "gross_margin_rate": gross_margin_rate,
            "gross_margin_rate_text": self._rate_text(gross_margin_rate),
            "fba_sellable": number_value(row.get("fba_sellable")) or 0,
            "fba_inbound": number_value(row.get("fba_inbound")) or 0,
            "day_tag": self._day_tag(day, event),
            "source_missing": False,
        }

    def _attach_followup_trend(self, rows: list[dict[str, Any]], event: dict[str, Any]) -> None:
        return_start = parse_day(event.get("return_start_date"))
        exit_day = parse_day(event.get("exit_date"))
        standard_exit = event.get("exit_reason") == "达标退出"
        pre_sales = number_value(event.get("pre_21d_sales_qty"))
        baseline_daily = float(pre_sales) / 21 if pre_sales else None
        followup = bool(event.get("recovery_followup_flag"))
        if followup and return_start:
            dated_rows = {parse_day(row.get("dt_date")): row for row in rows if parse_day(row.get("dt_date"))}
            last_day = max(dated_rows, default=None)
            cursor_day = return_start + timedelta(days=21)
            while last_day and cursor_day <= last_day:
                if cursor_day not in dated_rows:
                    rows.append(
                        {
                            "dt_date": cursor_day.isoformat(),
                            "sales_qty": 0,
                            "sales_amount": 0,
                            "order_gross_profit": 0,
                            "gross_margin_rate": None,
                            "gross_margin_rate_text": "",
                            "fba_sellable": 0,
                            "fba_inbound": 0,
                            "day_tag": "数据缺失（销量按0）",
                            "source_missing": True,
                        }
                    )
                cursor_day += timedelta(days=1)
            rows.sort(key=lambda row: parse_day(row.get("dt_date")) or date.min)
        cumulative_sales = 0.0
        for row in rows:
            row.setdefault("source_missing", False)
            row["return_day"] = None
            row["return_day_label"] = "-"
            row["daily_recovery_rate"] = None
            row["daily_recovery_rate_text"] = ""
            row["cumulative_avg_recovery_rate"] = None
            row["cumulative_avg_recovery_rate_text"] = ""
            row_day = parse_day(row.get("dt_date"))
            if return_start is None or row_day is None or row_day < return_start:
                continue
            return_day = (row_day - return_start).days + 1
            row["return_day"] = return_day
            row["return_day_label"] = (
                "达标退出" if standard_exit and row_day == exit_day else f"D{return_day}"
            )
            cumulative_sales += float(number_value(row.get("sales_qty")) or 0)
            if not followup or return_day <= 21 or baseline_daily is None:
                continue
            daily_rate = float(number_value(row.get("sales_qty")) or 0) / baseline_daily
            cumulative_rate = (cumulative_sales / return_day) / baseline_daily
            row["daily_recovery_rate"] = daily_rate
            row["daily_recovery_rate_text"] = self._rate_text(daily_rate)
            row["cumulative_avg_recovery_rate"] = cumulative_rate
            row["cumulative_avg_recovery_rate_text"] = self._rate_text(cumulative_rate)

    def _day_tag(self, day: str | None, event: dict[str, Any]) -> str:
        if not day:
            return ""
        if day == event.get("stockout_date"):
            return "断货日"
        if day == event.get("return_start_date"):
            return "返场开始"
        if day < (event.get("stockout_date") or ""):
            return "断货前"
        if day < (event.get("return_start_date") or ""):
            return "断货中"
        return "返场后"

    def _rate_text(self, value: Any) -> str:
        rate = number_value(value)
        return "" if rate is None else f"{rate * 100:.1f}%"

    def _meta(self, conn) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute("select distinct snapshot_date from dashboard_return_goods_events order by snapshot_date desc limit 30")
            dates = [format_day(row.get("snapshot_date")) for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct country_category
                from dashboard_return_goods_events
                where country_category is not null and country_category <> ''
                order by country_category
                """
            )
            country_categories = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct seller_name_new
                from dashboard_return_goods_events
                where seller_name_new is not null and seller_name_new <> ''
                order by seller_name_new
                limit 500
                """
            )
            stores = [row["seller_name_new"] for row in cursor.fetchall()]
        return {
            "dates": [item for item in dates if item],
            "country_categories": country_categories,
            "stores": stores,
            "stages": ["观察期", "运营干预期", "超期未处理", "已退出"],
            "warning_types": ["二次断货", "严重超期", "干预期严重低恢复", "干预期未恢复"],
        }


return_goods_service = ReturnGoodsDataService()
