from copy import deepcopy
from datetime import date,timedelta
import pytest
from app.services.label_analysis_engine import prepare_rows,aggregate
from app.services.label_analysis_materialized import split_row,join_row,encode_history,decode_history,DOMAIN_FIELDS,dumps
from app.services.label_analysis_service import LabelAnalysisService,AnalysisQuery
from test_label_analysis_engine import sample


def test_domain_results_roundtrip_keeps_all_metrics_ratios_and_shared_pool():
    raw=[sample(),sample('B','p1',sales=10)]
    prepared=prepare_rows(raw,date(2026,10,9),date(2026,10,11))
    restored=[]
    for row in prepared:
        context,domains=split_row(row)
        restored.append(join_row(dumps(context),{key:dumps(value) for key,value in domains.items()}))
    assert aggregate(restored)==aggregate(prepared)
    assert set(DOMAIN_FIELDS)=={'business','traffic','stockout','inventory'}


def test_history_archive_preserves_zero_null_and_rejects_corruption():
    row=sample();row['inventory']['2026-10-10']=None
    blob,checksum=encode_history(row)
    assert decode_history(blob,checksum)==row
    with pytest.raises(ValueError):decode_history(blob,'0'*64)


def test_all_web_endpoints_never_prepare_or_read_source(monkeypatch):
    import app.services.label_analysis_service as module
    raw=[sample(labels=[{'id':101,'parent_id':1}])]
    prepared=prepare_rows(raw,date(2026,10,5),date(2026,10,11))
    previous=prepare_rows(raw,date(2026,9,28),date(2026,10,4))
    class Repository:
        materialized=True
        calls=0
        def metadata(self):return {'published_batch':'frozen-batch','dates':['2026-10-11'],'categories':[{'id':1,'children':[{'id':101,'label':'明星'}],'label':'销售角色'}]}
        def load_prepared(self,end,period,view,version=''):
            self.calls+=1
            return {'version':'frozen-batch','prepared':deepcopy(prepared),'previous_prepared':deepcopy(previous),'rows':[], 'sources':{'labels':'2026-10-11','label_publication_time':'fixed'},'warnings':[],'categories':self.metadata()['categories']}
        def histories(self,data,rows):return raw
        def evidence(self,*args):return []
        def load(self,*args):raise AssertionError('must not load business sources')
        def source_connect(self,*args):raise AssertionError('must not connect source')
    def forbid(*args):raise AssertionError('must not prepare during a web request')
    monkeypatch.setattr(module,'prepare_rows',forbid)
    service=LabelAnalysisService(Repository())
    query=AnalysisQuery(data_date='2026-10-11',period=7)
    result=service.summary(query)
    pinned=query.model_copy(update={'version':result['version']})
    assert service.details(pinned)['total']==1
    assert len(service.trends(pinned)['current'])==7
    assert 'A' in service.export(pinned)
    assert service.details(pinned.model_copy(update={'object_key':'A'}))['rows'][0]['history'][-1]['inventory']==0
    assert service.repository.calls==1


def test_prepared_input_aggregation_keeps_null_negative_and_country_components():
    from etl.label_analysis_inputs import combine_points
    assert combine_points([['2026-10-11',2,3],['2026-10-11',5,None],['2026-10-12',-1,4]])==[
        ['2026-10-11',7,None],['2026-10-12',None,4]]


def test_traffic_sync_covers_unloaded_gap_and_historical_source_changes():
    from etl.label_analysis_inputs import traffic_sync_start
    revision=('schema','table','2026-10-12')
    start=date(2025,10,18);end=date(2026,10,12)
    state={'first_loaded':start,'last_loaded':date(2026,8,1),'coverage_start':date(2025,12,11),'source_revision':list(revision)}
    assert traffic_sync_start(state,start,end,30,revision,'2025-12-11')==date(2026,8,2)
    assert traffic_sync_start(state,start,end,30,(*revision[:2],'changed'),'2025-12-11')==start


def test_refresh_follows_new_published_date_and_old_pin_uses_its_own_date():
    class Repository:
        materialized=True
        def metadata(self,version=''):
            return {'dates':['2026-10-11' if version=='old' else '2026-10-12'],'published_batch':version or 'new'}
        def load_prepared(self,end,period,view,version):
            assert end.isoformat()==('2026-10-11' if version=='old' else '2026-10-12')
            return {'version':version}
    service=LabelAnalysisService(Repository())
    assert service._dataset(AnalysisQuery(data_date='2026-10-11',force_refresh=True))['date']==date(2026,10,12)
    assert service._dataset(AnalysisQuery(version='old'))['date']==date(2026,10,11)


def test_partial_window_cannot_replace_global_publication(monkeypatch):
    import etl.label_analysis_refresh as module
    monkeypatch.setattr(module,'ensure_schema',lambda:pytest.fail('partial publication must fail before DB changes'))
    with pytest.raises(ValueError,match='全部六个周期'):module.refresh(periods=[7])


def test_expired_pin_without_date_retains_recovery_error():
    from app.services.label_analysis_materialized import PreparedVersionMissing
    from app.services.label_analysis_service import StaleAnalysis
    class Repository:
        materialized=True
        def metadata(self,version=''):
            if version:raise PreparedVersionMissing('missing')
            return {'dates':['2026-10-12'],'published_batch':'new'}
    with pytest.raises(StaleAnalysis):LabelAnalysisService(Repository())._dataset(AnalysisQuery(version='old'))


def test_longest_archive_keeps_every_short_period_inventory_mapping():
    from etl.label_analysis_refresh import ResultWriter
    records={}
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,query,args):self.ids=args[1:]
        def fetchall(self):return [{'object_id':oid,'payload':records[oid][0],'checksum':records[oid][1]} for oid in self.ids]
        def executemany(self,query,rows):
            for blob,checksum,batch,oid in rows:records[oid]=(blob,checksum)
    class Conn:
        def cursor(self):return Cursor()
    writer=ResultWriter(Conn(),'batch',date(2026,10,12));writer.ids['country','A']=1
    def insert(table,columns,rows):
        for batch,oid,blob,checksum in rows:records[oid]=(blob,checksum)
    writer.insert=insert
    raw=sample();raw['replenishment_history']={'2026-10-12':{'pool_id':'shared'},'2026-04-15':{'pool_id':'shared-old'}}
    writer.histories([raw],'country')
    shorter=deepcopy(raw);shorter['daily']={};shorter['replenishment_history']={'2026-10-05':{'pool_id':'short-shared'}}
    writer.histories([shorter],'country');writer.finish_histories()
    restored=decode_history(*records[1])
    assert restored['daily']==raw['daily']
    assert restored['replenishment_history']['2026-10-05']['pool_id']=='short-shared'
