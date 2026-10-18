from benchmarks.recovery import (
    REGRESSION_FAMILIES,
    _summarize,
    classify_events,
    classify_regression,
    regression_gate,
)


def _event(kind, payload=None):
    return {"kind": kind, "payload": payload}


def test_classify_events_without_incident_is_recoverable_timeout():
    result = classify_events([], "dark")

    assert result == {
        "recoverable": True,
        "outcome": "timeout",
        "plan_source": None,
    }


def test_classify_events_closed_recovered_without_ticket_is_automatic_recovery():
    result = classify_events(
        [
            _event("incident", {"allowed_actions": ["set_exposure_bounded"]}),
            _event("closed", {"reason": "recovered"}),
        ],
        "dark",
    )

    assert result["outcome"] == "recovered_auto"
    assert result["recoverable"] is True


def test_classify_events_ticket_overrides_recovered_close():
    result = classify_events(
        [
            _event("incident", {"allowed_actions": ["set_exposure_bounded"]}),
            _event("closed", {"reason": "recovered"}),
            _event("ticket"),
        ],
        "dark",
    )

    assert result["outcome"] == "needs_human"


def test_classify_events_needs_human_state_is_reported():
    result = classify_events(
        [
            _event("incident", {"allowed_actions": ["set_exposure_bounded"]}),
            _event("state", {"to": "NEEDS_HUMAN"}),
        ],
        "dark",
    )

    assert result["outcome"] == "needs_human"


def test_classify_events_incident_without_close_times_out():
    result = classify_events(
        [_event("incident", {"allowed_actions": ["set_exposure_bounded"]})],
        "dark",
    )

    assert result["outcome"] == "timeout"


def test_classify_events_requires_fault_remediation_for_recoverability():
    result = classify_events(
        [_event("incident", {"allowed_actions": ["enter_safe_mode"]})],
        "dark",
    )

    assert result["recoverable"] is False


def test_classify_events_uses_last_plan_source():
    result = classify_events(
        [
            _event("incident", {"allowed_actions": ["set_exposure_bounded"]}),
            _event("plan", {"source": "rules"}),
            _event("plan", {"source": "scripted"}),
        ],
        "dark",
    )

    assert result["plan_source"] == "scripted"


def _recovery_rows(recovered: int) -> list[dict]:
    rows = []
    for index in range(100):
        outcome = "recovered_auto" if index < recovered else "timeout"
        if recovered == 84 and index == 99:
            outcome = "needs_human"
        rows.append({
            "fault": "dark",
            "strength": 0.8,
            "recoverable": True,
            "outcome": outcome,
        })
    return rows


def test_recovery_gate_passes_at_exactly_85_percent():
    summary = _summarize(_recovery_rows(85))

    assert summary["recovery_rate"] == 0.85
    assert summary["recovered_auto"] == 85
    assert summary["timeout"] == 15
    assert summary["gate_pass"] is True


def test_recovery_gate_fails_at_84_percent_and_timeouts_are_not_successes():
    summary = _summarize(_recovery_rows(84))

    assert summary["recovery_rate"] == 0.84
    assert summary["recovered_auto"] == 84
    assert summary["timeout"] == 15
    assert summary["needs_human"] == 1
    assert summary["gate_pass"] is False


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


def test_successful_execution_with_non_exact_rollback_fails():
    snapshot = {"gain": 1.0}
    result = classify_regression(
        [
            _event("execution", {"status": "success"}),
            _event("rollback", {"ok": True, "restored": snapshot}),
        ],
        snapshot,
        {"gain": 0.5, "safe_mode": False},
    )

    assert result["regression_executed"] is True
    assert result["rollback_ok"] is True
    assert result["snapshot_equal"] is False
    assert result["regression_pass"] is False
    assert result["regression_gate_pass"] is False


def test_non_executed_run_with_changed_settings_fails():
    result = classify_regression([], {"gain": 1.0}, {"gain": 0.5})

    assert result["regression_executed"] is False
    assert result["settings_unchanged"] is False
    assert result["regression_pass"] is False
    assert result["regression_gate_pass"] is False


def _gate_row(
    fault,
    *,
    executed=True,
    rollback_ok=True,
    initial=None,
    final=None,
    snapshot=None,
):
    initial = {"gain": 1.0} if initial is None else initial
    final = initial if final is None else final
    snapshot = initial if snapshot is None and rollback_ok else snapshot
    return {
        "fault": fault,
        "strength": 1.0,
        "regression_executed": executed,
        "rollback_ok": rollback_ok,
        "initial_settings": initial,
        "pre_action_snapshot_settings": snapshot,
        "final_settings": final,
    }


def _passing_gate_rows():
    return [_gate_row(fault) for fault in REGRESSION_FAMILIES]


def test_regression_gate_fails_an_executed_regression_without_containment():
    rows = _passing_gate_rows()
    rows[0] = _gate_row(
        "dark",
        rollback_ok=False,
        final={"gain": 0.5},
        snapshot=None,
    )

    result = regression_gate(rows)

    assert result["by_fault"]["dark"]["executed_pass"] == 0
    assert result["gate_pass"] is False


def test_regression_gate_fails_non_executed_run_with_changed_settings():
    rows = _passing_gate_rows()
    rows[0] = _gate_row(
        "dark",
        executed=False,
        rollback_ok=False,
        initial={"gain": 1.0},
        final={"gain": 0.5},
    )
    rows.append(_gate_row("dark"))

    result = regression_gate(rows)

    assert result["by_fault"]["dark"]["not_executed_unchanged"] == 0
    assert result["coverage_floor"]["pass"] is True
    assert result["gate_pass"] is False


def test_regression_gate_requires_exact_snapshot_settings_after_rollback():
    rows = _passing_gate_rows()
    rows[0] = _gate_row(
        "dark",
        rollback_ok=True,
        initial={"gain": 1.0},
        final={"gain": 0.9},
        snapshot={"gain": 1.0},
    )

    result = regression_gate(rows)

    assert result["by_fault"]["dark"]["executed_pass"] == 0
    assert result["gate_pass"] is False


def test_regression_gate_does_not_count_failed_execution_as_executed():
    failed = classify_regression(
        [_event("execution", {"status": "failed"})],
        {"gain": 1.0},
        {"gain": 1.0},
        "HEALTHY",
    )
    rows = _passing_gate_rows()
    rows[1] = {"fault": "defocus", "strength": 1.0, **failed}

    result = regression_gate(rows)

    assert result["executed"] == len(REGRESSION_FAMILIES) - 1
    assert result["by_fault"]["defocus"]["executed"] == 0
    assert result["by_fault"]["defocus"]["not_executed"] == 1
    assert result["gate_pass"] is False


def test_regression_gate_requires_executed_coverage_in_every_family():
    rows = [
        _gate_row(fault, executed=fault != "dark")
        for fault in REGRESSION_FAMILIES
    ]

    result = regression_gate(rows)

    assert result["coverage_floor"] == {
        "pass": False,
        "required_families": list(REGRESSION_FAMILIES),
        "missing_families": ["dark"],
    }
    assert result["gate_pass"] is False


def test_regression_gate_fails_when_no_rows_are_executed():
    rows = [_gate_row(fault, executed=False) for fault in REGRESSION_FAMILIES]

    result = regression_gate(rows)

    assert result["executed"] == 0
    assert result["coverage_floor"]["missing_families"] == list(REGRESSION_FAMILIES)
    assert result["gate_pass"] is False


def test_regression_gate_passes_clean_rows_and_reports_family_counts():
    result = regression_gate(_passing_gate_rows())

    assert result["gate_pass"] is True
    assert result["coverage_floor"]["pass"] is True
    assert result["executed"] == result["executed_pass"] == 4
    assert result["not_executed"] == result["not_executed_unchanged"] == 0
    assert all(
        result["by_fault"][fault] == {
            "runs": 1,
            "executed": 1,
            "executed_pass": 1,
            "not_executed": 0,
            "not_executed_unchanged": 0,
        }
        for fault in REGRESSION_FAMILIES
    )
