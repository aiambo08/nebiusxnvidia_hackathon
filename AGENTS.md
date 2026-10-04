# AGENTS.md — operating manual for coding agents

Any coding agent (Devin, Copilot, Claude Code, Codex, …) working on this repository must read this
file, `docs/phases-and-gates.md` and `docs/agents/PROJECT_STATE.md` before changing code.
Task playbooks live in `.agents/skills/` (see its README); load the matching one before a task.

## Language
- Code, comments, docs, UI, commit messages: **English**.
- Talking to the human owner (Aibo): Spanish.

## Hard rules
1. Never commit secrets. Keys only in `.env` (git-ignored). Never print keys in logs.
2. Never simulate human-only steps: API key creation, YouTube upload, Devpost submission.
3. Never hard-code Nemotron model IDs or prices in logic — they live in `configs/` and are
   verified with `scripts/list_models.py`.
4. The LLM never executes anything. Every action passes `policy/gate.py`, has a snapshot, a
   timeout and a rollback.
5. Never weaken a gate threshold to make a test pass. Changing a threshold requires an ADR and a
   benchmark report.
6. A phase gate is passed only with evidence produced by CI or a benchmark — never self-declared.
7. Zero extra spend: no paid services, no dedicated endpoints, respect budget caps.
8. Do not vendor third-party code without adding it to `docs/third-party-licenses.md`.

## Roles and ownership

| Role | Owns (may modify) | Must not modify |
|---|---|---|
| Architecture | `src/reliability_agent/contracts/`, `incidents/state_machine.py`, `docs/adr/` | probe implementations |
| Ingestion | `capture/` | prompts |
| Vision | `probes/`, `tasks/` | executor, actions |
| Evaluation | `benchmarks/`, `tests/e2e/`, `docs/evaluation.md` | production thresholds without evidence |
| Nebius | `nemotron/` | actions |
| Safety | `policy/`, `actions/`, `verification/`, `tests/adversarial/` | UI |
| Product | `apps/`, `README.md`, `docs/demo-script.md` | critical logic |
| Integrator | CI, release, merges | new features after freeze (day 25) |

Vetoes: Safety vetoes any new tool/action; Evaluation vetoes any change that lowers a metric;
Integrator vetoes unreviewed or untested code.

## Workflow
1. Architecture freezes contracts first (`contracts/models.py`). Contract changes need an ADR.
2. One branch per agent/module: `feat/<role>-<topic>`.
3. Every PR: tests, the phase gate it advances (`Gate: F3`), and the PR template filled.
4. Evaluation runs the benchmark independently of the author.
5. Update `docs/agents/PROJECT_STATE.md` and `docs/agents/TASKS.md` at the end of each session.
6. Record non-trivial decisions in `docs/agents/DECISIONS.md` (short) or an ADR (structural).

## Handoff format
```
HANDOFF from <role> to <role>
Gate: F<n>
Done: <bullets with file paths>
Evidence: <test names / report paths>
Open risks: <bullets>
Next step: <one concrete action>
```

## Commands
```bash
pip install -e ".[dev,api]"
pytest                       # unit + integration + adversarial (no network)
pytest -m live               # live Token Factory tests (needs NEBIUS_API_KEY, costs credits)
ruff check .
python scripts/demo_offline.py   # deterministic end-to-end loop, no network
```
