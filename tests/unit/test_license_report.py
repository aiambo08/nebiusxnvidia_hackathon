import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "license_report.py"


def test_installed_dependency_licences_are_documented():
    document = (ROOT / "docs/third-party-licenses.md").read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    generated_start = document.index("<!-- BEGIN GENERATED DEPENDENCY LICENSES -->")
    hand_written_content = document[:generated_start]
    assert "No third-party source code is vendored." in hand_written_content
    assert "WoodScape / Dirty WoodScape datasets" in hand_written_content
