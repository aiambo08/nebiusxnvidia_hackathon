"""Event-backed live-pipeline soak benchmark (SIMULATION)."""

from __future__ import annotations

import gc
import importlib.util
import json
import os
import random
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
REMEDIATIONS = {
    "dark": {"set_exposure_bounded"},
    "defocus": {"trigger_autofocus"},
    "freeze": {"restart_capture"},
    "overexpose": {"set_exposure_bounded"},
    "occlude": set(),
}
ROOT = Path(__file__).resolve().parents[1]


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


def evaluate_events(
    events: list[dict[str, Any]], duration_s: float | None = None
) -> dict[str, Any]:
    """Evaluate the preregistered gates from EventStore-shaped records only."""
    run_starts = [e for e in events if e.get("kind") == "soak_run"
                  and e.get("payload", {}).get("phase") == "start"]
    run_ends = [e for e in events if e.get("kind") == "soak_run"
                and e.get("payload", {}).get("phase") == "end"]
    start_payload = run_starts[0]["payload"] if run_starts else {}
    end_payload = run_ends[-1]["payload"] if run_ends else {}
    if duration_s is None:
        duration_s = float(end_payload.get("elapsed_s",
                                           start_payload.get("requested_duration_s", 0.0)))
    complete = bool(end_payload.get("completed", False))
    errors = [e for e in events if e.get("kind") in {"error", "exception", "soak_error"}]
    gate_a = complete and not errors

    samples = [e["payload"] for e in events if e.get("kind") == "soak_sample"]
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
    return {
        "label": "SIMULATION",
        "code_revision": start_payload.get("code_revision", "unknown"),
        "duration_s": duration_s,
        "duration_complete": complete,
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
        "overall_pass": gate_a and gate_b is True and gate_c,
    }


def render_report(report: dict[str, Any]) -> str:
    gates = report["gates"]
    fmt = lambda value: "n/a" if value is None else f"{value:.3f}"  # noqa: E731
    lines = [
        "# F10 soak report — SIMULATION",
        "",
        f"- code revision: `{report['code_revision']}`",
        f"- duration: {report['duration_s'] / 3600:.4f} h",
        f"- complete: {report['duration_complete']}",
        "",
        "| Gate | Result | Details |",
        "|---|---:|---|",
        f"| No crash | {'PASS' if gates['no_crash']['pass'] else 'FAIL'} | "
        f"{gates['no_crash']['error_events']} error/exception events |",
        f"| Sustained leak | {gates['no_sustained_leak']['pass']} | "
        f"RSS growth {fmt(gates['no_sustained_leak']['rss_growth_mb'])} MB "
        f"(limit {fmt(gates['no_sustained_leak']['rss_growth_limit_mb'])} MB); "
        f"threads {gates['no_sustained_leak']['final_thread_count']}; "
        f"fds {gates['no_sustained_leak']['final_fd_count']} |",
        f"| False alarms | {'PASS' if gates['false_alarms_per_hour']['pass'] else 'FAIL'} | "
        f"{fmt(gates['false_alarms_per_hour']['rate'])}/h "
        f"(limit 1.000/h) |",
        f"| Detection (reported, not gated) | "
        f"{fmt(gates['detection']['rate'])} | "
        f"{gates['detection']['faults_with_confirmed_incident']}/"
        f"{gates['detection']['injected_faults']} faults |",
        "",
        f"Overall: **{'PASS' if report['overall_pass'] else 'NOT PASSED'}**",
        "",
    ]
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
    source = SyntheticSource(width=640, height=480, seed=seed)
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
        source.set_fault(None)
        if reason in {"duration", "run_end"} and active_fault["fault"] == "defocus":
            source.apply_settings({"focus_ok": active_fault["focus_ok"]})
        end_wall = _wall_now()
        store.append("soak_fault", {
            **active_fault,
            "phase": "end",
            "end_wall": _iso(end_wall),
            "elapsed_end_s": elapsed,
            "clear_reason": reason,
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
        if active_fault is None and elapsed >= first_fault_s + fault_index * schedule_period_s:
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
            try:
                run_live(
                    cfg,
                    duration_s=remaining,
                    on_window=on_window,
                    store=store,
                    source=source,
                    planner=planner,
                )
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
    return report
