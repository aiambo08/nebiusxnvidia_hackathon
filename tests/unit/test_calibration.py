"""F5: the baseline calibrates itself on clean windows only and logs its version (SIMULATION)."""

import numpy as np
import pytest

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import IncidentState
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import ReliabilityAgent, state_key
from reliability_agent.storage import EventStore

S = IncidentState
DARK = {"brightness_p50": 5.0, "black_pixel_ratio": 0.95}


class Cam:
    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store or EventStore()
        self.t, self.wall = [0.0], [1_000_000.0]
        self.agent = self.start()

    def start(self):
        return ReliabilityAgent(self.cfg, SyntheticSource(width=64, height=48),
                                RuleBasedPlanner(), self.store,
                                clock=lambda: self.t[0], wall_clock=lambda: self.wall[0])

    def feed(self, tw):
        self.t[0] += 1.0
        self.wall[0] += 1.0
        return self.agent.on_window(tw)

    def events(self, kind):
        return self.store.events(kind=kind)


def healthy(window, rng, brightness=110.0):
    return window(visual={"brightness_p50": brightness + float(rng.normal(0, 1.0)),
                          "blur_effect_p50": 0.25 + float(rng.normal(0, 0.005))})


@pytest.fixture
def need(cfg):
    return cfg["baseline"]["min_samples"]


def test_clean_start_calibrates_once_with_a_version_and_checkpoints_it(cfg, window, need):
    cam, rng = Cam(cfg), np.random.default_rng(0)
    for i in range(need - 1):
        cam.feed(healthy(window, rng))
    assert not cam.agent.tracker.baseline.ready and cam.events("baseline_calibrated") == []
    cam.feed(healthy(window, rng))
    b = cam.agent.tracker.baseline
    [ev] = cam.events("baseline_calibrated")
    assert ev["payload"] == {"baseline_version": b.version, "samples": need, "mode": b.mode}
    assert cam.store.get_state(state_key("cam_01"))["tracker"]["baseline"]["updates"] == need
    for _ in range(30):
        cam.feed(healthy(window, rng))
    assert len(cam.events("baseline_calibrated")) == 1


def test_a_visual_fault_during_calibration_drops_the_windows_just_before_it(
        cfg, window, need):
    cam, rng = Cam(cfg), np.random.default_rng(1)
    drop = cfg["baseline"]["calibration_discard"]
    for _ in range(need - 5):
        cam.feed(healthy(window, rng))
    for _ in range(drop):
        cam.feed(healthy(window, rng, brightness=150.0))     # already degrading
    cam.feed(window(visual=DARK))
    [ev] = cam.events("calibration_samples_discarded")
    assert ev["payload"] == {"discarded": drop, "faults": ["blackout"]}
    b = cam.agent.tracker.baseline
    assert b.updates == need - 5 and b.count("visual.brightness_p50") == need - 5
    while cam.agent.state is not S.HEALTHY:
        cam.feed(healthy(window, rng))
    while not cam.agent.tracker.baseline.ready:
        cam.feed(healthy(window, rng))
    [cal] = cam.events("baseline_calibrated")
    assert cal["payload"]["samples"] == need
    assert abs(cam.agent.tracker.baseline.median("visual.brightness_p50") - 110.0) < 2.0
    assert max(cam.agent.tracker.baseline._data["visual.brightness_p50"]) < 120.0
    assert cam.events("plan") == []


def test_a_transport_fault_during_calibration_keeps_the_clean_windows(cfg, window, need):
    cam, rng = Cam(cfg), np.random.default_rng(5)
    for _ in range(need - 2):
        cam.feed(healthy(window, rng))
    cam.feed(window(transport={"connected": False}))
    assert cam.agent.state is S.SUSPECT
    assert cam.events("calibration_samples_discarded") == []
    assert cam.agent.tracker.baseline.updates == need - 2


@pytest.mark.parametrize("fault", ["stream_down", "blackout"])
def test_an_intermittent_fault_still_calibrates_and_low_fps_stays_detectable(
        cfg, window, need, fault):
    """Reviewer C1: one faulty window in ten (a flaky RTSP phone) must not starve calibration,
    or LOW_FPS, which needs the baseline's FPS median, could never fire."""
    cam, rng = Cam(cfg), np.random.default_rng(6)
    bad = window(transport={"connected": False}) if fault == "stream_down" else window(visual=DARK)
    for i in range(300):
        cam.feed(bad if i % 10 == 9 else healthy(window, rng))
    assert cam.agent.tracker.baseline.ready
    assert len(cam.events("baseline_calibrated")) == 1
    while cam.agent.state is not S.HEALTHY:
        cam.feed(healthy(window, rng))
    for _ in range(cfg["fusion"]["enter_windows"]):
        cam.feed(window(transport={"capture_fps": 10.0}))
    [inc] = cam.events("incident")
    assert "low_fps" in inc["payload"]["candidate_faults"]


def test_a_fault_after_calibration_keeps_the_baseline(cfg, window, need):
    cam, rng = Cam(cfg), np.random.default_rng(2)
    for _ in range(need):
        cam.feed(healthy(window, rng))
    version = cam.agent.tracker.baseline.version
    cam.feed(window(visual=DARK))
    assert cam.agent.state is S.SUSPECT and cam.events("calibration_restarted") == []
    assert cam.agent.tracker.baseline.version == version


def test_a_restart_after_calibration_does_not_calibrate_again(cfg, window, need, tmp_path):
    db = tmp_path / "agent.sqlite"
    cam, rng = Cam(cfg, EventStore(db)), np.random.default_rng(3)
    for _ in range(need):
        cam.feed(healthy(window, rng))
    version = cam.agent.tracker.baseline.version
    cam.agent.release_lease()
    cam.agent = cam.start()
    assert cam.agent.tracker.baseline.version == version
    for _ in range(5):
        cam.feed(healthy(window, rng))
    assert len(cam.events("baseline_calibrated")) == 1


def test_the_same_windows_give_the_same_baseline_version(cfg, window, need):
    versions = []
    for _ in range(2):
        cam, rng = Cam(cfg), np.random.default_rng(4)
        for _ in range(need + 3):
            cam.feed(healthy(window, rng))
        versions.append(cam.events("baseline_calibrated")[0]["payload"]["baseline_version"])
    assert versions[0] == versions[1]


@pytest.mark.parametrize("seed", range(20))
def test_random_fault_bursts_never_leak_into_the_calibration(cfg, window, need, seed):
    """Short visual fault bursts (below enter_windows) at random times: calibration still
    completes, once, and holds none of the windows learned just before a fault."""
    cam, rng = Cam(cfg), np.random.default_rng(100 + seed)
    burst_max = cfg["fusion"]["enter_windows"] - 1
    drop = cfg["baseline"]["calibration_discard"]
    learned, tainted = [], set()
    for i in range(400):
        b = cam.agent.tracker.baseline
        if cam.agent.state is S.HEALTHY and not b.ready and rng.random() < 0.15:
            tainted.update(learned[-drop:])
            for _ in range(int(rng.integers(1, burst_max + 1))):
                cam.feed(window(visual=DARK))
            continue
        value = 110.0 + i * 1e-3                         # one distinct value per window
        before = b.updates
        cam.feed(window(visual={"brightness_p50": value,
                                "blur_effect_p50": 0.25 + float(rng.normal(0, 0.005))}))
        b = cam.agent.tracker.baseline
        if b.updates > before:
            learned.append(value)
        if b.ready:
            break
    assert len(cam.events("baseline_calibrated")) == 1, "never calibrated in 400 windows"
    data = list(cam.agent.tracker.baseline._data["visual.brightness_p50"])
    assert len(data) == need and not tainted & set(data)
    assert cam.events("plan") == []


def test_a_restored_baseline_reports_its_version_and_readiness(cfg, window, need, tmp_path):
    """Reviewer C2: a baseline that is already ready on restore (lower min_samples, or a DB from
    before calibration events) logs no baseline_calibrated; the restore event carries it."""
    db = tmp_path / "agent.sqlite"
    cam, rng = Cam(cfg, EventStore(db)), np.random.default_rng(7)
    for _ in range(need - 5):
        cam.feed(healthy(window, rng))
    cam.agent.checkpoint()
    cam.agent.release_lease()
    cam.cfg = {**cfg, "baseline": {**cfg["baseline"], "min_samples": need - 10}}
    cam.agent = cam.start()
    [restore] = cam.events("restore")
    assert restore["payload"]["baseline_ready"] is True
    assert restore["payload"]["baseline_version"] == cam.agent.tracker.baseline.version
