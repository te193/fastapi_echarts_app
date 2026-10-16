"""问题产品首轮动作预览。纯本地计算，不写数据库或广告平台。"""
from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path

from extract_inputs import write_json

ROOT = Path(__file__).parent / 'outputs/20260921-162402'
OUT = ROOT / 'problem_actions'
CODES = {'德国':'DE','法国':'FR','意大利':'IT','西班牙':'ES','荷兰':'NL','英国':'UK','美国':'US'}
CURRENCY = {country: ('GBP' if country=='英国' else 'USD' if country=='美国' else 'EUR') for country in CODES}
LABELS = {'price_decrease':'降价','bid_decrease':'降低竞价','bid_increase':'提高竞价',
          'keyword_negative_exact':'否定关键词','ad_enable':'开启广告','keyword_add_exact':'新增精准词'}
D = Decimal
CENT = D('.01')


def number(value):
    try:
        result = D(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def pid(row):
    return row['country'], row['store'], row['msku']


def read(name):
    return json.loads((ROOT/f'{name}.json').read_text(encoding='utf-8'))


def unique_index(rows, key):
    index=defaultdict(list)
    for row in rows: index[key(row)].append(row)
    return {key: values[0] for key, values in index.items() if len(values)==1}


def latest(rows, fields):
    result={}
    for row in rows:
        key=tuple(str(row[f]) for f in fields)
        rank=(str(row.get('update_time') or row.get('create_time') or ''), int(row['id']))
        if key not in result or rank>result[key][0]: result[key]=(rank,row)
    return {key:value[1] for key,value in result.items()}


def not_deleted(row):
    # 源BIT字段经JSON的default=str序列化为bytes字面量；未知值不得视作未删除。
    return row.get('delete_flag') in (0, False, "b'\\x00'")


def enabled(row):
    return row is not None and not_deleted(row) and str(row.get('state','')).lower()=='enabled'


def price_action(current, p10, p25):
    if any(v is None or v<=0 for v in (current,p10,p25)) or p25<p10:
        return None,'价格线缺失或反向'
    if current<=p10: return None,'已到P10，无自动降价空间'
    rule='100101' if current>p25 else '100102'
    suggested=(p25 if rule=='100101' else max(current*D('.95'),p10)).quantize(CENT,rounding=ROUND_CEILING)
    if suggested>=current: return None,'取整后无有效降价空间'
    return (rule,suggested),None


def bid_rule(auto, clicks, orders, cost, sales):
    """仅返回已明确分支；I01、I02不自动采用建议解释。"""
    if any(x is None or x<0 for x in (clicks,orders,cost,sales)): return None,'成熟指标缺失或负数'
    acos=cost/sales if sales>0 else None
    cvr=orders/clicks if clicks>0 else None
    if auto:
        if orders==0 and clicks>=63: return ('100202',D('-.20')),None
        if orders==0 and clicks>=34: return ('100201',D('-.10')),None
        if orders==1 and clicks>=63: return ('100204',D('-.10')),None
        if orders==1 and 34<=clicks<=62 and ((acos is not None and acos>D('.5')) or (cvr is not None and cvr<D('.03'))):
            return None,'100203条件括号待确认'
        if orders>=2 and acos is not None:
            if acos>D('.65'): return ('100206',D('-.20')),None
            if acos>=D('.5'): return ('100205',D('-.10')),None
            if acos>=D('.4') and cvr is not None and cvr<D('.03'): return ('100207',D('-.05')),None
            if clicks>=80 and orders>=5 and acos<=D('.2') and cvr>=D('.07'): return ('100210',D('.15')),None
            if clicks>=40 and orders>=3 and acos<=D('.3') and cvr>=D('.07'): return ('100209',D('.10')),None
            if clicks>=15 and acos<=D('.4') and cvr>=D('.05'): return ('100208',D('.05')),None
    else:
        if orders>=2 and acos is not None:
            if acos>=D('.5'): return ('100302',D('-.20')),None
            if acos>D('.3'): return ('100301',D('-.10')),None
            if clicks>=10 and acos<=D('.2'): return ('100306',D('.10')),None
        if orders==0 and clicks>=12: return None,'100303至100305：60天客单价缺失，且问题产品花费分档口径尚待确认'
    return None,None


def rounded_bid(current, rate, auto, lower, upper):
    if current is None or current<=0: return None,'当前bid缺失或非正'
    if lower is None or upper is None or lower<=0 or upper<lower:
        return None,'平台bid上下限未核实'
    value=(current*(1+rate)).quantize(CENT,rounding=ROUND_HALF_UP)
    if auto and value==current: value=current+(CENT if rate>0 else -CENT)
    value=max(lower,min(upper,value))
    if value<=0 or (rate<0 and value>=current) or (rate>0 and value<=current):
        return None,'舍入或限幅后无有效变化'
    return value,None


def select_ads(rows):
    # 同一实际执行对象只留一条；风险收缩优先，同级按成熟花费降序，再用稳定ID破同分。
    ordered=sorted(rows,key=lambda r:(0 if r['action_type'] in ('keyword_negative_exact','bid_decrease') else 1,
                                    -(number(r.get('cost')) or D(0)),r['action_id']))
    selected=[]; rejected=[]; counts=Counter(); seen=set()
    for row in ordered:
        key=pid(row)
        if row['execution_key'] in seen:
            rejected.append((row,'同一执行对象去重'))
        elif counts[key]>=2:
            rejected.append((row,'同产品最多2个广告动作'))
        else:
            selected.append(row); seen.add(row['execution_key']); counts[key]+=1
    return selected,rejected


def write_csv(path, rows, fields):
    with path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            cells={key:row.get(key) for key in fields}
            for key,value in cells.items():
                if isinstance(value,(dict,list)): cells[key]=json.dumps(value,ensure_ascii=False,default=str)
                if isinstance(cells[key],str) and cells[key].startswith(('=','+','-','@')): cells[key]="'"+cells[key]
            writer.writerow(cells)


def main():
    OUT.mkdir(exist_ok=True)
    products=[p for p in read('product_base') if p['source_roles']==['problem']]
    product_index={pid(p):p for p in products}
    canonical_keys=defaultdict(set)
    for key in product_index: canonical_keys[(key[0],key[1].casefold(),key[2])].add(key)
    metrics=unique_index(read('support_metrics'),pid)
    price_rows=read('pricing')
    aliases=defaultdict(set)
    for p in price_rows:
        if p['国家'] in CODES and p['新店铺']:
            aliases[(CODES[p['国家']],p['店铺名'].casefold())].add(p['新店铺'])
    def resolve(code,store,sku,base_store=None):
        code=str(code).upper()
        code='UK' if code=='GB' else code
        country=next((k for k,v in CODES.items() if v==code),None)
        stores=aliases.get((code,str(store).casefold()),set())
        if base_store:
            if stores and {s.casefold() for s in stores}!={base_store.casefold()}: return None
            stores={base_store}
        if len(stores)!=1: return None
        keys=canonical_keys.get((country,next(iter(stores)).casefold(),sku),set())
        return next(iter(keys)) if len(keys)==1 else None
    accounts=latest(read('support_accounts'),['profile_id'])
    campaigns=latest(read('support_campaigns'),['profile_id','entity_id'])
    groups=latest(read('support_ad_groups'),['profile_id','entity_id'])
    ads=latest(read('support_product_ads'),['profile_id','ad_id'])
    ad_by_product=defaultdict(list)
    profile_map=defaultdict(set)
    for (profile,),account in accounts.items():
        if not not_deleted(account): continue
        code=str(account['country_code']).upper(); code='UK' if code=='GB' else code
        for store in aliases.get((code,str(account['name']).casefold()),set()): profile_map[(code,store.casefold())].add(profile)
    for row in ads.values():
        account=accounts.get((str(row['profile_id']),))
        if not account or not not_deleted(account): continue
        key=resolve(account['country_code'],row['seller_name'],row['sku'])
        if key: ad_by_product[key].append(row)
    bids=read('bid_objects'); terms=read('search_terms')
    bid_attrs=unique_index(read('support_bid_attribution'),lambda r:r['row_key'])
    term_attrs=unique_index(read('support_term_attribution'),lambda r:r['row_key'])
    actions=[]; proposals=[]; diagnostics=[]; product_summary=[]
    def diagnostic(key,scope,reason,entity=''):
        diagnostics.append(dict(country=key[0],store=key[1],msku=key[2],scope=scope,reason=reason,entity=str(entity)))
    def action(key,kind,rule,execution_key,reason,**extra):
        seed='|'.join(map(str,(*key,kind,execution_key)))
        row=dict(action_id=hashlib.sha256(seed.encode()).hexdigest()[:20],country=key[0],store=key[1],msku=key[2],
                 product_role='problem',action_type=kind,action_name=LABELS[kind],rule_code=rule,
                 execution_key=execution_key,reason=reason,status='MANUAL_REVIEW',
                 label_date='2026-09-20',rule_version='problem-v1-preview-20260921',**extra)
        return row
    eligible=set()
    for product in products:
        key=pid(product); metric=metrics.get(key); price=product['pricing_input']
        qty=number(metric.get('sales_volume')) if metric else None
        daily=qty/30 if qty is not None else None
        summary=dict(country=key[0],store=key[1],msku=key[2],sales_30d=qty,daily_sales=daily,
                     metric_date=metric.get('data_date') if metric else None,ad_state='待核广告实体')
        product_summary.append(summary)
        if not metric or metric['period_days']!=30 or qty is None or qty<0:
            diagnostic(key,'产品准入','完整30天销量缺失或异常'); continue
        if daily>1:
            diagnostic(key,'产品准入','日销已大于1，退出问题产品动作池'); continue
        eligible.add(key)
        if not price:
            diagnostic(key,'调价','定价缺失或不唯一')
        elif price['币种']!=CURRENCY[key[0]] or price.get('数据异常备注'):
            diagnostic(key,'调价','币种或定价质量异常')
        elif number(metric.get('fba_available_inventory')) is None or number(metric['fba_available_inventory'])<=0:
            diagnostic(key,'调价','FBA可售缺失或为零，断货价格测试口径待核')
        else:
            result,reason=price_action(number(price['listing价格']),number(price['10毛利润价格']),number(price['25毛利润价格']))
            if result:
                code,value=result
                actions.append(action(key,'price_decrease',code,'price:'+':'.join(key),
                                      '降至P25' if code=='100101' else '最多降5%，不低于P10',
                                      currency=price['币种'],current_value=number(price['listing价格']),suggested_value=value,
                                      p10=number(price['10毛利润价格']),p25=number(price['25毛利润价格']),price_date=price['数据日期'],
                                      sales_30d=qty,inventory=metric['fba_available_inventory'],metric_date=metric['data_date']))
            elif reason: diagnostic(key,'调价',reason)
        # 只使用实体枚举而不是有花费的竞价快照判断是否开启。
        profiles=profile_map.get((CODES[key[0]],key[1].casefold()),set())
        entity_rows=ad_by_product.get(key,[])
        active=[]; unknown=[]; nondeleted=[]
        for entity in entity_rows:
            if not not_deleted(entity): continue
            nondeleted.append(entity)
            profile=str(entity['profile_id'])
            campaign=campaigns.get((profile,str(entity['campaign_id'])))
            group=groups.get((profile,str(entity['ad_group_id'])))
            if not campaign or not group:
                unknown.append(entity); continue
            states=[str(r.get('state','')).lower() for r in (entity,campaign,group)]
            if any(s not in ('enabled','paused','archived') for s in states): unknown.append(entity)
            elif all(enabled(r) for r in (entity,campaign,group)): active.append(entity)
        if active:
            summary['ad_state']='已开启广告'
        elif len(profiles)!=1 or unknown:
            diagnostic(key,'开启广告','账号映射不唯一或广告父实体缺失，不能判定未开启')
        elif nondeleted:
            summary['ad_state']='未开启广告'
            resumable=any(all(not_deleted(e) and str(e.get('state','')).lower() in ('enabled','paused') for e in
                          (ad,campaigns[(str(ad['profile_id']),str(ad['campaign_id']))],groups[(str(ad['profile_id']),str(ad['ad_group_id']))])) for ad in nondeleted)
            actions.append(action(key,'ad_enable','100801','enable:'+':'.join(key),
                                  '有停用结构，核验后启用广告' if resumable else '现有结构含归档或删除状态，核验后重建广告',
                                  profile_id=next(iter(profiles)),currency=CURRENCY[key[0]],enable_mode='review_existing' if resumable else 'review_rebuild',
                                  entity_count=len(nondeleted),evidence_scope='已同步商品广告、活动和广告组实体',
                                  existing_structures=[dict(ad_id=str(e['ad_id']),campaign_id=str(e['campaign_id']),
                                      ad_group_id=str(e['ad_group_id']),product_ad_state=e['state'],
                                      campaign_state=campaigns[(str(e['profile_id']),str(e['campaign_id']))]['state'],
                                      ad_group_state=groups[(str(e['profile_id']),str(e['ad_group_id']))]['state'],
                                      source_time=e['update_time'] or e['create_time']) for e in nondeleted],
                                  suggested_value=None,current_value=None))
        else:
            # 缺少账号同步完整性凭证：不以空集证明未投放。
            summary['ad_state']='未发现广告记录，待核完整性'
            proposals.append(action(key,'ad_enable','100801','enable:'+':'.join(key),
                                    '已映射账号，但没有商品广告记录；补全实体同步完整性证明后可新建',
                                    profile_id=next(iter(profiles)),blocker='账号广告实体同步完整性未核实',suggested_value=None))
    for row in bids:
        key=resolve(row['country_code'],row['seller_name'],row['msku'],row['base_store_name'])
        if key not in eligible: continue
        entity='|'.join(str(row[f]) for f in ('profile_id','campaign_id','ad_group_id','object_type','object_id'))
        if row['msku_mapping_status']!='mapped' or any(number(row[f])!=1 for f in ('associated_msku_count','period_msku_count','current_enabled_msku_count')):
            diagnostic(key,'竞价','对象到产品映射不唯一',entity); continue
        if any(str(row[f]).lower()!='enabled' for f in ('campaign_state_current','ad_group_state_current','object_state_current')):
            diagnostic(key,'竞价','活动、广告组或竞价对象未开启',entity); continue
        if any(number(row[f])!=30 for f in ('source_keyword_days','source_ad_group_days','source_product_ad_days')):
            diagnostic(key,'竞价','30天来源报表不完整',entity); continue
        if (date.fromisoformat(row['mature_end'])-date.fromisoformat(row['mature_start'])).days!=29 or (date.fromisoformat(row['snapshot_date'])-date.fromisoformat(row['mature_end'])).days<7:
            diagnostic(key,'竞价','成熟观察窗口不满足30天及7天归因',entity); continue
        attrs=bid_attrs.get(row['row_key'])
        if not attrs:
            diagnostic(key,'竞价','成熟7天归因字段缺失',entity); continue
        auto=row['targeting_type']=='auto' and row['object_type']=='ad_group'
        if not auto and not(row['targeting_type']=='manual' and row['object_type']=='keyword'): continue
        c,o,spend,sales=map(number,(row['clicks'],attrs['same_sku_attributed_orders_7d'],row['cost'],attrs['same_sku_attributed_sales_7d']))
        rule,reason=bid_rule(auto,c,o,spend,sales)
        if reason: diagnostic(key,'竞价',reason,entity)
        if not rule:
            if spend==0: diagnostic(key,'曝光测试','零花费需补齐预算可用余额和首次测试标记',entity)
            continue
        code,rate=rule
        if auto:
            # 当前宽表的自动对象是广告组默认bid，不是四种自动target的独立bid。
            blocker='自动对象仅有广告组默认bid，需核实自动target是否覆盖默认竞价'
        else: blocker=None
        metric=metrics[key]; tacos=number(metric.get('tacos'))
        if rate>0:
            if not auto and tacos is not None and D('.05')<tacos<D('.1'): code,rate='100307',D('.05')
            if tacos is None or tacos>=D('.1'): blocker='TACOS缺失或达到10%，不允许扩量'
            elif auto and tacos>D('.05'): blocker='中TACOS自动扩量幅度待确认'
            else: blocker='缺少扣除未来基础消耗后的可用预算，不能生成扩量金额'
        value,bid_error=rounded_bid(number(row['current_bid']),rate,auto,number(row['bid_lower_limit']),number(row['bid_upper_limit']))
        blocker=blocker or bid_error
        result=action(key,'bid_increase' if rate>0 else 'bid_decrease',code,'bid:'+entity,
                      f'成熟30天同产品7天归因：点击{c}，订单{o}，花费{spend}，销售额{sales}',
                      currency=row['currency_code'],profile_id=str(row['profile_id']),campaign_id=str(row['campaign_id']),ad_group_id=str(row['ad_group_id']),
                      object_type=row['object_type'],object_id=str(row['object_id']),object_text=row['object_text'],
                      current_value=number(row['current_bid']),suggested_value=value if not blocker else None,
                      change_rate=rate,cost=spend,clicks=c,orders=o,sales=sales,attribution_days=7,
                      mature_start=row['mature_start'],mature_end=row['mature_end'],snapshot_date=row['snapshot_date'])
        if blocker:
            result['blocker']=blocker; proposals.append(result)
        else: actions.append(result)
    # 搜索词在广告组+标准化词粒度合并；任一同组来源有订单/保护，均不否定。
    term_groups=defaultdict(list)
    for row in terms:
        key=resolve(row['country_code'],row['seller_name'],row['msku'])
        if key not in eligible: continue
        if not row['search_term_normalized']: continue
        term_groups[(key,str(row['profile_id']),str(row['campaign_id']),str(row['ad_group_id']),row['search_term_normalized'])].append(row)
    for (key,profile,campaign,group,word),rows in term_groups.items():
        if not all(number(r['is_auto_campaign'])==1 for r in rows): continue
        if any(number(r['clicks']) is None or number(r['cost']) is None or number(r['clicks'])<0 or number(r['cost'])<0 for r in rows):
            diagnostic(key,'搜索词','点击或花费缺失/负数',word); continue
        clicks=sum(number(r['clicks']) for r in rows)
        if clicks<10: continue
        entity='|'.join((profile,campaign,group,word))
        attrs=[term_attrs.get(r['row_key']) for r in rows]
        if any(not a or number(a['attribution_7d_mature'])!=1 for a in attrs):
            diagnostic(key,'否词','7天归因未成熟或缺失',entity); continue
        if any(number(r['source_search_term_days'])!=30 or number(r['source_product_ad_days'])!=30 or
               r['period_msku_candidates']!=key[2] or r['current_msku_candidates']!=key[2] for r in rows):
            diagnostic(key,'搜索词','观察窗口不完整或广告组产品映射不唯一',entity); continue
        if all(number(a['same_orders_7d']) is not None and number(a['same_sales_7d']) is not None for a in attrs):
            same_orders=sum(number(a['same_orders_7d']) for a in attrs)
            same_sales=sum(number(a['same_sales_7d']) for a in attrs)
            term_cost=sum(number(r['cost']) for r in rows)
            if same_orders>=1 and same_sales>0 and term_cost/same_sales<=D('.3') and all(r['search_term_type']=='keyword' for r in rows):
                tacos=number(metrics[key].get('tacos'))
                blocker='新增精准缺少相关性、有效精准/否词冲突、目标广告组及可用预算核验'
                if tacos is None or tacos>=D('.1'): blocker='TACOS缺失或达到10%，不允许加精准词'
                proposals.append(action(key,'keyword_add_exact','100503','exact:'+entity,
                                        '自动来源文字词满足点击、同产品订单及ACOS门槛',
                                        profile_id=profile,source_campaign_id=campaign,source_ad_group_id=group,
                                        object_text=word,clicks=clicks,orders=same_orders,cost=term_cost,sales=same_sales,
                                        currency=rows[0]['currency_code'],suggested_value=None,blocker=blocker,attribution_days=7))
        if clicks<49: continue
        if any(number(a['orders_7d']) is None or number(a['orders_7d'])>0 or number(r['orders_30d']) is None or number(r['orders_30d'])>0 for r,a in zip(rows,attrs)):
            continue
        if any(r['msku_mapping_status']!='mapped' or number(r['term_protection_complete'])!=1 or
               any(number(r[f])!=0 for f in ('is_brand_term','is_core_category_term','is_new_product_term')) for r in rows):
            diagnostic(key,'否词','映射、品牌/核心/新品保护条件不通过',entity); continue
        if any(r['search_term_type']!='keyword' for r in rows):
            diagnostic(key,'否词','ASIN否定需核对全店自有ASIN，暂不输出',entity); continue
        if not enabled(campaigns.get((profile,campaign))) or not enabled(groups.get((profile,group))):
            diagnostic(key,'否词','当前活动或广告组未开启',entity); continue
        code='100502' if clicks>=63 else '100501'
        actions.append(action(key,'keyword_negative_exact',code,'negative:'+entity,'自动来源，零订单高点击且否词保护通过',
                              profile_id=profile,campaign_id=campaign,ad_group_id=group,object_type='search_term',object_text=word,
                              negative_match_type='negativeExact',clicks=clicks,orders=0,
                              cost=sum(number(r['cost']) or D(0) for r in rows),currency=rows[0]['currency_code'],
                              attribution_days=7,mature_start=rows[0]['mature_start'],mature_end=rows[0]['mature_end']))
    price_actions=[r for r in actions if r['action_type']=='price_decrease']
    ad_actions,rejected=select_ads([r for r in actions if r['action_type']!='price_decrease'])
    for row,reason in rejected: diagnostic(pid(row),'动作收口',reason,row['execution_key'])
    final=sorted(price_actions+ad_actions,key=lambda r:(pid(r),r['action_type'],r['execution_key']))
    for row in proposals: row['status']='BLOCKED'
    final_count=Counter(pid(r) for r in final)
    proposal_count=Counter(pid(r) for r in proposals)
    reasons=defaultdict(set)
    for row in diagnostics: reasons[pid(row)].add(row['reason'])
    for row in proposals: reasons[pid(row)].add(row['blocker'])
    for row in product_summary:
        row['action_count']=final_count[pid(row)]; row['blocked_candidate_count']=proposal_count[pid(row)]
        row['reasons']=sorted(reasons[pid(row)])
        if not row['action_count'] and not row['reasons']: row['reasons']=['未命中当前可输出的动作条件']
    manifest=dict(generated_at=datetime.now().isoformat(timespec='seconds'),products=len(products),eligible_products=len(eligible),
                  products_with_actions=len(final_count),action_count=len(final),action_counts=dict(Counter(r['action_type'] for r in final)),
                  blocked_candidates=len(proposals),blocker_counts=dict(Counter(r['blocker'] for r in proposals)),
                  diagnostic_counts=dict(Counter(r['reason'] for r in diagnostics)),
                  attribution='30天观察窗口；7天同产品归因。30天归因未成熟，不用于判定。',
                  no_database_writes=True,no_platform_writes=True)
    for name,value in [('final_actions',final),('blocked_candidates',proposals),('diagnostics',diagnostics),('products',product_summary),('manifest',manifest)]:
        write_json(OUT/f'{name}.json',value)
    fields=['country','store','msku','action_name','rule_code','status','currency','current_value','suggested_value','change_rate',
            'profile_id','campaign_id','ad_group_id','object_type','object_id','object_text','clicks','orders','cost','sales',
            'reason','blocker','action_id','mature_start','mature_end','attribution_days','price_date','metric_date','p10','p25','existing_structures']
    write_csv(OUT/'问题产品最终动作.csv',final,fields)
    write_csv(OUT/'问题产品待核候选.csv',proposals,fields)
    write_csv(OUT/'问题产品全量覆盖.csv',product_summary,['country','store','msku','metric_date','sales_30d','daily_sales','ad_state','action_count','blocked_candidate_count','reasons'])
    render_html(final,proposals,product_summary,manifest)
    print(json.dumps(manifest,ensure_ascii=False,indent=2),flush=True)


def render_html(actions,blocked,products,manifest):
    payload=json.dumps({'actions':actions,'blocked':blocked,'products':products},ensure_ascii=False,default=str).replace('<','\\u003c')
    template='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>问题产品动作预览</title>
<style>body{font:14px system-ui;margin:28px;background:#f5f7fa;color:#172b40}h1{font-size:24px}button,select,input{padding:9px;margin:5px;border:1px solid #bcc8d3;border-radius:5px}table{width:100%;border-collapse:collapse;background:white}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd;vertical-align:top;max-width:400px;word-break:break-word}th{position:sticky;top:0;background:#dfeaf3}.note{padding:14px;background:#fff4d9;line-height:1.8}.stats{font-size:18px;margin:20px 0}small{color:#536575}</style>
<h1>问题产品 · 首轮动作预览</h1><div class="stats">__SUMMARY__</div>
<p class="note">仅本地预览，未写数据库或操作广告。最终建议均需人工审核。标签/广告快照：2026-09-20，价格：2026-09-21。广告采用30天观察窗口、成熟7天归因。<br>“待核候选”不属于最终动作，缺少平台bid边界或预算等必要输入时不生成金额。未发现广告记录不直接等于未开启广告。</p>
<button onclick="mode='actions';draw()">最终动作</button><button onclick="mode='blocked';draw()">待核候选</button><button onclick="mode='products';draw()">全部产品</button>
<input id="q" placeholder="搜索国家 / 店铺 / MSKU / 原因" oninput="draw()"><select id="type" onchange="draw()"><option value="">全部动作</option></select><span id="count"></span>
<table><thead id="head"></thead><tbody id="body"></tbody></table>
<script>const data=__DATA__;let mode='actions';const labels={country:'国家',store:'店铺',msku:'MSKU',action_name:'动作',rule_code:'规则',currency:'币种',current_value:'当前值',suggested_value:'建议值',change_rate:'规则幅度',object_text:'词/对象',reason:'命中原因',blocker:'待核原因',daily_sales:'日销',ad_state:'广告状态',action_count:'最终动作数',blocked_candidate_count:'待核数',reasons:'说明'};
for(const x of [...new Set([...data.actions,...data.blocked].map(r=>r.action_name))]){let o=document.createElement('option');o.value=x;o.textContent=x;document.getElementById('type').append(o)}
function cell(tag,value){let e=document.createElement(tag);e.textContent=value===undefined||value===null?'—':Array.isArray(value)?value.join('；'):value;return e}
function draw(){let q=document.getElementById('q').value.toLowerCase(),t=document.getElementById('type').value;let rows=data[mode].filter(r=>JSON.stringify(r).toLowerCase().includes(q)&&(!t||mode==='products'||r.action_name===t));let cols=mode==='products'?['country','store','msku','daily_sales','ad_state','action_count','blocked_candidate_count','reasons']:['country','store','msku','action_name','rule_code','currency','current_value','suggested_value','change_rate','object_text','reason',...(mode==='blocked'?['blocker']:[])];let h=document.getElementById('head'),b=document.getElementById('body');h.replaceChildren();b.replaceChildren();let tr=document.createElement('tr');cols.forEach(c=>tr.append(cell('th',labels[c])));tr.append(cell('th','完整证据'));h.append(tr);for(let r of rows){let tr=document.createElement('tr');cols.forEach(c=>tr.append(cell('td',r[c])));let td=document.createElement('td'),details=document.createElement('details');details.append(cell('summary','展开'));details.append(cell('pre',JSON.stringify(r,null,2)));td.append(details);tr.append(td);b.append(tr)}document.getElementById('count').textContent=` ${rows.length} 条`}draw();</script></html>'''
    summary=f"覆盖 {manifest['products']} 个问题产品 · {manifest['products_with_actions']} 个产品有最终建议 · {manifest['action_count']} 条动作 · {manifest['blocked_candidates']} 条待核候选"
    (OUT/'问题产品动作预览.html').write_text(template.replace('__SUMMARY__',html.escape(summary)).replace('__DATA__',payload),encoding='utf-8')


if __name__=='__main__': main()
