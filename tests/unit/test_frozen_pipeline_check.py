from copy import deepcopy

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    Incident,
    IncidentState,
)
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.storage import EventStore


class SpyPlanner(RuleBasedPlanner):
    def __init__(self):
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        return super().plan(incident)


def _agent(cfg):
    planner = SpyPlanner()
    store = EventStore()
    agent = ReliabilityAgent(
        cfg,
        SyntheticSource(width=64, height=48),
        planner,
        store,
        restart_cb=lambda: None,
        clock=lambda: 1000.0,
        wall_clock=lambda: 1_000_000.0,
    )
    agent.tracker.fsm.state = IncidentState.CONFIRMED
    return agent, planner, store


def _incident(cfg, tw):
    return Incident(
        camera_id=cfg["camera"]["id"],
        candidate_faults=[FaultType.BLACKOUT],
        telemetry=tw,
    )


def _with_visual(tw, **updates):
    return tw.model_copy(update={"visual": tw.visual.model_copy(update=updates)})


def _plan_action(store):
    event = store.events(kind="plan")[-1]
    return event["payload"]["plan"]["action"]["name"]


def test_exact_repeat_at_configured_minimum_uses_restart_without_planner(cfg, window):
    minimum = cfg["faults"]["freeze"]["exact_repeat_ratio_min"]
    tw = _with_visual(window(), exact_repeat_ratio=minimum)
    agent, planner, store = _agent(cfg)
    incident = _incident(cfg, tw)

    try:
        agent._handle_confirmed(incident)

        assert _plan_action(store) == ActionName.RESTART_CAPTURE.value
        assert ActionName.SET_EXPOSURE_BOUNDED not in incident.allowed_actions
        assert ActionName.TRIGGER_AUTOFOCUS not in incident.allowed_actions
        assert planner.calls == 0
    finally:
        agent.release_lease()


def test_exact_repeat_below_configured_minimum_uses_planner(cfg, window):
    minimum = cfg["faults"]["freeze"]["exact_repeat_ratio_min"]
    tw = _with_visual(window(), exact_repeat_ratio=minimum - 1e-6)
    agent, planner, store = _agent(cfg)
    incident = _incident(cfg, tw)

    try:
        agent._handle_confirmed(incident)

        assert planner.calls == 1
        assert ActionName.SET_EXPOSURE_BOUNDED in incident.allowed_actions
        assert _plan_action(store) == ActionName.SET_EXPOSURE_BOUNDED.value
    finally:
        agent.release_lease()


def test_repeated_hash_ratio_does_not_mark_pipeline_frozen(cfg, window):
    tw = _with_visual(window(), exact_repeat_ratio=0.0, repeated_hash_ratio=1.0)
    agent, planner, store = _agent(cfg)
    incident = _incident(cfg, tw)

    try:
        agent._handle_confirmed(incident)

        assert planner.calls == 1
        assert ActionName.SET_EXPOSURE_BOUNDED in incident.allowed_actions
        assert _plan_action(store) == ActionName.SET_EXPOSURE_BOUNDED.value
    finally:
        agent.release_lease()


def test_frozen_check_uses_configured_threshold(cfg, window):
    cfg = deepcopy(cfg)
    cfg["faults"]["freeze"]["exact_repeat_ratio_min"] = 0.6

    below = _with_visual(window(), exact_repeat_ratio=0.55)
    agent, planner, store = _agent(cfg)
    incident = _incident(cfg, below)
    try:
        agent._handle_confirmed(incident)
        assert planner.calls == 1
        assert ActionName.SET_EXPOSURE_BOUNDED in incident.allowed_actions
        assert _plan_action(store) == ActionName.SET_EXPOSURE_BOUNDED.value
    finally:
        agent.release_lease()

    above = _with_visual(window(), exact_repeat_ratio=0.65)
    agent, planner, store = _agent(cfg)
    incident = _incident(cfg, above)
    try:
        agent._handle_confirmed(incident)
        assert planner.calls == 0
        assert ActionName.SET_EXPOSURE_BOUNDED not in incident.allowed_actions
        assert _plan_action(store) == ActionName.RESTART_CAPTURE.value
    finally:
        agent.release_lease()
