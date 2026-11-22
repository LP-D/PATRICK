"""CHANTIER D (feature/hrp-portfolio) : la section HRP ajoutee a
`/portfolio` (`webapp/app.py::portfolio_page`) rend correctement dans les
deux cas -- cache vide (message explicite, pas de crash) et cache peuple
(table de poids + annotation explicative). Isolation DB/DataStore comme
`test_history_webapp_smoke.py` (`PATRICK_DB_PATH`/`PATRICK_STORE_ROOT`),
sans worker separe (route read-only, pas de pipeline a lancer)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.webapp.app import app


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


def test_portfolio_page_renders_with_empty_hrp_cache(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    assert "Historique de prix insuffisant" in resp.text


def test_portfolio_page_renders_hrp_weights_table_when_cache_is_populated(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store = DataStore(root=str(tmp_path / "store"))
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2018-01-01", periods=400)
    for symbol in D.DEFAULT_UNIVERSE_YF_TICKERS[:3]:
        col = clean_symbol(symbol)
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(idx)))
        store.save(f"raw_{symbol}", pd.DataFrame({col: prices}, index=idx))

    client = TestClient(app)
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    # Marqueur ASCII (pas "Répartition", accentué) -- eviter tout artefact
    # d'encodage entre ce fichier de test et l'assertion Python sur Windows.
    assert "HRP" in resp.text
    assert "Actif" in resp.text  # en-tete de la table de poids (branche peuplee)
    for symbol in D.DEFAULT_UNIVERSE_YF_TICKERS[:3]:
        assert symbol in resp.text
