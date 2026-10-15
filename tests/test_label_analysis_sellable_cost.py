from datetime import date
from copy import deepcopy
from types import SimpleNamespace

from app.services.label_analysis_inventory import SellableCostRepository,aligned_sellable_cost
from app.services.label_analysis_engine import prepare_rows,aggregate
from test_label_analysis_engine import sample


def pool(qty=10,total=100):
    return {'inventory':{'2026-10-12':qty},'costs':{'2026-10-12':total}}


def test_cost_uses_explicit_source_only_after_same_date_quantity_and_total_match():
    source={'quantity':10,'total_cost':100,'sellable_cost':60}
    assert aligned_sellable_cost(source,pool(),'2026-10-12')==60
    assert aligned_sellable_cost({**source,'sellable_cost':None},pool(),'2026-10-12') is None
    assert aligned_sellable_cost(source,pool(qty=11),'2026-10-12') is None
    assert aligned_sellable_cost(source,pool(total=101),'2026-10-12') is None
    assert aligned_sellable_cost(source,pool(),'2026-10-11') is None
    assert aligned_sellable_cost({**source,'sellable_cost':-1},pool(),'2026-10-12') is None
    assert aligned_sellable_cost({'quantity':0,'total_cost':0,'sellable_cost':0},pool(0,0),'2026-10-12')==0


def test_exact_date_cost_deduplicates_shared_country_pool_and_keeps_conflicts_unknown():
    raw=sample();raw['sellable_cost_history']={'2026-10-10':55,'2026-10-11':60}
    other=deepcopy(raw);other.update(key='B',msku='B',country='法国')
    rows=prepare_rows([raw,other],date(2026,10,9),date(2026,10,11))
    assert aggregate(rows)['sellable_inventory_cost']['value']==60
    assert rows[0]['values']['inventory_cost'] is None
    other['sellable_cost_history']['2026-10-11']=61
    assert aggregate(prepare_rows([raw,other],date(2026,10,9),date(2026,10,11)))['sellable_inventory_cost']['value'] is None
    assert prepare_rows([raw],date(2026,10,9),date(2026,10,10))[0]['values']['sellable_inventory_cost']==55
    assert prepare_rows([raw],date(2026,10,9),date(2026,10,12))[0]['values']['sellable_inventory_cost'] is None


def test_source_read_is_exact_date_null_preserving_and_non_mutating(monkeypatch):
    monkeypatch.delenv('DASHBOARD_ETL_SOURCE_SCHEMA',raising=False)
    class DB:
        schemas=SimpleNamespace(etl_source_schema='etl_datasync_test')
        statements=[]
        def source_connect(self,**kwargs):return self
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,args=None):self.statements.append((sql,args))
        def fetchall(self):return []
        def fetchone(self):return {'update_time':'published'}
    db=DB();repo=SellableCostRepository(db)
    assert repo.schema=='etl_datasync'
    assert repo.revision()[-1]=='published'
    repo.load(date(2026,10,12),30)
    sql,args=db.statements[-1]
    assert 'count(*)=count(afn_fulfillable_quantity_price)' in sql
    assert 'sum(afn_fulfillable_quantity_price)' in sql and 'sum(coalesce(afn_fulfillable_quantity_price' not in sql
    assert args==(date(2026,10,12),date(2026,10,13),date(2026,9,12),date(2026,9,13))
    assert all(sql.lstrip().startswith(('select','set transaction','start transaction')) for sql,args in db.statements)
