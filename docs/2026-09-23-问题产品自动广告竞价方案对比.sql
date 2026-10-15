-- 生成最新可用标签队列与 2026-09-11 建议价的安全关联清单。
-- 查询结果中的 source_bid_20260911 是旧表采集时竞价；模拟执行价须再按 target_id
-- 读取 ods_datasync.lx_advertising_sp_targets.bid，并核对 profile/campaign/ad_group、
-- expression_type = 'auto'、state = 'enabled'、serving_status = 'TARGETING_CLAUSE_STATUS_LIVE'。
with cohort as (
    select distinct b.country, b.store, b.msku
    from dws_datasync.dws_标签表 a
    join dws_datasync.dws_标签表 b
      on a.data_date = b.data_date
     and a.store = b.store
     and a.msku = b.msku
    where a.data_date = '2026-09-22'
      and a.label_id = 301
      and a.label_period = 'current'
      and a.country is null
      and b.label_id = 1304
      and b.label_period = '30d'
      and b.country is not null
), auto_groups as (
    select p.country, p.store, p.msku,
           d.profile_id, d.campaign_id, d.ad_group_id,
           d.current_bid as group_bid, d.clicks, d.orders
    from cohort p
    join dws_datasync.dws_sp_bid_object_snapshot_daily d
      on d.snapshot_date = '2026-09-22'
     and d.targeting_type = 'auto'
     and d.msku_mapping_status = 'mapped'
     and d.base_store_name = p.store
     and d.msku = p.msku
     and d.country_code = case p.country
          when '西班牙' then 'es' when '意大利' then 'it'
          when '英国' then 'uk' when '荷兰' then 'nl'
          when '法国' then 'fr' when '波兰' then 'pl'
          when '德国' then 'de' when '爱尔兰' then 'ie'
          when '瑞典' then 'se' when '比利时' then 'be'
          when '土耳其' then 'tr' when '墨西哥' then 'mx'
          when '巴西' then 'br' when '加拿大' then 'ca'
          when '美国' then 'us' end
    where d.campaign_state_current = 'enabled'
      and d.ad_group_state_current = 'enabled'
), suggestions as (
    select profile_id, campaign_id, ad_group_id, bid_owner_id,
           max(current_bid) as old_source_bid,
           max(suggested_bid) as suggested_bid,
           max(suggested_min) as suggested_min,
           max(suggested_max) as suggested_max,
           count(distinct suggested_bid) as suggested_variants,
           max(bid_observed_at) as bid_observed_at
    from ods_datasync.lx_mcp_sp_search_term_daily
    where bid_owner_type = 'target'
      and bid_status = 'AVAILABLE'
      and match_type in ('queryBroadRelMatches', 'queryHighRelMatches', 'asinSubstituteRelated', 'asinAccessoryRelated')
    group by profile_id, campaign_id, ad_group_id, bid_owner_id
), joined as (
    select g.country, g.store, g.msku,
           g.profile_id, g.campaign_id, g.ad_group_id,
           g.clicks as group_clicks, g.orders as group_orders,
           s.bid_owner_id as target_id,
           s.old_source_bid as source_bid_20260911,
           s.old_source_bid, s.suggested_bid,
           s.suggested_min, s.suggested_max,
           s.suggested_variants, s.bid_observed_at
    from auto_groups g
    join suggestions s
      on s.profile_id = cast(g.profile_id as char)
     and s.campaign_id = cast(g.campaign_id as char)
     and s.ad_group_id = cast(g.ad_group_id as char)
)
select country, store, msku, profile_id, campaign_id, ad_group_id,
       target_id, source_bid_20260911, suggested_bid, suggested_min, suggested_max,
       group_clicks, group_orders, suggested_variants, bid_observed_at
from joined
order by country, store, msku, profile_id, campaign_id, ad_group_id, target_id
limit 5000;
