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
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill
from pydantic import BaseModel

from etl.dashboard_daily_update import COLUMN_COMMENTS

from .services.dashboard_db import dashboard_service
from .services.country_label_hub_data import country_label_hub_service
from .services.label_hub_data import label_hub_service
from .services.label_hub_change_data import label_hub_change_service
from .services.price_review_data import price_review_service
from .services.replenishment_data import replenishment_service
from .services.replenishment_tracking_data import replenishment_tracking_service
from .services.replenishment_tracking_summary_data import replenishment_tracking_summary_service
from .services.return_goods_data import return_goods_service


BASE_DIR = Path(__file__).resolve().parent
TWO_DECIMAL_EXPORT_COLUMNS = {
    "limit_price",
    "limit_price_10",
    "limit_price_35",
    "margin_price_35",
    "margin_price_10",
}
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")
REPLENISHMENT_EXPORT_HEADER_COMMENTS = {
    "fba_local_quantity": "FBA本地 = FBA总库存+本地库存",
    "total": "FBA总库存 = FBA可售+FBA预留+待调仓+标发在途+入库中",
    "available_total": "FBA可用库存 = FBA可售+待调仓+FBA预留+入库中（此字段可在业务配置中自定义）",
    "afn_fulfillable_quantity": "FBA可售库存 = afn fulfillable",
    "stock_up_num": "FBA在途 = 实际在途发货单发货数量-签收数量",
    "afn_unsellable_quantity": "FBA不可售 = Unfulfillable",
    "sc_quantity_local_valid": (
        "本地可用 = 配对SKU的可用量+可用锁定量+期望可用量，"
        "仅组合产品包含期望可用量；点击设置-业务配置-补货建议中自定义"
    ),
    "sc_quantity_purchase_shipping": "采购在途 = 目的仓为本地仓的调拨单待收货量",
    "sc_quantity_purchase_plan": (
        "采购计划 = 配对SKU相关采购计划单待采购量统计数据："
        "采购计划（待审批）+采购计划（待采购）"
    ),
    "sc_quantity_local_qc": (
        "本地质检 = 配对SKU的待检待上架量（汇总SKU无绑定FNSKU数量与SKU+FNSKU数量）"
    ),
    "local_quantity": "本地库存 = 本地可用+采购在途+采购计划+本地质检",
    "final_sales_3d": (
        "黄色提醒规则：仅针对紧急补货、建议补货和计划补货的有效行；"
        "当7天销量不少于10，且3天销量达到7天销量的70%时，整行标黄。"
    ),
}
REPLENISHMENT_SALES_CONCENTRATION_FILL = PatternFill(
    fill_type="solid",
    fgColor="FFF2CC",
)
CSV_HEADER_LABELS = {
    "snapshot_date": "快照日期",
    "period_start": "周期开始",
    "period_end": "周期结束",
    "item_key": "商品键",
    "stat_period": "统计周期",
    "dt_year": "年",
    "dt_week": "周",
    "dt_month": "月",
    "dt_date": "日期",
    "seller_name_new": "店铺",
    "seller_name": "原店铺",
    "seller_sku_adj": "MSKU",
    "seller_sku": "卖家SKU",
    "country_category": "国家分组",
    "country": "国家",
    "local_sku": "SKU",
    "sales_qty": "销量",
    "sales_amount": "销售额",
    "sales_amount_ex_tax": "不含税销售额",
    "order_gross_profit": "毛利润",
    "raw_order_gross_profit": "原始毛利润",
    "order_gross_margin": "毛利率",
    "margin_band": "毛利分层",
    "settlement_gross_profit": "结算毛利润",
    "filter_flag": "纳入筛选",
    "current_price_cny": "当前售价(CNY)",
    "price_currency": "币种",
    "current_price": "当前售价",
    "limit_price": "限价",
    "limit_price_10": "10毛利定价",
    "limit_price_adj": "调整后限价",
    "limit_price_without_ad": "不含广告限价",
    "over_limit_flag": "是否超限价",
    "shipping_method": "发货方式",
    "target_margin": "目标毛利率",
    "in_stock_days": "有货天数",
    "stat_days": "统计天数",
    "abnormal_days": "异常天数",
    "all_abnormal_flag": "全周期异常",
    "abnormal_flag_count": "异常标记次数",
    "daily_sales": "日销",
    "daily_sales_in_stock_days": "有货日销",
    "daily_sales_in_stock_band": "有货日销分层",
    "daily_sales_band": "日销分层",
    "ad_spend": "广告花费",
    "ad_orders": "广告订单量",
    "ad_sales": "广告销售额",
    "ad_clicks": "广告点击量",
    "ad_impressions": "广告曝光量",
    "acos": "ACOS",
    "tacos": "TACOS",
    "ctr": "CTR",
    "sessions_total": "Sessions",
    "ranking": "排名",
    "return_count": "退货量",
    "return_amount": "退货额",
    "net_amount": "净销售额",
    "afn_fulfillable_quantity": "AFN可售库存",
    "fba_total_inventory": "FBA总库存",
    "fba_total_inventory_cost": "FBA总库存成本",
    "fba_available_inventory": "FBA可用库存",
    "fba_available_inventory_cost": "FBA可用库存成本",
    "fba_sellable_inventory": "FBA可售库存",
    "pending_transfer": "预留调拨",
    "transferring_qty": "调拨在途",
    "pending_shipment": "待发货",
    "unsellable_inventory": "不可售库存",
    "planned_inbound": "计划入库",
    "actual_in_transit": "实际在途",
    "under_investigation": "调查中库存",
    "total_available_inventory": "总可用库存",
    "local_sellable_inventory": "本地可售库存",
    "local_stock_sellable_days": "本地可售天数",
    "price": "当前售价",
    "org_currency_icon": "币种",
    "price_cny": "售价(CNY)",
    "tax_inclusive_price": "含税限价",
    "tax_inclusive_price_noad": "不含广告限价",
    "tax_inclusive_price_adj": "调整后限价",
    "margin_price_35": "35毛利定价",
    "margin_price_10": "10毛利定价",
    "created_at": "创建时间",
    "updated_at": "更新时间",
}

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
    return COLUMN_COMMENTS.get(column) or CSV_HEADER_LABELS.get(column, column)


def xlsx_cell_value(value, column: str | None = None):
    if isinstance(value, Decimal):
        return value
    return csv_cell_value(value, column)


def is_replenishment_sales_concentrated(row: dict) -> bool:
    try:
        level_sort = int(row.get("support_replenish_level_sort") or 0)
        sales_3d = Decimal(str(row.get("final_sales_3d") or 0))
        sales_7d = Decimal(str(row.get("final_sales_7d") or 0))
        replenish_qty = Decimal(str(row.get("replenish_qty") or 0))
    except (ArithmeticError, TypeError, ValueError):
        return False

    asin_merge_flag = str(row.get("asin_merge_flag") or 0).strip().lower()
    is_asin_merged = asin_merge_flag in {"1", "1.0", "true", "yes", "是"}
    if level_sort not in (1, 2, 3):
        return False
    if is_asin_merged and replenish_qty == 0:
        return False
    if sales_7d < 10:
        return False
    return sales_3d * 10 >= sales_7d * 7


def build_replenishment_xlsx(payload: dict) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "补货计划"
    columns = payload["columns"]

    for column_index, column in enumerate(columns, start=1):
        cell = worksheet.cell(row=1, column=column_index, value=column["label"])
        comment_text = REPLENISHMENT_EXPORT_HEADER_COMMENTS.get(column["name"])
        if comment_text:
            cell.comment = Comment(comment_text, "看板系统")

    for row_index, row in enumerate(payload["rows"], start=2):
        highlight_row = is_replenishment_sales_concentrated(row)
        for column_index, column in enumerate(columns, start=1):
            cell = worksheet.cell(
                row=row_index,
                column=column_index,
                value=xlsx_cell_value(row.get(column["name"]), column["name"]),
            )
            if column["name"] in TWO_DECIMAL_EXPORT_COLUMNS and cell.value != "":
                cell.number_format = "0.00"
            if highlight_row:
                cell.fill = REPLENISHMENT_SALES_CONCENTRATION_FILL

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


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

@app.get("/replenishment-tracking", response_class=HTMLResponse)
def replenishment_tracking_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "replenishment_tracking.html",
        {"page": "replenishment_tracking", "title": "补货追踪"},
    )


@app.get("/return-goods", response_class=HTMLResponse)
def return_goods_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "return_goods.html",
        {"page": "return_goods", "title": "返场品"},
    )


@app.get("/sales-role", response_class=HTMLResponse)
def sales_role_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "sales_role.html",
        {"page": "sales_role", "title": "销售角色分析"},
    )


@app.get("/label-hub", response_class=HTMLResponse)
def label_hub_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "label_hub.html",
        {"page": "label_hub", "title": "标签看板"},
    )


@app.get("/country-label-hub", response_class=HTMLResponse)
def country_label_hub_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "country_label_hub.html",
        {"page": "country_label_hub", "title": "国家标签看板"},
    )


@app.get("/api/label-hub/meta")
def api_label_hub_meta() -> dict:
    return label_hub_service.get_meta()


@app.get("/api/label-hub")
def api_label_hub(
    data_date: str = "", country_category: str = "all", store: str = "all", keyword: str = "",
    parent_label_id: int = 0, compare_parent_id: int = 0, conditions: str = "", label_period: str = "all",
    metric_period: str = "30d", analysis_parent_ids: str = "", analysis_periods: str = "",
    sales_roles: str = "", sales_trends: str = "", daily_sales_bands: str = "", margin_bands: str = "", problem: str = "all",
    page: int = 1, page_size: int = 20, sort_field: str = "sales_amount", sort_dir: str = "desc",
) -> dict:
    try:
        return label_hub_service.get_payload(
            data_date=data_date, country_category=country_category, store=store, keyword=keyword,
            parent_label_id=parent_label_id, compare_parent_id=compare_parent_id,
            conditions=conditions, label_period=label_period, metric_period=metric_period,
            analysis_parent_ids=analysis_parent_ids, analysis_periods=analysis_periods,
            sales_roles=sales_roles, sales_trends=sales_trends,
            daily_sales_bands=daily_sales_bands, margin_bands=margin_bands, problem=problem,
            page=page, page_size=page_size, sort_field=sort_field, sort_dir=sort_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="标签数据暂不可用，请稍后重试") from exc


@app.get("/api/label-hub/msku")
def api_label_hub_msku(data_date: str, country_category: str, store: str, msku: str, metric_period: str = "30d") -> dict:
    try:
        return label_hub_service.get_msku_profile(data_date=data_date, country_category=country_category, store=store, msku=msku, metric_period=metric_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/label-hub/msku-country-profile")
def api_label_hub_msku_country_profile(
    country_category: str,
    store: str,
    msku: str,
    metric_period: str = "30d",
) -> dict:
    try:
        return country_label_hub_service.get_label_hub_country_profile(
            country_category=country_category,
            store=store,
            msku=msku,
            metric_period=metric_period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="国家画像暂不可用，请稍后重试") from exc


@app.get("/api/label-hub/changes")
def api_label_hub_changes(
    data_date: str = "", country_category: str = "all", store: str = "all", keyword: str = "",
    parent_label_id: int = 0, compare_parent_id: int = 0, conditions: str = "", label_period: str = "all",
    metric_period: str = "30d", analysis_parent_ids: str = "", analysis_periods: str = "",
    sales_trends: str = "", daily_sales_bands: str = "", margin_bands: str = "", problem: str = "all",
    transition_period: str = "", change_type: str = "all", page: int = 1, page_size: int = 20,
    sort_field: str = "change_type", sort_dir: str = "asc",
    layer_change_parent: int = 0, layer_change_bucket: str = "", layer_change_period: str = "all",
    layer_transition_from: str = "", layer_transition_to: str = "",
) -> dict:
    try:
        return label_hub_change_service.get_changes(
            data_date=data_date, country_category=country_category, store=store, keyword=keyword,
            parent_label_id=parent_label_id, compare_parent_id=compare_parent_id,
            conditions=conditions, label_period=label_period, metric_period=metric_period,
            analysis_parent_ids=analysis_parent_ids, analysis_periods=analysis_periods,
            sales_trends=sales_trends, daily_sales_bands=daily_sales_bands,
            margin_bands=margin_bands, problem=problem, transition_period=transition_period,
            change_type=change_type, page=page, page_size=page_size,
            sort_field=sort_field, sort_dir=sort_dir,
            layer_change_parent=layer_change_parent, layer_change_bucket=layer_change_bucket,
            layer_change_period=layer_change_period,
            layer_transition_from=layer_transition_from, layer_transition_to=layer_transition_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="标签变化数据暂不可用，请稍后重试") from exc


@app.get("/api/label-hub/msku-change")
def api_label_hub_msku_change(msku: str, transition_period: str = "30d") -> dict:
    try:
        return label_hub_change_service.get_msku_change(msku=msku, transition_period=transition_period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/country-label-hub/meta")
def api_country_label_hub_meta() -> dict:
    try:
        return country_label_hub_service.get_meta()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="国家标签元数据暂不可用，请稍后重试") from exc


@app.get("/api/country-label-hub")
def api_country_label_hub(
    data_date: str = "", metric_period: str = "30d", country_category: str = "all",
    store: str = "all", keyword: str = "", conditions: str = "", label_periods: str = "",
    sales_trends: str = "", daily_sales_bands: str = "", margin_bands: str = "",
    problem: str = "all", page: int = 1, page_size: int = 20,
    sort_field: str = "problem_priority", sort_dir: str = "desc",
) -> dict:
    try:
        return country_label_hub_service.get_payload(
            data_date=data_date, metric_period=metric_period, country_category=country_category,
            store=store, keyword=keyword, conditions=conditions, label_periods=label_periods,
            sales_trends=sales_trends, daily_sales_bands=daily_sales_bands,
            margin_bands=margin_bands, problem=problem, page=page, page_size=page_size,
            sort_field=sort_field, sort_dir=sort_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="国家标签数据暂不可用，请稍后重试") from exc


@app.get("/api/country-label-hub/msku")
def api_country_label_hub_msku(
    data_date: str, country: str, country_category: str, store: str, msku: str, metric_period: str = "30d",
) -> dict:
    try:
        return country_label_hub_service.get_msku_profile(
            data_date=data_date, country=country, country_category=country_category, store=store,
            msku=msku, metric_period=metric_period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="国家标签画像暂不可用，请稍后重试") from exc


@app.get("/api/meta")
def api_meta() -> dict:
    return dashboard_service.get_meta()


@app.get("/api/sales-role/meta")
def api_sales_role_meta() -> dict:
    return dashboard_service.get_sales_role_meta()


@app.get("/api/sales-role")
def api_sales_role(
    period: str = "30d",
    country_category: str = "all",
    seller_name_new: str = "all",
    sales_role: str = "all",
    daily_sales_band: str = "all",
    margin_band: str = "all",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    sort_field: str = "sales_amount",
    sort_dir: str = "desc",
) -> dict:
    return dashboard_service.get_sales_role_payload(
        period=period,
        country_category=country_category,
        seller_name_new=seller_name_new,
        sales_role=sales_role,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )


@app.get("/api/sales-role/export")
def api_sales_role_export(
    period: str = "30d",
    country_category: str = "all",
    seller_name_new: str = "all",
    sales_role: str = "all",
    daily_sales_band: str = "all",
    margin_band: str = "all",
    keyword: str = "",
    sort_field: str = "sales_amount",
    sort_dir: str = "desc",
) -> StreamingResponse:
    payload = dashboard_service.get_sales_role_export_payload(
        period=period,
        country_category=country_category,
        seller_name_new=seller_name_new,
        sales_role=sales_role,
        daily_sales_band=daily_sales_band,
        margin_band=margin_band,
        keyword=keyword,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "销售角色", "国家类别", "店铺新", "MSKU", "SKU示例", "覆盖国家数", "覆盖国家",
        "销量", "日均销量", "销售额", "订单毛利额", "订单毛利率", "日销分层", "毛利率分层",
        "广告花费", "广告销售额", "ACOS", "TACOS",
    ])
    for row in payload["rows"]:
        writer.writerow([
            csv_cell_value(row.get("sales_role")),
            csv_cell_value(row.get("country_category")),
            csv_cell_value(row.get("seller_name_new")),
            csv_cell_value(row.get("seller_sku_adj")),
            csv_cell_value(row.get("local_sku_sample")),
            csv_cell_value(row.get("country_count")),
            csv_cell_value(row.get("countries")),
            csv_cell_value(row.get("sales_qty")),
            csv_cell_value(row.get("daily_sales")),
            csv_cell_value(row.get("sales_amount")),
            csv_cell_value(row.get("order_gross_profit")),
            csv_cell_value(row.get("order_gross_margin")),
            csv_cell_value(row.get("daily_sales_band")),
            csv_cell_value(row.get("margin_band")),
            csv_cell_value(row.get("ad_spend")),
            csv_cell_value(row.get("ad_sales")),
            csv_cell_value(row.get("acos")),
            csv_cell_value(row.get("tacos")),
        ])
    filename = f"sales_role_{period}_{date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/sales-role/lifecycle")
def api_sales_role_lifecycle(
    period: str = "30d",
    country_category: str = "all",
    seller_name_new: str = "all",
    lifecycle_label: str = "all",
    sales_role: str = "all",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    sort_field: str = "sales_amount",
    sort_dir: str = "desc",
) -> dict:
    return dashboard_service.get_sales_role_lifecycle_payload(
        period=period,
        country_category=country_category,
        seller_name_new=seller_name_new,
        lifecycle_label=lifecycle_label,
        sales_role=sales_role,
        keyword=keyword,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )


@app.get("/api/sales-role/lifecycle/export")
def api_sales_role_lifecycle_export(
    period: str = "30d",
    country_category: str = "all",
    seller_name_new: str = "all",
    lifecycle_label: str = "all",
    sales_role: str = "all",
    keyword: str = "",
    sort_field: str = "sales_amount",
    sort_dir: str = "desc",
) -> StreamingResponse:
    payload = dashboard_service.get_sales_role_lifecycle_export_payload(
        period=period,
        country_category=country_category,
        seller_name_new=seller_name_new,
        lifecycle_label=lifecycle_label,
        sales_role=sales_role,
        keyword=keyword,
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    output = io.StringIO(newline="")
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "生命周期", "销售角色", "国家类别", "店铺", "MSKU", "SKU示例", "覆盖国家数", "覆盖国家",
        "销量", "日均销量", "销售额", "订单毛利润", "订单毛利率", "标签周期", "销售角色周期",
        "广告花费", "广告销售额", "ACOS", "TACOS",
    ])
    for row in payload["rows"]:
        writer.writerow([
            csv_cell_value(row.get("lifecycle_label")),
            csv_cell_value(row.get("sales_role")),
            csv_cell_value(row.get("country_category")),
            csv_cell_value(row.get("seller_name_new")),
            csv_cell_value(row.get("seller_sku_adj")),
            csv_cell_value(row.get("local_sku_sample")),
            csv_cell_value(row.get("country_count")),
            csv_cell_value(row.get("countries")),
            csv_cell_value(row.get("sales_qty")),
            csv_cell_value(row.get("daily_sales")),
            csv_cell_value(row.get("sales_amount")),
            csv_cell_value(row.get("order_gross_profit")),
            csv_cell_value(row.get("order_gross_margin")),
            csv_cell_value(row.get("label_period")),
            csv_cell_value(row.get("sales_role_period")),
            csv_cell_value(row.get("ad_spend")),
            csv_cell_value(row.get("ad_sales")),
            csv_cell_value(row.get("acos")),
            csv_cell_value(row.get("tacos")),
        ])
    filename = f"sales_role_lifecycle_{period}_{date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)


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
    content = build_replenishment_xlsx(payload)
    filename = f"replenishment_{payload.get('snapshot_date') or snapshot_date or date.today().isoformat()}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


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


@app.get("/api/replenishment-tracking")
def api_replenishment_tracking(
    snapshot_date: str = Query(default=""),
    tracking_window_days: int = Query(default=7),
    level: str = Query(default="all"),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    status: str = Query(default="all"),
    sort_field: str = Query(default=""),
    sort_dir: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    category_period_days: int = Query(default=30),
) -> dict:
    return replenishment_tracking_service.get_payload(
        snapshot_date=snapshot_date,
        tracking_window_days=tracking_window_days,
        level=level,
        site=site,
        store=store,
        keyword=keyword,
        status=status,
        sort_field=sort_field,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
        category_period_days=category_period_days,
    )


@app.get("/api/replenishment-tracking/detail")
def api_replenishment_tracking_detail(
    snapshot_date: str = Query(default=""),
    tracking_window_days: int = Query(default=30),
    site: str = Query(default=""),
    store: str = Query(default=""),
    msku: str = Query(default=""),
) -> dict:
    return replenishment_tracking_service.get_detail(
        snapshot_date=snapshot_date,
        tracking_window_days=tracking_window_days,
        site=site,
        store=store,
        msku=msku,
    )


@app.get("/api/replenishment-tracking-summary")
def api_replenishment_tracking_summary(
    cutoff_date: str = Query(default=""),
    entry_batch_days: int = Query(default=30),
    level: str = Query(default="all"),
    purchase_status: str = Query(default="all"),
    fba_status: str = Query(default="all"),
    summary_stage: str = Query(default="all"),
    level_flow_stage: str = Query(default="all"),
    detail_stage: str = Query(default=""),
    category_period_days: int = Query(default=30),
    history_level: str = Query(default="all"),
    product_category: str = Query(default="all"),
    site: str = Query(default="all"),
    store: str = Query(default="all"),
    keyword: str = Query(default=""),
    order_keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    return replenishment_tracking_summary_service.get_payload(
        cutoff_date=cutoff_date,
        entry_batch_days=entry_batch_days,
        level=level,
        purchase_status=purchase_status,
        fba_status=fba_status,
        summary_stage=summary_stage,
        level_flow_stage=level_flow_stage,
        detail_stage=detail_stage,
        category_period_days=category_period_days,
        history_level=history_level,
        product_category=product_category,
        site=site,
        store=store,
        keyword=keyword,
        order_keyword=order_keyword,
        page=page,
        page_size=page_size,
    )


@app.get("/api/replenishment-tracking-summary/detail")
def api_replenishment_tracking_summary_detail(
    cutoff_date: str = Query(default=""),
    site: str = Query(default=""),
    store: str = Query(default=""),
    msku: str = Query(default=""),
) -> dict:
    return replenishment_tracking_summary_service.get_detail(
        cutoff_date=cutoff_date,
        site=site,
        store=store,
        msku=msku,
    )


@app.get("/api/return-goods")
def api_return_goods(
    snapshot_date: str = Query(default=""),
    period_days: int = Query(default=1, ge=1, le=30),
    country_category: str = Query(default="all"),
    seller_name_new: str = Query(default="all"),
    keyword: str = Query(default=""),
    stage: str = Query(default="all"),
    warning_type: str = Query(default="all"),
    quick_filter: str = Query(default="all"),
    return_day: int = Query(default=0, ge=0, le=21),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict:
    safe_return_day = return_day if isinstance(return_day, int) else 0
    params = {
        "snapshot_date": snapshot_date,
        "period_days": period_days,
        "country_category": country_category,
        "seller_name_new": seller_name_new,
        "keyword": keyword,
        "stage": stage,
        "warning_type": warning_type,
        "quick_filter": quick_filter,
        "page": page,
        "page_size": page_size,
    }
    if safe_return_day:
        params["return_day"] = safe_return_day
    return return_goods_service.get_payload(**params)


@app.get("/api/return-goods/detail")
def api_return_goods_detail(
    snapshot_date: str = Query(default=""),
    return_event_id: str = Query(default=""),
) -> dict:
    return return_goods_service.get_detail(
        snapshot_date=snapshot_date,
        return_event_id=return_event_id,
    )


@app.get("/api/return-goods/stage-detail")
def api_return_goods_stage_detail(
    snapshot_date: str = Query(default=""),
    period_days: int = Query(default=1, ge=1, le=30),
    country_category: str = Query(default="all"),
    seller_name_new: str = Query(default="all"),
    keyword: str = Query(default=""),
    stage_key: str = Query(default="observe"),
) -> dict:
    return return_goods_service.get_stage_detail(
        snapshot_date=snapshot_date,
        period_days=period_days,
        country_category=country_category,
        seller_name_new=seller_name_new,
        keyword=keyword,
        stage_key=stage_key,
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
    include_all: bool = Query(default=False),
) -> dict:
    return {
        "items": price_review_service.get_daily_adjustment_counts(
            days=days,
            include_all=include_all,
        )
    }


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
    ("调价幅度", "drop_ratio"),
    ("调价幅度区间", "drop_range"),
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
