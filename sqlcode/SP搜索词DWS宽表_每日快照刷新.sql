/*
用途：每天只重建 SP 搜索词分析的当天快照，并保留最近 7 个快照日期。
数据库：MySQL 8.0
目标表：dws_datasync.dws_sp_search_term_analysis_daily

执行前提：
1. 请先执行《SP搜索词DWS宽表_建表.sql》创建目标表。
2. 默认以搜索词报表最大日期作为快照日。
3. 如需指定日期，请先执行：SET @requested_snapshot_date = '2026-09-08';
4. 成熟窗口为快照日前跳过 7 天，再取 30 个自然日。
5. 只有搜索词和商品广告两个成熟窗口都覆盖 30 天时，才刷新并清理历史快照。
6. 当天快照不会累计此前快照的数据；同一天重复执行时先删除当天旧结果，再写当天新结果。
7. 快照日期不足 7 个时持续追加且不删除；写入第 8 个快照日期后删除最早快照，只保留日期最新的 7 份。
8. opt_db.tmp_spst_* 均为连接级临时表，会话结束自动释放。
*/

/* ============================== 刷新参数与前置校验 ============================== */

SET SESSION group_concat_max_len = 8192;

SET @snapshot_date = COALESCE(
    STR_TO_DATE(NULLIF(TRIM(@requested_snapshot_date), ''), '%Y-%m-%d'),
    (
        SELECT STR_TO_DATE(MAX(report_date), '%Y-%m-%d')
        FROM dwd_datasync.lx_advertising_sp_query_word_reports
    )
);
SET @mature_end = DATE_SUB(@snapshot_date, INTERVAL 7 DAY);
SET @mature_start = DATE_SUB(@mature_end, INTERVAL 29 DAY);
SET @rule_version = 'sp-search-term-v1';

/* 两个成熟窗口只读取一次：完整性检查和后续聚合共同复用。 */
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_search_source;

CREATE TEMPORARY TABLE opt_db.tmp_spst_search_source
ENGINE=InnoDB
AS
SELECT
    report_date, profile_id, campaign_id, ad_group_id, target_id,
    query, match_type, target_text, seller_name, create_time,
    impressions, clicks, cost,
    orders_1d, orders_7d, orders_14d, orders_30d,
    same_orders_1d, same_orders_7d, same_orders_14d, same_orders_30d,
    sales_1d, sales_7d, sales_14d, sales_30d,
    same_sales_1d, same_sales_7d, same_sales_14d, same_sales_30d,
    units_1d, units_7d, units_14d, units_30d,
    same_units_1d, same_units_7d, same_units_14d, same_units_30d
FROM dwd_datasync.lx_advertising_sp_query_word_reports
WHERE report_date BETWEEN DATE_FORMAT(@mature_start, '%Y-%m-%d')
                      AND DATE_FORMAT(@mature_end, '%Y-%m-%d');

ALTER TABLE opt_db.tmp_spst_search_source
    ADD KEY idx_report_date (report_date),
    ADD KEY idx_group (profile_id, campaign_id, ad_group_id, target_id);

SET @source_search_term_days = (
    SELECT COUNT(DISTINCT report_date)
    FROM opt_db.tmp_spst_search_source
);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_product_source;

CREATE TEMPORARY TABLE opt_db.tmp_spst_product_source
ENGINE=InnoDB
AS
SELECT
    d.report_date,
    o.profile_id,
    o.campaign_id,
    o.ad_group_id,
    d.sku,
    d.asin
FROM dwd_datasync.lx_advertising_sp_product_ad_reports d
INNER JOIN ods_datasync.lx_advertising_sp_product_ad_reports o
    ON o.id = d.relate_id
WHERE d.report_date BETWEEN DATE_FORMAT(@mature_start, '%Y-%m-%d')
                        AND DATE_FORMAT(@mature_end, '%Y-%m-%d')
  AND o.profile_id IS NOT NULL
  AND o.campaign_id IS NOT NULL
  AND o.ad_group_id IS NOT NULL;

ALTER TABLE opt_db.tmp_spst_product_source
    ADD KEY idx_report_date (report_date),
    ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

SET @source_product_ad_days = (
    SELECT COUNT(DISTINCT report_date)
    FROM opt_db.tmp_spst_product_source
);
SET @source_complete = (@source_search_term_days = 30 AND @source_product_ad_days = 30);

SELECT
    @snapshot_date AS snapshot_date,
    @mature_start AS mature_start,
    @mature_end AS mature_end,
    @source_search_term_days AS source_search_term_days,
    @source_product_ad_days AS source_product_ad_days,
    @source_complete AS source_complete,
    CASE WHEN @source_complete = 1 THEN '可以刷新' ELSE '源数据不足30天，本次不会改写目标快照' END AS refresh_check;


/* ============================== 分阶段物化与索引 ============================== *//* ============================== 分阶段物化与索引 ============================== */

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_account_ranked;

CREATE TEMPORARY TABLE opt_db.tmp_spst_account_ranked
ENGINE=InnoDB
AS
SELECT
        CAST(profile_id AS UNSIGNED) AS profile_id,
        sid,
        name AS seller_name,
        country_code,
        currency_code,
        ROW_NUMBER() OVER (
            PARTITION BY profile_id
            ORDER BY COALESCE(update_time, create_time) DESC, id DESC
        ) AS rn
    FROM dwd_datasync.lx_advertising_account_list
    WHERE COALESCE(delete_flag, 0) = 0;

ALTER TABLE opt_db.tmp_spst_account_ranked ADD KEY idx_profile_rn (profile_id, rn);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_account_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_account_current
ENGINE=InnoDB
AS
SELECT profile_id, sid, seller_name, country_code, currency_code
    FROM opt_db.tmp_spst_account_ranked
    WHERE rn = 1;

ALTER TABLE opt_db.tmp_spst_account_current ADD KEY idx_profile (profile_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_campaign_ranked;

CREATE TEMPORARY TABLE opt_db.tmp_spst_campaign_ranked
ENGINE=InnoDB
AS
SELECT
        profile_id,
        campaign_id,
        name,
        state,
        targeting_type,
        daily_budget,
        bidding_strategy,
        ROW_NUMBER() OVER (
            PARTITION BY profile_id, campaign_id
            ORDER BY COALESCE(update_time, last_updated_date, create_time) DESC, id DESC
        ) AS rn
    FROM dwd_datasync.lx_advertising_sp_campaigns
    WHERE COALESCE(delete_flag, 0) = 0;

ALTER TABLE opt_db.tmp_spst_campaign_ranked ADD KEY idx_campaign_rn (profile_id, campaign_id, rn);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_campaign_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_campaign_current
ENGINE=InnoDB
AS
SELECT profile_id, campaign_id, name, state, targeting_type, daily_budget, bidding_strategy
    FROM opt_db.tmp_spst_campaign_ranked
    WHERE rn = 1;

ALTER TABLE opt_db.tmp_spst_campaign_current ADD KEY idx_campaign (profile_id, campaign_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_ad_group_ranked;

CREATE TEMPORARY TABLE opt_db.tmp_spst_ad_group_ranked
ENGINE=InnoDB
AS
SELECT
        profile_id,
        campaign_id,
        ad_group_id,
        name,
        state,
        default_bid,
        ROW_NUMBER() OVER (
            PARTITION BY profile_id, campaign_id, ad_group_id
            ORDER BY COALESCE(update_time, last_updated_date, create_time) DESC, id DESC
        ) AS rn
    FROM dwd_datasync.lx_advertising_sp_ad_groups
    WHERE COALESCE(delete_flag, 0) = 0;

ALTER TABLE opt_db.tmp_spst_ad_group_ranked ADD KEY idx_group_rn (profile_id, campaign_id, ad_group_id, rn);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_ad_group_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_ad_group_current
ENGINE=InnoDB
AS
SELECT profile_id, campaign_id, ad_group_id, name, state, default_bid
    FROM opt_db.tmp_spst_ad_group_ranked
    WHERE rn = 1;

ALTER TABLE opt_db.tmp_spst_ad_group_current ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_target_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_target_current
ENGINE=InnoDB
AS
SELECT
        profile_id,
        campaign_id,
        ad_group_id,
        target_id,
        CASE
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 2 THEN 'enabled'
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 1 THEN 'inactive'
            ELSE NULL
        END AS state_bucket
    FROM dwd_datasync.lx_advertising_sp_targets
    WHERE COALESCE(delete_flag, 0) = 0
    GROUP BY profile_id, campaign_id, ad_group_id, target_id;

ALTER TABLE opt_db.tmp_spst_target_current ADD KEY idx_target (profile_id, campaign_id, ad_group_id, target_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_search_term_agg;

CREATE TEMPORARY TABLE opt_db.tmp_spst_search_term_agg
ENGINE=InnoDB
AS
SELECT
        profile_id,
        campaign_id,
        ad_group_id,
        target_id,
        CAST(COALESCE(query, '') AS BINARY) AS search_term_binary,
        CAST(COALESCE(match_type, '') AS BINARY) AS match_type_binary,
        MAX(COALESCE(query, '')) AS search_term,
        MAX(COALESCE(match_type, '')) AS match_type,
        MAX(target_text) AS target_text,
        MAX(seller_name) AS report_seller_name,
        MAX(create_time) AS source_latest_create_time,
        SUM(COALESCE(impressions, 0)) AS impressions,
        SUM(COALESCE(clicks, 0)) AS clicks,
        SUM(COALESCE(cost, 0)) AS cost,
        SUM(COALESCE(orders_1d, 0)) AS orders_1d,
        SUM(COALESCE(orders_7d, 0)) AS orders_7d,
        SUM(COALESCE(orders_14d, 0)) AS orders_14d,
        SUM(COALESCE(orders_30d, 0)) AS orders_30d,
        SUM(COALESCE(same_orders_1d, 0)) AS same_orders_1d,
        SUM(COALESCE(same_orders_7d, 0)) AS same_orders_7d,
        SUM(COALESCE(same_orders_14d, 0)) AS same_orders_14d,
        SUM(COALESCE(same_orders_30d, 0)) AS same_orders_30d,
        SUM(COALESCE(sales_1d, 0)) AS sales_1d,
        SUM(COALESCE(sales_7d, 0)) AS sales_7d,
        SUM(COALESCE(sales_14d, 0)) AS sales_14d,
        SUM(COALESCE(sales_30d, 0)) AS sales_30d,
        SUM(COALESCE(same_sales_1d, 0)) AS same_sales_1d,
        SUM(COALESCE(same_sales_7d, 0)) AS same_sales_7d,
        SUM(COALESCE(same_sales_14d, 0)) AS same_sales_14d,
        SUM(COALESCE(same_sales_30d, 0)) AS same_sales_30d,
        SUM(COALESCE(units_1d, 0)) AS units_1d,
        SUM(COALESCE(units_7d, 0)) AS units_7d,
        SUM(COALESCE(units_14d, 0)) AS units_14d,
        SUM(COALESCE(units_30d, 0)) AS units_30d,
        SUM(COALESCE(same_units_1d, 0)) AS same_units_1d,
        SUM(COALESCE(same_units_7d, 0)) AS same_units_7d,
        SUM(COALESCE(same_units_14d, 0)) AS same_units_14d,
        SUM(COALESCE(same_units_30d, 0)) AS same_units_30d
    FROM opt_db.tmp_spst_search_source
    WHERE profile_id IS NOT NULL
      AND campaign_id IS NOT NULL
      AND ad_group_id IS NOT NULL
      AND NULLIF(TRIM(query), '') IS NOT NULL
    GROUP BY
        profile_id, campaign_id, ad_group_id, target_id,
        CAST(COALESCE(query, '') AS BINARY),
        CAST(COALESCE(match_type, '') AS BINARY);

ALTER TABLE opt_db.tmp_spst_search_term_agg ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

ALTER TABLE opt_db.tmp_spst_search_term_agg ADD KEY idx_target (profile_id, campaign_id, ad_group_id, target_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_period_product;

CREATE TEMPORARY TABLE opt_db.tmp_spst_period_product
ENGINE=InnoDB
AS
SELECT
    profile_id,
    campaign_id,
    ad_group_id,
    COUNT(DISTINCT NULLIF(TRIM(sku), '')) AS period_msku_count,
    CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1 THEN MAX(TRIM(sku)) END AS period_msku,
    CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1 THEN MAX(NULLIF(TRIM(asin), '')) END AS period_asin,
    GROUP_CONCAT(DISTINCT NULLIF(TRIM(sku), '') ORDER BY TRIM(sku) SEPARATOR ',') AS period_msku_candidates
FROM opt_db.tmp_spst_product_source
GROUP BY profile_id, campaign_id, ad_group_id;

ALTER TABLE opt_db.tmp_spst_period_product ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_current_product;

CREATE TEMPORARY TABLE opt_db.tmp_spst_current_product
ENGINE=InnoDB
AS
SELECT
        profile_id,
        campaign_id,
        ad_group_id,
        COUNT(DISTINCT NULLIF(TRIM(sku), '')) AS current_enabled_msku_count,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1 THEN MAX(TRIM(sku)) END AS current_msku,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1 THEN MAX(NULLIF(TRIM(asin), '')) END AS current_asin,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(sku), '') ORDER BY TRIM(sku) SEPARATOR ',') AS current_msku_candidates
    FROM dwd_datasync.lx_advertising_sp_product_ads
    WHERE COALESCE(delete_flag, 0) = 0
      AND LOWER(COALESCE(state, '')) IN ('enabled', 'enable')
    GROUP BY profile_id, campaign_id, ad_group_id;

ALTER TABLE opt_db.tmp_spst_current_product ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_group_keys;

CREATE TEMPORARY TABLE opt_db.tmp_spst_group_keys
ENGINE=InnoDB
AS
SELECT profile_id, campaign_id, ad_group_id FROM opt_db.tmp_spst_period_product
    UNION
    SELECT profile_id, campaign_id, ad_group_id FROM opt_db.tmp_spst_current_product;

ALTER TABLE opt_db.tmp_spst_group_keys ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_group_product_mapping;

CREATE TEMPORARY TABLE opt_db.tmp_spst_group_product_mapping
ENGINE=InnoDB
AS
SELECT
        k.profile_id,
        k.campaign_id,
        k.ad_group_id,
        COALESCE(p.period_msku_count, 0) AS period_msku_count,
        COALESCE(c.current_enabled_msku_count, 0) AS current_enabled_msku_count,
        p.period_msku_candidates,
        c.current_msku_candidates,
        GREATEST(COALESCE(p.period_msku_count, 0), COALESCE(c.current_enabled_msku_count, 0)) AS associated_msku_count,
        CASE
            WHEN COALESCE(p.period_msku_count, 0) = 0 THEN 'period_msku_missing'
            WHEN COALESCE(c.current_enabled_msku_count, 0) = 0 THEN 'current_enabled_msku_missing'
            WHEN p.period_msku_count > 1 THEN 'period_multiple_msku'
            WHEN c.current_enabled_msku_count > 1 THEN 'current_multiple_msku'
            WHEN LOWER(TRIM(p.period_msku)) <> LOWER(TRIM(c.current_msku)) THEN 'msku_changed'
            ELSE 'mapped'
        END AS msku_mapping_status,
        CASE
            WHEN p.period_msku_count = 1
             AND c.current_enabled_msku_count = 1
             AND LOWER(TRIM(p.period_msku)) = LOWER(TRIM(c.current_msku))
            THEN p.period_msku
        END AS msku,
        CASE
            WHEN p.period_msku_count = 1
             AND c.current_enabled_msku_count = 1
             AND LOWER(TRIM(p.period_msku)) = LOWER(TRIM(c.current_msku))
            THEN COALESCE(p.period_asin, c.current_asin)
        END AS asin
    FROM opt_db.tmp_spst_group_keys k
    LEFT JOIN opt_db.tmp_spst_period_product p
        ON p.profile_id = k.profile_id
       AND p.campaign_id = k.campaign_id
       AND p.ad_group_id = k.ad_group_id
    LEFT JOIN opt_db.tmp_spst_current_product c
        ON c.profile_id = k.profile_id
       AND c.campaign_id = k.campaign_id
       AND c.ad_group_id = k.ad_group_id;

ALTER TABLE opt_db.tmp_spst_group_product_mapping ADD KEY idx_group (profile_id, campaign_id, ad_group_id);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_keyword_existing;

CREATE TEMPORARY TABLE opt_db.tmp_spst_keyword_existing
ENGINE=InnoDB
AS
SELECT
        profile_id,
        ad_group_id,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(COALESCE(keyword_text, ''), '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        ))) AS object_normalized,
        CASE
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 2 THEN 'enabled'
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 1 THEN 'inactive'
            ELSE NULL
        END AS existing_state
    FROM dwd_datasync.lx_advertising_sp_keywords
    WHERE COALESCE(delete_flag, 0) = 0
      AND UPPER(COALESCE(match_type, '')) = 'EXACT'
      AND NULLIF(TRIM(keyword_text), '') IS NOT NULL
    GROUP BY
        profile_id,
        ad_group_id,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(COALESCE(keyword_text, ''), '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        )));

ALTER TABLE opt_db.tmp_spst_keyword_existing ADD KEY idx_keyword (profile_id, ad_group_id, object_normalized(100));

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_product_target_existing;

CREATE TEMPORARY TABLE opt_db.tmp_spst_product_target_existing
ENGINE=InnoDB
AS
SELECT
        profile_id,
        ad_group_id,
        UPPER(TRIM(COALESCE(NULLIF(resolved_expression_item_value, ''), expression_item_value))) AS asin,
        CASE
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 2 THEN 'enabled'
            WHEN MAX(CASE WHEN LOWER(COALESCE(state, '')) IN ('enabled', 'enable') THEN 2
                               WHEN LOWER(COALESCE(state, '')) IN ('paused', 'pause', 'archived', 'archive') THEN 1
                               ELSE 0 END) = 1 THEN 'inactive'
            ELSE NULL
        END AS existing_state
    FROM dwd_datasync.lx_advertising_sp_targets
    WHERE COALESCE(delete_flag, 0) = 0
      AND LOWER(COALESCE(NULLIF(resolved_expression_item_type, ''), expression_item_type)) = 'asinsameas'
      AND UPPER(TRIM(COALESCE(NULLIF(resolved_expression_item_value, ''), expression_item_value))) REGEXP '^B[0-9A-Z]{9}$'
    GROUP BY
        profile_id,
        ad_group_id,
        UPPER(TRIM(COALESCE(NULLIF(resolved_expression_item_value, ''), expression_item_value)));

ALTER TABLE opt_db.tmp_spst_product_target_existing ADD KEY idx_asin (profile_id, ad_group_id, asin);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_listing_ranked;

CREATE TEMPORARY TABLE opt_db.tmp_spst_listing_ranked
ENGINE=InnoDB
AS
SELECT
        l.*,
        CASE l.marketplace
            WHEN '美国' THEN 'US' WHEN '加拿大' THEN 'CA' WHEN '墨西哥' THEN 'MX' WHEN '巴西' THEN 'BR'
            WHEN '英国' THEN 'UK' WHEN '德国' THEN 'DE' WHEN '法国' THEN 'FR' WHEN '意大利' THEN 'IT'
            WHEN '西班牙' THEN 'ES' WHEN '荷兰' THEN 'NL' WHEN '瑞典' THEN 'SE' WHEN '波兰' THEN 'PL'
            WHEN '比利时' THEN 'BE' WHEN '爱尔兰' THEN 'IE' WHEN '土耳其' THEN 'TR'
            WHEN '日本' THEN 'JP' WHEN '澳大利亚' THEN 'AU' WHEN '阿联酋' THEN 'AE'
            WHEN '沙特阿拉伯' THEN 'SA' WHEN '印度' THEN 'IN' WHEN '新加坡' THEN 'SG'
            ELSE UPPER(l.marketplace)
        END AS listing_country_code,
        ROW_NUMBER() OVER (
            PARTITION BY LOWER(TRIM(l.seller_name)),
                         CASE l.marketplace
                             WHEN '美国' THEN 'US' WHEN '加拿大' THEN 'CA' WHEN '墨西哥' THEN 'MX' WHEN '巴西' THEN 'BR'
                             WHEN '英国' THEN 'UK' WHEN '德国' THEN 'DE' WHEN '法国' THEN 'FR' WHEN '意大利' THEN 'IT'
                             WHEN '西班牙' THEN 'ES' WHEN '荷兰' THEN 'NL' WHEN '瑞典' THEN 'SE' WHEN '波兰' THEN 'PL'
                             WHEN '比利时' THEN 'BE' WHEN '爱尔兰' THEN 'IE' WHEN '土耳其' THEN 'TR'
                             WHEN '日本' THEN 'JP' WHEN '澳大利亚' THEN 'AU' WHEN '阿联酋' THEN 'AE'
                             WHEN '沙特阿拉伯' THEN 'SA' WHEN '印度' THEN 'IN' WHEN '新加坡' THEN 'SG'
                             ELSE UPPER(l.marketplace)
                         END,
                         LOWER(TRIM(l.seller_sku))
            ORDER BY l.create_time DESC, l.id DESC
        ) AS rn
    FROM dwd_datasync.lx_sales_mws_listing l
    WHERE NULLIF(TRIM(l.seller_name), '') IS NOT NULL
      AND NULLIF(TRIM(l.seller_sku), '') IS NOT NULL;

ALTER TABLE opt_db.tmp_spst_listing_ranked ADD KEY idx_listing_rn (seller_name, seller_sku, rn);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_listing_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_listing_current
ENGINE=InnoDB
AS
SELECT * FROM opt_db.tmp_spst_listing_ranked WHERE rn = 1;

ALTER TABLE opt_db.tmp_spst_listing_current ADD KEY idx_listing (seller_name, seller_sku, listing_country_code);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_latest_title_run;

CREATE TEMPORARY TABLE opt_db.tmp_spst_latest_title_run
ENGINE=InnoDB
AS
SELECT MAX(run_id) AS run_id
    FROM opt_db.lyt_title_optimization_latest_detail;

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_title_ranked;

CREATE TEMPORARY TABLE opt_db.tmp_spst_title_ranked
ENGINE=InnoDB
AS
SELECT
        t.*,
        ROW_NUMBER() OVER (
            PARTITION BY LOWER(TRIM(t.seller_name)), LOWER(TRIM(t.msku))
            ORDER BY t.id DESC
        ) AS rn
    FROM opt_db.lyt_title_optimization_latest_detail t
    INNER JOIN opt_db.tmp_spst_latest_title_run r ON r.run_id = t.run_id;

ALTER TABLE opt_db.tmp_spst_title_ranked ADD KEY idx_title_rn (seller_name, msku, rn);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_title_current;

CREATE TEMPORARY TABLE opt_db.tmp_spst_title_current
ENGINE=InnoDB
AS
SELECT
        seller_name COLLATE utf8mb4_0900_ai_ci AS seller_name,
        msku COLLATE utf8mb4_0900_ai_ci AS msku,
        leaf_category COLLATE utf8mb4_0900_ai_ci AS leaf_category,
        category COLLATE utf8mb4_0900_ai_ci AS category
    FROM opt_db.tmp_spst_title_ranked
    WHERE rn = 1;

ALTER TABLE opt_db.tmp_spst_title_current ADD KEY idx_title (seller_name, msku);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_distinct;

CREATE TEMPORARY TABLE opt_db.tmp_spst_store_brand_distinct
ENGINE=InnoDB
AS
SELECT DISTINCT
        LOWER(TRIM(`店铺名`)) AS store_name_normalized,
        TRIM(`品牌名`) AS brand_name,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(COALESCE(`品牌名`, ''), '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        ))) AS brand_normalized
    FROM opt_db.store_brand_relation
    WHERE NULLIF(TRIM(`店铺名`), '') IS NOT NULL
      AND NULLIF(TRIM(`品牌名`), '') IS NOT NULL;

ALTER TABLE opt_db.tmp_spst_store_brand_distinct ADD KEY idx_store_brand (store_name_normalized(100), brand_normalized(100));

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_agg;

CREATE TEMPORARY TABLE opt_db.tmp_spst_store_brand_agg
ENGINE=InnoDB
AS
SELECT
        store_name_normalized,
        JSON_ARRAYAGG(brand_name) AS store_brands_json
    FROM opt_db.tmp_spst_store_brand_distinct
    GROUP BY store_name_normalized;

ALTER TABLE opt_db.tmp_spst_store_brand_agg ADD KEY idx_store (store_name_normalized(100));

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_base;

CREATE TEMPORARY TABLE opt_db.tmp_spst_term_base
ENGINE=InnoDB
AS
SELECT
        q.*,
        a.sid,
        COALESCE(a.seller_name, q.report_seller_name) AS seller_name,
        a.country_code,
        a.currency_code,
        c.name AS campaign_name_current,
        c.state AS campaign_state_current,
        c.targeting_type,
        c.daily_budget AS daily_budget_current,
        c.bidding_strategy AS bidding_strategy_current,
        g.name AS ad_group_name_current,
        g.state AS ad_group_state_current,
        g.default_bid AS default_bid_current,
        tc.state_bucket AS target_state_current,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(q.search_term, '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        ))) AS search_term_normalized,
        CASE WHEN UPPER(TRIM(q.search_term)) REGEXP '^B[0-9A-Z]{9}$'
             THEN 'product_target' ELSE 'keyword' END AS search_term_type,
        SHA2(CONCAT_WS(CHAR(31),
            COALESCE(CAST(q.profile_id AS CHAR), '<null>'),
            COALESCE(CAST(q.campaign_id AS CHAR), '<null>'),
            COALESCE(CAST(q.ad_group_id AS CHAR), '<null>'),
            COALESCE(CAST(q.target_id AS CHAR), '<null>'),
            COALESCE(q.search_term, '<null>'),
            COALESCE(q.match_type, '<null>')
        ), 256) AS row_key,
        COALESCE(m.msku_mapping_status, 'period_msku_missing') AS msku_mapping_status,
        COALESCE(m.associated_msku_count, 0) AS associated_msku_count,
        COALESCE(m.period_msku_count, 0) AS period_msku_count,
        COALESCE(m.current_enabled_msku_count, 0) AS current_enabled_msku_count,
        m.period_msku_candidates,
        m.current_msku_candidates,
        m.msku,
        m.asin
    FROM opt_db.tmp_spst_search_term_agg q
    LEFT JOIN opt_db.tmp_spst_account_current a ON a.profile_id = q.profile_id
    LEFT JOIN opt_db.tmp_spst_campaign_current c
        ON c.profile_id = q.profile_id AND c.campaign_id = q.campaign_id
    LEFT JOIN opt_db.tmp_spst_ad_group_current g
        ON g.profile_id = q.profile_id
       AND g.campaign_id = q.campaign_id
       AND g.ad_group_id = q.ad_group_id
    LEFT JOIN opt_db.tmp_spst_target_current tc
        ON tc.profile_id = q.profile_id
       AND tc.campaign_id = q.campaign_id
       AND tc.ad_group_id = q.ad_group_id
       AND tc.target_id = q.target_id
    LEFT JOIN opt_db.tmp_spst_group_product_mapping m
        ON m.profile_id = q.profile_id
       AND m.campaign_id = q.campaign_id
       AND m.ad_group_id = q.ad_group_id;

ALTER TABLE opt_db.tmp_spst_term_base ADD KEY idx_row_key (row_key);

ALTER TABLE opt_db.tmp_spst_term_base ADD KEY idx_existing (profile_id, ad_group_id, search_term_normalized(100));

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_existing;

CREATE TEMPORARY TABLE opt_db.tmp_spst_term_existing
ENGINE=InnoDB
AS
SELECT
        b.*,
        CASE
            WHEN b.search_term_type = 'product_target' THEN pte.existing_state
            ELSE ke.existing_state
        END AS existing_object_state
    FROM opt_db.tmp_spst_term_base b
    LEFT JOIN opt_db.tmp_spst_keyword_existing ke
        ON b.search_term_type = 'keyword'
       AND ke.profile_id = b.profile_id
       AND ke.ad_group_id = b.ad_group_id
       AND ke.object_normalized = b.search_term_normalized
    LEFT JOIN opt_db.tmp_spst_product_target_existing pte
        ON b.search_term_type = 'product_target'
       AND pte.profile_id = b.profile_id
       AND pte.ad_group_id = b.ad_group_id
       AND pte.asin = UPPER(TRIM(b.search_term));

ALTER TABLE opt_db.tmp_spst_term_existing ADD KEY idx_row_key (row_key);

ALTER TABLE opt_db.tmp_spst_term_existing ADD KEY idx_listing (seller_name, msku, country_code);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_context;

CREATE TEMPORARY TABLE opt_db.tmp_spst_term_context
ENGINE=InnoDB
AS
SELECT
        b.*,
        l.id AS listing_row_id,
        NULLIF(TRIM(l.seller_brand), '') AS product_brand,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(COALESCE(l.seller_brand, ''), '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        ))) AS product_brand_normalized,
        sba.store_brands_json,
        JSON_ARRAY(
            NULLIF(REGEXP_REPLACE(TRIM(l.small_1), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(l.small_2), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(l.small_3), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(l.small_4), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(l.small_5), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(t.leaf_category), '^\\s*[0-9]+\\s*-\\s*', ''), ''),
            NULLIF(REGEXP_REPLACE(TRIM(t.category), '^\\s*[0-9]+\\s*-\\s*', ''), '')
        ) AS leaf_categories_json,
        COALESCE(
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.first_order_time), ''), 10), '%Y-%m-%d'),
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.first_order_time), ''), 10), '%Y/%m/%d'),
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.on_sale_time), ''), 10), '%Y-%m-%d'),
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.on_sale_time), ''), 10), '%Y/%m/%d'),
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.open_date_display), ''), 10), '%Y-%m-%d'),
            STR_TO_DATE(LEFT(NULLIF(TRIM(l.open_date_display), ''), 10), '%Y/%m/%d')
        ) AS product_launch_date,
        CASE
            WHEN STR_TO_DATE(LEFT(NULLIF(TRIM(l.first_order_time), ''), 10), '%Y-%m-%d') IS NOT NULL
              OR STR_TO_DATE(LEFT(NULLIF(TRIM(l.first_order_time), ''), 10), '%Y/%m/%d') IS NOT NULL THEN 'first_order_time'
            WHEN STR_TO_DATE(LEFT(NULLIF(TRIM(l.on_sale_time), ''), 10), '%Y-%m-%d') IS NOT NULL
              OR STR_TO_DATE(LEFT(NULLIF(TRIM(l.on_sale_time), ''), 10), '%Y/%m/%d') IS NOT NULL THEN 'on_sale_time'
            WHEN STR_TO_DATE(LEFT(NULLIF(TRIM(l.open_date_display), ''), 10), '%Y-%m-%d') IS NOT NULL
              OR STR_TO_DATE(LEFT(NULLIF(TRIM(l.open_date_display), ''), 10), '%Y/%m/%d') IS NOT NULL THEN 'open_date_display'
            ELSE NULL
        END AS product_launch_date_source,
        REGEXP_REPLACE(LOWER(TRIM(COALESCE(b.seller_name, ''))), '-(eu-)?[a-z]{2}$', '') AS base_store_normalized,
        LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(l.small_1), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '),
            '[[:space:]]+', ' '
        ))) AS category_1_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(l.small_2), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_2_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(l.small_3), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_3_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(l.small_4), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_4_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(l.small_5), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_5_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(t.leaf_category), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_6_normalized,
        LOWER(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(COALESCE(REGEXP_REPLACE(TRIM(t.category), '^\\s*[0-9]+\\s*-\\s*', ''), ''), '_', ' '), '[^[:alnum:]]+', ' '), '[[:space:]]+', ' '))) AS category_7_normalized,
        REGEXP_REPLACE(TRIM(l.small_1), '^\\s*[0-9]+\\s*-\\s*', '') AS category_1,
        REGEXP_REPLACE(TRIM(l.small_2), '^\\s*[0-9]+\\s*-\\s*', '') AS category_2,
        REGEXP_REPLACE(TRIM(l.small_3), '^\\s*[0-9]+\\s*-\\s*', '') AS category_3,
        REGEXP_REPLACE(TRIM(l.small_4), '^\\s*[0-9]+\\s*-\\s*', '') AS category_4,
        REGEXP_REPLACE(TRIM(l.small_5), '^\\s*[0-9]+\\s*-\\s*', '') AS category_5,
        REGEXP_REPLACE(TRIM(t.leaf_category), '^\\s*[0-9]+\\s*-\\s*', '') AS category_6,
        REGEXP_REPLACE(TRIM(t.category), '^\\s*[0-9]+\\s*-\\s*', '') AS category_7
    FROM opt_db.tmp_spst_term_existing b
    LEFT JOIN opt_db.tmp_spst_listing_current l
        ON LOWER(TRIM(l.seller_name)) = LOWER(TRIM(b.seller_name))
       AND l.listing_country_code = b.country_code
       AND LOWER(TRIM(l.seller_sku)) = LOWER(TRIM(b.msku))
       AND b.msku_mapping_status = 'mapped'
    LEFT JOIN opt_db.tmp_spst_title_current t
        ON LOWER(TRIM(t.seller_name)) = LOWER(TRIM(b.seller_name))
       AND LOWER(TRIM(t.msku)) = LOWER(TRIM(b.msku))
       AND b.msku_mapping_status = 'mapped'
    LEFT JOIN opt_db.tmp_spst_store_brand_agg sba
        ON sba.store_name_normalized = REGEXP_REPLACE(LOWER(TRIM(COALESCE(b.seller_name, ''))), '-(eu-)?[a-z]{2}$', '');

ALTER TABLE opt_db.tmp_spst_term_context ADD KEY idx_row_key (row_key);

ALTER TABLE opt_db.tmp_spst_term_context ADD KEY idx_store (base_store_normalized(100));

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_match;

CREATE TEMPORARY TABLE opt_db.tmp_spst_store_brand_match
ENGINE=InnoDB
AS
SELECT
        c.row_key,
        MAX(s.brand_name) AS matched_store_brand
    FROM opt_db.tmp_spst_term_context c
    INNER JOIN opt_db.tmp_spst_store_brand_distinct s
        ON s.store_name_normalized = c.base_store_normalized
    WHERE NULLIF(c.product_brand_normalized, '') IS NULL
      AND NULLIF(s.brand_normalized, '') IS NOT NULL
      AND (
          (CHAR_LENGTH(s.brand_normalized) <= 2 AND c.search_term_normalized = s.brand_normalized)
          OR
          (CHAR_LENGTH(s.brand_normalized) > 2
           AND LOCATE(CONCAT(' ', s.brand_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
      )
    GROUP BY c.row_key;

ALTER TABLE opt_db.tmp_spst_store_brand_match ADD KEY idx_row_key (row_key);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_protection_eval;

CREATE TEMPORARY TABLE opt_db.tmp_spst_protection_eval
ENGINE=InnoDB
AS
SELECT
        c.*,
        sbm.matched_store_brand,
        CASE
            WHEN NULLIF(c.product_brand_normalized, '') IS NOT NULL
             AND ((CHAR_LENGTH(c.product_brand_normalized) <= 2 AND c.search_term_normalized = c.product_brand_normalized)
               OR (CHAR_LENGTH(c.product_brand_normalized) > 2
                  AND LOCATE(CONCAT(' ', c.product_brand_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0))
            THEN c.product_brand
            ELSE sbm.matched_store_brand
        END AS protection_brand,
        CASE
            WHEN NULLIF(c.category_1_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_1_normalized) <= 2 AND c.search_term_normalized = c.category_1_normalized)
                  OR (CHAR_LENGTH(c.category_1_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_1_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_1_normalized, ' ')) > 0)) THEN c.category_1
            WHEN NULLIF(c.category_2_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_2_normalized) <= 2 AND c.search_term_normalized = c.category_2_normalized)
                  OR (CHAR_LENGTH(c.category_2_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_2_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_2_normalized, ' ')) > 0)) THEN c.category_2
            WHEN NULLIF(c.category_3_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_3_normalized) <= 2 AND c.search_term_normalized = c.category_3_normalized)
                  OR (CHAR_LENGTH(c.category_3_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_3_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_3_normalized, ' ')) > 0)) THEN c.category_3
            WHEN NULLIF(c.category_4_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_4_normalized) <= 2 AND c.search_term_normalized = c.category_4_normalized)
                  OR (CHAR_LENGTH(c.category_4_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_4_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_4_normalized, ' ')) > 0)) THEN c.category_4
            WHEN NULLIF(c.category_5_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_5_normalized) <= 2 AND c.search_term_normalized = c.category_5_normalized)
                  OR (CHAR_LENGTH(c.category_5_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_5_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_5_normalized, ' ')) > 0)) THEN c.category_5
            WHEN NULLIF(c.category_6_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_6_normalized) <= 2 AND c.search_term_normalized = c.category_6_normalized)
                  OR (CHAR_LENGTH(c.category_6_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_6_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_6_normalized, ' ')) > 0)) THEN c.category_6
            WHEN NULLIF(c.category_7_normalized, '') IS NOT NULL AND
                 ((CHAR_LENGTH(c.category_7_normalized) <= 2 AND c.search_term_normalized = c.category_7_normalized)
                  OR (CHAR_LENGTH(c.category_7_normalized) > 2 AND LOCATE(CONCAT(' ', c.category_7_normalized, ' '), CONCAT(' ', c.search_term_normalized, ' ')) > 0)
                  OR (CHAR_LENGTH(c.search_term_normalized) > 2 AND LOCATE(CONCAT(' ', c.search_term_normalized, ' '), CONCAT(' ', c.category_7_normalized, ' ')) > 0)) THEN c.category_7
            ELSE NULL
        END AS protection_category,
        CASE
            WHEN c.msku_mapping_status <> 'mapped' THEN 0
            WHEN c.listing_row_id IS NULL THEN 0
            WHEN NULLIF(c.product_brand, '') IS NULL AND c.store_brands_json IS NULL THEN 0
            WHEN COALESCE(NULLIF(c.category_1_normalized, ''), NULLIF(c.category_2_normalized, ''),
                          NULLIF(c.category_3_normalized, ''), NULLIF(c.category_4_normalized, ''),
                          NULLIF(c.category_5_normalized, ''), NULLIF(c.category_6_normalized, ''),
                          NULLIF(c.category_7_normalized, '')) IS NULL THEN 0
            WHEN c.product_launch_date IS NULL OR c.product_launch_date > @snapshot_date THEN 0
            ELSE 1
        END AS term_protection_complete,
        CASE
            WHEN c.msku_mapping_status <> 'mapped' THEN JSON_ARRAY(c.msku_mapping_status)
            WHEN c.listing_row_id IS NULL THEN JSON_ARRAY('term_protection_context_missing')
            ELSE JSON_MERGE_PRESERVE(
                IF(NULLIF(c.product_brand, '') IS NULL AND c.store_brands_json IS NULL,
                   JSON_ARRAY('brand_context_missing'), JSON_ARRAY()),
                IF(COALESCE(NULLIF(c.category_1_normalized, ''), NULLIF(c.category_2_normalized, ''),
                            NULLIF(c.category_3_normalized, ''), NULLIF(c.category_4_normalized, ''),
                            NULLIF(c.category_5_normalized, ''), NULLIF(c.category_6_normalized, ''),
                            NULLIF(c.category_7_normalized, '')) IS NULL,
                   JSON_ARRAY('category_context_missing'), JSON_ARRAY()),
                IF(c.product_launch_date IS NULL, JSON_ARRAY('launch_date_missing'), JSON_ARRAY()),
                IF(c.product_launch_date > @snapshot_date, JSON_ARRAY('launch_date_invalid'), JSON_ARRAY())
            )
        END AS protection_missing_codes
    FROM opt_db.tmp_spst_term_context c
    LEFT JOIN opt_db.tmp_spst_store_brand_match sbm ON sbm.row_key = c.row_key;

ALTER TABLE opt_db.tmp_spst_protection_eval ADD KEY idx_row_key (row_key);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_rate_eval;

CREATE TEMPORARY TABLE opt_db.tmp_spst_rate_eval
ENGINE=InnoDB
AS
SELECT
        p.*,
        p.clicks / NULLIF(p.impressions, 0) AS ctr,
        p.cost / NULLIF(p.clicks, 0) AS cpc,
        p.orders_1d / NULLIF(p.clicks, 0) AS cvr_1d,
        p.orders_7d / NULLIF(p.clicks, 0) AS cvr_7d,
        p.orders_14d / NULLIF(p.clicks, 0) AS cvr_14d,
        p.orders_30d / NULLIF(p.clicks, 0) AS cvr_30d,
        p.cost / NULLIF(p.sales_1d, 0) AS acos_1d,
        p.cost / NULLIF(p.sales_7d, 0) AS acos_7d,
        p.cost / NULLIF(p.sales_14d, 0) AS acos_14d,
        p.cost / NULLIF(p.sales_30d, 0) AS acos_30d,
        p.sales_1d / NULLIF(p.cost, 0) AS roas_1d,
        p.sales_7d / NULLIF(p.cost, 0) AS roas_7d,
        p.sales_14d / NULLIF(p.cost, 0) AS roas_14d,
        p.sales_30d / NULLIF(p.cost, 0) AS roas_30d
    FROM opt_db.tmp_spst_protection_eval p;

ALTER TABLE opt_db.tmp_spst_rate_eval ADD KEY idx_row_key (row_key);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_recommendation_eval;

CREATE TEMPORARY TABLE opt_db.tmp_spst_recommendation_eval
ENGINE=InnoDB
AS
SELECT
        r.*,
        CASE
            WHEN r.existing_object_state = 'enabled' THEN 'existing'
            WHEN r.existing_object_state = 'inactive' THEN 'existing_inactive'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.10 THEN 'recommended'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.15 THEN 'recommended'
            ELSE 'observe'
        END AS add_status,
        CASE
            WHEN r.existing_object_state IS NOT NULL THEN 'none'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.10 THEN 'highest'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.15 THEN 'medium'
            ELSE 'none'
        END AS add_priority,
        CASE
            WHEN r.existing_object_state = 'enabled' THEN 'existing_enabled'
            WHEN r.existing_object_state = 'inactive' THEN 'existing_inactive'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.10 THEN 'orders_ge_10_acos_le_10'
            WHEN r.orders_7d >= 10 AND r.acos_7d <= 0.15 THEN 'orders_ge_10_acos_le_15'
            ELSE 'threshold_not_met'
        END AS add_primary_reason,
        CASE
            WHEN r.clicks < 10 OR r.orders_7d <> 0 THEN 'observe'
            WHEN r.msku_mapping_status <> 'mapped' THEN 'manual_review'
            WHEN r.term_protection_complete = 0 THEN 'manual_review'
            WHEN r.protection_brand IS NOT NULL
              OR r.protection_category IS NOT NULL
              OR (r.product_launch_date IS NOT NULL
                  AND r.product_launch_date <= @snapshot_date
                  AND DATEDIFF(@snapshot_date, r.product_launch_date) <= 90)
            THEN 'manual_review'
            ELSE 'recommended'
        END AS negative_status,
        CASE
            WHEN r.clicks >= 10 AND r.orders_7d = 0 THEN 'high'
            ELSE 'none'
        END AS negative_priority
    FROM opt_db.tmp_spst_rate_eval r;

ALTER TABLE opt_db.tmp_spst_recommendation_eval ADD KEY idx_row_key (row_key);

DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_final_eval;

CREATE TEMPORARY TABLE opt_db.tmp_spst_final_eval
ENGINE=InnoDB
AS
SELECT
        r.*,
        CASE
            WHEN r.clicks < 10 OR r.orders_7d <> 0 THEN JSON_ARRAY('threshold_not_met')
            WHEN r.msku_mapping_status <> 'mapped' THEN JSON_ARRAY(r.msku_mapping_status)
            WHEN r.term_protection_complete = 0 THEN r.protection_missing_codes
            ELSE JSON_MERGE_PRESERVE(
                IF(r.protection_brand IS NOT NULL, JSON_ARRAY('brand_term'), JSON_ARRAY()),
                IF(r.protection_category IS NOT NULL, JSON_ARRAY('core_category_term'), JSON_ARRAY()),
                IF(r.product_launch_date IS NOT NULL
                   AND r.product_launch_date <= @snapshot_date
                   AND DATEDIFF(@snapshot_date, r.product_launch_date) <= 90,
                   JSON_ARRAY('new_product_term'), JSON_ARRAY()),
                IF(r.protection_brand IS NULL
                   AND r.protection_category IS NULL
                   AND NOT (r.product_launch_date IS NOT NULL
                            AND r.product_launch_date <= @snapshot_date
                            AND DATEDIFF(@snapshot_date, r.product_launch_date) <= 90),
                   JSON_ARRAY('clicks_ge_10_orders_zero'), JSON_ARRAY())
            )
        END AS negative_reason_codes
    FROM opt_db.tmp_spst_recommendation_eval r;

ALTER TABLE opt_db.tmp_spst_final_eval ADD KEY idx_row_key (row_key);

/* ============================== 原子替换每日快照 ============================== */

START TRANSACTION;

DELETE FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
  AND @source_complete = 1;

INSERT INTO dws_datasync.dws_sp_search_term_analysis_daily (
    snapshot_date, row_key, rule_version, mature_start, mature_end,
    source_search_term_days, source_product_ad_days,
    profile_id, sid, seller_name, country_code, currency_code,
    campaign_id, campaign_name_current, campaign_state_current,
    targeting_type, targeting_type_name, is_auto_campaign, is_manual_campaign,
    daily_budget_current, bidding_strategy_current,
    ad_group_id, ad_group_name_current, ad_group_state_current, default_bid_current,
    target_id, target_text, target_state_current, match_type,
    search_term, search_term_normalized, search_term_type, existing_object_state,
    msku, asin, msku_mapping_status, associated_msku_count,
    period_msku_count, current_enabled_msku_count,
    period_msku_candidates, current_msku_candidates,
    product_brand, store_brands_json, leaf_categories_json,
    product_launch_date, product_launch_date_source, product_age_days,
    term_protection_complete, protection_missing_codes,
    is_brand_term, is_core_category_term, is_new_product_term,
    protection_brand, protection_category,
    impressions, clicks, cost,
    orders_1d, orders_7d, orders_14d, orders_30d,
    same_orders_1d, same_orders_7d, same_orders_14d, same_orders_30d,
    sales_1d, sales_7d, sales_14d, sales_30d,
    same_sales_1d, same_sales_7d, same_sales_14d, same_sales_30d,
    units_1d, units_7d, units_14d, units_30d,
    same_units_1d, same_units_7d, same_units_14d, same_units_30d,
    ctr, cpc, cvr_1d, cvr_7d, cvr_14d, cvr_30d,
    acos_1d, acos_7d, acos_14d, acos_30d,
    roas_1d, roas_7d, roas_14d, roas_30d,
    attribution_1d_mature, attribution_7d_mature,
    attribution_14d_mature, attribution_30d_mature,
    add_status, add_priority, add_suggestion_type, add_suggestion_value,
    add_reason_codes, is_add_recommended,
    negative_status, negative_priority, negative_suggestion_type,
    negative_suggestion_value, negative_reason_codes,
    is_negative_recommended, needs_manual_review, source_latest_create_time
)
SELECT
    @snapshot_date,
    f.row_key,
    @rule_version,
    @mature_start,
    @mature_end,
    @source_search_term_days,
    @source_product_ad_days,
    f.profile_id,
    f.sid,
    f.seller_name,
    f.country_code,
    f.currency_code,
    f.campaign_id,
    f.campaign_name_current,
    f.campaign_state_current,
    f.targeting_type,
    CASE LOWER(COALESCE(f.targeting_type, ''))
        WHEN 'auto' THEN '自动广告'
        WHEN 'manual' THEN '手工广告'
        ELSE '未知'
    END,
    (LOWER(COALESCE(f.targeting_type, '')) = 'auto'),
    (LOWER(COALESCE(f.targeting_type, '')) = 'manual'),
    f.daily_budget_current,
    f.bidding_strategy_current,
    f.ad_group_id,
    f.ad_group_name_current,
    f.ad_group_state_current,
    f.default_bid_current,
    f.target_id,
    f.target_text,
    f.target_state_current,
    f.match_type,
    f.search_term,
    f.search_term_normalized,
    f.search_term_type,
    f.existing_object_state,
    f.msku,
    f.asin,
    f.msku_mapping_status,
    f.associated_msku_count,
    f.period_msku_count,
    f.current_enabled_msku_count,
    f.period_msku_candidates,
    f.current_msku_candidates,
    f.product_brand,
    f.store_brands_json,
    f.leaf_categories_json,
    f.product_launch_date,
    f.product_launch_date_source,
    CASE WHEN f.product_launch_date IS NOT NULL AND f.product_launch_date <= @snapshot_date
         THEN DATEDIFF(@snapshot_date, f.product_launch_date) END,
    f.term_protection_complete,
    f.protection_missing_codes,
    (f.protection_brand IS NOT NULL),
    (f.protection_category IS NOT NULL),
    (f.product_launch_date IS NOT NULL
     AND f.product_launch_date <= @snapshot_date
     AND DATEDIFF(@snapshot_date, f.product_launch_date) <= 90),
    f.protection_brand,
    f.protection_category,
    f.impressions,
    f.clicks,
    f.cost,
    f.orders_1d, f.orders_7d, f.orders_14d, f.orders_30d,
    f.same_orders_1d, f.same_orders_7d, f.same_orders_14d, f.same_orders_30d,
    f.sales_1d, f.sales_7d, f.sales_14d, f.sales_30d,
    f.same_sales_1d, f.same_sales_7d, f.same_sales_14d, f.same_sales_30d,
    f.units_1d, f.units_7d, f.units_14d, f.units_30d,
    f.same_units_1d, f.same_units_7d, f.same_units_14d, f.same_units_30d,
    f.ctr, f.cpc,
    f.cvr_1d, f.cvr_7d, f.cvr_14d, f.cvr_30d,
    f.acos_1d, f.acos_7d, f.acos_14d, f.acos_30d,
    f.roas_1d, f.roas_7d, f.roas_14d, f.roas_30d,
    1, 1, 0, 0,
    f.add_status,
    f.add_priority,
    IF(f.search_term_type = 'product_target', 'product_target', 'exact_keyword'),
    f.search_term,
    JSON_MERGE_PRESERVE(
        JSON_ARRAY(f.add_primary_reason),
        IF(f.msku_mapping_status <> 'mapped', JSON_ARRAY(f.msku_mapping_status), JSON_ARRAY())
    ),
    (f.add_status = 'recommended'),
    f.negative_status,
    f.negative_priority,
    IF(f.search_term_type = 'product_target', 'negative_product_target', 'negative_exact'),
    f.search_term,
    f.negative_reason_codes,
    (f.negative_status = 'recommended'),
    (f.negative_status = 'manual_review'),
    f.source_latest_create_time
FROM opt_db.tmp_spst_final_eval f
WHERE @source_complete = 1;

/*
写入当天快照后按快照份数清理：
- 1～7 个不同 snapshot_date：全部保留；
- 第 8 个及以后：只保留日期最新的 7 份，删除其余历史。
*/
DELETE FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE @source_complete = 1
  AND snapshot_date NOT IN (
      SELECT snapshot_date
      FROM (
          SELECT DISTINCT snapshot_date
          FROM dws_datasync.dws_sp_search_term_analysis_daily
          ORDER BY snapshot_date DESC
          LIMIT 7
      ) AS latest_seven_snapshots
  );

COMMIT;

/* 临时计算表只在当前连接有效；显式释放，避免长连接占用空间。 */
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_product_source;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_search_source;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_final_eval;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_recommendation_eval;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_rate_eval;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_protection_eval;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_match;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_context;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_existing;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_term_base;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_agg;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_store_brand_distinct;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_title_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_title_ranked;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_latest_title_run;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_listing_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_listing_ranked;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_product_target_existing;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_keyword_existing;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_group_product_mapping;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_group_keys;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_current_product;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_period_product;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_search_term_agg;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_target_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_ad_group_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_ad_group_ranked;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_campaign_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_campaign_ranked;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_account_current;
DROP TEMPORARY TABLE IF EXISTS opt_db.tmp_spst_account_ranked;

/* ============================== 刷新后质量检查 ============================== */

-- 1. 快照行数、业务键唯一性及金额汇总。
SELECT
    snapshot_date,
    COUNT(*) AS result_rows,
    COUNT(DISTINCT row_key) AS distinct_row_keys,
    SUM(impressions) AS impressions,
    SUM(clicks) AS clicks,
    SUM(cost) AS cost,
    SUM(orders_7d) AS orders_7d,
    SUM(sales_7d) AS sales_7d
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY snapshot_date;

-- 2. 与源搜索词报表一次扫描完成全部指标对账。all_metrics_match应为1，差额JSON各项应为0。
WITH source_recon AS (
    SELECT
        COALESCE(SUM(impressions), 0) impressions, COALESCE(SUM(clicks), 0) clicks,
        COALESCE(SUM(cost), 0) cost,
        COALESCE(SUM(orders_1d), 0) orders_1d, COALESCE(SUM(orders_7d), 0) orders_7d,
        COALESCE(SUM(orders_14d), 0) orders_14d, COALESCE(SUM(orders_30d), 0) orders_30d,
        COALESCE(SUM(same_orders_1d), 0) same_orders_1d, COALESCE(SUM(same_orders_7d), 0) same_orders_7d,
        COALESCE(SUM(same_orders_14d), 0) same_orders_14d, COALESCE(SUM(same_orders_30d), 0) same_orders_30d,
        COALESCE(SUM(sales_1d), 0) sales_1d, COALESCE(SUM(sales_7d), 0) sales_7d,
        COALESCE(SUM(sales_14d), 0) sales_14d, COALESCE(SUM(sales_30d), 0) sales_30d,
        COALESCE(SUM(same_sales_1d), 0) same_sales_1d, COALESCE(SUM(same_sales_7d), 0) same_sales_7d,
        COALESCE(SUM(same_sales_14d), 0) same_sales_14d, COALESCE(SUM(same_sales_30d), 0) same_sales_30d,
        COALESCE(SUM(units_1d), 0) units_1d, COALESCE(SUM(units_7d), 0) units_7d,
        COALESCE(SUM(units_14d), 0) units_14d, COALESCE(SUM(units_30d), 0) units_30d,
        COALESCE(SUM(same_units_1d), 0) same_units_1d, COALESCE(SUM(same_units_7d), 0) same_units_7d,
        COALESCE(SUM(same_units_14d), 0) same_units_14d, COALESCE(SUM(same_units_30d), 0) same_units_30d
    FROM dwd_datasync.lx_advertising_sp_query_word_reports
    WHERE report_date BETWEEN DATE_FORMAT(@mature_start, '%Y-%m-%d') AND DATE_FORMAT(@mature_end, '%Y-%m-%d')
      AND profile_id IS NOT NULL AND campaign_id IS NOT NULL AND ad_group_id IS NOT NULL
      AND NULLIF(TRIM(query), '') IS NOT NULL
),
result_recon AS (
    SELECT
        COALESCE(SUM(impressions), 0) impressions, COALESCE(SUM(clicks), 0) clicks,
        COALESCE(SUM(cost), 0) cost,
        COALESCE(SUM(orders_1d), 0) orders_1d, COALESCE(SUM(orders_7d), 0) orders_7d,
        COALESCE(SUM(orders_14d), 0) orders_14d, COALESCE(SUM(orders_30d), 0) orders_30d,
        COALESCE(SUM(same_orders_1d), 0) same_orders_1d, COALESCE(SUM(same_orders_7d), 0) same_orders_7d,
        COALESCE(SUM(same_orders_14d), 0) same_orders_14d, COALESCE(SUM(same_orders_30d), 0) same_orders_30d,
        COALESCE(SUM(sales_1d), 0) sales_1d, COALESCE(SUM(sales_7d), 0) sales_7d,
        COALESCE(SUM(sales_14d), 0) sales_14d, COALESCE(SUM(sales_30d), 0) sales_30d,
        COALESCE(SUM(same_sales_1d), 0) same_sales_1d, COALESCE(SUM(same_sales_7d), 0) same_sales_7d,
        COALESCE(SUM(same_sales_14d), 0) same_sales_14d, COALESCE(SUM(same_sales_30d), 0) same_sales_30d,
        COALESCE(SUM(units_1d), 0) units_1d, COALESCE(SUM(units_7d), 0) units_7d,
        COALESCE(SUM(units_14d), 0) units_14d, COALESCE(SUM(units_30d), 0) units_30d,
        COALESCE(SUM(same_units_1d), 0) same_units_1d, COALESCE(SUM(same_units_7d), 0) same_units_7d,
        COALESCE(SUM(same_units_14d), 0) same_units_14d, COALESCE(SUM(same_units_30d), 0) same_units_30d
    FROM dws_datasync.dws_sp_search_term_analysis_daily
    WHERE snapshot_date = @snapshot_date
)
SELECT
    (
        s.impressions = r.impressions AND s.clicks = r.clicks AND s.cost = r.cost
        AND s.orders_1d = r.orders_1d AND s.orders_7d = r.orders_7d
        AND s.orders_14d = r.orders_14d AND s.orders_30d = r.orders_30d
        AND s.same_orders_1d = r.same_orders_1d AND s.same_orders_7d = r.same_orders_7d
        AND s.same_orders_14d = r.same_orders_14d AND s.same_orders_30d = r.same_orders_30d
        AND s.sales_1d = r.sales_1d AND s.sales_7d = r.sales_7d
        AND s.sales_14d = r.sales_14d AND s.sales_30d = r.sales_30d
        AND s.same_sales_1d = r.same_sales_1d AND s.same_sales_7d = r.same_sales_7d
        AND s.same_sales_14d = r.same_sales_14d AND s.same_sales_30d = r.same_sales_30d
        AND s.units_1d = r.units_1d AND s.units_7d = r.units_7d
        AND s.units_14d = r.units_14d AND s.units_30d = r.units_30d
        AND s.same_units_1d = r.same_units_1d AND s.same_units_7d = r.same_units_7d
        AND s.same_units_14d = r.same_units_14d AND s.same_units_30d = r.same_units_30d
    ) AS all_metrics_match,
    JSON_OBJECT(
        'impressions', r.impressions - s.impressions, 'clicks', r.clicks - s.clicks, 'cost', r.cost - s.cost,
        'orders_1d', r.orders_1d - s.orders_1d, 'orders_7d', r.orders_7d - s.orders_7d,
        'orders_14d', r.orders_14d - s.orders_14d, 'orders_30d', r.orders_30d - s.orders_30d,
        'same_orders_1d', r.same_orders_1d - s.same_orders_1d, 'same_orders_7d', r.same_orders_7d - s.same_orders_7d,
        'same_orders_14d', r.same_orders_14d - s.same_orders_14d, 'same_orders_30d', r.same_orders_30d - s.same_orders_30d,
        'sales_1d', r.sales_1d - s.sales_1d, 'sales_7d', r.sales_7d - s.sales_7d,
        'sales_14d', r.sales_14d - s.sales_14d, 'sales_30d', r.sales_30d - s.sales_30d,
        'same_sales_1d', r.same_sales_1d - s.same_sales_1d, 'same_sales_7d', r.same_sales_7d - s.same_sales_7d,
        'same_sales_14d', r.same_sales_14d - s.same_sales_14d, 'same_sales_30d', r.same_sales_30d - s.same_sales_30d,
        'units_1d', r.units_1d - s.units_1d, 'units_7d', r.units_7d - s.units_7d,
        'units_14d', r.units_14d - s.units_14d, 'units_30d', r.units_30d - s.units_30d,
        'same_units_1d', r.same_units_1d - s.same_units_1d, 'same_units_7d', r.same_units_7d - s.same_units_7d,
        'same_units_14d', r.same_units_14d - s.same_units_14d, 'same_units_30d', r.same_units_30d - s.same_units_30d
    ) AS metric_differences
FROM source_recon s
CROSS JOIN result_recon r;

-- 3. 自动/手工广告分布及源字段异常值。
SELECT targeting_type, targeting_type_name, COUNT(*) AS rows_count,
       SUM(cost) AS cost, SUM(sales_7d) AS sales_7d
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY targeting_type, targeting_type_name;

-- 4. MSKU映射结果分布。
SELECT msku_mapping_status, COUNT(*) AS rows_count,
       SUM(cost) AS cost, SUM(orders_7d) AS orders_7d
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY msku_mapping_status;

-- 5. 加词和否词建议分布。
SELECT 'add' AS recommendation_type, add_status AS status, add_priority AS priority,
       COUNT(*) AS rows_count
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY add_status, add_priority
UNION ALL
SELECT 'negative', negative_status, negative_priority, COUNT(*)
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY negative_status, negative_priority;

-- 6. 保护规则分布。
SELECT
    term_protection_complete,
    is_brand_term,
    is_core_category_term,
    is_new_product_term,
    needs_manual_review,
    COUNT(*) AS rows_count
FROM dws_datasync.dws_sp_search_term_analysis_daily
WHERE snapshot_date = @snapshot_date
GROUP BY term_protection_complete, is_brand_term,
         is_core_category_term, is_new_product_term, needs_manual_review;
