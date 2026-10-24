"""Downstream reference task: ArUco marker detection.

Cheap, deterministic, needs no training and is sensitive to blur, darkness, occlusion and
FOV shift — exactly the faults we want to recover from. It plays the role of the
"downstream application" in task-aware camera maintenance (Wischow et al.). Swap for a real
detector (e.g. an NVIDIA TAO/DeepStream model) behind the same interface later.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult


class MarkerTask:
    name = "reference_marker_detection"

    def __init__(self, expected_ids: set[int] | None = None, dictionary: int | None = None,
                 timer: Callable[[], float] = time.perf_counter):
        d = cv2.aruco.getPredefinedDictionary(
            dictionary if dictionary is not None else cv2.aruco.DICT_4X4_50
        )
        self.detector = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
        self.expected_ids = expected_ids or {7}
        # Simulated runs pass their simulated clock: host CPU jitter must not reach the
        # task.latency_ms_p95 verification guard of a simulated device.
        self.timer = timer

    def run(self, gray: np.ndarray) -> ProbeResult:
        t0 = self.timer()
        corners, ids, _ = self.detector.detectMarkers(gray)
        latency = (self.timer() - t0) * 1000
        found = set() if ids is None else {int(i) for i in ids.flatten()}
        hit = bool(self.expected_ids & found)
        conf = 0.0
        if hit and ids is not None:
            idx = [i for i, v in enumerate(ids.flatten()) if int(v) in self.expected_ids][0]
            pts = corners[idx].reshape(-1, 2).astype(np.int32)
            x, y, w, h = cv2.boundingRect(pts)
            roi = gray[max(0, y) : y + h, max(0, x) : x + w]
            # contrast of the marker region as a confidence proxy in [0, 1]
            conf = float(min(1.0, roi.std() / 100.0)) if roi.size else 0.0
        return ProbeResult(
            "task",
            values={"success": 1.0 if hit else 0.0, "confidence": conf, "latency_ms": latency},
        )
