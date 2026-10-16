"""补充问题产品动作输入，全部为只读查询。"""
import json
import argparse
from pathlib import Path
from inspect_sources import connect
from extract_inputs import write_json

ROOT = Path('outputs/20260921-162402')

def main():
    global ROOT
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    ROOT=args.root
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    label_date=str(manifest['sources']['labels']['date'])
    bid_date=str(manifest['sources']['bid_objects']['date'])
    term_date=str(manifest['sources']['search_terms']['date'])
    base = json.loads((ROOT/'product_base.json').read_text(encoding='utf-8'))
    skus = sorted({r['msku'] for r in base if r['source_roles'] == ['problem']})
    results = {}
    with connect() as conn, conn.cursor() as cur:
        def query(sql, args=()):
            cur.execute(sql, args)
            return cur.fetchall()
        def batches(sql, prefix=()):
            rows=[]
            for offset in range(0,len(skus),300):
                part=skus[offset:offset+300]
                rows.extend(query(sql.format(marks=','.join(['%s']*len(part))),(*prefix,*part)))
            return rows
        print('metrics',flush=True)
        dt=query('select max(data_date) as dt from dws_datasync.ops_product_site_metric_period where period_days=30 and data_date<=%s',(label_date,))[0]['dt']
        results['metrics']=batches('select data_date,period_days,country,store,msku,asin,sales_volume,avg_daily_sales,settlement_gross_margin,tacos,ad_spend,fba_available_inventory,inventory_snapshot_time,currency_code from dws_datasync.ops_product_site_metric_period where period_days=30 and data_date=%s and msku in ({marks})',(dt,))
        print('mature attribution',flush=True)
        results['bid_attribution']=batches('select row_key,same_sku_attributed_orders_7d,same_sku_attributed_sales_7d from dws_datasync.dws_sp_bid_object_snapshot_daily where snapshot_date=%s and msku in ({marks})',(bid_date,))
        results['term_attribution']=batches('select row_key,orders_7d,sales_7d,same_orders_7d,same_sales_7d,attribution_7d_mature from dws_datasync.dws_sp_search_term_analysis_daily where snapshot_date=%s and msku in ({marks})',(term_date,))
        print('current entities',flush=True)
        results['accounts']=query('select id,profile_id,country_code,currency_code,name,delete_flag,create_time,update_time from ods_datasync.lx_advertising_account_list')
        results['product_ads']=batches('select id,profile_id,campaign_id,ad_group_id,ad_id,state,sku,asin,serving_status,seller_name,delete_flag,create_time,update_time from ods_datasync.lx_advertising_sp_product_ads where sku in ({marks})')
        profiles=sorted({str(r['profile_id']) for r in results['product_ads'] if r['profile_id']})
        for name,table,id_column in [('campaigns','lx_advertising_sp_campaigns','campaign_id'),('ad_groups','lx_advertising_sp_ad_groups','ad_group_id')]:
            results[name]=[]
            for offset in range(0,len(profiles),100):
                part=profiles[offset:offset+100]
                extra=',targeting_type' if name=='campaigns' else ''
                results[name].extend(query(f'select id,profile_id,campaign_id,{id_column} as entity_id,state,serving_status,delete_flag,create_time,update_time{extra} from ods_datasync.{table} where profile_id in ('+','.join(['%s']*len(part))+')',part))
        print('support complete',flush=True)
    for name,rows in results.items():
        write_json(ROOT/f'support_{name}.json',rows)
    print(json.dumps({name:len(rows) for name,rows in results.items()},ensure_ascii=False),flush=True)

if __name__ == '__main__': main()
