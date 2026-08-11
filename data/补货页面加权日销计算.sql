/*
用途：只使用远端过程表计算补货口径的基础加权日销。

远端过程表：
1. dwd_datasync.lx_statistics_product_performance
   - 3/7/14/30 天销量
   - 每日 FBA 可售库存，用于统计可售天数
2. etl_datasync.etl_dispose_lx_product_local_product_info
   - 品牌年份，用于区分新品/老品权重
3. etl_datasync.etl_dispose_lx_fba_shipment
   - 接收次数 receiving_cnt

按用户要求，本 SQL 不计算跟卖补偿、补货数量、库存支撑天数等其他指标。

参数：
- biz_date：默认取产品表现过程表最新日期，也可以改为固定日期。
- target_msku：空字符串查询全部；填写 MSKU 可缩小查询范围。
*/
WITH
params AS (
    SELECT
        (
            SELECT MAX(DATE(start_date))
            FROM dwd_datasync.lx_statistics_product_performance
        ) AS biz_date,
        CAST('' AS CHAR(100)) AS target_msku
),

/* 将远端产品表现数据转换为补货页面使用的站点、店铺和 MSKU 口径。 */
product_source AS (
    SELECT
        DATE(p.start_date) AS dt_date,
        p.country AS country,
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
            TRIM(
                LEADING 'amzn.gr.' FROM
                SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1)
            ),
            SUBSTRING_INDEX(p.seller_sku, ',', 1)
        ) AS seller_sku_adj,
        COALESCE(p.volume, 0) AS sales_qty,
        COALESCE(p.afn_fulfillable_quantity, 0) AS afn_fulfillable_quantity
    FROM dwd_datasync.lx_statistics_product_performance AS p
    CROSS JOIN params AS prm
    WHERE p.start_date >= DATE_FORMAT(DATE_SUB(prm.biz_date, INTERVAL 29 DAY), '%Y-%m-%d')
      AND p.start_date < DATE_FORMAT(prm.biz_date + INTERVAL 1 DAY, '%Y-%m-%d')
      AND p.seller_sku NOT LIKE 'Amazon.Found%'
      AND p.seller_sku IS NOT NULL
      AND p.seller_sku <> ''
      AND (
          prm.target_msku = ''
          OR IF(
              LENGTH(SUBSTRING_INDEX(p.seller_sku, ',', 1)) > 16,
              TRIM(
                  LEADING 'amzn.gr.' FROM
                  SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1)
              ),
              SUBSTRING_INDEX(p.seller_sku, ',', 1)
          ) = prm.target_msku
      )
),

/* 先按天汇总，同一天只计算一个可售日。 */
product_daily AS (
    SELECT
        dt_date,
        country_category,
        country,
        seller_name_new,
        seller_sku_adj,
        SUM(sales_qty) AS sales_qty,
        MAX(afn_fulfillable_quantity) AS afn_fulfillable_quantity
    FROM product_source
    GROUP BY
        dt_date,
        country_category,
        country,
        seller_name_new,
        seller_sku_adj
),

/* 统计各周期销量和有 FBA 可售库存的天数。 */
period_metrics AS (
    SELECT
        p.country_category,
        p.country,
        p.seller_name_new,
        p.seller_sku_adj,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 2 DAY)
                 THEN p.sales_qty ELSE 0 END) AS sales_3,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 6 DAY)
                 THEN p.sales_qty ELSE 0 END) AS sales_7,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 13 DAY)
                 THEN p.sales_qty ELSE 0 END) AS sales_14,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 29 DAY)
                 THEN p.sales_qty ELSE 0 END) AS sales_30,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 2 DAY)
                  AND p.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
            AS r_3d_salable_days,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 6 DAY)
                  AND p.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
            AS r_7d_salable_days,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 13 DAY)
                  AND p.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
            AS r_14d_salable_days,
        SUM(CASE WHEN p.dt_date >= DATE_SUB(prm.biz_date, INTERVAL 29 DAY)
                  AND p.afn_fulfillable_quantity > 0 THEN 1 ELSE 0 END)
            AS r_30d_salable_days
    FROM product_daily AS p
    CROSS JOIN params AS prm
    GROUP BY
        p.country_category,
        p.country,
        p.seller_name_new,
        p.seller_sku_adj
),

/* 品牌年份。 */
product_brand AS (
    SELECT
        country_category,
        seller_name_new,
        seller_sku,
        MAX(brand_name) AS max_brand_name
    FROM etl_datasync.etl_dispose_lx_product_local_product_info
    GROUP BY country_category, seller_name_new, seller_sku
),

/* 与现有 ETL 一致：按 MSKU + 原店铺统计有效发货记录数。 */
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

/* 周期日销：销量 / 可售天数；可售天数不足时按现有规则平滑。 */
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
)
SELECT
    prm.biz_date,
    a.country_category,
    a.country,
    a.seller_name_new,
    a.seller_sku_adj,
    a.max_brand_name,
    a.receiving_cnt,
    CASE WHEN a.is_new_product = 1 THEN '新品' ELSE '老品' END AS product_type,
    a.sales_3,
    a.r_3d_salable_days,
    ROUND(a.daily_sales_3d, 6) AS daily_sales_3d,
    a.sales_7,
    a.r_7d_salable_days,
    ROUND(a.daily_sales_7d, 6) AS daily_sales_7d,
    a.sales_14,
    a.r_14d_salable_days,
    ROUND(a.daily_sales_14d, 6) AS daily_sales_14d,
    a.sales_30,
    a.r_30d_salable_days,
    ROUND(a.daily_sales_30d, 6) AS daily_sales_30d,
    ROUND(
        CASE
            WHEN a.is_new_product = 1 THEN
                a.daily_sales_3d * 0.5
                + a.daily_sales_7d * 0.5
            ELSE
                a.daily_sales_7d * 0.6
                + a.daily_sales_14d * 0.2
                + a.daily_sales_30d * 0.2
        END,
        6
    ) AS daily_avg_sales
FROM adjusted_daily_sales AS a
CROSS JOIN params AS prm
ORDER BY
    a.country_category,
    a.country,
    a.seller_name_new,
    a.seller_sku_adj;
