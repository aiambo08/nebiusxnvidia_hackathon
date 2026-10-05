# ADR-002 — Nemotron model tiers on Token Factory

- Status: accepted (confirmed live at Gate F0 on 2026-10-05)
- Date: 2026-10-04

## Context
The public Token Factory catalog (<https://tokenfactory.nebius.com/model-catalog.md>, read
2026-10-04) lists, among others:

| Model ID (catalog) | Region | Input $/M | Output $/M |
|---|---|---:|---:|
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | eu-north1 | 0.06 | 0.24 |
| `nvidia/Nemotron-3_5-Lightning` | eu-north1 | 0.06 | 0.24 |
| `nvidia/nemotron-3-super-120b-a12b` | us-central1 | 0.30 | 0.90 |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | us-central1 | 1.00 | 3.00 |

All four are text-to-text. We therefore send **structured metrics, not video**.

## Decision
- `fast` tier (default for every incident): Nemotron 3 Nano or 3.5 Lightning.
- `reasoning` tier (only on ambiguity/disagreement, max 1 extra call per incident): Nemotron 3 Super.
- Ultra is not used by default (cost).
- Prices in `configs/default.yaml` are **fallbacks**; at startup they are refreshed from
  `GET /v1/models?verbose=true` when available.

## Verified at F0 (2026-10-05, live calls with the owner's key)
Evidence: `docs/evidence/f0/` (copies of `runs/models-2026-10-05.json` and spike JSONL files; no secrets).

- `GET /v1/models` returns 25 models, 4 NVIDIA: the four IDs above, with the same prices as the
  catalog. Both configured tiers report `OK`.
- The default base URL `https://api.tokenfactory.nebius.com/v1/` serves the us-central1 Super
  model; no regional URL is needed.
- `response_format: json_schema` works for Nano and Super (no `json_object` fallback triggered).
- **Reasoning is on by default.** With `max_tokens=600`, Super spent all 600 tokens in
  `reasoning_content` and returned empty `content`; the planner spike scored **0/20** schema-valid
  (`nemotron-thinking-default.jsonl`). Nano with thinking on also mis-labelled a blackout probe
  as "blur".
- Fix: `nebius.extra_body: {chat_template_kwargs: {enable_thinking: false}}` in
  `configs/default.yaml`. Result: fast tier **20/20** valid, 20/20 diagnosis = local top fault,
  mean 0.00010 USD and ~2.0 s per diagnosis; reasoning tier **5/5** valid, 0.00047 USD per call.
- Super disagreed with the local top fault in 2/5 cases (blackout → `lens_occlusion`,
  freeze → `stream_down`). Not wrong per se (both are plausible causes of the evidence); it is
  input for the F6 golden set and the escalation rule.

## Consequences
- Thinking stays disabled for diagnosis. Re-enabling it for the reasoning tier requires a larger
  `max_output_tokens` and a new spike; record it here if done.
- Credits apply to all four NVIDIA models from the same key (all calls succeeded).
