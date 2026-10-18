"""Run the F10 live-pipeline soak in SIMULATION."""

from __future__ import annotations

import argparse
from pathlib import Path

import _src_path  # noqa: F401

from benchmarks.soak import run_soak


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=4.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sample-s", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    db_path = run_soak(hours=args.hours, out=args.out, sample_s=args.sample_s, seed=args.seed)
    print(f"SIMULATION EventStore: {db_path}", flush=True)


if __name__ == "__main__":
    main()
