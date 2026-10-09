# ADR-005 — Freeze is judged by the frame's own temporal-vs-spatial noise, not by a learned floor

- Status: accepted (supersedes the learned noise floor of ADR-004; ADR-003's causal suppression stands)
- Date: 2026-10-09
- Gate: F3

## Context
ADR-004 decided whether perceptual-hash repeats are a frozen pipeline or a quiet static scene by
comparing the window's temporal MSE with a **noise floor learned from this camera's history**
(10 % quantile of healthy windows). Three revisions of the learning rule (all windows; still
windows by hash; windows under the absolute MSE cap) each failed independent review on a new
counter-example, all of the same shape: whatever the camera saw *before* the scene rested was
not rest, so the floor was learned too high and the resting scene was flagged `freeze`. The last
review (SIMULATION, wall σ = 0.7, resting MSE ≈ 0.011) found false `freeze` with no recovery for
a 5 px or 8 px dark object (119/420 and 118/420 windows), a 20 px object at +15 counts and a
40 px object at +8 counts (120/420 each): their MSE (0.045–0.5) is under the absolute cap yet
far above rest, and the floor never recovers because the baseline stops learning while an
incident is open. A floor learned from history is contaminated by history; the fix cannot be
another learning rule.

## Decision
No history. Each frame pair yields a **noise ratio** (`probes/temporal.py::noise_ratio`):

- *Spatial* noise σ_s: Immerkær's Laplacian estimator (kernel `[[1,-2,1],[-2,4,-2],[1,-2,1]]`,
  scale √(π/2)/6) on the **flattest half of the frame** (Sobel gradient magnitude at or below its
  median), so texture and edges do not count as noise. ADR-004 rejected the unmasked estimator
  because texture dominated it (σ̂ = 50 on a textured scene with true σ = 2); the mask removes
  that failure (see Consequences).
- *Temporal* noise σ_t: RMS of the frame difference on the same flat pixels, divided by √2.
- `noise_ratio = σ_t / σ_s`; NaN (quality `unknown`) when σ_s < `MIN_SPATIAL_SIGMA` (0.05 counts:
  a black or heavily blurred frame carries no measurable noise).

A live sensor draws fresh noise every frame, so σ_t ≈ σ_s (ratio ≈ 1). A frozen pipeline keeps the noise baked into the repeated frame (σ_s
unchanged) but loses the temporal one (ratio ≈ 0; with decoder jitter j the ratio is ≈ j / σ_s).
Motion adds temporal energy, so it can only raise the ratio: no healthy event can make a window
look frozen, and nothing is remembered that could contaminate the next window.

`classify_window` keeps ADR-003's structure. The hash-repeat path of `freeze` now requires the
temporal noise to have collapsed in both senses, `visual.noise_ratio_p50 <=
faults.freeze.noise_ratio_max` (0.3) **and** `visual.temporal_sigma_p50 <=
faults.freeze.temporal_sigma_max` (0.5 counts, i.e. under half a quantisation step: most pixels
do not change at all), instead of a collapse against a learned floor; the config keys `noise_floor_quantile` and `noise_collapse_ratio` and the tracker's
`visual.noise_temporal_mse_p50` sample are removed. Bit-exact repeats and loops are unchanged.
Both estimates run at full resolution (the 160×120 analysis image is quantisation-limited, as
ADR-004 measured); `scripts/bench_probes.py` at 720p: p50 14.4 ms, p95 23.0 ms (gate ≤ 40 ms;
was p95 15.9 ms).

## Threshold
`noise_ratio_max = 0.3` sits between the two populations measured in SIMULATION
(`tests/unit/test_noise_ratio.py`, 640×480, Gaussian sensor noise σ = 0.7–3; scenes: flat wall,
gradient, blurred texture, hard edges; gain 0.3; 5–120 px moving objects at 8–90 counts of
contrast):

| population | ratio |
|---|---|
| live static scene, any σ, any texture, any gain | 0.99–1.01 |
| live + motion: 40 px at +8 / 20 px at +15 / 5 px / 8 px / person-sized | ≥ 1.09 / 1.14 / 1.28 / 1.70 / 8.7 |
| frozen bit-exact | 0.00 |
| frozen + decoder jitter 0.1 (σ 0.7 or 2) | 0.00 |
| frozen + jitter 0.25 on σ 0.7 / σ 2 | 0.27 / 0.11 |
| frozen + jitter 0.5 on σ 2 / σ 0.7 | 0.27 / **0.60 (limit, not detected)** |

Adversarial populations (same harness, not Gaussian white noise):

| population | ratio | σ_t (counts) | verdict |
|---|---|---|---|
| live, spatially correlated noise (ISP blur before quantisation) | 5.3 | ≥ 1 | alive |
| live, Poisson (brightness-dependent) noise | 1.0 | ≥ 1 | alive |
| live, 2 % periodic flicker | 1.7 | ≥ 1 | alive |
| live, pixel-scale static texture (fabric / grain / fixed-pattern σ 6) + sensor σ 1 | **0.17** | 1.0 | alive only thanks to `temporal_sigma_max` |
| live, H.264-like skip blocks copying 50 / 80 / 95 % of still 16×16 blocks | 0.72 / 0.44 / 0.23 | falls with the skip share | **not separable at ≥ 80 %** (see risks) |

The two caps are physical quantities (decoder jitter over sensor noise; half a count), not
per-camera calibrations;
ADR-004's prototype on the bench scenes (gain and 8-bit effects) spread live values over
0.75–1.85, still well above it.

## Consequences
- Motion before rest, alternating motion/rest, small or low-contrast objects, AGC/light-driven
  noise changes (both σ shrink together) no longer produce false `freeze`
  (`tests/unit/test_baseline_fusion.py`, `scripts/bench_static_scene.py` with the reviewer's
  5/8/20+15/40+8 px cases → `docs/evidence/f3/static-scene.md`).
- A frozen stream is caught even on cold start and right after a long motion period (no floor to
  wait for).
- Documented limit: decoder jitter of ≈ 0.7× the sensor noise (jitter 0.5 on σ 0.7) gives a ratio
  of 0.6 and is not distinguishable from a live sensor by any per-frame noise measure (`xfail`
  in `tests/unit/test_noise_ratio.py`); such a stream also no longer repeats its dHash, so the
  hash path would not see it anyway (ADR-004 limit, unchanged).
- Inherent limit, to be measured on REAL HARDWARE: a *live* camera whose still regions carry no
  fresh pixel noise — low-bitrate H.264 skip macroblocks over ≥ 80 % of the frame, or a strong
  temporal denoiser in the ISP — is pixel-identical to a frozen stream (both caps collapse,
  hashes repeat). No per-frame or per-window pixel measure can separate them; transport-level
  evidence (frame counters, RTP timestamps) is the structural answer and belongs to a later
  phase. The 10-min phone RTSP soak confirmed no `freeze` under the ADR-004 rules; the owner's
  webcam and phone must be re-checked under this rule (static scene, `noise_ratio_p50` and
  `temporal_sigma_p50` logged) before the F3 hardware box is ticked.
- Pixel-scale static texture (fabric, grain, fixed-pattern noise) fools the spatial estimator
  (ratio 0.17 live); the absolute `temporal_sigma_max` keeps such a live scene alive as long as
  the sensor noise is above half a count (SIMULATION: σ 1 → σ_t 1.0). A live, strongly denoised
  sensor on fine texture remains a false-positive risk of the same inherent kind.
- Contract change: `VisualMetrics.noise_ratio_p50` and `temporal_sigma_p50` added (Architecture role).
