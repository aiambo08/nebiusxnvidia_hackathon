# ADR-002 — Nemotron model tiers on Token Factory

- Status: proposed (must be confirmed at Gate F0 with `scripts/list_models.py`)
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

## Open questions (TBV at F0)
- Does the default base URL serve us-central1 models, or is
  `https://api.tokenfactory.us-central1.nebius.com/v1/` required?
- Does `response_format: json_schema` work with each Nemotron model? (Fallback: `json_object`.)
- How to disable/limit reasoning traces (e.g. `chat_template_kwargs`) to save tokens.
- Do hackathon credits apply to all regions/models?
