"""Build F6 golden data at an explicit path.

Usage: python scripts/build_golden.py --out /tmp/golden.jsonl
Pass --force only to replace an existing output.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import _src_path  # noqa: F401  (adds src/ to sys.path)

from benchmarks.golden import build_golden


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    out = args.out
    if out.exists() and not args.force:
        parser.error(f"{out} already exists; pass --force to overwrite")

    cases = build_golden()
    out.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n"
        for case in cases
    )
    try:
        with out.open("w" if args.force else "x", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except FileExistsError:
        parser.error(f"{out} already exists; pass --force to overwrite")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    counts = Counter((case["split"], case["variant"]) for case in cases)
    print(f"Wrote {len(cases)} cases: {out}")
    print(f"SHA256: {digest}")
    for split in ("dev", "test"):
        split_counts = {variant: counts[(split, variant)]
                        for variant in ("base", "no_cap", "injection")}
        print(f"{split}: {sum(split_counts.values())} {split_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
