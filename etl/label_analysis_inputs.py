"""Offline-only input preparation. Web repositories never import this module."""
from datetime import timedelta
import json
import zlib
from app.services.label_analysis_materialized import dumps,unpack
from app.services.label_analysis_engine import number
from app.services.label_analysis_traffic import ProductTrafficRepository,TrafficRows,PRODUCT_TRAFFIC_FIELDS
from app.services.label_analysis_inventory import SellableCostRepository


def combine_points(points):
    totals={}
    for point in points:
        day=str(point[0])[:10]
        values=[number(value) for value in point[1:]]
        values=[value if value is not None and value>=0 else None for value in values]
        if day not in totals:totals[day]=values
        else:totals[day]=[a+b if a is not None and b is not None else None for a,b in zip(totals[day],values)]
    return [[day,*values] for day,values in sorted(totals.items())]


def traffic_sync_start(state,start,end,refresh_days,revision,coverage_start):
    # A table-level revision cannot prove that old partitions stayed unchanged.
    if (not state or state['first_loaded']>start or not revision[-1]
            or tuple(unpack(state['source_revision']))!=revision
            or coverage_start!=str(state['coverage_start'])[:10]):return start
    return max(start,min(end-timedelta(days=refresh_days-1),state['last_loaded']+timedelta(days=1)))


def bounded_scope(scope):
    """Offline workers must supply one bounded inventory identity group."""
    if not isinstance(scope,dict):raise ValueError('输入读取必须指定商品范围')
    category=scope.get('country_category');store=scope.get('store');mskus=scope.get('mskus')
    if not isinstance(category,str) or not category or not isinstance(store,str) or not store:
        raise ValueError('输入范围必须包含国家类别和店铺')
    if not isinstance(mskus,(list,tuple)) or not mskus or any(not isinstance(sku,str) or not sku for sku in mskus):
        raise ValueError('输入范围必须包含有效 MSKU')
    mskus=tuple(sorted(set(mskus)))
    if len(mskus)>80:raise ValueError('每批输入最多读取 80 个 MSKU')
    for name,expected in [('category',[category]),('store',[store]),('msku',mskus)]:
        variants=scope.get(name+'_variants')
        if variants is not None:
            allowed={value.strip().casefold() for value in expected}
            if (not isinstance(variants,(list,tuple)) or not variants or len(variants)>640
                    or any(not isinstance(value,str) or value.strip().casefold() not in allowed for value in variants)):
                raise ValueError('原始拼写变体不得扩大商品范围')
    return category,store,mskus


def date_blocks(start,end,days=7):
    if days<1:raise ValueError('日期块必须至少一天')
    while start<=end:
        stop=min(end,start+timedelta(days=days-1))
        yield start,stop
        start=stop+timedelta(days=1)


class PreparedTrafficInputs:
    table='dashboard_analysis_traffic_input'

    @classmethod
    def from_prepared(cls,db,end,max_period=180):
        instance=cls.__new__(cls);instance.db=db;instance.schema=db.database
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('select * from dashboard_analysis_input_state where domain=%s',('traffic',))
            state=cur.fetchone()
        start=end-timedelta(days=max_period*2-1)
        if (not state or state['first_loaded']>start or state['last_loaded']<end
                or unpack(state['source_revision'])[0]=='syncing'):
            raise RuntimeError('流量输入日期范围尚未完整准备')
        instance.source_revision=tuple(unpack(state['source_revision']))
        instance.input_generation=str(state.get('updated_at') or '')
        instance.coverage_start=str(state['coverage_start'])[:10]
        return instance

    def __init__(self,db,end,max_period=180,refresh_days=30,progress=print):
        self.db=db;self.schema=db.database;self.original=ProductTrafficRepository(db)
        self.source_revision=self.original.revision()
        if self.source_revision==('unavailable',):raise RuntimeError('产品表现来源不可用，未发布新结果')
        start=end-timedelta(days=max_period*2-1)
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('''create table if not exists dashboard_analysis_traffic_input (
                data_date date not null,country_category varchar(64) not null,country varchar(64) not null,
                store varchar(128) not null,msku varchar(128) not null,points_json json not null,
                primary key(data_date,country_category,country,store,msku)) engine=innodb default charset=utf8mb4''')
            cur.execute('''create table if not exists dashboard_analysis_input_state (
                domain varchar(32) not null primary key,first_loaded date not null,last_loaded date not null,
                coverage_start date not null,source_revision json not null,updated_at datetime(6) not null default current_timestamp(6)) engine=innodb''')
            cur.execute('''select count(*) as found from information_schema.statistics
                where table_schema=%s and table_name=%s and index_name=%s''',
                (self.schema,self.table,'idx_analysis_traffic_scope'))
            if not cur.fetchone()['found']:
                cur.execute('''alter table dashboard_analysis_traffic_input add index
                    idx_analysis_traffic_scope(country_category,store,msku,data_date,country)''')
            cur.execute('select * from dashboard_analysis_input_state where domain=%s',('traffic',));state=cur.fetchone()
        with db.source_connect() as conn,conn.cursor() as cur:
            cur.execute(f'select min(start_date) as first_day from {self.original.schema}.{self.original.table}')
            first=cur.fetchone()['first_day']
        if not first:raise RuntimeError('产品表现来源没有有效日期')
        self.coverage_start=str(first)[:10]
        reuse=(state and bool(self.source_revision[-1]) and state['first_loaded']<=start
            and state['last_loaded']>=end and tuple(unpack(state['source_revision']))==self.source_revision
            and str(state['coverage_start'])[:10]==self.coverage_start)
        if not reuse:
            load_start=traffic_sync_start(state,start,end,refresh_days,self.source_revision,self.coverage_start)
            progress({'stage':'traffic_sync','start':load_start.isoformat(),'end':end.isoformat(),'mode':'incremental' if load_start>start else 'initial'})
            # Invalidate the completeness marker before committing any replacement block.
            # A failed refresh may leave input blocks, but can never publish them as complete.
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('update dashboard_analysis_input_state set source_revision=%s where domain=%s',
                    (dumps(['syncing',*self.source_revision]),'traffic'))
                conn.commit()
            for block_start,block_end in date_blocks(load_start,end):
                packed=self._fetch(block_start,block_end)
                self._store_block(block_start,block_end,packed)
                progress({'stage':'traffic_block','start':block_start.isoformat(),'end':block_end.isoformat(),'objects':len(packed)})
                del packed
            if self.original.revision()!=self.source_revision:
                raise RuntimeError('流量来源在分块同步中发生变化，输入范围未标记完整')
            first_loaded=min(start,state['first_loaded']) if load_start>start and state else start
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('''insert into dashboard_analysis_input_state(domain,first_loaded,last_loaded,coverage_start,source_revision)
                    values(%s,%s,%s,%s,%s) on duplicate key update first_loaded=values(first_loaded),
                    last_loaded=values(last_loaded),coverage_start=values(coverage_start),source_revision=values(source_revision),updated_at=current_timestamp(6)''',
                    ('traffic',first_loaded,end,self.coverage_start,dumps(self.source_revision)))
                conn.commit()

        if self.original.revision()!=self.source_revision:
            raise RuntimeError('流量来源在输入准备中发生变化')

    def _store_block(self,start,end,packed):
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute('delete from dashboard_analysis_traffic_input where data_date between %s and %s',(start,end))
            records=[]
            for group in packed:
                for point in group['points']:
                    records.append((point[0],group['country_category'],group.get('country') or '',group['seller_name_new'],group['seller_sku_adj'],dumps(point)))
                    if len(records)>=1000:
                        cur.executemany('insert into dashboard_analysis_traffic_input values (%s,%s,%s,%s,%s,%s)',records);records=[]
            if records:cur.executemany('insert into dashboard_analysis_traffic_input values (%s,%s,%s,%s,%s,%s)',records)
            conn.commit()

    def _fetch(self,start,end):
        # Aggregate raw records directly by object, without a large intermediate daily GROUP BY.
        columns=','.join(column for _,column in PRODUCT_TRAFFIC_FIELDS.values())
        with self.db.source_connect(autocommit=False) as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            cur.execute(f'''select country_category,country,seller_name_new,seller_sku_adj,
                compress(cast(json_arrayagg(json_array(dt_date,sessions_total,volume,{columns})) as char character set utf8mb4)) as points_blob from
                (select start_date as dt_date,country,
                case when country='英国' then '英国站' when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end as country_category,
                case when locate('-',seller_name)>0 then left(seller_name,locate('-',seller_name)-1) else seller_name end as seller_name_new,
                if(length(substring_index(seller_sku,',',1))>16,replace(substring_index(substring_index(seller_sku,',',1),'-',1),'amzn.gr.',''),substring_index(seller_sku,',',1)) as seller_sku_adj,
                sessions_total,volume,{columns} from {self.original.schema}.{self.original.table}
                where start_date>=%s and start_date<%s and end_date=start_date and seller_sku not like 'Amazon.Found%%') source
                group by country_category,country,seller_name_new,seller_sku_adj''',(start.isoformat(),(end+timedelta(days=1)).isoformat()))
            rows=cur.fetchall()
        for row in rows:row['points']=combine_points(json.loads(zlib.decompress(row.pop('points_blob')[4:])))
        if self.original.revision()!=self.source_revision:raise RuntimeError('流量来源在同步中发生变化，未提交输入范围')
        return rows

    def revision(self):return self.source_revision

    def load(self,end,period,view,scope=None):
        bounded_scope(scope)
        from app.services.label_analysis_repository import scope_filter,identity
        if view not in ('country','business_unit'):raise ValueError('无效分析视角')
        start=end-timedelta(days=period*2-1)
        scope_sql,scope_args=scope_filter(scope,store='store',msku='msku')
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute(f'''select country_category,country,store as seller_name_new,msku as seller_sku_adj,points_json
                from dashboard_analysis_traffic_input where data_date between %s and %s'''+scope_sql,
                (start,end,*scope_args))
            records=cur.fetchall()
        grouped={}
        for row in records:
            key=identity(row['country_category'],row['seller_name_new'],row['seller_sku_adj'],row['country'] if view=='country' else '')
            bucket=grouped.setdefault(key,{k:row[k] for k in ('country_category','seller_name_new','seller_sku_adj')})
            if view=='country':bucket['country']=row['country']
            bucket.setdefault('points',[]).append(unpack(row['points_json']))
        return TrafficRows([{**row,'points':combine_points(row['points'])} for row in grouped.values()],self.coverage_start)


class PreparedCostInputs:
    table='dashboard_analysis_cost_input'

    def __init__(self,db,end,periods):
        self.db=db;self.schema=db.database;self.original=SellableCostRepository(db)
        self.source_revision=self.original.revision()
        if self.source_revision==('unavailable',):raise RuntimeError('可售库存成本来源不可用，未发布新结果')
        dates=sorted({end,*[end-timedelta(days=period) for period in periods]})
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('''create table if not exists dashboard_analysis_cost_input (
                snapshot_date date not null,country_category varchar(64) not null,
                store varchar(128) not null,msku varchar(128) not null,
                quantity decimal(28,8) null,total_cost decimal(28,8) null,sellable_cost decimal(28,8) null,
                primary key(snapshot_date,country_category,store,msku),
                key idx_analysis_cost_scope(country_category,store,msku,snapshot_date)) engine=innodb default charset=utf8mb4''')
            cur.execute('select * from dashboard_analysis_input_state where domain=%s',('cost',));state=cur.fetchone()
        # Exact loaded dates are in the revision marker. A range alone cannot prove
        # the six previous cutoffs exist, especially when the period list changes.
        marker=[*self.source_revision,*[day.isoformat() for day in dates]]
        if state and bool(self.source_revision[-1]) and unpack(state['source_revision'])==marker:
            if self.original.revision()!=self.source_revision:raise RuntimeError('库存成本来源在输入准备中发生变化')
            return
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('update dashboard_analysis_input_state set source_revision=%s where domain=%s',
                (dumps(['syncing',*marker]),'cost'));conn.commit()
        for day in dates:
            rows=self._fetch(day)
            if self.original.revision()!=self.source_revision:
                raise RuntimeError('库存成本来源在准备中发生变化')
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('delete from dashboard_analysis_cost_input where snapshot_date=%s',(day,))
                records=[(row['snapshot_date'],row['country_category'],row['seller_name_new'],row['seller_sku_adj'],
                    row['quantity'],row['total_cost'],row['sellable_cost']) for row in rows]
                for offset in range(0,len(records),1000):
                    cur.executemany('insert into dashboard_analysis_cost_input values (%s,%s,%s,%s,%s,%s,%s)',records[offset:offset+1000])
                conn.commit()
            del rows,records
        if self.original.revision()!=self.source_revision:raise RuntimeError('库存成本来源在准备中发生变化')
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('''insert into dashboard_analysis_input_state(domain,first_loaded,last_loaded,coverage_start,source_revision)
                values(%s,%s,%s,%s,%s) on duplicate key update first_loaded=values(first_loaded),
                last_loaded=values(last_loaded),coverage_start=values(coverage_start),source_revision=values(source_revision),updated_at=current_timestamp(6)''',
                ('cost',dates[0],end,dates[0],dumps(marker)));conn.commit()

    @classmethod
    def from_prepared(cls,db,end,periods):
        instance=cls.__new__(cls);instance.db=db;instance.schema=db.database
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('select * from dashboard_analysis_input_state where domain=%s',('cost',));state=cur.fetchone()
        dates=sorted({end,*[end-timedelta(days=period) for period in periods]})
        marker=unpack(state['source_revision']) if state else []
        if not state or marker[:1]==['syncing'] or marker[3:]!=[day.isoformat() for day in dates]:
            raise RuntimeError('可售库存成本截止日期尚未完整准备')
        instance.source_revision=tuple(marker[:3])
        instance.input_generation=str(state.get('updated_at') or '')
        return instance

    def _fetch(self,day):
        with self.db.source_connect(autocommit=False) as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read');cur.execute('start transaction with consistent snapshot, read only')
            cur.execute(f'''select date(create_time) as snapshot_date,country_category,seller_name_new,seller_sku_adj,
                sum(coalesce(afn_fulfillable_quantity,0)) as quantity,sum(coalesce(total_price,0)) as total_cost,
                case when count(*)=count(afn_fulfillable_quantity_price) and count(*)=count(afn_fulfillable_quantity)
                and min(afn_fulfillable_quantity)>=0 and min(afn_fulfillable_quantity_price)>=0 then sum(afn_fulfillable_quantity_price) end as sellable_cost
                from {self.original.schema}.{self.original.table} where create_time>=%s and create_time<%s
                group by date(create_time),country_category,seller_name_new,seller_sku_adj''',
                (day,day+timedelta(days=1)))
            return cur.fetchall()

    def revision(self):return self.source_revision

    def load(self,end,period,scope=None):
        bounded_scope(scope)
        from app.services.label_analysis_repository import scope_filter
        scope_sql,scope_args=scope_filter(scope,store='store',msku='msku')
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute(f'''select snapshot_date,country_category,store as seller_name_new,msku as seller_sku_adj,
                quantity,total_cost,sellable_cost from dashboard_analysis_cost_input
                where snapshot_date in (%s,%s)'''+scope_sql,(end,end-timedelta(days=period),*scope_args))
            return cur.fetchall()
