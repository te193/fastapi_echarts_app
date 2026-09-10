/*
用途：创建并定义 SP 竞价对象每日快照刷新存储过程。
数据库：MySQL 8.0
目标表：dws_datasync.dws_sp_bid_object_snapshot_daily

注意：
1. 本文件只定义存储过程，不自动调用，不创建 MySQL Event。
2. 所有生产输入均来自远端 dwd_datasync、ods_datasync、dws_datasync、temporary_dwd。
3. 默认使用关键词、广告组和商品广告报表的最大共同日期。
4. 成熟窗口跳过最近7天后取30个完整自然日。
*/

DELIMITER $$

DROP PROCEDURE IF EXISTS dws_datasync.sp_refresh_sp_bid_object_snapshot_daily$$

CREATE PROCEDURE dws_datasync.sp_refresh_sp_bid_object_snapshot_daily(
    IN p_snapshot_date DATE
)
SQL SECURITY INVOKER
proc: BEGIN
    DECLARE v_snapshot_date DATE;
    DECLARE v_mature_start DATE;
    DECLARE v_mature_end DATE;
    DECLARE v_keyword_days INT DEFAULT 0;
    DECLARE v_ad_group_days INT DEFAULT 0;
    DECLARE v_product_ad_days INT DEFAULT 0;
    DECLARE v_lock_acquired INT DEFAULT 0;
    DECLARE v_rule_version VARCHAR(100) DEFAULT 'sp-bid-object-remote-v1';

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_final;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_scored;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_eval;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_enriched;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_limit_price;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_listing;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_spend;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_budget;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_fx;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_benchmark;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_p75;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_cvr_ranked;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_product;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_map;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_period_product;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_current_product;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_raw;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_auto_metric;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_metric;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_current;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_ad_group_current;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_campaign_current;
        DROP TEMPORARY TABLE IF EXISTS tmp_spbo_account_current;
        IF v_lock_acquired = 1 THEN
            DO RELEASE_LOCK('dws_datasync.sp_refresh_sp_bid_object_snapshot_daily');
        END IF;
        RESIGNAL;
    END;

    SELECT GET_LOCK('dws_datasync.sp_refresh_sp_bid_object_snapshot_daily', 0)
      INTO v_lock_acquired;
    IF v_lock_acquired <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'SP竞价对象宽表正在刷新，请稍后重试';
    END IF;

    SET v_snapshot_date = COALESCE(
        p_snapshot_date,
        (
            SELECT LEAST(
                STR_TO_DATE(MAX(report_date), '%Y-%m-%d'),
                (SELECT STR_TO_DATE(MAX(report_date), '%Y-%m-%d')
                   FROM ods_datasync.lx_advertising_sp_ad_group_reports
                  WHERE COALESCE(delete_flag, 0) = 0),
                (SELECT STR_TO_DATE(MAX(report_date), '%Y-%m-%d')
                   FROM ods_datasync.lx_advertising_sp_product_ad_reports
                  WHERE COALESCE(delete_flag, 0) = 0)
            )
            FROM ods_datasync.lx_advertising_sp_keyword_reports
            WHERE COALESCE(delete_flag, 0) = 0
        )
    );

    IF v_snapshot_date IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '远端SP广告报表不存在可用截止日期';
    END IF;

    SET v_mature_end = DATE_SUB(v_snapshot_date, INTERVAL 7 DAY);
    SET v_mature_start = DATE_SUB(v_mature_end, INTERVAL 29 DAY);

    SELECT COUNT(DISTINCT report_date)
      INTO v_keyword_days
     FROM ods_datasync.lx_advertising_sp_keyword_reports
     WHERE report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                           AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
       AND COALESCE(delete_flag, 0) = 0
       AND profile_id IS NOT NULL
       AND campaign_id IS NOT NULL
       AND ad_group_id IS NOT NULL
       AND keyword_id IS NOT NULL;

    SELECT COUNT(DISTINCT report_date)
      INTO v_ad_group_days
     FROM ods_datasync.lx_advertising_sp_ad_group_reports
     WHERE report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                           AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
       AND COALESCE(delete_flag, 0) = 0
       AND profile_id IS NOT NULL
       AND campaign_id IS NOT NULL
       AND ad_group_id IS NOT NULL;

    SELECT COUNT(DISTINCT report_date)
      INTO v_product_ad_days
     FROM ods_datasync.lx_advertising_sp_product_ad_reports
     WHERE report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                           AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
       AND COALESCE(delete_flag, 0) = 0
       AND profile_id IS NOT NULL
       AND campaign_id IS NOT NULL
       AND ad_group_id IS NOT NULL;

    IF v_keyword_days <> 30 OR v_ad_group_days <> 30 OR v_product_ad_days <> 30 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '成熟30天窗口不完整，本次不刷新宽表';
    END IF;

    /* 最新账号、活动、广告组和关键词维度。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_account_current;
    CREATE TEMPORARY TABLE tmp_spbo_account_current ENGINE=InnoDB AS
    SELECT profile_id, sid, name AS account_name, country_code, currency_code
    FROM (
        SELECT a.*,
               ROW_NUMBER() OVER (
                   PARTITION BY a.profile_id
                   ORDER BY COALESCE(a.update_time, a.create_time) DESC, a.id DESC
               ) AS rn
        FROM ods_datasync.lx_advertising_account_list a
        WHERE COALESCE(a.delete_flag, 0) = 0
          AND a.profile_id IS NOT NULL
    ) ranked
    WHERE rn = 1;
    ALTER TABLE tmp_spbo_account_current ADD PRIMARY KEY (profile_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_campaign_current;
    CREATE TEMPORARY TABLE tmp_spbo_campaign_current ENGINE=InnoDB AS
    SELECT
        profile_id, campaign_id, name, campaign_type,
        LOWER(COALESCE(targeting_type, 'unknown')) AS targeting_type,
        portfolio_id, daily_budget,
        CASE WHEN JSON_VALID(bidding)
             THEN JSON_UNQUOTE(JSON_EXTRACT(bidding, '$.strategy')) END AS bidding_strategy,
        state, serving_status,
        (
            SELECT MAX(a.percentage)
            FROM JSON_TABLE(
                CASE WHEN JSON_VALID(bidding) THEN bidding
                     ELSE JSON_OBJECT('adjustments', JSON_ARRAY()) END,
                '$.adjustments[*]' COLUMNS (
                    predicate VARCHAR(100) PATH '$.predicate',
                    percentage DECIMAL(10,4) PATH '$.percentage'
                )
            ) AS a
            WHERE a.predicate = 'placementTop'
        ) AS placement_top_percentage,
        (
            SELECT MAX(a.percentage)
            FROM JSON_TABLE(
                CASE WHEN JSON_VALID(bidding) THEN bidding
                     ELSE JSON_OBJECT('adjustments', JSON_ARRAY()) END,
                '$.adjustments[*]' COLUMNS (
                    predicate VARCHAR(100) PATH '$.predicate',
                    percentage DECIMAL(10,4) PATH '$.percentage'
                )
            ) AS a
            WHERE a.predicate = 'placementProductPage'
        ) AS placement_product_page_percentage,
        (
            SELECT MAX(a.percentage)
            FROM JSON_TABLE(
                CASE WHEN JSON_VALID(bidding) THEN bidding
                     ELSE JSON_OBJECT('adjustments', JSON_ARRAY()) END,
                '$.adjustments[*]' COLUMNS (
                    predicate VARCHAR(100) PATH '$.predicate',
                    percentage DECIMAL(10,4) PATH '$.percentage'
                )
            ) AS a
            WHERE a.predicate = 'placementRestOfSearch'
        ) AS placement_rest_of_search_percentage,
        COALESCE(
            update_time,
            FROM_UNIXTIME(NULLIF(CAST(last_updated_date AS UNSIGNED), 0) / 1000),
            create_time
        ) AS source_updated_at
    FROM (
        SELECT c.*,
               ROW_NUMBER() OVER (
                   PARTITION BY c.profile_id, c.campaign_id
                   ORDER BY COALESCE(
                       c.update_time,
                       FROM_UNIXTIME(NULLIF(CAST(c.last_updated_date AS UNSIGNED), 0) / 1000),
                       c.create_time
                   ) DESC, c.id DESC
               ) AS rn
        FROM ods_datasync.lx_advertising_sp_campaigns c
        WHERE COALESCE(c.delete_flag, 0) = 0
          AND c.profile_id IS NOT NULL
          AND c.campaign_id IS NOT NULL
    ) ranked
    WHERE rn = 1;
    ALTER TABLE tmp_spbo_campaign_current
        ADD PRIMARY KEY (profile_id, campaign_id),
        ADD KEY idx_campaign_type (targeting_type);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_ad_group_current;
    CREATE TEMPORARY TABLE tmp_spbo_ad_group_current ENGINE=InnoDB AS
    SELECT
        profile_id, campaign_id, ad_group_id, name, default_bid,
        state, serving_status,
        COALESCE(
            update_time,
            FROM_UNIXTIME(NULLIF(CAST(last_updated_date AS UNSIGNED), 0) / 1000),
            create_time
        ) AS source_updated_at
    FROM (
        SELECT g.*,
               ROW_NUMBER() OVER (
                   PARTITION BY g.profile_id, g.campaign_id, g.ad_group_id
                   ORDER BY COALESCE(
                       g.update_time,
                       FROM_UNIXTIME(NULLIF(CAST(g.last_updated_date AS UNSIGNED), 0) / 1000),
                       g.create_time
                   ) DESC, g.id DESC
               ) AS rn
        FROM ods_datasync.lx_advertising_sp_ad_groups g
        WHERE COALESCE(g.delete_flag, 0) = 0
          AND g.profile_id IS NOT NULL
          AND g.campaign_id IS NOT NULL
          AND g.ad_group_id IS NOT NULL
    ) ranked
    WHERE rn = 1;
    ALTER TABLE tmp_spbo_ad_group_current
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_current;
    CREATE TEMPORARY TABLE tmp_spbo_keyword_current ENGINE=InnoDB AS
    SELECT
        profile_id, campaign_id, ad_group_id, keyword_id,
        keyword_text, bid, state, match_type, serving_status,
        COALESCE(
            update_time,
            FROM_UNIXTIME(NULLIF(CAST(last_updated_date AS UNSIGNED), 0) / 1000),
            create_time
        ) AS source_updated_at
    FROM (
        SELECT k.*,
               ROW_NUMBER() OVER (
                   PARTITION BY k.profile_id, k.campaign_id, k.ad_group_id, k.keyword_id
                   ORDER BY COALESCE(
                       k.update_time,
                       FROM_UNIXTIME(NULLIF(CAST(k.last_updated_date AS UNSIGNED), 0) / 1000),
                       k.create_time
                   ) DESC, k.id DESC
               ) AS rn
        FROM ods_datasync.lx_advertising_sp_keywords k
        WHERE COALESCE(k.delete_flag, 0) = 0
          AND k.profile_id IS NOT NULL
          AND k.campaign_id IS NOT NULL
          AND k.ad_group_id IS NOT NULL
          AND k.keyword_id IS NOT NULL
    ) ranked
    WHERE rn = 1;
    ALTER TABLE tmp_spbo_keyword_current
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, keyword_id);

    /* 成熟30天竞价对象表现。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_metric;
    CREATE TEMPORARY TABLE tmp_spbo_keyword_metric ENGINE=InnoDB AS
    SELECT
        o.profile_id, o.campaign_id, o.ad_group_id, o.keyword_id,
        MAX(o.seller_name) AS report_seller_name,
        SUM(COALESCE(o.impressions, 0)) AS impressions,
        SUM(COALESCE(o.clicks, 0)) AS clicks,
        SUM(COALESCE(o.cost, 0)) AS cost,
        SUM(COALESCE(o.orders_7d, 0)) AS orders,
        SUM(COALESCE(o.sales_7d, 0)) AS sales,
        SUM(COALESCE(o.orders_1d, 0)) AS attributed_orders_1d,
        SUM(COALESCE(o.orders_7d, 0)) AS attributed_orders_7d,
        SUM(COALESCE(o.orders_14d, 0)) AS attributed_orders_14d,
        SUM(COALESCE(o.orders_30d, 0)) AS attributed_orders_30d,
        SUM(COALESCE(o.sales_1d, 0)) AS attributed_sales_1d,
        SUM(COALESCE(o.sales_7d, 0)) AS attributed_sales_7d,
        SUM(COALESCE(o.sales_14d, 0)) AS attributed_sales_14d,
        SUM(COALESCE(o.sales_30d, 0)) AS attributed_sales_30d,
        SUM(COALESCE(o.units_1d, 0)) AS attributed_units_1d,
        SUM(COALESCE(o.units_7d, 0)) AS attributed_units_7d,
        SUM(COALESCE(o.units_14d, 0)) AS attributed_units_14d,
        SUM(COALESCE(o.units_30d, 0)) AS attributed_units_30d,
        SUM(COALESCE(o.same_orders_1d, 0)) AS same_sku_attributed_orders_1d,
        SUM(COALESCE(o.same_orders_7d, 0)) AS same_sku_attributed_orders_7d,
        SUM(COALESCE(o.same_orders_14d, 0)) AS same_sku_attributed_orders_14d,
        SUM(COALESCE(o.same_orders_30d, 0)) AS same_sku_attributed_orders_30d,
        SUM(COALESCE(o.same_sales_1d, 0)) AS same_sku_attributed_sales_1d,
        SUM(COALESCE(o.same_sales_7d, 0)) AS same_sku_attributed_sales_7d,
        SUM(COALESCE(o.same_sales_14d, 0)) AS same_sku_attributed_sales_14d,
        SUM(COALESCE(o.same_sales_30d, 0)) AS same_sku_attributed_sales_30d,
        SUM(COALESCE(o.same_units_1d, 0)) AS same_sku_attributed_units_1d,
        SUM(COALESCE(o.same_units_7d, 0)) AS same_sku_attributed_units_7d,
        SUM(COALESCE(o.same_units_14d, 0)) AS same_sku_attributed_units_14d,
        SUM(COALESCE(o.same_units_30d, 0)) AS same_sku_attributed_units_30d,
        MAX(o.create_time) AS report_source_time
    FROM ods_datasync.lx_advertising_sp_keyword_reports o
    WHERE o.report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                            AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
      AND COALESCE(o.delete_flag, 0) = 0
      AND o.profile_id IS NOT NULL
      AND o.campaign_id IS NOT NULL
      AND o.ad_group_id IS NOT NULL
      AND o.keyword_id IS NOT NULL
    GROUP BY o.profile_id, o.campaign_id, o.ad_group_id, o.keyword_id;
    ALTER TABLE tmp_spbo_keyword_metric
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, keyword_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_auto_metric;
    CREATE TEMPORARY TABLE tmp_spbo_auto_metric ENGINE=InnoDB AS
    SELECT
        o.profile_id, o.campaign_id, o.ad_group_id,
        MAX(o.seller_name) AS report_seller_name,
        SUM(COALESCE(o.impressions, 0)) AS impressions,
        SUM(COALESCE(o.clicks, 0)) AS clicks,
        SUM(COALESCE(o.cost, 0)) AS cost,
        SUM(COALESCE(o.orders_7d, 0)) AS orders,
        SUM(COALESCE(o.sales_7d, 0)) AS sales,
        SUM(COALESCE(o.orders_1d, 0)) AS attributed_orders_1d,
        SUM(COALESCE(o.orders_7d, 0)) AS attributed_orders_7d,
        SUM(COALESCE(o.orders_14d, 0)) AS attributed_orders_14d,
        SUM(COALESCE(o.orders_30d, 0)) AS attributed_orders_30d,
        SUM(COALESCE(o.sales_1d, 0)) AS attributed_sales_1d,
        SUM(COALESCE(o.sales_7d, 0)) AS attributed_sales_7d,
        SUM(COALESCE(o.sales_14d, 0)) AS attributed_sales_14d,
        SUM(COALESCE(o.sales_30d, 0)) AS attributed_sales_30d,
        SUM(COALESCE(o.units_1d, 0)) AS attributed_units_1d,
        SUM(COALESCE(o.units_7d, 0)) AS attributed_units_7d,
        SUM(COALESCE(o.units_14d, 0)) AS attributed_units_14d,
        SUM(COALESCE(o.units_30d, 0)) AS attributed_units_30d,
        SUM(COALESCE(o.same_orders_1d, 0)) AS same_sku_attributed_orders_1d,
        SUM(COALESCE(o.same_orders_7d, 0)) AS same_sku_attributed_orders_7d,
        SUM(COALESCE(o.same_orders_14d, 0)) AS same_sku_attributed_orders_14d,
        SUM(COALESCE(o.same_orders_30d, 0)) AS same_sku_attributed_orders_30d,
        SUM(COALESCE(o.same_sales_1d, 0)) AS same_sku_attributed_sales_1d,
        SUM(COALESCE(o.same_sales_7d, 0)) AS same_sku_attributed_sales_7d,
        SUM(COALESCE(o.same_sales_14d, 0)) AS same_sku_attributed_sales_14d,
        SUM(COALESCE(o.same_sales_30d, 0)) AS same_sku_attributed_sales_30d,
        SUM(COALESCE(o.same_units_1d, 0)) AS same_sku_attributed_units_1d,
        SUM(COALESCE(o.same_units_7d, 0)) AS same_sku_attributed_units_7d,
        SUM(COALESCE(o.same_units_14d, 0)) AS same_sku_attributed_units_14d,
        SUM(COALESCE(o.same_units_30d, 0)) AS same_sku_attributed_units_30d,
        MAX(o.create_time) AS report_source_time
    FROM ods_datasync.lx_advertising_sp_ad_group_reports o
    WHERE o.report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                            AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
      AND COALESCE(o.delete_flag, 0) = 0
      AND o.profile_id IS NOT NULL
      AND o.campaign_id IS NOT NULL
      AND o.ad_group_id IS NOT NULL
    GROUP BY o.profile_id, o.campaign_id, o.ad_group_id;
    ALTER TABLE tmp_spbo_auto_metric
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_raw;
    CREATE TEMPORARY TABLE tmp_spbo_object_raw ENGINE=InnoDB AS
    SELECT
        m.profile_id, m.campaign_id, m.ad_group_id,
        'keyword' AS object_type,
        m.keyword_id AS object_id,
        COALESCE(k.keyword_text, '') AS object_text,
        k.state AS object_state_current,
        k.serving_status AS object_serving_status,
        k.match_type,
        k.bid AS current_bid,
        m.report_seller_name,
        m.impressions, m.clicks, m.cost, m.orders, m.sales,
        m.attributed_orders_1d, m.attributed_orders_7d, m.attributed_orders_14d, m.attributed_orders_30d,
        m.attributed_sales_1d, m.attributed_sales_7d, m.attributed_sales_14d, m.attributed_sales_30d,
        m.attributed_units_1d, m.attributed_units_7d, m.attributed_units_14d, m.attributed_units_30d,
        m.same_sku_attributed_orders_1d, m.same_sku_attributed_orders_7d, m.same_sku_attributed_orders_14d, m.same_sku_attributed_orders_30d,
        m.same_sku_attributed_sales_1d, m.same_sku_attributed_sales_7d, m.same_sku_attributed_sales_14d, m.same_sku_attributed_sales_30d,
        m.same_sku_attributed_units_1d, m.same_sku_attributed_units_7d, m.same_sku_attributed_units_14d, m.same_sku_attributed_units_30d,
        m.report_source_time,
        k.source_updated_at AS object_source_time
    FROM tmp_spbo_keyword_metric m
    LEFT JOIN tmp_spbo_keyword_current k
      ON k.profile_id = m.profile_id
     AND k.campaign_id = m.campaign_id
     AND k.ad_group_id = m.ad_group_id
     AND k.keyword_id = m.keyword_id

    UNION ALL

    SELECT
        m.profile_id, m.campaign_id, m.ad_group_id,
        'ad_group' AS object_type,
        m.ad_group_id AS object_id,
        COALESCE(g.name, '') AS object_text,
        g.state AS object_state_current,
        g.serving_status AS object_serving_status,
        NULL AS match_type,
        g.default_bid AS current_bid,
        m.report_seller_name,
        m.impressions, m.clicks, m.cost, m.orders, m.sales,
        m.attributed_orders_1d, m.attributed_orders_7d, m.attributed_orders_14d, m.attributed_orders_30d,
        m.attributed_sales_1d, m.attributed_sales_7d, m.attributed_sales_14d, m.attributed_sales_30d,
        m.attributed_units_1d, m.attributed_units_7d, m.attributed_units_14d, m.attributed_units_30d,
        m.same_sku_attributed_orders_1d, m.same_sku_attributed_orders_7d, m.same_sku_attributed_orders_14d, m.same_sku_attributed_orders_30d,
        m.same_sku_attributed_sales_1d, m.same_sku_attributed_sales_7d, m.same_sku_attributed_sales_14d, m.same_sku_attributed_sales_30d,
        m.same_sku_attributed_units_1d, m.same_sku_attributed_units_7d, m.same_sku_attributed_units_14d, m.same_sku_attributed_units_30d,
        m.report_source_time,
        g.source_updated_at AS object_source_time
    FROM tmp_spbo_auto_metric m
    INNER JOIN tmp_spbo_campaign_current c
      ON c.profile_id = m.profile_id
     AND c.campaign_id = m.campaign_id
     AND c.targeting_type = 'auto'
    LEFT JOIN tmp_spbo_ad_group_current g
      ON g.profile_id = m.profile_id
     AND g.campaign_id = m.campaign_id
     AND g.ad_group_id = m.ad_group_id;
    ALTER TABLE tmp_spbo_object_raw
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id),
        ADD KEY idx_object_group (profile_id, campaign_id, ad_group_id);

    /* 当前启用产品与成熟窗口产品必须均唯一且一致，才允许关联产品级信息。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_current_product;
    CREATE TEMPORARY TABLE tmp_spbo_current_product ENGINE=InnoDB AS
    SELECT
        profile_id, campaign_id, ad_group_id,
        COUNT(DISTINCT NULLIF(TRIM(sku), '')) AS current_enabled_msku_count,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1
             THEN MAX(NULLIF(TRIM(sku), '')) END AS current_msku,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(sku), '')) = 1
             THEN MAX(NULLIF(TRIM(asin), '')) END AS current_asin,
        MAX(COALESCE(
            update_time,
            FROM_UNIXTIME(NULLIF(CAST(last_updated_date AS UNSIGNED), 0) / 1000),
            create_time
        )) AS source_updated_at
    FROM ods_datasync.lx_advertising_sp_product_ads
    WHERE COALESCE(delete_flag, 0) = 0
      AND LOWER(COALESCE(state, '')) = 'enabled'
      AND profile_id IS NOT NULL
      AND campaign_id IS NOT NULL
      AND ad_group_id IS NOT NULL
    GROUP BY profile_id, campaign_id, ad_group_id;
    ALTER TABLE tmp_spbo_current_product
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_period_product;
    CREATE TEMPORARY TABLE tmp_spbo_period_product ENGINE=InnoDB AS
    SELECT
        o.profile_id, o.campaign_id, o.ad_group_id,
        COUNT(DISTINCT NULLIF(TRIM(o.sku), '')) AS period_msku_count,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(o.sku), '')) = 1
             THEN MAX(NULLIF(TRIM(o.sku), '')) END AS period_msku,
        CASE WHEN COUNT(DISTINCT NULLIF(TRIM(o.sku), '')) = 1
             THEN MAX(NULLIF(TRIM(o.asin), '')) END AS period_asin,
        MAX(o.create_time) AS source_updated_at
    FROM ods_datasync.lx_advertising_sp_product_ad_reports o
    WHERE o.report_date BETWEEN DATE_FORMAT(v_mature_start, '%Y-%m-%d')
                            AND DATE_FORMAT(v_mature_end, '%Y-%m-%d')
      AND COALESCE(o.delete_flag, 0) = 0
      AND o.profile_id IS NOT NULL
      AND o.campaign_id IS NOT NULL
      AND o.ad_group_id IS NOT NULL
    GROUP BY o.profile_id, o.campaign_id, o.ad_group_id;
    ALTER TABLE tmp_spbo_period_product
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_map;
    CREATE TEMPORARY TABLE tmp_spbo_product_map ENGINE=InnoDB AS
    SELECT
        g.profile_id, g.campaign_id, g.ad_group_id,
        COALESCE(p.period_msku_count, 0) AS period_msku_count,
        COALESCE(c.current_enabled_msku_count, 0) AS current_enabled_msku_count,
        GREATEST(
            COALESCE(p.period_msku_count, 0),
            COALESCE(c.current_enabled_msku_count, 0)
        ) AS associated_msku_count,
        CASE
            WHEN COALESCE(p.period_msku_count, 0) = 0 THEN 'period_record_missing'
            WHEN p.period_msku_count > 1 THEN 'period_multiple_msku'
            WHEN COALESCE(c.current_enabled_msku_count, 0) = 0 THEN 'current_record_missing'
            WHEN c.current_enabled_msku_count > 1 THEN 'current_multiple_msku'
            WHEN LOWER(p.period_msku) <> LOWER(c.current_msku) THEN 'msku_changed'
            ELSE 'mapped'
        END AS msku_mapping_status,
        CAST(CASE
            WHEN p.period_msku_count = 1
             AND c.current_enabled_msku_count = 1
             AND LOWER(p.period_msku) = LOWER(c.current_msku)
            THEN p.period_msku
        END AS CHAR(100)) AS msku,
        CAST(CASE
            WHEN p.period_msku_count = 1
             AND c.current_enabled_msku_count = 1
             AND LOWER(p.period_msku) = LOWER(c.current_msku)
            THEN COALESCE(c.current_asin, p.period_asin)
        END AS CHAR(50)) AS asin,
        GREATEST(
            COALESCE(p.source_updated_at, '1000-01-01'),
            COALESCE(c.source_updated_at, '1000-01-01')
        ) AS source_updated_at
    FROM (
        SELECT DISTINCT profile_id, campaign_id, ad_group_id
        FROM tmp_spbo_object_raw
    ) g
    LEFT JOIN tmp_spbo_period_product p
      ON p.profile_id = g.profile_id
     AND p.campaign_id = g.campaign_id
     AND p.ad_group_id = g.ad_group_id
    LEFT JOIN tmp_spbo_current_product c
      ON c.profile_id = g.profile_id
     AND c.campaign_id = g.campaign_id
     AND c.ad_group_id = g.ad_group_id;
    ALTER TABLE tmp_spbo_product_map
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id),
        ADD KEY idx_product_msku (msku);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_product;
    CREATE TEMPORARY TABLE tmp_spbo_object_product ENGINE=InnoDB AS
    SELECT
        v_snapshot_date AS snapshot_date,
        o.profile_id,
        COALESCE(a.sid, 0) AS sid,
        COALESCE(NULLIF(o.report_seller_name, ''), a.account_name) AS seller_name,
        CAST(REGEXP_REPLACE(
            LOWER(TRIM(COALESCE(NULLIF(o.report_seller_name, ''), a.account_name, ''))),
            '-(eu-)?[a-z]{2}$',
            ''
        ) AS CHAR(255)) AS base_store_name,
        CAST(LOWER(COALESCE(a.country_code, '')) AS CHAR(20)) AS country_code,
        a.currency_code,
        o.campaign_id,
        c.name AS campaign_name_current,
        c.state AS campaign_state_current,
        c.serving_status AS campaign_serving_status,
        c.campaign_type,
        COALESCE(NULLIF(c.targeting_type, ''), 'unknown') AS targeting_type,
        c.portfolio_id,
        c.daily_budget AS daily_budget_current,
        c.bidding_strategy AS bidding_strategy_current,
        c.placement_top_percentage,
        c.placement_product_page_percentage,
        c.placement_rest_of_search_percentage,
        o.ad_group_id,
        g.name AS ad_group_name_current,
        g.state AS ad_group_state_current,
        g.serving_status AS ad_group_serving_status,
        g.default_bid AS default_bid_current,
        o.object_type, o.object_id, o.object_text,
        o.object_state_current, o.object_serving_status, o.match_type,
        o.current_bid,
        CAST(p.msku AS CHAR(100)) AS msku, CAST(p.asin AS CHAR(50)) AS asin, p.associated_msku_count,
        p.period_msku_count, p.current_enabled_msku_count,
        p.msku_mapping_status,
        o.impressions, o.clicks, o.cost, o.orders, o.sales,
        o.attributed_orders_1d, o.attributed_orders_7d, o.attributed_orders_14d, o.attributed_orders_30d,
        o.attributed_sales_1d, o.attributed_sales_7d, o.attributed_sales_14d, o.attributed_sales_30d,
        o.attributed_units_1d, o.attributed_units_7d, o.attributed_units_14d, o.attributed_units_30d,
        o.same_sku_attributed_orders_1d, o.same_sku_attributed_orders_7d, o.same_sku_attributed_orders_14d, o.same_sku_attributed_orders_30d,
        o.same_sku_attributed_sales_1d, o.same_sku_attributed_sales_7d, o.same_sku_attributed_sales_14d, o.same_sku_attributed_sales_30d,
        o.same_sku_attributed_units_1d, o.same_sku_attributed_units_7d, o.same_sku_attributed_units_14d, o.same_sku_attributed_units_30d,
        o.sales / NULLIF(o.orders, 0) AS aov,
        o.clicks / NULLIF(o.impressions, 0) AS ctr,
        o.cost / NULLIF(o.clicks, 0) AS cpc,
        o.orders / NULLIF(o.clicks, 0) AS cvr,
        o.cost / NULLIF(o.sales, 0) AS acos,
        o.sales / NULLIF(o.cost, 0) AS roas,
        GREATEST(
            COALESCE(o.report_source_time, '1000-01-01'),
            COALESCE(o.object_source_time, '1000-01-01'),
            COALESCE(c.source_updated_at, '1000-01-01'),
            COALESCE(g.source_updated_at, '1000-01-01'),
            COALESCE(p.source_updated_at, '1000-01-01')
        ) AS source_latest_create_time
    FROM tmp_spbo_object_raw o
    LEFT JOIN tmp_spbo_account_current a
      ON a.profile_id = o.profile_id
    LEFT JOIN tmp_spbo_campaign_current c
      ON c.profile_id = o.profile_id
     AND c.campaign_id = o.campaign_id
    LEFT JOIN tmp_spbo_ad_group_current g
      ON g.profile_id = o.profile_id
     AND g.campaign_id = o.campaign_id
     AND g.ad_group_id = o.ad_group_id
    LEFT JOIN tmp_spbo_product_map p
      ON p.profile_id = o.profile_id
     AND p.campaign_id = o.campaign_id
     AND p.ad_group_id = o.ad_group_id;
    ALTER TABLE tmp_spbo_object_product
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id),
        ADD KEY idx_object_product_key (base_store_name, country_code, msku),
        ADD KEY idx_object_benchmark (object_type, country_code);

    /* 复刻按对象类型和站点计算的加权CVR均值与线性插值P75。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_cvr_ranked;
    CREATE TEMPORARY TABLE tmp_spbo_cvr_ranked ENGINE=InnoDB AS
    SELECT
        object_type, country_code, cvr,
        ROW_NUMBER() OVER (
            PARTITION BY object_type, country_code ORDER BY cvr
        ) AS rn,
        COUNT(*) OVER (
            PARTITION BY object_type, country_code
        ) AS n
    FROM tmp_spbo_object_product
    WHERE clicks > 0;
    ALTER TABLE tmp_spbo_cvr_ranked
        ADD KEY idx_cvr_group (object_type, country_code, rn);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_p75;
    CREATE TEMPORARY TABLE tmp_spbo_p75 ENGINE=InnoDB AS
    SELECT
        object_type, country_code,
        MAX(CASE WHEN rn = FLOOR((n - 1) * 0.75) + 1 THEN cvr END)
          + (
              MAX(CASE WHEN rn = CEIL((n - 1) * 0.75) + 1 THEN cvr END)
              - MAX(CASE WHEN rn = FLOOR((n - 1) * 0.75) + 1 THEN cvr END)
            ) * MOD((MAX(n) - 1) * 0.75, 1) AS site_cvr_p75
    FROM tmp_spbo_cvr_ranked
    GROUP BY object_type, country_code;
    ALTER TABLE tmp_spbo_p75
        ADD PRIMARY KEY (object_type, country_code);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_benchmark;
    CREATE TEMPORARY TABLE tmp_spbo_benchmark ENGINE=InnoDB AS
    SELECT
        b.object_type, b.country_code,
        SUM(b.orders) / NULLIF(SUM(b.clicks), 0) AS site_cvr_avg,
        MAX(p.site_cvr_p75) AS site_cvr_p75
    FROM tmp_spbo_object_product b
    LEFT JOIN tmp_spbo_p75 p
      ON p.object_type = b.object_type
     AND p.country_code = b.country_code
    GROUP BY b.object_type, b.country_code;
    ALTER TABLE tmp_spbo_benchmark
        ADD PRIMARY KEY (object_type, country_code);

    /* 截止快照月的最新远端汇率；预算DWS汇率为空时用于安全回补。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_fx;
    CREATE TEMPORARY TABLE tmp_spbo_fx ENGINE=InnoDB AS
    SELECT currency_code, exchange_rate_cny
    FROM (
        SELECT
            fx_base.*,
            ROW_NUMBER() OVER (
                PARTITION BY currency_code
                ORDER BY rate_month DESC
            ) AS rn
        FROM (
            SELECT
                CASE UPPER(TRIM(c.name))
                    WHEN '欧元' THEN 'EUR' WHEN 'EUR' THEN 'EUR'
                    WHEN '波兰兹罗提' THEN 'PLN' WHEN 'PLN' THEN 'PLN'
                    WHEN '瑞典' THEN 'SEK' WHEN '瑞典克朗' THEN 'SEK' WHEN 'SEK' THEN 'SEK'
                    WHEN '土耳其里拉' THEN 'TRY' WHEN 'TRY' THEN 'TRY'
                    WHEN '英镑' THEN 'GBP' WHEN 'GBP' THEN 'GBP'
                    WHEN '美元' THEN 'USD' WHEN 'USD' THEN 'USD'
                    WHEN '加元' THEN 'CAD' WHEN 'CAD' THEN 'CAD'
                    WHEN '墨西哥比索' THEN 'MXN' WHEN 'MXN' THEN 'MXN'
                    WHEN '巴西雷亚尔' THEN 'BRL' WHEN 'BRL' THEN 'BRL'
                    WHEN '日元' THEN 'JPY' WHEN 'JPY' THEN 'JPY'
                    WHEN '澳元' THEN 'AUD' WHEN 'AUD' THEN 'AUD'
                    WHEN '阿联酋迪拉姆' THEN 'AED' WHEN 'AED' THEN 'AED'
                    WHEN '沙特里亚尔' THEN 'SAR' WHEN 'SAR' THEN 'SAR'
                    WHEN '印度卢比' THEN 'INR' WHEN 'INR' THEN 'INR'
                    WHEN '新加坡元' THEN 'SGD' WHEN 'SGD' THEN 'SGD'
                    ELSE NULL
                END AS currency_code,
                CAST(NULLIF(c.rate_org, '') AS DECIMAL(20,8)) AS exchange_rate_cny,
                c.date AS rate_month
            FROM dwd_datasync.lx_basic_currency c
            WHERE c.date <= DATE_FORMAT(v_snapshot_date, '%Y-%m')
              AND NULLIF(c.rate_org, '') IS NOT NULL
        ) fx_base
        WHERE currency_code IS NOT NULL
    ) ranked_fx
    WHERE rn = 1
      AND currency_code IS NOT NULL
      AND exchange_rate_cny > 0;
    ALTER TABLE tmp_spbo_fx ADD PRIMARY KEY (currency_code);

    /* 远端预算快照，按店铺主体、站点代码和MSKU标准化。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_budget;
    CREATE TEMPORARY TABLE tmp_spbo_budget ENGINE=InnoDB AS
    SELECT
        budget_snapshot_date,
        base_store_name,
        country_code,
        msku_key,
        MAX(product_currency_code) AS product_currency_code,
        MAX(exchange_rate_cny) AS exchange_rate_cny,
        MAX(monthly_ad_budget_original) AS monthly_ad_budget_original,
        MAX(monthly_ad_budget_cny) AS monthly_ad_budget_cny,
        MAX(weekly_ad_budget_original) AS weekly_ad_budget_original,
        MAX(weekly_ad_budget_cny) AS weekly_ad_budget_cny,
        MAX(site_total_budget_cny) AS site_total_budget_cny,
        MIN(inventory_sufficient_flag) AS inventory_sufficient_flag,
        MIN(weekly_inventory_sufficient_flag) AS weekly_inventory_sufficient_flag
    FROM (
        SELECT
            b.biz_date AS budget_snapshot_date,
            CAST(LOWER(TRIM(b.seller_name_new)) AS CHAR(255)) AS base_store_name,
            CAST(CASE LOWER(TRIM(b.country))
                WHEN '美国' THEN 'us' WHEN '加拿大' THEN 'ca'
                WHEN '墨西哥' THEN 'mx' WHEN '巴西' THEN 'br'
                WHEN '英国' THEN 'uk' WHEN '德国' THEN 'de'
                WHEN '法国' THEN 'fr' WHEN '意大利' THEN 'it'
                WHEN '西班牙' THEN 'es' WHEN '荷兰' THEN 'nl'
                WHEN '瑞典' THEN 'se' WHEN '波兰' THEN 'pl'
                WHEN '比利时' THEN 'be' WHEN '爱尔兰' THEN 'ie'
                WHEN '日本' THEN 'jp' WHEN '澳大利亚' THEN 'au'
                WHEN '阿联酋' THEN 'ae' WHEN '沙特阿拉伯' THEN 'sa'
                WHEN '印度' THEN 'in' WHEN '新加坡' THEN 'sg'
                WHEN '土耳其' THEN 'tr'
                ELSE LOWER(REPLACE(TRIM(b.country), '站', ''))
            END AS CHAR(20)) AS country_code,
            CAST(LOWER(TRIM(b.seller_sku_adj)) AS CHAR(100)) AS msku_key,
            b.currency_code AS product_currency_code,
            COALESCE(b.exchange_rate_cny, fx.exchange_rate_cny) AS exchange_rate_cny,
            b.monthly_ad_budget_original,
            COALESCE(
                b.monthly_ad_budget_cny,
                b.monthly_ad_budget_original
                    * COALESCE(b.exchange_rate_cny, fx.exchange_rate_cny)
            ) AS monthly_ad_budget_cny,
            b.weekly_ad_budget_original,
            COALESCE(
                b.weekly_ad_budget_cny,
                b.weekly_ad_budget_original
                    * COALESCE(b.exchange_rate_cny, fx.exchange_rate_cny)
            ) AS weekly_ad_budget_cny,
            b.site_total_budget_cny,
            b.inventory_sufficient_flag,
            b.weekly_inventory_sufficient_flag
        FROM dws_datasync.dws_monthly_ad_budget_detail b
        LEFT JOIN tmp_spbo_fx fx
          ON fx.currency_code = UPPER(TRIM(b.currency_code))
        WHERE b.biz_date = (
            SELECT MAX(b2.biz_date)
            FROM dws_datasync.dws_monthly_ad_budget_detail b2
            /* 预算DWS在快照次日发布，取该日及之前最近可用版本。 */
            WHERE b2.biz_date <= DATE_ADD(v_snapshot_date, INTERVAL 1 DAY)
        )
    ) normalized_budget
    GROUP BY budget_snapshot_date, base_store_name, country_code, msku_key;
    ALTER TABLE tmp_spbo_budget
        ADD KEY idx_budget_product (base_store_name, country_code, msku_key);

    /* 产品本月至今及近7天花费。与现有页面一致，使用产品经营表spend字段。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_spend;
    CREATE TEMPORARY TABLE tmp_spbo_product_spend ENGINE=InnoDB AS
    SELECT
        CAST(REGEXP_REPLACE(
            LOWER(TRIM(p.seller_name)),
            '-(eu-)?[a-z]{2}$',
            ''
        ) AS CHAR(255)) AS base_store_name,
        CAST(CASE LOWER(TRIM(p.country))
            WHEN '美国' THEN 'us' WHEN '加拿大' THEN 'ca'
            WHEN '墨西哥' THEN 'mx' WHEN '巴西' THEN 'br'
            WHEN '英国' THEN 'uk' WHEN '德国' THEN 'de'
            WHEN '法国' THEN 'fr' WHEN '意大利' THEN 'it'
            WHEN '西班牙' THEN 'es' WHEN '荷兰' THEN 'nl'
            WHEN '瑞典' THEN 'se' WHEN '波兰' THEN 'pl'
            WHEN '比利时' THEN 'be' WHEN '爱尔兰' THEN 'ie'
            WHEN '日本' THEN 'jp' WHEN '澳大利亚' THEN 'au'
            WHEN '阿联酋' THEN 'ae' WHEN '沙特阿拉伯' THEN 'sa'
            WHEN '印度' THEN 'in' WHEN '新加坡' THEN 'sg'
            WHEN '土耳其' THEN 'tr'
            ELSE LOWER(REPLACE(TRIM(p.country), '站', ''))
        END AS CHAR(20)) AS country_code,
        CAST(LOWER(TRIM(
            CASE
                WHEN LENGTH(SUBSTRING_INDEX(p.seller_sku, ',', 1)) > 16
                THEN REPLACE(
                    SUBSTRING_INDEX(SUBSTRING_INDEX(p.seller_sku, ',', 1), '-', 1),
                    'amzn.gr.',
                    ''
                )
                ELSE SUBSTRING_INDEX(p.seller_sku, ',', 1)
            END
        )) AS CHAR(100)) AS msku_key,
        SUM(COALESCE(p.spend, 0)) AS month_product_spend_cny,
        SUM(
            CASE WHEN p.start_date >= DATE_SUB(v_snapshot_date, INTERVAL 6 DAY)
                 THEN COALESCE(p.spend, 0) ELSE 0 END
        ) AS spend_7d_cny,
        MAX(DATE(p.start_date)) AS budget_performance_date,
        MAX(p.create_time) AS source_updated_at
    FROM dwd_datasync.lx_statistics_product_performance p
    WHERE p.start_date >= DATE_FORMAT(v_snapshot_date, '%Y-%m-01')
      AND p.start_date < DATE_ADD(v_snapshot_date, INTERVAL 1 DAY)
      AND p.seller_sku NOT LIKE 'Amazon.Found%'
    GROUP BY base_store_name, country_code, msku_key;
    ALTER TABLE tmp_spbo_product_spend
        ADD KEY idx_spend_product (base_store_name, country_code, msku_key);

    /* 截止快照日的最新Listing价格。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_listing;
    CREATE TEMPORARY TABLE tmp_spbo_listing ENGINE=InnoDB AS
    SELECT base_store_name, country_code, msku_key, listing_price, source_updated_at
    FROM (
        SELECT
            listing_base.*,
            ROW_NUMBER() OVER (
                PARTITION BY base_store_name, country_code, msku_key
                ORDER BY source_updated_at DESC, source_id DESC
            ) AS rn
        FROM (
            SELECT
                CAST(REGEXP_REPLACE(
                    LOWER(TRIM(l.seller_name)),
                    '-(eu-)?[a-z]{2}$',
                    ''
                ) AS CHAR(255)) AS base_store_name,
                CAST(CASE LOWER(TRIM(l.marketplace))
                    WHEN '美国' THEN 'us' WHEN '加拿大' THEN 'ca'
                    WHEN '墨西哥' THEN 'mx' WHEN '巴西' THEN 'br'
                    WHEN '英国' THEN 'uk' WHEN '德国' THEN 'de'
                    WHEN '法国' THEN 'fr' WHEN '意大利' THEN 'it'
                    WHEN '西班牙' THEN 'es' WHEN '荷兰' THEN 'nl'
                    WHEN '瑞典' THEN 'se' WHEN '波兰' THEN 'pl'
                    WHEN '比利时' THEN 'be' WHEN '爱尔兰' THEN 'ie'
                    WHEN '日本' THEN 'jp' WHEN '澳大利亚' THEN 'au'
                    WHEN '阿联酋' THEN 'ae' WHEN '沙特阿拉伯' THEN 'sa'
                    WHEN '印度' THEN 'in' WHEN '新加坡' THEN 'sg'
                    WHEN '土耳其' THEN 'tr'
                    ELSE LOWER(REPLACE(TRIM(l.marketplace), '站', ''))
                END AS CHAR(20)) AS country_code,
                CAST(LOWER(TRIM(l.seller_sku)) AS CHAR(100)) AS msku_key,
                CAST(NULLIF(l.landed_price, '') AS DECIMAL(20,6)) AS listing_price,
                l.create_time AS source_updated_at,
                l.id AS source_id
            FROM dwd_datasync.lx_sales_mws_listing l
            /* Listing在快照次日凌晨同步，保留该日数据以避免整批价格关联为空。 */
            WHERE l.create_time < DATE_ADD(v_snapshot_date, INTERVAL 2 DAY)
              AND NULLIF(TRIM(l.seller_sku), '') IS NOT NULL
        ) listing_base
    ) ranked
    WHERE rn = 1;
    ALTER TABLE tmp_spbo_listing
        ADD KEY idx_listing_product (base_store_name, country_code, msku_key);

    /* 当前远端定价阶梯。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_limit_price;
    CREATE TEMPORARY TABLE tmp_spbo_limit_price ENGINE=InnoDB AS
    SELECT
        CAST(LOWER(TRIM(`新店铺`)) AS CHAR(255)) AS base_store_name,
        CAST(CASE LOWER(TRIM(`国家`))
            WHEN '美国' THEN 'us' WHEN '加拿大' THEN 'ca'
            WHEN '墨西哥' THEN 'mx' WHEN '巴西' THEN 'br'
            WHEN '英国' THEN 'uk' WHEN '德国' THEN 'de'
            WHEN '法国' THEN 'fr' WHEN '意大利' THEN 'it'
            WHEN '西班牙' THEN 'es' WHEN '荷兰' THEN 'nl'
            WHEN '瑞典' THEN 'se' WHEN '波兰' THEN 'pl'
            WHEN '比利时' THEN 'be' WHEN '爱尔兰' THEN 'ie'
            WHEN '日本' THEN 'jp' WHEN '澳大利亚' THEN 'au'
            WHEN '阿联酋' THEN 'ae' WHEN '沙特阿拉伯' THEN 'sa'
            WHEN '印度' THEN 'in' WHEN '新加坡' THEN 'sg'
            WHEN '土耳其' THEN 'tr'
            ELSE LOWER(REPLACE(TRIM(`国家`), '站', ''))
        END AS CHAR(20)) AS country_code,
        CAST(LOWER(TRIM(msku)) AS CHAR(100)) AS msku_key,
        MAX(CAST(NULLIF(`35毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_35,
        MAX(CAST(NULLIF(`30毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_30,
        MAX(CAST(NULLIF(`25毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_25,
        MAX(CAST(NULLIF(`20毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_20,
        MAX(CAST(NULLIF(`15毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_15,
        MAX(CAST(NULLIF(`10毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_10,
        MAX(CAST(NULLIF(`5毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_5,
        MAX(CAST(NULLIF(`0毛利润价格`, '') AS DECIMAL(20,6))) AS margin_price_0
    FROM temporary_dwd.`在库节点_输出定价表`
    WHERE NULLIF(TRIM(msku), '') IS NOT NULL
      AND NULLIF(TRIM(`新店铺`), '') IS NOT NULL
      AND NULLIF(TRIM(`国家`), '') IS NOT NULL
    GROUP BY base_store_name, country_code, msku_key;
    ALTER TABLE tmp_spbo_limit_price
        ADD KEY idx_limit_product (base_store_name, country_code, msku_key);

    /* 合并全部远端上下文，并计算基础指标、毛利率阶梯与预算状态。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_enriched;
    CREATE TEMPORARY TABLE tmp_spbo_enriched ENGINE=InnoDB AS
    SELECT
        o.*,
        b.site_cvr_avg,
        b.site_cvr_p75,
        l.listing_price,
        CASE
            WHEN l.listing_price IS NULL OR lp.margin_price_0 IS NULL THEN NULL
            WHEN l.listing_price < lp.margin_price_0 THEN NULL
            WHEN lp.margin_price_35 IS NOT NULL AND l.listing_price >= lp.margin_price_35 THEN 0.35
            WHEN lp.margin_price_30 IS NOT NULL AND l.listing_price >= lp.margin_price_30 THEN 0.30
            WHEN lp.margin_price_25 IS NOT NULL AND l.listing_price >= lp.margin_price_25 THEN 0.25
            WHEN lp.margin_price_20 IS NOT NULL AND l.listing_price >= lp.margin_price_20 THEN 0.20
            WHEN lp.margin_price_15 IS NOT NULL AND l.listing_price >= lp.margin_price_15 THEN 0.15
            WHEN lp.margin_price_10 IS NOT NULL AND l.listing_price >= lp.margin_price_10 THEN 0.10
            WHEN lp.margin_price_5 IS NOT NULL AND l.listing_price >= lp.margin_price_5 THEN 0.05
            ELSE 0.00
        END AS margin_rate,
        CASE
            WHEN lp.margin_price_0 IS NOT NULL
             AND lp.margin_price_5 IS NOT NULL
             AND lp.margin_price_10 IS NOT NULL
             AND lp.margin_price_15 IS NOT NULL
             AND lp.margin_price_20 IS NOT NULL
             AND lp.margin_price_25 IS NOT NULL
             AND lp.margin_price_30 IS NOT NULL
             AND lp.margin_price_35 IS NOT NULL
            THEN 1 ELSE 0
        END AS margin_ladder_complete,
        CASE
            WHEN l.listing_price IS NOT NULL
             AND lp.margin_price_0 IS NOT NULL
             AND l.listing_price < lp.margin_price_0
            THEN 1 ELSE 0
        END AS below_zero_margin_price,
        bud.budget_snapshot_date,
        v_snapshot_date AS budget_performance_date,
        bud.product_currency_code,
        bud.exchange_rate_cny,
        bud.monthly_ad_budget_original,
        bud.monthly_ad_budget_cny,
        bud.weekly_ad_budget_original,
        bud.weekly_ad_budget_cny,
        ps.month_product_spend_cny,
        ps.spend_7d_cny,
        bud.monthly_ad_budget_cny - ps.month_product_spend_cny
            AS monthly_remaining_budget_cny,
        bud.weekly_ad_budget_cny - ps.spend_7d_cny
            AS weekly_remaining_budget_cny,
        ps.month_product_spend_cny / NULLIF(bud.monthly_ad_budget_cny, 0)
            AS monthly_budget_usage_rate,
        ps.spend_7d_cny / NULLIF(bud.weekly_ad_budget_cny, 0)
            AS weekly_budget_usage_rate,
        DAY(v_snapshot_date) / DAY(LAST_DAY(v_snapshot_date)) AS month_progress_rate,
        bud.site_total_budget_cny,
        bud.inventory_sufficient_flag,
        bud.weekly_inventory_sufficient_flag,
        CASE
            WHEN bud.msku_key IS NULL
              OR bud.monthly_ad_budget_cny IS NULL
              OR bud.weekly_ad_budget_cny IS NULL
              OR bud.site_total_budget_cny IS NULL
            THEN 'incomplete'
            WHEN bud.monthly_ad_budget_cny > bud.site_total_budget_cny + 0.01
              OR bud.weekly_ad_budget_cny > bud.monthly_ad_budget_cny + 0.01
            THEN 'invalid'
            ELSE 'complete'
        END AS budget_config_status,
        CASE
            WHEN bud.monthly_ad_budget_cny IS NULL
              OR bud.monthly_ad_budget_cny <= 0 THEN 'missing'
            WHEN ps.msku_key IS NULL THEN 'spend_missing'
            WHEN COALESCE(ps.month_product_spend_cny, 0) > bud.monthly_ad_budget_cny + 0.01
              THEN 'overspent'
            WHEN COALESCE(ps.month_product_spend_cny, 0) / NULLIF(bud.monthly_ad_budget_cny, 0)
                 - DAY(v_snapshot_date) / DAY(LAST_DAY(v_snapshot_date)) >= 0.20
              THEN 'too_fast'
            WHEN ps.msku_key IS NOT NULL
             AND COALESCE(ps.month_product_spend_cny, 0) = 0 THEN 'not_started'
            WHEN DAY(v_snapshot_date) / DAY(LAST_DAY(v_snapshot_date)) >= 0.25
             AND DAY(v_snapshot_date) / DAY(LAST_DAY(v_snapshot_date))
                 - COALESCE(ps.month_product_spend_cny, 0)
                   / NULLIF(bud.monthly_ad_budget_cny, 0) >= 0.20
              THEN 'too_slow'
            ELSE 'normal'
        END AS monthly_budget_status,
        CASE
            WHEN bud.weekly_ad_budget_cny IS NULL
              OR bud.weekly_ad_budget_cny <= 0 THEN 'missing'
            WHEN ps.msku_key IS NULL THEN 'spend_missing'
            WHEN COALESCE(ps.spend_7d_cny, 0) > bud.weekly_ad_budget_cny + 0.01
              THEN 'overspent'
            ELSE 'normal'
        END AS weekly_budget_status,
        CASE
            WHEN o.msku_mapping_status = 'period_multiple_msku'
              THEN '成熟窗口内投放过多个MSKU，需人工排查'
            WHEN o.msku_mapping_status = 'current_multiple_msku'
              THEN '当前同时启用多个MSKU，需人工排查'
            WHEN o.msku_mapping_status = 'msku_changed'
              THEN '成熟窗口商品与当前启用商品不一致，需人工排查'
            WHEN o.msku_mapping_status <> 'mapped'
              THEN '推广MSKU未安全映射，需人工排查'
            WHEN bud.msku_key IS NULL THEN '商品预算未匹配，需人工排查'
            WHEN bud.inventory_sufficient_flag = 0
             AND bud.monthly_ad_budget_cny IS NOT NULL
             AND ps.month_product_spend_cny IS NOT NULL
             AND ps.month_product_spend_cny >= bud.monthly_ad_budget_cny
              THEN '库存不足且预算已用尽'
            WHEN bud.inventory_sufficient_flag = 0 THEN '库存不足，禁止提价'
            WHEN bud.monthly_ad_budget_cny IS NOT NULL
             AND ps.month_product_spend_cny IS NOT NULL
             AND ps.month_product_spend_cny >= bud.monthly_ad_budget_cny
              THEN '预算已用尽，禁止提价'
            WHEN bud.monthly_ad_budget_cny IS NULL THEN '预算额度缺失'
            WHEN ps.month_product_spend_cny IS NULL THEN '本月花费未匹配'
            ELSE '支持提价'
        END AS budget_support_status,
        JSON_MERGE_PRESERVE(
            IF(
                bud.monthly_ad_budget_cny > bud.site_total_budget_cny + 0.01,
                JSON_ARRAY('monthly_budget_exceeds_site_total'),
                JSON_ARRAY()
            ),
            IF(
                bud.weekly_ad_budget_cny > bud.monthly_ad_budget_cny + 0.01,
                JSON_ARRAY('weekly_budget_exceeds_monthly'),
                JSON_ARRAY()
            ),
            IF(
                COALESCE(ps.month_product_spend_cny, 0) > 0
                AND COALESCE(bud.monthly_ad_budget_cny, 0) <= 0,
                JSON_ARRAY('spend_without_monthly_budget'),
                JSON_ARRAY()
            ),
            IF(
                bud.monthly_ad_budget_cny > 0
                AND COALESCE(ps.month_product_spend_cny, 0)
                    > bud.monthly_ad_budget_cny + 0.01,
                JSON_ARRAY('monthly_budget_overspent'),
                JSON_ARRAY()
            ),
            IF(
                bud.weekly_ad_budget_cny > 0
                AND COALESCE(ps.spend_7d_cny, 0)
                    > bud.weekly_ad_budget_cny + 0.01,
                JSON_ARRAY('weekly_budget_overspent'),
                JSON_ARRAY()
            )
        ) AS budget_anomalies,
        GREATEST(
            o.source_latest_create_time,
            COALESCE(l.source_updated_at, '1000-01-01'),
            COALESCE(ps.source_updated_at, '1000-01-01')
        ) AS enriched_source_time
    FROM tmp_spbo_object_product o
    LEFT JOIN tmp_spbo_benchmark b
      ON b.object_type = o.object_type
     AND b.country_code = o.country_code
    LEFT JOIN tmp_spbo_listing l
      ON l.base_store_name = o.base_store_name
     AND l.country_code = o.country_code
     AND l.msku_key = LOWER(o.msku)
    LEFT JOIN tmp_spbo_limit_price lp
      ON lp.base_store_name = o.base_store_name
     AND lp.country_code = o.country_code
     AND lp.msku_key = LOWER(o.msku)
    LEFT JOIN tmp_spbo_budget bud
      ON bud.base_store_name = o.base_store_name
     AND bud.country_code = o.country_code
     AND bud.msku_key = LOWER(o.msku)
    LEFT JOIN tmp_spbo_product_spend ps
      ON ps.base_store_name = o.base_store_name
     AND ps.country_code = o.country_code
     AND ps.msku_key = LOWER(o.msku);
    ALTER TABLE tmp_spbo_enriched
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id);

    /* 计算理论CPC与规则分支。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_eval;
    CREATE TEMPORARY TABLE tmp_spbo_eval ENGINE=InnoDB AS
    SELECT
        e.*,
        e.aov * e.cvr * e.margin_rate AS theoretical_cpc,
        e.aov * e.cvr * 0.20 AS reference_cpc_20,
        e.aov * e.cvr * 0.333 AS reference_cpc_333,
        CASE
            WHEN e.msku_mapping_status <> 'mapped'
              OR e.listing_price IS NULL
              OR e.margin_ladder_complete = 0
              OR e.below_zero_margin_price = 1
            THEN 'manual_review'
            WHEN e.current_bid IS NULL OR e.current_bid <= 0
            THEN 'insufficient_data'
            WHEN e.clicks >= 15 AND e.orders = 0
            THEN 'decrease_no_order'
            WHEN e.clicks >= 20 AND e.orders >= 1 AND e.acos > 0.50
            THEN 'decrease_acos_50'
            WHEN e.clicks >= 20 AND e.orders >= 1 AND e.acos > 0.333
            THEN 'decrease_acos_333'
            WHEN e.aov IS NULL OR e.cvr IS NULL OR e.margin_rate IS NULL
            THEN 'insufficient_data'
            WHEN (
                    e.clicks >= 20 AND e.orders >= 3
                AND e.acos <= 0.15
                AND e.site_cvr_p75 IS NOT NULL
                AND e.cvr >= e.site_cvr_p75
                AND e.aov * e.cvr * e.margin_rate > e.current_bid
                 )
              AND (
                    e.inventory_sufficient_flag = 0
                 OR (
                        e.monthly_ad_budget_cny IS NOT NULL
                    AND e.month_product_spend_cny IS NOT NULL
                    AND e.month_product_spend_cny >= e.monthly_ad_budget_cny
                    )
                  )
            THEN 'increase_blocked'
            WHEN (
                    e.clicks >= 20 AND e.orders >= 3
                AND e.acos <= 0.20
                AND e.site_cvr_avg IS NOT NULL
                AND e.cvr >= e.site_cvr_avg
                AND e.aov * e.cvr * e.margin_rate > e.current_bid
                 )
              AND (
                    e.inventory_sufficient_flag = 0
                 OR (
                        e.monthly_ad_budget_cny IS NOT NULL
                    AND e.month_product_spend_cny IS NOT NULL
                    AND e.month_product_spend_cny >= e.monthly_ad_budget_cny
                    )
                  )
            THEN 'increase_blocked'
            WHEN e.clicks >= 20 AND e.orders >= 3
             AND e.acos <= 0.15
             AND e.site_cvr_p75 IS NOT NULL
             AND e.cvr >= e.site_cvr_p75
             AND e.aov * e.cvr * e.margin_rate > e.current_bid
            THEN 'increase_high'
            WHEN e.clicks >= 20 AND e.orders >= 3
             AND e.acos <= 0.20
             AND e.site_cvr_avg IS NOT NULL
             AND e.cvr >= e.site_cvr_avg
             AND e.aov * e.cvr * e.margin_rate > e.current_bid
            THEN 'increase_small'
            WHEN e.clicks >= 10 AND e.acos <= 0.333
            THEN 'keep'
            ELSE 'insufficient_data'
        END AS decision_code
    FROM tmp_spbo_enriched e;
    ALTER TABLE tmp_spbo_eval
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id);

    /* 竞价最小单位为0.01：提价向下取整，降价向上取整。 */
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_scored;
    CREATE TEMPORARY TABLE tmp_spbo_scored ENGINE=InnoDB AS
    SELECT
        e.*,
        CASE e.decision_code
            WHEN 'decrease_no_order' THEN
                CEIL(
                    e.current_bid * (
                        1 - LEAST(
                            GREATEST(
                                COALESCE(
                                    GREATEST(
                                        0,
                                        (e.current_bid - e.theoretical_cpc) / e.current_bid
                                    ),
                                    0.30
                                ),
                                0.20
                            ),
                            0.30
                        )
                    ) * 100
                ) / 100
            WHEN 'decrease_acos_50' THEN
                CEIL(
                    e.current_bid * (
                        1 - LEAST(
                            GREATEST(
                                COALESCE(
                                    GREATEST(
                                        0,
                                        (e.current_bid - e.theoretical_cpc) / e.current_bid
                                    ),
                                    0.30
                                ),
                                0.20
                            ),
                            0.30
                        )
                    ) * 100
                ) / 100
            WHEN 'decrease_acos_333' THEN
                CEIL(
                    e.current_bid * (
                        1 - LEAST(
                            GREATEST(
                                COALESCE(
                                    GREATEST(
                                        0,
                                        (e.current_bid - e.theoretical_cpc) / e.current_bid
                                    ),
                                    0.20
                                ),
                                0.10
                            ),
                            0.20
                        )
                    ) * 100
                ) / 100
            WHEN 'increase_high' THEN
                FLOOR(LEAST(e.theoretical_cpc, e.current_bid * 1.20) * 100) / 100
            WHEN 'increase_small' THEN
                FLOOR(LEAST(e.theoretical_cpc, e.current_bid * 1.10) * 100) / 100
            WHEN 'increase_blocked' THEN ROUND(e.current_bid, 2)
            WHEN 'keep' THEN ROUND(e.current_bid, 2)
            ELSE NULL
        END AS suggested_bid_raw,
        CASE
            WHEN e.decision_code = 'manual_review' THEN
                JSON_MERGE_PRESERVE(
                    IF(
                        e.msku_mapping_status <> 'mapped',
                        JSON_ARRAY(
                            CASE e.msku_mapping_status
                                WHEN 'period_multiple_msku' THEN 'period_multiple_msku'
                                WHEN 'current_multiple_msku' THEN 'current_multiple_msku'
                                WHEN 'msku_changed' THEN 'msku_changed'
                                ELSE 'msku_missing'
                            END
                        ),
                        JSON_ARRAY()
                    ),
                    IF(e.listing_price IS NULL, JSON_ARRAY('price_not_mapped'), JSON_ARRAY()),
                    IF(e.margin_ladder_complete = 0, JSON_ARRAY('margin_ladder_missing'), JSON_ARRAY()),
                    IF(e.below_zero_margin_price = 1, JSON_ARRAY('below_zero_margin_price'), JSON_ARRAY())
                )
            WHEN e.current_bid IS NULL OR e.current_bid <= 0
                THEN JSON_ARRAY('metric_missing')
            WHEN e.decision_code = 'decrease_no_order'
                THEN JSON_MERGE_PRESERVE(
                    JSON_ARRAY('clicks_ge_15_orders_zero'),
                    IF(e.theoretical_cpc IS NULL, JSON_ARRAY(), JSON_ARRAY('theoretical_cpc_guard'))
                )
            WHEN e.decision_code = 'decrease_acos_50'
                THEN JSON_MERGE_PRESERVE(
                    JSON_ARRAY('acos_gt_50'),
                    IF(e.theoretical_cpc IS NULL, JSON_ARRAY(), JSON_ARRAY('theoretical_cpc_guard'))
                )
            WHEN e.decision_code = 'decrease_acos_333'
                THEN JSON_MERGE_PRESERVE(
                    JSON_ARRAY('acos_gt_333'),
                    IF(e.theoretical_cpc IS NULL, JSON_ARRAY(), JSON_ARRAY('theoretical_cpc_guard'))
                )
            WHEN e.decision_code = 'increase_high'
                THEN JSON_ARRAY('high_cvr_increase', 'theoretical_cpc_guard')
            WHEN e.decision_code = 'increase_small'
                THEN JSON_ARRAY('site_avg_cvr_increase', 'theoretical_cpc_guard')
            WHEN e.decision_code = 'increase_blocked'
                THEN JSON_MERGE_PRESERVE(
                    IF(e.inventory_sufficient_flag = 0, JSON_ARRAY('inventory_blocks_increase'), JSON_ARRAY()),
                    IF(
                        e.monthly_ad_budget_cny IS NOT NULL
                        AND e.month_product_spend_cny IS NOT NULL
                        AND e.month_product_spend_cny >= e.monthly_ad_budget_cny,
                        JSON_ARRAY('budget_blocks_increase'),
                        JSON_ARRAY()
                    )
                )
            WHEN e.decision_code = 'keep'
                THEN JSON_ARRAY('performance_within_guardrail')
            WHEN e.theoretical_cpc IS NULL
                THEN JSON_ARRAY('metric_missing')
            ELSE JSON_ARRAY('threshold_not_met')
        END AS reason_codes_raw
    FROM tmp_spbo_eval e;
    ALTER TABLE tmp_spbo_scored
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id);

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_final;
    CREATE TEMPORARY TABLE tmp_spbo_final ENGINE=InnoDB AS
    SELECT
        prepared.*,
        CASE
            WHEN prepared.msku IS NULL THEN 0
            WHEN ROW_NUMBER() OVER (
                PARTITION BY snapshot_date, base_store_name, country_code, msku
                ORDER BY cost DESC, profile_id, campaign_id, ad_group_id, object_type, object_id
            ) = 1 THEN 1
            ELSE 0
        END AS product_metric_owner_flag
    FROM (
        SELECT
            s.*,
            SHA2(
                CONCAT_WS(
                    CHAR(31),
                    s.object_type,
                    s.profile_id,
                    s.campaign_id,
                    s.ad_group_id,
                    s.object_id,
                    COALESCE(s.object_text, ''),
                    COALESCE(s.match_type, '')
                ),
                256
            ) AS row_key,
            CASE
                WHEN s.decision_code = 'manual_review' THEN 'manual_review'
                WHEN s.decision_code LIKE 'decrease_%' THEN 'decrease'
                WHEN s.decision_code LIKE 'increase_%' THEN
                    CASE WHEN s.decision_code = 'increase_blocked' THEN 'keep' ELSE 'increase' END
                WHEN s.decision_code = 'keep' THEN 'keep'
                ELSE 'insufficient_data'
            END AS raw_recommendation_status,
            CASE
                WHEN s.decision_code IN (
                    'decrease_no_order', 'decrease_acos_50', 'decrease_acos_333',
                    'increase_high', 'increase_small'
                )
                 AND s.suggested_bid_raw = s.current_bid
                THEN 'keep'
                WHEN s.decision_code = 'manual_review' THEN 'manual_review'
                WHEN s.decision_code LIKE 'decrease_%' THEN 'decrease'
                WHEN s.decision_code IN ('increase_high', 'increase_small') THEN 'increase'
                WHEN s.decision_code IN ('increase_blocked', 'keep') THEN 'keep'
                WHEN s.current_bid IS NULL OR s.current_bid <= 0 THEN 'current_bid_missing'
                WHEN s.orders = 0 AND s.clicks < 15 THEN 'no_order_below_threshold'
                WHEN s.orders > 0 AND s.clicks < 20 THEN 'with_order_below_threshold'
                ELSE 'calculation_input_missing'
            END AS recommendation_status,
            CASE
                WHEN s.decision_code IN (
                    'decrease_no_order', 'decrease_acos_50', 'decrease_acos_333',
                    'increase_high', 'increase_small'
                )
                 AND s.suggested_bid_raw = s.current_bid
                THEN JSON_MERGE_PRESERVE(
                    s.reason_codes_raw,
                    JSON_ARRAY('minimum_bid_increment_blocks_change')
                )
                ELSE s.reason_codes_raw
            END AS reason_codes,
            CASE
                WHEN s.decision_code IN ('increase_high', 'increase_small')
                THEN s.suggested_bid_raw
                WHEN s.decision_code = 'increase_blocked'
                THEN s.current_bid
                ELSE NULL
            END AS max_allowed_bid,
            CASE
                WHEN s.suggested_bid_raw > s.current_bid THEN 'increase'
                WHEN s.suggested_bid_raw < s.current_bid THEN 'decrease'
                WHEN s.suggested_bid_raw IS NOT NULL THEN 'keep'
                ELSE NULL
            END AS change_direction,
            CASE
                WHEN s.suggested_bid_raw IS NOT NULL
                THEN ROUND(s.suggested_bid_raw - s.current_bid, 2)
                ELSE NULL
            END AS change_amount,
            CASE
                WHEN s.suggested_bid_raw IS NOT NULL AND s.current_bid <> 0
                THEN ROUND((s.suggested_bid_raw - s.current_bid) / s.current_bid, 4)
                ELSE NULL
            END AS change_rate,
            CASE
                WHEN s.decision_code = 'manual_review' THEN
                    CASE s.msku_mapping_status
                        WHEN 'period_multiple_msku' THEN '成熟窗口内投放过多个MSKU，需人工排查'
                        WHEN 'current_multiple_msku' THEN '当前同时启用多个MSKU，需人工排查'
                        WHEN 'msku_changed' THEN '成熟窗口商品与当前启用商品不一致，需人工排查'
                        WHEN 'period_record_missing' THEN '成熟窗口未找到推广MSKU，需人工排查'
                        WHEN 'current_record_missing' THEN '当前未找到启用MSKU，需人工排查'
                        ELSE 'Listing价格或毛利阶梯缺失，需人工排查'
                    END
                WHEN s.budget_support_status = '商品预算未匹配，需人工排查'
                    THEN '产品预算未匹配，预算保护状态未知'
                ELSE NULL
            END AS data_warning,
            CASE
                WHEN (
                    CASE
                        WHEN s.decision_code IN (
                            'decrease_no_order', 'decrease_acos_50', 'decrease_acos_333',
                            'increase_high', 'increase_small'
                        )
                         AND s.suggested_bid_raw = s.current_bid
                        THEN 'keep'
                        WHEN s.decision_code = 'manual_review' THEN 'manual_review'
                        WHEN s.decision_code LIKE 'decrease_%' THEN 'decrease'
                        WHEN s.decision_code IN ('increase_high', 'increase_small') THEN 'increase'
                        ELSE 'other'
                    END
                ) IN ('increase', 'decrease')
                THEN 1 ELSE 9
            END AS priority_rank
        FROM tmp_spbo_scored s
    ) prepared;
    ALTER TABLE tmp_spbo_final
        ADD PRIMARY KEY (profile_id, campaign_id, ad_group_id, object_type, object_id),
        ADD KEY idx_final_product (snapshot_date, base_store_name, country_code, msku);

    START TRANSACTION;

    DELETE FROM dws_datasync.dws_sp_bid_object_snapshot_daily
    WHERE snapshot_date = v_snapshot_date;

    INSERT INTO dws_datasync.dws_sp_bid_object_snapshot_daily (
        snapshot_date, row_key, rule_version, mature_start, mature_end,
        source_keyword_days, source_ad_group_days, source_product_ad_days,
        budget_snapshot_date, budget_performance_date,
        profile_id, sid, base_store_name, seller_name, country_code,
        currency_code, product_currency_code, exchange_rate_cny, budget_currency_code,
        campaign_id, campaign_name_current, campaign_state_current,
        campaign_serving_status, campaign_type, targeting_type, portfolio_id,
        daily_budget_current, bidding_strategy_current,
        placement_top_percentage, placement_product_page_percentage,
        placement_rest_of_search_percentage,
        ad_group_id, ad_group_name_current, ad_group_state_current,
        ad_group_serving_status, default_bid_current,
        object_type, object_id, object_text, object_state_current,
        object_serving_status, match_type,
        msku, asin, associated_msku_count, period_msku_count,
        current_enabled_msku_count, msku_mapping_status, product_metric_owner_flag,
        impressions, clicks, cost, orders, sales,
        attributed_orders_1d, attributed_orders_7d, attributed_orders_14d, attributed_orders_30d,
        attributed_sales_1d, attributed_sales_7d, attributed_sales_14d, attributed_sales_30d,
        attributed_units_1d, attributed_units_7d, attributed_units_14d, attributed_units_30d,
        same_sku_attributed_orders_1d, same_sku_attributed_orders_7d, same_sku_attributed_orders_14d, same_sku_attributed_orders_30d,
        same_sku_attributed_sales_1d, same_sku_attributed_sales_7d, same_sku_attributed_sales_14d, same_sku_attributed_sales_30d,
        same_sku_attributed_units_1d, same_sku_attributed_units_7d, same_sku_attributed_units_14d, same_sku_attributed_units_30d,
        aov, ctr, cpc, cvr, acos, roas,
        current_bid, listing_price, margin_rate, site_cvr_avg, site_cvr_p75,
        theoretical_cpc, reference_cpc_20, reference_cpc_333,
        suggested_bid, max_allowed_bid, change_direction, change_amount, change_rate,
        bid_lower_limit, bid_upper_limit,
        raw_recommendation_status, recommendation_status, priority_rank,
        reason_codes, data_warning,
        monthly_ad_budget_original, monthly_ad_budget_cny,
        weekly_ad_budget_original, weekly_ad_budget_cny,
        month_product_spend_cny, spend_7d_cny,
        monthly_remaining_budget_cny, weekly_remaining_budget_cny,
        monthly_budget_usage_rate, weekly_budget_usage_rate, month_progress_rate,
        monthly_budget_status, weekly_budget_status, budget_config_status,
        budget_support_status, budget_anomalies, site_total_budget_cny,
        inventory_sufficient_flag, weekly_inventory_sufficient_flag,
        source_latest_create_time, created_at, updated_at
    )
    SELECT
        f.snapshot_date, f.row_key, v_rule_version, v_mature_start, v_mature_end,
        v_keyword_days, v_ad_group_days, v_product_ad_days,
        f.budget_snapshot_date, f.budget_performance_date,
        f.profile_id, NULLIF(f.sid, 0), f.base_store_name, f.seller_name,
        f.country_code, f.currency_code, f.product_currency_code,
        f.exchange_rate_cny, 'CNY',
        f.campaign_id, f.campaign_name_current, f.campaign_state_current,
        f.campaign_serving_status, f.campaign_type, f.targeting_type, f.portfolio_id,
        f.daily_budget_current, f.bidding_strategy_current,
        f.placement_top_percentage, f.placement_product_page_percentage,
        f.placement_rest_of_search_percentage,
        f.ad_group_id, f.ad_group_name_current, f.ad_group_state_current,
        f.ad_group_serving_status, f.default_bid_current,
        f.object_type, f.object_id, f.object_text, f.object_state_current,
        f.object_serving_status, f.match_type,
        f.msku, f.asin, f.associated_msku_count, f.period_msku_count,
        f.current_enabled_msku_count, f.msku_mapping_status,
        f.product_metric_owner_flag,
        f.impressions, f.clicks, f.cost, f.orders, f.sales,
        f.attributed_orders_1d, f.attributed_orders_7d, f.attributed_orders_14d, f.attributed_orders_30d,
        f.attributed_sales_1d, f.attributed_sales_7d, f.attributed_sales_14d, f.attributed_sales_30d,
        f.attributed_units_1d, f.attributed_units_7d, f.attributed_units_14d, f.attributed_units_30d,
        f.same_sku_attributed_orders_1d, f.same_sku_attributed_orders_7d, f.same_sku_attributed_orders_14d, f.same_sku_attributed_orders_30d,
        f.same_sku_attributed_sales_1d, f.same_sku_attributed_sales_7d, f.same_sku_attributed_sales_14d, f.same_sku_attributed_sales_30d,
        f.same_sku_attributed_units_1d, f.same_sku_attributed_units_7d, f.same_sku_attributed_units_14d, f.same_sku_attributed_units_30d,
        f.aov, f.ctr, f.cpc, f.cvr, f.acos, f.roas,
        f.current_bid, f.listing_price, f.margin_rate,
        f.site_cvr_avg, f.site_cvr_p75,
        CASE
            WHEN f.decision_code = 'manual_review'
              OR f.current_bid IS NULL OR f.current_bid <= 0
            THEN NULL ELSE ROUND(f.theoretical_cpc, 4)
        END,
        CASE
            WHEN f.decision_code = 'manual_review'
              OR f.current_bid IS NULL OR f.current_bid <= 0
            THEN NULL ELSE ROUND(f.reference_cpc_20, 4)
        END,
        CASE
            WHEN f.decision_code = 'manual_review'
              OR f.current_bid IS NULL OR f.current_bid <= 0
            THEN NULL ELSE ROUND(f.reference_cpc_333, 4)
        END,
        f.suggested_bid_raw, f.max_allowed_bid,
        f.change_direction, f.change_amount, f.change_rate,
        NULL, NULL,
        f.raw_recommendation_status, f.recommendation_status, f.priority_rank,
        f.reason_codes, f.data_warning,
        f.monthly_ad_budget_original, f.monthly_ad_budget_cny,
        f.weekly_ad_budget_original, f.weekly_ad_budget_cny,
        f.month_product_spend_cny, f.spend_7d_cny,
        f.monthly_remaining_budget_cny, f.weekly_remaining_budget_cny,
        f.monthly_budget_usage_rate, f.weekly_budget_usage_rate,
        f.month_progress_rate,
        f.monthly_budget_status, f.weekly_budget_status, f.budget_config_status,
        f.budget_support_status, f.budget_anomalies, f.site_total_budget_cny,
        f.inventory_sufficient_flag, f.weekly_inventory_sufficient_flag,
        f.enriched_source_time, NOW(), NOW()
    FROM tmp_spbo_final f;

    /* 先成功写入当天快照，再按不同快照日期保留最新7份。 */
    DELETE FROM dws_datasync.dws_sp_bid_object_snapshot_daily
    WHERE snapshot_date NOT IN (
        SELECT keep_date
        FROM (
            SELECT DISTINCT snapshot_date AS keep_date
            FROM dws_datasync.dws_sp_bid_object_snapshot_daily
            ORDER BY snapshot_date DESC
            LIMIT 7
        ) latest_seven
    );

    COMMIT;

    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_final;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_scored;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_eval;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_enriched;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_limit_price;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_listing;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_spend;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_budget;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_fx;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_benchmark;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_p75;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_cvr_ranked;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_product;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_product_map;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_period_product;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_current_product;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_object_raw;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_auto_metric;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_metric;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_keyword_current;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_ad_group_current;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_campaign_current;
    DROP TEMPORARY TABLE IF EXISTS tmp_spbo_account_current;

    DO RELEASE_LOCK('dws_datasync.sp_refresh_sp_bid_object_snapshot_daily');
    SET v_lock_acquired = 0;
END$$

DELIMITER ;

/*
手工执行示例（本文件不会自动执行）：

CALL dws_datasync.sp_refresh_sp_bid_object_snapshot_daily(NULL);
CALL dws_datasync.sp_refresh_sp_bid_object_snapshot_daily('2026-09-09');
*/
