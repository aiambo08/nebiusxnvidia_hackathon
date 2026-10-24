# Independent review record — F9 (product & demo) + F12 (submission)

Checklist executed: `docs/review-checklist-f9-f12.md` (Parts A, B, C, D), as found in the clone.

- Reviewer: independent Cursor review agent (no authorship of this repo)
- Date: 2026-10-24
- Environment: Windows 10.0.26300 (PowerShell 5.1); Python 3.13.9 (venv created from
  `C:\Users\niaib\anaconda3\python.exe`); fresh clone at `C:\Users\niaib\ra-review` (outside OneDrive)
- Revision under review: **`9d026d1c42809f93572b9fa1061f72cf742ea5ba`** (`main`,
  "Merge pull request #78 from aiambo08/fix/evaluation-sim-task-latency"). The checklist was written
  for `768cd4b`; count differences are recorded and judged on intent, not on the literal number.
- Network/keys: `NEBIUS_API_KEY` was never set (checked: `NEBIUS_API_KEY set? False`, no `.env`
  in the clone). No Token Factory call was made. The only network calls were the `git clone`, the
  pip install, and read-only unauthenticated GitHub API requests (repository visibility and CI
  check runs).
- Project code was not modified. `git status --porcelain` in the clone was empty at the end
  (`runs/` and `.venv/` are git-ignored).

---

## Setup transcript

```text
PS> git clone https://github.com/aiambo08/nebiusxnvidia_hackathon.git C:\Users\niaib\ra-review
Cloning into 'C:\Users\niaib\ra-review'...
PS> git rev-parse HEAD
9d026d1c42809f93572b9fa1061f72cf742ea5ba
PS> git log --oneline -3
9d026d1 Merge pull request #78 from aiambo08/fix/evaluation-sim-task-latency
47fd021 fix(sim): time the marker task with the simulated clock
1144ab6 Merge pull request #77 from aiambo08/copilot/fix-windows-tests-job-failure

PS> C:\Users\niaib\anaconda3\python.exe -m venv .venv
PS> .venv\Scripts\python.exe --version
Python 3.13.9
PS> .venv\Scripts\python.exe -m pip install -q -e ".[dev,api]"
[notice] A new release of pip is available: 25.2 -> 26.2.2      (only output; exit 0)
PS> .venv\Scripts\python.exe -m pip check
No broken requirements found.
```

---

## Part A — F12 happy path (transcript)

### A1. Full test suite

```text
PS> .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
........................................................................ [ 52%]
......................................................xx................ [ 67%]
...
...................                                                      [100%]
953 passed, 1 deselected, 2 xfailed in 1014.50s (0:16:54)
EXIT 0
```

(`-p no:cacheprovider` only disables the `.pytest_cache` write; it does not change test selection.)
No `FAILED`/`ERROR` lines in the full log. Checklist expected 952 passed at `768cd4b`; one more
test exists at `9d026d1`. The single deselected test is the network test, excluded by
`addopts = "-m 'not live'"` (`pyproject.toml:49`):

```text
PS> .venv\Scripts\python.exe -m pytest --collect-only -q -m live
tests/integration/test_live_token_factory.py::test_live_nemotron_plan_is_valid
1/956 tests collected (955 deselected) in 0.66s
```

### A2. `cli all`

```text
PS> .venv\Scripts\python.exe -m reliability_agent.cli all
=== SIMULATION scenario: dark ===
plan[rules]: blackout -> set_exposure_bounded {'delta_ev': 2.0} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
final: HEALTHY
=== SIMULATION scenario: defocus ===
plan[rules]: focus_drift -> trigger_autofocus {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
final: HEALTHY
=== SIMULATION scenario: freeze ===
plan[rules]: freeze -> restart_capture {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
final: HEALTHY
=== SIMULATION scenario: occlusion ===
plan[rules]: lens_occlusion -> request_manual_cleaning {} | model=local-rules tokens=0/0 cost=$0.00000
verification: n/a
transitions: ... | ACTING->NEEDS_HUMAN | NEEDS_HUMAN->HEALTHY
final: HEALTHY
=== SIMULATION scenario: overexposure ===
plan[rules]: overexposure -> set_exposure_bounded {'delta_ev': -1.5} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
final: HEALTHY
=== SIMULATION scenario: bad_action ===
plan[scripted]: blackout -> set_exposure_bounded {'delta_ev': -1.5} | model=scripted tokens=0/0 cost=$0.00000
verification: ['rolled_back']
transitions: HEALTHY->SUSPECT | SUSPECT->CONFIRMED | CONFIRMED->DIAGNOSING | DIAGNOSING->PLANNED | PLANNED->ACTING | ACTING->VERIFYING | VERIFYING->ROLLING_BACK | ROLLING_BACK->ROLLED_BACK | ROLLED_BACK->NEEDS_HUMAN | NEEDS_HUMAN->HEALTHY
final: HEALTHY
=== SIMULATION scenario: frozen_black ===
plan[rules]: blackout -> restart_capture {} | model=local-rules tokens=0/0 cost=$0.00000
verification: ['committed']
final: HEALTHY
EXIT 0
```

I also ran the README alias `.venv\Scripts\ra-demo.exe all` twice, without `PYTHONIOENCODING`.
I got the same 7/7 `final: HEALTHY`, and `Compare-Object` against the first run reported
`diff lines: 0`, so the SIMULATION output is byte-identical between runs.

### A3. Dashboard smoke (default SIMULATION, port 8000)

```text
PS> .venv\Scripts\python.exe -m reliability_agent.cli dashboard --db runs\review-quickstart.sqlite
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
Mode: SIMULATION
Planner: rules
Database: runs\review-quickstart.sqlite
Dashboard: http://127.0.0.1:8000
INFO:     127.0.0.1:50235 - "GET / HTTP/1.1" 200 OK

PS> curl.exe -sS -o NUL -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
HTTP 200
PS> Invoke-RestMethod http://127.0.0.1:8000/api/status   (excerpt)
{"mode":"SIMULATION","source_label":"SyntheticSource","scenario":"dark",...,
 "planner":{"kind":"rules","model":null,"prompt_version":null,"tier":"fast","api_key_present":false},
 "budget":{"spent_usd_estimate":0.0,...,"hard_cap_usd":27,...}}
```

Server stopped afterwards (process 30596 killed; port 8000 confirmed free).

---

## Part B — F9 product evidence audit (transcript)

### B1. Main flow ≤ 90 s, no manual interaction

```text
PS> .venv\Scripts\python.exe -m reliability_agent.cli dashboard --scenario bad_action --planner rules --db runs\review-bad.sqlite
Mode: SIMULATION
Planner: rules
Database: runs\review-bad.sqlite
Dashboard: http://127.0.0.1:8000
```

I launched it once and did nothing else. I polled `/api/status` and `/api/incidents` every
250 ms (read-only GETs) and logged each state change:

```text
0.1s state=HEALTHY planner_source=scripted model= incidents=0
13.6s state=SUSPECT planner_source=scripted model=
15.7s state=VERIFYING planner_source=scripted model=
19.1s state=NEEDS_HUMAN planner_source=scripted model=
28.9s state=HEALTHY planner_source=scripted model=
CLOSED seen at 28.9s
```

Event-store timestamps (`runs/review-bad.sqlite`). The launch time is the creation time of the
redirected log file:

```text
launch (log file created)        2026-10-24T13:00:26.580Z
('2026-10-24T13:00:47.699542+00:00', 'incident', 'bb0ade45')
('2026-10-24T13:01:00.856723+00:00', 'closed',   'bb0ade45')
=> launch -> closed = 34.3 s   (author's doc: 34.274 s)
```

Incident events (from `/api/incidents`) include `"status": "rolled_back"`,
`ROLLING_BACK -> ROLLED_BACK`, `ROLLED_BACK -> NEEDS_HUMAN` with reason
`"automatic action did not help; escalated"`, and `"kind": "closed"`.

I also viewed the rendered page in a browser while the server ran. The header showed the
`SIMULATION` badge, `source SyntheticSource`, `scenario bad_action`,
`planner scripted (demo planner, no LLM call)`, `model –`, `prompt –`,
`Token Factory spend $0.0000 / $27 cap` and `event chain verified`. The incident loop showed
`2 · Diagnose — scripted (demo planner, no LLM call)`, `Policy gate APPROVED`,
`Act ... snapshot restored`, and `5 · Verify` with **`ROLLED BACK (snapshot restored)`**
(task.success_rate 0.000 -> 0.000).

The API is GET-only:

```text
PS> Select-String -Path apps\api\main.py -Pattern "@app\.(get|post|put|delete|patch|websocket|api_route)|add_api_route|@router"
55:@app.get("/")
60:@app.get("/health")
64:@app.get("/incidents")
78:@app.get("/incidents/{incident_id}")
85:@app.get("/budget")
89:@app.get("/api/status")
118:@app.get("/api/windows")
122:@app.get("/api/frame.jpg")
133:@app.get("/api/incidents")
```

I read the full file (150 lines): there is no middleware, no mount, and no write path. All
handlers read from the `EventStore`/`LiveFeed`.

```text
PS> .venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_f9.py::test_scenarios_run_confirm_to_verify_without_input -q
.......                                                                  [100%]
7 passed in 14.95s
```

### B2. Header reset across the scenario switch

```text
PS> .venv\Scripts\python.exe -m reliability_agent.cli dashboard --scenario bad_action --scenario dark --planner rules --pace 1.0 --gap 1 --db runs\review-tour.sqlite
```

I ran the exact checklist loop (60 × 500 ms), then continued polling until there were 70 more
`dark` samples. Results grouped by value, in time order:

```text
--- exact checklist loop (60 x 500ms) ---
25x {"scenario":"bad_action","planner_source":"scripted","scenario_started_at":"2026-10-24T13:02:10.473070+00:00","model":null,"state":"HEALTHY"}
 4x {... "bad_action","planner_source":"scripted", ... "state":"SUSPECT"}
 6x {... "bad_action","planner_source":"scripted", ... "state":"VERIFYING"}
19x {... "bad_action","planner_source":"scripted", ... "state":"NEEDS_HUMAN"}
 6x {"scenario":"dark","planner_source":null,"scenario_started_at":"2026-10-24T13:02:48.594972+00:00","model":null,"state":"HEALTHY"}
--- extended loop ---
29x {"scenario":"dark","planner_source":null, ... "state":"HEALTHY"}
 4x {"scenario":"dark","planner_source":null, ... "state":"SUSPECT"}
 7x {"scenario":"dark","planner_source":"rules", ... "state":"VERIFYING"}
30x {"scenario":"dark","planner_source":"rules", ... "state":"HEALTHY"}

first dark sample index: 55 of 130
scripted after first dark: 0
non-null model samples: 0
last bad_action sample : {"scenario":"bad_action","planner_source":"scripted",...,"state":"HEALTHY"}
first dark sample      : {"scenario":"dark","planner_source":null,...,"state":"HEALTHY"}
```

Event-store timestamps (`runs/review-tour.sqlite`): bad_action incident closed at
`13:02:43.301`; dark scenario started at `13:02:48.595`; dark incident opened at `13:03:08.400`
and closed at `13:03:11.678` (23.1 s after the dark scenario started).

```text
PS> .venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_api.py::test_dashboard_header_planner_resets_across_scenario_switch -q
.                                                                        [100%]
1 passed in 24.35s
```

### B3. SIMULATION / REPLAY labels

```text
PS> .venv\Scripts\python.exe -c "import cv2, numpy as np; w=cv2.VideoWriter('runs/review-clip.mp4', ...); ...; w.release()"
review-clip.mp4 106881 bytes
PS> .venv\Scripts\python.exe -m reliability_agent.cli dashboard --live --uri runs/review-clip.mp4 --planner rules --db runs\review-replay.sqlite --port 8001
WARNING:reliability_agent.runtime:NEBIUS_API_KEY not set: running in LOCAL MODE (rule-based planner)
Mode: REPLAY
Planner: rules
Database: runs\review-replay.sqlite
Dashboard: http://127.0.0.1:8001
PS> curl.exe -sS -o NUL -w "HTTP %{http_code}\n" http://127.0.0.1:8001/
HTTP 200
PS> Invoke-RestMethod http://127.0.0.1:8001/api/status
mode           : REPLAY
source_label   : Video replay
planner        : {"kind":"rules","model":null,"prompt_version":null,"tier":"fast","api_key_present":false}
```

The rendered page (browser) showed the `REPLAY` badge, `source Video replay`, `scenario –`,
`planner rules (local planner, no LLM call)`, `model –`, `prompt –`, `event chain verified`,
and Capture FPS 6874.5 (decode speed, consistent with the documented REPLAY limitation).

```text
PS> .venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_api.py::test_mode_label -q
......                                                                   [100%]
6 passed in 0.62s
```

Committed screenshots, both last changed in `2ac15fa` (2026-10-20). I opened them with an
image viewer:

- `docs/evidence/f9/dashboard-simulation-bad-action.png`: `SIMULATION` badge,
  `source SyntheticSource`, `scenario bad_action`,
  `planner scripted (demo planner, no LLM call)`, `model –`, `prompt –`,
  `Token Factory spend $0.0000 / $27 cap`, `event chain verified`. The incident loop shows
  `Diagnose — scripted (demo planner, no LLM call)`, gate `APPROVED`, act snapshot `restored`,
  and verify **`ROLLED BACK (snapshot restored)`** with the before/after table. **Matches the
  claim.**
- `docs/evidence/f9/dashboard-replay.png`: `REPLAY` badge, `source Video replay`,
  `scenario –`, `planner rules (local planner, no LLM call)`, `model –`, `prompt –`,
  `event chain verified`, camera tile `SUSPECT` + `REPLAY`, Capture FPS **9291.6**. **Matches
  the claim**, except for the FPS figure quoted in the evidence doc (see comment 3 below).

### B4. Deterministic demo with a recorded source (REPLAY part)

I left the first REPLAY server (port 8001) running about 37 s. Incidents, newest first:

```text
afef7113 faults=stream_down        state=VERIFYING  plan=restart_capture  states=DIAGNOSING>PLANNED>ACTING>VERIFYING
e1d259a4 faults=focus_drift        state=HEALTHY    plan=needs_human      states=DIAGNOSING>NEEDS_HUMAN>HEALTHY
b4613ba1 faults=freeze,focus_drift state=HEALTHY    plan=restart_capture  states=...>VERIFYING>ROLLING_BACK>ROLLED_BACK>NEEDS_HUMAN>HEALTHY
```

Second run, same clip, fresh DB, port 8002 (`--db runs\review-replay2.sqlite --port 8002`,
about 52 s). Incidents, oldest first:

```text
e09267c2 faults=freeze,focus_drift plan=restart_capture states=...>VERIFYING>ROLLING_BACK>ROLLED_BACK>NEEDS_HUMAN>HEALTHY
f52943e5 faults=freeze,focus_drift plan=restart_capture states=DIAGNOSING>PLANNED>ACTING>VERIFYING
```

Same input file, different incident sequences: run 1 had a `focus_drift` escalation and a
`stream_down` within about 37 s; run 2 had neither in about 52 s. REPLAY reads the file at
decode speed (6874–9292 FPS observed), so the loop's timing, and therefore its incident
sequence, is not reproducible. By contrast, the SIMULATION mode was byte-identical across runs
(Part A2).

All three dashboard servers (ports 8000, 8001, 8002) were stopped, and the port check confirmed
no listener was left.

---

## Part C — Honesty, secrets and compliance (transcript)

### C1. README spend and media captions

- `README.md:40`: "Provenance, commands and the $0.0008336 Token Factory spend for these
  captures are in `docs/media/README.md`."
- `README.md:28`: "*SIMULATION, real speed (1×), downscaled to 800×500.*"
- `docs/media/README.md:16`: "$0.0008336 in total ($0.00071 for the first six, plus $0.0001236
  for the recaptured `dark` scenario)". The parts add up: 0.00071 + 0.0001236 = 0.0008336.
- Captions in the provenance table say "real speed (1×), downscaled to 800×500" for both GIFs.

```text
PS> git grep -n "0\.00071"
Binary file docs/evidence/f10/soak/soak.sqlite matches
docs/media/README.md:16: ... $0.0008336 in total ($0.00071 for the first six, plus $0.0001236 ...
docs/review-checklist-f9-f12.md:155: ...
tests/unit/test_readme_media.py:95:    assert "$0.00071" not in readme
PS> git grep -n -I -E "(2×|2x speed|\b2x\b|double speed)" -- "*.md"
(only probe-downscale / benchmark-ratio mentions in ADR-005, DECISIONS, PROJECT_STATE, TASKS, f3/README; no media caption)
```

Media file check (Pillow from the base interpreter, read-only):

```text
docs/media/dashboard-nemotron-defocus.gif (800, 500) frames 40 durations_ms [500] total_s 20.0
docs/media/dashboard-bad_action.gif       (800, 500) frames 38 durations_ms [500] total_s 19.0
```

500 ms per frame matches the documented 0.5 s capture interval, so playback is 1×.

### C2. Repo hygiene

```text
PS> .venv\Scripts\python.exe scripts/audit_repo.py --repo . --report runs\review-audit.md
Scanned 245 tracked files; 0 unallowlisted findings; 5 historical paths with findings; 0 history blobs skipped above 5 MB.
EXIT 0
(report header: "**Result: PASS**")
PS> .venv\Scripts\python.exe scripts/license_report.py --check
Licence report check passed for 35 distributions.
EXIT 0
PS> .venv\Scripts\python.exe -m pytest tests/unit/test_audit_repo.py tests/unit/test_license_report.py tests/unit/test_readme_media.py -q
...............................................                          [100%]
47 passed in 40.63s
PS> (git ls-files).Count
245
```

Checklist expected 244 tracked files at `768cd4b`; 245 at `9d026d1`. CI also runs
`gitleaks (full history)` (`.github/workflows/ci.yml:50-53`). The GitHub check runs for
`9d026d1` at review time were: `secret scan completed success`,
`tests (ubuntu-latest, py3.11) success`, `tests (ubuntu-latest, py3.12) success`, and both
`tests (windows-latest, …)` jobs still `in_progress`.

### C3. Claimed-limits honesty

```text
src/reliability_agent/capture/sources.py:57   class OpenCVSource(CameraSource):
src/reliability_agent/capture/sources.py:159      def capabilities(self) -> SourceCapabilities:
                                                     # Real capability discovery per device is a Phase-7 task (UVC/ONVIF adapters).
                                                     return SourceCapabilities(restartable=True)
```

- REAL HARDWARE exposure/focus: `git grep` for "real hardware" within 120 characters of
  exposure/focus/autofocus across README, devpost, compliance matrix, demo script, gates,
  TASKS, PROJECT_STATE, `docs/evidence/f9` and `docs/evidence/f12` returned **no matches**.
  The README (`README.md:242-246`) and devpost (`docs/devpost.md:78-81`) explicitly say
  bounded exposure/focus commit/rollback is SIMULATION only. Compliance matrix R7
  (`docs/compliance-matrix.md:19`) says "no real exposure/focus commit is claimed".
- Stream-down → restart via the live dashboard: `docs/demo-script.md:65-68` explicitly excludes
  it ("do not exercise the combined outage through the live dashboard loop"), and
  `docs/agents/TASKS.md:99` says "No stream-down/restart segment is claimed". No claim found.
- Footage: `README.md:41` says "No REAL HARDWARE footage is shown yet." ✔

### C4. Runtime call visible

- `README.md:24-31` "See it (SIMULATION)" embeds `docs/media/dashboard-nemotron-defocus.gif`
  and its caption describes the live Nemotron call on Nebius Token Factory.
- `docs/media/README.md:10` names the model `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`,
  1284 in / 198 out tokens, $0.00012, 1574 ms, and the command
  `ra-demo dashboard --planner nemotron --scenario defocus --pace 1.0`.
- I extracted the last GIF frame (40 frames total). It shows the `SIMULATION` badge,
  `planner nemotron`, `model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `prompt diagnose_v2`,
  `Token Factory spend $0.0001 / $27 cap`, and
  `2 · Diagnose — NVIDIA Nemotron on Nebius Token Factory`, source `nemotron ● live runtime call`,
  tokens `1284 in / 198 out`, cost `$0.00012`, latency `1574 ms`, proposes `trigger_autofocus`,
  gate `APPROVED`, verify **`COMMITTED`** (task.success_rate 0.000 -> 1.000). This matches the
  provenance exactly.
- Code path present: `src/reliability_agent/nemotron/{client.py, planner.py, budget.py, prompts/}`.
- Limitation: I could not re-verify the $ figures against the capture databases (they are
  git-ignored). I verified only internal consistency between README, provenance and the
  rendered frame.

---

## Part D — Owner / hardware boxes (state check only)

```text
docs/phases-and-gates.md:154  - [ ] 5 technical users who did not build it can answer ...
docs/phases-and-gates.md:159  - [ ] No secrets on screen, logs or video
docs/phases-and-gates.md:160  - [ ] Deterministic demo mode with a recorded source + real webcam mode
docs/phases-and-gates.md:196-203 F12: all seven boxes "- [ ]" (fresh reviewer, video, runtime call in video, incognito, tag, compliance matrix, submitted)
docs/phases-and-gates.md:26   | F10 | End-to-end validation | 4 | Evaluation | in progress |
docs/phases-and-gates.md:28   | F12 | Submission | 4 | Product + human | not started |
docs/agents/TASKS.md:100-106  - [ ] fresh reviewer / F4 REAL HARDWARE / five-user test / public video / tag / incognito / Devpost submit
docs/agents/TASKS.md:113      - [ ] [F10][evaluation] Complete REAL HARDWARE validation ... F10 remains in progress and is not passed
README.md:20-21               "F12 is documentation preparation only; its gate is not passed and owner/reviewer actions remain."
README.md:121-122             "These results do not claim that the submission video, five-user test, final tag or Devpost submission exist."
docs/compliance-matrix.md:38  "Video, tag, incognito checks and submission remain human-only until completed by the owner."
docs/devpost.md:107           "- Video: `<YouTube URL — added by the owner>`"
docs/devpost.md:76-78         "What's next: ... validate F10 on REAL HARDWARE ..., record the public demo, conduct the five-user test, verify links and submit"
PS> git tag -l
(no tags — v1.0-submission does not exist)
```

`docs/es/pasos-del-propietario.md` has §4 "Prueba con cinco usuarios" (line 119) and §8
"Comprobación en incógnito" (line 200), as referenced. None of the six Part D items is claimed
as done anywhere I checked.

---

## Result

| Gate box | Verdict (PASS/FAIL) | Evidence (file / line / transcript snippet) |
|---|---|---|
| F12 fresh reviewer reproduces the happy path | **PASS** | Fresh clone at `9d026d1`, README install. `953 passed, 1 deselected, 2 xfailed in 1014.50s` (exit 0; the deselected test is `test_live_token_factory.py`, live-only). `cli all` 7/7 `final: HEALTHY`, `model=local-rules`/`model=scripted`, `cost=$0.00000`; `bad_action` shows `['rolled_back']` and `ROLLED_BACK->NEEDS_HUMAN`. Dashboard banner `Mode: SIMULATION` / `Planner: rules`, `HTTP 200`. |
| F9 main flow ≤ 90 s SIMULATION | **PASS** | `bad_action` launch→`closed` 34.3 s from event-store timestamps (13:00:26.58 → 13:01:00.86 UTC); in the tour, `dark` closed 23.1 s after scenario start. Only these two scenarios were timed by me; the other five rely on `demo-flow.md` (20.9–27.2 s) plus `cli all` completing. |
| F9 no manual interaction confirm→verify | **PASS** | No input after launch; incident reached ROLLED_BACK→NEEDS_HUMAN→closed. `apps/api/main.py` has only `@app.get` routes (lines 55–133). `test_scenarios_run_confirm_to_verify_without_input`: `7 passed`. |
| F9 SIMULATION/REPLAY labels correct | **PASS** | Live SIMULATION page: badge SIMULATION, `planner scripted (demo planner, no LLM call)`, `model –`, `prompt –`. Live REPLAY page (my own clip, port 8001): badge REPLAY, `source Video replay`, `planner rules (local planner, no LLM call)`, `model –`, `prompt –`; API `mode: REPLAY`. `test_mode_label`: `6 passed`. Both committed PNGs match. Minor doc FPS mismatch (comment 3). |
| F9 header reset across scenario switch (B1) | **PASS** | `scripted` (bad_action) → `null` on the first dark sample (500 ms resolution) → `rules` once dark planned. 0 `scripted` samples after the switch over 76 dark samples; 0 non-null `model` samples out of 130. Test `test_dashboard_header_planner_resets_across_scenario_switch`: `1 passed`. |
| F9 REPLAY deterministic recorded-source mode | **FAIL** | The REPLAY label and read-only loop work on a recorded file, but the run is **not deterministic**: two runs on the same clip gave different incident sequences (run 1: freeze → focus_drift `needs_human` → `stream_down`; run 2: freeze twice, no `stream_down`), and capture runs at decode speed (6874–9292 FPS). The checklist's statement "The REPLAY run above is the deterministic recorded-source mode" (`docs/review-checklist-f9-f12.md:142`) contradicts the repo's own `docs/evidence/f9/demo-flow.md:93-98` ("The deterministic demo for the video is therefore the SIMULATION mode"). The corresponding gate box (`phases-and-gates.md:160`) is correctly still unchecked, so this is not an overclaim in the gate doc. SIMULATION is deterministic (byte-identical `ra-demo all` across two runs). |
| C1 README spend/captions current | **PASS** | `README.md:40` $0.0008336 = `docs/media/README.md:16`; captions say 1× and 800×500, and the GIFs measure 800×500 with 500 ms frames. `0.00071` appears only as the correct sub-total for the first six calls (`docs/media/README.md:16`), not as a stale total. No `2×` caption. |
| C2 audit + licenses + secret tests | **PASS** | `Scanned 245 tracked files; 0 unallowlisted findings` (report: `Result: PASS`); `Licence report check passed for 35 distributions.`; 3 test files: `47 passed`. CI `secret scan` success on `9d026d1`. |
| C3 claimed-limits honesty | **PASS** | `sources.py:159-161` returns `SourceCapabilities(restartable=True)` only. No REAL HARDWARE exposure/focus claim found by grep. SIMULATION-only stated at `README.md:242-246`, `devpost.md:78-81`, `compliance-matrix.md:19`. Stream-down excluded at `demo-script.md:65-68` and `TASKS.md:99`. `README.md:41` "No REAL HARDWARE footage is shown yet." |
| C4 runtime call visible | **PASS** | `README.md:24-31` embeds the GIF. `docs/media/README.md:10` names model/tokens/cost/latency/command. The GIF's last frame shows `nemotron ● live runtime call`, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, 1284/198 tokens, $0.00012, 1574 ms, COMMITTED. Code in `src/reliability_agent/nemotron/`. Dollar figures not re-derivable (capture DBs git-ignored). |
| D boxes remain open, not overclaimed | **PASS** | All six items are unchecked in `phases-and-gates.md` (154, 159–160, 196–203) and `TASKS.md` (100–106, 113). No `v1.0-submission` tag. README 20–21 and 121–122, `compliance-matrix.md:38`, and `devpost.md:76-78, 107` disclaim them. Wording nit at `README.md:210` (comment 6). |

**Overall verdict: ☒ FAIL ☐ PASS** for the checklist as a whole, because one box (REPLAY
deterministic recorded-source mode) fails as written.

Scope of that FAIL: the F12 box "A fresh reviewer reproduces the happy path" **PASSES**, and
every F9 box that is currently ticked in `docs/phases-and-gates.md` (≤ 90 s, no manual
interaction, labels) **PASSES** on `9d026d1`. The failing item belongs to the F9 box
`phases-and-gates.md:160`, which the repo correctly leaves unchecked. Its REPLAY half cannot be
called "deterministic" with the current file source unless the claim is reworded or REPLAY is
paced and made reproducible.

---

## Blockers / comments

```
BLOCKER (checklist claim, B4)
1. docs/review-checklist-f9-f12.md:142 says "The REPLAY run above is the deterministic
   recorded-source mode." That is false as observed: two REPLAY runs of the same
   runs/review-clip.mp4 produced different incident sequences:
     run 1 (8001, ~37 s): b4613ba1 freeze,focus_drift -> rolled back; e1d259a4 focus_drift ->
                          needs_human; afef7113 stream_down -> restart_capture
     run 2 (8002, ~52 s): e09267c2 freeze,focus_drift -> rolled back; f52943e5
                          freeze,focus_drift -> restart_capture (no stream_down)
   It also contradicts docs/evidence/f9/demo-flow.md:93-98. Fix either the claim (state that
   SIMULATION is the deterministic recorded/seeded mode and REPLAY only proves the label and the
   read-only loop), or make REPLAY paced to the file's FPS and reproducible. The gate box
   phases-and-gates.md:160 must stay unchecked until this and the real-webcam half are resolved.

NON-BLOCKING (stale or inconsistent documentation)
2. docs/compliance-matrix.md:21 (R9) says the repository is "currently **private**
   (`private: true`, verified 2026-10-21)". The unauthenticated GitHub API now returns
   private=False, visibility=public, and an unauthenticated `git ls-remote` succeeds. R9 is
   stale (an under-claim). Update it; the incognito check (phases-and-gates.md:200) is still
   owner-only.
3. docs/evidence/f9/demo-flow.md:94 says the REPLAY panel showed "Capture FPS ≈ 13110", but
   the committed screenshot docs/evidence/f9/dashboard-replay.png shows 9291.6, and my run
   showed 6874.5. The figure depends on decode speed; quote it as machine-dependent or match
   it to the screenshot.
4. docs/evidence/f9/demo-flow.md:102-103 and docs/agents/TASKS.md:97 say "49 tests" for the
   audit/license/secret checks. The three test files named in the checklist C2 give 47 passed
   at 9d026d1. Either the doc counted a different set of files (ambiguous; not stated) or the
   count is stale.
5. docs/compliance-matrix.md:28 (R16) quotes "refreshed audit on 768cd4b: 244 tracked files";
   9d026d1 has 245 with 0 unallowlisted findings. README.md:137 quotes "952 passed ... at
   bc6ea44"; 9d026d1 gives 953. Both are labelled with their revision, so they are acceptable,
   but they will drift.
6. README.md:210 says "The hackathon video uses the real webcam." in the present tense, while
   no video exists yet (README.md:121-122 and devpost.md:107 say so). Suggest "will use".

CHECKLIST USABILITY
7. B2's polling loop (60 x 500 ms, about 30-40 s of wall time with Invoke-RestMethod overhead)
   barely covers the switch: in my run the first `dark` sample was #55 of 60. On a slower
   machine, or if polling starts a few seconds late, the reviewer would never see the switch.
   Suggest 1..150, and starting the loop immediately after launch.
8. B1 asks the reviewer to watch the page for ~90 s without giving a timing method. The
   event-store `incident`/`closed` timestamps plus the launch time are a reproducible way to
   measure it (used above).

OBSERVATIONS (not failures)
9. On the flat synthetic REPLAY clip the agent raises freeze/focus_drift incidents and plans
   restart_capture, which is rolled back and escalated. That is reasonable for a textureless,
   slowly changing clip, and the stream_down at end-of-file is documented in demo-flow.md:95-97.
10. apps/api/main.py:48 compares event `ts` and `scenario_started_at` as ISO strings
    (`event["ts"] >= started`). This is correct only while both stay in the same UTC
    "+00:00" format, which they do today (observed). Worth a comment or a parsed comparison.
11. CI for 9d026d1 at review time: secret scan, ubuntu py3.11 and ubuntu py3.12 succeeded; both
    Windows jobs were still in_progress. My local Windows/py3.13 run passed in full.
12. The C4 dollar figures ($0.0008336, $0.00012) could not be independently recomputed: the
    capture databases are git-ignored. Only internal consistency was verified.
```
