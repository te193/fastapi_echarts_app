from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


DAILY_SALES_BANDS = ["日销 0", "日销 <1", "日销 1-5", "日销 >5"]
MARGIN_BANDS = ["毛利率 >35%", "毛利率 25-35%", "毛利率 15-25%", "毛利率 10-15%", "毛利率 0-10%", "毛利率 <0%"]
SITES = ["美国站", "英国站", "德国站", "法国站", "意大利站", "西班牙站", "波兰站"]
STORES_BY_SITE = {
    "美国站": ["PrimeNest", "North Harbor", "SkyCart US"],
    "英国站": ["BritFlow", "West Loom"],
    "德国站": ["BerlinWave", "Rhine Trade", "Qipunike"],
    "法国站": ["Paris Hub", "jingjie231335"],
    "意大利站": ["Milano Goods", "Yeechese"],
    "西班牙站": ["Iberia Mart", "MuuWei"],
    "波兰站": ["Baltic Cart", "senmile"],
}
OWNERS = ["林然", "周乔", "许杉", "陈诺", "唐悦", "冯鸣", "顾言", "赵嘉"]
BRANDS = ["NestArc", "PawHue", "CookPulse", "TrailMint", "DeskNova", "CoreLift"]
CATEGORIES = ["家居收纳", "宠物用品", "厨房电器", "户外出行", "办公配件", "健身器材"]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_in_year(current: date) -> int:
    return (date(current.year + 1, 1, 1) - date(current.year, 1, 1)).days


def day_of_year(current: date) -> int:
    return (current - date(current.year, 1, 1)).days + 1


def format_percent(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def sales_band(value: float) -> str:
    if value <= 0.01:
        return "日销 0"
    if value < 1:
        return "日销 <1"
    if value <= 5:
        return "日销 1-5"
    return "日销 >5"


def margin_band(value: float) -> str:
    if value > 0.35:
        return "毛利率 >35%"
    if value >= 0.25:
        return "毛利率 25-35%"
    if value >= 0.15:
        return "毛利率 15-25%"
    if value >= 0.10:
        return "毛利率 10-15%"
    if value >= 0:
        return "毛利率 0-10%"
    return "毛利率 <0%"


@dataclass
class WindowInfo:
    start_index: int
    end_index: int
    days: int
    start_date: date
    end_date: date


class MockDashboardService:
    def __init__(self) -> None:
        self.history_days = 30
        self.kpi_trend_days = 7
        self.end_date = date.today()
        self.start_date = self.end_date - timedelta(days=self.history_days - 1)
        self.sales_goal = 135000000
        self.sales_goal_buffer = 1.01
        self.margin_goal = 0.20
        self.dataset = self._build_dataset()

    def get_meta(self) -> dict[str, Any]:
        return {
            "default_start_date": format_date(self.start_date),
            "default_end_date": format_date(self.end_date),
            "history_days": self.history_days,
            "daily_sales_bands": DAILY_SALES_BANDS,
            "margin_bands": MARGIN_BANDS,
            "sites": SITES,
            "stores": sorted({store for stores in STORES_BY_SITE.values() for store in stores}),
            "owners": OWNERS,
        }

    def get_dashboard_payload(self, filters: dict[str, Any]) -> dict[str, Any]:
        scoped = self._get_filtered_items(filters)
        goal_items = self._get_goal_items()
        return {
            "meta": self.get_meta(),
            "goal_overview": self._build_goal_overview(goal_items),
            "summary_hint": self._build_summary(scoped),
            "kpis": self._build_kpis(scoped),
            "daily_sales_chart": self._build_band_chart(scoped, DAILY_SALES_BANDS, "daily_sales_band"),
            "margin_chart": self._build_band_chart(scoped, MARGIN_BANDS, "margin_band"),
            "matrix": self._build_matrix(scoped),
        }

    def get_detail_payload(
        self,
        filters: dict[str, Any],
        page: int,
        page_size: int,
        sort_field: str = "",
        sort_dir: str = "",
    ) -> dict[str, Any]:
        scoped = self._get_filtered_items(filters)
        scoped.sort(key=lambda item: (-item["revenue_30d"], -item["daily_sales"], item["sku"]))
        total = len(scoped)
        total_pages = max(1, math.ceil(total / page_size))
        safe_page = min(max(1, page), total_pages)
        start = (safe_page - 1) * page_size
        rows = scoped[start:start + page_size]
        return {
            "meta": self.get_meta(),
            "rows": rows,
            "total": total,
            "page": safe_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "summary_hint": self._build_summary(scoped),
        }

    def get_detail_record(self, item_id: str, trend_days: int) -> dict[str, Any]:
        item = next((row for row in self.dataset if row["id"] == item_id), None)
        if not item:
            return {"error": "not_found"}

        days = max(7, min(30, trend_days))
        trend_values = item["revenue_trend"][-days:]
        trend_labels = [format_date(self.end_date - timedelta(days=days - index - 1)) for index in range(days)]
        total_revenue = round(sum(trend_values), 2)
        average_revenue = round(total_revenue / days, 2)
        first_value = trend_values[0] if trend_values else 0
        latest_value = trend_values[-1] if trend_values else 0
        change_ratio = ((latest_value - first_value) / first_value) if first_value else (1 if latest_value > 0 else 0)
        scoped = self._scope_item(item, self._default_window())

        return {
            "item": {
                "id": item["id"],
                "title": f'{item["sku"]} · {item["store"]} / {item["site"]}',
                "site": item["site"],
                "store": item["store"],
                "sku": item["sku"],
                "asin": item["asin"],
                "owner": item["owner"],
                "brand": item["brand"],
                "category": item["category"],
                "stat_period": scoped["stat_period"],
                "current_revenue": scoped["scoped_revenue"],
                "current_daily_sales": scoped["daily_sales"],
                "current_margin": scoped["order_gross_margin"],
                "current_price": item["current_price"],
                "fba_sellable_inventory": item["fba_sellable_inventory"],
                "stock_days": item["stock_days"],
            },
            "trend": {
                "days": days,
                "labels": trend_labels,
                "values": trend_values,
                "total_revenue": total_revenue,
                "average_revenue": average_revenue,
                "latest_revenue": latest_value,
                "change_ratio": round(change_ratio, 4),
            },
        }

    def _build_dataset(self) -> list[dict[str, Any]]:
        dataset: list[dict[str, Any]] = []
        for index in range(240):
            site = SITES[index % len(SITES)]
            store = STORES_BY_SITE[site][(index // len(SITES)) % len(STORES_BY_SITE[site])]
            owner = OWNERS[index % len(OWNERS)]
            brand = BRANDS[index % len(BRANDS)]
            category = CATEGORIES[(index * 2) % len(CATEGORIES)]
            sku = f"{brand[:2].upper()}-{index + 1:04d}"
            asin = f"B0{148000 + index:06d}"
            current_price = round(18 + (index % 11) * 2.75 + (len(store) % 3) * 1.4, 2)
            limit_price = round(current_price + 3.6 + (index % 4) * 0.9, 2)
            limit_price_10 = round(max(current_price - 2.4, 0), 2)
            over_limit = (index % 17) == 0
            if over_limit:
                current_price = round(limit_price + 1.35, 2)

            margin_base = [0.42, 0.31, 0.21, 0.13, 0.06, -0.04][index % 6]
            revenue_trend = self._build_revenue_trend(index, current_price)
            units_trend = [round(value / max(current_price, 0.1), 2) for value in revenue_trend]
            margin_trend = [
                round(clamp(margin_base + math.sin((index + day) / 4.3) * 0.025, -0.12, 0.52), 3)
                for day in range(self.history_days)
            ]
            ad_spend_trend = [
                round(value * (0.08 + ((index + day) % 4) * 0.02), 2)
                for day, value in enumerate(revenue_trend)
            ]
            ad_sales_trend = [
                round(value * (0.18 + ((index + day) % 5) * 0.03), 2)
                for day, value in enumerate(revenue_trend)
            ]
            ad_clicks_trend = [int(max(0, value / 12 + ((index + day) % 6))) for day, value in enumerate(ad_sales_trend)]
            ad_impressions_trend = [int(clicks * (24 + ((index + day) % 7) * 6)) for day, clicks in enumerate(ad_clicks_trend)]
            fba_sellable_inventory = 45 + (index % 13) * 26
            actual_in_transit = 8 + (index % 7) * 11
            unsellable_inventory = 1 + (index % 5) * 3
            stock_days = int(fba_sellable_inventory / max(sum(units_trend) / self.history_days, 0.08))

            dataset.append(
                {
                    "id": f"{store}-{sku}-{site}-{index}",
                    "site": site,
                    "store": store,
                    "owner": owner,
                    "sku": sku,
                    "asin": asin,
                    "product_name": f"{brand} {category} 款式 {index % 5 + 1}",
                    "brand": brand,
                    "category": category,
                    "current_price": current_price,
                    "limit_price": limit_price,
                    "limit_price_35": limit_price,
                    "limit_price_10": limit_price_10,
                    "over_limit": over_limit,
                    "price_gap": round(current_price - limit_price, 2),
                    "fba_sellable_inventory": fba_sellable_inventory,
                    "actual_in_transit": actual_in_transit,
                    "unsellable_inventory": unsellable_inventory,
                    "fba_sellable_trend": self._build_snapshot_trend(index + 13, fba_sellable_inventory, 0),
                    "actual_in_transit_trend": self._build_snapshot_trend(index + 23, actual_in_transit, 0),
                    "unsellable_trend": self._build_snapshot_trend(index + 31, unsellable_inventory, 0),
                    "stock_days": stock_days,
                    "rating": round(3.8 + (index % 7) * 0.17, 1),
                    "review_count": 36 + (index % 11) * 41,
                    "units_trend": units_trend,
                    "revenue_trend": revenue_trend,
                    "margin_trend": margin_trend,
                    "ad_spend_trend": ad_spend_trend,
                    "ad_sales_trend": ad_sales_trend,
                    "ad_clicks_trend": ad_clicks_trend,
                    "ad_impressions_trend": ad_impressions_trend,
                }
            )
        return dataset

    def _build_revenue_trend(self, seed: int, price: float) -> list[float]:
        base_units = [0.0, 0.45, 1.6, 3.4, 5.8][seed % 5]
        trend: list[float] = []
        for day in range(self.history_days):
            wave = math.sin((seed + day) / 3.1) * (0.55 + (seed % 4) * 0.14)
            drift = (((seed * 7 + day * 5) % 7) - 3) * 0.16
            units = clamp(base_units + wave + drift, 0, 12)
            trend.append(round(units * price, 2))
        return trend

    def _build_snapshot_trend(self, seed: int, current_value: float, digits: int = 0) -> list[float]:
        trend: list[float] = []
        for day in range(self.history_days):
            wave = math.sin((seed + day) / 4.4) * 0.08
            drift = (((seed * 5 + day * 2) % 7) - 3) * 0.018
            value = max(0, current_value * (1 + wave + drift))
            trend.append(round(value, digits))
        return trend

    def _default_window(self) -> WindowInfo:
        return WindowInfo(
            start_index=0,
            end_index=self.history_days - 1,
            days=self.history_days,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def _window_from_filters(self, filters: dict[str, Any]) -> WindowInfo:
        start = parse_date(filters.get("start_date")) or self.start_date
        end = parse_date(filters.get("end_date")) or self.end_date
        start = max(start, self.start_date)
        end = min(end, self.end_date)
        if start > end:
            start = self.start_date
            end = self.end_date

        start_index = (start - self.start_date).days
        end_index = (end - self.start_date).days
        return WindowInfo(
            start_index=start_index,
            end_index=end_index,
            days=end_index - start_index + 1,
            start_date=start,
            end_date=end,
        )

    def _scope_item(self, item: dict[str, Any], window: WindowInfo) -> dict[str, Any]:
        trend_start_index = max(0, window.end_index - self.kpi_trend_days + 1)
        units = item["units_trend"][window.start_index:window.end_index + 1]
        revenue = item["revenue_trend"][window.start_index:window.end_index + 1]
        margin_values = item["margin_trend"][window.start_index:window.end_index + 1]
        ad_spend = item["ad_spend_trend"][window.start_index:window.end_index + 1]
        ad_sales = item["ad_sales_trend"][window.start_index:window.end_index + 1]
        ad_clicks = item["ad_clicks_trend"][window.start_index:window.end_index + 1]
        ad_impressions = item["ad_impressions_trend"][window.start_index:window.end_index + 1]
        sellable = item["fba_sellable_trend"][window.start_index:window.end_index + 1]
        in_transit = item["actual_in_transit_trend"][window.start_index:window.end_index + 1]
        unsellable = item["unsellable_trend"][window.start_index:window.end_index + 1]
        kpi_units = item["units_trend"][trend_start_index:window.end_index + 1]
        kpi_revenue = item["revenue_trend"][trend_start_index:window.end_index + 1]
        kpi_margin = item["margin_trend"][trend_start_index:window.end_index + 1]
        kpi_sellable = item["fba_sellable_trend"][trend_start_index:window.end_index + 1]
        kpi_in_transit = item["actual_in_transit_trend"][trend_start_index:window.end_index + 1]
        kpi_unsellable = item["unsellable_trend"][trend_start_index:window.end_index + 1]
        kpi_ad_spend = item["ad_spend_trend"][trend_start_index:window.end_index + 1]
        kpi_ad_sales = item["ad_sales_trend"][trend_start_index:window.end_index + 1]

        scoped_revenue = round(sum(revenue), 2)
        scoped_sales = round(sum(units))
        daily_sales = round(sum(units) / max(window.days, 1), 2)
        order_gross_margin = round(sum(margin_values) / max(len(margin_values), 1), 3)
        ad_spend_total = round(sum(ad_spend), 2)
        ad_sales_total = round(sum(ad_sales), 2)
        ad_clicks_total = sum(ad_clicks)
        ad_impressions_total = sum(ad_impressions)
        acos = round(ad_spend_total / ad_sales_total, 4) if ad_sales_total else 0
        tacos = round(ad_spend_total / scoped_revenue, 4) if scoped_revenue else 0
        ctr = round(ad_clicks_total / ad_impressions_total, 4) if ad_impressions_total else 0

        return {
            "id": item["id"],
            "site": item["site"],
            "store": item["store"],
            "owner": item["owner"],
            "sku": item["sku"],
            "asin": item["asin"],
            "product_name": item["product_name"],
            "brand": item["brand"],
            "category": item["category"],
            "current_price": item["current_price"],
            "limit_price": item["limit_price"],
            "limit_price_35": item["limit_price_35"],
            "limit_price_10": item["limit_price_10"],
            "price_gap": item["price_gap"],
            "over_limit": item["over_limit"],
            "fba_sellable_inventory": item["fba_sellable_inventory"],
            "actual_in_transit": item["actual_in_transit"],
            "unsellable_inventory": item["unsellable_inventory"],
            "stock_days": item["stock_days"],
            "rating": item["rating"],
            "review_count": item["review_count"],
            "scoped_sales": scoped_sales,
            "scoped_revenue": scoped_revenue,
            "daily_sales": daily_sales,
            "daily_sales_band": sales_band(daily_sales),
            "order_gross_margin": order_gross_margin,
            "margin_band": margin_band(order_gross_margin),
            "sales_7d": round(sum(units[-7:])),
            "sales_30d": round(sum(item["units_trend"])),
            "revenue_30d": round(sum(item["revenue_trend"]), 2),
            "ad_spend": ad_spend_total,
            "ad_sales": ad_sales_total,
            "acos": acos,
            "tacos": tacos,
            "ctr": ctr,
            "stat_period": f"{format_date(window.start_date)} ~ {format_date(window.end_date)}",
            "series_units": units,
            "series_revenue": revenue,
            "series_margin": margin_values,
            "series_sellable": sellable,
            "series_in_transit": in_transit,
            "series_unsellable": unsellable,
            "series_ad_spend": ad_spend,
            "series_ad_sales": ad_sales,
            "kpi_series_units": kpi_units,
            "kpi_series_revenue": kpi_revenue,
            "kpi_series_margin": kpi_margin,
            "kpi_series_sellable": kpi_sellable,
            "kpi_series_in_transit": kpi_in_transit,
            "kpi_series_unsellable": kpi_unsellable,
            "kpi_series_ad_spend": kpi_ad_spend,
            "kpi_series_ad_sales": kpi_ad_sales,
        }

    def _get_filtered_items(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        window = self._window_from_filters(filters)
        scoped = [self._scope_item(item, window) for item in self.dataset]
        keyword = str(filters.get("keyword") or "").strip().lower()

        result: list[dict[str, Any]] = []
        for item in scoped:
            if filters.get("site", "all") != "all" and item["site"] != filters["site"]:
                continue
            if filters.get("store", "all") != "all" and item["store"] != filters["store"]:
                continue
            if filters.get("owner", "all") != "all" and item["owner"] != filters["owner"]:
                continue
            if filters.get("over_limit") == "yes" and not item["over_limit"]:
                continue
            if filters.get("over_limit") == "no" and item["over_limit"]:
                continue
            if filters.get("daily_sales_band", "all") != "all" and item["daily_sales_band"] != filters["daily_sales_band"]:
                continue
            if filters.get("margin_band", "all") != "all" and item["margin_band"] != filters["margin_band"]:
                continue
            if keyword:
                haystack = " ".join(
                    [
                        item["sku"],
                        item["asin"],
                        item["product_name"],
                        item["brand"],
                        item["category"],
                        item["site"],
                        item["store"],
                    ]
                ).lower()
                if keyword not in haystack:
                    continue
            result.append(item)
        return result

    def _get_goal_items(self) -> list[dict[str, Any]]:
        window = self._default_window()
        return [self._scope_item(item, window) for item in self.dataset]

    def _build_summary(self, items: list[dict[str, Any]]) -> str:
        combo = len([item for item in items if item["margin_band"] == "毛利率 >35%" and item["daily_sales_band"] == "日销 <1"])
        over_limit = len([item for item in items if item["over_limit"]])
        return f"全部结果共 {len(items)} 个 SKU，其中“毛利率 >35% 且日销 <1”有 {combo} 个，超限价 {over_limit} 个。"

    def _build_goal_overview(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        current_revenue = round(sum(item["scoped_revenue"] for item in items), 2)
        current_margin = round(sum(item["order_gross_margin"] for item in items) / max(len(items), 1), 4)
        today = date.today()
        year_days = days_in_year(today)
        current_day = day_of_year(today)
        target_by_today = round(
            self.sales_goal / year_days * self.sales_goal_buffer * current_day,
            2,
        )

        return {
            "sales_goal": {
                "title": "销售额目标",
                "current_value": current_revenue,
                "target_value": self.sales_goal,
                "ratio": round(current_revenue / self.sales_goal, 4) if self.sales_goal else 0,
                "detail_text": "固定周期销售额 / 年度目标",
                "delta_text": f"距目标还差 {self.sales_goal - current_revenue:,.2f}",
            },
            "current_goal": {
                "title": "当前目标情况",
                "current_value": current_revenue,
                "target_value": target_by_today,
                "ratio": round(current_revenue / target_by_today, 4) if target_by_today else 0,
                "detail_text": f"{format_date(today)} / 1.35 亿 ÷ {year_days} × 1.01 × 第 {current_day} 天",
                "delta_text": f"距今还差 {target_by_today - current_revenue:,.2f}",
            },
            "margin_goal": {
                "title": "毛利率目标",
                "current_value": current_margin,
                "target_value": self.margin_goal,
                "ratio": round(current_margin / self.margin_goal, 4) if self.margin_goal else 0,
                "detail_text": "当前平均订单毛利率 / 目标值",
                "delta_text": f"距目标差 {(self.margin_goal - current_margin) * 100:.1f} 个百分点",
            },
        }

    def _build_kpis(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        revenue = round(sum(item["scoped_revenue"] for item in items), 2)
        avg_daily_sales = round(sum(item["daily_sales"] for item in items) / max(len(items), 1), 2)
        avg_margin = round(sum(item["order_gross_margin"] for item in items) / max(len(items), 1), 4)
        sellable = sum(item["fba_sellable_inventory"] for item in items)
        in_transit = sum(item["actual_in_transit"] for item in items)
        unsellable = sum(item["unsellable_inventory"] for item in items)
        ad_spend = round(sum(item["ad_spend"] for item in items), 2)
        ad_sales = round(sum(item["ad_sales"] for item in items), 2)
        total_revenue = max(revenue, 0.01)
        acos = round(ad_spend / ad_sales, 4) if ad_sales else 0
        tacos = round(ad_spend / total_revenue, 4)
        total_inventory = max(sellable + in_transit + unsellable, 1)

        revenue_series = self._aggregate_sum_series(items, "kpi_series_revenue")
        daily_series = self._aggregate_sum_series(items, "kpi_series_units")
        active_sku_series = self._aggregate_active_sku_series(items, "kpi_series_units")
        margin_series = self._aggregate_average_series(items, "kpi_series_margin", 4)
        sellable_series = self._aggregate_sum_series(items, "kpi_series_sellable", 0)
        in_transit_series = self._aggregate_sum_series(items, "kpi_series_in_transit", 0)
        unsellable_series = self._aggregate_sum_series(items, "kpi_series_unsellable", 0)
        ad_spend_series = self._aggregate_sum_series(items, "kpi_series_ad_spend")
        ad_sales_series = self._aggregate_sum_series(items, "kpi_series_ad_sales")
        acos_series = self._aggregate_ratio_series(ad_spend_series, ad_sales_series, 4)
        tacos_series = self._aggregate_ratio_series(ad_spend_series, revenue_series, 4)

        return [
            self._build_kpi_item("active_sku", "在售产品数", len(items), "number", "结构", "当前筛选下的产品数量", self._ratio_text(len(items), len(self.dataset)), "positive", "#1769e0", active_sku_series),
            self._build_kpi_item("revenue", "区间销售额", revenue, "currency", "规模", "当前区间累计销售额", self._slope_text(revenue_series), self._slope_tone(revenue_series), "#18a17d", revenue_series),
            self._build_kpi_item("avg_daily_sales", "平均日销", avg_daily_sales, "number", "日销", "当前样本平均日销", self._daily_sales_hint(avg_daily_sales), self._daily_sales_tone(avg_daily_sales), "#4b86df", daily_series),
            self._build_kpi_item("avg_margin", "平均订单毛利率", avg_margin, "percent", "毛利", "当前样本平均订单毛利率", self._margin_hint(avg_margin), self._margin_tone(avg_margin), "#cf4f5f", margin_series),
            self._build_kpi_item("fba_sellable", "FBA 可售", sellable, "number", "库存", "当前筛选下 FBA 可售库存", "可售占比 " + format_percent(sellable / total_inventory), "positive", "#4b86df", sellable_series),
            self._build_kpi_item("actual_in_transit", "实际在途", in_transit, "number", "补货", "当前筛选下实际在途", self._ratio_text(in_transit, total_inventory), "warning", "#18a17d", in_transit_series),
            self._build_kpi_item("unsellable", "不可售库存", unsellable, "number", "风险库存", "当前筛选下不可售库存", self._ratio_text(unsellable, total_inventory), "negative", "#cf4f5f", unsellable_series),
            self._build_kpi_item("ad_spend", "广告花费", ad_spend, "currency", "广告", "当前区间广告花费", self._slope_text(ad_spend_series), self._slope_tone(ad_spend_series), "#d97706", ad_spend_series),
            self._build_kpi_item("acos", "ACOS", acos, "percent", "投放效率", "广告花费 / 广告销售额", self._slope_text(acos_series), self._slope_tone(acos_series), "#cf4f5f", acos_series),
            self._build_kpi_item("tacos", "TACOS", tacos, "percent", "营收占比", "广告花费 / 总销售额", self._slope_text(tacos_series), self._slope_tone(tacos_series), "#4b86df", tacos_series),
        ]

    def _build_kpi_item(
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
            "series": series,
        }

    def _aggregate_sum_series(self, items: list[dict[str, Any]], key: str, digits: int = 2) -> list[float]:
        if not items:
            return [0]
        size = len(items[0].get(key, []))
        if not size:
            return [0]
        result = [0.0] * size
        for item in items:
            values = item.get(key, [])
            for index in range(min(size, len(values))):
                result[index] += float(values[index] or 0)
        return [round(value, digits) for value in result]

    def _aggregate_average_series(self, items: list[dict[str, Any]], key: str, digits: int = 4) -> list[float]:
        if not items:
            return [0]
        totals = self._aggregate_sum_series(items, key, digits + 2)
        return [round(value / max(len(items), 1), digits) for value in totals]

    def _aggregate_active_sku_series(self, items: list[dict[str, Any]], key: str = "series_units") -> list[int]:
        if not items:
            return [0]
        size = len(items[0].get(key, []))
        if not size:
            return [0]
        result = [0] * size
        for item in items:
            values = item.get(key, [])
            for index in range(min(size, len(values))):
                if float(values[index] or 0) > 0.01:
                    result[index] += 1
        return result

    def _aggregate_ratio_series(self, numerator: list[float], denominator: list[float], digits: int = 4) -> list[float]:
        size = max(len(numerator), len(denominator), 1)
        result: list[float] = []
        for index in range(size):
            num = float(numerator[index] if index < len(numerator) else 0)
            den = float(denominator[index] if index < len(denominator) else 0)
            result.append(round(num / den, digits) if den else 0)
        return result

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


mock_service = MockDashboardService()
