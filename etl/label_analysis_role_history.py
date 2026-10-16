"""Bounded historical-role preparation. Source read-only; publish only in intranet DB."""
from datetime import date,timedelta
from pathlib import Path
import json
import time
import pymysql
from app.services.dashboard_db import dashboard_service as db
from app.services.label_analysis_repository import identity,public_key
from app.services.label_analysis_role_history import FORMULA_VERSION,summarize_periods


SOURCE_SQL="""select h.scope_mode,h.country_category,h.country,h.store,h.msku,h.data_date,
    json_unquote(json_extract(h.evidence_json,'$.calculation.rule_version')) rule_version,
    (select json_arrayagg(json_object('no',j.period_no,'start',j.start_date,'end',j.end_date,
        'role_id',j.role_id,'complete',j.complete,'eligible',j.eligible))
     from json_table(h.evidence_json,'$.history[*]' columns(
        period_no int path '$.period_no',start_date varchar(10) path '$.start',end_date varchar(10) path '$.end',
        role_id int path '$.role_id',complete int path '$.complete',eligible int path '$.vote_eligible')) j) periods
    from dws_datasync.dws_product_sales_role_history h"""


def sync_role_history(batch='',windows=None,database=db,progress=print):
    if database.host!='192.168.112.235' or database.database!='etl_datasync_test':
        raise ValueError('历史角色结果只允许写入既定192内网分析结果库')
    started=time.monotonic()
    with database.connect() as target,target.cursor() as cur:
        for statement in (Path(__file__).resolve().parents[1]/'sqlcode/label_analysis_role_history.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip():cur.execute(statement)
        if not batch:
            cur.execute('select batch_id from dashboard_analysis_publication where singleton=1');batch=cur.fetchone()['batch_id']
        cur.execute('select get_lock(%s,0) acquired',('label_analysis_role_history',))
        if cur.fetchone()['acquired']!=1:raise RuntimeError('历史销售角色同步正在运行')
        try:
            cur.execute('select * from dashboard_analysis_role_snapshot where batch_id=%s',(batch,));old=cur.fetchone()
            if old and old['state']=='ready':
                if old['formula_version']!=FORMULA_VERSION:raise ValueError('既有历史快照版本不一致，不能覆盖已发布结果')
                return old
            if windows is None:
                cur.execute('select available_windows from dashboard_analysis_batch where batch_id=%s',(batch,));windows=cur.fetchone()['available_windows']
                if isinstance(windows,str):windows=json.loads(windows)
            cutoffs=sorted({date.fromisoformat(w['date'])-timedelta(days=offset) for w in windows for offset in (0,w['period'])})
            if not cutoffs:raise ValueError('没有需要准备的截止日期')
            cur.execute('select view_kind,object_key from dashboard_analysis_object')
            keys={(r['view_kind'],r['object_key']) for r in cur.fetchall()}
            cur.execute('delete from dashboard_analysis_role_result where batch_id=%s',(batch,))
            cur.execute("insert into dashboard_analysis_role_snapshot(batch_id,state,formula_version) values(%s,'building',%s) on duplicate key update state='building'",(batch,FORMULA_VERSION));target.commit()
            pending=[];written=processed=matched=0
            with database.source_connect(autocommit=False) as source:
                with source.cursor() as src:
                    src.execute('select min(data_date) lo,max(data_date) hi,count(*) n,sum(data_date is null) missing_dates from dws_datasync.dws_product_sales_role_history')
                    coverage=src.fetchone()
                    if not coverage['lo'] or coverage['missing_dates'] or coverage['lo']<max(cutoffs):raise ValueError('历史角色源数据尚未完整推进至看板截止日')
                with source.cursor(pymysql.cursors.SSDictCursor) as stream:
                    stream.execute(SOURCE_SQL)
                    for record in stream:
                        processed+=1
                        key=public_key(identity(record['country_category'],record['store'],record['msku'],record['country']))
                        if (record['scope_mode'],key) not in keys:continue
                        if record['rule_version']!='history_30d_v47_20261010':raise ValueError('历史角色规则版本未核验')
                        matched+=1
                        periods=json.loads(record['periods']) if isinstance(record['periods'],(str,bytes)) else record['periods'] or []
                        for cutoff in cutoffs:
                            result=summarize_periods(periods,cutoff)
                            result.update(source_date=str(record['data_date']),source_rule_version=record['rule_version'],formula_version=FORMULA_VERSION)
                            pending.append((batch,cutoff,record['scope_mode'],key,json.dumps(result,ensure_ascii=False,separators=(',',':'))))
                        if len(pending)>=500:
                            cur.executemany('insert into dashboard_analysis_role_result(batch_id,as_of_date,view_kind,object_key,result_json) values(%s,%s,%s,%s,%s)',pending)
                            written+=len(pending);pending=[];target.commit()
                        if processed%2000==0:progress(json.dumps({'stage':'history_roles','source_objects':processed,'matched':matched,'result_rows':written},ensure_ascii=False),flush=True)
                    if pending:
                        cur.executemany('insert into dashboard_analysis_role_result(batch_id,as_of_date,view_kind,object_key,result_json) values(%s,%s,%s,%s,%s)',pending);written+=len(pending)
                source.rollback()
            cur.execute('select count(*) n from dashboard_analysis_role_result where batch_id=%s',(batch,))
            if not matched or cur.fetchone()['n']!=matched*len(cutoffs) or processed!=coverage['n']:raise ValueError('历史角色快照行数校验失败')
            manifest=dict(source_table='dws_datasync.dws_product_sales_role_history',source_objects=processed,matched_objects=matched,cutoffs=[str(d) for d in cutoffs],seconds=round(time.monotonic()-started,2))
            cur.execute("update dashboard_analysis_role_snapshot set state='ready',source_date=%s,row_count=%s,manifest=%s,completed_at=current_timestamp(6) where batch_id=%s",(coverage['hi'],written,json.dumps(manifest),batch));target.commit()
            progress(json.dumps({'stage':'history_roles_ready','batch':batch,'rows':written,**manifest},ensure_ascii=False),flush=True)
            return manifest
        except Exception:
            target.rollback();cur.execute("update dashboard_analysis_role_snapshot set state='failed' where batch_id=%s and state='building'",(batch,));target.commit();raise
        finally:cur.execute('select release_lock(%s)',('label_analysis_role_history',))


if __name__=='__main__':
    import argparse
    import os
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        kernel.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x4000):raise ctypes.WinError(ctypes.get_last_error())
    parser=argparse.ArgumentParser();parser.add_argument('--batch',default='')
    sync_role_history(parser.parse_args().batch)
