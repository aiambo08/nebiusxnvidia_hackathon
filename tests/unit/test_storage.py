from reliability_agent.contracts.models import FaultType, Incident
from reliability_agent.storage import EventStore


def test_hash_chain_and_tamper_detection(tmp_path):
    s = EventStore(tmp_path / "e.sqlite")
    inc = Incident(camera_id="c", candidate_faults=[FaultType.FREEZE])
    s.append("incident", inc, inc.incident_id)
    s.append("plan", {"a": 1}, inc.incident_id)
    s.append("state", {"from": "A", "to": "B"})
    assert s.verify_chain()
    assert [e["kind"] for e in s.events(inc.incident_id)] == ["incident", "plan"]
    s._db.execute("UPDATE events SET payload='{\"a\":2}' WHERE kind='plan'")
    assert not s.verify_chain()


def test_snapshots_usage_and_state(tmp_path):
    p = tmp_path / "e.sqlite"
    s = EventStore(p)
    s.save_snapshot("x1", "inc", "set_exposure_bounded", {"exposure": 0.0})
    assert s.pending_snapshots()[0]["snapshot"] == {"exposure": 0.0}
    s.mark_restored("x1")
    assert s.pending_snapshots() == []
    s.record_usage("m", "v1", 100, 10, 0.25)
    s.record_usage("m", "v1", 100, 10, 0.5)
    s.put_state("baseline", {"v": 1})
    s.close()
    s2 = EventStore(p)  # survives restart
    assert s2.spent_usd() == 0.75
    assert s2.get_state("baseline") == {"v": 1}
