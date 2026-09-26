"""Roadmap bloc 4 -- "benchmark column everywhere": every run row shows the
common reference (persistence baseline, fixed across asset classes, same
test-fold aggregation as the model's F1_dir) and the model's gap to it.
A model score alone does not say whether it beats doing nothing clever."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap", "h", None, None, None)
    db.create_run(conn, "r1", "^VIX", 5, "snap", json.dumps({"name": "vix", "validation": {"scheme": "walkforward"}}),
                  "c", "s", 42)
    tid = db.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, tid)
    db.add_fold_metrics(conn, tid, 1, "test", {"F1_dir": 0.60})
    db.add_fold_metrics(conn, tid, 2, "test", {"F1_dir": 0.62})
    db.add_baseline_metrics(conn, "r1", "BASELINE_persistence", "test", {"F1_dir": 0.55})
    db.add_baseline_metrics(conn, "r1", "BASELINE_majority", "test", {"F1_dir": 0.70})
    db.finish_run(conn, "r1", status="done", n_trials=1)
    db.create_run(conn, "r2", "^VIX", 10, "snap", json.dumps({"name": "no_baseline"}), "c", "s", 42)
    db.finish_run(conn, "r2", status="done", n_trials=0)
    return conn


def test_batch_lookup_returns_the_persistence_f1(tmp_path, monkeypatch):
    conn = _seed(tmp_path, monkeypatch)
    assert db.batch_baseline_f1_dir(conn, ["r1", "r2"]) == {"r1": 0.55}
    runs = {r["run_id"]: r for r in db.list_all_runs(conn)}
    assert runs["r1"]["benchmark_f1_dir"] == 0.55 and runs["r2"]["benchmark_f1_dir"] is None


def test_runs_page_shows_the_benchmark_and_the_gap(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    html = TestClient(app).get("/runs").text
    assert "Persistance" in html
    assert "0.5500" in html
    assert "+0.0600" in html


def test_target_page_shows_the_benchmark_and_the_gap(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    html = TestClient(app).get("/targets/^VIX").text
    assert "Persistance (F1_dir)" in html and "+0.0600" in html
