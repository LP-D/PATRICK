"""Téléchargement Yahoo Finance robuste — reprend le pattern établi dans
VIX_FINAL_FEATURES/VIX_PURGED_CV : un lot principal en un seul appel batch (rapide),
puis un repli ticker-par-ticker pour les tickers à faible historique ou instables en
batch, pour qu'un seul ticker cassé ne fasse pas perdre tout le lot.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import yfinance as yf


def _clean_col(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("-", "_")


def clean_symbol(ticker: str) -> str:
    """Version publique de `_clean_col`, pour que le pipeline puisse retrouver le
    nom de colonne d'un symbole sans dépendre d'un détail interne du module."""
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


def download_one(ticker: str, start: str) -> pd.Series | None:
    try:
        s = yf.download(ticker, start=start, auto_adjust=True, progress=False)["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s.name = _clean_col(ticker)
        return s
    except Exception as e:
        print(f"  [WARN] yfinance {ticker}: {str(e)[:100]}")
        return None


def download_universe(tickers: list[str], start: str, coverage_min: float = 0.85,
                       t0: float | None = None) -> pd.DataFrame:
    """Télécharge un univers de tickers avec repli individuel sur les échecs/faible
    couverture. Retourne un DataFrame indexé par date, une colonne par ticker retenu.
    """
    t0 = t0 or time.time()
    raw = download_batch(tickers, start)
    if len(raw):
        raw = raw.loc[:, raw.notna().mean() >= coverage_min].ffill().dropna(how="all")
    kept = set(raw.columns) if len(raw) else set()
    missing = [t for t in tickers if _clean_col(t) not in kept]
    for t in missing:
        s = download_one(t, start)
        if s is None:
            continue
        if len(raw):
            s = s.reindex(raw.index).ffill()
        if s.notna().mean() >= coverage_min:
            raw[s.name] = s
    print(f"  [yfinance] {raw.shape[1] if len(raw) else 0}/{len(tickers)} tickers retenus "
          f"(couverture>={coverage_min:.0%}) en {time.time()-t0:.1f}s")
    return raw


def download_target(symbol: str, start: str) -> pd.Series:
    s = download_one(symbol, start)
    if s is None or s.dropna().empty:
        raise RuntimeError(f"Impossible de récupérer la cible '{symbol}' via yfinance.")
    return s.rename(_clean_col(symbol))


def download_ohlc(symbol: str, start: str) -> pd.DataFrame | None:
    """OHLC pour un seul symbole — utilisé par les estimateurs de vol réalisée
    (Parkinson/GK/RS/Yang-Zhang), qui n'ont besoin que de la cible, pas de tout
    l'univers (cf. portée de VIX_OHLC_VOL)."""
    try:
        df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        cols = [c for c in ("Open", "High", "Low", "Close") if c in df.columns]
        if len(cols) < 4:
            return None
        return df[list(cols)].dropna(how="all")
    except Exception as e:
        print(f"  [WARN] yfinance OHLC {symbol}: {str(e)[:100]}")
        return None
