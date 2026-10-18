# F11 — independent install and run from README only

- **Gate box:** F11 "A different agent installs and runs from README only".
- **Who:** an independent Devin session that did not author the code and was told to use only `README.md` (no other docs, CI files or source to work out the install): https://app.devin.ai/sessions/ce3f6fdb150a45c591119f0b839c33e8
- **When / what:** 2026-10-18, fresh `git clone` checked out at `190ce74` (merge of PR #60).
- **Environment:** Ubuntu 22.04.5 LTS, x86_64, Python 3.11.13 in a fresh venv. `NEBIUS_API_KEY` was not set (local mode), so $0 was spent.
- **Mode:** SIMULATION only. No live Nemotron call and no webcam. Those paths stay owner steps in [`docs/es/pasos-del-propietario.md`](../../es/pasos-del-propietario.md).

| Command (verbatim from README) | Exit | Key output |
|---|---|---|
| `git clone https://github.com/aiambo08/nebiusxnvidia_hackathon` + `git checkout 190ce74` | 0 | HEAD at `190ce74` |
| `python -m venv .venv` + `source .venv/bin/activate` | 0 | — |
| `pip install -e ".[dev,api]"` | 0 | `Successfully installed ... reliability-agent-0.1.0` |
| `pytest -q` | 0 | `907 passed, 1 deselected, 2 xfailed in 669.62s` |
| `ra-demo all` | 0 | All 7 scenarios match the README table. `dark`, `defocus`, `freeze`, `frozen_black` and `overexposure` end `committed` → `RECOVERED->HEALTHY`. `occlusion` ends `request_manual_cleaning` → `ACTING->NEEDS_HUMAN`. `bad_action` ends `rolled_back` → `ROLLED_BACK->NEEDS_HUMAN`. |
| `ra-demo dashboard --db runs/readme-simulation.sqlite` | (server) | `Mode: SIMULATION` / `Planner: rules` / `Database: runs/readme-simulation.sqlite` / `Dashboard: http://127.0.0.1:8000`, exactly as documented |
| `curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/` | 0 | `HTTP 200` |

**Verdict reported by the session:** `VERDICT: PASS`. Every command worked as written on the first try, and no step had to be guessed.

**Mismatches it reported:** both are fixed in the README in the same PR as this record.
1. The README expected `854 passed`; the clone at `190ce74` gives `907 passed` because tests were added after the F12 transcript.
2. The README did not state a Python version; you had to open `pyproject.toml` (`requires-python = ">=3.11"`) to find it.

This record ticks one F11 box. The independent F11 gate review later passed on `d16436f` ([phases and gates](../../phases-and-gates.md)).
