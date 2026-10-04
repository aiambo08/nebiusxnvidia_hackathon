"""Temporal probes: freeze and short-loop detection.

A near-zero frame difference may be a genuinely static scene. Real sensors add noise, so a
*bit-exact* repeat is strong evidence of a frozen pipeline. Perceptual hashes catch repeats
after re-encoding and detect loops of period 2..N.
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


class FreezeTracker:
    def __init__(self, window: int = 10, max_loop_period: int = 8, hash_tol: int = 0,
                 loop_mse_max: float = 0.5) -> None:
        self.window = window
        self.max_loop_period = max_loop_period
        self.hash_tol = hash_tol
        self.loop_mse_max = loop_mse_max
        self._prev: np.ndarray | None = None
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
        self._prev = small
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
            },
        )
        if len(self._exact) < 2:
            res.quality = "unknown"
            res.unknown_reason = "warming up"
        return res

    def _loop_period(self) -> int:
        """Smallest p in [2, max] such that frame[t-i] ~= frame[t-i-p] for i < p (pixel MSE
        below the sensor-noise floor) while consecutive frames differ. A static scene has
        consecutive frames that are equal up to noise, so it is never reported as a loop."""
        fr = list(self._frames)

        def mse(a: np.ndarray, b: np.ndarray) -> float:
            return float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))

        for p in range(2, self.max_loop_period + 1):
            if len(fr) < 2 * p:
                break
            tail = fr[-2 * p :]
            if all(mse(tail[i], tail[i + p]) <= self.loop_mse_max for i in range(p)) and all(
                mse(tail[i], tail[i + 1]) > self.loop_mse_max for i in range(p)
            ):
                return p
        return 0
