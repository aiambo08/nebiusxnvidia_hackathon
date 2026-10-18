from benchmarks.recovery import classify_regression


def _event(kind, payload):
    return {"kind": kind, "payload": payload}


def test_no_incident_is_not_executed_and_unchanged_settings_pass():
    result = classify_regression([], {"gain": 1.0}, {"gain": 1.0})

    assert result["regression_executed"] is False
    assert result["settings_unchanged"] is True
    assert result["non_executed_reason"] == "no incident confirmed"
    assert result["regression_gate_pass"] is True


def test_successful_execution_with_exact_rollback_passes():
    snapshot = {"gain": 1.0}
    events = [
        _event("execution", {"status": "success"}),
        _event("rollback", {"ok": True, "restored": snapshot}),
    ]

    result = classify_regression(events, {"gain": 1.0}, snapshot)

    assert result["regression_executed"] is True
    assert result["settings_unchanged"] is None
    assert result["rollback_ok"] is True
    assert result["snapshot_equal"] is True
    assert result["regression_gate_pass"] is True


def test_successful_execution_in_safe_mode_passes():
    result = classify_regression(
        [_event("execution", {"status": "success"})],
        {"safe_mode": False},
        {"safe_mode": True},
    )

    assert result["regression_executed"] is True
    assert result["regression_gate_pass"] is True


def test_successful_execution_without_rollback_or_safe_mode_fails():
    result = classify_regression(
        [_event("execution", {"status": "success"})],
        {"gain": 1.0},
        {"gain": 0.5, "safe_mode": False},
    )

    assert result["regression_executed"] is True
    assert result["snapshot_equal"] is False
    assert result["regression_gate_pass"] is False


def test_non_executed_run_with_changed_settings_fails():
    result = classify_regression([], {"gain": 1.0}, {"gain": 0.5})

    assert result["regression_executed"] is False
    assert result["settings_unchanged"] is False
    assert result["regression_gate_pass"] is False
