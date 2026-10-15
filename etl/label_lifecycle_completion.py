"""Local lifecycle coverage policy approved on 2026-10-09."""
from datetime import date, datetime
from etl.label_local_store import table
from etl.label_local_sql import WORK_TABLE

VERSION = "local_v47_lifecycle_coverage_20261009"
IDS = (206, 207)
DETAIL_COLUMNS = "label_id,label_name,sub_label_id,sub_label_name,tag_rule,business_definition,business_owner,label_category,update_frequency,mutual_exclusion,status,create_time,tagging_method".split(',')


def validate_extension_ids(conn, input_schema: str) -> None:
    with conn.cursor() as q:
        q.execute(f"select sub_label_id from {table(input_schema,'dashboard_label_source_dictionary')} where sub_label_id in (206,207)")
        if q.fetchall():
            raise RuntimeError("local lifecycle IDs 206/207 are occupied by source dictionary; publication blocked")


def extension_details(conn, input_schema: str) -> list[dict]:
    validate_extension_ids(conn,input_schema)
    with conn.cursor() as q:
        q.execute(f"select {','.join(DETAIL_COLUMNS)} from {table(input_schema,'dashboard_label_source_dictionary')} where sub_label_id=201")
        template=q.fetchone()
    if not template:
        raise RuntimeError('lifecycle metadata template 201 missing')
    rows=[]
    for child,name,rule in [
        (206,'归档产品','同批销售角色商品未命中原生命周期，且运营状态为停售'),
        (207,'生命周期待判定','同批销售角色商品未命中原生命周期，且运营状态不是停售或缺失'),
    ]:
        rows.append({**template,'label_id':2,'label_name':'生命周期','sub_label_id':child,
                     'sub_label_name':name,'tag_rule':rule,
                     'business_definition':rule+'；不编造首次收货日期，仅为标签分类，每日重新判断',
                     'status':'启用','tagging_method':'auto_sql','create_time':datetime(2026,10,9)})
    return rows



def shipment_projection(inputs: str) -> str:
    shipment=table(inputs,'dashboard_label_source_shipment')
    return f"""                select case when country='英国' then '英国站'
                    when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end collate utf8mb4_0900_ai_ci as country_category,
                    substring_index(substring_index(cast(seller as char),' ',1),'-',1) collate utf8mb4_0900_ai_ci as store,
                    cast(msku as char) collate utf8mb4_0900_ai_ci as msku,count(*) as shipment_n,
                    min(case when cast(receiving_time as char) regexp '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                        then str_to_date(left(cast(receiving_time as char),10),'%%Y-%%m-%%d') end) as first_receiving
                from {shipment} group by 1,2,3"""


def complete_day(conn, schema: str, day: date, *, input_schema: str | None = None) -> dict:
    inputs=input_schema or schema
    validate_extension_ids(conn,inputs)
    work=table(schema,WORK_TABLE)
    with conn.cursor() as q:
        # Refresh only our derived classifications; original phases stay intact.
        q.execute(f"delete from {work} where data_date=%s and label_id in (206,207)",(day,))
        q.execute(f"""insert into {work}
            (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_json)
            with settings as (select cast(%s as date) as d,%s as version),
            roles as (
                select distinct country_category,store,msku from {work},settings
                where data_date=settings.d and label_id in (101,102,103,104)
            ), missing as (
                select r.* from roles r cross join settings
                where not exists (select 1 from {work} l where l.data_date=settings.d
                    and l.country_category=r.country_category and l.store=r.store and l.msku=r.msku
                    and l.label_id between 201 and 205)
            ), operations as (
                select country_category,store,msku,max(label_id) as operation_id from {work},settings
                where data_date=settings.d and label_id between 301 and 308 group by country_category,store,msku
            ), ships as ({shipment_projection(inputs)})
            select settings.d,m.country_category,null,m.store,m.msku,
                if(o.operation_id=306,206,207),'current',current_timestamp(6),
                json_object('schema_version','1.0','rule_version',settings.version,
                    'type','lifecycle_coverage','label_id',if(o.operation_id=306,206,207),
                    'classification',if(o.operation_id=306,'归档产品','生命周期待判定'),
                    'operation_status_id',o.operation_id,
                    'first_receiving_date',if(s.first_receiving<=settings.d,date_format(s.first_receiving,'%%Y-%%m-%%d'),null),
                    'candidate_first_receiving_date',date_format(s.first_receiving,'%%Y-%%m-%%d'),
                    'reason',case when s.shipment_n is null then 'no_matching_shipment'
                        when s.first_receiving is null then 'no_valid_receiving_date'
                        when s.first_receiving>settings.d then 'receiving_after_label_date'
                        else 'original_lifecycle_not_matched' end,
                    'matched_rule',if(o.operation_id=306,'原生命周期未命中且当前停售','原生命周期未命中且当前非停售或运营状态缺失'),
                    'receiving_source','dwd_datasync.lx_fba_shipment','data_date',date_format(settings.d,'%%Y-%%m-%%d'))
            from missing m cross join settings
            left join operations o using(country_category,store,msku)
            left join ships s using(country_category,store,msku)
            """,(day,VERSION))
        added=q.rowcount
    return {'lifecycle_added_rows':added,**validate_coverage(conn,schema,day,input_schema=inputs)}


def validate_coverage(conn, schema: str, day: date, *, input_schema: str | None = None, check_source_evidence: bool = True) -> dict:
    work=table(schema,WORK_TABLE)
    # Retained archives are validated against their own stored evidence and checksum.
    source_checks = """            or coalesce(json_unquote(json_extract(w.evidence_json,'$.first_receiving_date')),'')<>
                coalesce(if(s.first_receiving<=w.data_date,date_format(s.first_receiving,'%%Y-%%m-%%d'),null),'null')
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.candidate_first_receiving_date')),'')<>
                coalesce(date_format(s.first_receiving,'%%Y-%%m-%%d'),'null')
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.reason')),'')<>
                case when s.shipment_n is null then 'no_matching_shipment'
                    when s.first_receiving is null then 'no_valid_receiving_date'
                    when s.first_receiving>w.data_date then 'receiving_after_label_date'
                    else 'original_lifecycle_not_matched' end
""" if check_source_evidence else ''
    with conn.cursor() as q:
        q.execute(f"""select count(*) as n from (
            select r.country_category,r.store,r.msku from
                (select distinct country_category,store,msku from {work}
                 where data_date=%s and label_id in (101,102,103,104)) r
            left join {work} l on l.data_date=%s and l.country_category=r.country_category
                and l.store=r.store and l.msku=r.msku and l.label_id between 201 and 207
            group by r.country_category,r.store,r.msku having count(l.label_id)<>1
            ) invalid""",(day,day))
        if q.fetchone()['n']:
            raise RuntimeError('lifecycle coverage must have exactly one classification per sales-role business key')
        q.execute(f"""with ships as ({shipment_projection(input_schema or schema)}),
            operations as (select country_category,store,msku,max(label_id) as operation_id
                from {work} where data_date=%s and label_id between 301 and 308
                group by country_category,store,msku)
            select count(*) as n from {work} w
            left join operations o using(country_category,store,msku)
            left join ships s using(country_category,store,msku)
            where w.data_date=%s and w.label_id in (206,207) and (
            w.label_period<>'current'
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.rule_version')),'')<>%s
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.label_id')),'')<>cast(w.label_id as char)
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.classification')),'')<>if(w.label_id=206,'归档产品','生命周期待判定')
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.data_date')),'')<>cast(w.data_date as char)
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.operation_status_id')),'')<>coalesce(cast(o.operation_id as char),'null')
            {source_checks}
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.matched_rule')),'')<>
                if(o.operation_id=306,'原生命周期未命中且当前停售','原生命周期未命中且当前非停售或运营状态缺失')
            or coalesce(json_unquote(json_extract(w.evidence_json,'$.receiving_source')),'')<>'dwd_datasync.lx_fba_shipment'
            or (w.label_id=206)<>exists(select 1 from {work} op where op.data_date=w.data_date
                and op.country_category=w.country_category and op.store=w.store and op.msku=w.msku and op.label_id=306)
            or not exists(select 1 from {work} r where r.data_date=w.data_date and r.country_category=w.country_category
                and r.store=w.store and r.msku=w.msku and r.label_id in (101,102,103,104))
            )""",(day,day,VERSION))
        if q.fetchone()['n']:
            raise RuntimeError('lifecycle completion evidence or classification disagrees with same-batch inputs')
        q.execute(f"""select
            count(distinct case when label_id in (101,102,103,104) then concat_ws('|',country_category,store,msku) end) as sales_role_units,
            count(distinct case when label_id between 201 and 207 then concat_ws('|',country_category,store,msku) end) as lifecycle_units,
            count(distinct case when label_id in (101,102,103,104) then msku end) as sales_role_unique_msku,
            count(distinct case when label_id between 201 and 207 then msku end) as lifecycle_unique_msku
            from {work} where data_date=%s""",(day,))
        return q.fetchone()
