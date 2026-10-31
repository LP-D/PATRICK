"""Fiche d'un actif (`/targets/{symbole}`) et pages de classes d'actifs : le cadre s'ouvre sans lire les runs, les signaux, le tableau, les
actualités et les statistiques arrivent en fragments ; une classe sait dire le signal de chacun de ses actifs."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from page_support import FullPageClient

from patrick.config import asset_classes
from patrick.tracking import champions as trackchampions
from patrick.tracking import db
from patrick.webapp import asset_view, forms
from patrick.webapp.app import app


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    connection = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(connection, "snap1", "hash1", None, None, None)
    yield connection
    connection.close()


def _train_vix(conn) -> None:
    """^VIX : un run terminé à 5 jours, un signal du jour (classe 3 = hausse forte), un champion."""
    cfg = forms.default_config_dict()
    cfg["objective"].update(target_symbol="^VIX", horizons=[5])
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps(cfg), "cfghash", "sha", 42)
    trial = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial)
    db.add_predictions(conn, trial, fold_index=None, split="live", ts=["2024-06-01T00:00:00"], y_true=[None], y_pred=[3], y_proba=[0.71])
    db.add_fold_metrics(conn, trial, 1, "test", {"F1_dir": 0.6})
    db.add_predictions(conn, trial, fold_index=1, split="test", ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[3, 0], y_proba=[0.7, 0.7])
    db.finish_run(conn, "run1", status="done", n_trials=1)
    trackchampions.promote(conn, "^VIX", 5, "run1", trial, "test", 0.61)


# --------------------------------------------------------------------------- la fiche


def test_the_asset_page_opens_with_its_frame_and_loads_the_rest_after(conn):
    _train_vix(conn)
    page = TestClient(app).get("/targets/%5EVIX").text                    # le client simple ne suit pas les fragments
    assert 'id="marche"' in page and "asset-panel" in page and 'data-symbol="^VIX"' in page
    assert 'data-lazy-url="/fragments/asset-signals/%5EVIX"' in page
    assert 'data-lazy-url="/fragments/news-feed?symbol=%5EVIX"' in page
    assert 'href="/indices"' in page and "Yahoo Finance" in page          # la classe, la source
    assert 'href="/ml?target=%5EVIX"' in page and 'href="/dl?target=%5EVIX"' in page and 'href="/rl?target=%5EVIX"' in page
    assert "Aucune stratégie du fonds" in page
    assert "as-signals" not in page                                       # le tableau des signaux n'est pas calculé pour ouvrir la page


def test_the_signals_fragment_gives_one_signal_per_horizon_with_the_champion(conn):
    _train_vix(conn)
    html = FullPageClient(app).get("/fragments/asset-signals/%5EVIX").text
    assert "Hausse forte" in html and "5j" in html                         # le signal du jour, à 5 jours
    assert 'href="/runs/run1/detail"' in html and "RandomForest" in html and "F1 0.610" in html
    assert "1j" not in html.split("<tbody>")[1].split("</tbody>")[0].split("5j")[0]      # seuls les horizons qui ont un signal ou un champion


def test_an_asset_without_a_model_still_has_a_page_with_a_way_to_launch_one(conn):
    client = FullPageClient(app)
    resp = client.get("/targets/GC=F")
    assert resp.status_code == 200
    assert "Aucun signal" in resp.text and "/ml?profile=quick&amp;target=GC%3DF" in resp.text.replace("&amp;amp;", "&amp;")
    assert 'data-symbol="GC=F"' in resp.text


def test_a_stock_page_shows_the_market_its_features_are_computed_against(conn):
    html = TestClient(app).get("/targets/MC.PA").text
    assert 'id="contexte"' in html and 'href="/targets/%5EFCHI"' in html and 'href="/targets/%5EGSPC"' in html      # indice de sa place, S&P 500
    assert 'href="/targets/%5EGDAXI"' in html                                                                  # composite zone euro
    assert 'id="contexte"' not in TestClient(app).get("/targets/%5EVIX").text                                   # seulement pour une action


def test_an_unknown_asset_is_a_404(conn):
    client = TestClient(app)
    assert client.get("/targets/NOPE").status_code == 404
    assert client.get("/fragments/asset-signals/NOPE").status_code == 404


def test_the_asset_page_is_available_in_english(conn):
    _train_vix(conn)
    html = FullPageClient(app).get("/targets/%5EVIX?lang=en").text
    assert "Signals by horizon" in html and "Signaux par horizon" not in html and "In the funds" in html
    assert "Launch as machine learning" in html


def test_the_asset_helpers_find_the_class_the_group_and_the_neighbours():
    group, cls = asset_view.locate("BTC-USD", forms.TARGET_GROUPS)
    assert cls == "crypto" and group in asset_classes.BY_KEY["crypto"].groups
    assert asset_view.locate("NOPE", forms.TARGET_GROUPS) == (None, None)
    peers = asset_view.peers("BTC-USD", group, forms.TARGET_GROUPS)
    assert "BTC-USD" not in peers and len(peers) <= asset_view.PEERS_LIMIT
    assert asset_view.peers("BTC-USD", None, forms.TARGET_GROUPS) == []


# --------------------------------------------------------------------------- les pages de classes


def test_a_class_page_opens_with_its_frame_and_loads_its_table_after(conn):
    page = TestClient(app).get("/indices").text
    assert 'data-lazy-url="/fragments/asset-class/indices?min_history_years=10"' in page
    assert 'class="cls-row"' not in page and "cls-search" not in page
    body = TestClient(app).get("/fragments/asset-class/indices").text
    assert 'data-class-key="indices"' in body and 'class="cls-signals"' in body and 'data-symbol="^GSPC"' in body
    assert 'href="/targets/^GSPC"' in body


def test_the_class_fragment_checks_its_arguments(conn):
    client = TestClient(app)
    assert client.get("/fragments/asset-class/nope").status_code == 404
    assert client.get("/fragments/asset-class/indices?min_history_years=1").status_code == 400


def test_the_class_signals_api_gives_the_signal_of_each_horizon_of_each_asset(conn):
    _train_vix(conn)
    signals = TestClient(app).get("/api/class-signals/indices").json()
    assert signals["^VIX"] == [[5, "▲▲", "ok", "Hausse forte"]]
    assert "^GSPC" not in signals                                          # pas de modèle, pas de repère
    assert "^VIX" not in TestClient(app).get("/api/class-signals/crypto").json()
    english = TestClient(app).get("/api/class-signals/indices?lang=en").json()
    assert english["^VIX"][0][3] != "Hausse forte"
    assert TestClient(app).get("/api/class-signals/nope").status_code == 404
