"""Gate F2: enforce line AND branch coverage of a package from a coverage.py JSON report.

    pytest <tests> --cov=reliability_agent.capture --cov-report=json:coverage.json
    python scripts/check_coverage.py coverage.json --min-lines 80 --min-branches 75

`--cov-fail-under` only checks coverage.py's combined figure, which hides weak branch coverage.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--min-lines", type=float, required=True)
    ap.add_argument("--min-branches", type=float, required=True)
    args = ap.parse_args()
    totals = json.loads(args.report.read_text(encoding="utf-8"))["totals"]
    lines = 100.0 * totals["covered_lines"] / max(1, totals["num_statements"])
    branches = 100.0 * totals["covered_branches"] / max(1, totals["num_branches"])
    print(f"lines {lines:.1f}% (gate >= {args.min_lines:.0f}%) | "
          f"branches {branches:.1f}% (gate >= {args.min_branches:.0f}%)")
    ok = lines >= args.min_lines and branches >= args.min_branches
    print("coverage gate:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
