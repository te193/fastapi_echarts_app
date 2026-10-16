"""Pure cohort/metric engine. No database writes or implicit zero filling."""
from collections import defaultdict
from datetime import date, timedelta
from math import isfinite
from statistics import median

from .label_analysis_metrics import DAILY_FIELDS, INVENTORY_FIELDS, METRICS, REPL_FIELDS,TRAFFIC_DAILY_FIELDS


ZERO_BUSINESS_RECORD={key:0 for key in DAILY_FIELDS}


def business_record(daily,day,unavailable_fields=()):
    """Absent business rows are zero; present null fields and stock stay unknown."""
    if day in daily:return daily[day]
    return {**ZERO_BUSINESS_RECORD,**dict.fromkeys(unavailable_fields)} if unavailable_fields else ZERO_BUSINESS_RECORD


def row_business_record(row,day):
    record=business_record(row.get('daily',{}),day)
    if 'traffic_daily' in row:
        record={**record,**row['traffic_daily'].get(day,dict.fromkeys(TRAFFIC_DAILY_FIELDS,0))}
    if row.get('traffic_coverage_start') and day<row['traffic_coverage_start']:
        record={**record,**dict.fromkeys(TRAFFIC_DAILY_FIELDS)}
    if row.get('unavailable_daily_fields'):
        record={**record,**dict.fromkeys(row['unavailable_daily_fields'])}
    return record


def metric_calendar(row,field):
    return row['traffic_daily'] if field in TRAFFIC_DAILY_FIELDS and 'traffic_daily' in row else row.get('daily',{})


def number(value):
    if value is None or value == '':
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


def safe_ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def days_between(start, end):
    return [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]


def inventory_calendar(values, start, end):
    days = days_between(start,end)
    observed = instock = stockout = longest = streak = events = 0
    previous = None
    streak_bounded = False
    longest_lower_bound = False
    for day in days:
        value=number(values.get(day))
        if value is None or value < 0:
            previous=None; streak=0; streak_bounded=False
            continue
        observed+=1
        if value > 0:
            instock+=1; streak=0; streak_bounded=True
        else:
            stockout+=1
            if previous is not None and previous>0:
                events+=1; streak_bounded=True
            elif streak==0:
                streak_bounded=False
            streak+=1
            if streak>longest:
                longest=streak; longest_lower_bound=not streak_bounded
            elif streak==longest and not streak_bounded:
                longest_lower_bound=True
        previous=value
    current = None if previous is None else streak
    return dict(stockout_days=stockout if observed else None,instock_days=instock if observed else None,unknown_inventory_days=len(days)-observed,
                inventory_observed_days=observed,expected_inventory_days=len(days),stockout_events=events if observed else None,
                current_stockout_days=current,max_stockout_days=longest if observed else None,
                current_stockout_lower_bound=bool(current and not streak_bounded),
                max_stockout_lower_bound=bool(longest and longest_lower_bound),
                stockout_day_rate=safe_ratio(stockout,observed),inventory_observation_rate=safe_ratio(observed,len(days)))


def prepare_rows(raw_rows, start, end):
    dates=days_between(start,end); result=[]
    for raw in raw_rows:
        row=dict(raw); values={}; daily=raw.get('daily',{})
        observed_records=[row_business_record(raw,day) for day in dates]
        zero_filled_days=sum(day not in daily for day in dates)
        counts={};effective_counts={};filled_counts={}
        for key in DAILY_FIELDS:
            present=[number(record.get(key)) for record in observed_records]
            actual=[v for v in present if v is not None]
            values[key]=sum(actual) if actual else None
            calendar=metric_calendar(raw,key)
            filled_counts[key]=sum(day not in calendar and v is not None for day,v in zip(dates,present))
            counts[key]=len(actual)-filled_counts[key]
            effective_counts[key]=len(actual)
        values['period_daily_sales']=safe_ratio(values['sales_qty'],len(dates))
        rank=number(daily.get(end.isoformat(),{}).get('small_category_rank'))
        values['small_category_rank']=rank if rank is not None and rank>0 else None
        values['sales_days']=sum(number(record.get('sales_qty')) is not None and number(record.get('sales_qty'))>0 for record in observed_records) if effective_counts['sales_qty'] else None
        values['traffic_days']=sum(number(record.get('sessions_total')) is not None and number(record.get('sessions_total'))>0 for record in observed_records) if effective_counts['sessions_total'] else None
        profit=values['order_gross_profit']
        values['positive_profit']=max(profit,0) if profit is not None else None
        values['loss_amount']=max(-profit,0) if profit is not None else None
        ad_values=[values[k] for k in ('ad_clicks','ad_orders','ad_spend')]
        values['zero_order_spend']=(values['ad_spend'] if values['ad_clicks']>0 and values['ad_orders']==0 else 0) if all(v is not None for v in ad_values) else None
        inv=raw.get('inventory',{})
        inventory_end=number(inv.get(end.isoformat()))
        if inventory_end is not None and inventory_end<0:
            inventory_end=None
        inv_fields=raw.get('inventory_values',{})
        for key in INVENTORY_FIELDS:
            values[key]=number(inv_fields.get(key)) if inv_fields.get('date')==end.isoformat() else None
        values['sellable_inventory_cost']=number(raw.get('sellable_cost_history',{}).get(end.isoformat()))
        values['ending_inventory_qty']=inventory_end
        cal_start=max(start,date.fromisoformat(raw['inception_date'])) if raw.get('inception_date') else start
        calendar=inventory_calendar(inv,cal_start,end) if cal_start<=end else inventory_calendar({},end,end)
        values.update(calendar)
        for key in ('stockout_days','instock_days','inventory_observed_days','expected_inventory_days'):
            values['pool_'+key]=values[key]
        obs=[number(inv.get(d)) for d in dates]
        values['avg_inventory_qty']=sum(obs)/len(obs) if obs and all(v is not None and v>=0 for v in obs) else None
        costs=[number(raw.get('inventory_cost_daily',{}).get(d)) for d in dates]
        values['avg_inventory_cost']=sum(costs)/len(costs) if costs and all(v is not None and v>=0 for v in costs) else None
        values['zero_sales_inventory_cost']=values['inventory_cost'] if effective_counts['sales_qty']==len(dates) and values['sales_qty']==0 else None
        repl=raw.get('replenishment_history',{}).get(end.isoformat(),raw.get('replenishment',{}))
        aligned=repl.get('date')==end.isoformat()
        for key,(_,field,_,_) in REPL_FIELDS.items():
            values[key]=number(repl.get(field)) if aligned else None
        demand=number(repl.get('coverage_daily_sales',values['replenishment_daily_sales']))
        values['coverage_demand_daily_sales']=demand if aligned and demand is not None and demand>=0 else None
        coverage_inventory=number(repl.get('coverage_inventory_qty',inventory_end))
        values['fba_coverage_days']=safe_ratio(coverage_inventory,demand) if aligned and inventory_end is not None else None
        paired={};paired_filled={}
        for key,m in METRICS.items():
            if m.aggregation=='ratio':
                if m.numerator in DAILY_FIELDS and m.denominator in DAILY_FIELDS:
                    num_calendar=metric_calendar(raw,m.numerator);den_calendar=metric_calendar(raw,m.denominator)
                    pairs=[(number(record.get(m.numerator)),number(record.get(m.denominator)),day not in num_calendar or day not in den_calendar) for day,record in zip(dates,observed_records)]
                    pairs=[(a,b,filled) for a,b,filled in pairs if a is not None and b is not None]
                    a=sum(p[0] for p in pairs) if pairs else None; b=sum(p[1] for p in pairs) if pairs else None
                    paired[key]=(a,b,len(pairs))
                    paired_filled[key]=sum(p[2] for p in pairs)
                    ratio=safe_ratio(a,b)
                    values[key]=ratio*m.multiplier if ratio is not None else None
                else:values[key]=safe_ratio(values.get(m.numerator),values.get(m.denominator))
        row.update(values=values,observed_days=counts,effective_days=effective_counts,zero_filled_days=zero_filled_days,zero_filled_by_metric=filled_counts,ratio_zero_filled_days=paired_filled,period_days=len(dates),
                   coverage_daily_sales=demand,coverage_inventory_qty=coverage_inventory,
                   ratio_pairs=paired,aggregate_values=repl.get('aggregate_values',{}) if aligned else {},
                   pool_id=repl.get('pool_id',raw.get('pool_id')) if aligned else raw.get('pool_id'),
                   demand_id=repl.get('demand_id',raw.get('demand_id')) if aligned else raw.get('demand_id'),
                   inventory_boundary_lower_bound=calendar['current_stockout_lower_bound'],
                   inventory_max_boundary_lower_bound=calendar['max_stockout_lower_bound'],
                   replenishment_source_date=repl.get('date'),
                   coverage_reason=('补货日销未覆盖或日期不一致' if not aligned else '补货需求缺失或组映射未确认' if demand is None else '补货日销为零或异常' if demand<=0 else '库存缺失或映射冲突' if inventory_end is None or coverage_inventory is None else '可计算'))
        result.append(row)
    return result


def coverage_gap(row):
    """Explain a missing coverage result using the published period context."""
    if number(row['values'].get('fba_coverage_days')) is not None:return ''
    reason=row.get('coverage_reason','')
    if reason=='补货日销未覆盖或日期不一致':
        fields=('sales_qty','sales_amount','order_gross_profit','sessions_total','page_views','order_count','traffic_sales_qty')
        observed=row.get('observed_days',{})
        return 'missing_daily_sales' if any((number(observed.get(key)) or 0)>0 for key in fields) else 'no_performance'
    if reason=='补货日销为零或异常' and number(row.get('coverage_daily_sales'))==0:return 'zero_daily_sales'
    return 'data_pending'


def matches(row, condition):
    if condition.get('kind')=='coverage':return coverage_gap(row)==condition.get('reason')
    if condition.get('kind')=='label':
        return any(t['parent_id']==condition['parent_id'] and t['id'] in condition['ids'] for t in row.get('labels',[]))
    value=number(row['values'].get(condition.get('metric')))
    op=condition.get('op')
    if op=='missing': return value is None
    if op=='present': return value is not None
    if value is None: return False
    threshold=condition.get('value')
    if op=='eq': return value==threshold
    if op=='gt': return value>threshold
    if op=='gte': return value>=threshold
    if op=='lt': return value<threshold
    if op=='lte': return value<=threshold
    if op=='between': return threshold<=value<=condition['upper']
    if op=='range': return threshold<value<=condition['upper']
    return False


def select_cohorts(rows, conditions):
    parent=rows; current=rows
    for condition in conditions:
        parent=current
        current=[r for r in current if matches(r,condition)]
    return rows,parent,current


def percentile(values, q):
    ordered=sorted(values); index=(len(ordered)-1)*q
    lower=int(index); upper=min(lower+1,len(ordered)-1)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(index-lower)


def metric_samples(rows, metric, grouped=None):
    field=metric.id
    if metric.grain=='object':
        return [r['values'].get(field) for r in rows]
    key='pool_id' if metric.grain=='pool' else 'demand_id'
    groups=grouped
    if groups is None:
        groups=defaultdict(list)
        for row in rows:
            groups[row.get(key) or ('unknown:'+row['key'])].append(row)
    result=[]
    for identity,members in groups.items():
        vals=[r.get('aggregate_values',{}).get(field,r['values'].get(field)) for r in members]
        present=[v for v in vals if v is not None]
        result.append(present[0] if not identity.startswith('unknown:') and present and len(present)==len(vals) and max(present)-min(present)<1e-8 else None)
    return result


def aggregate(rows, fields=None):
    out={}
    requested=set(fields) if fields is not None else set(METRICS)
    active=set(requested)
    for k in requested:
        m=METRICS[k]
        if m.aggregation=='ratio':active.update(x for x in (m.numerator,m.denominator) if x in METRICS)
    registry={k:m for k,m in METRICS.items() if k in active}
    grouped={}
    for grain,key in [('pool','pool_id'),('demand','demand_id')]:
        groups=defaultdict(list)
        for row in rows:groups[row.get(key) or ('unknown:'+row['key'])].append(row)
        grouped[grain]=groups
    def cell(key,value,valid,total,**extra):
        m=METRICS[key]
        if value is None and 'reason' not in extra:
            extra['reason']='当前范围没有商品' if total==0 else '缺少共同有效样本或分母非正' if m.aggregation=='ratio' else '没有满足来源、日期及映射要求的有效值'
        out[key]=dict(value=value,unit=m.unit,valid_count=valid,total_count=total,
                      status='unavailable' if value is None else 'partial' if valid<total else 'available',**extra)
    count=len(rows)
    n=lambda test:sum(bool(test(r)) for r in rows)
    valid=lambda key:n(lambda r:r['values'].get(key) is not None)
    positive=lambda key:n(lambda r:(r['values'].get(key) or 0)>0)
    counters=dict(object_count=count,unique_msku_count=len({r['msku'].casefold() for r in rows}),
                  store_count=len({r['store'] for r in rows}),country_count=len({c for r in rows for c in r.get('countries',[r.get('country')]) if c}),
                  pool_count=len({r['pool_id'] for r in rows if r.get('pool_id')}),
                  labeled_count=n(lambda r:any(t['parent_id']!=9001 for t in r.get('labels',[]))),sales_valid_count=valid('sales_qty'),
                  inventory_valid_count=valid('ending_inventory_qty'),selling_count=positive('sales_qty'),
                  zero_sales_count=n(lambda r:r['values'].get('sales_qty')==0),
                  profitable_count=positive('order_gross_profit'),loss_count=n(lambda r:(r['values'].get('order_gross_profit') or 0)<0),
                  traffic_count=positive('sessions_total'),ad_product_count=n(lambda r:any((r['values'].get(k) or 0)>0 for k in ('ad_spend','ad_clicks','ad_impressions'))),
                  return_product_count=positive('return_count'),zero_inventory_count=n(lambda r:r['values'].get('ending_inventory_qty')==0),
                  stockout_product_count=positive('stockout_days'),inventory_observed_count=positive('inventory_observed_days'),
                  long_stockout_count=n(lambda r:(r['values'].get('current_stockout_days') or 0)>=7),
                  recovered_stockout_count=n(lambda r:(r['values'].get('stockout_days') or 0)>0 and (r['values'].get('ending_inventory_qty') or 0)>0),
                  current_inventory_unknown_count=n(lambda r:r['values'].get('ending_inventory_qty') is None),
                  unlabeled_count=n(lambda r:not any(t['parent_id']!=9001 for t in r.get('labels',[]))),missing_sales_count=n(lambda r:r['values'].get('sales_qty') is None),
                  multiple_label_count=n(lambda r:sum(t['parent_id']!=9001 for t in r.get('labels',[]))>1),profit_valid_count=valid('order_gross_profit'),
                  traffic_valid_count=valid('sessions_total'),ads_valid_count=valid('ad_spend'),return_valid_count=valid('return_count'))
    for key,m in registry.items():
        if m.aggregation=='count':
            cell(key,counters[key],count,count)
            if key in ('zero_inventory_count','long_stockout_count'):
                out[key]['valid_count']=counters['inventory_valid_count']
                if out[key]['valid_count']<count:out[key].update(status='partial',reason='部分商品截止日库存不明，未计作断货')
            if key in ('stockout_product_count','recovered_stockout_count','long_stockout_count') and any(r['values']['inventory_observed_days']<r['values']['expected_inventory_days'] for r in rows):
                out[key].update(status='partial',reason='仅统计已确认的断货；部分库存日期缺失')
        elif not m.available: cell(key,None,0,count,reason='来源尚未接入或未核验')
        elif m.aggregation in ('sum','median','max'):
            samples=metric_samples(rows,m,grouped.get(m.grain)); present=[v for v in samples if v is not None]
            value=(sum(present) if m.aggregation=='sum' else max(present) if m.aggregation=='max' else median(present)) if present else None
            extra={}
            if present and m.aggregation=='median':
                extra=dict(p25=percentile(present,.25),p75=percentile(present,.75))
            cell(key,value,len(present),len(samples),**extra)
            if key in DAILY_FIELDS:
                if value is not None and any(r['effective_days'][key]<r['period_days'] for r in rows):out[key]['status']='partial'
                out[key]['observed_object_days']=sum(r['observed_days'][key] for r in rows)
                out[key]['expected_object_days']=sum(r['period_days'] for r in rows)
                out[key]['zero_filled_object_days']=sum(r['zero_filled_by_metric'][key] for r in rows)
            if key in ('stockout_days','instock_days','pool_stockout_days','pool_instock_days','stockout_events','current_stockout_days','max_stockout_days') and value is not None:
                if any(r['values']['inventory_observed_days']<r['values']['expected_inventory_days'] or (key in ('current_stockout_days','stockout_events') and r['inventory_boundary_lower_bound']) or (key=='max_stockout_days' and r['inventory_max_boundary_lower_bound']) for r in rows):
                    out[key]['status']='partial'
                    out[key]['reason']='仅已确认观察；连续天数或次数可能为下限'
    for key,m in registry.items():
        if m.aggregation!='ratio': continue
        pair_days=None
        if m.numerator in DAILY_FIELDS and m.denominator in DAILY_FIELDS:
            pairs=[r['ratio_pairs'][key] for r in rows if r['ratio_pairs'][key][2]>0]
            a=sum(p[0] for p in pairs) if pairs else None; b=sum(p[1] for p in pairs) if pairs else None
            valid_count=len(pairs); pair_days=sum(p[2] for p in pairs)
        elif m.numerator in counters or m.denominator in counters:
            a=counters.get(m.numerator,out.get(m.numerator,{}).get('value'))
            b=counters.get(m.denominator,out.get(m.denominator,{}).get('value'))
            valid_count=min(b or 0,count)
        elif METRICS.get(m.numerator) and METRICS.get(m.denominator):
            pair=[r for r in rows if r['values'].get(m.numerator) is not None and r['values'].get(m.denominator) is not None]
            aa=metric_samples(pair,METRICS[m.numerator]); bb=metric_samples(pair,METRICS[m.denominator])
            pairs=[(a,b) for a,b in zip(aa,bb) if a is not None and b is not None]
            a=sum(x[0] for x in pairs) if pairs else None; b=sum(x[1] for x in pairs) if pairs else None
            valid_count=len(pair)
        else: a=b=None; valid_count=0
        ratio=safe_ratio(a,b)
        cell(key,ratio*m.multiplier if ratio is not None else None,valid_count,count,numerator=a,denominator=b)
        if pair_days is not None:
            filled=sum(r['ratio_zero_filled_days'].get(key,0) for r in rows)
            out[key].update(observed_object_days=pair_days-filled,zero_filled_object_days=filled,expected_object_days=sum(r['period_days'] for r in rows))
            if pair_days<out[key]['expected_object_days'] and out[key]['value'] is not None:out[key]['status']='partial'
        if key in ('stockout_day_rate','stockout_occurrence_rate','average_stockout_days') and out[key]['value'] is not None and any(r['values']['inventory_observed_days']<r['values']['expected_inventory_days'] for r in rows):out[key]['status']='partial'
    positive_sales=sorted([r['values']['sales_amount'] for r in rows if (r['values'].get('sales_amount') or 0)>0],reverse=True)
    if 'top10_sales_share' in requested:cell('top10_sales_share',safe_ratio(sum(positive_sales[:10]),sum(positive_sales)),len(positive_sales),count)
    return {k:v for k,v in out.items() if k in requested}


def compare_metrics(current, baseline):
    result={}
    for key,c in current.items():
        a=c.get('value'); b=baseline.get(key,{}).get('value')
        delta=a-b if a is not None and b is not None else None
        result[key]=dict(delta=delta,relative_change=delta/b if delta is not None and b>0 else None,
                         percentage_points=delta*100 if delta is not None and c.get('unit')=='percent' else None)
    return result


def coverage_distribution(rows):
    edges=[(0,0,'0天'),(0,7,'0—7天'),(7,14,'7—14天'),(14,30,'14—30天'),(30,60,'30—60天'),(60,90,'60—90天'),(90,None,'90天以上'),(None,None,'无法计算')]
    result=[]
    for low,high,label in edges:
        condition=dict(kind='metric',metric='fba_coverage_days',op='missing' if low is None else 'eq' if high==0 else 'gt' if high is None else 'range',value=low,upper=high)
        selected=[r for r in rows if matches(r,condition)]
        result.append(dict(label=label,count=len(selected),share=safe_ratio(len(selected),len(rows)),condition=condition))
    return result
