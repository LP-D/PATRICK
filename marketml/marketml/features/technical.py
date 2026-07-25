"""Features techniques de base : retours, z-scores, moyennes mobiles, et les
estimateurs de volatilité réalisée OHLC (Parkinson/Garman-Klass/Rogers-Satchell/
Yang-Zhang) validés (sans signal net, mais reproductibles) dans VIX_OHLC_VOL.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketml.features._utils import safe_pct_change


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
        out[f"vs_ma{w}"] = series / series.rolling(w).mean() - 1
    return pd.DataFrame(out, index=series.index)


def rolling_vol(series: pd.Series, windows: list[int] = (10, 20)) -> pd.DataFrame:
    ret = safe_pct_change(series)
    out = {}
    for w in windows:
        out[f"vol_{w}d"] = ret.rolling(w).std()
    return pd.DataFrame(out, index=series.index)


# ---------------------------------------------------------------------------
# Estimateurs de volatilité réalisée à partir de l'OHLC (VIX_OHLC_VOL) — tous
# annualisés (facteur sqrt(252)) et calculés sur une fenêtre glissante.
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
    """ohlc: DataFrame avec colonnes Open/High/Low/Close (yfinance-style)."""
    o, h, l, c = ohlc["Open"], ohlc["High"], ohlc["Low"], ohlc["Close"]
    out = {}
    for w in windows:
        out[f"{prefix}_pk_{w}d"] = parkinson_vol(h, l, w)
        out[f"{prefix}_gk_{w}d"] = garman_klass_vol(o, h, l, c, w)
        out[f"{prefix}_rs_{w}d"] = rogers_satchell_vol(o, h, l, c, w)
        out[f"{prefix}_yz_{w}d"] = yang_zhang_vol(o, h, l, c, w)
    return pd.DataFrame(out, index=ohlc.index)


def build_technical_features(series: pd.Series, prefix: str = "px",
                              ohlc: pd.DataFrame | None = None) -> pd.DataFrame:
    parts = [returns(series), zscore(series), ma_ratio(series), rolling_vol(series)]
    df = pd.concat(parts, axis=1)
    df.columns = [f"{prefix}_{c}" for c in df.columns]
    if ohlc is not None and {"Open", "High", "Low", "Close"}.issubset(ohlc.columns):
        df = pd.concat([df, ohlc_vol_features(ohlc, prefix)], axis=1)
    return df
