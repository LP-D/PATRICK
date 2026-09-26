"""Market state read by the HMM (decision of 2026-09-26: the HMM serves regime
models and market-state analysis, no longer ML features).

Per market: a 2-state Gaussian HMM (calm / stress) on daily log returns in
percent, the causal forward filter of `features.regime_detection`, and:
the current regime (P(stress) > 0.5), since when, the share of the last
quarter spent in stress, each state's annualised volatility, and realised
volatility (21 sessions vs the whole history).

Why 2 states and not `detect_regime`'s calm / normal / stress terciles
(built to split training data into balanced thirds): measured on real
prices (2000-2026, six markets), with 3-4 states the calm and normal states
overlap so much that the most probable state changed every 1-8 sessions on
average, and terciles of P(stress) labelled WTI "stress" at
P(stress) = 0.000; with 2 states the average regime lasts 14-26 sessions
for five markets (bitcoin still flips every ~5 sessions). Non-positive
prices (WTI, 2020-04-20) are dropped: a log return does not exist there.

Descriptive, not a backtested signal: the HMM parameters are fitted on the
whole history up to today; only the state probability is filtered (causal
given those parameters). `MarketStateCache` keeps one fit per (symbol, last
price date).
"""
from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from patrick.features.regime_detection import filtered_state_probs

ASSETS: tuple[tuple[str, str], ...] = (
    ("^GSPC", "S&P 500"),
    ("^FCHI", "CAC 40"),
    ("EURUSD=X", "EUR/USD"),
    ("GC=F", "Or"),
    ("BZ=F", "Pétrole Brent"),
    ("BTC-USD", "Bitcoin"),
)
TRADING_DAYS = 252
MIN_RETURNS = 250


def summarize_asset(symbol: str, label: str, prices: pd.Series) -> dict:
    prices = prices.dropna().astype(float)
    prices = prices[prices > 0]
    base = {"symbol": symbol, "label": label, "regime": None, "stress_prob": None, "since": None,
            "sessions_in_regime": None, "share_stress_63": None, "vol_calm": None, "vol_stress": None,
            "vol_21d": None, "vol_long": None, "as_of": str(prices.index[-1].date()) if len(prices) else None}
    ret = np.log(prices).diff().dropna()
    if len(ret) < MIN_RETURNS:
        return {**base, "status": "insufficient"}
    filtered, model = filtered_state_probs((ret.to_numpy() * 100).reshape(-1, 1), n_states=2)
    state_vol = np.sqrt(model.covars_.reshape(2, -1)[:, 0]) / 100 * math.sqrt(TRADING_DAYS)
    stress_state = int(np.argmax(state_vol))
    p_stress = pd.Series(filtered[:, stress_state], index=ret.index)
    in_stress = p_stress > 0.5
    run_start = in_stress.index[in_stress.ne(in_stress.shift())][-1]
    return {
        **base,
        "status": "ok",
        "regime": "stress" if in_stress.iloc[-1] else "calme",
        "stress_prob": float(p_stress.iloc[-1]),
        "since": str(run_start.date()),
        "sessions_in_regime": int((in_stress.index >= run_start).sum()),
        "share_stress_63": float(in_stress.iloc[-63:].mean()),
        "vol_calm": float(state_vol.min()),
        "vol_stress": float(state_vol.max()),
        "vol_21d": float(ret.iloc[-21:].std() * math.sqrt(TRADING_DAYS)),
        "vol_long": float(ret.std() * math.sqrt(TRADING_DAYS)),
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
