"""Basic technical features: returns, z-scores, moving averages, and the OHLC
realized-volatility estimators (Parkinson/Garman-Klass/Rogers-Satchell/
Yang-Zhang) validated (no clean signal, but reproducible) in VIX_OHLC_VOL.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features._utils import safe_pct_change


def returns(series: pd.Series, windows: list[int] = (1, 5, 10, 20)) -> pd.DataFrame:
    out = {}
    for w in windows:
        out[f"ret_{w}d"] = safe_pct_change(series, w)
    return pd.DataFrame(out, index=series.index)


def zscore(series: pd.Series, windows: list[int] = (10, 20, 60)) -> pd.DataFrame:
    out = {}
    for w in windows:
        roll = series.rolling(w)
        out[f"zscore_{w}d"] = (series - roll.mean()) / roll.std().replace(0, np.nan)
    return pd.DataFrame(out, index=series.index)


def ma_ratio(series: pd.Series, windows: list[int] = (10, 20, 50)) -> pd.DataFrame:
    out = {}
    for w in windows:
        ma = series.rolling(w).mean().replace(0, np.nan)
        out[f"vs_ma{w}"] = series / ma - 1
    return pd.DataFrame(out, index=series.index)


def rolling_vol(series: pd.Series, windows: list[int] = (10, 20)) -> pd.DataFrame:
    ret = safe_pct_change(series)
    out = {}
    for w in windows:
        out[f"vol_{w}d"] = ret.rolling(w).std()
    return pd.DataFrame(out, index=series.index)


def _wilder_rsi_single(series: pd.Series, period: int) -> pd.Series:
    """Wilder's original recursive smoothing, computed vectorized (no Python
    loop): seed = simple average of the first `period` gains/losses (delta
    indices 1..period), then avg_x_t = (avg_x_{t-1}*(period-1) + x_t) / period
    for every later bar -- exactly `pandas.ewm(alpha=1/period, adjust=False)`
    applied to a series whose FIRST element is that seed and whose remaining
    elements are the raw gains/losses after the seed window (ewm(adjust=False)
    recursion y_t = alpha*x_t + (1-alpha)*y_{t-1} is algebraically identical
    to Wilder's formula once alpha=1/period), which lets us reuse pandas' C
    implementation instead of a Python-level per-bar loop across 14 lookbacks
    x N columns."""
    n = len(series)
    if n <= period:
        return pd.Series(np.nan, index=series.index, dtype=float)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    seed_gain = gain.iloc[1:period + 1].mean()
    seed_loss = loss.iloc[1:period + 1].mean()
    tail_gain = gain.iloc[period + 1:].to_numpy()
    tail_loss = loss.iloc[period + 1:].to_numpy()

    work_gain = pd.Series(np.concatenate(([seed_gain], tail_gain)))
    work_loss = pd.Series(np.concatenate(([seed_loss], tail_loss)))
    avg_gain_tail = work_gain.ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    avg_loss_tail = work_loss.ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()

    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    avg_gain[period:period + len(avg_gain_tail)] = avg_gain_tail
    avg_loss[period:period + len(avg_loss_tail)] = avg_loss_tail

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi_vals = 100 - 100 / (1 + rs)
    # Convention (undefined 0/0 or x/0 otherwise): all gains, no losses in the
    # window -> RSI=100; perfectly flat window (both averages exactly 0) ->
    # RSI=50 (neutral), not NaN/inf.
    rsi_vals = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, rsi_vals)
    rsi_vals = np.where((avg_loss == 0) & (avg_gain == 0), 50.0, rsi_vals)
    return pd.Series(rsi_vals, index=series.index)


def rsi(series: pd.Series, windows: list[int] = (14,)) -> pd.DataFrame:
    """Wilder's RSI (Relative Strength Index) — the "usual" classic formula
    (not a variant): Wilder-smoothed average gain vs average loss over
    `period` bars, RSI = 100 - 100/(1+RS) with RS = avg_gain/avg_loss. Pure
    rolling/recursive computation on past bars only (causal by construction,
    no global parameter, no `fit_end_idx` needed) — see `_wilder_rsi_single`
    for the exact recursion and its vectorized implementation."""
    out = {}
    for w in windows:
        out[f"rsi_{w}d"] = _wilder_rsi_single(series, w)
    return pd.DataFrame(out, index=series.index)


# ---------------------------------------------------------------------------
# Realized-volatility estimators from OHLC (VIX_OHLC_VOL) — all annualized
# (sqrt(252) factor) and computed over a rolling window.
# ---------------------------------------------------------------------------
_ANNUALIZE = np.sqrt(252)


def parkinson_vol(high: pd.Series, low: pd.Series, window: int = 10) -> pd.Series:
    hl = np.log(high / low) ** 2
    var = hl.rolling(window).mean() / (4 * np.log(2))
    return np.sqrt(var) * _ANNUALIZE


def garman_klass_vol(open_: pd.Series, high: pd.Series, low: pd.Series,
                      close: pd.Series, window: int = 10) -> pd.Series:
    log_hl = np.log(high / low) ** 2
    log_co = np.log(close / open_) ** 2
    term = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
    var = term.rolling(window).mean()
    return np.sqrt(var.clip(lower=0)) * _ANNUALIZE


def rogers_satchell_vol(open_: pd.Series, high: pd.Series, low: pd.Series,
                         close: pd.Series, window: int = 10) -> pd.Series:
    term = (np.log(high / close) * np.log(high / open_)
            + np.log(low / close) * np.log(low / open_))
    var = term.rolling(window).mean()
    return np.sqrt(var.clip(lower=0)) * _ANNUALIZE


def yang_zhang_vol(open_: pd.Series, high: pd.Series, low: pd.Series,
                    close: pd.Series, window: int = 10) -> pd.Series:
    prev_close = close.shift(1)
    overnight = np.log(open_ / prev_close) ** 2
    open_close = np.log(close / open_) ** 2
    rs = (np.log(high / close) * np.log(high / open_)
          + np.log(low / close) * np.log(low / open_))
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    var = (overnight.rolling(window).mean()
           + k * open_close.rolling(window).mean()
           + (1 - k) * rs.rolling(window).mean())
    return np.sqrt(var.clip(lower=0)) * _ANNUALIZE


def ohlc_vol_features(ohlc: pd.DataFrame, prefix: str, windows: list[int] = (10, 20)) -> pd.DataFrame:
    """ohlc: DataFrame with Open/High/Low/Close columns (yfinance-style)."""
    o, h, l, c = ohlc["Open"], ohlc["High"], ohlc["Low"], ohlc["Close"]
    out = {}
    for w in windows:
        out[f"{prefix}_pk_{w}d"] = parkinson_vol(h, l, w)
        out[f"{prefix}_gk_{w}d"] = garman_klass_vol(o, h, l, c, w)
        out[f"{prefix}_rs_{w}d"] = rogers_satchell_vol(o, h, l, c, w)
        out[f"{prefix}_yz_{w}d"] = yang_zhang_vol(o, h, l, c, w)
    return pd.DataFrame(out, index=ohlc.index)


_DEFAULT_WINDOWS = {
    "returns": (1, 5, 10, 20),
    "zscore": (10, 20, 60),
    "ma_ratio": (10, 20, 50),
    "rolling_vol": (10, 20),
    "rsi": (14,),
}


def _merged_windows(name: str, guida_windows: list[int] | None) -> list[int]:
    """Merges a function's own small default windows with the Guida 14-
    lookback grid (deduplicated, sorted) when `guida_windows` is provided —
    reuses the `windows=` parameter every function below already accepts,
    rather than introducing a second, parallel window mechanism."""
    base = _DEFAULT_WINDOWS[name]
    if not guida_windows:
        return list(base)
    return sorted(set(base) | set(guida_windows))


def build_technical_features(series: pd.Series, prefix: str = "px",
                              ohlc: pd.DataFrame | None = None,
                              guida_windows: list[int] | None = None) -> pd.DataFrame:
    """`guida_windows` (Phase 2, feature/guida-features-full): optional list
    of extra lookbacks (typically `config.defaults.GUIDA_LOOKBACKS`) merged
    into every already-`windows=`-parameterized function below (returns/
    zscore/ma_ratio/rolling_vol/rsi). `None` (default): behavior strictly
    unchanged from before this parameter existed."""
    parts = [
        returns(series, _merged_windows("returns", guida_windows)),
        zscore(series, _merged_windows("zscore", guida_windows)),
        ma_ratio(series, _merged_windows("ma_ratio", guida_windows)),
        rolling_vol(series, _merged_windows("rolling_vol", guida_windows)),
        rsi(series, _merged_windows("rsi", guida_windows)),
    ]
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    if ohlc is not None and {"Open", "High", "Low", "Close"}.issubset(ohlc.columns):
        df = pd.concat([df, ohlc_vol_features(ohlc, prefix)], axis=1)
    return df
