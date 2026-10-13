"""The F3 latency rewrites of the probes return what the previous implementations returned."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from reliability_agent.capture import SyntheticSource
from reliability_agent.probes.base import median, to_gray
from reliability_agent.probes.sharpness import blur_effect
from reliability_agent.probes.temporal import (
    _IMMERKAER,
    _IMMERKAER_SCALE,
    FreezeTracker,
    noise_sigmas,
)


def _ref_blur_effect(gray: np.ndarray, h_size: int = 11) -> float:
    img = gray.astype(np.float64) / 255.0
    scores = []
    for axis, ksize in ((0, (1, h_size)), (1, (h_size, 1))):
        blurred = cv2.blur(img, ksize)
        d_sharp = np.abs(np.diff(img, axis=axis))
        d_blur = np.abs(np.diff(blurred, axis=axis))
        t = np.maximum(0.0, d_sharp - d_blur)
        sl = (slice(2, -1), slice(2, -1))
        m1, m2 = float(d_sharp[sl].sum()), float(t[sl].sum())
        scores.append(1.0 if m1 <= 1e-12 else abs(m1 - m2) / m1)
    return float(max(scores))


def _ref_noise_sigmas(gray: np.ndarray, prev: np.ndarray) -> tuple[float, float]:
    g = gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)[1:-1, 1:-1]
    flat = mag <= float(np.median(mag))
    if not flat.any():
        return float("nan"), float("nan")
    lap = cv2.filter2D(g, cv2.CV_32F, _IMMERKAER)[1:-1, 1:-1]
    sigma_s = _IMMERKAER_SCALE * float(np.mean(np.abs(lap[flat])))
    d = (g - prev.astype(np.float32))[1:-1, 1:-1]
    return float(np.sqrt(np.mean(d[flat] ** 2) / 2.0)), sigma_s


def _ref_loop_period(tr: FreezeTracker) -> int:
    fr, full = list(tr._frames), list(tr._full)

    def mse(a, b):
        return float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))

    for p in range(2, tr.max_loop_period + 1):
        if len(fr) < 2 * p:
            break
        tail = fr[-2 * p:]
        period = [mse(tail[i], tail[i + p]) for i in range(p)]
        step = [mse(tail[i], tail[i + 1]) for i in range(p)]
        if all(d <= tr.loop_mse_max for d in period) and all(d > tr.loop_mse_max for d in step):
            return p
        if all(d > 0.0 for d in step):
            tf = full[-2 * p:]
            if all(np.array_equal(tf[i], tf[i + p]) for i in range(p)):
                return p
    return 0


def _frames(seed: int, n: int, size=(640, 480)) -> list[np.ndarray]:
    src = SyntheticSource(width=size[0], height=size[1], seed=seed)
    src.open()
    return [to_gray(src.read().image) for _ in range(n)]


def _scenes(rng: np.random.Generator) -> list[np.ndarray]:
    base = _frames(3, 1)[0]
    flat = np.full((480, 640), 120, np.uint8)
    return [base, cv2.GaussianBlur(base, (9, 9), 3), cv2.GaussianBlur(base, (31, 31), 10),
            (base // 6).astype(np.uint8), flat,
            np.clip(flat + rng.normal(0, 2, flat.shape), 0, 255).astype(np.uint8),
            rng.integers(0, 256, (360, 640), dtype=np.uint8),
            rng.integers(0, 256, (241, 333), dtype=np.uint8)]


@pytest.mark.parametrize("dtype", [np.uint8, np.float32, np.int32])
@pytest.mark.parametrize("n", [1, 2, 7, 640 * 480, 639 * 479])
def test_median_matches_numpy(dtype, n):
    rng = np.random.default_rng(n)
    for a in (rng.integers(0, 50, n).astype(dtype), rng.normal(0, 9, n).astype(dtype)):
        m = median(a.reshape(-1, 1) if n % 2 else a)
        assert m == np.median(a) and np.asarray(m).dtype == np.asarray(np.median(a)).dtype


def test_median_and_noise_sigmas_on_empty_or_nan_input_match_numpy():
    assert np.isnan(median(np.zeros(0, np.float32)))
    a = np.array([1.0, np.nan, 3.0, 4.0], np.float32)
    assert np.isnan(median(a)) and median(a).dtype == np.median(a).dtype
    tiny = np.zeros((2, 5), np.uint8)
    assert all(np.isnan(v) for v in noise_sigmas(tiny, tiny))


def test_blur_effect_matches_the_float64_computation():
    for img in _scenes(np.random.default_rng(0)):
        assert blur_effect(img) == pytest.approx(_ref_blur_effect(img), abs=1e-6)
    assert blur_effect(np.zeros((40, 40), np.uint8)) == 1.0


def test_noise_sigmas_match_the_boolean_index_computation():
    rng = np.random.default_rng(1)
    scenes = _scenes(rng)
    for img in scenes:
        noisy = img.astype(np.int16) + rng.integers(-3, 4, img.shape)
        nxt = np.clip(noisy, 0, 255).astype(np.uint8)
        for prev in (img, nxt):
            got, ref = noise_sigmas(img, prev), _ref_noise_sigmas(img, prev)
            assert got == pytest.approx(ref, rel=1e-5, abs=1e-9)


@pytest.mark.parametrize("case", ["live", "frozen", "loop3", "loop5_jitter", "mixed"])
def test_cached_loop_period_matches_the_uncached_search(case):
    rng = np.random.default_rng(7)
    live = _frames(5, 40, (320, 240))
    if case == "live":
        seq = live
    elif case == "frozen":
        seq = [live[0]] * 30
    elif case == "loop3":
        seq = (live[:3] * 12)[:36]
    elif case == "loop5_jitter":
        seq = [np.clip(f.astype(np.int16) + rng.integers(-1, 2, f.shape), 0, 255).astype(np.uint8)
               for f in (live[:5] * 8)]
    else:
        seq = live[:10] + (live[10:14] * 5) + [live[20]] * 6 + live[21:]
    tr = FreezeTracker(10, 8)
    for f in seq:
        got = tr.update(f).values["loop_period"]
        assert got == _ref_loop_period(tr)
        assert len(tr._pair_mse) <= 2 * tr.max_loop_period * (2 * tr.max_loop_period)
