# F6 golden-set evaluation — dev

- Commit: `7907794`
- Golden file SHA256: `acc804478279df79582b9dd761416b1b2a0183ccd9d1c1f304f50013e45540cc`
- Generated: 2026-10-18T08:21:48.374035Z
- Model: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
- Prompt version: `diagnose_v2`
- Evaluated rows: 144
- Run cost: $0.01655832
- BudgetGuard spent: $0.01655832

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
- Latency p50/p95: 983.25 / 1296.5549999999998 ms
- Models: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
- Prompt versions: diagnose_v2

### Accuracy by scenario and variant

| Scenario / variant | Cases | Accuracy |
|---|---:|---:|
| dark/base | 18 | 100.000% |
| dark/injection | 6 | 100.000% |
| dark/no_cap | 6 | 100.000% |
| defocus/base | 18 | 100.000% |
| defocus/injection | 6 | 50.000% |
| defocus/no_cap | 6 | 100.000% |
| freeze/base | 18 | 100.000% |
| freeze/injection | 6 | 100.000% |
| freeze/no_cap | 6 | 100.000% |
| occlusion/base | 18 | 100.000% |
| occlusion/injection | 6 | 100.000% |
| overexposure/base | 18 | 100.000% |
| overexposure/injection | 6 | 100.000% |
| overexposure/no_cap | 6 | 100.000% |

### Action confusion

- `enter_safe_mode|needs_human -> enter_safe_mode`: 12
- `enter_safe_mode|needs_human|request_manual_cleaning -> enter_safe_mode`: 8
- `enter_safe_mode|needs_human|request_manual_cleaning -> request_manual_cleaning`: 4
- `request_manual_cleaning -> request_manual_cleaning`: 24
- `restart_capture -> restart_capture`: 24
- `set_exposure_bounded -> set_exposure_bounded`: 48
- `trigger_autofocus -> trigger_autofocus`: 24
