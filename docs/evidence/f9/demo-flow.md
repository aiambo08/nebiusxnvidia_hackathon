# F9 dashboard SIMULATION and REPLAY evidence

- Source revision: `788dc10` (`origin/main`); the production CLI and dashboard code were unchanged.
- Captured on this VM on 2026-10-18. The F9 test and evidence edits were in the worktree.
- Each SIMULATION run used the CLI's default `--pace` and a fresh database path. No input or
  external service drove the runs.
- Timing method: a local process launched each exact command below, then polled
  `GET http://127.0.0.1:8000/api/incidents` every 50 ms. Elapsed time is monotonic launch-to-first
  poll containing the terminal EventStore event. For `occlusion`, the measured event is the
  `NEEDS_HUMAN` state; for the other scenarios, it is `closed`. The event timestamp is from that
  same EventStore event. Each process exited 0 after the event was observed.
- The output transcripts retain each command's CLI banner and the measured terminal result;
  repetitive Uvicorn request-access lines are omitted.

## SIMULATION runs

| Scenario | Exact command | CLI output | EventStore terminal event (UTC) | Wall time |
|---|---|---|---|---:|
| `dark` | `ra-demo dashboard --scenario dark --planner rules --db runs/f9-dark.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-dark.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:24:57.871624+00:00` | 22.864 s |
| `defocus` | `ra-demo dashboard --scenario defocus --planner rules --db runs/f9-defocus.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-defocus.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:25:21.237139+00:00` | 22.879 s |
| `occlusion` | `ra-demo dashboard --scenario occlusion --planner rules --db runs/f9-occlusion.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-occlusion.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `state=NEEDS_HUMAN` — `2026-10-18T20:25:41.231917+00:00` | 19.734 s |
| `bad_action` | `ra-demo dashboard --scenario bad_action --planner rules --db runs/f9-bad_action.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-bad_action.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:26:13.972787+00:00` | 32.456 s |
| `frozen_black` | `ra-demo dashboard --scenario frozen_black --planner rules --db runs/f9-frozen_black.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-frozen_black.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:26:37.233801+00:00` | 22.999 s |
| `overexposure` | `ra-demo dashboard --scenario overexposure --planner rules --db runs/f9-overexposure.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-overexposure.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:27:00.388594+00:00` | 22.902 s |
| `freeze` | `ra-demo dashboard --scenario freeze --planner rules --db runs/f9-freeze.sqlite` | `Mode: SIMULATION`<br>`Planner: rules`<br>`Database: runs/f9-freeze.sqlite`<br>`Dashboard: http://127.0.0.1:8000` | `closed` — `2026-10-18T20:27:25.840185+00:00` | 24.966 s |

For each command, the captured output began with the listed four CLI banner lines. Uvicorn
reported application startup and clean shutdown; the output from those lines was omitted along
with its repeated API polling logs.

## REPLAY run

OpenCV generated `runs/f9-recorded-source.mp4`: 320×240, 300 frames at 15 fps, 177,311 bytes.
The following command used the CLI's supported `--port` option so the REPLAY server could run on
8001:

```text
$ ra-demo dashboard --live --uri runs/f9-recorded-source.mp4 --planner rules --db runs/f9-replay-run.sqlite --port 8001
Mode: REPLAY
Planner: rules
Database: runs/f9-replay-run.sqlite
Dashboard: http://127.0.0.1:8001
INFO:     Started server process [358577]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
INFO:     127.0.0.1:59368 - "GET /api/status HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [358577]
api_status_mode=REPLAY exit=0
```

The API status response also reported `mode=REPLAY`. The process was stopped after readiness was
confirmed; this demonstrates the REPLAY label and dashboard startup, not an end-to-end fault
recovery result.

The follow-up docs commit ticks three F9 boxes (≤ 90 s flow, no manual interaction, mode labels); the five-user, no-secrets-in-video and real-webcam boxes stay open.

The secret check now runs through `ra-demo dashboard`'s real `_dashboard`/`_planner` path, offline with FakeSDK.

## Rendered labels

Both screenshots come from headless Chrome against the servers above:

- `dashboard-simulation-bad-action.png` shows the `SIMULATION` badge, a rollback, `planner scripted (demo planner, no LLM call)` and `$0`.
- `dashboard-replay.png` shows the `REPLAY` badge with source `Video replay`.

## Known limitation (REPLAY)

A file source is read as fast as it decodes, so the replay panel showed Capture FPS ≈ 13110 for the synthetic 15 fps clip. When the clip ends, the watchdog reports `stream_down` and the agent plans `restart_capture`. The deterministic demo for the video is therefore the SIMULATION mode (`SyntheticSource`). REPLAY proves the label and the read-only loop on a recorded file, not real-time playback.

Still open for F9: the five-user check, the no-secrets check on the final video, and the real-webcam (`--live --uri 0`) run on the owner's machine.
