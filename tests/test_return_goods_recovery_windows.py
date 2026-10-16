from datetime import timedelta
from decimal import Decimal
import pytest
from test_return_goods_strategy_rules import daily,START,event,rules


@pytest.mark.parametrize('problem',['stockout','missing_stock','missing_qty'])
def test_price_floor_cannot_bypass_inventory_and_sales_data_guard(problem):
    from etl.return_goods_strategy_update import enrich,business_key
    rows,e=event(10)
    rows[-1][{'stockout':'stock','missing_stock':'stock','missing_qty':'qty'}[problem]]=0 if problem=='stockout' else None
    if problem=='stockout':
        for row in rows[-3:]:row['stock']=0
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    for row in rows:row['country']='德国'
    key=('test','欧洲','sku');country_key=business_key('test','德国','sku')
    listing={country_key:dict(price=5,org_currency_icon='EUR')}
    ladder={country_key:{f'margin_price_{x}':x for x in (10,15,20,25,30,35)}}
    _,detail=enrich(result,key,rows,listing,ladder,{}, {},rows[-1]['day'])
    suggestions=detail['countries'][0]['suggestions']
    assert all(s['action'] in ('hold','check') for s in suggestions)
    assert any('P10' in s['reason'] for s in suggestions)


@pytest.mark.parametrize('age,window',[(1,1),(6,6),(7,7),(12,12),(21,21),(22,21),(29,21),(30,30),(60,30)])
def test_matched_windows(age,window):
    rows,e=event(age)
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    c=result['comparison']
    assert c['days']==window and c['history']['days']==window
    assert c['current']['start']==rows[-1]['day']-timedelta(days=window-1)
    assert c['history']['end']<e['stockout_date']


def test_history_sales_without_profit_still_comparable():
    rows,e=event(12)
    for row in rows[:30]:row['profit']=None
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['baseline']['daily'] is None
    assert result['comparison']['history']['daily']==2
    assert result['recovery']==1 and result['state']=='good'


@pytest.mark.parametrize('change,state',[('missing_qty','data_missing'),('missing_stock','stock_missing'),
    ('stockout','stock_interrupted'),('missing_profit','profit_unknown'),('zero_sales','no_sales')])
def test_missing_zero_and_stock_are_distinct(change,state):
    rows,e=event(12)
    if change=='missing_qty':rows[-1]['qty']=None
    if change=='missing_stock':rows[-1]['stock']=None
    if change=='stockout':
        for row in rows[-3:]:row['stock']=0
    if change=='missing_profit':rows[-1]['profit']=None
    if change=='zero_sales':
        for row in rows[33:]:row.update(qty=0,revenue=0,profit=0)
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['state']==state
    if change=='missing_profit':assert result['recovery']==1 and result['comparison']['current']['daily']==2
    if change=='zero_sales':assert result['recovery']==0


def test_zero_history_not_missing_and_current_can_exit():
    rows,e=event(12,False)
    for row in rows[:30]:row.update(qty=0,revenue=0,profit=0)
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['state']=='history_zero' and result['recovery'] is None
    assert result['exit_status']=='early'


def test_no_matching_history_but_current_sales_and_margin_visible():
    rows,e=event(12)
    for row in rows[:30]:row['stock']=None
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['state']=='history_missing'
    assert result['comparison']['current']['daily']==2
    assert result['comparison']['current']['margin'] is not None


def test_long_period_recent_decline_is_warning_not_main_failure():
    rows,e=event(60)
    for row in rows[-7:]:row.update(qty=1,revenue=20,profit=2.4)
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['comparison']['current']['daily']==Decimal(53)/30
    assert result['state']=='good'
    assert result['trend7']['daily_change']==Decimal('-.5')
    assert result['trend7']['warning']


def test_improvement_allowed_through_d14():
    rows,e=event(14)
    for row in rows[:30]:row.update(qty=10,revenue=200,profit=24)
    for row in rows[-6:-3]:row.update(qty=1,revenue=20,profit=2.4)
    for row in rows[-3:]:row.update(qty=3,revenue=60,profit=7.2)
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['state']=='improving'
    rows+=daily([5],qty=3,start=rows[-1]['day']+timedelta(days=1))
    assert rules().evaluate_event(rows,e,rows[-1]['day'])['state']=='poor'


@pytest.mark.parametrize('exit_age,windows',[(22,[20,21,21]),(30,[21,21,30])])
def test_exit_confirmation_survives_window_switch(exit_age,windows):
    rows,e=event(exit_age)
    for row in rows[33:]:row.update(qty=2,revenue=40,profit=0)
    # Only the final three evaluation dates have at least 10% order margin.
    for offset in range(3):
        n=exit_age-2+offset
        rows[32+n]['profit']=40*n/10 if offset==0 else 4
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['exit_status']=='normal'
    assert result['exit_date']==rows[-1]['day']
    assert [m['days'] for m in result['exit_confirmation']]==windows


def test_current_role_uses_30_days_not_old_14_days():
    rows,e=event(32)
    for row in rows[33:]:row.update(qty=1,revenue=20,profit=0)
    for row in rows[33:49]:row.update(qty=10,revenue=200,profit=40)
    # Missing first day blocks all N-day windows, and drops out at D31.
    rows[33]['stock']=None
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['current_evaluation']['days']==30
    assert result['current_evaluation']['role'] in ('潜力','明星')
    assert rules().metrics({r['day']:r for r in rows},rows[-1]['day'],14)['margin']==0


def test_missing_history_does_not_block_matched_role_exit():
    rows,e=event(10)
    for row in rows[:30]:row['stock']=None
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['comparison']['history'] is None
    assert result['exit_status']=='normal' and result['confirmation_days']==3


def test_role_failure_restarts_three_day_confirmation():
    rows,e=event(13)
    rows[41]['profit']=-100  # D9 drags the whole N-day role below target.
    rows[43]['profit']=150   # D11 restores the whole N-day role.
    for age,expected in [(8,1),(9,0),(10,0),(11,1),(12,2),(13,3)]:
        result=rules().evaluate_event(rows,e,e['return_date']+timedelta(days=age-1))
        assert result['confirmation_days']==expected
        assert (result['exit_status']=='normal')==(age==13)
