from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "register_web_server_task.ps1"


def test_web_server_task_starts_powershell_hidden():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "-WindowStyle Hidden" in script
