from __future__ import annotations

import math
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql

from etl.replenishment_update import apply_database_ini_env


TRACKING_WINDOW_DAYS = 30
PRODUCT_CATEGORY_PERIODS = {7, 14, 30, 90}
PRODUCT_CATEGORY_COLUMNS = {
    7: "product_category_7d",
    14: "product_category_14d",
    30: "product_category_30d",
    90: "product_category_90d",
}
PURCHASE_STATUS_LABELS = {
    "current": "本次补货后采购",
    "historical": "历史采购在途",
    "mixed": "本次+历史采购",
    "none": "未采购",
}
FBA_STATUS_LABELS = {
    "current": "本次FBA在途",
    "historical": "历史FBA在途",
    "mixed": "本次+历史FBA在途",
    "none": "未建FBA",
}


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_day(value: Any) -> str:
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_int(value: Any) -> int:
    return int(round(to_float(value)))


def purchase_status_label(value: str | None) -> str:
    return PURCHASE_STATUS_LABELS.get(value or "none", PURCHASE_STATUS_LABELS["none"])


def fba_status_label(value: str | None) -> str:
    return FBA_STATUS_LABELS.get(value or "none", FBA_STATUS_LABELS["none"])


def format_eta_text(days: int | float | None) -> str:
    if days is None:
        return "-"
    days_int = int(days)
    if days_int == 0:
        return "今天预计到货"
    if days_int > 0:
        return f"{days_int}天后到货"
    return f"已过预计到货{abs(days_int)}天"


def chain_state(row: dict[str, Any]) -> tuple[str, str, str]:
    purchase_qty = to_float(row.get("purchase_plan_qty"))
    inbound_qty = to_float(row.get("purchase_inbound_qty"))
    if to_int(row.get("purchase_plan_flag")) <= 0:
        return "建采购计划", "建采购计划", "未匹配到补货后的采购计划"
    if to_int(row.get("supplier_shipped_flag")) <= 0:
        return "采购在途", "采购在途", f"已建采购计划，但未确认采购在途 {purchase_qty:g}"
    if to_int(row.get("local_received_flag")) <= 0:
        return "到本地仓", "到本地仓", f"采购已在途，但未确认到本地仓 {inbound_qty:g}"
    if to_int(row.get("qc_passed_flag")) <= 0:
        return "质检通过", "质检通过", "已到本地仓，但未确认质检通过"
    if to_int(row.get("fba_plan_flag")) <= 0:
        return "建FBA计划", "建FBA计划", f"采购已响应，但未确认创建FBA计划 {purchase_qty:g}"
    if to_int(row.get("fba_shipped_flag")) <= 0:
        return "FBA出库", "FBA出库", "已建FBA计划，但未确认出库在途"
    if to_int(row.get("fba_receiving_flag")) <= 0:
        return "FBA接收", "FBA接收", "FBA在途，未开始接收"
    if to_int(row.get("fba_closed_flag")) <= 0:
        return "完成", "FBA接收", "FBA已接收，未确认完成"
    return "完成", "链路完成", "链路完成"


def map_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    level = row.get("current_replenishment_level") or "未分层"
    history_levels = row.get("historical_replenishment_levels") or ""
    appearance_days = to_int(row.get("appearance_days"))
    tags = []
    if appearance_days >= 3:
        tags.append(f"反复出现{appearance_days}天")
    if "紧急补货" in history_levels and not str(history_levels).startswith("紧急补货"):
        tags.append("曾升级为紧急")
    if level == "紧急补货":
        tags.append("当前仍紧急")

    current_node, breakpoint_node, breakpoint_reason = chain_state(row)
    return {
        "msku": row.get("seller_sku_adj") or "",
        "sku": row.get("sku") or "",
        "store": row.get("seller_name_new") or "",
        "country": row.get("country_category") or "",
        "level": level,
        "historical_replenishment_levels": history_levels,
        "product_category": row.get("selected_product_category") or row.get("product_category") or "未分类",
        "first_replenishment_date": format_day(row.get("first_replenishment_date")),
        "latest_replenishment_date": format_day(row.get("latest_replenishment_date")),
        "appearance_days": appearance_days,
        "replenishment_tags": "、".join(tags),
        "latest_replenishment_qty": to_float(row.get("latest_replenishment_qty")),
        "latest_replenishment_value": to_float(row.get("latest_replenishment_value")),
        "purchase_status": row.get("purchase_status") or "none",
        "purchase_status_label": purchase_status_label(row.get("purchase_status")),
        "current_purchase_plan_count": to_int(row.get("current_purchase_plan_count")),
        "current_purchase_plan_qty": to_float(row.get("current_purchase_plan_qty")),
        "current_purchase_shipping_qty": to_float(row.get("current_purchase_shipping_qty")),
        "historical_purchase_shipping_qty": to_float(row.get("historical_purchase_shipping_qty")),
        "local_stock_qty": to_float(row.get("local_stock_qty")),
        "fba_status": row.get("fba_status") or "none",
        "fba_status_label": fba_status_label(row.get("fba_status")),
        "current_fba_inbound_qty": to_float(row.get("current_fba_inbound_qty")),
        "historical_fba_inbound_qty": to_float(row.get("historical_fba_inbound_qty")),
        "received_qty": to_float(row.get("received_qty")),
        "nearest_fba_eta_date": format_day(row.get("nearest_fba_eta_date")),
        "nearest_fba_eta_days": row.get("nearest_fba_eta_days"),
        "nearest_fba_eta_text": format_eta_text(row.get("nearest_fba_eta_days")),
        "purchase_plan_flag": to_int(row.get("purchase_plan_flag")),
        "purchase_plan_count": to_int(row.get("purchase_plan_count")),
        "purchase_plan_qty": to_float(row.get("purchase_plan_qty")),
        "purchase_order_flag": to_int(row.get("purchase_order_flag")),
        "supplier_shipped_flag": to_int(row.get("supplier_shipped_flag")),
        "purchase_inbound_qty": to_float(row.get("purchase_inbound_qty")),
        "local_received_flag": to_int(row.get("local_received_flag")),
        "local_received_qty": to_float(row.get("local_received_qty")),
        "qc_flag": to_int(row.get("qc_flag")),
        "qc_passed_flag": to_int(row.get("qc_passed_flag")),
        "qc_good_qty": to_float(row.get("qc_good_qty")),
        "qc_bad_qty": to_float(row.get("qc_bad_qty")),
        "fba_plan_flag": to_int(row.get("fba_plan_flag")),
        "fba_plan_count": to_int(row.get("fba_plan_count")),
        "fba_plan_qty": to_float(row.get("fba_plan_qty")),
        "historical_fba_plan_count": to_int(row.get("historical_fba_plan_count")),
        "historical_fba_plan_qty": to_float(row.get("historical_fba_plan_qty")),
        "fba_shipped_flag": to_int(row.get("fba_shipped_flag")),
        "fba_shipped_qty": to_float(row.get("fba_shipped_qty")),
        "fba_receiving_flag": to_int(row.get("fba_receiving_flag")),
        "fba_received_qty": to_float(row.get("fba_received_qty")),
        "fba_closed_flag": to_int(row.get("fba_closed_flag")),
        "current_node": current_node,
        "breakpoint_node": breakpoint_node,
        "breakpoint_reason": breakpoint_reason,
        "order_sn_summary": row.get("order_sn_summary") or "",
        "latest_status": row.get("latest_status") or "",
    }


class ReplenishmentTrackingSummaryService:
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
        cutoff_date: str = "",
        entry_batch_days: int | str | None = 30,
        level: str = "all",
        purchase_status: str = "all",
        fba_status: str = "all",
        summary_stage: str = "all",
        category_period_days: int | str | None = 30,
        history_level: str = "all",
        product_category: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        order_keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        safe_page_size = max(10, min(100, int(page_size or 20)))
        safe_page = max(1, int(page or 1))
        with self.connect() as conn:
            selected_date = parse_day(cutoff_date) or self._latest_date(conn)
            if not selected_date:
                return self._empty_payload(safe_page, safe_page_size)
            safe_category_period = self._normalize_category_period(category_period_days)
            category_column = PRODUCT_CATEGORY_COLUMNS[safe_category_period]
            filters, params = self._where(selected_date, entry_batch_days, level, purchase_status, fba_status, summary_stage, history_level, product_category, site, store, keyword, category_column, order_keyword)
            summary = self._summary(conn, filters, params)
            level_flow = self._level_flow(conn, filters, params, category_column)
            total = self._total(conn, filters, params)
            total_pages = max(1, math.ceil(total / safe_page_size))
            safe_page = min(safe_page, total_pages)
            items = self._items(conn, filters, params, safe_page, safe_page_size, category_column)
            meta = self._meta(conn)
        return {
            "cutoff_date": format_day(selected_date),
            "category_period_days": safe_category_period,
            "summary": summary,
            "level_flow": level_flow,
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "total_pages": total_pages,
            "meta": meta,
        }

    def get_detail(self, cutoff_date: str = "", site: str = "", store: str = "", msku: str = "") -> dict[str, Any]:
        selected_date = parse_day(cutoff_date)
        if not selected_date or not site or not store or not msku:
            return {"rows": []}
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    self._detail_sql(),
                    {"cutoff_date": selected_date, "site": site, "store": store, "msku": msku},
                )
                rows = cursor.fetchall()
        return {"rows": [self._map_detail_row(row) for row in rows]}

    @staticmethod
    def _sku_parent_sql(expr: str) -> str:
        return f"""
            case
                when replace(coalesce({expr}, ''), '-zu', '') regexp '[0-9][a-z]$'
                    then left(replace(coalesce({expr}, ''), '-zu', ''), char_length(replace(coalesce({expr}, ''), '-zu', '')) - 1)
                else replace(coalesce({expr}, ''), '-zu', '')
            end
        """.strip()

    def _detail_sql(self) -> str:
        s_sku = self._sku_parent_sql("s.sku")
        po_sku = self._sku_parent_sql("po.sku")
        ro_sku = self._sku_parent_sql("ro.sku")
        qo_sku = self._sku_parent_sql("qo.sku")
        fp_sku = self._sku_parent_sql("fp.sku")
        ii_sku = self._sku_parent_sql("ii.sku")
        po2_sku = self._sku_parent_sql("po2.sku")
        ro2_sku = self._sku_parent_sql("ro2.sku")
        qo2_sku = self._sku_parent_sql("qo2.sku")
        return f"""
        select distinct
            'purchase_plan' as source_type,
            '采购计划' as source_type_label,
            'current' as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            pp.status_text as purchase_plan_status,
            pp.quantity_plan as purchase_plan_qty,
            pp.expect_arrive_time as purchase_expect_arrive_time,
            pp.supplier_name,
            pp.purchaser_name,
            null as order_sn,
            null as logistics_provider_name,
            null as logistics_order,
            null as shipment_sn,
            null as plan_create_time,
            null as method_name,
            null as logistics_channel_name,
            0 as shipment_plan_quantity,
            0 as quantity_shipped,
            0 as quantity_received,
            null as shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'purchase_order' as source_type,
            '采购单' as source_type_label,
            case when nullif(po.logistics_provider, '') is not null or nullif(po.logistics_order, '') is not null then 'current' else 'pending' end as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            po.status as purchase_plan_status,
            coalesce(nullif(po.quantity_real, 0), po.quantity_plan, 0) as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            po.order_sn,
            po.logistics_provider as logistics_provider_name,
            po.logistics_order,
            null as shipment_sn,
            po.order_create_time as plan_create_time,
            null as method_name,
            po.logistics_provider as logistics_channel_name,
            0 as shipment_plan_quantity,
            coalesce(nullif(po.quantity_real, 0), po.quantity_plan, 0) as quantity_shipped,
            po.quantity_receive as quantity_received,
            po.order_create_time as shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_replenishment_tracking_summary s
          on s.cutoff_date = h.cutoff_date
         and s.country_category = h.country_category
         and s.seller_name_new = h.seller_name_new
         and s.seller_sku_adj = h.seller_sku_adj
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        join dashboard_tracking_purchase_order_sync po
          on po.plan_sn = pp.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and {po_sku} = {s_sku} collate utf8mb4_unicode_ci
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'receipt_order' as source_type,
            '本地收货单' as source_type_label,
            'current' as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            ro.status as purchase_plan_status,
            coalesce(ro.product_receive_num, 0) as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            ro.order_sn,
            ro.ware_name as logistics_provider_name,
            concat_ws(
                ' / ',
                nullif(ro.ware_name, ''),
                nullif(ro.qc_sn, ''),
                case
                    when ro.quality_examine_status = '2' then '已质检'
                    when nullif(ro.quality_examine_status, '') is not null then concat('质检状态 ', ro.quality_examine_status)
                    else null
                end
            ) as logistics_order,
            null as shipment_sn,
            coalesce(ro.receive_time, ro.order_create_time) as plan_create_time,
            null as method_name,
            ro.ware_name as logistics_channel_name,
            0 as shipment_plan_quantity,
            0 as quantity_shipped,
            coalesce(ro.product_receive_num, 0) as quantity_received,
            coalesce(ro.receive_time, ro.order_create_time) as shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_replenishment_tracking_summary s
          on s.cutoff_date = h.cutoff_date
         and s.country_category = h.country_category
         and s.seller_name_new = h.seller_name_new
         and s.seller_sku_adj = h.seller_sku_adj
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        join dashboard_tracking_purchase_order_sync po
          on po.plan_sn = pp.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and {po_sku} = {s_sku} collate utf8mb4_unicode_ci
        join dashboard_tracking_receipt_order_sync ro
          on ro.business_order_sn = po.order_sn collate utf8mb4_unicode_ci
         and {ro_sku} = {s_sku} collate utf8mb4_unicode_ci
         and coalesce(ro.product_receive_num, 0) > 0
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'qc_order' as source_type,
            '质检单' as source_type_label,
            'current' as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            qo.status as purchase_plan_status,
            coalesce(qo.product_good_num, 0) as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            qo.qc_sn as order_sn,
            qo.qc_type as logistics_provider_name,
            concat_ws(' / ', nullif(qo.qc_rate_pass, ''), concat('不良 ', coalesce(qo.product_bad_num, 0)), nullif(qo.status, '')) as logistics_order,
            null as shipment_sn,
            coalesce(qo.qc_time, qo.order_create_time, qo.receive_time) as plan_create_time,
            null as method_name,
            qo.qc_type as logistics_channel_name,
            0 as shipment_plan_quantity,
            0 as quantity_shipped,
            coalesce(qo.product_good_num, 0) as quantity_received,
            coalesce(qo.qc_time, qo.order_create_time, qo.receive_time) as shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_replenishment_tracking_summary s
          on s.cutoff_date = h.cutoff_date
         and s.country_category = h.country_category
         and s.seller_name_new = h.seller_name_new
         and s.seller_sku_adj = h.seller_sku_adj
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        join dashboard_tracking_purchase_order_sync po
          on po.plan_sn = pp.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and {po_sku} = {s_sku} collate utf8mb4_unicode_ci
        join dashboard_tracking_receipt_order_sync ro
          on ro.business_order_sn = po.order_sn collate utf8mb4_unicode_ci
         and {ro_sku} = {s_sku} collate utf8mb4_unicode_ci
         and coalesce(ro.product_receive_num, 0) > 0
        join dashboard_tracking_qc_order_sync qo
          on qo.delivery_order_sn = ro.order_sn collate utf8mb4_unicode_ci
         and qo.order_sn = ro.business_order_sn collate utf8mb4_unicode_ci
         and {qo_sku} = {ro_sku} collate utf8mb4_unicode_ci
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'fba_shipment' as source_type,
            'FBA出库/在途' as source_type_label,
            '本次链路' as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            case
                when nullif(ish.status_name, '') is not null then ish.status_name
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'SHIPPED' then '已发货'
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'RECEIVING' then '接收中'
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'CLOSED' then '已完成'
                else coalesce(nullif(ii.shipment_status, ''), nullif(ii.status_text, ''))
            end as purchase_plan_status,
            coalesce(ii.quantity_shipped, 0) as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            ii.shipment_id as order_sn,
            ish.logistics_provider_name,
            concat_ws(' / ', nullif(ii.shipment_sn, ''), nullif(ii.status_text, ''), nullif(ish.logistics_status, '')) as logistics_order,
            ii.shipment_sn,
            coalesce(ii.shipment_time, ish.shipment_time, ii.source_create_time) as plan_create_time,
            null as method_name,
            ish.logistics_channel_name,
            ii.shipment_plan_quantity,
            ii.quantity_shipped,
            coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0) as quantity_received,
            coalesce(ii.shipment_time, ish.shipment_time) as shipment_time,
            coalesce(ish.expected_arrival_date, ish.eta_date) as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_replenishment_tracking_summary s
          on s.cutoff_date = h.cutoff_date
         and s.country_category = h.country_category
         and s.seller_name_new = h.seller_name_new
         and s.seller_sku_adj = h.seller_sku_adj
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        join dashboard_tracking_fba_shipment_plan_sync fp
          on fp.plan_create_time >= pp.plan_create_time
         and fp.country_category = s.country_category collate utf8mb4_unicode_ci
         and fp.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and fp.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
         and abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp.quantity_plan, 0)) <= greatest(coalesce(pp.quantity_plan, 0) * 0.2, 5)
        join dashboard_tracking_inbound_item_sync ii
          on ii.shipment_order_sn = fp.order_sn collate utf8mb4_unicode_ci
         and ii.country_category = s.country_category collate utf8mb4_unicode_ci
         and ii.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and ii.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {ii_sku} = {s_sku} collate utf8mb4_unicode_ci
         and nullif(ii.shipment_id, '') is not null
         and ii.shipment_id like 'FBA%%'
        left join dashboard_tracking_inbound_shipment_sync ish
          on ish.shipment_sn = ii.shipment_sn collate utf8mb4_unicode_ci
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'fba_plan' as source_type,
            'FBA发货计划' as source_type_label,
            '本次链路' as link_attribution,
            pp.plan_sn as purchase_plan_sn,
            pp.plan_create_time as purchase_plan_time,
            fp.status_name as purchase_plan_status,
            fp.shipment_plan_quantity as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            fp.order_sn,
            fp.method_name as logistics_provider_name,
            fp.logistics_name as logistics_order,
            null as shipment_sn,
            fp.plan_create_time,
            fp.method_name,
            fp.logistics_name as logistics_channel_name,
            fp.shipment_plan_quantity,
            0 as quantity_shipped,
            fp.quantity_receive as quantity_received,
            fp.shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary_level_history h
        join dashboard_replenishment_tracking_summary s
          on s.cutoff_date = h.cutoff_date
         and s.country_category = h.country_category
         and s.seller_name_new = h.seller_name_new
         and s.seller_sku_adj = h.seller_sku_adj
        join dashboard_tracking_purchase_plan_sync pp
          on find_in_set(pp.plan_sn collate utf8mb4_unicode_ci, h.purchase_plan_sn_list)
        left join dashboard_tracking_purchase_order_sync po
          on po.plan_sn = pp.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and {po_sku} = {s_sku} collate utf8mb4_unicode_ci
        left join dashboard_tracking_receipt_order_sync ro
          on ro.business_order_sn = po.order_sn collate utf8mb4_unicode_ci
         and {ro_sku} = {s_sku} collate utf8mb4_unicode_ci
         and coalesce(ro.product_receive_num, 0) > 0
        left join dashboard_tracking_qc_order_sync qo
          on qo.delivery_order_sn = ro.order_sn collate utf8mb4_unicode_ci
         and qo.order_sn = ro.business_order_sn collate utf8mb4_unicode_ci
         and {qo_sku} = {ro_sku} collate utf8mb4_unicode_ci
         and coalesce(qo.product_good_num, 0) > 0
         and coalesce(qo.product_bad_num, 0) = 0
        join dashboard_tracking_fba_shipment_plan_sync fp
          on fp.plan_create_time >= pp.plan_create_time
         and fp.country_category = s.country_category collate utf8mb4_unicode_ci
         and fp.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and fp.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
         and abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp.quantity_plan, 0)) <= greatest(coalesce(pp.quantity_plan, 0) * 0.2, 5)
        where h.cutoff_date = %(cutoff_date)s
          and h.country_category = %(site)s
          and h.seller_name_new = %(store)s
          and h.seller_sku_adj = %(msku)s
        union all
        select distinct
            'fba_plan' as source_type,
            'FBA发货计划' as source_type_label,
            '历史/待确认' as link_attribution,
            null as purchase_plan_sn,
            fp.plan_create_time as purchase_plan_time,
            fp.status_name as purchase_plan_status,
            fp.shipment_plan_quantity as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            fp.order_sn,
            fp.method_name as logistics_provider_name,
            fp.logistics_name as logistics_order,
            null as shipment_sn,
            fp.plan_create_time,
            fp.method_name,
            fp.logistics_name as logistics_channel_name,
            fp.shipment_plan_quantity,
            0 as quantity_shipped,
            fp.quantity_receive as quantity_received,
            fp.shipment_time,
            null as expected_arrival_date
        from dashboard_replenishment_tracking_summary s
        join dashboard_tracking_fba_shipment_plan_sync fp
          on fp.plan_create_time >= s.first_replenishment_date
         and fp.plan_create_time < date_add(date_add(s.first_replenishment_date, interval 30 day), interval 1 day)
         and fp.country_category = s.country_category collate utf8mb4_unicode_ci
         and fp.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and fp.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
        where s.cutoff_date = %(cutoff_date)s
          and s.country_category = %(site)s
          and s.seller_name_new = %(store)s
          and s.seller_sku_adj = %(msku)s
          and not exists (
              select 1
              from dashboard_replenishment_tracking_summary_level_history h2
              join dashboard_tracking_purchase_plan_sync pp2
                on find_in_set(pp2.plan_sn collate utf8mb4_unicode_ci, h2.purchase_plan_sn_list)
              left join dashboard_tracking_purchase_order_sync po2
                on po2.plan_sn = pp2.plan_sn collate utf8mb4_unicode_ci
               and po2.status <> '作废'
               and {po2_sku} = {s_sku} collate utf8mb4_unicode_ci
              left join dashboard_tracking_receipt_order_sync ro2
                on ro2.business_order_sn = po2.order_sn collate utf8mb4_unicode_ci
               and {ro2_sku} = {s_sku} collate utf8mb4_unicode_ci
               and coalesce(ro2.product_receive_num, 0) > 0
              left join dashboard_tracking_qc_order_sync qo2
                on qo2.delivery_order_sn = ro2.order_sn collate utf8mb4_unicode_ci
               and qo2.order_sn = ro2.business_order_sn collate utf8mb4_unicode_ci
               and {qo2_sku} = {ro2_sku} collate utf8mb4_unicode_ci
               and coalesce(qo2.product_good_num, 0) > 0
               and coalesce(qo2.product_bad_num, 0) = 0
              where h2.cutoff_date = s.cutoff_date
                and h2.country_category = s.country_category
                and h2.seller_name_new = s.seller_name_new
                and h2.seller_sku_adj = s.seller_sku_adj
                and fp.plan_create_time >= pp2.plan_create_time
                and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
                and abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp2.quantity_plan, 0)) <= greatest(coalesce(pp2.quantity_plan, 0) * 0.2, 5)
          )
        union all
        select distinct
            'fba_shipment' as source_type,
            'FBA出库/在途' as source_type_label,
            '历史/待确认' as link_attribution,
            null as purchase_plan_sn,
            fp.plan_create_time as purchase_plan_time,
            case
                when nullif(ish.status_name, '') is not null then ish.status_name
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'SHIPPED' then '已发货'
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'RECEIVING' then '接收中'
                when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'CLOSED' then '已完成'
                else coalesce(nullif(ii.shipment_status, ''), nullif(ii.status_text, ''))
            end as purchase_plan_status,
            coalesce(ii.quantity_shipped, 0) as purchase_plan_qty,
            null as purchase_expect_arrive_time,
            null as supplier_name,
            null as purchaser_name,
            fp.order_sn,
            ish.logistics_provider_name,
            concat_ws(' / ', nullif(ii.shipment_id, ''), nullif(ii.shipment_sn, ''), nullif(ii.status_text, ''), nullif(ish.logistics_status, '')) as logistics_order,
            ii.shipment_sn,
            coalesce(ii.shipment_time, ish.shipment_time, ii.source_create_time) as plan_create_time,
            null as method_name,
            ish.logistics_channel_name,
            ii.shipment_plan_quantity,
            ii.quantity_shipped,
            coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0) as quantity_received,
            coalesce(ii.shipment_time, ish.shipment_time) as shipment_time,
            coalesce(ish.expected_arrival_date, ish.eta_date) as expected_arrival_date
        from dashboard_replenishment_tracking_summary s
        join dashboard_tracking_fba_shipment_plan_sync fp
          on fp.plan_create_time >= s.first_replenishment_date
         and fp.plan_create_time < date_add(date_add(s.first_replenishment_date, interval 30 day), interval 1 day)
         and fp.country_category = s.country_category collate utf8mb4_unicode_ci
         and fp.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and fp.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
        join dashboard_tracking_inbound_item_sync ii
          on ii.shipment_order_sn = fp.order_sn collate utf8mb4_unicode_ci
         and ii.country_category = s.country_category collate utf8mb4_unicode_ci
         and ii.seller_name_norm = s.seller_name_new collate utf8mb4_unicode_ci
         and ii.msku = s.seller_sku_adj collate utf8mb4_unicode_ci
         and {ii_sku} = {s_sku} collate utf8mb4_unicode_ci
         and nullif(ii.shipment_id, '') is not null
         and ii.shipment_id like 'FBA%%'
        left join dashboard_tracking_inbound_shipment_sync ish
          on ish.shipment_sn = ii.shipment_sn collate utf8mb4_unicode_ci
        where s.cutoff_date = %(cutoff_date)s
          and s.country_category = %(site)s
          and s.seller_name_new = %(store)s
          and s.seller_sku_adj = %(msku)s
          and not exists (
              select 1
              from dashboard_replenishment_tracking_summary_level_history h2
              join dashboard_tracking_purchase_plan_sync pp2
                on find_in_set(pp2.plan_sn collate utf8mb4_unicode_ci, h2.purchase_plan_sn_list)
              left join dashboard_tracking_purchase_order_sync po2
                on po2.plan_sn = pp2.plan_sn collate utf8mb4_unicode_ci
               and po2.status <> '作废'
               and {po2_sku} = {s_sku} collate utf8mb4_unicode_ci
              left join dashboard_tracking_receipt_order_sync ro2
                on ro2.business_order_sn = po2.order_sn collate utf8mb4_unicode_ci
               and {ro2_sku} = {s_sku} collate utf8mb4_unicode_ci
               and coalesce(ro2.product_receive_num, 0) > 0
              left join dashboard_tracking_qc_order_sync qo2
                on qo2.delivery_order_sn = ro2.order_sn collate utf8mb4_unicode_ci
               and qo2.order_sn = ro2.business_order_sn collate utf8mb4_unicode_ci
               and {qo2_sku} = {ro2_sku} collate utf8mb4_unicode_ci
               and coalesce(qo2.product_good_num, 0) > 0
               and coalesce(qo2.product_bad_num, 0) = 0
              where h2.cutoff_date = s.cutoff_date
                and h2.country_category = s.country_category
                and h2.seller_name_new = s.seller_name_new
                and h2.seller_sku_adj = s.seller_sku_adj
                and fp.plan_create_time >= pp2.plan_create_time
                and {fp_sku} = {s_sku} collate utf8mb4_unicode_ci
                and abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp2.quantity_plan, 0)) <= greatest(coalesce(pp2.quantity_plan, 0) * 0.2, 5)
          )
        order by purchase_plan_time desc, plan_create_time desc
        limit 200
        """

    def _map_detail_row(self, row: dict[str, Any]) -> dict[str, Any]:
        mapped = dict(row)
        for key in ("purchase_plan_time", "purchase_expect_arrive_time", "plan_create_time", "shipment_time", "expected_arrival_date"):
            mapped[key] = format_datetime(row.get(key))
        mapped["shipment_time_display"] = mapped.get("shipment_time") or ""
        return mapped

    def _latest_date(self, conn) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute("select max(cutoff_date) as cutoff_date from dashboard_replenishment_tracking_summary")
            row = cursor.fetchone() or {}
        return row.get("cutoff_date")

    def _empty_payload(self, page: int, page_size: int) -> dict[str, Any]:
        return {"summary": {}, "level_flow": [], "items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 1, "meta": {}}

    def _normalize_category_period(self, value: int | str | None) -> int:
        try:
            period = int(value or 30)
        except (TypeError, ValueError):
            period = 30
        return period if period in PRODUCT_CATEGORY_PERIODS else 30

    def _where(self, cutoff_date, entry_batch_days, level, purchase_status, fba_status, summary_stage, history_level, product_category, site, store, keyword, category_column, order_keyword=""):
        clauses = ["s.cutoff_date = %(cutoff_date)s"]
        params: dict[str, Any] = {"cutoff_date": cutoff_date}
        try:
            batch_days = int(entry_batch_days or 30)
        except (TypeError, ValueError):
            batch_days = 30
        if batch_days > 0:
            clauses.append("s.first_replenishment_date >= date_sub(%(cutoff_date)s, interval %(batch_days)s day)")
            params["batch_days"] = batch_days - 1
        if level and level != "all":
            clauses.append("s.current_replenishment_level = %(level)s")
            params["level"] = level
        if purchase_status and purchase_status != "all":
            clauses.append("s.purchase_status = %(purchase_status)s")
            params["purchase_status"] = purchase_status
        if fba_status and fba_status != "all":
            clauses.append("s.fba_status = %(fba_status)s")
            params["fba_status"] = fba_status
        if summary_stage == "purchased":
            clauses.append("s.purchase_status <> 'none'")
        elif summary_stage == "unpurchased":
            clauses.append("s.purchase_status = 'none'")
        elif summary_stage == "purchased_no_fba":
            clauses.append("s.purchase_status <> 'none' and s.fba_status = 'none'")
        elif summary_stage == "fba_inbound":
            clauses.append("s.fba_status <> 'none'")
        elif summary_stage == "current_fba":
            clauses.append("s.fba_status in ('current', 'mixed')")
        elif summary_stage == "historical_fba":
            clauses.append("s.fba_status in ('historical', 'mixed')")
        elif summary_stage == "historical_fba_shipment":
            clauses.append("coalesce(s.historical_fba_inbound_qty, 0) > 0")
        elif summary_stage == "received":
            clauses.append("s.received_qty > 0")
        elif summary_stage == "eta_7d":
            clauses.append("s.nearest_fba_eta_days between 0 and 7")
        elif summary_stage == "eta_overdue":
            clauses.append("s.nearest_fba_eta_days < 0")
        elif summary_stage == "no_purchase_plan":
            if history_level and history_level != "all":
                clauses.append("""
                    exists (
                        select 1
                        from dashboard_replenishment_tracking_summary_level_history h
                        where h.cutoff_date = s.cutoff_date
                          and h.country_category = s.country_category
                          and h.seller_name_new = s.seller_name_new
                          and h.seller_sku_adj = s.seller_sku_adj
                          and h.historical_replenishment_level = %(history_level)s
                          and h.purchase_plan_flag = 0
                    )
                """)
                params["history_level"] = history_level
            else:
                clauses.append("s.purchase_plan_flag = 0")
        elif summary_stage == "purchase_plan_done":
            if history_level and history_level != "all":
                clauses.append("""
                    exists (
                        select 1
                        from dashboard_replenishment_tracking_summary_level_history h
                        where h.cutoff_date = s.cutoff_date
                          and h.country_category = s.country_category
                          and h.seller_name_new = s.seller_name_new
                          and h.seller_sku_adj = s.seller_sku_adj
                          and h.historical_replenishment_level = %(history_level)s
                          and h.purchase_plan_flag = 1
                    )
                """)
                params["history_level"] = history_level
            else:
                clauses.append("s.purchase_plan_flag = 1")
        elif summary_stage == "supplier_not_shipped":
            if history_level and history_level != "all":
                clauses.append("""
                    exists (
                        select 1
                        from dashboard_replenishment_tracking_summary_level_history h
                        where h.cutoff_date = s.cutoff_date
                          and h.country_category = s.country_category
                          and h.seller_name_new = s.seller_name_new
                          and h.seller_sku_adj = s.seller_sku_adj
                          and h.historical_replenishment_level = %(history_level)s
                          and h.purchase_plan_flag = 1
                          and h.supplier_shipped_flag = 0
                    )
                """)
                params["history_level"] = history_level
            else:
                clauses.append("s.purchase_plan_flag = 1 and s.supplier_shipped_flag = 0")
        elif summary_stage == "supplier_shipped_done":
            if history_level and history_level != "all":
                clauses.append("""
                    exists (
                        select 1
                        from dashboard_replenishment_tracking_summary_level_history h
                        where h.cutoff_date = s.cutoff_date
                          and h.country_category = s.country_category
                          and h.seller_name_new = s.seller_name_new
                          and h.seller_sku_adj = s.seller_sku_adj
                          and h.historical_replenishment_level = %(history_level)s
                          and h.supplier_shipped_flag = 1
                    )
                """)
                params["history_level"] = history_level
            else:
                clauses.append("s.supplier_shipped_flag = 1")
        elif summary_stage == "inbound_not_received":
            clauses.append("s.supplier_shipped_flag = 1 and s.local_received_flag = 0")
        elif summary_stage == "local_received_done":
            clauses.append("s.local_received_flag = 1")
        elif summary_stage == "qc_pending":
            clauses.append("s.local_received_flag = 1 and s.qc_passed_flag = 0")
        elif summary_stage == "qc_passed_done":
            clauses.append("s.qc_passed_flag = 1")
        elif summary_stage == "no_fba_plan":
            clauses.append("s.qc_passed_flag = 1 and s.fba_plan_flag = 0")
        elif summary_stage == "fba_plan_done":
            clauses.append("s.fba_plan_flag = 1")
        elif summary_stage == "fba_not_shipped":
            clauses.append("s.fba_plan_flag = 1 and s.fba_shipped_flag = 0")
        elif summary_stage == "fba_shipped_done":
            clauses.append("s.fba_shipped_flag = 1")
        elif summary_stage == "fba_not_receiving":
            clauses.append("s.fba_shipped_flag = 1 and s.fba_receiving_flag = 0")
        elif summary_stage == "fba_receiving_done":
            clauses.append("s.fba_receiving_flag = 1")
        elif summary_stage == "fba_closed":
            clauses.append("s.fba_closed_flag = 1")
        if history_level and history_level != "all":
            clauses.append("exists (select 1 from dashboard_replenishment_tracking_summary_level_history h where h.cutoff_date = s.cutoff_date and h.country_category = s.country_category and h.seller_name_new = s.seller_name_new and h.seller_sku_adj = s.seller_sku_adj and h.historical_replenishment_level = %(history_level)s)")
            params["history_level"] = history_level
        if product_category and product_category != "all":
            clauses.append(f"coalesce(s.{category_column}, s.product_category, '未分类') = %(product_category)s")
            params["product_category"] = product_category
        if site and site != "all":
            clauses.append("s.country_category = %(site)s")
            params["site"] = site
        if store and store != "all":
            clauses.append("s.seller_name_new = %(store)s")
            params["store"] = store
        if keyword:
            clauses.append("(s.seller_sku_adj like %(keyword)s or s.seller_name_new like %(keyword)s or coalesce(s.sku, '') like %(keyword)s)")
            params["keyword"] = f"%{keyword.strip()}%"
        if order_keyword:
            clauses.append("coalesce(s.order_sn_summary, '') like %(order_keyword)s")
            params["order_keyword"] = f"%{order_keyword.strip()}%"
        return " and ".join(clauses), params

    def _summary(self, conn, filters, params):
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(*) as msku_count,
                    sum(case when purchase_status = 'none' then 1 else 0 end) as unpurchased_count,
                    sum(case when purchase_status <> 'none' and fba_status = 'none' then 1 else 0 end) as purchased_no_fba_count,
                    sum(case when fba_status <> 'none' then 1 else 0 end) as fba_inbound_count,
                    sum(case when nearest_fba_eta_days between 0 and 7 then 1 else 0 end) as eta_7d_count,
                    sum(case when nearest_fba_eta_days < 0 then 1 else 0 end) as eta_overdue_count,
                    sum(case when purchase_plan_flag = 0 then 1 else 0 end) as no_purchase_plan_count,
                    sum(case when purchase_plan_flag = 1 and supplier_shipped_flag = 0 then 1 else 0 end) as supplier_not_shipped_count,
                    sum(case when supplier_shipped_flag = 1 and local_received_flag = 0 then 1 else 0 end) as inbound_not_received_count,
                    sum(case when local_received_flag = 1 and qc_passed_flag = 0 then 1 else 0 end) as qc_pending_count,
                    sum(case when qc_passed_flag = 1 and fba_plan_flag = 0 then 1 else 0 end) as no_fba_plan_count,
                    sum(case when fba_plan_flag = 1 and fba_shipped_flag = 0 then 1 else 0 end) as fba_not_shipped_count,
                    sum(case when fba_shipped_flag = 1 and fba_receiving_flag = 0 then 1 else 0 end) as fba_not_receiving_count,
                    sum(case when fba_closed_flag = 1 then 1 else 0 end) as fba_closed_count,
                    sum(case when coalesce(historical_fba_inbound_qty, 0) > 0 then 1 else 0 end) as historical_fba_shipment_count,
                    sum(coalesce(historical_fba_inbound_qty, 0)) as historical_fba_shipment_qty
                from dashboard_replenishment_tracking_summary s
                where {filters}
                """,
                params,
            )
            row = cursor.fetchone() or {}
        return {key: to_int(value) for key, value in row.items()}

    def _level_flow(self, conn, filters, params, category_column):
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    h.historical_replenishment_level as level,
                    count(*) as msku_count,
                    sum(case when h.is_current_level = 1 then 1 else 0 end) as current_count,
                    sum(case
                        when d.cur_date = s.cutoff_date
                         and d.support_replenish_level = h.historical_replenishment_level collate utf8mb4_0900_ai_ci
                         and not (
                            coalesce(d.asin_merge_flag, 0) = 1
                            and coalesce(d.replenish_qty, 0) = 0
                            and coalesce(d.replenish_block_reason, '') <> '被跟卖点不补货'
                         )
                        then 1 else 0
                    end) as same_day_count,
                    sum(case when h.purchase_plan_flag = 1 then 1 else 0 end) as purchased_count,
                    sum(case when s.purchase_status = 'none' then 1 else 0 end) as unpurchased_count,
                    sum(case when s.purchase_status <> 'none' and s.fba_status <> 'none' then 1 else 0 end) as fba_created_count,
                    sum(case when s.fba_status in ('current', 'mixed') then 1 else 0 end) as current_fba_count,
                    sum(case when s.fba_status in ('historical', 'mixed') then 1 else 0 end) as historical_fba_count,
                    sum(case when s.received_qty > 0 then 1 else 0 end) as received_count,
                    count(*) as demand_count,
                    sum(case when h.purchase_plan_flag = 1 then 1 else 0 end) as purchase_plan_node_count,
                    sum(case when h.supplier_shipped_flag = 1 then 1 else 0 end) as supplier_shipped_count,
                    sum(case when s.local_received_flag = 1 then 1 else 0 end) as local_received_count,
                    sum(case when s.qc_passed_flag = 1 then 1 else 0 end) as qc_passed_count,
                    sum(case when s.fba_plan_flag = 1 then 1 else 0 end) as fba_plan_count,
                    sum(case when s.historical_fba_plan_count > 0 then 1 else 0 end) as historical_fba_plan_count,
                    sum(case when s.fba_shipped_flag = 1 then 1 else 0 end) as fba_shipped_count,
                    sum(case when s.fba_receiving_flag = 1 then 1 else 0 end) as fba_receiving_count,
                    sum(case when s.fba_closed_flag = 1 then 1 else 0 end) as fba_closed_count
                from dashboard_replenishment_tracking_summary s
                join dashboard_replenishment_tracking_summary_level_history h
                  on h.cutoff_date = s.cutoff_date
                 and h.country_category = s.country_category
                 and h.seller_name_new = s.seller_name_new
                 and h.seller_sku_adj = s.seller_sku_adj
                left join dashboard_pur_plan_replenish_data d
                  on d.cur_date = s.cutoff_date
                 and d.country_category = s.country_category collate utf8mb4_0900_ai_ci
                 and d.seller_name_new = s.seller_name_new collate utf8mb4_0900_ai_ci
                 and d.seller_sku_adj = s.seller_sku_adj collate utf8mb4_0900_ai_ci
                where {filters}
                group by h.historical_replenishment_level
                order by
                    case h.historical_replenishment_level
                        when '紧急补货' then 1
                        when '建议补货' then 2
                        when '计划补货' then 3
                        else 9
                    end
                """,
                params,
            )
            rows = cursor.fetchall()
        result = [{key: (to_int(value) if key.endswith("_count") else value) for key, value in row.items()} for row in rows]
        category_mix = self._level_category_mix(conn, filters, params, category_column)
        for row in result:
            row["category_mix"] = category_mix.get(row["level"], [])
        return result

    def _level_category_mix(self, conn, filters, params, category_column):
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    h.historical_replenishment_level as level,
                    coalesce(s.{category_column}, s.product_category, '未分类') as category,
                    count(*) as msku_count
                from dashboard_replenishment_tracking_summary s
                join dashboard_replenishment_tracking_summary_level_history h
                  on h.cutoff_date = s.cutoff_date
                 and h.country_category = s.country_category
                 and h.seller_name_new = s.seller_name_new
                 and h.seller_sku_adj = s.seller_sku_adj
                where {filters}
                group by h.historical_replenishment_level, coalesce(s.{category_column}, s.product_category, '未分类')
                order by
                    case h.historical_replenishment_level
                        when '紧急补货' then 1
                        when '建议补货' then 2
                        when '计划补货' then 3
                        else 9
                    end,
                    count(*) desc
                """,
                params,
            )
            rows = cursor.fetchall()
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["level"], []).append({
                "category": row.get("category") or "未分类",
                "msku_count": to_int(row.get("msku_count")),
            })
        return result

    def _total(self, conn, filters, params) -> int:
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) as total from dashboard_replenishment_tracking_summary s where {filters}", params)
            row = cursor.fetchone() or {}
        return to_int(row.get("total"))

    def _items(self, conn, filters, params, page, page_size, category_column):
        offset = (page - 1) * page_size
        query_params = dict(params, limit=page_size, offset=offset)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select s.*, coalesce(s.{category_column}, s.product_category, '未分类') as selected_product_category
                from dashboard_replenishment_tracking_summary s
                where {filters}
                order by current_replenishment_level_sort, appearance_days desc, latest_replenishment_qty desc, seller_sku_adj
                limit %(limit)s offset %(offset)s
                """,
                query_params,
            )
            rows = cursor.fetchall()
        return [map_summary_row(row) for row in rows]

    def _meta(self, conn):
        with conn.cursor() as cursor:
            cursor.execute("select distinct cutoff_date from dashboard_replenishment_tracking_summary order by cutoff_date desc limit 30")
            dates = [format_day(row.get("cutoff_date")) for row in cursor.fetchall()]
            cursor.execute("select distinct country_category from dashboard_replenishment_tracking_summary where country_category is not null and country_category <> '' order by country_category")
            sites = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute("select distinct seller_name_new from dashboard_replenishment_tracking_summary where seller_name_new is not null and seller_name_new <> '' order by seller_name_new limit 500")
            stores = [row["seller_name_new"] for row in cursor.fetchall()]
        return {"dates": dates, "sites": sites, "stores": stores}


replenishment_tracking_summary_service = ReplenishmentTrackingSummaryService()
