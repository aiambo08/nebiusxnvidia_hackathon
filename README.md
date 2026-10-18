# Physical AI Reliability Agent

**An autonomous reliability layer for camera-based Physical AI.** It watches a camera, notices
when the perception pipeline stops being trustworthy, asks **NVIDIA Nemotron on Nebius Token
Factory** for a root-cause diagnosis and a plan, runs only **bounded, reversible** fixes through a
deterministic policy gate, and **keeps the change only if the downstream task measurably
recovers** — otherwise it rolls back and escalates to a human.

> Working name · Nebius x NVIDIA Global AI Hackathon 2026 · **Physical AI track** ·
> License: [Apache-2.0](LICENSE) · F5, F6 and F8 are the gates currently marked passed in
> [`docs/phases-and-gates.md`](docs/phases-and-gates.md). F3, F4, F7 and F9 remain open.
> F10 A1–A8 and 4 h SIMULATION soak evidence are merged on `main`. The soak report records
> 4.0 h, 23/24 faults detected, 0.25 false alarms/h, +7.2 MB RSS and $0; REAL HARDWARE
> validation remains pending, so F10 is in progress and the gate is not passed
> ([soak report](docs/evidence/f10/soak/soak.md)). F11 license-inventory and public-repo-audit boxes are ticked on `main`
> (`4b5b929`; 218 tracked files, 35 distributions), and an independent agent installed and ran
> it from the README alone ([transcript](docs/evidence/f11/readme-install.md)); the independent F11
> gate review is pending, so F11 is not yet marked passed ([audit](docs/evidence/f11/public-repo-audit.md);
> [licenses](docs/third-party-licenses.md)).
> F12 is documentation preparation only; its gate is not
> passed and owner/reviewer actions remain. Evidence is labelled SIMULATION or REAL HARDWARE.
> See [`docs/phases-and-gates.md`](docs/phases-and-gates.md).

## Why

A camera can be "online" and useless: defocused, covered, too dark, frozen on the last frame,
knocked out of position. Commercial camera-health tools already raise alerts for this. What is
missing for robots and edge AI is the **closed loop**:

```
detect → diagnose (Nemotron) → act safely → verify on the downstream task → commit or roll back
```

Verifying on the *task* matters: we measured that ArUco marker detection on our synthetic scene
fails at mild blur but succeeds again at stronger blur — image-quality metrics alone are not a
safe success criterion (consistent with Wischow et al., arXiv:2112.05456).

## How it works (MAPE-K)

```mermaid
flowchart LR
  CAM[Webcam / file / RTSP] --> CAP[Capture + watchdog]
  CAP --> PROBES[Probes: exposure, blur, freeze/loop,<br/>occlusion grid, FOV homography,<br/>ArUco downstream task]
  PROBES --> FUSE[Robust baseline + temporal fusion<br/>HEALTHY → SUSPECT → CONFIRMED]
  FUSE -- confirmed only --> NEM[NVIDIA Nemotron<br/>on Nebius Token Factory]
  NEM -- JSON plan --> GATE[Deterministic policy gate<br/>allowlist · bounds · cooldown]
  GATE --> EXE[Executor<br/>snapshot → apply]
  EXE --> VER[Verifier<br/>task + guards]
  VER -- improved --> OK[Commit]
  VER -- no / worse --> RB[Rollback → human]
  KB[(Hash-chained SQLite<br/>event log)] -.-> FUSE & NEM & GATE & EXE & VER
```

| Stage | Module | Authority |
|---|---|---|
| Monitor | `capture/`, `probes/`, `tasks/marker.py` | local, deterministic, works offline |
| Analyze | `baselines/robust.py`, `incidents/fusion.py`, `incidents/state_machine.py` | deterministic |
| Plan | `nemotron/` | **advisory only** — Nemotron proposes, never executes |
| Execute | `policy/gate.py`, `actions/executor.py` | allowlist, typed bounds, cooldown, rate limit |
| Verify | `verification/verifier.py` | commit/rollback rule |
| Knowledge | `storage/event_store.py` | append-only, tamper-evident |

Non-negotiables: detection works without the cloud · Nemotron is called only after a CONFIRMED
incident · the LLM never touches the device · every action has a snapshot, timeout and rollback ·
client-side budget caps · a Token Factory outage degrades to local rules + human escalation.

## How we use NVIDIA and Nebius

- **NVIDIA Nemotron 3** (open models) via **Nebius Token Factory**'s OpenAI-compatible API
  (`https://api.tokenfactory.nebius.com/v1/`) for causal diagnosis, action selection among the
  incident's allowed actions, verification design and a human-readable explanation.
- The deterministic policy gate offers only fault-relevant, device-supported actions plus safe
  escalation (ADR-009); Nemotron proposes but never executes. A circuit breaker opens on provider
  failures and falls back to local rules, keeping monitoring available during outages.
- Each call logs model, prompt version, input/output tokens, latency and estimated cost. The live
  F6 golden-set evaluation made 264 calls and cost about $0.031 ($0.03057240 in the report)
  ([report](docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md)).
  A local selector also scored 100% by action name on that test, so this is constrained action
  selection—not independent diagnosis ([baseline](docs/evidence/f6/golden-rules-baseline-test.md)).
- Tiers (ADR-002): a fast Nemotron (Nano / 3.5 Lightning) for every incident; Nemotron 3 Super
  only on ambiguity. Model IDs are **verified against `/v1/models`** (`scripts/list_models.py`),
  never trusted from docs.
- Structured output with `response_format: json_schema` where the action enum is restricted to
  the actions the policy gate offers for this device; automatic fallback to JSON mode.
- Token Factory accelerated the workflow by returning structured, auditable plans for evaluation;
  local diagnosis, gate, executor and verification remain authoritative. See
  [ADR-009](docs/adr/ADR-009-offer-only-fault-relevant-actions.md).

## Results

| Phase | Result | Evidence |
|---|---|---|
| F3 · REAL HARDWARE CPU, synthetic frames | Three 720p paced probe p95 runs on the owner's laptop were 23.2 / 32.6 / 34.5 ms under Windows Best performance. This is a CPU measurement using synthetic frames, not a live-camera latency result. | [`latency-hardware.md`](docs/evidence/f3/latency-hardware.md) |
| F3 · REAL HARDWARE camera inputs | Static-scene checks passed on the webcam at rest and two phone RTSP scenes. The walk-by test observed 22/22 trials with no `fov_shift` windows and detected its bump control; MJPEG was inconclusive. | [`static-scene-hardware.md`](docs/evidence/f3/static-scene-hardware.md), [`walkby-hardware.md`](docs/evidence/f3/walkby-hardware.md) |
| F5 · SIMULATION | Independent gate review passed 6/6 conditions; the associated hysteresis benchmark is SIMULATION evidence. | [`PROJECT_STATE.md`](docs/agents/PROJECT_STATE.md), [`hysteresis.md`](docs/evidence/f5/hysteresis.md) |
| F6 · REAL TOKEN FACTORY | Golden-v2 test: 264 calls, 100% schema validity, 98.864% action accuracy, and $0.03057240 run cost (about $0.031). The local selector also scored 100% by action name, so this is not evidence of independent diagnosis. | [test report](docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md), [rules baseline](docs/evidence/f6/golden-rules-baseline-test.md) |
| F7 · SIMULATION | A subprocess crash-recovery test verifies snapshot restoration and conservative rollback/escalation after restart; the real webcam adapter remains open. | [`test_crash_recovery.py`](tests/integration/test_crash_recovery.py), [`PROJECT_STATE.md`](docs/agents/PROJECT_STATE.md) |
| F8 · SIMULATION | Recovered 87/100 recoverable cases. Regression results were 45/50 raw; all 45/45 executed cases were contained. Five `dark:0.8` cases did not execute because no incident was confirmed. | [`recovery-bench.md`](docs/evidence/f8/recovery-bench.md) |
| F10 · SIMULATION | The merged A1–A8 report has 454 valid EventStores; A3 recovery was 25/25 (20/20 on the F8-comparable subset); A4 COMMITTED was 0/20 versus 0/20 in A3, so no difference was demonstrated. The 4 h SIMULATION soak is also merged; REAL HARDWARE validation remains pending, so F10 is in progress and not passed. | [`experiments.md`](docs/evidence/f10/experiments.md); [`soak.md`](docs/evidence/f10/soak/soak.md) |
| F10 soak | 4.0 h, 23/24 faults detected, 0.25 false alarms/h, +7.2 MB RSS, $0. SIMULATION evidence is merged; REAL HARDWARE validation remains pending, so the F10 gate is not passed. | [`soak.md`](docs/evidence/f10/soak/soak.md) |

These results do not claim that the submission video, five-user test, final tag or Devpost
submission exist. Each row identifies whether its evidence is SIMULATION, REAL HARDWARE, or a live
Token Factory evaluation; none should be read as evidence of a different mode.

## Quickstart

Use Python 3.11 or newer (`requires-python = ">=3.11"` in [`pyproject.toml`](pyproject.toml); CI runs 3.11 and 3.12). Works on Windows and Linux;
no GPU is needed for the MVP.

```bash
git clone https://github.com/aiambo08/nebiusxnvidia_hackathon.git
cd nebiusxnvidia_hackathon
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,api]"

pytest -q                              # 907 passed, 1 deselected, 2 xfailed at 190ce74 (count grows as tests are added); transcripts: docs/evidence/f11/readme-install.md, docs/evidence/f12/quickstart.md
ra-demo all                            # deterministic SIMULATION of every scenario
```

Start the read-only SIMULATION dashboard:

```bash
ra-demo dashboard --db runs/readme-simulation.sqlite
```

Expected startup output:

```text
Mode: SIMULATION
Planner: rules
Database: runs/readme-simulation.sqlite
Dashboard: http://127.0.0.1:8000
```

In another terminal, check that the page responds successfully, then stop the server with Ctrl+C:

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
```

Expected: `HTTP 200`. For a REAL HARDWARE webcam dashboard, run:

```bash
ra-demo dashboard --live --uri 0 --db runs/readme-webcam-check.sqlite
```

Expected: `Mode: REAL HARDWARE`, the selected database path, and the dashboard URL. The static page
is [`apps/dashboard/index.html`](apps/dashboard/index.html). No dashboard screenshots are committed,
so none is shown here.

Before rerunning a dashboard command, delete the database file named by `--db` or choose a new path.

Use Nemotron (spends a few cents of Token Factory credits):

```bash
cp .env.example .env                   # then set NEBIUS_API_KEY in .env (never commit it)
python scripts/list_models.py          # confirm NVIDIA model IDs available to your key
python scripts/spike_nemotron.py --n 20
ra-demo scenario dark --planner nemotron
```

Real camera (physical demo path):

```bash
ra-demo live --uri 0                   # REAL HARDWARE when URI 0 is a webcam
ra-demo dashboard --live --uri 0 --db runs/readme-webcam-live.sqlite  # read-only dashboard plus live webcam agent
uvicorn --factory apps.api.main:create_app --port 8000   # read-only incident API
```

Expected: the dashboard reports `Mode: REAL HARDWARE`, its database path, and its URL. Use an
available webcam; this command is not a hardware result by itself.

Without `NEBIUS_API_KEY` the agent starts in **local mode** (rule-based planner) and says so.

## Simulation scenarios

`ra-demo all` runs these on a seeded synthetic scene with a reference ArUco marker:

| Scenario | Expected loop |
|---|---|
| `dark` | blackout → raise exposure (bounded) → task recovers → **commit** |
| `defocus` | focus drift → autofocus → task recovers → **commit** |
| `freeze` | bit-exact repeated frames → restart capture → **commit** |
| `frozen_black` | decoder frozen on a black frame (reported as blackout) → restart capture → **commit** |
| `overexposure` | clipping → lower exposure → **commit** |
| `occlusion` | covered lens → maintenance **ticket** → waits for human → closes when clean |
| `bad_action` | a deliberately harmful plan → verification fails → **exact rollback** → human |

These are labelled SIMULATION everywhere. The hackathon video uses the real webcam.

## Repository map

```
src/reliability_agent/   capture · probes · tasks · baselines · incidents · nemotron
                         policy · actions · verification · storage · orchestrator · cli
apps/api/                read-only FastAPI over the event log (dashboard backend)
benchmarks/              seeded fault injectors, run manifests, degraded-clip builder
scripts/                 spikes/benchmarks: list_models, spike_nemotron, spike_capture, spike_static_scene, spike_walkby, bench_probes, bench_static_scene
configs/default.yaml     every threshold, cap and model ID (no secrets)
docs/                    phase gates, compliance matrix, ADRs, safety, evaluation, budget
docs/es/                 full technical execution report (Spanish)
AGENTS.md                operating manual for the multi-agent coding team
```

## Budget: zero extra spend

Only Token Factory inference is paid, from the hackathon credits. Client-side soft, demo and hard
caps, per-incident call limits, caching and the no-video-upload policy are documented in
[`docs/budget.md`](docs/budget.md).

## Out of scope (frozen at F0)

Free-form robot control or dangerous actuators · automatic physical lens cleaning · training a
foundation model · managing thousands of cameras · replacing an NVR (Frigate, Shinobi, Agent DVR)
· continuous video to Token Factory · irreversible changes decided by the LLM.

## Known limitations (honest status)

- F4 REAL HARDWARE recall/precision and varied-session benchmarking remain pending
  ([evaluation protocol](docs/evaluation.md)); the F3 camera checks do not close the F4 benchmark.
- Real UVC/ONVIF exposure/focus control is not implemented yet:
  `OpenCVSource.capabilities()` returns only `restart`, so on a real webcam the gate offers only
  restart, safe mode, cleaning/human tickets. Bounded exposure/focus commit/rollback is
  demonstrated in SIMULATION only ([source](src/reliability_agent/capture/sources.py),
  [open task](docs/agents/TASKS.md)).
- The F6 action score is not an independent-diagnosis measure: the local selector also scores
  100% by action name ([F6 report](docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md),
  [baseline](docs/evidence/f6/golden-rules-baseline-test.md)).
- The merged F10 report records a 0-vs-0 COMMITTED result for the full-loop and no-downstream-metric
  arms; it does not demonstrate a difference. The report is SIMULATION evidence only
  ([experiments](docs/evidence/f10/experiments.md)). The 4 h SIMULATION soak is also merged, but
  REAL HARDWARE validation remains pending; F10 is in progress and not passed
  ([soak](docs/evidence/f10/soak/soak.md)).
- The frozen check examines only the confirming window, so window alignment can miss freeze onset
  around a dark frame. Frozen overexposure/focus-drift may be classified as those faults instead of
  blackout and can receive one exposure/autofocus action before snapshot-backed rollback and human
  escalation; checking recent windows remains open work
  ([ADR-003](docs/adr/ADR-003-freeze-needs-a-measurable-scene.md),
  [project state](docs/agents/PROJECT_STATE.md)).
- The F10 SIMULATION soak is merged, but REAL HARDWARE validation remains pending. Do not
  interpret simulation evidence as REAL HARDWARE.

## Documentation

[Phase gates](docs/phases-and-gates.md) · [Compliance matrix](docs/compliance-matrix.md) ·
[ADR-001](docs/adr/ADR-001-architecture.md) · [ADR-002](docs/adr/ADR-002-model-selection.md) ·
[Safety model](docs/safety-model.md) · [Evaluation](docs/evaluation.md) ·
[Budget](docs/budget.md) · [Research](docs/research.md) · [Feedback log](docs/feedback.md) ·
[Demo script](docs/demo-script.md) · [Devpost draft](docs/devpost.md) ·
[Owner's submission steps (ES)](docs/es/pasos-del-propietario.md) ·
[Informe técnico (ES)](docs/es/informe-tecnico-ejecucion.md)

## Hackathon notes

Created during the submission period (first commit: October 2026); not a pre-existing project.
Built with AI coding assistants under the human author's direction; design decisions are
recorded in `docs/agents/DECISIONS.md` and `docs/adr/`.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
