"""Pure return-event and suggestion rules. No database or advertising writes."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

RULE_VERSION = "return-v14-20261012-dynamic-price-visits"
ACOS_TARGET = Decimal('.20')
ACOS_MAX = Decimal('.50')
STATE_LABELS = {"observe":"自然观察", "good":"恢复较好", "improving":"改善中",
                "poor":"恢复不足", "sales_repair":"销量修复", "risk":"利润风险", "unknown":"数据不足",
                "history_missing":"历史数据不足", "history_zero":"历史零销量",
                "data_missing":"返场经营数据缺失", "stock_missing":"库存数据缺失",
                "stock_interrupted":"库存中断", "no_sales":"当前评价窗口无销量",
                "profit_unknown":"利润无法评价"}
STATUS_LABELS = {"ready":"条件已满足", "pending":"待核建议", "blocked":"暂不调整", "hold":"保持"}
ACTION_LABELS = {"hold":"保持", "check":"人工核查", "restore":"恢复已有广告",
                 "start_ad":"建议开启广告",
                 "bid_up":"提高竞价", "bid_down":"降低竞价", "budget":"申请预算",
                 "price_up":"提高一档价格", "price_down":"降低一档价格"}

STRATEGY_COUNTRIES = {'德国','法国','意大利','西班牙','荷兰','英国','美国',
                      'de','fr','it','es','nl','uk','gb','us'}


def strategy_country(country):
    return str(country or '').strip().lower() in STRATEGY_COUNTRIES


def start_ad_suggestion():
    result=suggestion('ad','start_ad','该国家未匹配到广告记录，建议开启广告；不代表其他国家没有广告')
    result['checks']=['确认该站点商品可售且可以投放','开启前确认没有遗漏的已有活动，避免重复建广告',
                      '竞价、预算和投放对象另行设置；本页不自动开户或投放']
    return result


def dec(value):
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except Exception:
        return None


def at_least_potential(qty, margin):
    qty, margin = dec(qty), dec(margin)
    return bool(qty is not None and margin is not None and
                ((qty > 5 and margin >= Decimal('.05')) or
                 (1 <= qty <= 5 and margin >= Decimal('.10'))))


def role(qty, margin):
    qty, margin = dec(qty), dec(margin)
    if qty is None or margin is None:
        return "不可判"
    if (qty > 5 and margin > Decimal('.15')) or (1 <= qty <= 5 and margin > Decimal('.25')):
        return "明星"
    if at_least_potential(qty, margin):
        return "潜力"
    if (0 < qty < 1 and margin > Decimal('.05')) or (1 <= qty <= 5 and Decimal('.05') <= margin < Decimal('.10')):
        return "瘦狗"
    return "问题"


def exit_target(baseline):
    return '潜力' if baseline.get('role') in ('潜力','明星') else '瘦狗'


def meets_exit_target(qty, margin, target):
    accepted = ('潜力','明星') if target == '潜力' else ('瘦狗','潜力','明星')
    return role(qty,margin) in accepted


def build_events(rows):
    events, zeros, first_zero, confirmed, previous = [], 0, None, None, None
    for row in sorted(rows, key=lambda r:r['day']):
        day, stock = row['day'], dec(row.get('stock'))
        if previous is not None and day != previous + timedelta(days=1):
            zeros, first_zero = 0, None
        if stock == 0:
            if zeros == 0:
                first_zero = day
            zeros += 1
            if zeros == 3 and confirmed is None:
                confirmed = first_zero
        else:
            zeros, first_zero = 0, None
        if confirmed is not None and stock is not None and stock >= 5:
            events.append({'stockout_date':confirmed, 'confirmed_date':confirmed+timedelta(days=2),
                           'return_date':day, 'round':len(events)+1})
            confirmed = None
        previous = day
    return events


def metrics(by_day, end, days, require_stock=True):
    start = end - timedelta(days=days-1)
    rows = [by_day.get(start+timedelta(days=i)) for i in range(days)]
    missing = [start+timedelta(days=i) for i,r in enumerate(rows)
               if r is None or any(dec(r.get(k)) is None for k in ('qty','revenue','profit'))]
    stock_missing = [start+timedelta(days=i) for i,r in enumerate(rows) if r is None or dec(r.get('stock')) is None]
    zero_days = [r['day'] for r in rows if r and dec(r.get('stock')) is not None and dec(r['stock']) <= 0]
    complete = not missing and (not require_stock or not stock_missing)
    stocked = complete and not zero_days and not stock_missing
    result = dict(start=start, end=end, days=days, complete=complete, stocked=stocked,
                  missing=missing, stock_missing=stock_missing, zero_days=zero_days,
                  qty=None, revenue=None, profit=None, daily=None, margin=None, sessions=None, role='不可判')
    if not complete:
        return result
    for k in ('qty','revenue','profit'):
        result[k] = sum(dec(r[k]) for r in rows)
    result['daily'] = result['qty']/days
    result['margin'] = result['profit']/result['revenue'] if result['revenue'] > 0 else None
    result['role'] = role(result['daily'], result['margin'])
    if all(dec(r.get('sessions')) is not None for r in rows):
        result['sessions'] = sum(dec(r['sessions']) for r in rows)
    result['selling_days'] = sum(dec(r['qty']) > 0 for r in rows)
    return result


def historical_baseline(by_day, stockout_date):
    # Latest complete 30-day in-stock evidence is retained through later outages.
    ends = sorted((d for d in by_day if d < stockout_date), reverse=True)
    for n in (30, 14):
        for end in ends:
            m = metrics(by_day, end, n)
            if m['stocked'] and m['margin'] is not None:
                m['evidence'] = ('有效' if end == stockout_date-timedelta(days=1) else '沿用最后有效')+f'{n}天'
                return m
    reference=metrics(by_day,stockout_date-timedelta(days=1),30)
    if reference['complete'] and reference['revenue']==0:
        reason='未找到有效角色基准；断货前30天销售额为0，订单毛利率无法计算，实际历史数据仍保留'
    elif reference['complete'] and reference['revenue'] is not None and reference['revenue']<0:
        reason='未找到有效角色基准；断货前30天销售额为负，需核查退货或数据异常'
    else:
        reason='没有满足完整数据、连续有货和毛利率可计算条件的30天或14天历史窗口'
    return {'daily':None,'margin':None,'role':'不可判','start':None,'end':None,'days':None,'evidence':reason}


def improving(by_day, end):
    seven, last, prior = metrics(by_day,end,7), metrics(by_day,end,3), metrics(by_day,end-timedelta(days=3),3)
    if not all(m['stocked'] for m in (seven,last,prior)):
        return False
    if any(m['margin'] is None or m['margin'] < Decimal('.05') for m in (seven,last)):
        return False
    if prior['margin'] is not None and last['margin'] < prior['margin']:
        return False
    if last['selling_days'] < 2:
        return False
    if prior['qty'] == 0:
        return last['qty'] >= 3
    return last['qty'] >= prior['qty']*Decimal('1.2') and last['qty']-prior['qty'] >= 2


def comparison_days(age):
    return age if age<=21 else (21 if age<30 else 30)


def consecutive_zero_stock_days(by_day, end, days):
    longest=streak=0
    for i in range(days):
        day=end-timedelta(days=days-1-i)
        stock=dec((by_day.get(day) or {}).get('stock'))
        streak=streak+1 if stock==0 else 0
        longest=max(longest,streak)
    return longest


def comparison_metrics(by_day, end, days):
    """Sales and finance are independent; exit metrics retain their strict contract."""
    result=metrics(by_day,end,days)
    dates=[end-timedelta(days=i) for i in range(days)]
    rows=[by_day.get(d) for d in dates]
    result['sales_missing']=sorted(d for d,r in zip(dates,rows) if not r or dec(r.get('qty')) is None)
    result['sales_complete']=not result['sales_missing']
    result['financial_complete']=all(r and dec(r.get('revenue')) is not None and dec(r.get('profit')) is not None for r in rows)
    result['finance_missing']=sorted(d for d,r in zip(dates,rows) if not r or dec(r.get('revenue')) is None or dec(r.get('profit')) is None)
    result['inventory_complete']=not result['stock_missing']
    result['max_zero_stock_days']=consecutive_zero_stock_days(by_day,end,days)
    result['stocked']=result['sales_complete'] and result['inventory_complete'] and not result['zero_days']
    if result['sales_complete']:
        result['qty']=sum(dec(r['qty']) for r in rows)
        result['daily']=result['qty']/days
    if all(r and dec(r.get('sessions')) is not None for r in rows):
        result['sessions']=sum(dec(r['sessions']) for r in rows)
    if result['financial_complete']:
        result['revenue']=sum(dec(r['revenue']) for r in rows)
        result['profit']=sum(dec(r['profit']) for r in rows)
        result['margin']=result['profit']/result['revenue'] if result['revenue']>0 else None
    result['role']=role(result['daily'],result['margin'])
    return result


def recovery_comparison(by_day, event, end, age):
    days=comparison_days(age)
    current=comparison_metrics(by_day,end,days)
    history=None
    for day in sorted((d for d in by_day if d<event['stockout_date']),reverse=True):
        candidate=comparison_metrics(by_day,day,days)
        if candidate['stocked']:
            history=candidate
            history['evidence']=('断货前紧邻' if day==event['stockout_date']-timedelta(days=1) else '沿用最后有效')+f'{days}天销量窗口'
            break
    ratio=current['daily']/history['daily'] if history and history['daily'] and current['daily'] is not None else None
    issues=[]
    if current['sales_missing'] or not current['financial_complete']:issues.append('data_missing')
    if current['stock_missing']:issues.append('stock_missing')
    if current['max_zero_stock_days']>=3:issues.append('stock_interrupted')
    if history is None:issues.append('history_missing')
    elif history['daily']==0:issues.append('history_zero')
    if current['sales_complete'] and current['qty']==0:issues.append('no_sales')
    if current['margin'] is None:issues.append('profit_unknown')
    return dict(days=days,current=current,history=history,ratio=ratio,issues=issues)


def sales_repair_first(event):
    m=event.get('comparison',{}).get('current',{})
    daily=dec(m.get('daily'))
    return bool(m.get('sales_complete') and daily is not None and 0<=daily<1)


def comparison_state(age, comparison, is_improving):
    m=comparison['current'];issues=comparison['issues']
    for state in ('stock_interrupted','stock_missing'):
        if state in issues:return state
    if not m['sales_complete']:return 'data_missing'
    if age>=8 and 'no_sales' in issues:return 'no_sales'
    if age>=8 and m['daily'] is not None and 0<=m['daily']<1:
        return 'improving' if age<=14 and is_improving else 'sales_repair'
    if m['margin'] is not None and m['margin']<Decimal('.05'):return 'risk'
    if age<=7:return 'observe'
    if 'no_sales' in issues:return 'no_sales'
    if m['margin'] is None:return 'profit_unknown'
    if comparison['history'] is None:return 'history_missing'
    if 'history_zero' in issues:return 'history_zero'
    if comparison['ratio']>=Decimal('.8'):return 'good'
    if age<=14 and is_improving:return 'improving'
    return 'poor'


def recovery_state(day_number, recovery, margin, complete, is_improving):
    if not complete:
        return 'unknown'
    if margin is not None and dec(margin) < Decimal('.05'):
        return 'risk'
    if day_number <= 7:
        return 'observe'
    if recovery is None or margin is None:
        return 'unknown'
    if dec(recovery) >= Decimal('.8') and dec(margin) >= Decimal('.05'):
        return 'good'
    if day_number < 14 and is_improving:
        return 'improving'
    return 'poor'


def role_gaps(m, target='潜力'):
    reasons = []
    if m['missing'] or m['stock_missing']:
        reasons.append(f"评价窗口缺少{len(set(m['missing']+m['stock_missing']))}天完整数据")
    if m['zero_days']:
        reasons.append(f"评价窗口内有{len(m['zero_days'])}天无可售库存")
    if m['daily'] is not None:
        if target=='潜力' and m['daily']<1:
            reasons.append(f"日销{m['daily']:.2f}件，未达到1件")
        elif target=='瘦狗' and m['daily']<=0:
            reasons.append('当前评价窗口无有效销量，未达到瘦狗')
    if m['margin'] is None:
        reasons.append('订单毛利率不可计算')
    elif m['daily'] is not None:
        threshold = Decimal('.05') if target=='瘦狗' or m['daily'] > 5 else Decimal('.10')
        strict = target=='瘦狗' and 0<m['daily']<1
        if m['margin'] < threshold or (strict and m['margin']==threshold):
            requirement='需高于' if strict else '最低需要'
            reasons.append(f"订单毛利率{m['margin']:.1%}，该日销档{requirement}{threshold:.0%}")
    return reasons


def evaluate_event(rows, event, as_of):
    by_day = {r['day']:r for r in rows if r['day'] <= as_of}
    start = event['return_date']
    age = (as_of-start).days+1
    baseline = historical_baseline(by_day,event['stockout_date'])
    target = exit_target(baseline)
    pre_stockout=metrics(by_day,event['stockout_date']-timedelta(days=1),30)
    pre_timeline=[]
    for i in range(30):
        day=pre_stockout['start']+timedelta(days=i)
        row=by_day.get(day,{})
        m=metrics(by_day,day,1)
        pre_timeline.append(dict(day=day,stock=row.get('stock'),qty=row.get('qty'),margin=m['margin'],role=m['role'],complete=m['complete']))
    seven = metrics(by_day,as_of,min(7,age))
    comparison=recovery_comparison(by_day,event,as_of,age)
    recovery=comparison['ratio']
    previous7=comparison_metrics(by_day,as_of-timedelta(days=7),7) if age>=14 else None
    recent7=comparison_metrics(by_day,as_of,min(7,age))
    trend=dict(current=recent7,previous=previous7,daily_change=None,margin_change=None,warning=None)
    if previous7 and recent7['stocked'] and previous7['stocked']:
        if previous7['daily'] and recent7['daily'] is not None:
            trend['daily_change']=recent7['daily']/previous7['daily']-1
        if recent7['margin'] is not None and previous7['margin'] is not None:
            trend['margin_change']=recent7['margin']-previous7['margin']
        if (trend['daily_change'] is not None and trend['daily_change']<0) or (trend['margin_change'] is not None and trend['margin_change']<0):
            trend['warning']='近7天日销或订单毛利率较前7天下降，请核对近期变化，不据此自动调整'
    elif previous7:
        trend['warning']='近7天趋势涉及缺数或无可售库存日期，不能直接认定经营下滑'
    exit_status, exit_date, streak, exit_evidence = 'tracking', None, 0, None
    if age >= 7:
        initial = metrics(by_day,start+timedelta(days=6),7)
        stable = initial['stocked'] and meets_exit_target(initial['daily'],initial['margin'],target)
        for i in range(7):
            m = metrics(by_day,start+timedelta(days=i),1)
            stable = stable and m['stocked'] and meets_exit_target(m['daily'],m['margin'],target)
        if stable:
            exit_status, exit_date, exit_evidence = 'early', start+timedelta(days=6), initial
    current_evaluation = metrics(by_day,as_of,comparison_days(age))
    confirmations = []
    if exit_date is None:
        for i in range(7,age):
            day = start+timedelta(days=i)
            evaluation = metrics(by_day,day,comparison_days(i+1))
            passes = evaluation['stocked'] and meets_exit_target(evaluation['daily'],evaluation['margin'],target)
            streak = streak+1 if passes else 0
            confirmations = (confirmations+[evaluation])[-3:] if passes else []
            if streak == 3:
                exit_status, exit_date, exit_evidence = 'normal',day,evaluation
                break
    reasons = []
    if exit_date is not None:
        reasons = [f'D1—D7每天及整体稳定达到至少{target}' if exit_status == 'early' else f'按返场天数对应窗口评价角色，连续3天达到至少{target}']
    elif age < 7:
        reasons = [f'自然恢复第{age}天，D7完整数据形成后首次判断提前退出']
    elif age == 7:
        reasons = ['D1—D7未满足每天稳定达标，D8起按对应窗口开始连续确认']
    else:
        reasons = role_gaps(current_evaluation,target)
        if not reasons:
            reasons = [f'连续达标{streak}/3天']
    state = comparison_state(age,comparison,improving(by_day,as_of) if age>=7 else False)
    if age >= 8 and state == 'good' and not meets_exit_target(current_evaluation['daily'],current_evaluation['margin'],target):
        note = '销量恢复较好，但角色仍有差距；核查利润或日销，不自动增加广告'
    else:
        note = {'observe':'7天自然恢复期内保持价格和有效广告','good':'销量恢复率至少80%，订单毛利率至少5%',
                'improving':'近3天销量和出单天数满足改善条件，最长观察至D14',
                'poor':'恢复不足，先检查已有广告，再审核价格','risk':'订单毛利率低于5%，优先检查消耗、售价与成本',
                'sales_repair':'主评价窗口日销不足1件，先修复销量；暂不以利润不足限制拉量，库存、预算及复评限制仍保留',
                'unknown':'库存、历史基准或当前经营数据不足，不能视为恢复失败',
                'history_missing':'没有完整连续有货的同长度历史销量窗口；当前表现仍可评价',
                'history_zero':'对应历史日销为0，恢复率不适用；当前出单和利润单独评价',
                'data_missing':'返场评价窗口缺少销量记录，不能按0填充',
                'stock_missing':'返场评价窗口库存记录缺失，暂不进行正常拉量',
                'stock_interrupted':'返场评价窗口内连续至少3个自然日可售库存为0，先处理库存，不归因恢复能力差',
                'no_sales':f"当前{comparison['days']}天评价窗口销量记录完整且总销量为0，先检查商品及广告状态",
                'profit_unknown':'销量仍可比较，但销售额或毛利数据无法支持利润评价，暂不加投'}[state]
    timeline = []
    for i in range(age):
        d=start+timedelta(days=i)
        r=by_day.get(d,{})
        m=metrics(by_day,d,1)
        timeline.append(dict(day=d,stock=r.get('stock'),qty=r.get('qty'),margin=m['margin'],role=m['role'],complete=m['complete']))
    return {**event,'age':age,'exit_target':target,'exit_status':exit_status,'exit_date':exit_date,'exit_reasons':reasons,
            'confirmation_days':streak,'exit_evidence':exit_evidence,'baseline':baseline,'recent':seven,
            'pre_stockout':pre_stockout,'pre_stockout_timeline':pre_timeline,
            'current_evaluation':current_evaluation,'exit_confirmation':confirmations,
            'recovery':recovery,'comparison':comparison,'trend7':trend,'state':state,'state_label':STATE_LABELS[state],
            'state_reason':note,'phase':'观察期' if age<=7 else ('干预期' if age<=21 else '持续干预期'),
            'timeline':timeline,'current_stock':by_day.get(as_of,{}).get('stock')}


def adjacent_price(current, ladder, direction, precision='0.01'):
    current = dec(current)
    prices=[(f'p{x}',dec(ladder.get(f'p{x}'))) for x in (10,15,20,25,30,35)]
    if current is None or current <= 0 or any(v is None or v<=0 for _,v in prices):
        return {'target':None,'reason':'当前价或P10至P35档位不完整'}
    if any(a[1]>=b[1] for a,b in zip(prices,prices[1:])):
        return {'target':None,'reason':'档位价格重复或顺序异常'}
    matches=[(k,v) for k,v in prices if (v<current if direction=='down' else v>current)]
    if not matches:
        return {'target':None,'reason':'已到P10降价底线' if direction=='down' else '已到P35涨价上限'}
    tier,raw = matches[-1] if direction=='down' else matches[0]
    amount=raw.quantize(Decimal(precision),rounding=ROUND_CEILING)
    if amount>prices[-1][1] or amount<prices[0][1] or (direction=='down' and amount>=current) or (direction=='up' and amount<=current):
        return {'target':None,'reason':'金额取整后超出档位边界或没有实际变化'}
    return {'target':amount,'tier':tier.upper(),'change_rate':amount/current-1,'reason':'按相邻档位逐档调整'}


def effective_bid(value, default):
    value = dec(value)
    if value is not None and value < 0:
        return None
    return value if value is not None and value > 0 else (dec(default) if dec(default) is not None and dec(default)>0 else None)


def bid_target(current, change, step='.01'):
    current,change,step=dec(current),dec(change),dec(step)
    if current is None or current<=0 or step is None or step<=0:
        return None
    rounding=ROUND_FLOOR if change>0 else ROUND_CEILING
    value=((current*(1+change)/step).to_integral_value(rounding=rounding))*step
    return value if value>0 and value!=current else None


def suggestion(kind, action, reason, status='pending', **values):
    return dict(kind=kind,action=action,label=ACTION_LABELS[action],status=status,reason=reason,
                target=None,checks=[],**values)


def acos_policy(acos):
    """Fixed operational bands, never a claim about an object's actual profitability."""
    acos=dec(acos)
    if acos is None or acos<0:
        return dict(acos_band='unknown',acos_band_label='ACOS无法计算',acos=None,
                    acos_target=ACOS_TARGET,acos_max=ACOS_MAX)
    band,label=(('target','ACOS≤20%：积极拉量') if acos<=ACOS_TARGET else
                ('cautious','20%<ACOS≤30%：谨慎拉量') if acos<=Decimal('.30') else
                ('observe','30%<ACOS≤40%：保持观察') if acos<=Decimal('.40') else
                ('reduce','40%<ACOS≤50%：收紧花费') if acos<=ACOS_MAX else
                ('over_limit','ACOS>50%：超限止损'))
    return dict(acos_band=band,acos_band_label=label,acos=acos,
                acos_target=ACOS_TARGET,acos_max=ACOS_MAX)


def ad_candidate(ad, dos=None, sales_first=False):
    result=suggestion('ad','check','核查广告状态与效果')
    result.update(acos_policy(None))
    result['current']=effective_bid(ad.get('current_bid'),ad.get('default_bid'))
    if ad.get('mapping_count') != 1:
        result['reason']='广告对象关联多个商品或归属不明，不能按单个MSKU调整'
        return result
    if not ad.get('enabled',True):
        result.update(action='restore',label=ACTION_LABELS['restore'],reason='已有广告未投放；核实是否因断货暂停及原设置', target=None)
        old_cost,old_sales,old_orders=(dec(ad.get(k)) for k in ('cost','sales','orders'))
        if ad.get('mature') and ad.get('days',0)>=7 and old_orders is not None and old_orders>=3 and old_sales is not None and old_sales>0 and old_cost is not None and old_cost>=0:
            result.update(acos_policy(old_cost/old_sales))
            if result['acos']>ACOS_MAX:
                result.update(status='blocked',reason='已有成熟对象ACOS超过50%，不能直接恢复原高消耗设置')
                return result
        if dos is None or dos<14:
            result.update(status='blocked',reason='库存覆盖不足14天或未知，不能恢复试投')
        return result
    if not ad.get('mature'):
        result['reason']='返场后的广告订单尚未归因完整，暂不判断零单或低效'
        return result
    clicks,orders,cost,sales=(dec(ad.get(k)) for k in ('clicks','orders','cost','sales'))
    if any(v is None for v in (clicks,orders,cost,sales)):
        result['reason']='广告点击、花费或订单数据不完整'
        return result
    if any(v<0 for v in (clicks,orders,cost,sales)):
        result['reason']='广告点击、订单、花费或销售额为负，需核对报表'
        return result
    if clicks == 0 and orders>0:
        result['reason']='没有点击但存在广告订单，先核对归因报表及投放状态'
        return result
    # Zero orders are evaluated independently; zero sales never means ACOS=0.
    acos=cost/sales if orders>0 and sales>0 else None
    result.update(acos_policy(acos))
    action,change=None,None
    if orders==0:
        result['zero_order_clicks']=dict(clicks=clicks,orders=orders,
            click_band='below_20' if clicks<20 else ('20_39' if clicks<40 else '40_plus'),
            first_threshold=20,second_threshold=40,is_trial_rule=True,
            coverage_verified=ad.get('zero_order_coverage_verified'))
        if sales>0:
            result['reason']='对象零订单但归因销售额大于0，先核对归因报表'
        elif ad.get('zero_order_coverage_verified') is False:
            result['reason']='成熟零单：对象评价窗口报表或库存日期覆盖不完整，不能把缺记录当零单'
        elif clicks>=40:
            action,change='bid_down',Decimal('-.20')
        elif clicks>=20:
            action,change='bid_down',Decimal('-.10')
        else:
            result.update(action='hold',label='暂不调整竞价',status='hold',
                          reason=f"该对象成熟点击{clicks:g}次、0单，不足20次点击，继续观察")
    elif orders>0 and sales<=0:
        result['reason']='已有广告订单但归因销售额不大于0，ACOS无法计算'
    elif orders>=3 and ad.get('days',0)>=7:
        band=result['acos_band']
        if band in ('reduce','over_limit'):
            action,change='bid_down',Decimal('-.20') if band=='over_limit' else Decimal('-.10')
        elif band=='observe' or (band=='cautious' and not sales_first):
            result.update(action='hold',label='暂不调整竞价',status='hold',
                          reason=result['acos_band_label']+'；不增加竞价或预算')
        elif clicks>=20:
            minimum=14 if band=='cautious' else 7
            if dos is None or dos<minimum:
                result.update(status='blocked',reason=f'库存覆盖不足{minimum}天或未知，暂不增加投放')
            else:
                action='bid_up'
                change=Decimal('.03') if band=='cautious' or dos<14 else Decimal('.10')
    if action:
        result.update(action=action,label=ACTION_LABELS[action],change_rate=change,
                      target=bid_target(result['current'],change,ad.get('bid_step','.01')),
                      reason=(f"该对象成熟点击{clicks:g}次、0单；{'达到40次' if clicks>=40 else '20—39次'}点击，候选降低竞价{abs(change)*100:g}%（试算规则）" if orders==0 else
                              f"{result['acos_band_label']}；候选降低{abs(change)*100:g}%" if change<0 else
                              f"{result['acos_band_label']}；销量修复小步测试，候选提高3%" if result['acos_band']=='cautious' else
                              f"{result['acos_band_label']}；库存覆盖限制后候选提高{change*100:g}%"))
        if result['target'] is None:
            result.update(action='check',label='无法判断竞价：缺少有效金额',
                          reason='当前有效竞价缺失或取整后无变化')
    return result


def allocate_budget(actions, balances):
    remaining={k:max(Decimal(0),dec(v) or Decimal(0)) for k,v in balances.items()}
    allocated=[]
    for a in actions:
        amount=min(max(Decimal(0),dec(a['amount']) or Decimal(0)),remaining.get(a['pool'],Decimal(0)))
        remaining[a['pool']]=remaining.get(a['pool'],Decimal(0))-amount
        allocated.append(amount)
    return allocated


def review_checks(action, checks):
    """Unknown evidence is pending, known failed checks are restrictions."""
    failed=[name+'未通过' for name,value in checks.items() if value is False]
    unknown=[name+'待核' for name,value in checks.items() if value is None]
    action['checks']=failed+unknown
    action['status']='blocked' if failed else ('pending' if unknown else 'ready')
    return action


def budget_candidate(context):
    result=suggestion('ad','check','广告效率或实际预算限制尚未核实')
    if context.get('efficient') is not True or context.get('limited') is not True:
        return result
    result.update(acos_policy(context.get('acos')))
    if result['acos'] is None:
        result['reason']='对象ACOS无法计算，不能确认增加预算效率条件'
        return result
    if result['acos']>ACOS_TARGET:
        result.update(status='blocked',reason='对象ACOS超过20%，不新增预算')
        return result
    dos=dec(context.get('dos'))
    if dos is None or dos<14:
        result.update(status='blocked',reason='库存覆盖不足14天或未知，不增加预算')
        return result
    month,week,pool,profit=(dec(context.get(k)) for k in ('month','week','pool_remaining','profit_capacity'))
    if month is None or week is None or month<=0 or week<=0:
        result['reason']='月周配置预算为零或缺失，不能申请统一兜底额度'
        return result
    result.update(action='budget',label=ACTION_LABELS['budget'],reason='效率合格且确有预算限制，在池内申请测试额度',
                  configuration_cap=min(month*Decimal('.10'),week*Decimal('.25')))
    sales_first=context.get('sales_first',False)
    if pool is None or (profit is None and not sales_first):
        result['checks']=['共享池真实余额与可承受利润额度待核']
        return result
    caps=[result['configuration_cap'],pool]
    if not sales_first:caps.append(profit)
    result['target']=max(Decimal(0),min(caps))
    if result['target']==0:
        result.update(status='blocked',reason='没有可分配的预算或利润额度')
    return result


def classify_ad_suggestion(s):
    """Turn sample-based no-action decisions into holds, without hiding missing data."""
    if s['kind']=='ad' and s['action'] in ('bid_up','bid_down','budget') and s['status'] in ('ready','pending'):
        amount=dec(s.get('target'))
        if amount is None or amount<=0:
            s.update(action='check',status='pending',label='无法判断广告调整：缺少有效金额')
    if s['kind']!='ad' or s['action']!='check':
        return s
    stats=s.get('stats',{})
    if s.get('reason') in ('核查广告状态与效果','已归因点击、订单或报表天数未达到竞价调整样本条件') and stats.get('mature'):
        s.update(action='hold',label='暂不调整竞价',status='hold',
                 reason=f"已归因报表{stats.get('days',0)}天、{stats.get('clicks',0)}次点击、{stats.get('orders',0)}单，未达到竞价调整门槛，继续积累样本")
    elif '可承受ACOS待核' in s.get('reason',''):
        s['label']='旧快照需按固定ACOS规则重算'
    elif 'ACOS无法计算' in s.get('reason',''):
        s['label']='无法判断竞价：缺少有效归因销售额'
    elif '试错成本依据待核' in s.get('reason',''):
        s['label']='旧快照需按零单点击规则重算'
    elif '未找到可核实的已有广告对象' in s.get('reason',''):
        s['label']='无法判断广告：未匹配到对象'
    elif '自动广告需匹配到具体匹配方式' in s.get('reason',''):
        s['label']='无法判断竞价：缺少匹配方式数据'
    elif '没有点击或花费' in s.get('reason',''):
        s['label']='投放异常：无点击或花费'
    elif '尚未归因完整' in s.get('reason',''):
        s['label']='暂不能判断竞价：订单归因未完成'
    return s


def resolve_direction_conflicts(suggestions):
    """Different objects may move in different directions; one object cannot."""
    groups={}
    for s in suggestions:
        if s.get('status') not in ('ready','pending'):
            continue
        if s.get('kind')=='price' and s.get('action') in ('price_up','price_down'):
            key=('price',s.get('country'))
        elif s.get('kind')=='ad' and s.get('action') in ('bid_up','bid_down'):
            identity=tuple(str(s.get(k) or '') for k in ('profile_id','campaign_id','ad_group_id','object_type','object_id'))
            if not all(identity):continue
            key=('ad',s.get('country'),*identity)
        else:
            continue
        groups.setdefault(key,[]).append(s)
    conflicts=[g for g in groups.values() if len({s['action'] for s in g})>1]
    replacements={};removed=set()
    for group in conflicts:
        diagnostic=dict(group[0])
        diagnostic.update(action='check',label=ACTION_LABELS['check'],status='pending',target=None,
                          change_rate=None,reason='同一价格或竞价对象同时命中涨降方向，先核查，不输出相反调整',
                          conflicting_suggestions=[dict(s) for s in group])
        replacements[id(group[0])]=diagnostic
        removed.update(id(s) for s in group[1:])
    suggestions[:]=[replacements.get(id(s),s) for s in suggestions if id(s) not in removed]
    return suggestions


def order_country_suggestions(suggestions):
    """Prioritize applicable ad suggestions, not missing ad-only evidence.

    A suggestion is not an executed adjustment or proof of a review interval.
    Price restrictions remain independent and retain their own explanations.
    """
    resolve_direction_conflicts(suggestions)
    for s in suggestions:
        classify_ad_suggestion(s)
    ads=[s for s in suggestions if s['kind']=='ad']
    applicable=any(s['action'] in ('start_ad','restore','bid_up','bid_down','budget') and s['status'] in ('ready','pending') for s in ads)
    for s in suggestions:
        if s['kind']!='price':
            continue
        for key in ('deferred','defer_reason','defer_type'):
            s.pop(key,None)
        s['checks']=[c for c in s.get('checks',[]) if c!='广告状态尚未核清，当前仅列候选价格']
        if applicable and s['action'] in ('price_up','price_down') and s['status'] in ('ready','pending'):
            if '低于P10' in s.get('reason',''):
                s['price_risk_note']='当前售价低于P10，请单独核查价格底线风险'
            s.update(deferred=True,defer_type='ad_priority',
                     defer_reason='该站点已有具体广告建议，优先核验并处理广告；这不代表已经执行调整')
            if s['status']=='ready':
                s['status']='pending'
    return suggestions


def price_conversion_evidence(country, age):
    """Use this station's pre-stockout units/session rate, not a fixed visit quota."""
    pair=country.get('price_comparison') or {}
    current=pair.get('current') or {};history=pair.get('history') or {}
    cs,cq,hs,hq=(dec(v) for v in (current.get('sessions'),current.get('qty'),history.get('sessions'),history.get('qty')))
    result=dict(status='pending',is_trial_rule=True,expected_unit_target=3,
                required_sessions=None,expected_qty=None,conversion_ratio=None,
                enough_visits=False,weak_conversion=False,
                current_days=current.get('days'),current_start=current.get('start'),current_end=current.get('end'),
                history_days=history.get('days'),history_start=history.get('start'),history_end=history.get('end'),
                current_sessions=cs,current_qty=cq,history_sessions=hs,history_qty=hq,
                reason='当前对应窗口或断货前国家历史数据不完整，不能计算动态访问门槛')
    if (current.get('days')!=comparison_days(age) or current.get('stocked') is not True
            or history.get('stocked') is not True or any(v is None for v in (cs,cq,hs,hq))):
        return result
    if cs<0 or cq<0 or hs<=0 or hq<=0:
        result['reason']='国家访问或销量无有效历史基准，不能计算动态访问门槛'
        return result
    if hq<5:
        result.update(status='hold',reason='断货前该国家历史销量不足5件，转化基准样本不足')
        return result
    # Multiply before dividing; equality at 3 units and 70% uses exact products.
    required=(Decimal(3)*hs/hq).to_integral_value(rounding=ROUND_CEILING)
    expected=cs*hq/hs
    enough=cs*hq>=Decimal(3)*hs
    weak=enough and cq*hs<Decimal('.7')*cs*hq
    result.update(required_sessions=int(required),expected_qty=expected,
                  conversion_ratio=cq*hs/(cs*hq) if cs>0 else None,
                  enough_visits=enough,weak_conversion=weak,status='eligible' if weak else 'hold',
                  reason=(f'当前{current["days"]}天访问{cs:g}次，按断货前表现预期销量{expected:g}件；实际{cq:g}件，低于预期70%' if weak else
                          f'当前{current["days"]}天访问{cs:g}次，未达到断货前卖3件所需的{int(required)}次访问，继续观察' if not enough else
                          '当前对应窗口访问已达到动态门槛，实际销量未低于历史预期70%，保持价格'))
    return result


def price_candidate(event, country, listing, ladder, dos=None, ad_pending=False):
    result=suggestion('price','hold','未命中调价条件','hold')
    current=dec(listing.get('price'))
    result.update(current=current,currency=listing.get('currency'),source_date=listing.get('snapshot_date'))
    if event['exit_status']!='tracking' or event['age']<8:
        result['reason']='已退出本轮' if event['exit_status']!='tracking' else '7天自然恢复期保持价格'
        return result
    if current is None or current<=0:
        result.update(action='check',label=ACTION_LABELS['check'],status='pending',reason='当前Listing价格缺失')
        return result
    m=country['recent']; margin=dec(m.get('margin')); qty=dec(m.get('daily'))
    sales_first=sales_repair_first(event)
    p10=dec(ladder.get('p10'))
    floor=p10 is not None and current<p10
    direction=None
    if floor:
        direction='up'; result['reason']='当前价格低于P10，先审核恢复至P10'
    elif sales_first:
        evidence=price_conversion_evidence(country,event['age'])
        result['price_conversion']=evidence
        if evidence['weak_conversion']:
            direction='down'; result['reason']='主窗口日销不足1件，先修复销量；'+evidence['reason']+'，审核降低一档（试算规则）'
        else:
            result.update(status=evidence['status'],reason=evidence['reason'])
            if evidence['status']=='pending':result.update(action='check',label=ACTION_LABELS['check'])
    elif not m.get('complete') or margin is None:
        result.update(status='pending',reason='站点近7天订单毛利率或经营数据不完整')
    elif qty and margin<Decimal('.05'):
        direction='up'; result['reason']='订单毛利率低于5%，核实低价是利润缺口原因后提高一档'
    elif at_least_potential(event['recent']['daily'],event['recent']['margin']) or (event['age']<14 and event['state']=='good'):
        result['reason']='当前恢复较好或角色已达目标，保持价格'
    elif qty is not None and 1<=qty<=5 and Decimal('.05')<=margin<Decimal('.10'):
        direction='up'; result['reason']='日销1至5件，订单毛利率不足10%，审核提高一档修复角色差距'
    elif event['state']=='poor' or (event['age']>=8 and event.get('current_evaluation') and event['current_evaluation']['daily'] is not None and event['current_evaluation']['daily']<1):
        evidence=price_conversion_evidence(country,event['age'])
        result['price_conversion']=evidence
        if margin>=Decimal('.10') and evidence['weak_conversion']:
            direction='down'; result['reason']=evidence['reason']+'；近7天订单毛利率至少10%，审核降低一档（试算规则）'
        else:
            result.update(status='hold' if margin<Decimal('.10') else evidence['status'],
                          reason='近7天订单毛利率不足10%，不满足正常降价利润余量' if margin<Decimal('.10') else evidence['reason'])
            if result['status']=='pending':result.update(action='check',label=ACTION_LABELS['check'])
    if direction:
        result.update(action='price_'+direction,label=ACTION_LABELS['price_'+direction],status='pending')
        price=adjacent_price(current,ladder,direction,'1' if listing.get('currency')=='JPY' else '.01')
        result.update({k:v for k,v in price.items() if k!='reason'})
        if price['target'] is None:
            result.update(status='blocked',reason=price['reason'])
        if direction=='down' and (dos is None or dos<14):
            result.update(status='blocked',reason='库存覆盖不足14天或未知，不能降价拉量')
        last_change=listing.get('last_change_date')
        result['last_change_date']=last_change
        result['checks']=['站点实际经营与Listing可售状态待核','上一轮调价复评结果待核' if last_change else '近期实际调整及复评记录待核','联合预测利润不低于5%待核']
        if sales_first:
            result['checks'].remove('联合预测利润不低于5%待核')
            result['profit_policy']='日销不足1件，先修复销量，暂不设利润门槛'
        if last_change and event.get('as_of'):
            elapsed=(event['as_of']-last_change).days
            if elapsed<7:
                if floor or (not sales_first and margin is not None and margin<Decimal('.05')):
                    result['checks'].append(f'{last_change}刚完成调价，未满7天；本次底线或利润风险须单独人工审核')
                else:
                    result.update(status='blocked',reason=f'{last_change}已完成调价，距今{elapsed}天，未满7天，暂不进行下一轮正常调价')
        if direction=='up':
            result['checks'].append('低售价是利润缺口原因、成本与广告异常待核')
    return result
