# F8 Offline Recovery Benchmark

**SIMULATION** — deterministic `SyntheticSource` runs; no network or paid services.
Code commit: `20c4126c218229646395ba7bff3aa8dd50399891`
Generated: 2026-10-18T12:38:24.502778+00:00

## Recovery grid

Pre-registered cases: dark=[0.8, 0.9, 0.99], defocus=[0.6, 0.8, 1.0], overexpose=[0.6, 0.8, 1.0], frozen_black=[None]; seeds `0..9`.

| Fault | Strength | Runs | Recovered auto / recoverable | Needs human | Timeout |
|---|---:|---:|---:|---:|---:|
| dark | 0.8 | 10 | 0 / 10 | 0 | 10 |
| dark | 0.9 | 10 | 8 / 10 | 2 | 0 |
| dark | 0.99 | 10 | 10 / 10 | 0 | 0 |
| defocus | 0.6 | 10 | 10 / 10 | 0 | 0 |
| defocus | 0.8 | 10 | 10 / 10 | 0 | 0 |
| defocus | 1.0 | 10 | 10 / 10 | 0 | 0 |
| frozen_black | n/a | 10 | 10 / 10 | 0 | 0 |
| overexpose | 0.6 | 10 | 9 / 10 | 1 | 0 |
| overexpose | 0.8 | 10 | 10 / 10 | 0 | 0 |
| overexpose | 1.0 | 10 | 10 / 10 | 0 | 0 |

Global: **87 / 100** recoverable cases (87.0%); 3 needs-human, 10 timeouts. Gate ≥85%: PASS.
Margin note: 87/100 is only 1–2 cases above the 85% threshold. The reviewer reported 86/100 under heavy parallel CPU load when `defocus:1.0`, seed 2, hit the wall-clock `task.latency_ms_p95` guard with 5 ms tolerance; 12 repeats across idle and loaded conditions recovered.

## Deliberate regression grid

Same pre-registered faults and seeds `0..4`; actions are proposed through the policy gate when an incident is confirmed.
The frozen-black case uses the agent's local frozen-blackout restart plan instead of the injected planner; the harness keeps the repeated frame across restart to exercise rollback.
The defocus and frozen_black regression proposals use `enter_safe_mode`, a policy-approved non-remediating action.
The other regression cases use scripted, policy-gated proposals.
The first benchmark report recorded `100% gate: FAIL` at commit `46c383a`; commit `13d2559` revised `gate_pass`. A run that never confirms an incident executes no action to contain, so raw 45/50 remains published while non-executed runs must leave settings unchanged. Review then added the executed-coverage floor so a never-acting agent cannot pass.

| Fault | Strength | Runs | Raw rollback/safe-mode pass | Executed | Executed pass | Not executed / settings unchanged | Rollback events | Settings restored |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dark | 0.8 | 5 | 0 / 5 | 0 | 0 / 0 | 5 / 5 | 0 | 0 |
| dark | 0.9 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| dark | 0.99 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 0.6 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 0.8 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 1.0 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 0.6 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 0.8 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 1.0 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| frozen_black | n/a | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |

### Executed coverage by fault family

| Fault family | Runs | Executed | Executed pass | Not executed | Not executed, settings unchanged |
|---|---:|---:|---:|---:|---:|
| dark | 15 | 10 | 10 | 5 | 5 |
| defocus | 15 | 15 | 15 | 0 | 0 |
| overexpose | 15 | 15 | 15 | 0 | 0 |
| frozen_black | 5 | 5 | 5 | 0 | 0 |

Raw rollback/safe-mode result: **45 / 50**; successful rollback events: 45; settings equal restored snapshots: 45.
Executed regressions ending in rollback with exact snapshot restoration or safe mode: **45 / 45**.
Non-executed runs with unchanged settings: **5 / 5**. Revised 100% gate: PASS. Coverage floor: PASS.
Regression misses by fault/strength: dark strength 0.8: 5/5.

Non-executed runs (incident reason from EventStore; unchanged-settings check uses device state):
- dark:0.8, seed 0: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 1: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 2: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 3: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 4: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).

Recovery classification and incident reports are event-only. Regression classification combines EventStore events, device settings, and `ScenarioResult.final_state`; per-case inputs and outcomes are in the companion JSON.
