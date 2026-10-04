"""Camera source abstraction. Webcam, file and RTSP must pass the same contract suite (F2)."""

from __future__ import annotations

import abc
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray            # BGR uint8
    seq: int                     # monotonically increasing per source session
    t_mono: float                # time.monotonic() at capture (local clock)
    t_source: float | None = None  # source timestamp (ms) if provided, never mixed with t_mono


@dataclass
class SourceCapabilities:
    """What the device lets us change. Actions are only offered if supported."""

    exposure: bool = False
    exposure_range: tuple[float, float] | None = None
    autofocus: bool = False
    profiles: list[str] = field(default_factory=list)
    restartable: bool = True

    def as_list(self) -> list[str]:
        caps = []
        if self.exposure:
            caps.append("exposure")
        if self.autofocus:
            caps.append("autofocus")
        if self.profiles:
            caps.append("profiles")
        if self.restartable:
            caps.append("restart")
        return caps


class SourceError(RuntimeError):
    pass


class CameraSource(abc.ABC):
    """Synchronous source. Wrap with :class:`CaptureWorker` for non-blocking capture."""

    kind: str = "abstract"

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def read(self) -> Frame | None:
        """Return the next frame, or None on a transient failure. Raise SourceError if closed."""

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    @abc.abstractmethod
    def is_open(self) -> bool: ...

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities()

    def get_settings(self) -> dict:
        return {}

    def apply_settings(self, settings: dict) -> None:  # pragma: no cover - adapter specific
        raise NotImplementedError


class RingBuffer:
    """Bounded, thread-safe buffer: old frames are dropped, memory never grows."""

    def __init__(self, maxlen: int) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be > 0")
        self._q: deque[Frame] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.overwritten = 0

    def push(self, frame: Frame) -> None:
        with self._lock:
            if len(self._q) == self._q.maxlen:
                self.overwritten += 1
            self._q.append(frame)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._q[-1] if self._q else None

    def drain(self) -> list[Frame]:
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)

    @property
    def maxlen(self) -> int:
        return self._q.maxlen or 0


def now() -> float:
    return time.monotonic()
