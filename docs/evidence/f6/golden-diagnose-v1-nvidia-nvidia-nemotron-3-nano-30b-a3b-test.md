# F6 golden-set evaluation — test

- Commit: `6e48ec8`
- Golden file SHA256: `3f0c5699f4d8f5464c6c020b799648d81f9a8f59fdfe5dcd694e1c84d8199d44`
- Generated: 2026-10-18T00:31:24.471073Z
- Model: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
- Prompt version: `diagnose_v1`
- Evaluated rows: 264
- Run cost: $0.02940384
- BudgetGuard spent: $0.02940384

This box measures whether the planner follows the local diagnosis and respects capability/policy constraints; candidate_faults[0] determines the label in every case and synthetic defocus carries focus_ok=false, so it is not a test of independent diagnosis. Deterministic rules baseline: [golden-rules-baseline-test.md](golden-rules-baseline-test.md).

## F6 gate (test split pooled across repeats)

| Box | Result | Value | Threshold |
|---|---:|---:|---:|
| Schema-valid rate | **PASS** | 100.000% | 98% |
| Action accuracy | **FAIL** | 75.379% | 90% |
| Projected cost for 300 incidents | **PASS** | $0.033413 | $23.00 |

## Secondary metrics

- Test rows: 264
- Mean cost per API call: $0.00011138
- Mean cost per incident: $0.00011138
- Valid on first try: 1.0
- Policy accepted: 1.0
- Diagnosis accuracy: 1.0
- Latency p50/p95: 905.25 / 1225.17 ms
- Models: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
- Prompt versions: diagnose_v1

### Accuracy by scenario and variant

| Scenario / variant | Cases | Accuracy |
|---|---:|---:|
| dark/base | 42 | 0.000% |
| dark/injection | 6 | 0.000% |
| dark/no_cap | 6 | 50.000% |
| defocus/base | 42 | 100.000% |
| defocus/injection | 6 | 100.000% |
| defocus/no_cap | 6 | 0.000% |
| freeze/base | 42 | 100.000% |
| freeze/injection | 6 | 100.000% |
| freeze/no_cap | 6 | 66.667% |
| occlusion/base | 42 | 100.000% |
| occlusion/injection | 6 | 100.000% |
| overexposure/base | 42 | 100.000% |
| overexposure/injection | 6 | 100.000% |
| overexposure/no_cap | 6 | 0.000% |

### Action confusion

- `enter_safe_mode|needs_human -> enter_safe_mode`: 4
- `enter_safe_mode|needs_human -> restart_capture`: 6
- `enter_safe_mode|needs_human -> switch_stream_profile`: 2
- `enter_safe_mode|needs_human|request_manual_cleaning -> request_manual_cleaning`: 3
- `enter_safe_mode|needs_human|request_manual_cleaning -> restart_capture`: 3
- `enter_safe_mode|needs_human|request_manual_cleaning -> set_exposure_bounded`: 6
- `request_manual_cleaning -> request_manual_cleaning`: 48
- `restart_capture -> restart_capture`: 48
- `set_exposure_bounded -> enter_safe_mode`: 4
- `set_exposure_bounded -> request_manual_cleaning`: 7
- `set_exposure_bounded -> restart_capture`: 37
- `set_exposure_bounded -> set_exposure_bounded`: 48
- `trigger_autofocus -> trigger_autofocus`: 48
