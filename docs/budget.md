# Budget policy — total extra spend must be 0 USD

The only paid resource is Token Factory inference, paid with the 30 USD hackathon credits.
Everything else is free: local Python/OpenCV, SQLite, GitHub (public repo + Actions), YouTube.
**No dedicated endpoints** (a running replica is billed while up).

| Pool | Max (USD) | Use |
|---|---:|---|
| Development | 12 | prompts, errors, first evaluation |
| Evaluation | 7 | golden set + adversarial |
| Demo rehearsals | 4 | controlled repetitions |
| Margin | 7 | contingency, never consumed automatically |

Caps enforced by `nemotron/budget.py` (ledger persisted in SQLite):
- **soft cap 23 USD** → non-essential calls (reasoning tier, re-diagnosis) disabled.
- **demo cap 25 USD** → only calls flagged `demo=True` allowed.
- **hard cap 27 USD** → no request leaves the client.
- Alerts at 50%, 70%, 80% of the 30 USD total.

Per-incident controls: ≤ 2 calls normally, 3rd only on explicit disagreement; cache by incident
signature; compact JSON; no continuous video.

The ledger is an *estimate* from token usage × catalog price. Cross-check weekly with the Token
Factory console and record the real balance in `docs/agents/PROJECT_STATE.md`.
