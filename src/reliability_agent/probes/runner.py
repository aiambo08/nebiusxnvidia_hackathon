"""Run all probes on analysed frames and aggregate them into TelemetryWindow objects."""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, wait
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
from reliability_agent.probes.base import ProbeResult, downscale, median, to_gray
from reliability_agent.probes.geometry import GeometryProbe
from reliability_agent.probes.occlusion import (
    cell_slices,
    cell_stats,
    normalise_brightness,
    occlusion_probe,
)
from reliability_agent.probes.photometric import exposure_probe
from reliability_agent.probes.sharpness import sharpness_probe
from reliability_agent.probes.temporal import FreezeTracker
from reliability_agent.tasks.marker import MarkerTask

_POOL: ThreadPoolExecutor | None = None
_POOL_PID: int | None = None
_POOL_LOCK = threading.Lock()


def _geometry_pool() -> ThreadPoolExecutor:
    """Process-wide pool for the geometry probe; recreated in a forked child (dead threads)."""
    global _POOL, _POOL_PID
    with _POOL_LOCK:
        if _POOL is None or _POOL_PID != os.getpid():
            _POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ra-geometry")
            _POOL_PID = os.getpid()
        return _POOL


def _p(values: list[float], q: float) -> float | None:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.percentile(vals, q)) if vals else None


class ProbeRunner:
    def __init__(self, cfg: dict[str, Any], task: MarkerTask | None = None) -> None:
        p = cfg["probes"]
        self.cfg = p
        self.grid = tuple(p["grid"])
        self.freeze = FreezeTracker(p["freeze_window"], p["max_loop_period"],
                                    loop_mse_max=p["loop_mse_max"])
        g = p["geometry"]
        self.geometry = GeometryProbe(g["orb_features"], g["min_matches"], g["ransac_reproj_px"])
        self.geometry_every = g["every_n_frames"]
        self.geometry_parallel = bool(g.get("parallel", True))
        self.task = task or MarkerTask()
        self.occlusion_cfg: dict[str, float] = dict(p.get("occlusion", {}))
        self.baseline_cells: np.ndarray | None = None
        self.calibration_cfg: dict[str, float] = dict(p.get("occlusion_calibration", {}))
        self._cal_open: np.ndarray | None = None
        self._cal_prev: np.ndarray | None = None
        self._cal_seq: int | None = None
        self._cal_still = np.zeros(self.grid, np.int32)
        self._cal_stats: list[np.ndarray] = []
        self._cal_rest: list[np.ndarray] = []
        self._n = 0
        self._geom_stale = False
        self._last_geom: dict[str, float] = {}
        self._geom_quality = "no_reference"

    def calibrate_reference(self, frame: Frame) -> None:
        """Set the geometry reference now; start the per-cell occlusion calibration (ADR-008).

        A frame is not a baseline by itself: whatever moves through it (a person walking by)
        would be learned as the scene. A cell adopts its baseline once it has been still for
        ``rest_frames`` consecutive frames (median of those frames' statistics). A textured
        adoption is final; an untextured one stays unjudgeable until ``max_frames`` and is then
        replaced by the median over every frame in which the cell was at rest, so a foreground
        that rested there briefly (a uniform or a textured person) is outvoted by the scene.
        Cells never at rest stay NaN (not judged) unless most cells never rested, or without them
        too few cells could be judged (a noisy, vibrating or flickering camera, where textured
        cells are exactly the ones that never look still); then they adopt the median of all
        frames, so occlusion is never left disabled by calibration.
        """
        gray = downscale(to_gray(frame.image))
        self.geometry.set_reference(cv2.equalizeHist(gray))
        self.baseline_cells = np.full((*self.grid, 3), np.nan, np.float32)
        self._cal_open = np.ones(self.grid, bool)
        self._cal_prev = None
        self._cal_seq = None
        self._cal_still[:] = 0
        self._cal_stats = []
        self._cal_rest = []
        self._calibrate_cells(gray, frame.seq)

    @property
    def occlusion_calibrating(self) -> bool:
        return self._cal_open is not None and bool(self._cal_open.any())

    @property
    def occlusion_calibrated_ratio(self) -> float:
        if self.baseline_cells is None:
            return 0.0
        return float((~np.isnan(self.baseline_cells[..., 1])).mean())

    def _calibrate_cells(self, gray: np.ndarray, seq: int) -> None:
        if not self.occlusion_calibrating or seq == self._cal_seq:
            return
        c = self.calibration_cfg
        rest = int(c.get("rest_frames", 10))
        self._cal_seq = seq
        norm = normalise_brightness(gray)
        self._cal_stats.append(cell_stats(norm, self.grid))
        self._cal_rest.append(np.zeros(self.grid, bool))
        if self._cal_prev is not None and self._cal_prev.shape == norm.shape:
            delta = cv2.absdiff(norm, self._cal_prev)
            noise = 1.4826 * float(median(delta))
            moving = delta > max(c.get("pixel_delta", 25), c.get("noise_k", 4.0) * noise)
            for r, col, sl in cell_slices(norm.shape, self.grid):
                still = moving[sl].mean() <= c.get("moving_fraction_max", 0.01)
                self._cal_still[r, col] = self._cal_still[r, col] + 1 if still else 0
        self._cal_prev = norm
        ready = self._cal_open & (self._cal_still >= rest)
        if ready.any():
            for m in self._cal_rest[-rest:]:
                m |= ready
            new = ready & np.isnan(self.baseline_cells[..., 1])
            self.baseline_cells[new] = np.median(np.stack(self._cal_stats[-rest:]), axis=0)[new]
            textured = self.baseline_cells[..., 1] >= self.occlusion_cfg.get("std_max", 6.0)
            self._cal_open &= ~(new & textured)
        if len(self._cal_stats) >= c.get("max_frames", 150):
            self._finish_calibration()

    def _finish_calibration(self) -> None:
        stats, at_rest = np.stack(self._cal_stats), np.stack(self._cal_rest)
        rested = self._cal_open & at_rest.any(axis=0)
        if rested.any():
            masked = np.where(at_rest[..., None], stats, np.nan)[:, rested]
            self.baseline_cells[rested] = np.nanmedian(masked, axis=0)
        never = np.isnan(self.baseline_cells[..., 1])
        judgeable = self.baseline_cells[..., 1] >= self.occlusion_cfg.get("std_max", 6.0)
        if never.any() and (never.mean() > self.calibration_cfg.get("global_fallback_min", 0.5)
                            or judgeable.mean() < self.occlusion_cfg.get("judgeable_min", 0.25)):
            self.baseline_cells[never] = np.median(stats, axis=0)[never]
        self._cal_open[:] = False
        self._cal_stats, self._cal_rest, self._cal_prev = [], [], None

    def set_geometry_reference(self, frame: Frame) -> bool:
        """Replace only the geometry reference (occlusion calibration is left running).
        False, and the old reference kept, if the frame has too few features."""
        ok = self.geometry.set_reference(cv2.equalizeHist(downscale(to_gray(frame.image))))
        self._geom_stale = self._geom_stale or ok
        return ok

    def analyse(self, frame: Frame) -> dict[str, float]:
        """Per-frame metrics. The geometry probe (ORB + RANSAC, the costliest stage) runs on a
        pool thread while the other probes run here (OpenCV releases the GIL); its result is
        awaited before returning, so the output is the same as running it in sequence."""
        gray = downscale(to_gray(frame.image))
        self._n += 1
        geom: Future[ProbeResult] | None = None
        if self._n % self.geometry_every == 1 or self.geometry_every == 1 or self._geom_stale:
            self._geom_stale = False
            eq = cv2.equalizeHist(gray)
            if self.geometry_parallel:
                geom = _geometry_pool().submit(self.geometry.measure, eq)
            else:
                self._publish_geometry(self.geometry.measure(eq))
        out: dict[str, float] = {}
        try:
            out.update(exposure_probe(gray, self.cfg["black_level"],
                                      self.cfg["white_level"]).values)
            out.update(sharpness_probe(gray, self.cfg["blur_kernel"]).values)
            out.update(self.freeze.update(gray).values)
            if self.baseline_cells is not None:
                self._calibrate_cells(gray, frame.seq)
            occ = occlusion_probe(gray, self.grid, self.baseline_cells,
                                  white_level=self.cfg["white_level"],
                                  calibrating=self.occlusion_calibrating, **self.occlusion_cfg)
            out.update(occ.values)
            t = self.task.run(gray)
        finally:
            if geom is not None:  # never leave the probe running into the next call
                wait([geom])
        if geom is not None:
            self._publish_geometry(geom.result())
        out.update({f"geom_{k}": v for k, v in self._last_geom.items()})
        out.update({f"task_{k}": v for k, v in t.values.items()})
        return out

    def _publish_geometry(self, g: ProbeResult) -> None:
        self._last_geom, self._geom_quality = g.values, g.quality


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
            noise_ratio_p50=_p(r["noise_ratio"], 50),
            temporal_sigma_p50=_p(r["temporal_sigma"], 50),
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
