from __future__ import annotations

import json

import pytest

from benchmarks.experiments import (
    _NoCallPlanner,
    _a6_planner,
    _run_custom,
    _run_standard,
    _run_training_baseline,
    generate_report,
    run_experiments,
)
from benchmarks.recovery import ScriptedPlanner, REGRESSION_ACTIONS
from reliability_agent.config import load_config
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
        planner=planner, detector_only=True, warmup=3, fault_windows=20,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A1_local_detector_only" / "dark-0.99-seed0.sqlite"
    )

    assert chain_valid
    assert planner.calls == 0
    assert any(event["kind"] == "incident" for event in events)
    assert not any(event["kind"] in ("plan", "execution") for event in events)


def test_a2_emits_a_plan_without_executing_or_changing_settings(tmp_path):
    _run_standard(
        tmp_path, "test-revision", "A2_detector_no_actions", "dark", 0.99, 0,
        auto_execute=False, warmup=3, fault_windows=20,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A2_detector_no_actions" / "dark-0.99-seed0.sqlite"
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
    assert run["settings_unchanged"]


def test_a3_and_a4_smoke_recovery_and_visual_metric_ablation(tmp_path):
    _run_standard(
        tmp_path, "test-revision", "A3_full_loop", "dark", 0.99, 0,
        warmup=3, fault_windows=20,
    )
    action, arguments = REGRESSION_ACTIONS["dark"]
    _run_standard(
        tmp_path, "test-revision", "A4_no_downstream_metric", "dark", 0.99, 0,
        planner=ScriptedPlanner(action, arguments), downstream_ablation=True,
        warmup=3, fault_windows=20, extra_metadata={"phase": "regression"},
    )

    for arm in ("A3_full_loop", "A4_no_downstream_metric"):
        files = list((tmp_path / "db" / arm).glob("*.sqlite"))
        assert len(files) == 1
        events, chain_valid = _read_store(files[0])
        assert chain_valid
        assert any(event["kind"] == "incident" for event in events)


def test_a5_reuses_a_frozen_baseline_learned_on_another_scene(tmp_path):
    baseline = _run_training_baseline(tmp_path, "test-revision", 1000)
    _run_standard(
        tmp_path, "test-revision", "A5_single_baseline", "dark", 0.99, 0,
        baseline_data=baseline, warmup=3, fault_windows=20,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A5_single_baseline" / "dark-0.99-seed0.sqlite"
    )

    assert chain_valid
    assert any(event["kind"] == "incident" for event in events)
    trained = _read_store(
        tmp_path / "db" / "A5_training" / "clean-0.0-seed1000.sqlite"
    )[0]
    training_run = next(event["payload"] for event in reversed(trained)
                        if event["kind"] == "experiment_run")
    assert training_run["trained_baseline"]["updates"] > 0


def test_a6_fake_outage_falls_back_and_opens_circuit_without_spend(tmp_path):
    planner = _a6_planner(load_config(env=False))
    for seed in range(3):
        _run_standard(
            tmp_path, "test-revision", "A6_token_factory_outage",
            "dark", 0.99, seed,
            planner=planner, warmup=3, fault_windows=20,
        )
    stores = list((tmp_path / "db" / "A6_token_factory_outage").glob("*.sqlite"))
    events = [event for path in stores for event in _read_store(path)[0]]

    assert planner.opened_after_threshold
    assert planner.max_failures >= planner.client.breaker.threshold
    assert sum(event["kind"] == "plan"
               and event["payload"].get("source") == "fallback"
               for event in events) >= 3
    assert all(_read_store(path)[0] for path in stores)
    for path in stores:
        store = EventStore(path)
        try:
            assert store.spent_usd() == 0.0
        finally:
            store.close()


def test_one_seed_smoke_covers_every_arm(tmp_path):
    summary = run_experiments(
        tmp_path / "smoke", seeds=[0], smoke=True
    )

    arms = {row["arm"]: row for row in summary["arms"]}
    assert len(arms) == 8
    assert all(row["runs"] for row in arms.values())
    assert all(row["valid_chains"] for row in arms.values())


def test_a7_never_commits_verification_without_frames(tmp_path):
    meta = _run_custom(
        tmp_path, "test-revision", "A7_rtsp_failure_during_action",
        "dark", "dark", 0.99, 0, disconnect_after_execution=True,
        warmup=3, fault_windows=30,
    )
    events, chain_valid = _read_store(
        tmp_path / "db" / "A7_rtsp_failure_during_action"
        / "dark-full-seed0.sqlite"
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
        warmup=3, fault_windows=30,
    )

    assert meta["same_incident_id"]
    assert meta["plan_count_unchanged"]
    assert meta["execution_ids_unique"]
    assert meta["settings_match_snapshot_or_commit"]
    assert meta["verify_chain"]


def test_report_regenerates_identically_from_saved_eventstores(tmp_path):
    db = tmp_path / "db" / "A3_full_loop" / "dark.sqlite"
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


def test_live_mode_requires_explicit_yes(tmp_path):
    with pytest.raises(ValueError, match="requires --yes"):
        run_experiments(tmp_path / "out", live=True)
