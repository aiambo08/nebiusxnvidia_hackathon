# Feedback log (required by the hackathon)

Fill this during development; it becomes the Devpost "feedback" answer.

## Nebius Token Factory
- 2026-10-05: OpenAI-compatible API worked first try with the official `openai` SDK; `GET /v1/models?verbose=true` returns prices and context length, which let us avoid hardcoding prices.
- 2026-10-05: `response_format: json_schema` honoured by Nemotron 3 Nano and Super.
- 2026-10-05: Nemotron 3 models reason by default; with a modest `max_tokens` the whole budget goes to `reasoning_content` and `content` is empty, with HTTP 200 and no warning. A `finish_reason`/doc note about `chat_template_kwargs.enable_thinking` would have saved a debugging round.
- 2026-10-05: one base URL served both eu-north1 (Nano) and us-central1 (Super) models.

## Nebius AI Cloud / Serverless
- 

## NVIDIA models and tools (Nemotron, DeepStream, …)
- 2026-10-05: with thinking disabled, Nemotron 3 Nano returns schema-valid diagnosis plans in ~2 s for ~0.0001 USD, cheap enough to call on every confirmed incident.
