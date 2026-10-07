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
- [ ] [F1][ingestion] Local RTSP from the phone (IP Webcam app) through the same source contract — 1-min capture PASSED (REAL HARDWARE, `docs/evidence/f1/README.md`); contract test failed on undecodable H.264 frames, fixed with bounded retries in `OpenCVSource`; rerun `RA_TEST_RTSP=<url> pytest tests/integration/test_source_contract.py` (awaiting Aibo)
- [x] [F1][evaluation] Inject blur/dark/freeze on a recorded clip — `docs/evidence/f1/README.md`, manifests `benchmarks/manifests/f1-s001-*.yaml`
- [ ] [F3][vision] Freeze rule fires on dark/blurred real frames and ranks first — fix specificity (ADR + benchmark), see `docs/evidence/f1/README.md`
- [ ] [F1][safety] Simulated action apply/rollback ×2 — unit test green

## F2–F8
- [ ] [F2][ingestion] Coverage ≥ 80% lines / 75% branches on `capture/`
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
