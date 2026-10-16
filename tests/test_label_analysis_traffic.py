from datetime import date
from copy import deepcopy
import pytest
from app.services.label_analysis_engine import prepare_rows,aggregate
from app.services.label_analysis_metrics import METRICS
from test_label_analysis_engine import sample


def test_product_conversion_uses_pooled_orders_and_sessions_not_ad_clicks_or_average():
    a=sample(sales=20);b=sample('B','p2',sales=5)
    for row,sessions,orders,pv in [(a,100,10,140),(b,10,5,18)]:
        row['daily']['2026-10-10'].update(sessions_total=sessions,order_count=orders,page_views=pv,traffic_sales_qty=row['daily']['2026-10-10']['sales_qty'],ad_clicks=2)
    totals=aggregate(prepare_rows([a,b],date(2026,10,9),date(2026,10,11)))
    assert totals['page_views']['value']==158
    assert totals['order_count']['value']==15
    assert totals['order_conversion']['value']==pytest.approx(15/110)
    assert totals['product_conversion']['value']==pytest.approx(25/110)
    assert totals['order_conversion']['status']=='available'
    assert METRICS['product_conversion'].unit=='percent'
    assert METRICS['order_conversion'].denominator=='sessions_total'


def test_total_traffic_uses_one_source_batch_and_keeps_operating_snapshot_unchanged():
    from app.services.label_analysis_traffic import attach_traffic,PRODUCT_TRAFFIC_FIELDS
    from app.services.label_analysis_engine import row_business_record
    row=sample();row['country_category']='欧洲站';row['daily']['2026-10-10'].update(sessions_total=100,sales_qty=30)
    source={'country_category':'欧洲站','seller_name_new':'S','seller_sku_adj':'A','points':[['2026-10-10',100,30,7,60,40,140,90,50],['2026-10-11',4,1,1,2,2,6,3,3]]}
    attach_traffic([row],[source],'business_unit')
    assert row_business_record(row,'2026-10-10')['order_count']==7
    assert row_business_record(row,'2026-10-10')['page_views']==140
    # Recent source backfills must be reflected even if the operating snapshot is older.
    assert row_business_record(row,'2026-10-11')['page_views']==6
    assert row_business_record(row,'2026-10-11')['traffic_sales_qty']==1
    assert row_business_record(row,'2026-10-11')['sales_qty']==0
    assert row_business_record(row,'2026-10-09')['page_views']==0
    changed=deepcopy(source);changed['points'][0][1]=101
    attach_traffic([row],[changed],'business_unit')
    assert row_business_record(row,'2026-10-10')['sessions_total']==101
    assert row['daily']['2026-10-10']['sessions_total']==100
    row['unavailable_daily_fields']=list(PRODUCT_TRAFFIC_FIELDS)
    assert row_business_record(row,'2026-10-09')['page_views'] is None
    assert row_business_record(row,'2026-10-09')['sales_qty']==0


def test_source_query_is_daily_bounded_country_aware_and_does_not_average_cvr(monkeypatch):
    from app.services.label_analysis_traffic import ProductTrafficRepository
    monkeypatch.delenv('DASHBOARD_DWD_SOURCE_SCHEMA',raising=False)
    class DB:
        statements=[]
        def source_connect(self,**kwargs):return self
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,args=None):self.statements.append((sql,args))
        def fetchall(self):return []
        def fetchone(self):return {'first_day':date(2026,1,1)}
    db=DB();repo=ProductTrafficRepository(db)
    repo.load(date(2026,10,12),30,'country')
    sql,args=db.statements[-1]
    assert args==('2026-08-14','2026-10-13')
    assert 'end_date=start_date' in sql and 'page_views_total as page_views' in sql and 'sum(page_views)' in sql
    assert 'avg(' not in sql and 'volume_cvr' not in sql
    assert 'country_category,seller_name_new,seller_sku_adj,country' in sql
    assert all(s.lstrip().startswith(('select','set transaction','start transaction')) for s,_ in db.statements)


def test_country_join_keeps_country_totals_separate_and_unavailable_feed_stays_unknown():
    from app.services.label_analysis_traffic import attach_traffic,PRODUCT_TRAFFIC_FIELDS
    a=sample();b=deepcopy(a);b.update(key='B',country='法国')
    sources=[{'country_category':a['country_category'],'seller_name_new':'S','seller_sku_adj':'A','country':country,'points':[['2026-10-10',100,30,orders,60,40,pv,90,50]]} for country,orders,pv in [('德国',5,140),('法国',9,180)]]
    attach_traffic([a,b],sources,'country')
    rows=prepare_rows([a,b],date(2026,10,9),date(2026,10,11))
    assert rows[0]['values']['order_count']==5 and rows[1]['values']['order_count']==9
    assert aggregate(rows)['page_views']['value']==320
    a['daily']={};a['unavailable_daily_fields']=list(PRODUCT_TRAFFIC_FIELDS)
    row=prepare_rows([a],date(2026,10,9),date(2026,10,11))[0]
    assert row['values']['page_views'] is None
    assert row['observed_days']['page_views']==row['effective_days']['page_views']==0
    assert row['values']['sales_qty']==0
