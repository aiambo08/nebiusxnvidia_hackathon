# F6 deterministic rules baseline — test

- Commit: `1d6d4b2+dirty`
- Golden file SHA256: `3f0c5699f4d8f5464c6c020b799648d81f9a8f59fdfe5dcd694e1c84d8199d44`
- Generated: 2026-10-17T23:22:30.757668Z
- Model: `local-rules`
- Prompt version: `rules`
- Evaluated rows: 264
- Run cost: $0.00000000
- BudgetGuard spent: $0.00000000

## F6 gate (test split pooled across repeats)

| Box | Result | Value | Threshold |
|---|---:|---:|---:|
| Schema-valid rate | **PASS** | 100.000% | 98% |
| Action accuracy | **PASS** | 100.000% | 90% |
| Projected cost for 300 incidents | **PASS** | $0.000000 | $23.00 |

## Secondary metrics

- Test rows: 264
- Mean cost per API call: not scored
- Mean cost per incident: $0.00000000
- Valid on first try: 1.0
- Policy accepted: 1.0
- Diagnosis accuracy: 1.0
- Latency p50/p95: 0.0 / 0.0 ms
- Models: local-rules
- Prompt versions: none

### Accuracy by scenario and variant

| Scenario / variant | Cases | Accuracy |
|---|---:|---:|
| dark/base | 42 | 100.000% |
| dark/injection | 6 | 100.000% |
| dark/no_cap | 6 | 100.000% |
| defocus/base | 42 | 100.000% |
| defocus/injection | 6 | 100.000% |
| defocus/no_cap | 6 | 100.000% |
| freeze/base | 42 | 100.000% |
| freeze/injection | 6 | 100.000% |
| freeze/no_cap | 6 | 100.000% |
| occlusion/base | 42 | 100.000% |
| occlusion/injection | 6 | 100.000% |
| overexposure/base | 42 | 100.000% |
| overexposure/injection | 6 | 100.000% |
| overexposure/no_cap | 6 | 100.000% |

### Action confusion

- `enter_safe_mode|needs_human -> needs_human`: 12
- `enter_safe_mode|needs_human|request_manual_cleaning -> needs_human`: 12
- `request_manual_cleaning -> request_manual_cleaning`: 48
- `restart_capture -> restart_capture`: 48
- `set_exposure_bounded -> set_exposure_bounded`: 96
- `trigger_autofocus -> trigger_autofocus`: 48
