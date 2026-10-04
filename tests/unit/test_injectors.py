import numpy as np
import pytest

from benchmarks.injectors.faults import ALL, SPATIAL, apply_spatial, apply_stream
from reliability_agent.capture import SyntheticSource
from reliability_agent.probes.base import to_gray
from reliability_agent.probes.sharpness import blur_effect


@pytest.fixture(scope="module")
def frames():
    s = SyntheticSource(width=320, height=240, seed=5)
    s.open()
    return [s.read().image for _ in range(30)]


@pytest.mark.parametrize("kind", sorted(SPATIAL))
def test_spatial_is_deterministic(frames, kind):
    a = apply_spatial(frames[0], kind, 0.8, np.random.default_rng(1))
    b = apply_spatial(frames[0], kind, 0.8, np.random.default_rng(1))
    assert np.array_equal(a, b) and a.shape == frames[0].shape


def test_blur_injection_raises_blur_effect(frames):
    g = to_gray(frames[0])
    assert blur_effect(to_gray(apply_spatial(frames[0], "gaussian_blur", 1.0))) > blur_effect(g)


def test_freeze_and_loop_streams(frames):
    out = list(apply_stream(frames, "freeze", 10, 20))
    assert all(np.array_equal(out[10], out[i]) for i in range(10, 20))
    assert not np.array_equal(out[20], out[10])
    loop = list(apply_stream(frames, "loop4", 0, 30))
    assert np.array_equal(loop[4], loop[0]) and np.array_equal(loop[9], loop[5])


def test_fps_drop_reduces_frames(frames):
    assert len(list(apply_stream(frames, "fps_drop", 0, 30, 1.0))) < 10


def test_unknown_fault_raises(frames):
    with pytest.raises(ValueError):
        list(apply_stream(frames, "nope", 0, 5))
    assert "freeze" in ALL
