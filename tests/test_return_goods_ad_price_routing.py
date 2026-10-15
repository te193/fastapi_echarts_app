from copy import deepcopy

import pytest

from app.services.return_goods_strategy_rules import order_country_suggestions
from app.services.return_goods_strategy_data import display_ordered_suggestions


def price(status='pending'):
    return dict(kind='price',action='price_down',label='价格降一档',status=status,
                reason='转化偏弱',target=10,checks=[])


@pytest.mark.parametrize('reason', ['订单归因未完成','缺少匹配方式','缺少可承受ACOS','无点击或花费'])
def test_ad_only_missing_data_does_not_block_price(reason):
    p=price();p.update(deferred=True,defer_reason='旧拦截')
    p['checks']=['广告状态尚未核清，当前仅列候选价格','库存待核']
    ad=dict(kind='ad',action='check',label='核查',status='pending',reason=reason)
    row=display_ordered_suggestions(dict(state='poor',countries=[dict(country='德国',suggestions=[p,ad])]))
    assert not p.get('deferred')
    assert p['checks']==['库存待核']
    assert row['ad_result']=='unknown'
    assert row['price_review_actions']==['price_down']


@pytest.mark.parametrize('action', ['bid_up','bid_down','budget'])
def test_missing_amount_is_diagnostic_not_applicable_action(action):
    p=price()
    ad=dict(kind='ad',action=action,label='调整',status='pending',reason='金额缺失',target=None)
    row=display_ordered_suggestions(dict(state='poor',countries=[dict(country='德国',suggestions=[p,ad])]))
    assert ad['action']=='check'
    assert row['ad_result']=='unknown'
    assert not p.get('deferred')
    assert action not in row['candidate_actions']


@pytest.mark.parametrize('action,target', [('restore',None),('start_ad',None),('bid_up',.55),('bid_down',.45),('budget',20)])
def test_concrete_ad_priority_is_not_claimed_as_executed_review(action,target):
    p=price()
    ad=dict(kind='ad',action=action,label='广告',status='pending',reason='满足候选条件',target=target)
    order_country_suggestions([p,ad])
    assert p['deferred']
    assert p['defer_type']=='ad_priority'
    assert '复评' not in p['defer_reason']
    before=deepcopy(p)
    order_country_suggestions([p,ad])
    assert p==before


def test_blocked_price_keeps_own_cooldown_reason_even_with_ad_priority():
    p=price('blocked');p['reason']='调价未满7天'
    ad=dict(kind='ad',action='restore',label='恢复',status='pending',reason='暂停')
    order_country_suggestions([p,ad])
    assert not p.get('deferred')
    assert p['reason']=='调价未满7天'


def test_blocked_ad_does_not_erase_price_limits():
    p=price('blocked');p['reason']='库存不足14天'
    ad=dict(kind='ad',action='bid_up',label='提高',status='blocked',reason='预算不通过',target=.5)
    order_country_suggestions([p,ad])
    assert not p.get('deferred')
    assert p['status']=='blocked'
