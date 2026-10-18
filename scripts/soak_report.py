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
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    report = report_database(args.db)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "soak.json"
    markdown_path = args.out_dir / "soak.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_report(report), encoding="utf-8")
    print(f"SIMULATION report: {markdown_path}", flush=True)


if __name__ == "__main__":
    main()
