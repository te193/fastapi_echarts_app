import sys
from pathlib import Path

from app.services.replenishment_tracking_summary_data import (
    ReplenishmentTrackingSummaryService,
    fba_status_label,
    format_eta_text,
    map_summary_row,
    purchase_status_label,
)
from etl import replenishment_tracking_summary_update


def test_summary_etl_dry_run_exits_before_database_setup(monkeypatch, capsys):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("dry-run must not initialize or connect to a database")

    monkeypatch.setattr(replenishment_tracking_summary_update, "apply_database_ini_env", fail_if_called)
    monkeypatch.setattr(replenishment_tracking_summary_update, "connect_target", fail_if_called)
    monkeypatch.setattr(replenishment_tracking_summary_update, "connect_source", fail_if_called)
    monkeypatch.setattr(sys, "argv", ["replenishment_tracking_summary_update", "--dry-run"])

    replenishment_tracking_summary_update.main()

    output = capsys.readouterr().out
    assert "Replenishment tracking summary ETL plan" in output
    assert "cutoff_date: latest replenishment date" in output
    assert "[success] replenishment_tracking_summary dry_run=true writes=0" in output


def test_summary_etl_syncs_qc_orders_for_qc_node():
    assert "dashboard_tracking_qc_order_sync" in replenishment_tracking_summary_update.CREATE_QC_ORDER_SYNC_SQL
    assert "lx_storage_qc_order" in replenishment_tracking_summary_update.SELECT_QC_ORDER_SYNC_SQL
    assert "delivery_order_sn" in replenishment_tracking_summary_update.QC_ORDER_SYNC_COLUMNS
    assert "product_good_num" in replenishment_tracking_summary_update.QC_ORDER_SYNC_COLUMNS
    assert "product_bad_num" in replenishment_tracking_summary_update.QC_ORDER_SYNC_COLUMNS


def test_summary_etl_uses_qc_order_good_bad_for_qc_passed_node():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL
    assert "qc_doc as" in sql
    assert "qo.delivery_order_sn = m.receipt_order_sn" in sql
    assert "qo.order_sn = m.business_order_sn" in sql
    assert "replace(coalesce(qo.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "replace(coalesce(m.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "coalesce(qd.qc_good_qty, 0) > 0 and coalesce(qd.qc_bad_qty, 0) = 0" in sql


def test_summary_etl_moves_qc_passed_rows_to_fba_nodes():
    sql = replenishment_tracking_summary_update.UPDATE_QC_PASSED_NODE_SQL
    assert "qc_passed_flag = 1" in sql
    assert "fba_plan_flag = 0" in sql
    assert "fba_shipped_flag = 0" in sql


def test_summary_etl_splits_current_and_historical_fba_plans():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "current_fba_plan_match as" in sql
    assert "all_fba_plan_match as" in sql
    assert "historical_fba_plan_doc as" in sql
    assert "fp.plan_create_time >= pp0.plan_create_time" in sql
    assert "replace(coalesce(fp.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "p0.tracking_sku" in sql
    assert "abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp0.quantity_plan, 0))" in sql
    assert "left join current_fba_plan_match cfpm" in sql
    assert "cfpm.order_sn is null" in sql


def test_summary_etl_uses_real_fba_shipment_id_for_fba_outbound_node():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "current_fba_shipped_doc as" in sql
    assert "dashboard_tracking_inbound_item_sync ii" in sql
    assert "ii.shipment_order_sn = cfpm.order_sn" in sql
    assert "ii.shipment_id like 'FBA%%'" in sql
    assert "case when coalesce(fbsd.fba_shipment_count, 0) > 0 then 1 else 0 end" in sql
    assert "coalesce(fbsd.fba_shipped_qty, 0)" in sql


def test_summary_etl_uses_current_fba_items_for_receiving_and_closed_nodes():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "sum(coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0)) as fba_received_qty" in sql
    assert "receiving_shipment_count" in sql
    assert "closed_shipment_count" in sql
    assert "upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) = 'RECEIVING'" in sql
    assert "upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) = 'CLOSED'" in sql
    assert "ish.receiving_time is not null" in sql
    assert "ish.closed_time is not null" in sql
    assert "coalesce(ish.quantity_received, 0) > 0" in sql
    assert "case when coalesce(fbsd.receiving_shipment_count, 0) > 0 then 1 else 0 end" in sql
    assert "coalesce(fbsd.closed_shipment_count, 0) = coalesce(fbsd.fba_shipment_count, 0)" in sql
    assert "case when coalesce(t.received_qty, 0) > 0 then 1 else 0 end" not in sql


def test_summary_etl_marks_fba_complete_only_after_all_current_shipments_close():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "coalesce(fbsd.fba_shipment_count, 0) > 0" in sql
    assert "coalesce(fbsd.closed_shipment_count, 0) = coalesce(fbsd.fba_shipment_count, 0)" in sql


def test_summary_eta_uses_active_inbound_shipments_relative_to_cutoff_date():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "active_fba_eta_doc as" in sql
    assert "coalesce(ii.quantity_shipped, 0) > coalesce(nullif(ii.shipment_quantity_received, 0), ii.quantity_receive, 0)" in sql
    assert "upper(coalesce(ii.shipment_status, ii.status_text, ish.shipment_status, ish.status_name, '')) <> 'CLOSED'" in sql
    assert "ish.closed_time is null" in sql
    assert "coalesce(eta.nearest_fba_eta_date, t.nearest_fba_eta_date)" not in sql
    assert "eta.nearest_fba_eta_date" in sql


def test_summary_detail_fba_match_uses_sku_and_quantity_tolerance():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()

    assert "replace(coalesce(fp.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "replace(coalesce(s.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "abs(coalesce(fp.shipment_plan_quantity, 0) - coalesce(pp.quantity_plan, 0))" in sql
    assert "fp.plan_create_time >= pp.plan_create_time" in sql


def test_summary_detail_includes_real_fba_shipment_rows():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()

    assert "'fba_shipment' as source_type" in sql
    assert "'FBA出库/在途' as source_type_label" in sql
    assert "ii.shipment_order_sn = fp.order_sn" in sql
    assert "ii.shipment_id like 'FBA%%'" in sql
    assert "left join dashboard_tracking_inbound_shipment_sync ish" in sql


def test_summary_detail_prefers_chinese_fba_shipment_status_over_raw_status_code():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()

    assert "nullif(ish.status_name, '')" in sql
    assert "when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'SHIPPED' then '已发货'" in sql
    assert "when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'RECEIVING' then '接收中'" in sql
    assert "when upper(coalesce(ii.shipment_status, ish.shipment_status, '')) = 'CLOSED' then '已完成'" in sql


def test_map_summary_row_exposes_historical_fba_plan_metrics():
    mapped = map_summary_row({
        "historical_fba_plan_count": 2,
        "historical_fba_plan_qty": 120,
    })

    assert mapped["historical_fba_plan_count"] == 2
    assert mapped["historical_fba_plan_qty"] == 120


def test_status_labels_are_business_readable():
    assert purchase_status_label("current") == "本次补货后采购"
    assert purchase_status_label("historical") == "历史采购在途"
    assert purchase_status_label("mixed") == "本次+历史采购"
    assert purchase_status_label("none") == "未采购"

    assert fba_status_label("current") == "本次FBA在途"
    assert fba_status_label("historical") == "历史FBA在途"
    assert fba_status_label("mixed") == "本次+历史FBA在途"
    assert fba_status_label("none") == "未建FBA"


def test_format_eta_text():
    assert format_eta_text(None) == "-"
    assert format_eta_text(3) == "3天后到货"
    assert format_eta_text(0) == "今天预计到货"
    assert format_eta_text(-2) == "已过预计到货2天"


def test_map_summary_row_formats_labels_and_tags():
    row = {
        "seller_sku_adj": "YJR008a",
        "sku": "HRJ0003a",
        "seller_name_new": "YuanJinRong",
        "country_category": "欧洲站",
        "current_replenishment_level": "紧急补货",
        "historical_replenishment_levels": "建议补货,紧急补货",
        "product_category": "瘦狗产品",
        "purchase_status": "mixed",
        "fba_status": "historical",
        "nearest_fba_eta_days": -1,
        "appearance_days": 4,
    }

    mapped = map_summary_row(row)

    assert mapped["msku"] == "YJR008a"
    assert mapped["purchase_status_label"] == "本次+历史采购"
    assert mapped["fba_status_label"] == "历史FBA在途"
    assert mapped["nearest_fba_eta_text"] == "已过预计到货1天"
    assert "反复出现4天" in mapped["replenishment_tags"]
    assert "曾升级为紧急" in mapped["replenishment_tags"]
    assert "当前仍紧急" in mapped["replenishment_tags"]


def test_map_summary_row_uses_second_link_node_state():
    row = {
        "seller_sku_adj": "YJR008a",
        "sku": "HRJ0003a",
        "seller_name_new": "YuanJinRong",
        "country_category": "欧洲站",
        "current_replenishment_level": "紧急补货",
        "historical_replenishment_levels": "紧急补货",
        "purchase_plan_flag": 1,
        "purchase_plan_qty": 53,
        "supplier_shipped_flag": 1,
        "purchase_inbound_qty": 53,
        "local_received_flag": 0,
    }

    mapped = map_summary_row(row)

    assert mapped["current_node"] == "到本地仓"
    assert mapped["breakpoint_reason"] == "采购已在途，但未确认到本地仓 53"


def test_map_summary_row_shows_supplier_not_shipped():
    row = {
        "seller_sku_adj": "YJR008a",
        "sku": "HRJ0003a",
        "seller_name_new": "YuanJinRong",
        "country_category": "欧洲站",
        "current_replenishment_level": "紧急补货",
        "historical_replenishment_levels": "紧急补货",
        "purchase_plan_flag": 1,
        "purchase_plan_qty": 53,
        "supplier_shipped_flag": 0,
    }

    mapped = map_summary_row(row)

    assert mapped["current_node"] == "采购在途"
    assert mapped["breakpoint_reason"] == "已建采购计划，但未确认采购在途 53"


def test_summary_etl_reuses_existing_replenishment_and_tracking_tables():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "dashboard_pur_plan_replenish_data" in sql
    assert "dashboard_replenishment_tracking_snapshot" in sql
    assert "lx_purchase_purchase_plan" not in sql
    assert "lx_fba_shipment_plan" not in sql
    assert "lx_inbound_shipment_detail" not in sql


def test_level_history_prestores_purchase_plan_match():
    sql = replenishment_tracking_summary_update.INSERT_LEVEL_HISTORY_SQL

    assert "purchase_plan_flag" in sql
    assert "purchase_plan_count" in sql
    assert "purchase_plan_qty" in sql
    assert "purchase_plan_sn_list" in sql
    assert "p0.support_replenish_level" in sql
    assert "dashboard_tracking_purchase_plan_sync" in sql


def test_level_history_prestores_supplier_shipping_match():
    sql = replenishment_tracking_summary_update.INSERT_LEVEL_HISTORY_SQL

    assert "supplier_shipped_flag" in sql
    assert "purchase_order_count" in sql
    assert "purchase_inbound_qty" in sql
    assert "dashboard_tracking_purchase_order_sync" in sql
    assert "logistics_provider" in sql
    assert "logistics_order" in sql


def test_summary_etl_syncs_purchase_orders_for_second_link():
    assert "dashboard_tracking_purchase_order_sync" in replenishment_tracking_summary_update.CREATE_PURCHASE_ORDER_SYNC_SQL
    assert "lx_purchase_purchase_order" in replenishment_tracking_summary_update.SELECT_PURCHASE_ORDER_SYNC_SQL
    assert "logistics_provider" in replenishment_tracking_summary_update.PURCHASE_ORDER_SYNC_COLUMNS
    assert "logistics_order" in replenishment_tracking_summary_update.PURCHASE_ORDER_SYNC_COLUMNS


def test_summary_etl_uses_purchase_order_match_for_inbound_node():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "purchase_order_doc as" in sql
    assert "replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "p0.tracking_sku" in sql
    assert "coalesce(pod.shipped_order_count, 0) > 0 or coalesce(rd.local_received_qty, 0) > 0 or coalesce(qd.qc_good_qty, 0) > 0" in sql
    assert "greatest(coalesce(pod.purchase_inbound_qty, 0), coalesce(rd.local_received_qty, 0), coalesce(qd.qc_good_qty, 0))" in sql


def test_summary_etl_syncs_receipts_for_local_received_node():
    assert "dashboard_tracking_receipt_order_sync" in replenishment_tracking_summary_update.CREATE_RECEIPT_ORDER_SYNC_SQL
    assert "lx_storage_receipt_order" in replenishment_tracking_summary_update.SELECT_RECEIPT_ORDER_SYNC_SQL
    assert "business_order_sn" in replenishment_tracking_summary_update.RECEIPT_ORDER_SYNC_COLUMNS
    assert "product_receive_num" in replenishment_tracking_summary_update.RECEIPT_ORDER_SYNC_COLUMNS


def test_summary_etl_uses_receipt_match_for_local_received_node():
    sql = replenishment_tracking_summary_update.INSERT_SUMMARY_SQL

    assert "receipt_doc as" in sql
    assert "ro.business_order_sn = m.order_sn" in sql
    assert "replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "replace(coalesce(m.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "coalesce(rd.local_received_qty, 0)" in sql
    assert "case when coalesce(rd.local_received_qty, 0) > 0 then 1 else 0 end" in sql


def test_summary_stage_filters_match_level_cards():
    service = ReplenishmentTrackingSummaryService()

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "purchased", "紧急补货", "all", "all", "all", "", "product_category_30d")
    assert "s.purchase_status <> 'none'" in filters
    assert "h.historical_replenishment_level = %(history_level)s" in filters

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "current_fba", "all", "all", "all", "all", "", "product_category_30d")
    assert "s.fba_status in ('current', 'mixed')" in filters

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "historical_fba", "all", "all", "all", "all", "", "product_category_30d")
    assert "s.fba_status in ('historical', 'mixed')" in filters

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "received", "all", "all", "all", "all", "", "product_category_30d")
    assert "s.received_qty > 0" in filters

    checks = {
        "unpurchased": "s.purchase_status = 'none'",
        "purchased_no_fba": "s.purchase_status <> 'none' and s.fba_status = 'none'",
        "fba_inbound": "s.fba_status <> 'none'",
        "eta_7d": "s.nearest_fba_eta_days between 0 and 7",
        "eta_overdue": "s.nearest_fba_eta_days < 0",
    }
    for stage, expected in checks.items():
        filters, _ = service._where("2026-06-29", 30, "all", "all", "all", stage, "all", "all", "all", "all", "", "product_category_30d")
        assert expected in filters


def test_summary_keyword_filters_keep_object_and_order_keywords_separate():
    service = ReplenishmentTrackingSummaryService()

    filters, params = service._where(
        "2026-06-29",
        30,
        "all",
        "all",
        "all",
        "all",
        "all",
        "all",
        "all",
        "all",
        "YJR008a",
        "product_category_30d",
        "PP260625013",
    )

    assert "s.seller_sku_adj like %(keyword)s" in filters
    assert "coalesce(s.order_sn_summary, '') like %(order_keyword)s" in filters
    assert params["keyword"] == "%YJR008a%"
    assert params["order_keyword"] == "%PP260625013%"


def test_level_purchase_plan_stage_filters_use_prestored_level_history():
    service = ReplenishmentTrackingSummaryService()

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "purchase_plan_done", "紧急补货", "all", "all", "all", "", "product_category_30d")
    assert "h.purchase_plan_flag = 1" in filters
    assert "dashboard_tracking_purchase_plan_sync" not in filters

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "no_purchase_plan", "紧急补货", "all", "all", "all", "", "product_category_30d")
    assert "h.purchase_plan_flag = 0" in filters


def test_level_supplier_shipping_stage_filters_use_prestored_level_history():
    service = ReplenishmentTrackingSummaryService()

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "supplier_shipped_done", "紧急补货", "all", "all", "all", "", "product_category_30d")
    assert "h.supplier_shipped_flag = 1" in filters

    filters, _ = service._where("2026-06-29", 30, "all", "all", "all", "supplier_not_shipped", "紧急补货", "all", "all", "all", "", "product_category_30d")
    assert "h.purchase_plan_flag = 1" in filters
    assert "h.supplier_shipped_flag = 0" in filters


def test_summary_detail_query_includes_purchase_orders():
    service = ReplenishmentTrackingSummaryService()

    assert "purchase_order" in service._detail_sql()
    assert "dashboard_tracking_purchase_order_sync" in service._detail_sql()


def test_summary_detail_uses_visible_cutoff_date():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert "cutoff_date: state.date" not in js
    assert 'cutoff_date: textOf("datePickerValue")' in js


def test_tracking_summary_same_day_count_uses_daily_dashboard_display_rules():
    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            queries.append(" ".join(str(sql).split()))

        def fetchall(self):
            return []

    class Connection:
        def cursor(self):
            return Cursor()

    service = ReplenishmentTrackingSummaryService()
    service._level_flow(Connection(), "1 = 1", {}, "product_category_30d")
    sql = queries[0]

    assert "left join dashboard_pur_plan_replenish_data d" in sql
    assert "d.cur_date = s.cutoff_date" in sql
    assert "d.support_replenish_level = h.historical_replenishment_level collate utf8mb4_0900_ai_ci" in sql
    assert "d.country_category = s.country_category collate utf8mb4_0900_ai_ci" in sql
    assert "d.seller_name_new = s.seller_name_new collate utf8mb4_0900_ai_ci" in sql
    assert "d.seller_sku_adj = s.seller_sku_adj collate utf8mb4_0900_ai_ci" in sql
    assert "d.country_category collate utf8mb4_unicode_ci" not in sql
    assert "coalesce(d.asin_merge_flag, 0) = 1" in sql
    assert "coalesce(d.replenish_qty, 0) = 0" in sql
    assert "coalesce(d.replenish_block_reason, '') <> '被跟卖点不补货'" in sql
    assert "h.is_current_level = 1 and s.latest_replenishment_date = s.cutoff_date" not in sql


def test_summary_detail_labels_date_as_cutoff_date():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert "截止日期 \" + cutoffDate" in js


def test_summary_detail_groups_rows_by_purchase_plan():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert "function groupDetailRows(rows)" in js
    assert "rowData: groupDetailRows(rows)" in js


def test_summary_detail_hides_received_and_labels_purchase_qty():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert 'numberColumn("采购数量", "purchase_order_qty", 104)' in js
    assert "已收" not in js[js.index("function renderDetailTable"):js.index("function renderStageDetailTable")]


def test_summary_detail_dedupes_orders_from_multiple_history_levels():
    service = ReplenishmentTrackingSummaryService()
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert "select distinct" in service._detail_sql().lower()
    assert "seenOrderKeys" in js


def test_purchase_order_links_ignore_voided_and_match_sku():
    service = ReplenishmentTrackingSummaryService()
    detail_sql = service._detail_sql()
    level_sql = replenishment_tracking_summary_update.INSERT_LEVEL_HISTORY_SQL

    assert "po.status <> '作废'" in detail_sql
    assert "replace(coalesce(po.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in detail_sql
    assert "replace(coalesce(s.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in detail_sql
    assert "po.status <> '作废'" in level_sql
    assert "replace(coalesce(ppm.max_sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in level_sql


def test_summary_chain_progress_uses_unambiguous_node_labels():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")
    start = js.index("function renderChainProgress")
    end = js.index("function ratioText", start)
    block = js[start:end]

    assert '"购", "建采购"' in block
    assert '"途", "采购在途"' in block
    assert 'title="' in block
    assert '"采", row.purchase_plan_flag' not in block
    assert '"发", row.supplier_shipped_flag' not in block
def test_summary_detail_includes_receipt_orders():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()
    assert "'receipt_order' as source_type" in sql
    assert "dashboard_tracking_receipt_order_sync ro" in sql
    assert "ro.business_order_sn = po.order_sn" in sql
    assert "replace(coalesce(ro.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "replace(coalesce(s.sku, ''), '-zu', '') regexp '[0-9][a-z]$'" in sql
    assert "coalesce(ro.product_receive_num, 0) as quantity_received" in sql


def test_summary_detail_labels_receipt_qc_status_code():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()
    assert "when ro.quality_examine_status = '2' then '已质检'" in sql


def test_summary_page_shows_historical_fba_plan_separately():
    js = Path("app/static/js/replenishment_tracking_summary.js").read_text(encoding="utf-8")

    assert 'numberColumn("历史FBA计划", "historical_fba_plan_qty", 120)' in js
    assert "row.historical_fba_plan_count" in js
    assert 'var isFbaPlan = row.source_type === "fba_plan"' in js
    assert 'Number(row.shipment_plan_quantity || row.purchase_plan_qty || 0)' in js
    assert 'isFbaPlan ? "计划数"' in js
    assert 'headerName: "候选/重复FBA"' in js
    assert 'historical_fba_summary' in js
    assert 'isHistoricalFbaPlan(row)' in js


def test_summary_detail_includes_current_and_historical_fba_plans():
    sql = ReplenishmentTrackingSummaryService()._detail_sql()

    assert "'fba_plan' as source_type" in sql
    assert "'本次链路' as link_attribution" in sql
    assert "'历史/待确认' as link_attribution" in sql
    assert "fp.plan_create_time >= pp.plan_create_time" in sql
