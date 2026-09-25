"""Robust Yahoo Finance download -- reuses the pattern established in
VIX_FINAL_FEATURES/VIX_PURGED_CV: a single batch call for the main lot
(fast), then a ticker-by-ticker fallback for tickers with short history or
unstable in batch, so one broken ticker doesn't lose the whole lot.
"""
from __future__ import annotations

import time
from functools import lru_cache

import pandas as pd
import yfinance as yf

from patrick.cache_manager import LocalCache


def _clean_col(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("-", "_")


def clean_symbol(ticker: str) -> str:
    """Public version of `_clean_col`, so the pipeline can recover a
    symbol's column name without depending on an internal module detail."""
    return _clean_col(ticker)


def download_batch(tickers: list[str], start: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw["Close"]
    elif "Close" in raw.columns:
        raw = raw[["Close"]]
        raw.columns = tickers
    raw.columns = [_clean_col(c) for c in raw.columns]
    return raw


@lru_cache(maxsize=256)
def _download_one_cached(ticker: str, start: str) -> pd.Series | None:
    try:
        s = yf.download(ticker, start=start, auto_adjust=True, progress=False)["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.copy()
        s.name = _clean_col(ticker)
        return s
    except Exception as e:  # noqa: BLE001 -- provider boundary: one failing ticker never loses the others
        print(f"  [WARN] yfinance {ticker}: {str(e)[:100]}")
        return None


def download_one(ticker: str, start: str) -> pd.Series | None:
    key = f"series_{_clean_col(ticker)}_{start}"
    cache = LocalCache()
    cached = cache.load_dataframe(key, max_age_days=7)
    if cached is not None:
        if cached.shape[1] == 1:
            return cached.iloc[:, 0].copy()
        return cached.iloc[:, 0].copy()
    s = _download_one_cached(ticker, start)
    if s is not None:
        cache.save_dataframe(key, s.to_frame(), max_age_days=7)
        return s.copy()
    return None


def download_universe(tickers: list[str], start: str, coverage_min: float = 0.85,
                       t0: float | None = None, issues: list | None = None,
                       return_unfilled: bool = False):
    """Downloads a universe of tickers with an individual fallback for
    failures/low coverage. Returns a DataFrame indexed by date, one column
    per retained ticker.

    `issues` (Phase 6.5, P6.5): if provided, every ticker excluded by THIS
    coverage filter (the only one already in place here) adds a
    `QualityIssue` to it -- the real reason observed at the decision point,
    not reconstructed after the fact. The other quality checks (frozen
    prices, gaps, outlier returns, early series end) run separately in
    `data/ingest.py` on the surviving series, via `data/quality.py`.

    `return_unfilled=True`: returns `(filled, unfilled)` -- `unfilled` holds
    the closes as REPORTED (no forward fill), on the same columns. The
    quality gates must run on it: forward-filling a holiday bridge turns it
    into "identical closes" (measured on real data, 2000-2026: max run of
    identical reported closes 2-3 on every liquid future/index, 4-12 once
    forward-filled -- GC=F, ^VIX, EURUSD=X excluded as "frozen" for that
    reason alone).
    """
    from patrick.data.quality import QualityIssue

    t0 = t0 or time.time()
    raw = download_batch(tickers, start)
    if len(raw):
        # Coverage "of business days populated" -- measured on business days
        # only: a weekend-trading ticker in the batch (BTC-USD) adds Saturday/
        # Sunday rows to the union index and used to drag every exchange-
        # traded ticker to ~5/7 coverage (^VIX excluded at 81.9%).
        coverage = raw.loc[raw.index.dayofweek < 5].notna().mean()
        low_coverage = coverage[coverage < coverage_min]
        if issues is not None:
            for col, cov in low_coverage.items():
                issues.append(QualityIssue(col, "couverture_insuffisante",
                                            f"{cov:.1%} of business days populated (threshold {coverage_min:.0%})"))
        unfilled = raw.loc[:, coverage >= coverage_min].dropna(how="all")
        raw = unfilled.ffill()
    else:
        unfilled = raw.copy()
    kept = set(raw.columns) if len(raw) else set()
    missing = [t for t in tickers if _clean_col(t) not in kept]
    for t in missing:
        s = download_one(t, start)
        if s is None:
            if issues is not None:
                issues.append(QualityIssue(_clean_col(t), "echec_telechargement",
                                            "no data returned by yfinance (individual fallback)"))
            continue
        s_reported = s.reindex(raw.index) if len(raw) else s
        if len(raw):
            s = s.reindex(raw.index).ffill()
        cov = s_reported.loc[s_reported.index.dayofweek < 5].notna().mean()
        if cov >= coverage_min:
            raw[s.name] = s
            unfilled[s.name] = s_reported
        elif issues is not None:
            issues.append(QualityIssue(s.name, "couverture_insuffisante",
                                        f"{cov:.1%} of business days populated (threshold {coverage_min:.0%})"))
    print(f"  [yfinance] {raw.shape[1] if len(raw) else 0}/{len(tickers)} tickers kept "
          f"(coverage>={coverage_min:.0%}) in {time.time()-t0:.1f}s")
    if return_unfilled:
        return raw, unfilled.reindex(columns=raw.columns) if len(raw) else unfilled
    return raw


def download_target(symbol: str, start: str) -> pd.Series:
    s = download_one(symbol, start)
    if s is None or s.dropna().empty:
        raise RuntimeError(f"Could not fetch target '{symbol}' via yfinance.")
    return s.rename(_clean_col(symbol))


@lru_cache(maxsize=128)
def _download_ohlc_cached(symbol: str, start: str) -> pd.DataFrame | None:
    try:
        df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        cols = [c for c in ("Open", "High", "Low", "Close") if c in df.columns]
        if len(cols) < 4:
            return None
        return df[list(cols)].dropna(how="all").copy()
    except Exception as e:  # noqa: BLE001 -- provider boundary, OHLC is optional
        print(f"  [WARN] yfinance OHLC {symbol}: {str(e)[:100]}")
        return None


def download_ohlc(symbol: str, start: str) -> pd.DataFrame | None:
    """OHLC for a single symbol -- used by realized-vol estimators
    (Parkinson/GK/RS/Yang-Zhang), which only need the target, not the whole
    universe (see VIX_OHLC_VOL scope).

    The result is cached locally + in memory by `(symbol, start)` to avoid
    repeated downloads during a grid scan or a multi-fold run: the same
    OHLC dataset is read multiple times over the same history, with no
    added value in re-downloading it from Yahoo.
    """
    cache_key = f"ohlc_{_clean_col(symbol)}_{start}"
    cached = LocalCache().load_dataframe(cache_key, max_age_days=7)
    if cached is not None:
        return cached.copy()
    df = _download_ohlc_cached(symbol, start)
    if df is not None:
        LocalCache().save_dataframe(cache_key, df, max_age_days=7)
    return None if df is None else df.copy()
