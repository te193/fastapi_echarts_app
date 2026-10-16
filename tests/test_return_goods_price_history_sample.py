from datetime import date
from decimal import Decimal
import pytest
from app.services import return_goods_strategy_rules as rules


@pytest.mark.parametrize('sales_first',[True,False])
@pytest.mark.parametrize('history_sessions,history_qty,current_sessions,current_qty,expected',[
    (49,5,50,1,'price_down'),(50,5,50,1,'price_down'),(99,5,50,1,'hold'),
    (50,4,50,1,'hold'),(50,5,49,1,'price_down'),(50,5,50,3.5,'hold'),
])
def test_dynamic_visits_replace_both_fifty_visit_gates(sales_first,history_sessions,history_qty,current_sessions,current_qty,expected):
    event=dict(exit_status='tracking',age=20,state='sales_repair' if sales_first else 'poor',as_of=date(2026,10,8),
               recent=dict(daily=1.1,margin=.02),comparison=dict(current=dict(sales_complete=True,daily=.5 if sales_first else 1.1)))
    country=dict(recent=dict(complete=True,daily=current_qty/7,qty=current_qty,sessions=current_sessions,margin=.12),
                 historical=dict(qty=history_qty,sessions=history_sessions))
    country['price_comparison']=dict(current=dict(days=20,stocked=True,sales_complete=True,qty=current_qty,sessions=current_sessions),
                                     history=dict(days=30,stocked=True,sales_complete=True,qty=history_qty,sessions=history_sessions))
    result=rules.price_candidate(event,country,dict(price=25,currency='EUR'),{f'p{x}':x for x in (10,15,20,25,30,35)},28)
    assert result['action']==expected
    if expected=='price_down':assert result['target']==Decimal('20.00')
