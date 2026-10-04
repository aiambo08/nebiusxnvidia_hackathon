"""Deterministic offline scenarios on the SyntheticSource (no network, no credits).

Used by `scripts/demo_offline.py`, the CLI and the e2e tests. The UI/video must label these
runs as SIMULATION; the real-hardware demo uses the webcam path.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.capture.worker import TransportMeter
from reliability_agent.config import load_config
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    Incident,
    IncidentState,
    NemotronPlan,
    PlanAction,
    TokenUsage,
)
from reliability_agent.nemotron.planner import Planner, PlanOutcome, RuleBasedPlanner
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator
from reliability_agent.storage.event_store import EventStore

# scenario -> (synthetic fault, strength, human_fix_after_windows or None)
SCENARIOS: dict[str, tuple[str, float, int | None]] = {
    "dark": ("dark", 0.99, None),
    "defocus": ("defocus", 1.0, None),
    "freeze": ("freeze", 1.0, None),
    "occlusion": ("occlude", 1.0, 6),
    "overexposure": ("overexpose", 1.0, None),
    "bad_action": ("dark", 0.99, 8),   # scripted planner proposes the WRONG action -> rollback
}


class WrongActionPlanner:
    """Deliberately proposes a harmful (but policy-valid) action to prove rollback works."""

    name = "scripted-wrong"

    def plan(self, incident: Incident) -> PlanOutcome:
        return PlanOutcome(
            NemotronPlan(diagnosis=FaultType.BLACKOUT, confidence=0.9,
                         action=PlanAction(name=ActionName.SET_EXPOSURE_BOUNDED,
                                           arguments={"delta_ev": -1.5}),
                         human_message="(scripted) lower exposure"),
            TokenUsage(model="scripted"), "scripted")


@dataclass
class ScenarioResult:
    name: str
    states: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    final_state: str = ""

    @property
    def transitions(self) -> list[str]:
        return [f"{e['payload']['from']}->{e['payload']['to']}"
                for e in self.events if e["kind"] == "state"]


def demo_config() -> dict[str, Any]:
    cfg = copy.deepcopy(load_config(env=False))
    cfg["baseline"]["min_samples"] = 10
    cfg["verification"]["window_seconds"] = 3
    cfg["fusion"]["cooldown_s"] = 0
    return cfg


def run_scenario(name: str, planner: Planner | None = None, *, cfg: dict | None = None,
                 store: EventStore | None = None, warmup: int = 15, fault_windows: int = 20,
                 seed: int = 0, on_window=None) -> ScenarioResult:
    cfg = cfg or demo_config()
    fault, strength, human_fix = SCENARIOS[name]
    t = [0.0]

    def clock() -> float:
        return t[0]

    fps = cfg["camera"]["analytic_fps"]
    src = SyntheticSource(width=320, height=240, seed=seed, clock=clock)
    src.open()

    def restart() -> None:  # simulated decoder reconnect clears a frozen pipeline
        if src.fault in ("freeze", "disconnect"):
            src.set_fault(None)

    if name == "bad_action":
        planner = WrongActionPlanner()
    store = store or EventStore()
    agent = ReliabilityAgent(cfg, src, planner or RuleBasedPlanner(), store,
                             restart_cb=restart, clock=clock)
    runner = ProbeRunner(cfg)
    meter = TransportMeter()
    meter.connected = True
    res = ScenarioResult(name)

    def one_window() -> None:
        agg = WindowAggregator(cfg["camera"]["id"], cfg["window"]["seconds"])
        for _ in range(fps):
            t[0] += 1.0 / fps
            f = src.read()
            meter.on_frame(f, processed_at=t[0] + 0.02)
            agg.add(runner.analyse(f))
        tw = agg.emit(meter.snapshot(t=t[0] + 0.02), runner._geom_quality)
        st = agent.on_window(tw)
        res.states.append(str(st))
        if on_window:
            on_window(tw, agent)

    runner.calibrate_reference(src.read())
    for _ in range(warmup):
        one_window()
    src.set_fault(fault, strength)
    in_human = 0
    for _ in range(fault_windows):
        one_window()
        if agent.state is IncidentState.NEEDS_HUMAN:
            in_human += 1
            if human_fix is not None and in_human >= human_fix:
                src.set_fault(None)  # the human cleaned the lens / fixed the lights
                src.settings.update({"focus_ok": True})
        if agent.state is IncidentState.HEALTHY and store.events(kind="closed"):
            break
    for _ in range(4):
        one_window()
    res.events = store.events()
    res.final_state = str(agent.state)
    return res
