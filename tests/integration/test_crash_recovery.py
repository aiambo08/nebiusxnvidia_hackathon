"""F7 evidence: a real process death is recovered from persistent state."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reliability_agent.config import load_config
from reliability_agent.contracts.models import ActionName, IncidentState
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.orchestrator import ReliabilityAgent, lease_key
from reliability_agent.storage import EventStore
from tests.helpers.crash_child import FileBackedDevice

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests" / "helpers" / "crash_child.py"
S = IncidentState


class CountingPlanner:
    def __init__(self) -> None:
        self._planner = RuleBasedPlanner()
        self.calls = 0

    def plan(self, incident):
        self.calls += 1
        return self._planner.plan(incident)


def crash_config() -> dict:
    cfg = load_config(env=False)
    cfg["camera"]["id"] = "f7-crash-test"
    cfg["planner"]["kind"] = "rules"
    cfg["planner"]["timeout_s"] = 0.1
    cfg["planner"]["max_calls_per_incident"] = 1
    cfg["storage"]["lease_stale_s"] = 11.5
    return cfg


def _kill_child_at_marker(command: list[str], marker: Path) -> None:
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(ROOT / "src"),
                    str(ROOT),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        },
    )
    try:
        deadline = time.monotonic() + 30.0
        while not marker.exists() and proc.poll() is None:
            if time.monotonic() >= deadline:
                proc.kill()
                output, _ = proc.communicate(timeout=10)
                raise AssertionError(f"child did not reach kill point:\n{output}")
            time.sleep(0.02)
        if not marker.exists():
            output, _ = proc.communicate(timeout=10)
            raise AssertionError(f"child exited before kill point:\n{output}")
        proc.kill()
        proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)


def _wait_for_lease_expiry(store: EventStore, camera_id: str, stale_s: float) -> None:
    deadline = time.monotonic() + 30.0
    while True:
        lease = store.get_state(lease_key(camera_id))
        age = time.time() - float(lease["heartbeat"])
        if age >= stale_s:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"lease did not expire after {stale_s}s")
        time.sleep(min(0.05, max(0.01, stale_s - age)))


@pytest.mark.parametrize("kill_point", ["after_snapshot", "mid_apply", "verifying"])
def test_real_process_kill_restores_pending_action(kill_point: str, tmp_path: Path) -> None:
    cfg = crash_config()
    db_path = tmp_path / "agent.sqlite"
    device_path = tmp_path / "device-settings.json"
    marker_path = tmp_path / "kill-marker.json"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg, sort_keys=True), encoding="utf-8")
    command = [
        sys.executable,
        str(HELPER),
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--device",
        str(device_path),
        "--marker",
        str(marker_path),
        "--kill-point",
        kill_point,
    ]
    _kill_child_at_marker(command, marker_path)
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {"kill_point": kill_point}

    store = EventStore(db_path)
    first_agent = None
    second_store = None
    second_agent = None
    restart_cfg = copy.deepcopy(cfg)
    restart_cfg["storage"]["restore_on_start"] = False
    try:
        _wait_for_lease_expiry(store, cfg["camera"]["id"], cfg["storage"]["lease_stale_s"])
        pending = store.pending_snapshots()
        assert len(pending) == 1
        pending_snapshot = pending[0]["snapshot"]
        incident_id = pending[0]["incident_id"]
        assert pending[0]["action"] == ActionName.SET_EXPOSURE_BOUNDED.value
        assert len(store.events(kind="incident")) == 1
        assert len(store.events(kind="plan")) == 1
        assert len(store.events(kind="execution")) == (1 if kill_point == "verifying" else 0)

        device = FileBackedDevice(device_path)
        before_restore = device.get_settings()
        if kill_point == "after_snapshot":
            assert before_restore == pending_snapshot
        else:
            assert before_restore["exposure"] != pending_snapshot["exposure"]

        planner = CountingPlanner()
        first_agent = ReliabilityAgent(restart_cfg, device, planner, store)
        assert first_agent.restore()
        assert first_agent.state is S.NEEDS_HUMAN
        assert first_agent.active is not None
        assert first_agent.active.incident.incident_id == incident_id
        assert planner.calls == 0
        assert device.get_settings() == pending_snapshot
        assert store.pending_snapshots() == []
        assert ActionName.SET_EXPOSURE_BOUNDED.value in first_agent.gate.export_history()
        assert len(store.events(kind="rollback")) == 1
        assert store.verify_chain()

        first_agent.release_lease()
        first_agent = None
        store.close()
        store = None

        second_store = EventStore(db_path)
        second_device = FileBackedDevice(device_path)
        second_planner = CountingPlanner()
        second_agent = ReliabilityAgent(restart_cfg, second_device, second_planner, second_store)
        assert second_agent.restore()
        assert second_agent.state is S.NEEDS_HUMAN
        assert second_agent.active is not None
        assert second_agent.active.incident.incident_id == incident_id
        assert second_planner.calls == 0
        assert second_device.get_settings() == pending_snapshot
        assert second_store.pending_snapshots() == []
        assert len(second_store.events(kind="rollback")) == 1
        assert len(second_store.events(kind="plan")) == 1
        assert second_store.verify_chain()
    finally:
        if first_agent is not None:
            first_agent.release_lease()
        if store is not None:
            store.close()
        if second_agent is not None:
            second_agent.release_lease()
        if second_store is not None:
            second_store.close()
