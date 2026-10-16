"""Derive evidence-backed bid trials for the XMind conditions, without writes to ads."""
from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from statistics import median


ROOT = Path("outputs/问题产品广告竞价条件分析")
TARGET_ACOS = Decimal("0.20")
MAX_STEP = Decimal("0.50")  # Conservative single-step guard, not a learned effect.
TICK = Decimal("0.01")
FLOOR = Decimal("0.10")
CONDITIONS = (
    "pause_high_click_zero_sale", "keep_low_evidence", "decrease_over_max_bid",
    "decrease_zero_sale_clicks_40", "decrease_zero_sale_clicks_25",
    "decrease_zero_sale_clicks_15_or_cost_15", "decrease_acos_gt_50",
    "decrease_acos_gt_40", "decrease_acos_gt_30", "decrease_acos_gt_20",
    *(f"increase_exact_phrase_{i}" for i in range(1, 5)),
    *(f"increase_broad_close_complements_{i}" for i in range(1, 4)),
    *(f"increase_loose_substitutes_unknown_{i}" for i in range(1, 3)),
    "keep_profitable_below_increase_threshold", "observe_no_condition",
)


def number(value):
    return Decimal(str(value or 0))


def quantile(values, share):
    values = sorted(values)
    if not values:
        return None
    position = Decimal(len(values) - 1) * share
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def peer_benchmarks(rows):
    pools = defaultdict(list)
    for row in rows:
        clicks = number(row["clicks"]) + number(row["previous_clicks"])
        orders = number(row["orders"]) + number(row["previous_orders"])
        sales = number(row["sales"]) + number(row["previous_sales"])
        same_orders = number(row["same_orders"]) + number(row["previous_same_orders"])
        if clicks < 10 or orders <= 0 or sales <= 0 or same_orders <= 0:
            continue
        unit = (sales / orders, same_orders / clicks, clicks)
        pools[(row["country"], row["currency_code"], row["match_group"])].append(unit)
    return {
        group: {
            "peer_n": len(samples),
            "aov": median(sample[0] for sample in samples),
            "cvr": median(sample[1] for sample in samples),
            "prior_clicks": median(sample[2] for sample in samples),
        }
        for group, samples in pools.items()
    }


def trial(row, peers):
    condition = row["condition"]
    if condition.startswith(("pause", "keep", "observe")):
        return "no_bid_change", None, None, None, None
    if row["eligible_for_bid"] != "True":
        return "object_not_eligible", None, None, None, None
    bid = number(row["current_bid"])
    if bid <= 0:
        return "missing_bid", None, None, None, None

    clicks = number(row["clicks"])
    cost = number(row["cost"])
    sales = number(row["sales"])
    prev_clicks = number(row["previous_clicks"])
    prev_cost = number(row["previous_cost"])
    prev_sales = number(row["previous_sales"])
    prior_acos = prev_cost / prev_sales if prev_sales else None
    pooled_acos = (cost + prev_cost) / (sales + prev_sales) if sales + prev_sales else None
    evidence = None

    if condition == "decrease_over_max_bid":
        maximum = number(row["max_bid"])
        if maximum <= 0:
            return "maxbid_unavailable", None, None, prior_acos, pooled_acos
        raw_rate = max(-MAX_STEP, maximum / bid - 1)
        evidence = "maxbid_ratio"
    elif condition.startswith("decrease_acos_"):
        if pooled_acos is None:
            return "acos_unavailable", None, None, prior_acos, pooled_acos
        if pooled_acos <= TARGET_ACOS:
            return "history_profitable_review", Decimal(0), None, prior_acos, pooled_acos
        raw_rate = max(-MAX_STEP, TARGET_ACOS / pooled_acos - 1)
        evidence = "pooled_60d_acos"
    elif condition.startswith("decrease_zero_sale_"):
        peer = peers.get((row["country"], row["currency_code"], row["match_group"]))
        if not peer or clicks <= 0 or cost <= 0:
            return "peer_or_cpc_unavailable", None, None, prior_acos, pooled_acos
        aov = number(row["aov_60d"]) if row["aov_60d"] else peer["aov"]
        prior_clicks = peer["prior_clicks"]
        estimated_cvr = (
            number(row["previous_same_orders"]) + peer["cvr"] * prior_clicks
        ) / (prev_clicks + clicks + prior_clicks)
        affordable_cpc = TARGET_ACOS * aov * estimated_cvr
        actual_cpc = cost / clicks
        raw_rate = max(-MAX_STEP, min(Decimal(0), affordable_cpc / actual_cpc - 1))
        evidence = f"peer_bayes_cvr_n{peer['peer_n']}"
        if raw_rate == 0:
            return "history_or_peer_supports_cpc_review", raw_rate, None, prior_acos, pooled_acos
    elif condition.startswith("increase_"):
        maximum = number(row["max_bid"])
        if maximum <= 0:
            return "maxbid_unavailable", None, None, prior_acos, pooled_acos
        if pooled_acos is None or pooled_acos >= TARGET_ACOS:
            return "history_not_profitable_review", Decimal(0), None, prior_acos, pooled_acos
        raw_rate = min(Decimal("0.20"), (TARGET_ACOS - pooled_acos) / TARGET_ACOS)
        evidence = "pooled_60d_acos_headroom"
    else:
        return "condition_not_supported", None, None, prior_acos, pooled_acos

    if raw_rate < 0:
        if bid <= FLOOR:
            return "minimum_bid_blocks_cut", raw_rate, None, prior_acos, pooled_acos
        proposed = max(FLOOR, (bid * (1 + raw_rate)).quantize(TICK, rounding=ROUND_CEILING))
        if proposed >= bid:
            return "tick_blocks_cut", raw_rate, None, prior_acos, pooled_acos
    else:
        maximum = number(row["max_bid"])
        proposed = min(
            maximum.quantize(TICK, rounding=ROUND_FLOOR),
            (bid * (1 + raw_rate)).quantize(TICK, rounding=ROUND_FLOOR),
        )
        if proposed <= bid:
            return "maxbid_or_tick_blocks_raise", raw_rate, None, prior_acos, pooled_acos
    return evidence, proposed / bid - 1, proposed, prior_acos, pooled_acos


def main():
    with (ROOT / "对象条件明细.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    peers = peer_benchmarks(rows)
    for row in rows:
        status, rate, proposed, prior_acos, pooled_acos = trial(row, peers)
        row.update(
            trial_status=status,
            proposed_change_rate=rate,
            proposed_bid=proposed,
            previous_acos=prior_acos,
            pooled_60d_acos=pooled_acos,
        )
    with (ROOT / "对象调价试算明细.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for condition in CONDITIONS:
        group = [row for row in rows if row["condition"] == condition]
        proposed = [row for row in group if row["proposed_bid"] is not None]
        rates = [number(row["proposed_change_rate"]) for row in proposed]
        status_counts = defaultdict(int)
        for row in group:
            status_counts[row["trial_status"]] += 1
        summary.append({
            "condition": condition,
            "objects": len(group),
            "eligible_objects": sum(row["eligible_for_bid"] == "True" for row in group),
            "proposed_objects": len(proposed),
            "rate_p25": quantile(rates, Decimal("0.25")),
            "rate_p50": quantile(rates, Decimal("0.50")),
            "rate_p75": quantile(rates, Decimal("0.75")),
            "blocked_or_review_statuses": ";".join(f"{name}:{count}" for name, count in sorted(status_counts.items()) if name not in {"maxbid_ratio", "pooled_60d_acos", "pooled_60d_acos_headroom"} and not name.startswith("peer_bayes")),
        })
    with (ROOT / "各条件调价档位.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    print(f"objects={len(rows)} conditions={len(summary)} proposed={sum(x['proposed_objects'] for x in summary)}")


if __name__ == "__main__":
    main()
