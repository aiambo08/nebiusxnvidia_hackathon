# Project state

Last update: 2026-10-08 · Current phase: **F3** (F1/F2 hardware box awaiting owner) · Days to deadline: 22

## Snapshot
- Repository scaffolded end-to-end: contracts, FSM, capture worker, probes, ArUco task, robust
  baseline, fusion, Nemotron planner + budget guard, policy gate, executor, verifier, hash-chained
  event store, orchestrator, CLI, read-only API, injectors, CI.
- 283 tests green (unit, integration, adversarial, e2e simulation), ruff clean.
- F2 resilience proven on a simulated clock (`tests/unit/test_capture_resilience.py`): stream_down in
  3 s, non-blocking reconnect, telemetry back < 15 s; capture coverage gate enforced in CI
  (`scripts/check_coverage.py`, 96%/91%). `CaptureWorker.health()` JSON export. `docs/evidence/f2/`.
- Live Token Factory verified (REAL TOKEN FACTORY, 2026-10-05): model IDs confirmed, json_schema works,
  thinking must be disabled; fast tier 20/20 valid at ~0.0001 USD/diagnosis (ADR-002).
- Real webcam verified (REAL HARDWARE, native Windows, integrated 640×480 webcam): 30-min soak 100% valid
  windows, heap +0.4%, 0 reconnects (`docs/evidence/f1/`). Risk: live probe p95 110 ms vs 20.5 ms isolated.
- F1 replay tooling: record a clean clip, inject seeded blur/dark/freeze, replay it through
  `OpenCVSource` + probes + tracker offline (no LLM). REAL HARDWARE clip s001 (SIMULATION faults):
  dark/blur/freeze detected in 2.9 s, 0 false alarms on the clean clip.
- F3 started: spurious `freeze` on dark/blurred live scenes fixed by causal suppression (ADR-003,
  `docs/evidence/f3/`); owner to confirm on the real clip replay. Open: the absolute MSE floor is
  close to a quiet healthy sensor; recall/precision, static-scene and latency gates not measured.

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |
| 2026-10-05 | ~0.02 (spikes + probes) | to confirm by Aibo |

## Blockers
- Token Factory console balance to be confirmed by Aibo.

## Next 3 actions
1. Aibo (when the phone is available): `RA_TEST_RTSP` and `RA_TEST_WEBCAM=0` contract runs to close the shared F1/F2 box; the 1-min RTSP capture passed twice (96.2% valid windows). Last attempt (2026-10-08) failed before `open()`: phone unreachable.
1b. Devin: F3 visual monitors — freeze specificity on dark/blurred real frames (ADR + benchmark), per-cell occlusion, live probe p95.
2. Ingestion: probe UVC exposure/autofocus on the integrated webcam (decides UVC vs pipeline action).
3. Nebius (F6): golden set including the cases where the reasoning tier disagrees with the local top fault.
