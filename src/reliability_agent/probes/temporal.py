"""Temporal probes: freeze and short-loop detection.

A near-zero frame difference may be a genuinely static scene. Real sensors add noise, so a
*bit-exact* repeat is strong evidence of a frozen pipeline. Perceptual hashes catch repeats
after re-encoding and detect loops of period 2..N.

Whether repeats are a freeze or a static scene is decided per frame, without history: a live
sensor adds fresh noise every frame, so its frame-to-frame (temporal) noise is of the same order
as the noise baked into one frame (spatial, Immerkaer's estimator on flat regions). A frozen
pipeline keeps the spatial noise but loses the temporal one (ADR-005).
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from reliability_agent.probes.base import ProbeResult


def dhash(gray: np.ndarray, size: int = 8) -> int:
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(sum(1 << i for i, b in enumerate(bits) if b))


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
_IMMERKAER_SCALE = float(np.sqrt(np.pi / 2) / 6.0)
MIN_SPATIAL_SIGMA = 0.05  # below this the frame carries no measurable noise (dark, blurred)


def noise_ratio(gray: np.ndarray, prev: np.ndarray) -> float:
    """Temporal-to-spatial noise ratio of a frame pair, NaN when the frame carries no measurable
    noise. Both estimates use the flattest half of the frame (gradient magnitude at or below its
    median) so texture and edges do not count as noise. The temporal sigma is the RMS of the
    frame difference divided by sqrt(2) (two independent noise draws); the spatial sigma is
    Immerkaer's Laplacian estimator. Live: ~1 (0.7-1.9 with codec and gain effects). Frozen: ~0.
    Motion raises the ratio, so it can only make a window look more alive, never frozen."""
    g = gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)[1:-1, 1:-1]
    flat = mag <= float(np.median(mag))
    if not flat.any():
        return float("nan")
    lap = cv2.filter2D(g, cv2.CV_32F, _IMMERKAER)[1:-1, 1:-1]
    sigma_s = _IMMERKAER_SCALE * float(np.mean(np.abs(lap[flat])))
    if sigma_s < MIN_SPATIAL_SIGMA:
        return float("nan")
    d = (g - prev.astype(np.float32))[1:-1, 1:-1]
    sigma_t = float(np.sqrt(np.mean(d[flat] ** 2) / 2.0))
    return sigma_t / sigma_s


class FreezeTracker:
    def __init__(self, window: int = 10, max_loop_period: int = 8, hash_tol: int = 0,
                 loop_mse_max: float = 0.5) -> None:
        self.window = window
        self.max_loop_period = max_loop_period
        self.hash_tol = hash_tol
        self.loop_mse_max = loop_mse_max
        self._prev: np.ndarray | None = None
        self._prev_full: np.ndarray | None = None
        self._frames: deque[np.ndarray] = deque(maxlen=2 * max_loop_period)
        self._hashes: deque[int] = deque(maxlen=max(window, 2 * max_loop_period + 1))
        self._exact: deque[bool] = deque(maxlen=window)
        self._mse: deque[float] = deque(maxlen=window)

    def update(self, gray: np.ndarray) -> ProbeResult:
        small = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        h = dhash(small)
        if self._prev is not None and self._prev.shape == small.shape:
            diff = small.astype(np.int16) - self._prev.astype(np.int16)
            mse = float(np.mean(diff.astype(np.float32) ** 2))
            self._mse.append(mse)
            self._exact.append(mse == 0.0)
        ratio = float("nan")
        if self._prev_full is not None and self._prev_full.shape == gray.shape:
            ratio = noise_ratio(gray, self._prev_full)
        self._prev = small
        self._prev_full = gray.copy()
        self._frames.append(small)
        self._hashes.append(h)
        hs = list(self._hashes)
        rep = [hamming(a, b) <= self.hash_tol for a, b in zip(hs, hs[1:], strict=False)]
        recent = rep[-self.window :] if rep else []
        res = ProbeResult(
            "temporal",
            values={
                "temporal_mse": float(self._mse[-1]) if self._mse else float("nan"),
                "repeated_hash_ratio": float(np.mean(recent)) if recent else 0.0,
                "exact_repeat_ratio": float(np.mean(self._exact)) if self._exact else 0.0,
                "loop_period": float(self._loop_period()),
                "noise_ratio": ratio,
            },
        )
        if len(self._exact) < 2:
            res.quality = "unknown"
            res.unknown_reason = "warming up"
        return res

    def _loop_period(self) -> int:
        """Smallest p in [2, max] such that frame[t-i] ~= frame[t-i-p] for i < p while consecutive
        frames differ: either pixel MSE below the loop floor with real motion between frames, or a
        bit-exact period (a replayed buffer) on frames that merely differ by noise. A live static
        scene has consecutive frames that are equal up to noise but never bit-exact across a
        period, so it is never reported as a loop; a bit-exact repeat of one frame is a freeze,
        not a loop."""
        fr = list(self._frames)

        def mse(a: np.ndarray, b: np.ndarray) -> float:
            return float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))

        for p in range(2, self.max_loop_period + 1):
            if len(fr) < 2 * p:
                break
            tail = fr[-2 * p :]
            period = [mse(tail[i], tail[i + p]) for i in range(p)]
            step = [mse(tail[i], tail[i + 1]) for i in range(p)]
            if all(d <= self.loop_mse_max for d in period) and all(d > self.loop_mse_max
                                                                   for d in step):
                return p
            if all(d == 0.0 for d in period) and all(d > 0.0 for d in step):
                return p
        return 0
