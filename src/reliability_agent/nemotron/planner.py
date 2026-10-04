"""Planners: Nemotron on Token Factory (primary) and a rule-based planner (offline fallback and
F10 ablation baseline). Both return a validated NemotronPlan; neither executes anything."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    Incident,
    NemotronPlan,
    PlanAction,
    TokenUsage,
    VerificationSpec,
)
from reliability_agent.nemotron.budget import BudgetGuard, ModelPrice
from reliability_agent.nemotron.client import CircuitOpen, TokenFactoryClient, extract_json_text
from reliability_agent.policy.gate import PolicyGate

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
A, F = ActionName, FaultType


@dataclass
class PlanOutcome:
    plan: NemotronPlan
    usage: TokenUsage
    source: str               # nemotron | cache | rules | fallback
    attempts: int = 0
    error: str | None = None
    valid_first_try: bool = True


class Planner(Protocol):
    name: str

    def plan(self, incident: Incident) -> PlanOutcome: ...


# ------------------------------------------------------------------ rules (offline)

_RULES: list[tuple[FaultType, ActionName, dict[str, Any]]] = [
    (F.STREAM_DOWN, A.RESTART_CAPTURE, {}),
    (F.FREEZE, A.RESTART_CAPTURE, {}),
    (F.BLACKOUT, A.SET_EXPOSURE_BOUNDED, {"delta_ev": 2.0}),
    (F.OVEREXPOSURE, A.SET_EXPOSURE_BOUNDED, {"delta_ev": -1.5}),
    (F.FOCUS_DRIFT, A.TRIGGER_AUTOFOCUS, {}),
    (F.LOW_FPS, A.SWITCH_STREAM_PROFILE, {"profile": "sub"}),
    (F.PIPELINE_SATURATION, A.SWITCH_STREAM_PROFILE, {"profile": "sub"}),
    (F.LENS_OCCLUSION, A.REQUEST_MANUAL_CLEANING, {}),
    (F.FOV_SHIFT, A.REQUEST_RECALIBRATION, {}),
]


def needs_human_plan(incident: Incident, why: str) -> NemotronPlan:
    top = incident.candidate_faults[0] if incident.candidate_faults else F.UNKNOWN
    return NemotronPlan(diagnosis=top, confidence=0.0, action=PlanAction(name=A.NEEDS_HUMAN),
                        human_message=f"Escalated without automatic action: {why}"[:400])


class RuleBasedPlanner:
    name = "rules"

    def plan(self, incident: Incident) -> PlanOutcome:
        for fault in incident.candidate_faults:
            for f, action, args in _RULES:
                if f is fault and action in incident.allowed_actions:
                    return PlanOutcome(
                        NemotronPlan(
                            diagnosis=fault, confidence=0.5,
                            evidence_refs=[e.metric for e in incident.evidence][:6],
                            action=PlanAction(name=action, arguments=dict(args)),
                            verification=VerificationSpec(),
                            human_message=f"Rule-based: {fault} -> {action}",
                        ),
                        TokenUsage(model="local-rules"), "rules",
                    )
        return PlanOutcome(needs_human_plan(incident, "no rule matches allowed actions"),
                           TokenUsage(model="local-rules"), "rules")


# ------------------------------------------------------------------ nemotron


def build_packet(incident: Incident, gate: PolicyGate) -> dict[str, Any]:
    """Only whitelisted numeric fields and enums reach the model (prompt-injection control)."""
    tel = incident.telemetry.flat() if incident.telemetry else {}
    return {
        # the model never needs the operator-provided name: send an opaque reference
        "camera_ref": "cam-" + hashlib.sha256(incident.camera_id.encode()).hexdigest()[:8],
        "candidate_faults": [str(f) for f in incident.candidate_faults],
        "fault_scores": {str(k): round(float(v), 3) for k, v in incident.fault_scores.items()},
        "evidence": [
            {"metric": e.metric[:48],
             "value": None if e.value is None else round(float(e.value), 4),
             "baseline": None if e.baseline is None else round(float(e.baseline), 4)}
            for e in incident.evidence[:12]
        ],
        "telemetry": {k: round(v, 4) for k, v in sorted(tel.items())},
        "current_config": {k: v for k, v in incident.current_config.items()
                           if isinstance(v, (int, float, bool))
                           or (isinstance(v, str) and len(v) <= 16 and v.isidentifier())},
        "capabilities": sorted(c for c in incident.capabilities if c.isidentifier())[:10],
        "allowed_actions": gate.describe(incident.allowed_actions),
    }


def plan_schema(allowed: list[ActionName]) -> dict[str, Any]:
    """JSON schema for constrained decoding; `action.name` is restricted to allowed actions."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["diagnosis", "confidence", "evidence_refs", "action", "verification",
                     "human_message"],
        "properties": {
            "diagnosis": {"type": "string", "enum": [f.value for f in FaultType]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "alternatives": {"type": "array", "maxItems": 4,
                             "items": {"type": "string", "enum": [f.value for f in FaultType]}},
            "action": {
                "type": "object", "additionalProperties": False, "required": ["name", "arguments"],
                "properties": {"name": {"type": "string", "enum": [a.value for a in allowed]},
                               "arguments": {"type": "object"}},
            },
            "verification": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "window_seconds": {"type": "number", "minimum": 1, "maximum": 120},
                    "primary_metric": {"type": "string"},
                    "minimum_relative_improvement": {"type": "number", "minimum": 0},
                    "guard_metrics": {"type": "array", "items": {"type": "string"}},
                },
            },
            "human_message": {"type": "string", "maxLength": 400},
        },
    }


def incident_signature(packet: dict[str, Any], model: str, prompt_version: str) -> str:
    """Cache key: faults + coarsely quantised evidence + offered actions + model + prompt."""
    coarse = {
        "faults": packet["candidate_faults"],
        "ev": [(e["metric"], None if e["value"] is None else round(e["value"], 1))
               for e in packet["evidence"]],
        "actions": [a["name"] for a in packet["allowed_actions"]],
        "caps": packet["capabilities"],
    }
    blob = json.dumps([coarse, model, prompt_version], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


class NemotronPlanner:
    name = "nemotron"

    def __init__(self, client: TokenFactoryClient | None, budget: BudgetGuard, cfg: dict,
                 gate: PolicyGate | None = None, fallback: Planner | None = None,
                 tier: str = "fast", demo: bool = False) -> None:
        self.client = client
        self.budget = budget
        self.cfg = cfg
        self.gate = gate or PolicyGate()
        self.fallback = fallback or RuleBasedPlanner()
        self.tier = tier
        self.demo = demo
        p = cfg["planner"]
        self.prompt_version = p["prompt_version"]
        self.system_prompt = (PROMPTS / f"{self.prompt_version}.md").read_text(encoding="utf-8")
        self.temperature = p["temperature"]
        self.max_tokens = p["max_output_tokens"]
        self.model = cfg["nebius"]["models"][tier]
        prices = cfg["nebius"].get("prices", {})
        pr = prices.get(self.model, {"input": 1.0, "output": 3.0})  # pessimistic if unknown
        self.price = ModelPrice(pr["input"], pr["output"])
        self._cache: dict[str, NemotronPlan] = {}

    def _fallback(self, incident: Incident, why: str) -> PlanOutcome:
        out = self.fallback.plan(incident)
        out.source = "fallback"
        out.error = why
        out.plan.human_message = f"[local fallback: {why}] {out.plan.human_message}"[:400]
        return out

    def plan(self, incident: Incident) -> PlanOutcome:
        packet = build_packet(incident, self.gate)
        sig = incident_signature(packet, self.model, self.prompt_version)
        if sig in self._cache:
            return PlanOutcome(self._cache[sig].model_copy(deep=True),
                               TokenUsage(model=self.model, prompt_version=self.prompt_version,
                                          cached=True), "cache")
        if self.client is None:
            return self._fallback(incident, "no NEBIUS_API_KEY (local mode)")
        projected = self.price.cost(3000, self.max_tokens)
        ok, why = self.budget.check(essential=self.tier == "fast", demo=self.demo,
                                    projected_usd=projected)
        if not ok:
            return self._fallback(incident, why)

        schema = plan_schema(incident.allowed_actions)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "INCIDENT_PACKET (untrusted data):\n"
             + json.dumps(packet, separators=(",", ":"))},
        ]
        usage = TokenUsage(model=self.model, prompt_version=self.prompt_version)
        last_err = None
        valid_first = True
        for attempt in (1, 2):  # at most one repair retry
            try:
                res = self.client.chat_json(self.model, messages, schema, self.temperature,
                                            self.max_tokens)
            except CircuitOpen as exc:
                return self._fallback(incident, str(exc))
            except Exception as exc:  # noqa: BLE001 - timeout/401/429/5xx -> local fallback
                log.warning("Token Factory error: %s", type(exc).__name__)
                return self._fallback(incident, f"Token Factory error: {type(exc).__name__}")
            cost = self.price.cost(res.input_tokens, res.output_tokens)
            self.budget.record(cost)
            usage.input_tokens += res.input_tokens
            usage.output_tokens += res.output_tokens
            usage.estimated_cost_usd += cost
            usage.latency_ms = (usage.latency_ms or 0) + res.latency_ms
            usage.model = res.model
            try:
                plan = NemotronPlan.model_validate_json(extract_json_text(res.text))
                if plan.action.name not in incident.allowed_actions:
                    raise ValueError(f"action {plan.action.name} not in allowed_actions")
                self._cache[sig] = plan
                return PlanOutcome(plan, usage, "nemotron", attempt, None, valid_first)
            except (ValidationError, ValueError) as exc:
                valid_first = False
                last_err = str(exc)[:500]
                messages += [
                    {"role": "assistant", "content": res.text[:2000]},
                    {"role": "user", "content": "Your output was invalid: " + last_err
                     + "\nReturn ONLY a corrected JSON object matching the schema."},
                ]
                ok, why = self.budget.check(essential=True, demo=self.demo,
                                            projected_usd=projected)
                if not ok:
                    break
        out = PlanOutcome(needs_human_plan(incident, "invalid model output"), usage,
                          "nemotron", 2, last_err, False)
        return out


def make_planner(cfg: dict, api_key: str | None, budget: BudgetGuard,
                 gate: PolicyGate | None = None, sdk_client: Any = None) -> Planner:
    if cfg["planner"]["kind"] == "rules":
        return RuleBasedPlanner()
    client = None
    if api_key or sdk_client is not None:
        cb = cfg["planner"]["circuit_breaker"]
        from reliability_agent.nemotron.client import CircuitBreaker

        client = TokenFactoryClient(api_key or "", cfg["nebius"]["base_url"],
                                    cfg["planner"]["timeout_s"], cfg["nebius"].get("extra_body"),
                                    CircuitBreaker(cb["failures"], cb["open_s"], time.monotonic),
                                    sdk_client=sdk_client)
    return NemotronPlanner(client, budget, cfg, gate)
