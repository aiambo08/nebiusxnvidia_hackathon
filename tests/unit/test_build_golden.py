import json
import sys

import pytest

from scripts import build_golden as builder

CASES = [{"id": "dev-base-001", "split": "dev", "variant": "base"}]


def _run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["build_golden.py", *args])
    return builder.main()


def test_build_golden_requires_output_path(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch)

    assert exc.value.code == 2


def test_build_golden_writes_to_requested_path(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "build_golden", lambda: CASES)
    out = tmp_path / "custom.jsonl"

    assert _run(monkeypatch, "--out", str(out)) == 0

    assert [json.loads(line) for line in out.read_text().splitlines()] == CASES


def test_build_golden_refuses_existing_file_without_force(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "build_golden", lambda: CASES)
    out = tmp_path / "frozen.jsonl"
    original = b"frozen bytes\n"
    out.write_bytes(original)

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--out", str(out))

    assert exc.value.code == 2
    assert out.read_bytes() == original


def test_build_golden_force_overwrites_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "build_golden", lambda: CASES)
    out = tmp_path / "replace.jsonl"
    out.write_text("old content\n")

    assert _run(monkeypatch, "--out", str(out), "--force") == 0

    assert out.read_text() == (
        json.dumps(CASES[0], ensure_ascii=False, separators=(",", ":")) + "\n"
    )
