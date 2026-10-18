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
    regression_summary = regression["summary"]
    rate = (
        "n/a" if summary["recovery_rate"] is None
        else f"{summary['recovery_rate']:.1%}"
    )
    regression_misses = [
        f"{key.replace(':', ' strength ')}: "
        f"{result['runs'] - result['passed']}/{result['runs']}"
        for key, result in regression_summary["by_fault_strength"].items()
        if result["passed"] != result["runs"]
    ]
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
        "the policy gate when an incident is confirmed.",
        "The frozen-black case uses the agent's local frozen-blackout restart plan "
        "instead of the injected planner; the harness keeps the repeated frame "
        "across restart to exercise rollback.",
        "Other regression cases use scripted, policy-gated, non-remediating proposals.",
        "",
        "| Fault | Strength | Runs | Raw rollback/safe-mode pass | Executed | "
        "Executed pass | Not executed / settings unchanged | Rollback events | "
        "Settings restored |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for key, result in regression["summary"]["by_fault_strength"].items():
        fault, strength = key.rsplit(":", 1)
        lines.append(
            f"| {fault} | {strength} | {result['runs']} | "
            f"{result['passed']} / {result['runs']} | "
            f"{result['executed']} | {result['executed_passed']} / "
            f"{result['executed']} | {result['not_executed']} / "
            f"{result['settings_unchanged']} | {result['rollback_ok']} | "
            f"{result['settings_identical']} |"
        )
    lines.extend([
        "",
        f"Raw rollback/safe-mode result: **{regression_summary['passed']} / "
        f"{regression_summary['runs']}**; successful rollback events: "
        f"{regression_summary['rollback_ok']}; settings equal restored snapshots: "
        f"{regression_summary['settings_identical']}.",
        f"Executed regressions ending in rollback with exact snapshot restoration "
        f"or safe mode: **{regression_summary['executed_passed']} / "
        f"{regression_summary['executed']}**.",
        f"Non-executed runs with unchanged settings: "
        f"**{regression_summary['not_executed_settings_unchanged']} / "
        f"{regression_summary['not_executed']}**. Revised 100% gate: "
        f"{'PASS' if regression_summary['gate_pass'] else 'FAIL'}.",
        "Regression misses by fault/strength: "
        f"{', '.join(regression_misses) if regression_misses else 'none'}.",
        "",
        "Non-executed runs (reason from EventStore):",
    ])
    if regression["non_executed_runs"]:
        for run in regression["non_executed_runs"]:
            strength = run["strength"] if run["strength"] is not None else "n/a"
            lines.append(
                f"- {run['fault']}:{strength}, seed {run['seed']}: "
                f"{run['reason']}; settings_unchanged={run['settings_unchanged']} "
                f"(final_state={run['final_state']}, "
                f"plan_source={run['plan_source'] or 'null'})."
            )
    else:
        lines.append("- None.")
    lines.extend([
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
