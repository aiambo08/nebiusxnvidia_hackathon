"""Gate F1 spike: continuous capture soak with telemetry validity and memory growth.

    python scripts/spike_capture.py --uri 0 --minutes 30
Writes spikes/capture-report.md (commit it as evidence).
"""

import argparse
import time
import tracemalloc

import _src_path  # noqa: F401  (adds src/ to sys.path)
import numpy as np

from reliability_agent.capture import CaptureWorker, OpenCVSource, SyntheticSource
from reliability_agent.config import REPO_ROOT, load_config
from reliability_agent.probes.runner import ProbeRunner, WindowAggregator


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="0")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--synthetic", action="store_true", help="dry run without hardware")
    args = ap.parse_args()
    cfg = load_config()
    src = SyntheticSource() if args.synthetic else OpenCVSource(args.uri)
    worker = CaptureWorker(src, cfg["camera"]["ring_buffer_size"],
                           max_fps=30 if args.synthetic else None)
    runner = ProbeRunner(cfg)
    tracemalloc.start()
    worker.start()
    fps = cfg["camera"]["analytic_fps"]
    windows = valid = 0
    probe_ms: list[float] = []
    mem: list[tuple[float, int]] = []
    t_start = time.monotonic()
    calibrated = False
    while time.monotonic() - t_start < args.minutes * 60:
        agg = WindowAggregator("spike", 1.0)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.0:
            time.sleep(1 / fps)
            f = worker.buffer.latest()
            if f is None:
                continue
            if not calibrated:
                runner.calibrate_reference(f)
                calibrated = True
            p0 = time.perf_counter()
            agg.add(runner.analyse(f))
            probe_ms.append((time.perf_counter() - p0) * 1000)
        windows += 1
        try:
            tw = agg.emit(worker.meter.snapshot())
            valid += int(tw.frames_analyzed > 0 and tw.visual.brightness_p50 is not None)
        except Exception:  # noqa: BLE001
            pass
        if windows % 10 == 0:
            mem.append((time.monotonic() - t_start, tracemalloc.get_traced_memory()[0]))
    worker.stop()
    warm = [m for t, m in mem if t > 60] or [m for _, m in mem]
    growth = (warm[-1] - warm[0]) / max(1, warm[0]) if len(warm) > 1 else 0.0
    snap = worker.meter.snapshot()
    report = REPO_ROOT / "spikes" / "capture-report.md"
    report.parent.mkdir(exist_ok=True)
    p95 = float(np.percentile(probe_ms, 95)) if probe_ms else float("nan")
    lines = [
        "# Capture spike report (Gate F1)", "",
        f"- source: {'synthetic' if args.synthetic else src.kind} | duration: {args.minutes} min",
        f"- windows: {windows}, valid telemetry: {valid} ({100 * valid / max(1, windows):.1f}%)"
        " — gate >= 95%",
        f"- python heap growth after warm-up: {100 * growth:.1f}% — gate <= 10%",
        f"- probe latency p95: {p95:.1f} ms/frame (analytic {fps} FPS)",
        f"- reconnects: {snap.reconnect_count}, dropped frames: {snap.dropped_frames}, "
        f"decode errors: {snap.decode_errors}, "
        f"ring buffer overwritten: {worker.buffer.overwritten}",
        f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    ok = valid >= 0.95 * windows and growth <= 0.10
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
