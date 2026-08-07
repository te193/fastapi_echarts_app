from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest

from etl.replenishment_sales_spike import (
    CalibrationSample,
    DailySalesPoint,
    SpikeConfigurationError,
    calibrate_spike_bands,
    decimal_quantile,
    load_spike_calibration,
    write_spike_calibration,
)
from scripts.calibrate_replenishment_sales_spike import (
    build_calibration_samples,
    fetch_group_daily_sales,
    write_shadow_report,
)


def calibration_samples() -> list[CalibrationSample]:
    return [
        CalibrationSample(
            baseline=Decimal(index),
            score=Decimal(index),
            following_three_day_mean=Decimal(index + 1),
        )
        for index in range(1, 41)
    ]


def test_decimal_quantile_uses_linear_interpolation():
    values = [Decimal(1), Decimal(2), Decimal(3), Decimal(4)]

    assert decimal_quantile(values, Decimal("0.25")) == Decimal("1.75")
    assert decimal_quantile(values, Decimal("0.50")) == Decimal("2.5")
    assert decimal_quantile(values, Decimal("0.995")) == Decimal("3.985")


def test_calibration_builds_data_driven_volume_bands():
    calibration = calibrate_spike_bands(calibration_samples())

    assert calibration.lookback_days == 30
    assert calibration.min_history_days == 14
    assert calibration.scale_floor == Decimal(1)
    assert len(calibration.bands) == 4
    assert [band.baseline_upper for band in calibration.bands] == [
        Decimal("10.75"),
        Decimal("20.5"),
        Decimal("30.25"),
        None,
    ]
    assert calibration.bands[-1].suspected_score_threshold == Decimal("39.955")
    assert calibration.bands[-1].recovery_mean_upper == Decimal("39.6")


def test_calibration_round_trip_preserves_decimal_values(tmp_path):
    path = tmp_path / "spike.json"
    expected = calibrate_spike_bands(calibration_samples())

    write_spike_calibration(expected, path, calibrated_at=date(2026, 8, 7))

    assert load_spike_calibration(path) == expected
    assert '"calibrated_at": "2026-08-07"' in path.read_text(encoding="utf-8")


def test_load_rejects_config_without_unbounded_fallback_band(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(
        """
        {
          "lookback_days": 30,
          "min_history_days": 14,
          "scale_floor": "1",
          "bands": [
            {
              "baseline_upper": "5",
              "suspected_score_threshold": "12",
              "recovery_mean_upper": "8"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(SpikeConfigurationError, match="兜底销量分组"):
        load_spike_calibration(path)


class ReadOnlyCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed_sql = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        normalized = sql.lstrip().lower()
        if not normalized.startswith("select"):
            raise AssertionError(f"校准脚本执行了非只读SQL: {normalized.split()[0]}")
        self.executed_sql.append((sql, params))

    def fetchall(self):
        return self.rows


class ReadOnlyConnection:
    def __init__(self, rows):
        self.test_cursor = ReadOnlyCursor(rows)

    def cursor(self):
        return self.test_cursor


def test_fetch_group_daily_sales_uses_read_only_query_and_groups_points():
    conn = ReadOnlyConnection(
        [
            {
                "dt_date": date(2026, 8, 5),
                "country_category": "欧洲站",
                "max_asin": "B0CX51133J",
                "sales_qty": Decimal(168),
            },
            {
                "dt_date": date(2026, 8, 6),
                "country_category": "欧洲站",
                "max_asin": "B0CX51133J",
                "sales_qty": Decimal(5),
            },
        ]
    )

    grouped = fetch_group_daily_sales(
        conn,
        snapshot_date=date(2026, 8, 7),
        start_date=date(2026, 5, 9),
        end_date=date(2026, 8, 6),
    )

    assert len(conn.test_cursor.executed_sql) == 1
    assert [(point.day, point.sales_qty) for point in grouped[("欧洲站", "B0CX51133J")]] == [
        (date(2026, 8, 5), Decimal(168)),
        (date(2026, 8, 6), Decimal(5)),
    ]


def test_build_calibration_samples_uses_prior_history_and_three_following_days():
    daily_points = points = [
        DailySalesPoint(day=date(2026, 7, 1) + timedelta(days=index), sales_qty=Decimal(5))
        for index in range(40)
    ]
    points[20] = DailySalesPoint(day=points[20].day, sales_qty=Decimal(80))

    samples = build_calibration_samples({("欧洲站", "B0CX51133J"): daily_points})

    assert len(samples) == 23
    spike_sample = samples[6]
    assert spike_sample.baseline == Decimal(5)
    assert spike_sample.score == Decimal(75)
    assert spike_sample.following_three_day_mean == Decimal(5)


def test_script_entrypoint_can_run_directly():
    result = subprocess.run(
        [sys.executable, "scripts/calibrate_replenishment_sales_spike.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--as-of-date" in result.stdout


def test_shadow_report_contains_review_sections_and_jc029b_result(tmp_path):
    start = date(2026, 7, 8)
    grouped = {
        ("欧洲站", "B0CX51133J"): [
            DailySalesPoint(day=start + timedelta(days=index), sales_qty=Decimal(value))
            for index, value in enumerate([5] * 26 + [168, 5, 2, 2])
        ]
    }
    output = tmp_path / "report.md"

    write_shadow_report(
        calibration=calibrate_spike_bands(calibration_samples()),
        grouped_points=grouped,
        output_path=output,
        as_of_date=date(2026, 8, 6),
        sample_count=40,
    )

    report = output.read_text(encoding="utf-8")
    assert "每日状态统计" in report
    assert "各销量体量组阈值" in report
    assert "最高分样本" in report
    assert "临界样本" in report
    assert "JC029b / B0CX51133J" in report
