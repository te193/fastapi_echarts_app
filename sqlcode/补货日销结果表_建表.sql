/*
用途：保存独立复算后的 MSKU 日销结果。

唯一粒度：数据日期 + 站点 + 店铺 + MSKU。
说明：本文件仅提供建表语句，请在确认目标库和权限后单独执行。
*/

CREATE TABLE IF NOT EXISTS dws_datasync.dws_msku_daily_sales (
    data_date DATE NOT NULL COMMENT '业务数据日期',
    country_category VARCHAR(64) NOT NULL COMMENT '站点',
    seller_name_new VARCHAR(128) NOT NULL COMMENT '店铺名',
    seller_sku_adj VARCHAR(255) NOT NULL COMMENT 'MSKU',
    asin VARCHAR(32) NULL COMMENT 'ASIN',
    fnsku VARCHAR(64) NULL COMMENT 'FNSKU',
    sku VARCHAR(128) NULL COMMENT '本地 SKU',
    follow_type VARCHAR(16) NOT NULL COMMENT '链接类型：自产/跟卖',
    follow_origin_link VARCHAR(255) NULL COMMENT '跟卖继承的原始店铺/MSKU',
    product_stage VARCHAR(16) NOT NULL COMMENT '新品/老品',
    brand_name VARCHAR(255) NULL COMMENT '品牌名称',
    receiving_count INT NULL COMMENT '历史收货次数',

    own_sales_3d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '自身近3天销量',
    own_sales_7d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '自身近7天销量',
    own_sales_14d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '自身近14天销量',
    own_sales_30d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '自身近30天销量',
    inherited_sales_3d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '继承近3天销量',
    inherited_sales_7d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '继承近7天销量',
    inherited_sales_14d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '继承近14天销量',
    inherited_sales_30d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '继承近30天销量',
    final_sales_3d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '合并后近3天销量',
    final_sales_7d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '合并后近7天销量',
    final_sales_14d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '合并后近14天销量',
    final_sales_30d DECIMAL(18, 4) NOT NULL DEFAULT 0 COMMENT '合并后近30天销量',

    salable_days_3d INT NOT NULL DEFAULT 0 COMMENT '近3天历史有货天数',
    salable_days_7d INT NOT NULL DEFAULT 0 COMMENT '近7天历史有货天数',
    salable_days_14d INT NOT NULL DEFAULT 0 COMMENT '近14天历史有货天数',
    salable_days_30d INT NOT NULL DEFAULT 0 COMMENT '近30天历史有货天数',
    adjusted_daily_sales_3d DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '近3天修正日销',
    adjusted_daily_sales_7d DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '近7天修正日销',
    adjusted_daily_sales_14d DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '近14天修正日销',
    adjusted_daily_sales_30d DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '近30天修正日销',
    final_daily_sales DECIMAL(18, 6) NOT NULL DEFAULT 0 COMMENT '补货最终日销',
    daily_sales_formula VARCHAR(128) NOT NULL COMMENT '最终日销公式说明',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    PRIMARY KEY (data_date, country_category, seller_name_new, seller_sku_adj),
    KEY idx_daily_sales_msku (seller_sku_adj),
    KEY idx_daily_sales_origin (follow_origin_link)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'MSKU 日销计算结果';
