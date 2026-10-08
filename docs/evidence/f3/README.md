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

## Open F3 boxes
Recall/precision per detector (≥ 10 runs per fault), the 20-min static-scene freeze false-positive
run, the 20 walk-by trials for `fov_shift`, and the probe-set p95 ≤ 40 ms/frame at 720p are not
measured yet.
