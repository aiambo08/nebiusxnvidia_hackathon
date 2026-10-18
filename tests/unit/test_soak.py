"""SIMULATION: the F10 soak report classifies EventStore records."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from benchmarks import soak as soak_module
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
    specifications = [
        (0, 0, "soak_run", {
            "phase": "start",
            "code_revision": "abc123",
            "requested_duration_s": 14400,
            "sample_s": 60,
        }, None),
        (600, 0, "soak_fault", {
            "phase": "start", "fault_id": "fault-0000", "fault": "dark",
            "started_elapsed_s": 600,
            "start_wall": (start + timedelta(seconds=600)).isoformat(),
        }, None),
        (630, 0, "incident", {
            "incident_id": "inc-1",
            "candidate_faults": ["dark"],
            "state": "CONFIRMED",
        }, "inc-1"),
        (660, 0, "soak_fault", {
            "phase": "end", "fault_id": "fault-0000",
            "start_wall": (start + timedelta(seconds=600)).isoformat(),
            "end_wall": (start + timedelta(seconds=660)).isoformat(),
        }, None),
    ]
    for elapsed in range(60, 14401, 60):
        rss = 110.0 if elapsed >= 12600 else 100.0
        threads = 9 if elapsed >= 12600 else 8
        fds = 19 if elapsed >= 12600 else 18
        specifications.append((elapsed, 1, "soak_sample", {
            "elapsed_s": elapsed,
            "rss_mb": rss,
            "thread_count": threads,
            "fd_count": fds,
        }, None))
    specifications.append((14400, 2, "soak_run", {
        "phase": "end",
        "completed": True,
        "elapsed_s": 14400,
        "ended_wall": (start + timedelta(seconds=14400)).isoformat(),
    }, None))
    specifications.sort(key=lambda event: (event[0], event[1]))
    return [
        _event(seq, start + timedelta(seconds=elapsed), kind, payload, incident_id)
        for seq, (elapsed, _order, kind, payload, incident_id) in enumerate(specifications, 1)
    ]


def test_soak_report_passes_clean_event_list():
    report = evaluate_events(_clean_events())
    assert report["gates"]["no_crash"]["pass"] is True
    assert report["gates"]["no_sustained_leak"]["pass"] is True
    assert report["gates"]["false_alarms_per_hour"]["pass"] is True
    assert report["gates"]["detection"]["rate"] == 1.0
    assert report["sample_coverage"]["pass"] is True
    assert report["overall_pass"] is True
    markdown = soak_module.render_report(report)
    assert "| Sustained leak (B) | PASS |" in markdown
    assert "| False alarms (C) | PASS |" in markdown
    assert "(maximum 1.000/h)" in markdown
    assert "| Sustained leak (B) | True |" not in markdown


def test_soak_report_fails_sustained_rss_leak():
    events = _clean_events()
    for event in events:
        if event["kind"] == "soak_sample" and event["payload"]["elapsed_s"] >= 12600:
            event["payload"]["rss_mb"] = 150.0
    report = evaluate_events(events)
    assert report["gates"]["no_sustained_leak"]["pass"] is False
    assert report["gates"]["no_sustained_leak"]["rss_growth_mb"] > 32
    assert report["overall_pass"] is False


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


def test_thread_growth_of_two_passes_and_three_fails():
    events = _clean_events()
    baseline_max = max(
        event["payload"]["thread_count"]
        for event in events
        if event["kind"] == "soak_sample"
        and 1800 <= event["payload"]["elapsed_s"] < 3600
    )
    final_sample = max(
        (event for event in events if event["kind"] == "soak_sample"),
        key=lambda event: event["payload"]["elapsed_s"],
    )
    final_sample["payload"]["thread_count"] = baseline_max + 2
    assert evaluate_events(events)["gates"]["no_sustained_leak"]["pass"] is True
    final_sample["payload"]["thread_count"] = baseline_max + 3
    assert evaluate_events(events)["gates"]["no_sustained_leak"]["pass"] is False


def test_fd_growth_of_two_passes_and_three_fails():
    events = _clean_events()
    baseline_max = max(
        event["payload"]["fd_count"]
        for event in events
        if event["kind"] == "soak_sample"
        and 1800 <= event["payload"]["elapsed_s"] < 3600
    )
    final_sample = max(
        (event for event in events if event["kind"] == "soak_sample"),
        key=lambda event: event["payload"]["elapsed_s"],
    )
    final_sample["payload"]["fd_count"] = baseline_max + 2
    assert evaluate_events(events)["gates"]["no_sustained_leak"]["pass"] is True
    final_sample["payload"]["fd_count"] = baseline_max + 3
    assert evaluate_events(events)["gates"]["no_sustained_leak"]["pass"] is False


def test_baseline_window_starts_at_1800_seconds():
    events = _clean_events()
    for event in events:
        if event["kind"] == "soak_sample" and event["payload"]["elapsed_s"] < 1800:
            event["payload"]["rss_mb"] = 0.0
    start = datetime.fromisoformat(events[0]["ts"])
    events.append(_event(
        1000,
        start,
        "soak_sample",
        {"elapsed_s": 0, "rss_mb": 0.0, "thread_count": 8, "fd_count": 18},
    ))
    report = evaluate_events(events)
    assert report["gates"]["no_sustained_leak"]["baseline_rss_median_mb"] == 100.0
    assert report["gates"]["no_sustained_leak"]["pass"] is True


def test_final_rss_window_is_not_the_entire_run():
    events = _clean_events()
    for event in events:
        if event["kind"] == "soak_sample":
            elapsed = event["payload"]["elapsed_s"]
            if 3600 <= elapsed < 12600:
                event["payload"]["rss_mb"] = 150.0
    report = evaluate_events(events)
    leak = report["gates"]["no_sustained_leak"]
    assert leak["baseline_rss_median_mb"] == 100.0
    assert leak["last_rss_median_mb"] == 110.0
    assert leak["pass"] is True


def test_incident_matching_start_boundary_is_inclusive_at_minus_five_seconds():
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    events.extend([
        _event(1001, start + timedelta(seconds=595), "incident",
               {"incident_id": "start-boundary"}, "start-boundary"),
        _event(1002, start + timedelta(seconds=594.9), "incident",
               {"incident_id": "start-outside"}, "start-outside"),
    ])
    report = evaluate_events(events)
    assert "start-boundary" not in report["false_alarm_incident_ids"]
    assert "start-outside" in report["false_alarm_incident_ids"]


def test_incident_matching_end_boundary_is_inclusive_at_plus_sixty_seconds():
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    events.extend([
        _event(1001, start + timedelta(seconds=720), "incident",
               {"incident_id": "end-boundary"}, "end-boundary"),
        _event(1002, start + timedelta(seconds=720.1), "incident",
               {"incident_id": "end-outside"}, "end-outside"),
    ])
    report = evaluate_events(events)
    assert "end-boundary" not in report["false_alarm_incident_ids"]
    assert "end-outside" in report["false_alarm_incident_ids"]


def test_incomplete_run_fails_no_crash_gate():
    events = _clean_events()
    run_end = next(event for event in events if event["kind"] == "soak_run"
                   and event["payload"]["phase"] == "end")
    run_end["payload"]["completed"] = False
    report = evaluate_events(events)
    assert report["gates"]["no_crash"]["pass"] is False
    assert report["overall_pass"] is False


def test_soak_error_counts_as_an_error_event():
    events = _clean_events()
    events.append(_event(1000, datetime(2026, 1, 1, 1, tzinfo=UTC), "soak_error", {
        "message": "run_live returned early",
    }))
    report = evaluate_events(events)
    assert report["gates"]["no_crash"]["error_events"] == 1
    assert report["gates"]["no_crash"]["pass"] is False


def _short_run_events(*, requested_duration_s: int = 14400) -> list[dict]:
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    observed_duration_s = 5400
    events = [
        event for event in events
        if event["kind"] != "soak_sample"
        or event["payload"]["elapsed_s"] <= observed_duration_s
    ]
    run_start = next(event for event in events if event["kind"] == "soak_run"
                     and event["payload"]["phase"] == "start")
    run_start["payload"]["requested_duration_s"] = requested_duration_s
    run_end = next(event for event in events if event["kind"] == "soak_run"
                   and event["payload"]["phase"] == "end")
    run_end["ts"] = (start + timedelta(seconds=observed_duration_s)).isoformat()
    run_end["payload"].update(
        elapsed_s=observed_duration_s,
        ended_wall=(start + timedelta(seconds=observed_duration_s)).isoformat(),
        completed=True,
    )
    return events


def test_overall_pass_fails_a_complete_but_one_and_a_half_hour_run():
    report = evaluate_events(_short_run_events())
    assert report["duration_qualification"]["observed_duration_s"] == 5400
    assert report["duration_qualification"]["pass"] is False
    assert report["overall_pass"] is False


def test_overall_pass_fails_when_requested_duration_is_below_required_minimum():
    events = _clean_events()
    run_start = next(event for event in events if event["kind"] == "soak_run"
                     and event["payload"]["phase"] == "start")
    run_start["payload"]["requested_duration_s"] = 14399
    report = evaluate_events(events)
    assert report["duration_qualification"]["pass"] is False
    assert report["overall_pass"] is False


def test_required_duration_override_is_keyword_only():
    events = _short_run_events(requested_duration_s=5400)
    report = evaluate_events(events, required_duration_s=5400)
    assert report["duration_qualification"]["pass"] is True
    assert report["overall_pass"] is True


def test_overall_pass_fails_for_two_sparse_samples():
    events = _clean_events()
    sample_events = [event for event in events if event["kind"] == "soak_sample"]
    keep = {sample_events[29]["payload"]["elapsed_s"], sample_events[-1]["payload"]["elapsed_s"]}
    events = [
        event for event in events
        if event["kind"] != "soak_sample" or event["payload"]["elapsed_s"] in keep
    ]
    report = evaluate_events(events)
    assert report["sample_coverage"]["sample_count"] == 2
    assert report["sample_coverage"]["pass"] is False
    assert report["overall_pass"] is False


def test_sample_coverage_includes_run_start_and_run_end():
    events = _clean_events()
    events = [
        event for event in events
        if event["kind"] != "soak_sample"
        or 1800 <= event["payload"]["elapsed_s"] <= 14400
    ]
    assert evaluate_events(events)["sample_coverage"]["pass"] is False

    events = _clean_events()
    events = [
        event for event in events
        if event["kind"] != "soak_sample"
        or event["payload"]["elapsed_s"] <= 14220
    ]
    assert evaluate_events(events)["sample_coverage"]["pass"] is False


def test_overall_pass_fails_when_leak_gate_is_none():
    events = _clean_events()
    for event in events:
        if event["kind"] == "soak_sample":
            event["payload"].pop("rss_mb")
    report = evaluate_events(events)
    assert report["sample_coverage"]["pass"] is True
    assert report["gates"]["no_sustained_leak"]["pass"] is None
    assert report["overall_pass"] is False


def test_median_rss_is_used_instead_of_minimum():
    events = _clean_events()
    baseline_samples = [
        event for event in events
        if event["kind"] == "soak_sample"
        and 1800 <= event["payload"]["elapsed_s"] < 3600
    ]
    final_samples = [
        event for event in events
        if event["kind"] == "soak_sample"
        and 12600 <= event["payload"]["elapsed_s"] <= 14400
    ]
    for index, event in enumerate(baseline_samples):
        event["payload"]["rss_mb"] = 100.0 if index == 0 else 200.0
    for event in final_samples:
        event["payload"]["rss_mb"] = 220.0
    leak = evaluate_events(events)["gates"]["no_sustained_leak"]
    assert leak["baseline_rss_median_mb"] == 200.0
    assert leak["last_rss_median_mb"] == 220.0
    assert leak["rss_growth_mb"] == 20.0
    assert leak["pass"] is True


def test_fault_matching_uses_payload_end_wall():
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    fault_end = next(
        event for event in events
        if event["kind"] == "soak_fault" and event["payload"]["phase"] == "end"
    )
    fault_end["ts"] = (start + timedelta(seconds=720.1)).isoformat()
    events.append(_event(
        1001,
        start + timedelta(seconds=720.1),
        "incident",
        {"incident_id": "after-payload-end"},
        "after-payload-end",
    ))
    report = evaluate_events(events)
    assert "after-payload-end" in report["false_alarm_incident_ids"]


def test_report_notes_are_generated_from_unmatched_events():
    events = _clean_events()
    start = datetime.fromisoformat(events[0]["ts"])
    incident_id = "unmatched-incident"
    events.extend([
        _event(1001, start + timedelta(seconds=1000), "incident", {
            "incident_id": incident_id,
            "candidate_faults": ["low_fps"],
        }, incident_id),
        _event(1002, start + timedelta(seconds=1000.1), "plan", {
            "source": "rules",
            "attempts": 0,
            "usage": {"model": "local-rules", "estimated_cost_usd": 0.0},
        }, incident_id),
        _event(1003, start + timedelta(seconds=1000.2), "execution", {
            "action": "switch_stream_profile",
            "status": "success",
        }, incident_id),
        _event(1004, start + timedelta(seconds=1001), "verification", {
            "status": "rolled_back",
        }, incident_id),
        _event(1005, start + timedelta(seconds=1002), "rollback", {"ok": True}, incident_id),
        _event(1006, start + timedelta(seconds=1002), "state", {
            "to": "NEEDS_HUMAN",
        }, incident_id),
        _event(1007, start + timedelta(seconds=1003), "state", {"to": "HEALTHY"}, incident_id),
        _event(1008, start + timedelta(seconds=1003.1), "closed", {}, incident_id),
        _event(1009, start + timedelta(seconds=14400), "soak_fault", {
            "phase": "start",
            "fault_id": "fault-no-incident",
            "fault": "overexpose",
            "started_elapsed_s": 14400,
            "start_wall": (start + timedelta(seconds=14400)).isoformat(),
        }),
        _event(1010, start + timedelta(seconds=14401), "soak_fault", {
            "phase": "end",
            "fault_id": "fault-no-incident",
            "fault": "overexpose",
            "start_wall": (start + timedelta(seconds=14400)).isoformat(),
            "end_wall": (start + timedelta(seconds=14401)).isoformat(),
        }),
    ])
    report = evaluate_events(events)
    unmatched = report["unmatched_incidents"][0]
    assert unmatched["incident_id"] == incident_id
    assert unmatched["fault_kind"] == "low_fps"
    assert unmatched["seconds_since_preceding_fault_end"]["fault_id"] == "fault-0000"
    assert unmatched["seconds_since_preceding_fault_end"]["seconds_before_confirmation"] == 340
    assert unmatched["actions"] == [
        "switch_stream_profile (execution success, verification rolled_back)",
        "rollback (restored)",
    ]
    assert unmatched["closing_state"] == "HEALTHY"
    assert round(unmatched["seconds_until_closure"], 1) == 3.1
    assert round(unmatched["seconds_from_needs_human_to_closure"], 1) == 1.1
    undetected = report["faults_without_incident"][0]
    assert undetected["fault_id"] == "fault-no-incident"
    assert undetected["kind"] == "overexpose"
    assert undetected["active_duration_s"] == 1
    assert undetected["started_at_or_after_requested_duration"] is True
    markdown = soak_module.render_report(report)
    assert "Detection is informational (`gate: false`); the F10 detection minimum" in markdown
    assert "Planner: local-rules, rules, live calls 0, cost USD 0.000000" in markdown
    assert "Unmatched incident unmatched-incident" in markdown
    assert "Fault fault-no-incident (overexpose) had no incident" in markdown


class _StubSource:
    def __init__(self, **_kwargs):
        self.settings = {"profile": "main"}
        self.fault = None
        self.closed = False

    def apply_settings(self, settings):
        self.settings.update(settings)

    def get_settings(self):
        return dict(self.settings)

    def set_fault(self, fault, _strength=1.0):
        self.fault = fault

    def close(self):
        self.closed = True


def test_run_soak_builds_a_fresh_source_after_early_run_live_return(tmp_path, monkeypatch):
    sources = []
    clock = {"now": 0.0}

    def monotonic():
        return clock["now"]

    def advance(seconds):
        clock["now"] += seconds

    monkeypatch.setattr(
        soak_module,
        "time",
        SimpleNamespace(monotonic=monotonic, sleep=advance),
    )

    def early_return(_cfg, **kwargs):
        source = kwargs["source"]
        sources.append(source)
        source.close()

    monkeypatch.setattr(soak_module, "SyntheticSource", _StubSource)
    monkeypatch.setattr(soak_module, "run_live", early_return)
    run_soak(
        hours=0.0006,
        out=tmp_path / "early-return",
        sample_s=0.5,
        first_fault_s=10,
    )
    assert len(sources) >= 2
    assert len({id(source) for source in sources}) == len(sources)
    assert all(source.closed for source in sources)


def test_run_soak_does_not_schedule_fault_at_or_after_requested_end(tmp_path, monkeypatch):
    def return_after_deadline(_cfg, *, duration_s, on_window, source, **_kwargs):
        import time

        time.sleep(duration_s + 0.05)
        source.close()
        on_window(None, None)

    monkeypatch.setattr(soak_module, "SyntheticSource", _StubSource)
    monkeypatch.setattr(soak_module, "run_live", return_after_deadline)
    db_path = run_soak(
        hours=0.0002,
        out=tmp_path / "late-schedule",
        sample_s=0.1,
        first_fault_s=0.01,
    )
    events = _load_events(db_path)
    assert not any(
        event["kind"] == "soak_fault" and event["payload"].get("phase") == "start"
        for event in events
    )


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
    assert len(report["database_sha256"]) == 64
    assert "--out-dir" in report["regenerate_command"]
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
