# Project state

Last update: 2026-10-04 · Current phase: **F0** · Days to deadline: 26

## Snapshot
- Repository scaffolded: contracts, FSM, capture, probes, baseline, fusion, Nemotron client with
  budget guard, policy gate, simulated actions, verifier, SQLite event store, offline demo.
- No live Token Factory call yet → Gate F0 open.

## Budget (update weekly from the Token Factory console)
| Date | Ledger estimate (USD) | Console balance (USD) |
|---|---:|---:|
| 2026-10-04 | 0.00 | 30.00 (to confirm) |

## Blockers
- Need `NEBIUS_API_KEY` in local `.env` (human-only).
- Confirm Nemotron model IDs/regions with `scripts/list_models.py`.

## Next 3 actions
1. Human: create `.env`, run `python scripts/list_models.py`, then `python scripts/spike_nemotron.py --n 20`.
2. Ingestion: run `python scripts/spike_capture.py --minutes 30` on the real webcam.
3. Vision: record 10 clean minutes + first manual faults for the F3/F4 dataset.
