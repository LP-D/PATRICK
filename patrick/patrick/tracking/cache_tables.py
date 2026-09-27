"""Additive, isolated SQLite schema for the local cache layer (SHAP
explanations of recorded predictions).

Deliberately NOT a numbered migration run through `db.migrate()`: that
function has a known, still-unreproduced race on `schema_version`
(out of scope here -- it needs its own failing reproduction test before any
fix). These tables are created by `ensure_cache_schema()` with plain
`CREATE TABLE IF NOT EXISTS` -- idempotent, safe to call on every access
from any process, never touches `schema_version`, and never alters an
existing table. Predictions themselves already live in the `prediction`
table (migration 0001); this module only adds what was recomputed on every
page open.

Key (ported from feature/replay-cache-universe, 7373b4f, and tightened):
- `trial_id`: the explained model is immutable per trial;
- `ts`: the explained prediction date;
- `snapshot_id`: the data snapshot the feature row was rebuilt from (the
  one `explain._load_snapshot_for_prediction` picks) -- a newer vintage
  revising the past gets its own row, never a stale hit;
- `code_hash`: hash of the code that produces the payload (`explain.py`
  and the feature source code, `pool_cache.FEATURE_CODE_HASH`) -- a fix to
  either invalidates every cached explanation without anyone having to
  remember to bump a version (the branch's version had no such component).
"""
from __future__ import annotations

import json
import sqlite3

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS shap_explanation_cache (
        trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (trial_id, ts, snapshot_id, code_hash)
    )""",
)


def ensure_cache_schema(conn: sqlite3.Connection) -> None:
    with conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)


def get_cached_shap(conn: sqlite3.Connection, trial_id: int, ts: str, snapshot_id: str,
                    code_hash: str) -> dict | None:
    ensure_cache_schema(conn)
    row = conn.execute(
        "SELECT payload_json FROM shap_explanation_cache "
        "WHERE trial_id = ? AND ts = ? AND snapshot_id = ? AND code_hash = ?",
        (trial_id, ts, snapshot_id, code_hash)).fetchone()
    return json.loads(row[0]) if row else None


def save_cached_shap(conn: sqlite3.Connection, trial_id: int, ts: str, snapshot_id: str,
                     code_hash: str, payload: dict) -> None:
    ensure_cache_schema(conn)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO shap_explanation_cache "
            "(trial_id, ts, snapshot_id, code_hash, payload_json) VALUES (?, ?, ?, ?, ?)",
            (trial_id, ts, snapshot_id, code_hash, json.dumps(payload)))
