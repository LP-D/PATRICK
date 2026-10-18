"""Section Black-Litterman de `/portfolio` : arrive par fragment après le cadre (la page s'ouvre tout de suite), explique son
absence de vue, et montre le tilt par rapport au portefeuille de référence quand des probabilités calibrées existent."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from page_support import FullPageClient

from patrick.config import defaults as D
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.tracking import db
from patrick.webapp.app import app


def _isolate(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    return path


def _prices(tmp_path, n=4):
    store = DataStore(root=str(tmp_path / "store"))
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2018-01-01", periods=400)
    symbols = D.DEFAULT_UNIVERSE_YF_TICKERS[:n]
    for symbol in symbols:
        store.save(f"raw_{symbol}", pd.DataFrame(
            {clean_symbol(symbol): 100 * np.cumprod(1 + rng.normal(0, 0.01, len(idx)))}, index=idx))
    return symbols


def _live_view(db_path, run_id, target, horizon, p_up):
    conn = db.connect(db_path)
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, target, horizon, f"snap_{run_id}",
                  json.dumps({"name": run_id, "models": {"calibration": True}}), "h", "sha", 1)
    db.finish_run(conn, run_id, status="done", n_trials=1)
    trial = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    ts = pd.Timestamp.now().strftime("%Y-%m-%d")
    db.add_predictions(conn, trial, 1, "live", [ts], [None], [3], [0.6], p_up=[p_up])
    conn.close()


def test_the_page_opens_without_waiting_for_black_litterman(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    resp = TestClient(app).get("/portfolio")
    assert resp.status_code == 200
    assert "Black-Litterman" in resp.text
    assert "/fragments/portfolio-bl" in resp.text            # chargé après coup
    assert "Probabilité de hausse" not in resp.text           # le tableau n'est pas dans le cadre


def test_without_calibrated_probabilities_the_fragment_says_what_is_missing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _prices(tmp_path)
    resp = TestClient(app).get("/fragments/portfolio-bl")
    assert resp.status_code == 200
    assert "calibr" in resp.text.lower()
    assert "Poids Black-Litterman" not in resp.text


def test_fragment_lists_the_tilt_against_the_reference_portfolio(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    symbols = _prices(tmp_path)
    _live_view(path, "r1", symbols[0], 5, 0.9)
    _live_view(path, "r2", symbols[1], 5, 0.1)
    resp = TestClient(app).get("/fragments/portfolio-bl", params={"horizon": 5})
    assert resp.status_code == 200
    for header in ("Poids de référence", "Poids Black-Litterman", "Probabilité de hausse"):
        assert header in resp.text
    assert symbols[0] in resp.text and symbols[1] in resp.text
    assert "90" in resp.text and "10" in resp.text           # probabilités affichées en pourcent


def test_full_page_shows_the_fragment_content(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    symbols = _prices(tmp_path)
    _live_view(path, "r1", symbols[0], 5, 0.9)
    resp = FullPageClient(app).get("/portfolio")
    assert resp.status_code == 200 and "Poids Black-Litterman" in resp.text


def test_an_unknown_horizon_is_refused(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert TestClient(app).get("/fragments/portfolio-bl", params={"horizon": 9999}).status_code == 400
