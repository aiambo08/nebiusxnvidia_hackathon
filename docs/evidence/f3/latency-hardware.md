# Probe latency on the owner's laptop — REAL HARDWARE CPU, synthetic frames

Box: probe set p95 ≤ 40 ms/frame at 720p, 5 analytic FPS (`docs/phases-and-gates.md`, F3).
**Passed** after geometry moved to a pool thread (see "Re-measurement after geometry on a pool
thread" below): 720p paced p95 23.2 / 32.6 / 34.5 ms in 3 runs under Windows "Best performance"
(synthetic frames). Before that change: p95 41.4 ms (single run, sections below). Under
"Balanced": 54–112 ms. The sections up to "Consequences" describe the earlier runs.

- Machine: owner's laptop, native Windows AMD64, 28 logical CPUs, Python 3.11.9, OpenCV 5.0.0,
  plugged in (confirmed by the owner after the runs). Frames are `SyntheticSource` frames (no camera, no network), so this measures the
  probe-set cost on the CPU the agent runs on, not a live stream.
- Intended code: `main` after PR #34 (`f3be8a7`, probe-cost rewrite); not verified, the SHA was
  not pasted back.
- Tool: `scripts/bench_probes.py` (`--breakdown` per-probe p95 measured inside `analyse`).
  Each row is a single run (n = 100, n = 150 for the isolated rows). The only repeated condition
  (720p paced, 28 threads; once via the CLI, once via the `cv2.setNumThreads(28)` sweep) gave
  112.5 then 72.2 ms p95 (1.6×). With that spread, the 41.4 vs 40 ms margin and the single
  640×480 PASS are not reliable: any future tick needs ≥ 3 repeats.

## 1. Default settings (power plan "Balanced", OpenCV default 28 threads)

| condition | p50 ms | p95 ms | gate |
|---|---|---|---|
| 1280×720 isolated (back-to-back) | 24.2 | 34.5 | PASS |
| 640×480 isolated | 34.2 | 92.6 | FAIL |
| 640×480 paced + capture thread + tracemalloc (`spike_capture`'s conditions) | 148.4 | 194.6 | FAIL |
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

Under "Balanced" no thread setting brought p95 below 64 ms (640×480) or 54 ms (720p) (single runs;
the spread between settings is within the 1.6× run-to-run spread; not measured under "Best
performance"). Thread oversubscription is not the main cause, and no thread setting is changed.

## 3. Windows power mode "Best performance" (default threads)

| condition | p50 ms | p95 ms | gate |
|---|---|---|---|
| 640×480 paced at 5 FPS | 24.6 | 32.7 | PASS |
| 1280×720 paced at 5 FPS (the box) | 20.2 | 41.4 | FAIL (+1.4 ms) |
| 640×480 paced + capture thread + tracemalloc (`spike_capture`'s conditions) | 35.8 | 46.1 | FAIL |

Per-probe p95 ms, 1280×720 paced: downscale 0.1, exposure 1.6, sharpness 8.1, freeze 8.2,
occlusion 5.9, geometry 11.0, task 2.8.

## Findings
1. On synthetic frames, switching the power plan from "Balanced" to "Best performance" cut 720p
   paced p95 from 54–112 ms (4 single runs) to 41.4 ms (1 run), and `spike_capture`'s conditions
   from 194.6 to 46.1 ms. Under "Balanced", at 720p the paced p95 was 54–112 ms against 34.5 ms
   back-to-back (1.6–3.3×, single runs); at 640×480 the paced runs (64–76 ms) came in below the
   single isolated run (92.6 ms). Pacing at 5 FPS leaves the CPU mostly idle between frames
   (roughly 60–90 % depending on p50). Inference: this accounts for most of the live 110–248 ms
   gap; live `spike_capture.py` was not re-run under "Best performance". Inference (not
   measured): the CPU lowers its clock or Windows moves the idle process to efficiency cores
   between frames.
2. The remaining 720p tail is p95 41.4 ms with p50 20.2 ms; geometry (ORB + RANSAC on every 5th
   frame) is the largest stage (p95 11.0 ms), followed by freeze and sharpness (≈ 8 ms each).
3. The `spike_capture` row includes `tracemalloc` (needed only for the F1 heap gate), so it is
   not the box's condition.

## Consequences
- Demo and live runs: laptop plugged in and Windows power mode "Best performance"
  (`docs/demo-script.md`).
- The box stayed open until the 720p paced p95 was ≤ 40 ms on this laptop; the geometry probe was
  then moved to a pool thread (see below).

## Re-measurement after geometry on a pool thread (REAL HARDWARE CPU)
Same laptop, plugged in, Windows power mode "Best performance", synthetic frames (no camera, no
network), `main` after the parallel-geometry change (`probes.geometry.parallel: true`; no
threshold, ORB setting, cadence or analysis size changed). Code SHA `ae918ae` (the merge of the
parallel-geometry change), reported by the owner from `git rev-parse --short HEAD`; working-tree
status not reported. Three consecutive runs of
`uv run python scripts/bench_probes.py --size 1280x720 --frames 100 --paced --breakdown`:

| run | p50 ms | p95 ms | gate ≤ 40 ms |
|---|---:|---:|---|
| 1 | 18.4 | 23.2 | PASS |
| 2 | 30.3 | 32.6 | PASS |
| 3 | 30.8 | 34.5 | PASS |

Per-probe p95 ms (runs 1/2/3): sharpness 5.7/7.9/8.0, freeze 5.9/7.9/9.2, geometry 9.8/13.4/14.8,
occlusion 3.6/5.5/5.5, exposure 1.3/1.6/1.5, task 2.4/3.0/3.1, downscale 0.1. With geometry on the
pool thread its stage overlaps the others, so the stages do not sum to the total.

All three runs pass with ≥ 5.5 ms margin (worst p95 34.5 ms vs 41.4 ms in the single run before
the change). p50 rose from 18.4 to ~30 ms between run 1 and runs 2–3; the cause was not measured.
The pass holds under "Best performance" only; under "Balanced" the earlier runs were 54–112 ms,
so the demo requirement (plugged in, "Best performance") stays.
