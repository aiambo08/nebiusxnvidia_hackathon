# ADR-006 — `fov_shift` motion comes from a rigid similarity fit; the homography keeps the inlier gate

- Status: accepted
- Date: 2026-10-09
- Gate: F3

## Context
`GeometryProbe` matched ORB features between the current frame and a reference bank and fitted
one 8-DOF homography with RANSAC; `fov_shift` fired when the homography's inlier share was
≥ `inlier_ratio_min` (0.35) and its translation ≥ 25 px or rotation ≥ 3°. The 20-min
static-scene benchmark (SIMULATION, `docs/evidence/f3/static-scene.md`) found false `fov_shift`
on every smooth `wall` scene at rest and on every walk-by case: `equalizeHist` amplifies sensor
noise into ~210 spurious keypoints, and a homography fitted through them still finds ≈ 60 %
"inliers" while its 8 parameters bend to the noise — translation p95 27–48 px, max 94 px,
rotation up to 3° on a camera that did not move (σ 0.7–4). Textured scenes: 0 windows.

Replacing the homography by a 4-DOF similarity (`cv2.estimateAffinePartial2D`) removes the false
positives (same scenes: p95 2.4–4.6 px, rotation ≤ 1°; walk-by 0 windows) and keeps 25–40 px
shifts, 4–5° rotations and 0.2–1 px/frame pans detectable. But the independent review showed it
also drops real, large camera turns on a textured scene: a physical yaw/tilt of 10–15°
(H = K·R·K⁻¹, 60° HFOV) is a perspective change a rigid model fits poorly, so the similarity's
inlier share falls to 0.20–0.34 and the rule never looks at the ~100–160 px translation
(`main` confirmed 2/2 at 10° and 15°, the rigid-only probe 1/2 and 0/2). The 0.35 gate was
calibrated on homography inliers; reusing it on a different model would silently change its
meaning (rule 5).

## Decision
Two fits over the same cross-checked matches, each used for what it is good at:

1. `homography_inlier_ratio` stays the inlier share of the 8-DOF homography — the measurement
   quality gate the rule was calibrated on; its meaning and threshold are unchanged.
2. `translation_px` and `rotation_deg` come from the 4-DOF similarity, which cannot bend to
   noise keypoints. If the rigid fit fails, the homography's own estimate is used.

No threshold, contract field or rule in `classify_window` changes.

## Consequences
- SIMULATION: smooth walls at rest (σ 0.7–4) and the walk-by / small-object cases produce 0
  `fov_shift` windows; 25–40 px shifts, 4–5° rotations, slow pans and 10–15° physical
  yaw/tilt stay confirmed (`tests/unit/test_probes.py::test_geometry_*`).
- A pure keystone/perspective change with no translation, and an in-plane rotation of exactly
  3° on a smooth wall (the similarity underestimates it by ~10 %), are no longer confirmed;
  the former was only confirmed through the homography's noise fit and neither is a camera
  move at the scale the gate targets.
- `translation_px` is the displacement of the image origin, so an in-plane rotation about the
  centre also contributes to it (pre-existing; documented).
- Probe cost is unchanged (`bench_probes.py` 720p p95 ≈ 21–23 ms on an idle machine); the
  extra rigid fit costs ≈ 0.08 ms per measured frame.
- Still open for the gate: the 20 real person-walk-by trials (REAL HARDWARE).
