"""`scripts/bench_hysteresis.py`: tracker vs memoryless detector flapping (F5, SIMULATION)."""

import bench_hysteresis as bench
import numpy as np
import pytest

from reliability_agent.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config(env=False)


def test_schedule_is_deterministic_clean_during_calibration_and_holds_sustained_faults():
    bad, starts = bench.schedule(200, 0.2, seed=3)
    again, _ = bench.schedule(200, 0.2, seed=3)
    assert np.array_equal(bad, again)
    assert not bad[:bench.CALIB_WINDOWS].any() and len(bad) == bench.CALIB_WINDOWS + 200
    assert len(starts) == 3 and all(bad[s:s + bench.SUSTAINED_WINDOWS].all() for s in starts)
    assert not np.array_equal(bad, bench.schedule(200, 0.2, seed=4)[0])
    assert not np.array_equal(bad, bench.schedule(200, 0.2, seed=3, salt="dark/1")[0])


def test_a_run_is_deterministic(cfg):
    args = dict(kind="dark", p=0.2, seed=1, sigma=2.0, cfg=cfg, windows=30, calib=22,
                size=(160, 120))
    assert bench.run(**args) == bench.run(**args)


def test_a_freeze_repeats_the_last_frame_delivered_before_it():
    bad = np.array([False, True, True, False])
    frames = list(bench.clip(bad, "freeze", seed=0, sigma=2.0, per_window=2, size=(64, 48)))
    assert len(frames) == 8
    assert all(np.array_equal(frames[1], f) for f in frames[2:6])
    assert not np.array_equal(frames[6], frames[1])


def test_clip_keeps_the_occluder_still_within_a_run():
    bad = np.array([True, True])
    frames = list(bench.clip(bad, "occlude_opaque", seed=1, sigma=0.0, per_window=2,
                             size=(64, 48)))
    masks = [(f == 10).all(axis=(0, 2)) for f in frames]
    assert masks[0].any() and all(np.array_equal(masks[0], m) for m in masks[1:])


@pytest.mark.parametrize("kind", ["dark", "occlude_opaque"])
def test_tracker_flaps_less_and_still_alerts_on_every_sustained_fault(cfg, kind):
    r = bench.run(kind, 0.3, seed=0, sigma=2.0, cfg=cfg, windows=150, calib=25, size=(320, 240))
    assert r["calibrated"] and r["sustained_covered"] == r["sustained"] == 3
    assert r["naive_flaps"] >= bench.MIN_FLAPS
    assert r["tracker_flaps"] <= (1 - bench.REDUCTION_MIN) * r["naive_flaps"]
    assert r["tracker_changes"] <= (1 - bench.REDUCTION_MIN) * r["naive_changes"]


def test_flaps_exclude_the_changes_every_detector_owes_a_sustained_fault(cfg):
    r = bench.run("dark", 0.0, seed=0, sigma=2.0, cfg=cfg, windows=60, calib=25, size=(320, 240))
    assert r["bad_windows"] == 3 * bench.SUSTAINED_WINDOWS
    assert r["naive_changes"] == r["tracker_changes"] == 6
    assert r["naive_flaps"] == r["tracker_flaps"] == 0


def _cell(naive, tracker, covered=3, calibrated=1, kind="dark", flaps=None):
    nf, tf = flaps or (naive, tracker)
    return {"kind": kind, "p": 0.1, "naive_changes": naive, "tracker_changes": tracker,
            "naive_flaps": nf, "tracker_flaps": tf, "fsm_changes": 0,
            "sustained_covered": covered, "sustained": 3, "calibrated": bool(calibrated)}


def test_gate_needs_half_the_flaps_in_every_cell():
    assert bench.gate_ok(bench.aggregate([_cell(40, 20)]))
    assert not bench.gate_ok(bench.aggregate([_cell(40, 21)]))
    other = _cell(100, 0, kind="freeze")
    assert not bench.gate_ok(bench.aggregate([_cell(40, 30), other])), "per cell, not pooled"
    assert not bench.gate_ok(bench.aggregate([_cell(40, 30, flaps=(34, 10))])), "and overall"


def test_a_cell_without_flapping_passes_only_if_the_tracker_adds_none():
    quiet = _cell(8, 6, kind="freeze", flaps=(2, 0))
    assert bench.gate_ok(bench.aggregate([_cell(40, 10), quiet]))
    noisier = _cell(8, 8, kind="freeze", flaps=(2, 3))
    assert not bench.gate_ok(bench.aggregate([_cell(40, 10), noisier]))
    assert not bench.gate_ok(bench.aggregate([quiet])), "no evaluable cell is no evidence"


def test_a_tracker_that_never_alerts_cannot_pass():
    assert not bench.gate_ok(bench.aggregate([_cell(40, 0, covered=0)]))
    assert not bench.gate_ok(bench.aggregate([_cell(40, 0, calibrated=0)]))
    assert not bench.gate_ok({})
    assert not bench.gate_ok(bench.aggregate([_cell(0, 0)])), "no flapping to cut is no evidence"
