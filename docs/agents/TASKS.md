# Task board

Format: `- [ ] [Fx][role] task — acceptance`

## F0
- [x] [F0][human] Create Token Factory key and local `.env` — `scripts/list_models.py` lists NVIDIA models
- [x] [F0][nebius] Confirm model IDs, regions, json_schema support, reasoning toggle — update ADR-002
- [x] [F0][nebius] 20 live diagnoses — ≥ 19 schema-valid, cost logged
- [ ] [F0][architecture] Freeze contracts v1.0 — tag `contracts-v1`

## F0 (remaining)
- [x] [F0][human] Run on own hardware: `python scripts/spike_capture.py --minutes 1` on native Windows (MVP runs on owned hardware)
- [ ] [F0][architecture] Fill planned evidence for every row of `docs/compliance-matrix.md`

## F1
- [ ] [F1][ingestion] Probe UVC exposure/autofocus support of the integrated webcam (set-and-read-back)
- [x] [F1][ingestion] 30-min webcam soak — `docs/evidence/f1/README.md`
- [ ] [F3][vision] Explain live probe p95 (110 ms at 640×480) vs isolated bench (20.5 ms at 720p) — see `docs/evidence/f1/README.md`
- [ ] [F1][ingestion] Local RTSP from the phone (IP Webcam app) through the same source contract — 1-min capture PASSED (REAL HARDWARE, `docs/evidence/f1/README.md`); contract test failed on undecodable H.264 frames: bounded read retries (PR #6) were not enough for the startup burst, `open()` now warms up network sources until the first decodable frame; rerun `RA_TEST_RTSP=<url> pytest tests/integration/test_source_contract.py` (awaiting Aibo)
- [x] [F1][evaluation] Inject blur/dark/freeze on a recorded clip — `docs/evidence/f1/README.md`, manifests `benchmarks/manifests/f1-s001-*.yaml`
- [x] [F3][vision] Freeze rule fires on dark/blurred real frames and ranks first — fixed by causal suppression (ADR-003, `docs/evidence/f3/README.md`); owner to confirm on the real clip replay
- [ ] [F3][vision] **First F3 item.** Absolute `temporal_mse_floor` (0.5) fires on a healthy lit static scene with σ=2 noise (358/400 windows on `main`, per independent review) — replace with a baseline-relative noise floor (ADR + benchmark), then run the 20-min static-scene gate
- [ ] [F3][evaluation] `benchmarks.replay.EXPECTED` has no entries for `loop4`/`loop8`, so `score()` cannot grade those runs; loop8 on a static smooth scene confirms only 3/10 (10/10 with motion)
- [ ] [F5][planner] Frozen black frame is reported as `blackout` only (ADR-003): if the exposure action fails verification while `exact_repeat_ratio ≥ 0.9`, plan `restart_capture` next instead of NEEDS_HUMAN
- [ ] [F1][safety] Simulated action apply/rollback ×2 — unit test green

## F2–F8
- [x] [F2][ingestion] Coverage ≥ 80% lines / 75% branches on `capture/` — CI `scripts/check_coverage.py` (96.1% / 90.8% sandbox)
- [x] [F2][ingestion] Disconnect < 5 s, non-blocking reconnect, telemetry resume < 15 s — `tests/unit/test_capture_resilience.py`
- [ ] [F2][human] Contract suite on the integrated webcam (`RA_TEST_WEBCAM=0`) and on the phone RTSP (`RA_TEST_RTSP`) — awaiting Aibo's hardware run (F1/F2 shared box)
- [ ] [F3][vision] Per-cell occlusion against baseline cells
- [ ] [F3][vision] Day/night baselines + reference bank for geometry
- [ ] [F4][evaluation] `scripts/run_benchmark.py` producing a markdown report from event files
- [ ] [F5][architecture] Restore FSM + baseline from SQLite after restart
- [ ] [F6][nebius] Golden set (20 cases × fault) + ambiguity cases
- [ ] [F7][safety] Real webcam adapter for exposure/autofocus (capability discovery)
- [ ] [F8][safety] Persist pending VERIFYING decisions across restarts

## F9–F12
- [ ] [F9][product] Dashboard (live state, timeline, Nemotron panel, before/after, cost)
- [ ] [F12][product] Video + Devpost text
