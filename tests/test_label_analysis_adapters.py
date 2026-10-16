from datetime import date
import pytest

from app.services.label_analysis_engine import prepare_rows, aggregate
from app.services.label_analysis_repository import AnalysisRepository, normalize_msku, remove_redundant_unmapped, resolve_supply
from app.services.label_analysis_service import Condition


def test_all_categories_follow_fixed_dictionary_order():
    definitions=[dict(label_id=p,label_name=str(p),sub_label_id=c,sub_label_name=str(c),status='启用') for p,c in [(3,303),(1,104),(3,301),(1,102),(1,101),(1,103)]]
    for source in [definitions,list(reversed(definitions))]:
        result=AnalysisRepository.categories(source)
        assert [c['id'] for c in result]==[1,3]
        assert [[t['id'] for t in c['children']] for c in result]==[[101,102,103,104],[301,303]]


def test_listing_normalization_matches_existing_long_msku_rule():
    assert normalize_msku('amzn.gr.BYA002a-special') == 'BYA002a'
    assert normalize_msku('BYA-002') == 'BYA-002'


def test_only_truly_unmapped_regions_remain():
    rows={'a':dict(region_key='x',country='',daily={}), 'b':dict(region_key='x',country='德国',daily={}), 'c':dict(region_key='y',country='',daily={})}
    remove_redundant_unmapped(rows)
    assert set(rows)=={'b','c'}


def supply(flag=1, merged=0, qty=20, daily=2):
    return dict(date='2026-10-12', fllow_flag=flag, asin_merge_flag=merged, max_asin='ASIN', max_fnsku='', daily_avg_sales=daily, afn_fulfillable_quantity=qty, support_inventory_qty=qty, effective_purchase_lead_days=10, lead_time_demand_qty=30, inventory_support_days=20)


def test_normal_links_keep_daily_and_followers_do_not_invent_demand():
    repl={('地区\x1fS\x1fA\x1f','2026-10-12'):supply(), ('地区\x1fS\x1fB\x1f','2026-10-12'):supply(0)}
    resolve_supply(repl)
    a,b=repl.values()
    assert a['coverage_daily_sales']==2
    assert b['coverage_daily_sales'] is None
    assert b['daily_avg_sales']==2


def test_merged_group_uses_published_group_demand_not_inherited_sum():
    repl={('地区\x1fS\x1fA\x1f','2026-10-12'):supply(1,1), ('地区\x1fT\x1fB\x1f','2026-10-12'):supply(0,1,40,2)}
    resolve_supply(repl)
    a,b=repl.values()
    assert a['coverage_daily_sales']==3
    assert a['coverage_inventory_qty']==60
    assert a['demand_id']==b['demand_id']
    assert a['daily_avg_sales']==2
    assert a['aggregate_values']['replenishment_daily_sales']==3


def test_conflicting_group_demand_stays_unknown():
    a,b=supply(1,1),supply(0,1);b['lead_time_demand_qty']=40
    repl={('地区\x1fS\x1fA\x1f','2026-10-12'):a,('地区\x1fT\x1fB\x1f','2026-10-12'):b}
    resolve_supply(repl)
    assert a['coverage_daily_sales'] is None


def test_ratio_pairs_days_and_missing_inventory_is_not_zero():
    raw=dict(key='A',msku='A',store='S',pool_id='p',demand_id='p',daily={'2026-10-11':dict(sales_amount=100,order_gross_profit=20),'2026-10-12':dict(sales_amount=100)},inventory={})
    r=aggregate(prepare_rows([raw],date(2026,10,11),date(2026,10,12)))
    assert r['order_gross_margin']['value']==.2
    assert r['order_gross_margin']['status']=='partial'
    assert r['order_gross_margin']['denominator']==100
    assert r['stockout_days']['value'] is None
    assert r['stockout_events']['value'] is None


def test_population_ratios_are_not_row_filters():
    with pytest.raises(ValueError): Condition(kind='metric',metric='current_zero_inventory_rate',op='gt',value=0)


def test_shared_fnsku_uses_complete_demand_even_if_one_link_is_selected():
    a,b=supply(daily=2),supply(daily=3)
    a['max_fnsku']=b['max_fnsku']='F'
    repl={('地区\x1fS\x1fA\x1f','2026-10-12'):a,('地区\x1fS\x1fB\x1f','2026-10-12'):b}
    resolve_supply(repl)
    assert a['coverage_daily_sales']==5
    assert a['demand_id']==b['demand_id']
    row=dict(key='A',msku='A',store='S',daily={},inventory={'2026-10-12':20},replenishment=a)
    assert prepare_rows([row],date(2026,10,12),date(2026,10,12))[0]['values']['fba_coverage_days']==4


def test_shared_inventory_conflict_stays_unknown_when_selecting_one_member():
    a,b=supply(qty=20),supply(qty=30)
    a['max_fnsku']=b['max_fnsku']='F'
    resolve_supply({('地区\x1fS\x1fA\x1f','2026-10-12'):a,('地区\x1fS\x1fB\x1f','2026-10-12'):b})
    row=dict(key='A',msku='A',store='S',daily={},inventory={'2026-10-12':20},replenishment=a)
    result=prepare_rows([row],date(2026,10,12),date(2026,10,12))
    assert result[0]['values']['fba_coverage_days'] is None
    assert aggregate(result)['ending_inventory_qty']['value'] is None


def test_inception_excludes_days_before_object_existed():
    row=dict(key='A',msku='A',store='S',inception_date='2026-10-12',daily={},inventory={'2026-10-12':0})
    v=prepare_rows([row],date(2026,10,1),date(2026,10,12))[0]['values']
    assert v['expected_inventory_days']==1
    assert v['unknown_inventory_days']==0
    assert v['stockout_days']==1


def test_stockout_pool_days_do_not_repeat_for_country_members():
    row=dict(key='A',msku='A',store='S',pool_id='p',daily={},inventory={'2026-10-12':0})
    other={**row,'key':'B','country':'FR'}
    metrics=aggregate(prepare_rows([row,other],date(2026,10,12),date(2026,10,12)))
    assert metrics['stockout_days']['value']==2
    assert metrics['pool_stockout_days']['value']==1


def test_mysql_compressed_evidence_is_decoded_before_json_response():
    import json
    class DB:
        def connect(self):return self
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,args):self.sql=sql
        def fetchone(self):return {'t':'release'}
        def fetchall(self):
            value='{"sales":3}' if 'uncompress(evidence_blob)' in self.sql else b'\x97compressed'
            return [dict(label_id=101,label_period='30d',country='',evidence_blob=value)]
    row=dict(country_category='欧洲',store='s',msku='A',labels=[dict(id=101,period='30d',country='')])
    result=AnalysisRepository(DB()).evidence(row,'2026-10-11','release')
    assert json.loads(result[0]['evidence_blob'])=={'sales':3}
