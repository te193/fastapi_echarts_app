"""Prepare and atomically publish intranet label analysis results, outside HTTP."""
import argparse
import gc
from collections import defaultdict
from datetime import date,timedelta
import json
from pathlib import Path
import time
import uuid

from app.services.dashboard_db import dashboard_service as db
from app.services.label_analysis_repository import AnalysisRepository,identity,COUNTRY_PARENTS
from app.services.label_analysis_engine import prepare_rows,aggregate,select_cohorts
from app.services.label_analysis_metrics import VERSION
from app.services.label_analysis_materialized import dumps,split_row,encode_history,decode_history
from .label_analysis_inputs import PreparedTrafficInputs,PreparedCostInputs

PERIODS=(7,14,30,60,90,180)


def log(value):print(dumps(value),flush=True)


def ensure_schema(database=db):
    if database.host!='192.168.112.235' or database.database!='etl_datasync_test':raise RuntimeError('分析结果迁移只允许已授权的192内网目标库')
    sql=(Path(__file__).resolve().parents[1]/'sqlcode'/'label_analysis_read_model.sql').read_text(encoding='utf-8')
    sql='\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
    with database.connect() as conn,conn.cursor() as cur:
        for statement in sql.split(';'):
            if statement.strip():cur.execute(statement)


class ResultWriter:
    def __init__(self,conn,batch,end):
        self.conn=conn;self.batch=batch;self.end=end;self.ids={};self.archived=set();self.history_mappings={}

    def register(self,rows,view):
        if not rows:return
        keys=sorted({r['key'] for r in rows if (view,r['key']) not in self.ids})
        if not keys:return
        with self.conn.cursor() as cur:
            cur.execute('select object_id,object_key from dashboard_analysis_object where view_kind=%s and object_key in ('+','.join(['%s']*len(keys))+')',(view,*keys))
            self.ids.update({(view,row['object_key']):row['object_id'] for row in cur.fetchall()})
        missing=[r for r in rows if (view,r['key']) not in self.ids]
        if not missing:return
        # Dimensions are shared, stable metadata. Never hold their duplicate-key
        # locks across twelve fact windows in concurrent calculation transactions.
        with db.connect() as conn,conn.cursor() as cur:
            cur.execute('select get_lock(%s,30) as acquired',('label_analysis_object_register',))
            if cur.fetchone()['acquired']!=1:raise RuntimeError('商品身份注册正在占用')
            try:
                cur.executemany('''insert ignore into dashboard_analysis_object
                    (object_key,view_kind,country_category,country,store,msku) values(%s,%s,%s,%s,%s,%s)''',
                    [(r['key'],view,r['country_category'],r.get('country') or '',r['store'],r['msku']) for r in sorted(missing,key=lambda r:r['key'])])
                cur.execute('select object_id,object_key from dashboard_analysis_object where view_kind=%s and object_key in ('+','.join(['%s']*len(keys))+')',(view,*keys))
                self.ids.update({(view,row['object_key']):row['object_id'] for row in cur.fetchall()});conn.commit()
            finally:cur.execute('select release_lock(%s)',('label_analysis_object_register',))

    def histories(self,rows,view):
        pending=[]
        for row in rows:
            oid=self.ids[view,row['key']]
            self.history_mappings.setdefault(oid,{}).update(row.get('replenishment_history',{}))
            if oid in self.archived:continue
            blob,checksum=encode_history(row);pending.append((self.batch,oid,blob,checksum));self.archived.add(oid)
            if len(pending)>=200:self.insert('dashboard_analysis_object_history',['batch_id','object_id','payload','checksum'],pending);pending=[]
        if pending:self.insert('dashboard_analysis_object_history',['batch_id','object_id','payload','checksum'],pending)

    def finish_histories(self):
        # Preserve the longest daily calendar and every shorter comparison cutoff's mapping.
        ids=list(self.archived)
        with self.conn.cursor() as cur:
            for offset in range(0,len(ids),200):
                chunk=ids[offset:offset+200]
                cur.execute('select object_id,payload,checksum from dashboard_analysis_object_history where batch_id=%s and object_id in ('+','.join(['%s']*len(chunk))+')',(self.batch,*chunk))
                changes=[]
                for record in cur.fetchall():
                    raw=decode_history(record['payload'],record['checksum'])
                    raw.setdefault('replenishment_history',{}).update(self.history_mappings[record['object_id']])
                    blob,checksum=encode_history(raw);changes.append((blob,checksum,self.batch,record['object_id']))
                cur.executemany('update dashboard_analysis_object_history set payload=%s,checksum=%s where batch_id=%s and object_id=%s',changes)

    def insert(self,table,columns,rows):
        if not rows:return
        with self.conn.cursor() as cur:
            for offset in range(0,len(rows),300):
                cur.executemany('insert into '+table+' ('+','.join(columns)+') values ('+','.join(['%s']*len(columns))+')',rows[offset:offset+300])

    def period(self,rows,view,period,phase):
        cutoff=self.end if phase=='current' else self.end-timedelta(days=period)
        common=['batch_id','cutoff_date','period_days','object_id']
        contexts=[];business=[];traffic=[];stockout=[];inventory=[]
        business_fields=['sales_qty','sales_amount','sales_amount_ex_tax','order_gross_profit','settlement_gross_profit','net_amount','positive_profit','loss_amount','ad_spend','ad_sales','ad_orders','ad_clicks','ad_impressions','return_count','return_amount','zero_order_spend']
        traffic_fields=['sessions_total','page_views','order_count','traffic_sales_qty','sessions_browser','sessions_mobile','page_views_browser','page_views_mobile']
        stock_fields=['stockout_days','instock_days','unknown_days','valid_days','expected_days','current_stock_state','current_stockout_days','max_stockout_days','confirmed_events','current_lower_bound','max_lower_bound']
        for row in rows:
            oid=self.ids[view,row['key']];context,domains=split_row(row)
            context.update(_object_id=oid,_batch_id=self.batch)
            contexts.append((self.batch,self.end,cutoff,period,view,phase,oid,dumps(context)))
            prefix=(self.batch,cutoff,period,oid);v=row['values']
            coverage={key:row.get(key,{}) for key in ('observed_days','effective_days','zero_filled_by_metric')}
            paired=dumps(row['ratio_pairs']);encoded_coverage=dumps(coverage)
            business.append((*prefix,*[v.get(field) for field in business_fields],paired,encoded_coverage,dumps(domains['business'])))
            pairs=row['ratio_pairs'];orders=pairs.get('order_conversion',(None,None));units=pairs.get('product_conversion',(None,None))
            traffic.append((*prefix,*[v.get(field) for field in traffic_fields],orders[0],orders[1],units[0],units[1],paired,encoded_coverage,dumps(domains['traffic'])))
            qty=v.get('ending_inventory_qty');state=2 if qty is None else 0 if qty==0 else 1
            stockout.append((*prefix,v.get('stockout_days'),v.get('instock_days'),v['unknown_inventory_days'],v['inventory_observed_days'],v['expected_inventory_days'],state,v.get('current_stockout_days'),v.get('max_stockout_days'),v.get('stockout_events'),int(row['inventory_boundary_lower_bound']),int(row['inventory_max_boundary_lower_bound']),dumps(domains['stockout'])))
            inventory.append((*prefix,dumps(domains['inventory'])))
        self.insert('dashboard_analysis_object_period',['batch_id','analysis_date','cutoff_date','period_days','view_kind','phase','object_id','context_json'],contexts)
        self.insert('dashboard_analysis_business_period',common+business_fields+['paired_values','coverage_json','result_json'],business)
        self.insert('dashboard_analysis_traffic_period',common+traffic_fields+['cvr_orders_numerator','cvr_orders_sessions_denominator','cvr_units_numerator','cvr_units_sessions_denominator','paired_values','coverage_json','result_json'],traffic)
        self.insert('dashboard_analysis_stockout_period',common+stock_fields+['result_json'],stockout)
        self.insert('dashboard_analysis_inventory_object_period',common+['result_json'],inventory)

    def tags(self,rows,view,source_date):
        records=set()
        for row in rows:
            oid=self.ids[view,row['key']]
            for tag in row['labels']:records.add((self.batch,self.end,oid,tag['parent_id'],tag['id'],tag.get('period') or '',source_date))
        with self.conn.cursor() as cur:
            cur.executemany('''insert ignore into dashboard_analysis_object_tag
                (batch_id,cutoff_date,object_id,parent_id,label_id,label_period,label_date) values(%s,%s,%s,%s,%s,%s,%s)''',list(records))

    def summaries(self,rows,view,period):
        records=[]
        for preset,conditions in [('all',[]),('over180',[{'kind':'metric','metric':'fba_coverage_days','op':'gt','value':180}])]:
            selected=select_cohorts(rows,conditions)[2];totals=aggregate(selected)
            records.append((self.batch,self.end,period,view,preset,0,0,dumps(totals),dumps({'object_count':len(selected)})))
            groups=defaultdict(list)
            for row in selected:
                for tag in row['labels']:groups[tag['parent_id'],tag['id']].append(row)
            for (parent,child),members in groups.items():
                records.append((self.batch,self.end,period,view,preset,parent,child,dumps(aggregate(members)),dumps({'object_count':len(members)})))
        self.insert('dashboard_analysis_tag_summary',['batch_id','cutoff_date','period_days','view_kind','preset_key','parent_id','label_id','metrics_json','denominator_json'],records)


def attach_evidence(repository,rows,end,scope=None):
    evidence=getattr(repository,'prepared_evidence',None)
    if evidence is None:
        with repository.db.connect() as conn,conn.cursor() as cur:
            from app.services.label_analysis_repository import scope_filter
            clause,args=scope_filter(scope,store='store',msku='msku')
            cur.execute('''select country_category,store,msku,label_id,label_period,country,
                cast(uncompress(evidence_blob) as char character set utf8mb4) as evidence_blob
                from dashboard_label_fact_snapshot where data_date=%s'''+clause,(end,*args))
            evidence=defaultdict(list)
            for item in cur.fetchall():evidence[identity(item['country_category'],item['store'],item['msku'])].append(item)
        repository.prepared_evidence=evidence
    for row in rows:row['evidence_all']=evidence.get(row['region_key'],[])


def legacy_refresh(end=None,periods=PERIODS,views=('business_unit','country'),traffic_refresh_days=30):
    if set(periods)!=set(PERIODS) or set(views)!={'business_unit','country'}:
        raise ValueError('发布必须包含全部六个周期和两个视角，不能用部分窗口替换页面数据')
    ensure_schema()
    with db.connect() as lock_conn,lock_conn.cursor() as lock_cursor:
        lock_cursor.execute('select get_lock(%s,0) as acquired',('label_analysis_refresh',))
        if lock_cursor.fetchone()['acquired']!=1:raise RuntimeError('已有分析准备任务正在运行')
        batch=str(uuid.uuid4());started=time.monotonic()
        try:
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot');latest=cur.fetchone()['d']
            end=end or latest
            if end!=latest:raise ValueError('本次切换必须准备内网标签表最新日期')
            log({'stage':'start','batch':batch,'date':end,'periods':periods,'views':views})
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('''insert into dashboard_analysis_batch(batch_id,formula_version,schema_version,source_manifest,available_windows,label_dictionary)
                    values(%s,%s,%s,%s,%s,%s)''',(batch,VERSION,'analysis-read-model-v1','{}','[]','[]'));conn.commit()
            traffic=PreparedTrafficInputs(db,end,max(periods),refresh_days=traffic_refresh_days,progress=log)
            cost=PreparedCostInputs(db,end,periods)
            repository=AnalysisRepository(db);repository.traffic=traffic;repository.sellable_cost=cost
            baseline_revision=repository.revision(end)
            datasets={};windows=[];counts={};categories=[]
            with db.connect() as conn:
                writer=ResultWriter(conn,batch,end)
                for view in views:
                    for period in sorted(periods,reverse=True):
                        log({'stage':'prepare','view':view,'period':period})
                        data=repository.load(end,period,view)
                        if data['sources']['labels']!=end.isoformat():raise RuntimeError('标签日期未对齐最新日期')
                        rows=data['rows'];attach_evidence(repository,rows,end);writer.register(rows,view);writer.histories(rows,view)
                        start=end-timedelta(days=period-1)
                        current=prepare_rows(rows,start,end)
                        previous=prepare_rows(rows,start-timedelta(days=period),end-timedelta(days=period))
                        writer.period(current,view,period,'current');writer.period(previous,view,period,'previous')
                        writer.tags(current,view,data['sources']['labels']);writer.summaries(current,view,period)
                        counts[f'{view}:{period}']=len(current)
                        datasets[f'{view}:{period}']={'sources':data['sources'],'warnings':data['warnings']}
                        categories=data['categories'];windows.append({'date':end.isoformat(),'period':period,'view':view})
                        # Same numeric values before/after domain serialization.
                        from app.services.label_analysis_materialized import join_row
                        projected=[]
                        for row in current:
                            context,domains=split_row(row)
                            projected.append(join_row(dumps(context),{key:dumps(value) for key,value in domains.items()}))
                        if aggregate(projected)!=aggregate(current):raise RuntimeError('分域结果序列化对账失败')
                        conn.commit();log({'stage':'stored','view':view,'period':period,'objects':len(current)})
                        del current,previous,rows,data,projected
                        gc.collect()
                    traffic.frames.pop(view,None)
                writer.finish_histories()
                if repository.revision(end)!=baseline_revision:raise RuntimeError('来源发布版本在准备中变化，未切换指针')
                with conn.cursor() as cur:
                    cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot')
                    if cur.fetchone()['d']!=end:raise RuntimeError('标签最新日期发生变化，未切换指针')
                    cur.execute('select count(*) as n from dashboard_analysis_object_period where batch_id=%s',(batch,))
                    actual=cur.fetchone()['n'];expected=sum(counts.values())*2
                    if actual!=expected:raise RuntimeError('周期结果行数校验失败')
                    for table in ['dashboard_analysis_business_period','dashboard_analysis_traffic_period','dashboard_analysis_stockout_period','dashboard_analysis_inventory_object_period']:
                        cur.execute('select count(*) as n from '+table+' where batch_id=%s',(batch,))
                        if cur.fetchone()['n']!=expected:raise RuntimeError('分域周期结果不完整：'+table)
                    manifest={'datasets':datasets,'counts':counts,'source_revision':baseline_revision,'prepared_seconds':time.monotonic()-started}
                    cur.execute('''update dashboard_analysis_batch set state=%s,source_manifest=%s,available_windows=%s,label_dictionary=%s,
                        quality_report=%s,completed_at=current_timestamp(6) where batch_id=%s''',
                        ('ready',dumps(manifest),dumps(windows),dumps(categories),dumps({'rows':actual,'reconciliation':'passed','label_date':end}),batch))
                    # Publish only after all domain sets and both views pass. Prior versions remain readable.
                    cur.execute('''insert into dashboard_analysis_publication(singleton,batch_id) values(1,%s)
                        on duplicate key update batch_id=values(batch_id),published_at=current_timestamp(6)''',(batch,))
                    conn.commit()
            log({'stage':'published','batch':batch,'date':end,'seconds':time.monotonic()-started,'counts':counts})
            return batch
        except Exception:
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('update dashboard_analysis_batch set state=%s where batch_id=%s and state=%s',('failed',batch,'building'));conn.commit()
            raise
        finally:lock_cursor.execute('select release_lock(%s)',('label_analysis_refresh',))


def refresh(end=None,periods=PERIODS,views=('business_unit','country'),traffic_refresh_days=30,**options):
    if set(periods)!=set(PERIODS) or set(views)!={'business_unit','country'}:
        raise ValueError('发布必须包含全部六个周期和两个视角，不能用部分窗口替换页面数据')
    from .label_analysis_bounded_refresh import refresh_bounded
    return refresh_bounded(end,periods,views,traffic_refresh_days,**options)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Prepare intranet label analysis, without updating label facts')
    parser.add_argument('--date',type=date.fromisoformat)
    parser.add_argument('--biz-date',help='Daily runner business date; this consumer still prepares the latest published label day')
    parser.add_argument('--snapshot-date',help='Upstream snapshot date; analysis still follows the latest published label day')
    parser.add_argument('--dry-run',action='store_true',help='Print preparation contract without database access or writes')
    parser.add_argument('--periods',nargs='+',type=int,choices=PERIODS,default=PERIODS)
    parser.add_argument('--views',nargs='+',choices=['business_unit','country'],default=['business_unit','country'])
    parser.add_argument('--traffic-refresh-days',type=int,default=30)
    parser.add_argument('--workers',type=int,default=2,choices=range(1,9))
    parser.add_argument('--chunk-size',type=int,default=80)
    parser.add_argument('--worker-memory-mb',type=int,default=512)
    parser.add_argument('--resume',default='')
    parser.add_argument('--probe-scopes',type=int,default=0,help='Prepare a few scopes without publishing; safely resumable')
    parser.add_argument('--worker-spec',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.traffic_refresh_days<1:parser.error('traffic-refresh-days must be positive')
    if args.worker_spec:
        from .label_analysis_bounded_refresh import worker,summary_worker
        spec=json.loads(Path(args.worker_spec).read_text(encoding='utf-8'))
        (summary_worker if spec.get('kind')=='summary' else worker)(spec)
    elif args.dry_run:log({'stage':'dry_run','periods':args.periods,'views':args.views,'date':'latest published label day','workers':args.workers,'chunk_size':args.chunk_size})
    else:refresh(args.date,args.periods,args.views,args.traffic_refresh_days,workers=args.workers,chunk_size=args.chunk_size,
                 memory_mb=args.worker_memory_mb,resume=args.resume,probe_scopes=args.probe_scopes)
