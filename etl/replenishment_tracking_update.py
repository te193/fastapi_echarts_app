from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from etl.dashboard_daily_update import connect_source, connect_target, parse_day
from etl.replenishment_update import apply_database_ini_env


TRACKING_WINDOWS = (7, 14, 30)
SOURCE_LOOKBACK_DAYS = 30


CREATE_TRACKING_SNAPSHOT_SQL = """
create table if not exists dashboard_replenishment_tracking_snapshot (
    id bigint not null auto_increment comment '自增主键',
    snapshot_date date not null comment '补货结果日期',
    tracking_window_days int not null default 30 comment '追踪窗口天数，从补货结果日期起向后观察采购、发货、收货状态',
    country_category varchar(64) not null comment '国家类别，沿用补货计算粒度',
    seller_name_new varchar(128) not null comment '店铺',
    seller_sku_adj varchar(128) not null comment 'MSKU',
    max_sku varchar(128) null comment '本地SKU',
    replenishment_level varchar(64) null comment '补货层级',
    replenishment_level_sort tinyint null comment '补货层级排序，1紧急2建议3计划4库存充足5日销为0等',
    product_category varchar(32) null comment '产品角色分类，如明星、潜力、瘦狗、问题',
    replenishment_qty decimal(18,4) not null default 0 comment '补货建议数量',
    replenishment_value decimal(18,4) not null default 0 comment '补货建议货值',
    purchase_snapshot_plan_qty decimal(18,4) not null default 0 comment '本地补货快照中已纳入库存支撑的采购计划数量',
    purchase_snapshot_shipping_qty decimal(18,4) not null default 0 comment '本地补货快照中已纳入库存支撑的采购在途数量',
    purchase_planned_flag tinyint not null default 0 comment '追踪窗口内是否新建未完成采购计划',
    purchase_plan_msku_flag tinyint not null default 0 comment '该MSKU是否已有未完成采购计划',
    purchase_plan_count int not null default 0 comment '追踪窗口内采购计划单数，包含已完成和未完成',
    purchase_plan_total_qty decimal(18,4) not null default 0 comment '追踪窗口内采购计划总数量，包含已完成和未完成',
    current_purchase_shipping_qty decimal(18,4) not null default 0 comment '按追踪窗口采购计划数量归因的本次采购在途数量',
    historical_purchase_shipping_qty decimal(18,4) not null default 0 comment '超出追踪窗口采购计划数量的历史采购在途数量',
    purchase_plan_qty decimal(18,4) not null default 0 comment '未完成采购计划数量，仅统计待审批、待采购等未完成状态',
    purchase_plan_sn_list text null comment '采购计划单号列表',
    purchase_plan_status text null comment '采购计划状态汇总',
    purchase_expect_arrive_time datetime null comment '最近预计到货时间',
    fba_shipment_planned_flag tinyint not null default 0 comment '是否已有FBA发货计划',
    fba_shipment_plan_msku_flag tinyint not null default 0 comment '该MSKU是否已有FBA发货计划',
    fba_shipment_plan_qty decimal(18,4) not null default 0 comment 'FBA发货计划数量',
    current_fba_shipment_plan_qty decimal(18,4) not null default 0 comment '本次采购链路内FBA发货计划数量',
    current_shipped_qty decimal(18,4) not null default 0 comment '本次采购链路内实际发货数量',
    historical_fba_shipment_plan_qty decimal(18,4) not null default 0 comment '历史采购链路FBA发货计划数量',
    historical_shipped_qty decimal(18,4) not null default 0 comment '历史采购链路实际发货数量',
    shipment_attribution varchar(32) null comment '发货归因：current/historical/mixed/none',
    shipment_order_sn_list text null comment 'FBA发货计划单号列表',
    shipment_plan_status text null comment 'FBA发货计划状态汇总',
    shipped_qty decimal(18,4) not null default 0 comment '实际发货数量',
    received_qty decimal(18,4) not null default 0 comment '实际收货数量',
    pending_ship_qty decimal(18,4) not null default 0 comment '未发数量，FBA发货计划数减实际发货数',
    pending_receive_qty decimal(18,4) not null default 0 comment '未收数量，实际发货数减实际收货数',
    main_shipping_method varchar(128) null comment '主要运输方式',
    main_logistics_channel varchar(255) null comment '主要物流渠道',
    main_logistics_provider varchar(255) null comment '主要物流商',
    latest_purchase_plan_time datetime null comment '最新采购计划创建时间',
    latest_plan_time datetime null comment '最新FBA发货计划创建时间',
    latest_shipment_time datetime null comment '最新实际发货时间',
    nearest_fba_eta_date datetime null comment '本次或历史FBA在途最近预计到货时间',
    latest_status varchar(255) null comment '最新追踪状态',
    created_at datetime not null default current_timestamp comment '创建时间',
    updated_at datetime not null default current_timestamp on update current_timestamp comment '更新时间',
    primary key (id),
    unique key uk_tracking_snapshot (snapshot_date, tracking_window_days, country_category, seller_name_new, seller_sku_adj),
    key idx_tracking_filter (snapshot_date, tracking_window_days, replenishment_level_sort, country_category, seller_name_new),
    key idx_tracking_msku (seller_sku_adj, snapshot_date)
) engine=InnoDB default charset=utf8mb4 comment='补货分层采购发货追踪汇总表';
"""


CREATE_TRACKING_DETAIL_SQL = """
create table if not exists dashboard_replenishment_tracking_detail (
    id bigint not null auto_increment comment '自增主键',
    snapshot_date date not null comment '补货结果日期',
    tracking_window_days int not null default 30 comment '追踪窗口天数，从补货结果日期起向后观察采购、发货、收货状态',
    country_category varchar(64) not null comment '国家类别，沿用补货计算粒度',
    seller_name_new varchar(128) not null comment '店铺',
    seller_sku_adj varchar(128) not null comment 'MSKU',
    max_sku varchar(128) null comment '本地SKU',
    replenishment_level varchar(64) null comment '补货层级',
    product_category varchar(32) null comment '产品角色分类',
    source_type varchar(32) not null default 'local_snapshot' comment '明细来源类型：local_snapshot/purchase_plan/shipment_plan/shipment_detail',
    link_attribution varchar(32) null comment '链路归因：current/historical',
    purchase_plan_sn varchar(128) null comment '采购计划单号',
    purchase_plan_time datetime null comment '采购计划创建时间',
    purchase_plan_status varchar(255) null comment '采购计划状态',
    purchase_plan_qty decimal(18,4) not null default 0 comment '采购计划数量',
    purchase_expect_arrive_time datetime null comment '预计到货时间',
    supplier_name varchar(255) null comment '供应商',
    purchaser_name varchar(128) null comment '采购员',
    order_sn varchar(128) null comment 'FBA发货计划单号',
    shipment_sn varchar(128) null comment '货件号',
    plan_create_time datetime null comment 'FBA发货计划创建时间',
    plan_status varchar(255) null comment 'FBA发货计划状态',
    shipment_status varchar(255) null comment '货件状态',
    logistics_status varchar(255) null comment '物流状态',
    method_name varchar(128) null comment '运输方式',
    logistics_channel_name varchar(255) null comment '物流渠道',
    logistics_provider_name varchar(255) null comment '物流商',
    shipment_plan_quantity decimal(18,4) not null default 0 comment 'FBA计划发货数量',
    quantity_shipped decimal(18,4) not null default 0 comment '实际发货数量',
    quantity_received decimal(18,4) not null default 0 comment '实际收货数量',
    box_num decimal(18,4) null comment '箱数',
    quantity_in_case decimal(18,4) null comment '单箱数量',
    shipment_time datetime null comment '计划或实际发货时间',
    actual_shipment_time datetime null comment '实际发货时间',
    expected_arrival_date datetime null comment '预计到达时间',
    eta_date datetime null comment '预计到港或预计到达时间',
    delivery_date datetime null comment '实际妥投时间',
    sku varchar(128) null comment 'SKU',
    nation varchar(64) null comment '国家',
    created_at datetime not null default current_timestamp comment '创建时间',
    updated_at datetime not null default current_timestamp on update current_timestamp comment '更新时间',
    primary key (id),
    key idx_tracking_detail_lookup (snapshot_date, tracking_window_days, country_category, seller_name_new, seller_sku_adj),
    key idx_tracking_detail_order (purchase_plan_sn, order_sn, shipment_sn)
) engine=InnoDB default charset=utf8mb4 comment='补货分层采购发货追踪明细表';
"""


CREATE_PURCHASE_PLAN_SYNC_SQL = """
create table if not exists dashboard_tracking_purchase_plan_sync (
    id bigint not null auto_increment comment 'auto id',
    plan_sn varchar(128) null comment 'purchase plan number',
    status_text varchar(255) null comment 'purchase plan status',
    plan_create_time datetime null comment 'purchase plan create time',
    seller_name varchar(255) null comment 'source shop name',
    seller_name_norm varchar(128) null comment 'shop name normalized to dashboard store',
    country_category varchar(64) null comment 'dashboard country category',
    marketplace varchar(64) null comment 'source marketplace',
    msku varchar(128) null comment 'MSKU',
    sku varchar(128) null comment 'local SKU',
    quantity_plan decimal(18,4) not null default 0 comment 'purchase plan quantity',
    expect_arrive_time datetime null comment 'expected arrival time',
    supplier_name varchar(255) null comment 'supplier',
    purchaser_name varchar(128) null comment 'purchaser',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_purchase_plan_window (plan_create_time, country_category, seller_name_norm, msku),
    key idx_purchase_plan_msku (seller_name_norm, msku, plan_create_time),
    key idx_purchase_plan_sn (plan_sn)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking purchase plan source sync';
"""


CREATE_FBA_SHIPMENT_PLAN_SYNC_SQL = """
create table if not exists dashboard_tracking_fba_shipment_plan_sync (
    id bigint not null auto_increment comment 'auto id',
    order_sn varchar(128) null comment 'FBA shipment plan number',
    status_name varchar(255) null comment 'FBA shipment plan status',
    plan_create_time datetime null comment 'FBA plan create time',
    seller_name varchar(255) null comment 'source shop name',
    seller_name_norm varchar(128) null comment 'shop name normalized to dashboard store',
    country_category varchar(64) null comment 'dashboard country category',
    nation varchar(64) null comment 'source country',
    msku varchar(128) null comment 'MSKU',
    sku varchar(128) null comment 'local SKU',
    shipment_plan_quantity decimal(18,4) not null default 0 comment 'FBA shipment plan quantity',
    method_name varchar(128) null comment 'shipping method',
    logistics_name varchar(255) null comment 'logistics channel',
    shipment_time datetime null comment 'planned shipment time',
    quantity_receive decimal(18,4) not null default 0 comment 'received quantity from plan table',
    box_num decimal(18,4) null comment 'box count',
    quantity_in_case decimal(18,4) null comment 'quantity in case',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_fba_plan_window (plan_create_time, country_category, seller_name_norm, msku),
    key idx_fba_plan_msku (seller_name_norm, msku, plan_create_time),
    key idx_fba_order_sn (order_sn)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking FBA shipment plan source sync';
"""


CREATE_INBOUND_SHIPMENT_SYNC_SQL = """
create table if not exists dashboard_tracking_inbound_shipment_sync (
    id bigint not null auto_increment comment 'auto id',
    shipment_sn varchar(128) null comment 'shipment number',
    shipment_id varchar(128) null comment 'shipment id',
    shipment_status varchar(255) null comment 'shipment source status',
    status_name varchar(255) null comment 'shipment status name',
    shipment_time datetime null comment 'shipment time',
    actual_shipment_time datetime null comment 'actual shipment time',
    expected_arrival_date datetime null comment 'expected arrival date',
    eta_date datetime null comment 'ETA date',
    delivery_date datetime null comment 'delivery date',
    receiving_time datetime null comment 'FBA receiving time',
    closed_time datetime null comment 'FBA closed time',
    logistics_status varchar(255) null comment 'logistics status',
    logistics_channel_name varchar(255) null comment 'logistics channel',
    logistics_provider_name varchar(255) null comment 'logistics provider',
    quantity_total decimal(18,4) not null default 0 comment 'shipment total quantity',
    quantity_shipped decimal(18,4) not null default 0 comment 'FBA shipped quantity',
    quantity_received decimal(18,4) not null default 0 comment 'FBA received quantity',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_inbound_shipment_sn (shipment_sn),
    key idx_inbound_shipment_time (shipment_time)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking inbound shipment source sync';
"""


CREATE_INBOUND_ITEM_SYNC_SQL = """
create table if not exists dashboard_tracking_inbound_item_sync (
    id bigint not null auto_increment comment 'auto id',
    shipment_order_sn varchar(128) null comment 'FBA shipment plan number',
    shipment_sn varchar(128) null comment 'shipment number',
    shipment_id varchar(128) null comment 'shipment id',
    shipment_time datetime null comment 'shipment time',
    seller_name varchar(255) null comment 'source shop name',
    seller_name_norm varchar(128) null comment 'shop name normalized to dashboard store',
    country_category varchar(64) null comment 'dashboard country category',
    nation varchar(64) null comment 'source country',
    msku varchar(128) null comment 'MSKU',
    sku varchar(128) null comment 'local SKU',
    shipment_status varchar(255) null comment 'shipment status',
    status_text varchar(255) null comment 'source status',
    shipment_plan_quantity decimal(18,4) not null default 0 comment 'shipment plan quantity',
    quantity_shipped decimal(18,4) not null default 0 comment 'actual shipped quantity',
    shipment_quantity_received decimal(18,4) not null default 0 comment 'shipment received quantity',
    quantity_receive decimal(18,4) not null default 0 comment 'received quantity fallback',
    quantity_in_case decimal(18,4) null comment 'quantity in case',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_inbound_item_window (shipment_time, country_category, seller_name_norm, msku),
    key idx_inbound_item_msku (seller_name_norm, msku, shipment_time),
    key idx_inbound_item_order (shipment_order_sn),
    key idx_inbound_item_shipment (shipment_sn)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking inbound item source sync';
"""


DELETE_PURCHASE_PLAN_SYNC_SQL = """
delete from dashboard_tracking_purchase_plan_sync
where plan_create_time >= %(window_start)s
  and plan_create_time < %(window_end_exclusive)s;
"""


DELETE_FBA_SHIPMENT_PLAN_SYNC_SQL = """
delete from dashboard_tracking_fba_shipment_plan_sync
where plan_create_time >= %(window_start)s
  and plan_create_time < %(window_end_exclusive)s;
"""


DELETE_INBOUND_SHIPMENT_SYNC_SQL = """
delete from dashboard_tracking_inbound_shipment_sync
where coalesce(shipment_time, source_create_time) >= %(window_start)s
  and coalesce(shipment_time, source_create_time) < %(window_end_exclusive)s;
"""


DELETE_INBOUND_ITEM_SYNC_SQL = """
delete from dashboard_tracking_inbound_item_sync
where coalesce(shipment_time, source_create_time) >= %(window_start)s
  and coalesce(shipment_time, source_create_time) < %(window_end_exclusive)s;
"""


SELECT_PURCHASE_PLAN_SYNC_SQL = """
select
    plan_sn,
    status_text,
    str_to_date(nullif(plan_create_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s') as plan_create_time,
    seller_name,
    case
        when upper(seller_name) regexp '-EU-[A-Z]{2}$' then substring(seller_name, 1, char_length(seller_name) - 6)
        when seller_name regexp '-[A-Za-z]{2}$' then substring(seller_name, 1, char_length(seller_name) - 3)
        else seller_name
    end as seller_name_norm,
    case
        when upper(seller_name) regexp '-US$' then '美国站'
        when upper(seller_name) regexp '-UK$' then '英国站'
        else '欧洲站'
    end as country_category,
    marketplace,
    msku,
    sku,
    coalesce(quantity_plan, 0) as quantity_plan,
    str_to_date(nullif(expect_arrive_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s') as expect_arrive_time,
    supplier_name,
    purchaser_name,
    create_time as source_create_time
from dwd_datasync.lx_purchase_purchase_plan
where nullif(plan_create_time, '') >= %(window_start)s
  and nullif(plan_create_time, '') < %(window_end_exclusive)s
  and coalesce(msku, '') <> '';
"""


SELECT_FBA_SHIPMENT_PLAN_SYNC_SQL = """
select
    order_sn,
    status_name,
    plan_create_time,
    sname as seller_name,
    case
        when upper(sname) regexp '-EU-[A-Z]{2}$' then substring(sname, 1, char_length(sname) - 6)
        when sname regexp '-[A-Za-z]{2}$' then substring(sname, 1, char_length(sname) - 3)
        else sname
    end as seller_name_norm,
    case
        when upper(sname) regexp '-US$' then '美国站'
        when upper(sname) regexp '-UK$' then '英国站'
        else '欧洲站'
    end as country_category,
    nation,
    msku,
    sku,
    coalesce(shipment_plan_quantity, 0) as shipment_plan_quantity,
    method_name,
    logistics_name,
    shipment_time,
    coalesce(quantity_receive, 0) as quantity_receive,
    box_num,
    quantity_in_case,
    create_time as source_create_time
from dwd_datasync.lx_fba_shipment_plan
where plan_create_time >= %(window_start)s
  and plan_create_time < %(window_end_exclusive)s
  and coalesce(msku, '') <> '';
"""


SELECT_INBOUND_SHIPMENT_SYNC_SQL = """
select
    s.shipment_sn,
    s.shipment_id,
    s.status as shipment_status,
    s.status_name,
    coalesce(
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d')
    ) as shipment_time,
    coalesce(
        str_to_date(nullif(s.actual_shipment_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.actual_shipment_time, ''), '%%Y-%%m-%%d')
    ) as actual_shipment_time,
    coalesce(
        str_to_date(nullif(s.expected_arrival_date, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.expected_arrival_date, ''), '%%Y-%%m-%%d')
    ) as expected_arrival_date,
    coalesce(
        str_to_date(nullif(s.eta_date, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.eta_date, ''), '%%Y-%%m-%%d')
    ) as eta_date,
    coalesce(
        str_to_date(nullif(s.delivery_date, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.delivery_date, ''), '%%Y-%%m-%%d')
    ) as delivery_date,
    coalesce(
        str_to_date(nullif(fs.receiving_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(fs.receiving_time, ''), '%%Y-%%m-%%d')
    ) as receiving_time,
    coalesce(
        str_to_date(nullif(fs.closed_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(fs.closed_time, ''), '%%Y-%%m-%%d')
    ) as closed_time,
    s.order_logistics_status as logistics_status,
    s.logistics_channel_name,
    s.logistics_provider_name,
    coalesce(s.quantity_total, 0) as quantity_total,
    coalesce(fs.quantity_shipped + 0, 0) as quantity_shipped,
    coalesce(fs.quantity_received + 0, 0) as quantity_received,
    s.create_time as source_create_time
from dwd_datasync.lx_inbound_shipment_detail s
left join dwd_datasync.lx_fba_shipment fs
  on fs.shipment_id = s.shipment_id
where coalesce(
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d'),
        s.create_time
      ) >= %(window_start)s
  and coalesce(
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(s.shipment_time, ''), '%%Y-%%m-%%d'),
        s.create_time
      ) < %(window_end_exclusive)s
  and coalesce(s.shipment_sn, '') <> '';
"""


SELECT_INBOUND_ITEM_SYNC_SQL = """
select
    shipment_order_sn,
    shipment_sn,
    shipment_id,
    from_unixtime(nullif(shipment_time, 0)) as shipment_time,
    sname as seller_name,
    case
        when upper(sname) regexp '-EU-[A-Z]{2}$' then substring(sname, 1, char_length(sname) - 6)
        when sname regexp '-[A-Za-z]{2}$' then substring(sname, 1, char_length(sname) - 3)
        else sname
    end as seller_name_norm,
    case
        when upper(sname) regexp '-US$' then '美国站'
        when upper(sname) regexp '-UK$' then '英国站'
        else '欧洲站'
    end as country_category,
    nation,
    msku,
    sku,
    shipment_status,
    status as status_text,
    coalesce(shipment_plan_quantity, 0) as shipment_plan_quantity,
    coalesce(quantity_shipped, 0) as quantity_shipped,
    coalesce(shipment_quantity_received, 0) as shipment_quantity_received,
    coalesce(quantity_receive, 0) as quantity_receive,
    quantity_in_case,
    create_time as source_create_time
from dwd_datasync.lx_inbound_shipment_detail_ShangPinLieBiao
where coalesce(from_unixtime(nullif(shipment_time, 0)), create_time) >= %(window_start)s
  and coalesce(from_unixtime(nullif(shipment_time, 0)), create_time) < %(window_end_exclusive)s
  and coalesce(msku, '') <> '';
"""


PURCHASE_PLAN_SYNC_COLUMNS = (
    "plan_sn",
    "status_text",
    "plan_create_time",
    "seller_name",
    "seller_name_norm",
    "country_category",
    "marketplace",
    "msku",
    "sku",
    "quantity_plan",
    "expect_arrive_time",
    "supplier_name",
    "purchaser_name",
    "source_create_time",
)


INBOUND_SHIPMENT_SYNC_COLUMNS = (
    "shipment_sn",
    "shipment_id",
    "shipment_status",
    "status_name",
    "shipment_time",
    "actual_shipment_time",
    "expected_arrival_date",
    "eta_date",
    "delivery_date",
    "receiving_time",
    "closed_time",
    "logistics_status",
    "logistics_channel_name",
    "logistics_provider_name",
    "quantity_total",
    "quantity_shipped",
    "quantity_received",
    "source_create_time",
)


INBOUND_ITEM_SYNC_COLUMNS = (
    "shipment_order_sn",
    "shipment_sn",
    "shipment_id",
    "shipment_time",
    "seller_name",
    "seller_name_norm",
    "country_category",
    "nation",
    "msku",
    "sku",
    "shipment_status",
    "status_text",
    "shipment_plan_quantity",
    "quantity_shipped",
    "shipment_quantity_received",
    "quantity_receive",
    "quantity_in_case",
    "source_create_time",
)


FBA_SHIPMENT_PLAN_SYNC_COLUMNS = (
    "order_sn",
    "status_name",
    "plan_create_time",
    "seller_name",
    "seller_name_norm",
    "country_category",
    "nation",
    "msku",
    "sku",
    "shipment_plan_quantity",
    "method_name",
    "logistics_name",
    "shipment_time",
    "quantity_receive",
    "box_num",
    "quantity_in_case",
    "source_create_time",
)


DELETE_SNAPSHOT_SQL = """
delete from dashboard_replenishment_tracking_snapshot
where snapshot_date = %(snapshot_date)s
  and tracking_window_days = %(tracking_window_days)s;
"""


INSERT_SNAPSHOT_SQL = """
insert into dashboard_replenishment_tracking_snapshot (
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    replenishment_level_sort,
    product_category,
    replenishment_qty,
    replenishment_value,
    purchase_snapshot_plan_qty,
    purchase_snapshot_shipping_qty,
    purchase_planned_flag,
    purchase_plan_msku_flag,
    purchase_plan_count,
    purchase_plan_total_qty,
    current_purchase_shipping_qty,
    historical_purchase_shipping_qty,
    purchase_plan_qty,
    purchase_plan_sn_list,
    purchase_plan_status,
    purchase_expect_arrive_time,
    fba_shipment_planned_flag,
    fba_shipment_plan_msku_flag,
    fba_shipment_plan_qty,
    current_fba_shipment_plan_qty,
    current_shipped_qty,
    historical_fba_shipment_plan_qty,
    historical_shipped_qty,
    shipment_attribution,
    shipment_order_sn_list,
    shipment_plan_status,
    shipped_qty,
    received_qty,
    pending_ship_qty,
    pending_receive_qty,
    main_shipping_method,
    main_logistics_channel,
    main_logistics_provider,
    latest_purchase_plan_time,
    latest_plan_time,
    latest_shipment_time,
    nearest_fba_eta_date,
    latest_status
)
select
    p.cur_date as snapshot_date,
    %(tracking_window_days)s as tracking_window_days,
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    p.max_sku,
    p.support_replenish_level as replenishment_level,
    p.support_replenish_level_sort as replenishment_level_sort,
    p.abcd_category as product_category,
    coalesce(p.replenish_qty, 0) as replenishment_qty,
    coalesce(p.replenish_cost, 0) as replenishment_value,
    coalesce(r.purchase_plan_quantity, p.sc_quantity_purchase_plan, 0) as purchase_snapshot_plan_qty,
    coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) as purchase_snapshot_shipping_qty,
    case
        when coalesce(pp.purchase_plan_count, 0) > 0 then 1 else 0
    end as purchase_planned_flag,
    case
        when coalesce(pp.purchase_plan_count, 0) > 0 then 1 else 0
    end as purchase_plan_msku_flag,
    coalesce(pp.purchase_plan_count, 0) as purchase_plan_count,
    coalesce(pp.purchase_plan_total_qty, 0) as purchase_plan_total_qty,
    least(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0), coalesce(pp.purchase_plan_total_qty, 0)) as current_purchase_shipping_qty,
    greatest(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) - coalesce(pp.purchase_plan_total_qty, 0), 0) as historical_purchase_shipping_qty,
    case
        when coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) > 0 then 0
        else coalesce(pp.purchase_plan_qty, 0)
    end as purchase_plan_qty,
    pp.purchase_plan_sn_list,
    pp.purchase_plan_status,
    case
        when coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) > 0 then null
        else pp.purchase_expect_arrive_time
    end as purchase_expect_arrive_time,
    case when greatest(
        coalesce(sp.current_fba_shipment_plan_qty, 0) + coalesce(sp.historical_fba_shipment_plan_qty, 0),
        coalesce(sd.current_shipment_plan_quantity, 0) + coalesce(sd.historical_shipment_plan_quantity, 0)
    ) > 0 then 1 else 0 end as fba_shipment_planned_flag,
    case when coalesce(sp.current_fba_shipment_plan_qty, 0) + coalesce(sd.current_shipment_plan_quantity, 0) > 0 then 1 else 0 end as fba_shipment_plan_msku_flag,
    greatest(
        coalesce(sp.current_fba_shipment_plan_qty, 0) + coalesce(sp.historical_fba_shipment_plan_qty, 0),
        coalesce(sd.current_shipment_plan_quantity, 0) + coalesce(sd.historical_shipment_plan_quantity, 0)
    ) as fba_shipment_plan_qty,
    greatest(coalesce(sp.current_fba_shipment_plan_qty, 0), coalesce(sd.current_shipment_plan_quantity, 0)) as current_fba_shipment_plan_qty,
    coalesce(sd.current_shipped_qty, 0) as current_shipped_qty,
    greatest(coalesce(sp.historical_fba_shipment_plan_qty, 0), coalesce(sd.historical_shipment_plan_quantity, 0)) as historical_fba_shipment_plan_qty,
    coalesce(sd.historical_shipped_qty, 0) as historical_shipped_qty,
    case
        when coalesce(sd.current_shipped_qty, 0) > 0 and coalesce(sd.historical_shipped_qty, 0) > 0 then 'mixed'
        when coalesce(sd.current_shipped_qty, 0) > 0 then 'current'
        when coalesce(sd.historical_shipped_qty, 0) > 0 then 'historical'
        when greatest(coalesce(sp.current_fba_shipment_plan_qty, 0), coalesce(sd.current_shipment_plan_quantity, 0)) > 0 then 'current'
        when greatest(coalesce(sp.historical_fba_shipment_plan_qty, 0), coalesce(sd.historical_shipment_plan_quantity, 0)) > 0 then 'historical'
        else 'none'
    end as shipment_attribution,
    coalesce(sp.shipment_order_sn_list, sd.shipment_order_sn_list) as shipment_order_sn_list,
    coalesce(sp.shipment_plan_status, sd.shipment_status) as shipment_plan_status,
    coalesce(sd.current_shipped_qty, 0) as shipped_qty,
    coalesce(sd.current_received_qty, sp.current_received_qty, 0) as received_qty,
    greatest(greatest(coalesce(sp.current_fba_shipment_plan_qty, 0), coalesce(sd.current_shipment_plan_quantity, 0)) - coalesce(sd.current_shipped_qty, 0), 0) as pending_ship_qty,
    greatest(coalesce(sd.current_shipped_qty, 0) - coalesce(sd.current_received_qty, sp.current_received_qty, 0), 0) as pending_receive_qty,
    sp.main_shipping_method,
    coalesce(sd.main_logistics_channel, sp.main_logistics_channel) as main_logistics_channel,
    sd.main_logistics_provider,
    pp.latest_purchase_plan_time,
    sp.latest_plan_time,
    sd.latest_shipment_time,
    sd.nearest_fba_eta_date,
    case
        when coalesce(sd.current_received_qty, sp.current_received_qty, 0) > 0 then '本次链路已收货'
        when coalesce(sd.current_shipped_qty, 0) > 0 then '本次链路已发货'
        when coalesce(pp.purchase_plan_count, 0) > 0 and greatest(coalesce(sp.current_fba_shipment_plan_qty, 0), coalesce(sd.current_shipment_plan_quantity, 0)) > 0 then '已建本次FBA'
        when coalesce(pp.purchase_plan_count, 0) > 0 and coalesce(sd.historical_shipped_qty, 0) > 0 then '已采购，存在历史发货'
        when coalesce(sd.historical_shipped_qty, 0) > 0 then '历史采购发货'
        when greatest(coalesce(sp.historical_fba_shipment_plan_qty, 0), coalesce(sd.historical_shipment_plan_quantity, 0)) > 0 then '历史FBA计划'
        when least(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0), coalesce(pp.purchase_plan_total_qty, 0)) > 0
         and greatest(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) - coalesce(pp.purchase_plan_total_qty, 0), 0) > 0 then '本次+历史采购在途'
        when least(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0), coalesce(pp.purchase_plan_total_qty, 0)) > 0 then '本次采购在途'
        when greatest(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) - coalesce(pp.purchase_plan_total_qty, 0), 0) > 0 then '历史采购在途'
        when coalesce(pp.purchase_plan_count, 0) > 0 then '已建采购计划'
        else '未进入采购链路'
    end as latest_status
from dashboard_pur_plan_replenish_data p
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        max(coalesce(r0.purchase_plan_quantity, 0)) as purchase_plan_quantity,
        max(coalesce(r0.purchase_shipping_quantity, 0)) as purchase_shipping_quantity
    from dashboard_pur_plan_replenish_data p0
    left join dashboard_restock_daily_snapshot r0
           on r0.snapshot_date >= p0.cur_date
          and r0.snapshot_date <= date_add(p0.cur_date, interval %(tracking_window_days)s day)
          and r0.country_category = p0.country_category
          and r0.seller_name_new = p0.seller_name_new
          and r0.seller_sku_adj = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) r
       on r.cur_date = p.cur_date
      and r.country_category = p.country_category
      and r.seller_name_new = p.seller_name_new
      and r.seller_sku_adj = p.seller_sku_adj
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        count(distinct pp0.plan_sn) as purchase_plan_count,
        sum(coalesce(pp0.quantity_plan, 0)) as purchase_plan_total_qty,
        sum(case
                when coalesce(pp0.status_text, '') <> '已完成' then coalesce(pp0.quantity_plan, 0)
                else 0
            end) as purchase_plan_qty,
        group_concat(distinct pp0.plan_sn order by pp0.plan_create_time separator ',') as purchase_plan_sn_list,
        group_concat(distinct pp0.status_text order by pp0.plan_create_time separator ',') as purchase_plan_status,
        max(case
                when coalesce(pp0.status_text, '') <> '已完成' then pp0.expect_arrive_time
            end) as purchase_expect_arrive_time,
        max(pp0.plan_create_time) as latest_purchase_plan_time
    from dashboard_pur_plan_replenish_data p0
    join dashboard_tracking_purchase_plan_sync pp0
      on pp0.plan_create_time >= p0.cur_date
     and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
     and pp0.country_category = p0.country_category
     and pp0.seller_name_norm = p0.seller_name_new
     and pp0.msku = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) pp
       on pp.cur_date = p.cur_date
      and pp.country_category = p.country_category
      and pp.seller_name_new = p.seller_name_new
      and pp.seller_sku_adj = p.seller_sku_adj
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        sum(case
                when pp.latest_purchase_plan_time is not null
                 and sp0.plan_create_time >= pp.latest_purchase_plan_time
                then coalesce(sp0.shipment_plan_quantity, 0)
                else 0
            end) as current_fba_shipment_plan_qty,
        sum(case
                when pp.latest_purchase_plan_time is not null
                 and sp0.plan_create_time >= pp.latest_purchase_plan_time
                then coalesce(sp0.quantity_receive, 0)
                else 0
            end) as current_received_qty,
        sum(case
                when pp.latest_purchase_plan_time is null
                  or sp0.plan_create_time < pp.latest_purchase_plan_time
                then coalesce(sp0.shipment_plan_quantity, 0)
                else 0
            end) as historical_fba_shipment_plan_qty,
        group_concat(distinct sp0.order_sn order by sp0.plan_create_time separator ',') as shipment_order_sn_list,
        group_concat(distinct sp0.status_name order by sp0.plan_create_time separator ',') as shipment_plan_status,
        substring_index(group_concat(nullif(sp0.method_name, '') order by sp0.plan_create_time desc separator ','), ',', 1) as main_shipping_method,
        substring_index(group_concat(nullif(sp0.logistics_name, '') order by sp0.plan_create_time desc separator ','), ',', 1) as main_logistics_channel,
        max(sp0.plan_create_time) as latest_plan_time
    from dashboard_pur_plan_replenish_data p0
    join dashboard_tracking_fba_shipment_plan_sync sp0
      on sp0.plan_create_time >= p0.cur_date
     and sp0.plan_create_time < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
     and sp0.country_category = p0.country_category
     and sp0.seller_name_norm = p0.seller_name_new
     and sp0.msku = p0.seller_sku_adj
    left join (
        select
            p1.cur_date,
            p1.country_category,
            p1.seller_name_new,
            p1.seller_sku_adj,
            max(pp1.plan_create_time) as latest_purchase_plan_time
        from dashboard_pur_plan_replenish_data p1
        join dashboard_tracking_purchase_plan_sync pp1
          on pp1.plan_create_time >= p1.cur_date
         and pp1.plan_create_time < date_add(date_add(p1.cur_date, interval %(tracking_window_days)s day), interval 1 day)
         and pp1.country_category = p1.country_category
         and pp1.seller_name_norm = p1.seller_name_new
         and pp1.msku = p1.seller_sku_adj
        where p1.cur_date = %(snapshot_date)s
          and p1.support_replenish_level_sort in (1, 2, 3)
        group by p1.cur_date, p1.country_category, p1.seller_name_new, p1.seller_sku_adj
    ) pp
      on pp.cur_date = p0.cur_date
     and pp.country_category = p0.country_category
     and pp.seller_name_new = p0.seller_name_new
     and pp.seller_sku_adj = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) sp
       on sp.cur_date = p.cur_date
      and sp.country_category = p.country_category
      and sp.seller_name_new = p.seller_name_new
      and sp.seller_sku_adj = p.seller_sku_adj
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        sum(case
                when pp.latest_purchase_plan_time is not null
                 and coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time
                then coalesce(it.shipment_plan_quantity, 0)
                else 0
            end) as current_shipment_plan_quantity,
        sum(case
                when pp.latest_purchase_plan_time is not null
                 and coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time
                then coalesce(it.quantity_shipped, 0)
                else 0
            end) as current_shipped_qty,
        sum(case
                when pp.latest_purchase_plan_time is not null
                 and coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time
                 and coalesce(it.shipment_quantity_received, 0) > 0 then coalesce(it.shipment_quantity_received, 0)
                when pp.latest_purchase_plan_time is not null
                 and coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time then coalesce(it.quantity_receive, 0)
                else 0
            end) as current_received_qty,
        sum(case
                when pp.latest_purchase_plan_time is null
                  or coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) < pp.latest_purchase_plan_time
                then coalesce(it.shipment_plan_quantity, 0)
                else 0
            end) as historical_shipment_plan_quantity,
        sum(case
                when pp.latest_purchase_plan_time is null
                  or coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) < pp.latest_purchase_plan_time
                then coalesce(it.quantity_shipped, 0)
                else 0
            end) as historical_shipped_qty,
        sum(case
                when pp.latest_purchase_plan_time is null
                  or coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) < pp.latest_purchase_plan_time
                then
                    case
                        when coalesce(it.shipment_quantity_received, 0) > 0 then coalesce(it.shipment_quantity_received, 0)
                        else coalesce(it.quantity_receive, 0)
                    end
                else 0
            end) as historical_received_qty,
        sum(case
                when coalesce(it.shipment_quantity_received, 0) > 0 then coalesce(it.shipment_quantity_received, 0)
                else coalesce(it.quantity_receive, 0)
            end) as received_qty,
        group_concat(distinct it.shipment_order_sn order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) separator ',') as shipment_order_sn_list,
        group_concat(distinct it.shipment_sn order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) separator ',') as shipment_sn_list,
        group_concat(distinct coalesce(sm.status_name, it.shipment_status, it.status_text) order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) separator ',') as shipment_status,
        group_concat(distinct sm.logistics_status order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) separator ',') as logistics_status,
        substring_index(group_concat(nullif(sm.logistics_channel_name, '') order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) desc separator ','), ',', 1) as main_logistics_channel,
        substring_index(group_concat(nullif(sm.logistics_provider_name, '') order by coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time) desc separator ','), ',', 1) as main_logistics_provider,
        max(coalesce(sm.actual_shipment_time, it.shipment_time, sm.shipment_time)) as latest_shipment_time,
        coalesce(
            min(case
                    when coalesce(it.quantity_shipped, 0) > 0
                     and coalesce(it.quantity_shipped, 0) > coalesce(nullif(it.shipment_quantity_received, 0), it.quantity_receive, 0)
                     and upper(coalesce(it.shipment_status, it.status_text, sm.shipment_status, sm.status_name, '')) <> 'CLOSED'
                     and sm.closed_time is null
                     and coalesce(sm.expected_arrival_date, sm.eta_date) >= p0.cur_date
                    then coalesce(sm.expected_arrival_date, sm.eta_date)
                end),
            max(case
                    when coalesce(it.quantity_shipped, 0) > 0
                     and coalesce(it.quantity_shipped, 0) > coalesce(nullif(it.shipment_quantity_received, 0), it.quantity_receive, 0)
                     and upper(coalesce(it.shipment_status, it.status_text, sm.shipment_status, sm.status_name, '')) <> 'CLOSED'
                     and sm.closed_time is null
                     and coalesce(sm.expected_arrival_date, sm.eta_date) < p0.cur_date
                    then coalesce(sm.expected_arrival_date, sm.eta_date)
                end)
        ) as nearest_fba_eta_date
    from dashboard_pur_plan_replenish_data p0
    join dashboard_tracking_inbound_item_sync it
      on coalesce(it.shipment_time, it.source_create_time) >= date_sub(p0.cur_date, interval 30 day)
     and coalesce(it.shipment_time, it.source_create_time) < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
     and it.country_category = p0.country_category
     and it.seller_name_norm = p0.seller_name_new
     and it.msku = p0.seller_sku_adj
    left join dashboard_tracking_inbound_shipment_sync sm
      on sm.shipment_sn = it.shipment_sn
    left join dashboard_tracking_fba_shipment_plan_sync sp_link
      on sp_link.order_sn = it.shipment_order_sn
     and sp_link.country_category = it.country_category
     and sp_link.seller_name_norm = it.seller_name_norm
     and sp_link.msku = it.msku
    left join (
        select
            p1.cur_date,
            p1.country_category,
            p1.seller_name_new,
            p1.seller_sku_adj,
            max(pp1.plan_create_time) as latest_purchase_plan_time
        from dashboard_pur_plan_replenish_data p1
        join dashboard_tracking_purchase_plan_sync pp1
          on pp1.plan_create_time >= p1.cur_date
         and pp1.plan_create_time < date_add(date_add(p1.cur_date, interval %(tracking_window_days)s day), interval 1 day)
         and pp1.country_category = p1.country_category
         and pp1.seller_name_norm = p1.seller_name_new
         and pp1.msku = p1.seller_sku_adj
        where p1.cur_date = %(snapshot_date)s
          and p1.support_replenish_level_sort in (1, 2, 3)
        group by p1.cur_date, p1.country_category, p1.seller_name_new, p1.seller_sku_adj
    ) pp
      on pp.cur_date = p0.cur_date
     and pp.country_category = p0.country_category
     and pp.seller_name_new = p0.seller_name_new
     and pp.seller_sku_adj = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
      and (
            (
                coalesce(it.shipment_time, it.source_create_time) >= p0.cur_date
                and coalesce(it.shipment_time, it.source_create_time) < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
            )
            or (
                coalesce(it.shipment_time, it.source_create_time) < p0.cur_date
                and coalesce(it.quantity_shipped, 0) > 0
                and coalesce(sm.delivery_date, sm.expected_arrival_date, sm.eta_date, date_add(p0.cur_date, interval %(tracking_window_days)s day)) >= p0.cur_date
            )
         )
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) sd
       on sd.cur_date = p.cur_date
      and sd.country_category = p.country_category
      and sd.seller_name_new = p.seller_name_new
      and sd.seller_sku_adj = p.seller_sku_adj
where p.cur_date = %(snapshot_date)s
  and p.support_replenish_level_sort in (1, 2, 3);
"""

DELETE_DETAIL_SQL = """
delete from dashboard_replenishment_tracking_detail
where snapshot_date = %(snapshot_date)s
  and tracking_window_days = %(tracking_window_days)s;
"""


INSERT_DETAIL_SQL = """
insert into dashboard_replenishment_tracking_detail (
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    product_category,
    source_type,
    link_attribution,
    purchase_plan_status,
    purchase_plan_qty,
    sku
)
select
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    product_category,
    'local_snapshot' as source_type,
    null as link_attribution,
    purchase_plan_status,
    purchase_plan_qty,
    max_sku as sku
from dashboard_replenishment_tracking_snapshot
where snapshot_date = %(snapshot_date)s
  and tracking_window_days = %(tracking_window_days)s;
"""


INSERT_PURCHASE_DETAIL_SQL = """
insert into dashboard_replenishment_tracking_detail (
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    product_category,
    source_type,
    link_attribution,
    purchase_plan_sn,
    purchase_plan_time,
    purchase_plan_status,
    purchase_plan_qty,
    purchase_expect_arrive_time,
    supplier_name,
    purchaser_name,
    sku,
    nation
)
select
    p.cur_date as snapshot_date,
    %(tracking_window_days)s as tracking_window_days,
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    p.max_sku,
    p.support_replenish_level as replenishment_level,
    p.abcd_category as product_category,
    'purchase_plan' as source_type,
    'current' as link_attribution,
    pp.plan_sn as purchase_plan_sn,
    pp.plan_create_time as purchase_plan_time,
    pp.status_text as purchase_plan_status,
    coalesce(pp.quantity_plan, 0) as purchase_plan_qty,
    pp.expect_arrive_time as purchase_expect_arrive_time,
    pp.supplier_name,
    pp.purchaser_name,
    pp.sku,
    pp.marketplace as nation
from dashboard_pur_plan_replenish_data p
join dashboard_tracking_purchase_plan_sync pp
  on pp.plan_create_time >= p.cur_date
 and pp.plan_create_time < date_add(date_add(p.cur_date, interval %(tracking_window_days)s day), interval 1 day)
 and pp.country_category = p.country_category
 and pp.seller_name_norm = p.seller_name_new
 and pp.msku = p.seller_sku_adj
where p.cur_date = %(snapshot_date)s
  and p.support_replenish_level_sort in (1, 2, 3);
"""


INSERT_FBA_DETAIL_SQL = """
insert into dashboard_replenishment_tracking_detail (
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    product_category,
    source_type,
    link_attribution,
    order_sn,
    plan_create_time,
    plan_status,
    method_name,
    logistics_channel_name,
    shipment_plan_quantity,
    quantity_received,
    box_num,
    quantity_in_case,
    shipment_time,
    sku,
    nation
)
select
    p.cur_date as snapshot_date,
    %(tracking_window_days)s as tracking_window_days,
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    p.max_sku,
    p.support_replenish_level as replenishment_level,
    p.abcd_category as product_category,
    'shipment_plan' as source_type,
    case
        when pp.latest_purchase_plan_time is not null
         and sp.plan_create_time >= pp.latest_purchase_plan_time then 'current'
        else 'historical'
    end as link_attribution,
    sp.order_sn,
    sp.plan_create_time,
    sp.status_name as plan_status,
    sp.method_name,
    sp.logistics_name as logistics_channel_name,
    coalesce(sp.shipment_plan_quantity, 0) as shipment_plan_quantity,
    coalesce(sp.quantity_receive, 0) as quantity_received,
    sp.box_num,
    sp.quantity_in_case,
    sp.shipment_time,
    sp.sku,
    sp.nation
from dashboard_pur_plan_replenish_data p
join dashboard_tracking_fba_shipment_plan_sync sp
  on sp.plan_create_time >= p.cur_date
 and sp.plan_create_time < date_add(date_add(p.cur_date, interval %(tracking_window_days)s day), interval 1 day)
 and sp.country_category = p.country_category
 and sp.seller_name_norm = p.seller_name_new
 and sp.msku = p.seller_sku_adj
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        max(pp0.plan_create_time) as latest_purchase_plan_time
    from dashboard_pur_plan_replenish_data p0
    join dashboard_tracking_purchase_plan_sync pp0
      on pp0.plan_create_time >= p0.cur_date
     and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
     and pp0.country_category = p0.country_category
     and pp0.seller_name_norm = p0.seller_name_new
     and pp0.msku = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) pp
  on pp.cur_date = p.cur_date
 and pp.country_category = p.country_category
 and pp.seller_name_new = p.seller_name_new
 and pp.seller_sku_adj = p.seller_sku_adj
where p.cur_date = %(snapshot_date)s
  and p.support_replenish_level_sort in (1, 2, 3);
"""


INSERT_SHIPMENT_DETAIL_SQL = """
insert into dashboard_replenishment_tracking_detail (
    snapshot_date,
    tracking_window_days,
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    replenishment_level,
    product_category,
    source_type,
    link_attribution,
    order_sn,
    shipment_sn,
    shipment_status,
    logistics_status,
    logistics_channel_name,
    logistics_provider_name,
    shipment_plan_quantity,
    quantity_shipped,
    quantity_received,
    quantity_in_case,
    shipment_time,
    actual_shipment_time,
    expected_arrival_date,
    eta_date,
    delivery_date,
    sku,
    nation
)
select
    p.cur_date as snapshot_date,
    %(tracking_window_days)s as tracking_window_days,
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    p.max_sku,
    p.support_replenish_level as replenishment_level,
    p.abcd_category as product_category,
    'shipment_detail' as source_type,
    case
        when pp.latest_purchase_plan_time is not null
         and coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time then 'current'
        else 'historical'
    end as link_attribution,
    it.shipment_order_sn as order_sn,
    it.shipment_sn,
    coalesce(sm.status_name, it.shipment_status, it.status_text) as shipment_status,
    sm.logistics_status,
    sm.logistics_channel_name,
    sm.logistics_provider_name,
    coalesce(it.shipment_plan_quantity, 0) as shipment_plan_quantity,
    coalesce(it.quantity_shipped, 0) as quantity_shipped,
    case
        when coalesce(it.shipment_quantity_received, 0) > 0 then coalesce(it.shipment_quantity_received, 0)
        else coalesce(it.quantity_receive, 0)
    end as quantity_received,
    it.quantity_in_case,
    coalesce(it.shipment_time, sm.shipment_time) as shipment_time,
    sm.actual_shipment_time,
    sm.expected_arrival_date,
    sm.eta_date,
    sm.delivery_date,
    it.sku,
    it.nation
from dashboard_pur_plan_replenish_data p
join dashboard_tracking_inbound_item_sync it
  on coalesce(it.shipment_time, it.source_create_time) >= date_sub(p.cur_date, interval 30 day)
 and coalesce(it.shipment_time, it.source_create_time) < date_add(date_add(p.cur_date, interval %(tracking_window_days)s day), interval 1 day)
 and it.country_category = p.country_category
 and it.seller_name_norm = p.seller_name_new
 and it.msku = p.seller_sku_adj
left join dashboard_tracking_inbound_shipment_sync sm
  on sm.shipment_sn = it.shipment_sn
left join dashboard_tracking_fba_shipment_plan_sync sp_link
  on sp_link.order_sn = it.shipment_order_sn
 and sp_link.country_category = it.country_category
 and sp_link.seller_name_norm = it.seller_name_norm
 and sp_link.msku = it.msku
left join (
    select
        p0.cur_date,
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        max(pp0.plan_create_time) as latest_purchase_plan_time
    from dashboard_pur_plan_replenish_data p0
    join dashboard_tracking_purchase_plan_sync pp0
      on pp0.plan_create_time >= p0.cur_date
     and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval %(tracking_window_days)s day), interval 1 day)
     and pp0.country_category = p0.country_category
     and pp0.seller_name_norm = p0.seller_name_new
     and pp0.msku = p0.seller_sku_adj
    where p0.cur_date = %(snapshot_date)s
      and p0.support_replenish_level_sort in (1, 2, 3)
    group by p0.cur_date, p0.country_category, p0.seller_name_new, p0.seller_sku_adj
) pp
  on pp.cur_date = p.cur_date
 and pp.country_category = p.country_category
 and pp.seller_name_new = p.seller_name_new
 and pp.seller_sku_adj = p.seller_sku_adj
where p.cur_date = %(snapshot_date)s
  and p.support_replenish_level_sort in (1, 2, 3)
  and (
        (
            coalesce(it.shipment_time, it.source_create_time) >= p.cur_date
            and coalesce(it.shipment_time, it.source_create_time) < date_add(date_add(p.cur_date, interval %(tracking_window_days)s day), interval 1 day)
        )
        or (
            coalesce(it.shipment_time, it.source_create_time) < p.cur_date
            and coalesce(it.quantity_shipped, 0) > 0
            and coalesce(sm.delivery_date, sm.expected_arrival_date, sm.eta_date, date_add(p.cur_date, interval %(tracking_window_days)s day)) >= p.cur_date
        )
     )
;
"""


def build_insert_sql(table_name: str, columns: tuple[str, ...]) -> str:
    column_sql = ", ".join(columns)
    value_sql = ", ".join(f"%({column})s" for column in columns)
    return f"insert into {table_name} ({column_sql}) values ({value_sql})"


def copy_source_rows(
    source_conn,
    target_conn,
    source_sql: str,
    delete_sql: str,
    target_table: str,
    columns: tuple[str, ...],
    params: dict[str, date],
    batch_size: int,
) -> int:
    insert_sql = build_insert_sql(target_table, columns)
    total_rows = 0
    with target_conn.cursor() as target_cursor:
        target_cursor.execute(delete_sql, params)
    with source_conn.cursor() as source_cursor:
        source_cursor.execute(source_sql, params)
        while True:
            rows = source_cursor.fetchmany(batch_size)
            if not rows:
                break
            with target_conn.cursor() as target_cursor:
                target_cursor.executemany(insert_sql, rows)
            total_rows += len(rows)
    target_conn.commit()
    return total_rows


def sync_tracking_sources(
    target_conn,
    source_conn,
    snapshot_date: date,
    tracking_window_days: int,
    batch_size: int,
) -> dict[str, int]:
    window_start = snapshot_date - timedelta(days=SOURCE_LOOKBACK_DAYS)
    window_end_exclusive = snapshot_date + timedelta(days=tracking_window_days + 1)
    params = {"window_start": window_start, "window_end_exclusive": window_end_exclusive}
    with target_conn.cursor() as cursor:
        cursor.execute(CREATE_PURCHASE_PLAN_SYNC_SQL)
        cursor.execute(CREATE_FBA_SHIPMENT_PLAN_SYNC_SQL)
        cursor.execute(CREATE_INBOUND_SHIPMENT_SYNC_SQL)
        cursor.execute(CREATE_INBOUND_ITEM_SYNC_SQL)
    target_conn.commit()
    ensure_inbound_shipment_sync_columns(target_conn)
    purchase_rows = copy_source_rows(
        source_conn,
        target_conn,
        SELECT_PURCHASE_PLAN_SYNC_SQL,
        DELETE_PURCHASE_PLAN_SYNC_SQL,
        "dashboard_tracking_purchase_plan_sync",
        PURCHASE_PLAN_SYNC_COLUMNS,
        params,
        batch_size,
    )
    fba_rows = copy_source_rows(
        source_conn,
        target_conn,
        SELECT_FBA_SHIPMENT_PLAN_SYNC_SQL,
        DELETE_FBA_SHIPMENT_PLAN_SYNC_SQL,
        "dashboard_tracking_fba_shipment_plan_sync",
        FBA_SHIPMENT_PLAN_SYNC_COLUMNS,
        params,
        batch_size,
    )
    inbound_shipment_rows = copy_source_rows(
        source_conn,
        target_conn,
        SELECT_INBOUND_SHIPMENT_SYNC_SQL,
        DELETE_INBOUND_SHIPMENT_SYNC_SQL,
        "dashboard_tracking_inbound_shipment_sync",
        INBOUND_SHIPMENT_SYNC_COLUMNS,
        params,
        batch_size,
    )
    inbound_item_rows = copy_source_rows(
        source_conn,
        target_conn,
        SELECT_INBOUND_ITEM_SYNC_SQL,
        DELETE_INBOUND_ITEM_SYNC_SQL,
        "dashboard_tracking_inbound_item_sync",
        INBOUND_ITEM_SYNC_COLUMNS,
        params,
        batch_size,
    )
    return {
        "purchase_source_rows": purchase_rows,
        "fba_source_rows": fba_rows,
        "inbound_shipment_source_rows": inbound_shipment_rows,
        "inbound_item_source_rows": inbound_item_rows,
    }


def latest_replenishment_date(conn) -> date | None:
    with conn.cursor() as cursor:
        cursor.execute("select max(cur_date) as snapshot_date from dashboard_pur_plan_replenish_data")
        row = cursor.fetchone() or {}
    return row.get("snapshot_date")


def recent_replenishment_dates(conn, end_date: date, days: int) -> list[date]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select distinct cur_date
            from dashboard_pur_plan_replenish_data
            where cur_date <= %(end_date)s
            order by cur_date desc
            limit %(days)s
            """,
            {"end_date": end_date, "days": max(1, int(days or 1))},
        )
        rows = cursor.fetchall()
    return sorted(row["cur_date"] for row in rows if row.get("cur_date"))


def ensure_tracking_snapshot_columns(conn) -> None:
    required_columns = {
        "purchase_plan_count": "alter table dashboard_replenishment_tracking_snapshot add column purchase_plan_count int not null default 0 comment '追踪窗口内采购计划单数，包含已完成和未完成' after purchase_plan_msku_flag",
        "purchase_plan_total_qty": "alter table dashboard_replenishment_tracking_snapshot add column purchase_plan_total_qty decimal(18,4) not null default 0 comment '追踪窗口内采购计划总数量，包含已完成和未完成' after purchase_plan_count",
        "current_purchase_shipping_qty": "alter table dashboard_replenishment_tracking_snapshot add column current_purchase_shipping_qty decimal(18,4) not null default 0 comment '按追踪窗口采购计划数量归因的本次采购在途数量' after purchase_plan_total_qty",
        "historical_purchase_shipping_qty": "alter table dashboard_replenishment_tracking_snapshot add column historical_purchase_shipping_qty decimal(18,4) not null default 0 comment '超出追踪窗口采购计划数量的历史采购在途数量' after current_purchase_shipping_qty",
        "current_fba_shipment_plan_qty": "alter table dashboard_replenishment_tracking_snapshot add column current_fba_shipment_plan_qty decimal(18,4) not null default 0 comment '本次采购链路内FBA发货计划数量' after fba_shipment_plan_qty",
        "current_shipped_qty": "alter table dashboard_replenishment_tracking_snapshot add column current_shipped_qty decimal(18,4) not null default 0 comment '本次采购链路内实际发货数量' after current_fba_shipment_plan_qty",
        "historical_fba_shipment_plan_qty": "alter table dashboard_replenishment_tracking_snapshot add column historical_fba_shipment_plan_qty decimal(18,4) not null default 0 comment '历史采购链路FBA发货计划数量' after current_shipped_qty",
        "historical_shipped_qty": "alter table dashboard_replenishment_tracking_snapshot add column historical_shipped_qty decimal(18,4) not null default 0 comment '历史采购链路实际发货数量' after historical_fba_shipment_plan_qty",
        "shipment_attribution": "alter table dashboard_replenishment_tracking_snapshot add column shipment_attribution varchar(32) null comment '发货归因：current/historical/mixed/none' after historical_shipped_qty",
        "nearest_fba_eta_date": "alter table dashboard_replenishment_tracking_snapshot add column nearest_fba_eta_date datetime null comment '本次或历史FBA在途最近预计到货时间' after latest_shipment_time",
    }
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = database()
              and table_name = 'dashboard_replenishment_tracking_snapshot'
              and column_name in (
                  'purchase_plan_count',
                  'purchase_plan_total_qty',
                  'current_purchase_shipping_qty',
                  'historical_purchase_shipping_qty',
                  'current_fba_shipment_plan_qty',
                  'current_shipped_qty',
                  'historical_fba_shipment_plan_qty',
                  'historical_shipped_qty',
                  'shipment_attribution',
                  'nearest_fba_eta_date'
              )
            """
        )
        existing = {row.get("column_name") or row.get("COLUMN_NAME") for row in cursor.fetchall()}
        for column_name, statement in required_columns.items():
            if column_name not in existing:
                cursor.execute(statement)
    conn.commit()


def ensure_tracking_detail_columns(conn) -> None:
    required_columns = {
        "link_attribution": "alter table dashboard_replenishment_tracking_detail add column link_attribution varchar(32) null comment '链路归因：current/historical' after source_type",
    }
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = database()
              and table_name = 'dashboard_replenishment_tracking_detail'
              and column_name in ('link_attribution')
            """
        )
        existing = {row.get("column_name") or row.get("COLUMN_NAME") for row in cursor.fetchall()}
        for column_name, statement in required_columns.items():
            if column_name not in existing:
                cursor.execute(statement)
    conn.commit()


def ensure_inbound_shipment_sync_columns(conn) -> None:
    required_columns = {
        "receiving_time": "alter table dashboard_tracking_inbound_shipment_sync add column receiving_time datetime null comment 'FBA receiving time' after delivery_date",
        "closed_time": "alter table dashboard_tracking_inbound_shipment_sync add column closed_time datetime null comment 'FBA closed time' after receiving_time",
        "quantity_shipped": "alter table dashboard_tracking_inbound_shipment_sync add column quantity_shipped decimal(18,4) not null default 0 comment 'FBA shipped quantity' after quantity_total",
        "quantity_received": "alter table dashboard_tracking_inbound_shipment_sync add column quantity_received decimal(18,4) not null default 0 comment 'FBA received quantity' after quantity_shipped",
    }
    with conn.cursor() as cursor:
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = database()
              and table_name = 'dashboard_tracking_inbound_shipment_sync'
              and column_name in ('receiving_time', 'closed_time', 'quantity_shipped', 'quantity_received')
            """
        )
        existing = {row.get("column_name") or row.get("COLUMN_NAME") for row in cursor.fetchall()}
        for column_name, statement in required_columns.items():
            if column_name not in existing:
                cursor.execute(statement)
    conn.commit()


def refresh_tracking(conn, snapshot_date: date, tracking_window_days: int) -> dict[str, int]:
    params = {"snapshot_date": snapshot_date, "tracking_window_days": tracking_window_days}
    with conn.cursor() as cursor:
        for statement in (
            CREATE_TRACKING_SNAPSHOT_SQL,
            CREATE_TRACKING_DETAIL_SQL,
            CREATE_PURCHASE_PLAN_SYNC_SQL,
            CREATE_FBA_SHIPMENT_PLAN_SYNC_SQL,
            CREATE_INBOUND_SHIPMENT_SYNC_SQL,
            CREATE_INBOUND_ITEM_SYNC_SQL,
        ):
            cursor.execute(statement)
    ensure_inbound_shipment_sync_columns(conn)
    ensure_tracking_snapshot_columns(conn)
    ensure_tracking_detail_columns(conn)
    with conn.cursor() as cursor:
        cursor.execute(DELETE_DETAIL_SQL, params)
        cursor.execute(DELETE_SNAPSHOT_SQL, params)
        cursor.execute(INSERT_SNAPSHOT_SQL, params)
        snapshot_rows = max(cursor.rowcount, 0)
        cursor.execute(INSERT_DETAIL_SQL, params)
        detail_rows = max(cursor.rowcount, 0)
        cursor.execute(INSERT_PURCHASE_DETAIL_SQL, params)
        detail_rows += max(cursor.rowcount, 0)
        cursor.execute(INSERT_FBA_DETAIL_SQL, params)
        detail_rows += max(cursor.rowcount, 0)
        cursor.execute(INSERT_SHIPMENT_DETAIL_SQL, params)
        detail_rows += max(cursor.rowcount, 0)
    conn.commit()
    return {"snapshot_rows": snapshot_rows, "detail_rows": detail_rows}


def validate_tracking_result(
    snapshot_date: date,
    tracking_window_days: int,
    result: dict[str, int],
) -> None:
    snapshot_rows = int(result.get("snapshot_rows") or 0)
    if snapshot_rows <= 0:
        raise RuntimeError(
            "Business result validation failed: "
            f"replenishment tracking snapshot_date={snapshot_date} "
            f"tracking_window_days={tracking_window_days} has 0 rows."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh replenishment purchase/shipment tracking tables.")
    parser.add_argument("--snapshot-date", default="", help="补货日期，默认使用最新补货日期")
    parser.add_argument("--tracking-window-days", type=int, default=30, help="追踪窗口天数")
    parser.add_argument("--rolling-days", type=int, default=0, help="滚动刷新最近 N 个补货日期；启用后固定刷新 7/14/30 天窗口")
    parser.add_argument("--skip-source-sync", action="store_true", help="只用本地已同步的追踪源表刷新结果")
    parser.add_argument("--batch-size", type=int, default=1000, help="远端同步批量行数")
    args = parser.parse_args()

    apply_database_ini_env()
    with connect_target() as conn:
        selected_date = parse_day(args.snapshot_date) if args.snapshot_date else latest_replenishment_date(conn)
        if not selected_date:
            raise RuntimeError("没有可用的补货日期，无法刷新追踪表")
        started = datetime.now()
        source_zero = {
            "purchase_source_rows": 0,
            "fba_source_rows": 0,
            "inbound_shipment_source_rows": 0,
            "inbound_item_source_rows": 0,
        }
        if args.rolling_days:
            dates = recent_replenishment_dates(conn, selected_date, args.rolling_days)
            totals = {
                "runs": 0,
                "snapshot_rows": 0,
                "detail_rows": 0,
                "purchase_source_rows": 0,
                "fba_source_rows": 0,
                "inbound_shipment_source_rows": 0,
                "inbound_item_source_rows": 0,
            }
            source_conn = None if args.skip_source_sync else connect_source()
            try:
                for refresh_date in dates:
                    for window_days in TRACKING_WINDOWS:
                        source_result = source_zero.copy()
                        if source_conn is not None:
                            source_result = sync_tracking_sources(
                                conn,
                                source_conn,
                                refresh_date,
                                window_days,
                                max(100, args.batch_size),
                            )
                        result = refresh_tracking(conn, refresh_date, window_days)
                        validate_tracking_result(refresh_date, window_days, result)
                        totals["runs"] += 1
                        totals["snapshot_rows"] += result["snapshot_rows"]
                        totals["detail_rows"] += result["detail_rows"]
                        for key in source_zero:
                            totals[key] += source_result[key]
                        print(
                            f"[success] replenishment_tracking snapshot_date={refresh_date} "
                            f"tracking_window_days={window_days} "
                            f"purchase_source_rows={source_result['purchase_source_rows']} "
                            f"fba_source_rows={source_result['fba_source_rows']} "
                            f"inbound_shipment_source_rows={source_result['inbound_shipment_source_rows']} "
                            f"inbound_item_source_rows={source_result['inbound_item_source_rows']} "
                            f"snapshot_rows={result['snapshot_rows']} detail_rows={result['detail_rows']}"
                        )
            finally:
                if source_conn is not None:
                    source_conn.close()
            print(
                f"[success] replenishment_tracking rolling_days={args.rolling_days} "
                f"date_count={len(dates)} windows={','.join(str(day) for day in TRACKING_WINDOWS)} "
                f"runs={totals['runs']} purchase_source_rows={totals['purchase_source_rows']} "
                f"fba_source_rows={totals['fba_source_rows']} "
                f"inbound_shipment_source_rows={totals['inbound_shipment_source_rows']} "
                f"inbound_item_source_rows={totals['inbound_item_source_rows']} "
                f"snapshot_rows={totals['snapshot_rows']} detail_rows={totals['detail_rows']} "
                f"elapsed={(datetime.now() - started).total_seconds():.2f}s"
            )
        else:
            source_result = source_zero.copy()
            if not args.skip_source_sync:
                with connect_source() as source_conn:
                    source_result = sync_tracking_sources(
                        conn,
                        source_conn,
                        selected_date,
                        args.tracking_window_days,
                        max(100, args.batch_size),
                    )
            result = refresh_tracking(conn, selected_date, args.tracking_window_days)
            validate_tracking_result(selected_date, args.tracking_window_days, result)
            print(
                f"[success] replenishment_tracking snapshot_date={selected_date} "
                f"tracking_window_days={args.tracking_window_days} "
                f"purchase_source_rows={source_result['purchase_source_rows']} "
                f"fba_source_rows={source_result['fba_source_rows']} "
                f"inbound_shipment_source_rows={source_result['inbound_shipment_source_rows']} "
                f"inbound_item_source_rows={source_result['inbound_item_source_rows']} "
                f"snapshot_rows={result['snapshot_rows']} detail_rows={result['detail_rows']} "
                f"elapsed={(datetime.now() - started).total_seconds():.2f}s"
            )


if __name__ == "__main__":
    main()

