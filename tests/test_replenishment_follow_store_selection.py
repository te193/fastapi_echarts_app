import re
import sqlite3

import pytest

from etl import replenishment_update as update


def select_for(table):
    prefix = f"create temporary table {table} as"
    statement = next(s for s in update.split_sql_statements(update.REPLENISHMENT_RESULT_SQL) if s.startswith(prefix))
    return statement[len(prefix):].strip()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.create_function("concat", -1, lambda *parts: "".join(str(p) for p in parts))
    conn.create_function("greatest", -1, max)
    conn.execute("attach database ':memory:' as etl_datasync_test")
    conn.executescript("""
        create table etl_datasync_test.dashboard_replenishment_disabled_store_sync (seller_name_new text);
        create table tmp_pur_plan_replenish_calc (
            country_category text, max_asin text, seller_name_new text, seller_sku_adj text,
            fllow_flag integer, followed_flag integer default 0, sales_status text default '在售中',
            sales_30 real default 30, sales_14 real default 14, sales_7 real default 7, sales_3 real default 3,
            result_r_30d_salable_days real default 30, result_r_14d_salable_days real default 14,
            result_r_7d_salable_days real default 7, result_r_3d_salable_days real default 3,
            max_brand_name text default '', receiving_cnt integer default 2,
            pre_replenish_comp_months integer default 4, support_inventory_qty real default 10,
            purchase_lead_days_raw real default 20, effective_purchase_lead_days real default 20,
            max_cg_box_pcs real default 10, max_cg_price real default 5, max_cg_transport_costs real default 1,
            sales_adj_factor real default 1, support_replenish_level_sort integer default 2,
            history_recovery_flag integer default 0, normal_replenish_need_qty real default 100
        );
        create table tmp_asin_merge_latest_performance (
            country_category text, max_asin text, seller_name_new text, seller_sku_adj text, max_perf_date text
        );
    """)
    yield conn
    conn.close()


def add_link(db, store, msku="sku", day="2026-10-07", site="US", asin="ASIN", follow=0):
    db.execute("insert into tmp_pur_plan_replenish_calc (country_category, max_asin, seller_name_new, seller_sku_adj, fllow_flag, followed_flag) values (?, ?, ?, ?, ?, ?)",
               (site, asin, store, msku, follow, 1 if follow else 0))
    db.execute("insert into tmp_asin_merge_latest_performance values (?, ?, ?, ?, ?)", (site, asin, store, msku, day))


def select_targets(db, disabled=()):
    db.executemany("insert into etl_datasync_test.dashboard_replenishment_disabled_store_sync values (?)", [(s.strip().lower(),) for s in disabled])
    db.execute("create table tmp_asin_merge_group_daily_base as " + select_for("tmp_asin_merge_group_daily_base"))
    db.execute("""create table tmp_asin_merge_groups as select *,
        100 as group_replenish_need_qty, 10 as group_inventory_support_days,
        0 as group_arrival_inventory_support_days, 0 as group_arrival_inventory_qty,
        20 as group_lead_time_demand_qty, 100 as group_base_replenish_need_qty,
        100 as group_lead_adjusted_replenish_need_qty, 0 as group_lead_time_stockout_flag,
        0 as group_lead_time_stockout_days, 0 as group_lead_time_lost_sales_qty,
        2 as group_support_replenish_level_sort from tmp_asin_merge_group_daily_base""")
    db.execute("create table tmp_asin_merge_targets as " + select_for("tmp_asin_merge_targets"))
    db.execute("create table tmp_asin_merge_assignments as " + select_for("tmp_asin_merge_assignments"))
    return [dict(row) for row in db.execute("select * from tmp_asin_merge_targets")]


def assigned_quantities(db):
    expression = re.search(r"case when coalesce\(followed_flag, 0\) = 1 then 0.*?end as replenish_qty", update.REPLENISHMENT_RESULT_SQL, re.S).group()
    sql = f"""select seller_name_new, {expression} from (
        select calc.*, assign.asin_merge_flag, assign.asin_merge_target_flag,
               assign.asin_merge_reason, assign.group_replenish_need_qty,
               assign.group_support_replenish_level_sort, calc.max_cg_box_pcs as effective_max_cg_box_pcs
        from tmp_pur_plan_replenish_calc calc join tmp_asin_merge_assignments assign
          using (country_category, max_asin, seller_name_new, seller_sku_adj)
    )"""
    return {row["seller_name_new"]: row["replenish_qty"] for row in db.execute(sql)}


def test_multiple_stores_skip_disabled_latest_link_and_assign_all_qty_to_allowed_store(db):
    add_link(db, "A", follow=1)
    add_link(db, "B", day="2026-10-06")
    add_link(db, "C")
    targets = select_targets(db, disabled=("C",))
    assert [r["target_seller_name_new"] for r in targets] == ["B"]
    assert assigned_quantities(db) == {"A": 0, "B": 100, "C": 0}


def test_only_one_follow_store_keeps_disabled_store_as_target(db):
    add_link(db, "A", follow=1)
    add_link(db, "C")
    assert select_targets(db, disabled=("C",))[0]["target_seller_name_new"] == "C"
    assert assigned_quantities(db) == {"A": 0, "C": 100}


def test_multiple_mskus_in_same_follow_store_keep_original_ranking(db):
    add_link(db, "A", follow=1)
    add_link(db, "C", msku="old", day="2026-10-06")
    add_link(db, "C", msku="new")
    assert select_targets(db, disabled=("C",))[0]["target_seller_sku_adj"] == "new"


def test_all_follow_stores_disabled_have_no_target_and_keep_unassigned_need(db):
    add_link(db, "A", follow=1)
    add_link(db, "B")
    add_link(db, "C")
    assert select_targets(db, disabled=("B", "C")) == []
    assert assigned_quantities(db) == {"A": 0, "B": 0, "C": 0}
    rows = list(db.execute("select * from tmp_asin_merge_assignments"))
    assert {r["asin_merge_reason"] for r in rows} == {"无可承接补货店铺"}
    assert {r["group_replenish_need_qty"] for r in rows} == {100}


def test_allowed_stores_keep_existing_latest_date_priority(db):
    add_link(db, "B", day="2026-10-06")
    add_link(db, "C")
    assert select_targets(db)[0]["target_seller_name_new"] == "C"


def test_follow_store_counts_are_separate_for_each_site(db):
    add_link(db, "B")
    add_link(db, "C")
    add_link(db, "C", site="UK")
    add_link(db, "A", site="UK", follow=1)
    assert {(r["country_category"], r["target_seller_name_new"]) for r in select_targets(db, disabled=("C",))} == {("US", "B"), ("UK", "C")}


def test_disabled_store_source_normalizes_names_and_any_disabled_brand_blocks_store(db):
    db.execute("attach database ':memory:' as opt_db")
    db.execute('create table opt_db.store_brand_relation ("店铺名" text, "是否补货" text)')
    db.executemany("insert into opt_db.store_brand_relation values (?, ?)", [(" C ", " 否 "), ("C", "是"), ("B", "是"), (" ", "否"), ("D", None)])
    sql = update.STEPS["disabled_store_sync"].source_select_statement
    assert [r["seller_name_new"] for r in db.execute(sql)] == ["c"]


@pytest.mark.parametrize("setting, expected_target", [
    (None, "C"),
    ("", "C"),
    ("   ", "C"),
    ("是", "C"),
    (" 否 ", "B"),
])
def test_only_explicit_no_excludes_store_and_empty_setting_can_inherit_qty(db, setting, expected_target):
    db.execute("attach database ':memory:' as opt_db")
    db.execute('create table opt_db.store_brand_relation ("店铺名" text, "是否补货" text)')
    db.executemany("insert into opt_db.store_brand_relation values (?, ?)", [("B", "是"), ("C", setting)])
    disabled = [row["seller_name_new"] for row in db.execute(update.SELECT_DISABLED_STORE_SYNC_SQL)]
    add_link(db, "A", follow=1)
    add_link(db, "B", day="2026-10-06")
    add_link(db, "C")
    db.execute("update tmp_pur_plan_replenish_calc set sales_status = '停售中' where seller_name_new = 'C'")
    assert select_targets(db, disabled)[0]["target_seller_name_new"] == expected_target
    quantities = assigned_quantities(db)
    assert quantities[expected_target] == 100
    assert sum(quantities.values()) == 100


def test_disabled_store_sync_is_available_before_result_and_in_test_copy_plan():
    from etl.replenishment_test_db import COPY_TABLES

    steps = update.DEFAULT_STEP_ORDER
    assert steps.index("disabled_store_sync") < steps.index("replenishment_result")
    assert update.STEPS["disabled_store_sync"].target_table in "\n".join(update.DDL_STATEMENTS)
    assert "dashboard_replenishment_disabled_store_sync" in {item.table for item in COPY_TABLES}


def test_no_allowed_store_reason_is_preserved_in_page_display(db):
    from app.services.replenishment_data import ReplenishmentDataService

    add_link(db, "B")
    add_link(db, "C")
    select_targets(db, disabled=("B", "C"))
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    for expression in (service._display_block_reason_expr(), service._display_asin_merge_reason_expr()):
        params = {name: "other reason" for name in re.findall(r"%\((\w+)\)s", expression)}
        expression = re.sub(r"%\((\w+)\)s", r":\1", expression)
        rows = db.execute(f"select {expression} from (select *, 0 as replenish_qty, asin_merge_reason as replenish_block_reason from tmp_asin_merge_assignments)", params)
        assert {row[0] for row in rows} == {"无可承接补货店铺"}
