"""Régime de marché du jour (A11) : la classification de phase9 sur VIX et S&P 500, et son fragment sur /fonds."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.fund import regime


def _payload(values, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=len(values))
    return {"dates": [d.strftime("%Y-%m-%d") for d in idx], "closes": list(values)}


def _calm_market(n=400):
    rng = np.random.default_rng(1)
    px = 4000 * np.exp(np.cumsum(0.0006 + 0.004 * rng.standard_normal(n)))
    vix = np.r_[np.full(n - 30, 18.0), np.full(30, 12.0)]           # VIX au plus bas de l'année à la fin
    return _payload(vix), _payload(px)


def test_calm_regime_on_a_quiet_rising_market():
    vix, px = _calm_market()
    out = regime.current(loader=lambda s: vix if s == regime.VIX else px)
    assert out["label"] == "CALM" and out["vix"] == pytest.approx(12.0) and out["triggers"] == []
    assert out["days_in_regime"] >= 1 and sum(out["recent"].values()) == regime.RET_WINDOW


def test_crash_regime_after_a_sell_off():
    vix, px = _calm_market()
    px["closes"][-20:] = [c * (1 - 0.006 * (i + 1)) for i, c in enumerate(px["closes"][-20:])]   # -12 % en 20 séances
    vix["closes"][-5:] = [55.0] * 5
    out = regime.current(loader=lambda s: vix if s == regime.VIX else px)
    assert out["label"] == "CRASH" and out["ret20"] < -0.08
    assert {"vix", "ret20"} <= set(out["triggers"])


def test_short_or_missing_history_gives_none():
    vix, px = _calm_market(100)
    assert regime.current(loader=lambda s: vix if s == regime.VIX else px) is None
    assert regime.current(loader=lambda s: {"dates": [], "closes": []}) is None


def test_fragment_shows_the_regime_or_a_quiet_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    from patrick.webapp.app import app

    vix, px = _calm_market()
    monkeypatch.setattr(regime, "current", lambda loader=None: regime.classify(regime._series(vix), regime._series(px)))
    client = TestClient(app)
    text = client.get("/fragments/market-regime").text
    assert "Régime de marché" in text and "calme" in text and "le pilote n&#39;en tient pas compte" in text
