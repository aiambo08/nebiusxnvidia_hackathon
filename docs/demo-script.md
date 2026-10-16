# Demo video script (< 3:00, public YouTube, no copyrighted music)

| Time | Scene | Must show |
|---|---|---|
| 0:00–0:20 | Problem & user | A camera can be "online" and useless |
| 0:20–0:40 | Healthy camera + downstream task (ArUco reference task) | live webcam, task score |
| 0:40–1:05 | Real physical fault: cover lens / lights off / defocus / move camera | **real hardware** |
| 1:05–1:30 | Signals + Nemotron diagnosis | model id, tokens, cost, JSON plan |
| 1:30–1:55 | Policy gate + action | approved/rejected reasons |
| 1:55–2:20 | Verification + commit / rollback | before/after metrics |
| 2:20–2:40 | Architecture, NVIDIA + Nebius | MAPE-K diagram |
| 2:40–2:55 | Results & cost | benchmark table from event files |

Physical footage between 0:20 and 2:20 ≥ 1 minute (Physical AI requirement).

Recording setup: laptop plugged in, Windows power mode "Best performance" — the 720p
probe p95 at 5 FPS was 54–112 ms under "Balanced" (single runs) vs 23.2 / 32.6 / 34.5 ms under
"Best performance" (3 runs, after geometry moved to a pool thread) on the owner's laptop
(`docs/evidence/f3/latency-hardware.md`).
