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
- An open cell adopts the per-cell median of the last `rest_frames` (10, 2 s at 5 FPS)
  statistics once it has been still for that many consecutive frames. A textured adoption
  closes the cell; an untextured one (baseline std < `std_max`) keeps the cell open, because a
  uniform foreground (a wide person in plain clothes moving slowly) is "still" inside and would
  otherwise leave the cell unjudgeable for good.
- After `max_frames` (150, 30 s) calibration ends: cells never at rest (vibration ±1 px every
  frame, a cell that never stops moving) adopt the per-cell median of all calibration frames,
  which still discards a person who was in that cell less than half of the time. Every cell
  has a baseline afterwards; occlusion is never disabled by an unfinished calibration.
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
| Wide uniform person (300 px, 4 px/frame) at calibration, then a 50 % opaque occlusion | first design: wall unjudgeable, 0.00; single frame 0.28 on texture | texture 0.47, wall 0.79 |
| `bench_static_scene.py`, `docs/evidence/f3/static-scene.md` | `lens_occlusion` confirmed on `wall sigma 2, 5 min of motion then rest` | see the regenerated report |
| `bench_detectors.py`, `docs/evidence/f3/detectors.md` | recall/precision 1.00 | see the regenerated report |

Probe latency at 720p (`scripts/bench_probes.py`, isolated, sandbox): p50 15.5 ms, p95 23.1 ms.

## Consequences
- Occlusion is not measured during the first ≥ 2 s after calibration (`unknown`, `calibrating`).
  A fault already present then is learned as the scene, as before.
- A person or object that stands **still** for ≥ 2 s during calibration is still learned as the
  scene; pixels cannot tell a still person from furniture. The fix only removes what moves.
- Cells that never rest (a robot arm's path) get the median of 30 s of motion; whatever was
  there more than half of the time is learned.
- A straight edge moving along itself (the top of a person sliding sideways) looks still and
  can be learned: wide-person case on the wall still reaches 0.36 per frame after it leaves
  (single frame 0.45). A real silhouette is less regular; to be re-checked on hardware.
- An open cell can adopt an occluder that arrives and holds still before the cell closes
  (≤ 30 s). After calibration the baseline does not learn (ADR-007 principle).
- Pre-existing, unchanged: a low-texture wall with luminance noise σ ≈ `std_max` (6) sits on the
  judgeable boundary; both baselines reach 0.43–0.45 per frame at rest.
- Recalibration after a legitimate scene change remains the orchestrator's responsibility.
