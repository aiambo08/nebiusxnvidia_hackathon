"""The geometry probe on a pool thread (`probes.geometry.parallel`) returns what it returns in
sequence, publishes per frame as before, and never outlives the `analyse` call that started it."""

from __future__ import annotations

import copy
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from benchmarks.injectors.faults import SPATIAL, TEMPORAL, apply_stream
from reliability_agent.capture import SyntheticSource
from reliability_agent.capture.base import Frame
from reliability_agent.probes import runner as runner_mod
from reliability_agent.probes.runner import ProbeRunner


def _cfg(cfg: dict, parallel: bool, every: int = 5) -> dict:
    c = copy.deepcopy(cfg)
    c["probes"]["geometry"]["parallel"] = parallel
    c["probes"]["geometry"]["every_n_frames"] = every
    return c


def _frames(kind: str | None, n: int = 40, size: tuple[int, int] = (640, 480), seed: int = 3):
    src = SyntheticSource(width=size[0], height=size[1], seed=seed)
    src.open()
    raw = [src.read().image for _ in range(n)]
    imgs = raw if kind is None else list(apply_stream(raw, kind, 12, 30, 1.0, seed))
    return [Frame(image=im, seq=i, t_mono=float(i)) for i, im in enumerate(imgs)]


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys() or list(a) != list(b):
        return False
    for k in a:
        if k == "task_latency_ms":
            continue
        x, y = a[k], b[k]
        if not (x == y or (isinstance(x, float) and math.isnan(x) and math.isnan(y))):
            return False
    return True


def _trace(cfg: dict, frames: list[Frame], *, rereference: int | None = None, calibrate=True):
    r = ProbeRunner(cfg)
    if calibrate:
        r.calibrate_reference(frames[0])
    rows = []
    for i, f in enumerate(frames[1:], 1):
        if rereference is not None and i == rereference:
            r.set_geometry_reference(f)
        rows.append((r.analyse(f), r._geom_quality))
    return rows


@pytest.mark.parametrize("kind", [None, *sorted(SPATIAL | TEMPORAL)])
def test_parallel_matches_sequential_under_every_injector(cfg, kind):
    frames = _frames(kind)
    seq = _trace(_cfg(cfg, False), frames, rereference=17)
    par = _trace(_cfg(cfg, True), frames, rereference=17)
    assert len(seq) == len(par)
    for (a, qa), (b, qb) in zip(seq, par, strict=True):
        assert qa == qb
        assert _same(a, b)


@pytest.mark.parametrize("size", [(1280, 720), (320, 240)])
@pytest.mark.parametrize("every", [1, 3])
def test_parallel_matches_sequential_across_sizes_and_cadence(cfg, size, every):
    frames = _frames("translate", n=25, size=size)
    seq = _trace(_cfg(cfg, False, every), frames)
    par = _trace(_cfg(cfg, True, every), frames)
    for (a, qa), (b, qb) in zip(seq, par, strict=True):
        assert qa == qb and _same(a, b)


def test_no_reference_and_low_texture_quality_are_kept(cfg):
    frames = _frames(None, n=8)
    for parallel in (False, True):
        rows = _trace(_cfg(cfg, parallel), frames, calibrate=False)
        assert {q for _, q in rows} == {"no_reference"}
        r = ProbeRunner(_cfg(cfg, parallel))
        r.calibrate_reference(frames[0])
        flat = Frame(image=np.full((480, 640, 3), 128, np.uint8), seq=99, t_mono=99.0)
        r.analyse(flat)
        assert r._geom_quality == "low_texture"


def test_geometry_runs_off_the_calling_thread_only_when_parallel(cfg):
    frames = _frames(None, n=3)
    for parallel in (False, True):
        r = ProbeRunner(_cfg(cfg, parallel))
        r.calibrate_reference(frames[0])
        seen: list[str] = []
        measure = r.geometry.measure

        def spy(gray, _m=measure, _seen=seen):
            _seen.append(threading.current_thread().name)
            return _m(gray)

        r.geometry.measure = spy
        r.analyse(frames[1])
        caller = threading.current_thread().name
        assert seen and (seen[0] != caller) == parallel
        if parallel:
            assert seen[0].startswith("ra-geometry")


def test_worker_exception_propagates_and_the_runner_recovers(cfg):
    frames = _frames(None, n=8)
    r = ProbeRunner(_cfg(cfg, True, every=1))
    r.calibrate_reference(frames[0])
    measure = r.geometry.measure

    def boom(gray):
        raise RuntimeError("geometry failed")

    r.geometry.measure = boom
    with pytest.raises(RuntimeError, match="geometry failed"):
        r.analyse(frames[1])
    r.geometry.measure = measure
    out = r.analyse(frames[2])
    assert r._geom_quality == "ok" and "geom_translation_px" in out


def test_probe_exception_waits_for_the_running_geometry(cfg, monkeypatch):
    frames = _frames(None, n=3)
    r = ProbeRunner(_cfg(cfg, True))
    r.calibrate_reference(frames[0])
    done = threading.Event()
    measure = r.geometry.measure

    def slow(gray):
        time.sleep(0.2)
        res = measure(gray)
        done.set()
        return res

    r.geometry.measure = slow

    def broken(*a, **k):
        raise ValueError("sharpness failed")

    monkeypatch.setattr(runner_mod, "sharpness_probe", broken)
    with pytest.raises(ValueError, match="sharpness failed"):
        r.analyse(frames[1])
    assert done.is_set()  # the probe did not keep running into the caller's next step


def test_concurrent_runners_match_their_sequential_traces(cfg):
    clips = [_frames(k, n=20, seed=s) for s, k in enumerate([None, "translate", "rotate", "dark"])]
    expected = [_trace(_cfg(cfg, False), c) for c in clips]
    with ThreadPoolExecutor(max_workers=len(clips)) as ex:
        got = list(ex.map(lambda c: _trace(_cfg(cfg, True), c), clips))
    for exp, par in zip(expected, got, strict=True):
        for (a, qa), (b, qb) in zip(exp, par, strict=True):
            assert qa == qb and _same(a, b)


def test_pool_is_recreated_in_a_forked_child(monkeypatch):
    pool = runner_mod._geometry_pool()
    assert runner_mod._geometry_pool() is pool
    monkeypatch.setattr(runner_mod.os, "getpid", lambda: -1)
    child = runner_mod._geometry_pool()
    assert child is not pool
    assert child.submit(lambda: 7).result(timeout=5) == 7


def test_default_config_enables_parallel_geometry(cfg):
    assert cfg["probes"]["geometry"]["parallel"] is True
    assert ProbeRunner(cfg).geometry_parallel is True
