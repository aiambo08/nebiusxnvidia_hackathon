import pytest

from reliability_agent.actions import Executor
from reliability_agent.capture import SyntheticSource
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    Incident,
    PlanAction,
    VerificationSpec,
    VerificationStatus,
)
from reliability_agent.policy import PolicyGate
from reliability_agent.verification import Verifier
from tests.conftest import make_window

A = ActionName
CAPS = ["exposure", "autofocus", "profiles", "restart"]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def incident(actions=None, caps=CAPS):
    gate = PolicyGate()
    return Incident(camera_id="cam", candidate_faults=[FaultType.BLACKOUT],
                    capabilities=caps, allowed_actions=actions or gate.allowed_for(caps))


def test_allowed_for_respects_capabilities():
    g = PolicyGate()
    assert A.SET_EXPOSURE_BOUNDED not in g.allowed_for(["restart"])
    assert A.NEEDS_HUMAN in g.allowed_for([])
    assert set(g.allowed_for(CAPS)) == set(A)


def test_valid_plan_approved_and_cooldown():
    clock = Clock()
    g = PolicyGate(clock=clock)
    inc = incident()
    act = PlanAction(name=A.SET_EXPOSURE_BOUNDED, arguments={"delta_ev": 1.0})
    d = g.evaluate(act, inc)
    assert d.approved and d.arguments == {"delta_ev": 1.0}
    g.record_execution(d.action)
    clock.t += 5
    assert not g.evaluate(act, inc).approved  # cooldown
    clock.t += 30
    assert g.evaluate(act, inc).approved


def test_ticket_actions_are_ticket_only():
    d = PolicyGate().evaluate(PlanAction(name=A.REQUEST_MANUAL_CLEANING), incident())
    assert d.approved and d.ticket_only


def test_action_not_offered_rejected():
    inc = incident(actions=[A.NEEDS_HUMAN])
    d = PolicyGate().evaluate(PlanAction(name=A.RESTART_CAPTURE), inc)
    assert not d.approved and "not offered" in d.reasons[0]


# ------------------------------------------------------------------ executor


class Sink:
    def __init__(self, device):
        self.device, self.calls = device, []

    def save_snapshot(self, execution_id, incident_id, action, snapshot):
        # snapshot must be persisted BEFORE the device changes
        assert self.device.get_settings() == snapshot
        self.calls.append((execution_id, action, dict(snapshot)))


@pytest.fixture
def dev():
    s = SyntheticSource(width=160, height=120)
    s.open()
    return s


def _approved(name, args=None):
    return PolicyGate().evaluate(PlanAction(name=name, arguments=args or {}), incident())


@pytest.mark.parametrize("name,args,key,value", [
    (A.SET_EXPOSURE_BOUNDED, {"delta_ev": 1.5}, "exposure", 1.5),
    (A.SWITCH_STREAM_PROFILE, {"profile": "sub"}, "profile", "sub"),
    (A.TRIGGER_AUTOFOCUS, {}, "focus_ok", True),
    (A.ENTER_SAFE_MODE, {}, "safe_mode", True),
])
def test_apply_and_exact_rollback(dev, name, args, key, value):
    dev.set_fault("defocus")
    before = dev.get_settings()
    sink = Sink(dev)
    ex = Executor(dev, sink)
    rec = ex.execute("inc-1", _approved(name, args))
    assert rec.status == "success" and dev.get_settings()[key] == value
    assert len(sink.calls) == 1
    assert ex.rollback(rec) and dev.get_settings() == before
    assert ex.rollback(rec) and dev.get_settings() == before  # idempotent


def test_same_plan_not_applied_twice(dev):
    ex = Executor(dev)
    d = _approved(A.SET_EXPOSURE_BOUNDED, {"delta_ev": 1.0})
    r1 = ex.execute("inc", d)
    r2 = ex.execute("inc", d)
    assert r1 is r2 and dev.get_settings()["exposure"] == 1.0


def test_exposure_clamped_to_range(dev):
    dev.apply_settings({"exposure": 1.8})
    Executor(dev).execute("inc", _approved(A.SET_EXPOSURE_BOUNDED, {"delta_ev": 2.0}))
    assert dev.get_settings()["exposure"] == 2.0


def test_restart_without_support_is_failure_not_success(dev):
    rec = Executor(dev, restart_cb=None).execute("inc", _approved(A.RESTART_CAPTURE))
    assert rec.status == "failed" and "not supported" in rec.error


def test_rejected_decision_never_touches_device(dev):
    before = dev.get_settings()
    d = PolicyGate().evaluate(PlanAction(name=A.SET_EXPOSURE_BOUNDED,
                                         arguments={"delta_ev": 9.0}), incident())
    rec = Executor(dev).execute("inc", d)
    assert rec.status == "rejected" and dev.get_settings() == before


def test_ticket_action_creates_ticket(dev):
    tickets = []
    rec = Executor(dev, ticket_cb=tickets.append).execute(
        "inc", _approved(A.REQUEST_MANUAL_CLEANING))
    assert rec.status == "ticket" and tickets[0]["action"] == "request_manual_cleaning"


# ------------------------------------------------------------------ verifier

SPEC = VerificationSpec()


def _w(success, fps=30.0, latency=5.0):
    return make_window(transport=dict(capture_fps=fps), task=dict(success_rate=success,
                                                                  latency_ms_p95=latency))


def test_commit_when_task_recovers():
    d = Verifier().decide([_w(0.0)], [_w(0.9), _w(1.0)], [set(), set()],
                          {FaultType.BLACKOUT}, SPEC, baseline_primary=1.0)
    assert d.status is VerificationStatus.COMMITTED, d.reasons


def test_rollback_when_no_improvement():
    d = Verifier().decide([_w(0.5)], [_w(0.5), _w(0.5)], [set(), set()],
                          {FaultType.BLACKOUT}, SPEC, baseline_primary=1.0)
    assert d.status is VerificationStatus.ROLLED_BACK


def test_rollback_when_guard_regresses():
    d = Verifier().decide([_w(0.2)], [_w(1.0, fps=10), _w(1.0, fps=10)], [set(), set()],
                          {FaultType.BLACKOUT}, SPEC, baseline_primary=1.0)
    assert d.status is VerificationStatus.ROLLED_BACK
    assert any("guard" in r for r in d.reasons)


def test_rollback_when_fault_persists_or_new_fault():
    v = Verifier()
    d1 = v.decide([_w(0.0)], [_w(1.0), _w(1.0)], [set(), {FaultType.BLACKOUT}],
                  {FaultType.BLACKOUT}, SPEC)
    d2 = v.decide([_w(0.0)], [_w(1.0), _w(1.0)], [set(), {FaultType.FOCUS_DRIFT}],
                  {FaultType.BLACKOUT}, SPEC)
    assert d1.status is d2.status is VerificationStatus.ROLLED_BACK


def test_execution_failure_distinct_from_no_improvement():
    d = Verifier().decide([_w(0.0)], [], [], {FaultType.BLACKOUT}, SPEC, execution_ok=False)
    assert d.status is VerificationStatus.EXECUTION_FAILED
    d2 = Verifier().decide([_w(0.0)], [_w(1.0)], [set()], {FaultType.BLACKOUT}, SPEC)
    assert d2.status is VerificationStatus.INCONCLUSIVE
