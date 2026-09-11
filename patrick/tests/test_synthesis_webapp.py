"""P8 -- smoke tests for the synthesis dashboard ("/", replaces the old
launcher route) and its two structural consequences: the launcher moved to
"/launch", and "/phase9" was trimmed to journal/snapshots only. Same style
as `test_history_webapp_smoke.py`: seeds the DB directly, renders the real
FastAPI app, no pipeline run."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def test_synthesis_page_renders_empty_states_on_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Aucun résultat Diebold-Mariano en base" in resp.text
    assert "Classification de régime jamais exécutée en production" in resp.text
    assert "Aucune prédiction enregistrée" in resp.text
    assert "Aucune métrique par direction disponible" in resp.text


def _seed_run_with_predictions(conn, up_correct=8, up_wrong=2, down_correct=9, down_wrong=1) -> None:
    config = {
        "name": "vix_synthesis", "target": "^VIX",
        "validation": {"scheme": "walkforward"},
    }
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps(config), "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6, "AUC_ovr_4cls": 0.58})
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})
    db.finish_run(conn, "run1", status="done", n_trials=1)

    ts, y_true, y_pred = [], [], []
    i = 0
    for _ in range(up_correct):
        ts.append(f"2024-01-{i+1:02d}"); y_true.append(3); y_pred.append(3); i += 1
    for _ in range(up_wrong):
        ts.append(f"2024-02-{i+1:02d}"); y_true.append(2); y_pred.append(0); i += 1
    for _ in range(down_correct):
        ts.append(f"2024-03-{i+1:02d}"); y_true.append(0); y_pred.append(0); i += 1
    for _ in range(down_wrong):
        ts.append(f"2024-04-{i+1:02d}"); y_true.append(1); y_pred.append(2); i += 1
    db.add_predictions(conn, trial_id, fold_index=1, split="test", ts=ts, y_true=y_true, y_pred=y_pred,
                        y_proba=[0.7] * len(ts))
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2024-05-01T00:00:00"],
                        y_true=[None], y_pred=[3], y_proba=[0.81])


def test_synthesis_page_renders_with_real_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    _seed_run_with_predictions(conn)
    conn.close()

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "^VIX" in resp.text
    assert "0.0300" in resp.text  # p-value DM, real value from dm_result
    assert "UP" in resp.text or "hausse" in resp.text.lower()
    assert "2024-05-01" in resp.text  # latest (live) prediction timestamp
    # 10 UP (8+2) and 10 DOWN (9+1) rows -- both clear the >=10 threshold,
    # so real precision/recall/F1 must render, not the "insufficient data" NA.
    assert "min 10" not in resp.text


def test_synthesis_page_no_page_cache_reflects_new_run(tmp_path, monkeypatch):
    """B4 -- no caching layer: a run added between two requests must show up
    on the very next load, no restart/invalidation needed."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    first = client.get("/")
    assert "0.0300" not in first.text

    conn = db.connect(str(tmp_path / "patrick.db"))
    _seed_run_with_predictions(conn)
    conn.close()

    second = client.get("/")
    assert "0.0300" in second.text


# flexibility-gaps Gap 4: ?fdr_alpha= on "/" was previously fixed at 0.10
# (tracking.history.station_verdict's own default) with no way to change
# it from the web -- CLI already had `patrick report --fdr-alpha`.

def test_synthesis_page_fdr_alpha_query_param_changes_verdict_and_quality_table(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    _seed_run_with_predictions(conn)
    conn.close()

    client = TestClient(app)
    resp_default = client.get("/")
    assert resp_default.status_code == 200
    # Single target, p=0.03 < default alpha (0.10) -> significant -> survivor.
    assert "α=0.1)" in resp_default.text
    assert "alpha=0.1." in resp_default.text  # quality-table footer (overview.fdr_alpha)

    resp_strict = client.get("/", params={"fdr_alpha": "0.01"})
    assert resp_strict.status_code == 200
    # Same p-value, stricter alpha -> no more survivors.
    assert "α=0.01)" in resp_strict.text
    assert "alpha=0.01." in resp_strict.text


def test_synthesis_page_rejects_non_positive_fdr_alpha(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/", params={"fdr_alpha": "0"})
    assert resp.status_code == 400


def test_synthesis_page_rejects_fdr_alpha_above_one(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/", params={"fdr_alpha": "1.5"})
    assert resp.status_code == 400


def test_launch_page_serves_the_run_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    assert "Poste de lancement" in resp.text
    assert 'id="run-form"' in resp.text


def test_launch_page_has_no_example_loader(tmp_path, monkeypatch):
    """fix/remove-launch-example-loader : le dropdown "Charger un exemple"
    (id="load" / id="example-form") rechargeait la page et ecrasait
    silencieusement les 65 champs saisis au premier changement (cf.
    .impeccable/critique/...index-html.md) -- retire sans remplacement, du
    template et de la route /launch."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch")
    assert resp.status_code == 200
    assert 'id="example-form"' not in resp.text
    assert 'id="load"' not in resp.text


def test_launch_page_ignores_stale_load_query_param(tmp_path, monkeypatch):
    """Un ancien lien/marque-page vers /launch?load=... (point d'entree
    retire) ne doit plus produire d'erreur ni de comportement special --
    parametre simplement ignore, page normale rendue."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/launch", params={"load": "some_example.yaml"})
    assert resp.status_code == 200
    assert 'id="run-form"' in resp.text


def test_phase9_page_no_longer_carries_fabricated_signal_quality(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/phase9")
    assert resp.status_code == 200
    assert "Journal de décision" in resp.text
    assert "Qualité des signaux" not in resp.text
    assert "Classification de régime" not in resp.text
