"""Run every deterministic SIMULATION scenario end-to-end (no network, no credits).

    python scripts/demo_offline.py                # rule-based planner
    python scripts/demo_offline.py --nemotron     # real Nemotron on Token Factory (costs credits)
"""

import sys

import _src_path  # noqa: F401  (adds src/ to sys.path)

from reliability_agent.cli import main

if __name__ == "__main__":
    if "--nemotron" in sys.argv:
        names = ["dark", "defocus", "freeze", "occlusion", "overexposure"]
        rc = 0
        for n in names:
            rc |= main(["scenario", n, "--planner", "nemotron"])
        raise SystemExit(rc)
    raise SystemExit(main(["all"]))
