"""`scripts/spike_static_scene.py`: the live static-scene spike (F3 real-hardware re-check)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import spike_static_scene as spike

ROOT = Path(__file__).resolve().parents[2]


def _row(t, faults=(), confirmed=None, exact=0.0, loop=0, frames=5):
    return {"t_s": t, "frames": frames, "state": "HEALTHY", "faults": list(faults),
            "confirmed": confirmed, "exact_repeat_ratio": exact, "noise_ratio_p50": 1.0,
            "temporal_sigma_p50": 1.8, "temporal_mse_p50": 6.0, "repeated_hash_ratio": 0.0,
            "loop_period": loop}


def test_summarise_counts_freeze_windows_and_first_confirmation():
    rows = [_row(1.0), _row(2.0, frames=0, exact=None, loop=None),
            _row(3.0, ["freeze"], exact=1.0), _row(4.0, ["freeze"], exact=0.95),
            _row(5.0, ["freeze"], confirmed=["freeze"], exact=1.0, loop=4),
            _row(6.0, ["fov_shift"]), _row(7.0, ["freeze"], confirmed=["freeze"], exact=1.0)]
    s = spike.summarise(rows, 0.9)
    assert s["windows"] == 7 and s["valid_windows"] == 6
    assert s["freeze_windows"] == 4 and s["other_fault_windows"] == 1
    assert s["confirmed"] == ["freeze"] and s["confirmed_at_s"] == 5.0
    assert s["exact_repeat_ge_min"] == 4 and s["loop_windows"] == 1
    assert s["metrics"]["exact_repeat_ratio"]["n"] == 6
    assert s["metrics"]["exact_repeat_ratio"]["max"] == 1.0
    assert s["metrics"]["noise_ratio_p50"]["p50"] == 1.0
    assert s["exit_code"] == 1
    assert s["verdict"].startswith("FAIL: `freeze` in 4 window(s), first at 3 s")


def test_freeze_windows_after_another_confirmed_incident_still_fail():
    """The tracker stays CONFIRMED without an orchestrator, so a later freeze never 'confirms';
    the verdict counts freeze windows, like `static-scene.md` (reviewer finding)."""
    rows = [_row(1.0, ["fov_shift"]), _row(2.0, ["fov_shift"]),
            _row(3.0, ["fov_shift"], confirmed=["fov_shift"])]
    rows += [_row(10.0 + i, ["freeze"], exact=1.0) for i in range(10)]
    s = spike.summarise(rows, 0.9)
    assert s["confirmed"] == ["fov_shift"] and s["freeze_windows"] == 10
    assert s["exit_code"] == 1 and "FAIL" in s["verdict"] and "fov_shift" in s["verdict"]


def test_no_picture_is_inconclusive_not_pass():
    empty = [_row(float(t), frames=0, exact=None, loop=None) for t in range(1, 25)]
    s = spike.summarise(empty, 0.9)
    assert s["exit_code"] == 3 and s["verdict"].startswith("INCONCLUSIVE: 0/24")
    cut = [_row(1.0), _row(2.0)] + [_row(float(t), ["stream_down"], frames=0, exact=None,
                                         loop=None) for t in range(3, 25)]
    s = spike.summarise(cut, 0.9)
    assert s["exit_code"] == 3 and "22 with stream_down/low_fps" in s["verdict"]
    assert spike.summarise([], 0.9)["exit_code"] == 3
    one_hiccup = [_row(float(t)) for t in range(1, 40)] + [_row(40.0, frames=0, exact=None,
                                                                loop=None)]
    assert spike.summarise(one_hiccup, 0.9)["exit_code"] == 0


def test_render_verdicts():
    healthy = spike.summarise([_row(1.0), _row(2.0)], 0.9)
    txt = spike.render("wall", "rtsp", 20, 5, "640x480", healthy, {"transport": {}}, 0, 10, 0.9)
    assert "REAL HARDWARE" in txt and "PASS: no `freeze` window" in txt and "0/10" in txt
    frozen = spike.summarise([_row(3.0, ["freeze"], confirmed=["freeze"], exact=1.0)], 0.9)
    txt = spike.render("wall", "rtsp", 20, 5, "640x480", frozen, {"transport": {}}, 0, 5, 0.9)
    assert "FAIL: `freeze` in 1 window(s), first at 3 s; confirmed: freeze at 3 s" in txt
    other = spike.summarise([_row(9.0, ["fov_shift"], confirmed=["fov_shift"])], 0.9)
    txt = spike.render("wall", "rtsp", 20, 5, "640x480", other, {"transport": {}}, 0, 5, 0.9)
    assert txt.count("PASS") == 1 and "finding: fov_shift confirmed at 9 s" in txt
    dry = spike.render("x", "synthetic", 1, 5, "640x480", healthy, {"transport": {}}, 0, 5, 0.9)
    assert "SIMULATION" in dry


def test_dry_run_writes_reports_without_the_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(spike, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["spike", "--synthetic", "--minutes", "0.1",
                                      "--label", "dry run/wall q=50"])
    assert spike.main() == 0
    md = tmp_path / "spikes" / "static-scene-dry-run-wall-q-50.md"
    js = json.loads((md.with_suffix(".json")).read_text())
    assert "SIMULATION" in md.read_text()
    assert js["summary"]["windows"] >= 4 and js["summary"]["freeze_windows"] == 0
    assert js["summary"]["confirmed"] is None and js["summary"]["exit_code"] == 0
    assert js["polls"] >= js["summary"]["windows"] * 4 and js["stalled_polls"] == 0
    assert js["windows"][-1]["exact_repeat_ratio"] == 0.0
    assert js["windows"][-1]["noise_ratio_p50"] is not None
    assert "uri" not in json.dumps(js).lower()


@pytest.mark.parametrize("label", ["rtsp://10.0.0.1:8080/x", "wall 192.168.1.20",
                                   "http://cam/video", "wall-192-168-1-20"])
def test_label_with_url_or_ip_is_rejected(label, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["spike", "--synthetic", "--minutes", "0.1", "--label", label])
    with pytest.raises(SystemExit) as e:
        spike.main()
    assert e.value.code == 2


def test_cli_help_runs_without_hardware():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "spike_static_scene.py"), "-h"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "--label" in r.stdout
