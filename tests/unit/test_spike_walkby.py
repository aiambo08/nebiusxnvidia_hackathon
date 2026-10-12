"""`scripts/spike_walkby.py`: person walk-by trials for `fov_shift` false positives (F3)."""

import json
import sys

import pytest
import spike_walkby as walk


def _w(t, phase, trial, faults=(), mse=0.3, frames=5, armed=True, confirmed=None, tx=0.5,
       inlier=0.9):
    return {"t_s": float(t), "phase": phase, "trial": trial, "frames": frames,
            "state": "HEALTHY", "faults": list(faults), "confirmed": confirmed,
            "armed": armed and frames > 0,
            "temporal_mse_p50": mse if frames else None, "occluded_cell_ratio": 0.0,
            "brightness_p50": 120.0, "translation_px": tx if frames else None,
            "rotation_deg": 0.1, "homography_inlier_ratio": inlier if frames else None,
            "match_count": 200, "quality": "ok"}


def _run(trials=3, walk_mse=500.0, bump=None):
    rows = [_w(t, "calibrate", 0) for t in range(3)]
    t = 3
    for k in range(1, trials + 1):
        rows += [_w(t + i, "walk", k, mse=walk_mse) for i in range(4)]
        rows += [_w(t + 4 + i, "rest", k) for i in range(4)]
        t += 8
    if bump is not None:
        rows += [_w(t + i, "bump", 0, faults=["fov_shift"] if bump else []) for i in range(3)]
    return rows


def _set(rows, trial, phase, **kw):
    for w in rows:
        if w["trial"] == trial and w["phase"] == phase:
            w.update(kw)
    return rows


def test_schedule_is_calibrate_walk_rest_per_trial_then_bump():
    assert walk.schedule(2, 30, 8, 12, 10) == [
        ("calibrate", 0, 30), ("walk", 1, 8), ("rest", 1, 12), ("walk", 2, 8), ("rest", 2, 12),
        ("bump", 0, 10)]
    assert walk.schedule(1, 30, 8, 12)[-1] == ("rest", 1, 12)


def test_armed_needs_quality_ok_and_the_rule_inlier_ratio():
    assert walk.is_armed({"quality": "ok", "homography_inlier_ratio": 0.35}, 0.35)
    assert not walk.is_armed({"quality": "ok", "homography_inlier_ratio": 0.05}, 0.35)
    assert not walk.is_armed({"quality": "ok", "homography_inlier_ratio": None}, 0.35)
    assert not walk.is_armed({"quality": "low_texture", "homography_inlier_ratio": 0.9}, 0.35)


def test_all_trials_observed_without_fov_shift_pass():
    s = walk.summarise(_run(bump=True), 3, bump=True)
    assert s["exit_code"] == 0 and s["observed_trials"] == 3 and s["fov_shift_windows"] == 0
    assert s["verdict"] == "PASS: 0 `fov_shift` windows across 3 walk-by trials, BUMP detected"
    assert [t["walk_mse_max"] for t in s["per_trial"]] == [500.0] * 3


@pytest.mark.parametrize("phase", ["walk", "rest"])
def test_any_fov_shift_window_fails_even_unconfirmed(phase):
    rows = _run()
    next(w for w in rows if w["phase"] == phase).update(faults=["fov_shift"], translation_px=31.25)
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 1 and s["fov_shift_windows"] == 1 and s["fov_shift_confirmed"] == 0
    assert "31.25 px" in s["verdict"] and s["verdict"].startswith("FAIL")


def test_calibrate_fov_shift_is_reported_not_judged():
    """Before the reference is re-taken a person in the first frame can move the fit."""
    rows = _run()
    rows[0]["faults"] = ["fov_shift"]
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 0 and s["calibrate_fov_shift_windows"] == 1


def test_other_faults_are_findings_not_failures():
    rows = _run()
    rows[4].update(faults=["lens_occlusion"], confirmed=["lens_occlusion"])
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 0 and s["other_fault_windows"] == {"lens_occlusion": 1}


def test_a_walk_without_motion_is_not_a_trial():
    """The owner missed the cue: nothing crossed, so that trial proves nothing."""
    rows = _set(_run(), 2, "walk", temporal_mse_p50=walk.MOTION_MSE_MIN - 0.1)
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and s["observed_trials"] == 2
    assert [t["observed"] for t in s["per_trial"]] == [True, False, True]


def test_spare_trials_absorb_a_missed_cue():
    rows = _set(_run(), 2, "walk", temporal_mse_p50=0.2)
    assert walk.summarise(rows, 3, min_observed=2)["exit_code"] == 0


def test_a_walk_seen_for_one_second_only_is_not_a_trial():
    """Reviewer case: frames stop after 1 s of the WALK while REST is fine."""
    rows = _run()
    for w in [w for w in rows if w["trial"] == 1 and w["phase"] == "walk"][1:]:
        w.update(frames=0, armed=False, temporal_mse_p50=None, translation_px=None)
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and not s["per_trial"][0]["observed"]
    assert s["per_trial"][0]["walk_armed"] == 1


def test_a_disarmed_walk_is_not_a_trial():
    rows = _set(_run(), 1, "walk", armed=False, homography_inlier_ratio=0.1)
    assert not walk.summarise(rows, 3)["per_trial"][0]["observed"]


def test_plain_wall_with_quality_ok_but_no_inliers_is_inconclusive():
    """Reviewer case: `equalizeHist` keypoints keep quality `ok`, yet no shift can be seen."""
    rows = _run()
    for w in rows:
        if w["phase"] == "rest":
            w.update(armed=False, homography_inlier_ratio=0.05)
    s = walk.summarise(rows, 3)
    assert s["exit_code"] == 3 and "point the camera at a textured scene" in s["verdict"]


def test_undetected_bump_is_inconclusive():
    s = walk.summarise(_run(bump=False), 3, bump=True)
    assert s["exit_code"] == 3 and "BUMP raised no `fov_shift`" in s["verdict"]
    assert s["bump"] == {"windows": 3, "fov_shift_detected": False}


@pytest.mark.parametrize("ref", ["not_still", "no_frame", "no_features"])
def test_no_still_reference_is_inconclusive(ref):
    s = walk.summarise(_run(), 3, reference=ref)
    assert s["exit_code"] == 3 and walk.REFERENCE[ref] in s["verdict"]


def test_translation_is_reported_on_armed_windows_only():
    rows = _run()
    rows[3].update(armed=False, translation_px=1400.0, homography_inlier_ratio=0.02)
    t = walk.summarise(rows, 3)["per_trial"][0]
    assert t["translation_px_max_armed"] == 0.5 and t["inlier_max"] == 0.9


def _argv(*extra):
    return ["walk", "--trials", "2", "--min-observed", "2", "--start-delay", "0",
            "--calibrate-s", "6", "--walk-s", "2", "--rest-s", "2", "--bump-s", "3", *extra]


def test_dry_run_passes_and_writes_reports_without_the_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "dry walk"))
    assert walk.main() == 0
    md = tmp_path / "spikes" / "walkby-dry-walk.md"
    js = json.loads(md.with_suffix(".json").read_text())
    assert "SIMULATION" in md.read_text() and "| 2 |" in md.read_text()
    s = js["summary"]
    assert s["observed_trials"] == 2 and s["fov_shift_windows"] == 0 and s["reference"] == "ok"
    assert s["bump"]["fov_shift_detected"]
    assert {w["phase"] for w in js["windows"]} >= {"calibrate", "walk", "rest", "bump"}
    assert "uri" not in json.dumps(js).lower()
    assert js["commit"] == walk.code_revision() != "unknown"


def test_dry_run_with_a_moved_camera_fails(tmp_path, monkeypatch):
    """Negative control: the harness must see a real view shift during trial 1."""
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", _argv("--synthetic-bump", "--label", "bump"))
    assert walk.main() == 1
    js = json.loads((tmp_path / "spikes" / "walkby-bump.json").read_text())
    assert js["summary"]["per_trial"][0]["fov_shift_windows"] > 0


def test_person_in_front_at_start_up_does_not_become_the_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(walk.WalkBySource, "walk_until_seq", 30)  # first second of CALIBRATE
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "start"))
    assert walk.main() == 0


def test_motion_through_calibrate_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(walk.WalkBySource, "walk_until_seq", 10**9)
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "busy"))
    assert walk.main() == 3
    js = json.loads((tmp_path / "spikes" / "walkby-busy.json").read_text())
    assert js["summary"]["reference"] == "not_still"
    assert {w["phase"] for w in js["windows"]} <= {"handshake", "calibrate"}


def test_existing_report_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(walk, "REPO_ROOT", tmp_path)
    (tmp_path / "spikes").mkdir()
    old = tmp_path / "spikes" / "walkby-x.md"
    old.write_text("old")
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", "--label", "x"))
    with pytest.raises(SystemExit) as exc:
        walk.main()
    assert exc.value.code == 2 and old.read_text() == "old"


@pytest.mark.parametrize("extra", [["--label", "rtsp://h/x"], ["--label", "192.168.1.20"],
                                   ["--label", r"C:\Users\someone\cam"],
                                   ["--min-observed", "3"]])
def test_bad_label_or_min_observed_is_rejected(extra, monkeypatch):
    monkeypatch.setattr(sys, "argv", _argv("--synthetic", *extra))
    with pytest.raises(SystemExit) as exc:
        walk.main()
    assert exc.value.code == 2
