from datetime import date

from app.services.label_analysis_engine import prepare_rows, select_cohorts
from app.services.label_analysis_service import AnalysisQuery, LabelAnalysisService
from test_label_analysis_engine import sample


def capital_rows():
    rows=[]
    for key,stock,demand in [('a',90,1),('b',180,1),('c',181,1),('d',10,0),('e',10,None)]:
        r=sample(key,key,labels=[{'id':101,'parent_id':1}])
        r['inventory']['2026-10-11']=stock
        r['inventory_values'].update(ending_inventory_qty=stock,inventory_cost=stock*2)
        r['replenishment']['daily_avg_sales']=demand
        rows.append(r)
    return rows


class CapitalRepo:
    def metadata(self):
        return dict(dates=['2026-10-11'],categories=[dict(id=1,label='销售角色',children=[dict(id=101,label='明星')])])
    def load(self,*args):
        return dict(rows=capital_rows(),categories=self.metadata()['categories'],sources={},warnings=[])


def test_capital_bands_boundaries_missing_zero_and_preserved_filters():
    s=LabelAnalysisService(CapitalRepo())
    q=AnalysisQuery(data_date='2026-10-11',conditions=[dict(kind='label',parent_id=1,ids=[101]),dict(kind='metric',metric='fba_coverage_days',op='gt',value=180,preset='capital')])
    p=s.summary(q)
    assert p['current']['object_count']['value']==1
    bands=p['capital']['bands']
    assert [b['metrics']['object_count']['value'] for b in bands]==[1,1,1,2]
    assert p['capital']['zero_demand']['metrics']['object_count']['value']==1
    for b in bands+[p['capital']['zero_demand']]:
        conditions=[q.conditions[0].model_dump()]+b['conditions']
        rows=prepare_rows(capital_rows(),date(2026,9,12),date(2026,10,11))
        chosen=select_cohorts(rows,conditions)[2]
        assert len(chosen)==b['metrics']['object_count']['value']
    assert bands[2]['metrics']['inventory_cost']['value']==362
    assert p['capital']['scope']['object_count']['value']==5


def test_rank_is_cutoff_only_and_coverage_demand_is_full_group_demand():
    r=capital_rows()[0]
    r['daily']['2026-10-10']['small_category_rank']=5
    r['daily']['2026-10-11']={'small_category_rank':51}
    r['replenishment']['coverage_daily_sales']=3
    row=prepare_rows([r],date(2026,10,9),date(2026,10,11))[0]
    assert row['values']['small_category_rank']==51
    assert row['values']['coverage_demand_daily_sales']==3
    del r['daily']['2026-10-11']
    assert prepare_rows([r],date(2026,10,9),date(2026,10,11))[0]['values']['small_category_rank'] is None


def test_capital_shared_pool_cost_is_deduplicated_and_manual_filter_kept():
    repo=CapitalRepo()
    original=repo.load
    def load(*args):
        data=original(*args)
        from copy import deepcopy
        duplicate=deepcopy(data['rows'][2]);duplicate.update(key='shared',msku='shared')
        data['rows'].append(duplicate)
        return data
    repo.load=load
    s=LabelAnalysisService(repo)
    q=AnalysisQuery(data_date='2026-10-11',conditions=[dict(kind='metric',metric='inventory_cost',op='gt',value=350),dict(kind='metric',metric='fba_coverage_days',op='gt',value=180,preset='capital')])
    p=s.summary(q)
    assert p['capital']['scope']['object_count']['value']==3
    assert p['current']['object_count']['value']==2
    assert p['capital']['bands'][2]['metrics']['inventory_cost']['value']==362
    assert p['capital']['scope']['inventory_cost']['value']==722
    assert len(p['capital']['structures'][0]['children'])==1
