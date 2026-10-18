"""Run the deterministic offline F8 recovery and regression benchmark."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.recovery import (
    RECOVERY_GRID,
    run_recovery_benchmark,
    run_regression_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]


def _code_sha() -> str:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, encoding="utf-8"
    )
    if status.strip():
        raise RuntimeError("Run the final benchmark from a clean committed worktree.")
    return sha


def _markdown(code_sha: str, recovery: dict, regression: dict) -> str:
    summary = recovery["summary"]
    rate = (
        "n/a" if summary["recovery_rate"] is None
        else f"{summary['recovery_rate']:.1%}"
    )
    lines = [
        "# F8 Offline Recovery Benchmark",
        "",
        "**SIMULATION** — deterministic `SyntheticSource` runs; no network or paid services.",
        f"Code commit: `{code_sha}`",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Recovery grid",
        "",
        "Pre-registered cases: " + ", ".join(
            f"{fault}={list(strengths)}" for fault, strengths in RECOVERY_GRID
        ) + "; seeds `0..9`.",
        "",
        "| Fault | Strength | Runs | Recovered auto / recoverable | Needs human | Timeout |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, result in summary["by_fault_strength"].items():
        fault, strength = key.rsplit(":", 1)
        lines.append(
            f"| {fault} | {strength} | {result['runs']} | "
            f"{result['recovered_auto']} / {result['recoverable']} | "
            f"{result['needs_human']} | {result['timeout']} |"
        )
    lines.extend([
        "",
        f"Global: **{summary['recovered_auto']} / {summary['recoverable']}** "
        f"recoverable cases ({rate}); "
        f"{summary['needs_human']} needs-human, {summary['timeout']} timeouts. "
        f"Gate ≥85%: {'PASS' if summary['gate_pass'] else 'FAIL'}.",
        "",
        "## Deliberate regression grid",
        "",
        "Same pre-registered faults and seeds `0..4`; actions are proposed through "
        "the policy gate.",
        "",
        "| Fault | Strength | Runs | Rollback/safe-mode pass | Rollback events | "
        "Settings restored |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for key, result in regression["summary"]["by_fault_strength"].items():
        fault, strength = key.rsplit(":", 1)
        lines.append(
            f"| {fault} | {strength} | {result['runs']} | "
            f"{result['passed']} / {result['runs']} | {result['rollback_ok']} | "
            f"{result['settings_identical']} |"
        )
    lines.extend([
        "",
        f"Rollback/safe-mode pass: **{regression['summary']['passed']} / "
        f"{regression['summary']['runs']}**; successful rollback events: "
        f"{regression['summary']['rollback_ok']}; settings equal restored snapshots: "
        f"{regression['summary']['settings_identical']}. "
        f"100% gate: {'PASS' if regression['summary']['gate_pass'] else 'FAIL'}.",
        "",
        "Per-case event-derived outcomes and regression checks are in the companion JSON.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/evidence/f8")
    args = parser.parse_args()
    code_sha = _code_sha()
    recovery = run_recovery_benchmark()
    regression = run_regression_benchmark()
    report = {
        "title": "F8 Offline Recovery Benchmark",
        "label": "SIMULATION",
        "code_sha": code_sha,
        "generated_at": datetime.now(UTC).isoformat(),
        "recovery": recovery,
        "regression": regression,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / "recovery-bench.json"
    markdown_path = args.out / "recovery-bench.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(_markdown(code_sha, recovery, regression), encoding="utf-8")
    print(f"Recovery report: {markdown_path}")
    print(f"JSON report: {json_path}")
    print(json.dumps({
        "recovery": recovery["summary"],
        "regression": regression["summary"],
        "code_sha": code_sha,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
