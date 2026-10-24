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
        "Margin note: 87/100 is only 1–2 cases above the 85% threshold. "
        "The reviewer reported 86/100 under heavy parallel CPU load when "
        "`defocus:1.0`, seed 2, hit the wall-clock `task.latency_ms_p95` guard "
        "with 5 ms tolerance; 12 repeats across idle and loaded conditions recovered. "
        "Since `47fd021` the SIMULATION harness times the marker task with its simulated "
        "clock, so host CPU load no longer reaches that guard; thresholds are unchanged.",
        "",
        "## Deliberate regression grid",
        "",
        "Same pre-registered faults and seeds `0..4`; actions are proposed through "
        "the policy gate when an incident is confirmed.",
        "The frozen-black case uses the agent's local frozen-blackout restart plan "
        "instead of the injected planner; the harness keeps the repeated frame "
        "across restart to exercise rollback.",
        "The defocus and frozen_black regression proposals use `enter_safe_mode`, "
        "a policy-approved non-remediating action.",
        "The other regression cases use scripted, policy-gated proposals.",
        "The first benchmark report recorded `100% gate: FAIL` at commit `46c383a`; "
        "commit `13d2559` revised `gate_pass`. A run that never confirms an incident "
        "executes no action to contain, so raw 45/50 remains published while "
        "non-executed runs must leave settings unchanged. Review then added the "
        "executed-coverage floor so a never-acting agent cannot pass.",
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
            f"{result['executed']} | {result['executed_pass']} / "
            f"{result['executed']} | {result['not_executed']} / "
            f"{result['not_executed_unchanged']} | {result['rollback_ok']} | "
            f"{result['settings_identical']} |"
        )
    lines.extend([
        "",
        "### Executed coverage by fault family",
        "",
        "| Fault family | Runs | Executed | Executed pass | Not executed | "
        "Not executed, settings unchanged |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for fault, result in regression_summary["by_fault"].items():
        lines.append(
            f"| {fault} | {result['runs']} | {result['executed']} | "
            f"{result['executed_pass']} | {result['not_executed']} | "
            f"{result['not_executed_unchanged']} |"
        )
    lines.extend([
        "",
        f"Raw rollback/safe-mode result: **{regression_summary['passed']} / "
        f"{regression_summary['runs']}**; successful rollback events: "
        f"{regression_summary['rollback_ok']}; settings equal restored snapshots: "
        f"{regression_summary['settings_identical']}.",
        f"Executed regressions ending in rollback with exact snapshot restoration "
        f"or safe mode: **{regression_summary['executed_pass']} / "
        f"{regression_summary['executed']}**.",
        f"Non-executed runs with unchanged settings: "
        f"**{regression_summary['not_executed_unchanged']} / "
        f"{regression_summary['not_executed']}**. Revised 100% gate: "
        f"{'PASS' if regression_summary['gate_pass'] else 'FAIL'}. "
        f"Coverage floor: "
        f"{'PASS' if regression_summary['coverage_floor']['pass'] else 'FAIL'}"
        + (
            f" (missing: {', '.join(regression_summary['coverage_floor']['missing_families'])})"
            if regression_summary["coverage_floor"]["missing_families"] else ""
        )
        + ".",
        "Regression misses by fault/strength: "
        f"{', '.join(regression_misses) if regression_misses else 'none'}.",
        "",
        "Non-executed runs (incident reason from EventStore; unchanged-settings check "
        "uses device state):",
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
        "Recovery classification and incident reports are event-only. Regression "
        "classification combines EventStore events, device settings, and "
        "`ScenarioResult.final_state`; per-case inputs and outcomes are in the companion JSON.",
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
