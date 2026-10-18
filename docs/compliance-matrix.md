# Compliance matrix

Official sources (re-read before submitting — they can change):
- Rules: <https://nebiusglobalaihackathon.devpost.com/rules>
- Judging: <https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works>

Deadline: **30 Oct 2026, 10:00 PDT = 18:00 Europe/Madrid (CET)**. Internal target: submit on 29 Oct.
Judging: viability pass/fail, then 1–5 on four equally weighted criteria — technological
implementation, design, potential impact, quality of the idea.

| ID | Requirement | How we satisfy it | Evidence | Status |
|---|---|---|---|---|
| R1 | Runtime call on Nebius Token Factory or AI Cloud | Token Factory client is called for confirmed incidents; logs include the provider result. | `src/reliability_agent/nemotron/client.py`; `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.json` | evidenced; video still human-only |
| R2 | NVIDIA open model | Nemotron via Token Factory. | `docs/evidence/f0/models-2026-10-05.json`; F6 test report | evidenced |
| R3 | One track | Select Physical AI in the Devpost form. | `docs/devpost.md` | human-only submission |
| R4 | Project description | README and Devpost draft describe what, why and how. | `README.md`; `docs/devpost.md` | prepared |
| R5 | Demo URL | Not required for Physical AI. | Official rules link above | n/a |
| R6 | Short public YouTube video | Script is prepared; no video or URL is claimed. | `docs/demo-script.md` | human-only |
| R7 | Physical input operating in video | Owner records real webcam footage. | `docs/demo-script.md`; F3 hardware evidence | human-only |
| R8 | Show Token Factory and Nemotron use | Dashboard panels and required video shots are specified. | `apps/dashboard/index.html`; `docs/demo-script.md` | prepared; video human-only |
| R9 | Public repository | This repository is public. | Repository URL | done |
| R10 | Visible open-source license | Apache-2.0 is at repository root. | `LICENSE` | done |
| R11 | README setup and run steps | Fresh-clone workflow and test count are recorded. | `README.md`; `docs/evidence/f12/quickstart.md` | author-verified; independent reviewer pending |
| R12 | NVIDIA models and Token Factory use | README documents structured calls, constraints, fallback and observed acceleration. | `README.md`; F6 report | prepared |
| R13 | Feedback on Token Factory, AI Cloud and NVIDIA | Recorded Token Factory and NVIDIA observations; AI Cloud was not used. | `docs/feedback.md` | prepared; owner must enter in form |
| R14 | Explain whether project pre-existed | Created during the submission period. | `docs/agents/DECISIONS.md`; git history | evidenced |
| R15 | No copyrighted music | Owner uses silence or cleared audio. | `docs/demo-script.md` | human-only |
| R16 | Third-party code/data licensing | F11 license inventory is in PR #59 and is not yet integrated on `main`. | PR #59; `docs/third-party-licenses.md` | pending review |
| R17 | Free demo/test access | Local mode needs no paid service; live provider calls may spend credits. | `README.md`; `docs/budget.md` | prepared |
| R18 | API key, upload and submission steps | Owner guide lists the human-only actions; agents do not perform them. | `docs/es/pasos-del-propietario.md` | human-only |
| R19 | Verifiable authorship | Decisions, ADRs and commit history are available. | `docs/agents/DECISIONS.md`; git history | evidenced |
| R20 | Stay within hackathon credit budget | Client-side caps and tests limit inference. | `docs/budget.md`; budget tests | evidenced in code |
| R21 | Optional Tavily runtime bonus | Not pursued. | — | n/a |
| R22 | Materials in English | English submission materials are prepared; Spanish owner instructions are operational support. | `README.md`; `docs/devpost.md`; `docs/demo-script.md` | prepared; owner review pending |
| R23 | Feedback field | Drafted from observed development evidence; AI Cloud remains not used. | `docs/feedback.md` | prepared; owner submission pending |

Rule of this file: mark a row `done` only when its Evidence points to something a judge can open.
Video, tag, incognito checks and submission remain human-only until completed by the owner.
