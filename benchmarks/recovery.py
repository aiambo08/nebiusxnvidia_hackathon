"""Offline recovery and rollback benchmark for F8."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from reliability_agent.contracts.models import ActionName, NemotronPlan, PlanAction, TokenUsage
from reliability_agent.demo import demo_config, run_scenario
from reliability_agent.nemotron.planner import PlanOutcome, RuleBasedPlanner
from reliability_agent.storage import EventStore

RECOVERY_GRID: tuple[tuple[str, tuple[float | None, ...]], ...] = (
    ("dark", (0.8, 0.9, 0.99)),
    ("defocus", (0.6, 0.8, 1.0)),
    ("overexpose", (0.6, 0.8, 1.0)),
    ("frozen_black", (None,)),
)

RECOVERABLE_ACTIONS = {
    "dark": {str(ActionName.SET_EXPOSURE_BOUNDED)},
    "defocus": {str(ActionName.TRIGGER_AUTOFOCUS)},
    "overexpose": {str(ActionName.SET_EXPOSURE_BOUNDED)},
    "frozen_black": {str(ActionName.RESTART_CAPTURE)},
}

REGRESSION_ACTIONS = {
    "dark": (ActionName.SET_EXPOSURE_BOUNDED, {"delta_ev": -1.5}),
    "defocus": (ActionName.ENTER_SAFE_MODE, {}),
    "overexpose": (ActionName.SET_EXPOSURE_BOUNDED, {"delta_ev": 1.5}),
    "frozen_black": (ActionName.ENTER_SAFE_MODE, {}),
}


class ScriptedPlanner:
    name = "scripted-regression"

    def __init__(self, action: ActionName, arguments: dict[str, Any]) -> None:
        self.action = action
        self.arguments = arguments

    def plan(self, incident):
        return PlanOutcome(
            NemotronPlan(
                diagnosis=incident.candidate_faults[0],
                confidence=0.9,
                action=PlanAction(name=self.action, arguments=self.arguments),
                human_message="Scripted F8 regression case",
            ),
            TokenUsage(model="scripted"),
            "scripted",
        )


def _normal(value: Any) -> str:
    return str(value).lower().rsplit(".", 1)[-1]


def classify_events(events: list[dict], fault: str) -> dict[str, Any]:
    """Classify a completed run using only its persisted EventStore events."""
    incident_events = [event for event in events if event["kind"] == "incident"]
    if not incident_events:
        return {
            "recoverable": True,
            "outcome": "timeout",
            "plan_source": None,
        }
    payload = incident_events[-1]["payload"]
    allowed = {_normal(action) for action in payload.get("allowed_actions", [])}
    recoverable = bool(allowed & RECOVERABLE_ACTIONS[fault])
    plan_events = [event for event in events if event["kind"] == "plan"]
    closed = [event["payload"] for event in events if event["kind"] == "closed"]
    ticketed = any(event["kind"] == "ticket" for event in events)
    states = [event["payload"].get("to") for event in events if event["kind"] == "state"]
    needs_human = any(_normal(state) == "needs_human" for state in states)
    if any(_normal(item.get("reason")) == "recovered" for item in closed) and not ticketed:
        outcome = "recovered_auto"
    elif needs_human or ticketed:
        outcome = "needs_human"
    else:
        outcome = "timeout"
    return {
        "recoverable": recoverable,
        "outcome": outcome,
        "plan_source": plan_events[-1]["payload"].get("source") if plan_events else None,
    }


def classify_regression(
    events: list[dict],
    initial_settings: dict[str, Any],
    final_settings: dict[str, Any],
) -> dict[str, Any]:
    """Classify rollback coverage and untouched settings from events and device state."""
    regression_executed = any(
        event["kind"] == "execution"
        and event["payload"].get("status") == "success"
        for event in events
    )
    rollback = next(
        (event["payload"] for event in reversed(events)
         if event["kind"] == "rollback"),
        None,
    )
    rollback_ok = bool(rollback and rollback.get("ok"))
    snapshot_equal = bool(rollback_ok and final_settings == rollback.get("restored"))
    safe_mode = final_settings.get("safe_mode") is True
    settings_unchanged = (
        final_settings == initial_settings if not regression_executed else None
    )
    regression_pass = snapshot_equal or safe_mode
    regression_gate_pass = (
        regression_pass if regression_executed else settings_unchanged is True
    )
    incident_confirmed = any(event["kind"] == "incident" for event in events)
    non_executed_reason = (
        None if regression_executed else (
            "no incident confirmed" if not incident_confirmed
            else "no successful execution event"
        )
    )
    return {
        "regression_executed": regression_executed,
        "settings_unchanged": settings_unchanged,
        "incident_confirmed": incident_confirmed,
        "non_executed_reason": non_executed_reason,
        "rollback_ok": rollback_ok,
        "snapshot_equal": snapshot_equal,
        "regression_pass": regression_pass,
        "regression_gate_pass": regression_gate_pass,
    }


def _run_case(
    scenario: str,
    strength: float | None,
    seed: int,
    *,
    regression: bool,
    warmup: int = 15,
    fault_windows: int = 56,
):
    store = EventStore()
    observed_source = []
    initial_settings = []
    planner = (
        ScriptedPlanner(*REGRESSION_ACTIONS[scenario])
        if regression else RuleBasedPlanner()
    )

    def observe_source(source):
        observed_source.append(source)
        initial_settings.append(source.get_settings())
        if regression and scenario == "frozen_black":
            set_fault = source.set_fault

            def do_not_clear_frozen_fault(fault, *args, **kwargs):
                if fault is not None:
                    set_fault(fault, *args, **kwargs)

            source.set_fault = do_not_clear_frozen_fault

    try:
        demo_scenario = "overexposure" if scenario == "overexpose" else scenario
        result = run_scenario(
            demo_scenario,
            planner=planner,
            cfg=demo_config(),
            store=store,
            warmup=warmup,
            fault_windows=fault_windows,
            fault_strength=strength,
            seed=seed,
            on_source=observe_source,
        )
        events = store.events()
        classified = classify_events(events, scenario)
        final_settings = observed_source[0].get_settings()
        rollback = next(
            (event["payload"] for event in reversed(events)
             if event["kind"] == "rollback"),
            None,
        )
        snapshot_equal = bool(
            rollback
            and rollback.get("ok")
            and final_settings == rollback.get("restored")
        )
        run = {
            "scenario": scenario,
            "fault": scenario,
            "strength": strength,
            "seed": seed,
            **classified,
            "final_state": result.final_state,
            "rollback_ok": bool(rollback and rollback.get("ok")),
            "snapshot_equal": snapshot_equal,
        }
        if regression:
            run.update(classify_regression(
                events, initial_settings[0], final_settings
            ))
        return run
    finally:
        store.close()


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(run["fault"], run["strength"])].append(run)
    by_fault_strength = {}
    for (fault, strength), values in sorted(grouped.items(), key=lambda item: (
        item[0][0], -1 if item[0][1] is None else item[0][1]
    )):
        recoverable = sum(item["recoverable"] for item in values)
        by_fault_strength[f"{fault}:{strength if strength is not None else 'n/a'}"] = {
            "runs": len(values),
            "recoverable": recoverable,
            "recovered_auto": sum(
                item["recoverable"] and item["outcome"] == "recovered_auto"
                for item in values
            ),
            "needs_human": sum(item["outcome"] == "needs_human" for item in values),
            "timeout": sum(item["outcome"] == "timeout" for item in values),
        }
    recoverable = sum(item["recoverable"] for item in runs)
    recovery_rate = (
        sum(item["recoverable"] and item["outcome"] == "recovered_auto" for item in runs)
        / recoverable if recoverable else None
    )
    return {
        "runs": len(runs),
        "recoverable": recoverable,
        "recovered_auto": sum(
            item["recoverable"] and item["outcome"] == "recovered_auto" for item in runs
        ),
        "needs_human": sum(item["outcome"] == "needs_human" for item in runs),
        "timeout": sum(item["outcome"] == "timeout" for item in runs),
        "recovery_rate": recovery_rate,
        "gate_pass": recovery_rate is not None and recovery_rate >= 0.85,
        "by_fault_strength": by_fault_strength,
    }


def run_recovery_benchmark(seeds=range(10)) -> dict[str, Any]:
    runs = [
        _run_case(scenario, strength, seed, regression=False)
        for scenario, strengths in RECOVERY_GRID
        for strength in strengths
        for seed in seeds
    ]
    return {"summary": _summarize(runs), "runs": runs}


def run_regression_benchmark(seeds=range(5)) -> dict[str, Any]:
    runs = [
        _run_case(scenario, strength, seed, regression=True)
        for scenario, strengths in RECOVERY_GRID
        for strength in strengths
        for seed in seeds
    ]
    executed = [run for run in runs if run["regression_executed"]]
    not_executed = [run for run in runs if not run["regression_executed"]]
    executed_passed = sum(run["regression_gate_pass"] for run in executed)
    not_executed_unchanged = sum(
        run["settings_unchanged"] is True for run in not_executed
    )
    grouped: dict[tuple[str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(run["fault"], run["strength"])].append(run)
    by_fault_strength = {
        f"{fault}:{strength if strength is not None else 'n/a'}": {
            "runs": len(values),
            "passed": sum(item["regression_pass"] for item in values),
            "rollback_ok": sum(item["rollback_ok"] for item in values),
            "settings_identical": sum(item["snapshot_equal"] for item in values),
            "executed": sum(item["regression_executed"] for item in values),
            "executed_passed": sum(
                item["regression_executed"] and item["regression_gate_pass"]
                for item in values
            ),
            "not_executed": sum(not item["regression_executed"] for item in values),
            "settings_unchanged": sum(
                not item["regression_executed"] and item["settings_unchanged"] is True
                for item in values
            ),
        }
        for (fault, strength), values in sorted(grouped.items(), key=lambda item: (
            item[0][0], -1 if item[0][1] is None else item[0][1]
        ))
    }
    non_executed_runs = [
        {
            "fault": run["fault"],
            "strength": run["strength"],
            "seed": run["seed"],
            "reason": run["non_executed_reason"],
            "settings_unchanged": run["settings_unchanged"],
            "final_state": run["final_state"],
            "plan_source": run["plan_source"],
        }
        for run in not_executed
    ]
    return {
        "summary": {
            "runs": len(runs),
            "passed": sum(item["regression_pass"] for item in runs),
            "failed": sum(not item["regression_pass"] for item in runs),
            "executed": len(executed),
            "executed_passed": executed_passed,
            "not_executed": len(not_executed),
            "not_executed_settings_unchanged": not_executed_unchanged,
            "gate_pass": (
                executed_passed == len(executed)
                and not_executed_unchanged == len(not_executed)
            ),
            "rollback_ok": sum(item["rollback_ok"] for item in runs),
            "settings_identical": sum(item["snapshot_equal"] for item in runs),
            "by_fault_strength": by_fault_strength,
        },
        "non_executed_runs": non_executed_runs,
        "runs": runs,
    }


def run_smoke() -> dict[str, Any]:
    """Small offline CI smoke: one recoverable case and one regression case."""
    recovery = _run_case(
        "dark", 0.99, 0, regression=False, warmup=3, fault_windows=20
    )
    regression = _run_case(
        "dark", 0.99, 0, regression=True, warmup=3, fault_windows=20
    )
    return {"recovery": recovery, "regression": regression}
