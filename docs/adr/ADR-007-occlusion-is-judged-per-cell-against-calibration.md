# ADR-007 — Occlusion is judged per cell against the calibration cells

- Status: accepted
- Date: 2026-10-11
- Gate: F3

## Context
`occlusion_probe` counted a cell as occluded only when it was uniform and edge-less in absolute
terms (std < 6, edge density < 0.01 on the brightness-normalised frame). The F3 detector
benchmark and its independent review (SIMULATION, `docs/evidence/f3/detectors.md`) showed three
gaps:

1. A textured occluder (hand-like, not uniform) over 40–60 % of the width gave
   `occluded_cell_ratio` 0.05 and was never detected.
2. Extreme global defocus made 23–31 % of cells uniform; at ≥ 0.30 it was confirmed as
   `lens_occlusion` and masked `focus_drift`.
3. A saturated window suppressed occlusion as a whole (PR #20), so an occlusion that co-occurs
   with overexposure was invisible until exposure was restored.

## Decision
`occlusion_probe(gray, grid, baseline_cells, ...)` receives the raw probe frame and compares each
cell with the same cell at calibration (`ProbeRunner.calibrate_reference`):

- **Judgeable cells**: textured at calibration (baseline std ≥ `std_max`) and not clipped white
  in the current raw frame (> 50 % of pixels ≥ `white_level`). The ratio is
  occluded / judgeable. Fewer than `judgeable_min` judgeable cells → `quality="unknown"`,
  `unknown_reason="too_few_judgeable_cells"`, ratio 0 (a blank wall or a clipped frame is not
  evidence of occlusion; ADR-003 principle).
- **Occluded cell**: uniform (as before) or *changed* — edge density below
  `edge_loss_ratio_max` × its baseline and either its mean moved ≥ `mean_shift_min` baseline
  stds or its std collapsed below `1 - texture_drop` × baseline.
- **Global defocus guard**: when ≥ `global_loss_ratio_min` of judgeable cells lost their edges
  while the median cell kept its contrast (std ratio ≥ `1 - texture_drop`) and its brightness
  (median mean shift < `mean_shift_min`), the frame is defocused, not occluded: ratio 0 and
  `global_texture_loss` 1. Defocus keeps cell means; an occluder moves them or flattens them.
- `fusion.classify_window` no longer suppresses `lens_occlusion` on a saturated window: the
  probe already excludes clipped cells. `focus_drift` stays suppressed when saturated.

New thresholds in `configs/default.yaml` → `probes.occlusion` (`std_max` and `edge_max` are the
previous hard-coded values). `faults.lens_occlusion.occluded_cell_ratio_min` (0.30) is unchanged.
`global_loss_ratio_min` is 0.75, not 0.9: a horizontal motion blur keeps edges in ~17 % of cells
and its uniform cells reached 0.32 of the judgeable cells.

## Evidence (SIMULATION, `SyntheticSource` σ 1/2/3, seeds 1–3)
| Case | `main` | ADR-007 |
|---|---|---|
| Healthy, lighting change, dark-but-alive | 0.00 | 0.00 |
| Smooth hand-like occluder, 40 % width | 0.31 | 0.40–0.42 |
| Smooth hand-like occluder, full frame | — | 1.00 |
| i.i.d. textured occluder (mean 90, σ 10), 40–60 % width | 0.05 | 0.24–0.38 |
| Opaque, half frame | 0.56 | 0.81–0.84 |
| `occlude_semi` 1.0 | 0.38 | 0.45–0.52 |
| `gaussian_blur` 0.4 / 0.7 / 1.0 | 0.21–0.30 | 0.00 (`global_texture_loss` 1) |
| `motion_blur_h` 1.0 | 0.14–0.27 | 0.00 |
| `overexpose` 1.0 (white 0.96) | 0.69 | 0.00 (`unknown`) |
| `overexpose` 0.5 + opaque | 0.56 | 0.83–0.86 |

Full chain: `scripts/bench_detectors.py` and `scripts/bench_static_scene.py` regenerated on this
change (`docs/evidence/f3/detectors.md`, `docs/evidence/f3/static-scene.md`).

## Consequences
- A real near-lens occluder is out of focus and therefore smooth; it is detected. A sharp,
  high-frequency occluder (the i.i.d. σ 10 case) keeps Canny edges and is only partially counted
  (0.24–0.38 around the 0.30 threshold). Documented limitation.
- An occluder that arrives together with a global defocus of the rest of the frame is reported
  as defocus (`global_texture_loss`), not occlusion.
- The calibration frame matters more: cells must carry texture at calibration to be judged.
  Recalibration after a legitimate scene change is the orchestrator's responsibility (unchanged).
- REAL HARDWARE validation (hand in front of the webcam, phone RTSP) is still pending.
