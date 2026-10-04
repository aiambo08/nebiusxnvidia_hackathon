# Evaluation protocol

## Faults (MVP = first five)
1. blackout / darkness  2. strong blur (defocus)  3. freeze (repeated frame / short loop)
4. lens occlusion (opaque, partial)  5. overexposure
Extensions: FOV shift (rotation/translation), FPS drop, delay/jitter, RTSP disconnect, motion blur,
semi-transparent occlusion, legitimate lighting change, static scene (negatives).

## Data
- Real webcam sessions + synthetic degradations from `benchmarks/injectors/faults.py` (seeded).
- Each run described by a manifest (`benchmarks/manifests/*.yaml`) with source hash, fault type,
  intensity, start/end, expected action or `needs_human`.
- **Split by session, never by random consecutive frames** (WoodScape leakage lesson).

## Metrics
Per fault precision/recall/F1, false alarms per hour, time to detect, time to recover, % actions
committed, % correct rollbacks, downstream task delta before/after, Nemotron calls and USD per
incident, % schema-valid responses, human interventions avoided.

**Headline metric:** % of incidents where downstream capability is recovered without human
intervention and without introducing a regression.

## Ablations (F10)
local detector only · detector + Nemotron without actions · full loop · no downstream metric ·
single baseline · Token Factory outage · RTSP failure during action · restart in every state.
