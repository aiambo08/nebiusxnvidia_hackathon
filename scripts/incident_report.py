"""Render an incident report from the EventStore event log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reliability_agent.storage import EventStore


def report_for_incident(events: list[dict[str, Any]], incident_id: str) -> dict[str, Any]:
    selected = [event for event in events if event.get("incident_id") == incident_id]
    incident_event = next((event for event in selected if event["kind"] == "incident"), None)
    plan_event = next((event for event in selected if event["kind"] == "plan"), None)
    policy_events = [event for event in selected if event["kind"] == "policy"]
    executions = [event for event in selected if event["kind"] == "execution"]
    verifications = [event for event in selected if event["kind"] == "verification"]
    rollbacks = [event for event in selected if event["kind"] == "rollback"]
    restore_events = [event for event in selected if event["kind"] == "restore"]
    restart_rollbacks = [
        event for event in rollbacks
        if event["payload"].get("reason") == "restart with an uncommitted action"
    ]
    if not restart_rollbacks:
        restart_rollbacks = [
            {
                "seq": event["seq"],
                "ts": event["ts"],
                "incident_id": incident_id,
                "kind": "restore",
                "payload": item,
            }
            for event in restore_events
            for item in event["payload"].get("rolled_back", [])
        ]
    usage = plan_event["payload"].get("usage", {}) if plan_event else {}
    return {
        "incident_id": incident_id,
        "faults": (
            incident_event["payload"].get("candidate_faults", [])
            if incident_event else []
        ),
        "opened": incident_event["ts"] if incident_event else None,
        "plan": None if plan_event is None else {
            "source": plan_event["payload"].get("source"),
            "model": usage.get("model"),
            "prompt_version": usage.get("prompt_version"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": usage.get("estimated_cost_usd"),
            "plan": plan_event["payload"].get("plan"),
            "usage": usage,
        },
        "decisions": [event["payload"] for event in policy_events],
        "executions": [event["payload"] for event in executions],
        "verifications": [event["payload"] for event in verifications],
        "rollbacks": [event["payload"] for event in rollbacks],
        "restart_rollbacks": restart_rollbacks,
        "restart_resolution": (
            "rolled back on restart" if restart_rollbacks else None
        ),
        "events": selected,
    }


def to_markdown(report: dict[str, Any]) -> str:
    plan = report["plan"] or {}
    lines = [
        f"# Incident {report['incident_id']}",
        "",
        "**SIMULATION / EVENTSTORE DERIVED**",
        "",
        f"- Opened: {report['opened']}",
        f"- Faults: {', '.join(map(str, report['faults'])) or 'unknown'}",
        f"- Planner source: {plan.get('source', 'not recorded')}",
        f"- Model / prompt: {plan.get('model', 'n/a')} / "
        f"{plan.get('prompt_version', 'n/a')}",
        f"- Tokens: {plan.get('input_tokens', 0)} input, "
        f"{plan.get('output_tokens', 0)} output",
        f"- Estimated plan cost: ${plan.get('cost_usd', 0) or 0}",
        f"- Restart resolution: {report['restart_resolution'] or 'none'}",
        "",
        "## Gate decisions",
        "",
        "```json",
        json.dumps(report["decisions"], indent=2, sort_keys=True),
        "```",
        "",
        "## Execution and verification",
        "",
        "```json",
        json.dumps({
            "executions": report["executions"],
            "verifications": report["verifications"],
            "rollbacks": report["rollbacks"],
        }, indent=2, sort_keys=True),
        "```",
        "",
        f"Event count: {len(report['events'])}.",
        "",
    ]
    return "\n".join(lines)


def write_reports(events: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    incident_ids = list(dict.fromkeys(
        event["incident_id"] for event in events
        if event.get("kind") == "incident" and event.get("incident_id")
    ))
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for incident_id in incident_ids:
        report = report_for_incident(events, incident_id)
        stem = out_dir / f"incident-{incident_id}"
        stem.with_suffix(".json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stem.with_suffix(".md").write_text(to_markdown(report), encoding="utf-8")
        outputs.extend((stem.with_suffix(".md"), stem.with_suffix(".json")))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    store = EventStore(args.db)
    try:
        events = store.events()
    finally:
        store.close()
    out_dir = args.out or args.db.parent / "incident-reports"
    for path in write_reports(events, out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
