from __future__ import annotations

import argparse
import configparser
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from etl.dashboard_daily_update import (
    CREATE_LOG_TABLE_SQL,
    CREATE_SCHEMA_SQL,
    SchemaConfig,
    SourceLoadStep,
    assert_source_select_only,
    build_schema_config,
    build_target_insert_sql,
    connect_source,
    connect_target,
    execute_source_load_step,
    log_task,
    parse_day,
    render_sql,
)
from etl.replenishment_sales_spike import (
    SpikeConfigurationError,
    refresh_replenishment_sales_spike_flags,
)


DEFAULT_CANDIDATE_DAYS = 1
DEFAULT_STEP_ORDER = [
    "listing_basic_sync",
    "self_asin_sync",
    "fba_shipment_sync",
    "order_profit_source_sync",
    "supplier_moq_sync",
    "check_daily_snapshots",
    "salable_days_stat",
    "replenishment_result",
    "moq_gating",
    "country_metrics",
]

REPLENISHMENT_WORK_TABLES = {
    "tmp_pur_plan_candidate_keys": "etl_datasync_test.dashboard_replenishment_work_candidate_keys_v3",
    "tmp_pur_plan_candidate_asins": "etl_datasync_test.dashboard_replenishment_work_candidate_asins_v3",
    "tmp_pur_plan_follow_listing_asins": "etl_datasync_test.dashboard_replenishment_work_follow_listing_asins_v3",
    "tmp_prod_perf_sku_asin_metrics": "etl_datasync_test.dashboard_replenishment_work_sku_asin_metrics_v3",
    "tmp_prod_perf_sku_metrics": "etl_datasync_test.dashboard_replenishment_work_sku_metrics_v3",
    "tmp_asin_origin_sales_fallback": "etl_datasync_test.dashboard_replenishment_work_asin_origin_sales_fallback_v3",
    "tmp_prod_perf_follow_origin": "etl_datasync_test.dashboard_replenishment_work_follow_origin_v3",
    "tmp_prod_perf_sku_follow_metrics": "etl_datasync_test.dashboard_replenishment_work_sku_follow_metrics_v3",
    "tmp_followed_origin_links": "etl_datasync_test.dashboard_replenishment_work_followed_origin_links_v3",
    "tmp_pur_plan_fba_current": "etl_datasync_test.dashboard_replenishment_work_fba_current_v3",
    "tmp_pur_plan_replenish_sug_current": "etl_datasync_test.dashboard_replenishment_work_restock_current_v3",
    "tmp_pur_plan_future_history_stat": "etl_datasync_test.dashboard_replenishment_work_future_history_stat_v3",
    "tmp_pur_plan_prev_history_stat": "etl_datasync_test.dashboard_replenishment_work_prev_history_stat_v3",
    "tmp_pur_plan_sales_change_rate": "etl_datasync_test.dashboard_replenishment_work_sales_change_rate_v3",
    "tmp_pur_plan_support_metric_base": "etl_datasync_test.dashboard_replenishment_work_support_metric_base_v3",
    "tmp_pur_plan_support_calc_base": "etl_datasync_test.dashboard_replenishment_work_support_calc_base_v3",
    "tmp_pur_plan_support_layer_all": "etl_datasync_test.dashboard_replenishment_work_support_layer_all_v3",
    "tmp_pur_plan_replenish_calc": "etl_datasync_test.dashboard_replenishment_work_replenish_calc_v3",
    "tmp_asin_merge_group_daily_base": "etl_datasync_test.dashboard_replenishment_work_asin_merge_group_daily_base_v1",
    "tmp_asin_merge_group_daily_parts": "etl_datasync_test.dashboard_replenishment_work_asin_merge_group_daily_parts_v1",
    "tmp_asin_merge_groups": "etl_datasync_test.dashboard_replenishment_work_asin_merge_groups_v3",
    "tmp_asin_merge_latest_performance": "etl_datasync_test.dashboard_replenishment_work_asin_latest_performance_v1",
    "tmp_asin_merge_targets": "etl_datasync_test.dashboard_replenishment_work_asin_merge_targets_v3",
    "tmp_asin_merge_assignments": "etl_datasync_test.dashboard_replenishment_work_asin_merge_assignments_v3",
    "tmp_asin_merge_purchase_fields": "etl_datasync_test.dashboard_replenishment_work_asin_merge_purchase_fields_v3",
    "tmp_replenishment_country_listing_price": "etl_datasync_test.dashboard_replenishment_work_country_listing_price_v3",
    "tmp_replenishment_moq_gate": "etl_datasync_test.dashboard_replenishment_work_moq_gate_v1",
}


@dataclass(frozen=True)
class ReplenishmentStep:
    name: str
    statements: tuple[str, ...]


CONFIG_ENV_MAP = {
    "target": {
        "host": "DASHBOARD_DB_HOST",
        "port": "DASHBOARD_DB_PORT",
        "user": "DASHBOARD_DB_USER",
        "password": "DASHBOARD_DB_PASSWORD",
        "database": "DASHBOARD_DB_NAME",
        "charset": "DASHBOARD_DB_CHARSET",
    },
    "source": {
        "host": "DASHBOARD_SOURCE_DB_HOST",
        "port": "DASHBOARD_SOURCE_DB_PORT",
        "user": "DASHBOARD_SOURCE_DB_USER",
        "password": "DASHBOARD_SOURCE_DB_PASSWORD",
        "database": "DASHBOARD_SOURCE_DB_NAME",
        "charset": "DASHBOARD_SOURCE_DB_CHARSET",
    },
}

SCHEMA_ENV_MAP = {
    "target_schema": "DASHBOARD_TARGET_SCHEMA",
    "etl_source_schema": "DASHBOARD_ETL_SOURCE_SCHEMA",
    "dwd_source_schema": "DASHBOARD_DWD_SOURCE_SCHEMA",
    "pricing_source_schema": "DASHBOARD_PRICING_SOURCE_SCHEMA",
}


def is_real_config_value(value: str | None) -> bool:
    if not value:
        return False
    upper_value = value.strip().upper()
    return not (
        upper_value.startswith("REMOTE_")
        or upper_value in {"YOUR_USER", "YOUR_PASSWORD", "CHANGE_ME"}
    )


def apply_database_ini_env(config_path: Path = Path("config/database.ini")) -> None:
    parser = configparser.ConfigParser()
    if not config_path.exists():
        return
    parser.read(config_path, encoding="utf-8")

    for section, option_map in CONFIG_ENV_MAP.items():
        if not parser.has_section(section):
            continue
        for option, env_name in option_map.items():
            value = parser[section].get(option)
            if is_real_config_value(value):
                os.environ.setdefault(env_name, value.strip())

    if parser.has_section("target"):
        target = parser["target"]
        target_schema = target.get("target_schema", "").strip() or target.get("database", "").strip()
        if is_real_config_value(target_schema):
            os.environ.setdefault("DASHBOARD_TARGET_SCHEMA", target_schema)

    if parser.has_section("schemas"):
        for option, env_name in SCHEMA_ENV_MAP.items():
            value = parser["schemas"].get(option)
            if is_real_config_value(value):
                os.environ.setdefault(env_name, value.strip())

    opt_lyt_fallbacks = {
        "DASHBOARD_SOURCE_DB_HOST": "OPT_LYT_DB_HOST",
        "DASHBOARD_SOURCE_DB_PORT": "OPT_LYT_DB_PORT",
        "DASHBOARD_SOURCE_DB_USER": "OPT_LYT_DB_USER",
        "DASHBOARD_SOURCE_DB_PASSWORD": "OPT_LYT_DB_PASSWORD",
    }
    for target_env, source_env in opt_lyt_fallbacks.items():
        if not os.getenv(target_env) and os.getenv(source_env):
            os.environ[target_env] = os.environ[source_env]


CREATE_SALABLE_DAYS_STAT_SQL = """
create table if not exists etl_datasync_test.pur_plan_prod_perf_salable_days_stat (
    sta_dt date not null,
    country_category varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_sku_adj varchar(128) not null,
    r_180d_salable_days int not null default 0,
    r_90d_salable_days int not null default 0,
    r_30d_salable_days int not null default 0,
    r_14d_salable_days int not null default 0,
    r_7d_salable_days int not null default 0,
    r_3d_salable_days int not null default 0,
    sales_30 decimal(18,4) not null default 0,
    available_total decimal(18,4) not null default 0,
    available_daily_sales_base decimal(18,6) null,
    available_salable_days decimal(18,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (sta_dt, country_category, seller_name_new, seller_sku_adj),
    key idx_salable_lookup (country_category, seller_name_new, seller_sku_adj),
    key idx_salable_days (sta_dt, available_salable_days)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_HISTORY_DAILY_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_history_daily_sync (
    dt_date date not null,
    country_category varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_sku_adj varchar(128) not null,
    day_volume decimal(18,4) not null default 0,
    afn_fulfillable_quantity decimal(18,4) not null default 0,
    synced_at datetime not null default current_timestamp,
    primary key (dt_date, country_category, seller_name_new, seller_sku_adj),
    key idx_repl_hist_lookup (country_category, seller_name_new, seller_sku_adj, dt_date)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_SELF_ASIN_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_self_asin_sync (
    seller_name_new varchar(128) not null,
    seller_brand varchar(128) not null,
    asin varchar(64) not null,
    synced_at datetime not null default current_timestamp,
    primary key (seller_name_new, seller_brand, asin),
    key idx_repl_self_asin_lookup (asin, seller_name_new)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_LISTING_BASIC_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_listing_basic_sync (
    country_category varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_sku varchar(128) not null,
    new_old_product varchar(64) null,
    max_fnsku varchar(128) null,
    max_asin varchar(64) null,
    max_sku varchar(128) null,
    marketplace_status text null,
    seller_name_concat text null,
    onsale_sites text null,
    unsale_sites text null,
    sales_status varchar(64) null,
    marketplace_concat varchar(128) null,
    global_tags text null,
    seller_name_copy varchar(255) null,
    seller_name_ue varchar(128) null,
    principal varchar(128) null,
    sales_team_1 varchar(128) null,
    max_local_name varchar(512) null,
    max_brand_name varchar(255) null,
    max_cg_box_pcs decimal(18,4) null,
    max_cg_delivery decimal(10,2) null,
    max_cg_price decimal(18,4) null,
    max_cg_transport_costs decimal(18,4) null,
    synced_at datetime not null default current_timestamp,
    primary key (country_category, seller_name_new, seller_sku),
    key idx_repl_listing_sku (seller_sku),
    key idx_repl_listing_owner (principal, sales_team_1)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_FBA_SHIPMENT_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_fba_shipment_sync (
    country_category varchar(64) not null,
    seller_name_new varchar(128) not null,
    msku varchar(128) not null,
    min_receiving_time datetime null,
    max_receiving_time datetime null,
    receiving_cnt int null,
    days_since_launch int null,
    days_latest_delivery int null,
    since_launch_range varchar(128) null,
    delivery_time_range varchar(128) null,
    synced_at datetime not null default current_timestamp,
    primary key (country_category, seller_name_new, msku),
    key idx_repl_fba_ship_msku (msku)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_ORDER_PROFIT_SOURCE_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_order_profit_source (
    seller_name_new varchar(100) not null,
    seller_sku_adj varchar(100) not null,
    country_category varchar(20) not null,
    best_country varchar(64) not null,
    order_cnt_20 int not null,
    final_profit_rate decimal(10,6) null,
    synced_at datetime not null default current_timestamp,
    primary key (seller_name_new, seller_sku_adj, country_category),
    key idx_repl_order_profit_country (country_category, best_country)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_SUPPLIER_MOQ_SYNC_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_supplier_moq_sync (
    snapshot_date date not null,
    sku varchar(500) not null,
    supplier_moq decimal(18,4) null,
    synced_at datetime not null default current_timestamp,
    primary key (snapshot_date, sku),
    key idx_repl_supplier_moq_sku (sku, snapshot_date)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_REPLENISHMENT_RESULT_SQL = """
create table if not exists etl_datasync_test.dashboard_pur_plan_replenish_data (
    cur_date date not null,
    new_old_product varchar(64) null,
    seller_sku_adj varchar(128) not null,
    max_fnsku varchar(128) null,
    max_asin varchar(64) null,
    max_sku varchar(128) null,
    marketplace_status text null,
    seller_name_concat text null,
    onsale_sites text null,
    unsale_sites text null,
    sales_status varchar(64) null,
    marketplace_concat varchar(128) null,
    global_tags text null,
    seller_name_copy varchar(255) null,
    seller_name_ue varchar(128) null,
    seller_name_new varchar(128) not null,
    country_category varchar(64) not null,
    max_local_name varchar(512) null,
    max_brand_name varchar(255) null,
    principal varchar(128) null,
    sales_team_1 varchar(128) null,
    max_receiving_time datetime null,
    receiving_cnt int null,
    max_cg_box_pcs decimal(18,4) null,
    max_cg_price decimal(18,4) null,
    max_cg_transport_costs decimal(18,4) null,
    purchase_lead_days_raw decimal(10,2) null,
    effective_purchase_lead_days decimal(10,2) not null default 0,
    purchase_lead_status varchar(32) not null default 'unconfigured',
    stockout_status varchar(64) null,
    pre_daily_avg_sales decimal(18,6) null,
    pre_normal_replenish_need_qty decimal(18,4) null,
    pre_replenish_trigger_qty decimal(18,4) null,
    hist_90d_instock_days int null,
    hist_90d_instock_sales decimal(18,4) null,
    hist_90d_instock_daily_sales decimal(18,6) null,
    history_recovery_need_qty decimal(18,4) null,
    history_recovery_flag tinyint not null default 0,
    support_inventory_qty decimal(18,4) null,
    inventory_support_days decimal(18,6) null,
    arrival_inventory_support_days decimal(18,6) null,
    arrival_inventory_qty decimal(18,4) null,
    lead_time_demand_qty decimal(18,4) null,
    base_replenish_need_qty decimal(18,4) null,
    lead_adjusted_replenish_need_qty decimal(18,4) null,
    lead_time_stockout_flag tinyint not null default 0,
    lead_time_stockout_days decimal(18,6) null,
    lead_time_lost_sales_qty decimal(18,4) null,
    support_replenish_level varchar(64) null,
    support_replenish_level_sort tinyint null,
    abcd_category varchar(16) null,
    gp_margin_range varchar(64) null,
    predict_abcd_category varchar(16) null,
    pre_1m_predict_abcd_category varchar(16) null,
    pre_1q_predict_abcd_category varchar(16) null,
    fba_local_quantity decimal(18,4) null,
    total decimal(18,4) null,
    available_total decimal(18,4) null,
    afn_fulfillable_quantity decimal(18,4) null,
    stock_up_num decimal(18,4) null,
    afn_unsellable_quantity decimal(18,4) null,
    sc_quantity_local_valid decimal(18,4) null,
    sc_quantity_purchase_shipping decimal(18,4) null,
    sc_quantity_purchase_plan decimal(18,4) null,
    sc_quantity_local_qc decimal(18,4) null,
    local_quantity decimal(18,4) null,
    r_180d_salable_days int null,
    r_90d_salable_days int null,
    r_30d_salable_days int null,
    r_14d_salable_days int null,
    r_7d_salable_days int null,
    r_3d_salable_days int null,
    sales_180d decimal(18,4) null,
    sales_90d decimal(18,4) null,
    final_sales_30d decimal(18,4) null,
    final_sales_14d decimal(18,4) null,
    final_sales_7d decimal(18,4) null,
    final_sales_3d decimal(18,4) null,
    amount_180d decimal(18,4) null,
    amount_90d decimal(18,4) null,
    amount_30d decimal(18,4) null,
    amount_14d decimal(18,4) null,
    amount_7d decimal(18,4) null,
    amount_3d decimal(18,4) null,
    pprofit_180d decimal(18,4) null,
    pprofit_90d decimal(18,4) null,
    pprofit_30d decimal(18,4) null,
    pprofit_14d decimal(18,4) null,
    pprofit_7d decimal(18,4) null,
    pprofit_3d decimal(18,4) null,
    pprofit_ratio_180d decimal(10,6) null,
    pprofit_ratio_90d decimal(10,6) null,
    pprofit_ratio_30d decimal(10,6) null,
    pprofit_ratio_14d decimal(10,6) null,
    pprofit_ratio_7d decimal(10,6) null,
    pprofit_ratio_3d decimal(10,6) null,
    gamount_30d decimal(18,4) null,
    gamount_14d decimal(18,4) null,
    gamount_7d decimal(18,4) null,
    gamount_3d decimal(18,4) null,
    gprofit_30d decimal(18,4) null,
    gprofit_14d decimal(18,4) null,
    gprofit_7d decimal(18,4) null,
    gprofit_3d decimal(18,4) null,
    gprofit_ratio_30d decimal(10,6) null,
    gprofit_ratio_14d decimal(10,6) null,
    gprofit_ratio_7d decimal(10,6) null,
    gprofit_ratio_3d decimal(10,6) null,
    new_old_prod_jg varchar(64) null,
    daily_avg_sales decimal(18,6) null,
    replenish_comp_months decimal(10,4) null,
    salable_days decimal(18,6) null,
    `60d_stocko_qty` decimal(18,4) null,
    `90d_stocko_qty` decimal(18,4) null,
    `180d_stocko_qty` decimal(18,4) null,
    replenish_dur_calc_stocko_qty decimal(18,4) null,
    replenish_need_qty decimal(18,4) null,
    replenish_trigger_qty decimal(18,4) null,
    sales_change_rate_adj decimal(10,6) null,
    sales_adj_factor decimal(10,6) null,
    final_profit_rate decimal(10,6) null,
    replenish_qty decimal(18,4) null,
    replenish_box_qty decimal(18,4) null,
    replenish_cost decimal(18,4) null,
    supplier_moq decimal(18,4) null,
    moq_status varchar(32) null,
    calculated_replenish_qty decimal(18,4) null,
    calculated_replenish_box_qty decimal(18,4) null,
    calculated_replenish_cost decimal(18,4) null,
    executable_replenish_qty decimal(18,4) null,
    executable_replenish_box_qty decimal(18,4) null,
    executable_replenish_cost decimal(18,4) null,
    moq_shortfall_qty decimal(18,4) null,
    amz_instock_sales_ratio decimal(18,6) null,
    instock_intrans_pur_sales_ratio decimal(18,6) null,
    fllow_flag tinyint null,
    followed_flag tinyint not null default 0,
    followed_by_count int not null default 0,
    followed_by_links text null,
    follow_origin_link varchar(255) null,
    replenish_block_reason varchar(64) null,
    asin_merge_flag tinyint not null default 0,
    asin_merge_target varchar(255) null,
    asin_merge_reason varchar(64) null,
    sales_spike_status varchar(32) not null default 'normal',
    sales_spike_flag tinyint not null default 0,
    sales_spike_date date null,
    sales_spike_qty decimal(18,4) null,
    sales_spike_baseline decimal(18,6) null,
    sales_spike_score decimal(18,6) null,
    sales_spike_reason varchar(500) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (cur_date, country_category, seller_name_new, seller_sku_adj),
    key idx_replenish_level (cur_date, support_replenish_level_sort, support_replenish_level),
    key idx_replenish_owner (cur_date, principal, sales_team_1),
    key idx_replenish_sku (seller_sku_adj),
    key idx_replenish_follow_origin (cur_date, follow_origin_link),
    key idx_replenish_qty (cur_date, replenish_qty)
) engine=InnoDB default charset=utf8mb4;
"""

CREATE_COUNTRY_METRICS_SQL = """
create table if not exists etl_datasync_test.dashboard_replenishment_country_metrics (
    snapshot_date date not null,
    period_days int not null,
    period_start date not null,
    period_end date not null,
    country_category varchar(64) not null,
    country varchar(64) not null,
    seller_name_new varchar(128) not null,
    seller_sku_adj varchar(128) not null,
    local_sku_list text null,
    listing_price decimal(18,4) null,
    sales_qty decimal(18,4) not null default 0,
    natural_daily_sales decimal(18,6) not null default 0,
    salable_days int not null default 0,
    salable_daily_sales decimal(18,6) null,
    sales_amount decimal(18,4) not null default 0,
    order_gross_profit decimal(18,4) not null default 0,
    order_gross_margin decimal(10,6) null,
    avg_ranking decimal(18,4) null,
    best_ranking decimal(18,4) null,
    worst_ranking decimal(18,4) null,
    sessions_total decimal(18,4) not null default 0,
    conversion_rate decimal(10,6) null,
    ad_spend decimal(18,4) not null default 0,
    ad_orders decimal(18,4) not null default 0,
    ad_sales decimal(18,4) not null default 0,
    ad_clicks decimal(18,4) not null default 0,
    ad_impressions decimal(18,4) not null default 0,
    acos decimal(10,6) null,
    ctr decimal(10,6) null,
    created_at datetime not null default current_timestamp,
    updated_at datetime not null default current_timestamp on update current_timestamp,
    primary key (snapshot_date, period_days, country_category, country, seller_name_new, seller_sku_adj),
    key idx_repl_country_parent (snapshot_date, period_days, country_category, seller_name_new, seller_sku_adj),
    key idx_repl_country_sales (snapshot_date, period_days, country_category, seller_name_new, sales_qty)
) engine=InnoDB default charset=utf8mb4;
"""

DDL_STATEMENTS = (
    CREATE_SCHEMA_SQL,
    CREATE_LOG_TABLE_SQL,
    CREATE_SALABLE_DAYS_STAT_SQL,
    CREATE_HISTORY_DAILY_SYNC_SQL,
    CREATE_SELF_ASIN_SYNC_SQL,
    CREATE_LISTING_BASIC_SYNC_SQL,
    CREATE_FBA_SHIPMENT_SYNC_SQL,
    CREATE_ORDER_PROFIT_SOURCE_SYNC_SQL,
    CREATE_SUPPLIER_MOQ_SYNC_SQL,
    CREATE_REPLENISHMENT_RESULT_SQL,
    CREATE_COUNTRY_METRICS_SQL,
)

LISTING_BASIC_COLUMNS = (
    "country_category",
    "seller_name_new",
    "seller_sku",
    "new_old_product",
    "max_fnsku",
    "max_asin",
    "max_sku",
    "marketplace_status",
    "seller_name_concat",
    "onsale_sites",
    "unsale_sites",
    "sales_status",
    "global_tags",
    "marketplace_concat",
    "seller_name_copy",
    "seller_name_ue",
    "principal",
    "sales_team_1",
    "max_local_name",
    "max_brand_name",
    "max_cg_box_pcs",
    "max_cg_delivery",
    "max_cg_price",
    "max_cg_transport_costs",
)

SUPPLIER_MOQ_COLUMNS = ("snapshot_date", "sku", "supplier_moq")

DELETE_SUPPLIER_MOQ_SYNC_SQL = """
delete from etl_datasync_test.dashboard_replenishment_supplier_moq_sync
where snapshot_date = %(snapshot_date)s
"""

SELECT_SUPPLIER_MOQ_SYNC_SQL = """
select
    %(snapshot_date)s as snapshot_date,
    sku,
    min(case when moq > 0 then moq end) as supplier_moq
from dwd_datasync.lx_product_local_product_info_GongYingShangBaoJia
where is_primary = '是'
  and sku is not null
  and sku <> ''
group by sku
"""

DELETE_LISTING_BASIC_SYNC_SQL = "delete from etl_datasync_test.dashboard_replenishment_listing_basic_sync;"

SELECT_LISTING_BASIC_SYNC_SQL = """
select
    country_category,
    seller_name_new,
    seller_sku,
    case
        when max(max_brand_name) regexp '2027|2026|2025' then '新品'
        else '老品'
    end as new_old_product,
    max(max_fnsku) as max_fnsku,
    max(max_asin) as max_asin,
    max(max_sku) as max_sku,
    group_concat(distinct concat(marketplace, ':', status) separator ',') as marketplace_status,
    group_concat(distinct seller_name separator ',') as seller_name_concat,
    max(onsale_sites) as onsale_sites,
    max(unsale_sites) as unsale_sites,
    case
        when max(onsale_sites) = 0 then '停售中'
        else '在售中'
    end as sales_status,
    group_concat(
        distinct case
            when nullif(global_tags, '') is not null then concat(marketplace, ':', global_tags)
            else null
        end
        order by marketplace
        separator ' | '
    ) as global_tags,
    '汇总' as marketplace_concat,
    case
        when country_category = '北美站' then concat(max(seller_name_ue), '-US')
        when country_category = '英国站' then concat(max(seller_name_ue), '-UK')
        else coalesce(max(inventory_seller_name_copy), concat(max(seller_name_ue), '-DE'))
    end as seller_name_copy,
    max(seller_name_ue) as seller_name_ue,
    max(principal) as principal,
    max(sales_team_1) as sales_team_1,
    max(max_local_name) as max_local_name,
    max(max_brand_name) as max_brand_name,
    max(max_cg_box_pcs) as max_cg_box_pcs,
    max(max_cg_delivery) as max_cg_delivery,
    max(max_cg_price) as max_cg_price,
    max(max_cg_transport_costs) as max_cg_transport_costs
from (
    select
        sml.seller_sku,
        sml.fnsku as max_fnsku,
        sml.asin as max_asin,
        sml.local_sku as max_sku,
        sml.marketplace,
        sml.status,
        sml.global_tags,
        sml.seller_name,
        count(case when sml.status = '在售' then 1 end)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as onsale_sites,
        count(case when sml.status = '停售' then 1 end)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as unsale_sites,
        sml.seller_name_ue,
        sml.seller_name_new,
        sml.country_category,
        sml.principal,
        sml.sales_team_1,
        inv_store.inventory_seller_name_copy,
        max(sml.local_name)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_local_name,
        max(plpi.brand_name)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_brand_name,
        max(plpi.cg_box_pcs)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_cg_box_pcs,
        max(lead_info.cg_delivery)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_cg_delivery,
        max(plpi.cg_price)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_cg_price,
        max(plpi.cg_transport_costs)
            over (partition by sml.country_category, sml.seller_name_new, sml.seller_sku) as max_cg_transport_costs
    from (
        select
            seller_sku,
            fnsku,
            asin,
            local_sku,
            local_name,
            marketplace,
            status,
            global_tags,
            seller_name,
            seller_name_ue,
            seller_name_new,
            country_category,
            principal,
            sales_team_1
        from etl_datasync.etl_dispose_lx_sales_mws_listing
        union all
        select
            raw.seller_sku,
            raw.fnsku,
            raw.asin,
            raw.local_sku,
            null as local_name,
            raw.marketplace,
            raw.status,
            raw.global_tags,
            raw.seller_name,
            substring_index(raw.seller_name, '-', 1) as seller_name_ue,
            substring_index(raw.seller_name, '-', 1) as seller_name_new,
            case
                when upper(raw.marketplace) in ('US', 'CA', 'MX', 'BR')
                  or raw.marketplace in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
                when upper(raw.marketplace) in ('UK', 'GB')
                  or raw.marketplace = '英国' then '英国站'
                else '欧洲站'
            end as country_category,
            null as principal,
            null as sales_team_1
        from dwd_datasync.lx_sales_mws_listing raw
        where raw.seller_sku is not null
          and raw.seller_sku <> ''
          and raw.asin is not null
          and raw.asin <> ''
    ) as sml
    left join etl_datasync.etl_dispose_lx_product_local_product_info as plpi
           on sml.seller_sku = plpi.seller_sku
          and sml.marketplace = plpi.country
          and sml.seller_name_new = plpi.seller_name_new
    left join dwd_datasync.lx_product_local_product_info as lead_info
           on binary sml.local_sku = binary lead_info.sku
    left join (
        select
            sku,
            msku,
            substring_index(store_name, '-', 1) as seller_name_new,
            substring_index(
                group_concat(
                    distinct store_name
                    order by
                        case when upper(substring_index(store_name, '-', -1)) = 'DE' then 0 else 1 end,
                        store_name
                    separator ','
                ),
                ',',
                1
            ) as inventory_seller_name_copy
        from dwd_datasync.lx_storage_inventory_details
        where nullif(sku, '') is not null
          and nullif(msku, '') is not null
          and nullif(store_name, '') is not null
        group by sku, msku, substring_index(store_name, '-', 1)
    ) inv_store
           on inv_store.sku = sml.local_sku
          and inv_store.msku = sml.seller_sku
          and inv_store.seller_name_new = sml.seller_name_new
) listing_basic
group by country_category, seller_name_new, seller_sku
"""

SELF_ASIN_COLUMNS = (
    "seller_name_new",
    "seller_brand",
    "asin",
)

DELETE_SELF_ASIN_SYNC_SQL = "delete from etl_datasync_test.dashboard_replenishment_self_asin_sync;"

SELECT_SELF_ASIN_SYNC_SQL = """
select distinct
    store.`店铺名` as seller_name_new,
    store.`品牌名` as seller_brand,
    list.asin
from dwd_datasync.lx_sales_mws_listing list
left join opt_db.store_brand_relation store
       on store.`店铺名` = substring_index(list.seller_name, '-', 1)
      and store.`品牌名` = list.seller_brand
where store.`店铺名` is not null
  and list.asin is not null
  and list.asin <> ''
"""

FBA_SHIPMENT_COLUMNS = (
    "country_category",
    "seller_name_new",
    "msku",
    "min_receiving_time",
    "max_receiving_time",
    "receiving_cnt",
    "days_since_launch",
    "days_latest_delivery",
    "since_launch_range",
    "delivery_time_range",
)

DELETE_FBA_SHIPMENT_SYNC_SQL = "delete from etl_datasync_test.dashboard_replenishment_fba_shipment_sync;"

SELECT_FBA_SHIPMENT_SYNC_SQL = """
select
    country_category,
    seller_name_new,
    msku,
    min_receiving_time,
    max_receiving_time,
    receiving_cnt,
    days_since_launch,
    days_latest_delivery,
    since_launch_range,
    delivery_time_range
from (
    select
        b.*,
        datediff(current_date, min_receiving_time) as days_since_launch,
        datediff(current_date, max_receiving_time) as days_latest_delivery,
        case
            when datediff(current_date, min_receiving_time) between 0 and 30 then '<=30天'
            when datediff(current_date, min_receiving_time) between 31 and 90 then '<=90天'
            when datediff(current_date, min_receiving_time) between 91 and 180 then '<=180'
            when datediff(current_date, min_receiving_time) > 180 then '>180天'
        end as since_launch_range,
        case
            when datediff(current_date, max_receiving_time) between 0 and 7 then '0-7天'
            when datediff(current_date, max_receiving_time) between 8 and 14 then '8-14天'
            when datediff(current_date, max_receiving_time) between 15 and 30 then '15-30天'
            when datediff(current_date, max_receiving_time) >= 30 then '>=30天'
        end as delivery_time_range
    from (
        select
            msku,
            seller_name_new,
            country_category,
            min(str_to_date(receiving_time, '%%Y-%%m-%%d %%H:%%i:%%s')) as min_receiving_time,
            max(str_to_date(receiving_time, '%%Y-%%m-%%d %%H:%%i:%%s')) as max_receiving_time,
            max(receiving_cnt) as receiving_cnt
        from (
            select
                f.country_category,
                f.store_name,
                f.seller_name_new,
                f.msku,
                case
                    when f.receiving_time = '' then null
                    else f.receiving_time
                end as receiving_time,
                r.receiving_cnt
            from etl_datasync.etl_dispose_lx_fba_shipment as f
            left join (
                select
                    msku,
                    store_name,
                    count(*) as receiving_cnt
                from etl_datasync.etl_dispose_lx_fba_shipment
                where receiving_time is not null
                  and quantity_shipped <> 0
                group by msku, store_name
            ) as r
              on f.msku = r.msku
             and f.store_name = r.store_name
            where f.receiving_time is not null
              and f.quantity_received <> 0
        ) as a
        group by msku, seller_name_new, country_category
    ) as b
) as shipment_basic
where msku is not null
  and msku <> ''
  and seller_name_new is not null
  and country_category is not null
"""

ORDER_PROFIT_SOURCE_COLUMNS = (
    "seller_name_new",
    "seller_sku_adj",
    "country_category",
    "best_country",
    "order_cnt_20",
    "final_profit_rate",
)

DELETE_ORDER_PROFIT_SOURCE_SYNC_SQL = (
    "delete from etl_datasync_test.dashboard_replenishment_order_profit_source;"
)

SELECT_ORDER_PROFIT_SOURCE_SYNC_SQL = """
with order_base as (
    select
        create_time,
        country,
        amazon_order_id,
        cast(
            case
                when locate('-', seller_name) > 0
                    then left(seller_name, locate('-', seller_name) - 1)
                else seller_name
            end as char(100)
        ) as seller_name_new,
        cast(
            if(
                length(substring_index(seller_sku, ',', 1)) > 16,
                replace(
                    substring_index(substring_index(seller_sku, ',', 1), '-', 1),
                    'amzn.gr.',
                    ''
                ),
                substring_index(seller_sku, ',', 1)
            ) as char(100)
        ) as seller_sku_adj,
        cast(
            case
                when country = '英国' then '英国站'
                when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'
                else '欧洲站'
            end as char(20)
        ) as country_category,
        sales_price_amount,
        profit
    from dwd_datasync.lx_sales_mws_orders_detail
    where create_time >= date_sub(%(biz_date)s, interval 90 day)
      and create_time < date_add(%(biz_date)s, interval 1 day)
      and nullif(seller_name, '') is not null
      and nullif(seller_sku, '') is not null
      and nullif(country, '') is not null
),
recent_five_ranked as (
    select
        order_base.*,
        row_number() over (
            partition by seller_name_new, seller_sku_adj, country_category, country
            order by create_time desc, amazon_order_id desc
        ) as rn_5
    from order_base
),
country_metrics as (
    select
        seller_name_new,
        seller_sku_adj,
        country_category,
        country,
        count(*) as order_cnt_5,
        sum(sales_price_amount) as sales_price_amount_5,
        sum(profit) as profit_5,
        sum(profit) / sum(sales_price_amount) as profit_rate_5
    from recent_five_ranked
    where rn_5 <= 5
    group by seller_name_new, seller_sku_adj, country_category, country
    having count(*) = 5
       and sum(sales_price_amount) <> 0
),
selected_country as (
    select
        seller_name_new,
        seller_sku_adj,
        country_category,
        country as best_country
    from (
        select
            country_metrics.*,
            row_number() over (
                partition by seller_name_new, seller_sku_adj, country_category
                order by profit_rate_5 desc, sales_price_amount_5 desc, profit_5 desc, country
            ) as country_rank
        from country_metrics
    ) ranked_countries
    where country_rank = 1
),
recent_twenty_ranked as (
    select
        order_base.*,
        selected_country.best_country,
        row_number() over (
            partition by order_base.seller_name_new, order_base.seller_sku_adj,
                         order_base.country_category
            order by order_base.create_time desc, order_base.amazon_order_id desc
        ) as rn_20
    from order_base
    inner join selected_country
            on order_base.seller_name_new = selected_country.seller_name_new
           and order_base.seller_sku_adj = selected_country.seller_sku_adj
           and order_base.country_category = selected_country.country_category
           and order_base.country = selected_country.best_country
)
select
    seller_name_new,
    seller_sku_adj,
    country_category,
    best_country,
    count(*) as order_cnt_20,
    round(sum(profit) / sum(sales_price_amount), 2) as final_profit_rate
from recent_twenty_ranked
where rn_20 <= 20
group by seller_name_new, seller_sku_adj, country_category, best_country
having sum(sales_price_amount) <> 0
"""

HISTORY_DAILY_COLUMNS = (
    "dt_date",
    "country_category",
    "seller_name_new",
    "seller_sku_adj",
    "day_volume",
    "afn_fulfillable_quantity",
)

HISTORY_SOURCE_TABLES = {
    2024: "etl_datasync.etl_dispose_lx_statistics_product_performance_2024",
    2025: "etl_datasync.etl_dispose_lx_statistics_product_performance_2025",
    2026: "etl_datasync.etl_dispose_lx_statistics_product_performance_2026",
}

DELETE_HISTORY_DAILY_SYNC_SQL = "delete from etl_datasync_test.dashboard_replenishment_history_daily_sync;"

SELECT_HISTORY_DAILY_SYNC_SQL = """
select
    start_date as dt_date,
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(coalesce(volume, 0)) as day_volume,
    max(afn_fulfillable_quantity) as afn_fulfillable_quantity
from {history_source_table}
where start_date between %(history_start_date)s and %(history_end_date)s
group by start_date, country_category, seller_name_new, seller_sku_adj
"""

CHECK_DAILY_SNAPSHOTS_SQL = """
select
    (select count(*)
     from etl_datasync_test.dashboard_inventory_daily_snapshot
     where snapshot_date = %(snapshot_date)s) as inventory_rows,
    (select count(*)
     from etl_datasync_test.dashboard_restock_daily_snapshot
     where snapshot_date = %(snapshot_date)s) as restock_rows;
"""

DELETE_SALABLE_DAYS_SQL = """
delete from etl_datasync_test.pur_plan_prod_perf_salable_days_stat
where sta_dt = %(biz_date)s;
"""

INSERT_SALABLE_DAYS_SQL = """
insert into etl_datasync_test.pur_plan_prod_perf_salable_days_stat (
    sta_dt,
    country_category,
    seller_name_new,
    seller_sku_adj,
    r_180d_salable_days,
    r_90d_salable_days,
    r_30d_salable_days,
    r_14d_salable_days,
    r_7d_salable_days,
    r_3d_salable_days,
    sales_30,
    available_total,
    available_daily_sales_base,
    available_salable_days
)
with candidate_keys as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj
    from etl_datasync_test.dashboard_product_performance_daily
    where dt_date between %(candidate_start_date)s and %(biz_date)s
      and seller_sku_adj is not null
      and seller_sku_adj <> ''
    group by country_category, seller_name_new, seller_sku_adj
),
product_daily as (
    select
        p.dt_date,
        p.country_category,
        p.seller_name_new,
        p.seller_sku_adj,
        sum(coalesce(p.sales_qty, 0)) as sales_qty,
        max(coalesce(p.afn_fulfillable_quantity, 0)) as afn_fulfillable_quantity
    from etl_datasync_test.dashboard_product_performance_daily p
    inner join candidate_keys c
            on p.country_category = c.country_category
           and p.seller_name_new = c.seller_name_new
           and p.seller_sku_adj = c.seller_sku_adj
    where p.dt_date between %(product_start_date)s and %(biz_date)s
    group by
        p.dt_date,
        p.country_category,
        p.seller_name_new,
        p.seller_sku_adj
),
salable as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 179 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_180d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 89 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_90d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_30d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 13 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_14d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 6 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_7d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 2 day)
                  and afn_fulfillable_quantity > 0 then 1 else 0 end) as r_3d_salable_days,
        sum(case when dt_date >= date_sub(%(biz_date)s, interval 29 day)
                  then sales_qty else 0 end) as sales_30
    from product_daily
    group by country_category, seller_name_new, seller_sku_adj
),
inventory_current as (
    select
        country_category,
        seller_name_new,
        seller_sku_adj,
        sum(coalesce(available_total, 0)) as available_total
    from etl_datasync_test.dashboard_inventory_daily_snapshot
    where snapshot_date = %(snapshot_date)s
    group by country_category, seller_name_new, seller_sku_adj
)
select
    %(biz_date)s as sta_dt,
    s.country_category,
    s.seller_name_new,
    s.seller_sku_adj,
    coalesce(s.r_180d_salable_days, 0) as r_180d_salable_days,
    coalesce(s.r_90d_salable_days, 0) as r_90d_salable_days,
    coalesce(s.r_30d_salable_days, 0) as r_30d_salable_days,
    coalesce(s.r_14d_salable_days, 0) as r_14d_salable_days,
    coalesce(s.r_7d_salable_days, 0) as r_7d_salable_days,
    coalesce(s.r_3d_salable_days, 0) as r_3d_salable_days,
    coalesce(s.sales_30, 0) as sales_30,
    coalesce(i.available_total, 0) as available_total,
    coalesce(s.sales_30, 0) / nullif(s.r_30d_salable_days, 0) as available_daily_sales_base,
    case
        when coalesce(i.available_total, 0) = 0 then 0
        else coalesce(i.available_total, 0)
             / nullif(coalesce(s.sales_30, 0) / nullif(s.r_30d_salable_days, 0), 0)
    end as available_salable_days
from salable s
left join inventory_current i
       on s.country_category = i.country_category
      and s.seller_name_new = i.seller_name_new
      and s.seller_sku_adj = i.seller_sku_adj;
"""

REPLENISHMENT_RESULT_SQL = """
delete from etl_datasync_test.dashboard_pur_plan_replenish_data
where cur_date = %(snapshot_date)s;

drop temporary table if exists tmp_pur_plan_candidate_keys;
create temporary table tmp_pur_plan_candidate_keys as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    max(local_sku) as max_sku,
    group_concat(distinct seller_name separator ',') as seller_name_concat
from etl_datasync_test.dashboard_product_performance_daily
where dt_date between %(candidate_start_date)s and %(biz_date)s
  and seller_sku_adj is not null
  and seller_sku_adj <> ''
group by country_category, seller_name_new, seller_sku_adj;

drop temporary table if exists tmp_pur_plan_candidate_asins;
create temporary table tmp_pur_plan_candidate_asins as
select distinct
    candidate.country_category,
    listing.max_asin
from tmp_pur_plan_candidate_keys candidate
inner join etl_datasync_test.dashboard_replenishment_listing_basic_sync listing
        on candidate.country_category = listing.country_category
       and candidate.seller_name_new = listing.seller_name_new
       and candidate.seller_sku_adj = listing.seller_sku
where listing.max_asin is not null
  and listing.max_asin <> '';

drop temporary table if exists tmp_pur_plan_follow_listing_asins;
create temporary table tmp_pur_plan_follow_listing_asins as
select
    candidate_asin.country_category,
    candidate_asin.max_asin
from tmp_pur_plan_candidate_asins candidate_asin
inner join etl_datasync_test.dashboard_replenishment_listing_basic_sync listing
        on candidate_asin.country_category = listing.country_category
       and candidate_asin.max_asin = listing.max_asin
left join etl_datasync_test.dashboard_replenishment_self_asin_sync self_asin
       on listing.seller_name_new = self_asin.seller_name_new
      and listing.max_asin = self_asin.asin
group by candidate_asin.country_category, candidate_asin.max_asin
having count(distinct concat(listing.seller_name_new, '\0', listing.seller_sku)) > 1
   and max(case when self_asin.asin is not null then 1 else 0 end) > 0
   and max(case when self_asin.asin is null then 1 else 0 end) > 0;

insert into tmp_pur_plan_candidate_keys (
    country_category,
    seller_name_new,
    seller_sku_adj,
    max_sku,
    seller_name_concat
)
select
    listing.country_category,
    listing.seller_name_new,
    listing.seller_sku as seller_sku_adj,
    coalesce(nullif(max(listing.max_sku), ''), listing.seller_sku) as max_sku,
    max(listing.seller_name_concat) as seller_name_concat
from etl_datasync_test.dashboard_replenishment_listing_basic_sync listing
inner join tmp_pur_plan_follow_listing_asins follow_asin
        on listing.country_category = follow_asin.country_category
       and listing.max_asin = follow_asin.max_asin
left join tmp_pur_plan_candidate_keys existing
       on listing.country_category = existing.country_category
      and listing.seller_name_new = existing.seller_name_new
      and listing.seller_sku = existing.seller_sku_adj
left join etl_datasync_test.dashboard_replenishment_self_asin_sync listing_self
       on listing.seller_name_new = listing_self.seller_name_new
      and listing.max_asin = listing_self.asin
where existing.seller_sku_adj is null
  and listing_self.asin is null
  and listing.seller_sku is not null
  and listing.seller_sku <> ''
  and listing.seller_sku not like 'amzn.%%'
group by listing.country_category, listing.seller_name_new, listing.seller_sku;

drop temporary table if exists tmp_prod_perf_sku_metrics;
drop temporary table if exists tmp_prod_perf_sku_asin_metrics;
create temporary table tmp_prod_perf_sku_asin_metrics as
select
    p.country_category,
    p.seller_name_new,
    p.seller_sku_adj,
    max(l.max_asin) as asin,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 179 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_180,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 89 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_90,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_30,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 13 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_14,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 6 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_7,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 2 day) then coalesce(p.sales_qty, 0) else 0 end) as sales_3,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 179 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_180,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 89 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_90,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_30,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 13 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_14,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 6 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_7,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 2 day) then coalesce(p.sales_amount, 0) else 0 end) as amount_3,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 179 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_180,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 89 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_90,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 29 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_30,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 13 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_14,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 6 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_7,
    sum(case when p.dt_date >= date_sub(%(biz_date)s, interval 2 day) then coalesce(p.order_gross_profit, 0) else 0 end) as pprofit_3
from etl_datasync_test.dashboard_product_performance_daily p
inner join tmp_pur_plan_candidate_keys c
        on p.country_category = c.country_category
       and p.seller_name_new = c.seller_name_new
       and p.seller_sku_adj = c.seller_sku_adj
left join etl_datasync_test.dashboard_replenishment_listing_basic_sync l
       on p.country_category = l.country_category
      and p.seller_name_new = l.seller_name_new
      and p.seller_sku_adj = l.seller_sku
where p.dt_date between %(product_start_date)s and %(biz_date)s
group by p.country_category, p.seller_name_new, p.seller_sku_adj;

create temporary table tmp_prod_perf_sku_metrics as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(sales_180) as sales_180,
    sum(sales_90) as sales_90,
    sum(sales_30) as sales_30,
    sum(sales_14) as sales_14,
    sum(sales_7) as sales_7,
    sum(sales_3) as sales_3,
    sum(amount_180) as amount_180,
    sum(amount_90) as amount_90,
    sum(amount_30) as amount_30,
    sum(amount_14) as amount_14,
    sum(amount_7) as amount_7,
    sum(amount_3) as amount_3,
    sum(pprofit_180) as pprofit_180,
    sum(pprofit_90) as pprofit_90,
    sum(pprofit_30) as pprofit_30,
    sum(pprofit_14) as pprofit_14,
    sum(pprofit_7) as pprofit_7,
    sum(pprofit_3) as pprofit_3
from tmp_prod_perf_sku_asin_metrics
group by country_category, seller_name_new, seller_sku_adj;

drop temporary table if exists tmp_asin_origin_sales_fallback;
create temporary table tmp_asin_origin_sales_fallback as
select
    ranked.country_category,
    ranked.asin,
    ranked.seller_name_new as origin_seller_name_new,
    ranked.seller_sku_adj as origin_seller_sku_adj,
    ranked.sales_3,
    ranked.sales_7,
    ranked.sales_14,
    ranked.sales_30,
    ranked.origin_r_3d_salable_days,
    ranked.origin_r_7d_salable_days,
    ranked.origin_r_14d_salable_days,
    ranked.origin_r_30d_salable_days,
    ranked.origin_max_sku,
    ranked.origin_max_fnsku,
    ranked.origin_new_old_product,
    ranked.origin_marketplace_status,
    ranked.origin_seller_name_concat,
    ranked.origin_onsale_sites,
    ranked.origin_unsale_sites,
    ranked.origin_sales_status,
    ranked.origin_marketplace_concat,
    ranked.origin_global_tags,
    ranked.origin_seller_name_copy,
    ranked.origin_seller_name_ue,
    ranked.origin_max_local_name,
    ranked.origin_max_brand_name,
    ranked.origin_principal,
    ranked.origin_sales_team_1
from (
    select
        origin.country_category,
        origin.asin,
        origin.seller_name_new,
        origin.seller_sku_adj,
        coalesce(metrics.sales_3, 0) as sales_3,
        coalesce(metrics.sales_7, 0) as sales_7,
        coalesce(metrics.sales_14, 0) as sales_14,
        coalesce(metrics.sales_30, 0) as sales_30,
        coalesce(origin_ks.r_3d_salable_days, 0) as origin_r_3d_salable_days,
        coalesce(origin_ks.r_7d_salable_days, 0) as origin_r_7d_salable_days,
        coalesce(origin_ks.r_14d_salable_days, 0) as origin_r_14d_salable_days,
        coalesce(origin_ks.r_30d_salable_days, 0) as origin_r_30d_salable_days,
        origin_listing.max_sku as origin_max_sku,
        origin_listing.max_fnsku as origin_max_fnsku,
        origin_listing.new_old_product as origin_new_old_product,
        origin_listing.marketplace_status as origin_marketplace_status,
        origin_listing.seller_name_concat as origin_seller_name_concat,
        origin_listing.onsale_sites as origin_onsale_sites,
        origin_listing.unsale_sites as origin_unsale_sites,
        origin_listing.sales_status as origin_sales_status,
        origin_listing.marketplace_concat as origin_marketplace_concat,
        origin_listing.global_tags as origin_global_tags,
        origin_listing.seller_name_copy as origin_seller_name_copy,
        origin_listing.seller_name_ue as origin_seller_name_ue,
        origin_listing.max_local_name as origin_max_local_name,
        origin_listing.max_brand_name as origin_max_brand_name,
        origin_listing.principal as origin_principal,
        origin_listing.sales_team_1 as origin_sales_team_1,
        row_number() over (
            partition by origin.country_category, origin.asin
            order by
                case when self_asin.asin is not null then 0 else 1 end,
                coalesce(metrics.sales_30, 0) desc,
                coalesce(metrics.sales_14, 0) desc,
                coalesce(metrics.sales_7, 0) desc,
                coalesce(metrics.sales_3, 0) desc,
                origin.seller_name_new,
                origin.seller_sku_adj
        ) as rn
    from tmp_prod_perf_sku_asin_metrics origin
    left join etl_datasync_test.dashboard_replenishment_self_asin_sync self_asin
           on origin.seller_name_new = self_asin.seller_name_new
          and origin.asin = self_asin.asin
    left join tmp_prod_perf_sku_metrics metrics
           on origin.country_category = metrics.country_category
          and origin.seller_name_new = metrics.seller_name_new
          and origin.seller_sku_adj = metrics.seller_sku_adj
    left join etl_datasync_test.pur_plan_prod_perf_salable_days_stat origin_ks
           on origin_ks.sta_dt = %(biz_date)s
          and origin.country_category = origin_ks.country_category
          and origin.seller_name_new = origin_ks.seller_name_new
          and origin.seller_sku_adj = origin_ks.seller_sku_adj
    left join etl_datasync_test.dashboard_replenishment_listing_basic_sync origin_listing
           on origin.country_category = origin_listing.country_category
          and origin.seller_name_new = origin_listing.seller_name_new
          and origin.seller_sku_adj = origin_listing.seller_sku
    where origin.asin is not null
      and origin.asin <> ''
) ranked
where ranked.rn = 1;

drop temporary table if exists tmp_prod_perf_follow_origin;
create temporary table tmp_prod_perf_follow_origin as
select
    bridge.country_category,
    bridge.seller_name_new,
    bridge.seller_sku_adj,
    max(case
        when self_asin.asin is not null
          or fallback.origin_seller_sku_adj is null
          or (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
          )
            then 1
        else 0
    end) as fllow_flag,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.sales_3
        else null
    end) as origin_sales_3,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.sales_7
        else null
    end) as origin_sales_7,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.sales_14
        else null
    end) as origin_sales_14,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.sales_30
        else null
    end) as origin_sales_30,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.origin_r_3d_salable_days
        else null
    end) as origin_r_3d_salable_days,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.origin_r_7d_salable_days
        else null
    end) as origin_r_7d_salable_days,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.origin_r_14d_salable_days
        else null
    end) as origin_r_14d_salable_days,
    max(case
        when self_asin.asin is null
         and not (
                bridge.seller_name_new = fallback.origin_seller_name_new
            and bridge.seller_sku_adj = fallback.origin_seller_sku_adj
         )
            then fallback.origin_r_30d_salable_days
        else null
    end) as origin_r_30d_salable_days,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_seller_name_new else null end) as origin_seller_name_new,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_seller_sku_adj else null end) as origin_seller_sku_adj,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_max_sku else null end) as origin_max_sku,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_max_fnsku else null end) as origin_max_fnsku,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_new_old_product else null end) as origin_new_old_product,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_marketplace_status else null end) as origin_marketplace_status,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_seller_name_concat else null end) as origin_seller_name_concat,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_onsale_sites else null end) as origin_onsale_sites,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_unsale_sites else null end) as origin_unsale_sites,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_sales_status else null end) as origin_sales_status,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_marketplace_concat else null end) as origin_marketplace_concat,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_global_tags else null end) as origin_global_tags,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_seller_name_copy else null end) as origin_seller_name_copy,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_seller_name_ue else null end) as origin_seller_name_ue,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_max_local_name else null end) as origin_max_local_name,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_max_brand_name else null end) as origin_max_brand_name,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_principal else null end) as origin_principal,
    max(case when self_asin.asin is null and not (bridge.seller_name_new = fallback.origin_seller_name_new and bridge.seller_sku_adj = fallback.origin_seller_sku_adj) then fallback.origin_sales_team_1 else null end) as origin_sales_team_1
from tmp_prod_perf_sku_asin_metrics bridge
left join etl_datasync_test.dashboard_replenishment_self_asin_sync self_asin
       on bridge.seller_name_new = self_asin.seller_name_new
      and bridge.asin = self_asin.asin
left join tmp_asin_origin_sales_fallback fallback
       on fallback.country_category = bridge.country_category
      and fallback.asin = bridge.asin
group by bridge.country_category, bridge.seller_name_new, bridge.seller_sku_adj;

drop temporary table if exists tmp_prod_perf_sku_follow_metrics;
create temporary table tmp_prod_perf_sku_follow_metrics as
select
    m.country_category,
    m.seller_name_new,
    m.seller_sku_adj,
    coalesce(fo.fllow_flag, 1) as fllow_flag,
    m.sales_180,
    m.sales_90,
    case
        when coalesce(fo.fllow_flag, 1) = 1 then coalesce(m.sales_30, 0)
        else coalesce(m.sales_30, 0) + coalesce(fo.origin_sales_30, 0)
    end as sales_30,
    case
        when coalesce(fo.fllow_flag, 1) = 1 then coalesce(m.sales_14, 0)
        else coalesce(m.sales_14, 0) + coalesce(fo.origin_sales_14, 0)
    end as sales_14,
    case
        when coalesce(fo.fllow_flag, 1) = 1 then coalesce(m.sales_7, 0)
        else coalesce(m.sales_7, 0) + coalesce(fo.origin_sales_7, 0)
    end as sales_7,
    case
        when coalesce(fo.fllow_flag, 1) = 1 then coalesce(m.sales_3, 0)
        else coalesce(m.sales_3, 0) + coalesce(fo.origin_sales_3, 0)
    end as sales_3,
    m.amount_180,
    m.amount_90,
    m.amount_30,
    m.amount_14,
    m.amount_7,
    m.amount_3,
    m.pprofit_180,
    m.pprofit_90,
    m.pprofit_30,
    m.pprofit_14,
    m.pprofit_7,
    m.pprofit_3,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_r_30d_salable_days end as origin_r_30d_salable_days,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_r_14d_salable_days end as origin_r_14d_salable_days,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_r_7d_salable_days end as origin_r_7d_salable_days,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_r_3d_salable_days end as origin_r_3d_salable_days,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else concat(fo.origin_seller_name_new, '/', fo.origin_seller_sku_adj) end as follow_origin_link,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_max_sku end as origin_max_sku,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_max_fnsku end as origin_max_fnsku,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_new_old_product end as origin_new_old_product,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_marketplace_status end as origin_marketplace_status,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_seller_name_concat end as origin_seller_name_concat,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_onsale_sites end as origin_onsale_sites,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_unsale_sites end as origin_unsale_sites,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_sales_status end as origin_sales_status,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_marketplace_concat end as origin_marketplace_concat,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_global_tags end as origin_global_tags,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_seller_name_copy end as origin_seller_name_copy,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_seller_name_ue end as origin_seller_name_ue,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_max_local_name end as origin_max_local_name,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_max_brand_name end as origin_max_brand_name,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_principal end as origin_principal,
    case when coalesce(fo.fllow_flag, 1) = 1 then null else fo.origin_sales_team_1 end as origin_sales_team_1
from tmp_prod_perf_sku_metrics m
left join tmp_prod_perf_follow_origin fo
       on m.country_category = fo.country_category
      and m.seller_name_new = fo.seller_name_new
      and m.seller_sku_adj = fo.seller_sku_adj;

drop temporary table if exists tmp_followed_origin_links;
create temporary table tmp_followed_origin_links as
select
    origin.country_category,
    origin.seller_name_new,
    origin.seller_sku_adj,
    count(distinct concat(follower.seller_name_new, '\0', follower.seller_sku)) as followed_by_count,
    group_concat(
        distinct concat(follower.seller_name_new, '/', follower.seller_sku)
        order by follower.seller_name_new, follower.seller_sku
        separator ' | '
    ) as followed_by_links
from tmp_prod_perf_sku_asin_metrics origin
inner join etl_datasync_test.dashboard_replenishment_self_asin_sync origin_self
        on origin.seller_name_new = origin_self.seller_name_new
       and origin.asin = origin_self.asin
inner join etl_datasync_test.dashboard_replenishment_listing_basic_sync follower
        on follower.country_category = origin.country_category
       and follower.max_asin = origin.asin
       and not (
            follower.seller_name_new = origin.seller_name_new
        and follower.seller_sku = origin.seller_sku_adj
       )
left join etl_datasync_test.dashboard_replenishment_self_asin_sync follower_self
       on follower.seller_name_new = follower_self.seller_name_new
      and follower.max_asin = follower_self.asin
where origin.asin is not null
  and origin.asin <> ''
  and follower_self.asin is null
group by origin.country_category, origin.seller_name_new, origin.seller_sku_adj;

drop temporary table if exists tmp_pur_plan_fba_current;
create temporary table tmp_pur_plan_fba_current as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(coalesce(total, 0)) as total,
    sum(coalesce(total_price, 0)) as total_price,
    sum(coalesce(available_total, 0)) as available_total,
    sum(coalesce(available_price, 0)) as available_price,
    sum(coalesce(afn_fulfillable_quantity, 0)) as afn_fulfillable_quantity,
    sum(coalesce(stock_up_num, 0)) as stock_up_num,
    sum(coalesce(stock_up_num_price, 0)) as stock_up_num_price,
    sum(coalesce(afn_unsellable_quantity, 0)) as afn_unsellable_quantity
from etl_datasync_test.dashboard_inventory_daily_snapshot
where snapshot_date = %(snapshot_date)s
group by country_category, seller_name_new, seller_sku_adj;

drop temporary table if exists tmp_pur_plan_replenish_sug_current;
create temporary table tmp_pur_plan_replenish_sug_current as
select
    country_category,
    seller_name_new,
    seller_sku_adj,
    sum(coalesce(local_quantity, 0)) as local_quantity,
    sum(coalesce(purchase_shipping_quantity, 0)) as sc_quantity_purchase_shipping,
    sum(coalesce(purchase_plan_quantity, 0)) as sc_quantity_purchase_plan,
    sum(coalesce(local_valid_quantity, 0)) as sc_quantity_local_valid,
    sum(coalesce(local_qc_quantity, 0)) as sc_quantity_local_qc
from etl_datasync_test.dashboard_restock_daily_snapshot
where snapshot_date = %(snapshot_date)s
group by country_category, seller_name_new, seller_sku_adj;

drop temporary table if exists tmp_pur_plan_future_history_stat;
create temporary table tmp_pur_plan_future_history_stat as
select
    h.country_category,
    h.seller_name_new,
    h.seller_sku_adj,
    sum(case when h.afn_fulfillable_quantity <> 0 then 1 else 0 end) as future_instock_days,
    sum(case when h.afn_fulfillable_quantity <> 0 then h.day_volume else 0 end) as future_instock_sales
from etl_datasync_test.dashboard_replenishment_history_daily_sync h
inner join tmp_pur_plan_candidate_keys c
        on h.country_category = c.country_category
       and h.seller_name_new = c.seller_name_new
       and h.seller_sku_adj = c.seller_sku_adj
where h.dt_date between date_sub(%(biz_date)s, interval 1 year)
                    and date_add(date_sub(%(biz_date)s, interval 1 year), interval 90 day)
group by h.country_category, h.seller_name_new, h.seller_sku_adj;

drop temporary table if exists tmp_pur_plan_prev_history_stat;
create temporary table tmp_pur_plan_prev_history_stat as
select
    h.country_category,
    h.seller_name_new,
    h.seller_sku_adj,
    sum(case when h.afn_fulfillable_quantity <> 0 then 1 else 0 end) as prev_instock_days,
    sum(case when h.afn_fulfillable_quantity <> 0 then h.day_volume else 0 end) as prev_matched_sales
from etl_datasync_test.dashboard_replenishment_history_daily_sync h
inner join tmp_pur_plan_candidate_keys c
        on h.country_category = c.country_category
       and h.seller_name_new = c.seller_name_new
       and h.seller_sku_adj = c.seller_sku_adj
where h.dt_date between date_sub(date_sub(%(biz_date)s, interval 1 year), interval 90 day)
                    and date_sub(%(biz_date)s, interval 1 year)
group by h.country_category, h.seller_name_new, h.seller_sku_adj;

drop temporary table if exists tmp_pur_plan_sales_change_rate;
create temporary table tmp_pur_plan_sales_change_rate as
select
    ratio_base.*,
    least(
        greatest(
            case
                when future_instock_days < 45 then null
                when prev_instock_days < 45 then null
                when prev_matched_sales_adj is null or prev_matched_sales_adj = 0 then null
                else ((future_instock_sales_adj - prev_matched_sales_adj) / greatest(prev_matched_sales_adj, 30))
                    * least(prev_matched_sales_adj / 50.0, 1.0)
            end,
            -0.5
        ),
        1.5
    ) as sales_change_rate_adj
from (
    select
        future_stat.country_category,
        future_stat.seller_name_new,
        future_stat.seller_sku_adj,
        future_stat.future_instock_days,
        future_stat.future_instock_sales,
        prev_stat.prev_instock_days,
        prev_stat.prev_matched_sales,
        case
            when future_stat.future_instock_days = 0 then null
            when future_stat.future_instock_days < 90 then future_stat.future_instock_sales / future_stat.future_instock_days * 90
            else future_stat.future_instock_sales
        end as future_instock_sales_adj,
        case
            when prev_stat.prev_instock_days = 0 then null
            when prev_stat.prev_instock_days < 90 then prev_stat.prev_matched_sales / prev_stat.prev_instock_days * 90
            else prev_stat.prev_matched_sales
        end as prev_matched_sales_adj
    from tmp_pur_plan_future_history_stat future_stat
    left join tmp_pur_plan_prev_history_stat prev_stat
           on future_stat.country_category = prev_stat.country_category
          and future_stat.seller_name_new = prev_stat.seller_name_new
          and future_stat.seller_sku_adj = prev_stat.seller_sku_adj
) ratio_base;

drop temporary table if exists tmp_pur_plan_support_metric_base;
create temporary table tmp_pur_plan_support_metric_base as
select
    metric_base.*
from (
    select
        c.country_category,
        c.seller_name_new,
        c.seller_sku_adj,
        coalesce(nullif(l.new_old_product, ''), '老品') as new_old_product,
        coalesce(nullif(l.max_fnsku, ''), fm.origin_max_fnsku) as max_fnsku,
        l.max_asin,
        coalesce(nullif(l.max_sku, ''), fm.origin_max_sku, c.max_sku) as max_sku,
        coalesce(nullif(l.marketplace_status, ''), fm.origin_marketplace_status) as marketplace_status,
        coalesce(nullif(l.seller_name_concat, ''), fm.origin_seller_name_concat, c.seller_name_concat) as seller_name_concat,
        coalesce(nullif(l.onsale_sites, ''), fm.origin_onsale_sites) as onsale_sites,
        coalesce(nullif(l.unsale_sites, ''), fm.origin_unsale_sites) as unsale_sites,
        coalesce(nullif(l.sales_status, ''), fm.origin_sales_status) as sales_status,
        coalesce(nullif(l.marketplace_concat, ''), fm.origin_marketplace_concat) as marketplace_concat,
        coalesce(nullif(l.global_tags, ''), fm.origin_global_tags) as global_tags,
        coalesce(nullif(l.seller_name_copy, ''), fm.origin_seller_name_copy) as seller_name_copy,
        coalesce(nullif(l.seller_name_ue, ''), fm.origin_seller_name_ue) as seller_name_ue,
        coalesce(nullif(l.max_local_name, ''), fm.origin_max_local_name) as max_local_name,
        coalesce(nullif(l.max_brand_name, ''), fm.origin_max_brand_name) as max_brand_name,
        coalesce(nullif(l.principal, ''), fm.origin_principal) as principal,
        coalesce(nullif(l.sales_team_1, ''), fm.origin_sales_team_1) as sales_team_1,
        fm.follow_origin_link,
        fs.max_receiving_time,
        fs.receiving_cnt,
        coalesce(fm.fllow_flag, 1) as fllow_flag,
        case when followed_by_count > 0 then 1 else 0 end as followed_flag,
        coalesce(fol.followed_by_count, 0) as followed_by_count,
        fol.followed_by_links,
        coalesce(m.sales_180, 0) as sales_180,
        coalesce(m.sales_90, 0) as sales_90,
        coalesce(m.sales_30, 0) as sales_30,
        coalesce(m.sales_14, 0) as sales_14,
        coalesce(m.sales_7, 0) as sales_7,
        coalesce(m.sales_3, 0) as sales_3,
        coalesce(fm.sales_30, m.sales_30, 0) as final_sales_30,
        coalesce(fm.sales_14, m.sales_14, 0) as final_sales_14,
        coalesce(fm.sales_7, m.sales_7, 0) as final_sales_7,
        coalesce(fm.sales_3, m.sales_3, 0) as final_sales_3,
        coalesce(m.amount_180, 0) as amount_180,
        coalesce(m.amount_90, 0) as amount_90,
        coalesce(m.amount_30, 0) as amount_30,
        coalesce(m.amount_14, 0) as amount_14,
        coalesce(m.amount_7, 0) as amount_7,
        coalesce(m.amount_3, 0) as amount_3,
        coalesce(m.pprofit_180, 0) as pprofit_180,
        coalesce(m.pprofit_90, 0) as pprofit_90,
        coalesce(m.pprofit_30, 0) as pprofit_30,
        coalesce(m.pprofit_14, 0) as pprofit_14,
        coalesce(m.pprofit_7, 0) as pprofit_7,
        coalesce(m.pprofit_3, 0) as pprofit_3,
        m.pprofit_180 / nullif(m.amount_180, 0) as pprofit_ratio_180,
        m.pprofit_90 / nullif(m.amount_90, 0) as pprofit_ratio_90,
        m.pprofit_30 / nullif(m.amount_30, 0) as pprofit_ratio_30,
        m.pprofit_14 / nullif(m.amount_14, 0) as pprofit_ratio_14,
        m.pprofit_7 / nullif(m.amount_7, 0) as pprofit_ratio_7,
        m.pprofit_3 / nullif(m.amount_3, 0) as pprofit_ratio_3,
        gp.final_profit_rate,
        coalesce(f.total, 0) as total,
        coalesce(f.total_price, 0) as total_price,
        coalesce(f.available_total, 0) as available_total,
        coalesce(f.available_price, 0) as available_price,
        coalesce(f.afn_fulfillable_quantity, 0) as afn_fulfillable_quantity,
        coalesce(f.stock_up_num, 0) as stock_up_num,
        coalesce(f.stock_up_num_price, 0) as stock_up_num_price,
        coalesce(f.afn_unsellable_quantity, 0) as afn_unsellable_quantity,
        coalesce(r.local_quantity, 0) as local_quantity,
        coalesce(r.sc_quantity_purchase_shipping, 0) as sc_quantity_purchase_shipping,
        coalesce(r.sc_quantity_purchase_plan, 0) as sc_quantity_purchase_plan,
        coalesce(r.sc_quantity_local_valid, 0) as sc_quantity_local_valid,
        coalesce(r.sc_quantity_local_qc, 0) as sc_quantity_local_qc,
        coalesce(ks.r_180d_salable_days, 0) as r_180d_salable_days,
        coalesce(ks.r_90d_salable_days, 0) as r_90d_salable_days,
        coalesce(ks.r_30d_salable_days, 0) as r_30d_salable_days,
        coalesce(ks.r_14d_salable_days, 0) as r_14d_salable_days,
        coalesce(ks.r_7d_salable_days, 0) as r_7d_salable_days,
        coalesce(ks.r_3d_salable_days, 0) as r_3d_salable_days,
        greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)) as result_r_30d_salable_days,
        greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) as result_r_14d_salable_days,
        greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) as result_r_7d_salable_days,
        greatest(coalesce(ks.r_3d_salable_days, 0), coalesce(fm.origin_r_3d_salable_days, 0)) as result_r_3d_salable_days,
        coalesce(ks.r_90d_salable_days, 0) as hist_90d_instock_days,
        coalesce(m.sales_90, 0) as hist_90d_instock_sales,
        case
            when coalesce(ks.r_90d_salable_days, 0) > 0 then coalesce(m.sales_90, 0) / ks.r_90d_salable_days
            else 0
        end as hist_90d_instock_daily_sales,
        scr.sales_change_rate_adj,
        case
            when coalesce(ks.r_30d_salable_days, 0) >= 7 then
                case when coalesce(ks.r_3d_salable_days, 0) > 0 then coalesce(m.sales_3, 0) / ks.r_3d_salable_days else 0 end
            else coalesce(m.sales_3, 0) / greatest(coalesce(ks.r_3d_salable_days, 0), 2)
        end as adjusted_daily_sales_3d,
        case
            when coalesce(ks.r_30d_salable_days, 0) >= 7 then
                case
                    when coalesce(ks.r_7d_salable_days, 0) >= 7 then coalesce(m.sales_7, 0) / ks.r_7d_salable_days
                    else least(
                        case when coalesce(ks.r_7d_salable_days, 0) > 0 then coalesce(m.sales_7, 0) / ks.r_7d_salable_days else 0 end,
                        (case when coalesce(ks.r_7d_salable_days, 0) > 0 then coalesce(m.sales_7, 0) / ks.r_7d_salable_days else 0 end)
                            * (ks.r_7d_salable_days / (ks.r_7d_salable_days + 3))
                        + (coalesce(m.sales_30, 0) / ks.r_30d_salable_days)
                            * (1 - ks.r_7d_salable_days / (ks.r_7d_salable_days + 3))
                    )
                end
            else coalesce(m.sales_7, 0) / greatest(coalesce(ks.r_7d_salable_days, 0), 3)
        end as adjusted_daily_sales_7d,
        case
            when coalesce(ks.r_30d_salable_days, 0) >= 7 then
                case
                    when coalesce(ks.r_14d_salable_days, 0) >= 14 then coalesce(m.sales_14, 0) / ks.r_14d_salable_days
                    else least(
                        case when coalesce(ks.r_14d_salable_days, 0) > 0 then coalesce(m.sales_14, 0) / ks.r_14d_salable_days else 0 end,
                        (case when coalesce(ks.r_14d_salable_days, 0) > 0 then coalesce(m.sales_14, 0) / ks.r_14d_salable_days else 0 end)
                            * (ks.r_14d_salable_days / (ks.r_14d_salable_days + 7))
                        + (coalesce(m.sales_30, 0) / ks.r_30d_salable_days)
                            * (1 - ks.r_14d_salable_days / (ks.r_14d_salable_days + 7))
                    )
                end
            else coalesce(m.sales_14, 0) / greatest(coalesce(ks.r_14d_salable_days, 0), 7)
        end as adjusted_daily_sales_14d,
        case
            when coalesce(ks.r_30d_salable_days, 0) >= 7 then coalesce(m.sales_30, 0) / ks.r_30d_salable_days
            else coalesce(m.sales_30, 0) / greatest(coalesce(ks.r_30d_salable_days, 0), 15)
        end as adjusted_daily_sales_30d,
        case
            when greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)) >= 7 then
                case
                    when greatest(coalesce(ks.r_3d_salable_days, 0), coalesce(fm.origin_r_3d_salable_days, 0)) > 0
                        then coalesce(fm.sales_3, m.sales_3, 0)
                             / greatest(coalesce(ks.r_3d_salable_days, 0), coalesce(fm.origin_r_3d_salable_days, 0))
                    else 0
                end
            else coalesce(fm.sales_3, m.sales_3, 0)
                 / greatest(greatest(coalesce(ks.r_3d_salable_days, 0), coalesce(fm.origin_r_3d_salable_days, 0)), 2)
        end as final_adjusted_daily_sales_3d,
        case
            when greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)) >= 7 then
                case
                    when greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) >= 7
                        then coalesce(fm.sales_7, m.sales_7, 0)
                             / greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0))
                    else least(
                        case
                            when greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) > 0
                                then coalesce(fm.sales_7, m.sales_7, 0)
                                     / greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0))
                            else 0
                        end,
                        (case
                            when greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) > 0
                                then coalesce(fm.sales_7, m.sales_7, 0)
                                     / greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0))
                            else 0
                        end)
                            * (
                                greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0))
                                / (greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) + 3)
                            )
                        + (
                            coalesce(fm.sales_30, m.sales_30, 0)
                            / greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0))
                          )
                            * (
                                1 - greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0))
                                / (greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)) + 3)
                            )
                    )
                end
            else coalesce(fm.sales_7, m.sales_7, 0)
                 / greatest(greatest(coalesce(ks.r_7d_salable_days, 0), coalesce(fm.origin_r_7d_salable_days, 0)), 3)
        end as final_adjusted_daily_sales_7d,
        case
            when greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)) >= 7 then
                case
                    when greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) >= 14
                        then coalesce(fm.sales_14, m.sales_14, 0)
                             / greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0))
                    else least(
                        case
                            when greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) > 0
                                then coalesce(fm.sales_14, m.sales_14, 0)
                                     / greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0))
                            else 0
                        end,
                        (case
                            when greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) > 0
                                then coalesce(fm.sales_14, m.sales_14, 0)
                                     / greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0))
                            else 0
                        end)
                            * (
                                greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0))
                                / (greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) + 7)
                            )
                        + (
                            coalesce(fm.sales_30, m.sales_30, 0)
                            / greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0))
                          )
                            * (
                                1 - greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0))
                                / (greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)) + 7)
                            )
                    )
                end
            else coalesce(fm.sales_14, m.sales_14, 0)
                 / greatest(greatest(coalesce(ks.r_14d_salable_days, 0), coalesce(fm.origin_r_14d_salable_days, 0)), 7)
        end as final_adjusted_daily_sales_14d,
        case
            when greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)) >= 7
                then coalesce(fm.sales_30, m.sales_30, 0)
                     / greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0))
            else coalesce(fm.sales_30, m.sales_30, 0)
                 / greatest(greatest(coalesce(ks.r_30d_salable_days, 0), coalesce(fm.origin_r_30d_salable_days, 0)), 15)
        end as final_adjusted_daily_sales_30d,
        l.max_cg_box_pcs,
        l.max_cg_delivery as purchase_lead_days_raw,
        case when coalesce(l.max_cg_delivery, 0) > 0 then l.max_cg_delivery else 0 end
            as effective_purchase_lead_days,
        case when coalesce(l.max_cg_delivery, 0) > 0 then 'configured' else 'unconfigured' end
            as purchase_lead_status,
        l.max_cg_price,
        l.max_cg_transport_costs,
        4 as pre_replenish_comp_months,
        coalesce(f.available_total, 0) + coalesce(f.stock_up_num, 0) + coalesce(r.local_quantity, 0) as support_inventory_qty
    from tmp_pur_plan_candidate_keys c
    left join tmp_prod_perf_sku_metrics m
           on c.country_category = m.country_category
          and c.seller_name_new = m.seller_name_new
          and c.seller_sku_adj = m.seller_sku_adj
    left join tmp_prod_perf_sku_follow_metrics fm
           on c.country_category = fm.country_category
          and c.seller_name_new = fm.seller_name_new
          and c.seller_sku_adj = fm.seller_sku_adj
    left join tmp_followed_origin_links fol
           on c.country_category = fol.country_category
          and c.seller_name_new = fol.seller_name_new
          and c.seller_sku_adj = fol.seller_sku_adj
    left join tmp_pur_plan_fba_current f
           on c.country_category = f.country_category
          and c.seller_name_new = f.seller_name_new
          and c.seller_sku_adj = f.seller_sku_adj
    left join tmp_pur_plan_replenish_sug_current r
           on c.country_category = r.country_category
          and c.seller_name_new = r.seller_name_new
          and c.seller_sku_adj = r.seller_sku_adj
    left join etl_datasync_test.dashboard_replenishment_listing_basic_sync l
           on c.country_category = l.country_category
          and c.seller_name_new = l.seller_name_new
          and c.seller_sku_adj = l.seller_sku
    left join etl_datasync_test.dashboard_replenishment_fba_shipment_sync fs
           on c.country_category = fs.country_category
          and c.seller_name_new = fs.seller_name_new
          and c.seller_sku_adj = fs.msku
    left join etl_datasync_test.pur_plan_prod_perf_salable_days_stat ks
           on ks.sta_dt = %(biz_date)s
          and c.country_category = ks.country_category
          and c.seller_name_new = ks.seller_name_new
          and c.seller_sku_adj = ks.seller_sku_adj
    left join tmp_pur_plan_sales_change_rate scr
           on c.country_category = scr.country_category
          and c.seller_name_new = scr.seller_name_new
          and c.seller_sku_adj = scr.seller_sku_adj
    left join etl_datasync_test.dashboard_replenishment_order_profit_source gp
           on c.country_category = gp.country_category
          and c.seller_name_new = gp.seller_name_new
          and c.seller_sku_adj = gp.seller_sku_adj
) metric_base;

drop temporary table if exists tmp_pur_plan_support_calc_base;
create temporary table tmp_pur_plan_support_calc_base as
select
    metric_base.*,
    case
        when (max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null))
          or (max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null))
            then adjusted_daily_sales_3d * 0.5 + adjusted_daily_sales_7d * 0.5
        else adjusted_daily_sales_7d * 0.6 + adjusted_daily_sales_14d * 0.2 + adjusted_daily_sales_30d * 0.2
    end as pre_daily_avg_sales,
    case
        when (max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null))
          or (max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null))
            then final_adjusted_daily_sales_3d * 0.5 + final_adjusted_daily_sales_7d * 0.5
        else final_adjusted_daily_sales_7d * 0.6 + final_adjusted_daily_sales_14d * 0.2 + final_adjusted_daily_sales_30d * 0.2
    end as daily_avg_sales,
    pre_replenish_comp_months * 30 * (
        case
            when (max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null))
              or (max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null))
                then adjusted_daily_sales_3d * 0.5 + adjusted_daily_sales_7d * 0.5
            else adjusted_daily_sales_7d * 0.6 + adjusted_daily_sales_14d * 0.2 + adjusted_daily_sales_30d * 0.2
        end
    )
    - available_total
    - stock_up_num
    - local_quantity as pre_normal_replenish_need_qty,
    hist_90d_instock_daily_sales * 120
    - available_total
    - stock_up_num
    - local_quantity as history_recovery_need_qty,
    case
        when coalesce(max_cg_box_pcs, 0) > 0 then max_cg_box_pcs
        else 50
    end as pre_replenish_trigger_qty
from tmp_pur_plan_support_metric_base metric_base;

drop temporary table if exists tmp_pur_plan_support_layer_all;
create temporary table tmp_pur_plan_support_layer_all as
select
    arrival.*,
    case
        when coalesce(arrival.daily_avg_sales, 0) <= 0 then 5
        when arrival.arrival_inventory_support_days <= 35 then 1
        when arrival.arrival_inventory_support_days <= 65 then 2
        when arrival.arrival_inventory_support_days <= 90 then 3
        when arrival.arrival_inventory_support_days > 90 then 4
        else 2
    end as support_replenish_level_sort,
    case
        when coalesce(arrival.daily_avg_sales, 0) <= 0 then '日销为0'
        when arrival.arrival_inventory_support_days <= 35 then '紧急补货'
        when arrival.arrival_inventory_support_days <= 65 then '建议补货'
        when arrival.arrival_inventory_support_days <= 90 then '计划补货'
        when arrival.arrival_inventory_support_days > 90 then '库存充足'
        else '建议补货'
    end as support_replenish_level
from (
select
    base.*,
    case
        when coalesce(base.daily_avg_sales, 0) <= 0 then null
        else base.support_inventory_qty / base.daily_avg_sales
    end as inventory_support_days,
    case
        when coalesce(base.daily_avg_sales, 0) <= 0 then null
        else base.support_inventory_qty / base.daily_avg_sales - base.effective_purchase_lead_days
    end as arrival_inventory_support_days,
    greatest(
        base.support_inventory_qty
        - base.effective_purchase_lead_days * base.daily_avg_sales,
        0
    ) as arrival_inventory_qty,
    base.effective_purchase_lead_days * coalesce(base.daily_avg_sales, 0) as lead_time_demand_qty,
    greatest(120 * coalesce(base.daily_avg_sales, 0) - base.support_inventory_qty, 0)
        as base_replenish_need_qty,
    greatest(
        120 * coalesce(base.daily_avg_sales, 0)
        - greatest(
            base.support_inventory_qty
            - base.effective_purchase_lead_days * base.daily_avg_sales,
            0
        ),
        0
    ) as lead_adjusted_replenish_need_qty,
    case
        when coalesce(base.daily_avg_sales, 0) > 0
         and base.support_inventory_qty / base.daily_avg_sales < base.effective_purchase_lead_days
            then 1
        else 0
    end as lead_time_stockout_flag,
    case
        when coalesce(base.daily_avg_sales, 0) <= 0 then 0
        else greatest(
            base.effective_purchase_lead_days
            - base.support_inventory_qty / base.daily_avg_sales,
            0
        )
    end as lead_time_stockout_days,
    case
        when coalesce(base.daily_avg_sales, 0) <= 0 then 0
        else greatest(
            base.effective_purchase_lead_days
            - base.support_inventory_qty / base.daily_avg_sales,
            0
        ) * base.daily_avg_sales
    end as lead_time_lost_sales_qty
from tmp_pur_plan_support_calc_base base
) arrival;

drop temporary table if exists tmp_pur_plan_replenish_calc;
create temporary table tmp_pur_plan_replenish_calc as
select
    support.*,
    greatest(120 * support.daily_avg_sales - support.arrival_inventory_qty, 0)
        as normal_replenish_need_qty,
    case
        when support.pre_normal_replenish_need_qty < support.pre_replenish_trigger_qty
             and support.r_30d_salable_days < 15
             and support.hist_90d_instock_days >= 15
             and support.hist_90d_instock_daily_sales > 1.5
             and support.history_recovery_need_qty >= support.pre_replenish_trigger_qty
            then 1
        else 0
    end as history_recovery_flag,
    case
        when sales_change_rate_adj is null then 1
        when 1 + sales_change_rate_adj < 0 then 1
        else 1 + sales_change_rate_adj
    end as sales_adj_factor
from tmp_pur_plan_support_layer_all support;

drop temporary table if exists tmp_asin_merge_groups;
drop temporary table if exists tmp_asin_merge_group_daily_base;
create temporary table tmp_asin_merge_group_daily_base as
select
    group_base.country_category,
    group_base.max_asin,
    count(*) as link_count,
    max(case when coalesce(fllow_flag, 1) = 0 then 1 else 0 end) as has_follow_link,
    max(case when coalesce(followed_flag, 0) = 1 then 1 else 0 end) as has_followed_origin,
    sum(coalesce(sales_30, 0)) as group_sales_30,
    sum(coalesce(sales_14, 0)) as group_sales_14,
    sum(coalesce(sales_7, 0)) as group_sales_7,
    sum(coalesce(sales_3, 0)) as group_sales_3,
    max(coalesce(result_r_30d_salable_days, 0)) as group_result_r_30d_salable_days,
    max(coalesce(result_r_14d_salable_days, 0)) as group_result_r_14d_salable_days,
    max(coalesce(result_r_7d_salable_days, 0)) as group_result_r_7d_salable_days,
    max(coalesce(result_r_3d_salable_days, 0)) as group_result_r_3d_salable_days,
    max(
        case
            when (max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null))
              or (max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null))
                then 1
            else 0
        end
    ) as group_new_product_daily_weight_flag,
    max(coalesce(pre_replenish_comp_months, 4)) as group_replenish_comp_months,
    sum(coalesce(support_inventory_qty, 0)) as group_support_inventory_qty,
    max(coalesce(purchase_source.effective_purchase_lead_days, 0))
        as group_effective_purchase_lead_days,
    sum(case when coalesce(fllow_flag, 1) = 0 then 1 else 0 end) as eligible_target_link_count
from (
    select
        country_category,
        max_asin,
        seller_name_new,
        seller_sku_adj,
        fllow_flag,
        followed_flag,
        sales_status,
        sales_30,
        sales_14,
        sales_7,
        sales_3,
        result_r_30d_salable_days,
        result_r_14d_salable_days,
        result_r_7d_salable_days,
        result_r_3d_salable_days,
        max_brand_name,
        receiving_cnt,
        pre_replenish_comp_months,
        support_inventory_qty
    from tmp_pur_plan_replenish_calc
    where max_asin is not null
      and max_asin <> ''
) group_base
left join (
    select
        ranked.country_category,
        ranked.max_asin,
        ranked.purchase_lead_days_raw,
        ranked.effective_purchase_lead_days
    from (
        select
            calc.country_category,
            calc.max_asin,
            calc.purchase_lead_days_raw,
            calc.effective_purchase_lead_days,
            row_number() over (partition by calc.country_category, calc.max_asin order by
                case when coalesce(calc.followed_flag, 0) = 1 then 0 else 1 end,
                case when coalesce(calc.fllow_flag, 1) = 1 then 0 else 1 end,
                case when coalesce(calc.sales_30, 0) > 0 then 0 else 1 end,
                coalesce(calc.sales_30, 0) desc,
                calc.seller_name_new,
                calc.seller_sku_adj
            ) as rn
        from tmp_pur_plan_replenish_calc calc
        where calc.max_asin is not null
          and calc.max_asin <> ''
          and calc.max_cg_price is not null
          and calc.max_cg_transport_costs is not null
    ) ranked
    where ranked.rn = 1
) purchase_source
       on group_base.country_category = purchase_source.country_category
      and group_base.max_asin = purchase_source.max_asin
group by group_base.country_category, group_base.max_asin
having link_count > 1
   and has_follow_link > 0;

drop temporary table if exists tmp_asin_merge_group_daily_parts;
create temporary table tmp_asin_merge_group_daily_parts as
select
    daily_base.*,
    case
        when group_result_r_30d_salable_days >= 7 then
            case
                when group_result_r_3d_salable_days > 0
                    then group_sales_3 / group_result_r_3d_salable_days
                else 0
            end
        else group_sales_3 / greatest(group_result_r_3d_salable_days, 2)
    end as group_adjusted_daily_sales_3d,
    case
        when group_result_r_30d_salable_days >= 7 then
            case
                when group_result_r_7d_salable_days >= 7
                    then group_sales_7 / group_result_r_7d_salable_days
                else least(
                    case
                        when group_result_r_7d_salable_days > 0
                            then group_sales_7 / group_result_r_7d_salable_days
                        else 0
                    end,
                    (case
                        when group_result_r_7d_salable_days > 0
                            then group_sales_7 / group_result_r_7d_salable_days
                        else 0
                    end)
                        * (
                            group_result_r_7d_salable_days
                            / (group_result_r_7d_salable_days + 3)
                        )
                    + (group_sales_30 / nullif(group_result_r_30d_salable_days, 0))
                        * (
                            1 - group_result_r_7d_salable_days
                            / (group_result_r_7d_salable_days + 3)
                        )
                )
            end
        else group_sales_7 / greatest(group_result_r_7d_salable_days, 3)
    end as group_adjusted_daily_sales_7d,
    case
        when group_result_r_30d_salable_days >= 7 then
            case
                when group_result_r_14d_salable_days >= 14
                    then group_sales_14 / group_result_r_14d_salable_days
                else least(
                    case
                        when group_result_r_14d_salable_days > 0
                            then group_sales_14 / group_result_r_14d_salable_days
                        else 0
                    end,
                    (case
                        when group_result_r_14d_salable_days > 0
                            then group_sales_14 / group_result_r_14d_salable_days
                        else 0
                    end)
                        * (
                            group_result_r_14d_salable_days
                            / (group_result_r_14d_salable_days + 7)
                        )
                    + (group_sales_30 / nullif(group_result_r_30d_salable_days, 0))
                        * (
                            1 - group_result_r_14d_salable_days
                            / (group_result_r_14d_salable_days + 7)
                        )
                )
            end
        else group_sales_14 / greatest(group_result_r_14d_salable_days, 7)
    end as group_adjusted_daily_sales_14d,
    case
        when group_result_r_30d_salable_days >= 7
            then group_sales_30 / group_result_r_30d_salable_days
        else group_sales_30 / greatest(group_result_r_30d_salable_days, 15)
    end as group_adjusted_daily_sales_30d
from tmp_asin_merge_group_daily_base daily_base;

create temporary table tmp_asin_merge_groups as
select
    group_daily.*,
    case
        when group_daily_avg_sales <= 0 then null
        else group_support_inventory_qty / group_daily_avg_sales
    end as group_inventory_support_days,
    case
        when group_daily_avg_sales <= 0 then null
        else group_support_inventory_qty / group_daily_avg_sales
            - group_effective_purchase_lead_days
    end as group_arrival_inventory_support_days,
    greatest(
        group_support_inventory_qty
        - group_effective_purchase_lead_days * group_daily_avg_sales,
        0
    ) as group_arrival_inventory_qty,
    group_effective_purchase_lead_days * group_daily_avg_sales
        as group_lead_time_demand_qty,
    greatest(
        120 * group_daily_avg_sales - group_support_inventory_qty,
        0
    ) as group_base_replenish_need_qty,
    greatest(
        group_replenish_comp_months * 30 * group_daily_avg_sales
        - greatest(
            group_support_inventory_qty
            - group_effective_purchase_lead_days * group_daily_avg_sales,
            0
        ),
        0
    ) as group_replenish_need_qty,
    greatest(
        group_replenish_comp_months * 30 * group_daily_avg_sales
        - greatest(
            group_support_inventory_qty
            - group_effective_purchase_lead_days * group_daily_avg_sales,
            0
        ),
        0
    ) as group_lead_adjusted_replenish_need_qty,
    case
        when group_daily_avg_sales > 0
         and group_support_inventory_qty / group_daily_avg_sales
             < group_effective_purchase_lead_days
            then 1
        else 0
    end as group_lead_time_stockout_flag,
    case
        when group_daily_avg_sales <= 0 then 0
        else greatest(
            group_effective_purchase_lead_days
            - group_support_inventory_qty / group_daily_avg_sales,
            0
        )
    end as group_lead_time_stockout_days,
    case
        when group_daily_avg_sales <= 0 then 0
        else greatest(
            group_effective_purchase_lead_days
            - group_support_inventory_qty / group_daily_avg_sales,
            0
        ) * group_daily_avg_sales
    end as group_lead_time_lost_sales_qty,
    case
        when group_daily_avg_sales <= 0 then 5
        when group_support_inventory_qty / group_daily_avg_sales
            - group_effective_purchase_lead_days <= 35 then 1
        when group_support_inventory_qty / group_daily_avg_sales
            - group_effective_purchase_lead_days <= 65 then 2
        when group_support_inventory_qty / group_daily_avg_sales
            - group_effective_purchase_lead_days <= 90 then 3
        when group_support_inventory_qty / group_daily_avg_sales
            - group_effective_purchase_lead_days > 90 then 4
        else 2
    end as group_support_replenish_level_sort
from (
    select
        daily_parts.*,
        case
            when group_new_product_daily_weight_flag = 1
                then group_adjusted_daily_sales_3d * 0.5
                   + group_adjusted_daily_sales_7d * 0.5
            else group_adjusted_daily_sales_7d * 0.6
               + group_adjusted_daily_sales_14d * 0.2
               + group_adjusted_daily_sales_30d * 0.2
        end as group_daily_avg_sales
    from tmp_asin_merge_group_daily_parts daily_parts
) group_daily;

drop temporary table if exists tmp_asin_merge_latest_performance;
create temporary table tmp_asin_merge_latest_performance as
select
    calc.country_category,
    calc.seller_name_new,
    calc.seller_sku_adj,
    max(perf.dt_date) as max_perf_date
from tmp_pur_plan_replenish_calc calc
left join etl_datasync_test.dashboard_product_performance_daily perf
       on calc.country_category = perf.country_category
      and calc.seller_name_new = perf.seller_name_new
      and calc.seller_sku_adj = perf.seller_sku_adj
      and perf.dt_date <= %(biz_date)s
inner join tmp_asin_merge_groups grp
        on calc.country_category = grp.country_category
       and calc.max_asin = grp.max_asin
group by
    calc.country_category,
    calc.seller_name_new,
    calc.seller_sku_adj;

drop temporary table if exists tmp_asin_merge_targets;
create temporary table tmp_asin_merge_targets as
select
    ranked.country_category,
    ranked.max_asin,
    ranked.seller_name_new as target_seller_name_new,
    ranked.seller_sku_adj as target_seller_sku_adj,
    concat(ranked.seller_name_new, '/', ranked.seller_sku_adj) as asin_merge_target
from (
    select
        calc.country_category,
        calc.max_asin,
        calc.seller_name_new,
        calc.seller_sku_adj,
        row_number() over (partition by calc.country_category, calc.max_asin order by
            coalesce(perf.max_perf_date, date('1900-01-01')) desc,
            case when coalesce(calc.followed_flag, 0) = 0 then 0 else 1 end,
            case when calc.sales_status <> '停售中' then 0 else 1 end,
            case
                when coalesce(calc.max_cg_box_pcs, 0) > 0
                 and calc.max_cg_price is not null
                 and calc.max_cg_transport_costs is not null then 0
                else 1
            end,
            case when coalesce(calc.support_inventory_qty, 0) > 0 then 0 else 1 end,
            case when coalesce(calc.sales_30, 0) > 0 then 0 else 1 end,
            calc.seller_name_new,
            calc.seller_sku_adj
        ) as rn
    from tmp_pur_plan_replenish_calc calc
    inner join tmp_asin_merge_groups grp
            on calc.country_category = grp.country_category
           and calc.max_asin = grp.max_asin
    left join tmp_asin_merge_latest_performance perf
           on calc.country_category = perf.country_category
          and calc.seller_name_new = perf.seller_name_new
          and calc.seller_sku_adj = perf.seller_sku_adj
    where coalesce(calc.fllow_flag, 1) = 0
      and grp.eligible_target_link_count > 0
) ranked
where ranked.rn = 1;

drop temporary table if exists tmp_asin_merge_assignments;
create temporary table tmp_asin_merge_assignments as
select
    calc.country_category,
    calc.seller_name_new,
    calc.seller_sku_adj,
    calc.max_asin,
    1 as asin_merge_flag,
    target.asin_merge_target,
    case
        when grp.eligible_target_link_count = 0 then '同ASIN库存充足不补货'
        when grp.group_replenish_need_qty <= 0
          or grp.group_support_replenish_level_sort not in (1, 2, 3)
            then '同ASIN库存充足不补货'
        when target.asin_merge_target is null then '同ASIN库存充足不补货'
        when calc.seller_name_new = target.target_seller_name_new
         and calc.seller_sku_adj = target.target_seller_sku_adj
            then '产品组补货目标链接'
        else '同ASIN已合并至主链接'
    end as asin_merge_reason,
    case
        when calc.seller_name_new = target.target_seller_name_new
         and calc.seller_sku_adj = target.target_seller_sku_adj
            then 1
        else 0
    end as asin_merge_target_flag,
    grp.group_replenish_need_qty,
    grp.group_effective_purchase_lead_days,
    grp.group_inventory_support_days,
    grp.group_arrival_inventory_support_days,
    grp.group_arrival_inventory_qty,
    grp.group_lead_time_demand_qty,
    grp.group_base_replenish_need_qty,
    grp.group_lead_adjusted_replenish_need_qty,
    grp.group_lead_time_stockout_flag,
    grp.group_lead_time_stockout_days,
    grp.group_lead_time_lost_sales_qty,
    grp.group_support_replenish_level_sort
from tmp_pur_plan_replenish_calc calc
inner join tmp_asin_merge_groups grp
        on calc.country_category = grp.country_category
       and calc.max_asin = grp.max_asin
left join tmp_asin_merge_targets target
       on calc.country_category = target.country_category
      and calc.max_asin = target.max_asin;

drop temporary table if exists tmp_asin_merge_purchase_fields;
create temporary table tmp_asin_merge_purchase_fields as
select
    ranked.country_category,
    ranked.max_asin,
    nullif(ranked.max_cg_box_pcs, 0) as effective_max_cg_box_pcs,
    ranked.max_cg_price as effective_max_cg_price,
    ranked.max_cg_transport_costs as effective_max_cg_transport_costs,
    ranked.purchase_lead_days_raw,
    ranked.effective_purchase_lead_days,
    ranked.purchase_lead_status
from (
    select
        calc.country_category,
        calc.max_asin,
        calc.max_cg_box_pcs,
        calc.max_cg_price,
        calc.max_cg_transport_costs,
        calc.purchase_lead_days_raw,
        calc.effective_purchase_lead_days,
        calc.purchase_lead_status,
        row_number() over (partition by calc.country_category, calc.max_asin order by
            case when coalesce(calc.followed_flag, 0) = 1 then 0 else 1 end,
            case when coalesce(calc.fllow_flag, 1) = 1 then 0 else 1 end,
            case when coalesce(calc.sales_30, 0) > 0 then 0 else 1 end,
            coalesce(calc.sales_30, 0) desc,
            calc.seller_name_new,
            calc.seller_sku_adj
        ) as rn
    from tmp_pur_plan_replenish_calc calc
    inner join tmp_asin_merge_groups grp
            on calc.country_category = grp.country_category
           and calc.max_asin = grp.max_asin
    where calc.max_cg_price is not null
      and calc.max_cg_transport_costs is not null
) ranked
where ranked.rn = 1;

insert into etl_datasync_test.dashboard_pur_plan_replenish_data (
    cur_date, new_old_product, seller_sku_adj, max_fnsku, max_asin, max_sku,
    marketplace_status, seller_name_concat, onsale_sites, unsale_sites, sales_status,
    marketplace_concat, global_tags, seller_name_copy, seller_name_ue, seller_name_new, country_category,
    max_local_name, max_brand_name, principal, sales_team_1, max_receiving_time, receiving_cnt,
    max_cg_box_pcs, max_cg_price, max_cg_transport_costs,
    purchase_lead_days_raw, effective_purchase_lead_days, purchase_lead_status, stockout_status,
    pre_daily_avg_sales, pre_normal_replenish_need_qty, pre_replenish_trigger_qty,
    hist_90d_instock_days, hist_90d_instock_sales, hist_90d_instock_daily_sales,
    history_recovery_need_qty, history_recovery_flag,
    support_inventory_qty, inventory_support_days,
    arrival_inventory_support_days, arrival_inventory_qty, lead_time_demand_qty,
    base_replenish_need_qty, lead_adjusted_replenish_need_qty,
    lead_time_stockout_flag, lead_time_stockout_days, lead_time_lost_sales_qty,
    support_replenish_level, support_replenish_level_sort,
    abcd_category, gp_margin_range, predict_abcd_category,
    fba_local_quantity, total, available_total, afn_fulfillable_quantity, stock_up_num, afn_unsellable_quantity,
    sc_quantity_local_valid, sc_quantity_purchase_shipping, sc_quantity_purchase_plan, sc_quantity_local_qc, local_quantity,
    r_180d_salable_days, r_90d_salable_days, r_30d_salable_days, r_14d_salable_days, r_7d_salable_days, r_3d_salable_days,
    sales_180d, sales_90d, final_sales_30d, final_sales_14d, final_sales_7d, final_sales_3d,
    amount_180d, amount_90d, amount_30d, amount_14d, amount_7d, amount_3d,
    pprofit_180d, pprofit_90d, pprofit_30d, pprofit_14d, pprofit_7d, pprofit_3d,
    pprofit_ratio_180d, pprofit_ratio_90d, pprofit_ratio_30d, pprofit_ratio_14d, pprofit_ratio_7d, pprofit_ratio_3d,
    new_old_prod_jg, daily_avg_sales, replenish_comp_months, salable_days,
    `60d_stocko_qty`, `90d_stocko_qty`, `180d_stocko_qty`, replenish_dur_calc_stocko_qty,
    replenish_need_qty, replenish_trigger_qty, sales_change_rate_adj, sales_adj_factor, final_profit_rate,
    replenish_qty, replenish_box_qty, replenish_cost,
    amz_instock_sales_ratio, instock_intrans_pur_sales_ratio, fllow_flag,
    followed_flag, followed_by_count, followed_by_links, follow_origin_link, replenish_block_reason,
    asin_merge_flag, asin_merge_target, asin_merge_reason
)
select
    %(snapshot_date)s as cur_date,
    new_old_product,
    seller_sku_adj,
    max_fnsku,
    max_asin,
    max_sku,
    marketplace_status,
    seller_name_concat,
    onsale_sites,
    unsale_sites,
    sales_status,
    marketplace_concat,
    global_tags,
    seller_name_copy,
    seller_name_ue,
    seller_name_new,
    country_category,
    max_local_name,
    max_brand_name,
    principal,
    sales_team_1,
    max_receiving_time,
    receiving_cnt,
    effective_max_cg_box_pcs as max_cg_box_pcs,
    effective_max_cg_price as max_cg_price,
    effective_max_cg_transport_costs as max_cg_transport_costs,
    final_purchase_lead_days_raw as purchase_lead_days_raw,
    final_effective_purchase_lead_days as effective_purchase_lead_days,
    final_purchase_lead_status as purchase_lead_status,
    case
        when final_inventory_support_days > 60 then '不会缺货'
        when stock_up_num = 0 and local_quantity = 0 then '缺货未补货'
        else '缺货已补货'
    end as stockout_status,
    pre_daily_avg_sales,
    pre_normal_replenish_need_qty,
    pre_replenish_trigger_qty,
    hist_90d_instock_days,
    hist_90d_instock_sales,
    hist_90d_instock_daily_sales,
    history_recovery_need_qty,
    history_recovery_flag,
    support_inventory_qty,
    final_inventory_support_days as inventory_support_days,
    final_arrival_inventory_support_days as arrival_inventory_support_days,
    final_arrival_inventory_qty as arrival_inventory_qty,
    final_lead_time_demand_qty as lead_time_demand_qty,
    final_base_replenish_need_qty as base_replenish_need_qty,
    final_lead_adjusted_replenish_need_qty as lead_adjusted_replenish_need_qty,
    final_lead_time_stockout_flag as lead_time_stockout_flag,
    final_lead_time_stockout_days as lead_time_stockout_days,
    final_lead_time_lost_sales_qty as lead_time_lost_sales_qty,
    final_support_replenish_level as support_replenish_level,
    final_support_replenish_level_sort as support_replenish_level_sort,
    case
        when adjusted_daily_sales_30d >= 5 and pprofit_ratio_30 >= 0.15 then '明星产品'
        when adjusted_daily_sales_30d >= 1 and adjusted_daily_sales_30d < 5 and pprofit_ratio_30 >= 0.25 then '明星产品'
        when adjusted_daily_sales_30d >= 5 and pprofit_ratio_30 >= 0.05 and pprofit_ratio_30 < 0.15 then '潜力产品'
        when adjusted_daily_sales_30d >= 1 and adjusted_daily_sales_30d < 5 and pprofit_ratio_30 >= 0.10 and pprofit_ratio_30 < 0.25 then '潜力产品'
        when adjusted_daily_sales_30d >= 1 and adjusted_daily_sales_30d < 5 and pprofit_ratio_30 >= 0.05 and pprofit_ratio_30 < 0.10 then '瘦狗产品'
        when adjusted_daily_sales_30d < 1 and pprofit_ratio_30 >= 0.05 then '瘦狗产品'
        when adjusted_daily_sales_30d = 0 or (adjusted_daily_sales_30d > 1 and pprofit_ratio_30 < 0.05) then '问题产品'
        else '问题产品'
    end as abcd_category,
    case
        when pprofit_ratio_30 >= 0.15 then '>=15%%'
        when pprofit_ratio_30 >= 0.10 then '10%%-15%%'
        when pprofit_ratio_30 >= 0.05 then '5%%-10%%'
        when pprofit_ratio_30 >= 0 then '0%%-5%%'
        else '<0%%'
    end as gp_margin_range,
    case
        when pprofit_ratio_7 >= 0.15 and sales_7 >= 7 then 'A'
        when pprofit_ratio_7 >= 0.10 and sales_7 >= 3 then 'B'
        when pprofit_ratio_7 >= 0.05 then 'C'
        when pprofit_ratio_7 >= 0 then 'D'
        else 'E'
    end as predict_abcd_category,
    total + local_quantity as fba_local_quantity,
    total,
    available_total,
    afn_fulfillable_quantity,
    stock_up_num,
    afn_unsellable_quantity,
    sc_quantity_local_valid,
    sc_quantity_purchase_shipping,
    sc_quantity_purchase_plan,
    sc_quantity_local_qc,
    local_quantity,
    r_180d_salable_days,
    r_90d_salable_days,
    result_r_30d_salable_days as r_30d_salable_days,
    result_r_14d_salable_days as r_14d_salable_days,
    result_r_7d_salable_days as r_7d_salable_days,
    result_r_3d_salable_days as r_3d_salable_days,
    sales_180 as sales_180d,
    sales_90 as sales_90d,
    final_sales_30 as final_sales_30d,
    final_sales_14 as final_sales_14d,
    final_sales_7 as final_sales_7d,
    final_sales_3 as final_sales_3d,
    amount_180 as amount_180d,
    amount_90 as amount_90d,
    amount_30 as amount_30d,
    amount_14 as amount_14d,
    amount_7 as amount_7d,
    amount_3 as amount_3d,
    pprofit_180 as pprofit_180d,
    pprofit_90 as pprofit_90d,
    pprofit_30 as pprofit_30d,
    pprofit_14 as pprofit_14d,
    pprofit_7 as pprofit_7d,
    pprofit_3 as pprofit_3d,
    pprofit_ratio_180 as pprofit_ratio_180d,
    pprofit_ratio_90 as pprofit_ratio_90d,
    pprofit_ratio_30 as pprofit_ratio_30d,
    pprofit_ratio_14 as pprofit_ratio_14d,
    pprofit_ratio_7 as pprofit_ratio_7d,
    pprofit_ratio_3 as pprofit_ratio_3d,
    case
        when max_brand_name like '%%2025%%' and (receiving_cnt <= 1 or receiving_cnt is null) then '2025新品'
        when max_brand_name like '%%2026%%' and (receiving_cnt <= 1 or receiving_cnt is null) then '2026新品'
        else '老品'
    end as new_old_prod_jg,
    daily_avg_sales,
    pre_replenish_comp_months as replenish_comp_months,
    case when daily_avg_sales <= 0 then null else (total + local_quantity) / daily_avg_sales end as salable_days,
    60 * daily_avg_sales - (total + local_quantity) as `60d_stocko_qty`,
    90 * daily_avg_sales - (total + local_quantity) as `90d_stocko_qty`,
    180 * daily_avg_sales - (total + local_quantity) as `180d_stocko_qty`,
    normal_replenish_need_qty as replenish_dur_calc_stocko_qty,
    case when support_replenish_level_sort in (1, 2, 3) then normal_replenish_need_qty else 0 end as replenish_need_qty,
    pre_replenish_trigger_qty as replenish_trigger_qty,
    sales_change_rate_adj,
    sales_adj_factor,
    final_profit_rate,
    case when coalesce(followed_flag, 0) = 1 then 0
        when coalesce(asin_merge_flag, 0) = 1 and coalesce(asin_merge_target_flag, 0) = 0 then 0
        when coalesce(asin_merge_flag, 0) = 1 and asin_merge_reason = '同ASIN库存充足不补货' then 0
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(group_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1) * effective_max_cg_box_pcs
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then greatest(round(group_replenish_need_qty * sales_adj_factor, 0), 50)
        when support_replenish_level_sort in (1, 2, 3) and coalesce(history_recovery_flag, 0) = 1
            then case when coalesce(effective_max_cg_box_pcs, 0) > 0 then effective_max_cg_box_pcs else 50 end
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(normal_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1) * effective_max_cg_box_pcs
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then greatest(round(normal_replenish_need_qty * sales_adj_factor, 0), 50)
        else 0
    end as replenish_qty,
    case when coalesce(followed_flag, 0) = 1 then 0
        when coalesce(asin_merge_flag, 0) = 1 and coalesce(asin_merge_target_flag, 0) = 0 then 0
        when coalesce(asin_merge_flag, 0) = 1 and asin_merge_reason = '同ASIN库存充足不补货' then 0
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(group_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1)
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then 0
        when support_replenish_level_sort in (1, 2, 3) and coalesce(history_recovery_flag, 0) = 1
            then case when coalesce(effective_max_cg_box_pcs, 0) > 0 then 1 else 0 end
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(normal_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1)
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then 0
        else null
    end as replenish_box_qty,
    case when coalesce(followed_flag, 0) = 1 then 0
        when coalesce(asin_merge_flag, 0) = 1 and coalesce(asin_merge_target_flag, 0) = 0 then 0
        when coalesce(asin_merge_flag, 0) = 1 and asin_merge_reason = '同ASIN库存充足不补货' then 0
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(group_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1) * effective_max_cg_box_pcs
                 * (effective_max_cg_price + effective_max_cg_transport_costs)
        when coalesce(asin_merge_flag, 0) = 1
             and coalesce(asin_merge_target_flag, 0) = 1
             and group_support_replenish_level_sort in (1, 2, 3)
             and group_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then greatest(round(group_replenish_need_qty * sales_adj_factor, 0), 50)
                 * (effective_max_cg_price + effective_max_cg_transport_costs)
        when support_replenish_level_sort in (1, 2, 3) and coalesce(history_recovery_flag, 0) = 1
            then (case when coalesce(effective_max_cg_box_pcs, 0) > 0 then effective_max_cg_box_pcs else 50 end)
                 * (effective_max_cg_price + effective_max_cg_transport_costs)
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and effective_max_cg_box_pcs > 0
            then greatest(round(normal_replenish_need_qty * sales_adj_factor / effective_max_cg_box_pcs, 0), 1) * effective_max_cg_box_pcs
                 * (effective_max_cg_price + effective_max_cg_transport_costs)
        when support_replenish_level_sort in (1, 2, 3) and normal_replenish_need_qty > 0
             and (effective_max_cg_box_pcs = 0 or effective_max_cg_box_pcs is null)
            then greatest(round(normal_replenish_need_qty * sales_adj_factor, 0), 50)
                 * (effective_max_cg_price + effective_max_cg_transport_costs)
        else 0
    end as replenish_cost,
    case when sales_30 = 0 then null else available_total / sales_30 end as amz_instock_sales_ratio,
    case when sales_30 = 0 then null else (total + local_quantity) / sales_30 end as instock_intrans_pur_sales_ratio,
    fllow_flag,
    coalesce(followed_flag, 0) as followed_flag,
    coalesce(followed_by_count, 0) as followed_by_count,
    followed_by_links,
    follow_origin_link,
    case
        when coalesce(followed_flag, 0) = 1 then '被跟卖点不补货'
        when coalesce(asin_merge_flag, 0) = 1 then asin_merge_reason
        else null
    end as replenish_block_reason,
    coalesce(asin_merge_flag, 0) as asin_merge_flag,
    asin_merge_target,
    asin_merge_reason
from (
    select
        calc.*,
        coalesce(assign.asin_merge_flag, 0) as asin_merge_flag,
        assign.asin_merge_target,
        assign.asin_merge_reason,
        coalesce(assign.asin_merge_target_flag, 0) as asin_merge_target_flag,
        assign.group_replenish_need_qty,
        assign.group_effective_purchase_lead_days,
        assign.group_inventory_support_days,
        assign.group_arrival_inventory_support_days,
        assign.group_arrival_inventory_qty,
        assign.group_lead_time_demand_qty,
        assign.group_base_replenish_need_qty,
        assign.group_lead_adjusted_replenish_need_qty,
        assign.group_lead_time_stockout_flag,
        assign.group_lead_time_stockout_days,
        assign.group_lead_time_lost_sales_qty,
        assign.group_support_replenish_level_sort,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_inventory_support_days
            else calc.inventory_support_days
        end as final_inventory_support_days,
        case
            when coalesce(assign.asin_merge_target_flag, 0) = 1
                then coalesce(purchase.effective_max_cg_box_pcs, max_cg_box_pcs)
            else max_cg_box_pcs
        end as effective_max_cg_box_pcs,
        case
            when coalesce(assign.asin_merge_target_flag, 0) = 1
                then coalesce(purchase.effective_max_cg_price, max_cg_price)
            else max_cg_price
        end as effective_max_cg_price,
        case
            when coalesce(assign.asin_merge_target_flag, 0) = 1
                then coalesce(purchase.effective_max_cg_transport_costs, max_cg_transport_costs)
            else max_cg_transport_costs
        end as effective_max_cg_transport_costs,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then coalesce(purchase.purchase_lead_days_raw, calc.purchase_lead_days_raw)
            else calc.purchase_lead_days_raw
        end as final_purchase_lead_days_raw,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then coalesce(
                    purchase.effective_purchase_lead_days,
                    assign.group_effective_purchase_lead_days,
                    calc.effective_purchase_lead_days
                )
            else calc.effective_purchase_lead_days
        end as final_effective_purchase_lead_days,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then coalesce(purchase.purchase_lead_status, calc.purchase_lead_status)
            else calc.purchase_lead_status
        end as final_purchase_lead_status,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_arrival_inventory_support_days
            else calc.arrival_inventory_support_days
        end as final_arrival_inventory_support_days,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_arrival_inventory_qty
            else calc.arrival_inventory_qty
        end as final_arrival_inventory_qty,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_lead_time_demand_qty
            else calc.lead_time_demand_qty
        end as final_lead_time_demand_qty,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_base_replenish_need_qty
            else calc.base_replenish_need_qty
        end as final_base_replenish_need_qty,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_lead_adjusted_replenish_need_qty
            else calc.lead_adjusted_replenish_need_qty
        end as final_lead_adjusted_replenish_need_qty,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_lead_time_stockout_flag
            else calc.lead_time_stockout_flag
        end as final_lead_time_stockout_flag,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_lead_time_stockout_days
            else calc.lead_time_stockout_days
        end as final_lead_time_stockout_days,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then assign.group_lead_time_lost_sales_qty
            else calc.lead_time_lost_sales_qty
        end as final_lead_time_lost_sales_qty,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1 then
                case assign.group_support_replenish_level_sort
                    when 1 then '紧急补货'
                    when 2 then '建议补货'
                    when 3 then '计划补货'
                    when 4 then '库存充足'
                    when 5 then '日销为0'
                    else calc.support_replenish_level
                end
            else calc.support_replenish_level
        end as final_support_replenish_level,
        case
            when coalesce(assign.asin_merge_flag, 0) = 1
                then coalesce(assign.group_support_replenish_level_sort, calc.support_replenish_level_sort)
            else calc.support_replenish_level_sort
        end as final_support_replenish_level_sort
    from tmp_pur_plan_replenish_calc calc
    left join tmp_asin_merge_assignments assign
           on calc.country_category = assign.country_category
          and calc.seller_name_new = assign.seller_name_new
          and calc.seller_sku_adj = assign.seller_sku_adj
    left join tmp_asin_merge_purchase_fields purchase
           on calc.country_category = purchase.country_category
          and calc.max_asin = purchase.max_asin
) merged;
"""

REPLENISHMENT_TEMPORARY_SQL = (
    CHECK_DAILY_SNAPSHOTS_SQL,
    INSERT_SALABLE_DAYS_SQL,
    REPLENISHMENT_RESULT_SQL,
)

MOQ_GATING_SQL = """
drop table if exists tmp_replenishment_moq_gate;
create table tmp_replenishment_moq_gate as
select
    base.*,
    case
        when base.calculated_replenish_qty <= 0 then 'not_applicable'
        when supplier_moq is null or supplier_moq <= 0 then 'unconfigured'
        when calculated_replenish_qty < supplier_moq then 'below_minimum'
        else 'met'
    end as moq_status,
    case
        when base.calculated_replenish_qty > 0 and base.supplier_moq > 0
            then greatest(supplier_moq - calculated_replenish_qty, 0)
        else 0
    end as moq_shortfall_qty
from (
    select
        r.cur_date,
        r.country_category,
        r.seller_name_new,
        r.seller_sku_adj,
        m.supplier_moq,
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then case when coalesce(r.max_cg_box_pcs, 0) > 0 then r.max_cg_box_pcs else 50 end
            else coalesce(r.replenish_qty, 0)
        end as calculated_replenish_qty,
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then case when coalesce(r.max_cg_box_pcs, 0) > 0 then 1 else 0 end
            else coalesce(r.replenish_box_qty, 0)
        end as calculated_replenish_box_qty,
        case
            when coalesce(r.history_recovery_flag, 0) = 1
             and coalesce(r.support_replenish_level_sort, 99) not in (1, 2, 3)
             and coalesce(r.replenish_block_reason, '') <> '被跟卖点不补货'
             and not (coalesce(r.asin_merge_flag, 0) = 1 and coalesce(r.replenish_qty, 0) = 0)
                then (case when coalesce(r.max_cg_box_pcs, 0) > 0 then r.max_cg_box_pcs else 50 end)
                   * (coalesce(r.max_cg_price, 0) + coalesce(r.max_cg_transport_costs, 0))
            else coalesce(r.replenish_cost, 0)
        end as calculated_replenish_cost
    from etl_datasync_test.dashboard_pur_plan_replenish_data r
    left join etl_datasync_test.dashboard_replenishment_supplier_moq_sync m
           on m.snapshot_date = r.cur_date
          and binary m.sku = binary r.max_sku
    where r.cur_date = %(snapshot_date)s
) base;

update etl_datasync_test.dashboard_pur_plan_replenish_data r
inner join tmp_replenishment_moq_gate g
        on g.cur_date = r.cur_date
       and g.country_category = r.country_category
       and g.seller_name_new = r.seller_name_new
       and g.seller_sku_adj = r.seller_sku_adj
set r.supplier_moq = g.supplier_moq,
    r.moq_status = g.moq_status,
    r.calculated_replenish_qty = g.calculated_replenish_qty,
    r.calculated_replenish_box_qty = g.calculated_replenish_box_qty,
    r.calculated_replenish_cost = g.calculated_replenish_cost,
    r.executable_replenish_qty = case when g.moq_status = 'below_minimum' then 0 else g.calculated_replenish_qty end,
    r.executable_replenish_box_qty = case when g.moq_status = 'below_minimum' then 0 else g.calculated_replenish_box_qty end,
    r.executable_replenish_cost = case when g.moq_status = 'below_minimum' then 0 else g.calculated_replenish_cost end,
    r.moq_shortfall_qty = g.moq_shortfall_qty
where r.cur_date = %(snapshot_date)s;
"""

DELETE_COUNTRY_METRICS_SQL = """
delete from etl_datasync_test.dashboard_replenishment_country_metrics
where snapshot_date = %(snapshot_date)s
"""

DROP_COUNTRY_LISTING_PRICE_SQL = """
drop temporary table if exists tmp_replenishment_country_listing_price
"""

CREATE_COUNTRY_LISTING_PRICE_SQL = """
create temporary table tmp_replenishment_country_listing_price (
    country_category varchar(64) not null,
    seller_name_new varchar(128) not null,
    country varchar(64) not null,
    seller_sku varchar(128) not null,
    price decimal(18,4) null,
    primary key (country_category, seller_name_new, country, seller_sku)
) engine=InnoDB
"""

INSERT_COUNTRY_LISTING_PRICE_SQL = """
insert into tmp_replenishment_country_listing_price (
    country_category,
    seller_name_new,
    country,
    seller_sku,
    price
)
select
    country_category,
    seller_name_new,
    country,
    seller_sku,
    max(price) as price
from etl_datasync_test.dashboard_listing_price_daily_snapshot
where snapshot_date = %(snapshot_date)s
group by country_category, seller_name_new, country, seller_sku
"""

BUILD_COUNTRY_METRICS_SQL = """
insert into etl_datasync_test.dashboard_replenishment_country_metrics (
    snapshot_date,
    period_days,
    period_start,
    period_end,
    country_category,
    country,
    seller_name_new,
    seller_sku_adj,
    local_sku_list,
    listing_price,
    sales_qty,
    natural_daily_sales,
    salable_days,
    salable_daily_sales,
    sales_amount,
    order_gross_profit,
    order_gross_margin,
    avg_ranking,
    best_ranking,
    worst_ranking,
    sessions_total,
    conversion_rate,
    ad_spend,
    ad_orders,
    ad_sales,
    ad_clicks,
    ad_impressions,
    acos,
    ctr,
    created_at,
    updated_at
)
select
    %(snapshot_date)s as snapshot_date,
    period_def.period_days,
    date_sub(%(biz_date)s, interval period_def.period_days - 1 day) as period_start,
    %(biz_date)s as period_end,
    p.country_category,
    coalesce(nullif(p.country, ''), '-') as country,
    p.seller_name_new,
    p.seller_sku_adj,
    group_concat(distinct nullif(p.local_sku, '') order by nullif(p.local_sku, '') separator ',') as local_sku_list,
    null as listing_price,
    sum(coalesce(p.sales_qty, 0)) as sales_qty,
    sum(coalesce(p.sales_qty, 0)) / period_def.period_days as natural_daily_sales,
    sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end) as salable_days,
    sum(coalesce(p.sales_qty, 0))
        / nullif(sum(case when coalesce(p.afn_fulfillable_quantity, 0) > 0 then 1 else 0 end), 0) as salable_daily_sales,
    sum(coalesce(p.sales_amount, 0)) as sales_amount,
    sum(coalesce(p.order_gross_profit, 0)) as order_gross_profit,
    sum(coalesce(p.order_gross_profit, 0)) / nullif(sum(coalesce(p.sales_amount, 0)), 0) as order_gross_margin,
    avg(case when p.dt_date = %(biz_date)s then nullif(p.ranking, 0) end) as avg_ranking,
    min(nullif(p.ranking, 0)) as best_ranking,
    max(nullif(p.ranking, 0)) as worst_ranking,
    sum(coalesce(p.sessions_total, 0)) as sessions_total,
    sum(coalesce(p.sales_qty, 0)) / nullif(sum(coalesce(p.sessions_total, 0)), 0) as conversion_rate,
    sum(coalesce(p.ad_spend, 0)) as ad_spend,
    sum(coalesce(p.ad_orders, 0)) as ad_orders,
    sum(coalesce(p.ad_sales, 0)) as ad_sales,
    sum(coalesce(p.ad_clicks, 0)) as ad_clicks,
    sum(coalesce(p.ad_impressions, 0)) as ad_impressions,
    sum(coalesce(p.ad_spend, 0)) / nullif(sum(coalesce(p.ad_sales, 0)), 0) as acos,
    sum(coalesce(p.ad_clicks, 0)) / nullif(sum(coalesce(p.ad_impressions, 0)), 0) as ctr,
    now(),
    now()
from (
    select 7 as period_days
    union all select 14
    union all select 30
    union all select 90
    union all select 180
) period_def
inner join etl_datasync_test.dashboard_product_performance_daily p
        on p.dt_date between date_sub(%(biz_date)s, interval period_def.period_days - 1 day)
                         and %(biz_date)s
inner join etl_datasync_test.dashboard_pur_plan_replenish_data r
        on r.cur_date = %(snapshot_date)s
       and r.country_category = p.country_category
       and r.seller_name_new = p.seller_name_new
       and r.seller_sku_adj = p.seller_sku_adj
where period_def.period_days in (7, 14, 30, 90, 180)
group by
    period_def.period_days,
    p.country_category,
    coalesce(nullif(p.country, ''), '-'),
    p.seller_name_new,
    p.seller_sku_adj
"""

UPDATE_COUNTRY_METRICS_LISTING_PRICE_SQL = """
update etl_datasync_test.dashboard_replenishment_country_metrics m
left join tmp_replenishment_country_listing_price lp
       on lp.country_category = m.country_category
      and lp.seller_name_new = m.seller_name_new
      and lp.country = m.country
      and binary lp.seller_sku = binary m.seller_sku_adj
set m.listing_price = lp.price
where m.snapshot_date = %(snapshot_date)s
"""

STEPS = {
    "listing_basic_sync": SourceLoadStep(
        "listing_basic_sync",
        DELETE_LISTING_BASIC_SYNC_SQL,
        SELECT_LISTING_BASIC_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_listing_basic_sync",
        LISTING_BASIC_COLUMNS,
    ),
    "self_asin_sync": SourceLoadStep(
        "self_asin_sync",
        DELETE_SELF_ASIN_SYNC_SQL,
        SELECT_SELF_ASIN_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_self_asin_sync",
        SELF_ASIN_COLUMNS,
    ),
    "fba_shipment_sync": SourceLoadStep(
        "fba_shipment_sync",
        DELETE_FBA_SHIPMENT_SYNC_SQL,
        SELECT_FBA_SHIPMENT_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_fba_shipment_sync",
        FBA_SHIPMENT_COLUMNS,
    ),
    "order_profit_source_sync": SourceLoadStep(
        "order_profit_source_sync",
        DELETE_ORDER_PROFIT_SOURCE_SYNC_SQL,
        SELECT_ORDER_PROFIT_SOURCE_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_order_profit_source",
        ORDER_PROFIT_SOURCE_COLUMNS,
    ),
    "supplier_moq_sync": SourceLoadStep(
        "supplier_moq_sync",
        DELETE_SUPPLIER_MOQ_SYNC_SQL,
        SELECT_SUPPLIER_MOQ_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_supplier_moq_sync",
        SUPPLIER_MOQ_COLUMNS,
    ),
    "history_daily_sync": SourceLoadStep(
        "history_daily_sync",
        DELETE_HISTORY_DAILY_SYNC_SQL,
        SELECT_HISTORY_DAILY_SYNC_SQL,
        "etl_datasync_test.dashboard_replenishment_history_daily_sync",
        HISTORY_DAILY_COLUMNS,
    ),
    "check_daily_snapshots": ReplenishmentStep("check_daily_snapshots", (CHECK_DAILY_SNAPSHOTS_SQL,)),
    "salable_days_stat": ReplenishmentStep("salable_days_stat", (DELETE_SALABLE_DAYS_SQL, INSERT_SALABLE_DAYS_SQL)),
    "replenishment_result": ReplenishmentStep(
        "replenishment_result",
        tuple(statement.strip() + ";" for statement in REPLENISHMENT_RESULT_SQL.split(";") if statement.strip()),
    ),
    "moq_gating": ReplenishmentStep(
        "moq_gating",
        tuple(statement.strip() + ";" for statement in MOQ_GATING_SQL.split(";") if statement.strip()),
    ),
    "country_metrics": ReplenishmentStep(
        "country_metrics",
        (
            DELETE_COUNTRY_METRICS_SQL,
            DROP_COUNTRY_LISTING_PRICE_SQL,
            CREATE_COUNTRY_LISTING_PRICE_SQL,
            INSERT_COUNTRY_LISTING_PRICE_SQL,
            BUILD_COUNTRY_METRICS_SQL,
            UPDATE_COUNTRY_METRICS_LISTING_PRICE_SQL,
        ),
    ),
}


def default_biz_date() -> date:
    return date.today() - timedelta(days=1)


def subtract_one_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def iter_history_source_ranges(start_date: date, end_date: date):
    year = start_date.year
    while year <= end_date.year:
        if year not in HISTORY_SOURCE_TABLES:
            raise RuntimeError(f"No history source table configured for year {year}")
        yield (
            HISTORY_SOURCE_TABLES[year],
            max(start_date, date(year, 1, 1)),
            min(end_date, date(year, 12, 31)),
        )
        year += 1


def build_params(args: argparse.Namespace) -> dict[str, object]:
    candidate_days = int(args.candidate_days or DEFAULT_CANDIDATE_DAYS)
    if candidate_days < 1:
        raise SystemExit("candidate_days must be at least 1")
    biz_date = parse_day(args.biz_date) if args.biz_date else default_biz_date()
    snapshot_date = parse_day(args.snapshot_date) if args.snapshot_date else date.today()
    history_year = subtract_one_year(biz_date).year
    history_start_date = (
        parse_day(getattr(args, "history_start_date", None))
        if getattr(args, "history_start_date", None)
        else date(history_year, 1, 1) - timedelta(days=90)
    )
    history_end_date = (
        parse_day(getattr(args, "history_end_date", None))
        if getattr(args, "history_end_date", None)
        else date(history_year, 12, 31) + timedelta(days=90)
    )
    return {
        "biz_date": biz_date,
        "snapshot_date": snapshot_date,
        "next_snapshot_date": snapshot_date + timedelta(days=1),
        "period_start": biz_date - timedelta(days=89),
        "period_end": biz_date,
        "product_start_date": biz_date - timedelta(days=179),
        "candidate_start_date": biz_date - timedelta(days=candidate_days - 1),
        "candidate_days": candidate_days,
        "history_start_date": history_start_date,
        "history_end_date": history_end_date,
    }


def render_replenishment_sql(sql: str, schemas: SchemaConfig) -> str:
    rendered = render_sql(sql, schemas)
    rendered = rendered.replace("etl_datasync_test.pur_plan_", f"{schemas.target_schema}.pur_plan_")
    rendered = rendered.replace("etl_datasync.pur_plan_", f"{schemas.target_schema}.pur_plan_")
    return rendered


def split_sql_statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def render_replenishment_work_sql(sql: str, schemas: SchemaConfig) -> str:
    rendered = render_replenishment_sql(sql, schemas)
    for temporary_name, work_table in REPLENISHMENT_WORK_TABLES.items():
        rendered_work_table = render_replenishment_sql(work_table, schemas)
        rendered = re.sub(rf"\b{re.escape(temporary_name)}\b", rendered_work_table, rendered)
    return rendered


def render_replenishment_work_table(temporary_name: str, schemas: SchemaConfig) -> str:
    try:
        work_table = REPLENISHMENT_WORK_TABLES[temporary_name]
    except KeyError as exc:
        raise KeyError(f"Missing replenishment work table mapping for {temporary_name}") from exc
    return render_replenishment_sql(work_table, schemas)


def build_replenishment_result_statements(schemas: SchemaConfig) -> list[str]:
    statements = split_sql_statements(REPLENISHMENT_RESULT_SQL)
    expanded: list[str] = []
    for statement in statements:
        drop_match = re.fullmatch(r"drop\s+temporary\s+table\s+if\s+exists\s+(\w+)", statement, re.IGNORECASE)
        if drop_match:
            render_replenishment_work_table(drop_match.group(1), schemas)
            continue

        create_match = re.fullmatch(
            r"create\s+temporary\s+table\s+(\w+)\s+as\s+(.*)",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if create_match:
            temporary_name = create_match.group(1)
            work_table = render_replenishment_work_table(temporary_name, schemas)
            select_sql = render_replenishment_work_sql(create_match.group(2), schemas)
            expanded.extend(
                [
                    f"drop table if exists {work_table}",
                    f"create table {work_table} as select * from ({select_sql}) as seed where 1 = 0",
                    f"insert into {work_table}\n{select_sql}",
                ]
            )
            continue

        explicit_create_match = re.fullmatch(
            r"create\s+temporary\s+table\s+(\w+)\s*(\(.*)",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if explicit_create_match:
            temporary_name = explicit_create_match.group(1)
            work_table = render_replenishment_work_table(temporary_name, schemas)
            definition_sql = render_replenishment_work_sql(explicit_create_match.group(2), schemas)
            expanded.extend(
                [
                    f"drop table if exists {work_table}",
                    f"create table {work_table} {definition_sql}",
                ]
            )
            continue

        expanded.append(render_replenishment_work_sql(statement, schemas))
    return expanded


def parse_steps(raw_steps: str) -> list[str]:
    if raw_steps == "all":
        return DEFAULT_STEP_ORDER[:]
    step_names = [name.strip() for name in raw_steps.split(",") if name.strip()]
    unknown = [name for name in step_names if name not in STEPS]
    if unknown:
        raise SystemExit(f"Unknown step(s): {', '.join(unknown)}")
    return step_names


def ensure_tables(conn, schemas: SchemaConfig) -> None:
    with conn.cursor() as cursor:
        for statement in DDL_STATEMENTS:
            cursor.execute(render_replenishment_sql(statement, schemas))
        ensure_replenishment_columns(cursor, schemas)
    conn.commit()


def ensure_replenishment_columns(cursor, schemas: SchemaConfig) -> None:
    column_specs = {
        "dashboard_replenishment_country_metrics": [
            ("listing_price", "decimal(18,4) null", "local_sku_list"),
        ],
        "pur_plan_prod_perf_salable_days_stat": [
            ("r_180d_salable_days", "int not null default 0", "seller_sku_adj"),
        ],
        "dashboard_replenishment_listing_basic_sync": [
            ("global_tags", "text null", "marketplace_concat"),
            ("max_cg_delivery", "decimal(10,2) null", "max_cg_box_pcs"),
        ],
        "dashboard_pur_plan_replenish_data": [
            ("global_tags", "text null", "marketplace_concat"),
            ("r_180d_salable_days", "int null", "local_quantity"),
            ("sales_180d", "decimal(18,4) null", "r_3d_salable_days"),
            ("amount_180d", "decimal(18,4) null", "final_sales_3d"),
            ("amount_90d", "decimal(18,4) null", "amount_180d"),
            ("pprofit_180d", "decimal(18,4) null", "amount_3d"),
            ("pprofit_90d", "decimal(18,4) null", "pprofit_180d"),
            ("pprofit_ratio_180d", "decimal(10,6) null", "pprofit_3d"),
            ("pprofit_ratio_90d", "decimal(10,6) null", "pprofit_ratio_180d"),
            ("followed_flag", "tinyint not null default 0", "fllow_flag"),
            ("followed_by_count", "int not null default 0", "followed_flag"),
            ("followed_by_links", "text null", "followed_by_count"),
            ("follow_origin_link", "varchar(255) null", "followed_by_links"),
            ("replenish_block_reason", "varchar(64) null", "follow_origin_link"),
            ("asin_merge_flag", "tinyint not null default 0", "replenish_block_reason"),
            ("asin_merge_target", "varchar(255) null", "asin_merge_flag"),
            ("asin_merge_reason", "varchar(64) null", "asin_merge_target"),
            ("purchase_lead_days_raw", "decimal(10,2) null", "max_cg_transport_costs"),
            ("effective_purchase_lead_days", "decimal(10,2) not null default 0", "purchase_lead_days_raw"),
            ("purchase_lead_status", "varchar(32) not null default 'unconfigured'", "effective_purchase_lead_days"),
            ("arrival_inventory_support_days", "decimal(18,6) null", "inventory_support_days"),
            ("arrival_inventory_qty", "decimal(18,4) null", "arrival_inventory_support_days"),
            ("lead_time_demand_qty", "decimal(18,4) null", "arrival_inventory_qty"),
            ("base_replenish_need_qty", "decimal(18,4) null", "lead_time_demand_qty"),
            ("lead_adjusted_replenish_need_qty", "decimal(18,4) null", "base_replenish_need_qty"),
            ("lead_time_stockout_flag", "tinyint not null default 0", "lead_adjusted_replenish_need_qty"),
            ("lead_time_stockout_days", "decimal(18,6) null", "lead_time_stockout_flag"),
            ("lead_time_lost_sales_qty", "decimal(18,4) null", "lead_time_stockout_days"),
            ("supplier_moq", "decimal(18,4) null", "replenish_cost"),
            ("moq_status", "varchar(32) null", "supplier_moq"),
            ("calculated_replenish_qty", "decimal(18,4) null", "moq_status"),
            ("calculated_replenish_box_qty", "decimal(18,4) null", "calculated_replenish_qty"),
            ("calculated_replenish_cost", "decimal(18,4) null", "calculated_replenish_box_qty"),
            ("executable_replenish_qty", "decimal(18,4) null", "calculated_replenish_cost"),
            ("executable_replenish_box_qty", "decimal(18,4) null", "executable_replenish_qty"),
            ("executable_replenish_cost", "decimal(18,4) null", "executable_replenish_box_qty"),
            ("moq_shortfall_qty", "decimal(18,4) null", "executable_replenish_cost"),
            ("sales_spike_status", "varchar(32) not null default 'normal'", "asin_merge_reason"),
            ("sales_spike_flag", "tinyint not null default 0", "sales_spike_status"),
            ("sales_spike_date", "date null", "sales_spike_flag"),
            ("sales_spike_qty", "decimal(18,4) null", "sales_spike_date"),
            ("sales_spike_baseline", "decimal(18,6) null", "sales_spike_qty"),
            ("sales_spike_score", "decimal(18,6) null", "sales_spike_baseline"),
            ("sales_spike_reason", "varchar(500) null", "sales_spike_score"),
        ],
    }
    for table_name, columns in column_specs.items():
        cursor.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = %(schema)s
              and table_name = %(table)s
            """,
            {"schema": schemas.target_schema, "table": table_name},
        )
        existing = {
            next(iter(row.values())) if isinstance(row, dict) else row[0]
            for row in cursor.fetchall()
        }
        for column_name, definition, after_column in columns:
            if column_name in existing:
                continue
            cursor.execute(
                f"alter table `{schemas.target_schema}`.`{table_name}` "
                f"add column `{column_name}` {definition} after `{after_column}`"
            )
            existing.add(column_name)


def check_daily_snapshots(conn, schemas: SchemaConfig, params: dict[str, object]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(render_replenishment_sql(CHECK_DAILY_SNAPSHOTS_SQL, schemas), params)
        row = cursor.fetchone() or {}
    inventory_rows = int(row.get("inventory_rows") or 0)
    restock_rows = int(row.get("restock_rows") or 0)
    if inventory_rows <= 0 or restock_rows <= 0:
        raise RuntimeError(
            "Missing daily snapshots for snapshot_date="
            f"{params['snapshot_date']}: inventory_rows={inventory_rows}, restock_rows={restock_rows}"
        )
    print(
        "[success] check_daily_snapshots: "
        f"inventory_rows={inventory_rows}, restock_rows={restock_rows}"
    )


def validate_replenishment_result(
    conn,
    schemas: SchemaConfig,
    params: dict[str, object],
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            render_replenishment_sql(
                """
                select count(*) as row_count
                from etl_datasync_test.dashboard_pur_plan_replenish_data
                where cur_date = %(snapshot_date)s
                """,
                schemas,
            ),
            params,
        )
        row = cursor.fetchone() or {}
    row_count = int(row.get("row_count") or 0)
    if row_count <= 0:
        raise RuntimeError(
            "Business result validation failed: "
            f"replenishment snapshot_date={params['snapshot_date']} has 0 rows "
            f"for biz_date={params['biz_date']}."
        )
    print(
        "[success] replenishment_business_result: "
        f"snapshot_date={params['snapshot_date']} rows={row_count}"
    )
    return row_count


def execute_sql_step(conn, schemas: SchemaConfig, step: ReplenishmentStep, params: dict[str, object]) -> None:
    if step.name == "check_daily_snapshots":
        check_daily_snapshots(conn, schemas, params)
        return

    started_at = datetime.now()
    affected_rows = 0
    try:
        with conn.cursor() as cursor:
            statements = (
                build_replenishment_result_statements(schemas)
                if step.name == "replenishment_result"
                else [render_replenishment_sql(statement, schemas) for statement in step.statements]
            )
            for statement in statements:
                cursor.execute(statement, params)
                if statement.lstrip().lower().startswith(("insert", "delete")):
                    affected_rows += max(cursor.rowcount, 0)
                conn.commit()
        if step.name == "replenishment_result":
            try:
                spike_rows = refresh_replenishment_sales_spike_flags(
                    conn,
                    schemas,
                    snapshot_date=params["snapshot_date"],
                    biz_date=params["biz_date"],
                    calibration_path=Path("config/replenishment_sales_spike.json"),
                )
                print(f"[success] sales_spike_refresh: affected_rows={spike_rows}")
            except SpikeConfigurationError as exc:
                print(f"[warning] sales_spike_refresh skipped: {exc}", file=sys.stderr)
            validate_replenishment_result(conn, schemas, params)
        log_task(conn, schemas, step.name, params, "success", affected_rows, started_at)
        print(f"[success] {step.name}: affected_rows={affected_rows}")
    except Exception:
        conn.rollback()
        error = traceback.format_exc()
        log_task(conn, schemas, step.name, params, "failed", affected_rows, started_at, error)
        print(f"[failed] {step.name}", file=sys.stderr)
        raise


def execute_history_daily_sync_step(
    target_conn,
    source_conn,
    schemas: SchemaConfig,
    step: SourceLoadStep,
    params: dict[str, object],
    batch_size: int,
) -> None:
    started_at = datetime.now()
    affected_rows = 0
    target_insert_sql = build_target_insert_sql(step.target_table, step.target_columns, schemas)

    history_start_date = params["history_start_date"]
    history_end_date = params["history_end_date"]
    if not isinstance(history_start_date, date) or not isinstance(history_end_date, date):
        raise RuntimeError("history_start_date and history_end_date must be dates")

    try:
        with target_conn.cursor() as target_cursor:
            target_cursor.execute(render_sql(step.delete_statement, schemas), params)
        target_conn.commit()

        for source_table, chunk_start, chunk_end in iter_history_source_ranges(history_start_date, history_end_date):
            source_sql = render_sql(
                step.source_select_statement.format(history_source_table=source_table),
                schemas,
            )
            assert_source_select_only(source_sql)
            chunk_params = dict(params)
            chunk_params["history_start_date"] = chunk_start
            chunk_params["history_end_date"] = chunk_end
            chunk_rows = 0
            with source_conn.cursor() as source_cursor, target_conn.cursor() as target_cursor:
                source_cursor.execute(source_sql, chunk_params)
                while True:
                    rows = source_cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    target_cursor.executemany(target_insert_sql, rows)
                    chunk_rows += len(rows)
                    affected_rows += len(rows)
            target_conn.commit()
            print(f"[success] {step.name}: {source_table} {chunk_start}~{chunk_end} rows={chunk_rows}")

        log_task(target_conn, schemas, step.name, params, "success", affected_rows, started_at)
        print(f"[success] {step.name}: affected_rows={affected_rows}")
    except Exception:
        target_conn.rollback()
        error = traceback.format_exc()
        log_task(target_conn, schemas, step.name, params, "failed", affected_rows, started_at, error)
        print(f"[failed] {step.name}", file=sys.stderr)
        raise


def print_plan(step_names: list[str], params: dict[str, object], schemas: SchemaConfig) -> None:
    print("Replenishment local ETL plan")
    print(f"  biz_date        : {params['biz_date']}")
    print(f"  snapshot_date   : {params['snapshot_date']}")
    print(f"  candidate_start : {params['candidate_start_date']}")
    print(f"  product_start   : {params['product_start_date']}")
    print(f"  history_window  : {params['history_start_date']} ~ {params['history_end_date']}")
    print(f"  target_schema   : {schemas.target_schema}")
    print(f"  steps           : {', '.join(step_names)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run replenishment local ETL setup.")
    parser.add_argument("--biz-date", help="Business date, format YYYY-MM-DD. Default: yesterday.")
    parser.add_argument("--snapshot-date", help="Inventory snapshot date, format YYYY-MM-DD. Default: today.")
    parser.add_argument("--candidate-days", type=int, default=DEFAULT_CANDIDATE_DAYS)
    parser.add_argument("--steps", default="all", help="Comma separated step names or all.")
    parser.add_argument("--history-start-date", help="History sync start date, format YYYY-MM-DD.")
    parser.add_argument("--history-end-date", help="History sync end date, format YYYY-MM-DD.")
    parser.add_argument("--skip-ddl", action="store_true", help="Do not create local target tables before running.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per local bulk insert from read-only source.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; do not connect or execute SQL.")
    args = parser.parse_args()

    apply_database_ini_env()
    step_names = parse_steps(args.steps)
    params = build_params(args)
    schemas = build_schema_config()
    print_plan(step_names, params, schemas)

    if args.dry_run:
        return

    conn = connect_target()
    needs_source = any(isinstance(STEPS[step_name], SourceLoadStep) for step_name in step_names)
    source_conn = connect_source() if needs_source else None
    try:
        if not args.skip_ddl:
            ensure_tables(conn, schemas)
            print("[success] ensure_tables")
        for step_name in step_names:
            step = STEPS[step_name]
            if isinstance(step, SourceLoadStep):
                if source_conn is None:
                    raise RuntimeError("Source connection is required for listing_basic_sync")
                if step.name == "history_daily_sync":
                    execute_history_daily_sync_step(conn, source_conn, schemas, step, params, args.batch_size)
                else:
                    execute_source_load_step(conn, source_conn, schemas, step, params, args.batch_size)
            else:
                execute_sql_step(conn, schemas, step, params)
    finally:
        if source_conn is not None:
            source_conn.close()
        conn.close()


if __name__ == "__main__":
    main()
