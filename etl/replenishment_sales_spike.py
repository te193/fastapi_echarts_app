from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Sequence


ROBUST_SCALE_FACTOR = Decimal("1.4826")


class SpikeStatus(str, Enum):
    NORMAL = "normal"
    SUSPECTED = "suspected"
    CONFIRMED_RECOVERED = "confirmed_recovered"
    SUSTAINED_GROWTH = "sustained_growth"


class SpikeConfigurationError(ValueError):
    pass


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
class CalibrationSample:
    baseline: Decimal
    score: Decimal
    following_three_day_mean: Decimal


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


def decimal_quantile(values: Sequence[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("分位数样本不能为空")
    if quantile < 0 or quantile > 1:
        raise ValueError("分位数必须在0到1之间")
    position = quantile * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def calibrate_spike_bands(samples: Sequence[CalibrationSample]) -> SpikeCalibration:
    if not samples:
        raise ValueError("爆单校准样本不能为空")

    baselines = [sample.baseline for sample in samples]
    candidate_bounds = [
        decimal_quantile(baselines, quantile)
        for quantile in (Decimal("0.25"), Decimal("0.50"), Decimal("0.75"))
    ]
    bounds: list[Decimal | None] = []
    for bound in candidate_bounds:
        if not bounds or bound != bounds[-1]:
            bounds.append(bound)
    bounds.append(None)

    bands: list[SpikeBand] = []
    lower_bound: Decimal | None = None
    for upper_bound in bounds:
        group = [
            sample
            for sample in samples
            if (lower_bound is None or sample.baseline > lower_bound)
            and (upper_bound is None or sample.baseline <= upper_bound)
        ]
        if not group:
            lower_bound = upper_bound
            continue
        positive_scores = [sample.score for sample in group if sample.score > 0]
        if not positive_scores:
            positive_scores = [Decimal("1")]
        suspected_threshold = decimal_quantile(positive_scores, Decimal("0.995"))
        normal_means = [
            sample.following_three_day_mean
            for sample in group
            if sample.score < suspected_threshold
        ]
        if not normal_means:
            normal_means = [sample.following_three_day_mean for sample in group]
        bands.append(
            SpikeBand(
                baseline_upper=upper_bound,
                suspected_score_threshold=suspected_threshold,
                recovery_mean_upper=decimal_quantile(normal_means, Decimal("0.95")),
            )
        )
        lower_bound = upper_bound

    if not bands or bands[-1].baseline_upper is not None:
        raise SpikeConfigurationError("爆单校准配置缺少兜底销量分组")
    return SpikeCalibration(
        lookback_days=30,
        min_history_days=14,
        scale_floor=Decimal("1"),
        bands=tuple(bands),
    )


def write_spike_calibration(
    calibration: SpikeCalibration,
    path: Path,
    calibrated_at: date,
) -> None:
    payload = {
        "version": 1,
        "calibrated_at": calibrated_at.isoformat(),
        "lookback_days": calibration.lookback_days,
        "min_history_days": calibration.min_history_days,
        "scale_floor": str(calibration.scale_floor),
        "bands": [
            {
                "baseline_upper": None if band.baseline_upper is None else str(band.baseline_upper),
                "suspected_score_threshold": str(band.suspected_score_threshold),
                "recovery_mean_upper": str(band.recovery_mean_upper),
            }
            for band in calibration.bands
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_spike_calibration(path: Path) -> SpikeCalibration:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bands = tuple(
            SpikeBand(
                baseline_upper=(
                    None if item.get("baseline_upper") is None else Decimal(str(item["baseline_upper"]))
                ),
                suspected_score_threshold=Decimal(str(item["suspected_score_threshold"])),
                recovery_mean_upper=Decimal(str(item["recovery_mean_upper"])),
            )
            for item in payload["bands"]
        )
        calibration = SpikeCalibration(
            lookback_days=int(payload["lookback_days"]),
            min_history_days=int(payload["min_history_days"]),
            scale_floor=Decimal(str(payload["scale_floor"])),
            bands=bands,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
        raise SpikeConfigurationError(f"无法读取爆单校准配置: {exc}") from exc
    if not calibration.bands or calibration.bands[-1].baseline_upper is not None:
        raise SpikeConfigurationError("爆单校准配置缺少兜底销量分组")
    return calibration


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
