# 20+ person walk-by trials for `fov_shift` on the owner's webcam (Gate F3) — REAL HARDWARE

Run 2026-10-13 by the owner on his laptop (native Windows, integrated 640×480 webcam pointed at a
textured scene, crossing a few metres from the camera), on `main` after PR #31, with
`scripts/spike_walkby.py --uri 0 --label webcam-walk1` (defaults: START 10 s, CALIBRATE 30 s,
22 × (WALK 8 s + REST 12 s), BUMP 10 s). The run drives the production path
(`CaptureWorker` -> probes -> windows -> baseline -> `IncidentTracker`) at 5 analytic FPS and logs
every window, not only confirmations.

## Result

**PASS: 0 `fov_shift` windows across 22 walk-by trials, BUMP detected.**

| | value |
|---|---|
| geometry reference | re-taken at the end of CALIBRATE on a still scene (`ok`) |
| trials observed (WALK `temporal_mse_p50` max ≥ 10 and ≥ 80 % armed) | **22/22** (needed 20) |
| WALK windows armed (`quality == ok` and inlier ratio ≥ 0.35) | 176/176; inlier ratio min 0.674 |
| REST windows armed | 264/264; inlier ratio min 0.851 |
| `fov_shift` windows in WALK/REST (confirmed) | **0** (0) |
| `translation_px` max in WALK/REST (threshold 25) | 0.58 |
| WALK `temporal_mse_p50` max per trial | 1057 – 2305 (REST median 0.38; 2 REST windows of trial 1 above 10, still armed, no fault) |
| other faults in WALK/REST | none (`occluded_cell_ratio` max 0.058) |
| BUMP positive control | `fov_shift` at 523.2 s (56 px / rotation 55.9°) and 525.3 s (144 px, inliers 0.65) |
| capture | 29.881 fps, 0 decode errors, 0 reconnects, 0 dropped |

The tool's per-trial table, re-rendered from the JSON with `render()` of `scripts/spike_walkby.py`:

| trial | walk temporal_mse_p50 max | walk windows armed | observed | fov_shift windows | inlier max | translation_px max (armed) |
|---|---|---|---|---|---|---|
| 1 | 1056.781 | 8/8 | yes | 0 | 1.0 | 0.299 |
| 2 | 1902.248 | 8/8 | yes | 0 | 0.998 | 0.395 |
| 3 | 2070.78 | 8/8 | yes | 0 | 1.0 | 0.239 |
| 4 | 2198.478 | 8/8 | yes | 0 | 0.995 | 0.282 |
| 5 | 1935.071 | 8/8 | yes | 0 | 0.998 | 0.302 |
| 6 | 2304.674 | 8/8 | yes | 0 | 1.0 | 0.374 |
| 7 | 1902.357 | 8/8 | yes | 0 | 1.0 | 0.455 |
| 8 | 1807.702 | 8/8 | yes | 0 | 0.997 | 0.306 |
| 9 | 1852.163 | 8/8 | yes | 0 | 0.997 | 0.397 |
| 10 | 1759.211 | 8/8 | yes | 0 | 0.995 | 0.539 |
| 11 | 1901.889 | 8/8 | yes | 0 | 0.992 | 0.291 |
| 12 | 1939.069 | 8/8 | yes | 0 | 0.995 | 0.329 |
| 13 | 2168.033 | 8/8 | yes | 0 | 0.995 | 0.358 |
| 14 | 1960.771 | 8/8 | yes | 0 | 0.995 | 0.459 |
| 15 | 1826.082 | 8/8 | yes | 0 | 0.997 | 0.372 |
| 16 | 2135.633 | 8/8 | yes | 0 | 0.997 | 0.347 |
| 17 | 2028.858 | 8/8 | yes | 0 | 0.992 | 0.58 |
| 18 | 2199.887 | 8/8 | yes | 0 | 0.997 | 0.446 |
| 19 | 2256.291 | 8/8 | yes | 0 | 0.995 | 0.469 |
| 20 | 1897.164 | 8/8 | yes | 0 | 0.995 | 0.498 |
| 21 | 2216.14 | 8/8 | yes | 0 | 0.992 | 0.339 |
| 22 | 1931.892 | 8/8 | yes | 0 | 0.995 | 0.449 |

## Traceability
The per-window JSON written by the tool is committed unchanged as
`hardware/walkby-webcam-walk1.json` (sha256
`bcad1b47b5b1407b48675805acc153bacb01b40b3b3c1c87bd75e74f353f33f2`; label only, no URI; scanned
for IPv4, URLs and paths: none). Re-running `summarise()` of `scripts/spike_walkby.py` on its
`windows` reproduces the stored summary exactly. The JSON's `commit` field is `unknown`:
the owner's checkout was clean at `90cb5cb` (`main` after PR #31; `git rev-parse --short HEAD`
and an empty `git status --porcelain --untracked-files=no`, reported by the owner after the run;
owner-reported, not machine-recorded, and untracked files are not covered. `scripts/`, `src/` and `configs/` are identical at `90cb5cb` and on this branch).
`code_revision()` returned `unknown` because `git rev-parse --show-toplevel` succeeded but its
path did not compare equal to the script's own resolved root on the owner's Windows checkout
(diagnostic: `rc 0`, `same False`). That is a tool defect, fixed in a separate PR; the JSON is
kept as written and the code revision `90cb5cb` is recorded here, not in the JSON.

## Limits (what this run does and does not show)
- One camera (integrated webcam), one textured indoor scene, one person, crossings a few metres
  away. Close crossings by a person wider than about a third of the frame leave the geometry
  disarmed and are not observed trials (independent reviewer, SIMULATION; see `README.md`), so this
  run does not claim them.
- Phone RTSP/MJPEG walk-bys are not measured.
- This closes only the walk-by box. F3 as a whole stays open: recall/precision on real clips belongs to
  F4 (the 720p probe p95 box passed later, `latency-hardware.md`).
- Production still takes the geometry reference from the first frame (`runtime.py`, open in
  `docs/agents/TASKS.md`); this run used the tool's still reference re-taken after CALIBRATE.
