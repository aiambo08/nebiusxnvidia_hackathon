"""Gate F7: >= 100 adversarial plans cannot bypass allowlist, ranges or cooldown."""

import math
import random

import pytest

from reliability_agent.contracts.models import ActionName, FaultType, Incident
from reliability_agent.nemotron.planner import _RULES
from reliability_agent.policy import PolicyGate
from reliability_agent.policy.gate import ALWAYS_OFFERED, FAULT_ACTIONS

CAPS = ["exposure", "autofocus", "profiles", "restart"]


def _incident(allowed=None):
    g = PolicyGate()
    return Incident(camera_id="cam", candidate_faults=[FaultType.FREEZE], capabilities=CAPS,
                    allowed_actions=allowed if allowed is not None else g.allowed_for(CAPS))


def adversarial_cases():
    rng = random.Random(1337)
    bad_names = ["rm -rf /", "exec", "shell", "set_exposure", "SET_EXPOSURE_BOUNDED ",
                 "firmware_update", "move_robot_arm", "", None, 42, "restart_capture; reboot",
                 "__import__('os')", "trigger_autofocus\n", "disable_policy_gate"]
    for n in bad_names:
        yield {"name": n, "arguments": {}}, "unknown"
    bad_values = [3.0, -3.0, 2.0001, 1e9, -1e9, float("nan"), float("inf"), -float("inf"),
                  "1.0", None, True, False, [1.0], {"v": 1}, "0; DROP TABLE"]
    for v in bad_values:
        yield {"name": "set_exposure_bounded", "arguments": {"delta_ev": v}}, "range"
    for p in ["MAIN", "hd", "../../etc", "sub ", "x" * 100, 1, None, True]:
        yield {"name": "switch_stream_profile", "arguments": {"profile": p}}, "choice"
    for extra in ["shell", "cmd", "callback", "__class__", "url", "exposure_raw"]:
        yield {"name": "trigger_autofocus", "arguments": {extra: "x"}}, "extra"
    yield {"name": "set_exposure_bounded", "arguments": {}}, "missing"
    yield {"name": "set_exposure_bounded", "arguments": "delta_ev=1"}, "type"
    # random garbage
    for _ in range(60):
        name = rng.choice([a.value for a in ActionName] + ["evil", "sudo"])
        args = {rng.choice(["delta_ev", "profile", "x", "cmd"]):
                rng.choice([99, -99, "sudo", float("nan"), [], {}, "sub", 0.5])
                for _ in range(rng.randint(1, 3))}
        yield {"name": name, "arguments": args}, "random"


CASES = list(adversarial_cases())
EXPECTED_FAULT_ACTIONS = {
    FaultType.STREAM_DOWN: (ActionName.RESTART_CAPTURE,),
    FaultType.FREEZE: (ActionName.RESTART_CAPTURE,),
    FaultType.BLACKOUT: (
        ActionName.SET_EXPOSURE_BOUNDED,
        ActionName.REQUEST_MANUAL_CLEANING,
    ),
    FaultType.OVEREXPOSURE: (ActionName.SET_EXPOSURE_BOUNDED,),
    FaultType.FOCUS_DRIFT: (
        ActionName.TRIGGER_AUTOFOCUS,
        ActionName.REQUEST_MANUAL_CLEANING,
    ),
    FaultType.LOW_FPS: (ActionName.SWITCH_STREAM_PROFILE,),
    FaultType.PIPELINE_SATURATION: (ActionName.SWITCH_STREAM_PROFILE,),
    FaultType.LENS_OCCLUSION: (ActionName.REQUEST_MANUAL_CLEANING,),
    FaultType.FOV_SHIFT: (ActionName.REQUEST_RECALIBRATION,),
    FaultType.MOTION_BLUR: (),
    FaultType.UNKNOWN: (),
}


def test_fault_actions_covers_every_fault_type_and_matches_the_offer_table():
    assert set(FAULT_ACTIONS) == set(FaultType)
    assert FAULT_ACTIONS == EXPECTED_FAULT_ACTIONS
    assert ALWAYS_OFFERED == (ActionName.ENTER_SAFE_MODE, ActionName.NEEDS_HUMAN)


@pytest.mark.parametrize(("fault", "expected"), EXPECTED_FAULT_ACTIONS.items())
def test_offered_for_each_fault_with_full_capabilities(fault, expected):
    gate = PolicyGate()
    offered = gate.offered_for(CAPS, [fault])
    expected_set = set(expected) | set(ALWAYS_OFFERED)
    assert set(offered) == expected_set
    assert offered == [name for name in gate.allowed_for(CAPS) if name in expected_set]


@pytest.mark.parametrize("missing", CAPS)
def test_offered_for_omits_actions_requiring_each_missing_capability(missing):
    gate = PolicyGate()
    capabilities = [cap for cap in CAPS if cap != missing]
    faults = list(FaultType)
    expected_relevant = {
        action
        for fault, actions in EXPECTED_FAULT_ACTIONS.items()
        for action in actions
    } | set(ALWAYS_OFFERED)
    expected = [
        name for name in gate.allowed_for(capabilities)
        if name in expected_relevant
    ]
    assert gate.offered_for(capabilities, faults) == expected


def test_offered_for_unions_multiple_fault_actions_in_registry_order():
    gate = PolicyGate()
    faults = [FaultType.BLACKOUT, FaultType.FOCUS_DRIFT]
    relevant = set(EXPECTED_FAULT_ACTIONS[FaultType.BLACKOUT]
                   + EXPECTED_FAULT_ACTIONS[FaultType.FOCUS_DRIFT]) | set(ALWAYS_OFFERED)
    assert gate.offered_for(CAPS, faults) == [
        name for name in gate.allowed_for(CAPS) if name in relevant
    ]


@pytest.mark.parametrize("faults", [[], [FaultType.UNKNOWN], [FaultType.MOTION_BLUR]])
def test_unknown_or_empty_faults_offer_only_always_offered(faults):
    assert PolicyGate().offered_for(CAPS, faults) == [
        ActionName.ENTER_SAFE_MODE,
        ActionName.NEEDS_HUMAN,
    ]


def test_overexposure_without_exposure_offers_only_escalation():
    assert PolicyGate().offered_for(
        ["autofocus", "profiles", "restart"], [FaultType.OVEREXPOSURE]
    ) == [ActionName.ENTER_SAFE_MODE, ActionName.NEEDS_HUMAN]


def test_every_planner_rule_action_is_offered_for_its_fault():
    for fault, action, _ in _RULES:
        assert action in FAULT_ACTIONS[fault]


def test_at_least_100_cases():
    assert len(CASES) >= 100


@pytest.mark.parametrize("plan,kind", CASES, ids=[f"{i}-{k}" for i, (_, k) in enumerate(CASES)])
def test_adversarial_plan(plan, kind):
    d = PolicyGate().evaluate(plan, _incident())
    if kind != "random":
        assert not d.approved, (plan, d)
        return
    # random cases may be valid by chance: then args must be exactly within spec
    if d.approved:
        for k, v in d.arguments.items():
            if k == "delta_ev":
                assert isinstance(v, float) and math.isfinite(v) and -2 <= v <= 2
            if k == "profile":
                assert v in ("main", "sub")


def test_not_offered_action_rejected_even_if_valid():
    inc = _incident(allowed=[ActionName.NEEDS_HUMAN])
    for name in ("restart_capture", "trigger_autofocus", "enter_safe_mode"):
        assert not PolicyGate().evaluate({"name": name, "arguments": {}}, inc).approved


def test_rate_limit_cannot_be_bypassed():
    t = [0.0]
    g = PolicyGate(clock=lambda: t[0])
    inc = _incident()
    approved = 0
    for _ in range(200):
        d = g.evaluate({"name": "restart_capture", "arguments": {}}, inc)
        if d.approved:
            approved += 1
            g.record_execution(d.action)
        t[0] += 16  # just above the 15 s cooldown, 200 tries within < 1 h
    assert approved == 12  # max_per_hour
