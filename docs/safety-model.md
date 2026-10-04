# Safety model

## Assets
Managed perception pipeline (camera settings, stream profile, downstream task), the Token Factory
budget, API keys, private recordings.

## Threats and controls

| Threat | Control | Test |
|---|---|---|
| LLM invents a tool | Allowlist in `policy/gate.py`; unknown names rejected | `tests/adversarial/test_policy_fuzz.py` |
| LLM passes out-of-range / wrong-type / extra args | Typed `ParamSpec` bounds; NaN/inf rejected; extra keys rejected | adversarial |
| LLM picks an action not offered for this incident | Plan action must be in `incident.allowed_actions` | unit |
| Action spam / oscillation | Per-action cooldown + hourly rate limit | adversarial |
| Prompt injection via camera metadata (names, ONVIF strings, logs) | Only whitelisted numeric fields and enums enter the packet; free text truncated and marked untrusted; output is schema-validated | `tests/unit/test_planner.py` |
| Action makes the task worse | Verification window + guard metrics + automatic rollback | `tests/unit/test_verifier.py` |
| Crash mid-action | Snapshot persisted **before** apply; idempotent rollback | `tests/unit/test_actions.py` |
| Budget exhaustion | Soft/demo/hard caps, cache, max calls per incident | `tests/unit/test_budget.py` |
| Cloud outage | Timeout + circuit breaker → local `needs_human` plan | `tests/unit/test_planner.py` |
| Secret leakage | `.env` git-ignored, redacted logging, gitleaks in CI | CI |

## Action risk classes
- **low / auto**: `restart_capture`, `switch_stream_profile`, `set_exposure_bounded`,
  `trigger_autofocus`, `enter_safe_mode` (logical).
- **human**: `request_manual_cleaning`, re-aim / recalibrate camera. The agent only creates a ticket.
- **forbidden**: any physical actuation beyond camera imaging settings, firmware changes,
  irreversible configuration.
