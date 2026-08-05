"""Téléchargement Yahoo Finance robuste — reprend le pattern établi dans
VIX_FINAL_FEATURES/VIX_PURGED_CV : un lot principal en un seul appel batch (rapide),
puis un repli ticker-par-ticker pour les tickers à faible historique ou instables en
batch, pour qu'un seul ticker cassé ne fasse pas perdre tout le lot.
"""
from __future__ import annotations

import time
from functools import lru_cache

import numpy as np
import pandas as pd
import yfinance as yf

from patrick.cache_manager import LocalCache


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


@lru_cache(maxsize=256)
def _download_one_cached(ticker: str, start: str) -> pd.Series | None:
    try:
        s = yf.download(ticker, start=start, auto_adjust=True, progress=False)["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.copy()
        s.name = _clean_col(ticker)
        return s
    except Exception as e:
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
                       t0: float | None = None, issues: list | None = None) -> pd.DataFrame:
    """Télécharge un univers de tickers avec repli individuel sur les échecs/faible
    couverture. Retourne un DataFrame indexé par date, une colonne par ticker retenu.

    `issues` (Phase 6.5, P6.5) : si fourni, chaque ticker exclu par CE filtre de
    couverture (le seul déjà en place ici) y ajoute un `QualityIssue` -- motif
    réel constaté au point de décision, pas reconstruit après coup. Les autres
    contrôles de qualité (prix figés, trous, rendements aberrants, fin de
    série précoce) tournent séparément dans `data/ingest.py` sur les séries
    survivantes, via `data/quality.py`.
    """
    from patrick.data.quality import QualityIssue

    t0 = t0 or time.time()
    raw = download_batch(tickers, start)
    if len(raw):
        coverage = raw.notna().mean()
        low_coverage = coverage[coverage < coverage_min]
        if issues is not None:
            for col, cov in low_coverage.items():
                issues.append(QualityIssue(col, "couverture_insuffisante",
                                            f"{cov:.1%} de jours ouvrés renseignés (seuil {coverage_min:.0%})"))
        raw = raw.loc[:, raw.notna().mean() >= coverage_min].ffill().dropna(how="all")
    kept = set(raw.columns) if len(raw) else set()
    missing = [t for t in tickers if _clean_col(t) not in kept]
    for t in missing:
        s = download_one(t, start)
        if s is None:
            if issues is not None:
                issues.append(QualityIssue(_clean_col(t), "echec_telechargement",
                                            "aucune donnée renvoyée par yfinance (repli individuel)"))
            continue
        if len(raw):
            s = s.reindex(raw.index).ffill()
        cov = s.notna().mean()
        if cov >= coverage_min:
            raw[s.name] = s
        elif issues is not None:
            issues.append(QualityIssue(s.name, "couverture_insuffisante",
                                        f"{cov:.1%} de jours ouvrés renseignés (seuil {coverage_min:.0%})"))
    print(f"  [yfinance] {raw.shape[1] if len(raw) else 0}/{len(tickers)} tickers retenus "
          f"(couverture>={coverage_min:.0%}) en {time.time()-t0:.1f}s")
    return raw


def download_target(symbol: str, start: str) -> pd.Series:
    s = download_one(symbol, start)
    if s is None or s.dropna().empty:
        raise RuntimeError(f"Impossible de récupérer la cible '{symbol}' via yfinance.")
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
    except Exception as e:
        print(f"  [WARN] yfinance OHLC {symbol}: {str(e)[:100]}")
        return None


def download_ohlc(symbol: str, start: str) -> pd.DataFrame | None:
    """OHLC pour un seul symbole — utilisé par les estimateurs de vol réalisée
    (Parkinson/GK/RS/Yang-Zhang), qui n'ont besoin que de la cible, pas de tout
    l'univers (cf. portée de VIX_OHLC_VOL).

    Le résultat est mis en cache local + mémoire par `(symbol, start)` pour éviter
    les téléchargements répétés pendant un scan de grille ou un run multi-fold : le
    même dataset OHLC est relu plusieurs fois sur le même historique, sans valeur
    ajoutée à re-télécharger depuis Yahoo.
    """
    cache_key = f"ohlc_{_clean_col(symbol)}_{start}"
    cached = LocalCache().load_dataframe(cache_key, max_age_days=7)
    if cached is not None:
        return cached.copy()
    df = _download_ohlc_cached(symbol, start)
    if df is not None:
        LocalCache().save_dataframe(cache_key, df, max_age_days=7)
    return None if df is None else df.copy()
