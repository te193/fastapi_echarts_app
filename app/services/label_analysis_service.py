from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from io import StringIO
from copy import deepcopy
import csv
import json
import threading
import time
import uuid
from typing import Literal
from pathlib import Path
from array import array
from math import isfinite

from pydantic import BaseModel, Field, model_validator

from .label_analysis_engine import aggregate, metric_calendar, row_business_record, compare_metrics, coverage_distribution, days_between, number, prepare_rows, safe_ratio, select_cohorts
from .label_analysis_metrics import DAILY_FIELDS, METRICS, VERSION, catalog, row_filterable
from .label_analysis_repository import AnalysisRepository
from .label_analysis_cache import PreparedSnapshotCache
from .label_analysis_materialized import MaterializedAnalysisRepository,PreparedVersionMissing
from .label_analysis_role_history import HISTORY_FIELDS,PARENT_ID,role_distribution


class StaleAnalysis(ValueError):
    pass


class Condition(BaseModel):
    kind: Literal['label','metric','coverage']
    reason: Literal['','no_performance','missing_daily_sales','zero_daily_sales','data_pending'] = ''
    preset: Literal['','capital'] = ''
    parent_id: int | None = None
    ids: list[int] = Field(default_factory=list,max_length=100)
    metric: str | None = None
    op: Literal['eq','gt','gte','lt','lte','between','range','missing','present'] = 'eq'
    value: float | None = Field(default=None,allow_inf_nan=False)
    upper: float | None = Field(default=None,allow_inf_nan=False)

    @model_validator(mode='after')
    def check(self):
        if self.kind=='coverage' and not self.reason:raise ValueError('可售天数分类条件需要原因')
        if self.kind=='label' and (not self.parent_id or not self.ids): raise ValueError('标签条件需要大类及子标签')
        if self.kind=='metric':
            if self.metric not in METRICS or not row_filterable(METRICS[self.metric]): raise ValueError('该指标不支持明细筛选')
            if self.op not in ('missing','present') and self.value is None: raise ValueError('数值条件缺少阈值')
            if self.op in ('between','range') and (self.upper is None or self.upper<self.value): raise ValueError('区间无效')
        return self


class AnalysisQuery(BaseModel):
    data_date: date | None = None
    period: Literal[7,14,30,60,90,180] = 30
    view: Literal['business_unit','country'] = 'business_unit'
    version: str = Field(default='',max_length=64)
    force_refresh: bool = False
    country_categories: list[str] = Field(default_factory=list,max_length=50)
    countries: list[str] = Field(default_factory=list,max_length=100)
    stores: list[str] = Field(default_factory=list,max_length=500)
    keyword: str = Field(default='',max_length=200)
    conditions: list[Condition] = Field(default_factory=list,max_length=30)
    page: int = Field(default=1,ge=1)
    page_size: int = Field(default=20,ge=1,le=100)
    sort: str = 'sales_amount'
    descending: bool = True
    columns: list[str] = Field(default_factory=list,max_length=len(METRICS))
    object_key: str = Field(default='',max_length=64)
    export_kind: Literal['details','summary'] = 'details'
    matrix_parents: list[int] = Field(default_factory=list,max_length=2)

    @model_validator(mode='after')
    def check(self):
        parents=[c.parent_id for c in self.conditions if c.kind=='label']
        if len(set(parents))!=len(parents):raise ValueError('同大类条件请合并为任一命中')
        if self.sort not in METRICS and self.sort not in ('msku','store','country','country_category'):raise ValueError('排序字段无效')
        if self.sort in METRICS and not row_filterable(METRICS[self.sort]):raise ValueError('群体指标或待接入字段不能用于商品排序')
        if any(c not in METRICS for c in self.columns):raise ValueError('导出指标无效')
        if self.view=='business_unit' and self.countries:raise ValueError('国家筛选仅适用于国家视角')
        return self


class LabelAnalysisService:
    def __init__(self,repository=None,cache_directory=None):
        self.repository=repository or MaterializedAnalysisRepository()
        self._cache=OrderedDict(); self._lock=threading.RLock()
        self._meta_lock=threading.Lock(); self._load_locks={}
        self._prepared_load_lock=threading.Lock()
        self._trend_lock=threading.Lock()
        self._meta=None; self._meta_time=0
        self._disk_cache=PreparedSnapshotCache(cache_directory) if cache_directory is not None and not getattr(self.repository,'materialized',False) else None

    def meta(self):
        with self._meta_lock:
            if self._meta is None or time.monotonic()-self._meta_time>120:
                self._meta=self.repository.metadata(); self._meta_time=time.monotonic()
            return {**self._meta,'metrics':catalog(),'formula_version':VERSION,'default_period':30}

    def _dataset(self,q):
        if getattr(self.repository,'materialized',False):return self._prepared_dataset(q)
        with self._lock:
            if q.version and not q.force_refresh:
                entry=self._cache.get(q.version)
                if not entry or time.monotonic()-entry['created']>1800:raise StaleAnalysis('本次数据版本已过期，请刷新全部模块')
                if (q.data_date and q.data_date!=entry['date']) or q.period!=entry['period'] or q.view!=entry['view']:raise StaleAnalysis('日期、周期或视角已改变，请重新加载')
                return entry
        meta=self.meta(); end=q.data_date or (date.fromisoformat(meta['dates'][0]) if meta['dates'] else None)
        if end is None or end.isoformat() not in meta['dates']:raise ValueError('所选日期没有已发布标签快照')
        key=(end,q.period,q.view)
        with self._lock:
            load_lock=self._load_locks.setdefault(key,threading.Lock())
        # Single flight for one dataset; unrelated datasets and pinned reads stay free.
        with load_lock:
            with self._lock:
                candidates=[e for e in self._cache.values() if (e['date'],e['period'],e['view'])==key and time.monotonic()-e['created']<1800]
            entry=candidates[-1] if candidates else None
            if entry and not q.force_refresh:
                if time.monotonic()-entry.get('checked',entry['created'])<120:return entry
                if hasattr(self.repository,'revision') and self.repository.revision(end)==entry.get('revision'):
                    entry['checked']=time.monotonic()
                    return entry
            restored=None
            if self._disk_cache and not q.force_refresh:
                revision=self.repository.revision(end)
                restored=self._disk_cache.read(key,revision)
            data=restored or self.repository.load(end,q.period,q.view)
            start=end-timedelta(days=q.period-1)
            entry=dict(**data,version=uuid.uuid4().hex,date=end,start=start,period=q.period,view=q.view,created=time.monotonic())
            entry['checked']=entry['created']
            if restored is None:
                entry['prepared']=prepare_rows(data['rows'],start,end)
                entry['previous_prepared']=prepare_rows(data['rows'],start-timedelta(days=q.period),end-timedelta(days=q.period))
                stable=not hasattr(self.repository,'revision') or self.repository.revision(end)==data.get('revision')
                if self._disk_cache and stable:
                    self._disk_cache.write(key,data['revision'],{**data,'prepared':entry['prepared'],'previous_prepared':entry['previous_prepared']})
                if not stable:
                    entry['checked']=entry['created']-121
            with self._lock:
                self._cache[entry['version']]=entry
                while len(self._cache)>3:self._cache.popitem(last=False)
            return entry

    def _prepared_dataset(self,q):
        # Published versions are durable DB identities, not process-local UUIDs.
        if q.force_refresh:
            with self._meta_lock:self._meta=None
        meta=self.meta()
        if q.version and not q.force_refresh and not q.data_date:
            try:meta=self.repository.metadata(q.version)
            except PreparedVersionMissing as exc:raise StaleAnalysis(str(exc)) from exc
        end=q.data_date or date.fromisoformat(meta['dates'][0])
        if q.force_refresh and end.isoformat() not in meta['dates']:end=date.fromisoformat(meta['dates'][0])
        version=q.version if q.version and not q.force_refresh else meta['published_batch']
        key=(version,end,q.period,q.view)
        with self._lock:
            entry=self._cache.get(key)
        if entry:return entry
        # One cold dataset load at a time keeps parallel tabs from filling RAM.
        with self._prepared_load_lock:
            with self._lock:entry=self._cache.get(key)
            if entry:return entry
            with self._lock:self._cache.clear()
            try:data=self.repository.load_prepared(end,q.period,q.view,version)
            except PreparedVersionMissing as exc:raise StaleAnalysis(str(exc)) from exc
            entry=dict(**data,date=end,start=end-timedelta(days=q.period-1),period=q.period,view=q.view,created=time.monotonic())
            with self._lock:
                self._cache[key]=entry
            return entry

    def _cohorts(self,q):
        data=self._dataset(q)
        children={c['id']:{i['id'] for i in c['children']} for c in data['categories']}
        for cond in q.conditions:
            if cond.kind=='label' and not set(cond.ids).issubset(children.get(cond.parent_id,set())):raise ValueError('标签不存在或大类归属不正确')
            if cond.kind=='label' and q.view=='business_unit' and next(c for c in data['categories'] if c['id']==cond.parent_id).get('scope')=='country':raise ValueError('国家标签请切换国家视角后分析')
        keyword=q.keyword.casefold().strip()
        rows=[r for r in data['prepared'] if (not q.country_categories or r['country_category'] in q.country_categories)
              and (not q.countries or r['country'] in q.countries) and (not q.stores or r['store'] in q.stores)
              and (not keyword or keyword in (' '.join([r['msku'],r['store'],r.get('sku','')])).casefold())]
        base,parent,current=select_cohorts(rows,[c.model_dump() for c in q.conditions])
        return data,base,parent,current

    @staticmethod
    def _context(data,q):
        return dict(version=data['version'],formula_version=VERSION,data_date=data['date'].isoformat(),
                    period=q.period,view=q.view,period_start=data['start'].isoformat(),sources=data['sources'],warnings=data['warnings'],
                    conditions=[c.model_dump() for c in q.conditions],baseline_description='当前国家/店铺/搜索范围，未应用标签及数值条件',
                    parent_description='移除最后一个条件组后的商品群体' if len(q.conditions)>1 else '与总体相同')

    def _aggregate(self,data,rows,previous=False):
        key=(previous,tuple(r['key'] for r in rows))
        with self._lock:
            cache=data.setdefault('aggregates',OrderedDict())
            found=cache.get(key)
            if found is not None:
                cache.move_to_end(key)
                return deepcopy(found)
        result=aggregate(rows)
        with self._lock:
            cache[key]=result
            while len(cache)>16:cache.popitem(last=False)
        return deepcopy(result)

    def summary(self,q):
        data,base,parent,current=self._cohorts(q)
        key=json.dumps(q.model_dump(mode='json',exclude={'version','force_refresh','page','page_size','sort','descending','object_key','export_kind'}),sort_keys=True)
        with self._lock:
            cache=data.setdefault('summaries',OrderedDict())
            if key in cache:
                cache.move_to_end(key)
                return deepcopy(cache[key])
        preset=self._summary_preset(q)
        saved=data.get('tag_summaries',{})
        baseline=deepcopy(saved['all',0,0]) if preset and ('all',0,0) in saved else self._aggregate(data,base)
        parent_metrics=deepcopy(baseline) if preset else self._aggregate(data,parent)
        now=deepcopy(saved[preset,0,0]) if preset and (preset,0,0) in saved else self._aggregate(data,current)
        # Existing immutable summaries predate the independent history domain.
        # Overlay only the newly attached metrics; business values stay frozen.
        for cells,members in ((baseline,base),(parent_metrics,parent),(now,current)):
            cells.update(aggregate(members,HISTORY_FIELDS))
        for k,m in METRICS.items():
            now[k]['overall_share']=safe_ratio(now[k]['value'],baseline[k]['value']) if m.share else None
            now[k]['parent_share']=safe_ratio(now[k]['value'],parent_metrics[k]['value']) if m.share else None
        by_tag=defaultdict(list)
        for r in current:
            for t in r['labels']:by_tag[t['parent_id'],t['id']].append(r)
        categories=[]
        for category in data['categories']:
            if q.view=='business_unit' and category.get('scope')=='country':continue
            children=[]
            for child in category['children']:
                members=by_tag[category['id'],child['id']]
                persisted=saved.get((preset,category['id'],child['id'])) if preset else None
                metrics={k:deepcopy(v) for k,v in persisted.items() if not q.columns or k in q.columns} if persisted is not None else aggregate(members,q.columns or None)
                history_columns=[k for k in HISTORY_FIELDS if not q.columns or k in q.columns]
                if history_columns:metrics.update(aggregate(members,history_columns))
                children.append({**child,'metrics':metrics,'count':len(members),'history_roles':role_distribution(members)})
            categories.append({**category,'children':children})
        selected_keys={r['key'] for r in current}
        previous=self._aggregate(data,[r for r in data['previous_prepared'] if r['key'] in selected_keys],previous=True)
        breakdowns={}
        for dim in ('store','country'):
            groups=defaultdict(list)
            for row in current:groups[row.get(dim) or '国家类别汇总'].append(row)
            breakdowns[dim]=[dict(label=k,metrics=aggregate(v)) for k,v in groups.items()]
        matrix=[]
        if len(q.matrix_parents)==2:
            a,b=q.matrix_parents
            if a==b or a not in children_map(data) or b not in children_map(data):raise ValueError('交叉大类无效')
            buckets=defaultdict(list)
            for r in current:
                aa={t['id'] for t in r['labels'] if t['parent_id']==a}; bb={t['id'] for t in r['labels'] if t['parent_id']==b}
                for x in aa:
                    for y in bb:buckets[x,y].append(r)
            matrix=[dict(row_id=x,column_id=y,metrics=aggregate(v)) for (x,y),v in buckets.items()]
        options=dict(stores=sorted({r['store'] for r in data['prepared']}),countries=sorted({r['country'] for r in data['prepared'] if r['country']}),country_categories=sorted({r['country_category'] for r in data['prepared']}))
        result={**self._context(data,q), 'baseline':baseline,'parent':parent_metrics,'current':now,'previous':previous,
                'comparison':compare_metrics(now,previous),'baseline_comparison':compare_metrics(now,baseline),'parent_comparison':compare_metrics(now,parent_metrics),
                'categories':categories,'coverage_distribution':coverage_distribution(current),'breakdowns':breakdowns,'matrix':matrix,'options':options,
                'capital':self._capital(base,current,data,q)}
        with self._lock:
            cache[key]=result
            while len(cache)>8:cache.popitem(last=False)
        return deepcopy(result)

    @staticmethod
    def _summary_preset(q):
        if q.country_categories or q.countries or q.stores or q.keyword.strip():return None
        if not q.conditions:return 'all'
        if len(q.conditions)==1:
            c=q.conditions[0]
            if c.kind=='metric' and c.metric=='fba_coverage_days' and c.op=='gt' and c.value==180:return 'over180'
        return None

    @staticmethod
    def _capital(base,current,data,q):
        # Only the quick-preset conditions are removed from the band comparison scope.
        scope=select_cohorts(base,[c.model_dump() for c in q.conditions if c.preset!='capital'])[2]
        fields=['object_count','unique_msku_count','inventory_cost','sellable_inventory_cost','ending_inventory_qty','sales_qty','sales_amount','order_gross_profit','sessions_total']
        def condition(metric,op,value=None,upper=None):
            return dict(kind='metric',metric=metric,op=op,value=value,upper=upper,preset='capital')
        definitions=[('short','3个月以内（≤90天）',[condition('fba_coverage_days','between',0,90)]),
                     ('medium','3—6个月（90—180天）',[condition('fba_coverage_days','range',90,180)]),
                     ('long','超过6个月（>180天）',[condition('fba_coverage_days','gt',180)]),
                     ('unknown','可售天数无法计算',[condition('fba_coverage_days','missing')])]
        def bucket(key,label,conditions):
            members=select_cohorts(scope,conditions)[2]
            return dict(key=key,label=label,conditions=conditions,metrics=aggregate(members,fields))
        bands=[bucket(*d) for d in definitions]
        gap_definitions=[
            ('no_performance','周期内无表现数据','当前经营周期未观察到有效经营或产品表现记录，且同日补货日销未覆盖；无记录补出的0不算实际记录。'),
            ('missing_daily_sales','有表现但缺日销','当前经营周期有有效经营或产品表现记录，但没有匹配同日补货日销。'),
            ('zero_daily_sales','日销为0','同日补货需求日销为0，无法计算库存÷日销；已有表现记录的0仍算实际记录。'),
            ('data_pending','数据待核','产品组需求、库存映射或数据异常需要核对，暂不能计算可售天数。')]
        gaps=[]
        for key,label,description in gap_definitions:
            item=bucket(key,label,[dict(kind='coverage',reason=key,preset='capital')])
            item['description']=description;gaps.append(item)
        zero=bucket('zero','有可售库存 · 完整需求日销为零',[condition('ending_inventory_qty','gt',0),condition('coverage_demand_daily_sales','eq',0)])
        structures=[]
        for category in data['categories']:
            if category['label'] not in ('销售角色','运营状态'):continue
            groups=[]
            for child in category['children']:
                members=[r for r in current if any(t['parent_id']==category['id'] and t['id']==child['id'] for t in r['labels'])]
                if members:groups.append(dict(id=child['id'],label=child['label'],metrics=aggregate(members,fields)))
            untagged=[r for r in current if not any(t['parent_id']==category['id'] for t in r['labels'])]
            if untagged:groups.append(dict(id=None,label='未匹配该类标签',metrics=aggregate(untagged,fields)))
            structures.append(dict(id=category['id'],label=category['label'],children=groups))
        ranks=[]
        for label,op,low,high in [('1—50名','between',1,50),('51—100名','range',50,100),('101—500名','range',100,500),('500名以后','gt',500,None),('排名未知 / 多国家','missing',None,None)]:
            c=dict(kind='metric',metric='small_category_rank',op=op,value=low,upper=high)
            ranks.append(dict(label=label,condition=c,metrics=aggregate(select_cohorts(current,[c])[2],fields)))
        return dict(scope=aggregate(scope,fields),bands=bands,coverage_gaps=gaps,zero_demand=zero,structures=structures,ranks=ranks)

    def details(self,q,all_rows=False):
        data,_,_,rows=self._cohorts(q)
        if q.object_key:rows=[r for r in rows if r['key']==q.object_key]
        def value(r):return r.get(q.sort) if q.sort in r else r['values'].get(q.sort)
        present=[r for r in rows if value(r) is not None]; missing=[r for r in rows if value(r) is None]
        rows=sorted(present,key=value,reverse=q.descending)+missing
        total=len(rows)
        if not all_rows:rows=rows[(q.page-1)*q.page_size:q.page*q.page_size]
        public=[]
        for row in rows:
            result={k:v for k,v in row.items() if not k.startswith('_') and k not in ('daily','traffic_daily','inventory','inventory_cost_daily','replenishment_history','replenishment','region_key')}
            if q.object_key:
                raw=self.repository.histories(data,[row])[0] if getattr(self.repository,'materialized',False) else row
                result['history']=[dict(date=d,**row_business_record(raw,d),inventory=raw['inventory'].get(d),zero_filled=d not in raw['daily']) for d in days_between(data['start'],data['date'])]
                result['replenishment']=raw.get('replenishment',{})
                if hasattr(self.repository,'evidence'):
                    with self._lock:
                        evidence=data.setdefault('evidence',OrderedDict())
                        if row['key'] not in evidence:
                            evidence[row['key']]=self.repository.evidence_from_history(row,raw) if hasattr(self.repository,'evidence_from_history') else self.repository.evidence(row,data['sources']['labels'],data['sources']['label_publication_time'])
                        while len(evidence)>64:evidence.popitem(last=False)
                        result['tag_evidence']=evidence[row['key']]
            public.append(result)
        return {**self._context(data,q),'rows':public,'total':total,'page':q.page,'page_size':q.page_size}

    def trends(self,q):
        # Only one trend archive scan per process; other endpoints remain free.
        with self._trend_lock:
            return self._stream_trends(q)

    def _stream_trends(self,q):
        data,_,_,rows=self._cohorts(q); keys={r['key'] for r in rows}
        if getattr(self.repository,'materialized',False):
            raw=self.repository.iter_histories(data,rows) if hasattr(self.repository,'iter_histories') else iter(self.repository.histories(data,rows))
        else:
            raw=(r for r in data['rows'] if r['key'] in keys)
        fields=[k for k,m in METRICS.items() if m.trend]
        daily_fields=[field for field in fields if field in DAILY_FIELDS]
        dates=days_between(data['start']-timedelta(days=q.period),data['date'])
        points=[{'date':d,'valid_objects':0,'coverage':{field:{'valid_count':0,'total_count':0,'zero_filled_count':0} for field in daily_fields},**{field:0 for field in daily_fields}} for d in dates]
        # One compact double vector per pool; inf means no membership on that day,
        # nan means observed membership with unknown or conflicting stock.
        pools={}; unseen=float('inf'); unknown=float('nan')
        for row in raw:
            calendars={field:metric_calendar(row,field) for field in daily_fields}
            for offset,d in enumerate(dates):
                point=points[offset]; record=row_business_record(row,d)
                for field in daily_fields:
                    value=number(record.get(field)); coverage=point['coverage'][field]
                    coverage['total_count']+=1
                    if value is not None:
                        point[field]+=value; coverage['valid_count']+=1
                        coverage['zero_filled_count']+=d not in calendars[field]
                snapshot=row.get('replenishment_history',{}).get(d,{})
                pool=snapshot.get('pool_id',row['pool_id'])
                vector=pools.get(pool)
                if vector is None:vector=pools[pool]=array('d',[unseen])*len(dates)
                value=number(row['inventory'].get(d))
                value=value if value is not None and value>=0 else unknown
                old=vector[offset]
                if old==unseen:vector[offset]=value
                elif not isfinite(old) or not isfinite(value) or old!=value:vector[offset]=unknown
        for offset,point in enumerate(points):
            for field in daily_fields:
                if not point['coverage'][field]['valid_count']:point[field]=None
            point['valid_objects']=point['coverage']['sales_qty']['valid_count']
            total=valid=0; quantity=0
            for vector in pools.values():
                value=vector[offset]
                if value==unseen:continue
                total+=1
                if isfinite(value):quantity+=value;valid+=1
            point['ending_inventory_qty']=quantity if valid else None
            point['coverage']['ending_inventory_qty']={'valid_count':valid,'total_count':total}
        return {**self._context(data,q),'member_count':len(keys),'current':points[q.period:],'previous':points[:q.period]}
    def export(self,q):
        columns=q.columns or [k for k,m in METRICS.items() if k not in ('coverage_demand_daily_sales','small_category_rank') and m.available and m.aggregation not in ('count','custom')]
        output=StringIO(); writer=csv.writer(output)
        safe=lambda v: "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
        import json
        scope=json.dumps(q.model_dump(mode='json',include={'country_categories','countries','stores','keyword','conditions'}),ensure_ascii=False)
        if q.export_kind=='summary':
            p=self.summary(q)
            writer.writerow(['数据日期','数据版本','视角','经营周期','条件','标签大类','子标签']+[METRICS[k].label for k in columns]+['历史主导角色构成（商品数）'])
            for group in p['categories']:
                for child in group['children']:writer.writerow([p['data_date'],p['version'],q.view,q.period,safe(scope),safe(group['label']),safe(child['label'])]+[child['metrics'][k]['value'] for k in columns]+[' / '.join(f"{r['label']}:{r['count']}" for r in child['history_roles'] if r['count'])])
        else:
            p=self.details(q,True)
            writer.writerow(['数据日期','数据版本','视角','经营周期','条件','国家类别','国家','店铺','MSKU','销售角色','运营状态','库存池','补货需求对象','日销日期','覆盖状态','覆盖计算库存（完整需求）','日销汇总值（按需求对象去重）','补货支持库存汇总值（按需求对象去重）']+[METRICS[k].label for k in columns]+['历史主导角色'])
            for row in p['rows']:
                roles=lambda parent:' / '.join(t.get('label',str(t['id'])) for t in row['labels'] if t['parent_id']==parent)
                writer.writerow([p['data_date'],p['version'],q.view,q.period,safe(scope),safe(row['country_category']),safe(row.get('country','')),safe(row['store']),safe(row['msku']),safe(roles(1)),safe(roles(3)),safe(row.get('pool_id','')),safe(row.get('demand_id','')),row.get('replenishment_source_date'),row.get('coverage_reason'),row.get('coverage_inventory_qty'),row.get('aggregate_values',{}).get('replenishment_daily_sales',row['values'].get('replenishment_daily_sales')),row.get('aggregate_values',{}).get('support_inventory_qty',row['values'].get('support_inventory_qty'))]+[row['values'].get(k) for k in columns]+[safe(roles(PARENT_ID))])
        return '\ufeff'+output.getvalue()


def children_map(data):
    return {c['id']:c['children'] for c in data['categories']}


label_analysis_service=LabelAnalysisService()
