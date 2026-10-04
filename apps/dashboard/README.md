# Dashboard (Phase 9)

Planned screens (report F9): live camera + task state, essential metrics, state timeline,
Nemotron diagnosis + evidence, proposed action + policy decision, before/after comparison,
commit/rollback status, tokens and cost. Must label SIMULATION vs REAL HARDWARE.

Data source: the read-only API in `apps/api` (`/incidents`, `/incidents/{id}`, `/budget`).
Stack decision pending (Streamlit for speed vs. small React app) — record it in an ADR.
