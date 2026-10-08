# F2 evidence — ingestion & observability

All results below are **SIMULATION** (scripted sources, fake clock) unless marked REAL HARDWARE.
Gate thresholds come from `configs/default.yaml` (`camera.frame_age_timeout_s`,
`camera.reconnect.*`, `faults.stream_down.frame_age_ms_min`); none was changed.

## How the resilience gates are measured
`CaptureWorker` now exposes its loop body as `_step()`; `tests/unit/test_capture_resilience.py`
drives it with a fake monotonic clock (`worker.now` patched, `_wait` advances the clock), so the
"< 5 s" and "< 15 s" bounds are measured on the simulated timeline and do not depend on CI speed.

| Gate condition | Test | Result |
|---|---|---|
| Disconnect detected < 5 s | `test_simulated_rtsp_disconnect_detected_under_5s` | `stream_down` raised by `incidents.fusion.classify_window` once `frame_age_ms_p95` ≥ 3000 ms (≈3.0 s after the last frame); watchdog closes and reconnects at 5 s |
| Reconnection does not block the main process | `test_reconnection_never_blocks_the_main_thread` (real thread) | `open()` hangs 0.4 s and fails repeatedly on the capture thread; ≥ 20 main-thread polls of `buffer`, `meter.snapshot()` and `health()` in 1 s, worst poll < 50 ms |
| Telemetry resumes < 15 s | `test_telemetry_resumes_under_15s_after_stream_returns[0.5/4/12/30/95 s outages]` | first frame after return always < 15 s on the simulated clock |
| Worst-case bound from config | `test_default_config_bounds_recovery_under_15s` | 8 s max backoff × (1 + 0.2 jitter) + 5 s network warm-up = 14.6 s < 15 s |
| Transport vs content | `test_frozen_but_connected_stream_is_transport_healthy` | frozen frames keep `connected=True`, classified as `freeze`, never `stream_down` |
| Ring buffer bounded | `tests/unit/test_capture.py::test_ring_buffer_is_bounded`, `test_ring_buffer_drain_and_maxlen` | overwrite counter, drain, maxlen |

## Coverage of `reliability_agent.capture`
CI step: `pytest tests/unit/test_capture.py tests/unit/test_capture_resilience.py
tests/unit/test_opencv_source.py tests/integration/test_source_contract.py --cov=reliability_agent.capture
--cov-report=json:coverage-capture.json` then `python scripts/check_coverage.py coverage-capture.json
--min-lines 80 --min-branches 75` (fails the job below the gate; `--cov-fail-under` only checks the
combined figure). Sandbox run (Linux, py3.11): **lines 96.1%, branches 90.8%**. Before this PR the
CI step measured 80.2% lines / 57.4% branches and did not fail on it.

## Health export
`CaptureWorker.health()` returns a JSON-serialisable dict (connection, staleness, attempts, warm-up
frames, buffer occupancy, `TransportMetrics`). It never includes the stream URI; `OpenCVSource`'s
`repr` redacts embedded credentials (`rtsp://***@host/...`, `test_redact_uri_hides_credentials`).
`scripts/spike_capture.py` writes it to `spikes/capture-health.json` next to the markdown report.

## Still open (needs the owner's hardware)
- Contract suite on the integrated webcam: `$env:RA_TEST_WEBCAM = "0"; uv run pytest -q tests/integration/test_source_contract.py`
- Contract suite on the phone over RTSP: `$env:RA_TEST_RTSP = "rtsp://<phone>:8080/h264_ulaw.sdp"; uv run pytest -q tests/integration/test_source_contract.py`
  (last attempt on 2026-10-08 failed before `open()` because the phone was unreachable; see `docs/evidence/f1/README.md`).
