"""Sharpness probes.

- Laplacian variance: cheap, but scene-texture dependent -> only relative to baseline.
- Edge density (Canny): used to tell low-texture scenes from blur.
- ``blur_effect``: Crete-Roffet et al. 2007 perceptual no-reference blur metric
  (0 = sharp, 1 = maximally blurred). Re-blur the image and measure how much
  neighbour differences drop; an already-blurred image changes little.
"""

from __future__ import annotations

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult

LOW_TEXTURE_EDGE_DENSITY = 0.002


def laplacian_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def edge_density(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, 50, 150)
    return float(np.count_nonzero(edges) / edges.size)


def blur_effect(gray: np.ndarray, h_size: int = 11) -> float:
    img = gray.astype(np.float64) / 255.0
    scores = []
    for axis, ksize in ((0, (1, h_size)), (1, (h_size, 1))):
        blurred = cv2.blur(img, ksize)  # ksize=(w,h): (1,h) blurs vertically (axis 0)
        d_sharp = np.abs(np.diff(img, axis=axis))
        d_blur = np.abs(np.diff(blurred, axis=axis))
        t = np.maximum(0.0, d_sharp - d_blur)
        sl = (slice(2, -1), slice(2, -1))
        m1 = float(d_sharp[sl].sum())
        m2 = float(t[sl].sum())
        scores.append(1.0 if m1 <= 1e-12 else abs(m1 - m2) / m1)
    return float(max(scores))


def sharpness_probe(gray: np.ndarray, h_size: int = 11) -> ProbeResult:
    ed = edge_density(gray)
    res = ProbeResult(
        "sharpness",
        values={
            "laplacian_variance": laplacian_variance(gray),
            "edge_density": ed,
            "blur_effect": blur_effect(gray, h_size),
        },
    )
    if ed < LOW_TEXTURE_EDGE_DENSITY:
        res.quality = "low_texture"
        res.unknown_reason = "too few edges to judge focus (dark, occluded or blank scene)"
    return res
