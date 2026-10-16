from datetime import date
from decimal import Decimal

import pytest
from return_goods_data import rules as r


def ad(acos, **changes):
    value=dict(mapping_count=1,enabled=True,mature=True,days=7,clicks=20,
               orders=3,cost=Decimal(str(acos))*100,sales=100,current_bid=1,
               affordable_acos=None)
    value.update(changes)
    return value


@pytest.mark.parametrize('acos,sales_first,action,target',[
    (0,False,'bid_up','1.10'),(.1,False,'bid_up','1.10'),
    (.199999,False,'bid_up','1.10'),(.2,False,'bid_up','1.10'),
    (.200001,False,'hold',None),(.200001,True,'bid_up','1.03'),
    (.3,True,'bid_up','1.03'),(.300001,True,'hold',None),
    (.4,False,'hold',None),(.400001,False,'bid_down','.90'),
    (.5,True,'bid_down','.90'),(.500001,True,'bid_down','.80'),
    (1.5,True,'bid_down','.80'),
])
def test_every_band_boundary_and_low_sales_override(acos,sales_first,action,target):
    result=r.ad_candidate(ad(acos),28,sales_first)
    assert result['action']==action
    assert result['target']==(Decimal(target) if target else None)
    assert result['acos_target']==Decimal('.20') and result['acos_max']==Decimal('.50')
    assert result['status']=='hold' if action=='hold' else result['status']=='pending'


@pytest.mark.parametrize('dos,acos,sales_first,action,target',[
    (6,.15,True,'check',None),(7,.15,False,'bid_up','1.03'),
    (13,.2,True,'bid_up','1.03'),(14,.2,False,'bid_up','1.10'),
    (13,.25,True,'check',None),(14,.25,True,'bid_up','1.03'),
    (None,.6,True,'bid_down','.80'),
])
def test_inventory_caps_increases_but_not_reliable_stoploss(dos,acos,sales_first,action,target):
    result=r.ad_candidate(ad(acos),dos,sales_first)
    assert result['action']==action
    assert result['target']==(Decimal(target) if target else None)
    if action=='check':assert result['status']=='blocked'


@pytest.mark.parametrize('changes',[
    {'mature':False},{'mapping_count':2},{'days':6},{'orders':2},
    {'clicks':19},{'cost':None},{'sales':None},{'cost':-1},
])
def test_low_acos_does_not_bypass_data_and_sample_gates(changes):
    assert r.ad_candidate(ad(.1,**changes),28,True)['target'] is None


def test_orders_with_no_sales_not_low_acos_and_zero_orders_use_separate_gate():
    result=r.ad_candidate(ad(.1,sales=0),28,True)
    assert result['action']=='check' and result['acos'] is None
    zero=ad(.1,orders=0,sales=0,cost=10)
    assert r.ad_candidate(zero,28,True)['target']==Decimal('.90')
    zero['clicks']=40
    assert r.ad_candidate(zero,28,True)['target']==Decimal('.80')
    zero['cost']=Decimal('5.999')
    assert r.ad_candidate(zero,28,True)['target']==Decimal('.80')


def test_paused_high_acos_not_restored_and_legacy_threshold_ignored():
    assert r.ad_candidate(ad(.6,enabled=False),28,True)['status']=='blocked'
    assert r.ad_candidate(ad(.2,affordable_acos=.001),28)['target']==Decimal('1.10')
    assert r.ad_candidate(ad(.6,affordable_acos=2),28,True)['target']==Decimal('.80')


@pytest.mark.parametrize('acos,dos,allowed',[(.2,14,True),(.200001,28,False),(.15,13,False),(None,28,False)])
def test_budget_needs_target_acos_and_two_weeks_stock(acos,dos,allowed):
    context=dict(efficient=True,limited=True,month=100,week=20,pool_remaining=3,
                 profit_capacity=None,sales_first=True,acos=acos,dos=dos)
    result=r.budget_candidate(context)
    assert (result['target']==3)==allowed


def test_effective_bid_rounding_preserves_actual_increase():
    result=r.ad_candidate(ad(.15,current_bid=None,default_bid=Decimal('.51')),28)
    assert result['target']==Decimal('.56')
    assert result['target']/result['current']-1<=Decimal('.10')


@pytest.mark.parametrize('acos,sales_first,limited,expected,target',[
    (.15,False,False,'bid_up','1.10'),(.25,True,False,'bid_up','1.03'),
    (.6,True,False,'bid_down','.80'),(.15,True,True,'budget','3'),
])
def test_real_object_pipeline_preserves_fixed_band_and_budget_gate(monkeypatch,acos,sales_first,limited,expected,target):
    from return_goods_data import enrichment as etl
    monkeypatch.setattr(etl,'aggregate_ad_days',lambda *args:
                        dict(days=7,mature=True,clicks=20,orders=3,cost=Decimal(str(acos))*100,sales=100))
    event=dict(state='sales_repair' if sales_first else 'poor',as_of=date(2026,10,10),
               return_date=date(2026,9,1),timeline=[],
               comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5') if sales_first else 2)))
    key=('test','de','sku')
    obj=dict(object_type='keyword',current_bid=1,associated_msku_count=1,currency_code='EUR',
             snapshot_date=event['as_of'],campaign_state_current='enabled',
             ad_group_state_current='enabled',object_state_current='enabled')
    ads=dict(by_product={key:[obj]},common_end=event['as_of'],daily={})
    budget=dict(budget_limited_verified=limited,monthly_ad_budget_original=100,
                weekly_ad_budget_original=20,verified_pool_remaining=3)
    result=etl.ad_for_country(event,key,ads,28,budget,{})[0]
    assert result['action']==expected and result['target']==Decimal(target)
    assert result['acos']==Decimal(str(acos))
    assert not any('可承受ACOS' in check for check in result['checks'])
    assert result['status']=='pending'
