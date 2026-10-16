from __future__ import annotations
import hashlib
import math
from datetime import date, datetime
from decimal import Decimal
from .rules import STATE_LABELS, order_country_suggestions, strategy_country, start_ad_suggestion

def json_default(value):
    if isinstance(value,(date,datetime)):
        return value.isoformat()
    if isinstance(value,Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def display_window_text(row, timeline=None):
    """Correct display wording on saved batches without changing their decisions."""
    if row.get('state')=='no_sales':
        days=row.get('recent_days') or row.get('comparison',{}).get('days')
        timeline=timeline if timeline is not None else row.get('timeline',[])
        since_return=bool(timeline and len(timeline)==row.get('age') and all(day.get('qty') is not None and float(day['qty'])==0 for day in timeline))
        previous_sales=any(day.get('qty') is not None and float(day['qty'])>0 for day in timeline)
        row['no_sales_scope']='since_return' if since_return else 'window'
        row['no_sales_previous_sales']=previous_sales
        row['state_label']='返场至今未出单' if since_return else (f'近{days}天无销量' if days else STATE_LABELS['no_sales'])
        row['state_reason']=(f"返场至今{row['age']}天销量记录完整且每天为0，先检查商品及广告状态" if since_return else
            (f'当前{days}天评价窗口销量记录完整且总销量为0' if days else '当前评价窗口销量为0')+
            ('；返场后曾有销量，当前窗口没有销量' if previous_sales else '；不据此判断返场以来一直未出单'))
        for country in row.get('countries',[]):
            for suggestion in country.get('suggestions',[]):
                if suggestion.get('action')=='hold' and '尚未恢复出单' in suggestion.get('reason',''):
                    suggestion['reason']=row['state_reason']
    row['exit_reasons']=[reason.replace('评价窗口未恢复有效出单','当前评价窗口无有效销量') for reason in row.get('exit_reasons',[])]
    return row


def display_ordered_suggestions(row, countries=None):
    countries=countries if countries is not None else row.get('countries',[])
    countries=[c for c in countries if not c.get('country') or strategy_country(c['country'])]
    if 'countries' in row:row['countries']=countries
    suggestions=[]
    for country in countries:
        for s in country.get('suggestions',[]):
            if s['kind']=='ad' and s['action']=='check' and '未找到可核实的已有广告对象' in s.get('reason',''):
                s.update(start_ad_suggestion())
            stats=s.get('stats',{})
            if s['kind']=='ad' and s['action']=='check' and s.get('reason')=='核查广告状态与效果' and stats.get('mature'):
                s['reason']='已归因点击、订单或报表天数未达到竞价调整样本条件'
        suggestions.extend(order_country_suggestions(country.get('suggestions',[])))
    if countries:
        row['ad_diagnostic_reasons']=sorted({s['reason'] for s in suggestions if s['kind']=='ad' and s['action']=='check'})
        row['ad_limit_reasons']=sorted({s['reason'] for s in suggestions if s['kind']=='ad' and s['status']=='blocked'})
        concrete=[s for s in suggestions if s['action'] not in ('hold','check') and s['status'] in ('ready','pending')]
        prices=[s for s in concrete if s['kind']=='price']
        ads=[s for s in suggestions if s['kind']=='ad']
        ad_actions=[s for s in concrete if s['kind']=='ad']
        ad_unknown=any(s['action']=='check' and s['status']=='pending' for s in ads)
        row['ad_result']='adjust' if ad_actions else 'unknown' if ad_unknown else 'limited' if any(s['status']=='blocked' for s in ads) or row.get('state') in ('stock_missing','stock_interrupted') else 'hold' if ads else 'no_need' if row.get('state') in ('good','improving','observe') else 'unknown'
        row['ad_result_label']={'adjust':'已有具体广告调整建议','unknown':'广告暂无法判断','limited':'广告调整受到限制','hold':'暂不调整广告','no_need':'本轮无需广告干预'}[row['ad_result']]
        row['price_review_actions']=sorted({s['action'] for s in prices if not s.get('deferred')})
        row['price_wait_ad']=bool(prices) and all(s.get('deferred') for s in prices)
        row['price_can_review']=any(not s.get('deferred') for s in prices)
        current=[s for s in concrete if not s.get('deferred')]
        row.update(ready_count=sum(s['status']=='ready' for s in suggestions),
            pending_count=sum(s['status']=='pending' for s in suggestions),
            candidate_actions=sorted({s['action'] for s in concrete}),
            action_types=sorted({s['action'] for s in suggestions}),
            ad_check=any(s['kind']=='ad' and s['action']=='check' and s['status']=='pending' for s in suggestions),
            suggestion_summary=('；'.join(dict.fromkeys(s['label'] for s in current)) or (row['ad_result_label'] if ads else '人工核查' if any(s['status']=='pending' for s in suggestions) else '保持')))
    else:
        row.update(ad_result='no_need',ad_result_label='七国范围内没有实际经营站点，不生成广告或调价建议',
                   ad_diagnostic_reasons=[],ad_limit_reasons=[],price_review_actions=[],price_wait_ad=False,
                   price_can_review=False,ready_count=0,pending_count=0,candidate_actions=[],action_types=[],
                   ad_check=False,suggestion_summary='七国范围内无经营站点')
    return row


AGE_BANDS = [(f'd{i}',f'D{i}',i,i,'observe') for i in range(1,8)] + [
    ('d8_14','D8—D14',8,14,'intervene'),('d15_21','D15—D21',15,21,'intervene'),
    ('d22_30','D22—D30',22,30,'intervene'),('d31_60','D31—D60',31,60,'intervene'),
    ('d61_plus','D61及以上',61,None,'intervene')]


INTERVENTION_CARDS = [
    ('good','恢复较好，保持','恢复率≥80%、订单毛利率≥5%，继续跟踪退出'),
    ('improving','改善中，继续观察','每天复核，最多继续观察至D14'),
    ('poor','恢复不足，检查广告','先确认广告有没有开启、是否正常投放'),
    ('sales_repair','日销不足1件，先修复销量','先判断广告，再审核价格；暂不以利润不足拦截，库存、预算及复评限制保留'),
    ('ad_unknown','广告暂无法判断','列出具体缺失数据或投放异常，不视为广告正常'),
    ('ad_adjust','需要调整广告','已经计算出具体恢复、竞价或预算候选，详情显示对象和金额'),
    ('ad_hold','暂不调整广告','已得出暂不调整的结果，详情显示样本及依据'),
    ('ad_limited','广告调整受到限制','库存或利润等限制已经明确，暂不调整'),
    ('ad_no_need','本轮无需广告干预','本轮恢复表现无需干预；不代表逐个广告对象效率已核实'),
    ('restore','恢复已有广告','核实因断货暂停及原设置后，恢复原来有效的投放'),
    ('start_ad','建议开启广告','该经营国家未匹配到广告记录，建议开启；其他国家已有广告独立判断'),
    ('bid_up','提高竞价','ACOS≤20%候选+10%；20%—30%仅低日销候选+3%，仍受库存和预算限制'),
    ('bid_down','降低竞价','有单按ACOS分档；成熟零单20—39次点击降10%，40次及以上降20%（试算）'),
    ('budget','申请池内预算','ACOS≤20%、库存覆盖≥14天且确有预算限制，与涨竞价二选一'),
    ('price_up_review','审核价格升一档','该站点没有适用广告动作；价格已命中条件，仍需核验价格自身限制'),
    ('price_down_review','审核价格降一档','该站点没有适用广告动作；最低P10，仍需核验价格自身限制'),
    ('price_wait_ad','优先处理广告，暂缓调价','该站点有具体广告建议；建议尚未执行，不标成已调整待复评'),
    ('risk','利润风险','主窗口日销达到1件、订单毛利率低于5%，查看利润修复与止损建议'),
    ('unknown','旧快照数据不足','旧版未拆分结果，更新快照后查看具体原因'),
    ('no_sales_since_return','返场至今未出单','从本轮返场第一天至今，完整销量记录每天均为0'),
    ('no_sales_window','近期窗口无销量','当前N／21／30天窗口无销量，但不能判为返场以来一直未出单')]+[
    (key,STATE_LABELS[key],description) for key,description in [
        ('history_missing','未找到同长度有效历史窗口；仍展示当前销量和利润'),
        ('history_zero','历史日销为0，恢复率不适用'),('data_missing','具体缺失日期和字段见详情'),
        ('stock_missing','库存记录缺失，暂不拉量'),('stock_interrupted','当前评价窗口内连续至少3个自然日可售库存为0，先处理库存'),
        ('profit_unknown','销量仍可评价，利润无法确认')]]


def decision_branches(row):
    if row['exit_status']!='tracking' or row.get('age',0)<8:
        return []
    branches=[row['state']]
    ad_result=row.get('ad_result')
    if ad_result in ('adjust','unknown','hold','limited','no_need'):
        branches.append('ad_'+ad_result)
    if row['state']=='no_sales':
        branches.append('no_sales_since_return' if row.get('no_sales_scope')=='since_return' else 'no_sales_window')
    # Follow recovery triage before showing intervention branches. A saved
    # candidate alone does not move good/improving/unknown products into them.
    if row['state'] not in ('sales_repair','poor','risk','no_sales','history_missing','history_zero','profit_unknown'):
        return branches
    # Candidate branches do not assert that earlier checks or review have passed.
    # One product can have distinct actions at different sites or ad objects.
    branches.extend(row.get('candidate_actions') or [])
    branches.extend(a+'_review' for a in row.get('price_review_actions',[]) if a in ('price_up','price_down'))
    if row.get('price_wait_ad'):branches.append('price_wait_ad')
    if ad_result is None:
        branches.extend(a+'_review' for a in (row.get('candidate_actions') or []) if a in ('price_up','price_down') and not row.get('price_wait_ad'))
        if row.get('ad_check') or row['state'] in ('poor','no_sales'):branches.append('ad_unknown')
    return list(dict.fromkeys(branches))


def intervention_focus(row):
    if row['exit_status']!='tracking' or row.get('age',0)<8:
        return None
    return row['state']


def stage_of(row):
    if row['exit_status']!='tracking':
        return row['exit_status']
    return 'observe' if 1<=row.get('age',0)<=7 else 'intervene'


def in_age_band(row, band):
    if band=='all':
        return True
    return row['exit_status']=='tracking' and any(
        key==band and low<=row.get('age',0) and (high is None or row['age']<=high)
        for key,_,low,high,_ in AGE_BANDS)


def stage_distribution(rows):
    stages={key:[r for r in rows if stage_of(r)==key] for key in ('observe','intervene','early','normal')}
    return dict(total=len(rows),counts={key:len(value) for key,value in stages.items()},
                days=[dict(key=key,label=label,stage=stage,count=sum(in_age_band(r,key) for r in rows))
                      for key,label,_,_,stage in AGE_BANDS],
                states={key:{state:sum(r['state']==state for r in value)
                             for state in STATE_LABELS}
                        for key,value in stages.items() if key in ('observe','intervene')})


def ad_reason_details(row):
    """Reasons explain the existing decision; they do not change its outcome."""
    category=row.get('ad_result')
    if category=='limited':
        if row['state']=='stock_missing':reasons=['库存快照缺少商品记录']
        elif row['state']=='stock_interrupted':
            stock=row.get('current_stock')
            reasons=[('当前仍断货：连续至少3天零库存' if stock is not None and float(stock)==0 else
                      f'曾连续断货：当前仅恢复{float(stock):g}件库存' if stock is not None else
                      '曾连续断货，当前库存无法确认')]
        else:reasons=row.get('ad_limit_reasons') or ['广告调整限制原因尚未记录，需查看商品详情']
    elif category=='unknown':
        reasons=row.get('ad_diagnostic_reasons') or [row.get('state_reason') or '缺少广告判断所需数据，需查看商品详情']
    else:return []
    return [dict(key='ad_reason_'+hashlib.sha1((category+'|'+reason).encode()).hexdigest()[:16],
                 category=category,reason=reason) for reason in sorted(set(reasons))]


def filter_payload(rows, meta, *, country_category='all', seller_name_new='all', keyword='',
                   exit_status='tracking', state='all', action='all', recommendation='all',
                   stage='all', age_band='all', focus='all', all_rows=False, page=1, page_size=50):
    labels={key:label for key,label,_ in INTERVENTION_CARDS}
    rows=[dict(row,decision_branches=decision_branches(row),intervention_focus=intervention_focus(row),
               intervention_label=labels.get(intervention_focus(row),'—')) for row in rows]
    for row in rows:
        row['ad_reason_details']=ad_reason_details(row) if stage_of(row)=='intervene' else []
        row['decision_branches'].extend(r['key'] for r in row['ad_reason_details'])
    options={'countries':sorted({r['country_category'] for r in rows}),
             'stores':sorted({r['seller_name_new'] for r in rows})}
    key=keyword.strip().casefold()
    base=[r for r in rows if (country_category=='all' or r['country_category']==country_category)
          and (seller_name_new=='all' or r['seller_name_new']==seller_name_new)
          and (not key or key in (r['msku']+' '+str(r.get('local_sku') or '')).casefold())
          and (state=='all' or r['state']==state)
          and (action=='all' or action in r['action_types'])]
    summary={'tracking':sum(r['exit_status']=='tracking' for r in base),
             'ready':sum(r['ready_count']>0 for r in base),
             'pending':sum(r['pending_count']>0 for r in base),
             'exited':sum(r['exit_status']!='tracking' for r in base)}
    distribution=stage_distribution(base)
    intervention=[dict(key=key,label=label,description=description,
                       count=sum(key in r['decision_branches'] for r in base))
                  for key,label,description in INTERVENTION_CARDS]
    rows=[r for r in base if (exit_status=='all' or (exit_status=='exited' and r['exit_status']!='tracking') or r['exit_status']==exit_status)
          and (stage=='all' or stage_of(r)==stage) and in_age_band(r,age_band)
          and (focus=='all' or focus in r['decision_branches'])
          and (recommendation=='all' or (recommendation=='ready' and r['ready_count']>0)
               or (recommendation=='pending' and r['pending_count']>0))]
    rows.sort(key=lambda r:(r['priority'],r['seller_name_new'],r['msku'],r['event_id']))
    total=len(rows); page_size=max(10,min(200,int(page_size))); pages=max(1,math.ceil(total/page_size));page=max(1,min(int(page),pages))
    ad_diagnostics=[dict(reason=reason,count=sum(reason in r.get('ad_diagnostic_reasons',[]) for r in base if stage_of(r)=='intervene'))
                    for reason in sorted({reason for r in base if stage_of(r)=='intervene' for reason in r.get('ad_diagnostic_reasons',[])})]
    reason_groups={}
    for row in base:
        for reason in row['ad_reason_details']:
            group=reason_groups.setdefault(reason['key'],dict(reason,count=0,products=[]))
            group['count']+=1
            group['products'].append({k:row.get(k) for k in ('event_id','msku','seller_name_new','country_category','current_stock')})
    return dict(meta=meta,options=options,summary=summary,distribution=distribution,intervention=intervention,ad_diagnostics=ad_diagnostics,
                ad_reason_groups=sorted(reason_groups.values(),key=lambda g:(g['category'],-g['count'],g['reason'])),
                items=rows if all_rows else rows[(page-1)*page_size:page*page_size],
                total=total,page=page,page_size=page_size,pages=pages)


def prepare_page_data(products, meta=None, **filters):
    """Derive the same list, stage and card statistics from completed decisions."""
    rows = []
    for product in products:
        detail = product['detail']
        display_window_text(detail)
        display_ordered_suggestions(detail)
        row = dict(product['summary'])
        display_window_text(row, detail.get('timeline', []))
        display_ordered_suggestions(row, detail.get('countries', []))
        rows.append(row)
    return filter_payload(rows, meta or {}, **filters)
