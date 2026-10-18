# F10 soak report — SIMULATION

- code revision: `70d7848`
- database SHA-256: `ff62ae0231a925d99fb295b9b546e8566a21f6ffaa5a41db662abd2fb40c6847`
- regenerate from the repository root:
  `python scripts/soak_report.py --db docs/evidence/f10/soak/soak.sqlite && mv docs/evidence/f10/soak/report.md docs/evidence/f10/soak/soak.md && mv docs/evidence/f10/soak/report.json docs/evidence/f10/soak/soak.json`
- duration: 4.0002 h
- complete: True

| Gate | Result | Details |
|---|---:|---|
| No crash | PASS | 0 error/exception events |
| Sustained leak | True | RSS growth 7.178 MB (limit 32.000 MB); threads 2; fds 6 |
| False alarms | PASS | 0.250/h (limit 1.000/h) |
| Detection (reported, not gated) | 0.958 | 23/24 faults |

Overall: **PASS**

## Notes (SIMULATION)
- fault-0023 (overexpose) was scheduled at elapsed 14400 s, the requested end of the run, and was cleared by `run_end` 0.02 s later; it had no observable window. Detection is therefore 23/24 raw and 23/23 for faults that were active for at least one analysis window. Detection is informational in this harness (`gate: false`); the F10 detection minimum is evidenced by A1 in `docs/evidence/f10/experiments.md`.
- The one unmatched incident (`266430bd-5385-433e-99a6-a33bc86f3cf4`) is a `low_fps` confirmation at 16:29:26 UTC, 269 s after freeze fault-0022 was cleared by remediation (16:24:57 UTC) and outside the 60 s matching window. `switch_stream_profile` was applied, verification failed (original fault still present; new fault `focus_drift`), rollback restored the exact snapshot, the incident escalated to NEEDS_HUMAN and closed HEALTHY 3 s later. It is counted as a false alarm: 1 in 4.0 h = 0.25/h, within the 1/h minimum.
- No live Token Factory calls (rules planner), 0 USD.
