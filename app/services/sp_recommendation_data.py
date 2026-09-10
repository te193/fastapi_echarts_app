from __future__ import annotations

import configparser
import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor


TABLES = {
    "bid": "dashboard_sp_bid_recommendation",
    "add": "dashboard_sp_add_term_recommendation",
    "negative": "dashboard_sp_negative_term_recommendation",
}
DEFAULT_INDEXES = {"bid": "idx_bid_default_v2", "add": "idx_add_default_v2", "negative": "idx_negative_default_v2"}
SORTS = {
    "bid": {"cost", "clicks", "orders", "sales", "current_bid", "suggested_bid", "change_amount", "change_rate", "priority_rank"},
    "add": {"cost", "clicks", "orders", "sales", "acos", "priority_rank"},
    "negative": {"cost", "clicks", "orders", "sales", "acos", "priority_rank"},
}
PAGE_SIZES = {50, 100, 200}
ID_FIELDS = {"id", "batch_id", "profile_id", "campaign_id", "ad_group_id", "target_id", "object_id"}
FORMULA_PREFIXES = ("=", "+", "-", "@")
CONTEXT_WARNING_LABELS = {
    "msku_missing": "未找到推广MSKU，需人工排查",
    "multiple_msku": "关联多个MSKU，需人工排查",
    "period_multiple_msku": "成熟窗口内投放过多个MSKU，需人工排查",
    "current_multiple_msku": "当前同时启用多个MSKU，需人工排查",
    "msku_changed": "成熟窗口商品与当前启用商品不一致，需人工排查",
    "term_protection_context_missing": "未匹配Listing保护信息，需人工排查",
    "brand_context_missing": "产品品牌信息缺失，需人工排查",
    "category_context_missing": "本地化叶子类目信息缺失，需人工排查",
    "launch_date_missing": "首单及开售日期缺失，需人工排查",
    "launch_date_invalid": "首单或开售日期晚于数据截止日，需人工排查",
}
RULE_COPY = {
    "bid": "成熟30天：点击≥15且订单为0降价20%–30%；点击≥20、有订单且ACOS>50%降价20%–30%，ACOS>33.3%降价10%–20%；点击≥20、订单≥3、ACOS≤15%且CVR达到站点P75可提价，ACOS≤20%且CVR达到站点均值可小幅提价。调整幅度参考定价毛利段理论CPC；库存不足或人民币月预算已用尽时禁止提价。",
    "add": "成熟30天内广告订单≥10且ACOS≤10%为最高优先级；订单≥10且10%<ACOS≤15%为中优先级。文本词建议精准匹配，ASIN建议商品投放；MSKU映射异常单独提示，不覆盖建议结论。",
    "negative": "成熟30天内点击量≥10且广告订单为0进入高优先级。品牌词、核心类目词和首单/开售90天内的新品推广词转人工审核；文本词建议精准否定，ASIN建议否定商品投放。",
}

BID_BUDGET_FIELDS = (
    "budget_snapshot_date",
    "budget_performance_date",
    "monthly_ad_budget_cny",
    "month_spend_cny",
    "remaining_budget_cny",
    "budget_usage_rate",
    "inventory_sufficient_flag",
    "weekly_inventory_sufficient_flag",
    "budget_support_status",
)


def table_for_kind(kind: str) -> str:
    try:
        return TABLES[kind]
    except KeyError as exc:
        raise ValueError("unsupported recommendation kind") from exc


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


@dataclass
class RecommendationFilters:
    kind: str = "bid"
    object_type: str = ""
    currency: str = ""
    store: str = ""
    country: str = ""
    targeting: str = ""
    status: str = ""
    priority: str = ""
    keyword: str = ""
    campaign: str = ""
    ad_group: str = ""
    keyword_text: str = ""
    search_term: str = ""
    msku: str = ""
    base_store: str = ""
    profile_id: int | None = None
    campaign_id: int | None = None
    ad_group_id: int | None = None
    page: int = 1
    page_size: int = 50
    sort: str = "cost"
    direction: str = "desc"
    key: str = ""

    def __init__(self, values: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        source = dict(values or {}) | kwargs
        self.kind = str(source.get("kind") or "bid")
        table_for_kind(self.kind)
        self.object_type = str(source.get("object_type") or "")
        if self.object_type not in {"", "ad_group", "keyword"}:
            raise ValueError("unsupported bid object type")
        if self.object_type and self.kind != "bid":
            raise ValueError("object type only applies to bid recommendations")
        self.currency = str(source.get("currency") or "")
        self.store = str(source.get("store") or "")
        self.country = str(source.get("country") or "")
        self.targeting = str(source.get("targeting") or "")
        self.status = str(source.get("status") or "")
        self.priority = str(source.get("priority") or "")
        self.keyword = str(source.get("keyword") or "").strip()
        self.campaign = str(source.get("campaign") or "").strip()
        self.ad_group = str(source.get("ad_group") or "").strip()
        self.keyword_text = str(source.get("keyword_text") or "").strip()
        self.search_term = str(source.get("search_term") or "").strip()
        self.msku = str(source.get("msku") or "").strip()
        self.base_store = str(source.get("base_store") or "").strip()
        try:
            self.profile_id = int(source["profile_id"]) if source.get("profile_id") not in (None, "") else None
            self.campaign_id = int(source["campaign_id"]) if source.get("campaign_id") not in (None, "") else None
            self.ad_group_id = int(source["ad_group_id"]) if source.get("ad_group_id") not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ValueError("广告对象ID必须为整数") from exc
        self.page = max(1, int(source.get("page") or 1))
        self.page_size = int(source.get("page_size") or 50)
        self.sort = str(source.get("sort") or "cost")
        self.direction = str(source.get("direction") or "desc").lower()
        self.key = str(source.get("key") or "")
        if self.page_size not in PAGE_SIZES:
            raise ValueError("unsupported page size")
        if self.sort not in SORTS[self.kind] or self.direction not in {"asc", "desc"}:
            raise ValueError("unsupported recommendation sort")
        if self.key and (len(self.key) != 64 or any(c not in "0123456789abcdef" for c in self.key.lower())):
            raise ValueError("invalid recommendation key")


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ID_FIELDS and item is not None:
                result[key] = str(item)
            elif key == "reason_codes" and isinstance(item, str):
                try:
                    result[key] = json.loads(item)
                except json.JSONDecodeError:
                    result[key] = [item]
            else:
                result[key] = serialize(item)
        reason_codes = result.get("reason_codes")
        if isinstance(reason_codes, list):
            warnings = []
            for code in reason_codes:
                if code == "brand_term":
                    warnings.append(f"品牌词：{result.get('protection_brand') or '已命中'}")
                elif code == "core_category_term":
                    warnings.append(f"核心类目词：{result.get('protection_category') or '已命中'}")
                elif code == "new_product_term":
                    launch_date = result.get("product_launch_date") or "日期缺失"
                    warnings.append(f"新品推广词：首单/开售日期 {launch_date}")
                elif code in CONTEXT_WARNING_LABELS:
                    warnings.append(CONTEXT_WARNING_LABELS[code])
            result["data_warning"] = "；".join(warnings)
        return result
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


def csv_cell(field: str, value: Any) -> Any:
    if value is None:
        return ""
    text = str(value)
    if field in ID_FIELDS or text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return value


def _product_context_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("seller_name") or "").strip().casefold(),
        str(row.get("country_code") or "").strip().upper(),
        str(row.get("msku") or "").strip().casefold(),
    )


def _reason_code_set(value: Any) -> set[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    return {str(item) for item in (value or [])}


BID_WAITING_STATUSES = {
    "no_order_below_threshold",
    "with_order_below_threshold",
}


def bid_display_status(row: Mapping[str, Any]) -> str:
    """Turn the legacy catch-all bid status into an actionable display status."""
    status = str(row.get("status") or "")
    change_amount = row.get("change_amount")
    if status in {"increase", "decrease"} and change_amount is not None and Decimal(str(change_amount)) == 0:
        return "keep"
    if status != "insufficient_data":
        return status

    current_bid = row.get("current_bid")
    if current_bid is None or Decimal(str(current_bid)) <= 0:
        return "current_bid_missing"
    clicks = Decimal(str(row.get("clicks") or 0))
    orders = Decimal(str(row.get("orders") or 0))
    if orders <= 0 and clicks < 15:
        return "no_order_below_threshold"
    if orders > 0 and clicks < 20:
        return "with_order_below_threshold"
    return "calculation_input_missing"


def merge_bid_budget_context(
    rows: list[dict[str, Any]],
    contexts: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        source_status = str(row.get("status") or "")
        display_status = bid_display_status(row)
        if display_status != source_status:
            row["source_status"] = source_status
            row["status"] = display_status
        sales = row.get("sales")
        row["acos"] = Decimal(str(row.get("cost") or 0)) / Decimal(str(sales)) if sales else None
        if row.get("listing_price") is None:
            row["listing_mapping_status"] = "Listing价格未匹配"
        elif row.get("margin_rate") is None:
            row["listing_mapping_status"] = "定价毛利率未匹配"
        else:
            row["listing_mapping_status"] = "已匹配"

        for field in BID_BUDGET_FIELDS:
            row.setdefault(field, None)
        associated_count = int(row.get("associated_msku_count") or 0)
        mapping_code = next(
            (
                code
                for code in _reason_code_set(row.get("reason_codes"))
                if code in {"period_multiple_msku", "current_multiple_msku", "msku_changed"}
            ),
            None,
        )
        key = _product_context_key(row)
        if mapping_code:
            row["budget_context_status"] = mapping_code
            row["budget_support_status"] = CONTEXT_WARNING_LABELS[mapping_code]
        elif associated_count > 1:
            row["budget_context_status"] = "multiple_msku"
            row["budget_support_status"] = "关联多个MSKU，分别查看商品预算"
        elif not key[2]:
            row["budget_context_status"] = "msku_missing"
            row["budget_support_status"] = "未找到推广MSKU，需人工排查"
        else:
            context = contexts.get(key)
            if context:
                row.update({field: context.get(field) for field in BID_BUDGET_FIELDS})
                row["budget_context_status"] = "matched"
            else:
                row["budget_context_status"] = "not_mapped"
                row["budget_support_status"] = "商品预算未匹配，需人工排查"

        reasons = _reason_code_set(row.get("reason_codes"))
        if source_status == "insufficient_data":
            reasons.difference_update({"metric_missing", "threshold_not_met"})
            reasons.add(display_status)
            row["reason_codes"] = sorted(reasons)
        if display_status in BID_WAITING_STATUSES:
            current_bid = Decimal(str(row["current_bid"]))
            row["suggested_bid"] = current_bid
            row["change_direction"] = "keep"
            row["change_amount"] = Decimal("0")
            row["change_rate"] = Decimal("0")
        change_amount = row.get("change_amount")
        if source_status in {"increase", "decrease"} and change_amount is not None and Decimal(str(change_amount)) == 0:
            row["status"] = "keep"
            reasons.add("minimum_bid_increment_blocks_change")
            row["reason_codes"] = sorted(reasons)
        if reasons & {"inventory_blocks_increase", "budget_blocks_increase"}:
            row["max_allowed_bid"] = row.get("current_bid")
        elif row.get("status") == "increase":
            row["max_allowed_bid"] = row.get("suggested_bid")
        else:
            row["max_allowed_bid"] = None
        enriched_rows.append(row)
    return enriched_rows


def _where(filters: RecommendationFilters, batch_id: int) -> tuple[str, list[Any]]:
    clauses = ["batch_id=%s"]
    params: list[Any] = [batch_id]
    if filters.object_type:
        clauses.append("object_type=%s")
        params.append(filters.object_type)
    for column, value in (("currency_code", filters.currency), ("targeting_type", filters.targeting)):
        if value:
            if column == "targeting_type" and value == "__unknown__":
                clauses.append("coalesce(targeting_type,'') not in ('auto','manual')")
            else:
                clauses.append(f"coalesce({column},'')=%s")
                params.append("" if value == "__unknown__" else value)
    for column, value in (
        ("seller_name", filters.store),
        ("country_code", filters.country),
        ("campaign_name_current", filters.campaign),
        ("ad_group_name_current", filters.ad_group),
    ):
        if value:
            clauses.append(f"coalesce({column},'') like %s escape '!'")
            params.append(f"%{_escape_like(value)}%")
    if filters.keyword_text:
        keyword_column = "object_text" if filters.kind == "bid" else "target_text"
        clauses.append(f"coalesce({keyword_column},'') like %s escape '!'")
        params.append(f"%{_escape_like(filters.keyword_text)}%")
    if filters.search_term and filters.kind != "bid":
        clauses.append("coalesce(search_term,'') like %s escape '!'")
        params.append(f"%{_escape_like(filters.search_term)}%")
    if filters.status:
        status_expression = status_breakdown_expression(filters.kind)
        clauses.append(f"{status_expression}=%s")
        params.append(filters.status)
    if filters.priority and filters.kind != "bid":
        clauses.append("coalesce(priority,'')=%s")
        params.append(filters.priority)
    if filters.msku:
        clauses.append("coalesce(msku,'') like %s escape '!'")
        params.append(f"%{_escape_like(filters.msku)}%")
    if filters.base_store:
        clauses.append(
            "lower(regexp_replace(regexp_replace(coalesce(seller_name,''),"
            "concat('-',coalesce(country_code,''),'$'),''),'-(eu|uk)$',''))=lower(%s)"
        )
        params.append(filters.base_store)
    for column, value in (
        ("profile_id", filters.profile_id),
        ("campaign_id", filters.campaign_id),
        ("ad_group_id", filters.ad_group_id),
    ):
        if value is not None:
            clauses.append(f"{column}=%s")
            params.append(value)
    if filters.keyword:
        fields = ["object_text"] if filters.kind == "bid" else ["search_term", "target_text", "suggestion_value"]
        clauses.append("(" + " or ".join(f"coalesce({field},'') like %s escape '!'" for field in fields) + ")")
        params.extend([f"%{_escape_like(filters.keyword)}%"] * len(fields))
    return " and ".join(clauses), params


def order_by(filters: RecommendationFilters) -> str:
    if filters.sort == "cost" and filters.direction == "desc":
        if filters.kind == "bid":
            return "case when status in ('increase','decrease') and coalesce(change_amount,0)=0 then 1 else 0 end asc,priority_rank asc,cost desc,id asc"
        return "priority_rank asc,cost desc,id asc"
    return f"{filters.sort} {filters.direction},id asc"


def status_breakdown_expression(kind: str) -> str:
    table_for_kind(kind)
    if kind == "bid":
        return (
            "case "
            "when status in ('increase','decrease') and coalesce(change_amount,0)=0 then 'keep' "
            "when status='insufficient_data' and coalesce(current_bid,0)<=0 then 'current_bid_missing' "
            "when status='insufficient_data' and coalesce(orders,0)<=0 and coalesce(clicks,0)<15 then 'no_order_below_threshold' "
            "when status='insufficient_data' and coalesce(orders,0)>0 and coalesce(clicks,0)<20 then 'with_order_below_threshold' "
            "when status='insufficient_data' then 'calculation_input_missing' "
            "else status end"
        )
    return "status"


class SpRecommendationService:
    def __init__(self) -> None:
        config = configparser.ConfigParser()
        config.read(Path(__file__).resolve().parents[2] / "config" / "database.ini", encoding="utf-8")
        target = config["target"]
        self.settings = dict(host=target["host"], port=int(target.get("port", 3306)), user=target["user"],
                             password=target["password"], database=target.get("database", "etl_datasync_test"),
                             charset="utf8mb4", cursorclass=DictCursor, autocommit=True)

    def connect(self):
        return pymysql.connect(**self.settings)

    def _batch(self, conn) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute("select * from dashboard_sp_recommendation_batch where status='success' order by cutoff_date desc,batch_id desc limit 1")
            return cur.fetchone()

    def _bid_budget_context(self, conn, rows: list[dict[str, Any]], recommendation_batch_id: int) -> dict[tuple[str, str, str], dict[str, Any]]:
        keys = {
            _product_context_key(row)
            for row in rows
            if int(row.get("associated_msku_count") or 0) <= 1 and _product_context_key(row)[2]
        }
        if not keys:
            return {}
        with conn.cursor() as cur:
            cur.execute(
                """select batch_id from dashboard_sp_product_diagnosis_batch
                   where status='success' and recommendation_batch_id=%s
                   order by data_end desc,batch_id desc limit 1""",
                (recommendation_batch_id,),
            )
            diagnosis_batch = cur.fetchone()
            if not diagnosis_batch:
                return {}
            stores = sorted({key[0] for key in keys})
            countries = sorted({key[1] for key in keys})
            mskus = sorted({key[2] for key in keys})
            store_marks = ",".join(["%s"] * len(stores))
            country_marks = ",".join(["%s"] * len(countries))
            msku_marks = ",".join(["%s"] * len(mskus))
            fields = ",".join(BID_BUDGET_FIELDS)
            cur.execute(
                f"""select seller_name,country_code,msku,{fields}
                    from dashboard_sp_product_diagnosis_period_snapshot force index (idx_diag_period_product)
                    where batch_id=%s and period_code='30d'
                      and lower(seller_name) in ({store_marks})
                      and country_code in ({country_marks})
                      and lower(msku) in ({msku_marks})""",
                [diagnosis_batch["batch_id"], *stores, *countries, *mskus],
            )
            context_rows = cur.fetchall()
        return {_product_context_key(row): row for row in context_rows}

    def options(self) -> dict[str, Any]:
        with self.connect() as conn:
            batch = self._batch(conn)
            if not batch:
                return {"status": "no_data", "rules": RULE_COPY, "currencies": [], "stores": [], "countries": []}
            with conn.cursor() as cur:
                cur.execute("""select currency_code value,count(*) n from dashboard_sp_bid_recommendation
                    where batch_id=%s group by currency_code order by n desc""", (batch["batch_id"],))
                currencies = [{"value": r["value"] or "__unknown__", "label": r["value"] or "币种未知", "count": r["n"]} for r in cur.fetchall()]
                cur.execute("select distinct seller_name value from dashboard_sp_bid_recommendation where batch_id=%s and seller_name is not null order by seller_name", (batch["batch_id"],))
                stores = [r["value"] for r in cur.fetchall()]
                cur.execute("select distinct country_code value from dashboard_sp_bid_recommendation where batch_id=%s and country_code is not null order by country_code", (batch["batch_id"],))
                countries = [r["value"] for r in cur.fetchall()]
        return serialize({"status": "success", "batch": batch, "rules": RULE_COPY, "currencies": currencies,
                          "stores": stores, "countries": countries, "default_currency": currencies[0]["value"] if currencies else ""})

    def _filters_and_batch(self, values: Mapping[str, Any]) -> tuple[RecommendationFilters, dict[str, Any]]:
        filters = RecommendationFilters(values)
        with self.connect() as conn:
            batch = self._batch(conn)
        if not batch:
            raise LookupError("暂无已发布的广告建议数据")
        return filters, batch

    def summary(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        summary_filters = RecommendationFilters({**vars(filters), "status": ""})
        clause, params = _where(summary_filters, batch["batch_id"])
        table = table_for_kind(filters.kind)
        status_expression = status_breakdown_expression(filters.kind)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select {status_expression} status,count(*) total,
                    coalesce(sum(cost),0) cost,coalesce(sum(sales),0) sales
                    from {table} where {clause}
                    group by {status_expression}""",
                params,
            )
            groups = cur.fetchall()
            cur.execute(
                f"""select coalesce(nullif(currency_code,''),'') currency_code,count(*) total,
                    coalesce(sum(cost),0) cost,coalesce(sum(sales),0) sales
                    from {table} where {clause}
                    group by coalesce(nullif(currency_code,''),'')
                    order by currency_code""",
                params,
            )
            currency_totals = cur.fetchall()
        breakdown = {str(group["status"]): int(group["total"]) for group in groups}
        single_currency = currency_totals[0] if len(currency_totals) == 1 else None
        row = {
            "total": sum(breakdown.values()),
            "recommended": (
                breakdown.get("increase", 0) + breakdown.get("decrease", 0)
                if filters.kind == "bid"
                else breakdown.get("recommended", 0)
            ),
            "manual_review": breakdown.get("manual_review", 0),
            "cost": single_currency["cost"] if single_currency else None,
            "sales": single_currency["sales"] if single_currency else None,
            "currency_totals": currency_totals,
            "status_breakdown": breakdown,
        }
        return serialize({"batch_id": batch["batch_id"], "summary": row})

    def rows(self, values: Mapping[str, Any], export: bool = False) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        clause, params = _where(filters, batch["batch_id"])
        table = table_for_kind(filters.kind)
        limit = "" if export else " limit %s offset %s"
        query_params = params if export else [*params, filters.page_size, (filters.page - 1) * filters.page_size]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select count(*) total from {table} where {clause}", params)
            total = int(cur.fetchone()["total"])
            index_hint = f" force index ({DEFAULT_INDEXES[filters.kind]})" if filters.sort == "cost" and filters.direction == "desc" else ""
            cur.execute(f"select * from {table}{index_hint} where {clause} order by {order_by(filters)}{limit}", query_params)
            rows = cur.fetchall()
            if filters.kind == "bid":
                rows = merge_bid_budget_context(rows, self._bid_budget_context(conn, rows, batch["batch_id"]))
        return serialize({"batch_id": batch["batch_id"], "kind": filters.kind, "rows": rows, "total": total,
                          "page": filters.page, "page_size": filters.page_size})

    def detail(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters, batch = self._filters_and_batch(values)
        if not filters.key:
            raise ValueError("recommendation key is required")
        table = table_for_kind(filters.kind)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select * from {table} where batch_id=%s and recommendation_key=%s", (batch["batch_id"], filters.key))
            row = cur.fetchone()
            if row and filters.kind == "bid":
                row = merge_bid_budget_context([row], self._bid_budget_context(conn, [row], batch["batch_id"]))[0]
        if not row:
            raise LookupError("建议记录不存在")
        return serialize({"batch_id": batch["batch_id"], "item": row})

    def export_csv(self, values: Mapping[str, Any]) -> bytes:
        rows = self.rows(values, export=True)["rows"]
        output = io.StringIO()
        fields = list(rows[0]) if rows else ["message"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(key, value) for key, value in row.items()})
        return ("\ufeff" + output.getvalue()).encode("utf-8")


sp_recommendation_service = SpRecommendationService()
