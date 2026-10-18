from benchmarks.recovery import run_smoke


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
