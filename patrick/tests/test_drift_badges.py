"""Roadmap bloc 3 -- drift badge per (target, horizon) from stored data,
and the on-demand PSI measurement route."""
from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from patrick.tracking import db, history
from patrick.webapp.app import app


def _seed(conn, n_live=0, flip_at=None):
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", "^VIX", 5, "s", "{}", "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    db.mark_best_trial(conn, tid)
    db.finish_run(conn, "r", "done", n_trials=1)
    if n_live:
        ts = [str(d.date()) for d in pd.bdate_range("2025-01-01", periods=n_live)]
        y_true = [1.0 if (flip_at is None or i < flip_at) else 0.0 for i in range(n_live)]
        db.add_predictions(conn, tid, 0, "live", ts, y_true=y_true, y_pred=[3] * n_live, y_proba=[0.7] * n_live)
    return tid


def test_states_follow_what_is_measured(conn):
    _seed(conn)
    assert history.drift_badges(conn, ["^VIX"], [5])[("^VIX", 5)]["state"] == "insufficient_data"
    db.record_drift_psi(conn, "^VIX", 5, "f1", 0.05)
    db.record_drift_psi(conn, "^VIX", 5, "f2", 0.31)
    b = history.drift_badges(conn, ["^VIX"], [5])[("^VIX", 5)]
    assert b["state"] == "provisional" and b["status"] == "significant"
    assert b["worst_feature"] == "f2" and b["n_features"] == 2


def test_page_hinkley_on_resolved_live_calls_confirms_a_concept_drift(conn):
    _seed(conn, n_live=120, flip_at=60)
    db.record_drift_psi(conn, "^VIX", 5, "f1", 0.02)
    b = history.drift_badges(conn, ["^VIX"], [5])[("^VIX", 5)]
    assert b["state"] == "confirmed" and b["concept_drift"] is True and b["status"] == "stable"


def test_predictions_page_shows_the_badge(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    _seed(conn)
    db.record_drift_psi(conn, "^VIX", 5, "f1", 0.18)
    html = TestClient(app).get("/predictions").text
    assert "attention · PSI 0.18" in html and "non mesurée" in html


def test_measure_route(monkeypatch):
    from patrick import explain
    monkeypatch.setattr(explain, "compute_drift_for_ticker_horizon",
                        lambda t, h: {"a": {"psi": 0.3, "status": "significant"}, "b": {"psi": 0.01, "status": "stable"}})
    resp = TestClient(app).post("/api/drift/^VIX/5")
    assert resp.status_code == 200 and [f["feature"] for f in resp.json()["features"]] == ["a", "b"]
    monkeypatch.setattr(explain, "compute_drift_for_ticker_horizon", lambda t, h: None)
    assert TestClient(app).post("/api/drift/^VIX/5").status_code == 404
