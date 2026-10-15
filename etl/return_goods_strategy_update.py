"""Publish independent return-strategy snapshots; never execute business actions."""
from __future__ import annotations

import argparse
import hashlib
import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pymysql

from app.services.return_goods_data import ReturnGoodsDataService
from app.services.return_goods_strategy_data import json_default
from app.services import return_goods_strategy_rules as rules
from etl.sp_advertising_recommendations import business_key, _source_connect


DDL = """
create table if not exists dashboard_return_strategy_batch (
 batch_id bigint not null auto_increment primary key,
 data_date date not null, rule_version varchar(100) not null,
 status varchar(16) not null, quality_json json null, error_message varchar(500) null,
 started_at datetime not null default current_timestamp, finished_at datetime null,
 key idx_return_strategy_batch (status,data_date,batch_id)
) engine=InnoDB default charset=utf8mb4;
create table if not exists dashboard_return_strategy_item (
 batch_id bigint not null, event_id char(40) not null,
 seller_name_new varchar(128) not null, country_category varchar(64) not null, msku varchar(128) not null,
 exit_status varchar(16) not null, summary_json json not null, detail_json json not null,
 primary key (batch_id,event_id), key idx_return_strategy_item (batch_id,exit_status)
) engine=InnoDB default charset=utf8mb4;
"""


def optional_read(call, name, warnings):
    try:
        return call()
    except (pymysql.MySQLError, RuntimeError, KeyError, ValueError):
        warnings.append(f'{name}读取失败，相关建议待核')
        return []


def index_snapshot(rows, cutoff):
    result={}
    for row in rows:
        stamp=row.get('snapshot_date',row.get('biz_date'))
        if stamp is None or stamp>cutoff:
            continue
        key=business_key(row.get('seller_name_new'),row.get('country'),row.get('seller_sku',row.get('seller_sku_adj')))
        old=result.get(key)
        if old is None or stamp>old.get('snapshot_date',old.get('biz_date')):
            result[key]=dict(row)
        elif stamp==old.get('snapshot_date',old.get('biz_date')):
            compare=('price','currency','org_currency_icon',*(f'margin_price_{x}' for x in (10,15,20,25,30,35)))
            if any(old.get(k)!=row.get(k) for k in compare):
                old['conflict']=True
    return result


def read_snapshot(conn, table, column, cutoff):
    with conn.cursor() as cur:
        cur.execute(f'select max({column}) d from {table} where {column}<=%s',(cutoff,))
        d=cur.fetchone()['d']
        if d is None:
            return []
        cur.execute(f'select * from {table} where {column}=%s',(d,))
        return cur.fetchall()


def index_budget_snapshot(rows, cutoff):
    result=index_snapshot(rows,cutoff)
    grouped=defaultdict(list)
    for row in rows:
        if row.get('biz_date') is not None and row['biz_date']<=cutoff:
            key=business_key(row.get('seller_name_new'),row.get('country'),row.get('seller_sku_adj'))
            grouped[key].append(dict(row))
    for key,entry in result.items():
        entry['history']=grouped[key]
    return result


def attach_price_changes(listings, rows, cutoff):
    """Only completed, same-currency changes matching the dated current price qualify."""
    latest={}
    for row in rows:
        changed=row.get('adjust_date')
        if not changed or changed>cutoff:
            continue
        key=business_key(row.get('seller_name_new'),row.get('country'),row.get('msku'))
        if key not in latest or row['finish_time']>latest[key]['finish_time']:
            latest[key]=row
    for key,row in latest.items():
        listing=listings.get(key)
        if not listing:
            continue
        before=rules.dec(row.get('price_before'));after=rules.dec(row.get('price_after'))
        if (before is not None and after is not None and before>0 and after>0 and before!=after
                and after==rules.dec(listing.get('price'))
                and currency(row.get('currency'),key[1])
                and currency(row.get('currency'),key[1])==currency(listing.get('org_currency_icon'),key[1])
                and row['adjust_date']<=listing['snapshot_date']):
            listing.update(last_change_date=row['adjust_date'],last_change_source_id=row['source_id'])


def read_price_changes(conn, cutoff):
    with conn.cursor() as cur:
        cur.execute('''select source_id,adjust_date,finish_time,seller_name_new,country,msku,
            currency,price_before,price_after from price_review_adjustment_source
            where adjust_date between %s and %s and finish_time is not null
              and finish_time<%s''',(cutoff-timedelta(days=30),cutoff,cutoff+timedelta(days=1)))
        return cur.fetchall()


def iter_products(conn, cutoff):
    # Inventory has its own calendar; missing business rows must not erase stock.
    fields={'qty':'sales_qty','revenue':'sales_amount','profit':'order_gross_profit','sessions':'sessions_total',
            'ad_spend':'ad_spend'}
    selections=','.join(f'{col} as {name}' for name,col in fields.items())
    # Start from inventory, never the old return pool or business-report coverage.
    # Indexed per-product reads avoid sorting millions of combined historical rows.
    with conn.cursor() as cur:
        cur.execute("""select distinct seller_name_new,country_category,seller_sku_adj
            from dashboard_inventory_daily_snapshot where snapshot_date<=%s
              and seller_name_new is not null and seller_name_new<>''
              and country_category is not null and country_category<>''
              and seller_sku_adj is not null and seller_sku_adj<>''
              and seller_sku_adj not like 'amzn.gr.%%'
            order by country_category,seller_name_new,seller_sku_adj""",(cutoff,))
        keys=cur.fetchall()
        for product in keys:
            key=(product['seller_name_new'],product['country_category'],product['seller_sku_adj'])
            cur.execute('''select snapshot_date day,afn_fulfillable_quantity stock,1 inventory_only
                from dashboard_inventory_daily_snapshot force index (idx_sku)
                where seller_name_new=%s and country_category=%s and seller_sku_adj=%s
                  and snapshot_date<=%s order by snapshot_date''',(*key,cutoff))
            inventory=cur.fetchall()
            events=rules.build_events(inventory)
            if not events or events[-1]['return_date']<cutoff-timedelta(days=179):
                yield key,inventory
                continue
            cur.execute(f'''select country,dt_date day,local_sku,{selections},null stock,0 inventory_only
                from dashboard_product_performance_daily force index (idx_replenishment_lookup)
                where seller_name_new=%s and country_category=%s and seller_sku_adj=%s
                  and dt_date<=%s order by dt_date''',(*key,cutoff))
            yield key,attach_inventory_days(list(cur.fetchall())+list(inventory))


def attach_inventory_days(rows):
    """Use only dated inventory snapshots, including when business rows are absent."""
    stocks={r['day']:r.get('stock') for r in rows if r.get('inventory_only')}
    for row in rows:
        row['stock']=stocks.get(row['day'])
    return rows


def merge_days(rows):
    grouped=defaultdict(list)
    for row in rows:
        grouped[row['day']].append(row)
    result=[]
    for day,members in sorted(grouped.items()):
        item={'day':day}
        business=[r for r in members if not r.get('inventory_only')]
        for key in ('qty','revenue','profit','sessions','ad_spend'):
            values=[rules.dec(r.get(key)) for r in business]
            item[key]=sum(values) if values and all(v is not None for v in values) else None
        stocks=[rules.dec(r.get('stock')) for r in members]
        item['stock']=max(stocks) if all(v is not None for v in stocks) else None
        result.append(item)
    return result


def aggregate_ad_days(rows, returned, common_end, stock_by_day=None):
    common_end=date.fromisoformat(str(common_end)[:10])
    end=common_end-timedelta(days=7)
    start=max(returned,end-timedelta(days=13))
    chosen=[]
    for row in rows:
        day=date.fromisoformat(str(row['day'])[:10])
        stocked=stock_by_day is None or (rules.dec(stock_by_day.get(day)) or Decimal(0))>0
        if start<=day<=end and stocked:
            chosen.append(row)
    out={}
    for k in ('clicks','cost','orders','sales','impressions'):
        values=[rules.dec(r.get(k)) for r in chosen]
        out[k]=sum(values,Decimal(0)) if all(v is not None for v in values) else None
    out.update(days=len({r['day'] for r in chosen}),report_days=sorted({str(r['day'])[:10] for r in chosen}),
               mature=bool(chosen) and all(out[k] is not None for k in ('clicks','cost','orders','sales')),
               mature_start=start,mature_end=end)
    window=[start+timedelta(days=i) for i in range(max(0,(end-start).days+1))]
    stocks_known=stock_by_day is not None and all(rules.dec(stock_by_day.get(d)) is not None for d in window)
    expected={d.isoformat() for d in window if stocks_known and rules.dec(stock_by_day[d])>0}
    out['zero_order_coverage_verified']=stocks_known and expected==set(out['report_days']) and bool(expected)
    return out


CURRENCIES={'欧元':'EUR','英镑':'GBP','美元':'USD','加元':'CAD','日元':'JPY','波兰兹罗提':'PLN',
            '瑞典克朗':'SEK','墨西哥比索':'MXN','巴西雷亚尔':'BRL','土耳其里拉':'TRY',
            '€':'EUR','£':'GBP','￡':'GBP','zł':'PLN','CA$':'CAD','₺':'TRY'}


def currency(value,country=None):
    if value=='kr':
        return 'SEK' if country=='se' else ''
    if value=='$':
        return {'us':'USD','ca':'CAD','mx':'MXN','au':'AUD','sg':'SGD'}.get(country,'')
    return CURRENCIES.get(value,str(value or '').upper())


def retain_exit(current,previous,cutoff):
    if not previous or not previous.get('exit_date'):
        return
    old_date=date.fromisoformat(str(previous['exit_date'])[:10])
    if old_date>cutoff:
        return
    for key in ('exit_status','exit_reasons','confirmation_days','exit_evidence','exit_confirmation'):
        current[key]=previous.get(key)
    for key in ('exit_target','baseline'):
        if key in previous:
            current[key]=previous[key]
    if current.get('baseline'):
        current['baseline']=dict(current['baseline'])
        for key in ('start','end'):
            value=current['baseline'].get(key)
            if isinstance(value,str):current['baseline'][key]=date.fromisoformat(value[:10])
    current['exit_date']=old_date


def expand_auto_targets(objects, targets):
    by_group=defaultdict(list)
    for target in targets:
        by_group[tuple(str(target.get(k)) for k in ('profile_id','campaign_id','ad_group_id'))].append(target)
    result=[]
    names={'queryHighRelMatches':'紧密匹配','queryBroadRelMatches':'宽泛匹配',
           'asinSubstituteRelated':'替代品','asinAccessoryRelated':'关联品'}
    for obj in objects:
        key=tuple(str(obj.get(k)) for k in ('profile_id','campaign_id','ad_group_id'))
        if obj.get('object_type')!='ad_group' or not by_group.get(key):
            result.append(obj);continue
        for target in by_group[key]:
            expression=target.get('expression') or '[]'
            try:
                parts=json.loads(expression) if isinstance(expression,str) else expression
                name=' / '.join(names.get(p.get('type'),p.get('type','')) for p in parts)
            except (ValueError,TypeError,AttributeError):
                name='匹配方式待核'
            result.append(dict(obj,object_type='auto_target',object_id=target['target_id'],object_text=name,
                               current_bid=target.get('bid'),object_state_current=target.get('state'),
                               target_source_date=target.get('create_time')))
    return result


def settings_cutoff(cutoff, requested_date=None, today=None):
    """Latest runs use today's settings; dated replays keep their historical limit."""
    return cutoff if requested_date is not None else max(cutoff, today or date.today())


def read_ad_sources(cutoff, warnings, settings_date=None):
    """Dated object metadata plus fresh object-day reports; never reuse generic recommendations."""
    source=_source_connect()
    try:
        settings_date=settings_date or cutoff
        objects=read_snapshot(source,'dws_datasync.dws_sp_bid_object_snapshot_daily','snapshot_date',settings_date)
        with source.cursor() as cur:
            cur.execute("""select profile_id,campaign_id,ad_group_id,target_id,bid,state,expression,create_time
                from ods_datasync.lx_advertising_sp_targets
                where expression_type='auto' and coalesce(delete_flag,0)=0
                  and create_time<%s and coalesce(update_time,create_time)<%s""",
                        (settings_date+timedelta(days=1),settings_date+timedelta(days=1)))
            targets=cur.fetchall()
        objects=expand_auto_targets(objects,targets)
        # The object snapshot's suggested_bid, aggregates and statuses are deliberately ignored.
        with source.cursor() as cur:
            dates=[]
            report_tables=['lx_advertising_sp_keyword_reports','lx_advertising_sp_product_ad_reports','lx_advertising_sp_ad_group_reports']
            if targets:
                report_tables.append('lx_advertising_sp_query_word_reports')
            for table in report_tables:
                cur.execute(f'select max(report_date) d from ods_datasync.{table} where report_date<=%s',(cutoff,))
                raw=cur.fetchone()['d']
                dates.append(date.fromisoformat(str(raw)[:10]) if raw else None)
        common=min(dates) if all(dates) else None
        if common is None:
            warnings.append('广告完整报表日期缺失，不能评价返场后的广告效果')
            return {'objects':objects,'daily':{},'common_end':None}
        with source.cursor() as cur:
            # Natural report key may have repeated sync versions; latest id is authoritative.
            cur.execute("""select profile_id,campaign_id,ad_group_id,keyword_id object_id,
                report_date day,clicks,cost,orders_7d orders,sales_7d sales,impressions from (
                  select r.*,row_number() over(partition by profile_id,campaign_id,ad_group_id,keyword_id,report_date
                    order by id desc) rn from ods_datasync.lx_advertising_sp_keyword_reports r
                  where report_date between %s and %s
                ) t where rn=1 and coalesce(delete_flag,0)=0""",
                (common-timedelta(days=20),common-timedelta(days=7)))
            daily=defaultdict(list)
            for row in cur.fetchall():
                daily[(str(row['profile_id']),str(row['campaign_id']),str(row['ad_group_id']),str(row['object_id']))].append(row)
            if targets:
                cur.execute("""select profile_id,campaign_id,ad_group_id,target_id object_id,report_date day,
                    case when count(clicks)=count(*) then sum(clicks) end clicks,
                    case when count(cost)=count(*) then sum(cost) end cost,
                    case when count(orders_7d)=count(*) then sum(orders_7d) end orders,
                    case when count(sales_7d)=count(*) then sum(sales_7d) end sales,
                    case when count(impressions)=count(*) then sum(impressions) end impressions
                    from (select r.*,row_number() over(partition by profile_id,campaign_id,ad_group_id,target_id,report_date,`query`
                        order by id desc) rn from ods_datasync.lx_advertising_sp_query_word_reports r
                        where report_date between %s and %s) t
                    where rn=1 and coalesce(delete_flag,0)=0 and target_id is not null
                    group by profile_id,campaign_id,ad_group_id,target_id,report_date""",
                            (common-timedelta(days=20),common-timedelta(days=7)))
                for row in cur.fetchall():
                    daily[('auto',str(row['profile_id']),str(row['campaign_id']),str(row['ad_group_id']),str(row['object_id']))].append(row)
        by_product=defaultdict(list)
        for obj in objects:
            by_product[business_key(obj.get('base_store_name') or obj.get('seller_name'),obj.get('country_code'),obj.get('msku'))].append(obj)
        return {'objects':objects,'by_product':by_product,'daily':daily,'common_end':common}
    finally:
        source.close()


def country_budget_usage(prepared, budget, stock_days):
    """Historical v10/v11 audit helper only; not called by current ad decisions."""
    result=dict(scope='country_store_msku',verified=False,spend=None,budget=None,ratio=None,issues=[])
    if not prepared or any(o.get('associated_msku_count')!=1 or o.get('object_type') not in ('keyword','auto_target') or not s.get('mature') for o,s in prepared):
        result['issues']=['国家商品广告对象覆盖、单商品归属或成熟数据待核']
        return result
    windows={(s.get('mature_start'),s.get('mature_end')) for _,s in prepared}
    if len(windows)!=1 or None in next(iter(windows)):
        result['issues']=['国家商品广告花费的统一成熟周期待核']
        return result
    start,end=(date.fromisoformat(str(v)[:10]) for v in next(iter(windows)))
    days=[start+timedelta(days=n) for n in range((end-start).days+1)]
    if any(rules.dec(stock_days.get(d)) is None for d in days):
        result['issues']=['广告评价周期库存日期不完整']
        return result
    days=[d for d in days if rules.dec(stock_days.get(d))>0]
    dates={d.isoformat() for d in days}
    if not days or any(set(s.get('report_days',[]))!=dates for _,s in prepared):
        result['issues']=['国家商品广告逐日花费覆盖不完整，缺失不补0']
        return result
    currencies={currency(o.get('currency_code')) for o,_ in prepared}
    if len(currencies)!=1 or not next(iter(currencies)):
        result['issues']=['国家商品广告花费币种不一致或缺失']
        return result
    code=next(iter(currencies))
    amounts=[rules.dec(s.get('cost')) for _,s in prepared]
    if any(v is None or v<0 for v in amounts):
        result['issues']=['国家商品成熟广告花费缺失或为负']
        return result
    history=budget.get('history') or ([budget] if budget.get('biz_date') else [])
    pieces=defaultdict(int);sources=[]
    for day in days:
        eligible=[r for r in history if r.get('biz_date') and date.fromisoformat(str(r['biz_date'])[:10])<=day]
        if not eligible:
            result['issues']=[f'{day}缺少当时已有的预算记录，不借未来预算']
            return result
        stamp=max(str(r['biz_date'])[:10] for r in eligible)
        rows=[r for r in eligible if str(r['biz_date'])[:10]==stamp]
        signatures={(r.get('currency_code'),str(r.get('weekly_ad_budget_original')),str(r.get('monthly_ad_budget_original'))) for r in rows}
        if len(signatures)!=1 or currency(rows[0].get('currency_code'))!=code:
            result['issues']=[f'{day}预算记录冲突或与广告花费币种不一致']
            return result
        row=rows[0];source=date.fromisoformat(stamp);limits=[]
        week=rules.dec(row.get('weekly_ad_budget_original'));month=rules.dec(row.get('monthly_ad_budget_original'))
        if (source.isocalendar()[:2]==day.isocalendar()[:2] and week is not None and week<=0) or ((source.year,source.month)==(day.year,day.month) and month is not None and month<=0):
            result['issues']=[f'{day}同周期预算为零或负数，不能计算消耗比例']
            return result
        if source.isocalendar()[:2]==day.isocalendar()[:2] and week is not None:limits.append((week,7))
        if (source.year,source.month)==(day.year,day.month) and month is not None:limits.append((month,monthrange(day.year,day.month)[1]))
        if not limits:
            result['issues']=[f'{day}没有有效同周或同月预算']
            return result
        pieces[min(limits,key=lambda v:v[0]/v[1])]+=1;sources.append(stamp)
    total=sum((amount*count/period for (amount,period),count in pieces.items()),Decimal(0))
    spend=sum(amounts,Decimal(0))
    result.update(verified=True,spend=spend,budget=total,ratio=spend/total,currency=code,
                  start=start,end=end,days=len(days),source_dates=sorted(set(sources)),object_count=len(prepared))
    return result


def ad_for_country(event, key, ads, dos, budget, recent):
    suggestions=[]
    sales_first=rules.sales_repair_first(event)
    objects=ads.get('by_product',{}).get(key,[]) if 'by_product' in ads else [o for o in ads.get('objects',[]) if business_key(o.get('base_store_name') or o.get('seller_name'),o.get('country_code'),o.get('msku'))==key]
    if not objects:
        return [rules.start_ad_suggestion()]
    seen=set();prepared=[]
    for obj in objects:
        object_key=tuple(str(obj.get(k)) for k in ('profile_id','campaign_id','ad_group_id','object_id'))
        seen_key=(obj.get('object_type'),*object_key)
        if seen_key in seen:
            continue
        seen.add(seen_key)
        common=ads.get('common_end')
        stock_days={r['day']:r.get('stock') for r in event['timeline']}
        report_key=('auto',*object_key) if obj.get('object_type')=='auto_target' else object_key
        stats=aggregate_ad_days(ads.get('daily',{}).get(report_key,[]),event['return_date'],common,stock_days) if common else dict(days=0,mature=False)
        prepared.append((obj,stats))
    for obj,stats in prepared:
        # Existing automatic snapshots are ad-group-level. Never relabel as four auto targets.
        automatic=str(obj.get('object_type','')).lower() not in ('keyword','auto_target')
        if automatic:
            s=rules.suggestion('ad','check','自动广告需匹配到具体匹配方式；现有广告组汇总不能代替单个投放对象')
        else:
            paused=any(str(obj.get(k) or '').lower()=='paused' for k in ('campaign_state_current','ad_group_state_current','object_state_current'))
            archived=any(str(obj.get(k) or '').lower()=='archived' for k in ('campaign_state_current','ad_group_state_current','object_state_current'))
            bid_step='1' if obj.get('currency_code')=='JPY' else '.01'
            inputs=dict(stats,current_bid=obj.get('current_bid'),default_bid=obj.get('default_bid_current'),bid_step=bid_step,
                        mapping_count=obj.get('associated_msku_count'),enabled=not paused,
                        currency=obj.get('currency_code'))
            s=rules.ad_candidate(inputs,dos,sales_first=sales_first)
            if s['action']=='bid_up' and budget.get('budget_limited_verified') is True:
                # Budget and bid increases are alternatives, not a combined action.
                s=rules.budget_candidate(dict(efficient=True,limited=True,
                    month=budget.get('monthly_ad_budget_original'),week=budget.get('weekly_ad_budget_original'),
                    pool_remaining=budget.get('verified_pool_remaining'),profit_capacity=budget.get('verified_profit_capacity'),
                    sales_first=sales_first,acos=s.get('acos'),dos=dos))
            if archived:
                s=rules.suggestion('ad','check','投放对象已归档，不建议直接恢复')
            if s['action']=='restore':
                s['checks']=['暂停原因待核','断货前有效设置及投放效果待核','库存、预算和联合利润待核']
                if sales_first:s['checks'][-1]='库存及真实可用预算待核'
            else:
                s['checks']+=['近期实际广告调整及复评记录待核']
                if stats.get('orders')==0:
                    s['checks']+=['其他归因订单及保护条件待核']
                if s['action'] in ('bid_up','budget'):
                    s['checks'].append('真实可用预算及批准花费上限待核')
                if sales_first and s['action'] in ('bid_up','budget'):
                    s['profit_policy']='日销不足1件暂不设利润门槛，固定ACOS分档仍生效'
            if obj.get('object_type')=='auto_target':
                s['checks'].append('具体匹配方式的搜索词汇总，需核实是否覆盖该对象全部投放表现')
        s.update(country=key[1].upper(),currency=obj.get('currency_code'),profile_id=obj.get('profile_id'),
                 campaign_id=obj.get('campaign_id'),ad_group_id=obj.get('ad_group_id'),object_id=obj.get('object_id'),
                 campaign=obj.get('campaign_name_current'),ad_group=obj.get('ad_group_name_current'),
                 object_text=obj.get('object_text'),object_type=obj.get('object_type'),stats=stats,
                 source_date=obj.get('snapshot_date'),target_source_date=obj.get('target_source_date'),
                 current=s.get('current',obj.get('current_bid')))
        if sales_first and stats.get('orders')!=0:
            s['profit_policy']='日销不足1件，先修复销量，暂不设利润门槛；固定ACOS分档仍生效'
        if obj.get('snapshot_date')!=event['as_of']:
            s['checks'].append('广告设置快照不是当前评价日期，需核对当前设置')
        if s.get('target') is not None and obj.get('currency_code') not in {'JPY','EUR','GBP','USD','CAD','MXN','BRL','PLN','SEK','TRY','AUD','AED','SAR','INR','SGD'}:
            s.update(target=None,status='pending',reason='币种及竞价最小单位无法核实，不输出具体金额')
        if s['action'] in ('bid_up','bid_down'):
            s['checks'].append('平台允许的竞价上下限待核')
        if s['action'] in ('restore','bid_up','budget') and event['state']=='risk' and not sales_first:
            s.update(status='blocked',reason='订单毛利率低于5%，先修复利润，暂不加投')
        suggestions.append(s)
    # Concrete atoms first; diagnostics are displayed but never counted as actions.
    suggestions.sort(key=lambda s:(s['action']=='check',s['action']!='bid_down',-float(s.get('stats',{}).get('cost') or 0)))
    return rules.resolve_direction_conflicts(suggestions)


def enrich(event, key, country_rows, listings, ladders, budgets, ads, cutoff):
    event.update(seller_name_new=key[0],country_category=key[1],msku=key[2],as_of=cutoff)
    event_id=hashlib.sha1('|'.join((*key,event['stockout_date'].isoformat(),event['return_date'].isoformat())).encode()).hexdigest()
    event['event_id']=event_id
    recent=event['recent'];stock=rules.dec(event['current_stock'])
    stock_recent=rules.comparison_metrics({r['day']:r for r in event['timeline']},cutoff,7)
    daily=stock_recent.get('daily')
    dos=stock/daily if stock is not None and daily is not None and daily>0 and stock_recent['stocked'] else None
    event['dos']=dos
    event['dos_note']='FBA可售除以同店铺国家类别MSKU近7天日销；其他共享库存成员关系仍待核'
    if daily==0 and stock_recent['stocked'] and stock is not None and stock>0:
        history=event.get('comparison',{}).get('history') or {}
        historical_daily=rules.dec(history.get('daily'))
        if history.get('stocked') and historical_daily is not None and historical_daily>0:
            dos=stock/historical_daily
            event['dos']=dos
            event['dos_note']='近期零销量，使用本轮有效历史实际日销估算库存覆盖；仅作带标记参考，共享库存承接仍待核'
    countries=[];all_suggestions=[]
    by_country=defaultdict(list)
    for row in country_rows:
        if row.get('country') and rules.strategy_country(row['country']):
            by_country[row['country']].append(row)
    needs=event['exit_status']=='tracking' and event['age']>=8 and (
        event['state'] in ('sales_repair','poor','risk','no_sales','history_missing','history_zero','profit_unknown') or (event['state']=='good' and event['age']>=8 and event['current_evaluation'] and
        not rules.meets_exit_target(event['current_evaluation']['daily'],event['current_evaluation']['margin'],event['exit_target'])))
    for country,rows in sorted(by_country.items()):
        country_key=business_key(key[0],country,key[2]); by_day={r['day']:r for r in merge_days(rows)}
        cm=rules.comparison_metrics(by_day,cutoff,7)
        base=event['baseline']
        hm=rules.comparison_metrics(by_day,base['end'],base['days']) if base.get('end') else dict(qty=None,sessions=None)
        price_current=rules.comparison_metrics(by_day,cutoff,rules.comparison_days(event['age']))
        listing=dict(listings.get(country_key,{})); has_listing=bool(listing); ladderrow=ladders.get(country_key,{})
        listing['currency']=currency(listing.get('org_currency_icon'))
        ladder={f'p{x}':ladderrow.get(f'margin_price_{x}') for x in (10,15,20,25,30,35)}
        info=dict(country=country,recent=cm,historical=hm,listing=listing,ladder=ladder,
                  ladder_date=ladderrow.get('snapshot_date'),budget=budgets.get(country_key,{}),
                  price_comparison=dict(current=price_current,history=hm))
        p10=rules.dec(ladder.get('p10'));current=rules.dec(listing.get('price'))
        floor_risk=event['exit_status']=='tracking' and current is not None and p10 is not None and current<p10
        country_needs=needs or (floor_risk and event['age']>=8 and
            event['state'] not in ('stock_missing','stock_interrupted','data_missing'))
        if country_needs and not has_listing and (not cm.get('sessions') or cm['sessions']==0) and (not cm.get('qty') or cm['qty']==0):
            info['suggestions']=[rules.suggestion('general','check','该站点没有当前Listing、近期流量或销量，先核实是否实际经营')]
        elif country_needs:
            ad_suggestions=ad_for_country(event,country_key,ads,dos,info['budget'],cm)
            for s in ad_suggestions:
                if s['action'] in ('restore','bid_up','budget') and not rules.sales_repair_first(event) and (event['state']!='poor' or
                        (event.get('trend7',{}).get('current',{}).get('margin') is not None and event['trend7']['current']['margin']<rules.dec('.05'))):
                    s.update(status='blocked',reason='恢复不足及近期利润安全条件未同时确认，暂不增加投放')
            ad_pending=any(s['status'] in ('ready','pending') and s['action'] in ('check','start_ad','restore','bid_up','bid_down','budget') for s in ad_suggestions)
            price=rules.price_candidate(event,info,listing,ladder,dos,ad_pending)
            price['country']=country
            if listing.get('conflict') or ladderrow.get('conflict') or not listing['currency'] or listing['currency']!=currency(ladderrow.get('currency')):
                price.update(action='check',label='人工核查',status='pending',target=None,reason='同站点价格记录冲突、币种缺失或不一致')
            if price['action']=='price_down':
                price['checks'].append('共享库存实际成员及承接能力待核')
            info['suggestions']=rules.order_country_suggestions([price]+ad_suggestions)
        else:
            reason='本轮已退出，不再生成新动作' if event['exit_status']!='tracking' else event['state_reason']
            info['suggestions']=[dict(rules.suggestion('general','hold',reason,'hold'),country=country)]
            if floor_risk:
                info['suggestions']=[dict(rules.suggestion('price','check','发现售价低于P10，但当前观察、库存或数据条件不支持正常调价，单独核查底线风险'),country=country)]
        countries.append(info);all_suggestions.extend(info['suggestions'])
    if needs and not countries:
        all_suggestions=[rules.suggestion('general','check','缺少实际经营国家站点记录')]
    event['countries']=countries
    ready=sum(s['status']=='ready' for s in all_suggestions)
    pending=sum(s['status']=='pending' for s in all_suggestions)
    concrete=[s for s in all_suggestions if s['action'] not in ('hold','check') and s['status']!='blocked']
    summary={k:event[k] for k in ('event_id','seller_name_new','country_category','msku','return_date','stockout_date','age',
              'phase','state','state_label','state_reason','exit_target','exit_status','exit_date','exit_reasons','confirmation_days','recovery','current_stock')}
    comparison=event.get('comparison'); display=comparison['current'] if comparison else recent
    summary.update(local_sku=next((r.get('local_sku') for r in reversed(country_rows) if r.get('local_sku')),None),
                   recent_days=display['days'],
                   historical_daily=(comparison['history']['daily'] if comparison and comparison['history'] else None) if comparison else event['baseline']['daily'],recent_daily=display['daily'],margin=display['margin'],role=display['role'],
                   comparison_start=display['start'],comparison_end=display['end'],
                   recovery_issues=comparison['issues'] if comparison else [],trend7=event.get('trend7'),
                   ready_count=ready,pending_count=pending,action_types=sorted(set(s['action'] for s in all_suggestions)),
                   suggestion_summary='；'.join(dict.fromkeys(s['label'] for s in concrete)) or ('人工核查' if pending else '保持'),
                   priority=0 if event['state']=='risk' and event['exit_status']=='tracking' else (1 if concrete else (2 if pending else 3)))
    if event['exit_status']!='tracking':
        summary['priority']=4
    return summary,event


def run(cutoff=None,dry_run=False):
    service=ReturnGoodsDataService()
    with service.connect() as conn:
        with conn.cursor() as cur:
            cur.execute('select max(dt_date) d from dashboard_product_performance_daily')
            latest=cur.fetchone()['d']
        requested_date=cutoff
        cutoff=cutoff or latest
        if cutoff is None or cutoff>latest:
            raise ValueError('评价日期没有完整经营数据')
        settings_date=settings_cutoff(cutoff,requested_date)
        batch_id=None
        if not dry_run:
            with conn.cursor() as cur:
                for ddl in DDL.split(';'):
                    if ddl.strip():cur.execute(ddl)
                cur.execute("insert into dashboard_return_strategy_batch(data_date,rule_version,status) values(%s,%s,'running')",(cutoff,rules.RULE_VERSION))
                batch_id=cur.lastrowid
        warnings=[]
        try:
            frozen={}
            if batch_id:
                # Advertising/price routing does not change historical exit criteria.
                with conn.cursor() as cur:
                    cur.execute("""select i.event_id,i.detail_json from dashboard_return_strategy_item i
                        join dashboard_return_strategy_batch b on b.batch_id=i.batch_id
                        where b.status='success' and b.rule_version in (%s,%s,%s,%s,%s,%s,%s,%s,%s) and b.data_date<=%s
                          and i.exit_status<>'tracking' order by b.batch_id""",
                        (rules.RULE_VERSION,'return-v13-20261012-zero-order-clicks','return-v12-20261012-object-trial-cost','return-v11-20261012-no-action-quota','return-v10-20261012-zero-order-budget','return-v9-20261010-fixed-acos-bands','return-v8-20261009-ad-price-routing','return-v7-20261009-price-history-50','return-v6-20261008-sales-repair-first',cutoff))
                    for row in cur.fetchall():
                        frozen.setdefault(row['event_id'],json.loads(row['detail_json']))
            listings=index_snapshot(optional_read(lambda:read_snapshot(conn,'dashboard_listing_price_daily_snapshot','snapshot_date',settings_date),'当前Listing价格',warnings),settings_date)
            attach_price_changes(listings,optional_read(lambda:read_price_changes(conn,settings_date),'已完成调价记录',warnings),settings_date)
            ladders=index_snapshot(optional_read(lambda:read_snapshot(conn,'dashboard_limit_price_daily_snapshot','snapshot_date',settings_date),'价格档位',warnings),settings_date)
            def budget_history():
                with conn.cursor() as cur:
                    cur.execute('select * from dashboard_ad_budget_snapshot where biz_date between %s and %s',
                                (settings_date-timedelta(days=60),settings_date))
                    return cur.fetchall()
            budgets=index_budget_snapshot(optional_read(budget_history,'月周预算历史',warnings),settings_date)
            ads=optional_read(lambda:read_ad_sources(cutoff,warnings,settings_date),'广告对象及返场后报表',warnings) or {}
            if settings_date!=cutoff:
                warnings.append(f'经营与退出评价截至{cutoff}；当前价格、预算和广告设置读取截至{settings_date}的已同步记录，广告效果仍只用完整且成熟的报表')
            warnings.extend(['广告ACOS采用固定20%目标、50%上限分档；成熟零单20—39次点击候选降10%，40次及以上降20%；不区分日销、不依赖CPA或预算消耗；实际操作复评及联合预测利润仍需核验',
                             '预算仅展示月周配置，未来基础消耗与已承诺占用待核，不实际分配或锁定资金',
                             '自动广告须有具体匹配方式数据；广告组汇总不用于调整单个匹配方式'])
            output=[];products=0;all_events=0
            # Independent streaming connection keeps writes/metadata outside the streaming cursor.
            with service.connect() as history:
                for key,rows in iter_products(history,cutoff):
                    products+=1
                    if products%1000==0:
                        print(json.dumps({'products_scanned':products,'events_found':len(output)}),flush=True)
                    days=merge_days(rows)
                    events=rules.build_events(days)
                    if not events or events[-1]['return_date']<cutoff-timedelta(days=179):continue
                    all_events+=len(events)
                    result=rules.evaluate_event(days,events[-1],cutoff)
                    eid=hashlib.sha1('|'.join((*key,result['stockout_date'].isoformat(),result['return_date'].isoformat())).encode()).hexdigest()
                    retain_exit(result,frozen.get(eid),cutoff)
                    output.append(enrich(result,key,rows,listings,ladders,budgets,ads,cutoff))
            quality=dict(warnings=warnings,inventory_source='dashboard_inventory_daily_snapshot',products_scanned=products,latest_events=len(output),all_events=all_events,
                         exited=sum(s['exit_status']!='tracking' for s,_ in output),
                         early=sum(s['exit_status']=='early' for s,_ in output),
                         normal=sum(s['exit_status']=='normal' for s,_ in output),
                         pending=sum(s['pending_count']>0 for s,_ in output),
                         ready=sum(s['ready_count']>0 for s,_ in output),ad_common_end=ads.get('common_end'),settings_date=settings_date)
            if not dry_run:
                conn.begin()
                with conn.cursor() as cur:
                    for s,d in output:
                        cur.execute('''insert into dashboard_return_strategy_item
                            (batch_id,event_id,seller_name_new,country_category,msku,exit_status,summary_json,detail_json)
                            values(%s,%s,%s,%s,%s,%s,%s,%s)''',
                            (batch_id,s['event_id'],s['seller_name_new'],s['country_category'],s['msku'],s['exit_status'],
                             json.dumps(s,default=json_default,ensure_ascii=False),json.dumps(d,default=json_default,ensure_ascii=False)))
                    cur.execute("update dashboard_return_strategy_batch set status='success',quality_json=%s,finished_at=now() where batch_id=%s",
                                (json.dumps(quality,default=json_default,ensure_ascii=False),batch_id))
                conn.commit()
            print(json.dumps(dict(batch_id=batch_id,data_date=cutoff,quality=quality),default=json_default,ensure_ascii=True),flush=True)
            return quality
        except Exception:
            conn.rollback()
            if batch_id:
                with conn.cursor() as cur:
                    cur.execute("update dashboard_return_strategy_batch set status='failed',error_message=%s,finished_at=now() where batch_id=%s",
                                ('计算失败，上一成功快照仍保留；查看本次任务日志',batch_id))
            raise


def main():
    parser=argparse.ArgumentParser(description='Generate return strategy suggestions without execution')
    parser.add_argument('--snapshot-date')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    run(date.fromisoformat(args.snapshot_date) if args.snapshot_date else None,args.dry_run)


if __name__=='__main__':main()
