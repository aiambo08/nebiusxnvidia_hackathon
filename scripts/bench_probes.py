"""Gate F3 probe latency (SIMULATION): `ProbeRunner.analyse` per frame on a synthetic scene.

Box: probe set p95 <= 40 ms/frame at 720p, 5 analytic FPS. The default run measures exactly that
(1280x720 frames, back-to-back, nothing else in the process). The flags reproduce, one at a time,
the conditions under which `scripts/spike_capture.py` measures its live probe p95, so a gap
between the two numbers can be attributed on the same machine:

    --size WxH      input resolution (probes downscale to <= 640 px first; webcams give 640x480,
                    phones 1920x1080)
    --paced         one frame every 1/analytic_fps s, as the live loop does (lets a laptop CPU
                    clock down between bursts)
    --worker        a CaptureWorker pulling a synthetic source at 30 FPS in the same process
                    (GIL and OpenCV thread contention; implies --paced)
    --tracemalloc   tracemalloc active, as spike_capture.py needs for its heap-growth gate
    --breakdown     p50/p95 per probe, measured inside the real `analyse` call

Prints machine facts (CPU count, OpenCV threads, Python, OpenCV, platform) so numbers from
different machines can be compared. No camera, no network, no paid calls.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
import tracemalloc
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import _src_path  # noqa: F401  (adds src/ to sys.path)
import cv2
import numpy as np

from reliability_agent.capture import CaptureWorker, SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.probes import runner as runner_mod
from reliability_agent.probes.runner import ProbeRunner

GATE_MS = 40.0


def _timed(name: str, fn: Callable[..., Any], sink: dict[str, list[float]]) -> Callable[..., Any]:
    def wrapped(*a: Any, **k: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            sink[name].append((time.perf_counter() - t0) * 1000)

    return wrapped


def _instrument(runner: ProbeRunner) -> tuple[dict[str, list[float]], Callable[[], None]]:
    """Time each stage of `analyse` without changing its code path; returns (sink, restore)."""
    sink: dict[str, list[float]] = defaultdict(list)
    originals: list[tuple[Any, str, Any]] = []
    targets: list[tuple[Any, str, str]] = [
        (runner_mod, name, name)
        for name in ("downscale", "exposure_probe", "sharpness_probe", "occlusion_probe")
    ] + [(runner.freeze, "update", "freeze"), (runner.geometry, "measure", "geometry"),
         (runner.task, "run", "task")]
    for obj, attr, label in targets:
        fn = getattr(obj, attr)
        originals.append((obj, attr, fn))
        setattr(obj, attr, _timed(label, fn, sink))

    def restore() -> None:
        for obj, attr, fn in originals:
            setattr(obj, attr, fn)

    return sink, restore


def _pct(xs: list[float], q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def run(size: tuple[int, int] = (1280, 720), n: int = 100, *, paced: bool = False,
        worker: bool = False, trace: bool = False, breakdown: bool = False) -> dict[str, Any]:
    cfg = load_config(env=False)
    fps = cfg["camera"]["analytic_fps"]
    w, h = size
    runner = ProbeRunner(cfg)
    sink, restore = _instrument(runner) if breakdown else ({}, lambda: None)
    cw: CaptureWorker | None = None
    if worker:
        cw = CaptureWorker(SyntheticSource(width=w, height=h), buffer_size=64, max_fps=30)
        cw.start()
        paced = True
        frames = []
    else:
        src = SyntheticSource(width=w, height=h)
        src.open()
        frames = [src.read() for _ in range(20)]
    if trace:
        tracemalloc.start()
    ms: list[float] = []
    try:
        calibrated = False
        i = 0
        while len(ms) < n:
            if paced:
                time.sleep(1 / fps)
            f = cw.buffer.latest() if cw else frames[i % len(frames)]
            i += 1
            if f is None:
                continue
            if not calibrated:
                runner.calibrate_reference(f)
                calibrated = True
                continue
            t0 = time.perf_counter()
            runner.analyse(f)
            ms.append((time.perf_counter() - t0) * 1000)
    finally:
        restore()
        if trace:
            tracemalloc.stop()
        if cw:
            cw.stop()
    return {
        "size": f"{w}x{h}", "n": len(ms), "paced": paced, "worker": worker, "tracemalloc": trace,
        "p50_ms": round(_pct(ms, 50), 1), "p95_ms": round(_pct(ms, 95), 1),
        "gate_ms": GATE_MS, "gate_pass": _pct(ms, 95) <= GATE_MS,
        "breakdown_p95_ms": {k: round(_pct(v, 95), 1) for k, v in sink.items()},
        "breakdown_p50_ms": {k: round(_pct(v, 50), 1) for k, v in sink.items()},
        "machine": machine_facts(),
    }


def machine_facts() -> dict[str, Any]:
    return {"cpus": os.cpu_count(), "cv2_threads": cv2.getNumThreads(),
            "python": platform.python_version(), "opencv": cv2.__version__,
            "platform": f"{platform.system()} {platform.machine()}"}


def format_report(r: dict[str, Any]) -> str:
    conds = ", ".join(k for k in ("paced", "worker", "tracemalloc") if r[k]) or "isolated"
    lines = [f"probes {r['size']} ({conds}, n={r['n']}): p50={r['p50_ms']:.1f} ms  "
             f"p95={r['p95_ms']:.1f} ms  (gate <= {r['gate_ms']:.0f} ms: "
             f"{'PASS' if r['gate_pass'] else 'FAIL'})"]
    if r["breakdown_p95_ms"]:
        lines.append("  per-probe p95 ms: " + "  ".join(
            f"{k}={v:.1f}" for k, v in r["breakdown_p95_ms"].items()))
    m = r["machine"]
    lines.append(f"  machine: cpus={m['cpus']} cv2_threads={m['cv2_threads']} "
                 f"python={m['python']} opencv={m['opencv']} platform={m['platform']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--size", default="1280x720", help="WxH input frames (default 1280x720)")
    ap.add_argument("--frames", type=int, default=100, help="analysed frames (default 100)")
    ap.add_argument("--paced", action="store_true")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--tracemalloc", action="store_true")
    ap.add_argument("--breakdown", action="store_true")
    args = ap.parse_args(argv)
    w, h = (int(x) for x in args.size.lower().split("x"))
    r = run((w, h), args.frames, paced=args.paced, worker=args.worker, trace=args.tracemalloc,
            breakdown=args.breakdown)
    print(format_report(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
