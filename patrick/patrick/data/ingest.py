"""Orchestration de l'ingestion : cible + univers de features (yfinance + FRED),
alignés sur un même index, mis en cache dans le data lake local.
"""
from __future__ import annotations

import os
import time

import pandas as pd

from patrick.config.schema import ObjectiveConfig, UniverseConfig
from patrick.data.session_calendar import session_lag_days
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.sources.fred_source import FRED_API_KEY_ENV
from patrick.data.store import DataStore


def _apply_session_lag(yf_df: pd.DataFrame, tickers: list[str], objective: ObjectiveConfig) -> pd.DataFrame:
    """Décale d'une barre les colonnes dont la classe d'actif clôture après celle
    de la cible (Phase 0.4 — cf. `data/session_calendar.py`) : une jointure "même
    date calendaire" traite implicitement comme simultanées des clôtures de
    marché qui ne le sont pas (ex. clôture US utilisée "du jour" pour une cible
    qui a déjà clôturé plus tôt dans la même journée UTC).

    `objective.disable_session_lag` (rapport de correction, C7) : bascule
    ajoutée uniquement pour `patrick audit degradation`, jamais utilisée en
    production (défaut False -- correction toujours appliquée)."""
    if objective.disable_session_lag:
        return yf_df
    reverse = {yfinance_source.clean_symbol(t): t for t in tickers}
    out = yf_df.copy()
    lagged = []
    for col in out.columns:
        original_symbol = reverse.get(col, col)
        if session_lag_days(original_symbol, "yfinance",
                             objective.target_symbol, objective.target_source):
            out[col] = out[col].shift(1)
            lagged.append(original_symbol)
    if lagged:
        print(f"  [ALIGNEMENT] {len(lagged)} tickers décalés d'une barre "
              f"(clôture postérieure à celle de la cible) : {', '.join(lagged[:8])}"
              f"{'...' if len(lagged) > 8 else ''}")
    return out


def _attach_snapshot_context(df: pd.DataFrame, universe: UniverseConfig) -> None:
    """Métadonnées de contexte (Phase 1.6) transportées via `DataFrame.attrs` —
    lues par `pipeline/engine.py` pour peupler la table `snapshot` sans changer
    la signature de `ingest()` (qui reste "retourne un DataFrame", ce que
    monkeypatchent déjà tous les tests existants)."""
    df.attrs["n_tickers"] = len(universe.yf_tickers)
    df.attrs["n_fred_series"] = len(universe.fred_series)
    df.attrs["fred_source"] = "api" if os.environ.get(FRED_API_KEY_ENV) else "scrape"


def ingest(objective: ObjectiveConfig, universe: UniverseConfig,
           store: DataStore | None = None, force: bool = False) -> pd.DataFrame:
    """`cache_key` ne dépend que de `target_symbol`, pas de `universe.
    vintage_realtime_date`/`objective.disable_session_lag` (rapport de
    correction, C7) : un cache existant peut donc masquer un changement de ces
    deux bascules. Appelants qui les font varier pour un même `target_symbol`
    (ex. `patrick audit degradation`) DOIVENT passer `force=True`."""
    store = store or DataStore()
    cache_key = f"raw_{objective.target_symbol}"
    if not force and store.exists(cache_key):
        df = store.load(cache_key)
        _attach_snapshot_context(df, universe)
        print(f"[CACHE] {cache_key}: {df.shape} déjà en cache (force=True pour rafraîchir).")
        return df

    t0 = time.time()
    if objective.target_source == "yfinance":
        target = yfinance_source.download_target(objective.target_symbol, universe.start_date)
    else:
        target = fred_source.download_series(objective.target_symbol, objective.target_symbol,
                                               universe.start_date)
        if target is None:
            raise RuntimeError(f"Impossible de récupérer la cible FRED '{objective.target_symbol}'.")

    df = target.to_frame()

    if universe.yf_tickers:
        yf_df = yfinance_source.download_universe(universe.yf_tickers, universe.start_date,
                                                    universe.yf_coverage, t0=t0)
        yf_df = _apply_session_lag(yf_df, universe.yf_tickers, objective)
        df = df.join(yf_df, how="outer")

    if universe.fred_series:
        fred_df = fred_source.download_fred_universe(
            universe.fred_series, universe.start_date, realtime_date=universe.vintage_realtime_date)
        if len(fred_df):
            fred_df = fred_df.reindex(df.index, method="ffill")
            df = pd.concat([df, fred_df], axis=1)

    df = df.sort_index().ffill().dropna(subset=[target.name])
    print(f"[INGEST] {df.shape} ({time.time()-t0:.1f}s) | cible={target.name}")
    store.save(cache_key, df)
    _attach_snapshot_context(df, universe)
    return df
