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

## Freeze noise floor relative to the camera (ADR-004) — SIMULATION
Independent review of PR #10 found that a healthy, lit, static textured scene with σ=2 webcam noise
tripped `freeze` in 358/400 windows on `main`: after the 4×4 downscale its temporal MSE (≈ 0.41) sits
under the absolute `temporal_mse_floor` (0.5) while dHash repeats. The hash-repeat path now needs the
window's MSE to collapse to ≤ 0.25× the camera's own healthy noise floor (10 % quantile of the
temporal MSE of healthy *still* windows, `visual.still_temporal_mse_p50`); without such windows
(cold start, or a baseline learned while people move through the scene) only bit-exact repeats and
loops count. A
bit-exact period on frames that differ only by noise (a replayed buffer) is now a loop.

`python scripts/bench_static_scene.py` (20 min per healthy scene, 3 min per frozen scene, full local
path through `benchmarks.replay.replay`) → `static-scene.md`:
- 10 healthy scenes × 20 min (smooth wall σ 0.7/2, textured σ 1/2/3, dim gain 0.3, slow 15 %
  light drift, and the reviewer's cases: 30 s walk-by then rest, 5 min of motion then rest,
  alternating 30 s motion / 30 s rest): **0 freeze windows, 0 freeze confirmations** in 12 000
  windows. Only the wall and dim scenes exercise the fix (the textured scenes never repeat a hash
  and pass on `main` too).
- Frozen bit-exact (textured and wall), frozen + decoder jitter 0.1, loop of 4 frames: `freeze`
  confirmed 2–4 s after the fault.
- Documented limit: decoder jitter ≥ ~0.3 counts on a frozen stream flips dHash bits, so the hash
  path loses it (0.2 → 22/180 freeze windows, still confirmed; 0.5 → not detected). Bit-exact repeats
  and loops are unaffected; repeated P-frames of a frozen encoder decode bit-exactly in practice.
- Residual risk (ADR-004): the floor is learned at one gain/light; if AGC lowers the noise while the
  scene is still, the relative rule can fire (reviewer: σ 2 → 1 gives 180/360 windows). F5 per-mode
  baselines are the structural fix.
- Finding, not caused by this PR: the smooth-wall scenes confirm `fov_shift` (noise-driven ORB
  keypoints after `equalizeHist`), tracked as the next F3 item in `docs/agents/TASKS.md`.

The 20-min box remains open on REAL HARDWARE (owner's webcam at rest).

## Open F3 boxes
Recall/precision per detector (≥ 10 runs per fault), the 20-min static-scene freeze false-positive
run, the 20 walk-by trials for `fov_shift`, and the probe-set p95 ≤ 40 ms/frame at 720p are not
measured yet.
