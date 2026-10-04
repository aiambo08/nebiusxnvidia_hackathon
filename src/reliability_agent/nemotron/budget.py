"""Client-side budget guard. The project must not spend beyond the 30 USD hackathon credits.

soft cap -> non-essential calls blocked; demo cap -> only demo calls; hard cap -> nothing leaves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: float
    output_per_m: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_m + output_tokens * self.output_per_m) / 1_000_000


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    total_usd: float = 30.0
    soft_cap_usd: float = 23.0
    demo_cap_usd: float = 25.0
    hard_cap_usd: float = 27.0
    alerts_pct: tuple[int, ...] = (50, 70, 80)
    spent_usd: float = 0.0
    calls: int = 0
    _alerted: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not (0 < self.soft_cap_usd <= self.demo_cap_usd <= self.hard_cap_usd <= self.total_usd):
            raise ValueError("caps must satisfy 0 < soft <= demo <= hard <= total")

    @classmethod
    def from_config(cls, cfg: dict, spent_usd: float = 0.0) -> BudgetGuard:
        b = cfg["budget"]
        return cls(float(b["total_usd"]), float(b["soft_cap_usd"]), float(b["demo_cap_usd"]),
                   float(b["hard_cap_usd"]), tuple(b.get("alerts_pct", (50, 70, 80))),
                   spent_usd=spent_usd)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.hard_cap_usd - self.spent_usd)

    def check(self, *, essential: bool = True, demo: bool = False,
              projected_usd: float = 0.0) -> tuple[bool, str]:
        after = self.spent_usd + projected_usd
        if after >= self.hard_cap_usd:
            return False, "hard cap reached: no request may leave the client"
        if self.spent_usd >= self.demo_cap_usd and not demo:
            return False, "demo cap reached: only demo calls allowed"
        if self.spent_usd >= self.soft_cap_usd and not essential:
            return False, "soft cap reached: non-essential calls disabled"
        return True, "ok"

    def require(self, **kw) -> None:
        ok, why = self.check(**kw)
        if not ok:
            raise BudgetExceeded(why)

    def record(self, cost_usd: float) -> list[int]:
        """Add a cost; return newly crossed alert thresholds (% of total)."""
        self.spent_usd += max(0.0, cost_usd)
        self.calls += 1
        crossed = [p for p in self.alerts_pct
                   if p not in self._alerted and self.spent_usd >= self.total_usd * p / 100]
        for p in crossed:
            self._alerted.add(p)
            log.warning("budget alert: %d%% of %.2f USD used (%.4f)", p, self.total_usd,
                        self.spent_usd)
        return crossed
