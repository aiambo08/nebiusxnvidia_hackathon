# Hysteresis vs a memoryless detector (Gate F5) — SIMULATION

`SyntheticSource` 640x480 textured scene, sensor noise sigma 1, 3, 5 analytic FPS, 1 s windows, real probe path (`benchmarks.replay.telemetry_windows`). 30 clean calibration windows, then 200 windows where a glitch of one strong fault (strength 1.0) lasting 1 or 2 windows starts at each window with probability p, plus 3 sustained faults of 10 windows. 2 seed(s) per (fault, p, sigma). Same `classify_window` verdicts for both: the memoryless detector alerts on every faulty window (per window, so already more stable than frame by frame); the tracker alerts on CONFIRMED (enter_windows=3) and closes after exit_windows=2 fault-free windows, without cooldown. Flapping = alert on/off changes; flaps = changes outside each sustained fault's guard zone [start - enter_windows, end + exit_windows]. Gate: flaps cut by >= 50 % in every cell where the memoryless detector flaps >= 10 times, no more flaps in the other cells (n/a), all changes cut by >= 50 % overall; a cell is valid only if every sustained fault was alerted on, every sustained alert closed before the next sustained fault (or the end of the run) and every run calibrated. `fsm changes` also counts the internal HEALTHY <-> SUSPECT moves (not alerts).

| fault | p | runs | memoryless flaps | tracker flaps | flap cut | memoryless changes | tracker changes | change cut | fsm changes | sustained alerted | sustained closed | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dark | 0.1 | 4 | 94 | 15 | 84.0 % | 127 | 36 | 71.7 % | 131 | 12/12 | 12/12 | PASS |
| dark | 0.2 | 4 | 188 | 47 | 75.0 % | 227 | 65 | 71.4 % | 198 | 12/12 | 12/12 | PASS |
| dark | 0.3 | 4 | 230 | 78 | 66.1 % | 264 | 96 | 63.6 % | 224 | 12/12 | 12/12 | PASS |
| freeze | 0.1 | 4 | 10 | 0 | 100.0 % | 36 | 24 | 33.3 % | 48 | 12/12 | 12/12 | PASS |
| freeze | 0.2 | 4 | 24 | 6 | 75.0 % | 51 | 28 | 45.1 % | 65 | 12/12 | 12/12 | PASS |
| freeze | 0.3 | 4 | 76 | 17 | 77.6 % | 100 | 42 | 58.0 % | 121 | 12/12 | 12/12 | PASS |
| gaussian_blur | 0.1 | 4 | 123 | 14 | 88.6 % | 150 | 38 | 74.7 % | 155 | 12/12 | 12/12 | PASS |
| gaussian_blur | 0.2 | 4 | 175 | 32 | 81.7 % | 210 | 52 | 75.2 % | 181 | 12/12 | 12/12 | PASS |
| gaussian_blur | 0.3 | 4 | 213 | 67 | 68.5 % | 248 | 86 | 65.3 % | 209 | 12/12 | 12/12 | PASS |
| occlude_opaque | 0.1 | 4 | 96 | 10 | 89.6 % | 126 | 32 | 74.6 % | 130 | 12/12 | 12/12 | PASS |
| occlude_opaque | 0.2 | 4 | 188 | 45 | 76.1 % | 224 | 65 | 71.0 % | 212 | 12/12 | 12/12 | PASS |
| occlude_opaque | 0.3 | 4 | 229 | 72 | 68.6 % | 266 | 92 | 65.4 % | 227 | 12/12 | 12/12 | PASS |
| overexpose | 0.1 | 4 | 104 | 21 | 79.8 % | 132 | 44 | 66.7 % | 138 | 12/12 | 12/12 | PASS |
| overexpose | 0.2 | 4 | 187 | 40 | 78.6 % | 224 | 62 | 72.3 % | 215 | 12/12 | 12/12 | PASS |
| overexpose | 0.3 | 4 | 221 | 74 | 66.5 % | 262 | 92 | 64.9 % | 233 | 12/12 | 12/12 | PASS |

**Overall:** memoryless 2647 changes, tracker 854, reduction 67.7 % — PASS.

## Runs

| fault | p | sigma | seed | bad windows | memoryless flaps/changes | tracker flaps/changes | fsm | sustained alerted | sustained closed |
|---|---|---|---|---|---|---|---|---|---|
| dark | 0.1 | 1 | 0 | 53/230 | 26/32 | 5/10 | 33 | 3/3 | 3/3 |
| dark | 0.1 | 1 | 1 | 47/230 | 15/21 | 6/12 | 25 | 3/3 | 3/3 |
| dark | 0.1 | 3 | 0 | 49/230 | 27/36 | 0/6 | 37 | 3/3 | 3/3 |
| dark | 0.1 | 3 | 1 | 62/230 | 26/38 | 4/8 | 36 | 3/3 | 3/3 |
| dark | 0.2 | 1 | 0 | 83/230 | 46/57 | 13/17 | 48 | 3/3 | 3/3 |
| dark | 0.2 | 1 | 1 | 73/230 | 39/48 | 9/12 | 44 | 3/3 | 3/3 |
| dark | 0.2 | 3 | 0 | 86/230 | 56/68 | 14/18 | 56 | 3/3 | 3/3 |
| dark | 0.2 | 3 | 1 | 83/230 | 47/54 | 11/18 | 50 | 3/3 | 3/3 |
| dark | 0.3 | 1 | 0 | 94/230 | 48/53 | 16/20 | 45 | 3/3 | 3/3 |
| dark | 0.3 | 1 | 1 | 98/230 | 58/67 | 23/28 | 65 | 3/3 | 3/3 |
| dark | 0.3 | 3 | 0 | 96/230 | 62/72 | 13/18 | 52 | 3/3 | 3/3 |
| dark | 0.3 | 3 | 1 | 99/230 | 62/72 | 26/30 | 62 | 3/3 | 3/3 |
| gaussian_blur | 0.1 | 1 | 0 | 51/230 | 28/34 | 2/8 | 36 | 3/3 | 3/3 |
| gaussian_blur | 0.1 | 1 | 1 | 62/230 | 37/44 | 6/12 | 44 | 3/3 | 3/3 |
| gaussian_blur | 0.1 | 3 | 0 | 62/230 | 36/42 | 6/12 | 42 | 3/3 | 3/3 |
| gaussian_blur | 0.1 | 3 | 1 | 49/230 | 22/30 | 0/6 | 33 | 3/3 | 3/3 |
| gaussian_blur | 0.2 | 1 | 0 | 69/230 | 38/47 | 7/12 | 47 | 3/3 | 3/3 |
| gaussian_blur | 0.2 | 1 | 1 | 84/230 | 45/53 | 6/10 | 42 | 3/3 | 3/3 |
| gaussian_blur | 0.2 | 3 | 0 | 84/230 | 49/58 | 14/20 | 47 | 3/3 | 3/3 |
| gaussian_blur | 0.2 | 3 | 1 | 72/230 | 43/52 | 5/10 | 45 | 3/3 | 3/3 |
| gaussian_blur | 0.3 | 1 | 0 | 99/230 | 52/62 | 15/20 | 48 | 3/3 | 3/3 |
| gaussian_blur | 0.3 | 1 | 1 | 80/230 | 47/59 | 13/18 | 54 | 3/3 | 3/3 |
| gaussian_blur | 0.3 | 3 | 0 | 90/230 | 51/58 | 20/24 | 54 | 3/3 | 3/3 |
| gaussian_blur | 0.3 | 3 | 1 | 109/230 | 63/69 | 19/24 | 53 | 3/3 | 3/3 |
| freeze | 0.1 | 1 | 0 | 65/230 | 8/14 | 0/6 | 17 | 3/3 | 3/3 |
| freeze | 0.1 | 1 | 1 | 47/230 | 0/6 | 0/6 | 9 | 3/3 | 3/3 |
| freeze | 0.1 | 3 | 0 | 64/230 | 2/10 | 0/6 | 13 | 3/3 | 3/3 |
| freeze | 0.1 | 3 | 1 | 48/230 | 0/6 | 0/6 | 9 | 3/3 | 3/3 |
| freeze | 0.2 | 1 | 0 | 77/230 | 5/13 | 0/6 | 16 | 3/3 | 3/3 |
| freeze | 0.2 | 1 | 1 | 73/230 | 7/12 | 3/8 | 16 | 3/3 | 3/3 |
| freeze | 0.2 | 3 | 0 | 72/230 | 4/10 | 3/8 | 14 | 3/3 | 3/3 |
| freeze | 0.2 | 3 | 1 | 82/230 | 8/16 | 0/6 | 19 | 3/3 | 3/3 |
| freeze | 0.3 | 1 | 0 | 104/230 | 22/28 | 8/14 | 35 | 3/3 | 3/3 |
| freeze | 0.3 | 1 | 1 | 105/230 | 23/30 | 2/10 | 35 | 3/3 | 3/3 |
| freeze | 0.3 | 3 | 0 | 110/230 | 23/28 | 4/10 | 33 | 3/3 | 3/3 |
| freeze | 0.3 | 3 | 1 | 93/230 | 8/14 | 3/8 | 18 | 3/3 | 3/3 |
| occlude_opaque | 0.1 | 1 | 0 | 55/230 | 25/32 | 5/10 | 34 | 3/3 | 3/3 |
| occlude_opaque | 0.1 | 1 | 1 | 53/230 | 29/36 | 3/8 | 34 | 3/3 | 3/3 |
| occlude_opaque | 0.1 | 3 | 0 | 41/230 | 16/22 | 0/6 | 24 | 3/3 | 3/3 |
| occlude_opaque | 0.1 | 3 | 1 | 51/230 | 26/36 | 2/8 | 38 | 3/3 | 3/3 |
| occlude_opaque | 0.2 | 1 | 0 | 77/230 | 40/48 | 13/18 | 49 | 3/3 | 3/3 |
| occlude_opaque | 0.2 | 1 | 1 | 71/230 | 49/58 | 12/17 | 48 | 3/3 | 3/3 |
| occlude_opaque | 0.2 | 3 | 0 | 88/230 | 49/59 | 16/20 | 55 | 3/3 | 3/3 |
| occlude_opaque | 0.2 | 3 | 1 | 76/230 | 50/59 | 4/10 | 60 | 3/3 | 3/3 |
| occlude_opaque | 0.3 | 1 | 0 | 100/230 | 61/70 | 21/27 | 57 | 3/3 | 3/3 |
| occlude_opaque | 0.3 | 1 | 1 | 100/230 | 52/61 | 18/22 | 54 | 3/3 | 3/3 |
| occlude_opaque | 0.3 | 3 | 0 | 96/230 | 56/65 | 18/22 | 60 | 3/3 | 3/3 |
| occlude_opaque | 0.3 | 3 | 1 | 104/230 | 60/70 | 15/21 | 56 | 3/3 | 3/3 |
| overexpose | 0.1 | 1 | 0 | 60/230 | 36/42 | 10/16 | 40 | 3/3 | 3/3 |
| overexpose | 0.1 | 1 | 1 | 48/230 | 21/28 | 3/8 | 28 | 3/3 | 3/3 |
| overexpose | 0.1 | 3 | 0 | 53/230 | 25/32 | 6/12 | 36 | 3/3 | 3/3 |
| overexpose | 0.1 | 3 | 1 | 51/230 | 22/30 | 2/8 | 34 | 3/3 | 3/3 |
| overexpose | 0.2 | 1 | 0 | 80/230 | 42/54 | 10/16 | 54 | 3/3 | 3/3 |
| overexpose | 0.2 | 1 | 1 | 70/230 | 45/52 | 6/12 | 52 | 3/3 | 3/3 |
| overexpose | 0.2 | 3 | 0 | 82/230 | 44/52 | 13/18 | 49 | 3/3 | 3/3 |
| overexpose | 0.2 | 3 | 1 | 85/230 | 56/66 | 11/16 | 60 | 3/3 | 3/3 |
| overexpose | 0.3 | 1 | 0 | 99/230 | 58/64 | 19/24 | 60 | 3/3 | 3/3 |
| overexpose | 0.3 | 1 | 1 | 97/230 | 51/64 | 22/26 | 59 | 3/3 | 3/3 |
| overexpose | 0.3 | 3 | 0 | 82/230 | 46/60 | 10/14 | 51 | 3/3 | 3/3 |
| overexpose | 0.3 | 3 | 1 | 102/230 | 66/74 | 23/28 | 63 | 3/3 | 3/3 |

commit: b6ddfd3 | runs: 60 | wall time: 1929 s | generated: 2026-10-17 18:36:07 | overall: PASS
