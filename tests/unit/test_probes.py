import cv2
import numpy as np
import pytest

from reliability_agent.capture import SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.probes.base import to_gray
from reliability_agent.probes.geometry import GeometryProbe
from reliability_agent.probes.occlusion import cell_stats, occlusion_probe
from reliability_agent.probes.photometric import exposure_probe
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator
from reliability_agent.probes.sharpness import blur_effect, sharpness_probe
from reliability_agent.probes.temporal import FreezeTracker, dhash
from reliability_agent.tasks.marker import MarkerTask
from reliability_agent.capture.worker import TransportMeter


@pytest.fixture
def scene():
    src = SyntheticSource(seed=1)
    src.open()
    return src, to_gray(src.read().image)


def test_blur_effect_monotonic(scene):
    _, g = scene
    vals = [blur_effect(g)] + [blur_effect(cv2.GaussianBlur(g, (k, k), 0)) for k in (5, 11, 21)]
    assert vals == sorted(vals)
    assert vals[0] < 0.4 and vals[-1] > 0.6


def test_sharpness_low_texture_is_unknown():
    res = sharpness_probe(np.full((240, 320), 128, np.uint8))
    assert res.quality == "low_texture" and res.unknown_reason


def test_exposure_detects_dark_and_clipping(scene):
    _, g = scene
    dark = exposure_probe((g * 0.05).astype(np.uint8))
    bright = exposure_probe(np.clip(g.astype(int) * 4, 0, 255).astype(np.uint8))
    assert dark.values["brightness"] < 15 and dark.values["black_pixel_ratio"] > 0.8
    assert bright.values["white_pixel_ratio"] > 0.5


def test_freeze_vs_static_scene(scene):
    src, g = scene
    ft = FreezeTracker(window=8)
    for _ in range(10):
        r = ft.update(g)  # bit-exact repeat = frozen pipeline
    assert r.values["exact_repeat_ratio"] == 1.0
    ft2 = FreezeTracker(window=8)
    rng = np.random.default_rng(0)
    for _ in range(10):  # static scene + sensor noise = NOT frozen
        noisy = np.clip(g + rng.normal(0, 2, g.shape), 0, 255).astype(np.uint8)
        r2 = ft2.update(noisy)
    assert r2.values["exact_repeat_ratio"] == 0.0


def test_loop_detection(scene):
    src, _ = scene
    frames = [to_gray(src.read().image) for _ in range(4)]
    ft = FreezeTracker(window=10, max_loop_period=8)
    for i in range(16):
        r = ft.update(frames[i % 4])
    assert r.values["loop_period"] == 4


def test_dhash_stable_under_noise(scene):
    _, g = scene
    noisy = np.clip(g + np.random.default_rng(0).normal(0, 1, g.shape), 0, 255).astype(np.uint8)
    assert (dhash(g) ^ dhash(noisy)).bit_count() <= 6


def test_occlusion_ratio(scene):
    _, g = scene
    occ = g.copy()
    occ[:, : g.shape[1] // 2] = 10
    base = cell_stats(g)
    assert occlusion_probe(g, baseline_cells=base).values["occluded_cell_ratio"] < 0.1
    r = occlusion_probe(occ, baseline_cells=base).values["occluded_cell_ratio"]
    assert 0.4 <= r <= 0.6


def test_geometry_detects_shift(scene):
    _, g = scene
    gp = GeometryProbe()
    assert gp.measure(g).quality == "no_reference"
    gp.set_reference(g)
    same = gp.measure(g).values
    assert same["translation_px"] < 2 and same["homography_inlier_ratio"] > 0.8
    m = np.float32([[1, 0, 40], [0, 1, 20]])
    shifted = cv2.warpAffine(g, m, (g.shape[1], g.shape[0]), borderMode=cv2.BORDER_REFLECT)
    assert gp.measure(shifted).values["translation_px"] > 30


def test_marker_task_degrades_with_faults(scene):
    _, g = scene
    task = MarkerTask({7})
    assert task.run(g).values["success"] == 1.0
    # NB: ArUco success is non-monotonic in blur strength (see DECISIONS.md), so we test a
    # known-failing level rather than "more blur = worse".
    assert task.run(cv2.GaussianBlur(g, (9, 9), 0)).values["success"] == 0.0
    assert task.run((g * 0.03).astype(np.uint8)).values["success"] == 0.0


def test_runner_produces_valid_window():
    cfg = load_config(env=False)
    src = SyntheticSource(seed=2)
    src.open()
    runner = ProbeRunner(cfg)
    runner.calibrate_reference(src.read())
    agg = WindowAggregator("cam", 1.0)
    meter = TransportMeter()
    for _ in range(6):
        f = src.read()
        meter.on_frame(f)
        agg.add(runner.analyse(f))
    tw = agg.emit(meter.snapshot())
    assert tw.frames_analyzed == 6
    assert tw.task.success_rate == 1.0
    assert tw.visual.blur_effect_p50 is not None
    assert tw.geometry.translation_px is not None and tw.geometry.translation_px < 3
