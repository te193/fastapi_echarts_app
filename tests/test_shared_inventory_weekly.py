from datetime import date
from unittest.mock import MagicMock, patch

from etl import shared_inventory_weekly as shared
from etl import dashboard_daily_update as daily


def test_only_changed_or_missing_weeks_are_replaced():
    current = {date(2026, 10, 5): "same", date(2026, 10, 12): "new"}
    saved = {date(2026, 10, 5): "same", date(2026, 10, 12): "old"}
    assert shared.changed_weeks(current, saved) == [date(2026, 10, 12)]
    assert shared.changed_weeks(current, {}) == sorted(current)


def test_signature_distinguishes_exact_current_day_from_historical_fallback():
    sql = shared.signature_sql()
    assert "max(snapshot_date)" in sql.lower()
    assert "snapshot_date = %(snapshot_date)s" in sql
    assert "dashboard_inventory_daily_snapshot" in sql
    assert "dashboard_restock_daily_snapshot" in sql
    assert "etl_dispose" not in sql


def test_current_week_uses_exact_local_day_and_preserves_cost_formula():
    sql = shared.current_week_insert_sql()
    assert "snapshot_date = %(snapshot_date)s" in sql
    assert sql.count("where snapshot_date = %(snapshot_date)s") == 2
    assert "coalesce(r.local_quantity, 0) * (coalesce(r.purchase_cost, 0) + coalesce(r.transport_cost, 0))" in sql
    assert "available_price" in sql
    assert "etl_dispose" not in sql


def test_legacy_remote_step_is_now_a_local_step():
    assert isinstance(daily.STEPS["inventory_weekly_remote_snapshot"], daily.SqlStep)


def test_unchanged_weeks_do_not_delete_or_insert_business_rows():
    conn=MagicMock()
    with patch.object(shared,"load_signatures",return_value={date(2026,10,5):"same"}), \
         patch.object(shared,"load_saved",return_value={date(2026,10,5):"same"}):
        assert shared.refresh(conn,daily.build_schema_config(),{"snapshot_date":date(2026,10,17)},current=False)==0
    statements=[call.args[0].lower() for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert not any(sql.startswith("delete from") for sql in statements)
    assert not any("insert into etl_datasync_test.dashboard_inventory_weekly_snapshot" in sql for sql in statements)


def test_removed_week_is_invalidated_once_and_empty_week_is_stable():
    week=date(2026,10,12)
    assert shared.changed_weeks({}, {week:"old"})==[week]
    assert shared.changed_weeks({}, {week:shared.EMPTY_SIGNATURE})==[]


def test_empty_current_day_clears_existing_week_even_without_saved_signature():
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.rowcount=0
    with patch.object(shared,"load_signatures",return_value={}), patch.object(shared,"load_saved",return_value={}):
        shared.refresh(conn,daily.build_schema_config(),{"snapshot_date":date(2026,10,17)},current=True)
    statements=[call.args[0].lower() for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert any(sql.startswith("delete from") for sql in statements)
