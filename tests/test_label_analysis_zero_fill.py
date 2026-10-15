import csv,io
from datetime import date
from app.services.label_analysis_engine import prepare_rows,aggregate
from app.services.label_analysis_service import LabelAnalysisService,AnalysisQuery
from test_label_analysis_engine import sample
from test_label_analysis_service import Repo


def test_absent_business_days_are_zero_but_inventory_and_present_nulls_stay_unknown():
    raw=sample();raw['inventory']={};raw['replenishment']={};raw['daily']['2026-10-10']['sessions_total']=None
    row=prepare_rows([raw],date(2026,10,9),date(2026,10,11))[0]
    totals=aggregate([row])
    assert totals['sales_qty']['value']==30
    assert totals['sales_qty']['status']=='available'
    assert row['observed_days']['sales_qty']==1
    assert row['effective_days']['sales_qty']==3
    assert row['zero_filled_days']==2
    assert totals['sessions_total']['status']=='partial'
    assert row['values']['ending_inventory_qty'] is None
    assert row['values']['fba_coverage_days'] is None
    assert row['values']['stockout_days'] is None
    assert row['values']['small_category_rank'] is None
    assert len(raw['daily'])==1


def test_entirely_absent_business_period_is_zero_including_prior_and_all_delivery_paths():
    repo=Repo()
    def load(*args):
        raw=sample(labels=[{'id':101,'parent_id':1}]);raw['daily']={}
        return {'rows':[raw],'categories':repo.metadata()['categories'],'sources':{},'warnings':[]}
    repo.load=load
    service=LabelAnalysisService(repo);q=AnalysisQuery(data_date='2026-10-11',period=7,columns=['sales_qty','sales_amount','order_gross_profit','sessions_total'])
    summary=service.summary(q)
    for key in q.columns:
        assert summary['current'][key]['value']==summary['previous'][key]['value']==0
        assert summary['current'][key]['status']=='available'
    assert summary['current']['zero_sales_rate']['value']==1
    assert summary['current']['order_gross_margin']['value'] is None
    detail=service.details(q)['rows'][0]
    history=service.details(q.model_copy(update={'object_key':detail['key']}))['rows'][0]['history']
    assert len(history)==7 and all(day['sales_qty']==day['sessions_total']==0 for day in history)
    assert all(day['inventory'] is None for day in history[:4])
    trend=service.trends(q)
    for point in trend['current']+trend['previous']:
        assert point['sales_qty']==point['sales_amount']==0
        assert point['coverage']['sales_qty']['valid_count']==1
    exported=list(csv.DictReader(io.StringIO(service.export(q).lstrip('\ufeff'))))
    assert float(exported[0]['销量'])==float(exported[0]['销售额'])==0
