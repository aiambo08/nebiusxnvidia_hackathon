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
The live probe p95 (68 ms after 1 min, 110 ms after 30 min, at 640 × 480) is 3–5× the isolated benchmark. Probe latency is not an F1 gate, but F3 must explain this gap before it claims the ≤ 40 ms gate. Candidate causes, none verified yet:
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
blurring removes sensor noise, so consecutive frames fall under `freeze.temporal_mse_floor` and repeat
their perceptual hash. F3 must fix the rule's specificity, with an ADR and a benchmark report.
Thresholds are not changed here.

## File + RTSP through the same `CameraSource` — pending
The file variant runs in CI (`tests/integration/test_source_contract.py`). Webcam and RTSP variants
run when `RA_TEST_WEBCAM` / `RA_TEST_RTSP` are set; the RTSP run uses the phone (IP Webcam app)
on the local network.
