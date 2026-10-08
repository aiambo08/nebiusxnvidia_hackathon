# Project state

Last update: 2026-10-08 · Current phase: **F3** (F1/F2: every box evidenced, independent gate review pending) · Days to deadline: 22

## Snapshot
- Repository scaffolded end-to-end: contracts, FSM, capture worker, probes, ArUco task, robust
  baseline, fusion, Nemotron planner + budget guard, policy gate, executor, verifier, hash-chained
  event store, orchestrator, CLI, read-only API, injectors, CI.
- 298 tests green (unit, integration, adversarial, e2e simulation), ruff clean.
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
  `docs/evidence/f3/`); owner to confirm on the real clip replay. The absolute MSE floor that
  flagged a healthy σ=2 static scene is replaced by a camera-relative noise floor (ADR-004,
  `scripts/bench_static_scene.py` → `docs/evidence/f3/static-scene.md`: 20-min SIMULATION static
  scenes with 0 freeze false positives, frozen/looped streams still confirmed). Open: the 20-min
  box on REAL HARDWARE, recall/precision per detector, walk-by FOV trials, probe p95 at 720p.

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |
| 2026-10-05 | ~0.02 (spikes + probes) | to confirm by Aibo |

## Blockers
- Token Factory console balance to be confirmed by Aibo.

## Next 3 actions
1. Webcam + phone RTSP contract passed on REAL HARDWARE (2026-10-08), closing the shared F1/F2 box. 10-min RTSP soak passed (533/536, 99.4 %). Next: independent F1/F2 gate review.
1b. Devin: F3 visual monitors — freeze specificity on dark/blurred real frames (ADR + benchmark), per-cell occlusion, live probe p95.
2. Ingestion: probe UVC exposure/autofocus on the integrated webcam (decides UVC vs pipeline action).
3. Nebius (F6): golden set including the cases where the reasoning tier disagrees with the local top fault.
