from datetime import date
from decimal import Decimal

import pytest

from app.services import return_goods_strategy_rules as r
from etl.return_goods_strategy_update import ad_for_country


def ad(clicks=20, **changes):
    result = dict(mapping_count=1, enabled=True, mature=True, days=1,
                  clicks=clicks, orders=0, sales=0, cost=1, current_bid=1,
                  currency='EUR', zero_order_coverage_verified=True)
    result.update(changes)
    return result


@pytest.mark.parametrize('clicks,target', [(0, None), (19, None), (20, '.90'),
                                         (39, '.90'), (40, '.80'), (100, '.80')])
@pytest.mark.parametrize('sales_first', [False, True])
def test_zero_order_click_boundaries_are_same_for_all_daily_sales(clicks, target, sales_first):
    result = r.ad_candidate(ad(clicks), 28, sales_first)
    assert result['target'] == (Decimal(target) if target else None)
    if clicks:
        assert result['zero_order_clicks']['clicks'] == clicks
        assert result['zero_order_clicks']['is_trial_rule'] is True
    if 0 < clicks < 20:
        assert result['action'] == 'hold'


@pytest.mark.parametrize('changes', [dict(mature=False), dict(mapping_count=2),
    dict(current_bid=None), dict(clicks=None), dict(orders=None), dict(cost=-1),
    dict(zero_order_coverage_verified=False), dict(sales=1)])
def test_missing_or_conflicting_evidence_cannot_be_zero_order_action(changes):
    assert r.ad_candidate(ad(**changes), 28)['target'] is None


def test_price_profit_budget_and_cost_do_not_set_zero_order_bid_band():
    for cost in (0, Decimal('.01'), 10000):
        result = r.ad_candidate(ad(40, cost=cost, trial_reference={},
            order_economics={}, budget_comparison=dict(verified=True, ratio=0)), 28)
        assert result['target'] == Decimal('.80')
        assert 'zero_order_trial' not in result and 'budget_comparison' not in result


def test_orders_use_acos_instead_of_zero_order_click_band():
    result = r.ad_candidate(ad(40, days=7, orders=3, cost=15, sales=100), 28)
    assert result['action'] == 'bid_up'
    assert result['target'] == Decimal('1.10')
    assert 'zero_order_clicks' not in result


def test_default_bid_and_rounding():
    assert r.ad_candidate(ad(20, current_bid=0, default_bid=1), 28)['target'] == Decimal('.90')
    result = r.ad_candidate(ad(40, current_bid='.01'), 28)
    assert result['target'] is None and result['action'] == 'check'


def test_pipeline_uses_individual_target_clicks_and_needs_no_price_or_cost_reference(monkeypatch):
    from etl import return_goods_strategy_update as etl
    monkeypatch.setattr(etl, 'aggregate_ad_days', lambda rows, *args: rows[0])
    stamp = date(2026, 10, 10)
    event = dict(return_date=stamp, as_of=stamp, state='sales_repair', timeline=[],
                 comparison=dict(current=dict(sales_complete=True, daily=Decimal('.5'))))
    key = ('s', 'de', 'sku')
    template = dict(profile_id='p', campaign_id='c', ad_group_id='g',
                    current_bid=1, associated_msku_count=1, currency_code='EUR', snapshot_date=stamp)
    objects = [dict(template, object_type='auto_target', object_id=str(i)) for i in (1, 2)]
    stats = [ad(20), ad(40)]
    ads = dict(by_product={key: objects + [dict(objects[0])]}, common_end=stamp,
               daily={('auto', 'p', 'c', 'g', str(i + 1)): [s] for i, s in enumerate(stats)})
    output = ad_for_country(event, key, ads, 28, {}, {})
    assert len(output) == 2
    assert {s['object_id']: s['target'] for s in output} == {'1': Decimal('.90'), '2': Decimal('.80')}
    assert not any('Listing' in c or '试错' in c for s in output for c in s['checks'])


def test_incomplete_coverage_is_pending_even_below_twenty_clicks():
    result = r.ad_candidate(ad(19, zero_order_coverage_verified=False), 28)
    assert result['action'] == 'check' and result['status'] == 'pending'
