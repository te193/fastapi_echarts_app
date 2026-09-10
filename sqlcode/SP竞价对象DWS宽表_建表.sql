/*
用途：创建 SP 竞价对象每日快照宽表。
数据库：MySQL 8.0
目标表：dws_datasync.dws_sp_bid_object_snapshot_daily

粒度：
1. 手动广告一行对应一个关键词（object_type = keyword）。
2. 自动广告一行对应一个广告组（object_type = ad_group）。
3. 活动、广告组和安全归属后的产品是竞价对象的维度，不展开关键词 × MSKU。
4. 产品预算及产品花费会在同一产品的多个竞价对象上重复展示；跨行汇总时只统计
   product_metric_owner_flag = 1 的记录。
*/

CREATE TABLE IF NOT EXISTS dws_datasync.dws_sp_bid_object_snapshot_daily (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    snapshot_date DATE NOT NULL COMMENT '业务快照日期，即广告表现共同截止日',
    row_key CHAR(64) NOT NULL COMMENT '竞价对象业务键SHA256，不含快照日期',
    rule_version VARCHAR(100) NOT NULL COMMENT '竞价建议规则版本',
    mature_start DATE NOT NULL COMMENT '成熟30天窗口开始日期',
    mature_end DATE NOT NULL COMMENT '成熟30天窗口结束日期',
    source_keyword_days TINYINT UNSIGNED NOT NULL COMMENT '关键词报表成熟窗口覆盖天数',
    source_ad_group_days TINYINT UNSIGNED NOT NULL COMMENT '广告组报表成熟窗口覆盖天数',
    source_product_ad_days TINYINT UNSIGNED NOT NULL COMMENT '商品广告报表成熟窗口覆盖天数',
    budget_snapshot_date DATE NULL COMMENT '远端产品预算快照日期',
    budget_performance_date DATE NULL COMMENT '产品花费统计截止日期',

    profile_id BIGINT NOT NULL COMMENT '广告账号Profile ID',
    sid BIGINT NULL COMMENT '领星店铺SID',
    base_store_name VARCHAR(255) NULL COMMENT '去除站点后缀的店铺主体',
    seller_name VARCHAR(255) NULL COMMENT '广告店铺名称',
    country_code VARCHAR(20) NULL COMMENT '站点代码',
    currency_code VARCHAR(20) NULL COMMENT '竞价与广告表现的站点币种',
    product_currency_code VARCHAR(10) NULL COMMENT '产品预算源币种',
    exchange_rate_cny DECIMAL(20,8) NULL COMMENT '产品预算源币种兑人民币汇率',
    budget_currency_code VARCHAR(10) NOT NULL DEFAULT 'CNY' COMMENT '产品预算与产品花费币种',

    campaign_id BIGINT NOT NULL COMMENT '广告活动ID',
    campaign_name_current VARCHAR(255) NULL COMMENT '当前广告活动名称',
    campaign_state_current VARCHAR(50) NULL COMMENT '当前广告活动状态',
    campaign_serving_status VARCHAR(100) NULL COMMENT '当前广告活动投放状态',
    campaign_type VARCHAR(50) NULL COMMENT '广告活动类型',
    targeting_type VARCHAR(50) NOT NULL COMMENT 'auto/manual/unknown',
    portfolio_id BIGINT NULL COMMENT '广告组合ID',
    daily_budget_current DECIMAL(20,6) NULL COMMENT '当前活动日预算（站点币种）',
    bidding_strategy_current VARCHAR(100) NULL COMMENT '当前竞价策略',
    placement_top_percentage DECIMAL(10,4) NULL COMMENT '搜索结果顶部竞价调整百分比',
    placement_product_page_percentage DECIMAL(10,4) NULL COMMENT '商品页面竞价调整百分比',
    placement_rest_of_search_percentage DECIMAL(10,4) NULL COMMENT '搜索结果其余位置竞价调整百分比',

    ad_group_id BIGINT NOT NULL COMMENT '广告组ID',
    ad_group_name_current VARCHAR(255) NULL COMMENT '当前广告组名称',
    ad_group_state_current VARCHAR(50) NULL COMMENT '当前广告组状态',
    ad_group_serving_status VARCHAR(100) NULL COMMENT '当前广告组投放状态',
    default_bid_current DECIMAL(20,6) NULL COMMENT '当前广告组默认竞价（站点币种）',

    object_type VARCHAR(30) NOT NULL COMMENT 'keyword/ad_group',
    object_id BIGINT NOT NULL COMMENT '关键词ID或自动广告组ID',
    object_text VARCHAR(1000) COLLATE utf8mb4_bin NULL COMMENT '关键词文本或广告组名称',
    object_state_current VARCHAR(50) NULL COMMENT '当前竞价对象状态',
    object_serving_status VARCHAR(100) NULL COMMENT '当前竞价对象投放状态',
    match_type VARCHAR(100) NULL COMMENT '关键词匹配方式；自动广告为空',

    msku VARCHAR(100) NULL COMMENT '安全归属后的MSKU',
    asin VARCHAR(50) NULL COMMENT '安全归属后的ASIN',
    associated_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '周期与当前MSKU数量最大值',
    period_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '成熟窗口内不同MSKU数',
    current_enabled_msku_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前启用MSKU数',
    msku_mapping_status VARCHAR(40) NOT NULL COMMENT 'mapped/period_multiple_msku/current_multiple_msku/msku_changed等',
    product_metric_owner_flag TINYINT(1) NOT NULL DEFAULT 0 COMMENT '同产品预算与花费的唯一可汇总行',

    impressions BIGINT NOT NULL DEFAULT 0 COMMENT '成熟30天曝光量',
    clicks BIGINT NOT NULL DEFAULT 0 COMMENT '成熟30天点击量',
    cost DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天对象花费（站点币种）',
    orders DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d归因订单',
    sales DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d归因销售额（站点币种）',
    attributed_orders_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因订单',
    attributed_orders_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因订单；与orders同口径',
    attributed_orders_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因订单',
    attributed_orders_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因订单',
    attributed_sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因销售额（站点币种）',
    attributed_sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因销售额；与sales同口径（站点币种）',
    attributed_sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因销售额（站点币种）',
    attributed_sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因销售额（站点币种）',
    attributed_units_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因销量',
    attributed_units_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因销量',
    attributed_units_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因销量',
    attributed_units_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因销量',
    same_sku_attributed_orders_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因订单',
    same_sku_attributed_orders_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因订单',
    same_sku_attributed_orders_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因订单',
    same_sku_attributed_orders_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因订单',
    same_sku_attributed_sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因销售额（站点币种）',
    same_sku_attributed_sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因销售额（站点币种）',
    same_sku_attributed_sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因销售额（站点币种）',
    same_sku_attributed_sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因销售额（站点币种）',
    same_sku_attributed_units_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因销量',
    same_sku_attributed_units_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因销量',
    same_sku_attributed_units_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因销量',
    same_sku_attributed_units_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因销量',
    aov DECIMAL(20,6) NULL COMMENT '广告客单价：sales/orders',
    ctr DECIMAL(20,8) NULL COMMENT '点击率：clicks/impressions',
    cpc DECIMAL(20,8) NULL COMMENT '平均点击成本：cost/clicks',
    cvr DECIMAL(20,8) NULL COMMENT '7d归因转化率：orders/clicks',
    acos DECIMAL(20,8) NULL COMMENT '广告投入产出比：cost/sales',
    roas DECIMAL(20,8) NULL COMMENT '广告回报率：sales/cost',

    current_bid DECIMAL(20,6) NULL COMMENT '当前关键词竞价或自动广告组默认竞价',
    listing_price DECIMAL(20,6) NULL COMMENT '当前Listing价格（站点币种）',
    margin_rate DECIMAL(10,6) NULL COMMENT 'Listing价格命中的毛利率阶梯',
    site_cvr_avg DECIMAL(20,8) NULL COMMENT '同对象类型同站点加权CVR',
    site_cvr_p75 DECIMAL(20,8) NULL COMMENT '同对象类型同站点对象CVR的P75',
    theoretical_cpc DECIMAL(20,6) NULL COMMENT '理论最高CPC：AOV×CVR×毛利率',
    reference_cpc_20 DECIMAL(20,6) NULL COMMENT '20%毛利参考CPC',
    reference_cpc_333 DECIMAL(20,6) NULL COMMENT '33.3%毛利参考CPC',
    suggested_bid DECIMAL(20,6) NULL COMMENT '建议竞价（站点币种）',
    max_allowed_bid DECIMAL(20,6) NULL COMMENT '库存与预算保护后的最高允许建议竞价',
    change_direction VARCHAR(30) NULL COMMENT 'increase/decrease/keep',
    change_amount DECIMAL(20,6) NULL COMMENT '建议竞价减当前竞价',
    change_rate DECIMAL(20,8) NULL COMMENT '竞价调整比例',
    bid_lower_limit DECIMAL(20,6) NULL COMMENT '预留竞价下限，首版为空且不参与计算',
    bid_upper_limit DECIMAL(20,6) NULL COMMENT '预留竞价上限，首版为空且不参与计算',
    raw_recommendation_status VARCHAR(30) NOT NULL COMMENT '规则原始状态',
    recommendation_status VARCHAR(50) NOT NULL COMMENT '页面最终状态',
    priority_rank INT NOT NULL DEFAULT 9 COMMENT '动作优先级，1为明确调价，9为其他',
    reason_codes JSON NOT NULL COMMENT '建议原因代码数组',
    data_warning VARCHAR(500) NULL COMMENT '数据缺失或映射异常提示',

    monthly_ad_budget_original DECIMAL(20,2) NULL COMMENT '产品月预算（预算源原币）',
    monthly_ad_budget_cny DECIMAL(20,2) NULL COMMENT '产品月预算（人民币）',
    weekly_ad_budget_original DECIMAL(20,2) NULL COMMENT '产品周预算（预算源原币）',
    weekly_ad_budget_cny DECIMAL(20,2) NULL COMMENT '产品周预算（人民币）',
    month_product_spend_cny DECIMAL(20,4) NULL COMMENT '产品本月至快照日广告花费（人民币口径）',
    spend_7d_cny DECIMAL(20,4) NULL COMMENT '产品截至快照日近7天广告花费（人民币口径）',
    monthly_remaining_budget_cny DECIMAL(20,4) NULL COMMENT '月预算余额，可为负数',
    weekly_remaining_budget_cny DECIMAL(20,4) NULL COMMENT '周预算余额，可为负数',
    monthly_budget_usage_rate DECIMAL(20,8) NULL COMMENT '本月花费/月预算',
    weekly_budget_usage_rate DECIMAL(20,8) NULL COMMENT '近7天花费/周预算',
    month_progress_rate DECIMAL(20,8) NULL COMMENT '快照日在自然月中的时间进度',
    monthly_budget_status VARCHAR(50) NOT NULL COMMENT 'missing/spend_missing/normal/overspent/too_fast/too_slow/not_started',
    weekly_budget_status VARCHAR(50) NOT NULL COMMENT 'missing/spend_missing/normal/overspent',
    budget_config_status VARCHAR(30) NOT NULL COMMENT 'complete/incomplete/invalid',
    budget_support_status VARCHAR(100) NOT NULL COMMENT '提价预算与库存保护状态',
    budget_anomalies JSON NOT NULL COMMENT '预算异常代码数组',
    site_total_budget_cny DECIMAL(20,2) NULL COMMENT '站点总预算（人民币）',
    inventory_sufficient_flag TINYINT(1) NULL COMMENT '30天库存是否充足',
    weekly_inventory_sufficient_flag TINYINT(1) NULL COMMENT '7天库存是否充足',

    source_latest_create_time DATETIME NULL COMMENT '参与计算的源数据最新同步时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    PRIMARY KEY (id),
    UNIQUE KEY uq_snapshot_object (
        snapshot_date, profile_id, campaign_id, ad_group_id, object_type, object_id
    ),
    UNIQUE KEY uq_snapshot_row_key (snapshot_date, row_key),
    KEY idx_snapshot_filter (
        snapshot_date, base_store_name, country_code, targeting_type
    ),
    KEY idx_snapshot_action (
        snapshot_date, recommendation_status, priority_rank, cost
    ),
    KEY idx_snapshot_hierarchy (
        snapshot_date, profile_id, campaign_id, ad_group_id
    ),
    KEY idx_snapshot_product (
        snapshot_date, seller_name, country_code, msku
    ),
    KEY idx_snapshot_object_state (
        snapshot_date, object_type, object_state_current
    ),
    KEY idx_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='SP手动关键词与自动广告组竞价对象每日快照宽表';

/* 既有表迁移：仅新增字段，不删除任何历史快照数据。请只执行一次。 */
ALTER TABLE dws_datasync.dws_sp_bid_object_snapshot_daily
    ADD COLUMN attributed_orders_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因订单',
    ADD COLUMN attributed_orders_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因订单；与orders同口径',
    ADD COLUMN attributed_orders_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因订单',
    ADD COLUMN attributed_orders_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因订单',
    ADD COLUMN attributed_sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因销售额（站点币种）',
    ADD COLUMN attributed_sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因销售额；与sales同口径（站点币种）',
    ADD COLUMN attributed_sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因销售额（站点币种）',
    ADD COLUMN attributed_sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因销售额（站点币种）',
    ADD COLUMN attributed_units_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d总归因销量',
    ADD COLUMN attributed_units_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d总归因销量',
    ADD COLUMN attributed_units_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d总归因销量',
    ADD COLUMN attributed_units_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d总归因销量',
    ADD COLUMN same_sku_attributed_orders_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因订单',
    ADD COLUMN same_sku_attributed_orders_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因订单',
    ADD COLUMN same_sku_attributed_orders_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因订单',
    ADD COLUMN same_sku_attributed_orders_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因订单',
    ADD COLUMN same_sku_attributed_sales_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因销售额（站点币种）',
    ADD COLUMN same_sku_attributed_sales_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因销售额（站点币种）',
    ADD COLUMN same_sku_attributed_sales_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因销售额（站点币种）',
    ADD COLUMN same_sku_attributed_sales_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因销售额（站点币种）',
    ADD COLUMN same_sku_attributed_units_1d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天1d同款归因销量',
    ADD COLUMN same_sku_attributed_units_7d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天7d同款归因销量',
    ADD COLUMN same_sku_attributed_units_14d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天14d同款归因销量',
    ADD COLUMN same_sku_attributed_units_30d DECIMAL(20,4) NOT NULL DEFAULT 0 COMMENT '成熟30天30d同款归因销量';
