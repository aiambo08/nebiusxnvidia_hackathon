# README media — provenance

Every image here is labelled SIMULATION on screen. None shows REAL HARDWARE, a webcam or a person.
The defocus capture and fault gallery were produced on 2026-10-19 from `main` at `64ec0c2`.
`dashboard-bad_action.gif` and `nemotron-live-call.png` were recaptured on 2026-10-19 from
dashboard fix commit `5e8008775fd2484f901831d3623d53b2dbf7f525`.

| File | What it shows | How it was produced |
|---|---|---|
| `dashboard-nemotron-defocus.gif` | One incident end to end: `focus_drift` detected locally, **live Nemotron call** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, 1284 in / 198 out tokens, $0.00012, 1574 ms) proposes `trigger_autofocus`, gate APPROVED, executor applies it after a snapshot, verification COMMITTED (`task.success_rate` 0.000 → 1.000). | `ra-demo dashboard --planner nemotron --scenario defocus --pace 1.0`, page captured every 0.5 s at 1440×900, played back at 2× speed. |
| `nemotron-live-call.png` | A **live Nemotron plan that did not help**: for `blackout` it proposed `set_exposure_bounded {"delta_ev": 1}`; the gate approved it, but verification saw the original fault still present and rolled back to the snapshot (incident ends NEEDS_HUMAN). The recaptured call used 1316 input / 186 output tokens, cost $0.0001236, and took 1238 ms. | `ra-demo dashboard --planner nemotron --scenario dark --pace 1.0`, one scenario and one capture. |
| `dashboard-bad_action.gif` | Rollback of a harmful action: the scripted demo planner (not Nemotron) deliberately proposes a policy-valid but wrong exposure change; verification detects the regression and restores the snapshot. The header identifies `scripted` from the first frame. | `ra-demo dashboard --scenario bad_action --pace 1.0`, captured at 1440×900 every 0.5 s and played at 2× speed. |
| `fault-gallery.png` | One `SyntheticSource` frame per injected fault (healthy, dark, defocus, occlusion, overexposure, fov shift). | `python scripts/render_fault_gallery.py --out docs/media/fault-gallery.png` (deterministic, seed 0). |

Total Token Factory spend for these captures: seven live planner calls (`usage` table of the
capture databases), $0.0008336 in total ($0.00071 for the first six, plus $0.0001236 for the
recaptured `dark` scenario). Outcomes of the first six live plans: `defocus` committed;
`lens_occlusion` opened a cleaning ticket and the camera returned to HEALTHY; `blackout` (twice)
and `overexposure` (twice) were rolled back because the original fault was still present or a
guard metric regressed. For `blackout` Nemotron proposed `delta_ev: 1`, where the deterministic
rules planner proposes `delta_ev: 2` and commits. The verifier caught every one of
them, and that is shown here, not hidden. The seventh live call in the single-scenario `dark`
capture also proposed `delta_ev: 1`; verification rolled it back and escalated to NEEDS_HUMAN.
