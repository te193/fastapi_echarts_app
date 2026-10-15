-- 由用户执行；本文件未在远端执行，不修改现有其他事件。
-- 推荐北京时间每天03:30；首次2026-10-13 03:30。
-- 只读实查：本次表现记录最晚入库2026-10-12 01:21:51，event_scheduler已为ON。
set session time_zone = '+08:00';

create event dws_datasync.ev_product_role_history_incremental_daily
on schedule every 1 day
starts '2026-10-13 03:30:00'
on completion preserve
enable
comment '产品历史销售角色每日增量'
do call dws_datasync.sp_product_role_history_incremental();

-- 创建后核对：enabled、+08:00、starts=2026-10-13 03:30:00；首次执行前last_executed为空。
select event_name,status,time_zone,starts,last_executed
from information_schema.events
where event_schema='dws_datasync'
  and event_name='ev_product_role_history_incremental_daily';

-- 明天再看：last_executed只能证明事件触发；成功更新需结合下面的增量日志、源日期及结果日期。
/*
select cutoff,status,stage,published_products,
    timestampdiff(second,started_at,finished_at) as elapsed_seconds,error_message
from dws_datasync.dws_product_sales_role_history_run_log
where run_mode='incremental' and started_at>='2026-10-13 00:00:00'
order by started_at desc limit 5;

select max(start_date) as source_latest
from dwd_datasync.lx_statistics_product_performance;

select min(data_date) as min_processed,max(data_date) as max_processed
from dws_datasync.dws_product_sales_role_history;
*/
