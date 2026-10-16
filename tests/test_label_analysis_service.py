import csv, io
from datetime import date
import pytest
from app.services.label_analysis_service import LabelAnalysisService, AnalysisQuery, StaleAnalysis
from test_label_analysis_engine import sample


class Repo:
    calls=0
    def metadata(self):
        return {'dates':['2026-10-11'], 'categories':[{'id':1,'label':'销售角色','children':[{'id':101,'label':'明星'},{'id':102,'label':'潜力'}]}]}
    def load(self, end, days, view):
        self.calls+=1
        a=sample(labels=[{'id':101,'parent_id':1}]); b=sample('B','p2',labels=[{'id':102,'parent_id':1}])
        return {'rows':[a,b], 'categories':self.metadata()['categories'], 'sources':{}, 'warnings':[]}


def test_summary_details_export_same_membership_and_version():
    s=LabelAnalysisService(Repo()); q=AnalysisQuery(data_date='2026-10-11',period=7,conditions=[{'kind':'label','parent_id':1,'ids':[101]}])
    p=s.summary(q)
    assert p['current']['object_count']['value']==1
    assert p['baseline']['object_count']['value']==2
    q=q.model_copy(update={'version':p['version']})
    assert s.details(q)['total']==1
    text=s.export(q)
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    assert len(rows)==2 and 'A' in rows[1]
    assert s.repository.calls==1


def test_invalid_metric_and_duplicate_parent_rejected():
    with pytest.raises(ValueError): AnalysisQuery(conditions=[{'kind':'metric','metric':'drop table','op':'gt','value':0}])
    with pytest.raises(ValueError): AnalysisQuery(conditions=[{'kind':'label','parent_id':1,'ids':[101]},{'kind':'label','parent_id':1,'ids':[102]}])


def test_unknown_version_requires_reload_not_silent_mixing():
    s=LabelAnalysisService(Repo())
    with pytest.raises(StaleAnalysis): s.details(AnalysisQuery(data_date='2026-10-11',version='expired'))


def test_trends_keep_current_members_and_do_not_use_daily_labels():
    s=LabelAnalysisService(Repo()); q=AnalysisQuery(data_date='2026-10-11',period=7,conditions=[{'kind':'label','parent_id':1,'ids':[101]}])
    t=s.trends(q)
    assert t['member_count']==1
    assert len(t['current'])==7 and len(t['previous'])==7
    assert t['current'][-2]['sales_qty']==30
    assert t['previous'][0]['sales_qty']==0


def test_csv_escapes_formula_identity():
    repo=Repo(); original=repo.load
    def load(*args):
        p=original(*args); p['rows'][0]['msku']='=1+1'; return p
    repo.load=load
    s=LabelAnalysisService(repo)
    assert "'=1+1" in s.export(AnalysisQuery(data_date='2026-10-11'))


def test_cached_aggregates_do_not_mutate_baseline_or_previous_period():
    s=LabelAnalysisService(Repo()); q=AnalysisQuery(data_date='2026-10-11',period=7)
    full=s.summary(q)
    selected=q.model_copy(update={'version':full['version'],'conditions':AnalysisQuery(conditions=[{'kind':'label','parent_id':1,'ids':[101]}]).conditions})
    narrow=s.summary(selected)
    assert narrow['current']['object_count']['overall_share']==.5
    again=s.summary(q.model_copy(update={'version':full['version']}))
    assert again['current']['object_count']['overall_share']==1
    assert again['current']['sales_qty']['value']==60
    assert again['previous']['sales_qty']['value']==0
    assert s.repository.calls==1
