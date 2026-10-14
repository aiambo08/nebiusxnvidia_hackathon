# Probe latency on the owner's laptop — REAL HARDWARE CPU, synthetic frames

Box: probe set p95 ≤ 40 ms/frame at 720p, 5 analytic FPS (`docs/phases-and-gates.md`, F3).
**Not passed:** the closest condition (`--paced`, 1280×720, Windows power mode "Best performance")
gives p95 41.4 ms.

- Machine: owner's laptop, native Windows AMD64, 28 logical CPUs, Python 3.11.9, OpenCV 5.0.0,
  plugged in. Frames are `SyntheticSource` frames (no camera, no network), so this measures the
  probe-set cost on the CPU the agent runs on, not a live stream.
- Code: `main` after PR #34 (probe-cost rewrite). The owner was asked to check out `f3be8a7`;
  the SHA was not pasted back, so it is not recorded here.
- Tool: `scripts/bench_probes.py` (`--breakdown` per-probe p95 measured inside `analyse`).
  Each row is a single run (n = 100, n = 150 for the isolated rows); repeated runs of the same
  command differed by up to 1.6× (720p paced, 28 threads: 112.5 then 72.2 ms p95).

## 1. Default settings (power plan "Balanced", OpenCV default 28 threads)

| condition | p50 ms | p95 ms | gate |
|---|---|---|---|
| 1280×720 isolated (back-to-back) | 24.2 | 34.5 | PASS |
| 640×480 isolated | 34.2 | 92.6 | FAIL |
| 640×480 paced + capture thread + tracemalloc (= `spike_capture`) | 148.4 | 194.6 | FAIL |
| 1280×720 paced at 5 FPS (the box) | 75.1 | 112.5 | FAIL |

Per-probe p95 ms, 1280×720 paced: downscale 0.3, exposure 4.2, sharpness 21.8, freeze 24.3,
occlusion 17.3, geometry 31.7, task 8.2.

## 2. OpenCV thread count (Balanced, `--paced`, `cv2.setNumThreads(N)`)

| N | 640×480 p50 / p95 ms | 1280×720 p50 / p95 ms |
|---|---|---|
| 1 | 40.0 / 76.4 | 36.4 / 54.3 |
| 2 | 39.0 / 66.8 | — |
| 4 | 43.1 / 71.2 | 34.8 / 54.0 |
| 8 | 42.0 / 64.2 | — |
| 28 | 47.7 / 71.8 | 31.1 / 72.2 |

The thread count does not move p95 below 64 ms (640×480) or 54 ms (720p): thread oversubscription
is not the cause, and no thread setting is changed.

## 3. Windows power mode "Best performance" (default threads)

| condition | p50 ms | p95 ms | gate |
|---|---|---|---|
| 640×480 paced at 5 FPS | 24.6 | 32.7 | PASS |
| 1280×720 paced at 5 FPS (the box) | 20.2 | 41.4 | FAIL (+1.4 ms) |
| 640×480 paced + capture thread + tracemalloc (= `spike_capture`) | 35.8 | 46.1 | FAIL |

Per-probe p95 ms, 1280×720 paced: downscale 0.1, exposure 1.6, sharpness 8.1, freeze 8.2,
occlusion 5.9, geometry 11.0, task 2.8.

## Findings
1. Power management, not the algorithm, explains most of the live gap: pacing at 5 FPS leaves the
   CPU idle 80 % of the time, and under "Balanced" the paced p95 is 2–3× the back-to-back p95.
   "Best performance" cuts 720p paced p95 112.5 → 41.4 ms and the `spike_capture` conditions
   194.6 → 46.1 ms. Inference (not measured): the CPU lowers its clock or Windows moves the idle
   process to efficiency cores between frames.
2. The remaining 720p tail is p95 41.4 ms with p50 20.2 ms; geometry (ORB + RANSAC on every 5th
   frame) is the largest stage (p95 11.0 ms), followed by freeze and sharpness (≈ 8 ms each).
3. The `spike_capture` row includes `tracemalloc` (needed only for the F1 heap gate), so it is
   not the box's condition.

## Consequences
- Demo and live runs: laptop plugged in and Windows power mode "Best performance"
  (`docs/demo-script.md`).
- The box stays open until the 720p paced p95 is ≤ 40 ms on this laptop; next step: reduce the
  geometry cost without threshold changes (`docs/agents/TASKS.md`).
