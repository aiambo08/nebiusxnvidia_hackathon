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
