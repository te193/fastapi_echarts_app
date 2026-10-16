/*
用途：在远端数据库独立复算补货页面最终日销。

说明：
1. 本文件只有查询计算过程，不包含建表、删表和写入语句。
2. 输出粒度：数据日期 + 站点 + 店铺名 + MSKU。
3. 逻辑对齐补货页面：历史有货天数修正、跟卖继承原始链接销量、新老品加权。
4. 跟卖口径沿用现有补货逻辑：跟卖链接的周期销量 = 自身周期销量 + 原始链接周期销量。
*/

WITH
业务参数 AS (
    SELECT
        DATE(MAX(start_date)) AS biz_date,
        DATE_SUB(DATE(MAX(start_date)), INTERVAL 179 DAY) AS start_date_180d
    FROM dwd_datasync.lx_statistics_product_performance
),

/* 远端产品表现日数据，先统一为站点 + 店铺 + MSKU + 日期粒度。 */
产品表现标准化 AS (
    SELECT
        DATE(p.start_date) AS dt_date,
        CASE
            WHEN p.country = '英国' THEN '英国站'
            WHEN p.country IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
            ELSE '欧洲站'
        END AS country_category,
        CASE
            WHEN LOCATE('-', p.seller_name) > 0
                THEN LEFT(p.seller_name, LOCATE('-', p.seller_name) - 1)
            ELSE p.seller_name
        END AS seller_name_new,
        IF(
            LENGTH(SUBSTRING_INDEX(p.seller_sku, ',', 1)) > 16,
            CASE
                WHEN SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1)
                     LIKE 'amzn.gr.%'
                    THEN SUBSTRING(
                        SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1),
                        9
                    )
                ELSE SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1)
            END,
            SUBSTRING_INDEX(p.seller_sku, ',', 1)
        ) AS seller_sku_adj,
        COALESCE(p.volume, 0) AS sales_qty,
        COALESCE(p.afn_fulfillable_quantity, 0) AS afn_fulfillable_quantity
    FROM dwd_datasync.lx_statistics_product_performance AS p
    CROSS JOIN 业务参数 AS prm
    WHERE p.start_date >= prm.start_date_180d
      AND p.start_date < DATE_ADD(prm.biz_date, INTERVAL 1 DAY)
      AND p.seller_sku NOT LIKE 'Amazon.Found%'
      AND NULLIF(p.seller_name, '') IS NOT NULL
      AND NULLIF(p.seller_sku, '') IS NOT NULL
),
产品表现日汇总 AS (
    SELECT
        dt_date,
        country_category,
        seller_name_new,
        seller_sku_adj,
        SUM(sales_qty) AS sales_qty,
        MAX(afn_fulfillable_quantity) AS afn_fulfillable_quantity
    FROM 产品表现标准化
    WHERE NULLIF(seller_sku_adj, '') IS NOT NULL
    GROUP BY
        dt_date,
        country_category,
        seller_name_new,
        seller_sku_adj
),

/* Listing 同时使用 ETL 清洗表和原始表，逻辑与补货页面同步链路一致。 */
Listing来源 AS (
    SELECT
        seller_sku,
        fnsku,
        asin,
        local_sku,
        marketplace,
        seller_name_new,
        country_category
    FROM etl_datasync.etl_dispose_lx_sales_mws_listing

    UNION ALL

    SELECT
        raw.seller_sku,
        raw.fnsku,
        raw.asin,
        raw.local_sku,
        raw.marketplace,
        SUBSTRING_INDEX(raw.seller_name, '-', 1) AS seller_name_new,
        CASE
            WHEN UPPER(raw.marketplace) IN ('US', 'CA', 'MX', 'BR')
              OR raw.marketplace IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
            WHEN UPPER(raw.marketplace) IN ('UK', 'GB')
              OR raw.marketplace = '英国' THEN '英国站'
            ELSE '欧洲站'
        END AS country_category
    FROM dwd_datasync.lx_sales_mws_listing AS raw
    WHERE NULLIF(raw.seller_sku, '') IS NOT NULL
      AND NULLIF(raw.asin, '') IS NOT NULL
),
Listing汇总 AS (
    SELECT
        src.country_category,
        src.seller_name_new,
        src.seller_sku,
        MAX(src.asin) AS max_asin,
        MAX(src.fnsku) AS max_fnsku,
        MAX(src.local_sku) AS max_sku,
        MAX(product_info.brand_name) AS max_brand_name
    FROM Listing来源 AS src
    LEFT JOIN etl_datasync.etl_dispose_lx_product_local_product_info AS product_info
        ON product_info.seller_sku = src.seller_sku
       AND product_info.country = src.marketplace
       AND product_info.seller_name_new = src.seller_name_new
    WHERE NULLIF(src.seller_sku, '') IS NOT NULL
      AND NULLIF(src.seller_name_new, '') IS NOT NULL
      AND NULLIF(src.country_category, '') IS NOT NULL
    GROUP BY
        src.country_category,
        src.seller_name_new,
        src.seller_sku
),

/* 店铺品牌关系命中的 ASIN 视为自产链接。 */
自产ASIN AS (
    SELECT DISTINCT
        store.`店铺名` AS seller_name_new,
        listing.asin
    FROM dwd_datasync.lx_sales_mws_listing AS listing
    INNER JOIN opt_db.store_brand_relation AS store
        ON store.`店铺名` = SUBSTRING_INDEX(listing.seller_name, '-', 1)
       AND store.`品牌名` = listing.seller_brand
    WHERE NULLIF(listing.asin, '') IS NOT NULL
),

/* 先取得正常有产品表现的候选 MSKU。 */
基础候选MSKU AS (
    SELECT DISTINCT
        country_category,
        seller_name_new,
        seller_sku_adj
    FROM 产品表现日汇总
),
候选ASIN AS (
    SELECT DISTINCT
        candidate.country_category,
        listing.max_asin
    FROM 基础候选MSKU AS candidate
    INNER JOIN Listing汇总 AS listing
        ON listing.country_category = candidate.country_category
       AND listing.seller_name_new = candidate.seller_name_new
       AND listing.seller_sku = candidate.seller_sku_adj
    WHERE NULLIF(listing.max_asin, '') IS NOT NULL
),

/* 同一站点、同一 ASIN 同时存在自产和非自产链接时，启用跟卖继承。 */
跟卖ASIN AS (
    SELECT
        candidate.country_category,
        candidate.max_asin
    FROM 候选ASIN AS candidate
    INNER JOIN Listing汇总 AS listing
        ON listing.country_category = candidate.country_category
       AND listing.max_asin = candidate.max_asin
    LEFT JOIN 自产ASIN AS self_asin
        ON self_asin.seller_name_new = listing.seller_name_new
       AND self_asin.asin = listing.max_asin
    GROUP BY
        candidate.country_category,
        candidate.max_asin
    HAVING COUNT(DISTINCT CONCAT(listing.seller_name_new, CHAR(0), listing.seller_sku)) > 1
       AND MAX(CASE WHEN self_asin.asin IS NOT NULL THEN 1 ELSE 0 END) > 0
       AND MAX(CASE WHEN self_asin.asin IS NULL THEN 1 ELSE 0 END) > 0
),

/* 补入没有产品表现、但与自产链接共用 ASIN 的跟卖链接。 */
全部候选MSKU AS (
    SELECT
        country_category,
        seller_name_new,
        seller_sku_adj
    FROM 基础候选MSKU

    UNION

    SELECT
        listing.country_category,
        listing.seller_name_new,
        listing.seller_sku AS seller_sku_adj
    FROM Listing汇总 AS listing
    INNER JOIN 跟卖ASIN AS follow_asin
        ON follow_asin.country_category = listing.country_category
       AND follow_asin.max_asin = listing.max_asin
    LEFT JOIN 自产ASIN AS listing_self
        ON listing_self.seller_name_new = listing.seller_name_new
       AND listing_self.asin = listing.max_asin
    WHERE listing_self.asin IS NULL
      AND NULLIF(listing.seller_sku, '') IS NOT NULL
      AND listing.seller_sku NOT LIKE 'amzn.%'
),

/* 自身周期销量。跟卖继承发生在后续步骤，不在这里混入。 */
自身周期指标 AS (
    SELECT
        candidate.country_category,
        candidate.seller_name_new,
        candidate.seller_sku_adj,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 29 DAY)
                          THEN perf.sales_qty ELSE 0 END), 0) AS sales_30,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 13 DAY)
                          THEN perf.sales_qty ELSE 0 END), 0) AS sales_14,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 6 DAY)
                          THEN perf.sales_qty ELSE 0 END), 0) AS sales_7,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 2 DAY)
                          THEN perf.sales_qty ELSE 0 END), 0) AS sales_3,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 29 DAY)
                               AND perf.afn_fulfillable_quantity > 0
                          THEN 1 ELSE 0 END), 0) AS salable_days_30,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 13 DAY)
                               AND perf.afn_fulfillable_quantity > 0
                          THEN 1 ELSE 0 END), 0) AS salable_days_14,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 6 DAY)
                               AND perf.afn_fulfillable_quantity > 0
                          THEN 1 ELSE 0 END), 0) AS salable_days_7,
        COALESCE(SUM(CASE WHEN perf.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 2 DAY)
                               AND perf.afn_fulfillable_quantity > 0
                          THEN 1 ELSE 0 END), 0) AS salable_days_3
    FROM 全部候选MSKU AS candidate
    CROSS JOIN 业务参数 AS prm
    LEFT JOIN 产品表现日汇总 AS perf
        ON perf.country_category = candidate.country_category
       AND perf.seller_name_new = candidate.seller_name_new
       AND perf.seller_sku_adj = candidate.seller_sku_adj
    GROUP BY
        candidate.country_category,
        candidate.seller_name_new,
        candidate.seller_sku_adj
),
MSKU桥接 AS (
    SELECT
        metric.country_category,
        metric.seller_name_new,
        metric.seller_sku_adj,
        listing.max_asin,
        listing.max_fnsku,
        listing.max_sku,
        listing.max_brand_name,
        metric.sales_3,
        metric.sales_7,
        metric.sales_14,
        metric.sales_30,
        metric.salable_days_3,
        metric.salable_days_7,
        metric.salable_days_14,
        metric.salable_days_30
    FROM 自身周期指标 AS metric
    LEFT JOIN Listing汇总 AS listing
        ON listing.country_category = metric.country_category
       AND listing.seller_name_new = metric.seller_name_new
       AND listing.seller_sku = metric.seller_sku_adj
),

/* 每个站点 + ASIN 选择一个原始链接：优先自产，其次近30天销量高的链接。 */
原始链接排名 AS (
    SELECT
        bridge.*,
        CASE WHEN self_asin.asin IS NOT NULL THEN 1 ELSE 0 END AS is_self_asin,
        ROW_NUMBER() OVER (
            PARTITION BY bridge.country_category, bridge.max_asin
            ORDER BY
                CASE WHEN self_asin.asin IS NOT NULL THEN 0 ELSE 1 END,
                bridge.sales_30 DESC,
                bridge.sales_14 DESC,
                bridge.sales_7 DESC,
                bridge.sales_3 DESC,
                bridge.seller_name_new,
                bridge.seller_sku_adj
        ) AS origin_rank
    FROM MSKU桥接 AS bridge
    LEFT JOIN 自产ASIN AS self_asin
        ON self_asin.seller_name_new = bridge.seller_name_new
       AND self_asin.asin = bridge.max_asin
    WHERE NULLIF(bridge.max_asin, '') IS NOT NULL
),
原始链接 AS (
    SELECT
        country_category,
        max_asin,
        seller_name_new AS origin_seller_name_new,
        seller_sku_adj AS origin_seller_sku_adj,
        max_brand_name AS origin_brand_name,
        sales_3 AS origin_sales_3,
        sales_7 AS origin_sales_7,
        sales_14 AS origin_sales_14,
        sales_30 AS origin_sales_30,
        salable_days_3 AS origin_salable_days_3,
        salable_days_7 AS origin_salable_days_7,
        salable_days_14 AS origin_salable_days_14,
        salable_days_30 AS origin_salable_days_30
    FROM 原始链接排名
    WHERE origin_rank = 1
),

/* 判断当前 MSKU 是否跟卖，并带出需要继承的原始链接指标。 */
跟卖关系 AS (
    SELECT
        bridge.*,
        CASE
            WHEN self_asin.asin IS NOT NULL
              OR origin.origin_seller_sku_adj IS NULL
              OR (
                    bridge.seller_name_new = origin.origin_seller_name_new
                AND bridge.seller_sku_adj = origin.origin_seller_sku_adj
              ) THEN 1
            ELSE 0
        END AS fllow_flag,
        origin.origin_seller_name_new,
        origin.origin_seller_sku_adj,
        origin.origin_brand_name,
        origin.origin_sales_3,
        origin.origin_sales_7,
        origin.origin_sales_14,
        origin.origin_sales_30,
        origin.origin_salable_days_3,
        origin.origin_salable_days_7,
        origin.origin_salable_days_14,
        origin.origin_salable_days_30
    FROM MSKU桥接 AS bridge
    LEFT JOIN 自产ASIN AS self_asin
        ON self_asin.seller_name_new = bridge.seller_name_new
       AND self_asin.asin = bridge.max_asin
    LEFT JOIN 原始链接 AS origin
        ON origin.country_category = bridge.country_category
       AND origin.max_asin = bridge.max_asin
),

/* 跟卖链接按现有补货口径：自身销量 + 原始链接销量；有货天数取两者较大值。 */
继承后周期指标 AS (
    SELECT
        relation.*,
        CASE WHEN relation.fllow_flag = 1
             THEN relation.sales_3
             ELSE relation.sales_3 + COALESCE(relation.origin_sales_3, 0)
        END AS final_sales_3,
        CASE WHEN relation.fllow_flag = 1
             THEN relation.sales_7
             ELSE relation.sales_7 + COALESCE(relation.origin_sales_7, 0)
        END AS final_sales_7,
        CASE WHEN relation.fllow_flag = 1
             THEN relation.sales_14
             ELSE relation.sales_14 + COALESCE(relation.origin_sales_14, 0)
        END AS final_sales_14,
        CASE WHEN relation.fllow_flag = 1
             THEN relation.sales_30
             ELSE relation.sales_30 + COALESCE(relation.origin_sales_30, 0)
        END AS final_sales_30,
        GREATEST(
            relation.salable_days_3,
            CASE WHEN relation.fllow_flag = 1 THEN 0 ELSE COALESCE(relation.origin_salable_days_3, 0) END
        ) AS final_salable_days_3,
        GREATEST(
            relation.salable_days_7,
            CASE WHEN relation.fllow_flag = 1 THEN 0 ELSE COALESCE(relation.origin_salable_days_7, 0) END
        ) AS final_salable_days_7,
        GREATEST(
            relation.salable_days_14,
            CASE WHEN relation.fllow_flag = 1 THEN 0 ELSE COALESCE(relation.origin_salable_days_14, 0) END
        ) AS final_salable_days_14,
        GREATEST(
            relation.salable_days_30,
            CASE WHEN relation.fllow_flag = 1 THEN 0 ELSE COALESCE(relation.origin_salable_days_30, 0) END
        ) AS final_salable_days_30
    FROM 跟卖关系 AS relation
),

/* 新品判断所需的收货次数，复刻补货页面的远端 FBA shipment 口径。 */
收货次数 AS (
    SELECT
        shipment.country_category,
        shipment.seller_name_new,
        shipment.msku,
        MAX(receiving_count.receiving_cnt) AS receiving_cnt
    FROM etl_datasync.etl_dispose_lx_fba_shipment AS shipment
    LEFT JOIN (
        SELECT
            msku,
            store_name,
            COUNT(*) AS receiving_cnt
        FROM etl_datasync.etl_dispose_lx_fba_shipment
        WHERE receiving_time IS NOT NULL
          AND quantity_shipped <> 0
        GROUP BY msku, store_name
    ) AS receiving_count
        ON receiving_count.msku = shipment.msku
       AND receiving_count.store_name = shipment.store_name
    WHERE shipment.receiving_time IS NOT NULL
      AND shipment.quantity_received <> 0
      AND NULLIF(shipment.msku, '') IS NOT NULL
      AND NULLIF(shipment.seller_name_new, '') IS NOT NULL
      AND NULLIF(shipment.country_category, '') IS NOT NULL
    GROUP BY
        shipment.country_category,
        shipment.seller_name_new,
        shipment.msku
),

/* 计算各周期修正日销。 */
周期修正日销 AS (
    SELECT
        metric.*,
        COALESCE(NULLIF(metric.max_brand_name, ''), metric.origin_brand_name) AS effective_brand_name,
        receiving.receiving_cnt,
        CASE
            WHEN metric.final_salable_days_30 >= 7 THEN
                CASE WHEN metric.final_salable_days_3 > 0
                     THEN metric.final_sales_3 / metric.final_salable_days_3
                     ELSE 0
                END
            ELSE metric.final_sales_3 / GREATEST(metric.final_salable_days_3, 2)
        END AS adjusted_daily_sales_3,
        CASE
            WHEN metric.final_salable_days_30 >= 7 THEN
                CASE
                    WHEN metric.final_salable_days_7 >= 7
                        THEN metric.final_sales_7 / metric.final_salable_days_7
                    ELSE LEAST(
                        CASE WHEN metric.final_salable_days_7 > 0
                             THEN metric.final_sales_7 / metric.final_salable_days_7
                             ELSE 0
                        END,
                        (CASE WHEN metric.final_salable_days_7 > 0
                              THEN metric.final_sales_7 / metric.final_salable_days_7
                              ELSE 0
                         END)
                            * (metric.final_salable_days_7 / (metric.final_salable_days_7 + 3))
                        + (metric.final_sales_30 / metric.final_salable_days_30)
                            * (1 - metric.final_salable_days_7 / (metric.final_salable_days_7 + 3))
                    )
                END
            ELSE metric.final_sales_7 / GREATEST(metric.final_salable_days_7, 3)
        END AS adjusted_daily_sales_7,
        CASE
            WHEN metric.final_salable_days_30 >= 7 THEN
                CASE
                    WHEN metric.final_salable_days_14 >= 14
                        THEN metric.final_sales_14 / metric.final_salable_days_14
                    ELSE LEAST(
                        CASE WHEN metric.final_salable_days_14 > 0
                             THEN metric.final_sales_14 / metric.final_salable_days_14
                             ELSE 0
                        END,
                        (CASE WHEN metric.final_salable_days_14 > 0
                              THEN metric.final_sales_14 / metric.final_salable_days_14
                              ELSE 0
                         END)
                            * (metric.final_salable_days_14 / (metric.final_salable_days_14 + 7))
                        + (metric.final_sales_30 / metric.final_salable_days_30)
                            * (1 - metric.final_salable_days_14 / (metric.final_salable_days_14 + 7))
                    )
                END
            ELSE metric.final_sales_14 / GREATEST(metric.final_salable_days_14, 7)
        END AS adjusted_daily_sales_14,
        CASE
            WHEN metric.final_salable_days_30 >= 7
                THEN metric.final_sales_30 / metric.final_salable_days_30
            ELSE metric.final_sales_30 / GREATEST(metric.final_salable_days_30, 15)
        END AS adjusted_daily_sales_30
    FROM 继承后周期指标 AS metric
    LEFT JOIN 收货次数 AS receiving
        ON receiving.country_category = metric.country_category
       AND receiving.seller_name_new = metric.seller_name_new
       AND receiving.msku = metric.seller_sku_adj
),

最终计算 AS (
    SELECT
        daily.*,
        CASE
            WHEN (
                    daily.effective_brand_name LIKE '%2025%'
                 OR daily.effective_brand_name LIKE '%2026%'
                 )
             AND (daily.receiving_cnt <= 1 OR daily.receiving_cnt IS NULL)
                THEN '新品'
            ELSE '老品'
        END AS product_stage,
        CASE
            WHEN (
                    daily.effective_brand_name LIKE '%2025%'
                 OR daily.effective_brand_name LIKE '%2026%'
                 )
             AND (daily.receiving_cnt <= 1 OR daily.receiving_cnt IS NULL)
                THEN daily.adjusted_daily_sales_3 * 0.5
                   + daily.adjusted_daily_sales_7 * 0.5
            ELSE daily.adjusted_daily_sales_7 * 0.6
               + daily.adjusted_daily_sales_14 * 0.2
               + daily.adjusted_daily_sales_30 * 0.2
        END AS final_daily_sales
    FROM 周期修正日销 AS daily
)

SELECT
    prm.biz_date AS data_date,
    result.country_category AS country_category,
    result.seller_name_new AS seller_name_new,
    result.seller_sku_adj AS seller_sku_adj,
    result.max_asin AS asin,
    result.max_fnsku AS fnsku,
    result.max_sku AS sku,
    CASE WHEN result.fllow_flag = 1 THEN '自产' ELSE '跟卖' END AS follow_type,
    CASE WHEN result.fllow_flag = 1
         THEN NULL
         ELSE CONCAT(result.origin_seller_name_new, '/', result.origin_seller_sku_adj)
    END AS follow_origin_link,
    result.product_stage AS product_stage,
    result.effective_brand_name AS brand_name,
    result.receiving_cnt AS receiving_count,

    result.sales_3 AS own_sales_3d,
    result.sales_7 AS own_sales_7d,
    result.sales_14 AS own_sales_14d,
    result.sales_30 AS own_sales_30d,
    CASE WHEN result.fllow_flag = 1 THEN 0 ELSE COALESCE(result.origin_sales_3, 0) END AS inherited_sales_3d,
    CASE WHEN result.fllow_flag = 1 THEN 0 ELSE COALESCE(result.origin_sales_7, 0) END AS inherited_sales_7d,
    CASE WHEN result.fllow_flag = 1 THEN 0 ELSE COALESCE(result.origin_sales_14, 0) END AS inherited_sales_14d,
    CASE WHEN result.fllow_flag = 1 THEN 0 ELSE COALESCE(result.origin_sales_30, 0) END AS inherited_sales_30d,
    result.final_sales_3 AS final_sales_3d,
    result.final_sales_7 AS final_sales_7d,
    result.final_sales_14 AS final_sales_14d,
    result.final_sales_30 AS final_sales_30d,

    result.final_salable_days_3 AS salable_days_3d,
    result.final_salable_days_7 AS salable_days_7d,
    result.final_salable_days_14 AS salable_days_14d,
    result.final_salable_days_30 AS salable_days_30d,
    ROUND(result.adjusted_daily_sales_3, 6) AS adjusted_daily_sales_3d,
    ROUND(result.adjusted_daily_sales_7, 6) AS adjusted_daily_sales_7d,
    ROUND(result.adjusted_daily_sales_14, 6) AS adjusted_daily_sales_14d,
    ROUND(result.adjusted_daily_sales_30, 6) AS adjusted_daily_sales_30d,
    ROUND(result.final_daily_sales, 6) AS final_daily_sales,
    CASE
        WHEN result.product_stage = '新品' THEN '近3天50% + 近7天50%'
        ELSE '近7天60% + 近14天20% + 近30天20%'
    END AS daily_sales_formula,
    CURRENT_TIMESTAMP AS created_at,
    CURRENT_TIMESTAMP AS updated_at
FROM 最终计算 AS result
CROSS JOIN 业务参数 AS prm
ORDER BY
    result.country_category,
    result.seller_name_new,
    result.seller_sku_adj;
