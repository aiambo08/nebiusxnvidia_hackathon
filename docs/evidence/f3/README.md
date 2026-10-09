# F3 evidence — visual monitors

All results below are **SIMULATION** unless marked REAL HARDWARE. Thresholds in
`configs/default.yaml` (`probes.*`, `faults.*`) are unchanged in this phase so far.

## Freeze specificity on dark and blurred live scenes (ADR-003)
Risk recorded at F1: on the owner's real clip, `dark` and `gaussian_blur` also confirmed `freeze`,
ranked first. Reproduced in SIMULATION with a smooth scene and a quiet sensor (σ ≈ 0.7 counts):

| Scene (160×120 analysis image, median of 30 frames) | temporal MSE | hash repeat | exact repeat |
|---|---:|---:|---:|
| live | 0.42 | 0.80 | 0.00 |
| live, dark 95 % | 0.0006 | 1.00 | 0.00 |
| live, blur (k=43) | 0.42 | 0.00 | 0.00 |
| frozen | 0.0000 | 1.00 | 1.00 |
| frozen, dark 95 % | 0.0000 | 1.00 | 1.00 |

Fix: freeze is evaluated last and suppressed under blackout; under focus drift only bit-exact repeats
or loops count. Regression tests (fail before the fix, pass after):

| Test | What it proves |
|---|---|
| `tests/unit/test_probes.py::test_live_dark_scene_pixels_do_not_classify_as_freeze` | pixel-level: darkened live wall scene → `blackout` only, although `repeated_hash_ratio ≥ 0.95` |
| `tests/unit/test_probes.py::test_frozen_lit_scene_pixels_classify_as_freeze` | pixel-level: the same scene frozen → `freeze` (recall kept) |
| `tests/unit/test_baseline_fusion.py::test_dark_live_scene_is_blackout_not_freeze` | rule-level: dark + repeats → `{blackout}` |
| `tests/unit/test_baseline_fusion.py::test_strong_blur_hash_repeats_are_not_freeze` | rule-level: blur + hash repeats → `focus_drift`, not `freeze`; bit-exact repeats still `freeze` |
| `tests/unit/test_baseline_fusion.py::test_frozen_dark_pipeline_is_attributed_to_blackout` | documented limitation |

Pending REAL HARDWARE confirmation: replay the owner's `f1-s001-dark.yaml` / `f1-s001-gaussian_blur.yaml`
manifests (`python scripts/spike_inject.py`, clip is git-ignored) and check that `freeze` no longer
appears among the confirmed faults. Command for the owner (PowerShell, repo root, after merging):
`uv run python scripts/spike_inject.py --clip benchmarks\data\s001_clean.avi --faults dark,gaussian_blur,freeze`.

Independent review of this PR (SIMULATION, `origin/main` vs branch): freeze recall on lit scenes unchanged
(manifest `f1-s001-freeze.yaml` 10/10, loop4/loop8 10/10, clean clip 0/700 windows, static wall σ=0.7 10/10);
no `configs/` diff. Findings folded into the PR: freeze ranking priority (`rank_faults`); blur recall cost
quantified in ADR-003. Finding **not** caused by this PR and now the first open F3 item: a healthy lit textured
static scene with σ=2 noise already trips the absolute `temporal_mse_floor` on `main` (358/400 windows).

## Freeze noise floor relative to the camera (ADR-004, superseded) — SIMULATION
Independent review of PR #10 found that a healthy, lit, static textured scene with σ=2 webcam noise
tripped `freeze` in 358/400 windows on `main`: after the 4×4 downscale its temporal MSE (≈ 0.41) sits
under the absolute `temporal_mse_floor` (0.5) while dHash repeats. PRs #11 and #14 replaced the
absolute floor by a floor learned from the camera's own healthy windows. Three independent review
passes showed the learned floor is contaminated by any motion that precedes rest and never recovers
(the baseline freezes while the incident is active): 30 s walk-by at start-up (328/360 false freeze
windows), 5–20 px objects (dHash does not see them, MSE does), and on the σ 0.7 wall 5 px / 8 px /
20 px at +15 counts / 40 px at +8 counts (118–120 of 420 windows each, the last a regression). The
PRs were merged by the owner; the design is withdrawn by ADR-005 below. The ADR-004 record keeps
the quantisation findings (dark scenes crush the noise below one count) and the alternatives table.

## Freeze noise measured per frame, no learned history and no pixel trigger (ADR-005) — SIMULATION
`probes/temporal.py::noise_sigmas` measures on every frame pair, at full resolution and on the
flattest half of the frame (Sobel magnitude ≤ median): the **temporal sigma** (RMS frame difference
/ √2) and the **spatial sigma** (Immerkaer's Laplacian estimator). Both are exported as telemetry
(`visual.noise_ratio_p50`, `visual.temporal_sigma_p50`) and attached to freeze incidents as evidence.
They are **not** a trigger: `freeze` is claimed only on bit-exact repeats
(`faults.freeze.exact_repeat_ratio_min`, 0.9, unchanged) or a frame loop; perceptual-hash repeats
no longer count at all. `repeated_hash_ratio_min`, `temporal_mse_floor`, `noise_floor_quantile` and
`noise_collapse_ratio` are removed from `configs/default.yaml` (nothing reads them).

Why the collapse is not a trigger (4th independent review pass + reproduction with libx264,
`tests/unit/test_noise_ratio.py::test_live_static_scene_over_h264_is_pixel_identical_to_a_frozen_one`):

| live static scene through libx264 (640×480, veryfast) | hash repeat | exact repeat | ratio p50 | σ_t p50 |
|---|---:|---:|---:|---:|
| textured, σ 2, CRF 23 | 1.00 | 0.01 | 0.04 | 0.03 |
| textured, σ 2, CRF 28 | 1.00 | 0.62 | 0.00 | 0.00 |
| smooth wall, σ 0.7 / 2, CRF 23 / 28 | 1.00 | **1.00** | NaN | 0.00 |

A healthy compressed camera at rest is pixel-identical to a frozen one (skip macroblocks); the draft
rule (ratio ≤ 0.3 and σ_t ≤ 0.5) produced 73/240 false `freeze` windows on the textured CRF 28 clip
(0/240 on `main`), and 27–240/240 with an ISP temporal denoiser or a quiet sensor on fine texture.

Population table of the telemetry (`tests/unit/test_noise_ratio.py`, four scene types, σ 0.7–3, gain 0.3),
the reference for reading the two fields on REAL HARDWARE:

| population | ratio | σ_t (counts) |
|---|---|---|
| live raw static, any σ / texture / gain | 0.99–1.01 | = sensor σ |
| live + motion 40 px at +8 / 20 px at +15 / 5 px / 8 px / person | ≥ 1.09 / 1.14 / 1.28 / 1.70 / 8.7 | ≥ sensor σ |
| live, spatially correlated noise / Poisson / 2 % flicker | 5.3 / 1.0 / 1.7 | ≥ 1 |
| live, pixel-scale static grain σ 6 + sensor σ 1 | 0.17 | 1.0 |
| live, H.264 static scene (CRF 23–28) | 0.00–0.04 | 0.00–0.03 |
| frozen bit-exact / + jitter 0.1 / 0.25 / 0.5 | 0.00 / 0.00 / 0.11–0.27 / 0.27–0.60 | 0 / = jitter |

Documented miss: a frozen frame (or a replayed buffer of a static scene) re-emitted with decoder jitter is neither bit-exact (exact repeats
are judged on the probe input frame (≤ 640 px side, not the 160×120 image), where any jitter breaks equality — jitter 0.1 was still
confirmed while they were judged on the 160×120 image) nor claimable through hashes; the benchmark
lists those cases as INFO. The independent review also
measured pre-existing bit-exact false positives on the 160×120 analysis image (raw smooth wall
σ ≤ 0.4, strong 8-bit temporal denoiser): fixed by judging
bit-exact repeats on the ≤ 640 px probe input frame (`tests/unit/test_probes.py`; `probes.loop_mse_max` now in config, unchanged). A ±4 periodic
flicker still trips the 160×120 MSE-floor loop branch (pre-existing, `docs/agents/TASKS.md`). Pre-existing risk, measured and not reachable with pixels: a
live **smooth** scene over H.264 decodes bit-exact, so the bit-exact rule can fire on a healthy
compressed camera pointed at a plain wall. REAL HARDWARE must decide: the owner's webcam and phone at
rest (textured room and plain wall) with `exact_repeat_ratio`, `noise_ratio_p50` and `temporal_sigma_p50`
logged, before the 20-min box is ticked (`docs/agents/TASKS.md`). Tool for that run:
`python scripts/spike_static_scene.py --uri <uri> --minutes 20 --label <tag>` drives the production
path (`CaptureWorker` -> probes -> windows -> baseline -> `IncidentTracker`) on a live source and
writes `spikes/static-scene-<tag>.md` (summary, quantiles of the three fields, verdict) and
`spikes/static-scene-<tag>.json` (per-window series + worker `health()`); neither contains the URI,
and a label with a URL or IP is rejected. Verdict with the same criterion as the table above: FAIL
(exit 1) on any `freeze` window, INCONCLUSIVE (exit 3) when the source did not deliver a steady
picture (first frame after more than 10 s, frames in < 95 % of the judged windows, or
`stream_down`/`low_fps` in > 5 % of them), PASS otherwise. Windows before the first frame (RTSP
handshake + H.264 warm-up) are reported apart and never judged; another detector
confirming on the healthy scene is reported as a finding, as in the table. FFmpeg may print the
camera address on stderr when a connection fails, so stderr is not evidence to paste. Dry run:
`--synthetic --minutes 0.5` (SIMULATION, 0 freeze windows, `tests/unit/test_spike_static_scene.py`).
Structural answer for compressed sources: transport-level freeze evidence (RTP timestamps / frame
counters), later phase.

## `fov_shift` false positive on a smooth wall at rest (ADR-006) — SIMULATION
Finding of the 20-min static-scene run: every smooth `wall` scene and every walk-by case confirmed
`fov_shift` with the camera at rest. `equalizeHist` amplifies sensor noise into ~210 spurious ORB
keypoints and the 8-DOF homography fitted through them still finds ≈ 60 % inliers while its
translation bends to the noise (σ 0.7–4: p95 27–48 px, max 94 px, rotation up to 3°; 14–33 of
180 windows met the rule, confirmations at σ 2 and 4). `GeometryProbe` now takes `translation_px`
and `rotation_deg` from a 4-DOF similarity (`cv2.estimateAffinePartial2D`, same RANSAC
threshold) — same scenes p95 2.4–4.6 px, rotation ≤ 1°, 0 `fov_shift` windows at rest and in the
walk-by / small-object cases — while `homography_inlier_ratio` stays the homography's inlier
share, because the independent review showed a rigid-only probe loses real 10–15° physical
yaw/tilt turns on a textured scene (inliers 0.20–0.34 < 0.35). 25–40 px shifts, 4–5° rotations,
0.2–1 px/frame pans and 10–15° yaw/tilt stay confirmed; a pure keystone without translation and
an in-plane rotation of exactly 3° on a smooth wall are not (documented in the ADR). Thresholds
and contract unchanged; `static-scene.md` regenerated without `fov_shift` findings; probe cost
unchanged. Tests: `tests/unit/test_probes.py::test_geometry_*`.

## Recall / precision per detector — SIMULATION
`scripts/bench_detectors.py` → `detectors.md`. 156 seeded runs on the `SyntheticSource` textured
scene (sensor noise σ 1/2/3, 30 s healthy lead-in, 30 s of one injected fault from
`benchmarks/injectors/faults.py`, strong strengths only; 4 seeds per fault × strength × σ), full
local path (`benchmarks.replay.replay`), production thresholds. TP = the detector `EXPECTED` maps
the injector to is confirmed after onset; FP = any detector confirmed where not expected.

| detector | runs | recall | precision | delay p50 |
|---|---|---|---|---|
| blackout (`dark` 0.9/1.0) | 24 | 1.00 | 1.00 | 2.8 s |
| focus_drift (`gaussian_blur` 0.7/1.0) | 24 | 0.96 | 1.00 | 2.8 s |
| freeze (`freeze`, `loop4`, `loop8`) | 36 | 1.00 | 1.00 | 4.8 s |
| lens_occlusion (`occlude_opaque` 0.7/1.0) | 24 | 1.00 | 0.96 | 2.8 s |
| overexposure (`overexpose` 0.8/1.0, not gated) | 24 | 1.00 | 1.00 | 2.8 s |

Negative controls (clean scene and a legitimate 35 % lighting change, 24 runs): 0 confirmations.

Findings fixed in the same PR (production rules, thresholds unchanged, `docs/agents/DECISIONS.md`):
every strong overexposure run also confirmed `lens_occlusion` (a clipped-white frame makes every
cell uniform and edge-less; precision 0.50) and, once that was suppressed, `focus_drift` (no edges
left to judge). Both rules now require a non-saturated window, symmetric to the blackout
suppression of ADR-003. `benchmarks.replay.EXPECTED` grades `loop4`/`loop8` as `freeze`.

Documented miss: one `gaussian_blur` 1.0 run (σ 3, seed 2) is confirmed as `lens_occlusion`
instead of `focus_drift`. A 43 px defocus removes 80 % of the texture of 17–31 % of the grid
cells (`occluded_cell_ratio` 0.17–0.31 across seeds, threshold 0.30) while `blur_effect_p50` is
0.71, and the fusion rule lets occlusion mask blur. Extreme uniform defocus and a partial smudge
are not separable with the current window metrics; tracked in `docs/agents/TASKS.md`
(per-cell occlusion vs global defocus). The gate still passes (recall 0.96, precision 0.96).

What "strong" means here, from the independent reviewer's sweeps just below the bench strengths
(SIMULATION, σ 2, identical on `main`): `dark` 0.8 leaves `brightness_p50` at 26 against the
25 cap and nothing fires on a 78 % brightness drop (0/4; 0.85 → 4/4); `occlude_opaque` 0.3
(38 % of the width) → 0/4, 0.5 (50 %) → 4/4 with a 2.8 or 7.8 s delay depending on how the band
lands on the 8×8 grid; `gaussian_blur` 0.4/0.5 → 8/8 at 2.8 s. A hand-like textured occluder
(mean 90, σ 10) over 40–60 % of the width gives `occluded_cell_ratio` 0.05–0.06 (threshold 0.30)
and is never detected: the 1.00 occlusion recall rests on the flat-value injector. A
semi-transparent smudge (`occlude_semi` 1.0) is confirmed 3/3 at 2.8 s and does not push
`white_pixel_ratio` past 0.17, so it never suppresses itself. A real occlusion that co-occurs
with a clipped frame (white ratio ≥ 0.45) is now reported as `overexposure` alone until exposure
is restored; on `main` the same claim was false on every pure overexposure run.

Accounting caveat: `benchmarks.replay.replay` records the first confirmation only and the tracker
stays CONFIRMED, so a wrong detector that appears after a correct confirmation is not counted as
an FP; precision is optimistic by construction. The one FP above is a wrong *first* confirmation.

What this does not show: REAL HARDWARE recall/precision (F4 clips), textured occluders, motion
blur, slow drifts, walk-by or AGC negatives (freeze FPs are covered by `static-scene.md`), and
the detection delay on a laptop whose live probe p95 is 248 ms (`docs/evidence/f1/README.md`).

## Open F3 boxes
Recall/precision per detector is measured in SIMULATION only (above; REAL HARDWARE clips are F4).
The 20 walk-by trials for `fov_shift` and the probe-set p95 ≤ 40 ms/frame at 720p in the live
pipeline are not measured yet. The 20-min static-scene freeze
false-positive box is measured in SIMULATION only (above); REAL HARDWARE is pending.
