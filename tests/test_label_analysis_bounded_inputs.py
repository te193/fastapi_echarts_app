from datetime import date,timedelta
import json
import pytest

from etl.label_analysis_inputs import (
    PreparedTrafficInputs,PreparedCostInputs,bounded_scope,date_blocks,
)


END=date(2026,10,12)
REVISION=('dwd_datasync','lx_statistics_product_performance','2026-10-12 01:00:00')
PERIODS=[7,14,30,60,90,180]
SCOPE={'country_category':'欧洲站','store':'CHOOJEE','mskus':['A','B']}


class Cursor:
    def __init__(self,db):self.db=db;self.query=''
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,query,args=None):
        self.query=query;self.args=args;self.db.queries.append((query,args))
    def fetchone(self):
        if 'information_schema.statistics' in self.query:return {'found':1}
        if 'min(start_date)' in self.query:return {'first_day':date(2025,12,11)}
        return self.db.states.get(self.args[0])
    def fetchall(self):return self.db.rows


class Connection:
    def __init__(self,db):self.db=db
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def cursor(self):return Cursor(self.db)
    def commit(self):self.db.commits+=1


class Database:
    database='etl_datasync_test'
    def __init__(self,states=None,rows=None,source_allowed=False):
        self.states=states or {};self.rows=rows or [];self.queries=[];self.commits=0
        self.source_allowed=source_allowed
    def connect(self):return Connection(self)
    def source_connect(self,*args,**kwargs):
        if not self.source_allowed:raise AssertionError('worker must never query remote sources')
        return Connection(self)


def traffic_state():
    return {'first_loaded':END-timedelta(days=359),'last_loaded':END,
        'coverage_start':date(2025,12,11),'source_revision':json.dumps(REVISION)}


def cost_state(periods=PERIODS):
    dates=sorted({END,*[END-timedelta(days=period) for period in periods]})
    return {'first_loaded':dates[0],'last_loaded':END,
        'source_revision':json.dumps([*REVISION,*[day.isoformat() for day in dates]])}


def test_scope_is_mandatory_bounded_and_preserves_product_identity():
    for invalid in [None,{}, {**SCOPE,'mskus':[]},{**SCOPE,'mskus':['']},{**SCOPE,'mskus':['A']*2+[str(i) for i in range(81)]}]:
        with pytest.raises(ValueError):bounded_scope(invalid)
    assert bounded_scope({**SCOPE,'mskus':['B','A','A']})==('欧洲站','CHOOJEE',('A','B'))


def test_traffic_worker_reads_only_bounded_target_and_merges_country_nulls():
    db=Database({'traffic':traffic_state()},[
        {'country_category':'欧洲站','country':'德国','seller_name_new':'CHOOJEE','seller_sku_adj':'A','points_json':'["2026-10-12",2,3]'},
        {'country_category':'欧洲站','country':'法国','seller_name_new':'CHOOJEE','seller_sku_adj':'A','points_json':'["2026-10-12",5,null]'},
    ])
    adapter=PreparedTrafficInputs.from_prepared(db,END)
    assert not hasattr(adapter,'frames')
    country=adapter.load(END,180,'country',SCOPE)
    assert len(country)==2
    unit=adapter.load(END,180,'business_unit',SCOPE)
    assert unit[0]['points']==[['2026-10-12',7,None]]
    query,args=db.queries[-1]
    assert 'country_category in' in query and 'store in' in query and 'msku in' in query
    assert args==(END-timedelta(days=359),END,'欧洲站','CHOOJEE','A','B')
    assert unit.coverage_start=='2025-12-11'
    assert all('select'==query.strip().split()[0] for query,_ in db.queries)


def test_traffic_worker_rejects_partial_state_and_range_gap():
    for state in [None,{**traffic_state(),'last_loaded':END-timedelta(days=1)},
            {**traffic_state(),'source_revision':json.dumps(['syncing',*REVISION])}]:
        with pytest.raises(RuntimeError):PreparedTrafficInputs.from_prepared(Database({'traffic':state}),END)


def test_input_spelling_variants_cannot_expand_scope_and_merge_same_identity():
    scope={**SCOPE,'store_variants':['CHOOJEE','choojee '],'msku_variants':['A','a ','B']}
    assert bounded_scope(scope)==('欧洲站','CHOOJEE',('A','B'))
    with pytest.raises(ValueError):bounded_scope({**scope,'msku_variants':['unrelated']})
    db=Database({'traffic':traffic_state()},[
        {'country_category':'欧洲站','country':'德国','seller_name_new':'CHOOJEE','seller_sku_adj':'A','points_json':'["2026-10-12",2,3]'},
        {'country_category':'欧洲站','country':'德国','seller_name_new':'choojee ','seller_sku_adj':'a ','points_json':'["2026-10-12",5,null]'},
    ])
    adapter=PreparedTrafficInputs.from_prepared(db,END)
    result=adapter.load(END,30,'country',scope)
    assert len(result)==1 and result[0]['points']==[['2026-10-12',7,None]]
    assert db.queries[-1][1]==(END-timedelta(days=59),END,'欧洲站','CHOOJEE','choojee ','A','a ','B')


def test_cost_worker_reads_exact_cutoffs_from_target_and_requires_all_dates():
    row={'snapshot_date':END,'quantity':10,'total_cost':100,'sellable_cost':80}
    db=Database({'cost':cost_state()},[row])
    adapter=PreparedCostInputs.from_prepared(db,END,PERIODS)
    assert adapter.load(END,30,SCOPE)==[row]
    query,args=db.queries[-1]
    assert 'snapshot_date in (%s,%s)' in query
    assert args==(END,END-timedelta(days=30),'欧洲站','CHOOJEE','A','B')
    assert all('select'==query.strip().split()[0] for query,_ in db.queries)
    with pytest.raises(RuntimeError):PreparedCostInputs.from_prepared(Database({'cost':cost_state([7,30])}),END,PERIODS)


def test_cost_fetch_uses_configured_source_and_one_day_only():
    row={'snapshot_date':END,'quantity':10,'total_cost':100,'sellable_cost':80}
    db=Database(rows=[row],source_allowed=True)
    adapter=PreparedCostInputs.__new__(PreparedCostInputs);adapter.db=db
    adapter.original=type('Source',(),{'schema':'etl_datasync','table':'warehouse'})()
    assert adapter._fetch(END)==[row]
    query,args=db.queries[-1]
    assert 'etl_datasync.warehouse' in query
    assert args==(END,END+timedelta(days=1))
    assert all(query.lstrip().startswith(('select','set','start')) for query,_ in db.queries)


@pytest.mark.parametrize('domain',['traffic','cost'])
def test_prepared_generation_distinguishes_syncs_without_source_timestamp(domain):
    no_timestamp=(*REVISION[:2],'')
    adapters=[]
    for generation in ['2026-10-14 01:00:00.000001','2026-10-14 01:00:00.000002']:
        state=traffic_state() if domain=='traffic' else cost_state()
        marker=json.loads(state['source_revision']);marker[:3]=no_timestamp
        state.update(source_revision=json.dumps(marker),updated_at=generation)
        db=Database({domain:state})
        adapter=(PreparedTrafficInputs.from_prepared(db,END) if domain=='traffic'
            else PreparedCostInputs.from_prepared(db,END,PERIODS))
        adapters.append(adapter)
        assert adapter.revision()==no_timestamp
    assert adapters[0].input_generation!=adapters[1].input_generation


def test_date_blocks_cover_every_day_without_overlap():
    blocks=list(date_blocks(END-timedelta(days=16),END))
    assert [int((stop-start).days)+1 for start,stop in blocks]==[7,7,3]
    assert blocks[0][0]==END-timedelta(days=16) and blocks[-1][1]==END
    assert all(right[0]==left[1]+timedelta(days=1) for left,right in zip(blocks,blocks[1:]))


def test_reusable_traffic_constructor_does_not_load_full_history(monkeypatch):
    import etl.label_analysis_inputs as module
    class Original:
        schema='dwd_datasync';table='product'
        def __init__(self,db):pass
        def revision(self):return REVISION
    monkeypatch.setattr(module,'ProductTrafficRepository',Original)
    db=Database({'traffic':traffic_state()},source_allowed=True)
    adapter=PreparedTrafficInputs(db,END)
    assert not hasattr(adapter,'frames')
    assert not any('points_json' in query and query.lstrip().startswith('select') for query,_ in db.queries)
    assert not any(query.lstrip().startswith('delete') for query,_ in db.queries)


@pytest.mark.parametrize('domain',['traffic','cost'])
def test_reuse_detects_revision_changed_during_metadata_read(monkeypatch,domain):
    import etl.label_analysis_inputs as module
    class Original:
        schema='dwd_datasync';table='product'
        def __init__(self,db):self.calls=0
        def revision(self):
            self.calls+=1
            return REVISION if self.calls==1 else (*REVISION[:2],'changed')
    if domain=='traffic':
        monkeypatch.setattr(module,'ProductTrafficRepository',Original)
        with pytest.raises(RuntimeError,match='发生变化'):
            PreparedTrafficInputs(Database({'traffic':traffic_state()},source_allowed=True),END)
    else:
        monkeypatch.setattr(module,'SellableCostRepository',Original)
        with pytest.raises(RuntimeError,match='发生变化'):
            PreparedCostInputs(Database({'cost':cost_state()}),END,PERIODS)


def test_failed_second_sync_block_never_promotes_completeness_marker(monkeypatch):
    import etl.label_analysis_inputs as module
    class Original:
        schema='dwd_datasync';table='product'
        def __init__(self,db):pass
        def revision(self):return REVISION
    monkeypatch.setattr(module,'ProductTrafficRepository',Original)
    calls=[];stored=[]
    def fetch(self,start,end):
        calls.append((start,end))
        if len(calls)==2:raise RuntimeError('simulated source failure')
        return []
    monkeypatch.setattr(PreparedTrafficInputs,'_fetch',fetch)
    monkeypatch.setattr(PreparedTrafficInputs,'_store_block',lambda self,start,end,rows:stored.append((start,end)))
    db=Database({'traffic':{**traffic_state(),'source_revision':json.dumps([*REVISION[:2],'older'])}},source_allowed=True)
    with pytest.raises(RuntimeError,match='simulated'):PreparedTrafficInputs(db,END,progress=lambda info:None)
    assert len(calls)==2 and len(stored)==1
    writes=[(query,args) for query,args in db.queries if query.lstrip().startswith(('update','insert'))]
    assert len(writes)==1 and json.loads(writes[0][1][0])[0]=='syncing'
