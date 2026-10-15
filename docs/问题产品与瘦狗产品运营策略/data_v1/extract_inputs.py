"""提取第一版样本和来源事实到本地；不产生动作、不写数据库。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path

from inspect_sources import SOURCES, connect


COUNTRIES = ("美国", "英国", "德国", "法国", "意大利", "西班牙", "荷兰")

# 明确选取输入字段，不读取上游旧规则的 suggested_bid / recommendation_status 等。
FIELDS = {
    "cost": "数据日期 统计窗口开始日期 统计窗口结束日期 销售数据截止日期 国家 店铺名 msku asin 币种 近30天销量 近30天订单数 近30天净销售额_cny 近30天订单毛利润_cny 广告成本_cny 成本状态 对账状态 数据质量说明 公式版本".split(),
    "pricing": "数据日期 国家 国家类别 店铺名 新店铺 msku asin 币种 listing价格 5毛利润价格 10毛利润价格 15毛利润价格 20毛利润价格 25毛利润价格 30毛利润价格 近30天销量 近30天净销售额 近30天结算毛利润 近30天结算毛利率 近30天广告花费 近30天ACOAS 站点可售库存 可用库存 实际在途 价格备注 数据异常备注 含广告定价异常备注".split(),
    "inventory": "id create_time sid name_dianpu name_share seller_sku asin fnsku afn_fulfillable_quantity available_total total_fulfillable_quantity afn_inbound_working_quantity afn_inbound_shipped_quantity afn_inbound_receiving_quantity reserved_customerorders reserved_fc_transfers reserved_fc_processing".split(),
    "bid_objects": "snapshot_date row_key mature_start mature_end source_keyword_days source_ad_group_days source_product_ad_days profile_id sid base_store_name seller_name country_code currency_code campaign_id campaign_state_current campaign_serving_status ad_group_id ad_group_state_current ad_group_serving_status targeting_type object_type object_id object_text object_state_current object_serving_status match_type msku asin msku_mapping_status associated_msku_count period_msku_count current_enabled_msku_count product_metric_owner_flag impressions clicks cost orders sales same_sku_attributed_orders_30d same_sku_attributed_sales_30d current_bid bid_lower_limit bid_upper_limit source_latest_create_time".split(),
    "search_terms": "snapshot_date row_key mature_start mature_end source_search_term_days source_product_ad_days profile_id sid seller_name country_code currency_code campaign_id campaign_state_current ad_group_id ad_group_state_current target_id target_state_current targeting_type is_auto_campaign is_manual_campaign target_text match_type search_term search_term_normalized search_term_type msku asin msku_mapping_status period_msku_candidates current_msku_candidates term_protection_complete protection_missing_codes is_brand_term is_core_category_term is_new_product_term clicks cost orders_30d sales_30d same_orders_30d same_sales_30d attribution_30d_mature source_latest_create_time".split(),
    "budget": "biz_date country_category country seller_name_new seller_sku_adj currency_code exchange_rate_cny monthly_ad_budget_original monthly_ad_budget_cny weekly_ad_budget_original weekly_ad_budget_cny site_total_budget_cny total_budget_pool_cny".split(),
}
SKU_COLUMN = {"inventory": "seller_sku", "budget": "seller_sku_adj"}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def group_product(rows, country, store, sku):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row[country], row[store], row[sku])].append(row)
    return grouped


def build_base(cohort, raw):
    # 只采用来源明确给出的别名关系，不删除后缀猜店铺。
    aliases = defaultdict(set)
    for row in raw["pricing"]:
        if row["新店铺"]:
            aliases[(row["国家"], row["店铺名"])].add(row["新店铺"])
    cost_index, price_index = defaultdict(list), defaultdict(list)
    for row in raw["pricing"]:
        mapping = aliases[(row["国家"], row["店铺名"])]
        if len(mapping) == 1:
            price_index[(row["国家"], next(iter(mapping)), row["msku"])].append(row)
    for row in raw["cost"]:
        mapping = aliases[(row["国家"], row["店铺名"])]
        if len(mapping) == 1:
            cost_index[(row["国家"], next(iter(mapping)), row["msku"])].append(row)
    products = group_product(cohort, "country", "store", "msku")
    base = []
    for product_key, tags in sorted(products.items()):
        roles = sorted({"problem" if int(tag["label_id"]) == 1304 else "dog" for tag in tags})
        costs, prices = cost_index[product_key], price_index[product_key]
        diagnostics = []
        if len(roles) != 1:
            diagnostics.append("role_conflict")
        for name, matched in (("cost", costs), ("pricing", prices)):
            if not matched:
                diagnostics.append(f"{name}_missing_mapped_key")
            elif len(matched) > 1:
                diagnostics.append(f"{name}_ambiguous_mapped_key")
        base.append({"label_date": tags[0]["data_date"], "country": product_key[0],
                     "store": product_key[1], "msku": product_key[2], "source_roles": roles,
                     "cost_match_count": len(costs), "pricing_match_count": len(prices),
                     "cost_input": costs[0] if len(costs) == 1 else None,
                     "pricing_input": prices[0] if len(prices) == 1 else None,
                     "diagnostics": diagnostics})
    return base, [dict(country=country, source_store=store, base_stores=sorted(mapped))
                  for (country, store), mapped in sorted(aliases.items())]


def finish_snapshot(output, manifest, cohort, raw):
    base, mapping = build_base(cohort, raw)
    write_json(output / "store_mapping.json", mapping)
    write_json(output / "product_base.json", base)
    manifest["products"] = len(base)
    manifest["role_counts"] = dict(Counter(role for row in base for role in row["source_roles"]))
    manifest["diagnostic_counts"] = dict(Counter(code for row in base for code in row["diagnostics"]))
    manifest["store_mapping_source"] = "pricing.国家 + 店铺名 -> 新店铺；仅接受唯一关系"
    manifest["ambiguous_store_mappings"] = sum(len(row["base_stores"]) > 1 for row in mapping)
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, default=str), flush=True)


def extract(output: Path):
    # 每次单独目录，不覆盖既有批次。manifest 只在全部提取成功后生成。
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"run_at": datetime.now().isoformat(timespec="seconds"),
                "status": "input_snapshot_only", "sources": {},
                "notes": ["来源各取当前最新日期并保留原日期，尚不代表业务日期已对齐。",
                          "广告及库存按样本MSKU提取候选，尚未按店铺/国家唯一归属。",
                          "未查到广告不等于未开启广告；需完整实体清单证明。",
                          "预算为额度，未计算扣除基础消耗后的可分配余额。"]}
    raw = {}
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("select max(data_date) as data_date from dws_datasync.`dws_标签表汇总` "
                       "where label_id in (1303,1304) and label_period='30d'")
        label_date = cursor.fetchone()["data_date"]
        if label_date is None:
            raise ValueError("未找到角色标签日期")
        placeholders = ",".join(["%s"] * len(COUNTRIES))
        cursor.execute(
            "select distinct b.data_date, b.country_category, b.country, b.store, b.msku, b.label_id "
            "from dws_datasync.`dws_标签表汇总` b "
            "where b.data_date=%s and b.label_id in (1303,1304) and b.label_period='30d' "
            f"and b.country in ({placeholders}) and exists ("
            "select 1 from dws_datasync.`dws_标签表汇总` a where a.data_date=b.data_date "
            "and a.label_id=301 and a.label_period='current' and a.store=b.store and a.msku=b.msku) "
            "order by b.country,b.store,b.msku,b.label_id", (label_date, *COUNTRIES))
        cohort = cursor.fetchall()
        if not cohort:
            raise ValueError("最新角色日没有符合301交集的样本，不自动回退旧日期")
        write_json(output / "cohort.json", cohort)
        manifest["sources"]["labels"] = {"date": label_date, "rows": len(cohort)}
        skus = sorted({row["msku"] for row in cohort if row["msku"]})
        for alias, schema, table, date_column in SOURCES:
            if alias == "labels":
                continue
            print(f"extracting {alias}", flush=True)
            cursor.execute(f"select max(`{date_column}`) as latest_date from `{schema}`.`{table}`")
            source_date = cursor.fetchone()["latest_date"]
            if source_date is None:
                raise ValueError(f"{alias}: 无来源日期")
            columns = ",".join(f"`{field}`" for field in FIELDS[alias])
            sku_column = SKU_COLUMN.get(alias, "msku")
            rows = []
            for offset in range(0, len(skus), 300):
                batch = skus[offset:offset + 300]
                marks = ",".join(["%s"] * len(batch))
                # 库存按最新入库日期保留该日所有明细；不把全表最大秒级时间当完整快照。
                if alias == "inventory":
                    date_predicate = f"`{date_column}` >= %s and `{date_column}` < date_add(%s, interval 1 day)"
                    day = str(source_date)[:10]
                    parameters = (day, day, *batch)
                else:
                    date_predicate = f"`{date_column}` = %s"
                    parameters = (source_date, *batch)
                cursor.execute(f"select {columns} from `{schema}`.`{table}` "
                               f"where {date_predicate} and `{sku_column}` in ({marks})", parameters)
                rows.extend(cursor.fetchall())
            write_json(output / f"{alias}.json", rows)
            raw[alias] = rows
            manifest["sources"][alias] = {"date": source_date, "rows": len(rows)}

    finish_snapshot(output, manifest, cohort, raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "outputs" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--rebuild", type=Path, help="从已完成原始输入重建映射，不重复查询数据库")
    args = parser.parse_args()
    if args.rebuild:
        def read(name):
            return json.loads((args.rebuild / f"{name}.json").read_text(encoding="utf-8"))
        finish_snapshot(args.rebuild, read("manifest"), read("cohort"), {alias: read(alias) for alias in FIELDS})
    else:
        extract(args.output)
