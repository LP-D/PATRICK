"""Orchestration de l'ingestion : cible + univers de features (yfinance + FRED),
alignés sur un même index, mis en cache dans le data lake local.
"""
from __future__ import annotations

import time

import pandas as pd

from patrick.config.schema import ObjectiveConfig, UniverseConfig
from patrick.data.sources import fred_source, yfinance_source
from patrick.data.store import DataStore


def ingest(objective: ObjectiveConfig, universe: UniverseConfig,
           store: DataStore | None = None, force: bool = False) -> pd.DataFrame:
    store = store or DataStore()
    cache_key = f"raw_{objective.target_symbol}"
    if not force and store.exists(cache_key):
        df = store.load(cache_key)
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
        df = df.join(yf_df, how="outer")

    if universe.fred_series:
        fred_df = fred_source.download_fred_universe(universe.fred_series, universe.start_date)
        if len(fred_df):
            fred_df = fred_df.reindex(df.index, method="ffill")
            df = pd.concat([df, fred_df], axis=1)

    df = df.sort_index().ffill().dropna(subset=[target.name])
    print(f"[INGEST] {df.shape} ({time.time()-t0:.1f}s) | cible={target.name}")
    store.save(cache_key, df)
    return df
