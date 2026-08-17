import json
import shutil
import subprocess
from pathlib import Path

from app.services.station_sales_role import FINANCE_BANDS


ROOT = Path(__file__).resolve().parents[1]
FLOW_SCRIPT = ROOT / "app" / "static" / "js" / "price_review_finance_flow.js"


def build_flow_model(items: list[dict]) -> dict:
    node = shutil.which("node")
    assert node, "Node.js is required for the finance-flow frontend contract test"
    payload = {
        "bands": [{"key": key, "label": label} for key, label in FINANCE_BANDS],
        "items": items,
    }
    script = """
const fs = require('fs');
const flow = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(flow.buildModel(payload.bands, payload.items)));
"""
    result = subprocess.run(
        [node, "-e", script, str(FLOW_SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_finance_flow_keeps_every_pricing_band_and_classifies_each_direction():
    model = build_flow_model(
        [
            {"before": "below_0", "after": "10_15", "count": 27},
            {"before": "5_10", "after": "5_10", "count": 21},
            {"before": "25_30", "after": "10_15", "count": 13},
            {"before": "5_10", "after": "10_15", "count": 42},
        ]
    )

    expected_keys = [key for key, _ in FINANCE_BANDS]
    assert [node["key"] for node in model["leftNodes"]] == expected_keys
    assert [node["key"] for node in model["rightNodes"]] == expected_keys
    assert len(model["leftNodes"]) == 9
    assert len(model["rightNodes"]) == 9

    links = {(link["before"], link["after"]): link for link in model["links"]}
    assert links[("below_0", "10_15")]["direction"] == "up"
    assert links[("5_10", "5_10")]["direction"] == "stable"
    assert links[("25_30", "10_15")]["direction"] == "down"
    assert links[("5_10", "10_15")]["count"] == 42
    assert model["maxCount"] == 42


def test_finance_flow_ignores_unclassified_or_empty_paths_without_dropping_nodes():
    model = build_flow_model(
        [
            {"before": "unavailable", "after": "10_15", "count": 9},
            {"before": "0_5", "after": "5_10", "count": 0},
        ]
    )

    assert model["links"] == []
    assert len(model["leftNodes"]) == len(FINANCE_BANDS)
    assert len(model["rightNodes"]) == len(FINANCE_BANDS)
    assert model["maxCount"] == 0
