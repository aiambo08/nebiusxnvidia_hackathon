"""F5: FSM, hysteresis counters, cooldowns, gate history and baseline survive a restart."""

import copy

import numpy as np
import pytest

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import ActionName, FaultType, IncidentState
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import STATE_KEY, ReliabilityAgent
from reliability_agent.storage import EventStore

S = IncidentState
DARK = {"brightness_p50": 5.0, "black_pixel_ratio": 0.95}


class CountingPlanner:
    def __init__(self):
        self.inner = RuleBasedPlanner()
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        return self.inner.plan(incident)


class BrokenDevice(SyntheticSource):
    broken = False

    def apply_settings(self, settings):
        if self.broken:
            raise OSError("device unplugged")
        super().apply_settings(settings)


class Rig:
    """One camera, one store, agents that can be 'restarted' against them."""

    def __init__(self, cfg, store=None, device=None):
        self.cfg, self.store = cfg, store or EventStore()
        self.device = device or SyntheticSource(width=64, height=48)
        self.t, self.wall = [0.0], [1_000_000.0]
        self.planner = CountingPlanner()
        self.agent = self.start()

    def start(self, cfg=None):
        self.planner = CountingPlanner()
        self.agent = ReliabilityAgent(cfg or self.cfg, self.device, self.planner, self.store,
                                      clock=lambda: self.t[0], wall_clock=lambda: self.wall[0])
        return self.agent

    def feed(self, tw, dt=1.0):
        self.t[0] += dt
        self.wall[0] += dt
        return self.agent.on_window(tw)


def healthy(window, rng):
    return window(visual={"brightness_p50": 110.0 + float(rng.normal(0, 1.0)),
                          "blur_effect_p50": 0.25 + float(rng.normal(0, 0.005))})


def warm(rig, window, n=25, seed=0):
    rng = np.random.default_rng(seed)
    for _ in range(n):
        rig.feed(healthy(window, rng))
    assert rig.agent.tracker.baseline.ready


def kinds(store):
    return [e["kind"] for e in store.events()]


def test_empty_store_starts_fresh_without_events(cfg):
    rig = Rig(cfg)
    assert rig.agent.state is S.HEALTHY and rig.store.events() == []


@pytest.mark.parametrize("seed", range(6))
def test_clean_restarts_continue_exactly_like_an_uninterrupted_agent(cfg, window, seed):
    rng = np.random.default_rng(seed)
    seq = []
    while len(seq) < 90:  # healthy jitter with 1-2 window glitches: HEALTHY <-> SUSPECT flapping
        seq += [healthy(window, rng) for _ in range(int(rng.integers(1, 6)))]
        seq += [window(visual=DARK) for _ in range(int(rng.integers(1, 3)))]
    ref = Rig(cfg)
    ref_states = [str(ref.feed(tw)) for tw in seq]
    # an open incident escalates on restart by design; restart only between incidents
    can = [i for i in range(5, len(seq)) if ref_states[i - 1] in ("HEALTHY", "SUSPECT")]
    restarts = set(rng.choice(can, size=3, replace=False).tolist())

    rig = Rig(cfg)
    states = []
    for i, tw in enumerate(seq):
        if i in restarts:
            rig.agent.checkpoint()
            rig.start()
        states.append(str(rig.feed(tw)))
    assert states == ref_states
    assert "SUSPECT" in states
    assert rig.agent.tracker.baseline.version == ref.agent.tracker.baseline.version
    assert rig.agent.tracker.baseline.to_dict() == ref.agent.tracker.baseline.to_dict()
    assert kinds(rig.store).count("restore") == 3


def test_suspect_counters_survive_a_restart(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    for _ in range(cfg["fusion"]["enter_windows"] - 1):
        assert rig.feed(window(visual=DARK)) is S.SUSPECT
    rig.start()  # no explicit checkpoint: as after a crash
    assert rig.agent.state is S.SUSPECT
    rig.feed(window(visual=DARK))
    assert rig.store.events(kind="incident"), "the third bad window confirms after the restart"


def test_without_restore_the_counters_are_lost(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    for _ in range(cfg["fusion"]["enter_windows"] - 1):
        rig.feed(window(visual=DARK))
    no_restore = copy.deepcopy(cfg)
    no_restore["storage"]["restore_on_start"] = False
    rig.start(no_restore)
    assert rig.agent.state is S.HEALTHY and not rig.agent.tracker.baseline.ready


def drive_to_verifying(rig, window):
    warm(rig, window)
    for _ in range(cfg_enter(rig)):
        st = rig.feed(window(visual=DARK))
    assert st is S.VERIFYING, rig.store.events(kind="state")[-3:]
    assert rig.device.settings["exposure"] != 0.0
    assert rig.store.pending_snapshots()


def cfg_enter(rig):
    return rig.cfg["fusion"]["enter_windows"]


def test_restart_while_verifying_rolls_back_and_escalates_without_a_new_plan(
        cfg, window, tmp_path):
    db = tmp_path / "agent.sqlite"
    rig = Rig(cfg, store=EventStore(db))
    drive_to_verifying(rig, window)
    incident_id = rig.store.events(kind="incident")[0]["incident_id"]
    version = rig.agent.tracker.baseline.version
    rig.store.close()
    rig.store = EventStore(db)  # the process is gone; only the SQLite file survives

    agent = rig.start()
    assert agent.state is S.NEEDS_HUMAN
    assert agent.active.incident.incident_id == incident_id
    assert rig.device.settings["exposure"] == 0.0, "pre-action snapshot restored"
    assert rig.store.pending_snapshots() == []
    assert agent.tracker.baseline.version == version
    restore = rig.store.events(kind="restore")[-1]["payload"]
    assert restore["restored"] and restore["state"] == "NEEDS_HUMAN"
    assert restore["rolled_back"][0]["ok"]
    assert ActionName.SET_EXPOSURE_BOUNDED.value in agent.gate.export_history()

    learned = agent.tracker.baseline.updates
    rng = np.random.default_rng(9)
    for _ in range(cfg["fusion"]["exit_windows"]):
        rig.feed(healthy(window, rng))
    assert agent.state is S.HEALTHY
    assert rig.planner.calls == 0, "no plan and no LLM call after a restart"
    assert agent.tracker.baseline.updates == learned
    assert rig.store.verify_chain()


def test_a_crash_between_checkpoints_still_rolls_back_the_action(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    for _ in range(cfg_enter(rig) - 1):
        rig.feed(window(visual=DARK))
    stale = rig.store.get_state(STATE_KEY)          # last checkpoint: SUSPECT
    assert stale["tracker"]["state"] == "SUSPECT"
    rig.feed(window(visual=DARK))
    assert rig.agent.state is S.VERIFYING
    rig.store.put_state(STATE_KEY, stale)           # the crash lost the newer checkpoint

    agent = rig.start()
    assert agent.state is S.NEEDS_HUMAN and agent.active is not None
    assert rig.device.settings["exposure"] == 0.0
    assert rig.store.pending_snapshots() == []
    assert rig.planner.calls == 0


def test_a_failed_restart_rollback_keeps_the_snapshot_for_the_next_start(cfg, window):
    rig = Rig(cfg, device=BrokenDevice(width=64, height=48))
    drive_to_verifying(rig, window)
    rig.device.broken = True
    agent = rig.start()
    assert agent.state is S.NEEDS_HUMAN
    assert len(rig.store.pending_snapshots()) == 1
    assert rig.store.events(kind="rollback")[-1]["payload"]["ok"] is False

    rig.device.broken = False
    rig.start()
    assert rig.store.pending_snapshots() == []
    assert rig.device.settings["exposure"] == 0.0


def test_restart_while_waiting_for_a_human_keeps_waiting(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    occluded = {"occluded_cell_ratio": 0.8}
    for _ in range(cfg_enter(rig)):
        rig.feed(window(visual=occluded))
    assert rig.agent.state is S.NEEDS_HUMAN  # occlusion opens a ticket
    agent = rig.start()
    assert agent.state is S.NEEDS_HUMAN and not rig.store.events(kind="rollback")
    rig.feed(window(visual=occluded))
    assert agent.state is S.NEEDS_HUMAN and rig.planner.calls == 0
    rng = np.random.default_rng(1)
    for _ in range(cfg["fusion"]["exit_windows"]):
        rig.feed(healthy(window, rng))
    assert agent.state is S.HEALTHY


@pytest.mark.parametrize("change", ["camera", "schema"])
def test_state_from_another_camera_or_schema_is_ignored(cfg, window, change):
    rig = Rig(cfg)
    warm(rig, window)
    other = copy.deepcopy(cfg)
    if change == "camera":
        other["camera"]["id"] = "another-cam"
    else:
        saved = rig.store.get_state(STATE_KEY)
        rig.store.put_state(STATE_KEY, {**saved, "schema": 999})
    agent = rig.start(other)
    assert agent.state is S.HEALTHY and not agent.tracker.baseline.ready
    assert rig.store.events(kind="restore")[-1]["payload"]["restored"] is False


@pytest.mark.parametrize(("down", "suppressed"), [(5.0, True), (30.0, False)])
def test_fault_cooldown_loses_the_downtime(cfg, window, down, suppressed):
    rig = Rig(cfg)
    warm(rig, window)
    rig.agent.tracker.suppress([FaultType.BLACKOUT], rig.t[0])  # 20 s cooldown
    rig.agent.checkpoint()
    rig.wall[0] += down
    agent = rig.start()
    rig.feed(window(visual=DARK))
    assert (agent.state is S.HEALTHY) is suppressed


@pytest.mark.parametrize(("down", "limited"), [(60.0, True), (3601.0, False)])
def test_hourly_action_limit_survives_a_restart(cfg, window, down, limited):
    rig = Rig(cfg)
    gate = rig.agent.gate
    for i in range(8):  # set_exposure_bounded: max 8 per hour
        gate.record_execution(ActionName.SET_EXPOSURE_BOUNDED, now=rig.t[0] - 600 + i * 30)
    rig.agent.checkpoint()
    rig.wall[0] += down
    rig.t[0] = -50.0  # a new process: the monotonic clock restarted elsewhere
    agent = rig.start()
    warm(rig, window)
    for _ in range(cfg_enter(rig)):
        rig.feed(window(visual=DARK))
    policy = rig.store.events(kind="policy")[-1]["payload"]
    assert policy["action"] == ActionName.SET_EXPOSURE_BOUNDED
    assert policy["approved"] is not limited
    assert ("hourly rate limit reached" in policy["reasons"]) is limited
    assert agent.state is (S.NEEDS_HUMAN if limited else S.VERIFYING)


def test_restored_baseline_takes_the_configured_window(cfg, window):
    rig = Rig(cfg)
    warm(rig, window, n=40)
    small = copy.deepcopy(cfg)
    small["baseline"]["window"] = 30
    agent = rig.start(small)
    b = agent.tracker.baseline
    assert b.window == 30 and b.count("visual.brightness_p50") == 30
    assert b.updates == 40


def test_gate_history_ignores_unknown_actions_and_merges():
    from reliability_agent.policy.gate import PolicyGate

    g = PolicyGate(clock=lambda: 100.0)
    g.record_execution(ActionName.RESTART_CAPTURE, now=90.0)
    g.import_history({"rm_rf": [1.0], "restart_capture": [50.0, 4000.0]}, now=100.0)
    assert g.export_history() == {"restart_capture": [50.0, 10.0]}


def test_a_monotonic_clock_below_zero_does_not_suppress_faults(cfg, window):
    from reliability_agent.incidents.fusion import IncidentTracker

    tr = IncidentTracker("cam", cfg["faults"])
    assert tr.step(window(visual=DARK), now_s=-100.0).faults
