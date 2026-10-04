# Compliance matrix

Official sources (re-read before submitting — they can change):
- Rules: <https://nebiusglobalaihackathon.devpost.com/rules>
- Judging: <https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works>

Deadline: **30 Oct 2026, 10:00 PDT = 18:00 Europe/Madrid (CET)**. Internal target: submit on 29 Oct.
Judging: viability pass/fail, then 1–5 on four equally weighted criteria — technological
implementation, design, potential impact, quality of the idea.

| ID | Requirement | How we satisfy it | Evidence | Status |
|---|---|---|---|---|
| R1 | Runs on Nebius Token Factory or AI Cloud (runtime call) | `NemotronPlanner` calls Token Factory `/v1/chat/completions` at runtime for every confirmed incident | `src/reliability_agent/nemotron/client.py`, `runs/spikes/nemotron.jsonl`, video 1:05–1:30 | pending live call |
| R2 | Uses ≥ 1 NVIDIA open model | Nemotron 3 (Nano / Super) via Token Factory; IDs discovered from `/v1/models` | `scripts/list_models.py` output, decision log `model` field | pending |
| R3 | Fits one track | Physical AI track: camera sensing + acting on a real perception pipeline | Devpost form | planned |
| R4 | Project description (what, why, how) | README sections + Devpost text | README | draft |
| R5 | Working demo URL | **Not required** for Physical AI; optional recorded deterministic demo | — | n/a |
| R6 | Demo video ≤ 3 min, public YouTube | Script in `docs/demo-script.md` | YouTube link | human-only |
| R7 | Physical AI: ≥ 1 min of hardware / physical input operating | Real webcam: cover lens, kill lights, defocus, move camera | video 0:20–2:20 | planned |
| R8 | Show how Token Factory + Nemotron were used | Dashboard panel with model id, tokens, cost; video segment | video, dashboard | planned |
| R9 | Public repo (GitHub) | This repository | URL | done |
| R10 | Open source license visible at top of repo | Apache-2.0 `LICENSE` at root (GitHub "About" detects it) | repo page | done |
| R11 | README with setup + clear run instructions | README "Quickstart" | README | draft |
| R12 | Highlight NVIDIA models, Token Factory acceleration, other Nebius tools | README "How we use NVIDIA & Nebius" | README | draft |
| R13 | Feedback on Token Factory / AI Cloud / NVIDIA tools | `docs/feedback.md`, filled during development | file | ongoing |
| R14 | Pre-existing project explanation | Not applicable: repository created during the submission period (first commit Oct 2026) | git history | done |
| R15 | No copyrighted music in video | Silence or royalty-free/CC0 audio only | video | human-only |
| R16 | Third-party code/data used under their licenses, new functionality created | `docs/third-party-licenses.md`; no vendored code | file | ongoing |
| R17 | Demo/test access free until end of judging | Repo + local run, no paid service required | README | planned |
| R18 | Human-only steps: API keys, YouTube upload, Devpost submission | Done by Aibo (owner/Representative); agents never simulate them | — | human-only |
| R19 | Verifiable authorship | Real commit history, ADRs, `docs/agents/DECISIONS.md` | git log | ongoing |
| R20 | Zero additional spend beyond the 30 USD Token Factory credits | Client-side budget guard with soft/demo/hard caps | `docs/budget.md`, tests | done (code) |
| R21 | Optional Tavily bonus requires functional runtime Tavily call | **Not pursued** unless it adds real value (out of scope) | — | n/a |

Rule of this file: a row may only be marked `done` when the Evidence column points to something a
judge can open.
