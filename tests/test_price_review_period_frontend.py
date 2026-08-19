import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operating_effect_period_config_defaults_to_three_days():
    module_path = ROOT / "app" / "static" / "js" / "price_review_period.js"
    script = """
const period = require(process.argv[1]);
process.stdout.write(JSON.stringify({
  defaultDays: period.defaultDays,
  supportedDays: period.supportedDays,
  accepts3: period.isSupported("3"),
  accepts7: period.isSupported("7"),
  rejectsOther: period.isSupported("5")
}));
"""

    result = subprocess.run(
        ["node", "-e", script, str(module_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "defaultDays": "3",
        "supportedDays": ["3", "7", "14", "28"],
        "accepts3": True,
        "accepts7": True,
        "rejectsOther": False,
    }
