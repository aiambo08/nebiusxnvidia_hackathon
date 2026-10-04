"""Reversible action executor. Snapshot is persisted BEFORE any change; rollback is idempotent."""

from __future__ import annotations

import copy
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from reliability_agent.contracts.models import ActionName
from reliability_agent.policy.gate import PolicyDecision

log = logging.getLogger(__name__)
A = ActionName


class Device(Protocol):
    def get_settings(self) -> dict: ...
    def apply_settings(self, settings: dict) -> None: ...


class SnapshotSink(Protocol):
    def save_snapshot(self, execution_id: str, incident_id: str, action: str,
                      snapshot: dict) -> None: ...


@dataclass
class ExecutionRecord:
    execution_id: str
    incident_id: str
    action: ActionName
    arguments: dict[str, Any]
    snapshot: dict[str, Any]
    status: str = "pending"        # pending | success | failed | rejected | ticket
    error: str | None = None
    rolled_back: bool = False
    ticket: dict[str, Any] | None = None
    applied: dict[str, Any] = field(default_factory=dict)


class Executor:
    def __init__(self, device: Device, sink: SnapshotSink | None = None,
                 restart_cb: Callable[[], None] | None = None,
                 ticket_cb: Callable[[dict], None] | None = None) -> None:
        self.device = device
        self.sink = sink
        self.restart_cb = restart_cb
        self.ticket_cb = ticket_cb
        self._done: dict[str, ExecutionRecord] = {}

    def execute(self, incident_id: str, decision: PolicyDecision,
                idempotency_key: str | None = None) -> ExecutionRecord:
        key = idempotency_key or f"{incident_id}:{decision.action}"
        if key in self._done:  # never apply the same approved plan twice
            return self._done[key]
        snapshot = copy.deepcopy(self.device.get_settings())
        rec = ExecutionRecord(str(uuid.uuid4()), incident_id, decision.action,  # type: ignore[arg-type]
                              dict(decision.arguments), snapshot)
        if not decision.approved or decision.action is None:
            rec.status, rec.error = "rejected", "; ".join(decision.reasons)
            self._done[key] = rec
            return rec
        if self.sink is not None:
            self.sink.save_snapshot(rec.execution_id, incident_id, str(rec.action), snapshot)
        try:
            if decision.ticket_only:
                rec.ticket = {"incident_id": incident_id, "action": str(rec.action),
                              "arguments": rec.arguments}
                if self.ticket_cb:
                    self.ticket_cb(rec.ticket)
                rec.status = "ticket"
            else:
                rec.applied = self._apply(rec.action, rec.arguments, snapshot)
                rec.status = "success"
        except Exception as exc:  # noqa: BLE001 - any device error is an execution failure
            log.exception("action %s failed", rec.action)
            rec.status, rec.error = "failed", f"{type(exc).__name__}: {exc}"[:200]
        self._done[key] = rec
        return rec

    def rollback(self, rec: ExecutionRecord) -> bool:
        """Restore the exact pre-action settings. Safe to call more than once."""
        if rec.status in ("rejected", "ticket") or rec.rolled_back:
            return rec.rolled_back
        self.device.apply_settings(copy.deepcopy(rec.snapshot))
        rec.rolled_back = True
        return True

    # -- action implementations (device-agnostic, bounded again defensively)
    def _apply(self, name: ActionName, args: dict[str, Any], snap: dict[str, Any]) -> dict:
        if name is A.RESTART_CAPTURE:
            if self.restart_cb is None:
                raise RuntimeError("restart not supported by this device")
            self.restart_cb()
            return {}
        if name is A.SWITCH_STREAM_PROFILE:
            change = {"profile": args["profile"]}
        elif name is A.SET_EXPOSURE_BOUNDED:
            lo, hi = snap.get("exposure_range", (-2.0, 2.0))
            cur = float(snap.get("exposure", 0.0))
            change = {"exposure": max(lo, min(hi, cur + float(args["delta_ev"])))}
        elif name is A.TRIGGER_AUTOFOCUS:
            change = {"focus_ok": True}
        elif name is A.ENTER_SAFE_MODE:
            change = {"safe_mode": True}
        else:
            raise RuntimeError(f"no implementation for {name}")
        self.device.apply_settings(change)
        return change
