-- 标签看板“运营状态 -> 返厂品”大标签及下钻明细计算
-- 仅包含 WITH + SELECT，不创建临时表，不写入、删除或更新任何数据库对象。
-- 修改 params.data_date 即可验证其他统计日。
--
-- 核心口径：
-- 1. 粒度为国家类别 + 店铺 + MSKU。
-- 2. 同一国家类别内多国共享库存，FBA 可售按日取 MAX，销量按日求和。
-- 3. 识别“FBA 可售 = 0 -> 后续首次 FBA 可售 > 5”的完整事件。
-- 4. 只取最近 180 天内最新一轮已经完成恢复的事件。
-- 5. 基础池要求最近 180 天出现过 FBA 可售 = 0，且周期销量 > 0。
-- 6. D1-D7 为观察期，D8-D21 为干预期，D22 起退出返厂大标签。
-- 7. 最终结果每一行就是大标签“返厂品”的一条下钻明细；汇总字段在每行重复，
--    便于同时核对返厂品总数、观察期和干预期数量。

WITH
params AS (
    SELECT DATE('2026-07-26') AS data_date
),
listing_ranked AS (
    SELECT CAST(li.marketplace AS CHAR(50)) AS marketplace,
           CAST(li.seller_name AS CHAR(100)) AS seller_name,
           CAST(li.seller_sku AS CHAR(255)) AS seller_sku,
           ROW_NUMBER() OVER (
               PARTITION BY
                   CAST(li.marketplace AS CHAR),
                   CAST(li.seller_name AS CHAR),
                   CAST(li.seller_sku AS CHAR)
               ORDER BY li.create_time DESC, li.id DESC
           ) AS row_num
    FROM dwd_datasync.lx_sales_mws_listing li
    WHERE li.seller_sku IS NOT NULL
      AND CAST(li.seller_sku AS CHAR) <> ''
      AND LOWER(TRIM(CAST(li.seller_sku AS CHAR))) NOT LIKE 'amzn.gr%'
      AND UPPER(TRIM(CAST(li.seller_sku AS CHAR))) NOT LIKE 'AMAZON%'
),
listing_keys AS (
    SELECT DISTINCT
           CASE
               WHEN marketplace = '英国' THEN '英国站'
               WHEN marketplace IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
               ELSE '欧洲站'
           END AS country_category,
           CASE
               WHEN LOCATE('-', SUBSTRING_INDEX(seller_name, ' ', 1)) > 0
                   THEN LEFT(
                       SUBSTRING_INDEX(seller_name, ' ', 1),
                       LOCATE('-', SUBSTRING_INDEX(seller_name, ' ', 1)) - 1
                   )
               ELSE SUBSTRING_INDEX(seller_name, ' ', 1)
           END AS store,
           seller_sku AS msku
    FROM listing_ranked
    WHERE row_num = 1
),
return_daily AS (
    SELECT k.country_category,
           k.store,
           k.msku,
           DATE(p.start_date) AS stat_date,
           MAX(COALESCE(p.afn_fulfillable_quantity, 0)) AS site_fba_available,
           SUM(COALESCE(p.volume, 0)) AS site_sales_volume
    FROM listing_keys k
    JOIN dwd_datasync.lx_statistics_product_performance p
      ON k.country_category = CASE
          WHEN CAST(p.country AS CHAR) = '英国' THEN '英国站'
          WHEN CAST(p.country AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
          ELSE '欧洲站'
      END
     AND k.store = CASE
          WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.seller_name AS CHAR), ' ', 1)) > 0
              THEN LEFT(
                  SUBSTRING_INDEX(CAST(p.seller_name AS CHAR), ' ', 1),
                  LOCATE('-', SUBSTRING_INDEX(CAST(p.seller_name AS CHAR), ' ', 1)) - 1
              )
          ELSE SUBSTRING_INDEX(CAST(p.seller_name AS CHAR), ' ', 1)
      END
     AND k.msku = CAST(p.seller_sku AS CHAR)
    CROSS JOIN params q
    WHERE DATE(p.start_date) BETWEEN DATE_SUB(q.data_date, INTERVAL 380 DAY) AND q.data_date
    GROUP BY k.country_category, k.store, k.msku, DATE(p.start_date)
),
return_daily_seq AS (
    SELECT d.*,
           MAX(CASE WHEN d.site_fba_available > 5 THEN d.stat_date END)
               OVER (
                   PARTITION BY d.country_category, d.store, d.msku
                   ORDER BY d.stat_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
               ) AS previous_gt5_date,
           MAX(CASE WHEN d.site_fba_available = 0 THEN d.stat_date END)
               OVER (
                   PARTITION BY d.country_category, d.store, d.msku
                   ORDER BY d.stat_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
               ) AS previous_zero_date
    FROM return_daily d
),
return_daily_segmented AS (
    SELECT d.*,
           MIN(CASE WHEN d.site_fba_available = 0 THEN d.stat_date END)
               OVER (
                   PARTITION BY d.country_category, d.store, d.msku, d.previous_gt5_date
               ) AS segment_stockout_date
    FROM return_daily_seq d
),
return_candidates AS (
    SELECT d.country_category,
           d.store,
           d.msku,
           d.segment_stockout_date AS stockout_date,
           d.stat_date AS return_start_date
    FROM return_daily_segmented d
    WHERE d.site_fba_available > 5
      AND d.previous_zero_date IS NOT NULL
      AND (d.previous_gt5_date IS NULL OR d.previous_zero_date > d.previous_gt5_date)
      AND d.segment_stockout_date IS NOT NULL
),
return_pool AS (
    SELECT d.country_category,
           d.store,
           d.msku
    FROM return_daily d
    CROSS JOIN params q
    WHERE d.stat_date BETWEEN DATE_SUB(q.data_date, INTERVAL 179 DAY) AND q.data_date
    GROUP BY d.country_category, d.store, d.msku
    HAVING SUM(CASE WHEN d.site_fba_available = 0 THEN 1 ELSE 0 END) > 0
       AND SUM(COALESCE(d.site_sales_volume, 0)) > 0
),
return_ranked AS (
    SELECT c.*,
           ROW_NUMBER() OVER (
               PARTITION BY c.country_category, c.store, c.msku
               ORDER BY c.return_start_date DESC, c.stockout_date DESC
           ) AS event_rank
    FROM return_candidates c
    CROSS JOIN params q
    WHERE c.return_start_date BETWEEN DATE_SUB(q.data_date, INTERVAL 179 DAY) AND q.data_date
),
latest_return AS (
    SELECT r.country_category,
           r.store,
           r.msku,
           r.stockout_date,
           r.return_start_date,
           DATEDIFF(q.data_date, r.return_start_date) + 1 AS return_days,
           CASE
               WHEN DATEDIFF(q.data_date, r.return_start_date) BETWEEN 0 AND 6 THEN '观察期'
               WHEN DATEDIFF(q.data_date, r.return_start_date) BETWEEN 7 AND 20 THEN '干预期'
               ELSE '退出阶段'
           END AS return_stage
    FROM return_ranked r
    JOIN return_pool p
      ON r.country_category = p.country_category
     AND r.store = p.store
     AND r.msku = p.msku
    CROSS JOIN params q
    WHERE r.event_rank = 1
),
summary AS (
    SELECT COUNT(*) AS latest_completed_return_msku,
           SUM(CASE WHEN return_days BETWEEN 1 AND 21 THEN 1 ELSE 0 END) AS return_label_msku,
           SUM(CASE WHEN return_stage = '观察期' THEN 1 ELSE 0 END) AS observe_msku,
           SUM(CASE WHEN return_stage = '干预期' THEN 1 ELSE 0 END) AS operating_msku,
           SUM(CASE WHEN return_stage = '退出阶段' THEN 1 ELSE 0 END) AS exited_msku
    FROM latest_return
)
SELECT q.data_date,
       s.latest_completed_return_msku,
       s.return_label_msku,
       s.observe_msku,
       s.operating_msku,
       s.exited_msku,
       r.country_category,
       r.store,
       r.msku,
       r.stockout_date,
       r.return_start_date,
       r.return_days,
       r.return_stage
FROM latest_return r
CROSS JOIN summary s
CROSS JOIN params q
WHERE r.return_days BETWEEN 1 AND 21
ORDER BY r.return_stage, r.return_days, r.country_category, r.store, r.msku;
