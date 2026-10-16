"""Read remote sources and calculate return decisions; no routes or database writes.

Run from the repository root with python -m return_goods_data.remote_sources.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import rules
from .connection import apply_database_ini_env, _source_connect
from .enrichment import (
    attach_inventory_days, attach_price_changes, currency, enrich,
    expand_auto_targets, index_snapshot, index_budget_snapshot, merge_days,
)
from .keys import business_key
from .presentation import prepare_page_data


# Preserve the existing MSKU normalization used by the daily data task.
MSKU_SQL = """case when char_length(substring_index(seller_sku,',',1))>16
    then replace(substring_index(substring_index(seller_sku,',',1),'-',1),'amzn.gr.','')
    else substring_index(seller_sku,',',1) end"""


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def category(country):
    code = business_key('', country, '')[1]
    return '英国站' if code in ('gb', 'uk') else (
        '北美站' if code in ('us', 'ca', 'br', 'mx') else '欧洲站')


def read_rows(conn, sql, params):
    # This adapter has no mutation statements or calls to the publishing ETL.
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def inventory_days(raw, warnings):
    grouped = defaultdict(list)
    for row in raw:
        grouped[(row['country_category'], as_date(row['create_time']))].append(row)
    result = defaultdict(list)
    for (cat, day), rows in sorted(grouped.items()):
        captures = {r['create_time'] for r in rows}
        values = [rules.dec(r['afn_fulfillable_quantity']) for r in rows]
        # Multiple captures cannot safely be added as independent inventory.
        valid = len(captures) == 1 and all(v is not None for v in values)
        stock = sum(values, Decimal(0)) if valid else None
        if not valid:
            warnings.append(f'{cat}/{day}库存多次采集或字段缺失，保留缺失而不当作0')
        result[cat].append(dict(day=day, stock=stock, inventory_only=True))
    return result


def performance_days(raw, warnings):
    latest = {}
    for row in raw:
        if as_date(row['start_date']) != as_date(row['end_date']):
            continue
        key = (as_date(row['start_date']), row['seller_name'], row['seller_sku'],
               row['country'], row.get('asin'), row.get('local_sku'))
        old = latest.get(key)
        if old is None or (str(row['create_time']), row['id']) > (str(old['create_time']), old['id']):
            latest[key] = row
    grouped = defaultdict(list)
    for row in latest.values():
        grouped[(category(row['country']), row['country'], as_date(row['start_date']))].append(row)
    result = defaultdict(list)
    for (cat, country, day), rows in sorted(grouped.items()):
        currencies = {currency(r.get('currency_icon'), business_key('', country, '')[1]) for r in rows}
        item = dict(day=day, country=country, local_sku=rows[0].get('local_sku'),
                    financial_currency=next(iter(currencies)) if len(currencies) == 1 else None)
        for field, source in [('qty', 'volume'), ('revenue', 'amount'),
                              ('profit', 'predict_gross_profit'), ('sessions', 'sessions_total'),
                              ('ad_spend', 'spend')]:
            values = [rules.dec(r.get(source)) for r in rows]
            item[field] = sum(values, Decimal(0)) if all(v is not None for v in values) else None
        if len(currencies) != 1 or not next(iter(currencies), ''):
            item['revenue'] = item['profit'] = item['ad_spend'] = None
            warnings.append(f'{country}/{day}经营金额币种无法统一，利润保留待核')
        result[cat].append(item)
    return result


def evaluation_days(country_rows):
    """Never sum different currencies for category-level profit evaluation."""
    safe = [dict(r) for r in country_rows]
    currencies = defaultdict(set)
    for row in safe:
        if not row.get('inventory_only'):
            currencies[row['day']].add(row.get('financial_currency'))
    for row in safe:
        if not row.get('inventory_only') and (len(currencies[row['day']]) != 1 or None in currencies[row['day']]):
            row['revenue'] = row['profit'] = row['ad_spend'] = None
    return merge_days(safe)


def read_history(conn, store, msku, cutoff, warnings):
    inventory = read_rows(conn, """select create_time,country_category,afn_fulfillable_quantity
        from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
        where seller_name_new=%s and seller_sku_adj=%s and create_time<%s
        order by create_time""", (store, msku, cutoff + timedelta(days=1)))
    performance = read_rows(conn, f"""select id,relate_id,create_time,start_date,end_date,
        seller_name,seller_sku,country,asin,local_sku,currency_icon,
        volume,amount,predict_gross_profit,sessions_total,spend
        from dwd_datasync.lx_statistics_product_performance
        where substring_index(seller_name,'-',1)=%s and ({MSKU_SQL})=%s
          and start_date<%s and date(start_date)=date(end_date)""",
        (store, msku, cutoff + timedelta(days=1)))
    stocks = inventory_days(inventory, warnings)
    business = performance_days(performance, warnings)
    return {cat: attach_inventory_days(stocks.get(cat, []) + business.get(cat, []))
            for cat in stocks.keys() | business.keys()}


def read_settings(conn, store, msku, settings_date):
    end = settings_date + timedelta(days=1)
    listing_rows = read_rows(conn, f"""select date(create_time) snapshot_date,
        substring_index(seller_name,'-',1) seller_name_new,marketplace country,
        seller_sku,landed_price price,currency_code org_currency_icon
        from dwd_datasync.lx_sales_mws_listing
        where substring_index(seller_name,'-',1)=%s and ({MSKU_SQL})=%s and create_time<%s""",
        (store, msku, end))
    for row in listing_rows:
        row['snapshot_date'] = as_date(row['snapshot_date'])
        row['seller_sku'] = msku
    listings = index_snapshot(listing_rows, settings_date)
    ladder_rows = read_rows(conn, """select `数据日期` snapshot_date,`新店铺` seller_name_new,
        `国家` country,msku seller_sku,`币种` currency,
        `10毛利润价格` margin_price_10,`15毛利润价格` margin_price_15,
        `20毛利润价格` margin_price_20,`25毛利润价格` margin_price_25,
        `30毛利润价格` margin_price_30,`35毛利润价格` margin_price_35
        from temporary_dwd.`在库节点_输出定价表`
        where `新店铺`=%s and msku=%s and `数据日期`<%s""", (store, msku, end))
    for row in ladder_rows:
        row['snapshot_date'] = as_date(row['snapshot_date'])
    budgets = read_rows(conn, """select biz_date,seller_name_new,country,seller_sku_adj,
        currency_code,monthly_ad_budget_original,weekly_ad_budget_original
        from dws_datasync.dws_monthly_ad_budget_detail
        where seller_name_new=%s and seller_sku_adj=%s and biz_date<=%s""",
        (store, msku, settings_date))
    for row in budgets:
        row['biz_date'] = as_date(row['biz_date'])
    changes = read_rows(conn, """select id source_id,date(finish_time) adjust_date,
        cast(finish_time as datetime) finish_time,substring_index(store_name,'-',1) seller_name_new,
        marketplace country,msku,currency_icon currency,
        adjust_before_obj_standard_price price_before,adjust_after_obj_standard_price price_after
        from temporary_APP.lx_sale_adjust_price_queue
        where delete_flag=0 and finish_time is not null and finish_time<>''
          and finish_time<%s and substring_index(store_name,'-',1)=%s and msku=%s
          and processing_status_text='调价成功'""", (end, store, msku))
    for row in changes:
        row['adjust_date'] = as_date(row['adjust_date'])
    attach_price_changes(listings, changes, settings_date)
    return listings, index_snapshot(ladder_rows, settings_date), index_budget_snapshot(budgets, settings_date)


def read_ads(conn, store, msku, cutoff, settings_date, warnings):
    """Read only groups associated with this product, never the entire object snapshot."""
    snapshot = read_rows(conn, """select max(snapshot_date) day
        from dws_datasync.dws_sp_bid_object_snapshot_daily where snapshot_date<=%s""", (settings_date,))[0]['day']
    if snapshot is None:
        raise RuntimeError('截止日期没有广告对象快照，不能判定该商品没有广告')
    objects = read_rows(conn, """select * from dws_datasync.dws_sp_bid_object_snapshot_daily
        where snapshot_date=%s and base_store_name=%s and msku=%s""", (snapshot, store, msku))
    objects = [o for o in objects if rules.strategy_country(o.get('country_code'))]
    groups = sorted({tuple(o[k] for k in ('profile_id', 'campaign_id', 'ad_group_id')) for o in objects})
    if not groups:
        return dict(objects=[], by_product={}, daily={}, common_end=None)
    placeholders = ','.join(['(%s,%s,%s)'] * len(groups))
    scoped = f'(profile_id,campaign_id,ad_group_id) in ({placeholders})'
    group_params = tuple(v for group in groups for v in group)
    end = settings_date + timedelta(days=1)
    targets = read_rows(conn, f"""select profile_id,campaign_id,ad_group_id,target_id,bid,state,expression,create_time
        from ods_datasync.lx_advertising_sp_targets where {scoped}
          and expression_type='auto' and coalesce(delete_flag,0)=0
          and create_time<%s and coalesce(update_time,create_time)<%s""", (*group_params, end, end))
    objects = expand_auto_targets(objects, targets)
    tables = ['lx_advertising_sp_keyword_reports', 'lx_advertising_sp_product_ad_reports',
              'lx_advertising_sp_ad_group_reports']
    if targets:
        tables.append('lx_advertising_sp_query_word_reports')
    dates = [read_rows(conn, f'select max(report_date) day from ods_datasync.{table} where report_date<=%s',
                       (cutoff,))[0]['day'] for table in tables]
    common = min(as_date(d) for d in dates) if all(dates) else None
    daily = defaultdict(list)
    if common is None:
        warnings.append('广告完整报表日期缺失，不能评价返场广告效果')
    else:
        start, stop = common - timedelta(days=20), common - timedelta(days=7)
        manual = read_rows(conn, f"""select profile_id,campaign_id,ad_group_id,keyword_id object_id,
            report_date day,clicks,cost,orders_7d orders,sales_7d sales,impressions
            from (select r.*,row_number() over(partition by profile_id,campaign_id,ad_group_id,
              keyword_id,report_date order by id desc) rn
              from ods_datasync.lx_advertising_sp_keyword_reports r
              where {scoped} and report_date between %s and %s) t
            where rn=1 and coalesce(delete_flag,0)=0""", (*group_params, start, stop))
        for row in manual:
            daily[tuple(str(row[k]) for k in ('profile_id', 'campaign_id', 'ad_group_id', 'object_id'))].append(row)
        if targets:
            automatic = read_rows(conn, f"""select profile_id,campaign_id,ad_group_id,target_id object_id,report_date day,
                case when count(clicks)=count(*) then sum(clicks) end clicks,
                case when count(cost)=count(*) then sum(cost) end cost,
                case when count(orders_7d)=count(*) then sum(orders_7d) end orders,
                case when count(sales_7d)=count(*) then sum(sales_7d) end sales,
                case when count(impressions)=count(*) then sum(impressions) end impressions
                from (select r.*,row_number() over(partition by profile_id,campaign_id,ad_group_id,
                  target_id,report_date,`query` order by id desc) rn
                  from ods_datasync.lx_advertising_sp_query_word_reports r
                  where {scoped} and report_date between %s and %s) t
                where rn=1 and coalesce(delete_flag,0)=0 and target_id is not null
                group by profile_id,campaign_id,ad_group_id,target_id,report_date""", (*group_params, start, stop))
            for row in automatic:
                daily[('auto', *(str(row[k]) for k in ('profile_id', 'campaign_id', 'ad_group_id', 'object_id')))].append(row)
    by_product = defaultdict(list)
    for obj in objects:
        by_product[business_key(obj.get('base_store_name') or obj.get('seller_name'),
                                obj.get('country_code'), obj.get('msku'))].append(obj)
    return dict(objects=objects, by_product=by_product, daily=daily, common_end=common)


def calculate(store, msku, cutoff, settings_date):
    if settings_date > cutoff:
        raise ValueError('历史评价不能使用未来设置；settings-date不得晚于snapshot-date')
    apply_database_ini_env()
    warnings = ['广告ACOS采用固定20%目标、50%上限分档；成熟零单按点击分档20—39次降10%、40次及以上降20%；不区分日销、不使用CPA及预算消耗；真实余额、广告操作记录与预测利润需核验',
                '历史查询按业务日期重算，源表后续修订不等于当时已知数据；不承诺双时间历史还原']
    with _source_connect() as conn:
        histories = read_history(conn, store, msku, cutoff, warnings)
        listings, ladders, budgets = read_settings(conn, store, msku, settings_date)
        ads = read_ads(conn, store, msku, cutoff, settings_date, warnings)
    output = []
    for cat, rows in sorted(histories.items()):
        days = evaluation_days(rows)
        events = rules.build_events(days)
        if not events or events[-1]['return_date'] < cutoff - timedelta(days=179):
            continue
        detail = rules.evaluate_event(days, events[-1], cutoff)
        summary, detail = enrich(detail, (store, cat, msku), rows,
                                 listings, ladders, budgets, ads, cutoff)
        output.append(dict(summary=summary, detail=detail))
    return dict(rule_version=rules.RULE_VERSION, data_date=cutoff, settings_date=settings_date,
                scope=dict(store=store, msku=msku), source='remote', database_writes=0,
                warnings=warnings, products=output,
                page_data=prepare_page_data(output, dict(data_date=cutoff, settings_date=settings_date), all_rows=True))


def main():
    parser = argparse.ArgumentParser(description='远端只读取数及返场决策达标计算，不提供路由或执行流程')
    parser.add_argument('--store', required=True)
    parser.add_argument('--msku', required=True)
    parser.add_argument('--snapshot-date', required=True, type=date.fromisoformat)
    parser.add_argument('--settings-date', type=date.fromisoformat)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = calculate(args.store, args.msku, args.snapshot_date, args.settings_date or args.snapshot_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, default=json_value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), products=len(result['products']), database_writes=0)))


if __name__ == '__main__':
    main()
