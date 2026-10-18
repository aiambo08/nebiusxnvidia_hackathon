"""SIMULATION: the F10 soak report classifies EventStore records."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from benchmarks.soak import evaluate_events, report_database, run_soak


def _event(seq: int, at: datetime, kind: str, payload: dict, incident_id=None) -> dict:
    return {
        "seq": seq,
        "ts": at.isoformat(),
        "incident_id": incident_id,
        "kind": kind,
        "payload": payload,
    }


def _clean_events() -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        _event(1, start, "soak_run", {
            "phase": "start", "code_revision": "abc123", "requested_duration_s": 14400,
        }),
        _event(2, start + timedelta(minutes=10), "soak_fault", {
            "phase": "start", "fault_id": "fault-0000", "fault": "dark",
            "start_wall": (start + timedelta(minutes=10)).isoformat(),
        }),
        _event(3, start + timedelta(minutes=11), "soak_fault", {
            "phase": "end", "fault_id": "fault-0000",
            "start_wall": (start + timedelta(minutes=10)).isoformat(),
            "end_wall": (start + timedelta(minutes=11)).isoformat(),
        }),
        _event(4, start + timedelta(minutes=10, seconds=30), "incident", {
            "incident_id": "inc-1",
        }, "inc-1"),
    ]
    seq = 5
    for elapsed, rss, threads, fds in (
        (1800, 100.0, 8, 18),
        (2400, 102.0, 9, 19),
        (3599, 101.0, 8, 18),
        (12600, 108.0, 9, 20),
        (13200, 109.0, 9, 20),
        (14399, 110.0, 9, 19),
        (14400, 110.0, 9, 19),
    ):
        events.append(_event(seq, start + timedelta(seconds=elapsed), "soak_sample", {
            "elapsed_s": elapsed,
            "rss_mb": rss,
            "thread_count": threads,
            "fd_count": fds,
        }))
        seq += 1
    events.append(_event(seq, start + timedelta(hours=4), "soak_run", {
        "phase": "end", "completed": True, "elapsed_s": 14400,
    }))
    return events


def test_soak_report_passes_clean_event_list():
    report = evaluate_events(_clean_events())
    assert report["gates"]["no_crash"]["pass"] is True
    assert report["gates"]["no_sustained_leak"]["pass"] is True
    assert report["gates"]["false_alarms_per_hour"]["pass"] is True
    assert report["gates"]["detection"]["rate"] == 1.0
    assert report["overall_pass"] is True


def test_soak_report_fails_sustained_rss_leak():
    events = _clean_events()
    for event in events:
        if event["kind"] == "soak_sample" and event["payload"]["elapsed_s"] >= 12600:
            event["payload"]["rss_mb"] = 150.0
    report = evaluate_events(events)
    assert report["gates"]["no_sustained_leak"]["pass"] is False
    assert report["gates"]["no_sustained_leak"]["rss_growth_mb"] > 32


def test_soak_report_fails_false_alarms_outside_fault_margins():
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    for index in range(5):
        at = start + timedelta(hours=index * 0.5 + 1)
        events.append(_event(100 + index, at, "incident", {
            "incident_id": f"false-{index}",
        }, f"false-{index}"))
    report = evaluate_events(events)
    assert report["gates"]["false_alarms_per_hour"]["rate"] == 1.25
    assert report["gates"]["false_alarms_per_hour"]["pass"] is False


def test_soak_report_fails_error_event():
    events = _clean_events()
    events.append(_event(200, datetime(2026, 1, 1, 1, tzinfo=UTC), "error", {
        "message": "simulated failure",
    }))
    report = evaluate_events(events)
    assert report["gates"]["no_crash"]["pass"] is False


def test_soak_smoke_uses_live_runtime_and_writes_event_database(tmp_path):
    out = tmp_path / "smoke"
    out.mkdir()
    (out / "soak.log").write_text("", encoding="utf-8")
    db_path = run_soak(
        hours=0.002,
        out=out,
        sample_s=1,
        seed=11,
        schedule_period_s=2,
        fault_duration_s=1,
        first_fault_s=1,
    )
    report = report_database(db_path)
    assert report["duration_complete"] is True
    assert report["duration_s"] >= 7.2
    assert report["faults"]
    assert any(event["kind"] == "soak_sample" for event in _load_events(db_path))
    assert report["code_revision"] != "unknown"


def _load_events(db_path):
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT seq, ts, incident_id, kind, payload FROM events ORDER BY seq")
        return [
            {"seq": seq, "ts": ts, "incident_id": incident_id, "kind": kind,
             "payload": json.loads(payload)}
            for seq, ts, incident_id, kind, payload in rows.fetchall()
        ]
