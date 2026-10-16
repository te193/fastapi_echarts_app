
drop procedure if exists dws_datasync.sp_dws_msku_daily_sales;
delimiter $$
create procedure dws_datasync.sp_dws_msku_daily_sales()
begin

SET @biz_date := (
    SELECT DATE(MAX(start_date))
    FROM dwd_datasync.lx_statistics_product_performance
);
SET @start_date_180d := DATE_SUB(@biz_date, INTERVAL 179 DAY);
SET @start_date_30d := DATE_SUB(@biz_date, INTERVAL 29 DAY);

/* 先按依赖倒序清理，便于在同一连接中重复运行。 */
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_receiving;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_follow_metric;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_origin;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_metric;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_candidate;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_follow_asin;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_candidate_asin;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_self_asin;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_listing;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_performance;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_daily_sales_candidate_base;

/*
候选范围仍按原逻辑保留近 180 天出现过的 MSKU。
这里仅投影三个业务键，不携带销量和库存明细，避免后续处理 180 天宽数据。
*/
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_candidate_base
ENGINE = InnoDB
AS
SELECT DISTINCT
    CAST(candidate_key.country_category AS CHAR(16)) AS country_category,
    CAST(candidate_key.seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(candidate_key.seller_sku_adj AS CHAR(255)) AS seller_sku_adj
FROM (
SELECT
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
    ) AS seller_sku_adj
FROM dwd_datasync.lx_statistics_product_performance AS p
WHERE p.start_date >= @start_date_180d
  AND p.start_date < DATE_ADD(@biz_date, INTERVAL 1 DAY)
  AND p.seller_sku NOT LIKE 'Amazon.Found%'
  AND NULLIF(p.seller_name, '') IS NOT NULL
  AND NULLIF(p.seller_sku, '') IS NOT NULL
) AS candidate_key
WHERE NULLIF(candidate_key.seller_sku_adj, '') IS NOT NULL;

ALTER TABLE dws_datasync.tmp_daily_sales_candidate_base
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/*
阶段 1：产品表现日汇总。
先标准化店铺、MSKU、站点，再压缩到每日唯一粒度，避免后续重复扫描大表。
*/
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_performance
ENGINE = InnoDB
AS
SELECT
    normalized.dt_date,
    CAST(normalized.country_category AS CHAR(16)) AS country_category,
    CAST(normalized.seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(normalized.seller_sku_adj AS CHAR(255)) AS seller_sku_adj,
    SUM(normalized.sales_qty) AS sales_qty,
    MAX(normalized.afn_fulfillable_quantity) AS afn_fulfillable_quantity
FROM (
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
    WHERE p.start_date >= @start_date_30d
      AND p.start_date < DATE_ADD(@biz_date, INTERVAL 1 DAY)
      AND p.seller_sku NOT LIKE 'Amazon.Found%'
      AND NULLIF(p.seller_name, '') IS NOT NULL
      AND NULLIF(p.seller_sku, '') IS NOT NULL
) AS normalized
WHERE NULLIF(normalized.seller_sku_adj, '') IS NOT NULL
GROUP BY
    normalized.dt_date,
    normalized.country_category,
    normalized.seller_name_new,
    normalized.seller_sku_adj;

ALTER TABLE dws_datasync.tmp_daily_sales_performance
    ADD PRIMARY KEY (dt_date, country_category, seller_name_new, seller_sku_adj),
    ADD KEY idx_msku (country_category, seller_name_new, seller_sku_adj);

/* 阶段 2：Listing 统一并压缩为站点 + 店铺 + MSKU 唯一记录。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_listing
ENGINE = InnoDB
AS
SELECT
    CAST(src.country_category AS CHAR(16)) AS country_category,
    CAST(src.seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(src.seller_sku AS CHAR(255)) AS seller_sku,
    CAST(MAX(src.asin) AS CHAR(32)) AS max_asin,
    MAX(src.fnsku) AS max_fnsku,
    MAX(src.local_sku) AS max_sku,
    MAX(product_info.brand_name) AS max_brand_name
FROM (
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
) AS src
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
    src.seller_sku;

ALTER TABLE dws_datasync.tmp_daily_sales_listing
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku),
    ADD KEY idx_asin (country_category, max_asin),
    ADD KEY idx_store_asin (seller_name_new, max_asin);

/* 店铺品牌关系命中的 ASIN 视为自产链接。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_self_asin
ENGINE = InnoDB
AS
SELECT DISTINCT
    CAST(store.`店铺名` AS CHAR(128)) AS seller_name_new,
    CAST(listing.asin AS CHAR(32)) AS asin
FROM dwd_datasync.lx_sales_mws_listing AS listing
INNER JOIN opt_db.store_brand_relation AS store
    ON store.`店铺名` = SUBSTRING_INDEX(listing.seller_name, '-', 1)
   AND store.`品牌名` = listing.seller_brand
WHERE NULLIF(listing.asin, '') IS NOT NULL;

ALTER TABLE dws_datasync.tmp_daily_sales_self_asin
    ADD PRIMARY KEY (seller_name_new, asin),
    ADD KEY idx_asin (asin);

/* 先物化候选 ASIN，避免 MySQL 在同一语句中重复打开 Listing 临时表。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_candidate_asin
ENGINE = InnoDB
AS
SELECT DISTINCT
    candidate_base.country_category,
    listing.max_asin
FROM dws_datasync.tmp_daily_sales_candidate_base AS candidate_base
INNER JOIN dws_datasync.tmp_daily_sales_listing AS listing
    ON listing.country_category = candidate_base.country_category
   AND listing.seller_name_new = candidate_base.seller_name_new
   AND listing.seller_sku = candidate_base.seller_sku_adj
WHERE NULLIF(listing.max_asin, '') IS NOT NULL;

ALTER TABLE dws_datasync.tmp_daily_sales_candidate_asin
    ADD PRIMARY KEY (country_category, max_asin);

/* 识别同站点、同 ASIN 下同时存在自产和非自产链接的 ASIN。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_follow_asin
ENGINE = InnoDB
AS
SELECT
    candidate.country_category,
    candidate.max_asin
FROM dws_datasync.tmp_daily_sales_candidate_asin AS candidate
INNER JOIN dws_datasync.tmp_daily_sales_listing AS listing FORCE INDEX (idx_asin)
    ON listing.country_category = candidate.country_category
   AND listing.max_asin = candidate.max_asin
LEFT JOIN dws_datasync.tmp_daily_sales_self_asin AS self_asin
    ON self_asin.seller_name_new = listing.seller_name_new
   AND self_asin.asin = listing.max_asin
GROUP BY
    candidate.country_category,
    candidate.max_asin
HAVING COUNT(DISTINCT CONCAT(listing.seller_name_new, CHAR(0), listing.seller_sku)) > 1
   AND MAX(CASE WHEN self_asin.asin IS NOT NULL THEN 1 ELSE 0 END) > 0
   AND MAX(CASE WHEN self_asin.asin IS NULL THEN 1 ELSE 0 END) > 0;

ALTER TABLE dws_datasync.tmp_daily_sales_follow_asin
    ADD PRIMARY KEY (country_category, max_asin);

/* 阶段 3：正常产品表现 MSKU + 需要补入的跟卖 MSKU。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_candidate
ENGINE = InnoDB
AS
SELECT DISTINCT
    candidate_base.country_category,
    candidate_base.seller_name_new,
    candidate_base.seller_sku_adj
FROM dws_datasync.tmp_daily_sales_candidate_base AS candidate_base

UNION

SELECT
    listing.country_category,
    listing.seller_name_new,
    listing.seller_sku AS seller_sku_adj
FROM dws_datasync.tmp_daily_sales_listing AS listing
INNER JOIN dws_datasync.tmp_daily_sales_follow_asin AS follow_asin
    ON follow_asin.country_category = listing.country_category
   AND follow_asin.max_asin = listing.max_asin
LEFT JOIN dws_datasync.tmp_daily_sales_self_asin AS listing_self
    ON listing_self.seller_name_new = listing.seller_name_new
   AND listing_self.asin = listing.max_asin
WHERE listing_self.asin IS NULL
  AND NULLIF(listing.seller_sku, '') IS NOT NULL
  AND listing.seller_sku NOT LIKE 'amzn.%';

ALTER TABLE dws_datasync.tmp_daily_sales_candidate
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/*
阶段 4：一次聚合得到自身 3/7/14/30 天销量和历史有货天数，随后接入 Listing 字段。
*/
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_metric
ENGINE = InnoDB
AS
SELECT
    candidate.country_category,
    candidate.seller_name_new,
    candidate.seller_sku_adj,
    listing.max_asin,
    listing.max_fnsku,
    listing.max_sku,
    listing.max_brand_name,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 29 DAY)
                      THEN performance.sales_qty ELSE 0 END), 0) AS sales_30,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 13 DAY)
                      THEN performance.sales_qty ELSE 0 END), 0) AS sales_14,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 6 DAY)
                      THEN performance.sales_qty ELSE 0 END), 0) AS sales_7,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 2 DAY)
                      THEN performance.sales_qty ELSE 0 END), 0) AS sales_3,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 29 DAY)
                           AND performance.afn_fulfillable_quantity > 0
                      THEN 1 ELSE 0 END), 0) AS salable_days_30,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 13 DAY)
                           AND performance.afn_fulfillable_quantity > 0
                      THEN 1 ELSE 0 END), 0) AS salable_days_14,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 6 DAY)
                           AND performance.afn_fulfillable_quantity > 0
                      THEN 1 ELSE 0 END), 0) AS salable_days_7,
    COALESCE(SUM(CASE WHEN performance.dt_date >= DATE_SUB(@biz_date, INTERVAL 2 DAY)
                           AND performance.afn_fulfillable_quantity > 0
                      THEN 1 ELSE 0 END), 0) AS salable_days_3
FROM dws_datasync.tmp_daily_sales_candidate AS candidate
LEFT JOIN dws_datasync.tmp_daily_sales_performance AS performance
    ON performance.country_category = candidate.country_category
   AND performance.seller_name_new = candidate.seller_name_new
   AND performance.seller_sku_adj = candidate.seller_sku_adj
LEFT JOIN dws_datasync.tmp_daily_sales_listing AS listing
    ON listing.country_category = candidate.country_category
   AND listing.seller_name_new = candidate.seller_name_new
   AND listing.seller_sku = candidate.seller_sku_adj
GROUP BY
    candidate.country_category,
    candidate.seller_name_new,
    candidate.seller_sku_adj,
    listing.max_asin,
    listing.max_fnsku,
    listing.max_sku,
    listing.max_brand_name;

ALTER TABLE dws_datasync.tmp_daily_sales_metric
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj),
    ADD KEY idx_asin (country_category, max_asin);

/* 每个站点 + ASIN 选择一个原始链接：优先自产，其次选择周期销量更高的链接。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_origin
ENGINE = InnoDB
AS
SELECT
    ranked.country_category,
    ranked.max_asin,
    ranked.seller_name_new AS origin_seller_name_new,
    ranked.seller_sku_adj AS origin_seller_sku_adj,
    ranked.max_brand_name AS origin_brand_name,
    ranked.sales_3 AS origin_sales_3,
    ranked.sales_7 AS origin_sales_7,
    ranked.sales_14 AS origin_sales_14,
    ranked.sales_30 AS origin_sales_30,
    ranked.salable_days_3 AS origin_salable_days_3,
    ranked.salable_days_7 AS origin_salable_days_7,
    ranked.salable_days_14 AS origin_salable_days_14,
    ranked.salable_days_30 AS origin_salable_days_30
FROM (
    SELECT
        metric.*,
        ROW_NUMBER() OVER (
            PARTITION BY metric.country_category, metric.max_asin
            ORDER BY
                CASE WHEN self_asin.asin IS NOT NULL THEN 0 ELSE 1 END,
                metric.sales_30 DESC,
                metric.sales_14 DESC,
                metric.sales_7 DESC,
                metric.sales_3 DESC,
                metric.seller_name_new,
                metric.seller_sku_adj
        ) AS origin_rank
FROM dws_datasync.tmp_daily_sales_metric AS metric
LEFT JOIN dws_datasync.tmp_daily_sales_self_asin AS self_asin
        ON self_asin.seller_name_new = metric.seller_name_new
       AND self_asin.asin = metric.max_asin
    WHERE NULLIF(metric.max_asin, '') IS NOT NULL
) AS ranked
WHERE ranked.origin_rank = 1;

ALTER TABLE dws_datasync.tmp_daily_sales_origin
    ADD PRIMARY KEY (country_category, max_asin),
    ADD KEY idx_origin_msku (country_category, origin_seller_name_new, origin_seller_sku_adj);

/*
阶段 5：识别跟卖并继承原始链接指标。
跟卖销量 = 自身销量 + 原始链接销量；历史有货天数取两者较大值。
*/
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_follow_metric
ENGINE = InnoDB
AS
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
FROM (
    SELECT
        metric.*,
        CASE
            WHEN self_asin.asin IS NOT NULL
              OR origin.origin_seller_sku_adj IS NULL
              OR (
                    metric.seller_name_new = origin.origin_seller_name_new
                AND metric.seller_sku_adj = origin.origin_seller_sku_adj
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
FROM dws_datasync.tmp_daily_sales_metric AS metric
LEFT JOIN dws_datasync.tmp_daily_sales_self_asin AS self_asin
        ON self_asin.seller_name_new = metric.seller_name_new
       AND self_asin.asin = metric.max_asin
LEFT JOIN dws_datasync.tmp_daily_sales_origin AS origin
        ON origin.country_category = metric.country_category
       AND origin.max_asin = metric.max_asin
) AS relation;

ALTER TABLE dws_datasync.tmp_daily_sales_follow_metric
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/* 阶段 6：收货次数。口径保持与原补货逻辑一致。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_daily_sales_receiving
ENGINE = InnoDB
AS
SELECT
    CAST(shipment.country_category AS CHAR(16)) AS country_category,
    CAST(shipment.seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(shipment.msku AS CHAR(255)) AS msku,
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
    shipment.msku;

ALTER TABLE dws_datasync.tmp_daily_sales_receiving
    ADD PRIMARY KEY (country_category, seller_name_new, msku);

/*
最终阶段只处理已压缩的小临时表：计算修正日销、新老品加权并输出英文结果字段。
*/
delete from dws_datasync.dws_msku_daily_sales where data_date = @biz_date;
insert into dws_datasync.dws_msku_daily_sales
WITH adjusted AS (
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
    FROM dws_datasync.tmp_daily_sales_follow_metric AS metric
    LEFT JOIN dws_datasync.tmp_daily_sales_receiving AS receiving
        ON receiving.country_category = metric.country_category
       AND receiving.seller_name_new = metric.seller_name_new
       AND receiving.msku = metric.seller_sku_adj
),
final_result AS (
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
    FROM adjusted AS daily
)
SELECT
    @biz_date AS data_date,
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
FROM final_result AS result
ORDER BY
    result.country_category,
    result.seller_name_new,
    result.seller_sku_adj;
end$$
delimiter ;
