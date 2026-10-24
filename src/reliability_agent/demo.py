"""Deterministic offline scenarios on the SyntheticSource (no network, no credits).

Used by `scripts/demo_offline.py`, the CLI and the e2e tests. The UI/video must label these
runs as SIMULATION; the real-hardware demo uses the webcam path.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
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
from reliability_agent.tasks.marker import MarkerTask

# scenario -> (synthetic fault, strength, human_fix_after_windows or None)
SCENARIOS: dict[str, tuple[str, float, int | None]] = {
    "dark": ("dark", 0.99, None),
    "defocus": ("defocus", 1.0, None),
    "freeze": ("freeze", 1.0, None),
    "occlusion": ("occlude", 1.0, 6),
    "overexposure": ("overexpose", 1.0, None),
    "bad_action": ("dark", 0.99, 8),   # scripted planner proposes the WRONG action -> rollback
    "frozen_black": ("freeze", 1.0, None),  # decoder froze on a black frame -> restart_capture
}


def scenario_planner_source(name: str) -> str | None:
    return "scripted" if name == "bad_action" else None


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
                 seed: int = 0, fault_strength: float | None = None, on_window=None,
                 on_frame: Callable[[Any], None] | None = None,
                 on_source: Callable[[Any], None] | None = None,
                 pace_s: float = 0.0, stop_event: Event | None = None) -> ScenarioResult:
    if pace_s < 0:
        raise ValueError("pace_s must be >= 0")
    cfg = cfg or demo_config()
    fault, strength, human_fix = SCENARIOS[name]
    if fault_strength is not None:
        strength = fault_strength
    t = [0.0]

    def clock() -> float:
        return t[0]

    fps = cfg["camera"]["analytic_fps"]
    src = SyntheticSource(width=320, height=240, seed=seed, clock=clock)
    if on_source:
        on_source(src)
    src.open()

    def read_frame():
        frame = src.read()
        if on_frame:
            on_frame(frame.image)
        if pace_s > 0:
            time.sleep(pace_s / fps)
        return frame

    def restart() -> None:  # simulated decoder reconnect clears a frozen pipeline
        if src.fault in ("freeze", "disconnect"):
            src.set_fault(None)

    if scenario_planner_source(name) is not None:
        planner = WrongActionPlanner()
    owns_store = store is None
    store = store if store is not None else EventStore()
    existing_events = store.events()
    scenario_start_seq = existing_events[-1]["seq"] if existing_events else 0
    agent = ReliabilityAgent(cfg, src, planner or RuleBasedPlanner(), store,
                             restart_cb=restart, clock=clock)
    runner = ProbeRunner(cfg, task=MarkerTask(timer=clock))
    meter = TransportMeter()
    meter.connected = True
    res = ScenarioResult(name)

    def one_window() -> bool:
        agg = WindowAggregator(cfg["camera"]["id"], cfg["window"]["seconds"])
        for _ in range(fps):
            if stop_event and stop_event.is_set():
                return False
            t[0] += 1.0 / fps
            f = read_frame()
            meter.on_frame(f, processed_at=t[0] + 0.02)
            agg.add(runner.analyse(f))
        tw = agg.emit(meter.snapshot(t=t[0] + 0.02), runner._geom_quality)
        st = agent.on_window(tw)
        res.states.append(str(st))
        if on_window:
            on_window(tw, agent)
        return True

    try:
        runner.calibrate_reference(read_frame())
        for _ in range(warmup):
            if not one_window():
                break
        if not (stop_event and stop_event.is_set()):
            if name == "frozen_black":  # render one black frame for the freeze to repeat
                src.set_fault("dark", 0.99)
                read_frame()
            src.set_fault(fault, strength)
            in_human = 0
            for _ in range(fault_windows):
                if not one_window():
                    break
                if agent.state is IncidentState.NEEDS_HUMAN:
                    in_human += 1
                    if human_fix is not None and in_human >= human_fix:
                        src.set_fault(None)  # the human cleaned the lens / fixed the lights
                        src.settings.update({"focus_ok": True})
                closed_since_start = any(
                    event["seq"] > scenario_start_seq
                    for event in store.events(kind="closed")
                )
                if agent.state is IncidentState.HEALTHY and closed_since_start:
                    break
        for _ in range(4):
            if not one_window():
                break
        res.events = store.events()
        res.final_state = str(agent.state)
        return res
    finally:
        agent.checkpoint()
        agent.release_lease()
        src.close()
        if owns_store:
            store.close()
