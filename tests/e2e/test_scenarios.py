"""End-to-end MAPE-K loop on the deterministic synthetic source (no network)."""

import pytest

from reliability_agent.demo import SCENARIOS, run_scenario
from reliability_agent.storage import EventStore


def kinds(res):
    return [e["kind"] for e in res.events]


def verification(res):
    return [e["payload"]["status"] for e in res.events if e["kind"] == "verification"]


@pytest.mark.parametrize("name", ["dark", "defocus", "freeze", "overexposure"])
@pytest.mark.parametrize("seed", [0, 1])
def test_recoverable_faults_are_committed(name, seed):
    res = run_scenario(name, seed=seed)
    assert verification(res) == ["committed"], res.transitions
    assert res.final_state == "HEALTHY"
    t = res.transitions
    assert t.index("CONFIRMED->DIAGNOSING") < t.index("PLANNED->ACTING") < t.index(
        "VERIFYING->RECOVERED")


def test_occlusion_opens_ticket_and_waits_for_human():
    res = run_scenario("occlusion")
    assert "ticket" in kinds(res) and "verification" not in kinds(res)
    assert "ACTING->NEEDS_HUMAN" in res.transitions
    assert res.transitions[-1] == "NEEDS_HUMAN->HEALTHY"


def test_harmful_action_is_rolled_back():
    store = EventStore()
    res = run_scenario("bad_action", store=store)
    assert verification(res) == ["rolled_back"]
    rb = [e for e in res.events if e["kind"] == "rollback"][0]["payload"]
    assert rb["ok"] and rb["restored"]["exposure"] == 0.0
    assert "ROLLED_BACK->NEEDS_HUMAN" in res.transitions
    assert store.pending_snapshots() == []
    assert store.verify_chain()


@pytest.mark.parametrize("name", ["dark", "freeze"])
def test_planner_called_once_and_only_after_confirmation(name):
    res = run_scenario(name)
    ev = res.events
    plans = [i for i, e in enumerate(ev) if e["kind"] == "plan"]
    assert len(plans) == 1  # one call per incident, none during warm-up
    confirmed = [i for i, e in enumerate(ev) if e["kind"] == "state"
                 and e["payload"]["to"] == "DIAGNOSING"]
    assert confirmed and confirmed[0] < plans[0]


def test_all_scenarios_registered():
    assert set(SCENARIOS) >= {"dark", "defocus", "freeze", "occlusion", "overexposure",
                              "bad_action"}
