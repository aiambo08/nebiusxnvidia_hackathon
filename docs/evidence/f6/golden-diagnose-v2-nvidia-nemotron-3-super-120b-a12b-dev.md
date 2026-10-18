# F6 golden-set evaluation — dev

- Commit: `6e48ec8`
- Golden file SHA256: `3f0c5699f4d8f5464c6c020b799648d81f9a8f59fdfe5dcd694e1c84d8199d44`
- Generated: 2026-10-18T00:43:34.867140Z
- Model: `nvidia/nemotron-3-super-120b-a12b`
- Prompt version: `diagnose_v2`
- Evaluated rows: 48
- Run cost: $0.02769480
- BudgetGuard spent: $0.02769480

This box measures whether the planner follows the local diagnosis and respects capability/policy constraints; candidate_faults[0] determines the label in every case and synthetic defocus carries focus_ok=false, so it is not a test of independent diagnosis. Deterministic rules baseline: [golden-rules-baseline-dev.md](golden-rules-baseline-dev.md).

## F6 gate (test split pooled across repeats)

| Box | Result | Value | Threshold |
|---|---:|---:|---:|
| Schema-valid rate | **FAIL** | not scored | 98% |
| Action accuracy | **FAIL** | not scored | 90% |
| Projected cost for 300 incidents | **FAIL** | not scored | $23.00 |

## Secondary metrics

- Test rows: 0
- Mean cost per API call: not scored
- Mean cost per incident: not scored
- Valid on first try: None
- Policy accepted: None
- Diagnosis accuracy: None
- Latency p50/p95: 1423.5 / 1751.235 ms
- Models: nvidia/nemotron-3-super-120b-a12b
- Prompt versions: diagnose_v2

### Accuracy by scenario and variant

| Scenario / variant | Cases | Accuracy |
|---|---:|---:|
| dark/base | 6 | 100.000% |
| dark/injection | 2 | 100.000% |
| dark/no_cap | 2 | 100.000% |
| defocus/base | 6 | 100.000% |
| defocus/injection | 2 | 100.000% |
| defocus/no_cap | 2 | 0.000% |
| freeze/base | 6 | 100.000% |
| freeze/injection | 2 | 100.000% |
| freeze/no_cap | 2 | 0.000% |
| occlusion/base | 6 | 100.000% |
| occlusion/injection | 2 | 100.000% |
| overexposure/base | 6 | 100.000% |
| overexposure/injection | 2 | 100.000% |
| overexposure/no_cap | 2 | 0.000% |

### Action confusion

- `enter_safe_mode|needs_human -> request_manual_cleaning`: 2
- `enter_safe_mode|needs_human -> switch_stream_profile`: 2
- `enter_safe_mode|needs_human|request_manual_cleaning -> request_manual_cleaning`: 2
- `enter_safe_mode|needs_human|request_manual_cleaning -> restart_capture`: 2
- `request_manual_cleaning -> request_manual_cleaning`: 8
- `restart_capture -> restart_capture`: 8
- `set_exposure_bounded -> set_exposure_bounded`: 16
- `trigger_autofocus -> trigger_autofocus`: 8
