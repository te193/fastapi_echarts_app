from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from statistics import median
from typing import Sequence


ROBUST_SCALE_FACTOR = Decimal("1.4826")


class SpikeStatus(str, Enum):
    NORMAL = "normal"
    SUSPECTED = "suspected"
    CONFIRMED_RECOVERED = "confirmed_recovered"
    SUSTAINED_GROWTH = "sustained_growth"


@dataclass(frozen=True)
class DailySalesPoint:
    day: date
    sales_qty: Decimal


@dataclass(frozen=True)
class SpikeBand:
    baseline_upper: Decimal | None
    suspected_score_threshold: Decimal
    recovery_mean_upper: Decimal


@dataclass(frozen=True)
class SpikeCalibration:
    lookback_days: int
    min_history_days: int
    scale_floor: Decimal
    bands: tuple[SpikeBand, ...]


@dataclass(frozen=True)
class SpikeDetection:
    status: SpikeStatus
    highlight: bool
    spike_date: date | None = None
    spike_qty: Decimal = Decimal("0")
    baseline: Decimal = Decimal("0")
    score: Decimal = Decimal("0")
    reason: str = ""


@dataclass(frozen=True)
class _ScoredPoint:
    point: DailySalesPoint
    baseline: Decimal
    score: Decimal
    band: SpikeBand
    is_anomaly: bool


def median_and_mad(values: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    if not values:
        raise ValueError("MAD样本不能为空")
    center = Decimal(median(values))
    deviations = [abs(value - center) for value in values]
    return center, Decimal(median(deviations))


def robust_score(
    value: Decimal,
    baseline: Decimal,
    mad: Decimal,
    scale_floor: Decimal,
) -> Decimal:
    scale = max(ROBUST_SCALE_FACTOR * mad, scale_floor)
    return (value - baseline) / scale


def select_band(baseline: Decimal, calibration: SpikeCalibration) -> SpikeBand:
    for band in calibration.bands:
        if band.baseline_upper is None or baseline <= band.baseline_upper:
            return band
    raise ValueError("爆单校准配置缺少兜底销量分组")


def detect_sales_spike(
    points: Sequence[DailySalesPoint],
    calibration: SpikeCalibration,
) -> SpikeDetection:
    window = sorted(points, key=lambda item: item.day)[-calibration.lookback_days :]
    if len(window) - 1 < calibration.min_history_days:
        return SpikeDetection(
            status=SpikeStatus.NORMAL,
            highlight=False,
            reason=f"有效历史不足{calibration.min_history_days}天，使用现有3天/7天规则兜底",
        )

    scored: list[_ScoredPoint] = []
    for index, point in enumerate(window):
        baseline_values = [item.sales_qty for offset, item in enumerate(window) if offset != index]
        baseline, mad = median_and_mad(baseline_values)
        band = select_band(baseline, calibration)
        score = robust_score(point.sales_qty, baseline, mad, calibration.scale_floor)
        scored.append(
            _ScoredPoint(
                point=point,
                baseline=baseline,
                score=score,
                band=band,
                is_anomaly=score >= band.suspected_score_threshold,
            )
        )

    anomaly_indexes = [index for index, item in enumerate(scored) if item.is_anomaly]
    if not anomaly_indexes:
        return SpikeDetection(status=SpikeStatus.NORMAL, highlight=False, reason="最近30天未发现单日爆单")

    events: list[list[int]] = []
    for index in anomaly_indexes:
        if not events or index - events[-1][-1] > 3:
            events.append([index])
        else:
            events[-1].append(index)

    spike_index = events[-1][0]
    spike = scored[spike_index]
    following = scored[spike_index + 1 : spike_index + 4]
    common = {
        "spike_date": spike.point.day,
        "spike_qty": spike.point.sales_qty,
        "baseline": spike.baseline,
        "score": spike.score,
    }
    if len(following) < 3:
        return SpikeDetection(
            status=SpikeStatus.SUSPECTED,
            highlight=True,
            reason="最新单日销量显著偏离常态，等待3个完整销售日确认",
            **common,
        )

    following_mean = sum((item.point.sales_qty for item in following), Decimal("0")) / Decimal(3)
    recovered = all(not item.is_anomaly for item in following) and following_mean <= spike.band.recovery_mean_upper
    if recovered:
        return SpikeDetection(
            status=SpikeStatus.CONFIRMED_RECOVERED,
            highlight=True,
            reason="单日爆单后连续3个完整销售日已恢复正常",
            **common,
        )
    return SpikeDetection(
        status=SpikeStatus.SUSTAINED_GROWTH,
        highlight=False,
        reason="异常后销量持续高位，不作为一次性爆单长期提醒",
        **common,
    )
