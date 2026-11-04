"""Page /econometrie et API /api/econometrics/* : vraies routes FastAPI, séries synthétiques injectées à la place du réseau, cache de résultats
dans un dossier temporaire (jamais le vrai `~/.patrick`)."""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.econometrics import mean_models as M
from patrick.econometrics import simulate as SIM
from patrick.webapp import econometrics_cache as EC
from patrick.webapp import econometrics_routes as ER
from patrick.webapp import exploration_routes as E
from patrick.webapp.app import app

SYM = "^GSPC"
FRED = "CPIAUCSL"


def _levels(n=1400, seed=1):
    r = SIM.garch11(n, 0.05, 0.10, 0.85, seed=seed) / 100.0
    return pd.Series(100 * np.exp(np.cumsum(r.to_numpy())), index=r.index)


def _ohlc(close):
    rng = np.random.default_rng(3)
    o = close.shift(1).fillna(close.iloc[0])
    spread = np.abs(rng.normal(0, 0.004, len(close))) * close
    return pd.DataFrame({"Open": o, "High": np.maximum(o, close) + spread, "Low": np.minimum(o, close) - spread, "Close": close})


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "cache"))
    lv = _levels()
    monthly = pd.Series(np.cumsum(np.random.default_rng(5).normal(0.2, 0.3, 300)) + 100, index=pd.date_range("2000-01-31", periods=300, freq="ME"))

    def fake(symbol, source):
        if symbol == "BROKEN":
            raise RuntimeError("fichier de cache illisible")
        return monthly if source == "fred" else lv

    monkeypatch.setattr(E, "loader", fake)
    monkeypatch.setattr(ER, "ohlc_loader", lambda symbol: _ohlc(lv))
    ER.clear_cache()
    yield
    ER.clear_cache()


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


def _get(client, study, **params):
    base = {"symbol": SYM, "transform": "logret", "start": ""}
    base.update(params)
    return client.get(f"/api/econometrics/{study}", params=base)


# ---------------------------------------------------------------- cache de résultats
def test_cache_key_is_stable_and_changes_with_the_data_and_the_spec():
    s = _levels(300)
    a = EC.cache_key(study="mean", fp=EC.fingerprint(s), p={"max_p": 2})
    assert a == EC.cache_key(p={"max_p": 2}, fp=EC.fingerprint(s), study="mean")
    assert a != EC.cache_key(study="mean", fp=EC.fingerprint(s), p={"max_p": 3})
    s2 = s.copy()
    s2.iloc[-1] *= 1.01
    assert a != EC.cache_key(study="mean", fp=EC.fingerprint(s2), p={"max_p": 2})


def test_cache_round_trip_survives_a_corrupt_file_and_evicts_the_oldest(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_CACHE_ROOT", str(tmp_path / "c"))
    EC.save("abc", {"x": [1, 2, None]})
    assert EC.load("abc") == {"x": [1, 2, None]}
    (EC.directory() / "bad.json.gz").write_bytes(b"pas du gzip")
    assert EC.load("bad") is None and EC.load("absent") is None
    monkeypatch.setattr(EC, "MAX_ENTRIES", 5)
    for i in range(12):
        EC.save(f"k{i}", {"i": i})
    assert len(list(EC.directory().glob("*.json.gz"))) <= 5 + EC.EVICT_SLACK


# ---------------------------------------------------------------- page
def test_the_page_lists_the_catalog_and_the_six_tabs(client):
    html = client.get("/econometrie").text
    assert 'id="eco-series"' in html and 'value="^GSPC"' in html
    for tab in ("unitroot", "dependence", "mean", "variance", "regimes", "forecast"):
        assert f'data-panel="{tab}"' in html


def test_the_page_is_in_the_navigation_next_to_exploration(client):
    html = client.get("/exploration").text
    assert 'href="/econometrie"' in html


# ---------------------------------------------------------------- série
def test_series_meta_describes_frequency_transform_and_sample(client):
    body = _get(client, "series").json()
    meta = body["meta"]
    assert meta["periods_per_year"] == 252 and meta["periodicity"] == "daily" and meta["transform"]["kind"] == "logret"
    assert meta["n_obs"] == len(body["result"]["dates"]) == len(body["result"]["values"])


def test_a_monthly_fred_series_is_monthly_and_offers_the_seasonal_period(client):
    meta = _get(client, "series", symbol=FRED, transform="diff").json()["meta"]
    assert meta["periodicity"] == "monthly" and meta["periods_per_year"] == 12 and meta["seasonal_period"] == 12


def test_the_window_selects_the_sample(client):
    meta = _get(client, "series", start="2013-01-01").json()["meta"]
    assert meta["start"] >= "2013-01-01" and meta["n_obs"] < 1400


# ---------------------------------------------------------------- études
def test_unitroot_reads_log_returns_as_stationary_and_includes_the_break_test(client):
    res = _get(client, "unitroot").json()["result"]
    assert res["unit_root"]["verdict"] == "stationary" and {"adf", "kpss", "pp", "dfgls"} <= set(res["unit_root"]["tests"])
    assert "break_date" in res["zivot_andrews"] and res["variance_ratio"]["rows"]


def test_dependence_finds_arch_effects_in_the_simulated_returns(client):
    res = _get(client, "dependence", nlags=20).json()["result"]
    assert res["arch_lm_p"] < 0.001 and "bds" in res


def test_mean_grid_says_nothing_beats_the_constant_on_returns_with_a_constant_mean(client):
    res = _get(client, "mean", max_p=1, max_q=1).json()["result"]
    assert res["verdict"] == "no_better_than_constant" and res["n_specs"] == 4 and "gph" in res


def test_variance_detail_with_a_range_based_proxy_overlays_realized_volatility(client):
    res = _get(client, "variance", model="gjr", dist="t", proxy="parkinson").json()["result"]
    assert res["model"] == "gjr" and res["converged"] in (True, False) and "realized_vol" in res and res["corr_with_realized"] is not None


def test_variance_grid_reports_every_requested_combination(client):
    res = _get(client, "variance_grid", models="garch,gjr", dists="normal,t").json()["result"]
    assert res["n_specs"] == 4 and len(res["rows"]) == 4


def test_har_uses_the_requested_proxy(client):
    res = _get(client, "har", proxy="parkinson").json()["result"]
    assert set(res["params"]) == {"const", "daily", "weekly", "monthly"}


def test_regimes_markov_and_hmm_both_answer(client):
    ms = _get(client, "regimes", method="ms", start="2013-01-01").json()["result"]
    hmm = _get(client, "regimes", method="hmm", start="2013-01-01").json()["result"]
    assert ms["verdict"] in ("regimes_supported", "single_regime_enough", "not_converged") and hmm["causal"] is True


def test_forecast_compares_models_out_of_sample_and_backtests_the_var(client):
    res = _get(client, "forecast", specs="garch|normal,riskmetrics", min_train=500, refit_every=150, reps=100).json()["result"]
    assert res["comparison"]["n_models"] == 2 and "garch|normal" in res["var_backtest"] and res["proxy"] == "squared_return"


# ---------------------------------------------------------------- cache, erreurs, garde-fous
def test_the_second_identical_request_comes_from_the_cache_and_does_not_recompute(client, monkeypatch):
    calls = []
    real = M.fit_arma_grid
    monkeypatch.setattr(M, "fit_arma_grid", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    first = _get(client, "mean", max_p=1, max_q=0).json()
    second = _get(client, "mean", max_p=1, max_q=0).json()
    assert first["cached"] is False and second["cached"] is True and len(calls) == 1
    assert first["result"] == second["result"]
    files = list(EC.directory().glob("*.json.gz"))
    assert len(files) == 1 and json.loads(gzip.decompress(files[0].read_bytes()))["study"] == "mean"


def test_a_different_parameter_is_a_different_cache_entry(client):
    _get(client, "mean", max_p=1, max_q=0)
    assert _get(client, "mean", max_p=0, max_q=1).json()["cached"] is False


@pytest.mark.parametrize("params,status,fragment", [
    ({"symbol": "NOPE"}, 400, "inconnu"),
    ({"symbol": "BROKEN"}, 400, "BROKEN"),
    ({"transform": "cubic"}, 400, "cubic"),
    ({"max_p": 9}, 400, "max_p"),
    ({"seasonal": 1}, 400, "mensuel"),
])
def test_bad_requests_return_a_readable_error(client, params, status, fragment):
    study = "mean" if ("max_p" in params or "seasonal" in params) else "series"
    r = _get(client, study, **params)
    assert r.status_code == status and fragment in r.json()["error"]


def test_a_range_based_transform_on_a_series_without_ohlc_says_so(client):
    r = _get(client, "series", symbol=FRED, transform="parkinson")
    assert r.status_code == 400 and "OHLC" in r.json()["error"]


def test_an_unknown_study_is_a_404(client):
    assert client.get("/api/econometrics/nope", params={"symbol": SYM}).status_code == 404


def test_a_too_short_window_is_refused(client):
    r = _get(client, "unitroot", start="2019-12-01")
    assert r.status_code == 400 and "minimum" in r.json()["error"].lower()
