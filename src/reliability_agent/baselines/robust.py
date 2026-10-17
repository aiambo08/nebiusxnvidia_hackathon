"""Robust per-camera baseline: rolling median + MAD, frozen while an incident is open.

    z_t = |x_t - median(X)| / (1.4826 * MAD(X) + eps)
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

import numpy as np


class RobustBaseline:
    RECENT = 16  # latest updates that ``drop_last`` can undo

    def __init__(self, window: int = 300, min_samples: int = 20, eps: float = 1e-6,
                 mode: str = "default") -> None:
        self.window = window
        self.min_samples = min_samples
        self.eps = eps
        self.mode = mode  # e.g. day / night / profile — one baseline per mode (F5)
        self._data: dict[str, deque[float]] = {}
        self.updates = 0
        self._recent: deque[list[str]] = deque(maxlen=self.RECENT)

    def update(self, sample: dict[str, float], *, frozen: bool = False) -> bool:
        """Add a sample unless frozen. Returns True if it was learned."""
        if frozen:
            return False
        keys = []
        for k, v in sample.items():
            if v is None or not np.isfinite(v):
                continue
            self._data.setdefault(k, deque(maxlen=self.window)).append(float(v))
            keys.append(k)
        self._recent.append(keys)
        self.updates += 1
        return True

    def drop_last(self, n: int) -> int:
        """Forget up to the ``n`` latest updates (at most ``RECENT``); returns how many."""
        dropped = 0
        while dropped < n and self._recent:
            for k in self._recent.pop():
                if self._data.get(k):
                    self._data[k].pop()
            self.updates -= 1
            dropped += 1
        return dropped

    def count(self, metric: str) -> int:
        return len(self._data.get(metric, ()))

    @property
    def ready(self) -> bool:
        return self.updates >= self.min_samples

    def stats(self, metric: str) -> tuple[float, float] | None:
        vals = self._data.get(metric)
        if not vals or len(vals) < self.min_samples:
            return None
        arr = np.asarray(vals)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        return med, mad

    def median(self, metric: str) -> float | None:
        s = self.stats(metric)
        return None if s is None else s[0]

    def quantile(self, metric: str, q: float) -> float | None:
        """Low quantiles give the quietest healthy value seen, e.g. a camera's noise floor."""
        vals = self._data.get(metric)
        if not vals or len(vals) < self.min_samples:
            return None
        return float(np.quantile(np.asarray(vals), q))

    def z(self, metric: str, value: float | None) -> float | None:
        s = self.stats(metric)
        if s is None or value is None or not np.isfinite(value):
            return None
        med, mad = s
        return abs(value - med) / (1.4826 * mad + self.eps)

    @property
    def version(self) -> str:
        meds = {k: round(self.median(k) or 0.0, 4) for k in sorted(self._data)}
        h = hashlib.sha256(json.dumps([self.mode, meds]).encode()).hexdigest()[:12]
        return f"{self.mode}-{self.updates}-{h}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "min_samples": self.min_samples,
            "eps": self.eps,
            "mode": self.mode,
            "updates": self.updates,
            "data": {k: list(v) for k, v in self._data.items()},
            "recent": [list(keys) for keys in self._recent],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RobustBaseline:
        b = cls(d["window"], d["min_samples"], d["eps"], d.get("mode", "default"))
        b.updates = d["updates"]
        for k, vals in d["data"].items():
            b._data[k] = deque(vals, maxlen=b.window)
        b._recent.extend([str(k) for k in keys] for keys in d.get("recent", []))
        return b
