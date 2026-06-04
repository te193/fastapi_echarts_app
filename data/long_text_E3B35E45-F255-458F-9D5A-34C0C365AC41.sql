
#找出各站点sku的本地仓库存货数
drop  table if exists temporary_dwd.本地各sku仓库数量;
CREATE  table temporary_dwd.本地各sku仓库数量
with replenishment_value as (
    select distinct *
    from etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
    where date(create_time) = date_add(
            date_add(str_to_date(concat(dt_week, '1'), '%X%V%w'), interval -1 week), 
            interval 6 day
        )
        or date(create_time) = curdate()
),
month_end_data as (
    select 
        create_time,
		seller_sku_adj,
		country_category,
		seller_name_new,
        (max(sc_quantity_local_valid) +
         max(sc_quantity_purchase_shipping) +
         max(sc_quantity_purchase_plan) +
         max(sc_quantity_local_qc))        as 本地仓库存货数量
         ,max(sc_quantity_purchase_shipping) as 采购在途
    from replenishment_value
    group by create_time,seller_sku_adj,country_category,seller_name_new
    order by yearweek(create_time, 1) desc  
)
select 
*
from month_end_data
order by create_time 
;
CREATE index id1 on temporary_dwd.本地各sku仓库数量(seller_sku_adj,country_category);


-- 计算各站点sku的采购和头程成本
drop  table if exists temporary_dwd.产品_站点采购头程成本;
CREATE  table temporary_dwd.产品_站点采购头程成本
SELECT 
SUBSTRING_INDEX(seller_sku,'-',1)  产品sku
,country_category
,seller_name_new
,max(cg_price) 采购成本 
,max(cg_transport_costs) 头程成本
-- select *
from 
etl_datasync.etl_dispose_lx_product_local_product_info
group by 
country_category,产品sku,seller_name_new
order by 
采购成本 desc 
;
CREATE index id1 on temporary_dwd.产品_站点采购头程成本(产品sku,country_category);




#最终合并，计算总数，只看每周的数量和货值
drop  table if exists temporary_dwd.补货建议总趋势;
CREATE  table temporary_dwd.补货建议总趋势
with 合计库存数及货值 as
(
SELECT 
a.create_time
,a.seller_sku_adj
,a.country_category	
,a.seller_name_new		
-- *
,a.本地仓库存货数量
,a.采购在途
,a.本地仓库存货数量*(ifnull(b.采购成本,0)+ifnull(b.头程成本,0)) 本地仓库存货货值
,a.采购在途*(ifnull(b.采购成本,0)+ifnull(b.头程成本,0)) 采购在途货值
from 
temporary_dwd.本地各sku仓库数量 a
left join
temporary_dwd.产品_站点采购头程成本 b 
on a.seller_sku_adj=b.产品sku and a.country_category=b.country_category and a.seller_name_new=b.seller_name_new
-- where b.seller_name_new is null 
)
SELECT 
CONCAT('W', ROW_NUMBER() OVER (ORDER BY create_time)) AS 周标签
,create_time 补货日期
,sum(本地仓库存货数量) 本地仓库存货数量
,sum(采购在途) 采购在途
,round(sum(本地仓库存货货值),2) 本地仓库存货货值
,round(sum(采购在途货值),2) 采购在途货值
FROM 
合计库存数及货值
group by
create_time
order by create_time
;

CREATE index id1 on temporary_dwd.补货建议总趋势(补货日期);




-- 计算补货建议总趋势的环比变化率和历史波动率预警
DROP TABLE IF EXISTS temporary_dwd.补货建议总趋势_环比预警计算;
CREATE TABLE temporary_dwd.补货建议总趋势_环比预警计算
WITH weekly_data AS (
    SELECT 
        周标签,
        补货日期,
        本地仓库存货数量,
        本地仓库存货货值,
        采购在途,
        采购在途货值,
        LAG(本地仓库存货数量) OVER (ORDER BY 补货日期) AS prev_本地仓库存货数量,
        LAG(本地仓库存货货值) OVER (ORDER BY 补货日期) AS prev_本地仓库存货货值,
        LAG(采购在途) OVER (ORDER BY 补货日期) AS prev_采购在途,
        LAG(采购在途货值) OVER (ORDER BY 补货日期) AS prev_采购在途货值
    FROM temporary_dwd.补货建议总趋势
),

-- 计算各列环比变化率
momentum AS (
    SELECT 
        周标签,
        补货日期,
        本地仓库存货数量,
        本地仓库存货货值,
        采购在途,
        采购在途货值,
        CASE WHEN prev_本地仓库存货数量 IS NOT NULL AND prev_本地仓库存货数量 != 0 
             THEN (本地仓库存货数量 - prev_本地仓库存货数量) / ABS(prev_本地仓库存货数量) 
        END AS rate_本地仓库存货数量,
        CASE WHEN prev_本地仓库存货货值 IS NOT NULL AND prev_本地仓库存货货值 != 0 
             THEN (本地仓库存货货值 - prev_本地仓库存货货值) / ABS(prev_本地仓库存货货值) 
        END AS rate_本地仓库存货货值,
        CASE WHEN prev_采购在途 IS NOT NULL AND prev_采购在途 != 0 
             THEN (采购在途 - prev_采购在途) / ABS(prev_采购在途) 
        END AS rate_采购在途,
        CASE WHEN prev_采购在途货值 IS NOT NULL AND prev_采购在途货值 != 0 
             THEN (采购在途货值 - prev_采购在途货值) / ABS(prev_采购在途货值) 
        END AS rate_采购在途货值
    FROM weekly_data
),

-- 计算历史波动率（用子查询避免JOIN导致的行膨胀）
volatility AS (
    SELECT 
        m1.周标签,
        m1.补货日期,
        m1.本地仓库存货数量,
        m1.本地仓库存货货值,
        m1.采购在途,
        m1.采购在途货值,
        m1.rate_本地仓库存货数量,
        m1.rate_本地仓库存货货值,
        m1.rate_采购在途,
        m1.rate_采购在途货值,
        (SELECT AVG(ABS(rate_本地仓库存货数量)) FROM momentum m2 WHERE m2.补货日期 < m1.补货日期) AS volatility_本地仓库存货数量,
        (SELECT AVG(ABS(rate_本地仓库存货货值)) FROM momentum m2 WHERE m2.补货日期 < m1.补货日期) AS volatility_本地仓库存货货值,
        (SELECT AVG(ABS(rate_采购在途)) FROM momentum m2 WHERE m2.补货日期 < m1.补货日期) AS volatility_采购在途,
        (SELECT AVG(ABS(rate_采购在途货值)) FROM momentum m2 WHERE m2.补货日期 < m1.补货日期) AS volatility_采购在途货值
    FROM momentum m1
)

SELECT 
    周标签,
    补货日期,
    本地仓库存货数量,
    本地仓库存货货值,
    采购在途,
    采购在途货值,
    
    -- 环比变化率
    ROUND(rate_本地仓库存货数量, 4) AS 本地仓库存货数量_环比,
    ROUND(rate_本地仓库存货货值, 4) AS 本地仓库存货货值_环比,
    ROUND(rate_采购在途, 4) AS 采购在途_环比,
    ROUND(rate_采购在途货值, 4) AS 采购在途货值_环比,
    
    -- 历史波动率
    ROUND(volatility_本地仓库存货数量, 4) AS 本地仓库存货数量_历史波动率,
    ROUND(volatility_本地仓库存货货值, 4) AS 本地仓库存货货值_历史波动率,
    ROUND(volatility_采购在途, 4) AS 采购在途_历史波动率,
    ROUND(volatility_采购在途货值, 4) AS 采购在途货值_历史波动率,
    
    -- 预警列：当前波动幅度超过历史波动率的 ±5% 才预警
    CASE 
        WHEN rate_本地仓库存货数量 IS NULL THEN '首周无数据'
        WHEN ABS(rate_本地仓库存货数量) > IFNULL(volatility_本地仓库存货数量, 0) + 0.05 
          OR ABS(rate_本地仓库存货货值) > IFNULL(volatility_本地仓库存货货值, 0) + 0.05
          OR ABS(rate_采购在途) > IFNULL(volatility_采购在途, 0) + 0.05
          OR ABS(rate_采购在途货值) > IFNULL(volatility_采购在途货值, 0) + 0.05
        THEN '波动超过5%预警'
        ELSE '正常'
    END AS 预警状态,
    
    -- 详细预警信息（哪一列触发）
    CONCAT_WS(', ',
        CASE WHEN ABS(rate_本地仓库存货数量) > IFNULL(volatility_本地仓库存货数量, 0) + 0.05 THEN '本地仓库存货数量' END,
        CASE WHEN ABS(rate_本地仓库存货货值) > IFNULL(volatility_本地仓库存货货值, 0) + 0.05 THEN '本地仓库存货货值' END,
        CASE WHEN ABS(rate_采购在途) > IFNULL(volatility_采购在途, 0) + 0.05 THEN '采购在途' END,
        CASE WHEN ABS(rate_采购在途货值) > IFNULL(volatility_采购在途货值, 0) + 0.05 THEN '采购在途货值' END
    ) AS 预警明细

FROM volatility
ORDER BY 补货日期;

CREATE INDEX id1 ON temporary_dwd.补货建议总趋势_环比预警计算(补货日期);



-- SELECT * from temporary_dwd.补货建议总趋势;
-- SELECT * from temporary_dwd.补货建议总趋势_环比预警计算;


#====================================================================================================




drop  table if exists temporary_dwd.FBA库存可用与在途;
CREATE  table temporary_dwd.FBA库存可用与在途
with inventory_value as (select distinct *
                         from etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
                         where date(create_time) =
                               date_add(date_add(str_to_date(concat(yearweek(create_time, 1), '1'), '%X%V%w'),
                                                 interval -1 week), interval 6 day)
                            or date(create_time) = curdate()),
     month_end_data as (select 
                               date(iv.create_time)                                           as create_time,
                               iv.country_category,
                               iv.seller_sku_adj,
                               iv.seller_name_new,
                               sum(iv.available_total)                                        as 可用总数,
                               sum(iv.available_total_price)                                  as 可用总数成本价,
                               sum(iv.stock_up_num)                                           as 实际在途,
                               sum(iv.stock_up_num_price)                                     as 实际在途成本价,
                               max(iv.cg_price)                                               as 采购单价,
                               max(iv.cg_transport_costs)                                     as 单位头程成本
                        from inventory_value iv
                        group by iv.create_time, iv.country_category, iv.seller_sku_adj, iv.seller_name_new)
select 
CONCAT('W', ROW_NUMBER() OVER (ORDER BY create_time)) AS 周标签
,create_time 日期
,sum(可用总数) 可用总数
,round(sum(可用总数成本价),2) 可用总数成本价
,sum(实际在途) 实际在途
,round(sum(实际在途成本价),2) 实际在途成本价
from month_end_data
group by 日期
order by create_time ;
create index id1 on temporary_dwd.FBA库存可用与在途(日期);



drop  table if exists temporary_dwd.FBA库存可用与在途_最终趋势表;
CREATE  table temporary_dwd.FBA库存可用与在途_最终趋势表
WITH weekly_data AS (
    SELECT 
        周标签,
        日期,
        可用总数,
        可用总数成本价,
        实际在途,
        实际在途成本价,
        LAG(可用总数) OVER (ORDER BY 日期) AS prev_可用总数,
        LAG(可用总数成本价) OVER (ORDER BY 日期) AS prev_可用总数成本价,
        LAG(实际在途) OVER (ORDER BY 日期) AS prev_实际在途,
        LAG(实际在途成本价) OVER (ORDER BY 日期) AS prev_实际在途成本价
    FROM temporary_dwd.FBA库存可用与在途
),

-- 计算各列环比变化率
momentum AS (
    SELECT 
        周标签,
        日期,
        可用总数,
        可用总数成本价,
        实际在途,
        实际在途成本价,
        CASE WHEN prev_可用总数 IS NOT NULL AND prev_可用总数 != 0 
             THEN (可用总数 - prev_可用总数)  / ABS(prev_可用总数) 
        END AS rate_可用总数,
        CASE WHEN prev_可用总数成本价 IS NOT NULL AND prev_可用总数成本价 != 0 
             THEN (可用总数成本价 - prev_可用总数成本价)  / ABS(prev_可用总数成本价) 
        END AS rate_可用总数成本价,
        CASE WHEN prev_实际在途 IS NOT NULL AND prev_实际在途 != 0 
             THEN (实际在途 - prev_实际在途)  / ABS(prev_实际在途) 
        END AS rate_实际在途,
        CASE WHEN prev_实际在途成本价 IS NOT NULL AND prev_实际在途成本价 != 0 
             THEN (实际在途成本价 - prev_实际在途成本价)  / ABS(prev_实际在途成本价) 
        END AS rate_实际在途成本价
    FROM weekly_data
),

-- 计算历史波动率（用子查询避免JOIN导致的行膨胀）
volatility AS (
    SELECT 
        m1.周标签,
        m1.日期,
        m1.可用总数,
        m1.可用总数成本价,
        m1.实际在途,
        m1.实际在途成本价,
        m1.rate_可用总数,
        m1.rate_可用总数成本价,
        m1.rate_实际在途,
        m1.rate_实际在途成本价,
        (SELECT AVG(ABS(rate_可用总数)) FROM momentum m2 WHERE m2.日期 < m1.日期) AS volatility_可用总数,
        (SELECT AVG(ABS(rate_可用总数成本价)) FROM momentum m2 WHERE m2.日期 < m1.日期) AS volatility_可用总数成本价,
        (SELECT AVG(ABS(rate_实际在途)) FROM momentum m2 WHERE m2.日期 < m1.日期) AS volatility_实际在途,
        (SELECT AVG(ABS(rate_实际在途成本价)) FROM momentum m2 WHERE m2.日期 < m1.日期) AS volatility_实际在途成本价
    FROM momentum m1
)

SELECT 
    周标签,
    日期,
    可用总数,
    可用总数成本价,
    实际在途,
    实际在途成本价,
    -- 环比变化率
    ROUND(rate_可用总数, 4)  AS 可用总数_环比,
    ROUND(rate_可用总数成本价, 4) AS 可用总数成本价_环比,
    ROUND(rate_实际在途, 4) AS 实际在途_环比,
    ROUND(rate_实际在途成本价, 4)  AS 实际在途成本价_环比,
    
    -- 历史波动率
    ROUND(volatility_可用总数, 4) AS 可用总数_历史波动率,
    ROUND(volatility_可用总数成本价, 4) AS 可用总数成本价_历史波动率,
    ROUND(volatility_实际在途, 4) AS 实际在途_历史波动率,
    ROUND(volatility_实际在途成本价, 4) AS 实际在途成本价_历史波动率,
    
    -- 预警列：当前波动幅度超过历史波动率的 ±5% 才预警
    CASE 
        WHEN rate_可用总数 IS NULL THEN '首周无数据'
        WHEN ABS(rate_可用总数) > volatility_可用总数 + 0.05 
          OR ABS(rate_可用总数成本价) > volatility_可用总数成本价 + 0.05
          OR ABS(rate_实际在途) > volatility_实际在途 + 0.05
          OR ABS(rate_实际在途成本价) > volatility_实际在途成本价 + 0.05
        THEN '波动超过5%预警'
        ELSE '正常'
    END AS 预警状态,
    
    -- 详细预警信息（哪一列触发）
    CONCAT_WS(', ',
        CASE WHEN ABS(rate_可用总数) > volatility_可用总数 + 0.05 THEN '可用总数' END,
        CASE WHEN ABS(rate_可用总数成本价) > volatility_可用总数成本价 + 0.05 THEN '可用总数成本价' END,
        CASE WHEN ABS(rate_实际在途) > volatility_实际在途 + 0.05 THEN '实际在途' END,
        CASE WHEN ABS(rate_实际在途成本价) > volatility_实际在途成本价 + 0.05 THEN '实际在途成本价' END
    ) AS 预警明细
    
FROM volatility
ORDER BY 日期;


create index id1 on temporary_dwd.FBA库存可用与在途_最终趋势表(日期);


-- SELECT * from temporary_dwd.FBA库存可用与在途_最终趋势表;