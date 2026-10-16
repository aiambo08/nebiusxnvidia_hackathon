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

## F4 protocol (pre-registered before any F4 recording)
- Sessions: `python scripts/record_clip.py --uri 0 --seconds 300 --session s0NN --split test
  --conditions "<scene, light, people>"` adds the clip's sha256, frames, FPS and conditions to
  `benchmarks/manifests/sessions.yaml` (committed; clips stay in git-ignored `benchmarks/data/`,
  never overwritten). `dev` sessions are never scored; `s001` and every clip hash in the F1/F3
  manifests count as development data.
- Runs: `python -m benchmarks.build_manifests` writes `benchmarks/manifests/f4/` — per test
  session × MVP fault, three runs of 30 s healthy lead-in + 30 s fault, one per non-overlapping
  slot of the session, strengths `dark` 0.9/0.95/1.0, `gaussian_blur` 0.7/0.85/1.0, `freeze` 1.0,
  `occlude_opaque` 0.7/0.85/1.0, `overexpose` 0.8/0.9/1.0, plus three `lighting_change`
  negatives; seeds derived from (session, fault, slot). Faults are SIMULATION on the clips.
- Degraded clips: `python -m benchmarks.make_degraded --all` (hash-checked, byte-for-byte frames).
- Report: `python scripts/run_benchmark.py` → `benchmarks/reports/<date>-f4.md` + `.json`. Every
  test session is also replayed in full with `rearm=True` (each confirmation counted) for false
  alarms per hour. TP/FP rules as `scripts/bench_detectors.py`; F1 per MVP detector, macro F1 over
  the five (a detector with no TP scores 0). Exit 0 only if every box it judges passes.
- Limits: 30 min of normal clips means a single false alarm is already 2 / h; three runs per
  session share the session's scene, so "independent" means ≥ 5 sessions per fault.

## Metrics
Per fault precision/recall/F1, false alarms per hour, time to detect, time to recover, % actions
committed, % correct rollbacks, downstream task delta before/after, Nemotron calls and USD per
incident, % schema-valid responses, human interventions avoided.

**Headline metric:** % of incidents where downstream capability is recovered without human
intervention and without introducing a regression.

## Ablations (F10)
local detector only · detector + Nemotron without actions · full loop · no downstream metric ·
single baseline · Token Factory outage · RTSP failure during action · restart in every state.
