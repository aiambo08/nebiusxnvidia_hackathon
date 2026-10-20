# Fresh-clone quickstart transcript

Re-run on 2026-10-20 from a fresh clone in `f12-fresh/repo` at
`bc6ea442970bf241039c87f8a7be2a7e06c5065f` (origin/main after merging PR #72), Python
3.13.16 on Windows. The clone destination and `python -m venv` command are
environment-specific; the steps mirror the README quickstart exactly.

```text
$ git rev-parse HEAD
bc6ea442970bf241039c87f8a7be2a7e06c5065f

$ python --version
Python 3.13.16

$ python -m venv .venv
exit code: 0

$ .venv\Scripts\python.exe -m pip install -e ".[dev,api]"
Editable install completed successfully.
exit code: 0

$ .venv\Scripts\python.exe -m pytest -q
........................................................................ [ 83%]
........................................................................ [ 90%]
........................................................................ [ 98%]
..................                                                       [100%]
952 passed, 1 deselected, 2 xfailed in 1083.29s (0:18:03)
exit code: 0

$ .venv\Scripts\python.exe -m reliability_agent.cli all
=== SIMULATION scenario: dark ===
plan[rules]: blackout -> set_exposure_bounded {'delta_ev': 2.0} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->RECOVERED | RECOVERED->HEALTHY
final: HEALTHY

=== SIMULATION scenario: defocus ===
plan[rules]: focus_drift -> trigger_autofocus {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->RECOVERED | RECOVERED->HEALTHY
final: HEALTHY

=== SIMULATION scenario: freeze ===
plan[rules]: freeze -> restart_capture {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->RECOVERED | RECOVERED->HEALTHY
final: HEALTHY

=== SIMULATION scenario: occlusion ===
plan[rules]: lens_occlusion -> request_manual_cleaning {} | model=local-rules tokens=0/0 cost=$0.00000
verification: n/a
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->NEEDS_HUMAN | NEEDS_HUMAN->HEALTHY
final: HEALTHY

=== SIMULATION scenario: overexposure ===
plan[rules]: overexposure -> set_exposure_bounded {'delta_ev': -1.5} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->RECOVERED | RECOVERED->HEALTHY
final: HEALTHY

=== SIMULATION scenario: bad_action ===
plan[scripted]: blackout -> set_exposure_bounded {'delta_ev': -1.5} | model=scripted tokens=0/0 cost=$0.00000
verification: ['rolled_back']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->ROLLING_BACK | ROLLING_BACK->ROLLED_BACK | ROLLED_BACK->NEEDS_HUMAN | NEEDS_HUMAN->HEALTHY
final: HEALTHY

=== SIMULATION scenario: frozen_black ===
plan[rules]: blackout -> restart_capture {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->RECOVERED | RECOVERED->HEALTHY
final: HEALTHY
exit code: 0

$ .venv\Scripts\python.exe -m reliability_agent.cli dashboard --help
usage: ra-demo dashboard [-h] [--live |
                         --scenario {dark,defocus,freeze,occlusion,overexposure,bad_action,frozen_black}]
                         [--uri URI] [--planner {rules,nemotron}]
                         [--pace PACE] [--loop] [--gap GAP] [--host HOST]
                         [--port PORT] [--db DB] [--append]
exit code: 0

$ .venv\Scripts\python.exe -m reliability_agent.cli dashboard --live --uri 0 --help
(help shown as above; no webcam was opened by --help)
exit code: 0
```

The default dashboard started in SIMULATION mode:

```text
$ .venv\Scripts\python.exe -m reliability_agent.cli dashboard --db runs\readme-simulation.sqlite
Mode: SIMULATION
Planner: rules
Database: runs\readme-simulation.sqlite
Dashboard: http://127.0.0.1:8000
INFO:     Started server process [42600]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:64413 - "GET / HTTP/1.1" 200 OK

$ curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
HTTP 200
exit code: 0

server stopped after the check
```

All commands used no live Token Factory calls and no hardware input.

## Synthetic-file CLI smoke test

SIMULATION only; verifies that the recorder can open a generated file and write a local clip.
It is not a webcam test or REAL HARDWARE evidence.

```text
# Input: locally generated synthetic 160x120 MJPG AVI with 1200 frames; not a camera recording.
$ .venv\Scripts\python.exe scripts/record_clip.py --uri benchmarks\data\f12-synthetic-dry-run.avi --seconds 0.000001 --warmup 0.01 --session f12-synthetic-dry-run-mini
{
  "session": "f12-synthetic-dry-run-mini",
  "path": "benchmarks/data/f12-synthetic-dry-run-mini_clean.avi",
  "sha256": "4bf1bb733d3ee3d2133e1c6feaf59c190578ad9b8417deb0e3b2d06782421e0e",
  "frames": 1,
  "fps": 1712.04,
  "header_fps": 7746.93,
  "resolution": [160, 120],
  "seconds": 0.0,
  "read_misses": 0,
  "uri_kind": "file"
}
warning: recorded at 1712.04 FPS, warm-up measured 7746.93 FPS
exit code: 0
```

No `--split` was passed, so no session was added to `sessions.yaml`; the generated clip was
not used for detector metrics.
