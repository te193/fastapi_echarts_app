from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


STATION_ROLE_RULE_VERSION = "station_sales_role_v47_local"
STATION_ROLE_RULE_SOURCE = "dws_datasync.dws_标签详情表/label_id=13"
SUPPORTED_ROLE_PERIODS = (3, 7, 14, 30, 90)
REMOTE_ROLE_PERIODS = (7, 14, 30, 90)
REMOTE_ROLE_LABELS = {1301: "star", 1302: "potential", 1303: "dog", 1304: "problem"}

ROLE_DEFINITIONS = {
    "star": {"label": "明星产品", "rank": 4},
    "potential": {"label": "潜力产品", "rank": 3},
    "dog": {"label": "瘦狗产品", "rank": 2},
    "problem": {"label": "问题产品", "rank": 1},
}

FINANCE_BANDS = (
    ("below_0", "低于0%"),
    ("0_5", "0–5%"),
    ("5_10", "5–10%"),
    ("10_15", "10–15%"),
    ("15_20", "15–20%"),
    ("20_25", "20–25%"),
    ("25_30", "25–30%"),
    ("30_35", "30–35%"),
    ("at_least_35", "35%以上"),
)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def classify_station_sales_role(daily_sales: Any, margin_rate: Any, small_rank: Any) -> dict[str, Any]:
    daily = _decimal(daily_sales) or Decimal("0")
    margin = _decimal(margin_rate)
    rank = _decimal(small_rank)

    if daily <= 0 or margin is None or margin < Decimal("0.05") or rank in {None, Decimal("0"), Decimal("99999")}:
        return {"code": "problem", **ROLE_DEFINITIONS["problem"]}

    star_metrics = (
        (daily > Decimal("3") and margin >= Decimal("0.15"))
        or (Decimal("1") <= daily <= Decimal("3") and margin >= Decimal("0.25"))
    )
    potential_metrics = (
        (daily > Decimal("3") and Decimal("0.05") <= margin < Decimal("0.15"))
        or (Decimal("1") <= daily <= Decimal("3") and Decimal("0.10") <= margin < Decimal("0.25"))
    )

    if star_metrics and rank <= 50:
        return {"code": "star", **ROLE_DEFINITIONS["star"]}
    if (potential_metrics and rank <= 100) or (star_metrics and Decimal("51") <= rank <= 100):
        return {"code": "potential", **ROLE_DEFINITIONS["potential"]}
    return {"code": "dog", **ROLE_DEFINITIONS["dog"]}


def role_change(before: str | None, after: str | None) -> str:
    if before not in ROLE_DEFINITIONS or after not in ROLE_DEFINITIONS:
        return "unavailable"
    before_rank = ROLE_DEFINITIONS[before]["rank"]
    after_rank = ROLE_DEFINITIONS[after]["rank"]
    if after_rank > before_rank:
        return "up"
    if after_rank < before_rank:
        return "down"
    return "stable"


@dataclass(frozen=True)
class TrackingWindows:
    pre_start: date
    pre_end: date
    post_start: date
    post_end: date
    pre_days: int
    post_days: int


def tracking_windows(adjust_date: date, pre_days: int, post_days: int) -> TrackingWindows:
    if pre_days not in SUPPORTED_ROLE_PERIODS or post_days not in SUPPORTED_ROLE_PERIODS:
        raise ValueError("Unsupported station role period")
    return TrackingWindows(
        pre_start=adjust_date - timedelta(days=pre_days),
        pre_end=adjust_date - timedelta(days=1),
        post_start=adjust_date + timedelta(days=1),
        post_end=adjust_date + timedelta(days=post_days),
        pre_days=pre_days,
        post_days=post_days,
    )


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def normalize_remote_role_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    role_code = REMOTE_ROLE_LABELS.get(int(row.get("label_id") or 0))
    if role_code is None:
        raise ValueError(f"Unsupported station role label: {row.get('label_id')!r}")

    evidence = row.get("evidence_json") or {}
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid station role evidence_json") from exc
    if not isinstance(evidence, Mapping):
        raise ValueError("Invalid station role evidence_json")
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, Mapping):
        metrics = {}

    margin_percent = _decimal(metrics.get("tag_margin_rate"))
    margin_rate = margin_percent / Decimal("100") if margin_percent is not None else None
    role = ROLE_DEFINITIONS[role_code]
    return {
        "role_code": role_code,
        "role_label": role["label"],
        "role_rank": role["rank"],
        "daily_sales": _decimal(metrics.get("daily_sales")) or Decimal("0"),
        "sales_qty": _decimal(metrics.get("period_sales_qty")) or Decimal("0"),
        "sales_amount": _decimal(metrics.get("sales_amount")) or Decimal("0"),
        "order_profit": _decimal(metrics.get("tag_gross_profit")) or Decimal("0"),
        "margin_rate": margin_rate,
        "small_rank": int(metrics["small_rank"]) if metrics.get("small_rank") is not None else None,
        "small_rank_date": _date_value(metrics.get("small_rank_stat_date")),
        "source": "remote_dws",
        "freshness": str(row.get("freshness") or "fresh"),
        "source_data_date": _date_value(row.get("data_date")),
        "source_created_time": row.get("created_time") or row.get("source_created_time"),
        "rule_version": str(evidence.get("rule_version") or row.get("rule_version") or "v47"),
    }


def finance_price_band(price: Any, ladder: Mapping[int, Any] | None) -> dict[str, str]:
    amount = _decimal(price)
    if amount is None or not ladder or any(level not in ladder for level in range(0, 36, 5)):
        return {"code": "unavailable", "label": "无法归类"}

    thresholds = [_decimal(ladder[level]) for level in range(0, 36, 5)]
    if any(value is None for value in thresholds):
        return {"code": "unavailable", "label": "无法归类"}
    numeric_thresholds = [value for value in thresholds if value is not None]
    if any(left >= right for left, right in zip(numeric_thresholds, numeric_thresholds[1:])):
        return {"code": "invalid_ladder", "label": "价格阶梯异常"}

    if amount < numeric_thresholds[0]:
        code, label = FINANCE_BANDS[0]
        return {"code": code, "label": label}
    for index in range(1, len(numeric_thresholds)):
        if amount < numeric_thresholds[index]:
            code, label = FINANCE_BANDS[index]
            return {"code": code, "label": label}
    code, label = FINANCE_BANDS[-1]
    return {"code": code, "label": label}


def _ratio(numerator: Any, denominator: Any) -> Decimal | None:
    top = _decimal(numerator)
    bottom = _decimal(denominator)
    if top is None or bottom in {None, Decimal("0")}:
        return None
    return top / bottom


def build_station_role_tracking_row(
    raw: Mapping[str, Any],
    pre_days: int,
    post_days: int,
    latest_data_date: date,
    pre_snapshot: Mapping[str, Any] | None = None,
    post_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adjust_date = raw["adjust_date"]
    windows = tracking_windows(adjust_date, pre_days, post_days)
    pre_complete = pre_snapshot is not None or int(raw.get("pre_seen_days") or 0) >= windows.pre_days
    post_mature = post_snapshot is not None or latest_data_date >= windows.post_end
    post_complete = post_snapshot is not None or int(raw.get("post_seen_days") or 0) >= windows.post_days

    if not post_mature:
        data_status = "pending"
        data_message = f"调后{post_days}天窗口尚未结束"
    elif not pre_complete or not post_complete:
        data_status = "source_incomplete"
        data_message = "销售明细天数不足"
    else:
        data_status = "complete"
        data_message = ""

    pre_daily_sales = (
        _decimal(pre_snapshot.get("daily_sales"))
        if pre_snapshot is not None
        else (_decimal(raw.get("pre_sales_qty")) or Decimal("0")) / windows.pre_days
    )
    post_daily_sales = (
        _decimal(post_snapshot.get("daily_sales"))
        if post_snapshot is not None
        else (_decimal(raw.get("post_sales_qty")) or Decimal("0")) / windows.post_days
    )
    pre_margin = (
        _decimal(pre_snapshot.get("margin_rate"))
        if pre_snapshot is not None
        else _ratio(raw.get("pre_order_profit"), raw.get("pre_sales_amount"))
    )
    post_margin = (
        _decimal(post_snapshot.get("margin_rate"))
        if post_snapshot is not None
        else _ratio(raw.get("post_order_profit"), raw.get("post_sales_amount"))
    )
    pre_rank = pre_snapshot.get("small_rank") if pre_snapshot is not None else raw.get("pre_small_rank")
    post_rank = post_snapshot.get("small_rank") if post_snapshot is not None else raw.get("post_small_rank")

    pre_role = (
        {
            "code": pre_snapshot["role_code"],
            "label": pre_snapshot["role_label"],
            "rank": pre_snapshot["role_rank"],
        }
        if pre_snapshot is not None
        else classify_station_sales_role(pre_daily_sales, pre_margin, pre_rank)
        if pre_complete
        else None
    )
    post_role = (
        {
            "code": post_snapshot["role_code"],
            "label": post_snapshot["role_label"],
            "rank": post_snapshot["role_rank"],
        }
        if post_snapshot is not None
        else classify_station_sales_role(post_daily_sales, post_margin, post_rank)
        if post_mature and post_complete
        else None
    )

    ladder = {level: raw.get(f"margin_price_{level}") for level in range(0, 36, 5)}
    if int(raw.get("finance_ladder_variants") or 0) > 1:
        finance_before = finance_after = {"code": "invalid_ladder", "label": "价格阶梯异常"}
    else:
        finance_before = finance_price_band(raw.get("price_before"), ladder)
        finance_after = finance_price_band(raw.get("price_after"), ladder)
    finance_codes = [code for code, _ in FINANCE_BANDS]
    if finance_before["code"] not in finance_codes or finance_after["code"] not in finance_codes:
        finance_change = "unavailable"
    else:
        before_index = finance_codes.index(finance_before["code"])
        after_index = finance_codes.index(finance_after["code"])
        finance_change = "up" if after_index > before_index else "down" if after_index < before_index else "stable"

    row = dict(raw)
    row.update(
        {
            "post_period_days": post_days,
            "comparison_mode": "decision_30d" if pre_days == 30 else "equal_window" if pre_days == post_days else "custom",
            "pre_period_days": windows.pre_days,
            "pre_period_start": windows.pre_start,
            "pre_period_end": windows.pre_end,
            "post_period_start": windows.post_start,
            "post_period_end": windows.post_end,
            "pre_daily_sales": pre_daily_sales,
            "post_daily_sales": post_daily_sales,
            "pre_margin_rate": pre_margin,
            "post_margin_rate": post_margin,
            "pre_sales_qty": pre_snapshot.get("sales_qty") if pre_snapshot is not None else raw.get("pre_sales_qty"),
            "post_sales_qty": post_snapshot.get("sales_qty") if post_snapshot is not None else raw.get("post_sales_qty"),
            "pre_sales_amount": pre_snapshot.get("sales_amount") if pre_snapshot is not None else raw.get("pre_sales_amount"),
            "post_sales_amount": post_snapshot.get("sales_amount") if post_snapshot is not None else raw.get("post_sales_amount"),
            "pre_order_profit": pre_snapshot.get("order_profit") if pre_snapshot is not None else raw.get("pre_order_profit"),
            "post_order_profit": post_snapshot.get("order_profit") if post_snapshot is not None else raw.get("post_order_profit"),
            "pre_small_rank": pre_rank,
            "post_small_rank": post_rank,
            "pre_small_rank_date": pre_snapshot.get("small_rank_date") if pre_snapshot is not None else raw.get("pre_small_rank_date"),
            "post_small_rank_date": post_snapshot.get("small_rank_date") if post_snapshot is not None else raw.get("post_small_rank_date"),
            "role_before_code": pre_role["code"] if pre_role else None,
            "role_before_label": pre_role["label"] if pre_role else None,
            "role_before_rank": pre_role["rank"] if pre_role else None,
            "role_after_code": post_role["code"] if post_role else None,
            "role_after_label": post_role["label"] if post_role else None,
            "role_after_rank": post_role["rank"] if post_role else None,
            "role_change": role_change(pre_role["code"] if pre_role else None, post_role["code"] if post_role else None),
            "pre_role_source": pre_snapshot.get("source") if pre_snapshot is not None else "local_recomputed" if pre_complete else "unavailable",
            "post_role_source": post_snapshot.get("source") if post_snapshot is not None else "local_recomputed" if post_mature and post_complete else "unavailable",
            "pre_source_freshness": pre_snapshot.get("freshness", "fresh") if pre_snapshot is not None else "fresh",
            "post_source_freshness": post_snapshot.get("freshness", "fresh") if post_snapshot is not None else "fresh",
            "pre_source_data_date": pre_snapshot.get("source_data_date") if pre_snapshot is not None else windows.pre_end if pre_complete else None,
            "post_source_data_date": post_snapshot.get("source_data_date") if post_snapshot is not None else windows.post_end if post_mature and post_complete else None,
            "pre_source_created_time": pre_snapshot.get("source_created_time") if pre_snapshot is not None else None,
            "post_source_created_time": post_snapshot.get("source_created_time") if post_snapshot is not None else None,
            "data_status": data_status,
            "data_message": data_message,
            "finance_band_before_code": finance_before["code"],
            "finance_band_before_label": finance_before["label"],
            "finance_band_after_code": finance_after["code"],
            "finance_band_after_label": finance_after["label"],
            "finance_change": finance_change,
            "station_sales_role_rule_version": STATION_ROLE_RULE_VERSION,
            "station_sales_role_rule_source": STATION_ROLE_RULE_SOURCE,
        }
    )
    return row
