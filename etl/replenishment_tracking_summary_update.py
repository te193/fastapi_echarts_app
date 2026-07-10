from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from etl.dashboard_daily_update import connect_source, connect_target, parse_day
from etl.replenishment_update import apply_database_ini_env
from etl.replenishment_tracking_update import copy_source_rows


def product_category_case(sales_col: str, salable_col: str, margin_col: str) -> str:
    daily_sales_expr = f"case when coalesce({salable_col}, 0) > 0 then coalesce({sales_col}, 0) / {salable_col} else 0 end"
    return f"""
        case
            when ({daily_sales_expr}) >= 5 and coalesce({margin_col}, 0) >= 0.15 then '明星产品'
            when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and coalesce({margin_col}, 0) >= 0.25 then '明星产品'
            when ({daily_sales_expr}) >= 5 and coalesce({margin_col}, 0) >= 0.05 and coalesce({margin_col}, 0) < 0.15 then '潜力产品'
            when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and coalesce({margin_col}, 0) >= 0.10 and coalesce({margin_col}, 0) < 0.25 then '潜力产品'
            when ({daily_sales_expr}) >= 1 and ({daily_sales_expr}) < 5 and coalesce({margin_col}, 0) >= 0.05 and coalesce({margin_col}, 0) < 0.10 then '瘦狗产品'
            when ({daily_sales_expr}) < 1 and coalesce({margin_col}, 0) >= 0.05 then '瘦狗产品'
            when ({daily_sales_expr}) = 0 or (({daily_sales_expr}) > 1 and coalesce({margin_col}, 0) < 0.05) then '问题产品'
            else '问题产品'
        end
    """.strip()


PRODUCT_CATEGORY_7D_SQL = product_category_case("l.final_sales_7d", "l.r_7d_salable_days", "l.pprofit_ratio_7d")
PRODUCT_CATEGORY_14D_SQL = product_category_case("l.final_sales_14d", "l.r_14d_salable_days", "l.pprofit_ratio_14d")
PRODUCT_CATEGORY_30D_SQL = product_category_case("l.final_sales_30d", "l.r_30d_salable_days", "l.pprofit_ratio_30d")
PRODUCT_CATEGORY_90D_SQL = product_category_case("l.sales_90d", "l.r_90d_salable_days", "l.pprofit_ratio_90d")


CREATE_SUMMARY_SQL = """
create table if not exists dashboard_replenishment_tracking_summary (
    cutoff_date date not null comment '截止日期',
    country_category varchar(64) not null comment '国家类别',
    seller_name_new varchar(255) not null comment '店铺',
    seller_sku_adj varchar(255) not null comment 'MSKU',
    sku varchar(255) null comment 'SKU',
    first_replenishment_date date not null comment '首次进入补货日期',
    latest_replenishment_date date not null comment '最近补货日期',
    appearance_days int not null default 0 comment '补货结果中出现天数',
    current_replenishment_level varchar(32) null comment '当前补货分层',
    current_replenishment_level_sort int null comment '分层排序',
    historical_replenishment_levels varchar(255) null comment '历史出现过的补货分层',
    latest_replenishment_qty decimal(18,4) not null default 0 comment '最近补货建议数',
    latest_replenishment_value decimal(18,4) not null default 0 comment '最近补货货值',
    product_category varchar(32) null comment '销售角色分类',
    product_category_7d varchar(32) null comment '7天销售角色分类',
    product_category_14d varchar(32) null comment '14天销售角色分类',
    product_category_30d varchar(32) null comment '30天销售角色分类',
    product_category_90d varchar(32) null comment '90天销售角色分类',
    purchase_status varchar(32) not null default 'none' comment '采购状态',
    current_purchase_plan_count int not null default 0 comment '本次补货后采购计划单数',
    current_purchase_plan_qty decimal(18,4) not null default 0 comment '本次补货后采购计划数量',
    current_purchase_shipping_qty decimal(18,4) not null default 0 comment '本次采购在途数量',
    historical_purchase_shipping_qty decimal(18,4) not null default 0 comment '历史采购在途数量',
    local_stock_qty decimal(18,4) not null default 0 comment '本地仓数量',
    fba_status varchar(32) not null default 'none' comment 'FBA状态',
    current_fba_inbound_qty decimal(18,4) not null default 0 comment '本次FBA在途数量',
    historical_fba_inbound_qty decimal(18,4) not null default 0 comment '历史FBA在途数量',
    received_qty decimal(18,4) not null default 0 comment '已收货数量',
    nearest_fba_eta_date date null comment '最近预计到货日期',
    nearest_fba_eta_days int null comment '距离截止日期预计到货天数',
    purchase_plan_flag tinyint not null default 0 comment '是否已建采购计划',
    purchase_plan_count int not null default 0 comment '采购计划单数',
    purchase_plan_qty decimal(18,4) not null default 0 comment '采购计划数量',
    purchase_order_flag tinyint not null default 0 comment '是否已生成采购单',
    supplier_shipped_flag tinyint not null default 0 comment '供应商是否发货',
    purchase_inbound_qty decimal(18,4) not null default 0 comment '采购在途数量',
    local_received_flag tinyint not null default 0 comment '是否到本地仓',
    local_received_qty decimal(18,4) not null default 0 comment '本地收货数量',
    qc_flag tinyint not null default 0 comment '是否有质检',
    qc_passed_flag tinyint not null default 0 comment '质检是否通过',
    qc_good_qty decimal(18,4) not null default 0 comment '良品数量',
    qc_bad_qty decimal(18,4) not null default 0 comment '不良数量',
    fba_plan_flag tinyint not null default 0 comment '是否已建FBA计划',
    fba_plan_count int not null default 0 comment 'FBA计划单数',
    fba_plan_qty decimal(18,4) not null default 0 comment 'FBA计划数量',
    historical_fba_plan_count int not null default 0 comment '历史或待确认FBA计划单数',
    historical_fba_plan_qty decimal(18,4) not null default 0 comment '历史或待确认FBA计划数量',
    fba_shipped_flag tinyint not null default 0 comment '是否FBA出库在途',
    fba_shipped_qty decimal(18,4) not null default 0 comment 'FBA已发数量',
    fba_receiving_flag tinyint not null default 0 comment 'FBA是否开始接收',
    fba_received_qty decimal(18,4) not null default 0 comment 'FBA已收数量',
    fba_closed_flag tinyint not null default 0 comment 'FBA是否完成',
    current_node varchar(64) null comment '当前节点',
    breakpoint_node varchar(64) null comment '断点节点',
    breakpoint_reason varchar(255) null comment '断点原因',
    order_sn_summary text null comment '订单号摘要',
    latest_status varchar(255) null comment '最新状态',
    created_at timestamp not null default current_timestamp,
    updated_at timestamp not null default current_timestamp on update current_timestamp,
    primary key (cutoff_date, country_category, seller_name_new, seller_sku_adj),
    key idx_summary_filter (cutoff_date, current_replenishment_level_sort, country_category, seller_name_new),
    key idx_summary_status (cutoff_date, purchase_status, fba_status)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
"""

CREATE_LEVEL_HISTORY_SQL = """
create table if not exists dashboard_replenishment_tracking_summary_level_history (
    cutoff_date date not null comment '截止日期',
    country_category varchar(64) not null comment '国家类别',
    seller_name_new varchar(255) not null comment '店铺',
    seller_sku_adj varchar(255) not null comment 'MSKU',
    historical_replenishment_level varchar(32) not null comment '历史出现分层',
    first_level_date date not null comment '首次进入该分层日期',
    latest_level_date date not null comment '最近进入该分层日期',
    level_appearance_days int not null default 0 comment '该分层出现天数',
    is_current_level tinyint not null default 0 comment '截止日期最近分层是否仍为该层',
    purchase_plan_flag tinyint not null default 0 comment '该分层是否已建采购计划',
    purchase_plan_count int not null default 0 comment '该分层采购计划单数',
    purchase_plan_qty decimal(18,4) not null default 0 comment '该分层采购计划数量',
    purchase_plan_sn_list text null comment '该分层采购计划单号',
    supplier_shipped_flag tinyint not null default 0 comment '该分层供应商是否发货',
    purchase_order_count int not null default 0 comment '该分层采购单数',
    shipped_order_count int not null default 0 comment '该分层有物流采购单数',
    purchase_inbound_qty decimal(18,4) not null default 0 comment '该分层采购在途数量',
    supplier_unshipped_order_count int not null default 0 comment '该分层未发货采购单数',
    supplier_unshipped_qty decimal(18,4) not null default 0 comment '该分层供应商未发货数量',
    purchase_order_sn_list text null comment '该分层采购单号',
    logistics_provider_list text null comment '该分层物流商',
    logistics_order_list text null comment '该分层物流单号',
    primary key (cutoff_date, country_category, seller_name_new, seller_sku_adj, historical_replenishment_level)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
"""

DELETE_SUMMARY_SQL = "delete from dashboard_replenishment_tracking_summary where cutoff_date = %(cutoff_date)s"
DELETE_LEVEL_HISTORY_SQL = "delete from dashboard_replenishment_tracking_summary_level_history where cutoff_date = %(cutoff_date)s"
ENSURE_SUMMARY_COLUMNS_SQL = (
    "alter table dashboard_replenishment_tracking_summary add column product_category_7d varchar(32) null comment '7天销售角色分类'",
    "alter table dashboard_replenishment_tracking_summary add column product_category_14d varchar(32) null comment '14天销售角色分类'",
    "alter table dashboard_replenishment_tracking_summary add column product_category_30d varchar(32) null comment '30天销售角色分类'",
    "alter table dashboard_replenishment_tracking_summary add column product_category_90d varchar(32) null comment '90天销售角色分类'",
    "alter table dashboard_replenishment_tracking_summary add column purchase_plan_flag tinyint not null default 0 comment '是否已建采购计划'",
    "alter table dashboard_replenishment_tracking_summary add column purchase_plan_count int not null default 0 comment '采购计划单数'",
    "alter table dashboard_replenishment_tracking_summary add column purchase_plan_qty decimal(18,4) not null default 0 comment '采购计划数量'",
    "alter table dashboard_replenishment_tracking_summary add column purchase_order_flag tinyint not null default 0 comment '是否已生成采购单'",
    "alter table dashboard_replenishment_tracking_summary add column supplier_shipped_flag tinyint not null default 0 comment '供应商是否发货'",
    "alter table dashboard_replenishment_tracking_summary add column purchase_inbound_qty decimal(18,4) not null default 0 comment '采购在途数量'",
    "alter table dashboard_replenishment_tracking_summary add column local_received_flag tinyint not null default 0 comment '是否到本地仓'",
    "alter table dashboard_replenishment_tracking_summary add column local_received_qty decimal(18,4) not null default 0 comment '本地收货数量'",
    "alter table dashboard_replenishment_tracking_summary add column qc_flag tinyint not null default 0 comment '是否有质检'",
    "alter table dashboard_replenishment_tracking_summary add column qc_passed_flag tinyint not null default 0 comment '质检是否通过'",
    "alter table dashboard_replenishment_tracking_summary add column qc_good_qty decimal(18,4) not null default 0 comment '良品数量'",
    "alter table dashboard_replenishment_tracking_summary add column qc_bad_qty decimal(18,4) not null default 0 comment '不良数量'",
    "alter table dashboard_replenishment_tracking_summary add column fba_plan_flag tinyint not null default 0 comment '是否已建FBA计划'",
    "alter table dashboard_replenishment_tracking_summary add column fba_plan_count int not null default 0 comment 'FBA计划单数'",
    "alter table dashboard_replenishment_tracking_summary add column fba_plan_qty decimal(18,4) not null default 0 comment 'FBA计划数量'",
    "alter table dashboard_replenishment_tracking_summary add column historical_fba_plan_count int not null default 0 comment '历史或待确认FBA计划单数'",
    "alter table dashboard_replenishment_tracking_summary add column historical_fba_plan_qty decimal(18,4) not null default 0 comment '历史或待确认FBA计划数量'",
    "alter table dashboard_replenishment_tracking_summary add column fba_shipped_flag tinyint not null default 0 comment '是否FBA出库在途'",
    "alter table dashboard_replenishment_tracking_summary add column fba_shipped_qty decimal(18,4) not null default 0 comment 'FBA已发数量'",
    "alter table dashboard_replenishment_tracking_summary add column fba_receiving_flag tinyint not null default 0 comment 'FBA是否开始接收'",
    "alter table dashboard_replenishment_tracking_summary add column fba_received_qty decimal(18,4) not null default 0 comment 'FBA已收数量'",
    "alter table dashboard_replenishment_tracking_summary add column fba_closed_flag tinyint not null default 0 comment 'FBA是否完成'",
    "alter table dashboard_replenishment_tracking_summary add column current_node varchar(64) null comment '当前节点'",
    "alter table dashboard_replenishment_tracking_summary add column breakpoint_node varchar(64) null comment '断点节点'",
    "alter table dashboard_replenishment_tracking_summary add column breakpoint_reason varchar(255) null comment '断点原因'",
    "alter table dashboard_replenishment_tracking_summary add column order_sn_summary text null comment '订单号摘要'",
)
ENSURE_LEVEL_HISTORY_COLUMNS_SQL = (
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_plan_flag tinyint not null default 0 comment '该分层是否已建采购计划'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_plan_count int not null default 0 comment '该分层采购计划单数'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_plan_qty decimal(18,4) not null default 0 comment '该分层采购计划数量'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_plan_sn_list text null comment '该分层采购计划单号'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column supplier_shipped_flag tinyint not null default 0 comment '该分层供应商是否发货'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_order_count int not null default 0 comment '该分层采购单数'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column shipped_order_count int not null default 0 comment '该分层有物流采购单数'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_inbound_qty decimal(18,4) not null default 0 comment '该分层采购在途数量'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column supplier_unshipped_order_count int not null default 0 comment '该分层未发货采购单数'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column supplier_unshipped_qty decimal(18,4) not null default 0 comment '该分层供应商未发货数量'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column purchase_order_sn_list text null comment '该分层采购单号'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column logistics_provider_list text null comment '该分层物流商'",
    "alter table dashboard_replenishment_tracking_summary_level_history add column logistics_order_list text null comment '该分层物流单号'",
)

CREATE_PURCHASE_ORDER_SYNC_SQL = """
create table if not exists dashboard_tracking_purchase_order_sync (
    id bigint not null auto_increment comment 'auto id',
    plan_sn varchar(128) null comment 'purchase plan number',
    order_sn varchar(128) null comment 'purchase order number',
    status varchar(255) null comment 'purchase order status',
    order_create_time datetime null comment 'purchase order create time',
    msku varchar(128) null comment 'MSKU',
    sku varchar(128) null comment 'local SKU',
    quantity_plan decimal(18,4) not null default 0 comment 'planned quantity',
    quantity_real decimal(18,4) not null default 0 comment 'real quantity',
    quantity_receive decimal(18,4) not null default 0 comment 'received quantity',
    logistics_provider varchar(255) null comment 'logistics provider',
    logistics_order varchar(255) null comment 'logistics order',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_purchase_order_plan (plan_sn),
    key idx_purchase_order_order (order_sn),
    key idx_purchase_order_time (order_create_time)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking purchase order source sync';
"""

DELETE_PURCHASE_ORDER_SYNC_SQL = """
delete from dashboard_tracking_purchase_order_sync
where order_create_time >= %(window_start)s
  and order_create_time < %(window_end_exclusive)s;
"""

SELECT_PURCHASE_ORDER_SYNC_SQL = """
select
    plan_sn,
    order_sn,
    status,
    coalesce(
        str_to_date(nullif(order_create_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(order_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        create_time
    ) as order_create_time,
    msku,
    sku,
    coalesce(quantity_plan, 0) as quantity_plan,
    coalesce(quantity_real, 0) as quantity_real,
    coalesce(quantity_receive, 0) as quantity_receive,
    logistics_provider,
    logistics_order,
    create_time as source_create_time
from dwd_datasync.lx_purchase_purchase_order
where coalesce(
        str_to_date(nullif(order_create_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(order_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        create_time
    ) >= %(window_start)s
  and coalesce(
        str_to_date(nullif(order_create_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        str_to_date(nullif(order_time, ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
        create_time
    ) < %(window_end_exclusive)s
  and coalesce(plan_sn, '') <> '';
"""

PURCHASE_ORDER_SYNC_COLUMNS = (
    "plan_sn",
    "order_sn",
    "status",
    "order_create_time",
    "msku",
    "sku",
    "quantity_plan",
    "quantity_real",
    "quantity_receive",
    "logistics_provider",
    "logistics_order",
    "source_create_time",
)

CREATE_RECEIPT_ORDER_SYNC_SQL = """
create table if not exists dashboard_tracking_receipt_order_sync (
    id bigint not null auto_increment comment 'auto id',
    order_sn varchar(128) null comment 'receipt order number',
    business_order_sn varchar(128) null comment 'source purchase order number',
    status varchar(255) null comment 'receipt status',
    order_create_time datetime null comment 'receipt order create time',
    receive_time datetime null comment 'receipt time',
    ware_name varchar(255) null comment 'warehouse name',
    logistics_company varchar(255) null comment 'logistics company',
    logistics_order_no varchar(255) null comment 'logistics order number',
    sku varchar(128) null comment 'local SKU',
    seller_name varchar(255) null comment 'seller name',
    country varchar(128) null comment 'country',
    notice_num_total decimal(18,4) not null default 0 comment 'notice receive quantity',
    product_receive_num decimal(18,4) not null default 0 comment 'actual received quantity',
    quantity_qc_prepare decimal(18,4) not null default 0 comment 'pending qc quantity',
    quantity_qc_already decimal(18,4) not null default 0 comment 'qc done quantity',
    quality_examine_status varchar(255) null comment 'qc status summary',
    qc_sn varchar(255) null comment 'qc order number',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_receipt_business_order (business_order_sn),
    key idx_receipt_order (order_sn),
    key idx_receipt_time (receive_time)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking receipt order source sync';
"""

DELETE_RECEIPT_ORDER_SYNC_SQL = """
delete from dashboard_tracking_receipt_order_sync
where coalesce(receive_time, order_create_time, source_create_time) >= %(window_start)s
  and coalesce(receive_time, order_create_time, source_create_time) < %(window_end_exclusive)s;
"""

SELECT_RECEIPT_ORDER_SYNC_SQL = """
select
    order_sn,
    business_order_sn,
    status,
    order_create_time,
    receive_time,
    ware_name,
    logistics_company,
    logistics_order_no,
    sku,
    seller_name,
    country,
    coalesce(notice_num_total, 0) as notice_num_total,
    coalesce(product_receive_num, 0) as product_receive_num,
    coalesce(quantity_qc_prepare, 0) as quantity_qc_prepare,
    coalesce(quantity_qc_already, 0) as quantity_qc_already,
    quality_examine_status,
    qc_sn,
    create_time as source_create_time
from dwd_datasync.lx_storage_receipt_order
where coalesce(receive_time, order_create_time, create_time) >= %(window_start)s
  and coalesce(receive_time, order_create_time, create_time) < %(window_end_exclusive)s
  and coalesce(business_order_sn, '') <> '';
"""

RECEIPT_ORDER_SYNC_COLUMNS = (
    "order_sn",
    "business_order_sn",
    "status",
    "order_create_time",
    "receive_time",
    "ware_name",
    "logistics_company",
    "logistics_order_no",
    "sku",
    "seller_name",
    "country",
    "notice_num_total",
    "product_receive_num",
    "quantity_qc_prepare",
    "quantity_qc_already",
    "quality_examine_status",
    "qc_sn",
    "source_create_time",
)

CREATE_QC_ORDER_SYNC_SQL = """
create table if not exists dashboard_tracking_qc_order_sync (
    id bigint not null auto_increment comment 'auto id',
    qc_sn varchar(128) null comment 'qc order number',
    status varchar(255) null comment 'qc status',
    qc_type varchar(255) null comment 'qc type',
    order_type varchar(255) null comment 'source order type',
    order_sn varchar(128) null comment 'source purchase order number',
    delivery_order_sn varchar(128) null comment 'receipt order number',
    receive_time datetime null comment 'receive time',
    qc_time datetime null comment 'qc time',
    order_create_time datetime null comment 'qc order create time',
    sku varchar(128) null comment 'local SKU',
    seller_name varchar(255) null comment 'seller name',
    country varchar(128) null comment 'country',
    product_receive_num decimal(18,4) not null default 0 comment 'received quantity',
    qc_num decimal(18,4) not null default 0 comment 'sample qc quantity',
    qc_bad_num decimal(18,4) not null default 0 comment 'sample bad quantity',
    qc_rate_pass varchar(64) null comment 'qc pass rate',
    product_good_num decimal(18,4) not null default 0 comment 'good quantity',
    product_bad_num decimal(18,4) not null default 0 comment 'bad quantity',
    source_create_time datetime null comment 'source sync create time',
    created_at datetime not null default current_timestamp comment 'created at',
    updated_at datetime not null default current_timestamp on update current_timestamp comment 'updated at',
    primary key (id),
    key idx_qc_delivery_order (delivery_order_sn),
    key idx_qc_purchase_order (order_sn),
    key idx_qc_time (qc_time)
) engine=InnoDB default charset=utf8mb4 comment='replenishment tracking qc order source sync';
"""

DELETE_QC_ORDER_SYNC_SQL = """
delete from dashboard_tracking_qc_order_sync
where coalesce(qc_time, order_create_time, receive_time, source_create_time) >= %(window_start)s
  and coalesce(qc_time, order_create_time, receive_time, source_create_time) < %(window_end_exclusive)s;
"""

SELECT_QC_ORDER_SYNC_SQL = """
select
    qc_sn,
    status,
    qc_type,
    order_type,
    order_sn,
    delivery_order_sn,
    receive_time,
    qc_time,
    order_create_time,
    sku,
    seller_name,
    country,
    coalesce(product_receive_num, 0) as product_receive_num,
    coalesce(qc_num, 0) as qc_num,
    coalesce(qc_bad_num, 0) as qc_bad_num,
    qc_rate_pass,
    coalesce(product_good_num, 0) as product_good_num,
    coalesce(product_bad_num, 0) as product_bad_num,
    create_time as source_create_time
from dwd_datasync.lx_storage_qc_order
where coalesce(qc_time, order_create_time, receive_time, create_time) >= %(window_start)s
  and coalesce(qc_time, order_create_time, receive_time, create_time) < %(window_end_exclusive)s
  and coalesce(delivery_order_sn, '') <> '';
"""

QC_ORDER_SYNC_COLUMNS = (
    "qc_sn",
    "status",
    "qc_type",
    "order_type",
    "order_sn",
    "delivery_order_sn",
    "receive_time",
    "qc_time",
    "order_create_time",
    "sku",
    "seller_name",
    "country",
    "product_receive_num",
    "qc_num",
    "qc_bad_num",
    "qc_rate_pass",
    "product_good_num",
    "product_bad_num",
    "source_create_time",
)

INSERT_SUMMARY_SQL = """
insert into dashboard_replenishment_tracking_summary (
    cutoff_date, country_category, seller_name_new, seller_sku_adj, sku,
    first_replenishment_date, latest_replenishment_date, appearance_days,
    current_replenishment_level, current_replenishment_level_sort, historical_replenishment_levels,
    latest_replenishment_qty, latest_replenishment_value, product_category,
    product_category_7d, product_category_14d, product_category_30d, product_category_90d,
    purchase_status, current_purchase_plan_count, current_purchase_plan_qty,
    current_purchase_shipping_qty, historical_purchase_shipping_qty, local_stock_qty,
    fba_status, current_fba_inbound_qty, historical_fba_inbound_qty, received_qty,
    nearest_fba_eta_date, nearest_fba_eta_days,
    purchase_plan_flag, purchase_plan_count, purchase_plan_qty,
    purchase_order_flag, supplier_shipped_flag, purchase_inbound_qty,
    local_received_flag, local_received_qty, qc_flag, qc_passed_flag, qc_good_qty, qc_bad_qty,
    fba_plan_flag, fba_plan_count, fba_plan_qty,
    historical_fba_plan_count, historical_fba_plan_qty,
    fba_shipped_flag, fba_shipped_qty, fba_receiving_flag, fba_received_qty, fba_closed_flag,
    current_node, breakpoint_node, breakpoint_reason, order_sn_summary,
    latest_status
)
with base as (
    select
        d.*,
        case
            when replace(coalesce(d.max_sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(d.max_sku, ''), '-zu', ''), char_length(replace(coalesce(d.max_sku, ''), '-zu', '')) - 1)
            else replace(coalesce(d.max_sku, ''), '-zu', '')
        end as tracking_sku
    from dashboard_pur_plan_replenish_data d
    where cur_date <= %(cutoff_date)s
      and support_replenish_level_sort in (1, 2, 3)
),
agg as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        min(cur_date) as first_replenishment_date,
        max(cur_date) as latest_replenishment_date,
        count(distinct cur_date) as appearance_days,
        group_concat(distinct support_replenish_level order by support_replenish_level_sort separator ',') as historical_replenishment_levels
    from base
    group by country_category, seller_name_new, seller_sku_adj
),
latest_row as (
    select b.*
    from base b
    join agg a
      on a.country_category = b.country_category
     and a.seller_name_new = b.seller_name_new
     and a.seller_sku_adj = b.seller_sku_adj
     and a.latest_replenishment_date = b.cur_date
),
purchase_plan_doc as (
    select
        m.country_category,
        m.seller_name_new,
        m.seller_sku_adj,
        count(distinct m.plan_sn) as purchase_plan_count,
        sum(coalesce(m.quantity_plan, 0)) as purchase_plan_total_qty,
        sum(case when coalesce(m.status_text, '') <> '已完成' then coalesce(m.quantity_plan, 0) else 0 end) as purchase_plan_qty,
        group_concat(distinct m.plan_sn order by m.plan_create_time separator ',') as purchase_plan_sn_list,
        group_concat(distinct m.status_text order by m.plan_create_time separator ',') as purchase_plan_status,
        max(case when coalesce(m.status_text, '') <> '已完成' then m.expect_arrive_time end) as purchase_expect_arrive_time,
        max(m.plan_create_time) as latest_purchase_plan_time
    from (
        select distinct
            p0.country_category,
            p0.seller_name_new,
            p0.seller_sku_adj,
            pp0.plan_sn,
            pp0.status_text,
            pp0.plan_create_time,
            pp0.quantity_plan,
            pp0.expect_arrive_time
        from base p0
        join dashboard_tracking_purchase_plan_sync pp0
          on pp0.plan_create_time >= p0.cur_date
         and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
         and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
         and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
         and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
    ) m
    group by m.country_category, m.seller_name_new, m.seller_sku_adj
),
purchase_order_doc as (
    select
        m.country_category,
        m.seller_name_new,
        m.seller_sku_adj,
        count(distinct m.order_sn) as purchase_order_count,
        count(distinct case when nullif(m.logistics_provider, '') is not null or nullif(m.logistics_order, '') is not null then m.order_sn end) as shipped_order_count,
        sum(case when nullif(m.logistics_provider, '') is not null or nullif(m.logistics_order, '') is not null then coalesce(nullif(m.quantity_real, 0), m.quantity_plan, 0) else 0 end) as purchase_inbound_qty,
        group_concat(distinct m.order_sn order by m.order_create_time separator ',') as purchase_order_sn_list
    from (
        select distinct
            p0.country_category,
            p0.seller_name_new,
            p0.seller_sku_adj,
            po.order_sn,
            po.sku,
            po.order_create_time,
            po.quantity_real,
            po.quantity_plan,
            po.logistics_provider,
            po.logistics_order
        from base p0
        join dashboard_tracking_purchase_plan_sync pp0
          on pp0.plan_create_time >= p0.cur_date
         and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
         and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
         and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
         and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
        join dashboard_tracking_purchase_order_sync po
          on po.plan_sn = pp0.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and case
            when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
            else replace(coalesce(po.sku, ''), '-zu', '')
         end = p0.tracking_sku collate utf8mb4_unicode_ci
    ) m
    group by m.country_category, m.seller_name_new, m.seller_sku_adj
),
receipt_doc as (
    select
        m.country_category,
        m.seller_name_new,
        m.seller_sku_adj,
        count(distinct ro.order_sn) as receipt_order_count,
        sum(coalesce(ro.product_receive_num, 0)) as local_received_qty,
        sum(coalesce(ro.notice_num_total, 0)) as local_notice_qty,
        max(coalesce(ro.receive_time, ro.order_create_time)) as latest_receive_time,
        group_concat(distinct ro.order_sn order by coalesce(ro.receive_time, ro.order_create_time) separator ',') as receipt_order_sn_list,
        group_concat(distinct nullif(ro.ware_name, '') order by ro.ware_name separator ',') as warehouse_name_list,
        group_concat(distinct nullif(ro.status, '') order by ro.status separator ',') as receipt_status_list,
        group_concat(distinct nullif(ro.qc_sn, '') order by ro.qc_sn separator ',') as qc_sn_list
    from (
        select distinct
            p0.country_category,
            p0.seller_name_new,
            p0.seller_sku_adj,
            po.order_sn,
            po.sku
        from base p0
        join dashboard_tracking_purchase_plan_sync pp0
          on pp0.plan_create_time >= p0.cur_date
         and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
         and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
         and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
         and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
        join dashboard_tracking_purchase_order_sync po
         on po.plan_sn = pp0.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and case
            when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
            else replace(coalesce(po.sku, ''), '-zu', '')
         end = p0.tracking_sku collate utf8mb4_unicode_ci
    ) m
    join dashboard_tracking_receipt_order_sync ro
      on ro.business_order_sn = m.order_sn collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ro.sku, ''), '-zu', ''), char_length(replace(coalesce(ro.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ro.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(m.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(m.sku, ''), '-zu', ''), char_length(replace(coalesce(m.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(m.sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
    group by m.country_category, m.seller_name_new, m.seller_sku_adj
),
qc_doc as (
    select
        m.country_category,
        m.seller_name_new,
        m.seller_sku_adj,
        count(distinct qo.qc_sn) as qc_count,
        sum(coalesce(qo.product_good_num, 0)) as qc_good_qty,
        sum(coalesce(qo.product_bad_num, 0)) as qc_bad_qty,
        sum(coalesce(qo.qc_num, 0)) as qc_sample_qty,
        max(coalesce(qo.qc_time, qo.order_create_time, qo.receive_time)) as latest_qc_time,
        group_concat(distinct qo.qc_sn order by coalesce(qo.qc_time, qo.order_create_time, qo.receive_time) separator ',') as qc_sn_list,
        group_concat(distinct nullif(qo.status, '') order by qo.status separator ',') as qc_status_list
    from (
        select distinct
            p0.country_category,
            p0.seller_name_new,
            p0.seller_sku_adj,
            ro.order_sn as receipt_order_sn,
            ro.business_order_sn,
            ro.sku
        from base p0
        join dashboard_tracking_purchase_plan_sync pp0
          on pp0.plan_create_time >= p0.cur_date
         and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
         and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
         and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
         and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
        join dashboard_tracking_purchase_order_sync po
         on po.plan_sn = pp0.plan_sn collate utf8mb4_unicode_ci
         and po.status <> '作废'
         and case
            when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
            else replace(coalesce(po.sku, ''), '-zu', '')
         end = p0.tracking_sku collate utf8mb4_unicode_ci
        join dashboard_tracking_receipt_order_sync ro
          on ro.business_order_sn = po.order_sn collate utf8mb4_unicode_ci
         and case
            when replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(ro.sku, ''), '-zu', ''), char_length(replace(coalesce(ro.sku, ''), '-zu', '')) - 1)
            else replace(coalesce(ro.sku, ''), '-zu', '')
         end = case
            when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
                then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
            else replace(coalesce(po.sku, ''), '-zu', '')
         end collate utf8mb4_unicode_ci
         and coalesce(ro.product_receive_num, 0) > 0
    ) m
    join dashboard_tracking_qc_order_sync qo
      on qo.delivery_order_sn = m.receipt_order_sn collate utf8mb4_unicode_ci
     and qo.order_sn = m.business_order_sn collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(qo.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(qo.sku, ''), '-zu', ''), char_length(replace(coalesce(qo.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(qo.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(m.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(m.sku, ''), '-zu', ''), char_length(replace(coalesce(m.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(m.sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
    group by m.country_category, m.seller_name_new, m.seller_sku_adj
),
current_fba_plan_match as (
    select distinct
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        fp.order_sn,
        fp.sku,
        fp.plan_create_time,
        fp.shipment_plan_quantity
    from base p0
    join dashboard_tracking_purchase_plan_sync pp0
      on pp0.plan_create_time >= p0.cur_date
     and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
     and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
     and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
     and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
    left join dashboard_tracking_purchase_order_sync po
      on po.plan_sn = pp0.plan_sn collate utf8mb4_unicode_ci
     and po.status <> '作废'
     and case
        when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(po.sku, ''), '-zu', '')
     end = p0.tracking_sku collate utf8mb4_unicode_ci
     and (nullif(po.logistics_provider, '') is not null or nullif(po.logistics_order, '') is not null)
    left join dashboard_tracking_receipt_order_sync ro
      on ro.business_order_sn = po.order_sn collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ro.sku, ''), '-zu', ''), char_length(replace(coalesce(ro.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ro.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(po.sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
     and coalesce(ro.product_receive_num, 0) > 0
    left join dashboard_tracking_qc_order_sync qo
      on qo.delivery_order_sn = ro.order_sn collate utf8mb4_unicode_ci
     and qo.order_sn = ro.business_order_sn collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(qo.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(qo.sku, ''), '-zu', ''), char_length(replace(coalesce(qo.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(qo.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ro.sku, ''), '-zu', ''), char_length(replace(coalesce(ro.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ro.sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
     and coalesce(qo.product_good_num, 0) > 0
     and coalesce(qo.product_bad_num, 0) = 0
    join dashboard_tracking_fba_shipment_plan_sync fp
      on fp.plan_create_time >= pp0.plan_create_time
     and fp.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
     and fp.country_category = p0.country_category collate utf8mb4_unicode_ci
     and fp.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
     and fp.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(fp.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(fp.sku, ''), '-zu', ''), char_length(replace(coalesce(fp.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(fp.sku, ''), '-zu', '')
     end = p0.tracking_sku collate utf8mb4_unicode_ci
     and abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp0.quantity_plan, 0)) <= greatest(coalesce(pp0.quantity_plan, 0) * 0.2, 5)
),
current_fba_plan_doc as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        count(distinct order_sn) as fba_plan_count,
        sum(coalesce(shipment_plan_quantity, 0)) as fba_plan_qty,
        group_concat(distinct order_sn order by plan_create_time separator ',') as fba_plan_sn_list
    from current_fba_plan_match
    group by country_category, seller_name_new, seller_sku_adj
),
current_fba_shipped_doc as (
    select
        cfpm.country_category,
        cfpm.seller_name_new,
        cfpm.seller_sku_adj,
        count(distinct ii.shipment_id) as fba_shipment_count,
        count(distinct ii.shipment_sn) as fba_internal_shipment_count,
        sum(coalesce(ii.quantity_shipped, 0)) as fba_shipped_qty,
        sum(coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0)) as fba_received_qty,
        count(distinct case
            when coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0) > 0
              or coalesce(ish.quantity_received, 0) > 0
              or upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) = 'RECEIVING'
              or upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) = 'CLOSED'
              or upper(coalesce(ish.shipment_status, ish.status_name, '')) in ('RECEIVING', 'CLOSED')
              or ish.receiving_time is not null
              or ish.closed_time is not null
            then ii.shipment_id
        end) as receiving_shipment_count,
        count(distinct case
            when upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) = 'CLOSED'
              or upper(coalesce(ish.shipment_status, ish.status_name, '')) = 'CLOSED'
              or ish.closed_time is not null
            then ii.shipment_id
        end) as closed_shipment_count,
        group_concat(distinct ii.shipment_id order by coalesce(ii.shipment_time, ii.source_create_time) separator ',') as fba_shipment_id_list,
        group_concat(distinct ii.shipment_sn order by coalesce(ii.shipment_time, ii.source_create_time) separator ',') as fba_shipment_sn_list
    from current_fba_plan_match cfpm
    join dashboard_tracking_inbound_item_sync ii
      on ii.shipment_order_sn = cfpm.order_sn collate utf8mb4_unicode_ci
     and ii.country_category = cfpm.country_category collate utf8mb4_unicode_ci
     and ii.seller_name_norm = cfpm.seller_name_new collate utf8mb4_unicode_ci
     and ii.msku = cfpm.seller_sku_adj collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(ii.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ii.sku, ''), '-zu', ''), char_length(replace(coalesce(ii.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ii.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(cfpm.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(cfpm.sku, ''), '-zu', ''), char_length(replace(coalesce(cfpm.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(cfpm.sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
     and nullif(ii.shipment_id, '') is not null
     and ii.shipment_id like 'FBA%%'
    left join dashboard_tracking_inbound_shipment_sync ish
      on ish.shipment_sn = ii.shipment_sn collate utf8mb4_unicode_ci
    group by cfpm.country_category, cfpm.seller_name_new, cfpm.seller_sku_adj
),
all_fba_plan_match as (
    select distinct
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        fp.order_sn,
        fp.plan_create_time,
        fp.shipment_plan_quantity
    from base p0
    join dashboard_tracking_fba_shipment_plan_sync fp
      on fp.plan_create_time >= p0.cur_date
     and fp.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
     and fp.country_category = p0.country_category collate utf8mb4_unicode_ci
     and fp.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
     and fp.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
),
historical_fba_plan_doc as (
    select
        afpm.country_category,
        afpm.seller_name_new,
        afpm.seller_sku_adj,
        count(distinct afpm.order_sn) as historical_fba_plan_count,
        sum(coalesce(afpm.shipment_plan_quantity, 0)) as historical_fba_plan_qty,
        group_concat(distinct afpm.order_sn order by afpm.plan_create_time separator ',') as historical_fba_plan_sn_list
    from all_fba_plan_match afpm
    left join current_fba_plan_match cfpm
      on cfpm.country_category = afpm.country_category collate utf8mb4_unicode_ci
     and cfpm.seller_name_new = afpm.seller_name_new collate utf8mb4_unicode_ci
     and cfpm.seller_sku_adj = afpm.seller_sku_adj collate utf8mb4_unicode_ci
     and cfpm.order_sn = afpm.order_sn collate utf8mb4_unicode_ci
    where cfpm.order_sn is null
    group by afpm.country_category, afpm.seller_name_new, afpm.seller_sku_adj
),
active_fba_eta_doc as (
    select
        l.country_category,
        l.seller_name_new,
        l.seller_sku_adj,
        coalesce(
            min(case
                    when coalesce(ish.expected_arrival_date, ish.eta_date) >= %(cutoff_date)s
                    then coalesce(ish.expected_arrival_date, ish.eta_date)
                end),
            max(case
                    when coalesce(ish.expected_arrival_date, ish.eta_date) < %(cutoff_date)s
                    then coalesce(ish.expected_arrival_date, ish.eta_date)
                end)
        ) as nearest_fba_eta_date
    from latest_row l
    join agg a
      on a.country_category = l.country_category
     and a.seller_name_new = l.seller_name_new
     and a.seller_sku_adj = l.seller_sku_adj
    join dashboard_tracking_inbound_item_sync ii
      on ii.country_category = l.country_category collate utf8mb4_unicode_ci
     and ii.seller_name_norm = l.seller_name_new collate utf8mb4_unicode_ci
     and ii.msku = l.seller_sku_adj collate utf8mb4_unicode_ci
     and case
        when replace(coalesce(ii.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ii.sku, ''), '-zu', ''), char_length(replace(coalesce(ii.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ii.sku, ''), '-zu', '')
     end = l.tracking_sku collate utf8mb4_unicode_ci
     and coalesce(ii.shipment_time, ii.source_create_time) >= date_sub(a.first_replenishment_date, interval 30 day)
     and coalesce(ii.shipment_time, ii.source_create_time) < date_add(%(cutoff_date)s, interval 1 day)
     and nullif(ii.shipment_id, '') is not null
     and ii.shipment_id like 'FBA%%'
    left join dashboard_tracking_inbound_shipment_sync ish
      on ish.shipment_sn = ii.shipment_sn collate utf8mb4_unicode_ci
    where coalesce(ii.quantity_shipped, 0) > coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0)
      and upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) <> 'CLOSED'
      and ish.closed_time is null
    group by l.country_category, l.seller_name_new, l.seller_sku_adj
)
select
    %(cutoff_date)s,
    a.country_category,
    a.seller_name_new,
    a.seller_sku_adj,
    l.max_sku,
    a.first_replenishment_date,
    a.latest_replenishment_date,
    a.appearance_days,
    l.support_replenish_level,
    l.support_replenish_level_sort,
    a.historical_replenishment_levels,
    coalesce(l.replenish_qty, 0),
    coalesce(l.replenish_cost, 0),
    coalesce(l.abcd_category, '未分类'),
    {PRODUCT_CATEGORY_7D_SQL},
    {PRODUCT_CATEGORY_14D_SQL},
    {PRODUCT_CATEGORY_30D_SQL},
    {PRODUCT_CATEGORY_90D_SQL},
    case
        when coalesce(ppd.purchase_plan_count, 0) > 0 and coalesce(t.historical_purchase_shipping_qty, 0) > 0 then 'mixed'
        when coalesce(ppd.purchase_plan_count, 0) > 0 then 'current'
        when coalesce(t.historical_purchase_shipping_qty, 0) > 0 then 'historical'
        else 'none'
    end as purchase_status,
    coalesce(ppd.purchase_plan_count, 0),
    coalesce(ppd.purchase_plan_total_qty, 0),
    greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)),
    coalesce(t.historical_purchase_shipping_qty, 0),
    coalesce(l.local_quantity, 0),
    case
        when coalesce(t.current_fba_shipment_plan_qty, 0) > 0 and coalesce(t.historical_fba_shipment_plan_qty, 0) > 0 then 'mixed'
        when coalesce(t.current_fba_shipment_plan_qty, 0) > 0 then 'current'
        when coalesce(t.historical_fba_shipment_plan_qty, 0) > 0 then 'historical'
        else 'none'
    end as fba_status,
    coalesce(t.current_fba_shipment_plan_qty, 0),
    coalesce(t.historical_fba_shipment_plan_qty, 0),
    coalesce(t.received_qty, 0),
    eta.nearest_fba_eta_date,
    case when eta.nearest_fba_eta_date is null then null else datediff(eta.nearest_fba_eta_date, %(cutoff_date)s) end,
    case when coalesce(ppd.purchase_plan_count, 0) > 0 then 1 else 0 end,
    coalesce(ppd.purchase_plan_count, 0),
    coalesce(ppd.purchase_plan_total_qty, 0),
    case when coalesce(pod.purchase_order_count, 0) > 0 then 1 else 0 end,
    case when coalesce(pod.shipped_order_count, 0) > 0 or coalesce(rd.local_received_qty, 0) > 0 or coalesce(qd.qc_good_qty, 0) > 0 then 1 else 0 end,
    greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)),
    case when coalesce(rd.local_received_qty, 0) > 0 then 1 else 0 end,
    coalesce(rd.local_received_qty, 0),
    case when coalesce(qd.qc_count, 0) > 0 then 1 else 0 end,
    case when coalesce(qd.qc_good_qty, 0) > 0 and coalesce(qd.qc_bad_qty, 0) = 0 then 1 else 0 end,
    coalesce(qd.qc_good_qty, 0),
    coalesce(qd.qc_bad_qty, 0),
    case when coalesce(cfpd.fba_plan_count, 0) > 0 then 1 else 0 end,
    coalesce(cfpd.fba_plan_count, 0),
    coalesce(cfpd.fba_plan_qty, 0),
    coalesce(hfpd.historical_fba_plan_count, 0),
    coalesce(hfpd.historical_fba_plan_qty, 0),
    case when coalesce(fbsd.fba_shipment_count, 0) > 0 then 1 else 0 end,
    coalesce(fbsd.fba_shipped_qty, 0),
    case when coalesce(fbsd.receiving_shipment_count, 0) > 0 then 1 else 0 end,
    coalesce(fbsd.fba_received_qty, 0),
    case
        when coalesce(fbsd.fba_shipment_count, 0) > 0
         and coalesce(fbsd.closed_shipment_count, 0) = coalesce(fbsd.fba_shipment_count, 0)
        then 1 else 0
    end,
    case
        when coalesce(ppd.purchase_plan_count, 0) <= 0 then '建采购计划'
        when greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)) <= 0 then '供应商发货'
        when coalesce(rd.local_received_qty, 0) <= 0 then '到本地仓'
        when coalesce(rd.local_received_qty, 0) > 0 then '质检通过'
        when coalesce(cfpd.fba_plan_count, 0) <= 0 then '建FBA计划'
        when coalesce(fbsd.fba_shipment_count, 0) <= 0 then 'FBA出库'
        when coalesce(fbsd.receiving_shipment_count, 0) <= 0 then 'FBA接收'
        when coalesce(fbsd.closed_shipment_count, 0) <= 0 then 'FBA完成'
        else '链路完成'
    end,
    case
        when coalesce(ppd.purchase_plan_count, 0) <= 0 then '建采购计划'
        when greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)) <= 0 then '供应商发货'
        when coalesce(rd.local_received_qty, 0) <= 0 then '到本地仓'
        when coalesce(rd.local_received_qty, 0) > 0 then '质检通过'
        when coalesce(cfpd.fba_plan_count, 0) <= 0 then '建FBA计划'
        when coalesce(fbsd.fba_shipment_count, 0) <= 0 then 'FBA出库'
        when coalesce(fbsd.receiving_shipment_count, 0) <= 0 then 'FBA接收'
        when coalesce(fbsd.closed_shipment_count, 0) <= 0 then 'FBA完成'
        else '链路完成'
    end,
    case
        when coalesce(ppd.purchase_plan_count, 0) <= 0 then '未匹配到补货后的采购计划'
        when greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)) <= 0 then '已建采购计划，但未确认采购在途'
        when coalesce(rd.local_received_qty, 0) <= 0 then concat('采购已在途，但未确认到本地仓 ', greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0)))
        when coalesce(rd.local_received_qty, 0) > 0 then concat('已到本地仓，但未确认质检通过 ', coalesce(rd.local_received_qty, 0))
        when coalesce(cfpd.fba_plan_count, 0) <= 0 then '质检已通过，但未确认创建本次FBA计划'
        when coalesce(fbsd.fba_shipment_count, 0) <= 0 then '已建FBA计划，但未确认出库在途'
        when coalesce(fbsd.receiving_shipment_count, 0) <= 0 then 'FBA在途，未开始接收'
        when coalesce(fbsd.closed_shipment_count, 0) <= 0 then 'FBA已开始接收，未确认收货完成'
        else '链路完成'
    end,
    concat_ws(' / ', nullif(ppd.purchase_plan_sn_list, ''), nullif(pod.purchase_order_sn_list, ''), nullif(rd.receipt_order_sn_list, ''), nullif(qd.qc_sn_list, ''), nullif(cfpd.fba_plan_sn_list, ''), nullif(hfpd.historical_fba_plan_sn_list, ''), nullif(fbsd.fba_shipment_id_list, ''), nullif(fbsd.fba_shipment_sn_list, ''), nullif(t.shipment_order_sn_list, '')),
    coalesce(t.latest_status, '')
from agg a
join latest_row l
  on l.country_category = a.country_category
 and l.seller_name_new = a.seller_name_new
 and l.seller_sku_adj = a.seller_sku_adj
left join dashboard_replenishment_tracking_snapshot t
  on t.snapshot_date = a.latest_replenishment_date
 and t.tracking_window_days = 30
 and t.country_category = a.country_category
and t.seller_name_new = a.seller_name_new
and t.seller_sku_adj = a.seller_sku_adj
left join active_fba_eta_doc eta
  on eta.country_category = a.country_category
 and eta.seller_name_new = a.seller_name_new
 and eta.seller_sku_adj = a.seller_sku_adj
left join purchase_plan_doc ppd
  on ppd.country_category = a.country_category
 and ppd.seller_name_new = a.seller_name_new
 and ppd.seller_sku_adj = a.seller_sku_adj
left join purchase_order_doc pod
  on pod.country_category = a.country_category
 and pod.seller_name_new = a.seller_name_new
 and pod.seller_sku_adj = a.seller_sku_adj
left join receipt_doc rd
  on rd.country_category = a.country_category
 and rd.seller_name_new = a.seller_name_new
 and rd.seller_sku_adj = a.seller_sku_adj
left join qc_doc qd
  on qd.country_category = a.country_category
 and qd.seller_name_new = a.seller_name_new
 and qd.seller_sku_adj = a.seller_sku_adj
left join current_fba_plan_doc cfpd
  on cfpd.country_category = a.country_category
 and cfpd.seller_name_new = a.seller_name_new
 and cfpd.seller_sku_adj = a.seller_sku_adj
left join current_fba_shipped_doc fbsd
  on fbsd.country_category = a.country_category
 and fbsd.seller_name_new = a.seller_name_new
 and fbsd.seller_sku_adj = a.seller_sku_adj
left join historical_fba_plan_doc hfpd
  on hfpd.country_category = a.country_category
 and hfpd.seller_name_new = a.seller_name_new
 and hfpd.seller_sku_adj = a.seller_sku_adj;
""".format(
    PRODUCT_CATEGORY_7D_SQL=PRODUCT_CATEGORY_7D_SQL,
    PRODUCT_CATEGORY_14D_SQL=PRODUCT_CATEGORY_14D_SQL,
    PRODUCT_CATEGORY_30D_SQL=PRODUCT_CATEGORY_30D_SQL,
    PRODUCT_CATEGORY_90D_SQL=PRODUCT_CATEGORY_90D_SQL,
)

UPDATE_QC_PASSED_NODE_SQL = """
update dashboard_replenishment_tracking_summary
set current_node = case
        when fba_plan_flag = 0 then '建FBA计划'
        when fba_shipped_flag = 0 then 'FBA出库'
        when fba_receiving_flag = 0 then 'FBA接收'
        when fba_closed_flag = 0 then 'FBA完成'
        else current_node
    end,
    breakpoint_node = case
        when fba_plan_flag = 0 then '建FBA计划'
        when fba_shipped_flag = 0 then 'FBA出库'
        when fba_receiving_flag = 0 then 'FBA接收'
        when fba_closed_flag = 0 then '链路完成'
        else breakpoint_node
    end,
    breakpoint_reason = case
        when fba_plan_flag = 0 then '质检已通过，但未确认创建FBA计划'
        when fba_shipped_flag = 0 then '已建FBA计划，但未确认出库在途'
        when fba_receiving_flag = 0 then 'FBA在途，未开始接收'
        when fba_closed_flag = 0 then 'FBA已接收，未确认完成'
        else breakpoint_reason
    end
where cutoff_date = %(cutoff_date)s
  and qc_passed_flag = 1;
"""

INSERT_LEVEL_HISTORY_SQL = """
insert into dashboard_replenishment_tracking_summary_level_history (
    cutoff_date, country_category, seller_name_new, seller_sku_adj,
    historical_replenishment_level, first_level_date, latest_level_date,
    level_appearance_days, is_current_level,
    purchase_plan_flag, purchase_plan_count, purchase_plan_qty, purchase_plan_sn_list,
    supplier_shipped_flag, purchase_order_count, shipped_order_count, purchase_inbound_qty,
    supplier_unshipped_order_count, supplier_unshipped_qty,
    purchase_order_sn_list, logistics_provider_list, logistics_order_list
)
with level_base as (
    select
        b.country_category,
        b.seller_name_new,
        b.seller_sku_adj,
        b.max_sku,
        b.support_replenish_level,
        b.support_replenish_level_sort,
        b.cur_date
    from dashboard_pur_plan_replenish_data b
    where b.cur_date <= %(cutoff_date)s
      and b.support_replenish_level_sort in (1, 2, 3)
),
level_agg as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        support_replenish_level,
        support_replenish_level_sort,
        min(cur_date) as first_level_date,
        max(cur_date) as latest_level_date,
        count(distinct cur_date) as level_appearance_days
    from level_base
    group by country_category, seller_name_new, seller_sku_adj, support_replenish_level, support_replenish_level_sort
),
purchase_plan_match as (
    select distinct
        p0.country_category,
        p0.seller_name_new,
        p0.seller_sku_adj,
        p0.support_replenish_level,
        pp0.plan_sn,
        p0.max_sku,
        pp0.sku,
        pp0.quantity_plan,
        pp0.plan_create_time
    from level_base p0
    join dashboard_tracking_purchase_plan_sync pp0
      on pp0.plan_create_time >= p0.cur_date
     and pp0.plan_create_time < date_add(date_add(p0.cur_date, interval 30 day), interval 1 day)
     and pp0.country_category = p0.country_category collate utf8mb4_unicode_ci
     and pp0.seller_name_norm = p0.seller_name_new collate utf8mb4_unicode_ci
     and pp0.msku = p0.seller_sku_adj collate utf8mb4_unicode_ci
),
purchase_order_match as (
    select distinct
        ppm.country_category,
        ppm.seller_name_new,
        ppm.seller_sku_adj,
        ppm.support_replenish_level,
        po.order_sn,
        po.quantity_real,
        po.quantity_plan,
        po.logistics_provider,
        po.logistics_order
    from purchase_plan_match ppm
    join dashboard_tracking_purchase_order_sync po
      on po.plan_sn = ppm.plan_sn collate utf8mb4_unicode_ci
     and po.status <> '作废'
     and case
        when replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(po.sku, ''), '-zu', ''), char_length(replace(coalesce(po.sku, ''), '-zu', '')) - 1)
        else replace(coalesce(po.sku, ''), '-zu', '')
     end = case
        when replace(coalesce(ppm.max_sku, ''), '-zu', '') regexp '[0-9][a-z]$'
            then left(replace(coalesce(ppm.max_sku, ''), '-zu', ''), char_length(replace(coalesce(ppm.max_sku, ''), '-zu', '')) - 1)
        else replace(coalesce(ppm.max_sku, ''), '-zu', '')
     end collate utf8mb4_unicode_ci
),
purchase_order_agg as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        support_replenish_level,
        count(distinct order_sn) as purchase_order_count,
        count(distinct case when nullif(logistics_provider, '') is not null or nullif(logistics_order, '') is not null then order_sn end) as shipped_order_count,
        sum(case when nullif(logistics_provider, '') is not null or nullif(logistics_order, '') is not null then coalesce(nullif(quantity_real, 0), quantity_plan, 0) else 0 end) as purchase_inbound_qty,
        count(distinct case when nullif(logistics_provider, '') is null and nullif(logistics_order, '') is null then order_sn end) as supplier_unshipped_order_count,
        sum(case when nullif(logistics_provider, '') is null and nullif(logistics_order, '') is null then coalesce(nullif(quantity_real, 0), quantity_plan, 0) else 0 end) as supplier_unshipped_qty,
        group_concat(distinct order_sn order by order_sn separator ',') as purchase_order_sn_list,
        group_concat(distinct nullif(logistics_provider, '') order by logistics_provider separator ',') as logistics_provider_list,
        group_concat(distinct nullif(logistics_order, '') order by logistics_order separator ',') as logistics_order_list
    from purchase_order_match
    group by country_category, seller_name_new, seller_sku_adj, support_replenish_level
),
purchase_plan_agg as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        support_replenish_level,
        count(distinct plan_sn) as purchase_plan_count,
        sum(coalesce(quantity_plan, 0)) as purchase_plan_qty,
        group_concat(distinct plan_sn order by plan_create_time separator ',') as purchase_plan_sn_list
    from purchase_plan_match
    group by country_category, seller_name_new, seller_sku_adj, support_replenish_level
)
select
    %(cutoff_date)s,
    la.country_category,
    la.seller_name_new,
    la.seller_sku_adj,
    la.support_replenish_level,
    la.first_level_date,
    la.latest_level_date,
    la.level_appearance_days,
    case when s.current_replenishment_level_sort = la.support_replenish_level_sort then 1 else 0 end,
    case when coalesce(ppa.purchase_plan_count, 0) > 0 then 1 else 0 end,
    coalesce(ppa.purchase_plan_count, 0),
    coalesce(ppa.purchase_plan_qty, 0),
    ppa.purchase_plan_sn_list,
    case when coalesce(poa.shipped_order_count, 0) > 0 then 1 else 0 end,
    coalesce(poa.purchase_order_count, 0),
    coalesce(poa.shipped_order_count, 0),
    coalesce(poa.purchase_inbound_qty, 0),
    case
        when coalesce(poa.purchase_order_count, 0) = 0 and coalesce(ppa.purchase_plan_count, 0) > 0 then coalesce(ppa.purchase_plan_count, 0)
        else coalesce(poa.supplier_unshipped_order_count, 0)
    end,
    case
        when coalesce(poa.purchase_order_count, 0) = 0 and coalesce(ppa.purchase_plan_count, 0) > 0 then coalesce(ppa.purchase_plan_qty, 0)
        else coalesce(poa.supplier_unshipped_qty, 0)
    end,
    poa.purchase_order_sn_list,
    poa.logistics_provider_list,
    poa.logistics_order_list
from level_agg la
join dashboard_replenishment_tracking_summary s
  on s.cutoff_date = %(cutoff_date)s
 and s.country_category = la.country_category collate utf8mb4_unicode_ci
 and s.seller_name_new = la.seller_name_new collate utf8mb4_unicode_ci
 and s.seller_sku_adj = la.seller_sku_adj collate utf8mb4_unicode_ci
left join purchase_plan_agg ppa
  on ppa.country_category = la.country_category collate utf8mb4_unicode_ci
 and ppa.seller_name_new = la.seller_name_new collate utf8mb4_unicode_ci
 and ppa.seller_sku_adj = la.seller_sku_adj collate utf8mb4_unicode_ci
 and ppa.support_replenish_level = la.support_replenish_level collate utf8mb4_unicode_ci
left join purchase_order_agg poa
  on poa.country_category = la.country_category collate utf8mb4_unicode_ci
 and poa.seller_name_new = la.seller_name_new collate utf8mb4_unicode_ci
 and poa.seller_sku_adj = la.seller_sku_adj collate utf8mb4_unicode_ci
 and poa.support_replenish_level = la.support_replenish_level collate utf8mb4_unicode_ci;
"""


def latest_replenishment_date(conn) -> date | None:
    with conn.cursor() as cursor:
        cursor.execute("select max(cur_date) as cutoff_date from dashboard_pur_plan_replenish_data")
        row = cursor.fetchone() or {}
    return row.get("cutoff_date")


def ensure_summary_columns(cursor) -> None:
    for statement in ENSURE_SUMMARY_COLUMNS_SQL:
        try:
            cursor.execute(statement)
        except Exception as exc:
            if not exc.args or exc.args[0] != 1060:
                raise


def ensure_level_history_columns(cursor) -> None:
    for statement in ENSURE_LEVEL_HISTORY_COLUMNS_SQL:
        try:
            cursor.execute(statement)
        except Exception as exc:
            if not exc.args or exc.args[0] != 1060:
                raise


def sync_purchase_orders(target_conn, source_conn, cutoff_date: date, batch_size: int = 1000) -> int:
    window_start = cutoff_date - timedelta(days=30)
    window_end_exclusive = cutoff_date + timedelta(days=31)
    params = {"window_start": window_start, "window_end_exclusive": window_end_exclusive}
    with target_conn.cursor() as cursor:
        cursor.execute(CREATE_PURCHASE_ORDER_SYNC_SQL)
    target_conn.commit()
    return copy_source_rows(
        source_conn,
        target_conn,
        SELECT_PURCHASE_ORDER_SYNC_SQL,
        DELETE_PURCHASE_ORDER_SYNC_SQL,
        "dashboard_tracking_purchase_order_sync",
        PURCHASE_ORDER_SYNC_COLUMNS,
        params,
        batch_size,
    )


def sync_receipt_orders(target_conn, source_conn, cutoff_date: date, batch_size: int = 1000) -> int:
    window_start = cutoff_date - timedelta(days=30)
    window_end_exclusive = cutoff_date + timedelta(days=31)
    params = {"window_start": window_start, "window_end_exclusive": window_end_exclusive}
    with target_conn.cursor() as cursor:
        cursor.execute(CREATE_RECEIPT_ORDER_SYNC_SQL)
    target_conn.commit()
    return copy_source_rows(
        source_conn,
        target_conn,
        SELECT_RECEIPT_ORDER_SYNC_SQL,
        DELETE_RECEIPT_ORDER_SYNC_SQL,
        "dashboard_tracking_receipt_order_sync",
        RECEIPT_ORDER_SYNC_COLUMNS,
        params,
        batch_size,
    )


def sync_qc_orders(target_conn, source_conn, cutoff_date: date, batch_size: int = 1000) -> int:
    window_start = cutoff_date - timedelta(days=30)
    window_end_exclusive = cutoff_date + timedelta(days=31)
    params = {"window_start": window_start, "window_end_exclusive": window_end_exclusive}
    with target_conn.cursor() as cursor:
        cursor.execute(CREATE_QC_ORDER_SYNC_SQL)
    target_conn.commit()
    return copy_source_rows(
        source_conn,
        target_conn,
        SELECT_QC_ORDER_SYNC_SQL,
        DELETE_QC_ORDER_SYNC_SQL,
        "dashboard_tracking_qc_order_sync",
        QC_ORDER_SYNC_COLUMNS,
        params,
        batch_size,
    )


def refresh_summary(conn, cutoff_date: date, source_conn=None) -> dict[str, int]:
    purchase_order_rows = sync_purchase_orders(conn, source_conn, cutoff_date) if source_conn else 0
    receipt_order_rows = sync_receipt_orders(conn, source_conn, cutoff_date) if source_conn else 0
    qc_order_rows = sync_qc_orders(conn, source_conn, cutoff_date) if source_conn else 0
    params = {"cutoff_date": cutoff_date}
    with conn.cursor() as cursor:
        cursor.execute(CREATE_SUMMARY_SQL)
        cursor.execute(CREATE_LEVEL_HISTORY_SQL)
        cursor.execute(CREATE_PURCHASE_ORDER_SYNC_SQL)
        cursor.execute(CREATE_RECEIPT_ORDER_SYNC_SQL)
        cursor.execute(CREATE_QC_ORDER_SYNC_SQL)
        ensure_summary_columns(cursor)
        ensure_level_history_columns(cursor)
        cursor.execute(DELETE_LEVEL_HISTORY_SQL, params)
        cursor.execute(DELETE_SUMMARY_SQL, params)
        cursor.execute(INSERT_SUMMARY_SQL, params)
        summary_rows = max(cursor.rowcount, 0)
        cursor.execute(UPDATE_QC_PASSED_NODE_SQL, params)
        cursor.execute(INSERT_LEVEL_HISTORY_SQL, params)
        level_history_rows = max(cursor.rowcount, 0)
    conn.commit()
    return {
        "summary_rows": summary_rows,
        "level_history_rows": level_history_rows,
        "purchase_order_rows": purchase_order_rows,
        "receipt_order_rows": receipt_order_rows,
        "qc_order_rows": qc_order_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh replenishment tracking summary tables.")
    parser.add_argument("--cutoff-date", default="", help="截止日期，默认使用最新补货日期")
    args = parser.parse_args()

    apply_database_ini_env()
    with connect_target() as conn, connect_source() as source_conn:
        selected_date = parse_day(args.cutoff_date) if args.cutoff_date else latest_replenishment_date(conn)
        if not selected_date:
            raise RuntimeError("没有可用的补货日期，无法刷新汇总表")
        started = datetime.now()
        result = refresh_summary(conn, selected_date, source_conn)
        elapsed = (datetime.now() - started).total_seconds()
    print(
        f"[success] cutoff_date={selected_date} "
        f"summary_rows={result['summary_rows']} "
        f"level_history_rows={result['level_history_rows']} "
        f"purchase_order_rows={result['purchase_order_rows']} "
        f"receipt_order_rows={result['receipt_order_rows']} "
        f"qc_order_rows={result['qc_order_rows']} "
        f"elapsed={elapsed:.2f}s"
    )


if __name__ == "__main__":
    main()
