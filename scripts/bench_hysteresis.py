"""Gate F5 hysteresis benchmark (SIMULATION): alert flapping, tracker vs a detector without memory.

Each run is a clean synthetic scene (`SyntheticSource`) replayed through the real probe path
(`benchmarks.replay.telemetry_windows`). After `CALIB_WINDOWS` clean windows, a glitch of one
strong MVP fault lasting 1 or 2 windows starts at each window with probability `p` (flicker, a
hand, a focus hunt, a stuck buffer), and three sustained faults of
`SUSTAINED_WINDOWS` windows are placed at fixed positions. Both detectors see the same windows
and the same `classify_window` verdicts:

* memoryless: alerts on every window with a fault (`TrackerStep.faults` non-empty). It is a
  per-window detector, so it already averages the window's frames: a frame-by-frame detector
  can only flap more, which makes this comparison conservative.
* tracker: `IncidentTracker` alerts on CONFIRMED (`fusion.enter_windows` faulty windows in a
  row); the alert is closed as the orchestrator closes an incident without a successful action
  (`fusion.exit_windows` fault-free windows) and no cooldown is applied, which only adds
  tracker changes.

Changes = alert on/off transitions. Both detectors must change on a sustained fault, so
flapping is the changes outside its guard zone ([start - enter_windows, end + exit_windows]).
Gate: the tracker cuts flapping by >= 50 % in every (fault, p) cell where the memoryless
detector flaps at least `MIN_FLAPS` times, never flaps more in the other cells (the freeze
probe already debounces over `probes.freeze_window` frames), and cuts all changes by >= 50 %
overall. A cell is valid only if every sustained fault is alerted on and every run calibrated,
so a tracker that never alerts cannot pass, and only if every sustained alert closes before
the next sustained fault (or the end of the run), so a tracker that latches on cannot.
Writes a Markdown report; exits 1 on FAIL.
"""

from __future__ import annotations

import argparse
import time
import zlib
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)
import numpy as np
from spike_static_scene import code_revision

from benchmarks.injectors.faults import apply_spatial
from benchmarks.replay import telemetry_windows
from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.capture.sources import SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.contracts.models import IncidentState
from reliability_agent.incidents.fusion import IncidentTracker
from reliability_agent.incidents.state_machine import IncidentStateMachine

KINDS = ("dark", "gaussian_blur", "freeze", "occlude_opaque", "overexpose")  # the 5 MVP faults
P_BAD = (0.1, 0.2, 0.3)
SIGMAS = (1.0, 3.0)
CALIB_WINDOWS = 30
SUSTAINED_WINDOWS = 10
REDUCTION_MIN = 0.5
MIN_FLAPS = 10  # memoryless flaps per cell under which a cell has no flapping to cut
ROOT = Path(__file__).resolve().parents[1]


def schedule(windows: int, p: float, seed: int, *, calib: int = CALIB_WINDOWS,
             sustained: int = SUSTAINED_WINDOWS, salt: str = "") -> tuple[np.ndarray, list[int]]:
    """Bad-window mask over ``calib + windows`` windows and the sustained-fault start indices.

    ``salt`` (fault and noise level) gives every run its own glitch pattern."""
    rng = np.random.default_rng([seed, int(round(p * 1000)), zlib.crc32(salt.encode())])
    bad = np.zeros(calib + windows, dtype=bool)
    i = calib
    while i < len(bad):
        if rng.random() < p:
            length = int(rng.integers(1, 3))
            bad[i:i + length] = True
            i += length
        else:
            i += 1
    starts = [calib + windows * (j + 1) // 4 for j in range(3)]
    for s in starts:
        bad[s:s + sustained] = True
    return bad, starts


def clip(bad: np.ndarray, kind: str, seed: int, sigma: float, per_window: int,
         size: tuple[int, int] = (640, 480)) -> Iterator[np.ndarray]:
    """Frames of the synthetic scene with ``kind`` applied to every frame of each bad window.

    A run of consecutive bad windows is one fault: a freeze repeats the last frame delivered
    before it (a stuck buffer) and an occluder keeps one position for the whole run."""
    src = SyntheticSource(width=size[0], height=size[1], seed=seed, noise_sigma=sigma)
    src.open()
    try:
        last: np.ndarray | None = None
        run_start = -1
        for w, is_bad in enumerate(bad):
            if not is_bad:
                run_start = -1
            elif run_start < 0:
                run_start = w
            for _ in range(per_window):
                img = src.read().image
                if not is_bad:
                    last = img
                    yield img
                elif kind == "freeze":
                    last = img if last is None else last
                    yield last.copy()
                else:
                    yield apply_spatial(img, kind, 1.0, np.random.default_rng([seed, run_start]))
    finally:
        src.close()


def closed(alerted: np.ndarray, starts: list[int], sustained: int = SUSTAINED_WINDOWS) -> int:
    """Sustained faults whose alert is off at least once between their end and the next one."""
    bounds = [*starts[1:], len(alerted)]
    return sum(not alerted[s + sustained:b].all() for s, b in zip(starts, bounds, strict=True))


def run(kind: str, p: float, seed: int, sigma: float, cfg: dict, *, windows: int = 200,
        calib: int = CALIB_WINDOWS, size: tuple[int, int] = (640, 480)) -> dict:
    afps = cfg["camera"]["analytic_fps"]
    per_window = max(1, round(afps * cfg["window"]["seconds"]))
    fu, b = cfg["fusion"], cfg["baseline"]
    bad, starts = schedule(windows, p, seed, calib=calib, salt=f"{kind}/{sigma:g}")
    tracker = IncidentTracker(
        "bench", cfg["faults"], fu["enter_windows"], fu["exit_windows"], fu["cooldown_s"],
        RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]),
        calibration_discard=int(b.get("calibration_discard", 3)))
    naive = alert = False
    fsm_changes = healthy = 0
    naive_at: list[int] = []
    tracker_at: list[int] = []
    alerted = np.zeros(len(bad), dtype=bool)
    prev = IncidentState.HEALTHY
    n = 0
    for n, (t, tw) in enumerate(telemetry_windows(clip(bad, kind, seed, sigma, per_window, size),
                                                  afps, cfg)):
        st = tracker.step(tw, now_s=t)
        if bool(st.faults) != naive:
            naive = not naive
            naive_at.append(n)
        if st.state is not prev:
            fsm_changes += 1
        if alert:
            healthy = 0 if st.faults else healthy + 1
            if healthy >= fu["exit_windows"]:
                tracker.fsm = IncidentStateMachine()
                tracker.reset_healthy()
                alert = False
                tracker_at.append(n)
                fsm_changes += 1
        elif st.incident is not None:
            alert, healthy = True, 0
            tracker_at.append(n)
        alerted[n] = alert
        prev = tracker.fsm.state
    if n + 1 != len(bad):
        raise RuntimeError(f"replay produced {n + 1} windows, schedule has {len(bad)}")
    covered = [bool(alerted[s:s + SUSTAINED_WINDOWS].any()) for s in starts]
    zones = [(s - fu["enter_windows"], s + SUSTAINED_WINDOWS + fu["exit_windows"])
             for s in starts]
    flaps = lambda at: sum(not any(a <= i <= b for a, b in zones) for i in at)  # noqa: E731
    return {"kind": kind, "p": p, "seed": seed, "sigma": sigma, "windows": len(bad),
            "bad_windows": int(bad.sum()), "naive_changes": len(naive_at),
            "tracker_changes": len(tracker_at), "naive_flaps": flaps(naive_at),
            "tracker_flaps": flaps(tracker_at), "fsm_changes": fsm_changes,
            "sustained_covered": sum(covered), "sustained": len(covered),
            "sustained_closed": closed(alerted, starts),
            "calibrated": tracker.baseline.ready}


def reduction(naive: int, tracker: int) -> float | None:
    return None if naive == 0 else 1.0 - tracker / naive


def aggregate(results: list[dict]) -> dict[tuple[str, float], dict]:
    cells: dict[tuple[str, float], dict] = defaultdict(
        lambda: {"runs": 0, "naive": 0, "tracker": 0, "naive_flaps": 0, "tracker_flaps": 0,
                 "fsm": 0, "covered": 0, "closed": 0, "sustained": 0, "calibrated": 0})
    for r in results:
        c = cells[(r["kind"], r["p"])]
        c["runs"] += 1
        c["naive"] += r["naive_changes"]
        c["tracker"] += r["tracker_changes"]
        c["naive_flaps"] += r["naive_flaps"]
        c["tracker_flaps"] += r["tracker_flaps"]
        c["fsm"] += r["fsm_changes"]
        c["covered"] += r["sustained_covered"]
        c["closed"] += r["sustained_closed"]
        c["sustained"] += r["sustained"]
        c["calibrated"] += int(r["calibrated"])
    for c in cells.values():
        c["reduction"] = reduction(c["naive"], c["tracker"])
        c["flap_reduction"] = reduction(c["naive_flaps"], c["tracker_flaps"])
        c["evaluable"] = c["naive_flaps"] >= MIN_FLAPS
        c["valid"] = (c["covered"] == c["closed"] == c["sustained"]
                      and c["calibrated"] == c["runs"])
        cut = (c["flap_reduction"] >= REDUCTION_MIN if c["evaluable"]
               else c["tracker_flaps"] <= c["naive_flaps"])
        c["pass"] = c["valid"] and cut
    return dict(cells)


def gate_ok(cells: dict[tuple[str, float], dict]) -> bool:
    naive = sum(c["naive"] for c in cells.values())
    tracker = sum(c["tracker"] for c in cells.values())
    overall = reduction(naive, tracker)
    return (any(c["evaluable"] for c in cells.values())
            and all(c["pass"] for c in cells.values())
            and overall is not None and overall >= REDUCTION_MIN)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=1, help="seeds per (fault, p, sigma)")
    ap.add_argument("--windows", type=int, default=200, help="windows after calibration")
    ap.add_argument("--out", default="docs/evidence/f5/hysteresis.md")
    args = ap.parse_args()
    cfg = load_config(env=False)
    results: list[dict] = []
    t_all = time.perf_counter()
    for kind in KINDS:
        for p in P_BAD:
            for sigma in SIGMAS:
                for seed in range(args.seeds):
                    t0 = time.perf_counter()
                    r = run(kind, p, seed, sigma, cfg, windows=args.windows)
                    results.append(r)
                    print(f"{kind} p={p:g} sigma={sigma:g} seed={seed}: naive={r['naive_flaps']}/"
                          f"{r['naive_changes']} tracker={r['tracker_flaps']}/"
                          f"{r['tracker_changes']} sustained={r['sustained_covered']}/"
                          f"{r['sustained']} closed={r['sustained_closed']} "
                          f"({time.perf_counter() - t0:.1f}s)")
    cells = aggregate(results)
    ok = gate_ok(cells)
    naive = sum(c["naive"] for c in cells.values())
    tracker = sum(c["tracker"] for c in cells.values())
    rev = code_revision(ROOT)
    fu = cfg["fusion"]
    fmt = lambda v: "-" if v is None else f"{100 * v:.1f} %"  # noqa: E731
    lines = [
        "# Hysteresis vs a memoryless detector (Gate F5) — SIMULATION",
        "",
        f"`SyntheticSource` 640x480 textured scene, sensor noise sigma "
        f"{', '.join(f'{s:g}' for s in SIGMAS)}, {cfg['camera']['analytic_fps']} analytic FPS, "
        f"{cfg['window']['seconds']:g} s windows, real probe path "
        f"(`benchmarks.replay.telemetry_windows`). {CALIB_WINDOWS} clean calibration windows, "
        f"then {args.windows} windows where a glitch of one strong fault (strength 1.0) lasting "
        f"1 or 2 windows starts at each window with probability p, plus 3 sustained faults "
        f"of {SUSTAINED_WINDOWS} windows. "
        f"{args.seeds} seed(s) per (fault, p, sigma). Same `classify_window` verdicts for both: "
        "the memoryless detector alerts on every faulty window (per window, so already more "
        "stable than frame by frame); the tracker alerts on CONFIRMED "
        f"(enter_windows={fu['enter_windows']}) and closes after exit_windows="
        f"{fu['exit_windows']} fault-free windows, without cooldown. Flapping = alert on/off "
        f"changes; flaps = changes outside each sustained fault's guard zone [start - "
        f"enter_windows, end + exit_windows]. Gate: flaps cut by >= {100 * REDUCTION_MIN:.0f} % in "
        f"every cell where the memoryless detector flaps >= {MIN_FLAPS} times, no more flaps in "
        f"the other cells (n/a), all changes cut by >= {100 * REDUCTION_MIN:.0f} % overall; a cell "
        "is valid only if every sustained fault was alerted on, every sustained alert closed "
        "before the next sustained fault (or the end of the run) and every run calibrated. "
        "`fsm changes` also counts the internal HEALTHY <-> SUSPECT moves (not alerts).",
        "",
        "| fault | p | runs | memoryless flaps | tracker flaps | flap cut | memoryless changes "
        "| tracker changes | change cut | fsm changes | sustained alerted | sustained closed "
        "| gate |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (kind, p), c in sorted(cells.items()):
        cut = fmt(c["flap_reduction"]) if c["evaluable"] else "n/a"
        lines.append(f"| {kind} | {p:g} | {c['runs']} | {c['naive_flaps']} | "
                     f"{c['tracker_flaps']} | {cut} | {c['naive']} | {c['tracker']} | "
                     f"{fmt(c['reduction'])} | {c['fsm']} | {c['covered']}/{c['sustained']} | "
                     f"{c['closed']}/{c['sustained']} | {'PASS' if c['pass'] else 'FAIL'} |")
    lines += ["", f"**Overall:** memoryless {naive} changes, tracker {tracker}, reduction "
              f"{fmt(reduction(naive, tracker))} — {'PASS' if ok else 'FAIL'}.", "", "## Runs", "",
              "| fault | p | sigma | seed | bad windows | memoryless flaps/changes "
              "| tracker flaps/changes | fsm | sustained alerted | sustained closed |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['kind']} | {r['p']:g} | {r['sigma']:g} | {r['seed']} | "
                     f"{r['bad_windows']}/{r['windows']} | "
                     f"{r['naive_flaps']}/{r['naive_changes']} | "
                     f"{r['tracker_flaps']}/{r['tracker_changes']} | {r['fsm_changes']} | "
                     f"{r['sustained_covered']}/{r['sustained']} | "
                     f"{r['sustained_closed']}/{r['sustained']} |")
    lines += ["", f"commit: {rev} | runs: {len(results)} | wall time: "
              f"{time.perf_counter() - t_all:.0f} s | generated: "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')} | overall: {'PASS' if ok else 'FAIL'}", ""]
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {out} overall={'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
