from datetime import date, datetime, timedelta

import pytest

from app.services.replenishment_tracking_data import ReplenishmentTrackingService
from etl import replenishment_tracking_update


def test_tracking_window_normalization():
    service = ReplenishmentTrackingService()

    assert service._normalize_window_days(7) == 7
    assert service._normalize_window_days("14") == 14
    assert service._normalize_window_days("90") == 30
    assert service._normalize_window_days("bad") == 30
    assert service._normalize_window_days(180) == 30


def test_tracking_category_period_normalization():
    service = ReplenishmentTrackingService()

    assert service._normalize_category_period_days(7) == 7
    assert service._normalize_category_period_days("14") == 14
    assert service._normalize_category_period_days(30) == 30
    assert service._normalize_category_period_days("90") == 90
    assert service._normalize_category_period_days("180") == 30
    assert service._normalize_category_period_days("bad") == 30


def test_tracking_category_expression_uses_requested_period_columns():
    service = ReplenishmentTrackingService()

    expr_7 = service._product_category_expr(7)
    assert "p.final_sales_7d" in expr_7
    assert "p.r_7d_salable_days" in expr_7
    assert "p.pprofit_ratio_7d" in expr_7
    assert "s.product_category" in expr_7

    expr_90 = service._product_category_expr("90")
    assert "p.sales_90d" in expr_90
    assert "p.r_90d_salable_days" in expr_90
    assert "p.pprofit_ratio_90d" in expr_90

    expr_invalid = service._product_category_expr("180")
    assert "p.final_sales_30d" in expr_invalid


def test_empty_tracking_payload_includes_category_period_days():
    service = ReplenishmentTrackingService()

    payload = service._empty_payload(30, 90, 1, 20)

    assert payload["tracking_window_days"] == 30
    assert payload["category_period_days"] == 90


def test_source_type_label_translation():
    service = ReplenishmentTrackingService()

    assert service._source_type_label("purchase_plan") == "采购计划"
    assert service._source_type_label("shipment_plan") == "FBA发货计划"
    assert service._source_type_label("shipment_detail") == "FBA发货单"
    assert service._source_type_label("local_snapshot") == "本地快照"
    assert service._source_type_label("new_source") == "new_source"


def test_detail_serialization_includes_source_type_label():
    service = ReplenishmentTrackingService()

    row = service._serialize_detail({"source_type": "shipment_plan", "shipment_plan_quantity": 12})

    assert row["source_type"] == "shipment_plan"
    assert row["source_type_label"] == "FBA发货计划"
    assert row["shipment_plan_quantity"] == 12


def test_detail_serialization_falls_back_to_shipment_time_for_display():
    service = ReplenishmentTrackingService()

    row = service._serialize_detail(
        {
            "source_type": "shipment_detail",
            "shipment_time": datetime(2026, 6, 23, 19, 31, 53),
            "actual_shipment_time": None,
        }
    )

    assert row["shipment_time_display"] == "2026-06-23 19:31:53"

    actual_row = service._serialize_detail(
        {
            "source_type": "shipment_detail",
            "shipment_time": datetime(2026, 6, 23, 19, 31, 53),
            "actual_shipment_time": datetime(2026, 6, 24, 8, 15, 0),
        }
    )

    assert actual_row["shipment_time_display"] == "2026-06-24 08:15:00"


def test_detail_rows_hide_local_snapshot_source():
    service = ReplenishmentTrackingService()

    rows = service._serialize_detail_rows(
        [
            {"source_type": "local_snapshot", "purchase_plan_qty": 3},
            {"source_type": "purchase_plan", "purchase_plan_qty": 5},
            {"source_type": "shipment_plan", "shipment_plan_quantity": 8},
        ]
    )

    assert [row["source_type"] for row in rows] == ["purchase_plan", "shipment_plan"]


def test_detail_falls_back_to_first_tracked_date_in_window(monkeypatch):
    service = ReplenishmentTrackingService()

    class Cursor:
        def __init__(self):
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            if "from dashboard_replenishment_tracking_snapshot" in sql:
                self.rows = [{"snapshot_date": date(2026, 6, 25), "country_category": "raw-site"}]
            elif params["snapshot_date"] == date(2026, 6, 25):
                assert params["site"] == "raw-site"
                self.rows = [{"source_type": "purchase_plan", "purchase_plan_sn": "PP260625045"}]
            else:
                self.rows = []

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(service, "connect", lambda: Conn())

    payload = service.get_detail("2026-06-29", 30, "欧洲站", "YuanJinRong", "YJR008a")

    assert [row["purchase_plan_sn"] for row in payload["rows"]] == ["PP260625045"]


def test_level_summary_serialization_includes_status_msku_counts():
    service = ReplenishmentTrackingService()

    row = service._serialize_level_summary(
        {
            "level": "紧急补货",
            "msku_count": 93,
            "purchase_planned_msku_count": 35,
            "purchase_unplanned_msku_count": 58,
            "fba_plan_msku_count": 12,
            "shipped_msku_count": 7,
        }
    )

    assert row["purchase_planned_msku_count"] == 35
    assert row["fba_plan_msku_count"] == 12
    assert row["shipped_msku_count"] == 7


def test_tracking_tables_have_business_comments():
    snapshot_ddl = replenishment_tracking_update.CREATE_TRACKING_SNAPSHOT_SQL
    detail_ddl = replenishment_tracking_update.CREATE_TRACKING_DETAIL_SQL

    assert "comment='补货分层采购发货追踪汇总表'" in snapshot_ddl
    assert "comment='补货分层采购发货追踪明细表'" in detail_ddl
    assert "purchase_plan_qty decimal(18,4)" in snapshot_ddl
    assert "comment '未完成采购计划数量" in snapshot_ddl
    assert "purchase_plan_count int" in snapshot_ddl
    assert "comment '追踪窗口内采购计划单数" in snapshot_ddl
    assert "purchase_plan_total_qty decimal(18,4)" in snapshot_ddl
    assert "comment '追踪窗口内采购计划总数量" in snapshot_ddl
    assert "fba_shipment_plan_qty decimal(18,4)" in snapshot_ddl
    assert "comment 'FBA发货计划数量'" in snapshot_ddl
    assert "quantity_received decimal(18,4)" in detail_ddl
    assert "comment '实际收货数量'" in detail_ddl


def test_snapshot_sql_counts_shipment_detail_plan_quantity_as_fba_plan_fallback():
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL

    assert "as current_shipment_plan_quantity" in sql
    assert "as historical_shipment_plan_quantity" in sql
    assert "greatest(coalesce(sp.current_fba_shipment_plan_qty, 0), coalesce(sd.current_shipment_plan_quantity, 0)) as current_fba_shipment_plan_qty" in sql
    assert "greatest(coalesce(sp.historical_fba_shipment_plan_qty, 0), coalesce(sd.historical_shipment_plan_quantity, 0)) as historical_fba_shipment_plan_qty" in sql


def test_snapshot_sql_counts_purchase_entry_only_from_new_purchase_plans():
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL

    assert "coalesce(pp0.status_text, '') <> '已完成'" in sql
    assert "sum(case" in sql
    assert "then coalesce(pp0.quantity_plan, 0)" in sql
    assert "count(distinct pp0.plan_sn) as purchase_plan_count" in sql
    assert "sum(coalesce(pp0.quantity_plan, 0)) as purchase_plan_total_qty" in sql
    assert "coalesce(pp.purchase_plan_count, 0) > 0 then 1 else 0" in sql
    assert "or coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) > 0" not in sql
    assert "or greatest(coalesce(sp.fba_shipment_plan_qty, 0), coalesce(sd.shipment_plan_quantity, 0)) > 0" not in sql
    assert "when coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) > 0 then 0" in sql
    assert "end as purchase_plan_qty" in sql


def test_snapshot_sql_labels_existing_purchase_in_transit_without_ambiguity():
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL

    assert "least(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0), coalesce(pp.purchase_plan_total_qty, 0)) as current_purchase_shipping_qty" in sql
    assert "greatest(coalesce(r.purchase_shipping_quantity, p.sc_quantity_purchase_shipping, 0) - coalesce(pp.purchase_plan_total_qty, 0), 0) as historical_purchase_shipping_qty" in sql
    assert "then '本次+历史采购在途'" in sql
    assert "then '本次采购在途'" in sql
    assert "then '历史采购在途'" in sql
    assert "then '采购在途'" not in sql


def test_tracking_service_serializes_current_and_historical_purchase_shipping():
    service = ReplenishmentTrackingService()

    item = service._serialize_item(
        {
            "current_purchase_shipping_qty": 120,
            "historical_purchase_shipping_qty": 30,
        }
    )

    assert item["current_purchase_shipping_qty"] == 120
    assert item["historical_purchase_shipping_qty"] == 30


def test_tracking_service_serializes_purchase_plan_count_and_total_qty():
    service = ReplenishmentTrackingService()

    summary = service._serialize_summary({"purchase_plan_count": 3, "purchase_plan_total_qty": 450})
    level = service._serialize_level_summary({"purchase_plan_count": 2, "purchase_plan_total_qty": 200})
    item = service._serialize_item({"purchase_plan_count": 1, "purchase_plan_total_qty": 120})

    assert summary["purchase_plan_count"] == 3
    assert summary["purchase_plan_total_qty"] == 450
    assert level["purchase_plan_count"] == 2
    assert level["purchase_plan_total_qty"] == 200
    assert item["purchase_plan_count"] == 1
    assert item["purchase_plan_total_qty"] == 120


def test_snapshot_sql_separates_current_chain_and_historical_shipments():
    snapshot_ddl = replenishment_tracking_update.CREATE_TRACKING_SNAPSHOT_SQL
    detail_ddl = replenishment_tracking_update.CREATE_TRACKING_DETAIL_SQL
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL

    assert "current_fba_shipment_plan_qty decimal(18,4)" in snapshot_ddl
    assert "current_shipped_qty decimal(18,4)" in snapshot_ddl
    assert "historical_fba_shipment_plan_qty decimal(18,4)" in snapshot_ddl
    assert "historical_shipped_qty decimal(18,4)" in snapshot_ddl
    assert "shipment_attribution varchar(32)" in snapshot_ddl
    assert "link_attribution varchar(32)" in detail_ddl

    assert "sp0.plan_create_time >= pp.latest_purchase_plan_time" in sql
    assert "sp0.plan_create_time < pp.latest_purchase_plan_time" in sql
    assert "sp_link.order_sn = it.shipment_order_sn" in sql
    assert "coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) >= pp.latest_purchase_plan_time" in sql
    assert "coalesce(sp_link.plan_create_time, it.shipment_time, it.source_create_time) < pp.latest_purchase_plan_time" in sql
    assert "current_shipped_qty" in sql
    assert "historical_shipped_qty" in sql
    assert "'历史采购发货'" in sql


def test_snapshot_sql_includes_pre_replenishment_fba_carryover_as_historical():
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL
    detail_sql = replenishment_tracking_update.INSERT_SHIPMENT_DETAIL_SQL

    assert "coalesce(it.shipment_time, it.source_create_time) < p0.cur_date" in sql
    assert "coalesce(sm.delivery_date, sm.expected_arrival_date, sm.eta_date, date_add(p0.cur_date, interval %(tracking_window_days)s day)) >= p0.cur_date" in sql
    assert "coalesce(it.shipment_time, it.source_create_time) < p.cur_date" in detail_sql
    assert "coalesce(sm.delivery_date, sm.expected_arrival_date, sm.eta_date, date_add(p.cur_date, interval %(tracking_window_days)s day)) >= p.cur_date" in detail_sql


def test_source_sync_looks_back_for_historical_fba_carryover():
    source = replenishment_tracking_update.SOURCE_LOOKBACK_DAYS

    assert source == 30


def test_source_sync_normalizes_eu_store_suffix_before_marketplace_suffix():
    assert "upper(seller_name) regexp '-EU-[A-Z]{2}$'" in replenishment_tracking_update.SELECT_PURCHASE_PLAN_SYNC_SQL
    assert "upper(sname) regexp '-EU-[A-Z]{2}$'" in replenishment_tracking_update.SELECT_FBA_SHIPMENT_PLAN_SYNC_SQL
    assert "upper(sname) regexp '-EU-[A-Z]{2}$'" in replenishment_tracking_update.SELECT_INBOUND_ITEM_SYNC_SQL


def test_tracking_result_validation_rejects_empty_snapshot():
    with pytest.raises(RuntimeError, match="2026-06-27.*7.*0 rows"):
        replenishment_tracking_update.validate_tracking_result(
            date(2026, 6, 27),
            7,
            {"snapshot_rows": 0, "detail_rows": 0},
        )


def test_tracking_service_serializes_current_and_historical_shipments():
    service = ReplenishmentTrackingService()

    item = service._serialize_item(
        {
            "current_fba_shipment_plan_qty": 432,
            "current_shipped_qty": 0,
            "historical_fba_shipment_plan_qty": 48,
            "historical_shipped_qty": 48,
            "shipment_attribution": "mixed",
        }
    )
    summary = service._serialize_summary(
        {
            "current_shipped_qty": 10,
            "historical_shipped_qty": 5,
            "historical_shipped_msku_count": 2,
        }
    )

    assert item["current_fba_shipment_plan_qty"] == 432
    assert item["current_shipped_qty"] == 0
    assert item["historical_fba_shipment_plan_qty"] == 48
    assert item["historical_shipped_qty"] == 48
    assert item["shipment_attribution"] == "mixed"
    assert summary["current_shipped_qty"] == 10
    assert summary["historical_shipped_qty"] == 5
    assert summary["historical_shipped_msku_count"] == 2


def test_snapshot_sql_tracks_nearest_fba_eta_only_from_fba_in_transit():
    snapshot_ddl = replenishment_tracking_update.CREATE_TRACKING_SNAPSHOT_SQL
    sql = replenishment_tracking_update.INSERT_SNAPSHOT_SQL

    assert "nearest_fba_eta_date datetime" in snapshot_ddl
    assert "sm.expected_arrival_date" in sql
    assert "sm.eta_date" in sql
    assert "as nearest_fba_eta_date" in sql
    assert "coalesce(it.quantity_shipped, 0) > 0" in sql
    nearest_eta_section = sql.split("as nearest_fba_eta_date", 1)[0].rsplit("coalesce(", 1)[-1]
    assert "purchase_expect_arrive_time" not in nearest_eta_section
    assert "delivery_date" not in nearest_eta_section


def test_tracking_service_serializes_nearest_fba_eta_label_and_days():
    service = ReplenishmentTrackingService()
    eta_date = date.today() + timedelta(days=3)

    item = service._serialize_item({"nearest_fba_eta_date": eta_date})

    assert item["nearest_fba_eta_date"] == eta_date.isoformat()
    assert item["nearest_fba_eta_days"] == 3
    assert item["nearest_fba_eta_label"] == f"{eta_date.isoformat()}（3天）"


def test_tracking_service_serializes_overdue_fba_eta_label():
    service = ReplenishmentTrackingService()
    eta_date = date.today() - timedelta(days=2)

    item = service._serialize_item({"nearest_fba_eta_date": eta_date})

    assert item["nearest_fba_eta_days"] == -2
    assert item["nearest_fba_eta_label"] == f"{eta_date.isoformat()}（已超2天）"
