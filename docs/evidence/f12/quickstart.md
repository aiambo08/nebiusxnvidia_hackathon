# Fresh-clone quickstart transcript

The workflow below was run from a fresh clone in `/home/ubuntu/f12-fresh` at
`34390e7a624325ea2e251fc4f58ee1532b7f6894` (Python 3.11.13). The environment-specific clone
destination was used instead of the README's generic default directory name.

```text
$ python -m venv .venv
exit code: 0

$ source .venv/bin/activate
$ python --version
Python 3.11.13
exit code: 0

$ pip install -e ".[dev,api]"
Editable install completed successfully.
exit code: 0

$ nice -n 19 pytest -q
........................................................................ [  8%]
........................................................................ [ 16%]
........................................................................ [ 25%]
........................................................................ [ 33%]
........................................................................ [ 42%]
........................................................................ [ 50%]
........................................................................ [ 58%]
...............................................................xx....... [ 67%]
........................................................................ [ 75%]
........................................................................ [ 84%]
........................................................................ [ 92%]
................................................................         [100%]
854 passed, 1 deselected, 2 xfailed in 694.66s (0:11:34)
exit code: 0

$ nice -n 19 ra-demo all
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

$ ra-demo dashboard --help
Relevant help flags: --scenario, --live, --uri
exit code: 0

$ ra-demo dashboard --live --uri 0 --help
exit code: 0
```

The output is summarized to the relevant flags and exit codes. The `--help` invocations only
inspected argument parsing; no webcam was opened.

The default dashboard started in SIMULATION mode:

```text
$ ra-demo dashboard
Mode: SIMULATION
Dashboard: http://127.0.0.1:8000

$ curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8000/
HTTP 200
exit code: 0

Ctrl+C; clean server shutdown
exit code: 0
```

The commands used no live Token Factory calls and no hardware input.

## Synthetic-file F4 CLI smoke test

SIMULATION only; this verifies that the recorder can open a generated file and write a local clip.
It is not an F4 benchmark, a webcam test, or REAL HARDWARE evidence.

```text
# Input: locally generated synthetic 160x120 MJPG AVI with 1200 frames; not a camera recording.
$ python scripts/record_clip.py --uri /tmp/f12-synthetic-dry-run.avi --seconds 0.000001 --warmup 0.01 --session f12-synthetic-dry-run-mini
Relevant output fields:
{
  "session": "f12-synthetic-dry-run-mini",
  "path": "benchmarks/data/f12-synthetic-dry-run-mini_clean.avi",
  "sha256": "10d27e4432994373b4c259e3097498cc1bab55c289976bf23ab177d0837624a6",
  "frames": 1,
  "seconds": 0.0,
  "uri_kind": "file"
}
exit code: 0
```

No `--split` was passed, no session was added to `sessions.yaml`, and the generated file was not
used for detector metrics.
