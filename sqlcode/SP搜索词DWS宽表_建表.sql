/*
用途：创建 SP 搜索词分析每日快照宽表。
数据库：MySQL 8.0
目标表：dws_datasync.dws_sp_search_term_analysis_daily

说明：
1. 本文件只负责建表，不刷新数据。
2. 一行 = 快照日 + profile + 活动 + 广告组 + target + 原始搜索词 + 匹配方式。
3. 每次只写一个 snapshot_date 的当天快照；累计不足 7 个快照日期时不删除历史。
4. 每个快照独立保存，不把前几日结果累计进当天快照。
5. 写入第 8 个快照日期后，仅保留日期最新的 7 份快照。
*/

CREATE TABLE IF NOT EXISTS dws_datasync.dws_sp_search_term_analysis_daily (
    snapshot_date DATE NOT NULL COMMENT '快照日期',
    row_key CHAR(64) NOT NULL COMMENT '搜索词业务键SHA256，不含快照日期',
    rule_version VARCHAR(50) NOT NULL COMMENT '建议规则版本',
    mature_start DATE NOT NULL COMMENT '建议成熟窗口开始日期',
    mature_end DATE NOT NULL COMMENT '建议成熟窗口结束日期',
    source_search_term_days TINYINT UNSIGNED NOT NULL COMMENT '搜索词源表覆盖天数',
    source_product_ad_days TINYINT UNSIGNED NOT NULL COMMENT '商品广告源表覆盖天数',

    profile_id BIGINT NOT NULL COMMENT '广告账号Profile ID',
    sid BIGINT NULL COMMENT '领星店铺SID',
    seller_name VARCHAR(255) NULL COMMENT '店铺名称',
    country_code VARCHAR(20) NULL COMMENT '站点代码',
    currency_code VARCHAR(20) NULL COMMENT '币种代码',

    campaign_id BIGINT NOT NULL COMMENT '广告活动ID',
    campaign_name_current VARCHAR(255) NULL COMMENT '当前广告活动名称',
    campaign_state_current VARCHAR(50) NULL COMMENT '当前广告活动状态',
    targeting_type VARCHAR(50) NULL COMMENT '广告活动投放类型原值',
    targeting_type_name VARCHAR(20) NOT NULL COMMENT '自动广告/手工广告/未知',
    is_auto_campaign TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自动广告',
    is_manual_campaign TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否手工广告',
    daily_budget_current DECIMAL(20,4) NULL COMMENT '当前活动日预算（站点币种）',
    bidding_strategy_current VARCHAR(100) NULL COMMENT '当前竞价策略',

    ad_group_id BIGINT NOT NULL COMMENT '广告组ID',
    ad_group_name_current VARCHAR(255) NULL COMMENT '当前广告组名称',
    ad_group_state_current VARCHAR(50) NULL COMMENT '当前广告组状态',
    default_bid_current DECIMAL(20,4) NULL COMMENT '当前广告组默认竞价（站点币种）',

    target_id BIGINT NULL COMMENT '原投放对象ID',
    target_text VARCHAR(500) NULL COMMENT '原投放对象文本',
    target_state_current VARCHAR(50) NULL COMMENT '原投放对象当前状态',
    match_type VARCHAR(100) NOT NULL DEFAULT '' COMMENT '搜索词报告匹配方式',
    search_term VARCHAR(500) NOT NULL COMMENT '客户搜索词原文',
    search_term_normalized VARCHAR(500) NOT NULL COMMENT '用于判重匹配的标准化搜索词',
    search_term_type VARCHAR(30) NOT NULL COMMENT 'keyword/product_target',
    existing_object_state VARCHAR(30) NULL COMMENT '同组精确关键词或ASIN投放状态：enabled/inactive',

    msku VARCHAR(255) NULL COMMENT '安全归属后的MSKU',
    asin VARCHAR(50) NULL COMMENT '安全归属后的ASIN',
    msku_mapping_status VARCHAR(50) NOT NULL COMMENT 'MSKU归属状态',
    associated_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '周期与当前MSKU数量最大值',
    period_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '成熟窗口内MSKU数',
    current_enabled_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前启用MSKU数',
    period_msku_candidates TEXT NULL COMMENT '成熟窗口MSKU候选列表',
    current_msku_candidates TEXT NULL COMMENT '当前启用MSKU候选列表',

    product_brand VARCHAR(255) NULL COMMENT 'Listing商品品牌',
    store_brands_json JSON NULL COMMENT '店铺品牌候选',
    leaf_categories_json JSON NULL COMMENT '商品核心类目候选',
    product_launch_date DATE NULL COMMENT '首单/开售日期',
    product_launch_date_source VARCHAR(50) NULL COMMENT '首单/开售日期来源字段',
    product_age_days INT NULL COMMENT '快照日商品年龄',
    term_protection_complete TINYINT(1) NOT NULL DEFAULT 0 COMMENT '否词保护信息是否完整',
    protection_missing_codes JSON NOT NULL COMMENT '保护信息缺失原因',
    is_brand_term TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否品牌词',
    is_core_category_term TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否核心类目词',
    is_new_product_term TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否90天内新品',
    protection_brand VARCHAR(255) NULL COMMENT '命中的保护品牌',
    protection_category VARCHAR(255) NULL COMMENT '命中的保护类目',

    impressions BIGINT NOT NULL DEFAULT 0 COMMENT '曝光量',
    clicks BIGINT NOT NULL DEFAULT 0 COMMENT '点击量',
    cost DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '花费（站点币种）',

    orders_1d BIGINT NOT NULL DEFAULT 0 COMMENT '1d归因订单',
    orders_7d BIGINT NOT NULL DEFAULT 0 COMMENT '7d归因订单',
    orders_14d BIGINT NOT NULL DEFAULT 0 COMMENT '14d归因订单',
    orders_30d BIGINT NOT NULL DEFAULT 0 COMMENT '30d归因订单',
    same_orders_1d BIGINT NOT NULL DEFAULT 0 COMMENT '1d归因直接成交订单',
    same_orders_7d BIGINT NOT NULL DEFAULT 0 COMMENT '7d归因直接成交订单',
    same_orders_14d BIGINT NOT NULL DEFAULT 0 COMMENT '14d归因直接成交订单',
    same_orders_30d BIGINT NOT NULL DEFAULT 0 COMMENT '30d归因直接成交订单',

    sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '1d归因销售额（站点币种）',
    sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '7d归因销售额（站点币种）',
    sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '14d归因销售额（站点币种）',
    sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '30d归因销售额（站点币种）',
    same_sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '1d归因直接成交销售额',
    same_sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '7d归因直接成交销售额',
    same_sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '14d归因直接成交销售额',
    same_sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '30d归因直接成交销售额',

    units_1d BIGINT NOT NULL DEFAULT 0 COMMENT '1d归因销量',
    units_7d BIGINT NOT NULL DEFAULT 0 COMMENT '7d归因销量',
    units_14d BIGINT NOT NULL DEFAULT 0 COMMENT '14d归因销量',
    units_30d BIGINT NOT NULL DEFAULT 0 COMMENT '30d归因销量',
    same_units_1d BIGINT NOT NULL DEFAULT 0 COMMENT '1d归因直接成交销量',
    same_units_7d BIGINT NOT NULL DEFAULT 0 COMMENT '7d归因直接成交销量',
    same_units_14d BIGINT NOT NULL DEFAULT 0 COMMENT '14d归因直接成交销量',
    same_units_30d BIGINT NOT NULL DEFAULT 0 COMMENT '30d归因直接成交销量',

    ctr DECIMAL(20,8) NULL COMMENT '点击率',
    cpc DECIMAL(20,8) NULL COMMENT '平均点击花费（站点币种）',
    cvr_1d DECIMAL(20,8) NULL COMMENT '1d归因转化率',
    cvr_7d DECIMAL(20,8) NULL COMMENT '7d归因转化率',
    cvr_14d DECIMAL(20,8) NULL COMMENT '14d归因转化率',
    cvr_30d DECIMAL(20,8) NULL COMMENT '30d归因转化率',
    acos_1d DECIMAL(20,8) NULL COMMENT '1d归因ACOS',
    acos_7d DECIMAL(20,8) NULL COMMENT '7d归因ACOS，建议规则口径',
    acos_14d DECIMAL(20,8) NULL COMMENT '14d归因ACOS',
    acos_30d DECIMAL(20,8) NULL COMMENT '30d归因ACOS',
    roas_1d DECIMAL(20,8) NULL COMMENT '1d归因ROAS',
    roas_7d DECIMAL(20,8) NULL COMMENT '7d归因ROAS',
    roas_14d DECIMAL(20,8) NULL COMMENT '14d归因ROAS',
    roas_30d DECIMAL(20,8) NULL COMMENT '30d归因ROAS',
    attribution_1d_mature TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1d归因是否成熟',
    attribution_7d_mature TINYINT(1) NOT NULL DEFAULT 1 COMMENT '7d归因是否成熟',
    attribution_14d_mature TINYINT(1) NOT NULL DEFAULT 0 COMMENT '14d归因是否成熟',
    attribution_30d_mature TINYINT(1) NOT NULL DEFAULT 0 COMMENT '30d归因是否成熟',

    add_status VARCHAR(30) NOT NULL COMMENT '加词状态',
    add_priority VARCHAR(20) NOT NULL COMMENT '加词优先级',
    add_suggestion_type VARCHAR(40) NOT NULL COMMENT 'exact_keyword/product_target',
    add_suggestion_value VARCHAR(500) NOT NULL COMMENT '建议新增值',
    add_reason_codes JSON NOT NULL COMMENT '加词原因代码',
    is_add_recommended TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否建议加词',

    negative_status VARCHAR(30) NOT NULL COMMENT '否词状态',
    negative_priority VARCHAR(20) NOT NULL COMMENT '否词优先级',
    negative_suggestion_type VARCHAR(50) NOT NULL COMMENT 'negative_exact/negative_product_target',
    negative_suggestion_value VARCHAR(500) NOT NULL COMMENT '建议否定值',
    negative_reason_codes JSON NOT NULL COMMENT '否词原因代码',
    is_negative_recommended TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否建议否词',
    needs_manual_review TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需要人工审核',

    source_latest_create_time DATETIME NULL COMMENT '本组搜索词源记录最新同步时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    PRIMARY KEY (snapshot_date, row_key),
    KEY idx_search_term_store (snapshot_date, seller_name, country_code),
    KEY idx_search_term_msku (snapshot_date, msku),
    KEY idx_search_term_campaign (snapshot_date, profile_id, campaign_id),
    KEY idx_search_term_ad_group (snapshot_date, profile_id, ad_group_id),
    KEY idx_search_term_add (snapshot_date, add_status, add_priority),
    KEY idx_search_term_negative (snapshot_date, negative_status, negative_priority),
    KEY idx_search_term_targeting (snapshot_date, targeting_type),
    KEY idx_search_term_normalized (snapshot_date, search_term_normalized(100))
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='SP搜索词表现、MSKU安全归属及加词否词建议每日快照';
