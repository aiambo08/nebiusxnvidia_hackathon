# Feedback log (required by the hackathon)

Fill this during development; it becomes the Devpost "feedback" answer.

## Nebius Token Factory
- 2026-10-05: OpenAI-compatible API worked first try with the official `openai` SDK; `GET /v1/models?verbose=true` returns prices and context length, which let us avoid hardcoding prices.
- 2026-10-05: `response_format: json_schema` honoured by Nemotron 3 Nano and Super.
- 2026-10-05: Nemotron 3 models reason by default; with a modest `max_tokens` the whole budget goes to `reasoning_content` and `content` is empty, with HTTP 200 and no warning. A `finish_reason`/doc note about `chat_template_kwargs.enable_thinking` would have saved a debugging round.
- 2026-10-05: one base URL served both eu-north1 (Nano) and us-central1 (Super) models.
- 2026-10-18: The golden-v2 live test returned schema-valid plans on every test row; the run cost
  was $0.03057240. Source: `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md`.
- 2026-10-18: Three trigger_autofocus plans with invented `delta_ev`/`delta` arguments were rejected
  by the policy gate, so no action ran for those misses. Sources: the F6 test report and
  `docs/evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test-misses.json`.
- 2026-10-18: Narrowing offered actions to supported, fault-relevant choices addressed earlier
  capability-missing plans; the local selector also scores 100% by action name, so action accuracy
  is not evidence of independent diagnosis. Sources: `docs/adr/ADR-009-offer-only-fault-relevant-actions.md`,
  `docs/evidence/f6/golden-rules-baseline-test.md`.

## Nebius AI Cloud / Serverless
Not used during development; no feedback to report.

## NVIDIA models and tools (Nemotron, DeepStream, …)
- 2026-10-05: with thinking disabled, Nemotron 3 Nano returns schema-valid diagnosis plans in ~2 s for ~0.0001 USD, cheap enough to call on every confirmed incident.
