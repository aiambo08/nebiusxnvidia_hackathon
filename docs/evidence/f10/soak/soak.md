# F10 soak report — SIMULATION

- code revision: `70d7848`
- database SHA-256: `ff62ae0231a925d99fb295b9b546e8566a21f6ffaa5a41db662abd2fb40c6847`
- regenerate command: `python scripts/soak_report.py --db docs/evidence/f10/soak/soak.sqlite --out-dir docs/evidence/f10/soak`
- duration: 4.0002 h
- complete: yes

| Gate | Result | Details |
|---|---|---|
| No crash (A) | PASS | 0 error/exception events |
| Sustained leak (B) | PASS | RSS growth 7.178 MB (limit 32.000 MB); threads 2; fds 6 |
| False alarms (C) | PASS | 0.250/h (maximum 1.000/h) |
| Duration | PASS | observed 14400.865 s; requested 14400.000 s; minimum 14400.000 s |
| Sample coverage | PASS | 241 samples at 60.000 s; maximum gap 60.915 s (maximum 120.000 s) |
| Detection (reported, not gated) | 0.958 | 23/24 faults |

Overall: **PASS**

## Notes (SIMULATION)
- Unmatched incident 266430bd-5385-433e-99a6-a33bc86f3cf4: confirmed low_fps at 2026-10-18 16:29:26 UTC, 268.479 s after fault-0022 (freeze) ended; actions: switch_stream_profile (execution success, verification rolled_back); rollback (restored); closed HEALTHY 19.019 s later (2.304 s after NEEDS_HUMAN).
- Fault fault-0023 (overexpose) had no incident; active for 0.026 s; started at or after requested duration: yes.
- Detection is informational (`gate: false`); the F10 detection minimum is evidenced by A1 in docs/evidence/f10/experiments.md
- Planner: local-rules, rules, live calls 0, cost USD 0.000000