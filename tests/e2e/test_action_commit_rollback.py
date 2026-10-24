"""F8 full-loop action verification on simulated devices.

The test-only recovery effects model a stream profile restoring bandwidth and safe mode
selecting a healthy downstream path; production device behavior is unchanged.
"""

from __future__ import annotations

import pytest

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    IncidentState,
    NemotronPlan,
    PlanAction,
    TokenUsage,
)
from reliability_agent.nemotron.planner import PlanOutcome
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.storage import EventStore


class ScriptedPlanner:
    name = "scripted"

    def __init__(self, diagnosis, action, arguments):
        self.diagnosis = diagnosis
        self.action = action
        self.arguments = arguments
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        return PlanOutcome(
            NemotronPlan(
                diagnosis=self.diagnosis,
                confidence=0.9,
                action=PlanAction(name=self.action, arguments=self.arguments),
                human_message="F8 scripted action",
            ),
            TokenUsage(model="scripted"),
            "scripted",
        )


class RecoveryDevice(SyntheticSource):
    def __init__(self, *, effect, action):
        super().__init__(width=64, height=48)
        self.effect = effect
        self.action = action
        self.restarted = False

    def recovery_effect_applies(self):
        if not self.effect:
            return False
        if self.action is ActionName.SET_EXPOSURE_BOUNDED:
            return self.settings["exposure"] > 0
        if self.action is ActionName.TRIGGER_AUTOFOCUS:
            return self.settings["focus_ok"]
        if self.action is ActionName.SWITCH_STREAM_PROFILE:
            return self.settings["profile"] == "sub"
        if self.action is ActionName.ENTER_SAFE_MODE:
            return self.settings["safe_mode"]
        return self.restarted


CASES = (
    (ActionName.RESTART_CAPTURE, FaultType.FREEZE),
    (ActionName.SWITCH_STREAM_PROFILE, FaultType.LOW_FPS),
    (ActionName.SET_EXPOSURE_BOUNDED, FaultType.BLACKOUT),
    (ActionName.TRIGGER_AUTOFOCUS, FaultType.FOCUS_DRIFT),
    (ActionName.ENTER_SAFE_MODE, FaultType.BLACKOUT),
)
CASE_IDS = [action.value for action, _ in CASES]


def _fault_window(window, fault, device):
    if device.recovery_effect_applies():
        return window()
    if fault is FaultType.FREEZE:
        return window(visual={"exact_repeat_ratio": 1.0, "repeated_hash_ratio": 1.0,
                              "temporal_mse_p50": 0.0})
    if fault is FaultType.LOW_FPS:
        return window(transport={"capture_fps": 0.0, "frame_age_ms_p95": 1000.0})
    if fault is FaultType.BLACKOUT:
        return window(visual={"brightness_p50": 5.0, "black_pixel_ratio": 0.95})
    return window(visual={"blur_effect_p50": 1.0, "laplacian_variance_p50": 0.0})


def _action_args(action, effect):
    if action is ActionName.SWITCH_STREAM_PROFILE:
        return {"profile": "sub"}
    if action is ActionName.SET_EXPOSURE_BOUNDED:
        return {"delta_ev": 1.5 if effect else -1.5}
    return {}


def _run_case(cfg, window, action, fault, effect):
    device = RecoveryDevice(effect=effect, action=action)
    if fault is FaultType.FOCUS_DRIFT:
        device.apply_settings({"focus_ok": False})
    original_settings = device.get_settings()
    planner = ScriptedPlanner(fault, action, _action_args(action, effect))
    store = EventStore()
    agent = None

    def restart():
        device.restarted = True

    try:
        agent = ReliabilityAgent(cfg, device, planner, store, restart_cb=restart)
        for _ in range(cfg["baseline"]["min_samples"] + 2):
            agent.on_window(window())
        for _ in range(cfg["fusion"]["enter_windows"]):
            agent.on_window(_fault_window(window, fault, device))
        for _ in range(agent._verify_windows):
            if agent.state not in (IncidentState.VERIFYING,):
                break
            agent.on_window(_fault_window(window, fault, device))
        return device, original_settings, planner, store, agent
    except Exception:
        if agent is not None:
            agent.release_lease()
        store.close()
        raise


def _check_case(cfg, window, action, fault, effect):
    device, original_settings, planner, store, agent = _run_case(
        cfg, window, action, fault, effect
    )
    try:
        assert planner.calls == 1
        assert store.events(kind="policy")[-1]["payload"]["approved"] is True
        assert store.events(kind="execution")[-1]["payload"]["status"] == "success"
        if effect:
            assert store.events(kind="verification")[-1]["payload"]["status"] == "committed"
            assert store.events(kind="closed")[-1]["payload"]["reason"] == "recovered"
            assert agent.state is IncidentState.HEALTHY
            assert store.pending_snapshots() == []
        else:
            assert store.events(kind="verification")[-1]["payload"]["status"] == "rolled_back"
            rollback = store.events(kind="rollback")[-1]["payload"]
            assert rollback["ok"] is True
            assert device.get_settings() == original_settings
            transitions = [
                str(event["payload"]["to"]).lower().rsplit(".", 1)[-1]
                for event in store.events(kind="state")
            ]
            assert transitions[-2:] == ["rolled_back", "needs_human"]
            assert agent.state is IncidentState.NEEDS_HUMAN
            assert store.pending_snapshots() == []
        assert store.verify_chain()
    finally:
        try:
            agent.checkpoint()
        finally:
            try:
                agent.release_lease()
            finally:
                store.close()


class FailingApplyDevice(RecoveryDevice):
    def apply_settings(self, settings):
        if settings != self.get_settings():
            raise OSError("synthetic adapter apply failure")
        super().apply_settings(settings)


def _states(store):
    return [str(event["payload"]["to"]).lower().rsplit(".", 1)[-1]
            for event in store.events(kind="state")]


def test_execution_failure_and_no_improvement_leave_distinct_records(cfg, window):
    action, fault = ActionName.SET_EXPOSURE_BOUNDED, FaultType.BLACKOUT
    runs = {}
    for label, device_cls in (("failed", FailingApplyDevice), ("no_effect", RecoveryDevice)):
        device = device_cls(effect=False, action=action)
        original = device.get_settings()
        store = EventStore()
        agent = ReliabilityAgent(cfg, device, ScriptedPlanner(fault, action, {"delta_ev": 1.5}),
                                 store)
        try:
            for _ in range(cfg["baseline"]["min_samples"] + 2):
                agent.on_window(window())
            for _ in range(cfg["fusion"]["enter_windows"] + agent._verify_windows):
                agent.on_window(_fault_window(window, fault, device))
            runs[label] = {
                "execution": store.events(kind="execution")[-1]["payload"]["status"],
                "verifications": [e["payload"]["status"]
                                  for e in store.events(kind="verification")],
                "rollback_ok": store.events(kind="rollback")[-1]["payload"]["ok"],
                "states": _states(store),
                "final": agent.state,
                "restored": device.get_settings() == original,
                "chain": store.verify_chain(),
            }
        finally:
            agent.checkpoint()
            agent.release_lease()
            store.close()

    failed, no_effect = runs["failed"], runs["no_effect"]
    assert failed["execution"] != "success"
    assert failed["verifications"] == []
    assert "failed" in failed["states"] and "verifying" not in failed["states"]
    assert no_effect["execution"] == "success"
    assert no_effect["verifications"] == ["rolled_back"]
    assert "failed" not in no_effect["states"] and "verifying" in no_effect["states"]
    for run in (failed, no_effect):
        assert run["rollback_ok"] is True and run["restored"] and run["chain"]
        assert run["final"] is IncidentState.NEEDS_HUMAN


@pytest.mark.parametrize(("action", "fault"), CASES, ids=CASE_IDS)
def test_each_mvp_action_commits(cfg, window, action, fault):
    _check_case(cfg, window, action, fault, effect=True)


@pytest.mark.parametrize(("action", "fault"), CASES, ids=CASE_IDS)
def test_each_mvp_action_rolls_back_without_improvement(cfg, window, action, fault):
    _check_case(cfg, window, action, fault, effect=False)
