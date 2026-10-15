"""Local V47 work tables, compressed history, and transactional publication."""

from __future__ import annotations

from datetime import date
import hashlib
import json
import zlib

from etl.label_local_sql import BASELINE_SHA256, RULE_VERSION, WORK_TABLE, checked_schema, quote


FACT_COLUMNS = ("data_date", "country_category", "country", "store", "msku", "label_id", "label_period", "created_time", "evidence_json")


def table(schema: str, name: str) -> str:
    checked_schema(schema)
    if not name.startswith("dashboard_label_"):
        raise ValueError("not a local label table")
    return f"{quote(schema)}.{quote(name)}"


def encode_history_chunk(rows: list) -> tuple[bytes, str]:
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return zlib.compress(raw), hashlib.sha256(raw).hexdigest()


def decode_history_chunk(payload: bytes, checksum: str) -> list:
    raw = zlib.decompress(payload)
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise ValueError("local history checksum mismatch")
    return json.loads(raw)


def prepare_tables(conn, schema: str) -> None:
    work = table(schema, WORK_TABLE)
    statements = [
        f"""create table if not exists {work} (
            id bigint unsigned not null auto_increment primary key,
            data_date date not null, country_category varchar(20), country varchar(100),
            store varchar(100) not null, msku varchar(500) not null,
            label_id int not null, label_period varchar(20) not null,
            created_time datetime not null default current_timestamp, evidence_json json,
            key idx_dt(data_date), key idx_date_label(data_date,label_id,label_period),
            key idx_unit(data_date,country_category,store(80),msku(120),label_id,label_period)
        ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci""",
        f"""create table if not exists {table(schema,'dashboard_label_local_execution_log')} (
            id int not null auto_increment primary key, proc_name varchar(255) not null,
            start_time datetime not null, end_time datetime, data_time datetime,
            record_count int, status varchar(20) not null,
            create_time timestamp default current_timestamp
        ) engine=innodb default charset=utf8mb4""",
        f"""create table if not exists {table(schema,'dashboard_label_local_error_log')} (
            id int not null auto_increment primary key, proc_name varchar(255) not null,
            error_time datetime not null, error_message text not null, execution_log_id int
        ) engine=innodb default charset=utf8mb4""",
        f"""create table if not exists {table(schema,'dashboard_label_local_select_log')} (
            id bigint unsigned not null auto_increment primary key, execution_log_id int not null,
            data_time date, select_no int not null, select_name varchar(255) not null,
            statement_type varchar(40) not null, source_line int, sql_start_time datetime(6) not null,
            sql_end_time datetime(6), elapsed_seconds decimal(18,6), affected_rows bigint,
            status varchar(20) not null default 'running', connection_id bigint, error_message text,
            create_time timestamp not null default current_timestamp,
            key idx_execution(execution_log_id,select_no)
        ) engine=innodb default charset=utf8mb4""",
        f"""create table if not exists {table(schema,'dashboard_label_local_history')} (
            data_date date not null, chunk_no int not null, row_count int not null,
            payload longblob not null, checksum char(64) not null,
            primary key(data_date,chunk_no)
        ) engine=innodb""",
        f"""create table if not exists {table(schema,'dashboard_label_local_history_stage')} (
            run_id char(36) not null, data_date date not null, chunk_no int not null,
            row_count int not null, payload longblob not null, checksum char(64) not null,
            primary key(run_id,data_date,chunk_no)
        ) engine=innodb""",
        f"""create table if not exists {table(schema,'dashboard_label_local_days')} (
            data_date date primary key, run_id char(36) not null, input_batch char(36) not null,
            input_hash char(64) not null, rule_version varchar(96) not null, baseline_sha256 char(64) not null,
            history_start date not null, fact_rows bigint not null, evidence_rows bigint not null,
            summary_json json not null, completed_at datetime(6) not null default current_timestamp(6)
        ) engine=innodb""",
        f"""create table if not exists {table(schema,'dashboard_label_local_runs')} (
            run_id char(36) primary key, business_date date, input_batch char(36), status varchar(32) not null,
            started_at datetime(6) not null default current_timestamp(6), finished_at datetime(6),
            summary_json json, error_message text
        ) engine=innodb""",
        f"""create table if not exists {table(schema,'dashboard_label_local_publication')} (
            singleton tinyint primary key, run_id char(36) not null, business_date date not null,
            source_mode varchar(32) not null, rule_version varchar(96) not null,
            history_start date not null, input_batch char(36) not null,
            published_at datetime(6) not null default current_timestamp(6)
        ) engine=innodb""",
    ]
    with conn.cursor() as cursor:
        for sql in statements:
            cursor.execute(sql)
    conn.commit()


def restore_work(conn, schema: str, dates: list[date]) -> None:
    """Discard possibly half-committed work, restoring only verified local history."""
    work = table(schema, WORK_TABLE)
    history = table(schema, "dashboard_label_local_history")
    placeholders = ",".join(["%s"] * len(FACT_COLUMNS))
    insert = f"insert into {work} ({','.join(FACT_COLUMNS)}) values ({placeholders})"
    with conn.cursor() as cursor:
        cursor.execute(f"delete from {work}")
        for day in dates:
            chunk = -1
            while True:
                cursor.execute(f"select chunk_no,row_count,payload,checksum from {history} where data_date=%s and chunk_no>%s order by chunk_no limit 1", (day, chunk))
                item = cursor.fetchone()
                if not item:
                    break
                rows = decode_history_chunk(item["payload"], item["checksum"])
                if len(rows) != item["row_count"]:
                    raise ValueError("local history row count mismatch")
                cursor.executemany(insert, rows)
                chunk = item["chunk_no"]
    conn.commit()


def validate_day(conn, schema: str, day: date, *, input_schema: str | None = None, complete_lifecycle: bool = False) -> dict:
    work = table(schema, WORK_TABLE)
    dictionary = table(input_schema or schema, "dashboard_label_source_dictionary")
    with conn.cursor() as cursor:
        cursor.execute(f"select count(*) as fact_rows, sum(evidence_json is not null) as evidence_rows, count(distinct msku) as unique_msku_count from {work} where data_date=%s", (day,))
        summary = cursor.fetchone()
        if not summary["fact_rows"]:
            raise RuntimeError("local V47 produced no facts")
        if summary["evidence_rows"] != summary["fact_rows"]:
            raise RuntimeError("local V47 facts and evidence are incomplete")
        cursor.execute(f"select count(*) as n from {work} where data_date=%s and (json_type(evidence_json)<>'OBJECT' or label_period not in ('current','7d','14d','30d','90d','6m','long_term'))", (day,))
        if cursor.fetchone()["n"]:
            raise RuntimeError("invalid local evidence object or label period")
        extensions = " and w.label_id not in (206,207,308)" if complete_lifecycle else " and w.label_id<>308"
        cursor.execute(f"select count(*) as n from {work} w left join {dictionary} d on d.sub_label_id=w.label_id where w.data_date=%s and d.sub_label_id is null{extensions}", (day,))
        if cursor.fetchone()["n"]:
            raise RuntimeError("generated label has no dictionary entry")
        cursor.execute(f"select 1 as duplicate_key from {work} where data_date=%s group by country_category,country,store,msku,label_id,label_period having count(*)>1 limit 1", (day,))
        if cursor.fetchone():
            raise RuntimeError("duplicate local label fact business key")
        cursor.execute(f"select label_id,count(*) as rows_count,sum(evidence_json is not null) as evidence_count from {work} where data_date=%s group by label_id order by label_id", (day,))
        summary["labels"] = cursor.fetchall()
        cursor.execute(f"select count(*) as n from (select country_category,store,msku from {work} where data_date=%s and label_id between 301 and 308 group by country_category,store,msku having count(distinct label_id)>1) c", (day,))
        if cursor.fetchone()["n"]:
            raise RuntimeError("multiple mutually exclusive operating statuses")
    if complete_lifecycle:
        from etl.label_lifecycle_completion import validate_extension_ids,validate_coverage
        validate_extension_ids(conn,input_schema or schema)
        summary.update(validate_coverage(conn,schema,day,input_schema=input_schema or schema))
    return summary


def archive_day(conn, schema: str, day: date, run_id: str, inputs: dict, history_start: date, summary: dict, *, rule_version: str = RULE_VERSION) -> None:
    work = table(schema, WORK_TABLE)
    stage = table(schema, "dashboard_label_local_history_stage")
    history = table(schema, "dashboard_label_local_history")
    days = table(schema, "dashboard_label_local_days")
    last_id = 0
    chunk_no = 0
    copied = 0
    with conn.cursor() as cursor:
        cursor.execute(f"delete from {stage} where run_id=%s and data_date=%s", (run_id, day))
        while True:
            cursor.execute(f"select id,{','.join(FACT_COLUMNS)} from {work} where data_date=%s and id>%s order by id limit 1000", (day, last_id))
            records = cursor.fetchall()
            if not records:
                break
            payload, checksum = encode_history_chunk([[row[col] for col in FACT_COLUMNS] for row in records])
            cursor.execute(f"insert into {stage} (run_id,data_date,chunk_no,row_count,payload,checksum) values (%s,%s,%s,%s,%s,%s)", (run_id, day, chunk_no, len(records), payload, checksum))
            conn.commit()
            copied += len(records)
            last_id = records[-1]["id"]
            chunk_no += 1
        if copied != summary["fact_rows"]:
            raise RuntimeError("history archive count differs from validated work")
        try:
            cursor.execute(f"delete from {history} where data_date=%s", (day,))
            cursor.execute(f"insert into {history} (data_date,chunk_no,row_count,payload,checksum) select data_date,chunk_no,row_count,payload,checksum from {stage} where run_id=%s and data_date=%s", (run_id, day))
            cursor.execute(f"delete from {days} where data_date=%s", (day,))
            cursor.execute(f"insert into {days} (data_date,run_id,input_batch,input_hash,rule_version,baseline_sha256,history_start,fact_rows,evidence_rows,summary_json) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (day, run_id, inputs["batch_id"], inputs["input_hash"], rule_version, BASELINE_SHA256, history_start, summary["fact_rows"], summary["evidence_rows"], json.dumps(summary, ensure_ascii=False, default=str)))
            cursor.execute(f"delete from {stage} where run_id=%s and data_date=%s", (run_id, day))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def validate_retained_archive(conn, work_schema: str, history_schema: str, day: date, rule_version: str) -> None:
    """Prove retained work is byte-for-byte the already validated archive."""
    with conn.cursor() as q:
        q.execute(f"select rule_version,baseline_sha256,fact_rows from {table(history_schema,'dashboard_label_local_days')} where data_date=%s", (day,))
        metadata=q.fetchone()
        if not metadata or metadata['rule_version']!=rule_version or metadata['baseline_sha256']!=BASELINE_SHA256:
            raise RuntimeError('retained date lacks an accepted archive')
        last_id=0;chunk=-1;total=0
        while True:
            q.execute(f"select chunk_no,row_count,payload,checksum from {table(history_schema,'dashboard_label_local_history')} where data_date=%s and chunk_no>%s order by chunk_no limit 1", (day,chunk))
            archived=q.fetchone()
            if not archived:break
            records=decode_history_chunk(archived['payload'],archived['checksum'])
            if len(records)!=archived['row_count']:raise RuntimeError('retained archive row count mismatch')
            q.execute(f"select id,{','.join(FACT_COLUMNS)} from {table(work_schema,WORK_TABLE)} where data_date=%s and id>%s order by id limit %s", (day,last_id,len(records)))
            rows=q.fetchall()
            actual=[[row[name] for name in FACT_COLUMNS] for row in rows]
            if encode_history_chunk(actual)[1]!=archived['checksum']:
                raise RuntimeError('retained work differs from validated archive')
            last_id=rows[-1]['id'];chunk=archived['chunk_no'];total+=len(rows)
        q.execute(f"select count(*) as n from {table(work_schema,WORK_TABLE)} where data_date=%s", (day,))
        if total!=metadata['fact_rows'] or total!=q.fetchone()['n']:
            raise RuntimeError('retained work count differs from validated archive')


def publish_days(conn, schema: str, dates: list[date], run_id: str, inputs: dict, history_start: date, *, input_schema: str | None = None, complete_lifecycle: bool = False,
                 work_schema: str | None = None, history_schema: str | None = None, retained_dates: tuple[date, ...] = ()) -> dict:
    from etl.label_rule_evidence_snapshot_update import fact_table_sql, detail_table_sql, CREATE_TABLE_SQL
    from etl.dashboard_daily_update import SchemaConfig, render_sql

    fact = table(schema, "dashboard_label_fact_snapshot")
    detail = table(schema, "dashboard_label_detail_snapshot")
    audit = table(schema, "dashboard_label_rule_evidence_snapshot")
    work = table(work_schema or schema, WORK_TABLE)
    dictionary = table(input_schema or schema, "dashboard_label_source_dictionary")
    extension_rows = []
    from etl.label_receiving_status import extension_details as receiving_details
    receiving_rows=receiving_details(conn,input_schema or schema)
    rule_version = RULE_VERSION
    if complete_lifecycle:
        from etl.label_lifecycle_completion import VERSION,extension_details,validate_coverage
        extension_rows = extension_details(conn,input_schema or schema)
        rule_version = VERSION
        if not set(retained_dates).issubset(dates):
            raise ValueError('retained dates must belong to the publication')
        for day in dates:
            if day in retained_dates:
                validate_retained_archive(conn,work_schema or schema,history_schema or schema,day,VERSION)
            validate_coverage(conn,work_schema or schema,day,input_schema=input_schema or schema,
                              check_source_evidence=day not in retained_dates)
    placeholders = ",".join(["%s"] * len(dates))
    extension_rows += receiving_rows
    if len(dates) != 2 or len(set(dates)) != 2:
        raise ValueError("publication requires exactly two distinct local dates")
    detail_cols = "label_id,label_name,sub_label_id,sub_label_name,tag_rule,business_definition,business_owner,label_category,update_frequency,mutual_exclusion,status,create_time,tagging_method"
    with conn.cursor() as cursor:
        cursor.execute(fact_table_sql(fact, include_indexes=True))
        cursor.execute(detail_table_sql(detail, include_indexes=True))
        cursor.execute(render_sql(CREATE_TABLE_SQL, SchemaConfig(schema, "etl_datasync", "dwd_datasync", "temporary_dwd")))
    conn.commit()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"delete from {fact}")
            cursor.execute(f"insert into {fact} (data_date,country_category,country,store,msku,label_id,label_period,created_time,evidence_blob) select data_date,country_category,country,store,msku,label_id,label_period,created_time,compress(cast(evidence_json as char)) from {work} where data_date in ({placeholders})", dates)
            fact_count = cursor.rowcount
            if not fact_count:
                raise RuntimeError("refusing to publish empty local facts")
            cursor.execute(f"delete from {detail}")
            cursor.execute(f"insert into {detail} ({detail_cols}) select {detail_cols} from {dictionary}")
            detail_count = cursor.rowcount
            cursor.execute(f"update {detail} set tag_rule=%s where sub_label_id=304", ('FBA可售库存=0，且存在最新状态为接收中的货件，或供应链数量达到单位箱规；接收中货件不要求供应链数量达到箱规；符合首次上新接收条件的商品归入入库接收中',))
            if extension_rows:
                cursor.executemany(f"insert into {detail} ({detail_cols}) values ({','.join(['%s']*len(detail_cols.split(',')))})",[tuple(row[name] for name in detail_cols.split(',')) for row in extension_rows])
                detail_count += cursor.rowcount
            # Audit comes from the SAME generated V47 evidence; no old Python rule or remote comparison.
            cursor.execute(f"delete from {audit}")
            cursor.execute(f"""insert into {audit} (
                label_date,country_category,store,msku,parent_label_id,label_period,period_start,period_end,
                sales_qty,daily_sales,tag_sales_amount,tag_gross_profit,tag_gross_margin,
                computed_sub_label_id,remote_sub_label_id,rule_version,evidence_status)
                select data_date,country_category,store,msku,1,label_period,
                    cast(json_unquote(json_extract(evidence_json,'$.window.start')) as date),data_date,
                    json_extract(evidence_json,'$.metrics.period_sales_qty'),
                    json_extract(evidence_json,'$.metrics.daily_sales'),
                    json_extract(evidence_json,'$.metrics.sales_amount'),
                    json_extract(evidence_json,'$.metrics.tag_gross_profit'),
                    json_extract(evidence_json,'$.metrics.tag_margin_rate') / 100,
                    label_id,null,%s,'generated'
                from {work} where data_date in ({placeholders}) and label_id in (101,102,103,104)
            """, (rule_version, *dates))
            audit_count = cursor.rowcount
            if history_schema is not None:
                # Promote only validated staged archives in the same transaction
                # as the live facts, dictionary and publication marker.
                for name in ('dashboard_label_local_history', 'dashboard_label_local_days'):
                    target_history = table(schema, name)
                    staged_history = table(history_schema, name)
                    cursor.execute(f"delete from {target_history} where data_date in ({placeholders})", dates)
                    cursor.execute(f"insert into {target_history} select * from {staged_history} where data_date in ({placeholders})", dates)
            cursor.execute(f"insert into {table(schema,'dashboard_label_local_publication')} (singleton,run_id,business_date,source_mode,rule_version,history_start,input_batch) values (1,%s,%s,'local_generated',%s,%s,%s) on duplicate key update run_id=values(run_id),business_date=values(business_date),source_mode=values(source_mode),rule_version=values(rule_version),history_start=values(history_start),input_batch=values(input_batch),published_at=current_timestamp(6)", (run_id, max(dates), rule_version, history_start, inputs["batch_id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"fact_rows": fact_count, "evidence_rows": fact_count, "detail_rows": detail_count, "audit_rows": audit_count}
