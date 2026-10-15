"""Historical-role contracts and immutable intranet snapshot reader."""
from collections import Counter
import json
import sys

PARENT_ID = 9001
FORMULA_VERSION = 'history-role-asof-v1'
ROLES = ((101,'star','明星产品'),(102,'potential','潜力产品'),(103,'dog','瘦狗产品'),(104,'problem','问题产品'))
HISTORY_FIELDS = ('history_valid_segments','history_excluded_segments',*(f'history_{name}_{suffix}' for _,name,_ in ROLES for suffix in ('count','share')))


def category(view='business_unit'):
    rule='截至分析日期，有效完整30天段中出现次数最多的角色；同次数取最近有效段。'
    return dict(id=PARENT_ID,label='历史主导角色',scope=view,children=[
        dict(id=PARENT_ID*100+role,label=label,enabled=True,rule=rule) for role,_,label in ROLES
    ]+[dict(id=PARENT_ID*100,label='暂未形成主导角色',enabled=True,rule='没有有效完整历史周期或未匹配历史来源；不标为问题产品。')])


def role_tag(role):
    role = role if role in (101,102,103,104) else 0
    label=next((label for code,_,label in ROLES if code==role),'暂未形成主导角色')
    return dict(id=PARENT_ID*100+role,parent_id=PARENT_ID,label=label,period='history',country='')


def summarize_periods(periods, cutoff):
    """Source-computed eligibility is authoritative; only completed as-of votes count."""
    cutoff=str(cutoff)[:10];counts=Counter();last={};excluded=0;seen=set()
    for node in periods:
        start=node.get('start');end=node.get('end');no=node.get('no')
        if not start or not end or start>cutoff:continue
        if no in seen:raise ValueError('历史角色周期编号重复')
        seen.add(no)
        role=node.get('role_id')
        role=role-1200 if role in (1301,1302,1303,1304) else role
        if end<=cutoff and node.get('complete')==1 and node.get('eligible')==1 and role in (101,102,103,104):
            counts[role]+=1;last[role]=max(last.get(role,0),int(no))
        else:excluded+=1
    total=sum(counts.values());dominant=max(counts,key=lambda role:(counts[role],last[role])) if total else None
    values={'history_valid_segments':total,'history_excluded_segments':excluded}
    for role,name,_ in ROLES:
        values[f'history_{name}_count']=counts[role]
        values[f'history_{name}_share']=counts[role]/total if total else None
    return dict(dominant_role_id=dominant,values=values,as_of_date=cutoff)


def snapshot_meta(cur,batch):
    cur.execute("select batch_id,source_date,formula_version,state,row_count from dashboard_analysis_role_snapshot where batch_id=%s and state='ready'",(batch,))
    return cur.fetchone()


def attach_snapshot(cur,batch,cutoff,view,rows):
    cur.execute('select object_key,result_json from dashboard_analysis_role_result where batch_id=%s and as_of_date=%s and view_kind=%s',(batch,cutoff,view))
    results={r['object_key']:json.loads(r['result_json'],object_hook=lambda obj:{sys.intern(k):v for k,v in obj.items()}) if isinstance(r['result_json'],(str,bytes)) else r['result_json'] for r in cur.fetchall()}
    for row in rows:
        history=results.get(row['key'])
        row['values'].update(dict.fromkeys(HISTORY_FIELDS))
        if history:row['values'].update(history['values'])
        row['role_history']=history
        row['labels']=[t for t in row['labels'] if t['parent_id']!=PARENT_ID]+[role_tag(history.get('dominant_role_id') if history else None)]
    return len(results)


def role_distribution(rows):
    counts=Counter((row.get('role_history') or {}).get('dominant_role_id') or 0 for row in rows)
    return [dict(role_id=role,label=role_tag(role)['label'],count=counts[role],tag_id=PARENT_ID*100+role) for role in (101,102,103,104,0)]
