from datetime import date
import pytest
from app.services.label_analysis_engine import prepare_rows,select_cohorts
from app.services.label_analysis_service import AnalysisQuery,LabelAnalysisService
from test_label_analysis_engine import sample


def gap_rows():
    no_data=sample('no-data','pool-1');no_data['daily']={};no_data['replenishment']={}
    has_data=sample('has-data','pool-2');has_data['replenishment']={}
    zero=sample('zero','pool-3');zero['replenishment']['daily_avg_sales']=0
    pending=sample('pending','pool-4');pending['replenishment']['coverage_daily_sales']=None
    good=sample('good','pool-5')
    return [no_data,has_data,zero,pending,good]


class GapRepository:
    def metadata(self):return {'dates':['2026-10-11'],'categories':[]}
    def load(self,*args):return {'rows':gap_rows(),'categories':[],'sources':{},'warnings':[]}


def test_coverage_gaps_partition_and_click_members_without_inventing_sales():
    service=LabelAnalysisService(GapRepository());q=AnalysisQuery(data_date='2026-10-11')
    result=service.summary(q);gaps=result['capital']['coverage_gaps']
    assert [g['key'] for g in gaps]==['no_performance','missing_daily_sales','zero_daily_sales','data_pending']
    assert [g['metrics']['object_count']['value'] for g in gaps]==[1,1,1,1]
    assert sum(g['metrics']['object_count']['value'] for g in gaps)==result['capital']['bands'][3]['metrics']['object_count']['value']
    prepared=prepare_rows(gap_rows(),date(2026,9,12),date(2026,10,11))
    for gap,key in zip(gaps,['no-data','has-data','zero','pending']):
        query=AnalysisQuery.model_validate({'data_date':'2026-10-11','conditions':gap['conditions']})
        assert [r['key'] for r in select_cohorts(prepared,[c.model_dump() for c in query.conditions])[2]]==[key]
        details=service.details(query)
        assert [r['key'] for r in details['rows']]==[key]
        assert key in service.export(query)


def test_existing_zero_sales_records_are_performance_and_traffic_alone_counts():
    from app.services.label_analysis_engine import coverage_gap
    r=sample();r['replenishment']={};r['daily']={'2026-10-11':{'sales_qty':0,'sales_amount':0}}
    prepared=prepare_rows([r],date(2026,10,5),date(2026,10,11))[0]
    assert coverage_gap(prepared)=='missing_daily_sales'
    r['daily']={};r['traffic_daily']={'2026-10-11':{'sessions_total':3}}
    assert coverage_gap(prepare_rows([r],date(2026,10,5),date(2026,10,11))[0])=='missing_daily_sales'


def test_invalid_coverage_reason_is_rejected_and_other_filters_still_apply():
    with pytest.raises(ValueError):AnalysisQuery(conditions=[{'kind':'coverage','reason':'anything'}])
    q=AnalysisQuery(conditions=[{'kind':'coverage','reason':'no_performance','preset':'capital'},
                               {'kind':'metric','metric':'sales_qty','op':'gt','value':0}])
    assert LabelAnalysisService(GapRepository()).summary(q)['current']['object_count']['value']==0
