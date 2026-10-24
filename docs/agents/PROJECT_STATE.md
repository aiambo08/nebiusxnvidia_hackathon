# Project state

Last update: 2026-10-24 · Current phase: **F9** (F8 independent gate review PASSED on `095617a`, 7/7 SIMULATION, `docs/evidence/f8/independent-review-2026-10-24.md`; F12 fresh-reviewer box ticked from the independent review on `9d026d1` (`docs/evidence/f9/independent-review-2026-10-24.md`), which also found REPLAY is not deterministic, so the F9 recorded-source box stays open; Windows CI flake fixed in `47fd021` (SIMULATION marker task timed with the simulated clock); F6 independent gate review passed (https://app.devin.ai/sessions/4ad9cabd2a5c4cb383b2e743273ef06e); F4 tooling is merged, but REAL HARDWARE sessions remain pending from the owner; F3 lacks REAL HARDWARE recall/precision, moved to F4; F1–F3 independent gate review pending; F9 product review remains open; F12 preparation is documentation only, with every F12 gate unchecked) · Days to deadline: 15

## Snapshot
- F6 offline golden set (SIMULATION, `benchmarks/golden/golden_v1.jsonl`): 136 captured-incident cases (base 100, no_cap 16, injection 20; dev 48 / test 88); evaluation and grading are implemented without live Token Factory calls.
- F6 offered-action update (ADR-009): `PolicyGate` offers actions relevant to local candidate faults plus safe escalation, and includes `freeze` for a frozen confirming window. `golden_v2.jsonl` has the same 136 case IDs, labels, expected actions, seeds, and splits as v1, with offered actions narrowed. The deterministic rules baseline on v2 test (264 rows, 3 repeats) scored 100% schema validity, 100% correct actions, and $0 projected cost (`docs/evidence/f6/golden-rules-baseline-test.md`).
- F6 tooling follow-up: `scripts/build_golden.py` requires an explicit `--out` and protects existing outputs unless `--force`; the frozen v1/v2 files were left unchanged. `scripts/spike_nemotron.py` uses ADR-009 `PolicyGate.offered_for` for its synthetic incidents.
- Earlier live results (run by Devin with the owner's Token Factory key; reports in `docs/evidence/f6/`): diagnose_v1 fast test was 100% schema/first-try valid but 75.379% action accuracy (FAIL), projected $0.0334/300; dark base/injection 0/48 (restart 37, cleaning 7, safe mode 4), with no_cap cases choosing actions from other faults. v1 dev 102/144. The earlier diagnose_v2 fast dev was 120/144 on golden_v1 (base+injection 120/120, no_cap 0/24); v2b fast dev was 125/144 (no_cap 5/24, removed as an iteration); v2 Super-120B reasoning dev was 42/48 (no_cap 2/8). Before ADR-009, v2 was tuned only on dev and had not been run on test.
- Golden-v2 live re-run (diagnose_v2, fast Nano-30B; `golden_v2` SHA `acc80447…`; `configs/default.yaml` now defaults to `diagnose_v2`): dev, 48×3, 141/144 correct (97.917 %); the only miss was defocus-injection-s01 ×3 (trigger_autofocus with extra args, rejected by policy); cost $0.01655832. The golden_v2 dev report is `golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-dev-2.{md,json}`; the older `...-dev` report used golden_v1. Test, 88×3=264, run once after dev with no change in between: schema-valid 100 %, valid first try 100 %, action accuracy 98.864 % (261/264), projected $0.0347/300 incidents (gate $23), run cost $0.03057240, latency p50/p95 1005/1354 ms. Misses: defocus-base-s11 r1 `{'delta_ev': 0.0}`, defocus-injection-s06 r2 `{'delta_ev': 0.0}`, and defocus-injection-s07 r3 `{'delta': 0.0}` — correct action trigger_autofocus with invented args; policy gate rejected them and nothing executed. dark and no_cap were 100 %. The deterministic rules baseline on v2 test is 100 %, so this measures following the local diagnosis and respecting limits, not independent diagnosis. Total live spend ≈ $0.175. F6 schema, action, and cost boxes are evidenced; independent gate review passed (https://app.devin.ai/sessions/4ad9cabd2a5c4cb383b2e743273ef06e).
- F9 dashboard: thread-safe LiveFeed, read-only FastAPI status/windows/frame/incidents endpoints, and `ra-demo dashboard` simulation/live runner share one EventStore. The API never starts actions or scenarios. `tests/integration/test_dashboard_f9.py` covers read-only routes, the seven runner terminal paths, and sentinel-free API/log/store surfaces through both the runner and real dashboard CLI path with offline FakeSDK; the no-secrets-in-final-video check remains open. `docs/evidence/f9/demo-flow.md` records default-pace SIMULATION timings and a synthetic REPLAY run. The completed static page is `apps/dashboard/index.html`; F9 product evidence and gate review remain open (author-side evidence refreshed on `main` at `bc6ea44`: 7 SIMULATION timings, REPLAY readiness, the `bad_action → dark` header-reset tour — 1,227 samples never returning to `scripted` — and fresh headless screenshots cross-checked against the rendered DOM). The dashboard header planner is decided by the backend (`/api/status`): `LiveFeed.set_scenario` stamps `scenario_started_at`, incidents left over from a previous scenario never drive the header again, the model/prompt chips are hidden when the planner is local/scripted, `/api/status` serves the computed header source (so `cache`/`fallback` labels stay consistent with the model/prompt chips), and a behavioural test (`test_dashboard_header_planner_resets_across_scenario_switch`) runs the real `bad_action → dark` tour across the switch.
- README SIMULATION media is in `docs/media/`, with provenance in `docs/media/README.md`; seven live Nemotron calls cost $0.0008336. No REAL HARDWARE footage is shown.
- F7 crash recovery (SIMULATION, real subprocess kill): `tests/integration/test_crash_recovery.py` kills a child after snapshot persistence, during device settings persistence, and in `VERIFYING`; the next start restores the exact snapshot, escalates the same incident without a new plan, and leaves a valid event chain. A crash after verification commits but before `mark_restored` also conservatively rolls back and escalates. The policy gate rejects numeric arguments whose float conversion overflows without letting the exception escape `on_window` (`tests/integration/test_policy_gate_overflow.py`). The F7 gate passed on `76797de` after independent review; real-webcam exposure/autofocus capability discovery remains a TASKS follow-up outside the eight gate boxes, and the real `OpenCVSource` exposes `restart` only.
- F10 SIMULATION soak evidence is merged on `main` at `7c4607c`: 4.0 h, 23/24 faults detected, 0.25 false alarms/h, +7.2 MB RSS and $0 (`docs/evidence/f10/soak/soak.md`). REAL HARDWARE validation remains pending; F10 is in progress and the gate is not passed.
- F8 verification and rollback (SIMULATION): `tests/e2e/test_action_commit_rollback.py` covers commit and rollback for all five MVP actions using test-only device effects; `tests/unit/test_restore.py` proves a restart during VERIFYING restores the snapshot and escalates the same incident without replanning. Event-derived incident examples are in `docs/evidence/f8/incident-reports/`. Clean-code benchmark at `13d25590ae5561f0eb1cd5559d80cf5da7475f9c` recovered 87/100 capability-remediable cases (87%, above the 85% gate), with 3 needs-human and 10 timeouts; all ten timeouts were dark:0.8 runs without a confirmed incident. The raw regression result remains 45/50: all 45 executed regressions rolled back with exact snapshot restoration, and the five non-executed dark:0.8 runs had no confirmed incident and left device settings unchanged, so the revised 100% gate passes. Frozen_black uses the agent's local restart plan and keeps the repeated frame across restart. Full breakdown: `docs/evidence/f8/recovery-bench.md` and `.json`. No thresholds or decision logic were changed.
- F11 public-repository hardening: `scripts/license_report.py --check` compares 35 distributions resolved from runtime dependencies, every optional extra, and transitives for Linux and win32. `certifi` MPL-2.0 is flagged as copyleft; the win32-only `colorama` 0.4.6 entry uses a BSD License override sourced from its exact PyPI JSON record. No UNKNOWN or non-commercial licences were found. `scripts/audit_repo.py` scans tracked files and full Git history, checking path names and blob content for credential patterns; typed path allowlists waive only documented non-credential findings, while credentials always fail and oversized blobs require an `oversized_blob` waiver. Five synthetic JSONL paths are justified in the allowlist; F0 logs cite `scripts/spike_nemotron.py` at `3f5e4e3`, golden v1 cites `scripts/build_golden.py` at `2275652`, and golden v2 was added under ADR-009 at `a245332` and can be generated with `scripts/build_golden.py --out <path>`; the frozen file is protected from accidental overwrite. The report is `docs/evidence/f11/public-repo-audit.md`; CI's `secret scan` job also runs gitleaks over full history. The license document records the conditional FFmpeg/libgfortran notices; the project redistributes no wheels. Independent README-only installation passed at `190ce74`; the F11 gate passed on `d16436f`.
- F5 gate review (independent, 2026-10-17, SIMULATION): passed, 6/6 conditions; 710 passed, 1 deselected, 2 xfailed, Ruff clean and CI 5/5 on `d425c03`.
  Hysteresis report `b6ddfd3` remains valid: intervening source changes are limited to `demo.py`, `nemotron/planner.py` and `orchestrator._handle_confirmed`/`_frozen` (none imported by `bench_hysteresis`); the config diff adds only `calibration_discard`, `stall_windows`, `restore_on_start`, `checkpoint_windows` and `lease_stale_s`, with no threshold relaxed.
  Reviewer checks: 36 random clean/crash restarts preserved state sequences; seeds 7/11/23 were deterministic across processes; 35/35 fault cases confirmed once and closed; lighting gains 0.30–1.525, a 50% ramp and 60/120 px crossings yielded 0 SUSPECT states and 0 planner calls.
- Frozen-black handling (SIMULATION, `tests/e2e/test_scenarios.py` and
  `tests/adversarial/test_frozen_pipeline.py`): a confirmed blackout on a bit-exact frozen pipeline
  plans `restart_capture` first when supported; exposure and autofocus are withheld, and a device
  without restart escalates to NEEDS_HUMAN.
- The frozen check sees only the confirming window; freeze onset can miss that window due to timing,
  and frozen `overexposure`/`focus_drift` cases remain outside the BLACKOUT-only shortcut. They may
  receive one exposure/autofocus action, then snapshot-backed rollback and NEEDS_HUMAN, preserving
  the prior one-action behavior. Checking recent windows is open work (TASKS.md).
- F5 hysteresis (SIMULATION, `scripts/bench_hysteresis.py` → `docs/evidence/f5/hysteresis.md`, ~33 min):
  over the same windows of the real probe path, the tracker flaps 66–100 % less than a memoryless
  per-window detector in every (MVP fault, glitch rate) cell and changes alert 67.7 % less overall,
  while alerting on all 180 sustained faults. Alert (CONFIRMED) flapping only: internal HEALTHY↔SUSPECT
  moves drop just 9–36 %; every sustained alert closes; glitches are 1–2 windows (< `enter_windows`).
- F5 end to end (SIMULATION, `tests/e2e/test_confirm_and_return.py`): with the default config, each of the
  5 MVP faults is confirmed once with the expected fault after calibration (one planner call) and closes
  once it clears; a legitimate lighting change (82.5 % / 65 % brightness, transient or persistent) never
  leaves HEALTHY; a 2-window transient of each MVP fault (freeze: 3, first flagged in its third frozen window) goes SUSPECT and back to HEALTHY; the planner is
  never called in either case. All six F5 boxes are evidenced in SIMULATION.
- F5 restart persistence (SIMULATION, `tests/unit/test_restore.py`): FSM, hysteresis counters, cooldowns,
  gate rate-limit history and baseline restored from SQLite, one checkpoint per camera id; uncommitted
  actions of this camera rolled back on restart, its never-closed incident resumes as NEEDS_HUMAN without
  a new plan (also across a second restart); a heartbeat lease refuses a second live agent with the same
  camera id (`RA_CAMERA_ID`).
- F5 automatic calibration (SIMULATION, `tests/unit/test_calibration.py`): the baseline learns only
  fault-free HEALTHY windows; before `min_samples`, a visual fault also drops the 3 windows just before it
  (`calibration_samples_discarded`); readiness logs `baseline_calibrated` with `baseline_version` once and
  checkpoints at once; the `restore` event carries `baseline_version` and `baseline_ready`; an unready baseline
  with no progress for `baseline.stall_windows` (120) windows logs `calibration_stalled` once.
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
  windows, heap +0.4%, 0 reconnects (`docs/evidence/f1/`). The live probe p95 (110 ms webcam, 248 ms RTSP) vs 20–25 ms isolated is
  only partly attributed in SIMULATION (`spike_capture.py` measures with tracemalloc + capture thread
  on raw 640×480; `bench_probes.py` flags reproduce ~2×); the probe-cost rewrite (no threshold
  change) cuts sandbox p50 by 24 % at 720p and 33 % under spike conditions (p95 56 → 40 ms).
  Owner's laptop (REAL HARDWARE CPU, `docs/evidence/f3/latency-hardware.md`, synthetic frames): the paced tail is mostly Windows
  power management — 720p paced p95 54–112 ms on "Balanced", 41.4 ms on "Best performance" (1.4 ms
  over before the geometry change); no OpenCV thread setting brought it below
  54 ms under "Balanced" (single runs). Geometry now runs on a pool thread alongside the other
  probes, same output (SIMULATION, indicative: 720p p95 2.6–4.1 ms lower in a same-process A/B). Owner
  re-measured 720p paced ×3 on "Best performance": p95 23.2 / 32.6 / 34.5 ms — latency box ticked
  (demo requires plugged in + "Best performance").
- F1 replay tooling: record a clean clip, inject seeded blur/dark/freeze, replay it through
  `OpenCVSource` + probes + tracker offline (no LLM). REAL HARDWARE clip s001 (SIMULATION faults):
  dark/blur/freeze detected in 2.9 s, 0 false alarms on the clean clip.
- F3 recall/precision box (SIMULATION, `scripts/bench_detectors.py` → `docs/evidence/f3/detectors.md`):
  156 seeded runs, recall and precision 1.00 for every detector after ADR-007 (strong blur recall and
  lens_occlusion precision were 0.96 before), 0 confirmations on 24 negative controls. Two fusion mis-attributions found
  and fixed (saturation ⇒ no `focus_drift` claim; `lens_occlusion` is now judged per cell, ADR-007).
  REAL HARDWARE recall/precision is F4.
- F3 per-cell occlusion (ADR-007, SIMULATION): cells compared with their calibration cells, clipped
  cells excluded, global/motion blur no longer counted as occlusion, hand-like occluders detected.
  Known new false positive: hard local shadow (TASKS). The walk-by false positive on a low-texture
  wall calibrated with a person in view is fixed by ADR-008 (each cell calibrates once it is still
  for 2 s; untextured cells take the median of their at-rest frames at 30 s; cells never at rest
  stay unjudged unless calibration fails globally; a textured person standing still ≥ 2 s during
  calibration is still learned).
- F3 started: spurious `freeze` on dark/blurred live scenes fixed by causal suppression (ADR-003,
  `docs/evidence/f3/`); owner to confirm on the real clip replay. The absolute MSE floor that
  flagged a healthy σ=2 static scene was first replaced by a learned camera-relative noise floor
  (ADR-004, PRs #11/#14), which independent review showed is contaminated by any motion before
  rest (walk-by, 5–40 px low-contrast objects) and never recovers. ADR-005 drops the learned
  history: `FreezeTracker` measures per frame the temporal-vs-spatial noise ratio and the
  temporal sigma and exports them as telemetry (`visual.noise_ratio_p50`, `temporal_sigma_p50`).
  They are not a trigger: the 4th review pass and a libx264 reproduction showed a live static
  scene over H.264 has no temporal noise either (smooth wall: bit-exact), so perceptual-hash
  repeats were dropped as freeze evidence and `freeze` = bit-exact repeats or loops (ADR-003
  rule, `exact_repeat_ratio_min` 0.9 unchanged; `repeated_hash_ratio_min`, `temporal_mse_floor`,
  `noise_floor_quantile`, `noise_collapse_ratio` removed). `scripts/bench_static_scene.py` →
  `docs/evidence/f3/static-scene.md`: 20-min SIMULATION static scenes incl. the reviewer's cases
  with 0 freeze false positives; bit-exact and looped streams confirmed, jittered freezes are a
  documented miss. The 20-min box passed on REAL HARDWARE on 2026-10-11 (`docs/evidence/f3/static-scene-hardware.md`:
  PASS on webcam at rest and phone RTSP wall/textured, MJPEG q80 INCONCLUSIVE but 0 `freeze`; the phone's H.264 wall was never bit-exact). Background (a smooth wall may decode
  bit-exact while alive: libx264 repeats a live smooth wall bit-exact at full resolution at every
  CRF, SIMULATION; the raw-sensor cases — σ ≤ 0.4 wall, strong temporal denoiser — are fixed since bit-exact
  repeats are judged on the probe input frame (≤ 640 px side) instead of the 160×120 image, at
  the cost of missing frozen + jitter 0.1 and replayed static buffer + jitter 0.1; 720p σ 0.1 / 1080p σ ≤ 0.2 and MJPEG q ≤ 50 still repeat;
  periodic flicker still trips the 160×120 MSE-floor loop branch, pre-existing),
  tool ready for the owner's run: `scripts/spike_static_scene.py` (live source -> production
  path, per-window freeze telemetry, reports without the URI, `tests/unit/test_spike_static_scene.py`),
  and `run_live` no longer judges the same `Frame.seq` twice on a source slower than
  `analytic_fps` (`tests/unit/test_runtime.py`), and `fov_shift` no longer fires on a smooth wall at rest:
  `GeometryProbe` takes translation/rotation from a rigid similarity fit while the homography keeps
  the inlier gate (ADR-006; SIMULATION, thresholds unchanged, `tests/unit/test_probes.py`; the 20 walk-by trials pass on REAL HARDWARE 2026-10-13 with `scripts/spike_walkby.py`: 22/22 observed on the owner's webcam, 0 `fov_shift` windows, BUMP detected, `docs/evidence/f3/walkby-hardware.md`),
  transport-level freeze evidence for compressed sources (later phase),
  recall/precision per detector on real clips (F4), live probe p95 at 720p.

- F4 started (SIMULATION tooling): session index (`benchmarks/dataset.py`, `sessions.yaml`),
  `record_clip.py --split/--conditions`, pre-registered manifests (`benchmarks/build_manifests.py`),
  `make_degraded --all`, one-command report `scripts/run_benchmark.py` (gate boxes, macro F1,
  false alarms/h with a re-armed tracker). Waiting for the owner's F4 recordings (REAL HARDWARE).

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |
| 2026-10-05 | ~0.02 (spikes + probes) | to confirm by Aibo |

## F8 review revalidation
- SIMULATION on clean code commit `20c4126c218229646395ba7bff3aa8dd50399891`: recovery remained 87/100 (3 needs-human, 10 timeouts); raw regression remained 45/50. All 45/45 executed runs rolled back with exact snapshot restoration, and all five non-executed dark:0.8 runs left settings unchanged. The executed-coverage floor passed for dark, defocus, overexpose, and frozen_black. Recovery classification and incident reports are EventStore-only; regression uses EventStore events, initial/pre-action/final device settings, and `ScenarioResult.final_state`. Defocus and frozen_black `enter_safe_mode` proposals are non-remediating actions. Full report: `docs/evidence/f8/recovery-bench.md` and `.json`.
- Classifier follow-up: `tests/unit/test_recovery_classifier.py` retains the no-rollback execution failure test and separately pins non-exact rollback diagnostics (`snapshot_equal=False`) and non-executed changed-settings rejection; M14, M6a and M7 mutation checks kill their respective mutants.

## F10 PR2 experiments (SIMULATION; gate in progress, not passed)
- `docs/evidence/f10/experiments.md` and `.json` summarize 454 valid EventStores: A1–A7 remain from the clean grid commit `496ac7b`, and only A8 was rerun on clean code commit `4f3c18e`; no live calls were made. A3 recovery is 25/25 on classifier-recoverable runs; the F8-comparable cells are 20/20. The F8 classifier returns `recoverable=False` for occlusion, so its five ticket/needs-human outcomes are separate from that denominator.
- A4's regression events use the visual metric override and contain no `task.*` metrics; the deliberate-regression result remains 0 COMMITTED vs 0 for A3. Per fault family, both arms have five rolled-back verification decisions and zero committed or inconclusive decisions. No ablation metric or threshold was tuned.
- A8's `policy_reject` trace reaches `REJECTED`, and `failed_apply` reaches `FAILED` before rollback; restart stores cover every state reached in each trace. Only `SAFE_MODE` and `CLOSED` are unreachable because runtime transition call sites outside `state_machine.py` do not target them; other absent states are listed as not reached in their respective scenario.
- A6 used fallback for all 25 planner-routed incidents; its five `frozen_black` cases are separately reported as deterministic local plans with the planner not called. The `circuit_open` field is cumulative across the arm because one breaker is shared across its 30 runs. A7's RTSP failure lands during the action's verification window; simulated actions return instantly. The SIMULATION soak is merged on `main`; REAL HARDWARE validation remains pending, so F10 is in progress and not passed.
## F10–F12 submission status
- F10 A1–A8 SIMULATION evidence is merged on `main` at `34390e7`; cite `docs/evidence/f10/experiments.md`. The 4 h SIMULATION soak is merged at `7c4607c`: 4.0 h, 23/24 faults detected, 0.25 false alarms/h, +7.2 MB RSS and $0 (`docs/evidence/f10/soak/soak.md`). REAL HARDWARE validation remains pending; F10 is in progress and the gate is not passed.
- F11 license-inventory and public-repo-audit boxes are ticked on `main` (`4b5b929`; 218 tracked files, 35 distributions); an independent agent installed and ran it from the README alone at `190ce74` (`docs/evidence/f11/readme-install.md`), so all F11 boxes are ticked; the independent F11 gate review passed on `d16436f` (all 7 boxes verified), so F11 is passed (`docs/evidence/f11/public-repo-audit.md`, `docs/third-party-licenses.md`).
- F12 submission docs are prepared in `README.md`, `docs/compliance-matrix.md`, `docs/demo-script.md`, `docs/devpost.md`, `docs/feedback.md` and `docs/es/pasos-del-propietario.md`. The author-run fresh-clone transcript is `docs/evidence/f12/quickstart.md`, re-run on 2026-10-20 at `bc6ea44` (Python 3.13.16): 952 passed / 1 deselected / 2 xfailed, `ra-demo all` passed 7/7, `dashboard --help` incl. `--live --uri 0 --help`, and the SIMULATION dashboard returned HTTP 200; the synthetic `record_clip` smoke is CLI-only, not F4 or REAL HARDWARE evidence. A PR reviewer independently reproduced the fresh-clone quickstart, but that review transcript is not committed as judge-open evidence, so the F12 reproduction box remains unchecked. Real UVC/ONVIF exposure/focus control is not implemented: the webcam exposes only `restart`; bounded exposure/focus commit/rollback is SIMULATION only. The demo script accepts a cleaning ticket, safe mode or `needs_human` escalation as live webcam outcomes; it does not claim stream-down recovery through the live dashboard because no combined test covers that path. No F12 gate is claimed complete; F4 webcam benchmark, physical demo video, five-user test, final tag, incognito link check and Devpost submission remain owner/reviewer work.
## Blockers
- Token Factory console balance to be confirmed by Aibo.

## Next 3 actions
1. Webcam + phone RTSP contract passed on REAL HARDWARE (2026-10-08), closing the shared F1/F2 box. 10-min RTSP soak passed (533/536, 99.4 %). Next: independent F1/F2 gate review.
1b. Devin: F3 — structure veto for hard shadows (ADR-007 follow-up), the 20 walk-by trials are done (REAL HARDWARE 2026-10-13); owner runs `bench_probes.py` flags (the four 20-min static-scene checks are done, REAL HARDWARE 2026-10-11).
2. Ingestion: probe UVC exposure/autofocus on the integrated webcam (decides UVC vs pipeline action).
3. Nebius (F6): golden set including the cases where the reasoning tier disagrees with the local top fault.
