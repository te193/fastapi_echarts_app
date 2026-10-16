"""Exact-day total product traffic; supplement existing published daily facts."""
from datetime import timedelta
import json
import os
import re
import pymysql
from .dashboard_db import dashboard_service
from .label_analysis_engine import number
from .label_analysis_metrics import PRODUCT_TRAFFIC_FIELDS,TRAFFIC_DAILY_FIELDS


class TrafficRows(list):
    """Carry the source calendar boundary even when no product rows match."""
    def __init__(self,rows,coverage_start):
        super().__init__(rows)
        self.coverage_start=coverage_start


class ProductTrafficRepository:
    table='lx_statistics_product_performance'

    def __init__(self,db=dashboard_service):
        self.db=db
        self.schema=os.getenv('DASHBOARD_DWD_SOURCE_SCHEMA','dwd_datasync')
        if not re.fullmatch(r'[a-zA-Z0-9_]+',self.schema):raise ValueError('产品表现来源库名无效')

    def revision(self):
        try:
            with self.db.source_connect() as conn,conn.cursor() as cur:
                cur.execute('select update_time from information_schema.tables where table_schema=%s and table_name=%s',(self.schema,self.table))
                row=cur.fetchone()
                return (self.schema,self.table,str((row or {}).get('UPDATE_TIME') or (row or {}).get('update_time') or '')) if row else ('unavailable',)
        except (OSError,RuntimeError,pymysql.err.Error):return ('unavailable',)

    def load(self,end,period,view):
        start=end-timedelta(days=period*2-1)
        country=',country' if view=='country' else ''
        grain='country_category,seller_name_new,seller_sku_adj'+country
        columns=','.join(f'{column} as {key}' for key,(_,column) in PRODUCT_TRAFFIC_FIELDS.items())
        totals=','.join(f'case when count(*)=count({key}) and min({key})>=0 then sum({key}) end as {key}' for key in PRODUCT_TRAFFIC_FIELDS)
        with self.db.source_connect(autocommit=False) as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            cur.execute(f'select min(start_date) as first_day from {self.schema}.{self.table}')
            boundary=cur.fetchone()
            if not boundary or not boundary['first_day']:raise RuntimeError('产品表现来源没有可确认的日期范围')
            coverage_start=str(boundary['first_day'])[:10]
            cur.execute(f'''select {grain},json_arrayagg(json_array(dt_date,sessions_total,sales_qty,{','.join(PRODUCT_TRAFFIC_FIELDS)})) as points
                from (select dt_date,{grain},case when count(*)=count(sessions_total) and min(sessions_total)>=0 then sum(sessions_total) end as sessions_total,
                    case when count(*)=count(sales_qty) and min(sales_qty)>=0 then sum(sales_qty) end as sales_qty,{totals}
                    from (select start_date as dt_date,country,
                        case when country='英国' then '英国站' when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end as country_category,
                        case when locate('-',seller_name)>0 then left(seller_name,locate('-',seller_name)-1) else seller_name end as seller_name_new,
                        if(length(substring_index(seller_sku,',',1))>16,replace(substring_index(substring_index(seller_sku,',',1),'-',1),'amzn.gr.',''),substring_index(seller_sku,',',1)) as seller_sku_adj,
                        sessions_total,volume as sales_qty,{columns}
                        from {self.schema}.{self.table}
                        where start_date>=%s and start_date<%s and end_date=start_date
                            and seller_sku not like 'Amazon.Found%%') source
                    group by dt_date,{grain}) daily group by {grain}''',
                (start.isoformat(),(end+timedelta(days=1)).isoformat()))
            return TrafficRows(cur.fetchall(),coverage_start)


def attach_traffic(rows,packed,view):
    """Total traffic and both CVR components come from one product source snapshot."""
    lookup={}
    for source in packed:
        points=json.loads(source['points']) if isinstance(source['points'],(str,bytes)) else source['points']
        key=(source['country_category'],source['seller_name_new'],source['seller_sku_adj'],(source.get('country') or '') if view=='country' else '')
        lookup[key]={str(point[0])[:10]:point for point in points}
    for row in rows:
        if getattr(packed,'coverage_start',None):row['traffic_coverage_start']=packed.coverage_start
        key=(row['country_category'],row['store'],row['msku'],(row.get('country') or '') if view=='country' else '')
        points=lookup.get(key,{})
        row['traffic_daily']={day:{field:number(value) for field,value in zip(TRAFFIC_DAILY_FIELDS,point[1:])} for day,point in points.items()}
