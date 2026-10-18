# Compliance matrix

Official sources (re-read before submitting — they can change):
- Rules: <https://nebiusglobalaihackathon.devpost.com/rules>
- Judging: <https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works>

Deadline: **30 Oct 2026, 10:00 PDT = 18:00 Europe/Madrid (CET)**. Internal target: submit on 29 Oct.
Judging: viability pass/fail, then 1–5 on four equally weighted criteria — technological
implementation, design, potential impact, quality of the idea.

| ID | Requirement | How we satisfy it | Evidence | Status |
|---|---|---|---|---|
| R1 | Runtime call on Nebius Token Factory or AI Cloud | Token Factory was called for the F6 golden-set evaluation; provider responses and usage metadata are in the report. | [`client.py`](../src/reliability_agent/nemotron/client.py); [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md) | evidenced; video still human-only |
| R2 | NVIDIA open model | Nemotron via Token Factory. | [Model inventory](evidence/f0/models-2026-10-05.json); [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md) | evidenced |
| R3 | One track | Select Physical AI in the Devpost form. | [Devpost draft](devpost.md) | human-only submission |
| R4 | Project description | README and Devpost draft describe what, why and how. | [`README.md`](../README.md); [`docs/devpost.md`](devpost.md) | prepared |
| R5 | Demo URL | Not required for Physical AI. | [Official rules](https://nebiusglobalaihackathon.devpost.com/rules) | n/a |
| R6 | Short public YouTube video | Script is prepared; no video or URL is claimed. | [`docs/demo-script.md`](demo-script.md) | human-only |
| R7 | Physical input operating in video | Owner records at least one minute of real webcam footage and a visible, safe lens-cover input. The incident plan may offer only restart, safe mode, cleaning/human tickets; no real exposure/focus commit is claimed. | [`docs/demo-script.md`](demo-script.md); [static-scene results](evidence/f3/static-scene-hardware.md); [walk-by results](evidence/f3/walkby-hardware.md) | human-only |
| R8 | Show Token Factory and Nemotron use | The recording must show a live Nemotron call and keep the SIMULATION/REAL HARDWARE badge visible; local rules are only the declared offline fallback. | [`apps/dashboard/index.html`](../apps/dashboard/index.html); [`docs/demo-script.md`](demo-script.md) | prepared; video human-only |
| R9 | Public repository | This repository is public. | [GitHub repository](https://github.com/aiambo08/nebiusxnvidia_hackathon) | done |
| R10 | Visible open-source license | Apache-2.0 is at repository root. | [`LICENSE`](../LICENSE) | done |
| R11 | README setup and run steps | The committed quickstart transcript is author-generated. A fresh-clone PR review also reproduced the commands, but that review transcript is not committed as judge-open evidence. | [`README.md`](../README.md); [quickstart transcript](evidence/f12/quickstart.md) | prepared; committed independent evidence pending |
| R12 | NVIDIA models and Token Factory use | README documents constrained structured calls, policy gate, fallback, per-call usage logging and observed F6 result. | [`README.md`](../README.md); [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md) | prepared |
| R13 | Feedback on Token Factory, AI Cloud and NVIDIA | Feedback is based on recorded development evidence; AI Cloud was not used. | [`docs/feedback.md`](feedback.md); [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md) | prepared; owner must enter in form |
| R14 | Explain whether project pre-existed | Decision log records the project origin during the submission period; repository history is available to judges. | [`docs/agents/DECISIONS.md`](agents/DECISIONS.md); [GitHub commits](https://github.com/aiambo08/nebiusxnvidia_hackathon/commits/main) | evidenced |
| R15 | No copyrighted music | Owner uses silence or cleared audio. | [`docs/demo-script.md`](demo-script.md) | human-only |
| R16 | Third-party code/data licensing | F11 license inventory and public-repository audit are **pending review** in PR #59; do not claim the evidence is complete until it is merged. | [PR #59](https://github.com/aiambo08/nebiusxnvidia_hackathon/pull/59) (pending review) | pending review |
| R17 | Free demo/test access | Local mode needs no paid service; live provider calls may spend credits. | [`README.md`](../README.md); [`docs/budget.md`](budget.md) | prepared |
| R18 | API key, upload and submission steps | Owner guide lists the human-only actions; agents do not perform them. | [`docs/es/pasos-del-propietario.md`](es/pasos-del-propietario.md) | human-only |
| R19 | Verifiable authorship | Decisions, ADRs and public commit history are available. | [`docs/agents/DECISIONS.md`](agents/DECISIONS.md); [GitHub commits](https://github.com/aiambo08/nebiusxnvidia_hackathon/commits/main) | evidenced |
| R20 | Stay within hackathon credit budget | Client-side caps and budget behavior are documented and tested. | [`docs/budget.md`](budget.md); [`test_planner_budget.py`](../tests/unit/test_planner_budget.py) | evidenced in code |
| R21 | Optional Tavily runtime bonus | Not pursued. | — | n/a |
| R22 | Materials in English | English submission materials are prepared; Spanish owner instructions are operational support. | [`README.md`](../README.md); [`docs/devpost.md`](devpost.md); [`docs/demo-script.md`](demo-script.md); [`docs/feedback.md`](feedback.md) | prepared; owner review pending |
| R23 | Feedback field | Drafted from observed development evidence; AI Cloud remains not used. | [`docs/feedback.md`](feedback.md) | prepared; owner submission pending |

Rule of this file: mark a row `done` only when its Evidence points to something a judge can open.
Video, tag, incognito checks and submission remain human-only until completed by the owner.
