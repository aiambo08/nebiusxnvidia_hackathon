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
- On every analysed frame while cells are pending, a pixel is *moving* when it changed by more
  than `pixel_delta` (25 counts, > 4 σ of the noisiest sensor in the benchmarks) since the
  previous analysed frame; a cell is *still* when at most `moving_fraction_max` (1 %) of its
  pixels moved.
- A pending cell adopts its baseline once it has been still for `rest_frames` (10, 2 s at 5 FPS)
  consecutive frames: the per-cell median of those frames' statistics.
- After `max_frames` (150, 30 s) calibration stops; cells never at rest stay unjudged.
- While fewer than `judgeable_min` cells can be judged and some are still pending, the probe
  reports `quality="unknown"`, `unknown_reason="calibrating"` and ratio 0 — not the absolute
  uniform-cell rule, which would call a blank wall occluded.

Thresholds in `configs/default.yaml` → `probes.occlusion_calibration`. ADR-007 thresholds and
`faults.lens_occlusion.occluded_cell_ratio_min` (0.30) are unchanged.

## Evidence (SIMULATION)
| Case | single-frame baseline (ADR-007) | per-cell at rest (this ADR) |
|---|---|---|
| Wall σ 2, person walks during calibration, rest, then a walk-by (`test_occlusion_calibration_does_not_learn_a_person_walking_by`, person at the border / mid-frame) | at rest 0.14–0.28, walk-by max 0.24–0.36 | at rest 0.00, walk-by max 0.11 |
| `bench_static_scene.py`, `docs/evidence/f3/static-scene.md` | `lens_occlusion` confirmed on `wall sigma 2, 5 min of motion then rest` | see the regenerated report |
| `bench_detectors.py`, `docs/evidence/f3/detectors.md` | recall/precision 1.00 | see the regenerated report |

Probe latency at 720p (`scripts/bench_probes.py`, isolated, sandbox): p50 15.5 ms, p95 23.1 ms.

## Consequences
- Occlusion is not measured during the first ≥ 2 s after calibration (`unknown`, `calibrating`).
  A fault already present then is learned as the scene, as before.
- A person or object that stands **still** for ≥ 2 s during calibration is still learned as the
  scene; pixels cannot tell a still person from furniture. The fix only removes what moves.
- Cells that never rest (a robot arm's path, the moving object of `SyntheticSource`) are never
  judged; the ratio is over the cells that can be.
- A pending cell can adopt an occluder that arrives and holds still within the first 30 s;
  `max_frames` bounds that window. After it, the baseline does not learn (ADR-007 principle).
- Recalibration after a legitimate scene change remains the orchestrator's responsibility.
