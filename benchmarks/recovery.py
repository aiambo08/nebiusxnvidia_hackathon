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
REGRESSION_FAMILIES = tuple(REGRESSION_ACTIONS)


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
    """Classify recovery outcomes from persisted EventStore events."""
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
    final_state: str | None = None,
) -> dict[str, Any]:
    """Classify regression behavior from events, scenario state, and device settings."""
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
    pre_action_snapshot_settings = rollback.get("restored") if rollback else None
    snapshot_equal = bool(
        rollback_ok and _same_settings(final_settings, pre_action_snapshot_settings)
    )
    safe_mode = final_settings.get("safe_mode") is True
    settings_unchanged = (
        final_settings == initial_settings if not regression_executed else None
    )
    regression_pass = regression_executed and (snapshot_equal or safe_mode)
    regression_gate_pass = (
        (safe_mode or (rollback_ok and snapshot_equal))
        if regression_executed else settings_unchanged is True
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
        "safe_mode": safe_mode,
        "initial_settings": initial_settings,
        "pre_action_snapshot_settings": pre_action_snapshot_settings,
        "final_settings": final_settings,
        "final_state": final_state,
        "regression_pass": regression_pass,
        "regression_gate_pass": regression_gate_pass,
    }


def _same_settings(left: Any, right: Any) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


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
                events, initial_settings[0], final_settings, result.final_state
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


def regression_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate regression outcomes using EventStore classifications and device state."""
    by_fault = {
        fault: {
            "runs": 0,
            "executed": 0,
            "executed_pass": 0,
            "not_executed": 0,
            "not_executed_unchanged": 0,
        }
        for fault in REGRESSION_FAMILIES
    }
    by_fault_strength: dict[str, dict[str, int]] = {}
    raw_passed = 0
    executed_count = 0
    executed_pass = 0
    not_executed = 0
    not_executed_unchanged = 0
    rollback_ok_count = 0
    settings_identical = 0
    row_passes = []

    for row in rows:
        fault = str(row.get("fault", row.get("scenario", "")))
        if fault not in by_fault:
            by_fault[fault] = {
                "runs": 0,
                "executed": 0,
                "executed_pass": 0,
                "not_executed": 0,
                "not_executed_unchanged": 0,
            }
        family = by_fault[fault]
        family["runs"] += 1
        executed = row.get("regression_executed") is True
        rollback_ok = row.get("rollback_ok") is True
        exact_snapshot = rollback_ok and _same_settings(
            row.get("final_settings"), row.get("pre_action_snapshot_settings")
        )
        if rollback_ok:
            rollback_ok_count += 1
        if exact_snapshot:
            settings_identical += 1

        if executed:
            executed_count += 1
            family["executed"] += 1
            passed = (
                row.get("final_settings", {}).get("safe_mode") is True
                or exact_snapshot
            )
            if passed:
                executed_pass += 1
                family["executed_pass"] += 1
                raw_passed += 1
        else:
            not_executed += 1
            family["not_executed"] += 1
            unchanged = _same_settings(
                row.get("final_settings"), row.get("initial_settings")
            )
            if unchanged:
                not_executed_unchanged += 1
                family["not_executed_unchanged"] += 1
            passed = unchanged
        row_passes.append(passed)

        strength = row.get("strength")
        key = f"{fault}:{strength if strength is not None else 'n/a'}"
        counts = by_fault_strength.setdefault(key, {
            "runs": 0,
            "passed": 0,
            "rollback_ok": 0,
            "settings_identical": 0,
            "executed": 0,
            "executed_pass": 0,
            "not_executed": 0,
            "not_executed_unchanged": 0,
        })
        counts["runs"] += 1
        counts["passed"] += int(executed and passed)
        counts["rollback_ok"] += int(rollback_ok)
        counts["settings_identical"] += int(exact_snapshot)
        if executed:
            counts["executed"] += 1
            counts["executed_pass"] += int(passed)
        else:
            counts["not_executed"] += 1
            counts["not_executed_unchanged"] += int(unchanged)

    missing_families = [
        fault for fault in REGRESSION_FAMILIES if by_fault[fault]["executed"] == 0
    ]
    coverage_floor_pass = not missing_families
    return {
        "runs": len(rows),
        "passed": raw_passed,
        "failed": len(rows) - raw_passed,
        "executed": executed_count,
        "executed_pass": executed_pass,
        "not_executed": not_executed,
        "not_executed_unchanged": not_executed_unchanged,
        "rollback_ok": rollback_ok_count,
        "settings_identical": settings_identical,
        "coverage_floor": {
            "pass": coverage_floor_pass,
            "required_families": list(REGRESSION_FAMILIES),
            "missing_families": missing_families,
        },
        "gate_pass": all(row_passes) and coverage_floor_pass,
        "by_fault": by_fault,
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
    summary = regression_gate(runs)
    not_executed = [run for run in runs if not run["regression_executed"]]
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
        "summary": summary,
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
