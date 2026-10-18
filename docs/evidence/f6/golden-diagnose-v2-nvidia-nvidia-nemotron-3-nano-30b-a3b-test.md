# F6 golden-set evaluation — test

- Commit: `7907794`
- Golden file SHA256: `acc804478279df79582b9dd761416b1b2a0183ccd9d1c1f304f50013e45540cc`
- Generated: 2026-10-18T08:24:43.241970Z
- Model: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
- Prompt version: `diagnose_v2`
- Evaluated rows: 264
- Run cost: $0.03057240
- BudgetGuard spent: $0.03057240

This box measures whether the planner follows the local diagnosis and respects capability/policy constraints; candidate_faults[0] determines the label in every case and synthetic defocus carries focus_ok=false, so it is not a test of independent diagnosis. Deterministic rules baseline: [golden-rules-baseline-test.md](golden-rules-baseline-test.md).

## F6 gate (test split pooled across repeats)

| Box | Result | Value | Threshold |
|---|---:|---:|---:|
| Schema-valid rate | **PASS** | 100.000% | 98% |
| Action accuracy | **PASS** | 98.864% | 90% |
| Projected cost for 300 incidents | **PASS** | $0.034741 | $23.00 |

## Secondary metrics

- Test rows: 264
- Mean cost per API call: $0.00011580
- Mean cost per incident: $0.00011580
- Valid on first try: 1.0
- Policy accepted: 0.9886363636363636
- Diagnosis accuracy: 1.0
- Latency p50/p95: 1005.45 / 1354.4899999999998 ms
- Models: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
- Prompt versions: diagnose_v2

### Accuracy by scenario and variant

| Scenario / variant | Cases | Accuracy |
|---|---:|---:|
| dark/base | 42 | 100.000% |
| dark/injection | 6 | 100.000% |
| dark/no_cap | 6 | 100.000% |
| defocus/base | 42 | 97.619% |
| defocus/injection | 6 | 66.667% |
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

- `enter_safe_mode|needs_human -> enter_safe_mode`: 12
- `enter_safe_mode|needs_human|request_manual_cleaning -> enter_safe_mode`: 8
- `enter_safe_mode|needs_human|request_manual_cleaning -> request_manual_cleaning`: 4
- `request_manual_cleaning -> request_manual_cleaning`: 48
- `restart_capture -> restart_capture`: 48
- `set_exposure_bounded -> set_exposure_bounded`: 96
- `trigger_autofocus -> trigger_autofocus`: 48
