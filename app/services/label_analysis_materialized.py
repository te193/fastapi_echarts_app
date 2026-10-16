"""Read immutable, precomputed analysis results from the configured intranet DB."""
from datetime import date
from decimal import Decimal
import hashlib
import json
import zlib
import sys
from pymysql.cursors import SSDictCursor

from .dashboard_db import dashboard_service
from .label_analysis_metrics import METRICS, VERSION
from .label_analysis_role_history import category as history_category,snapshot_meta,attach_snapshot

DOMAIN_FIELDS={domain:set() for domain in ('business','traffic','stockout','inventory')}
for key,metric in METRICS.items():
    domain='traffic' if metric.group=='流量' else 'stockout' if metric.group=='缺货' else 'inventory' if metric.group in ('库存','覆盖与补货') else 'business'
    DOMAIN_FIELDS[domain].add(key)
DOMAIN_FIELDS['stockout'].update(('current_stockout_lower_bound','max_stockout_lower_bound'))
RAW_FIELDS={'daily','traffic_daily','inventory','inventory_cost_daily','replenishment_history','replenishment','region_key','all_labels','evidence_all'}


def json_value(value):
    if isinstance(value,Decimal):return float(value)
    if isinstance(value,date):return value.isoformat()
    if isinstance(value,set):return sorted(value)
    raise TypeError(type(value).__name__)


def dumps(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),default=json_value,allow_nan=False)


def _shared_keys(value):return {sys.intern(key):item for key,item in value.items()}


def unpack(value):return json.loads(value,object_hook=_shared_keys) if isinstance(value,(str,bytes)) else value


def split_row(row):
    context={key:value for key,value in row.items() if key not in RAW_FIELDS|{'values'}}
    values=row['values']
    domains={domain:{key:value for key,value in values.items() if key in fields} for domain,fields in DOMAIN_FIELDS.items()}
    assigned=set().union(*(set(x) for x in domains.values()))
    domains['business'].update({key:value for key,value in values.items() if key not in assigned})
    return context,domains


def join_row(context,domains):
    return {**unpack(context),'values':{key:value for domain in domains.values() for key,value in unpack(domain).items()}}


def encode_history(row):
    payload=dumps(row).encode('utf-8')
    return zlib.compress(payload,6),hashlib.sha256(payload).hexdigest()


def decode_history(blob,checksum):
    payload=zlib.decompress(blob)
    if hashlib.sha256(payload).hexdigest()!=checksum:raise ValueError('分析历史归档校验失败')
    return json.loads(payload,object_hook=_shared_keys)


class PreparedVersionMissing(ValueError):pass


class MaterializedAnalysisRepository:
    materialized=True

    def __init__(self,db=dashboard_service):self.db=db

    def _batch(self,cur,version=''):
        if version:
            cur.execute('select * from dashboard_analysis_batch where batch_id=%s and state in (%s,%s)',(version,'ready','published'))
        else:
            cur.execute('select b.* from dashboard_analysis_publication p join dashboard_analysis_batch b on b.batch_id=p.batch_id where p.singleton=1 and b.state in (%s,%s)',('ready','published'))
        batch=cur.fetchone()
        if not batch:
            if version:raise PreparedVersionMissing('本次预计算批次不存在或已清理，请刷新全部模块')
            raise ValueError('标签分析结果尚未准备，请先运行后台预计算任务')
        if batch['formula_version']!=VERSION:raise ValueError('当前公式版本尚未完成预计算，请更新分析结果')
        return batch

    def metadata(self,version=''):
        with self.db.connect() as conn,conn.cursor() as cur:
            batch=self._batch(cur,version)
            history=snapshot_meta(cur,batch['batch_id'])
        windows=unpack(batch['available_windows'])
        return dict(dates=sorted({w['date'] for w in windows},reverse=True),categories=unpack(batch['label_dictionary'])+([history_category()] if history else []),role_history=history,
                    published_batch=batch['batch_id'],storage='intranet_precomputed',available_windows=windows)

    def load_prepared(self,end,period,view,version=''):
        with self.db.connect() as conn,conn.cursor() as cur:
            batch=self._batch(cur,version)
            windows=unpack(batch['available_windows'])
            if dict(date=end.isoformat(),period=period,view=view) not in windows:raise ValueError('该日期、周期或视角尚未完成预计算；页面不会现场生成')
            with conn.cursor(SSDictCursor) as stream:
                current=self._rows(stream,batch['batch_id'],end,period,view,'current')
                previous=self._rows(stream,batch['batch_id'],end,period,view,'previous')
            manifest=unpack(batch['source_manifest'])
            expected=manifest['counts'][f'{view}:{period}']
            if len(current)!=expected or len(previous)!=expected:raise ValueError('发布批次的分域周期结果不完整')
            context=manifest['datasets'][f'{view}:{period}']
            history=snapshot_meta(cur,batch['batch_id'])
            if history:
                from datetime import timedelta
                attach_snapshot(cur,batch['batch_id'],end,view,current)
                attach_snapshot(cur,batch['batch_id'],end-timedelta(days=period),view,previous)
            cur.execute('''select preset_key,parent_id,label_id,metrics_json from dashboard_analysis_tag_summary
                where batch_id=%s and cutoff_date=%s and period_days=%s and view_kind=%s''',
                (batch['batch_id'],end,period,view))
            summaries={(r['preset_key'],r['parent_id'],r['label_id']):unpack(r['metrics_json']) for r in cur.fetchall()}
        return dict(version=batch['batch_id'],prepared=current,previous_prepared=previous,rows=[],role_history=history,
                    tag_summaries=summaries,categories=unpack(batch['label_dictionary'])+([history_category(view)] if history else []),sources={**context['sources'],'storage':'intranet_precomputed','role_history':history},warnings=context['warnings'])

    @staticmethod
    def _rows(cur,batch,end,period,view,phase):
        # Start with the exact date/view/period/phase range in the context primary
        # key. A domain-first plan scans other windows and sorts large JSON rows.
        cur.execute('''select straight_join c.context_json,b.result_json as business,t.result_json as traffic,
            s.result_json as stockout,i.result_json as inventory
            from dashboard_analysis_object_period c
            join dashboard_analysis_business_period b using (batch_id,cutoff_date,period_days,object_id)
            join dashboard_analysis_traffic_period t using (batch_id,cutoff_date,period_days,object_id)
            join dashboard_analysis_stockout_period s using (batch_id,cutoff_date,period_days,object_id)
            join dashboard_analysis_inventory_object_period i using (batch_id,cutoff_date,period_days,object_id)
            where c.batch_id=%s and c.analysis_date=%s and c.period_days=%s and c.view_kind=%s and c.phase=%s order by c.object_id''',
            (batch,end,period,view,phase))
        result=[]
        while True:
            chunk=cur.fetchmany(40)
            if not chunk:break
            result.extend(join_row(row['context_json'],{domain:row[domain] for domain in DOMAIN_FIELDS}) for row in chunk)
        return result

    def histories(self,data,rows):
        return list(self.iter_histories(data,rows))

    def iter_histories(self,data,rows):
        """Decode at most one archive at a time, with bounded compressed DB chunks."""
        ids=[row['_object_id'] for row in rows]
        if len(set(ids))!=len(ids):raise ValueError('商品历史归档请求存在重复对象')
        with self.db.connect() as conn,conn.cursor() as cur:
            for offset in range(0,len(ids),40):
                chunk=ids[offset:offset+40]
                cur.execute('select object_id,payload,checksum from dashboard_analysis_object_history where batch_id=%s and object_id in ('+','.join(['%s']*len(chunk))+')',(data['version'],*chunk))
                records={row['object_id']:row for row in cur.fetchall()}
                if set(records)!=set(chunk):raise ValueError('发布批次的商品历史归档不完整')
                for oid in chunk:
                    row=records.pop(oid)
                    yield decode_history(row['payload'],row['checksum'])

    def evidence(self,row,*unused):
        raw=self.histories({'version':row['_batch_id']},[row])[0]
        return self.evidence_from_history(row,raw)

    @staticmethod
    def evidence_from_history(row,raw):
        allowed={(tag['id'],tag.get('period',''),tag.get('country','')) for tag in row['labels']}
        return [item for item in raw.get('evidence_all',[]) if (item['label_id'],item.get('label_period') or '',item.get('country') or '') in allowed]
