"""Index de recherche élargi de la palette Ctrl K (AM13 du 25/11)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.webapp.app import app


def test_the_index_holds_notions_courses_and_recent_runs():
    conn = trackdb.connect()
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    trackdb.create_run(conn, "run-xyz", "^GSPC", 5, "snap", '{"name": "Mon essai"}', "cfg", "sha", 1)
    conn.commit()
    conn.close()
    rows = TestClient(app).get("/api/search-index").json()
    kinds = {r["k"] for r in rows}
    assert {"notion", "cours", "run"} <= kinds
    run = next(r for r in rows if r["k"] == "run")
    assert run["u"] == "/runs/run-xyz/analyse" and "Mon essai" in run["l"] and run["a"] == "run-xyz"
    assert sum(r["k"] == "notion" for r in rows) > 500
