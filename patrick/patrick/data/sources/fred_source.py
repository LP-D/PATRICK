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

Phase 0.5 (vintages ALFRED) : par défaut, l'API FRED renvoie chaque série TELLE
QUE RÉVISÉE AUJOURD'HUI (`realtime_start`/`realtime_end` par défaut = date du
jour) — le CPI de janvier 2020, par exemple, a été révisé plusieurs fois depuis
sa première publication ; l'utiliser tel quel dans un backtest walk-forward sur
2020 est un look-ahead bias (le modèle "voit" une révision qui n'existait pas
encore à l'époque). `download_series(..., realtime_date=...)` bascule sur les
vintages ALFRED (mêmes endpoints FRED, `realtime_start=realtime_end=<date>`) :
renvoie la série telle qu'elle était connue à `realtime_date`, pas aujourd'hui.
Seul le chemin API le permet ; le repli scrape ne peut historiquement renvoyer
que la version actuelle (courante) de chaque série, jamais un vintage passé —
`download_fred_universe` émet un warning explicite dans ce cas.
"""
from __future__ import annotations

import os

import pandas as pd
import pandas_datareader.data as web
import requests

FRED_API_KEY_ENV = "FRED_API_KEY"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"


def _download_via_api(series_id: str, start: str, api_key: str,
                       realtime_date: str | None = None) -> pd.Series:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    if realtime_date:
        # Vintage ALFRED : renvoie, pour chaque date d'observation, la valeur
        # telle qu'elle était connue à `realtime_date` (pas la révision actuelle).
        params["realtime_start"] = realtime_date
        params["realtime_end"] = realtime_date
    resp = requests.get(FRED_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    observations = resp.json()["observations"]
    data = {o["date"]: float(o["value"]) for o in observations if o["value"] != "."}
    s = pd.Series(data, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s


def download_series(name: str, series_id: str, start: str,
                     realtime_date: str | None = None) -> pd.Series | None:
    """`realtime_date` (YYYY-MM-DD) : récupère le vintage ALFRED connu à cette
    date plutôt que la série telle que révisée aujourd'hui — nécessite le chemin
    API (FRED_API_KEY défini) ; ignoré silencieusement en repli scrape (impossible
    à faire sans l'API, cf. docstring de module)."""
    api_key = os.environ.get(FRED_API_KEY_ENV)
    try:
        s = _download_via_api(series_id, start, api_key, realtime_date) if api_key \
            else web.DataReader(series_id, "fred", start).squeeze()
        s.name = name
        return s
    except Exception as e:
        print(f"  [WARN] FRED {series_id}: {str(e)[:100]}")
        return None


def download_fred_universe(series_map: dict[str, str], start: str,
                            realtime_date: str | None = None, issues: list | None = None) -> pd.DataFrame:
    """series_map: {nom_colonne: identifiant_FRED}. `realtime_date` : cf.
    `download_series` — propagé à chaque série de l'univers.

    `issues` (Phase 6.5, P6.5) : si fourni, chaque série sans donnée (échec de
    récupération ou série discontinuée) y ajoute un `QualityIssue`."""
    from patrick.data.quality import check_fred_missing

    api_key = os.environ.get(FRED_API_KEY_ENV)
    if not api_key:
        print("  [WARN] FRED_API_KEY non défini : repli sur le scrape CSV public, qui ne "
              "peut renvoyer que la version RÉVISÉE AUJOURD'HUI de chaque série (pas de "
              "vintage point-in-time possible). Les features macro dérivées de ces séries "
              "sont donc potentiellement en avance sur l'information réellement disponible "
              "aux dates historiques du backtest (look-ahead bias sur les révisions). "
              "Définir FRED_API_KEY pour activer les vintages ALFRED (Phase 0.5).")
    cols = []
    for name, sid in series_map.items():
        s = download_series(name, sid, start, realtime_date=realtime_date)
        if s is not None:
            cols.append(s)
        elif issues is not None:
            issue = check_fred_missing(name, s)
            if issue is not None:
                issues.append(issue)
    if not cols:
        return pd.DataFrame()
    return pd.concat(cols, axis=1)
