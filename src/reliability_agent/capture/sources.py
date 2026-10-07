"""Concrete sources: OpenCV (webcam/file/RTSP) and a deterministic synthetic source."""

from __future__ import annotations

import math

import cv2
import numpy as np

from reliability_agent.capture.base import (
    CameraSource,
    Frame,
    SourceCapabilities,
    SourceError,
    now,
)


def parse_uri(uri: str | int) -> str | int:
    if isinstance(uri, int):
        return uri
    return int(uri) if str(uri).isdigit() else str(uri)


NETWORK_SCHEMES = ("rtsp://", "rtsps://", "http://", "https://")


class OpenCVSource(CameraSource):
    """Webcam index, video file or rtsp:// / http:// URL through ``cv2.VideoCapture``.

    Network streams (phone apps, IP cameras) deliver some frames FFmpeg cannot decode: lost or
    reordered packets, truncated NAL units. ``cv2.VideoCapture.read`` returns ``(False, None)``
    for each of them. For network sources ``read`` retries up to ``read_retries`` times before
    reporting a transient failure, and counts every skipped frame in ``decode_errors`` so the
    transport telemetry stays honest. Files and webcams never retry.
    """

    def __init__(self, uri: str | int, *, loop_file: bool = False, read_retries: int = 3) -> None:
        self.uri = parse_uri(uri)
        self.loop_file = loop_file
        self.read_retries = max(0, int(read_retries))
        self.decode_errors = 0
        self._cap: cv2.VideoCapture | None = None
        self._seq = 0
        # logical settings only; real UVC/ONVIF imaging controls arrive with Phase-7 adapters
        self.settings: dict = {"safe_mode": False, "profile": "main"}
        lower = str(self.uri).lower()
        if isinstance(self.uri, int):
            self.kind = "webcam"
        elif lower.startswith(("rtsp://", "rtsps://")):
            self.kind = "rtsp"
        elif lower.startswith(("http://", "https://")):
            self.kind = "http"
        else:
            self.kind = "file"

    @property
    def is_network(self) -> bool:
        return self.kind in ("rtsp", "http")

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.uri)
        if not self._cap.isOpened():
            self._cap = None
            raise SourceError(f"cannot open {self.kind} source")

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> Frame | None:
        if self._cap is None:
            raise SourceError("source not open")
        ok, img = self._cap.read()
        for _ in range(self.read_retries if self.is_network else 0):
            if ok and img is not None:
                break
            self.decode_errors += 1
            ok, img = self._cap.read()
        if not ok or img is None:
            if self.kind == "file" and self.loop_file:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, img = self._cap.read()
            if not ok or img is None:
                return None
        self._seq += 1
        pos_ms = self._cap.get(cv2.CAP_PROP_POS_MSEC)
        return Frame(img, self._seq, now(), pos_ms if pos_ms > 0 else None)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None

    def capabilities(self) -> SourceCapabilities:
        # Real capability discovery per device is a Phase-7 task (UVC/ONVIF adapters).
        return SourceCapabilities(restartable=True)

    def get_settings(self) -> dict:
        return dict(self.settings)

    def apply_settings(self, settings: dict) -> None:
        unknown = set(settings) - set(self.settings)
        if unknown:
            raise NotImplementedError(f"device does not support {sorted(unknown)}")
        self.settings.update(settings)


class SyntheticSource(CameraSource):
    """Deterministic textured scene with sensor noise and a reference ArUco marker.

    Used for unit tests, the offline demo and as a reproducible benchmark source. Exposes
    simulated controls (exposure, autofocus, profile) so the executor can be tested without
    hardware. Faults can be injected with ``set_fault``.
    """

    kind = "synthetic"

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        seed: int = 0,
        marker_id: int = 7,
        noise_sigma: float = 2.0,
        clock=None,
    ) -> None:
        self.clock = clock or now
        self.w, self.h = width, height
        self.seed = seed
        self.noise_sigma = noise_sigma
        self._rng = np.random.default_rng(seed)
        self._seq = 0
        self._open = False
        self._last: np.ndarray | None = None
        self.settings = {"exposure": 0.0, "focus_ok": True, "profile": "main", "safe_mode": False}
        self.fault: str | None = None
        self.fault_strength: float = 1.0
        self._background = self._make_background()
        d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self._msize = max(24, int(min(width, height) * 0.15))
        self._marker = cv2.aruco.generateImageMarker(d, marker_id, self._msize)

    def _make_background(self) -> np.ndarray:
        rng = np.random.default_rng(self.seed + 1)
        img = np.full((self.h, self.w, 3), 120, np.uint8)
        for _ in range(60):
            x, y = int(rng.integers(0, self.w)), int(rng.integers(0, self.h))
            r = int(rng.integers(5, 40))
            color = tuple(int(c) for c in rng.integers(30, 230, 3))
            if rng.random() < 0.5:
                cv2.circle(img, (x, y), r, color, -1)
            else:
                cv2.rectangle(img, (x, y), (x + r, y + r // 2), color, -1)
        for x in range(0, self.w, 40):
            cv2.line(img, (x, 0), (x, self.h), (90, 90, 90), 1)
        return img

    # -- CameraSource API
    def open(self) -> None:
        self._open = True

    @property
    def is_open(self) -> bool:
        return self._open

    def close(self) -> None:
        self._open = False

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            exposure=True,
            exposure_range=(-2.0, 2.0),
            autofocus=True,
            profiles=["main", "sub"],
            restartable=True,
        )

    def get_settings(self) -> dict:
        return dict(self.settings)

    def apply_settings(self, settings: dict) -> None:
        self.settings.update(settings)

    def set_fault(self, fault: str | None, strength: float = 1.0) -> None:
        self.fault = fault
        self.fault_strength = strength
        if fault == "defocus":
            self.settings["focus_ok"] = False

    def read(self) -> Frame | None:
        if not self._open:
            raise SourceError("source not open")
        if self.fault == "disconnect":
            return None
        if self.fault == "freeze" and self._last is not None:
            self._seq += 1
            return Frame(self._last.copy(), self._seq, self.clock(), None)
        img = self._render()
        self._last = img
        self._seq += 1
        return Frame(img, self._seq, self.clock(), None)

    def _render(self) -> np.ndarray:
        img = self._background.copy()
        t = self._seq / 10.0
        # moving object so the scene is not static
        cx = int(self.w * 0.5 + self.w * 0.3 * math.sin(t))
        cv2.circle(img, (cx, int(self.h * 0.8)), 25, (20, 200, 240), -1)
        # reference marker with white quiet zone
        ms, q = self._msize, max(4, self._msize // 9)
        mx, my = q + 4, q + 4
        img[my - q : my + ms + q, mx - q : mx + ms + q] = 255
        img[my : my + ms, mx : mx + ms] = cv2.cvtColor(self._marker, cv2.COLOR_GRAY2BGR)
        if self.settings.get("profile") == "sub":
            small = cv2.resize(img, (self.w // 2, self.h // 2), interpolation=cv2.INTER_AREA)
            img = cv2.resize(small, (self.w, self.h), interpolation=cv2.INTER_LINEAR)
        # exposure in EV-like stops, combined with fault-induced darkening
        gain = 2.0 ** float(self.settings.get("exposure", 0.0))
        if self.fault == "dark":
            gain *= max(0.02, 1.0 - 0.95 * self.fault_strength)
        if self.fault == "overexpose":
            gain *= 1.0 + 4.0 * self.fault_strength
        out = img.astype(np.float32) * gain
        if not self.settings.get("focus_ok", True):
            k = int(9 + 20 * self.fault_strength) | 1
            out = cv2.GaussianBlur(out, (k, k), 0)
        if self.fault == "occlude":
            frac = min(1.0, 0.5 * self.fault_strength + 0.2)
            out[:, : int(self.w * frac)] = 12.0
        if self.fault == "shift":
            m = np.float32([[1, 0, 60 * self.fault_strength], [0, 1, 30 * self.fault_strength]])
            out = cv2.warpAffine(out, m, (self.w, self.h), borderMode=cv2.BORDER_REFLECT)
        out += self._rng.normal(0, self.noise_sigma, out.shape).astype(np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)
