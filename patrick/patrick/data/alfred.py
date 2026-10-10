"""ALFRED (les archives de FRED) comme source par défaut des séries macro.

FRED renvoie chaque série TELLE QUE RÉVISÉE AUJOURD'HUI : le PIB du T1 2020 a changé plusieurs fois depuis sa première
publication, et un modèle entraîné « en 2020 » avec la valeur d'aujourd'hui voit une révision qui n'existait pas encore.
ALFRED garde chaque version (« vintage ») : on prend la PREMIÈRE publication de chaque observation, indexée sur la date où
elle est réellement sortie. C'est la seule information qu'un modèle pouvait avoir à cette date.

Trois cas, par série (`AlfredResult.mode`) :
- `alfred` : les vintages couvrent tout l'historique demandé -> première publication partout ;
- `hybrid` : ALFRED n'archive la série qu'à partir d'une date (NFCI : 2011, ICE BofA : 2023) -> première publication
  depuis cette date, et AVANT elle la version actuelle de FRED indexée sur une date de publication estimée
  (`publication_lag`) : c'est la seule donnée qui existe, et elle vaut mieux qu'un historique raccourci ;
- `fred` : la série n'existe pas dans ALFRED (SP500) ou ALFRED échoue -> FRED + date de publication estimée, jamais une série
  perdue.

Le téléchargement est découpé en fenêtres de vintages (l'API refuse plus de ~2000 dates de vintage par requête, ce qui exclut
d'un coup toutes les séries quotidiennes : DGS10 en a 5126) et mis en cache 12 h.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import requests

from patrick.cache_manager import LocalCache
from patrick.data import publication_lag

API_BASE = "https://api.stlouisfed.org/fred"
OBSERVATIONS_URL = f"{API_BASE}/series/observations"
VINTAGES_URL = f"{API_BASE}/series/vintagedates"
API_KEY_ENV = "FRED_API_KEY"
MAX_VINTAGES_PER_REQUEST = 1500       # l'API refuse au-delà d'environ 2000
FAR_PAST, FAR_FUTURE = "1776-07-04", "9999-12-31"
CACHE_TTL_HOURS = 12.0
_CACHE_PREFIX = "alfred_"


@dataclass
class AlfredResult:
    series: pd.Series                       # valeurs sur leur date de PUBLICATION (réelle ou estimée), triées
    mode: str                               # "alfred" | "hybrid" | "fred"
    info: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------------ appels API

def _get_json(url: str, params: dict, *, retries: int = 3, session=requests) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:     # limite de débit / panne passagère
                time.sleep(2 * (attempt + 1))
                last = requests.HTTPError(f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last or RuntimeError("ALFRED : échec sans détail")


def vintage_dates(series_id: str, api_key: str, *, session=requests) -> list[str] | None:
    """Dates de vintage de la série, ou `None` si ALFRED ne la connaît pas (SP500...)."""
    try:
        data = _get_json(VINTAGES_URL, {"series_id": series_id, "api_key": api_key, "file_type": "json",
                                        "realtime_start": FAR_PAST, "realtime_end": FAR_FUTURE}, session=session)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 400:
            return None
        raise
    return sorted(data.get("vintage_dates", []))


def _windows(vintages: list[str]) -> list[tuple[str, str]]:
    """Fenêtres de temps réel contenant chacune au plus `MAX_VINTAGES_PER_REQUEST` dates de vintage."""
    out = []
    for k in range(0, len(vintages), MAX_VINTAGES_PER_REQUEST):
        lo = FAR_PAST if k == 0 else vintages[k]
        last = k + MAX_VINTAGES_PER_REQUEST >= len(vintages)
        hi = FAR_FUTURE if last else vintages[k + MAX_VINTAGES_PER_REQUEST - 1]
        out.append((lo, hi))
    return out


def initial_releases(series_id: str, start: str, api_key: str, vintages: list[str], *, session=requests) -> pd.DataFrame:
    """Première publication de chaque observation : colonnes `obs_date`, `release_date`, `value`."""
    rows: list[tuple[str, str, float]] = []
    for lo, hi in _windows(vintages):
        data = _get_json(OBSERVATIONS_URL, {"series_id": series_id, "api_key": api_key, "file_type": "json",
                                            "observation_start": start, "realtime_start": lo, "realtime_end": hi,
                                            "output_type": 4}, session=session)
        rows += [(o["date"], o["realtime_start"], float(o["value"])) for o in data["observations"]
                 if o.get("value") not in (".", None, "")]
    frame = pd.DataFrame(rows, columns=["obs_date", "release_date", "value"])
    if frame.empty:
        return frame
    frame["obs_date"] = pd.to_datetime(frame["obs_date"])
    frame["release_date"] = pd.to_datetime(frame["release_date"])
    return frame.drop_duplicates("obs_date", keep="first").sort_values("obs_date").reset_index(drop=True)


def current_series(series_id: str, start: str, api_key: str, *, session=requests) -> pd.Series:
    """La série telle que révisée aujourd'hui (FRED), indexée sur la date de l'observation."""
    data = _get_json(OBSERVATIONS_URL, {"series_id": series_id, "api_key": api_key, "file_type": "json",
                                        "observation_start": start}, session=session)
    s = pd.Series({o["date"]: float(o["value"]) for o in data["observations"] if o["value"] != "."}, dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


# ------------------------------------------------------------------------------------------------ assemblage

def assemble(series_id: str, releases: pd.DataFrame, current: pd.Series, first_vintage: str | None) -> AlfredResult:
    """Première publication là où ALFRED en a, version actuelle datée par `publication_lag` avant (voir le module)."""
    mode = "fred"
    backfill = pd.Series(dtype="float64")
    alfred_part = pd.Series(dtype="float64")
    if not releases.empty:
        alfred_part = pd.Series(releases["value"].to_numpy(), index=pd.DatetimeIndex(releases["release_date"]))
        alfred_part = alfred_part[~alfred_part.index.duplicated(keep="last")]
        first_obs = releases["obs_date"].min()
        older = current[current.index < first_obs]
        if not older.empty:
            backfill = publication_lag.to_availability_index(older, series_id)
            backfill = backfill[backfill.index < alfred_part.index.min()]
        mode = "hybrid" if len(backfill) else "alfred"
    else:
        backfill = publication_lag.to_availability_index(current, series_id)
    series = pd.concat([backfill, alfred_part]).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    series.name = series_id
    info = {"mode": mode, "first_vintage": first_vintage, "n_alfred": len(alfred_part),
            "n_backfilled": len(backfill),
            "first_obs": None if releases.empty else str(releases["obs_date"].min().date()),
            "last_obs": str(max(current.index.max(), releases["obs_date"].max() if not releases.empty else current.index.max()).date())
            if len(current) or not releases.empty else None}
    return AlfredResult(series=series, mode=mode, info=info)


# ------------------------------------------------------------------------------------------------ cache

def _to_payload(releases: pd.DataFrame, current: pd.Series, first_vintage: str | None, start: str) -> dict:
    return {"start": start, "first_vintage": first_vintage,
            "releases": [[d.strftime("%Y-%m-%d"), r.strftime("%Y-%m-%d"), v]
                         for d, r, v in zip(releases["obs_date"], releases["release_date"], releases["value"])]
            if not releases.empty else [],
            "current": [[d.strftime("%Y-%m-%d"), float(v)] for d, v in current.items()]}


def _from_payload(payload: dict) -> tuple[pd.DataFrame, pd.Series, str | None]:
    rel = pd.DataFrame(payload.get("releases", []), columns=["obs_date", "release_date", "value"])
    if not rel.empty:
        rel["obs_date"] = pd.to_datetime(rel["obs_date"])
        rel["release_date"] = pd.to_datetime(rel["release_date"])
    cur = pd.Series({d: v for d, v in payload.get("current", [])}, dtype="float64")
    cur.index = pd.to_datetime(cur.index)
    return rel, cur.sort_index(), payload.get("first_vintage")


def _fresh(meta: dict, ttl_hours: float) -> bool:
    from patrick.clock import parse_utc, utc_now
    try:
        return (utc_now() - parse_utc(meta["updated_at"])).total_seconds() < ttl_hours * 3600
    except (KeyError, TypeError, ValueError):
        return False


def load_series_data(series_id: str, start: str, api_key: str, *, ttl_hours: float = CACHE_TTL_HOURS,
                     cache: LocalCache | None = None, session=requests, refresh: bool = False,
                     ) -> tuple[pd.DataFrame, pd.Series, str | None]:
    """(premières publications, version actuelle, premier vintage) d'une série, depuis le cache ou l'API."""
    cache = cache or LocalCache()
    key = f"{_CACHE_PREFIX}{series_id}"
    if not refresh:
        payload = cache.load_json(key, max_age_days=1)
        if payload and payload.get("start") == start and _fresh(cache.read_meta(key), ttl_hours):
            return _from_payload(payload)
    vintages = vintage_dates(series_id, api_key, session=session)
    releases = (initial_releases(series_id, start, api_key, vintages, session=session)
                if vintages else pd.DataFrame(columns=["obs_date", "release_date", "value"]))
    current = current_series(series_id, start, api_key, session=session)
    first_vintage = vintages[0] if vintages else None
    cache.save_json(key, _to_payload(releases, current, first_vintage, start))
    return releases, current, first_vintage


def alfred_series(series_id: str, start: str, api_key: str | None = None, *, name: str | None = None,
                  cache: LocalCache | None = None, session=requests, refresh: bool = False) -> AlfredResult:
    """La série `series_id` en première publication (voir le module). Ne lève jamais pour une panne d'ALFRED : repli `fred`."""
    api_key = api_key or os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} absente : ALFRED est inaccessible.")
    try:
        releases, current, first_vintage = load_series_data(series_id, start, api_key, cache=cache, session=session,
                                                            refresh=refresh)
    except Exception as exc:  # noqa: BLE001 -- une série en panne ne doit pas faire perdre les autres
        print(f"  [WARN] ALFRED {series_id}: {str(exc)[:100]} -- repli sur FRED + date de publication estimée.")
        current = current_series(series_id, start, api_key, session=session)
        releases, first_vintage = pd.DataFrame(columns=["obs_date", "release_date", "value"]), None
    result = assemble(series_id, releases, current, first_vintage)
    if name:
        result.series = result.series.rename(name)
    return result


# ------------------------------------------------------------------------------------------------ FRED contre ALFRED

def compare_with_fred(series_id: str, start: str, api_key: str | None = None, *, cache: LocalCache | None = None,
                      session=requests, refresh: bool = False) -> dict:
    """Ce que change ALFRED pour une série : révisions entre la première publication et la valeur actuelle, couverture,
    retard de publication réel contre l'hypothèse du tableau `publication_lag`. Pour la page Macro."""
    api_key = api_key or os.environ.get(API_KEY_ENV)
    releases, current, first_vintage = load_series_data(series_id, start, api_key, cache=cache, session=session,
                                                        refresh=refresh)
    out: dict = {"series": series_id, "first_vintage": first_vintage, "n_current": len(current),
                 "mode": "fred", "n_compared": 0}
    if releases.empty:
        out["note"] = "absente d'ALFRED" if first_vintage is None else "aucune première publication"
        return out
    first_obs = releases["obs_date"].min()
    out["mode"] = "hybrid" if (current.index < first_obs).any() else "alfred"
    out["first_obs"] = str(first_obs.date())
    out["lost_years_if_alfred_only"] = round(max(0.0, (first_obs - pd.Timestamp(start)).days / 365.25), 1)
    joined = releases.set_index("obs_date")["value"].to_frame("first").join(current.rename("now"), how="inner")
    if joined.empty:
        return out
    diff = (joined["now"] - joined["first"]).astype(float)
    scale = float(np.nanstd(current.diff().dropna())) or float(np.nanstd(current)) or 1.0
    tol = max(1e-9, 1e-6 * float(np.nanmean(np.abs(current))))
    lag_real = (releases["release_date"] - releases["obs_date"]).dt.days
    lag_est = pd.Series(
        (publication_lag.availability_dates(pd.DatetimeIndex(releases["obs_date"]), series_id)
         - pd.DatetimeIndex(releases["obs_date"])).days, index=releases.index)
    out.update(
        n_compared=len(joined),
        share_revised=float((diff.abs() > tol).mean()),
        mean_abs_revision=float(diff.abs().mean()),
        max_abs_revision=float(diff.abs().max()),
        revision_vs_move=float(diff.abs().mean() / scale) if scale else None,
        lag_real_days=float(lag_real.median()), lag_assumed_days=float(lag_est.median()),
    )
    return out
