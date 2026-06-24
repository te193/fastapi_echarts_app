import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from etl.dashboard_daily_update import COLUMN_COMMENTS

from .services.dashboard_db import dashboard_service
from .services.price_review_data import price_review_service
from .services.replenishment_data import replenishment_service


BASE_DIR = Path(__file__).resolve().parent
TWO_DECIMAL_EXPORT_COLUMNS = {
    "limit_price",
    "limit_price_10",
    "limit_price_35",
    "margin_price_35",
    "margin_price_10",
}
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")

app = FastAPI(title="产品分层看板", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class AdjustmentDayNotePayload(BaseModel):
    note: str = ""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def csv_cell_value(value, column: str | None = None):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if column in TWO_DECIMAL_EXPORT_COLUMNS:
        return f"{Decimal(str(value)):.2f}"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(CSV_FORMULA_PREFIXES):
            return "\t" + value
    return value


def csv_header_value(column: str) -> str:
    return COLUMN_COMMENTS.get(column, column)


def build_filters(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
) -> dict:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "site": site,
        "store": store,
        "over_limit": over_limit,
        "daily_sales_band": daily_sales_band,
        "margin_band": margin_band,
        "keyword": keyword,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"page": "dashboard", "title": "产品分层看板"},
    )


@app.get("/layers", response_class=HTMLResponse)
def layers_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "layers.html",
        {"page": "layers", "title": "产品分层分布"},
    )


@app.get("/matrix", response_class=HTMLResponse)
def matrix_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "matrix.html",
        {"page": "matrix", "title": "日销毛利率矩阵"},
    )


@app.get("/detail", response_class=HTMLResponse)
def detail_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "detail.html",
        {"page": "detail", "title": "产品数据明细"},
    )


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "alerts.html",
        {"page": "alerts", "title": "异常预警工作台"},
    )


@app.get("/opportunities", response_class=HTMLResponse)
def opportunities_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {"page": "opportunities", "title": "机会 SKU 池"},
    )


@app.get("/inventory-weekly", response_class=HTMLResponse)
def inventory_weekly_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "inventory_weekly.html",
        {"page": "inventory_weekly", "title": "库存周报"},
    )


@app.get("/replenishment", response_class=HTMLResponse)
def replenishment_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "replenishment.html",
        {"page": "replenishment", "title": "补货计划"},
    )


@app.get("/api/meta")
def api_meta() -> dict:
    return dashboard_service.get_meta()


@app.get("/api/dashboard")
def api_dashboard(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
) -> dict:
    filters = build_filters(
        start_date=start_date,
        end_date=end_date,
        site=site,
        store=store,
        over_limit=over_limit,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
    )
    return dashboard_service.get_dashboard_payload(filters)


@app.get("/api/dashboard/monthly-goals")
def api_dashboard_monthly_goals() -> dict:
    return dashboard_service.get_monthly_goals_payload()


@app.get("/api/alerts")
def api_alerts(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
    alert_type: str = Query(default="all"),
    compare_days: int = Query(default=7, ge=7, le=90),
    comparison_code: str = Query(default=""),
    comparison_mode: str = Query(default="days"),
    previous_month: str = Query(default=""),
    recent_month: str = Query(default=""),
    sales_trend: str = Query(default="all"),
    rank_trend: str = Query(default="all"),
    margin_status: str = Query(default="all"),
    stock_status: str = Query(default="all"),
    transition_filter: str = Query(default=""),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    filters = build_filters(
        start_date=start_date,
        end_date=end_date,
        site=site,
        store=store,
        over_limit=over_limit,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
    )
    return dashboard_service.get_alerts_payload(
        filters,
        alert_type=alert_type,
        compare_days=compare_days,
        comparison_code=comparison_code,
        comparison_mode=comparison_mode,
        previous_month=previous_month,
        recent_month=recent_month,
        sales_trend=sales_trend,
        rank_trend=rank_trend,
        margin_status=margin_status,
        stock_status=stock_status,
        transition_filter=transition_filter,
        sort_field=sort_field,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )


@app.get("/api/alerts/export")
def api_alerts_export(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
    alert_type: str = Query(default="all"),
    compare_days: int = Query(default=7, ge=7, le=90),
    comparison_code: str = Query(default=""),
    comparison_mode: str = Query(default="days"),
    previous_month: str = Query(default=""),
    recent_month: str = Query(default=""),
    sales_trend: str = Query(default="all"),
    rank_trend: str = Query(default="all"),
    margin_status: str = Query(default="all"),
    stock_status: str = Query(default="all"),
    transition_filter: str = Query(default=""),
) -> StreamingResponse:
    filters = build_filters(
        start_date=start_date,
        end_date=end_date,
        site=site,
        store=store,
        over_limit=over_limit,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
    )
    payload = dashboard_service.get_alerts_export_payload(
        filters,
        alert_type=alert_type,
        compare_days=compare_days,
        comparison_code=comparison_code,
        comparison_mode=comparison_mode,
        previous_month=previous_month,
        recent_month=recent_month,
        sales_trend=sales_trend,
        rank_trend=rank_trend,
        margin_status=margin_status,
        stock_status=stock_status,
        transition_filter=transition_filter,
    )

    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "统计周期", "对比周期", "类型", "MSKU", "店铺", "国家",
        "销量趋势", "近期总销量", "近期日均销量", "对比总销量", "对比日均销量",
        "近期销售额", "近期日均销售额", "对比销售额", "对比日均销售额",
        "排名趋势", "毛利", "库存",
    ])
    for item in payload["items"]:
        writer.writerow(
            [
                payload["window"],
                payload["comparison_window"],
                csv_cell_value(item.get("label")),
                csv_cell_value(item.get("title")),
                csv_cell_value(item.get("store")),
                csv_cell_value(item.get("country")),
                csv_cell_value(item.get("sales_text")),
                csv_cell_value(item.get("recent_qty")),
                csv_cell_value(item.get("recent_daily_sales")),
                csv_cell_value(item.get("previous_qty")),
                csv_cell_value(item.get("previous_daily_sales")),
                csv_cell_value(item.get("recent_sales_amount")),
                csv_cell_value(item.get("recent_daily_sales_amount")),
                csv_cell_value(item.get("previous_sales_amount")),
                csv_cell_value(item.get("previous_daily_sales_amount")),
                csv_cell_value(item.get("rank_text")),
                csv_cell_value(item.get("margin_text")),
                csv_cell_value(item.get("stock_text")),
            ]
        )

    filename = f"alerts_{payload.get('comparison_code') or str(payload['compare_days']) + 'd'}_{date.today().isoformat()}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/opportunities")
def api_opportunities(
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    country: str = Query(default="all"),
    over_limit: str = Query(default="no"),
    keyword: str = Query(default=""),
    opportunity_type: str = Query(default="all"),
    compare_days: int = Query(default=14, ge=7, le=90),
    comparison_code: str = Query(default=""),
    comparison_mode: str = Query(default="days"),
    previous_month: str = Query(default=""),
    recent_month: str = Query(default=""),
    stock_status: str = Query(default="all"),
    transition_filter: str = Query(default=""),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    filters = build_filters(
        start_date=None,
        end_date=None,
        site=country if country != "all" else site,
        store=store,
        over_limit=over_limit,
        daily_sales_band="all",
        margin_band="all",
        keyword=keyword,
    )
    return dashboard_service.get_opportunities_payload(
        filters,
        opportunity_type=opportunity_type,
        compare_days=compare_days,
        comparison_code=comparison_code,
        comparison_mode=comparison_mode,
        previous_month=previous_month,
        recent_month=recent_month,
        stock_status=stock_status,
        transition_filter=transition_filter,
        sort_field=sort_field,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )


@app.get("/api/opportunities/export")
def api_opportunities_export(
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    country: str = Query(default="all"),
    over_limit: str = Query(default="no"),
    keyword: str = Query(default=""),
    opportunity_type: str = Query(default="all"),
    compare_days: int = Query(default=14, ge=7, le=90),
    comparison_code: str = Query(default=""),
    comparison_mode: str = Query(default="days"),
    previous_month: str = Query(default=""),
    recent_month: str = Query(default=""),
    stock_status: str = Query(default="all"),
    transition_filter: str = Query(default=""),
) -> StreamingResponse:
    filters = build_filters(
        start_date=None,
        end_date=None,
        site=country if country != "all" else site,
        store=store,
        over_limit=over_limit,
        daily_sales_band="all",
        margin_band="all",
        keyword=keyword,
    )
    payload = dashboard_service.get_opportunities_export_payload(
        filters,
        opportunity_type=opportunity_type,
        compare_days=compare_days,
        comparison_code=comparison_code,
        comparison_mode=comparison_mode,
        previous_month=previous_month,
        recent_month=recent_month,
        stock_status=stock_status,
        transition_filter=transition_filter,
    )

    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "统计周期", "对比周期", "机会类型", "机会分", "MSKU", "店铺", "国家",
        "日销", "销量变化", "销售额", "毛利率", "毛利润", "排名变化",
        "Sessions", "转化率", "FBA可售", "可售天数", "ACOS", "TACOS",
        "广告花费", "售价", "35毛利定价", "10毛利定价", "是否超限价", "建议动作",
    ])
    for item in payload["items"]:
        writer.writerow([
            payload["window"],
            payload["comparison_window"],
            csv_cell_value(item.get("label")),
            csv_cell_value(item.get("score")),
            csv_cell_value(item.get("msku")),
            csv_cell_value(item.get("store")),
            csv_cell_value(item.get("country")),
            csv_cell_value(item.get("daily_sales")),
            csv_cell_value(item.get("sales_text")),
            csv_cell_value(item.get("scoped_revenue")),
            csv_cell_value(item.get("margin")),
            csv_cell_value(item.get("profit")),
            csv_cell_value(item.get("rank_text")),
            csv_cell_value(item.get("recent_sessions")),
            csv_cell_value(item.get("conversion")),
            csv_cell_value(item.get("fba_sellable_inventory")),
            csv_cell_value(item.get("sellable_days")),
            csv_cell_value(item.get("acos")),
            csv_cell_value(item.get("tacos")),
            csv_cell_value(item.get("ad_spend")),
            csv_cell_value(item.get("current_price")),
            csv_cell_value(item.get("limit_price_35")),
            csv_cell_value(item.get("limit_price_10")),
            "是" if item.get("over_limit") else "否",
            csv_cell_value(item.get("suggested_action")),
        ])

    filename = f"opportunities_{payload['compare_days']}d_{date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/inventory-weekly/overview")
def api_inventory_weekly_overview(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
) -> dict:
    filters = build_filters(start_date=start_date, end_date=end_date, site=site, store=store, keyword=keyword)
    return dashboard_service.get_inventory_weekly_overview(filters)


@app.get("/api/inventory-weekly/trends")
def api_inventory_weekly_trends(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
) -> dict:
    filters = build_filters(start_date=start_date, end_date=end_date, site=site, store=store, keyword=keyword)
    return dashboard_service.get_inventory_weekly_trends(filters)


@app.get("/api/inventory-weekly/details")
def api_inventory_weekly_details(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    warning_status: str = Query(default="all"),
    metric: str = Query(default="all"),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    filters = build_filters(start_date=start_date, end_date=end_date, site=site, store=store, keyword=keyword)
    return dashboard_service.get_inventory_weekly_details(
        filters,
        warning_status=warning_status,
        metric=metric,
        sort_field=sort_field,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )


@app.get("/api/inventory-weekly/export")
def api_inventory_weekly_export(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    warning_status: str = Query(default="all"),
    metric: str = Query(default="all"),
) -> StreamingResponse:
    filters = build_filters(start_date=start_date, end_date=end_date, site=site, store=store, keyword=keyword)
    payload = dashboard_service.get_inventory_weekly_export_payload(
        filters,
        warning_status=warning_status,
        metric=metric,
    )
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "周开始", "周结束", "快照日期", "站点", "店铺", "MSKU", "可用数量", "可用成本",
        "在途数量", "在途成本", "在仓数量", "在仓成本", "采购数量", "采购成本", "是否预警", "预警指标",
    ])
    metric_labels = {"available": "可用", "transit": "在途", "warehouse": "在仓", "plan": "采购"}
    for item in payload["items"]:
        writer.writerow([
            csv_cell_value(item.get("week_start")),
            csv_cell_value(item.get("week_end")),
            csv_cell_value(item.get("snapshot_date")),
            csv_cell_value(item.get("site")),
            csv_cell_value(item.get("store")),
            csv_cell_value(item.get("msku")),
            csv_cell_value(item.get("available_quantity")),
            csv_cell_value(item.get("available_cost")),
            csv_cell_value(item.get("transit_quantity")),
            csv_cell_value(item.get("transit_cost")),
            csv_cell_value(item.get("warehouse_quantity")),
            csv_cell_value(item.get("warehouse_cost")),
            csv_cell_value(item.get("plan_quantity")),
            csv_cell_value(item.get("plan_cost")),
            "是" if item.get("warning") else "否",
            "、".join(metric_labels.get(key, key) for key in item.get("warning_metrics", [])),
        ])
    filename = f"inventory_weekly_{date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/replenishment")
def api_replenishment(
    snapshot_date: str = Query(default=""),
    level: str = Query(default="all"),
    category: str = Query(default="all"),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    category_period_days: int = Query(default=30),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    return replenishment_service.get_payload(
        snapshot_date=snapshot_date,
        level=level,
        category=category,
        site=site,
        store=store,
        keyword=keyword,
        category_period_days=category_period_days,
        sort_field=sort_field,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )


@app.get("/api/replenishment/export")
def api_replenishment_export(
    snapshot_date: str = Query(default=""),
    level: str = Query(default="all"),
    category: str = Query(default="all"),
    category_period_days: int = Query(default=30),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
) -> StreamingResponse:
    payload = replenishment_service.get_export_payload(
        snapshot_date=snapshot_date,
        level=level,
        category=category,
        category_period_days=category_period_days,
        site=site,
        store=store,
        keyword=keyword,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    columns = payload["columns"]
    writer.writerow([column["label"] for column in columns])
    for row in payload["rows"]:
        writer.writerow([csv_cell_value(row.get(column["name"]), column["name"]) for column in columns])
    filename = f"replenishment_{payload.get('snapshot_date') or snapshot_date or date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/replenishment/country-metrics")
def api_replenishment_country_metrics(
    snapshot_date: str = Query(default=""),
    site: str = Query(default=""),
    store: str = Query(default=""),
    msku: str = Query(default=""),
    period_days: int = Query(default=30),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
) -> dict:
    return replenishment_service.get_country_metrics(
        snapshot_date=snapshot_date,
        site=site,
        store=store,
        msku=msku,
        period_days=period_days,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )


@app.get("/api/replenishment/level-flow")
def api_replenishment_level_flow(
    snapshot_date: str = Query(default=""),
    level: str = Query(default="all"),
    flow_type: str = Query(default="all"),
    category: str = Query(default="all"),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    category_period_days: int = Query(default=30),
) -> dict:
    return replenishment_service.get_level_flow(
        snapshot_date=snapshot_date,
        level=level,
        flow_type=flow_type,
        category=category,
        site=site,
        store=store,
        keyword=keyword,
        category_period_days=category_period_days,
    )


@app.get("/api/detail")
def api_detail(
    request: Request,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
) -> dict:
    filters = build_filters(
        start_date=start_date,
        end_date=end_date,
        site=site,
        store=store,
        over_limit=over_limit,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
    )
    filters["column_filters"] = price_review_column_filters(request)
    return dashboard_service.get_detail_payload(
        filters,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )


@app.get("/api/detail/export")
def api_detail_export(
    request: Request,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
) -> StreamingResponse:
    filters = build_filters(
        start_date=start_date,
        end_date=end_date,
        site=site,
        store=store,
        over_limit=over_limit,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
    )
    filters["column_filters"] = price_review_column_filters(request)
    payload = dashboard_service.get_detail_export_payload(filters)
    columns = payload["columns"]

    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([csv_header_value(column) for column in columns])
    for row in payload["rows"]:
        writer.writerow([csv_cell_value(row.get(column), column) for column in columns])

    filename = f"product_detail_raw_{payload['start_date']}_{payload['end_date']}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/detail/{item_id}")
def api_detail_record(
    item_id: str,
    trend_days: int = Query(default=30, ge=7, le=30),
) -> dict:
    return dashboard_service.get_detail_record(item_id, trend_days)


@app.get("/price-review", response_class=HTMLResponse)
def price_review_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "price_review.html",
        {"page": "price_review", "title": "调价效果复盘"},
    )


@app.get("/price-adjustments", response_class=HTMLResponse)
def price_adjustments_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "price_adjustments.html",
        {"page": "price_adjustments", "title": "调价日历"},
    )


@app.get("/api/price-adjustments/daily-counts")
def api_price_adjustments_daily_counts(
    days: int = Query(default=30, ge=7, le=90),
) -> dict:
    return {"items": price_review_service.get_daily_adjustment_counts(days=days)}


@app.put("/api/price-adjustments/daily-notes/{adjust_date}")
def api_price_adjustments_daily_note(
    adjust_date: str,
    payload: AdjustmentDayNotePayload,
) -> dict:
    parsed_date = _parse_date(adjust_date)
    if parsed_date is None:
        raise HTTPException(status_code=400, detail="Invalid adjust_date")
    try:
        note = price_review_service.save_adjustment_day_note(parsed_date, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"date": parsed_date.isoformat(), "note": note}


def price_review_filters(
    adjust_date: Optional[str] = Query(default=None),
    compare_days: int = Query(default=14, ge=7, le=28),
    country: str = Query(default=""),
    drop_range: str = Query(default=""),
    risk_level: str = Query(default=""),
    store: str = Query(default=""),
    price_band: str = Query(default=""),
    adjustment_type: str = Query(default=""),
    keyword: str = Query(default=""),
) -> dict:
    return {
        "adjust_date": _parse_date(adjust_date),
        "compare_days": compare_days,
        "country": country,
        "drop_range": drop_range,
        "risk_level": risk_level,
        "store": store,
        "price_band": price_band,
        "adjustment_type": adjustment_type,
        "keyword": keyword,
    }


def price_review_column_filters(request: Request) -> dict[str, str]:
    return {
        key[3:]: value
        for key, value in request.query_params.items()
        if key.startswith("cf_") and value not in {"", "all"}
    }


@app.get("/api/price-review/overview")
def api_price_review_overview(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_overview_payload(**filters)


@app.get("/api/price-review/drop-range")
def api_price_review_drop_range(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_drop_range_payload(**filters)


@app.get("/api/price-review/matrices")
def api_price_review_matrices(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_matrices_payload(**filters)


@app.get("/api/price-review/countries")
def api_price_review_countries(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_country_payload(**filters)


@app.get("/api/price-review/second-adjustments")
def api_price_review_second_adjustments(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_second_adjustments_payload(**filters)


@app.get("/api/price-review/top-lists")
def api_price_review_top_lists(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_top_lists_payload(**filters)


@app.get("/api/price-review/skus")
def api_price_review_skus(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    filters: dict = Depends(price_review_filters),
) -> dict:
    filters = dict(filters)
    filters["column_filters"] = price_review_column_filters(request)
    return price_review_service.get_sku_list_payload(
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_dir=sort_dir,
        **filters,
    )


_TOP_LIST_COLUMNS = [
    ("类型", "类型"),
    ("国家", "country"),
    ("店铺", "store"),
    ("MSKU", "msku"),
    ("品名", "product_name"),
    ("调价类型", "adjustment_type"),
    ("上次调价日期", "previous_adjust_date"),
    ("前销量", "sales_before"),
    ("后销量", "sales_after"),
    ("销量变化", "sales_change"),
    ("前日销", "daily_sales_before"),
    ("后日销", "daily_sales_after"),
    ("日销变化", "daily_sales_change"),
    ("毛利润变化", "profit_change"),
    ("后毛利率", "margin_after"),
    ("排名变化", "rank_change"),
    ("风险等级", "risk_level"),
    ("问题标签", "issue_tags"),
]

_SKU_EXPORT_COLUMNS = [
    ("国家", "country"),
    ("店铺", "store"),
    ("MSKU", "msku"),
    ("品名", "product_name"),
    ("调价类型", "adjustment_type"),
    ("上次调价日期", "previous_adjust_date"),
    ("调价前价格", "price_before"),
    ("调价后价格", "price_after"),
    ("降幅", "drop_ratio"),
    ("降幅区间", "drop_range"),
    ("价格带", "price_band"),
    ("前销量", "sales_before"),
    ("后销量", "sales_after"),
    ("销量变化", "sales_change"),
    ("前日销", "daily_sales_before"),
    ("后日销", "daily_sales_after"),
    ("前销售额", "revenue_before"),
    ("后销售额", "revenue_after"),
    ("前毛利润", "profit_before"),
    ("后毛利润", "profit_after"),
    ("前毛利率", "margin_before"),
    ("后毛利率", "margin_after"),
    ("毛利率变化", "margin_change"),
    ("前Sessions", "sessions_before"),
    ("后Sessions", "sessions_after"),
    ("前ACOS", "acos_before"),
    ("后ACOS", "acos_after"),
    ("前TACOS", "tacos_before"),
    ("后TACOS", "tacos_after"),
    ("前CPC", "cpc_before"),
    ("后CPC", "cpc_after"),
    ("调前排名", "rank_before"),
    ("调后排名", "rank_after"),
    ("排名变化", "rank_change"),
    ("调前销量分层", "sales_band_before"),
    ("调后销量分层", "sales_band_after"),
    ("调前日销分层", "daily_sales_band_before"),
    ("调后日销分层", "daily_sales_band_after"),
    ("调前毛利率分层", "margin_band_before"),
    ("调后毛利率分层", "margin_band_after"),
    ("调前排名分层", "rank_band_before"),
    ("调后排名分层", "rank_band_after"),
    ("风险等级", "risk_level"),
    ("问题标签", "issue_tags"),
    ("建议动作", "suggested_action"),
]


def _write_price_review_csv(rows: list[dict], columns: list[tuple[str, str]], filename: str) -> StreamingResponse:
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([csv_cell_value(row.get(key)) for _, key in columns])
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/price-review/top-lists/export")
def api_price_review_top_lists_export(
    filters: dict = Depends(price_review_filters),
) -> StreamingResponse:
    rows = price_review_service.get_top_lists_export_payload(**filters)
    date_label = filters["adjust_date"].isoformat() if filters.get("adjust_date") else "latest"
    filename = f"price_review_top_lists_{date_label}_{filters['compare_days']}d.csv"
    return _write_price_review_csv(rows, _TOP_LIST_COLUMNS, filename)


@app.get("/api/price-review/skus/export")
def api_price_review_skus_export(
    request: Request,
    filters: dict = Depends(price_review_filters),
) -> StreamingResponse:
    filters = dict(filters)
    filters["column_filters"] = price_review_column_filters(request)
    rows = price_review_service.get_sku_list_export_payload(**filters)
    date_label = filters["adjust_date"].isoformat() if filters.get("adjust_date") else "latest"
    filename = f"price_review_skus_{date_label}_{filters['compare_days']}d.csv"
    return _write_price_review_csv(rows, _SKU_EXPORT_COLUMNS, filename)
