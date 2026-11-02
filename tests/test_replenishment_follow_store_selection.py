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
        create table etl_datasync_test.dashboard_replenishment_clearance_sync (msku text, store text);
        create table tmp_pur_plan_replenish_calc (
            country_category text, max_asin text, seller_name_new text, seller_sku_adj text,
            fllow_flag integer, followed_flag integer default 0, sales_status text default '在售中',
            sales_30 real default 30, sales_14 real default 14, sales_7 real default 7, sales_3 real default 3,
            result_r_30d_salable_days real default 30, result_r_14d_salable_days real default 14,
            result_r_7d_salable_days real default 7, result_r_3d_salable_days real default 3,
            max_brand_name text default '', receiving_cnt integer default 2,
            pre_replenish_comp_months integer default 4, support_inventory_qty real default 10,
            purchase_lead_days_raw real default 20, effective_purchase_lead_days real default 20,
            purchase_lead_status text default 'configured',
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
    db.execute("create table tmp_asin_merge_purchase_fields as " + select_for("tmp_asin_merge_purchase_fields"))
    return [dict(row) for row in db.execute("select * from tmp_asin_merge_targets")]


def assigned_results(db):
    final = next(s for s in update.split_sql_statements(update.REPLENISHMENT_RESULT_SQL)
                 if s.startswith('insert into etl_datasync_test.dashboard_pur_plan_replenish_data'))
    expressions = [m.group() for m in re.finditer(
        r"case when coalesce\(followed_flag, 0\) = 1.*?"
        r"end as (?:replenish_qty|replenish_box_qty|replenish_cost)\b",
        final, re.S,
    )]
    purchase = re.findall(
        r"case\s+when coalesce\(assign\.asin_merge_target_flag, 0\) = 1.*?"
        r"end as effective_max_cg_(?:box_pcs|price|transport_costs)",
        update.REPLENISHMENT_RESULT_SQL, re.S,
    )
    assert len(expressions) == len(purchase) == 3
    sql = f"""select seller_name_new, {','.join(expressions)} from (
        select calc.*, assign.asin_merge_flag, assign.asin_merge_target_flag,
               assign.asin_merge_reason, assign.group_replenish_need_qty,
               assign.group_support_replenish_level_sort, {','.join(purchase)}
        from tmp_pur_plan_replenish_calc calc join tmp_asin_merge_assignments assign
          using (country_category, max_asin, seller_name_new, seller_sku_adj)
        left join tmp_asin_merge_purchase_fields purchase using (country_category, max_asin)
    )"""
    return {r['seller_name_new']:(r['replenish_qty'],r['replenish_box_qty'],r['replenish_cost'])
            for r in db.execute(sql)}


def assigned_quantities(db):
    return {store:values[0] for store,values in assigned_results(db).items()}


def test_multiple_stores_skip_disabled_latest_link_and_assign_all_qty_to_allowed_store(db):
    add_link(db, "A", follow=1)
    add_link(db, "B", day="2026-10-06")
    add_link(db, "C")
    targets = select_targets(db, disabled=("C",))
    assert [r["target_seller_name_new"] for r in targets] == ["B"]
    assert assigned_quantities(db) == {"A": 0, "B": 100, "C": 0}


def test_only_one_follow_store_disabled_returns_quantity_to_origin(db):
    add_link(db, "A", follow=1)
    add_link(db, "C")
    assert select_targets(db, disabled=("C",))[0]["target_seller_name_new"] == "A"
    assert assigned_quantities(db) == {"A": 100, "C": 0}


def test_multiple_mskus_in_same_follow_store_keep_original_ranking(db):
    add_link(db, "A", follow=1)
    add_link(db, "C", msku="old", day="2026-10-06")
    add_link(db, "C", msku="new")
    assert select_targets(db)[0]["target_seller_sku_adj"] == "new"


def test_all_follow_stores_and_origin_disabled_have_no_target(db):
    add_link(db, "A", follow=1)
    add_link(db, "B")
    add_link(db, "C")
    assert select_targets(db, disabled=("A", "B", "C")) == []
    assert assigned_quantities(db) == {"A": 0, "B": 0, "C": 0}
    rows = list(db.execute("select * from tmp_asin_merge_assignments"))
    assert {r["asin_merge_reason"] for r in rows} == {"无可承接补货店铺"}
    assert {r["group_replenish_need_qty"] for r in rows} == {100}


def test_clearance_appendix_restores_original_target_without_changing_actual_assignments(db):
    add_link(db, 'A', msku='origin', follow=1)
    add_link(db, 'B', msku='allowed', day='2026-10-06')
    add_link(db, 'C', msku='clearance')
    db.execute("insert into etl_datasync_test.dashboard_replenishment_clearance_sync values ('clearance','全部')")
    assert select_targets(db)[0]['target_seller_name_new'] == 'B'
    reference = [dict(row) for row in db.execute(update.clearance_reference_targets_sql())]
    assert reference[0]['target_seller_name_new'] == 'C'
    assert assigned_quantities(db) == {'A': 0, 'B': 100, 'C': 0}


def test_clearance_appendix_preserves_disabled_store_protection(db):
    add_link(db, 'B', msku='allowed', day='2026-10-06')
    add_link(db, 'C', msku='clearance')
    db.execute("insert into etl_datasync_test.dashboard_replenishment_clearance_sync values ('clearance','全部')")
    select_targets(db, disabled=('C',))
    reference = [dict(row) for row in db.execute(update.clearance_reference_targets_sql())]
    assert reference[0]['target_seller_name_new'] == 'B'


def test_allowed_stores_keep_existing_latest_date_priority(db):
    add_link(db, "B", day="2026-10-06")
    add_link(db, "C")
    assert select_targets(db)[0]["target_seller_name_new"] == "C"


def test_clearance_link_cannot_receive_asin_merged_quantity_even_as_only_follow_store(db):
    add_link(db, "A", msku="origin", follow=1)
    add_link(db, "C", msku="clearance")
    db.execute("insert into etl_datasync_test.dashboard_replenishment_clearance_sync values ('clearance','全部')")
    assert select_targets(db)[0]['target_seller_name_new'] == 'A'
    assert assigned_quantities(db) == {"A":100,"C":0}


def test_clearance_link_cannot_win_but_group_sales_and_inventory_are_preserved(db):
    add_link(db,"A",msku="origin",follow=1)
    add_link(db,"B",msku="normal",day="2026-10-06")
    add_link(db,"C",msku="clearance")
    db.execute("insert into etl_datasync_test.dashboard_replenishment_clearance_sync values ('clearance','c')")
    assert select_targets(db)[0]["target_seller_name_new"] == "B"
    assert assigned_quantities(db) == {"A":0,"B":100,"C":0}
    group=db.execute('select group_sales_30,group_support_inventory_qty from tmp_asin_merge_group_daily_base').fetchone()
    assert group['group_sales_30'] == 90 and group['group_support_inventory_qty'] == 30


def test_follow_store_counts_are_separate_for_each_site(db):
    add_link(db, "B")
    add_link(db, "C")
    add_link(db, "C", site="UK")
    add_link(db, "A", site="UK", follow=1)
    assert {(r["country_category"], r["target_seller_name_new"]) for r in select_targets(db, disabled=("C",))} == {("US", "B"), ("UK", "A")}


def test_multiple_follow_stores_all_disabled_keep_original_no_target_rule(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'B')
    add_link(db, 'C')
    assert select_targets(db, disabled=('B', 'C')) == []
    assert assigned_quantities(db) == {'A':0, 'B':0, 'C':0}


def test_allowed_follow_store_is_preferred_even_when_origin_has_newer_performance(db):
    add_link(db, 'A', day='2026-10-08', follow=1)
    add_link(db, 'B', day='2026-10-06')
    assert select_targets(db)[0]['target_seller_name_new'] == 'B'
    assert assigned_quantities(db) == {'A':0, 'B':100}


def test_fallback_uses_original_need_even_when_disabled_follower_stock_makes_group_sufficient(db):
    add_link(db, 'miqiao', 'MQ025a', follow=1)
    add_link(db, 'pingter', 'PT057a')
    db.execute("update tmp_pur_plan_replenish_calc set support_inventory_qty=675 where seller_name_new='pingter'")
    assert select_targets(db, disabled=('pingter',))[0]['target_seller_name_new'] == 'miqiao'
    db.execute('update tmp_asin_merge_groups set group_replenish_need_qty=0,group_support_replenish_level_sort=4')
    db.execute('drop table tmp_asin_merge_assignments')
    db.execute('create table tmp_asin_merge_assignments as '+select_for('tmp_asin_merge_assignments'))
    origin=db.execute("select * from tmp_asin_merge_assignments where seller_name_new='miqiao'").fetchone()
    assert origin['asin_merge_flag'] == 0
    assert origin['asin_merge_target_flag'] == 1
    assert origin['asin_merge_reason'] == '跟卖不补货回退原链接'
    assert assigned_quantities(db) == {'miqiao':100, 'pingter':0}


def test_disabled_origin_and_only_follow_store_produce_no_quantity(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'C')
    assert select_targets(db, disabled=('A', 'C')) == []
    assert assigned_quantities(db) == {'A':0, 'C':0}


def test_clearance_origin_cannot_take_disabled_followers_need(db):
    add_link(db, 'A', msku='origin', follow=1)
    add_link(db, 'C')
    db.execute("insert into etl_datasync_test.dashboard_replenishment_clearance_sync values ('origin','全部')")
    assert select_targets(db, disabled=('C',)) == []
    assert assigned_quantities(db) == {'A':0, 'C':0}


def test_fallback_still_checks_the_origins_own_inventory_layer(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'C')
    db.execute("update tmp_pur_plan_replenish_calc set support_replenish_level_sort=4 where seller_name_new='A'")
    assert select_targets(db, disabled=('C',))[0]['target_seller_name_new'] == 'A'
    assert assigned_quantities(db) == {'A':0, 'C':0}


def test_fallback_box_count_cost_and_reason_use_the_same_original_target(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'C')
    select_targets(db, disabled=('C',))
    assert assigned_results(db) == {'A':(100,10,600), 'C':(0,0,0)}


@pytest.mark.parametrize('history_recovery', [0, 1])
def test_multiple_origins_prefer_one_with_its_own_executable_need(db, history_recovery):
    add_link(db, 'A', day='2026-10-08', follow=1)
    add_link(db, 'B', day='2026-10-06', follow=1)
    add_link(db, 'C')
    db.execute("update tmp_pur_plan_replenish_calc set support_replenish_level_sort=4,normal_replenish_need_qty=0 where seller_name_new='A'")
    if history_recovery:
        db.execute("update tmp_pur_plan_replenish_calc set support_replenish_level_sort=5,normal_replenish_need_qty=0,history_recovery_flag=1 where seller_name_new='B'")
    assert select_targets(db, disabled=('C',))[0]['target_seller_name_new'] == 'B'
    assert assigned_quantities(db) == {'A':0,'B':0 if history_recovery else 100,'C':0}
    # History recovery at layer 5 is restored by the subsequent MOQ stage.
    if history_recovery:
        row=db.execute("select * from tmp_asin_merge_assignments where seller_name_new='B'").fetchone()
        assert row['asin_merge_flag']==0 and row['asin_merge_target_flag']==1
        assert row['asin_merge_reason']=='跟卖不补货回退原链接'
        expression=re.search(
            r"case\s+when coalesce\(r\.history_recovery_flag, 0\) = 1.*?end as calculated_replenish_qty",
            update.MOQ_GATING_SQL, re.S,
        ).group()
        restored=db.execute('select '+expression+''' from (
            select calc.*,assign.asin_merge_flag,
                assign.asin_merge_reason as replenish_block_reason,0 as replenish_qty
            from tmp_pur_plan_replenish_calc calc join tmp_asin_merge_assignments assign
            using(country_category,max_asin,seller_name_new,seller_sku_adj)) r
            where seller_name_new='B' ''').fetchone()
        assert restored['calculated_replenish_qty']==10


def test_multiple_follow_stores_with_clearance_keep_no_origin_fallback(db):
    add_link(db, 'A', msku='origin', follow=1)
    add_link(db, 'B', msku='clear-b')
    add_link(db, 'C', msku='clear-c')
    db.executemany('insert into etl_datasync_test.dashboard_replenishment_clearance_sync values (?,?)',
                   [('clear-b','全部'), ('clear-c','全部')])
    assert select_targets(db)==[]
    assert assigned_quantities(db)=={'A':0,'B':0,'C':0}


def test_multiple_follow_stores_keep_existing_block_for_target_that_is_also_followed(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'B', day='2026-10-06')
    add_link(db, 'C')
    db.execute("update tmp_pur_plan_replenish_calc set followed_flag=1 where seller_name_new='C'")
    assert select_targets(db)[0]['target_seller_name_new']=='C'
    assert assigned_quantities(db)=={'A':0,'B':0,'C':0}


def test_one_disabled_follow_store_with_multiple_mskus_still_uses_single_store_fallback(db):
    add_link(db, 'A', follow=1)
    add_link(db, 'C', msku='old', day='2026-10-06')
    add_link(db, 'C', msku='new')
    assert select_targets(db, disabled=('C',))[0]['target_seller_name_new']=='A'
    assert assigned_quantities(db)=={'A':100,'C':0}
    assert db.execute('select follow_store_count from tmp_asin_merge_groups').fetchone()[0]==1


def test_fallback_keeps_own_box_size_and_cost_when_another_origin_supplies_group_purchase_fields(db):
    add_link(db, 'A', day='2026-10-08', follow=1)
    add_link(db, 'B', day='2026-10-06', follow=1)
    add_link(db, 'C')
    db.execute("update tmp_pur_plan_replenish_calc set sales_30=1000,max_cg_box_pcs=100,max_cg_price=50 where seller_name_new='B'")
    assert select_targets(db, disabled=('C',))[0]['target_seller_name_new'] == 'A'
    assert assigned_results(db) == {'A':(100,10,600), 'B':(0,0,0), 'C':(0,0,0)}


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
