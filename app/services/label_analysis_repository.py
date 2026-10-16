"""Read-only adapter for existing published snapshots. No ETL invocation."""
from collections import defaultdict, OrderedDict
from datetime import date, timedelta
import hashlib
import json

from .dashboard_db import dashboard_service
from .label_analysis_engine import number
from .label_analysis_metrics import SNAPSHOT_DAILY_FIELDS, REPL_FIELDS
from .replenishment_data import replenishment_service
from .label_analysis_inventory import SellableCostRepository,aligned_sellable_cost
from .label_analysis_traffic import ProductTrafficRepository,PRODUCT_TRAFFIC_FIELDS,TRAFFIC_DAILY_FIELDS,TrafficRows,attach_traffic

COUNTRY_PARENTS = {4,7,13,14,16,17,18,19,21}
INVENTORY_COLUMNS = {
    'ending_inventory_qty':'afn_fulfillable_quantity','inventory_total':'total','inventory_cost':'total_price',
    'available_inventory':'available_total','available_inventory_cost':'available_price',
    'unsellable_inventory':'afn_unsellable_quantity','reserved_inventory':'reserved_customerorders',
    'transfer_inventory':'reserved_fc_transfers','processing_inventory':'reserved_fc_processing',
    'inbound_inventory':'afn_inbound_working_quantity','in_transit':'stock_up_num','in_transit_cost':'stock_up_num_price',
}


def day(value):
    return value.isoformat()[:10] if hasattr(value,'isoformat') else str(value or '')[:10]


def label_window(days):
    """Long analysis periods reuse published 30-day labels, without regeneration."""
    return 30 if days in (60,180) else days


def unpack_points(records, fields):
    """Lossless wire packing: keep nulls and duplicate days for contract checks."""
    for record in records:
        identity_fields={k:v for k,v in record.items() if k!='points'}
        points=json.loads(record['points']) if isinstance(record['points'],(str,bytes)) else record['points']
        for point in points:
            if len(point)!=len(fields):raise ValueError('分析快照字段结构不匹配')
            yield {**identity_fields,**dict(zip(fields,point))}


def identity(category, store, msku, country=''):
    return '\x1f'.join(str(x or '').strip().casefold() for x in (category,store,msku,country))


def public_key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def normalize_msku(value):
    """Mirror etl.label_fba_source's published seller_sku_adj contract."""
    value=str(value or '').strip()
    return value.split('-',1)[0].replace('amzn.gr.','') if len(value.encode('utf-8'))>16 else value


LISTING_MSKU_SQL="case when length(trim(seller_sku))>16 then replace(substring_index(trim(seller_sku),'-',1),'amzn.gr.','') else trim(seller_sku) end"


def scope_filter(scope, category='country_category', store='seller_name_new', msku='seller_sku_adj', mapping=False):
    """Push bounded row selection into SQL; mappings retain complete ASIN groups."""
    if scope is None:return '',()
    categories=tuple(scope.get('category_variants') or [scope['country_category']])
    params=categories
    sql=f' and {category} in ('+','.join(['%s']*len(categories))+')'
    if not mapping:
        members=tuple(scope.get('msku_variants') or scope['mskus'])
        if not members:raise ValueError('分析分块不能没有MSKU')
        stores=tuple(scope.get('store_variants') or [scope['store']])
        sql+=f' and {store} in ('+','.join(['%s']*len(stores))+f') and {msku} in ('+','.join(['%s']*len(members))+')'
        params+= (*stores,*members)
    return sql,params


def remove_redundant_unmapped(rows):
    mapped={r['region_key'] for r in rows.values() if r['country']}
    for key,row in list(rows.items()):
        # Unallocated actual sales cannot be discarded or distributed arbitrarily.
        if not row['country'] and row['region_key'] in mapped and not row['daily'] and not row.get('traffic_daily'):
            del rows[key]


def resolve_supply(repl, pools=None):
    """Reuse published replenishment results, including its country-category/ASIN groups.

    The old table does not persist group_daily_avg_sales. Group lead demand is its
    published product with group lead days: inversion retains the stored precision.
    Individual daily_avg_sales is never overwritten with this derived group value.
    """
    groups=defaultdict(list)
    for (region,dt),r in repl.items():
        parts=region.split('\x1f'); category,store=parts[:2]
        r['pool_id']=identity(category,store,'fnsku:'+r['max_fnsku']) if r.get('max_fnsku') else region
        r['demand_id']=region
        r['coverage_daily_sales']=number(r.get('daily_avg_sales'))
        r['aggregate_values']={}
        r['coverage_mapping_status']='同日补货对象；明细日销与补货页面一致'
        if r.get('asin_merge_flag')==1:
            groups[category,r.get('max_asin'),dt].append((region,r))
        elif r.get('fllow_flag')==0 or r.get('mapping_conflict'):
            r['coverage_daily_sales']=None
            r['aggregate_values']['replenishment_daily_sales']=None
            r['coverage_mapping_status']='跟卖需求对象未完成组映射；继承日销仅作明细展示'
    for (category,asin,dt),members in groups.items():
        demands=[]; inventory={}; support=[]
        for region,r in members:
            lead=number(r.get('effective_purchase_lead_days')); demand=number(r.get('lead_time_demand_qty'))
            demands.append(demand/lead if lead is not None and lead>0 and demand is not None and demand>=0 else None)
            qty=number(pools.get(region,{}).get('inventory',{}).get(dt)) if pools is not None else number(r.get('afn_fulfillable_quantity'))
            inventory.setdefault(r['pool_id'],[]).append(qty if qty is not None and qty>=0 else None)
            support.append(number(r.get('support_inventory_qty')))
        valid=bool(asin) and len(members)>1 and all(x is not None for x in demands) and max(demands)-min(demands)<1e-8
        demand=demands[0] if valid else None
        pool_quantities=[vs[0] if all(v is not None for v in vs) and max(vs)==min(vs) else None for vs in inventory.values()]
        quantity=sum(pool_quantities) if pool_quantities and all(x is not None for x in pool_quantities) else None
        for region,r in members:
            r['demand_id']=identity(category,'asin-group',asin or region)
            r['coverage_daily_sales']=demand
            r['coverage_inventory_qty']=quantity
            r['aggregate_values']={'replenishment_daily_sales':demand,'support_inventory_qty':sum(support) if all(x is not None for x in support) else None}
            # Link-local warehouse stock is not a group-level repeated field.
            r['coverage_mapping_status']='组级需求=已发布提前期需求量÷有效提前期（保留源表舍入精度）；FBA库存取完整产品组' if valid else '产品组映射或已发布组需求不完整，覆盖天数未知'
    shared=defaultdict(list)
    for (region,dt),r in repl.items():
        if r.get('asin_merge_flag')!=1:shared[r['pool_id'],dt].append((region,r))
    for (pool,dt),members in shared.items():
        if len(members)<2:continue
        demands=[r['coverage_daily_sales'] for _,r in members]
        demand=sum(demands) if all(v is not None and v>=0 for v in demands) else None
        stocks=[number(pools.get(region,{}).get('inventory',{}).get(dt)) if pools is not None else number(r.get('afn_fulfillable_quantity')) for region,r in members]
        stock=stocks[0] if all(v is not None and v>=0 for v in stocks) and max(stocks)==min(stocks) else None
        for _,r in members:
            r['demand_id']=pool
            r['coverage_daily_sales']=demand
            r['coverage_inventory_qty']=stock
            r['aggregate_values']['replenishment_daily_sales']=demand
            if stock is None:
                for field in INVENTORY_COLUMNS:r['aggregate_values'][field]=None
                r['aggregate_values']['sellable_inventory_cost']=None
            r['coverage_mapping_status']='同店铺FNSKU共享库存；使用完整已映射需求，跟卖未映射则未知'


class AnalysisRepository:
    def __init__(self, db=dashboard_service):
        self.db=db
        self.sellable_cost=SellableCostRepository(db) if hasattr(db,'source_connect') else None
        self.traffic=ProductTrafficRepository(db) if hasattr(db,'source_connect') else None
        # Offline scoped workers validate one source baseline before publication.
        # Retain only small immutable metadata and endpoint supply quantities;
        # no financial, traffic or inventory daily histories enter these caches.
        self._scope_metadata=OrderedDict()
        self._scope_inventory_endpoints=OrderedDict()
        self._scope_replenishment_endpoints=OrderedDict()

    @staticmethod
    def _remember(cache,key,value,limit=16):
        cache[key]=value;cache.move_to_end(key)
        while len(cache)>limit:cache.popitem(last=False)

    def _endpoint_records(self,cur,scope,dates,table,projection,date_column,cache):
        categories=tuple(scope.get('category_variants') or [scope['country_category']])
        missing=[dt for dt in dates if (categories,dt) not in cache]
        if missing:
            clause,args=scope_filter(scope,mapping=True)
            cur.execute(f'select {projection} from {table} where {date_column} in ('+','.join(['%s']*len(missing))+')'+clause,(*missing,*args))
            buckets={day(dt):[] for dt in missing}
            for record in cur.fetchall():buckets.setdefault(day(record[date_column]),[]).append(record)
            for dt in missing:self._remember(cache,(categories,dt),buckets.get(day(dt),[]))
        return [record for dt in dates for record in cache[(categories,dt)]]

    def _source_revision(self):
        return (self.sellable_cost.revision() if self.sellable_cost else ('unavailable',))+(self.traffic.revision() if self.traffic else ('unavailable',))

    @staticmethod
    def _publication_time(cur,label_date):
        # The local publisher commits this marker together with facts/dictionary.
        cur.execute('select count(*) as n from information_schema.tables where table_schema=database() and table_name=%s',('dashboard_label_local_publication',))
        if cur.fetchone().get('n'):
            cur.execute('select published_at,source_mode from dashboard_label_local_publication where singleton=%s',(1,))
            publication=cur.fetchone() or {}
            if publication.get('source_mode')=='local_generated':return str(publication['published_at'])
        # Compatibility with older sources without a transactional publication marker.
        cur.execute('select max(created_time) as t from dashboard_label_fact_snapshot where data_date=%s',(label_date,))
        return str(cur.fetchone()['t'])

    @staticmethod
    def _revision(cur, end, definitions=None, label_version=None):
        # Both daily and replenishment publishers record completed steps here.
        cur.execute('select max(id) as id from dashboard_etl_task_log')
        etl_revision=cur.fetchone()['id']
        cur.execute('select table_name,update_time from information_schema.tables where table_schema=database() and table_name in (%s,%s,%s,%s,%s) order by table_name',(
            'dashboard_label_fact_snapshot','dashboard_product_performance_daily','dashboard_inventory_daily_snapshot',
            'dashboard_listing_price_daily_snapshot','dashboard_pur_plan_replenish_data'))
        table_revision=tuple((str(r.get('TABLE_NAME') or r.get('table_name')),str(r.get('UPDATE_TIME') or r.get('update_time') or '')) for r in cur.fetchall())
        if label_version is None:
            cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot where data_date<=%s',(end,))
            label_date=cur.fetchone()['d']
            label_version=(label_date,AnalysisRepository._publication_time(cur,label_date))
        if definitions is None:
            cur.execute('select label_id,label_name,sub_label_id,sub_label_name,status,tag_rule,business_definition from dashboard_label_detail_snapshot')
            definitions=cur.fetchall()
        definition_version=hashlib.sha256(json.dumps(sorted(definitions,key=lambda d:(int(d['label_id']),int(d['sub_label_id']))),sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
        return (etl_revision,day(label_version[0]),label_version[1],definition_version,table_revision)

    def revision(self,end):
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            return self._revision(cur,end)+self._source_revision()

    def metadata(self):
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            cur.execute('select distinct data_date from dashboard_label_fact_snapshot order by data_date desc limit 30')
            dates=[day(r['data_date']) for r in cur.fetchall()]
            cur.execute('select min(d) as d from (select max(dt_date) as d from dashboard_product_performance_daily union all select max(cur_date) from dashboard_pur_plan_replenish_data union all select max(snapshot_date) from dashboard_inventory_daily_snapshot) sources')
            latest=day(cur.fetchone()['d'])
            if latest and dates and latest>=dates[0]: dates=sorted(set(dates+[latest]),reverse=True)
            cur.execute('select label_id, label_name, sub_label_id, sub_label_name, status, tag_rule, business_definition from dashboard_label_detail_snapshot')
            definitions=cur.fetchall()
        return dict(dates=dates,categories=self.categories(definitions))

    def evidence(self, row, label_date, publication_time):
        with self.db.connect() as conn,conn.cursor() as cur:
            if self._publication_time(cur,label_date)!=publication_time:raise ValueError('标签发布批次已改变，刷新全部模块后再查看命中证据')
            cur.execute('select label_id,label_period,country,cast(uncompress(evidence_blob) as char character set utf8mb4) as evidence_blob from dashboard_label_fact_snapshot where data_date=%s and country_category=%s and store=%s and msku=%s',
                        (label_date,row['country_category'],row['store'],row['msku']))
            allowed={(t['id'],t.get('period',''),t.get('country','')) for t in row['labels']}
            return [r for r in cur.fetchall() if (int(r['label_id']),r.get('label_period') or '',r.get('country') or '') in allowed]

    @staticmethod
    def categories(definitions):
        categories={}
        for d in definitions:
            parent=int(d['label_id']); child=int(d['sub_label_id'])
            group=categories.setdefault(parent,dict(id=parent,label=d['label_name'],scope='country' if parent in COUNTRY_PARENTS else 'business_unit',children=[]))
            group['children'].append(dict(id=child,label=d['sub_label_name'],enabled=d.get('status')=='启用',rule=d.get('tag_rule') or '',definition=d.get('business_definition') or ''))
        for category in categories.values():category['children'].sort(key=lambda child:child['id'])
        return sorted(categories.values(),key=lambda c:c['id'])

    def scopes(self, end:date, chunk_size=80):
        """Enumerate identities only, without loading their daily metric histories."""
        if not 1<=chunk_size<=500:raise ValueError('分析分块大小必须在1到500之间')
        start=end-timedelta(days=359)
        queries=[
            ('select distinct country_category,store,msku from dashboard_label_fact_snapshot where data_date=(select max(data_date) from dashboard_label_fact_snapshot where data_date<=%s)',(end,)),
            (f'select distinct country_category,seller_name_new as store,{LISTING_MSKU_SQL} as msku from dashboard_listing_price_daily_snapshot where snapshot_date=(select max(snapshot_date) from dashboard_listing_price_daily_snapshot where snapshot_date<=%s)',(end,)),
            ('select distinct country_category,seller_name_new as store,seller_sku_adj as msku from dashboard_product_performance_daily where dt_date between %s and %s',(start,end)),
            ('select distinct country_category,seller_name_new as store,seller_sku_adj as msku from dashboard_inventory_daily_snapshot where snapshot_date between %s and %s',(start,end)),
            ('select distinct country_category,seller_name_new as store,seller_sku_adj as msku from dashboard_pur_plan_replenish_data where cur_date=%s',(end,)),
            ('select distinct country_category,store,msku from dashboard_analysis_traffic_input where data_date between %s and %s',(start,end)),
        ]
        groups={};category_spellings=defaultdict(set)
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            for sql,args in queries:
                cur.execute(sql,args)
                for record in cur.fetchall():
                    raw_category,raw_store,raw_msku=(str(record.get(field) or '') for field in ('country_category','store','msku'))
                    category,store,msku=(value.strip() for value in (raw_category,raw_store,raw_msku))
                    if not store or not msku or msku.startswith('Amazon.Found.'):continue
                    key=(category.casefold(),store.casefold())
                    category_spellings[category.casefold()].add(raw_category)
                    group=groups.setdefault(key,dict(country_category=category,store=store,mskus={},category_variants=set(),store_variants=set()))
                    group['category_variants'].add(raw_category);group['store_variants'].add(raw_store)
                    group['mskus'].setdefault(msku.casefold(),set()).update((msku,raw_msku))
        result=[]
        for key in sorted(groups):
            group=groups[key];members=sorted(group['mskus'])
            for offset in range(0,len(members),chunk_size):
                chosen=members[offset:offset+chunk_size]
                variants=sorted({value for member in chosen for value in group['mskus'][member]})
                result.append(dict(country_category=group['country_category'],store=group['store'],mskus=chosen,
                    category_variants=sorted(category_spellings[key[0]]),store_variants=sorted(group['store_variants']),msku_variants=variants))
        return result

    def load(self, end:date, days:int, view:str, scope=None):
        start=end-timedelta(days=days*2-1)
        tag_days=label_window(days)
        rows={}; pools={}; sources={}; warnings=[]; definitions=[]; repl={}
        facts_by_region=defaultdict(list)
        selected={identity(scope['country_category'],scope['store'],msku) for msku in scope['mskus']} if scope else None
        def get_row(category,store,msku,country=''):
            if not str(msku or '').strip() or not str(store or '').strip(): return None
            if str(msku).startswith('Amazon.Found.'): return None
            region_key=identity(category,store,msku)
            if selected is not None and region_key not in selected:return None
            key=identity(category,store,msku,country if view=='country' else '')
            if key not in rows:
                rows[key]=dict(key=public_key(key),msku=str(msku),store=str(store),country_category=str(category),country=country if view=='country' else '',countries=set(),
                               region_key=region_key,pool_id=region_key,demand_id=region_key,labels=[],daily={},inventory={},inventory_cost_daily={},inventory_values={},replenishment_history={})
            row=rows[key]
            if country: row['countries'].add(country)
            return row
        with self.db.connect() as conn,conn.cursor() as cur:
            cur.execute('set transaction isolation level repeatable read')
            cur.execute('start transaction with consistent snapshot, read only')
            metadata=self._scope_metadata.get(end) if scope is not None else None
            if metadata is None:
                cur.execute('select label_id,label_name,sub_label_id,sub_label_name,status,tag_rule,business_definition from dashboard_label_detail_snapshot')
                definitions=cur.fetchall()
                cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot where data_date<=%s',(end,))
                label_date=cur.fetchone()['d']
                if not label_date:raise ValueError('所选截止日之前没有标签快照')
                publication_time=self._publication_time(cur,label_date)
                revision=self._revision(cur,end,definitions,(label_date,publication_time))+self._source_revision()
                if scope is not None:
                    cur.execute('select max(snapshot_date) as d from dashboard_listing_price_daily_snapshot where snapshot_date<=%s',(end,))
                    listing_date=cur.fetchone()['d']
                    metadata=dict(definitions=definitions,label_date=label_date,publication_time=publication_time,revision=revision,listing_date=listing_date)
                    self._remember(self._scope_metadata,end,metadata,limit=2)
            else:
                definitions=metadata['definitions'];label_date=metadata['label_date']
                publication_time=metadata['publication_time'];revision=metadata['revision'];listing_date=metadata['listing_date']
            by_id={int(d['sub_label_id']):d for d in definitions}
            sources['labels']=day(label_date)
            sources['label_publication_time']=publication_time
            # Universe includes EVERY period/status even when that tag is inapplicable.
            tag_filter,tag_args=scope_filter(scope,store='store',msku='msku')
            cur.execute('select distinct country_category,country,store,msku from dashboard_label_fact_snapshot where data_date=%s'+tag_filter,(label_date,*tag_args))
            for f in cur.fetchall():get_row(f['country_category'],f['store'],f['msku'],f.get('country') or '')
            # Only transfer tags usable in this view/window; do not discard objects.
            applicable=[int(d['sub_label_id']) for d in definitions if d.get('status')=='启用' and (view=='country' or int(d['label_id']) not in COUNTRY_PARENTS)]
            placeholders=','.join(['%s']*len(applicable)) or 'null'
            cur.execute('select country_category,store,msku,json_arrayagg(json_array(country,label_id,label_period)) as points from dashboard_label_fact_snapshot where data_date=%s and (label_period is null or label_period in (%s,%s,%s)) and label_id in ('+placeholders+')'+tag_filter+' group by country_category,store,msku',(label_date,'','current',f'{tag_days}d',*applicable,*tag_args))
            sources['label_window_days']=tag_days
            for packed in cur.fetchall():
                region=identity(packed['country_category'],packed['store'],packed['msku'])
                for f in unpack_points([packed],['country','label_id','label_period']):
                    d=by_id.get(int(f['label_id']))
                    if not d:continue
                    parent=int(d['label_id']); period=f.get('label_period') or ''
                    if period not in ('', 'current', f'{tag_days}d'):continue
                    if view=='business_unit' and parent in COUNTRY_PARENTS:continue
                    if d.get('status')!='启用':continue
                    facts_by_region[region].append(dict(parent_id=parent,id=int(f['label_id']),label=d['sub_label_name'],period=period,country=f.get('country') or '',scope='country' if parent in COUNTRY_PARENTS else 'business_unit'))
            if day(label_date)!=end.isoformat():warnings.append(f'标签使用截至{day(label_date)}的最新可用快照，经营与库存截止日为{end.isoformat()}。')
            # The current universe also includes listings without tags or sales.
            if scope is None:
                cur.execute('select max(snapshot_date) as d from dashboard_listing_price_daily_snapshot where snapshot_date<=%s',(end,))
                listing_date=cur.fetchone()['d']
            sources['listings']=day(listing_date)
            if listing_date:
                listing_filter,listing_args=scope_filter(scope,msku=LISTING_MSKU_SQL)
                cur.execute('select country_category,country,seller_name_new,seller_sku,price,price_cny,org_currency_icon from dashboard_listing_price_daily_snapshot where snapshot_date=%s'+listing_filter,(listing_date,*listing_args))
                for r in cur.fetchall():
                    row=get_row(r['country_category'],r['seller_name_new'],normalize_msku(r['seller_sku']),r['country'])
                    if row is not None: row['listing_price']=number(r['price_cny']); row['listing_currency']='CNY'
            # SQL reduces local_sku duplicates before any metric enters the cohort engine.
            grain='country_category,seller_name_new,seller_sku_adj'+(',country' if view=='country' else '')
            fields=','.join(f'sum({k}) as {k}' for k in SNAPSHOT_DAILY_FIELDS)
            # Ranking belongs to one country, cannot be added or averaged across markets.
            fields+=",case when count(distinct country)=1 and count(case when country is null or country='' or ranking is null or ranking<=0 then 1 end)=0 and min(ranking)=max(ranking) then min(ranking) end as small_category_rank"
            country_expr='' if view=='country' else ",group_concat(distinct country separator '|') as countries"
            point_country='' if view=='country' else ',countries'
            # Pack ordered field arrays per object in MySQL. This preserves every day/null,
            # while avoiding hundreds of thousands of Decimal/dict wire conversions.
            history_filter,history_args=scope_filter(scope)
            inner=f'select dt_date,{grain}{country_expr},{fields} from dashboard_product_performance_daily where dt_date between %s and %s{history_filter} group by dt_date,{grain}'
            cur.execute(f'select {grain},json_arrayagg(json_array(dt_date,{",".join(SNAPSHOT_DAILY_FIELDS)},small_category_rank{point_country})) as points from ({inner}) daily group by {grain}',(start,end,*history_args))
            for r in cur.fetchall():
                row=get_row(r['country_category'],r['seller_name_new'],r['seller_sku_adj'],r.get('country',''))
                if row is None: continue
                if r.get('countries'): row['countries'].update(r['countries'].split('|'))
                points=json.loads(r['points']) if isinstance(r['points'],(str,bytes)) else r['points']
                for point in points:
                    row['daily'][day(point[0])]={k:number(v) for k,v in zip(SNAPSHOT_DAILY_FIELDS,point[1:])}
                    row['daily'][day(point[0])]['small_category_rank']=number(point[1+len(SNAPSHOT_DAILY_FIELDS)])
                    if view=='business_unit' and point[-1]:row['countries'].update(point[-1].split('|'))
            sources['performance_window']=[start.isoformat(),end.isoformat()]
            inventory_fields=['snapshot_date',*sorted(set(INVENTORY_COLUMNS.values()))]
            cur.execute('select country_category,seller_name_new,seller_sku_adj,json_arrayagg(json_array('+','.join(inventory_fields)+')) as points from dashboard_inventory_daily_snapshot where snapshot_date between %s and %s'+history_filter+' group by country_category,seller_name_new,seller_sku_adj',(start,end,*history_args))
            for r in unpack_points(cur.fetchall(),inventory_fields):
                key=identity(r['country_category'],r['seller_name_new'],r['seller_sku_adj'])
                pool=pools.setdefault(key,dict(inventory={},costs={},values={}))
                dt=day(r['snapshot_date']); qty=number(r['afn_fulfillable_quantity'])
                # Duplicate inventory object/day is a contract violation, not another stock contribution.
                if dt in pool['inventory']:
                    pool['inventory'][dt]=None; pool['costs'][dt]=None
                    if dt==end.isoformat(): pool['values']={}
                    continue
                pool['inventory'][dt]=qty; pool['costs'][dt]=number(r['total_price'])
                if dt==end.isoformat(): pool['values']={'date':dt,**{k:number(r[v]) for k,v in INVENTORY_COLUMNS.items()}}
                if view=='business_unit': get_row(r['country_category'],r['seller_name_new'],r['seller_sku_adj'])
            sources['inventory_window']=[start.isoformat(),end.isoformat()]
            if scope is not None:
                # Only two days of quantities for outside-block supply members. ASIN
                # merge groups cross stores, so category is the complete mapping scope.
                records=self._endpoint_records(cur,scope,(end,end-timedelta(days=days)),
                    'dashboard_inventory_daily_snapshot','snapshot_date,country_category,seller_name_new,seller_sku_adj,afn_fulfillable_quantity','snapshot_date',self._scope_inventory_endpoints)
                endpoints={}
                for record in records:
                    region=identity(record['country_category'],record['seller_name_new'],record['seller_sku_adj'])
                    dt=day(record['snapshot_date']);key=(region,dt)
                    endpoints[key]=None if key in endpoints else number(record['afn_fulfillable_quantity'])
                for (region,dt),quantity in endpoints.items():
                    if region not in (selected or set()):
                        pools.setdefault(region,dict(inventory={},costs={},values={}))['inventory'][dt]=quantity
            repl_fields=sorted({x[1] for x in REPL_FIELDS.values()}|{'afn_fulfillable_quantity','asin_merge_flag','asin_merge_target','fllow_flag','follow_origin_link','max_fnsku','max_asin','lead_time_demand_qty'})
            # Two exact as-of snapshots: current and preceding comparison period.
            fields=[replenishment_service._display_support_days_expr()+' as inventory_support_days' if f=='inventory_support_days' else f for f in repl_fields]
            if scope is not None:
                records=self._endpoint_records(cur,scope,(end,end-timedelta(days=days)),
                    'dashboard_pur_plan_replenish_data','cur_date,country_category,seller_name_new,seller_sku_adj,'+','.join(fields),'cur_date',self._scope_replenishment_endpoints)
            else:
                cur.execute('select cur_date,country_category,seller_name_new,seller_sku_adj,'+','.join(fields)+' from dashboard_pur_plan_replenish_data where cur_date in (%s,%s)',(end,end-timedelta(days=days)))
                records=cur.fetchall()
            for r in records:
                key=identity(r['country_category'],r['seller_name_new'],r['seller_sku_adj']); dt=day(r['cur_date'])
                value={k:r[k] if k in {'asin_merge_target','follow_origin_link','max_fnsku','max_asin'} else number(r[k]) for k in repl_fields}
                value['date']=dt
                if (key,dt) in repl: value={'date':dt,'mapping_conflict':True}
                repl[key,dt]=value
                if view=='business_unit' and dt==end.isoformat():get_row(r['country_category'],r['seller_name_new'],r['seller_sku_adj'])
            sources['replenishment_dates']=sorted({dt for _,dt in repl})
        try:
            if self.traffic is None:raise RuntimeError('产品表现来源连接不可用')
            traffic_rows=self.traffic.load(end,days,view,scope=scope) if scope is not None else self.traffic.load(end,days,view)
            aligned_traffic=[]
            for source in traffic_rows:
                row=get_row(source['country_category'],source['seller_name_new'],source['seller_sku_adj'],source.get('country') or '')
                if scope is not None and row is not None:
                    aligned_traffic.append({**source,'country_category':row['country_category'],'seller_name_new':row['store'],
                        'seller_sku_adj':row['msku'],'country':row['country']})
            if scope is not None:traffic_rows=TrafficRows(aligned_traffic,getattr(traffic_rows,'coverage_start',None))
            attach_traffic(rows.values(),traffic_rows,view)
            sources['product_traffic']={'table':f'{self.traffic.schema}.{self.traffic.table}','window':[start.isoformat(),end.isoformat()],
                'coverage_start':getattr(traffic_rows,'coverage_start',None),
                'fields':{'sessions_total':'sessions_total','traffic_sales_qty':'volume',**{key:column for key,(_,column) in PRODUCT_TRAFFIC_FIELDS.items()}},'alignment':'流量及CVR分子分母同取本批产品表现日记录；经营金额、库存仍使用已发布快照'}
            if getattr(traffic_rows,'coverage_start',None) and start.isoformat()<traffic_rows.coverage_start:
                warnings.append(f'产品表现当前来源从{traffic_rows.coverage_start}开始，之前日期的流量保持缺失；未用0回填。')
        except Exception:
            for row in rows.values():
                row['unavailable_daily_fields']=list(TRAFFIC_DAILY_FIELDS)
            warnings.append('产品表现流量来源暂不可用；会话、浏览量、订单量和转化字段保持缺失，未用广告点击或零值替代。')
        sellable_costs={}
        try:
            cost_rows=(self.sellable_cost.load(end,days,scope=scope) if scope is not None else self.sellable_cost.load(end,days)) if self.sellable_cost else []
            for cost in cost_rows:
                region=identity(cost['country_category'],cost['seller_name_new'],cost['seller_sku_adj']);dt=day(cost['snapshot_date'])
                sellable_costs[region,dt]=aligned_sellable_cost(cost,pools.get(region,{}),dt)
            sources['sellable_inventory_cost']={'table':'etl_dispose_lx_storage_fba_warehouse_detail.afn_fulfillable_quantity_price','dates':sorted({day(c['snapshot_date']) for c in cost_rows}),'alignment':'同日、同商品；可售数量和总成本与日快照一致后采用'}
        except Exception:
            warnings.append('FBA可售库存成本来源暂不可用；未用总库存或可用库存成本替代。')
        if view=='country':remove_redundant_unmapped(rows)
        resolve_supply(repl,pools)
        # Labels retain their native scope. Category tags can filter country rows, with scope explicit.
        for row in rows.values():
            region=row['region_key']; pool=pools.get(region,{})
            row['inventory']=pool.get('inventory',{}); row['inventory_cost_daily']=pool.get('costs',{}); row['inventory_values']=pool.get('values',{})
            row['sellable_cost_history']={dt:sellable_costs.get((region,dt)) for dt in (end.isoformat(),(end-timedelta(days=days)).isoformat())}
            tags={}
            for f in facts_by_region.get(region,[]):
                if view=='country' and f['scope']=='country' and f['country']!=row['country']:continue
                tags[f['parent_id'],f['id']]=f
            row['labels']=sorted(tags.values(),key=lambda tag:(tag['parent_id'],tag['id'])); row['countries']=sorted(row['countries'])
            for dt in (end.isoformat(),(end-timedelta(days=days)).isoformat()):
                if (region,dt) in repl: row['replenishment_history'][dt]=repl[region,dt]
            current=row['replenishment_history'].get(end.isoformat(),{})
            row['replenishment']=current
            row['coverage_mapping_status']=current.get('coverage_mapping_status','补货对象未覆盖')
        warnings.extend([
            '库存来自国家类别+店铺+MSKU日快照；国家视角展示关联共享库存，不能按国家相加。',
            '经营周期内缺少整条日记录时按0参与汇总、趋势和明细；已有记录的空字段仍保留缺失。库存、成本和日销缺失不补零。',
            '补货日销使用同日已发布结果，不随经营周期改写；合并组的覆盖需求取已发布提前期需求量÷有效提前期（保留源表精度），明细继承日销不相加。',
            '广告指标按展示窗口统计，归因可能回补；不代表成熟归因结论。',
            '源快照未提供可靠商品创建日期，应观察库存日数暂按完整选择期；新商品的未知库存日可能偏多。',
        ])
        if view=='country':
            # A category-only record cannot be silently allocated to a made-up country.
            unassigned=sum(not r['country'] for r in rows.values())
            warnings.append(f'无国家映射的类别记录 {unassigned} 条单列为“国家未映射”，不分摊经营指标。')
        return dict(rows=list(rows.values()),categories=self.categories(definitions),sources=sources,warnings=warnings,revision=revision)
