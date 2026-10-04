"""Commit-or-rollback rule (report, Phase 8). Parameters are initial and must be calibrated.

Commit iff ALL hold (guard changes within `guard_abs_tolerance` are treated as noise):
1. primary metric improves >= min_relative_improvement OR reaches recovery_ratio * baseline;
2. no guard metric regresses more than max_guard_regression;
3. the original faults are absent for `healthy_windows_required` consecutive windows;
4. no new fault appears in those windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from reliability_agent.contracts.models import (
    FaultType,
    TelemetryWindow,
    VerificationSpec,
    VerificationStatus,
)

LOWER_IS_BETTER = {
    "task.latency_ms_p95", "transport.frame_age_ms_p95", "visual.blur_effect_p50",
    "transport.dropped_frames", "visual.occluded_cell_ratio", "visual.exact_repeat_ratio",
}


@dataclass
class VerificationDecision:
    status: VerificationStatus
    reasons: list[str] = field(default_factory=list)
    before: dict[str, float] = field(default_factory=dict)
    after: dict[str, float] = field(default_factory=dict)


def _median(windows: list[TelemetryWindow], metric: str) -> float | None:
    vals = [w.flat().get(metric) for w in windows]
    vals = [v for v in vals if v is not None]
    return float(np.median(vals)) if vals else None


class Verifier:
    def __init__(self, min_relative_improvement: float = 0.10, baseline_recovery_ratio: float = 0.95,
                 max_guard_regression: float = 0.10, healthy_windows_required: int = 2,
                 guard_abs_tolerance: dict[str, float] | None = None) -> None:
        self.guard_abs = guard_abs_tolerance or {}
        self.min_rel = min_relative_improvement
        self.recovery = baseline_recovery_ratio
        self.max_guard = max_guard_regression
        self.healthy_required = healthy_windows_required

    @classmethod
    def from_config(cls, cfg: dict) -> Verifier:
        v = cfg["verification"]
        return cls(v["min_relative_improvement"], v["baseline_recovery_ratio"],
                   v["max_guard_regression"], v["healthy_windows_required"],
                   v.get("guard_abs_tolerance"))

    def decide(
        self,
        before: list[TelemetryWindow],
        after: list[TelemetryWindow],
        after_faults: list[set[FaultType]],
        original_faults: set[FaultType],
        spec: VerificationSpec,
        baseline_primary: float | None = None,
        execution_ok: bool = True,
    ) -> VerificationDecision:
        if not execution_ok:
            return VerificationDecision(VerificationStatus.EXECUTION_FAILED, ["execution failed"])
        if len(after) < self.healthy_required or not before:
            return VerificationDecision(VerificationStatus.INCONCLUSIVE, ["not enough windows"])
        metrics = [spec.primary_metric, *spec.guard_metrics]
        b = {m: v for m in metrics if (v := _median(before, m)) is not None}
        a = {m: v for m in metrics if (v := _median(after[-self.healthy_required:], m)) is not None}
        reasons: list[str] = []
        ok = True

        pm = spec.primary_metric
        min_rel = max(self.min_rel, spec.minimum_relative_improvement)
        if pm not in a or pm not in b:
            return VerificationDecision(VerificationStatus.INCONCLUSIVE,
                                        [f"primary metric {pm} unavailable"], b, a)
        lower = pm in LOWER_IS_BETTER
        pb, pa = b[pm], a[pm]
        gain = (pb - pa) if lower else (pa - pb)
        rel = gain / abs(pb) if abs(pb) > 1e-9 else (gain if gain > 0 else 0.0)
        recovered = baseline_primary is not None and (
            pa <= baseline_primary / self.recovery if lower else pa >= self.recovery * baseline_primary
        )
        if rel >= min_rel or recovered:
            reasons.append(f"{pm}: {pb:.3f} -> {pa:.3f} (rel {rel:+.0%})")
        else:
            ok = False
            reasons.append(f"{pm} did not improve enough ({pb:.3f} -> {pa:.3f}, rel {rel:+.0%})")

        for g in spec.guard_metrics:
            if g not in a or g not in b or abs(b[g]) < 1e-9:
                continue
            if abs(a[g] - b[g]) <= self.guard_abs.get(g, 0.0):
                continue  # within measurement noise
            worse = (a[g] - b[g]) / abs(b[g]) if g in LOWER_IS_BETTER else (b[g] - a[g]) / abs(b[g])
            if worse > self.max_guard:
                ok = False
                reasons.append(f"guard {g} regressed {worse:.0%}")

        tail = after_faults[-self.healthy_required:]
        if any(original_faults & f for f in tail):
            ok = False
            reasons.append("original fault still present")
        new = set().union(*tail) - original_faults if tail else set()
        if new:
            ok = False
            reasons.append(f"new faults appeared: {sorted(map(str, new))}")

        status = VerificationStatus.COMMITTED if ok else VerificationStatus.ROLLED_BACK
        return VerificationDecision(status, reasons, b, a)
