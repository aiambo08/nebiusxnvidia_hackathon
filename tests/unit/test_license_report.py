import subprocess
import sys
from pathlib import Path

from scripts import license_report

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "license_report.py"
LICENSE_DOCUMENT = ROOT / "docs/third-party-licenses.md"


def _check_document(tmp_path, document):
    path = tmp_path / "licenses.md"
    path.write_text(document, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--doc", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_installed_dependency_licences_are_documented():
    document = LICENSE_DOCUMENT.read_text(encoding="utf-8")
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


def test_license_inventory_covers_linux_win32_extras_and_transitives():
    records, errors = license_report.resolve_dependencies()

    assert errors == []
    assert {"numpy", "httpx", "fastapi", "pytest", "colorama"} <= set(records)
    assert records["colorama"]["version"] == "0.4.6"
    assert "dev" in records["colorama"]["groups"]
    assert license_report._metadata_licence(records["colorama"]) == "BSD License"
    generated = license_report.render_generated_section(records, errors)
    assert "https://pypi.org/pypi/colorama/0.4.6/json" in generated
    assert "`certifi` — `MPL-2.0` (copyleft)" in generated


def test_license_check_rejects_wrong_missing_unknown_and_extra_rows(tmp_path):
    document = LICENSE_DOCUMENT.read_text(encoding="utf-8")
    certifi_row = next(
        line for line in document.splitlines() if line.startswith("| `certifi` |")
    )
    certifi_cells = [cell.strip() for cell in certifi_row.strip("|").split("|")]

    licence_cell = certifi_cells[2]
    wrong_licence = document.replace(
        certifi_row,
        certifi_row.replace(f"| {licence_cell} |", "| MIT |", 1),
    )
    missing_row = document.replace(certifi_row + "\n", "")
    unknown_licence = document.replace(
        certifi_row,
        certifi_row.replace(f"| {licence_cell} |", "| UNKNOWN |", 1),
    )
    extra_row = document.replace(
        certifi_row + "\n",
        certifi_row + "\n| `not-a-real-distribution` | 1.0 | MIT | — | dev |\n",
    )

    for altered in (wrong_licence, missing_row, unknown_licence, extra_row):
        result = _check_document(tmp_path, altered)
        assert result.returncode == 1, result.stdout + result.stderr


def test_license_check_ignores_version_changes(tmp_path):
    document = LICENSE_DOCUMENT.read_text(encoding="utf-8")
    certifi_row = next(
        line for line in document.splitlines() if line.startswith("| `certifi` |")
    )
    certifi_cells = [cell.strip() for cell in certifi_row.strip("|").split("|")]
    altered = document.replace(
        certifi_row,
        certifi_row.replace(f"| {certifi_cells[1]} |", "| 0.0.0 |", 1),
    )

    result = _check_document(tmp_path, altered)

    assert result.returncode == 0, result.stdout + result.stderr


def test_copyleft_licences_are_reported_as_review_flags():
    records, errors = license_report.resolve_dependencies()

    assert errors == []
    assert ("certifi", "MPL-2.0", "copyleft") in license_report._review_flags(records)
