from datetime import date, timedelta
from decimal import Decimal


def test_decision_steps_keep_recovery_separate_from_action_candidates():
    from return_goods_data.presentation import filter_payload
    def row(key,state,actions=(),age=20,status='tracking'):
        return dict(event_id=key,msku=key,seller_name_new='s',country_category='欧洲站',age=age,
                    exit_status=status,state=state,ready_count=0,pending_count=1,candidate_actions=list(actions),
                    action_types=list(actions),priority=0)
    rows=[row('risk','risk',['price_up']),row('data','unknown',['price_up']),row('ads','poor',['bid_down','price_down']),
          row('price','poor',['price_down']),row('hold','good'),row('blocked','poor'),
          row('observing','risk',age=7),row('exited','poor',['bid_up'],status='early')]
    result=filter_payload(rows,{})
    counts={r['key']:r['count'] for r in result['intervention']}
    assert {k:v for k,v in counts.items() if v}==dict(good=1,poor=3,ad_unknown=3,bid_down=1,price_up_review=1,price_down_review=2,risk=1,unknown=1)
    assert sum(counts[k] for k in ('good','improving','poor','risk','unknown'))==result['distribution']['counts']['intervene']
    for key,count in counts.items():
        selected=filter_payload(rows,{},focus=key,all_rows=True)
        assert selected['total']==count
        assert all(key in r['decision_branches'] for r in selected['items'])
    # Missing recovery history remains unknown even if a P10 floor candidate exists.
    unknown=filter_payload(rows,{},focus='unknown')['items'][0]
    assert unknown['intervention_focus']=='unknown' and 'poor' not in unknown['decision_branches']
    assert 'price_up' not in unknown['decision_branches']
    for state in ('good','improving','unknown'):
        item=row('not_forced',state,['bid_up','price_up'])
        item['ad_check']=True
        assert filter_payload([item],{})['items'][0]['decision_branches']==[state]


def test_saved_and_new_suggestions_defer_price_per_country_until_ads_reviewed():
    from return_goods_data.presentation import display_ordered_suggestions
    from return_goods_data.rules import order_country_suggestions
    def price():
        return dict(kind='price',action='price_up',label='价格升一档',status='pending',target=20,checks=['利润待核'],reason='利润不足')
    for action in ('restore','bid_up','bid_down','budget'):
        countries=[dict(country='德国',suggestions=[price(),dict(kind='ad',action=action,label='广告',status='pending',reason='广告待核',target=.5)]),
                   dict(country='法国',suggestions=[price(),dict(kind='ad',action='hold',label='保持',status='hold',reason='正常')])]
        result=display_ordered_suggestions({},countries)
        assert countries[0]['suggestions'][0]['action']=='price_up'
        assert countries[0]['suggestions'][0]['target']==20
        assert countries[0]['suggestions'][0]['deferred'] is True
        assert countries[1]['suggestions'][0]['action']=='price_up'
        assert result['candidate_actions'].count('price_up')==1
        assert result['pending_count']==3
        assert not result['price_wait_ad'] and result['price_can_review']
        assert order_country_suggestions(countries[0]['suggestions'])==countries[0]['suggestions']


def test_ad_sample_decision_is_a_hold_but_missing_attributed_sales_remains_unknown():
    from return_goods_data.presentation import display_ordered_suggestions,filter_payload
    def row(key,reason):
        price=dict(kind='price',action='price_up',label='价格升一档',status='pending',target=20,checks=[],reason='利润不足')
        ad=dict(kind='ad',action='check',label='核查',status='pending',reason=reason,
                stats=dict(mature=True,days=7,clicks=10,orders=1))
        return display_ordered_suggestions(dict(event_id=key,msku=key,seller_name_new='s',country_category='欧洲站',
            age=20,state='risk',exit_status='tracking',priority=0,countries=[dict(suggestions=[price,ad])]))
    hold=row('hold','核查广告状态与效果')
    missing=row('missing','已有广告订单但归因销售额不大于0，ACOS无法计算')
    assert hold['ad_result']=='hold'
    assert hold['countries'][0]['suggestions'][1]['action']=='hold'
    assert not hold['countries'][0]['suggestions'][0].get('deferred')
    assert missing['ad_result']=='unknown'
    assert not missing['countries'][0]['suggestions'][0].get('deferred')
    assert '缺少有效归因销售额' in missing['countries'][0]['suggestions'][1]['label']
    payload=filter_payload([hold,missing],{})
    counts={c['key']:c['count'] for c in payload['intervention']}
    assert counts['ad_hold']==counts['ad_unknown']==1
    assert counts['price_up_review']==2 and counts['price_wait_ad']==0


def test_no_sales_cards_partition_full_return_history_and_recent_window():
    from return_goods_data.presentation import display_window_text,filter_payload
    def row(key,timeline):
        return display_window_text(dict(event_id=key,msku=key,seller_name_new='s',country_category='欧洲站',
            age=40,recent_days=30,exit_status='tracking',state='no_sales',ready_count=0,pending_count=0,
            action_types=[],priority=0),timeline)
    rows=[row('never',[{'qty':0}]*40),row('previous',[{'qty':1}]+[{'qty':0}]*39),
          row('incomplete',[{'qty':0}]*39)]
    result=filter_payload(rows,{})
    counts={r['key']:r['count'] for r in result['intervention']}
    assert 'no_sales' not in counts
    assert counts['no_sales_since_return']==1
    assert counts['no_sales_window']==2
    assert result['distribution']['states']['intervene']['no_sales']==3
    never=filter_payload(rows,{},focus='no_sales_since_return',all_rows=True)
    recent=filter_payload(rows,{},focus='no_sales_window',all_rows=True)
    assert {r['msku'] for r in never['items']}=={'never'}
    assert {r['msku'] for r in recent['items']}=={'previous','incomplete'}
    assert never['total']+recent['total']==result['total']


def test_grid_can_load_all_matching_rows_without_changing_default_pagination():
    from return_goods_data.presentation import filter_payload
    rows=[dict(event_id=str(i),msku=str(i),seller_name_new='s',country_category='欧洲站',age=20,
               exit_status='tracking',state='poor',ready_count=0,pending_count=0,action_types=[],priority=0) for i in range(75)]
    assert len(filter_payload(rows,{})['items'])==50
    assert len(filter_payload(rows,{},all_rows=True)['items'])==75


def test_stage_and_day_distribution_uses_all_rows_and_separates_exits():
    from return_goods_data.presentation import filter_payload
    def row(key,age,status='tracking',store='s'):
        return dict(event_id=key,msku=key,seller_name_new=store,country_category='欧洲站',age=age,
                    exit_status=status,state='observe' if age<=7 else 'poor',ready_count=0,pending_count=0,
                    action_types=['hold'],priority=0)
    rows=[row(str(age),age) for age in (1,7,8,14,15,21,22,30,31,60,61,180)]
    rows += [row('early',90,'early'),row('normal',120,'normal'),row('other',7,store='other')]
    result=filter_payload(rows,{},seller_name_new='s',page_size=10)
    assert result['total']==12 and len(result['items'])==10
    d=result['distribution']
    assert d['counts']==dict(observe=2,intervene=10,early=1,normal=1)
    assert d['total']==14
    assert sum(r['count'] for r in d['days'])==12
    assert [r['count'] for r in d['days'] if r['stage']=='intervene']==[2]*5
    assert d['states']['observe']['observe']==2
    selected=filter_payload(rows,{},seller_name_new='s',stage='intervene',age_band='d8_14')
    assert {r['age'] for r in selected['items']}=={8,14}
    assert selected['distribution']==d
    early=filter_payload(rows,{},seller_name_new='s',exit_status='early',stage='early')
    assert early['total']==1 and early['items'][0]['msku']=='early'
    assert filter_payload([], {})['distribution']['counts']==dict(observe=0,intervene=0,early=0,normal=0)


def test_completed_price_change_requires_same_currency_current_price_and_historical_date():
    from return_goods_data.enrichment import attach_price_changes
    cutoff=date(2026,9,29)
    listing=dict(price=20,org_currency_icon='欧元',snapshot_date=cutoff)
    row=dict(source_id=1,adjust_date=date(2026,9,25),finish_time='2026-09-25 12:00:00',
             seller_name_new='x',country='德国',msku='a',currency='€',price_before=25,price_after=20)
    listings={('x','de','a'):dict(listing)}
    attach_price_changes(listings,[row],cutoff)
    assert listings[('x','de','a')]['last_change_date']==date(2026,9,25)
    for invalid in (dict(row,currency='USD'),dict(row,currency='$'),dict(row,price_after=21),
                    dict(row,adjust_date=date(2026,9,30)),dict(row,price_before=20)):
        listings={('x','de','a'):dict(listing)}
        attach_price_changes(listings,[invalid],cutoff)
        assert 'last_change_date' not in listings[('x','de','a')]


def test_latest_snapshot_never_uses_future_and_conflicts_not_merged():
    from return_goods_data.enrichment import index_snapshot
    rows = [dict(seller_name_new='x',country='德国',seller_sku='a',snapshot_date=date(2026,9,29),price=20),
            dict(seller_name_new='x',country='德国',seller_sku='a',snapshot_date=date(2026,9,30),price=30)]
    values = index_snapshot(rows,date(2026,9,29))
    assert values[('x','de','a')]['price']==20
    rows.append(dict(rows[0],price=21))
    assert index_snapshot(rows,date(2026,9,29))[('x','de','a')]['conflict']


def test_list_summary_deduplicates_and_filters_exit_separately():
    from return_goods_data.presentation import filter_payload
    rows=[dict(event_id='a',exit_status='tracking',seller_name_new='s',country_category='欧洲站',
               msku='A',state='poor',ready_count=0,pending_count=2,action_types=['price_down'],priority=1),
          dict(event_id='b',exit_status='early',seller_name_new='s',country_category='欧洲站',
               msku='B',state='good',ready_count=0,pending_count=0,action_types=[],priority=4)]
    result=filter_payload(rows,{},exit_status='tracking')
    assert result['total']==1
    assert result['summary']==dict(tracking=1,ready=0,pending=1,exited=1)
    assert filter_payload(rows,{},exit_status='all',action='price_down')['total']==1


def test_decimal_serialization_keeps_missing_null():
    from return_goods_data.presentation import json_default
    assert json_default(Decimal('0.05'))==.05
    assert json_default(date(2026,9,29))=='2026-09-29'


def test_only_returned_window_used_for_ad_performance():
    from return_goods_data.enrichment import aggregate_ad_days
    rows=[dict(day=date(2026,9,1),clicks=100,cost=100,orders=5,sales=100),
          dict(day=date(2026,9,21),clicks=2,cost=1,orders=0,sales=0)]
    result=aggregate_ad_days(rows,date(2026,9,20),date(2026,9,29))
    assert result['clicks']==2
    assert result['days']==1
    assert result['mature_end']==date(2026,9,22)


def test_ad_source_string_dates_are_normalized():
    from return_goods_data.enrichment import aggregate_ad_days
    result=aggregate_ad_days([dict(day='2026-09-21',clicks=2,cost=1,orders=0,sales=0)],
                             date(2026,9,20),'2026-09-29')
    assert result['clicks']==2


def test_missing_orders_do_not_become_mature_zero_orders():
    from return_goods_data.enrichment import aggregate_ad_days
    result=aggregate_ad_days([dict(day='2026-09-21',clicks=25,cost=20,orders=None,sales=0)],
                             date(2026,9,20),date(2026,9,29))
    assert result['orders'] is None
    assert result['mature'] is False


def test_ad_window_excludes_stockout_days():
    from return_goods_data.enrichment import aggregate_ad_days
    result=aggregate_ad_days([dict(day='2026-09-21',clicks=25,cost=20,orders=0,sales=0)],
                             date(2026,9,20),date(2026,9,29),{date(2026,9,21):0})
    assert result['clicks']==0
    assert result['mature'] is False


def test_optional_source_failure_is_not_empty_ads():
    from return_goods_data.enrichment import optional_read
    warnings=[]
    def fail():
        raise RuntimeError('private connection details')
    assert optional_read(fail,'广告对象',warnings)==[]
    assert warnings==['广告对象读取失败，相关建议待核']


def test_exit_history_is_frozen_without_reading_future():
    from return_goods_data.enrichment import retain_exit
    current=dict(exit_status='tracking',exit_date=None,exit_reasons=['未达标'],confirmation_days=0)
    previous=dict(exit_status='early',exit_date='2026-09-20',exit_reasons=['每日稳定'],confirmation_days=0,exit_evidence={})
    retain_exit(current,previous,date(2026,9,19))
    assert current['exit_status']=='tracking'
    retain_exit(current,previous,date(2026,9,29))
    assert current['exit_status']=='early'
    assert current['exit_date']==date(2026,9,20)
    current['exit_date']=date(2026,9,18)
    retain_exit(current,previous,date(2026,9,29))
    assert current['exit_date']==date(2026,9,20)


def test_p10_floor_checked_even_when_recovery_good():
    from return_goods_data.enrichment import enrich
    from return_goods_data.rules import evaluate_event,build_events
    from test_return_goods_strategy_rules import daily
    rows=daily([20]*30+[0]*3+[5]*8)
    rows[33]['profit']=0
    cutoff=rows[-1]['day']; event=evaluate_event(rows,build_events(rows)[0],cutoff)
    assert event['state']=='good'
    key=('x','de','a')
    listing={key:dict(price=8,org_currency_icon='EUR',snapshot_date=cutoff)}
    ladders={key:dict(currency='EUR',snapshot_date=cutoff,**{f'margin_price_{x}':x for x in (10,15,20,25,30,35)})}
    countries=[dict(r,country='德国') for r in rows]
    summary,detail=enrich(event,('x','欧洲站','a'),countries,listing,ladders,{}, {},cutoff)
    price=detail['countries'][0]['suggestions'][0]
    assert price['action']=='price_up' and price['target']==10
    assert price['deferred'] is True
    assert 'P10' in price['price_risk_note']


def test_automatic_targets_keep_own_bid_and_group_default():
    from return_goods_data.enrichment import expand_auto_targets
    group=dict(object_type='ad_group',profile_id=1,campaign_id=2,ad_group_id=3,current_bid=.5,
               default_bid_current=.5,msku='x',associated_msku_count=1)
    target=dict(profile_id=1,campaign_id=2,ad_group_id=3,target_id=9,bid=None,state='enabled',
                expression='[{"type":"queryHighRelMatches"}]')
    obj=expand_auto_targets([group],[target])[0]
    assert obj['object_type']=='auto_target'
    assert obj['object_id']==9
    assert obj['current_bid'] is None
    assert obj['default_bid_current']==.5
    assert expand_auto_targets([group],[])[0]['object_type']=='ad_group'


def test_jpy_zero_order_candidate_uses_whole_yen(monkeypatch):
    from return_goods_data.enrichment import ad_for_country
    obj=dict(object_type='keyword',profile_id=1,campaign_id=2,ad_group_id=3,object_id=4,
             current_bid=51,associated_msku_count=1,currency_code='JPY',snapshot_date=date(2026,9,29))
    ads=dict(by_product={('s','jp','m'):[obj]},common_end=date(2026,9,29),
             daily={('1','2','3','4'):[dict(day=date(2026,9,9)+timedelta(days=i),
                 clicks=25 if i==0 else 0,cost=100 if i==0 else 0,orders=0,sales=0) for i in range(14)]})
    event=dict(return_date=date(2026,9,1),as_of=date(2026,9,29),state='poor',
               timeline=[dict(day=date(2026,9,9)+timedelta(days=i),stock=10) for i in range(14)])
    recent={}
    assert ad_for_country(event,('s','jp','m'),ads,30,{},recent)[0]['target']==46
    obj['currency_code']=None
    assert ad_for_country(event,('s','jp','m'),ads,30,{},recent)[0]['target'] is None
