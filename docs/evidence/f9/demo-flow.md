# F9 dashboard SIMULATION and REPLAY evidence

- Source revision: `bc6ea44` (`origin/main`, the merged PR #72 including the header-planner fix).
- Captured on 2026-10-20 with the repo's local `.venv` (Python 3.13.16) via
  `runs/f9_refresh_harness.py`. The raw evidence is in `runs/f9-refresh-evidence.json`
  (git-ignored; reproducible by rerunning the harness from the repo root).
- Each SIMULATION run used the CLI's default `--pace` and a fresh database path. No input or
  external service drove the runs.
- Timing method: the harness launched each exact command below, then polled
  `GET http://127.0.0.1:8000/api/incidents` every 50 ms. Elapsed time is monotonic
  launch-to-first poll containing the terminal EventStore event. For `occlusion`, the
  measured event is the `NEEDS_HUMAN` state; for the other scenarios it is `closed`. The
  event timestamp is from that same EventStore event. Each dashboard process was terminated
  right after its terminal event was observed (the runner's wrapper exit code reflects the
  final SIGTERM of the tour server, which does not affect the recorded events).

## SIMULATION runs

| Scenario | Exact command | EventStore terminal event (UTC) | Wall time |
|---|---|---|---:|
| `dark` | `ra-demo dashboard --scenario dark --planner rules --db runs/f9-dark.sqlite` | `closed` — `2026-10-20T17:11:09.231342+00:00` | 24.727 s |
| `defocus` | `ra-demo dashboard --scenario defocus --planner rules --db runs/f9-defocus.sqlite` | `closed` — `2026-10-20T17:11:33.644101+00:00` | 24.368 s |
| `occlusion` | `ra-demo dashboard --scenario occlusion --planner rules --db runs/f9-occlusion.sqlite` | `state=NEEDS_HUMAN` — `2026-10-20T17:11:54.560050+00:00` | 20.900 s |
| `bad_action` | `ra-demo dashboard --scenario bad_action --planner rules --db runs/f9-bad_action.sqlite` | `closed` — `2026-10-20T17:12:28.839026+00:00` | 34.274 s |
| `frozen_black` | `ra-demo dashboard --scenario frozen_black --planner rules --db runs/f9-frozen_black.sqlite` | `closed` — `2026-10-20T17:12:53.713988+00:00` | 24.878 s |
| `overexposure` | `ra-demo dashboard --scenario overexposure --planner rules --db runs/f9-overexposure.sqlite` | `closed` — `2026-10-20T17:13:18.830269+00:00` | 25.115 s |
| `freeze` | `ra-demo dashboard --scenario freeze --planner rules --db runs/f9-freeze.sqlite` | `closed` — `2026-10-20T17:13:46.057225+00:00` | 27.197 s |

Each run reported the standard CLI banner (`Mode: SIMULATION`, `Planner: rules`, the fresh
database path, `Dashboard: http://127.0.0.1:8000`); Uvicorn access lines are omitted here.

## REPLAY run

OpenCV generated `runs/f9-recorded-source.mp4`: 320×240, 300 frames at 15 fps, 106,881 bytes.
The following command used the CLI's supported `--port` option so the REPLAY server could run
on 8001:

```text
$ ra-demo dashboard --live --uri runs/f9-recorded-source.mp4 --planner rules --db runs/f9-replay-run.sqlite --port 8001
Mode: REPLAY
Planner: rules
Database: runs/f9-replay-run.sqlite
Dashboard: http://127.0.0.1:8001
```

The API status response reported `mode=REPLAY` after 1.06 s; the process was then stopped.
This demonstrates the REPLAY label and the read-only loop on a recorded file, not an
end-to-end fault recovery result.

## Scenario switch: header planner resets (reviewer B1)

A tour chained two scenarios at the CLI's default pace with `--gap 1`:

```text
$ ra-demo dashboard --scenario bad_action --scenario dark --planner rules --pace 1.0 --gap 1 --db runs/f9-tour.sqlite
```

The harness polled `/api/status` every 100 ms for 180 s. The header planner is the field the
dashboard renders from `/api/status`, decided by the backend (scenario start timestamp +
latest plan of an incident opened inside the current scenario; see `header_planner_source`
in `apps/api/main.py`).

- Before the switch (t = 40.449 s): `scenario=bad_action`, `planner_source=scripted`,
  `model=None`.
- First sample after the switch (t = 40.556 s): `scenario=dark`, `planner_source=None`,
  `scenario_started_at=2026-10-20T17:14:27.848408+00:00`, `model=None`.
- 1,227 further `dark` samples: `planner_source` never returned to `scripted`; `model`
  stayed `None`.

So the stale incident from the previous scenario no longer drives the header: the reviewer's
B1 repro (header showing the previous scenario's planner for ~15 s) is fixed at the API and
CLI level. The behavioral test
`test_dashboard_header_planner_resets_across_scenario_switch` covers the same switch through
the real dashboard scenario runner + `TestClient`.

## Rendered labels

Both screenshots come from headless Chrome (`--headless=new`, 1440×900) against live servers
started with the same commands:

- `dashboard-simulation-bad-action.png`: `SIMULATION` badge, `scenario bad_action`, header
  `planner scripted (demo planner, no LLM call)`, `model –`, `prompt –` (N3: no Nemotron
  advertised for a scripted planner), `Token Factory spend $0.0000 / $27 cap`, `event chain
  verified`, and a completed rollback loop (`ROLLED BACK (snapshot restored)`,
  snapshot restored, verifier metrics before/after).
- `dashboard-replay.png`: `REPLAY` badge, source `Video replay`, `planner rules (local
  planner, no LLM call)`, `model –`, `prompt –`, `event chain verified`.

Both captures were cross-checked against the rendered DOM (`--dump-dom`): the header chips
show exactly those values (planner label, `model –`, `prompt –`).

## Known limitation (REPLAY)

A file source is read as fast as it decodes, so the replay panel showed Capture FPS ≈ 13110
for the synthetic 15 fps clip in this run (the committed screenshot shows 9291.6; the value
depends on host decode speed). When the clip ends, the watchdog reports `stream_down` and
the agent plans `restart_capture`. REPLAY is not deterministic: an independent review on
`9d026d1` saw different incident sequences in two runs on the same clip. The deterministic demo
for the video is therefore the SIMULATION mode (`SyntheticSource`). REPLAY proves the label and
the read-only loop on a recorded file, not real-time or repeatable playback.

Still open for F9: the five-user check, the no-secrets check on the final video, and the
real-webcam (`--live --uri 0`) run on the owner's machine. The secret/audit/license checks
(see `runs/f9-audit-report.md`) pass: 244 tracked files, 0 unallowlisted findings; 35
distributions in the license report; corresponding tests 49 passed.
