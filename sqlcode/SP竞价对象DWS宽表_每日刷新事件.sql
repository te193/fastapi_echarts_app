/*
用途：每天北京时间 09:30 刷新 SP 竞价对象 DWS 宽表。
前提：首次执行前确认事件调度器已开启：
select @@event_scheduler;
如结果不是 on，请由具备管理员权限的账号执行：
set global event_scheduler = on;
*/

set time_zone = '+08:00';

drop event if exists dws_datasync.ev_refresh_sp_bid_object_snapshot_daily;

delimiter $$

create event dws_datasync.ev_refresh_sp_bid_object_snapshot_daily
    on schedule every 1 day
    starts '2026-09-15 09:30:00'
    on completion preserve
    enable
    do
begin
    call dws_datasync.sp_refresh_sp_bid_object_snapshot_daily(null);
end$$

delimiter ;
