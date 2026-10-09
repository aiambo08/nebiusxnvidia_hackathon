# F1 evidence — REAL HARDWARE (owner's laptop, native Windows, integrated webcam)

Run by the owner on 2026-10-05 from `main`, with `uv run python scripts/...`. Reports are pasted verbatim.

## Camera properties
`cv2.VideoCapture(0)` reported 640 × 480. FPS = -1, meaning the backend does not report it (the capture meter measures it instead).

## 1-min capture — `scripts/spike_capture.py --uri 0 --minutes 1`
```
- source: webcam | duration: 1.0 min
- windows: 52, valid telemetry: 52 (100.0%) — gate >= 95%
- python heap growth after warm-up: 0.0% — gate <= 10%
- probe latency p95: 68.4 ms/frame (analytic 5 FPS)
- reconnects: 0, dropped frames: 0, ring buffer overwritten: 1713
- generated: 2026-10-05 18:30:59
```

## 30-min soak — `scripts/spike_capture.py --uri 0 --minutes 30`
```
- source: webcam | duration: 30.0 min
- windows: 1629, valid telemetry: 1629 (100.0%) — gate >= 95%
- python heap growth after warm-up: 0.4% — gate <= 10%
- probe latency p95: 109.7 ms/frame (analytic 5 FPS)
- reconnects: 0, dropped frames: 0, ring buffer overwritten: 53763
- generated: 2026-10-05 19:02:57
```
"Ring buffer overwritten" is expected: the camera delivers about 30 FPS and only 5 FPS are analysed. The buffer keeps the latest frames.

## Probe benchmark — `scripts/bench_probes.py` (synthetic 720p frames, same laptop)
```
720p probes: p50=13.5 ms  p95=20.5 ms (gate <= 40 ms)
```

## Open risk for F3
The live probe p95 (68 ms after 1 min, 110 ms after 30 min, at 640 × 480) is 3–5× the isolated benchmark. Probe latency is not an F1 gate, but F3 must explain this gap before it claims the ≤ 40 ms gate. Candidate causes (attributed in SIMULATION in `docs/evidence/f3/README.md`, "Probe latency": 1 is the largest factor, 2 compounds with it, the 640×480 frame being analysed without downscale adds ~50 %, 3 and 4 are untested):
1. `tracemalloc` is active during the spike, which slows every allocation.
2. GIL contention with the 30 FPS capture thread.
3. Geometry and ArUco cost more on real textured frames than on synthetic ones.
4. CPU throttling over long runs.

## Fault injection on a real clip — `scripts/spike_inject.py` (REAL HARDWARE clip, SIMULATION faults)
Recorded and replayed on the owner's laptop (native Windows, integrated webcam, 2026-10-06):
```
uv run python scripts/record_clip.py --uri 0 --seconds 90 --session s001
uv run python scripts/spike_inject.py --clip benchmarks/data/s001_clean.avi --session s001
```
Clip `s001`: 2692 frames, 27.28 FPS, 640×480, 0 read misses, sha256
`f0195d0b08a08d1d4d7c2362c3a2873e21f9ac4f9c1a0e564cc13e20e13c6e1b`. The clip stays local
(`benchmarks/data/` is git-ignored). Manifests: `benchmarks/manifests/f1-s001-{dark,gaussian_blur,freeze}.yaml`.

Faults: seeded (seed 42), frames [1091, 1909) = 40–70 s. Detection is local only (probes +
`IncidentTracker`), with no Nemotron calls and zero cost.

| injected | expected | confirmed (ranked) | delay s | pre-fault suspect windows | passed |
|---|---|---|---|---|---|
| none | - | - | - | 0/107 | True |
| dark | blackout | freeze, blackout | 2.89 | 0/107 | True |
| gaussian_blur | focus_drift | freeze, focus_drift | 2.89 | 0/107 | True |
| freeze | freeze | freeze | 2.89 | 0/107 | True |

Each degraded clip can be regenerated with `python -m benchmarks.make_degraded <manifest> <out.avi>`.
A dry run on a SIMULATION 640×480 clip did not show the spurious `freeze`.

### Open risk for F3 — spurious `freeze` on dark and blur
On the real clip, `dark` and `gaussian_blur` also confirm `freeze`, and `freeze` is ranked first.
All three faults are detected, so the F1 item holds. But a planner that trusts the top candidate
could pick `restart_capture` instead of the right action. Hypothesis, not yet verified: darkening or
blurring removes sensor noise, so consecutive frames fell under the then `freeze.temporal_mse_floor` (removed by ADR-005) and repeat
their perceptual hash. F3 must fix the rule's specificity, with an ADR and a benchmark report.
Thresholds are not changed here.

## File + RTSP through the same `CameraSource` (REAL HARDWARE)
The file variant runs in CI (`tests/integration/test_source_contract.py`). Webcam and RTSP variants
run when `RA_TEST_WEBCAM` / `RA_TEST_RTSP` are set; the RTSP run uses the phone (IP Webcam app,
Android) on the local Wi-Fi, URL `rtsp://<phone>:8080/h264_ulaw.sdp`.

RTSP 1-min capture on the owner's laptop (2026-10-07, `scripts/spike_capture.py --uri rtsp://... --minutes 1`):
```
source: rtsp | duration: 1.0 min
windows: 53, valid telemetry: 51 (96.2%) — gate >= 95%
python heap growth after warm-up: 1.6% — gate <= 10%
probe latency p95: 109.4 ms/frame (analytic 5 FPS)
reconnects: 0, dropped frames: 0, ring buffer overwritten: 1713
```
Both F1 capture gates hold over RTSP, with a thin margin on telemetry validity.

The contract test failed on the same stream (`assert f is not None` on the second read). Direct
probe with `cv2.VideoCapture`: 53/60 frames decodable over UDP, 41/60 over TCP
(`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`), with FFmpeg logging `non-existing PPS`,
`nal size exceeds length`, `decode_slice_header error`. TCP did not help, so the loss is in the
app's H.264 encoder/muxer, not in the network. Fix (this PR): `OpenCVSource` retries up to 3
undecodable frames on network sources and reports them as `decode_errors` in the transport
telemetry (`spike_capture.py` now prints them). Files and webcams are unchanged. The test itself
was not relaxed.

Rerun on the retry fix (2026-10-07, same phone, 640x480, audio disabled in the app):
```
source: rtsp | duration: 1.0 min
windows: 53, valid telemetry: 51 (96.2%) — gate >= 95%
python heap growth after warm-up: 0.0% — gate <= 10%
probe latency p95: 109.2 ms/frame (analytic 5 FPS)
reconnects: 0, dropped frames: 0, decode errors: 2, ring buffer overwritten: 1721
```
Only 2 undecodable frames in ~1770 reads once the stream is running, yet the contract test still
failed on `rtsp`. Every direct probe reported `first_fail 0`: the stream opens with a burst of
undecodable frames until the first parameter sets and keyframe arrive, longer than 3 retries.
Fix (second PR): `OpenCVSource.open` warms up network sources — discards frames until the first
decodable one, bounded by `warmup_timeout_s` (5 s; a stream that never yields a picture raises
`SourceError`, so the worker's reconnect/backoff path handles it). Warm-up frames are reported in
`warmup_frames` and `decode_errors`. Files and webcams do not warm up.

Side result: the app's MJPEG endpoint (`http://<phone>:8080/video`) decoded 60/60 frames in a direct
probe, but `OpenCVSource.open` on it raised `cannot open http source` after ~31 s right after the
RTSP soak; `open` is the same `cv2.VideoCapture(uri)` call for both schemes, so this points at the
app serving one video client at a time. HTTP/MJPEG is a diagnostic aid only: the F1 box requires RTSP.

Contract rerun on `main` with the warm-up fix (2026-10-08, same phone, 640x480, audio disabled; the
phone was first checked reachable with `Test-NetConnection <phone> -Port 8080` → `True`):
```
$env:RA_TEST_RTSP = "rtsp://<phone>:8080/h264_ulaw.sdp"
uv run pytest -q tests/integration/test_source_contract.py      → 2 passed in 16.73s
$env:RA_TEST_WEBCAM = "0"   # RA_TEST_RTSP still set: file + webcam + RTSP in one run
uv run pytest -q tests/integration/test_source_contract.py      → 2 passed in 6.24s
```
File, integrated webcam and phone RTSP are read through the same `CameraSource` interface and pass
the same contract. The box is closed on REAL HARDWARE; the test was not relaxed.

1-min RTSP capture in the same session:
```
source: rtsp | duration: 1.0 min
windows: 54, valid telemetry: 51 (94.4%) — gate >= 95%
python heap growth after warm-up: 0.1% — gate <= 10%
probe latency p95: 240.2 ms/frame (analytic 5 FPS)
reconnects: 0, dropped frames: 0, decode errors: 4, ring buffer overwritten: 1645
```
Not a pass at 1 min. `spike_capture.py` counts every 1-s window from the moment the worker starts
opening the source, so the RTSP handshake and the H.264 warm-up (up to `warmup_timeout_s` = 5 s)
fall inside the measured minute; a window with no frame yet is invalid, and each one weighs 1.85 %
of a 1-min run. The F1 validity box is defined on the 30-min webcam soak (1629/1629) and is
unaffected. Neither the gate threshold nor the script is changed.

10-min RTSP soak, same laptop and phone, same day (`uv run python scripts/spike_capture.py --uri
$env:RA_TEST_RTSP --minutes 10`):
```
source: rtsp | duration: 10.0 min
windows: 536, valid telemetry: 533 (99.4%) — gate >= 95%
python heap growth after warm-up: 1.6% — gate <= 10%
probe latency p95: 248.1 ms/frame (analytic 5 FPS)
reconnects: 0, dropped frames: 0, decode errors: 5, ring buffer overwritten: 17886
```
`capture-health.json`: `gate_pass: true`, `warmup_frames: 5`, `capture_fps: 30.083`,
`frame_age_ms_p95: 31.0`, `connect_attempt: 0`. PASS on REAL HARDWARE. The invalid windows stay at 3
for a 10× longer run, which is consistent with start-up windows (handshake + warm-up) rather than a
mid-stream fault; the script does not log per-window timestamps, so this is an inference. The probe p95 (240–248 ms vs 109 ms the day before on the same
laptop) is tracked against the F3 latency box (≤ 40 ms/frame at 720p).
