import pytest
from pydantic import ValidationError

from reliability_agent.config import load_config
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    IncidentState,
    NemotronPlan,
)
from reliability_agent.incidents.state_machine import (
    TRANSITIONS,
    IllegalTransition,
    IncidentStateMachine,
)


def test_plan_schema_roundtrip():
    plan = NemotronPlan.model_validate(
        {
            "diagnosis": "focus_drift",
            "confidence": 0.91,
            "evidence_refs": ["visual.blur_effect_p50"],
            "alternatives": ["motion_blur"],
            "action": {"name": "trigger_autofocus", "arguments": {}},
            "human_message": "Probable focus loss",
        }
    )
    assert plan.diagnosis is FaultType.FOCUS_DRIFT
    assert plan.action.name is ActionName.TRIGGER_AUTOFOCUS
    assert NemotronPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    "bad",
    [
        {"diagnosis": "aliens", "confidence": 0.5, "action": {"name": "enter_safe_mode"}},
        {"diagnosis": "freeze", "confidence": 1.5, "action": {"name": "enter_safe_mode"}},
        {"diagnosis": "freeze", "confidence": 0.5, "action": {"name": "rm_rf"}},
        {"diagnosis": "freeze", "confidence": 0.5, "action": {"name": "enter_safe_mode"}, "x": 1},
    ],
)
def test_plan_schema_rejects(bad):
    with pytest.raises(ValidationError):
        NemotronPlan.model_validate(bad)


def test_fsm_happy_path_and_illegal():
    fsm = IncidentStateMachine()
    for s in ["SUSPECT", "CONFIRMED", "DIAGNOSING", "PLANNED", "ACTING", "VERIFYING",
              "RECOVERED", "HEALTHY"]:
        fsm.to(IncidentState(s))
    assert fsm.state is IncidentState.HEALTHY
    with pytest.raises(IllegalTransition):
        fsm.to(IncidentState.ACTING)  # cannot act from HEALTHY


def test_fsm_llm_only_in_diagnosing_and_baseline_frozen():
    fsm = IncidentStateMachine()
    assert not fsm.llm_allowed and not fsm.baseline_frozen
    fsm.to(IncidentState.SUSPECT)
    assert fsm.baseline_frozen
    fsm.to(IncidentState.CONFIRMED)
    fsm.to(IncidentState.DIAGNOSING)
    assert fsm.llm_allowed


def test_every_state_has_entry():
    targets = {d for ds in TRANSITIONS.values() for d in ds}
    assert set(IncidentState) - {IncidentState.HEALTHY} <= targets


def test_config_loads_and_env_override(monkeypatch):
    monkeypatch.setenv("RA_BUDGET_HARD_CAP_USD", "26")
    cfg = load_config()
    assert cfg["budget"]["hard_cap_usd"] == 26
    assert cfg["budget"]["soft_cap_usd"] < cfg["budget"]["demo_cap_usd"] < 26 < 30
