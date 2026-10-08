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
| Worst-case bound from config | `test_default_config_bounds_recovery_under_15s` | 8 s max backoff (jitter clamped at `max_backoff_s`) + 5 s network warm-up = 13 s < 15 s |
| Transport vs content | `test_frozen_but_connected_stream_is_transport_healthy` | frozen frames keep `connected=True`, classified as `freeze`, never `stream_down` |
| Ring buffer bounded | `tests/unit/test_capture.py::test_ring_buffer_is_bounded`, `test_ring_buffer_drain_and_maxlen` | overwrite counter, drain, maxlen |

## Independent review (Evaluation/Safety role, child session, 2026-10-08)
First pass: **DO NOT MERGE** with two blocking findings, both fixed in this PR with regression tests:

| Finding | Fix | Regression test |
|---|---|---|
| A `SourceError` from `read()` on an open source caused an unbounded zero-delay reconnect storm (1 M opens/s): `open()` reset the attempt counter and the read-failure path never waited | Every disconnect backs off (`_disconnect` → `_backoff`); `_attempt` is reset only when a frame arrives | `test_reconnect_storm_is_bounded_by_backoff[read_raises/read_none/open_raises_runtime]` (< 1 open per `initial_backoff_s` over 600 simulated s) |
| Watchdog had no grace period after a (re)connect: `stale()` counted from the previous session's last frame, so an empty first read after `open()` tore the session down forever | `stale()` counts from `max(last_frame, connected_at)` | `test_first_read_none_after_reconnect_gets_a_grace_period` |

Non-blocking findings also fixed: exceptions other than `SourceError` from `open()/read()/close()`
no longer kill the capture thread (`test_non_source_errors_do_not_kill_the_capture_thread`);
`TransportMeter` is locked so `snapshot()`/`health()` from the main thread cannot hit "deque mutated
during iteration" (`test_meter_snapshot_is_safe_while_frames_arrive`); a restart requested during
an outage is satisfied by the reconnect instead of tearing down the fresh session
(`test_restart_requested_during_outage_does_not_tear_down_the_new_session`); the `max_fps`
throttle runs on the fake clock; `redact_uri` also hides `?user=…&password=…&token=…` query
credentials. Residual risks recorded below.

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

Second pass at `57b65ec`: **MERGE**, 6/7 conditions PROVEN (the contract-suite box stays open for
the owner's hardware). Reviewer adversarial runs: read-error storm 1,012,079 → 2 opens/s; empty first
read after a 30 s outage now recovers; exceptions other than `SourceError` and a raising `close()` no
longer kill the thread; 0 errors polling `snapshot()`/`health()` concurrently; `stop()` returns in
0.3 ms during an 8 s backoff. Non-blocking findings fixed in the follow-up PR (code only, configs unchanged): the jittered
backoff delay is clamped at `max_backoff_s` (worst-case resume 14.6 s → 13 s,
`test_backoff_jitter_never_exceeds_max_delay`); `redact_uri` uses `urllib.parse` (query without a
path, `passwd`/`access_token`, percent-encoded keys, fragments). Still open by design: a source that delivers one frame per session reconnects every ~5.5 s without escalating backoff.

Semantics note: `health()["stale"]` is the **watchdog** view — it is `False` during the grace period
right after a (re)connect even if no frame has arrived yet. Fault detection must use
`health()["transport"]["frame_age_ms_p95"]` (what `classify_window` consumes), which does report the
real staleness.

## Residual risks (reviewer + author)
- All resilience evidence is SIMULATION. Real RTSP recovery adds the FFmpeg handshake (up to ~30 s
  seen on the owner's phone when the host is unreachable) and a possibly hanging `read()`; neither
  is bounded by the 15 s derivation. To be measured on the owner's hardware with
  `scripts/spike_capture.py` once the phone is reachable.
- `stream_down` is raised per window in < 5 s; a *confirmed* incident needs
  `fusion.enter_windows` consecutive windows, so the FSM reacts ~3 windows later by design.
- The non-blocking test uses a 50 ms main-thread poll bound on a shared CI runner.

## Contract suite on the owner's hardware (REAL HARDWARE, 2026-10-08)
- Phone over RTSP: `$env:RA_TEST_RTSP = "rtsp://<phone>:8080/h264_ulaw.sdp"; uv run pytest -q tests/integration/test_source_contract.py` → `2 passed`.
- Integrated webcam, with `RA_TEST_RTSP` still set (file + webcam + RTSP in one run):
  `$env:RA_TEST_WEBCAM = "0"; uv run pytest -q tests/integration/test_source_contract.py` → `2 passed`.
  Details and the 1-min RTSP capture in `docs/evidence/f1/README.md`.
- Still open on hardware: real RTSP recovery time after a phone-side outage (see residual risks).

Reviewer confirmation pass on this follow-up (SIMULATION, 694-outage sweep): worst resume 12.97 s with maximum
jitter, 13.00 s with random jitter, delay never above 8.0 s; every earlier `redact_uri` leak is masked.
Known gap: credentials embedded in the *path* (`rtsp://host/user=admin&password=x&...sdp`, seen on cheap IP
cameras) are not masked — the URI is never logged or exported, so the exposure is limited to `repr()`.
