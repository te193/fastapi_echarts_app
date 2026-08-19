import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREND_SCRIPT = ROOT / "app" / "static" / "js" / "price_review_role_trend.js"


def build_trend_option(payload: dict) -> dict:
    node = shutil.which("node")
    assert node, "Node.js is required for the role-trend frontend contract test"
    script = """
const fs = require('fs');
const trend = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(trend.buildOption(payload)));
"""
    result = subprocess.run(
        [node, "-e", script, str(TREND_SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_role_trend_keeps_sparse_margin_observations_visible_across_empty_days():
    points = [
        {
            "date": f"2026-07-{day:02d}",
            "relative_day": f"D-{31 - day}",
            "period": "before",
            "sales_qty": 1 if day in (1, 6, 11, 16, 21, 26) else 0,
            "margin_rate": 0.2 + day / 1000 if day in (1, 6, 11, 16, 21, 26) else None,
        }
        for day in range(1, 31)
    ]
    points.extend(
        [
            {"date": "2026-08-01", "relative_day": "D", "period": "adjustment", "sales_qty": 0, "margin_rate": None},
            {"date": "2026-08-02", "relative_day": "D+1", "period": "after", "sales_qty": 1, "margin_rate": 0.26},
            {"date": "2026-08-03", "relative_day": "D+2", "period": "after", "sales_qty": 0, "margin_rate": None},
            {"date": "2026-08-04", "relative_day": "D+3", "period": "after", "sales_qty": 2, "margin_rate": 0.27},
        ]
    )

    option = build_trend_option({"points": points})
    margin_series = option["series"][1]

    assert margin_series["data"][1] is None
    assert margin_series["connectNulls"] is True
    assert margin_series["showSymbol"] is True


def test_role_trend_option_renders_daily_sales_and_margin_on_separate_axes():
    option = build_trend_option(
        {
            "points": [
                {"date": "2026-08-09", "relative_day": "D-1", "period": "before", "sales_qty": 20, "margin_rate": 0.1},
                {"date": "2026-08-10", "relative_day": "D", "period": "adjustment", "sales_qty": 5, "margin_rate": 0.12},
                {"date": "2026-08-11", "relative_day": "D+1", "period": "after", "sales_qty": 30, "margin_rate": 0.15},
                {"date": "2026-08-12", "relative_day": "D+2", "period": "after", "sales_qty": None, "margin_rate": None},
            ]
        }
    )

    assert [axis["name"] for axis in option["yAxis"]] == ["销量", "毛利率"]
    assert option["xAxis"]["data"] == ["D-1", "D", "D+1", "D+2"]
    assert option["series"][0]["name"] == "每日销量"
    assert option["series"][0]["data"] == [20, 5, 30, None]
    assert option["series"][1]["name"] == "毛利率"
    assert option["series"][1]["data"] == [0.1, 0.12, 0.15, None]
    assert option["series"][0]["markLine"]["data"] == [{"xAxis": "D", "name": "调价日"}]


def test_role_trend_window_backgrounds_meet_without_a_gap_after_adjustment_day():
    option = build_trend_option(
        {
            "points": [
                {"date": "2026-08-09", "relative_day": "D-1", "period": "before", "sales_qty": 20, "margin_rate": 0.1},
                {"date": "2026-08-10", "relative_day": "D", "period": "before", "sales_qty": 5, "margin_rate": 0.12},
                {"date": "2026-08-11", "relative_day": "D+1", "period": "after", "sales_qty": 30, "margin_rate": 0.15},
                {"date": "2026-08-12", "relative_day": "D+2", "period": "after", "sales_qty": 40, "margin_rate": 0.16},
            ]
        }
    )

    mark_areas = option["series"][0]["markArea"]["data"]
    assert mark_areas[0][1]["xAxis"] == "D+1"
    assert mark_areas[1][0]["xAxis"] == "D+1"
    assert "调价日计入调前汇总" in option["aria"]["description"]
