# Project state

Last update: 2026-10-05 · Current phase: **F0** · Days to deadline: 25

## Snapshot
- Repository scaffolded end-to-end: contracts, FSM, capture worker, probes, ArUco task, robust
  baseline, fusion, Nemotron planner + budget guard, policy gate, executor, verifier, hash-chained
  event store, orchestrator, CLI, read-only API, injectors, CI.
- 228 tests green (unit, integration, adversarial, e2e simulation), ruff clean.
- Live Token Factory verified (REAL TOKEN FACTORY, 2026-10-05): model IDs confirmed, json_schema works,
  thinking must be disabled; fast tier 20/20 valid at ~0.0001 USD/diagnosis (ADR-002).
- Real webcam verified (REAL HARDWARE, native Windows, integrated 640×480 webcam): 30-min soak 100% valid
  windows, heap +0.4%, 0 reconnects (`docs/evidence/f1/`). Risk: live probe p95 110 ms vs 20.5 ms isolated.
- F1 replay tooling: record a clean clip, inject seeded blur/dark/freeze, replay it through
  `OpenCVSource` + probes + tracker offline (no LLM). SIMULATION clip: 4/4 runs pass, 0 false alarms.

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |
| 2026-10-05 | ~0.02 (spikes + probes) | to confirm by Aibo |

## Blockers
- Token Factory console balance to be confirmed by Aibo.

## Next 3 actions
1. Aibo: record a 90-s clip, run `scripts/spike_inject.py` on it and the RTSP contract test with the phone (F1).
2. Ingestion: probe UVC exposure/autofocus on the integrated webcam (decides UVC vs pipeline action).
3. Nebius (F6): golden set including the cases where the reasoning tier disagrees with the local top fault.
