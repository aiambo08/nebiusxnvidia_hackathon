"""Read-only API over the event store (feeds the Phase-9 dashboard).

    uvicorn --factory apps.api.main:create_app --port 8000
The API never triggers actions; only the agent loop can, through the policy gate.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

from reliability_agent.config import api_key, load_config
from reliability_agent.feed import LiveFeed
from reliability_agent.storage.event_store import EventStore


def create_app(
    db_path: str | None = None,
    *,
    store: EventStore | None = None,
    feed: LiveFeed | None = None,
    cfg: dict | None = None,
) -> FastAPI:
    cfg = cfg if cfg is not None else load_config()
    store = store if store is not None else EventStore(db_path or cfg["storage"]["db_path"])
    app = FastAPI(title="Physical AI Reliability Agent", version="0.1.0",
                  docs_url=None, redoc_url=None)

    def budget_summary() -> dict:
        b = cfg["budget"]
        spent = store.spent_usd()
        return {"spent_usd_estimate": round(spent, 5), **b,
                "remaining_to_hard_cap": round(b["hard_cap_usd"] - spent, 5)}

    def header_planner_source(snapshot: dict) -> str | None:
        """Planner source the header must show, decided by the backend.

        The header belongs to the *current* scenario: take the plan source of the
        latest incident opened after ``scenario_started_at`` if it has planned yet,
        otherwise the scenario's configured planner (``planner_source``). Incidents
        left over from a previous scenario never drive the header again.
        """
        started = snapshot.get("scenario_started_at")
        if started:
            for event in reversed(store.events(kind="incident")):
                if event["ts"] >= started:
                    plans = [plan for plan in store.events(event["incident_id"], "plan")]
                    if plans:
                        return plans[-1]["payload"].get("source")
                    break
        return snapshot.get("planner_source")

    @app.get("/")
    def dashboard() -> FileResponse:
        path = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"
        return FileResponse(path)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "chain_valid": store.verify_chain()}

    @app.get("/incidents")
    def incidents() -> list[dict]:
        out = []
        for e in store.events(kind="incident"):
            iid = e["incident_id"]
            states = [x for x in store.events(iid, "state")]
            out.append({
                "incident_id": iid,
                "opened": e["ts"],
                "faults": e["payload"]["candidate_faults"],
                "state": states[-1]["payload"]["to"] if states else "CONFIRMED",
            })
        return out

    @app.get("/incidents/{incident_id}")
    def incident(incident_id: str) -> list[dict]:
        ev = store.events(incident_id)
        if not ev:
            raise HTTPException(404, "unknown incident")
        return ev

    @app.get("/budget")
    def budget() -> dict:
        return budget_summary()

    @app.get("/api/status")
    def status() -> dict:
        planner_cfg = cfg["planner"]
        tier = planner_cfg.get("tier", "fast")
        kind = planner_cfg["kind"]
        model = cfg["nebius"]["models"].get(tier) if kind != "rules" else None
        snapshot = feed.snapshot() if feed is not None else {
            "mode": "OFFLINE (event store only)",
        }
        header_source = header_planner_source(snapshot)
        # N3: the model/prompt chips only describe an LLM call. With a local or
        # scripted planner the header must not advertise the configured Nemotron.
        uses_llm = header_source in ("nemotron", "cache") or (
            header_source is None and kind != "rules"
        )
        return {
            **snapshot,
            "chain_valid": store.verify_chain(),
            "planner": {
                "kind": kind,
                "model": model if uses_llm else None,
                "prompt_version": planner_cfg.get("prompt_version") if uses_llm else None,
                "tier": tier,
                "api_key_present": bool(api_key()),
            },
            "budget": budget_summary(),
        }

    @app.get("/api/windows")
    def windows(n: int = Query(default=120, ge=0)) -> list[dict]:
        return feed.windows(n) if feed is not None else []

    @app.get("/api/frame.jpg")
    def frame() -> Response:
        latest = feed.frame() if feed is not None else None
        if latest is None:
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return Response(
            content=latest[0],
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/incidents")
    def api_incidents(limit: int = Query(default=20, ge=1)) -> list[dict]:
        incident_events = list(reversed(store.events(kind="incident")))[:limit]
        out = []
        for event in incident_events:
            incident_id = event["incident_id"]
            events = store.events(incident_id=incident_id)
            states = [item for item in events if item["kind"] == "state"]
            out.append({
                "incident_id": incident_id,
                "opened": event["ts"],
                "faults": event["payload"]["candidate_faults"],
                "state": states[-1]["payload"].get("to", "CONFIRMED") if states else "CONFIRMED",
                "events": events,
            })
        return out

    return app
