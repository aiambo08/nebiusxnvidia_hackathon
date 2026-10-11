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
| Hard local shadow (half frame × 0.15) | no confirmation | **confirmed `lens_occlusion`** (reviewer replay) |
| Wall σ 2, calibrated with a person at the frame edge, then 5 min walk-by (`bench_static_scene.py`) | no confirmation | **confirmed `lens_occlusion`** |
| Dark-clothed person standing, 35 % / 50 % width | 0.19–0.22 / 0.34–0.44 | 0.26–0.29 / 0.49–0.56 |

Full chain: `scripts/bench_detectors.py` and `scripts/bench_static_scene.py` regenerated on this
change (`docs/evidence/f3/detectors.md`, `docs/evidence/f3/static-scene.md`).

## Consequences
- A real near-lens occluder is out of focus and therefore smooth; it is detected. A sharp,
  high-frequency occluder (the i.i.d. σ 10 case) keeps Canny edges and is only partially counted
  (0.24–0.38 around the 0.30 threshold). Documented limitation.
- An occluder that arrives together with a global defocus of the rest of the frame is reported
  as defocus (`global_texture_loss`), not occlusion.
- **Known false positive, new vs `main`:** a hard local shadow (part of the frame dimmed to
  ~15 %) is confirmed as `lens_occlusion`. The shadowed cells lose absolute Canny edges, their
  mean moves by many baseline stds and their std collapses, so per-cell mean/std/edge statistics
  cannot separate a deep shadow from a dark occluder. Soft shadows and gain 0.3–2.0 are not
  affected. A structure veto (normalised cross-correlation against the calibration cell) is
  tracked in `docs/agents/TASKS.md`; it must not hide a semi-transparent smudge.
- **Known false positive, new vs `main` (20-min static-scene benchmark):** on a low-texture
  wall only 25 of 64 cells are judgeable, and the ratio is taken over judgeable cells, so each
  cell weighs 2.6× more than in `main` (which divided by all 64). In `wall sigma 2, 5 min of
  motion then rest` the calibration frame holds the edge of the walking person at the left
  border; once the person moves on, those 7 border cells lose their (person) edges and stay
  "occluded" (ratio 0.28 persistently, `main` 0.11), and the person crossing the textured part
  of the wall pushes the windows over 0.30. With a clean calibration frame the same walk-by
  peaks at 0.22 and never confirms. Root cause: a single calibration frame taken while the
  scene is not at rest (the ADR-004 lesson). Dividing by all non-clipped cells removes it but
  gives back the ADR-007 recall (textured hand 0.18–0.29, full-frame occluder 0.75), so it is
  not done here; a calibration taken only on a scene at rest is tracked in `docs/agents/TASKS.md`.
- A dark-clothed person standing still in front of the camera moves closer to the threshold
  (0.26–0.29 at 35 % width); at 50 % width both `main` and this design confirm `lens_occlusion`.
- Overexposure + occlusion is data-dependent: when fewer than `judgeable_min` cells stay
  judgeable the probe returns `unknown` and only `overexposure` is reported (still actionable).
- `quality="unknown"`, `judgeable_cell_ratio` and `global_texture_loss` are not yet carried into
  `VisualMetrics`; an operator cannot tell "no occlusion" from "could not judge" (TASKS item).
- Opaque bands narrower than ~35 % of the width still do not reach 0.30 (grid placement,
  pre-existing).
- Recalibrating with an occluder in the reference gives no phantom occlusion afterwards, and no
  detection of that occluder until the next calibration.
- The calibration frame matters more: cells must carry texture at calibration to be judged.
  Recalibration after a legitimate scene change is the orchestrator's responsibility (unchanged).
- REAL HARDWARE validation (hand in front of the webcam, phone RTSP) is still pending.
