"""F5: FSM, hysteresis counters, cooldowns, gate history and baseline survive a restart."""

import copy

import numpy as np
import pytest

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import ActionName, FaultType, IncidentState
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import (
    CameraInUseError,
    ReliabilityAgent,
    lease_key,
    state_key,
)
from reliability_agent.policy.gate import PolicyGate
from reliability_agent.storage import EventStore

S = IncidentState
DARK = {"brightness_p50": 5.0, "black_pixel_ratio": 0.95}

KEY = state_key("cam_01")


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
        """A new process after the previous one died (its lease has expired)."""
        self.store.delete_state(lease_key((cfg or self.cfg)["camera"]["id"]))
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
    stale = rig.store.get_state(KEY)          # last checkpoint: SUSPECT
    assert stale["tracker"]["state"] == "SUSPECT"
    rig.feed(window(visual=DARK))
    assert rig.agent.state is S.VERIFYING
    rig.store.put_state(KEY, stale)           # the crash lost the newer checkpoint

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
        # cam_01's checkpoint under the other camera's key (e.g. a copied DB)
        rig.store.put_state(state_key("another-cam"), rig.store.get_state(KEY))
    else:
        saved = rig.store.get_state(KEY)
        rig.store.put_state(KEY, {**saved, "schema": 999})
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


@pytest.mark.parametrize("bad", ["json", "tracker", "baseline", "list"])
def test_unreadable_or_malformed_state_starts_fresh(cfg, window, bad):
    rig = Rig(cfg)
    warm(rig, window)
    saved = rig.store.get_state(KEY)
    if bad == "json":
        rig.store._db.execute("UPDATE kv SET value='{not json' WHERE key=?", (KEY,))
        rig.store._db.commit()
    elif bad == "tracker":
        saved["tracker"]["state"] = "EXPLODED"
        rig.store.put_state(KEY, saved)
    elif bad == "baseline":
        del saved["tracker"]["baseline"]["data"]
        rig.store.put_state(KEY, saved)
    else:
        rig.store.put_state(KEY, [1, 2, 3])
    agent = rig.start()
    assert agent.state is S.HEALTHY and not agent.tracker.baseline.ready
    assert agent.tracker.baseline.updates == 0
    assert agent.gate.export_history() == {}
    assert rig.store.events(kind="restore")[-1]["payload"]["restored"] is False
    rig.feed(window(visual=DARK))
    assert agent.state is S.SUSPECT


def test_a_second_camera_on_the_same_db_leaves_the_first_cameras_action_alone(
        cfg, window, tmp_path):
    db = tmp_path / "agent.sqlite"
    a = Rig(cfg, store=EventStore(db))
    drive_to_verifying(a, window)                       # cam_01 crashes mid-action
    exposure_a = a.device.settings["exposure"]
    other = copy.deepcopy(cfg)
    other["camera"]["id"] = "phone_rtsp"
    dev_b = SyntheticSource(width=64, height=48)
    dev_b.apply_settings({"exposure": 1.5})
    b = Rig(other, store=EventStore(db), device=dev_b)
    warm(b, window, seed=3)
    assert b.agent.state is S.HEALTHY and b.agent.active is None
    assert dev_b.settings["exposure"] == 1.5
    assert len(a.store.pending_snapshots()) == 1
    assert a.device.settings["exposure"] == exposure_a
    a2 = a.start()                                      # cam_01 restarts: its own state
    assert a2.state is S.NEEDS_HUMAN and a.store.pending_snapshots() == []
    assert a.device.settings["exposure"] != exposure_a  # rolled back on its own device
    assert a2.tracker.baseline.ready


def test_a_second_restart_before_any_window_does_not_repeat_the_action(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    for _ in range(cfg_enter(rig) - 1):
        rig.feed(window(visual=DARK))
    stale = rig.store.get_state(KEY)                    # SUSPECT
    rig.feed(window(visual=DARK))
    assert rig.agent.state is S.VERIFYING
    rig.store.put_state(KEY, stale)                     # the crash lost the newer checkpoint
    calls = rig.planner.calls
    assert rig.start().state is S.NEEDS_HUMAN
    ag = rig.start()                                    # crash again before any window
    assert ag.state is S.NEEDS_HUMAN
    assert ActionName.SET_EXPOSURE_BOUNDED.value in ag.gate.export_history()
    rig.feed(window(visual=DARK))
    assert rig.planner.calls == 0 and calls == 1
    assert len(rig.store.events(kind="execution")) == 1


def test_a_crash_right_after_a_ticket_keeps_waiting_without_a_new_plan(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    occ = {"occluded_cell_ratio": 0.8}
    for _ in range(cfg_enter(rig) - 1):
        rig.feed(window(visual=occ))
    stale = rig.store.get_state(KEY)
    rig.feed(window(visual=occ))
    assert rig.agent.state is S.NEEDS_HUMAN
    rig.store.put_state(KEY, stale)
    assert rig.start().state is S.NEEDS_HUMAN
    rig.feed(window(visual=occ))
    assert rig.planner.calls == 0 and len(rig.store.events(kind="ticket")) == 1


def test_a_stale_checkpoint_does_not_reopen_a_closed_incident(cfg, window):
    rig = Rig(cfg)
    drive_to_verifying(rig, window)
    stale = rig.store.get_state(KEY)                    # VERIFYING
    rng = np.random.default_rng(2)
    while rig.agent.state is S.VERIFYING:
        rig.feed(healthy(window, rng))
    assert rig.agent.state is S.HEALTHY
    rig.store.put_state(KEY, stale)
    ag = rig.start()
    assert ag.state is S.HEALTHY and ag.active is None
    assert rig.store.events(kind="rollback") == []


def test_pending_snapshots_of_unknown_incidents_or_actions_do_not_crash_start(cfg, window):
    rig = Rig(cfg)
    drive_to_verifying(rig, window)
    inc = rig.store.events(kind="incident")[0]["incident_id"]
    rig.store.save_snapshot("x1", "no-such-incident", "rm_rf", {})
    rig.store.save_snapshot("x2", inc, "rm_rf", {})
    ag = rig.start()
    assert ag.state is S.NEEDS_HUMAN
    left = {p["execution_id"] for p in rig.store.pending_snapshots()}
    assert left == {"x1", "x2"}


def test_a_negative_saved_age_is_clamped_not_a_permanent_block():
    g = PolicyGate(clock=lambda: 10_000.0)
    g.import_history({"set_exposure_bounded": [-1e9]})
    assert g.export_history() == {"set_exposure_bounded": [0.0]}


def test_a_second_live_agent_with_the_same_camera_id_refuses_to_start(cfg, window, tmp_path):
    db = tmp_path / "agent.sqlite"
    a = Rig(cfg, store=EventStore(db))
    drive_to_verifying(a, window)                       # cam_01 alive, mid-action
    phone = SyntheticSource(width=64, height=48)
    phone.apply_settings({"exposure": 1.5})
    store_b = EventStore(db)
    with pytest.raises(CameraInUseError, match="RA_CAMERA_ID"):
        ReliabilityAgent(cfg, phone, CountingPlanner(), store_b,
                         clock=lambda: a.t[0], wall_clock=lambda: a.wall[0] + 3.0)
    assert phone.settings["exposure"] == 1.5
    assert len(a.store.pending_snapshots()) == 1
    a.feed(window())                                    # cam_01 carries on unharmed
    assert a.agent.state is S.VERIFYING


@pytest.mark.parametrize("gap, refused", [(59.0, True), (61.0, False)])
def test_a_crashed_agents_lease_expires(cfg, window, gap, refused):
    rig = Rig(cfg)
    warm(rig, window)
    rig.wall[0] += gap

    def start():
        return ReliabilityAgent(cfg, rig.device, CountingPlanner(), rig.store,
                                clock=lambda: rig.t[0], wall_clock=lambda: rig.wall[0])
    if refused:
        with pytest.raises(CameraInUseError):
            start()
    else:
        assert start().tracker.baseline.ready


def test_a_clean_shutdown_releases_the_lease_at_once(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    rig.agent.checkpoint()
    rig.agent.release_lease()
    again = ReliabilityAgent(cfg, rig.device, CountingPlanner(), rig.store,
                             clock=lambda: rig.t[0], wall_clock=lambda: rig.wall[0])
    assert again.tracker.baseline.ready
    rig.agent.release_lease()                           # not the owner any more: no-op
    assert rig.store.get_state(lease_key("cam_01"))["owner"] == again._owner


@pytest.mark.parametrize("bad", ["{not json", '{"owner": "x"}', '{"owner": "x", "heartbeat": "y"}'])
def test_an_unreadable_lease_does_not_block_start(cfg, bad):
    store = EventStore()
    store.put_state(lease_key("cam_01"), None)
    store._db.execute("UPDATE kv SET value=? WHERE key=?", (bad, lease_key("cam_01")))
    ReliabilityAgent(cfg, SyntheticSource(width=64, height=48), CountingPlanner(), store)


def test_camera_id_has_an_env_override(monkeypatch):
    from reliability_agent.config import load_config
    monkeypatch.setenv("RA_CAMERA_ID", "phone_rtsp")
    assert load_config()["camera"]["id"] == "phone_rtsp"


class SlowPlanner(CountingPlanner):
    """Valid but slow planner call; another agent tries to start while it runs."""

    def __init__(self, rig, intruder):
        super().__init__()
        self.rig, self.intruder = rig, intruder

    def plan(self, incident):
        self.rig.wall[0] += 25.0                         # longer than the old 10 s lease
        self.intruder()
        return super().plan(incident)


def test_a_slow_plan_keeps_the_lease_and_a_second_agent_is_refused(cfg, window, tmp_path):
    db = tmp_path / "agent.sqlite"
    a = Rig(cfg, store=EventStore(db))
    warm(a, window)
    phone = SyntheticSource(width=64, height=48)
    phone.apply_settings({"exposure": 1.5})
    refused = []

    def intruder():
        try:
            ReliabilityAgent(cfg, phone, CountingPlanner(), EventStore(db),
                             clock=lambda: a.t[0], wall_clock=lambda: a.wall[0])
        except CameraInUseError:
            refused.append(True)
    a.agent.planner = a.planner = SlowPlanner(a, intruder)
    for _ in range(cfg_enter(a)):
        a.feed(window(visual=DARK))
    assert refused == [True] and phone.settings["exposure"] == 1.5
    assert a.agent.state is S.VERIFYING


def test_an_agent_whose_lease_was_taken_over_stops_acting(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)
    rig.store.put_state(lease_key("cam_01"), {"owner": "other", "heartbeat": rig.wall[0]})
    saved = rig.store.get_state(KEY)
    for _ in range(cfg_enter(rig) + 3):
        rig.feed(window(visual=DARK))
    assert rig.agent.state is S.HEALTHY and rig.planner.calls == 0
    assert rig.store.events(kind="execution") == []
    assert len(rig.store.events(kind="lease_lost")) == 1
    assert rig.store.get_state(KEY) == saved             # the new owner's checkpoint is kept
    assert rig.store.get_state(lease_key("cam_01"))["owner"] == "other"


def test_a_lease_taken_over_during_planning_runs_no_action(cfg, window):
    rig = Rig(cfg)
    warm(rig, window)

    def steal():
        rig.store.put_state(lease_key("cam_01"), {"owner": "other", "heartbeat": rig.wall[0]})
    rig.agent.planner = rig.planner = SlowPlanner(rig, steal)
    for _ in range(cfg_enter(rig)):
        rig.feed(window(visual=DARK))
    assert rig.planner.calls == 1 and rig.agent.state is S.NEEDS_HUMAN
    assert rig.store.events(kind="execution") == [] and rig.store.pending_snapshots() == []


def test_a_lease_shorter_than_a_planner_call_is_a_config_error(cfg):
    bad = copy.deepcopy(cfg)
    bad.setdefault("storage", {})["lease_stale_s"] = 10
    with pytest.raises(ValueError, match="lease_stale_s"):
        ReliabilityAgent(bad, SyntheticSource(width=64, height=48), CountingPlanner(), EventStore())
