"""Grid-based occlusion probe (single-value metrics per cell, cf. DLR partial obstruction).

A cell is 'occluded' when it is nearly uniform and edge-less. If baseline cell statistics are
provided, a cell that lost most of its texture *relative to its own baseline* also counts —
this avoids flagging naturally blank walls.
"""

from __future__ import annotations

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult


def cell_stats(gray: np.ndarray, grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    rows, cols = grid
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    out = np.zeros((rows, cols, 3), np.float32)  # mean, std, edge density
    for r in range(rows):
        for c in range(cols):
            ys, ye = r * h // rows, (r + 1) * h // rows
            xs, xe = c * w // cols, (c + 1) * w // cols
            cell = gray[ys:ye, xs:xe]
            e = edges[ys:ye, xs:xe]
            out[r, c] = (cell.mean(), cell.std(), np.count_nonzero(e) / max(1, e.size))
    return out


def occlusion_probe(
    gray: np.ndarray,
    grid: tuple[int, int] = (8, 8),
    baseline_cells: np.ndarray | None = None,
    std_max: float = 6.0,
    edge_max: float = 0.01,
    texture_drop: float = 0.8,
) -> ProbeResult:
    stats = cell_stats(gray, grid)
    uniform = (stats[..., 1] < std_max) & (stats[..., 2] < edge_max)
    if baseline_cells is not None and baseline_cells.shape == stats.shape:
        # Only cells that had texture in the baseline can be judged; blank walls are excluded.
        textured_before = baseline_cells[..., 1] >= std_max
        base_std = np.maximum(baseline_cells[..., 1], 1e-3)
        lost = ((stats[..., 1] / base_std) < (1 - texture_drop)) & (stats[..., 2] < edge_max)
        occluded = (uniform | lost) & textured_before
    else:
        occluded = uniform
    return ProbeResult(
        "occlusion",
        values={"occluded_cell_ratio": float(occluded.mean())},
        evidence={"uniform_cells": float(uniform.sum())},
    )
