"""Non-blocking capture worker with watchdog, reconnection (backoff + jitter) and metrics."""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np

from reliability_agent.capture.base import CameraSource, Frame, RingBuffer, now
from reliability_agent.contracts.models import TransportMetrics

log = logging.getLogger(__name__)


@dataclass
class BackoffPolicy:
    initial_s: float = 0.5
    max_s: float = 8.0
    jitter: float = 0.2

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        rng = rng or random.Random()  # noqa: S311 - not crypto
        base = min(self.max_s, self.initial_s * (2 ** max(0, attempt)))
        # jitter never pushes the delay past max_s, so the recovery bound is max_s + warm-up
        return min(self.max_s, max(0.0, base * (1 + rng.uniform(-self.jitter, self.jitter))))


class TransportMeter:
    """Transport-level health, reported separately from visual content (F2 gate)."""

    def __init__(self, horizon_s: float = 5.0) -> None:
        self.horizon_s = horizon_s
        self._lock = threading.Lock()
        self._arrivals: deque[float] = deque()
        self._ages: deque[tuple[float, float]] = deque()
        self.last_seq: int | None = None
        self.dropped = 0
        self.reconnects = 0
        self.decode_errors = 0
        self.connected = False
        self.last_frame_t: float | None = None

    def on_frame(self, frame: Frame, processed_at: float | None = None) -> None:
        t = processed_at if processed_at is not None else now()
        with self._lock:
            self._arrivals.append(frame.t_mono)
            self._ages.append((t, (t - frame.t_mono) * 1000.0))
            if self.last_seq is not None and frame.seq > self.last_seq + 1:
                self.dropped += frame.seq - self.last_seq - 1
            self.last_seq = frame.seq
            self.last_frame_t = frame.t_mono
            self._trim(t)

    def _trim(self, t: float) -> None:
        while self._arrivals and t - self._arrivals[0] > self.horizon_s:
            self._arrivals.popleft()
        while self._ages and t - self._ages[0][0] > self.horizon_s:
            self._ages.popleft()

    def frame_age_s(self, t: float | None = None) -> float:
        t = t if t is not None else now()
        return float("inf") if self.last_frame_t is None else t - self.last_frame_t

    def snapshot(self, t: float | None = None) -> TransportMetrics:
        t = t if t is not None else now()
        with self._lock:
            self._trim(t)
            n = len(self._arrivals)
            span = (self._arrivals[-1] - self._arrivals[0]) if n > 1 else 0.0
            ages = [a for _, a in self._ages]
        fps = (n - 1) / span if span > 0 else 0.0
        ages = ages or [self.frame_age_s(t) * 1000.0]
        age95 = float(np.percentile(ages, 95)) if np.isfinite(ages).all() else 1e9
        # a stale stream must show its staleness even if historical ages were small
        age95 = max(age95, min(1e9, self.frame_age_s(t) * 1000.0))
        return TransportMetrics(
            capture_fps=round(fps, 3),
            frame_age_ms_p95=round(age95, 2),
            dropped_frames=self.dropped,
            reconnect_count=self.reconnects,
            decode_errors=self.decode_errors,
            connected=self.connected,
        )


class CaptureWorker:
    """Reads a source in a background thread into a bounded ring buffer.

    Never blocks the caller: ``buffer``, ``meter`` and ``health()`` are safe to poll from the main
    thread while the worker is reconnecting. On failure it reconnects with exponential backoff
    and jitter. The loop body is :meth:`_step`, so tests can drive it deterministically with a
    fake clock instead of real threads.
    """

    def __init__(
        self,
        source: CameraSource,
        buffer_size: int = 64,
        frame_timeout_s: float = 5.0,
        backoff: BackoffPolicy | None = None,
        max_fps: float | None = None,
    ) -> None:
        self.source = source
        self.buffer = RingBuffer(buffer_size)
        self.meter = TransportMeter()
        self.frame_timeout_s = frame_timeout_s
        self.backoff = backoff or BackoffPolicy()
        self.max_fps = max_fps
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._thread: threading.Thread | None = None
        self._attempt = 0
        self._connected_at: float | None = None
        self._source_decode_errors = 0

    # -- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        try:
            self.source.close()
        except Exception:  # noqa: BLE001
            log.exception("error closing source")

    def request_restart(self) -> None:
        """Used by the ``restart_capture`` action. Non-blocking."""
        self._restart.set()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stale(self) -> bool:
        """No frame for ``frame_timeout_s``, counted from the last frame *or* the (re)connect,
        so a fresh session gets a grace period instead of inheriting the outage's staleness."""
        t = now()
        since_frame = self.meter.frame_age_s(t)
        if self._connected_at is not None:
            since_frame = min(since_frame, t - self._connected_at)
        return since_frame > self.frame_timeout_s

    def health(self) -> dict:
        """JSON-serialisable ingestion health for the API/dashboard. Never includes the URI."""
        age = self.meter.frame_age_s()
        return {
            "alive": self.alive,
            "connected": self.meter.connected,
            "stale": self.stale(),
            "source_kind": self.source.kind,
            "frame_age_s": None if age == float("inf") else round(age, 3),
            "connect_attempt": self._attempt,
            "warmup_frames": int(getattr(self.source, "warmup_frames", 0)),
            "buffer": {
                "size": len(self.buffer),
                "maxlen": self.buffer.maxlen,
                "overwritten": self.buffer.overwritten,
            },
            "transport": self.meter.snapshot().model_dump(),
        }

    # -- loop
    def _wait(self, seconds: float) -> None:
        """Sleep on the capture thread only; interrupted by ``stop()``. Tests fake the clock."""
        self._stop.wait(seconds)

    def _account_source_decode_errors(self) -> None:
        """Frames the source skipped internally (undecodable RTSP frames) are decode errors."""
        total = int(getattr(self.source, "decode_errors", 0))
        if total > self._source_decode_errors:
            self.meter.decode_errors += total - self._source_decode_errors
            self._source_decode_errors = total

    def _backoff(self, reason: str) -> None:
        delay = self.backoff.delay(self._attempt)
        self._attempt += 1
        log.warning("%s; retry in %.2fs", reason, delay)
        self._wait(delay)

    def _connect(self) -> bool:
        self._restart.clear()  # a restart asked for during an outage is satisfied by reconnecting
        try:
            self.source.open()
        except Exception as exc:  # noqa: BLE001 - cv2 raises plain errors on bad streams
            self.meter.connected = False
            self._backoff(f"connect failed ({exc})")
            return False
        self.meter.connected = True
        self._connected_at = now()
        return True

    def _disconnect(self, reason: str) -> None:
        """Close the source and back off before the next attempt. ``_attempt`` is reset only when
        a frame actually arrives, so a source that opens but never delivers cannot storm."""
        try:
            self.source.close()
        except Exception:  # noqa: BLE001
            log.exception("error closing source")
        self.meter.connected = False
        self.meter.reconnects += 1
        self._backoff(f"capture disconnect: {reason}")

    def _step(self, min_dt: float = 0.0) -> None:
        """One iteration of the capture loop; never raises."""
        if not self.source.is_open and not self._connect():
            return
        if self._restart.is_set():
            self._restart.clear()
            self._disconnect("restart requested")
            return
        t0 = now()
        try:
            frame = self.source.read()
        except Exception as exc:  # noqa: BLE001
            self._disconnect(f"read failed ({exc})")
            return
        self._account_source_decode_errors()
        if frame is None:
            self.meter.decode_errors += 1
            if self.stale():
                self._disconnect(f"watchdog: no frames for {self.frame_timeout_s:.1f}s")
            else:
                self._wait(0.01)
            return
        self._attempt = 0
        self.buffer.push(frame)
        self.meter.on_frame(frame)
        if min_dt:
            self._wait(max(0.0, min_dt - (now() - t0)))

    def _run(self) -> None:
        min_dt = 1.0 / self.max_fps if self.max_fps else 0.0
        while not self._stop.is_set():
            try:
                self._step(min_dt)
            except Exception:  # noqa: BLE001 - keep the thread alive; health() shows the outage
                log.exception("capture step failed")
                self._wait(self.backoff.delay(self._attempt))
