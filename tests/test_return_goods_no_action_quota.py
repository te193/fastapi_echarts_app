from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from app.services import return_goods_strategy_rules as r


@pytest.mark.parametrize('acos,dos,action,target',[(Decimal('.15'),28,'bid_up',Decimal('1.10')),
                                                (Decimal('.15'),10,'bid_up',Decimal('1.03')),
                                                (Decimal('.60'),28,'bid_down',Decimal('.80'))])
def test_all_four_eligible_targets_survive_without_country_quota(monkeypatch,acos,dos,action,target):
    from etl import return_goods_strategy_update as etl
    monkeypatch.setattr(etl,'aggregate_ad_days',lambda *a:
                        dict(mature=True,days=7,clicks=20,orders=3,cost=acos*100,sales=100))
    day=date(2026,10,12);key=('s','de','sku')
    event=dict(state='sales_repair',as_of=day,return_date=date(2026,9,1),timeline=[],
               comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5'))))
    objects=[dict(object_type='auto_target',profile_id='p',campaign_id='c',ad_group_id='g',
                  object_id=str(i),associated_msku_count=1,current_bid=1,currency_code='EUR',snapshot_date=day)
             for i in range(4)]
    result=etl.ad_for_country(event,key,dict(by_product={key:objects},daily={},common_end=day),dos,{},{} )
    assert len(result)==4
    assert all(s['action']==action and s['target']==target and s['status']=='pending' for s in result)


def bid(object_id,action,**changes):
    value=dict(kind='ad',action=action,label='调整竞价',status='pending',target=1,checks=[],reason='样本达标',
               country='de',profile_id='p',campaign_id='c',ad_group_id='g',object_type='auto_target',object_id=object_id)
    value.update(changes)
    return value


def price(country,action):
    return dict(kind='price',action=action,label='调价',status='pending',target=20,checks=[],reason='命中',country=country)


def test_opposite_bid_directions_on_same_target_collapse_to_one_diagnostic():
    values=[bid('1','bid_up'),bid('1','bid_down')]
    result=r.order_country_suggestions(values)
    assert len(result)==1 and result[0]['action']=='check' and result[0]['target'] is None
    assert {s['action'] for s in result[0]['conflicting_suggestions']}=={'bid_up','bid_down'}
    before=deepcopy(result)
    assert r.order_country_suggestions(result)==before


def test_different_targets_and_countries_can_move_in_opposite_directions():
    ads=[bid('1','bid_up'),bid('2','bid_down')]
    assert [s['action'] for s in r.order_country_suggestions(ads)]==['bid_up','bid_down']
    prices=[price('de','price_up'),price('fr','price_down')]
    assert [s['action'] for s in r.order_country_suggestions(prices)]==['price_up','price_down']


def test_same_price_directions_conflict_but_blocked_ad_is_not_an_active_conflict():
    result=r.order_country_suggestions([price('de','price_up'),price('de','price_down')])
    assert len(result)==1 and result[0]['action']=='check' and result[0]['target'] is None
    ads=[bid('1','bid_up'),bid('1','bid_down',status='blocked')]
    assert ads[0]['action']=='bid_up'
    r.order_country_suggestions(ads)
    assert ads[0]['action']=='bid_up' and ads[0]['status']=='pending'


def test_removing_quota_does_not_erase_inventory_and_amount_restrictions():
    ad=dict(mapping_count=1,mature=True,days=7,clicks=20,orders=3,cost=15,sales=100,current_bid=1)
    assert r.ad_candidate(ad,6,True)['status']=='blocked'
    assert r.ad_candidate(dict(ad,current_bid=None),28,True)['target'] is None


def test_budget_pool_allocation_remains_capped_when_action_count_is_unlimited():
    requests=[dict(pool='same',amount=4) for _ in range(4)]
    assert r.allocate_budget(requests,dict(same=10))==[4,4,2,0]
