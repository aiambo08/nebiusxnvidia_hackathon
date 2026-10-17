"""Build the frozen F6 golden data file from the offline synthetic scenarios."""

import hashlib
import json
from collections import Counter

import _src_path  # noqa: F401  (adds src/ to sys.path)

from benchmarks.golden import build_golden
from reliability_agent.config import REPO_ROOT


def main() -> int:
    cases = build_golden()
    out = REPO_ROOT / "benchmarks" / "golden" / "golden_v1.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n"
        for case in cases
    )
    out.write_text(content, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    counts = Counter((case["split"], case["variant"]) for case in cases)
    print(f"Wrote {len(cases)} cases: {out.relative_to(REPO_ROOT)}")
    print(f"SHA256: {digest}")
    for split in ("dev", "test"):
        split_counts = {variant: counts[(split, variant)]
                        for variant in ("base", "no_cap", "exposure_edge", "injection")}
        print(f"{split}: {sum(split_counts.values())} {split_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
