"""Bounded, resumable preparation. Only two hidden low-priority workers by default."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import date,timedelta
from pathlib import Path
import gc,hashlib,json,os,subprocess,sys,time,uuid
import pymysql
from app.services.dashboard_db import dashboard_service as db
from app.services.label_analysis_repository import AnalysisRepository
from app.services.label_analysis_materialized import MaterializedAnalysisRepository,dumps,unpack,split_row,join_row
from app.services.label_analysis_engine import prepare_rows,aggregate
from app.services.label_analysis_metrics import VERSION
from .label_analysis_inputs import PreparedTrafficInputs,PreparedCostInputs
from .label_analysis_refresh import PERIODS,ResultWriter,attach_evidence,ensure_schema,log

ROOT=Path(__file__).resolve().parents[1]

def code_hash():
    paths=['etl/label_analysis_bounded_refresh.py','etl/label_analysis_refresh.py','etl/label_analysis_inputs.py',
           'app/services/label_analysis_repository.py','app/services/label_analysis_engine.py','app/services/label_analysis_metrics.py',
           'app/services/label_analysis_materialized.py','app/services/label_analysis_inventory.py','app/services/label_analysis_traffic.py',
           'app/services/label_analysis_role_history.py','etl/label_analysis_role_history.py','sqlcode/label_analysis_role_history.sql']
    digest=hashlib.sha256()
    for path in paths:digest.update(path.encode());digest.update((ROOT/path).read_bytes())
    return digest.hexdigest()

def canonical(value):return json.dumps(unpack(dumps(value)),ensure_ascii=False,sort_keys=True,separators=(',',':'))

def scoped_key(scope):return hashlib.sha256(canonical(scope).encode()).hexdigest()

def prepared_repository(end):
    repository=AnalysisRepository(db)
    repository.traffic=PreparedTrafficInputs.from_prepared(db,end)
    repository.sellable_cost=PreparedCostInputs.from_prepared(db,end,PERIODS)
    traffic,cost=repository.traffic,repository.sellable_cost
    repository._source_revision=lambda:cost.revision()+traffic.revision()+('input_generations',cost.input_generation,traffic.input_generation)
    return repository

def forbid_source(*args,**kwargs):raise RuntimeError('分块计算不得访问远端来源')

def worker(spec):
    """One <=80-MSKU scope; all twelve windows commit together or roll back."""
    end=date.fromisoformat(spec['date']);batch=spec['batch'];scope=spec['scope'];key=scoped_key(scope)
    repository=prepared_repository(end);db.source_connect=forbid_source
    if code_hash()!=spec['code_hash']:raise RuntimeError('计算代码版本已变化')
    if dumps(repository.revision(end))!=dumps(spec['source_revision']):raise RuntimeError('分块输入版本已变化')
    results={};counts={};categories=[]
    with db.connect() as conn:
        writer=ResultWriter(conn,batch,end)
        for view in ('business_unit','country'):
            for period in sorted(PERIODS,reverse=True):
                data=repository.load(end,period,view,scope=scope)
                if data['sources']['labels']!=end.isoformat():raise RuntimeError('标签日期未对齐')
                if 'product_traffic' not in data['sources'] or 'sellable_inventory_cost' not in data['sources']:
                    raise RuntimeError('必要输入读取失败，不发布缺失结果')
                rows=data['rows'];attach_evidence(repository,rows,end,scope)
                writer.register(rows,view);writer.histories(rows,view)
                start=end-timedelta(days=period-1)
                current=prepare_rows(rows,start,end)
                previous=prepare_rows(rows,start-timedelta(days=period),end-timedelta(days=period))
                writer.period(current,view,period,'current');writer.period(previous,view,period,'previous')
                writer.tags(current,view,data['sources']['labels'])
                # Validate each object rather than adding partial pool totals across blocks.
                for row in current:
                    context,domains=split_row(row)
                    restored=join_row(dumps(context),{domain:dumps(values) for domain,values in domains.items()})
                    if restored['values']!=row['values'] or restored['ratio_pairs']!=json.loads(dumps(row['ratio_pairs'])):
                        raise RuntimeError('对象结果序列化对账失败')
                counts[f'{view}:{period}']=len(current)
                results[f'{view}:{period}']={'sources':data['sources'],'warnings':data['warnings']}
                categories=data['categories']
                del current,previous,rows,data
                gc.collect()
        writer.finish_histories()
        if code_hash()!=spec['code_hash']:raise RuntimeError('计算中代码版本已变化')
        report={'counts':counts,'datasets':results,'categories':categories,'reconciliation':'passed'}
        with conn.cursor() as cur:
            cur.execute('update dashboard_analysis_scope set state=%s,result_json=%s,updated_at=current_timestamp(6) where batch_id=%s and scope_key=%s',
                        ('ready',dumps(report),batch,key))
        conn.commit()
    return report

def working_set(pid):
    if os.name!='nt':return 0
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('peak','rss','paged_peak','paged','nonpaged_peak','nonpaged','pagefile','pagefile_peak')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return 0
    try:
        value=Counters();value.cb=ctypes.sizeof(value)
        if psapi.GetProcessMemoryInfo(wintypes.HANDLE(handle),ctypes.byref(value),value.cb):return value.rss
        return 0
    finally:kernel.CloseHandle(wintypes.HANDLE(handle))

def launch_scope(spec,folder,memory_mb=512,timeout=600):
    key=scoped_key(spec['scope']) if 'scope' in spec else spec['view']+'-'+str(spec['period']);input_path=folder/(key+'.json');log_path=folder/(key+'.log')
    input_path.write_text(dumps(spec),encoding='utf-8')
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
    peak=0;started=time.monotonic()
    with log_path.open('w',encoding='utf-8') as output:
        process=subprocess.Popen([sys.executable,'-m','etl.label_analysis_refresh','--worker-spec',str(input_path)],
            cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,creationflags=flags,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        try:
            while process.poll() is None:
                peak=max(peak,working_set(process.pid))
                if peak>memory_mb*1024**2:raise RuntimeError('商品块超过内存预算，请缩小chunk-size；保留已完成块')
                if time.monotonic()-started>timeout:raise RuntimeError('商品块超时；保留已完成块')
                time.sleep(.25)
            if process.returncode:
                tail='\n'.join(log_path.read_text(encoding='utf-8').splitlines()[-8:])
                raise RuntimeError('商品块计算失败：'+tail)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=30)
    return key,peak,time.monotonic()-started

def summary_worker(spec):
    if code_hash()!=spec['code_hash']:raise RuntimeError('汇总代码版本已变化')
    batch=spec['batch'];end=date.fromisoformat(spec['date']);period=spec['period'];view=spec['view']
    db.source_connect=forbid_source
    with db.connect() as conn,conn.cursor(pymysql.cursors.SSDictCursor) as cur:
        rows=MaterializedAnalysisRepository._rows(cur,batch,end,period,view,'current')
    if len(rows)!=spec['count']:raise RuntimeError('商品周期行数不完整')
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute('delete from dashboard_analysis_tag_summary where batch_id=%s and cutoff_date=%s and period_days=%s and view_kind=%s',(batch,end,period,view))
        ResultWriter(conn,batch,end).summaries(rows,view,period)
        if code_hash()!=spec['code_hash']:raise RuntimeError('汇总代码版本已变化')
        conn.commit()

def launch_with_retry(spec,folder,memory_mb):
    for attempt in range(4):
        try:return launch_scope(spec,folder,memory_mb)
        except RuntimeError as exc:
            if attempt==3 or not any(code in str(exc) for code in ('1213','1205')):raise
            time.sleep(.5*(attempt+1))

def merge_scope_reports(batch):
    counts={};datasets={};categories=[]
    with db.connect() as conn,conn.cursor(pymysql.cursors.SSDictCursor) as cur:
        cur.execute('select result_json from dashboard_analysis_scope where batch_id=%s and state=%s',(batch,'ready'))
        for record in cur:
            report=unpack(record['result_json']);categories=report['categories']
            for key,value in report['counts'].items():counts[key]=counts.get(key,0)+value
            for key,value in report['datasets'].items():
                if key not in datasets:datasets[key]=value;continue
                dest=datasets[key]
                dest['warnings']=sorted(set(dest['warnings'])|set(value['warnings']))
                for source_name,source in value['sources'].items():
                    # Union only subset-specific date lists. Labels/windows stay identical.
                    if source_name=='replenishment_dates':dest['sources'][source_name]=sorted(set(dest['sources'][source_name])|set(source))
                    elif source_name=='sellable_inventory_cost':
                        dest['sources'][source_name]['dates']=sorted(set(dest['sources'][source_name]['dates'])|set(source['dates']))
    return counts,datasets,categories

def refresh_bounded(end=None,periods=PERIODS,views=('business_unit','country'),traffic_refresh_days=30,
                    workers=2,chunk_size=80,memory_mb=512,resume='',probe_scopes=0):
    if set(periods)!=set(PERIODS) or set(views)!={'business_unit','country'}:raise ValueError('发布必须包含全部六个周期和两个视角')
    if not 1<=workers<=8 or not 1<=chunk_size<=80:raise ValueError('电脑模式最多8进程，每块最多80个MSKU')
    ensure_schema();started=time.monotonic();batch=resume or str(uuid.uuid4())
    with db.connect() as lock_conn,lock_conn.cursor() as lock_cursor:
        lock_cursor.execute('select get_lock(%s,0) as acquired',('label_analysis_refresh',))
        if lock_cursor.fetchone()['acquired']!=1:raise RuntimeError('已有分析准备任务')
        try:
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot');latest=cur.fetchone()['d']
            end=end or latest
            if end!=latest:raise ValueError('必须准备内网标签最新日期')
            log({'stage':'bounded_start','batch':batch,'date':end,'workers':workers,'chunk_size':chunk_size,'worker_memory_mb':memory_mb})
            PreparedTrafficInputs(db,end,180,traffic_refresh_days,progress=log)
            PreparedCostInputs(db,end,PERIODS)
            repository=prepared_repository(end);revision=repository.revision(end)
            scopes=repository.scopes(end,chunk_size);signature=code_hash()
            if not scopes:raise RuntimeError('没有可准备商品')
            manifest={'source_revision':revision,'code_hash':signature,'scopes':scopes,'workers':workers,'chunk_size':chunk_size,'date':end}
            with db.connect() as conn,conn.cursor() as cur:
                if resume:
                    cur.execute('select * from dashboard_analysis_batch where batch_id=%s',(batch,));old=cur.fetchone()
                    frozen=unpack(old['source_manifest']) if old else {}
                    if not old or old['state'] not in ('building','failed') or old['formula_version']!=VERSION:
                        raise ValueError('该批次不能续跑')
                    if any(canonical(frozen.get(key))!=canonical(manifest[key]) for key in ('source_revision','code_hash','scopes','date')):
                        raise ValueError('代码或来源已变化，不能混合旧块续跑')
                    cur.execute('update dashboard_analysis_batch set state=%s where batch_id=%s',('building',batch))
                else:
                    cur.execute('insert into dashboard_analysis_batch(batch_id,formula_version,schema_version,source_manifest,available_windows,label_dictionary) values(%s,%s,%s,%s,%s,%s)',
                        (batch,VERSION,'analysis-read-model-v2-bounded',dumps(manifest),'[]','[]'))
                    cur.executemany('insert into dashboard_analysis_scope(batch_id,scope_key,scope_json) values(%s,%s,%s)',
                        [(batch,scoped_key(scope),dumps(scope)) for scope in scopes])
                cur.execute('select scope_key from dashboard_analysis_scope where batch_id=%s and state=%s',(batch,'ready'))
                completed={row['scope_key'] for row in cur.fetchall()};conn.commit()
            pending=[scope for scope in scopes if scoped_key(scope) not in completed]
            if probe_scopes:pending=pending[:probe_scopes]
            folder=ROOT/'logs'/'label_analysis'/batch;folder.mkdir(parents=True,exist_ok=True)
            peak=0;done=len(completed);iterator=iter(pending)
            # Submit only active worker slots. No unbounded queue retains datasets.
            with ThreadPoolExecutor(max_workers=workers) as executor:
                active={}
                def submit_next():
                    scope=next(iterator,None)
                    if scope is None:return
                    spec={'date':end.isoformat(),'batch':batch,'scope':scope,'source_revision':revision,'code_hash':signature}
                    active[executor.submit(launch_with_retry,spec,folder,memory_mb)]=scope
                for _ in range(workers):submit_next()
                while active:
                    ready,_=wait(active,timeout=1,return_when=FIRST_COMPLETED)
                    for task in ready:
                        key,rss,seconds=task.result();active.pop(task);peak=max(peak,rss);done+=1
                        log({'stage':'scope_ready','done':done,'total':len(scopes),'seconds':round(seconds,2),'peak_mb':round(rss/1024**2,1)})
                        submit_next()
            if probe_scopes:
                log({'stage':'probe_complete','batch':batch,'completed':done,'total':len(scopes),'peak_worker_mb':round(peak/1024**2,1),'published':False})
                return batch
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('select count(*) as n from dashboard_analysis_scope where batch_id=%s and state=%s',(batch,'ready'))
                if cur.fetchone()['n']!=len(scopes):raise RuntimeError('商品块未全部完成')
            counts,datasets,categories=merge_scope_reports(batch)
            windows=[{'date':end.isoformat(),'period':period,'view':view} for view in views for period in periods]
            from .label_analysis_role_history import sync_role_history
            sync_role_history(batch,windows=windows)
            # Pool deduplication and quantiles are computed once from scalar results,
            # never by summing scope medians or partial shared-pool totals.
            for view in views:
                for period in periods:
                    spec={'kind':'summary','date':end.isoformat(),'batch':batch,'view':view,'period':period,'count':counts[f'{view}:{period}'],'code_hash':signature}
                    _,rss,_=launch_scope(spec,folder,memory_mb=1024,timeout=300)
                    peak=max(peak,rss)
                    log({'stage':'summary_ready','view':view,'period':period})
            if code_hash()!=signature:raise RuntimeError('代码版本变化，未切换指针')
            if dumps(prepared_repository(end).revision(end))!=dumps(revision):raise RuntimeError('输入版本变化，未切换指针')
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('select max(data_date) as d from dashboard_label_fact_snapshot')
                if cur.fetchone()['d']!=end:raise RuntimeError('标签最新日期已变化')
                expected=sum(counts.values())*2
                for table in ['object_period','business_period','traffic_period','stockout_period','inventory_object_period']:
                    cur.execute('select count(*) as n from dashboard_analysis_'+table+' where batch_id=%s',(batch,))
                    if cur.fetchone()['n']!=expected:raise RuntimeError('分域结果不完整：'+table)
                manifest.update(counts=counts,datasets=datasets,prepared_seconds=time.monotonic()-started,peak_worker_mb=round(peak/1024**2,1))
                cur.execute('update dashboard_analysis_batch set state=%s,source_manifest=%s,available_windows=%s,label_dictionary=%s,quality_report=%s,completed_at=current_timestamp(6) where batch_id=%s',
                    ('ready',dumps(manifest),dumps(windows),dumps(categories),dumps({'rows':expected,'reconciliation':'passed','label_date':end,'scopes':len(scopes),'workers':workers}),batch))
                cur.execute('insert into dashboard_analysis_publication(singleton,batch_id) values(1,%s) on duplicate key update batch_id=values(batch_id),published_at=current_timestamp(6)',(batch,));conn.commit()
            log({'stage':'published','batch':batch,'date':end,'seconds':time.monotonic()-started,'counts':counts,'peak_worker_mb':round(peak/1024**2,1)})
            return batch
        except Exception:
            with db.connect() as conn,conn.cursor() as cur:
                cur.execute('update dashboard_analysis_batch set state=%s where batch_id=%s and state=%s',('failed',batch,'building'));conn.commit()
            raise
        finally:lock_cursor.execute('select release_lock(%s)',('label_analysis_refresh',))
