"""Event-backed SIMULATION experiments and ablations for F10 PR2."""

from __future__ import annotations

import copy
import json
import subprocess
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from benchmarks.injectors.faults import apply_spatial
from benchmarks.recovery import (
    REGRESSION_ACTIONS,
    ScriptedPlanner,
    classify_events,
    classify_regression,
    regression_gate,
)
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.capture.worker import TransportMeter
from reliability_agent.config import api_key
from reliability_agent.contracts.models import (
    FaultType,
    IncidentState,
)
from reliability_agent.demo import SCENARIOS as DEMO_SCENARIOS
from reliability_agent.demo import (
    WrongActionPlanner,
    demo_config,
    run_scenario,
)
from reliability_agent.nemotron.budget import BudgetGuard
from reliability_agent.nemotron.planner import RuleBasedPlanner, make_planner
from reliability_agent.orchestrator import ReliabilityAgent
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator
from reliability_agent.storage import EventStore

FAULT_GRID: tuple[tuple[str, float | None], ...] = (
    ("dark", 0.99),
    ("defocus", 1.0),
    ("overexpose", 1.0),
    ("freeze", 1.0),
    ("occlusion", 1.0),
    ("frozen_black", None),
)
SEEDS = range(5)
CONTROLS = ("clean", "lighting_change")
SCENARIO_NAMES = {
    "clean": "dark",
    "lighting_change": "dark",
    "dark": "dark",
    "defocus": "defocus",
    "overexpose": "overexposure",
    "freeze": "freeze",
    "occlusion": "occlusion",
    "frozen_black": "frozen_black",
}
EXPECTED_FAULT = {
    "dark": "blackout",
    "defocus": "focus_drift",
    "overexpose": "overexposure",
    "freeze": "freeze",
    "occlusion": "lens_occlusion",
    "frozen_black": "blackout",
}
CLASSIFIER_FAULT = {
    "dark": "dark",
    "defocus": "defocus",
    "overexpose": "overexpose",
    "freeze": "frozen_black",
    "occlusion": "dark",
    "frozen_black": "frozen_black",
}
MVP_FAULTS = ("dark", "defocus", "overexpose", "freeze", "occlusion")
VERIFY_COMMITTED = "COMMITTED"


def _state_name(value: Any) -> str:
    return str(getattr(value, "value", value)).upper().rsplit(".", 1)[-1]


def _code_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True, encoding="utf-8"
    )
    if status.strip():
        raise RuntimeError("Run the F10 grid from a clean committed worktree.")
    return sha


def _scenario_for(fault: str) -> str:
    return SCENARIO_NAMES[fault]


def _grid_db(
    out_dir: Path, arm: str, run_id: str, phase: str = "recovery"
) -> Path:
    return out_dir / "db" / arm / phase / f"{run_id}.sqlite"


def _capture_source(source: SyntheticSource, state: dict[str, Any],
                    lighting_change: bool = False) -> None:
    state["source"] = source
    state["initial_settings"] = copy.deepcopy(source.get_settings())
    original_set_fault = source.set_fault
    original_read = source.read
    active = False

    def set_fault(fault: str | None, strength: float = 1.0) -> None:
        nonlocal active
        if fault is not None:
            active = active or lighting_change
        original_set_fault(fault, strength)
        if fault is not None and "fault_settings" not in state:
            state["fault_settings"] = copy.deepcopy(source.get_settings())

    def read():
        frame = original_read()
        if frame is not None and active:
            frame.image[...] = apply_spatial(
                frame.image, "lighting_change", 1.0
            )
        return frame

    source.set_fault = set_fault
    if lighting_change:
        source.read = read


def _append_run(store: EventStore, metadata: dict[str, Any]) -> None:
    store.append("experiment_run", metadata)


@contextmanager
def _no_downstream_verifier():
    import reliability_agent.orchestrator as orchestrator
    import reliability_agent.verification.verifier as verifier_module

    original_factory = orchestrator.Verifier.from_config

    class NoDownstreamVerifier:
        def __init__(self, delegate):
            self.delegate = delegate

        def decide(self, before, after, after_faults, original_faults, spec,
                   baseline_primary=None, execution_ok=True):
            faults = set(original_faults or ())
            primary_by_fault = (
                (FaultType.FREEZE, "visual.exact_repeat_ratio"),
                (FaultType.BLACKOUT, "visual.brightness_p50"),
                (FaultType.OVEREXPOSURE, "visual.brightness_p50"),
                (FaultType.FOCUS_DRIFT, "visual.blur_effect_p50"),
                (FaultType.LENS_OCCLUSION, "visual.occluded_cell_ratio"),
            )
            primary = next(
                (metric for fault, metric in primary_by_fault if fault in faults),
                "visual.brightness_p50",
            )
            adapted = spec.model_copy(update={
                "primary_metric": primary,
                "guard_metrics": [
                    metric for metric in spec.guard_metrics
                    if not metric.startswith("task.") and metric != primary
                ],
            })
            lower_is_better = set(verifier_module.LOWER_IS_BETTER)
            if FaultType.OVEREXPOSURE in faults and primary == "visual.brightness_p50":
                lower_is_better.add(primary)
            elif FaultType.BLACKOUT in faults:
                lower_is_better.discard(primary)
            with patch.object(
                verifier_module, "LOWER_IS_BETTER", frozenset(lower_is_better)
            ):
                return self.delegate.decide(
                    before, after, after_faults, original_faults, adapted,
                    baseline_primary, execution_ok,
                )

    def factory(cls, cfg):
        return NoDownstreamVerifier(original_factory(cfg))

    with patch.object(orchestrator.Verifier, "from_config", classmethod(factory)):
        yield


def _fixed_baseline_agent(baseline_data: dict[str, Any]):
    class FixedBaselineAgent(ReliabilityAgent):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from reliability_agent.baselines.robust import RobustBaseline

            baseline = RobustBaseline.from_dict(copy.deepcopy(baseline_data))
            baseline.update = lambda sample, frozen=False: False
            self.tracker.baseline = baseline

    return FixedBaselineAgent


class _NoCallPlanner:
    name = "planner-must-not-be-called"

    def __init__(self) -> None:
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        raise AssertionError("A1 detector-only arm invoked its planner")


class _DetectorOnlyAgent(ReliabilityAgent):
    def _handle_confirmed(self, incident) -> None:
        self.store.append("incident", incident, incident.incident_id)


class _StopAtState(Exception):
    pass


class _FailingCompletions:
    def create(self, **kwargs):
        raise TimeoutError("offline F10 fake Token Factory outage")


class _FailingSDK:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FailingCompletions()


class _ObservedOutagePlanner:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.client = delegate.client
        self.opened_after_threshold = False
        self.max_failures = 0

    def plan(self, incident):
        result = self.delegate.plan(incident)
        breaker = self.client.breaker
        opened = breaker.opened_at is not None or breaker.failures >= breaker.threshold
        self.opened_after_threshold |= opened
        self.max_failures = max(
            self.max_failures, breaker.failures,
            breaker.threshold if opened else 0,
        )
        return result


def _run_standard(
    out_dir: Path,
    code_revision: str,
    arm: str,
    fault: str,
    strength: float | None,
    seed: int,
    *,
    planner=None,
    auto_execute: bool = True,
    warmup: int = 15,
    fault_windows: int = 56,
    detector_only: bool = False,
    lighting_change: bool = False,
    baseline_data: dict[str, Any] | None = None,
    downstream_ablation: bool = False,
    scripted_black: bool = False,
    on_window=None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = f"{fault}-{strength if strength is not None else 'na'}-seed{seed}"
    phase = (extra_metadata or {}).get("phase", "recovery")
    path = _grid_db(out_dir, arm, run_id, phase)
    store = EventStore(path)
    source_state: dict[str, Any] = {}
    cfg = demo_config()
    cfg["planner"]["kind"] = "rules"
    cfg["planner"]["auto_execute"] = auto_execute
    effective_planner = planner or RuleBasedPlanner()
    scenario = _scenario_for(fault)
    def source_cb(source):
        _capture_source(source, source_state, lighting_change=lighting_change)

    patched_agent = None
    if detector_only:
        patched_agent = _DetectorOnlyAgent
    elif baseline_data is not None:
        patched_agent = _fixed_baseline_agent(baseline_data)
    metadata = {
        "arm": arm,
        "fault": fault,
        "strength": strength,
        "seed": seed,
        "scenario": scenario,
        "code_revision": code_revision,
        "initial_settings": {},
        "final_settings": {},
        "final_state": None,
        "run_id": run_id,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    try:
        with ExitStack() as stack:
            if patched_agent is not None:
                import reliability_agent.demo as demo_module

                stack.enter_context(patch.object(
                    demo_module, "ReliabilityAgent", patched_agent
                ))
            if downstream_ablation:
                stack.enter_context(_no_downstream_verifier())
            if scripted_black:
                import reliability_agent.orchestrator as orchestrator

                stack.enter_context(patch.object(
                    orchestrator.ReliabilityAgent, "_frozen", lambda self, incident: False
                ))
            result = run_scenario(
                scenario,
                planner=effective_planner,
                cfg=cfg,
                store=store,
                warmup=warmup,
                fault_windows=fault_windows,
                seed=seed,
                fault_strength=strength,
                on_window=on_window,
                on_source=source_cb,
            )
        metadata["initial_settings"] = source_state["initial_settings"]
        metadata["fault_settings"] = source_state.get(
            "fault_settings", source_state["initial_settings"]
        )
        metadata["final_settings"] = copy.deepcopy(
            source_state["source"].get_settings()
        )
        metadata["settings_unchanged"] = (
            metadata["fault_settings"] == metadata["final_settings"]
        )
        metadata["final_state"] = _state_name(result.final_state)
        if isinstance(effective_planner, _NoCallPlanner):
            metadata["planner_calls"] = effective_planner.calls
        events = store.events()
        if arm == "A1_local_detector_only":
            if isinstance(effective_planner, _NoCallPlanner) and effective_planner.calls:
                raise AssertionError("A1 must never call its planner")
            if any(event["kind"] == "execution" for event in events):
                raise AssertionError("A1 must not execute actions")
        if arm == "A2_detector_no_actions":
            if any(
                event["kind"] == "execution"
                and event["payload"].get("status") in ("success", "failed")
                for event in events
            ):
                raise AssertionError("A2 must not execute device actions")
            if not metadata["settings_unchanged"]:
                raise AssertionError("A2 must leave device settings unchanged")
            incident_ids = {
                event["incident_id"] for event in events
                if event["kind"] == "incident" and event["incident_id"]
            }
            planned_incidents = {
                event["incident_id"] for event in events
                if event["kind"] == "plan" and event["incident_id"]
            }
            if not incident_ids.issubset(planned_incidents):
                raise AssertionError("A2 must plan for each confirmed incident")
        _append_run(store, metadata)
    finally:
        store.close()
    return metadata


def _run_training_baseline(
    out_dir: Path, code_revision: str, seed: int, *, smoke: bool = False
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def save_baseline(_tw, agent):
        if agent.tracker.baseline.ready:
            captured["baseline"] = agent.tracker.baseline.to_dict()

    _run_standard(
        out_dir, code_revision, "A5_training", "clean", 0.0, seed,
        warmup=6 if smoke else 30, fault_windows=0, on_window=save_baseline,
        extra_metadata={"training_scene_seed": seed},
    )
    if "baseline" not in captured:
        raise RuntimeError("A5 training scene did not produce a ready baseline.")
    store = EventStore(_grid_db(out_dir, "A5_training",
                                f"clean-0.0-seed{seed}"))
    try:
        store.append("experiment_metadata", {
            "trained_baseline": captured["baseline"],
        })
    finally:
        store.close()
    return captured["baseline"]


def _update_run_metadata(
    out_dir: Path, arm: str, fault: str, strength: float | None, seed: int,
    updates: dict[str, Any],
) -> None:
    run_id = f"{fault}-{strength if strength is not None else 'na'}-seed{seed}"
    store = EventStore(_grid_db(out_dir, arm, run_id))
    try:
        events = store.events(kind="experiment_run")
        if not events:
            raise RuntimeError(f"missing experiment metadata for {run_id}")
        store.append("experiment_metadata", updates)
    finally:
        store.close()


def _run_custom(
    out_dir: Path,
    code_revision: str,
    arm: str,
    scenario: str,
    fault: str,
    strength: float | None,
    seed: int,
    *,
    disconnect_after_execution: bool = False,
    restart_target: str | None = None,
    warmup: int = 15,
    fault_windows: int = 56,
) -> dict[str, Any]:
    run_id = f"{scenario}-{restart_target or 'full'}-seed{seed}"
    path = _grid_db(out_dir, arm, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(path)
    cfg = demo_config()
    cfg["planner"]["kind"] = "rules"
    cfg["planner"]["auto_execute"] = True
    now = [0.0]
    fps = int(cfg["camera"]["analytic_fps"])
    source = SyntheticSource(width=320, height=240, seed=seed, clock=lambda: now[0])
    initial_settings = copy.deepcopy(source.get_settings())
    source.open()
    runner = ProbeRunner(cfg)
    meter = TransportMeter()
    source_fault, default_strength, human_fix = DEMO_SCENARIOS[scenario]
    strength = default_strength if strength is None else strength
    planner = WrongActionPlanner() if scenario == "bad_action" else RuleBasedPlanner()

    def restart_source():
        if source.fault in ("freeze", "disconnect"):
            source.set_fault(None)

    agent = ReliabilityAgent(
        cfg, source, planner, store, restart_cb=restart_source, clock=lambda: now[0]
    )
    initial_frame = source.read()
    runner.calibrate_reference(initial_frame)
    total_windows = warmup + fault_windows + 4
    disconnect_remaining = 0
    disconnect_triggered = False
    cut_settings: dict[str, Any] | None = None
    start_seq = 0
    if store.events():
        start_seq = store.events()[-1]["seq"]

    def install_restart_hook(current_agent, current_store):
        if restart_target is None:
            return
        if restart_target == "CONFIRMED":
            last_step: dict[str, Any] = {}
            original_step = current_agent.tracker.step

            def step(tw, now_s=0.0):
                result = original_step(tw, now_s=now_s)
                last_step["result"] = result
                return result

            current_agent.tracker.step = step
            original_append = current_store.append
            cut_once = {"done": False}

            def append(kind, payload, incident_id=None):
                digest = original_append(kind, payload, incident_id)
                if (
                    not cut_once["done"]
                    and kind == "state"
                    and _state_name(payload.get("to")) == restart_target
                ):
                    incident = last_step.get("result").incident
                    original_append("incident", incident, incident.incident_id)
                    original_append(
                        "experiment_restart_cut",
                        {"state": restart_target, "settings": source.get_settings()},
                        incident.incident_id,
                    )
                    cut_once["done"] = True
                    raise _StopAtState(restart_target)
                return digest

            current_store.append = append
            return
        original_to = current_agent._to
        cut_once = {"done": False}

        def to(dst, reason):
            nonlocal cut_settings
            original_to(dst, reason)
            if not cut_once["done"] and _state_name(dst) == restart_target:
                cut_settings = copy.deepcopy(source.get_settings())
                incident_id = (
                    current_agent.active.incident.incident_id
                    if current_agent.active else None
                )
                current_store.append(
                    "experiment_restart_cut",
                    {"state": restart_target, "settings": cut_settings},
                    incident_id,
                )
                cut_once["done"] = True
                raise _StopAtState(restart_target)

        current_agent._to = to

    install_restart_hook(agent, store)
    def process_window(index: int, current_agent: ReliabilityAgent) -> tuple[str, int]:
        nonlocal disconnect_remaining, disconnect_triggered
        if index == warmup:
            source.set_fault(source_fault, strength)
        agg = WindowAggregator(cfg["camera"]["id"], cfg["window"]["seconds"])
        frames = 0
        meter.connected = True
        for _ in range(fps):
            now[0] += 1.0 / fps
            if disconnect_remaining:
                disconnect_remaining -= 1
                frame = None
            else:
                frame = source.read()
            if frame is None:
                meter.connected = False
                continue
            frames += 1
            meter.on_frame(frame, processed_at=now[0] + 0.02)
            agg.add(runner.analyse(frame))
        tw = agg.emit(meter.snapshot(t=now[0] + 0.02), runner._geom_quality)
        store.append(
            "experiment_window",
            {"index": index, "frames_analyzed": frames,
             "state_before": _state_name(current_agent.state)},
        )
        execution_events_before = store.events(kind="execution")
        executions_before = len(execution_events_before)
        state = current_agent.on_window(tw)
        executions = store.events(kind="execution")
        new_execution_ids = [
            event["payload"].get("execution_id")
            for event in executions[executions_before:]
        ]
        new_execution_incidents = [
            event["incident_id"] for event in executions[executions_before:]
        ]
        store.append(
            "experiment_window_result",
            {"index": index, "state": _state_name(state),
             "settings": copy.deepcopy(source.get_settings()),
             "execution_ids": new_execution_ids,
             "execution_incidents": new_execution_incidents},
        )
        new_success = any(
            event["payload"].get("status") == "success"
            for event in executions[executions_before:]
        )
        if disconnect_after_execution and new_success and not disconnect_triggered:
            disconnect_remaining = 3 * fps
            disconnect_triggered = True
        return _state_name(state), frames

    cut_index: int | None = None
    try:
        for index in range(total_windows):
            try:
                state, _ = process_window(index, agent)
            except _StopAtState:
                cut_index = index
                break
            if restart_target in ("HEALTHY", "SUSPECT") and state == restart_target:
                cut_settings = copy.deepcopy(source.get_settings())
                store.append(
                    "experiment_restart_cut",
                    {"state": restart_target, "settings": cut_settings},
                    agent.active.incident.incident_id if agent.active else None,
                )
                cut_index = index
                break
            if state == "NEEDS_HUMAN" and human_fix is not None:
                if index >= warmup + human_fix:
                    source.set_fault(None)
                    source.settings.update({"focus_ok": True})
            if state == "HEALTHY" and any(
                event["seq"] > start_seq for event in store.events(kind="closed")
            ):
                break

        if restart_target is not None:
            if cut_index is None:
                raise RuntimeError(f"state {restart_target} was not reached")
            before = store.events()
            before_plans = sum(event["kind"] == "plan" for event in before)
            cut_ids = {event["incident_id"] for event in before
                       if event["kind"] == "incident"}
            cut_incident_id = next(iter(cut_ids), None)
            agent.checkpoint()
            agent.release_lease()
            store.close()
            store = EventStore(path)
            agent = ReliabilityAgent(
                cfg, source, planner, store, restart_cb=restart_source,
                clock=lambda: now[0],
            )
            resumed_state = _state_name(agent.state)
            for index in range(cut_index + 1, total_windows):
                state, _ = process_window(index, agent)
                if state == "NEEDS_HUMAN" and human_fix is not None:
                    if index >= warmup + human_fix:
                        source.set_fault(None)
                        source.settings.update({"focus_ok": True})
                if _state_name(agent.state) == "HEALTHY" and any(
                    event["seq"] > start_seq for event in store.events(kind="closed")
                ):
                    break
            after = store.events()
            after_plans = sum(event["kind"] == "plan" for event in after)
            after_executions = [
                event["payload"].get("execution_id")
                for event in after if event["kind"] == "execution"
            ]
            final_settings = copy.deepcopy(source.get_settings())
            rollback_snapshots = [
                event["payload"].get("restored") for event in after
                if event["kind"] == "rollback" and event["payload"].get("ok")
            ]
            settings_reference = _settings_reference(
                after, initial_settings, cut_settings, rollback_snapshots
            )
            restart_metrics = {
                "restart_target": restart_target,
                "cut_index": cut_index,
                "same_incident_id": (
                    cut_incident_id is None
                    or cut_incident_id in {
                        event["incident_id"] for event in after
                        if event["kind"] == "incident"
                    }
                ),
                "plan_count_unchanged": (
                    restart_target not in ("ACTING", "VERIFYING")
                    or after_plans == before_plans
                ),
                "execution_ids_unique": (
                    len([eid for eid in after_executions if eid])
                    == len({eid for eid in after_executions if eid})
                ),
                "settings_match_snapshot_or_commit": final_settings == settings_reference,
                "final_state_valid": (
                    _state_name(agent.state) in ("HEALTHY", "NEEDS_HUMAN")
                ),
                "final_state": _state_name(agent.state),
                "resumed_state": resumed_state,
                "verify_chain": store.verify_chain(),
                "initial_settings": initial_settings,
                "final_settings": final_settings,
            }
        else:
            final_settings = copy.deepcopy(source.get_settings())
            rollback_snapshots = [
                event["payload"].get("restored") for event in store.events()
                if event["kind"] == "rollback" and event["payload"].get("ok")
            ]
            settings_reference = _settings_reference(
                store.events(), initial_settings, None, rollback_snapshots
            )
            restart_metrics = {
                "final_state": _state_name(agent.state),
                "final_state_valid": _state_name(agent.state) in (
                    "HEALTHY", "NEEDS_HUMAN"
                ),
                "initial_settings": initial_settings,
                "final_settings": final_settings,
                "verify_chain": store.verify_chain(),
                "disconnect_triggered": disconnect_triggered,
                "no_committed_verification_without_frames": all(
                    not (
                        event["kind"] == "verification"
                        and _state_name(event["payload"].get("status")) == VERIFY_COMMITTED
                        and _active_window_frames(store.events(), event["seq"]) == 0
                    )
                    for event in store.events(kind="verification")
                ),
                "settings_match_snapshot_or_commit": final_settings == settings_reference,
            }
        metadata = {
            "arm": arm,
            "fault": fault,
            "strength": strength,
            "seed": seed,
            "scenario": scenario,
            "run_id": run_id,
            "code_revision": code_revision,
            "final_state": restart_metrics["final_state"],
            **restart_metrics,
        }
        _append_run(store, metadata)
        return metadata
    finally:
        try:
            agent.checkpoint()
            agent.release_lease()
        finally:
            source.close()
            store.close()


def _active_window_frames(events: list[dict], seq: int) -> int | None:
    starts = [
        event for event in events
        if event["kind"] == "experiment_window" and event["seq"] < seq
    ]
    return starts[-1]["payload"]["frames_analyzed"] if starts else None


def _settings_reference(
    events: list[dict],
    initial_settings: dict[str, Any],
    cut_settings: dict[str, Any] | None,
    rollback_snapshots: list[dict[str, Any] | None],
) -> dict[str, Any]:
    if rollback_snapshots:
        return rollback_snapshots[-1]
    committed_ids = {
        event["incident_id"] for event in events
        if event["kind"] == "verification"
        and _state_name(event["payload"].get("status")) == VERIFY_COMMITTED
    }
    if committed_ids:
        for event in reversed(events):
            if event["kind"] != "experiment_window_result":
                continue
            if committed_ids.intersection(
                event["payload"].get("execution_incidents", [])
            ):
                return event["payload"]["settings"]
        if cut_settings is not None:
            return cut_settings
    return initial_settings


def _classifier_result(events: list[dict], fault: str) -> dict[str, Any]:
    return classify_events(events, CLASSIFIER_FAULT[fault])


def _update_recovery_counts(
    counts: dict[str, int], result: dict[str, Any]
) -> None:
    counts["runs"] += 1
    counts["recoverable"] += int(result["recoverable"])
    if result["outcome"] == "recovered_auto":
        counts["recovered_auto"] += int(result["recoverable"])
    else:
        counts[result["outcome"]] += 1


def _verification_decisions_by_fault(
    runs: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    decisions: dict[str, dict[str, int]] = {}
    for run in runs:
        if run["meta"].get("phase") != "regression":
            continue
        fault = run["meta"].get("fault")
        if not fault:
            continue
        counts = decisions.setdefault(
            fault, {"committed": 0, "rolled_back": 0, "inconclusive": 0}
        )
        events = [event for event in run["events"] if event["kind"] == "verification"]
        if not events:
            counts["inconclusive"] += 1
            continue
        for event in events:
            status = _state_name(event["payload"].get("status")).lower()
            outcome = status if status in ("committed", "rolled_back") else "inconclusive"
            counts[outcome] += 1
    return decisions


def _same_recovery_run_set(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> bool:
    def keys(runs):
        return Counter(
            (
                run["meta"].get("fault"),
                run["meta"].get("strength"),
                run["meta"].get("seed"),
            )
            for run in runs
            if run["meta"].get("fault") in CLASSIFIER_FAULT
            and run["meta"].get("phase") != "regression"
        )

    return keys(left) == keys(right)


def _a6_plan_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    planner_incidents = set()
    fallback_incidents = set()
    frozen_black_local_plans = set()
    for run in runs:
        run_id = run["meta"].get("run_id")
        for event in run["events"]:
            if event["kind"] != "plan":
                continue
            source = event["payload"].get("source")
            incident_id = event.get("incident_id") or f"seq:{event['seq']}"
            key = (run_id, incident_id)
            if run["meta"].get("fault") == "frozen_black" and source == "rules":
                frozen_black_local_plans.add(key)
                continue
            planner_incidents.add(key)
            if source == "fallback":
                fallback_incidents.add(key)

    planner_count = len(planner_incidents)
    fallback_count = len(fallback_incidents)
    return {
        "planner_incidents": planner_count,
        "fallback_incidents": fallback_count,
        "fallback_ratio": fallback_count / planner_count if planner_count else 0.0,
        "fallback_for_all_planner_incidents": (
            planner_count > 0 and fallback_count == planner_count
        ),
        "frozen_black_local_plans": len(frozen_black_local_plans),
        "frozen_black_local_plan_label": (
            "deterministic local plan, planner not called"
        ),
    }


def _load_runs(out_dir: str | Path) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(Path(out_dir).rglob("*.sqlite")):
        store = EventStore(path)
        try:
            events = store.events()
            run_events = [event for event in events if event["kind"] == "experiment_run"]
            if not run_events:
                continue
            if len(run_events) > 1:
                raise ValueError(
                    f"{path} contains more than one experiment_run event"
                )
            metadata = copy.deepcopy(run_events[0]["payload"])
            for event in events:
                if event["kind"] == "experiment_metadata":
                    metadata.update(event["payload"])
            runs.append({
                "db": str(path),
                "events": events,
                "meta": metadata,
                "spend_usd": store.spent_usd(),
                "chain_valid": store.verify_chain(),
            })
        finally:
            store.close()
    return runs


def _detection_for_run(run: dict[str, Any]) -> dict[str, Any]:
    events, meta = run["events"], run["meta"]
    incidents = [event["payload"] for event in events if event["kind"] == "incident"]
    detected_faults = []
    for incident in incidents:
        candidates = incident.get("candidate_faults", [])
        detected_faults.append(
            str(candidates[0]).lower().rsplit(".", 1)[-1] if candidates else None
        )
    return {
        "detected": bool(incidents),
        "first_candidate": detected_faults[0] if detected_faults else None,
        "correct_first_candidate": (
            bool(detected_faults)
            and detected_faults[0] == EXPECTED_FAULT.get(meta.get("fault"))
        ),
        "control": meta.get("fault") in CONTROLS,
    }


def _summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    arm_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        arm_runs[run["meta"]["arm"]].append(run)

    a3_all = arm_runs["A3_full_loop"]
    a3 = [run for run in a3_all
          if run["meta"].get("phase") != "regression"]
    classifier_runs = []
    for run in a3:
        fault = run["meta"]["fault"]
        if fault in CLASSIFIER_FAULT:
            classifier_runs.append({
                **run["meta"],
                **_classifier_result(run["events"], fault),
            })
    recovery = {
        fault: {
            "runs": sum(item["fault"] == fault for item in classifier_runs),
            "recoverable": sum(
                item["fault"] == fault and item["recoverable"] for item in classifier_runs
            ),
            "recovered_auto": sum(
                item["fault"] == fault and item["recoverable"]
                and item["outcome"] == "recovered_auto"
                for item in classifier_runs
            ),
            "needs_human": sum(
                item["fault"] == fault and item["outcome"] == "needs_human"
                for item in classifier_runs
            ),
            "timeout": sum(
                item["fault"] == fault and item["outcome"] == "timeout"
                for item in classifier_runs
            ),
        }
        for fault in sorted({item["fault"] for item in classifier_runs})
    }
    f8_comparable_faults = {"dark", "defocus", "overexpose", "frozen_black"}
    f8_comparable_runs = [
        item for item in classifier_runs if item["fault"] in f8_comparable_faults
    ]
    recovery_a3_f8_comparable = {
        "runs": len(f8_comparable_runs),
        "recoverable": sum(item["recoverable"] for item in f8_comparable_runs),
        "recovered_auto": sum(
            item["recoverable"] and item["outcome"] == "recovered_auto"
            for item in f8_comparable_runs
        ),
        "needs_human": sum(
            item["outcome"] == "needs_human" for item in f8_comparable_runs
        ),
        "timeout": sum(
            item["outcome"] == "timeout" for item in f8_comparable_runs
        ),
    }
    a4_recovery: dict[str, dict[str, int]] = {}
    for run in arm_runs.get("A4_no_downstream_metric", []):
        fault = run["meta"].get("fault")
        if fault not in CLASSIFIER_FAULT or run["meta"].get("phase") == "regression":
            continue
        result = _classifier_result(run["events"], fault)
        counts = a4_recovery.setdefault(
            fault, {"runs": 0, "recoverable": 0, "recovered_auto": 0,
                    "needs_human": 0, "timeout": 0}
        )
        _update_recovery_counts(counts, result)
    confusion: dict[str, dict[str, int]] = {}
    f1_values = []
    scored = [
        run for run in a3
        if run["meta"].get("fault") in (*MVP_FAULTS, *CONTROLS)
    ]
    for fault in MVP_FAULTS:
        expected = EXPECTED_FAULT[fault]
        tp = sum(
            item["meta"]["fault"] == fault
            and _detection_for_run(item)["first_candidate"] == expected
            for item in scored
        )
        positives = sum(item["meta"]["fault"] == fault for item in scored)
        fp = sum(
            item["meta"]["fault"] != fault
            and _detection_for_run(item)["first_candidate"] == expected
            for item in scored
        )
        fn = positives - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / positives if positives else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        confusion[fault] = {
            "tp": tp, "fp_wrong_first_or_control": fp, "fn": fn,
            "positives": positives,
        }
        f1_values.append(f1)
    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else None

    rows: list[dict[str, Any]] = []
    for arm in ("A1_local_detector_only", "A2_detector_no_actions", "A3_full_loop",
                "A4_no_downstream_metric", "A5_single_baseline",
                "A6_token_factory_outage", "A7_rtsp_failure_during_action",
                "A8_restart_in_every_state"):
        values = arm_runs.get(arm, [])
        event_counts = Counter(event["kind"] for run in values for event in run["events"])
        faults = [run for run in values if run["meta"].get("fault") in EXPECTED_FAULT]
        controls = [run for run in values if run["meta"].get("fault") in CONTROLS]
        detections = sum(_detection_for_run(run)["detected"] for run in faults)
        false_confirmations = sum(
            _detection_for_run(run)["detected"] for run in controls
        )
        row: dict[str, Any] = {
            "arm": arm,
            "runs": len(values),
            "incidents": sum(
                sum(event["kind"] == "incident" for event in run["events"])
                for run in values
            ),
            "plans": event_counts["plan"],
            "successful_executions": sum(
                event["kind"] == "execution"
                and event["payload"].get("status") == "success"
                for run in values for event in run["events"]
            ),
            "device_executions": sum(
                event["kind"] == "execution"
                and event["payload"].get("status") in ("success", "failed")
                for run in values for event in run["events"]
            ),
            "rollbacks": event_counts["rollback"],
            "controls": len(controls),
            "false_confirmations": false_confirmations,
            "detection_runs": len(faults),
            "detected_runs": detections,
            "valid_chains": all(run["chain_valid"] for run in values),
            "spend_usd": round(sum(run["spend_usd"] for run in values), 8),
            "unchanged_settings_runs": sum(
                run["meta"].get("settings_unchanged", False)
                for run in values
            ),
            "planner_calls": sum(run["meta"].get("planner_calls", 0) for run in values),
            "correct_first_candidate": sum(
                _detection_for_run(run)["correct_first_candidate"] for run in faults
            ),
        }
        if arm == "A3_full_loop":
            row["macro_f1_mvp"] = macro_f1
            row["recovery_by_fault"] = recovery
        if arm == "A4_no_downstream_metric":
            row["recovery_by_fault"] = a4_recovery
        if arm == "A4_no_downstream_metric":
            row["committed_regressions"] = sum(
                event["kind"] == "verification"
                and _state_name(event["payload"].get("status")) == VERIFY_COMMITTED
                for run in values for event in run["events"]
                if run["meta"].get("phase") == "regression"
            )
            regression_rows = [
                {
                    **classify_regression(
                        run["events"],
                        run["meta"].get("initial_settings", {}),
                        run["meta"].get("final_settings", {}),
                        run["meta"].get("final_state"),
                    ),
                    "fault": run["meta"].get("fault"),
                    "strength": run["meta"].get("strength"),
                }
                for run in values if run["meta"].get("phase") == "regression"
            ]
            row["regression_gate"] = regression_gate(regression_rows)
        if arm == "A6_token_factory_outage":
            row.update(_a6_plan_summary(values))
            row["unhandled_exceptions"] = sum(
                event["kind"] == "experiment_error"
                for run in values for event in run["events"]
            )
        if arm in ("A7_rtsp_failure_during_action", "A8_restart_in_every_state"):
            row["invariant_pass"] = all(
                run["meta"].get("verify_chain", False)
                and run["meta"].get("settings_match_snapshot_or_commit", False)
                and run["meta"].get("no_committed_verification_without_frames", True)
                and run["meta"].get("final_state_valid", True)
                and run["meta"].get("same_incident_id", True)
                and run["meta"].get("plan_count_unchanged", True)
                and run["meta"].get("execution_ids_unique", True)
                for run in values
            )
        if arm == "A2_detector_no_actions":
            row["ticket_requests"] = sum(
                event["kind"] == "execution"
                and event["payload"].get("status") == "ticket"
                for run in values for event in run["events"]
            )
        if arm == "A6_token_factory_outage":
            row["circuit_open_runs"] = sum(
                run["meta"].get("circuit_open", False) for run in values
            )
            row["max_circuit_failures"] = max(
                (run["meta"].get("circuit_failures", 0) for run in values), default=0
            )
            row["circuit_threshold"] = max(
                (run["meta"].get("circuit_threshold", 0) for run in values), default=0
            )
            row["circuit_open_after_threshold"] = any(
                run["meta"].get("circuit_open", False)
                and run["meta"].get("circuit_failures", 0)
                >= run["meta"].get("circuit_threshold", float("inf"))
                for run in values
            )
        rows.append(row)

    a3_recovery = {
        key: value for key, value in recovery.items()
    }
    a6_recovery: dict[str, dict[str, Any]] = {}
    a6_runs = arm_runs.get("A6_token_factory_outage", [])
    for run in a6_runs:
        fault = run["meta"].get("fault")
        if (
            fault not in CLASSIFIER_FAULT
            or run["meta"].get("phase") == "regression"
        ):
            continue
        result = _classifier_result(run["events"], fault)
        counts = a6_recovery.setdefault(
            fault, {"runs": 0, "recoverable": 0, "recovered_auto": 0,
                    "needs_human": 0, "timeout": 0}
        )
        _update_recovery_counts(counts, result)

    def detection_pair(arm):
        values = arm_runs.get(arm, [])
        fault_values = [run for run in values if run["meta"].get("fault") in EXPECTED_FAULT]
        correct = sum(_detection_for_run(run)["correct_first_candidate"]
                      for run in fault_values)
        controls = [run for run in values if run["meta"].get("fault") in CONTROLS]
        false_confirmations = sum(_detection_for_run(run)["detected"] for run in controls)
        return {
            "correct_first_candidate": correct,
            "fault_runs": len(fault_values),
            "false_confirmations": false_confirmations,
            "control_runs": len(controls),
        }

    a3_detection = detection_pair("A3_full_loop")
    a5_detection = detection_pair("A5_single_baseline")
    a3_recovery_runs = [
        run for run in a3 if run["meta"].get("fault") in CLASSIFIER_FAULT
    ]
    a6_recovery_runs = [
        run for run in a6_runs
        if run["meta"].get("fault") in CLASSIFIER_FAULT
        and run["meta"].get("phase") != "regression"
    ]
    a6_recovery_same_run_set = (
        bool(a3_recovery_runs and a6_recovery_runs)
        and _same_recovery_run_set(a3_recovery_runs, a6_recovery_runs)
    )
    a6_recovery_equal = (
        a6_recovery_same_run_set
        and set(a6_recovery) == set(a3_recovery)
        and all(
            a6_recovery[fault]["recoverable"] == a3_recovery[fault]["recoverable"]
            and a6_recovery[fault]["recovered_auto"]
            == a3_recovery[fault]["recovered_auto"]
            for fault in a3_recovery
        )
    )

    a4_regression_runs = [
        run for run in arm_runs.get("A4_no_downstream_metric", [])
        if run["meta"].get("phase") == "regression"
    ]
    a3_regression_runs = [
        run for run in a3_all
        if run["meta"].get("phase") == "regression"
    ]
    verification_decisions = {
        "A3_full_loop": _verification_decisions_by_fault(a3_regression_runs),
        "A4_no_downstream_metric": _verification_decisions_by_fault(
            a4_regression_runs
        ),
    }

    def committed_count(values):
        return sum(
            event["kind"] == "verification"
            and _state_name(event["payload"].get("status")) == VERIFY_COMMITTED
            for run in values for event in run["events"]
        )

    def gate_for(values):
        rows = []
        for run in values:
            if run["meta"].get("phase") != "regression":
                continue
            rows.append({
                **classify_regression(
                    run["events"],
                    run["meta"].get("initial_settings", {}),
                    run["meta"].get("final_settings", {}),
                    run["meta"].get("final_state"),
                ),
                "fault": run["meta"].get("fault"),
                "strength": run["meta"].get("strength"),
            })
        return regression_gate(rows)

    return {
        "arms": rows,
        "macro_f1": {"mvp_faults": confusion, "macro_f1": macro_f1},
        "recovery_a3": a3_recovery,
        "recovery_a3_f8_comparable": recovery_a3_f8_comparable,
        "recovery_a4": a4_recovery,
        "recovery_a6": a6_recovery,
        "a6_recovery_same_run_set": a6_recovery_same_run_set,
        "a6_recovery_equals_a3": a6_recovery_equal,
        "a5_vs_a3_detection": {
            "a3": a3_detection,
            "a5": a5_detection,
        },
        "a4_regression_comparison": {
            "full_loop_committed": committed_count(a3_regression_runs),
            "no_downstream_committed": committed_count(a4_regression_runs),
            "full_loop_runs": len(a3_regression_runs),
            "no_downstream_runs": len(a4_regression_runs),
            "full_loop_gate": gate_for(a3_regression_runs),
            "no_downstream_gate": gate_for(a4_regression_runs),
        },
        "verification_decisions": verification_decisions,
        "a8_states": {
            "runs": [
                run["meta"] for run in arm_runs.get("A8_restart_in_every_state", [])
            ],
            "trace_runs": [
                run["meta"] for run in arm_runs.get("A8_trace", [])
            ],
        },
        "run_count": len(runs),
        "chain_valid": all(run["chain_valid"] for run in runs),
    }


def run_experiments(
    out_dir: str | Path,
    *,
    live: bool = False,
    yes: bool = False,
    seeds=SEEDS,
    smoke: bool = False,
) -> dict[str, Any]:
    if live and not yes:
        raise ValueError("--live requires --yes")
    revision = _code_revision()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    cfg = demo_config()
    cfg["planner"]["kind"] = "nemotron" if live else "rules"
    budget = BudgetGuard(total_usd=0.05, soft_cap_usd=0.05,
                         demo_cap_usd=0.05, hard_cap_usd=0.05)
    live_planner = (
        make_planner(cfg, api_key(), budget) if live else RuleBasedPlanner()
    )
    if live and getattr(live_planner, "client", None) is None:
        raise RuntimeError("--live requires NEBIUS_API_KEY")
    seeds = list(seeds)
    if smoke:
        seeds = seeds[:1]

    a6_planner = _a6_planner(cfg)
    fault_grid = FAULT_GRID[:1] if smoke else FAULT_GRID
    for seed in seeds:
        baseline_for_seed = _run_training_baseline(
            out_dir, revision, 1000 + seed, smoke=smoke
        )
        for fault, strength in fault_grid:
            planner = _NoCallPlanner()
            _run_standard(
                out_dir, revision, "A1_local_detector_only", fault, strength, seed,
                planner=planner, detector_only=True,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )
            _run_standard(
                out_dir, revision, "A2_detector_no_actions", fault, strength, seed,
                planner=live_planner, auto_execute=False,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )
            _run_standard(
                out_dir, revision, "A3_full_loop", fault, strength, seed,
                planner=live_planner,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )
            _run_standard(
                out_dir, revision, "A5_single_baseline", fault, strength, seed,
                baseline_data=baseline_for_seed,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )
            _run_standard(
                out_dir, revision, "A6_token_factory_outage", fault, strength, seed,
                planner=a6_planner,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )
            _update_run_metadata(
                out_dir, "A6_token_factory_outage", fault, strength, seed,
                {
                    "circuit_failures": a6_planner.max_failures,
                    "circuit_open": a6_planner.opened_after_threshold,
                    "circuit_threshold": a6_planner.client.breaker.threshold,
                },
            )
        for control in CONTROLS:
            change = control == "lighting_change"
            control_strength = 0.0
            for arm, kwargs in (
                ("A1_local_detector_only", {
                    "planner": _NoCallPlanner(), "detector_only": True,
                }),
                ("A2_detector_no_actions", {
                    "planner": live_planner, "auto_execute": False,
                }),
                ("A3_full_loop", {"planner": live_planner}),
                ("A5_single_baseline", {
                    "baseline_data": baseline_for_seed,
                }),
            ):
                _run_standard(
                    out_dir, revision, arm, control, control_strength, seed,
                    lighting_change=change,
                    warmup=3 if smoke else 30,
                    fault_windows=6 if smoke else 18,
                    **kwargs,
                )

        for fault, strength in fault_grid:
            _run_standard(
                out_dir, revision, "A4_no_downstream_metric", fault, strength, seed,
                planner=RuleBasedPlanner(), downstream_ablation=True,
                warmup=3 if smoke else 30,
                fault_windows=12 if smoke else 56,
            )

        regression_faults = ("dark",) if smoke else tuple(REGRESSION_ACTIONS)
        for fault in regression_faults:
            strength = dict(FAULT_GRID).get(fault)
            action, arguments = REGRESSION_ACTIONS[fault]
            for arm, ablated in (
                ("A3_full_loop", False),
                ("A4_no_downstream_metric", True),
            ):
                planner = ScriptedPlanner(action, arguments)
                _run_standard(
                    out_dir, revision, arm, fault, strength, seed,
                    planner=planner, downstream_ablation=ablated,
                    scripted_black=fault == "frozen_black",
                    warmup=3 if smoke else 30,
                    fault_windows=12 if smoke else 56,
                    extra_metadata={"phase": "regression"},
                )

        a7_faults = (("dark", 0.99),) if smoke else (
            ("dark", 0.99), ("defocus", 1.0)
        )
        for fault, strength in a7_faults:
            _run_custom(
                out_dir, revision, "A7_rtsp_failure_during_action",
                _scenario_for(fault), fault, strength, seed,
                disconnect_after_execution=True,
                warmup=3 if smoke else 15,
                fault_windows=12 if smoke else 56,
            )

    if smoke:
        for target in ("ACTING", "VERIFYING"):
            _run_custom(
                out_dir, revision, "A8_restart_in_every_state",
                "dark", "dark", 0.99, seeds[0],
                restart_target=target, warmup=3, fault_windows=12,
            )
    else:
        _run_a8(out_dir, revision, seeds)

    summary = _summarize_runs(_load_runs(out_dir))
    a2 = next(row for row in summary["arms"]
              if row["arm"] == "A2_detector_no_actions")
    if not (
        a2["plans"] > 0
        and a2["device_executions"] == 0
        and a2["unchanged_settings_runs"] == a2["runs"]
    ):
        raise AssertionError("A2 must plan, never execute, and preserve settings")
    return summary


def _a6_planner(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["planner"]["kind"] = "nemotron"
    budget = BudgetGuard(total_usd=0.05, soft_cap_usd=0.05,
                         demo_cap_usd=0.05, hard_cap_usd=0.05)
    return _ObservedOutagePlanner(
        make_planner(cfg, "offline-fake-key", budget, sdk_client=_FailingSDK())
    )


def _run_a8(
    out_dir: Path, code_revision: str, seeds: list[int]
) -> None:
    for scenario in ("dark", "bad_action"):
        fault, strength, _ = DEMO_SCENARIOS[scenario]
        _run_custom(
            out_dir, code_revision, "A8_trace", scenario, scenario,
            strength, seeds[0], warmup=15, fault_windows=56,
        )
    traces = _load_runs(out_dir)
    reachable: dict[str, set[str]] = defaultdict(set)
    for run in traces:
        if run["meta"]["arm"] != "A8_trace":
            continue
        reachable[run["meta"]["scenario"]].add("HEALTHY")
        for event in run["events"]:
            if event["kind"] == "state":
                target = event["payload"].get("to")
                if target:
                    reachable[run["meta"]["scenario"]].add(
                        _state_name(target)
                    )
    for seed in seeds:
        for scenario in ("dark", "bad_action"):
            fault, strength, _ = DEMO_SCENARIOS[scenario]
            for target in sorted(reachable[scenario]):
                _run_custom(
                    out_dir, code_revision, "A8_restart_in_every_state",
                    scenario, scenario, strength, seed,
                    restart_target=target, warmup=15, fault_windows=56,
                )
    all_states = {_state_name(state) for state in IncidentState}
    for scenario in ("dark", "bad_action"):
        store = EventStore(_grid_db(
            out_dir, "A8_trace", f"{scenario}-full-seed{seeds[0]}"
        ))
        try:
            store.append("experiment_metadata", {
                "reachable_states": sorted(reachable[scenario]),
                "unreachable_states": sorted(all_states - reachable[scenario]),
            })
        finally:
            store.close()


def _report_data(out_dir: str | Path) -> dict[str, Any]:
    runs = _load_runs(out_dir)
    summary = _summarize_runs(runs)
    meta = runs[0]["meta"] if runs else {}
    return {
        "label": "SIMULATION",
        "code_revision": meta.get("code_revision"),
        "summary": summary,
        "runs": [
            {
                "arm": run["meta"].get("arm"),
                "fault": run["meta"].get("fault"),
                "strength": run["meta"].get("strength"),
                "seed": run["meta"].get("seed"),
                "scenario": run["meta"].get("scenario"),
                "run_id": run["meta"].get("run_id"),
                "database": run["db"],
                "final_state": run["meta"].get("final_state"),
                "chain_valid": run["chain_valid"],
                "spend_usd": run["spend_usd"],
                "invariants": {
                    key: run["meta"].get(key)
                    for key in (
                        "disconnect_triggered",
                        "no_committed_verification_without_frames",
                        "settings_match_snapshot_or_commit",
                        "final_state_valid",
                        "same_incident_id",
                        "plan_count_unchanged",
                        "execution_ids_unique",
                    )
                },
            }
            for run in runs
        ],
        "evidence": [
            {
                "category": "Macro F1 (A3) and controls",
                "source": "this report, derived from A3 EventStores",
                "status": "SIMULATION",
            },
            {
                "category": "False alarms per hour by route",
                "source": "/home/ubuntu/staging/f10-soak-20261018T122142Z/report.md",
                "status": "pending PR1 soak report; not recalculated here",
            },
            {
                "category": "Diagnosis",
                "source": (
                    "docs/evidence/f6/"
                    "golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md"
                ),
                "status": "SIMULATION evidence; REAL HARDWARE pending F4",
            },
            {
                "category": "LLM structure",
                "source": (
                    "docs/evidence/f6/"
                    "golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md"
                ),
                "status": "SIMULATION evidence; REAL HARDWARE pending F4",
            },
            {
                "category": "Adversarial safety",
                "source": "tests/adversarial/",
                "status": "SIMULATION evidence; REAL HARDWARE pending F4",
            },
            {
                "category": "Recovery",
                "source": "this report, A3 EventStores",
                "status": "SIMULATION",
            },
            {
                "category": "Rollback gate",
                "source": "docs/evidence/f8/recovery-bench.md",
                "status": "SIMULATION evidence; REAL HARDWARE pending F4",
            },
            {
                "category": "Soak robustness",
                "source": "/home/ubuntu/staging/f10-soak-20261018T122142Z/report.md",
                "status": "pending PR1 soak report; REAL HARDWARE pending F4",
            },
            {
                "category": "Budget",
                "source": "per-run EventStore usage tables and docs/evidence/f6/",
                "status": "SIMULATION; no live calls in this run",
            },
            {
                "category": "Reproducibility",
                "source": "F11",
                "status": "pending",
            },
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# F10 PR2 Experiments and Ablations",
        "",
        "**SIMULATION** — `SyntheticSource`; no live Nebius calls were made.",
        f"Code revision: `{report.get('code_revision')}`",
        f"EventStore runs: {summary['run_count']}; all hash chains valid: "
        f"{summary['chain_valid']}.",
        "",
        "## Per-arm results",
        "",
        "| Arm | Runs | Incidents | Plans | Successful executions | "
        "Controls / false confirmations | Rollbacks | Key result | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in summary["arms"]:
        key_result = ""
        status = "SIMULATION"
        if row["arm"] == "A1_local_detector_only":
            key_result = (
                f"correct={row['correct_first_candidate']}/{row['detection_runs']}; "
                f"planner calls={row['planner_calls']}"
            )
        elif row["arm"] == "A2_detector_no_actions":
            key_result = (
                f"unchanged={row['unchanged_settings_runs']}/{row['runs']}; "
                f"device executions={row['device_executions']}; "
                f"ticket requests={row['ticket_requests']}; auto-execution disabled"
            )
        elif row["arm"] == "A3_full_loop":
            f1 = row.get("macro_f1_mvp")
            key_result = (
                f"macro F1={f1:.3f}; "
                f"recovery={sum(x['recovered_auto'] for x in row['recovery_by_fault'].values())}/"
                f"{sum(x['recoverable'] for x in row['recovery_by_fault'].values())}"
            ) if f1 is not None else "no scored runs"
        elif row["arm"] == "A4_no_downstream_metric":
            comparison = summary["a4_regression_comparison"]
            key_result = (
                f"COMMITTED={comparison['no_downstream_committed']} vs "
                f"{comparison['full_loop_committed']} full-loop"
            )
        elif row["arm"] == "A5_single_baseline":
            detection = summary["a5_vs_a3_detection"]
            key_result = (
                f"correct={detection['a5']['correct_first_candidate']}/"
                f"{detection['a5']['fault_runs']} (A3 "
                f"{detection['a3']['correct_first_candidate']}/"
                f"{detection['a3']['fault_runs']}); false controls="
                f"{detection['a5']['false_confirmations']}/"
                f"{detection['a5']['control_runs']}"
            )
        elif row["arm"] == "A6_token_factory_outage":
            key_result = (
                f"fallback={row.get('fallback_incidents', 0)}/"
                f"{row.get('planner_incidents', 0)} planner incidents; "
                f"unhandled={row.get('unhandled_exceptions', 0)}; "
                f"circuit opened after threshold="
                f"{row.get('circuit_open_after_threshold', False)}; "
                f"same recovery as A3={summary['a6_recovery_equals_a3']}; "
                f"spend=${row['spend_usd']:.4f}"
            )
        elif row["arm"] in (
            "A7_rtsp_failure_during_action", "A8_restart_in_every_state"
        ):
            key_result = f"invariants pass={row.get('invariant_pass', False)}"
        lines.append(
            f"| {row['arm']} | {row['runs']} | {row['incidents']} | {row['plans']} | "
            f"{row['successful_executions']} | {row['controls']} / "
            f"{row['false_confirmations']} | {row['rollbacks']} | "
            f"{key_result} | {status} |"
        )
    lines.extend([
        "",
        "For A2, device executions count only `success` and `failed` statuses; "
        "policy-designated human-ticket requests are reported separately. Settings are "
        "compared with the SyntheticSource state immediately after fault injection.",
        "",
        "## A6 plan routing",
        "",
        "| Path | Incidents | Result |",
        "|---|---:|---|",
    ])
    a6 = next(
        row for row in summary["arms"]
        if row["arm"] == "A6_token_factory_outage"
    )
    lines.extend([
        f"| Planner-routed | {a6['planner_incidents']} | fallback "
        f"{a6['fallback_incidents']}/{a6['planner_incidents']} incidents "
        f"({a6['fallback_ratio']:.3f}) |",
        f"| frozen_black | {a6['frozen_black_local_plans']} | "
        f"{a6['frozen_black_local_plan_label']} |",
    ])
    lines.extend(["", "## A3 recovery by fault", "",
                  "| Fault | Runs | Recoverable | Recovered auto | Needs human | Timeout |",
                  "|---|---:|---:|---:|---:|---:|"])
    for fault, result in sorted(summary["recovery_a3"].items()):
        fault_label = (
            "occlusion (ticket / needs_human expected)"
            if fault == "occlusion" else fault
        )
        lines.append(
            f"| {fault_label} | {result['runs']} | {result['recoverable']} | "
            f"{result['recovered_auto']} | {result['needs_human']} | {result['timeout']} |"
        )
    f8_comparable = summary["recovery_a3_f8_comparable"]
    lines.append(
        f"| F8-comparable subset | {f8_comparable['runs']} | "
        f"{f8_comparable['recoverable']} | {f8_comparable['recovered_auto']} | "
        f"{f8_comparable['needs_human']} | {f8_comparable['timeout']} |"
    )
    lines.extend([
        "",
        "The F8 classifier returns `recoverable=False` for occlusion; its five "
        "ticket / needs-human outcomes are reported separately and excluded from "
        "the recoverable denominator.",
    ])
    comparison = summary["a4_regression_comparison"]
    lines.extend([
        "",
        "A4 used the fixed visual primary by fault and removed every `task.*` primary/guard; "
        "the pre-registered improvement delta was not adjusted.",
        f"Deliberate-regression COMMITTED count: full loop "
        f"{comparison['full_loop_committed']}/{comparison['full_loop_runs']}; "
        f"no-downstream-metric {comparison['no_downstream_committed']}/"
        f"{comparison['no_downstream_runs']}.",
        f"Regression gate: full loop {comparison['full_loop_gate'].get('gate_pass')}; "
        f"no-downstream-metric {comparison['no_downstream_gate'].get('gate_pass')}.",
        "",
        "## Regression verification decisions by fault family",
        "",
        "| Family | A3 committed | A3 rolled_back | A3 inconclusive | "
        "A4 committed | A4 rolled_back | A4 inconclusive |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    a3_decisions = summary["verification_decisions"]["A3_full_loop"]
    a4_decisions = summary["verification_decisions"]["A4_no_downstream_metric"]
    for fault in sorted(set(a3_decisions) | set(a4_decisions)):
        a3 = a3_decisions.get(
            fault, {"committed": 0, "rolled_back": 0, "inconclusive": 0}
        )
        a4 = a4_decisions.get(
            fault, {"committed": 0, "rolled_back": 0, "inconclusive": 0}
        )
        lines.append(
            f"| {fault} | {a3['committed']} | {a3['rolled_back']} | "
            f"{a3['inconclusive']} | {a4['committed']} | "
            f"{a4['rolled_back']} | {a4['inconclusive']} |"
        )
    lines.extend([
        "",
        "## A4 recovery by fault",
        "",
        "| Fault | Runs | Recoverable | Recovered auto | Needs human | Timeout |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for fault, result in sorted(summary["recovery_a4"].items()):
        lines.append(
            f"| {fault} | {result['runs']} | {result['recoverable']} | "
            f"{result['recovered_auto']} | {result['needs_human']} | {result['timeout']} |"
        )
    lines.extend([
        "",
        f"A6 recovery matches A3 on the identical fault/strength/seed run set "
        f"({summary['a6_recovery_same_run_set']}): "
        f"{summary['a6_recovery_equals_a3']}.",
        "",
        "## A8 restart coverage",
        "",
    ])
    for trace in summary["a8_states"]["trace_runs"]:
        lines.append(
            f"- `{trace['scenario']}` reachable states: "
            f"{', '.join(trace.get('reachable_states', [])) or 'none'}; unreachable: "
            f"{', '.join(trace.get('unreachable_states', [])) or 'none'}."
        )
    lines.extend([
        "",
        "## Evidence and limitations",
        "",
        "| Category | Source | Result |",
        "|---|---|---|",
    ])
    for evidence in report["evidence"]:
        lines.append(
            f"| {evidence['category']} | `{evidence['source']}` | {evidence['status']} |"
        )
    lines.extend([
        "",
        "All results in this report are SIMULATION. REAL HARDWARE rows remain pending F4; "
        "F11 reproducibility remains pending. False alarms/hour are referenced from the "
        "F10 PR1 soak report and are not recalculated by this report.",
        "",
    ])
    return "\n".join(lines)


def generate_report(
    out_dir: str | Path, report_dir: str | Path
) -> tuple[dict[str, Any], str]:
    report = _report_data(out_dir)
    markdown = _markdown(report)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "experiments.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (report_dir / "experiments.md").write_text(markdown, encoding="utf-8")
    return report, markdown
