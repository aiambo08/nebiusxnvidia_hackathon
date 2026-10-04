"""Photometric probes: brightness, contrast, clipping (blackout / overexposure)."""

from __future__ import annotations

import numpy as np

from reliability_agent.probes.base import ProbeResult


def exposure_probe(gray: np.ndarray, black_level: int = 16, white_level: int = 240) -> ProbeResult:
    n = gray.size
    if n == 0:
        return ProbeResult("exposure", quality="failed", unknown_reason="empty frame")
    return ProbeResult(
        "exposure",
        values={
            "brightness": float(gray.mean()),
            "contrast": float(gray.std()),
            "black_pixel_ratio": float(np.count_nonzero(gray <= black_level) / n),
            "white_pixel_ratio": float(np.count_nonzero(gray >= white_level) / n),
        },
    )
