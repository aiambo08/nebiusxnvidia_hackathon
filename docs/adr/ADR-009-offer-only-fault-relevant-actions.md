# ADR-009 — Offer only fault-relevant actions

- Status: accepted
- Date: 2026-10-18
- Gate: F6

## Context

The live diagnose_v1 fast test run was 100% schema-valid (100% on first try), but action accuracy
was 75.379% (FAIL) with $0.0334 projected for 300 incidents. Dark base/injection cases were 0/48
correct: responses chose `restart_capture` 37 times, `request_manual_cleaning` 7 times, and
`enter_safe_mode` 4 times; no-capability cases chose an action associated with another fault.
The v1 fast dev score was 102/144.

Prompt iteration was development-only. diagnose_v2 fast scored 120/144 on dev (base+injection
120/120, no_cap 0/24); diagnose_v2b fast scored 125/144 (no_cap 5/24) and was removed as an
iteration. diagnose_v2 reasoning (Super-120B), one dev repeat, scored 42/48 (no_cap 2/8). v2 was
tuned only on dev; v2 test was not run. Prompt-only changes did not resolve missing-capability
cases on either tier. Total reported spend was approximately $0.128.

## Decision

The policy gate offers only actions relevant to the incident's local `candidate_faults`, subject
to device capabilities. Multiple candidate faults offer the union of their mapped actions, in
action-registry order. `enter_safe_mode` and `needs_human` are always offered.

| Fault | Relevant actions |
|---|---|
| `stream_down` | `restart_capture` |
| `freeze` | `restart_capture` |
| `blackout` | `set_exposure_bounded`, `request_manual_cleaning` |
| `overexposure` | `set_exposure_bounded` |
| `focus_drift` | `trigger_autofocus`, `request_manual_cleaning` |
| `low_fps` | `switch_stream_profile` |
| `pipeline_saturation` | `switch_stream_profile` |
| `lens_occlusion` | `request_manual_cleaning` |
| `fov_shift` | `request_recalibration` |
| `motion_blur` | none |
| `unknown` | none |

Cleaning is relevant to blackout because a covered lens can look dark, and to focus drift because a
dirty lens can blur the image. For a frozen confirming window, the orchestrator also includes
`freeze` when calculating offers, preserving `restart_capture` for frozen blackout. The existing
filter for image-setting actions on frozen frames remains in place.

## Consequences

- Nemotron cannot choose an action for a fault the local monitor did not list. This least-privilege
  restriction is accepted; ambiguous or unsupported cases still have the always-offered
  escalation actions.
- The policy gate, capability checks, executor, snapshots, timeouts, verification, and rollback
  behavior are unchanged.
- No action is added and no threshold changes.
- Evaluation moves to `golden_v2.jsonl`; case IDs, labels, expected actions, seeds, and split remain
  unchanged from v1, while offered actions are narrowed. This measures following the local
  diagnosis and respecting capability/policy constraints, not independent diagnosis:
  `candidate_faults[0]` determines each label and synthetic defocus carries `focus_ok=false`.
