"""HMM market state for analysis (decision of 2026-09-26: the HMM serves regime
models and market-state reading, not ML features). The synthesis page's
"Classification de régime" card was an empty state ("never run in
production"); it now shows, per market, the current HMM regime, since when,
and realised volatility.

Two states (calm / stress), on percent log returns, not the calm / normal /
stress terciles of `detect_regime` (built to split training data into
balanced thirds). Measured on real prices (2000-2026, six markets): with 3-4
states the calm and normal states overlap so much that the most probable
state changed every 1-8 sessions on average, and terciles of P(stress)
labelled WTI "stress" at P(stress) = 0.000; with 2 states the average
regime lasts 14-26 sessions for five markets (bitcoin still flips every ~5).

Descriptive, not a backtested signal: the HMM parameters are fitted on the
whole history up to today; only the state probability is filtered (causal
given those parameters).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick.tracking import market_state as ms
from patrick.webapp import market_regime
from patrick.webapp.app import app


def _calm_then_stress(n_calm=700, n_stress=120, seed=0):
    rng = np.random.default_rng(seed)
    r = np.r_[rng.normal(0.0003, 0.006, n_calm), rng.normal(-0.001, 0.03, n_stress)]
    idx = pd.bdate_range("2020-01-01", periods=len(r))
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)


def test_summary_reads_the_current_stress_episode():
    s = _calm_then_stress()
    out = ms.summarize_asset("X", "Actif X", s)
    assert out["status"] == "ok"
    assert out["regime"] == "stress" and out["stress_prob"] > 0.5
    assert pd.Timestamp(out["since"]) >= s.index[680]             # the episode, not the calm years
    assert out["share_stress_63"] > 0.5
    assert out["vol_stress"] > 3 * out["vol_calm"]                # the two states are well separated
    assert out["vol_21d"] > out["vol_long"]
    assert out["as_of"] == str(s.index[-1].date())


def test_calm_market_is_labelled_calm_with_a_long_run():
    rng = np.random.default_rng(1)
    r = np.r_[rng.normal(0, 0.03, 150), rng.normal(0.0003, 0.006, 400)]     # stress, then a long calm
    s = pd.Series(100 * np.exp(np.cumsum(r)), index=pd.bdate_range("2019-01-01", periods=len(r)))
    out = ms.summarize_asset("X", "Actif X", s)
    assert out["regime"] == "calme" and out["sessions_in_regime"] > 100


def test_non_positive_prices_are_dropped_not_turned_into_returns():
    s = _calm_then_stress()
    s.iloc[400] = -5.0                                            # WTI, 2020-04-20
    out = ms.summarize_asset("X", "Actif X", s)
    assert out["status"] == "ok" and out["vol_stress"] < 200      # no state devoted to a -300 % "return"


def test_short_history_is_reported_not_guessed():
    s = _calm_then_stress(n_calm=50, n_stress=20)
    out = ms.summarize_asset("X", "Actif X", s)
    assert out["status"] == "insufficient"
    assert out["regime"] is None


def test_overview_caches_per_symbol_and_date_and_isolates_failures():
    calls = []
    s = _calm_then_stress()

    def loader(symbol):
        calls.append(symbol)
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return s

    cache = ms.MarketStateCache()
    assets = (("A", "Actif A"), ("BAD", "Actif cassé"))
    first = cache.overview(loader, assets)
    second = cache.overview(loader, assets)
    assert [r["status"] for r in first] == ["ok", "error"]
    assert "provider down" in first[1]["error"]
    assert second[0] is first[0]                      # same (symbol, date): HMM not refitted
    assert calls.count("A") == 2                      # prices re-read (cheap), model not refitted


def test_default_markets_use_brent_not_wti():
    symbols = [s for s, _ in ms.ASSETS]
    assert "BZ=F" in symbols and "CL=F" not in symbols


def test_api_returns_the_background_cache(monkeypatch):
    monkeypatch.setattr(market_regime, "_state", {"rows": [{"symbol": "^GSPC", "status": "ok"}],
                                                   "updated_at": "2026-09-26 10:00", "error": None,
                                                   "computing": False})
    res = TestClient(app).get("/api/market-state")
    assert res.status_code == 200
    assert res.json()["rows"][0]["symbol"] == "^GSPC"


def test_synthesis_page_renders_the_market_state_panel():
    html = TestClient(app).get("/").text
    assert 'id="market-state"' in html
    assert "jamais exécutée en production" not in html
