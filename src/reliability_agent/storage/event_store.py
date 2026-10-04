"""Knowledge store (MAPE-K "K"): append-only, hash-chained SQLite event log.

Every decision (telemetry summary, incident, plan, policy decision, execution, verification,
rollback, budget usage) is an event. Benchmark and README numbers must be generated from these
events, never typed by hand (Gate F10).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  incident_id TEXT,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_incident ON events(incident_id);
CREATE TABLE IF NOT EXISTS snapshots (
  execution_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  action TEXT NOT NULL,
  payload TEXT NOT NULL,
  ts TEXT NOT NULL,
  restored INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  model TEXT,
  prompt_version TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  cached INTEGER
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

GENESIS = "0" * 64


def _default(o: Any) -> Any:
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(map(str, o))
    return str(o)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, default=_default, sort_keys=True, separators=(",", ":"))


class EventStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._db.close()

    # -- events
    def _last_hash(self) -> str:
        row = self._db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS

    def append(self, kind: str, payload: Any, incident_id: str | None = None) -> str:
        with self._lock:
            ts = datetime.now(UTC).isoformat()
            body = _dumps(payload)
            prev = self._last_hash()
            h = hashlib.sha256(f"{prev}|{ts}|{incident_id}|{kind}|{body}".encode()).hexdigest()
            self._db.execute(
                "INSERT INTO events(ts, incident_id, kind, payload, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?)", (ts, incident_id, kind, body, prev, h))
            self._db.commit()
            return h

    def events(self, incident_id: str | None = None, kind: str | None = None) -> list[dict]:
        q, args = "SELECT seq, ts, incident_id, kind, payload FROM events", []
        conds = []
        if incident_id:
            conds.append("incident_id = ?")
            args.append(incident_id)
        if kind:
            conds.append("kind = ?")
            args.append(kind)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY seq"
        return [
            {"seq": s, "ts": ts, "incident_id": i, "kind": k, "payload": json.loads(p)}
            for s, ts, i, k, p in self._db.execute(q, args).fetchall()
        ]

    def verify_chain(self) -> bool:
        prev = GENESIS
        for ts, inc, kind, body, p, h in self._db.execute(
            "SELECT ts, incident_id, kind, payload, prev_hash, hash FROM events ORDER BY seq"
        ):
            if p != prev:
                return False
            if hashlib.sha256(f"{prev}|{ts}|{inc}|{kind}|{body}".encode()).hexdigest() != h:
                return False
            prev = h
        return True

    # -- snapshots (written BEFORE an action changes the device)
    def save_snapshot(self, execution_id: str, incident_id: str, action: str,
                      snapshot: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,0)",
                (execution_id, incident_id, action, _dumps(snapshot),
                 datetime.now(UTC).isoformat()))
            self._db.commit()

    def mark_restored(self, execution_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE snapshots SET restored=1 WHERE execution_id=?",
                             (execution_id,))
            self._db.commit()

    def pending_snapshots(self) -> list[dict]:
        """Snapshots whose action outcome was never committed/restored (crash recovery)."""
        rows = self._db.execute(
            "SELECT execution_id, incident_id, action, payload FROM snapshots WHERE restored=0"
        ).fetchall()
        return [{"execution_id": e, "incident_id": i, "action": a, "snapshot": json.loads(p)}
                for e, i, a, p in rows]

    # -- usage / budget
    def record_usage(self, model: str | None, prompt_version: str | None, input_tokens: int,
                     output_tokens: int, cost_usd: float, cached: bool = False) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO usage(ts, model, prompt_version, input_tokens, output_tokens, "
                "cost_usd, cached) VALUES (?,?,?,?,?,?,?)",
                (datetime.now(UTC).isoformat(), model, prompt_version, input_tokens,
                 output_tokens, cost_usd, int(cached)))
            self._db.commit()

    def spent_usd(self) -> float:
        row = self._db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM usage").fetchone()
        return float(row[0])

    # -- small persistent state (baseline, FSM)
    def put_state(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, _dumps(value)))
            self._db.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default
