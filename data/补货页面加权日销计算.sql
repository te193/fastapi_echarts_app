/*
用途：使用两张会话临时表计算补货口径的国家站点加权日销和双币种广告预算，最终直接返回查询结果。

会话临时表：
1. dws_datasync.tmp_replenishment_weighted_sales_product_30d
   - 产品表现最近 30 天的国家周期汇总
2. dws_datasync.tmp_replenishment_listing_price_latest
   - Listing 最新同步日的国家售价和人民币汇率

以上两张表只在当前数据库连接内存在，连接关闭后由 MySQL 自动释放；本 SQL 不持久化过程表或最终结果表。

远端源表：
1. dwd_datasync.lx_statistics_product_performance
2. dwd_datasync.lx_sales_mws_listing
3. dwd_datasync.lx_basic_currency
4. etl_datasync.etl_dispose_lx_product_local_product_info
5. etl_datasync.etl_dispose_lx_fba_shipment

参数：
- @biz_date：产品表现的最新业务日期。
*/

SET @biz_date = (
    SELECT DATE(MAX(start_date))
    FROM dwd_datasync.lx_statistics_product_performance
);
SET @product_start_date = DATE_SUB(@biz_date, INTERVAL 29 DAY);
SET @product_end_date = DATE_ADD(@biz_date, INTERVAL 1 DAY);
SET @listing_date = (
    SELECT DATE(MAX(create_time))
    FROM dwd_datasync.lx_sales_mws_listing
);
SET @listing_end_date = DATE_ADD(@listing_date, INTERVAL 1 DAY);

/* 第一层：会话临时表只扫描最近 30 天，先按日去重，再落国家周期指标。 */
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_replenishment_weighted_sales_product_30d;
CREATE TEMPORARY TABLE dws_datasync.tmp_replenishment_weighted_sales_product_30d
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
AS
SELECT
    d.country_category,
    d.country,
    d.seller_name_new,
    d.seller_sku_adj,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 2 DAY)
             THEN d.sales_qty ELSE 0 END) AS sales_3,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 6 DAY)
             THEN d.sales_qty ELSE 0 END) AS sales_7,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 13 DAY)
             THEN d.sales_qty ELSE 0 END) AS sales_14,
    SUM(d.sales_qty) AS sales_30,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 2 DAY)
              AND d.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
        AS r_3d_salable_days,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 6 DAY)
              AND d.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
        AS r_7d_salable_days,
    SUM(CASE WHEN d.dt_date >= DATE_SUB(@biz_date, INTERVAL 13 DAY)
              AND d.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
        AS r_14d_salable_days,
    SUM(CASE WHEN d.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
        AS r_30d_salable_days
FROM (
    SELECT
        DATE(p.start_date) AS dt_date,
        CAST(
            CASE
                WHEN p.country = '英国' THEN '英国站'
                WHEN p.country IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                ELSE '欧洲站'
            END AS CHAR(16)
        ) AS country_category,
        CAST(p.country AS CHAR(32)) AS country,
        CAST(
            CASE
                WHEN LOCATE('-', p.seller_name) > 0
                    THEN LEFT(p.seller_name, LOCATE('-', p.seller_name) - 1)
                ELSE p.seller_name
            END AS CHAR(64)
        ) AS seller_name_new,
        CAST(
            IF(
                LENGTH(SUBSTRING_INDEX(p.seller_sku, ',', 1)) > 16,
                TRIM(
                    LEADING 'amzn.gr.' FROM
                    SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1)
                ),
                SUBSTRING_INDEX(p.seller_sku, ',', 1)
            ) AS CHAR(100)
        ) AS seller_sku_adj,
        SUM(COALESCE(p.volume, 0)) AS sales_qty,
        MAX(COALESCE(p.afn_fulfillable_quantity, 0)) AS afn_fulfillable_quantity
    FROM dwd_datasync.lx_statistics_product_performance AS p
    FORCE INDEX (idx_osp_performance_dashboard_cover)
    WHERE p.start_date >= DATE_FORMAT(@product_start_date, '%Y-%m-%d')
      AND p.start_date < DATE_FORMAT(@product_end_date, '%Y-%m-%d')
      AND p.seller_sku NOT LIKE 'Amazon.Found%'
      AND p.seller_sku IS NOT NULL
      AND p.seller_sku <> ''
    GROUP BY
        dt_date,
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
) AS d
GROUP BY
    d.country_category,
    d.country,
    d.seller_name_new,
    d.seller_sku_adj;

/* 第二层：会话临时表只扫描最新同步日，再在当天取每个业务键的最新有效售价。 */
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_replenishment_listing_price_latest;
CREATE TEMPORARY TABLE dws_datasync.tmp_replenishment_listing_price_latest
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
AS
WITH listing_source AS (
    SELECT
        CAST(
            CASE
                WHEN l.marketplace = '英国' THEN '英国站'
                WHEN l.marketplace IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                ELSE '欧洲站'
            END AS CHAR(16)
        ) AS country_category,
        CAST(l.marketplace AS CHAR(32)) AS country,
        CAST(
            CASE
                WHEN LOCATE('-', l.seller_name) > 0
                    THEN LEFT(l.seller_name, LOCATE('-', l.seller_name) - 1)
                ELSE l.seller_name
            END AS CHAR(64)
        ) AS seller_name_new,
        CAST(l.seller_sku AS CHAR(100)) AS seller_sku_adj,
        CAST(NULLIF(l.landed_price, '') AS DECIMAL(18,4)) AS listing_price,
        CAST(NULLIF(UPPER(TRIM(l.currency_code)), '') AS CHAR(10)) AS currency_code,
        l.create_time,
        CAST(
            CASE NULLIF(UPPER(TRIM(l.currency_code)), '')
                WHEN 'EUR' THEN '欧元'
                WHEN 'PLN' THEN '波兰兹罗提'
                WHEN 'SEK' THEN '瑞典'
                WHEN 'TRY' THEN '土耳其里拉'
                WHEN 'GBP' THEN '英镑'
                WHEN 'USD' THEN '美元'
                WHEN 'CAD' THEN '加元'
                WHEN 'MXN' THEN '墨西哥比索'
                WHEN 'BRL' THEN '巴西雷亚尔'
                ELSE NULL
            END AS CHAR(32)
        ) AS currency_name
    FROM dwd_datasync.lx_sales_mws_listing AS l
    WHERE l.create_time >= @listing_date
      AND l.create_time < @listing_end_date
      AND NULLIF(TRIM(l.landed_price), '') IS NOT NULL
      AND CAST(l.landed_price AS DECIMAL(18,4)) > 0
      AND l.seller_sku IS NOT NULL
      AND l.seller_sku <> ''
),
listing_ranked AS (
    SELECT
        l.*,
        ROW_NUMBER() OVER (
            PARTITION BY
                l.country_category,
                l.country,
                l.seller_name_new,
                l.seller_sku_adj
            ORDER BY l.create_time DESC, l.listing_price DESC
        ) AS price_rank
    FROM listing_source AS l
)
SELECT
    l.country_category,
    l.country,
    l.seller_name_new,
    l.seller_sku_adj,
    l.listing_price,
    l.currency_code,
    l.create_time AS listing_create_time,
    CAST(NULLIF(c.rate_org, '') AS DECIMAL(18,8)) AS exchange_rate_cny,
    ROUND(
        l.listing_price * CAST(NULLIF(c.rate_org, '') AS DECIMAL(18,8)),
        2
    ) AS listing_price_cny
FROM listing_ranked AS l
LEFT JOIN dwd_datasync.lx_basic_currency AS c
       ON l.currency_name = c.name
      AND DATE_FORMAT(l.create_time, '%Y-%m') = c.date
WHERE l.price_rank = 1;

ALTER TABLE dws_datasync.tmp_replenishment_listing_price_latest
    ADD PRIMARY KEY (
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
    );

/* 第三层：直接读取两张会话临时表并返回最终结果。 */
WITH
period_metrics AS (
    SELECT
        p.country_category,
        p.country,
        p.seller_name_new,
        p.seller_sku_adj,
        p.sales_3,
        p.sales_7,
        p.sales_14,
        p.sales_30,
        p.r_3d_salable_days,
        p.r_7d_salable_days,
        p.r_14d_salable_days,
        p.r_30d_salable_days
    FROM dws_datasync.tmp_replenishment_weighted_sales_product_30d AS p
),
product_brand AS (
    SELECT
        country_category,
        seller_name_new,
        seller_sku,
        MAX(brand_name) AS max_brand_name
    FROM etl_datasync.etl_dispose_lx_product_local_product_info
    GROUP BY country_category, seller_name_new, seller_sku
),
shipment_receiving_count AS (
    SELECT
        msku,
        store_name,
        COUNT(*) AS receiving_cnt
    FROM etl_datasync.etl_dispose_lx_fba_shipment
    WHERE receiving_time IS NOT NULL
      AND receiving_time <> ''
      AND quantity_shipped <> 0
    GROUP BY msku, store_name
),
receiving_metrics AS (
    SELECT
        f.country_category,
        f.seller_name_new,
        f.msku,
        MAX(rc.receiving_cnt) AS receiving_cnt
    FROM etl_datasync.etl_dispose_lx_fba_shipment AS f
    LEFT JOIN shipment_receiving_count AS rc
           ON f.msku = rc.msku
          AND f.store_name = rc.store_name
    WHERE f.receiving_time IS NOT NULL
      AND f.receiving_time <> ''
      AND f.quantity_received <> 0
    GROUP BY f.country_category, f.seller_name_new, f.msku
),
metric_base AS (
    SELECT
        m.*,
        b.max_brand_name,
        r.receiving_cnt,
        CASE
            WHEN (
                b.max_brand_name LIKE '%2025%'
                OR b.max_brand_name LIKE '%2026%'
            )
            AND (r.receiving_cnt <= 1 OR r.receiving_cnt IS NULL)
                THEN 1
            ELSE 0
        END AS is_new_product
    FROM period_metrics AS m
    LEFT JOIN product_brand AS b
           ON m.country_category = b.country_category
          AND m.seller_name_new = b.seller_name_new
          AND m.seller_sku_adj = b.seller_sku
    LEFT JOIN receiving_metrics AS r
           ON m.country_category = r.country_category
          AND m.seller_name_new = r.seller_name_new
          AND m.seller_sku_adj = r.msku
),
adjusted_daily_sales AS (
    SELECT
        m.*,
        CASE
            WHEN m.r_30d_salable_days >= 7 THEN
                CASE WHEN m.r_3d_salable_days > 0
                     THEN m.sales_3 / m.r_3d_salable_days ELSE 0 END
            ELSE m.sales_3 / GREATEST(m.r_3d_salable_days, 2)
        END AS daily_sales_3d,
        CASE
            WHEN m.r_30d_salable_days >= 7 THEN
                CASE
                    WHEN m.r_7d_salable_days >= 7
                        THEN m.sales_7 / m.r_7d_salable_days
                    ELSE LEAST(
                        CASE WHEN m.r_7d_salable_days > 0
                             THEN m.sales_7 / m.r_7d_salable_days ELSE 0 END,
                        (CASE WHEN m.r_7d_salable_days > 0
                              THEN m.sales_7 / m.r_7d_salable_days ELSE 0 END)
                            * (m.r_7d_salable_days / (m.r_7d_salable_days + 3))
                        + (m.sales_30 / m.r_30d_salable_days)
                            * (1 - m.r_7d_salable_days / (m.r_7d_salable_days + 3))
                    )
                END
            ELSE m.sales_7 / GREATEST(m.r_7d_salable_days, 3)
        END AS daily_sales_7d,
        CASE
            WHEN m.r_30d_salable_days >= 7 THEN
                CASE
                    WHEN m.r_14d_salable_days >= 14
                        THEN m.sales_14 / m.r_14d_salable_days
                    ELSE LEAST(
                        CASE WHEN m.r_14d_salable_days > 0
                             THEN m.sales_14 / m.r_14d_salable_days ELSE 0 END,
                        (CASE WHEN m.r_14d_salable_days > 0
                              THEN m.sales_14 / m.r_14d_salable_days ELSE 0 END)
                            * (m.r_14d_salable_days / (m.r_14d_salable_days + 7))
                        + (m.sales_30 / m.r_30d_salable_days)
                            * (1 - m.r_14d_salable_days / (m.r_14d_salable_days + 7))
                    )
                END
            ELSE m.sales_14 / GREATEST(m.r_14d_salable_days, 7)
        END AS daily_sales_14d,
        CASE
            WHEN m.r_30d_salable_days >= 7
                THEN m.sales_30 / m.r_30d_salable_days
            ELSE m.sales_30 / GREATEST(m.r_30d_salable_days, 15)
        END AS daily_sales_30d
    FROM metric_base AS m
),
weighted_metrics AS (
    SELECT
        a.*,
        CASE
            WHEN a.is_new_product = 1 THEN
                a.daily_sales_3d * 0.5
                + a.daily_sales_7d * 0.5
            ELSE
                a.daily_sales_7d * 0.6
                + a.daily_sales_14d * 0.2
                + a.daily_sales_30d * 0.2
        END AS daily_avg_sales
    FROM adjusted_daily_sales AS a
)
SELECT
    CAST(@biz_date AS DATE) AS biz_date,
    w.country_category,
    w.country,
    w.seller_name_new,
    w.seller_sku_adj,
    w.max_brand_name,
    w.receiving_cnt,
    CASE WHEN w.is_new_product = 1 THEN '新品' ELSE '老品' END AS product_type,
    w.sales_3,
    w.r_3d_salable_days,
    ROUND(w.daily_sales_3d, 6) AS daily_sales_3d,
    w.sales_7,
    w.r_7d_salable_days,
    ROUND(w.daily_sales_7d, 6) AS daily_sales_7d,
    w.sales_14,
    w.r_14d_salable_days,
    ROUND(w.daily_sales_14d, 6) AS daily_sales_14d,
    w.sales_30,
    w.r_30d_salable_days,
    ROUND(w.daily_sales_30d, 6) AS daily_sales_30d,
    ROUND(w.daily_avg_sales, 6) AS daily_avg_sales,
    ROUND(lp.listing_price, 4) AS listing_price,
    lp.currency_code,
    ROUND(lp.exchange_rate_cny, 4) AS exchange_rate_cny,
    ROUND(lp.listing_price_cny, 2) AS listing_price_cny,
    ROUND(lp.listing_price * 0.05 * w.daily_avg_sales * 30, 2) AS ad_budget_original,
    ROUND(
        lp.listing_price * lp.exchange_rate_cny
        * 0.05 * w.daily_avg_sales * 30,
        2
    ) AS ad_budget_cny
FROM weighted_metrics AS w
LEFT JOIN dws_datasync.tmp_replenishment_listing_price_latest AS lp
       ON w.country_category = lp.country_category
      AND w.country = lp.country
      AND w.seller_name_new = lp.seller_name_new
      AND BINARY w.seller_sku_adj = lp.seller_sku_adj
ORDER BY
    w.country_category,
    w.country,
    w.seller_name_new,
    w.seller_sku_adj;
