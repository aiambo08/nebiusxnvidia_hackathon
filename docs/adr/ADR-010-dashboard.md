# ADR-010 — In-process read-only dashboard

- Status: accepted
- Date: 2026-10-18
- Gate: F9

## Context

The demo needs a live view of agent state and recent evidence without giving browser requests a
path to initiate actions or scenarios. It should run offline without a frontend toolchain.

## Decision

Serve one static HTML page with vanilla JavaScript from FastAPI. Keep the API read-only; the
in-process agent loop owns scenario and live execution in a daemon thread, while uvicorn serves
the dashboard in the main thread. Do not add a build step or CDN dependency.

## Consequences

- The dashboard works without network access beyond the running agent's selected camera source.
- The shared event store and live feed are injected into the API process.
- HTTP endpoints expose status, telemetry, frames, incidents, and budget only; they never trigger
  actions or scenarios.
- The static dashboard page is implemented in `apps/dashboard/index.html`.
