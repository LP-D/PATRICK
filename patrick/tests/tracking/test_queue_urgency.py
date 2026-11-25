"""Tri de la file par urgence (AM9 du 25/11)."""
from __future__ import annotations

import datetime as dt
import json

from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.tracking import queue_urgency

TODAY = dt.date(2026, 11, 25)


def _job(conn, job_id, symbol, horizons, when):
    cfg = json.dumps({"objective": {"target_symbol": symbol, "horizons": horizons}})
    conn.execute("INSERT INTO job (job_id, config_json, status, created_at) VALUES (?, ?, 'queued', ?)", (job_id, cfg, when))


def _champion(conn, target, horizon, promoted):
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    trackdb.create_run(conn, f"r-{target}-{horizon}", target, horizon, "snap", "{}", "cfg", "sha", 1)
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) VALUES (?, ?, ?, 1, ?, 'test')",
                 (target, horizon, f"r-{target}-{horizon}", promoted))


def _seed():
    conn = trackdb.connect()
    _champion(conn, "^GSPC", 1, "2026-11-20")       # 5 jours
    _champion(conn, "EURUSD=X", 1, "2026-06-01")    # 177 jours
    _champion(conn, "BTC-USD", 1, "2026-11-24")
    _job(conn, "j-recent", "^GSPC", [1], "2026-11-25 10:00:00")
    _job(conn, "j-old", "EURUSD=X", [1], "2026-11-25 10:00:01")
    _job(conn, "j-new", "GC=F", [1], "2026-11-25 10:00:02")              # aucun champion
    _job(conn, "j-mixed", "BTC-USD", [1, 5], "2026-11-25 10:00:03")       # h=5 sans champion
    _job(conn, "j-broken", None, [1], "2026-11-25 10:00:04")
    conn.commit()
    return conn


def test_pairs_without_a_champion_come_first_then_the_oldest_champions():
    conn = _seed()
    try:
        assert queue_urgency.sorted_queue(conn, TODAY) == ["j-new", "j-mixed", "j-old", "j-recent", "j-broken"]
    finally:
        conn.close()


def test_the_route_rewrites_the_order_every_worker_reads():
    conn = _seed()
    conn.close()
    body = TestClient(__import__("patrick.webapp.app", fromlist=["app"]).app).post("/api/queue/sort-urgency").json()
    ids = [q.get("id", q.get("job_id")) for q in body["queue"]]
    assert ids[:2] == ["j-new", "j-mixed"]
    conn = trackdb.connect()
    try:
        assert [r[0] for r in conn.execute("SELECT job_id FROM job WHERE status = 'queued' ORDER BY created_at, rowid")][:2] == ["j-new", "j-mixed"]
    finally:
        conn.close()
