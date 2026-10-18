# F8 Offline Recovery Benchmark

**SIMULATION** — deterministic `SyntheticSource` runs; no network or paid services.
Code commit: `969f406f0d03286c8a85476f83f7aa19933f7fcc`
Generated: 2026-10-18T11:27:07.950919+00:00

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

| Fault | Strength | Runs | Rollback/safe-mode pass | Rollback events | Settings restored |
|---|---:|---:|---:|---:|---:|
| dark | 0.8 | 5 | 0 / 5 | 0 | 0 |
| dark | 0.9 | 5 | 5 / 5 | 5 | 5 |
| dark | 0.99 | 5 | 5 / 5 | 5 | 5 |
| defocus | 0.6 | 5 | 5 / 5 | 5 | 5 |
| defocus | 0.8 | 5 | 5 / 5 | 5 | 5 |
| defocus | 1.0 | 5 | 5 / 5 | 5 | 5 |
| frozen_black | n/a | 5 | 5 / 5 | 5 | 5 |
| overexpose | 0.6 | 5 | 5 / 5 | 5 | 5 |
| overexpose | 0.8 | 5 | 5 / 5 | 5 | 5 |
| overexpose | 1.0 | 5 | 5 / 5 | 5 | 5 |

Rollback/safe-mode pass: **45 / 50**; successful rollback events: 45; settings equal restored snapshots: 45. 100% gate: FAIL.
Regression misses by fault/strength: dark strength 0.8: 5/5.

Per-case event-derived outcomes and regression checks are in the companion JSON.
