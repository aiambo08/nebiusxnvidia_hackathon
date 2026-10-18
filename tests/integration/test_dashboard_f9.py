import builtins
import json
import logging
import socket
import sqlite3
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import reliability_agent.cli as cli  # noqa: E402
import reliability_agent.demo as demo  # noqa: E402
from reliability_agent.demo import SCENARIOS, demo_config  # noqa: E402
from reliability_agent.feed import LiveFeed  # noqa: E402
from reliability_agent.nemotron import BudgetGuard, make_planner  # noqa: E402
from reliability_agent.storage.event_store import EventStore  # noqa: E402

SENTINEL = "nvapi-F9SENTINEL0123456789abcdef"
NEEDS_HUMAN_REPLY = json.dumps({
    "diagnosis": "blackout",
    "confidence": 0.8,
    "evidence_refs": [],
    "action": {"name": "needs_human", "arguments": {}},
    "verification": {
        "window_seconds": 10,
        "primary_metric": "task.success_rate",
        "minimum_relative_improvement": 0.1,
        "guard_metrics": [],
    },
    "human_message": "Synthetic offline response.",
})


class FakeSDK:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
        )


def _args(names):
    return SimpleNamespace(scenarios=list(names), pace=0.0, gap=0.0, loop=False)


def _forbid_external_drivers(monkeypatch):
    calls = []

    def forbidden_input(*_args, **_kwargs):
        calls.append("input")
        raise AssertionError("the dashboard runner must not request manual input")

    def forbidden_network(*_args, **_kwargs):
        calls.append("network")
        raise AssertionError("the dashboard runner must not make network calls")

    monkeypatch.setattr(builtins, "input", forbidden_input)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    return calls


def _incident_events(store):
    incidents = store.events(kind="incident")
    assert len(incidents) == 1
    incident_id = incidents[0]["incident_id"]
    return incident_id, store.events(incident_id=incident_id)


def _event_index(events, kind, predicate=lambda _event: True):
    return next(
        index for index, event in enumerate(events)
        if event["kind"] == kind and predicate(event)
    )


def _settings_bytes(source):
    return json.dumps(
        source.get_settings(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("name", "expected_path"),
    [
        ("dark", "committed"),
        ("defocus", "committed"),
        ("freeze", "committed"),
        ("overexposure", "committed"),
        ("frozen_black", "committed"),
        ("bad_action", "rollback"),
        ("occlusion", "ticket"),
    ],
)
def test_scenarios_run_confirm_to_verify_without_input(name, expected_path, monkeypatch):
    external_calls = _forbid_external_drivers(monkeypatch)
    settings = []
    if expected_path == "ticket":
        original_run_scenario = demo.run_scenario

        def capture_source(*args, **kwargs):
            snapshot = {}

            def on_source(source):
                snapshot["source"] = source
                snapshot["before"] = _settings_bytes(source)

            kwargs["on_source"] = on_source
            result = original_run_scenario(*args, **kwargs)
            snapshot["after"] = _settings_bytes(snapshot["source"])
            settings.append(snapshot)
            return result

        monkeypatch.setattr(demo, "run_scenario", capture_source)

    store = EventStore()
    feed = LiveFeed("SIMULATION", "SyntheticSource")
    stop_event = threading.Event()
    try:
        cli._run_dashboard_scenarios(
            _args([name]), demo_config(), feed, store, "rules", stop_event
        )
        assert not stop_event.is_set()
        incident_id, events = _incident_events(store)

        incident_index = _event_index(events, "incident")
        confirmed_index = _event_index(
            events,
            "state",
            lambda event: (
                event["payload"]["to"] == "DIAGNOSING"
                and event["payload"]["reason"] == "incident confirmed"
            ),
        )
        assert incident_index < confirmed_index

        if expected_path == "committed":
            execution_index = _event_index(
                events, "execution", lambda event: event["payload"]["status"] == "success"
            )
            verification_index = _event_index(
                events,
                "verification",
                lambda event: event["payload"]["status"] == "committed",
            )
            closed_index = _event_index(events, "closed")
            assert confirmed_index < execution_index < verification_index < closed_index
            states = [event["payload"]["to"] for event in events if event["kind"] == "state"]
            assert states[-1] == "HEALTHY"
        elif expected_path == "rollback":
            execution_index = _event_index(
                events, "execution", lambda event: event["payload"]["status"] == "success"
            )
            verification_index = _event_index(
                events,
                "verification",
                lambda event: event["payload"]["status"] == "rolled_back",
            )
            rollback_index = _event_index(events, "rollback")
            closed_index = _event_index(events, "closed")
            assert (
                confirmed_index
                < execution_index
                < verification_index
                < rollback_index
                < closed_index
            )
            states = [event["payload"]["to"] for event in events if event["kind"] == "state"]
            assert states[-1] == "HEALTHY"
        else:
            execution_index = _event_index(
                events, "execution", lambda event: event["payload"]["status"] == "ticket"
            )
            needs_human_index = _event_index(
                events,
                "state",
                lambda event: event["payload"]["to"] == "NEEDS_HUMAN",
            )
            assert confirmed_index < execution_index < needs_human_index
            assert not any(event["kind"] == "verification" for event in events)
            assert not any(event["kind"] == "rollback" for event in events)
            assert settings[0]["before"] == settings[0]["after"]
            assert settings[0]["before"] == _settings_bytes(settings[0]["source"])
            assert incident_id == events[incident_index]["incident_id"]
        assert external_calls == []
    finally:
        store.close()


def test_api_exposes_no_mutating_routes():
    from apps.api.main import create_app

    store = EventStore()
    try:
        app = create_app(store=store)
        assert app.routes
        for route in app.routes:
            methods = getattr(route, "methods", None)
            assert methods, f"{route.path} must expose HTTP methods"
            assert methods <= {"GET", "HEAD"}, f"{route.path}: {methods}"
    finally:
        store.close()


def test_no_secret_reaches_api_html_logs_or_store(
    monkeypatch, capsys, caplog, tmp_path
):
    from apps.api.main import create_app

    monkeypatch.setenv("NEBIUS_API_KEY", SENTINEL)
    caplog.set_level(logging.DEBUG)
    external_calls = _forbid_external_drivers(monkeypatch)
    cfg = demo_config()
    cfg["planner"]["kind"] = "nemotron"
    sdk = FakeSDK([NEEDS_HUMAN_REPLY] * len(SCENARIOS))

    def offline_planner(kind, planner_cfg):
        assert kind == "nemotron"
        return make_planner(
            planner_cfg,
            SENTINEL,
            BudgetGuard.from_config(planner_cfg),
            sdk_client=sdk,
        )

    monkeypatch.setattr(cli, "_planner", offline_planner)
    db_path = tmp_path / "dashboard-f9.sqlite"
    store = EventStore(db_path)
    feed = LiveFeed("SIMULATION", "SyntheticSource")
    stop_event = threading.Event()
    try:
        cli._run_dashboard_scenarios(
            _args(SCENARIOS), cfg, feed, store, "nemotron", stop_event
        )
        assert not stop_event.is_set()
        assert sdk.calls
        app = create_app(store=store, feed=feed, cfg=cfg)
        incident_id = store.events(kind="incident")[0]["incident_id"]
        response_bodies = []
        with TestClient(app) as client:
            paths = [
                route.path
                for route in app.routes
                if "GET" in getattr(route, "methods", set())
            ]
            assert "/" in paths
            for path in paths:
                path = path.replace("{incident_id}", incident_id)
                response = client.get(path)
                assert response.status_code < 500, path
                response_bodies.append(response.content)

        with sqlite3.connect(db_path) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            ]
            rows = {
                table: connection.execute(f'SELECT * FROM "{table}"').fetchall()
                for table in tables
            }

        captured = capsys.readouterr()
        surfaces = [
            *(body.decode("utf-8", errors="replace") for body in response_bodies),
            captured.out,
            captured.err,
            caplog.text,
            json.dumps(rows, default=str, sort_keys=True),
            json.dumps(sdk.calls, default=str, sort_keys=True),
        ]
        assert SENTINEL not in "\n".join(surfaces), (
            "secret sentinel leaked into the dashboard, logs, output, or SQLite store"
        )
        assert external_calls == []
    finally:
        store.close()
