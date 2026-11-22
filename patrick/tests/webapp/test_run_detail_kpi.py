"""Run detail page (`/runs/{id}/detail`): the KPI section of the whole launch
(all horizons that share the run's job) -- per algorithm, per number of
features, ranking, best per horizon."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

_CONFIG = RunConfig.model_validate({
    "name": "kpi_page", "objective": {"target_symbol": "^TEST", "horizons": [1, 5], "regimes": ["GLOBAL"]},
}).model_dump_json()


def _seed(db_path: str) -> None:
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    grid = {  # horizon -> {(algo, N): fold-1 (F1_dir, Acc_dir)}
        1: {("AlgoA", 5): (0.50, 0.55), ("AlgoA", 6): (0.60, 0.65), ("AlgoB", 5): (0.40, 0.45), ("AlgoB", 6): (0.30, 0.35)},
        5: {("AlgoA", 5): (0.58, 0.60), ("AlgoA", 6): (0.52, 0.50), ("AlgoB", 5): (0.62, 0.66), ("AlgoB", 6): (0.44, 0.40)},
    }
    for horizon, candidates in grid.items():
        run_id = f"kpi_page_h{horizon}"
        trackdb.create_run(conn, run_id, target="^TEST", horizon=horizon, snapshot_id="snap1", config_json=_CONFIG,
                           config_hash="h", git_sha="sha", seed=42, job_id="job-kpi")
        with conn:
            conn.execute("UPDATE run SET status = 'done' WHERE run_id = ?", (run_id,))
        for (algo, n), (f1, acc) in candidates.items():
            tid = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", n, "shap")
            trackdb.add_fold_metrics(conn, tid, 1, "test", {"F1_dir": f1, "Acc_dir": acc})
            if f1 == max(v[0] for v in candidates.values()):       # the finalist goes on to fold 2
                trackdb.add_fold_metrics(conn, tid, 2, "test", {"F1_dir": f1 - 0.1, "Acc_dir": acc - 0.1})
    conn.close()


def test_detail_page_shows_the_kpi_of_the_whole_launch(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    _seed(db_path)

    # asked from ONE horizon's page, the section covers the launch's two horizons
    resp = TestClient(app).get("/runs/kpi_page_h1/detail")

    assert resp.status_code == 200, resp.text[:300]
    html = resp.text
    assert 'id="kpi"' in html and "Synthèse des modèles" in html
    for heading in ("Par algorithme", "Par nombre de variables", "Classement des configurations", "Par horizon"):
        assert heading in html
    assert "AlgoA" in html and "AlgoB" in html
    assert "0.550" in html                    # AlgoA's mean F1_dir over both horizons
    assert "premier fold" in html            # the comparison window is stated
    assert 'href="#kpi"' in html
    assert "holdout" in html and "optimiste" in html


def test_detail_page_without_any_grid_has_no_kpi_section(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "empty_run", target="^TEST", horizon=1, snapshot_id="snap1", config_json=_CONFIG,
                       config_hash="h", git_sha="sha", seed=42)
    conn.close()

    resp = TestClient(app).get("/runs/empty_run/detail")

    assert resp.status_code == 200
    assert 'id="kpi"' not in resp.text
