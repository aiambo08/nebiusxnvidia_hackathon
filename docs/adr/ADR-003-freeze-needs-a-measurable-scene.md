# ADR-003 — Freeze is only claimed on a scene that can carry sensor noise

- Status: accepted
- Date: 2026-10-08
- Gate: F3

## Context
`classify_window` (`incidents/fusion.py`) reports `freeze` when frames repeat bit-exactly, or when
perceptual hashes repeat while the pixel MSE is under `faults.freeze.temporal_mse_floor`, or when a
loop is detected. On the owner's REAL HARDWARE clip s001 with SIMULATION faults
(`docs/evidence/f1/README.md`), `dark` and `gaussian_blur` also confirmed `freeze`, ranked first.

Reproduced in SIMULATION (`tests/unit/test_probes.py::test_live_dark_scene_pixels_do_not_classify_as_freeze`):
a smooth indoor scene with a quiet sensor (σ ≈ 0.7 counts, as a laptop webcam at rest) darkened by
95 % yields `repeated_hash_ratio = 1.0` and `temporal_mse ≈ 0.001` **while the camera is live**:
the gain crushes the noise below one quantisation step, so consecutive frames are (nearly)
identical. Strong blur removes the high-frequency detail that makes perceptual hashes differ and
suppresses the noise in the same way. Both faults therefore produce the freeze signature on a
healthy pipeline. The measurements (median over 30 frames, 160×120 analysis image):

| Scene | temporal MSE | hash repeat ratio |
|---|---:|---:|
| wall, live, σ=0.7 | 0.42 | 0.80 |
| wall, live, dark 95 % | 0.0006 | 1.00 |
| wall, frozen | 0.0000 | 1.00 |
| wall, frozen, dark | 0.0000 | 1.00 |

A frozen dark frame and a live dark frame are indistinguishable by content: the information needed
to measure motion is not in the image.

## Decision
1. Freeze is evaluated **after** blackout and focus drift, and only on a scene that can carry noise:
   - under blackout (`dark`), no freeze rule fires — blackout explains the missing motion and is
     the actionable fault (exposure); once exposure is restored the freeze, if real, is measurable;
   - when `focus_drift` fired in the same window, the hash-repeat path is disabled; only bit-exact
     repeats (`exact_repeat_ratio_min`) or a detected loop count as freeze.
2. No threshold in `configs/default.yaml` changes. The rule gains specificity through causal
   suppression (the same mechanism that already stops blackout from being reported as occlusion or
   blur), not through looser numbers.
3. A frozen pipeline that is also black is reported as `blackout` only. This is a documented
   limitation, covered by `test_frozen_dark_pipeline_is_attributed_to_blackout`.

## Consequences
- Ranking: freeze is evaluated after blackout/overexposure/focus drift, so `rank_faults` gives it
  priority among equal scores; otherwise a real freeze co-occurring with overexposure ranked second
  and the rule planner chose the exposure action (independent review of PR #10, 5/10 runs).
- Quantified recall cost (independent review, SIMULATION): when a freeze is **not** bit-exact
  (e.g. an RTSP server re-encoding the last frame) **and** the scene is strongly blurred, freeze
  windows drop from 196/210 to 42/210. Accepted: that case is reported as `focus_drift`, which is
  the measurable fault; a frozen re-encoded stream on a sharp scene is unaffected.
- Dark and blurred live scenes no longer rank `freeze` first, so the planner is not steered towards
  `restart_capture` when the right action is exposure/focus.
- Freeze recall on lit scenes is unchanged (`test_frozen_lit_scene_pixels_classify_as_freeze`,
  `test_each_fault_rule_fires[FREEZE]`, replay manifest `f1-s001-freeze.yaml`).
- Still open for F3 (confirmed by the independent review on `origin/main`, so not caused by this
  change): the absolute `temporal_mse_floor` (0.5) is reached by a healthy, lit, textured static scene
  with σ = 2 webcam noise (MSE 0.413 after the 4×4 area downscale divides the variance by 16; hash
  repeat 1.0) — freeze fired in 358/400 windows and was confirmed in 9/10 healthy clips. Semi-dark
  smooth scenes with σ 0.5–0.7 confirm freeze in every run. The 20-min static-scene false-positive gate
  must be measured with a benchmark before relying on it; a baseline-relative floor is the candidate
  follow-up and will need its own ADR.
