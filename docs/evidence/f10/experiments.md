# F10 PR2 Experiments and Ablations

**SIMULATION** — `SyntheticSource`; no live Nebius calls were made.
Code revision: `496ac7b69b6966b3afda030f1a11610b0b631f6c`
EventStore runs: 367; all hash chains valid: True.

## Per-arm results

| Arm | Runs | Incidents | Plans | Successful executions | Controls / false confirmations | Rollbacks | Key result | Status |
|---|---:|---:|---:|---:|---:|---:|---|---|
| A1_local_detector_only | 40 | 30 | 0 | 0 | 10 / 0 | 0 | correct=30/30; planner calls=0 | SIMULATION |
| A2_detector_no_actions | 40 | 30 | 30 | 0 | 10 / 0 | 0 | unchanged=40/40; device executions=0; ticket requests=5; auto-execution disabled | SIMULATION |
| A3_full_loop | 60 | 50 | 50 | 45 | 10 / 0 | 20 | macro F1=1.000; recovery=25/25 | SIMULATION |
| A4_no_downstream_metric | 50 | 50 | 50 | 45 | 0 / 0 | 20 | COMMITTED=0 vs 0 full-loop | SIMULATION |
| A5_single_baseline | 40 | 30 | 30 | 25 | 10 / 0 | 3 | correct=30/30 (A3 50/50); false controls=0/10 | SIMULATION |
| A6_token_factory_outage | 30 | 30 | 30 | 25 | 0 / 0 | 0 | fallback=25/25 planner incidents; unhandled=0; circuit opened after threshold=True; same recovery as A3=True; spend=$0.0000 | SIMULATION |
| A7_rtsp_failure_during_action | 10 | 10 | 10 | 10 | 0 / 0 | 10 | invariants pass=True | SIMULATION |
| A8_restart_in_every_state | 90 | 90 | 70 | 50 | 0 / 0 | 40 | invariants pass=True | SIMULATION |

For A2, device executions count only `success` and `failed` statuses; policy-designated human-ticket requests are reported separately. Settings are compared with the SyntheticSource state immediately after fault injection.

## A6 plan routing

| Path | Incidents | Result |
|---|---:|---|
| Planner-routed | 25 | fallback 25/25 incidents (1.000) |
| frozen_black | 5 | deterministic local plan, planner not called |

## A3 recovery by fault

| Fault | Runs | Recoverable | Recovered auto | Needs human | Timeout |
|---|---:|---:|---:|---:|---:|
| dark | 5 | 5 | 5 | 0 | 0 |
| defocus | 5 | 5 | 5 | 0 | 0 |
| freeze | 5 | 5 | 5 | 0 | 0 |
| frozen_black | 5 | 5 | 5 | 0 | 0 |
| occlusion (ticket / needs_human expected) | 5 | 0 | 0 | 5 | 0 |
| overexpose | 5 | 5 | 5 | 0 | 0 |
| F8-comparable subset | 20 | 20 | 20 | 0 | 0 |

The F8 classifier returns `recoverable=False` for occlusion; its five ticket / needs-human outcomes are reported separately and excluded from the recoverable denominator.

A4 used the fixed visual primary by fault and removed every `task.*` primary/guard; the pre-registered improvement delta was not adjusted.
Deliberate-regression COMMITTED count: full loop 0/20; no-downstream-metric 0/20.
Regression gate: full loop True; no-downstream-metric True.

## Regression verification decisions by fault family

| Family | A3 committed | A3 rolled_back | A3 inconclusive | A4 committed | A4 rolled_back | A4 inconclusive |
|---|---:|---:|---:|---:|---:|---:|
| dark | 0 | 5 | 0 | 0 | 5 | 0 |
| defocus | 0 | 5 | 0 | 0 | 5 | 0 |
| frozen_black | 0 | 5 | 0 | 0 | 5 | 0 |
| overexpose | 0 | 5 | 0 | 0 | 5 | 0 |

## A4 recovery by fault

| Fault | Runs | Recoverable | Recovered auto | Needs human | Timeout |
|---|---:|---:|---:|---:|---:|
| dark | 5 | 5 | 5 | 0 | 0 |
| defocus | 5 | 5 | 5 | 0 | 0 |
| freeze | 5 | 5 | 5 | 0 | 0 |
| frozen_black | 5 | 5 | 5 | 0 | 0 |
| occlusion | 5 | 0 | 0 | 5 | 0 |
| overexpose | 5 | 5 | 5 | 0 | 0 |

A6 recovery matches A3 on the identical fault/strength/seed run set (True): True.

## A8 restart coverage

- `bad_action` reachable states: ACTING, CONFIRMED, DIAGNOSING, HEALTHY, NEEDS_HUMAN, PLANNED, ROLLED_BACK, ROLLING_BACK, SUSPECT, VERIFYING; unreachable: CLOSED, FAILED, RECOVERED, REJECTED, SAFE_MODE.
- `dark` reachable states: ACTING, CONFIRMED, DIAGNOSING, HEALTHY, PLANNED, RECOVERED, SUSPECT, VERIFYING; unreachable: CLOSED, FAILED, NEEDS_HUMAN, REJECTED, ROLLED_BACK, ROLLING_BACK, SAFE_MODE.

## Evidence and limitations

| Category | Source | Result |
|---|---|---|
| Macro F1 (A3) and controls | `this report, derived from A3 EventStores` | SIMULATION |
| False alarms per hour by route | `/home/ubuntu/staging/f10-soak-20261018T122142Z/report.md` | pending PR1 soak report; not recalculated here |
| Diagnosis | `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md` | SIMULATION evidence; REAL HARDWARE pending F4 |
| LLM structure | `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md` | SIMULATION evidence; REAL HARDWARE pending F4 |
| Adversarial safety | `tests/adversarial/` | SIMULATION evidence; REAL HARDWARE pending F4 |
| Recovery | `this report, A3 EventStores` | SIMULATION |
| Rollback gate | `docs/evidence/f8/recovery-bench.md` | SIMULATION evidence; REAL HARDWARE pending F4 |
| Soak robustness | `/home/ubuntu/staging/f10-soak-20261018T122142Z/report.md` | pending PR1 soak report; REAL HARDWARE pending F4 |
| Budget | `per-run EventStore usage tables and docs/evidence/f6/` | SIMULATION; no live calls in this run |
| Reproducibility | `F11` | pending |

All results in this report are SIMULATION. REAL HARDWARE rows remain pending F4; F11 reproducibility remains pending. False alarms/hour are referenced from the F10 PR1 soak report and are not recalculated by this report.
