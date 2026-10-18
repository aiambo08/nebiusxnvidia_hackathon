from __future__ import annotations

import json

import pytest

from benchmarks.experiments import (
    _a6_plan_summary,
    _a6_planner,
    _classifier_result,
    _NoCallPlanner,
    _run_custom,
    _run_standard,
    _run_training_baseline,
    _same_recovery_run_set,
    _summarize_runs,
    _update_recovery_counts,
    _verification_decisions_by_fault,
    generate_report,
    run_experiments,
)
from benchmarks.recovery import REGRESSION_ACTIONS, ScriptedPlanner
from reliability_agent.config import load_config
from reliability_agent.contracts.models import Incident
from reliability_agent.storage import EventStore


def _read_store(path):
    store = EventStore(path)
    try:
        return store.events(), store.verify_chain()
    finally:
        store.close()


def test_a1_detector_only_never_calls_its_failing_planner(tmp_path):
    planner = _NoCallPlanner()
    _run_standard(
        tmp_path, "test-revision", "A1_local_detector_only", "dark", 0.99, 0,
        planner=planner, detector_only=True, warmup=3, fault_windows=12,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A1_local_detector_only" / "recovery"
        / "dark-0.99-seed0.sqlite"
    )

    assert chain_valid
    assert planner.calls == 0
    assert any(event["kind"] == "incident" for event in events)
    assert not any(event["kind"] in ("plan", "execution") for event in events)


def test_a2_emits_a_plan_without_executing_or_changing_settings(tmp_path):
    _run_standard(
        tmp_path, "test-revision", "A2_detector_no_actions", "occlusion", 1.0, 0,
        auto_execute=False, warmup=3, fault_windows=12,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A2_detector_no_actions" / "recovery"
        / "occlusion-1.0-seed0.sqlite"
    )
    run = next(event["payload"] for event in reversed(events)
               if event["kind"] == "experiment_run")

    assert chain_valid
    assert any(event["kind"] == "plan" for event in events)
    assert not any(
        event["kind"] == "execution"
        and event["payload"].get("status") in ("success", "failed")
        for event in events
    )
    assert any(
        event["kind"] == "execution"
        and event["payload"].get("status") == "ticket"
        for event in events
    )
    assert run["settings_unchanged"]


def test_a3_and_a4_smoke_recovery_and_visual_metric_ablation(tmp_path):
    _run_standard(
        tmp_path, "test-revision", "A3_full_loop", "dark", 0.99, 0,
        warmup=3, fault_windows=12,
    )
    action, arguments = REGRESSION_ACTIONS["dark"]
    _run_standard(
        tmp_path, "test-revision", "A4_no_downstream_metric", "dark", 0.99, 0,
        planner=ScriptedPlanner(action, arguments), downstream_ablation=True,
        warmup=3, fault_windows=12, extra_metadata={"phase": "regression"},
    )

    recovery = tmp_path / "db" / "A3_full_loop" / "recovery"
    regression = tmp_path / "db" / "A4_no_downstream_metric" / "regression"
    assert (recovery / "dark-0.99-seed0.sqlite").exists()
    assert (regression / "dark-0.99-seed0.sqlite").exists()
    for path in (
        recovery / "dark-0.99-seed0.sqlite",
        regression / "dark-0.99-seed0.sqlite",
    ):
        events, chain_valid = _read_store(path)
        assert chain_valid
        assert any(event["kind"] == "incident" for event in events)


def test_a4_verification_events_use_visual_metric_without_task_guards(tmp_path):
    action, arguments = REGRESSION_ACTIONS["dark"]
    for arm, downstream_ablation in (
        ("A3_full_loop", False),
        ("A4_no_downstream_metric", True),
    ):
        _run_standard(
            tmp_path, "test-revision", arm, "dark", 0.99, 0,
            planner=ScriptedPlanner(action, arguments),
            downstream_ablation=downstream_ablation,
            warmup=3, fault_windows=12,
            extra_metadata={"phase": "regression"},
        )

    verification_events = {}
    for arm in ("A3_full_loop", "A4_no_downstream_metric"):
        events, chain_valid = _read_store(
            tmp_path / "db" / arm / "regression" / "dark-0.99-seed0.sqlite"
        )
        assert chain_valid
        verification_events[arm] = next(
            event for event in events if event["kind"] == "verification"
        )["payload"]

    a3 = verification_events["A3_full_loop"]
    a3_metrics = set(a3["before"]) | set(a3["after"])
    assert a3["reasons"][0].startswith("task.success_rate")
    assert {"task.success_rate", "task.latency_ms_p95"} <= a3_metrics

    a4 = verification_events["A4_no_downstream_metric"]
    a4_metrics = set(a4["before"]) | set(a4["after"])
    assert a4["reasons"][0].startswith("visual.brightness_p50")
    assert "visual.brightness_p50" in a4_metrics
    assert all(not metric.startswith("task.") for metric in a4_metrics)


def test_occlusion_recoverability_uses_the_f8_event_classifier():
    result = _classifier_result(
        [
            {
                "kind": "incident",
                "payload": {"allowed_actions": ["request_manual_cleaning"]},
            },
            {"kind": "execution", "payload": {"status": "ticket"}},
            {"kind": "state", "payload": {"to": "NEEDS_HUMAN"}},
            {"kind": "closed", "payload": {"reason": "camera healthy again"}},
        ],
        "occlusion",
    )

    assert result["recoverable"] is False
    assert result["outcome"] == "needs_human"


def test_recovery_summary_does_not_double_count_recovered_auto():
    counts = {
        "runs": 0,
        "recoverable": 0,
        "recovered_auto": 0,
        "needs_human": 0,
        "timeout": 0,
    }

    _update_recovery_counts(
        counts, {"recoverable": True, "outcome": "recovered_auto"}
    )

    assert counts == {
        "runs": 1,
        "recoverable": 1,
        "recovered_auto": 1,
        "needs_human": 0,
        "timeout": 0,
    }


def test_regression_verification_decisions_are_counted_by_fault():
    runs = [
        {
            "meta": {"fault": "dark", "phase": "regression"},
            "events": [{"kind": "verification", "payload": {"status": "COMMITTED"}}],
        },
        {
            "meta": {"fault": "dark", "phase": "regression"},
            "events": [{"kind": "verification", "payload": {"status": "ROLLED_BACK"}}],
        },
        {
            "meta": {"fault": "dark", "phase": "regression"},
            "events": [{"kind": "verification", "payload": {"status": "INCONCLUSIVE"}}],
        },
        {"meta": {"fault": "dark", "phase": "regression"}, "events": []},
        {
            "meta": {"fault": "dark", "phase": "recovery"},
            "events": [{"kind": "verification", "payload": {"status": "COMMITTED"}}],
        },
    ]

    assert _verification_decisions_by_fault(runs) == {
        "dark": {"committed": 1, "rolled_back": 1, "inconclusive": 2}
    }


def test_a5_reuses_a_frozen_baseline_learned_on_another_scene(tmp_path):
    baseline = _run_training_baseline(tmp_path, "test-revision", 1000)
    _run_standard(
        tmp_path, "test-revision", "A5_single_baseline", "dark", 0.99, 0,
        baseline_data=baseline, warmup=3, fault_windows=12,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A5_single_baseline" / "recovery"
        / "dark-0.99-seed0.sqlite"
    )

    assert chain_valid
    assert any(event["kind"] == "incident" for event in events)
    trained = _read_store(
        tmp_path / "db" / "A5_training" / "recovery"
        / "clean-0.0-seed1000.sqlite"
    )[0]
    metadata = next(event["payload"] for event in trained
                    if event["kind"] == "experiment_metadata")
    assert metadata["trained_baseline"]["updates"] > 0


def test_a6_fake_outage_falls_back_and_opens_circuit_without_spend(tmp_path):
    planner = _a6_planner(load_config(env=False))
    _run_standard(
        tmp_path, "test-revision", "A6_token_factory_outage",
        "dark", 0.99, 0,
        planner=planner, warmup=3, fault_windows=12,
    )
    stores = list(
        (tmp_path / "db" / "A6_token_factory_outage").rglob("*.sqlite")
    )
    events = [event for path in stores for event in _read_store(path)[0]]
    incident = next(event["payload"] for event in events
                    if event["kind"] == "incident")
    outcomes = [
        planner.plan(Incident.model_validate(incident))
        for _ in range(2)
    ]

    assert planner.opened_after_threshold
    assert planner.max_failures >= planner.client.breaker.threshold
    assert all(outcome.source == "fallback" for outcome in outcomes)
    assert sum(event["kind"] == "plan"
               and event["payload"].get("source") == "fallback"
               for event in events) >= 1
    assert all(_read_store(path)[0] for path in stores)
    for path in stores:
        store = EventStore(path)
        try:
            assert store.spent_usd() == 0.0
        finally:
            store.close()


def test_one_seed_smoke_covers_every_arm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchmarks.experiments._code_revision", lambda: "test-revision"
    )
    summary = run_experiments(
        tmp_path / "smoke", seeds=[0], smoke=True
    )

    arms = {row["arm"]: row for row in summary["arms"]}
    assert len(arms) == 8
    assert all(row["runs"] for row in arms.values())
    assert all(row["valid_chains"] for row in arms.values())
    stores = list((tmp_path / "smoke" / "db").rglob("*.sqlite"))
    assert stores
    for path in stores:
        events, _ = _read_store(path)
        assert sum(event["kind"] == "experiment_run" for event in events) == 1
    for arm in ("A3_full_loop", "A4_no_downstream_metric"):
        assert (
            tmp_path / "smoke" / "db" / arm / "recovery"
            / "dark-0.99-seed0.sqlite"
        ).exists()
        assert (
            tmp_path / "smoke" / "db" / arm / "regression"
            / "dark-0.99-seed0.sqlite"
        ).exists()


def test_a6_fallback_ratio_excludes_the_frozen_black_local_plan():
    runs = [
        {
            "meta": {"run_id": "dark-seed0", "fault": "dark"},
            "events": [
                {
                    "kind": "plan",
                    "incident_id": "dark-incident",
                    "seq": 1,
                    "payload": {"source": "fallback"},
                }
            ],
        },
        {
            "meta": {"run_id": "black-seed0", "fault": "frozen_black"},
            "events": [
                {
                    "kind": "plan",
                    "incident_id": "black-incident",
                    "seq": 1,
                    "payload": {"source": "rules"},
                }
            ],
        },
    ]

    result = _a6_plan_summary(runs)

    assert result["planner_incidents"] == 1
    assert result["fallback_incidents"] == 1
    assert result["fallback_ratio"] == 1.0
    assert result["frozen_black_local_plans"] == 1
    assert result["frozen_black_local_plan_label"] == (
        "deterministic local plan, planner not called"
    )


def test_a6_recovery_comparison_requires_identical_run_sets():
    a3_runs = [
        {"meta": {"fault": "dark", "strength": 0.99, "seed": 0}},
        {"meta": {"fault": "defocus", "strength": 1.0, "seed": 0}},
        {
            "meta": {
                "fault": "dark",
                "strength": 0.99,
                "seed": 0,
                "phase": "regression",
            }
        },
    ]
    a6_runs = [
        {"meta": {"fault": "dark", "strength": 0.99, "seed": 0}},
        {"meta": {"fault": "defocus", "strength": 1.0, "seed": 0}},
    ]

    assert _same_recovery_run_set(a3_runs, a6_runs)
    assert not _same_recovery_run_set(
        a3_runs,
        [
            {"meta": {"fault": "dark", "strength": 0.99, "seed": 0}},
            {"meta": {"fault": "defocus", "strength": 1.0, "seed": 1}},
        ],
    )


def test_a2_ticket_requests_do_not_count_as_device_executions():
    summary = _summarize_runs([
        {
            "meta": {
                "arm": "A2_detector_no_actions",
                "fault": "occlusion",
                "settings_unchanged": True,
            },
            "events": [
                {
                    "kind": "execution",
                    "incident_id": "incident-1",
                    "payload": {"status": "ticket"},
                }
            ],
            "chain_valid": True,
            "spend_usd": 0.0,
        }
    ])
    a2 = next(
        row for row in summary["arms"]
        if row["arm"] == "A2_detector_no_actions"
    )

    assert a2["device_executions"] == 0
    assert a2["ticket_requests"] == 1


def test_a7_never_commits_verification_without_frames(tmp_path):
    meta = _run_custom(
        tmp_path, "test-revision", "A7_rtsp_failure_during_action",
        "dark", "dark", 0.99, 0, disconnect_after_execution=True,
        warmup=3, fault_windows=30,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A7_rtsp_failure_during_action"
        / "recovery" / "dark-full-seed0.sqlite"
    )

    assert chain_valid
    assert meta["disconnect_triggered"]
    assert meta["final_state"] in ("HEALTHY", "NEEDS_HUMAN")
    assert meta["no_committed_verification_without_frames"]
    assert all(
        not (
            event["kind"] == "verification"
            and str(event["payload"].get("status", "")).lower() == "committed"
            and next(
                window["payload"]["frames_analyzed"]
                for window in reversed(events)
                if window["kind"] == "experiment_window"
                and window["seq"] < event["seq"]
            ) == 0
        )
        for event in events if event["kind"] == "verification"
    )


@pytest.mark.parametrize("target", ["ACTING", "VERIFYING"])
def test_a8_restart_preserves_invariants_in_acting_and_verifying(tmp_path, target):
    meta = _run_custom(
        tmp_path, "test-revision", "A8_restart_in_every_state",
        "dark", "dark", 0.99, 0, restart_target=target,
        warmup=3, fault_windows=20,
    )

    assert meta["same_incident_id"]
    assert meta["plan_count_unchanged"]
    assert meta["execution_ids_unique"]
    assert meta["settings_match_snapshot_or_commit"]
    assert meta["verify_chain"]


def test_report_regenerates_identically_from_saved_eventstores(tmp_path):
    db = tmp_path / "db" / "A3_full_loop" / "recovery" / "dark.sqlite"
    store = EventStore(db)
    try:
        store.append("incident", {"candidate_faults": ["blackout"]}, "incident-1")
        store.append("experiment_run", {
            "arm": "A3_full_loop",
            "fault": "dark",
            "strength": 0.99,
            "seed": 0,
            "scenario": "dark",
            "run_id": "dark",
            "code_revision": "test-revision",
            "final_state": "HEALTHY",
        })
    finally:
        store.close()

    report_a, markdown_a = generate_report(tmp_path, tmp_path / "report-a")
    report_b, markdown_b = generate_report(tmp_path, tmp_path / "report-b")

    assert report_a == report_b
    assert markdown_a == markdown_b
    assert json.loads((tmp_path / "report-a" / "experiments.json").read_text(
        encoding="utf-8"
    )) == json.loads((tmp_path / "report-b" / "experiments.json").read_text(
        encoding="utf-8"
    ))
    assert "| F8-comparable subset |" in markdown_a
    assert "The F8 classifier returns `recoverable=False` for occlusion" in markdown_a
    assert "## Regression verification decisions by fault family" in markdown_a


def test_live_mode_requires_explicit_yes(tmp_path):
    with pytest.raises(ValueError, match="requires --yes"):
        run_experiments(tmp_path / "out", live=True)
