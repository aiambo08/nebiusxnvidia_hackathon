"""MAPE-K orchestrator: wires Monitor -> Analyze -> Plan -> Execute -> Verify over Knowledge.

`on_window` is called once per telemetry window. It never blocks on the cloud for longer than
the planner timeout and never lets the LLM touch the device: Nemotron's plan goes through the
policy gate, the executor snapshots state first, and the verifier decides commit vs rollback.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from reliability_agent.actions.executor import ExecutionRecord, Executor
from reliability_agent.baselines.robust import RobustBaseline
from reliability_agent.contracts.models import (
    ActionName,
    FaultType,
    Incident,
    IncidentState,
    TelemetryWindow,
    VerificationStatus,
)
from reliability_agent.incidents.fusion import IncidentTracker, classify_window
from reliability_agent.nemotron.planner import Planner, PlanOutcome
from reliability_agent.policy.gate import PolicyGate
from reliability_agent.storage.event_store import EventStore
from reliability_agent.verification.verifier import Verifier

log = logging.getLogger(__name__)
S = IncidentState


@dataclass
class ActiveIncident:
    incident: Incident
    before: list[TelemetryWindow]
    plan: PlanOutcome | None = None
    record: ExecutionRecord | None = None
    after: list[TelemetryWindow] = field(default_factory=list)
    after_faults: list[set[FaultType]] = field(default_factory=list)
    healthy_streak: int = 0


class ReliabilityAgent:
    def __init__(
        self,
        cfg: dict[str, Any],
        device: Any,
        planner: Planner,
        store: EventStore,
        *,
        restart_cb: Callable[[], None] | None = None,
        gate: PolicyGate | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.device = device
        self.planner = planner
        self.store = store
        self.clock = clock
        self.gate = gate or PolicyGate(clock=clock)
        self.verifier = Verifier.from_config(cfg)
        f, b = cfg["fusion"], cfg["baseline"]
        self.tracker = IncidentTracker(
            cfg["camera"]["id"], cfg["faults"], f["enter_windows"], f["exit_windows"],
            f["cooldown_s"], RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]))
        self.executor = Executor(device, store, restart_cb,
                                 ticket_cb=lambda t: store.append("ticket", t,
                                                                  t["incident_id"]))
        self.active: ActiveIncident | None = None
        self._recent: deque[TelemetryWindow] = deque(maxlen=f["enter_windows"] + 2)
        win = cfg["window"]["seconds"]
        self._verify_windows = max(
            cfg["verification"]["healthy_windows_required"],
            math.ceil(cfg["verification"]["window_seconds"] / win))

    @property
    def state(self) -> IncidentState:
        return self.tracker.fsm.state

    def _to(self, dst: IncidentState, reason: str) -> None:
        src = self.state
        self.tracker.fsm.to(dst, reason)
        inc = self.active.incident.incident_id if self.active else None
        self.store.append("state", {"from": src, "to": dst, "reason": reason}, inc)

    # ------------------------------------------------------------------ main entry
    def on_window(self, tw: TelemetryWindow) -> IncidentState:
        self._recent.append(tw)
        st = self.state
        if st in (S.HEALTHY, S.SUSPECT):
            step = self.tracker.step(tw, now_s=self.clock())
            if step.state is not st:
                self.store.append("state", {"from": st, "to": step.state,
                                            "faults": sorted(map(str, step.faults))})
            if step.incident is not None:
                self._handle_confirmed(step.incident)
        elif st is S.VERIFYING:
            self._verify(tw)
        elif st is S.NEEDS_HUMAN:
            self._await_human(tw)
        return self.state

    # ------------------------------------------------------------------ plan + execute
    def _handle_confirmed(self, incident: Incident) -> None:
        caps = self.device.capabilities().as_list() if hasattr(self.device, "capabilities") \
            else []
        incident.capabilities = caps
        incident.allowed_actions = self.gate.allowed_for(caps)
        incident.current_config = {k: v for k, v in self.device.get_settings().items()
                                   if isinstance(v, (int, float, bool, str))}
        budget = getattr(self.planner, "budget", None)
        incident.budget_remaining_usd = budget.remaining_usd if budget else None
        self.active = ActiveIncident(incident, before=list(self._recent)[-3:])
        self.store.append("incident", incident, incident.incident_id)

        self._to(S.DIAGNOSING, "incident confirmed")
        out = self.planner.plan(incident)
        self.active.plan = out
        u = out.usage
        self.store.record_usage(u.model, u.prompt_version, u.input_tokens, u.output_tokens,
                                u.estimated_cost_usd, u.cached)
        self.store.append("plan", {"source": out.source, "attempts": out.attempts,
                                   "error": out.error, "plan": out.plan, "usage": u},
                          incident.incident_id)
        plan = out.plan
        if plan.action.name is ActionName.NEEDS_HUMAN:
            self._to(S.NEEDS_HUMAN, plan.human_message or "planner escalated")
            return
        self._to(S.PLANNED, f"{plan.diagnosis} -> {plan.action.name}")
        decision = self.gate.evaluate(plan.action, incident)
        self.store.append("policy", {"approved": decision.approved, "reasons": decision.reasons,
                                     "action": decision.action,
                                     "arguments": decision.arguments}, incident.incident_id)
        if not decision.approved:
            self._to(S.REJECTED, "; ".join(decision.reasons))
            self._to(S.NEEDS_HUMAN, "policy rejected plan")
            return
        if not self.cfg["planner"].get("auto_execute", True) and not decision.ticket_only:
            self._to(S.REJECTED, "auto_execute disabled: recommendation only")
            self._to(S.NEEDS_HUMAN, "recommendation only")
            return
        self._to(S.ACTING, str(decision.action))
        rec = self.executor.execute(incident.incident_id, decision)
        self.gate.record_execution(decision.action)
        self.active.record = rec
        self.store.append("execution", {"status": rec.status, "action": rec.action,
                                        "arguments": rec.arguments, "applied": rec.applied,
                                        "error": rec.error, "execution_id": rec.execution_id},
                          incident.incident_id)
        if rec.status == "ticket":
            self._to(S.NEEDS_HUMAN, f"ticket opened ({rec.action}); waiting for a human")
            self.store.mark_restored(rec.execution_id)
            return
        if rec.status != "success":
            self._to(S.FAILED, rec.error or "execution failed")
            self._rollback("execution failed")
            return
        self._to(S.VERIFYING, "observing effect")

    # ------------------------------------------------------------------ verify
    def _verify(self, tw: TelemetryWindow) -> None:
        a = self.active
        assert a is not None and a.plan is not None and a.record is not None
        faults, _ = classify_window(tw, self.tracker.baseline if self.tracker.baseline.ready
                                    else None, self.cfg["faults"])
        a.after.append(tw)
        a.after_faults.append(set(faults))
        if len(a.after) < self._verify_windows:
            return
        decision = self.verifier.decide(
            a.before, a.after, a.after_faults, set(a.incident.candidate_faults),
            a.plan.plan.verification,
            baseline_primary=self.tracker.baseline.median(a.plan.plan.verification.primary_metric),
        )
        if decision.status is VerificationStatus.INCONCLUSIVE and \
                len(a.after) < 2 * self._verify_windows:
            return
        self.store.append("verification", {"status": decision.status,
                                           "reasons": decision.reasons,
                                           "before": decision.before, "after": decision.after},
                          a.incident.incident_id)
        if decision.status is VerificationStatus.COMMITTED:
            self._to(S.RECOVERED, "; ".join(decision.reasons))
            self.store.mark_restored(a.record.execution_id)
            self._close(S.HEALTHY, "recovered")
        else:
            self._to(S.ROLLING_BACK, "; ".join(decision.reasons))
            self._rollback("verification failed")

    def _rollback(self, why: str) -> None:
        a = self.active
        assert a is not None and a.record is not None
        if self.state is S.FAILED:
            self._to(S.ROLLING_BACK, why)
        ok = self.executor.rollback(a.record)
        self.store.mark_restored(a.record.execution_id)
        self.store.append("rollback", {"ok": ok, "restored": a.record.snapshot},
                          a.incident.incident_id)
        self._to(S.ROLLED_BACK, why)
        self._to(S.NEEDS_HUMAN, "automatic action did not help; escalated")

    # ------------------------------------------------------------------ human loop
    def _await_human(self, tw: TelemetryWindow) -> None:
        """No repeated LLM calls while waiting; close once the camera is healthy again."""
        faults, _ = classify_window(tw, self.tracker.baseline if self.tracker.baseline.ready
                                    else None, self.cfg["faults"])
        a = self.active
        if a is None:
            return
        a.healthy_streak = 0 if faults else a.healthy_streak + 1
        if a.healthy_streak >= self.cfg["fusion"]["exit_windows"]:
            self._close(S.HEALTHY, "camera healthy again (human fix or transient)")

    def _close(self, dst: IncidentState, reason: str) -> None:
        a = self.active
        self._to(dst, reason)
        if a is not None:
            if reason == "recovered":  # cooldown after a successful action (report F5)
                self.tracker.suppress(list(a.incident.candidate_faults), self.clock())
            self.store.append("closed", {"reason": reason}, a.incident.incident_id)
        self.tracker.reset_healthy()
        self.active = None
