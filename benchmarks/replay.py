"""Deterministic offline replay of a clip through probes + incident tracker (no network, no LLM).

Time is driven by the frame index of the clip, not the wall clock, so the same clip and the same
fault spec always produce the same telemetry windows and the same detection result.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import numpy as np

from benchmarks.injectors.faults import apply_stream
from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.capture.base import Frame
from reliability_agent.capture.worker import TransportMeter
from reliability_agent.contracts.models import FaultType, IncidentState
from reliability_agent.incidents.fusion import IncidentTracker
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator

# Injector kind -> fault the detector must confirm.
EXPECTED: dict[str, FaultType] = {
    "dark": FaultType.BLACKOUT,
    "gaussian_blur": FaultType.FOCUS_DRIFT,
    "freeze": FaultType.FREEZE,
    "overexpose": FaultType.OVEREXPOSURE,
    "occlude_opaque": FaultType.LENS_OCCLUSION,
    "loop4": FaultType.FREEZE,  # short replayed loops are a freeze variant (bit-exact period rule)
    "loop8": FaultType.FREEZE,
}


@dataclass
class WindowResult:
    index: int
    t_end_s: float
    state: IncidentState
    faults: list[str]


@dataclass
class ReplayResult:
    windows: list[WindowResult] = field(default_factory=list)
    confirmed_window: int | None = None
    confirmed_faults: list[str] = field(default_factory=list)


def replay(frames: Iterable[np.ndarray], clip_fps: float, cfg: dict) -> ReplayResult:
    """Sample `analytic_fps` frames/s from a clip and run the local detection path on them."""
    afps = cfg["camera"]["analytic_fps"]
    step = max(1, round(clip_fps / afps))
    per_window = max(1, round(afps * cfg["window"]["seconds"]))
    fu, b = cfg["fusion"], cfg["baseline"]
    tracker = IncidentTracker(
        "replay", cfg["faults"], fu["enter_windows"], fu["exit_windows"], fu["cooldown_s"],
        RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]))
    runner = ProbeRunner(cfg)
    meter = TransportMeter()
    meter.connected = True
    agg = WindowAggregator("replay", cfg["window"]["seconds"])
    res = ReplayResult()
    seq = n = 0
    calibrated = False
    for i, img in enumerate(frames):
        if i % step:
            continue
        t = i / clip_fps
        seq += 1
        frame = Frame(img, seq, t)
        meter.on_frame(frame, processed_at=t)
        if not calibrated:
            runner.calibrate_reference(frame)
            calibrated = True
        agg.add(runner.analyse(frame))
        n += 1
        if n < per_window:
            continue
        tw = agg.emit(meter.snapshot(t=t), runner._geom_quality)
        st = tracker.step(tw, now_s=t)
        idx = len(res.windows)
        res.windows.append(WindowResult(idx, round(t, 3), st.state, sorted(map(str, st.faults))))
        if st.incident is not None and res.confirmed_window is None:
            res.confirmed_window = idx
            res.confirmed_faults = [str(f) for f in st.incident.candidate_faults]
        agg = WindowAggregator("replay", cfg["window"]["seconds"])
        n = 0
    return res


def inject(frames: Iterable[np.ndarray], kind: str | None, start: int, end: int,
           strength: float, seed: int) -> Iterator[np.ndarray]:
    """`kind=None` is the negative control: the clean clip, untouched."""
    if kind is None:
        yield from frames
    else:
        yield from apply_stream(frames, kind, start, end, strength, seed)


def score(res: ReplayResult, kind: str | None, fault_start_s: float, clip_fps: float,
          cfg: dict) -> dict:
    """Pass = expected fault confirmed after onset and no confirmation before it (or at all for
    a negative control: `kind=None` or an injector without an `EXPECTED` entry, e.g. a
    legitimate lighting change)."""
    expected = EXPECTED.get(kind) if kind else None
    win_s = cfg["window"]["seconds"]
    pre = [w for w in res.windows if w.t_end_s < fault_start_s]
    pre_suspect = sum(1 for w in pre if w.faults)
    confirmed_t = (res.windows[res.confirmed_window].t_end_s
                   if res.confirmed_window is not None else None)
    out = {
        "kind": kind or "none",
        "expected": str(expected) if expected else None,
        "windows": len(res.windows),
        "confirmed_faults": res.confirmed_faults,
        "confirmed_at_s": confirmed_t,
        "detection_delay_s": (round(confirmed_t - fault_start_s, 2)
                              if confirmed_t is not None and expected else None),
        "pre_fault_suspect_windows": pre_suspect,
        "window_s": win_s,
    }
    if expected is None:
        out["passed"] = res.confirmed_window is None
    else:
        out["passed"] = (confirmed_t is not None and confirmed_t >= fault_start_s
                         and str(expected) in res.confirmed_faults)
    return out
