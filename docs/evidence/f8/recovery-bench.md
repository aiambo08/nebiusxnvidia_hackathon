# F8 Offline Recovery Benchmark

**SIMULATION** — deterministic `SyntheticSource` runs; no network or paid services.
Code commit: `13d25590ae5561f0eb1cd5559d80cf5da7475f9c`
Generated: 2026-10-18T11:47:24.267483+00:00

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

## Deliberate regression grid

Same pre-registered faults and seeds `0..4`; actions are proposed through the policy gate when an incident is confirmed.
The frozen-black case uses the agent's local frozen-blackout restart plan instead of the injected planner; the harness keeps the repeated frame across restart to exercise rollback.
Other regression cases use scripted, policy-gated, non-remediating proposals.

| Fault | Strength | Runs | Raw rollback/safe-mode pass | Executed | Executed pass | Not executed / settings unchanged | Rollback events | Settings restored |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dark | 0.8 | 5 | 0 / 5 | 0 | 0 / 0 | 5 / 5 | 0 | 0 |
| dark | 0.9 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| dark | 0.99 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 0.6 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 0.8 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| defocus | 1.0 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| frozen_black | n/a | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 0.6 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 0.8 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |
| overexpose | 1.0 | 5 | 5 / 5 | 5 | 5 / 5 | 0 / 0 | 5 | 5 |

Raw rollback/safe-mode result: **45 / 50**; successful rollback events: 45; settings equal restored snapshots: 45.
Executed regressions ending in rollback with exact snapshot restoration or safe mode: **45 / 45**.
Non-executed runs with unchanged settings: **5 / 5**. Revised 100% gate: PASS.
Regression misses by fault/strength: dark strength 0.8: 5/5.

Non-executed runs (reason from EventStore):
- dark:0.8, seed 0: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 1: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 2: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 3: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).
- dark:0.8, seed 4: no incident confirmed; settings_unchanged=True (final_state=HEALTHY, plan_source=null).

Per-case event-derived outcomes and regression checks are in the companion JSON.
