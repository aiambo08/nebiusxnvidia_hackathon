from benchmarks.recovery import run_smoke
from reliability_agent.demo import demo_config, run_scenario
from reliability_agent.nemotron.planner import RuleBasedPlanner
from reliability_agent.storage import EventStore


def test_recovery_benchmark_smoke_uses_event_store_outcomes():
    result = run_smoke()
    assert result["recovery"]["recoverable"] is True
    assert result["recovery"]["outcome"] in {
        "recovered_auto",
        "needs_human",
        "timeout",
    }
    assert result["regression"]["plan_source"] == "scripted"
    assert result["regression"]["regression_executed"] is True
    assert result["regression"]["regression_gate_pass"] is True
    assert result["regression"]["rollback_ok"] is True
    assert result["regression"]["snapshot_equal"] is True


def test_run_scenario_applies_requested_fault_strength_through_source():
    store = EventStore()
    observed = []

    def observe_source(source):
        set_fault = source.set_fault

        def record_fault_strength(fault, strength=1.0):
            set_fault(fault, strength)
            if fault is not None:
                observed.append(source.fault_strength)

        source.set_fault = record_fault_strength

    try:
        run_scenario(
            "dark",
            planner=RuleBasedPlanner(),
            cfg=demo_config(),
            store=store,
            fault_strength=0.37,
            seed=0,
            on_source=observe_source,
        )
    finally:
        store.close()

    assert observed == [0.37]
