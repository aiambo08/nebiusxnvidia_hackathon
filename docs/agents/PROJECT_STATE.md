# Project state

Last update: 2026-10-05 · Current phase: **F0** · Days to deadline: 25

## Snapshot
- Repository scaffolded end-to-end: contracts, FSM, capture worker, probes, ArUco task, robust
  baseline, fusion, Nemotron planner + budget guard, policy gate, executor, verifier, hash-chained
  event store, orchestrator, CLI, read-only API, injectors, CI.
- 222 tests green (unit, integration, adversarial, e2e simulation), ruff clean.
- Live Token Factory verified (REAL TOKEN FACTORY, 2026-10-05): model IDs confirmed, json_schema works,
  thinking must be disabled; fast tier 20/20 valid at ~0.0001 USD/diagnosis (ADR-002).
- No real-webcam run yet → F0 hardware box and F1 open (SIMULATION only for vision).

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |
| 2026-10-05 | ~0.02 (spikes + probes) | to confirm by Aibo |

## Blockers
- Real webcam run on Aibo's laptop (native Windows) — human-only.
- Token Factory console balance to be confirmed by Aibo.

## Next 3 actions
1. Human: on native Windows, run `python scripts/spike_capture.py --minutes 1` (F0 hardware box), then `--minutes 30` (F1).
2. Ingestion: probe UVC exposure/autofocus on the integrated webcam; RTSP from the phone camera.
3. Nebius (F6): golden set including the cases where the reasoning tier disagrees with the local top fault.
