from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from etl.returned_product_tags_update import (
    DEFAULT_OUTPUT_PATH,
    build_payload,
    write_payload,
)


def test_build_payload_matches_dashboard_json_shape():
    summary_row = {
        "run_id": 12,
        "source_generated_at": datetime(2026, 6, 23, 9, 51, 53),
        "latest_inventory_date": date(2026, 6, 22),
        "window_180_start": date(2025, 12, 25),
        "window_14_start": date(2026, 6, 9),
        "window_21_start": date(2026, 6, 2),
        "total_msku": 2,
        "total_asin": 2,
        "current_fba_available": Decimal("12"),
        "current_fba_inbound": Decimal("3"),
        "current_stock_up_qty": Decimal("4"),
        "sales_qty_14d": Decimal("5"),
        "sales_qty_21d": Decimal("6"),
        "exited_return_msku": 1,
        "return_closure_rate": Decimal("0.5"),
    }
    cohort_items = [
        {"msku": "A", "observed_days": 21, "day21_cumulative_sales": Decimal("3.5")},
        {"msku": "B", "observed_days": 7, "day21_cumulative_sales": None},
    ]

    payload = build_payload(
        summary_row=summary_row,
        summary_by_status=[{"status": "returned_with_sales", "msku_count": 1}],
        cohort_by_day=[{"day": 0, "order_rate": Decimal("0.25")}],
        cohort_items=cohort_items,
        detail=[{"msku": "A", "sales_qty_21d": Decimal("6")}],
        generated_at=datetime(2026, 6, 24, 11, 0, 0),
    )

    assert payload["generated_at"] == "2026-06-24T11:00:00"
    assert payload["scope"]["run_id"] == 12
    assert payload["scope"]["latest_inventory_date"] == "2026-06-22"
    assert payload["summary"]["total_msku"] == 2
    assert payload["summary"]["return_closure_rate"] == 0.5
    assert payload["summary_by_status"] == [{"status": "returned_with_sales", "msku_count": 1}]
    assert payload["cohort_by_day"] == [{"day": 0, "order_rate": 0.25}]
    assert payload["cohort_items"][0]["day21_cumulative_sales"] == 3.5
    assert payload["detail"] == [{"msku": "A", "sales_qty_21d": 6.0}]
    assert payload["cohort_summary"] == {
        "cohort_msku": 2,
        "complete_21d_msku": 1,
        "partial_msku": 1,
        "day0_to_day21_window": "observable sample by return day",
    }


def test_write_payload_creates_parent_and_valid_json(tmp_path):
    output_path = tmp_path / "static" / "returned-product-tags-data.json"

    write_payload(output_path, {"generated_at": "2026-06-24T11:00:00", "summary": {"total_msku": 2}})

    assert json.loads(output_path.read_text(encoding="utf-8"))["summary"]["total_msku"] == 2


def test_default_output_path_points_to_dashboard_static_json():
    assert DEFAULT_OUTPUT_PATH == (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "returned-product-tags"
        / "returned-product-tags-data.json"
    )


def test_daily_11_scheduler_script_registers_returned_product_tags_task():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "register_returned_product_tags_daily_task.ps1").read_text(
        encoding="utf-8"
    )

    assert "run_returned_product_tags_update.ps1" in script
    assert "-At 11:00" in script
    assert "Register-ScheduledTask" in script
