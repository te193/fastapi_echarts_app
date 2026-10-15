from datetime import date
from decimal import Decimal

import pytest
from app.services import return_goods_strategy_rules as r


@pytest.mark.parametrize('daily,margin,expected',[(0,None,'sales_repair'),(.99,-.2,'sales_repair'),(1,.01,'risk'),(1,None,'profit_unknown')])
def test_main_window_sales_before_profit(daily,margin,expected):
    m=dict(sales_complete=True,daily=Decimal(str(daily)),margin=r.dec(margin))
    c=dict(current=m,issues=[],history={},ratio=Decimal('.9'))
    assert r.comparison_state(8,c,False)==expected
    m['sales_complete']=False
    assert r.comparison_state(8,c,False)=='data_missing'


def test_sales_repair_bid_still_requires_samples_and_inventory():
    ad=dict(mapping_count=1,enabled=True,mature=True,days=7,clicks=20,orders=3,cost=30,sales=20,current_bid=1)
    assert r.ad_candidate(ad,28,sales_first=True)['target']==Decimal('.80')
    assert r.ad_candidate(ad,28)['target']==Decimal('.80')
    ad.update(cost=30,sales=200)
    assert r.ad_candidate(ad,28,sales_first=True)['target']==Decimal('1.10')
    assert r.ad_candidate(ad,6,sales_first=True)['status']=='blocked'
    ad['mature']=False
    assert r.ad_candidate(ad,28,sales_first=True)['target'] is None


def test_budget_bypasses_profit_but_not_pool_cap():
    c=dict(efficient=True,limited=True,month=100,week=20,pool_remaining=3,profit_capacity=None,sales_first=True,acos=.2,dos=28)
    assert r.budget_candidate(c)['target']==3
    c['pool_remaining']=None
    assert r.budget_candidate(c)['target'] is None


def test_low_margin_price_can_fall_one_tier_but_review_still_applies():
    e=dict(exit_status='tracking',age=20,state='sales_repair',as_of=date(2026,10,7),comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5'))))
    country=dict(recent=dict(complete=False,daily=.1,margin=None,qty=1,sessions=100),historical=dict(qty=10,sessions=100))
    country['price_comparison']=dict(current=dict(days=20,stocked=True,sales_complete=True,qty=1,sessions=100),
                                     history=dict(days=30,stocked=True,sales_complete=True,qty=10,sessions=100))
    listing=dict(price=20,currency='EUR')
    ladder={f'p{x}':x for x in (10,15,20,25,30,35)}
    result=r.price_candidate(e,country,listing,ladder,28)
    assert result['target']==15
    assert '联合预测利润不低于5%待核' not in result['checks']
    listing['last_change_date']=date(2026,10,5)
    assert r.price_candidate(e,country,listing,ladder,28)['status']=='blocked'
    listing['price']=10
    assert r.price_candidate(e,country,listing,ladder,28)['target'] is None


def test_small_country_does_not_bypass_main_product_profit():
    assert not r.sales_repair_first(dict(comparison=dict(current=dict(sales_complete=True,daily=2))))


def test_zero_sales_inventory_can_use_marked_reliable_history():
    from etl.return_goods_strategy_update import enrich
    from test_return_goods_strategy_rules import event
    rows,e=event(12)
    for row in rows[33:]:row.update(qty=0,revenue=0,profit=0)
    result=r.evaluate_event(rows,e,rows[-1]['day'])
    _,detail=enrich(result,('test','欧洲','sku'),[],{}, {}, {}, {},rows[-1]['day'])
    assert detail['dos']>0
    assert '历史实际日销' in detail['dos_note']


def test_actual_ad_pipeline_does_not_reapply_profit_block(monkeypatch):
    from etl import return_goods_strategy_update as etl
    monkeypatch.setattr(etl,'aggregate_ad_days',lambda *args:dict(days=7,mature=True,clicks=20,orders=3,cost=30,sales=200))
    event=dict(state='sales_repair',as_of=date(2026,10,7),return_date=date(2026,9,1),timeline=[],comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5'))))
    key=('test','de','sku')
    obj=dict(object_type='keyword',current_bid=1,associated_msku_count=1,currency_code='EUR',snapshot_date=event['as_of'],campaign_state_current='enabled',ad_group_state_current='enabled',object_state_current='enabled')
    ads=dict(by_product={key:[obj]},common_end=event['as_of'],daily={})
    result=etl.ad_for_country(event,key,ads,28,{},{} )[0]
    assert result['action']=='bid_up'
    assert result['target']==Decimal('1.10')
    assert '同站点可承受ACOS与获客成本待核' not in result['checks']
    assert '真实可用预算及批准花费上限待核' in result['checks']


def test_second_snapshot_retains_exit_and_restores_baseline_dates():
    from etl.return_goods_strategy_update import retain_exit
    current={}
    previous=dict(exit_date='2026-10-01',exit_status='normal',baseline=dict(start='2026-08-01',end='2026-08-30',days=30))
    retain_exit(current,previous,date(2026,10,7))
    assert current['baseline']['end']==date(2026,8,30)
    assert current['exit_date']==date(2026,10,1)
    assert previous['baseline']['end']=='2026-08-30'
