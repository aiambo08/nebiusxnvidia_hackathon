"""F5: every MVP fault reaches CONFIRMED and a legitimate lighting change returns to HEALTHY
without calling the planner (SIMULATION: synthetic scene, production probe path and agent)."""

import pytest

from benchmarks.injectors.faults import apply_stream
from benchmarks.replay import EXPECTED, telemetry_windows
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.contracts.models import IncidentState, TokenUsage
from reliability_agent.nemotron.planner import PlanOutcome, needs_human_plan
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.storage import EventStore

MVP = ("dark", "gaussian_blur", "freeze", "occlude_opaque", "overexpose")
CALIB, FAULT, AFTER = 30, 12, 10  # windows


class CountingPlanner:
    """Stands in for Nemotron: records every call and escalates without an action."""

    name = "counting"

    def __init__(self):
        self.calls = []

    def plan(self, incident):
        self.calls.append(incident)
        return PlanOutcome(needs_human_plan(incident, "test planner: no action"),
                           TokenUsage(model="test"), "test")


def run(kind, strength, seed, *, end_window=CALIB + FAULT):
    cfg = load_config(env=False)
    afps = cfg["camera"]["analytic_fps"]
    per_window = round(afps * cfg["window"]["seconds"])
    total = CALIB + FAULT + AFTER
    src = SyntheticSource(width=320, height=240, seed=seed)
    src.open()
    frames = (src.read().image for _ in range(total * per_window))
    device = SyntheticSource(width=320, height=240, seed=seed)
    device.open()
    now = [0.0]
    planner, store = CountingPlanner(), EventStore()
    agent = ReliabilityAgent(cfg, device, planner, store, clock=lambda: now[0])
    states = []
    for t, tw in telemetry_windows(
            apply_stream(frames, kind, CALIB * per_window, end_window * per_window,
                         strength, seed), afps, cfg):
        now[0] = t
        states.append(agent.on_window(tw))
    assert len(states) == total
    return states, planner, store


def confirmed_windows(states):
    return [i for i, s in enumerate(states) if s is not IncidentState.HEALTHY
            and s is not IncidentState.SUSPECT]


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("kind", MVP)
def test_every_mvp_fault_reaches_confirmed_once_and_then_closes(kind, seed):
    states, planner, store = run(kind, 1.0, seed)
    kinds = [e["kind"] for e in store.events()]
    assert "baseline_calibrated" in kinds and "incident" in kinds, states
    assert kinds.index("baseline_calibrated") < kinds.index("incident")
    incidents = store.events(kind="incident")
    assert len(incidents) == 1 and len(planner.calls) == 1
    assert EXPECTED[kind] in planner.calls[0].candidate_faults
    hit = confirmed_windows(states)
    assert hit and CALIB <= hit[0] < CALIB + FAULT, states
    assert states[-1] is IncidentState.HEALTHY, "closes once the fault clears"


@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("strength", [0.5, 1.0])
@pytest.mark.parametrize("seed", [0, 1])
def test_a_lighting_change_returns_to_healthy_without_the_planner(seed, strength, persist):
    end = CALIB + FAULT + AFTER if persist else CALIB + FAULT
    states, planner, store = run("lighting_change", strength, seed, end_window=end)
    assert planner.calls == []
    assert store.events(kind="incident") == [] and confirmed_windows(states) == []
    assert states[-1] is IncidentState.HEALTHY


@pytest.mark.parametrize("kind", MVP)
def test_a_transient_shorter_than_enter_windows_goes_suspect_and_back_without_the_planner(kind):
    """The lighting change above never leaves HEALTHY; this covers the way back from SUSPECT.
    A freeze is first flagged in its third frozen window (observed, SIMULATION), so it needs one
    window more than the others to be seen and still stay below `enter_windows` flagged windows."""
    short = load_config(env=False)["fusion"]["enter_windows"] - 1 + (kind == "freeze")
    states, planner, store = run(kind, 1.0, 0, end_window=CALIB + short)
    assert IncidentState.SUSPECT in states[CALIB:CALIB + short + 1], states
    assert planner.calls == [] and store.events(kind="incident") == []
    assert confirmed_windows(states) == [] and states[-1] is IncidentState.HEALTHY
