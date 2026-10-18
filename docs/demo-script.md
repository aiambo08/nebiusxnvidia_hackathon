# Demo video script (< 3:00, public YouTube, no copyrighted music)

Every segment below is labelled SIMULATION or REAL HARDWARE. Keep the dashboard mode badge visible
whenever the dashboard is on screen; do not splice simulated results into webcam footage.

| Time | Segment and on-screen action | Required panel / narration |
|---|---|---|
| 0:00–0:20 | [SIMULATION] Introduce the camera reliability problem with the dashboard running. | Keep the SIMULATION badge visible; explain the MAPE-K loop. |
| 0:20–1:25 | [REAL HARDWARE] Run the owner's webcam live for at least 65 seconds. Show the physical lens being covered, then wait for a confirmed incident. | Keep the REAL HARDWARE badge and physical input visible. Show the incident, JSON plan, gate decision and a cleaning ticket, safe mode or `needs_human` escalation. The gate offers only `enter_safe_mode`, `request_manual_cleaning` or `needs_human`; do not claim an exposure/focus commit. |
| 1:25–1:55 | [SIMULATION] Run `dark`: bounded exposure improves the downstream task and verification is COMMITTED. | Keep the SIMULATION badge visible. Show the live Nemotron call, model, tokens, cost, JSON plan, gate and COMMITTED result. |
| 1:55–2:20 | [SIMULATION] Run `bad_action`: the harmful plan fails verification and is ROLLED BACK. | Keep the SIMULATION badge visible; show the snapshot-backed rollback and human escalation. |
| 2:20–2:40 | [SIMULATION] Explain the policy gate, verification and rollback. | Distinguish simulated bounded device controls from webcam capabilities. |
| 2:40–2:55 | [SIMULATION] Summarize measured results and open work. | Cite the reports on screen; say that F4 hardware validation, the soak and the submission video remain pending until completed. |

The REAL HARDWARE webcam segment must run continuously for at least one minute. Covering the lens
should produce a detected incident. Show the plan and the gate's available actions, then show the
cleaning ticket, safe-mode outcome or `needs_human` escalation. `OpenCVSource.capabilities()`
returns only `restart` on the real webcam; physical exposure/focus control is not implemented, so
no exposure/focus commit or rollback is claimed. If the incident or expected outcome does not occur,
stop and report it; do not replace it with SIMULATION footage while the badge says REAL HARDWARE.

Use these commands:

```powershell
# [SIMULATION] successful live Token Factory/Nemotron call
ra-demo dashboard --scenario dark --planner nemotron --db runs/demo-dark.sqlite

# [SIMULATION] deterministic harmful action and rollback
ra-demo dashboard --scenario bad_action --db runs/demo-bad-action.sqlite

# [REAL HARDWARE] owner's webcam; keep it running for at least one minute
ra-demo dashboard --live --uri 0 --db runs/demo-webcam.sqlite
```

Expected startup: `Mode: SIMULATION` and `Planner: nemotron` for `dark`; `Mode: SIMULATION` and
`Planner: rules` for `bad_action`; `Mode: REAL HARDWARE` for the webcam. Each prints its `Database`
path and `Dashboard` URL. In the completed SIMULATION scenarios, `dark` is COMMITTED and
`bad_action` is ROLLED BACK; the webcam outcome is a cleaning ticket, safe mode or `needs_human`
escalation. Before rerunning a dashboard command, delete the database file named by `--db` or choose
a new path.

The recording must capture at least one successful live Nemotron call while `.env` contains
`NEBIUS_API_KEY`. Never show the key or its contents. The `dark` scenario uses simulated bounded
exposure; `bad_action` uses the scripted harmful plan. Keep the mode badge and plan/gate/verification
panels visible so these SIMULATION outcomes cannot be mistaken for webcam controls.

The dashboard panel map is: `mode` labels SIMULATION versus REAL HARDWARE; `planner` names the plan
source; `model` and `diag` show model ID/source, prompt, input/output tokens and cost; `plan` shows
the JSON plan; `gate` shows allow/reject and reasons; `act` shows the pre-action snapshot, action
execution and restoration; `verify` shows before/after values and the COMMITTED or ROLLED BACK
outcome.

Pre-recording checklist: connect the laptop to power and select Windows “Best performance”; put the
key in `.env` and confirm a live Nemotron call during rehearsal; never show the key or its contents;
set browser zoom so the required panels are readable; close notifications and unrelated windows;
keep the physical camera and hand input in frame; confirm the mode badge; use silence or cleared
audio, never copyrighted music. The owner's hardware latency evidence uses synthetic frames and
reports 23.2 / 32.6 / 34.5 ms p95 in three Best performance runs
([source](evidence/f3/latency-hardware.md)).

If the network or Token Factory fails, say “local mode—Token Factory unavailable” on screen and do
not imply a live Nemotron call occurred. A local-fallback recording is not a substitute for the
required successful live call; record a successful Nemotron call separately in the final video.

No optional `stream_down` → `restart_capture` segment is included: current tests cover disconnect
detection and restart/verification separately, but do not exercise the combined outage through the
live dashboard loop. The owner should not present that recovery as verified without a rehearsal
that proves it.

The owner uploads a public video; this document does not claim that a video exists.
