"""F1: seeded faults on a recorded clip are detected by the local path, read via CameraSource."""

import copy

import cv2
import pytest

from benchmarks.replay import inject, replay, score
from reliability_agent.capture import OpenCVSource, SyntheticSource
from reliability_agent.config import load_config

FPS, SECONDS, START_S, END_S = 10, 36, 18, 33


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "clean.avi"
    t = [0.0]
    src = SyntheticSource(width=320, height=240, seed=11, clock=lambda: t[0])
    src.open()
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (320, 240))
    for _ in range(FPS * SECONDS):
        t[0] += 1 / FPS
        vw.write(src.read().image)
    vw.release()
    return path


@pytest.fixture(scope="module")
def cfg():
    c = copy.deepcopy(load_config(env=False))
    c["baseline"]["min_samples"] = 10
    return c


def frames(path):
    s = OpenCVSource(str(path))
    s.open()
    while (f := s.read()) is not None:
        yield f.image
    s.close()


def run(clip, cfg, kind, strength=1.0, seed=42):
    res = replay(inject(frames(clip), kind, START_S * FPS, END_S * FPS, strength, seed), FPS, cfg)
    return res, score(res, kind, START_S, FPS, cfg)


def test_clean_clip_raises_no_incident(clip, cfg):
    _, row = run(clip, cfg, None)
    assert row["passed"] and row["windows"] == SECONDS, row


@pytest.mark.parametrize("kind,strength", [("dark", 0.95), ("gaussian_blur", 0.8),
                                           ("freeze", 1.0)])
def test_injected_fault_is_confirmed_after_onset(clip, cfg, kind, strength):
    _, row = run(clip, cfg, kind, strength)
    assert row["passed"], row
    assert row["pre_fault_suspect_windows"] == 0, row
    assert 0 <= row["detection_delay_s"] <= cfg["fusion"]["enter_windows"] + 2, row


def test_replay_is_deterministic(clip, cfg):
    a, _ = run(clip, cfg, "gaussian_blur", 0.8)
    b, _ = run(clip, cfg, "gaussian_blur", 0.8)
    assert [(w.state, w.faults) for w in a.windows] == [(w.state, w.faults) for w in b.windows]
