"""Gate F3 latency check: probe set p95 per frame at 720p (target <= 40 ms)."""

import time

import _src_path  # noqa: F401  (adds src/ to sys.path)
import numpy as np

from reliability_agent.capture import SyntheticSource
from reliability_agent.config import load_config
from reliability_agent.probes.runner import ProbeRunner


def main(n: int = 100) -> None:
    cfg = load_config(env=False)
    src = SyntheticSource(width=1280, height=720)
    src.open()
    frames = [src.read() for _ in range(20)]
    runner = ProbeRunner(cfg)
    runner.calibrate_reference(frames[0])
    ms = []
    for i in range(n):
        t0 = time.perf_counter()
        runner.analyse(frames[i % len(frames)])
        ms.append((time.perf_counter() - t0) * 1000)
    print(f"720p probes: p50={np.percentile(ms, 50):.1f} ms  p95={np.percentile(ms, 95):.1f} ms "
          f"(gate <= 40 ms)")


if __name__ == "__main__":
    main()
