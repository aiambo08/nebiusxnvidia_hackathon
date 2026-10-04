"""Read-only API over the event store (feeds the Phase-9 dashboard).

    uvicorn --factory apps.api.main:create_app --port 8000
The API never triggers actions; only the agent loop can, through the policy gate.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from reliability_agent.config import load_config
from reliability_agent.storage.event_store import EventStore


def create_app(db_path: str | None = None) -> FastAPI:
    cfg = load_config()
    store = EventStore(db_path or cfg["storage"]["db_path"])
    app = FastAPI(title="Physical AI Reliability Agent", version="0.1.0")

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
        b = cfg["budget"]
        spent = store.spent_usd()
        return {"spent_usd_estimate": round(spent, 5), **b,
                "remaining_to_hard_cap": round(b["hard_cap_usd"] - spent, 5)}

    return app
