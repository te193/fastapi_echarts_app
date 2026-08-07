from __future__ import annotations

import json
from dataclasses import dataclass
from collections import defaultdict
from datetime import date, timedelta
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


def refresh_replenishment_sales_spike_flags(
    conn,
    schemas,
    *,
    snapshot_date: date,
    biz_date: date,
    calibration_path: Path,
) -> int:
    calibration = load_spike_calibration(calibration_path)
    schema = schemas.target_schema.replace("`", "``")
    result_table = f"`{schema}`.`dashboard_pur_plan_replenish_data`"
    sales_table = f"`{schema}`.`dashboard_product_performance_daily`"
    start_date = biz_date - timedelta(days=calibration.lookback_days - 1)

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            select distinct
                country_category,
                seller_name_new,
                seller_sku_adj,
                max_asin
            from {result_table}
            where cur_date = %(snapshot_date)s
              and max_asin is not null
              and max_asin <> ''
            """,
            {"snapshot_date": snapshot_date},
        )
        mappings = cursor.fetchall()
        if not mappings:
            return 0

        cursor.execute(
            f"""
            select
                p.dt_date,
                mapping.country_category,
                mapping.max_asin,
                sum(coalesce(p.sales_qty, 0)) as sales_qty
            from {sales_table} p
            inner join (
                select distinct
                    country_category,
                    seller_name_new,
                    seller_sku_adj,
                    max_asin
                from {result_table}
                where cur_date = %(snapshot_date)s
                  and max_asin is not null
                  and max_asin <> ''
            ) mapping
              on mapping.country_category = p.country_category
             and mapping.seller_name_new = p.seller_name_new
             and mapping.seller_sku_adj = p.seller_sku_adj
            where p.dt_date between %(start_date)s and %(biz_date)s
            group by p.dt_date, mapping.country_category, mapping.max_asin
            order by mapping.country_category, mapping.max_asin, p.dt_date
            """,
            {
                "snapshot_date": snapshot_date,
                "start_date": start_date,
                "biz_date": biz_date,
            },
        )
        sales_rows = cursor.fetchall()

        group_keys = {
            (str(row["country_category"]), str(row["max_asin"]))
            for row in mappings
            if row.get("max_asin")
        }
        sales_by_group_day: dict[tuple[str, str], dict[date, Decimal]] = defaultdict(dict)
        for row in sales_rows:
            key = (str(row["country_category"]), str(row["max_asin"]))
            sales_by_group_day[key][row["dt_date"]] = Decimal(str(row["sales_qty"] or 0))

        update_params = []
        for country_category, max_asin in sorted(group_keys):
            daily_sales = sales_by_group_day.get((country_category, max_asin), {})
            if daily_sales:
                series_start = max(start_date, min(daily_sales))
                series_days = (biz_date - series_start).days + 1
                points = [
                    DailySalesPoint(
                        day=series_start + timedelta(days=offset),
                        sales_qty=daily_sales.get(
                            series_start + timedelta(days=offset), Decimal("0")
                        ),
                    )
                    for offset in range(series_days)
                ]
            else:
                points = []
            detection = detect_sales_spike(points, calibration)
            update_params.append(
                {
                    "sales_spike_status": detection.status.value,
                    "sales_spike_flag": int(detection.highlight),
                    "sales_spike_date": detection.spike_date,
                    "sales_spike_qty": detection.spike_qty,
                    "sales_spike_baseline": detection.baseline,
                    "sales_spike_score": detection.score,
                    "sales_spike_reason": detection.reason,
                    "snapshot_date": snapshot_date,
                    "country_category": country_category,
                    "max_asin": max_asin,
                }
            )

        cursor.executemany(
            f"""
            update {result_table}
            set sales_spike_status = %(sales_spike_status)s,
                sales_spike_flag = %(sales_spike_flag)s,
                sales_spike_date = %(sales_spike_date)s,
                sales_spike_qty = %(sales_spike_qty)s,
                sales_spike_baseline = %(sales_spike_baseline)s,
                sales_spike_score = %(sales_spike_score)s,
                sales_spike_reason = %(sales_spike_reason)s
            where cur_date = %(snapshot_date)s
              and country_category = %(country_category)s
              and binary max_asin = binary %(max_asin)s
            """,
            update_params,
        )
        affected_rows = max(cursor.rowcount, 0)
    conn.commit()
    return affected_rows
