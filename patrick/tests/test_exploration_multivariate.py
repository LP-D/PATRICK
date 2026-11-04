"""Onglet « Multivarié » de /exploration : VAR (réponses impulsionnelles, décomposition de la variance) et cointégration de Johansen avec VECM,
sur la sélection d'actifs de la page (séries synthétiques injectées à la place du réseau)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import exploration_routes as E
from patrick.webapp.app import app

SYMS = ["^GSPC", "^NDX", "XLK"]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    E.clear_cache()
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=900)
    common = np.cumsum(rng.normal(0, 0.01, 900))                     # tendance stochastique commune : les trois séries sont cointégrées

    def fake(symbol, source):
        own = np.zeros(900)
        for t in range(1, 900):
            own[t] = 0.5 * own[t - 1] + rng.normal(0, 0.01)
        return pd.Series(100 * np.exp(common * (1.0 + 0.2 * SYMS.index(symbol)) + own), index=idx)

    monkeypatch.setattr(E, "loader", fake)
    yield
    E.clear_cache()


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _q(**extra):
    base = {"symbols": ",".join(SYMS), "freq": "D", "transform": "auto"}
    base.update(extra)
    return base


def test_the_page_has_a_multivariate_tab(client):
    assert 'data-panel="multi"' in client.get("/exploration").text


def test_var_returns_orders_stability_irf_and_fevd_for_the_selection(client):
    body = client.get("/api/exploration/var", params=_q(maxlag=3, periods=6)).json()["result"]
    assert body["names"] == SYMS and body["irf_order"] == SYMS and body["stable"] is True
    assert np.array(body["irf"]).shape == (7, 3, 3) and np.array(body["fevd"]).shape == (7, 3, 3)
    np.testing.assert_allclose(np.array(body["fevd"]).sum(axis=2), 1.0, atol=1e-6)


def test_var_needs_two_assets(client):
    r = client.get("/api/exploration/var", params=_q(symbols="^GSPC"))
    assert r.status_code == 400 and "au moins 2" in r.json()["error"]


def test_johansen_finds_the_common_trend_and_fits_a_vecm_on_the_chosen_rank(client):
    body = client.get("/api/exploration/johansen", params=_q(k_ar_diff=1, det_order=0)).json()["result"]
    assert body["names"] == SYMS and body["rank"] >= 1 and len(body["rows"]) == 3
    assert body["vecm"]["rank"] == body["rank"] and len(body["vecm"]["ect"]["values"]) > 500


def test_johansen_reports_a_full_rank_without_a_vecm(client):
    body = client.get("/api/exploration/johansen", params=_q(symbols="^GSPC,^NDX")).json()["result"]
    assert "rank" in body and ("vecm" in body) == (1 <= body["rank"] < 2)
