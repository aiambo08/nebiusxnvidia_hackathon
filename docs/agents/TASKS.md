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
- [x] [F1][ingestion] Local RTSP from the phone (IP Webcam app) through the same source contract — `2 passed` on REAL HARDWARE (2026-10-08) after the decode retries (PR #6) and the network warm-up (PR #7), `docs/evidence/f1/README.md`
- [x] [F1][evaluation] Inject blur/dark/freeze on a recorded clip — `docs/evidence/f1/README.md`, manifests `benchmarks/manifests/f1-s001-*.yaml`
- [x] [F3][vision] Freeze rule fires on dark/blurred real frames and ranks first — fixed by causal suppression (ADR-003, `docs/evidence/f3/README.md`); owner to confirm on the real clip replay
- [x] [F3][vision] Absolute `temporal_mse_floor` (0.5) fired on a healthy lit static scene with σ=2 noise (358/400 windows, per independent review) — replaced by the camera-relative noise floor (ADR-004, `scripts/bench_static_scene.py`, `docs/evidence/f3/static-scene.md`: 20-min SIMULATION static scenes, 0 false positives). floor learned from still windows only after the independent review found that 30 s of motion at start-up re-created the false freeze; AGC/light-driven noise drops documented as a residual risk for F5 per-mode baselines. REAL HARDWARE 20-min run on the owner's webcam still pending
- [x] [F3][vision] Learned freeze noise floor (ADR-004) contaminated by motion before rest (independent review of PR #11/#14: person walk-by, 5–40 px low-contrast objects, no recovery) — replaced by ADR-005: per-frame temporal-vs-spatial noise exported as telemetry (`probes/temporal.py::noise_sigmas`), perceptual-hash repeats dropped as freeze evidence (a live static scene over H.264 has no temporal noise either: reviewer 4th pass + libx264 reproduction), `freeze` = bit-exact repeats or loops only; `docs/evidence/f3/static-scene.md`; owner to confirm on REAL HARDWARE (webcam 20-min static scene, phone RTSP on a plain wall)
- [x] [F3][vision] `fov_shift` false positive on a healthy static *smooth* scene (found by the 20-min static-scene run): `equalizeHist` amplifies sensor noise into ~210 ORB keypoints and the 8-DOF homography fitted through them still found ≈ 60 % inliers while its translation jittered (SIMULATION wall σ 0.7–4: p95 27–48 px, max 94 px, rotation up to 3°), so the rule fired on a camera at rest (52/600 and 93/600 windows on σ 0.7 / σ 2). Fixed (ADR-006) by taking translation/rotation from a 4-DOF similarity (`cv2.estimateAffinePartial2D`, RANSAC) while `homography_inlier_ratio` keeps the homography's inlier share (a rigid-only probe lost real 10–15° yaw/tilt turns, reviewer): same scenes p95 2.4–4.6 px, rotation ≤ 1°; a real 40 px shift, a 5° rotation and a slow pan are reported within a pixel / 0.1°, so the reviewer's slow-pan case stays detectable. Thresholds unchanged; regression tests `test_geometry_is_still_on_a_noisy_smooth_wall`, `test_geometry_keeps_large_camera_turns_measurable`, `test_geometry_reports_a_real_shift_and_rotation_of_a_noisy_wall`; `docs/evidence/f3/static-scene.md` regenerated without `fov_shift` findings.
- [ ] [F3][evaluation] The 20 person-walk-by trials for `fov_shift` (gate box) are still open; the static-scene benchmark's walk-by cases now pass without `fov_shift` but are not the 20-trial protocol.
- [ ] [F3][vision] Documented miss (ADR-005): a frozen frame, or a replayed buffer of a static scene, re-emitted with per-frame decoder noise (any jitter > 0 since exact repeats are judged on the ≤ 640 px input frame; jitter 0.1 was still confirmed on the 160×120 image) is neither bit-exact nor claimable through hash repeats; `scripts/bench_static_scene.py` reports those cases as INFO. Needs transport evidence, not pixels
- [ ] [F3][vision] **REAL HARDWARE re-check before ticking the 20-min box (ADR-005):** a live *smooth* scene over H.264 decodes bit-exact in SIMULATION (libx264 CRF 23–28, `exact_repeat_ratio` 1.00), so the bit-exact rule can fire on a healthy compressed camera pointed at a plain wall. Run the owner's phone RTSP at rest on a textured room and on a plain wall (20 min each) and the webcam at rest, logging `visual.exact_repeat_ratio`, `visual.noise_ratio_p50`, `visual.temporal_sigma_p50`; repeat the plain wall with IP Webcam in MJPEG (`/video`) noting the quality setting, since a live σ 0.7 wall over MJPEG quality ≤ 50 is bit-exact in SIMULATION; expected: no `freeze` on the webcam, result on the plain wall decides the next item. Tool: `scripts/spike_static_scene.py --uri <uri> --minutes 20 --label <tag>` (reports `spikes/static-scene-<tag>.md/.json`, no URI inside; FAIL/exit 1 on any `freeze` window, INCONCLUSIVE/exit 3 if the source did not deliver a steady picture; handshake windows reported apart, not judged)
- [x] [F3][ingestion+vision] Pre-existing in production (independent review of the spike, SIMULATION): `runtime.py` analyses `buffer.latest()` at the analytic rate without checking `Frame.seq`, so a source slower than `analytic_fps` is judged on the same frame twice — at 1 / 2 / 4 source fps `exact_repeat_ratio` p50 0.8 / 0.6 / 0.1 (max 1.0, one `freeze` window at 1 fps). `scripts/spike_static_scene.py` skips re-read frames (`stalled_polls/polls` in its report); bring the same `seq` check to `runtime.py` in its own PR — done: `run_live` skips polls that return the same `Frame.seq` (`tests/unit/test_runtime.py`, SIMULATION: 10 polls/s on a 2 fps blocking source, `exact_repeat_ratio` 0.0)
- [x] [F3][vision] Pre-existing bit-exact false `freeze` on a live raw camera (independent review of ADR-005, SIMULATION): bit-exact repeats and the bit-exact loop period are judged on the probe input frame (`downscale(max_side=640)` in `runner.py`: native pixels at 640×480, 2× INTER_AREA at 720p/1080p), not on the 160×120 image; `loop_mse_max` moved to `configs/default.yaml` (`probes.loop_mse_max`, 0.5, still on the 160×120 image). Smooth wall σ ≤ 0.4 and σ 0.7 behind an 8-bit temporal denoiser no longer repeat (`tests/unit/test_probes.py`). Cost accepted (same mechanism, numbers in ADR-005): frozen + decoder jitter 0.1, and a replayed buffer of a *static* scene + jitter ≥ 0.1, are now misses; loops with real motion are detected as on `main`. Residual (reviewer): live wall 720p σ 0.1 or 1080p σ ≤ 0.2 still bit-exact after the 2× downscale. Not fixable with pixels: a live smooth wall over libx264 is bit-exact at full resolution at CRF 23–35 and a textured scene from CRF 28 → transport-evidence item below
- [ ] [F3][vision] Pre-existing (on `main` too, SIMULATION): a periodic multi-level flicker on a live sensor (±4 counts, period 2–8) trips the MSE-floor loop branch on the 160×120 image (σ 0.7: 300/420 windows). Judging that branch at full resolution loses replayed-buffer loops with decoder jitter (reviewer numbers in ADR-005); needs a noise-relative period test or transport evidence
- [ ] [F3→later][ingestion+vision] Transport-level freeze evidence for compressed sources (RTP timestamps / decoder frame counters / `CAP_PROP_POS_MSEC` advancing while pixels repeat), so `freeze` on RTSP does not rest on pixels alone; contract change → ADR
- [ ] [F3][evaluation] `benchmarks.replay.EXPECTED` has no entries for `loop4`/`loop8`, so `score()` cannot grade those runs (static-scene loops are now detected via the bit-exact period rule, ADR-004; re-measure loop8 on the static smooth scene)
- [ ] [F5][planner] Frozen black frame is reported as `blackout` only (ADR-003): if the exposure action fails verification while `exact_repeat_ratio ≥ 0.9`, plan `restart_capture` next instead of NEEDS_HUMAN
- [ ] [F1][safety] Simulated action apply/rollback ×2 — unit test green

## F2–F8
- [x] [F2][ingestion] Coverage ≥ 80% lines / 75% branches on `capture/` — CI `scripts/check_coverage.py` (96.1% / 90.8% sandbox)
- [x] [F2][ingestion] Disconnect < 5 s, non-blocking reconnect, telemetry resume < 15 s — `tests/unit/test_capture_resilience.py`
- [x] [F2][human] Contract suite on the integrated webcam (`RA_TEST_WEBCAM=0`) and on the phone RTSP (`RA_TEST_RTSP`) — `2 passed` in one run (REAL HARDWARE, 2026-10-08)
- [x] [F1][human] 10-min RTSP soak (`scripts/spike_capture.py --uri <rtsp> --minutes 10`): 533/536 valid windows (99.4 %), heap +1.6 %, 0 reconnects, REAL HARDWARE 2026-10-08 (`docs/evidence/f1/README.md`)
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
