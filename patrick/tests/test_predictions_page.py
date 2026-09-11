"""Route tests for `/predictions` (feature/predictions-overview): universe-
wide (target x horizon) table of the latest prediction + Diebold-Mariano
significance. Same style as `test_history_webapp_smoke.py` -- real Jinja
templates through a real FastAPI route, DB seeded directly via
`PATRICK_DB_PATH`, no pipeline run, no network."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.tracking import db
from patrick.webapp.app import app


def _seed_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live",
                        ts=["2024-06-01T00:00:00"], y_true=[None], y_pred=[3], y_proba=[0.71])
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
    db.add_predictions(conn, trial_id, fold_index=1, split="test",
                        ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[3, 0], y_proba=[0.7, 0.7])
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()


def test_predictions_page_returns_200_on_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/predictions")
    assert resp.status_code == 200


def test_predictions_page_shows_significant_prediction(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/predictions")
    assert resp.status_code == 200
    assert "^VIX" in resp.text
    assert "5j" in resp.text
    # UP (classe 3, cf. _CLASS_DIRECTION) + p=0.0300 < 0.05 -> badge "ok".
    assert "UP" in resp.text
    assert "0.0300" in resp.text


def test_predictions_page_shows_explicit_empty_state_for_pairs_without_data(tmp_path, monkeypatch):
    """La quasi-totalite des ~408 paires (68 cibles x 6 horizons) n'ont
    aucune prediction sur une base fraiche -- chacune doit afficher un etat
    vide explicite ("aucune prediction"), jamais une case silencieusement
    absente ou une exception."""
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/predictions")
    assert resp.status_code == 200
    assert "aucune prédiction" in resp.text
    # ^VIX/h=5 a une prediction ; ^VIX/h=10 (meme cible, autre horizon) n'en a pas.
    assert "10j" in resp.text


def test_predictions_page_groups_match_default_target_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/predictions")
    for group_name in D.DEFAULT_TARGET_GROUPS:
        assert group_name in resp.text


def test_predictions_reachable_from_nav():
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/predictions"' in resp.text


def test_predictions_page_shows_live_hit_rate(tmp_path, monkeypatch):
    """Phase 3 (suivi prediction -> realise) -- la colonne 'Fiabilite live'
    doit afficher le hit rate calcule sur les predictions `split='live'`
    deja backfillees, distinct de la significativite Diebold-Mariano
    (backtest) affichee a cote."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    # 10 predictions live resolues, 7 hits / 3 miss (>= _MIN_DIRECTION_SAMPLES
    # donc le badge n'est pas dans l'etat "peu de recul").
    for i in range(7):
        db.add_predictions(conn, trial_id, fold_index=None, split="live",
                            ts=[f"2024-06-{i+1:02d}T00:00:00"], y_true=[1.0], y_pred=[3], y_proba=[0.6])
    for i in range(3):
        db.add_predictions(conn, trial_id, fold_index=None, split="live",
                            ts=[f"2024-06-{i+8:02d}T00:00:00"], y_true=[0.0], y_pred=[3], y_proba=[0.6])
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()

    client = TestClient(app)
    resp = client.get("/predictions")
    assert resp.status_code == 200
    # 7/10 = 70%, n=10.
    assert "70% (n=10)" in resp.text


# flexibility-gaps Gap 2: ?dm_alpha= overrides the DM significance
# threshold, sourced from tracking.history.DM_SIGNIFICANCE_ALPHA -- no
# longer a literal 0.05 hardcoded in the template.

def test_predictions_page_dm_alpha_query_param_changes_significance_badge(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    resp_default = client.get("/predictions")
    assert resp_default.status_code == 200
    # p=0.03 < default alpha (0.05) -> "ok" badge.
    assert 'status-ok">p=0.0300' in resp_default.text

    resp_strict = client.get("/predictions", params={"dm_alpha": "0.01"})
    assert resp_strict.status_code == 200
    # Same p-value, stricter alpha (0.01) -> no longer significant -> "warning".
    assert 'status-warning">p=0.0300' in resp_strict.text
    assert "0,01" in resp_strict.text  # subtitle reflects the actual threshold used


def test_predictions_page_rejects_non_positive_dm_alpha(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/predictions", params={"dm_alpha": "0"})
    assert resp.status_code == 400


def test_predictions_page_rejects_dm_alpha_above_one(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    resp = client.get("/predictions", params={"dm_alpha": "1.5"})
    assert resp.status_code == 400


def test_predictions_page_shows_no_live_track_record_state(tmp_path, monkeypatch):
    """Une paire (cible, horizon) sans aucune prediction 'live' backfillee
    affiche un etat vide explicite pour la colonne live, jamais une case
    silencieusement absente."""
    _seed_db(tmp_path, monkeypatch)  # seed_db du test existant : 1 live non backfillee (y_true=None)
    client = TestClient(app)
    resp = client.get("/predictions")
    assert resp.status_code == 200
    assert "pas de recul live" in resp.text
