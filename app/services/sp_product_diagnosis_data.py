from __future__ import annotations

import configparser
import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import pymysql
from pymysql.cursors import DictCursor


PERIODS = {"7d", "14d", "30d", "90d"}
WINDOWS = {1, 7, 14, 30}
ACTIONS = {"", "bid", "add", "negative", "manual_review"}
PAGE_SIZES = {50, 100, 200}
SORTS = {
    "actionable_count", "ad_cost", "ad_sales", "ad_orders", "ad_units", "ad_impressions", "ad_clicks",
    "operating_sales_qty", "operating_sales_amount", "operating_gross_profit", "operating_gross_margin", "operating_inventory_qty",
    "ctr", "cpc", "cvr", "acos", "tacos", "roas", "msku", "asin", "seller_name", "country_code", "currency_code",
    "bid_increase_count", "bid_decrease_count", "bid_manual_review_count", "add_recommended_count",
    "negative_recommended_count", "negative_manual_review_count",
    "monthly_ad_budget_cny", "month_spend_cny", "remaining_budget_cny", "budget_usage_rate", "budget_support_status",
}
FORMULA_PREFIXES = ("=", "+", "-", "@")
SUGGESTION_ACTION_STATUSES = {
    "bid": ("increase", "decrease", "manual_review"),
    "add": ("recommended",),
    "negative": ("recommended", "manual_review"),
}


def product_key(store: Any, country: Any, msku: Any) -> str:
    raw = "\x1f".join(str(value or "").strip().casefold() for value in (store, country, msku))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ratio(numerator: Any, denominator: Any) -> Decimal | None:
    if numerator is None or denominator is None:
        return None
    bottom = Decimal(str(denominator))
    return Decimal(str(numerator)) / bottom if bottom else None


def calculate_diagnosis_rates(row: Mapping[str, Any]) -> dict[str, Decimal | None]:
    return {
        "ctr": _ratio(row.get("clicks"), row.get("impressions")),
        "cpc": _ratio(row.get("ad_cost"), row.get("clicks")),
        "cvr": _ratio(row.get("ad_orders"), row.get("clicks")),
        "acos": _ratio(row.get("ad_cost"), row.get("ad_sales")),
        "roas": _ratio(row.get("ad_sales"), row.get("ad_cost")),
        "tacos": _ratio(row.get("ad_cost"), row.get("operating_sales")),
        "operating_gross_margin": _ratio(row.get("operating_gross_profit"), row.get("operating_sales")),
    }


@dataclass
class ProductDiagnosisFilters:
    period: str = "30d"
    window: int = 7
    currency: str = ""
    store: str = ""
    country: str = ""
    keyword: str = ""
    action: str = ""
    page: int = 1
    page_size: int = 50
    sort: str = "ad_cost"
    direction: str = "desc"
    key: str = ""

    def __init__(self, values: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        source = dict(values or {}) | kwargs
        self.period = str(source.get("period") or "30d")
        self.window = int(source.get("window") or 7)
        self.currency = str(source.get("currency") or "")
        self.store = str(source.get("store") or "")
        self.country = str(source.get("country") or "")
        self.keyword = str(source.get("keyword") or source.get("msku") or "").strip()
        self.action = str(source.get("action") or "")
        self.page = max(1, int(source.get("page") or 1))
        self.page_size = int(source.get("page_size") or 50)
        self.sort = str(source.get("sort") or "ad_cost")
        self.direction = str(source.get("direction") or "desc").lower()
        self.key = str(source.get("key") or "")
        if self.period not in PERIODS: raise ValueError("unsupported period")
        if self.window not in WINDOWS: raise ValueError("unsupported attribution window")
        if self.action not in ACTIONS: raise ValueError("unsupported action")
        if self.page_size not in PAGE_SIZES: raise ValueError("unsupported page size")
        if self.sort not in SORTS or self.direction not in {"asc", "desc"}: raise ValueError("unsupported sort")
        if self.key and (len(self.key) != 64 or any(c not in "0123456789abcdef" for c in self.key.lower())):
            raise ValueError("invalid diagnosis key")


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: str(item) if item is not None and (key == "id" or key.endswith("_id")) else _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serialize(item) for item in value]
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, datetime): return value.isoformat(sep=" ")
    if isinstance(value, date): return value.isoformat()
    return value


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _where(filters: ProductDiagnosisFilters, batch_id: int, alias: str = "s") -> tuple[str, list[Any]]:
    p = f"{alias}." if alias else ""
    clauses = [f"{p}batch_id=%s", f"{p}period_code=%s"]
    params: list[Any] = [batch_id, filters.period]
    if filters.currency:
        clauses.append(f"coalesce({p}currency_code,'')=%s")
        params.append("" if filters.currency == "__unknown__" else filters.currency)
    for column, value in (("seller_name", filters.store), ("country_code", filters.country)):
        if value:
            clauses.append(f"coalesce({p}{column},'') like %s escape '!'")
            params.append(f"%{_escape_like(value)}%")
    if filters.keyword:
        like = "%" + _escape_like(filters.keyword) + "%"
        clauses.append(f"({p}msku like %s escape '!' or coalesce({p}asin,'') like %s escape '!')")
        params.extend([like, like])
    action_expr = {
        "bid": f"({p}bid_increase_count+{p}bid_decrease_count+{p}bid_manual_review_count)>0",
        "add": f"{p}add_recommended_count>0",
        "negative": f"({p}negative_recommended_count+{p}negative_manual_review_count)>0",
        "manual_review": f"({p}bid_manual_review_count+{p}negative_manual_review_count)>0",
    }
    if filters.action: clauses.append(action_expr[filters.action])
    if filters.key: clauses.append(f"{p}diagnosis_key=%s"); params.append(filters.key)
    return " and ".join(clauses), params


class SpProductDiagnosisService:
    def __init__(self) -> None:
        config=configparser.ConfigParser(); config.read(Path(__file__).resolve().parents[2]/"config"/"database.ini",encoding="utf-8")
        target=config["target"]
        self.settings=dict(host=target["host"],port=int(target.get("port",3306)),user=target["user"],password=target["password"],
                           database=target.get("database","etl_datasync_test"),charset="utf8mb4",cursorclass=DictCursor,autocommit=True)

    def connect(self): return pymysql.connect(**self.settings)

    def _batch(self, conn) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute("select * from dashboard_sp_product_diagnosis_batch where status='success' order by data_end desc,batch_id desc limit 1")
            return cur.fetchone()

    def _context(self, values: Mapping[str, Any]) -> tuple[ProductDiagnosisFilters, dict[str, Any]]:
        filters=ProductDiagnosisFilters(values)
        with self.connect() as conn: batch=self._batch(conn)
        if not batch: raise LookupError("暂无已发布的产品诊断数据")
        return filters,batch

    def options(self) -> dict[str, Any]:
        with self.connect() as conn:
            batch=self._batch(conn)
            if not batch: return {"status":"no_data","periods":[7,14,30,90],"windows":[1,7,14,30],"currencies":[],"stores":[],"countries":[]}
            with conn.cursor() as cur:
                cur.execute("select currency_code value,count(*) n from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s and period_code='30d' group by currency_code order by n desc",(batch["batch_id"],))
                currencies=[{"value":r["value"] or "__unknown__","label":r["value"] or "币种未知","count":r["n"]} for r in cur.fetchall()]
                cur.execute("select distinct seller_name value from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s and period_code='30d' order by seller_name",(batch["batch_id"],)); stores=[r["value"] for r in cur.fetchall()]
                cur.execute("select distinct country_code value from dashboard_sp_product_diagnosis_period_snapshot where batch_id=%s and period_code='30d' order by country_code",(batch["batch_id"],)); countries=[r["value"] for r in cur.fetchall()]
        return _serialize({"status":"success","batch":batch,"periods":[7,14,30,90],"windows":[1,7,14,30],"currencies":currencies,"stores":stores,"countries":countries,"default_currency":currencies[0]["value"] if currencies else ""})

    @staticmethod
    def _metric_select(window: int, prefix: str = "s") -> str:
        p=prefix+"." if prefix else ""
        return f"{p}ad_impressions impressions,{p}ad_clicks clicks,{p}ad_cost,{p}ad_orders_{window}d ad_orders,{p}ad_units_{window}d ad_units,{p}ad_sales_{window}d ad_sales"

    @staticmethod
    def _decorate(row: dict[str, Any]) -> dict[str, Any]:
        row.update(calculate_diagnosis_rates({**row,"operating_sales":row.get("operating_sales_amount")}))
        row["item_key"] = row.get("diagnosis_key")
        return _serialize(row)

    def summary(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters,batch=self._context(values); clause,params=_where(filters,batch["batch_id"])
        w=filters.window
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"""select count(*) product_count,sum(actionable_flag) actionable_product_count,
              coalesce(sum(operating_sales_amount),0) operating_sales_amount,coalesce(sum(operating_gross_profit),0) operating_gross_profit,
              coalesce(sum(ad_impressions),0) impressions,coalesce(sum(ad_clicks),0) clicks,coalesce(sum(ad_cost),0) ad_cost,
              coalesce(sum(ad_orders_{w}d),0) ad_orders,coalesce(sum(ad_sales_{w}d),0) ad_sales,
              coalesce(sum(bid_increase_count+bid_decrease_count),0) bid_action_count,
              coalesce(sum(add_recommended_count),0) add_action_count,
              coalesce(sum(negative_recommended_count),0) negative_action_count,
              coalesce(sum(bid_manual_review_count+negative_manual_review_count),0) manual_review_count
              from dashboard_sp_product_diagnosis_period_snapshot s where {clause}""",params)
            row=cur.fetchone()
        return {"batch_id":str(batch["batch_id"]),"summary":self._decorate(row)}

    def rows(self, values: Mapping[str, Any], export: bool = False) -> dict[str, Any]:
        filters,batch=self._context(values); clause,params=_where(filters,batch["batch_id"]); w=filters.window
        sort_expressions={
            "ad_orders":f"s.ad_orders_{w}d","ad_units":f"s.ad_units_{w}d","ad_sales":f"s.ad_sales_{w}d",
            "ctr":"s.ad_clicks/nullif(s.ad_impressions,0)","cpc":"s.ad_cost/nullif(s.ad_clicks,0)",
            "cvr":f"s.ad_orders_{w}d/nullif(s.ad_clicks,0)","acos":f"s.ad_cost/nullif(s.ad_sales_{w}d,0)",
            "tacos":"s.ad_cost/nullif(s.operating_sales_amount,0)","roas":f"s.ad_sales_{w}d/nullif(s.ad_cost,0)",
            "operating_gross_margin":"s.operating_gross_profit/nullif(s.operating_sales_amount,0)",
        }
        sort_expression=sort_expressions.get(filters.sort,f"s.{filters.sort}")
        order = f"{sort_expression} {filters.direction},s.diagnosis_key asc"
        if filters.sort=="ad_cost" and filters.direction=="desc": order="s.actionable_flag desc,s.ad_cost desc,s.diagnosis_key asc"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"select count(*) n from dashboard_sp_product_diagnosis_period_snapshot s where {clause}",params); total=cur.fetchone()["n"]
            select=f"s.*,{self._metric_select(w)}"
            index_hint=" force index(idx_diag_period_default)" if filters.sort=="ad_cost" and filters.direction=="desc" else ""
            sql=f"select {select} from dashboard_sp_product_diagnosis_period_snapshot s{index_hint} where {clause} order by {order}"
            query_params=list(params)
            if not export: sql+=" limit %s offset %s"; query_params.extend([filters.page_size,(filters.page-1)*filters.page_size])
            cur.execute(sql,query_params); rows=[self._decorate(r) for r in cur.fetchall()]
        return {"batch_id":str(batch["batch_id"]),"period":filters.period,"window":w,"page":filters.page,"page_size":filters.page_size,"total":total,"rows":rows}

    def trend(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters,batch=self._context(values); clause,params=_where(filters,batch["batch_id"]); w=filters.window
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"""select d.data_date report_date,coalesce(sum(d.operating_sales_amount),0) operating_sales_amount,
              coalesce(sum(d.ad_cost),0) ad_cost,coalesce(sum(d.ad_sales_{w}d),0) ad_sales
              from dashboard_sp_product_diagnosis_period_snapshot s force index(idx_diag_period_default)
              straight_join dashboard_sp_product_diagnosis_daily d force index(idx_diag_daily_key)
              on s.batch_id=d.batch_id and s.diagnosis_key=d.diagnosis_key
              where {clause} and d.data_date between s.period_start and s.period_end group by d.data_date order by d.data_date""",params)
            rows=cur.fetchall()
        return _serialize({"batch_id":batch["batch_id"],"rows":rows})

    def _suggestions(self, item: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        result={}
        key_params=(batch["recommendation_batch_id"],item["seller_name"],item["country_code"],item["msku"])
        with self.connect() as conn, conn.cursor() as cur:
            for kind,table in (("bid","dashboard_sp_bid_recommendation"),("add","dashboard_sp_add_term_recommendation"),("negative","dashboard_sp_negative_term_recommendation")):
                statuses = SUGGESTION_ACTION_STATUSES[kind]
                placeholders = ",".join(["%s"] * len(statuses))
                cur.execute(
                    f"select * from {table} where batch_id=%s and seller_name=%s and country_code=%s and msku=%s "
                    f"and status in ({placeholders}) order by priority_rank,cost desc,id limit 500",
                    (*key_params, *statuses),
                )
                result[kind]=_serialize(cur.fetchall())
        return result

    def detail(self, values: Mapping[str, Any]) -> dict[str, Any]:
        filters,batch=self._context(values)
        if not filters.key: raise ValueError("diagnosis key is required")
        row_payload=self.rows({**dict(values),"page":1,"page_size":50})
        if not row_payload["rows"]: raise LookupError("detail item not found")
        item=row_payload["rows"][0]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("select data_date report_date,operating_sales_qty,operating_sales_amount,operating_gross_profit,operating_sessions,operating_return_count,operating_return_amount,operating_net_amount,operating_inventory_qty,ad_impressions impressions,ad_clicks clicks,ad_cost,ad_orders_1d,ad_orders_7d,ad_orders_14d,ad_orders_30d,ad_sales_1d,ad_sales_7d,ad_sales_14d,ad_sales_30d from dashboard_sp_product_diagnosis_daily where batch_id=%s and diagnosis_key=%s and data_date between %s and %s order by data_date",(batch["batch_id"],filters.key,item["period_start"],item["period_end"]))
            daily=cur.fetchall()
        windows={}
        for w in WINDOWS:
            x={"impressions":item["ad_impressions"],"clicks":item["ad_clicks"],"ad_cost":item["ad_cost"],"ad_orders":item[f"ad_orders_{w}d"],"ad_sales":item[f"ad_sales_{w}d"],"operating_sales":item["operating_sales_amount"],"operating_gross_profit":item["operating_gross_profit"]}
            windows[str(w)]={**x,**_serialize(calculate_diagnosis_rates(x))}
        suggestion_counts = {
            "bid_adjust": int(item["bid_increase_count"] or 0) + int(item["bid_decrease_count"] or 0),
            "add": int(item["add_recommended_count"] or 0),
            "negative": int(item["negative_recommended_count"] or 0),
            "manual_review": int(item["bid_manual_review_count"] or 0) + int(item["negative_manual_review_count"] or 0),
        }
        return _serialize({
            "item": item,
            "daily": daily,
            "windows": windows,
            "suggestion_counts": suggestion_counts,
            "suggestions": self._suggestions(item,batch),
        })

    def export_csv(self, values: Mapping[str, Any]) -> bytes:
        payload=self.rows(values,export=True)
        headers=[("msku","MSKU"),("asin","ASIN"),("seller_name","店铺"),("country_code","站点"),("currency_code","币种"),("targeting_type","广告类型"),
                 ("operating_sales_qty","经营销量"),("operating_sales_amount","经营销售额"),("operating_gross_profit","经营毛利润"),("operating_gross_margin","经营毛利率"),("operating_inventory_qty","FBA可售库存"),
                 ("ad_impressions","曝光"),("ad_clicks","点击"),("ctr","CTR"),("ad_cost","广告花费"),("cpc","CPC"),("ad_orders","广告订单"),("ad_sales","广告销售额"),("cvr","CVR"),("acos","ACOS"),("tacos","TACOS"),("roas","ROAS"),
                 ("monthly_ad_budget_cny","月预算（人民币）"),("month_spend_cny","本月已用（人民币）"),("remaining_budget_cny","剩余预算（人民币）"),("budget_usage_rate","预算使用率"),("budget_support_status","提价支持"),
                 ("bid_increase_count","提价数"),("bid_decrease_count","降价数"),("bid_manual_review_count","竞价复核数"),("add_recommended_count","建议加词数"),("negative_recommended_count","建议否词数"),("negative_manual_review_count","否词人工审核数"),("data_warning","数据提示")]
        out=io.StringIO(); writer=csv.writer(out); writer.writerow([label for _,label in headers])
        for row in payload["rows"]:
            cells=[]
            for key,_ in headers:
                value="" if row.get(key) is None else str(row.get(key))
                if value.startswith(FORMULA_PREFIXES) or key in {"msku","asin"}: value="'"+value
                cells.append(value)
            writer.writerow(cells)
        return ("\ufeff"+out.getvalue()).encode("utf-8")


sp_product_diagnosis_service=SpProductDiagnosisService()
