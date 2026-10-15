
drop procedure if exists dws_datasync.sp_dws_msku_safety_stock;
delimiter $$
create procedure dws_datasync.sp_dws_msku_safety_stock()
begin

SET @sales_date := (
    SELECT MAX(data_date)
    FROM dws_datasync.dws_msku_daily_sales
);

/* 两个库存来源取共同可用的最新日期，避免混用不同日期的库存。 */
SET @inventory_date := (
    SELECT LEAST(
        (
            SELECT DATE(MAX(create_time))
            FROM etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
        ),
        (
            SELECT MAX(create_time)
            FROM etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
        )
    )
);

SET @role_date := (
    SELECT MAX(data_date)
    FROM dws_datasync.`dws_标签表`
    WHERE data_date <= @sales_date
      AND label_period = '30d'
      AND country IS NULL
      AND label_id IN (101, 102, 103, 104)
);

DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_safety_stock_daily_sales;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_safety_stock_fba_inventory;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_safety_stock_restock_inventory;
DROP TEMPORARY TABLE IF EXISTS dws_datasync.tmp_safety_stock_sales_role;

/* 主表：最新日销结果。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_safety_stock_daily_sales
ENGINE = InnoDB
AS
SELECT
    data_date,
    CAST(country_category AS CHAR(16)) AS country_category,
    CAST(seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(seller_sku_adj AS CHAR(255)) AS seller_sku_adj,
    asin,
    fnsku,
    sku,
    product_stage,
    brand_name,
    final_sales_30d,
    salable_days_30d,
    adjusted_daily_sales_30d,
    final_daily_sales,
    daily_sales_formula
FROM dws_datasync.dws_msku_daily_sales
WHERE data_date = @sales_date;

ALTER TABLE dws_datasync.tmp_safety_stock_daily_sales
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/* FBA库存：复用补货页面汇总口径。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_safety_stock_fba_inventory
ENGINE = InnoDB
AS
SELECT
    CAST(fba.country_category AS CHAR(16)) AS country_category,
    CAST(fba.seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(fba.seller_sku_adj AS CHAR(255)) AS seller_sku_adj,
    SUM(COALESCE(fba.available_total, 0)) AS available_total,
    SUM(COALESCE(fba.stock_up_num, 0)) AS stock_up_num,
    SUM(COALESCE(fba.afn_fulfillable_quantity, 0)) AS afn_fulfillable_quantity
FROM etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail AS fba FORCE INDEX (id1)
INNER JOIN dws_datasync.tmp_safety_stock_daily_sales AS daily
    ON fba.seller_sku_adj = daily.seller_sku_adj
   AND fba.seller_name_new = daily.seller_name_new
   AND fba.country_category = daily.country_category
WHERE fba.create_time >= @inventory_date
  AND fba.create_time < DATE_ADD(@inventory_date, INTERVAL 1 DAY)
  AND NULLIF(fba.country_category, '') IS NOT NULL
  AND NULLIF(fba.seller_name_new, '') IS NOT NULL
  AND NULLIF(fba.seller_sku_adj, '') IS NOT NULL
GROUP BY
    fba.country_category,
    fba.seller_name_new,
    fba.seller_sku_adj;

ALTER TABLE dws_datasync.tmp_safety_stock_fba_inventory
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/* 本地仓、采购和待检状态：同一键按补货页面逻辑取各状态最大值。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_safety_stock_restock_inventory
ENGINE = InnoDB
AS
SELECT
    CAST(country_category AS CHAR(16)) AS country_category,
    CAST(seller_name_new AS CHAR(128)) AS seller_name_new,
    CAST(seller_sku_adj AS CHAR(255)) AS seller_sku_adj,
    MAX(COALESCE(sc_quantity_local_valid, 0)) AS local_valid_quantity,
    MAX(COALESCE(sc_quantity_purchase_shipping, 0)) AS purchase_shipping_quantity,
    MAX(COALESCE(sc_quantity_purchase_plan, 0)) AS purchase_plan_quantity,
    MAX(COALESCE(sc_quantity_local_qc, 0)) AS local_qc_quantity
FROM etl_datasync.etl_dispose_lx_replenishment_suggest_restocking
WHERE create_time = @inventory_date
  AND NULLIF(country_category, '') IS NOT NULL
  AND NULLIF(seller_name_new, '') IS NOT NULL
  AND NULLIF(seller_sku_adj, '') IS NOT NULL
GROUP BY
    country_category,
    seller_name_new,
    seller_sku_adj;

ALTER TABLE dws_datasync.tmp_safety_stock_restock_inventory
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/* 全站点、30天销售角色。 */
CREATE TEMPORARY TABLE dws_datasync.tmp_safety_stock_sales_role
ENGINE = InnoDB
AS
SELECT
    CAST(country_category AS CHAR(16)) AS country_category,
    CAST(store AS CHAR(128)) AS seller_name_new,
    CAST(msku AS CHAR(255)) AS seller_sku_adj,
    MIN(label_id) AS sales_role_label_id
FROM dws_datasync.`dws_标签表`
WHERE data_date = @role_date
  AND label_period = '30d'
  AND country IS NULL
  AND label_id IN (101, 102, 103, 104)
  AND NULLIF(country_category, '') IS NOT NULL
  AND NULLIF(store, '') IS NOT NULL
  AND NULLIF(msku, '') IS NOT NULL
GROUP BY
    country_category,
    store,
    msku;

ALTER TABLE dws_datasync.tmp_safety_stock_sales_role
    ADD PRIMARY KEY (country_category, seller_name_new, seller_sku_adj);

/*
  最终结果：
  - inventory_support_days 只作库存支撑分析；
  - safety_stock_status 只按 fba_fulfillable_support_days 判断。
*/

insert into dws_datasync.dws_msku_safety_stock
SELECT
    result.data_date,
    result.inventory_date,
    result.role_date,
    result.country_category,
    result.seller_name_new,
    result.seller_sku_adj,
    result.asin,
    result.fnsku,
    result.sku,
    result.product_stage,
    result.brand_name,
    result.sales_role_label_id,
    result.sales_role,
    result.final_sales_30d,
    result.salable_days_30d,
    result.adjusted_daily_sales_30d,
    result.final_daily_sales,
    result.daily_sales_formula,
    result.available_total,
    result.stock_up_num,
    result.local_valid_quantity,
    result.purchase_shipping_quantity,
    result.purchase_plan_quantity,
    result.local_qc_quantity,
    result.support_inventory_qty,
    result.afn_fulfillable_quantity,
    result.inventory_support_days,
    result.fba_fulfillable_support_days,
    CASE
        WHEN sales_role_label_id IS NULL
          OR sales_role_label_id NOT IN (101, 102) THEN 2204
        WHEN fba_fulfillable_support_days IS NULL THEN 2203
        WHEN fba_fulfillable_support_days > 35 THEN 2201
        ELSE 2202
    END AS safety_stock_label_id,
    CASE
        WHEN sales_role_label_id IS NULL
          OR sales_role_label_id NOT IN (101, 102) THEN '不适用'
        WHEN fba_fulfillable_support_days IS NULL THEN '数据不足'
        WHEN fba_fulfillable_support_days > 35 THEN '安全'
        ELSE '库存预警'
    END AS safety_stock_status,
    CURRENT_TIMESTAMP AS created_at,
    CURRENT_TIMESTAMP AS updated_at
FROM (
    SELECT
        base.*,
        support_inventory_qty
            / NULLIF(final_daily_sales, 0) AS inventory_support_days,
        afn_fulfillable_quantity
            / NULLIF(final_daily_sales, 0) AS fba_fulfillable_support_days
    FROM (
        SELECT
            daily.data_date,
            @inventory_date AS inventory_date,
            @role_date AS role_date,
            daily.country_category,
            daily.seller_name_new,
            daily.seller_sku_adj,
            daily.asin,
            daily.fnsku,
            daily.sku,
            daily.product_stage,
            daily.brand_name,
            role.sales_role_label_id,
            CASE role.sales_role_label_id
                WHEN 101 THEN '明星产品'
                WHEN 102 THEN '潜力产品'
                WHEN 103 THEN '瘦狗产品'
                WHEN 104 THEN '问题产品'
                ELSE NULL
            END AS sales_role,
            daily.final_sales_30d,
            daily.salable_days_30d,
            daily.adjusted_daily_sales_30d,
            daily.final_daily_sales,
            daily.daily_sales_formula,
            COALESCE(fba.available_total, 0) AS available_total,
            COALESCE(fba.stock_up_num, 0) AS stock_up_num,
            COALESCE(restock.local_valid_quantity, 0) AS local_valid_quantity,
            COALESCE(restock.purchase_shipping_quantity, 0) AS purchase_shipping_quantity,
            COALESCE(restock.purchase_plan_quantity, 0) AS purchase_plan_quantity,
            COALESCE(restock.local_qc_quantity, 0) AS local_qc_quantity,
            COALESCE(fba.available_total, 0)
                + COALESCE(fba.stock_up_num, 0)
                + COALESCE(restock.local_valid_quantity, 0)
                + COALESCE(restock.purchase_shipping_quantity, 0)
                + COALESCE(restock.purchase_plan_quantity, 0)
                + COALESCE(restock.local_qc_quantity, 0) AS support_inventory_qty,
            COALESCE(fba.afn_fulfillable_quantity, 0) AS afn_fulfillable_quantity
        FROM dws_datasync.tmp_safety_stock_daily_sales AS daily
        LEFT JOIN dws_datasync.tmp_safety_stock_fba_inventory AS fba
            ON fba.country_category = daily.country_category
           AND fba.seller_name_new = daily.seller_name_new
           AND fba.seller_sku_adj = daily.seller_sku_adj
        LEFT JOIN dws_datasync.tmp_safety_stock_restock_inventory AS restock
            ON restock.country_category = daily.country_category
           AND restock.seller_name_new = daily.seller_name_new
           AND restock.seller_sku_adj = daily.seller_sku_adj
        LEFT JOIN dws_datasync.tmp_safety_stock_sales_role AS role
            ON role.country_category = daily.country_category
           AND role.seller_name_new = daily.seller_name_new
           AND role.seller_sku_adj = daily.seller_sku_adj
    ) AS base
) AS result
ORDER BY
    result.country_category,
    result.seller_name_new,
    result.seller_sku_adj;
end$$
delimiter ;
