# Demo video script (< 3:00, public YouTube, no copyrighted music)

| Time | On-screen action | Required panel / narration |
|---|---|---|
| 0:00–0:20 | State the user problem and show the camera/task. | Introduce camera reliability; show the SIMULATION/REAL HARDWARE badge. |
| 0:20–0:40 | Show the healthy webcam and ArUco task before changing anything. | Live source, task result and mode badge. |
| 0:40–1:05 | Apply a real physical input: cover lens, change lighting, defocus if safe, or move camera. | Keep the camera and physical change visible. |
| 1:05–1:30 | Show detection and the runtime Nemotron plan. | Model ID, input/output tokens, cost, JSON plan and SIMULATION/REAL HARDWARE label. |
| 1:30–1:55 | Show policy decision, then approved action or rejection. | Gate decision and reasons; snapshot/execution status. |
| 1:55–2:20 | Show downstream verification and final state. | Before/after values, commit or rollback, restored snapshot if rolled back. |
| 2:20–2:40 | Explain MAPE-K and NVIDIA/Nebius components. | Architecture diagram and local fallback. |
| 2:40–2:55 | State results and limitations. | Cite the result files shown; do not present pending results as passed. |

Physical footage between 0:20 and 2:20 must total at least one minute (Physical AI requirement).

Start commands (verify flags with `ra-demo dashboard --help`):

```powershell
ra-demo dashboard --scenario dark
ra-demo dashboard --live --uri 0
```

The dashboard's diagnosis panel shows model, tokens, cost and JSON plan; the policy panel shows
gate decision/reasons; the verification panel shows before/after values and COMMITTED or ROLLED
BACK. The mode badge distinguishes SIMULATION from REAL HARDWARE. Planner labels distinguish local
rules/fallback from a live or cached Nemotron plan.

Pre-recording checklist: connect laptop power; select Windows “Best performance”; confirm `.env`
exists only if using Token Factory; keep the key out of view; set browser zoom so the full panel is
readable; close notifications. The owner's hardware latency evidence uses synthetic frames and
reports 23.2 / 32.6 / 34.5 ms p95 in three Best performance runs
([source](docs/evidence/f3/latency-hardware.md)).

If the network or Token Factory fails, continue in local mode, say “local mode—Token Factory
unavailable” on screen, and do not imply a live Nemotron call occurred. Never show a secret or add
copyrighted music. The owner uploads a public video; this document does not claim it exists.
