import csv
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .services.dashboard_db import dashboard_service


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="产品分层看板", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def csv_cell_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


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
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in payload["rows"]:
        writer.writerow({column: csv_cell_value(row.get(column)) for column in columns})

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
