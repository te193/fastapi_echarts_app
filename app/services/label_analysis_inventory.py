"""Read exact-date sellable cost from the existing processed warehouse history."""
from datetime import timedelta
import os
import re
import pymysql

from .dashboard_db import dashboard_service


class SellableCostRepository:
    table='etl_dispose_lx_storage_fba_warehouse_detail'

    def __init__(self,db=dashboard_service):
        self.db=db
        # DashboardDbService.schemas points to the local snapshot database.
        # This source connection reads the ETL warehouse schema, as the daily ETL does.
        self.schema=os.getenv('DASHBOARD_ETL_SOURCE_SCHEMA','etl_datasync')
        if not re.fullmatch(r'[a-zA-Z0-9_]+',self.schema):raise ValueError('库存来源库名无效')

    def revision(self):
        try:
            with self.db.source_connect() as conn,conn.cursor() as cur:
                cur.execute('select update_time from information_schema.tables where table_schema=%s and table_name=%s',(self.schema,self.table))
                row=cur.fetchone()
                return (self.schema,self.table,str((row or {}).get('UPDATE_TIME') or (row or {}).get('update_time') or '')) if row else ('unavailable',)
        except (OSError,RuntimeError,pymysql.err.Error):return ('unavailable',)

    def load(self,end,period):
        previous=end-timedelta(days=period)
        with self.db.source_connect(autocommit=False) as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            cur.execute(f'''select date(create_time) as snapshot_date,country_category,seller_name_new,seller_sku_adj,
                sum(coalesce(afn_fulfillable_quantity,0)) as quantity,
                sum(coalesce(total_price,0)) as total_cost,
                case when count(*)=count(afn_fulfillable_quantity_price)
                    and count(*)=count(afn_fulfillable_quantity)
                    and min(afn_fulfillable_quantity)>=0 and min(afn_fulfillable_quantity_price)>=0
                    then sum(afn_fulfillable_quantity_price) end as sellable_cost
                from {self.schema}.{self.table}
                where (create_time>=%s and create_time<%s) or (create_time>=%s and create_time<%s)
                group by date(create_time),country_category,seller_name_new,seller_sku_adj''',
                (end,end+timedelta(days=1),previous,previous+timedelta(days=1)))
            return cur.fetchall()


def aligned_sellable_cost(source,pool,dt):
    """Reject stale/unmatched stock; never substitute total or available cost."""
    def valid(value):
        try:return float(value) if value is not None and float(value)>=0 else None
        except (ValueError,TypeError):return None
    quantity=valid(source.get('quantity'));target_qty=valid(pool.get('inventory',{}).get(dt))
    total=valid(source.get('total_cost'));target_cost=valid(pool.get('costs',{}).get(dt))
    if None in (quantity,target_qty,total,target_cost) or abs(quantity-target_qty)>1e-4 or abs(total-target_cost)>1e-4:return None
    return valid(source.get('sellable_cost'))
