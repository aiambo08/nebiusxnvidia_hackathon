# ADR-008 — Occlusion calibration is taken per cell, at rest

- Status: accepted
- Date: 2026-10-11
- Gate: F3

## Context
ADR-007 judges each occlusion cell against the same cell at calibration, and
`ProbeRunner.calibrate_reference` took that baseline from a single frame — the first frame the
pipeline sees (`runtime.py`, `benchmarks/replay.py`, the spikes). The static-scene benchmark and
its independent review (SIMULATION, `docs/evidence/f3/static-scene.md`, ADR-007 Consequences)
showed that whatever moves through that frame is learned as the scene: on a low-texture wall a
person in view at calibration (at the border or mid-frame, σ 0.7 or 2) leaves their cells
"occluded" (ratio 0.28 at rest) once they leave, and a later walk-by confirms `lens_occlusion`.
`main` before ADR-007 did not. Dividing by all cells instead of judgeable cells removes it but
gives back ADR-007's detection gain (hand over the full frame 0.75 instead of ≥ 0.90).

## Decision
The geometry reference is still the first frame (ADR-006, unchanged). The occlusion baseline is
built **per cell, from frames in which that cell is at rest**:

- `calibrate_reference` resets the baseline to NaN for every cell; NaN cells are never judged
  (`occlusion_probe`).
- On every new analysed frame (a `Frame.seq` is counted once; the first frame reaches both
  `calibrate_reference` and `analyse`) the frame is brightness-normalised and differenced with
  the previous one. A pixel is *moving* when it changed by more than
  `max(pixel_delta, noise_k × 1.4826 × median|Δ|)` — 25 counts, raised on noisy sensors to 4×
  the frame's robust σ of the change; a cell is *still* when at most `moving_fraction_max`
  (1 %) of its pixels moved. Normalising first makes global flicker/AGC steps not motion.
- A cell adopts the per-cell median of the last `rest_frames` (10, 2 s at 5 FPS) statistics
  the first time it has been still for that many consecutive frames. A textured adoption is
  final. An untextured one (baseline std < `std_max`, not judgeable) is provisional: the cell
  keeps recording every frame in which it is at rest, and at `max_frames` its baseline becomes
  the median over all of them. A foreground that rested there briefly — a wide person in plain
  clothes moving slowly (uniform inside, so "still"), or a textured person standing 4 s on a
  plain wall — is outvoted by the scene instead of being learned (the latest-rest rule of the
  second draft learned it, see Evidence).
- At `max_frames` (150, 30 s) calibration ends. Cells never at rest stay NaN and are not
  judged — local motion (someone fidgeting in one corner for the whole 30 s) is not learned.
  Only when calibration failed globally — more than `global_fallback_min` (50 %) of the cells
  never rested, or without them fewer than `judgeable_min` cells could be judged (vibration
  ±1 px moves exactly the textured cells; luminance noise or flicker every frame) — do the
  never-rested cells adopt the per-cell median of all calibration frames, so occlusion is never
  left disabled by calibration.
- While calibration is open and fewer than `judgeable_min` cells can be judged, the probe
  reports `quality="unknown"`, `unknown_reason="calibrating"` and ratio 0 (afterwards
  `too_few_judgeable_cells`) — not the absolute uniform-cell rule, which would call a blank wall
  occluded.

Thresholds in `configs/default.yaml` → `probes.occlusion_calibration`. ADR-007 thresholds and
`faults.lens_occlusion.occluded_cell_ratio_min` (0.30) are unchanged.

## Evidence (SIMULATION)
| Case | single-frame baseline (ADR-007) | per-cell at rest (this ADR) |
|---|---|---|
| Wall σ 2, person walks during calibration, rest, then a walk-by (`test_occlusion_calibration_does_not_learn_a_person_walking_by`, person at the border / mid-frame) | at rest 0.14–0.28, walk-by max 0.24–0.36 | at rest 0.00, walk-by max 0.11 |
| Independent review, DO_NOT_MERGE on the first design (fixed, `test_calibration_completes_and_occlusion_is_still_detected`): luminance noise σ 7–10, ±1 px vibration, ±10 % flicker every frame | first design: 0.00–0.17 of the cells calibrated, a 50 % opaque occlusion → ratio 0.00 (single frame 0.50–0.57) | all cells calibrated, 0.47–0.67 (= single frame) |
| Wide uniform person (300 px, 4 px/frame) at calibration, then a 50 % opaque occlusion | first design: wall unjudgeable, 0.00; single frame 0.28 on texture | texture 0.47, wall 0.77 |
| Second review, DO_NOT_MERGE on the second draft (median fallback for every unrested cell, open cells adopt the latest rest): `bench_static_scene` wall, dark person drifting 0.53 px/frame through column 0 for > 50 % of calibration (`test_a_person_resting_or_drifting_at_calibration_is_not_learned[slow]`) | second draft: learned by the fallback, at rest 0.28, `lens_occlusion` confirmed at 181.8 s; single frame 0.28 | at rest ≤ 0.05; the 6 cells never at rest stay unjudged |
| Textured person standing still 4 s on a plain wall during calibration, then leaving (`[textured]`) | second draft: at rest 0.57, confirmed at 19.8 s; single frame 0.00 | 0.00 |
| Wall, ±1 px vibration every frame (textured cells never rest, 19 %) | without the judgeable clause: textured cells NaN, occlusion 0.00 | fallback, 0.67 (= single frame) |
| `bench_static_scene.py`, `docs/evidence/f3/static-scene.md` | `lens_occlusion` confirmed on `wall sigma 2, 5 min of motion then rest` | see the regenerated report |
| `bench_detectors.py`, `docs/evidence/f3/detectors.md` | recall/precision 1.00 | see the regenerated report |

Probe latency at 720p (`scripts/bench_probes.py`, isolated, sandbox): p50 15.5 ms, p95 23.1 ms.

## Consequences
- Occlusion is not measured during the first ≥ 2 s after calibration (`unknown`, `calibrating`).
  A fault already present then is learned as the scene, as before.
- A person or object that stands **still** for ≥ 2 s during calibration is still learned as the
  scene; pixels cannot tell a still person from furniture. The fix only removes what moves.
- Cells that never rest locally (a robot arm's path) are never judged. On a camera where
  calibration fails globally they get the median of 30 s; whatever was there more than half of
  the time is learned.
- A straight edge moving along itself (the top of a person sliding sideways) looks still and
  can be learned: wide-person case on the wall still reaches 0.31 per frame after it leaves
  (single frame 0.45). A real silhouette is less regular; to be re-checked on hardware.
- A textured foreground that holds still for 2 s on a cell before the scene does is adopted and
  final (a person standing still at start-up). An untextured cell's final baseline learns a
  foreground at rest there for more of the 30 s than the scene. After calibration the baseline
  does not learn (ADR-007 principle).
- A person in the middle of the picture at calibration leaves a small residue on the wall:
  0.14 at rest, max 0.24 during walk-bys (first design 0.00); below 0.30 but less margin.
- With ±20 % flicker every frame some textured cells never rest while the global clause does
  not trigger (0.94 of the cells calibrated); occlusion still reads 0.51 (single frame 0.55).
- Pre-existing, unchanged: a low-texture wall with luminance noise σ ≈ `std_max` (6) sits on the
  judgeable boundary; both baselines reach 0.43–0.45 per frame at rest.
- Recalibration after a legitimate scene change remains the orchestrator's responsibility.
