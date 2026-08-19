import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "js" / "price_review_role_detail_chart.js"


def build_option(payload: dict, view: str = "sales_margin") -> dict:
    node = shutil.which("node")
    assert node, "Node.js is required for the role-detail chart contract test"
    script = """
const chart = require(process.argv[1]);
const payload = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(chart.buildOption(payload, process.argv[3])));
"""
    result = subprocess.run(
        [node, "-e", script, str(SCRIPT), json.dumps(payload, ensure_ascii=False), view],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


TREND_PAYLOAD = {
    "trend": [
        {"relative_day": "D-1", "period": "before", "sales_qty": 2, "margin_rate": 0.3, "small_rank": 45},
        {"relative_day": "D", "period": "adjustment", "sales_qty": 1, "margin_rate": 0.2, "small_rank": 88},
        {"relative_day": "D+1", "period": "after", "sales_qty": 0, "margin_rate": None, "small_rank": 900},
    ]
}


def test_role_detail_chart_defaults_to_sales_and_margin_lines():
    option = build_option(TREND_PAYLOAD)

    assert [axis["name"] for axis in option["yAxis"]] == ["销量", "毛利率"]
    assert [series["name"] for series in option["series"]] == ["每日销量", "毛利率"]
    assert [series["type"] for series in option["series"]] == ["line", "line"]
    assert [series["showSymbol"] for series in option["series"]] == [False, True]
    assert option["series"][0]["data"] == [2, 1, 0]
    assert option["series"][1]["data"] == [0.3, 0.2, None]
    assert option["series"][0]["markLine"]["data"] == [{"xAxis": "D", "name": "调价日"}]


def test_role_detail_chart_rank_view_is_independent_and_reversed():
    option = build_option(TREND_PAYLOAD, "rank")

    assert [axis["name"] for axis in option["yAxis"]] == ["小类排名"]
    assert option["yAxis"][0]["inverse"] is True
    assert [series["name"] for series in option["series"]] == ["小类排名"]
    assert option["series"][0]["type"] == "line"
    assert option["series"][0]["data"] == [45, 88, 900]
    assert option["series"][0]["markLine"]["data"] == [{"xAxis": "D", "name": "调价日"}]
