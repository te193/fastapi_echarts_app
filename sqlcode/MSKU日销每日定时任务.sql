/*
  用途：每天 08:10 刷新 MSKU 日销结果。
  前提：MySQL 全局参数 event_scheduler = ON，执行账号具备 EVENT 权限。
*/

DROP EVENT IF EXISTS dws_datasync.evt_dws_msku_daily_sales;

DELIMITER $$

CREATE DEFINER = 'analysis_zhr'@'%'
EVENT dws_datasync.evt_dws_msku_daily_sales ON SCHEDULE
    EVERY 1 DAY
    STARTS '2026-08-21 08:10:00'
ON COMPLETION PRESERVE
ENABLE
COMMENT '每天08:10计算MSKU日销'
DO
BEGIN
    CALL dws_datasync.sp_dws_msku_daily_sales();
    CALL dws_datasync.sp_dws_msku_safety_stock();
END$$

DELIMITER ;
