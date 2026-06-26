from __future__ import annotations

import math
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql

from etl.replenishment_update import apply_database_ini_env


LEVEL_ALL = "全部"
TRACKING_WINDOWS = {7, 14, 30}
PRODUCT_CATEGORY_PERIODS = {7, 14, 30, 90}
PRODUCT_CATEGORY_SALES_COLUMNS = {
    7: "final_sales_7d",
    14: "final_sales_14d",
    30: "final_sales_30d",
    90: "sales_90d",
}


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_int(value: Any) -> int:
    return int(round(to_float(value)))


def format_day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


class ReplenishmentTrackingService:
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
        tracking_window_days: int | str | None = 30,
        level: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        status: str = "all",
        sort_field: str = "",
        sort_dir: str = "",
        page: int = 1,
        page_size: int = 20,
        category_period_days: int | str | None = 30,
    ) -> dict[str, Any]:
        safe_window = self._normalize_window_days(tracking_window_days)
        safe_category_period = self._normalize_category_period_days(category_period_days)
        safe_page_size = max(10, min(100, int(page_size or 20)))
        safe_page = max(1, int(page or 1))
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date:
                return self._empty_payload(safe_window, safe_category_period, safe_page, safe_page_size)
            base_filters, base_params = self._build_where(selected_date, safe_window, level, site, store, keyword, "all")
            detail_filters, detail_params = self._build_where(selected_date, safe_window, level, site, store, keyword, status)
            summary = self._summary(conn, base_filters, base_params)
            level_summary = self._level_summary(conn, base_filters, base_params)
            category_mix = self._level_category_mix(conn, base_filters, base_params, safe_category_period)
            self._attach_category_mix(level_summary, category_mix)
            total = self._total(conn, detail_filters, detail_params)
            total_pages = max(1, math.ceil(total / safe_page_size))
            safe_page = min(safe_page, total_pages)
            items = self._items(conn, detail_filters, detail_params, sort_field, sort_dir, safe_page, safe_page_size, safe_category_period)
            meta = self._meta(conn)

        return {
            "snapshot_date": format_day(selected_date),
            "tracking_window_days": safe_window,
            "category_period_days": safe_category_period,
            "meta": meta,
            "summary": summary,
            "level_summary": level_summary,
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
            "selected_level": level,
        }

    def get_detail(
        self,
        snapshot_date: str = "",
        tracking_window_days: int | str | None = 30,
        site: str = "",
        store: str = "",
        msku: str = "",
    ) -> dict[str, Any]:
        safe_window = self._normalize_window_days(tracking_window_days)
        selected_date = parse_day(snapshot_date)
        if not selected_date or not site or not store or not msku:
            return {"rows": []}
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        source_type,
                        link_attribution,
                        purchase_plan_sn,
                        purchase_plan_time,
                        purchase_plan_status,
                        purchase_plan_qty,
                        purchase_expect_arrive_time,
                        supplier_name,
                        purchaser_name,
                        order_sn,
                        shipment_sn,
                        plan_create_time,
                        plan_status,
                        shipment_status,
                        logistics_status,
                        method_name,
                        logistics_channel_name,
                        logistics_provider_name,
                        shipment_plan_quantity,
                        quantity_shipped,
                        quantity_received,
                        shipment_time,
                        actual_shipment_time,
                        expected_arrival_date,
                        eta_date,
                        delivery_date,
                        sku,
                        nation
                    from dashboard_replenishment_tracking_detail
                    where snapshot_date = %(snapshot_date)s
                      and tracking_window_days = %(tracking_window_days)s
                      and country_category = %(site)s
                      and seller_name_new = %(store)s
                      and seller_sku_adj = %(msku)s
                    order by
                        case source_type
                            when 'purchase_plan' then 1
                            when 'shipment_plan' then 2
                            when 'shipment_detail' then 3
                            else 9
                        end,
                        coalesce(actual_shipment_time, shipment_time, plan_create_time, purchase_plan_time) desc
                    limit 200
                    """,
                    {
                        "snapshot_date": selected_date,
                        "tracking_window_days": safe_window,
                        "site": site,
                        "store": store,
                        "msku": msku,
                    },
                )
                rows = cursor.fetchall()
        return {"rows": self._serialize_detail_rows(rows)}

    def _latest_date(self, conn) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute("select max(snapshot_date) as snapshot_date from dashboard_replenishment_tracking_snapshot")
            row = cursor.fetchone() or {}
        return row.get("snapshot_date")

    def _meta(self, conn) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select distinct snapshot_date
                from dashboard_replenishment_tracking_snapshot
                order by snapshot_date desc
                limit 30
                """
            )
            dates = [format_day(row.get("snapshot_date")) for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct country_category
                from dashboard_replenishment_tracking_snapshot
                where country_category is not null and country_category <> ''
                order by country_category
                """
            )
            sites = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct seller_name_new
                from dashboard_replenishment_tracking_snapshot
                where seller_name_new is not null and seller_name_new <> ''
                order by seller_name_new
                limit 500
                """
            )
            stores = [row["seller_name_new"] for row in cursor.fetchall()]
        return {
            "dates": [item for item in dates if item],
            "sites": sites,
            "stores": stores,
            "levels": [
                {"key": "all", "label": LEVEL_ALL},
                {"key": "紧急补货", "label": "紧急补货"},
                {"key": "建议补货", "label": "建议补货"},
                {"key": "计划补货", "label": "计划补货"},
                {"key": "库存充足", "label": "库存充足"},
                {"key": "日销为0", "label": "日销为0"},
                {"key": "历史兜底", "label": "历史兜底"},
            ],
            "statuses": [
                {"key": "all", "label": "全部状态"},
                {"key": "unplanned", "label": "未建采购计划"},
                {"key": "purchase_planned", "label": "已建采购计划"},
                {"key": "shipment_planned", "label": "已建本次FBA"},
                {"key": "shipped", "label": "本次已发货"},
                {"key": "historical_shipped", "label": "历史采购发货"},
                {"key": "received", "label": "已收货"},
            ],
        }

    def _build_where(
        self,
        snapshot_date: date,
        tracking_window_days: int,
        level: str,
        site: str,
        store: str,
        keyword: str,
        status: str,
    ) -> tuple[str, dict[str, Any]]:
        clauses = [
            "s.snapshot_date = %(snapshot_date)s",
            "s.tracking_window_days = %(tracking_window_days)s",
            "s.replenishment_level_sort in (1, 2, 3)",
        ]
        params: dict[str, Any] = {"snapshot_date": snapshot_date, "tracking_window_days": tracking_window_days}
        if level and level != "all":
            clauses.append("s.replenishment_level = %(level)s")
            params["level"] = level
        if site and site != "all":
            clauses.append("s.country_category = %(site)s")
            params["site"] = site
        if store and store != "all":
            clauses.append("s.seller_name_new = %(store)s")
            params["store"] = store
        if keyword:
            clauses.append("(s.seller_sku_adj like %(keyword)s or s.seller_name_new like %(keyword)s or coalesce(s.max_sku, '') like %(keyword)s)")
            params["keyword"] = f"%{keyword.strip()}%"
        if status == "unplanned":
            clauses.append("s.purchase_planned_flag = 0")
        elif status == "purchase_planned":
            clauses.append("s.purchase_planned_flag = 1")
        elif status == "shipment_planned":
            clauses.append("s.current_fba_shipment_plan_qty > 0")
        elif status == "shipped":
            clauses.append("s.current_shipped_qty > 0")
        elif status == "historical_shipped":
            clauses.append("s.historical_shipped_qty > 0")
        elif status == "received":
            clauses.append("s.received_qty > 0")
        return " and ".join(clauses), params

    def _summary(self, conn, filters: str, params: dict[str, Any]) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(*) as msku_count,
                    sum(case when replenishment_level_sort in (1, 2, 3) then 1 else 0 end) as active_msku_count,
                    sum(coalesce(replenishment_qty, 0)) as replenishment_qty,
                    sum(coalesce(replenishment_value, 0)) as replenishment_value,
                    sum(case when purchase_planned_flag = 1 then 1 else 0 end) as purchase_planned_msku_count,
                    sum(case when purchase_planned_flag = 0 then 1 else 0 end) as purchase_unplanned_msku_count,
                    sum(coalesce(purchase_plan_count, 0)) as purchase_plan_count,
                    sum(coalesce(purchase_plan_total_qty, 0)) as purchase_plan_total_qty,
                    sum(coalesce(purchase_plan_qty, 0)) as purchase_plan_qty,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as purchase_shipping_qty,
                    sum(case when current_fba_shipment_plan_qty > 0 then 1 else 0 end) as fba_plan_msku_count,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as fba_shipment_plan_qty,
                    sum(coalesce(current_fba_shipment_plan_qty, 0)) as current_fba_shipment_plan_qty,
                    sum(coalesce(current_shipped_qty, 0)) as current_shipped_qty,
                    sum(coalesce(historical_fba_shipment_plan_qty, 0)) as historical_fba_shipment_plan_qty,
                    sum(coalesce(historical_shipped_qty, 0)) as historical_shipped_qty,
                    sum(case when current_shipped_qty > 0 then 1 else 0 end) as shipped_msku_count,
                    sum(case when historical_shipped_qty > 0 then 1 else 0 end) as historical_shipped_msku_count,
                    sum(coalesce(shipped_qty, 0)) as shipped_qty,
                    sum(case when received_qty > 0 then 1 else 0 end) as received_msku_count,
                    sum(coalesce(received_qty, 0)) as received_qty,
                    sum(coalesce(pending_ship_qty, 0)) as pending_ship_qty,
                    sum(coalesce(pending_receive_qty, 0)) as pending_receive_qty
                from dashboard_replenishment_tracking_snapshot s
                where {filters}
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return self._serialize_summary(row)

    def _level_summary(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    coalesce(replenishment_level_sort, 99) as sort,
                    coalesce(replenishment_level, '未分层') as level,
                    count(*) as msku_count,
                    sum(coalesce(replenishment_qty, 0)) as replenishment_qty,
                    sum(coalesce(replenishment_value, 0)) as replenishment_value,
                    sum(case when purchase_planned_flag = 1 then 1 else 0 end) as purchase_planned_msku_count,
                    sum(case when purchase_planned_flag = 0 then 1 else 0 end) as purchase_unplanned_msku_count,
                    sum(coalesce(purchase_plan_count, 0)) as purchase_plan_count,
                    sum(coalesce(purchase_plan_total_qty, 0)) as purchase_plan_total_qty,
                    sum(coalesce(purchase_plan_qty, 0)) as purchase_plan_qty,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as purchase_shipping_qty,
                    sum(case when current_fba_shipment_plan_qty > 0 then 1 else 0 end) as fba_plan_msku_count,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as fba_shipment_plan_qty,
                    sum(coalesce(current_fba_shipment_plan_qty, 0)) as current_fba_shipment_plan_qty,
                    sum(coalesce(current_shipped_qty, 0)) as current_shipped_qty,
                    sum(coalesce(historical_fba_shipment_plan_qty, 0)) as historical_fba_shipment_plan_qty,
                    sum(coalesce(historical_shipped_qty, 0)) as historical_shipped_qty,
                    sum(case when current_shipped_qty > 0 then 1 else 0 end) as shipped_msku_count,
                    sum(case when historical_shipped_qty > 0 then 1 else 0 end) as historical_shipped_msku_count,
                    sum(coalesce(shipped_qty, 0)) as shipped_qty,
                    sum(coalesce(received_qty, 0)) as received_qty
                from dashboard_replenishment_tracking_snapshot s
                where {filters}
                group by coalesce(replenishment_level_sort, 99), coalesce(replenishment_level, '未分层')
                order by sort
                """,
                params,
            )
            rows = cursor.fetchall()
        return [self._serialize_level_summary(row) for row in rows]

    def _level_category_mix(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        category_period_days: int,
    ) -> dict[str, list[dict[str, Any]]]:
        category_expr = self._product_category_expr(category_period_days)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    coalesce(s.replenishment_level, '未分层') as level,
                    coalesce(nullif({category_expr}, ''), '未分类') as category,
                    count(*) as msku_count,
                    sum(case when purchase_planned_flag = 1 then 1 else 0 end) as purchase_planned_msku_count,
                    sum(case when purchase_planned_flag = 0 then 1 else 0 end) as purchase_unplanned_msku_count,
                    sum(coalesce(purchase_plan_count, 0)) as purchase_plan_count,
                    sum(coalesce(purchase_plan_total_qty, 0)) as purchase_plan_total_qty,
                    sum(coalesce(replenishment_qty, 0)) as replenishment_qty,
                    sum(coalesce(replenishment_value, 0)) as replenishment_value,
                    sum(coalesce(purchase_plan_qty, 0)) as purchase_plan_qty,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as purchase_shipping_qty,
                    sum(coalesce(fba_shipment_plan_qty, 0)) as fba_shipment_plan_qty,
                    sum(coalesce(current_fba_shipment_plan_qty, 0)) as current_fba_shipment_plan_qty,
                    sum(coalesce(current_shipped_qty, 0)) as current_shipped_qty,
                    sum(coalesce(historical_fba_shipment_plan_qty, 0)) as historical_fba_shipment_plan_qty,
                    sum(coalesce(historical_shipped_qty, 0)) as historical_shipped_qty,
                    sum(coalesce(shipped_qty, 0)) as shipped_qty,
                    sum(coalesce(received_qty, 0)) as received_qty
                from dashboard_replenishment_tracking_snapshot s
                left join dashboard_pur_plan_replenish_data p
                       on p.cur_date = s.snapshot_date
                      and p.country_category = s.country_category
                      and p.seller_name_new = s.seller_name_new
                      and p.seller_sku_adj = s.seller_sku_adj
                where {filters}
                group by level, category
                order by msku_count desc, category
                """,
                params,
            )
            rows = cursor.fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.get("level") or "未分层", []).append(
                {
                    "category": row.get("category") or "未分类",
                    "msku_count": to_int(row.get("msku_count")),
                    "purchase_planned_msku_count": to_int(row.get("purchase_planned_msku_count")),
                    "purchase_unplanned_msku_count": to_int(row.get("purchase_unplanned_msku_count")),
                    "purchase_plan_count": to_int(row.get("purchase_plan_count")),
                    "purchase_plan_total_qty": to_float(row.get("purchase_plan_total_qty")),
                    "replenishment_qty": to_float(row.get("replenishment_qty")),
                    "replenishment_value": to_float(row.get("replenishment_value")),
                    "purchase_plan_qty": to_float(row.get("purchase_plan_qty")),
                    "purchase_shipping_qty": to_float(row.get("purchase_shipping_qty")),
                    "fba_shipment_plan_qty": to_float(row.get("fba_shipment_plan_qty")),
                    "current_fba_shipment_plan_qty": to_float(row.get("current_fba_shipment_plan_qty")),
                    "current_shipped_qty": to_float(row.get("current_shipped_qty")),
                    "historical_fba_shipment_plan_qty": to_float(row.get("historical_fba_shipment_plan_qty")),
                    "historical_shipped_qty": to_float(row.get("historical_shipped_qty")),
                    "shipped_qty": to_float(row.get("shipped_qty")),
                    "received_qty": to_float(row.get("received_qty")),
                }
            )
        return grouped

    def _attach_category_mix(self, levels: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> None:
        for level in levels:
            level["category_purchase_mix"] = grouped.get(level.get("level") or "未分层", [])

    def _total(self, conn, filters: str, params: dict[str, Any]) -> int:
        with conn.cursor() as cursor:
            cursor.execute(
                f"select count(*) as total from dashboard_replenishment_tracking_snapshot s where {filters}",
                params,
            )
            row = cursor.fetchone() or {}
        return to_int(row.get("total"))

    def _items(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        sort_field: str,
        sort_dir: str,
        page: int,
        page_size: int,
        category_period_days: int,
    ) -> list[dict[str, Any]]:
        query_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
        sort_map = {
            "level": "s.replenishment_level_sort",
            "msku": "s.seller_sku_adj",
            "store": "s.seller_name_new",
            "replenishment_qty": "s.replenishment_qty",
            "purchase_plan_qty": "s.purchase_plan_qty",
            "fba_shipment_plan_qty": "s.fba_shipment_plan_qty",
            "shipped_qty": "s.current_shipped_qty",
            "received_qty": "s.received_qty",
            "nearest_fba_eta_date": "s.nearest_fba_eta_date",
            "replenishment_value": "s.replenishment_value",
        }
        sort_column = sort_map.get(sort_field or "", "s.replenishment_level_sort")
        direction = "desc" if str(sort_dir or "").lower() == "desc" else "asc"
        category_expr = self._product_category_expr(category_period_days)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    s.snapshot_date,
                    s.tracking_window_days,
                    s.country_category,
                    s.seller_name_new,
                    s.seller_sku_adj,
                    s.max_sku,
                    s.replenishment_level,
                    s.replenishment_level_sort,
                    {category_expr} as product_category,
                    s.replenishment_qty,
                    s.replenishment_value,
                    s.purchase_snapshot_plan_qty,
                    s.purchase_snapshot_shipping_qty,
                    s.purchase_planned_flag,
                    s.purchase_plan_count,
                    s.purchase_plan_total_qty,
                    s.current_purchase_shipping_qty,
                    s.historical_purchase_shipping_qty,
                    s.purchase_plan_qty,
                    s.purchase_plan_sn_list,
                    s.purchase_plan_status,
                    s.fba_shipment_planned_flag,
                    s.fba_shipment_plan_qty,
                    s.current_fba_shipment_plan_qty,
                    s.current_shipped_qty,
                    s.historical_fba_shipment_plan_qty,
                    s.historical_shipped_qty,
                    s.shipment_attribution,
                    s.shipment_order_sn_list,
                    s.shipment_plan_status,
                    s.shipped_qty,
                    s.received_qty,
                    s.pending_ship_qty,
                    s.pending_receive_qty,
                    s.main_shipping_method,
                    s.main_logistics_channel,
                    s.main_logistics_provider,
                    s.latest_purchase_plan_time,
                    s.latest_plan_time,
                    s.latest_shipment_time,
                    s.nearest_fba_eta_date,
                    s.latest_status
                from dashboard_replenishment_tracking_snapshot s
                left join dashboard_pur_plan_replenish_data p
                       on p.cur_date = s.snapshot_date
                      and p.country_category = s.country_category
                      and p.seller_name_new = s.seller_name_new
                      and p.seller_sku_adj = s.seller_sku_adj
                where {filters}
                order by {sort_column} {direction}, s.replenishment_qty desc, s.seller_sku_adj
                limit %(limit)s offset %(offset)s
                """,
                query_params,
            )
            rows = cursor.fetchall()
        return [self._serialize_item(row) for row in rows]

    def _serialize_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "msku_count": to_int(row.get("msku_count")),
            "active_msku_count": to_int(row.get("active_msku_count")),
            "replenishment_qty": to_float(row.get("replenishment_qty")),
            "replenishment_value": to_float(row.get("replenishment_value")),
            "purchase_planned_msku_count": to_int(row.get("purchase_planned_msku_count")),
            "purchase_unplanned_msku_count": to_int(row.get("purchase_unplanned_msku_count")),
            "purchase_plan_count": to_int(row.get("purchase_plan_count")),
            "purchase_plan_total_qty": to_float(row.get("purchase_plan_total_qty")),
            "current_purchase_shipping_qty": to_float(row.get("current_purchase_shipping_qty")),
            "historical_purchase_shipping_qty": to_float(row.get("historical_purchase_shipping_qty")),
            "purchase_plan_qty": to_float(row.get("purchase_plan_qty")),
            "purchase_shipping_qty": to_float(row.get("purchase_shipping_qty")),
            "fba_plan_msku_count": to_int(row.get("fba_plan_msku_count")),
            "fba_shipment_plan_qty": to_float(row.get("fba_shipment_plan_qty")),
            "current_fba_shipment_plan_qty": to_float(row.get("current_fba_shipment_plan_qty")),
            "current_shipped_qty": to_float(row.get("current_shipped_qty")),
            "historical_fba_shipment_plan_qty": to_float(row.get("historical_fba_shipment_plan_qty")),
            "historical_shipped_qty": to_float(row.get("historical_shipped_qty")),
            "shipped_msku_count": to_int(row.get("shipped_msku_count")),
            "historical_shipped_msku_count": to_int(row.get("historical_shipped_msku_count")),
            "shipped_qty": to_float(row.get("shipped_qty")),
            "received_msku_count": to_int(row.get("received_msku_count")),
            "received_qty": to_float(row.get("received_qty")),
            "pending_ship_qty": to_float(row.get("pending_ship_qty")),
            "pending_receive_qty": to_float(row.get("pending_receive_qty")),
        }

    def _serialize_level_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "sort": to_int(row.get("sort")),
            "level": row.get("level") or "未分层",
            "msku_count": to_int(row.get("msku_count")),
            "replenishment_qty": to_float(row.get("replenishment_qty")),
            "replenishment_value": to_float(row.get("replenishment_value")),
            "purchase_planned_msku_count": to_int(row.get("purchase_planned_msku_count")),
            "purchase_unplanned_msku_count": to_int(row.get("purchase_unplanned_msku_count")),
            "purchase_plan_count": to_int(row.get("purchase_plan_count")),
            "purchase_plan_total_qty": to_float(row.get("purchase_plan_total_qty")),
            "purchase_plan_qty": to_float(row.get("purchase_plan_qty")),
            "purchase_shipping_qty": to_float(row.get("purchase_shipping_qty")),
            "fba_plan_msku_count": to_int(row.get("fba_plan_msku_count")),
            "fba_shipment_plan_qty": to_float(row.get("fba_shipment_plan_qty")),
            "current_fba_shipment_plan_qty": to_float(row.get("current_fba_shipment_plan_qty")),
            "current_shipped_qty": to_float(row.get("current_shipped_qty")),
            "historical_fba_shipment_plan_qty": to_float(row.get("historical_fba_shipment_plan_qty")),
            "historical_shipped_qty": to_float(row.get("historical_shipped_qty")),
            "shipped_msku_count": to_int(row.get("shipped_msku_count")),
            "historical_shipped_msku_count": to_int(row.get("historical_shipped_msku_count")),
            "shipped_qty": to_float(row.get("shipped_qty")),
            "received_qty": to_float(row.get("received_qty")),
        }

    def _serialize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_date": format_day(row.get("snapshot_date")),
            "tracking_window_days": to_int(row.get("tracking_window_days")),
            "country": row.get("country_category"),
            "store": row.get("seller_name_new"),
            "msku": row.get("seller_sku_adj"),
            "sku": row.get("max_sku") or "",
            "level": row.get("replenishment_level") or "",
            "level_sort": to_int(row.get("replenishment_level_sort")),
            "category": row.get("product_category") or "",
            "replenishment_qty": to_float(row.get("replenishment_qty")),
            "replenishment_value": to_float(row.get("replenishment_value")),
            "purchase_snapshot_plan_qty": to_float(row.get("purchase_snapshot_plan_qty")),
            "purchase_snapshot_shipping_qty": to_float(row.get("purchase_snapshot_shipping_qty")),
            "purchase_planned": bool(to_int(row.get("purchase_planned_flag"))),
            "purchase_plan_count": to_int(row.get("purchase_plan_count")),
            "purchase_plan_total_qty": to_float(row.get("purchase_plan_total_qty")),
            "current_purchase_shipping_qty": to_float(row.get("current_purchase_shipping_qty")),
            "historical_purchase_shipping_qty": to_float(row.get("historical_purchase_shipping_qty")),
            "purchase_plan_qty": to_float(row.get("purchase_plan_qty")),
            "purchase_plan_sn_list": row.get("purchase_plan_sn_list") or "",
            "purchase_plan_status": row.get("purchase_plan_status") or "",
            "fba_shipment_planned": bool(to_int(row.get("fba_shipment_planned_flag"))),
            "fba_shipment_plan_qty": to_float(row.get("fba_shipment_plan_qty")),
            "current_fba_shipment_plan_qty": to_float(row.get("current_fba_shipment_plan_qty")),
            "current_shipped_qty": to_float(row.get("current_shipped_qty")),
            "historical_fba_shipment_plan_qty": to_float(row.get("historical_fba_shipment_plan_qty")),
            "historical_shipped_qty": to_float(row.get("historical_shipped_qty")),
            "shipment_attribution": row.get("shipment_attribution") or "none",
            "shipment_order_sn_list": row.get("shipment_order_sn_list") or "",
            "shipment_plan_status": row.get("shipment_plan_status") or "",
            "shipped_qty": to_float(row.get("shipped_qty")),
            "received_qty": to_float(row.get("received_qty")),
            "pending_ship_qty": to_float(row.get("pending_ship_qty")),
            "pending_receive_qty": to_float(row.get("pending_receive_qty")),
            "main_shipping_method": row.get("main_shipping_method") or "",
            "main_logistics_channel": row.get("main_logistics_channel") or "",
            "main_logistics_provider": row.get("main_logistics_provider") or "",
            "latest_purchase_plan_time": self._format_datetime(row.get("latest_purchase_plan_time")),
            "latest_plan_time": self._format_datetime(row.get("latest_plan_time")),
            "latest_shipment_time": self._format_datetime(row.get("latest_shipment_time")),
            "nearest_fba_eta_date": self._format_date(row.get("nearest_fba_eta_date")),
            "nearest_fba_eta_days": self._days_from_today(row.get("nearest_fba_eta_date")),
            "nearest_fba_eta_label": self._format_eta_label(row.get("nearest_fba_eta_date")),
            "latest_status": row.get("latest_status") or "",
        }

    def _serialize_detail(self, row: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: (self._format_datetime(value) if isinstance(value, datetime) else to_float(value) if isinstance(value, Decimal) else value)
            for key, value in row.items()
        }
        result["source_type_label"] = self._source_type_label(result.get("source_type"))
        result["shipment_time_display"] = result.get("actual_shipment_time") or result.get("shipment_time") or ""
        return result

    def _serialize_detail_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            self._serialize_detail(row)
            for row in rows
            if row.get("source_type") != "local_snapshot"
        ]

    def _source_type_label(self, value: Any) -> str:
        source_type = str(value or "")
        return {
            "purchase_plan": "采购计划",
            "shipment_plan": "FBA发货计划",
            "shipment_detail": "FBA发货单",
            "local_snapshot": "本地快照",
        }.get(source_type, source_type)

    def _format_datetime(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.isoformat()
        return ""

    def _format_date(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return ""

    def _days_from_today(self, value: Any) -> int | None:
        if isinstance(value, datetime):
            eta_day = value.date()
        elif isinstance(value, date):
            eta_day = value
        else:
            return None
        return (eta_day - date.today()).days

    def _format_eta_label(self, value: Any) -> str:
        eta_day = self._format_date(value)
        days = self._days_from_today(value)
        if not eta_day or days is None:
            return ""
        if days > 0:
            return f"{eta_day}（{days}天）"
        if days == 0:
            return f"{eta_day}（今天）"
        return f"{eta_day}（已超{abs(days)}天）"

    def _normalize_window_days(self, value: int | str | None) -> int:
        try:
            days = int(value or 30)
        except (TypeError, ValueError):
            days = 30
        return days if days in TRACKING_WINDOWS else 30

    def _normalize_category_period_days(self, value: int | str | None) -> int:
        try:
            days = int(value or 30)
        except (TypeError, ValueError):
            days = 30
        return days if days in PRODUCT_CATEGORY_PERIODS else 30

    def _product_category_expr(self, period_days: int | str | None) -> str:
        safe_period = self._normalize_category_period_days(period_days)
        sales_col = f"p.{PRODUCT_CATEGORY_SALES_COLUMNS[safe_period]}"
        salable_col = f"p.r_{safe_period}d_salable_days"
        margin_col = f"p.pprofit_ratio_{safe_period}d"
        daily_sales_expr = f"case when {salable_col} > 0 then {sales_col} / {salable_col} else 0 end"
        return f"""
            case
                when p.seller_sku_adj is null then s.product_category
                when ({daily_sales_expr}) >= 5 and {margin_col} >= 0.15 then '明星产品'
                when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and {margin_col} >= 0.25 then '明星产品'
                when ({daily_sales_expr}) >= 5 and {margin_col} >= 0.05 and {margin_col} < 0.15 then '潜力产品'
                when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and {margin_col} >= 0.10 and {margin_col} < 0.25 then '潜力产品'
                when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and {margin_col} >= 0.05 and {margin_col} < 0.10 then '瘦狗产品'
                when ({daily_sales_expr}) < 1 and {margin_col} >= 0.05 then '瘦狗产品'
                when ({daily_sales_expr}) = 0 or (({daily_sales_expr}) > 1 and {margin_col} < 0.05) then '问题产品'
                else '问题产品'
            end
        """.strip()

    def _empty_payload(self, tracking_window_days: int, category_period_days: int, page: int, page_size: int) -> dict[str, Any]:
        return {
            "snapshot_date": None,
            "tracking_window_days": tracking_window_days,
            "category_period_days": category_period_days,
            "meta": {"dates": [], "sites": [], "stores": [], "levels": [], "statuses": []},
            "summary": self._serialize_summary({}),
            "level_summary": [],
            "items": [],
            "total": 0,
            "page": max(1, int(page or 1)),
            "page_size": page_size,
            "total_pages": 1,
            "selected_level": "all",
        }


replenishment_tracking_service = ReplenishmentTrackingService()
