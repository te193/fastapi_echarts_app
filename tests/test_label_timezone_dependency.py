from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from packaging.requirements import Requirement


def test_windows_runtime_declares_timezone_database():
    path = Path(__file__).resolve().parents[1] / "requirements.txt"
    requirements = [Requirement(line) for line in path.read_text().splitlines()]
    assert any(
        requirement.name == "tzdata"
        and (
            requirement.marker is None
            or requirement.marker.evaluate({"sys_platform": "win32"})
        )
        for requirement in requirements
    )


def test_shanghai_timezone_is_available_to_label_generation():
    business_time = datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert business_time.utcoffset() == timedelta(hours=8)
