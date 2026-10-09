# Detector recall / precision (Gate F3) — SIMULATION

`SyntheticSource` 640x480 textured scene with ArUco marker, sensor noise sigma 1, 2, 3, 5 analytic FPS, 30 s healthy lead-in then 30 s of one injected fault (`benchmarks.injectors.faults`), full local path (`benchmarks.replay.replay`). 4 seeds per (fault, strength, sigma). Negative controls: clean scene and legitimate lighting change. TP = expected detector confirmed after onset; FP = any detector confirmed where not expected (negatives, other faults, or before onset). Gate: recall >= 0.9 for blackout, freeze, strong blur (focus_drift) and strong occlusion (lens_occlusion); precision >= 0.85 per detector.

| detector | expected runs | TP | FN | FP | recall | precision | delay p50 s | gate |
|---|---|---|---|---|---|---|---|---|
| blackout | 24 | 24 | 0 | 0 | 1.00 | 1.00 | 2.80 | PASS |
| focus_drift | 24 | 23 | 1 | 0 | 0.96 | 1.00 | 2.80 | PASS |
| freeze | 36 | 36 | 0 | 0 | 1.00 | 1.00 | 4.80 | PASS |
| lens_occlusion | 24 | 24 | 0 | 1 | 1.00 | 0.96 | 2.80 | PASS |
| overexposure | 24 | 24 | 0 | 0 | 1.00 | 1.00 | 2.80 | PASS (not gated) |

## Runs

| injector | strength | sigma | seed | confirmed | delay s | false positives | result |
|---|---|---|---|---|---|---|---|
| dark | 0.9 | 1 | 0 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 1 | 1 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 1 | 2 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 1 | 3 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 2 | 0 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 2 | 1 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 2 | 2 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 2 | 3 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 3 | 0 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 3 | 1 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 3 | 2 | blackout | 2.8 | - | PASS |
| dark | 0.9 | 3 | 3 | blackout | 2.8 | - | PASS |
| dark | 1 | 1 | 0 | blackout | 2.8 | - | PASS |
| dark | 1 | 1 | 1 | blackout | 2.8 | - | PASS |
| dark | 1 | 1 | 2 | blackout | 2.8 | - | PASS |
| dark | 1 | 1 | 3 | blackout | 2.8 | - | PASS |
| dark | 1 | 2 | 0 | blackout | 2.8 | - | PASS |
| dark | 1 | 2 | 1 | blackout | 2.8 | - | PASS |
| dark | 1 | 2 | 2 | blackout | 2.8 | - | PASS |
| dark | 1 | 2 | 3 | blackout | 2.8 | - | PASS |
| dark | 1 | 3 | 0 | blackout | 2.8 | - | PASS |
| dark | 1 | 3 | 1 | blackout | 2.8 | - | PASS |
| dark | 1 | 3 | 2 | blackout | 2.8 | - | PASS |
| dark | 1 | 3 | 3 | blackout | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 1 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 1 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 1 | 2 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 1 | 3 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 2 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 2 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 2 | 2 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 2 | 3 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 3 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 3 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 3 | 2 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 0.7 | 3 | 3 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 1 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 1 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 1 | 2 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 1 | 3 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 2 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 2 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 2 | 2 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 2 | 3 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 3 | 0 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 3 | 1 | focus_drift | 2.8 | - | PASS |
| gaussian_blur | 1 | 3 | 2 | lens_occlusion | 2.8 | lens_occlusion | FAIL |
| gaussian_blur | 1 | 3 | 3 | focus_drift | 2.8 | - | PASS |
| freeze | 1 | 1 | 0 | freeze | 4.8 | - | PASS |
| freeze | 1 | 1 | 1 | freeze | 4.8 | - | PASS |
| freeze | 1 | 1 | 2 | freeze | 4.8 | - | PASS |
| freeze | 1 | 1 | 3 | freeze | 4.8 | - | PASS |
| freeze | 1 | 2 | 0 | freeze | 4.8 | - | PASS |
| freeze | 1 | 2 | 1 | freeze | 4.8 | - | PASS |
| freeze | 1 | 2 | 2 | freeze | 4.8 | - | PASS |
| freeze | 1 | 2 | 3 | freeze | 4.8 | - | PASS |
| freeze | 1 | 3 | 0 | freeze | 4.8 | - | PASS |
| freeze | 1 | 3 | 1 | freeze | 4.8 | - | PASS |
| freeze | 1 | 3 | 2 | freeze | 4.8 | - | PASS |
| freeze | 1 | 3 | 3 | freeze | 4.8 | - | PASS |
| loop4 | 1 | 1 | 0 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 1 | 1 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 1 | 2 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 1 | 3 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 2 | 0 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 2 | 1 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 2 | 2 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 2 | 3 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 3 | 0 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 3 | 1 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 3 | 2 | freeze | 3.8 | - | PASS |
| loop4 | 1 | 3 | 3 | freeze | 3.8 | - | PASS |
| loop8 | 1 | 1 | 0 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 1 | 1 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 1 | 2 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 1 | 3 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 2 | 0 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 2 | 1 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 2 | 2 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 2 | 3 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 3 | 0 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 3 | 1 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 3 | 2 | freeze | 5.8 | - | PASS |
| loop8 | 1 | 3 | 3 | freeze | 5.8 | - | PASS |
| occlude_opaque | 0.7 | 1 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 1 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 1 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 1 | 3 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 2 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 2 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 2 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 2 | 3 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 3 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 3 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 3 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 0.7 | 3 | 3 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 1 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 1 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 1 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 1 | 3 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 2 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 2 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 2 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 2 | 3 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 3 | 0 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 3 | 1 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 3 | 2 | lens_occlusion | 2.8 | - | PASS |
| occlude_opaque | 1 | 3 | 3 | lens_occlusion | 2.8 | - | PASS |
| overexpose | 0.8 | 1 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 1 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 1 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 1 | 3 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 2 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 2 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 2 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 2 | 3 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 3 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 3 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 3 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 0.8 | 3 | 3 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 1 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 1 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 1 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 1 | 3 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 2 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 2 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 2 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 2 | 3 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 3 | 0 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 3 | 1 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 3 | 2 | overexposure | 2.8 | - | PASS |
| overexpose | 1 | 3 | 3 | overexposure | 2.8 | - | PASS |
| none | 0 | 1 | 0 | - | - | - | PASS |
| none | 0 | 1 | 1 | - | - | - | PASS |
| none | 0 | 1 | 2 | - | - | - | PASS |
| none | 0 | 1 | 3 | - | - | - | PASS |
| none | 0 | 2 | 0 | - | - | - | PASS |
| none | 0 | 2 | 1 | - | - | - | PASS |
| none | 0 | 2 | 2 | - | - | - | PASS |
| none | 0 | 2 | 3 | - | - | - | PASS |
| none | 0 | 3 | 0 | - | - | - | PASS |
| none | 0 | 3 | 1 | - | - | - | PASS |
| none | 0 | 3 | 2 | - | - | - | PASS |
| none | 0 | 3 | 3 | - | - | - | PASS |
| lighting_change | 1 | 1 | 0 | - | - | - | PASS |
| lighting_change | 1 | 1 | 1 | - | - | - | PASS |
| lighting_change | 1 | 1 | 2 | - | - | - | PASS |
| lighting_change | 1 | 1 | 3 | - | - | - | PASS |
| lighting_change | 1 | 2 | 0 | - | - | - | PASS |
| lighting_change | 1 | 2 | 1 | - | - | - | PASS |
| lighting_change | 1 | 2 | 2 | - | - | - | PASS |
| lighting_change | 1 | 2 | 3 | - | - | - | PASS |
| lighting_change | 1 | 3 | 0 | - | - | - | PASS |
| lighting_change | 1 | 3 | 1 | - | - | - | PASS |
| lighting_change | 1 | 3 | 2 | - | - | - | PASS |
| lighting_change | 1 | 3 | 3 | - | - | - | PASS |

commit: 7332832 | runs: 156 | wall time: 1910 s | generated: 2026-10-09 15:12:50 | overall: PASS
