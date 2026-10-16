from datetime import date, timedelta
from decimal import Decimal

import pytest


def rules():
    from app.services import return_goods_strategy_rules
    return return_goods_strategy_rules


START = date(2026, 6, 1)


def daily(stocks, qty=2, margin=.12, start=START):
    return [{"day": start + timedelta(days=i), "stock": s, "qty": qty,
            "revenue": qty * 20, "profit": qty * 20 * margin, "sessions": 20}
            for i, s in enumerate(stocks)]


@pytest.mark.parametrize('stocks,longest,interrupted',[
    ([5,0,5],1,False),([5,0,0,5],2,False),([5,0,0,0,5],3,True),
    ([0,5,0,5,0],1,False),([0,None,0],1,False),([0,0,0,0],4,True),
    ([-1,-1,-1],0,False),
])
def test_inventory_interruption_requires_three_consecutive_zero_days(stocks,longest,interrupted):
    rows=daily(stocks);by_day={r['day']:r for r in rows}
    result=rules().recovery_comparison(by_day,{'stockout_date':START},rows[-1]['day'],len(rows))
    assert result['current']['max_zero_stock_days']==longest
    assert ('stock_interrupted' in result['issues']) is interrupted


def test_inventory_missing_date_breaks_streak_and_window_does_not_borrow_prior_days():
    rows=daily([0,0,0]);by_day={r['day']:r for r in rows}
    assert rules().consecutive_zero_stock_days(by_day,rows[-1]['day'],2)==2
    del by_day[rows[1]['day']]
    assert rules().consecutive_zero_stock_days(by_day,rows[-1]['day'],3)==1


def test_short_stock_gap_still_prevents_role_exit_even_if_not_interruption_label():
    rows=daily([20]*30+[0]*3+[5,0,5,5,5,5,5])
    e=rules().build_events(rows)[0]
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert 'stock_interrupted' not in result['comparison']['issues']
    assert result['exit_status']=='tracking'
    assert not result['current_evaluation']['stocked']


def event(days=16, first_bad=True):
    rows = daily([20] * 30 + [0] * 3 + [5] * days)
    if first_bad:
        rows[33]["profit"] = 0
    return rows, rules().build_events(rows)[0]


def test_zero_sales_history_remains_visible_without_inventing_role_or_recovery():
    rows=daily([10]*30,qty=0)+daily([0]*3,qty=0,start=START+timedelta(days=30))+daily([5]*7,start=START+timedelta(days=33))
    e=rules().build_events(rows)[0]
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    history=result['pre_stockout']
    assert history['complete'] and history['stocked']
    assert history['qty']==0 and history['revenue']==0 and history['daily']==0
    assert history['sessions']==600 and history['margin'] is None
    assert result['baseline']['daily'] is None and result['recovery'] is None
    assert '销售额为0' in result['baseline']['evidence']
    assert len(result['pre_stockout_timeline'])==30
    assert all(r['day']<e['stockout_date'] for r in result['pre_stockout_timeline'])


def test_missing_history_day_is_not_displayed_as_zero_sales():
    rows,e=event()
    del rows[15]
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['pre_stockout']['qty'] is None
    assert len(result['pre_stockout']['missing'])==1
    assert result['pre_stockout_timeline'][15]['qty'] is None


@pytest.mark.parametrize("stocks,count", [([0,0,5],0), ([0,0,0,4],0),
    ([0,0,0,5],1), ([0,None,0,0,5],0), ([0,0,1,0,5],0),
    ([0,0,0,5,0,0,5],1), ([0,0,0,5,0,0,0,4,5],2)])
def test_entry(stocks, count):
    assert len(rules().build_events(daily(stocks))) == count


def test_missing_date_breaks_stockout_and_start_is_first_zero():
    rows = daily([0,0,0,5])
    events = rules().build_events(rows)
    assert events[0]["stockout_date"] == START
    assert events[0]["return_date"] == START + timedelta(days=3)
    rows[2]["day"] += timedelta(days=1)
    rows[3]["day"] += timedelta(days=1)
    assert not rules().build_events(rows)


def test_d7_exit_is_frozen_and_ignores_historical_star():
    rows, e = event(20, first_bad=False)
    rows[0]["profit"] = 999
    rows[-1]["profit"] = 0
    result = rules().evaluate_event(rows, e, rows[-1]["day"])
    assert result["exit_status"] == "early"
    assert result["exit_date"] == e["return_date"] + timedelta(days=6)


def test_d8_three_confirmations_earliest_d10():
    rows, e = event()
    for n, count in [(8,1),(9,2),(10,3)]:
        result = rules().evaluate_event(rows, e, e["return_date"]+timedelta(days=n-1))
        assert result["confirmation_days"] == count
        assert (result["exit_status"] == "normal") == (n == 10)
        assert result['current_evaluation']['days']==n


def test_missing_day_cannot_exit_or_count_as_zero():
    rows, e = event(10)
    rows.pop(-2)
    result = rules().evaluate_event(rows, e, rows[-1]["day"])
    assert result["exit_status"] == "tracking"
    assert result["confirmation_days"] == 0
    assert any("缺" in x for x in result["exit_reasons"])


def test_normal_exit_breaks_on_stockout():
    rows, e = event(10)
    rows[-2]["stock"] = 0
    result = rules().evaluate_event(rows, e, rows[-1]["day"])
    assert result["exit_status"] == "tracking"
    assert result["confirmation_days"] == 0


@pytest.mark.parametrize("qty,margin,ok", [(1,.1,True),(5,.1,True),(5,.05,False),(6,.05,True),(.99,.4,False)])
def test_role_boundaries(qty, margin, ok):
    assert rules().at_least_potential(qty, margin) is ok


def test_recovery_80_margin_5_and_unknown_baseline():
    assert rules().recovery_state(8, .8, .05, True, False) == "good"
    assert rules().recovery_state(8, None, .2, True, False) == "unknown"
    assert rules().recovery_state(8, .9, .049, True, False) == "risk"


@pytest.mark.parametrize("current,direction,target", [(20,"down",15),(22,"down",20),
    (22,"up",25),(20,"up",25),(10,"down",None),(35,"up",None),
    (40,"up",None),(40,"down",35),(8,"up",10)])
def test_one_price_tier(current, direction, target):
    ladder = {f"p{x}":x for x in (10,15,20,25,30,35)}
    value = rules().adjacent_price(current, ladder, direction)
    assert value["target"] == target


def test_missing_price_tier_no_jump():
    ladder = {f"p{x}":x for x in (10,15,25,30,35)}
    assert rules().adjacent_price(25, ladder, "down")["target"] is None


def test_ad_inherited_bid_and_rounding():
    assert rules().effective_bid(0, .51) == Decimal("0.51")
    assert rules().effective_bid(None, .51) == Decimal("0.51")
    assert rules().effective_bid(-1, .51) is None
    assert rules().bid_target(.51, -.1, .01) == Decimal("0.46")
    assert rules().bid_target(.51, .05, .01) == Decimal("0.53")


def test_budget_simulation_does_not_double_spend_pool():
    actions = [{"pool":"eu", "amount":8}, {"pool":"eu", "amount":8}]
    assert rules().allocate_budget(actions, {"eu":10}) == [8,2]


def test_unmature_ad_zero_orders_and_shared_object_no_bid():
    ad = dict(current_bid=.5, default_bid=.4, days=2, clicks=30, orders=0,
              cost=20, sales=0, affordable_acos=.2,
              mapping_count=1, mature=False, enabled=True)
    assert rules().ad_candidate(ad, dos=40)["target"] is None
    ad.update(mature=True, days=7, mapping_count=2)
    assert rules().ad_candidate(ad, dos=40)["target"] is None


def test_fixed_acos_does_not_depend_on_legacy_affordability():
    ad = dict(current_bid=.5, days=7, clicks=30, orders=3, cost=22.5, sales=50,
              affordable_acos=.2, mapping_count=1, mature=True, enabled=True)
    result = rules().ad_candidate(ad, dos=40)
    assert result["target"] == Decimal("0.45")
    assert result["action"] == "bid_down"
    ad["affordable_acos"] = None
    result = rules().ad_candidate(ad, dos=40)
    assert result["status"] == "pending"
    assert result["target"] == Decimal("0.45")


@pytest.mark.parametrize('dos',[None,0,5,10])
def test_restore_blocked_by_known_inventory_limit(dos):
    assert rules().ad_candidate(dict(enabled=False,mapping_count=1),dos)['status']=='blocked'


def test_budget_requires_efficiency_and_respects_four_caps():
    budget=dict(efficient=True,limited=True,month=100,week=20,pool_remaining=3,profit_capacity=4,acos=.2,dos=28)
    candidate=rules().budget_candidate(budget)
    assert candidate['target']==3
    budget['limited']=None
    assert rules().budget_candidate(budget)['target'] is None


def test_ready_only_after_every_required_check_passes():
    action=rules().suggestion('price','price_up','提高一档')
    rules().review_checks(action,{'预算':True,'操作记录':None})
    assert action['status']=='pending'
    rules().review_checks(action,{'预算':True,'操作记录':True})
    assert action['status']=='ready'
    rules().review_checks(action,{'库存':False,'操作记录':None})
    assert action['status']=='blocked'


def test_known_recent_price_change_blocks_normal_adjustment():
    e=dict(exit_status='tracking',age=20,as_of=date(2026,9,29),state='poor',recent=dict(daily=.5,margin=.2),
           current_evaluation=dict(daily=.5))
    country=dict(recent=dict(complete=True,margin=.2,daily=.5,qty=3.5,sessions=100),
                 historical=dict(qty=20,sessions=100))
    country['price_comparison']=dict(current=dict(days=20,stocked=True,sales_complete=True,qty=Decimal('3.5'),sessions=100),
                                     history=dict(days=30,stocked=True,sales_complete=True,qty=20,sessions=100))
    listing=dict(price=25,currency='EUR',last_change_date=date(2026,9,25))
    ladder={f'p{x}':x for x in (10,15,20,25,30,35)}
    result=rules().price_candidate(e,country,listing,ladder,30)
    assert result['status']=='blocked'
    assert '7' in result['reason']
    listing['last_change_date']=date(2026,9,22)
    assert rules().price_candidate(e,country,listing,ladder,30)['target']==20
