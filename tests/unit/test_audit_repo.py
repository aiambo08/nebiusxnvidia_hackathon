import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_repo.py"


def _run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _audit(repo, allowlist, report):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--allowlist",
            str(allowlist),
            "--report",
            str(report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_audit_flags_media_and_private_keys_but_accepts_justified_media(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    (repo / "synthetic.mp4").write_bytes(b"synthetic fixture")
    (repo / "readme.txt").write_text("safe\n", encoding="utf-8")
    allowlist = repo / "allowlist.yaml"
    allowlist.write_text(
        "files:\n  synthetic.mp4: synthetic test fixture created for this audit test\n",
        encoding="utf-8",
    )
    report = tmp_path / "audit.md"
    _run_git(repo, "add", "synthetic.mp4", "readme.txt", "allowlist.yaml")
    _run_git(
        repo,
        "-c",
        "user.name=Audit Test",
        "-c",
        "user.email=audit@example.invalid",
        "commit",
        "-m",
        "test fixture",
    )

    allowed_result = _audit(repo, allowlist, report)
    assert allowed_result.returncode == 0, allowed_result.stdout + allowed_result.stderr
    assert "`synthetic.mp4`" in report.read_text(encoding="utf-8")
    assert "video/audio extension" in report.read_text(encoding="utf-8")
    assert "synthetic test fixture created for this audit test" in report.read_text(
        encoding="utf-8"
    )

    fake_key = (
        b"-----BEGIN "
        + b"PRIVATE KEY-----\n"
        + b"not a real key\n"
        + b"-----END "
        + b"PRIVATE KEY-----\n"
    )
    (repo / "fake-key.txt").write_bytes(fake_key)
    _run_git(repo, "add", "fake-key.txt")

    key_result = _audit(repo, allowlist, report)
    assert key_result.returncode == 1
    text = report.read_text(encoding="utf-8")
    assert "`fake-key.txt`" in text
    assert "private-key material" in text
    assert "PRIVATE KEY-----" not in key_result.stdout + key_result.stderr
