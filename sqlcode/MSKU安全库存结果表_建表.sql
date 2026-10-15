/*
  MSKU 安全库存结果表
  数据粒度：数据日期 + 站点 + 店铺 + MSKU
*/

CREATE TABLE IF NOT EXISTS dws_datasync.dws_msku_safety_stock (
    data_date DATE NOT NULL COMMENT '日销数据日期',
    inventory_date DATE NOT NULL COMMENT '库存数据日期',
    role_date DATE NULL COMMENT '销售角色数据日期',

    country_category VARCHAR(64) NOT NULL COMMENT '站点',
    seller_name_new VARCHAR(128) NOT NULL COMMENT '店铺',
    seller_sku_adj VARCHAR(255) NOT NULL COMMENT 'MSKU',
    asin VARCHAR(32) NULL COMMENT 'ASIN',
    fnsku VARCHAR(64) NULL COMMENT 'FNSKU',
    sku VARCHAR(128) NULL COMMENT '本地SKU',

    product_stage VARCHAR(16) NOT NULL COMMENT '新品/老品',
    brand_name VARCHAR(255) NULL COMMENT '品牌',
    sales_role_label_id INT NULL COMMENT '全站点30天销售角色标签ID',
    sales_role VARCHAR(32) NULL COMMENT '全站点30天销售角色',

    final_sales_30d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '最终30天销量',
    salable_days_30d INT NOT NULL DEFAULT 0 COMMENT '近30天历史有货天数',
    adjusted_daily_sales_30d DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '30天修正日销',
    final_daily_sales DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '最终日销',
    daily_sales_formula VARCHAR(128) NOT NULL COMMENT '最终日销计算方式',

    available_total DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT 'FBA可用库存',
    stock_up_num DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT 'FBA实际在途',
    local_valid_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '本地可用',
    purchase_shipping_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '采购在途',
    purchase_plan_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '采购计划',
    local_qc_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '待检待上架',
    support_inventory_qty DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '补货支撑库存总量',
    afn_fulfillable_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT 'FBA可售库存',

    inventory_support_days DECIMAL(18, 6) NULL COMMENT '补货支撑库存可支撑天数',
    fba_fulfillable_support_days DECIMAL(18, 6) NULL COMMENT 'FBA可售库存可支撑天数',
    safety_stock_label_id INT NOT NULL COMMENT '安全库存标签ID：2201安全、2202库存预警、2203数据不足、2204不适用',
    safety_stock_status VARCHAR(16) NOT NULL COMMENT '安全库存状态',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    PRIMARY KEY (data_date, country_category, seller_name_new, seller_sku_adj),
    KEY idx_safety_stock_label (data_date, safety_stock_label_id),
    KEY idx_safety_stock_role (data_date, sales_role_label_id),
    KEY idx_safety_stock_lookup (
        country_category,
        seller_name_new,
        seller_sku_adj,
        data_date
    )
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'MSKU安全库存及库存可支撑天数结果表';
