#!/usr/bin/env python3
"""Token Factory spend report for the Reliability Agent (read-only, no network).

Usage: python budget_report.py [--repo PATH] [--db runs/agent.sqlite]
       [--spikes runs/spikes/nemotron.jsonl] [--incidents 300]

Reads the usage ledger in the SQLite event store and/or the spike JSONL, prints spend by
model/prompt version, mean cost per call and the projection for N incidents against the caps
in configs/default.yaml. Estimates only: the Nebius console is the authoritative balance.
"""

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load_caps(repo: Path) -> dict:
    cfg = repo / "configs" / "default.yaml"
    if yaml and cfg.exists():
        return yaml.safe_load(cfg.read_text(encoding="utf-8")).get("budget", {})
    return {"total_usd": 30, "soft_cap_usd": 23, "demo_cap_usd": 25, "hard_cap_usd": 27}


def rows_from_db(db: Path) -> list[dict]:
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    cur = con.execute("SELECT model, prompt_version, input_tokens, output_tokens, cost_usd, "
                      "cached FROM usage")
    out = [dict(zip(("model", "prompt_version", "input_tokens", "output_tokens", "cost_usd",
                     "cached"), r, strict=True)) for r in cur]
    con.close()
    return out


def rows_from_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.append({k: r.get(k) for k in ("model", "prompt_version", "input_tokens",
                                              "output_tokens")} | {"cost_usd": r.get("cost_usd"),
                                                                   "cached": 0,
                                                                   "valid": r.get("valid")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--db", default="runs/agent.sqlite")
    ap.add_argument("--spikes", default="runs/spikes/nemotron.jsonl")
    ap.add_argument("--incidents", type=int, default=300)
    a = ap.parse_args()
    repo = Path(a.repo)
    caps = load_caps(repo)
    for label, rows in (("event store", rows_from_db(repo / a.db)),
                        ("spikes", rows_from_jsonl(repo / a.spikes))):
        print(f"\n== {label}: {len(rows)} calls ==")
        if not rows:
            continue
        by = defaultdict(lambda: [0, 0, 0, 0.0])
        for r in rows:
            k = (r["model"], r["prompt_version"])
            by[k][0] += 1
            by[k][1] += r["input_tokens"] or 0
            by[k][2] += r["output_tokens"] or 0
            by[k][3] += r["cost_usd"] or 0.0
        for (m, pv), (n, ti, to, c) in sorted(by.items(), key=lambda x: -x[1][3]):
            print(f"{m} [{pv}]: {n} calls, {ti} in / {to} out tokens, ${c:.4f}")
        paid = [r["cost_usd"] or 0.0 for r in rows if not r.get("cached")]
        total = sum(paid)
        mean = statistics.mean(paid) if paid else 0.0
        if "valid" in rows[0]:
            v = sum(bool(r.get("valid")) for r in rows)
            print(f"schema-valid: {v}/{len(rows)} (F1 gate >= 95%)")
        print(f"spent ${total:.4f} | mean ${mean:.5f}/call | "
              f"{a.incidents} incidents x 2 calls ~ ${2 * a.incidents * mean:.2f}")
        for name in ("soft_cap_usd", "demo_cap_usd", "hard_cap_usd"):
            if name in caps:
                print(f"  {name}: {caps[name]} -> remaining ${caps[name] - total:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
