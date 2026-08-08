"""Robust series-by-series FRED download (follows the pattern established in
VIX_FINAL_FEATURES/VIX_VAR_MACRO): one series failing does not lose the
others.

Two retrieval paths:
- Official FRED API (https://fred.stlouisfed.org/docs/api/fred/), used if the
  FRED_API_KEY environment variable is set (free key at
  https://fred.stlouisfed.org/docs/api/api_key.html). Stable, authenticated,
  doesn't depend on the public HTML/CSV.
- `pandas_datareader` (scrape of the public fredgraph.csv), used as a fallback
  if no key is provided. This is this module's historical path, but it is
  subject to blocking/format changes on fred.stlouisfed.org's side (observed:
  systematic failures on every FRED series while yfinance kept working) —
  hence the addition of the API path.

Phase 0.5 (ALFRED vintages): by default, the FRED API returns each series AS
REVISED TODAY (`realtime_start`/`realtime_end` default to today's date) —
January 2020's CPI, for instance, has been revised several times since its
first publication; using it as-is in a walk-forward backtest over 2020 is a
look-ahead bias (the model "sees" a revision that didn't exist yet at the
time). `download_series(..., realtime_date=...)` switches to ALFRED vintages
(same FRED endpoints, `realtime_start=realtime_end=<date>`): returns the
series as it was known at `realtime_date`, not today. Only the API path
allows this; the scrape fallback can historically only return the current
(latest) version of each series, never a past vintage —
`download_fred_universe` emits an explicit warning in that case.
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
        # ALFRED vintage: returns, for each observation date, the value as it
        # was known at `realtime_date` (not the current revision).
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
    """`realtime_date` (YYYY-MM-DD): fetches the ALFRED vintage known as of
    that date rather than the series as revised today — requires the API
    path (FRED_API_KEY set); silently ignored on the scrape fallback
    (impossible without the API, see module docstring)."""
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
    """series_map: {column_name: FRED_identifier}. `realtime_date`: see
    `download_series` — propagated to every series in the universe.

    `issues` (Phase 6.5, P6.5): if provided, every series with no data
    (fetch failure or discontinued series) adds a `QualityIssue` to it."""
    from patrick.data.quality import check_fred_missing

    api_key = os.environ.get(FRED_API_KEY_ENV)
    if not api_key:
        print("  [WARN] FRED_API_KEY not set: falling back to the public CSV scrape, which "
              "can only return the version REVISED TODAY of each series (no point-in-time "
              "vintage possible). Macro features derived from these series may therefore be "
              "ahead of the information actually available at the backtest's historical "
              "dates (look-ahead bias on revisions). "
              "Set FRED_API_KEY to enable ALFRED vintages (Phase 0.5).")
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
