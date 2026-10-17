"""Evaluate the frozen F6 golden set; live Token Factory calls require explicit --yes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import _src_path  # noqa: F401  (adds src/ to sys.path)
from spike_static_scene import code_revision

from benchmarks.golden import grade, summarize
from reliability_agent.config import REPO_ROOT, api_key, load_config
from reliability_agent.contracts.models import Incident
from reliability_agent.nemotron import BudgetGuard, ModelPrice
from reliability_agent.nemotron.planner import NemotronPlanner, RuleBasedPlanner, make_planner
from reliability_agent.policy import PolicyGate

MAX_INPUT_TOKENS_PER_CALL = 6000
MAX_PLANNER_ATTEMPTS = 2
PROMPT_VERSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def load_golden(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or REPO_ROOT / "benchmarks" / "golden" / "golden_v1.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def select_cases(cases: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    return cases if split == "all" else [case for case in cases if case["split"] == split]


def estimate_cost(cfg: dict[str, Any], tier: str, case_count: int,
                  repeats: int, planner: str = "nemotron") -> dict[str, Any]:
    """Bound retries using 6k input tokens and configured max output tokens per API call."""
    case_runs = case_count * repeats
    if planner == "rules":
        return {
            "model": "local-rules",
            "case_runs": case_runs,
            "max_api_calls": 0,
            "input_tokens_per_call": 0,
            "output_tokens_per_call": 0,
            "per_call_usd": 0.0,
            "upper_bound_usd": 0.0,
        }
    model = cfg["nebius"]["models"][tier]
    price_data = cfg["nebius"].get("prices", {}).get(model)
    if price_data is None:
        raise ValueError(f"no configured token price for model {model!r}")
    price = ModelPrice(float(price_data["input"]), float(price_data["output"]))
    max_api_calls = case_runs * MAX_PLANNER_ATTEMPTS
    output_tokens = int(cfg["planner"]["max_output_tokens"])
    per_call = price.cost(MAX_INPUT_TOKENS_PER_CALL, output_tokens)
    return {
        "model": model,
        "case_runs": case_runs,
        "max_api_calls": max_api_calls,
        "input_tokens_per_call": MAX_INPUT_TOKENS_PER_CALL,
        "output_tokens_per_call": output_tokens,
        "per_call_usd": per_call,
        "upper_bound_usd": per_call * max_api_calls,
    }


def run_eval(cases: list[dict[str, Any]], planner: Any, repeats: int = 3,
             output_path: Path | None = None, *, baseline: bool = False
             ) -> list[dict[str, Any]]:
    """Run an injectable planner on each case/repeat and optionally append JSONL rows."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in cases:
        for repeat in range(1, repeats + 1):
            cache = getattr(planner, "_cache", None)
            if hasattr(cache, "clear"):
                cache.clear()
            incident = Incident.model_validate(case["incident"])
            started = time.perf_counter()
            outcome = planner.plan(incident)
            wall_latency_ms = (time.perf_counter() - started) * 1000
            row = grade(case, outcome, PolicyGate(), baseline=baseline)
            row.update({
                "case_id": case["case_id"],
                "split": case["split"],
                "scenario": case["scenario"],
                "variant": case["variant"],
                "seed": case["seed"],
                "expected_fault": case["expected_fault"],
                "expected_actions": case["expected_actions"],
                "repeat": repeat,
                "latency_ms": round(wall_latency_ms, 1),
                "usage_latency_ms": row["latency_ms"],
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            })
            rows.append(row)
            if output_path is not None:
                with output_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return rows


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def _report_paths(report_dir: Path, prompt_version: str, model: str,
                  split: str, planner: str) -> tuple[Path, Path]:
    base = (f"golden-rules-baseline-{split}" if planner == "rules"
            else f"golden-{_slug(prompt_version)}-{_slug(model)}-{split}")
    stem = base
    suffix = 2
    while (report_dir / f"{stem}.md").exists() or (report_dir / f"{stem}.json").exists():
        stem = f"{base}-{suffix}"
        suffix += 1
    return report_dir / f"{stem}.md", report_dir / f"{stem}.json"


def _render_markdown(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    gate = summary["gate"]
    cost_per_call = gate["mean_cost_per_call"]
    cost_per_incident = gate["mean_cost_per_incident"]
    budget_spent = summary["budget_spent_usd"]
    cost_per_call_text = "not scored" if cost_per_call is None else f"${cost_per_call:.8f}"
    cost_per_incident_text = (
        "not scored" if cost_per_incident is None else f"${cost_per_incident:.8f}")
    budget_spent_text = "not reported" if budget_spent is None else f"${budget_spent:.8f}"
    title = ("F6 deterministic rules baseline" if meta["planner"] == "rules"
             else "F6 golden-set evaluation")
    lines = [
        f"# {title} — {meta['split']}",
        "",
        f"- Commit: `{meta['commit']}`",
        f"- Golden file SHA256: `{meta['golden_sha256']}`",
        f"- Generated: {meta['generated']}",
        f"- Model: `{meta['model']}`",
        f"- Prompt version: `{meta['prompt_version']}`",
        f"- Evaluated rows: {summary['row_count']}",
        f"- Run cost: ${summary['run_total_usd']:.8f}",
        f"- BudgetGuard spent: {budget_spent_text}",
    ]
    if meta["planner"] == "nemotron":
        lines.extend(["", meta["evaluation_note"]])
    lines += [
        "",
        "## F6 gate (test split pooled across repeats)",
        "",
        "| Box | Result | Value | Threshold |",
        "|---|---:|---:|---:|",
    ]
    labels = {
        "schema_valid": "Schema-valid rate",
        "action_accuracy": "Action accuracy",
        "projected_300": "Projected cost for 300 incidents",
    }
    for key, box in gate["boxes"].items():
        value = box["value"]
        shown = "not scored" if value is None else (
            f"${value:.6f}" if key == "projected_300" else f"{value:.3%}")
        threshold = (f"${box['threshold']:.2f}" if key == "projected_300"
                     else f"{box['threshold']:.0%}")
        lines.append(f"| {labels[key]} | **{box['status']}** | {shown} | {threshold} |")

    lines += [
        "",
        "## Secondary metrics",
        "",
        f"- Test rows: {gate['row_count']}",
        f"- Mean cost per API call: {cost_per_call_text}",
        f"- Mean cost per incident: {cost_per_incident_text}",
        f"- Valid on first try: {gate['valid_first_try_rate']}",
        f"- Policy accepted: {gate['policy_ok_rate']}",
        f"- Diagnosis accuracy: {gate['diagnosis_accuracy']}",
        f"- Latency p50/p95: {summary['latency_ms']['p50']} / "
        f"{summary['latency_ms']['p95']} ms",
        f"- Models: {', '.join(summary['model']) or 'none'}",
        f"- Prompt versions: {', '.join(summary['prompt_version']) or 'none'}",
        "",
        "### Accuracy by scenario and variant",
        "",
        "| Scenario / variant | Cases | Accuracy |",
        "|---|---:|---:|",
    ]
    for name, metrics in summary["per_scenario_variant_accuracy"].items():
        accuracy = metrics["accuracy"]
        lines.append(
            f"| {name} | {metrics['count']} | "
            f"{'not scored' if accuracy is None else f'{accuracy:.3%}'} |")
    lines += ["", "### Action confusion", ""]
    if summary["action_confusion"]:
        lines.extend(f"- `{pair}`: {count}"
                     for pair, count in summary["action_confusion"].items())
    else:
        lines.append("- No evaluated rows.")
    return "\n".join(lines) + "\n"


def write_reports(report_dir: Path, summary: dict[str, Any], *,
                  split: str, prompt_version: str, model: str, golden_sha256: str,
                  commit: str, generated: str, planner: str = "nemotron"
                  ) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path, json_path = _report_paths(report_dir, prompt_version, model, split, planner)
    evaluation_note = (
        "This box measures whether the planner follows the local diagnosis and respects "
        "capability/policy constraints; candidate_faults[0] determines the label in every "
        "case and synthetic defocus carries focus_ok=false, so it is not a test of independent "
        f"diagnosis. Deterministic rules baseline: "
        f"[golden-rules-baseline-{split}.md](golden-rules-baseline-{split}.md).")
    meta = {
        "planner": planner,
        "split": split,
        "prompt_version": prompt_version,
        "model": model,
        "golden_sha256": golden_sha256,
        "commit": commit,
        "generated": generated,
    }
    if planner == "nemotron":
        meta["evaluation_note"] = evaluation_note
    markdown_path.write_text(_render_markdown(meta, summary), encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps({"meta": meta, "summary": summary}, indent=2,
                                    sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return markdown_path, json_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("test", "dev", "all"), default="test")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tier", choices=("fast", "reasoning"), default="fast")
    parser.add_argument("--planner", choices=("nemotron", "rules"), default="nemotron")
    parser.add_argument("--prompt-version")
    parser.add_argument("--max-usd", type=float, default=0.50)
    parser.add_argument("--yes", action="store_true", help="allow live Token Factory calls")
    return parser


def main(argv: list[str] | None = None, *, sdk_client: Any = None,
         cases_path: Path | None = None, report_dir: Path | None = None,
         runs_dir: Path | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if not math.isfinite(args.max_usd) or args.max_usd < 0:
        parser.error("--max-usd must be a finite non-negative amount")

    cfg = load_config(env=False)
    if args.prompt_version is not None:
        if not PROMPT_VERSION_RE.fullmatch(args.prompt_version):
            parser.error("--prompt-version may contain only letters, digits, '_' and '-'")
        cfg["planner"]["prompt_version"] = args.prompt_version
    prompt_path = (REPO_ROOT / "src" / "reliability_agent" / "nemotron" / "prompts"
                   / f"{cfg['planner']['prompt_version']}.md")
    if not prompt_path.is_file():
        parser.error(f"prompt version {cfg['planner']['prompt_version']!r} does not exist")

    golden_path = cases_path or REPO_ROOT / "benchmarks" / "golden" / "golden_v1.jsonl"
    cases = select_cases(load_golden(golden_path), args.split)
    estimate = estimate_cost(cfg, args.tier, len(cases), args.repeats, args.planner)
    print(f"Cases: {len(cases)} × {args.repeats} repeats = {estimate['case_runs']} case runs")
    print(f"Maximum API calls (including one repair retry per case): "
          f"{estimate['max_api_calls']}")
    print(f"Upper-bound cost: ${estimate['upper_bound_usd']:.6f} "
          f"({estimate['input_tokens_per_call']} input + "
          f"{estimate['output_tokens_per_call']} output tokens per call; "
          f"model {estimate['model']})")
    if args.planner == "nemotron" and estimate["upper_bound_usd"] > args.max_usd:
        print(f"Estimate exceeds --max-usd ${args.max_usd:.6f}; no calls made.", file=sys.stderr)
        return 3
    if args.planner == "nemotron" and not args.yes:
        print("Dry run only; pass --yes to make live Token Factory calls.")
        return 0

    budget = BudgetGuard.from_config(cfg)
    if args.planner == "rules":
        planner = RuleBasedPlanner()
    else:
        key = api_key()
        if not key:
            print("NEBIUS_API_KEY is not set.", file=sys.stderr)
            return 2
        planner = make_planner(cfg, key, budget, sdk_client=sdk_client)
        if not isinstance(planner, NemotronPlanner):
            raise TypeError("F6 evaluation requires the Nemotron planner")
        if args.tier != "fast":
            planner = NemotronPlanner(planner.client, budget, cfg, tier=args.tier)

    generated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_root = runs_dir or REPO_ROOT / "runs" / "eval"
    run_path = run_root / f"{stamp}.jsonl"
    rows = run_eval(cases, planner, args.repeats, run_path,
                    baseline=args.planner == "rules")
    summary = summarize(rows, cfg, budget_spent_usd=budget.spent_usd, split=args.split)
    golden_sha256 = hashlib.sha256(golden_path.read_bytes()).hexdigest()
    reports = write_reports(
        report_dir or REPO_ROOT / "docs" / "evidence" / "f6",
        summary,
        split=args.split,
        prompt_version=planner.prompt_version if isinstance(planner, NemotronPlanner) else "rules",
        model=planner.model if isinstance(planner, NemotronPlanner) else "local-rules",
        golden_sha256=golden_sha256,
        commit=code_revision(),
        generated=generated,
        planner=args.planner,
    )
    print(f"Run ledger: {run_path}")
    print(f"Reports: {reports[0]} (+ {reports[1].name})")
    for name, box in summary["gate"]["boxes"].items():
        print(f"{box['status']} {name}: {box['value']}")
    print(f"Run total: ${summary['run_total_usd']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
