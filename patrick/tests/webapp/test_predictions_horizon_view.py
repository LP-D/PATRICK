"""Vue « Par horizon » de `/predictions?view=horizon` : signaux regroupés par horizon puis par classe d'actifs, avec l'avantage live."""
from __future__ import annotations

from datetime import date, timedelta

from page_support import FullPageClient as TestClient

from patrick.tracking import db
from patrick.webapp.app import app


def _seed(tmp_path, monkeypatch, days: int = 24) -> None:
    """Un ETF (SPY) toujours bien prédit, une crypto (BTC-USD) toujours mal prédite, à l'horizon 1, `days` jours jugés."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    start = date(2026, 9, 1)
    stamps = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    ups = [i % 2 == 0 for i in range(days)]
    for run_id, target, right in (("r_spy", "SPY", True), ("r_btc", "BTC-USD", False)):
        db.create_run(conn, run_id, target, 1, "snap1", "{}", run_id, "sha", 1)
        trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial_id)
        db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
        y_true = [1.0 if u else 0.0 for u in ups]
        y_pred = [3 if (u == right) else 0 for u in ups]
        db.add_predictions(conn, trial_id, None, "live", ts=stamps, y_true=y_true, y_pred=y_pred, y_proba=[0.7] * days)
        db.finish_run(conn, run_id, status="done", n_trials=1)
    conn.close()


def test_horizon_view_page_keeps_the_frame_and_loads_its_fragment(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    page = TestClient(app).get("/predictions?view=horizon")
    assert page.status_code == 200
    assert "view=horizon" in page.text and "Par horizon" in page.text
    assert "/fragments/predictions-horizon" in page.text


def test_horizon_view_groups_signals_by_horizon_then_class(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    text = TestClient(app).get("/predictions?view=horizon").text
    assert 'id="edge-matrix"' in text and 'id="edge-h1"' in text
    # Les deux classes présentes ont leur table ; les actifs renvoient vers leur fiche.
    assert "ETF" in text and "Cryptos" in text
    assert '<a href="/targets/SPY"' in text and '<a href="/targets/BTC-USD"' in text
    # ETF toujours juste = avantage probable ; crypto toujours fausse = sous le hasard.
    assert 'edge-verdict">Avantage probable' in text and 'edge-verdict">Sous le hasard' in text
    assert "100 %" in text and "0 %" in text


def test_horizon_view_says_too_early_without_enough_independent_observations(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, days=4)
    text = TestClient(app).get("/predictions?view=horizon").text
    assert 'edge-verdict">Trop tôt' in text
    assert 'edge-verdict">Avantage probable' not in text


def test_horizon_view_empty_database_is_an_explicit_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    resp = TestClient(app).get("/predictions?view=horizon")
    assert resp.status_code == 200
    assert "Aucun signal live jugé" in resp.text


def test_alpha_kind_ignores_the_horizon_view(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    text = TestClient(app).get("/predictions?kind=alpha&view=horizon").text
    assert "/fragments/predictions-horizon" not in text
    assert 'class="kind-tabs view-tabs"' not in text


def test_default_view_is_unchanged_and_offers_the_horizon_tab(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    text = TestClient(app).get("/predictions").text
    assert "/fragments/predictions?kind=directional" in text
    assert "/predictions?view=horizon" in text
