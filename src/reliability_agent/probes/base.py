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


def downscale(gray: np.ndarray, max_side: int = 640) -> np.ndarray:
    h, w = gray.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return gray
    f = max_side / s
    return cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
