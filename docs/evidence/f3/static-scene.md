# Static-scene freeze false positives (Gate F3) — SIMULATION

Synthetic 640x480 scenes, 5 analytic FPS, full local path (`benchmarks.replay.replay`: probes -> windows -> baseline -> IncidentTracker). Healthy cases must never confirm `freeze`; frozen cases must confirm `freeze` after the freeze. Other faults confirmed on a healthy scene are listed as findings.

| scene | minutes | windows | freeze windows | confirmed | delay s | result |
|---|---|---|---|---|---|---|
| wall sigma 0.7 (laptop webcam at rest) | 20 | 1200 | 0 | fov_shift | - | PASS (freeze); finding: fov_shift |
| wall sigma 2 | 20 | 1200 | 0 | fov_shift | - | PASS (freeze); finding: fov_shift |
| textured sigma 1 | 20 | 1200 | 0 | - | - | PASS |
| textured sigma 2 (reviewer FP case) | 20 | 1200 | 0 | - | - | PASS |
| textured sigma 3 | 20 | 1200 | 0 | - | - | PASS |
| textured sigma 2, dim (gain 0.3) | 20 | 1200 | 0 | - | - | PASS |
| textured sigma 2, slow light drift 15% | 20 | 1200 | 0 | - | - | PASS |
| textured sigma 2, frozen bit-exact | 3 | 180 | 118 | freeze | 4.0 | PASS |
| textured sigma 2, frozen + codec jitter 0.1 | 3 | 180 | 118 | freeze | 4.0 | PASS |
| textured sigma 2, frozen + codec jitter 0.2 | 3 | 180 | 22 | freeze | 4.0 | INFO: detected |
| textured sigma 2, frozen + codec jitter 0.5 | 3 | 180 | 0 | - | - | INFO: not detected (documented) |
| wall sigma 0.7, frozen bit-exact | 3 | 180 | 120 | freeze | 2.0 | PASS |
| textured sigma 2, loop of 4 frames | 3 | 180 | 120 | freeze | 2.0 | PASS |

## Findings (other faults confirmed on a healthy static scene)

- `wall sigma 0.7 (laptop webcam at rest)`: `fov_shift` — false positive of another detector, tracked in `docs/agents/TASKS.md`
- `wall sigma 2`: `fov_shift` — false positive of another detector, tracked in `docs/agents/TASKS.md`

generated: 2026-10-08 19:10:15
