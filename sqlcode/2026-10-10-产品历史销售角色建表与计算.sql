-- 产品历史销售角色：部署、首算、增量、重算、验收均在本文件。
-- 第1段首次部署；第2—5段为按需运行入口，包装在块注释中。
-- 全文件执行只部署。计算/验收时选中对应块注释内部正文执行（不选 /* 和 */）。
-- 首算需填写已确认完整的截止日；日常增量自动取最新表现日期；区间重算需填写完整产品身份。
-- 使用独立autocommit连接，不包外部事务；正式目标为dws_datasync。

-- section:deploy:begin
-- MySQL 8.0.21+。部署只建立本方案的新对象，不修改现有源表/标签表。
-- 不自动运行历史计算。先阅读配套说明，再执行末尾注释中的 call。
-- source_schema 指向 dwd 数据；所有持久写入只发生在 dws_datasync 新对象。
set names utf8mb4 collate utf8mb4_0900_ai_ci;
set @hr_deploy_sql_mode=@@session.sql_mode;
set session sql_mode=concat_ws(',',nullif(@@session.sql_mode,''),'strict_all_tables');

create table if not exists dws_datasync.dws_product_sales_role_history (
    scope_mode varchar(16) not null comment 'business_unit / country',
    country_category varchar(20) not null,
    country varchar(100) not null default '',
    store varchar(100) not null,
    msku varchar(500) not null,
    data_date date null comment '已原子处理至该日；null表示尚未发布',
    created_time datetime(6) not null default current_timestamp(6),
    updated_time datetime(6) not null default current_timestamp(6),
    evidence_json json not null,
    primary key (scope_mode,country_category,country,store,msku),
    key idx_history_cutoff (data_date)
) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;

create table if not exists dws_datasync.dws_product_sales_role_history_run_log (
    run_id char(36) primary key,
    run_mode varchar(16) not null,
    cutoff date not null,
    status varchar(16) not null,
    stage varchar(100) not null,
    published_products bigint not null default 0,
    started_at datetime(6) not null,
    finished_at datetime(6) null,
    error_message text null
) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;

delimiter $$
-- 内部加载器。调用者先建立会话临时表；一个年度的窄表落临时 innodb。
drop procedure if exists dws_datasync.sp_product_history_load_year$$
create procedure dws_datasync.sp_product_history_load_year(
    in p_schema varchar(64), in p_year int, in p_start date, in p_end date,
    in p_chunk int, in p_recent tinyint
)
sql security invoker
begin
    declare v_last bigint default -1;
    declare v_bound bigint;
    declare v_table varchar(100);
    declare v_index varchar(100);
    declare v_start date;
    declare v_end date;
    declare v_from text;
    declare v_id_column varchar(40);
    declare v_required text default '';
    set v_start=greatest(p_start,makedate(p_year,1));
    set v_end=least(p_end,date_sub(makedate(p_year+1,1),interval 1 day));
    set v_table=if(p_year<=2025,concat('lx_statistics_product_performance_',p_year),'lx_statistics_product_performance');
    if v_start<=v_end then
        truncate table tmp_hr_raw;
        set v_index='primary';
        if p_recent in (1,2) and p_year>=2026 then
            select coalesce(max(case when index_name='idx_osp_performance_date_sync' then index_name end),min(index_name)) into v_index from information_schema.statistics
            where table_schema=p_schema and table_name=v_table and seq_in_index=1 and column_name='start_date';
            if v_index is null then signal sqlstate '45000' set message_text='recent source needs a start_date index; no source DDL is performed'; end if;
        end if;
        set v_id_column='id';
        set v_from=concat('from `',p_schema,'`.`',v_table,'` src force index (`primary`)');
        if p_recent=2 then
            -- 仅为待核身份补历史时，落临时表前按所需产品和范围筛选。
            set v_required=concat('exists(select 1 from tmp_hr_required k where k.country=src.country ',
                'and k.store=substring_index(substring_index(src.seller_name,\' \',1),\'-\',1) and k.msku=src.seller_sku ',
                'and src.start_date between k.source_read_start and k.recalc_end)');
        end if;
        if p_recent in (1,2) and p_year>=2026 then
            -- 日期索引仅扫描一次ID；随后按临时ID主键分页并回源主键查明细。
            drop temporary table if exists tmp_hr_source_ids;
            create temporary table tmp_hr_source_ids(hr_source_id bigint primary key) engine=innodb;
            set @hr_sql=concat('insert into tmp_hr_source_ids select id from `',p_schema,'`.`',v_table,
                '` force index (`',v_index,'`) where start_date between ',quote(cast(v_start as char)),
                ' and ',quote(cast(v_end as char)));
            prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
            set v_id_column='i.hr_source_id';
            set v_from=concat('from tmp_hr_source_ids i straight_join `',p_schema,'`.`',v_table,
                '` src force index (`primary`) on id=i.hr_source_id');
        end if;
        load_blocks: loop
            if p_recent in (1,2) and p_year>=2026 then
                set @hr_sql=concat('select max(hr_source_id) into @hr_bound from (select hr_source_id from tmp_hr_source_ids where hr_source_id>',v_last,' order by hr_source_id limit ',p_chunk,') b');
            else
                set @hr_sql=concat('select max(id) into @hr_bound from (select id ',v_from,' where id>',v_last,' order by id limit ',p_chunk,') b');
            end if;
            prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
            set v_bound=@hr_bound;
            if v_bound is null then leave load_blocks; end if;
            -- 严格模式禁止身份截断；异常日级时间粒度停止本次计算。
            set @hr_sql=concat('select coalesce(sum(bad_count),0),json_arrayagg(stat_date) into @hr_bad,@hr_dates from (select date(start_date) stat_date,sum(case ',
                if(p_recent=2,concat('when not ',v_required,' then 0 '),''),
                'when lower(trim(seller_sku)) like \'amzn.gr%\' or lower(trim(seller_sku)) like \'amazon%\' then 0 else ',
                'end_date is null or start_date<>end_date or char_length(seller_sku)>500 or char_length(country)>100 or char_length(asin)>40',
                ' or seller_sku is null or trim(seller_sku)=\'\' or seller_name is null or trim(seller_name)=\'\' or country is null or trim(country)=\'\' end) bad_count ',v_from,' where ',v_id_column,'>',v_last,' and ',v_id_column,'<=',v_bound,
                ' and start_date between ',quote(cast(v_start as char)),' and ',quote(cast(v_end as char)),
                ' group by start_date) batch_dates');
            prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
            if @hr_bad>0 then signal sqlstate '45000' set message_text='invalid identity or non-daily source rows; inspect source before retry'; end if;
            insert ignore into tmp_hr_calendar select d from json_table(coalesce(@hr_dates,json_array()),'$[*]' columns(d date path '$')) observed_dates;
            set @hr_sql=concat('insert into tmp_hr_raw(country,store,msku,asin,stat_date,source_seller,source_id,source_time,create_date,qty,amount,profit,stock,small_rank,anomaly) ',
                'select country,substring_index(substring_index(seller_name,\' \',1),\'-\',1),seller_sku,coalesce(asin,\'\'),date(start_date),seller_name,id,coalesce(create_time,\'1000-01-01\'),',
                'case when product_create_time regexp \'^[0-9]{4}-[0-9]{2}-[0-9]{2}\' then date(left(product_create_time,10)) end,',
                'coalesce(volume,0),coalesce(amount,0),coalesce(predict_gross_profit,0),afn_fulfillable_quantity,`rank`,',
                '(volume is null or volume<0 or amount is null or ((volume>0 or amount>0) and predict_gross_profit is null) or afn_fulfillable_quantity is null) ',
                v_from,' where ',v_id_column,'>',v_last,' and ',v_id_column,'<=',v_bound,
                ' and start_date between ',quote(cast(v_start as char)),' and ',quote(cast(v_end as char)),
                ' and lower(trim(seller_sku)) not like \'amzn.gr%\' and lower(trim(seller_sku)) not like \'amazon%\'',
                if(p_recent=2,concat(' and ',v_required),''),
                ' on duplicate key update ',
                'qty=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(qty),tmp_hr_raw.qty),',
                'amount=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(amount),tmp_hr_raw.amount),',
                'profit=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(profit),tmp_hr_raw.profit),',
                'stock=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(stock),tmp_hr_raw.stock),',
                'small_rank=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(small_rank),tmp_hr_raw.small_rank),',
                'anomaly=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(anomaly),tmp_hr_raw.anomaly),',
                'create_date=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(create_date),tmp_hr_raw.create_date),',
                'source_seller=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(source_seller),tmp_hr_raw.source_seller),',
                'source_id=if((values(source_time),values(source_id))>(tmp_hr_raw.source_time,tmp_hr_raw.source_id),values(source_id),tmp_hr_raw.source_id),',
                'source_time=greatest(tmp_hr_raw.source_time,values(source_time))');
            prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
            set v_last=v_bound;
        end loop;
        -- 观测日历已在每批质量校验中收集，无需再次全年度扫描、排序。
    end if;
end$$

drop procedure if exists dws_datasync.sp_product_role_history$$
create procedure dws_datasync.sp_product_role_history(
    in p_mode varchar(16), in p_cutoff date, in p_source_schema varchar(64),
    in p_from date, in p_to date, in p_scope varchar(16),
    in p_category varchar(20), in p_country varchar(100), in p_store varchar(100), in p_msku varchar(500),
    in p_reset_anchor tinyint, in p_chunk int
)
sql security invoker
main: begin
    declare v_version varchar(80) default 'history_30d_v47_20261010';
    declare v_run char(36) default uuid();
    declare v_lock varchar(100) default 'dws_datasync.product_role_history';
    declare v_locked int default 0;
    declare v_year int;
    declare v_read_start date;
    declare v_scan_start date;
    declare v_pid bigint default 0;
    declare v_next bigint;
    declare v_anchor date;
    declare v_begin date;
    declare v_end date;
    declare v_scope varchar(16);
    declare v_history json;
    declare v_frozen json;
    declare v_identity json;
    declare v_dominant json;
    declare v_old json;
    declare v_doc json;
    declare v_paths longtext;
    declare v_concat_old bigint default null;
    declare v_error text;
    declare v_valid int;
    declare v_total int;
    declare v_tied int;
    declare v_max_votes int;
    declare v_counts json;
    declare v_shares json;
    declare v_asins json;
    declare v_tie_roles json;
    declare v_last_valid int;
    declare v_role int;
    declare v_stage varchar(100) default 'preflight';
    declare v_catalog_missing int default 0;
    declare v_initialize_pending int default 0;
    declare exit handler for sqlexception
    begin
        get diagnostics condition 1 v_error=message_text;
        rollback;
        if v_concat_old is not null then set session group_concat_max_len=v_concat_old; end if;
        if v_locked=1 then
            update dws_datasync.dws_product_sales_role_history_run_log
            set status='failed',stage=v_stage,error_message=v_error,finished_at=now(6) where run_id=v_run;
            commit;
            do release_lock(v_lock);
        end if;
        resignal;
    end;
    -- MySQL 8没有in_transaction系统变量。使用独立的autocommit连接执行。
    if @@session.autocommit<>1 then signal sqlstate '45000' set message_text='run from a fresh autocommit connection'; end if;
    if p_mode not in ('bootstrap','incremental','rebuild') or p_mode is null then signal sqlstate '45000' set message_text='invalid run mode'; end if;
    if p_source_schema is null or p_source_schema not regexp '^[a-zA-Z0-9_]+$' then signal sqlstate '45000' set message_text='invalid source schema'; end if;
    if p_cutoff is null or p_cutoff<'2020-01-01' or p_cutoff>=date(utc_timestamp()+interval 8 hour) then
        signal sqlstate '45000' set message_text='cutoff must be an ETL-complete business date before today (Asia/Shanghai)';
    end if;
    if p_chunk is null or p_chunk<1 or p_chunk>100000 then signal sqlstate '45000' set message_text='chunk must be between 1 and 100000'; end if;
    if p_mode='rebuild' and (p_scope not in ('business_unit','country') or p_scope is null
        or p_category is null or p_country is null or p_store is null or p_msku is null
        or p_from is null or p_to is null or p_from>p_to or p_to>p_cutoff) then
        signal sqlstate '45000' set message_text='rebuild requires exact product identity and valid date range';
    end if;
    if p_mode='rebuild' and p_scope='business_unit' and p_country<>'' then signal sqlstate '45000' set message_text='business_unit country must be empty'; end if;
    if p_reset_anchor is null or p_reset_anchor not in (0,1) or (p_reset_anchor=1 and (p_mode<>'rebuild' or p_from<>'2020-01-01' or p_to<>p_cutoff)) then
        signal sqlstate '45000' set message_text='anchor reset requires full product rebuild from 2020-01-01 through cutoff';
    end if;
    select get_lock(v_lock,0) into v_locked;
    if coalesce(v_locked,0)<>1 then signal sqlstate '45000' set message_text='another history run is active'; end if;
    insert into dws_datasync.dws_product_sales_role_history_run_log(run_id,run_mode,cutoff,status,stage,started_at)
    values(v_run,p_mode,p_cutoff,'running',v_stage,now(6));
    commit;
    if exists(select 1 from dws_datasync.dws_product_sales_role_history where
        (p_mode<>'rebuild' or (scope_mode=p_scope and country_category=p_category and country=p_country and store=p_store and msku=p_msku))
        and coalesce(json_unquote(json_extract(evidence_json,'$.calculation.rule_version')),'')<>v_version
        and not (p_mode='rebuild' and p_from='2020-01-01' and p_to=p_cutoff)) then
        signal sqlstate '45000' set message_text='rule version changed; full product rebuild is required';
    end if;
    if exists(select 1 from dws_datasync.dws_product_sales_role_history where data_date>p_cutoff and
        (p_mode<>'rebuild' or (scope_mode=p_scope and country_category=p_category and country=p_country and store=p_store and msku=p_msku))) then
        signal sqlstate '45000' set message_text='cutoff cannot move backwards';
    end if;
    if p_mode='incremental' and (not exists(select 1 from dws_datasync.dws_product_sales_role_history)
        or not exists(select 1 from dws_datasync.dws_product_sales_role_history_run_log where run_mode='bootstrap' and status='success')) then
        signal sqlstate '45000' set message_text='complete bootstrap must succeed before incremental';
    end if;
    if p_mode='rebuild' and not (p_from='2020-01-01' and p_to=p_cutoff)
        and exists(select 1 from dws_datasync.dws_product_sales_role_history
            where scope_mode=p_scope and country_category=p_category and country=p_country and store=p_store and msku=p_msku
              and (data_date is null or data_date<>p_cutoff)) then
        signal sqlstate '45000' set message_text='partial rebuild cutoff must equal stored data_date; run incremental first or use full rebuild';
    end if;
    -- 旧策略保存的待核记录有首次观测日时，只初始化这些空历史；同日也允许执行一次。
    if p_mode='incremental' then
        select exists(select 1 from dws_datasync.dws_product_sales_role_history
            where str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null
              and str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d') is not null)
        into v_initialize_pending;
    end if;
    -- 同日重复运行仍发现新Listing身份；已发布产品不重新计算。
    if p_mode='incremental' and v_initialize_pending=0 and not exists(
        select 1 from dws_datasync.dws_product_sales_role_history where data_date is null or data_date<p_cutoff
    ) and exists(select 1 from information_schema.tables where table_schema=p_source_schema and table_name='lx_sales_mws_listing') then
        set @hr_catalog_missing=0;
        set @hr_sql=concat('select exists(select 1 from `',p_source_schema,'`.lx_sales_mws_listing l ',
            'left join dws_datasync.dws_product_sales_role_history b on b.scope_mode=\'business_unit\' and b.country=\'\' ',
            'and b.country_category=case when l.marketplace=\'英国\' then \'英国站\' when l.marketplace in (\'美国\',\'加拿大\',\'巴西\',\'墨西哥\') then \'北美站\' else \'欧洲站\' end ',
            'and b.store=substring_index(substring_index(l.seller_name,\' \',1),\'-\',1) and b.msku=l.seller_sku ',
            'left join dws_datasync.dws_product_sales_role_history c on c.scope_mode=\'country\' and c.country=l.marketplace ',
            'and c.country_category=case when l.marketplace=\'英国\' then \'英国站\' when l.marketplace in (\'美国\',\'加拿大\',\'巴西\',\'墨西哥\') then \'北美站\' else \'欧洲站\' end ',
            'and c.store=substring_index(substring_index(l.seller_name,\' \',1),\'-\',1) and c.msku=l.seller_sku ',
            'where trim(l.seller_sku)<>\'\' and lower(trim(l.seller_sku)) not like \'amzn.gr%\' and lower(trim(l.seller_sku)) not like \'amazon%\' ',
            'and (b.msku is null or c.msku is null)) into @hr_catalog_missing');
        prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
        set v_catalog_missing=@hr_catalog_missing;
    end if;
    if p_mode='incremental' and v_catalog_missing=0 and v_initialize_pending=0 and not exists(
        select 1 from dws_datasync.dws_product_sales_role_history where data_date is null or data_date<p_cutoff
    ) then
        update dws_datasync.dws_product_sales_role_history_run_log
        set status='success',stage='already current',finished_at=now(6) where run_id=v_run;
        do release_lock(v_lock);
        select run_id,run_mode,cutoff,status,published_products from dws_datasync.dws_product_sales_role_history_run_log where run_id=v_run;
        leave main;
    end if;
    -- 一次调用仅占用一个年度的去重日级窄表；仅周期聚合跨年度保留。
    drop temporary table if exists tmp_hr_raw;
    create temporary table tmp_hr_raw(
        country varchar(100) not null,store varchar(100) not null,msku varchar(500) not null,asin varchar(40) not null,
        stat_date date not null,source_seller varchar(255),source_id bigint,source_time datetime,
        create_date date,qty decimal(24,4),amount decimal(24,4),profit decimal(24,4),stock int,small_rank int,anomaly tinyint,
        primary key(country,store,msku,asin,stat_date)
    ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    drop temporary table if exists tmp_hr_calendar;
    create temporary table tmp_hr_calendar(stat_date date primary key) engine=innodb;
    drop temporary table if exists tmp_hr_meta;
    create temporary table tmp_hr_meta(
        country varchar(100) not null,store varchar(100) not null,msku varchar(500) not null,
        first_positive date,candidate_date date,first_observed date,
        primary key(country,store,msku)
    ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    drop temporary table if exists tmp_hr_asin;
    create temporary table tmp_hr_asin(country varchar(100),store varchar(100),msku varchar(500),asin varchar(40),
        primary key(country,store,msku,asin),key idx_asin_product(store(32),msku(64),country)) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    drop temporary table if exists tmp_hr_listing;
    -- 商品池不依赖上架日期是否可解析；先校验，再合并，禁止insert ignore截断身份。
    set @hr_sql=concat('select count(*) into @hr_bad from `',p_source_schema,'`.lx_sales_mws_listing ',
        'where trim(seller_sku)<>\'\' and lower(trim(seller_sku)) not like \'amzn.gr%\' and lower(trim(seller_sku)) not like \'amazon%\' and (',
        'char_length(seller_sku)>500 or marketplace is null or trim(marketplace)=\'\' or char_length(marketplace)>100 ',
        'or seller_name is null or trim(seller_name)=\'\' or char_length(substring_index(substring_index(seller_name,\' \',1),\'-\',1))>100 ',
        'or substring_index(substring_index(seller_name,\' \',1),\'-\',1)=\'\' or char_length(asin)>40)');
    prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
    if @hr_bad>0 then signal sqlstate '45000' set message_text='invalid Listing identity; no identity is truncated or defaulted'; end if;
    drop temporary table if exists tmp_hr_listing_pool;
    create temporary table tmp_hr_listing_pool(country varchar(100),store varchar(100),msku varchar(500),asin varchar(40),
        primary key(country,store,msku,asin)) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    set @hr_sql=concat('insert into tmp_hr_listing_pool select distinct marketplace,substring_index(substring_index(seller_name,\' \',1),\'-\',1),seller_sku,coalesce(asin,\'\') ',
        'from `',p_source_schema,'`.lx_sales_mws_listing where trim(seller_sku)<>\'\' ',
        'and lower(trim(seller_sku)) not like \'amzn.gr%\' and lower(trim(seller_sku)) not like \'amazon%\'');
    prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
    create temporary table tmp_hr_listing(country varchar(100),source_seller varchar(255),msku varchar(500),asin varchar(40),candidate_date date,
        key idx_listing(country,source_seller(64),msku(64),asin)) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    set @hr_sql=concat('insert into tmp_hr_listing select marketplace,seller_name,seller_sku,coalesce(asin,\'\'),min(d) from (',
        'select marketplace,seller_name,seller_sku,asin,date(left(open_date_display,10)) d from `',p_source_schema,'`.lx_sales_mws_listing where open_date_display regexp \'^[0-9]{4}-[0-9]{2}-[0-9]{2}\' ',
        'union all select marketplace,seller_name,seller_sku,asin,date(left(on_sale_time,10)) d from `',p_source_schema,'`.lx_sales_mws_listing where on_sale_time regexp \'^[0-9]{4}-[0-9]{2}-[0-9]{2}\') l ',
        'where d between \'2000-01-01\' and ',quote(cast(p_cutoff as char)),
        ' and lower(trim(seller_sku)) not like \'amzn.gr%\' and lower(trim(seller_sku)) not like \'amazon%\' group by marketplace,seller_name,seller_sku,asin');
    prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
    set v_read_start='2020-01-01';
    if p_mode='incremental' then
        select min(coalesce(str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.calculation.open_segment_start')),'null'),'%Y-%m-%d'),date_add(data_date,interval 1 day)))
        into v_read_start from dws_datasync.dws_product_sales_role_history;
        set v_read_start=least(coalesce(v_read_start,p_cutoff),p_cutoff);
    elseif p_mode='rebuild' and p_reset_anchor=0 then
        select str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') into v_anchor
        from dws_datasync.dws_product_sales_role_history where scope_mode=p_scope and country_category=p_category and country=p_country and store=p_store and msku=p_msku;
        if v_anchor is null then signal sqlstate '45000' set message_text='unknown anchor; use full anchor-reset rebuild'; end if;
        set v_read_start=greatest('2020-01-01',date_add(v_anchor,interval (greatest(0,floor(datediff(p_from,v_anchor)/30))*30) day));
    end if;
    set v_stage='identity discovery';
    update dws_datasync.dws_product_sales_role_history_run_log set stage=v_stage where run_id=v_run;
    set v_year=year(v_read_start);
    while v_year<=year(p_cutoff) do
        set v_stage=concat('identity ',v_year);
        update dws_datasync.dws_product_sales_role_history_run_log set stage=v_stage where run_id=v_run;
        call dws_datasync.sp_product_history_load_year(p_source_schema,v_year,v_read_start,p_cutoff,p_chunk,if(p_mode in ('incremental','rebuild'),1,0));
        insert into tmp_hr_meta
        select r.country,r.store,r.msku,min(case when r.stock>0 or r.qty>0 then r.stat_date end),
            min(case when least(coalesce(r.create_date,l.candidate_date),coalesce(l.candidate_date,r.create_date)) between '2000-01-01' and p_cutoff
                then least(coalesce(r.create_date,l.candidate_date),coalesce(l.candidate_date,r.create_date)) end),min(r.stat_date)
        from (
            -- 先缩到身份与日期候选粒度，再关联Listing，不逐日重复关联。
            select country,store,msku,asin,source_seller,create_date,
                min(stat_date) stat_date,max(stock>0) stock,max(qty>0) qty
            from tmp_hr_raw group by country,store,msku,asin,source_seller,create_date,
                (stock>0 or qty>0)
        ) r left join tmp_hr_listing l on l.country=r.country and l.source_seller=r.source_seller and l.msku=r.msku and l.asin=r.asin
        group by r.country,r.store,r.msku
        on duplicate key update
            first_positive=least(coalesce(first_positive,values(first_positive)),coalesce(values(first_positive),first_positive)),
            candidate_date=least(coalesce(candidate_date,values(candidate_date)),coalesce(values(candidate_date),candidate_date)),
            first_observed=least(first_observed,values(first_observed));
        insert ignore into tmp_hr_asin select distinct country,store,msku,asin from tmp_hr_raw;
        set v_year=v_year+1;
    end while;
    -- 历史表现事实优先；只有Listing的身份保留为空历史，不把无记录当成零销量。
    drop temporary table if exists tmp_hr_listing_dates;
    create temporary table tmp_hr_listing_dates as
    select country,substring_index(substring_index(source_seller,' ',1),'-',1) store,msku,asin,min(candidate_date) candidate_date
    from tmp_hr_listing group by country,store,msku,asin;
    alter table tmp_hr_listing_dates add index idx_listing_dates(country,store(32),msku(64),asin);
    insert ignore into tmp_hr_meta(country,store,msku,candidate_date)
    select p.country,p.store,p.msku,min(l.candidate_date) from tmp_hr_listing_pool p
    left join tmp_hr_listing_dates l on l.country=p.country and l.store=p.store and l.msku=p.msku and l.asin=p.asin
    group by p.country,p.store,p.msku;
    insert ignore into tmp_hr_asin select country,store,msku,asin from tmp_hr_listing_pool;
    -- 最近窗口及当前Listing已消失的历史待核身份也从已保存事实恢复。
    if p_mode='incremental' then
        insert into tmp_hr_meta(country,store,msku,first_positive,candidate_date,first_observed)
        select country,store,msku,
            str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.first_positive')),'null'),'%Y-%m-%d'),
            str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.candidate_date')),'null'),'%Y-%m-%d'),
            str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d')
        from dws_datasync.dws_product_sales_role_history
        where scope_mode='country'
          and str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null
          and str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d') is not null
        on duplicate key update
            first_positive=least(coalesce(first_positive,values(first_positive)),coalesce(values(first_positive),first_positive)),
            candidate_date=least(coalesce(candidate_date,values(candidate_date)),coalesce(values(candidate_date),candidate_date)),
            first_observed=least(coalesce(first_observed,values(first_observed)),coalesce(values(first_observed),first_observed));
    end if;
    -- 源分区存在及最近7个自然日连续仅是基础核验；调用日期必须已由上游ETL确认完成。
    if (select count(*) from tmp_hr_calendar where stat_date between greatest('2020-01-01',date_sub(p_cutoff,interval 6 day),v_read_start) and p_cutoff)
       <> datediff(p_cutoff,greatest('2020-01-01',date_sub(p_cutoff,interval 6 day),v_read_start))+1 then
        signal sqlstate '45000' set message_text='cutoff source partitions are missing or discontinuous';
    end if;
    drop temporary table if exists tmp_hr_candidates;
    set v_stage='anchor candidates';
    create temporary table tmp_hr_candidates(
        scope_mode varchar(16),country_category varchar(20),country varchar(100),store varchar(100),msku varchar(500),
        anchor_date date,anchor_source varchar(40),date_conflict tinyint,first_observed date,
        candidate_date date,first_positive date,is_proxy tinyint,
        primary key(scope_mode,country_category,country,store,msku)
    ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    insert into tmp_hr_candidates
    select 'country' scope_mode,
        case when country='英国' then '英国站' when country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end country_category,
        country,store,msku,
        case when first_observed is null then null
            when candidate_date is not null and (first_positive is null or candidate_date<=first_positive) then candidate_date
            when candidate_date is null then first_observed else first_positive end anchor_date,
        case when first_observed is null then 'listing_without_business_evidence'
            when candidate_date is not null and (first_positive is null or candidate_date<=first_positive) then 'listing_or_product_date'
            when candidate_date is null then 'first_performance_record' else 'first_stock_or_sales' end anchor_source,
        if(candidate_date>first_positive,1,0) date_conflict,
        first_observed,candidate_date,first_positive,
        if(candidate_date is not null and (first_positive is null or candidate_date<=first_positive),0,1) from tmp_hr_meta;
    drop temporary table if exists tmp_hr_station_candidates;
    -- 全站点以各国家的有效起点为依据：存量国家优先冻结值，显式目标国家重建才取新值。
    create temporary table tmp_hr_station_candidates as
    select c.scope_mode,c.country_category,c.country,c.store,c.msku,
        if(p_reset_anchor=1 and p_scope='country' and c.country_category=p_category and c.country=p_country
            and c.store=p_store and c.msku=p_msku,c.anchor_date,
            coalesce(str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d'),c.anchor_date)) anchor_date,
        c.anchor_source,c.date_conflict,c.first_observed,c.candidate_date,c.first_positive,c.is_proxy
    from tmp_hr_candidates c left join dws_datasync.dws_product_sales_role_history r
      on r.scope_mode='country' and r.country_category=c.country_category and r.country=c.country and r.store=c.store and r.msku=c.msku;
    insert into tmp_hr_station_candidates
    select r.scope_mode,r.country_category,r.country,r.store,r.msku,
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d'),
        json_unquote(json_extract(r.evidence_json,'$.identity.anchor_source')),coalesce(json_extract(r.evidence_json,'$.identity.date_conflict'),0),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d'),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.candidate_date')),'null'),'%Y-%m-%d'),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.first_positive')),'null'),'%Y-%m-%d'),
        coalesce(json_extract(r.evidence_json,'$.identity.is_proxy'),1)
    from dws_datasync.dws_product_sales_role_history r left join tmp_hr_candidates c
      on c.scope_mode='country' and r.country_category=c.country_category and r.country=c.country and r.store=c.store and r.msku=c.msku
    where r.scope_mode='country' and c.msku is null;
    insert into tmp_hr_candidates
    select 'business_unit',country_category,'',store,msku,min(anchor_date),'earliest_station_anchor',max(date_conflict),min(first_observed),
        min(candidate_date),min(first_positive),max(is_proxy)
    from tmp_hr_station_candidates c group by country_category,store,msku;
    -- 历史静默商品即使近期没有源记录仍进入计算；候选表的当前观察不得改变已冻结起点。
    drop temporary table if exists tmp_hr_candidate_keys;
    create temporary table tmp_hr_candidate_keys as select scope_mode,country_category,country,store,msku from tmp_hr_candidates;
    insert into tmp_hr_candidates
    select r.scope_mode,r.country_category,r.country,r.store,r.msku,
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d'),
        json_unquote(json_extract(r.evidence_json,'$.identity.anchor_source')),
        coalesce(json_extract(r.evidence_json,'$.identity.date_conflict'),0),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d'),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.candidate_date')),'null'),'%Y-%m-%d'),
        str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.first_positive')),'null'),'%Y-%m-%d'),
        coalesce(json_extract(r.evidence_json,'$.identity.is_proxy'),1)
    from dws_datasync.dws_product_sales_role_history r left join tmp_hr_candidate_keys c
      on r.scope_mode=c.scope_mode and r.country_category=c.country_category and r.country=c.country and r.store=c.store and r.msku=c.msku
    where c.msku is null;
    drop temporary table if exists tmp_hr_expected_station;
    create temporary table tmp_hr_expected_station as
    select country_category,country,store,msku,anchor_date from tmp_hr_station_candidates;
    alter table tmp_hr_expected_station add index idx_station(country_category,store(32),msku(64),anchor_date);
    drop temporary table if exists tmp_hr_target;
    set v_stage='target identities';
    create temporary table tmp_hr_target(
        pid bigint unsigned not null auto_increment primary key,
        scope_mode varchar(16),country_category varchar(20),country varchar(100),store varchar(100),msku varchar(500),
        anchor_date date,recalc_start date,recalc_end date,source_read_start date,identity_doc json,old_doc json,
        key idx_target(scope_mode,country_category,country,store(32),msku(64)),
        key idx_target_product(store(32),msku(64),country_category,scope_mode,country)
    ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    insert into tmp_hr_target(scope_mode,country_category,country,store,msku,anchor_date,identity_doc,old_doc)
    select c.scope_mode,c.country_category,c.country,c.store,c.msku,
        if(p_reset_anchor=1,c.anchor_date,coalesce(str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d'),c.anchor_date)),
        if(r.evidence_json is not null and p_reset_anchor=0
            and str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is not null,json_extract(r.evidence_json,'$.identity'),
            json_object('anchor_date',c.anchor_date,'anchor_source',c.anchor_source,'is_proxy',c.is_proxy,
                        'candidate_date',c.candidate_date,'first_positive',c.first_positive,
                        'date_conflict',c.date_conflict,'date_conflict_reason',if(c.date_conflict=1,'candidate_after_first_stock_or_sales',null),
                        'first_observed',c.first_observed,'anchor_status',if(c.anchor_date is null,'pending','established'),
                        'history_before_2020_missing',if(c.anchor_date<'2020-01-01',1,0))),
        if(p_reset_anchor=1,json_object(),coalesce(r.evidence_json,json_object()))
    from tmp_hr_candidates c left join dws_datasync.dws_product_sales_role_history r
      on r.scope_mode=c.scope_mode and r.country_category=c.country_category and r.country=c.country and r.store=c.store and r.msku=c.msku
    where (p_mode='rebuild' and c.scope_mode=p_scope and c.country_category=p_category and c.country=p_country and c.store=p_store and c.msku=p_msku)
       or (p_mode<>'rebuild' and (r.data_date is null or r.data_date<p_cutoff
           or (p_mode='incremental' and c.anchor_date is not null
               and str_to_date(nullif(json_unquote(json_extract(r.evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null)));
    if p_mode='rebuild' and not exists(select 1 from tmp_hr_target) then signal sqlstate '45000' set message_text='rebuild product does not exist'; end if;
    set v_stage='recalculation windows';
    update tmp_hr_target set recalc_start=case
        when p_mode='rebuild' then greatest(anchor_date,date_add(anchor_date,interval (greatest(0,floor(datediff(p_from,anchor_date)/30))*30) day))
        when json_extract(old_doc,'$.calculation.cutoff') is null
            or str_to_date(nullif(json_unquote(json_extract(old_doc,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null then anchor_date
        else coalesce(str_to_date(nullif(json_unquote(json_extract(old_doc,'$.calculation.open_segment_start')),'null'),'%Y-%m-%d'),date_add(str_to_date(nullif(json_unquote(json_extract(old_doc,'$.calculation.cutoff')),'null'),'%Y-%m-%d'),interval 1 day)) end,
        recalc_end=if(p_mode='rebuild',least(p_cutoff,date_add(anchor_date,interval ((greatest(0,floor(datediff(p_to,anchor_date)/30))+1)*30-1) day)),p_cutoff);
    -- 起点可早于事实观测。补齐周期从起点开始，源读取从已知首次观测开始；无记录不补造零销量。
    update tmp_hr_target set source_read_start=greatest('2020-01-01',recalc_start,
        if(str_to_date(nullif(json_unquote(json_extract(old_doc,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null,
            coalesce(str_to_date(nullif(json_unquote(json_extract(identity_doc,'$.first_observed')),'null'),'%Y-%m-%d'),recalc_start),recalc_start));
    drop temporary table if exists tmp_hr_period;
    create temporary table tmp_hr_period(
        pid bigint,period_no int,qty decimal(24,4),amount decimal(24,4),profit decimal(24,4),
        observed_days int,stock_days int,anomaly_days int,small_rank int,rank_date date,missing_station_days int,
        primary key(pid,period_no)
    ) engine=innodb;
    select min(source_read_start) into v_scan_start from tmp_hr_target where anchor_date is not null;
    drop temporary table if exists tmp_hr_required;
    create temporary table tmp_hr_required(
        country varchar(100),store varchar(100),msku varchar(500),source_read_start date,recalc_end date,
        primary key(country,store,msku)
    ) engine=innodb default charset=utf8mb4 collate=utf8mb4_0900_ai_ci;
    if p_mode='incremental' and v_scan_start<v_read_start then
    -- 分开插入两种粒度，避免同一语句重复引用MySQL临时表。
    insert into tmp_hr_required
    select country,store,msku,source_read_start,recalc_end from tmp_hr_target
    where scope_mode='country' and anchor_date is not null and source_read_start<=recalc_end;
    insert into tmp_hr_required
    select e.country,t.store,t.msku,t.source_read_start,t.recalc_end
    from tmp_hr_target t join tmp_hr_expected_station e
      on t.scope_mode='business_unit' and t.country_category=e.country_category and t.store=e.store and t.msku=e.msku
    -- 全站点经营指标沿用原聚合口径；站点上架前的实际费用等记录仍须保留。
    where t.anchor_date is not null and t.source_read_start<=t.recalc_end
    on duplicate key update source_read_start=least(tmp_hr_required.source_read_start,values(source_read_start)),
        recalc_end=greatest(tmp_hr_required.recalc_end,values(recalc_end));
    end if;
    set v_stage='period aggregation';
    set v_year=year(v_scan_start);
    while v_year<=year(p_cutoff) do
        set v_stage=concat('aggregation ',v_year);
        update dws_datasync.dws_product_sales_role_history_run_log set stage=v_stage where run_id=v_run;
        -- 日常单年度更新复用身份发现阶段已去重的明细，避免第二遍源读取。
        if not (year(v_read_start)=year(p_cutoff) and v_year=year(p_cutoff) and v_scan_start>=v_read_start) then
            call dws_datasync.sp_product_history_load_year(p_source_schema,v_year,v_scan_start,p_cutoff,p_chunk,
                if(p_mode='incremental' and v_scan_start<v_read_start,2,if(p_mode in ('incremental','rebuild'),1,0)));
            insert ignore into tmp_hr_asin select distinct country,store,msku,asin from tmp_hr_raw;
        end if;
        drop temporary table if exists tmp_hr_daily;
        create temporary table tmp_hr_daily as
        select country,store,msku,stat_date,sum(qty) qty,sum(amount) amount,sum(profit) profit,max(stock) stock,max(anomaly) anomaly
        from tmp_hr_raw group by country,store,msku,stat_date;
        alter table tmp_hr_daily add index idx_day(country,store(32),msku(64),stat_date),
            add index idx_day_product(store(32),msku(64),stat_date,country);
        -- 缺失站点日=应有站点日数-实际观测站点日数，不逐产品逐日回查宽日表。
        -- 日历前缀累计数让任意范围计数变为两次主键查找；缺失日期仍计0。
        drop temporary table if exists tmp_hr_calendar_end;
        create temporary table tmp_hr_calendar_end as
        with recursive days as (
            select date_sub(makedate(v_year,1),interval 1 day) d
            union all select date_add(d,interval 1 day) from days
            where d<date_sub(makedate(v_year+1,1),interval 1 day)
        )
        select days.d stat_date,sum(case when days.d>=makedate(v_year,1) and cal.stat_date is not null then 1 else 0 end)
            over(order by days.d rows unbounded preceding) observed_cum
        from days left join tmp_hr_calendar cal on cal.stat_date=days.d;
        alter table tmp_hr_calendar_end add primary key(stat_date);
        -- MySQL temporary表同一语句不能引用两次；复制367行以内的前缀表。
        drop temporary table if exists tmp_hr_calendar_start;
        create temporary table tmp_hr_calendar_start like tmp_hr_calendar_end;
        insert into tmp_hr_calendar_start select * from tmp_hr_calendar_end;
        drop temporary table if exists tmp_hr_expected_period;
        create temporary table tmp_hr_expected_period as
        with recursive offsets as (
            select 0 k union all select k+1 from offsets where k<13
        ), bounds as (
            select t.pid,t.anchor_date,
                greatest(t.recalc_start,e.anchor_date,makedate(v_year,1)) bs,
                least(t.recalc_end,date_sub(makedate(v_year+1,1),interval 1 day)) be
            from tmp_hr_target t join tmp_hr_expected_station e
              on t.scope_mode='business_unit' and t.country_category=e.country_category and t.store=e.store and t.msku=e.msku
            where e.anchor_date is not null
        ), windows as (
            select b.*,floor(datediff(bs,anchor_date)/30)+1+k n from bounds b cross join offsets
            where bs<=be and floor(datediff(bs,anchor_date)/30)+k<=floor(datediff(be,anchor_date)/30)
        )
        select pid,n period_no,sum(hi.observed_cum-lo.observed_cum) expected_days
        from windows
        join tmp_hr_calendar_end hi on hi.stat_date=least(be,date_add(anchor_date,interval (n*30-1) day))
        join tmp_hr_calendar_start lo on lo.stat_date=date_sub(greatest(bs,date_add(anchor_date,interval ((n-1)*30) day)),interval 1 day)
        group by pid,n;
        alter table tmp_hr_expected_period add primary key(pid,period_no);
        drop temporary table if exists tmp_hr_observed_period;
        create temporary table tmp_hr_observed_period as
        select t.pid,floor(datediff(d.stat_date,t.anchor_date)/30)+1 period_no,count(*) observed_days
        from tmp_hr_daily d join tmp_hr_target t
          on t.scope_mode='business_unit' and t.store=d.store and t.msku=d.msku
          and t.country_category=case when d.country='英国' then '英国站' when d.country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end
          and d.stat_date between t.recalc_start and t.recalc_end
        join tmp_hr_expected_station e
          on e.country_category=t.country_category and e.country=d.country and e.store=d.store and e.msku=d.msku
          and d.stat_date>=e.anchor_date
        group by t.pid,period_no;
        alter table tmp_hr_observed_period add primary key(pid,period_no);
        drop temporary table if exists tmp_hr_missing_station;
        create temporary table tmp_hr_missing_station as
        select e.pid,e.period_no,e.expected_days-coalesce(o.observed_days,0) missing_station_days
        from tmp_hr_expected_period e left join tmp_hr_observed_period o on o.pid=e.pid and o.period_no=e.period_no
        where e.expected_days<>coalesce(o.observed_days,0);
        alter table tmp_hr_missing_station add primary key(pid,period_no);
        if exists(select 1 from tmp_hr_missing_station where missing_station_days<0) then
            signal sqlstate '45000' set message_text='observed station days exceed expected calendar days';
        end if;
        drop temporary table if exists tmp_hr_rank;
        create temporary table tmp_hr_rank as
        select country,store,msku,stat_date,small_rank from
          (select country,store,msku,stat_date,small_rank,row_number() over(partition by country,store,msku,stat_date order by source_time desc,source_id desc) rn from tmp_hr_raw) r where rn=1;
        alter table tmp_hr_rank add index idx_rank(country,store(32),msku(64),stat_date);
        drop temporary table if exists tmp_hr_joined;
        create temporary table tmp_hr_joined as
        select t.pid,floor(datediff(d.stat_date,t.anchor_date)/30)+1 period_no,d.stat_date,
            sum(d.qty) qty,sum(d.amount) amount,sum(d.profit) profit,max(d.stock) stock,max(d.anomaly) anomaly,max(r.small_rank) small_rank
        from tmp_hr_target t join tmp_hr_daily d on t.store=d.store and t.msku=d.msku
            and t.country_category=case when d.country='英国' then '英国站' when d.country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end
            and (t.scope_mode='business_unit' or t.country=d.country)
            and d.stat_date between t.recalc_start and t.recalc_end
        left join tmp_hr_rank r on r.country=d.country and r.store=d.store and r.msku=d.msku and r.stat_date=d.stat_date
        group by t.pid,period_no,d.stat_date;
        insert into tmp_hr_period
        select x.pid,x.period_no,sum(x.qty),sum(x.amount),sum(x.profit),count(*),sum(x.stock>0),sum(x.anomaly),
            max(case when x.rn=1 then x.small_rank end),max(x.stat_date),coalesce(max(m.missing_station_days),0)
        from (select j.*,row_number() over(partition by pid,period_no order by stat_date desc) rn from tmp_hr_joined j) x
        left join tmp_hr_missing_station m on m.pid=x.pid and m.period_no=x.period_no
        group by x.pid,x.period_no
        on duplicate key update
            qty=tmp_hr_period.qty+values(qty),amount=tmp_hr_period.amount+values(amount),profit=tmp_hr_period.profit+values(profit),
            observed_days=tmp_hr_period.observed_days+values(observed_days),stock_days=tmp_hr_period.stock_days+values(stock_days),anomaly_days=tmp_hr_period.anomaly_days+values(anomaly_days),
            small_rank=if(values(rank_date)>tmp_hr_period.rank_date,values(small_rank),tmp_hr_period.small_rank),rank_date=greatest(tmp_hr_period.rank_date,values(rank_date)),
            missing_station_days=tmp_hr_period.missing_station_days+values(missing_station_days);
        set v_year=v_year+1;
    end while;
    -- 每产品一个事务：历史与主导一同发布，已提交产品是失败恢复的检查点。
    set v_concat_old=@@session.group_concat_max_len;
    set session group_concat_max_len=greatest(v_concat_old,65536);
    set v_stage='atomic product publication';
    update dws_datasync.dws_product_sales_role_history_run_log set stage=v_stage where run_id=v_run;
    drop temporary table if exists tmp_hr_nodes;
    create temporary table tmp_hr_nodes(period_no int primary key,node_doc json) engine=innodb;
    drop temporary table if exists tmp_hr_votes;
    create temporary table tmp_hr_votes(role_id int primary key,votes int,last_period int) engine=innodb;
    drop temporary table if exists tmp_hr_history_doc;
    create temporary table tmp_hr_history_doc(doc json not null) engine=innodb;
    publish_products: loop
        select min(pid) into v_next from tmp_hr_target where pid>v_pid;
        if v_next is null then leave publish_products; end if;
        set v_pid=v_next;
        select anchor_date,recalc_start,recalc_end,scope_mode,identity_doc,old_doc into v_anchor,v_begin,v_end,v_scope,v_identity,v_old
        from tmp_hr_target where pid=v_pid;
        delete from tmp_hr_nodes;
        if p_mode<>'incremental' and json_type(json_extract(v_old,'$.history'))='ARRAY' then
            insert into tmp_hr_nodes select period_no,node_doc from json_table(v_old,'$.history[*]' columns(period_no int path '$.period_no',node_doc json path '$')) j
            where p_reset_anchor=0 and (v_anchor is null or str_to_date(nullif(json_unquote(json_extract(node_doc,'$.end')),'null'),'%Y-%m-%d') < v_begin or str_to_date(nullif(json_unquote(json_extract(node_doc,'$.start')),'null'),'%Y-%m-%d') > v_end);
        end if;
        if v_anchor is not null and v_begin<=v_end then
            insert into tmp_hr_nodes
            with recursive seq as (
                select greatest(0,floor(datediff(v_begin,v_anchor)/30))+1 n
                union all select n+1 from seq where n<floor(datediff(v_end,v_anchor)/30)+1
            ), metrics as (
                select s.n,date_add(v_anchor,interval ((s.n-1)*30) day) ws,date_add(v_anchor,interval (s.n*30-1) day) we,
                    coalesce(p.qty,0) qty,coalesce(p.amount,0) amount,coalesce(p.profit,0) profit,
                    coalesce(p.observed_days,0) observed_days,coalesce(p.stock_days,0) stock_days,coalesce(p.anomaly_days,0) anomaly_days,
                    p.small_rank,p.rank_date,coalesce(p.missing_station_days,0) missing_station_days from seq s left join tmp_hr_period p on p.pid=v_pid and p.period_no=s.n
            ), measured as (
                select m.*,datediff(least(we,p_cutoff),ws)+1 elapsed,
                    if(amount>0,profit/amount,0) margin,
                    qty/(datediff(least(we,p_cutoff),ws)+1) daily_sales_value from metrics m
            ), classified as (
                select m.*,if(observed_days=0,null,
                    -- classifier:begin
case when daily_sales_value is null or daily_sales_value<0 or margin is null then null
when v_scope='business_unit' then case when (daily_sales_value > 5 and margin > .15) or (daily_sales_value between 1 and 5 and margin > .25) then 101
        when (daily_sales_value > 5 and margin between .05 and .15) or (daily_sales_value between 1 and 5 and margin between .10 and .25) then 102
        when (daily_sales_value between 1 and 5 and margin >= .05 and margin < .10)
            or (daily_sales_value > 0 and daily_sales_value < 1 and margin >= .05)
            or (daily_sales_value > 1 and margin < .05) then 103
        when daily_sales_value = 0 or (daily_sales_value > 0 and daily_sales_value <= 1 and margin < .05) then 104 else null end
when v_scope='country' then case when daily_sales_value = 0 or (daily_sales_value > 0 and daily_sales_value <= 1 and margin < .05) then 1304
        when daily_sales_value > 0 and daily_sales_value <= 1 and margin >= .05 and (small_rank is null or small_rank in (0,99999)) then 1304
        when small_rank between 51 and 100 and ((daily_sales_value > 3 and margin >= .15) or (daily_sales_value between 1 and 3 and margin >= .25)) then 1302
        when small_rank between 1 and 50 and ((daily_sales_value > 3 and margin >= .15) or (daily_sales_value between 1 and 3 and margin >= .25)) then 1301
        when small_rank between 1 and 100 and ((daily_sales_value > 3 and margin >= .05 and margin < .15) or (daily_sales_value between 1 and 3 and margin >= .10 and margin < .25)) then 1302
        when daily_sales_value > 1 and margin < .05 then 1303
        when daily_sales_value > 1 and margin >= .05 and (small_rank is null or small_rank in (0,99999)) then 1303
        when ((daily_sales_value between 1 and 3 and margin >= .05 and margin < .10) or (daily_sales_value > 0 and daily_sales_value < 1 and margin >= .05)) and small_rank between 1 and 100 then 1303
        when daily_sales_value > 0 and margin >= .05 and small_rank > 100 and small_rank <> 99999 then 1303 else null end
else null end
                    -- classifier:end
                ) role_id from measured m
            ), eligible as (
                select c.*,(we<=p_cutoff and stock_days>0 and observed_days=30 and anomaly_days=0 and missing_station_days=0 and ws>='2020-01-01' and role_id is not null) vote
                from classified c
            )
            select n,json_object('period_no',n,'start',ws,'end',we,'calculated_through',least(we,p_cutoff),'complete',if(we<=p_cutoff,1,0),
                'role_id',role_id,'role',case role_id when 101 then '明星' when 1301 then '明星' when 102 then '潜力' when 1302 then '潜力' when 103 then '瘦狗' when 1303 then '瘦狗' when 104 then '问题' when 1304 then '问题' end,
                'sales_qty',if(observed_days=0,null,qty),'sales_amount',if(observed_days=0,null,amount),'predict_gross_profit',if(observed_days=0,null,profit),
                'daily_sales',if(observed_days=0,null,qty/elapsed),'margin_rate',if(observed_days=0,null,margin),
                'small_rank',if(v_scope='country',small_rank,null),'small_rank_date',if(v_scope='country',rank_date,null),
                'observed_days',observed_days,'stock_days',stock_days,'anomaly_days',anomaly_days,'missing_station_days',missing_station_days,'vote_eligible',vote,
                'exclusion_reason',case when vote=1 then null when ws<'2020-01-01' then 'before_source_history' when we>p_cutoff then 'incomplete_segment'
                    when observed_days<30 then 'missing_daily_data' when missing_station_days>0 then 'missing_station_daily_data'
                    when anomaly_days>0 then 'source_anomaly' when stock_days=0 then 'all_segment_out_of_stock' else 'unclassified_role' end)
            from eligible;
        end if;
        select count(*) into v_total from tmp_hr_nodes;
        -- 只拼接按周期排序的数字路径；经营JSON不转文本，保留原生数值类型。
        set v_history=json_array();
        if v_total=1 then
            select json_array(node_doc) into v_history from tmp_hr_nodes;
        elseif v_total>1 then
            select group_concat(quote(concat('$."',period_no,'"')) order by period_no separator ',') into v_paths from tmp_hr_nodes;
            if v_paths is null or char_length(v_paths)>=@@session.group_concat_max_len then
                signal sqlstate '45000' set message_text='history path list exceeds session limit';
            end if;
            delete from tmp_hr_history_doc;
            set @hr_sql=concat('insert into tmp_hr_history_doc select json_extract(json_objectagg(cast(period_no as char),node_doc),',v_paths,') from tmp_hr_nodes');
            prepare hr_stmt from @hr_sql; execute hr_stmt; deallocate prepare hr_stmt;
            select doc into v_history from tmp_hr_history_doc;
        end if;
        -- history assembly:end
        if p_mode='incremental' then
            set v_frozen=json_extract(v_old,'$.history');
            if json_type(v_frozen)='ARRAY' then
                -- 增量只会替换原尾段。其余冻结节点直接复用原生数组。
                if v_begin is not null and str_to_date(nullif(json_unquote(json_extract(v_frozen,'$[last].end')),'null'),'%Y-%m-%d')>=v_begin then
                    set v_frozen=json_remove(v_frozen,'$[last]');
                end if;
            else
                set v_frozen=json_array();
            end if;
            set v_history=json_merge_preserve(v_frozen,v_history);
        end if;
        set v_total=json_length(v_history);
        delete from tmp_hr_votes;
        insert into tmp_hr_votes
        select role_id,count(*) votes,max(period_no) last_period from json_table(v_history,'$[*]' columns(
            period_no int path '$.period_no',role_id int path '$.role_id',eligible int path '$.vote_eligible'
        )) n where eligible=1 group by role_id;
        select coalesce(sum(votes),0) into v_valid from tmp_hr_votes;
        set v_role=null;
        set v_tied=0;
        set v_last_valid=null;
        set v_tie_roles=json_array();
        if v_valid>0 then
            select role_id into v_role from tmp_hr_votes order by votes desc,last_period desc limit 1;
            select max(votes) into v_max_votes from tmp_hr_votes;
            select count(*) into v_tied from tmp_hr_votes where votes=v_max_votes;
            select json_arrayagg(role_id) into v_tie_roles from tmp_hr_votes where votes=v_max_votes;
            select last_period into v_last_valid from tmp_hr_votes where role_id=v_role;
        end if;
        -- 会话temporary表不可在一个语句中反复引用，单次聚合构造分布。
        select json_object('star',coalesce(sum(if(role_id in (101,1301),votes,0)),0),
            'potential',coalesce(sum(if(role_id in (102,1302),votes,0)),0),
            'dog',coalesce(sum(if(role_id in (103,1303),votes,0)),0),
            'problem',coalesce(sum(if(role_id in (104,1304),votes,0)),0)),
            json_object('star',if(v_valid=0,null,coalesce(sum(if(role_id in (101,1301),votes,0)),0)/v_valid),
            'potential',if(v_valid=0,null,coalesce(sum(if(role_id in (102,1302),votes,0)),0)/v_valid),
            'dog',if(v_valid=0,null,coalesce(sum(if(role_id in (103,1303),votes,0)),0)/v_valid),
            'problem',if(v_valid=0,null,coalesce(sum(if(role_id in (104,1304),votes,0)),0)/v_valid))
        into v_counts,v_shares from tmp_hr_votes;
        set v_dominant=json_object('role_id',v_role,'role',case v_role when 101 then '明星' when 1301 then '明星' when 102 then '潜力' when 1302 then '潜力' when 103 then '瘦狗' when 1303 then '瘦狗' when 104 then '问题' when 1304 then '问题' end,
            'valid_segment_count',v_valid,'excluded_segment_count',v_total-v_valid,'tie',if(v_tied>1,1,0),
            'max_count_role_ids',v_tie_roles,'max_count_role_count',v_tied,'selected_latest_valid_period',v_last_valid,
            'tie_break','most_recent_valid_segment','counts',v_counts,'shares',v_shares,
            'share',if(v_valid=0,null,v_max_votes/v_valid));
        select coalesce(json_arrayagg(asin),json_array()) into v_asins from (
            select distinct a.asin from tmp_hr_asin a join tmp_hr_target t on t.pid=v_pid and t.store=a.store and t.msku=a.msku
            and (t.scope_mode='business_unit' or t.country=a.country)
            and t.country_category=case when a.country='英国' then '英国站' when a.country in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end
            where a.asin<>''
            union select j.asin from json_table(
                if(p_reset_anchor=0,coalesce(json_extract(v_old,'$.identity.asins'),json_array()),json_array()),
                '$[*]' columns(asin varchar(40) path '$')) j
        ) aa;
        set v_identity=json_set(v_identity,'$.asins',v_asins);
        set v_doc=json_object('identity',v_identity,'history',v_history,'dominant_role',v_dominant,
            'quality',json_object('source_history_start','2020-01-01','segment_count',v_total,'non_voting_count',v_total-v_valid,
                'interpretation','recomputed_with_current_rules','missing_is_not_zero_sales',true),
            'calculation',json_object('rule_version',v_version,'cutoff',p_cutoff,'source_schema',p_source_schema,
                'source_tables','lx_statistics_product_performance_2020..2025 + lx_statistics_product_performance',
                'frozen_completed_segments',true,'last_mode',p_mode,
                'open_segment_start',if(v_anchor is null or mod(datediff(p_cutoff,v_anchor)+1,30)=0,null,date_add(v_anchor,interval (floor(datediff(p_cutoff,v_anchor)/30)*30) day))));
        start transaction;
        insert into dws_datasync.dws_product_sales_role_history(scope_mode,country_category,country,store,msku,data_date,evidence_json)
        select scope_mode,country_category,country,store,msku,p_cutoff,v_doc from tmp_hr_target where pid=v_pid
        on duplicate key update data_date=values(data_date),evidence_json=values(evidence_json),updated_time=now(6);
        update dws_datasync.dws_product_sales_role_history_run_log set published_products=published_products+1,stage=v_stage where run_id=v_run;
        commit;
    end loop;
    set session group_concat_max_len=v_concat_old;
    update dws_datasync.dws_product_sales_role_history_run_log set status='success',stage='complete',finished_at=now(6) where run_id=v_run;
    commit;
    do release_lock(v_lock);
    select run_id,run_mode,cutoff,status,published_products from dws_datasync.dws_product_sales_role_history_run_log where run_id=v_run;
end$$

-- 定时任务入口：按产品表现续表最新业务日推进；无需手填日期。
drop procedure if exists dws_datasync.sp_product_role_history_incremental$$
create procedure dws_datasync.sp_product_role_history_incremental()
sql security invoker
scheduled: begin
    declare v_latest varchar(100);
    declare v_cutoff date;
    declare v_min_processed date;
    declare v_max_processed date;
    declare v_unprocessed bigint;

    select max(start_date) into v_latest
    from dwd_datasync.lx_statistics_product_performance;
    if v_latest is null then
        select 'skipped' status,'source_empty' reason,cast(null as date) cutoff;
        leave scheduled;
    end if;
    if v_latest not regexp '^[0-9]{4}-[0-9]{2}-[0-9]{2}($| )' then
        signal sqlstate '45000' set message_text='invalid latest source date';
    end if;
    set v_cutoff=str_to_date(left(v_latest,10),'%Y-%m-%d');
    if v_cutoff is null or v_cutoff<'2020-01-01' then
        signal sqlstate '45000' set message_text='invalid latest source date';
    end if;
    if v_cutoff>=date(utc_timestamp()+interval 8 hour) then
        select 'skipped' status,'latest_day_not_closed' reason,v_cutoff cutoff;
        leave scheduled;
    end if;
    if not exists(select 1 from dws_datasync.dws_product_sales_role_history) then
        signal sqlstate '45000' set message_text='initialize history before scheduled incremental';
    end if;
    select min(data_date),max(data_date),sum(data_date is null)
    into v_min_processed,v_max_processed,v_unprocessed
    from dws_datasync.dws_product_sales_role_history;
    if v_max_processed>v_cutoff then
        select 'skipped' status,'source_date_behind_history' reason,v_cutoff cutoff;
        leave scheduled;
    end if;
    if v_min_processed=v_cutoff and v_max_processed=v_cutoff and v_unprocessed=0
       and not exists(select 1 from dws_datasync.dws_product_sales_role_history
           where str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.anchor_date')),'null'),'%Y-%m-%d') is null
             and str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.identity.first_observed')),'null'),'%Y-%m-%d') is not null) then
        select 'skipped' status,'already_current' reason,v_cutoff cutoff;
        leave scheduled;
    end if;
    call dws_datasync.sp_product_role_history(
        'incremental',v_cutoff,'dwd_datasync',
        null,null,null,null,null,null,null,0,50000
    );
end$$
delimiter ;
set session sql_mode=@hr_deploy_sql_mode;

-- section:deploy:end

-- 第2段：历史首算
-- section:bootstrap:begin
/*
-- 先执行“建表与计算.sql”；使用独立连接，autocommit=1，不开启外部事务。
-- 必填：上游已确认完整且早于北京时间今天的数据日；不能只取源表max日期。
set @role_history_cutoff=null;
-- 例如确认2026-10-09完整后：set @role_history_cutoff='2026-10-09';
set @role_history_source='dwd_datasync';
set @role_history_chunk=50000;

call dws_datasync.sp_product_role_history(
    'bootstrap',@role_history_cutoff,@role_history_source,
    null,null,null,null,null,null,null,0,@role_history_chunk
);

-- 可从另一连接查询进度：
select run_id,run_mode,cutoff,status,stage,published_products,started_at,finished_at,error_message
from dws_datasync.dws_product_sales_role_history_run_log order by started_at desc limit 10;
*/
-- section:bootstrap:end

-- 第3段：日常增量（定时任务直接运行这一条call）
-- section:incremental:begin
/*
-- 首算/导入成功后使用；自动读取续表max(start_date)，已处理且无可初始化的旧待核身份则跳过。
-- 按用户确认口径不依赖同步成功日志；同一天内回补数据仍须显式重算。
call dws_datasync.sp_product_role_history_incremental();

select run_id,run_mode,cutoff,status,stage,published_products,started_at,finished_at,error_message
from dws_datasync.dws_product_sales_role_history_run_log order by started_at desc limit 10;
*/
-- section:incremental:end

-- 第4段：指定区间重算
-- section:rebuild:begin
/*
-- 必填下面6个身份/区间参数。business_unit的country必须为''；msku填写完整值。
-- 局部重算保留起点，以产品当前data_date为截止日，不推进处理日期。
set @role_history_scope='country';
set @role_history_category='欧洲站';
set @role_history_country='德国';
set @role_history_store=null;
set @role_history_msku=null;
set @role_history_from=null;
set @role_history_to=null;
set @role_history_source='dwd_datasync';
set @role_history_chunk=50000;

set @role_history_cutoff=(
    select data_date from dws_datasync.dws_product_sales_role_history
    where scope_mode=@role_history_scope and country_category=@role_history_category
      and country=@role_history_country and store=@role_history_store and msku=@role_history_msku
);

call dws_datasync.sp_product_role_history(
    'rebuild',@role_history_cutoff,@role_history_source,
    @role_history_from,@role_history_to,@role_history_scope,@role_history_category,
    @role_history_country,@role_history_store,@role_history_msku,0,@role_history_chunk
);

-- 起点修正：单独选中执行下面的完整产品重建，不与上面的局部重算一起执行。
-- cutoff仍须是已确认完整的数据日；from固定2020-01-01，to等于cutoff。
-- call dws_datasync.sp_product_role_history(
--     'rebuild',@role_history_cutoff,@role_history_source,
--     '2020-01-01',@role_history_cutoff,@role_history_scope,@role_history_category,
--     @role_history_country,@role_history_store,@role_history_msku,1,@role_history_chunk
-- );

select data_date,evidence_json from dws_datasync.dws_product_sales_role_history
where scope_mode=@role_history_scope and country_category=@role_history_category
  and country=@role_history_country and store=@role_history_store and msku=@role_history_msku;
*/
-- section:rebuild:end

-- 第5段：只读验收
-- section:acceptance:begin
/*
-- 本文件只含会话变量、select、show、explain；按阶段选中执行。

-- 1. 部署前：版本、字符集、7张表现表及Listing结构、当前表日期首列索引。
select version() mysql_version,@@session.sql_mode sql_mode,@@session.autocommit autocommit;
select table_name,column_name,column_type,character_set_name,collation_name
from information_schema.columns where table_schema='dwd_datasync'
  and (table_name in ('lx_statistics_product_performance','lx_sales_mws_listing')
       or table_name regexp '^lx_statistics_product_performance_202[0-5]$')
order by table_name,ordinal_position;
select table_name,index_name,seq_in_index,column_name
from information_schema.statistics where table_schema='dwd_datasync'
  and table_name='lx_statistics_product_performance' order by index_name,seq_in_index;

-- 首算前覆盖检查：会扫描各年度表，建议在低峰期单独执行并保存结果。
select '2020' source_year,min(start_date) first_date,max(end_date) last_date,count(*) rows_total,
    sum(end_date is null or start_date<>end_date) non_daily_rows from dwd_datasync.lx_statistics_product_performance_2020
union all select '2021',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance_2021
union all select '2022',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance_2022
union all select '2023',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance_2023
union all select '2024',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance_2024
union all select '2025',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance_2025
union all select 'current',min(start_date),max(end_date),count(*),sum(end_date is null or start_date<>end_date) from dwd_datasync.lx_statistics_product_performance;

-- 2. 部署后：表结构及运行状态。
show create table dws_datasync.dws_product_sales_role_history;
select run_id,run_mode,cutoff,status,stage,published_products,started_at,finished_at,error_message
from dws_datasync.dws_product_sales_role_history_run_log order by started_at desc limit 20;
select scope_mode,country_category,count(*) products,min(data_date) min_cutoff,max(data_date) max_cutoff,
    sum(json_unquote(json_extract(evidence_json,'$.identity.anchor_status'))='pending') pending_anchors
from dws_datasync.dws_product_sales_role_history group by scope_mode,country_category;

-- 按国家类别＋店铺＋完整MSKU核对当前有效Listing覆盖；不按国家拆分计数。
-- absent_from_history非0时逐键核验来源，无历史表现的Listing不能补造经营数据。
with listing_keys as (
    select distinct case when marketplace='英国' then '英国站'
        when marketplace in ('美国','加拿大','巴西','墨西哥') then '北美站' else '欧洲站' end country_category,
        substring_index(substring_index(seller_name,' ',1),'-',1) store,seller_sku msku
    from dwd_datasync.lx_sales_mws_listing
    where seller_sku is not null and trim(seller_sku)<>''
      and lower(trim(seller_sku)) not like 'amzn.gr%' and lower(trim(seller_sku)) not like 'amazon%'
)
select l.country_category,count(*) listing_products,sum(r.msku is not null) history_products,
    sum(r.msku is null) absent_from_history
from listing_keys l left join dws_datasync.dws_product_sales_role_history r
    on r.scope_mode='business_unit' and r.country_category=l.country_category and r.country=''
    and r.store=l.store and r.msku=l.msku group by l.country_category;

-- 3. 周期重复、30天边界、主导次数：结果应为空。
with nodes as (
    select r.scope_mode,r.country_category,r.country,r.store,r.msku,j.*
    from dws_datasync.dws_product_sales_role_history r
    join json_table(r.evidence_json,'$.history[*]' columns(
        period_no int path '$.period_no',start_date date path '$.start',end_date date path '$.end'
    )) j on true
)
select scope_mode,country_category,country,store,msku,period_no,count(*) copies,
    min(datediff(end_date,start_date)+1) period_days from nodes
group by scope_mode,country_category,country,store,msku,period_no
having count(*)<>1 or min(datediff(end_date,start_date)+1)<>30;

select scope_mode,country_category,country,store,msku from dws_datasync.dws_product_sales_role_history
where json_extract(evidence_json,'$.dominant_role.valid_segment_count') <>
      json_extract(evidence_json,'$.dominant_role.counts.star')+
      json_extract(evidence_json,'$.dominant_role.counts.potential')+
      json_extract(evidence_json,'$.dominant_role.counts.dog')+
      json_extract(evidence_json,'$.dominant_role.counts.problem');

-- 4. 查询单个产品及周期：填写实际身份。也是重算/增量前后冻结节点核对的入口。
set @role_check_scope='country';
set @role_check_category='欧洲站';
set @role_check_country='德国';
set @role_check_store=null;
set @role_check_msku=null;
select r.data_date,j.period_no,j.start_date,j.end_date,j.complete,j.role_id,j.qty,j.daily_sales,
       j.margin_rate,j.small_rank,j.rank_date,j.observed_days,j.stock_days,j.vote_eligible,j.reason,
       sha2(cast(j.node_doc as char),256) node_hash
from dws_datasync.dws_product_sales_role_history r
join json_table(r.evidence_json,'$.history[*]' columns(
    period_no int path '$.period_no',start_date date path '$.start',end_date date path '$.end',
    complete int path '$.complete',role_id int path '$.role_id',qty decimal(24,4) path '$.sales_qty',
    daily_sales decimal(24,10) path '$.daily_sales',margin_rate decimal(24,10) path '$.margin_rate',
    small_rank int path '$.small_rank',rank_date date path '$.small_rank_date',
    observed_days int path '$.observed_days',stock_days int path '$.stock_days',
    vote_eligible int path '$.vote_eligible',reason varchar(80) path '$.exclusion_reason',node_doc json path '$'
)) j on true
where r.scope_mode=@role_check_scope and r.country_category=@role_check_category
  and r.country=@role_check_country and r.store=@role_check_store and r.msku=@role_check_msku
order by j.period_no;

-- 5. 当前30d标签仅在窗口起止完全相同的时候才可比较，不要直接对比任意历史段。
-- 返回相同窗口的样本及差异；零行表示目前没有重合窗口，不能解释为核对通过。
select r.scope_mode,r.country_category,r.country,r.store,r.msku,j.period_no,
    j.role_id history_role_id,l.label_id current_label_id,
    round(j.qty,4)-cast(json_unquote(json_extract(l.evidence_json,'$.metrics.period_sales_qty')) as decimal(24,4)) qty_diff,
    round(j.daily_sales,4)-cast(json_unquote(json_extract(l.evidence_json,'$.metrics.daily_sales')) as decimal(24,4)) daily_sales_diff,
    round(j.margin_rate*100,4)-cast(json_unquote(json_extract(l.evidence_json,'$.metrics.tag_margin_rate')) as decimal(24,4)) margin_percentage_point_diff,
    j.small_rank history_small_rank,json_extract(l.evidence_json,'$.metrics.small_rank') current_small_rank
from dws_datasync.dws_product_sales_role_history r
join json_table(r.evidence_json,'$.history[*]' columns(
    period_no int path '$.period_no',start_date date path '$.start',end_date date path '$.end',
    complete int path '$.complete',role_id int path '$.role_id',qty decimal(24,4) path '$.sales_qty',
    daily_sales decimal(24,10) path '$.daily_sales',margin_rate decimal(24,10) path '$.margin_rate',
    small_rank int path '$.small_rank'
)) j on j.complete=1
join dws_datasync.dws_标签表 l on l.country_category=r.country_category and coalesce(l.country,'')=r.country
    and l.store=r.store and l.msku=r.msku and l.label_period='30d' and l.data_date=j.end_date
    and ((r.scope_mode='business_unit' and l.label_id in (101,102,103,104))
      or (r.scope_mode='country' and l.label_id in (1301,1302,1303,1304)))
    and str_to_date(json_unquote(json_extract(l.evidence_json,'$.window.start')),'%Y-%m-%d')=j.start_date
    and str_to_date(json_unquote(json_extract(l.evidence_json,'$.window.end')),'%Y-%m-%d')=j.end_date
where r.store=@role_check_store and r.msku=@role_check_msku limit 100;

-- 阈值边界核对：expected_role应等于actual_role。
with cases as (
    select 'business_unit' scope_mode,6 daily_sales_value,.15 margin,cast(null as signed) small_rank,102 expected_role
    union all select 'business_unit',6,.15001,null,101
    union all select 'country',4,.15,50,1301
    union all select 'country',4,.15,51,1302
    union all select 'country',.5,.2,null,1304
    union all select 'country',2,.2,null,1303
)
select cases.*,case when daily_sales_value is null or daily_sales_value<0 or margin is null then null
when scope_mode='business_unit' then case when (daily_sales_value > 5 and margin > .15) or (daily_sales_value between 1 and 5 and margin > .25) then 101
        when (daily_sales_value > 5 and margin between .05 and .15) or (daily_sales_value between 1 and 5 and margin between .10 and .25) then 102
        when (daily_sales_value between 1 and 5 and margin >= .05 and margin < .10)
            or (daily_sales_value > 0 and daily_sales_value < 1 and margin >= .05)
            or (daily_sales_value > 1 and margin < .05) then 103
        when daily_sales_value = 0 or (daily_sales_value > 0 and daily_sales_value <= 1 and margin < .05) then 104 else null end
when scope_mode='country' then case when daily_sales_value = 0 or (daily_sales_value > 0 and daily_sales_value <= 1 and margin < .05) then 1304
        when daily_sales_value > 0 and daily_sales_value <= 1 and margin >= .05 and (small_rank is null or small_rank in (0,99999)) then 1304
        when small_rank between 51 and 100 and ((daily_sales_value > 3 and margin >= .15) or (daily_sales_value between 1 and 3 and margin >= .25)) then 1302
        when small_rank between 1 and 50 and ((daily_sales_value > 3 and margin >= .15) or (daily_sales_value between 1 and 3 and margin >= .25)) then 1301
        when small_rank between 1 and 100 and ((daily_sales_value > 3 and margin >= .05 and margin < .15) or (daily_sales_value between 1 and 3 and margin >= .10 and margin < .25)) then 1302
        when daily_sales_value > 1 and margin < .05 then 1303
        when daily_sales_value > 1 and margin >= .05 and (small_rank is null or small_rank in (0,99999)) then 1303
        when ((daily_sales_value between 1 and 3 and margin >= .05 and margin < .10) or (daily_sales_value > 0 and daily_sales_value < 1 and margin >= .05)) and small_rank between 1 and 100 then 1303
        when daily_sales_value > 0 and margin >= .05 and small_rank > 100 and small_rank <> 99999 then 1303 else null end
else null end actual_role from cases;

-- 6. 增量范围：查看最早需要读取的日期，而非全历史起点。
select min(coalesce(
    str_to_date(nullif(json_unquote(json_extract(evidence_json,'$.calculation.open_segment_start')),'null'),'%Y-%m-%d'),
    date_add(data_date,interval 1 day)
)) next_scan_start from dws_datasync.dws_product_sales_role_history;
-- 在现库已核验索引idx_osp_performance_date_sync；若环境不同，以步骤1实际索引为准。
-- 替换成真实增量范围。这是加载器一次取得近期ID的实际访问方式。
-- 预期使用日期索引范围访问，不涉及2020—2025表；后续分页作用于临时ID表。
explain select id from dwd_datasync.lx_statistics_product_performance
force index (idx_osp_performance_date_sync)
where start_date between '2026-09-10' and '2026-10-09';
*/
-- section:acceptance:end
