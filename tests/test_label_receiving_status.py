from datetime import date
import pytest
from test_label_local_store_mysql import local_store
from test_label_operation_completion_mysql import seed
from etl.label_local_store import table

def test_first_wave_receiving_is_separate_from_old_stockout():
    from etl.label_receiving_status import receiving_classification
    assert receiving_classification(1,False,None,date(2026,10,8))==308
    assert receiving_classification(1,False,date(2026,10,9),date(2026,10,8))==308
    assert receiving_classification(2,False,None,date(2026,10,8))==304
    assert receiving_classification(1,True,None,date(2026,10,8))==304
    assert receiving_classification(1,False,date(2025,10,1),date(2026,10,8))==304

@pytest.mark.parametrize('prior_stock,second_shipment,expected',[(False,False,308),(True,False,304),(False,True,304)])
def test_receiving_classification_database_and_repeat(local_store,prior_stock,second_shipment,expected):
    from etl.label_operation_completion import complete_operations
    from etl.label_receiving_status import apply_receiving_status
    conn,schema=local_store
    seed(conn,schema)
    with conn.cursor() as q:
        q.execute(f"delete from {table(schema,'dashboard_label_source_dictionary')}")
        q.execute(f"alter table {table(schema,'dashboard_label_source_shipment')} add receiving_time varchar(64)")
        if prior_stock:
            q.execute(f"insert into {table(schema,'dashboard_label_source_fba')} values('SKU','SHOP-DE','欧洲站','2026-10-06',2,0)")
        if second_shipment:
            q.execute(f"insert into {table(schema,'dashboard_label_source_shipment')} values(3,'SKU','SHOP-DE','德国','OTHER_SHIP','CLOSED','2026-10-01',null,null,null,'2026-09-01')")
    day=date(2026,10,7)
    complete_operations(conn,schema,day)
    apply_receiving_status(conn,schema,day)
    assert complete_operations(conn,schema,day)['operation_added_rows']==0
    assert apply_receiving_status(conn,schema,day)['receiving_reclassified_rows']==0
    with conn.cursor() as q:
        q.execute(f"select label_id from {table(schema,'dashboard_label_local_work')} where store='SHOP' and label_id between 301 and 308")
        assert q.fetchall()==[{'label_id':expected}]
        q.execute(f"select evidence_json from {table(schema,'dashboard_label_local_work')} where store='OTHER' and label_id=301")
        assert q.fetchone()['evidence_json']=='{"original": 1}'

def test_source_id_conflict_blocks_before_reclassification(local_store):
    from etl.label_receiving_status import apply_receiving_status
    conn,schema=local_store
    with conn.cursor() as q:
        q.execute(f"delete from {table(schema,'dashboard_label_source_dictionary')}")
        q.execute(f"insert into {table(schema,'dashboard_label_source_dictionary')} (label_id,sub_label_id,sub_label_name,create_time) values(3,308,'occupied',now())")
    with pytest.raises(RuntimeError,match='occupied'):
        apply_receiving_status(conn,schema,date(2026,10,7))
