-- ============================================================================
-- 20260915 V47产品表现前一日最大日期严格校验版
--   1. 自动执行时仍以产品表现表MAX(start_date)作为候选业务日期；
--   2. 自动执行(p_data_date IS NULL)要求产品表现表最大业务日期必须等于数据库前一天，
--      前一天没有源数据时直接报错，不再静默回退到更早日期；
--   3. 手工传入日期时保留历史回补能力，但要求该日期在产品表现表中确实存在数据；
--   4. 仅增加日期校验，不改变其他标签规则、统计周期、数据来源和写入逻辑；
--   5. 本文件不重复创建或修改事件，沿用已部署的事件和过程名称。
-- ============================================================================

-- ============================================================================
-- 20260904 V47新增标签23“30天销售角色频次记录”
--   1. 数据更新起算日为2026-09-04，对应首个业务日期为2026-09-03；业务日期早于2026-09-03不生成标签23；
--   2. 国家类别+店铺+MSKU维度读取标签1当天30d销售角色；
--   3. 国家+店铺+MSKU维度读取标签13当天30d站点销售角色；
--   4. 当前角色与前一日同维度30d角色相同则连续出现次数加1，变化或无前值时重置为1；
--   5. 30d表示销售角色计算周期，连续出现次数不限制为最多30；
--   6. 标签表固定写入2301，evidence_json仅保留维度、当前角色、连续次数、起始日期和展示文案；
--   7. 标签23定义已单独插入dws_标签详情表，本脚本只读取启用字典，不重复插入。
-- ============================================================================

-- ============================================================================
-- 20260826 V47运营状态304/306规则调整
--   1. 按国家类别+店铺+MSKU+shipment_id取得每个货件最新状态；任一最新状态为RECEIVING即视为存在接收中货件；
--   2. 供应链数量=FBA在途+本地仓数量+采购计划数量；本地仓含有效库存及质检中，采购计划含采购运输中及采购计划；
--   3. 单位箱规取产品资料cg_box_pcs有效正数，未匹配、NULL或<=0时按50件；
--   4. 304断货中：FBA可售=0、无RECEIVING货件、供应链数量>=单位箱规；
--   5. 306停售：FBA可售=0、无RECEIVING货件、供应链数量<单位箱规；
--   6. 标签详情表中的304/306定义已单独维护，本脚本不重复修改标签详情表。
-- ============================================================================

-- ============================================================================
-- 20260824 V47运营状态新增307“待上架”
--   1. 以tmp_listing_keys当前Listing商品池为计算基准；
--   2. 按国家类别+店铺+MSKU统计历史不同shipment_id数量，并取得最新shipment_status；
--   3. 历史不同货件数=1、最新状态=SHIPPED且首次到货日为空时，命中307待上架；
--   4. 运营状态优先级调整为：待上架 > 断货中 > 停售 > 清仓中 > 返厂品 > 测款扶持 > 正常在售；
--   5. 标签307定义已单独维护，本脚本不对dws_标签详情表执行INSERT、UPDATE或DELETE。
--   6. 标签307使用独立精简evidence_json，仅保留货件数、最新货件状态和首次到货日三项判断证据。
-- ============================================================================

-- ============================================================================
-- 20260819 V47标签16 evidence_json精简版
--   1. 仅调整标签16独立记录的evidence_json，标签13及标签15 JSON保持不变；
--   2. 删除标签16 JSON中的product_issue重复嵌套、重复matched_rule及重复metrics_used；
--   3. 标签16顶层rule_version使用七项策略规则版本，毛利率字段统一命名为margin_rate；
--   4. 保留窗口、标签、来源销售角色、计算指标、命中条件、目标及策略建议。
-- ============================================================================

-- ============================================================================
-- 20260819 V47标签13/16规则调整版（基于20260818 V47销售角色毛利润口径调整版）
--   1. 标签13仅调整1303瘦狗产品(站点)、1304问题产品(站点)；1301/1302原有业务阈值保持不变；
--   2. 标签21断货前销售角色(站点)的历史回溯判定同步标签13最新规则；
--   3. 标签16改为1601~1607七个策略子标签，evidence_json升级为1.3并写入对应strategy_advice；
--   4. 标签17继续复用既有10%订单毛利调价、固定7日销量及广告复核中间数据，不删除相关计算链路；
--   5. 本脚本只读取dws_标签详情表现有启用字典，不对标签详情表执行INSERT、UPDATE或DELETE；
--   6. 存储过程名、事件名、商品维度、统计周期及原始数据来源保持不变；原20260818 SQL文件不覆盖。
-- ============================================================================

-- ============================================================================
-- 20260818 V47销售角色毛利润口径调整版（基于20260814 JSON复用无缓存表版）
--   1. 删除“volume=0时predict_gross_profit强制按0计算”的限制；
--   2. 统计周期内无论volume是否为0，均正常取COALESCE(predict_gross_profit,0)参与毛利润汇总；
--   3. 覆盖标签1销售角色、标签13站点销售角色、标签20断货前销售角色、标签21断货前销售角色(站点)；
--      标签15/16继承标签1/13结果，因此同步使用新毛利润口径；
--   4. 存储过程名、事件名、商品维度、统计周期、角色阈值、排名、广告、断货及JSON结构均保持不变；
--   5. 原20260814 SQL文件不覆盖、不修改。
-- ============================================================================

-- ============================================================================
-- 20260814 V47新增标签20/21断货库存同源S07后报错修复版：修复第二阶段未声明v_next_date
-- 原正式SQL文件保持不变；不修改产品表现、订单明细等任何原始表结构，存储过程及事件名称保持不变。
--
-- 本次修正：
--   1. 修复station period metrics阶段Can't reopen table: 'r'：改为一次读取临时表并通过周期常量表展开7/14/30/90d；
--   2. 标签17问题产品复核使用调价后固定7个自然日：未调价或未满7天不进入完成复核，满7天后读取固定7日销量；
--   3. 标签17运营状态直接复用标签3按国家类别+店铺+MSKU计算的结果，再展开到各国家；
--   4. 测款扶持初始观察期固定为首次收货D1-D7；D8起再判断1702/1703/1704；
--   5. 1702/1703/1704的子标签名称保留对应执行策略，并与dws_标签详情表当前名称一致；策略同时写入evidence_json.strategy_action；
--   6. 修复tmp_perf_scoped在基础标签阶段被提前删除，导致站点10%订单毛利调价后7天指标报表不存在；
--   7. 标签17的10%订单毛利测试改用temporary_APP.lx_sale_adjust_price_queue真实调价成功记录判断；
--      调前价格>10%订单毛利目标价且调后价格<=目标价，才认定为进入10%订单毛利测试；
--      调价完成日期作为测试开始日，固定统计该日及后续6个自然日的站点销量；
--   8. 10%目标价优先取调价当日快照，历史当日快照缺失时取业务日最新快照，并在evidence_json记录匹配方式；
--   9. 标签17测款扶持策略调整：D1-D7仅在最新Listing价格处于5%～15%订单毛利价格区间时打1701；
--      D8起再按照站点问题标签、周期日销及10%定价+acos约5%的复核状态判断1702/1703/1704；
--  10. 性能优化但不改变逻辑：MAX(start_date)和日期条件改为可使用源表索引的写法；
--      基础阶段一次扫描产品表现表后复用为站点90天指标，避免站点阶段再次扫描源表；
--      站点后续仅保留销量窄表，并只对存在10%调价事件的商品汇总固定7天销量；
--  11. 所有标签统一排除：MSKU为NULL、空字符串或全空格，以及以amzn.gr或Amazon开头的数据；前缀判断忽略大小写；
--      基础标签和站点标签均在提交前执行统一安全清理，避免任何写入路径遗漏过滤；
--  12. 标签16、17、18、19、20、21仅读取dws_标签详情表中现有启用字典，不对该表执行INSERT、UPDATE或DELETE；
--  13. 每日事件固定于07:00执行；策略文本、注释及evidence_json输出键统一使用acos；
--      产品表现源表物理字段acoas、定价快照物理字段近30天ACOAS保持不变，仅作为数据来源读取；
--  14. 增加GET_LOCK单实例保护，事件、手工CALL或重复点击重叠时，后发任务立即拒绝，避免并发争抢资源；
--  15. 站点最新排名窗口只携带排名所需窄字段，不再对约170万行的销量、金额、毛利等宽字段一起排序；
--  16. 排名及90天性能临时表在最后一次使用后立即释放，降低站点阶段磁盘临时表峰值；
--  17. 站点启动日志立即记录业务日期；其他标签规则、统计周期、优先级、JSON、返厂策略和近两天保留逻辑不变。
--  18. S15拆为精确调价日快照与最新目标价补充两步，并统一定价快照连接字段排序规则。
--  19. 原S18、S21、S28三表联查均拆为驱动表连接临时表A，再由结果连接临时表B；中间结果建立联合索引。
--  20. 拆分后的第二阶段40条SELECT型语句逐条记录开始、结束、耗时、影响行数和状态；连接中断保留running记录。
--  21. S20移除连接键上的显式COLLATE转换，使调价后7天销量汇总命中五列联合索引，避免百万行临时表全扫描。
--  22. 标签16 strategy_advice 严格采用《站点销售角色-产品问题标签_策略建议.txt》原文。
--  23. 所有站点连接键统一为utf8mb4_0900_ai_ci，连接条件不再执行COLLATE转换，确保联合索引可用。
--  24. 重跑前统一清理标签13/14/15/16/17/18/19，避免站点类及广告类标签重复累积。
--  25. 标签17运营状态直接读取基础阶段已提交的标签3结果，不再依赖tmp_hits会话临时表。
--  26. 20260819版本已将标签16 evidence_json升级为1.3七项策略结构；10%订单毛利测试证据仅供标签17复核使用。
--  27. 新增标签18广告投放效果：产品表现表为商品主表，按国家+店铺+MSKU统计D-2截止近7天，按1801~1809顺序首次命中。
--  28. 新增标签19广告推广管理：产品表现表为商品主表，按五站D-2截止近7天广告花费判断覆盖，并按国家+店铺+MSKU写入。
--  29. 基础标签性能优化：先生成本次Listing MSKU临时键表；产品表现和订单明细各扫描一次，
--      仅将命中本次MSKU的数据写入会话临时表，并在临时表内生成国家类别、标准店铺及联合索引；
--      再通过临时索引删除不属于精确国家类别+店铺+MSKU的记录。全程不对任何原始表执行ALTER或新增索引。
--  30. 标签20/21只处理最终运营状态实际命中304“断货中”、且当前FBA可售库存=0的商品；
--      待上架等更高优先级状态即使底层is_out_of_stock=1，也不进入断货前销售角色计算。
--  31. 前一业务日明确不是断货中、当日首次命中304时，断货日取当日：标签20复制前一日标签1，标签21复制前一日标签13。
--  32. 前一业务日已经断货中且已有同一断货轮次标签20/21时直接复用，只更新当天304库存证据；恢复库存后停止写入。
--  33. 仅当前一业务日状态缺失、或存量断货缓存缺失/周期不完整时回溯有效FBA历史快照：
--      找到最后一个FBA可售>0日期后的第一次有效FBA可售=0日期；缺失快照不按0，历史回溯不重复判断RECEIVING、箱规、在途或本地仓。
--  34. 修复S07成功后、S08开始前同源历史扫描引用第二阶段未声明变量v_next_date的问题；
--      两处时间上限统一改为DATE_ADD(v_data_date, INTERVAL 1 DAY)，业务日期和统计口径不变。
--  35. 第二阶段查询性能优化但不改变计算口径：
--      断货前销售角色历史FBA回溯直接比较seller_sku_adj和country_category，避免索引列CAST导致约659万行全表扫描；
--      产品表现临时表增加国家类别+国家+店铺+MSKU+日期索引，供10%订单毛利调价后固定7天销量精确关联；
--      断货前角色待计算目标直接复用已汇总的缓存周期数，取消重复相关子查询。
-- ============================================================================

-- 第二阶段SELECT耗时诊断日志。使用MyISAM保证主事务回滚或连接中断时，已写入的开始记录仍然保留。
CREATE TABLE IF NOT EXISTS `etl_datasync`.`etl_execution_select_log_v47` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `execution_log_id` INT NOT NULL COMMENT '关联etl_execution_log.id',
    `data_time` DATE NULL COMMENT '本次业务日期',
    `select_no` INT NOT NULL COMMENT '第二阶段SELECT顺序号',
    `select_name` VARCHAR(255) NOT NULL COMMENT 'SELECT用途说明',
    `statement_type` VARCHAR(40) NOT NULL COMMENT 'CREATE_TABLE_AS_SELECT或INSERT_SELECT',
    `source_line` INT NULL COMMENT '本文件中的SELECT起始行（部署前基准行）',
    `sql_start_time` DATETIME(6) NOT NULL,
    `sql_end_time` DATETIME(6) NULL,
    `elapsed_seconds` DECIMAL(18,6) NULL,
    `affected_rows` BIGINT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'running',
    `connection_id` BIGINT NULL,
    `error_message` TEXT NULL,
    `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_execution_select` (`execution_log_id`, `select_no`),
    KEY `idx_status_start` (`status`, `sql_start_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='V47第二阶段每条SELECT开始结束及耗时日志';

-- 标签20/21为“断货发生时冻结”的历史事实。运行开始时先从主标签表当前日/前一日的
-- evidence_json恢复已计算断货轮次；过程内部仅使用临时表，不再创建或依赖永久缓存表。

-- 仅删除并重建同名 V47 过程；旧版本过程保持不变。
DROP PROCEDURE IF EXISTS `dws_datasync`.`sp_dws_标签表_一体化_v47`;

-- V35/V36/V37/V38 未曾部署时才新增字段；字段已存在时不改动 dws_标签表结构。
SET @evidence_json_column_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'dws_datasync'
      AND TABLE_NAME = 'dws_标签表'
      AND COLUMN_NAME = 'evidence_json'
);
SET @evidence_json_alter_sql := IF(
    @evidence_json_column_exists = 0,
    'ALTER TABLE dws_datasync.dws_标签表 ADD COLUMN evidence_json JSON NULL COMMENT ''本次打标实际使用的指标、统计窗口和命中阈值''',
    'SELECT ''evidence_json already exists'' AS message'
);
PREPARE stmt_evidence_json FROM @evidence_json_alter_sql;
EXECUTE stmt_evidence_json;
DEALLOCATE PREPARE stmt_evidence_json;

-- dws_标签详情表中的清仓中标签规则已提前维护，本脚本不再修改标签详情表。

-- V47 成熟期不可回退方案：不新建、不读取 dws_生命周期成熟期历史。
-- 每日读取 dws_标签表中当前业务日期之前最近一个业务日期的成熟期标签，并通过 evidence_json 逐日续传首次成熟日期。

-- 返厂品阶段下钻标签字典已在 dws_datasync.dws_标签详情表中维护，本脚本不再更新或插入标签字典。

-- ============================================================================
-- 标签16、17、18、19、20、21、23字典由dws_标签详情表单独维护。
-- 本脚本只读取当前已启用且tagging_method=auto_sql的字典记录，不执行INSERT、UPDATE或DELETE。
-- ============================================================================

DELIMITER //

CREATE PROCEDURE `dws_datasync`.`sp_dws_标签表_一体化_v47`(IN p_data_date DATE)
BEGIN
    -- 先统一锁定本次业务日期，确保基础标签与站点标签使用同一天，避免两阶段之间源表更新导致日期不一致。
    DECLARE v_run_data_date DATE DEFAULT NULL;
    DECLARE v_locked_max_source_date DATE DEFAULT NULL;
    DECLARE v_source_date_exists INT DEFAULT 0;
    DECLARE v_run_lock_acquired INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        IF v_run_lock_acquired = 1 THEN
            DO RELEASE_LOCK('dws_label_v47_singleton');
            SET v_run_lock_acquired = 0;
        END IF;
        RESIGNAL;
    END;

    SELECT GET_LOCK('dws_label_v47_singleton', 0) INTO v_run_lock_acquired;
    IF COALESCE(v_run_lock_acquired, 0) <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_dws_标签表_一体化_v47已有任务正在执行，本次调用已拒绝；请勿并发运行';
    END IF;

    SET collation_connection = 'utf8mb4_0900_ai_ci';

    -- 整个过程只读取一次最大业务日期；基础标签与站点标签共用锁定日期，避免重复扫描源表。
    SELECT CAST(MAX(`start_date`) AS DATE)
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

    -- 自动事件传NULL时，不允许使用历史最大日期代替当天日期；
    -- 手工传入日期时仍允许回补历史业务日，但必须存在对应源数据。
    IF p_data_date IS NULL
       AND v_locked_max_source_date <> DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '产品表现表最新业务日期不是前一天，禁止执行标签计算；请等待前一天源数据完成更新';
    END IF;

    -- 使用可命中start_date索引的范围条件，严格确认目标业务日存在源数据。
    SELECT EXISTS (
        SELECT 1
        FROM dwd_datasync.lx_statistics_product_performance p
        WHERE p.start_date >= DATE_FORMAT(v_run_data_date, '%Y-%m-%d')
          AND p.start_date < DATE_FORMAT(DATE_ADD(v_run_data_date, INTERVAL 1 DAY), '%Y-%m-%d')
    )
    INTO v_source_date_exists;

    IF COALESCE(v_source_date_exists, 0) = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '指定业务日期在产品表现表中没有源数据，禁止执行标签计算';
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
            DECLARE v_proc_name varchar(255) DEFAULT 'sp_dws_标签表_一体化_v47_基础标签';
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


                -- 标签20/21 JSON复用快照必须在阶段1删除当前日、清理历史日期之前生成。
                -- 正常每日运行读取前一日；同一业务日重跑时优先读取当前日原结果。
                SET v_stage = 'tmp_pre_oos_json_reuse_snapshot';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_json_reuse;
                CREATE TEMPORARY TABLE tmp_pre_oos_json_reuse (
                    dimension_type VARCHAR(30) NOT NULL,
                    country_category VARCHAR(20) NOT NULL,
                    country VARCHAR(100) NOT NULL DEFAULT '',
                    store VARCHAR(100) NOT NULL,
                    msku VARCHAR(255) NOT NULL,
                    oos_start_date DATE NOT NULL,
                    label_period VARCHAR(10) NOT NULL,
                    label_id INT NOT NULL,
                    evidence_json JSON NOT NULL,
                    first_calculated_data_date DATE NOT NULL,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (dimension_type,country_category,country,store,msku,oos_start_date,label_period),
                    KEY idx_pre_oos_json_current (country_category,store,msku,oos_start_date,dimension_type),
                    KEY idx_pre_oos_json_label (label_id,label_period)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                INSERT IGNORE INTO tmp_pre_oos_json_reuse
                    (dimension_type,country_category,country,store,msku,oos_start_date,
                     label_period,label_id,evidence_json,first_calculated_data_date)
                SELECT x.dimension_type,
                       x.country_category,
                       x.country,
                       x.store,
                       x.msku,
                       x.oos_start_date,
                       x.label_period,
                       x.label_id,
                       x.evidence_json,
                       x.first_calculated_data_date
                FROM (
                    SELECT y.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY y.dimension_type,y.country_category,y.country,y.store,y.msku,
                                            y.oos_start_date,y.label_period
                               ORDER BY y.source_data_date DESC,y.source_created_time DESC,y.label_id DESC
                           ) AS rn
                    FROM (
                        SELECT CASE CAST(d.label_name AS CHAR)
                                   WHEN '断货前销售角色' THEN 'country_category'
                                   WHEN '断货前销售角色(站点)' THEN 'country'
                               END AS dimension_type,
                               CAST(t.country_category AS CHAR(20)) AS country_category,
                               COALESCE(CAST(t.country AS CHAR(100)),'') AS country,
                               CAST(t.store AS CHAR(100)) AS store,
                               CAST(t.msku AS CHAR(255)) AS msku,
                               STR_TO_DATE(
                                   JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.oos.oos_start_date')),
                                   '%Y-%m-%d'
                               ) AS oos_start_date,
                               CAST(t.label_period AS CHAR(10)) AS label_period,
                               t.label_id,
                               t.evidence_json,
                               COALESCE(
                                   STR_TO_DATE(
                                       JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.calculation.first_calculated_data_date')),
                                       '%Y-%m-%d'
                                   ),
                                   t.data_date
                               ) AS first_calculated_data_date,
                               t.data_date AS source_data_date,
                               t.created_time AS source_created_time
                        FROM `dws_datasync`.`dws_标签表` t
                        JOIN tmp_active_labels d
                          ON d.sub_label_id = t.label_id
                         AND d.label_name IN ('断货前销售角色','断货前销售角色(站点)')
                        WHERE t.data_date BETWEEN DATE_SUB(v_data_date,INTERVAL 1 DAY) AND v_data_date
                          AND t.label_period IN ('7d','14d','30d','90d')
                          AND t.evidence_json IS NOT NULL
                          AND (
                              (JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.type')) = 'pre_oos_sales_role'
                               AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.rule_version')) = 'v47_pre_oos_same_source_20260826_hybrid')
                              OR
                              (JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.type')) = 'pre_oos_station_sales_role'
                               AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.rule_version')) = 'v47_pre_oos_station_role_20260826_hybrid')
                          )
                          AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,'$.oos.oos_start_date'))
                              REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                    ) y
                    WHERE y.dimension_type IS NOT NULL
                      AND y.oos_start_date IS NOT NULL
                ) x
                WHERE x.rn = 1;

                SET v_stage = 'tmp_listing_latest';
                -- 全量 Listing 最新同步记录：每个 marketplace+seller+seller_sku 仅保留 create_time 最大的一条。
                -- 同时排除退款占位 SKU（amzn.gr 开头）和 Amazon 占位 SKU（Amazon 开头，大小写不敏感）。
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_latest;
                CREATE TEMPORARY TABLE tmp_listing_latest AS
                SELECT CAST(li.`marketplace` AS CHAR(50))  AS marketplace,
                       CAST(li.`seller_name` AS CHAR(50))  AS seller_name,
                       CAST(li.`seller_sku` AS CHAR(255)) AS seller_sku,
                       li.`sid`,
                       li.`create_time`,
                       CAST(li.`status` AS CHAR(50))      AS listing_status
                FROM (
                    SELECT li.`marketplace`,
                           li.`seller_name`,
                           li.`seller_sku`,
                           li.`sid`,
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
                    ADD INDEX idx_tmp_listing_latest (marketplace, seller_name, seller_sku),
                    ADD INDEX idx_tmp_listing_sid_sku (sid, seller_sku);

                SET v_stage = 'tmp_listing_keys';
                -- 以 tmp_listing_latest 为全量维度主表，生成国家类别+店铺+MSKU 主键。
                -- tmp_listing_latest 已只保留每个 marketplace+seller+seller_sku 最新 create_time 记录，并排除 amzn.gr 和 Amazon 开头 SKU。
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_keys;
                CREATE TEMPORARY TABLE tmp_listing_keys AS
                SELECT DISTINCT
                       CAST(CASE
                                WHEN CAST(li.`marketplace` AS CHAR) = '英国' THEN '英国站'
                                WHEN CAST(li.`marketplace` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                ELSE '欧洲站' END AS CHAR(20)) COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(CASE
                                WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) > 0 THEN LEFT(
                                        SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1),
                                        LOCATE('-', SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1)) - 1)
                                ELSE SUBSTRING_INDEX(CAST(li.`seller_name` AS CHAR), ' ', 1) END AS CHAR(100))
                           COLLATE utf8mb4_0900_ai_ci AS store,
                       CAST(li.`seller_sku` AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS msku
                FROM tmp_listing_latest li;
                ALTER TABLE tmp_listing_keys
                    ADD INDEX idx_tmp_listing_keys (country_category, store, MSKU);

                SET v_stage = 'tmp_listing_msku_keys';
                -- 仅保留本次Listing出现的MSKU，供大源表扫描时先做低成本裁剪；避免同一MSKU跨国家/店铺重复放大源记录。
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_msku_keys;
                CREATE TEMPORARY TABLE tmp_listing_msku_keys (
                    MSKU VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
                    PRIMARY KEY (MSKU)
                );
                INSERT INTO tmp_listing_msku_keys (MSKU)
                SELECT DISTINCT CAST(k.MSKU AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci
                FROM tmp_listing_keys k
                WHERE k.MSKU IS NOT NULL
                  AND k.MSKU <> '';

                -- 性能优化：产品表现表约 360 万行且仅有主键索引。以下临时表只保留本次标签涉及的
                -- 国家类别+店铺+MSKU，并一次完成国家/店铺/MSKU/日期标准化；后续断货、创建日期、
                -- 客户体验、站点状态、流量结构均复用本表，标签规则和时间口径不变。
                -- 产品表现明细读取2026年至统计日的全部现有历史。
                -- 返厂事件需要先利用完整历史识别断货起点和返场轮次，再在事件层筛选最近180天；
                -- 其他标签规则仍分别在7/14/30/90/180天窗口内计算，不改变其业务口径。
                SET v_stage = 'tmp_perf_scoped_source_scan';
                DROP TEMPORARY TABLE IF EXISTS tmp_perf_scoped;
                -- 性能优化：先批量装载，再一次性建立索引，避免数百万行写入时逐行维护两棵索引。
                CREATE TEMPORARY TABLE tmp_perf_scoped AS
                SELECT CAST(CASE
                                WHEN CAST(p.`country` AS CHAR) = '英国' THEN '英国站'
                                WHEN CAST(p.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                ELSE '欧洲站' END AS CHAR(20)) COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(p.`country` AS CHAR(100)) AS source_country,
                       CAST(CASE
                                WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) > 0
                                    THEN LEFT(SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1),
                                              LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) - 1)
                                ELSE SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1) END AS CHAR(100))
                           COLLATE utf8mb4_0900_ai_ci AS perf_store,
                       CAST(p.`seller_sku` AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS perf_msku,
                       DATE(p.`start_date`) AS stat_date,
                       p.`product_create_time`,
                       p.`afn_fulfillable_quantity`,
                       p.`volume`,
                       p.`spend`,
                       p.`amount`,
                       p.`avg_star`,
                       p.`predict_gross_profit`,
                       p.`id` AS source_id,
                       p.`create_time` AS source_create_time,
                       p.`acoas`,
                       p.`rank` AS small_rank_raw
                FROM `dwd_datasync`.`lx_statistics_product_performance` p
                         FORCE INDEX (`idx_osp_performance_date_sync`)
                         STRAIGHT_JOIN tmp_listing_msku_keys mk
                                       ON mk.MSKU = p.`seller_sku`
                WHERE p.`start_date` BETWEEN '2026-01-01' AND DATE_FORMAT(v_data_date, '%Y-%m-%d');
                ALTER TABLE tmp_perf_scoped
                    ADD INDEX idx_tmp_perf_scoped_date_key (stat_date, country_category, perf_store, perf_msku),
                    ADD INDEX idx_tmp_perf_scoped_key_date (country_category, perf_store, perf_msku, stat_date);

                SET v_stage = 'tmp_perf_scoped_exact_filter';
                -- MSKU初筛后再用临时联合索引执行精确维度过滤；等价于原国家类别+标准店铺+MSKU关联。
                DELETE ps
                FROM tmp_perf_scoped ps
                LEFT JOIN tmp_listing_keys k
                  ON k.country_category = ps.country_category
                 AND k.store = ps.perf_store
                 AND k.MSKU = ps.perf_msku
                WHERE k.MSKU IS NULL;

                -- 无产品表现历史的Listing无需写入空占位行；下方tmp_perf以Listing键表LEFT JOIN本表，仍会完整保留这些商品。
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
                        SUM(CASE WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(ps.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_7d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(ps.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_14d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(ps.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_30d,
                        SUM(CASE WHEN ps.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(ps.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_90d,
                       CASE
                           WHEN SUM(CASE
                                        WHEN ps.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(ps.`amount`, 0)
                                        ELSE 0 END) > 0 THEN SUM(CASE
                                                                     WHEN ps.stat_date BETWEEN v_7d AND v_data_date
                                                                         THEN COALESCE(ps.`predict_gross_profit`, 0)
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
                                                                         THEN COALESCE(ps.`predict_gross_profit`, 0)
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
                                                                         THEN COALESCE(ps.`predict_gross_profit`, 0)
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
                                                                         THEN COALESCE(ps.`predict_gross_profit`, 0)
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
                ALTER TABLE tmp_perf
                    ADD INDEX idx_tmp_perf_key (country_category, store, MSKU);

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

                -- 运营状态307“待上架”：以当前Listing商品池限定货件范围，避免扫描无关商品。
                -- 历史货件数使用COUNT(DISTINCT shipment_id)，最新状态沿用断货在途流程的状态时间优先级。
                SET v_stage = 'tmp_pending_listing_shipment_scoped';
                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_shipment_scoped;
                CREATE TEMPORARY TABLE tmp_pending_listing_shipment_scoped AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       NULLIF(TRIM(CAST(s.`shipment_id` AS CHAR)), '') AS shipment_id,
                       UPPER(TRIM(CAST(s.`shipment_status` AS CHAR))) AS shipment_status,
                       COALESCE(
                           STR_TO_DATE(LEFT(CAST(s.`gmt_modified` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                           CASE
                               WHEN UPPER(TRIM(CAST(s.`shipment_status` AS CHAR))) = 'WORKING'
                                   THEN STR_TO_DATE(LEFT(CAST(s.`working_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s')
                           END,
                           STR_TO_DATE(LEFT(CAST(s.`gmt_create` AS CHAR), 19), '%Y-%m-%d %H:%i:%s'),
                           STR_TO_DATE(LEFT(CAST(s.`create_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s')
                       ) AS status_effective_time,
                       CASE
                           WHEN STR_TO_DATE(LEFT(CAST(s.`gmt_modified` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL
                               THEN 'gmt_modified'
                           WHEN UPPER(TRIM(CAST(s.`shipment_status` AS CHAR))) = 'WORKING'
                            AND STR_TO_DATE(LEFT(CAST(s.`working_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL
                               THEN 'working_time'
                           WHEN STR_TO_DATE(LEFT(CAST(s.`gmt_create` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL
                               THEN 'gmt_create'
                           WHEN STR_TO_DATE(LEFT(CAST(s.`create_time` AS CHAR), 19), '%Y-%m-%d %H:%i:%s') IS NOT NULL
                               THEN 'create_time'
                       END AS status_time_source,
                       CAST(s.`id` AS UNSIGNED) AS source_id
                FROM tmp_listing_keys k
                JOIN `dwd_datasync`.`lx_fba_shipment` s
                  ON k.country_category = CASE
                                              WHEN CAST(s.`country` AS CHAR) = '英国' THEN '英国站'
                                              WHEN CAST(s.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                              ELSE '欧洲站'
                                          END
                 AND k.store = CASE
                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) > 0
                                       THEN LEFT(
                                           SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1),
                                           LOCATE('-', SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)) - 1
                                       )
                                   ELSE SUBSTRING_INDEX(CAST(s.`seller` AS CHAR), ' ', 1)
                               END
                 AND k.MSKU = CAST(s.`msku` AS CHAR);
                ALTER TABLE tmp_pending_listing_shipment_scoped
                    ADD INDEX idx_pending_listing_shipment_scoped
                        (country_category, store, MSKU, shipment_id);

                SET v_stage = 'tmp_pending_listing_shipment_count';
                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_shipment_count;
                CREATE TEMPORARY TABLE tmp_pending_listing_shipment_count AS
                SELECT country_category,
                       store,
                       MSKU,
                       COUNT(DISTINCT shipment_id) AS historical_shipment_count
                FROM tmp_pending_listing_shipment_scoped
                GROUP BY country_category, store, MSKU;
                ALTER TABLE tmp_pending_listing_shipment_count
                    ADD INDEX idx_pending_listing_shipment_count (country_category, store, MSKU);

                SET v_stage = 'tmp_pending_listing_latest_status';
                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_latest_status;
                CREATE TEMPORARY TABLE tmp_pending_listing_latest_status AS
                SELECT country_category,
                       store,
                       MSKU,
                       shipment_status AS latest_shipment_status,
                       status_effective_time AS latest_shipment_status_time,
                       status_time_source AS latest_shipment_status_time_source
                FROM (
                    SELECT s.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.country_category, s.store, s.MSKU
                               ORDER BY s.status_effective_time DESC, s.source_id DESC
                           ) AS rn
                    FROM tmp_pending_listing_shipment_scoped s
                    WHERE s.shipment_id IS NOT NULL
                      AND s.shipment_status IS NOT NULL
                      AND s.shipment_status <> ''
                ) ranked
                WHERE rn = 1;
                ALTER TABLE tmp_pending_listing_latest_status
                    ADD INDEX idx_pending_listing_latest_status (country_category, store, MSKU);

                -- 304/306接收中货件判断：每个国家类别+店铺+MSKU+shipment_id只取最新一条状态。
                -- 任意一个货件最新状态为RECEIVING，即认为该商品存在接收中FBA货件。
                SET v_stage = 'tmp_op_receiving_shipment';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_receiving_shipment;
                CREATE TEMPORARY TABLE tmp_op_receiving_shipment AS
                SELECT country_category,
                       store,
                       MSKU,
                       COUNT(*) AS latest_shipment_count,
                       MAX(CASE WHEN shipment_status = 'RECEIVING' THEN 1 ELSE 0 END) AS has_receiving_shipment
                FROM (
                    SELECT s.country_category,
                           s.store,
                           s.MSKU,
                           s.shipment_id,
                           s.shipment_status,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.country_category, s.store, s.MSKU, s.shipment_id
                               ORDER BY s.status_effective_time DESC, s.source_id DESC
                           ) AS rn
                    FROM tmp_pending_listing_shipment_scoped s
                    WHERE s.shipment_id IS NOT NULL
                      AND s.shipment_status IS NOT NULL
                      AND s.shipment_status <> ''
                ) ranked
                WHERE rn = 1
                GROUP BY country_category, store, MSKU;
                ALTER TABLE tmp_op_receiving_shipment
                    ADD INDEX idx_tmp_op_receiving_shipment (country_category, store, MSKU);

                -- 新版运营状态不再以 Listing 的“在售/停售”状态作为断货或停售判定条件；
                -- Listing 仍仅作为商品池主表使用。

                -- 性能优化：旧 tmp_fba/tmp_stock 未被任何标签规则、证据JSON或最终写入引用，
                -- 删除这两段死计算，避免额外扫描FBA明细并重复聚合；运营状态仍使用下方同源库存逻辑。

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
                       SUM(COALESCE(f.`stock_up_num`, 0)) AS fba_in_transit,
                       SUM(COALESCE(f.`total`, 0)) AS total_stock
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

                -- 清仓条件统一使用DWD FBA库存明细全表最新数据日期快照，不跟随产品表现表v_data_date：
                -- 条件1：三个非重叠库龄字段合计>0；条件2：DWD FBA可售库存>1且德国/美国Listing存在“不合规%”标签。
                -- 清仓计算排除seller_sku以amzn.gr或Amazon开头的数据（大小写不敏感）。
                -- ETL FBA表仅提供DWD原始仓库/原始MSKU到标准国家类别+店铺+MSKU的维度映射，不提供清仓指标值。
                SET v_stage = 'tmp_clearance_age_snapshot';
                DROP TEMPORARY TABLE IF EXISTS tmp_clearance_age_snapshot;
                CREATE TEMPORARY TABLE tmp_clearance_age_snapshot AS
                SELECT DATE(MAX(d.`create_time`)) AS snapshot_date
                FROM `dwd_datasync`.`lx_storage_fba_warehouse_detail` d;

                SET v_stage = 'tmp_clearance_age_map';
                DROP TEMPORARY TABLE IF EXISTS tmp_clearance_age_map;
                CREATE TEMPORARY TABLE tmp_clearance_age_map AS
                SELECT DISTINCT
                       CAST(e.`name` AS CHAR(100)) AS raw_warehouse_name,
                       CAST(e.`seller_sku` AS CHAR(255)) AS raw_seller_sku,
                       k.country_category,
                       k.store,
                       k.MSKU
                FROM tmp_clearance_age_snapshot sd
                JOIN `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` e
                  ON e.`create_time` >= sd.snapshot_date
                 AND e.`create_time` < DATE_ADD(sd.snapshot_date, INTERVAL 1 DAY)
                JOIN tmp_listing_keys k
                  ON k.country_category = CAST(e.`country_category` AS CHAR)
                 AND k.store = CASE
                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(e.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                       THEN LEFT(SUBSTRING_INDEX(CAST(e.`seller_name_new` AS CHAR), ' ', 1),
                                                 LOCATE('-', SUBSTRING_INDEX(CAST(e.`seller_name_new` AS CHAR), ' ', 1)) - 1)
                                   ELSE SUBSTRING_INDEX(CAST(e.`seller_name_new` AS CHAR), ' ', 1)
                               END
                 AND k.MSKU = CAST(e.`seller_sku_adj` AS CHAR)
                WHERE sd.snapshot_date IS NOT NULL
                  AND e.`seller_sku` IS NOT NULL
                  AND CAST(e.`seller_sku` AS CHAR) <> ''
                  AND LOWER(TRIM(CAST(e.`seller_sku` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND UPPER(TRIM(CAST(e.`seller_sku` AS CHAR))) NOT LIKE 'AMAZON%';
                ALTER TABLE tmp_clearance_age_map
                    ADD INDEX idx_tmp_clearance_age_map_raw (raw_warehouse_name, raw_seller_sku),
                    ADD INDEX idx_tmp_clearance_age_map_dim (country_category, store, MSKU);

                SET v_stage = 'tmp_clearance_age';
                DROP TEMPORARY TABLE IF EXISTS tmp_clearance_age;
                CREATE TEMPORARY TABLE tmp_clearance_age AS
                SELECT m.country_category,
                       m.store,
                       m.MSKU,
                       SUM(COALESCE(d.`afn_fulfillable_quantity`, 0)) AS clearance_fba_available,
                       SUM(COALESCE(d.`total`, 0)) AS clearance_total_stock,
                       SUM(COALESCE(d.`inv_age_271_to_330_days`, 0)) AS inv_age_271_to_330_qty,
                       SUM(COALESCE(d.`inv_age_331_to_365_days`, 0)) AS inv_age_331_to_365_qty,
                       SUM(COALESCE(d.`inv_age_365_plus_days`, 0)) AS inv_age_365_plus_qty,
                       SUM(COALESCE(d.`inv_age_271_to_330_days`, 0)
                         + COALESCE(d.`inv_age_331_to_365_days`, 0)
                         + COALESCE(d.`inv_age_365_plus_days`, 0)) AS inv_age_271_plus_qty
                FROM tmp_clearance_age_snapshot sd
                JOIN `dwd_datasync`.`lx_storage_fba_warehouse_detail` d
                  ON d.`create_time` >= sd.snapshot_date
                 AND d.`create_time` < DATE_ADD(sd.snapshot_date, INTERVAL 1 DAY)
                JOIN tmp_clearance_age_map m
                  ON m.raw_warehouse_name = CAST(d.`name` AS CHAR)
                 AND m.raw_seller_sku = CAST(d.`seller_sku` AS CHAR)
                WHERE sd.snapshot_date IS NOT NULL
                  AND d.`seller_sku` IS NOT NULL
                  AND CAST(d.`seller_sku` AS CHAR) <> ''
                  AND LOWER(TRIM(CAST(d.`seller_sku` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND UPPER(TRIM(CAST(d.`seller_sku` AS CHAR))) NOT LIKE 'AMAZON%'
                GROUP BY m.country_category, m.store, m.MSKU;
                ALTER TABLE tmp_clearance_age
                    ADD INDEX idx_tmp_clearance_age (country_category, store, MSKU);

                -- 清仓条件2：DWD FBA可售库存>1，且德国或美国Listing存在“不合规%”标签。
                -- 同一国家类别下不同国家共享同一份可售库存，不按country重复累计。
                -- 德国映射欧洲站，美国映射北美站；标签关系按sid+MSKU匹配。
                SET v_stage = 'tmp_clearance_noncompliance';
                DROP TEMPORARY TABLE IF EXISTS tmp_clearance_noncompliance;
                CREATE TEMPORARY TABLE tmp_clearance_noncompliance AS
                SELECT CASE WHEN CAST(li.marketplace AS CHAR) IN ('美国', 'US', 'AMAZON.COM')
                            THEN '北美站' ELSE '欧洲站' END AS country_category,
                       CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(li.seller_name AS CHAR), ' ', 1)) > 0
                               THEN LEFT(SUBSTRING_INDEX(CAST(li.seller_name AS CHAR), ' ', 1),
                                         LOCATE('-', SUBSTRING_INDEX(CAST(li.seller_name AS CHAR), ' ', 1)) - 1)
                           ELSE SUBSTRING_INDEX(CAST(li.seller_name AS CHAR), ' ', 1)
                       END AS store,
                       CAST(li.seller_sku AS CHAR(255)) AS MSKU,
                       1 AS has_noncompliance_tag,
                       GROUP_CONCAT(DISTINCT CAST(li.marketplace AS CHAR) ORDER BY CAST(li.marketplace AS CHAR) SEPARATOR ',') AS noncompliance_countries,
                       GROUP_CONCAT(DISTINCT CAST(t.tag_name AS CHAR) ORDER BY CAST(t.tag_name AS CHAR) SEPARATOR ',') AS noncompliance_tags
                FROM tmp_listing_latest li
                JOIN `dwd_datasync`.`lx_sales_listing_relation_tag` t
                  ON t.`sid` = li.`sid`
                 AND CAST(t.`msku` AS CHAR) = CAST(li.`seller_sku` AS CHAR)
                WHERE (CAST(li.marketplace AS CHAR) IN ('德国', '德国站', 'DE', 'GERMANY', 'AMAZON.DE')
                    OR CAST(li.marketplace AS CHAR) IN ('美国', 'US', 'AMAZON.COM'))
                  AND CAST(t.`tag_name` AS CHAR) LIKE '不合规%'
                GROUP BY 1, 2, 3;
                ALTER TABLE tmp_clearance_noncompliance
                    ADD INDEX idx_tmp_clearance_noncompliance (country_category, store, MSKU);

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
                       MAX(COALESCE(r.`sc_quantity_local_valid`, 0)) AS local_valid_quantity,
                       MAX(COALESCE(r.`sc_quantity_local_qc`, 0)) AS local_qc_quantity,
                       MAX(COALESCE(r.`sc_quantity_purchase_shipping`, 0)) AS purchase_shipping_quantity,
                       MAX(COALESCE(r.`sc_quantity_purchase_plan`, 0)) AS purchase_plan_raw_quantity,
                       MAX(COALESCE(r.`sc_quantity_local_valid`, 0))
                       + MAX(COALESCE(r.`sc_quantity_local_qc`, 0)) AS local_warehouse_quantity,
                       MAX(COALESCE(r.`sc_quantity_purchase_shipping`, 0))
                       + MAX(COALESCE(r.`sc_quantity_purchase_plan`, 0)) AS purchase_plan_quantity,
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

                -- 304/306单位箱规：产品资料cg_box_pcs有效正数取同维度最大值，无有效箱规时后续统一按50件。
                SET v_stage = 'tmp_op_box_quantity';
                DROP TEMPORARY TABLE IF EXISTS tmp_op_box_quantity;
                CREATE TEMPORARY TABLE tmp_op_box_quantity AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       MAX(
                           CASE
                               WHEN CAST(p.`cg_box_pcs` AS DECIMAL(18,4)) > 0
                                   THEN CAST(p.`cg_box_pcs` AS DECIMAL(18,4))
                           END
                       ) AS source_box_quantity
                FROM tmp_listing_keys k
                LEFT JOIN `etl_datasync`.`etl_dispose_lx_product_local_product_info` p
                  ON k.country_category = CASE
                                              WHEN NULLIF(TRIM(CAST(p.`country_category` AS CHAR)), '') IS NOT NULL
                                                  THEN CAST(p.`country_category` AS CHAR)
                                              WHEN CAST(p.`country` AS CHAR) = '英国' THEN '英国站'
                                              WHEN CAST(p.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                              ELSE '欧洲站'
                                          END
                 AND k.store = CASE
                                   WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name_new` AS CHAR), ' ', 1)) > 0
                                       THEN LEFT(
                                           SUBSTRING_INDEX(CAST(p.`seller_name_new` AS CHAR), ' ', 1),
                                           LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name_new` AS CHAR), ' ', 1)) - 1
                                       )
                                   ELSE SUBSTRING_INDEX(CAST(p.`seller_name_new` AS CHAR), ' ', 1)
                               END
                 AND k.MSKU = CAST(p.`seller_sku` AS CHAR)
                GROUP BY k.country_category, k.store, k.MSKU;
                ALTER TABLE tmp_op_box_quantity
                    ADD INDEX idx_tmp_op_box_quantity (country_category, store, MSKU);

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

                -- 返厂品/返场事件 V47：先使用2026年至统计日的完整历史识别
                -- “首次库存=0 -> 后续首次库存>5”的返场轮次，再按首次补货日（返场D1）筛选最近180天。
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
                SET v_stage = 'tmp_order_raw_source_scan';
                DROP TEMPORARY TABLE IF EXISTS tmp_order_raw;
                CREATE TEMPORARY TABLE tmp_order_raw (
                    INDEX idx_tmp_order_raw (country_category, store, MSKU, amazon_order_id)
                ) AS
                SELECT CAST(CASE
                                WHEN CAST(o.`country` AS CHAR) = '英国' THEN '英国站'
                                WHEN CAST(o.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                                ELSE '欧洲站' END AS CHAR(20)) COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(CASE
                                WHEN LOCATE('-', SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1)) > 0
                                    THEN LEFT(SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1),
                                              LOCATE('-', SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1)) - 1)
                                ELSE SUBSTRING_INDEX(CAST(o.`seller_name` AS CHAR), ' ', 1) END AS CHAR(100))
                           COLLATE utf8mb4_0900_ai_ci AS store,
                       CAST(o.`seller_sku` AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS MSKU,
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
                FROM `dwd_datasync`.`lx_sales_mws_orders_detail` o
                         STRAIGHT_JOIN tmp_listing_msku_keys mk
                                       ON mk.MSKU = o.`seller_sku`
                WHERE o.`amazon_order_id` IS NOT NULL
                  AND o.`amazon_order_id` <> '';

                SET v_stage = 'tmp_order_raw_exact_filter';
                -- 利用会话临时表联合索引执行精确维度过滤；业务逻辑与原关联完全一致。
                DELETE o
                FROM tmp_order_raw o
                LEFT JOIN tmp_listing_keys k
                  ON k.country_category = o.country_category
                 AND k.store = o.store
                 AND k.MSKU = o.MSKU
                WHERE k.MSKU IS NULL;

                SET v_stage = 'tmp_listing_msku_keys_cleanup';
                DROP TEMPORARY TABLE IF EXISTS tmp_listing_msku_keys;

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
                           WHEN (vol_7d BETWEEN 1 AND 5 AND margin_7d >= 5 AND margin_7d < 10) OR (vol_7d > 0 AND vol_7d < 1 AND margin_7d >= 5) OR (vol_7d > 1 AND margin_7d < 5)
                               THEN '瘦狗产品'
                           WHEN vol_7d = 0 OR (vol_7d > 0 AND vol_7d <= 1 AND margin_7d < 5) THEN '问题产品' END    role_7d,
                       CASE
                           WHEN (vol_14d > 5 AND margin_14d > 15) OR (vol_14d BETWEEN 1 AND 5 AND margin_14d > 25) THEN '明星产品'
                           WHEN (vol_14d > 5 AND margin_14d BETWEEN 5 AND 15) OR
                                (vol_14d BETWEEN 1 AND 5 AND margin_14d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_14d BETWEEN 1 AND 5 AND margin_14d >= 5 AND margin_14d < 10) OR
                                (vol_14d > 0 AND vol_14d < 1 AND margin_14d >= 5) OR (vol_14d > 1 AND margin_14d < 5) THEN '瘦狗产品'
                           WHEN vol_14d = 0 OR (vol_14d > 0 AND vol_14d <= 1 AND margin_14d < 5) THEN '问题产品' END role_14d,
                       CASE
                           WHEN (vol_30d > 5 AND margin_30d > 15) OR (vol_30d BETWEEN 1 AND 5 AND margin_30d > 25) THEN '明星产品'
                           WHEN (vol_30d > 5 AND margin_30d BETWEEN 5 AND 15) OR
                                (vol_30d BETWEEN 1 AND 5 AND margin_30d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_30d BETWEEN 1 AND 5 AND margin_30d >= 5 AND margin_30d < 10) OR
                                (vol_30d > 0 AND vol_30d < 1 AND margin_30d >= 5) OR (vol_30d > 1 AND margin_30d < 5) THEN '瘦狗产品'
                           WHEN vol_30d = 0 OR (vol_30d > 0 AND vol_30d <= 1 AND margin_30d < 5) THEN '问题产品' END role_30d,
                       CASE
                           WHEN (vol_90d > 5 AND margin_90d > 15) OR (vol_90d BETWEEN 1 AND 5 AND margin_90d > 25) THEN '明星产品'
                           WHEN (vol_90d > 5 AND margin_90d BETWEEN 5 AND 15) OR
                                (vol_90d BETWEEN 1 AND 5 AND margin_90d BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (vol_90d BETWEEN 1 AND 5 AND margin_90d >= 5 AND margin_90d < 10) OR
                                (vol_90d > 0 AND vol_90d < 1 AND margin_90d >= 5) OR (vol_90d > 1 AND margin_90d < 5) THEN '瘦狗产品'
                           WHEN vol_90d = 0 OR (vol_90d > 0 AND vol_90d <= 1 AND margin_90d < 5) THEN '问题产品' END role_90d
                FROM tmp_perf;
                ALTER TABLE tmp_sales_role
                    ADD INDEX idx_evidence_sales_role (country_category, store, MSKU);

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

                -- 站点90天指标直接复用基础阶段已经标准化的产品表现结果，避免再次扫描约468万行源表。
                SET v_stage = 'reuse scoped performance for station 90d';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_perf_90d;
                CREATE TEMPORARY TABLE tmp_station_perf_90d AS
                SELECT country_category,
                       source_country AS country,
                       perf_store AS store,
                       perf_msku AS msku,
                       stat_date,
                       source_id,
                       source_create_time,
                       volume,
                       amount,
                       spend,
                       acoas,
                       predict_gross_profit,
                       small_rank_raw
                FROM tmp_perf_scoped
                WHERE stat_date BETWEEN v_90d AND v_data_date
                  AND source_country IS NOT NULL;
                ALTER TABLE tmp_station_perf_90d
                    ADD INDEX idx_tmp_station_perf_90d (country, store, msku, stat_date, source_create_time, source_id);

                -- 性能优化：不再复制2026年至业务日的数百万行每日销量窄表。
                -- S20和S26直接复用已有tmp_perf_scoped，字段、日期条件和统计公式保持不变；
                -- tmp_perf_scoped延迟到S26完成后释放。

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

                -- 运营状态（互斥）：待上架 > 断货中 > 停售 > 清仓中 > 返厂品 > 测款扶持 > 正常在售。
                -- 已进入观察期、运营干预期或持续干预期的MSKU继续计算返厂阶段；如果当前FBA可售为0，
                -- 则运营状态优先按照断货中或停售判断，返厂品阶段下钻标签仍继续保留。
                -- 断货中：FBA可售库存=0、无最新状态为RECEIVING的货件，且供应链数量>=单位箱规。
                -- 停售：FBA可售库存=0、无最新状态为RECEIVING的货件，且供应链数量<单位箱规。
                -- 供应链数量=FBA在途+本地仓数量+采购计划数量；单位箱规无有效值时按50件。
                -- 不再以 Listing 状态、产品表现表是否有数据作为断货/停售判断条件。
                -- 待上架：历史不同货件数=1、最新货件状态=SHIPPED，且首次到货日为空。
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
                       COALESCE(f.total_stock, 0) AS total_stock,
                       COALESCE(ca.clearance_fba_available, 0) AS clearance_fba_available,
                       COALESCE(ca.clearance_total_stock, 0) AS clearance_total_stock,
                       COALESCE(l.local_quantity, 0) AS local_quantity,
                       COALESCE(l.local_warehouse_quantity, 0) AS local_warehouse_quantity,
                       COALESCE(l.purchase_plan_quantity, 0) AS purchase_plan_quantity,
                       COALESCE(f.fba_in_transit, 0)
                           + COALESCE(l.local_warehouse_quantity, 0)
                           + COALESCE(l.purchase_plan_quantity, 0) AS supply_quantity,
                       b.source_box_quantity,
                       COALESCE(b.source_box_quantity, 50) AS unit_box_quantity,
                       CASE WHEN b.source_box_quantity IS NOT NULL THEN 'product_info' ELSE 'default_50' END AS unit_box_quantity_source,
                       COALESCE(rs.latest_shipment_count, 0) AS latest_shipment_count,
                       COALESCE(rs.has_receiving_shipment, 0) AS has_receiving_shipment,
                       COALESCE(ca.inv_age_271_to_330_qty, 0) AS inv_age_271_to_330_qty,
                       COALESCE(ca.inv_age_331_to_365_qty, 0) AS inv_age_331_to_365_qty,
                       COALESCE(ca.inv_age_365_plus_qty, 0) AS inv_age_365_plus_qty,
                       COALESCE(ca.inv_age_271_plus_qty, 0) AS inv_age_271_plus_qty,
                       COALESCE(cn.has_noncompliance_tag, 0) AS has_noncompliance_tag,
                       cn.noncompliance_countries,
                       cn.noncompliance_tags,
                       COALESCE(pc.historical_shipment_count, 0) AS historical_shipment_count,
                       pls.latest_shipment_status,
                       pls.latest_shipment_status_time,
                       pls.latest_shipment_status_time_source,
                       fr.first_receiving_date,
                       CASE
                           WHEN COALESCE(pc.historical_shipment_count, 0) = 1
                            AND pls.latest_shipment_status = 'SHIPPED'
                            AND fr.first_receiving_date IS NULL THEN 1
                           ELSE 0 END AS is_pending_listing,
                       CASE
                           WHEN fr.first_receiving_date IS NOT NULL
                                AND DATEDIFF(v_data_date, fr.first_receiving_date) BETWEEN 0 AND 30
                                AND COALESCE(f.fba_available, 0) > 0 THEN 1
                           ELSE 0 END AS is_test_support,
                       CASE
                           WHEN COALESCE(f.fba_available, 0) = 0
                                 AND COALESCE(rs.has_receiving_shipment, 0) = 0
                                 AND COALESCE(f.fba_in_transit, 0)
                                     + COALESCE(l.local_warehouse_quantity, 0)
                                     + COALESCE(l.purchase_plan_quantity, 0)
                                     >= COALESCE(b.source_box_quantity, 50) THEN 1
                           ELSE 0 END AS is_out_of_stock,
                       CASE
                           WHEN COALESCE(f.fba_available, 0) = 0
                                 AND COALESCE(rs.has_receiving_shipment, 0) = 0
                                 AND COALESCE(f.fba_in_transit, 0)
                                     + COALESCE(l.local_warehouse_quantity, 0)
                                     + COALESCE(l.purchase_plan_quantity, 0)
                                     < COALESCE(b.source_box_quantity, 50) THEN 1
                           ELSE 0 END AS is_stopped,
                       CASE
                           WHEN COALESCE(ca.inv_age_271_plus_qty, 0) > 0
                                OR (COALESCE(ca.clearance_fba_available, 0) > 1 AND COALESCE(cn.has_noncompliance_tag, 0) = 1) THEN 1
                           ELSE 0 END AS is_clearance,
                       CASE
                           WHEN r.return_stage IN ('观察期', '运营干预期', '持续干预期') THEN 1
                           ELSE 0 END AS is_return_event
                FROM tmp_listing_keys k
                         LEFT JOIN tmp_op_fba f
                                     ON k.country_category = f.country_category AND k.store = f.store AND k.MSKU = f.MSKU
                         LEFT JOIN tmp_op_local l
                                      ON k.country_category = l.country_category AND k.store = l.store AND k.MSKU = l.MSKU
                         LEFT JOIN tmp_op_box_quantity b
                                      ON k.country_category = b.country_category AND k.store = b.store AND k.MSKU = b.MSKU
                         LEFT JOIN tmp_op_receiving_shipment rs
                                      ON k.country_category = rs.country_category AND k.store = rs.store AND k.MSKU = rs.MSKU
                         LEFT JOIN tmp_first_receiving fr
                                     ON k.country_category = fr.country_category AND k.store = fr.store AND k.MSKU = fr.MSKU
                         LEFT JOIN tmp_pending_listing_shipment_count pc
                                     ON k.country_category = pc.country_category AND k.store = pc.store AND k.MSKU = pc.MSKU
                         LEFT JOIN tmp_pending_listing_latest_status pls
                                     ON k.country_category = pls.country_category AND k.store = pls.store AND k.MSKU = pls.MSKU
                         LEFT JOIN tmp_clearance_age ca
                                     ON k.country_category = ca.country_category AND k.store = ca.store AND k.MSKU = ca.MSKU
                         LEFT JOIN tmp_clearance_noncompliance cn
                                     ON k.country_category = cn.country_category AND k.store = cn.store AND k.MSKU = cn.MSKU
                         LEFT JOIN tmp_return r
                                     ON k.country_category = r.country_category AND k.store = r.store AND k.MSKU = r.MSKU;

                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_latest_status;
                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_shipment_count;
                DROP TEMPORARY TABLE IF EXISTS tmp_op_receiving_shipment;
                DROP TEMPORARY TABLE IF EXISTS tmp_op_box_quantity;
                DROP TEMPORARY TABLE IF EXISTS tmp_pending_listing_shipment_scoped;

                -- 运营状态必须互斥：每个国家类别+店铺+MSKU仅保留一个状态。
                -- 优先级：待上架 > 断货中 > 停售 > 清仓中 > 返厂品 > 测款扶持 > 正常在售。
                INSERT INTO tmp_hits
                SELECT country_category,
                       NULL AS country,
                       store,
                       MSKU,
                       '运营状态' AS label_name,
                       CASE
                           WHEN is_pending_listing = 1 THEN '待上架'
                           WHEN is_out_of_stock = 1 THEN '断货中'
                           WHEN is_stopped = 1 THEN '停售'
                           WHEN is_clearance = 1 THEN '清仓中'
                           WHEN is_return_event = 1 THEN '返厂品'
                           WHEN is_test_support = 1 THEN '测款扶持'
                           WHEN fba_available > 0 THEN '正常在售'
                       END AS child_label_name,
                       CASE
                           WHEN is_pending_listing = 1 THEN 'current'
                           WHEN is_out_of_stock = 1 THEN 'current'
                           WHEN is_stopped = 1 THEN 'current'
                           WHEN is_clearance = 1 THEN 'current'
                           WHEN is_return_event = 1 THEN 'current'
                           WHEN is_test_support = 1 THEN '30d'
                           WHEN fba_available > 0 THEN 'current'
                       END AS label_period
                FROM tmp_op
                WHERE is_pending_listing = 1
                   OR is_out_of_stock = 1
                   OR is_stopped = 1
                   OR is_clearance = 1
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
                                        'schema_version','1.1','rule_version','v47','type','sales_role',
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
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5 THEN '> 1'
                                                WHEN h.child_label_name IN ('明星产品','潜力产品','瘦狗产品') AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN 'BETWEEN 1 AND 5'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 1 THEN '> 1'
                                                WHEN h.child_label_name = '瘦狗产品' THEN '< 1'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) = 0 THEN '= 0'
                                                WHEN h.child_label_name = '问题产品' THEN '> 0 AND <= 1'
                                            END,
                                            'tag_margin_rate',CASE
                                                WHEN h.child_label_name = '明星产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN '> 15%'
                                                WHEN h.child_label_name = '明星产品' THEN '> 25%'
                                                WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 THEN 'BETWEEN 5% AND 15%'
                                                WHEN h.child_label_name = '潜力产品' THEN 'BETWEEN 10% AND 25%'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5 THEN '< 5%'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 THEN 'BETWEEN 5% AND 10%'
                                                WHEN h.child_label_name = '瘦狗产品' THEN '> 5%'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 1 THEN '< 5%'
                                            END
                                        ),
                                        'product_issue',JSON_OBJECT(
                                            'rule_version','20260729',
                                            'label',CASE
                                                WHEN h.child_label_name = '明星产品' THEN '明星产品-已达标'
                                                WHEN h.child_label_name = '潜力产品' AND (((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) BETWEEN 5 AND 15) OR ((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) BETWEEN 10 AND 15)) THEN '潜力产品-低毛利'
                                                WHEN h.child_label_name = '潜力产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) > 15 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) <= 25 THEN '潜力产品-日销或毛利待突破'
                                                WHEN h.child_label_name = '瘦狗产品' AND (((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) BETWEEN 1 AND 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 10) OR ((CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5)) THEN '瘦狗产品-低毛利'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) < 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 10 THEN '瘦狗产品-低日销'
                                                WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) < 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) >= 5 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 10 THEN '瘦狗产品-日销毛利双低'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 0 THEN '问题产品-零动销'
                                                WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5 THEN '问题产品-低毛利'
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
                                                    WHEN h.child_label_name = '瘦狗产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 1 AND (CASE h.label_period WHEN '7d' THEN p.margin_7d WHEN '14d' THEN p.margin_14d WHEN '30d' THEN p.margin_30d ELSE p.margin_90d END) < 5 THEN '> 1'
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
                                                    WHEN h.child_label_name = '问题产品' AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) > 0 AND (CASE h.label_period WHEN '7d' THEN p.vol_7d WHEN '14d' THEN p.vol_14d WHEN '30d' THEN p.vol_30d ELSE p.vol_90d END) <= 1 THEN '< 5%'
                                                END
                                            )
                                        )
                                    )
                                    WHEN '生命周期' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','lifecycle',
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
                                        'schema_version','1.0','rule_version','v47','type','pricing','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('matched_price_region',pr.price_label),
                                        'matched_rule',JSON_OBJECT('price_region',pr.price_label)
                                    )
                                    WHEN '站点状态' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','site_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('covered_site_count',ss.covered_site_count),
                                        'matched_rule',JSON_OBJECT('covered_site_count',CASE WHEN ss.covered_site_count = 5 THEN '= 5' ELSE '<> 5' END)
                                    )
                                    WHEN '库存水平' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','inventory_level','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('inventory_support_days',ROUND(il.inventory_support_days,4)),
                                        'matched_rule',JSON_OBJECT('inventory_support_days',CASE WHEN il.inventory_support_days < 35 THEN '< 35' WHEN il.inventory_support_days < 90 THEN 'BETWEEN 35 AND < 90' ELSE '>= 90' END)
                                    )
                                    WHEN '流量结构' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','traffic_structure',
                                        'window',JSON_OBJECT('start',DATE_FORMAT(v_30d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','30d','days',30),
                                        'metrics',JSON_OBJECT('sales_amount',ROUND(ts.sales_amount_30d,4),'ad_spend',ROUND(ts.ad_spend_30d,4),'tacos',ROUND(100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0),4)),
                                        'matched_rule',JSON_OBJECT('tacos',CASE WHEN ts.sales_amount_30d <= 0 THEN NULL WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 70 THEN '>= 70%' WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 40 THEN 'BETWEEN 40% AND < 70%' WHEN 100*ts.ad_spend_30d/NULLIF(ts.sales_amount_30d,0) >= 10 THEN 'BETWEEN 10% AND < 40%' ELSE '< 10%' END,'sales_amount',CASE WHEN ts.sales_amount_30d <= 0 THEN '<= 0' END)
                                    )
                                    WHEN '客户体验' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','customer_experience','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('average_rating',ROUND(ce.avg_star,4)),
                                        'matched_rule',JSON_OBJECT('average_rating',CASE WHEN ce.avg_star IS NULL OR ce.avg_star = 0 THEN 'IS NULL OR = 0' WHEN ce.avg_star >= 4.5 THEN '>= 4.50' WHEN ce.avg_star >= 4 THEN 'BETWEEN 4.00 AND < 4.50' WHEN ce.avg_star >= 3.5 THEN 'BETWEEN 3.50 AND < 4.00' ELSE '< 3.50' END)
                                    )
                                    WHEN '退货情况' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','return_rate','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','last_100_orders','orders',rr.order_count),
                                        'metrics',JSON_OBJECT('order_count',rr.order_count,'return_order_count',rr.return_order_count,'sales_volume',rr.sales_volume,'return_sales_volume',rr.return_sales_volume,'return_rate',ROUND(100*rr.return_rate,4)),
                                        'matched_rule',JSON_OBJECT('return_rate',CASE WHEN rr.return_rate < 0.02 THEN '< 2%' WHEN rr.return_rate < 0.05 THEN 'BETWEEN 2% AND < 5%' WHEN rr.return_rate <= 0.20 THEN 'BETWEEN 5% AND 20%' ELSE '> 20%' END)
                                    )
                                    WHEN '运营状态' THEN CASE
                                        WHEN h.child_label_name = '待上架' THEN JSON_OBJECT(
                                            'schema_version','1.0',
                                            'rule_version','v47_operation_status_20260824',
                                            'type','operation_status',
                                            'window',JSON_OBJECT(
                                                'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                                                'period','current'
                                            ),
                                            'metrics',JSON_OBJECT(
                                                'historical_shipment_count',op.historical_shipment_count,
                                                'latest_shipment_status',op.latest_shipment_status,
                                                'first_receiving_date',DATE_FORMAT(op.first_receiving_date,'%Y-%m-%d')
                                            ),
                                            'matched_rule',JSON_OBJECT(
                                                'operation_status','待上架',
                                                'historical_shipment_count','= 1',
                                                'latest_shipment_status','= SHIPPED',
                                                'first_receiving_date','IS NULL'
                                            )
                                        )
                                        WHEN h.child_label_name IN ('断货中','停售') THEN JSON_OBJECT(
                                            'schema_version','1.0',
                                            'rule_version','v47_operation_status_20260826',
                                            'type','operation_status',
                                            'window',JSON_OBJECT(
                                                'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                                                'period','current'
                                            ),
                                            'metrics',JSON_OBJECT(
                                                'fba_available',op.fba_available,
                                                'fba_in_transit',op.fba_in_transit,
                                                'local_warehouse_quantity',op.local_warehouse_quantity,
                                                'purchase_plan_quantity',op.purchase_plan_quantity,
                                                'supply_quantity',op.supply_quantity,
                                                'source_box_quantity',op.source_box_quantity,
                                                'unit_box_quantity',op.unit_box_quantity,
                                                'unit_box_quantity_source',op.unit_box_quantity_source,
                                                'latest_shipment_count',op.latest_shipment_count,
                                                'has_receiving_shipment',op.has_receiving_shipment
                                            ),
                                            'matched_rule',JSON_OBJECT(
                                                'operation_status',h.child_label_name,
                                                'fba_available','= 0',
                                                'has_receiving_shipment','= 0',
                                                'supply_quantity',CASE
                                                    WHEN h.child_label_name = '断货中' THEN '>= unit_box_quantity'
                                                    ELSE '< unit_box_quantity'
                                                END,
                                                'missing_box_quantity_rule','use 50'
                                            )
                                        )
                                        ELSE JSON_OBJECT(
                                            'schema_version','1.0','rule_version','v47_operation_status_20260824','type','operation_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                            'metrics',JSON_OBJECT(
                                                'fba_available',CASE WHEN h.child_label_name = '清仓中' THEN op.clearance_fba_available ELSE op.fba_available END,
                                                'fba_in_transit',op.fba_in_transit,
                                                'total_stock',CASE WHEN h.child_label_name = '清仓中' THEN op.clearance_total_stock ELSE op.total_stock END,
                                                'local_quantity',op.local_quantity,
                                                'inv_age_271_to_330_qty',op.inv_age_271_to_330_qty,
                                                'inv_age_331_to_365_qty',op.inv_age_331_to_365_qty,
                                                'inv_age_365_plus_qty',op.inv_age_365_plus_qty,
                                                'inv_age_271_plus_qty',op.inv_age_271_plus_qty,
                                                'has_noncompliance_tag',op.has_noncompliance_tag,
                                                'noncompliance_countries',op.noncompliance_countries,
                                                'noncompliance_tags',op.noncompliance_tags,
                                                'is_out_of_stock',op.is_out_of_stock,
                                                'is_stopped',op.is_stopped,
                                                'is_clearance',op.is_clearance,
                                                'is_return_event',op.is_return_event,
                                                'is_test_support',op.is_test_support
                                            ),
                                            'matched_rule',JSON_OBJECT(
                                                'operation_status',h.child_label_name,
                                                'fba_available',CASE
                                                    WHEN h.child_label_name IN ('断货中','停售') THEN '= 0'
                                                    WHEN h.child_label_name = '清仓中' AND op.clearance_fba_available > 1 AND op.has_noncompliance_tag = 1 THEN '> 1'
                                                END,
                                                'fba_in_transit',CASE WHEN h.child_label_name = '断货中' THEN '> 0 OR local_quantity > 0' WHEN h.child_label_name = '停售' THEN '= 0' END,
                                                'local_quantity',CASE WHEN h.child_label_name = '停售' THEN '= 0' END,
                                                'clearance_condition',CASE
                                                    WHEN h.child_label_name = '清仓中'
                                                     AND op.inv_age_271_plus_qty > 0
                                                     AND op.clearance_fba_available > 1
                                                     AND op.has_noncompliance_tag = 1 THEN 'inventory_age_271_plus_or_fba_available_and_noncompliance'
                                                    WHEN h.child_label_name = '清仓中' AND op.inv_age_271_plus_qty > 0 THEN 'inventory_age_271_plus'
                                                    WHEN h.child_label_name = '清仓中' THEN 'fba_available_and_noncompliance'
                                                END,
                                                'inv_age_271_plus_qty',CASE WHEN h.child_label_name = '清仓中' AND op.inv_age_271_plus_qty > 0 THEN '> 0' END,
                                                'listing_noncompliance',CASE WHEN h.child_label_name = '清仓中' AND op.clearance_fba_available > 1 AND op.has_noncompliance_tag = 1 THEN 'Germany_or_US_tag_name_like_不合规%' END
                                            )
                                        )
                                    END
                                    WHEN '返厂品阶段下钻' THEN JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','return_stage',
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
                                        'schema_version','1.0','rule_version','v47','type','shipment_status','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','current'),
                                        'metrics',JSON_OBJECT('shipment_status',sh.shipment_status,'status_effective_time',DATE_FORMAT(sh.status_effective_time,'%Y-%m-%d %H:%i:%s'),'status_time_source',sh.status_time_source),
                                        'matched_rule',JSON_OBJECT('shipment_status',sh.shipment_status,'operation_status','断货中')
                                    )
                                    ELSE JSON_OBJECT(
                                        'schema_version','1.0','rule_version','v47','type','unmapped','window',JSON_OBJECT('end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period',h.label_period),
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

    -- 全标签统一排除无效MSKU：NULL、空字符串/全空格、amzn.gr前缀、Amazon前缀（忽略大小写）。
    DELETE FROM `dws_datasync`.`dws_标签表`
    WHERE `data_date` = v_data_date
      AND (
          `msku` IS NULL
          OR TRIM(CAST(`msku` AS CHAR)) = ''
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amzn.gr%'
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amazon%'
      );

    SET v_record_count = GREATEST(v_record_count - ROW_COUNT(), 0);

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
            DECLARE v_ad_window_end DATE DEFAULT NULL;
            DECLARE v_ad_7d_start DATE DEFAULT NULL;
            DECLARE v_proc_name VARCHAR(255) DEFAULT 'sp_dws_标签表_一体化_v47';
            DECLARE v_log_id INT DEFAULT NULL;
            DECLARE v_record_count INT DEFAULT 0;
            DECLARE v_error_msg TEXT;
            DECLARE v_stage VARCHAR(255) DEFAULT 'initialization';
            DECLARE v_select_log_id BIGINT UNSIGNED DEFAULT NULL;
            DECLARE v_select_seq INT DEFAULT 0;
            DECLARE v_select_name VARCHAR(255) DEFAULT NULL;
            DECLARE v_select_affected_rows BIGINT DEFAULT NULL;

            DECLARE EXIT HANDLER FOR SQLEXCEPTION
            BEGIN
                GET DIAGNOSTICS CONDITION 1 v_error_msg = MESSAGE_TEXT;
                ROLLBACK;
                IF v_select_log_id IS NOT NULL THEN
                    UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                    SET `sql_end_time` = NOW(6),
                        `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                        `status` = 'error',
                        `error_message` = v_error_msg
                    WHERE `id` = v_select_log_id;
                    SET v_select_log_id = NULL;
                END IF;
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

            UPDATE `etl_datasync`.`etl_execution_log`
            SET `data_time` = v_data_date
            WHERE `id` = v_log_id;

            IF v_data_date IS NOT NULL THEN
                SET v_7d = DATE_SUB(v_data_date, INTERVAL 6 DAY);
                SET v_14d = DATE_SUB(v_data_date, INTERVAL 13 DAY);
                SET v_30d = DATE_SUB(v_data_date, INTERVAL 29 DAY);
                SET v_90d = DATE_SUB(v_data_date, INTERVAL 89 DAY);

                -- 标签详情表必须已部署并启用ID=13~21及23对应字典；本过程只读取，不重复插入标签18、19、20、21、23。
                SET v_stage = 'active station labels';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_active_labels;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S01 读取启用的站点标签字典';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2111,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_active_labels AS
                SELECT DISTINCT CAST(`label_name` AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS label_name,
                                CAST(`sub_label_name` AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS sub_label_name,
                                `sub_label_id`
                FROM `dws_datasync`.`dws_标签详情表`
                WHERE `label_id` IN (13,14,15,16,17,18,19,20,21,23)
                  AND CAST(`status` AS CHAR) = '启用'
                  AND CAST(`tagging_method` AS CHAR) = 'auto_sql'
                  AND `sub_label_name` IS NOT NULL;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;

                -- 商品池：Listing 最新同步记录（marketplace + seller_name + seller_sku），
                -- 以国家 + 清洗店铺 + MSKU 作为站点标签粒度；排除退款及 Amazon 占位 SKU。
                SET v_stage = 'station listing keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_listing_keys;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S02 生成站点Listing商品池';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2124,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_listing_keys
                    ADD INDEX idx_station_listing_keys (country, store, msku);

                -- 指标统计粒度：国家 + 店铺 + MSKU。销量和毛利仍按7/14/30/90天原周期累计。
                -- 小类排名不再取周期平均值，分别取各窗口内最新统计日期的rank；最新日期无效时不向前回退。
                SET v_stage = 'station performance 90d reused';
                -- tmp_station_perf_90d 已在基础阶段由同一批产品表现明细生成，此处直接复用，不再二次扫描源表。

                SET v_stage = 'station latest daily rank';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_daily;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S03 生成站点每日最新小类排名';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2162,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_rank_daily AS
                SELECT country_category, country, store, msku, stat_date, small_rank_raw
                FROM (
                    SELECT p.country_category,
                           p.country,
                           p.store,
                           p.msku,
                           p.stat_date,
                           p.small_rank_raw,
                           ROW_NUMBER() OVER (
                               PARTITION BY p.country, p.store, p.msku, p.stat_date
                               ORDER BY p.source_create_time DESC, p.source_id DESC
                           ) AS rn
                    FROM tmp_station_perf_90d p
                ) x
                WHERE x.rn = 1;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_rank_daily
                    ADD INDEX idx_tmp_station_rank_daily (country, store, msku, stat_date);

                SET v_stage = 'station latest rank dates';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_dates;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S04 计算各周期最新排名日期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2183,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_rank_dates AS
                SELECT k.country_category,
                       k.country,
                       k.store,
                       k.msku,
                       MAX(CASE WHEN r.stat_date BETWEEN v_7d AND v_data_date THEN r.stat_date END) AS latest_rank_date_7d,
                       MAX(CASE WHEN r.stat_date BETWEEN v_14d AND v_data_date THEN r.stat_date END) AS latest_rank_date_14d,
                       MAX(CASE WHEN r.stat_date BETWEEN v_30d AND v_data_date THEN r.stat_date END) AS latest_rank_date_30d,
                       MAX(CASE WHEN r.stat_date BETWEEN v_90d AND v_data_date THEN r.stat_date END) AS latest_rank_date_90d
                FROM tmp_station_listing_keys k
                LEFT JOIN tmp_station_rank_daily r
                  ON k.country = r.country AND k.store = r.store AND k.msku = r.msku
                GROUP BY k.country_category, k.country, k.store, k.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_rank_dates
                    ADD INDEX idx_tmp_station_rank_dates (country, store, msku);

                SET v_stage = 'station latest rank metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S05 提取各周期最新小类排名';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2201,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_rank_metrics AS
                SELECT d.country_category,
                       d.country,
                       d.store,
                       d.msku,
                       MAX(CASE WHEN r.stat_date = d.latest_rank_date_7d THEN r.small_rank_raw END) AS small_rank_7d,
                       MAX(CASE WHEN r.stat_date = d.latest_rank_date_14d THEN r.small_rank_raw END) AS small_rank_14d,
                       MAX(CASE WHEN r.stat_date = d.latest_rank_date_30d THEN r.small_rank_raw END) AS small_rank_30d,
                       MAX(CASE WHEN r.stat_date = d.latest_rank_date_90d THEN r.small_rank_raw END) AS small_rank_90d,
                       d.latest_rank_date_7d,
                       d.latest_rank_date_14d,
                       d.latest_rank_date_30d,
                       d.latest_rank_date_90d
                FROM tmp_station_rank_dates d
                LEFT JOIN tmp_station_rank_daily r
                  ON d.country = r.country AND d.store = r.store AND d.msku = r.msku
                 AND r.stat_date IN (
                     d.latest_rank_date_7d,
                     d.latest_rank_date_14d,
                     d.latest_rank_date_30d,
                     d.latest_rank_date_90d
                 )
                GROUP BY d.country_category, d.country, d.store, d.msku,
                         d.latest_rank_date_7d, d.latest_rank_date_14d,
                         d.latest_rank_date_30d, d.latest_rank_date_90d;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_rank_metrics
                    ADD INDEX idx_tmp_station_rank_metrics (country, store, msku);

                SET v_stage = 'station sales metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_sales_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S06 汇总站点7/14/30/90天销售指标';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2231,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_sales_metrics AS
                SELECT k.country_category,
                       k.country,
                       k.store,
                       k.msku,
                       SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_7d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_14d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_30d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`volume`, 0) ELSE 0 END) AS volume_90d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_7d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_14d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_30d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) AS sales_amount_90d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_7d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_14d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_30d,
                       SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END) AS tag_gross_profit_90d,
                       CASE WHEN SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_7d,
                       CASE WHEN SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_14d,
                       CASE WHEN SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_30d,
                       CASE WHEN SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END) > 0
                            THEN SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`predict_gross_profit`, 0) ELSE 0 END)
                                 / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`, 0) ELSE 0 END), 0)
                            ELSE NULL END AS margin_rate_90d,
                       CASE
                           WHEN SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END) > 0
                               THEN SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`spend`,0) ELSE 0 END)
                                    / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END),0)
                           ELSE AVG(CASE WHEN p.stat_date BETWEEN v_7d AND v_data_date THEN p.`acoas` END)
                       END AS acoas_rate_7d,
                       CASE
                           WHEN SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END) > 0
                               THEN SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`spend`,0) ELSE 0 END)
                                    / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END),0)
                           ELSE AVG(CASE WHEN p.stat_date BETWEEN v_14d AND v_data_date THEN p.`acoas` END)
                       END AS acoas_rate_14d,
                       CASE
                           WHEN SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END) > 0
                               THEN SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`spend`,0) ELSE 0 END)
                                    / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END),0)
                           ELSE AVG(CASE WHEN p.stat_date BETWEEN v_30d AND v_data_date THEN p.`acoas` END)
                       END AS acoas_rate_30d,
                       CASE
                           WHEN SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END) > 0
                               THEN SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`spend`,0) ELSE 0 END)
                                    / NULLIF(SUM(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN COALESCE(p.`amount`,0) ELSE 0 END),0)
                           ELSE AVG(CASE WHEN p.stat_date BETWEEN v_90d AND v_data_date THEN p.`acoas` END)
                       END AS acoas_rate_90d,
                       MAX(sr.small_rank_7d) AS small_rank_7d,
                       MAX(sr.small_rank_14d) AS small_rank_14d,
                       MAX(sr.small_rank_30d) AS small_rank_30d,
                       MAX(sr.small_rank_90d) AS small_rank_90d,
                       MAX(sr.latest_rank_date_7d) AS latest_rank_date_7d,
                       MAX(sr.latest_rank_date_14d) AS latest_rank_date_14d,
                       MAX(sr.latest_rank_date_30d) AS latest_rank_date_30d,
                       MAX(sr.latest_rank_date_90d) AS latest_rank_date_90d
                FROM tmp_station_listing_keys k
                LEFT JOIN tmp_station_perf_90d p
                  ON k.country_category = p.country_category
                 AND k.country = p.country
                 AND k.store = p.store
                 AND k.msku = p.msku
                 AND p.stat_date BETWEEN v_90d AND v_data_date
                LEFT JOIN tmp_station_rank_metrics sr
                  ON k.country = sr.country AND k.store = sr.store AND k.msku = sr.msku
                GROUP BY k.country_category, k.country, k.store, k.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_sales_metrics
                    ADD INDEX idx_station_sales_metrics (country, store, msku);

                SET v_stage = 'station rank temp cleanup';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_metrics;
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_dates;
                DROP TEMPORARY TABLE IF EXISTS tmp_station_rank_daily;
                DROP TEMPORARY TABLE IF EXISTS tmp_station_perf_90d;

                -- 规则：问题产品优先；基于日销和结算毛利率得到基础角色；小类排名 rank 执行封顶/降级。
                -- rank=99999 为无效排名，直接归问题产品。
                SET v_stage = 'station role classification';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_sales_roles;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S07 判定站点销售角色';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2319,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_sales_roles AS
                SELECT country_category, country, store, msku,
                       CASE
                           WHEN volume_7d / 7.0 = 0 THEN '问题产品(站点)'
                           WHEN volume_7d / 7.0 > 0 AND volume_7d / 7.0 <= 1 AND margin_rate_7d < 0.05 THEN '问题产品(站点)'
                           WHEN volume_7d / 7.0 > 0 AND volume_7d / 7.0 <= 1 AND margin_rate_7d >= 0.05
                            AND (small_rank_7d IS NULL OR small_rank_7d = 0 OR small_rank_7d = 99999) THEN '问题产品(站点)'
                           WHEN small_rank_7d BETWEEN 51 AND 100 AND ((volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_7d BETWEEN 1 AND 50 AND ((volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.25)) THEN '明星产品(站点)'
                           WHEN small_rank_7d BETWEEN 1 AND 100 AND ((volume_7d / 7.0 > 3 AND margin_rate_7d >= 0.05 AND margin_rate_7d < 0.15) OR (volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.10 AND margin_rate_7d < 0.25)) THEN '潜力产品(站点)'
                           WHEN volume_7d / 7.0 > 1 AND margin_rate_7d < 0.05 THEN '瘦狗产品(站点)'
                           WHEN volume_7d / 7.0 > 1 AND margin_rate_7d >= 0.05
                            AND (small_rank_7d IS NULL OR small_rank_7d = 0 OR small_rank_7d = 99999) THEN '瘦狗产品(站点)'
                           WHEN ((volume_7d / 7.0 BETWEEN 1 AND 3 AND margin_rate_7d >= 0.05 AND margin_rate_7d < 0.10) OR (volume_7d / 7.0 > 0 AND volume_7d / 7.0 < 1 AND margin_rate_7d >= 0.05)) AND small_rank_7d BETWEEN 1 AND 100 THEN '瘦狗产品(站点)'
                           WHEN volume_7d / 7.0 > 0 AND margin_rate_7d >= 0.05 AND small_rank_7d > 100 AND small_rank_7d <> 99999 THEN '瘦狗产品(站点)'
                       END AS role_7d,
                       CASE
                           WHEN volume_14d / 14.0 = 0 THEN '问题产品(站点)'
                           WHEN volume_14d / 14.0 > 0 AND volume_14d / 14.0 <= 1 AND margin_rate_14d < 0.05 THEN '问题产品(站点)'
                           WHEN volume_14d / 14.0 > 0 AND volume_14d / 14.0 <= 1 AND margin_rate_14d >= 0.05
                            AND (small_rank_14d IS NULL OR small_rank_14d = 0 OR small_rank_14d = 99999) THEN '问题产品(站点)'
                           WHEN small_rank_14d BETWEEN 51 AND 100 AND ((volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_14d BETWEEN 1 AND 50 AND ((volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.25)) THEN '明星产品(站点)'
                           WHEN small_rank_14d BETWEEN 1 AND 100 AND ((volume_14d / 14.0 > 3 AND margin_rate_14d >= 0.05 AND margin_rate_14d < 0.15) OR (volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.10 AND margin_rate_14d < 0.25)) THEN '潜力产品(站点)'
                           WHEN volume_14d / 14.0 > 1 AND margin_rate_14d < 0.05 THEN '瘦狗产品(站点)'
                           WHEN volume_14d / 14.0 > 1 AND margin_rate_14d >= 0.05
                            AND (small_rank_14d IS NULL OR small_rank_14d = 0 OR small_rank_14d = 99999) THEN '瘦狗产品(站点)'
                           WHEN ((volume_14d / 14.0 BETWEEN 1 AND 3 AND margin_rate_14d >= 0.05 AND margin_rate_14d < 0.10) OR (volume_14d / 14.0 > 0 AND volume_14d / 14.0 < 1 AND margin_rate_14d >= 0.05)) AND small_rank_14d BETWEEN 1 AND 100 THEN '瘦狗产品(站点)'
                           WHEN volume_14d / 14.0 > 0 AND margin_rate_14d >= 0.05 AND small_rank_14d > 100 AND small_rank_14d <> 99999 THEN '瘦狗产品(站点)'
                       END AS role_14d,
                       CASE
                           WHEN volume_30d / 30.0 = 0 THEN '问题产品(站点)'
                           WHEN volume_30d / 30.0 > 0 AND volume_30d / 30.0 <= 1 AND margin_rate_30d < 0.05 THEN '问题产品(站点)'
                           WHEN volume_30d / 30.0 > 0 AND volume_30d / 30.0 <= 1 AND margin_rate_30d >= 0.05
                            AND (small_rank_30d IS NULL OR small_rank_30d = 0 OR small_rank_30d = 99999) THEN '问题产品(站点)'
                           WHEN small_rank_30d BETWEEN 51 AND 100 AND ((volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_30d BETWEEN 1 AND 50 AND ((volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.25)) THEN '明星产品(站点)'
                           WHEN small_rank_30d BETWEEN 1 AND 100 AND ((volume_30d / 30.0 > 3 AND margin_rate_30d >= 0.05 AND margin_rate_30d < 0.15) OR (volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.10 AND margin_rate_30d < 0.25)) THEN '潜力产品(站点)'
                           WHEN volume_30d / 30.0 > 1 AND margin_rate_30d < 0.05 THEN '瘦狗产品(站点)'
                           WHEN volume_30d / 30.0 > 1 AND margin_rate_30d >= 0.05
                            AND (small_rank_30d IS NULL OR small_rank_30d = 0 OR small_rank_30d = 99999) THEN '瘦狗产品(站点)'
                           WHEN ((volume_30d / 30.0 BETWEEN 1 AND 3 AND margin_rate_30d >= 0.05 AND margin_rate_30d < 0.10) OR (volume_30d / 30.0 > 0 AND volume_30d / 30.0 < 1 AND margin_rate_30d >= 0.05)) AND small_rank_30d BETWEEN 1 AND 100 THEN '瘦狗产品(站点)'
                           WHEN volume_30d / 30.0 > 0 AND margin_rate_30d >= 0.05 AND small_rank_30d > 100 AND small_rank_30d <> 99999 THEN '瘦狗产品(站点)'
                       END AS role_30d,
                       CASE
                           WHEN volume_90d / 90.0 = 0 THEN '问题产品(站点)'
                           WHEN volume_90d / 90.0 > 0 AND volume_90d / 90.0 <= 1 AND margin_rate_90d < 0.05 THEN '问题产品(站点)'
                           WHEN volume_90d / 90.0 > 0 AND volume_90d / 90.0 <= 1 AND margin_rate_90d >= 0.05
                            AND (small_rank_90d IS NULL OR small_rank_90d = 0 OR small_rank_90d = 99999) THEN '问题产品(站点)'
                           WHEN small_rank_90d BETWEEN 51 AND 100 AND ((volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.25)) THEN '潜力产品(站点)'
                           WHEN small_rank_90d BETWEEN 1 AND 50 AND ((volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.25)) THEN '明星产品(站点)'
                           WHEN small_rank_90d BETWEEN 1 AND 100 AND ((volume_90d / 90.0 > 3 AND margin_rate_90d >= 0.05 AND margin_rate_90d < 0.15) OR (volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.10 AND margin_rate_90d < 0.25)) THEN '潜力产品(站点)'
                           WHEN volume_90d / 90.0 > 1 AND margin_rate_90d < 0.05 THEN '瘦狗产品(站点)'
                           WHEN volume_90d / 90.0 > 1 AND margin_rate_90d >= 0.05
                            AND (small_rank_90d IS NULL OR small_rank_90d = 0 OR small_rank_90d = 99999) THEN '瘦狗产品(站点)'
                           WHEN ((volume_90d / 90.0 BETWEEN 1 AND 3 AND margin_rate_90d >= 0.05 AND margin_rate_90d < 0.10) OR (volume_90d / 90.0 > 0 AND volume_90d / 90.0 < 1 AND margin_rate_90d >= 0.05)) AND small_rank_90d BETWEEN 1 AND 100 THEN '瘦狗产品(站点)'
                           WHEN volume_90d / 90.0 > 0 AND margin_rate_90d >= 0.05 AND small_rank_90d > 100 AND small_rank_90d <> 99999 THEN '瘦狗产品(站点)'
                       END AS role_90d
                FROM tmp_station_sales_metrics;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_sales_roles
                    ADD INDEX idx_station_sales_roles (country, store, msku);

                -- 标签20/21只处理最终运营状态实际命中304“断货中”、且当前FBA可售库存=0的维度。
                -- 缓存缺失时统一回溯实际FBA归零日；同一轮断货后续每日从JSON复用，恢复库存后停止写入。
                SET v_stage = 'pre oos period constants';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_periods;
                CREATE TEMPORARY TABLE tmp_pre_oos_periods (
                    label_period VARCHAR(10) NOT NULL,
                    days INT NOT NULL,
                    PRIMARY KEY (label_period)
                );
                INSERT INTO tmp_pre_oos_periods (label_period, days)
                VALUES ('7d',7),('14d',14),('30d',30),('90d',90);

                -- 前一业务日运营状态用于区分：
                -- 1) 前一日明确不是断货中、当日首次命中304：断货日取当日，复制前一日标签1/13；
                -- 2) 前一日已经断货中：优先复用同一断货轮次的标签20/21；
                -- 3) 前一日状态缺失：无法确认首次断货日，才回溯有效FBA历史快照。
                SET v_stage = 'pre oos previous operation status';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_prev_operation_status;
                CREATE TEMPORARY TABLE tmp_pre_oos_prev_operation_status AS
                SELECT t.country_category,
                       t.store,
                       t.msku,
                       MAX(CAST(d.sub_label_name AS CHAR(100))) AS previous_operation_status
                FROM `dws_datasync`.`dws_标签表` t
                JOIN `dws_datasync`.`dws_标签详情表` d
                  ON d.sub_label_id = t.label_id
                 AND CAST(d.label_name AS CHAR) = '运营状态'
                WHERE t.data_date = DATE_SUB(v_data_date, INTERVAL 1 DAY)
                  AND t.country IS NULL
                GROUP BY t.country_category,t.store,t.msku;
                ALTER TABLE tmp_pre_oos_prev_operation_status
                    ADD INDEX idx_pre_oos_prev_operation_status (country_category,store,msku);

                SET v_stage = 'pre oos current category status';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_current_category_status;
                CREATE TEMPORARY TABLE tmp_pre_oos_current_category_status AS
                SELECT o.country_category,
                       o.store,
                       o.MSKU,
                       o.fba_available AS current_fba_available,
                       o.fba_in_transit AS current_fba_in_transit,
                       o.local_quantity AS current_local_quantity,
                       p.previous_operation_status,
                       CASE WHEN p.previous_operation_status IS NOT NULL
                                  AND p.previous_operation_status <> '断货中'
                            THEN 1 ELSE 0 END AS is_new_oos
                FROM tmp_op o
                JOIN tmp_hits h
                  ON h.`国家类别` = o.country_category
                 AND h.`国家` IS NULL
                 AND h.`店铺` = o.store
                 AND h.`MSKU` = o.MSKU
                 AND h.label_name = '运营状态'
                 AND h.child_label_name = '断货中'
                LEFT JOIN tmp_pre_oos_prev_operation_status p
                  ON p.country_category = o.country_category
                 AND p.store = o.store
                 AND p.msku = o.MSKU
                WHERE COALESCE(o.fba_available,0) = 0;
                ALTER TABLE tmp_pre_oos_current_category_status
                    ADD INDEX idx_pre_oos_current_category_status (country_category,store,MSKU,is_new_oos);

                SET v_stage = 'pre oos current station status';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_current_station_status;
                CREATE TEMPORARY TABLE tmp_pre_oos_current_station_status AS
                SELECT DISTINCT k.country_category,
                                k.country,
                                k.store,
                                k.msku,
                                s.current_fba_available,
                                s.current_fba_in_transit,
                                s.current_local_quantity,
                                s.previous_operation_status,
                                s.is_new_oos
                FROM tmp_pre_oos_current_category_status s
                JOIN tmp_station_listing_keys k
                  ON k.country_category = s.country_category
                 AND k.store = s.store
                 AND k.msku = s.MSKU;
                ALTER TABLE tmp_pre_oos_current_station_status
                    ADD INDEX idx_pre_oos_current_station_status (country,store,msku,is_new_oos),
                    ADD INDEX idx_pre_oos_current_station_category (country_category,store,msku);

                -- 持续断货且当前日/前一日JSON中已有本轮结果时，直接沿用JSON中的断货日，不再扫描历史。
                SET v_stage = 'pre oos latest cached cycle';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_cycle_cache;
                CREATE TEMPORARY TABLE tmp_pre_oos_cycle_cache AS
                SELECT s.country_category,
                       s.store,
                       s.MSKU,
                       MAX(c.oos_start_date) AS cached_oos_start_date
                FROM tmp_pre_oos_current_category_status s
                LEFT JOIN tmp_pre_oos_json_reuse c
                  ON c.country_category = s.country_category
                 AND c.store = s.store
                 AND c.msku = s.MSKU
                GROUP BY s.country_category,s.store,s.MSKU;
                ALTER TABLE tmp_pre_oos_cycle_cache
                    ADD INDEX idx_pre_oos_cycle_cache (country_category,store,MSKU,cached_oos_start_date);

                SET v_stage = 'pre oos category cache counts';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_cache_counts;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_cache_counts AS
                SELECT s.country_category,
                       s.store,
                       s.MSKU,
                       x.cached_oos_start_date,
                       COUNT(DISTINCT c.label_period) AS cached_period_count
                FROM tmp_pre_oos_current_category_status s
                LEFT JOIN tmp_pre_oos_cycle_cache x
                  ON x.country_category = s.country_category
                 AND x.store = s.store
                 AND x.MSKU = s.MSKU
                LEFT JOIN tmp_pre_oos_json_reuse c
                  ON c.dimension_type = 'country_category'
                 AND c.country_category = s.country_category
                 AND c.country = ''
                 AND c.store = s.store
                 AND c.msku = s.MSKU
                 AND c.oos_start_date = x.cached_oos_start_date
                GROUP BY s.country_category,s.store,s.MSKU,x.cached_oos_start_date;
                ALTER TABLE tmp_pre_oos_category_cache_counts
                    ADD INDEX idx_pre_oos_category_cache_counts (country_category,store,MSKU,cached_oos_start_date);

                SET v_stage = 'pre oos station cache counts';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_cache_counts;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_cache_counts AS
                SELECT s.country_category,
                       s.country,
                       s.store,
                       s.msku,
                       x.cached_oos_start_date,
                       COUNT(DISTINCT c.label_period) AS cached_period_count
                FROM tmp_pre_oos_current_station_status s
                LEFT JOIN tmp_pre_oos_cycle_cache x
                  ON x.country_category = s.country_category
                 AND x.store = s.store
                 AND x.MSKU = s.msku
                LEFT JOIN tmp_pre_oos_json_reuse c
                  ON c.dimension_type = 'country'
                 AND c.country_category = s.country_category
                 AND c.country = s.country
                 AND c.store = s.store
                 AND c.msku = s.msku
                 AND c.oos_start_date = x.cached_oos_start_date
                GROUP BY s.country_category,s.country,s.store,s.msku,x.cached_oos_start_date;
                ALTER TABLE tmp_pre_oos_station_cache_counts
                    ADD INDEX idx_pre_oos_station_cache_counts (country,store,msku,cached_oos_start_date),
                    ADD INDEX idx_pre_oos_station_cache_category (country_category,store,msku,cached_period_count);

                -- 只有非新发生304且JSON缓存缺失/周期不完整的商品才回溯有效FBA历史；新发生304复制前一日标签1/13。
                SET v_stage = 'pre oos history candidate keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_candidates;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_candidates AS
                SELECT DISTINCT s.country_category,s.store,s.MSKU
                FROM tmp_pre_oos_current_category_status s
                LEFT JOIN tmp_pre_oos_cycle_cache x
                  ON x.country_category = s.country_category
                 AND x.store = s.store
                 AND x.MSKU = s.MSKU
                LEFT JOIN tmp_pre_oos_category_cache_counts cc
                  ON cc.country_category = s.country_category
                 AND cc.store = s.store
                 AND cc.MSKU = s.MSKU
                WHERE s.is_new_oos = 0
                  AND (
                      x.cached_oos_start_date IS NULL
                      OR COALESCE(cc.cached_period_count,0) < 4
                      OR EXISTS (
                          SELECT 1
                          FROM tmp_pre_oos_station_cache_counts sc
                          WHERE sc.country_category = s.country_category
                            AND sc.store = s.store
                            AND sc.msku = s.MSKU
                            AND COALESCE(sc.cached_period_count,0) < 4
                      )
                  );
                ALTER TABLE tmp_pre_oos_history_candidates
                    ADD PRIMARY KEY (country_category,store,MSKU);

                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_candidate_msku;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_candidate_msku AS
                SELECT DISTINCT MSKU
                FROM tmp_pre_oos_history_candidates;
                ALTER TABLE tmp_pre_oos_history_candidate_msku
                    ADD PRIMARY KEY (MSKU);

                -- 存量断货的一次性产品表现历史扫描：只用于计算断货前销量、销售额、毛利和小类排名，
                -- 不再使用产品表现表的afn_fulfillable_quantity判断断货日。
                SET v_stage = 'pre oos historical performance scan';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_scoped;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_scoped AS
                SELECT CAST(CASE
                                WHEN CAST(p.country AS CHAR) = '英国' THEN '英国站'
                                WHEN CAST(p.country AS CHAR) IN ('美国','加拿大','巴西','墨西哥') THEN '北美站'
                                ELSE '欧洲站' END AS CHAR(20)) COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(p.country AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS source_country,
                       CAST(CASE
                                WHEN LOCATE('-',SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)) > 0
                                    THEN LEFT(SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1),
                                              LOCATE('-',SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)) - 1)
                                ELSE SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)
                            END AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS perf_store,
                       CAST(p.seller_sku AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS perf_msku,
                       DATE(p.start_date) AS stat_date,
                       p.afn_fulfillable_quantity,
                       p.volume,
                       p.amount,
                       p.predict_gross_profit,
                       p.rank AS small_rank_raw,
                       p.id AS source_id,
                       p.create_time AS source_create_time
                FROM `dwd_datasync`.`lx_statistics_product_performance` p
                WHERE 1 = 0;
                ALTER TABLE tmp_pre_oos_history_scoped
                    ADD INDEX idx_pre_oos_history_key_date (country_category,perf_store,perf_msku,stat_date),
                    ADD INDEX idx_pre_oos_history_station_date (source_country,perf_store,perf_msku,stat_date);

                IF EXISTS (SELECT 1 FROM tmp_pre_oos_history_candidate_msku LIMIT 1) THEN
                    INSERT INTO tmp_pre_oos_history_scoped
                    SELECT CAST(CASE
                                    WHEN CAST(p.country AS CHAR) = '英国' THEN '英国站'
                                    WHEN CAST(p.country AS CHAR) IN ('美国','加拿大','巴西','墨西哥') THEN '北美站'
                                    ELSE '欧洲站' END AS CHAR(20)) COLLATE utf8mb4_0900_ai_ci,
                           CAST(p.country AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci,
                           CAST(CASE
                                    WHEN LOCATE('-',SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)) > 0
                                        THEN LEFT(SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1),
                                                  LOCATE('-',SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)) - 1)
                                    ELSE SUBSTRING_INDEX(CAST(p.seller_name AS CHAR),' ',1)
                                END AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci,
                           CAST(p.seller_sku AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci,
                           DATE(p.start_date),
                           p.afn_fulfillable_quantity,
                           p.volume,
                           p.amount,
                           p.predict_gross_profit,
                           p.rank,
                           p.id,
                           p.create_time
                    FROM `dwd_datasync`.`lx_statistics_product_performance` p
                    FORCE INDEX (`idx_osp_performance_date_sync`)
                    STRAIGHT_JOIN tmp_pre_oos_history_candidate_msku mk
                      ON mk.MSKU = p.seller_sku
                    WHERE p.start_date < DATE_FORMAT(DATE_ADD(v_data_date,INTERVAL 1 DAY),'%Y-%m-%d');

                    DELETE h
                    FROM tmp_pre_oos_history_scoped h
                    LEFT JOIN tmp_pre_oos_history_candidates k
                      ON k.country_category = h.country_category
                     AND k.store = h.perf_store
                     AND k.MSKU = h.perf_msku
                    WHERE k.MSKU IS NULL;
                END IF;

                -- 实际断货日只按有效FBA库存快照回溯：FBA明细按每天最后同步时点汇总。
                -- 只有新版本JSON缓存缺失/周期不完整时扫描历史FBA；没有FBA快照的日期不生成记录、也不补0。
                SET v_stage = 'pre oos historical inventory empty tables';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_fba_latest_key;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_fba_latest_key AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       CAST(NULL AS DATE) AS stat_date,
                       CAST(NULL AS DATETIME(6)) AS max_create_time
                FROM tmp_pre_oos_history_candidates k
                WHERE 1 = 0;

                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_fba_daily;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_fba_daily AS
                SELECT k.country_category,
                       k.store,
                       k.MSKU,
                       CAST(NULL AS DATE) AS stat_date,
                       CAST(NULL AS DECIMAL(65,10)) AS site_fba_available,
                       CAST(NULL AS DECIMAL(65,10)) AS fba_in_transit
                FROM tmp_pre_oos_history_candidates k
                WHERE 1 = 0;

                IF EXISTS (SELECT 1 FROM tmp_pre_oos_history_candidates LIMIT 1) THEN
                    SET v_stage = 'pre oos historical fba latest key';
                    INSERT INTO tmp_pre_oos_history_fba_latest_key
                    SELECT k.country_category,
                           k.store,
                           k.MSKU,
                           DATE(f.create_time) AS stat_date,
                           MAX(f.create_time) AS max_create_time
                    FROM tmp_pre_oos_history_candidates k
                    STRAIGHT_JOIN `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` f FORCE INDEX (`id1`)
                      ON f.seller_sku_adj = k.MSKU
                     AND f.country_category = k.country_category
                     AND k.store = CASE
                                       WHEN LOCATE('-',SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)) > 0
                                           THEN LEFT(SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1),
                                                     LOCATE('-',SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)) - 1)
                                       ELSE SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)
                                   END
                    WHERE f.create_time < DATE_ADD(v_data_date, INTERVAL 1 DAY)
                    GROUP BY k.country_category,k.store,k.MSKU,DATE(f.create_time);
                    ALTER TABLE tmp_pre_oos_history_fba_latest_key
                        ADD INDEX idx_pre_oos_history_fba_latest_key
                            (country_category,store,MSKU,stat_date,max_create_time);

                    SET v_stage = 'pre oos historical fba daily';
                    INSERT INTO tmp_pre_oos_history_fba_daily
                    SELECT x.country_category,
                           x.store,
                           x.MSKU,
                           x.stat_date,
                           SUM(COALESCE(f.afn_fulfillable_quantity,0)) AS site_fba_available,
                           SUM(COALESCE(f.stock_up_num,0)) AS fba_in_transit
                    FROM tmp_pre_oos_history_fba_latest_key x
                    JOIN `etl_datasync`.`etl_dispose_lx_storage_fba_warehouse_detail` f FORCE INDEX (`id1`)
                      ON f.seller_sku_adj = x.MSKU
                     AND f.country_category = x.country_category
                     AND f.create_time = x.max_create_time
                     AND x.store = CASE
                                       WHEN LOCATE('-',SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)) > 0
                                           THEN LEFT(SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1),
                                                     LOCATE('-',SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)) - 1)
                                       ELSE SUBSTRING_INDEX(CAST(f.seller_name_new AS CHAR),' ',1)
                                   END
                    GROUP BY x.country_category,x.store,x.MSKU,x.stat_date;
                    ALTER TABLE tmp_pre_oos_history_fba_daily
                        ADD INDEX idx_pre_oos_history_fba_daily (country_category,store,MSKU,stat_date);

                END IF;

                -- 只保留真实存在的FBA日快照；不再将本地仓日期并入，也不将缺失FBA快照自动补0。
                SET v_stage = 'pre oos historical valid fba daily';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_daily;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_daily AS
                SELECT f.country_category,
                       f.store,
                       f.MSKU,
                       f.stat_date,
                       f.site_fba_available
                FROM tmp_pre_oos_history_fba_daily f;
                ALTER TABLE tmp_pre_oos_history_daily
                    ADD INDEX idx_pre_oos_history_daily
                        (country_category,store,MSKU,stat_date,site_fba_available);

                SET v_stage = 'pre oos historical last positive fba';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_last_positive;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_last_positive AS
                SELECT country_category,
                       store,
                       MSKU,
                       MAX(CASE WHEN site_fba_available > 0 THEN stat_date END) AS last_positive_date
                FROM tmp_pre_oos_history_daily
                GROUP BY country_category,store,MSKU;
                ALTER TABLE tmp_pre_oos_history_last_positive
                    ADD INDEX idx_pre_oos_history_last_positive (country_category,store,MSKU,last_positive_date);

                SET v_stage = 'pre oos historical actual start';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_starts;
                CREATE TEMPORARY TABLE tmp_pre_oos_history_starts AS
                SELECT q.country_category,
                       q.store,
                       q.MSKU,
                       q.history_start_date,
                       q.previous_positive_date,
                       q.first_fba_zero_date AS oos_start_date,
                       CASE
                           WHEN q.first_fba_zero_date IS NOT NULL AND q.previous_positive_date IS NOT NULL
                               THEN 'first_fba_zero_after_last_positive'
                           WHEN q.first_fba_zero_date IS NOT NULL
                               THEN 'earliest_observed_fba_zero'
                           ELSE NULL
                       END AS oos_start_accuracy
                FROM (
                    SELECT k.country_category,
                           k.store,
                           k.MSKU,
                           MIN(d.stat_date) AS history_start_date,
                           g.last_positive_date AS previous_positive_date,
                           MIN(CASE
                                   WHEN d.site_fba_available = 0
                                    AND d.stat_date > COALESCE(g.last_positive_date,DATE('1000-01-01'))
                                       THEN d.stat_date
                               END) AS first_fba_zero_date
                    FROM tmp_pre_oos_history_candidates k
                    LEFT JOIN tmp_pre_oos_history_daily d
                      ON d.country_category = k.country_category
                     AND d.store = k.store
                     AND d.MSKU = k.MSKU
                    LEFT JOIN tmp_pre_oos_history_last_positive g
                      ON g.country_category = k.country_category
                     AND g.store = k.store
                     AND g.MSKU = k.MSKU
                    GROUP BY k.country_category,k.store,k.MSKU,g.last_positive_date
                ) q;
                ALTER TABLE tmp_pre_oos_history_starts
                    ADD INDEX idx_pre_oos_history_starts (country_category,store,MSKU,oos_start_date);

                SET v_stage = 'pre oos current category targets';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_targets;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_targets AS
                SELECT s.country_category,
                       s.store,
                       s.MSKU,
                       CASE
                           WHEN s.is_new_oos = 1 THEN v_data_date
                           ELSE COALESCE(x.cached_oos_start_date,h.oos_start_date)
                       END AS oos_start_date,
                       s.current_fba_available,
                       s.current_fba_in_transit,
                       s.current_local_quantity,
                       s.previous_operation_status,
                       s.is_new_oos,
                       CASE
                           WHEN s.is_new_oos = 1 THEN 'daily_status_transition'
                           WHEN x.cached_oos_start_date IS NOT NULL THEN 'json_reused_oos_cycle'
                           ELSE h.oos_start_accuracy
                       END AS oos_start_method,
                       h.history_start_date,
                       h.previous_positive_date
                FROM tmp_pre_oos_current_category_status s
                LEFT JOIN tmp_pre_oos_cycle_cache x
                  ON x.country_category = s.country_category
                 AND x.store = s.store
                 AND x.MSKU = s.MSKU
                LEFT JOIN tmp_pre_oos_history_starts h
                  ON h.country_category = s.country_category
                 AND h.store = s.store
                 AND h.MSKU = s.MSKU
                WHERE CASE
                          WHEN s.is_new_oos = 1 THEN v_data_date
                          ELSE COALESCE(x.cached_oos_start_date,h.oos_start_date)
                      END IS NOT NULL;
                ALTER TABLE tmp_pre_oos_category_targets
                    ADD INDEX idx_pre_oos_category_targets (country_category, store, MSKU, oos_start_date);

                SET v_stage = 'pre oos new category targets';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_new;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_new AS
                SELECT t.*
                FROM tmp_pre_oos_category_targets t
                LEFT JOIN tmp_pre_oos_category_cache_counts c
                  ON c.country_category = t.country_category
                 AND c.store = t.store
                 AND c.MSKU = t.MSKU
                 AND c.cached_oos_start_date = t.oos_start_date
                WHERE t.is_new_oos = 0
                  AND COALESCE(c.cached_period_count,0) < 4;
                ALTER TABLE tmp_pre_oos_category_new
                    ADD INDEX idx_pre_oos_category_new (country_category, store, MSKU, oos_start_date);

                SET v_stage = 'pre oos current station targets';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_targets;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_targets AS
                SELECT DISTINCT s.country_category,
                                s.country,
                                s.store,
                                s.msku,
                                t.oos_start_date,
                                t.current_fba_available,
                                t.current_fba_in_transit,
                                t.current_local_quantity,
                                t.previous_operation_status,
                                t.is_new_oos,
                                t.oos_start_method,
                                t.history_start_date,
                                t.previous_positive_date
                FROM tmp_pre_oos_category_targets t
                JOIN tmp_pre_oos_current_station_status s
                  ON s.country_category = t.country_category
                 AND s.store = t.store
                 AND s.msku = t.MSKU;
                ALTER TABLE tmp_pre_oos_station_targets
                    ADD INDEX idx_pre_oos_station_targets (country, store, msku, oos_start_date);

                SET v_stage = 'pre oos new station targets';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_new;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_new AS
                SELECT t.*
                FROM tmp_pre_oos_station_targets t
                LEFT JOIN tmp_pre_oos_station_cache_counts c
                  ON c.country_category = t.country_category
                 AND c.country = t.country
                 AND c.store = t.store
                 AND c.msku = t.msku
                 AND c.cached_oos_start_date = t.oos_start_date
                WHERE t.is_new_oos = 0
                  AND COALESCE(c.cached_period_count,0) < 4;
                ALTER TABLE tmp_pre_oos_station_new
                    ADD INDEX idx_pre_oos_station_new (country, store, msku, oos_start_date);

                -- 标签20：国家类别+店铺+MSKU，按断货日前各周期计算，规则与标签1一致。
                SET v_stage = 'pre oos category period metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_period_metrics;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_period_metrics AS
                SELECT t.country_category,
                       t.store,
                       t.MSKU,
                       t.oos_start_date,
                       t.current_fba_available,
                       t.current_fba_in_transit,
                       t.current_local_quantity,
                       t.oos_start_method,
                       t.history_start_date,
                       t.previous_positive_date,
                       w.label_period,
                       w.days,
                       DATE_SUB(t.oos_start_date, INTERVAL w.days DAY) AS window_start,
                       DATE_SUB(t.oos_start_date, INTERVAL 1 DAY) AS window_end,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.volume,0) ELSE 0 END) AS period_sales_qty,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.amount,0) ELSE 0 END) AS sales_amount,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.predict_gross_profit, 0)
                                ELSE 0 END) AS tag_gross_profit
                FROM tmp_pre_oos_category_new t
                CROSS JOIN tmp_pre_oos_periods w
                LEFT JOIN tmp_pre_oos_history_scoped p
                  ON p.country_category = t.country_category
                 AND p.perf_store = t.store
                 AND p.perf_msku = t.MSKU
                 AND p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL 90 DAY)
                                     AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                GROUP BY t.country_category, t.store, t.MSKU, t.oos_start_date,
                         t.current_fba_available,t.current_fba_in_transit,t.current_local_quantity,
                         t.oos_start_method,t.history_start_date,t.previous_positive_date,
                         w.label_period, w.days;

                SET v_stage = 'pre oos category roles';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_roles;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_roles AS
                SELECT x.*,
                       CASE
                           WHEN (x.daily_sales > 5 AND x.margin_rate > 15)
                             OR (x.daily_sales BETWEEN 1 AND 5 AND x.margin_rate > 25) THEN '明星产品'
                           WHEN (x.daily_sales > 5 AND x.margin_rate BETWEEN 5 AND 15)
                             OR (x.daily_sales BETWEEN 1 AND 5 AND x.margin_rate BETWEEN 10 AND 25) THEN '潜力产品'
                           WHEN (x.daily_sales BETWEEN 1 AND 5 AND x.margin_rate >= 5 AND x.margin_rate < 10)
                             OR (x.daily_sales > 0 AND x.daily_sales < 1 AND x.margin_rate >= 5)
                             OR (x.daily_sales > 1 AND x.margin_rate < 5) THEN '瘦狗产品'
                           WHEN x.daily_sales = 0 OR (x.daily_sales > 0 AND x.daily_sales <= 1 AND x.margin_rate < 5) THEN '问题产品'
                       END AS sales_role
                FROM (
                    SELECT m.*,
                           m.period_sales_qty / m.days AS daily_sales,
                           CASE WHEN m.sales_amount > 0
                                THEN m.tag_gross_profit / m.sales_amount * 100
                                ELSE 0 END AS margin_rate
                    FROM tmp_pre_oos_category_period_metrics m
                ) x;

                SET v_stage = 'pre oos category cache pending';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_pending;
                CREATE TEMPORARY TABLE tmp_pre_oos_category_pending AS
                SELECT 'country_category' AS dimension_type,
                       r.country_category,
                       '' AS country,
                       r.store,
                       r.MSKU AS msku,
                       r.oos_start_date,
                       r.label_period,
                       COALESCE(l.sub_label_id,0) AS label_id,
                       JSON_OBJECT(
                           'schema_version','1.1',
                           'rule_version','v47_pre_oos_same_source_20260826_hybrid',
                           'type','pre_oos_sales_role',
                           'dimension','country_category+store+msku',
                           'oos',JSON_OBJECT(
                               'oos_start_date',DATE_FORMAT(r.oos_start_date,'%Y-%m-%d'),
                               'snapshot_end_date',DATE_FORMAT(r.window_end,'%Y-%m-%d'),
                               'current_operation_status','断货中',
                               'inventory_source_fba','etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail',
                               'inventory_source_local','etl_datasync.etl_dispose_lx_replenishment_suggest_restocking',
                               'current_fba_available',r.current_fba_available,
                               'current_fba_in_transit',r.current_fba_in_transit,
                               'current_local_quantity',r.current_local_quantity,
                               'oos_start_method',r.oos_start_method,
                               'history_start_date',DATE_FORMAT(r.history_start_date,'%Y-%m-%d'),
                               'previous_positive_date',DATE_FORMAT(r.previous_positive_date,'%Y-%m-%d'),
                               'matched_rule','当前已命中304断货中；历史断货日起点仅按有效FBA快照可售库存=0回溯'
                           ),
                           'window',JSON_OBJECT(
                               'start',DATE_FORMAT(r.window_start,'%Y-%m-%d'),
                               'end',DATE_FORMAT(r.window_end,'%Y-%m-%d'),
                               'period',r.label_period,
                               'days',r.days
                           ),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(r.period_sales_qty,4),
                               'daily_sales',ROUND(r.daily_sales,4),
                               'sales_amount',ROUND(r.sales_amount,4),
                               'tag_gross_profit',ROUND(r.tag_gross_profit,4),
                               'tag_margin_rate',ROUND(r.margin_rate,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.sales_role,
                               'daily_sales',CASE
                                   WHEN r.sales_role IN ('明星产品','潜力产品') AND r.daily_sales > 5 THEN '> 5'
                                   WHEN r.sales_role = '瘦狗产品' AND r.daily_sales > 1 AND r.margin_rate < 5 THEN '> 1'
                                   WHEN r.sales_role IN ('明星产品','潜力产品','瘦狗产品') AND r.daily_sales BETWEEN 1 AND 5 THEN 'BETWEEN 1 AND 5'
                                   WHEN r.sales_role = '瘦狗产品' AND r.daily_sales > 1 THEN '> 1'
                                   WHEN r.sales_role = '瘦狗产品' THEN '< 1'
                                   WHEN r.sales_role = '问题产品' AND r.daily_sales = 0 THEN '= 0'
                                   WHEN r.sales_role = '问题产品' THEN '> 0 AND <= 1'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.sales_role = '明星产品' AND r.daily_sales > 5 THEN '> 15%'
                                   WHEN r.sales_role = '明星产品' THEN '> 25%'
                                   WHEN r.sales_role = '潜力产品' AND r.daily_sales > 5 THEN 'BETWEEN 5% AND 15%'
                                   WHEN r.sales_role = '潜力产品' THEN 'BETWEEN 10% AND 25%'
                                   WHEN r.sales_role = '瘦狗产品' AND r.daily_sales > 1 AND r.margin_rate < 5 THEN '< 5%'
                                   WHEN r.sales_role = '瘦狗产品' AND r.daily_sales >= 1 THEN 'BETWEEN 5% AND 10%'
                                   WHEN r.sales_role = '瘦狗产品' THEN '> 5%'
                                   WHEN r.sales_role = '问题产品' AND r.daily_sales > 0 AND r.daily_sales <= 1 THEN '< 5%'
                               END
                           ),
                           'calculation',JSON_OBJECT(
                               'mode','historical_backtrack',
                               'status',CASE WHEN r.sales_role IS NULL THEN 'calculated_no_matching_role' ELSE 'matched' END,
                               'first_calculated_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d')
                           )
                       ) AS evidence_json,
                       v_data_date AS first_calculated_data_date
                FROM tmp_pre_oos_category_roles r
                LEFT JOIN tmp_station_active_labels l
                  ON l.label_name = '断货前销售角色'
                 AND l.sub_label_name = CASE r.sales_role
                     WHEN '明星产品' THEN '断货前-明星产品'
                     WHEN '潜力产品' THEN '断货前-潜力产品'
                     WHEN '瘦狗产品' THEN '断货前-瘦狗产品'
                     WHEN '问题产品' THEN '断货前-问题产品'
                 END;


                -- 新发生304：断货日取当日，直接冻结前一业务日标签1的同周期销售角色。
                SET v_stage = 'pre oos category transition role copy';
                INSERT INTO tmp_pre_oos_category_pending
                    (dimension_type,country_category,country,store,msku,oos_start_date,
                     label_period,label_id,evidence_json,first_calculated_data_date)
                SELECT DISTINCT
                       'country_category',
                       t.country_category,
                       '',
                       t.store,
                       t.MSKU,
                       t.oos_start_date,
                       sr.label_period,
                       l.sub_label_id,
                       JSON_OBJECT(
                           'schema_version','1.1',
                           'rule_version','v47_pre_oos_same_source_20260826_hybrid',
                           'type','pre_oos_sales_role',
                           'dimension','country_category+store+msku',
                           'oos',JSON_OBJECT(
                               'oos_start_date',DATE_FORMAT(t.oos_start_date,'%Y-%m-%d'),
                               'snapshot_end_date',DATE_FORMAT(DATE_SUB(v_data_date,INTERVAL 1 DAY),'%Y-%m-%d'),
                               'current_status_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                               'current_operation_status','断货中',
                               'inventory_source_fba','etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail',
                               'inventory_source_local','etl_datasync.etl_dispose_lx_replenishment_suggest_restocking',
                               'current_fba_available',t.current_fba_available,
                               'current_fba_in_transit',t.current_fba_in_transit,
                               'current_local_quantity',t.current_local_quantity,
                               'oos_start_method','daily_status_transition',
                               'matched_rule','前一业务日运营状态明确不是断货中，当日最终命中304断货中且FBA可售库存=0'
                           ),
                           'window',JSON_EXTRACT(sr.evidence_json,'$.window'),
                           'metrics',JSON_EXTRACT(sr.evidence_json,'$.metrics'),
                           'matched_rule',JSON_EXTRACT(sr.evidence_json,'$.matched_rule'),
                           'source_sales_role',JSON_OBJECT(
                               'data_date',DATE_FORMAT(sr.data_date,'%Y-%m-%d'),
                               'label_period',sr.label_period,
                               'sub_label_id',sr.label_id,
                               'sub_label_name',CAST(sd.sub_label_name AS CHAR)
                           ),
                           'calculation',JSON_OBJECT(
                               'mode','copy_previous_day_sales_role',
                               'source_role_data_date',DATE_FORMAT(sr.data_date,'%Y-%m-%d'),
                               'first_calculated_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d')
                           )
                       ),
                       v_data_date
                FROM tmp_pre_oos_category_targets t
                JOIN `dws_datasync`.`dws_标签表` sr
                  ON sr.data_date = DATE_SUB(v_data_date,INTERVAL 1 DAY)
                 AND sr.country_category = t.country_category
                 AND sr.country IS NULL
                 AND sr.store = t.store
                 AND sr.msku = t.MSKU
                 AND sr.label_period IN ('7d','14d','30d','90d')
                JOIN `dws_datasync`.`dws_标签详情表` sd
                  ON sd.sub_label_id = sr.label_id
                 AND CAST(sd.label_name AS CHAR) = '销售角色'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '断货前销售角色'
                 AND l.sub_label_name = CASE CAST(sd.sub_label_name AS CHAR)
                     WHEN '明星产品' THEN '断货前-明星产品'
                     WHEN '潜力产品' THEN '断货前-潜力产品'
                     WHEN '瘦狗产品' THEN '断货前-瘦狗产品'
                     WHEN '问题产品' THEN '断货前-问题产品'
                 END
                WHERE t.is_new_oos = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tmp_pre_oos_json_reuse c
                      WHERE c.dimension_type = 'country_category'
                        AND c.country_category = t.country_category
                        AND c.country = ''
                        AND c.store = t.store
                        AND c.msku = t.MSKU
                        AND c.oos_start_date = t.oos_start_date
                        AND c.label_period = sr.label_period
                  );


                -- 标签21：国家+店铺+MSKU，规则与标签13一致；排名取各窗口内最新统计日期的值。
                SET v_stage = 'pre oos station period metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_period_metrics;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_period_metrics AS
                SELECT t.country_category,
                       t.country,
                       t.store,
                       t.msku,
                       t.oos_start_date,
                       t.current_fba_available,
                       t.current_fba_in_transit,
                       t.current_local_quantity,
                       t.oos_start_method,
                       t.history_start_date,
                       t.previous_positive_date,
                       w.label_period,
                       w.days,
                       DATE_SUB(t.oos_start_date, INTERVAL w.days DAY) AS window_start,
                       DATE_SUB(t.oos_start_date, INTERVAL 1 DAY) AS window_end,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.volume,0) ELSE 0 END) AS period_sales_qty,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.amount,0) ELSE 0 END) AS sales_amount,
                       SUM(CASE WHEN p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                                    AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(p.predict_gross_profit, 0)
                                ELSE 0 END) AS tag_gross_profit
                FROM tmp_pre_oos_station_new t
                CROSS JOIN tmp_pre_oos_periods w
                LEFT JOIN tmp_pre_oos_history_scoped p
                  ON p.country_category = t.country_category
                 AND p.source_country = t.country
                 AND p.perf_store = t.store
                 AND p.perf_msku = t.msku
                 AND p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL 90 DAY)
                                     AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                GROUP BY t.country_category, t.country, t.store, t.msku, t.oos_start_date,
                         t.current_fba_available,t.current_fba_in_transit,t.current_local_quantity,
                         t.oos_start_method,t.history_start_date,t.previous_positive_date,
                         w.label_period, w.days;

                SET v_stage = 'pre oos station latest ranks';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_latest_ranks;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_latest_ranks AS
                SELECT country_category, country, store, msku, oos_start_date,
                       label_period, stat_date AS small_rank_stat_date, small_rank_raw AS small_rank
                FROM (
                    SELECT t.country_category,
                           t.country,
                           t.store,
                           t.msku,
                           t.oos_start_date,
                           w.label_period,
                           p.stat_date,
                           p.small_rank_raw,
                           ROW_NUMBER() OVER (
                               PARTITION BY t.country, t.store, t.msku, t.oos_start_date, w.label_period
                               ORDER BY p.stat_date DESC, p.source_create_time DESC, p.source_id DESC
                           ) AS rn
                    FROM tmp_pre_oos_station_new t
                    CROSS JOIN tmp_pre_oos_periods w
                    JOIN tmp_pre_oos_history_scoped p
                      ON p.country_category = t.country_category
                     AND p.source_country = t.country
                     AND p.perf_store = t.store
                     AND p.perf_msku = t.msku
                     AND p.stat_date BETWEEN DATE_SUB(t.oos_start_date, INTERVAL w.days DAY)
                                         AND DATE_SUB(t.oos_start_date, INTERVAL 1 DAY)
                ) ranked
                WHERE rn = 1;
                ALTER TABLE tmp_pre_oos_station_latest_ranks
                    ADD INDEX idx_pre_oos_station_latest_ranks
                        (country, store, msku, oos_start_date, label_period);

                SET v_stage = 'pre oos station roles';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_roles;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_roles AS
                SELECT x.*,
                       CASE
                           WHEN x.daily_sales = 0 THEN '问题产品(站点)'
                           WHEN x.daily_sales > 0 AND x.daily_sales <= 1 AND x.margin_rate < 0.05 THEN '问题产品(站点)'
                           WHEN x.daily_sales > 0 AND x.daily_sales <= 1 AND x.margin_rate >= 0.05
                            AND (x.small_rank IS NULL OR x.small_rank = 0 OR x.small_rank = 99999) THEN '问题产品(站点)'
                           WHEN x.small_rank BETWEEN 51 AND 100
                            AND ((x.daily_sales > 3 AND x.margin_rate >= 0.15)
                              OR (x.daily_sales BETWEEN 1 AND 3 AND x.margin_rate >= 0.25)) THEN '潜力产品(站点)'
                           WHEN x.small_rank BETWEEN 1 AND 50
                            AND ((x.daily_sales > 3 AND x.margin_rate >= 0.15)
                              OR (x.daily_sales BETWEEN 1 AND 3 AND x.margin_rate >= 0.25)) THEN '明星产品(站点)'
                           WHEN x.small_rank BETWEEN 1 AND 100
                            AND ((x.daily_sales > 3 AND x.margin_rate >= 0.05 AND x.margin_rate < 0.15)
                              OR (x.daily_sales BETWEEN 1 AND 3 AND x.margin_rate >= 0.10 AND x.margin_rate < 0.25))
                               THEN '潜力产品(站点)'
                           WHEN x.daily_sales > 1 AND x.margin_rate < 0.05 THEN '瘦狗产品(站点)'
                           WHEN x.daily_sales > 1 AND x.margin_rate >= 0.05
                            AND (x.small_rank IS NULL OR x.small_rank = 0 OR x.small_rank = 99999) THEN '瘦狗产品(站点)'
                           WHEN ((x.daily_sales BETWEEN 1 AND 3 AND x.margin_rate >= 0.05 AND x.margin_rate < 0.10)
                              OR (x.daily_sales > 0 AND x.daily_sales < 1 AND x.margin_rate >= 0.05))
                            AND x.small_rank BETWEEN 1 AND 100 THEN '瘦狗产品(站点)'
                           WHEN x.daily_sales > 0 AND x.margin_rate >= 0.05
                            AND x.small_rank > 100 AND x.small_rank <> 99999 THEN '瘦狗产品(站点)'
                       END AS sales_role
                FROM (
                    SELECT m.*,
                           m.period_sales_qty / m.days AS daily_sales,
                           CASE WHEN m.sales_amount > 0
                                THEN m.tag_gross_profit / m.sales_amount
                                ELSE 0 END AS margin_rate,
                           r.small_rank,
                           r.small_rank_stat_date
                    FROM tmp_pre_oos_station_period_metrics m
                    LEFT JOIN tmp_pre_oos_station_latest_ranks r
                      ON r.country = m.country
                     AND r.store = m.store
                     AND r.msku = m.msku
                     AND r.oos_start_date = m.oos_start_date
                     AND r.label_period = m.label_period
                ) x;

                SET v_stage = 'pre oos station cache pending';
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_pending;
                CREATE TEMPORARY TABLE tmp_pre_oos_station_pending AS
                SELECT 'country' AS dimension_type,
                       r.country_category,
                       r.country,
                       r.store,
                       r.msku,
                       r.oos_start_date,
                       r.label_period,
                       l.sub_label_id AS label_id,
                       JSON_OBJECT(
                           'schema_version','1.1',
                           'rule_version','v47_pre_oos_station_role_20260826_hybrid',
                           'type','pre_oos_station_sales_role',
                           'dimension','country+store+msku',
                           'oos',JSON_OBJECT(
                               'oos_start_date',DATE_FORMAT(r.oos_start_date,'%Y-%m-%d'),
                               'snapshot_end_date',DATE_FORMAT(r.window_end,'%Y-%m-%d'),
                               'current_operation_status','断货中',
                               'inventory_source_fba','etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail',
                               'inventory_source_local','etl_datasync.etl_dispose_lx_replenishment_suggest_restocking',
                               'current_fba_available',r.current_fba_available,
                               'current_fba_in_transit',r.current_fba_in_transit,
                               'current_local_quantity',r.current_local_quantity,
                               'oos_start_method',r.oos_start_method,
                               'history_start_date',DATE_FORMAT(r.history_start_date,'%Y-%m-%d'),
                               'previous_positive_date',DATE_FORMAT(r.previous_positive_date,'%Y-%m-%d'),
                               'matched_rule','当前已命中304断货中；历史断货日起点仅按有效FBA快照可售库存=0回溯'
                           ),
                           'window',JSON_OBJECT(
                               'start',DATE_FORMAT(r.window_start,'%Y-%m-%d'),
                               'end',DATE_FORMAT(r.window_end,'%Y-%m-%d'),
                               'period',r.label_period,
                               'days',r.days
                           ),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(r.period_sales_qty,4),
                               'daily_sales',ROUND(r.daily_sales,4),
                               'sales_amount',ROUND(r.sales_amount,4),
                               'tag_gross_profit',ROUND(r.tag_gross_profit,4),
                               'tag_margin_rate',ROUND(100*r.margin_rate,4),
                               'small_rank',r.small_rank,
                               'small_rank_stat_date',DATE_FORMAT(r.small_rank_stat_date,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.sales_role,
                               'condition',CASE
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales = 0
                                       THEN '日销=0'
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales > 0 AND r.daily_sales <= 1 AND r.margin_rate < 0.05
                                       THEN '0<日销<=1且毛利率<5%'
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales > 0 AND r.daily_sales <= 1 AND r.margin_rate >= 0.05
                                    AND (r.small_rank IS NULL OR r.small_rank = 0 OR r.small_rank = 99999)
                                       THEN '0<日销<=1、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.sales_role = '明星产品(站点)' AND r.daily_sales > 3
                                       THEN '小类排名1-50，日销>3且毛利率>=15%'
                                   WHEN r.sales_role = '明星产品(站点)' AND r.daily_sales BETWEEN 1 AND 3
                                       THEN '小类排名1-50，1<=日销<=3且毛利率>=25%'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.small_rank BETWEEN 51 AND 100
                                       THEN '小类排名51-100，且满足明星产品的日销毛利条件'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.daily_sales > 3
                                       THEN '小类排名1-100，日销>3且5%<=毛利率<15%'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.daily_sales BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且10%<=毛利率<25%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 1 AND r.margin_rate < 0.05
                                       THEN '日销>1且毛利率<5%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 1 AND r.margin_rate >= 0.05
                                    AND (r.small_rank IS NULL OR r.small_rank = 0 OR r.small_rank = 99999)
                                       THEN '日销>1、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.small_rank BETWEEN 1 AND 100
                                    AND r.daily_sales BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且5%<=毛利率<10%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.small_rank BETWEEN 1 AND 100
                                    AND r.daily_sales > 0 AND r.daily_sales < 1
                                       THEN '小类排名1-100，0<日销<1且毛利率>=5%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.small_rank > 100 AND r.small_rank <> 99999
                                       THEN '日销>0、毛利率>=5%，且小类排名>100且不等于99999'
                               END,
                               'daily_sales',CASE
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales = 0 THEN '= 0'
                                   WHEN r.sales_role IN ('潜力产品(站点)','明星产品(站点)') AND r.daily_sales > 3 THEN '> 3'
                                   WHEN r.sales_role IN ('潜力产品(站点)','明星产品(站点)') AND r.daily_sales BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 0 AND r.daily_sales < 1 THEN '> 0 AND < 1'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 1 THEN '> 1'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.sales_role IN ('问题产品(站点)','瘦狗产品(站点)') AND r.daily_sales > 0 THEN '> 0'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales = 0 THEN 'NOT_USED'
                                   WHEN r.sales_role = '问题产品(站点)' AND r.daily_sales > 0 AND r.daily_sales <= 1 AND r.margin_rate < 0.05 THEN '< 5%'
                                   WHEN r.sales_role = '问题产品(站点)' THEN '>= 5%'
                                   WHEN r.sales_role = '明星产品(站点)' AND r.daily_sales > 3 THEN '>= 15%'
                                   WHEN r.sales_role = '明星产品(站点)' AND r.daily_sales BETWEEN 1 AND 3 THEN '>= 25%'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.small_rank BETWEEN 51 AND 100 AND r.daily_sales > 3 THEN '>= 15%'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.small_rank BETWEEN 51 AND 100 THEN '>= 25%'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.daily_sales > 3 THEN '>= 5% AND < 15%'
                                   WHEN r.sales_role = '潜力产品(站点)' THEN '>= 10% AND < 25%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 1 AND r.margin_rate < 0.05 THEN '< 5%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.small_rank BETWEEN 1 AND 100 AND r.daily_sales BETWEEN 1 AND 3 THEN '>= 5% AND < 10%'
                                   WHEN r.sales_role = '瘦狗产品(站点)' THEN '>= 5%'
                               END,
                               'small_rank',CASE
                                   WHEN r.sales_role = '问题产品(站点)'
                                    AND r.daily_sales > 0 AND r.margin_rate >= 0.05
                                    AND (r.small_rank IS NULL OR r.small_rank = 0 OR r.small_rank = 99999)
                                       THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.sales_role = '问题产品(站点)' THEN 'NOT_USED'
                                   WHEN r.sales_role = '明星产品(站点)' THEN 'BETWEEN 1 AND 50'
                                   WHEN r.sales_role = '潜力产品(站点)' AND r.small_rank BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.sales_role = '潜力产品(站点)' THEN 'BETWEEN 1 AND 100'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.daily_sales > 1
                                    AND (r.small_rank IS NULL OR r.small_rank = 0 OR r.small_rank = 99999) THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.sales_role = '瘦狗产品(站点)' AND r.small_rank BETWEEN 1 AND 100 THEN 'BETWEEN 1 AND 100'
                                   WHEN r.sales_role = '瘦狗产品(站点)' THEN '> 100 AND <> 99999'
                               END
                           ),
                           'calculation',JSON_OBJECT(
                               'mode','historical_backtrack',
                               'first_calculated_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d')
                           )
                       ) AS evidence_json,
                       v_data_date AS first_calculated_data_date
                FROM tmp_pre_oos_station_roles r
                JOIN tmp_station_active_labels l
                  ON l.label_name = '断货前销售角色(站点)'
                 AND l.sub_label_name = CASE r.sales_role
                     WHEN '明星产品(站点)' THEN '断货前-明星产品（站点）'
                     WHEN '潜力产品(站点)' THEN '断货前-潜力产品（站点）'
                     WHEN '瘦狗产品(站点)' THEN '断货前-瘦狗产品（站点）'
                     WHEN '问题产品(站点)' THEN '断货前-问题产品（站点）'
                 END;

                -- 新发生304：直接冻结前一业务日标签13的同国家、同周期站点销售角色。
                SET v_stage = 'pre oos station transition role copy';
                INSERT INTO tmp_pre_oos_station_pending
                    (dimension_type,country_category,country,store,msku,oos_start_date,
                     label_period,label_id,evidence_json,first_calculated_data_date)
                SELECT DISTINCT
                       'country',
                       t.country_category,
                       t.country,
                       t.store,
                       t.msku,
                       t.oos_start_date,
                       sr.label_period,
                       l.sub_label_id,
                       JSON_OBJECT(
                           'schema_version','1.1',
                           'rule_version','v47_pre_oos_station_role_20260826_hybrid',
                           'type','pre_oos_station_sales_role',
                           'dimension','country+store+msku',
                           'oos',JSON_OBJECT(
                               'oos_start_date',DATE_FORMAT(t.oos_start_date,'%Y-%m-%d'),
                               'snapshot_end_date',DATE_FORMAT(DATE_SUB(v_data_date,INTERVAL 1 DAY),'%Y-%m-%d'),
                               'current_status_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                               'current_operation_status','断货中',
                               'inventory_source_fba','etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail',
                               'inventory_source_local','etl_datasync.etl_dispose_lx_replenishment_suggest_restocking',
                               'current_fba_available',t.current_fba_available,
                               'current_fba_in_transit',t.current_fba_in_transit,
                               'current_local_quantity',t.current_local_quantity,
                               'oos_start_method','daily_status_transition',
                               'matched_rule','前一业务日运营状态明确不是断货中，当日最终命中304断货中且FBA可售库存=0'
                           ),
                           'window',JSON_EXTRACT(sr.evidence_json,'$.window'),
                           'metrics',JSON_EXTRACT(sr.evidence_json,'$.metrics'),
                           'matched_rule',JSON_EXTRACT(sr.evidence_json,'$.matched_rule'),
                           'source_sales_role',JSON_OBJECT(
                               'data_date',DATE_FORMAT(sr.data_date,'%Y-%m-%d'),
                               'label_period',sr.label_period,
                               'sub_label_id',sr.label_id,
                               'sub_label_name',CAST(sd.sub_label_name AS CHAR)
                           ),
                           'calculation',JSON_OBJECT(
                               'mode','copy_previous_day_station_sales_role',
                               'source_role_data_date',DATE_FORMAT(sr.data_date,'%Y-%m-%d'),
                               'first_calculated_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d')
                           )
                       ),
                       v_data_date
                FROM tmp_pre_oos_station_targets t
                JOIN `dws_datasync`.`dws_标签表` sr
                  ON sr.data_date = DATE_SUB(v_data_date,INTERVAL 1 DAY)
                 AND sr.country_category = t.country_category
                 AND sr.country = t.country
                 AND sr.store = t.store
                 AND sr.msku = t.msku
                 AND sr.label_period IN ('7d','14d','30d','90d')
                JOIN `dws_datasync`.`dws_标签详情表` sd
                  ON sd.sub_label_id = sr.label_id
                 AND CAST(sd.label_name AS CHAR) = '站点销售角色'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '断货前销售角色(站点)'
                 AND l.sub_label_name = CASE CAST(sd.sub_label_name AS CHAR)
                     WHEN '明星产品(站点)' THEN '断货前-明星产品（站点）'
                     WHEN '潜力产品(站点)' THEN '断货前-潜力产品（站点）'
                     WHEN '瘦狗产品(站点)' THEN '断货前-瘦狗产品（站点）'
                     WHEN '问题产品(站点)' THEN '断货前-问题产品（站点）'
                 END
                WHERE t.is_new_oos = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tmp_pre_oos_json_reuse c
                      WHERE c.dimension_type = 'country'
                        AND c.country_category = t.country_category
                        AND c.country = t.country
                        AND c.store = t.store
                        AND c.msku = t.msku
                        AND c.oos_start_date = t.oos_start_date
                        AND c.label_period = sr.label_period
                  );


                SET v_stage = 'pre_oos_temp_cleanup_keep_perf_scoped';
                -- tmp_perf_scoped仍供S20固定7日销量和S26返厂D3指标使用，此处不提前删除。
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_periods;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_prev_operation_status;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_current_category_status;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_current_station_status;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_cycle_cache;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_cache_counts;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_cache_counts;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_candidates;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_candidate_msku;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_scoped;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_fba_latest_key;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_fba_daily;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_daily;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_last_positive;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_history_starts;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_new;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_period_metrics;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_category_roles;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_new;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_period_metrics;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_latest_ranks;
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_station_roles;

                -- 站点生命周期首次收货：按 国家类别 + 店铺 + MSKU 取最早 receiving_time。
                -- 不再按国家限制货件来源：只要该国家类别内任一国家已首次收货，
                -- 即认为该国家类别下所有存在 Listing 的国家都具备相同的生命周期起点。
                -- 站点销售角色仍在后续按 国家 + 店铺 + MSKU 独立计算，不受此处影响。
                -- 先仅保留实际存在 Listing 的国家类别+店铺+MSKU，避免扫描无关货件。
                SET v_stage = 'station category first receiving keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_category_receiving_keys;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S08 生成国家类别首次收货商品键';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2372,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_category_receiving_keys AS
                SELECT DISTINCT country_category, store, msku
                FROM tmp_station_listing_keys;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_category_receiving_keys
                    ADD INDEX idx_station_category_receiving_keys (country_category, store, msku);

                SET v_stage = 'station category first receiving';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_category_first_receiving;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S09 计算国家类别首次收货日期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2380,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_category_first_receiving
                    ADD INDEX idx_station_category_first_receiving (country_category, store, msku);

                SET v_stage = 'station first receiving';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_first_receiving;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S10 展开国家站点首次收货日期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2409,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_first_receiving
                    ADD INDEX idx_station_first_receiving (country, store, msku);

                -- ========================================================================
                -- V47：站点产品问题标签统一计算层。
                -- 10%订单毛利价格测试状态没有独立业务字段，按每日定价快照推导：
                -- 10%订单毛利价格测试链路继续供标签17运营策略复核使用：调价后满7个自然日，并统计固定7天站点日销。
                -- ========================================================================
                SET v_stage = 'station period metrics v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_period_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S11 展开站点四周期指标';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2430,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_period_metrics AS
                SELECT r.country_category,
                       r.country,
                       r.store,
                       r.msku,
                       w.label_period,
                       w.period_days,
                       w.period_start,
                       CASE w.label_period
                           WHEN '7d' THEN r.role_7d
                           WHEN '14d' THEN r.role_14d
                           WHEN '30d' THEN r.role_30d
                           WHEN '90d' THEN r.role_90d
                       END AS station_sales_role,
                       CASE w.label_period
                           WHEN '7d' THEN m.volume_7d
                           WHEN '14d' THEN m.volume_14d
                           WHEN '30d' THEN m.volume_30d
                           WHEN '90d' THEN m.volume_90d
                       END AS period_sales_qty,
                       CASE w.label_period
                           WHEN '7d' THEN m.volume_7d / 7.0
                           WHEN '14d' THEN m.volume_14d / 14.0
                           WHEN '30d' THEN m.volume_30d / 30.0
                           WHEN '90d' THEN m.volume_90d / 90.0
                       END AS daily_sales,
                       CASE w.label_period
                           WHEN '7d' THEN m.sales_amount_7d
                           WHEN '14d' THEN m.sales_amount_14d
                           WHEN '30d' THEN m.sales_amount_30d
                           WHEN '90d' THEN m.sales_amount_90d
                       END AS sales_amount,
                       CASE w.label_period
                           WHEN '7d' THEN m.tag_gross_profit_7d
                           WHEN '14d' THEN m.tag_gross_profit_14d
                           WHEN '30d' THEN m.tag_gross_profit_30d
                           WHEN '90d' THEN m.tag_gross_profit_90d
                       END AS tag_gross_profit,
                       CASE w.label_period
                           WHEN '7d' THEN m.margin_rate_7d
                           WHEN '14d' THEN m.margin_rate_14d
                           WHEN '30d' THEN m.margin_rate_30d
                           WHEN '90d' THEN m.margin_rate_90d
                       END AS order_margin_rate,
                       CASE w.label_period
                           WHEN '7d' THEN m.acoas_rate_7d
                           WHEN '14d' THEN m.acoas_rate_14d
                           WHEN '30d' THEN m.acoas_rate_30d
                           WHEN '90d' THEN m.acoas_rate_90d
                       END AS acoas_rate,
                       CASE w.label_period
                           WHEN '7d' THEN m.small_rank_7d
                           WHEN '14d' THEN m.small_rank_14d
                           WHEN '30d' THEN m.small_rank_30d
                           WHEN '90d' THEN m.small_rank_90d
                       END AS small_rank,
                       CASE w.label_period
                           WHEN '7d' THEN m.latest_rank_date_7d
                           WHEN '14d' THEN m.latest_rank_date_14d
                           WHEN '30d' THEN m.latest_rank_date_30d
                           WHEN '90d' THEN m.latest_rank_date_90d
                       END AS small_rank_stat_date
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country
                 AND m.store = r.store
                 AND m.msku = r.msku
                CROSS JOIN (
                    SELECT '7d' AS label_period, 7 AS period_days, v_7d AS period_start
                    UNION ALL SELECT '14d', 14, v_14d
                    UNION ALL SELECT '30d', 30, v_30d
                    UNION ALL SELECT '90d', 90, v_90d
                ) w;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_period_metrics
                    ADD INDEX idx_station_period_metrics (country_category, country, store, msku, label_period);

                SET v_stage = 'station price snapshot daily v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_price_daily;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S12 汇总站点定价每日快照';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2508,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_price_daily AS
                SELECT (CASE
                            WHEN CAST(t.`国家` AS CHAR) = '英国' THEN '英国站'
                            WHEN CAST(t.`国家` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                            ELSE COALESCE(CAST(t.`国家类别` AS CHAR), '欧洲站')
                        END) COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(t.`国家` AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS country,
                       (CASE
                            WHEN LOCATE('-', SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1)) > 0
                                THEN LEFT(SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1),
                                          LOCATE('-', SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1)) - 1)
                            ELSE SUBSTRING_INDEX(CAST(t.`新店铺` AS CHAR), ' ', 1)
                        END) COLLATE utf8mb4_0900_ai_ci AS store,
                       CAST(t.`msku` AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS msku,
                       t.`数据日期` AS stat_date,
                       MIN(CASE
                               WHEN TRIM(CAST(t.`listing价格` AS CHAR)) REGEXP '^[0-9]+([.][0-9]+)?$'
                                   THEN CAST(t.`listing价格` AS DECIMAL(18,4))
                           END) AS listing_price,
                       MAX(CASE
                               WHEN t.`5毛利润价格` IS NOT NULL
                                   THEN CAST(t.`5毛利润价格` AS DECIMAL(18,4))
                           END) AS five_pct_target_price,
                       MAX(CASE
                               WHEN t.`10毛利润价格` IS NOT NULL
                                   THEN CAST(t.`10毛利润价格` AS DECIMAL(18,4))
                           END) AS ten_pct_target_price,
                       MAX(CASE
                               WHEN t.`15毛利润价格` IS NOT NULL
                                   THEN CAST(t.`15毛利润价格` AS DECIMAL(18,4))
                           END) AS fifteen_pct_target_price,
                       MAX(CASE
                               WHEN TRIM(CAST(t.`listing价格` AS CHAR)) REGEXP '^[0-9]+([.][0-9]+)?$'
                                AND t.`10毛利润价格` IS NOT NULL
                                AND CAST(t.`listing价格` AS DECIMAL(18,4)) <= t.`10毛利润价格`
                                   THEN 1 ELSE 0
                           END) AS is_at_or_below_10pct_price,
                       MAX(CASE
                               WHEN t.`近30天ACOAS` IS NULL THEN NULL
                               WHEN ABS(t.`近30天ACOAS`) > 1 THEN t.`近30天ACOAS` / 100.0
                               ELSE t.`近30天ACOAS`
                           END) AS snapshot_acoas_rate
                FROM `temporary_dwd`.`在库节点_输出定价表_每日快照` t
                WHERE t.`数据日期` <= v_data_date
                  AND t.`msku` IS NOT NULL
                  AND CAST(t.`msku` AS CHAR) <> ''
                  AND LOWER(TRIM(CAST(t.`msku` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND UPPER(TRIM(CAST(t.`msku` AS CHAR))) NOT LIKE 'AMAZON%'
                GROUP BY 1,2,3,4,5;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_price_daily
                    ADD INDEX idx_station_price_daily (country_category, country, store, msku, stat_date);

                -- 每个国家+店铺+MSKU取不晚于业务日的最新10%订单毛利目标价。
                -- 调价当日有快照时优先用当日目标价；历史当日快照缺失时才回退到最新目标价。
                SET v_stage = 'station latest 10pct target price v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_target_latest;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S13 提取最新10%订单毛利目标价';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2564,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_target_latest AS
                SELECT x.country_category, x.country, x.store, x.msku,
                       x.stat_date AS target_stat_date,
                       x.listing_price,
                       x.five_pct_target_price,
                       x.ten_pct_target_price,
                       x.fifteen_pct_target_price
                FROM (
                    SELECT d.country_category, d.country, d.store, d.msku,
                           d.stat_date, d.listing_price,
                           d.five_pct_target_price, d.ten_pct_target_price, d.fifteen_pct_target_price,
                           ROW_NUMBER() OVER (
                               PARTITION BY d.country_category, d.country, d.store, d.msku
                               ORDER BY d.stat_date DESC
                           ) AS rn
                    FROM tmp_station_price_daily d
                    WHERE d.ten_pct_target_price IS NOT NULL
                ) x
                WHERE x.rn = 1;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_target_latest
                    ADD INDEX idx_station_10pct_target_latest (country_category, country, store, msku);

                -- 真实调价队列：仅取调价成功、未删除、价格有效且完成日期不晚于业务日的记录。
                SET v_stage = 'station adjust price queue v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_adjust_queue;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S14 读取10%订单毛利调价队列';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2589,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_adjust_queue AS
                SELECT CASE
                           WHEN CAST(q.`marketplace` AS CHAR) = '英国' THEN '英国站'
                           WHEN CAST(q.`marketplace` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                           ELSE '欧洲站'
                       END COLLATE utf8mb4_0900_ai_ci AS country_category,
                       CAST(q.`marketplace` AS CHAR(100)) COLLATE utf8mb4_0900_ai_ci AS country,
                       (CASE
                            WHEN LOCATE('-', SUBSTRING_INDEX(CAST(q.`store_name` AS CHAR), ' ', 1)) > 0
                                THEN LEFT(SUBSTRING_INDEX(CAST(q.`store_name` AS CHAR), ' ', 1),
                                          LOCATE('-', SUBSTRING_INDEX(CAST(q.`store_name` AS CHAR), ' ', 1)) - 1)
                            ELSE SUBSTRING_INDEX(CAST(q.`store_name` AS CHAR), ' ', 1)
                        END) COLLATE utf8mb4_0900_ai_ci AS store,
                       CAST(q.`msku` AS CHAR(255)) COLLATE utf8mb4_0900_ai_ci AS msku,
                       CAST(q.`relate_id` AS CHAR(50)) AS adjust_relate_id,
                       STR_TO_DATE(NULLIF(TRIM(CAST(q.`finish_time` AS CHAR)), ''), '%Y-%m-%d %H:%i:%s') AS adjust_finish_time,
                       DATE(STR_TO_DATE(NULLIF(TRIM(CAST(q.`finish_time` AS CHAR)), ''), '%Y-%m-%d %H:%i:%s')) AS adjust_date,
                       CAST(q.`adjust_before_obj_standard_price` AS DECIMAL(18,4)) AS adjust_before_price,
                       CAST(q.`adjust_after_obj_standard_price` AS DECIMAL(18,4)) AS adjust_after_price
                FROM `temporary_APP`.`lx_sale_adjust_price_queue` q
                WHERE COALESCE(q.`delete_flag`, 0) = 0
                  AND CAST(q.`processing_status_text` AS CHAR) = '调价成功'
                  AND TRIM(CAST(q.`adjust_before_obj_standard_price` AS CHAR)) REGEXP '^[0-9]+([.][0-9]+)?$'
                  AND TRIM(CAST(q.`adjust_after_obj_standard_price` AS CHAR)) REGEXP '^[0-9]+([.][0-9]+)?$'
                  AND STR_TO_DATE(NULLIF(TRIM(CAST(q.`finish_time` AS CHAR)), ''), '%Y-%m-%d %H:%i:%s') IS NOT NULL
                  AND DATE(STR_TO_DATE(NULLIF(TRIM(CAST(q.`finish_time` AS CHAR)), ''), '%Y-%m-%d %H:%i:%s')) <= v_data_date
                  AND q.`msku` IS NOT NULL
                  AND TRIM(CAST(q.`msku` AS CHAR)) <> ''
                  AND LOWER(TRIM(CAST(q.`msku` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND UPPER(TRIM(CAST(q.`msku` AS CHAR))) NOT LIKE 'AMAZON%';
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_adjust_queue
                    ADD INDEX idx_station_10pct_adjust_queue (country_category, country, store, msku, adjust_date);

                -- 进入10%订单毛利测试的跨档条件：调前价格>目标价，调后价格<=目标价。
                -- 第一步只连接调价日精确快照，避免优化器在一条SQL中同时处理两个LEFT JOIN。
                SET v_stage = 'station 10pct adjust exact snapshot v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_adjust_exact;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S15 连接调价队列与调价日精确快照';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2626,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_adjust_exact AS
                SELECT q.country_category, q.country, q.store, q.msku,
                       q.adjust_relate_id, q.adjust_finish_time, q.adjust_date,
                       q.adjust_before_price, q.adjust_after_price,
                       p_exact.ten_pct_target_price AS exact_ten_pct_target_price,
                       p_exact.stat_date AS exact_target_stat_date
                FROM tmp_station_10pct_adjust_queue q
                LEFT JOIN tmp_station_price_daily p_exact
                  ON p_exact.country_category = q.country_category
                 AND p_exact.country = q.country
                 AND p_exact.store = q.store
                 AND p_exact.msku = q.msku
                 AND p_exact.stat_date = q.adjust_date;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_adjust_exact
                    ADD INDEX idx_station_10pct_adjust_exact (country_category, country, store, msku);

                -- 第二步仅对精确快照缺失的数据补充业务日之前的最新10%订单毛利目标价，并识别跨档事件。
                SET v_stage = 'station 10pct adjust crossing events v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_adjust_events;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S16 补充最新10%订单毛利目标价并识别跨档事件';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2645,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_adjust_events AS
                SELECT a.country_category, a.country, a.store, a.msku,
                       a.adjust_relate_id, a.adjust_finish_time, a.adjust_date,
                       a.adjust_before_price, a.adjust_after_price,
                       COALESCE(a.exact_ten_pct_target_price, p_latest.ten_pct_target_price) AS ten_pct_target_price,
                       COALESCE(a.exact_target_stat_date, p_latest.target_stat_date) AS ten_pct_target_stat_date,
                       CASE WHEN a.exact_ten_pct_target_price IS NOT NULL
                                THEN 'adjust_date_exact_snapshot'
                            ELSE 'latest_snapshot_on_or_before_business_date'
                       END AS target_price_match_method
                FROM tmp_station_10pct_adjust_exact a
                LEFT JOIN tmp_station_10pct_target_latest p_latest
                  ON a.exact_ten_pct_target_price IS NULL
                 AND p_latest.country_category = a.country_category
                 AND p_latest.country = a.country
                 AND p_latest.store = a.store
                 AND p_latest.msku = a.msku
                WHERE COALESCE(a.exact_ten_pct_target_price, p_latest.ten_pct_target_price) IS NOT NULL
                  AND a.adjust_before_price > COALESCE(a.exact_ten_pct_target_price, p_latest.ten_pct_target_price)
                  AND a.adjust_after_price <= COALESCE(a.exact_ten_pct_target_price, p_latest.ten_pct_target_price);
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_adjust_events
                    ADD INDEX idx_station_10pct_adjust_events (country_category, country, store, msku, adjust_finish_time);
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_adjust_exact;

                -- 多轮测试按最近一次符合跨档条件的真实调价事件重新计时。
                SET v_stage = 'station latest 10pct adjust event v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_adjust_latest;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S17 提取最新10%订单毛利调价事件';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2672,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_adjust_latest AS
                SELECT x.country_category, x.country, x.store, x.msku,
                       x.adjust_relate_id, x.adjust_finish_time, x.adjust_date,
                       x.adjust_before_price, x.adjust_after_price,
                       x.ten_pct_target_price, x.ten_pct_target_stat_date,
                       x.target_price_match_method
                FROM (
                    SELECT e.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY e.country_category, e.country, e.store, e.msku
                               ORDER BY e.adjust_finish_time DESC, e.adjust_relate_id DESC
                           ) AS rn
                    FROM tmp_station_10pct_adjust_events e
                ) x
                WHERE x.rn = 1;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_adjust_latest
                    ADD INDEX idx_station_10pct_adjust_latest (country_category, country, store, msku);

                -- S18拆分第一步：Listing商品池只连接最新10%订单毛利调价事件（一对一）。
                SET v_stage = 'station price test adjust base v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_price_test_adjust_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S18 连接Listing商品池与最新调价事件';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2693,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_price_test_adjust_base AS
                SELECT k.country_category, k.country, k.store, k.msku,
                       a.adjust_date,
                       a.adjust_relate_id,
                       a.adjust_finish_time,
                       a.adjust_before_price,
                       a.adjust_after_price,
                       a.ten_pct_target_price,
                       a.ten_pct_target_stat_date,
                       a.target_price_match_method
                FROM tmp_station_listing_keys k
                LEFT JOIN tmp_station_10pct_adjust_latest a
                  ON a.country_category = k.country_category
                 AND a.country = k.country
                 AND a.store = k.store
                 AND a.msku = k.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_price_test_adjust_base
                    ADD INDEX idx_station_price_test_adjust_base (country_category, country, store, msku);

                -- S18拆分第二步：使用第一步结果连接定价每日快照并计算价格测试状态。
                SET v_stage = 'station price test status v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_price_test_status;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S19 连接价格测试基础结果与定价每日快照';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2715,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_price_test_status AS
                SELECT x.country_category, x.country, x.store, x.msku,
                       MIN(d.stat_date) AS price_history_start_date,
                       x.adjust_date AS first_10pct_test_date,
                       x.adjust_relate_id,
                       x.adjust_finish_time,
                       x.adjust_before_price,
                       x.adjust_after_price,
                       x.ten_pct_target_price,
                       x.ten_pct_target_stat_date,
                       x.target_price_match_method,
                       MIN(CASE WHEN x.adjust_date IS NOT NULL
                                     AND d.stat_date >= x.adjust_date
                                     AND d.is_at_or_below_10pct_price = 1
                                     AND d.snapshot_acoas_rate >= 0.05 THEN d.stat_date END) AS first_10pct_acos5_date
                FROM tmp_station_price_test_adjust_base x
                LEFT JOIN tmp_station_price_daily d
                  ON d.country_category = x.country_category
                 AND d.country = x.country
                 AND d.store = x.store
                 AND d.msku = x.msku
                GROUP BY x.country_category, x.country, x.store, x.msku,
                         x.adjust_date, x.adjust_relate_id, x.adjust_finish_time,
                         x.adjust_before_price, x.adjust_after_price,
                         x.ten_pct_target_price, x.ten_pct_target_stat_date,
                         x.target_price_match_method;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_price_test_status
                    ADD INDEX idx_station_price_test_status (country_category, country, store, msku);
                DROP TEMPORARY TABLE IF EXISTS tmp_station_price_test_adjust_base;

                -- 标签17复核固定使用真实调价完成日作为D1，统计D1-D7（完成日及后续6个自然日），不随7/14/30/90d标签周期变化。
                SET v_stage = 'station 10pct price test 7d sales v47 optimized';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_test_7d_sales;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S20 汇总调价后固定7天销量';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2748,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                -- 仅在S20/S26使用前建立站点精确关联索引，避免基础阶段装载及清理明细时维护额外索引。
                ALTER TABLE tmp_perf_scoped
                    ADD INDEX idx_tmp_perf_scoped_station_date
                        (country_category, source_country, perf_store, perf_msku, stat_date);

                CREATE TEMPORARY TABLE tmp_station_10pct_test_7d_sales AS
                SELECT s.country_category, s.country, s.store, s.msku,
                       SUM(CASE WHEN ps.stat_date BETWEEN s.first_10pct_test_date
                                                     AND DATE_ADD(s.first_10pct_test_date, INTERVAL 6 DAY)
                                THEN COALESCE(ps.volume,0) ELSE 0 END) AS test_7d_sales_qty
                FROM tmp_station_price_test_status s
                LEFT JOIN tmp_perf_scoped ps
                  ON ps.country_category = s.country_category
                 AND ps.source_country = s.country
                 AND ps.perf_store = s.store
                 AND ps.perf_msku = s.msku
                 AND ps.stat_date BETWEEN s.first_10pct_test_date
                                      AND DATE_ADD(s.first_10pct_test_date, INTERVAL 6 DAY)
                WHERE s.first_10pct_test_date IS NOT NULL
                GROUP BY s.country_category, s.country, s.store, s.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_test_7d_sales
                    ADD INDEX idx_station_10pct_test_7d_sales (country_category, country, store, msku);

                SET v_stage = 'station 10pct price test 7d metrics v47 optimized';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_10pct_test_7d_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S21 计算调价后7天测试指标';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2768,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_10pct_test_7d_metrics AS
                SELECT s.country_category, s.country, s.store, s.msku,
                       s.price_history_start_date, s.first_10pct_test_date,
                       CASE WHEN s.first_10pct_test_date IS NULL THEN NULL
                            ELSE DATE_ADD(s.first_10pct_test_date, INTERVAL 6 DAY) END AS test_7d_end_date,
                       CASE WHEN s.first_10pct_test_date IS NULL THEN NULL
                            ELSE DATEDIFF(v_data_date,s.first_10pct_test_date)+1 END AS test_elapsed_days,
                       CASE WHEN s.first_10pct_test_date IS NULL THEN NULL
                            ELSE COALESCE(a.test_7d_sales_qty,0) END AS test_7d_sales_qty,
                       CASE WHEN s.first_10pct_test_date IS NOT NULL
                                  AND DATEDIFF(v_data_date,s.first_10pct_test_date)+1 >= 7
                            THEN COALESCE(a.test_7d_sales_qty,0) / 7.0 END AS test_7d_daily_sales
                FROM tmp_station_price_test_status s
                LEFT JOIN tmp_station_10pct_test_7d_sales a
                  ON a.country_category = s.country_category
                 AND a.country = s.country
                 AND a.store = s.store
                 AND a.msku = s.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_10pct_test_7d_metrics
                    ADD INDEX idx_station_10pct_test_7d_metrics (country_category, country, store, msku);

                -- S21拆分第一步：四周期站点指标只连接10%订单毛利价格测试状态。
                SET v_stage = 'station product issue price base v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_product_issue_price_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S22 连接站点周期指标与价格测试状态';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2792,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_product_issue_price_base AS
                SELECT p.*,
                       s.price_history_start_date,
                       s.first_10pct_test_date,
                       s.first_10pct_acos5_date,
                       s.adjust_relate_id,
                       s.adjust_finish_time,
                       s.adjust_before_price,
                       s.adjust_after_price,
                       s.ten_pct_target_price,
                       s.ten_pct_target_stat_date,
                       s.target_price_match_method
                FROM tmp_station_period_metrics p
                LEFT JOIN tmp_station_price_test_status s
                  ON s.country_category = p.country_category
                 AND s.country = p.country
                 AND s.store = p.store
                 AND s.msku = p.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_product_issue_price_base
                    ADD INDEX idx_station_product_issue_price_base (country_category, country, store, msku, label_period);

                -- S21拆分第二步：使用第一步结果连接调价后固定7天测试指标并判定产品问题。
                SET v_stage = 'station product issue base v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_product_issue_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S23 连接产品问题价格基础结果与7天测试指标';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2816,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_product_issue_base AS
                SELECT x.*,
                       t.test_7d_end_date,
                       t.test_elapsed_days,
                       t.test_7d_sales_qty,
                       t.test_7d_daily_sales,
                       CASE
                           WHEN x.first_10pct_test_date IS NULL THEN '未测试'
                           WHEN DATEDIFF(v_data_date, x.first_10pct_test_date) + 1 < 7 THEN '未完成测试'
                           ELSE '已完成7天测试'
                       END AS ten_pct_price_test_status,
                       CASE
                           WHEN x.station_sales_role = '明星产品(站点)'
                               THEN '明星产品（站点）-保持'
                           WHEN x.station_sales_role = '潜力产品(站点)'
                            AND x.small_rank BETWEEN 1 AND 50
                            AND ((x.daily_sales > 3 AND x.order_margin_rate BETWEEN 0.05 AND 0.15)
                              OR (x.daily_sales BETWEEN 1 AND 3 AND x.order_margin_rate BETWEEN 0.10 AND 0.15))
                               THEN '潜力产品（站点）-提升毛利'
                           WHEN x.station_sales_role = '潜力产品(站点)'
                            AND (x.small_rank BETWEEN 51 AND 100
                              OR (x.small_rank BETWEEN 1 AND 50
                              AND x.daily_sales BETWEEN 1 AND 3
                              AND x.order_margin_rate > 0.15
                              AND x.order_margin_rate <= 0.25))
                               THEN '潜力产品（站点）-提升销量'
                           WHEN x.station_sales_role = '瘦狗产品(站点)'
                            AND x.daily_sales > 1
                            AND x.order_margin_rate < 0.05
                               THEN '瘦狗产品（站点）-提升毛利'
                           WHEN x.station_sales_role = '瘦狗产品(站点)'
                            AND x.daily_sales BETWEEN 1 AND 3
                            AND x.order_margin_rate >= 0.05
                            AND x.order_margin_rate < 0.10
                            AND x.small_rank BETWEEN 1 AND 100
                               THEN '瘦狗产品（站点）-提升毛利'
                           WHEN x.station_sales_role = '瘦狗产品(站点)'
                            AND x.daily_sales > 1
                            AND x.order_margin_rate >= 0.05
                            AND (x.small_rank IS NULL OR x.small_rank = 0 OR x.small_rank = 99999)
                               THEN '瘦狗产品（站点）-提升销量'
                           WHEN x.station_sales_role = '瘦狗产品(站点)'
                            AND ((x.daily_sales > 0 AND x.daily_sales < 1
                              AND x.order_margin_rate >= 0.05
                              AND x.small_rank BETWEEN 1 AND 100)
                              OR (x.daily_sales > 0
                              AND x.order_margin_rate >= 0.05
                              AND x.small_rank > 100
                              AND x.small_rank <> 99999))
                               THEN '瘦狗产品（站点）-提升销量'
                           WHEN x.station_sales_role = '问题产品(站点)'
                            AND x.daily_sales > 0
                            AND x.order_margin_rate < 0.05
                               THEN '问题产品（站点）-提升毛利'
                           WHEN x.station_sales_role = '问题产品(站点)'
                            AND (x.daily_sales = 0
                              OR (x.daily_sales > 0
                              AND x.order_margin_rate >= 0.05
                              AND (x.small_rank IS NULL OR x.small_rank = 0 OR x.small_rank = 99999)))
                               THEN '问题产品（站点）-提升销量'
                       END AS issue_label
                FROM tmp_station_product_issue_price_base x
                LEFT JOIN tmp_station_10pct_test_7d_metrics t
                  ON t.country_category = x.country_category
                 AND t.country = x.country
                 AND t.store = x.store
                 AND t.msku = x.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_product_issue_base
                    ADD INDEX idx_station_product_issue_base (country_category, country, store, msku, label_period),
                    ADD INDEX idx_station_product_issue_label (issue_label);
                DROP TEMPORARY TABLE IF EXISTS tmp_station_product_issue_price_base;

                SET v_stage = 'station product issue evidence v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_product_issue;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S24 生成站点产品问题evidence_json';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2870,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_product_issue AS
                SELECT b.country_category, b.country, b.store, b.msku, b.label_period, b.issue_label,
                       JSON_OBJECT(
                           'evidence_schema_version','1.3',
                           'rule_version','20260819_seven_strategy_labels',
                           'label',b.issue_label,
                           'benchmark_target',CASE b.station_sales_role
                               WHEN '明星产品(站点)' THEN '保持站点明星'
                               WHEN '潜力产品(站点)' THEN '站点明星'
                               WHEN '瘦狗产品(站点)' THEN '站点潜力'
                               WHEN '问题产品(站点)' THEN '退出问题产品'
                           END,
                           'metrics_used',JSON_OBJECT(
                               'daily_sales',ROUND(b.daily_sales,4),
                               'order_margin_rate',ROUND(100 * b.order_margin_rate,4),
                               'small_rank',ROUND(b.small_rank,4)
                           ),
                           'matched_rule',JSON_OBJECT(
                               'station_sales_role',b.station_sales_role,
                               'condition',CASE b.issue_label
                                   WHEN '明星产品（站点）-保持' THEN '站点销售角色=明星产品(站点)'
                                   WHEN '潜力产品（站点）-提升毛利' THEN '站点销售角色=潜力产品(站点)，小类排名1-50，且（日销>3、订单毛利率5%-15%，或1<=日销<=3、订单毛利率10%-15%）'
                                   WHEN '潜力产品（站点）-提升销量' THEN '站点销售角色=潜力产品(站点)，且（小类排名51-100，或小类排名1-50、1<=日销<=3、15%<订单毛利率<=25%）'
                                    WHEN '瘦狗产品（站点）-提升毛利' THEN '站点销售角色=瘦狗产品(站点)，且（小类排名1-100、1<=日销<=3、5%<=订单毛利率<10%，或日销>1且订单毛利率<5%）'
                                    WHEN '瘦狗产品（站点）-提升销量' THEN '站点销售角色=瘦狗产品(站点)，且（小类排名1-100、0<日销<1、订单毛利率>=5%，或小类排名>100且不等于99999、日销>0、订单毛利率>=5%，或日销>1且订单毛利率>=5%、小类排名为空/0/99999）'
                                    WHEN '问题产品（站点）-提升毛利' THEN '站点销售角色=问题产品(站点)，0<日销<=1且订单毛利率<5%'
                                    WHEN '问题产品（站点）-提升销量' THEN '站点销售角色=问题产品(站点)，且（日销=0，或0<日销<=1、订单毛利率>=5%、小类排名为空/0/99999）'
                               END
                           ),
                           'strategy_advice',CASE b.issue_label
                               WHEN '明星产品（站点）-保持' THEN '保持当前价格和有效广告投入'
                               WHEN '潜力产品（站点）-提升毛利' THEN '涨价＋控制广告或其他成本投入'
                               WHEN '潜力产品（站点）-提升销量' THEN '降价＋投入广告'
                               WHEN '瘦狗产品（站点）-提升毛利' THEN '涨价＋控制广告或其他成本投入'
                               WHEN '瘦狗产品（站点）-提升销量' THEN '降价＋投入广告'
                               WHEN '问题产品（站点）-提升毛利' THEN '涨价＋控制广告或其他成本投入'
                               WHEN '问题产品（站点）-提升销量' THEN '降价＋投入广告'
                           END
                       ) AS product_issue_json
                FROM tmp_station_product_issue_base b;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_product_issue
                    ADD INDEX idx_station_product_issue (country_category, country, store, msku, label_period);


                -- 标签17直接复用标签3“运营状态”结果：国家类别+店铺+MSKU只有一个运营状态，再展开到各国家。
                SET v_stage = 'station operation status from label3 v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_operation_status;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S25 读取国家类别运营状态';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 2994,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_operation_status AS
                SELECT t.`country_category` COLLATE utf8mb4_0900_ai_ci AS country_category,
                       t.`store` COLLATE utf8mb4_0900_ai_ci AS store,
                       t.`msku` COLLATE utf8mb4_0900_ai_ci AS msku,
                       MAX(d.`sub_label_name`) COLLATE utf8mb4_0900_ai_ci AS operation_status
                FROM `dws_datasync`.`dws_标签表` t
                JOIN `dws_datasync`.`dws_标签详情表` d
                  ON d.`sub_label_id` = t.`label_id`
                 AND d.`label_id` = 3
                WHERE t.`data_date` = v_data_date
                  AND t.`country` IS NULL
                GROUP BY t.`country_category`, t.`store`, t.`msku`;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_operation_status
                    ADD INDEX idx_station_operation_status (country_category, store, msku);

                -- ========================================================================
                -- V47：标签17“运营状态-策略建议标签（站点）”计算层。
                -- 返厂D3采用返厂日为D0、D3为first_restock_date+3天；断货前原日销采用断货日前3天平均站点销量。
                -- “已执行降档+acos约5%”按每日定价快照中价格低于断货前价格且近30天ACOAS>=5%推导。
                -- ========================================================================
                SET v_stage = 'station return d3 metrics v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_return_d3_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S26 计算返厂D3基础指标';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3013,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_return_d3_base AS
                SELECT k.country_category, k.country, k.store, k.msku,
                       r.oos_start_date, r.first_restock_date,
                       DATEDIFF(v_data_date, r.first_restock_date) AS return_day_d0,
                       SUM(CASE WHEN ps.stat_date BETWEEN DATE_SUB(r.oos_start_date, INTERVAL 3 DAY)
                                                        AND DATE_SUB(r.oos_start_date, INTERVAL 1 DAY)
                                THEN COALESCE(ps.volume,0) ELSE 0 END) / 3.0 AS pre_oos_original_daily_sales,
                       SUM(CASE WHEN ps.stat_date = DATE_ADD(r.first_restock_date, INTERVAL 3 DAY)
                                THEN COALESCE(ps.volume,0) ELSE 0 END) AS return_d3_daily_sales,
                       MAX(CASE WHEN ps.stat_date = DATE_ADD(r.first_restock_date, INTERVAL 3 DAY)
                                     AND ps.source_country IS NOT NULL THEN 1 ELSE 0 END) AS has_return_d3_data
                FROM tmp_station_listing_keys k
                JOIN tmp_return r
                  ON r.country_category = k.country_category
                 AND r.store = k.store
                 AND r.msku = k.msku
                LEFT JOIN tmp_perf_scoped ps
                  ON ps.country_category = k.country_category
                 AND ps.source_country = k.country
                 AND ps.perf_store = k.store
                 AND ps.perf_msku = k.msku
                 AND ps.stat_date BETWEEN DATE_SUB(r.oos_start_date, INTERVAL 3 DAY)
                                      AND DATE_ADD(r.first_restock_date, INTERVAL 3 DAY)
                GROUP BY k.country_category, k.country, k.store, k.msku,
                         r.oos_start_date, r.first_restock_date;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_return_d3_base
                    ADD INDEX idx_station_return_d3_base (country_category, country, store, msku);

                -- S20和S26均已完成，释放复用的产品表现临时表。
                SET v_stage = 'tmp_perf_scoped_cleanup_after_station_volume_use';
                DROP TEMPORARY TABLE IF EXISTS tmp_perf_scoped;

                DROP TEMPORARY TABLE IF EXISTS tmp_station_return_d3_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S27 计算返厂D3恢复率';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3046,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_return_d3_metrics AS
                SELECT b.*,
                       CASE
                           WHEN b.return_day_d0 >= 3
                            AND b.has_return_d3_data = 1
                            AND b.pre_oos_original_daily_sales > 0
                               THEN b.return_d3_daily_sales / b.pre_oos_original_daily_sales
                       END AS return_d3_recovery_rate
                FROM tmp_station_return_d3_base b;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_return_d3_metrics
                    ADD INDEX idx_station_return_d3_metrics (country_category, country, store, msku);

                SET v_stage = 'station return price adjustment v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_pre_return_price_date;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S28 提取返场前价格日期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3060,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_pre_return_price_date AS
                SELECT r.country_category, r.country, r.store, r.msku,
                       r.oos_start_date, r.first_restock_date,
                       MAX(d.stat_date) AS pre_return_price_date
                FROM tmp_station_return_d3_metrics r
                LEFT JOIN tmp_station_price_daily d
                  ON d.country_category = r.country_category
                 AND d.country = r.country
                 AND d.store = r.store
                 AND d.msku = r.msku
                 AND d.stat_date <= r.oos_start_date
                GROUP BY r.country_category, r.country, r.store, r.msku,
                         r.oos_start_date, r.first_restock_date;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_pre_return_price_date
                    ADD INDEX idx_station_pre_return_price_date (country_category, country, store, msku, pre_return_price_date);

                DROP TEMPORARY TABLE IF EXISTS tmp_station_pre_return_price;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S29 提取返场前Listing价格';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3077,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_pre_return_price AS
                SELECT x.country_category, x.country, x.store, x.msku,
                       x.oos_start_date, x.first_restock_date, x.pre_return_price_date,
                       MAX(d.listing_price) AS pre_return_listing_price
                FROM tmp_station_pre_return_price_date x
                LEFT JOIN tmp_station_price_daily d
                  ON d.country_category = x.country_category
                 AND d.country = x.country
                 AND d.store = x.store
                 AND d.msku = x.msku
                 AND d.stat_date = x.pre_return_price_date
                GROUP BY x.country_category, x.country, x.store, x.msku,
                         x.oos_start_date, x.first_restock_date, x.pre_return_price_date;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_pre_return_price
                    ADD INDEX idx_station_pre_return_price (country_category, country, store, msku);

                -- S28拆分第一步：返厂D3指标只连接返场前价格。
                SET v_stage = 'station return adjust price base v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_return_adjust_price_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S30 连接返厂D3指标与返场前价格';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3096,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_return_adjust_price_base AS
                SELECT r.country_category, r.country, r.store, r.msku,
                       r.first_restock_date,
                       p.pre_return_price_date,
                       p.pre_return_listing_price
                FROM tmp_station_return_d3_metrics r
                LEFT JOIN tmp_station_pre_return_price p
                  ON p.country_category = r.country_category
                 AND p.country = r.country
                 AND p.store = r.store
                 AND p.msku = r.msku;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_return_adjust_price_base
                    ADD INDEX idx_station_return_adjust_price_base (country_category, country, store, msku);

                -- S28拆分第二步：使用第一步结果连接定价每日快照并计算返场后的调价状态。
                SET v_stage = 'station return adjust status v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_return_adjust_status;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S31 连接返场调价价格基础结果与定价快照';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3113,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_return_adjust_status AS
                SELECT x.country_category, x.country, x.store, x.msku,
                       x.pre_return_price_date, x.pre_return_listing_price,
                       MIN(CASE WHEN d.stat_date > DATE_ADD(x.first_restock_date, INTERVAL 3 DAY)
                                     AND x.pre_return_listing_price IS NOT NULL
                                     AND d.listing_price < x.pre_return_listing_price
                                     AND d.snapshot_acoas_rate >= 0.05
                                THEN d.stat_date END) AS first_return_price_acos5_adjust_date
                FROM tmp_station_return_adjust_price_base x
                LEFT JOIN tmp_station_price_daily d
                  ON d.country_category = x.country_category
                 AND d.country = x.country
                 AND d.store = x.store
                 AND d.msku = x.msku
                 AND d.stat_date <= v_data_date
                GROUP BY x.country_category, x.country, x.store, x.msku,
                         x.pre_return_price_date, x.pre_return_listing_price;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_return_adjust_status
                    ADD INDEX idx_station_return_adjust_status (country_category, country, store, msku);
                DROP TEMPORARY TABLE IF EXISTS tmp_station_return_adjust_price_base;

                SET v_stage = 'station operation strategy base v47';
                DROP TEMPORARY TABLE IF EXISTS tmp_station_operation_strategy_base;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S32 生成站点运营策略基础数据';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3136,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_station_operation_strategy_base AS
                SELECT z.*,
                       CASE
                           WHEN z.operation_status IS NULL THEN 1710
                           WHEN z.operation_status = '返厂品'
                            AND (z.first_restock_date IS NULL OR z.oos_start_date IS NULL
                                 OR z.pre_oos_original_daily_sales IS NULL OR z.pre_oos_original_daily_sales <= 0)
                               THEN 1709
                           WHEN z.operation_status = '返厂品' AND z.return_day_d0 BETWEEN 0 AND 2 THEN 1705
                           WHEN z.operation_status = '返厂品' AND z.return_day_d0 >= 3
                            AND (z.has_return_d3_data = 0 OR z.return_d3_daily_sales IS NULL OR z.return_d3_recovery_rate IS NULL)
                               THEN 1709
                           WHEN z.operation_status = '返厂品' AND z.return_d3_recovery_rate >= 0.70 THEN 1706
                           WHEN z.operation_status = '返厂品' AND z.return_d3_recovery_rate < 0.70
                            AND (z.order_margin_rate IS NULL OR z.acoas_rate IS NULL)
                               THEN 1710
                           WHEN z.operation_status = '返厂品' AND z.return_d3_recovery_rate < 0.70
                            AND (z.order_margin_rate <= 0.10
                                 OR (z.first_return_price_acos5_adjust_date IS NOT NULL
                                     AND DATEDIFF(v_data_date,z.first_return_price_acos5_adjust_date)+1 >= z.period_days))
                               THEN 1708
                           WHEN z.operation_status = '返厂品' AND z.return_d3_recovery_rate < 0.70
                            AND z.order_margin_rate > 0.10 THEN 1707
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days IS NULL THEN 1710
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days BETWEEN 1 AND 7
                            AND (z.latest_listing_price IS NULL
                                 OR z.five_pct_target_price IS NULL
                                 OR z.fifteen_pct_target_price IS NULL) THEN 1710
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days BETWEEN 1 AND 7
                            AND z.latest_listing_price >= z.five_pct_target_price
                            AND z.latest_listing_price <= z.fifteen_pct_target_price THEN 1701
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days > 7
                            AND (z.daily_sales IS NULL OR z.order_margin_rate IS NULL OR z.acoas_rate IS NULL)
                               THEN 1710
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days > 7
                            AND z.issue_label LIKE '问题产品（站点）-%'
                            AND z.daily_sales >= 1 THEN 1702
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days > 7
                            AND z.issue_label LIKE '问题产品（站点）-%'
                            AND z.daily_sales >= 0 AND z.daily_sales < 1
                            AND z.first_10pct_acos5_date IS NOT NULL
                            AND DATEDIFF(v_data_date,z.first_10pct_acos5_date)+1 >= z.period_days THEN 1704
                           WHEN z.operation_status = '测款扶持'
                            AND z.test_support_days > 7
                            AND z.issue_label LIKE '问题产品（站点）-%'
                            AND z.daily_sales >= 0 AND z.daily_sales < 1 THEN 1703
                       END AS strategy_sub_label_id
                FROM (
                    SELECT p.*,
                           i.issue_label, i.ten_pct_price_test_status,
                           i.price_history_start_date, i.first_10pct_test_date, i.first_10pct_acos5_date,
                           lp.target_stat_date AS latest_price_stat_date,
                           lp.listing_price AS latest_listing_price,
                           lp.five_pct_target_price,
                           lp.ten_pct_target_price AS latest_ten_pct_target_price,
                           lp.fifteen_pct_target_price,
                           CASE WHEN lp.listing_price IS NOT NULL
                                      AND lp.five_pct_target_price IS NOT NULL
                                      AND lp.fifteen_pct_target_price IS NOT NULL
                                      AND lp.listing_price >= lp.five_pct_target_price
                                      AND lp.listing_price <= lp.fifteen_pct_target_price
                                    THEN 1 ELSE 0 END AS listing_price_in_5_15_band,
                           fr.first_receiving_date,
                           CASE WHEN fr.first_receiving_date IS NULL THEN NULL
                                ELSE DATEDIFF(v_data_date,fr.first_receiving_date)+1 END AS test_support_days,
                           os.operation_status,
                           rd.oos_start_date, rd.first_restock_date, rd.return_day_d0,
                           rd.pre_oos_original_daily_sales, rd.return_d3_daily_sales,
                           rd.has_return_d3_data, rd.return_d3_recovery_rate,
                           ra.pre_return_price_date, ra.pre_return_listing_price,
                           ra.first_return_price_acos5_adjust_date
                    FROM tmp_station_period_metrics p
                    LEFT JOIN tmp_station_product_issue_base i
                      ON i.country_category = p.country_category
                     AND i.country = p.country AND i.store = p.store AND i.msku = p.msku
                     AND i.label_period = p.label_period
                    LEFT JOIN tmp_station_first_receiving fr
                      ON fr.country_category = p.country_category
                     AND fr.country = p.country AND fr.store = p.store AND fr.msku = p.msku
                    LEFT JOIN tmp_station_operation_status os
                      ON os.country_category = p.country_category
                     AND os.store = p.store AND os.msku = p.msku
                    LEFT JOIN tmp_station_10pct_target_latest lp
                      ON lp.country_category = p.country_category
                     AND lp.country = p.country
                     AND lp.store = p.store
                     AND lp.msku = p.msku
                    LEFT JOIN tmp_station_return_d3_metrics rd
                      ON rd.country_category = p.country_category
                     AND rd.country = p.country AND rd.store = p.store AND rd.msku = p.msku
                    LEFT JOIN tmp_station_return_adjust_status ra
                      ON ra.country_category = p.country_category
                     AND ra.country = p.country AND ra.store = p.store AND ra.msku = p.msku
                ) z;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_station_operation_strategy_base
                    ADD INDEX idx_station_operation_strategy_base (country_category, country, store, msku, label_period, strategy_sub_label_id);


                -- ========================================================================
                -- 标签18/19广告标签：产品表现表作为商品维度主表，不依赖Listing商品池。
                -- 正常每日执行时以当前日期D-2为指标截止日；手工回补历史日期时不晚于指定业务日期。
                -- 标签18、标签19均使用截止日近7天；标签19在同一7天窗口内汇总五个主要站点广告覆盖。
                -- ========================================================================
                SET v_ad_window_end = LEAST(v_data_date, DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY));
                SET v_ad_7d_start = DATE_SUB(v_ad_window_end, INTERVAL 6 DAY);

                SET v_stage = 'ad labels product performance daily';
                DROP TEMPORARY TABLE IF EXISTS tmp_ad_perf_daily;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S33 生成广告标签产品表现日表';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_ad_perf_daily AS
                SELECT CASE
                           WHEN CAST(p.`country` AS CHAR) = '英国' THEN '英国站'
                           WHEN CAST(p.`country` AS CHAR) IN ('美国', '加拿大', '巴西', '墨西哥') THEN '北美站'
                           ELSE '欧洲站'
                       END AS country_category,
                       CAST(p.`country` AS CHAR(100)) AS country,
                       CAST(CASE
                           WHEN LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) > 0
                               THEN LEFT(
                                   SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1),
                                   LOCATE('-', SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)) - 1
                               )
                           ELSE SUBSTRING_INDEX(CAST(p.`seller_name` AS CHAR), ' ', 1)
                       END AS CHAR(100)) AS store,
                       CAST(p.`seller_sku` AS CHAR(255)) AS msku,
                       DATE(p.`start_date`) AS stat_date,
                       CASE WHEN COUNT(p.`amount`) = COUNT(*) THEN SUM(p.`amount`) ELSE NULL END AS sales_amount,
                       CASE WHEN COUNT(p.`spend`) = COUNT(*) THEN SUM(p.`spend`) ELSE NULL END AS ad_spend,
                       CASE WHEN COUNT(p.`ad_sales_amount`) = COUNT(*) THEN SUM(p.`ad_sales_amount`) ELSE NULL END AS ad_attributed_sales,
                       COUNT(*) AS source_row_count
                FROM `dwd_datasync`.`lx_statistics_product_performance` p
                WHERE p.`start_date` >= DATE_FORMAT(v_ad_7d_start, '%Y-%m-%d')
                  AND p.`start_date` < DATE_FORMAT(DATE_ADD(v_ad_window_end, INTERVAL 1 DAY), '%Y-%m-%d')
                  AND p.`seller_sku` IS NOT NULL
                  AND TRIM(CAST(p.`seller_sku` AS CHAR)) <> ''
                  AND LOWER(TRIM(CAST(p.`seller_sku` AS CHAR))) NOT LIKE 'amzn.gr%'
                  AND LOWER(TRIM(CAST(p.`seller_sku` AS CHAR))) NOT LIKE 'amazon%'
                GROUP BY 1, 2, 3, 4, 5;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_ad_perf_daily
                    ADD INDEX idx_ad_perf_daily_key_date (country, store, msku, stat_date),
                    ADD INDEX idx_ad_perf_daily_product_date (store, msku, stat_date);

                SET v_stage = 'label18 metrics';
                DROP TEMPORARY TABLE IF EXISTS tmp_ad_18_metrics;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S34 计算标签18广告投放效果';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_ad_18_metrics AS
                SELECT r.*,
                       CASE
                           WHEN r.sales_amount IS NULL OR r.sales_amount <= 0 OR r.ad_spend IS NULL THEN 1801
                           WHEN r.ad_spend > 0 AND (r.ad_attributed_sales IS NULL OR r.ad_attributed_sales <= 0) THEN 1802
                           WHEN r.tacos >= 25 THEN 1803
                           WHEN r.acos >= 60 THEN 1804
                           WHEN r.ad_sales_share >= 50 THEN 1805
                           WHEN r.tacos < 4.8 THEN 1806
                           WHEN r.tacos BETWEEN 4.8 AND 5.2
                            AND r.acos BETWEEN 8 AND 10 THEN 1807
                           WHEN r.acos <= 20 THEN 1808
                           ELSE 1809
                       END AS sub_label_id
                FROM (
                    SELECT m.*,
                           CASE WHEN m.sales_amount > 0 AND m.ad_spend IS NOT NULL
                                THEN m.ad_spend / m.sales_amount * 100 END AS tacos,
                           CASE WHEN m.ad_attributed_sales > 0 AND m.ad_spend IS NOT NULL
                                THEN m.ad_spend / m.ad_attributed_sales * 100 END AS acos,
                           CASE WHEN m.sales_amount > 0 AND m.ad_attributed_sales IS NOT NULL
                                THEN m.ad_attributed_sales / m.sales_amount * 100 END AS ad_sales_share
                    FROM (
                        SELECT d.country_category,
                               d.country,
                               d.store,
                               d.msku,
                               CASE WHEN SUM(d.sales_amount IS NULL) > 0 THEN NULL ELSE SUM(d.sales_amount) END AS sales_amount,
                               CASE WHEN SUM(d.ad_spend IS NULL) > 0 THEN NULL ELSE SUM(d.ad_spend) END AS ad_spend,
                               CASE WHEN SUM(d.ad_attributed_sales IS NULL) > 0 THEN NULL ELSE SUM(d.ad_attributed_sales) END AS ad_attributed_sales,
                               COUNT(*) AS source_day_count,
                               SUM(d.source_row_count) AS source_row_count
                        FROM tmp_ad_perf_daily d
                        WHERE d.stat_date BETWEEN v_ad_7d_start AND v_ad_window_end
                        GROUP BY d.country_category, d.country, d.store, d.msku
                    ) m
                ) r;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_ad_18_metrics
                    ADD INDEX idx_ad_18_metrics (country, store, msku, sub_label_id);

                SET v_stage = 'label19 output keys';
                DROP TEMPORARY TABLE IF EXISTS tmp_ad_19_output_keys;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S35 生成标签19近7天输出商品键';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_ad_19_output_keys AS
                SELECT DISTINCT d.country_category, d.country, d.store, d.msku
                FROM tmp_ad_perf_daily d
                WHERE d.stat_date BETWEEN v_ad_7d_start AND v_ad_window_end
                  AND d.country IN ('德国', '法国', '意大利', '西班牙', '荷兰');
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_ad_19_output_keys
                    ADD INDEX idx_ad_19_output_keys (country, store, msku),
                    ADD INDEX idx_ad_19_output_product (store, msku);

                SET v_stage = 'label19 site status';
                DROP TEMPORARY TABLE IF EXISTS tmp_ad_19_site_status;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S36 计算标签19五站广告状态';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_ad_19_site_status AS
                SELECT k.store,
                       k.msku,
                       s.country,
                       CASE
                           WHEN COUNT(d.stat_date) = 0 OR SUM(d.ad_spend IS NULL) > 0 THEN '数据缺失'
                           WHEN SUM(d.ad_spend) > 0 THEN '已投入广告'
                           WHEN SUM(d.ad_spend) = 0 THEN '未投入广告'
                           ELSE '数据缺失'
                       END AS site_ad_status,
                       CASE
                           WHEN COUNT(d.stat_date) = 0 OR SUM(d.ad_spend IS NULL) > 0 THEN NULL
                           ELSE SUM(d.ad_spend)
                       END AS ad_spend_7d,
                       COUNT(d.stat_date) AS source_day_count
                FROM (
                    SELECT DISTINCT store, msku
                    FROM tmp_ad_19_output_keys
                ) k
                CROSS JOIN (
                    SELECT '德国' AS country
                    UNION ALL SELECT '法国'
                    UNION ALL SELECT '意大利'
                    UNION ALL SELECT '西班牙'
                    UNION ALL SELECT '荷兰'
                ) s
                LEFT JOIN tmp_ad_perf_daily d
                  ON d.store = k.store
                 AND d.msku = k.msku
                 AND d.country = s.country
                 AND d.stat_date BETWEEN v_ad_7d_start AND v_ad_window_end
                GROUP BY k.store, k.msku, s.country;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_ad_19_site_status
                    ADD INDEX idx_ad_19_site_status (store, msku, country);

                SET v_stage = 'label19 coverage';
                DROP TEMPORARY TABLE IF EXISTS tmp_ad_19_coverage;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S37 汇总标签19五站覆盖结果';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                CREATE TEMPORARY TABLE tmp_ad_19_coverage AS
                SELECT c.*,
                       CASE
                           WHEN c.missing_site_count > 0 THEN 1901
                           WHEN c.invested_site_count = 5 THEN 1902
                           WHEN c.not_invested_site_count = 5 THEN 1903
                           ELSE 1904
                       END AS sub_label_id
                FROM (
                    SELECT s.store,
                           s.msku,
                           SUM(s.site_ad_status = '已投入广告') AS invested_site_count,
                           SUM(s.site_ad_status = '未投入广告') AS not_invested_site_count,
                           SUM(s.site_ad_status = '数据缺失') AS missing_site_count,
                           MAX(CASE WHEN s.country = '德国' THEN s.site_ad_status END) AS germany_status,
                           MAX(CASE WHEN s.country = '法国' THEN s.site_ad_status END) AS france_status,
                           MAX(CASE WHEN s.country = '意大利' THEN s.site_ad_status END) AS italy_status,
                           MAX(CASE WHEN s.country = '西班牙' THEN s.site_ad_status END) AS spain_status,
                           MAX(CASE WHEN s.country = '荷兰' THEN s.site_ad_status END) AS netherlands_status,
                           MAX(CASE WHEN s.country = '德国' THEN s.ad_spend_7d END) AS germany_ad_spend,
                           MAX(CASE WHEN s.country = '法国' THEN s.ad_spend_7d END) AS france_ad_spend,
                           MAX(CASE WHEN s.country = '意大利' THEN s.ad_spend_7d END) AS italy_ad_spend,
                           MAX(CASE WHEN s.country = '西班牙' THEN s.ad_spend_7d END) AS spain_ad_spend,
                           MAX(CASE WHEN s.country = '荷兰' THEN s.ad_spend_7d END) AS netherlands_ad_spend,
                           MAX(CASE WHEN s.country = '德国' THEN s.source_day_count END) AS germany_source_days,
                           MAX(CASE WHEN s.country = '法国' THEN s.source_day_count END) AS france_source_days,
                           MAX(CASE WHEN s.country = '意大利' THEN s.source_day_count END) AS italy_source_days,
                           MAX(CASE WHEN s.country = '西班牙' THEN s.source_day_count END) AS spain_source_days,
                           MAX(CASE WHEN s.country = '荷兰' THEN s.source_day_count END) AS netherlands_source_days
                    FROM tmp_ad_19_site_status s
                    GROUP BY s.store, s.msku
                ) c;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_ad_19_coverage
                    ADD INDEX idx_ad_19_coverage (store, msku, sub_label_id);

                -- 标签23从2026-09-04更新的2026-09-03业务数据开始累计。主标签表仅保留近两天，因此在删除当前日重跑数据前，
                -- 先读取前一日标签23的角色与累计值；两个维度使用独立业务键，不互相续接。
                SET v_stage = 'sales role 30d continuous previous snapshot';
                DROP TEMPORARY TABLE IF EXISTS tmp_sales_role_30d_prev;
                CREATE TEMPORARY TABLE tmp_sales_role_30d_prev (
                    dimension_type VARCHAR(40) NOT NULL,
                    country_category VARCHAR(20) NOT NULL,
                    country VARCHAR(100) NOT NULL DEFAULT '',
                    store VARCHAR(100) NOT NULL,
                    msku VARCHAR(255) NOT NULL,
                    current_role_label_id INT NOT NULL,
                    continuous_count INT NOT NULL,
                    continuous_start_date DATE NOT NULL,
                    PRIMARY KEY (dimension_type, country_category, country, store, msku)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

                INSERT IGNORE INTO tmp_sales_role_30d_prev
                    (dimension_type, country_category, country, store, msku,
                     current_role_label_id, continuous_count, continuous_start_date)
                SELECT CASE WHEN t.country IS NULL
                                THEN 'country_category+store+msku'
                            ELSE 'country+store+msku' END,
                       CAST(t.country_category AS CHAR(20)),
                       COALESCE(CAST(t.country AS CHAR(100)), ''),
                       CAST(t.store AS CHAR(100)),
                       CAST(t.msku AS CHAR(255)),
                       CAST(JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                      '$.current_sales_role.sub_label_id')) AS UNSIGNED),
                       CAST(JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                      '$.continuous_count')) AS UNSIGNED),
                       STR_TO_DATE(JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                             '$.continuous_start_date')), '%Y-%m-%d')
                FROM `dws_datasync`.`dws_标签表` t
                WHERE v_data_date > DATE('2026-09-03')
                  AND t.data_date = DATE_SUB(v_data_date, INTERVAL 1 DAY)
                  AND t.label_id = 2301
                  AND t.label_period = '30d'
                  AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                '$.current_sales_role.sub_label_id')) REGEXP '^[0-9]+$'
                  AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                '$.continuous_count')) REGEXP '^[0-9]+$'
                  AND JSON_UNQUOTE(JSON_EXTRACT(t.evidence_json,
                                                '$.continuous_start_date')) REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$';

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

                -- 将本次新计算结果并入运行期JSON复用临时集；唯一键保证同一维度、同一轮断货、同一周期只保留一次。
                INSERT IGNORE INTO tmp_pre_oos_json_reuse
                    (`dimension_type`,`country_category`,`country`,`store`,`msku`,`oos_start_date`,
                     `label_period`,`label_id`,`evidence_json`,`first_calculated_data_date`)
                SELECT dimension_type,country_category,country,store,msku,oos_start_date,
                       label_period,label_id,evidence_json,first_calculated_data_date
                FROM tmp_pre_oos_category_pending;

                INSERT IGNORE INTO tmp_pre_oos_json_reuse
                    (`dimension_type`,`country_category`,`country`,`store`,`msku`,`oos_start_date`,
                     `label_period`,`label_id`,`evidence_json`,`first_calculated_data_date`)
                SELECT dimension_type,country_category,country,store,msku,oos_start_date,
                       label_period,label_id,evidence_json,first_calculated_data_date
                FROM tmp_pre_oos_station_pending;

                -- 当前仍断货时从历史JSON/本次计算临时集写入主标签表；已有轮次不重新计算历史窗口。
                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`,`country_category`,`country`,`store`,`msku`,
                     `label_id`,`label_period`,`created_time`,`evidence_json`)
                SELECT v_data_date,
                       c.country_category,
                       NULL,
                       c.store,
                       c.msku,
                       c.label_id,
                       c.label_period,
                       NOW(),
                       JSON_SET(
                           c.evidence_json,
                           '$.oos.current_operation_status','断货中',
                           '$.oos.current_status_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                           '$.oos.current_fba_available',t.current_fba_available,
                           '$.oos.current_fba_in_transit',t.current_fba_in_transit,
                           '$.oos.current_local_quantity',t.current_local_quantity
                       )
                FROM tmp_pre_oos_json_reuse c
                JOIN tmp_pre_oos_category_targets t
                  ON c.dimension_type = 'country_category'
                 AND c.country_category = t.country_category
                 AND c.country = ''
                 AND c.store = t.store
                 AND c.msku = t.MSKU
                 AND c.oos_start_date = t.oos_start_date
                JOIN tmp_station_active_labels l
                  ON l.sub_label_id = c.label_id
                 AND l.label_name = '断货前销售角色';
                SET v_record_count = v_record_count + ROW_COUNT();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`,`country_category`,`country`,`store`,`msku`,
                     `label_id`,`label_period`,`created_time`,`evidence_json`)
                SELECT v_data_date,
                       c.country_category,
                       c.country,
                       c.store,
                       c.msku,
                       c.label_id,
                       c.label_period,
                       NOW(),
                       JSON_SET(
                           c.evidence_json,
                           '$.oos.current_operation_status','断货中',
                           '$.oos.current_status_data_date',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                           '$.oos.current_fba_available',t.current_fba_available,
                           '$.oos.current_fba_in_transit',t.current_fba_in_transit,
                           '$.oos.current_local_quantity',t.current_local_quantity
                       )
                FROM tmp_pre_oos_json_reuse c
                JOIN tmp_pre_oos_station_targets t
                  ON c.dimension_type = 'country'
                 AND c.country_category = t.country_category
                 AND c.country = t.country
                 AND c.store = t.store
                 AND c.msku = t.msku
                 AND c.oos_start_date = t.oos_start_date
                JOIN tmp_station_active_labels l
                  ON l.sub_label_id = c.label_id
                 AND l.label_name = '断货前销售角色(站点)';
                SET v_record_count = v_record_count + ROW_COUNT();

                -- 标签20/21已写入，当次JSON复用临时集不再需要。
                DROP TEMPORARY TABLE IF EXISTS tmp_pre_oos_json_reuse;

                -- 站点销售角色按 7/14/30/90d 分别落表；证据仅在最终写入时构造，保留实际使用的销量、毛利率、小类排名和命中规则。
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S38 写入站点销售角色7d';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3255,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '7d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v47_station_role_20260819','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_7d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','7d','days',7),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_7d,4),'daily_sales',ROUND(m.volume_7d / 7.0,4),
                               'sales_amount',ROUND(m.sales_amount_7d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_7d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_7d,4),'small_rank',m.small_rank_7d,'small_rank_stat_date',DATE_FORMAT(m.latest_rank_date_7d,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.role_7d,
                               'condition',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 = 0
                                       THEN '日销=0'
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 > 0 AND m.margin_rate_7d < 0.05
                                       THEN '日销>0且毛利率<5%'
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 > 0 AND m.margin_rate_7d >= 0.05
                                    AND (m.small_rank_7d IS NULL OR m.small_rank_7d = 0 OR m.small_rank_7d = 99999)
                                       THEN '日销>0、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.role_7d = '明星产品(站点)' AND m.volume_7d / 7.0 > 3
                                       THEN '小类排名1-50，日销>3且毛利率>=15%'
                                   WHEN r.role_7d = '明星产品(站点)' AND m.volume_7d / 7.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-50，1<=日销<=3且毛利率>=25%'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100
                                       THEN '小类排名51-100，且满足明星产品的日销毛利条件'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.volume_7d / 7.0 > 3
                                       THEN '小类排名1-100，日销>3且5%<=毛利率<15%'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.volume_7d / 7.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且10%<=毛利率<25%'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d BETWEEN 1 AND 100
                                    AND m.volume_7d / 7.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且5%<=毛利率<10%'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d BETWEEN 1 AND 100
                                    AND m.volume_7d / 7.0 > 0 AND m.volume_7d / 7.0 < 1
                                       THEN '小类排名1-100，0<日销<1且毛利率>=5%'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d > 100 AND m.small_rank_7d <> 99999
                                       THEN '日销>0、毛利率>=5%，且小类排名>100且不等于99999'
                               END,
                               'daily_sales',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 = 0 THEN '= 0'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 > 3 THEN '> 3'
                                   WHEN r.role_7d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.volume_7d / 7.0 > 0 AND m.volume_7d / 7.0 < 1 THEN '> 0 AND < 1'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_7d IN ('问题产品(站点)','瘦狗产品(站点)') AND m.volume_7d / 7.0 > 0 THEN '> 0'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 = 0 THEN 'NOT_USED'
                                   WHEN r.role_7d = '问题产品(站点)' AND m.margin_rate_7d < 0.05 THEN '< 5%'
                                   WHEN r.role_7d = '问题产品(站点)' THEN '>= 5%'
                                   WHEN r.role_7d = '明星产品(站点)' AND m.volume_7d / 7.0 > 3 THEN '>= 15%'
                                   WHEN r.role_7d = '明星产品(站点)' AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN '>= 25%'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 AND m.volume_7d / 7.0 > 3 THEN '>= 15%'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 THEN '>= 25%'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.volume_7d / 7.0 > 3 THEN '>= 5% AND < 15%'
                                   WHEN r.role_7d = '潜力产品(站点)' THEN '>= 10% AND < 25%'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d BETWEEN 1 AND 100 AND m.volume_7d / 7.0 BETWEEN 1 AND 3 THEN '>= 5% AND < 10%'
                                   WHEN r.role_7d = '瘦狗产品(站点)' THEN '>= 5%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_7d = '问题产品(站点)' AND m.volume_7d / 7.0 > 0 AND m.margin_rate_7d >= 0.05
                                    AND (m.small_rank_7d IS NULL OR m.small_rank_7d = 0 OR m.small_rank_7d = 99999)
                                       THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.role_7d = '问题产品(站点)' THEN 'NOT_USED'
                                   WHEN r.role_7d = '明星产品(站点)' THEN 'BETWEEN 1 AND 50'
                                   WHEN r.role_7d = '潜力产品(站点)' AND m.small_rank_7d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_7d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_7d = '瘦狗产品(站点)' AND m.small_rank_7d BETWEEN 1 AND 100 THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_7d = '瘦狗产品(站点)' THEN '> 100 AND <> 99999'
                               END
                           ),
                            'product_issue',pi.product_issue_json
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_product_issue pi
                  ON pi.country_category = r.country_category
                 AND pi.country = r.country AND pi.store = r.store AND pi.msku = r.msku
                 AND pi.label_period = '7d'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_7d;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_select_affected_rows;

                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S39 写入站点销售角色14d';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3301,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '14d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v47_station_role_20260819','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_14d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','14d','days',14),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_14d,4),'daily_sales',ROUND(m.volume_14d / 14.0,4),
                               'sales_amount',ROUND(m.sales_amount_14d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_14d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_14d,4),'small_rank',m.small_rank_14d,'small_rank_stat_date',DATE_FORMAT(m.latest_rank_date_14d,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.role_14d,
                               'condition',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 = 0
                                       THEN '日销=0'
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 > 0 AND m.margin_rate_14d < 0.05
                                       THEN '日销>0且毛利率<5%'
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 > 0 AND m.margin_rate_14d >= 0.05
                                    AND (m.small_rank_14d IS NULL OR m.small_rank_14d = 0 OR m.small_rank_14d = 99999)
                                       THEN '日销>0、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.role_14d = '明星产品(站点)' AND m.volume_14d / 14.0 > 3
                                       THEN '小类排名1-50，日销>3且毛利率>=15%'
                                   WHEN r.role_14d = '明星产品(站点)' AND m.volume_14d / 14.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-50，1<=日销<=3且毛利率>=25%'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100
                                       THEN '小类排名51-100，且满足明星产品的日销毛利条件'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.volume_14d / 14.0 > 3
                                       THEN '小类排名1-100，日销>3且5%<=毛利率<15%'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.volume_14d / 14.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且10%<=毛利率<25%'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d BETWEEN 1 AND 100
                                    AND m.volume_14d / 14.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且5%<=毛利率<10%'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d BETWEEN 1 AND 100
                                    AND m.volume_14d / 14.0 > 0 AND m.volume_14d / 14.0 < 1
                                       THEN '小类排名1-100，0<日销<1且毛利率>=5%'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d > 100 AND m.small_rank_14d <> 99999
                                       THEN '日销>0、毛利率>=5%，且小类排名>100且不等于99999'
                               END,
                               'daily_sales',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 = 0 THEN '= 0'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 > 3 THEN '> 3'
                                   WHEN r.role_14d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.volume_14d / 14.0 > 0 AND m.volume_14d / 14.0 < 1 THEN '> 0 AND < 1'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_14d IN ('问题产品(站点)','瘦狗产品(站点)') AND m.volume_14d / 14.0 > 0 THEN '> 0'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 = 0 THEN 'NOT_USED'
                                   WHEN r.role_14d = '问题产品(站点)' AND m.margin_rate_14d < 0.05 THEN '< 5%'
                                   WHEN r.role_14d = '问题产品(站点)' THEN '>= 5%'
                                   WHEN r.role_14d = '明星产品(站点)' AND m.volume_14d / 14.0 > 3 THEN '>= 15%'
                                   WHEN r.role_14d = '明星产品(站点)' AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN '>= 25%'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 AND m.volume_14d / 14.0 > 3 THEN '>= 15%'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 THEN '>= 25%'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.volume_14d / 14.0 > 3 THEN '>= 5% AND < 15%'
                                   WHEN r.role_14d = '潜力产品(站点)' THEN '>= 10% AND < 25%'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d BETWEEN 1 AND 100 AND m.volume_14d / 14.0 BETWEEN 1 AND 3 THEN '>= 5% AND < 10%'
                                   WHEN r.role_14d = '瘦狗产品(站点)' THEN '>= 5%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_14d = '问题产品(站点)' AND m.volume_14d / 14.0 > 0 AND m.margin_rate_14d >= 0.05
                                    AND (m.small_rank_14d IS NULL OR m.small_rank_14d = 0 OR m.small_rank_14d = 99999)
                                       THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.role_14d = '问题产品(站点)' THEN 'NOT_USED'
                                   WHEN r.role_14d = '明星产品(站点)' THEN 'BETWEEN 1 AND 50'
                                   WHEN r.role_14d = '潜力产品(站点)' AND m.small_rank_14d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_14d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_14d = '瘦狗产品(站点)' AND m.small_rank_14d BETWEEN 1 AND 100 THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_14d = '瘦狗产品(站点)' THEN '> 100 AND <> 99999'
                               END
                           ),
                            'product_issue',pi.product_issue_json
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_product_issue pi
                  ON pi.country_category = r.country_category
                 AND pi.country = r.country AND pi.store = r.store AND pi.msku = r.msku
                 AND pi.label_period = '14d'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_14d;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S40 写入站点销售角色30d';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3347,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '30d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v47_station_role_20260819','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_30d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','30d','days',30),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_30d,4),'daily_sales',ROUND(m.volume_30d / 30.0,4),
                               'sales_amount',ROUND(m.sales_amount_30d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_30d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_30d,4),'small_rank',m.small_rank_30d,'small_rank_stat_date',DATE_FORMAT(m.latest_rank_date_30d,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.role_30d,
                               'condition',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 = 0
                                       THEN '日销=0'
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 > 0 AND m.margin_rate_30d < 0.05
                                       THEN '日销>0且毛利率<5%'
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 > 0 AND m.margin_rate_30d >= 0.05
                                    AND (m.small_rank_30d IS NULL OR m.small_rank_30d = 0 OR m.small_rank_30d = 99999)
                                       THEN '日销>0、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.role_30d = '明星产品(站点)' AND m.volume_30d / 30.0 > 3
                                       THEN '小类排名1-50，日销>3且毛利率>=15%'
                                   WHEN r.role_30d = '明星产品(站点)' AND m.volume_30d / 30.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-50，1<=日销<=3且毛利率>=25%'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100
                                       THEN '小类排名51-100，且满足明星产品的日销毛利条件'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.volume_30d / 30.0 > 3
                                       THEN '小类排名1-100，日销>3且5%<=毛利率<15%'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.volume_30d / 30.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且10%<=毛利率<25%'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d BETWEEN 1 AND 100
                                    AND m.volume_30d / 30.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且5%<=毛利率<10%'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d BETWEEN 1 AND 100
                                    AND m.volume_30d / 30.0 > 0 AND m.volume_30d / 30.0 < 1
                                       THEN '小类排名1-100，0<日销<1且毛利率>=5%'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d > 100 AND m.small_rank_30d <> 99999
                                       THEN '日销>0、毛利率>=5%，且小类排名>100且不等于99999'
                               END,
                               'daily_sales',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 = 0 THEN '= 0'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 > 3 THEN '> 3'
                                   WHEN r.role_30d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.volume_30d / 30.0 > 0 AND m.volume_30d / 30.0 < 1 THEN '> 0 AND < 1'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_30d IN ('问题产品(站点)','瘦狗产品(站点)') AND m.volume_30d / 30.0 > 0 THEN '> 0'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 = 0 THEN 'NOT_USED'
                                   WHEN r.role_30d = '问题产品(站点)' AND m.margin_rate_30d < 0.05 THEN '< 5%'
                                   WHEN r.role_30d = '问题产品(站点)' THEN '>= 5%'
                                   WHEN r.role_30d = '明星产品(站点)' AND m.volume_30d / 30.0 > 3 THEN '>= 15%'
                                   WHEN r.role_30d = '明星产品(站点)' AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN '>= 25%'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 AND m.volume_30d / 30.0 > 3 THEN '>= 15%'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 THEN '>= 25%'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.volume_30d / 30.0 > 3 THEN '>= 5% AND < 15%'
                                   WHEN r.role_30d = '潜力产品(站点)' THEN '>= 10% AND < 25%'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d BETWEEN 1 AND 100 AND m.volume_30d / 30.0 BETWEEN 1 AND 3 THEN '>= 5% AND < 10%'
                                   WHEN r.role_30d = '瘦狗产品(站点)' THEN '>= 5%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_30d = '问题产品(站点)' AND m.volume_30d / 30.0 > 0 AND m.margin_rate_30d >= 0.05
                                    AND (m.small_rank_30d IS NULL OR m.small_rank_30d = 0 OR m.small_rank_30d = 99999)
                                       THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.role_30d = '问题产品(站点)' THEN 'NOT_USED'
                                   WHEN r.role_30d = '明星产品(站点)' THEN 'BETWEEN 1 AND 50'
                                   WHEN r.role_30d = '潜力产品(站点)' AND m.small_rank_30d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_30d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_30d = '瘦狗产品(站点)' AND m.small_rank_30d BETWEEN 1 AND 100 THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_30d = '瘦狗产品(站点)' THEN '> 100 AND <> 99999'
                               END
                           ),
                            'product_issue',pi.product_issue_json
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_product_issue pi
                  ON pi.country_category = r.country_category
                 AND pi.country = r.country AND pi.store = r.store AND pi.msku = r.msku
                 AND pi.label_period = '30d'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_30d;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S41 写入站点销售角色90d';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3393,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`, `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date, r.country_category, r.country, r.store, r.msku,
                       l.sub_label_id, '90d', NOW(),
                       JSON_OBJECT(
                           'schema_version','1.1','rule_version','v47_station_role_20260819','type','station_sales_role',
                           'window',JSON_OBJECT('start',DATE_FORMAT(v_90d,'%Y-%m-%d'),'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),'period','90d','days',90),
                           'metrics',JSON_OBJECT(
                               'period_sales_qty',ROUND(m.volume_90d,4),'daily_sales',ROUND(m.volume_90d / 90.0,4),
                               'sales_amount',ROUND(m.sales_amount_90d,4),'tag_gross_profit',ROUND(m.tag_gross_profit_90d,4),
                               'tag_margin_rate',ROUND(100 * m.margin_rate_90d,4),'small_rank',m.small_rank_90d,'small_rank_stat_date',DATE_FORMAT(m.latest_rank_date_90d,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'sales_role',r.role_90d,
                               'condition',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 = 0
                                       THEN '日销=0'
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 > 0 AND m.margin_rate_90d < 0.05
                                       THEN '日销>0且毛利率<5%'
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 > 0 AND m.margin_rate_90d >= 0.05
                                    AND (m.small_rank_90d IS NULL OR m.small_rank_90d = 0 OR m.small_rank_90d = 99999)
                                       THEN '日销>0、毛利率>=5%，且小类排名为空、0或99999'
                                   WHEN r.role_90d = '明星产品(站点)' AND m.volume_90d / 90.0 > 3
                                       THEN '小类排名1-50，日销>3且毛利率>=15%'
                                   WHEN r.role_90d = '明星产品(站点)' AND m.volume_90d / 90.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-50，1<=日销<=3且毛利率>=25%'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100
                                       THEN '小类排名51-100，且满足明星产品的日销毛利条件'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.volume_90d / 90.0 > 3
                                       THEN '小类排名1-100，日销>3且5%<=毛利率<15%'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.volume_90d / 90.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且10%<=毛利率<25%'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d BETWEEN 1 AND 100
                                    AND m.volume_90d / 90.0 BETWEEN 1 AND 3
                                       THEN '小类排名1-100，1<=日销<=3且5%<=毛利率<10%'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d BETWEEN 1 AND 100
                                    AND m.volume_90d / 90.0 > 0 AND m.volume_90d / 90.0 < 1
                                       THEN '小类排名1-100，0<日销<1且毛利率>=5%'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d > 100 AND m.small_rank_90d <> 99999
                                       THEN '日销>0、毛利率>=5%，且小类排名>100且不等于99999'
                               END,
                               'daily_sales',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 = 0 THEN '= 0'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 > 3 THEN '> 3'
                                   WHEN r.role_90d IN ('潜力产品(站点)','明星产品(站点)') AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.volume_90d / 90.0 > 0 AND m.volume_90d / 90.0 < 1 THEN '> 0 AND < 1'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN 'BETWEEN 1 AND 3'
                                   WHEN r.role_90d IN ('问题产品(站点)','瘦狗产品(站点)') AND m.volume_90d / 90.0 > 0 THEN '> 0'
                               END,
                               'tag_margin_rate',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 = 0 THEN 'NOT_USED'
                                   WHEN r.role_90d = '问题产品(站点)' AND m.margin_rate_90d < 0.05 THEN '< 5%'
                                   WHEN r.role_90d = '问题产品(站点)' THEN '>= 5%'
                                   WHEN r.role_90d = '明星产品(站点)' AND m.volume_90d / 90.0 > 3 THEN '>= 15%'
                                   WHEN r.role_90d = '明星产品(站点)' AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN '>= 25%'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 AND m.volume_90d / 90.0 > 3 THEN '>= 15%'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 THEN '>= 25%'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.volume_90d / 90.0 > 3 THEN '>= 5% AND < 15%'
                                   WHEN r.role_90d = '潜力产品(站点)' THEN '>= 10% AND < 25%'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d BETWEEN 1 AND 100 AND m.volume_90d / 90.0 BETWEEN 1 AND 3 THEN '>= 5% AND < 10%'
                                   WHEN r.role_90d = '瘦狗产品(站点)' THEN '>= 5%'
                               END,
                               'small_rank',CASE
                                   WHEN r.role_90d = '问题产品(站点)' AND m.volume_90d / 90.0 > 0 AND m.margin_rate_90d >= 0.05
                                    AND (m.small_rank_90d IS NULL OR m.small_rank_90d = 0 OR m.small_rank_90d = 99999)
                                       THEN 'IS NULL OR = 0 OR = 99999'
                                   WHEN r.role_90d = '问题产品(站点)' THEN 'NOT_USED'
                                   WHEN r.role_90d = '明星产品(站点)' THEN 'BETWEEN 1 AND 50'
                                   WHEN r.role_90d = '潜力产品(站点)' AND m.small_rank_90d BETWEEN 51 AND 100 THEN 'BETWEEN 51 AND 100'
                                   WHEN r.role_90d = '潜力产品(站点)' THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_90d = '瘦狗产品(站点)' AND m.small_rank_90d BETWEEN 1 AND 100 THEN 'BETWEEN 1 AND 100'
                                   WHEN r.role_90d = '瘦狗产品(站点)' THEN '> 100 AND <> 99999'
                               END
                           ),
                            'product_issue',pi.product_issue_json
                       )
                FROM tmp_station_sales_roles r
                JOIN tmp_station_sales_metrics m
                  ON m.country = r.country AND m.store = r.store AND m.msku = r.msku
                JOIN tmp_station_product_issue pi
                  ON pi.country_category = r.country_category
                 AND pi.country = r.country AND pi.store = r.store AND pi.msku = r.msku
                 AND pi.label_period = '90d'
                JOIN tmp_station_active_labels l
                  ON l.label_name = '站点销售角色'
                 AND l.sub_label_name = r.role_90d;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                                -- 站点生命周期成熟期不自动回退：按国家类别+国家+店铺+MSKU读取前序成熟期标签。
                SET v_stage = 'tmp_previous_station_lifecycle_mature';
                DROP TEMPORARY TABLE IF EXISTS tmp_previous_station_lifecycle_mature;
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S42 读取上一业务日站点成熟期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'CREATE_TABLE_AS_SELECT', 3442,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                ALTER TABLE tmp_previous_station_lifecycle_mature
                    ADD INDEX idx_tmp_previous_station_lifecycle_mature (country_category, country, store, msku);

                -- 衰退期为人工维护定义，自动 SQL 仅写入测款期/新品期/成长期/成熟期。
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S43 写入站点生命周期';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3466,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                           'schema_version','1.0','rule_version','v47','type','station_lifecycle',
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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                -- 销售角色产品问题独立标签：复用前面已经按指标计算完成的 product_issue.label，
                -- 只把它映射为 label_id=15/16 的独立标签记录，不重复维护第二套 CASE 规则。
                -- 必须放在同一事务 COMMIT 前，确保基础标签与产品问题标签同时成功或同时回滚。
                SET v_stage = '销售角色产品问题独立标签写入';

                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S44 写入标签15和16产品问题标签';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3560,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

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
                       CASE source_detail.`label_name`
                           WHEN '站点销售角色' THEN JSON_OBJECT(
                               'type','station_sales_role_product_issue',
                               'schema_version','1.3',
                               'rule_version',JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`,'$.product_issue.rule_version')),
                               'window',JSON_EXTRACT(sr.`evidence_json`,'$.window'),
                               'label',JSON_OBJECT(
                                   'sub_label_id',issue_detail.`sub_label_id`,
                                   'sub_label_name',issue_detail.`sub_label_name`
                               ),
                               'source_sales_role',JSON_OBJECT(
                                   'sub_label_id',source_detail.`sub_label_id`,
                                   'sub_label_name',source_detail.`sub_label_name`
                               ),
                               'metrics',JSON_OBJECT(
                                   'period_sales_qty',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.period_sales_qty'),
                                   'daily_sales',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.daily_sales'),
                                   'sales_amount',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.sales_amount'),
                                   'gross_profit',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.tag_gross_profit'),
                                   'margin_rate',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.tag_margin_rate'),
                                   'small_rank',JSON_EXTRACT(sr.`evidence_json`,'$.metrics.small_rank'),
                                   'small_rank_stat_date',JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`,'$.metrics.small_rank_stat_date'))
                               ),
                               'matched_rule',JSON_OBJECT(
                                   'condition',JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`,'$.product_issue.matched_rule.condition'))
                               ),
                               'benchmark_target',JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`,'$.product_issue.benchmark_target')),
                               'strategy_advice',JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`,'$.product_issue.strategy_advice'))
                           )
                           ELSE JSON_SET(
                               sr.`evidence_json`,
                               '$.schema_version', JSON_UNQUOTE(JSON_EXTRACT(sr.`evidence_json`, '$.schema_version')),
                               '$.type', 'sales_role_product_issue',
                               -- 标签15继续保留原有JSON结构和字段。
                               '$.matched_rule', JSON_EXTRACT(
                                   sr.`evidence_json`,
                                   '$.product_issue.matched_rule'
                               ),
                               '$.source_sales_role', JSON_OBJECT(
                                   'parent_label_id', source_detail.`label_id`,
                                   'parent_label_name', source_detail.`label_name`,
                                   'sub_label_id', source_detail.`sub_label_id`,
                                   'sub_label_name', source_detail.`sub_label_name`
                               ),
                               '$.product_issue.parent_label_id', issue_detail.`label_id`,
                               '$.product_issue.parent_label_name', issue_detail.`label_name`,
                               '$.product_issue.sub_label_id', issue_detail.`sub_label_id`
                           )
                       END AS `evidence_json`
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
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;

                SET v_record_count = v_record_count + v_select_affected_rows;

                -- 标签17：按国家站点+店铺+MSKU+统计周期写入运营状态策略建议。
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S45 写入标签17运营策略标签';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 3614,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`,
                     `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date,
                       s.country_category, s.country, s.store, s.msku,
                       s.strategy_sub_label_id, s.label_period, NOW(),
                       JSON_OBJECT(
                           'schema_version','1.0',
                           'rule_version','v47_20260810_test_support_price_band',
                           'type','operation_status_strategy_station',
                           'window',JSON_OBJECT(
                               'start',DATE_FORMAT(s.period_start,'%Y-%m-%d'),
                               'end',DATE_FORMAT(v_data_date,'%Y-%m-%d'),
                               'period',s.label_period,
                               'days',s.period_days
                           ),
                           'metrics',JSON_OBJECT(
                               'operation_status',s.operation_status,
                               'operation_status_source','标签3：国家类别+店铺+MSKU运营状态展开到国家',
                               'station_sales_role',s.station_sales_role,
                               'product_issue_label',s.issue_label,
                               'period_sales_qty',ROUND(s.period_sales_qty,4),
                               'daily_sales',ROUND(s.daily_sales,4),
                               'order_margin_rate',ROUND(100*s.order_margin_rate,4),
                               'acos',ROUND(100*s.acoas_rate,4),
                               'small_rank',ROUND(s.small_rank,4),
                               'first_receiving_date',DATE_FORMAT(s.first_receiving_date,'%Y-%m-%d'),
                               'test_support_days',s.test_support_days,
                               'ten_percent_price_test_status',s.ten_pct_price_test_status,
                               'price_history_start_date',DATE_FORMAT(s.price_history_start_date,'%Y-%m-%d'),
                               'first_10pct_test_date',DATE_FORMAT(s.first_10pct_test_date,'%Y-%m-%d'),
                               'first_10pct_acos5_date',DATE_FORMAT(s.first_10pct_acos5_date,'%Y-%m-%d'),
                               'latest_price_source_table','temporary_dwd.在库节点_输出定价表_每日快照',
                               'latest_price_stat_date',DATE_FORMAT(s.latest_price_stat_date,'%Y-%m-%d'),
                               'latest_listing_price',ROUND(s.latest_listing_price,4),
                               'five_pct_target_price',ROUND(s.five_pct_target_price,4),
                               'latest_ten_pct_target_price',ROUND(s.latest_ten_pct_target_price,4),
                               'fifteen_pct_target_price',ROUND(s.fifteen_pct_target_price,4),
                               'listing_price_in_5_15_band',s.listing_price_in_5_15_band,
                               'oos_start_date',DATE_FORMAT(s.oos_start_date,'%Y-%m-%d'),
                               'first_restock_date',DATE_FORMAT(s.first_restock_date,'%Y-%m-%d'),
                               'return_day_d0',s.return_day_d0,
                               'pre_oos_window_days',3,
                               'pre_oos_original_daily_sales',ROUND(s.pre_oos_original_daily_sales,4),
                               'return_d3_daily_sales',ROUND(s.return_d3_daily_sales,4),
                               'return_d3_recovery_rate',ROUND(100*s.return_d3_recovery_rate,4),
                               'pre_return_price_date',DATE_FORMAT(s.pre_return_price_date,'%Y-%m-%d'),
                               'pre_return_listing_price',ROUND(s.pre_return_listing_price,4),
                               'first_return_price_acos5_adjust_date',DATE_FORMAT(s.first_return_price_acos5_adjust_date,'%Y-%m-%d')
                           ),
                           'matched_rule',JSON_OBJECT(
                               'operation_status',CASE
                                   WHEN s.strategy_sub_label_id BETWEEN 1701 AND 1704 THEN '= 测款扶持'
                                   WHEN s.strategy_sub_label_id BETWEEN 1705 AND 1709 THEN '= 返厂品'
                                   WHEN s.strategy_sub_label_id = 1710 THEN '缺失或指标异常'
                               END,
                               'test_support_days',CASE
                                   WHEN s.strategy_sub_label_id = 1701 THEN 'BETWEEN 1 AND 7'
                                   WHEN s.strategy_sub_label_id IN (1702,1703,1704) THEN '> 7'
                                   ELSE 'NOT_USED'
                               END,
                               'listing_price_band',CASE
                                   WHEN s.strategy_sub_label_id = 1701 THEN 'listing_price >= 5pct_target_price AND listing_price <= 15pct_target_price'
                                   ELSE 'NOT_USED'
                               END,
                               'daily_sales',CASE
                                   WHEN s.strategy_sub_label_id = 1702 THEN '>= 1'
                                   WHEN s.strategy_sub_label_id IN (1703,1704) THEN '>= 0 AND < 1'
                                   ELSE 'NOT_USED'
                               END,
                               'order_margin_rate',CASE
                                   WHEN s.strategy_sub_label_id = 1707 THEN '> 10%'
                                   WHEN s.strategy_sub_label_id = 1708 THEN '<= 10% OR 已完成降档复核'
                                   ELSE 'NOT_USED'
                               END,
                               'acos',CASE
                                   WHEN s.strategy_sub_label_id IN (1703,1707) THEN '目标约5%，尚未完成对应周期复核'
                                   WHEN s.strategy_sub_label_id IN (1704,1708) THEN '>= 5%且已完成对应周期复核'
                                   ELSE 'NOT_USED'
                               END,
                               'return_day',CASE
                                   WHEN s.strategy_sub_label_id = 1705 THEN 'D0-D2；D3数据形成后判断恢复率'
                                   WHEN s.strategy_sub_label_id IN (1706,1707,1708) THEN '>= D3'
                                   ELSE 'NOT_USED'
                               END,
                               'return_d3_recovery_rate',CASE
                                   WHEN s.strategy_sub_label_id = 1706 THEN '>= 70%'
                                   WHEN s.strategy_sub_label_id IN (1707,1708) THEN '< 70%'
                                   ELSE 'NOT_USED'
                               END,
                               'review_status',CASE
                                   WHEN s.strategy_sub_label_id = 1701 THEN '首次收货D1-D7且最新Listing价格处于5%-15%订单毛利价格区间'
                                   WHEN s.strategy_sub_label_id = 1703 THEN '首次收货超过7天，广告调整后的对应统计周期未完成'
                                   WHEN s.strategy_sub_label_id = 1704 THEN '10%订单毛利定价+acos约5%后已完成对应周期'
                                   WHEN s.strategy_sub_label_id = 1708 AND s.order_margin_rate > 0.10 THEN '降档+acos约5%后已完成对应周期'
                                   ELSE 'NOT_USED'
                               END
                           ),
                           'strategy_action',CASE s.strategy_sub_label_id
                               WHEN 1701 THEN '10%订单毛利起售'
                               WHEN 1702 THEN '提价至25%订单毛利'
                               WHEN 1703 THEN '提高广告投入至acos 5%'
                               WHEN 1704 THEN '改善Listing'
                               WHEN 1705 THEN '按断货前原价恢复销售并观察D3'
                               WHEN 1706 THEN '退出返厂品状态'
                               WHEN 1707 THEN '降至下一订单毛利档位并投入acos 5%'
                               WHEN 1708 THEN '降至10%订单毛利并转入测款扶持流程'
                               WHEN 1709 THEN '暂停判断并核查返厂数据'
                               WHEN 1710 THEN '暂停判断并核查运营状态及指标数据'
                           END,
                           'strategy_advice',CASE s.strategy_sub_label_id
                                                          WHEN 1701 THEN '首次收货D1-D7内，最新Listing价格已处于5%至15%订单毛利价格区间，按当前价格进行起售测试，并在D7结束后复核站点日销、订单毛利率和acos。'
                                                          WHEN 1702 THEN '将定价提高至可实现25%订单毛利率的价格，同时控制acos，持续观察日销是否稳定。'
                                                          WHEN 1703 THEN '保持10%订单毛利定价，将acos逐步提升至5%左右，并在一个对应统计周期后复核日销。'
                                                          WHEN 1704 THEN '10%订单毛利定价和acos约5%的广告调整后日销仍低于1，转入Listing优化，重点检查标题、图片、五点描述和产品描述。'
                                                          WHEN 1705 THEN '按断货前原价恢复销售，继续观察至返厂D3，并记录D3站点日销恢复率。'
                                                          WHEN 1706 THEN '返厂D3站点日销恢复率已达到70%，退出返厂品策略流程。'
                                                          WHEN 1707 THEN '返厂D3恢复率低于70%且当前订单毛利率高于10%，将价格下调至下一订单毛利档位，并将acos投入至5%左右。'
                                                          WHEN 1708 THEN '降价及广告调整后仍未恢复，或当前订单毛利率已不高于10%，将价格调整至10%订单毛利并转入测款扶持流程。'
                                                          WHEN 1709 THEN '返厂关键日期或销量数据异常，暂停输出恢复策略，先核查返厂日期、断货前日销和D3日销。'
                                                          WHEN 1710 THEN '运营状态或站点经营指标缺失/异常，暂停输出策略，先核查运营状态、日销、订单毛利率和acos。'
                                                      END,
                           'source_labels',JSON_OBJECT(
                               'operation_status',s.operation_status,
                               'station_sales_role',s.station_sales_role,
                               'product_issue_label',s.issue_label
                           )
                       ) AS evidence_json
                FROM tmp_station_operation_strategy_base s
                WHERE s.strategy_sub_label_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM `dws_datasync`.`dws_标签详情表` d
                      WHERE d.`label_id` = 17
                        AND d.`sub_label_id` = s.strategy_sub_label_id
                        AND d.`status` = '启用'
                        AND d.`tagging_method` = 'auto_sql'
                  );
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;

                SET v_record_count = v_record_count + v_select_affected_rows;

                -- 标签18：广告投放效果。严格按照1801至1809的优先顺序判断，CASE首次命中后停止。
                SET v_stage = 'label18 write';
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S46 写入标签18广告投放效果';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`,
                     `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date,
                       m.country_category,
                       m.country,
                       m.store,
                       m.msku,
                       m.sub_label_id,
                       '7d',
                       NOW(),
                       JSON_OBJECT(
                           'schema_version', '1.1',
                           'rule_version', 'v47_ad_labels_20260813',
                           'type', 'advertising_performance',
                           'window', JSON_OBJECT(
                               'start', DATE_FORMAT(v_ad_7d_start, '%Y-%m-%d'),
                               'end', DATE_FORMAT(v_ad_window_end, '%Y-%m-%d'),
                               'period', '7d'
                           ),
                           'metrics', JSON_OBJECT(
                               'sales_amount', ROUND(m.sales_amount, 4),
                               'ad_spend', ROUND(m.ad_spend, 4),
                               'ad_attributed_sales', ROUND(m.ad_attributed_sales, 4),
                               'tacos', ROUND(m.tacos, 4),
                               'acos', ROUND(m.acos, 4),
                               'ad_sales_share', ROUND(m.ad_sales_share, 4),
                               'source_day_count', m.source_day_count
                           ),
                           'matched_rule', JSON_OBJECT(
                               'sub_label_id', m.sub_label_id,
                               'label', l.sub_label_name,
                               'condition', CASE m.sub_label_id
                                   WHEN 1801 THEN '整体销售额为空或<=0，或广告花费缺失'
                                   WHEN 1802 THEN '广告花费>0，且广告归因销售额为空或<=0'
                                   WHEN 1803 THEN 'TACOS>=25%'
                                   WHEN 1804 THEN '未命中更高优先级，且ACOS>=60%'
                                   WHEN 1805 THEN '未命中更高优先级，且广告销售占比>=50%'
                                   WHEN 1806 THEN '未命中更高优先级，且TACOS<4.8%'
                                   WHEN 1807 THEN '未命中更高优先级，且TACOS为4.8%-5.2%、ACOS为8%-10%'
                                   WHEN 1808 THEN '未命中更高优先级，且ACOS<=20%'
                                   WHEN 1809 THEN '数据有效但未命中以上规则'
                               END
                           )
                       ) AS evidence_json
                FROM tmp_ad_18_metrics m
                JOIN tmp_station_active_labels l
                  ON l.label_name = '广告投放效果'
                 AND l.sub_label_id = m.sub_label_id;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                -- 标签19：按店铺+MSKU汇总五个主要站点近7天广告覆盖，再展开到对应国家+店铺+MSKU。
                -- 严格按照1901至1904的优先顺序判断，广告花费缺失不按0处理。
                SET v_stage = 'label19 write';
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S47 写入标签19广告推广管理';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`,
                     `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date,
                       k.country_category,
                       k.country,
                       k.store,
                       k.msku,
                       c.sub_label_id,
                       '7d',
                       NOW(),
                       JSON_OBJECT(
                           'schema_version', '1.1',
                           'rule_version', 'v47_ad_labels_20260813',
                           'type', 'advertising_coverage_management',
                           'window', JSON_OBJECT(
                               'start', DATE_FORMAT(v_ad_7d_start, '%Y-%m-%d'),
                               'end', DATE_FORMAT(v_ad_window_end, '%Y-%m-%d'),
                               'period', '7d'
                           ),
                           'metrics', JSON_OBJECT(
                               'site_status', JSON_OBJECT(
                                   '德国', c.germany_status,
                                   '法国', c.france_status,
                                   '意大利', c.italy_status,
                                   '西班牙', c.spain_status,
                                   '荷兰', c.netherlands_status
                               ),
                               'site_ad_spend_7d', JSON_OBJECT(
                                   '德国', ROUND(c.germany_ad_spend, 4),
                                   '法国', ROUND(c.france_ad_spend, 4),
                                   '意大利', ROUND(c.italy_ad_spend, 4),
                                   '西班牙', ROUND(c.spain_ad_spend, 4),
                                   '荷兰', ROUND(c.netherlands_ad_spend, 4)
                               ),
                               'site_source_days', JSON_OBJECT(
                                   '德国', c.germany_source_days,
                                   '法国', c.france_source_days,
                                   '意大利', c.italy_source_days,
                                   '西班牙', c.spain_source_days,
                                   '荷兰', c.netherlands_source_days
                               )
                           ),
                           'matched_rule', JSON_OBJECT(
                               'sub_label_id', c.sub_label_id,
                               'label', l.sub_label_name,
                               'condition', CASE c.sub_label_id
                                   WHEN 1901 THEN '五个主要站点中至少一个站点广告数据缺失'
                                   WHEN 1902 THEN '五个主要站点近7天广告花费均>0'
                                   WHEN 1903 THEN '五个主要站点近7天广告花费均=0'
                                   WHEN 1904 THEN '无数据缺失，至少一个站点广告花费>0且至少一个站点广告花费=0'
                               END
                           )
                       ) AS evidence_json
                FROM tmp_ad_19_output_keys k
                JOIN tmp_ad_19_coverage c
                  ON c.store = k.store
                 AND c.msku = k.msku
                JOIN tmp_station_active_labels l
                  ON l.label_name = '广告推广与管理'
                 AND l.sub_label_id = c.sub_label_id;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

                -- 标签23：分别续接标签1与标签13当天30d销售角色的连续出现次数。
                SET v_select_seq = v_select_seq + 1;
                SET v_select_name = 'S48 写入标签23当天30d销售角色连续出现次数';
                INSERT INTO `etl_datasync`.`etl_execution_select_log_v47`
                    (`execution_log_id`, `data_time`, `select_no`, `select_name`, `statement_type`, `source_line`,
                     `sql_start_time`, `status`, `connection_id`)
                VALUES
                    (v_log_id, v_data_date, v_select_seq, v_select_name, 'INSERT_SELECT', 0,
                     NOW(6), 'running', CONNECTION_ID());
                SET v_select_log_id = LAST_INSERT_ID();

                INSERT INTO `dws_datasync`.`dws_标签表`
                    (`data_date`, `country_category`, `country`, `store`, `msku`,
                     `label_id`, `label_period`, `created_time`, `evidence_json`)
                SELECT v_data_date,
                       c.country_category,
                       c.country,
                       c.store,
                       c.msku,
                       target_label.sub_label_id,
                       '30d',
                       NOW(),
                       JSON_OBJECT(
                           'dimension', c.dimension_type,
                           'current_sales_role', JSON_OBJECT(
                               'sub_label_id', c.current_role_label_id,
                               'sub_label_name', c.current_role_name
                           ),
                           'continuous_count', c.continuous_count,
                           'continuous_start_date', DATE_FORMAT(c.continuous_start_date, '%Y-%m-%d'),
                           'display_text', CONCAT('已在', c.current_role_name, c.continuous_count, '天')
                       )
                FROM (
                    SELECT r.dimension_type,
                           r.country_category,
                           r.country,
                           r.store,
                           r.msku,
                           r.current_role_label_id,
                           r.current_role_name,
                           CASE WHEN p.current_role_label_id = r.current_role_label_id
                                    THEN p.continuous_count + 1
                                ELSE 1 END AS continuous_count,
                           CASE WHEN p.current_role_label_id = r.current_role_label_id
                                    THEN p.continuous_start_date
                                ELSE v_data_date END AS continuous_start_date
                    FROM (
                        SELECT DISTINCT
                               'country_category+store+msku' AS dimension_type,
                               r.country_category,
                               NULL AS country,
                               r.store,
                               r.MSKU AS msku,
                               d.sub_label_id AS current_role_label_id,
                               d.sub_label_name AS current_role_name
                        FROM tmp_sales_role r
                        JOIN `dws_datasync`.`dws_标签详情表` d
                          ON d.label_id = 1
                         AND d.sub_label_name = r.role_30d
                         AND CAST(d.status AS CHAR) = '启用'
                        WHERE v_data_date >= DATE('2026-09-03')
                          AND r.role_30d IS NOT NULL

                        UNION ALL

                        SELECT DISTINCT
                               'country+store+msku' AS dimension_type,
                               r.country_category,
                               r.country,
                               r.store,
                               r.msku,
                               d.sub_label_id AS current_role_label_id,
                               d.sub_label_name AS current_role_name
                        FROM tmp_station_sales_roles r
                        JOIN `dws_datasync`.`dws_标签详情表` d
                          ON d.label_id = 13
                         AND d.sub_label_name = r.role_30d
                         AND CAST(d.status AS CHAR) = '启用'
                        WHERE v_data_date >= DATE('2026-09-03')
                          AND r.role_30d IS NOT NULL
                    ) r
                    LEFT JOIN tmp_sales_role_30d_prev p
                      ON p.dimension_type = r.dimension_type
                     AND p.country_category = r.country_category
                     AND p.country = COALESCE(r.country, '')
                     AND p.store = r.store
                     AND p.msku = r.msku
                ) c
                JOIN tmp_station_active_labels target_label
                  ON target_label.label_name = '30天销售角色频次记录'
                 AND target_label.sub_label_id = 2301;
                SET v_select_affected_rows = ROW_COUNT();
                UPDATE `etl_datasync`.`etl_execution_select_log_v47`
                SET `sql_end_time` = NOW(6),
                    `elapsed_seconds` = ROUND(TIMESTAMPDIFF(MICROSECOND, `sql_start_time`, NOW(6)) / 1000000, 6),
                    `affected_rows` = v_select_affected_rows,
                    `status` = 'success'
                WHERE `id` = v_select_log_id;
                SET v_select_log_id = NULL;
                SET v_record_count = v_record_count + v_select_affected_rows;

    -- 再次对本业务日执行统一兜底，覆盖站点标签等后续写入路径。
    DELETE FROM `dws_datasync`.`dws_标签表`
    WHERE `data_date` = v_data_date
      AND (
          `msku` IS NULL
          OR TRIM(CAST(`msku` AS CHAR)) = ''
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amzn.gr%'
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amazon%'
      );

    SET v_record_count = GREATEST(v_record_count - ROW_COUNT(), 0);

    -- 主表保留近两天：同步清理前一业务日可能遗留的无效MSKU。
    DELETE FROM `dws_datasync`.`dws_标签表`
    WHERE `data_date` = DATE_SUB(v_data_date, INTERVAL 1 DAY)
      AND (
          `msku` IS NULL
          OR TRIM(CAST(`msku` AS CHAR)) = ''
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amzn.gr%'
          OR LOWER(TRIM(CAST(`msku` AS CHAR))) LIKE 'amazon%'
      );

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

    IF v_run_lock_acquired = 1 THEN
        DO RELEASE_LOCK('dws_label_v47_singleton');
        SET v_run_lock_acquired = 0;
    END IF;
END //

DELIMITER ;

-- ============================================================================
-- V47手工补跑时请逐日串行执行，主表成功后再同步汇总表；以下仅为示例，不自动执行：
-- CALL `dws_datasync`.`sp_dws_标签表_一体化_v47`('2026-09-03');
-- CALL `dws_datasync`.`sp_dws_标签表汇总_同步_按日期_daily`('2026-09-03');
