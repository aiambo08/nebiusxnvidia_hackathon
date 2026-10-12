"""`scripts/spike_walkby.py`: person walk-by trials for `fov_shift` false positives (F3)."""

import json
import sys

import pytest
import spike_walkby as walk


def _w(t, phase, trial, faults=(), mse=0.3, frames=5, quality="ok", confirmed=None, tx=0.5):
    return {"t_s": float(t), "phase": phase, "trial": trial, "frames": frames,
            "state": "HEALTHY", "faults": list(faults), "confirmed": confirmed,
            "temporal_mse_p50": mse if frames else None, "occluded_cell_ratio": 0.0,
            "brightness_p50": 120.0, "translation_px": tx if frames else None,
            "rotation_deg": 0.1, "homography_inlier_ratio": 0.9, "match_count": 200,
            "quality": quality}


def _run(trials=3, walk_mse=500.0, **over):
    rows = [_w(t, "calibrate", 0) for t in range(3)]
    t = 3
    for k in range(1, trials + 1):
        rows += [_w(t + i, "walk", k, mse=walk_mse) for i in range(2)]
        rows += [_w(t + 2 + i, "rest", k) for i in range(2)]
        t += 4
    for i, kw in over.items():
        rows[int(i[1:])].update(kw)
    return rows


def test_schedule_is_calibrate_then_walk_rest_per_trial():
    s = walk.schedule(2, 30, 8, 12)
    assert s == [("calibrate", 0, 30), ("walk", 1, 8), ("rest", 1, 12), ("walk", 2, 8),
                 ("rest", 2, 12)]


def test_all_trials_observed_without_fov_shift_pass():
    s = walk.summarise(_run(), 3)
    assert s["exit_code"] == 0 and s["observed_trials"] == 3 and s["fov_shift_windows"] == 0
    assert s["verdict"] == "PASS: 0 `fov_shift` windows across 3 walk-by trials"
    assert [t["walk_mse_max"] for t in s["per_trial"]] == [500.0] * 3


@pytest.mark.parametrize("idx", [1, 4, 6])  # calibrate, trial 1 walk, trial 1 rest
def test_any_fov_shift_window_fails_even_unconfirmed(idx):
    s = walk.summarise(_run(**{f"w{idx}": {"faults": ["fov_shift"], "translation_px": 31.25}}), 3)
    assert s["exit_code"] == 1 and s["fov_shift_windows"] == 1 and s["fov_shift_confirmed"] == 0
    assert "31.25 px" in s["verdict"] and s["verdict"].startswith("FAIL")


def test_other_faults_are_findings_not_failures():
    rows = _run(w3={"faults": ["lens_occlusion"], "confirmed": ["lens_occlusion"]})
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 0 and s["other_fault_windows"] == {"lens_occlusion": 1}


def test_a_walk_without_motion_is_not_a_trial():
    """The owner missed the cue: nothing crossed, so that trial proves nothing."""
    rows = _run()
    for w in rows:
        if w["trial"] == 2 and w["phase"] == "walk":
            w["temporal_mse_p50"] = walk.MOTION_MSE_MIN - 0.1
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and s["observed_trials"] == 2
    assert [t["observed"] for t in s["per_trial"]] == [True, False, True]


def test_a_trial_without_frames_is_not_observed():
    rows = _run()
    for w in rows:
        if w["trial"] == 1 and w["phase"] == "rest":
            w.update(frames=0, temporal_mse_p50=None, translation_px=None)
    rows[3].update(frames=0, temporal_mse_p50=None, translation_px=None)
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and not s["per_trial"][0]["observed"]


def test_low_texture_scene_is_inconclusive_not_pass():
    """`fov_shift` needs geometry quality `ok`: a plain wall could never fail the gate."""
    rows = _run()
    for w in rows:
        if w["phase"] != "walk":
            w["quality"] = "low_texture"
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and "point the camera at a textured scene" in s["verdict"]


def test_missing_trials_are_inconclusive():
    s = walk.summarise(_run(trials=2), 3)
    assert s["exit_code"] == 3 and s["per_trial"][2]["windows"] == 0


def _argv(*extra):
    return ["walk", "--trials", "2", "--calibrate-s", "3", "--walk-s", "2", "--rest-s", "2",
            *extra]


def test_dry_run_passes_and_writes_reports_without_the_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "dry walk"))
    assert walk.main() == 0
    md = tmp_path / "spikes" / "walkby-dry-walk.md"
    js = json.loads(md.with_suffix(".json").read_text())
    assert "SIMULATION" in md.read_text() and "| 2 |" in md.read_text()
    assert js["summary"]["observed_trials"] == 2 and js["summary"]["fov_shift_windows"] == 0
    assert {w["phase"] for w in js["windows"]} == {"calibrate", "walk", "rest"}
    assert "uri" not in json.dumps(js).lower()
    assert js["commit"] == walk.code_revision() != "unknown"


def test_dry_run_with_a_moved_camera_fails(tmp_path, monkeypatch):
    """Negative control: the harness must see a real view shift during trial 1."""
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", _argv("--synthetic-bump", "--label", "bump"))
    assert walk.main() == 1
    js = json.loads((tmp_path / "spikes" / "walkby-bump.json").read_text())
    assert js["summary"]["per_trial"][0]["fov_shift_windows"] > 0


def test_existing_report_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    (tmp_path / "spikes").mkdir()
    old = tmp_path / "spikes" / "walkby-x.md"
    old.write_text("old")
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "x"))
    with pytest.raises(SystemExit) as exc:
        walk.main()
    assert exc.value.code == 2 and old.read_text() == "old"


@pytest.mark.parametrize("label", ["rtsp://h/x", "192.168.1.20", r"C:\Users\someone\cam"])
def test_label_with_url_ip_or_path_is_rejected(label, monkeypatch):
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", label))
    with pytest.raises(SystemExit) as exc:
        walk.main()
    assert exc.value.code == 2
