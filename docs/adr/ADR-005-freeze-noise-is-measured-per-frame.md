# ADR-005 — Freeze noise is measured per frame as telemetry; only bit-exact repeats and loops are freeze evidence

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
No history, and no pixel-noise trigger either.

1. **Measure, per frame pair, the camera's own noise** (`probes/temporal.py::noise_sigmas`),
   exported as `visual.noise_ratio_p50` and `visual.temporal_sigma_p50` (window medians):
   - *Spatial* noise σ_s: Immerkær's Laplacian estimator (kernel `[[1,-2,1],[-2,4,-2],[1,-2,1]]`,
     scale √(π/2)/6) on the **flattest half of the frame** (Sobel gradient magnitude at or below
     its median), so texture and edges do not count as noise. ADR-004 rejected the unmasked
     estimator because texture dominated it (σ̂ = 50 on a textured scene with true σ = 2); the
     mask removes that failure.
   - *Temporal* noise σ_t: RMS of the frame difference on the same flat pixels, divided by √2.
   - `noise_ratio = σ_t / σ_s`; NaN (quality `unknown`) when σ_s < `MIN_SPATIAL_SIGMA` (0.05
     counts: a black or heavily blurred frame carries no measurable noise).
   Both run at full resolution (the 160×120 analysis image is quantisation-limited, as ADR-004
   measured); `scripts/bench_probes.py` at 720p: p50 13.3 ms, p95 23.4 ms (gate ≤ 40 ms; was
   p95 15.9 ms before ADR-005).
2. **Perceptual-hash repeats are not freeze evidence**, with or without a noise collapse.
   `classify_window` keeps ADR-003's structure (freeze judged last, suppressed under blackout)
   and claims `freeze` only on `visual.exact_repeat_ratio ≥ faults.freeze.exact_repeat_ratio_min`
   (0.9, unchanged) or a detected loop (`visual.loop_period > 0`). The noise figures and the loop
   period are attached to the incident as `Evidence` for diagnosis. The config keys
   `repeated_hash_ratio_min`, `temporal_mse_floor` (ADR-003), `noise_floor_quantile` and
   `noise_collapse_ratio` (ADR-004) are removed: nothing reads them any more.

### Why the noise collapse was rejected as a trigger
The first draft of this ADR made hash repeats a `freeze` when the ratio collapsed (≤ 0.3) and,
after a fine-texture counter-example, when the temporal sigma was also under half a count
(≤ 0.5). On a raw sensor that separates the populations cleanly (table below). It fails on the
demo path. Independent review (4th pass) and our reproduction with ffmpeg/libx264 (SIMULATION,
`tests/unit/test_noise_ratio.py::test_live_static_scene_over_h264_is_pixel_identical_to_a_frozen_one`,
640×480, 30 fps, `-preset veryfast`):

| live static scene through libx264 | hash repeat | exact repeat | ratio p50 | σ_t p50 (counts) |
|---|---:|---:|---:|---:|
| textured, sensor σ 2, CRF 18 | 1.00 | — | 0.12 | 0.14 |
| textured, sensor σ 2, CRF 23 | 1.00 | 0.01 | 0.04 | 0.03 |
| textured, sensor σ 2, CRF 28 | 1.00 | 0.62 | 0.00 | 0.00 |
| textured, sensor σ 1, CRF 28 | 1.00 | — | 0.00 | 0.00 |
| smooth wall, σ 0.7 or 2, CRF 23 or 28 | 1.00 | **1.00** | NaN | 0.00 |

The encoder's skip macroblocks reproduce the previous frame exactly wherever nothing but noise
changed: a live static scene decodes with no fresh temporal noise, so any pixel measure of
"the noise collapsed" is also true of a healthy compressed camera. The reviewer measured 73/240
false `freeze` windows (confirmed at window 34) on the textured CRF 28 clip under the draft rule,
0/240 on `main`. An ISP temporal denoiser (α = 0.9) or a quiet sensor on fine texture
(σ_t 0.3–0.5) gave the same result on a raw path (27–240 of 240 windows). There is no cap value
that keeps these alive and still catches a frozen frame with decoder jitter: the populations
overlap exactly.

## Threshold
Only `exact_repeat_ratio_min` (0.9) remains, unchanged since ADR-003. The measured populations
(`tests/unit/test_noise_ratio.py`, 640×480, Gaussian sensor noise σ = 0.7–3; scenes: flat wall,
gradient, blurred texture, hard edges; gain 0.3; 5–120 px moving objects at 8–90 counts of
contrast) are kept as the reference for the REAL HARDWARE read-out of the two telemetry fields:

| population | ratio | σ_t (counts) |
|---|---|---|
| live raw static scene, σ ≥ 0.7, any texture, any gain | 0.99–1.01 | = sensor σ |
| live raw smooth wall, σ ≤ 0.4 | ≈ 1 at full resolution, but bit-exact on the 160×120 analysis image (see Consequences) | = sensor σ |
| live + motion: 40 px at +8 / 20 px at +15 / 5 px / 8 px / person-sized | ≥ 1.09 / 1.14 / 1.28 / 1.70 / 8.7 | ≥ sensor σ |
| live, spatially correlated noise / Poisson / 2 % flicker | 5.3 / 1.0 / 1.7 | ≥ 1 |
| live, pixel-scale static grain σ 6 + sensor σ 1 | 0.17 | 1.0 |
| live, H.264 (libx264 CRF 23–28) static scene | 0.00–0.04 | 0.00–0.03 |
| frozen bit-exact | 0.00 | 0.00 |
| frozen + decoder jitter 0.1 / 0.25 / 0.5 | 0.00 / 0.11–0.27 / 0.27–0.60 | = jitter |

## Consequences
- No learned history: motion before rest, alternating motion/rest, small or low-contrast objects
  and AGC/light-driven noise changes cannot produce `freeze`; the four counter-examples of the
  ADR-004 review and the H.264 / fine-texture / denoiser cases of this review no longer fire
  through the hash path (the pre-existing bit-exact cases below are unchanged from `main`)
  (`tests/unit/test_baseline_fusion.py`, `scripts/bench_static_scene.py` →
  `docs/evidence/f3/static-scene.md`).
- Recall unchanged from ADR-003 for the realistic frozen pipelines (stuck sensor, stuck frame
  buffer, encoder repeating a frame — a frozen frame behind libx264 CRF 28 decodes bit-exact and
  is confirmed): these are bit-exact. **Documented miss:** a frozen frame re-emitted with
  per-frame decoder noise is neither bit-exact nor, since this ADR, claimable through hash
  repeats. While exact repeats were judged on the 160×120 analysis image, jitter 0.1 still
  averaged away and was confirmed, with the miss starting at ≥ 0.15 on texture and ≥ 0.2 on a
  wall (independent review; `main` caught 0.15–0.2 on texture through the hash path). Since
  exact repeats are judged on the probe input frame (`downscale(max_side=640)` in `runner.py`: native pixels at 640×480, 2× INTER_AREA at 720p/1080p) (follow-up PR), any decoder jitter
  breaks equality (jitter 0.1: windows with `exact_repeat_ratio` ≥ 0.9 fall from 1.00 to
  0.08 at 640×480 and 0.04–0.33 at 720p in the reviewer's harness; in
  `docs/evidence/f3/static-scene.md` the "frozen + jitter 0.1" cases went from confirmed in 4 s
  with 111–116/180 windows to 13/180 unconfirmed on the wall and 17/180 confirmed only after
  60 s on texture), so detection is not reliable at any non-zero jitter. `scripts/bench_static_scene.py` reports those
  cases as INFO. Catching it needs transport evidence, not pixels.
- **Pre-existing risk, now measured (REAL HARDWARE to decide):** a live *smooth* scene over
  H.264 decodes bit-exact (table above), so the bit-exact rule itself can fire on a healthy
  compressed camera pointed at a plain wall. The owner's 10-min phone RTSP soak (textured room)
  showed no `freeze`; the 20-min static-scene box on REAL HARDWARE must include the phone on a
  plain wall, with `exact_repeat_ratio`, `noise_ratio_p50` and `temporal_sigma_p50` logged.
  The structural answer for compressed sources is transport-level freeze evidence (RTP
  timestamps / decoder frame counters), recorded in `docs/agents/TASKS.md` for a later phase.
- **Pre-existing bit-exact false positives (independent review, 5th pass, SIMULATION) — the
  raw-sensor ones fixed in the follow-up PR:** `exact_repeat_ratio` used to be computed on the
  160×120 INTER_AREA analysis image, where 16 raw pixels average into one, so a live smooth
  wall with sensor σ ≤ 0.4 rounded to the same image every frame (σ 0.3: 120/120 windows; σ 0.4:
  22/120), as did a raw σ 0.7 sensor behind an 8-bit temporal denoiser α ≥ 0.8 (129–240/240).
  Since the follow-up, `FreezeTracker` judges bit-exact repeats, and the bit-exact *period* of a
  loop, on the probe input frame (`downscale(max_side=640)` in `runner.py`: native pixels at 640×480, 2× INTER_AREA at 720p/1080p) instead of the 160×120 image, so sensor noise is averaged 1× or 4× instead of 16× before the
  equality test; those cases now give `exact_repeat_ratio` 0 (`tests/unit/test_probes.py`).
  Residual, measured by the reviewer: a live wall at 720p with σ 0.1, or at 1080p with σ ≤ 0.2,
  is still bit-exact after the 2× downscale; and a live σ 0.7 wall over MJPEG at quality ≤ 50 is
  bit-exact at 480 and 720p (identical on `main`) — both belong to the real-hardware re-check. The
  MSE-floor loop branch stays on the 160×120 image with `loop_mse_max` 0.5 (now
  `probes.loop_mse_max` in config, same value and same meaning), so loops with real motion
  between frames are detected exactly as on `main` (replayed blob, jitter 0.1–0.6, 480 and 720p;
  `test_replayed_moving_buffer_with_decoder_jitter_is_still_a_loop`).
  Trade-offs accepted and measured: (a) decoder jitter on a *static* repeated picture is now a
  miss, through one mechanism: a frozen frame with jitter ≥ 0.1 (see above), and a replayed
  buffer of a static scene with jitter ≥ 0.1 — on `main` its bit-exact period survived the
  160×120 averaging; now it is judged on the input frame where the jitter breaks it, and the MSE
  branch cannot take over because the step between its frames is noise only (~0.2 at σ 0.7 on
  160×120, under 0.5). Reviewer's harness, fraction of windows with `loop_period` > 0, jitter 0.1:

  | case (p2 / p4 / p8) | `main` | this PR |
  |---|---|---|
  | 480, wall σ 0.7 | 1.0 / 1.0 / 0.94 | 0.50 / 0.25 / 0.42 |
  | 720p, wall σ 0.7 | 1.0 / 1.0 / 0.94 | 0.50 / 0.52 / 0.08 |
  | 720p, wall σ 2 | 0.92 / 1.0 / 0.94 | 0.58 / 0.42 / 0.00 |
  | 720p, texture | 0.83 / 0.83 / 0.94 | 0.69 / 0.23 / 0.08 |

  (480 with wall σ 2 is the one case that still holds, which is what
  `test_replayed_buffer_is_a_loop_with_or_without_decoder_jitter` covers.) Accepted because the
  same jitter makes the identical live/frozen pictures of the H.264 case below indistinguishable
  anyway; transport evidence is the real fix for both. (b) A periodic multi-level flicker on a
  live sensor still trips the MSE-floor loop branch (pre-existing on `main`, ±4 counts period 4
  at σ 0.7: 300/420 windows; `tests/unit/test_probes.py::
  test_periodic_flicker_on_a_live_sensor_is_a_loop_only_through_the_mse_floor`),
  open in `docs/agents/TASKS.md`. What no pixel rule can reach is the compressed case above:
  libx264 decodes a live smooth wall bit-exact at full resolution at every CRF tried (23/28/35),
  and a textured scene from CRF 28 up — the encoder itself repeats the pixels, so only transport
  evidence can tell it from a freeze.
- Contract change: `VisualMetrics.noise_ratio_p50` and `temporal_sigma_p50` added (Architecture
  role); they are telemetry and incident evidence, and feed no rule.
