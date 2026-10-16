-- 标签综合分析预计算表结构，2026-10-14。
-- 目标仅为项目配置的192.168.112.235:3306 / etl_datasync_test。
-- 由预计算迁移工具执行；必须核验目标连接，不能拿source连接执行。
-- 这里只定义独立新表，不同步数据、不发布批次、不改变或删除旧表。

create table if not exists etl_datasync_test.dashboard_analysis_object (
    object_id bigint unsigned not null auto_increment,
    object_key varchar(64) character set ascii collate ascii_bin not null,
    view_kind varchar(16) not null,
    country_category varchar(64) not null,
    country varchar(64) not null default '',
    store varchar(128) not null,
    msku varchar(128) not null,
    first_seen_date date null,
    inception_date date null,
    inception_evidence varchar(255) null,
    primary key (object_id),
    unique key uk_object_key (view_kind, object_key),
    key idx_scope (view_kind, country_category, store, country),
    key idx_msku (msku)
) engine=innodb default charset=utf8mb4 comment='分析对象主数据，视角单独建对象';

create table if not exists etl_datasync_test.dashboard_analysis_source_partition (
    partition_id bigint unsigned not null auto_increment,
    domain varchar(32) not null,
    grain_kind varchar(20) not null,
    data_date date not null,
    source_checksum char(64) character set ascii not null,
    source_manifest json not null,
    row_count bigint unsigned not null,
    state varchar(20) not null,
    transform_version varchar(100) not null,
    created_at datetime(6) not null default current_timestamp(6),
    primary key (partition_id),
    unique key uk_partition (domain, grain_kind, data_date, source_checksum, transform_version)
) engine=innodb default charset=utf8mb4 comment='按域日期的不可变事实版本，状态区分ready、无来源覆盖和失败';

create table if not exists etl_datasync_test.dashboard_analysis_batch (
    batch_id char(36) character set ascii collate ascii_bin not null,
    state varchar(20) not null default 'building',
    formula_version varchar(100) not null,
    schema_version varchar(40) not null,
    source_manifest json not null,
    available_windows json not null,
    label_dictionary json not null,
    quality_report json null,
    started_at datetime(6) not null default current_timestamp(6),
    completed_at datetime(6) null,
    primary key (batch_id),
    key idx_state_time (state, started_at)
) engine=innodb default charset=utf8mb4 comment='单批次完整结果，校验后方可发布';

create table if not exists etl_datasync_test.dashboard_analysis_batch_partition (
    batch_id char(36) character set ascii collate ascii_bin not null,
    domain varchar(32) not null,
    grain_kind varchar(20) not null,
    data_date date not null,
    partition_id bigint unsigned not null,
    primary key (batch_id, domain, grain_kind, data_date),
    key idx_partition_refs (partition_id)
) engine=innodb default charset=utf8mb4 comment='批次固定日事实分区，未变化的日期复用已有分区';

create table if not exists etl_datasync_test.dashboard_analysis_publication (
    singleton tinyint unsigned not null,
    batch_id char(36) character set ascii collate ascii_bin not null,
    published_at datetime(6) not null default current_timestamp(6),
    primary key (singleton),
    check (singleton=1)
) engine=innodb default charset=utf8mb4 comment='当前发布指针；准备任务完成后短事务切换';

create table if not exists etl_datasync_test.dashboard_analysis_business_daily (
    partition_id bigint unsigned not null,
    data_date date not null,
    object_id bigint unsigned not null,
    sales_qty decimal(20,4) null,
    sales_amount decimal(20,4) null,
    sales_amount_ex_tax decimal(20,4) null,
    order_gross_profit decimal(20,4) null,
    settlement_gross_profit decimal(20,4) null,
    net_amount decimal(20,4) null,
    ad_spend decimal(20,4) null,
    ad_sales decimal(20,4) null,
    ad_orders decimal(20,4) null,
    ad_clicks decimal(20,4) null,
    ad_impressions decimal(20,4) null,
    return_count decimal(20,4) null,
    return_amount decimal(20,4) null,
    quality_json json null,
    primary key (partition_id, object_id),
    key idx_history (object_id, data_date, partition_id)
) engine=innodb default charset=utf8mb4 comment='由已发布经营事实在后台归一，供趋势和侧栏读取';

create table if not exists etl_datasync_test.dashboard_analysis_traffic_daily (
    partition_id bigint unsigned not null,
    data_date date not null,
    object_id bigint unsigned not null,
    sessions_total decimal(20,4) null,
    page_views decimal(20,4) null,
    order_count decimal(20,4) null,
    traffic_sales_qty decimal(20,4) null,
    sessions_browser decimal(20,4) null,
    sessions_mobile decimal(20,4) null,
    page_views_browser decimal(20,4) null,
    page_views_mobile decimal(20,4) null,
    quality_json json null,
    primary key (partition_id, object_id),
    key idx_history (object_id, data_date, partition_id)
) engine=innodb default charset=utf8mb4 comment='产品表现总流量日事实，先同步和归并再供页面读取';

create table if not exists etl_datasync_test.dashboard_analysis_inventory_daily (
    partition_id bigint unsigned not null,
    data_date date not null,
    pool_key char(64) character set ascii collate ascii_bin not null,
    country_category varchar(64) not null,
    store varchar(128) not null,
    source_qty decimal(20,4) null,
    sellable_qty decimal(20,4) null,
    total_qty decimal(20,4) null,
    total_cost decimal(20,4) null,
    sellable_cost decimal(20,4) null,
    available_qty decimal(20,4) null,
    available_cost decimal(20,4) null,
    unsellable_qty decimal(20,4) null,
    reserved_qty decimal(20,4) null,
    transfer_qty decimal(20,4) null,
    processing_qty decimal(20,4) null,
    inbound_qty decimal(20,4) null,
    in_transit_qty decimal(20,4) null,
    in_transit_cost decimal(20,4) null,
    stock_state tinyint unsigned not null default 2,
    quality_json json null,
    primary key (partition_id, pool_key),
    key idx_history (pool_key, data_date, partition_id),
    check (stock_state in (0,1,2))
) engine=innodb default charset=utf8mb4 comment='库存池日事实：0断货、1有货、2未知，不将异常或缺失补零';

create table if not exists etl_datasync_test.dashboard_analysis_inventory_map_daily (
    partition_id bigint unsigned not null,
    data_date date not null,
    object_id bigint unsigned not null,
    pool_key char(64) character set ascii collate ascii_bin null,
    demand_key char(64) character set ascii collate ascii_bin null,
    inherited_daily_sales decimal(20,6) null,
    mapping_state varchar(20) not null,
    mapping_evidence json null,
    primary key (partition_id, object_id),
    key idx_pool_members (partition_id, pool_key, object_id),
    key idx_demand_members (partition_id, demand_key, object_id),
    key idx_object_history (object_id, data_date, partition_id)
) engine=innodb default charset=utf8mb4 comment='商品当天到库存池和完整补货需求对象的映射';

create table if not exists etl_datasync_test.dashboard_analysis_supply_daily (
    partition_id bigint unsigned not null,
    data_date date not null,
    demand_key char(64) character set ascii collate ascii_bin not null,
    effective_daily_sales decimal(20,6) null,
    coverage_inventory_qty decimal(20,4) null,
    fba_coverage_days decimal(20,6) null,
    support_inventory_qty decimal(20,4) null,
    support_days decimal(20,6) null,
    arrival_support_days decimal(20,6) null,
    lead_stockout_days decimal(20,6) null,
    lead_shortfall_qty decimal(20,4) null,
    purchase_lead_days decimal(20,6) null,
    published_result_json json not null,
    source_rule_version varchar(100) not null,
    quality_json json null,
    primary key (partition_id, demand_key),
    key idx_history (demand_key, data_date, partition_id)
) engine=innodb default charset=utf8mb4 comment='复用补货已发布结果；完整需求对象去重，页面不重算日销';

create table if not exists etl_datasync_test.dashboard_analysis_object_tag (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    object_id bigint unsigned not null,
    parent_id int unsigned not null,
    label_id int unsigned not null,
    label_period varchar(20) not null default '',
    label_date date not null,
    evidence_reference varchar(255) null,
    evidence_json json null,
    primary key (batch_id, cutoff_date, object_id, parent_id, label_id, label_period),
    key idx_tag_members (batch_id, cutoff_date, parent_id, label_id, label_period, object_id)
) engine=innodb default charset=utf8mb4 comment='只关联原标签事实，筛选先取去重商品集合再汇总';

create table if not exists etl_datasync_test.dashboard_analysis_business_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    object_id bigint unsigned not null,
    sales_qty decimal(20,4) null,
    sales_amount decimal(20,4) null,
    sales_amount_ex_tax decimal(20,4) null,
    order_gross_profit decimal(20,4) null,
    settlement_gross_profit decimal(20,4) null,
    net_amount decimal(20,4) null,
    positive_profit decimal(20,4) null,
    loss_amount decimal(20,4) null,
    ad_spend decimal(20,4) null,
    ad_sales decimal(20,4) null,
    ad_orders decimal(20,4) null,
    ad_clicks decimal(20,4) null,
    ad_impressions decimal(20,4) null,
    return_count decimal(20,4) null,
    return_amount decimal(20,4) null,
    zero_order_spend decimal(20,4) null,
    paired_values json not null,
    coverage_json json not null,
    result_json json not null,
    primary key (batch_id, cutoff_date, period_days, object_id),
    key idx_sales_sort (batch_id, cutoff_date, period_days, sales_amount, object_id)
) engine=innodb default charset=utf8mb4 comment='经营域周期结果；paired_values保留比率共同有效分子分母，不能平均明细比率';

create table if not exists etl_datasync_test.dashboard_analysis_traffic_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    object_id bigint unsigned not null,
    sessions_total decimal(20,4) null,
    page_views decimal(20,4) null,
    order_count decimal(20,4) null,
    traffic_sales_qty decimal(20,4) null,
    sessions_browser decimal(20,4) null,
    sessions_mobile decimal(20,4) null,
    page_views_browser decimal(20,4) null,
    page_views_mobile decimal(20,4) null,
    cvr_orders_numerator decimal(20,4) null,
    cvr_orders_sessions_denominator decimal(20,4) null,
    cvr_units_numerator decimal(20,4) null,
    cvr_units_sessions_denominator decimal(20,4) null,
    paired_values json not null,
    coverage_json json not null,
    result_json json not null,
    primary key (batch_id, cutoff_date, period_days, object_id),
    key idx_sessions_sort (batch_id, cutoff_date, period_days, sessions_total, object_id)
) engine=innodb default charset=utf8mb4 comment='总流量周期结果；两类CVR以及跨域效率分别保留共同有效样本';

create table if not exists etl_datasync_test.dashboard_analysis_stockout_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    object_id bigint unsigned not null,
    stockout_days smallint unsigned null,
    instock_days smallint unsigned null,
    unknown_days smallint unsigned not null,
    valid_days smallint unsigned not null,
    expected_days smallint unsigned not null,
    current_stock_state tinyint unsigned not null default 2,
    current_stockout_days int unsigned null,
    max_stockout_days smallint unsigned null,
    confirmed_events smallint unsigned null,
    current_lower_bound tinyint unsigned not null default 0,
    max_lower_bound tinyint unsigned not null default 0,
    result_json json not null,
    quality_json json null,
    primary key (batch_id, cutoff_date, period_days, object_id),
    key idx_current_stockout (batch_id, cutoff_date, period_days, current_stock_state, object_id),
    key idx_stockout_sort (batch_id, cutoff_date, period_days, stockout_days, object_id),
    check (current_stock_state in (0,1,2)),
    check (valid_days+unknown_days=expected_days)
) engine=innodb default charset=utf8mb4 comment='断货按商品和周期提前计算；整期无观察时天数为空';

create table if not exists etl_datasync_test.dashboard_analysis_inventory_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    pool_key char(64) character set ascii collate ascii_bin not null,
    quantity_sum decimal(24,4) null,
    cost_sum decimal(24,4) null,
    quantity_valid_days smallint unsigned not null,
    cost_valid_days smallint unsigned not null,
    expected_days smallint unsigned not null,
    stockout_days smallint unsigned null,
    instock_days smallint unsigned null,
    quality_json json null,
    primary key (batch_id, cutoff_date, period_days, pool_key)
) engine=innodb default charset=utf8mb4 comment='库存池周期结果；不同商品关联同一库存池时不得重复求和';

create table if not exists etl_datasync_test.dashboard_analysis_tag_summary (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    view_kind varchar(16) not null,
    preset_key varchar(64) not null,
    parent_id int unsigned not null,
    label_id int unsigned not null,
    metrics_json json not null,
    denominator_json json not null,
    primary key (batch_id, cutoff_date, period_days, view_kind, preset_key, parent_id, label_id)
) engine=innodb default charset=utf8mb4 comment='常用单标签汇总缓存，任意组合必须从商品结果聚合而非相加';

create table if not exists etl_datasync_test.dashboard_analysis_object_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    analysis_date date not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    view_kind varchar(16) not null,
    phase varchar(16) not null,
    object_id bigint unsigned not null,
    context_json json not null,
    primary key (batch_id,analysis_date,period_days,view_kind,phase,object_id)
) engine=innodb default charset=utf8mb4 comment='商品周期上下文，与分域结果连接；不包含日事实';

create table if not exists etl_datasync_test.dashboard_analysis_inventory_object_period (
    batch_id char(36) character set ascii collate ascii_bin not null,
    cutoff_date date not null,
    period_days smallint unsigned not null,
    object_id bigint unsigned not null,
    result_json json not null,
    primary key (batch_id,cutoff_date,period_days,object_id)
) engine=innodb default charset=utf8mb4 comment='商品关联的库存补货结果；响应汇总仍按库存池和需求对象去重';

create table if not exists etl_datasync_test.dashboard_analysis_object_history (
    batch_id char(36) character set ascii collate ascii_bin not null,
    object_id bigint unsigned not null,
    payload longblob not null,
    checksum char(64) character set ascii not null,
    primary key (batch_id,object_id)
) engine=innodb default charset=utf8mb4 comment='不可变压缩日事实及证据；只供趋势和商品侧栏按需读取';

create table if not exists etl_datasync_test.dashboard_analysis_scope (
    batch_id char(36) character set ascii collate ascii_bin not null,
    scope_key char(64) character set ascii collate ascii_bin not null,
    scope_json json not null,
    state varchar(20) not null default 'building',
    result_json json null,
    updated_at datetime(6) not null default current_timestamp(6),
    primary key(batch_id,scope_key)
) engine=innodb default charset=utf8mb4 comment='有界商品块的完成记录，来源版本相同才允许断点续跑';
