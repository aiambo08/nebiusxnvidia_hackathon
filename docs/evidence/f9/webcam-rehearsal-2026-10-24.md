# Webcam dashboard rehearsal — 2026-10-24

**REAL HARDWARE** — owner's integrated webcam, physical lens cover by hand. Local rule-based
planner, no Token Factory call ($0.0000). This is a rehearsal, not the demo video; no image is
committed because the frame shows the owner.

- Code: fresh clone of `main` at `9d026d1`, Windows, Python 3.13.9 venv.
- Command: `ra-demo dashboard --live --uri 0 --planner rules --db runs\owner-webcam-check.sqlite`
  (invoked as `python -m reliability_agent.cli`).
- Startup banner: `Mode: REAL HARDWARE`, `Planner: rules`; `NEBIUS_API_KEY not set: running in
  LOCAL MODE`. The dashboard header showed `REAL HARDWARE`, `source Live camera`,
  `planner rules (local planner, no LLM call)`, `model –`, `prompt –`, spend `$0.0000 / $27 cap`
  and `event chain verified`.
- Capture: ~29.9 FPS at rest; healthy windows polled from `/api/status` had brightness ~120–128
  and occluded-cell ratio 0.04–0.21, with one `SUSPECT` window (0.34) that returned to `HEALTHY`
  without an incident.

## Lens cover (the physical input)

Times are UTC from the EventStore.

| Time | Event |
|---|---|
| 20:05:12.229 | `incident` — `candidate_faults: [lens_occlusion]`, occluded-cell ratio 0.868 (`/api/status` at 20:05:34: brightness 79, occluded 0.87); `allowed_actions: [enter_safe_mode, request_manual_cleaning, needs_human]`; capabilities `[restart]` |
| 20:05:12.241 | `plan` — `request_manual_cleaning`, source `rules`, model `local-rules`, cost 0.0 |
| 20:05:12.249 | `policy` — approved, reasons `ok` |
| 20:05:12.259 | `ticket` + `execution` status `ticket` (no device setting changed) |
| 20:05:12.265 | `ACTING → NEEDS_HUMAN` ("ticket opened (request_manual_cleaning); waiting for a human") |
| 20:05:53.821 | lens uncovered: `NEEDS_HUMAN → HEALTHY`, `closed` ("camera healthy again (human fix or transient)") |

The incident stayed in `NEEDS_HUMAN` for 41.6 s, until the hand was removed.

## Startup false positive

At 20:02:11, 17 s after start, a `fov_shift` incident was confirmed
(`geometry.translation_px` 31.9, inlier ratio 0.62), most likely from the laptop or camera
being moved into place. The gate offered `enter_safe_mode`, `request_recalibration` and
`needs_human`. The rule planner chose `request_recalibration`, which opened a ticket
(`NEEDS_HUMAN`), and the incident closed at 20:02:49 once the view was steady again. No setting
was changed.

## Observations for the demo video

- Wait until the state is `HEALTHY` for a while after startup and do not move the laptop;
  otherwise a `fov_shift` recalibration ticket opens first.
- The incident-loop panels (plan, gate, act) are only populated while the incident is open.
  Once it closes they reset to `waiting` / `–`. Show them during `NEEDS_HUMAN`, before
  uncovering the lens.
- The webcam outcome is a cleaning ticket and `needs_human`; no exposure/focus action was offered
  or claimed.
- Not recorded: Windows power mode during this run, and a live Nemotron call (rehearsed
  separately).
