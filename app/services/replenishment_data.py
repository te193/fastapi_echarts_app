from __future__ import annotations

import math
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql

from etl.replenishment_update import apply_database_ini_env


LEVEL_ALL = "\u5168\u90e8"
LEVEL_URGENT = "\u7d27\u6025\u8865\u8d27"
LEVEL_SUGGESTED = "\u5efa\u8bae\u8865\u8d27"
LEVEL_PLANNED = "\u8ba1\u5212\u8865\u8d27"
LEVEL_SUFFICIENT = "\u5e93\u5b58\u5145\u8db3"
LEVEL_ZERO_SALES = "\u65e5\u9500\u4e3a0"
LEVEL_UNKNOWN = "\u672a\u5206\u5c42"

REPLENISHMENT_COLUMN_LABELS = {
    "cur_date": "补货日期",
    "new_old_product": "新老品",
    "seller_sku_adj": "MSKU",
    "max_fnsku": "FNSKU",
    "max_asin": "ASIN",
    "max_sku": "SKU",
    "marketplace_status": "平台状态",
    "seller_name_concat": "店铺汇总",
    "onsale_sites": "在售站点",
    "unsale_sites": "停售站点",
    "sales_status": "销售状态",
    "marketplace_concat": "市场汇总",
    "seller_name_copy": "店铺名称原值",
    "seller_name_ue": "店铺名称UE",
    "seller_name_new": "店铺",
    "country_category": "站点",
    "max_local_name": "本地品名",
    "max_brand_name": "品牌",
    "principal": "负责人",
    "sales_team_1": "销售团队",
    "max_receiving_time": "最近接收时间",
    "receiving_cnt": "接收次数",
    "max_cg_box_pcs": "采购箱规",
    "max_cg_price": "采购价",
    "max_cg_transport_costs": "采购运输成本",
    "stockout_status": "缺货状态",
    "pre_daily_avg_sales": "预处理日销",
    "pre_normal_replenish_need_qty": "预处理正常补货需求量",
    "pre_replenish_trigger_qty": "预处理补货触发量",
    "hist_90d_instock_days": "历史90天有货天数",
    "hist_90d_instock_sales": "历史90天有货销量",
    "hist_90d_instock_daily_sales": "历史90天有货日销",
    "history_recovery_need_qty": "历史恢复需求量",
    "history_recovery_flag": "历史恢复标记",
    "support_inventory_qty": "支撑库存数量",
    "inventory_support_days": "库存支撑天数",
    "support_replenish_level": "补货层级",
    "support_replenish_level_sort": "补货层级排序",
    "abcd_category": "产品分类",
    "gp_margin_range": "毛利率区间",
    "predict_abcd_category": "预测ABCD分类",
    "pre_1m_predict_abcd_category": "前1月预测ABCD分类",
    "pre_1q_predict_abcd_category": "前1季预测ABCD分类",
    "fba_local_quantity": "FBA本地库存",
    "total": "总库存",
    "available_total": "可用库存",
    "afn_fulfillable_quantity": "FBA可售库存",
    "stock_up_num": "在途数量",
    "afn_unsellable_quantity": "FBA不可售库存",
    "sc_quantity_local_valid": "本地可用库存",
    "sc_quantity_purchase_shipping": "采购在途数量",
    "sc_quantity_purchase_plan": "采购计划数量",
    "sc_quantity_local_qc": "本地质检数量",
    "local_quantity": "本地库存",
    "r_90d_salable_days": "90天可售天数",
    "r_30d_salable_days": "30天可售天数",
    "r_14d_salable_days": "14天可售天数",
    "r_7d_salable_days": "7天可售天数",
    "r_3d_salable_days": "3天可售天数",
    "sales_90d": "90天销量",
    "final_sales_30d": "30天销量",
    "final_sales_14d": "14天销量",
    "final_sales_7d": "7天销量",
    "final_sales_3d": "3天销量",
    "amount_30d": "30天销售额",
    "amount_14d": "14天销售额",
    "amount_7d": "7天销售额",
    "amount_3d": "3天销售额",
    "pprofit_30d": "30天利润",
    "pprofit_14d": "14天利润",
    "pprofit_7d": "7天利润",
    "pprofit_3d": "3天利润",
    "pprofit_ratio_30d": "30天利润率",
    "pprofit_ratio_14d": "14天利润率",
    "pprofit_ratio_7d": "7天利润率",
    "pprofit_ratio_3d": "3天利润率",
    "gamount_30d": "30天GMV",
    "gamount_14d": "14天GMV",
    "gamount_7d": "7天GMV",
    "gamount_3d": "3天GMV",
    "gprofit_30d": "30天毛利",
    "gprofit_14d": "14天毛利",
    "gprofit_7d": "7天毛利",
    "gprofit_3d": "3天毛利",
    "gprofit_ratio_30d": "30天毛利率",
    "gprofit_ratio_14d": "14天毛利率",
    "gprofit_ratio_7d": "7天毛利率",
    "gprofit_ratio_3d": "3天毛利率",
    "new_old_prod_jg": "新老品判断",
    "daily_avg_sales": "日销",
    "replenish_comp_months": "补货覆盖月数",
    "salable_days": "可售天数",
    "60d_stocko_qty": "60天断货数量",
    "90d_stocko_qty": "90天断货数量",
    "180d_stocko_qty": "180天断货数量",
    "replenish_dur_calc_stocko_qty": "补货周期断货计算量",
    "replenish_need_qty": "补货需求量",
    "replenish_trigger_qty": "补货触发量",
    "sales_change_rate_adj": "销量变化率调整",
    "sales_adj_factor": "销量调整系数",
    "final_profit_rate": "最终利润率",
    "replenish_qty": "补货数量",
    "replenish_box_qty": "补货箱数",
    "replenish_cost": "补货货值",
    "amz_instock_sales_ratio": "亚马逊有货销售占比",
    "instock_intrans_pur_sales_ratio": "有货在途采购销售占比",
    "fllow_flag": "跟进标记",
    "created_at": "创建时间",
    "updated_at": "更新时间",
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


class ReplenishmentDataService:
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
        level: str = "all",
        category: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        sort_field: str = "",
        sort_dir: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date:
                return self._empty_payload(page, page_size)
            filters, params = self._build_where(selected_date, level, category, site, store, keyword)
            summary = self._summary(conn, filters, params)
            level_summary = self._level_summary(conn, filters, params)
            items, total = self._items(conn, filters, params, sort_field, sort_dir, page, page_size)
            meta = self._meta(conn)

        safe_page_size = max(10, min(100, int(page_size or 20)))
        total_pages = max(1, math.ceil(total / safe_page_size))
        safe_page = min(max(1, int(page or 1)), total_pages)
        return {
            "snapshot_date": format_day(selected_date),
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

    def get_export_items(
        self,
        snapshot_date: str = "",
        level: str = "all",
        category: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        sort_field: str = "",
        sort_dir: str = "",
    ) -> list[dict[str, Any]]:
        return self.get_export_payload(
            snapshot_date=snapshot_date,
            level=level,
            category=category,
            site=site,
            store=store,
            keyword=keyword,
            sort_field=sort_field,
            sort_dir=sort_dir,
        )["rows"]

    def get_export_payload(
        self,
        snapshot_date: str = "",
        level: str = "all",
        category: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        sort_field: str = "",
        sort_dir: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date:
                return {"columns": [], "rows": [], "snapshot_date": None}
            filters, params = self._build_where(selected_date, level, category, site, store, keyword)
            columns = self._export_columns(conn)
            rows = self._export_items(conn, filters, params, sort_field, sort_dir, [col["name"] for col in columns])
            return {"columns": columns, "rows": rows, "snapshot_date": format_day(selected_date)}

    def _latest_date(self, conn) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute("select max(cur_date) as cur_date from dashboard_pur_plan_replenish_data")
            row = cursor.fetchone() or {}
        return row.get("cur_date")

    def _meta(self, conn) -> dict[str, Any]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select cur_date
                from dashboard_pur_plan_replenish_data
                group by cur_date
                order by cur_date desc
                limit 30
                """
            )
            dates = [format_day(row.get("cur_date")) for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct country_category
                from dashboard_pur_plan_replenish_data
                where country_category is not null and country_category <> ''
                order by country_category
                """
            )
            sites = [row["country_category"] for row in cursor.fetchall()]
            cursor.execute(
                """
                select distinct seller_name_new
                from dashboard_pur_plan_replenish_data
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
                {"key": LEVEL_URGENT, "label": LEVEL_URGENT},
                {"key": LEVEL_SUGGESTED, "label": LEVEL_SUGGESTED},
                {"key": LEVEL_PLANNED, "label": LEVEL_PLANNED},
                {"key": LEVEL_SUFFICIENT, "label": LEVEL_SUFFICIENT},
                {"key": LEVEL_ZERO_SALES, "label": LEVEL_ZERO_SALES},
            ],
        }

    def _build_where(
        self,
        snapshot_date: date,
        level: str,
        category: str,
        site: str,
        store: str,
        keyword: str,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["cur_date = %(snapshot_date)s"]
        params: dict[str, Any] = {"snapshot_date": snapshot_date}
        if level and level != "all":
            clauses.append("support_replenish_level = %(level)s")
            params["level"] = level
        if category and category != "all":
            clauses.append("coalesce(abcd_category, '未分类') = %(category)s")
            params["category"] = category
        if site and site != "all":
            clauses.append("country_category = %(site)s")
            params["site"] = site
        if store and store != "all":
            clauses.append("seller_name_new = %(store)s")
            params["store"] = store
        if keyword:
            clauses.append(
                "(seller_sku_adj like %(keyword)s or seller_name_new like %(keyword)s "
                "or country_category like %(keyword)s or coalesce(max_sku, '') like %(keyword)s)"
            )
            params["keyword"] = f"%{keyword.strip()}%"
        return " and ".join(clauses), params

    def _summary(self, conn, filters: str, params: dict[str, Any]) -> dict[str, Any]:
        query_params = {
            **params,
            "level_urgent": LEVEL_URGENT,
            "level_suggested": LEVEL_SUGGESTED,
            "level_planned": LEVEL_PLANNED,
            "level_sufficient": LEVEL_SUFFICIENT,
            "level_zero_sales": LEVEL_ZERO_SALES,
        }
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(*) as sku_count,
                    count(*) as all_msku_count,
                    count(*) as detail_row_count,
                    sum(case when support_replenish_level_sort in (1, 2, 3) then 1 else 0 end) as calc_msku_count,
                    sum(coalesce(replenish_qty, 0)) as replenish_qty,
                    sum(coalesce(replenish_box_qty, 0)) as replenish_box_qty,
                    sum(coalesce(replenish_cost, 0)) as replenish_cost,
                    avg(inventory_support_days) as avg_support_days,
                    sum(case when support_replenish_level = %(level_urgent)s then 1 else 0 end) as urgent_count,
                    sum(case when support_replenish_level = %(level_suggested)s then 1 else 0 end) as suggested_count,
                    sum(case when support_replenish_level = %(level_planned)s then 1 else 0 end) as planned_count,
                    sum(case when support_replenish_level = %(level_sufficient)s then 1 else 0 end) as sufficient_count,
                    sum(case when support_replenish_level = %(level_zero_sales)s then 1 else 0 end) as zero_sales_count
                from dashboard_pur_plan_replenish_data
                where {filters}
                """,
                query_params,
            )
            row = cursor.fetchone() or {}
        return {
            "sku_count": to_int(row.get("sku_count")),
            "all_msku_count": to_int(row.get("all_msku_count")),
            "detail_row_count": to_int(row.get("detail_row_count")),
            "calc_msku_count": to_int(row.get("calc_msku_count")),
            "replenish_qty": round(to_float(row.get("replenish_qty")), 2),
            "replenish_box_qty": round(to_float(row.get("replenish_box_qty")), 2),
            "replenish_cost": round(to_float(row.get("replenish_cost")), 2),
            "avg_support_days": round(to_float(row.get("avg_support_days")), 2),
            "urgent_count": to_int(row.get("urgent_count")),
            "suggested_count": to_int(row.get("suggested_count")),
            "planned_count": to_int(row.get("planned_count")),
            "sufficient_count": to_int(row.get("sufficient_count")),
            "zero_sales_count": to_int(row.get("zero_sales_count")),
        }

    def _level_summary(self, conn, filters: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    support_replenish_level_sort,
                    support_replenish_level,
                    count(*) as sku_count,
                    count(*) as all_msku_count,
                    count(*) as detail_row_count,
                    sum(case when support_replenish_level_sort in (1, 2, 3) then 1 else 0 end) as calc_msku_count,
                    sum(coalesce(replenish_qty, 0)) as replenish_qty,
                    sum(coalesce(replenish_cost, 0)) as replenish_cost,
                    avg(inventory_support_days) as avg_support_days
                from dashboard_pur_plan_replenish_data
                where {filters}
                group by support_replenish_level_sort, support_replenish_level
                order by support_replenish_level_sort
                """,
                params,
            )
            rows = cursor.fetchall()
            cursor.execute(
                f"""
                select
                    support_replenish_level_sort,
                    coalesce(abcd_category, '未分类') as abcd_category,
                    count(*) as sku_count
                from dashboard_pur_plan_replenish_data
                where {filters}
                group by support_replenish_level_sort, coalesce(abcd_category, '未分类')
                order by support_replenish_level_sort, sku_count desc, abcd_category
                """,
                params,
            )
            mix_rows = cursor.fetchall()
        category_mix: dict[int, list[dict[str, Any]]] = {}
        for row in mix_rows:
            sort = to_int(row.get("support_replenish_level_sort"))
            category_mix.setdefault(sort, []).append(
                {
                    "category": row.get("abcd_category") or "未分类",
                    "sku_count": to_int(row.get("sku_count")),
                }
            )
        return [
            {
                "sort": to_int(row.get("support_replenish_level_sort")),
                "level": row.get("support_replenish_level") or LEVEL_UNKNOWN,
                "sku_count": to_int(row.get("sku_count")),
                "all_msku_count": to_int(row.get("all_msku_count")),
                "detail_row_count": to_int(row.get("detail_row_count")),
                "calc_msku_count": to_int(row.get("calc_msku_count")),
                "replenish_qty": round(to_float(row.get("replenish_qty")), 2),
                "replenish_cost": round(to_float(row.get("replenish_cost")), 2),
                "avg_support_days": round(to_float(row.get("avg_support_days")), 2),
                "category_mix": category_mix.get(to_int(row.get("support_replenish_level_sort")), []),
            }
            for row in rows
        ]

    def _items(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        sort_field: str,
        sort_dir: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        sort_map = {
            "level": "support_replenish_level_sort",
            "country": "country_category",
            "site": "country_category",
            "store": "seller_name_new",
            "msku": "seller_sku_adj",
            "sku": "max_sku",
            "support_days": "inventory_support_days",
            "daily_sales": "daily_avg_sales",
            "category_daily_sales_30d": "case when r_30d_salable_days > 0 then final_sales_30d / r_30d_salable_days else 0 end",
            "profit_rate_30d": "pprofit_ratio_30d",
            "available_total": "available_total",
            "stock_up_num": "stock_up_num",
            "local_quantity": "local_quantity",
            "replenish_qty": "replenish_qty",
            "replenish_cost": "replenish_cost",
            "cost": "replenish_cost",
            "sales_30d": "final_sales_30d",
            "need_qty": "replenish_need_qty",
            "box_qty": "replenish_box_qty",
            "stockout_status": "stockout_status",
            "category": "abcd_category",
            "margin_range": "gp_margin_range",
        }
        sort_column = sort_map.get(sort_field or "", "support_replenish_level_sort")
        direction = "desc" if str(sort_dir or "").lower() == "desc" else "asc"
        safe_page_size = max(10, min(100, int(page_size or 20)))
        safe_page = max(1, int(page or 1))
        offset = (safe_page - 1) * safe_page_size
        query_params = dict(params)
        query_params.update({"limit": safe_page_size, "offset": offset})
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) as total from dashboard_pur_plan_replenish_data where {filters}", params)
            total = to_int((cursor.fetchone() or {}).get("total"))
            cursor.execute(
                f"""
                select
                    cur_date,
                    support_replenish_level,
                    support_replenish_level_sort,
                    country_category,
                    seller_name_new,
                    seller_sku_adj,
                    max_sku,
                    daily_avg_sales,
                    case when r_30d_salable_days > 0 then final_sales_30d / r_30d_salable_days else 0 end as category_daily_sales_30d,
                    pprofit_ratio_30d,
                    inventory_support_days,
                    support_inventory_qty,
                    available_total,
                    stock_up_num,
                    local_quantity,
                    sc_quantity_purchase_plan,
                    final_sales_30d,
                    replenish_need_qty,
                    replenish_qty,
                    replenish_box_qty,
                    replenish_cost,
                    stockout_status,
                    abcd_category,
                    gp_margin_range
                from dashboard_pur_plan_replenish_data
                where {filters}
                order by {sort_column} {direction}, replenish_qty desc, seller_sku_adj
                limit %(limit)s offset %(offset)s
                """,
                query_params,
            )
            rows = cursor.fetchall()
        return [self._serialize_item(row) for row in rows], total

    def _export_items(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        sort_field: str,
        sort_dir: str,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        sort_map = {
            "level": "support_replenish_level_sort",
            "country": "country_category",
            "site": "country_category",
            "store": "seller_name_new",
            "msku": "seller_sku_adj",
            "sku": "max_sku",
            "support_days": "inventory_support_days",
            "daily_sales": "daily_avg_sales",
            "category_daily_sales_30d": "case when r_30d_salable_days > 0 then final_sales_30d / r_30d_salable_days else 0 end",
            "profit_rate_30d": "pprofit_ratio_30d",
            "available_total": "available_total",
            "stock_up_num": "stock_up_num",
            "local_quantity": "local_quantity",
            "replenish_qty": "replenish_qty",
            "replenish_cost": "replenish_cost",
            "cost": "replenish_cost",
            "sales_30d": "final_sales_30d",
            "need_qty": "replenish_need_qty",
            "box_qty": "replenish_box_qty",
            "stockout_status": "stockout_status",
            "category": "abcd_category",
            "margin_range": "gp_margin_range",
        }
        sort_column = sort_map.get(sort_field or "", "support_replenish_level_sort")
        direction = "desc" if str(sort_dir or "").lower() == "desc" else "asc"
        export_columns = columns or [col["name"] for col in self._export_columns(conn)]
        select_columns = ",\n                    ".join(self._quote_identifier(column) for column in export_columns)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    {select_columns}
                from dashboard_pur_plan_replenish_data
                where {filters}
                order by {sort_column} {direction}, replenish_qty desc, seller_sku_adj
                """,
                params,
            )
            rows = cursor.fetchall()
        return rows

    def _export_columns(self, conn) -> list[dict[str, str]]:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    column_name as column_name,
                    column_comment as column_comment
                from information_schema.columns
                where table_schema = %(database)s
                  and table_name = 'dashboard_pur_plan_replenish_data'
                order by ordinal_position
                """,
                {"database": self.database},
            )
            rows = cursor.fetchall()
        return [
            {
                "name": row.get("column_name"),
                "label": row.get("column_comment") or REPLENISHMENT_COLUMN_LABELS.get(row.get("column_name"), row.get("column_name")),
            }
            for row in rows
            if row.get("column_name")
        ]

    def _quote_identifier(self, value: str) -> str:
        return "`" + value.replace("`", "``") + "`"

    def _serialize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "cur_date": format_day(row.get("cur_date")),
            "level": row.get("support_replenish_level"),
            "level_sort": to_int(row.get("support_replenish_level_sort")),
            "country": row.get("country_category"),
            "store": row.get("seller_name_new"),
            "msku": row.get("seller_sku_adj"),
            "sku": row.get("max_sku"),
            "daily_sales": round(to_float(row.get("daily_avg_sales")), 4),
            "category_daily_sales_30d": round(to_float(row.get("category_daily_sales_30d")), 4),
            "profit_rate_30d": round(to_float(row.get("pprofit_ratio_30d")), 6),
            "support_days": round(to_float(row.get("inventory_support_days")), 2),
            "support_inventory_qty": round(to_float(row.get("support_inventory_qty")), 2),
            "available_total": round(to_float(row.get("available_total")), 2),
            "stock_up_num": round(to_float(row.get("stock_up_num")), 2),
            "local_quantity": round(to_float(row.get("local_quantity")), 2),
            "purchase_plan_quantity": round(to_float(row.get("sc_quantity_purchase_plan")), 2),
            "sales_30d": round(to_float(row.get("final_sales_30d")), 2),
            "need_qty": round(to_float(row.get("replenish_need_qty")), 2),
            "replenish_qty": round(to_float(row.get("replenish_qty")), 2),
            "box_qty": round(to_float(row.get("replenish_box_qty")), 2),
            "cost": round(to_float(row.get("replenish_cost")), 2),
            "stockout_status": row.get("stockout_status"),
            "category": row.get("abcd_category"),
            "margin_range": row.get("gp_margin_range"),
        }

    def _empty_payload(self, page: int, page_size: int) -> dict[str, Any]:
        return {
            "snapshot_date": None,
            "meta": {"dates": [], "sites": [], "stores": [], "levels": []},
            "summary": {},
            "level_summary": [],
            "items": [],
            "total": 0,
            "page": max(1, int(page or 1)),
            "page_size": max(10, min(100, int(page_size or 20))),
            "total_pages": 1,
            "selected_level": "all",
        }


replenishment_service = ReplenishmentDataService()
