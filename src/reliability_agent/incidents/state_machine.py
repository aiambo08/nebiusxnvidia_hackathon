"""Incident finite-state machine (report table + explicit terminal states, see ADR-001)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from reliability_agent.contracts.models import IncidentState as S
from reliability_agent.contracts.models import utcnow

TRANSITIONS: dict[S, frozenset[S]] = {
    S.HEALTHY: frozenset({S.SUSPECT}),
    S.SUSPECT: frozenset({S.HEALTHY, S.CONFIRMED}),
    S.CONFIRMED: frozenset({S.DIAGNOSING, S.SAFE_MODE}),
    S.SAFE_MODE: frozenset({S.DIAGNOSING, S.NEEDS_HUMAN, S.HEALTHY}),
    S.DIAGNOSING: frozenset({S.PLANNED, S.NEEDS_HUMAN}),
    S.PLANNED: frozenset({S.ACTING, S.REJECTED}),
    S.REJECTED: frozenset({S.NEEDS_HUMAN}),
    S.ACTING: frozenset({S.VERIFYING, S.FAILED, S.NEEDS_HUMAN}),  # NEEDS_HUMAN: ticket opened
    S.FAILED: frozenset({S.ROLLING_BACK, S.NEEDS_HUMAN}),
    S.VERIFYING: frozenset({S.RECOVERED, S.ROLLING_BACK}),
    S.ROLLING_BACK: frozenset({S.ROLLED_BACK, S.NEEDS_HUMAN}),
    S.ROLLED_BACK: frozenset({S.NEEDS_HUMAN, S.HEALTHY}),
    S.RECOVERED: frozenset({S.HEALTHY}),
    S.NEEDS_HUMAN: frozenset({S.HEALTHY, S.CLOSED}),
    S.CLOSED: frozenset(),
}

# States in which the baseline must NOT learn (would learn the fault as normal).
BASELINE_FROZEN_STATES: frozenset[S] = frozenset(
    {
        S.SUSPECT,
        S.CONFIRMED,
        S.SAFE_MODE,
        S.DIAGNOSING,
        S.PLANNED,
        S.ACTING,
        S.VERIFYING,
        S.ROLLING_BACK,
        S.FAILED,
        S.NEEDS_HUMAN,
    }
)

# States in which an LLM call is allowed.
LLM_ALLOWED_STATES: frozenset[S] = frozenset({S.DIAGNOSING})


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Transition:
    src: S
    dst: S
    at: datetime
    reason: str


@dataclass
class IncidentStateMachine:
    state: S = S.HEALTHY
    history: list[Transition] = field(default_factory=list)

    def can(self, dst: S) -> bool:
        return dst in TRANSITIONS[self.state]

    def to(self, dst: S, reason: str = "", at: datetime | None = None) -> Transition:
        if not self.can(dst):
            raise IllegalTransition(f"{self.state} -> {dst} not allowed ({reason})")
        t = Transition(self.state, dst, at or utcnow(), reason)
        self.history.append(t)
        self.state = dst
        return t

    @property
    def baseline_frozen(self) -> bool:
        return self.state in BASELINE_FROZEN_STATES

    @property
    def llm_allowed(self) -> bool:
        return self.state in LLM_ALLOWED_STATES

    def trace(self) -> list[str]:
        return [f"{t.src}->{t.dst}" for t in self.history]
