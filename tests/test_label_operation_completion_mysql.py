from datetime import date
import json
import pytest
from test_label_local_store_mysql import local_store
from etl.label_local_store import table
from etl.label_operation_completion import complete_operations,VERSION


def seed(conn,schema,available=0,status='RECEIVING'):
    with conn.cursor() as q:
        q.execute(f'''create table {table(schema,'dashboard_label_source_shipment')} (
            id int,msku varchar(100),seller varchar(100),country varchar(50),shipment_id varchar(100),
            shipment_status varchar(30),gmt_modified varchar(30),working_time varchar(30),gmt_create varchar(30),create_time varchar(30))''')
        q.execute(f'''create table {table(schema,'dashboard_label_source_fba')} (
            seller_sku_adj varchar(100),seller_name_new varchar(100),country_category varchar(50),
            create_time datetime,afn_fulfillable_quantity int,stock_up_num int)''')
        q.execute(f'''insert into {table(schema,'dashboard_label_source_shipment')} values
            (1,'SKU','SHOP-DE','德国','SHIP','RECEIVING','2026-10-01',null,null,null),
            (2,'SKU','SHOP-DE','德国','SHIP',%s,'2026-10-02',null,null,null)''',(status,))
        q.execute(f'''insert into {table(schema,'dashboard_label_source_fba')} values
            ('SKU','SHOP-DE','欧洲站','2026-10-07',%s,0),
            ('SKU','SHOP-DE','欧洲站','2026-10-08',99,0)''',(available,))
        q.execute(f'''insert into {table(schema,'dashboard_label_local_work')}
            (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_json) values
            ('2026-10-07','欧洲站',null,'SHOP','SKU',101,'30d',now(),json_object()),
            ('2026-10-07','欧洲站',null,'OTHER','SKU',101,'30d',now(),json_object()),
            ('2026-10-07','欧洲站',null,'OTHER','SKU',301,'current',now(),json_object('original',1))''')
    conn.commit()


def test_receiving_completes_gap_preserves_other_store_and_is_idempotent(local_store):
    conn,schema=local_store
    seed(conn,schema)
    assert complete_operations(conn,schema,date(2026,10,7))['operation_added_rows']==1
    assert complete_operations(conn,schema,date(2026,10,7))['operation_added_rows']==0
    with conn.cursor() as q:
        q.execute(f"select store,label_id,evidence_json from {table(schema,'dashboard_label_local_work')} where label_id between 301 and 307 order by store")
        other,new=q.fetchall()
        assert other['store']=='OTHER' and other['label_id']==301 and json.loads(other['evidence_json'])=={'original':1}
        evidence=json.loads(new['evidence_json'])
        assert new['label_id']==304 and evidence['rule_version']==VERSION
        assert evidence['metrics']['fba_available']==0 and evidence['metrics']['receiving_shipment_ids']==['SHIP']


@pytest.mark.parametrize('available,status',[(1,'RECEIVING'),(0,'CLOSED')])
def test_positive_inventory_or_stale_receiving_cannot_be_filled(local_store,available,status):
    conn,schema=local_store
    seed(conn,schema,available,status)
    with pytest.raises(RuntimeError,match='does not match'):
        complete_operations(conn,schema,date(2026,10,7))
