"""Apply the approved receiving-shipment stockout rule to uncovered products."""

from datetime import timedelta
import json
from etl.label_local_sql import WORK_TABLE
from etl.label_local_store import table

VERSION = "v47_operation_status_receiving_stockout_20261008"


def complete_operations(conn, schema, day, *, input_schema=None):
    inputs = input_schema or schema
    work = table(schema, WORK_TABLE)
    added = 0
    with conn.cursor() as q:
        q.execute(
            f"""select distinct a.country_category,a.store,a.msku from {work} a
            where a.data_date=%s and a.label_id between 101 and 104
            and not exists(select 1 from {work} b where b.data_date=a.data_date
              and b.country_category=a.country_category and b.store=a.store and b.msku=a.msku
              and b.label_id between 301 and 308)""",
            (day,),
        )
        missing = q.fetchall()
        for key in missing:
            args = (key["msku"], key["store"], key["country_category"])
            q.execute(
                f"""with ranked as (
                select shipment_id,upper(trim(shipment_status)) as status,
                    row_number() over(partition by trim(shipment_id) order by coalesce(
                    str_to_date(left(cast(gmt_modified as char),19),'%%Y-%%m-%%d %%H:%%i:%%s'),
                    case when upper(trim(shipment_status))='WORKING' then str_to_date(left(cast(working_time as char),19),'%%Y-%%m-%%d %%H:%%i:%%s') end,
                    str_to_date(left(cast(gmt_create as char),19),'%%Y-%%m-%%d %%H:%%i:%%s'),
                    str_to_date(left(cast(create_time as char),19),'%%Y-%%m-%%d %%H:%%i:%%s')) desc,cast(id as unsigned) desc) as rn
                from {table(inputs,'dashboard_label_source_shipment')}
                where msku=%s and substring_index(substring_index(seller,' ',1),'-',1)=%s
                  and case when country='英国' then '英国站' when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end=%s
                  and nullif(trim(shipment_id),'') is not null and nullif(trim(shipment_status),'') is not null)
                select shipment_id from ranked where rn=1 and status='RECEIVING' """,
                args,
            )
            receiving = q.fetchall()
            q.execute(
                f"""with scoped as (
                select create_time,afn_fulfillable_quantity,stock_up_num,
                    max(create_time) over() as latest_time
                from {table(inputs,'dashboard_label_source_fba')}
                where seller_sku_adj=%s and substring_index(substring_index(seller_name_new,' ',1),'-',1)=%s
                  and country_category=%s and create_time<%s)
                select max(latest_time) as snapshot_time,sum(coalesce(afn_fulfillable_quantity,0)) as available,
                    sum(coalesce(stock_up_num,0)) as in_transit from scoped where create_time=latest_time""",
                (*args, day + timedelta(days=1)),
            )
            fba = q.fetchone()
            if not receiving or (fba["available"] or 0) != 0:
                raise RuntimeError(
                    f"uncovered operating status does not match receiving stockout rule: {key}"
                )
            evidence = {
                "schema_version": "1.0",
                "rule_version": VERSION,
                "type": "operation_status",
                "window": {"end": str(day)},
                "operation_status": "断货中",
                "metrics": {
                    "fba_available": float(fba["available"] or 0),
                    "fba_in_transit": float(fba["in_transit"] or 0),
                    "has_receiving_shipment": 1,
                    "receiving_shipment_ids": [r["shipment_id"] for r in receiving],
                    "fba_snapshot_time": (
                        str(fba["snapshot_time"]) if fba["snapshot_time"] else None
                    ),
                },
                "matched_rule": {
                    "operation_status": "断货中",
                    "fba_available": "= 0",
                    "has_receiving_shipment": "= 1",
                    "supply_quantity": "not_required_when_receiving",
                },
                "inventory_source": "dwd_datasync.lx_storage_fba_warehouse_detail",
            }
            q.execute(
                f"""insert into {work}
                (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_json)
                values(%s,%s,null,%s,%s,304,'current',current_timestamp(6),%s)""",
                (
                    day,
                    key["country_category"],
                    key["store"],
                    key["msku"],
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
            added += 1
        q.execute(
            f"""select count(*) as n from (
            select r.country_category,r.store,r.msku from
              (select distinct country_category,store,msku from {work} where data_date=%s and label_id between 101 and 104) r
            left join {work} o on o.data_date=%s and o.country_category=r.country_category
              and o.store=r.store and o.msku=r.msku and o.label_id between 301 and 308
            group by r.country_category,r.store,r.msku having count(o.label_id)<>1) invalid""",
            (day, day),
        )
        if q.fetchone()["n"]:
            raise RuntimeError(
                "operating status must cover every sales-role product exactly once"
            )
    return {"operation_added_rows": added, "operation_coverage_verified": True}
