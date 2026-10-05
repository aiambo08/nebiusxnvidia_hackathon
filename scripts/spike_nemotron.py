"""Gate F0/F1 spike: N live diagnoses against Token Factory; schema validity, latency, cost.

    python scripts/spike_nemotron.py --n 20 [--tier fast|reasoning]
Writes runs/spikes/nemotron.jsonl (no secrets). Spends real credits (~cents).
"""

import argparse
import json
import statistics
import sys
import time

import _src_path  # noqa: F401  (adds src/ to sys.path)

from reliability_agent.config import REPO_ROOT, api_key, load_config
from reliability_agent.contracts.models import (
    Evidence,
    FaultType,
    GeometryMetrics,
    Incident,
    TaskMetrics,
    TelemetryWindow,
    TransportMetrics,
    VisualMetrics,
)
from reliability_agent.nemotron import BudgetGuard
from reliability_agent.nemotron.planner import NemotronPlanner, make_planner
from reliability_agent.policy import PolicyGate

CASES = {
    FaultType.BLACKOUT: dict(brightness_p50=7.0, black_pixel_ratio=0.95, occluded_cell_ratio=0.9),
    FaultType.FOCUS_DRIFT: dict(blur_effect_p50=0.72, edge_density_p50=0.004),
    FaultType.FREEZE: dict(exact_repeat_ratio=1.0, repeated_hash_ratio=1.0, temporal_mse_p50=0.0),
    FaultType.LENS_OCCLUSION: dict(occluded_cell_ratio=0.55, brightness_p50=70.0),
    FaultType.OVEREXPOSURE: dict(white_pixel_ratio=0.62, brightness_p50=228.0),
}
HEALTHY = dict(brightness_p50=110.0, contrast_p50=45.0, black_pixel_ratio=0.01,
               white_pixel_ratio=0.01, laplacian_variance_p50=400.0, blur_effect_p50=0.2,
               edge_density_p50=0.08, temporal_mse_p50=9.0, repeated_hash_ratio=0.0,
               exact_repeat_ratio=0.0, occluded_cell_ratio=0.0)
CAPS = ["exposure", "autofocus", "profiles", "restart"]


def make_incident(fault: FaultType, i: int) -> Incident:
    from datetime import UTC, datetime

    vis = dict(HEALTHY, **CASES[fault])
    tw = TelemetryWindow(camera_id="spike", window_start=datetime.now(UTC), window_seconds=1,
                         frames_analyzed=5,
                         transport=TransportMetrics(capture_fps=29.8 + 0.01 * i,
                                                    frame_age_ms_p95=40),
                         visual=VisualMetrics(**vis), geometry=GeometryMetrics(),
                         task=TaskMetrics(success_rate=0.0, confidence_p50=0.0,
                                          latency_ms_p95=3.0))
    gate = PolicyGate()
    return Incident(camera_id=f"spike-{i}", candidate_faults=[fault], capabilities=CAPS,
                    allowed_actions=gate.allowed_for(CAPS), telemetry=tw,
                    evidence=[Evidence(metric=f"visual.{k}", value=v, baseline=HEALTHY.get(k))
                              for k, v in CASES[fault].items()])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--tier", choices=["fast", "reasoning"], default="fast")
    args = ap.parse_args()
    key = api_key()
    if not key:
        print("NEBIUS_API_KEY is not set.", file=sys.stderr)
        return 2
    cfg = load_config()
    budget = BudgetGuard.from_config(cfg)
    planner = make_planner(cfg, key, budget)
    assert isinstance(planner, NemotronPlanner)
    if args.tier != "fast":
        planner = NemotronPlanner(planner.client, budget, cfg, tier=args.tier)
    out = REPO_ROOT / "runs" / "spikes" / "nemotron.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    faults = list(CASES)
    rows = []
    for i in range(args.n):
        fault = faults[i % len(faults)]
        planner._cache.clear()
        t0 = time.perf_counter()
        res = planner.plan(make_incident(fault, i))
        row = {
            "i": i, "expected": str(fault), "source": res.source, "attempts": res.attempts,
            "valid": res.source == "nemotron" and res.error is None,
            "valid_first_try": res.valid_first_try, "diagnosis": str(res.plan.diagnosis),
            "action": str(res.plan.action.name), "args": res.plan.action.arguments,
            "model": res.usage.model, "prompt_version": res.usage.prompt_version,
            "input_tokens": res.usage.input_tokens, "output_tokens": res.usage.output_tokens,
            "cost_usd": res.usage.estimated_cost_usd,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "error": res.error,
            "ts": time.time(),
        }
        rows.append(row)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"{i:02d} {fault:<15} -> {row['diagnosis']:<15} {row['action']:<24} "
              f"valid={row['valid']} {row['latency_ms']}ms ${row['cost_usd']:.5f}")
    valid = sum(r["valid"] for r in rows)
    correct = sum(r["diagnosis"] == r["expected"] for r in rows)
    mean_cost = statistics.mean(r["cost_usd"] for r in rows) if rows else 0
    print(f"\nschema-valid: {valid}/{len(rows)}  (F1 gate: >= 19/20)")
    print(f"diagnosis == local top fault: {correct}/{len(rows)}")
    print(f"mean cost ${mean_cost:.5f} -> 300 diagnoses ~ ${300 * mean_cost:.2f} (F1: <= 23)")
    print(f"ledger spent this run: ${budget.spent_usd:.4f}")
    return 0 if valid >= 0.95 * len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
