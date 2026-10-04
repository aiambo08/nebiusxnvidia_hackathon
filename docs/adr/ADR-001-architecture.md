# ADR-001 — MAPE-K architecture with deterministic authority

- Status: accepted
- Date: 2026-10-04
- Phase: F0

## Context
We need an agent that reacts to physical camera degradations, uses NVIDIA Nemotron on Nebius
Token Factory in an essential way, and is safe enough that an LLM error cannot damage the
managed pipeline. Commercial "camera health" products already detect blur/occlusion/darkness; our
differentiator is the closed loop detect → diagnose → act → verify → commit/rollback.

## Decision
Use the MAPE-K pattern:

| Stage | Component | Authority |
|---|---|---|
| Monitor | `capture/*`, `probes/*`, `tasks/*` | deterministic, local, offline-capable |
| Analyze | `baselines/*`, `incidents/*` (temporal fusion + FSM) | deterministic |
| Plan | `nemotron/*` (Nemotron proposes diagnosis + action + verification test) | **advisory only** |
| Execute | `policy/gate.py` then `actions/*` | deterministic allowlist, bounds, cooldowns |
| Verify | `verification/verifier.py` | deterministic commit/rollback rule |
| Knowledge | `storage/event_store.py` (SQLite, hash-chained events) | append-only |

Non-negotiables:
1. Primary detection works without the cloud.
2. Nemotron is called only after an incident is CONFIRMED.
3. The LLM never executes actions; it emits a `NemotronPlan` that the policy gate validates.
4. Every automatic action is in an allowlist, bounded, has a snapshot, timeout and rollback.
5. Budget has soft, demo and hard caps enforced client-side.
6. A Token Factory outage degrades to local monitoring + `needs_human`, never stops capture.

## Consequences
- More code than a "chat with your camera" demo, but every claim is testable.
- Nemotron's value is concentrated where heuristics are weak: causal ranking across transport,
  visual and task signals, choosing among allowed actions, defining the verification test and
  explaining the decision.
- A `RuleBasedPlanner` exists as offline fallback **and** as the ablation baseline for F10.

## FSM additions vs. the report
The report's table is kept; we make terminal/branch states explicit: `SAFE_MODE`, `REJECTED`,
`FAILED`, `ROLLED_BACK`, `CLOSED`, plus `ACTING → NEEDS_HUMAN` for ticket-only actions
(cleaning / recalibration requests never touch the device). See
`src/reliability_agent/incidents/state_machine.py`.
