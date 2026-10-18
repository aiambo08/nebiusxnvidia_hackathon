"""Run or regenerate the pre-registered F10 PR2 SIMULATION experiments."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import _src_path  # noqa: F401

from benchmarks.experiments import generate_report, run_experiments

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "evidence" / "f10"


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "benchmarks" / "reports" / f"f10-experiments-{stamp}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="directory for one EventStore per experiment run")
    parser.add_argument("--report-only", type=Path,
                        help="regenerate the report from EventStores in this directory")
    parser.add_argument("--live", action="store_true",
                        help="optional live Nemotron planner for A2/A3 (max USD 0.05)")
    parser.add_argument("--yes", action="store_true",
                        help="required acknowledgement for --live")
    args = parser.parse_args()

    if args.report_only:
        if args.live:
            parser.error("--report-only cannot be combined with --live")
        report, _ = generate_report(args.report_only, REPORT_DIR)
        print(f"Regenerated {REPORT_DIR / 'experiments.md'}")
        print(f"Code revision: {report.get('code_revision')}")
        return

    out_dir = args.out or _default_out()
    run_experiments(out_dir, live=args.live, yes=args.yes)
    report, _ = generate_report(out_dir, REPORT_DIR)
    print(f"EventStores: {out_dir}")
    print(f"Report: {REPORT_DIR / 'experiments.md'}")
    print(f"Code revision: {report.get('code_revision')}")


if __name__ == "__main__":
    main()
