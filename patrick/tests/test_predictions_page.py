"""Route tests for `/predictions` (feature/predictions-overview): universe-
wide (target x horizon) table of the latest prediction + Diebold-Mariano
significance. Same style as `test_history_webapp_smoke.py` -- real Jinja
templates through a real FastAPI route, DB seeded directly via
`PATRICK_DB_PATH`, no pipeline run, no network."""
from __future__ import annotations

from page_support import FullPageClient as TestClient

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
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03}, sample="holdout")
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
    assert "Hausse forte" in resp.text  # classe 3 = UP + FORT
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


def _seed_resolved_live(tmp_path, monkeypatch) -> None:
    """10 prédictions live résolues (7 bonnes directions, 3 mauvaises) sur ^VIX à 5 jours."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    for i in range(7):
        db.add_predictions(conn, trial_id, fold_index=None, split="live",
                           ts=[f"2024-06-{i+1:02d}T00:00:00"], y_true=[1.0], y_pred=[3], y_proba=[0.6])
    for i in range(3):
        db.add_predictions(conn, trial_id, fold_index=None, split="live",
                           ts=[f"2024-06-{i+8:02d}T00:00:00"], y_true=[0.0], y_pred=[3], y_proba=[0.6])
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()


def test_hover_bubble_leads_with_the_direction_hit_rate(tmp_path, monkeypatch):
    _seed_resolved_live(tmp_path, monkeypatch)
    html = TestClient(app).get("/predictions").text
    # le taux de réussite en direction passe avant les tableaux, avec son pourcentage
    assert 'class="pop-line pop-hit">Bon sens au total : 7/10 (70 %)' in html
    # le dernier signal est une date, pas « 2024-06-10T00:00:00 »
    assert "<dd>2024-06-10</dd>" in html


def test_reading_rules_are_said_once_not_in_every_bubble(tmp_path, monkeypatch):
    _seed_resolved_live(tmp_path, monkeypatch)
    html = TestClient(app).get("/predictions").text
    # un seul « ? » de survol (la légende) : plus un par colonne d'horizon
    assert html.count('class="pop-trigger q-mark"') == 1
    assert 'class="pred-legend" data-keep' in html
    # la règle de lecture de la fiabilité live n'existe que dans ce « ? » (aria-label + contenu), pas dans les cases
    assert html.count("Part de bonnes directions") == 2


def test_tally_view_gives_the_direction_hit_rate_in_percent():
    from patrick.webapp.app import _tally_view

    tally = {"since": "2026-09-29T00:00:00", "pending": 3, "direction_n": 6, "direction_hits": 4, "matrix": {},
             "direction": {"up": {"up": 2, "down": 2}, "down": {"up": 0, "down": 2}}}
    assert _tally_view(tally)["direction_pct"] == 67
    assert _tally_view({**tally, "direction_n": 0, "direction_hits": 0})["direction_pct"] is None


def _seed_trained_outside_the_default_list(tmp_path, monkeypatch) -> None:
    """Modèles entraînés hors de la liste par défaut : un ETF du catalogue (XLK), un symbole inconnu du catalogue, un alpha."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    for run_id, target in (("rx", "XLK"), ("ru", "ZZZ.UNKNOWN"), ("ra", "AAA__alpha_BBB")):
        db.create_run(conn, run_id, target, 1, "snap1", "{}", "cfghash", "sha", 42)
        trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial_id)
        db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2024-06-01T00:00:00"],
                           y_true=[None], y_pred=[3], y_proba=[0.71])
        db.finish_run(conn, run_id, status="done", n_trials=1)
    conn.close()


def test_directional_groups_add_every_trained_asset_to_the_default_list(tmp_path, monkeypatch):
    from patrick.webapp.app import _directional_prediction_groups

    _seed_trained_outside_the_default_list(tmp_path, monkeypatch)
    conn = db.connect(str(tmp_path / "patrick.db"))
    groups = _directional_prediction_groups(conn)
    conn.close()

    defaults = [sym for items in D.DEFAULT_TARGET_GROUPS.values() for sym, _ in items]
    shown = [sym for items in groups.values() for sym, _ in items]
    assert shown[:len(defaults)] == defaults                      # les actifs par défaut, dans le même ordre
    assert "XLK" in [sym for sym, _ in next(items for name, items in groups.items() if name.startswith("ETFs sectoriels"))]
    assert groups["Autres actifs"] == [("ZZZ.UNKNOWN", "ZZZ.UNKNOWN")]
    assert "XLF" not in shown and "AAA__alpha_BBB" not in shown   # sans modèle ou alpha : pas dans le tableau directionnel
    assert len(shown) == len(set(shown))


def test_predictions_page_shows_trained_assets_outside_the_default_list(tmp_path, monkeypatch):
    _seed_trained_outside_the_default_list(tmp_path, monkeypatch)
    html = TestClient(app).get("/predictions").text

    assert 'href="/targets/XLK"' in html and "Autres actifs" in html and "ZZZ.UNKNOWN" in html
    assert 'href="/targets/XLF"' not in html and "AAA__alpha_BBB" not in html
    assert "Volatilité · VIX (S&amp;P 500)" in html                  # les actifs par défaut restent affichés, sous leur nom


def test_a_prediction_cell_carries_the_reliability_hook_and_the_api_draws_it(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    conn = db.connect(str(tmp_path / "patrick.db"))
    trial_id = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'run1'").fetchone()[0]
    conn.execute("UPDATE trial SET artifact_path = 'model.joblib' WHERE trial_id = ?", (trial_id,))      # un modèle exporté : il est en titre
    ts = [f"2023-{m:02d}-{d:02d}" for m in range(1, 4) for d in range(1, 29)]        # 84 jours hors échantillon avec probabilité
    p_up = [0.25 + 0.5 * (i % 10) / 9 for i in range(len(ts))]
    y_true = [3.0 if (i % 10) / 9 > 0.5 else 0.0 for i in range(len(ts))]               # les probabilités élevées se réalisent : bien calibré
    db.add_predictions(conn, trial_id, fold_index=2, split="test", ts=ts, y_true=y_true, y_pred=y_true, y_proba=[0.7] * len(ts), p_up=p_up)
    conn.close()
    client = TestClient(app)
    assert 'data-rel-target="^VIX" data-rel-horizon="5"' in client.get("/predictions").text
    data = client.get("/api/predictions/reliability", params={"target": "^VIX", "horizon": 5}).json()
    assert data["title"] == "Fiabilité de P(hausse)" and len(data["bins"]) >= 3 and "84 prédictions" in data["caption"]
    freqs = [b["freq"] for b in data["bins"]]
    assert freqs == sorted(freqs) and freqs[0] < 0.5 < freqs[-1]                        # croissant : la fiabilité se lit
    en = client.get("/api/predictions/reliability", params={"target": "^VIX", "horizon": 5, "lang": "en"}).json()
    assert en["title"] == "Reliability of P(up)"


def test_the_reliability_api_refuses_too_few_points_and_unknown_targets(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    client = TestClient(app)
    few = client.get("/api/predictions/reliability", params={"target": "^VIX", "horizon": 5}).json()
    assert few["bins"] == [] and "Pas assez" in few["none"]                              # 2 lignes de test : rien à tracer
    assert client.get("/api/predictions/reliability", params={"target": "NOPE", "horizon": 5}).status_code == 404
    assert client.get("/api/predictions/reliability", params={"target": "^VIX", "horizon": 0}).status_code == 404
