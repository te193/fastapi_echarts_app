import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from etl.dashboard_daily_update import COLUMN_COMMENTS

from .services.dashboard_db import dashboard_service
from .services.price_review_data import price_review_service


BASE_DIR = Path(__file__).resolve().parent
TWO_DECIMAL_EXPORT_COLUMNS = {
    "limit_price",
    "limit_price_10",
    "limit_price_35",
    "margin_price_35",
    "margin_price_10",
}

app = FastAPI(title="产品分层看板", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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


@app.get("/api/detail")
def api_detail(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    over_limit: str = Query(default="all"),
    daily_sales_band: str = Query(default="all"),
    margin_band: str = Query(default="all"),
    keyword: str = Query(default=""),
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
    return dashboard_service.get_detail_payload(filters, page=page, page_size=page_size)


@app.get("/api/detail/export")
def api_detail_export(
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


@app.get("/api/price-review/top-lists")
def api_price_review_top_lists(filters: dict = Depends(price_review_filters)) -> dict:
    return price_review_service.get_top_lists_payload(**filters)


@app.get("/api/price-review/skus")
def api_price_review_skus(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    filters: dict = Depends(price_review_filters),
) -> dict:
    return price_review_service.get_sku_list_payload(page=page, page_size=page_size, **filters)


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
    filters: dict = Depends(price_review_filters),
) -> StreamingResponse:
    rows = price_review_service.get_sku_list_export_payload(**filters)
    date_label = filters["adjust_date"].isoformat() if filters.get("adjust_date") else "latest"
    filename = f"price_review_skus_{date_label}_{filters['compare_days']}d.csv"
    return _write_price_review_csv(rows, _SKU_EXPORT_COLUMNS, filename)
