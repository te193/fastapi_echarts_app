create
    definer = analysis_zhr@`%` procedure sp_dws_标签表_一体化_v45(IN p_data_date date)
BEGIN
    -- 先统一锁定本次业务日期，确保基础标签与站点标签使用同一天，避免两阶段之间源表更新导致日期不一致。
    DECLARE v_run_data_date DATE DEFAULT NULL;
    DECLARE v_locked_max_source_date DATE DEFAULT NULL;

    -- 整个过程只读取一次最大业务日期；基础标签与站点标签共用锁定日期，避免重复扫描源表。
    SELECT MAX(DATE(`start_date`))
    INTO v_locked_max_source_date
    FROM `dwd_datasync`.`lx_statistics_product_performance`;

    IF v_locked_max_source_date IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '产品表现表不存在可用业务日期，无法执行标签计算';
    END IF;

    SET v_run_data_date = COALESCE(p_data_date, v_locked_max_source_date);

    IF v_run_data_date > v_locked_max_source_date THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '指定业务日期晚于产品表现表最新业务日期，禁止执行';
    END IF;

    -- ========================================================================
    -- 阶段 1：基础标签（V37 sp_dws_标签表_按日期_v37 的原逻辑内联）
    -- ========================================================================
    BEGIN
            DECLARE v_data_date date DEFAULT NULL;
            DECLARE v_max_source_date date DEFAULT NULL;
            DECLARE v_next_date date DEFAULT NULL;
            DECLARE v_7d date DEFAULT NULL;
            DECLARE v_14d date DEFAULT NULL;
            DECLARE v_30d date DEFAULT NULL;
            DECLARE v_90d date DEFAULT NULL;
            DECLARE v_180d date DEFAULT NULL;
            DECLARE v_proc_name varchar(255) DEFAULT 'sp_dws_标签表_一体化_v45_基础标签';
            DECLARE v_log_id int DEFAULT NULL;
            DECLARE v_record_count int DEFAULT 0;
            DECLARE v_error_msg text;
            DECLARE v_stage varchar(255) DEFAULT '初始化';

            DECLARE EXIT HANDLER FOR SQLEXCEPTION
            BEGIN
                GET DIAGNOSTICS CONDITION 1 v_error_msg = MESSAGE_TEXT;
                SET v_error_msg = CONCAT('[执行阶段：', v_stage, '] ', v_error_msg);
                ROLLBACK;

                IF v_log_id IS NOT NULL THEN
                    UPDATE `etl_datasync`.`etl_execution_log`
                    SET `status` = 'error',
                        `end_time` = NOW()
                    WHERE `id` = v_log_id;

                    INSERT INTO `etl_datasync`.`etl_error_log`
                        (`proc_name`, `error_time`, `error_message`, `execution_log_id`)
                    VALUES
                        (v_proc_name, NOW(), v_error_msg, v_log_id);
                END IF;

                -- 不吞掉异常，避免客户端看到“执行成功”但标签未写入。
                RESIGNAL;
            END;

            INSERT INTO `etl_datasync`.`etl_execution_log`
                (`proc_name`, `start_time`, `status`)
            VALUES
                (v_proc_name, NOW(), 'started');

            SET v_log_id = LAST_INSERT_ID();

            -- 复用外层已锁定并校验过的业务日期；不再重复扫描产品表现表取 MAX(start_date)。
            SET v_max_source_date = v_locked_max_source_date;
            SET v_data_date = v_run_data_date;

            IF v_data_date IS NOT NULL THEN
                SET v_next_date = DATE_ADD(v_data_date, INTERVAL 1 DAY);
                SET v_7d = DATE_SUB(v_data_date, INTERVAL 6 DAY);
                SET v_14d = DATE_SUB(v_data_date, INTERVAL 13 DAY);
                SET v_30d = DATE_SUB(v_data_date, INTERVAL 29 DAY);
                SET v_90d = DATE_SUB(v_data_date, INTERVAL 89 DAY);
                -- 最近180个自然日包含统计日当天，因此起始日为统计日往前179天。
                SET v_180d = DATE_SUB(v_data_date, INTERVAL 179 DAY);

                SET v_stage = 'tmp_active_labels';

                DROP TEMPORARY TABLE IF EXISTS tmp_active_labels;
                CREATE TEMPORARY TABLE tmp_active_labels AS
                SELECT DISTINCT CAST(`label_name` AS CHAR(100))     label_name,
                                CAST(`sub_label_name` AS CHAR(100)) sub_label_name,
                                `sub_label_id`                      sub_label_id
                FROM `dws_datasync`.`dws_标签详情表`
                WHERE CAST(`status` AS CHAR) = '启用'
                  AND `label_name` IS NOT NULL
                  AND `sub_label_name` IS NOT NULL;


                SET v_stage = 'tmp_listing_latest';
                -- 全量 Listing 最新同步记录：每个 marketplace+seller+seller_sku 仅保留 create_time 最大的一条。
                -- 同时排除退款占位 SKU（amzn.gr 开头）和 Amazon 占位 SKU（Amazon 开头，大小写不敏感）。
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_latest;
                CREATE TEMPORARY TABLE tmp_listing_latest AS
                SELECT CAST(li.`marketplace` AS CHAR(50))  AS marketplace,
                       CAST(li.`seller_name` AS CHAR(50))  AS seller_name,
                       CAST(li.`seller_sku` AS CHAR(255)) AS seller_sku,
                       li.`create_time`,
                       CAST(li.`status` AS CHAR(50))      AS listing_status
                FROM (
                    SELECT li.`marketplace`,
                           li.`seller_name`,
                           li.`seller_sku`,
                           li.`create_time`,
                           li.`status`,
                           li.`id` AS listing_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST(li.`marketplace` AS CHAR), CAST(li.`seller_name` AS CHAR), CAST(li.`seller_sku` AS CHAR)
                               ORDER BY li.`create_time` DESC, li.`id` DESC
                           ) AS rn
                    FROM `dwd_datasync`.`lx_sales_mws_listing` li
                    WHERE li.`seller_sku` IS NOT NULL
                      AND CAST(li.`seller_sku` AS CHAR) <> ''
                      AND LOWER(TRIM(CAST(li.`seller_sku` AS CHAR))) NOT LIKE 'amzn.gr%'
                      AND UPPER(TRIM(CAST(li.`seller_sku` AS CHAR))) NOT LIKE 'AMAZON%'
                ) li
                WHERE li.rn = 1;
                ALTER TABLE tmp_listing_latest
                    ADD INDEX idx_tmp_listing_latest (marketplace, seller_name, seller_sku);

                SET v_stage = 'tmp_listing_keys';
                -- 以 tmp_listing_latest 为全量维度主表，生成国家类别+店铺+MSKU 主键。
                -- tmp_listing_latest 已只保留每个 marketplace+seller+seller_sku 最新 create_time 记录，并排除 amzn.gr 和 Amazon 开头 SKU。
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_keys;
                CREATE TEMPORARY TABLE tmp_listing_keys AS
                SELECT DISTINCT
                       CASE
                           WHEN CAST(li.`marketplace` AS CHAR) = '英国' THEN '英国站'
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                           ELSE '欧洲站' END AS country_category,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                   SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1),
                                   LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1) END AS store,
                       CAST(li.`seller_sku` AS CHAR(255)) AS msku
                FROM tmp_listing_latest li;
                ALTER TABLE tmp_listing_keys
                    ADD INDEX idx_tmp_listing_keys (country_category, store, MSKU);
                -- 性能优化：产品表现表约 360 万行且仅有主键索引。以下临时表只保留本次标签涉及的
                -- 国家类别+店铺+MSKU，并一次完成国家/店铺/MSKU/日期标准化；后续断货、创建日期、
                -- 客户体验、站点状态、流量结构均复用本表，标签规则和时间口径不变。
                -- 产品表现明细读取2026年至统计日的全部现有历史。
                -- 返厂事件需要先利用完整历史识别断货起点和返场轮次，再在事件层筛选最近180天；
                -- 其他标签规则仍分别在7/14/30/90/180天窗口内计算，不改变其业务口径。
                SET v_stage = 'tmp_perf_scoped';
                DROP TEMPORARY TABLE IF EXISTS tmp_perf_scoped;
                CREATE TEMPORARY TABLE tmp_perf_scoped AS
                SELECT k.country_category,
                       CAST(p.`country` AS CHAR(100)) AS source_country,
                       k.store AS perf_store,
                       k.MSKU AS perf_msku,
                       DATE(p.`start_date`) AS stat_date,
                       p.`product_create_time`,
                       p.`afn_fulfillable_quantity`,
                       p.`volume`,
                       p.`spend`,
                       p.`amount`,
                       p.`avg_star`,
                       p.`predict_gross_profit`
                FROM tmp_listing_keys k
                         LEFT JOIN `dwd_datasync`.`lx_statistics_product_performance` p
                                    ON k.country_category = CASE
                                                                WHEN CAST(p.`country` AS CHAR) = '英国' THEN '英国站'
                                                                WHEN CAST(p.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                                                ELSE '欧洲站' END
                                       AND k.store = CASE
                                                         WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) > 0
                                                             THEN LEFT(SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1),
                                                                       LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) - 1)
                                                         ELSE SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1) END
                                       AND k.MSKU = CAST(p.`seller_sku` AS CHAR)
                                       AND DATE(p.`start_date`) BETWEEN DATE('2026-01-01') AND v_data_date;
                ALTER TABLE tmp_perf_scoped
                    ADD INDEX idx_tmp_perf_scoped_date_key (stat_date, country_category, perf_store, perf_msku),
                    ADD INDEX idx_tmp_perf_scoped_key_date (country_category, perf_store, perf_msku, stat_date);
                -- 基础销售指标直接复用已裁剪为最近 180 天的产品表现临时表；销售角色仍严格使用 7/14/30/90 天原窗口。
                SET v_stage = 'tmp_perf';
                DROP TEMPORARY TABLE IF EXISTS tmp_perf;
                CREATE TEMPORARY TABLE tmp_perf AS
                SELECT k.country_category,
                       NULL                  AS                                                         country,
                       k.store,
                       k.MSKU,
                       MIN(CASE
                               WHEN ps.`product_create_time` REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                                   THEN STR_TO_DATE(LEFT(ps.`product_create_time`, 10), '%Y-%m-%d') END) product_create_date,
                       SUM(CASE
                               WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(ps.`volume`, 0)
                               ELSE 0 END) / 7.0                                                        vol_7d,
                       SUM(CASE
                               WHEN ps.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(ps.`volume`, 0)
                               ELSE 0 END) / 14.0                                                       vol_14d,
                       SUM(CASE
                               WHEN ps.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(ps.`volume`, 0)
                               ELSE 0 END) / 30.0                                                       vol_30d,
                       SUM(CASE
                               WHEN ps.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(ps.`volume`, 0)
                               ELSE 0 END) / 90.0                                                       vol_90d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(ps.`amount`, 0) ELSE 0 END) AS sales_amount_7d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(ps.`amount`, 0) ELSE 0 END) AS sales_amount_14d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(ps.`amount`, 0) ELSE 0 END) AS sales_amount_30d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(ps.`amount`, 0) ELSE 0 END) AS sales_amount_90d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0 ELSE COALESCE(ps.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_7d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_14d AND v_data_date THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0 ELSE COALESCE(ps.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_14d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_30d AND v_data_date THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0 ELSE COALESCE(ps.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_30d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_90d AND v_data_date THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0 ELSE COALESCE(ps.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_90d,
                       CASE
                           WHEN SUM(CASE
                                        WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(ps.`amount`, 0)
                                        ELSE 0 END) > 0 THEN SUM(CASE
                                                                     WHEN ps.stat_date BETWEEN v_7d AND v_data_date
                                                                         THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0
                                                                                   ELSE COALESCE(ps.`predict_gross_profit`, 0) END
                                                                     ELSE 0 END) / SUM(CASE
                                                                                           WHEN ps.stat_date BETWEEN v_7d AND v_data_date
                                                                                               THEN COALESCE(ps.`amount`, 0)
                                                                                           ELSE 0 END) * 100
                           ELSE 0 END                                                                   margin_7d,
                       CASE
                           WHEN SUM(CASE
                                        WHEN ps.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(ps.`amount`, 0)
                                        ELSE 0 END) > 0 THEN SUM(CASE
                                                                     WHEN ps.stat_date BETWEEN v_14d AND v_data_date
                                                                         THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0
                                                                                   ELSE COALESCE(ps.`predict_gross_profit`, 0) END
                                                                     ELSE 0 END) / SUM(CASE
                                                                                           WHEN ps.stat_date BETWEEN v_14d AND v_data_date
                                                                                               THEN COALESCE(ps.`amount`, 0)
                                                                                           ELSE 0 END) * 100
                           ELSE 0 END                                                                   margin_14d,
                       CASE
                           WHEN SUM(CASE
                                        WHEN ps.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(ps.`amount`, 0)
                                        ELSE 0 END) > 0 THEN SUM(CASE
                                                                     WHEN ps.stat_date BETWEEN v_30d AND v_data_date
                                                                         THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0
                                                                                   ELSE COALESCE(ps.`predict_gross_profit`, 0) END
                                                                     ELSE 0 END) / SUM(CASE
                                                                                           WHEN ps.stat_date BETWEEN v_30d AND v_data_date
                                                                                               THEN COALESCE(ps.`amount`, 0)
                                                                                           ELSE 0 END) * 100
                           ELSE 0 END                                                                   margin_30d,
                       CASE
                           WHEN SUM(CASE
                                        WHEN ps.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(ps.`amount`, 0)
                                        ELSE 0 END) > 0 THEN SUM(CASE
                                                                     WHEN ps.stat_date BETWEEN v_90d AND v_data_date
                                                                         THEN CASE WHEN COALESCE(ps.`volume`, 0) = 0 THEN 0
                                                                                   ELSE COALESCE(ps.`predict_gross_profit`, 0) END
                                                                     ELSE 0 END) / SUM(CASE
                                                                                           WHEN ps.stat_date BETWEEN v_90d AND v_data_date
                                                                                               THEN COALESCE(ps.`amount`, 0)
                                                                                           ELSE 0 END) * 100
                           ELSE 0 END                                                                   margin_90d,
                       SUM(CASE
                               WHEN ps.stat_date = v_data_date THEN COALESCE(ps.`afn_fulfillable_quantity`, 0)
                               ELSE 0 END)                                                              fba_current,
                       SUM(COALESCE(ps.`volume`, 0))                                                     vol_stat_period,
                       0                                                                                has_fba_oos_stat_period,
                       MAX(CASE WHEN ps.source_country IS NOT NULL THEN 1 ELSE 0 END)                              AS has_product_data
                FROM tmp_listing_keys k
                LEFT JOIN tmp_perf_scoped ps
                  ON k.country_category = ps.country_category
                 AND k.store = ps.perf_store
                 AND k.MSKU = ps.perf_msku
                 AND ps.stat_date BETWEEN v_90d AND v_data_date
                GROUP BY k.country_category, k.store, k.MSKU;

                -- 返厂品识别所需的站点级库存日表：按国家类别+店铺+MSKU+日期聚合。
                -- 同一站点不同国家库存共享时，站点级有效FBA可售库存取MAX(FBA可售库存)。
                -- 此处保留2026年至统计日的完整历史，避免在事件识别前截断跨越180天边界的断货段。
                -- 当前“断货中”不使用本表，而是单独按业务日期当天产品表现 FBA 可售库存=0 且 Listing 当前停售判断。
                SET v_stage = 'tmp_oos_perf_daily';
                DROP TEMPORARY TABLE IF EXISTS tmp_oos_perf_daily;
                CREATE TEMPORARY TABLE tmp_oos_perf_daily AS
                SELECT country_category,
                       perf_store AS store,
                       perf_msku AS MSKU,
                       stat_date,
                       MAX(COALESCE(afn_fulfillable_quantity, 0)) AS site_fba_available,
                       SUM(COALESCE(volume, 0)) AS site_sales_volume
                FROM tmp_perf_scoped
                WHERE stat_date BETWEEN DATE('2026-01-01') AND v_data_date
                GROUP BY country_category, perf_store, perf_msku, stat_date;
                ALTER TABLE tmp_oos_perf_daily
                    ADD INDEX idx_tmp_oos_perf_daily (country_category, store, MSKU, stat_date);

                -- 但“断货中”依赖当前 Listing 是否停售，后续仍需构建 Listing 状态临时表。
                -- 首次到货日：按国家类别+店铺+MSKU取 lx_fba_shipment.receiving_time 的最小日期；仅取不晚于打标日的有效日期。
                SET v_stage = 'tmp_first_receiving';
                DROP TEMPORARY TABLE IF EXISTS tmp_first_receiving;
                CREATE TEMPORARY TABLE tmp_first_receiving AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       MIN(STR_TO_DATE(LEFT(CAST(s.`receiving_time` AS CHAR), 10), '%Y-%m-%d')) AS first_receiving_date
                FROM tmp_listing_keys k
                         JOIN `dwd_datasync`.`lx_fba_shipment` s
                              ON k.country_category = CASE
                                                          WHEN CAST(s.`country` AS CHAR) = '英国' THEN '英国站'
                                                          WHEN CAST(s.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                                          ELSE '欧洲站' END
                             AND k.store = CASE
                                               WHEN LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                                       SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1),
                                                       LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) - 1)
                                               ELSE SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1) END
                             AND k.MSKU = CAST(s.`msku` AS CHAR)
                WHERE CAST(s.`receiving_time` AS CHAR) REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                  AND STR_TO_DATE(LEFT(CAST(s.`receiving_time` AS CHAR), 10), '%Y-%m-%d') <= v_data_date
                GROUP BY k.country_category, k.store, k.MSKU;
                ALTER TABLE tmp_first_receiving
                    ADD INDEX idx_tmp_first_receiving (country_category, store, MSKU, first_receiving_date);

                -- 新版运营状态不再以 Listing 的“在售/停售”状态作为断货或停售判定条件；
                -- Listing 仍仅作为商品池主表使用。

                SET v_stage = 'tmp_fba';

                DROP TEMPORARY TABLE IF EXISTS tmp_fba;
                CREATE TEMPORARY TABLE tmp_fba AS
                SELECT CAST(f.`country_category` AS CHAR)                                      country_category,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                   SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1),
                                   LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1) END store,
                       CAST(f.`seller_sku_adj` AS CHAR)                                        MSKU,
                       SUM(COALESCE(f.`total`, 0))                                             total_stock,
                       SUM(COALESCE(f.`available_total`, 0))                                   available_stock,
                       SUM(COALESCE(f.`stock_up_num`, 0))                                      stock_up_num
                FROM `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` f
                WHERE f.`create_time` >= DATE_SUB(v_data_date, INTERVAL 1 DAY)
                  AND f.`create_time` < DATE_ADD(v_data_date, INTERVAL 1 DAY)
                  AND f.`seller_sku_adj` IS NOT NULL
                  AND CAST(f.`seller_sku_adj` AS CHAR) <> ''
                GROUP BY country_category, store, MSKU;

                SET v_stage = 'tmp_stock';

                DROP TEMPORARY TABLE IF EXISTS tmp_stock;
                CREATE TEMPORARY TABLE tmp_stock AS
                SELECT p.country_category,
                       NULL AS                                                 country,
                       p.store,
                       p.MSKU,
                       COALESCE(MAX(f.total_stock), MAX(p.fba_current), 0)     total_stock,
                       COALESCE(MAX(f.available_stock), MAX(p.fba_current), 0) available_stock,
                       COALESCE(MAX(f.stock_up_num), 0)                        stock_up_num,
                       MAX(p.vol_90d)                                          vol_90d
                FROM tmp_perf p
                         LEFT JOIN tmp_fba f
                                   ON p.country_category = f.country_category AND p.store = f.store AND p.MSKU = f.MSKU
                GROUP BY p.country_category, p.store, p.MSKU;

                -- 运营状态专用 FBA 库存：只用于“断货中/停售/测款扶持/正常在售”判定。
                -- 每个国家类别+店铺+MSKU 先取不晚于业务日的最新同步时点，再汇总该时点的库存明细，
                -- FBA 可售库存使用 afn_fulfillable_quantity；FBA 在途使用 stock_up_num。
                SET v_stage = 'tmp_op_fba_latest_key';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_fba_latest_key;
                CREATE TEMPORARY TABLE tmp_op_fba_latest_key AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       MAX(f.`create_time`) AS max_create_time
                FROM tmp_listing_keys k
                         JOIN `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` f
                              ON k.country_category = CAST(f.`country_category` AS CHAR)
                                 AND k.store = CASE
                                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                                       THEN LEFT(SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1),
                                                                 LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                                                   ELSE SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)
                                               END
                                 AND k.MSKU = CAST(f.`seller_sku_adj` AS CHAR)
                WHERE f.`create_time` < v_next_date
                GROUP BY k.country_category, k.store, k.MSKU;
                ALTER TABLE tmp_op_fba_latest_key
                    ADD INDEX idx_tmp_op_fba_latest_key (country_category, store, MSKU, max_create_time);

                SET v_stage = 'tmp_op_fba';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_fba;
                CREATE TEMPORARY TABLE tmp_op_fba AS
                SELECT x.country_category,
                       x.store,
                       x.MSKU,
                       SUM(COALESCE(f.`afn_fulfillable_quantity`, 0)) AS fba_available,
                       SUM(COALESCE(f.`stock_up_num`, 0)) AS fba_in_transit
                FROM tmp_op_fba_latest_key x
                         JOIN `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` f
                              ON x.country_category = CAST(f.`country_category` AS CHAR)
                                 AND x.store = CASE
                                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                                       THEN LEFT(SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1),
                                                                 LOCATE('-', SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                                                   ELSE SUBSTRING_INDEX(CAST(f.`seller_name_new` AS CHAR), ' ', 1)
                                               END
                                 AND x.MSKU = CAST(f.`seller_sku_adj` AS CHAR)
                                 AND f.`create_time` = x.max_create_time
                GROUP BY x.country_category, x.store, x.MSKU;
                ALTER TABLE tmp_op_fba
                    ADD INDEX idx_tmp_op_fba (country_category, store, MSKU);

                -- 运营状态专用本地仓数量：四个原始字段分别取最新同步时点的 MAX，
                -- 再相加，避免同一 MSKU 在源表多行明细时重复累加。
                SET v_stage = 'tmp_op_local_latest_key';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_local_latest_key;
                CREATE TEMPORARY TABLE tmp_op_local_latest_key AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       MAX(r.`create_time`) AS max_create_time
                FROM tmp_listing_keys k
                         JOIN `etl_datasync`.`etl_dispose_lx_replenishment_suggest_restocking` r
                              ON k.country_category = CAST(r.`country_category` AS CHAR)
                                 AND k.store = CASE
                                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                                       THEN LEFT(SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1),
                                                                 LOCATE('-', SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                                                   ELSE SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)
                                               END
                                 AND k.MSKU = CAST(r.`seller_sku_adj` AS CHAR)
                WHERE r.`create_time` < v_next_date
                GROUP BY k.country_category, k.store, k.MSKU;
                ALTER TABLE tmp_op_local_latest_key
                    ADD INDEX idx_tmp_op_local_latest_key (country_category, store, MSKU, max_create_time);

                SET v_stage = 'tmp_op_local';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_local;
                CREATE TEMPORARY TABLE tmp_op_local AS
                SELECT x.country_category,
                       x.store,
                       x.MSKU,
                       MAX(COALESCE(r.`sc_quantity_local_valid`, 0))
                       + MAX(COALESCE(r.`sc_quantity_purchase_shipping`, 0))
                       + MAX(COALESCE(r.`sc_quantity_purchase_plan`, 0))
                       + MAX(COALESCE(r.`sc_quantity_local_qc`, 0)) AS local_quantity
                FROM tmp_op_local_latest_key x
                         JOIN `etl_datasync`.`etl_dispose_lx_replenishment_suggest_restocking` r
                              ON x.country_category = CAST(r.`country_category` AS CHAR)
                                 AND x.store = CASE
                                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                                       THEN LEFT(SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1),
                                                                 LOCATE('-', SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                                                   ELSE SUBSTRING_INDEX(CAST(r.`seller_name_new` AS CHAR), ' ', 1)
                                               END
                                 AND x.MSKU = CAST(r.`seller_sku_adj` AS CHAR)
                                 AND r.`create_time` = x.max_create_time
                GROUP BY x.country_category, x.store, x.MSKU;
                ALTER TABLE tmp_op_local
                    ADD INDEX idx_tmp_op_local (country_category, store, MSKU);

                SET v_stage = 'tmp_price';

                DROP TEMPORARY TABLE IF EXISTS tmp_price;
                CREATE TEMPORARY TABLE tmp_price AS
                SELECT country_category,
                       country,
                       store,
                       MSKU,
                       SUBSTRING_INDEX(GROUP_CONCAT(price_label ORDER BY price_priority SEPARATOR ','), ',', 1) price_label
                FROM (SELECT CASE
                                 WHEN CAST(t.`国家` AS CHAR) = '英国' THEN '英国站'
                                 WHEN CAST(t.`国家` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                 ELSE COALESCE(CAST(t.`国家类别` AS CHAR), '欧洲站') END        country_category,
                             CAST(t.`国家` AS CHAR)                                             country,
                             CASE
                                 WHEN LOCATE('-', SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                         SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1),
                                         LOCATE('-', SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1)) - 1)
                                 ELSE SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1) END     store,
                             CAST(t.`msku` AS CHAR)                                             MSKU,
                             CASE
                                 WHEN t.`listing价格` IS NULL THEN NULL
                                 WHEN (t.`0毛利润价格` IS NOT NULL AND t.`listing价格` < t.`0毛利润价格`) OR
                                      (t.`清货底价` IS NOT NULL AND t.`listing价格` < t.`清货底价`) THEN '清仓区'
                                 WHEN t.`listing价格` >= t.`0毛利润价格` AND t.`listing价格` < t.`10毛利润价格` THEN '微利区'
                                 WHEN t.`listing价格` >= t.`10毛利润价格` AND t.`listing价格` < t.`20毛利润价格` THEN '基础利润区'
                                 WHEN t.`listing价格` >= t.`20毛利润价格` AND t.`listing价格` < t.`30毛利润价格` THEN '健康利润区'
                                 WHEN t.`listing价格` >= t.`30毛利润价格` THEN '超额利润区' END price_label,
                             CASE
                                 WHEN (t.`0毛利润价格` IS NOT NULL AND t.`listing价格` < t.`0毛利润价格`) OR
                                      (t.`清货底价` IS NOT NULL AND t.`listing价格` < t.`清货底价`) THEN 1
                                 WHEN t.`listing价格` < t.`10毛利润价格` THEN 2
                                 WHEN t.`listing价格` < t.`20毛利润价格` THEN 3
                                 WHEN t.`listing价格` < t.`30毛利润价格` THEN 4
                                 WHEN t.`listing价格` >= t.`30毛利润价格` THEN 5
                                 ELSE 999 END                                                   price_priority
                      FROM `temporary_dwd`.`在库节点_输出定价表` t
                      WHERE t.`msku` IS NOT NULL
                        AND CAST(t.`msku` AS CHAR) <> ''
                        AND LOWER(TRIM(CAST(t.`msku` AS CHAR))) NOT LIKE 'amzn.gr%'
                        AND UPPER(TRIM(CAST(t.`msku` AS CHAR))) NOT LIKE 'AMAZON%') a
                WHERE price_label IS NOT NULL
                GROUP BY country_category, country, store, MSKU;

                -- 返厂品/返场事件 V45：先使用2026年至统计日的完整历史识别
                -- “首次库存=0 -> 后续首次库存>5”的返场轮次，再按返场开始日筛选最近180天。
                -- 同一MSKU存在多轮时仅使用最新一轮已完成返场事件；返场开始日为D1。
                SET v_stage = 'tmp_return_perf_daily';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_perf_daily;
                CREATE TEMPORARY TABLE tmp_return_perf_daily AS
                SELECT country_category,
                       store,
                       MSKU,
                       stat_date,
                       site_fba_available,
                       site_sales_volume
                FROM tmp_oos_perf_daily
                WHERE stat_date BETWEEN DATE('2026-01-01') AND v_data_date;
                ALTER TABLE tmp_return_perf_daily
                    ADD INDEX idx_tmp_return_perf_daily (country_category, store, MSKU, stat_date);

                -- 对每个库存=0日期，记录其前面最近一次库存>5的日期；同一previous_gt5_date属于同一轮断货。
                SET v_stage = 'tmp_return_zero_sequence';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_zero_sequence;
                CREATE TEMPORARY TABLE tmp_return_zero_sequence AS
                SELECT country_category,
                       store,
                       MSKU,
                       stat_date,
                       site_fba_available,
                       MAX(CASE WHEN site_fba_available > 5 THEN stat_date END) OVER (
                           PARTITION BY country_category, store, MSKU
                           ORDER BY stat_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS previous_gt5_date
                FROM tmp_return_perf_daily;
                ALTER TABLE tmp_return_zero_sequence
                    ADD INDEX idx_tmp_return_zero_sequence (country_category, store, MSKU, previous_gt5_date, stat_date);

                -- 每轮断货日期取该轮第一次出现FBA可售库存=0的日期，不取返场前最后一个0。
                SET v_stage = 'tmp_return_oos_rounds';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_oos_rounds;
                CREATE TEMPORARY TABLE tmp_return_oos_rounds AS
                SELECT country_category,
                       store,
                       MSKU,
                       previous_gt5_date,
                       MIN(stat_date) AS oos_start_date
                FROM tmp_return_zero_sequence
                WHERE site_fba_available = 0
                  AND stat_date BETWEEN DATE('2026-01-01') AND v_data_date
                GROUP BY country_category, store, MSKU, previous_gt5_date;
                ALTER TABLE tmp_return_oos_rounds
                    ADD INDEX idx_tmp_return_oos_rounds (country_category, store, MSKU, oos_start_date);

                -- 断货后首次FBA可售库存>5时完成一轮返场。
                SET v_stage = 'tmp_return_completed_rounds';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_completed_rounds;
                CREATE TEMPORARY TABLE tmp_return_completed_rounds AS
                SELECT o.country_category,
                       o.store,
                       o.MSKU,
                       o.oos_start_date,
                       MIN(d.stat_date) AS first_restock_date
                FROM tmp_return_oos_rounds o
                JOIN tmp_return_perf_daily d
                  ON d.country_category = o.country_category
                 AND d.store = o.store
                 AND d.MSKU = o.MSKU
                 AND d.stat_date > o.oos_start_date
                 AND d.stat_date <= v_data_date
                 AND d.site_fba_available > 5
                GROUP BY o.country_category, o.store, o.MSKU, o.oos_start_date
                -- 先从完整历史计算真实首次恢复日，再按返场开始日判断是否属于最近180天。
                -- 断货日可以早于180天窗口；不可在MIN之前裁剪日期，否则会丢失长期断货后近期返场的事件。
                HAVING MIN(d.stat_date) BETWEEN v_180d AND v_data_date;
                ALTER TABLE tmp_return_completed_rounds
                    ADD INDEX idx_tmp_return_completed_rounds (country_category, store, MSKU, first_restock_date);

                -- 返场品不再要求最近180天出现销量>0；只按完整断货返场事件进入返场流程。

                -- 页面与标签只使用每个国家类别+店铺+MSKU最新一轮已完成的返场事件。
                SET v_stage = 'tmp_return_latest_round';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_latest_round;
                CREATE TEMPORARY TABLE tmp_return_latest_round AS
                SELECT country_category,
                       store,
                       MSKU,
                       oos_start_date,
                       first_restock_date
                FROM (
                    SELECT c.country_category,
                           c.store,
                           c.MSKU,
                           c.oos_start_date,
                           c.first_restock_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY c.country_category, c.store, c.MSKU
                               ORDER BY c.first_restock_date DESC, c.oos_start_date DESC
                           ) AS rn
                    FROM tmp_return_completed_rounds c
                ) latest_round
                WHERE rn = 1;
                ALTER TABLE tmp_return_latest_round
                    ADD INDEX idx_tmp_return_latest_round (country_category, store, MSKU, first_restock_date);

                -- 返场开始日记为D1；D1-D21使用相同天数的断货前后总销量计算恢复率。
                SET v_stage = 'tmp_return_event_base';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_event_base;
                CREATE TEMPORARY TABLE tmp_return_event_base AS
                SELECT r.country_category,
                       r.store,
                       r.MSKU,
                       r.oos_start_date,
                       r.oos_start_date AS last_oos_date,
                       r.first_restock_date,
                       r.first_restock_date AS first_resume_sale_date,
                       DATEDIFF(v_data_date, r.first_restock_date) + 1 AS return_days,
                       LEAST(DATEDIFF(v_data_date, r.first_restock_date) + 1, 21) AS comparison_days
                FROM tmp_return_latest_round r
                WHERE r.first_restock_date <= v_data_date;
                ALTER TABLE tmp_return_event_base
                    ADD INDEX idx_tmp_return_event_base (country_category, store, MSKU, first_restock_date);

                SET v_stage = 'tmp_return_sales_metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_sales_metrics;
                CREATE TEMPORARY TABLE tmp_return_sales_metrics AS
                SELECT e.country_category,
                       e.store,
                       e.MSKU,
                       e.oos_start_date,
                       e.last_oos_date,
                       e.first_restock_date,
                       e.first_resume_sale_date,
                       e.return_days,
                       e.comparison_days,
                       SUM(CASE
                               WHEN d.stat_date BETWEEN DATE_SUB(e.oos_start_date, INTERVAL (e.comparison_days) DAY)
                                                    AND DATE_SUB(e.oos_start_date, INTERVAL 1 DAY)
                               THEN COALESCE(d.site_sales_volume, 0)
                               ELSE 0
                           END) AS pre_comparison_sales,
                       SUM(CASE
                               WHEN d.stat_date BETWEEN e.first_restock_date
                                                    AND DATE_ADD(e.first_restock_date, INTERVAL (e.comparison_days - 1) DAY)
                               THEN COALESCE(d.site_sales_volume, 0)
                               ELSE 0
                           END) AS post_comparison_sales,
                       SUM(CASE
                               WHEN d.stat_date BETWEEN DATE_SUB(e.oos_start_date, INTERVAL 21 DAY)
                                                    AND DATE_SUB(e.oos_start_date, INTERVAL 1 DAY)
                               THEN COALESCE(d.site_sales_volume, 0)
                               ELSE 0
                           END) AS pre_21d_sales,
                       SUM(CASE
                               WHEN d.stat_date BETWEEN e.first_restock_date
                                                    AND DATE_ADD(e.first_restock_date, INTERVAL 20 DAY)
                               THEN COALESCE(d.site_sales_volume, 0)
                               ELSE 0
                           END) AS post_21d_sales,
                       SUM(CASE
                               WHEN d.stat_date BETWEEN e.first_restock_date AND v_data_date
                               THEN COALESCE(d.site_sales_volume, 0)
                               ELSE 0
                           END) AS post_cumulative_sales
                FROM tmp_return_event_base e
                LEFT JOIN tmp_return_perf_daily d
                  ON d.country_category = e.country_category
                 AND d.store = e.store
                 AND d.MSKU = e.MSKU
                GROUP BY e.country_category,
                         e.store,
                         e.MSKU,
                         e.oos_start_date,
                         e.last_oos_date,
                         e.first_restock_date,
                         e.first_resume_sale_date,
                         e.return_days,
                         e.comparison_days;
                ALTER TABLE tmp_return_sales_metrics
                    ADD INDEX idx_tmp_return_sales_metrics (country_category, store, MSKU, first_restock_date);

                SET v_stage = 'tmp_return_rate_metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_rate_metrics;
                CREATE TEMPORARY TABLE tmp_return_rate_metrics AS
                SELECT m.*,
                       m.post_comparison_sales / NULLIF(m.pre_comparison_sales, 0) AS comparison_recovery_rate,
                       m.post_21d_sales / NULLIF(m.pre_21d_sales, 0) AS d21_recovery_rate,
                       m.post_cumulative_sales * 21
                           / NULLIF(m.return_days * m.pre_21d_sales, 0) AS cumulative_average_recovery_rate
                FROM tmp_return_sales_metrics m;
                ALTER TABLE tmp_return_rate_metrics
                    ADD INDEX idx_tmp_return_rate_metrics (country_category, store, MSKU, first_restock_date);

                -- D22以后每天计算累计平均恢复率；缺失日期销量按0处理，首次达到70%的日期为后续达标退出日。
                SET v_stage = 'tmp_return_cumulative_daily';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_cumulative_daily;
                CREATE TEMPORARY TABLE tmp_return_cumulative_daily AS
                SELECT e.country_category,
                       e.store,
                       e.MSKU,
                       e.first_restock_date,
                       d.stat_date,
                       DATEDIFF(d.stat_date, e.first_restock_date) + 1 AS return_day,
                       SUM(COALESCE(d.site_sales_volume, 0)) OVER (
                           PARTITION BY e.country_category, e.store, e.MSKU, e.first_restock_date
                           ORDER BY d.stat_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS cumulative_sales,
                       SUM(COALESCE(d.site_sales_volume, 0)) OVER (
                           PARTITION BY e.country_category, e.store, e.MSKU, e.first_restock_date
                           ORDER BY d.stat_date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) * 21
                           / NULLIF((DATEDIFF(d.stat_date, e.first_restock_date) + 1) * e.pre_21d_sales, 0)
                           AS cumulative_average_recovery_rate
                FROM tmp_return_rate_metrics e
                JOIN tmp_return_perf_daily d
                  ON d.country_category = e.country_category
                 AND d.store = e.store
                 AND d.MSKU = e.MSKU
                 AND d.stat_date BETWEEN e.first_restock_date AND v_data_date;
                ALTER TABLE tmp_return_cumulative_daily
                    ADD INDEX idx_tmp_return_cumulative_daily (country_category, store, MSKU, first_restock_date, stat_date);

                SET v_stage = 'tmp_return_late_exit_date';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_late_exit_date;
                CREATE TEMPORARY TABLE tmp_return_late_exit_date AS
                SELECT country_category,
                       store,
                       MSKU,
                       first_restock_date,
                       MIN(stat_date) AS late_exit_date
                FROM tmp_return_cumulative_daily
                WHERE return_day >= 22
                  AND cumulative_average_recovery_rate >= 0.70
                GROUP BY country_category, store, MSKU, first_restock_date;
                ALTER TABLE tmp_return_late_exit_date
                    ADD INDEX idx_tmp_return_late_exit_date (country_category, store, MSKU, first_restock_date, late_exit_date);

                -- 取D22以后首次达标当天的累计销量和累计平均恢复率，达标后指标冻结在该日。
                SET v_stage = 'tmp_return_late_exit';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_late_exit;
                CREATE TEMPORARY TABLE tmp_return_late_exit AS
                SELECT x.country_category,
                       x.store,
                       x.MSKU,
                       x.first_restock_date,
                       x.late_exit_date,
                       d.cumulative_sales AS late_exit_cumulative_sales,
                       d.cumulative_average_recovery_rate AS late_exit_recovery_rate
                FROM tmp_return_late_exit_date x
                JOIN tmp_return_cumulative_daily d
                  ON d.country_category = x.country_category
                 AND d.store = x.store
                 AND d.MSKU = x.MSKU
                 AND d.first_restock_date = x.first_restock_date
                 AND d.stat_date = x.late_exit_date;
                ALTER TABLE tmp_return_late_exit
                    ADD INDEX idx_tmp_return_late_exit (country_category, store, MSKU, first_restock_date, late_exit_date);

                -- 先确定退出日期：D21达标的于D22退出；D21未达标或为空的，D22以后首次累计平均恢复率达到70%时退出。
                SET v_stage = 'tmp_return_exit_decision';
                DROP TEMPORARY TABLE IF EXISTS tmp_return_exit_decision;
                CREATE TEMPORARY TABLE tmp_return_exit_decision AS
                SELECT e.*,
                       x.late_exit_date,
                       x.late_exit_cumulative_sales,
                       x.late_exit_recovery_rate,
                       CASE
                           WHEN e.return_days >= 22 AND e.d21_recovery_rate >= 0.70
                               THEN DATE_ADD(e.first_restock_date, INTERVAL 21 DAY)
                           WHEN e.return_days >= 22
                                AND (e.d21_recovery_rate < 0.70 OR e.d21_recovery_rate IS NULL)
                               THEN x.late_exit_date
                       END AS exit_date
                FROM tmp_return_rate_metrics e
                LEFT JOIN tmp_return_late_exit x
                  ON x.country_category = e.country_category
                 AND x.store = e.store
                 AND x.MSKU = e.MSKU
                 AND x.first_restock_date = e.first_restock_date;
                ALTER TABLE tmp_return_exit_decision
                    ADD INDEX idx_tmp_return_exit_decision (country_category, store, MSKU, first_restock_date, exit_date);

                -- 退出后返场天数、累计销量和恢复率冻结在退出判定日；达标退出不再计入运营状态返厂品。
                SET v_stage = 'tmp_return';
                DROP TEMPORARY TABLE IF EXISTS tmp_return;
                CREATE TEMPORARY TABLE tmp_return AS
                SELECT e.country_category,
                       e.store,
                       e.MSKU,
                       e.oos_start_date,
                       e.last_oos_date,
                       e.first_restock_date,
                       e.first_resume_sale_date,
                       CASE
                           WHEN e.exit_date IS NOT NULL
                               THEN DATEDIFF(e.exit_date, e.first_restock_date) + 1
                           ELSE e.return_days
                       END AS return_days,
                       e.comparison_days,
                       e.pre_comparison_sales,
                       e.post_comparison_sales,
                       e.comparison_recovery_rate,
                       e.pre_21d_sales,
                       e.post_21d_sales,
                       e.d21_recovery_rate,
                       CASE
                           WHEN e.exit_date IS NOT NULL AND e.d21_recovery_rate >= 0.70
                               THEN e.post_21d_sales
                           WHEN e.exit_date IS NOT NULL
                               THEN e.late_exit_cumulative_sales
                           ELSE e.post_cumulative_sales
                       END AS post_cumulative_sales,
                       CASE
                           WHEN e.exit_date IS NOT NULL AND e.d21_recovery_rate >= 0.70
                               THEN e.d21_recovery_rate
                           WHEN e.exit_date IS NOT NULL
                               THEN e.late_exit_recovery_rate
                           ELSE e.cumulative_average_recovery_rate
                       END AS cumulative_average_recovery_rate,
                       e.exit_date,
                       CASE
                           WHEN e.return_days BETWEEN 1 AND 7 THEN '观察期'
                           WHEN e.return_days BETWEEN 8 AND 21 THEN '运营干预期'
                           WHEN e.return_days >= 22 AND e.exit_date IS NOT NULL THEN '达标退出'
                           WHEN e.return_days >= 22 THEN '持续干预期'
                       END AS return_stage
                FROM tmp_return_exit_decision e;

                -- 客户体验：复用产品表现标准化临时表；仍仅取德国站、最新业务日期的 avg_star。
                SET v_stage = 'tmp_de_rating';
                DROP TEMPORARY TABLE IF EXISTS tmp_de_rating;
                CREATE TEMPORARY TABLE tmp_de_rating AS
                SELECT '欧洲站' AS country_category,
                       CAST(perf_store AS CHAR(100)) AS rating_store,
                       CAST(perf_msku AS CHAR(255)) AS MSKU,
                       MAX(avg_star) AS avg_star
                FROM tmp_perf_scoped
                WHERE stat_date = v_data_date
                  AND (source_country IN ('德国', '德国站')
                       OR UPPER(source_country) IN ('DE', 'GERMANY', 'AMAZON.DE'))
                GROUP BY rating_store, MSKU;
                ALTER TABLE tmp_de_rating
                    ADD INDEX idx_tmp_de_rating (country_category, rating_store, MSKU);

                -- 德国站点 listing 维度：客户体验仅针对德国站点商品，无 product 数据时 avg_star 为 NULL。
                SET v_stage = 'tmp_de_listing_keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_de_listing_keys;
                CREATE TEMPORARY TABLE tmp_de_listing_keys AS
                SELECT DISTINCT
                       '欧洲站' AS country_category,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) > 0
                               THEN LEFT(SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1),
                                         LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1) END AS store,
                       CAST(li.`seller_sku` AS CHAR(255)) AS MSKU
                FROM tmp_listing_latest li
                WHERE CAST(li.`marketplace` AS CHAR) IN ('德国', '德国站')
                   OR UPPER(CAST(li.`marketplace` AS CHAR)) IN ('DE', 'GERMANY', 'AMAZON.DE');
                ALTER TABLE tmp_de_listing_keys
                    ADD INDEX idx_tmp_de_listing_keys (country_category, store, MSKU);

                SET v_stage = 'tmp_customer_experience';
                DROP TEMPORARY TABLE IF EXISTS tmp_customer_experience;
                CREATE TEMPORARY TABLE tmp_customer_experience AS
                SELECT k.country_category,
                       '德国' AS country,
                       k.store,
                       k.MSKU,
                       r.avg_star
                FROM tmp_de_listing_keys k
                         LEFT JOIN tmp_de_rating r
                              ON k.country_category = r.country_category
                             AND k.store = r.rating_store
                             AND k.MSKU = r.MSKU;
                -- 退货情况：先将订单明细裁剪到当前标签维度，先按 amazon_order_id + order_item_id 去重订单行，再按 amazon_order_id 确定最近100个订单。
                -- 退货订单行以 is_return 非空且非“未退款”为准；退货率按最近100单内实际退货订单行下单量/全部订单行下单量计算。
                SET v_stage = 'tmp_order_raw';
                DROP TEMPORARY TABLE IF EXISTS tmp_order_raw;
                CREATE TEMPORARY TABLE tmp_order_raw AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       CAST(o.`amazon_order_id` AS CHAR) AS amazon_order_id,
                       COALESCE(NULLIF(CAST(o.`order_item_id` AS CHAR), ''),
                                CONCAT('__NO_ORDER_ITEM__:', CAST(o.`amazon_order_id` AS CHAR))) AS order_item_id,
                       COALESCE(
                           STR_TO_DATE(LEFT(CAST(o.`purchase_date_local_utc` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                           STR_TO_DATE(LEFT(CAST(o.`purchase_date_local` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                            o.`create_time`
                        ) AS order_time,
                        COALESCE(o.`quantity_ordered`, 0) AS sales_volume,
                        CASE
                           WHEN o.`is_return` IS NOT NULL
                                AND TRIM(CAST(o.`is_return` AS CHAR)) <> ''
                                AND TRIM(CAST(o.`is_return` AS CHAR)) NOT IN ('未退款', '否', '0', 'false', 'FALSE')
                               THEN 1
                           ELSE 0 END AS is_returned
                FROM tmp_listing_keys k
                         JOIN `dwd_datasync`.`lx_sales_mws_orders_detail` o
                              ON k.country_category = CASE
                                                          WHEN CAST(o.`country` AS CHAR) = '英国' THEN '英国站'
                                                          WHEN CAST(o.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥')
                                                              THEN '北美站'
                                                          ELSE '欧洲站' END
                             AND k.store = CASE
                                               WHEN LOCATE('-', SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                                       SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1),
                                                       LOCATE('-', SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1)) - 1)
                                               ELSE SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1) END
                             AND k.MSKU = CAST(o.`seller_sku` AS CHAR)
                WHERE o.`amazon_order_id` IS NOT NULL
                  AND CAST(o.`amazon_order_id` AS CHAR) <> '';
                ALTER TABLE tmp_order_raw
                    ADD INDEX idx_tmp_order_raw (country_category, store, MSKU, amazon_order_id);

                -- 先以 amazon_order_id + order_item_id 对订单行去重：同一订单下不同 order_item_id 为不同订单行，保留各行下单量；原始表索引仅保留四列，避免长文本联合索引超过 MySQL 键长上限。
                SET v_stage = 'tmp_order_line_dedup';
                DROP TEMPORARY TABLE IF EXISTS tmp_order_line_dedup;
                CREATE TEMPORARY TABLE tmp_order_line_dedup AS
                SELECT country_category,
                       store,
                       MSKU,
                       amazon_order_id,
                       order_item_id,
                       MAX(order_time) AS order_time,
                       MAX(sales_volume) AS sales_volume,
                       MAX(is_returned) AS is_returned
                FROM tmp_order_raw
                GROUP BY country_category, store, MSKU, amazon_order_id, order_item_id;
                ALTER TABLE tmp_order_line_dedup
                    ADD INDEX idx_tmp_order_line_dedup (country_category, store, MSKU, amazon_order_id);

                -- 再按 amazon_order_id 汇总订单总下单量；最近100单仍按去重订单数计算。
                SET v_stage = 'tmp_order_dedup';
                DROP TEMPORARY TABLE IF EXISTS tmp_order_dedup;
                CREATE TEMPORARY TABLE tmp_order_dedup AS
                SELECT country_category,
                       store,
                       MSKU,
                       amazon_order_id,
                       MAX(order_time) AS order_time,
                       SUM(sales_volume) AS sales_volume
                FROM tmp_order_line_dedup
                GROUP BY country_category, store, MSKU, amazon_order_id;
                ALTER TABLE tmp_order_dedup
                    ADD INDEX idx_tmp_order_dedup (country_category, store, MSKU, order_time);

                SET v_stage = 'tmp_return_last_100';

                DROP TEMPORARY TABLE IF EXISTS tmp_return_last_100;
                CREATE TEMPORARY TABLE tmp_return_last_100 AS
                SELECT l.country_category,
                       l.store,
                       l.MSKU,
                       l.amazon_order_id,
                       SUM(l.sales_volume) AS sales_volume,
                       SUM(CASE WHEN l.is_returned = 1 THEN l.sales_volume ELSE 0 END) AS return_sales_volume
                FROM (
                         SELECT d.country_category,
                                d.store,
                                d.MSKU,
                                d.amazon_order_id,
                                ROW_NUMBER() OVER (
                                    PARTITION BY d.country_category, d.store, d.MSKU
                                    ORDER BY d.order_time DESC, d.amazon_order_id DESC
                                    ) AS rn
                         FROM tmp_order_dedup d
                     ) ranked
                         JOIN tmp_order_line_dedup l
                              ON ranked.country_category = l.country_category
                             AND ranked.store = l.store
                             AND ranked.MSKU = l.MSKU
                             AND ranked.amazon_order_id = l.amazon_order_id
                WHERE ranked.rn <= 100
                GROUP BY l.country_category, l.store, l.MSKU, l.amazon_order_id;

                SET v_stage = 'tmp_return_rate';

                DROP TEMPORARY TABLE IF EXISTS tmp_return_rate;
                CREATE TEMPORARY TABLE tmp_return_rate AS
                SELECT country_category,
                       store,
                       MSKU,
                       COUNT(*) AS order_count,
                       SUM(CASE WHEN return_sales_volume > 0 THEN 1 ELSE 0 END) AS return_order_count,
                       SUM(sales_volume) AS sales_volume,
                       SUM(return_sales_volume) AS return_sales_volume,
                       SUM(return_sales_volume) / NULLIF(SUM(sales_volume), 0) AS return_rate
                FROM tmp_return_last_100
                GROUP BY country_category, store, MSKU;

                SET v_stage = 'tmp_hits';

                DROP TEMPORARY TABLE IF EXISTS tmp_hits;
                CREATE TEMPORARY TABLE tmp_hits
                (
                    `国家类别`       varchar(20),
                    `国家`           varchar(100),
                    `店铺`           varchar(100),
                    `MSKU`           varchar(500),
                    label_name       varchar(100),
                    child_label_name varchar(100),
                    label_period     varchar(20)
                ) ENGINE = InnoDB
                  DEFAULT CHARSET = utf8mb4
                  COLLATE = utf8mb4_0900_ai_ci;

                -- 销售角色：按 国家类别+店铺+MSKU。先生成7/14/30/90天销售角色，供生命周期“成熟期”判断复用。
                SET v_stage = 'tmp_sales_role';
                DROP TEMPORARY TABLE IF EXISTS tmp_sales_role;
                CREATE TEMPORARY TABLE tmp_sales_role AS
                SELECT country_category,
                       NULL AS                                                                      country,
                       store,
                       MSKU,
                       CASE
                           WHEN (vol_7d > 5 AND margin_7d > 15) OR (vol_7d BETWEEN 1 AND 5 AND margin_7d > 25) THEN '明星产品'
                           WHEN (vol_7d > 5 AND margin_7d BETWEEN 5 AND 15) OR
                                (vol_7d BETWEEN 1 AND 5 AND margin_7d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_7d BETWEEN 1 AND 5 AND margin_7d >= 5 AND margin_7d < 10) OR (vol_7d < 1 AND margin_7d > 5)
                               THEN '瘦狗产品'
                           WHEN vol_7d = 0 OR (vol_7d > 0 AND margin_7d < 5) THEN '问题产品' END    role_7d,
                       CASE
                           WHEN (vol_14d > 5 AND margin_14d > 15) OR (vol_14d BETWEEN 1 AND 5 AND margin_14d > 25) THEN '明星产品'
                           WHEN (vol_14d > 5 AND margin_14d BETWEEN 5 AND 15) OR
                                (vol_14d BETWEEN 1 AND 5 AND margin_14d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_14d BETWEEN 1 AND 5 AND margin_14d >= 5 AND margin_14d < 10) OR
                                (vol_14d < 1 AND margin_14d > 5) THEN '瘦狗产品'
                           WHEN vol_14d = 0 OR (vol_14d > 0 AND margin_14d < 5) THEN '问题产品' END role_14d,
                       CASE
                           WHEN (vol_30d > 5 AND margin_30d > 15) OR (vol_30d BETWEEN 1 AND 5 AND margin_30d > 25) THEN '明星产品'
                           WHEN (vol_30d > 5 AND margin_30d BETWEEN 5 AND 15) OR
                                (vol_30d BETWEEN 1 AND 5 AND margin_30d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_30d BETWEEN 1 AND 5 AND margin_30d >= 5 AND margin_30d < 10) OR
                                (vol_30d < 1 AND margin_30d > 5) THEN '瘦狗产品'
                           WHEN vol_30d = 0 OR (vol_30d > 0 AND margin_30d < 5) THEN '问题产品' END role_30d,
                       CASE
                           WHEN (vol_90d > 5 AND margin_90d > 15) OR (vol_90d BETWEEN 1 AND 5 AND margin_90d > 25) THEN '明星产品'
                           WHEN (vol_90d > 5 AND margin_90d BETWEEN 5 AND 15) OR
                                (vol_90d BETWEEN 1 AND 5 AND margin_90d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_90d BETWEEN 1 AND 5 AND margin_90d >= 5 AND margin_90d < 10) OR
                                (vol_90d < 1 AND margin_90d > 5) THEN '瘦狗产品'
                           WHEN vol_90d = 0 OR (vol_90d > 0 AND margin_90d < 5) THEN '问题产品' END role_90d
                FROM tmp_perf;

                -- MySQL 临时表不能在同一条 UNION SQL 中被重复打开；这里拆成4条 INSERT，避免 Can't reopen table: tmp_sales_role。
                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '销售角色', role_7d, '7d'
                FROM tmp_sales_role
                WHERE role_7d IS NOT NULL;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '销售角色', role_14d, '14d'
                FROM tmp_sales_role
                WHERE role_14d IS NOT NULL;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '销售角色', role_30d, '30d'
                FROM tmp_sales_role
                WHERE role_30d IS NOT NULL;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '销售角色', role_90d, '90d'
                FROM tmp_sales_role
                WHERE role_90d IS NOT NULL;

                -- 生命周期：按国家类别+店铺+MSKU，依据 lx_fba_shipment.receiving_time 的首次到货日判断。
                -- 成熟期不自动回退：读取当前业务日期之前最近一个业务日期的成熟期标签。
                -- 若前序已是成熟期，则当天继续成熟期；否则仅在当天四周期销售角色均健康时首次进入成熟期。
                SET v_stage = 'tmp_previous_lifecycle_mature';
                DROP TEMPORARY TABLE IF EXISTS tmp_previous_lifecycle_mature;
                CREATE TEMPORARY TABLE tmp_previous_lifecycle_mature AS
                SELECT t.`country_category`,
                       t.`store`,
                       t.`msku` AS MSKU,
                       t.`data_date` AS previous_mature_data_date,
                       COALESCE(
                           STR_TO_DATE(JSON_UNQUOTE(JSON_EXTRACT(t.`evidence_json`, '$.metrics.first_mature_data_date')), '%Y-%m-%d'),
                           t.`data_date`
                       ) AS first_mature_data_date
                FROM `dws_datasync`.`dws_标签表` t
                JOIN `dws_datasync`.`dws_标签详情表` d
                  ON d.`sub_label_id` = t.`label_id`
                WHERE d.`label_name` = '生命周期'
                  AND d.`sub_label_name` = '成熟期'
                  AND t.`data_date` = (
                      SELECT MAX(prev_t.`data_date`)
                      FROM `dws_datasync`.`dws_标签表` prev_t
                      WHERE prev_t.`data_date` < v_data_date
                  );
                ALTER TABLE tmp_previous_lifecycle_mature
                    ADD INDEX idx_tmp_previous_lifecycle_mature (country_category, store, MSKU);

                INSERT INTO tmp_hits
                SELECT p.country_category,
                       NULL,
                       p.store,
                       p.MSKU,
                       '生命周期',
                       CASE
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30 THEN '测款期'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 31 AND 120 THEN '新品期'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 121 AND 300 THEN '成长期'
                           WHEN pm.first_mature_data_date IS NOT NULL THEN '成熟期'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300
                                AND COALESCE(sr.role_7d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_14d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_30d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_90d, '') NOT IN ('瘦狗产品', '问题产品') THEN '成熟期'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300 THEN '成长期'
                       END AS child_label_name,
                       CASE
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30 THEN '30d'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 31 AND 120 THEN '90d'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 121 AND 300 THEN '6m'
                           WHEN pm.first_mature_data_date IS NOT NULL THEN 'long_term'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300
                                AND COALESCE(sr.role_7d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_14d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_30d, '') NOT IN ('瘦狗产品', '问题产品')
                                AND COALESCE(sr.role_90d, '') NOT IN ('瘦狗产品', '问题产品') THEN 'long_term'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300 THEN '6m'
                       END AS label_period
                FROM tmp_perf p
                JOIN tmp_first_receiving fr
                  ON p.country_category = fr.country_category AND p.store = fr.store AND p.MSKU = fr.MSKU
                LEFT JOIN tmp_sales_role sr
                  ON p.country_category = sr.country_category AND p.store = sr.store AND p.MSKU = sr.MSKU
                LEFT JOIN tmp_previous_lifecycle_mature pm
                  ON p.country_category = pm.country_category AND p.store = pm.store AND p.MSKU = pm.MSKU
                HAVING child_label_name IS NOT NULL;
                -- 定价：非库存类，国家+店铺+MSKU。
                INSERT INTO tmp_hits
                SELECT country_category, country, store, MSKU, '定价', price_label, 'current'
                FROM tmp_price
                WHERE price_label IS NOT NULL;


                -- 站点状态：基于 Listing 历史覆盖站点判断；五国覆盖判断规则不变。
                SET v_stage = 'tmp_site_status_base';
                DROP TEMPORARY TABLE IF EXISTS tmp_site_status_base;
                CREATE TEMPORARY TABLE tmp_site_status_base AS
                SELECT CAST(li.`marketplace` AS CHAR)                                                    AS site_country,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                   SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1),
                                   LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1) END AS site_store,
                       CAST(li.`seller_sku` AS CHAR)                                        AS site_msku,
                       CASE
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('德国', '德国站') OR
                                UPPER(CAST(li.`marketplace` AS CHAR)) IN ('DE', 'GERMANY', 'AMAZON.DE') THEN '德国'
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('意大利', '意大利站') OR
                                UPPER(CAST(li.`marketplace` AS CHAR)) IN ('IT', 'ITALY', 'AMAZON.IT') THEN '意大利'
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('法国', '法国站') OR
                                UPPER(CAST(li.`marketplace` AS CHAR)) IN ('FR', 'FRANCE', 'AMAZON.FR') THEN '法国'
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('西班牙', '西班牙站') OR
                                UPPER(CAST(li.`marketplace` AS CHAR)) IN ('ES', 'SPAIN', 'AMAZON.ES') THEN '西班牙'
                           WHEN CAST(li.`marketplace` AS CHAR) IN ('荷兰', '荷兰站') OR
                                UPPER(CAST(li.`marketplace` AS CHAR)) IN ('NL', 'NETHERLANDS', 'AMAZON.NL') THEN '荷兰'
                           END                                                             AS site_code
                FROM tmp_listing_latest li
                GROUP BY site_country, site_store, site_msku, site_code;

                SET v_stage = 'tmp_site_status_msku';
                DROP TEMPORARY TABLE IF EXISTS tmp_site_status_msku;
                CREATE TEMPORARY TABLE tmp_site_status_msku AS
                SELECT site_msku AS MSKU,
                       COUNT(DISTINCT site_code) AS covered_site_count,
                       CASE WHEN COUNT(DISTINCT site_code) = 5 THEN '五国全覆盖' ELSE '部分覆盖' END AS site_status_label
                FROM tmp_site_status_base
                WHERE site_code IS NOT NULL
                GROUP BY site_msku;

                SET v_stage = 'tmp_site_status';
                DROP TEMPORARY TABLE IF EXISTS tmp_site_status;
                CREATE TEMPORARY TABLE tmp_site_status AS
                SELECT '欧洲站' AS country_category,
                       b.site_country AS country,
                       b.site_store AS store,
                       b.site_msku AS MSKU,
                       s.covered_site_count,
                       s.site_status_label
                FROM tmp_site_status_base b
                         JOIN tmp_site_status_msku s ON b.site_msku = s.MSKU
                WHERE b.site_code IS NOT NULL
                  AND s.site_status_label IS NOT NULL;

                INSERT INTO tmp_hits
                SELECT country_category, country, store, MSKU, '站点状态', site_status_label, 'current'
                FROM tmp_site_status
                WHERE site_status_label IS NOT NULL;
                -- 库存水平：按 dws_datasync.dws_库存宽表 的库存支撑天数判断；按 国家类别(站点)+店铺+MSKU，country字段置NULL。
                -- 如实际库存表字段名与这里不同，请将 `数据日期`、`站点`、`店铺名`、`MSKU`、`库存支撑天数` 替换为实际字段名。
                SET v_stage = 'tmp_inventory_level';
                DROP TEMPORARY TABLE IF EXISTS tmp_inventory_level;
                SET v_stage = 'tmp_inventory_date';
                DROP TEMPORARY TABLE IF EXISTS tmp_inventory_date;
                CREATE TEMPORARY TABLE tmp_inventory_date AS
                SELECT MAX(k2.`数据日期`) AS inventory_date
                FROM `dws_datasync`.`dws_库存宽表` k2
                WHERE k2.`数据日期` <= v_data_date;

                CREATE TEMPORARY TABLE tmp_inventory_level AS
                SELECT CAST(k.`站点` AS CHAR)                                         AS country_category,
                       NULL                                                           AS country,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(k.`店铺名` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                   SUBSTRING_INDEX(CAST(k.`店铺名` AS CHAR), ' ', 1),
                                   LOCATE('-', SUBSTRING_INDEX(CAST(k.`店铺名` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(k.`店铺名` AS CHAR), ' ', 1) END AS store,
                       CAST(k.`MSKU` AS CHAR)                                         AS MSKU,
                       MAX(k.`库存支撑天数`)                                             AS inventory_support_days,
                       CASE
                           WHEN MAX(k.`库存支撑天数`) < 35 THEN '低库存'
                           WHEN MAX(k.`库存支撑天数`) >= 35 AND MAX(k.`库存支撑天数`) < 90 THEN '中库存'
                           WHEN MAX(k.`库存支撑天数`) >= 90 THEN '高库存'
                           END                                                        AS inventory_level_label
                FROM `dws_datasync`.`dws_库存宽表` k FORCE INDEX (`idx_date_store_site_wh_msku`)
                         JOIN tmp_inventory_date d
                              ON k.`数据日期` = d.inventory_date
                WHERE d.inventory_date IS NOT NULL
                  AND LOWER(TRIM(CAST(k.`MSKU` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND UPPER(TRIM(CAST(k.`MSKU` AS CHAR))) NOT LIKE 'AMAZON%'
                  AND CAST(k.`MSKU` AS CHAR) <> ''
                  AND k.`库存支撑天数` IS NOT NULL
                GROUP BY country_category, store, MSKU
                HAVING inventory_level_label IS NOT NULL;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '库存水平', inventory_level_label, 'current'
                FROM tmp_inventory_level
                WHERE inventory_level_label IS NOT NULL;

                -- 流量结构：基于 Listing 维度，关联产品表现近30天数据；无 product 数据时不打标签。
                SET v_stage = 'tmp_traffic_structure';
                DROP TEMPORARY TABLE IF EXISTS tmp_traffic_structure;
                CREATE TEMPORARY TABLE tmp_traffic_structure AS
                SELECT country_category,
                       NULL AS country,
                       traffic_store AS store,
                       traffic_msku AS MSKU,
                       sales_amount_30d,
                       ad_spend_30d,
                       CASE
                           WHEN sales_amount_30d <= 0 AND ad_spend_30d > 0 THEN '高度依赖广告'
                           WHEN sales_amount_30d <= 0 AND ad_spend_30d = 0 THEN '自然流量'
                           WHEN ad_spend_30d / sales_amount_30d >= 0.70 THEN '高度依赖广告'
                           WHEN ad_spend_30d / sales_amount_30d >= 0.40 AND ad_spend_30d / sales_amount_30d < 0.70 THEN '中度依赖广告'
                           WHEN ad_spend_30d / sales_amount_30d >= 0.10 AND ad_spend_30d / sales_amount_30d < 0.40 THEN '健康状态'
                           WHEN ad_spend_30d / sales_amount_30d < 0.10 THEN '自然流量'
                           END AS traffic_structure_label
                FROM (
                    SELECT country_category,
                           perf_store AS traffic_store,
                           perf_msku AS traffic_msku,
                           SUM(ABS(COALESCE(spend, 0))) AS ad_spend_30d,
                           SUM(COALESCE(amount, 0)) AS sales_amount_30d,
                           COUNT(stat_date) AS product_record_count_30d
                    FROM tmp_perf_scoped
                    WHERE stat_date BETWEEN v_30d AND v_data_date
                    GROUP BY country_category, perf_store, perf_msku
                ) a
                WHERE product_record_count_30d > 0;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '流量结构', traffic_structure_label, '30d'
                FROM tmp_traffic_structure
                WHERE traffic_structure_label IS NOT NULL;

                -- 所有依赖产品表现标准化表的标签已计算完成，提前释放临时空间。
                SET v_stage = 'tmp_perf_scoped_cleanup';
                DROP TEMPORARY TABLE IF EXISTS tmp_perf_scoped;
                -- 客户体验：严格按 dws_标签详情表的已启用规则分段；按德国+店铺+MSKU输出，国家类别为欧洲站。
                INSERT INTO tmp_hits
                SELECT country_category,
                       country,
                       store,
                       MSKU,
                       '客户体验',
                       CASE
                           WHEN avg_star IS NULL OR avg_star = 0 THEN '无评价'
                           WHEN avg_star >= 4.00 AND avg_star <= 4.50 THEN '口碑优秀'
                           WHEN avg_star >= 3.50 AND avg_star < 4.00 THEN '口碑正常'
                           WHEN avg_star < 3.50 THEN '口碑风险'
                           END AS child_label_name,
                       'current'
                FROM tmp_customer_experience
                WHERE avg_star IS NULL
                   OR avg_star = 0
                   OR (avg_star >= 4.00 AND avg_star <= 4.50)
                   OR (avg_star >= 3.50 AND avg_star < 4.00)
                   OR avg_star < 3.50;

                -- 退货情况：按国家类别+店铺+MSKU 的最近100个去重 amazon_order_id，以实际退货订单行下单量/全部订单行下单量计算退货率。
                INSERT INTO tmp_hits
                SELECT country_category,
                       NULL,
                       store,
                       MSKU,
                       '退货情况',
                       CASE
                           WHEN return_rate < 0.02 THEN '低退货率'
                           WHEN return_rate >= 0.02 AND return_rate < 0.05 THEN '正常退货率'
                           WHEN return_rate >= 0.05 AND return_rate <= 0.20 THEN '高退货率'
                           WHEN return_rate > 0.20 THEN '严重退货'
                           END AS child_label_name,
                       'current'
                FROM tmp_return_rate
                WHERE return_rate IS NOT NULL;

                -- 运营状态（互斥）：返厂品 > 断货中 > 停售 > 测款扶持 > 正常在售。
                -- 已进入观察期、运营干预期或持续干预期的MSKU，即使当前FBA可售再次为0，
                -- 仍保持返厂品状态，用于兼容亚马逊入库时效造成的短期库存回落。
                -- 断货中：FBA 可售库存=0，且 FBA 在途或本地仓数量>0。
                -- 停售：FBA 可售库存=0，且 FBA 在途、本地仓数量均=0。
                -- 不再以 Listing 状态、产品表现表是否有数据作为断货/停售判断条件。
                -- 测款扶持：首次货件到货日起0~30天，且当前 FBA 可售库存>0。
                SET v_stage = 'tmp_op';
                DROP TEMPORARY TABLE IF EXISTS tmp_op;
                CREATE TEMPORARY TABLE tmp_op AS
                SELECT k.country_category,
                       NULL AS country,
                       k.store,
                       k.MSKU,
                       COALESCE(f.fba_available, 0) AS fba_available,
                       COALESCE(f.fba_in_transit, 0) AS fba_in_transit,
                       COALESCE(l.local_quantity, 0) AS local_quantity,
                       CASE
                           WHEN fr.first_receiving_date IS NOT NULL
                                AND DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30
                                AND COALESCE(f.fba_available, 0) > 0 THEN 1
                           ELSE 0 END AS is_test_support,
                       CASE
                           WHEN COALESCE(f.fba_available, 0) = 0
                                AND (COALESCE(f.fba_in_transit, 0) > 0 OR COALESCE(l.local_quantity, 0) > 0) THEN 1
                           ELSE 0 END AS is_out_of_stock,
                       CASE
                           WHEN COALESCE(f.fba_available, 0) = 0
                                AND COALESCE(f.fba_in_transit, 0) = 0
                                AND COALESCE(l.local_quantity, 0) = 0 THEN 1
                           ELSE 0 END AS is_stopped,
                       CASE
                           WHEN r.return_stage IN ('观察期', '运营干预期', '持续干预期') THEN 1
                           ELSE 0 END AS is_return_event
                FROM tmp_listing_keys k
                         LEFT JOIN tmp_op_fba f
                                     ON k.country_category = f.country_category AND k.store = f.store AND k.MSKU = f.MSKU
                         LEFT JOIN tmp_op_local l
                                     ON k.country_category = l.country_category AND k.store = l.store AND k.MSKU = l.MSKU
                         LEFT JOIN tmp_first_receiving fr
                                     ON k.country_category = fr.country_category AND k.store = fr.store AND k.MSKU = fr.MSKU
                         LEFT JOIN tmp_return r
                                     ON k.country_category = r.country_category AND k.store = r.store AND k.MSKU = r.MSKU;

                -- 运营状态必须互斥：每个国家类别+店铺+MSKU仅保留一个状态。
                -- 优先级：返厂品 > 断货中 > 停售 > 测款扶持 > 正常在售。
                INSERT INTO tmp_hits
                SELECT country_category,
                       NULL AS country,
                       store,
                       MSKU,
                       '运营状态' AS label_name,
                       CASE
                           WHEN is_return_event = 1 THEN '返厂品'
                           WHEN is_out_of_stock = 1 THEN '断货中'
                           WHEN is_stopped = 1 THEN '停售'
                           WHEN is_test_support = 1 THEN '测款扶持'
                           WHEN fba_available > 0 THEN '正常在售'
                       END AS child_label_name,
                       CASE
                           WHEN is_return_event = 1 THEN 'current'
                           WHEN is_out_of_stock = 1 THEN 'current'
                           WHEN is_stopped = 1 THEN 'current'
                           WHEN is_test_support = 1 THEN '30d'
                           WHEN fba_available > 0 THEN 'current'
                       END AS label_period
                FROM tmp_op
                WHERE is_out_of_stock = 1
                   OR is_stopped = 1
                   OR is_return_event = 1
                   OR is_test_support = 1
                   OR fba_available > 0;

                -- 返厂品阶段下钻：D1-D7观察期，D8-D21运营干预期；D22以后未达标持续干预，达到70%后达标退出。
                INSERT INTO tmp_hits
                SELECT r.country_category,
                       NULL,
                       r.store,
                       r.MSKU,
                       '返厂品阶段下钻',
                       r.return_stage,
                       'current' AS label_period
                FROM tmp_return r
                WHERE r.return_stage IS NOT NULL;
                -- 断货在途流程标签：
                -- 1) 先以运营状态判定“断货中”；2) 仅查询这些维度的货件；
                -- 3) 按货件状态最近更新时间取每个 MSKU 的最新状态记录；4) 直接使用该记录的 shipment_status。
                SET v_stage = 'tmp_oos_category';
                DROP TEMPORARY TABLE IF EXISTS tmp_oos_category;
                CREATE TEMPORARY TABLE tmp_oos_category AS
                SELECT CAST(country_category AS CHAR(20)) AS country_category,
                       CAST(store AS CHAR(100)) AS store,
                       CAST(MSKU AS CHAR(255)) AS MSKU
                FROM tmp_op
                WHERE is_out_of_stock = 1
                GROUP BY country_category, store, MSKU;
                ALTER TABLE tmp_oos_category
                    ADD INDEX idx_tmp_oos_category (country_category, store, MSKU);

                SET v_stage = 'tmp_ship';

                DROP TEMPORARY TABLE IF EXISTS tmp_ship;
                CREATE TEMPORARY TABLE tmp_ship AS
                SELECT country_category,
                       store,
                       MSKU,
                       shipment_status,
                       status_effective_time,
                       status_time_source
                FROM (
                         SELECT o.country_category,
                                o.store,
                                o.MSKU,
                                CAST(s.`shipment_status` AS CHAR) AS shipment_status,
                                COALESCE(
                                    STR_TO_DATE(LEFT(CAST(s.`gmt_modified` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                                    CASE WHEN UPPER(CAST(s.`shipment_status` AS CHAR)) = 'WORKING'
                                         THEN STR_TO_DATE(LEFT(CAST(s.`working_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') END,
                                    STR_TO_DATE(LEFT(CAST(s.`gmt_create` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                                    STR_TO_DATE(LEFT(CAST(s.`create_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s')
                                ) AS status_effective_time,
                                CASE
                                    WHEN STR_TO_DATE(LEFT(CAST(s.`gmt_modified` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL THEN 'gmt_modified'
                                    WHEN UPPER(CAST(s.`shipment_status` AS CHAR)) = 'WORKING'
                                     AND STR_TO_DATE(LEFT(CAST(s.`working_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL THEN 'working_time'
                                    WHEN STR_TO_DATE(LEFT(CAST(s.`gmt_create` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL THEN 'gmt_create'
                                    WHEN STR_TO_DATE(LEFT(CAST(s.`create_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL THEN 'create_time'
                                END AS status_time_source,
                                ROW_NUMBER() OVER (
                                    PARTITION BY o.country_category, o.store, o.MSKU
                                    -- 货件状态按最近更新时间取值：优先 gmt_modified；仅 WORKING 状态可回退 working_time，其余再回退 gmt_create、create_time。
                                    ORDER BY COALESCE(
                                                 STR_TO_DATE(LEFT(CAST(s.`gmt_modified` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                                                 CASE
                                                     -- working_time 仅表示进入 WORKING 状态的时间，不能作为其他状态的通用更新时间。
                                                     WHEN UPPER(CAST(s.`shipment_status` AS CHAR)) = 'WORKING'
                                                         THEN STR_TO_DATE(LEFT(CAST(s.`working_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s')
                                                 END,
                                                 STR_TO_DATE(LEFT(CAST(s.`gmt_create` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                                                 STR_TO_DATE(LEFT(CAST(s.`create_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s')
                                             ) DESC,
                                             s.`id` DESC
                                    ) AS rn
                         FROM tmp_oos_category o
                                  JOIN `dwd_datasync`.`lx_fba_shipment` s
                                       ON o.country_category = CASE
                                                                   WHEN CAST(s.`country` AS CHAR) = '英国' THEN '英国站'
                                                                   WHEN CAST(s.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥')
                                                                       THEN '北美站'
                                                                   ELSE '欧洲站' END
                                      AND o.store = CASE
                                                        WHEN LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                                                SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1),
                                                                LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) - 1)
                                                        ELSE SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1) END
                                      AND o.MSKU = CAST(s.`msku` AS CHAR)
                         WHERE s.`shipment_status` IS NOT NULL
                           AND CAST(s.`shipment_status` AS CHAR) <> ''
                     ) latest_shipment
                WHERE latest_shipment.rn = 1;

                INSERT INTO tmp_hits
                SELECT country_category, NULL, store, MSKU, '断货在途流程标签', shipment_status, 'current'
                FROM tmp_ship
                WHERE shipment_status IS NOT NULL;

                SET v_stage = '最终标签写入';
                -- 证据在最终写入时生成：tmp_hits 保持原有窄表结构，避免每次临时写入/去重均搬运大 JSON。
                -- 为最终关联的临时来源建立键索引，减少 JSON 取数引入的关联成本。
                -- 索引 DDL 必须在目标表删除事务开始前执行，避免 DDL 的隐式提交影响 dws_标签表 的原子写入。
                ALTER TABLE tmp_sales_role ADD INDEX idx_evidence_sales_role (country_category, store, MSKU);
                ALTER TABLE tmp_price ADD INDEX idx_evidence_price (country_category, country, store, MSKU);
                ALTER TABLE tmp_site_status ADD INDEX idx_evidence_site_status (country_category, country, store, MSKU);
                ALTER TABLE tmp_inventory_level ADD INDEX idx_evidence_inventory (country_category, store, MSKU);
                ALTER TABLE tmp_traffic_structure ADD INDEX idx_evidence_traffic (country_category, store, MSKU);
                ALTER TABLE tmp_customer_experience ADD INDEX idx_evidence_customer (country_category, country, store, MSKU);
                ALTER TABLE tmp_return_rate ADD INDEX idx_evidence_return_rate (country_category, store, MSKU);
                ALTER TABLE tmp_op ADD INDEX idx_evidence_op (country_category, store, MSKU);
                ALTER TABLE tmp_return ADD INDEX idx_evidence_return (country_category, store, MSKU);
                ALTER TABLE tmp_ship ADD INDEX idx_evidence_ship (country_category, store, MSKU);

                START TRANSACTION;
                -- Keep only v_data_date and v_data_date - 1. Delete current date first so reruns cannot duplicate rows.
                DELETE FROM `dws_datasync`.`dws_标签表`
                WHERE `data_date` = v_data_date;

                DELETE FROM `dws_datasync`.`dws_标签表`
                WHERE `data_date` < DATE_SUB(v_data_date, INTERVAL 1 DAY);

                INSERT INTO `dws_datasync`.`dws_标签表` (`data_date`, `country_category`, `country`, `store`, `msku`,
                                                         `label_id`, `label_period`, `created_time`, `evidence_json`)
                -- 先对标签业务键去重，避免 JSON 表达式参与 DISTINCT，降低兼容性与临时排序风险。
                SELECT v_data_date,
                                h.`国家类别`, h.`国家`, h.`店铺`, h.`MSKU`, h.sub_label_id, h.label_period, NOW(),
                                CASE h.label_name
                                    WHEN '销售角色' THEN JSON_OBJECT(
                                        'schema_version','1.1','rule_version','v45','type','sales_role',
                                        'window',JSON_OBJECT(
                                            'start',DATE_FORMAT(CASE h.label_period WHEN '7d' THEN v_7d WHEN '14d' THEN v_14d WHEN '30d' THEN v_30d ELSE v_90d END,'%Y-%m-%d'),
                                            'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period',h.label_period,
                                            'days',CASE h.label_period WHEN '7d' THEN 7 WHEN '14d' THEN 14 WHEN '30d' THEN 30 ELSE 90 END
                                        ),
                                        'metrics',JSON_OBJECT(
                                            'period_sales_qty',ROUND(CASE h.label_period WHEN '7d' THEN p.vol_7d*7 WHEN '14d' THEN p.vol_14d*14 WHEN '30d' THEN p.vol_30d*30 ELSE p.vol_90d*90 END,4),
                                            'daily_sales',ROUND(CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END,4),
                                            'sales_amount',ROUND(CASE h.label_period WHEN '7d' THEN p.sales_amount_7d WHEN '14d' THEN p.sales_amount_14d WHEN '30d' THEN p.sales_amount_30d ELSE p.sales_amount_90d END,4),
                                            'tag_gross_profit',ROUND(CASE h.label_period WHEN '7d' THEN p.tag_gross_profit_7d WHEN '14d' THEN p.tag_gross_profit_14d WHEN '30d' THEN p.tag_gross_profit_30d ELSE p.tag_gross_profit_90d END,4),
                                            'tag_margin_rate',ROUND(CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END,4)
                                        ),
                                        'matched_rule',JSON_OBJECT(
                                            'daily_sales',CASE
                                                WHEN h.child_label_name IN ('明星产品','潜力产品') AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN '> 5'
                                                WHEN h.child_label_name IN ('明星产品','潜力产品','瘦狗产品') AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN 'BETWEEN 1 AND 5'
                                                WHEN h.child_label_name = '瘦狗产品' THEN '< 1'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) = 0 THEN '= 0'
                                                WHEN h.child_label_name = '问题产品' THEN '> 0'
                                            END,
                                            'tag_margin_rate',CASE
                                                WHEN h.child_label_name = '明星产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN '> 15%'
                                                WHEN h.child_label_name = '明星产品' THEN '> 25%'
                                                WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN 'BETWEEN 5% AND 15%'
                                                WHEN h.child_label_name = '潜力产品' THEN 'BETWEEN 10% AND 25%'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN 'BETWEEN 5% AND 10%'
                                                WHEN h.child_label_name = '瘦狗产品' THEN '> 5%'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 THEN '< 5%'
                                            END
                                        ),
                                        'product_issue',JSON_OBJECT(
                                            'rule_version','20260729',
                                            'label',CASE
                                                WHEN h.child_label_name = '明星产品' THEN '明星产品-已达标'
                                                WHEN h.child_label_name = '潜力产品' AND (((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) BETWEEN 5 AND 15) OR ((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) BETWEEN 10 AND 15)) THEN '潜力产品-低毛利'
                                                WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) > 15 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) <= 25 THEN '潜力产品-日销或毛利待突破'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 10 THEN '瘦狗产品-低毛利'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) < 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 10 THEN '瘦狗产品-低日销'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) < 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 10 THEN '瘦狗产品-日销毛利双低'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 0 THEN '问题产品-零动销'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5 THEN '问题产品-低毛利'
                                                ELSE '数据异常-无法判断'
                                            END,
                                            'benchmark_target',CASE h.child_label_name
                                                WHEN '明星产品' THEN '维持明星标准'
                                                WHEN '潜力产品' THEN '明星产品'
                                                WHEN '瘦狗产品' THEN '潜力产品'
                                                WHEN '问题产品' THEN '退出问题产品'
                                                ELSE '恢复数据'
                                            END,
                                            'metrics_used',JSON_OBJECT(
                                                'daily_sales',ROUND((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END),4),
                                                'tag_margin_rate',ROUND((CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END),4)
                                            ),
                                            'matched_rule',JSON_OBJECT(
                                                'sales_role',h.child_label_name,
                                                'daily_sales',CASE
                                                    WHEN h.child_label_name IN ('明星产品','潜力产品') AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN '> 5'
                                                    WHEN h.child_label_name IN ('明星产品','潜力产品','瘦狗产品') AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN 'BETWEEN 1 AND 5'
                                                    WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) < 1 THEN '> 0 AND < 1'
                                                    WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 0 THEN '<= 0'
                                                    WHEN h.child_label_name = '问题产品' THEN '> 0'
                                                END,
                                                'tag_margin_rate',CASE
                                                    WHEN h.child_label_name = '明星产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN '> 15%'
                                                    WHEN h.child_label_name = '明星产品' THEN '> 25%'
                                                    WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN 'BETWEEN 5% AND 15%'
                                                    WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) <= 15 THEN 'BETWEEN 10% AND 15%'
                                                    WHEN h.child_label_name = '潜力产品' THEN '> 15% AND <= 25%'
                                                    WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN '>= 5% AND < 10%'
                                                    WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 10 THEN '>= 10%'
                                                    WHEN h.child_label_name = '瘦狗产品' THEN '>= 5% AND < 10%'
                                                    WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 0 THEN 'NOT_USED'
                                                    WHEN h.child_label_name = '问题产品' THEN '< 5%'
                                                END
                                            )
                                        )
                                    )
                                    WHEN '生命周期' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','lifecycle',
                                        'window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT(
                                            'first_receiving_date',DATE_FORMAT(fr.first_receiving_date,'%Y-%m-%d'),
                                            'lifecycle_days',DATEDIFF(v_data_date,fr.first_receiving_date),
                                            'first_mature_data_date',DATE_FORMAT(COALESCE(
                                                pm.first_mature_data_date,
                                                CASE WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                                           AND COALESCE(sr.role_7d,'') NOT IN ('瘦狗产品','问题产品')
                                                           AND COALESCE(sr.role_14d,'') NOT IN ('瘦狗产品','问题产品')
                                                           AND COALESCE(sr.role_30d,'') NOT IN ('瘦狗产品','问题产品')
                                                           AND COALESCE(sr.role_90d,'') NOT IN ('瘦狗产品','问题产品')
                                                     THEN v_data_date END
                                            ),'%Y-%m-%d'),
                                            'previous_mature_data_date',DATE_FORMAT(pm.previous_mature_data_date,'%Y-%m-%d'),
                                            'sales_role_7d',sr.role_7d,'sales_role_14d',sr.role_14d,'sales_role_30d',sr.role_30d,'sales_role_90d',sr.role_90d
                                        ),
                                        'matched_rule',JSON_OBJECT(
                                            'lifecycle_days',CASE
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 0 AND 30 THEN 'BETWEEN 0 AND 30'
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 31 AND 120 THEN 'BETWEEN 31 AND 120'
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 121 AND 300 THEN 'BETWEEN 121 AND 300'
                                                ELSE '> 300'
                                            END,
                                            'maturity_source',CASE
                                                WHEN pm.first_mature_data_date IS NOT NULL THEN 'previous_lifecycle_mature'
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                                 AND COALESCE(sr.role_7d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_14d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_30d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_90d,'') NOT IN ('瘦狗产品','问题产品') THEN 'current_sales_role_passed'
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300 THEN 'not_mature'
                                                ELSE 'not_applicable'
                                            END,
                                            'maturity_history_check',CASE
                                                WHEN pm.first_mature_data_date IS NOT NULL THEN 'entered_maturity'
                                                ELSE 'not_entered_maturity'
                                            END,
                                            'maturity_sales_role_check',CASE
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                                 AND COALESCE(sr.role_7d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_14d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_30d,'') NOT IN ('瘦狗产品','问题产品')
                                                 AND COALESCE(sr.role_90d,'') NOT IN ('瘦狗产品','问题产品') THEN 'passed'
                                                WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300 THEN 'not_passed'
                                            END
                                        )
                                    )                                    WHEN '定价' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','pricing','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('matched_price_region',pr.price_label),
                                        'matched_rule',JSON_OBJECT('price_region',pr.price_label)
                                    )
                                    WHEN '站点状态' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','site_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('covered_site_count',ss.covered_site_count),
                                        'matched_rule',JSON_OBJECT('covered_site_count',CASE WHEN ss.covered_site_count = 5 THEN '= 5' ELSE '<> 5' END)
                                    )
                                    WHEN '库存水平' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','inventory_level','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('inventory_support_days',ROUND(il.inventory_support_days,4)),
                                        'matched_rule',JSON_OBJECT('inventory_support_days',CASE WHEN il.inventory_support_days < 35 THEN '< 35' WHEN il.inventory_support_days < 90 THEN 'BETWEEN 35 AND < 90' ELSE '>= 90' END)
                                    )
                                    WHEN '流量结构' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','traffic_structure',
                                        'window',JSON_OBJECT('start',DATE_FORMAT(v_30d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','30d','days',30),
                                        'metrics',JSON_OBJECT('sales_amount',ROUND(ts.sales_amount_30d,4),'ad_spend',ROUND(ts.ad_spend_30d,4),'tacos',ROUND(100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0),4)),
                                        'matched_rule',JSON_OBJECT('tacos',CASE WHEN ts.sales_amount_30d <= 0 THEN NULL WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 70 THEN '>= 70%' WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 40 THEN 'BETWEEN 40% AND < 70%' WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 10 THEN 'BETWEEN 10% AND < 40%' ELSE '< 10%' END,'sales_amount',CASE WHEN ts.sales_amount_30d <= 0 THEN '<= 0' END)
                                    )
                                    WHEN '客户体验' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','customer_experience','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('average_rating',ROUND(ce.avg_star,4)),
                                        'matched_rule',JSON_OBJECT('average_rating',CASE WHEN ce.avg_star IS NULL OR ce.avg_star = 0 THEN 'IS NULL OR = 0' WHEN ce.avg_star >= 4.5 THEN '>= 4.50' WHEN ce.avg_star >= 4 THEN 'BETWEEN 4.00 AND < 4.50' WHEN ce.avg_star >= 3.5 THEN 'BETWEEN 3.50 AND < 4.00' ELSE '< 3.50' END)
                                    )
                                    WHEN '退货情况' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','return_rate','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','last_100_orders','orders',rr.order_count),
                                        'metrics',JSON_OBJECT('order_count',rr.order_count,'return_order_count',rr.return_order_count,'sales_volume',rr.sales_volume,'return_sales_volume',rr.return_sales_volume,'return_rate',ROUND(100*rr.return_rate,4)),
                                        'matched_rule',JSON_OBJECT('return_rate',CASE WHEN rr.return_rate < 0.02 THEN '< 2%' WHEN rr.return_rate < 0.05 THEN 'BETWEEN 2% AND < 5%' WHEN rr.return_rate <= 0.20 THEN 'BETWEEN 5% AND 20%' ELSE '> 20%' END)
                                    )
                                    WHEN '运营状态' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','operation_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('fba_available',op.fba_available,'fba_in_transit',op.fba_in_transit,'local_quantity',op.local_quantity,'is_out_of_stock',op.is_out_of_stock,'is_stopped',op.is_stopped,'is_return_event',op.is_return_event,'is_test_support',op.is_test_support),
                                        'matched_rule',JSON_OBJECT('operation_status',h.child_label_name,'fba_available',CASE WHEN h.child_label_name IN ('断货中','停售') THEN '= 0' END,'fba_in_transit',CASE WHEN h.child_label_name = '断货中' THEN '> 0 OR local_quantity > 0' WHEN h.child_label_name = '停售' THEN '= 0' END,'local_quantity',CASE WHEN h.child_label_name = '停售' THEN '= 0' END)
                                    )
                                    WHEN '返厂品阶段下钻' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','return_stage',
                                        'window',JSON_OBJECT(
                                            'start',DATE_FORMAT(rt.first_resume_sale_date,'%Y-%m-%d'),
                                            'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                                            'period','current'
                                        ),
                                        'metrics',JSON_OBJECT(
                                            'oos_start_date',DATE_FORMAT(rt.oos_start_date,'%Y-%m-%d'),
                                            'first_restock_date',DATE_FORMAT(rt.first_restock_date,'%Y-%m-%d'),
                                            'return_days',rt.return_days,
                                            'comparison_days',rt.comparison_days,
                                            'pre_comparison_sales',ROUND(rt.pre_comparison_sales,4),
                                            'post_comparison_sales',ROUND(rt.post_comparison_sales,4),
                                            'comparison_recovery_rate',ROUND(100*rt.comparison_recovery_rate,4),
                                            'pre_21d_sales',ROUND(rt.pre_21d_sales,4),
                                            'post_21d_sales',ROUND(rt.post_21d_sales,4),
                                            'd21_recovery_rate',ROUND(100*rt.d21_recovery_rate,4),
                                            'post_cumulative_sales',ROUND(rt.post_cumulative_sales,4),
                                            'cumulative_average_recovery_rate',ROUND(100*rt.cumulative_average_recovery_rate,4),
                                            'exit_date',DATE_FORMAT(rt.exit_date,'%Y-%m-%d')
                                        ),
                                        'matched_rule',JSON_OBJECT(
                                            'return_stage',rt.return_stage,
                                            'return_days',CASE
                                                WHEN rt.return_stage = '观察期' THEN 'BETWEEN 1 AND 7'
                                                WHEN rt.return_stage = '运营干预期' THEN 'BETWEEN 8 AND 21'
                                                ELSE '>= 22'
                                            END,
                                            'recovery_rate',CASE
                                                WHEN rt.return_stage = '持续干预期' THEN '< 70% OR NULL'
                                                WHEN rt.return_stage = '达标退出' THEN '>= 70%'
                                            END
                                        )
                                    )
                                    WHEN '断货在途流程标签' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','shipment_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('shipment_status',sh.shipment_status,'status_effective_time',DATE_FORMAT(sh.status_effective_time,'%Y-%m-%d %H:%i:%s'),'status_time_source',sh.status_time_source),
                                        'matched_rule',JSON_OBJECT('shipment_status',sh.shipment_status,'operation_status','断货中')
                                    )
                                    ELSE JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v45','type','unmapped','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period',h.label_period),
                                        'metrics',JSON_OBJECT('label_name',h.label_name,'child_label_name',h.child_label_name),
                                        'matched_rule',JSON_OBJECT()
                                    )
                                END AS evidence_json
                FROM (
                    SELECT DISTINCT h.`国家类别`, h.`国家`, h.`店铺`, h.`MSKU`, h.label_name,
                                    h.child_label_name, h.label_period, d.sub_label_id
                    FROM tmp_hits h
                    JOIN tmp_active_labels d
                      ON d.label_name = h.label_name
                     AND d.sub_label_name = h.child_label_name
                    WHERE h.child_label_name IS NOT NULL
                      AND h.`MSKU` IS NOT NULL
                      AND h.`MSKU` <> ''
                ) h
                LEFT JOIN tmp_perf p ON p.country_category=h.`国家类别` AND p.store=h.`店铺` AND p.MSKU=h.`MSKU`
                LEFT JOIN tmp_first_receiving fr ON fr.country_category=h.`国家类别` AND fr.store=h.`店铺` AND fr.MSKU=h.`MSKU`
                LEFT JOIN tmp_sales_role sr ON sr.country_category=h.`国家类别` AND sr.store=h.`店铺` AND sr.MSKU=h.`MSKU`
                LEFT JOIN tmp_previous_lifecycle_mature pm
                  ON pm.country_category=h.`国家类别` AND pm.store=h.`店铺` AND pm.MSKU=h.`MSKU`
                LEFT JOIN tmp_price pr ON pr.country_category=h.`国家类别` AND pr.country <=> h.`国家` AND pr.store=h.`店铺` AND pr.MSKU=h.`MSKU`
                LEFT JOIN tmp_site_status ss ON ss.country_category=h.`国家类别` AND ss.country <=> h.`国家` AND ss.store=h.`店铺` AND ss.MSKU=h.`MSKU`
                LEFT JOIN tmp_inventory_level il ON il.country_category=h.`国家类别` AND il.store=h.`店铺` AND il.MSKU=h.`MSKU`
                LEFT JOIN tmp_traffic_structure ts ON ts.country_category=h.`国家类别` AND ts.store=h.`店铺` AND ts.MSKU=h.`MSKU`
                LEFT JOIN tmp_customer_experience ce ON ce.country_category=h.`国家类别` AND ce.country <=> h.`国家` AND ce.store=h.`店铺` AND ce.MSKU=h.`MSKU`
                LEFT JOIN tmp_return_rate rr ON rr.country_category=h.`国家类别` AND rr.store=h.`店铺` AND rr.MSKU=h.`MSKU`
                LEFT JOIN tmp_op op ON op.country_category=h.`国家类别` AND op.store=h.`店铺` AND op.MSKU=h.`MSKU`
                LEFT JOIN tmp_return rt ON rt.country_category=h.`国家类别` AND rt.store=h.`店铺` AND rt.MSKU=h.`MSKU`
                LEFT JOIN tmp_ship sh ON sh.country_category=h.`国家类别` AND sh.store=h.`店铺` AND sh.MSKU=h.`MSKU`;
                SET v_record_count = ROW_COUNT();
                COMMIT;

                UPDATE `etl_datasync`.`etl_execution_log`
                SET `status` = 'success',
                    `end_time` = NOW(),
                    `data_time` = v_data_date,
                    `record_count` = v_record_count
                WHERE `id` = v_log_id;
            ELSE
                UPDATE `etl_datasync`.`etl_execution_log`
                SET `status` = 'success',
                    `end_time` = NOW(),
                    `record_count` = 0
                WHERE `id` = v_log_id;
            END IF;
    END;

    -- ========================================================================
    -- 阶段 2：站点销售角色、站点生命周期（V37 原逻辑内联）
    -- 阶段 1 发生异常会 RESIGNAL，流程立即终止；因此不会写入只有一半的站点标签。
    -- ========================================================================
    BEGIN
            DECLARE v_data_date DATE DEFAULT NULL;
            DECLARE v_max_source_date DATE DEFAULT NULL;
            DECLARE v_7d DATE DEFAULT NULL;
            DECLARE v_14d DATE DEFAULT NULL;
            DECLARE v_30d DATE DEFAULT NULL;
            DECLARE v_90d DATE DEFAULT NULL;
            DECLARE v_proc_name VARCHAR(255) DEFAULT 'sp_dws_标签表_一体化_v45';
            DECLARE v_log_id INT DEFAULT NULL;
            DECLARE v_record_count INT DEFAULT 0;
            DECLARE v_error_msg TEXT;
            DECLARE v_stage VARCHAR(255) DEFAULT 'initialization';

            DECLARE EXIT HANDLER FOR SQLEXCEPTION
            BEGIN
                GET DIAGNOSTICS CONDITION 1 v_error_msg = MESSAGE_TEXT;
                ROLLBACK;
                IF v_log_id IS NOT NULL THEN
                    UPDATE `etl_datasync`.`etl_execution_log`
                    SET `status` = 'error', `end_time` = NOW()
                    WHERE `id` = v_log_id;
                    INSERT INTO `etl_datasync`.`etl_error_log`
                        (`proc_name`, `error_time`, `error_message`, `execution_log_id`)
                    VALUES
                        (v_proc_name, NOW(), CONCAT('[stage: ', v_stage, '] ', v_error_msg), v_log_id);
                END IF;
                RESIGNAL;
            END;

            INSERT INTO `etl_datasync`.`etl_execution_log` (`proc_name`, `start_time`, `status`)
            VALUES (v_proc_name, NOW(), 'started');
            SET v_log_id = LAST_INSERT_ID();

            -- 与基础标签共用外层已锁定并校验过的业务日期；不再重复扫描产品表现表。
            SET v_max_source_date = v_locked_max_source_date;
            SET v_data_date = v_run_data_date;

            IF v_data_date IS NOT NULL THEN
                SET v_7d = DATE_SUB(v_data_date, INTERVAL 6 DAY);
                SET v_14d = DATE_SUB(v_data_date, INTERVAL 13 DAY);
                SET v_30d = DATE_SUB(v_data_date, INTERVAL 29 DAY);
                SET v_90d = DATE_SUB(v_data_date, INTERVAL 89 DAY);

                -- 标签详情表必须先部署 ID=13（站点销售角色）和 ID=14（站点生命周期）的新定义。
                SET v_stage = 'active station labels';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_active_labels;
                CREATE TEMPORARY TABLE tmp_station_active_labels AS
                SELECT DISTINCT CAST(`label_name` AS CHAR(100)) AS label_name,
                                CAST(`sub_label_name` AS CHAR(100)) AS sub_label_name,
                                `sub_label_id`
                FROM `dws_datasync`.`dws_标签详情表`
                WHERE CAST(`label_name` AS CHAR) IN ('站点销售角色', '站点生命周期')
                  AND CAST(`status` AS CHAR) = '启用'
                  AND `sub_label_name` IS NOT NULL;

                -- 商品池：Listing 最新同步记录（marketplace + seller_name + seller_sku），
                -- 以国家 + 清洗店铺 + MSKU 作为站点标签粒度；排除退款及 Amazon 占位 SKU。
                SET v_stage = 'station listing keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_listing_keys;
                CREATE TEMPORARY TABLE tmp_station_listing_keys AS
                SELECT DISTINCT
                       CASE WHEN CAST(li.`marketplace` AS CHAR) = '英国' THEN '英国站'
                            WHEN CAST(li.`marketplace` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                            ELSE '欧洲站' END AS country_category,
                       CAST(li.`marketplace` AS CHAR(100)) AS country,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) > 0
                               THEN LEFT(SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1),
                                         LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)
                       END AS store,
                       CAST(li.`seller_sku` AS CHAR(255)) AS msku
                FROM (
                    SELECT li.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST(li.`marketplace` AS CHAR),
                                            CAST(li.`seller_name` AS CHAR),
                                            CAST(li.`seller_sku` AS CHAR)
                               ORDER BY li.`create_time` DESC, li.`id` DESC
                           ) AS rn
                    FROM `dwd_datasync`.`lx_sales_mws_listing` li
                    WHERE li.`seller_sku` IS NOT NULL
                      AND CAST(li.`seller_sku` AS CHAR) <> ''
                      AND LOWER(TRIM(CAST(li.`seller_sku` AS CHAR))) NOT LIKE 'amzn.gr%'
                      AND UPPER(TRIM(CAST(li.`seller_sku` AS CHAR))) NOT LIKE 'AMAZON%'
                ) li
                WHERE li.rn = 1;
                ALTER TABLE tmp_station_listing_keys
                    ADD INDEX idx_station_listing_keys (country, store, msku);

                -- 指标统计粒度：国家 + 店铺 + MSKU。先同时计算 7/14/30/90 天，
                -- 其中 30d 写入站点销售角色；7/14/30/90d 仅供站点生命周期“成熟期”判断。
                SET v_stage = 'station sales metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_sales_metrics;
                CREATE TEMPORARY TABLE tmp_station_sales_metrics AS
                SELECT k.country_category,
                       k.country,
                       k.store,
                       k.msku,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_7d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_14d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_30d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_90d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_7d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_14d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_30d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_90d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_7d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_14d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_30d,
                       SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END) AS tag_gross_profit_90d,
                       CASE WHEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_7d,
                       CASE WHEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_14d,
                       CASE WHEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_30d,
                       CASE WHEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN CASE WHEN COALESCE(p.`volume`, 0) = 0 THEN 0 ELSE COALESCE(p.`predict_gross_profit`, 0) END ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_90d,
                       AVG(CASE WHEN DATE(p.`start_date`) BETWEEN v_7d AND v_data_date AND p.`rank` > 0 THEN p.`rank` END) AS small_rank_7d,
                       AVG(CASE WHEN DATE(p.`start_date`) BETWEEN v_14d AND v_data_date AND p.`rank` > 0 THEN p.`rank` END) AS small_rank_14d,
                       AVG(CASE WHEN DATE(p.`start_date`) BETWEEN v_30d AND v_data_date AND p.`rank` > 0 THEN p.`rank` END) AS small_rank_30d,
                       AVG(CASE WHEN DATE(p.`start_date`) BETWEEN v_90d AND v_data_date AND p.`rank` > 0 THEN p.`rank` END) AS small_rank_90d
                FROM tmp_station_listing_keys k
                LEFT JOIN `dwd_datasync`.`lx_statistics_product_performance` p
                  ON k.country = CAST(p.`country` AS CHAR)
                 AND k.store = CASE WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) > 0
                                    THEN LEFT(SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1), LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) - 1)
                                    ELSE SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1) END
                 AND k.msku = CAST(p.`seller_sku` AS CHAR)
                 AND DATE(p.`start_date`) BETWEEN v_90d AND v_data_date
                GROUP BY k.country_category, k.country, k.store, k.msku;
                ALTER TABLE tmp_station_sales_metrics
                    ADD INDEX idx_station_sales_metrics (country, store, msku);

                -- 规则：问题产品优先；基于日销和结算毛利率得到基础角色；小类排名 rank 执行封顶/降级。
                -- rank=99999 为无效排名，直接归问题产品。
                SET v_stage = 'station role classification';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_sales_roles;
                CREATE TEMPORARY TABLE tmp_station_sales_roles AS
                SELECT country_category, country, store, msku,
                       CASE
                           WHEN COALESCE(volume_7d / 7.0, 0) <= 0 THEN '问题产品(站点)'
                           WHEN COALESCE(margin_rate_7d, 0) < 0.05 THEN '问题产品(站点)'
                           WHEN small_rank_7d IS NULL OR small_rank_7d <= 0 OR small_rank_7d >= 99999 THEN '问题产品(站点)'
                           WHEN small_rank_7d > 100 THEN '瘦狗产品(站点)'
                           WHEN small_rank_7d BETWEEN 51 AND 100 AND ((volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_7d <= 50 AND ((volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.25)) THEN '明星产品(站点)'
                           WHEN (volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.05 AND margin_rate_7d < 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.10 AND margin_rate_7d < 0.25) THEN '潜力产品(站点)'
                           ELSE '瘦狗产品(站点)'
                       END AS role_7d,
                       CASE
                           WHEN COALESCE(volume_14d / 14.0, 0) <= 0 THEN '问题产品(站点)'
                           WHEN COALESCE(margin_rate_14d, 0) < 0.05 THEN '问题产品(站点)'
                           WHEN small_rank_14d IS NULL OR small_rank_14d <= 0 OR small_rank_14d >= 99999 THEN '问题产品(站点)'
                           WHEN small_rank_14d > 100 THEN '瘦狗产品(站点)'
                           WHEN small_rank_14d BETWEEN 51 AND 100 AND ((volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_14d <= 50 AND ((volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.25)) THEN '明星产品(站点)'
                           WHEN (volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.05 AND margin_rate_14d < 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.10 AND margin_rate_14d < 0.25) THEN '潜力产品(站点)'
                           ELSE '瘦狗产品(站点)'
                       END AS role_14d,
                       CASE
                           WHEN COALESCE(volume_30d / 30.0, 0) <= 0 THEN '问题产品(站点)'
                           WHEN COALESCE(margin_rate_30d, 0) < 0.05 THEN '问题产品(站点)'
                           WHEN small_rank_30d IS NULL OR small_rank_30d <= 0 OR small_rank_30d >= 99999 THEN '问题产品(站点)'
                           WHEN small_rank_30d > 100 THEN '瘦狗产品(站点)'
                           WHEN small_rank_30d BETWEEN 51 AND 100 AND ((volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_30d <= 50 AND ((volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.25)) THEN '明星产品(站点)'
                           WHEN (volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.05 AND margin_rate_30d < 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.10 AND margin_rate_30d < 0.25) THEN '潜力产品(站点)'
                           ELSE '瘦狗产品(站点)'
                       END AS role_30d,
                       CASE
                           WHEN COALESCE(volume_90d / 90.0, 0) <= 0 THEN '问题产品(站点)'
                           WHEN COALESCE(margin_rate_90d, 0) < 0.05 THEN '问题产品(站点)'
                           WHEN small_rank_90d IS NULL OR small_rank_90d <= 0 OR small_rank_90d >= 99999 THEN '问题产品(站点)'
                           WHEN small_rank_90d > 100 THEN '瘦狗产品(站点)'
                           WHEN small_rank_90d BETWEEN 51 AND 100 AND ((volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_90d <= 50 AND ((volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.25)) THEN '明星产品(站点)'
                           WHEN (volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.05 AND margin_rate_90d < 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.10 AND margin_rate_90d < 0.25) THEN '潜力产品(站点)'
                           ELSE '瘦狗产品(站点)'
                       END AS role_90d
                FROM tmp_station_sales_metrics;
                ALTER TABLE tmp_station_sales_roles
                    ADD INDEX idx_station_sales_roles (country, store, msku);

                -- 站点生命周期首次收货：按 国家类别 + 店铺 + MSKU 取最早 receiving_time。
                -- 不再按国家限制货件来源：只要该国家类别内任一国家已首次收货，
                -- 即认为该国家类别下所有存在 Listing 的国家都具备相同的生命周期起点。
                -- 站点销售角色仍在后续按 国家 + 店铺 + MSKU 独立计算，不受此处影响。
                -- 先仅保留实际存在 Listing 的国家类别+店铺+MSKU，避免扫描无关货件。
                SET v_stage = 'station category first receiving keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_category_receiving_keys;
                CREATE TEMPORARY TABLE tmp_station_category_receiving_keys AS
                SELECT DISTINCT country_category, store, msku
                FROM tmp_station_listing_keys;
                ALTER TABLE tmp_station_category_receiving_keys
                    ADD INDEX idx_station_category_receiving_keys (country_category, store, msku);

                SET v_stage = 'station category first receiving';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_category_first_receiving;
                CREATE TEMPORARY TABLE tmp_station_category_first_receiving AS
                SELECT k.country_category,
                       k.store,
                       k.msku,
                       MIN(STR_TO_DATE(LEFT(CAST(s.`receiving_time` AS CHAR), 10), '%Y-%m-%d')) AS first_receiving_date
                FROM tmp_station_category_receiving_keys k
                JOIN `dwd_datasync`.`lx_fba_shipment` s
                  ON k.country_category = CASE
                                              WHEN CAST(s.`country` AS CHAR) = '英国' THEN '英国站'
                                              WHEN CAST(s.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                              ELSE '欧洲站'
                                          END
                 AND k.store = CASE
                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) > 0
                                       THEN LEFT(SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1),
                                                 LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) - 1)
                                   ELSE SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)
                               END
                 AND k.msku = CAST(s.`msku` AS CHAR)
                -- receiving_time 为 VARCHAR，源表存在空字符串；不能直接 DATE('')，否则严格模式报 Incorrect datetime value。
                WHERE NULLIF(TRIM(CAST(s.`receiving_time` AS CHAR)), '') IS NOT NULL
                  AND CAST(s.`receiving_time` AS CHAR) REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                  AND STR_TO_DATE(LEFT(CAST(s.`receiving_time` AS CHAR), 10), '%Y-%m-%d') <= v_data_date
                GROUP BY k.country_category, k.store, k.msku;
                ALTER TABLE tmp_station_category_first_receiving
                    ADD INDEX idx_station_category_first_receiving (country_category, store, msku);

                SET v_stage = 'station first receiving';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_first_receiving;
                CREATE TEMPORARY TABLE tmp_station_first_receiving AS
                SELECT k.country_category,
                       k.country,
                       k.store,
                       k.msku,
                       fr.first_receiving_date
                FROM tmp_station_listing_keys k
                JOIN tmp_station_category_first_receiving fr
                  ON fr.country_category = k.country_category
                 AND fr.store = k.store
                 AND fr.msku = k.msku;
                ALTER TABLE tmp_station_first_receiving
                    ADD INDEX idx_station_first_receiving (country, store, msku);

                SET v_stage = 'station label write';
                START TRANSACTION;

                -- 新增站点标签只清理自身：当天先删以支持重跑；同时仅保留最近两天业务日期。
                DELETE t
                FROM `dws_datasync`.`dws_标签表` t
                JOIN tmp_station_active_labels l ON l.sub_label_id = t.label_id
                WHERE t.`data_date` = v_data_date;

                DELETE t
                FROM `dws_datasync`.`dws_标签表` t
                JOIN tmp_station_active_labels l ON l.sub_label_id = t.label_id
                WHERE t.`data_date` < DATE_SUB(v_data_date, INTERVAL 1 DAY);

                -- 站点销售角色按 7/14/30/90d 分别落表；证据仅在最终写入时构造，保留实际使用的销量、毛利率、小类排名和命中规则。
                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '7d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v45','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_7d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','7d','days',7),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_7d,4),'daily_sales',ROUND(m.volume_7d / 7.0,4),
                               'sales_amount',ROUND(m.sales_amount_7d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_7d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_7d,4),'small_rank',ROUND(m.small_rank_7d,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'daily_sales',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND COALESCE(m.volume_7d / 7.0,0) <= 0 THEN '<= 0'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 > 3 THEN '> 3'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.volume_7d / 7.0 > 3 THEN '> 3'
                                   WHEN r.role_7d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 3'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND COALESCE(m.margin_rate_7d,0) < 0.05 THEN '< 5%'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 > 3 THEN '>= 15%'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN '>= 25%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND (m.small_rank_7d IS NULL OR m.small_rank_7d <= 0 OR m.small_rank_7d >= 99999) THEN 'IS NULL OR <= 0 OR >= 99999'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 THEN '> 100'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_7d = '明星产品(站点)' AND m.small_rank_7d <= 50 THEN '<= 50'
                               END
                           ),
                            'product_issue',JSON_OBJECT(
                                'rule_version','20260729',
                                'label',CASE
                                    WHEN r.role_7d = '明星产品(站点)' THEN '已达到站点明星产品标准'
                                    WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d <= 50 AND (((m.volume_7d / 7.0) > 3 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.15) OR ((m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.10 AND m.margin_rate_7d < 0.15)) THEN '潜力产品(站点)-低毛利'
                                    WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d <= 50 AND (m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.15 AND m.margin_rate_7d < 0.25 THEN '潜力产品(站点)-日销或毛利待突破'
                                    WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 AND (((m.volume_7d / 7.0) > 3 AND m.margin_rate_7d >= 0.15) OR ((m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.25)) THEN '潜力产品(站点)-排名不足'
                                    WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 AND (((m.volume_7d / 7.0) > 3 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.15) OR ((m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.10 AND m.margin_rate_7d < 0.15)) THEN '潜力产品(站点)-低毛利且排名不足'
                                    WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 AND (m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.15 AND m.margin_rate_7d < 0.25 THEN '潜力产品(站点)-排名及日销或毛利待突破'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d <= 100 AND (m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.10 THEN '瘦狗产品(站点)-低毛利'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d <= 100 AND (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 AND m.margin_rate_7d >= 0.10 THEN '瘦狗产品(站点)-低日销'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d <= 100 AND (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.10 THEN '瘦狗产品(站点)-日销毛利双低'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 AND (((m.volume_7d / 7.0) > 3 AND m.margin_rate_7d >= 0.05) OR ((m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.10)) THEN '瘦狗产品(站点)-排名不足'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 AND (m.volume_7d / 7.0) BETWEEN 1 AND 3 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.10 THEN '瘦狗产品(站点)-低毛利且排名不足'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 AND (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 AND m.margin_rate_7d >= 0.10 THEN '瘦狗产品(站点)-低日销且排名不足'
                                    WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 AND (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 AND m.margin_rate_7d >= 0.05 AND m.margin_rate_7d < 0.10 THEN '瘦狗产品(站点)-日销毛利排名均不足'
                                    WHEN r.role_7d = '问题产品(站点)' AND COALESCE((m.volume_7d / 7.0),0) <= 0 THEN '问题产品(站点)-零动销'
                                    WHEN r.role_7d = '问题产品(站点)' AND (m.volume_7d / 7.0) > 0 AND COALESCE(m.margin_rate_7d,0) < 0.05 AND (m.small_rank_7d IS NULL OR m.small_rank_7d <= 0 OR m.small_rank_7d >= 99999) THEN '问题产品(站点)-低毛利且排名无效'
                                    WHEN r.role_7d = '问题产品(站点)' AND (m.volume_7d / 7.0) > 0 AND COALESCE(m.margin_rate_7d,0) < 0.05 THEN '问题产品(站点)-低毛利'
                                    WHEN r.role_7d = '问题产品(站点)' AND (m.volume_7d / 7.0) > 0 AND COALESCE(m.margin_rate_7d,0) >= 0.05 AND (m.small_rank_7d IS NULL OR m.small_rank_7d <= 0 OR m.small_rank_7d >= 99999) THEN '问题产品(站点)-排名无效'
                                    ELSE '数据异常-无法判断'
                                END,
                                'benchmark_target',CASE r.role_7d
                                    WHEN '明星产品(站点)' THEN '保持站点明星'
                                    WHEN '潜力产品(站点)' THEN '站点明星'
                                    WHEN '瘦狗产品(站点)' THEN '站点潜力'
                                    WHEN '问题产品(站点)' THEN '退出问题产品'
                                    ELSE '恢复数据'
                                END,
                                'metrics_used',JSON_OBJECT(
                                    'daily_sales',ROUND((m.volume_7d / 7.0),4),
                                    'tag_margin_rate',ROUND(100 * m.margin_rate_7d,4),
                                    'small_rank',ROUND(m.small_rank_7d,4)
                                ),
                                'matched_rule',JSON_OBJECT(
                                    'station_sales_role',r.role_7d,
                                    'daily_sales',CASE
                                        WHEN (m.volume_7d / 7.0) > 3 THEN '> 3'
                                        WHEN (m.volume_7d / 7.0) BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                        WHEN (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 THEN '> 0 AND < 1'
                                        WHEN COALESCE((m.volume_7d / 7.0),0) <= 0 THEN '<= 0'
                                    END,
                                    'tag_margin_rate',CASE
                                        WHEN r.role_7d = '明星产品(站点)' AND (m.volume_7d / 7.0) > 3 THEN '>= 15%'
                                        WHEN r.role_7d = '明星产品(站点)' THEN '>= 25%'
                                        WHEN r.role_7d = '潜力产品(站点)' AND (m.volume_7d / 7.0) > 3 AND m.margin_rate_7d < 0.15 THEN '>= 5% AND < 15%'
                                        WHEN r.role_7d = '潜力产品(站点)' AND (m.volume_7d / 7.0) > 3 THEN '>= 15%'
                                        WHEN r.role_7d = '潜力产品(站点)' AND m.margin_rate_7d < 0.15 THEN '>= 10% AND < 15%'
                                        WHEN r.role_7d = '潜力产品(站点)' AND m.margin_rate_7d < 0.25 THEN '>= 15% AND < 25%'
                                        WHEN r.role_7d = '潜力产品(站点)' THEN '>= 25%'
                                        WHEN r.role_7d = '瘦狗产品(站点)' AND m.margin_rate_7d < 0.10 THEN '>= 5% AND < 10%'
                                        WHEN r.role_7d = '瘦狗产品(站点)' AND (m.volume_7d / 7.0) > 0 AND (m.volume_7d / 7.0) < 1 THEN '>= 10%'
                                        WHEN r.role_7d = '瘦狗产品(站点)' AND (m.volume_7d / 7.0) > 3 THEN '>= 5%'
                                        WHEN r.role_7d = '瘦狗产品(站点)' THEN '>= 10%'
                                        WHEN r.role_7d = '问题产品(站点)' AND COALESCE((m.volume_7d / 7.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN COALESCE(m.margin_rate_7d,0) < 0.05 THEN '< 5%'
                                        ELSE '>= 5%'
                                    END,
                                    'small_rank',CASE
                                        WHEN COALESCE((m.volume_7d / 7.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN m.small_rank_7d IS NULL OR m.small_rank_7d <= 0 OR m.small_rank_7d >= 99999 THEN 'IS NULL OR <= 0 OR >= 99999'
                                        WHEN m.small_rank_7d <= 50 THEN '<= 50'
                                        WHEN m.small_rank_7d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                        WHEN m.small_rank_7d > 100 THEN '> 100'
                                    END
                                )
                            )
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_7d;
                SET v_record_count = ROW_COUNT();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '14d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v45','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_14d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','14d','days',14),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_14d,4),'daily_sales',ROUND(m.volume_14d / 14.0,4),
                               'sales_amount',ROUND(m.sales_amount_14d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_14d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_14d,4),'small_rank',ROUND(m.small_rank_14d,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'daily_sales',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND COALESCE(m.volume_14d / 14.0,0) <= 0 THEN '<= 0'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 > 3 THEN '> 3'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.volume_14d / 14.0 > 3 THEN '> 3'
                                   WHEN r.role_14d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 3'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND COALESCE(m.margin_rate_14d,0) < 0.05 THEN '< 5%'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 > 3 THEN '>= 15%'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN '>= 25%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND (m.small_rank_14d IS NULL OR m.small_rank_14d <= 0 OR m.small_rank_14d >= 99999) THEN 'IS NULL OR <= 0 OR >= 99999'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 THEN '> 100'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_14d = '明星产品(站点)' AND m.small_rank_14d <= 50 THEN '<= 50'
                               END
                           ),
                            'product_issue',JSON_OBJECT(
                                'rule_version','20260729',
                                'label',CASE
                                    WHEN r.role_14d = '明星产品(站点)' THEN '已达到站点明星产品标准'
                                    WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d <= 50 AND (((m.volume_14d / 14.0) > 3 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.15) OR ((m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.10 AND m.margin_rate_14d < 0.15)) THEN '潜力产品(站点)-低毛利'
                                    WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d <= 50 AND (m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.15 AND m.margin_rate_14d < 0.25 THEN '潜力产品(站点)-日销或毛利待突破'
                                    WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 AND (((m.volume_14d / 14.0) > 3 AND m.margin_rate_14d >= 0.15) OR ((m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.25)) THEN '潜力产品(站点)-排名不足'
                                    WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 AND (((m.volume_14d / 14.0) > 3 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.15) OR ((m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.10 AND m.margin_rate_14d < 0.15)) THEN '潜力产品(站点)-低毛利且排名不足'
                                    WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 AND (m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.15 AND m.margin_rate_14d < 0.25 THEN '潜力产品(站点)-排名及日销或毛利待突破'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d <= 100 AND (m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.10 THEN '瘦狗产品(站点)-低毛利'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d <= 100 AND (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 AND m.margin_rate_14d >= 0.10 THEN '瘦狗产品(站点)-低日销'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d <= 100 AND (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.10 THEN '瘦狗产品(站点)-日销毛利双低'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 AND (((m.volume_14d / 14.0) > 3 AND m.margin_rate_14d >= 0.05) OR ((m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.10)) THEN '瘦狗产品(站点)-排名不足'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 AND (m.volume_14d / 14.0) BETWEEN 1 AND 3 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.10 THEN '瘦狗产品(站点)-低毛利且排名不足'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 AND (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 AND m.margin_rate_14d >= 0.10 THEN '瘦狗产品(站点)-低日销且排名不足'
                                    WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 AND (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 AND m.margin_rate_14d >= 0.05 AND m.margin_rate_14d < 0.10 THEN '瘦狗产品(站点)-日销毛利排名均不足'
                                    WHEN r.role_14d = '问题产品(站点)' AND COALESCE((m.volume_14d / 14.0),0) <= 0 THEN '问题产品(站点)-零动销'
                                    WHEN r.role_14d = '问题产品(站点)' AND (m.volume_14d / 14.0) > 0 AND COALESCE(m.margin_rate_14d,0) < 0.05 AND (m.small_rank_14d IS NULL OR m.small_rank_14d <= 0 OR m.small_rank_14d >= 99999) THEN '问题产品(站点)-低毛利且排名无效'
                                    WHEN r.role_14d = '问题产品(站点)' AND (m.volume_14d / 14.0) > 0 AND COALESCE(m.margin_rate_14d,0) < 0.05 THEN '问题产品(站点)-低毛利'
                                    WHEN r.role_14d = '问题产品(站点)' AND (m.volume_14d / 14.0) > 0 AND COALESCE(m.margin_rate_14d,0) >= 0.05 AND (m.small_rank_14d IS NULL OR m.small_rank_14d <= 0 OR m.small_rank_14d >= 99999) THEN '问题产品(站点)-排名无效'
                                    ELSE '数据异常-无法判断'
                                END,
                                'benchmark_target',CASE r.role_14d
                                    WHEN '明星产品(站点)' THEN '保持站点明星'
                                    WHEN '潜力产品(站点)' THEN '站点明星'
                                    WHEN '瘦狗产品(站点)' THEN '站点潜力'
                                    WHEN '问题产品(站点)' THEN '退出问题产品'
                                    ELSE '恢复数据'
                                END,
                                'metrics_used',JSON_OBJECT(
                                    'daily_sales',ROUND((m.volume_14d / 14.0),4),
                                    'tag_margin_rate',ROUND(100 * m.margin_rate_14d,4),
                                    'small_rank',ROUND(m.small_rank_14d,4)
                                ),
                                'matched_rule',JSON_OBJECT(
                                    'station_sales_role',r.role_14d,
                                    'daily_sales',CASE
                                        WHEN (m.volume_14d / 14.0) > 3 THEN '> 3'
                                        WHEN (m.volume_14d / 14.0) BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                        WHEN (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 THEN '> 0 AND < 1'
                                        WHEN COALESCE((m.volume_14d / 14.0),0) <= 0 THEN '<= 0'
                                    END,
                                    'tag_margin_rate',CASE
                                        WHEN r.role_14d = '明星产品(站点)' AND (m.volume_14d / 14.0) > 3 THEN '>= 15%'
                                        WHEN r.role_14d = '明星产品(站点)' THEN '>= 25%'
                                        WHEN r.role_14d = '潜力产品(站点)' AND (m.volume_14d / 14.0) > 3 AND m.margin_rate_14d < 0.15 THEN '>= 5% AND < 15%'
                                        WHEN r.role_14d = '潜力产品(站点)' AND (m.volume_14d / 14.0) > 3 THEN '>= 15%'
                                        WHEN r.role_14d = '潜力产品(站点)' AND m.margin_rate_14d < 0.15 THEN '>= 10% AND < 15%'
                                        WHEN r.role_14d = '潜力产品(站点)' AND m.margin_rate_14d < 0.25 THEN '>= 15% AND < 25%'
                                        WHEN r.role_14d = '潜力产品(站点)' THEN '>= 25%'
                                        WHEN r.role_14d = '瘦狗产品(站点)' AND m.margin_rate_14d < 0.10 THEN '>= 5% AND < 10%'
                                        WHEN r.role_14d = '瘦狗产品(站点)' AND (m.volume_14d / 14.0) > 0 AND (m.volume_14d / 14.0) < 1 THEN '>= 10%'
                                        WHEN r.role_14d = '瘦狗产品(站点)' AND (m.volume_14d / 14.0) > 3 THEN '>= 5%'
                                        WHEN r.role_14d = '瘦狗产品(站点)' THEN '>= 10%'
                                        WHEN r.role_14d = '问题产品(站点)' AND COALESCE((m.volume_14d / 14.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN COALESCE(m.margin_rate_14d,0) < 0.05 THEN '< 5%'
                                        ELSE '>= 5%'
                                    END,
                                    'small_rank',CASE
                                        WHEN COALESCE((m.volume_14d / 14.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN m.small_rank_14d IS NULL OR m.small_rank_14d <= 0 OR m.small_rank_14d >= 99999 THEN 'IS NULL OR <= 0 OR >= 99999'
                                        WHEN m.small_rank_14d <= 50 THEN '<= 50'
                                        WHEN m.small_rank_14d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                        WHEN m.small_rank_14d > 100 THEN '> 100'
                                    END
                                )
                            )
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_14d;
                SET v_record_count = v_record_count + ROW_COUNT();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '30d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v45','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_30d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','30d','days',30),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_30d,4),'daily_sales',ROUND(m.volume_30d / 30.0,4),
                               'sales_amount',ROUND(m.sales_amount_30d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_30d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_30d,4),'small_rank',ROUND(m.small_rank_30d,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'daily_sales',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND COALESCE(m.volume_30d / 30.0,0) <= 0 THEN '<= 0'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 > 3 THEN '> 3'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.volume_30d / 30.0 > 3 THEN '> 3'
                                   WHEN r.role_30d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 3'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND COALESCE(m.margin_rate_30d,0) < 0.05 THEN '< 5%'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 > 3 THEN '>= 15%'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN '>= 25%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND (m.small_rank_30d IS NULL OR m.small_rank_30d <= 0 OR m.small_rank_30d >= 99999) THEN 'IS NULL OR <= 0 OR >= 99999'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 THEN '> 100'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_30d = '明星产品(站点)' AND m.small_rank_30d <= 50 THEN '<= 50'
                               END
                           ),
                            'product_issue',JSON_OBJECT(
                                'rule_version','20260729',
                                'label',CASE
                                    WHEN r.role_30d = '明星产品(站点)' THEN '已达到站点明星产品标准'
                                    WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d <= 50 AND (((m.volume_30d / 30.0) > 3 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.15) OR ((m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.10 AND m.margin_rate_30d < 0.15)) THEN '潜力产品(站点)-低毛利'
                                    WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d <= 50 AND (m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.15 AND m.margin_rate_30d < 0.25 THEN '潜力产品(站点)-日销或毛利待突破'
                                    WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 AND (((m.volume_30d / 30.0) > 3 AND m.margin_rate_30d >= 0.15) OR ((m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.25)) THEN '潜力产品(站点)-排名不足'
                                    WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 AND (((m.volume_30d / 30.0) > 3 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.15) OR ((m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.10 AND m.margin_rate_30d < 0.15)) THEN '潜力产品(站点)-低毛利且排名不足'
                                    WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 AND (m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.15 AND m.margin_rate_30d < 0.25 THEN '潜力产品(站点)-排名及日销或毛利待突破'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d <= 100 AND (m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.10 THEN '瘦狗产品(站点)-低毛利'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d <= 100 AND (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 AND m.margin_rate_30d >= 0.10 THEN '瘦狗产品(站点)-低日销'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d <= 100 AND (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.10 THEN '瘦狗产品(站点)-日销毛利双低'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 AND (((m.volume_30d / 30.0) > 3 AND m.margin_rate_30d >= 0.05) OR ((m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.10)) THEN '瘦狗产品(站点)-排名不足'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 AND (m.volume_30d / 30.0) BETWEEN 1 AND 3 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.10 THEN '瘦狗产品(站点)-低毛利且排名不足'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 AND (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 AND m.margin_rate_30d >= 0.10 THEN '瘦狗产品(站点)-低日销且排名不足'
                                    WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 AND (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 AND m.margin_rate_30d >= 0.05 AND m.margin_rate_30d < 0.10 THEN '瘦狗产品(站点)-日销毛利排名均不足'
                                    WHEN r.role_30d = '问题产品(站点)' AND COALESCE((m.volume_30d / 30.0),0) <= 0 THEN '问题产品(站点)-零动销'
                                    WHEN r.role_30d = '问题产品(站点)' AND (m.volume_30d / 30.0) > 0 AND COALESCE(m.margin_rate_30d,0) < 0.05 AND (m.small_rank_30d IS NULL OR m.small_rank_30d <= 0 OR m.small_rank_30d >= 99999) THEN '问题产品(站点)-低毛利且排名无效'
                                    WHEN r.role_30d = '问题产品(站点)' AND (m.volume_30d / 30.0) > 0 AND COALESCE(m.margin_rate_30d,0) < 0.05 THEN '问题产品(站点)-低毛利'
                                    WHEN r.role_30d = '问题产品(站点)' AND (m.volume_30d / 30.0) > 0 AND COALESCE(m.margin_rate_30d,0) >= 0.05 AND (m.small_rank_30d IS NULL OR m.small_rank_30d <= 0 OR m.small_rank_30d >= 99999) THEN '问题产品(站点)-排名无效'
                                    ELSE '数据异常-无法判断'
                                END,
                                'benchmark_target',CASE r.role_30d
                                    WHEN '明星产品(站点)' THEN '保持站点明星'
                                    WHEN '潜力产品(站点)' THEN '站点明星'
                                    WHEN '瘦狗产品(站点)' THEN '站点潜力'
                                    WHEN '问题产品(站点)' THEN '退出问题产品'
                                    ELSE '恢复数据'
                                END,
                                'metrics_used',JSON_OBJECT(
                                    'daily_sales',ROUND((m.volume_30d / 30.0),4),
                                    'tag_margin_rate',ROUND(100 * m.margin_rate_30d,4),
                                    'small_rank',ROUND(m.small_rank_30d,4)
                                ),
                                'matched_rule',JSON_OBJECT(
                                    'station_sales_role',r.role_30d,
                                    'daily_sales',CASE
                                        WHEN (m.volume_30d / 30.0) > 3 THEN '> 3'
                                        WHEN (m.volume_30d / 30.0) BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                        WHEN (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 THEN '> 0 AND < 1'
                                        WHEN COALESCE((m.volume_30d / 30.0),0) <= 0 THEN '<= 0'
                                    END,
                                    'tag_margin_rate',CASE
                                        WHEN r.role_30d = '明星产品(站点)' AND (m.volume_30d / 30.0) > 3 THEN '>= 15%'
                                        WHEN r.role_30d = '明星产品(站点)' THEN '>= 25%'
                                        WHEN r.role_30d = '潜力产品(站点)' AND (m.volume_30d / 30.0) > 3 AND m.margin_rate_30d < 0.15 THEN '>= 5% AND < 15%'
                                        WHEN r.role_30d = '潜力产品(站点)' AND (m.volume_30d / 30.0) > 3 THEN '>= 15%'
                                        WHEN r.role_30d = '潜力产品(站点)' AND m.margin_rate_30d < 0.15 THEN '>= 10% AND < 15%'
                                        WHEN r.role_30d = '潜力产品(站点)' AND m.margin_rate_30d < 0.25 THEN '>= 15% AND < 25%'
                                        WHEN r.role_30d = '潜力产品(站点)' THEN '>= 25%'
                                        WHEN r.role_30d = '瘦狗产品(站点)' AND m.margin_rate_30d < 0.10 THEN '>= 5% AND < 10%'
                                        WHEN r.role_30d = '瘦狗产品(站点)' AND (m.volume_30d / 30.0) > 0 AND (m.volume_30d / 30.0) < 1 THEN '>= 10%'
                                        WHEN r.role_30d = '瘦狗产品(站点)' AND (m.volume_30d / 30.0) > 3 THEN '>= 5%'
                                        WHEN r.role_30d = '瘦狗产品(站点)' THEN '>= 10%'
                                        WHEN r.role_30d = '问题产品(站点)' AND COALESCE((m.volume_30d / 30.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN COALESCE(m.margin_rate_30d,0) < 0.05 THEN '< 5%'
                                        ELSE '>= 5%'
                                    END,
                                    'small_rank',CASE
                                        WHEN COALESCE((m.volume_30d / 30.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN m.small_rank_30d IS NULL OR m.small_rank_30d <= 0 OR m.small_rank_30d >= 99999 THEN 'IS NULL OR <= 0 OR >= 99999'
                                        WHEN m.small_rank_30d <= 50 THEN '<= 50'
                                        WHEN m.small_rank_30d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                        WHEN m.small_rank_30d > 100 THEN '> 100'
                                    END
                                )
                            )
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_30d;
                SET v_record_count = v_record_count + ROW_COUNT();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '90d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v45','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_90d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','90d','days',90),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_90d,4),'daily_sales',ROUND(m.volume_90d / 90.0,4),
                               'sales_amount',ROUND(m.sales_amount_90d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_90d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_90d,4),'small_rank',ROUND(m.small_rank_90d,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'daily_sales',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND COALESCE(m.volume_90d / 90.0,0) <= 0 THEN '<= 0'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 > 3 THEN '> 3'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.volume_90d / 90.0 > 3 THEN '> 3'
                                   WHEN r.role_90d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 3'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND COALESCE(m.margin_rate_90d,0) < 0.05 THEN '< 5%'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 > 3 THEN '>= 15%'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN '>= 25%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND (m.small_rank_90d IS NULL OR m.small_rank_90d <= 0 OR m.small_rank_90d >= 99999) THEN 'IS NULL OR <= 0 OR >= 99999'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 THEN '> 100'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_90d = '明星产品(站点)' AND m.small_rank_90d <= 50 THEN '<= 50'
                               END
                           ),
                            'product_issue',JSON_OBJECT(
                                'rule_version','20260729',
                                'label',CASE
                                    WHEN r.role_90d = '明星产品(站点)' THEN '已达到站点明星产品标准'
                                    WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d <= 50 AND (((m.volume_90d / 90.0) > 3 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.15) OR ((m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.10 AND m.margin_rate_90d < 0.15)) THEN '潜力产品(站点)-低毛利'
                                    WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d <= 50 AND (m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.15 AND m.margin_rate_90d < 0.25 THEN '潜力产品(站点)-日销或毛利待突破'
                                    WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 AND (((m.volume_90d / 90.0) > 3 AND m.margin_rate_90d >= 0.15) OR ((m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.25)) THEN '潜力产品(站点)-排名不足'
                                    WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 AND (((m.volume_90d / 90.0) > 3 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.15) OR ((m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.10 AND m.margin_rate_90d < 0.15)) THEN '潜力产品(站点)-低毛利且排名不足'
                                    WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 AND (m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.15 AND m.margin_rate_90d < 0.25 THEN '潜力产品(站点)-排名及日销或毛利待突破'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d <= 100 AND (m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.10 THEN '瘦狗产品(站点)-低毛利'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d <= 100 AND (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 AND m.margin_rate_90d >= 0.10 THEN '瘦狗产品(站点)-低日销'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d <= 100 AND (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.10 THEN '瘦狗产品(站点)-日销毛利双低'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 AND (((m.volume_90d / 90.0) > 3 AND m.margin_rate_90d >= 0.05) OR ((m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.10)) THEN '瘦狗产品(站点)-排名不足'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 AND (m.volume_90d / 90.0) BETWEEN 1 AND 3 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.10 THEN '瘦狗产品(站点)-低毛利且排名不足'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 AND (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 AND m.margin_rate_90d >= 0.10 THEN '瘦狗产品(站点)-低日销且排名不足'
                                    WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 AND (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 AND m.margin_rate_90d >= 0.05 AND m.margin_rate_90d < 0.10 THEN '瘦狗产品(站点)-日销毛利排名均不足'
                                    WHEN r.role_90d = '问题产品(站点)' AND COALESCE((m.volume_90d / 90.0),0) <= 0 THEN '问题产品(站点)-零动销'
                                    WHEN r.role_90d = '问题产品(站点)' AND (m.volume_90d / 90.0) > 0 AND COALESCE(m.margin_rate_90d,0) < 0.05 AND (m.small_rank_90d IS NULL OR m.small_rank_90d <= 0 OR m.small_rank_90d >= 99999) THEN '问题产品(站点)-低毛利且排名无效'
                                    WHEN r.role_90d = '问题产品(站点)' AND (m.volume_90d / 90.0) > 0 AND COALESCE(m.margin_rate_90d,0) < 0.05 THEN '问题产品(站点)-低毛利'
                                    WHEN r.role_90d = '问题产品(站点)' AND (m.volume_90d / 90.0) > 0 AND COALESCE(m.margin_rate_90d,0) >= 0.05 AND (m.small_rank_90d IS NULL OR m.small_rank_90d <= 0 OR m.small_rank_90d >= 99999) THEN '问题产品(站点)-排名无效'
                                    ELSE '数据异常-无法判断'
                                END,
                                'benchmark_target',CASE r.role_90d
                                    WHEN '明星产品(站点)' THEN '保持站点明星'
                                    WHEN '潜力产品(站点)' THEN '站点明星'
                                    WHEN '瘦狗产品(站点)' THEN '站点潜力'
                                    WHEN '问题产品(站点)' THEN '退出问题产品'
                                    ELSE '恢复数据'
                                END,
                                'metrics_used',JSON_OBJECT(
                                    'daily_sales',ROUND((m.volume_90d / 90.0),4),
                                    'tag_margin_rate',ROUND(100 * m.margin_rate_90d,4),
                                    'small_rank',ROUND(m.small_rank_90d,4)
                                ),
                                'matched_rule',JSON_OBJECT(
                                    'station_sales_role',r.role_90d,
                                    'daily_sales',CASE
                                        WHEN (m.volume_90d / 90.0) > 3 THEN '> 3'
                                        WHEN (m.volume_90d / 90.0) BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                        WHEN (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 THEN '> 0 AND < 1'
                                        WHEN COALESCE((m.volume_90d / 90.0),0) <= 0 THEN '<= 0'
                                    END,
                                    'tag_margin_rate',CASE
                                        WHEN r.role_90d = '明星产品(站点)' AND (m.volume_90d / 90.0) > 3 THEN '>= 15%'
                                        WHEN r.role_90d = '明星产品(站点)' THEN '>= 25%'
                                        WHEN r.role_90d = '潜力产品(站点)' AND (m.volume_90d / 90.0) > 3 AND m.margin_rate_90d < 0.15 THEN '>= 5% AND < 15%'
                                        WHEN r.role_90d = '潜力产品(站点)' AND (m.volume_90d / 90.0) > 3 THEN '>= 15%'
                                        WHEN r.role_90d = '潜力产品(站点)' AND m.margin_rate_90d < 0.15 THEN '>= 10% AND < 15%'
                                        WHEN r.role_90d = '潜力产品(站点)' AND m.margin_rate_90d < 0.25 THEN '>= 15% AND < 25%'
                                        WHEN r.role_90d = '潜力产品(站点)' THEN '>= 25%'
                                        WHEN r.role_90d = '瘦狗产品(站点)' AND m.margin_rate_90d < 0.10 THEN '>= 5% AND < 10%'
                                        WHEN r.role_90d = '瘦狗产品(站点)' AND (m.volume_90d / 90.0) > 0 AND (m.volume_90d / 90.0) < 1 THEN '>= 10%'
                                        WHEN r.role_90d = '瘦狗产品(站点)' AND (m.volume_90d / 90.0) > 3 THEN '>= 5%'
                                        WHEN r.role_90d = '瘦狗产品(站点)' THEN '>= 10%'
                                        WHEN r.role_90d = '问题产品(站点)' AND COALESCE((m.volume_90d / 90.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN COALESCE(m.margin_rate_90d,0) < 0.05 THEN '< 5%'
                                        ELSE '>= 5%'
                                    END,
                                    'small_rank',CASE
                                        WHEN COALESCE((m.volume_90d / 90.0),0) <= 0 THEN 'NOT_USED'
                                        WHEN m.small_rank_90d IS NULL OR m.small_rank_90d <= 0 OR m.small_rank_90d >= 99999 THEN 'IS NULL OR <= 0 OR >= 99999'
                                        WHEN m.small_rank_90d <= 50 THEN '<= 50'
                                        WHEN m.small_rank_90d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                        WHEN m.small_rank_90d > 100 THEN '> 100'
                                    END
                                )
                            )
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_90d;
                SET v_record_count = v_record_count + ROW_COUNT();

                                -- 站点生命周期成熟期不自动回退：按国家类别+国家+店铺+MSKU读取前序成熟期标签。
                SET v_stage = 'tmp_previous_station_lifecycle_mature';
                DROP TEMPORARY TABLE IF EXISTS tmp_previous_station_lifecycle_mature;
                CREATE TEMPORARY TABLE tmp_previous_station_lifecycle_mature AS
                SELECT t.`country_category`,
                       COALESCE(t.`country`, '') AS country,
                       t.`store`,
                       t.`msku`,
                       t.`data_date` AS previous_mature_data_date,
                       COALESCE(
                           STR_TO_DATE(JSON_UNQUOTE(JSON_EXTRACT(t.`evidence_json`, '$.metrics.first_mature_data_date')), '%Y-%m-%d'),
                           t.`data_date`
                       ) AS first_mature_data_date
                FROM `dws_datasync`.`dws_标签表` t
                JOIN `dws_datasync`.`dws_标签详情表` d
                  ON d.`sub_label_id` = t.`label_id`
                WHERE d.`label_name` = '站点生命周期'
                  AND d.`sub_label_name` = '成熟期(站点)'
                  AND t.`data_date` = (
                      SELECT MAX(prev_t.`data_date`)
                      FROM `dws_datasync`.`dws_标签表` prev_t
                      WHERE prev_t.`data_date` < v_data_date
                  );
                ALTER TABLE tmp_previous_station_lifecycle_mature
                    ADD INDEX idx_tmp_previous_station_lifecycle_mature (country_category, country, store, msku);

                -- 衰退期为人工维护定义，自动 SQL 仅写入测款期/新品期/成长期/成熟期。
                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, fr.country_category, fr.country, fr.store, fr.msku,
                       l.sub_label_id,
                       CASE
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30 THEN '30d'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 31 AND 120 THEN '90d'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 121 AND 300 THEN '6m'
                           WHEN pm.first_mature_data_date IS NOT NULL THEN 'long_term'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300
                                AND COALESCE(r.role_7d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_14d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_30d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_90d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)') THEN 'long_term'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300 THEN '6m'
                       END AS label_period,
                       NOW(),
                       JSON_OBJECT(
                           'schema_version','1.0','rule_version','v45','type','station_lifecycle',
                           'window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                           'metrics',JSON_OBJECT(
                               'first_receiving_scope','国家类别+店铺+MSKU',
                               'first_receiving_date',DATE_FORMAT(fr.first_receiving_date,'%Y-%m-%d'),
                               'lifecycle_days',DATEDIFF(v_data_date,fr.first_receiving_date),
                               'first_mature_data_date',DATE_FORMAT(COALESCE(
                                   pm.first_mature_data_date,
                                   CASE WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                              AND COALESCE(r.role_7d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                              AND COALESCE(r.role_14d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                              AND COALESCE(r.role_30d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                              AND COALESCE(r.role_90d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                        THEN v_data_date END
                               ),'%Y-%m-%d'),
                               'previous_mature_data_date',DATE_FORMAT(pm.previous_mature_data_date,'%Y-%m-%d'),
                               'sales_role_7d',r.role_7d,'sales_role_14d',r.role_14d,'sales_role_30d',r.role_30d,'sales_role_90d',r.role_90d
                           ),
                           'matched_rule',JSON_OBJECT(
                               'lifecycle_days',CASE
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 0 AND 30 THEN 'BETWEEN 0 AND 30'
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 31 AND 120 THEN 'BETWEEN 31 AND 120'
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) BETWEEN 121 AND 300 THEN 'BETWEEN 121 AND 300'
                                   ELSE '> 300'
                               END,
                               'maturity_source',CASE
                                   WHEN pm.first_mature_data_date IS NOT NULL THEN 'previous_station_lifecycle_mature'
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                    AND COALESCE(r.role_7d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_14d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_30d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_90d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)') THEN 'current_sales_role_passed'
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300 THEN 'not_mature'
                                   ELSE 'not_applicable'
                               END,
                               'maturity_history_check',CASE WHEN pm.first_mature_data_date IS NOT NULL THEN 'entered_maturity' ELSE 'not_entered_maturity' END,
                               'maturity_sales_role_check',CASE
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300
                                    AND COALESCE(r.role_7d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_14d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_30d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)')
                                    AND COALESCE(r.role_90d,'') NOT IN ('瘦狗产品(站点)','问题产品(站点)') THEN 'passed'
                                   WHEN DATEDIFF(v_data_date,fr.first_receiving_date) > 300 THEN 'not_passed'
                               END
                           )
                       )
                FROM tmp_station_first_receiving fr
                LEFT JOIN tmp_station_sales_roles r
                  ON fr.country = r.country AND fr.store = r.store AND fr.msku = r.msku
                LEFT JOIN tmp_previous_station_lifecycle_mature pm
                  ON fr.country_category = pm.country_category
                 AND COALESCE(fr.country, '') = pm.country
                 AND fr.store = pm.store
                 AND fr.msku = pm.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点生命周期'
                 AND l.sub_label_name = CASE
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30 THEN '测款期(站点)'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 31 AND 120 THEN '新品期(站点)'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 121 AND 300 THEN '成长期(站点)'
                           WHEN pm.first_mature_data_date IS NOT NULL THEN '成熟期(站点)'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300
                                AND COALESCE(r.role_7d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_14d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_30d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)')
                                AND COALESCE(r.role_90d, '') NOT IN ('瘦狗产品(站点)', '问题产品(站点)') THEN '成熟期(站点)'
                           WHEN DATEDIFF(v_data_date, fr.first_receiving_date) > 300 THEN '成长期(站点)'
                       END
                WHERE DATEDIFF(v_data_date, fr.first_receiving_date) >= 0;
                SET v_record_count = v_record_count + ROW_COUNT();

                -- 销售角色产品问题独立标签：复用前面已经按指标计算完成的 product_issue.label，
                -- 只把它映射为 label_id=15/16 的独立标签记录，不重复维护第二套 CASE 规则。
                -- 必须放在同一事务 COMMIT 前，确保基础标签与产品问题标签同时成功或同时回滚。
                SET v_stage = '销售角色产品问题独立标签写入';

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`,
                     `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT sr.`data_date`,
                       sr.`country_category`,
                       sr.`country`,
                       sr.`store`,
                       sr.`msku`,
                       issue_detail.`sub_label_id`,
                       sr.`label_period`,
                       NOW(),
                       JSON_SET(
                           sr.`evidence_json`,
                           '$.type', CASE source_detail.`label_name`
                               WHEN '销售角色' THEN 'sales_role_product_issue'
                               WHEN '站点销售角色' THEN 'station_sales_role_product_issue'
                           END,
                           '$.source_sales_role', JSON_OBJECT(
                               'parent_label_id', source_detail.`label_id`,
                               'parent_label_name', source_detail.`label_name`,
                               'sub_label_id', source_detail.`sub_label_id`,
                               'sub_label_name', source_detail.`sub_label_name`
                           ),
                           '$.product_issue.parent_label_id', issue_detail.`label_id`,
                           '$.product_issue.parent_label_name', issue_detail.`label_name`,
                           '$.product_issue.sub_label_id', issue_detail.`sub_label_id`
                       ) AS `evidence_json`
                FROM `dws_datasync`.`dws_标签表` sr
                JOIN `dws_datasync`.`dws_标签详情表` source_detail
                  ON source_detail.`sub_label_id` = sr.`label_id`
                 AND source_detail.`label_name` IN ('销售角色', '站点销售角色')
                JOIN `dws_datasync`.`dws_标签详情表` issue_detail
                  ON issue_detail.`label_id` = CASE source_detail.`label_name`
                         WHEN '销售角色' THEN 15
                         WHEN '站点销售角色' THEN 16
                     END
                 AND issue_detail.`sub_label_name` = JSON_UNQUOTE(
                         JSON_EXTRACT(sr.`evidence_json`, '$.product_issue.label')
                     )
                 AND issue_detail.`status` = '启用'
                 AND issue_detail.`tagging_method` = 'auto_sql'
                WHERE sr.`data_date` = v_data_date
                  AND sr.`label_period` IN ('7d', '14d', '30d', '90d')
                  AND JSON_EXTRACT(sr.`evidence_json`, '$.product_issue.label') IS NOT NULL;

                SET v_record_count = v_record_count + ROW_COUNT();
                COMMIT;

                UPDATE `etl_datasync`.`etl_execution_log`
                SET `status` = 'success', `end_time` = NOW(), `data_time` = v_data_date, `record_count` = v_record_count
                WHERE `id` = v_log_id;
            ELSE
                UPDATE `etl_datasync`.`etl_execution_log`
                SET `status` = 'success', `end_time` = NOW(), `record_count` = 0
                WHERE `id` = v_log_id;
            END IF;
    END;
END;
