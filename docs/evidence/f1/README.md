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

## Fault injection on a real clip — pending (tooling in place)
Reproduce on the owner's laptop (native Windows, repo root):
```
uv run python scripts/record_clip.py --uri 0 --seconds 90 --session s001
uv run python scripts/spike_inject.py --clip benchmarks/data/s001_clean.avi --session s001
```
- The clip is REAL HARDWARE and stays local (`benchmarks/data/` is git-ignored); only its SHA-256 is
  published in the manifests `benchmarks/manifests/f1-s001-*.yaml`.
- Faults are SIMULATION: seeded `dark` (0.95), `gaussian_blur` (0.8), `freeze`, frames 40–70 s.
  A negative control (clean clip) must raise no incident.
- Detection is local only (probes + `IncidentTracker`), no Nemotron calls, zero cost.
- Each degraded clip can be regenerated with `python -m benchmarks.make_degraded <manifest> <out.avi>`.
- Dry run on a SIMULATION 640×480 clip (CI box): 4/4 runs pass, detection delay 2.8–4.8 s,
  0 suspect windows before onset.

## File + RTSP through the same `CameraSource` — pending
The file variant runs in CI (`tests/integration/test_source_contract.py`). Webcam and RTSP variants
run when `RA_TEST_WEBCAM` / `RA_TEST_RTSP` are set; the RTSP run uses the phone (IP Webcam app)
on the local network.
