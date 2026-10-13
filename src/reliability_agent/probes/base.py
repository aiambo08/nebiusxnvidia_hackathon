"""Common probe result type. Every probe reports value, quality and why it may be unknown."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class ProbeResult:
    name: str
    values: dict[str, float] = field(default_factory=dict)
    quality: str = "ok"            # ok | low_texture | no_reference | failed | unknown
    unknown_reason: str | None = None
    evidence: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.quality == "ok"


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def median(a: np.ndarray) -> float:
    """``np.median`` with one single-pivot partition instead of two pivots (several times faster
    on a full frame, same value); NaN for an empty array or one that contains NaN."""
    v = a.ravel()
    n = v.size
    if n == 0 or (v.dtype.kind == "f" and np.isnan(v).any()):
        return np.float64("nan") if n == 0 else np.array(np.nan, dtype=v.dtype)[()]
    k = n // 2
    part = np.partition(v, k)
    if n % 2:
        return np.mean(part[k : k + 1])
    return np.mean(np.array([part[:k].max(), part[k]], dtype=v.dtype))


def downscale(gray: np.ndarray, max_side: int = 640) -> np.ndarray:
    h, w = gray.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return gray
    f = max_side / s
    return cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
