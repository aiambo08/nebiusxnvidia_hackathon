import random
import time

import numpy as np
import pytest

from reliability_agent.capture import (
    BackoffPolicy,
    CaptureWorker,
    Frame,
    RingBuffer,
    SyntheticSource,
    TransportMeter,
)


def _frame(seq, t):
    return Frame(np.zeros((2, 2, 3), np.uint8), seq, t)


def test_ring_buffer_is_bounded():
    rb = RingBuffer(5)
    for i in range(100):
        rb.push(_frame(i, float(i)))
    assert len(rb) == 5
    assert rb.overwritten == 95
    assert rb.latest().seq == 99
    with pytest.raises(ValueError):
        RingBuffer(0)


def test_backoff_grows_and_is_capped():
    b = BackoffPolicy(initial_s=0.5, max_s=4.0, jitter=0.0)
    assert [b.delay(i) for i in range(6)] == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]
    bj = BackoffPolicy(initial_s=1.0, max_s=8.0, jitter=0.2)
    d = bj.delay(0, random.Random(1))
    assert 0.8 <= d <= 1.2


def test_transport_meter_fps_drops_and_staleness():
    m = TransportMeter(horizon_s=10)
    for i in range(31):
        f = _frame(i if i < 20 else i + 3, i / 30.0)  # 3 dropped frames
        m.on_frame(f, processed_at=i / 30.0 + 0.01)
    snap = m.snapshot(t=1.0 + 0.01)
    assert 29 <= snap.capture_fps <= 31
    assert snap.dropped_frames == 3
    stale = m.snapshot(t=10.0)
    assert stale.frame_age_ms_p95 > 8000


def test_worker_captures_without_blocking_and_reconnects():
    src = SyntheticSource(width=160, height=120)
    w = CaptureWorker(src, buffer_size=8, frame_timeout_s=0.3,
                      backoff=BackoffPolicy(0.05, 0.1, 0.0), max_fps=100)
    t0 = time.monotonic()
    w.start()
    assert time.monotonic() - t0 < 0.5  # start() is non-blocking
    time.sleep(0.3)
    assert len(w.buffer) > 0 and len(w.buffer) <= 8
    src.set_fault("disconnect")
    time.sleep(0.8)
    assert w.meter.reconnects >= 1  # watchdog detected the stall
    src.set_fault(None)
    seq_before = w.meter.last_seq
    time.sleep(0.5)
    assert w.meter.last_seq > seq_before  # telemetry resumed
    w.stop()
    assert not w.alive


def test_restart_request_counts_as_reconnect():
    src = SyntheticSource(width=160, height=120)
    w = CaptureWorker(src, buffer_size=4, max_fps=100)
    w.start()
    time.sleep(0.15)
    w.request_restart()
    time.sleep(0.2)
    assert w.meter.reconnects == 1
    assert len(w.buffer) > 0
    w.stop()
