import numpy as np
import pytest

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.contracts.models import FaultType, IncidentState
from reliability_agent.incidents.fusion import (
    NOISE_FLOOR_METRIC,
    IncidentTracker,
    classify_window,
    rank_faults,
)
from tests.conftest import make_window

FAULT_WINDOWS = {
    FaultType.BLACKOUT: dict(visual=dict(brightness_p50=8.0, black_pixel_ratio=0.97)),
    FaultType.OVEREXPOSURE: dict(visual=dict(white_pixel_ratio=0.7)),
    FaultType.FOCUS_DRIFT: dict(visual=dict(blur_effect_p50=0.7, edge_density_p50=0.01)),
    FaultType.FREEZE: dict(visual=dict(exact_repeat_ratio=1.0, repeated_hash_ratio=1.0)),
    FaultType.LENS_OCCLUSION: dict(visual=dict(occluded_cell_ratio=0.5)),
    FaultType.FOV_SHIFT: dict(geometry=dict(translation_px=60.0)),
    FaultType.STREAM_DOWN: dict(transport=dict(frame_age_ms_p95=9000.0)),
}


def test_baseline_zscore_and_freeze():
    b = RobustBaseline(window=50, min_samples=10)
    rng = np.random.default_rng(0)
    for x in rng.normal(100, 2, 30):
        b.update({"m": x})
    assert b.ready
    assert b.z("m", 100) < 1.5
    assert b.z("m", 130) > 6
    v = b.version
    assert not b.update({"m": 1e6}, frozen=True)
    assert b.version == v  # frozen baseline does not learn the fault


def test_baseline_roundtrip():
    b = RobustBaseline(min_samples=2)
    for x in (1.0, 2.0, 3.0):
        b.update({"a": x})
    b2 = RobustBaseline.from_dict(b.to_dict())
    assert b2.version == b.version and b2.median("a") == 2.0


@pytest.mark.parametrize("fault,kw", list(FAULT_WINDOWS.items()))
def test_each_fault_rule_fires(cfg, fault, kw):
    faults, ev = classify_window(make_window(**kw), None, cfg["faults"])
    assert fault in faults, faults
    assert ev


def test_healthy_window_has_no_faults(cfg):
    faults, _ = classify_window(make_window(), None, cfg["faults"])
    assert faults == {}


def test_blackout_is_not_reported_as_occlusion_or_blur(cfg):
    w = make_window(visual=dict(brightness_p50=5.0, black_pixel_ratio=0.99,
                                occluded_cell_ratio=1.0, blur_effect_p50=0.9))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert set(faults) == {FaultType.BLACKOUT}


def _tracker(cfg):
    f = cfg["fusion"]
    return IncidentTracker("cam", cfg["faults"], f["enter_windows"], f["exit_windows"],
                           f["cooldown_s"], RobustBaseline(min_samples=5))


@pytest.mark.parametrize("fault", [FaultType.BLACKOUT, FaultType.FOCUS_DRIFT, FaultType.FREEZE,
                                   FaultType.LENS_OCCLUSION, FaultType.OVEREXPOSURE])
def test_mvp_faults_reach_confirmed(cfg, fault):
    t = _tracker(cfg)
    for _ in range(10):
        t.step(make_window())
    incident = None
    for _ in range(3):
        step = t.step(make_window(**FAULT_WINDOWS[fault]))
        incident = incident or step.incident
    assert t.fsm.state is IncidentState.CONFIRMED
    assert incident and incident.candidate_faults[0] is fault
    assert incident.baseline_ref


def test_transient_glitch_returns_to_healthy_without_incident(cfg):
    t = _tracker(cfg)
    for _ in range(10):
        t.step(make_window())
    t.step(make_window(**FAULT_WINDOWS[FaultType.BLACKOUT]))  # 1 bad window (lights flicker)
    steps = [t.step(make_window()) for _ in range(3)]
    assert t.fsm.state is IncidentState.HEALTHY
    assert all(s.incident is None for s in steps)


def test_baseline_not_learned_while_suspect(cfg):
    t = _tracker(cfg)
    for _ in range(10):
        t.step(make_window())
    n = t.baseline.updates
    t.step(make_window(**FAULT_WINDOWS[FaultType.FOCUS_DRIFT]))
    t.step(make_window(**FAULT_WINDOWS[FaultType.FOCUS_DRIFT]))
    assert t.baseline.updates == n


def test_determinism_same_events_same_states(cfg):
    seq = [make_window()] * 8 + [make_window(**FAULT_WINDOWS[FaultType.FREEZE])] * 4
    traces = []
    for _ in range(2):
        t = _tracker(cfg)
        for w in seq:
            t.step(w)
        traces.append(t.fsm.trace())
    assert traces[0] == traces[1]


@pytest.mark.parametrize("p_bad", [0.1, 0.2, 0.3])
def test_hysteresis_reduces_alert_flapping(cfg, p_bad):
    """Gate F5: alert-level state changes drop >= 50% vs a frame-by-frame detector.

    The naive detector alerts on every bad window. The tracker only alerts on CONFIRMED;
    SUSPECT is internal. Each confirmed incident counts as 2 changes (open + close).
    """
    from reliability_agent.incidents.state_machine import IncidentStateMachine

    bad = np.random.default_rng(1).random(400) < p_bad
    naive_changes = int(np.sum(bad[1:] != bad[:-1]))
    t = _tracker(cfg)
    incidents = 0
    for b in bad:
        step = t.step(make_window(**FAULT_WINDOWS[FaultType.BLACKOUT]) if b else make_window())
        if step.incident:
            incidents += 1
            t.fsm = IncidentStateMachine()  # orchestrator closes it
            t.reset_healthy()
    assert 2 * incidents <= 0.5 * naive_changes


def test_cooldown_suppresses_refire(cfg):
    t = _tracker(cfg)
    t.suppress([FaultType.BLACKOUT], now_s=0.0)
    step = t.step(make_window(**FAULT_WINDOWS[FaultType.BLACKOUT]), now_s=5.0)
    assert FaultType.BLACKOUT not in step.faults
    step = t.step(make_window(**FAULT_WINDOWS[FaultType.BLACKOUT]), now_s=25.0)
    assert FaultType.BLACKOUT in step.faults


def _noise_floor_baseline(mse_values):
    b = RobustBaseline(min_samples=5)
    for m in mse_values:
        b.update({NOISE_FLOOR_METRIC: m})
    return b


def test_static_scene_hash_repeats_are_not_freeze(cfg):
    # identical perceptual hash but real sensor noise between frames -> not frozen
    w = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                temporal_mse_p50=6.0))
    assert FaultType.FREEZE not in classify_window(w, None, cfg["faults"])[0]
    # ADR-004: with a camera whose healthy noise floor is ~12 the same hash repeats with the
    # pixel differences collapsed to 0.1 are a freeze ...
    w2 = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                 temporal_mse_p50=0.1))
    noisy_cam = _noise_floor_baseline([12.0 + 0.1 * i for i in range(30)])
    faults, ev = classify_window(w2, noisy_cam, cfg["faults"])
    assert FaultType.FREEZE in faults
    assert any(e.note == "sensor noise collapsed" and e.baseline for e in ev)
    # ... but a quiet sensor whose healthy floor *is* 0.4 (lit static scene, sigma 2 counts
    # after the 4x4 downscale) is alive at 0.4, even though that sits below the absolute floor
    quiet_cam = _noise_floor_baseline([0.4 + 0.01 * (i % 7) for i in range(30)])
    w3 = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                 temporal_mse_p50=0.41))
    assert FaultType.FREEZE not in classify_window(w3, quiet_cam, cfg["faults"])[0]
    # and the same quiet camera with its noise gone (codec jitter only) is frozen
    w4 = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                 temporal_mse_p50=0.05))
    assert FaultType.FREEZE in classify_window(w4, quiet_cam, cfg["faults"])[0]


def test_hash_repeats_need_a_learned_noise_floor(cfg):
    """Cold start (no baseline): only bit-exact repeats and loops are freeze evidence."""
    w = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                temporal_mse_p50=0.0001))
    assert FaultType.FREEZE not in classify_window(w, None, cfg["faults"])[0]
    exact = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=1.0,
                                    temporal_mse_p50=0.0))
    assert FaultType.FREEZE in classify_window(exact, None, cfg["faults"])[0]
    loop = make_window(visual=dict(repeated_hash_ratio=0.0, exact_repeat_ratio=0.0,
                                   temporal_mse_p50=30.0, loop_period=4))
    assert FaultType.FREEZE in classify_window(loop, None, cfg["faults"])[0]


def test_baseline_quantile_is_the_quiet_tail():
    b = _noise_floor_baseline([float(x) for x in range(1, 31)])
    assert b.quantile(NOISE_FLOOR_METRIC, 0.1) == pytest.approx(3.9)
    assert b.quantile(NOISE_FLOOR_METRIC, 0.5) == b.median(NOISE_FLOOR_METRIC)
    assert RobustBaseline().quantile(NOISE_FLOOR_METRIC, 0.1) is None


def test_quiet_static_camera_never_confirms_freeze_through_the_tracker(cfg):
    """SIMULATION of the F3 gate row: healthy static scene, quiet sensor, many windows."""
    t = _tracker(cfg)
    rng = np.random.default_rng(1)
    for _ in range(400):
        step = t.step(make_window(visual=dict(
            repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
            temporal_mse_p50=float(rng.uniform(0.35, 0.5)))))
        assert step.incident is None
    assert t.fsm.state is IncidentState.HEALTHY
    assert t.baseline.ready


def test_frozen_overexposed_window_ranks_freeze_first(cfg):
    w = make_window(visual=dict(
        white_pixel_ratio=0.6,
        repeated_hash_ratio=1.0,
        exact_repeat_ratio=1.0,
        temporal_mse_p50=0.0,
    ))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert set(faults) == {FaultType.FREEZE, FaultType.OVEREXPOSURE}
    assert rank_faults(faults)[0] is FaultType.FREEZE


def test_rank_faults_orders_by_score_then_priority():
    F = FaultType
    scores = {F.OVEREXPOSURE: 1.0, F.LENS_OCCLUSION: 1.0, F.FREEZE: 1.0, F.FOV_SHIFT: 0.4,
              F.STREAM_DOWN: 1.0}
    assert rank_faults(scores) == [F.STREAM_DOWN, F.FREEZE, F.OVEREXPOSURE, F.LENS_OCCLUSION,
                                   F.FOV_SHIFT]
    # equal score and priority keep the evaluation order (the e2e overexposure scenario needs it)
    assert rank_faults({F.LENS_OCCLUSION: 1.0, F.OVEREXPOSURE: 1.0}) == [F.LENS_OCCLUSION,
                                                                          F.OVEREXPOSURE]


def test_dark_live_scene_is_blackout_not_freeze(cfg):
    # Darkening crushes sensor noise: pixels repeat (even bit-exactly) although the camera is
    # live. Blackout explains the missing motion, so freeze must not be claimed on top of it.
    w = make_window(visual=dict(brightness_p50=8.0, black_pixel_ratio=0.97,
                                repeated_hash_ratio=1.0, exact_repeat_ratio=0.6,
                                temporal_mse_p50=0.001))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert set(faults) == {FaultType.BLACKOUT}, faults


def test_strong_blur_hash_repeats_are_not_freeze(cfg):
    # Strong blur removes high-frequency noise, so hashes repeat and the pixel MSE falls under the
    # noise floor on a live camera. Focus drift explains it; only bit-exact repeats mean a freeze.
    w = make_window(visual=dict(blur_effect_p50=0.7, edge_density_p50=0.01,
                                repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                temporal_mse_p50=0.1))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert FaultType.FOCUS_DRIFT in faults
    assert FaultType.FREEZE not in faults, faults
    w2 = make_window(visual=dict(blur_effect_p50=0.7, edge_density_p50=0.01,
                                 repeated_hash_ratio=1.0, exact_repeat_ratio=1.0,
                                 temporal_mse_p50=0.0))
    assert FaultType.FREEZE in classify_window(w2, None, cfg["faults"])[0]


def test_frozen_dark_pipeline_is_attributed_to_blackout(cfg):
    # Documented limitation: a frozen frame that is also black is reported as blackout only; the
    # freeze becomes measurable once exposure is restored (ADR-003).
    w = make_window(visual=dict(brightness_p50=3.0, black_pixel_ratio=0.99,
                                repeated_hash_ratio=1.0, exact_repeat_ratio=1.0,
                                temporal_mse_p50=0.0))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert set(faults) == {FaultType.BLACKOUT}


def _motion_window(rng):
    return make_window(visual=dict(repeated_hash_ratio=0.0, exact_repeat_ratio=0.0,
                                   temporal_mse_p50=float(rng.uniform(20.0, 40.0))))


def _still_window(rng, lo=0.35, hi=0.5):
    return make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                   temporal_mse_p50=float(rng.uniform(lo, hi))))


def test_noise_floor_is_learned_from_still_windows_only(cfg):
    """Reviewer case: a person walks by while the baseline is learned, then the scene rests.
    Motion windows carry scene change, not sensor noise, so they must not define the floor."""
    t = _tracker(cfg)
    rng = np.random.default_rng(7)
    for _ in range(60):  # 2 min of motion: baseline ready, but no still window learned yet
        assert t.step(_motion_window(rng)).incident is None
    assert t.baseline.ready
    assert t.baseline.quantile(NOISE_FLOOR_METRIC, 0.1) is None
    for _ in range(400):  # scene rests at its normal noise: never a freeze
        step = t.step(_still_window(rng))
        assert step.incident is None, step
    assert t.fsm.state is IncidentState.HEALTHY
    floor = t.baseline.quantile(NOISE_FLOOR_METRIC, 0.1)
    assert floor is not None and 0.3 < floor < 0.45
    # the noise then really collapses (frozen frames differing only by codec dither)
    incident = None
    for _ in range(10):
        incident = t.step(_still_window(rng, 0.0, 0.05)).incident or incident
    assert incident is not None and FaultType.FREEZE in incident.candidate_faults


def test_alternating_motion_and_rest_never_confirms_freeze(cfg):
    t = _tracker(cfg)
    rng = np.random.default_rng(11)
    for cycle in range(8):
        for _ in range(15):
            assert t.step(_motion_window(rng)).incident is None
        for _ in range(15):
            assert t.step(_still_window(rng)).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def test_tracker_sample_tags_noise_windows(cfg):
    t = _tracker(cfg)
    rng = np.random.default_rng(3)
    assert NOISE_FLOOR_METRIC not in t._sample(_motion_window(rng))
    s = t._sample(_still_window(rng))
    assert s[NOISE_FLOOR_METRIC] == s["visual.temporal_mse_p50"]


def test_small_moving_object_does_not_raise_the_noise_floor(cfg):
    """Reviewer case: a 10-20 px object keeps the dHash but raises the MSE (0.7-1.5). Those
    windows are scene change, not noise; once the object stops the scene must stay healthy."""
    t = _tracker(cfg)
    rng = np.random.default_rng(5)
    for _ in range(150):  # 5 min of a small object moving: hash repeats, MSE above the cap
        assert t.step(_still_window(rng, 0.7, 1.5)).incident is None
    assert t.baseline.quantile(NOISE_FLOOR_METRIC, 0.1) is None
    for _ in range(300):  # object stops, smooth wall at rest (sigma 0.7: MSE ~0.011)
        assert t.step(_still_window(rng, 0.008, 0.015)).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def test_textured_scene_learns_a_floor_and_still_catches_a_jittered_freeze(cfg):
    """Reviewer regression: textured healthy windows never repeat a hash, but their MSE is
    sensor noise and must teach the floor, so a frozen stream with codec jitter is caught."""
    t = _tracker(cfg)
    rng = np.random.default_rng(9)
    for _ in range(60):
        w = make_window(visual=dict(repeated_hash_ratio=0.43, exact_repeat_ratio=0.0,
                                    temporal_mse_p50=float(rng.uniform(0.35, 0.48))))
        assert t.step(w).incident is None
    assert t.baseline.quantile(NOISE_FLOOR_METRIC, 0.1) is not None
    incident = None
    for _ in range(10):  # frozen + jitter 0.2: hash repeats, MSE ~0.04
        incident = t.step(_still_window(rng, 0.03, 0.05)).incident or incident
    assert incident is not None and FaultType.FREEZE in incident.candidate_faults
