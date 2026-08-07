from datetime import date, timedelta
from decimal import Decimal

from etl.replenishment_sales_spike import (
    DailySalesPoint,
    SpikeBand,
    SpikeCalibration,
    SpikeStatus,
    detect_sales_spike,
    median_and_mad,
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
