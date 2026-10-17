"""MAPE-K orchestrator: wires Monitor -> Analyze -> Plan -> Execute -> Verify over Knowledge.

`on_window` is called once per telemetry window. It never blocks on the cloud for longer than
the planner timeout and never lets the LLM touch the device: Nemotron's plan goes through the
policy gate, the executor snapshots state first, and the verifier decides commit vs rollback.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
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

STATE_KEY = "agent_state"
STATE_SCHEMA = 1


def state_key(camera_id: str) -> str:
    """One checkpoint per camera: several cameras may share one event store."""
    return f"{STATE_KEY}:{camera_id}"


def lease_key(camera_id: str) -> str:
    return f"lease:{camera_id}"


class CameraInUseError(RuntimeError):
    """Another live agent holds this camera id on the same event store."""


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
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self.wall_clock = wall_clock
        self.device = device
        self.planner = planner
        self.store = store
        self.clock = clock
        self.gate = gate or PolicyGate(clock=clock)
        self.verifier = Verifier.from_config(cfg)
        f, b = cfg["fusion"], cfg["baseline"]
        self.tracker = IncidentTracker(
            cfg["camera"]["id"], cfg["faults"], f["enter_windows"], f["exit_windows"],
            f["cooldown_s"], RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"]),
            calibration_discard=int(b.get("calibration_discard", 3)))
        self.executor = Executor(device, store, restart_cb,
                                 ticket_cb=lambda t: store.append("ticket", t,
                                                                  t["incident_id"]))
        self.active: ActiveIncident | None = None
        self._recent: deque[TelemetryWindow] = deque(maxlen=f["enter_windows"] + 2)
        win = cfg["window"]["seconds"]
        self._verify_windows = max(
            cfg["verification"]["healthy_windows_required"],
            math.ceil(cfg["verification"]["window_seconds"] / win))
        self._stall_windows = int(b.get("stall_windows", 120))
        if self._stall_windows < 1:
            raise ValueError(f"baseline.stall_windows ({self._stall_windows}) must be >= 1")
        self._calib_best, self._calib_idle = -1, 0
        st = cfg.get("storage", {})
        self._checkpoint_every = max(1, int(st.get("checkpoint_windows", 10)))
        self._windows = 0
        self._lease_stale_s = float(st.get("lease_stale_s", 60.0))
        p = cfg["planner"]
        action_s = max((s.timeout_s for s in self.gate.registry.values()), default=0.0)
        busy_s = (float(p.get("timeout_s", 0)) * int(p.get("max_calls_per_incident", 1))
                  + action_s + float(win))
        if self._lease_stale_s <= busy_s:
            # the heartbeat is not refreshed while the planner or an action runs
            raise ValueError(f"storage.lease_stale_s ({self._lease_stale_s:g}) must exceed the "
                             f"longest gap between heartbeats ({busy_s:g}s: planner timeout x "
                             f"calls + action timeout + one window)")
        self._owner = uuid.uuid4().hex
        self._lease_lost = False
        self._acquire_lease()
        if st.get("restore_on_start", True):
            self.restore()

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
        if not self._heartbeat():  # another agent owns this camera now: observe nothing, act never
            return self.state
        self._recent.append(tw)
        st = self.state
        calibrated = False
        if st in (S.HEALTHY, S.SUSPECT):
            b = self.tracker.baseline
            was_ready = b.ready
            step = self.tracker.step(tw, now_s=self.clock())
            if step.calibration_discarded:
                self.store.append("calibration_samples_discarded",
                                  {"discarded": step.calibration_discarded,
                                   "faults": sorted(map(str, step.faults))})
            b = self.tracker.baseline
            if not was_ready and b.ready:
                calibrated = True
                self.store.append("baseline_calibrated",
                                  {"baseline_version": b.version, "samples": b.updates,
                                   "mode": b.mode})
            if step.state is not st:
                self.store.append("state", {"from": st, "to": step.state,
                                            "faults": sorted(map(str, step.faults))})
            if step.incident is not None:
                self._handle_confirmed(step.incident)
        elif st is S.VERIFYING:
            self._verify(tw)
        elif st is S.NEEDS_HUMAN:
            self._await_human(tw)
        self._watch_calibration()
        self._windows += 1
        if self._lease_lost:
            return self.state
        # SUSPECT checkpoints every window: its hysteresis counters change on each one
        if (calibrated or self.state is not st or self.state is S.SUSPECT
                or self._windows % self._checkpoint_every == 0):
            self.checkpoint()
        return self.state

    def _watch_calibration(self) -> None:
        """Log ``calibration_stalled`` once after ``baseline.stall_windows`` windows in which
        an unready baseline never exceeded its best sample count: until it is ready, LOW_FPS
        and the z-score rules are off, and the camera must not look quietly HEALTHY."""
        b = self.tracker.baseline
        if b.ready or b.updates > self._calib_best:
            self._calib_best, self._calib_idle = b.updates, 0
            return
        self._calib_idle += 1
        if self._calib_idle == self._stall_windows:
            self.store.append("calibration_stalled",
                              {"windows": self._calib_idle, "samples": b.updates,
                               "min_samples": b.min_samples})

    # ------------------------------------------------------------------ persistence (F5)
    def _acquire_lease(self) -> None:
        """One live agent per camera id and store: a second one would roll back the first
        one's action onto its own device and overwrite its checkpoint. The lease is a
        heartbeat refreshed every window; a crashed agent's lease goes stale after
        ``storage.lease_stale_s`` (a clean shutdown releases it at once)."""
        key = lease_key(self.tracker.camera_id)
        try:
            cur = self.store.get_state(key)
        except ValueError:
            cur = None
        if isinstance(cur, dict) and cur.get("owner") != self._owner \
                and not cur.get("released"):
            try:
                age = self.wall_clock() - float(cur["heartbeat"])
            except (KeyError, TypeError, ValueError):
                age = math.inf
            if abs(age) < self._lease_stale_s:
                raise CameraInUseError(
                    f"camera id {self.tracker.camera_id!r} is in use by another live agent "
                    f"on this event store (heartbeat {max(age, 0.0):.1f}s ago); give each "
                    f"camera its own id (RA_CAMERA_ID) or wait {self._lease_stale_s:.0f}s "
                    f"if that agent has crashed")
        self._write_lease()

    def _write_lease(self) -> None:
        self.store.put_state(lease_key(self.tracker.camera_id),
                             {"owner": self._owner, "heartbeat": self.wall_clock()})

    def _heartbeat(self) -> bool:
        """Refresh the lease; False (and the agent stops acting for good) unless it is still
        this agent's own live lease. A missing or released lease counts as lost too: another
        agent may have taken over while this one stalled and then shut down cleanly."""
        if self._lease_lost:
            return False
        try:
            cur = self.store.get_state(lease_key(self.tracker.camera_id))
        except ValueError:
            cur = None
        if not (isinstance(cur, dict) and cur.get("owner") == self._owner
                and not cur.get("released")):
            self._lease_lost = True
            log.error("lease of camera %s taken over by another agent; this agent stops acting",
                      self.tracker.camera_id)
            inc = self.active.incident.incident_id if self.active else None
            self.store.append("lease_lost", {"camera_id": self.tracker.camera_id}, inc)
            return False
        self._write_lease()
        return True

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost

    def release_lease(self) -> None:
        """Clean shutdown: the next start of this camera need not wait for the lease. A
        tombstone, not a deletion, so a stalled agent cannot mistake it for its own."""
        key = lease_key(self.tracker.camera_id)
        cur = self.store.get_state(key)
        if isinstance(cur, dict) and cur.get("owner") == self._owner:
            self.store.put_state(key, {"owner": self._owner, "released": True,
                                       "heartbeat": self.wall_clock()})
        self._lease_lost = True

    def checkpoint(self) -> None:
        """Persist what the next window depends on: FSM state, hysteresis counters, cooldowns,
        the policy gate's execution history and the baseline."""
        if self._lease_lost:  # never overwrite the new owner's checkpoint
            return
        now = self.clock()
        self.store.put_state(state_key(self.tracker.camera_id), {
            "schema": STATE_SCHEMA,
            "camera_id": self.tracker.camera_id,
            "saved_at": self.wall_clock(),
            "incident_id": self.active.incident.incident_id if self.active else None,
            "tracker": self.tracker.export_state(now),
            "gate": self.gate.export_history(now),
        })

    def restore(self) -> bool:
        """Resume after a restart. An action of this camera whose outcome was never committed
        is rolled back and never repeated; an incident of this camera that was never closed
        escalates to NEEDS_HUMAN (no new plan, no LLM call) and closes once the camera is
        healthy again. The event log, not the checkpoint, decides what is still open, so a
        checkpoint older than the last action cannot reopen or repeat anything."""
        try:
            saved = self.store.get_state(state_key(self.tracker.camera_id))
        except ValueError:  # unreadable JSON: start fresh, never refuse to start
            saved = {"schema": None}
        mine, open_ = self._camera_incidents()
        pending = [p for p in self.store.pending_snapshots() if p["incident_id"] in mine]
        if saved is None and not pending and not open_:
            return False
        now = self.clock()
        info: dict[str, Any] = {"restored": False, "rolled_back": []}
        incident_id = None
        state = S.HEALTHY
        if saved is not None and (not isinstance(saved, dict)
                                  or saved.get("schema") != STATE_SCHEMA
                                  or saved.get("camera_id") != self.tracker.camera_id):
            info["reason"] = "saved state is unreadable or for another schema or camera"
        elif saved is not None:
            try:
                down = max(0.0, self.wall_clock() - float(saved["saved_at"]))
                self.tracker.import_state(saved["tracker"], now, down)
                self.gate.import_history(saved["gate"], now, down)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                self._fresh_tracker()
                self.gate._last.clear()
                self.gate._hist.clear()
                info["reason"] = f"saved state is malformed ({type(exc).__name__})"
            else:
                state, incident_id = self.state, saved.get("incident_id")
                info.update(restored=True, state=state, downtime_s=round(down, 1),
                            baseline_version=self.tracker.baseline.version,
                            baseline_ready=self.tracker.baseline.ready)
        for p in pending:
            info["rolled_back"].append(self._rollback_pending(p, now))
        if open_ or state not in (S.HEALTHY, S.SUSPECT) or pending:
            self.tracker.fsm.state = S.HEALTHY
            self.tracker.reset_healthy()
            incident_id = None
            if open_:
                for old in open_[:-1]:
                    self.store.append("closed", {"reason": "superseded on restart"},
                                      old.incident_id)
                incident = open_[-1]
                incident_id = incident.incident_id
                self.active = ActiveIncident(incident, before=[])
                self.tracker.fsm.state = S.NEEDS_HUMAN
                self.store.append("state", {"from": state, "to": S.NEEDS_HUMAN,
                                            "reason": "restarted with an open incident"},
                                  incident_id)
            info["state"] = self.state
        self.store.append("restore", info, incident_id)
        log.info("restore: %s", info)
        self.checkpoint()  # a second restart must not resume the older checkpoint
        return bool(info["restored"])

    def _fresh_tracker(self) -> None:
        b, t = self.cfg["baseline"], self.tracker
        t.baseline = RobustBaseline(b["window"], b["min_samples"], b["mad_epsilon"])
        t.fsm.state = S.HEALTHY
        t._suppressed.clear()
        t.reset_healthy()

    def _rollback_pending(self, p: dict[str, Any], now: float) -> dict[str, Any]:
        try:
            action = ActionName(p["action"])
        except ValueError:  # not an action this build knows: leave it for a human
            log.error("restart: pending snapshot with unknown action; left pending")
            self.store.append("rollback", {"ok": False, "reason": "unknown action"},
                              p["incident_id"])
            return {"execution_id": p["execution_id"], "action": p["action"], "ok": False}
        rec = ExecutionRecord(p["execution_id"], p["incident_id"], action, {}, p["snapshot"],
                              status="success")
        try:
            ok = self.executor.rollback(rec)
        except Exception as exc:  # noqa: BLE001 - the snapshot stays pending for the next start
            log.error("restart rollback of %s failed: %s", action, type(exc).__name__)
            ok = False
        if ok:
            self.store.mark_restored(p["execution_id"])
        # it ran before the restart: count it against cooldowns and hourly limits
        self.gate.record_execution(action, now)
        self.store.append("rollback", {"ok": ok, "restored": p["snapshot"],
                                       "reason": "restart with an uncommitted action"},
                          p["incident_id"])
        return {"execution_id": p["execution_id"], "action": action, "ok": ok}

    def _camera_incidents(self) -> tuple[set[str], list[Incident]]:
        """Ids of this camera's incidents, and those never closed (oldest first)."""
        closed = {e["incident_id"] for e in self.store.events(kind="closed")}
        mine: set[str] = set()
        open_: list[Incident] = []
        for e in self.store.events(kind="incident"):
            try:
                inc = Incident.model_validate(e["payload"])
            except ValueError:
                continue
            if inc.camera_id != self.tracker.camera_id:
                continue
            mine.add(inc.incident_id)
            if inc.incident_id not in closed:
                open_.append(inc)
        return mine, open_

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
        if not self._heartbeat():
            self._to(S.NEEDS_HUMAN, "lease taken over by another agent: no plan")
            return
        out = self.planner.plan(incident)
        self.active.plan = out
        u = out.usage
        self.store.record_usage(u.model, u.prompt_version, u.input_tokens, u.output_tokens,
                                u.estimated_cost_usd, u.cached)
        self.store.append("plan", {"source": out.source, "attempts": out.attempts,
                                   "error": out.error, "plan": out.plan, "usage": u},
                          incident.incident_id)
        plan = out.plan
        if not self._heartbeat():
            self._to(S.NEEDS_HUMAN, "lease taken over by another agent during planning")
            return
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
        if not self._heartbeat():
            self._to(S.REJECTED, "lease taken over by another agent")
            self._to(S.NEEDS_HUMAN, "lease lost: no action")
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
