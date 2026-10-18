# Devpost submission draft

## Inspiration

Physical AI depends on a camera that remains useful, not merely connected. A blurred, covered,
dark or frozen camera can quietly invalidate a downstream perception task. This project treats
camera reliability as a closed-loop safety problem.

## What it does

The agent monitors camera and task signals, diagnoses confirmed incidents, offers a bounded plan,
checks the deterministic policy gate, and verifies whether the downstream task recovered. It keeps
a change only when verification succeeds; otherwise it rolls back and escalates. Nemotron is
advisory and never executes actions.

## How we built it

We built a MAPE-K loop with local probes and temporal fusion, Nemotron on Nebius Token Factory for
structured diagnosis/planning, a least-privilege policy gate, a snapshot-backed executor, and
downstream verification. A circuit breaker and local planner provide a no-cloud fallback. The
hash-chained event store records plans, model/token/cost details, gate decisions and outcomes.

## Challenges

Image-quality metrics are not reliable proxies for task success: ArUco detection can behave
non-monotonically as blur changes. We therefore verify on downstream task metrics and retain
guardrails. The F6 action score also has an important caveat: the local selector reaches the same
score by action name, so the result is not independent-diagnosis evidence. Freeze is checked on
the confirming window; if onset does not land in that window, a dark frame can hide it. Frozen
overexposure/focus-drift cases may receive one bounded exposure/autofocus action before
snapshot-backed verification and rollback/escalation. Recent-window checking remains open work
([ADR-003](adr/ADR-003-freeze-needs-a-measurable-scene.md)).

## Accomplishments

- REAL HARDWARE CPU measurement with synthetic frames: the owner's 720p paced probe p95 was
  23.2 / 32.6 / 34.5 ms in three Windows Best performance runs. These are CPU timings on synthetic
  frames, not live-camera latency
  ([source](evidence/f3/latency-hardware.md)).
- REAL HARDWARE static-scene and walk-by checks: the webcam-at-rest and two phone RTSP static
  scenes passed; the walk-by observed 22/22 trials, 0 `fov_shift` windows and the bump positive
  control. MJPEG was inconclusive
  ([static-scene](evidence/f3/static-scene-hardware.md),
  [walk-by](evidence/f3/walkby-hardware.md)).
- SIMULATION independent F5 gate review passed 6/6 conditions
  ([project state](agents/PROJECT_STATE.md), [hysteresis report](evidence/f5/hysteresis.md)).
- REAL TOKEN FACTORY golden-v2 test: 264 calls, 100% schema validity, 98.864% action accuracy and
  $0.03057240 run cost (about $0.031); the rules baseline also scored 100% by action name, so this
  is not independent-diagnosis evidence
  ([test](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md),
  [baseline](evidence/f6/golden-rules-baseline-test.md)).
- SIMULATION crash recovery restores the persisted snapshot and escalates without replanning after
  restart; the real webcam adapter remains open work
  ([test](../tests/integration/test_crash_recovery.py),
  [project state](agents/PROJECT_STATE.md)).
- SIMULATION recovery benchmark: 87/100 recoverable cases. Regression raw result was 45/50; all
  45/45 executed cases were contained, while five `dark:0.8` cases were not executed because no
  incident was confirmed. These are benchmark results, not physical-hardware results
  ([source](evidence/f8/recovery-bench.md)).
- Merged F10 A1–A8 SIMULATION report: 454 valid EventStores; A3 recovery 25/25 (20/20 on the
  F8-comparable subset); A4 COMMITTED 0/20 versus 0/20 in A3, so the ablation did not demonstrate
  a difference. The 4 h SIMULATION soak is merged on `main`: 4.0 h, 23/24 faults detected,
  0.25 false alarms/h, +7.2 MB RSS and $0 ([soak report](evidence/f10/soak/soak.md)).
  REAL HARDWARE validation remains pending, so F10 is in progress and the gate is not passed.

## What we learned

Structured output and strict action allowlists help make planning auditable, but a high action
score does not prove independent diagnosis. Verification must use the actual downstream task, and
rollback evidence must distinguish executed actions from cases where no incident was confirmed.

## What's next

Complete the independent product review, run the F4 REAL HARDWARE benchmark, validate F10 on REAL
HARDWARE (the SIMULATION soak is already merged), record the public demo, conduct the five-user test, verify links and submit the
final commit through the owner's account. Real UVC/ONVIF exposure/focus control is not implemented
yet: `OpenCVSource.capabilities()` returns only `restart`, so on a real webcam the gate offers only
restart, safe mode, cleaning/human tickets. Bounded exposure/focus commit/rollback is demonstrated
in SIMULATION only ([source](../src/reliability_agent/capture/sources.py)). F11 license-inventory
and public-repo-audit boxes are ticked on `main` (`4b5b929`; 218 tracked files, 35 distributions);
an independent agent installed and ran it from the README alone
([transcript](evidence/f11/readme-install.md)); the independent F11 gate review passed on `d16436f` (all 7 boxes verified), so F11 is passed ([audit](evidence/f11/public-repo-audit.md); [licenses](third-party-licenses.md)).

## Built with

NVIDIA Nemotron · Nebius Token Factory · Python · OpenCV · FastAPI · SQLite · pytest

## Track

Physical AI

## Feedback

Token Factory's OpenAI-compatible API and structured output supported the live evaluation; the
default reasoning mode could consume the output budget until thinking was disabled. The F6
golden-v2 run made 264 calls, with 100% schema validity, 98.864% action accuracy and $0.03057240
run cost. The local least-privilege selector also scored 100% by action name, so we treat the
Nemotron score as constrained action selection rather than independent diagnosis. Nebius AI Cloud
was not used. Sources: [feedback log](feedback.md), [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md)
and [rules baseline](evidence/f6/golden-rules-baseline-test.md).

## Links

- Repository: <https://github.com/aiambo08/nebiusxnvidia_hackathon>
- Video: `<YouTube URL — added by the owner>`

## Sources

- [F3 latency (REAL HARDWARE CPU, synthetic frames)](evidence/f3/latency-hardware.md)
- [F3 static-scene checks (REAL HARDWARE)](evidence/f3/static-scene-hardware.md)
- [F3 walk-by (REAL HARDWARE)](evidence/f3/walkby-hardware.md)
- [F5 hysteresis review (SIMULATION)](evidence/f5/hysteresis.md)
- [F6 golden-v2 live test](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md)
- [F6 local rules baseline](evidence/f6/golden-rules-baseline-test.md)
- [F7 crash recovery test (SIMULATION)](../tests/integration/test_crash_recovery.py)
- [F8 recovery benchmark (SIMULATION)](evidence/f8/recovery-bench.md)
- [Merged F10 experiments (SIMULATION)](evidence/f10/experiments.md)
- [Freeze-window limitation, ADR-003](adr/ADR-003-freeze-needs-a-measurable-scene.md)
- [Feedback log](feedback.md)
