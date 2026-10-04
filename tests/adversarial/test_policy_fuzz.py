"""Gate F7: >= 100 adversarial plans cannot bypass allowlist, ranges or cooldown."""

import math
import random

import pytest

from reliability_agent.contracts.models import ActionName, FaultType, Incident
from reliability_agent.policy import PolicyGate

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
