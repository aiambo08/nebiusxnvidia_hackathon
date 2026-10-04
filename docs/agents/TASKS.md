# Task board

Format: `- [ ] [Fx][role] task — acceptance`

## F0
- [ ] [F0][human] Create Token Factory key and local `.env` — `scripts/list_models.py` lists NVIDIA models
- [ ] [F0][nebius] Confirm model IDs, regions, json_schema support, reasoning toggle — update ADR-002
- [ ] [F0][nebius] 20 live diagnoses — ≥ 19 schema-valid, cost logged
- [ ] [F0][architecture] Freeze contracts v1.0 — tag `contracts-v1`

## F1
- [ ] [F1][ingestion] 30-min webcam soak — `spikes/capture-report.md`
- [ ] [F1][ingestion] Local RTSP via MediaMTX + same source contract
- [ ] [F1][evaluation] Inject blur/dark/freeze on a recorded clip — manifests committed
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
