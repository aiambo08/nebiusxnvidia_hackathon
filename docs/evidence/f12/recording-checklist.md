# Demo video recording checklist

Owner runbook for the public YouTube take. Follow [`docs/demo-script.md`](../../demo-script.md).
Do not claim a video exists until it is uploaded.

Target: **&lt; 3:00**, **≥ 1:00** continuous REAL HARDWARE, silence or cleared audio, no secrets on screen.

## T−15 min — setup

- [ ] Laptop plugged in; Windows power plan **Best performance**
- [ ] `NEBIUS_API_KEY` in `.env` (never open `.env` on camera; never paste the key)
- [ ] Clean DBs: delete or use new paths under `runs/`
- [ ] Browser zoom so badge + plan / gate / act / verify / model / cost are readable
- [ ] Close notifications, IM, password managers, other windows with secrets
- [ ] Camera and hand will stay in the same frame as the dashboard (picture-in-picture or split)
- [ ] Rehearse once: cover lens → `lens_occlusion` → ticket / `NEEDS_HUMAN` → uncover → `HEALTHY`
- [ ] Confirm one live Nemotron call in a short private rehearsal (expect ~$0.0001–0.001)

## T−2 min — commands ready

```powershell
# A [REAL HARDWARE] — keep running ≥ 65 s after HEALTHY
ra-demo dashboard --live --uri 0 --planner nemotron --db runs/demo-webcam.sqlite

# B [SIMULATION] — live Nemotron + COMMITTED (or use rules if Token Factory already shown in A)
ra-demo dashboard --scenario dark --planner nemotron --db runs/demo-dark.sqlite

# C [SIMULATION] — harmful plan + ROLLED BACK
ra-demo dashboard --scenario bad_action --planner rules --db runs/demo-bad-action.sqlite
```

Prefer **A with `--planner nemotron`** so the hardware minute also shows model / tokens / cost.
If A used rules only, **B must** show a successful live Nemotron call.

## Minute-by-minute take

| Clock | Mode | You do | Must be visible |
|---|---|---|---|
| **0:00–0:20** | SIMULATION (or still frame) | One sentence: camera reliability → MAPE-K | SIMULATION badge if dashboard is up |
| **0:20** | REAL HARDWARE | Start **A**; wait until state is **HEALTHY ≥ 15 s**; laptop still | `Mode: REAL HARDWARE`, planner chip |
| **0:35** | REAL HARDWARE | Cover the lens with your hand; **keep covered** | Physical hand + camera in frame |
| **0:40–1:10** | REAL HARDWARE | Hold cover; narrate briefly | `lens_occlusion`, plan JSON, gate approve, `request_manual_cleaning` ticket, `NEEDS_HUMAN` |
| **1:10–1:25** | REAL HARDWARE | Uncover; show close | `HEALTHY` / incident closed; badge still REAL HARDWARE |
| **1:25–1:55** | SIMULATION | Stop A; start **B** (`dark`) | SIMULATION badge; Nemotron model / tokens / cost; gate; **COMMITTED** |
| **1:55–2:20** | SIMULATION | Stop B; start **C** (`bad_action`) | SIMULATION badge; verify fail; **ROLLED BACK**; escalate |
| **2:20–2:40** | — | Voiceover: gate + verify + rollback; webcam has no exposure/focus commit | Clear SIMULATION vs REAL HARDWARE wording |
| **2:40–2:55** | — | Cite README numbers from reports; say open work (F4 HW, five-user, tag) | No invented metrics |

Stop the take if any of these fail: no `lens_occlusion`, no ticket/safe/needs_human, Token Factory down with no honest “local mode” line, or a secret appears. Do not splice SIMULATION into a REAL HARDWARE badge.

## After recording

- [ ] Watch once: badges never wrong; no `.env` / key / token string
- [ ] Export &lt; 3:00; upload **public** YouTube; copy URL
- [ ] Paste URL into Devpost + README/Devpost draft when ready
- [ ] Tag the commit shown in the video: `git tag -a v1.0-submission -m "submission"`
- [ ] Open repo, video and evidence links in an **incognito** window

## Do not claim

- Exposure / autofocus **commit** on the real webcam (`OpenCVSource` exposes `restart` only)
- `stream_down` → `restart_capture` end-to-end through the live dashboard (not rehearsed as a combined path)
- That REPLAY is deterministic
- That F4 REAL HARDWARE sessions or the five-user test are done unless the forms/reports exist
