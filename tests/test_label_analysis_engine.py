from datetime import date
import pytest

from app.services.label_analysis_engine import inventory_calendar, prepare_rows, aggregate, select_cohorts, compare_metrics


def sample(msku='A', pool='p1', sales=30, labels=None):
    return dict(key=msku, msku=msku, store='S', country_category='欧洲', country='德国',
                pool_id=pool, demand_id=pool, labels=labels or [],
                daily={'2026-10-10': {'sales_qty': sales, 'sales_amount': sales*10, 'order_gross_profit': sales*2, 'sessions_total': 100}},
                inventory={'2026-10-09': 5, '2026-10-10': 0, '2026-10-11': 0},
                replenishment={'date': '2026-10-11', 'daily_avg_sales': 2, 'inventory_support_days': 8, 'support_inventory_qty': 16},
                inventory_values={'date': '2026-10-11', 'ending_inventory_qty': 0})


def prepared(*rows):
    return prepare_rows(list(rows), date(2026,10,9), date(2026,10,11))


def test_calendar_keeps_missing_and_negative_days_unknown():
    r=inventory_calendar({'2026-10-09':0,'2026-10-11':-1},date(2026,10,9),date(2026,10,11))
    assert r['stockout_days']==1
    assert r['unknown_inventory_days']==2
    assert r['current_stockout_days'] is None
    assert r['stockout_day_rate']==1
    assert r['inventory_observation_rate']==pytest.approx(1/3)


def test_calendar_only_counts_confirmed_transitions_and_marks_open_boundary():
    r=inventory_calendar({'2026-10-09':0,'2026-10-10':0,'2026-10-11':0},date(2026,10,9),date(2026,10,11))
    assert r['stockout_events']==0
    assert r['current_stockout_days']==3
    assert r['current_stockout_lower_bound'] is True
    r=inventory_calendar({'2026-10-09':3,'2026-10-10':0,'2026-10-11':0},date(2026,10,9),date(2026,10,11))
    assert r['stockout_events']==1
    assert r['current_stockout_lower_bound'] is False


def test_replenishment_daily_sales_is_used_without_natural_day_fallback():
    a=sample(); a['inventory']['2026-10-11']=20; a['inventory_values']['ending_inventory_qty']=20
    row=prepared(a)[0]
    assert row['values']['replenishment_daily_sales']==2
    assert row['values']['fba_coverage_days']==10
    assert row['values']['period_daily_sales']==10
    assert row['values']['support_days']==8
    a['replenishment']['daily_avg_sales']=0
    assert prepared(a)[0]['values']['fba_coverage_days'] is None


def test_future_or_stale_replenishment_is_not_used_for_coverage():
    a=sample(); a['replenishment']['date']='2026-10-12'
    assert prepared(a)[0]['values']['replenishment_daily_sales'] is None
    a['replenishment']['date']='2026-10-10'
    assert prepared(a)[0]['values']['fba_coverage_days'] is None


def test_or_and_and_ordered_parent_cohort():
    a=sample(labels=[{'parent_id':1,'id':101},{'parent_id':3,'id':301}])
    b=sample('B','p2',labels=[{'parent_id':1,'id':102},{'parent_id':3,'id':304}])
    c=sample('C','p3',labels=[])
    base,parent,current=select_cohorts(prepared(a,b,c),[
        {'kind':'label','parent_id':1,'ids':[101,102]},
        {'kind':'label','parent_id':3,'ids':[301]},
    ])
    assert len(base)==3 and len(parent)==2 and len(current)==1


def test_metric_filter_null_and_numeric_bounds():
    rows=prepared(sample(),sample('B','p2',sales=0))
    _,_,found=select_cohorts(rows,[{'kind':'metric','metric':'sales_qty','op':'gt','value':0}])
    assert [r['msku'] for r in found]==['A']


def test_shared_pool_is_counted_once_but_sales_are_additive():
    a=sample(); b=sample('B',sales=60)
    for row in [a,b]:
        row['inventory']['2026-10-11']=20
        row['inventory_values']['ending_inventory_qty']=20
    r=aggregate(prepared(a,b))
    assert r['sales_qty']['value']==90
    assert r['ending_inventory_qty']['value']==20
    assert r['replenishment_daily_sales']['value']==2
    assert r['fba_coverage_days']['value']==10
    assert r['order_gross_margin']['value']==.2
    assert r['pool_count']['value']==1


def test_conflicting_shared_pool_is_unknown_not_arbitrary_max():
    a=sample(); b=sample('B'); b['inventory']['2026-10-11']=99
    b['inventory_values']['ending_inventory_qty']=99
    r=aggregate(prepared(a,b))
    assert r['ending_inventory_qty']['value'] is None
    assert r['ending_inventory_qty']['status']=='unavailable'


def test_absent_business_metrics_are_zero_and_inventory_stays_unknown():
    a=sample(); a['daily']={}; a['inventory']={}; a['replenishment']={}; a['inventory_values']={}
    r=aggregate(prepared(a))
    assert r['object_count']['value']==1
    assert r['sales_qty']['value']==0
    assert r['zero_sales_rate']['value']==1
    assert r['ending_inventory_qty']['value'] is None
    assert r['label_coverage_rate']['value']==0


def test_ratios_use_summed_components_and_absent_days_are_zero():
    a=sample(); b=sample('B','p2',sales=3)
    b['daily']['2026-10-10']['order_gross_profit']=-15
    r=aggregate(prepared(a,b))
    assert r['order_gross_margin']['value']==pytest.approx(45/330)
    assert r['sales_qty']['status']=='available'


def test_percentiles_do_not_pool_unrelated_demand():
    a=sample(); b=sample('B','p2')
    a['inventory']['2026-10-11']=20; a['inventory_values']['ending_inventory_qty']=20
    b['inventory']['2026-10-11']=100; b['inventory_values']['ending_inventory_qty']=100
    r=aggregate(prepared(a,b))['fba_coverage_days']
    assert r['value']==30
    assert r['p25']==20 and r['p75']==40


def test_comparison_uses_absolute_change_for_negative_base():
    a={'profit':{'value':5,'unit':'money'}}; b={'profit':{'value':-5,'unit':'money'}}
    c=compare_metrics(a,b)['profit']
    assert c['delta']==10 and c['relative_change'] is None


def test_requested_column_aggregation_has_same_ratios_and_pool_values():
    rows=prepared(sample(),sample('B','p1',sales=10))
    fields=['order_gross_margin','fba_coverage_days','object_count','stockout_day_rate','top10_sales_share']
    full=aggregate(rows); selected=aggregate(rows,fields)
    assert selected=={k:full[k] for k in fields}
