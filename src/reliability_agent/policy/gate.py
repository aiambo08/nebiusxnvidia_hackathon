"""Deterministic policy gate. The only path from an LLM plan to the device.

Every action declares compatible capabilities, typed/bounded parameters, cooldown, rate limit,
timeout, reversibility and risk class. Anything not explicitly allowed is rejected.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from reliability_agent.contracts.models import ActionName, Incident, PlanAction

A = ActionName


@dataclass(frozen=True)
class ParamSpec:
    type: str                      # float | int | str | bool
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] | None = None
    required: bool = True
    description: str = ""

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.choices:
            d["choices"] = list(self.choices)
        if self.description:
            d["description"] = self.description
        return d


@dataclass(frozen=True)
class ActionSpec:
    name: ActionName
    description: str
    params: dict[str, ParamSpec] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    risk: str = "low"              # low (auto) | ticket (human ticket, no device change)
    cooldown_s: float = 30.0
    max_per_hour: int = 10
    timeout_s: float = 10.0
    reversible: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "name": str(self.name),
            "description": self.description,
            "arguments": {k: v.to_json() for k, v in self.params.items()},
            "risk": self.risk,
        }


REGISTRY: dict[ActionName, ActionSpec] = {
    s.name: s
    for s in [
        ActionSpec(A.RESTART_CAPTURE, "Reconnect the capture/decoder (freeze, stream down).",
                   requires=("restart",), cooldown_s=15, max_per_hour=12),
        ActionSpec(A.SWITCH_STREAM_PROFILE, "Switch to another stream profile (e.g. sub-stream).",
                   {"profile": ParamSpec("str", choices=("main", "sub"))},
                   requires=("profiles",)),
        ActionSpec(A.SET_EXPOSURE_BOUNDED, "Change exposure by delta_ev stops, clamped to range.",
                   {"delta_ev": ParamSpec("float", -2.0, 2.0,
                                          description="relative exposure change in EV stops")},
                   requires=("exposure",), cooldown_s=20, max_per_hour=8),
        ActionSpec(A.TRIGGER_AUTOFOCUS, "Run one autofocus cycle.", requires=("autofocus",)),
        ActionSpec(A.ENTER_SAFE_MODE, "Mark the perception output as untrusted downstream.",
                   cooldown_s=5),
        ActionSpec(A.REQUEST_MANUAL_CLEANING, "Open a maintenance ticket to clean/uncover lens.",
                   risk="ticket", reversible=False, cooldown_s=0, max_per_hour=60),
        ActionSpec(A.REQUEST_RECALIBRATION, "Open a ticket to re-aim / recalibrate the camera.",
                   risk="ticket", reversible=False, cooldown_s=0, max_per_hour=60),
        ActionSpec(A.NEEDS_HUMAN, "Escalate to a human with the diagnosis; no device change.",
                   risk="ticket", reversible=False, cooldown_s=0, max_per_hour=60),
    ]
}


@dataclass
class PolicyDecision:
    approved: bool
    action: ActionName | None
    arguments: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    ticket_only: bool = False


class PolicyGate:
    def __init__(self, registry: dict[ActionName, ActionSpec] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.registry = registry or REGISTRY
        self.clock = clock
        self._last: dict[ActionName, float] = {}
        self._hist: dict[ActionName, deque[float]] = defaultdict(deque)

    # -- discovery
    def allowed_for(self, capabilities: list[str]) -> list[ActionName]:
        caps = set(capabilities)
        return [n for n, s in self.registry.items() if set(s.requires) <= caps]

    def describe(self, names: list[ActionName]) -> list[dict[str, Any]]:
        return [self.registry[n].to_json() for n in names if n in self.registry]

    # -- validation
    def evaluate(self, action: PlanAction | dict[str, Any], incident: Incident,
                 now: float | None = None) -> PolicyDecision:
        now = self.clock() if now is None else now
        raw_name = action.name if isinstance(action, PlanAction) else action.get("name")
        args = action.arguments if isinstance(action, PlanAction) else action.get("arguments", {})
        try:
            name = ActionName(raw_name)
        except ValueError:
            return PolicyDecision(False, None, reasons=[f"unknown action {str(raw_name)[:40]!r}"])
        spec = self.registry.get(name)
        if spec is None:
            return PolicyDecision(False, name, reasons=["action not in registry"])
        reasons: list[str] = []
        if name not in incident.allowed_actions:
            reasons.append("action not offered for this incident")
        missing = set(spec.requires) - set(incident.capabilities)
        if missing:
            reasons.append(f"device lacks capabilities {sorted(missing)}")
        if not isinstance(args, dict):
            reasons.append("arguments must be an object")
            args = {}
        clean, arg_errors = self._check_args(spec, args)
        reasons += arg_errors
        last = self._last.get(name)
        if last is not None and now - last < spec.cooldown_s:
            reasons.append(f"cooldown active ({spec.cooldown_s - (now - last):.1f}s left)")
        hist = self._hist[name]
        while hist and now - hist[0] > 3600:
            hist.popleft()
        if len(hist) >= spec.max_per_hour:
            reasons.append("hourly rate limit reached")
        if reasons:
            return PolicyDecision(False, name, reasons=reasons)
        return PolicyDecision(True, name, clean, ["ok"], ticket_only=spec.risk == "ticket")

    def record_execution(self, name: ActionName, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        self._last[name] = now
        self._hist[name].append(now)

    @staticmethod
    def _check_args(spec: ActionSpec, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        errors: list[str] = []
        clean: dict[str, Any] = {}
        extra = set(args) - set(spec.params)
        if extra:
            errors.append(f"unexpected arguments {sorted(str(e)[:20] for e in extra)}")
        for key, p in spec.params.items():
            if key not in args:
                if p.required:
                    errors.append(f"missing argument {key}")
                continue
            v = args[key]
            if p.type in ("float", "int"):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    errors.append(f"{key} must be a number")
                    continue
                if not math.isfinite(float(v)):
                    errors.append(f"{key} must be finite")
                    continue
                if p.type == "int" and not float(v).is_integer():
                    errors.append(f"{key} must be an integer")
                    continue
                if (p.min is not None and v < p.min) or (p.max is not None and v > p.max):
                    errors.append(f"{key}={v} outside [{p.min}, {p.max}]")
                    continue
                clean[key] = int(v) if p.type == "int" else float(v)
            elif p.type == "str":
                if not isinstance(v, str) or len(v) > 32:
                    errors.append(f"{key} must be a short string")
                    continue
                if p.choices and v not in p.choices:
                    errors.append(f"{key} must be one of {list(p.choices)}")
                    continue
                clean[key] = v
            elif p.type == "bool":
                if not isinstance(v, bool):
                    errors.append(f"{key} must be boolean")
                    continue
                clean[key] = v
        return clean, errors
