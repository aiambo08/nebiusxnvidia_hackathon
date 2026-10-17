import copy
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from benchmarks.golden import (
    INJECTION_METRIC,
    LABELS,
    NO_CAP_VARIANTS,
    SCENARIOS,
    VARIANT_SEEDS,
    build_golden,
    grade,
    summarize,
)
from reliability_agent.contracts.models import (
    ActionName,
    Evidence,
    FaultType,
    Incident,
    NemotronPlan,
    PlanAction,
    TokenUsage,
)
from reliability_agent.nemotron import BudgetGuard, NemotronPlanner, make_planner
from reliability_agent.nemotron.planner import PlanOutcome
from reliability_agent.policy import PolicyGate
from scripts import eval_nemotron
from tests.conftest import make_window


class FakeSDK:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            model=kw["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200),
        )


@pytest.fixture(scope="module")
def golden_cases():
    return build_golden()


def _model_reply(diagnosis="blackout", action="set_exposure_bounded", arguments=None):
    return json.dumps({
        "diagnosis": diagnosis,
        "confidence": 0.8,
        "evidence_refs": [],
        "action": {"name": action, "arguments": arguments or {"delta_ev": 1.0}},
        "verification": {
            "window_seconds": 10,
            "primary_metric": "task.success_rate",
            "minimum_relative_improvement": 0.1,
            "guard_metrics": [],
        },
        "human_message": "Synthetic test response.",
    })


def _outcome(action, arguments=None, *, diagnosis=FaultType.BLACKOUT, source="nemotron",
             error=None, attempts=1, valid_first_try=True):
    plan = NemotronPlan(
        diagnosis=diagnosis,
        confidence=0.8,
        action=PlanAction(name=ActionName(action), arguments=arguments or {}),
        human_message="Synthetic test response.",
    )
    return PlanOutcome(plan, TokenUsage(model="fake", prompt_version="diagnose_v1"),
                       source, attempts, error, valid_first_try)


def _planner(cfg, replies):
    sdk = FakeSDK(replies)
    planner = make_planner(cfg, "sentinel-test-key", BudgetGuard(), sdk_client=sdk)
    assert isinstance(planner, NemotronPlanner)
    return planner, sdk


def _summary_row(*, split="test", valid=True, correct=True, cost=0.0001, attempts=1,
                 scenario="dark", variant="base", action="set_exposure_bounded"):
    return {
        "case_id": f"{scenario}-{variant}-{split}",
        "split": split,
        "scenario": scenario,
        "variant": variant,
        "expected_actions": ["set_exposure_bounded"],
        "valid": valid,
        "correct": correct,
        "policy_ok": True,
        "diagnosis_ok": True,
        "valid_first_try": valid,
        "action": action,
        "attempts": attempts,
        "cost": cost,
        "latency_ms": 25.0,
        "model": "fake-model",
        "prompt_version": "diagnose_v1",
    }


def _simple_case(*, split="test", no_cap=False):
    capabilities = ["exposure", "autofocus", "restart"]
    if no_cap:
        capabilities.remove("exposure")
    incident = Incident(
        camera_id="test-camera",
        candidate_faults=[FaultType.BLACKOUT],
        evidence=[Evidence(metric="visual.black_pixel_ratio", value=0.9)],
        capabilities=capabilities,
        allowed_actions=PolicyGate().allowed_for(capabilities),
        telemetry=make_window(),
    )
    expected_actions = (
        ["enter_safe_mode", "needs_human", "request_manual_cleaning"]
        if no_cap else ["set_exposure_bounded"]
    )
    return {
        "case_id": f"dark-{'no_cap' if no_cap else 'base'}-s06",
        "split": split,
        "scenario": "dark",
        "variant": "no_cap" if no_cap else "base",
        "seed": 6,
        "expected_fault": "blackout",
        "expected_actions": expected_actions,
        "delta_ev_sign": 1,
        "incident": incident.model_dump(mode="json"),
    }


def _write_cases(path, cases):
    path.write_text("".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8")


def test_builder_recipe_counts_splits_labels_and_variants(golden_cases):
    assert len(golden_cases) == 136
    assert {case["scenario"] for case in golden_cases} == set(SCENARIOS)
    assert not {"frozen_black", "bad_action"} & {case["scenario"] for case in golden_cases}
    assert {case["variant"] for case in golden_cases} == {"base", "no_cap", "injection"}
    assert len({case["case_id"] for case in golden_cases}) == len(golden_cases)

    counts = Counter((case["variant"], case["split"]) for case in golden_cases)
    assert counts == {
        ("base", "dev"): 30,
        ("base", "test"): 70,
        ("no_cap", "dev"): 8,
        ("no_cap", "test"): 8,
        ("injection", "dev"): 10,
        ("injection", "test"): 10,
    }
    assert Counter(case["split"] for case in golden_cases) == {"dev": 48, "test": 88}

    for case in golden_cases:
        assert case["split"] == ("dev" if case["seed"] <= 5 else "test")
        incident = case["incident"]
        assert incident["incident_id"] == f"golden-{case['case_id']}"
        assert incident["opened_at"] == "2026-10-17T00:00:00Z"
        expected_fault, base_actions, delta_sign = LABELS[case["scenario"]]
        assert case["expected_fault"] == expected_fault
        assert case["delta_ev_sign"] == delta_sign
        if case["variant"] in ("base", "injection"):
            assert case["expected_actions"] == sorted(base_actions)
        if case["variant"] == "no_cap":
            cap, variant_actions = NO_CAP_VARIANTS[case["scenario"]]
            assert cap not in incident["capabilities"]
            assert incident["allowed_actions"] == [
                action.value for action in PolicyGate().allowed_for(incident["capabilities"])
            ]
            assert case["expected_actions"] == sorted(variant_actions)
            assert case["seed"] in VARIANT_SEEDS
        if case["variant"] == "injection":
            assert incident["evidence"][0]["metric"] == INJECTION_METRIC


def test_committed_golden_matches_fresh_build_on_recipe_fields(golden_cases):
    path = eval_nemotron.REPO_ROOT / "benchmarks" / "golden" / "golden_v1.jsonl"
    committed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fields = ("case_id", "split", "scenario", "variant", "seed", "expected_fault",
              "expected_actions", "delta_ev_sign")
    assert len(committed) == len(golden_cases)
    for built, saved in zip(golden_cases, committed, strict=True):
        assert {field: built[field] for field in fields} == {
            field: saved[field] for field in fields
        }
        for field in ("candidate_faults", "capabilities", "allowed_actions"):
            assert built["incident"][field] == saved["incident"][field]


def test_grader_accepts_correct_exposure_action_and_sign():
    result = grade(_simple_case(), _outcome("set_exposure_bounded", {"delta_ev": 1.5}),
                   PolicyGate())
    assert result["valid"] and result["policy_ok"] and result["correct"]
    assert result["action"] == "set_exposure_bounded"
    assert result["args"] == {"delta_ev": 1.5}


@pytest.mark.parametrize("arguments", [{"delta_ev": -1.0}, {"delta_ev": 0.0},
                                       {"delta_ev": True}, {}])
def test_grader_rejects_wrong_or_invalid_exposure_delta(arguments):
    result = grade(_simple_case(), _outcome("set_exposure_bounded", arguments), PolicyGate())
    assert result["valid"] and not result["correct"]


def test_grader_rejects_action_outside_expected_set():
    result = grade(_simple_case(), _outcome("trigger_autofocus"), PolicyGate())
    assert result["valid"] and not result["correct"]


def test_grader_zero_delta_is_incorrect_for_overexposure():
    case = _simple_case()
    case["scenario"] = "overexposure"
    case["expected_fault"] = "overexposure"
    case["expected_actions"] = ["set_exposure_bounded"]
    case["delta_ev_sign"] = -1
    incident = Incident.model_validate(case["incident"])
    incident.candidate_faults = [FaultType.OVEREXPOSURE]
    case["incident"] = incident.model_dump(mode="json")
    result = grade(case, _outcome("set_exposure_bounded", {"delta_ev": 0.0},
                                  diagnosis=FaultType.OVEREXPOSURE), PolicyGate())
    assert result["valid"] and result["policy_ok"]
    assert not result["correct"]


def test_disallowed_reply_becomes_invalid_human_fallback(cfg):
    case = _simple_case(no_cap=True)
    planner, sdk = _planner(cfg, [
        _model_reply(action="set_exposure_bounded", arguments={"delta_ev": 1.0}),
        _model_reply(action="set_exposure_bounded", arguments={"delta_ev": 1.0}),
    ])
    outcome = planner.plan(Incident.model_validate(case["incident"]))
    result = grade(case, outcome, PolicyGate())
    assert len(sdk.calls) == 2
    assert outcome.plan.action.name is ActionName.NEEDS_HUMAN
    assert not result["valid"] and not result["correct"]


def test_nemotron_mode_rejects_rules_source():
    result = grade(_simple_case(), _outcome("set_exposure_bounded", {"delta_ev": 1.0},
                                             source="rules"), PolicyGate())
    assert not result["valid"] and not result["correct"]


def test_rules_source_is_valid_only_in_baseline_mode():
    outcome = _outcome("set_exposure_bounded", {"delta_ev": 1.0}, source="rules")
    assert not grade(_simple_case(), outcome, PolicyGate())["valid"]
    result = grade(_simple_case(), outcome, PolicyGate(), baseline=True)
    assert result["valid"] and result["policy_ok"] and result["correct"]


def test_fallback_diagnosis_and_first_try_are_invalid_when_plan_is_invalid():
    outcome = _outcome("needs_human", diagnosis=FaultType.BLACKOUT,
                       source="fallback", error="timeout", valid_first_try=True)
    result = grade(_simple_case(), outcome, PolicyGate())
    assert not result["valid"]
    assert not result["diagnosis_ok"]
    assert not result["valid_first_try"]


def test_planner_failure_and_cache_outcomes_are_invalid(cfg):
    case = _simple_case()
    incident = Incident.model_validate(case["incident"])

    timeout_planner, _ = _planner(cfg, [TimeoutError()])
    timeout = timeout_planner.plan(incident)

    circuit_planner, circuit_sdk = _planner(cfg, [])
    for _ in range(circuit_planner.client.breaker.threshold):
        circuit_planner.client.breaker.failure()
    circuit = circuit_planner.plan(incident)
    assert circuit_sdk.calls == []

    no_key_planner = make_planner(cfg, None, BudgetGuard())
    no_key = no_key_planner.plan(incident)

    cache_planner, cache_sdk = _planner(cfg, [_model_reply()])
    cache_planner.plan(incident)
    cached = cache_planner.plan(incident)
    assert cached.source == "cache" and len(cache_sdk.calls) == 1

    for outcome in (timeout, circuit, no_key, cached):
        result = grade(case, outcome, PolicyGate())
        assert not result["valid"] and not result["correct"]


def test_invalid_json_twice_is_invalid(cfg):
    case = _simple_case()
    planner, sdk = _planner(cfg, ["not json", "still not json"])
    outcome = planner.plan(Incident.model_validate(case["incident"]))
    result = grade(case, outcome, PolicyGate())
    assert len(sdk.calls) == 2
    assert not result["valid"] and not result["correct"]


def test_invalid_once_then_valid_is_valid_but_not_first_try(cfg):
    case = _simple_case()
    planner, sdk = _planner(cfg, ["not json", _model_reply()])
    outcome = planner.plan(Incident.model_validate(case["incident"]))
    result = grade(case, outcome, PolicyGate())
    assert len(sdk.calls) == 2
    assert result["valid"] and result["correct"]
    assert not result["valid_first_try"] and result["attempts"] == 2


def test_out_of_range_exposure_is_not_policy_ok(cfg):
    case = _simple_case()
    planner, _ = _planner(cfg, [_model_reply(arguments={"delta_ev": 5.0})])
    result = grade(case, planner.plan(Incident.model_validate(case["incident"])), PolicyGate())
    assert result["valid"]
    assert not result["policy_ok"] and not result["correct"]


def test_summarize_all_correct_passes_three_f6_boxes(cfg):
    summary = summarize([_summary_row() for _ in range(10)], cfg)
    assert all(box["status"] == "PASS" for box in summary["gate"]["boxes"].values())
    assert summary["gate"]["schema_valid_rate"] == 1.0
    assert summary["gate"]["action_accuracy"] == 1.0


def test_summarize_89_percent_action_accuracy_fails_action_box(cfg):
    rows = [_summary_row(correct=i < 89) for i in range(100)]
    summary = summarize(rows, cfg)
    assert summary["gate"]["action_accuracy"] == pytest.approx(0.89)
    assert summary["gate"]["boxes"]["action_accuracy"]["status"] == "FAIL"


def test_summarize_97_percent_validity_fails_schema_box(cfg):
    rows = [_summary_row(valid=i < 97, correct=i < 97) for i in range(100)]
    summary = summarize(rows, cfg)
    assert summary["gate"]["schema_valid_rate"] == pytest.approx(0.97)
    assert summary["gate"]["boxes"]["schema_valid"]["status"] == "FAIL"


def test_summarize_excludes_dev_rows_from_gate_metrics(cfg):
    rows = ([_summary_row(split="dev", valid=False, correct=False) for _ in range(50)]
            + [_summary_row(split="test") for _ in range(10)])
    summary = summarize(rows, cfg)
    assert summary["row_count"] == 60
    assert summary["gate"]["row_count"] == 10
    assert summary["gate"]["schema_valid_rate"] == 1.0
    assert summary["gate"]["action_accuracy"] == 1.0


def test_summarize_uses_configured_soft_cap_for_cost_projection(cfg):
    config = copy.deepcopy(cfg)
    config["budget"]["soft_cap_usd"] = 0.02
    summary = summarize([_summary_row(cost=0.001)], config)
    assert summary["gate"]["projected_300"] == pytest.approx(0.3)
    assert summary["gate"]["boxes"]["projected_300"]["threshold"] == 0.02
    assert summary["gate"]["boxes"]["projected_300"]["status"] == "FAIL"


def test_summarize_gate_threshold_boundaries(cfg):
    config = copy.deepcopy(cfg)
    config["budget"]["soft_cap_usd"] = 0.3

    schema_rows = [_summary_row(valid=i < 98, correct=i < 98, cost=0.0)
                   for i in range(100)]
    accuracy_rows = [_summary_row(correct=i < 90, cost=0.0) for i in range(100)]
    exact_cost = summarize([_summary_row(cost=0.001)], config)
    over_cost = summarize([_summary_row(cost=0.0010000001)], config)

    assert summarize(schema_rows, config)["gate"]["boxes"]["schema_valid"]["status"] == "PASS"
    assert summarize(accuracy_rows, config)["gate"]["boxes"]["action_accuracy"]["status"] == "PASS"
    assert exact_cost["gate"]["projected_300"] == 0.3
    assert exact_cost["gate"]["boxes"]["projected_300"]["status"] == "PASS"
    assert over_cost["gate"]["boxes"]["projected_300"]["status"] == "FAIL"


def test_cost_estimate_accounts_for_both_planner_attempts(cfg):
    estimate = eval_nemotron.estimate_cost(cfg, "fast", case_count=3, repeats=2)
    assert estimate["case_runs"] == 6
    assert estimate["max_api_calls"] == 2 * estimate["case_runs"]


def test_cost_metrics_use_attempts_and_incident_cost(cfg):
    rows = [
        _summary_row(cost=0.0002, attempts=2),
        _summary_row(cost=0.0004, attempts=2),
    ]
    summary = summarize(rows, cfg)
    assert summary["gate"]["mean_cost_per_call"] == pytest.approx(0.00015)
    assert summary["gate"]["mean_cost_per_incident"] == pytest.approx(0.0003)
    assert summary["gate"]["mean_cost_per_incident"] == pytest.approx(
        2 * summary["gate"]["mean_cost_per_call"])
    assert summary["gate"]["projected_300"] == pytest.approx(0.09)


def test_eval_without_yes_prints_estimate_without_sdk_call(
        monkeypatch, tmp_path, capsys, cfg):
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_simple_case()])
    sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key",
                        lambda: pytest.fail("dry-run must not request an API key"))
    result = eval_nemotron.main(
        ["--split", "test", "--repeats", "3"],
        sdk_client=sdk,
        cases_path=cases_path,
        report_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "Cases: 1 × 3 repeats = 3 case runs" in output
    assert "Upper-bound cost:" in output
    assert sdk.calls == []
    assert not (tmp_path / "reports").exists()


def test_eval_over_max_usd_exits_three_before_any_call(
        monkeypatch, tmp_path, capsys, cfg):
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_simple_case()])
    sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key",
                        lambda: pytest.fail("budget refusal must precede key lookup"))
    result = eval_nemotron.main(
        ["--split", "test", "--repeats", "3", "--yes", "--max-usd", "0.0000001"],
        sdk_client=sdk,
        cases_path=cases_path,
        report_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )
    output = capsys.readouterr()
    assert result == 3
    assert "Upper-bound cost:" in output.out
    assert sdk.calls == []
    assert not (tmp_path / "reports").exists()


def test_live_cli_requires_key_when_yes_is_given(monkeypatch, tmp_path, capsys):
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_simple_case()])
    sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key", lambda: None)
    result = eval_nemotron.main(
        ["--split", "test", "--repeats", "1", "--yes"],
        sdk_client=sdk,
        cases_path=cases_path,
        report_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )
    output = capsys.readouterr()
    assert result == 2
    assert "NEBIUS_API_KEY is not set." in output.err
    assert sdk.calls == []


def test_report_does_not_include_fake_key_or_auth_headers(
        monkeypatch, tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_simple_case()])
    sentinel = "test-only-sentinel-key-72c1"
    sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key", lambda: sentinel)
    result = eval_nemotron.main(
        ["--split", "test", "--repeats", "1", "--yes"],
        sdk_client=sdk,
        cases_path=cases_path,
        report_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs" / "eval",
    )
    assert result == 0
    assert len(sdk.calls) == 1
    reports = list((tmp_path / "reports").glob("*"))
    assert {path.suffix for path in reports} == {".md", ".json"}
    for report in reports:
        content = report.read_text(encoding="utf-8")
        assert sentinel not in content
        assert "bearer" not in content.lower()
        assert "api_key" not in content.lower()
    ledger = next((tmp_path / "runs" / "eval").glob("*.jsonl"))
    ledger_content = ledger.read_text(encoding="utf-8")
    assert sentinel not in ledger_content
    assert "bearer" not in ledger_content.lower()
    assert "api_key" not in ledger_content.lower()
    report_text = next((tmp_path / "reports").glob("*.md")).read_text(encoding="utf-8")
    assert "candidate_faults[0] determines the label" in report_text
    assert "[golden-rules-baseline-test.md](golden-rules-baseline-test.md)" in report_text


def test_run_eval_clears_cache_before_each_repeat(cfg):
    case = _simple_case()
    planner, sdk = _planner(cfg, [_model_reply(), _model_reply(), _model_reply()])
    rows = eval_nemotron.run_eval([case], planner, repeats=3)
    assert len(sdk.calls) == 3
    assert [row["source"] for row in rows] == ["nemotron"] * 3


def test_budget_spend_reconciles_timeout_after_invalid_first_reply(cfg):
    case = _simple_case()
    planner, _ = _planner(cfg, ["not json", TimeoutError()])
    rows = eval_nemotron.run_eval([case], planner, repeats=1)
    spent = planner.budget.spent_usd
    assert rows[0]["cost"] == 0
    assert spent > 0
    summary = summarize(rows, cfg, budget_spent_usd=spent, split="test")
    assert summary["run_total_usd"] == pytest.approx(spent)
    assert summary["gate"]["projected_300"] == pytest.approx(spent * 300)


def test_max_usd_exact_boundary_proceeds_but_just_under_exits_three(
        monkeypatch, tmp_path, capsys, cfg):
    case_path = tmp_path / "cases.jsonl"
    _write_cases(case_path, [_simple_case()])
    estimate = eval_nemotron.estimate_cost(cfg, "fast", case_count=1, repeats=1)
    exact_sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key", lambda: "sentinel-test-key")
    exact = eval_nemotron.main(
        ["--split", "test", "--repeats", "1", "--yes",
         "--max-usd", f"{estimate['upper_bound_usd']:.17g}"],
        sdk_client=exact_sdk,
        cases_path=case_path,
        report_dir=tmp_path / "exact-reports",
        runs_dir=tmp_path / "exact-runs",
    )
    assert exact == 0
    assert exact_sdk.calls

    over_sdk = FakeSDK([_model_reply()])
    monkeypatch.setattr(eval_nemotron, "api_key",
                        lambda: pytest.fail("over-budget run must stop before key lookup"))
    over = eval_nemotron.main(
        ["--split", "test", "--repeats", "1", "--yes",
         "--max-usd", f"{estimate['upper_bound_usd'] - 1e-9:.12f}"],
        sdk_client=over_sdk,
        cases_path=case_path,
        report_dir=tmp_path / "over-reports",
        runs_dir=tmp_path / "over-runs",
    )
    assert over == 3
    assert over_sdk.calls == []


def test_rules_baseline_needs_no_key_or_yes_and_writes_named_report(
        monkeypatch, tmp_path):
    case_path = tmp_path / "cases.jsonl"
    _write_cases(case_path, [_simple_case()])
    sdk = FakeSDK([])
    monkeypatch.setattr(eval_nemotron, "api_key",
                        lambda: pytest.fail("rules baseline must not request a key"))
    result = eval_nemotron.main(
        ["--split", "test", "--planner", "rules"],
        sdk_client=sdk,
        cases_path=case_path,
        report_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )
    assert result == 0
    assert sdk.calls == []
    assert (tmp_path / "reports" / "golden-rules-baseline-test.md").is_file()
    summary = json.loads(
        (tmp_path / "reports" / "golden-rules-baseline-test.json").read_text(
            encoding="utf-8"))
    assert summary["summary"]["gate"]["schema_valid_rate"] == 1.0
    assert summary["summary"]["gate"]["action_accuracy"] == 1.0


def test_dev_eval_filters_cases_and_ledger(tmp_path):
    runs_dir = tmp_path / "runs"
    result = eval_nemotron.main(
        ["--split", "dev", "--planner", "rules", "--repeats", "1"],
        report_dir=tmp_path / "reports",
        runs_dir=runs_dir,
    )
    assert result == 0
    ledger = next(runs_dir.glob("*.jsonl"))
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 48
    assert {row["split"] for row in rows} == {"dev"}
    golden_cases = eval_nemotron.load_golden()
    test_ids = {case["case_id"] for case in golden_cases if case["split"] == "test"}
    assert not test_ids & {row["case_id"] for row in rows}
