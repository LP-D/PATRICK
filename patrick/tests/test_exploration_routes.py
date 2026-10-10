"""Page /exploration et API /api/exploration/* : vraies routes FastAPI, séries synthétiques injectées à la place du réseau
(`exploration_routes.loader`), base SQLite isolée."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import exploration_routes as E
from patrick.webapp import forms
from patrick.webapp.app import app

SYMS = ["^GSPC", "^NDX", "GC=F", "XLK"]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    E.clear_cache()
    yield
    E.clear_cache()


@pytest.fixture
def calls(monkeypatch):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=1500)
    common = rng.normal(0, 0.008, 1500)
    seen: list[str] = []

    def fake(symbol, source):
        seen.append(symbol)
        if symbol == "BROKEN":
            raise RuntimeError("fichier de cache illisible")
        own = rng.normal(0, 0.006, 1500)
        return pd.Series(100 * np.exp(np.cumsum(0.7 * common + own)), index=idx)

    monkeypatch.setattr(E, "loader", fake)
    return seen


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _q(**extra):
    base = {"symbols": ",".join(SYMS), "freq": "D", "transform": "auto", "start": "2018-06-01"}
    base.update(extra)
    return base


def test_the_page_lists_every_target_group_and_the_presets(client):
    html = client.get("/exploration").text
    assert "Exploration" in html and 'id="exp-assets"' in html
    assert 'value="^GSPC"' in html and 'value="BAMLH0A0HYM2"' in html
    assert 'data-symbols="^GSPC,^NDX,^STOXX50E,^GDAXI,^FTSE,^N225"' in html
    assert "/static/exploration.js" in html
    assert 'role="tablist"' in html and html.count('role="tabpanel"') == 6


def test_the_page_is_in_the_english_interface_without_leaking_keys(client):
    client.cookies.set("patrick_lang", "en")
    html = client.get("/exploration").text
    assert "Link between two assets" in html
    visible = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL)
    assert not re.search(r"\bexp_[a-z_]+", visible)


def test_every_preset_symbol_is_a_known_target():
    for key, symbols in E.PRESETS:
        assert sum(1 for s in symbols if s in forms.TARGET_SOURCE_BY_SYMBOL) >= 2, key


def test_the_catalog_endpoint_carries_the_periodicity_of_fred_series(client):
    groups = client.get("/api/exploration/catalog").json()["groups"]
    items = {i["symbol"]: i for g in groups for i in g["items"]}
    assert items["^GSPC"]["periodicity"] == "daily" and items["^GSPC"]["source"] == "yfinance"
    assert items["CPIAUCSL"]["source"] == "fred" and items["CPIAUCSL"]["periodicity"] in ("monthly", "quarterly")


@pytest.mark.parametrize("study, extra, keys", [
    ("correlation", {}, {"labels", "matrix", "n_obs", "significant"}),
    ("describe", {}, {"rows", "n_obs"}),
    ("stationarity", {}, {"rows"}),
    ("pca", {"n_components": 3}, {"components", "first_factor_share"}),
    ("memory", {"a": "^GSPC", "nlags": 10}, {"acf", "pacf", "arch_lm_p"}),
    ("seasonality", {"a": "^GSPC"}, {"rows", "omnibus_p"}),
    ("rolling", {"a": "^GSPC", "b": "^NDX", "window": 60}, {"dates", "values", "noise_band"}),
    ("leadlag", {"a": "^GSPC", "b": "^NDX", "maxlag": 5}, {"lags", "values", "best_lag"}),
    ("granger", {"a": "^GSPC", "b": "^NDX", "maxlag": 3}, {"a_to_b", "b_to_a"}),
    ("cointegration", {"a": "^GSPC", "b": "^NDX"}, {"p_value", "hedge_ratio", "zscore"}),
    ("tail", {"a": "^GSPC", "b": "^NDX", "q": 0.05}, {"lower", "upper", "lower_ratio"}),
    ("beta", {"a": "XLK", "b": "^GSPC", "window": 60}, {"beta", "alpha_annualized", "rolling_beta"}),
])
def test_every_study_answers_with_its_meta_and_result(client, calls, study, extra, keys):
    resp = client.get(f"/api/exploration/{study}", params=_q(**extra))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["study"] == study
    assert body["meta"]["n_assets"] == 4 and body["meta"]["freq"] == "D" and body["meta"]["n_obs"] > 100
    assert body["meta"]["start"] >= "2018-06-01"
    assert keys <= set(body["result"]), set(body["result"])


def test_a_second_study_on_the_same_selection_does_not_reload_anything(client, calls):
    client.get("/api/exploration/correlation", params=_q())
    first = len(calls)
    assert first == 4
    client.get("/api/exploration/describe", params=_q())
    client.get("/api/exploration/stationarity", params=_q())
    assert len(calls) == first                                   # panneau servi depuis la mémoire
    client.get("/api/exploration/correlation", params=_q(freq="W"))
    assert len(calls) == first + 4                               # autre fréquence : autre panneau


def test_bad_requests_are_readable_400s_and_unknown_study_is_404(client, calls):
    assert client.get("/api/exploration/nope", params=_q()).status_code == 404
    r = client.get("/api/exploration/correlation", params=_q(symbols="NOT_A_TICKER,^GSPC"))
    assert r.status_code == 400 and "Symbole inconnu" in r.json()["error"]
    assert client.get("/api/exploration/correlation", params=_q(symbols="")).status_code == 400
    assert client.get("/api/exploration/correlation", params=_q(freq="X")).status_code == 400
    assert client.get("/api/exploration/correlation", params=_q(start="hier")).status_code == 400
    r = client.get("/api/exploration/rolling", params=_q(a="^GSPC"))
    assert r.status_code == 400 and "« b »" in r.json()["error"]
    r = client.get("/api/exploration/granger", params=_q(a="^GSPC", b="^GSPC"))
    assert r.status_code == 400 and "différents" in r.json()["error"]
    r = client.get("/api/exploration/correlation", params=_q(method="cosine"))
    assert r.status_code == 400


def test_an_asset_that_fails_to_load_is_reported_not_fatal(client, monkeypatch, calls):
    monkeypatch.setitem(forms.TARGET_SOURCE_BY_SYMBOL, "BROKEN", "yfinance")
    resp = client.get("/api/exploration/correlation", params=_q(symbols=",".join([*SYMS, "BROKEN"])))
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["n_assets"] == 4 and "BROKEN" in meta["dropped"] and "illisible" in meta["dropped"]["BROKEN"]
    assert any("Exclus : BROKEN" in w for w in meta["warnings"])
    err = client.get("/api/exploration/rolling", params=_q(symbols=",".join([*SYMS, "BROKEN"]), a="^GSPC", b="BROKEN"))
    assert err.status_code == 400 and "n'a pas pu être chargé" in err.json()["error"]


def test_a_monthly_macro_series_needs_the_monthly_frequency(client, monkeypatch, calls):
    monthly_idx = pd.date_range("2005-01-31", periods=240, freq="ME")
    base = E.loader

    def with_macro(symbol, source):
        if symbol == "CPIAUCSL":
            return pd.Series(np.linspace(100, 160, 240), index=monthly_idx)
        return base(symbol, source)

    monkeypatch.setattr(E, "loader", with_macro)
    params = _q(symbols="^GSPC,CPIAUCSL", start="2018-01-01")
    daily = client.get("/api/exploration/describe", params=params).json()
    assert daily["meta"]["n_assets"] == 1 and "CPIAUCSL" in daily["meta"]["dropped"]
    monthly = client.get("/api/exploration/describe", params={**params, "freq": "M"}).json()
    assert monthly["meta"]["n_assets"] == 2 and monthly["meta"]["periods_per_year"] == 12
