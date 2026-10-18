"""Event-backed live-pipeline soak benchmark (SIMULATION)."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import os
import random
import shlex
import statistics
import threading
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.runtime import run_live
from reliability_agent.storage.event_store import EventStore

FAULTS = (
    ("dark", 0.99),
    ("defocus", 1.0),
    ("freeze", 1.0),
    ("overexpose", 1.0),
    ("occlude", 1.0),
)
# Only a decoder restart clears its fault in the harness; exposure and focus faults stay active for
# their whole episode, and the SyntheticSource physics decides whether an applied setting helps.
REMEDIATIONS = {
    "dark": set(),
    "defocus": set(),
    "freeze": {"restart_capture"},
    "overexpose": set(),
    "occlude": set(),
}
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DURATION_S = 14400


def _wall_now() -> datetime:
    return datetime.now(UTC)


def _rss_mb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    if importlib.util.find_spec("psutil") is not None:
        import psutil

        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    return None


def _sample(store: EventStore, db_path: Path, elapsed_s: float, windows: int,
            *, final: bool = False) -> dict[str, Any]:
    try:
        fd_count = len(os.listdir("/proc/self/fd"))
    except OSError:
        fd_count = None
    try:
        db_size = db_path.stat().st_size
    except OSError:
        db_size = None
    payload = {
        "elapsed_s": elapsed_s,
        "rss_mb": _rss_mb(),
        "thread_count": threading.active_count(),
        "fd_count": fd_count,
        "python_objects": len(gc.get_objects()),
        "event_store_bytes": db_size,
        "windows_processed": windows,
        "final": final,
        "label": "SIMULATION",
    }
    store.append("soak_sample", payload)
    return payload


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _event_fault_windows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("kind") != "soak_fault":
            continue
        payload = event.get("payload", {})
        fault_id = str(payload.get("fault_id", ""))
        if not fault_id:
            continue
        entry = windows.setdefault(fault_id, {})
        phase = payload.get("phase")
        if phase == "start":
            entry.update(payload)
            entry["start_wall"] = payload.get("start_wall", event.get("ts"))
        elif phase == "end":
            entry.update(payload)
            entry["end_wall"] = payload.get("end_wall", event.get("ts"))
    return [window for window in windows.values() if window.get("start_wall")]


def _incident_id(event: dict[str, Any]) -> str | None:
    payload = event.get("payload", {})
    return event.get("incident_id") or payload.get("incident_id")


def _planner_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    usage_events = [event for event in events if event.get("kind") == "usage"]
    planner_events = [
        event for event in events if event.get("kind") in {"plan", "usage"}
    ]
    names: set[str] = set()
    live_calls = 0
    cost_usd = 0.0
    for event in planner_events:
        payload = event.get("payload", {})
        usage = payload.get("usage", payload if event.get("kind") == "usage" else {})
        source = payload.get("source") or payload.get("planner")
        model = usage.get("model")
        if source:
            names.add(str(source))
        if model:
            names.add(str(model))
        if event.get("kind") == "usage" or not usage_events:
            cost_usd += float(
                usage.get("estimated_cost_usd") or usage.get("cost_usd") or 0.0
            )

        is_local = str(source or "").lower() in {"rules", "rule-based", "local"} or \
            str(model or "").lower() in {"rules", "rule-based", "local-rules"}
        if event.get("kind") == "usage":
            live_calls += int(not is_local)
        elif not usage_events and not is_local:
            live_calls += max(1, int(payload.get("attempts") or 0))

    return {
        "names": sorted(names),
        "live_calls": live_calls,
        "cost_usd": cost_usd,
    }


def _incident_notes(
    incident: dict[str, Any],
    events: list[dict[str, Any]],
    faults: list[dict[str, Any]],
) -> dict[str, Any]:
    incident_id = _incident_id(incident)
    payload = incident.get("payload", {})
    confirmed_faults = payload.get("candidate_faults") or []
    if isinstance(confirmed_faults, str):
        confirmed_faults = [confirmed_faults]
    fault_kind = str(confirmed_faults[0]) if confirmed_faults else "unknown"
    confirmed_at = _as_datetime(incident["ts"])

    preceding_faults = [
        fault for fault in faults
        if fault.get("end_wall")
        and _as_datetime(fault["end_wall"]) <= confirmed_at
    ]
    preceding_fault = max(
        preceding_faults,
        key=lambda fault: _as_datetime(fault["end_wall"]),
        default=None,
    )
    if preceding_fault:
        preceding = {
            "fault_id": preceding_fault.get("fault_id", "unknown"),
            "kind": preceding_fault.get("fault", "unknown"),
            "seconds_before_confirmation": (
                confirmed_at - _as_datetime(preceding_fault["end_wall"])
            ).total_seconds(),
        }
    else:
        preceding = None

    related = [event for event in events if _incident_id(event) == incident_id]
    related.sort(key=lambda event: int(event.get("seq", 0)))
    actions: list[str] = []
    executions = [event for event in related if event.get("kind") == "execution"]
    verifications = [event for event in related if event.get("kind") == "verification"]
    for execution in executions:
        execution_payload = execution.get("payload", {})
        execution_seq = int(execution.get("seq", 0))
        verification = next(
            (
                event for event in verifications
                if int(event.get("seq", 0)) > execution_seq
            ),
            None,
        )
        outcome = f"execution {execution_payload.get('status', 'unknown')}"
        if verification:
            outcome += f", verification {verification.get('payload', {}).get('status', 'unknown')}"
        actions.append(f"{execution_payload.get('action', 'unknown')} ({outcome})")
    for rollback in (event for event in related if event.get("kind") == "rollback"):
        actions.append(
            f"rollback ({'restored' if rollback.get('payload', {}).get('ok') else 'failed'})"
        )

    closed_event = next(
        (event for event in related if event.get("kind") == "closed"),
        None,
    )
    state_events = [event for event in related if event.get("kind") == "state"]
    closing_state = None
    if state_events:
        closing_state = state_events[-1].get("payload", {}).get("to")
    needs_human_event = next(
        (
            event for event in state_events
            if event.get("payload", {}).get("to") == "NEEDS_HUMAN"
        ),
        None,
    )
    if closed_event:
        closing_state = closed_event.get("payload", {}).get("state") or closing_state
        closed_after_s = (
            _as_datetime(closed_event["ts"]) - confirmed_at
        ).total_seconds()
        seconds_from_needs_human_to_closure = (
            (
                _as_datetime(closed_event["ts"])
                - _as_datetime(needs_human_event["ts"])
            ).total_seconds()
            if needs_human_event else None
        )
    else:
        closed_after_s = None
        seconds_from_needs_human_to_closure = None

    return {
        "incident_id": incident_id or "unknown",
        "fault_kind": fault_kind,
        "confirmed_at_utc": confirmed_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seconds_since_preceding_fault_end": preceding,
        "actions": actions,
        "closing_state": closing_state,
        "seconds_until_closure": closed_after_s,
        "seconds_from_needs_human_to_closure": seconds_from_needs_human_to_closure,
    }


def _faults_without_incidents(
    faults: list[dict[str, Any]],
    detected_fault_ids: set[str],
    requested_duration_s: float,
    run_end_wall: str | None,
) -> list[dict[str, Any]]:
    unobserved = []
    for fault in faults:
        fault_id = str(fault.get("fault_id", "unknown"))
        if fault_id in detected_fault_ids:
            continue
        start_wall = _as_datetime(fault["start_wall"])
        end_wall = fault.get("end_wall") or run_end_wall
        active_duration_s = (
            max(0.0, (_as_datetime(end_wall) - start_wall).total_seconds())
            if end_wall else 0.0
        )
        started_elapsed_s = float(
            fault.get("started_elapsed_s", fault.get("scheduled_start_s", 0.0))
        )
        unobserved.append({
            "fault_id": fault_id,
            "kind": str(fault.get("fault", "unknown")),
            "active_duration_s": active_duration_s,
            "started_elapsed_s": started_elapsed_s,
            "started_at_or_after_requested_duration": (
                started_elapsed_s >= requested_duration_s
            ),
        })
    return unobserved


def evaluate_events(
    events: list[dict[str, Any]],
    *,
    required_duration_s: float = REQUIRED_DURATION_S,
) -> dict[str, Any]:
    """Evaluate soak gates and evidence coverage from EventStore-shaped records."""
    run_starts = [e for e in events if e.get("kind") == "soak_run"
                  and e.get("payload", {}).get("phase") == "start"]
    run_ends = [e for e in events if e.get("kind") == "soak_run"
                and e.get("payload", {}).get("phase") == "end"]
    start_payload = run_starts[0]["payload"] if run_starts else {}
    end_payload = run_ends[-1]["payload"] if run_ends else {}
    sample_events = [e for e in events if e.get("kind") == "soak_sample"]
    duration_s = float(
        end_payload.get(
            "elapsed_s",
            max(
                (float(e.get("payload", {}).get("elapsed_s", 0.0)) for e in sample_events),
                default=0.0,
            ),
        )
    )
    requested_duration_s = float(start_payload.get("requested_duration_s") or 0.0)
    sample_s_value = start_payload.get("sample_s")
    sample_s = float(sample_s_value) if sample_s_value is not None else None
    complete = bool(end_payload.get("completed", False))
    errors = [e for e in events if e.get("kind") in {"error", "exception", "soak_error"}]
    gate_a = complete and not errors

    samples = [e["payload"] for e in sample_events]
    sample_elapsed = []
    malformed_sample_time = False
    for sample in samples:
        try:
            sample_elapsed.append(float(sample["elapsed_s"]))
        except (KeyError, TypeError, ValueError):
            malformed_sample_time = True
    sample_elapsed.sort()
    coverage_gaps = []
    if sample_elapsed:
        coverage_gaps.append(sample_elapsed[0])
        coverage_gaps.extend(
            current - previous
            for previous, current in zip(sample_elapsed, sample_elapsed[1:], strict=False)
        )
        coverage_gaps.append(duration_s - sample_elapsed[-1])
    maximum_gap_s = max(coverage_gaps) if coverage_gaps else None
    maximum_gap_allowed_s = 2.0 * sample_s if sample_s is not None else None
    sample_coverage_pass = bool(
        run_starts
        and run_ends
        and sample_elapsed
        and not malformed_sample_time
        and all(0.0 <= elapsed <= duration_s for elapsed in sample_elapsed)
        and maximum_gap_allowed_s is not None
        and maximum_gap_allowed_s > 0.0
        and maximum_gap_s is not None
        and maximum_gap_s <= maximum_gap_allowed_s
    )
    sample_coverage = {
        "sample_count": len(sample_events),
        "sample_interval_s": sample_s,
        "maximum_gap_s": maximum_gap_s,
        "maximum_allowed_gap_s": maximum_gap_allowed_s,
        "pass": sample_coverage_pass,
    }
    duration_qualified = (
        requested_duration_s >= required_duration_s
        and duration_s >= requested_duration_s
    )
    duration_qualification = {
        "observed_duration_s": duration_s,
        "requested_duration_s": requested_duration_s,
        "required_duration_s": required_duration_s,
        "pass": duration_qualified,
    }

    baseline = [s for s in samples if 1800 <= float(s.get("elapsed_s", -1)) < 3600]
    last = [s for s in samples
            if max(0.0, duration_s - 1800) <= float(s.get("elapsed_s", -1)) <= duration_s + 1]
    rss_base = [float(s["rss_mb"]) for s in baseline if s.get("rss_mb") is not None]
    rss_last = [float(s["rss_mb"]) for s in last if s.get("rss_mb") is not None]
    thread_base = [int(s["thread_count"]) for s in baseline if s.get("thread_count") is not None]
    fd_base = [int(s["fd_count"]) for s in baseline if s.get("fd_count") is not None]
    final_sample = max(samples, key=lambda s: float(s.get("elapsed_s", -1))) if samples else None
    leak_details: dict[str, Any] = {
        "baseline_rss_median_mb": statistics.median(rss_base) if rss_base else None,
        "last_rss_median_mb": statistics.median(rss_last) if rss_last else None,
        "rss_growth_mb": None,
        "rss_growth_limit_mb": None,
        "baseline_thread_max": max(thread_base) if thread_base else None,
        "baseline_fd_max": max(fd_base) if fd_base else None,
        "final_thread_count": final_sample.get("thread_count") if final_sample else None,
        "final_fd_count": final_sample.get("fd_count") if final_sample else None,
    }
    rss_ok = False
    if rss_base and rss_last:
        base_median = leak_details["baseline_rss_median_mb"]
        growth = leak_details["last_rss_median_mb"] - base_median
        limit = max(32.0, 0.10 * base_median)
        leak_details.update(rss_growth_mb=growth, rss_growth_limit_mb=limit)
        rss_ok = growth <= limit
    thread_ok = bool(thread_base and final_sample and
                     final_sample.get("thread_count") is not None and
                     final_sample["thread_count"] <= max(thread_base) + 2)
    fd_ok = bool(fd_base and final_sample and final_sample.get("fd_count") is not None and
                 final_sample["fd_count"] <= max(fd_base) + 2)
    gate_b: bool | None = rss_ok and thread_ok and fd_ok if rss_base and rss_last else None

    faults = _event_fault_windows(events)
    incidents = [e for e in events if e.get("kind") == "incident"]
    unmatched: list[dict[str, Any]] = []
    detected_faults: set[str] = set()
    for incident in incidents:
        incident_start = _as_datetime(incident["ts"])
        matched = None
        for fault in faults:
            fault_start = _as_datetime(fault["start_wall"])
            fault_end = _as_datetime(fault.get("end_wall") or fault["start_wall"])
            if fault_start - timedelta(seconds=5) <= incident_start <= \
                    fault_end + timedelta(seconds=60):
                matched = fault
                break
        if matched is None:
            unmatched.append(incident)
        else:
            detected_faults.add(str(matched.get("fault_id")))
    run_hours = duration_s / 3600.0
    false_alarms_per_hour = len(unmatched) / run_hours if run_hours > 0 else None
    gate_c = false_alarms_per_hour is not None and false_alarms_per_hour <= 1.0
    detection_rate = len(detected_faults) / len(faults) if faults else None
    gate_d = {
        "injected_faults": len(faults),
        "faults_with_confirmed_incident": len(detected_faults),
        "rate": detection_rate,
        "gate": False,
    }
    run_end_event = run_ends[-1] if run_ends else None
    run_end_wall = (
        end_payload.get("ended_wall")
        or (run_end_event.get("ts") if run_end_event else None)
    )
    unmatched_notes = [
        _incident_notes(incident, events, faults) for incident in unmatched
    ]
    undetected_fault_notes = _faults_without_incidents(
        faults, detected_faults, requested_duration_s, run_end_wall
    )
    planner_summary = _planner_summary(events)
    return {
        "label": "SIMULATION",
        "code_revision": start_payload.get("code_revision", "unknown"),
        "duration_s": duration_s,
        "duration_complete": complete,
        "duration_qualification": duration_qualification,
        "sample_coverage": sample_coverage,
        "gates": {
            "no_crash": {"pass": gate_a, "error_events": len(errors)},
            "no_sustained_leak": {"pass": gate_b, **leak_details},
            "false_alarms_per_hour": {
                "pass": gate_c,
                "count": len(unmatched),
                "rate": false_alarms_per_hour,
                "limit_per_hour": 1.0,
            },
            "detection": gate_d,
        },
        "faults": faults,
        "false_alarm_incident_ids": [e.get("incident_id") for e in unmatched],
        "unmatched_incidents": unmatched_notes,
        "faults_without_incident": undetected_fault_notes,
        "planner_summary": planner_summary,
        "overall_pass": (
            duration_qualified
            and sample_coverage_pass
            and gate_a is True
            and gate_b is True
            and gate_c is True
        ),
    }


def render_report(report: dict[str, Any]) -> str:
    gates = report["gates"]
    fmt = lambda value: "n/a" if value is None else f"{value:.3f}"  # noqa: E731
    coverage = report["sample_coverage"]
    duration = report["duration_qualification"]
    planner = report["planner_summary"]
    planner_names = ", ".join(planner["names"]) if planner["names"] else "none observed"
    lines = [
        "# F10 soak report — SIMULATION",
        "",
        f"- code revision: `{report['code_revision']}`",
        f"- database SHA-256: `{report.get('database_sha256', 'unavailable')}`",
        f"- regenerate command: `{report.get('regenerate_command', 'unavailable')}`",
        f"- duration: {report['duration_s'] / 3600:.4f} h",
        f"- complete: {'yes' if report['duration_complete'] else 'no'}",
        "",
        "| Gate | Result | Details |",
        "|---|---|---|",
        f"| No crash (A) | {'PASS' if gates['no_crash']['pass'] else 'FAIL'} | "
        f"{gates['no_crash']['error_events']} error/exception events |",
        f"| Sustained leak (B) | "
        f"{'PASS' if gates['no_sustained_leak']['pass'] is True else 'FAIL'} | "
        f"RSS growth {fmt(gates['no_sustained_leak']['rss_growth_mb'])} MB "
        f"(limit {fmt(gates['no_sustained_leak']['rss_growth_limit_mb'])} MB); "
        f"threads {gates['no_sustained_leak']['final_thread_count']}; "
        f"fds {gates['no_sustained_leak']['final_fd_count']} |",
        f"| False alarms (C) | "
        f"{'PASS' if gates['false_alarms_per_hour']['pass'] else 'FAIL'} | "
        f"{fmt(gates['false_alarms_per_hour']['rate'])}/h "
        f"(maximum 1.000/h) |",
        f"| Duration | {'PASS' if duration['pass'] else 'FAIL'} | "
        f"observed {duration['observed_duration_s']:.3f} s; "
        f"requested {duration['requested_duration_s']:.3f} s; "
        f"minimum {duration['required_duration_s']:.3f} s |",
        f"| Sample coverage | {'PASS' if coverage['pass'] else 'FAIL'} | "
        f"{coverage['sample_count']} samples at {fmt(coverage['sample_interval_s'])} s; "
        f"maximum gap "
        f"{fmt(coverage['maximum_gap_s'])} s "
        f"(maximum {fmt(coverage['maximum_allowed_gap_s'])} s) |",
        f"| Detection (reported, not gated) | "
        f"{fmt(gates['detection']['rate'])} | "
        f"{gates['detection']['faults_with_confirmed_incident']}/"
        f"{gates['detection']['injected_faults']} faults |",
        "",
        f"Overall: **{'PASS' if report['overall_pass'] else 'NOT PASSED'}**",
        "",
        "## Notes (SIMULATION)",
    ]
    for incident in report["unmatched_incidents"]:
        preceding = incident["seconds_since_preceding_fault_end"]
        if preceding:
            since_text = (
                f"{preceding['seconds_before_confirmation']:.3f} s after "
                f"{preceding['fault_id']} ({preceding['kind']}) ended"
            )
        else:
            since_text = "no preceding fault end was recorded"
        actions_text = "; ".join(incident["actions"]) if incident["actions"] else "none recorded"
        if incident["seconds_until_closure"] is None:
            closure_text = "not closed"
        else:
            closure_text = (
                f"closed {incident['closing_state'] or 'unknown'} "
                f"{incident['seconds_until_closure']:.3f} s later"
            )
            after_needs_human = incident["seconds_from_needs_human_to_closure"]
            if after_needs_human is not None:
                closure_text += f" ({after_needs_human:.3f} s after NEEDS_HUMAN)"
        lines.append(
            f"- Unmatched incident {incident['incident_id']}: confirmed "
            f"{incident['fault_kind']} at {incident['confirmed_at_utc']}, {since_text}; "
            f"actions: {actions_text}; {closure_text}."
        )
    for fault in report["faults_without_incident"]:
        started = "yes" if fault["started_at_or_after_requested_duration"] else "no"
        lines.append(
            f"- Fault {fault['fault_id']} ({fault['kind']}) had no incident; active for "
            f"{fault['active_duration_s']:.3f} s; started at or after requested duration: "
            f"{started}."
        )
    lines.append(
        "- Detection is informational (`gate: false`); the F10 detection minimum is evidenced "
        "by A1 in docs/evidence/f10/experiments.md"
    )
    lines.append(
        f"- Planner: {planner_names}, live calls {planner['live_calls']}, "
        f"cost USD {planner['cost_usd']:.6f}"
    )
    return "\n".join(lines)


def _default_out() -> Path:
    stamp = _wall_now().strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "benchmarks" / "reports" / f"soak-{stamp}"


def run_soak(*, hours: float = 4.0, out: str | Path | None = None, sample_s: float = 60.0,
             seed: int = 0, schedule_period_s: float = 600.0,
             fault_duration_s: float = 60.0, first_fault_s: float = 600.0) -> Path:
    if hours <= 0 or sample_s <= 0 or schedule_period_s <= 0 or fault_duration_s <= 0:
        raise ValueError("hours, sample interval, schedule period, and fault duration must be > 0")
    out_dir = Path(out) if out is not None else _default_out()
    if out_dir.exists():
        allowed = {"soak.log"}
        if (not out_dir.is_dir()
                or any(path.name not in allowed for path in out_dir.iterdir())):
            raise FileExistsError(f"soak output directory already contains data: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=False)
    db_path = out_dir / "soak.sqlite"
    if db_path.exists():
        raise FileExistsError(f"soak database already exists: {db_path}")
    duration_s = hours * 3600.0
    cfg = load_config(env=False)
    source: SyntheticSource | None = None
    source_settings: dict[str, Any] | None = None
    source_index = 0
    planner = RuleBasedPlanner()
    store = EventStore(db_path)
    start_mono = time.monotonic()
    start_wall = _wall_now()
    deadline = start_mono + duration_s
    rng = random.Random(seed)
    window_count = 0
    sample_due = sample_s
    fault_index = 0
    active_fault: dict[str, Any] | None = None
    store.append("soak_run", {
        "phase": "start",
        "label": "SIMULATION",
        "code_revision": _code_revision(ROOT),
        "requested_duration_s": duration_s,
        "sample_s": sample_s,
        "seed": seed,
        "started_wall": _iso(start_wall),
    })

    def finish_fault(elapsed: float, reason: str) -> None:
        nonlocal active_fault
        if active_fault is None:
            return
        assert source is not None
        source.set_fault(None)
        settings_reset = reason in {"duration", "run_end"}
        if settings_reset:  # end of the scripted episode: scene and camera back to pre-fault state
            source.apply_settings(dict(active_fault["settings_before"]))
        end_wall = _wall_now()
        store.append("soak_fault", {
            **active_fault,
            "phase": "end",
            "end_wall": _iso(end_wall),
            "elapsed_end_s": elapsed,
            "clear_reason": reason,
            "settings_reset": settings_reset,
            "label": "SIMULATION",
        })
        active_fault = None

    def on_window(_tw, _agent) -> None:
        nonlocal window_count, sample_due, fault_index, active_fault
        window_count += 1
        elapsed = time.monotonic() - start_mono
        if active_fault:
            actions = store.events(kind="execution")
            applied = any(
                event["seq"] > active_fault["start_seq"]
                and event["payload"].get("status") == "success"
                and event["payload"].get("action")
                in REMEDIATIONS[active_fault["fault"]]
                for event in actions
            )
            if applied:
                finish_fault(elapsed, "remediation_applied")
            elif elapsed >= active_fault["started_elapsed_s"] + fault_duration_s:
                finish_fault(elapsed, "duration")
        if (active_fault is None and elapsed < duration_s
                and elapsed >= first_fault_s + fault_index * schedule_period_s):
            fault, strength = FAULTS[fault_index % len(FAULTS)]
            fault_id = f"fault-{fault_index:04d}"
            fault_seed = rng.randrange(0, 2**32)
            start = _wall_now()
            settings = source.get_settings()
            active_fault = {
                "fault_id": fault_id,
                "fault": fault,
                "strength": strength,
                "seed": fault_seed,
                "scheduled_start_s": first_fault_s + fault_index * schedule_period_s,
                "started_elapsed_s": elapsed,
                "start_wall": _iso(start),
                "scheduled_end_wall": _iso(start + timedelta(seconds=fault_duration_s)),
                "focus_ok": settings.get("focus_ok", True),
                "settings_before": settings,
                "start_seq": store.events()[-1]["seq"] if store.events() else 0,
            }
            source.set_fault(fault, strength)
            store.append("soak_fault", {
                **active_fault, "phase": "start", "label": "SIMULATION",
            })
            active_fault["start_seq"] = store.events()[-1]["seq"]
            fault_index += 1
        while elapsed >= sample_due:
            _sample(store, db_path, elapsed, window_count)
            sample_due += sample_s

    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            source = SyntheticSource(
                width=640,
                height=480,
                seed=seed + source_index,
            )
            source_index += 1
            if source_settings is not None:
                source.apply_settings(source_settings)
            if active_fault is not None:
                source.set_fault(active_fault["fault"], active_fault["strength"])
            try:
                try:
                    run_live(
                        cfg,
                        duration_s=remaining,
                        on_window=on_window,
                        store=store,
                        source=source,
                        planner=planner,
                    )
                finally:
                    source_settings = source.get_settings()
                    source.close()
                if time.monotonic() < deadline:
                    store.append("soak_error", {
                        "error_type": "RuntimeError",
                        "message": "run_live returned before the requested duration",
                        "label": "SIMULATION",
                    })
                    time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                else:
                    break
            except Exception as exc:  # keep the soak alive, but the no-crash gate will fail
                store.append("soak_error", {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "label": "SIMULATION",
                })
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        elapsed = time.monotonic() - start_mono
        finish_fault(elapsed, "run_end")
        _sample(store, db_path, elapsed, window_count, final=True)
        store.append("soak_run", {
            "phase": "end",
            "label": "SIMULATION",
            "completed": elapsed >= duration_s,
            "elapsed_s": elapsed,
            "ended_wall": _iso(_wall_now()),
        })
    finally:
        if source is not None:
            source.close()
        store.close()
    return db_path


def _code_revision(root: Path) -> str:
    from spike_static_scene import code_revision

    return code_revision(root)


def report_database(db_path: str | Path) -> dict[str, Any]:
    """Read the EventStore database and derive the report without rerunning the soak."""
    import sqlite3

    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    uri = f"{db_path.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute("SELECT seq, ts, incident_id, kind, payload FROM events ORDER BY seq")
        events = [
            {"seq": seq, "ts": ts, "incident_id": incident_id, "kind": kind,
             "payload": json.loads(payload)}
            for seq, ts, incident_id, kind, payload in rows.fetchall()
        ]
    report = evaluate_events(events)
    if report["code_revision"] == "unknown":
        report["code_revision"] = _code_revision(ROOT)
    digest = hashlib.sha256()
    with db_path.open("rb") as database_file:
        for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
            digest.update(chunk)
    output_dir = db_path.parent

    def command_path(path: Path) -> str:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return str(path)

    report["database_sha256"] = digest.hexdigest()
    report["regenerate_command"] = (
        "python scripts/soak_report.py "
        f"--db {shlex.quote(command_path(db_path))} "
        f"--out-dir {shlex.quote(command_path(output_dir))}"
    )
    return report
