from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys
from typing import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.dashboard_daily_update import connect_target
from etl.replenishment_sales_spike import (
    CalibrationSample,
    DailySalesPoint,
    SpikeCalibration,
    SpikeStatus,
    calibrate_spike_bands,
    detect_sales_spike,
    median_and_mad,
    robust_score,
    select_band,
    write_spike_calibration,
)
from etl.replenishment_update import apply_database_ini_env, parse_day


GroupKey = tuple[str, str]


def fetch_group_daily_sales(
    conn,
    *,
    snapshot_date: date,
    start_date: date,
    end_date: date,
) -> dict[GroupKey, list[DailySalesPoint]]:
    sql = """
        SELECT
            p.dt_date,
            mapping.country_category,
            mapping.max_asin,
            SUM(COALESCE(p.sales_qty, 0)) AS sales_qty
        FROM dashboard_product_performance_daily AS p
        INNER JOIN (
            SELECT DISTINCT
                country_category,
                seller_name_new,
                seller_sku_adj,
                max_asin
            FROM dashboard_pur_plan_replenish_data
            WHERE cur_date = %(snapshot_date)s
              AND max_asin IS NOT NULL
              AND max_asin <> ''
        ) AS mapping
          ON mapping.country_category = p.country_category
         AND mapping.seller_name_new = p.seller_name_new
         AND mapping.seller_sku_adj = p.seller_sku_adj
        WHERE p.dt_date BETWEEN %(start_date)s AND %(end_date)s
        GROUP BY p.dt_date, mapping.country_category, mapping.max_asin
        ORDER BY mapping.country_category, mapping.max_asin, p.dt_date
    """
    with conn.cursor() as cursor:
        cursor.execute(
            sql,
            {
                "snapshot_date": snapshot_date,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        rows = cursor.fetchall()

    grouped: dict[GroupKey, list[DailySalesPoint]] = defaultdict(list)
    for row in rows:
        key = (str(row["country_category"]), str(row["max_asin"]))
        grouped[key].append(
            DailySalesPoint(
                day=row["dt_date"],
                sales_qty=Decimal(str(row["sales_qty"] or 0)),
            )
        )
    return dict(grouped)


def build_calibration_samples(
    grouped_points: Mapping[GroupKey, Sequence[DailySalesPoint]],
    *,
    lookback_days: int = 30,
    min_history_days: int = 14,
    scale_floor: Decimal = Decimal("1"),
) -> list[CalibrationSample]:
    samples: list[CalibrationSample] = []
    for points in grouped_points.values():
        ordered = sorted(points, key=lambda point: point.day)
        for index in range(min_history_days, len(ordered) - 3):
            history = ordered[max(0, index - lookback_days) : index]
            if len(history) < min_history_days:
                continue
            baseline, mad = median_and_mad([point.sales_qty for point in history])
            samples.append(
                CalibrationSample(
                    baseline=baseline,
                    score=robust_score(
                        ordered[index].sales_qty,
                        baseline,
                        mad,
                        scale_floor,
                    ),
                    following_three_day_mean=sum(
                        (point.sales_qty for point in ordered[index + 1 : index + 4]),
                        Decimal("0"),
                    )
                    / Decimal(3),
                )
            )
    return samples


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.001")), "f")


def write_shadow_report(
    *,
    calibration: SpikeCalibration,
    grouped_points: Mapping[GroupKey, Sequence[DailySalesPoint]],
    output_path: Path,
    as_of_date: date,
    sample_count: int,
) -> None:
    final_results = [
        (key, detect_sales_spike(points, calibration))
        for key, points in sorted(grouped_points.items())
    ]
    active_results = [item for item in final_results if item[1].spike_date is not None]
    highest = sorted(active_results, key=lambda item: item[1].score, reverse=True)[:20]
    critical = sorted(
        active_results,
        key=lambda item: abs(
            item[1].score
            - select_band(item[1].baseline, calibration).suspected_score_threshold
        ),
    )[:20]

    all_days = sorted({point.day for points in grouped_points.values() for point in points})
    daily_rows: list[tuple[date, int, int, int]] = []
    for day in all_days:
        if day > as_of_date:
            continue
        counts = defaultdict(int)
        for points in grouped_points.values():
            eligible = [point for point in points if point.day <= day]
            counts[detect_sales_spike(eligible, calibration).status] += 1
        daily_rows.append(
            (
                day,
                counts[SpikeStatus.SUSPECTED],
                counts[SpikeStatus.CONFIRMED_RECOVERED],
                counts[SpikeStatus.SUSTAINED_GROWTH],
            )
        )

    jc_result = next(
        (result for (country, asin), result in final_results if asin == "B0CX51133J"),
        None,
    )
    lines = [
        f"# {as_of_date.isoformat()} 补货爆单高亮90天影子回测报告",
        "",
        "## 回放口径",
        "",
        f"- 只读回放：是（read_only=true）",
        f"- 截止完整销售日：{as_of_date.isoformat()}（T+1口径）",
        f"- 产品组数：{len(grouped_points)}",
        f"- 滚动校准样本数：{sample_count}",
        "- 日常识别窗口：30个完整销售日；90天仅用于影子校准。",
        "",
        "## 各销量体量组阈值",
        "",
        "| 基线日销上界 | 疑似异常分数（P99.5） | 回落三日均值上界（P95） |",
        "| ---: | ---: | ---: |",
    ]
    for band in calibration.bands:
        lines.append(
            "| {} | {} | {} |".format(
                "无上限" if band.baseline_upper is None else _fmt(band.baseline_upper),
                _fmt(band.suspected_score_threshold),
                _fmt(band.recovery_mean_upper),
            )
        )

    lines.extend(
        [
            "",
            "## 每日状态统计",
            "",
            "| 日期 | 疑似 | 确认回落 | 持续增长 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for day, suspected, recovered, growth in daily_rows:
        lines.append(f"| {day.isoformat()} | {suspected} | {recovered} | {growth} |")

    def append_samples(title: str, rows) -> None:
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| 站点 | ASIN | 状态 | 爆单日 | 爆单量 | 基线 | 分数 |",
                "| --- | --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for (country, asin), result in rows:
            lines.append(
                f"| {country} | {asin} | {result.status.value} | "
                f"{result.spike_date or ''} | {_fmt(result.spike_qty)} | "
                f"{_fmt(result.baseline)} | {_fmt(result.score)} |"
            )
        if not rows:
            lines.append("| - | - | - | - | 0 | 0 | 0 |")

    append_samples("最高分样本", highest)
    append_samples("临界样本", critical)
    lines.extend(["", "## JC029b / B0CX51133J", ""])
    if jc_result is None:
        lines.append("当前快照未找到 B0CX51133J 产品组。")
    else:
        lines.extend(
            [
                f"- 状态：`{jc_result.status.value}`",
                f"- 是否持续标黄：`{str(jc_result.highlight).lower()}`",
                f"- 爆单日：{jc_result.spike_date or '-'}",
                f"- 爆单销量：{_fmt(jc_result.spike_qty)}",
                f"- 稳健基线：{_fmt(jc_result.baseline)}",
                f"- 异常分数：{_fmt(jc_result.score)}",
            ]
        )
    lines.extend(
        [
            "",
            "## 结论与边界",
            "",
            "固定配置只影响Excel高亮元数据，不参与日销、层级、补货数量、箱数或货值计算。",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="补货爆单高亮90天只读校准")
    parser.add_argument("--as-of-date", type=parse_day, required=True)
    parser.add_argument("--snapshot-date", type=parse_day)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.days < 34:
        raise SystemExit("--days 至少为34，才能包含30日基线和后续3日")
    snapshot_date = args.snapshot_date or args.as_of_date + timedelta(days=1)
    start_date = args.as_of_date - timedelta(days=args.days - 1)

    apply_database_ini_env()
    with connect_target() as conn:
        grouped = fetch_group_daily_sales(
            conn,
            snapshot_date=snapshot_date,
            start_date=start_date,
            end_date=args.as_of_date,
        )
    samples = build_calibration_samples(grouped)
    calibration = calibrate_spike_bands(samples)
    write_spike_calibration(calibration, args.output_config, calibrated_at=args.as_of_date)
    write_shadow_report(
        calibration=calibration,
        grouped_points=grouped,
        output_path=args.output_report,
        as_of_date=args.as_of_date,
        sample_count=len(samples),
    )
    print(
        f"read_only=true groups={len(grouped)} samples={len(samples)} "
        f"config={args.output_config} report={args.output_report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
