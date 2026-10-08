"""Gate F2 resilience tests, deterministic: the worker loop is driven step by step with a fake
clock, so "< 5 s" and "< 15 s" are measured on the simulated timeline, not on CI wall time.
The one real-thread test checks that reconnecting never blocks the caller."""

import json
import threading
import time

import numpy as np
import pytest

from reliability_agent.capture import (
    BackoffPolicy,
    CaptureWorker,
    Frame,
    OpenCVSource,
    RingBuffer,
    SourceCapabilities,
)
from reliability_agent.capture import worker as worker_mod
from reliability_agent.capture.base import CameraSource, SourceError
from reliability_agent.capture.sources import redact_uri
from reliability_agent.contracts.models import FaultType
from reliability_agent.incidents.fusion import classify_window
from tests.conftest import make_window


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ScriptedNetworkSource(CameraSource):
    """Looks like an RTSP source: ``up=False`` makes reads return None and open() fail."""

    kind = "rtsp"

    def __init__(self, clock) -> None:
        self.clock = clock
        self.up = True
        self.open_calls = 0
        self.n = 0
        self.decode_errors = 0
        self._open = False

    def open(self) -> None:
        self.open_calls += 1
        if not self.up:
            raise SourceError("cannot open rtsp source")
        self._open = True

    def read(self) -> Frame | None:
        if not self._open:
            raise SourceError("source not open")
        if not self.up:
            return None
        self.n += 1
        return Frame(np.zeros((2, 2, 3), np.uint8), self.n, self.clock())

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(worker_mod, "now", c)
    return c


def _worker(src, clock, cfg):
    cam = cfg["camera"]
    rc = cam["reconnect"]
    w = CaptureWorker(src, cam["ring_buffer_size"], cam["frame_age_timeout_s"],
                      BackoffPolicy(rc["initial_backoff_s"], rc["max_backoff_s"], rc["jitter"]))
    w._wait = clock.advance  # sleeping advances the simulated clock instead of blocking
    return w


def _run_healthy(w, clock, seconds: float, fps: float = 10.0) -> None:
    for _ in range(int(seconds * fps)):
        w._step()
        clock.advance(1.0 / fps)


def _stream_down(w, cfg) -> bool:
    tw = make_window(transport=w.meter.snapshot().model_dump())
    faults, _ = classify_window(tw, None, cfg["faults"])
    return FaultType.STREAM_DOWN in faults


def test_simulated_rtsp_disconnect_detected_under_5s(clock, cfg):
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    _run_healthy(w, clock, 3.0)
    assert w.meter.connected and not _stream_down(w, cfg)
    src.up = False
    t_down = clock.t
    detected_at = None
    while clock.t - t_down < 5.0:
        w._step()
        if _stream_down(w, cfg):
            detected_at = clock.t - t_down
            break
    assert detected_at is not None and detected_at < 5.0, "stream_down must be raised in < 5 s"
    # the watchdog then drops the dead connection and starts reconnecting with backoff
    while clock.t - t_down < 6.0:
        w._step()
    assert w.meter.reconnects == 1 and not w.meter.connected
    assert src.open_calls >= 2 and w.health()["connect_attempt"] >= 1


def test_default_config_bounds_recovery_under_15s(cfg):
    """Worst case: the stream returns right after a failed attempt at maximum backoff, then the
    source still has to warm up. The configured values must leave that sum below the gate."""
    rc = cfg["camera"]["reconnect"]
    worst_backoff = rc["max_backoff_s"] * (1 + rc["jitter"])
    warmup = OpenCVSource("rtsp://cam/live").warmup_timeout_s
    assert worst_backoff + warmup < 15.0


@pytest.mark.parametrize("outage_s", [0.5, 4.0, 12.0, 30.0, 95.0])
def test_telemetry_resumes_under_15s_after_stream_returns(clock, cfg, outage_s):
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    _run_healthy(w, clock, 2.0)
    src.up = False
    t_down = clock.t
    while clock.t - t_down < outage_s:
        w._step()
    src.up = True
    t_back = clock.t
    last_seq = w.meter.last_seq
    while w.meter.last_seq == last_seq and clock.t - t_back < 20.0:
        w._step()
    assert w.meter.last_seq > last_seq, "no telemetry after the stream returned"
    assert clock.t - t_back < 15.0
    assert w.meter.connected and not w.stale()
    snap = w.meter.snapshot()
    assert snap.connected and snap.dropped_frames == 0


def test_reconnect_resets_backoff_and_counts_once_per_outage(clock, cfg):
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    _run_healthy(w, clock, 1.0)
    for _ in range(3):
        src.up = False
        t_down = clock.t
        while clock.t - t_down < 30.0:
            w._step()
        attempts_during_outage = w._attempt
        assert attempts_during_outage >= 2
        src.up = True
        while w._attempt:
            w._step()
        assert w.meter.connected
    assert w.meter.reconnects == 3


class BlockingOpenSource(ScriptedNetworkSource):
    """A connect that hangs (RTSP handshake timeout) must only stall the capture thread."""

    def __init__(self, clock, block_s: float) -> None:
        super().__init__(clock)
        self.block_s = block_s

    def open(self) -> None:
        self.open_calls += 1
        time.sleep(self.block_s)
        raise SourceError("rtsp connect timed out")


def test_reconnection_never_blocks_the_main_thread():
    src = BlockingOpenSource(time.monotonic, block_s=0.4)
    w = CaptureWorker(src, buffer_size=4, backoff=BackoffPolicy(0.05, 0.05, 0.0))
    w.start()
    t_end = time.monotonic() + 1.0
    polls = 0
    worst_ms = 0.0
    while time.monotonic() < t_end:
        t0 = time.perf_counter()
        w.buffer.latest()
        snap = w.meter.snapshot()
        health = w.health()
        worst_ms = max(worst_ms, (time.perf_counter() - t0) * 1000)
        polls += 1
        assert snap.connected is False and health["connected"] is False
        time.sleep(0.01)
    w.stop()
    assert src.open_calls >= 2, "worker kept retrying in the background"
    assert polls >= 20 and worst_ms < 50.0, f"main thread stalled: {worst_ms:.1f} ms"
    assert threading.active_count() >= 1 and not w.alive


def test_frozen_but_connected_stream_is_transport_healthy(clock, cfg):
    """Frozen content keeps arriving: transport says connected, content detection is separate."""
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    _run_healthy(w, clock, 3.0)
    snap = w.meter.snapshot()
    assert snap.connected and snap.frame_age_ms_p95 < 1000 and not _stream_down(w, cfg)
    tw = make_window(transport=snap.model_dump(),
                     visual={"exact_repeat_ratio": 1.0, "temporal_mse_p50": 0.0})
    faults, _ = classify_window(tw, None, cfg["faults"])
    assert FaultType.FREEZE in faults and FaultType.STREAM_DOWN not in faults


def test_read_error_on_open_source_counts_as_disconnect(clock, cfg):
    class BrokenRead(ScriptedNetworkSource):
        def read(self):
            raise SourceError("device lost")

    src = BrokenRead(clock)
    w = _worker(src, clock, cfg)
    w._step()  # connects, read raises -> treated as a disconnect, not a crash
    assert w.meter.reconnects == 1 and not w.meter.connected and not src.is_open
    w._step()  # reconnects and fails again: still bounded, never raises
    assert w.meter.reconnects == 2 and src.open_calls == 2


def test_restart_request_is_honoured_before_reading(clock, cfg):
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    _run_healthy(w, clock, 0.5)
    w.request_restart()
    w._step()
    assert w.meter.reconnects == 1 and not src.is_open
    w._step()
    assert src.is_open and w.meter.connected


def test_health_is_json_serialisable_and_has_no_uri(clock, cfg):
    src = ScriptedNetworkSource(clock)
    w = _worker(src, clock, cfg)
    h0 = w.health()
    assert h0["frame_age_s"] is None and h0["stale"] and not h0["connected"]
    _run_healthy(w, clock, 1.0)
    h = w.health()
    text = json.dumps(h)
    assert "rtsp://" not in text and "uri" not in h
    assert h["connected"] and h["source_kind"] == "rtsp" and h["buffer"]["maxlen"] == 64
    assert h["transport"]["capture_fps"] > 0 and h["frame_age_s"] is not None


def test_start_is_idempotent_and_stop_survives_close_errors():
    class NoisyClose(ScriptedNetworkSource):
        def close(self):
            raise RuntimeError("device already gone")

    src = NoisyClose(time.monotonic)
    w = CaptureWorker(src, buffer_size=4, max_fps=200)
    w.start()
    first = w._thread
    w.start()
    assert w._thread is first
    time.sleep(0.1)
    w.stop()  # must not raise even though close() does
    assert not w.alive


def test_transport_meter_trims_old_samples():
    m = worker_mod.TransportMeter(horizon_s=1.0)
    for i in range(50):
        m.on_frame(Frame(np.zeros((1, 1, 3), np.uint8), i, i * 0.1), processed_at=i * 0.1)
    assert len(m._arrivals) <= 11 and len(m._ages) <= 11
    assert m.snapshot(t=4.9).capture_fps > 0
    assert m.frame_age_s(t=10.0) == pytest.approx(5.1)


def test_ring_buffer_drain_and_maxlen():
    rb = RingBuffer(3)
    assert rb.maxlen == 3 and rb.latest() is None
    for i in range(5):
        rb.push(Frame(np.zeros((1, 1, 3), np.uint8), i, float(i)))
    drained = rb.drain()
    assert [f.seq for f in drained] == [2, 3, 4]
    assert len(rb) == 0 and rb.drain() == []


def test_source_capabilities_as_list():
    assert SourceCapabilities().as_list() == ["restart"]
    full = SourceCapabilities(exposure=True, autofocus=True, profiles=["main"], restartable=False)
    assert full.as_list() == ["exposure", "autofocus", "profiles"]


def test_base_source_defaults(clock):
    src = ScriptedNetworkSource(clock)
    assert src.capabilities().restartable and src.get_settings() == {}


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("rtsp://admin:s3cret@192.168.1.50:554/live", "rtsp://***@192.168.1.50:554/live"),
        ("rtsp://user:p@ss@cam/live", "rtsp://***@cam/live"),
        ("http://10.0.0.2:8080/video", "http://10.0.0.2:8080/video"),
        ("rtsps://a:b@host", "rtsps://***@host"),
        ("clip.avi", "clip.avi"),
        (0, "0"),
    ],
)
def test_redact_uri_hides_credentials(uri, expected):
    assert redact_uri(uri) == expected


def test_opencv_source_repr_and_settings_never_leak_credentials():
    src = OpenCVSource("rtsp://admin:s3cret@cam/live")
    assert "s3cret" not in repr(src) and "***@cam" in repr(src)
    assert src.capabilities().restartable
    assert src.get_settings() == {"safe_mode": False, "profile": "main"}
    src.apply_settings({"safe_mode": True})
    assert src.get_settings()["safe_mode"] is True
    with pytest.raises(NotImplementedError):
        src.apply_settings({"exposure": 1.0})
    src.close()  # closing a never-opened source is a no-op
    assert not src.is_open
