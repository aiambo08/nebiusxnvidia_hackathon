"""Grid-based occlusion probe against the camera's own baseline cells (ADR-007).

Each cell is compared with the same cell at calibration. A cell counts as occluded when
(a) it is nearly uniform and edge-less (lens cap, tape), or (b) it lost its edges relative to
its baseline and either its brightness moved by at least `mean_shift_min` baseline standard
deviations or its texture collapsed (std ratio below ``1 - texture_drop``); (b) catches textured
occluders such as a hand, which are not uniform. Only cells that carried texture at calibration
and are not clipped white in the current frame are judged, so blank walls are never counted and
an occlusion that co-occurs with overexposure stays visible. When every judgeable cell lost its
edges but kept its contrast and its brightness (median over judgeable cells), the frame is a
global defocus, not an occlusion: the ratio is 0 and ``global_texture_loss`` is 1. Defocus keeps
cell means; an occluder moves them.
Thresholds live in ``configs/default.yaml`` (``probes.occlusion``).
"""

from __future__ import annotations

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult


def normalise_brightness(gray: np.ndarray) -> np.ndarray:
    """Brightness-normalised copy so texture statistics are not fooled by a dim or bright scene."""
    m = float(gray.mean())
    if m < 1.0:
        return gray
    return np.clip(gray.astype(np.float32) * (128.0 / m), 0, 255).astype(np.uint8)


def cell_slices(shape: tuple[int, int], grid: tuple[int, int]):
    rows, cols = grid
    h, w = shape
    for r in range(rows):
        for c in range(cols):
            yield r, c, (slice(r * h // rows, (r + 1) * h // rows),
                         slice(c * w // cols, (c + 1) * w // cols))


def cell_stats(gray: np.ndarray, grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    """Per cell: mean, std, edge density — on a brightness-normalised image."""
    edges = cv2.Canny(gray, 50, 150)
    out = np.zeros((*grid, 3), np.float32)
    for r, c, sl in cell_slices(gray.shape, grid):
        cell, e = gray[sl], edges[sl]
        out[r, c] = (cell.mean(), cell.std(), np.count_nonzero(e) / max(1, e.size))
    return out


def clipped_cells(gray: np.ndarray, grid: tuple[int, int], white_level: int) -> np.ndarray:
    """Cells where most pixels are clipped white in the *raw* frame; they cannot be judged."""
    out = np.zeros(grid, bool)
    for r, c, sl in cell_slices(gray.shape, grid):
        out[r, c] = (gray[sl] >= white_level).mean() > 0.5
    return out


def occlusion_probe(
    gray: np.ndarray,
    grid: tuple[int, int] = (8, 8),
    baseline_cells: np.ndarray | None = None,
    *,
    white_level: int = 240,
    std_max: float = 6.0,
    edge_max: float = 0.01,
    texture_drop: float = 0.8,
    edge_loss_ratio_max: float = 0.25,
    mean_shift_min: float = 1.0,
    global_loss_ratio_min: float = 0.75,
    judgeable_min: float = 0.25,
    calibrating: bool = False,
) -> ProbeResult:
    """`gray` is the raw probe input frame; normalisation happens here.

    NaN rows in `baseline_cells` are cells not calibrated yet (ADR-008); they are never judged.
    """
    stats = cell_stats(normalise_brightness(gray), grid)
    uniform = (stats[..., 1] < std_max) & (stats[..., 2] < edge_max)
    if baseline_cells is None or baseline_cells.shape != stats.shape:
        return ProbeResult("occlusion", values={"occluded_cell_ratio": float(uniform.mean()),
                                                "judgeable_cell_ratio": 1.0,
                                                "global_texture_loss": 0.0},
                           quality="no_reference", evidence={"uniform_cells": float(uniform.sum())})
    clipped = clipped_cells(gray, grid, white_level)
    judgeable = (baseline_cells[..., 1] >= std_max) & ~clipped
    n = int(judgeable.sum())
    judgeable_ratio = n / judgeable.size
    if judgeable_ratio < judgeable_min:
        return ProbeResult("occlusion", values={"occluded_cell_ratio": 0.0,
                                                "judgeable_cell_ratio": judgeable_ratio,
                                                "global_texture_loss": 0.0},
                           quality="unknown",
                           unknown_reason=("calibrating" if calibrating
                                           else "too_few_judgeable_cells"),
                           evidence={"clipped_cells": float(clipped.sum())})
    base_std = np.maximum(baseline_cells[..., 1], 1e-3)
    base_edges = np.maximum(baseline_cells[..., 2], 1e-3)
    std_ratio = stats[..., 1] / base_std
    edges_lost = (stats[..., 2] / base_edges) < edge_loss_ratio_max
    mean_shift = np.abs(stats[..., 0] - baseline_cells[..., 0]) / base_std
    changed = edges_lost & ((mean_shift >= mean_shift_min) | (std_ratio < 1 - texture_drop))
    occluded = judgeable & (uniform | changed)
    global_loss = bool(edges_lost[judgeable].mean() >= global_loss_ratio_min
                       and float(np.median(std_ratio[judgeable])) >= 1 - texture_drop
                       and float(np.median(mean_shift[judgeable])) < mean_shift_min)
    ratio = 0.0 if global_loss else float(occluded.sum() / n)
    return ProbeResult(
        "occlusion",
        values={"occluded_cell_ratio": ratio, "judgeable_cell_ratio": judgeable_ratio,
                "global_texture_loss": float(global_loss)},
        evidence={"uniform_cells": float(uniform.sum()), "changed_cells": float(changed.sum()),
                  "clipped_cells": float(clipped.sum())},
    )
