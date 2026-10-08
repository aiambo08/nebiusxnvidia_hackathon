# ADR-004 — The freeze noise floor is relative to the camera's own healthy noise

- Status: accepted
- Date: 2026-10-08
- Gate: F3

## Context
After ADR-003, `freeze` had three paths: bit-exact repeats, loops, and *perceptual-hash repeats
with temporal MSE under the absolute `faults.freeze.temporal_mse_floor` (0.5)*. The independent
F3 reviewer showed the third path fires on a **healthy static scene**: a lit, textured scene with
ordinary webcam noise (σ = 2 counts) has a temporal MSE of ≈ 0.41 on the 160×120 analysis image
(the 4×4 area downscale divides the noise variance by 16), repeated hash ratio 1.0, and was
flagged `freeze` in 358/400 windows and 9/10 healthy clips (SIMULATION, pre-existing on `main`).
A static scene's temporal MSE *is* its sensor noise; whether 0.41 means "frozen" or "quiet
sensor" cannot be decided by an absolute number.

Alternatives measured (SIMULATION, 640×480, 12 frames per scene):

| Approach | Result |
|---|---|
| Lower/raise the absolute floor | moves the false positive between cameras; forbidden without evidence (rule 5) |
| Spatial noise estimate (Immerkær, median of the Laplacian residual) on the analysis image | quantisation-limited: σ̂ = 0.49 for every scene with σ ≤ 3 — no information |
| Same estimate at full resolution | texture-dominated: σ̂ = 50 on a sharp textured scene (true σ = 2), 0.0 on a blurred one; ratio test unusable |
| **Camera-relative floor**: compare the window's MSE with the quietest healthy MSE this camera has shown (`RobustBaseline.quantile(..., 0.1)`) | separates live (ratio ≈ 1) from frozen bit-exact (0) and frozen with small codec jitter (0.05 at jitter σ = 0.2 counts, 0.19 at 0.3) |

## Decision
- `RobustBaseline.quantile(metric, q)` exposes low quantiles of the learned healthy distribution.
- In `classify_window` the hash-repeat path counts as freeze only when the window's
  `temporal_mse_p50` is both under the absolute cap `temporal_mse_floor` **and** under
  `noise_collapse_ratio` (0.25) × the camera's healthy noise floor, defined as the
  `noise_floor_quantile` (0.1) of `visual.temporal_mse_p50` in the baseline. The evidence list
  then carries `visual.temporal_mse_p50` with that floor as baseline ("sensor noise collapsed").
- Without a learned baseline (cold start, < `baseline.min_samples` healthy windows) only bit-exact
  repeats and loops are freeze evidence. The previous behaviour confirmed a freeze on the first
  three windows of a quiet static camera and then froze the baseline, so it never recovered.
- No existing threshold changes; two new keys are added under `faults.freeze` in
  `configs/default.yaml`.

## Consequences
- A frozen stream whose decoder adds per-frame noise of ≥ ~0.3 counts flips enough dHash bits
  that `repeated_hash_ratio` drops under 0.95 (1.0 at 0.2 counts, 0.75 at 0.5, 0.25 at 1.0 on
  the σ = 2 textured scene), so the hash path loses it even though its MSE stays far under the
  live floor; bit-exact repeats and loops are still caught. In practice repeated P-frames of a
  frozen encoder decode bit-exactly. Measured in `scripts/bench_static_scene.py` (jitter cases).
- A camera that never rests while the baseline is learned (robot in motion) learns a high
  floor; a later genuinely static period with low MSE could be flagged. The 10 % quantile and
  the 300-window baseline make this unlikely for a camera that is sometimes still; a per-mode
  baseline (F5) is the structural fix.
- Cold-start freeze detection is bit-exact only for the first `min_samples` (20) windows.
- Evidence: `tests/unit/test_baseline_fusion.py` (`test_static_scene_hash_repeats_are_not_freeze`,
  `test_hash_repeats_need_a_learned_noise_floor`, `test_quiet_static_camera_never_confirms_freeze_through_the_tracker`,
  `test_baseline_quantile_is_the_quiet_tail`), `scripts/bench_static_scene.py` →
  `docs/evidence/f3/static-scene.md` (20-min healthy static scenes vs frozen variants).
