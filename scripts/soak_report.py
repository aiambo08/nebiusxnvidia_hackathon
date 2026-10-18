"""Generate the F10 soak report from a single EventStore database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _src_path  # noqa: F401

from benchmarks.soak import render_report, report_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    report = report_database(args.db)
    out_dir = args.db.resolve().parent
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(report), encoding="utf-8")
    print(f"SIMULATION report: {out_dir / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
