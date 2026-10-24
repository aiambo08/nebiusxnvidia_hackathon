# F8 — Verification & rollback: independent gate review

- **Reviewer:** independent Cursor review agent (Evaluation role, no authorship of this repo)
- **Date:** 2026-10-24
- **Repository:** https://github.com/aiambo08/nebiusxnvidia_hackathon, branch `docs/evaluation-f8-reconcile`
- **Revision reviewed:** `d67f08a6c994bcad360c57f0167555fb9f02e643` (fresh clone into `C:\Users\niaib\ra-f8-review`)
- **Environment:** Windows 10.0.26300, PowerShell, Python 3.13.9 (`C:\Users\niaib\anaconda3\python.exe` → `.venv`),
  `pip install -e ".[dev,api]"`. Offline: `NEBIUS_API_KEY` unset, no Token Factory calls.
- **Procedure:** `.agents/skills/ra-phase-gate-review/SKILL.md`. All F8 boxes are judged as **SIMULATION** claims,
  as scoped in `docs/phases-and-gates.md` lines 144–151.
- **Project code was not modified.** Tests ran with `-p no:cacheprovider`; the worktree stayed clean throughout.

## Verdict

**Phase F8 — Verification & rollback: NOT PASSED (6/7 boxes PROVEN, 1 PARTIAL).**

The one gap is evidence for box 5 ("execution failure distinguished from 'no improvement'"). The behavior looks
correct in the orchestrator code and other tests cover each half of it, but the test cited in the gate does not
check the claim (details below). Everything else, including the benchmark, reproduced exactly.

## Per-box results

| # | F8 box (SIMULATION) | Status | Evidence (run by the reviewer) |
|---|---|---|---|
| 1 | Each MVP action has a full commit test and a rollback test (simulated device) | **PROVEN** | `tests/e2e/test_action_commit_rollback.py` → `10 passed in 0.36s`. These are parametrized `test_each_mvp_action_commits[...]` and `test_each_mvp_action_rolls_back_without_improvement[...]` over all 5 MVP actions (`restart_capture`, `switch_stream_profile`, `set_exposure_bounded`, `trigger_autofocus`, `enter_safe_mode`). Commit asserts: policy approved, execution `success`, verification `committed`, closed `recovered`, state `HEALTHY`, no pending snapshots, hash chain valid. Rollback asserts: verification `rolled_back`, rollback `ok`, `device.get_settings() == original_settings`, last transitions `rolled_back → needs_human`. |
| 2 | ≥ 85% of recoverable incidents resolved without humans on the test bench | **PROVEN** | Reproduced `scripts/bench_recovery.py`: **87/100 (87.0%)**, 3 needs-human, 10 timeouts, `gate_pass: true`. All 100 per-run records are identical to the committed JSON. Classifier tests: `tests/unit/test_recovery_classifier.py` → `22 passed`, including `test_recovery_gate_passes_at_exactly_85_percent` and `test_recovery_gate_fails_at_84_percent_and_timeouts_are_not_successes`. |
| 3 | 100% regression containment | **PROVEN** (governance note below) | Reproduced: raw **45/50**; executed **45/45** contained; non-executed **5/5** settings unchanged; coverage floor PASS (no missing families); `gate_pass: true`. All 45 executed runs passed by **exact snapshot restore** (0 by safe mode) and ended in `NEEDS_HUMAN`. Containment tests in `test_recovery_classifier.py` include `test_successful_execution_without_rollback_or_safe_mode_fails`, `test_successful_execution_with_non_exact_rollback_fails`, `test_regression_gate_fails_non_executed_run_with_changed_settings`, `test_regression_gate_requires_executed_coverage_in_every_family` and `test_regression_gate_fails_when_no_rows_are_executed`. |
| 4 | Rollback restores exactly the previous versioned config | **PROVEN** | The rollback leg of `test_action_commit_rollback.py` asserts exact dict equality with the pre-action settings. `Executor.execute` deep-copies the snapshot and persists it (`save_snapshot`) before applying. `Executor.rollback` re-applies that snapshot (`actions/executor.py` lines 58–89). In the benchmark, `final_settings == rollback.restored` held in 45/45 runs. For `restart_capture` the check is trivially true because no settings change. The other 4 actions change settings (`exposure`, `focus_ok`, `profile`, `safe_mode`) and are restored. |
| 5 | Execution failure distinguished from "no improvement" | **PARTIAL** | `tests/unit/test_policy_actions_verifier.py::test_execution_failure_distinct_from_no_improvement` → `1 passed`, but it does not check the claim. (a) Its "no improvement" leg feeds one *improving* window (`success_rate 0.0 → 1.0`) and gets `INCONCLUSIVE` only because 1 < `healthy_windows_required` (2). Reproduced: `inconclusive ['not enough windows']`. It never produces `ROLLED_BACK`. (b) The `execution_ok=False` branch of `Verifier.decide` (`verification/verifier.py` lines 69–72) is never called by the orchestrator. The real failure path is `orchestrator.py` lines 445–448 (`FAILED` state, then `_rollback("execution failed")`, with no verification event). Indirect coverage exists: `tests/integration/test_experiments.py::test_a8_failed_apply_restarts_in_failed_before_rollback` (passed, shows execution `failed` → `FAILED` → rollback), and the box-1 rollback test shows no-improvement → verification `rolled_back`. No test asserts the two outcomes are distinguishable in the persisted record. |
| 6 | Before/after report with metrics and evidence persisted | **PROVEN** | `tests/integration/test_incident_report.py` → `1 passed in 5.08s`. It runs `dark` and `bad_action` into a SQLite EventStore, reopens it, checks `verify_chain()`, then checks the committed and rolled-back reports and the CLI JSON output (one per incident, non-empty events). Committed artifacts in `docs/evidence/f8/incident-reports/` (2 × md+json) contain `before`/`after` metric dicts, for example `task.success_rate: 0.000 -> 1.000` (committed) and `0.000 -> 0.000, original fault still present` (rolled back). Minor: the test does not assert the `before`/`after` keys directly. |
| 7 | Restart during VERIFYING does not lose the pending decision | **PROVEN** | `tests/unit/test_restore.py::test_restart_while_verifying_rolls_back_and_escalates_without_a_new_plan` → `1 passed in 0.87s`. Real SQLite file reopened. Asserts: same incident id, state `NEEDS_HUMAN`, pre-action exposure restored, no pending snapshots, baseline version kept, gate history kept, plan/policy/execution events unchanged, rollback reason `restart with an uncommitted action`, report `restart_resolution == "rolled back on restart"`, and `planner.calls == 0` after recovery. |

## Benchmark reproduction

Command: `.venv\Scripts\python.exe scripts/bench_recovery.py --out C:\Users\niaib\ra-f8-review-out\bench`
(clean worktree, exit 0, about 7 minutes). Output: `C:\Users\niaib\ra-f8-review-out\bench\recovery-bench.{md,json}`.

| Metric | Committed (`be74665`) | Reproduced (`d67f08a`) | Match |
|---|---:|---:|:---:|
| Recovery (recovered auto / recoverable) | 87/100 (87.0%) | 87/100 (87.0%) | yes |
| Needs human / timeouts | 3 / 10 | 3 / 10 | yes |
| Recovery gate ≥ 85% | PASS | PASS (`gate_pass: true`) | yes |
| Raw rollback/safe-mode | 45/50 | 45/50 | yes |
| Executed regressions contained | 45/45 | 45/45 | yes |
| Non-executed, settings unchanged | 5/5 (all `dark:0.8`) | 5/5 (all `dark:0.8`) | yes |
| Rollback events ok / settings identical | 45 / 45 | 45 / 45 | yes |
| Coverage floor (dark, defocus, overexpose, frozen_black) | PASS | PASS (`missing_families: []`) | yes |
| Per-fault/strength rows | see committed md | identical | yes |
| Per-run records (100 recovery + 50 regression) | — | 0 field differences | yes |

Only `code_sha` and `generated_at` differ. The reviewed commits after `be74665` are documentation-only.

### Can the gate criteria be passed trivially? (`benchmarks/recovery.py`)

- **A never-acting agent fails recovery.** With no incident, the run counts as `recoverable=True`, `timeout`
  (lines 63–68). `recovered_auto` requires a `closed` event with reason `recovered` and no ticket. The
  orchestrator emits that only after a `COMMITTED` verification (`orchestrator.py` lines 478–481). The benchmarked
  scenarios (`dark`, `defocus`, `overexposure`, `frozen_black`) have `human_fix=None` (`demo.py` lines 35–43), so
  the fault never clears by itself, and the harness never clears it.
- **A never-acting agent fails containment.** All rows would be non-executed, so the coverage floor fails
  (`regression_gate`, lines 351–370). Pinned by `test_regression_gate_fails_when_no_rows_are_executed`.
- **The denominator is not shrunk.** `recoverable` depends on the incident offering the remediating action. All
  100 recovery runs counted as recoverable, and the 10 `dark:0.8` no-incident runs count as failures.
- **A changed but unexecuted device fails.** Non-executed rows must keep settings unchanged
  (`test_non_executed_run_with_changed_settings_fails`).

## Threshold check

- `git log -p --since=2026-10-10 -- configs/`: no gate threshold was relaxed. The F3 occlusion changes
  (2026-10-11) cite ADR-007/ADR-008, which exist in `docs/adr/`. The remaining changes are additive keys
  (`calibration_discard`, `stall_windows`, `restore_on_start`, `checkpoint_windows`, `lease_stale_s` 10→60
  with a written constraint, `parallel`), the `prompt_version` switch to `diagnose_v2`, and audit allowlists. The
  `verification:` block (`min_relative_improvement 0.10`, `baseline_recovery_ratio 0.95`,
  `max_guard_regression 0.10`, `healthy_windows_required 2`, `guard_abs_tolerance`) is unchanged in that window.
- **Commit `47fd021`** ("time the marker task with the simulated clock") touches no file under `configs/`, and no
  threshold or tolerance. It changes `tasks/marker.py` (injectable `timer`, default `time.perf_counter`),
  `demo.py` and `benchmarks/experiments.py` (pass the simulated clock), and adds
  `tests/e2e/test_scenarios.py::test_host_cpu_jitter_does_not_roll_back_a_simulated_recovery`. It is
  justified: host CPU jitter is not a property of the simulated device and was causing nondeterministic Windows
  CI rollbacks. Live and replay paths keep wall-clock timing. `main` CI is green on `9d026d1`, which includes it
  (GitHub Actions API).
- **Governance note (non-blocking).** The F8 containment criterion was redefined in benchmark code after a recorded
  FAIL (`46c383a` → `13d2559`). The redefinition counts only executed runs, requires unexecuted runs to keep
  settings unchanged, and was later hardened with the coverage floor. The 100% threshold itself did not change,
  raw 45/50 is still published, and the rationale is recorded in `docs/agents/DECISIONS.md` lines 47–48. But
  there is no ADR. The reviewer finds the redefinition sound (a run that never confirms an incident has no action to
  contain), but recommends an ADR, given AGENTS.md hard rule 5.

## Targeted suites (step 6)

```
.venv\Scripts\python.exe -m pytest -q tests/e2e/test_action_commit_rollback.py tests/unit/test_recovery_classifier.py tests/unit/test_restore.py tests/integration/test_incident_report.py tests/unit/test_policy_actions_verifier.py tests/e2e/test_scenarios.py
119 passed in 37.80s
```

Individually cited tests: `10 passed` (commit/rollback), `22 passed` (classifier), `1 passed` (execution-failure
unit test), `1 passed` (incident report), `1 passed` (restart while VERIFYING), and the supporting
`test_a8_failed_apply_restarts_in_failed_before_rollback` `1 passed`.

## Minimal actions to pass F8

1. **(agent, Safety/Evaluation)** Replace or extend the box-5 evidence with a test that proves the claim:
   - Unit level: give `Verifier.decide` ≥ 2 non-improving after-windows and assert `ROLLED_BACK`, versus
     `execution_ok=False` giving `EXECUTION_FAILED`.
   - Orchestrator level (preferred, because the production path does not use `execution_ok`): make one device's
     `apply_settings` raise, and leave another device's action without effect. Assert that the first yields
     execution `failed`, state `FAILED`, and no `verification` event. Assert that the second yields execution
     `success`, verification `rolled_back`, and no `FAILED` state. Both should end with rollback `ok` and exact
     settings.
   - Update the citation in `docs/phases-and-gates.md` line 149.
2. **(agent, Evaluation; then re-review)** Re-run this review on the new commit.

Recommended but not blocking: add an ADR for the F8 containment-criterion redefinition (`13d2559`, plus the
coverage floor).

## Known non-blocking risks

- **Thin recovery margin.** 87/100 is 2 cases above 85%. The result is deterministic after `47fd021`, but any
  future change to detection or verification can flip the gate.
- **The latency guard is inert in SIMULATION.** Since `47fd021`, the simulated clock does not advance during
  `detectMarkers`, so `task.latency_ms_p95` is always 0 in simulated runs. The verifier then skips that guard
  (`abs(b[g]) < 1e-9`), so no SIMULATION harness can exercise a latency regression. That path is only
  unit-tested (`test_guard_noise_within_absolute_tolerance_is_ignored` and others). The committed incident reports
  (2026-10-18) predate this change and still show non-zero latencies.
- **Half of the regression cases are not harmful actions.** The `defocus` and `frozen_black` regression cases use
  `enter_safe_mode`, a non-remediating action rather than a harmful one. Only `dark`/`overexpose` (25 executed)
  inject actively harmful settings.
- **`restart_capture` rollback is a no-op on settings,** so exact-restore is trivially true for that action.
- **The `dark:0.8` cells in both grids never confirm an incident** (10 timeouts in recovery, 5 unexecuted in
  regression). This is by design (DECISIONS line 48) and counted against recovery, but it means 10% of the recovery
  grid can never pass.
- **All F8 evidence is SIMULATION** (synthetic source, simulated device controls). Real UVC/ONVIF behavior is
  untested.
- CI evidence came from the public GitHub Actions API. `gh` was not authenticated, and no CI run was found for
  the docs branch itself.
