# 20-min static scene on the owner's hardware (Gate F3) — REAL HARDWARE

Run 2026-10-11 by the owner on his laptop (native Windows, integrated 640×480 webcam) and his
Android phone (IP Webcam app, same Wi-Fi), on `main` after PR #24 (ADR-008), with
`scripts/spike_static_scene.py --uri <uri> --minutes 20 --label <tag>`. The source URI only lived
in a local environment variable; the summaries below are the tool's own `.md` output and contain no
address. Each run drives the production path (`CaptureWorker` -> probes -> windows -> baseline ->
`IncidentTracker`) at 5 analytic FPS.

## Summary

| label | source / scene | judged windows (with frames) | freeze windows | exact_repeat_ratio p95 | other faults | verdict |
|---|---|---:|---:|---:|---|---|
| `webcam-rest` (run 2) | integrated webcam, laptop turned to a fixed scene, nobody in frame | 1057 (1057) | **0** | 0.0 | none | **PASS** |
| `rtsp-wall` | phone RTSP H.264, plain lit wall | 980 (971) | **0** | 0.0 | 1 unconfirmed `fov_shift` window at 988.9 s | **PASS** |
| `rtsp-textured` | phone RTSP H.264, textured scene | 987 (944) | **0** | 0.0 | `stream_down` confirmed at 464 s; 21 short gaps without frames (longest 6 windows ≈ 7 s, at 460 s and 500 s), 16 transport-fault windows, 0 reconnects | **PASS** (finding) |
| `mjpeg-q80` | phone MJPEG over HTTP (`/video`, quality 80), same plain wall | 1058 (1003) | **0** | 0.0 | `stream_down` confirmed at 251 s; 16 gaps without frames (longest 21 windows ≈ 22 s at 584–605 s, then 11 ≈ 12 s at 468–478 s), 36 transport-fault windows, 0 reconnects | INCONCLUSIVE (windows with frames 1003/1058 = 94.8 % < 95 %; supporting evidence only) |
| `webcam-rest` (run 1, excluded) | integrated webcam with the owner sitting in front of it | 1032 (1032) | **0** | 0.0 | `lens_occlusion` from 9 s, 757 windows | not a scene at rest |

The box is carried by the PASS runs (webcam at rest, phone RTSP wall, phone RTSP textured). Across
all five runs, including the excluded one and the INCONCLUSIVE MJPEG run: 5114 judged windows, 0
`freeze` windows, no window with `exact_repeat_ratio ≥ 0.9`, no loop window.

Traceability: code at `05c5030` (`git rev-parse --short HEAD` on the owner's checkout, `main` after
PR #24). The per-window JSON written by `scripts/spike_static_scene.py` for each counted run is
committed unchanged under `hardware/` (label only, no URI; scanned for IPv4, URLs, paths and `@`: none).
Re-running `summarise()` of `scripts/spike_static_scene.py` on each file's `windows` reproduces its
stored summary and the figures below exactly.

| run | file | sha256 |
|---|---|---|
| `webcam-rest` (run 2) | `hardware/static-scene-webcam-rest.json` | `7dbb965382e4695e24661906f77945c0016d6aeec3078a2f8146780007669715` |
| `rtsp-wall` | `hardware/static-scene-rtsp-wall.json` | `a57fd4bfcfd4c75123c19450d77d13836aff0ebc9c8da8d0d4c4ac8cc1ec5ccf` |
| `rtsp-textured` | `hardware/static-scene-rtsp-textured.json` | `4cc8c95367509ed92bc81d904228a45b0eceb8c61302547699a53640af36b8a2` |
| `mjpeg-q80` | `hardware/static-scene-mjpeg-q80.json` | `cee544e11a4194f779cd275b661a81282b5625ba887f9cbdf6c561c1de2e83e5` |

Run 1 of `webcam-rest` has no JSON: run 2 used the same label and overwrote it.

## Findings
- **The H.264 plain-wall risk did not materialise on this phone.** SIMULATION showed libx264 decoding
  a live smooth wall bit-exact (`exact_repeat_ratio` 1.00, ADR-005); the phone's encoder on a real lit
  wall gave `exact_repeat_ratio` 0.0 at p95 and max over 971 windows, `temporal_sigma_p50` ≈ 0.61. The
  structural item (transport-level freeze evidence) stays open for other encoders, not for this one.
- **MJPEG quality 80** on the same wall: `exact_repeat_ratio` 0.0 while `repeated_hash_ratio` is 1.0 in
  every window — the case where the pre-ADR-005 hash rule would have fired. MJPEG at quality ≤ 50
  (bit-exact in SIMULATION) was not measured.
- **`noise_ratio_p50` is NaN on MJPEG** in every window: JPEG quantisation leaves the flattest half of
  the wall with a spatial sigma below `MIN_SPATIAL_SIGMA` (0.05), so the ratio is reported as not
  measurable, as designed (`probes/temporal.py::noise_ratio`); `temporal_sigma_p50` ≈ 0.39 is still
  measured. Telemetry only, no detector reads it (ADR-005).
- **Webcam at rest is clean on every detector** in run 2, including `lens_occlusion` (ADR-007/008).
  Run 1's `lens_occlusion` happened with the owner in front of the camera (owner's confirmation). From
  the summary alone it cannot be told whether it was a true positive (a person close to the lens covering
  > 30 % of the calibrated cells) or the owner learned during calibration and then absent (ADR-008
  limit); its JSON was overwritten by run 2 (same label), so this stays undetermined on hardware.
- **Phone stream gaps** (from the JSON; the `.md` timeline prints one line per ~70 s and had
  suggested a single 35–40 s outage, which is wrong): the phone streams stall repeatedly for short
  spells instead. `rtsp-textured`: 21 runs of windows without frames (17 after the 4 handshake
  windows), mostly 1–3 windows, longest 6 (≈ 7 s) at 460 s and 500 s; `stream_down` confirmed at
  464 s. `mjpeg-q80`: 16 runs, longest 21 windows (≈ 22 s) at 584–605 s and 11 (≈ 12 s) at
  468–478 s. `rtsp-wall`: 6 runs after the handshake, 1–2 windows each, never reaching `stream_down`.
  All recovered with `reconnects: 0`. Cause not established (phone or Wi-Fi); they are transport
  events, correctly not reported as `freeze`.
- **One unconfirmed `fov_shift` window on `rtsp-wall`** at 988.9 s (4 frames, the tracker did not
  confirm it) on a plain wall at rest. Single window, no incident, but it is a REAL HARDWARE
  geometry false alarm on a smooth scene (ADR-006 risk) to keep in view for the walk-by trials.
- Live webcam noise: `noise_ratio_p50` ≈ 3.1 with `temporal_sigma_p50` ≈ 0.51 (run 2) — the ISP
  smooths spatially more than temporally, unlike the raw-sensor population of ADR-005 (≈ 1).

## Raw summaries (tool output)

### `webcam-rest` (run 2)
```
- source: webcam | frame: 640x480 | duration: 20 min | analytic 5 FPS
- handshake (windows before the first frame, not judged): 0 (0.0 s)
- judged windows: 1057, valid: 1057, freeze windows: 0, other-fault windows: 0
- windows with exact_repeat_ratio >= 0.9: 0; loop windows: 0; stalled polls (same frame twice): 0/4897
- capture fps: 29.986, decode errors: 0, reconnects: 0, dropped: 0
- result: PASS: no `freeze` window on a camera at rest

| metric | p50 | p95 | max | n |
|---|---|---|---|---|
| exact_repeat_ratio | 0.0 | 0.0 | 0.0 | 1057 |
| noise_ratio_p50 | 3.1062 | 3.1418 | 10.5186 | 1056 |
| temporal_sigma_p50 | 0.5146 | 0.5181 | 1.9924 | 1056 |
| temporal_mse_p50 | 0.3698 | 0.3763 | 7.6222 | 1056 |
| repeated_hash_ratio | 0.8 | 1.0 | 1.0 | 1057 |
| loop_period | None | None | None | 0 |

generated: 2026-10-11 22:25:12
```

### `rtsp-wall`
```
- source: rtsp | frame: 640x480 | duration: 20 min | analytic 5 FPS
- handshake (windows before the first frame, not judged): 4 (4.0 s)
- judged windows: 980, valid: 971, freeze windows: 0, other-fault windows: 1
- windows with exact_repeat_ratio >= 0.9: 0; loop windows: 0; stalled polls (same frame twice): 232/3906
- capture fps: 31.786, decode errors: 3, reconnects: 0, dropped: 0
- result: PASS: no `freeze` window on a camera at rest

| metric | p50 | p95 | max | n |
|---|---|---|---|---|
| exact_repeat_ratio | 0.0 | 0.0 | 0.0 | 971 |
| noise_ratio_p50 | 0.8434 | 0.8629 | 3.225 | 970 |
| temporal_sigma_p50 | 0.6098 | 0.6244 | 2.3092 | 970 |
| temporal_mse_p50 | 0.2365 | 0.254 | 27.1579 | 970 |
| repeated_hash_ratio | 0.8 | 1.0 | 1.0 | 971 |
| loop_period | None | None | None | 0 |

generated: 2026-10-11 21:14:15
```

### `rtsp-textured`
```
- source: rtsp | frame: 640x480 | duration: 20 min | analytic 5 FPS
- handshake (windows before the first frame, not judged): 4 (4.0 s)
- judged windows: 987, valid: 944, freeze windows: 0, other-fault windows: 16
- windows with exact_repeat_ratio >= 0.9: 0; loop windows: 0; stalled polls (same frame twice): 513/4025
- capture fps: 29.986, decode errors: 8, reconnects: 0, dropped: 0
- result: PASS: no `freeze` window on a camera at rest; finding: stream_down confirmed at 464 s (another detector)

| metric | p50 | p95 | max | n |
|---|---|---|---|---|
| exact_repeat_ratio | 0.0 | 0.0 | 0.0 | 944 |
| noise_ratio_p50 | 1.0706 | 1.1995 | 1.5644 | 943 |
| temporal_sigma_p50 | 0.6288 | 0.7079 | 0.918 | 943 |
| temporal_mse_p50 | 0.2309 | 0.3714 | 0.7195 | 943 |
| repeated_hash_ratio | 0.55 | 1.0 | 1.0 | 944 |
| loop_period | None | None | None | 0 |

generated: 2026-10-11 20:53:03
```

### `mjpeg-q80`
```
- source: http | frame: 640x480 | duration: 20 min | analytic 5 FPS
- handshake (windows before the first frame, not judged): 0 (0.0 s)
- judged windows: 1058, valid: 1003, freeze windows: 0, other-fault windows: 36
- windows with exact_repeat_ratio >= 0.9: 0; loop windows: 0; stalled polls (same frame twice): 630/4711
- capture fps: 38.306, decode errors: 0, reconnects: 0, dropped: 0
- result: INCONCLUSIVE: first frame after 0.0 s, 1003/1058 judged windows with frames, 36 with stream_down/low_fps; the source did not deliver a steady picture

| metric | p50 | p95 | max | n |
|---|---|---|---|---|
| exact_repeat_ratio | 0.0 | 0.0 | 0.0 | 1003 |
| noise_ratio_p50 | None | None | None | 0 |
| temporal_sigma_p50 | 0.3865 | 0.3991 | 2.1362 | 1003 |
| temporal_mse_p50 | 0.3439 | 0.3648 | 15.5406 | 1003 |
| repeated_hash_ratio | 1.0 | 1.0 | 1.0 | 1003 |
| loop_period | None | None | None | 0 |

generated: 2026-10-11 21:47:54
```

### `webcam-rest` (run 1, excluded: the owner was in frame)
```
- source: webcam | frame: 640x480 | duration: 20 min | analytic 5 FPS
- handshake (windows before the first frame, not judged): 0 (0.0 s)
- judged windows: 1032, valid: 1032, freeze windows: 0, other-fault windows: 757
- windows with exact_repeat_ratio >= 0.9: 0; loop windows: 0; stalled polls (same frame twice): 0/4698
- capture fps: 29.89, decode errors: 0, reconnects: 0, dropped: 0
- result: PASS: no `freeze` window on a camera at rest; finding: lens_occlusion confirmed at 9 s (another detector)

| metric | p50 | p95 | max | n |
|---|---|---|---|---|
| exact_repeat_ratio | 0.0 | 0.0 | 0.0 | 1032 |
| noise_ratio_p50 | 2.625 | 12.3402 | 77.3994 | 1031 |
| temporal_sigma_p50 | 0.8419 | 3.2036 | 18.4108 | 1031 |
| temporal_mse_p50 | 3.8683 | 142.3465 | 1036.5135 | 1031 |
| repeated_hash_ratio | 0.6 | 1.0 | 1.0 | 1032 |
| loop_period | None | None | None | 0 |

generated: 2026-10-11 19:34:55
```
