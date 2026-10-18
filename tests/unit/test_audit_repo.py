import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_repo.py"
EXPECTED_EXTENSION_CLASSES = {
    "model-weight extension": (
        ".pkl",
        ".pickle",
        ".pt",
        ".pth",
        ".ckpt",
        ".onnx",
        ".safetensors",
        ".bin",
        ".h5",
        ".tflite",
    ),
    "dataset extension": (
        ".csv",
        ".tsv",
        ".jsonl",
        ".ndjson",
        ".arrow",
        ".tfrecord",
        ".npz",
        ".npy",
        ".parquet",
        ".hdf5",
        ".hdf",
        ".zip",
        ".tgz",
    ),
    "archive extension": (".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".tar.zst"),
    "raw video/image extension": (".y4m", ".yuv", ".h264", ".h265", ".dng", ".raw"),
}


def _run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo, message):
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "-c",
        "user.name=Audit Test",
        "-c",
        "user.email=audit@example.invalid",
        "commit",
        "-m",
        message,
    )


def _new_repo(tmp_path, files=None):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _run_git(repo, "init", "-q")
    for relative, content in (files or {}).items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
    allowlist = repo / "allowlist.yaml"
    allowlist.write_text("files: {}\n", encoding="utf-8")
    _commit(repo, "audit fixture")
    return repo, allowlist


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
    repo, allowlist = _new_repo(
        tmp_path,
        {"synthetic.mp4": b"synthetic fixture", "readme.txt": "safe\n"},
    )
    allowlist.write_text(
        "files:\n  synthetic.mp4: synthetic test fixture created for this audit test\n",
        encoding="utf-8",
    )
    report = tmp_path / "audit.md"

    allowed_result = _audit(repo, allowlist, report)
    assert allowed_result.returncode == 0, allowed_result.stdout + allowed_result.stderr
    text = report.read_text(encoding="utf-8")
    assert "`synthetic.mp4`" in text
    assert "video/audio extension" in text
    assert "synthetic test fixture created for this audit test" in text
    assert "`gitleaks (full history)`" in text

    fake_key = (
        b"-----BEGIN "
        + b"PRIVATE "
        + b"KEY-----\n"
        + b"not a real key\n"
        + b"-----END "
        + b"PRIVATE "
        + b"KEY-----\n"
    )
    (repo / "fake-key.txt").write_bytes(fake_key)
    _run_git(repo, "add", "fake-key.txt")

    key_result = _audit(repo, allowlist, report)
    assert key_result.returncode == 1
    text = report.read_text(encoding="utf-8")
    assert "`fake-key.txt`" in text
    assert "private-key material" in text
    assert "PRIVATE KEY-----" not in key_result.stdout + key_result.stderr


def test_deleted_media_in_history_fails_the_audit(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"readme.txt": "safe\n"})
    base_commit = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    _run_git(repo, "switch", "--create", "historical-media")
    (repo / "old.mp4").write_bytes(b"synthetic video fixture")
    _commit(repo, "add fixture")
    (repo / "old.mp4").unlink()
    _commit(repo, "remove fixture")
    _run_git(repo, "switch", "--detach", base_commit)

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "`old.mp4`" in report
    assert "video/audio extension" in report


def test_extension_classes_are_detected_case_insensitively(tmp_path):
    files = {}
    expected_paths = []
    for reason, extensions in EXPECTED_EXTENSION_CLASSES.items():
        for index, extension in enumerate(extensions):
            filename = f"fixtures/{reason.split()[0]}-{index}{extension}"
            files[filename] = b"synthetic fixture"
            expected_paths.append((filename, reason))
    repo, allowlist = _new_repo(tmp_path, files)

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    for filename, reason in expected_paths:
        assert f"`{filename}`" in report
        assert reason in report

    uppercase_repo, uppercase_allowlist = _new_repo(
        tmp_path / "uppercase", {"capture.MP4": b"synthetic fixture"}
    )
    uppercase_result = _audit(
        uppercase_repo, uppercase_allowlist, tmp_path / "uppercase-audit.md"
    )
    assert uppercase_result.returncode == 1
    assert "video/audio extension" in (tmp_path / "uppercase-audit.md").read_text(
        encoding="utf-8"
    )


def test_env_file_is_flagged(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"prod.env": "MODE=test\n"})

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "`prod.env`" in report
    assert "environment file" in report


def test_env_example_and_forwarded_api_key_values_are_not_credentials(tmp_path):
    repo, allowlist = _new_repo(
        tmp_path,
        {
            ".env.example": "NEBIUS_API_KEY=https://api.example.invalid/v1/\n",
            "client.py": "api" + "_key = " + "api" + "_key\n",
        },
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 0, result.stdout + result.stderr
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    row = next(line for line in report.splitlines() if "`.env.example`" in line)
    assert "environment file" not in row
    assert "| credential pattern:" not in report


def _credential_fixtures():
    private_key = (
        b"-----BEGIN "
        + b"PRIVATE "
        + b"KEY-----\n"
        + b"fake material\n"
        + b"-----END "
        + b"PRIVATE "
        + b"KEY-----\n"
    )
    return {
        "private-key material": private_key,
        "AWS access-key ID": b"AKIA" + b"A" * 16,
        "GitHub token": b"gh" + b"p_" + b"B" * 24,
        "sk- API key": b"sk-" + b"C" * 24,
        "sk-proj- API key": b"sk-proj-" + b"H" * 24,
        "NVIDIA API key": b"nvapi-" + b"D" * 24,
        "Hugging Face token": b"hf_" + b"E" * 24,
        "nebius_api_key assignment": b"NEBIUS_" + b"API_KEY=" + b"F" * 24,
        "api_key assignment": b"api" + b"_key=" + b"G" * 24,
    }


def test_every_credential_pattern_is_flagged_in_current_files(tmp_path):
    fixtures = _credential_fixtures()
    files = {
        f"credential-{index}.txt": value for index, value in enumerate(fixtures.values())
    }
    repo, allowlist = _new_repo(tmp_path, files)

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    for index, expected_label in enumerate(fixtures):
        if expected_label == "sk-proj- API key":
            row = next(
                line
                for line in report.splitlines()
                if f"`credential-{index}.txt`" in line
            )
            assert "sk- API key" in row
        else:
            assert expected_label in report
    for value in fixtures.values():
        assert value.decode("ascii", errors="ignore") not in report


def test_every_credential_pattern_is_flagged_in_history_only(tmp_path):
    fixtures = _credential_fixtures()
    files = {
        f"credential-{index}.txt": value for index, value in enumerate(fixtures.values())
    }
    repo, allowlist = _new_repo(tmp_path, files)
    for relative in files:
        (repo / relative).unlink()
    _commit(repo, "remove synthetic credential fixtures")

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "Tracked-file inventory" in report
    assert "Historical findings" in report
    for index, expected_label in enumerate(fixtures):
        if expected_label == "sk-proj- API key":
            row = next(
                line
                for line in report.splitlines()
                if f"`credential-{index}.txt`" in line
            )
            assert "sk- API key" in row
        else:
            assert expected_label in report


def test_large_images_and_files_are_flagged(tmp_path):
    repo, allowlist = _new_repo(
        tmp_path,
        {
            "large.jpg": b"x" * (600 * 1024),
            "oversized.dat": b"x" * 1_000_001,
        },
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "`large.jpg`" in report and "image larger than 500 KB" in report
    assert "`oversized.dat`" in report and "file larger than 1 MB" in report


def test_data_directory_is_flagged_case_insensitively(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"Data/fixture.txt": "synthetic\n"})

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "`Data/fixture.txt`" in report
    assert "dataset/recording directory" in report


def test_shallow_clone_is_rejected(tmp_path):
    source, _ = _new_repo(tmp_path / "source", {"readme.txt": "fixture\n"})
    shallow = tmp_path / "shallow"
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", source.as_uri(), str(shallow)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert clone.returncode == 0, clone.stdout + clone.stderr
    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text("files: {}\n", encoding="utf-8")

    result = _audit(shallow, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    assert "shallow clone" in result.stdout + result.stderr


def test_stale_allowlist_entries_are_reported(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"readme.txt": "safe\n"})
    allowlist.write_text("files:\n  old.mp4: removed synthetic fixture\n", encoding="utf-8")

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 0, result.stdout + result.stderr
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "Stale allowlist entries" in report
    assert "`old.mp4`" in report
