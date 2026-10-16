from datetime import timedelta

import pytest

from test_return_goods_strategy_rules import event,rules


@pytest.mark.parametrize('history,target',[("问题","瘦狗"),("瘦狗","瘦狗"),("不可判","瘦狗"),("潜力","潜力"),("明星","潜力")])
@pytest.mark.parametrize('early',[True,False])
def test_history_role_sets_both_exit_paths(history,target,early):
    rows,e=event(10,first_bad=not early)
    historical={'问题':(2,.01),'瘦狗':(2,.08),'潜力':(2,.12),'明星':(6,.2),'不可判':(2,None)}
    qty,margin=historical[history]
    for row in rows[:30]:row.update(qty=qty,revenue=qty*20,profit=None if margin is None else qty*20*margin)
    for row in rows[33:]:row.update(qty=2,revenue=40,profit=3.2)
    if not early:rows[33]['profit']=0
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['baseline']['role']==history
    assert result['exit_target']==target
    if target=='瘦狗':
        assert result['exit_status']==('early' if early else 'normal')
        assert result['exit_date']==e['return_date']+timedelta(days=6 if early else 9)
    else:
        assert result['exit_status']=='tracking'
        assert any('10%' in reason for reason in result['exit_reasons'])


@pytest.mark.parametrize('qty,margin,passes',[(0,.8,False),(-1,.8,False),(.5,.05,False),(.5,.05001,True),(1,.05,True),(5,.05,True),(6,.05,True),(2,.0499,False)])
def test_dog_exit_boundaries(qty,margin,passes):
    assert rules().meets_exit_target(qty,margin,'瘦狗') is passes


def test_dog_exit_role_failure_resets_confirmation():
    rows,e=event(13)
    for row in rows[:30]:row['profit']=.4
    for row in rows[33:]:row['profit']=3.2
    rows[33]['profit']=0
    rows[41]['profit']=-100
    rows[43]['profit']=150
    for age,count in [(8,1),(9,0),(10,0),(11,1),(12,2),(13,3)]:
        result=rules().evaluate_event(rows,e,e['return_date']+timedelta(days=age-1))
        assert result['exit_target']=='瘦狗' and result['confirmation_days']==count
        assert (result['exit_status']=='normal')==(age==13)


@pytest.mark.parametrize('problem',['missing_qty','stockout'])
def test_dog_target_does_not_bypass_stock_and_data(problem):
    rows,e=event(10)
    for row in rows[:30]:row['profit']=.4
    for row in rows[33:]:row['profit']=3.2
    rows[33]['profit']=0
    rows[-2]['qty' if problem=='missing_qty' else 'stock']=None if problem=='missing_qty' else 0
    result=rules().evaluate_event(rows,e,rows[-1]['day'])
    assert result['exit_target']=='瘦狗' and result['exit_status']=='tracking'
    assert result['confirmation_days']==0


def test_completed_exit_keeps_original_target_and_role_evidence():
    from etl.return_goods_strategy_update import retain_exit
    rows,e=event(10)
    current=rules().evaluate_event(rows,e,rows[-1]['day'])
    previous={**current,'exit_target':'瘦狗','baseline':{'role':'不可判','evidence':'首次评价时无有效历史角色'}}
    retain_exit(current,previous,rows[-1]['day'])
    assert current['exit_target']=='瘦狗'
    assert current['baseline']['role']=='不可判'
