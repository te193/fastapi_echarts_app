from __future__ import annotations

import math
import os
import re
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
LEVEL_HISTORY_RECOVERY = "\u5386\u53f2\u515c\u5e95"
LEVEL_FOLLOWED_BLOCK = "\u88ab\u8ddf\u5356\u70b9\u4e0d\u8865\u8d27"
LEVEL_UNKNOWN = "\u672a\u5206\u5c42"
ASIN_MERGE_CONSOLIDATED_BLOCK = "\u540cASIN\u5df2\u5408\u5e76\u81f3\u4e3b\u94fe\u63a5"
ASIN_MERGE_SUFFICIENT_BLOCK = "\u540cASIN\u5e93\u5b58\u5145\u8db3\u4e0d\u8865\u8d27"
COUNTRY_METRIC_PERIODS = {7, 14, 30, 90}
PRODUCT_CATEGORY_PERIODS = {7, 14, 30, 90, 180}
MARGIN_PRICE_TARGETS = (35, 30, 25, 20, 15, 10, 5, 0)
PRODUCT_CATEGORY_SALES_COLUMNS = {
    7: "final_sales_7d",
    14: "final_sales_14d",
    30: "final_sales_30d",
    90: "sales_90d",
    180: "sales_180d",
}
FLOW_NEW = "\u65b0\u589e"
FLOW_IN = "\u6d41\u5165"
FLOW_OUT = "\u6d41\u51fa"
FLOW_EXIT = "\u9000\u51fa"
FLOW_STAY = "\u4fdd\u6301"
FLOW_ALL = "all"
FLOW_ENTRY_LABEL = "\u65e0\u8bb0\u5f55"
REPLENISHMENT_ACTIVE_LEVELS = {LEVEL_URGENT, LEVEL_SUGGESTED, LEVEL_PLANNED}
REPLENISHMENT_PASSIVE_LEVELS = {LEVEL_SUFFICIENT, LEVEL_ZERO_SALES}
FLOW_LEVEL_ORDER = {
    LEVEL_URGENT: 1,
    LEVEL_SUGGESTED: 2,
    LEVEL_PLANNED: 3,
    LEVEL_SUFFICIENT: 4,
    LEVEL_ZERO_SALES: 5,
    LEVEL_HISTORY_RECOVERY: 6,
    LEVEL_UNKNOWN: 7,
    FLOW_ENTRY_LABEL: 99,
}
PRODUCT_CATEGORY_SQL_COLUMNS = set(PRODUCT_CATEGORY_SALES_COLUMNS.values()) | {
    f"r_{period}d_salable_days" for period in PRODUCT_CATEGORY_PERIODS
} | {
    f"pprofit_ratio_{period}d" for period in PRODUCT_CATEGORY_PERIODS
}

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
    "r_180d_salable_days": "180天可售天数",
    "r_90d_salable_days": "90天可售天数",
    "r_30d_salable_days": "30天可售天数",
    "r_14d_salable_days": "14天可售天数",
    "r_7d_salable_days": "7天可售天数",
    "r_3d_salable_days": "3天可售天数",
    "sales_180d": "180天销量",
    "sales_90d": "90天销量",
    "final_sales_30d": "30天销量",
    "final_sales_14d": "14天销量",
    "final_sales_7d": "7天销量",
    "final_sales_3d": "3天销量",
    "amount_180d": "180天销售额",
    "amount_90d": "90天销售额",
    "amount_30d": "30天销售额",
    "amount_14d": "14天销售额",
    "amount_7d": "7天销售额",
    "amount_3d": "3天销售额",
    "pprofit_180d": "180天利润",
    "pprofit_90d": "90天利润",
    "pprofit_30d": "30天利润",
    "pprofit_14d": "14天利润",
    "pprofit_7d": "7天利润",
    "pprofit_3d": "3天利润",
    "pprofit_ratio_180d": "180天利润率",
    "pprofit_ratio_90d": "90天利润率",
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
    "final_profit_rate": "订单原始毛利率",
    "replenish_qty": "补货数量",
    "replenish_box_qty": "补货箱数",
    "replenish_cost": "补货货值",
    "amz_instock_sales_ratio": "亚马逊有货销售占比",
    "instock_intrans_pur_sales_ratio": "有货在途采购销售占比",
    "fllow_flag": "是否跟卖",
    "followed_flag": "是否被跟卖",
    "followed_by_count": "被跟卖方数量",
    "followed_by_links": "被跟卖方",
    "replenish_block_reason": "不补货原因",
    "asin_merge_flag": "是否ASIN合并",
    "asin_merge_target": "ASIN合并目标",
    "asin_merge_reason": "ASIN合并原因",
    "created_at": "创建时间",
    "updated_at": "更新时间",
}

REPLENISHMENT_EXPORT_LABEL_OVERRIDES = {
    "final_profit_rate": "订单原始毛利率",
}

REPLENISHMENT_EXPORT_EXCLUDED_COLUMNS = {
    "stockout_status",
    "gamount_30d",
    "gamount_14d",
    "gamount_7d",
    "gamount_3d",
    "gprofit_30d",
    "gprofit_14d",
    "gprofit_7d",
    "gprofit_3d",
    "gprofit_ratio_30d",
    "gprofit_ratio_14d",
    "gprofit_ratio_7d",
    "gprofit_ratio_3d",
    "pre_1m_predict_abcd_category",
    "pre_1q_predict_abcd_category",
}


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_int(value: Any) -> int:
    return int(round(to_float(value)))


def format_follow_status(value: Any) -> str:
    return "是" if to_int(value) == 0 else "否"


def format_yes_no_status(value: Any) -> str:
    return "是" if to_int(value) == 1 else "否"


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
        category_period_days: int | str | None = 30,
        sort_field: str = "",
        sort_dir: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        safe_category_period_days = self._normalize_product_category_period_days(category_period_days)
        period_metrics = self._product_category_metric_sql(safe_category_period_days)
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date:
                return self._empty_payload(page, page_size)
            filters, params = self._build_where(
                selected_date,
                level,
                category,
                site,
                store,
                keyword,
                category_expr=period_metrics["category_expr"],
            )
            summary = self._summary(conn, filters, params)
            level_summary = self._level_summary(conn, filters, params, period_metrics["category_expr"])
            flow_summary = self._level_flow_summary(
                conn,
                selected_date,
                category,
                site,
                store,
                keyword,
                period_metrics["category_expr"],
            )
            self._attach_level_flow_summary(level_summary, flow_summary)
            items, total = self._items(conn, filters, params, sort_field, sort_dir, page, page_size, period_metrics)
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
            "category_period_days": safe_category_period_days,
            "flow_dates": flow_summary.get("dates", {}),
        }

    def get_level_flow(
        self,
        snapshot_date: str = "",
        level: str = "all",
        flow_type: str = "all",
        category: str = "all",
        site: str = "all",
        store: str = "all",
        keyword: str = "",
        category_period_days: int | str | None = 30,
    ) -> dict[str, Any]:
        safe_category_period_days = self._normalize_product_category_period_days(category_period_days)
        period_metrics = self._product_category_metric_sql(safe_category_period_days)
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date:
                return self._empty_level_flow(None, None)
            prev_date = self._previous_date(conn, selected_date)
            if not prev_date:
                return self._empty_level_flow(None, selected_date)
            rows = self._level_flow_rows(
                conn,
                selected_date,
                prev_date,
                category,
                site,
                store,
                keyword,
                period_metrics["category_expr"],
                level,
                flow_type,
            )
        return self._build_level_flow_payload(
            rows,
            format_day(prev_date),
            format_day(selected_date),
            level,
            flow_type,
            category,
        )

    def get_export_items(
        self,
        snapshot_date: str = "",
        level: str = "all",
        category: str = "all",
        category_period_days: int | str | None = 30,
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
            category_period_days=category_period_days,
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
        category_period_days: int | str | None = 30,
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
            safe_category_period_days = self._normalize_product_category_period_days(category_period_days)
            period_metrics = self._product_category_metric_sql(safe_category_period_days)
            filters, params = self._build_where(
                selected_date,
                level,
                category,
                site,
                store,
                keyword,
                category_expr=period_metrics["category_expr"],
            )
            columns = self._export_columns(conn)
            rows = self._export_items(
                conn,
                filters,
                params,
                sort_field,
                sort_dir,
                [col["name"] for col in columns],
                period_metrics=period_metrics,
            )
            return {"columns": columns, "rows": rows, "snapshot_date": format_day(selected_date)}

    def get_country_metrics(
        self,
        snapshot_date: str = "",
        site: str = "",
        store: str = "",
        msku: str = "",
        period_days: int | str | None = 30,
        sort_field: str = "",
        sort_dir: str = "",
    ) -> dict[str, Any]:
        safe_period_days = self._normalize_country_period_days(period_days)
        sort_map = {
            "country": "m.country",
            "listing_price": "m.listing_price",
            "margin_price_35": "margin_price_35",
            "margin_price_10": "margin_price_10",
            "sales_qty": "sales_qty",
            "natural_daily_sales": "natural_daily_sales",
            "salable_daily_sales": "salable_daily_sales",
            "sales_amount": "sales_amount",
            "order_gross_profit": "order_gross_profit",
            "order_gross_margin": "order_gross_margin",
            "avg_ranking": "avg_ranking",
            "sessions_total": "sessions_total",
            "conversion_rate": "conversion_rate",
            "ad_spend": "ad_spend",
            "ad_sales": "ad_sales",
            "acos": "acos",
        }
        sort_column = sort_map.get(sort_field or "", "sales_qty")
        direction = "asc" if str(sort_dir or "").lower() == "asc" else "desc"
        with self.connect() as conn:
            selected_date = parse_day(snapshot_date) or self._latest_date(conn)
            if not selected_date or not site or not store or not msku:
                return self._empty_country_metrics(selected_date, safe_period_days, site, store, msku)
            params = {
                "snapshot_date": selected_date,
                "period_days": safe_period_days,
                "site": site,
                "store": store,
                "msku": msku,
            }
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        m.period_start,
                        m.period_end,
                        m.country,
                        m.local_sku_list,
                        m.listing_price,
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
                            snapshot_date,
                            country_category,
                            country,
                            seller_name_new,
                            seller_sku,
                            max(margin_price_35) as margin_price_35,
                            max(margin_price_30) as margin_price_30,
                            max(margin_price_25) as margin_price_25,
                            max(margin_price_20) as margin_price_20,
                            max(margin_price_15) as margin_price_15,
                            max(margin_price_10) as margin_price_10,
                            max(margin_price_5) as margin_price_5,
                            max(margin_price_0) as margin_price_0
                        from dashboard_limit_price_daily_snapshot
                        where snapshot_date = (
                            select max(snapshot_date)
                            from dashboard_limit_price_daily_snapshot
                            where snapshot_date <= %(snapshot_date)s
                        )
                          and country_category = %(site)s
                          and seller_name_new = %(store)s
                          and seller_sku = %(msku)s
                        group by snapshot_date, country_category, country, seller_name_new, seller_sku
                    ) p
                      on p.country_category = m.country_category
                     and p.country = m.country
                     and p.seller_name_new = m.seller_name_new
                     and p.seller_sku = m.seller_sku_adj
                    where m.snapshot_date = %(snapshot_date)s
                      and m.period_days = %(period_days)s
                      and m.country_category = %(site)s
                      and m.seller_name_new = %(store)s
                      and m.seller_sku_adj = %(msku)s
                    order by {sort_column} {direction}, m.country
                    """,
                    params,
                )
                rows = cursor.fetchall()
        items = [self._serialize_country_metric(row) for row in rows]
        sales_amount = sum(item["sales_amount"] for item in items)
        order_gross_profit = sum(item["order_gross_profit"] for item in items)
        return {
            "snapshot_date": format_day(selected_date),
            "period_days": safe_period_days,
            "period_start": format_day(rows[0].get("period_start")) if rows else None,
            "period_end": format_day(rows[0].get("period_end")) if rows else None,
            "parent": {"site": site, "store": store, "msku": msku},
            "summary": {
                "country_count": len(items),
                "sales_qty": round(sum(item["sales_qty"] for item in items), 2),
                "sales_amount": round(sales_amount, 2),
                "order_gross_profit": round(order_gross_profit, 2),
                "order_gross_margin": round(order_gross_profit / sales_amount, 6) if sales_amount else 0,
            },
            "items": items,
        }

    def _latest_date(self, conn) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute("select max(cur_date) as cur_date from dashboard_pur_plan_replenish_data")
            row = cursor.fetchone() or {}
        return row.get("cur_date")

    def _previous_date(self, conn, selected_date: date) -> date | None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select max(cur_date) as cur_date
                from dashboard_pur_plan_replenish_data
                where cur_date < %(snapshot_date)s
                """,
                {"snapshot_date": selected_date},
            )
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
                {"key": LEVEL_HISTORY_RECOVERY, "label": LEVEL_HISTORY_RECOVERY},
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
        category_expr: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["cur_date = %(snapshot_date)s"]
        params: dict[str, Any] = self._with_display_level_params({"snapshot_date": snapshot_date})
        if level and level != "all":
            clauses.append(f"{self._display_level_expr()} = %(level)s")
            params["level"] = level
        if category and category != "all" and category_expr:
            clauses.append(f"coalesce({category_expr}, '未分类') = %(category)s")
            params["category"] = category
            category = "all"
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
            "level_history_recovery": LEVEL_HISTORY_RECOVERY,
        }
        display_level_expr = self._display_level_expr()
        history_recovery_condition = self._history_recovery_display_condition()
        display_replenish_qty_expr = self._display_replenish_qty_expr()
        display_replenish_box_qty_expr = self._display_replenish_box_qty_expr()
        display_replenish_cost_expr = self._display_replenish_cost_expr()
        calc_pool_condition = self._calc_pool_condition()
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    count(*) as sku_count,
                    count(*) as all_msku_count,
                    count(*) as detail_row_count,
                    sum(case when {calc_pool_condition} then 1 else 0 end) as calc_msku_count,
                    sum({display_replenish_qty_expr}) as replenish_qty,
                    sum({display_replenish_box_qty_expr}) as replenish_box_qty,
                    sum({display_replenish_cost_expr}) as replenish_cost,
                    avg(inventory_support_days) as avg_support_days,
                    sum(case when {display_level_expr} = %(level_urgent)s then 1 else 0 end) as urgent_count,
                    sum(case when {display_level_expr} = %(level_suggested)s then 1 else 0 end) as suggested_count,
                    sum(case when {display_level_expr} = %(level_planned)s then 1 else 0 end) as planned_count,
                    sum(case when {display_level_expr} = %(level_sufficient)s then 1 else 0 end) as sufficient_count,
                    sum(case when {display_level_expr} = %(level_zero_sales)s then 1 else 0 end) as zero_sales_count,
                    sum(case when {history_recovery_condition} then 1 else 0 end) as history_recovery_count
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
            "history_recovery_count": to_int(row.get("history_recovery_count")),
        }

    def _level_summary(self, conn, filters: str, params: dict[str, Any], category_expr: str) -> list[dict[str, Any]]:
        display_level_expr = self._display_level_expr()
        display_level_sort_expr = self._display_level_sort_expr()
        display_replenish_qty_expr = self._display_replenish_qty_expr()
        display_replenish_cost_expr = self._display_replenish_cost_expr()
        calc_pool_condition = self._calc_pool_condition()
        query_params = self._with_display_level_params(params)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select
                    {display_level_sort_expr} as display_level_sort,
                    {display_level_expr} as display_level,
                    count(*) as sku_count,
                    count(*) as all_msku_count,
                    count(*) as detail_row_count,
                    sum(case when {calc_pool_condition} then 1 else 0 end) as calc_msku_count,
                    sum({display_replenish_qty_expr}) as replenish_qty,
                    sum({display_replenish_cost_expr}) as replenish_cost,
                    avg(inventory_support_days) as avg_support_days
                from dashboard_pur_plan_replenish_data
                where {filters}
                group by display_level_sort, display_level
                order by display_level_sort
                """,
                query_params,
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
            cursor.execute(
                f"""
                select
                    support_replenish_level_sort,
                    coalesce({category_expr}, '未分类') as abcd_category,
                    count(*) as sku_count
                from dashboard_pur_plan_replenish_data
                where {filters}
                group by support_replenish_level_sort, coalesce({category_expr}, '未分类')
                order by support_replenish_level_sort, sku_count desc, abcd_category
                """,
                params,
            )
            mix_rows = cursor.fetchall()
            cursor.execute(
                f"""
                select
                    {display_level_sort_expr} as display_level_sort,
                    coalesce({category_expr}, '未分类') as abcd_category,
                    count(*) as sku_count
                from dashboard_pur_plan_replenish_data
                where {filters}
                group by display_level_sort, coalesce({category_expr}, '未分类')
                order by display_level_sort, sku_count desc, abcd_category
                """,
                query_params,
            )
            mix_rows = cursor.fetchall()
        category_mix: dict[int, list[dict[str, Any]]] = {}
        for row in mix_rows:
            sort = to_int(row.get("display_level_sort"))
            category_mix.setdefault(sort, []).append(
                {
                    "category": row.get("abcd_category") or "未分类",
                    "sku_count": to_int(row.get("sku_count")),
                }
            )
        return [
            {
                "sort": to_int(row.get("display_level_sort")),
                "level": row.get("display_level") or LEVEL_UNKNOWN,
                "sku_count": to_int(row.get("sku_count")),
                "all_msku_count": to_int(row.get("all_msku_count")),
                "detail_row_count": to_int(row.get("detail_row_count")),
                "calc_msku_count": to_int(row.get("calc_msku_count")),
                "replenish_qty": round(to_float(row.get("replenish_qty")), 2),
                "replenish_cost": round(to_float(row.get("replenish_cost")), 2),
                "avg_support_days": round(to_float(row.get("avg_support_days")), 2),
                "category_mix": category_mix.get(to_int(row.get("display_level_sort")), []),
            }
            for row in rows
        ]

    def _calc_pool_condition(self, prefix: str = "") -> str:
        return (
            f"{prefix}support_replenish_level_sort in (1, 2, 3) "
            f"and not (coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0)"
        )

    def _level_flow_summary(
        self,
        conn,
        selected_date: date,
        category: str,
        site: str,
        store: str,
        keyword: str,
        category_expr: str,
    ) -> dict[str, Any]:
        prev_date = self._previous_date(conn, selected_date)
        if not prev_date:
            return {"dates": {"prev_date": None, "cur_date": format_day(selected_date)}, "levels": {}}
        rows = self._level_flow_rows(
            conn,
            selected_date,
            prev_date,
            category,
            site,
            store,
            keyword,
            category_expr,
            FLOW_ALL,
            FLOW_ALL,
        )
        payload = self._build_level_flow_payload(
            rows,
            format_day(prev_date),
            format_day(selected_date),
            target_category=category,
        )
        return {
            "dates": payload["dates"],
            "levels": {row["level"]: row for row in payload["level_changes"]},
        }

    def _attach_level_flow_summary(self, level_summary: list[dict[str, Any]], flow_summary: dict[str, Any]) -> None:
        changes = flow_summary.get("levels", {})
        for row in level_summary:
            row["flow"] = changes.get(
                row.get("level"),
                {
                    "delta_count": 0,
                    "new_count": 0,
                    "in_count": 0,
                    "out_count": 0,
                    "exit_count": 0,
                    "stay_count": 0,
                },
            )

    def _qualify_product_category_expr(self, expr: str, alias: str) -> str:
        qualified = expr
        for column in sorted(PRODUCT_CATEGORY_SQL_COLUMNS, key=len, reverse=True):
            qualified = re.sub(rf"\b{re.escape(column)}\b", f"{alias}.{column}", qualified)
        return qualified

    def _history_recovery_display_condition(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"coalesce({prefix}history_recovery_flag, 0) = 1 "
            f"and coalesce({prefix}support_replenish_level_sort, 99) not in (1, 2, 3) "
            f"and not ({self._followed_block_display_condition(alias)}) "
            f"and not (coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0)"
        )

    def _asin_merge_zero_qty_display_condition(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0 "
            f"and not ({self._followed_block_display_condition(alias)})"
        )

    def _followed_block_display_condition(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return f"coalesce({prefix}replenish_block_reason, '') = %(level_followed_block)s"

    def _display_level_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"case when {self._asin_merge_zero_qty_display_condition(alias)} "
            f"then %(level_sufficient)s when {self._history_recovery_display_condition(alias)} "
            f"then %(level_history_recovery)s else {prefix}support_replenish_level end"
        )

    def _display_level_sort_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"case when {self._asin_merge_zero_qty_display_condition(alias)} "
            f"then 4 when {self._history_recovery_display_condition(alias)} "
            f"then 6 else {prefix}support_replenish_level_sort end"
        )

    def _history_recovery_restore_qty_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return f"case when coalesce({prefix}max_cg_box_pcs, 0) > 0 then {prefix}max_cg_box_pcs else 50 end"

    def _display_replenish_qty_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"case when {self._history_recovery_display_condition(alias)} "
            f"then {self._history_recovery_restore_qty_expr(alias)} else coalesce({prefix}replenish_qty, 0) end"
        )

    def _display_replenish_box_qty_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"case when {self._history_recovery_display_condition(alias)} "
            f"then case when coalesce({prefix}max_cg_box_pcs, 0) > 0 then 1 else 0 end "
            f"else coalesce({prefix}replenish_box_qty, 0) end"
        )

    def _display_replenish_cost_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        unit_cost_expr = f"{prefix}max_cg_price + {prefix}max_cg_transport_costs"
        return (
            f"case when {self._history_recovery_display_condition(alias)} "
            f"then case when {prefix}max_cg_price is not null "
            f"and {prefix}max_cg_transport_costs is not null "
            f"then {self._history_recovery_restore_qty_expr(alias)} * ({unit_cost_expr}) "
            f"else 0 end "
            f"else coalesce({prefix}replenish_cost, 0) end"
        )

    def _display_block_reason_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        current_link_expr = f"concat({prefix}seller_name_new, '/', {prefix}seller_sku_adj)"
        return (
            f"case when {self._followed_block_display_condition(alias)} then %(level_followed_block)s "
            f"when coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0 "
            f"and coalesce({prefix}asin_merge_target, '') <> '' "
            f"and {current_link_expr} <> {prefix}asin_merge_target then %(asin_merge_consolidated_block)s "
            f"when coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0 then %(asin_merge_sufficient_block)s "
            f"when coalesce({prefix}asin_merge_flag, 0) = 1 then {prefix}asin_merge_reason "
            f"else {prefix}replenish_block_reason end"
        )

    def _display_asin_merge_reason_expr(self, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        current_link_expr = f"concat({prefix}seller_name_new, '/', {prefix}seller_sku_adj)"
        return (
            f"case when coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0 "
            f"and coalesce({prefix}asin_merge_target, '') <> '' "
            f"and {current_link_expr} <> {prefix}asin_merge_target then %(asin_merge_consolidated_block)s "
            f"when coalesce({prefix}asin_merge_flag, 0) = 1 "
            f"and coalesce({prefix}replenish_qty, 0) = 0 then %(asin_merge_sufficient_block)s "
            f"else {prefix}asin_merge_reason end"
        )

    def _display_product_daily_sales_expr(self, period_metrics: dict[str, str], alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        daily_sales_expr = self._qualify_product_category_expr(period_metrics["daily_sales_expr"], alias) if alias else period_metrics["daily_sales_expr"]
        group_daily_sales_expr = self._qualify_product_category_expr(period_metrics["daily_sales_expr"], "grp")
        return (
            f"case when coalesce({prefix}asin_merge_flag, 0) = 1 then coalesce(("
            f"select max({group_daily_sales_expr}) "
            f"from dashboard_pur_plan_replenish_data grp "
            f"where grp.cur_date = {prefix}cur_date "
            f"and grp.country_category <=> {prefix}country_category "
            f"and grp.max_asin <=> {prefix}max_asin"
            f"), {daily_sales_expr}) else {daily_sales_expr} end"
        )

    def _with_display_level_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            **params,
            "level_history_recovery": LEVEL_HISTORY_RECOVERY,
            "level_sufficient": LEVEL_SUFFICIENT,
            "level_followed_block": LEVEL_FOLLOWED_BLOCK,
            "asin_merge_consolidated_block": ASIN_MERGE_CONSOLIDATED_BLOCK,
            "asin_merge_sufficient_block": ASIN_MERGE_SUFFICIENT_BLOCK,
        }

    def _level_flow_rows(
        self,
        conn,
        selected_date: date,
        prev_date: date,
        category: str,
        site: str,
        store: str,
        keyword: str,
        category_expr: str,
        level: str,
        flow_type: str,
    ) -> list[dict[str, Any]]:
        filters, params = self._level_flow_filters(selected_date, prev_date, category, site, store, keyword)
        prev_category_expr = self._qualify_product_category_expr(category_expr, "p")
        cur_category_expr = self._qualify_product_category_expr(category_expr, "c")
        prev_level_expr = self._display_level_expr("p")
        prev_level_sort_expr = self._display_level_sort_expr("p")
        cur_level_expr = self._display_level_expr("c")
        cur_level_sort_expr = self._display_level_sort_expr("c")
        query_params = self._with_display_level_params(params)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select *
                from (
                    select
                        coalesce(c.country_category, p.country_category) as country_category,
                        coalesce(c.seller_name_new, p.seller_name_new) as seller_name_new,
                        coalesce(c.seller_sku_adj, p.seller_sku_adj) as seller_sku_adj,
                        coalesce(c.max_sku, p.max_sku) as max_sku,
                        case when p.seller_sku_adj is null then null else {prev_level_expr} end as prev_level,
                        case when p.seller_sku_adj is null then null else {prev_level_sort_expr} end as prev_level_sort,
                        {cur_level_expr} as cur_level,
                        {cur_level_sort_expr} as cur_level_sort,
                        p.replenish_qty as prev_replenish_qty,
                        c.replenish_qty as cur_replenish_qty,
                        p.replenish_cost as prev_replenish_cost,
                        c.replenish_cost as cur_replenish_cost,
                        p.inventory_support_days as prev_inventory_support_days,
                        c.inventory_support_days as cur_inventory_support_days,
                        p.support_inventory_qty as prev_support_inventory_qty,
                        c.support_inventory_qty as cur_support_inventory_qty,
                        p.available_total as prev_available_total,
                        c.available_total as cur_available_total,
                        p.stock_up_num as prev_stock_up_num,
                        c.stock_up_num as cur_stock_up_num,
                        p.local_quantity as prev_local_quantity,
                        c.local_quantity as cur_local_quantity,
                        p.sc_quantity_purchase_plan as prev_purchase_plan_quantity,
                        c.sc_quantity_purchase_plan as cur_purchase_plan_quantity,
                        p.daily_avg_sales as prev_daily_avg_sales,
                        c.daily_avg_sales as cur_daily_avg_sales,
                        p.final_sales_30d as prev_sales_30d,
                        c.final_sales_30d as cur_sales_30d,
                        case when p.seller_sku_adj is null then null else {prev_category_expr} end as prev_category,
                        {cur_category_expr} as cur_category
                    from dashboard_pur_plan_replenish_data c
                    left join dashboard_pur_plan_replenish_data p
                           on p.cur_date = %(prev_date)s
                          and c.country_category = p.country_category
                          and c.seller_name_new = p.seller_name_new
                          and c.seller_sku_adj = p.seller_sku_adj
                    where c.cur_date = %(snapshot_date)s
                    union all
                    select
                        p.country_category,
                        p.seller_name_new,
                        p.seller_sku_adj,
                        p.max_sku,
                        {prev_level_expr} as prev_level,
                        {prev_level_sort_expr} as prev_level_sort,
                        null as cur_level,
                        null as cur_level_sort,
                        p.replenish_qty as prev_replenish_qty,
                        null as cur_replenish_qty,
                        p.replenish_cost as prev_replenish_cost,
                        null as cur_replenish_cost,
                        p.inventory_support_days as prev_inventory_support_days,
                        null as cur_inventory_support_days,
                        p.support_inventory_qty as prev_support_inventory_qty,
                        null as cur_support_inventory_qty,
                        p.available_total as prev_available_total,
                        null as cur_available_total,
                        p.stock_up_num as prev_stock_up_num,
                        null as cur_stock_up_num,
                        p.local_quantity as prev_local_quantity,
                        null as cur_local_quantity,
                        p.sc_quantity_purchase_plan as prev_purchase_plan_quantity,
                        null as cur_purchase_plan_quantity,
                        p.daily_avg_sales as prev_daily_avg_sales,
                        null as cur_daily_avg_sales,
                        p.final_sales_30d as prev_sales_30d,
                        null as cur_sales_30d,
                        {prev_category_expr} as prev_category,
                        null as cur_category
                    from dashboard_pur_plan_replenish_data p
                    left join dashboard_pur_plan_replenish_data c
                           on c.cur_date = %(snapshot_date)s
                          and c.country_category = p.country_category
                          and c.seller_name_new = p.seller_name_new
                          and c.seller_sku_adj = p.seller_sku_adj
                    where p.cur_date = %(prev_date)s
                      and c.seller_sku_adj is null
                ) flow
                where {filters}
                order by coalesce(cur_level_sort, prev_level_sort, 99), seller_sku_adj
                """,
                query_params,
            )
            rows = cursor.fetchall()
        return rows

    def _level_flow_filters(
        self,
        selected_date: date,
        prev_date: date,
        category: str,
        site: str,
        store: str,
        keyword: str,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["1 = 1"]
        params: dict[str, Any] = {"snapshot_date": selected_date, "prev_date": prev_date}
        if category and category != "all":
            clauses.append(
                "(coalesce(cur_category, %(uncategorized)s) = %(category)s "
                "or coalesce(prev_category, %(uncategorized)s) = %(category)s)"
            )
            params["category"] = category
            params["uncategorized"] = "\u672a\u5206\u7c7b"
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

    def _build_level_flow_payload(
        self,
        rows: list[dict[str, Any]],
        prev_date: str | None,
        cur_date: str | None,
        target_level: str = FLOW_ALL,
        target_flow_type: str = FLOW_ALL,
        target_category: str = FLOW_ALL,
    ) -> dict[str, Any]:
        level_map: dict[str, dict[str, Any]] = {}
        link_map: dict[tuple[str, str], dict[str, Any]] = {}
        items: list[dict[str, Any]] = []
        summary = {
            "sku_count": 0,
            "new_count": 0,
            "in_count": 0,
            "out_count": 0,
            "exit_count": 0,
            "stay_count": 0,
            "replenish_qty_delta": 0.0,
            "replenish_cost_delta": 0.0,
        }
        for row in rows:
            prev_level = row.get("prev_level") or FLOW_ENTRY_LABEL
            cur_level = row.get("cur_level") or FLOW_ENTRY_LABEL
            prev_sort = to_int(row.get("prev_level_sort")) if row.get("prev_level_sort") is not None else 99
            cur_sort = to_int(row.get("cur_level_sort")) if row.get("cur_level_sort") is not None else 99
            flow_type = self._classify_flow_type(row, target_level, target_category)
            if target_level != FLOW_ALL and not self._row_matches_level(row, target_level, target_category):
                continue
            if target_flow_type != FLOW_ALL and flow_type != target_flow_type:
                continue
            self._accumulate_level_change(level_map, row, target_category)
            link_key = (f"\u6628\u5929{prev_level}", f"\u4eca\u5929{cur_level}")
            link = link_map.setdefault(
                link_key,
                {
                    "source": link_key[0],
                    "target": link_key[1],
                    "value": 0,
                    "replenish_qty": 0.0,
                    "replenish_cost": 0.0,
                },
            )
            link["value"] += 1
            link["replenish_qty"] += to_float(row.get("cur_replenish_qty"))
            link["replenish_cost"] += to_float(row.get("cur_replenish_cost"))
            cur_qty = to_float(row.get("cur_replenish_qty"))
            prev_qty = to_float(row.get("prev_replenish_qty"))
            cur_cost = to_float(row.get("cur_replenish_cost"))
            prev_cost = to_float(row.get("prev_replenish_cost"))
            summary["sku_count"] += 1
            summary["replenish_qty_delta"] += cur_qty - prev_qty
            summary["replenish_cost_delta"] += cur_cost - prev_cost
            if flow_type == FLOW_NEW:
                summary["new_count"] += 1
            elif flow_type == FLOW_IN:
                summary["in_count"] += 1
            elif flow_type == FLOW_OUT:
                summary["out_count"] += 1
            elif flow_type == FLOW_EXIT:
                summary["exit_count"] += 1
            elif flow_type == FLOW_STAY:
                summary["stay_count"] += 1
            items.append(self._serialize_flow_item(row, flow_type, self._flow_reason(row), prev_sort, cur_sort))
        nodes = sorted(
            {name for link in link_map.values() for name in (link["source"], link["target"])},
            key=self._sankey_node_sort_key,
        )
        links = sorted(
            link_map.values(),
            key=lambda link: (self._sankey_node_sort_key(link["source"]), self._sankey_node_sort_key(link["target"])),
        )
        return {
            "dates": {"prev_date": prev_date, "cur_date": cur_date},
            "target": {"level": target_level, "flow_type": target_flow_type, "category": target_category},
            "summary": {
                **summary,
                "replenish_qty_delta": round(summary["replenish_qty_delta"], 2),
                "replenish_cost_delta": round(summary["replenish_cost_delta"], 2),
            },
            "level_changes": sorted(level_map.values(), key=lambda item: item["sort"]),
            "sankey": {
                "nodes": [{"name": name, "depth": self._sankey_node_depth(name)} for name in nodes],
                "links": [
                    {
                        **link,
                        "replenish_qty": round(link["replenish_qty"], 2),
                        "replenish_cost": round(link["replenish_cost"], 2),
                    }
                    for link in links
                ],
            },
            "items": items,
        }

    def _sankey_node_sort_key(self, name: str) -> tuple[int, int, str]:
        raw_name = name or ""
        side = 1
        level = raw_name
        if raw_name.startswith("\u6628\u5929"):
            side = 0
            level = raw_name[2:]
        elif raw_name.startswith("\u4eca\u5929"):
            side = 1
            level = raw_name[2:]
        return side, FLOW_LEVEL_ORDER.get(level, 90), raw_name

    def _sankey_node_depth(self, name: str) -> int:
        return 0 if (name or "").startswith("\u6628\u5929") else 1

    def _category_matches(self, value: Any, target_category: str = FLOW_ALL) -> bool:
        if not target_category or target_category == FLOW_ALL:
            return True
        return (value or "未分类") == target_category

    def _accumulate_level_change(
        self,
        level_map: dict[str, dict[str, Any]],
        row: dict[str, Any],
        target_category: str = FLOW_ALL,
    ) -> None:
        prev_level = row.get("prev_level")
        cur_level = row.get("cur_level")
        prev_category_match = self._category_matches(row.get("prev_category"), target_category)
        cur_category_match = self._category_matches(row.get("cur_category"), target_category)
        if cur_level and cur_category_match:
            current = level_map.setdefault(
                cur_level,
                {
                    "level": cur_level,
                    "sort": to_int(row.get("cur_level_sort")),
                    "prev_count": 0,
                    "cur_count": 0,
                    "delta_count": 0,
                    "new_count": 0,
                    "in_count": 0,
                    "out_count": 0,
                    "exit_count": 0,
                    "stay_count": 0,
                },
            )
            current["cur_count"] += 1
            if prev_level in REPLENISHMENT_PASSIVE_LEVELS and cur_level in REPLENISHMENT_ACTIVE_LEVELS:
                current["new_count"] += 1
            elif prev_level == cur_level and prev_category_match:
                current["stay_count"] += 1
            else:
                current["in_count"] += 1
        if prev_level and prev_category_match:
            previous = level_map.setdefault(
                prev_level,
                {
                    "level": prev_level,
                    "sort": to_int(row.get("prev_level_sort")),
                    "prev_count": 0,
                    "cur_count": 0,
                    "delta_count": 0,
                    "new_count": 0,
                    "in_count": 0,
                    "out_count": 0,
                    "exit_count": 0,
                    "stay_count": 0,
                },
            )
            previous["prev_count"] += 1
            if prev_level in REPLENISHMENT_ACTIVE_LEVELS and cur_level in REPLENISHMENT_PASSIVE_LEVELS:
                previous["exit_count"] += 1
            elif cur_level != prev_level or not cur_category_match:
                previous["out_count"] += 1
        for item in level_map.values():
            item["delta_count"] = item["cur_count"] - item["prev_count"]

    def _classify_flow_type(
        self,
        row: dict[str, Any],
        target_level: str = FLOW_ALL,
        target_category: str = FLOW_ALL,
    ) -> str:
        prev_level = row.get("prev_level")
        cur_level = row.get("cur_level")
        prev_category_match = self._category_matches(row.get("prev_category"), target_category)
        cur_category_match = self._category_matches(row.get("cur_category"), target_category)
        if target_level != FLOW_ALL:
            cur_match = cur_level == target_level and cur_category_match
            prev_match = prev_level == target_level and prev_category_match
            if cur_match and prev_level in REPLENISHMENT_PASSIVE_LEVELS and cur_level in REPLENISHMENT_ACTIVE_LEVELS:
                return FLOW_NEW
            if cur_match and not prev_match:
                return FLOW_IN
            if prev_match and prev_level in REPLENISHMENT_ACTIVE_LEVELS and cur_level in REPLENISHMENT_PASSIVE_LEVELS:
                return FLOW_EXIT
            if prev_match and not cur_match:
                return FLOW_OUT
            if cur_match and prev_match:
                return FLOW_STAY
            return FLOW_STAY
        if prev_level in REPLENISHMENT_PASSIVE_LEVELS and cur_level in REPLENISHMENT_ACTIVE_LEVELS:
            return FLOW_NEW
        if not prev_level and cur_level:
            return FLOW_IN
        if prev_level in REPLENISHMENT_ACTIVE_LEVELS and cur_level in REPLENISHMENT_PASSIVE_LEVELS:
            return FLOW_EXIT
        if prev_level and not cur_level:
            return FLOW_OUT
        if prev_level == cur_level:
            return FLOW_STAY
        if row.get("cur_level_sort") is not None and row.get("prev_level_sort") is not None:
            return FLOW_IN if to_int(row.get("cur_level_sort")) < to_int(row.get("prev_level_sort")) else FLOW_OUT
        return FLOW_IN

    def _row_matches_level(self, row: dict[str, Any], level: str, target_category: str = FLOW_ALL) -> bool:
        return (
            (row.get("cur_level") == level and self._category_matches(row.get("cur_category"), target_category))
            or (row.get("prev_level") == level and self._category_matches(row.get("prev_category"), target_category))
        )

    def _flow_reason(self, row: dict[str, Any]) -> str:
        if not row.get("prev_level"):
            return "\u8fdb\u5165\u8865\u8d27\u6c60"
        if not row.get("cur_level"):
            return "\u9000\u51fa\u8865\u8d27\u6c60"
        if row.get("prev_level") in REPLENISHMENT_PASSIVE_LEVELS and row.get("cur_level") in REPLENISHMENT_ACTIVE_LEVELS:
            return "\u8f6c\u5165\u8865\u8d27\u8ba1\u7b97"
        if row.get("prev_level") in REPLENISHMENT_ACTIVE_LEVELS and row.get("cur_level") in REPLENISHMENT_PASSIVE_LEVELS:
            return "\u8f6c\u5165\u57fa\u7840\u6c60"
        support_delta = to_float(row.get("cur_support_inventory_qty")) - to_float(row.get("prev_support_inventory_qty"))
        sales_delta = to_float(row.get("cur_daily_avg_sales")) - to_float(row.get("prev_daily_avg_sales"))
        if support_delta > 0:
            return "\u5e93\u5b58\u589e\u52a0"
        if support_delta < 0:
            return "\u5e93\u5b58\u51cf\u5c11"
        if sales_delta > 0:
            return "\u65e5\u9500\u4e0a\u5347"
        if sales_delta < 0:
            return "\u65e5\u9500\u4e0b\u964d"
        return "\u5c42\u7ea7\u9608\u503c\u53d8\u5316"

    def _serialize_flow_item(
        self,
        row: dict[str, Any],
        flow_type: str,
        reason: str,
        prev_sort: int,
        cur_sort: int,
    ) -> dict[str, Any]:
        return {
            "country": row.get("country_category"),
            "store": row.get("seller_name_new"),
            "msku": row.get("seller_sku_adj"),
            "sku": row.get("max_sku"),
            "prev_level": row.get("prev_level") or FLOW_ENTRY_LABEL,
            "cur_level": row.get("cur_level") or FLOW_ENTRY_LABEL,
            "prev_level_sort": prev_sort,
            "cur_level_sort": cur_sort,
            "flow_type": flow_type,
            "reason": reason,
            "prev_support_days": round(to_float(row.get("prev_inventory_support_days")), 2),
            "cur_support_days": round(to_float(row.get("cur_inventory_support_days")), 2),
            "prev_replenish_qty": round(to_float(row.get("prev_replenish_qty")), 2),
            "cur_replenish_qty": round(to_float(row.get("cur_replenish_qty")), 2),
            "prev_replenish_cost": round(to_float(row.get("prev_replenish_cost")), 2),
            "cur_replenish_cost": round(to_float(row.get("cur_replenish_cost")), 2),
            "prev_support_inventory_qty": round(to_float(row.get("prev_support_inventory_qty")), 2),
            "cur_support_inventory_qty": round(to_float(row.get("cur_support_inventory_qty")), 2),
            "prev_daily_sales": round(to_float(row.get("prev_daily_avg_sales")), 4),
            "cur_daily_sales": round(to_float(row.get("cur_daily_avg_sales")), 4),
            "prev_category": row.get("prev_category"),
            "cur_category": row.get("cur_category"),
        }

    def _items(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        sort_field: str,
        sort_dir: str,
        page: int,
        page_size: int,
        period_metrics: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        period_metrics = period_metrics or self._product_category_metric_sql(30)
        display_level_expr = self._display_level_expr()
        display_level_sort_expr = self._display_level_sort_expr()
        display_replenish_qty_expr = self._display_replenish_qty_expr()
        display_replenish_box_qty_expr = self._display_replenish_box_qty_expr()
        display_replenish_cost_expr = self._display_replenish_cost_expr()
        display_product_daily_sales_expr = self._display_product_daily_sales_expr(period_metrics, "r")
        display_block_reason_expr = self._display_block_reason_expr("r")
        display_asin_merge_reason_expr = self._display_asin_merge_reason_expr("r")
        sort_map = {
            "level": display_level_sort_expr,
            "country": "country_category",
            "site": "country_category",
            "store": "seller_name_new",
            "msku": "seller_sku_adj",
            "sku": "max_sku",
            "support_days": "inventory_support_days",
            "daily_sales": "daily_avg_sales",
            "category_daily_sales_30d": display_product_daily_sales_expr,
            "profit_rate_30d": period_metrics["margin_col"],
            "available_total": "available_total",
            "stock_up_num": "stock_up_num",
            "local_quantity": "local_quantity",
            "replenish_qty": display_replenish_qty_expr,
            "replenish_cost": display_replenish_cost_expr,
            "cost": display_replenish_cost_expr,
            "sales_30d": "final_sales_30d",
            "need_qty": "replenish_need_qty",
            "box_qty": display_replenish_box_qty_expr,
            "follow_status": "fllow_flag",
            "followed_status": "followed_flag",
            "followed_by_count": "followed_by_count",
            "followed_by_links": "followed_by_links",
            "follow_origin_link": "follow_origin_link",
            "listing_tags": "global_tags",
            "replenish_block_reason": display_block_reason_expr,
            "asin_merge_status": "asin_merge_flag",
            "asin_merge_target": "asin_merge_target",
            "asin_merge_reason": display_asin_merge_reason_expr,
            "category": period_metrics["category_expr"],
            "margin_range": period_metrics["margin_range_expr"],
        }
        sort_column = sort_map.get(sort_field or "", "support_replenish_level_sort")
        direction = "desc" if str(sort_dir or "").lower() == "desc" else "asc"
        safe_page_size = max(10, min(100, int(page_size or 20)))
        safe_page = max(1, int(page or 1))
        offset = (safe_page - 1) * safe_page_size
        query_params = self._with_display_level_params(params)
        query_params.update({"limit": safe_page_size, "offset": offset})
        with conn.cursor() as cursor:
            cursor.execute(f"select count(*) as total from dashboard_pur_plan_replenish_data where {filters}", params)
            total = to_int((cursor.fetchone() or {}).get("total"))
            cursor.execute(
                f"""
                select
                    cur_date,
                    {display_level_expr} as support_replenish_level,
                    {display_level_sort_expr} as support_replenish_level_sort,
                    country_category,
                    seller_name_new,
                    seller_sku_adj,
                    max_sku,
                    daily_avg_sales,
                    {display_product_daily_sales_expr} as category_daily_sales_30d,
                    {period_metrics["margin_col"]} as pprofit_ratio_30d,
                    inventory_support_days,
                    support_inventory_qty,
                    available_total,
                    stock_up_num,
                    local_quantity,
                    sc_quantity_purchase_plan,
                    final_sales_30d,
                    replenish_need_qty,
                    {display_replenish_qty_expr} as replenish_qty,
                    {display_replenish_box_qty_expr} as replenish_box_qty,
                    {display_replenish_cost_expr} as replenish_cost,
                    fllow_flag,
                    followed_flag,
                    followed_by_count,
                    followed_by_links,
                    follow_origin_link,
                    global_tags,
                    {display_block_reason_expr} as replenish_block_reason,
                    asin_merge_flag,
                    asin_merge_target,
                    {display_asin_merge_reason_expr} as asin_merge_reason,
                    {period_metrics["category_expr"]} as abcd_category,
                    {period_metrics["margin_range_expr"]} as gp_margin_range
                from dashboard_pur_plan_replenish_data r
                where {filters}
                order by {sort_column} {direction}, replenish_qty desc, seller_sku_adj
                limit %(limit)s offset %(offset)s
                """,
                query_params,
            )
            rows = cursor.fetchall()
            self._attach_country_summaries(cursor, rows)
        return [self._serialize_item(row) for row in rows], total

    def _export_items(
        self,
        conn,
        filters: str,
        params: dict[str, Any],
        sort_field: str,
        sort_dir: str,
        columns: list[str] | None = None,
        period_metrics: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        period_metrics = period_metrics or self._product_category_metric_sql(30)
        sort_map = {
            "level": "support_replenish_level_sort",
            "country": "country_category",
            "site": "country_category",
            "store": "seller_name_new",
            "msku": "seller_sku_adj",
            "sku": "max_sku",
            "support_days": "inventory_support_days",
            "daily_sales": "daily_avg_sales",
            "category_daily_sales_30d": period_metrics["daily_sales_expr"],
            "profit_rate_30d": period_metrics["margin_col"],
            "available_total": "available_total",
            "stock_up_num": "stock_up_num",
            "local_quantity": "local_quantity",
            "replenish_qty": "replenish_qty",
            "replenish_cost": "replenish_cost",
            "cost": "replenish_cost",
            "sales_30d": "final_sales_30d",
            "need_qty": "replenish_need_qty",
            "box_qty": "replenish_box_qty",
            "follow_status": "fllow_flag",
            "followed_status": "followed_flag",
            "followed_by_count": "followed_by_count",
            "followed_by_links": "followed_by_links",
            "replenish_block_reason": "replenish_block_reason",
            "asin_merge_status": "asin_merge_flag",
            "asin_merge_target": "asin_merge_target",
            "asin_merge_reason": "asin_merge_reason",
            "category": period_metrics["category_expr"],
            "margin_range": period_metrics["margin_range_expr"],
        }
        sort_column = sort_map.get(sort_field or "", "support_replenish_level_sort")
        direction = "desc" if str(sort_dir or "").lower() == "desc" else "asc"
        export_columns = columns or [col["name"] for col in self._export_columns(conn)]
        select_columns = ",\n                    ".join(
            self._export_select_expression(column, period_metrics) for column in export_columns
        )
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
        for row in rows:
            if "fllow_flag" in row:
                row["fllow_flag"] = format_follow_status(row.get("fllow_flag"))
            if "followed_flag" in row:
                row["followed_flag"] = format_yes_no_status(row.get("followed_flag"))
            if "asin_merge_flag" in row:
                row["asin_merge_flag"] = format_yes_no_status(row.get("asin_merge_flag"))
        return rows

    def _export_select_expression(self, column: str, period_metrics: dict[str, str]) -> str:
        if column == "abcd_category":
            return f"{period_metrics['category_expr']} as {self._quote_identifier(column)}"
        if column == "gp_margin_range":
            return f"{period_metrics['margin_range_expr']} as {self._quote_identifier(column)}"
        return self._quote_identifier(column)

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
                "label": REPLENISHMENT_EXPORT_LABEL_OVERRIDES.get(row.get("column_name"))
                or row.get("column_comment")
                or REPLENISHMENT_COLUMN_LABELS.get(row.get("column_name"), row.get("column_name")),
            }
            for row in rows
            if row.get("column_name") and row.get("column_name") not in REPLENISHMENT_EXPORT_EXCLUDED_COLUMNS
        ]

    def _quote_identifier(self, value: str) -> str:
        return "`" + value.replace("`", "``") + "`"

    def _attach_country_summaries(self, cursor, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        params: dict[str, Any] = {}
        predicates: list[str] = []
        for index, row in enumerate(rows):
            params[f"snapshot_date_{index}"] = row.get("cur_date")
            params[f"country_category_{index}"] = row.get("country_category")
            params[f"seller_name_new_{index}"] = row.get("seller_name_new")
            params[f"seller_sku_adj_{index}"] = row.get("seller_sku_adj")
            predicates.append(
                "("
                f"snapshot_date = %(snapshot_date_{index})s "
                f"and country_category = %(country_category_{index})s "
                f"and seller_name_new = %(seller_name_new_{index})s "
                f"and seller_sku_adj = %(seller_sku_adj_{index})s"
                ")"
            )
        cursor.execute(
            f"""
            select
                snapshot_date,
                country_category,
                seller_name_new,
                seller_sku_adj,
                count(*) as country_count,
                substring_index(
                    group_concat(
                        concat(country, ' ', cast(round(sales_qty, 0) as char))
                        order by sales_qty desc, country
                        separator ' | '
                    ),
                    ' | ',
                    1
                ) as top_countries
            from dashboard_replenishment_country_metrics
            where period_days = 30
              and ({' or '.join(predicates)})
            group by snapshot_date, country_category, seller_name_new, seller_sku_adj
            """,
            params,
        )
        summary_map = {
            (
                row.get("snapshot_date"),
                row.get("country_category"),
                row.get("seller_name_new"),
                row.get("seller_sku_adj"),
            ): row
            for row in cursor.fetchall()
        }
        for row in rows:
            summary = summary_map.get(
                (
                    row.get("cur_date"),
                    row.get("country_category"),
                    row.get("seller_name_new"),
                    row.get("seller_sku_adj"),
                ),
                {},
            )
            row["country_count"] = summary.get("country_count")
            row["top_countries"] = summary.get("top_countries")

    def _normalize_product_category_period_days(self, value: int | str | None) -> int:
        try:
            period_days = int(value or 30)
        except (TypeError, ValueError):
            period_days = 30
        return period_days if period_days in PRODUCT_CATEGORY_PERIODS else 30

    def _product_category_metric_sql(self, period_days: int) -> dict[str, str]:
        safe_period_days = self._normalize_product_category_period_days(period_days)
        sales_col = PRODUCT_CATEGORY_SALES_COLUMNS[safe_period_days]
        salable_col = f"r_{safe_period_days}d_salable_days"
        margin_col = f"pprofit_ratio_{safe_period_days}d"
        salable_floor_days = math.ceil(safe_period_days / 2)
        effective_salable_days_expr = f"greatest({salable_col}, {salable_floor_days})"
        daily_sales_expr = f"case when {salable_col} > 0 then {sales_col} / {effective_salable_days_expr} else 0 end"
        category_expr = f"""
            case
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
        margin_range_expr = f"""
            case
                when {margin_col} >= 0.15 then '>=15%%'
                when {margin_col} >= 0.10 then '10%%-15%%'
                when {margin_col} >= 0.05 then '5%%-10%%'
                when {margin_col} >= 0 then '0%%-5%%'
                else '<0%%'
            end
        """.strip()
        return {
            "period_days": str(safe_period_days),
            "daily_sales_expr": daily_sales_expr,
            "margin_col": margin_col,
            "category_expr": category_expr,
            "margin_range_expr": margin_range_expr,
        }

    def _normalize_country_period_days(self, value: int | str | None) -> int:
        try:
            period_days = int(value or 30)
        except (TypeError, ValueError):
            period_days = 30
        return period_days if period_days in COUNTRY_METRIC_PERIODS else 30

    def _serialize_country_metric(self, row: dict[str, Any]) -> dict[str, Any]:
        margin_prices = [
            {
                "target": target,
                "label": f"{target}\u6bdb\u5229",
                "price": round(to_float(row.get(f"margin_price_{target}")), 4),
            }
            for target in MARGIN_PRICE_TARGETS
            if row.get(f"margin_price_{target}") is not None
        ]
        return {
            "country": row.get("country") or "-",
            "local_sku_list": row.get("local_sku_list") or "",
            "listing_price": round(to_float(row.get("listing_price")), 4),
            "margin_price_35": round(to_float(row.get("margin_price_35")), 4),
            "margin_price_30": round(to_float(row.get("margin_price_30")), 4),
            "margin_price_25": round(to_float(row.get("margin_price_25")), 4),
            "margin_price_20": round(to_float(row.get("margin_price_20")), 4),
            "margin_price_15": round(to_float(row.get("margin_price_15")), 4),
            "margin_price_10": round(to_float(row.get("margin_price_10")), 4),
            "margin_price_5": round(to_float(row.get("margin_price_5")), 4),
            "margin_price_0": round(to_float(row.get("margin_price_0")), 4),
            "margin_prices": margin_prices,
            "sales_qty": round(to_float(row.get("sales_qty")), 2),
            "natural_daily_sales": round(to_float(row.get("natural_daily_sales")), 4),
            "salable_days": to_int(row.get("salable_days")),
            "salable_daily_sales": round(to_float(row.get("salable_daily_sales")), 4),
            "sales_amount": round(to_float(row.get("sales_amount")), 2),
            "order_gross_profit": round(to_float(row.get("order_gross_profit")), 2),
            "order_gross_margin": round(to_float(row.get("order_gross_margin")), 6),
            "avg_ranking": round(to_float(row.get("avg_ranking")), 2),
            "best_ranking": round(to_float(row.get("best_ranking")), 2),
            "worst_ranking": round(to_float(row.get("worst_ranking")), 2),
            "sessions_total": round(to_float(row.get("sessions_total")), 2),
            "conversion_rate": round(to_float(row.get("conversion_rate")), 6),
            "ad_spend": round(to_float(row.get("ad_spend")), 2),
            "ad_orders": round(to_float(row.get("ad_orders")), 2),
            "ad_sales": round(to_float(row.get("ad_sales")), 2),
            "ad_clicks": round(to_float(row.get("ad_clicks")), 2),
            "ad_impressions": round(to_float(row.get("ad_impressions")), 2),
            "acos": round(to_float(row.get("acos")), 6),
            "ctr": round(to_float(row.get("ctr")), 6),
        }

    def _country_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        parts = [part.strip() for part in str(row.get("top_countries") or "").split("|") if part.strip()]
        return {
            "country_count": to_int(row.get("country_count")),
            "top_countries": " | ".join(parts[:3]),
        }

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
            "follow_status": format_follow_status(row.get("fllow_flag")),
            "followed_status": format_yes_no_status(row.get("followed_flag")),
            "followed_by_count": to_int(row.get("followed_by_count")),
            "followed_by_links": row.get("followed_by_links"),
            "follow_origin_link": row.get("follow_origin_link"),
            "listing_tags": row.get("global_tags"),
            "replenish_block_reason": row.get("replenish_block_reason"),
            "asin_merge_status": format_yes_no_status(row.get("asin_merge_flag")),
            "asin_merge_target": row.get("asin_merge_target"),
            "asin_merge_reason": row.get("asin_merge_reason"),
            "country_summary": self._country_summary(row),
            "category": row.get("abcd_category"),
            "margin_range": row.get("gp_margin_range"),
        }

    def _empty_country_metrics(
        self,
        snapshot_date: date | None,
        period_days: int,
        site: str,
        store: str,
        msku: str,
    ) -> dict[str, Any]:
        return {
            "snapshot_date": format_day(snapshot_date),
            "period_days": period_days,
            "period_start": None,
            "period_end": None,
            "parent": {"site": site, "store": store, "msku": msku},
            "summary": {
                "country_count": 0,
                "sales_qty": 0,
                "sales_amount": 0,
                "order_gross_profit": 0,
                "order_gross_margin": 0,
            },
            "items": [],
        }

    def _empty_level_flow(self, prev_date: date | None, cur_date: date | None) -> dict[str, Any]:
        return {
            "dates": {"prev_date": format_day(prev_date), "cur_date": format_day(cur_date)},
            "target": {"level": FLOW_ALL, "flow_type": FLOW_ALL},
            "summary": {
                "sku_count": 0,
                "new_count": 0,
                "in_count": 0,
                "out_count": 0,
                "exit_count": 0,
                "stay_count": 0,
                "replenish_qty_delta": 0,
                "replenish_cost_delta": 0,
            },
            "level_changes": [],
            "sankey": {"nodes": [], "links": []},
            "items": [],
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
