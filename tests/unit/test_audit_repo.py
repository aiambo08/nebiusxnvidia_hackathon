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
        "files:\n"
        "  synthetic.mp4:\n"
        "    types: [video/audio extension]\n"
        "    justification: synthetic test fixture created for this audit test\n",
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
            ".env.example": "NEBIUS_" + "API_KEY=https://api.example.invalid/v1/\n",
            "client.py": "api" + "_key = " + "api" + "_key\n",
            "constructor.py": "OpenAI(api" + "_key=api" + "_key)\n",
            "settings.py": "api" + "_key=settings.nebius_key\n",
            "multiline.py": "api" + "_key =\n" + "Q" * 24,
            "typed.py": "def create(api" + "_key: str | None):\n    pass\n",
            "placeholders.yaml": "NEBIUS_API" + "_KEY: your-key-here\n",
            "placeholders.json": '{"api' + '_key": "<redacted>"}\n',
            "placeholders.txt": "NEBIUS_API" + "_KEY=xxx\n",
            "known-prefix-placeholders.txt": (
                "api" + "_key=fake-key\n"
                "api" + "_key=dummy-key\n"
                "api" + "_key=example-key\n"
                "api" + "_key=placeholder-key\n"
                "api" + "_key=replace-key\n"
            ),
        },
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 0, result.stdout + result.stderr
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    row = next(line for line in report.splitlines() if "`.env.example`" in line)
    assert "environment file" not in row
    assert "| credential pattern:" not in report


def test_placeholder_prefixes_require_a_whole_known_value(tmp_path):
    repo, allowlist = _new_repo(
        tmp_path,
        {"client.py": "api" + "_key=fake-key-with-extra\n"},
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    row = next(line for line in report.splitlines() if "`client.py`" in line)
    assert "api_key assignment" in row


def test_your_prefix_alone_does_not_make_a_value_a_placeholder(tmp_path):
    repo, allowlist = _new_repo(
        tmp_path,
        {"client.py": "api" + "_key = your" + "-looks-like-a-real-value\n"},
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "api_key assignment" in report


def test_api_key_assignment_values_are_flagged_per_current_file_row(tmp_path):
    v1_value = b"v1." + b"CmQKHHN0YXRpY2tleS1lMDBhYmNkZWZnaGlqa2xtbm9w"
    hex_value = b"a3f9c2e1b7d84f0a" + b"9e6c5b2d1f0e8a7c"
    live_value = b"sk" + b"_live_" + b"abcdefghijklmnop1234"
    fixtures = [
        (
            "nebius-v1-env.txt",
            b"NEBIUS_" + b"API_KEY=" + v1_value,
            "nebius_api_key assignment",
        ),
        (
            "api-key-quoted-hex.txt",
            b"api" + b'_key = "' + hex_value + b'"',
            "api_key assignment",
        ),
        (
            "api-key-sk-live.txt",
            b'api_key="' + live_value + b'"',
            "api_key assignment",
        ),
        (
            "nebius-lowercase.txt",
            b"NEBIUS_" + b"API_KEY=" + b"abcdefghijklmnopqrstuvwxyz0123456789",
            "nebius_api_key assignment",
        ),
        (
            "nebius-reference.txt",
            b"NEBIUS_" + b"API_KEY=settings.nebius_key",
            "nebius_api_key assignment",
        ),
        ("v1-unquoted.txt", b"api_key=" + v1_value, "api_key assignment"),
        ("v1-quoted-colon.txt", b'api_key: "' + v1_value + b'"', "api_key assignment"),
        ("hex-unquoted.txt", b"api_key=" + hex_value, "api_key assignment"),
        (
            "hex-quoted-json.txt",
            b'{"api_key": "' + hex_value + b'"}',
            "api_key assignment",
        ),
        (
            "quoted-forward-reference.txt",
            b"api" + b'_key="' + b"settings.nebius_key" + b'"',
            "api_key assignment",
        ),
        (
            "os-environ.txt",
            b'os.environ["NEBIUS_API_KEY"] = "' + b"Q" * 24 + b'"',
            "nebius_api_key assignment",
        ),
        (
            "openai-call.txt",
            b'OpenAI(api_key="' + hex_value + b'")',
            "api_key assignment",
        ),
    ]
    repo, allowlist = _new_repo(
        tmp_path,
        {relative: content for relative, content, _reason in fixtures},
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    tracked_section = report.split("## Tracked-file inventory", 1)[1].split(
        "## Historical findings", 1
    )[0]
    for relative, _content, reason in fixtures:
        row = next(
            line for line in tracked_section.splitlines() if f"`{relative}`" in line
        )
        assert reason in row


def test_placeholder_prefixes_only_skip_exact_known_values(tmp_path):
    prefixes = ("fake", "dummy", "example", "placeholder", "replace")
    files = {
        f"{prefix}.py": "api" + "_key=" + prefix + "-looks-like-a-real-value\n"
        for prefix in prefixes
    }
    repo, allowlist = _new_repo(tmp_path, files)

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    tracked_section = report.split("## Tracked-file inventory", 1)[1].split(
        "## Historical findings", 1
    )[0]
    for prefix in prefixes:
        row = next(line for line in tracked_section.splitlines() if f"`{prefix}.py`" in line)
        assert "api_key assignment" in row


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
    nebius_value = b"J" * 24
    api_value = b"K" * 24
    return [
        ("private-key material", private_key),
        ("AWS access-key ID", b"AKIA" + b"A" * 16),
        ("GitHub token", b"gh" + b"p_" + b"B" * 24),
        ("sk- API key", b"sk-" + b"C" * 24),
        ("sk-proj- API key", b"sk-proj-" + b"H" * 24),
        ("NVIDIA API key", b"nvapi-" + b"D" * 24),
        ("Hugging Face token", b"hf_" + b"E" * 24),
        ("nebius_api_key assignment", b"NEBIUS_" + b"API_KEY=" + b"F" * 24),
        ("nebius_api_key assignment", b"NEBIUS_" + b"API_KEY: " + nebius_value),
        ("key assignment", b"K" + b"EY: " + api_value),
        ("api_key assignment", b'{"api' + b'_key": "' + api_value + b'"}'),
        (
            "nebius_api_key assignment",
            b'os.environ["NEBIUS_API_KEY"] = "' + nebius_value + b'"',
        ),
    ]


def test_every_credential_pattern_is_flagged_in_current_files(tmp_path):
    fixtures = _credential_fixtures()
    files = {
        f"credential-{index}.txt": value for index, (_, value) in enumerate(fixtures)
    }
    repo, allowlist = _new_repo(tmp_path, files)

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    tracked_section = report.split("## Tracked-file inventory", 1)[1].split(
        "## Historical findings", 1
    )[0]
    for index, (expected_label, _value) in enumerate(fixtures):
        row = next(
            line
            for line in tracked_section.splitlines()
            if f"`credential-{index}.txt`" in line
        )
        expected_reason = (
            "sk- API key" if expected_label == "sk-proj- API key" else expected_label
        )
        assert expected_reason in row
    for _label, value in fixtures:
        assert value.decode("ascii", errors="ignore") not in report


def test_every_credential_pattern_is_flagged_in_history_only(tmp_path):
    fixtures = _credential_fixtures()
    files = {
        f"credential-{index}.txt": value for index, (_, value) in enumerate(fixtures)
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
    history_section = report.split("## Historical findings", 1)[1].split(
        "## History scan warnings", 1
    )[0]
    for index, (expected_label, _value) in enumerate(fixtures):
        row = next(
            line
            for line in history_section.splitlines()
            if f"`credential-{index}.txt`" in line
        )
        expected_reason = (
            "sk- API key" if expected_label == "sk-proj- API key" else expected_label
        )
        assert f"credential pattern: {expected_reason}" in row


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


def test_600kb_uppercase_image_is_flagged_in_current_and_history(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"capture.JPG": b"x" * (600 * 1024)})
    report_path = tmp_path / "audit.md"

    current_result = _audit(repo, allowlist, report_path)
    assert current_result.returncode == 1
    current_report = report_path.read_text(encoding="utf-8")
    tracked_section = current_report.split("## Tracked-file inventory", 1)[1].split(
        "## Historical findings", 1
    )[0]
    current_row = next(line for line in tracked_section.splitlines() if "`capture.JPG`" in line)
    assert "image larger than 500 KB" in current_row
    assert "file larger than 1 MB" not in current_row

    (repo / "capture.JPG").unlink()
    _commit(repo, "remove synthetic uppercase image")
    history_result = _audit(repo, allowlist, report_path)
    assert history_result.returncode == 1
    history_report = report_path.read_text(encoding="utf-8")
    history_section = history_report.split("## Historical findings", 1)[1]
    history_row = next(line for line in history_section.splitlines() if "`capture.JPG`" in line)
    assert "image larger than 500 KB" in history_row


def test_allowlisted_dataset_does_not_waive_credential_in_current_or_history(tmp_path):
    fake_key = b"sk-proj-" + b"Z" * 24
    repo, allowlist = _new_repo(
        tmp_path,
        {"capture.jsonl": b'{"response":"' + fake_key + b'"}\n'},
    )
    allowlist.write_text(
        "files:\n"
        "  capture.jsonl:\n"
        "    types: [dataset extension]\n"
        "    justification: synthetic test JSONL\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "audit.md"

    current_result = _audit(repo, allowlist, report_path)
    assert current_result.returncode == 1
    current_report = report_path.read_text(encoding="utf-8")
    assert "`capture.jsonl`" in current_report
    assert "sk- API key" in current_report

    (repo / "capture.jsonl").unlink()
    _commit(repo, "remove synthetic credential fixture")
    history_result = _audit(repo, allowlist, report_path)
    assert history_result.returncode == 1
    history_report = report_path.read_text(encoding="utf-8")
    assert "`capture.jsonl`" in history_report
    assert "credential pattern: sk- API key" in history_report


def test_credential_types_are_never_waivable_in_current_and_history(tmp_path):
    cases = [
        (
            "sk",
            "current.txt",
            b"sk-proj-" + b"R" * 24,
            "sk- API key",
        ),
        (
            "assignment",
            "current.txt",
            b"NEBIUS_" + b"API_KEY=" + b"S" * 24,
            "nebius_api_key assignment",
        ),
    ]
    for name, relative, content, reason in cases:
        case_root = tmp_path / name
        repo, allowlist = _new_repo(case_root, {"readme.txt": "safe\n"})
        (repo / relative).write_bytes(content)
        _run_git(repo, "add", relative)
        allowlist.write_text(
            "files:\n"
            f"  {relative}:\n"
            f'    types: ["{reason}"]\n'
            "    justification: explicit credential type for negative test\n",
            encoding="utf-8",
        )

        current_result = _audit(repo, allowlist, case_root / "current.md")
        assert current_result.returncode == 1
        current_report = (case_root / "current.md").read_text(encoding="utf-8")
        current_row = next(
            line for line in current_report.splitlines() if f"`{relative}`" in line
        )
        assert reason in current_row

        _commit(repo, "add synthetic credential")
        (repo / relative).unlink()
        _commit(repo, "remove synthetic credential")
        allowlist.write_text(
            "files:\n"
            f"  {relative}:\n"
            f'    types: ["credential pattern: {reason}"]\n'
            "    justification: explicit historical credential type for negative test\n",
            encoding="utf-8",
        )
        history_result = _audit(repo, allowlist, case_root / "history.md")
        assert history_result.returncode == 1
        history_report = (case_root / "history.md").read_text(encoding="utf-8")
        history_row = next(
            line for line in history_report.splitlines() if f"`{relative}`" in line
        )
        assert f"credential pattern: {reason}" in history_row


def test_allowlist_entry_does_not_waive_an_unlisted_finding_type(tmp_path):
    repo, allowlist = _new_repo(
        tmp_path, {"capture.JPG": b"x" * (600 * 1024)}
    )
    allowlist.write_text(
        "files:\n"
        "  capture.JPG:\n"
        "    types: [dataset extension]\n"
        "    justification: unrelated dataset type\n",
        encoding="utf-8",
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "image larger than 500 KB" in report
    assert "Unallowlisted findings require review" in report


def test_current_file_allowlist_type_does_not_waive_another_type(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"readme.txt": "safe\n"})
    path = repo / "current-only.mp4"
    path.write_bytes(b"x" * 1_000_001)
    _run_git(repo, "add", "current-only.mp4")
    allowlist.write_text(
        "files:\n"
        "  current-only.mp4:\n"
        "    types: [video/audio extension]\n"
        "    justification: synthetic current-only media fixture\n",
        encoding="utf-8",
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    tracked_section = report.split("## Tracked-file inventory", 1)[1].split(
        "## Historical findings", 1
    )[0]
    current_row = next(
        line for line in tracked_section.splitlines() if "`current-only.mp4`" in line
    )
    assert "video/audio extension" in current_row
    assert "file larger than 1 MB" in current_row
    history_section = report.split("## Historical findings", 1)[1].split(
        "## History scan warnings", 1
    )[0]
    assert "`current-only.mp4`" not in history_section


def test_empty_allowlist_types_are_rejected(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"readme.txt": "safe\n"})
    allowlist.write_text(
        "files:\n"
        "  readme.txt:\n"
        "    types: []\n"
        "    justification: empty type list must be rejected\n",
        encoding="utf-8",
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 1
    assert "allowlist" in result.stdout.lower() + result.stderr.lower()


def test_history_blob_over_5mb_requires_oversized_blob_allowlist(tmp_path):
    repo, allowlist = _new_repo(tmp_path, {"readme.txt": "safe\n"})
    oversized = repo / "old.txt"
    oversized.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    _commit(repo, "add synthetic oversized blob")
    oversized.unlink()
    _commit(repo, "remove synthetic oversized blob")
    report_path = tmp_path / "audit.md"

    rejected = _audit(repo, allowlist, report_path)
    assert rejected.returncode == 1
    assert "oversized_blob" in report_path.read_text(encoding="utf-8")

    allowlist.write_text(
        "files:\n"
        "  old.txt:\n"
        "    types: [oversized_blob]\n"
        "    justification: synthetic oversized fixture created for this test\n",
        encoding="utf-8",
    )
    allowed = _audit(repo, allowlist, report_path)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    report = report_path.read_text(encoding="utf-8")
    assert "History blobs skipped above 5 MB: 1" in report
    assert "only by CI gitleaks" in report


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
    allowlist.write_text(
        "files:\n"
        "  old.mp4:\n"
        "    types: [video/audio extension]\n"
        "    justification: removed synthetic fixture\n",
        encoding="utf-8",
    )

    result = _audit(repo, allowlist, tmp_path / "audit.md")

    assert result.returncode == 0, result.stdout + result.stderr
    report = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "Stale allowlist entries" in report
    assert "`old.mp4`" in report


def test_allowlist_justifications_cite_git_verified_producers():
    allowlist = (ROOT / "configs" / "public_audit_allowlist.yaml").read_text(
        encoding="utf-8"
    )
    assert "scripts/spike_nemotron.py" in allowlist
    assert "3f5e4e3" in allowlist
    assert (
        "Live Nemotron responses to synthetic probe packets; token/cost metadata; no personal data."
        in allowlist
    )
    assert "scripts/build_golden.py" in allowlist
    assert "2275652" in allowlist
    assert "a245332" in allowlist
    assert "ADR-009" in allowlist
    assert "no repository script generates v2 yet" in allowlist
    assert "scripts/build_golden.py writes v1 only" in allowlist
