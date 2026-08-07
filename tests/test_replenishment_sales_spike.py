from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from etl.dashboard_daily_update import SchemaConfig

from etl.replenishment_sales_spike import (
    DailySalesPoint,
    SpikeBand,
    SpikeCalibration,
    SpikeStatus,
    detect_sales_spike,
    median_and_mad,
    refresh_replenishment_sales_spike_flags,
    write_spike_calibration,
)


def calibration() -> SpikeCalibration:
    return SpikeCalibration(
        lookback_days=30,
        min_history_days=14,
        scale_floor=Decimal("1"),
        bands=(
            SpikeBand(
                baseline_upper=None,
                suspected_score_threshold=Decimal("12"),
                recovery_mean_upper=Decimal("12"),
            ),
        ),
    )


def points(values: list[int], start: date = date(2026, 7, 8)) -> list[DailySalesPoint]:
    return [
        DailySalesPoint(day=start + timedelta(days=index), sales_qty=Decimal(value))
        for index, value in enumerate(values)
    ]


def test_median_and_mad_are_not_pulled_up_by_one_extreme_day():
    baseline, mad = median_and_mad(
        [Decimal(2), Decimal(4), Decimal(5), Decimal(6), Decimal(168)]
    )

    assert baseline == Decimal(5)
    assert mad == Decimal(1)


def test_latest_extreme_day_is_suspected_immediately():
    result = detect_sales_spike(points([5] * 29 + [168]), calibration())

    assert result.status == SpikeStatus.SUSPECTED
    assert result.highlight is True
    assert result.spike_date == date(2026, 8, 6)


def test_extreme_day_followed_by_three_normal_days_is_confirmed():
    result = detect_sales_spike(points([5] * 26 + [168, 5, 2, 2]), calibration())

    assert result.status == SpikeStatus.CONFIRMED_RECOVERED
    assert result.highlight is True
    assert result.spike_qty == Decimal(168)


def test_extreme_day_followed_by_sustained_high_sales_is_not_persistently_highlighted():
    result = detect_sales_spike(points([5] * 26 + [80, 70, 65, 60]), calibration())

    assert result.status == SpikeStatus.SUSTAINED_GROWTH
    assert result.highlight is False
    assert result.spike_date == date(2026, 8, 3)


def test_history_shorter_than_fourteen_days_defers_to_legacy_rule():
    result = detect_sales_spike(points([5] * 12 + [168]), calibration())

    assert result.status == SpikeStatus.NORMAL
    assert result.highlight is False
    assert result.reason == "有效历史不足14天，使用现有3天/7天规则兜底"


def test_jc029b_spike_remains_highlighted_after_leaving_three_day_window():
    normal_26_days = [
        6,
        5,
        2,
        5,
        7,
        6,
        6,
        3,
        8,
        5,
        2,
        6,
        6,
        7,
        3,
        6,
        1,
        4,
        5,
        6,
        11,
        11,
        6,
        1,
        4,
        5,
    ]

    result = detect_sales_spike(points(normal_26_days + [168, 5, 2, 2]), calibration())

    assert result.status == SpikeStatus.CONFIRMED_RECOVERED
    assert result.highlight is True
    assert result.spike_date == date(2026, 8, 3)
    assert result.spike_qty == Decimal(168)


class SpikeRefreshCursor:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.executed = []
        self.updated_sql = ""
        self.updated_params = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.result_sets.pop(0)

    def executemany(self, sql, params):
        self.updated_sql = sql
        self.updated_params = list(params)
        self.rowcount = len(self.updated_params) * 2


class SpikeRefreshConnection:
    def __init__(self, result_sets):
        self.test_cursor = SpikeRefreshCursor(result_sets)
        self.commit_count = 0

    def cursor(self):
        return self.test_cursor

    def commit(self):
        self.commit_count += 1


def test_refresh_propagates_group_status_without_touching_replenishment_fields(tmp_path):
    config_path = tmp_path / "spike.json"
    write_spike_calibration(calibration(), config_path, calibrated_at=date(2026, 8, 7))
    sales_rows = [
        {
            "dt_date": date(2026, 7, 8) + timedelta(days=index),
            "country_category": "欧洲站",
            "max_asin": "B0CX51133J",
            "sales_qty": Decimal(value),
        }
        for index, value in enumerate([5] * 26 + [168, 5, 2, 2])
    ]
    conn = SpikeRefreshConnection(
        [
            [
                {
                    "country_category": "欧洲站",
                    "seller_name_new": "Joochees",
                    "seller_sku_adj": "JC029b",
                    "max_asin": "B0CX51133J",
                },
                {
                    "country_category": "欧洲站",
                    "seller_name_new": "meeloo",
                    "seller_sku_adj": "KQ-UFY7-HWK2",
                    "max_asin": "B0CX51133J",
                },
            ],
            sales_rows,
        ]
    )

    affected = refresh_replenishment_sales_spike_flags(
        conn,
        SchemaConfig("etl_datasync_test", "etl_datasync", "dwd_datasync", "pricing"),
        snapshot_date=date(2026, 8, 7),
        biz_date=date(2026, 8, 6),
        calibration_path=Path(config_path),
    )

    assert affected == 2
    assert len(conn.test_cursor.updated_params) == 1
    update = conn.test_cursor.updated_params[0]
    assert update["sales_spike_status"] == "confirmed_recovered"
    assert update["sales_spike_flag"] == 1
    assert update["sales_spike_date"] == date(2026, 8, 3)
    assert update["sales_spike_qty"] == Decimal(168)
    assert update["snapshot_date"] == date(2026, 8, 7)
    assert update["max_asin"] == "B0CX51133J"
    for forbidden in (
        "daily_avg_sales",
        "support_replenish_level",
        "replenish_need_qty",
        "replenish_qty",
        "replenish_box_qty",
        "replenish_cost",
    ):
        assert forbidden not in conn.test_cursor.updated_sql


def test_refresh_does_not_treat_missing_history_as_zero_sales(tmp_path):
    config_path = tmp_path / "spike.json"
    write_spike_calibration(calibration(), config_path, calibrated_at=date(2026, 8, 7))
    conn = SpikeRefreshConnection(
        [
            [
                {
                    "country_category": "欧洲站",
                    "seller_name_new": "new-store",
                    "seller_sku_adj": "NEW-1",
                    "max_asin": "B0NEW",
                }
            ],
            [
                {
                    "dt_date": date(2026, 8, 6),
                    "country_category": "欧洲站",
                    "max_asin": "B0NEW",
                    "sales_qty": Decimal(168),
                }
            ],
        ]
    )

    refresh_replenishment_sales_spike_flags(
        conn,
        SchemaConfig("etl_datasync_test", "etl_datasync", "dwd_datasync", "pricing"),
        snapshot_date=date(2026, 8, 7),
        biz_date=date(2026, 8, 6),
        calibration_path=config_path,
    )

    update = conn.test_cursor.updated_params[0]
    assert update["sales_spike_status"] == "normal"
    assert update["sales_spike_flag"] == 0
    assert update["sales_spike_reason"] == "有效历史不足14天，使用现有3天/7天规则兜底"
