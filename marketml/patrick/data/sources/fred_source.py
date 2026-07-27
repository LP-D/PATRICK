"""Téléchargement FRED robuste série-par-série (reprend le pattern établi dans
VIX_FINAL_FEATURES/VIX_VAR_MACRO) : une série qui échoue ne fait pas perdre les
autres.

Deux chemins de récupération :
- API officielle FRED (https://fred.stlouisfed.org/docs/api/fred/), utilisée
  si la variable d'environnement FRED_API_KEY est définie (clé gratuite sur
  https://fred.stlouisfed.org/docs/api/api_key.html). Stable, authentifiée,
  ne dépend pas du HTML/CSV public.
- `pandas_datareader` (scrape du CSV public fredgraph.csv), utilisé en repli
  si aucune clé n'est fournie. C'est le chemin historique de ce module, mais
  il est sujet aux blocages/changements de format côté fred.stlouisfed.org
  (constaté : échecs systématiques sur toutes les séries FRED alors que
  yfinance fonctionnait toujours) — d'où l'ajout du chemin API.
"""
from __future__ import annotations

import os

import pandas as pd
import pandas_datareader.data as web
import requests

FRED_API_KEY_ENV = "FRED_API_KEY"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"


def _download_via_api(series_id: str, start: str, api_key: str) -> pd.Series:
    resp = requests.get(
        FRED_API_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=30,
    )
    resp.raise_for_status()
    observations = resp.json()["observations"]
    data = {o["date"]: float(o["value"]) for o in observations if o["value"] != "."}
    s = pd.Series(data, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s


def download_series(name: str, series_id: str, start: str) -> pd.Series | None:
    api_key = os.environ.get(FRED_API_KEY_ENV)
    try:
        s = _download_via_api(series_id, start, api_key) if api_key \
            else web.DataReader(series_id, "fred", start).squeeze()
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
