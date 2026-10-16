from collections import defaultdict
from copy import deepcopy
from datetime import date,timedelta
import pytest

from app.services.label_analysis_engine import prepare_rows,aggregate,number,row_business_record,metric_calendar,days_between
from app.services.label_analysis_materialized import MaterializedAnalysisRepository,encode_history,split_row,dumps
from app.services.label_analysis_metrics import METRICS,DAILY_FIELDS
from app.services.label_analysis_service import LabelAnalysisService,AnalysisQuery
from test_label_analysis_engine import sample


class Repository:
    materialized=True
    def __init__(self,raw):self.raw=raw;self.loads=0
    def metadata(self,version=''):
        return {'dates':['2026-10-11'],'published_batch':'batch','categories':[]}
    def load_prepared(self,end,period,view,version):
        self.loads+=1;start=end-timedelta(days=period-1)
        return dict(version=version,prepared=prepare_rows(self.raw,start,end),previous_prepared=prepare_rows(self.raw,start-timedelta(days=period),end-timedelta(days=period)),sources={},warnings=[],categories=[])
    def iter_histories(self,data,rows):
        keys={r['key'] for r in rows}
        yield from (r for r in self.raw if r['key'] in keys)
    def histories(self,*args):pytest.fail('trends must not collect the full archive')


def legacy_series(raw,start,period):
    result=[]
    for d in days_between(start,start+timedelta(days=period-1)):
        point={'date':d,'valid_objects':0,'coverage':{}}
        for field,m in METRICS.items():
            if not m.trend:continue
            if field in DAILY_FIELDS:samples=[number(row_business_record(r,d).get(field)) for r in raw]
            else:
                pools=defaultdict(list)
                for r in raw:
                    snapshot=r.get('replenishment_history',{}).get(d,{})
                    pools[snapshot.get('pool_id',r['pool_id'])].append(number(r['inventory'].get(d)))
                samples=[v[0] if all(x is not None and x>=0 for x in v) and max(v)==min(v) else None for v in pools.values()]
            values=[v for v in samples if v is not None]
            point[field]=sum(values) if values else None
            point['coverage'][field]={'valid_count':len(values),'total_count':len(samples)}
            if field in DAILY_FIELDS:point['coverage'][field]['zero_filled_count']=sum(d not in metric_calendar(r,field) and v is not None for r,v in zip(raw,samples))
            if field=='sales_qty':point['valid_objects']=len(values)
        result.append(point)
    return result


def test_streamed_trends_keep_legacy_coverage_zero_null_and_daily_shared_pool_mapping():
    raw=[sample(),sample('B'),sample('C','p2')]
    raw[1]['inventory']['2026-10-09']=6  # Shared pool conflict.
    raw[1]['inventory']['2026-10-10']=-1
    raw[1]['replenishment_history']={'2026-10-11':{'pool_id':'p2'}}
    raw[2]['traffic_daily']={'2026-10-10':{'sessions_total':None,'page_views':20}}
    raw[2]['traffic_coverage_start']='2026-10-09'
    raw[2]['unavailable_daily_fields']=['ad_spend']
    service=LabelAnalysisService(Repository(raw));q=AnalysisQuery(period=7)
    result=service.trends(q)
    assert result['current']==legacy_series(raw,date(2026,10,5),7)
    assert result['previous']==legacy_series(raw,date(2026,9,28),7)
    assert result['current'][-1]['coverage']['ending_inventory_qty']=={'valid_count':2,'total_count':2}


def test_only_one_materialized_dataset_is_retained_and_old_pin_can_reload():
    repository=Repository([sample()]);service=LabelAnalysisService(repository)
    for period in (7,14,30,60,90,180):
        service._dataset(AnalysisQuery(period=period))
        assert len(service._cache)==1
    service._dataset(AnalysisQuery(period=7,version='batch'))
    assert repository.loads==7
    assert not service._load_locks


def test_precomputed_default_summaries_are_used_without_losing_custom_scope(monkeypatch):
    repo=Repository([sample()]);original=repo.load_prepared
    def load(*args):
        data=original(*args);totals=aggregate(data['prepared']);totals['sales_amount']['value']=987654
        data['tag_summaries']={('all',0,0):totals}
        return data
    repo.load_prepared=load;service=LabelAnalysisService(repo)
    result=service.summary(AnalysisQuery(period=7))
    assert result['current']['sales_amount']['value']==987654
    assert result['parent']['sales_amount']['value']==987654
    assert service.summary(AnalysisQuery(period=7,stores=['S']))['current']['sales_amount']['value']==300
    assert LabelAnalysisService._summary_preset(AnalysisQuery(conditions=[{'kind':'metric','metric':'fba_coverage_days','op':'gt','value':180}]))=='over180'
    assert LabelAnalysisService._summary_preset(AnalysisQuery(conditions=[{'kind':'metric','metric':'fba_coverage_days','op':'gte','value':180}])) is None


def test_archive_reader_bounds_chunks_pins_batch_and_rejects_missing_record():
    calls=[];blob,checksum=encode_history(sample());missing=False
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,args):
            assert args[0]=='pinned';self.ids=args[1:];calls.append(len(self.ids))
        def fetchall(self):return [{'object_id':oid,'payload':blob,'checksum':checksum} for oid in self.ids if not missing or oid!=81]
    class Conn:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def cursor(self):return Cursor()
    class DB:
        def connect(self):return Conn()
    repository=MaterializedAnalysisRepository(DB());rows=[{'_object_id':i} for i in range(82)]
    assert sum(1 for _ in repository.iter_histories({'version':'pinned'},rows))==82
    assert calls==[40,40,2]
    missing=True
    with pytest.raises(ValueError,match='不完整'):list(repository.iter_histories({'version':'pinned'},rows))


def test_scalar_reader_uses_bounded_fetches_instead_of_a_second_full_result_list():
    context,domains=split_row(prepare_rows([sample()],date(2026,10,5),date(2026,10,11))[0])
    payload={'context_json':dumps(context),**{key:dumps(value) for key,value in domains.items()}}
    class Cursor:
        pending=81
        def execute(self,sql,args):assert args==('batch',date(2026,10,11),7,'country','current')
        def fetchall(self):pytest.fail('the scalar result must be streamed')
        def fetchmany(self,size):
            assert size==40
            count=min(size,self.pending);self.pending-=count
            return [payload for _ in range(count)]
    restored=MaterializedAnalysisRepository._rows(Cursor(),'batch',date(2026,10,11),7,'country','current')
    assert len(restored)==81
    assert restored[0]['values']==prepare_rows([sample()],date(2026,10,5),date(2026,10,11))[0]['values']
