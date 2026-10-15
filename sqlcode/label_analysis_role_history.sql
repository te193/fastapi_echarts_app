-- 仅在已配置的内网分析结果库创建独立结果表，源业务表只读。
create table if not exists dashboard_analysis_role_snapshot (
    batch_id char(36) character set ascii collate ascii_bin primary key,
    state varchar(20) not null,
    source_date date null,
    formula_version varchar(64) not null,
    row_count bigint not null default 0,
    manifest json null,
    created_at datetime(6) not null default current_timestamp(6),
    completed_at datetime(6) null
) engine=innodb default charset=utf8mb4;

create table if not exists dashboard_analysis_role_result (
    batch_id char(36) character set ascii collate ascii_bin not null,
    as_of_date date not null,
    view_kind varchar(16) character set ascii not null,
    object_key varchar(64) character set ascii collate ascii_bin not null,
    result_json json not null,
    primary key(batch_id,as_of_date,view_kind,object_key)
) engine=innodb default charset=utf8mb4;
