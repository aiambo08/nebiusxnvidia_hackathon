import numpy as np
import pytest

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.contracts.models import FaultType, IncidentState
from reliability_agent.incidents.fusion import (
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


def test_alternating_motion_and_rest_never_confirms_freeze(cfg):
    t = _tracker(cfg)
    rng = np.random.default_rng(11)
    for cycle in range(8):
        for _ in range(15):
            assert t.step(_motion_window(rng)).incident is None
        for _ in range(15):
            assert t.step(_still_window(rng)).incident is None
    assert t.fsm.state is IncidentState.HEALTHY




def _still_window(rng, noise_ratio=1.0, mse=(0.005, 0.02), sensor_sigma=0.7):
    """A static scene: every perceptual hash repeats, pixels differ only by sensor noise (a
    quiet sigma 0.7 sensor by default; the temporal sigma follows the ratio)."""
    return make_window(visual=dict(
        repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
        temporal_mse_p50=float(rng.uniform(*mse)), noise_ratio_p50=noise_ratio,
        temporal_sigma_p50=None if noise_ratio is None else sensor_sigma * noise_ratio))


def _frozen_window(rng=None):
    """A frozen pipeline: the same buffer is delivered again and again, bit-exact."""
    return make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.95,
                                   temporal_mse_p50=0.0, noise_ratio_p50=0.0,
                                   temporal_sigma_p50=0.0))


def test_static_scene_hash_repeats_are_never_freeze(cfg):
    """A live static scene repeats its perceptual hash. Fresh temporal noise (raw sensor), a
    collapsed ratio (H.264 skip blocks, ISP denoiser: ratio 0.00-0.04 in SIMULATION, see
    test_noise_ratio) or no measurable noise at all: none of it is a freeze (ADR-005)."""
    rng = np.random.default_rng(0)
    for ratio in (0.75, 1.0, 1.85, 0.17, 0.05, 0.0, None):
        faults, _ = classify_window(_still_window(rng, ratio), None, cfg["faults"])
        assert FaultType.FREEZE not in faults, ratio


def test_bit_exact_repeats_and_loops_are_freeze(cfg):
    faults, ev = classify_window(_frozen_window(), None, cfg["faults"])
    assert list(faults) == [FaultType.FREEZE]
    assert any(e.metric == "visual.noise_ratio_p50" for e in ev)
    w = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                temporal_mse_p50=0.3, loop_period=4.0))
    faults, ev = classify_window(w, None, cfg["faults"])
    assert list(faults) == [FaultType.FREEZE]
    assert any(e.metric == "visual.loop_period" for e in ev)


def test_exact_repeat_threshold_comes_from_config(cfg):
    rules = {k: dict(v) for k, v in cfg["faults"].items()}
    w = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.8,
                                temporal_mse_p50=0.0))
    faults, _ = classify_window(w, None, cfg["faults"])
    assert FaultType.FREEZE not in faults
    rules["freeze"]["exact_repeat_ratio_min"] = 0.7
    faults, _ = classify_window(w, None, rules)
    assert list(faults) == [FaultType.FREEZE]


def test_quiet_static_camera_never_confirms_freeze_through_the_tracker(cfg):
    """SIMULATION of the F3 gate row: healthy static scene, quiet sensor, many windows."""
    t = _tracker(cfg)
    rng = np.random.default_rng(1)
    for _ in range(400):
        step = t.step(_still_window(rng, float(rng.uniform(0.7, 1.9))))
        assert step.incident is None
    assert t.fsm.state is IncidentState.HEALTHY
    assert t.baseline.ready


def test_compressed_static_camera_never_confirms_freeze_through_the_tracker(cfg):
    """The demo path: a live static scene over H.264 (phone RTSP). The encoder removes the
    temporal noise in flat areas, so the hashes repeat and the ratio sits near 0, yet most
    frames are not bit-exact (SIMULATION with libx264 CRF 23: exact repeats 0.01)."""
    t = _tracker(cfg)
    rng = np.random.default_rng(6)
    for _ in range(400):
        w = make_window(visual=dict(repeated_hash_ratio=1.0,
                                    exact_repeat_ratio=float(rng.uniform(0.0, 0.6)),
                                    temporal_mse_p50=float(rng.uniform(0.0, 0.01)),
                                    noise_ratio_p50=float(rng.uniform(0.0, 0.05)),
                                    temporal_sigma_p50=float(rng.uniform(0.0, 0.05))))
        assert t.step(w).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def _motion_window(rng, mse=(0.045, 0.5)):
    """Reviewer cases: a person, or a 5-40 px low-contrast object, moving on a quiet wall. The
    MSE sits between the resting value and the absolute cap; motion only raises the ratio."""
    return make_window(visual=dict(repeated_hash_ratio=float(rng.uniform(0.0, 1.0)),
                                   exact_repeat_ratio=0.0,
                                   temporal_mse_p50=float(rng.uniform(*mse)),
                                   noise_ratio_p50=float(rng.uniform(1.0, 6.0)),
                                   temporal_sigma_p50=float(rng.uniform(0.7, 4.0))))


@pytest.mark.parametrize("motion_windows", [30, 300])
def test_motion_then_rest_never_confirms_freeze(cfg, motion_windows):
    """Motion of any size or duration before the scene rests cannot contaminate anything: the
    freeze verdict has no learned history (ADR-005)."""
    t = _tracker(cfg)
    rng = np.random.default_rng(2)
    for _ in range(motion_windows):
        assert t.step(_motion_window(rng)).incident is None
    for _ in range(300):
        assert t.step(_still_window(rng, float(rng.uniform(0.7, 1.9)))).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def test_alternating_low_contrast_motion_and_rest_never_confirms_freeze(cfg):
    t = _tracker(cfg)
    rng = np.random.default_rng(3)
    for cycle in range(40):
        for _ in range(10):
            w = _motion_window(rng) if cycle % 2 else _still_window(rng, 1.2)
            assert t.step(w).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def test_frozen_stream_is_confirmed_after_motion_and_live_windows_clear_the_rule(cfg):
    """A freeze right after a long motion period is caught (no stale floor to wait for); once
    the stream is live again the rule stops firing at once (CONFIRMED itself is left through the
    planner, not by the tracker)."""
    t = _tracker(cfg)
    rng = np.random.default_rng(4)
    for _ in range(300):
        t.step(_motion_window(rng))
    incidents = [t.step(_frozen_window()).incident for _ in range(5)]
    assert any(i is not None and FaultType.FREEZE in i.candidate_faults for i in incidents)
    assert t.fsm.state is IncidentState.CONFIRMED
    for _ in range(5):
        faults, _ = classify_window(_still_window(rng, 1.0), t.baseline, cfg["faults"])
        assert FaultType.FREEZE not in faults


def test_gain_drop_is_not_freeze(cfg):
    """AGC or dimmer light shrinks the sensor noise 10x: nothing to learn, nothing to trip."""
    t = _tracker(cfg)
    rng = np.random.default_rng(5)
    for _ in range(100):
        assert t.step(_still_window(rng, 1.0, mse=(0.3, 0.5))).incident is None
    for _ in range(100):
        assert t.step(_still_window(rng, 1.0, mse=(0.03, 0.05))).incident is None
    assert t.fsm.state is IncidentState.HEALTHY


def test_fine_grain_or_denoised_texture_is_not_freeze(cfg):
    """Fabric or grain under a live camera inflates the spatial sigma (ratio 0.17), an ISP
    temporal denoiser pushes the temporal sigma under half a count (0.07-0.4): reviewer cases
    that an absolute cap on the temporal noise turned into false freezes. Neither is bit-exact,
    so neither is a freeze now."""
    t = _tracker(cfg)
    for ratio, sigma_t in ((0.17, 1.0), (0.19, 0.07), (0.1, 0.4), (0.02, 0.1)):
        w = make_window(visual=dict(repeated_hash_ratio=1.0, exact_repeat_ratio=0.0,
                                    temporal_mse_p50=0.1, noise_ratio_p50=ratio,
                                    temporal_sigma_p50=sigma_t))
        for _ in range(100):
            assert t.step(w).incident is None
    assert t.fsm.state is IncidentState.HEALTHY
