# Demo video script (< 3:00, public YouTube, no copyrighted music)

| Time | On-screen action | Required panel / narration |
|---|---|---|
| 0:00–0:20 | Open on the camera and dashboard; state the reliability problem and show the mode badge. | `mode` panel must read SIMULATION for rehearsal or REAL HARDWARE for webcam footage. |
| 0:20–0:40 | Show a healthy webcam view and the ArUco task result before changing the scene. | Keep the camera/task output and `mode` badge in frame. |
| 0:40–1:05 | Cover the lens or change lighting by hand; keep the physical input visible. | Do not use a simulated or inserted clip while the badge says REAL HARDWARE. |
| 1:05–1:30 | Show the confirmed incident and selected plan. | `diag` shows source/model/prompt/tokens/cost; `model` shows model ID; `plan` shows JSON. |
| 1:30–1:55 | Show the policy decision before the device action. | `gate` shows decision/reasons; `act` shows the pre-action snapshot and execution status. |
| 1:55–2:20 | Show downstream verification and the resulting state. | `verify` shows before/after metrics and COMMITTED or ROLLED BACK; `act` shows restoration when rolled back. |
| 2:20–2:40 | Explain MAPE-K and NVIDIA/Nebius components. | Point to the `planner` source and explain the local-rule fallback. |
| 2:40–2:55 | State results and limitations. | Cite the evidence shown; identify pending results and distinguish SIMULATION from REAL HARDWARE. |

Physical footage between 0:20 and 2:20 must total at least one minute (Physical AI requirement).

Commands for a SIMULATION rehearsal and a REAL HARDWARE webcam recording (flags checked with
`ra-demo dashboard --help`; the webcam command's help form was also checked without opening the
camera):

```powershell
ra-demo dashboard --scenario dark
ra-demo dashboard --live --uri 0
```

Panel map: `mode` labels SIMULATION versus REAL HARDWARE; `planner` names the plan source; `model`
and `diag` show model ID/source, prompt, input/output tokens and cost; `plan` shows the JSON plan;
`gate` shows the allow/reject decision and reasons; `act` shows the pre-action snapshot, action
execution and restoration; `verify` shows before/after values and the COMMITTED or ROLLED BACK
outcome. Say “local mode—Token Factory unavailable” on screen if the provider is unavailable or
the local fallback is used; do not present a cached or local plan as a live Nemotron response.

Pre-recording checklist: connect the laptop to power and select Windows “Best performance”; create
or use `.env` only if Token Factory is needed, and never show the key or its contents; set browser
zoom so all required panels are readable; close notifications and unrelated windows; frame the
physical camera and hand input; confirm mode before recording; use silence or cleared audio, never
copyrighted music. The owner's hardware latency evidence uses synthetic frames and reports
23.2 / 32.6 / 34.5 ms p95 in three Best performance runs
([source](evidence/f3/latency-hardware.md)).

If the network or Token Factory fails, continue in local mode, say “local mode—Token Factory
unavailable” on screen, and do not imply a live Nemotron call occurred. Never show a secret or add
copyrighted music. The owner uploads a public video; this document does not claim it exists.
