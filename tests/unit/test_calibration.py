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


def test_a_fault_during_calibration_restarts_it_and_drops_the_earlier_windows(
        cfg, window, need):
    cam, rng = Cam(cfg), np.random.default_rng(1)
    for _ in range(need - 2):
        cam.feed(healthy(window, rng, brightness=150.0))     # windows next to a fault
    cam.feed(window(visual=DARK))
    [ev] = cam.events("calibration_restarted")
    assert ev["payload"] == {"discarded_samples": need - 2, "faults": ["blackout"]}
    assert cam.agent.tracker.baseline.updates == 0
    while cam.agent.state is not S.HEALTHY:
        cam.feed(healthy(window, rng))
    while not cam.agent.tracker.baseline.ready:
        cam.feed(healthy(window, rng))
    [cal] = cam.events("baseline_calibrated")
    assert cal["payload"]["samples"] == need
    assert abs(cam.agent.tracker.baseline.median("visual.brightness_p50") - 110.0) < 2.0
    assert cam.events("plan") == []


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
    """Short fault bursts (below enter_windows) at random times: calibration completes only
    after ``min_samples`` consecutive clean HEALTHY windows, and only once."""
    cam, rng = Cam(cfg), np.random.default_rng(100 + seed)
    burst_max = cfg["fusion"]["enter_windows"] - 1
    clean_run = 0
    for _ in range(400):
        if (cam.agent.state is S.HEALTHY and not cam.agent.tracker.baseline.ready
                and rng.random() < 0.06):
            for _ in range(int(rng.integers(1, burst_max + 1))):
                cam.feed(window(visual=DARK))
            clean_run = 0
            continue
        before = cam.agent.state
        cam.feed(healthy(window, rng))
        clean_run = clean_run + 1 if before is S.HEALTHY else 0
        if cam.events("baseline_calibrated"):
            assert clean_run >= need
            break
    assert len(cam.events("baseline_calibrated")) <= 1
    assert cam.events("plan") == []
