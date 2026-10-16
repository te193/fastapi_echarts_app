from copy import deepcopy
from datetime import date
import csv
import io
import json
import pytest
from app.services.label_analysis_role_history import summarize_periods,role_tag,category,attach_snapshot,HISTORY_FIELDS,PARENT_ID
from app.services.label_analysis_engine import aggregate,select_cohorts,prepare_rows
from app.services.label_analysis_service import LabelAnalysisService,AnalysisQuery
from test_label_analysis_engine import sample


def node(no,role,end='2026-09-30',eligible=1,complete=1,start='2026-09-01'):
    return dict(no=no,role_id=role,start=start,end=end,eligible=eligible,complete=complete)


def test_history_uses_only_completed_eligible_asof_periods_and_latest_tie():
    result=summarize_periods([node(1,101),node(2,1302),node(3,104,eligible=0),node(4,104,end='2026-10-15'),node(5,101,complete=0),node(6,103,start='2026-10-13')],'2026-10-12')
    assert result['dominant_role_id']==102
    assert result['values']['history_valid_segments']==2
    assert result['values']['history_excluded_segments']==3
    assert result['values']['history_star_share']==.5
    assert result['values']['history_problem_count']==0


def test_no_valid_history_has_no_fabricated_role_or_percentage():
    result=summarize_periods([node(1,104,eligible=0)],'2026-10-12')
    assert result['dominant_role_id'] is None
    assert result['values']['history_problem_count']==0
    assert result['values']['history_problem_share'] is None
    assert result['values']['history_excluded_segments']==1
    assert role_tag(None)['label']=='暂未形成主导角色'


def test_duplicate_period_is_rejected_instead_of_double_counted():
    with pytest.raises(ValueError):summarize_periods([node(1,101),node(1,102)],'2026-10-12')


def test_group_shares_use_summed_periods_not_average_product_percentages():
    a=prepare_rows([sample()],date(2026,10,5),date(2026,10,11))[0]
    b=deepcopy(a);b['key']='B'
    a['values'].update(summarize_periods([node(1,101)],'2026-10-12')['values'])
    b['values'].update(summarize_periods([node(i,102) for i in range(1,10)],'2026-10-12')['values'])
    result=aggregate([a,b],HISTORY_FIELDS)
    assert result['history_valid_segments']['value']==10
    assert result['history_star_share']['value']==.1
    assert result['history_potential_share']['value']==.9


def test_intranet_attach_keeps_unmatched_objects_and_never_borrows_country():
    a=prepare_rows([sample(),sample('B')],date(2026,10,5),date(2026,10,11))
    class Cursor:
        def execute(self,sql,args):assert args==('batch',date(2026,10,11),'country')
        def fetchall(self):return [dict(object_key='A',result_json=json.dumps(summarize_periods([node(1,1301)],'2026-10-11')))]
    assert attach_snapshot(Cursor(),'batch',date(2026,10,11),'country',a)==1
    assert len(a)==2 and a[0]['labels'][-1]==role_tag(101)
    assert a[1]['values']['history_star_count'] is None
    assert a[1]['labels'][-1]==role_tag(None)


def test_historical_current_role_and_operating_status_filter_together_and_export():
    rows=prepare_rows([sample('A',labels=[{'id':101,'parent_id':1},{'id':301,'parent_id':3}]),sample('B',labels=[{'id':104,'parent_id':1},{'id':301,'parent_id':3}])],date(2026,10,5),date(2026,10,11))
    for row in rows:
        row['role_history']=summarize_periods([node(1,102)],'2026-10-11')
        row['values'].update(row['role_history']['values']);row['labels'].append(role_tag(102))
    class Repo:
        materialized=True
        def metadata(self):return dict(published_batch='fixed',dates=['2026-10-11'],categories=[{'id':1,'label':'销售角色','children':[{'id':101,'label':'明星'},{'id':104,'label':'问题'}]},{'id':3,'label':'运营状态','children':[{'id':301,'label':'正常在售'}]},category()])
        def load_prepared(self,*args):return dict(version='fixed',prepared=deepcopy(rows),previous_prepared=deepcopy(rows),rows=[],sources={},warnings=[],categories=self.metadata()['categories'])
    service=LabelAnalysisService(Repo())
    query=AnalysisQuery(data_date='2026-10-11',period=7,conditions=[{'kind':'label','parent_id':PARENT_ID,'ids':[role_tag(102)['id'],role_tag(103)['id']]},{'kind':'label','parent_id':1,'ids':[101]},{'kind':'label','parent_id':3,'ids':[301]}],columns=list(HISTORY_FIELDS))
    result=service.summary(query)
    assert result['current']['object_count']['value']==1
    assert result['parent']['object_count']['value']==1
    assert result['baseline']['object_count']['value']==2
    assert result['current']['history_potential_share']['value']==1
    assert service.details(query)['rows'][0]['msku']=='A'
    exported=list(csv.DictReader(io.StringIO(service.export(query).lstrip('\ufeff'))))
    assert len(exported)==1 and exported[0]['历史主导角色']=='潜力产品'
    assert exported[0]['历史潜力次数']=='1'


def test_sync_rejects_non_intranet_target_before_any_connection():
    from etl.label_analysis_role_history import sync_role_history
    class WrongDb:
        host='127.0.0.1';database='etl_datasync_test'
        def connect(self):pytest.fail('no connection allowed')
    with pytest.raises(ValueError):sync_role_history(database=WrongDb())


def test_derived_history_role_does_not_change_original_fact_label_coverage():
    row=prepare_rows([sample()],date(2026,10,5),date(2026,10,11))[0]
    row['labels'].append(role_tag(None))
    result=aggregate([row],['labeled_count','unlabeled_count','multiple_label_count'])
    assert result['labeled_count']['value']==0
    assert result['unlabeled_count']['value']==1
    assert result['multiple_label_count']['value']==0
