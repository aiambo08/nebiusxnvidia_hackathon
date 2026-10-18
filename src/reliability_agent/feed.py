"""Thread-safe telemetry and preview feed for the dashboard."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock

import cv2
import numpy as np

from reliability_agent.contracts.models import TelemetryWindow


class LiveFeed:
    MODES = frozenset({"SIMULATION", "REAL HARDWARE", "REPLAY"})

    def __init__(
        self,
        mode: str,
        source_label: str,
        scenario: str | None = None,
        max_windows: int = 300,
        jpeg_fps: float = 5.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {sorted(self.MODES)}")
        if max_windows <= 0:
            raise ValueError("max_windows must be > 0")
        if not math.isfinite(jpeg_fps) or jpeg_fps <= 0:
            raise ValueError("jpeg_fps must be a finite number > 0")
        self.mode = mode
        self.source_label = source_label
        self.scenario = scenario
        self.started_at = datetime.now(UTC).isoformat()
        self._clock = clock
        self._jpeg_interval = 1.0 / jpeg_fps
        self._last_encode_at = -math.inf
        self._frame_bytes: bytes | None = None
        self._frame_seq = 0
        self._windows: deque[dict] = deque(maxlen=max_windows)
        self._state: str | None = None
        self._last_window: dict | None = None
        self._lock = Lock()

    def on_frame(self, img: np.ndarray) -> None:
        with self._lock:
            now = self._clock()
            if now - self._last_encode_at < self._jpeg_interval:
                return
            self._last_encode_at = now
            if not isinstance(img, np.ndarray) or img.ndim < 2 or img.size == 0:
                return
            height, width = img.shape[:2]
            if width > 640:
                scaled_height = max(1, round(height * 640 / width))
                img = cv2.resize(img, (640, scaled_height), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(
                ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            if not ok:
                return
            self._frame_bytes = encoded.tobytes()
            self._frame_seq += 1

    def on_window(self, tw: TelemetryWindow, agent) -> None:
        visual = tw.visual
        state = str(agent.state)
        window = {
            "ts": (tw.window_start + timedelta(seconds=tw.window_seconds)).isoformat(),
            "state": state,
            "fps": tw.transport.capture_fps,
            "brightness": visual.brightness_p50,
            "blur": visual.blur_effect_p50,
            "occluded": visual.occluded_cell_ratio,
            "sharpness": getattr(visual, "sharpness_p50", None),
            "exact_repeat_ratio": visual.exact_repeat_ratio,
            "task_success": tw.task.success_rate,
        }
        incident = getattr(getattr(agent, "active", None), "incident", None)
        if incident is not None:
            window["faults"] = [str(fault) for fault in incident.candidate_faults]
        with self._lock:
            self._state = state
            self._last_window = window
            self._windows.append(window)

    def set_scenario(self, name: str) -> None:
        with self._lock:
            self.scenario = name

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "source_label": self.source_label,
                "scenario": self.scenario,
                "state": self._state,
                "last_window": dict(self._last_window) if self._last_window else None,
                "started_at": self.started_at,
            }

    def windows(self, n: int) -> list[dict]:
        with self._lock:
            if n <= 0:
                return []
            return [dict(window) for window in list(self._windows)[-n:]]

    def frame(self) -> tuple[bytes, int] | None:
        with self._lock:
            if self._frame_bytes is None:
                return None
            return self._frame_bytes, self._frame_seq
