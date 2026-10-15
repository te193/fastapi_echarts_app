"""Local operating state for the first shipment being received by Amazon."""

from datetime import date, datetime
import json
from etl.label_local_sql import WORK_TABLE
from etl.label_local_store import table

VERSION = "v47_operation_receiving_first_launch_20261009"
ID = 308
RULE = "本店铺只有一个历史货件、未出现过正可售库存，且最新货件接收中、当前可售为0；首次接收超过30天的商品继续按老品规则判断"


def receiving_classification(shipment_count, has_prior_sellable, first_receiving, day):
    recent = first_receiving is None or (day - first_receiving).days <= 30
    return 308 if shipment_count == 1 and not has_prior_sellable and recent else 304


def validate_extension_id(conn, schema):
    with conn.cursor() as q:
        q.execute(
            f"select sub_label_id from {table(schema,'dashboard_label_source_dictionary')} where sub_label_id=308"
        )
        if q.fetchone():
            raise RuntimeError(
                "local operating ID 308 is occupied by source dictionary; publication blocked"
            )


def extension_details(conn, schema):
    from etl.label_lifecycle_completion import DETAIL_COLUMNS

    validate_extension_id(conn, schema)
    with conn.cursor() as q:
        q.execute(
            f"select {','.join(DETAIL_COLUMNS)} from {table(schema,'dashboard_label_source_dictionary')} where sub_label_id=304"
        )
        template = q.fetchone()
    if not template:
        return []
    return [
        {
            **template,
            "sub_label_id": 308,
            "sub_label_name": "入库接收中",
            "tag_rule": RULE,
            "business_definition": "首次上新货件进入亚马逊接收阶段，但尚无可售库存；老品补货仍归断货中。"
            + RULE,
            "status": "启用",
            "tagging_method": "auto_sql",
            "create_time": datetime(2026, 10, 9),
        }
    ]


def apply_receiving_status(conn, schema, day, *, input_schema=None):
    inputs = input_schema or schema
    validate_extension_id(conn, inputs)
    work = table(schema, WORK_TABLE)
    changed = 0
    first_wave = 0
    old = 0
    with conn.cursor() as q:
        q.execute(
            f"""select country_category,store,msku,label_id,evidence_json from {work}
            where data_date=%s and (label_id=308 or (label_id=304
            and json_extract(evidence_json,'$.metrics.has_receiving_shipment')=1))""",
            (day,),
        )
        candidates = q.fetchall()
        for row in candidates:
            args = (row["msku"], row["store"], row["country_category"])
            q.execute(
                f"""with scoped as (
                select shipment_id,upper(trim(shipment_status)) as status,receiving_time,
                    row_number() over(partition by trim(shipment_id) order by coalesce(
                    str_to_date(left(cast(gmt_modified as char),19),'%%Y-%%m-%%d %%H:%%i:%%s'),
                    case when upper(trim(shipment_status))='WORKING' then str_to_date(left(cast(working_time as char),19),'%%Y-%%m-%%d %%H:%%i:%%s') end,
                    str_to_date(left(cast(gmt_create as char),19),'%%Y-%%m-%%d %%H:%%i:%%s'),
                    str_to_date(left(cast(create_time as char),19),'%%Y-%%m-%%d %%H:%%i:%%s')) desc,cast(id as unsigned) desc) as rn
                from {table(inputs,'dashboard_label_source_shipment')}
                where msku=%s and substring_index(substring_index(seller,' ',1),'-',1)=%s
                    and case when country='英国' then '英国站' when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end=%s
                    and nullif(trim(shipment_id),'') is not null and nullif(trim(shipment_status),'') is not null)
                select count(distinct trim(shipment_id)) as shipment_count,
                    sum(rn=1 and status='RECEIVING') as receiving_count,
                    min(case when cast(receiving_time as char) regexp '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                    then str_to_date(left(cast(receiving_time as char),10),'%%Y-%%m-%%d') end) as first_receiving from scoped""",
                args,
            )
            ship = q.fetchone()
            if not ship["receiving_count"]:
                raise RuntimeError(
                    f"receiving evidence disagrees with frozen shipment source: {args}"
                )
            q.execute(
                f"""select min(create_time) as history_start,
                max(coalesce(afn_fulfillable_quantity,0)>0) as had_sellable
                from {table(inputs,'dashboard_label_source_fba')} where seller_sku_adj=%s
                and substring_index(substring_index(seller_name_new,' ',1),'-',1)=%s and country_category=%s
                and create_time<date_add(%s,interval 1 day)""",
                (*args, day),
            )
            stock = q.fetchone()
            ev = (
                json.loads(row["evidence_json"])
                if isinstance(row["evidence_json"], str)
                else row["evidence_json"]
            )
            if ev["metrics"].get("fba_available") != 0:
                raise RuntimeError(
                    "receiving state requires zero current sellable inventory"
                )
            child = receiving_classification(
                ship["shipment_count"],
                bool(stock["had_sellable"]),
                ship["first_receiving"],
                day,
            )
            name = "入库接收中" if child == 308 else "断货中"
            ev.update(rule_version=VERSION, operation_status=name)
            ev["metrics"].update(
                historical_shipment_count=ship["shipment_count"],
                has_prior_sellable=bool(stock["had_sellable"]),
                first_receiving_date=(
                    str(ship["first_receiving"]) if ship["first_receiving"] else None
                ),
                inventory_history_start=(
                    str(stock["history_start"]) if stock["history_start"] else None
                ),
            )
            ev["matched_rule"].update(operation_status=name, first_launch=child == 308)
            q.execute(
                f"""update {work} set label_id=%s,evidence_json=%s,created_time=current_timestamp(6)
                where data_date=%s and country_category=%s and store=%s and msku=%s and label_id=%s""",
                (
                    child,
                    json.dumps(ev, ensure_ascii=False),
                    day,
                    row["country_category"],
                    row["store"],
                    row["msku"],
                    row["label_id"],
                ),
            )
            changed += child != row["label_id"]
            first_wave += child == 308
            old += child == 304
    return {
        "receiving_reclassified_rows": changed,
        "first_launch_receiving_rows": first_wave,
        "old_receiving_stockout_rows": old,
    }
