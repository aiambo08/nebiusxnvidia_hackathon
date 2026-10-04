"""Run all probes on analysed frames and aggregate them into TelemetryWindow objects."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np

from reliability_agent.capture.base import Frame
from reliability_agent.contracts.models import (
    GeometryMetrics,
    TaskMetrics,
    TelemetryWindow,
    TransportMetrics,
    VisualMetrics,
)
from reliability_agent.probes.base import downscale, to_gray
from reliability_agent.probes.geometry import GeometryProbe
from reliability_agent.probes.occlusion import cell_stats, occlusion_probe
from reliability_agent.probes.photometric import exposure_probe
from reliability_agent.probes.sharpness import sharpness_probe
from reliability_agent.probes.temporal import FreezeTracker
from reliability_agent.tasks.marker import MarkerTask


def _p(values: list[float], q: float) -> float | None:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.percentile(vals, q)) if vals else None


class ProbeRunner:
    def __init__(self, cfg: dict[str, Any], task: MarkerTask | None = None) -> None:
        p = cfg["probes"]
        self.cfg = p
        self.grid = tuple(p["grid"])
        self.freeze = FreezeTracker(p["freeze_window"], p["max_loop_period"])
        g = p["geometry"]
        self.geometry = GeometryProbe(g["orb_features"], g["min_matches"], g["ransac_reproj_px"])
        self.geometry_every = g["every_n_frames"]
        self.task = task or MarkerTask()
        self.baseline_cells: np.ndarray | None = None
        self._n = 0
        self._last_geom: dict[str, float] = {}
        self._geom_quality = "no_reference"

    @staticmethod
    def _normalised(gray: np.ndarray) -> np.ndarray:
        """Brightness-normalised copy so texture probes are not fooled by a dim scene."""
        m = float(gray.mean())
        if m < 1.0:
            return gray
        return np.clip(gray.astype(np.float32) * (128.0 / m), 0, 255).astype(np.uint8)

    def calibrate_reference(self, frame: Frame) -> None:
        gray = downscale(to_gray(frame.image))
        self.geometry.set_reference(cv2.equalizeHist(gray))
        self.baseline_cells = cell_stats(self._normalised(gray), self.grid)

    def analyse(self, frame: Frame) -> dict[str, float]:
        gray = downscale(to_gray(frame.image))
        self._n += 1
        out: dict[str, float] = {}
        out.update(exposure_probe(gray, self.cfg["black_level"], self.cfg["white_level"]).values)
        out.update(sharpness_probe(gray, self.cfg["blur_kernel"]).values)
        out.update(self.freeze.update(gray).values)
        out.update(occlusion_probe(self._normalised(gray), self.grid, self.baseline_cells).values)
        if self._n % self.geometry_every == 1 or self.geometry_every == 1:
            g = self.geometry.measure(cv2.equalizeHist(gray))
            self._last_geom, self._geom_quality = g.values, g.quality
        out.update({f"geom_{k}": v for k, v in self._last_geom.items()})
        t = self.task.run(gray)
        out.update({f"task_{k}": v for k, v in t.values.items()})
        return out


class WindowAggregator:
    """Collect per-frame metrics for one window and emit a TelemetryWindow."""

    def __init__(self, camera_id: str, window_seconds: float) -> None:
        self.camera_id = camera_id
        self.window_seconds = window_seconds
        self._rows: dict[str, list[float]] = defaultdict(list)
        self._n = 0
        self._start = datetime.now(UTC)

    def add(self, metrics: dict[str, float]) -> None:
        self._n += 1
        for k, v in metrics.items():
            self._rows[k].append(v)

    def emit(self, transport: TransportMetrics, geometry_quality: str = "ok") -> TelemetryWindow:
        r = self._rows
        loop = [int(x) for x in r.get("loop_period", []) if x]
        visual = VisualMetrics(
            brightness_p50=_p(r["brightness"], 50),
            contrast_p50=_p(r["contrast"], 50),
            black_pixel_ratio=_p(r["black_pixel_ratio"], 50),
            white_pixel_ratio=_p(r["white_pixel_ratio"], 50),
            laplacian_variance_p50=_p(r["laplacian_variance"], 50),
            blur_effect_p50=_p(r["blur_effect"], 50),
            edge_density_p50=_p(r["edge_density"], 50),
            temporal_mse_p50=_p(r["temporal_mse"], 50),
            repeated_hash_ratio=_p(r["repeated_hash_ratio"], 50),
            exact_repeat_ratio=_p(r["exact_repeat_ratio"], 50),
            loop_period=max(set(loop), key=loop.count) if loop else None,
            occluded_cell_ratio=_p(r["occluded_cell_ratio"], 50),
        )
        geometry = GeometryMetrics(
            match_count=int(v) if (v := _p(r["geom_match_count"], 50)) is not None else None,
            homography_inlier_ratio=_p(r["geom_homography_inlier_ratio"], 50),
            translation_px=_p(r["geom_translation_px"], 50),
            rotation_deg=_p(r["geom_rotation_deg"], 50),
            quality=geometry_quality,
        )
        task = TaskMetrics(
            success_rate=_p(r["task_success"], 50) if not r["task_success"] else float(
                np.mean(r["task_success"])
            ),
            confidence_p50=_p(r["task_confidence"], 50),
            latency_ms_p95=_p(r["task_latency_ms"], 95),
        )
        tw = TelemetryWindow(
            camera_id=self.camera_id,
            window_start=self._start,
            window_seconds=self.window_seconds,
            frames_analyzed=self._n,
            transport=transport,
            visual=visual,
            geometry=geometry,
            task=task,
        )
        self._rows.clear()
        self._n = 0
        self._start = datetime.now(UTC)
        return tw
