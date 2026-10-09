import cv2
import numpy as np
import pytest

from reliability_agent.capture import SyntheticSource
from reliability_agent.capture.base import Frame
from reliability_agent.capture.worker import TransportMeter
from reliability_agent.config import load_config
from reliability_agent.contracts.models import TransportMetrics
from reliability_agent.probes.base import to_gray
from reliability_agent.probes.geometry import GeometryProbe
from reliability_agent.probes.occlusion import cell_stats, occlusion_probe
from reliability_agent.probes.photometric import exposure_probe
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator
from reliability_agent.probes.sharpness import blur_effect, sharpness_probe
from reliability_agent.probes.temporal import FreezeTracker, dhash
from reliability_agent.tasks.marker import MarkerTask


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


def _wall_scene(rng, n=30, sigma=0.7):
    """Smooth indoor scene with a quiet sensor (sigma ~0.7 counts), as a laptop webcam at rest."""
    base = np.zeros((480, 640, 3), np.uint8)
    base[:] = 120
    cv2.rectangle(base, (100, 100), (300, 300), (200, 180, 160), -1)
    cv2.putText(base, "wall", (350, 250), cv2.FONT_HERSHEY_SIMPLEX, 3, (40, 40, 40), 6)
    return [np.clip(base.astype(np.float32) + rng.normal(0, sigma, base.shape), 0, 255)
            .astype(np.uint8) for _ in range(n)]


def _classify_frames(cfg, frames):
    from reliability_agent.incidents.fusion import classify_window

    runner, agg = ProbeRunner(cfg), WindowAggregator("cam", 1.0)
    for i, img in enumerate(frames):
        agg.add(runner.analyse(Frame(image=img, seq=i, t_mono=i / 5, t_source=None)))
    tw = agg.emit(TransportMetrics(capture_fps=5.0, frame_age_ms_p95=40.0, connected=True))
    return classify_window(tw, None, cfg["faults"])[0], tw


def test_live_dark_scene_pixels_do_not_classify_as_freeze(cfg):
    from benchmarks.injectors.faults import apply_spatial
    from reliability_agent.contracts.models import FaultType

    rng = np.random.default_rng(0)
    frames = [apply_spatial(f, "dark", 0.95) for f in _wall_scene(rng)]
    faults, tw = _classify_frames(cfg, frames)
    assert tw.visual.repeated_hash_ratio >= 0.95  # the trap this test guards against
    assert FaultType.BLACKOUT in faults
    assert FaultType.FREEZE not in faults, (faults, tw.visual)


def test_frozen_lit_scene_pixels_classify_as_freeze(cfg):
    from reliability_agent.contracts.models import FaultType

    rng = np.random.default_rng(0)
    frames = [_wall_scene(rng, n=1)[0]] * 30
    faults, _ = _classify_frames(cfg, frames)
    assert FaultType.FREEZE in faults


def test_bit_exact_loop_of_a_static_noisy_scene_is_a_freeze(cfg):
    """A replayed 4-frame buffer of a static scene differs frame to frame only by the sensor
    noise it captured, so the motion-based loop rule cannot see it; the bit-exact period can."""
    from reliability_agent.contracts.models import FaultType

    rng = np.random.default_rng(3)
    live = _wall_scene(rng, n=30, sigma=2.0)
    faults, tw = _classify_frames(cfg, live)
    assert tw.visual.loop_period is None and FaultType.FREEZE not in faults
    looped = live[:10] + [live[10 + (i % 4)] for i in range(20)]
    faults, tw = _classify_frames(cfg, looped)
    assert tw.visual.loop_period == 4
    assert FaultType.FREEZE in faults


def _wall(rng, level, sigma, shape=(480, 640)):
    return np.clip(np.rint(level + rng.normal(0, sigma, shape)), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("level,sigma", [(40, 0.3), (120, 0.3), (200, 0.4)])
def test_live_low_noise_wall_is_not_bit_exact_on_the_input_frame(level, sigma):
    """Reviewer FP (ADR-005, 5th pass): sigma <= 0.4 averaged into the 160x120 image rounds to
    the same value every frame; the 640x480 input frame never repeats."""
    rng = np.random.default_rng(1)
    ft = FreezeTracker(window=10)
    for _ in range(30):
        r = ft.update(_wall(rng, level, sigma))
    assert r.values["exact_repeat_ratio"] == 0.0
    assert r.values["loop_period"] == 0


def test_live_wall_behind_temporal_denoiser_is_not_bit_exact():
    rng = np.random.default_rng(2)
    ft = FreezeTracker(window=10)
    acc = _wall(rng, 120, 0.7).astype(np.float32)
    for _ in range(40):
        acc = 0.9 * acc + 0.1 * _wall(rng, 120, 0.7)
        r = ft.update(np.rint(acc).astype(np.uint8))
    assert r.values["exact_repeat_ratio"] < 0.5


def test_periodic_flicker_on_a_live_sensor_is_a_loop_only_through_the_mse_floor():
    """A 4-level flicker (period 4, every step +-4 counts) on a live sigma 0.7 sensor: the
    640x480 input frames are never bit-exact across the period, but the 160x120 period MSE
    (noise variance / 16) sits under `loop_mse_max`, so the MSE floor still reports a loop.
    Pre-existing on `main`, kept on purpose: lowering it would cost replayed-buffer recall
    (ADR-005 consequences)."""
    rng = np.random.default_rng(3)
    exact_only = FreezeTracker(window=10, max_loop_period=8, loop_mse_max=0.0)
    with_floor = FreezeTracker(window=10, max_loop_period=8)
    for i in range(40):
        f = _wall(rng, 120 + (0, 4, 8, 4)[i % 4], 0.7)
        r_exact = exact_only.update(f)
        r_floor = with_floor.update(f)
    assert r_exact.values["loop_period"] == 0
    assert r_floor.values["loop_period"] == 4


@pytest.mark.parametrize("shape", [(480, 640), (720, 1280)])
@pytest.mark.parametrize("jitter", [0.1, 0.45])
def test_replayed_moving_buffer_with_decoder_jitter_is_still_a_loop(shape, jitter):
    rng = np.random.default_rng(6)
    base = [_wall(rng, 120, 2.0, shape) for _ in range(4)]
    for k, f in enumerate(base):  # real motion between frames: a bright block that moves
        f[100:160, 100 + 80 * k : 160 + 80 * k] = 220
    ft = FreezeTracker(window=10, max_loop_period=8)
    for i in range(24):
        f = np.clip(np.rint(base[i % 4] + rng.normal(0, jitter, shape)), 0, 255).astype(np.uint8)
        r = ft.update(f)
    assert r.values["loop_period"] == 4


@pytest.mark.parametrize("jitter", [0.0, 0.1])
def test_replayed_buffer_is_a_loop_with_or_without_decoder_jitter(jitter):
    """Static replayed buffer. Bit-exact: always a loop. With jitter 0.1 this only holds for wall
    sigma 2 at 640x480; other resolutions/noise levels are a documented miss (ADR-005 table)."""
    rng = np.random.default_rng(4)
    base = [_wall(rng, 120, 2.0) for _ in range(4)]
    ft = FreezeTracker(window=10, max_loop_period=8)
    for i in range(24):
        f = base[i % 4]
        if jitter:
            f = np.clip(np.rint(f + rng.normal(0, jitter, f.shape)), 0, 255).astype(np.uint8)
        r = ft.update(f)
    assert r.values["loop_period"] == 4


def test_frozen_input_frame_is_bit_exact():
    rng = np.random.default_rng(5)
    f = _wall(rng, 120, 2.0)
    ft = FreezeTracker(window=10)
    for _ in range(12):
        r = ft.update(f)
    assert r.values["exact_repeat_ratio"] == 1.0
