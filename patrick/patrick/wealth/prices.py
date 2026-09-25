"""Price provider for the patrimoine pages: the local data lake first (a
series ingested by a run), then yfinance through the existing 7-day
LocalCache (`download_one`, fixed start so every call hits the same cache
key). Memoised per provider instance -- one page render asks each symbol
once. Term deposits (`DAT:...`) have no quotes by definition."""
from __future__ import annotations

import pandas as pd

from patrick.data.sources.yfinance_source import clean_symbol, download_one
from patrick.data.store import DataStore

HISTORY_START = "2000-01-01"


def make_provider(store: DataStore | None = None, allow_network: bool = True):
    store = store or DataStore()
    memo: dict[str, pd.Series | None] = {}

    def get(symbol: str) -> pd.Series | None:
        if not symbol or symbol.startswith("DAT:"):
            return None
        if symbol in memo:
            return memo[symbol]
        series = None
        key = f"raw_{symbol}"
        if store.exists(key):
            df = store.load(key)
            col = clean_symbol(symbol)
            if col not in df.columns:
                col = "Close" if "Close" in df.columns else df.columns[0]
            series = df[col].dropna()
        elif allow_network:
            series = download_one(symbol, HISTORY_START)
        if series is not None:
            series = series.dropna()
            series.index = pd.DatetimeIndex(series.index).tz_localize(None) \
                if getattr(series.index, "tz", None) is not None else pd.DatetimeIndex(series.index)
            series = series[~series.index.duplicated(keep="last")].sort_index()
            if series.empty:
                series = None
        memo[symbol] = series
        return series

    return get
