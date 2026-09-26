"""Event lists for `patrick research event-study`.

- `read_events_csv`: `published_at` (publication time, market timezone
  unless an offset is given), optional `label` and `group` columns;
- `yahoo_earnings`: quarterly results with Yahoo's publication timestamp
  (after-close releases are stamped 16:00:00 ET, see
  `event_study.event_day_zero`) and the EPS surprise, grouped beat / miss /
  in line. Only past, reported quarters are kept.
"""
from __future__ import annotations

import pandas as pd


def read_events_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, comment="#")
    if "published_at" not in df.columns:
        raise ValueError(f"{path}: a `published_at` column is required (publication time, not the story's date)")
    if df["published_at"].isna().any():
        raise ValueError(f"{path}: {int(df['published_at'].isna().sum())} row(s) without published_at")
    df["label"] = df["label"] if "label" in df.columns else df["published_at"].astype(str)
    df["group"] = df["group"] if "group" in df.columns else "tous"
    return df[["published_at", "label", "group"]]


def _surprise_group(surprise: float, tolerance: float = 1.0) -> str:
    if surprise > tolerance:
        return "beat"
    if surprise < -tolerance:
        return "miss"
    return "en ligne"


def yahoo_earnings(ticker: str, limit: int = 60) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.Ticker(ticker).get_earnings_dates(limit=limit)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["published_at", "label", "group"])
    df = raw.dropna(subset=["Reported EPS"]).reset_index()
    date_col = df.columns[0]
    surprise = pd.to_numeric(df.get("Surprise(%)"), errors="coerce")
    out = pd.DataFrame({
        "published_at": df[date_col],
        "label": [f"{ts:%Y-%m-%d} ({s:+.1f} %)" if pd.notna(s) else f"{ts:%Y-%m-%d}"
                  for ts, s in zip(df[date_col], surprise)],
        "group": [_surprise_group(s) if pd.notna(s) else "n/d" for s in surprise],
    })
    return out.sort_values("published_at").reset_index(drop=True)
