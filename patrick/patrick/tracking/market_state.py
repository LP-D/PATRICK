"""Market state read by the HMM (decision of 2026-09-26: the HMM serves regime
models and market-state analysis, no longer ML features).

Per market: `features.regime_detection.detect_regime` (Gaussian HMM on daily
returns, number of states chosen by BIC among 2-4), then the current label --
calm / normal / stress are the terciles of the filtered probability of the
highest-variance state over the asset's OWN history -- since when, the share
of the last quarter spent in stress, and realised volatility (21 sessions vs
the whole history, annualised).

Descriptive, not a backtested signal: the HMM parameters are fitted on the
whole history up to today; only the state probability is filtered (causal
given those parameters). A fit costs ~12 s per market on 20+ years of data,
hence `MarketStateCache`: one fit per (symbol, last price date).
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable

import pandas as pd

from patrick.features._utils import safe_pct_change
from patrick.features.regime_detection import detect_regime

ASSETS: tuple[tuple[str, str], ...] = (
    ("^GSPC", "S&P 500"),
    ("^FCHI", "CAC 40"),
    ("EURUSD=X", "EUR/USD"),
    ("GC=F", "Or"),
    ("CL=F", "Pétrole WTI"),
    ("BTC-USD", "Bitcoin"),
)
TRADING_DAYS = 252


def summarize_asset(symbol: str, label: str, prices: pd.Series) -> dict:
    prices = prices.dropna().astype(float)
    base = {"symbol": symbol, "label": label, "regime": None, "stress_prob": None, "since": None,
            "sessions_in_regime": None, "share_stress_63": None, "vol_21d": None, "vol_long": None,
            "n_states": None, "as_of": str(prices.index[-1].date()) if len(prices) else None}
    res = detect_regime(prices, n_states="auto")
    if res.n_states_selected == 0:
        return {**base, "status": "insufficient"}
    regime = res.regime
    current = regime.iloc[-1]
    starts = regime.ne(regime.shift())
    run_start = regime.index[starts][-1]
    ret = safe_pct_change(prices).dropna()
    return {
        **base,
        "status": "ok",
        "regime": str(current),
        "stress_prob": float(res.stress_prob.iloc[-1]),
        "since": str(run_start.date()),
        "sessions_in_regime": int((regime.index >= run_start).sum()),
        "share_stress_63": float((regime.iloc[-63:] == "stress").mean()),
        "vol_21d": float(ret.iloc[-21:].std() * math.sqrt(TRADING_DAYS)),
        "vol_long": float(ret.std() * math.sqrt(TRADING_DAYS)),
        "n_states": int(res.n_states_selected),
    }


class MarketStateCache:
    """One HMM fit per (symbol, last price date); prices are re-read on every
    call (cheap, cached by the loader) so a new session triggers a refit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], dict] = {}

    def overview(self, loader: Callable[[str], pd.Series | None],
                 assets: Iterable[tuple[str, str]] = ASSETS) -> list[dict]:
        rows = []
        for symbol, label in assets:
            try:
                prices = loader(symbol)
                if prices is None or prices.dropna().empty:
                    raise RuntimeError("aucune donnée de prix")
                key = (symbol, str(prices.dropna().index[-1].date()))
                with self._lock:
                    cached = self._rows.get(key)
                if cached is None:
                    cached = summarize_asset(symbol, label, prices)
                    with self._lock:
                        self._rows[key] = cached
                rows.append(cached)
            except Exception as exc:  # noqa: BLE001 -- one market failing must not hide the others
                rows.append({"symbol": symbol, "label": label, "status": "error", "error": str(exc)[:200]})
        return rows
