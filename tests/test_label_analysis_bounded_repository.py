from datetime import date
import json

from app.services.label_analysis_metrics import REPL_FIELDS
from app.services.label_analysis_repository import AnalysisRepository, INVENTORY_COLUMNS, identity, scope_filter
from app.services.label_analysis_traffic import TrafficRows, TRAFFIC_DAILY_FIELDS
from app.services.label_analysis_engine import prepare_rows


END=date(2026,10,12)
SCOPE={'country_category':'欧洲','store':'s','mskus':['A']}


class FakeDB:
    def __init__(self,merged=False):self.queries=[];self.merged=merged
    def connect(self):return self
    def cursor(self):return self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,args=()):self.sql=sql;self.queries.append((sql,args))
    def fetchone(self):return {'d':END}
    def fetchall(self):
        sql=self.sql
        if 'dashboard_label_detail_snapshot' in sql:
            return [dict(label_id=1,label_name='销售角色',sub_label_id=101,sub_label_name='明星产品',status='启用')]
        if 'dashboard_label_fact_snapshot' in sql:
            if 'json_arrayagg' in sql:return [dict(country_category='欧洲',store='s',msku='A',points=json.dumps([['',101,'30d']]))]
            return [dict(country_category='欧洲',store='s',msku='A',country='')]
        if 'dashboard_listing_price_daily_snapshot' in sql:return []
        if 'dashboard_product_performance_daily' in sql:return []
        if 'dashboard_inventory_daily_snapshot' in sql:
            if 'json_arrayagg' in sql:
                fields=['snapshot_date',*sorted(set(INVENTORY_COLUMNS.values()))]
                value=dict(snapshot_date=END.isoformat(),afn_fulfillable_quantity=20,total_price=100)
                return [dict(country_category='欧洲',seller_name_new='s',seller_sku_adj='A',points=[[value.get(field) for field in fields]])]
            return [dict(snapshot_date=END,country_category='欧洲',seller_name_new=store,seller_sku_adj=msku,afn_fulfillable_quantity=qty) for store,msku,qty in [('s','A',20),('t' if self.merged else 's','B',40 if self.merged else 20)]]
        if 'dashboard_pur_plan_replenish_data' in sql:
            fields={value[1] for value in REPL_FIELDS.values()}|{'afn_fulfillable_quantity','asin_merge_flag','asin_merge_target','fllow_flag','follow_origin_link','max_fnsku','max_asin','lead_time_demand_qty'}
            result=[]
            for store,msku,daily in [('s','A',2),('t' if self.merged else 's','B',3)]:
                value={field:None for field in fields}
                value.update(cur_date=END,country_category='欧洲',seller_name_new=store,seller_sku_adj=msku,daily_avg_sales=daily,
                    max_fnsku='' if self.merged else 'shared',max_asin='ASIN',asin_merge_flag=int(self.merged),fllow_flag=1,
                    effective_purchase_lead_days=10,lead_time_demand_qty=30,support_inventory_qty=20,afn_fulfillable_quantity=20)
                result.append(value)
            return result
        return []


class ScopedInputs:
    schema='etl_datasync_test'
    table='input'
    def __init__(self):self.scopes=[]
    def load(self,*args,scope=None):self.scopes.append(scope);return []
    def revision(self):return ()


def repository(db,monkeypatch):
    repo=AnalysisRepository(db);repo.traffic=ScopedInputs();repo.sellable_cost=ScopedInputs()
    monkeypatch.setattr(repo,'_revision',lambda *args:('fixed',))
    monkeypatch.setattr(repo,'_publication_time',lambda *args:'fixed')
    return repo


def test_scope_predicates_are_inside_daily_aggregations(monkeypatch):
    db=FakeDB();repo=repository(db,monkeypatch)
    result=repo.load(END,30,'business_unit',scope=SCOPE)
    assert [row['msku'] for row in result['rows']]==['A']
    assert repo.traffic.scopes==[SCOPE] and repo.sellable_cost.scopes==[SCOPE]
    for sql,args in db.queries:
        if 'json_arrayagg' in sql or ('dashboard_listing_price_daily_snapshot' in sql and 'max(' not in sql) or ('select distinct' in sql and 'dashboard_label_fact_snapshot' in sql):
            assert 'country_category in (%s)' in sql
            assert ' in (%s)' in sql
            assert args[-3:]==('欧洲','s','A')
        if 'dashboard_inventory_daily_snapshot' in sql and 'snapshot_date in (' in sql:
            assert 'country_category in (%s)' in sql
            assert 'seller_sku_adj in (' not in sql
            assert args[:2]==(END,date(2026,9,12))


def test_outside_block_shared_fnsku_demand_is_retained(monkeypatch):
    row=repository(FakeDB(),monkeypatch).load(END,30,'business_unit',scope=SCOPE)['rows'][0]
    assert row['replenishment']['coverage_daily_sales']==5
    assert prepare_rows([row],END,END)[0]['values']['fba_coverage_days']==4
    assert set(row['inventory'])=={END.isoformat()}


def test_cross_store_asin_merge_uses_complete_group_inventory(monkeypatch):
    row=repository(FakeDB(merged=True),monkeypatch).load(END,30,'business_unit',scope=SCOPE)['rows'][0]
    assert row['replenishment']['coverage_daily_sales']==3
    assert row['replenishment']['coverage_inventory_qty']==60
    assert prepare_rows([row],END,END)[0]['values']['fba_coverage_days']==20


def test_outside_block_unmapped_follower_keeps_demand_unknown(monkeypatch):
    class FollowerDB(FakeDB):
        def fetchall(self):
            records=super().fetchall()
            if 'dashboard_pur_plan_replenish_data' in self.sql:records[1]['fllow_flag']=0
            return records
    row=repository(FollowerDB(),monkeypatch).load(END,30,'business_unit',scope=SCOPE)['rows'][0]
    assert row['replenishment']['coverage_daily_sales'] is None
    assert prepare_rows([row],END,END)[0]['values']['fba_coverage_days'] is None


def test_outside_block_conflicting_shared_stock_keeps_cover_unknown(monkeypatch):
    class ConflictDB(FakeDB):
        def fetchall(self):
            records=super().fetchall()
            if 'dashboard_inventory_daily_snapshot' in self.sql and 'json_arrayagg' not in self.sql:
                records[1]['afn_fulfillable_quantity']=30
            return records
    row=repository(ConflictDB(),monkeypatch).load(END,30,'business_unit',scope=SCOPE)['rows'][0]
    assert row['replenishment']['coverage_inventory_qty'] is None
    assert prepare_rows([row],END,END)[0]['values']['fba_coverage_days'] is None


def test_scopes_enumerate_all_sources_without_metric_histories():
    class UniverseDB(FakeDB):
        def fetchall(self):
            source=next(index for index,name in enumerate(('dashboard_label_fact_snapshot','dashboard_listing_price_daily_snapshot','dashboard_product_performance_daily','dashboard_inventory_daily_snapshot','dashboard_pur_plan_replenish_data','dashboard_analysis_traffic_input')) if name in self.sql)
            records=[dict(country_category='欧洲',store='s',msku=f'M{source}-{index}') for index in range(21)]
            return records+[dict(country_category='欧洲',store='s',msku='same'),dict(country_category='欧洲',store='s',msku='SAME')]
    db=UniverseDB();scopes=AnalysisRepository(db).scopes(END)
    assert [len(scope['mskus']) for scope in scopes]==[80,47]
    assert len({identity(s['country_category'],s['store'],m) for s in scopes for m in s['mskus']})==127
    for sql,args in db.queries:
        if sql.startswith('select'):
            assert 'select distinct' in sql and 'json_arrayagg' not in sql
            if 'between' in sql:assert args==(date(2025,10,18),END)


def test_scope_does_not_add_objects_absent_from_short_period(monkeypatch):
    scope={**SCOPE,'mskus':['A','only-in-old-history']}
    rows=repository(FakeDB(),monkeypatch).load(END,7,'business_unit',scope=scope)['rows']
    assert [row['msku'] for row in rows]==['A']


def test_scoped_metadata_and_complete_supply_endpoint_caches_are_small(monkeypatch):
    db=FakeDB();repo=repository(db,monkeypatch)
    for period,view in [(30,'business_unit'),(30,'country'),(7,'business_unit'),(7,'country')]:
        repo.load(END,period,view,scope=SCOPE)
    assert sum('dashboard_label_detail_snapshot' in sql for sql,_ in db.queries)==1
    assert sum('select max(data_date)' in sql for sql,_ in db.queries)==1
    assert sum('select max(snapshot_date)' in sql for sql,_ in db.queries)==1
    for table,column in [('dashboard_inventory_daily_snapshot','snapshot_date'),('dashboard_pur_plan_replenish_data','cur_date')]:
        reads=[args for sql,args in db.queries if table in sql and f'{column} in (' in sql]
        assert reads==[(END,date(2026,9,12),'欧洲'),(date(2026,10,5),'欧洲')]
    assert len(repo._scope_metadata)==1
    assert len(repo._scope_inventory_endpoints)==3
    assert len(repo._scope_replenishment_endpoints)==3


def test_original_case_variants_are_included_for_binary_columns():
    scope={**SCOPE,'category_variants':['欧洲',' 欧洲 '],'store_variants':['s','S'], 'msku_variants':['A','a']}
    sql,args=scope_filter(scope)
    assert sql==' and country_category in (%s,%s) and seller_name_new in (%s,%s) and seller_sku_adj in (%s,%s)'
    assert args==('欧洲',' 欧洲 ','s','S','A','a')


def test_scoped_traffic_identity_matches_existing_tag_spelling(monkeypatch):
    repo=repository(FakeDB(),monkeypatch)
    class Traffic(ScopedInputs):
        def load(self,*args,scope=None):
            return TrafficRows([dict(country_category='欧洲',seller_name_new='S',seller_sku_adj='a',country='',
                points=[[END.isoformat(),*[5]*len(TRAFFIC_DAILY_FIELDS)]])],END.isoformat())
    repo.traffic=Traffic()
    row=repo.load(END,30,'business_unit',scope=SCOPE)['rows'][0]
    assert row['traffic_daily'][END.isoformat()]['sessions_total']==5
    assert row['traffic_coverage_start']==END.isoformat()
