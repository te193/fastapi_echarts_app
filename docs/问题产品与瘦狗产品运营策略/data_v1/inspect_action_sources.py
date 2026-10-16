from inspect_sources import connect
from extract_inputs import write_json
from pathlib import Path
from collections import Counter
import json

root = Path('outputs/20260921-162402')
tables = [
    ('dws_datasync', 'ops_product_site_metric_period'),
    ('ods_datasync', 'lx_advertising_account_list'),
    ('ods_datasync', 'lx_advertising_sp_product_ads'),
    ('ods_datasync', 'lx_advertising_sp_campaigns'),
    ('ods_datasync', 'lx_advertising_sp_ad_groups'),
    ('ods_datasync', 'lx_advertising_sp_product_ad_reports'),
]
result = {}
with connect() as conn, conn.cursor() as cur:
    for schema, table in tables:
        cur.execute('select column_name,column_type,column_comment from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position',(schema,table))
        result[f'{schema}.{table}'] = [{k.lower():v for k,v in r.items()} for r in cur.fetchall()]
write_json(root/'action_source_schema.json',result)
for name in ['pricing','cost','bid_objects','search_terms']:
    rows=json.loads((root/f'{name}.json').read_text(encoding='utf-8'))
    fields = {'pricing':['币种','价格备注','数据异常备注','含广告定价异常备注'],
              'cost':['统计窗口开始日期','统计窗口结束日期','成本状态','对账状态'],
              'bid_objects':['object_type','targeting_type','campaign_state_current','campaign_serving_status','ad_group_state_current','object_state_current','object_serving_status','source_keyword_days','source_ad_group_days','source_product_ad_days','bid_lower_limit','bid_upper_limit'],
              'search_terms':['campaign_state_current','ad_group_state_current','target_state_current','search_term_type','attribution_30d_mature']}[name]
    print(name, {field:Counter(str(row[field]) for row in rows).most_common(8) for field in fields},flush=True)
print('schema complete',flush=True)
