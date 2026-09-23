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
"""
from __future__ import annotations

import json
import sqlite3

_SCHEMA = (
    # One row per (trial, prediction date, data snapshot): the explained
    # model is immutable per trial_id, and the feature row at `ts` depends
    # on the raw snapshot it was rebuilt from -- a newer vintage revising
    # the past gets its own row, never a stale hit.
    """CREATE TABLE IF NOT EXISTS shap_explanation_cache (
        trial_id INTEGER NOT NULL REFERENCES trial(trial_id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (trial_id, ts, snapshot_id)
    )""",
)


def ensure_cache_schema(conn: sqlite3.Connection) -> None:
    with conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)


def get_cached_shap(conn: sqlite3.Connection, trial_id: int, ts: str, snapshot_id: str) -> dict | None:
    ensure_cache_schema(conn)
    row = conn.execute(
        "SELECT payload_json FROM shap_explanation_cache WHERE trial_id = ? AND ts = ? AND snapshot_id = ?",
        (trial_id, ts, snapshot_id)).fetchone()
    return json.loads(row[0]) if row else None


def save_cached_shap(conn: sqlite3.Connection, trial_id: int, ts: str, snapshot_id: str,
                     payload: dict) -> None:
    ensure_cache_schema(conn)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO shap_explanation_cache (trial_id, ts, snapshot_id, payload_json) "
            "VALUES (?, ?, ?, ?)", (trial_id, ts, snapshot_id, json.dumps(payload)))
