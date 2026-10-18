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
score by action name, so the result is not independent-diagnosis evidence.

## Accomplishments

- REAL HARDWARE CPU measurement with synthetic frames: the owner's 720p paced probe p95 was
  23.2 / 32.6 / 34.5 ms in Best performance runs
  ([source](evidence/f3/latency-hardware.md)).
- REAL TOKEN FACTORY golden-set test: 100% schema validity, 98.864% action accuracy and
  $0.03057240 run cost; the rules baseline caveat is documented
  ([test](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md),
  [baseline](evidence/f6/golden-rules-baseline-test.md)).
- SIMULATION recovery benchmark: 87/100 recoverable cases; 45/45 executed regression cases were
  contained. These are benchmark results, not physical-hardware results
  ([source](evidence/f8/recovery-bench.md)).
- The F10 A1–A8 report, video, five-user test, final tag and Devpost submission remain pending.

## What we learned

Structured output and strict action allowlists help make planning auditable, but a high action
score does not prove independent diagnosis. Verification must use the actual downstream task, and
rollback evidence must distinguish executed actions from cases where no incident was confirmed.

## What's next

Complete the independent product review, run the real-hardware F4 benchmark, record the demo,
conduct the user test, verify public links and submit the final commit through the owner's account.

## Built with

NVIDIA Nemotron · Nebius Token Factory · Python · OpenCV · FastAPI · SQLite · pytest

## Track

Physical AI

## Feedback

Token Factory's OpenAI-compatible API and structured output supported the live evaluation. The
default reasoning mode consumed the output budget until thinking was disabled. The local
least-privilege action selector scored as well by action name on the golden test, so we treat the
Nemotron score as constrained action selection rather than independent diagnosis. Nebius AI Cloud
was not used. Sources: `docs/feedback.md`, the F6 test report and rules baseline.

## Links

- Repository: <https://github.com/aiambo08/nebiusxnvidia_hackathon>
- Video: `<YouTube URL — added by the owner>`

## Sources

- `docs/evidence/f3/latency-hardware.md`
- `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md`
- `docs/evidence/f6/golden-rules-baseline-test.md`
- `docs/evidence/f8/recovery-bench.md`
- `docs/feedback.md`
