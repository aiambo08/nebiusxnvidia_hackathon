"""Reproducible fault injection (F4). Spatial faults act per frame; temporal faults act on the
frame stream. Every transform is seeded, so a manifest fully determines the output."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import cv2
import numpy as np

SPATIAL = {
    "gaussian_blur", "motion_blur_h", "motion_blur_v", "dark", "overexpose",
    "occlude_opaque", "occlude_semi", "rotate", "translate", "lighting_change",
}
TEMPORAL = {"freeze", "loop4", "loop8", "fps_drop", "delay_jitter"}
ALL = SPATIAL | TEMPORAL


def apply_spatial(img: np.ndarray, kind: str, strength: float = 1.0,
                  rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    s = float(np.clip(strength, 0.0, 1.0))
    h, w = img.shape[:2]
    if kind == "gaussian_blur":
        k = int(3 + 40 * s) | 1
        return cv2.GaussianBlur(img, (k, k), 0)
    if kind in ("motion_blur_h", "motion_blur_v"):
        k = max(3, int(3 + 40 * s))
        kern = np.zeros((k, k), np.float32)
        if kind == "motion_blur_h":
            kern[k // 2, :] = 1.0 / k
        else:
            kern[:, k // 2] = 1.0 / k
        return cv2.filter2D(img, -1, kern)
    if kind in ("dark", "overexpose", "lighting_change"):
        gain = {"dark": 1 - 0.97 * s, "overexpose": 1 + 4 * s,
                "lighting_change": 1 - 0.35 * s}[kind]  # legitimate change: mild, global
        return np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    if kind in ("occlude_opaque", "occlude_semi"):
        out = img.copy()
        frac = 0.2 + 0.6 * s
        x0 = int(rng.integers(0, max(1, int(w * (1 - frac)))))
        x1 = x0 + int(w * frac)
        if kind == "occlude_opaque":
            out[:, x0:x1] = 10
        else:  # smudge: heavy blur + haze over the region
            region = cv2.GaussianBlur(out[:, x0:x1], (31, 31), 0).astype(np.float32)
            out[:, x0:x1] = np.clip(0.5 * region + 0.5 * 200, 0, 255).astype(np.uint8)
        return out
    if kind == "rotate":
        m = cv2.getRotationMatrix2D((w / 2, h / 2), 10 * s, 1.0)
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)
    if kind == "translate":
        m = np.float32([[1, 0, 0.15 * w * s], [0, 1, 0.1 * h * s]])
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)
    raise ValueError(f"unknown spatial fault {kind}")


def apply_stream(frames: Iterable[np.ndarray], kind: str, start: int, end: int,
                 strength: float = 1.0, seed: int = 0) -> Iterator[np.ndarray]:
    """Yield frames with `kind` active in [start, end)."""
    rng = np.random.default_rng(seed)
    buf: list[np.ndarray] = []
    held: np.ndarray | None = None
    for i, f in enumerate(frames):
        active = start <= i < end
        if not active:
            buf.clear()
            held = None
            yield f
            continue
        if kind in SPATIAL:
            yield apply_spatial(f, kind, strength, rng)
        elif kind == "freeze":
            held = f if held is None else held
            yield held.copy()
        elif kind in ("loop4", "loop8"):
            p = 4 if kind == "loop4" else 8
            if len(buf) < p:
                buf.append(f)
                yield f
            else:
                yield buf[(i - start) % p].copy()
        elif kind == "fps_drop":
            keep = max(2, int(2 + 8 * strength))  # keep 1 of every `keep` frames
            if (i - start) % keep == 0:
                yield f
        elif kind == "delay_jitter":
            if rng.random() < 0.3 * strength:
                continue  # dropped / late frame
            yield f
        else:
            raise ValueError(f"unknown fault {kind}")
