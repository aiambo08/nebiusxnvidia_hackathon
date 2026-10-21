# Independent reviewer checklist — F9 (product & demo) + F12 (submission)

Revision under review: `main` at **`768cd4b`** (2026-10-20/21, includes PRs #72/#73/#74).

- Reviewer: __________
- Date: __________
- Environment (OS / Python): __________

**Rules (judge-open evidence):** you must be someone who did **not** build this project.
Run every command yourself and paste the real output into your transcript. Do **not** copy
numbers from the evidence docs into your transcript — reproduce them. Fill the result table at
the end with PASS / FAIL per box and hand the filled file back to the owner so it can be
committed as judge-open evidence.

Setup (from the README quickstart only):

```powershell
git clone https://github.com/aiambo08/nebiusxnvidia_hackathon.git
cd nebiusxnvidia_hackathon
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,api]"    # Linux/macOS: source .venv/bin/activate
```

All commands below use `python -m reliability_agent.cli …`; the README alias is `ra-demo …`.

---

## Part A — F12 happy path (gate: “A fresh reviewer reproduces the happy path”)

Run and paste the output:

```powershell
.venv\Scripts\python.exe -m pytest -q
```
Expected: **952 passed, 1 deselected, 2 xfailed** (takes ~18 min).

```powershell
.venv\Scripts\python.exe -m reliability_agent.cli all
```
Expected: all 7 scenarios (`dark`, `defocus`, `freeze`, `occlusion`, `overexposure`,
`bad_action`, `frozen_black`), each `final: HEALTHY`, `model=local-rules` / `model=scripted`,
`cost=$0.00000`. `bad_action` must show `verification: ['rolled_back']` and the
`ROLLED_BACK → NEEDS_HUMAN` transition.

Dashboard smoke (default SIMULATION):

```powershell
.venv\Scripts\python.exe -m reliability_agent.cli dashboard --db runs\review-quickstart.sqlite
# second terminal:
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
```
Expected: startup banner `Mode: SIMULATION`, `Planner: rules`, and **HTTP 200**. Stop the server
afterwards (Ctrl+C).

Paste the transcript of Part A here (or in your own file):

```
…
```

---

## Part B — F9 product evidence audit

### B1. Main flow ≤ 90 s, no manual interaction (gate box)

1. Read `docs/evidence/f9/demo-flow.md` (the SIMULATION runs table). The documented wall times
   at `bc6ea44` are 20.9–34.3 s per scenario (occlusion measured at its `NEEDS_HUMAN` event).
2. Reproduce one full scenario yourself, without touching the keyboard after startup:

```powershell
.venv\Scripts\python.exe -m reliability_agent.cli dashboard --scenario bad_action --planner rules --db runs\review-bad.sqlite
```

   Watch `http://127.0.0.1:8000/`. Expected: badge **SIMULATION**, header
   `planner scripted (demo planner, no LLM call)`, `model –`, `prompt –` (no Nemotron
   advertised for a scripted planner), the incident loop reaching **ROLLED BACK
   (snapshot restored)**, and the incident closing. No keyboard input between confirmation and
   verification.
3. Confirm the API is GET-only (no endpoint mutates state):

```powershell
Select-String -Path apps\api\main.py -Pattern "@app\.(get|post|put|delete)"
```

4. Run the committed no-manual-interaction test:

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_f9.py::test_scenarios_run_confirm_to_verify_without_input -q
```

### B2. Header reset across scenario switch (PR #72 reviewer point B1)

This reproduces the original bug: chaining scenarios kept the previous scenario’s planner in the
header for ~15 s.

```powershell
.venv\Scripts\python.exe -m reliability_agent.cli dashboard --scenario bad_action --scenario dark --planner rules --pace 1.0 --gap 1 --db runs\review-tour.sqlite
```

While it runs, poll the read-only status endpoint (PowerShell):

```powershell
1..60 | ForEach-Object { Start-Sleep -Milliseconds 500; (Invoke-RestMethod http://127.0.0.1:8000/api/status) | Select-Object scenario, planner_source, scenario_started_at | ConvertTo-Json -Compress }
```

Expected: the `planner_source` flips from `scripted` (bad_action) to `None` (dark, before any
plan) within a second of the switch, then becomes `rules` once dark’s rule plan exists, and
**never returns to `scripted`**. `planner.model` stays `None` throughout.

Then run the committed behavioural test:

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_api.py::test_dashboard_header_planner_resets_across_scenario_switch -q
```

### B3. SIMULATION / REPLAY labels (gate box “UI clearly labels simulation vs real hardware”)

1. Generate a deterministic clip and start the REPLAY dashboard (do **not** reuse any file from
   the repo — this clip is yours):

```powershell
.venv\Scripts\python.exe -c "import cv2, numpy as np; w=cv2.VideoWriter('runs/review-clip.mp4', cv2.VideoWriter_fourcc(*'mp4v'), 15, (320,240)); [w.write(np.full((240,320,3),(i%255,60,30),np.uint8)) for i in range(300)]; w.release()"
.venv\Scripts\python.exe -m reliability_agent.cli dashboard --live --uri runs/review-clip.mp4 --planner rules --db runs\review-replay.sqlite --port 8001
```

   Expected: badge **REPLAY**, source `Video replay`, `planner rules (local planner, no LLM call)`,
   `model –`, `prompt –`.
2. Run the mode-label unit test:

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_dashboard_api.py::test_mode_label -q
```

3. Open `docs/evidence/f9/dashboard-simulation-bad-action.png` and
   `docs/evidence/f9/dashboard-replay.png`. They must show the fixed header (`planner scripted…`,
   `model –`, `prompt –`) and the SIMULATION / REPLAY badges. The evidence doc states the chips
   were cross-checked against the rendered DOM; you may re-verify with
   `chrome --headless=new --dump-dom`.

### B4. Deterministic demo with a recorded source (gate box, REPLAY part)

The REPLAY run above is the deterministic recorded-source mode. The REAL webcam half of this box
is an owner/hardware task (Part D) and is **not** covered by this review.

---

## Part C — Honesty, secrets and compliance

### C1. README spend and media captions are current

- `README.md` line ~40 states the Token Factory spend for the captures is **$0.0008336**; the
  GIF caption says **1×** (real speed), **800×500**.
- Cross-check the provenance in `docs/media/README.md` matches that figure and those captions.
  FAIL if you find a stale `0.00071` or a `2×` caption.

### C2. Repo hygiene

```powershell
.venv\Scripts\python.exe scripts/audit_repo.py --repo . --report runs\review-audit.md
.venv\Scripts\python.exe scripts/license_report.py --check
.venv\Scripts\python.exe -m pytest tests/unit/test_audit_repo.py tests/unit/test_license_report.py tests/unit/test_readme_media.py -q
```

Expected: audit **244 tracked files, 0 unallowlisted findings**; license **35 distributions**;
tests pass.

### C3. Claimed-limits honesty

These must **not** be claimed anywhere in the README/docs as REAL HARDWARE results — confirm the
docs explicitly say the opposite:

- UVC/ONVIF exposure/focus control (`OpenCVSource.capabilities()` exposes only `restart`) — no
  REAL HARDWARE exposure/focus commit or rollback may be claimed; bounded exposure/focus
  commit/rollback is SIMULATION only.
- Stream-down → restart through the live dashboard (no combined test covers that path — no claim).
- REAL HARDWARE footage — the README must say “No REAL HARDWARE footage is shown yet”.

### C4. Runtime call visible

The live Nemotron runtime call must be visible in media/code: `README.md` “See it (SIMULATION)”
shows a live Nemotron call on Nebius Token Factory (`dashboard-nemotron-defocus.gif`), and
`docs/media/README.md` documents the model, cost and timing. The code path is
`src/reliability_agent/nemotron/` + the Token Factory client. Confirm the media provenance names
the model and the call.

---

## Part D — Boxes outside this review (owner / hardware)

These gates are **not** reviewable by you (they need the owner, real hardware or a public
submission). Confirm only that they remain **open** in `docs/phases-and-gates.md` / TASKS and are
**not overclaimed**:

- [ ] Five-user product test (protocol + form: `docs/es/pasos-del-propietario.md` §4)
- [ ] REAL HARDWARE webcam run + public demo video (≥ 1 min physical input, total < 3 min;
      runtime call visible in the video; no secrets on screen)
- [ ] Final commit tagged (`v1.0-submission`) and matching the demo
- [ ] Incognito / public-links check (§8 of the owner steps)
- [ ] Devpost submission with operational margin (target 2026-10-29)
- [ ] F10 REAL HARDWARE validation (F10 gate stays unpassed until then)

---

## Result

| Gate box | Verdict (PASS/FAIL) | Evidence (file / line / transcript snippet) |
|---|---|---|
| F12 fresh reviewer reproduces the happy path | | |
| F9 main flow ≤ 90 s SIMULATION | | |
| F9 no manual interaction confirm→verify | | |
| F9 SIMULATION/REPLAY labels correct | | |
| F9 header reset across scenario switch (B1) | | |
| F9 REPLAY deterministic recorded-source mode | | |
| C1 README spend/captions current | | |
| C2 audit + licenses + secret tests | | |
| C3 claimed-limits honesty | | |
| C4 runtime call visible | | |
| D boxes remain open, not overclaimed | | |

Overall verdict: □ PASS □ FAIL

Blockers / comments (list concrete failures, with file/line or pasted output):

```
…
```
