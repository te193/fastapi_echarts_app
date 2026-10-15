-- 只读核查：不修改数据。批次与月份为2026-10-13本次核查值。
-- 更新业务日期时应重新查询成功批次，不把本次批次永久用于业务规则。
select snapshot_month,count(*) row_count,count(distinct sid) store_count,min(source_update_time) oldest_source,max(source_update_time) newest_source,max(create_time) latest_load from dwd_datasync.lx_replenishment_restriction where delete_flag=0 group by snapshot_month order by snapshot_month desc limit 4;

select count(*) group_count,sum(remaining_volume_m3<0) negative_remaining,sum(remaining_volume_m3>=0 and pending_volume_m3>remaining_volume_m3) positive_shortfall,sum(remaining_volume_m3>=0 and pending_volume_m3<=remaining_volume_m3) fits from dws_datasync.fba_capacity_group_snapshot where batch_id=1791851400331304 and delete_flag=0;

select g.capacity_group, count(*) group_count,sum(abs(g.remaining_volume_m3-(cast(r.vol_stock_remain as decimal(20,6))*case when r.sub_item_vol_unit_type=2 then 0.028316846592 else 1 end))<=0.000001) standard_match_count from dws_datasync.fba_capacity_group_snapshot g left join dwd_datasync.lx_replenishment_restriction r on r.sid=cast(g.representative_sid as char) and r.snapshot_month='2026-10' and r.month='2026-10-01' and r.storage_type='Standard' and r.delete_flag=0 where g.batch_id=1791851400331304 and g.delete_flag=0 group by g.capacity_group;
