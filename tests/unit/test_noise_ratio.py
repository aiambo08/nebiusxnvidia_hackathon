"""Temporal-vs-spatial noise (ADR-005) on synthetic frames. The figures are telemetry, not a
trigger: this file characterises the populations (live raw sensor ~1, frozen ~0) and records why
the collapse cannot be freeze evidence (a live static scene behind an H.264 encoder decodes with
no temporal noise either). No threshold in configs/default.yaml depends on these numbers."""

import pathlib
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from reliability_agent.probes.temporal import (
    MIN_SPATIAL_SIGMA,
    FreezeTracker,
    noise_ratio,
    noise_sigmas,
)

H, W = 480, 640
LIVE_RATIO_MIN = 0.6  # raw sensor, fresh noise every frame: ratio ~1
FROZEN_RATIO_MAX = 0.3  # repeated buffer with decoder jitter j: ratio ~ j / sigma


def _scene(kind: str, rng) -> np.ndarray:
    if kind == "wall":
        return np.full((H, W), 128, np.float32)
    if kind == "gradient":
        return np.tile(np.linspace(40, 220, W, dtype=np.float32), (H, 1))
    if kind == "textured":
        tex = rng.uniform(0, 255, (H // 8, W // 8)).astype(np.float32)
        return cv2.resize(tex, (W, H), interpolation=cv2.INTER_LINEAR)
    if kind == "edges":
        img = np.full((H, W), 90, np.float32)
        for k in range(0, W, 40):
            img[:, k:k + 20] = 200
        return img
    raise ValueError(kind)


def _live(scene, sigma, rng, n=12, gain=1.0, motion=None):
    for i in range(n):
        s = scene * gain
        if motion:
            size, contrast = motion
            s = s.copy()
            x = 20 + i * 15
            s[H // 2:H // 2 + size, x:x + size] += contrast
        yield np.clip(np.rint(s + rng.normal(0, sigma, scene.shape)), 0, 255).astype(np.uint8)


def _ratios(frames):
    frames = list(frames)
    return [noise_ratio(b, a) for a, b in zip(frames, frames[1:], strict=False)]


@pytest.mark.parametrize("kind", ["wall", "gradient", "textured", "edges"])
@pytest.mark.parametrize("sigma", [0.7, 1.0, 2.0, 3.0])
def test_live_raw_scenes_keep_temporal_noise(kind, sigma):
    rng = np.random.default_rng(0)
    r = _ratios(_live(_scene(kind, rng), sigma, rng))
    assert min(r) > LIVE_RATIO_MIN, (kind, sigma, r)
    assert max(r) < 3.0, (kind, sigma, r)


@pytest.mark.parametrize("size,contrast", [(5, 90), (8, 90), (20, 15), (40, 8), (120, 90)])
def test_small_or_low_contrast_motion_raises_the_ratio(size, contrast):
    """Reviewer cases on a sigma 0.7 wall: a 5 px dark blob, 20 px at +15, 40 px at +8, a
    person-sized block. Motion adds temporal energy, so the ratio can only go up."""
    rng = np.random.default_rng(1)
    still = _ratios(_live(_scene("wall", rng), 0.7, rng))
    moving = _ratios(_live(_scene("wall", rng), 0.7, rng, motion=(size, contrast)))
    assert min(moving) >= min(still) * 0.9
    assert min(moving) > LIVE_RATIO_MIN


@pytest.mark.parametrize("kind", ["wall", "textured"])
@pytest.mark.parametrize("sigma", [0.7, 2.0])
def test_frozen_frame_loses_temporal_noise(kind, sigma):
    rng = np.random.default_rng(2)
    frame = next(_live(_scene(kind, rng), sigma, rng, n=1))
    assert noise_ratio(frame, frame) == 0.0


@pytest.mark.parametrize("kind", ["wall", "textured"])
@pytest.mark.parametrize("sigma,jitter", [
    (0.7, 0.1), (0.7, 0.15), (0.7, 0.2), (0.7, 0.25),
    (2.0, 0.1), (2.0, 0.15), (2.0, 0.2), (2.0, 0.25), (2.0, 0.5),
    pytest.param(0.7, 0.5, marks=pytest.mark.xfail(
        strict=True, reason="ADR-005 limit: decoder jitter of ~0.7x the sensor noise is "
        "indistinguishable from a live sensor by any per-frame noise measure")),
])
def test_frozen_frame_with_codec_jitter_has_a_low_ratio(kind, sigma, jitter):
    """A frozen frame re-encoded with decoder jitter: the baked-in sensor noise sets the spatial
    sigma, the jitter alone sets the temporal one, so the ratio is about jitter / sigma."""
    rng = np.random.default_rng(3)
    frozen = next(_live(_scene(kind, rng), sigma, rng, n=1)).astype(np.float32)
    frames = [np.clip(np.rint(frozen + rng.normal(0, jitter, frozen.shape)), 0, 255)
              .astype(np.uint8) for _ in range(8)]
    r = _ratios(frames)
    assert max(r) <= FROZEN_RATIO_MAX, (kind, sigma, jitter, r)


def test_gain_drop_leaves_the_ratio_unchanged():
    """AGC / dimmer light: both noises shrink together."""
    rng = np.random.default_rng(4)
    bright = _ratios(_live(_scene("gradient", rng), 2.0, rng))
    dim = _ratios(_live(_scene("gradient", rng), 0.7, rng, gain=0.3))
    assert abs(np.median(bright) - np.median(dim)) < 0.5
    assert min(dim) > LIVE_RATIO_MIN


def test_frames_without_measurable_noise_abstain():
    black = np.zeros((H, W), np.uint8)
    assert np.isnan(noise_ratio(black, black))
    flat = np.full((H, W), 128, np.uint8)
    assert np.isnan(noise_ratio(flat, flat))
    assert MIN_SPATIAL_SIGMA > 0


def test_tracker_reports_noise_ratio_and_warms_up():
    rng = np.random.default_rng(5)
    t = FreezeTracker()
    frames = list(_live(_scene("wall", rng), 1.0, rng, n=4))
    first = t.update(frames[0])
    assert np.isnan(first.values["noise_ratio"]) and first.quality == "unknown"
    for f in frames[1:]:
        res = t.update(f)
    assert 0.6 < res.values["noise_ratio"] < 3.0
    frozen = t.update(frames[-1])
    assert frozen.values["noise_ratio"] == 0.0
    assert frozen.values["temporal_sigma"] == 0.0
    assert frozen.values["temporal_mse"] == 0.0


def test_fine_grain_texture_fools_the_ratio_but_not_the_temporal_sigma():
    """Pixel-scale static texture (fabric, grain, fixed-pattern noise, sigma 6) with live sensor
    noise sigma 1: the ratio drops to the frozen population while the temporal sigma says the
    pixels do change. One reason the ratio is not a trigger."""
    rng = np.random.default_rng(7)
    grain = np.clip(_scene("wall", rng) + rng.normal(0, 6.0, (H, W)), 0, 255)
    frames = list(_live(grain.astype(np.float32), 1.0, rng, n=6))
    pairs = [noise_sigmas(b, a) for a, b in zip(frames, frames[1:], strict=False)]
    assert max(st / ss for st, ss in pairs) < FROZEN_RATIO_MAX
    assert min(st for st, _ in pairs) > 0.5


@pytest.mark.parametrize("sigma", [0.7, 1.0, 2.0, 3.0])
def test_live_temporal_sigma_tracks_the_sensor_noise(sigma):
    rng = np.random.default_rng(8)
    frames = list(_live(_scene("gradient", rng), sigma, rng, n=6))
    sig_t = [noise_sigmas(b, a)[0] for a, b in zip(frames, frames[1:], strict=False)]
    assert all(abs(s - sigma) < 0.15 * sigma + 0.1 for s in sig_t), sig_t


def _x264_roundtrip(frames, crf, tmp_path):
    raw = tmp_path / "in.gray"
    raw.write_bytes(b"".join(f.tobytes() for f in frames))
    out = tmp_path / "out.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray",
         "-s", f"{W}x{H}", "-r", "30", "-i", str(raw), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)],
        check=True, timeout=120,
    )
    cap = cv2.VideoCapture(str(out))
    decoded = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        decoded.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    cap.release()
    return decoded


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg with libx264 not installed")
@pytest.mark.parametrize("kind,sigma,crf", [("textured", 2.0, 23), ("textured", 2.0, 28),
                                            ("wall", 0.7, 23), ("wall", 2.0, 28)])
def test_live_static_scene_over_h264_is_pixel_identical_to_a_frozen_one(kind, sigma, crf,
                                                                          tmp_path):
    """Why the noise collapse is not a trigger (reviewer finding, 4th pass): a live static
    scene through libx264 at everyday quality loses its temporal noise (skip macroblocks), so
    the hashes repeat and the ratio sits in the frozen population; on a smooth wall the decoded
    frames are even bit-exact. Freeze on compressed sources needs transport evidence."""
    rng = np.random.default_rng(9)
    frames = list(_live(_scene(kind, rng), sigma, rng, n=90))
    decoded = _x264_roundtrip(frames, crf, pathlib.Path(tmp_path))
    assert len(decoded) == 90
    t = FreezeTracker()
    vals = [t.update(f).values for f in decoded][30:]
    assert np.mean([v["repeated_hash_ratio"] for v in vals]) > 0.95
    ratios = [v["noise_ratio"] for v in vals if np.isfinite(v["noise_ratio"])]
    sig_t = [v["temporal_sigma"] for v in vals]
    assert np.median(sig_t) < 0.1, sig_t
    if ratios:
        assert np.median(ratios) < FROZEN_RATIO_MAX, ratios
    if kind == "wall":
        assert np.mean([v["exact_repeat_ratio"] for v in vals]) > 0.9
