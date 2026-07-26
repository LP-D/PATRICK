"""Téléchargement FRED robuste série-par-série (reprend le pattern établi dans
VIX_FINAL_FEATURES/VIX_VAR_MACRO) : une série qui échoue ne fait pas perdre les
autres.
"""
from __future__ import annotations

import pandas as pd
import pandas_datareader.data as web


def download_series(name: str, series_id: str, start: str) -> pd.Series | None:
    try:
        s = web.DataReader(series_id, "fred", start).squeeze()
        s.name = name
        return s
    except Exception as e:
        print(f"  [WARN] FRED {series_id}: {str(e)[:100]}")
        return None


def download_fred_universe(series_map: dict[str, str], start: str) -> pd.DataFrame:
    """series_map: {nom_colonne: identifiant_FRED}."""
    cols = []
    for name, sid in series_map.items():
        s = download_series(name, sid, start)
        if s is not None:
            cols.append(s)
    if not cols:
        return pd.DataFrame()
    return pd.concat(cols, axis=1)
