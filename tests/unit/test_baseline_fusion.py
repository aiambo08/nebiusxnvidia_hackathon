import numpy as np
import pytest

from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.contracts.models import FaultType, IncidentState
from reliability_agent.incidents.fusion import IncidentTracker, classify_window
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
