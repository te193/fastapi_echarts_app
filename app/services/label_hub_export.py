from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from .label_hub_detail_data import label_hub_detail_service


Column = tuple[str, str | Callable[[dict[str, Any], dict[str, Any]], Any], Callable[[Any], Any] | None]


def _period_label(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d+)d", text)
    return f"{match.group(1)}天" if match else (text or "经营周期")


def _plain(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple, set)):
        return " / ".join(str(item) for item in value if item not in (None, ""))
    return value


def _percent(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value) * 100:.2f}%"


def _label_count(row: dict[str, Any], _: dict[str, Any]) -> int:
    return len(row.get("labels") or [])


def _constant(field: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    return lambda _row, filters: filters.get(field, "")


def _dimension(row: dict[str, Any], filters: dict[str, Any]) -> str:
    return "国家明细" if filters.get("detail_view") == "country" else "MSKU维度"


def _columns(detail_view: str, metric_period: str) -> list[Column]:
    period = _period_label(metric_period)
    columns: list[Column] = [
        ("数据日期", _constant("data_date"), None),
        ("经营周期", lambda _row, _filters: period, None),
        ("明细维度", _dimension, None),
    ]
    if detail_view == "country":
        columns.extend([
            ("国家", "country", None),
            ("国家类别", "country_category", None),
            ("店铺", "store", None),
            ("MSKU", "msku", None),
            ("SKU", "sku", None),
            ("排名", "ranking", None),
            ("当前售价", "listing_price", None),
            ("售价币种", "listing_currency", None),
            ("当前售价（人民币）", "listing_price_cny", None),
            ("价格快照日期", "price_snapshot_date", None),
            ("35%毛利限价", "limit_price_35", None),
            ("10%毛利限价", "limit_price_10", None),
            ("当前毛利区间", "price_margin_interval", None),
        ])
    else:
        columns.extend([
            ("国家类别", "country_category", None),
            ("店铺", "store", None),
            ("MSKU", "msku", None),
            ("SKU示例", "local_sku_sample", None),
            ("覆盖国家数", "country_count", None),
            ("覆盖国家", "countries", None),
        ])
    columns.extend([
        ("当前标签", "current_label", None),
        ("销售角色", "sales_role", None),
        ("生命周期标签", "lifecycle_label", None),
        ("国家销售角色标签", "country_sales_role_label", None),
        ("站点生命周期标签", "site_lifecycle_label", None),
        ("价格标签", "price_label", None),
        ("站点状态标签", "site_status_label", None),
        ("角色诊断", "role_diagnostic_summary", None),
        ("角色诊断数量", "role_diagnostic_count", None),
        ("标签画像", "label_summary", None),
        ("标签数量", _label_count, None),
        ("是否标签冲突", "conflict", None),
        ("问题提示", "issue_labels", None),
        ("问题代码", "issue_codes", None),
        ("动销趋势", "sales_trend", None),
        ("动销趋势变化率", "sales_trend_ratio", _percent),
        ("经营数据状态", "data_status", None),
        ("是否有经营数据", "metric_present", None),
        ("日均销量", "daily_sales", None),
        (f"{period}销量", "sales_qty", None),
        (f"{period}销售额", "sales_amount", None),
        ("未税销售额", "sales_amount_ex_tax", None),
        ("订单毛利润", "order_gross_profit", None),
        ("订单毛利率", "order_gross_margin", _percent),
        ("结算毛利润", "settlement_gross_profit", None),
        ("结算毛利率", "settlement_gross_margin", _percent),
        ("净额", "net_amount", None),
        ("可售库存", "ending_inventory_qty", None),
        ("广告花费", "ad_spend", None),
        ("广告销售额", "ad_sales", None),
        ("广告订单量", "ad_orders", None),
        ("广告点击量", "ad_clicks", None),
        ("广告曝光量", "ad_impressions", None),
        ("ACOS", "acos", _percent),
        ("TACOS", "tacos", _percent),
        ("访客会话数", "sessions_total", None),
        ("退货数量", "return_count", None),
        ("退货金额", "return_amount", None),
    ])
    return columns


def _cell(row: dict[str, Any], filters: dict[str, Any], column: Column) -> Any:
    _, source, formatter = column
    value = source(row, filters) if callable(source) else row.get(source)
    return formatter(value) if formatter else _plain(value)


def _csv_chunks(columns: list[Column], rows: list[dict[str, Any]], filters: dict[str, Any]) -> Iterable[str]:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    yield "\ufeff"
    writer.writerow([header for header, _, _ in columns])
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in rows:
        writer.writerow([_cell(row, filters, column) for column in columns])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


class LabelHubExportService:
    def __init__(self, detail_service: Any) -> None:
        self._detail_service = detail_service

    def build_export(self, **filters: Any) -> tuple[str, Iterable[str]]:
        detail_view = str(filters.get("detail_view") or "business_unit")
        metric_period = str(filters.get("metric_period") or "30d")
        payload = self._detail_service.get_export_rows(**filters)
        columns = _columns(detail_view, metric_period)
        export_date = str(filters.get("data_date") or date.today().isoformat())
        dimension = "国家明细" if detail_view == "country" else "MSKU维度"
        filename = f"标签看板-{dimension}-{export_date}.csv"
        return filename, _csv_chunks(columns, list(payload.get("rows") or []), filters)


label_hub_export_service = LabelHubExportService(label_hub_detail_service)
