import re
from datetime import timedelta
from itertools import cycle
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from reliability_agent.cli import mode_label  # noqa: E402
from reliability_agent.config import load_config  # noqa: E402
from reliability_agent.demo import SCENARIOS, demo_config, run_scenario  # noqa: E402
from reliability_agent.feed import LiveFeed  # noqa: E402
from reliability_agent.nemotron.planner import RuleBasedPlanner  # noqa: E402
from reliability_agent.storage.event_store import EventStore  # noqa: E402
from tests.conftest import make_window  # noqa: E402


def test_live_feed_rate_limits_jpeg_and_bounds_windows():
    now = [0.0]
    feed = LiveFeed("SIMULATION", "SyntheticSource", max_windows=2, jpeg_fps=5,
                    clock=lambda: now[0])
    image = np.zeros((200, 1280, 3), dtype=np.uint8)
    feed.on_frame(image)
    first = feed.frame()
    assert first is not None and first[0].startswith(b"\xff\xd8") and first[1] == 1
    decoded = cv2.imdecode(np.frombuffer(first[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] == 640

    now[0] = 0.1
    feed.on_frame(image)
    assert feed.frame() == first
    now[0] = 0.21
    feed.on_frame(image)
    assert feed.frame() is not None and feed.frame()[1] == 2

    last_window = None
    for state in ("SUSPECT", "CONFIRMED", "NEEDS_HUMAN"):
        last_window = make_window()
        feed.on_window(last_window, SimpleNamespace(state=state, active=None))
    assert len(feed.windows(5)) == 2
    assert [window["state"] for window in feed.windows(5)] == ["CONFIRMED", "NEEDS_HUMAN"]
    assert feed.snapshot()["last_window"]["ts"] == (
        last_window.window_start + timedelta(seconds=1.0)
    ).isoformat()


def test_dashboard_api_and_legacy_routes_read_shared_store(monkeypatch):
    from apps.api.main import create_app

    fake_key = "dashboard-test-key-must-not-be-returned"
    monkeypatch.setenv("NEBIUS_API_KEY", fake_key)
    cfg = load_config(env=False)
    cfg["planner"]["kind"] = "nemotron"
    store = EventStore()
    feed = LiveFeed("SIMULATION", "SyntheticSource")
    app = create_app(store=store, feed=feed, cfg=cfg)
    assert all(route.methods <= {"GET"} for route in app.routes if route.path.startswith("/api/"))
    client = TestClient(app)
    try:
        assert client.get("/api/frame.jpg").status_code == 204
        assert client.get("/docs").status_code == 404
        feed.on_frame(np.zeros((120, 160, 3), dtype=np.uint8))
        frame = client.get("/api/frame.jpg")
        assert frame.status_code == 200
        assert frame.content.startswith(b"\xff\xd8")
        assert frame.headers["cache-control"] == "no-store"

        run_scenario("bad_action", store=store, on_frame=feed.on_frame,
                     on_window=feed.on_window)

        status = client.get("/api/status")
        assert status.status_code == 200
        assert fake_key not in status.text
        payload = status.json()
        assert payload["mode"] == "SIMULATION"
        assert payload["planner"] == {
            "kind": "nemotron",
            "model": cfg["nebius"]["models"]["fast"],
            "prompt_version": cfg["planner"]["prompt_version"],
            "tier": "fast",
            "api_key_present": True,
        }
        assert payload["budget"] == client.get("/budget").json()
        assert payload["chain_valid"] is True

        windows = client.get("/api/windows?n=3")
        assert windows.status_code == 200 and 0 < len(windows.json()) <= 3
        incidents = client.get("/api/incidents?limit=1")
        assert incidents.status_code == 200 and len(incidents.json()) == 1
        incident = incidents.json()[0]
        assert {"incident_id", "opened", "faults", "state", "events"} <= incident.keys()
        assert {"plan", "policy", "execution", "verification", "rollback"} <= {
            event["kind"] for event in incident["events"]
        }

        assert client.get("/").status_code == 200
        page = client.get("/").text
        assert "Physical AI Reliability Agent" in page
        assert "https://" not in page  # offline: no CDN or external assets
        assert client.get("/health").json() == {"status": "ok", "chain_valid": True}
        legacy_incidents = client.get("/incidents").json()
        assert len(legacy_incidents) == 1 and legacy_incidents[0]["state"] == "HEALTHY"
        incident_id = legacy_incidents[0]["incident_id"]
        assert client.get(f"/incidents/{incident_id}").status_code == 200
        assert client.get("/incidents/nope").status_code == 404
        assert client.get("/budget").json()["hard_cap_usd"] == 27

        offline = TestClient(create_app(store=store, cfg=cfg))
        assert offline.get("/api/status").json()["mode"] == "OFFLINE (event store only)"
        assert offline.get("/api/windows").json() == []
        assert offline.get("/api/frame.jpg").status_code == 204
    finally:
        store.close()


def test_dashboard_html_escapes_template_interpolations():
    """A deliberately simple regex checks template literals assigned to HTML sinks."""
    page = (Path(__file__).resolve().parents[2] / "apps/dashboard/index.html").read_text()
    assert "Fault cleared; primary metric already at baseline." in page
    assignments = re.findall(
        r"(?s)(?:\.innerHTML\s*=|\.insertAdjacentHTML\s*\([^,]+,)\s*(.*?);", page)
    for assignment in assignments:
        for template in re.findall(r"`([^`]*)`", assignment, re.S):
            if "<" not in template:
                continue
            interpolations = re.findall(r"\$\{([^{}]*)\}", template)
            assert template.count("${") == len(interpolations), template
            for expression in interpolations:
                assert re.match(r"\s*(?:esc|num|usd)\s*\(", expression), expression


def _without_timestamps(value):
    if isinstance(value, dict):
        return {
            key: _without_timestamps(item)
            for key, item in value.items()
            if key not in {"ts", "opened_at", "window_start", "incident_id", "execution_id"}
        }
    if isinstance(value, list):
        return [_without_timestamps(item) for item in value]
    return value


def test_scenario_hooks_without_pacing_preserve_events(monkeypatch):
    times = cycle((0.0, 0.001))
    monkeypatch.setattr(
        "reliability_agent.tasks.marker.time",
        SimpleNamespace(perf_counter=lambda: next(times)),
    )
    plain_store = EventStore()
    hooked_store = EventStore()
    try:
        run_scenario("bad_action", store=plain_store, seed=0)
        run_scenario("bad_action", store=hooked_store, seed=0, on_frame=lambda _image: None,
                     pace_s=0)
        plain_events = [(event["kind"], _without_timestamps(event["payload"]))
                        for event in plain_store.events()]
        hooked_events = [(event["kind"], _without_timestamps(event["payload"]))
                         for event in hooked_store.events()]
        assert hooked_events == plain_events
    finally:
        plain_store.close()
        hooked_store.close()


@pytest.mark.parametrize(
    ("args_or_uri", "expected"),
    [
        (SimpleNamespace(live=False, uri="clip.mp4"), "SIMULATION"),
        (SimpleNamespace(live=True, uri="0"), "REAL HARDWARE"),
        (SimpleNamespace(live=True, uri="rtsp://camera/live"), "REAL HARDWARE"),
        (SimpleNamespace(live=True, uri="clip.mp4"), "REPLAY"),
        (0, "REAL HARDWARE"),
        ("clip.mp4", "REPLAY"),
    ],
)
def test_mode_label(args_or_uri, expected):
    assert mode_label(args_or_uri) == expected


@pytest.mark.parametrize("name", tuple(SCENARIOS))
def test_scenarios_close_within_90_simulated_seconds(name):
    store = EventStore()
    warmup = 15
    window_clock = []
    close_clock = None

    def on_window(_window, agent):
        nonlocal close_clock
        now = agent.clock()
        window_clock.append(now)
        if close_clock is None and store.events(kind="closed"):
            close_clock = now

    try:
        result = run_scenario(
            name,
            RuleBasedPlanner(),
            cfg=demo_config(),
            store=store,
            warmup=warmup,
            seed=0,
            on_window=on_window,
            pace_s=0,
        )
        assert any(event["kind"] == "closed" for event in result.events), name
        assert len(window_clock) >= warmup, name
        assert close_clock is not None, name
        elapsed = close_clock - window_clock[warmup - 1]
        print(f"{name}: {elapsed:.1f}s")
        assert 0 <= elapsed <= 90, f"{name}: {elapsed:.1f}s"
    finally:
        store.close()
