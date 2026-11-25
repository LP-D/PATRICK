"""A28 : depuis l'onglet « Comparer » d'un run, la liste des runs se restreint d'office à sa cible."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.webapp.app import app


def test_compare_preselects_the_runs_of_the_same_target(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    for run_id, target in (("gold_1", "GC=F"), ("gold_2", "GC=F"), ("cac_1", "^FCHI")):
        trackdb.create_run(conn, run_id, target=target, horizon=1, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
        tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 3, "shap")
        trackdb.mark_best_trial(conn, tid, artifact_path=None)
        trackdb.finish_run(conn, run_id, "done", n_trials=1)
    conn.close()
    client = TestClient(app)

    html = client.get("/runs?compare=gold_1").text
    assert 'value="gold_1"' in html and 'value="gold_2"' in html and 'value="cac_1"' not in html
    assert 'value="cac_1"' in client.get("/runs").text                          # sans compare : toutes les cibles
