"""Price provider for the patrimoine pages: yfinance first, through a
short-lived cache of its own, the local data lake (a series ingested by a
run) as the offline fallback. Memoised per provider instance -- one page
render asks each symbol once. Term deposits (`DAT:...`) have no quotes by
definition.

Why not `yfinance_source.download_one` (the pipeline's helper) nor the lake
first, as before: the P&L must follow the last close.
- `download_one` keeps a series 7 days on disk and for the whole life of the
  process in an `lru_cache`: a long-running `patrick serve` showed the
  first price it ever fetched, and an empty answer (a ticker not listed
  yet, ALDAT.PA before 2026-09-25) stayed cached for a week;
- the lake holds whatever snapshot the last run of that target ingested,
  possibly weeks old.
Here: at most `PRICE_MAX_AGE_DAYS` old, an empty answer is never cached.

Closes are NOT dividend-adjusted (`auto_adjust=False`, split-adjusted
only): the ledger records dividends as income movements, so an adjusted
series would count every dividend twice (once in the price appreciation,
once as cash) and overstate the performance by the dividend yield.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from patrick.cache_manager import LocalCache
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore

HISTORY_START = "2000-01-01"
PRICE_MAX_AGE_DAYS = 0.25  # 6 h


def _download(symbol: str) -> pd.Series | None:
    try:
        close = yf.download(symbol, start=HISTORY_START, auto_adjust=False, progress=False)["Close"]
    except Exception as exc:  # noqa: BLE001 -- provider boundary: a failing symbol never breaks a page
        print(f"  [WARN] yfinance {symbol}: {str(exc)[:100]}")
        return None
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    return close if len(close) else None


def fetch_latest(symbol: str, max_age_days: float = PRICE_MAX_AGE_DAYS) -> pd.Series | None:
    key = f"wealth_close_{clean_symbol(symbol)}_{HISTORY_START}"
    cache = LocalCache()
    cached = cache.load_dataframe(key, max_age_days=max_age_days)
    if cached is not None and len(cached):
        return cached.iloc[:, 0]
    series = _download(symbol)
    if series is not None:
        cache.save_dataframe(key, series.rename(clean_symbol(symbol)).to_frame())
    return series


def _from_lake(store: DataStore, symbol: str) -> pd.Series | None:
    key = f"raw_{symbol}"
    if not store.exists(key):
        return None
    df = store.load(key)
    col = clean_symbol(symbol)
    if col not in df.columns:
        col = "Close" if "Close" in df.columns else df.columns[0]
    return df[col].dropna()


def make_provider(store: DataStore | None = None, allow_network: bool = True):
    store = store or DataStore()
    memo: dict[str, pd.Series | None] = {}

    def get(symbol: str) -> pd.Series | None:
        if not symbol or symbol.startswith("DAT:"):
            return None
        if symbol in memo:
            return memo[symbol]
        series = fetch_latest(symbol) if allow_network else None
        if series is None:
            series = _from_lake(store, symbol)
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
