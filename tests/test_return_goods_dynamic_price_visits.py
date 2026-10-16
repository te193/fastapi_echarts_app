from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import return_goods_strategy_rules as r
from etl.return_goods_strategy_update import enrich


def context(hs=100, hq=10, cs=30, cq=1, age=14, sales_first=True):
    event=dict(exit_status='tracking',age=age,state='sales_repair' if sales_first else 'poor',
               as_of=date(2026,10,8),recent=dict(daily=1.1,margin=.02),
               comparison=dict(current=dict(sales_complete=True,daily=Decimal('.5') if sales_first else Decimal('1.1'))))
    current=dict(days=r.comparison_days(age),stocked=True,sales_complete=True,qty=cq,sessions=cs)
    history=dict(days=30,stocked=True,sales_complete=True,qty=hq,sessions=hs)
    country=dict(recent=dict(complete=True,daily=.5,qty=1,sessions=1,margin=.12),
                 historical=history,price_comparison=dict(current=current,history=history))
    return event,country


def calculate(event,country,dos=28,listing=None):
    return r.price_candidate(event,country,listing or dict(price=25,currency='EUR'),
                             {f'p{x}':x for x in (10,15,20,25,30,35)},dos)


@pytest.mark.parametrize('hs,hq,threshold', [(100,20,15),(100,10,30),(100,5,60),(500,10,150),(99,9,33)])
@pytest.mark.parametrize('sales_first',[True,False])
def test_dynamic_visit_threshold_and_exact_boundary(hs,hq,threshold,sales_first):
    event,country=context(hs=hs,hq=hq,cs=threshold-1,sales_first=sales_first)
    result=calculate(event,country)
    assert result['action']=='hold'
    assert result['price_conversion']['required_sessions']==threshold
    country['price_comparison']['current']['sessions']=threshold
    result=calculate(event,country)
    assert result['action']=='price_down' and result['target']==20
    assert result['price_conversion']['is_trial_rule'] is True


def test_neither_current_nor_history_requires_fifty_visits():
    event,country=context(hs=40,hq=8,cs=15,cq=1)
    result=calculate(event,country)
    assert result['action']=='price_down' and result['price_conversion']['required_sessions']==15


@pytest.mark.parametrize('qty,action', [('2.09999','price_down'),('2.1','hold'),('3','hold')])
def test_seventy_percent_boundary_is_strict(qty,action):
    event,country=context(cq=Decimal(qty))
    assert calculate(event,country)['action']==action


def test_recent_seven_days_do_not_override_main_price_window():
    event,country=context(cs=30,cq=1)
    country['recent'].update(sessions=0,qty=0)
    assert calculate(event,country)['action']=='price_down'
    country['recent'].update(sessions=500,qty=1)
    country['price_comparison']['current']['sessions']=29
    assert calculate(event,country)['action']=='hold'


@pytest.mark.parametrize('field,value', [('sessions',None),('qty',None),('sessions',-1),
                                      ('stocked',False),('days',7)])
def test_current_window_missing_invalid_or_wrong_days_never_falls_back_to_seven(field,value):
    event,country=context()
    country['price_comparison']['current'][field]=value
    result=calculate(event,country)
    assert result['target'] is None and result['status']=='pending'


@pytest.mark.parametrize('field,value', [('sessions',None),('sessions',0),('qty',0),('qty',None),('stocked',False)])
def test_history_unknown_never_uses_fifty_as_fallback(field,value):
    event,country=context()
    country['price_comparison']['history'][field]=value
    result=calculate(event,country)
    assert result['target'] is None and result['status']=='pending'
    assert result['price_conversion']['required_sessions'] is None


def test_historical_five_units_and_existing_price_guards():
    event,country=context(hq=4)
    assert calculate(event,country)['action']=='hold'
    country['price_comparison']['history']['qty']=5
    country['price_comparison']['current']['sessions']=60
    assert calculate(event,country,dos=13)['status']=='blocked'
    assert calculate(event,country,listing=dict(price=10,currency='EUR'))['target'] is None
    assert calculate(event,country,listing=dict(price=25,currency='EUR',last_change_date=date(2026,10,7)))['status']=='blocked'
    event['age']=7
    assert calculate(event,country)['action']=='hold'
    event['age']=14;event['exit_status']='early'
    assert calculate(event,country)['action']=='hold'


@pytest.mark.parametrize('age,days',[(8,8),(14,14),(21,21),(22,21),(29,21),(30,30),(75,30)])
def test_enrichment_country_windows_are_after_return_and_history_is_before_stockout(age,days):
    from test_return_goods_strategy_rules import event as make_event
    rows,entry=make_event(age)
    # Same inventory, different country conversion; no cross-country borrowing.
    countries=[]
    for country,historical_qty in [('德国',1),('法国',Decimal('.2'))]:
        for row in rows:
            item=dict(row,country=country)
            if row['day']<entry['stockout_date']:
                item.update(qty=historical_qty,sessions=10)
            else:
                item.update(qty=0,sessions=10)
            countries.append(item)
    actual=r.evaluate_event(rows,entry,rows[-1]['day'])
    _,detail=enrich(actual,('test','欧洲站','sku'),countries,{}, {}, {}, {},rows[-1]['day'])
    by_country={c['country']:c for c in detail['countries']}
    for name in ('德国','法国'):
        pair=by_country[name]['price_comparison']
        assert pair['current']['days']==days
        assert pair['current']['start']>=entry['return_date']
        assert pair['current']['sessions']==days*10
        assert pair['history']['end']<entry['stockout_date']
    assert by_country['德国']['price_comparison']['history']['qty']!=by_country['法国']['price_comparison']['history']['qty']
