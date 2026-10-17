"""Frozen black pipelines must not receive unverifiable image-setting actions."""

from dataclasses import replace

from reliability_agent.capture.base import SourceCapabilities
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    NemotronPlan,
    PlanAction,
    TokenUsage,
)
from reliability_agent.demo import run_scenario
from reliability_agent.nemotron.planner import PlanOutcome, RuleBasedPlanner


def _disable_restart(monkeypatch):
    original_capabilities = SyntheticSource.capabilities

    def capabilities_without_restart(source) -> SourceCapabilities:
        return replace(original_capabilities(source), restartable=False)

    monkeypatch.setattr(SyntheticSource, "capabilities", capabilities_without_restart)


def _events(res, kind):
    return [event for event in res.events if event["kind"] == kind]


class SpyPlanner:
    name = "spy-rules"

    def __init__(self):
        self.calls = 0
        self.planner = RuleBasedPlanner()

    def plan(self, incident):
        self.calls += 1
        return self.planner.plan(incident)


class ExposurePlanner:
    name = "scripted-exposure"

    def plan(self, incident):
        return PlanOutcome(
            NemotronPlan(
                diagnosis=FaultType.BLACKOUT,
                confidence=0.9,
                action=PlanAction(
                    name=ActionName.SET_EXPOSURE_BOUNDED,
                    arguments={"delta_ev": 2.0},
                ),
                human_message="(scripted) increase exposure",
            ),
            TokenUsage(model="scripted"),
            "scripted",
        )


def test_frozen_black_without_restart_offers_no_image_setting_actions(monkeypatch):
    _disable_restart(monkeypatch)
    planner = SpyPlanner()

    res = run_scenario("frozen_black", planner=planner)

    incidents = _events(res, "incident")
    assert len(incidents) == 1
    allowed = {str(action) for action in incidents[0]["payload"]["allowed_actions"]}
    assert not allowed.intersection({
        "set_exposure_bounded",
        "trigger_autofocus",
        "restart_capture",
    })
    assert planner.calls == 1
    assert not _events(res, "execution")
    assert "NEEDS_HUMAN" in res.states


def test_frozen_black_without_restart_rejects_scripted_exposure(monkeypatch):
    _disable_restart(monkeypatch)

    res = run_scenario("frozen_black", planner=ExposurePlanner())

    assert any(event["payload"]["approved"] is False for event in _events(res, "policy"))
    assert not _events(res, "execution")
    assert "NEEDS_HUMAN" in res.states
