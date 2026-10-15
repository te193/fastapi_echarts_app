"""Read-only capacity annotations. No demand, stock or quantity fields are changed."""
from __future__ import annotations

from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Callable

import pymysql

CAPACITY_COLUMNS = tuple({"name": name, "label": label} for name, label in (
    ("capacity_status_label", "库容预警状态"), ("capacity_note", "库容预警说明"),
    ("capacity_group", "库容共享组"), ("capacity_storage_type", "商品仓储类型"),
    ("capacity_month", "库容额度月份"), ("capacity_remaining_m3", "来源剩余库容(m³)"),
    ("capacity_unit_volume_m3", "单件体积估算(m³)"), ("capacity_demand_volume_m3", "本行补货体积估算(m³)"),
    ("capacity_group_demand_m3", "店铺同类型补货总体积(m³)"), ("capacity_shortfall_m3", "店铺合计预计超出(m³)"),
    ("capacity_source_time", "库容来源时间"), ("capacity_measurement_source", "体积与类型来源"),
    ("capacity_snapshot_date", "库容采集日期"), ("capacity_match_basis", "库容匹配依据"),
    ("capacity_quota_summary", "店铺站点库容明细"), ("capacity_product_note", "补货体积核查说明"),
    ("capacity_row_status_label", "本行库容核查"), ("capacity_group_status_label", "店铺同类型合计核查"),
    ("capacity_row_shortfall_m3", "本行预计超出(m³)"), ("capacity_plan_scope", "体积核查范围"),
))
TYPE_LABELS = {"Standard": "标准尺寸", "Oversize": "大件", "Apparel": "服装", "Footwear": "鞋靴", "ExtraLarge": "超大件"}
EU_COUNTRIES = {"德国", "法国", "意大利", "西班牙", "荷兰", "比利时", "波兰", "瑞典", "爱尔兰"}
FT3_TO_M3 = Decimal("0.028316846592")
STORAGE_TYPES = {**{key.casefold():key for key in TYPE_LABELS}, "标准":"Standard", "标准尺寸":"Standard",
                 "大件":"Oversize", "服装":"Apparel", "鞋靴":"Footwear", "超大件":"ExtraLarge"}
SOURCE_KEY_BATCH_SIZE = 2000


def _index_sources(source: dict) -> None:
    """Build request-local lookups once; keep exact MSKU/SKU matching semantics."""
    lookups = {}
    for name, field in (("fees", "seller_sku"), ("warehouse_types", "msku"),
                        ("listing_dimensions", "seller_sku"), ("packages", "sku")):
        lookup = {}
        for record in source.get(name, []):
            lookup.setdefault(str(record.get(field) or ""), []).append(record)
        lookups[name] = lookup
    source["_lookups"] = lookups
    source["_seller_matches"] = {}
    quota_lookup = {}
    for position, record in enumerate(source.get("limits", [])):
        quota_lookup.setdefault(str(record.get("sid")), []).append((position, record))
    source["_quota_lookup"] = quota_lookup


def _source_records(source: dict, name: str, key: str) -> list[dict]:
    if "_lookups" in source:
        return source["_lookups"][name].get(key, [])
    return source.get(name, [])


def _matching_sellers(site: str, store: str, countries: set, source: dict) -> tuple:
    seller_matches = source.get("_seller_matches", {})
    if (site, store) not in seller_matches:
        sellers = [s for s in source.get("sellers", []) if s.get("country") in countries and store in
                   {str(s.get("account_name") or "").strip().casefold(), str(s.get("name") or "").strip().casefold()}]
        prefix_match = not sellers
        if prefix_match:
            # seller_name_new in the replenishment ETL is substring_index(name, '-', 1).
            sellers = [s for s in source.get("sellers", []) if s.get("country") in countries
                       and str(s.get("name") or "").strip().casefold().split("-", 1)[0] == store]
        seller_matches[(site, store)] = (sellers, prefix_match)
    return seller_matches[(site, store)]


def _row_key(row: dict) -> tuple:
    return (row.get("country_category") or row.get("country"),
            str(row.get("seller_name_new") or row.get("store") or "").strip().casefold(),
            str(row.get("seller_sku_adj") or row.get("msku") or ""))


def _listing_volume(record: dict) -> Decimal | None:
    try:
        data = json.loads(record.get("dimension_info") or "[]")
    except (ValueError, TypeError):
        return None
    volumes = []
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict):
            continue
        volume = Decimal(1)
        for edge in ("length", "width", "height"):
            size = number(item.get("package_"+edge))
            unit = str(item.get("package_"+edge+"_units_type") or "").strip().casefold()
            factor = {"cm":Decimal(".01"), "centimeter":Decimal(".01"), "centimeters":Decimal(".01"),
                      "inch":Decimal(".0254"), "inches":Decimal(".0254")}.get(unit)
            if size is None or size <= 0 or factor is None:
                break
            volume *= size*factor
        else:
            volumes.append(volume)
    return max(volumes) if volumes else None


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip())
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def volume_m3(value: Any, unit: Any) -> Decimal | None:
    amount = number(value)
    if amount is None:
        return None
    unit = str(unit).strip().lower()
    if unit in {"1", "m3", "m³", "cubic meters"}:
        return amount
    if unit in {"2", "ft3", "ft³", "cubic feet"}:
        return amount * FT3_TO_M3
    return None


def dimensions_m3(row: dict, fields: tuple[str, str, str], unit: str) -> Decimal | None:
    sizes = [number(row.get(field)) for field in fields]
    if any(value is None or value <= 0 for value in sizes):
        return None
    factor = {"centimeters": Decimal("0.01"), "cm": Decimal("0.01"), "inches": Decimal("0.0254")}.get(unit)
    if factor is None:
        return None
    return sizes[0] * sizes[1] * sizes[2] * factor ** 3


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return value.isoformat(sep=" ") if isinstance(value, datetime) else str(value or "")


def _volume_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _quota_signature(row: dict) -> tuple:
    unit = row.get("sub_item_vol_unit_type")
    maximum, remaining = volume_m3(row.get("vol_stock_max"), unit), volume_m3(row.get("vol_stock_remain"), unit)
    if maximum is None or maximum < 0 or remaining is None:
        return ("invalid", str(row.get("vol_stock_max")), str(row.get("vol_stock_remain")), str(unit))
    return (maximum, remaining, str(row.get("fba_allocation_type") or ""))


def _quota_summary(rows: list[dict], sellers: list[dict]) -> str:
    countries = {str(s["sid"]): s.get("country") or str(s["sid"]) for s in sellers}
    grouped = {}
    for row in rows:
        kind = row.get("sub_item_storage_type") or row.get("storage_type")
        key = (kind, _quota_signature(row))
        grouped.setdefault(key, []).append(countries.get(str(row.get("sid")), str(row.get("sid"))))
    notes = []
    for (kind, signature), sites in grouped.items():
        detail = "额度或单位未提供，不能用负数占位值判断超占用"
        if signature[0] != "invalid":
            maximum, remaining, allocation = signature
            detail = f"总额度 {_volume_text(maximum)} m³，剩余 {_volume_text(remaining)} m³"
            if allocation != "2":
                detail += "（预估或确定状态未确认）"
        notes.append(f"{TYPE_LABELS.get(kind, kind or '未知类型')} / {'、'.join(sorted(set(sites)))}：{detail}")
    return "\n".join(notes)


def _capacity_tooltip(result: dict, context: dict) -> str:
    """One source conclusion, at most one priority check, and the collection date."""
    state = result["capacity_status"]
    labels = {"source_available": "有剩余（仅参考）", "over_capacity": "来源已超占用",
              "no_capacity": "来源无剩余", "station_difference": "各国额度不一致",
              "type_unmapped": "已读取额度，商品类型未对应", "not_found": "未找到对应额度",
              "insufficient": "本次估算超出剩余", "within_capacity": "本次估算未超额",
              "pending": "暂时无法判断"}
    lines = ["库容：" + labels[state]]
    remaining = result.get("capacity_remaining_m3")
    if remaining is not None:
        amount = number(remaining)
        amount_text = f"{amount:.2f}" if abs(amount) >= Decimal(".01") or amount == 0 else _volume_text(amount)
        kind = str(result.get("capacity_storage_type") or "类型未确认").split("（", 1)[0]
        lines.append(f"剩余：{amount_text} m³ · {kind}" + ("（参考）" if not context.get("type_confirmed") else ""))
    if context.get("fatal"):
        action = (context.get("problems") or ["来源暂不可读取"])[0]
    elif state == "station_difference":
        action = "先核对发往哪个国家；各国额度见导出明细。"
    elif state == "type_unmapped":
        action = "先确认商品属于哪种仓储类型；店铺额度见导出明细。"
    elif state == "not_found":
        action = "先核对店铺和月份是否有对应额度。"
    elif state == "pending":
        action = "先核对来源日期或额度；原因见导出说明。"
        if number(context.get("maximum")) is None:
            action = "平台总额度未提供，暂不能判断剩余库容。"
    elif state in {"over_capacity", "no_capacity"}:
        action = "先核对库容和开放货件占用，再确认发货安排。"
    elif not context.get("type_confirmed"):
        action = "先核对商品仓储类型，尚未判断本次补货是否超额。"
    elif result.get("capacity_product_note"):
        action = "尚未核算本次是否超额；核查原因见导出说明。"
    else:
        action = "仅为估算提示，不修改补货数量。"
    lines.append("提醒：" + action)
    lines.append("数据日期：" + (result.get("capacity_snapshot_date") or "未提供") + ("（月末归档）" if context.get("archive_mode") else ""))
    return "\n".join(lines)


def evaluate_capacity(snapshot: date, quantity: Any, context: dict) -> dict:
    """Show source quota separately from eligibility to compare new shipment volume."""
    result = {column["name"]: None for column in CAPACITY_COLUMNS}
    result.update(capacity_status="pending", capacity_status_label="库容待核",
                  capacity_group=context.get("group"), capacity_storage_type=context.get("type_label"),
                  capacity_month=context.get("month"), capacity_source_time=_text(context.get("source_time")),
                  capacity_measurement_source=context.get("measurement_source") or "",
                  capacity_match_basis=context.get("match_basis") or "",
                  capacity_quota_summary=context.get("quota_summary") or "")
    unit_volume = number(context.get("unit_volume"))
    qty = number(quantity)
    if unit_volume is not None and unit_volume > 0:
        result["capacity_unit_volume_m3"] = float(unit_volume)
        if qty is not None and qty >= 0:
            result["capacity_demand_volume_m3"] = float(qty * unit_volume)
    problems = list(context.get("problems") or [])
    if context.get("fatal"):
        result["capacity_note"] = "；".join([*problems, "仅提示，不修改补货数量"])
        result["capacity_detail"] = result["capacity_note"]
        result["capacity_tooltip"] = _capacity_tooltip(result, context)
        return result
    source_status = context.get("source_status")
    remaining = volume_m3(context.get("remaining"), context.get("unit"))
    maximum = volume_m3(context.get("maximum"), context.get("unit"))
    if not source_status and (maximum is None or maximum < 0 or remaining is None):
        problems.append("额度或单位无法确认（“－”不代表零库容）")
        remaining = None
    elif remaining is not None:
        result["capacity_remaining_m3"] = float(remaining)
    product_problems = []
    if not context.get("group_confirmed"):
        product_problems.append("共享库容组未确认；不影响店铺额度展示")
    if not context.get("type_confirmed"):
        product_problems.append("商品仓储类型需确认，历史尺寸类型仅供参考")
    # Collection date measures daily freshness; a platform value can be unchanged for days.
    source_day = _day(context.get("snapshot_time") or context.get("source_time"))
    reference = _day(context.get("reference_date")) or snapshot
    if context.get("archive_mode"):
        if source_day != reference:
            problems.append("历史月归档未覆盖月底，展示已有来源供核对")
    elif source_day is None or not reference - timedelta(days=1) <= source_day <= reference:
        problems.append("来源未覆盖所选补货日期" if source_day is None or source_day < reference else "来源晚于所选补货日期")
    if _day(context.get("month")) != snapshot.replace(day=1):
        problems.append("额度月份与所选补货月份不一致")
    allocation = str(context.get("allocation_type") or "")
    if allocation == "1":
        problems.append("额度为预估，仅供参考")
    elif allocation != "2":
        problems.append("额度确定状态未确认")
    if unit_volume is None or unit_volume <= 0:
        product_problems.append("单件体积未确认")
    observation = ""
    demand_month = context.get("demand_month") or snapshot.strftime("%Y-%m")
    shipping_note = f"默认发货月份：{demand_month}（生成补货后当天开始发货流程）" if not context.get("demand_month") else f"发货月份：{demand_month}"
    snapshot_note = f"库容快照日期：{source_day.isoformat()}" if source_day else "库容快照日期未确认"
    result["capacity_snapshot_date"] = source_day.isoformat() if source_day else None
    if context.get("archive_mode"):
        snapshot_note += "（历史月月末归档，不代表所选历史日的实时库容）"
    elif reference != snapshot:
        snapshot_note += "（当前月最新版本，不代表所选历史日的实时库容）"
    if remaining is not None:
        observation = f"来源剩余库容 {_volume_text(remaining)} m³"
        if remaining < 0:
            observation += "（来源显示已超占用）"
        elif remaining == 0:
            observation += "（来源显示无剩余）"
    if source_status:
        labels = {"type_unmapped": "已读取店铺额度（商品类型未对应）",
                  "station_difference": "已读取库容（站点有差异）", "not_found": "店铺当月额度未提供"}
        result.update(capacity_status=source_status, capacity_status_label=labels[source_status])
        if problems:
            result["capacity_status_label"] += "（来源日期或额度需核对）"
    elif not problems and remaining is not None and remaining <= 0:
        result.update(capacity_status="over_capacity" if remaining < 0 else "no_capacity",
                      capacity_status_label="来源库容已超占用" if remaining < 0 else "来源无剩余库容")
    elif not problems:
        result.update(capacity_status="source_available", capacity_status_label="来源有剩余库容")
        demand = number(context.get("same_month_new_volume"))
        if demand_month != snapshot.strftime("%Y-%m"):
            product_problems.append("发货月份与库容额度月份不一致")
        elif not context.get("demand_complete"):
            product_problems.append("共享组需求体积未完整")
        elif not context.get("occupancy_reconciled"):
            product_problems.append("货件占用尚未核对，不重复扣减已纳入平台的在途")
        elif demand is None or demand < 0:
            product_problems.append("同期新增需求体积未确认")
        if not product_problems:
            result["capacity_group_demand_m3"] = float(demand)
            result["capacity_shortfall_m3"] = float(max(Decimal(0), demand - remaining))
            exceeds = demand > remaining
            result.update(capacity_status="insufficient" if exceeds else "within_capacity",
                          capacity_status_label="预计库容不足" if exceeds else "同期需求未超额")
            observation += f"；同期新增需求 {_volume_text(demand)} m³，缺口 {_volume_text(max(Decimal(0), demand-remaining))} m³"
    result["capacity_product_note"] = "；".join(dict.fromkeys(product_problems)) if product_problems else ""
    if product_problems:
        result["capacity_product_note"] = "未核算本次补货是否超额：" + result["capacity_product_note"]
    notes = [part for part in (observation, snapshot_note, shipping_note, context.get("measurement_source"),
                              context.get("match_basis"), context.get("quota_summary"), result["capacity_product_note"]) if part]
    if result["capacity_status"] == "pending" and remaining is not None and remaining <= 0:
        result["capacity_status_label"] = "库容待核（来源超占用）" if remaining < 0 else "库容待核（来源无剩余）"
    notes.extend(dict.fromkeys(problems))
    notes.append("仅提示，不修改补货数量、箱数或货值")
    result["capacity_note"] = "；".join([part for part in [observation, snapshot_note, shipping_note, *dict.fromkeys(problems), result["capacity_product_note"], "仅提示，不修改补货数量"] if part])
    result["capacity_detail"] = "\n".join([f"共享关系：{context.get('group') or '未在共享组快照出现，额度按店铺读取'}；额度月：{context.get('month') or '未提供'}；平台更新时间：{result['capacity_source_time'] or '未提供'}", *notes])
    if result["capacity_demand_volume_m3"] is not None:
        result["capacity_detail"] += f"\n本行补货体积估算：{_volume_text(qty * unit_volume)} m³（须核对整组需求和已有货件，避免重复计入占用）"
    result["capacity_tooltip"] = _capacity_tooltip(result, context)
    return result


def apply_plan_comparison(result: dict, context: dict, quantity: Any, group: dict,
                          unknown_types: int, snapshot: date) -> dict:
    """Hypothetically send the full new replenishment plan; never deduct open shipments again."""
    qty, unit = number(quantity), number(context.get("unit_volume"))
    volume = qty*unit if qty is not None and qty >= 0 and unit is not None and unit > 0 else None
    if qty == 0:
        volume = Decimal(0)
    result["capacity_demand_volume_m3"] = float(volume) if volume is not None else None
    result["capacity_plan_scope"] = "所选日期全量补货需求，按账号＋国家类别＋仓储类型汇总；假设本次需求全部作为新增发货，不再扣已纳入平台的在库和开放货件"
    if context.get("archive_mode"):
        result["capacity_plan_scope"] += "；历史月采用月末归档容量和当前可查类型/尺寸估算，不复原所选历史日实时库容"
    missing = group["missing"]+unknown_types
    total = group["volume"]
    result["capacity_group_demand_m3"] = float(total) if context.get("storage_type") else None
    result["capacity_row_shortfall_m3"] = None
    result["capacity_shortfall_m3"] = None
    available = []
    for item in context.get("comparison_limits", []):
        maximum = volume_m3(item.get("vol_stock_max"), item.get("sub_item_vol_unit_type"))
        remaining = volume_m3(item.get("vol_stock_remain"), item.get("sub_item_vol_unit_type"))
        if maximum is not None and maximum >= 0 and remaining is not None and str(item.get("fba_allocation_type")) == "2":
            available.append(remaining)
    remaining = None
    if available:
        # A valid existing Standard representative is retained; otherwise use the minimum.
        if context.get("source_status") != "station_difference" and result.get("capacity_remaining_m3") is not None:
            remaining = volume_m3(context.get("remaining"), context.get("unit"))
        else:
            remaining = min(available)
            result["capacity_match_basis"] += "；本次比较按当前类别有效站点最小剩余额度估算，不累加各国额度"
        missing += len(context.get("comparison_limits", []))-len(available)
        result["capacity_remaining_m3"] = float(remaining)
    date_ok = (_day(context.get("snapshot_time") or context.get("source_time")))
    reference = _day(context.get("reference_date")) or snapshot
    date_ok = date_ok == reference if context.get("archive_mode") else date_ok is not None and reference-timedelta(days=1) <= date_ok <= reference
    reason = ""
    if qty == 0:
        status, label = "no_replenishment", "本行无需补货"
        row_label, group_label = "数量为0，新增体积为0", "未以本行新增占用"
        if remaining is not None and remaining <= 0:
            label += "（库容已超占用）" if remaining < 0 else "（无剩余库容）"
    elif context.get("fatal"):
        status, label = "plan_unknown", "无法核算：店铺关联或来源异常"
        row_label, group_label = "未比较", "未比较"
        reason = (context.get("problems") or ["来源不可读"])[0]
    elif not context.get("storage_type"):
        status, label = "plan_unknown", "无法核算：商品类型冲突" if context.get("type_conflict") else "无法核算：商品类型缺失"
        row_label, group_label = "缺少可对应的仓储类型", "商品类型数据不足"
        reason = "实际库存类型和月仓储费分类均无法对应，未混用其他类型额度"
    elif volume is None:
        status, label = "plan_unknown", "无法核算：商品体积缺失"
        row_label, group_label = "缺少有效单件体积", "商品体积数据不足"
        reason = "Listing、月费表及SKU包装尺寸均未提供有效长宽高"
    elif remaining is None:
        status, label = "plan_unknown", "无法核算：库容额度未提供"
        row_label, group_label = "补货体积已计算，额度未提供", "额度未提供"
        reason = "对应类型的总额度或剩余值无效，未把“－”当作零额度或超占用"
    elif not date_ok:
        status, label = "plan_unknown", "无法核算：库容日期需核对"
        row_label, group_label = "补货体积已计算，来源日期不符", "来源日期不符"
        reason = "当前月需当天/前一天采集，历史月需月底归档"
    else:
        row_gap, group_gap = max(Decimal(0),volume-remaining), max(Decimal(0),total-remaining)
        result["capacity_row_shortfall_m3"] = float(row_gap)
        result["capacity_shortfall_m3"] = float(group_gap) if not missing or group_gap > 0 else None
        row_label = "本行补货超库容" if row_gap > 0 else "本行补货未超库容"
        group_label = ("已知合计超库容" if missing else "店铺同类型合计超库容") if group_gap > 0 else (f"合计数据不足（{missing}项缺类型、体积或额度）" if missing else "店铺同类型合计未超库容")
        if row_gap > 0:
            status, label = "plan_row_over", "本行补货超库容"
        elif group_gap > 0:
            status, label = "plan_group_over", "本行未超，店铺合计超库容"
        elif missing:
            status, label = "plan_incomplete", "本行未超，店铺合计数据不足"
        else:
            status, label = "plan_within", "本次补货未超库容"
    result.update(capacity_status=status, capacity_status_label=label,
                  capacity_row_status_label=row_label, capacity_group_status_label=group_label)
    estimate = "；商品类型按最近月仓储费分类估算" if context.get("storage_type") and not context.get("type_confirmed") else ""
    result["capacity_product_note"] = f"{row_label}；{group_label}" + ("；"+reason if reason else "") + estimate
    result["capacity_note"] = "；".join([result["capacity_product_note"], f"本行体积：{_volume_text(volume) if volume is not None else '缺失'} m³",
        f"店铺同类型已知合计：{_volume_text(total)} m³", f"来源剩余：{_volume_text(remaining) if remaining is not None else '未提供'} m³",
        "仅预警，不修改补货数量；不重复扣除在库和开放货件"])
    def display(value):
        if value is None:
            return "未提供"
        return _volume_text(value) if abs(value) < Decimal(".0001") else format(value, ".4f").rstrip("0").rstrip(".")
    if status in {"plan_within","plan_row_over","plan_group_over","plan_incomplete"}:
        tooltip = [label, f"本行：{display(volume)} m³ / 剩余：{display(remaining)} m³",
                   f"店铺同类型合计：{display(total)} m³；" + (f"超出：{display(number(result['capacity_shortfall_m3']))} m³" if result["capacity_shortfall_m3"] is not None else group_label)]
    else:
        tooltip = [label, f"本行体积：{display(volume)} m³" + (f" / 剩余：{display(remaining)} m³" if remaining is not None else ""), reason or "补货数量为0，不新增占用"]
    tooltip.append(f"数据日期：{result.get('capacity_snapshot_date') or '未提供'}" + ("（月末归档）" if context.get("archive_mode") else "") + " · 仅预警，数量不变")
    result["capacity_tooltip"] = "\n".join(tooltip)
    result["capacity_detail"] = "\n".join([result["capacity_note"], result["capacity_match_basis"], result["capacity_quota_summary"], result["capacity_plan_scope"]])
    return result


class ReplenishmentCapacityService:
    def __init__(self, connect: Callable):
        self.connect = connect

    def _query_source(self, job: tuple) -> tuple:
        name, sql, args = job
        with self.connect() as conn, conn.cursor() as cursor:
            cursor.execute(sql, args)
            return name, cursor.fetchall()

    def _load_source_queries(self, source: dict, jobs: list[tuple]) -> None:
        # Each worker owns its connection. map preserves batch order, including duplicates.
        with ThreadPoolExecutor(max_workers=3) as pool:
            for name, records in pool.map(self._query_source, jobs):
                source[name].extend(records)

    def enrich(self, rows: list[dict], snapshot: date, demand_rows: list[dict] | None = None) -> None:
        if not rows:
            return
        if not any((r.get("seller_name_new") or r.get("store")) and (r.get("seller_sku_adj") or r.get("msku")) for r in rows):
            source = {"error": "店铺或MSKU关联字段未完整"}
        else:
            try:
                source = self._load([*(demand_rows or []), *rows], snapshot)
            except pymysql.MySQLError:
                source = {"error": "库容数据暂不可读取，请核对来源服务"}
        _index_sources(source)
        inputs = {_row_key(r):r for r in [*(demand_rows or []), *rows]}
        contexts = {key:self._context(row, source) for key,row in inputs.items()}
        groups, unknown = {}, {}
        if demand_rows is not None:
            for row in {_row_key(r):r for r in demand_rows}.values():
                qty = number(row.get("replenish_qty"))
                if qty is None or qty <= 0:
                    continue
                context = contexts[_row_key(row)]
                base = (context.get("account") or _row_key(row)[1], _row_key(row)[0])
                kind, unit = context.get("storage_type"), number(context.get("unit_volume"))
                if not kind:
                    unknown[base] = unknown.get(base, 0)+1
                    continue
                group = groups.setdefault((*base,kind), {"volume":Decimal(0), "missing":0})
                if unit is None or unit <= 0:
                    group["missing"] += 1
                else:
                    group["volume"] += qty*unit
        for row in rows:
            context = contexts[_row_key(row)]
            result = evaluate_capacity(snapshot, row.get("replenish_qty"), context)
            if demand_rows is not None:
                base = (context.get("account") or _row_key(row)[1], _row_key(row)[0])
                group = groups.get((*base, context.get("storage_type")), {"volume":Decimal(0), "missing":0})
                result = apply_plan_comparison(result, context, row.get("replenish_qty"), group,
                                               unknown.get(base,0), snapshot)
            row.update(result)

    def _load(self, rows: list[dict], snapshot: date) -> dict:
        cutoff = datetime.combine(snapshot + timedelta(days=1), time.min)
        current_day = datetime.now(timezone(timedelta(hours=8))).date()
        archive = snapshot.strftime("%Y-%m") < current_day.strftime("%Y-%m")
        with self.connect() as conn, conn.cursor() as cursor:
            def query(sql, args=()):
                cursor.execute(sql, args)
                return cursor.fetchall()
            source = {"sellers": query("select sid, name, account_name, seller_account_id, country from dwd_datasync.lx_basic_seller")}
            source.update(archive_mode=archive, reference_date=snapshot.replace(day=monthrange(snapshot.year, snapshot.month)[1]) if archive else current_day)
            source["limits"] = query("select sid, storage_type, snapshot_month, month, sub_item_storage_type, sub_item_vol_unit_type, vol_stock_max, vol_stock_remain, create_time, source_update_time, fba_allocation_type from dwd_datasync.lx_replenishment_restriction where delete_flag=0 and month=%s and snapshot_month=%s order by create_time desc, source_update_time desc", (snapshot.replace(day=1), snapshot.strftime("%Y-%m")))
            source["groups"] = []
            try:
                batches = query("select batch_id, business_date from dws_datasync.fba_capacity_task_batch where delete_flag=0 and refresh_status='SUCCESS' and capacity_month=%s order by business_date desc, batch_id desc limit 1", (snapshot.replace(day=1),))
                if batches and batches[0].get("batch_id"):
                    source["groups"] = query("select seller_account_id, account_name, capacity_group, capacity_group_name, representative_sid from dws_datasync.fba_capacity_group_snapshot where batch_id=%s and delete_flag=0", (batches[0]["batch_id"],))
            except pymysql.MySQLError:
                # Group metadata is auxiliary; its absence must not discard source quotas.
                source["group_note"] = "共享组数据暂不可读取；额度仍按店铺sid展示"
            mskus = sorted({str(row.get("seller_sku_adj") or row.get("msku") or "") for row in rows} - {""})
            skus = sorted({str(row.get("max_sku") or row.get("sku") or "") for row in rows} - {""})
            listing_targets = {}
            source["_seller_matches"] = {}
            for row in rows:
                site, store, msku = _row_key(row)
                countries = EU_COUNTRIES if site == "欧洲站" else ({"英国"} if site == "英国站" else {"美国"})
                sellers, _ = _matching_sellers(site, store, countries, source)
                listing_targets.setdefault(msku, set()).update(str(s["sid"]) for s in sellers)
            source["fees"], source["packages"], source["warehouse_types"], source["listing_dimensions"] = [], [], [], []
            fee_months = query("select max(month_of_charge) as report_month from dwd_datasync.lx_statistics_storage_fee_month where month_of_charge<=%s and create_time<%s", (snapshot.strftime("%Y-%m"), cutoff))
            report_month = fee_months[0].get("report_month") if fee_months else None
            jobs = []
            for offset in range(0, len(mskus), SOURCE_KEY_BATCH_SIZE):
                if not report_month:
                    break
                keys = mskus[offset:offset+SOURCE_KEY_BATCH_SIZE]
                placeholders = ",".join(["%s"] * len(keys))
                jobs.append(("fees", f"select seller_name, country, seller_sku, product_size_tier, longest_side, median_side, shortest_side, measurement_units, item_volume, volume_units, month_of_charge from dwd_datasync.lx_statistics_storage_fee_month where seller_sku in ({placeholders}) and month_of_charge=%s and create_time<%s", (*keys, report_month, cutoff)))
            for offset in range(0, len(mskus), SOURCE_KEY_BATCH_SIZE):
                keys = mskus[offset:offset+SOURCE_KEY_BATCH_SIZE]
                placeholders = ",".join(["%s"] * len(keys))
                jobs.append(("warehouse_types", f"select `店铺` as store_names, `MSKU` as msku, `SKU` as sku, `仓储类型` as storage_type from temporary_dwd.`FBA库存明细` where `MSKU` in ({placeholders})", keys))
                target_groups = {}
                for key in keys:
                    sids = tuple(sorted(listing_targets.get(key, set())))
                    if sids:
                        target_groups.setdefault(sids, []).append(key)
                scope_clauses, scope_args = [], []
                for sids, target_keys in target_groups.items():
                    sid_placeholders = ",".join(["%s"]*len(sids))
                    key_placeholders = ",".join(["%s"]*len(target_keys))
                    scope_clauses.append(f"(sid in ({sid_placeholders}) and binary seller_sku in ({key_placeholders}))")
                    scope_args.extend((*sids, *target_keys))
                scope_sql = " and ("+" or ".join(scope_clauses)+")" if scope_clauses else ""
                jobs.append(("listing_dimensions", f"select listing.sid, listing.seller_sku, listing.dimension_info, listing.create_time from (select id, row_number() over(partition by sid, binary seller_sku order by coalesce(update_time,create_time) desc,id desc) as source_rank from ods_datasync.lx_sales_mws_listing where delete_flag=0 and seller_sku in ({placeholders}){scope_sql}) latest_dimensions join ods_datasync.lx_sales_mws_listing listing on listing.id=latest_dimensions.id where latest_dimensions.source_rank=1", (*keys, *scope_args)))
            for offset in range(0, len(skus), SOURCE_KEY_BATCH_SIZE):
                keys = skus[offset:offset+SOURCE_KEY_BATCH_SIZE]
                placeholders = ",".join(["%s"] * len(keys))
                jobs.append(("packages", f"select sku, cg_package_length, cg_package_width, cg_package_height from dwd_datasync.lx_product_local_product_info where sku in ({placeholders})", keys))
        self._load_source_queries(source, jobs)
        return source

    def _context(self, row: dict, source: dict) -> dict:
        if source.get("error"):
            return {"fatal": True, "problems": [source["error"]]}
        site = row.get("country_category") or row.get("country")
        store = str(row.get("seller_name_new") or row.get("store") or "").strip().casefold()
        msku = str(row.get("seller_sku_adj") or row.get("msku") or "")
        sku = str(row.get("max_sku") or row.get("sku") or "")
        group_code = {"欧洲站": "EU", "英国站": "UK", "北美站": "NA"}.get(site)
        countries = EU_COUNTRIES if group_code == "EU" else ({"英国"} if group_code == "UK" else {"美国"})
        sellers, prefix_match = _matching_sellers(site, store, countries, source)
        accounts = {str(s.get("seller_account_id")) for s in sellers if s.get("seller_account_id") is not None}
        context = {"problems": [], "type_confirmed": False, "group_confirmed": False,
                   "archive_mode": source.get("archive_mode", False), "reference_date": source.get("reference_date")}
        if not sellers or len(accounts) > 1:
            context.update(fatal=True, problems=["店铺与卖家账号关联不唯一或未找到"])
            return context
        account = next(iter(accounts)) if len(accounts) == 1 else ""
        context["account"] = account
        sids = {str(s.get("sid")) for s in sellers}
        groups = [g for g in source.get("groups", []) if account and str(g.get("seller_account_id")) == account and g.get("capacity_group") == group_code and str(g.get("representative_sid")) in sids]
        if len(groups) == 1:
            group = groups[0]
            context.update(group=f"{group.get('account_name') or store} / {group.get('capacity_group_name') or group_code}", group_confirmed=True)
        names = {str(s.get("name") or "").casefold() for s in sellers}
        if group_code == "NA":
            context["group"] = "美国站点额度；不合并加拿大和墨西哥"
        fees = [f for f in _source_records(source, "fees", msku) if str(f.get("seller_name") or "").casefold() in names and f.get("seller_sku") == msku and f.get("country") in countries]
        storage_type = None
        if fees:
            latest_month = max(str(f.get("month_of_charge") or "") for f in fees)
            fees = [f for f in fees if f.get("month_of_charge") == latest_month]
            types = {f.get("product_size_tier") for f in fees}
            storage_type = {"Standard-Size": "Standard", "Oversize": "Oversize"}.get(next(iter(types))) if len(types) == 1 else None
            volumes = [dimensions_m3(f, ("longest_side", "median_side", "shortest_side"), str(f.get("measurement_units") or "").lower()) or volume_m3(f.get("item_volume"), f.get("volume_units")) for f in fees]
            volumes = [v for v in volumes if v is not None and v > 0]
            if storage_type:
                context["type_label"] = TYPE_LABELS[storage_type] + "（历史报表参考）"
            if volumes:
                context.update(unit_volume=max(volumes), measurement_source=f"{latest_month}月仓储费长宽高；同对象多仓/多国取最大单件体积")
        warehouse = [r for r in _source_records(source, "warehouse_types", msku) if str(r.get("msku") or "") == msku
                     and names.intersection(part.strip().casefold() for part in str(r.get("store_names") or "").replace("，",",").split(","))]
        actual_types = {STORAGE_TYPES.get(str(r.get("storage_type") or "").strip().casefold()) for r in warehouse}
        actual_types.discard(None)
        if len(actual_types) == 1:
            storage_type = next(iter(actual_types))
            context.update(type_confirmed=True, type_label=TYPE_LABELS[storage_type])
            context["measurement_source"] = "商品类型：temporary_dwd.FBA库存明细.仓储类型；"+str(context.get("measurement_source") or "")
        elif len(actual_types) > 1:
            storage_type = None
            context["type_conflict"] = True
        elif storage_type:
            context["measurement_source"] = "商品类型按最近月仓储费尺寸分类估算；"+str(context.get("measurement_source") or "")
        context["storage_type"] = storage_type
        listing_volumes = [_listing_volume(r) for r in _source_records(source, "listing_dimensions", msku)
                           if str(r.get("sid")) in sids and str(r.get("seller_sku") or "") == msku]
        listing_volumes = [v for v in listing_volumes if v is not None and v > 0]
        if listing_volumes:
            context["unit_volume"] = max(listing_volumes)
            context["measurement_source"] = str(context.get("measurement_source") or "")+"；体积：最新Listing包装长宽高，多站点取最大值"
        # Quota lookup is by this store's own site ids, independent of group/size metadata.
        own = {}
        if "_quota_lookup" in source:
            # Retain source ordering across sites, including which equal-timestamp row wins.
            ordered = sorted((entry for sid in sids for entry in source["_quota_lookup"].get(sid, [])), key=lambda entry: entry[0])
            limit_records = [entry[1] for entry in ordered]
        else:
            limit_records = source.get("limits", [])
        for record in limit_records:
            if str(record.get("sid")) in sids:
                kind = record.get("sub_item_storage_type") or record.get("storage_type")
                own.setdefault((str(record.get("sid")), kind), record)
        limits = list(own.values())
        candidates = [r for r in limits if (r.get("sub_item_storage_type") or r.get("storage_type")) == storage_type] if storage_type else limits
        context["comparison_limits"] = candidates if storage_type else []
        context["quota_summary"] = _quota_summary(candidates or limits, sellers)
        context["match_basis"] = f"店铺 {store} → 当前类别sid={','.join(sorted(sids))} → DWD额度明细；各站点/类型不相加"
        if prefix_match:
            context["match_basis"] += "；店铺名称沿用补货ETL的首段匹配规则"
        if source.get("group_note"):
            context["match_basis"] += "；" + source["group_note"]
        metadata = candidates or limits
        if metadata:
            # Preserve all source information even without a product type or a shared group.
            dates = [_day(r.get("create_time") or r.get("source_update_time")) for r in metadata]
            dates = [d for d in dates if d is not None]
            context.update(month=_text(metadata[0].get("month")), snapshot_time=min(dates) if dates else None,
                           source_time=max((_text(r.get("source_update_time")) for r in metadata), default=""),
                           allocation_type=2 if all(str(r.get("fba_allocation_type")) == "2" for r in metadata) else 1)
        if not limits or (storage_type and not candidates):
            context.update(source_status="not_found", month=limits[0].get("month") if limits else None)
            context["problems"].append("店铺对应sid、月份或仓储类型的额度未提供；不借用其他店铺或历史月份额度")
        elif not storage_type:
            context.update(source_status="type_unmapped", type_label="商品类型未对应；店铺各类型额度已列出")
        else:
            representative = [r for r in candidates if len(groups) == 1 and storage_type == "Standard" and str(r.get("sid")) == str(groups[0].get("representative_sid"))]
            chosen = representative[0] if representative else candidates[0]
            if not representative and len({_quota_signature(r) for r in candidates}) > 1:
                context["source_status"] = "station_difference"
                context["match_basis"] += "；站点额度有差异，分别列出，不选择任意站点作为共享额度"
            else:
                context.update(month=_text(chosen.get("month")), source_time=chosen.get("source_update_time"),
                               snapshot_time=chosen.get("create_time") or chosen.get("source_update_time"),
                               maximum=chosen.get("vol_stock_max"), remaining=chosen.get("vol_stock_remain"),
                               unit=chosen.get("sub_item_vol_unit_type"), allocation_type=chosen.get("fba_allocation_type"))
                context["match_basis"] += f"；展示来源sid={chosen.get('sid')}"
                if representative:
                    context["match_basis"] += "（经现有Standard共享组代表站点关联，数值仍读取DWD）"
                elif len(candidates) > 1:
                    context["match_basis"] += "（各站点额度数值一致，仅展示一份；未据此认定共享关系）"
        if context.get("unit_volume") is None:
            volumes = [dimensions_m3(p, ("cg_package_length", "cg_package_width", "cg_package_height"), "cm") for p in _source_records(source, "packages", sku) if str(p.get("sku") or "") == sku]
            volumes = [v for v in volumes if v is not None and v > 0]
            if volumes:
                context.update(unit_volume=max(volumes), measurement_source=str(context.get("measurement_source") or "")+"；体积：领星当前SKU包装尺寸估算")
        return context
