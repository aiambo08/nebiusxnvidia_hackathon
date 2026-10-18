"""F7 regression: oversized plan numbers are rejected without escaping the agent."""

from __future__ import annotations

import json

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import (
    FaultType,
    IncidentState,
    NemotronPlan,
    TokenUsage,
)
from reliability_agent.nemotron.planner import PlanOutcome
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.storage import EventStore


class JsonPlanPlanner:
    name = "json-plan"

    def __init__(self, plan: NemotronPlan):
        self._plan = plan
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        return PlanOutcome(self._plan, TokenUsage(model=self.name), "fake")


def _settings_bytes(device: SyntheticSource) -> bytes:
    return json.dumps(
        device.get_settings(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def test_huge_numeric_plan_is_rejected_without_stopping_agent(cfg, window):
    huge_integer = "9" * 400
    plan_json = (
        '{"diagnosis":"blackout","confidence":0.9,'
        '"action":{"name":"set_exposure_bounded","arguments":{"delta_ev":'
        + huge_integer
        + "}}}"
    )
    plan = NemotronPlan.model_validate_json(plan_json)
    assert isinstance(plan.action.arguments["delta_ev"], int)
    assert len(str(plan.action.arguments["delta_ev"])) == 400

    planner = JsonPlanPlanner(plan)
    device = SyntheticSource(width=160, height=120)
    device.open()
    before = _settings_bytes(device)
    store = EventStore()
    agent = None

    try:
        agent = ReliabilityAgent(cfg, device, planner, store)
        for _ in range(cfg["baseline"]["min_samples"] + 2):
            agent.on_window(window())
        for _ in range(cfg["fusion"]["enter_windows"]):
            agent.on_window(
                window(visual={"brightness_p50": 5.0, "black_pixel_ratio": 0.95})
            )

        policy = store.events(kind="policy")
        assert len(policy) == 1
        assert policy[0]["payload"]["approved"] is False
        assert "delta_ev must be finite" in policy[0]["payload"]["reasons"]
        transitions = [
            event["payload"]["to"]
            for event in store.events(kind="state")
            if "to" in event["payload"]
        ]
        assert transitions[-2:] == ["REJECTED", "NEEDS_HUMAN"]
        assert agent.state is IncidentState.NEEDS_HUMAN
        assert planner.calls == 1
        assert store.events(kind="execution") == []
        assert _settings_bytes(device) == before
        assert store.verify_chain()
        assert FaultType.BLACKOUT.value == store.events(kind="incident")[0][
            "payload"
        ]["candidate_faults"][0]
    finally:
        if agent is not None:
            agent.release_lease()
        store.close()
        device.close()
