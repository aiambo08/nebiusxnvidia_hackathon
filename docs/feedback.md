# Feedback log (required by the hackathon)

Fill this during development; it becomes the Devpost "feedback" answer.

## Nebius Token Factory
- 2026-10-05: OpenAI-compatible API worked first try with the official `openai` SDK; `GET /v1/models?verbose=true` returned prices and context length, avoiding hardcoded prices. Sources: [model inventory](evidence/f0/models-2026-10-05.json) and [live response log](evidence/f0/nemotron-fast-thinking-off.jsonl).
- 2026-10-05: `response_format: json_schema` was honored by Nemotron 3 Nano and Super. Sources: [fast Nano log](evidence/f0/nemotron-fast-thinking-off.jsonl), [reasoning Super log](evidence/f0/nemotron-reasoning-thinking-off.jsonl).
- 2026-10-05: Nemotron 3 models reason by default; with a modest `max_tokens` the whole budget went to `reasoning_content` and `content` was empty, with HTTP 200 and no warning. A `finish_reason`/documentation note about `chat_template_kwargs.enable_thinking` would have saved a debugging round. Sources: [default-thinking log](evidence/f0/nemotron-thinking-default.jsonl), [thinking-off comparison](evidence/f0/nemotron-reasoning-thinking-off.jsonl).
- 2026-10-05: one base URL served both eu-north1 (Nano) and us-central1 (Super) models. Source: [model inventory](evidence/f0/models-2026-10-05.json).
- 2026-10-18: The golden-v2 live test returned schema-valid plans on every test row; the run cost
  was $0.03057240 across 264 calls, with 98.864% action accuracy. The local selector also scored
  100% by action name, so this is not independent-diagnosis evidence. Sources: [F6 test report](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test.md)
  and [rules baseline](evidence/f6/golden-rules-baseline-test.md).
- 2026-10-18: Three trigger_autofocus plans with invented `delta_ev`/`delta` arguments were rejected
  by the policy gate, so no action ran for those misses. Sources: the F6 test report and
  [F6 misses](evidence/f6/golden-diagnose-v2-nvidia-nvidia-nemotron-3-nano-30b-a3b-test-misses.json).
- 2026-10-18: Narrowing offered actions to supported, fault-relevant choices addressed earlier
  capability-missing plans; the local selector also scores 100% by action name, so action accuracy
  is not evidence of independent diagnosis. Sources: [ADR-009](adr/ADR-009-offer-only-fault-relevant-actions.md),
  [rules baseline](evidence/f6/golden-rules-baseline-test.md).

## Nebius AI Cloud / Serverless
Not used during development; no feedback to report.

## NVIDIA models and tools (Nemotron, DeepStream, …)
- 2026-10-05: with thinking disabled, Nemotron 3 Nano returned schema-valid diagnosis plans in about
  2 seconds for about $0.0001 per diagnosis. This supported testing a call on each confirmed
  incident within the budget. Source: [F0 live response log](evidence/f0/nemotron-fast-thinking-off.jsonl).
