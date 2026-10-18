import json
import subprocess
import sys
from pathlib import Path

from reliability_agent.demo import demo_config, run_scenario
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.storage import EventStore
from scripts.incident_report import report_for_incident


def test_reports_are_derived_from_scenario_event_store(tmp_path):
    db_path = tmp_path / "scenarios.sqlite"
    store = EventStore(db_path)
    try:
        run_scenario(
            "dark", planner=RuleBasedPlanner(), cfg=demo_config(), store=store, seed=0
        )
        run_scenario("bad_action", cfg=demo_config(), store=store, seed=1)
    finally:
        store.close()

    reopened = EventStore(db_path)
    try:
        events = reopened.events()
        assert reopened.verify_chain()
    finally:
        reopened.close()

    incidents = [event for event in events if event["kind"] == "incident"]
    assert len(incidents) == 2
    committed = report_for_incident(events, incidents[0]["incident_id"])
    rolled_back = report_for_incident(events, incidents[1]["incident_id"])
    assert committed["verifications"][-1]["status"] == "committed"
    assert rolled_back["rollbacks"][-1]["ok"] is True

    out_dir = tmp_path / "reports"
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.incident_report",
            "--db",
            str(db_path),
            "--out",
            str(out_dir),
        ],
        check=True,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(out_dir.glob("*.json"))
    ]
    assert len(payloads) == 2
    assert {payload["incident_id"] for payload in payloads} == {
        incident["incident_id"] for incident in incidents
    }
    assert all(payload["events"] for payload in payloads)
