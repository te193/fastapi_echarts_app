-- 一次性迁移：过程已由Codex部署到opt；由用户使用有DWS写权限的独立autocommit连接调用。
-- 不创建备份，事务内清空并写入最新opt结果；失败回滚，不重算历史。
delimiter $$
create procedure opt_db.hr_replace_dws_result_20261012_4ab671()
sql security invoker
begin
    declare v_target_lock int default 0;
    declare v_source_lock int default 0;
    declare v_total bigint;
    declare v_actual bigint;
    declare v_bad bigint;
    declare v_lo date;
    declare v_hi date;
    declare v_target_hi date;
    declare v_started datetime(6) default now(6);
    declare exit handler for sqlexception
    begin
        rollback;
        if v_source_lock=1 then do release_lock('opt_db.hr_lifecycle_pending_20261012_427c64'); end if;
        if v_target_lock=1 then do release_lock('dws_datasync.product_role_history'); end if;
        resignal;
    end;
    if @@session.autocommit<>1 then
        signal sqlstate '45000' set message_text='use a fresh autocommit connection';
    end if;
    select get_lock('dws_datasync.product_role_history',0) into v_target_lock;
    if coalesce(v_target_lock,0)<>1 then
        signal sqlstate '45000' set message_text='DWS history calculation is active; nothing replaced';
    end if;
    select get_lock('opt_db.hr_lifecycle_pending_20261012_427c64',0) into v_source_lock;
    if coalesce(v_source_lock,0)<>1 then
        signal sqlstate '45000' set message_text='opt history calculation is active; nothing replaced';
    end if;
    select count(*),min(data_date),max(data_date) into v_total,v_lo,v_hi
    from opt_db.hr_lifecycle_result_pending_20261012_427c64;
    if v_total<>52397 or not(v_lo<=>'2026-10-11') or not(v_hi<=>'2026-10-11') then
        signal sqlstate '45000' set message_text='verified opt snapshot changed; nothing replaced';
    end if;
    select max(data_date) into v_target_hi from dws_datasync.dws_product_sales_role_history;
    if v_target_hi>v_hi then
        signal sqlstate '45000' set message_text='DWS is newer than this opt snapshot; nothing replaced';
    end if;
    start transaction;
    delete from dws_datasync.dws_product_sales_role_history where scope_mode in ('business_unit','country');
    insert into dws_datasync.dws_product_sales_role_history
        (scope_mode,country_category,country,store,msku,data_date,created_time,updated_time,evidence_json)
    select scope_mode,country_category,country,store,msku,data_date,created_time,updated_time,evidence_json
    from opt_db.hr_lifecycle_result_pending_20261012_427c64;
    select count(*) into v_actual from dws_datasync.dws_product_sales_role_history;
    select count(*) into v_bad
    from opt_db.hr_lifecycle_result_pending_20261012_427c64 s
    left join dws_datasync.dws_product_sales_role_history d
      on d.scope_mode=s.scope_mode and d.country_category=s.country_category
      and d.country=s.country and d.store=s.store and d.msku=s.msku
    where d.msku is null or not(d.data_date<=>s.data_date)
      or not(d.created_time<=>s.created_time) or not(d.updated_time<=>s.updated_time)
      or not(sha2(cast(d.evidence_json as char),256)<=>sha2(cast(s.evidence_json as char),256));
    if v_actual<>v_total or v_bad<>0 then
        signal sqlstate '45000' set message_text='import verification failed; transaction rolled back';
    end if;
    insert into dws_datasync.dws_product_sales_role_history_run_log
        (run_id,run_mode,cutoff,status,stage,published_products,started_at,finished_at)
    values(uuid(),'import',v_hi,'success','replaced from verified opt pending_20261012_427c64',v_actual,v_started,now(6));
    commit;
    do release_lock('opt_db.hr_lifecycle_pending_20261012_427c64');
    do release_lock('dws_datasync.product_role_history');
    select 'success' status,v_actual imported_rows,v_hi imported_cutoff;
end$$
delimiter ;

-- 用户执行这一句；不要同时运行历史计算或定时增量。
-- call opt_db.hr_replace_dws_result_20261012_4ab671();
