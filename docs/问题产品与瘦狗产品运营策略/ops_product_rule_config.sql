-- 规则配置表设计稿；不包含建库、授权、初始化数据或发布操作。
-- 目标：mysql 8.x + innodb，实际服务器版本尚未核验。
-- 执行前选择目标 schema。规则条件、参数及 json 语义由配置发布校验器验证。
create table ops_product_rule_config (
    id bigint unsigned not null auto_increment comment '规则版本记录主键',
    rule_set_code varchar(64) not null comment '规则集，例如 product_operation',
    rule_set_version varchar(32) not null comment '整套规则版本，例如 v1_draft',
    rule_code char(6) not null comment '六位数字编码：角色1位+模块3位+序号2位；如100101=问题产品/调价/01，跨版本稳定',
    rule_name varchar(200) not null comment '中文规则名称',
    rule_description text not null comment '业务解释，不直接执行',
    product_role varchar(24) not null comment 'problem/dog，仅区分动作适用的产品角色',
    object_type varchar(32) not null comment 'product/auto_target/manual_keyword/search_term/ad_object',
    scope_json json not null comment '适用国家及其他范围条件',
    condition_json json not null comment '产生具体动作的完整准入条件，限制条件只作条件，不另建规则或标签',
    required_fields_json json not null comment '输入字段与质量要求',
    action_type varchar(40) not null comment '固定动作类型，用于结果筛选；不允许路径、护栏、复盘或诊断状态',
    calculator_code varchar(64) not null comment '已注册且有版本的计算模板编号',
    parameter_json json not null comment '模板参数、比例、边界及输出范围',
    exclusive_group varchar(64) not null comment '同一执行对象上的互斥组，例如 price_change/bid_change',
    priority int not null default 100 comment '同组同方向数值越小越优先；风险收缩优先由统一计算流程保证',
    reason_template varchar(1000) not null comment '只允许白名单字段插值的中文解释模板',
    source_refs_json json not null comment '文档名称、章节、原文摘要及源文件 sha256',
    resolution_status varchar(24) not null default 'mapped' comment 'mapped/needs_confirmation/deferred',
    resolution_note text null comment '歧义、建议解释或暂缓原因',
    status varchar(16) not null default 'draft' comment 'draft/published/retired',
    effective_from datetime(6) null comment '已发布规则版本的有效起点，utc',
    effective_to datetime(6) null comment '有效终点不含该时刻，utc；空表示无结束时间',
    definition_hash char(64) null comment '规范化业务定义的 sha256，不含维护时间等可变元数据',
    created_by varchar(64) not null comment '创建人或导入程序身份',
    updated_by varchar(64) not null comment '最后维护人或程序身份',
    created_at datetime(6) not null default current_timestamp(6) comment '创建时间，utc',
    updated_at datetime(6) not null default current_timestamp(6) on update current_timestamp(6) comment '维护时间，utc',
    primary key (id),
    unique key uk_rule_version (rule_set_code, rule_set_version, rule_code),
    key idx_rule_load (rule_set_code, rule_set_version, status, product_role, action_type),
    key idx_rule_history (rule_code, created_at)
) engine=innodb default charset=utf8mb4 collate=utf8mb4_bin
comment='产品具体动作规则配置：一条记录定义何时对何对象做何动作，不保存过程规则';
