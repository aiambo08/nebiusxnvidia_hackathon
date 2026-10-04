import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from reliability_agent.demo import run_scenario  # noqa: E402
from reliability_agent.storage import EventStore  # noqa: E402


def test_api_reads_incidents(tmp_path):
    db = tmp_path / "e.sqlite"
    store = EventStore(db)
    run_scenario("bad_action", store=store)
    from apps.api.main import create_app

    c = TestClient(create_app(str(db)))
    assert c.get("/health").json() == {"status": "ok", "chain_valid": True}
    incs = c.get("/incidents").json()
    assert len(incs) == 1 and incs[0]["state"] == "HEALTHY"
    ev = c.get(f"/incidents/{incs[0]['incident_id']}").json()
    assert {"plan", "policy", "execution", "verification", "rollback"} <= {e["kind"] for e in ev}
    assert c.get("/incidents/nope").status_code == 404
    assert c.get("/budget").json()["hard_cap_usd"] == 27
