"""Publication-timestamp guard for NLP / alternative data (roadmap bloc 3).

Any dated item -- a news story, a filing, a sentiment score, a product
announcement -- enters the feature row of session t only if it was
PUBLISHED before the close of t (plus a processing latency). The rule is
applied once, here, so no text/alt-data feature can bypass it:

- only `published_at` is accepted: the date a vendor attaches to the story
  (event date, fiscal period, "as of") is not when the market could read
  it. A missing publication timestamp is an error, never inferred;
- a timestamp after the close (or on a non-trading day) becomes visible at
  the next session; tz-aware timestamps are converted to the market's
  timezone, naive ones are read in it;
- a DATE-ONLY value (naive midnight) is ambiguous -- published at 07:00 or
  at 22:00? -- and becomes visible at the NEXT session. This is the
  opposite of `research.event_study.event_day_zero`, which reads a date as
  pre-open on purpose (to measure the reaction on the day): an event study
  may assume the earliest plausible time, a feature must assume the latest.

`event_features` then aggregates the aligned items per session: item
counts and mean value over trailing session windows, and sessions since the
last item. A window without any item gives a MISSING mean (not 0: "no
news" is not "neutral news").

No NLP source is wired into the pipeline: yfinance news only returns the
last few stories (no history to train on), and a licensed archive with
first-seen timestamps is the prerequisite. This module is the gate such a
source must go through.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MARKET_CLOSE = "16:00"
MARKET_TZ = "America/New_York"


def visible_session(published_at, trading_days, market_close: str = MARKET_CLOSE,
                    market_tz: str = MARKET_TZ, latency: str = "0min") -> pd.Timestamp | None:
    """First session at whose close the item is known: published strictly
    before that close. `None` beyond the calendar."""
    ts = pd.Timestamp(published_at)
    if pd.isna(ts):
        raise ValueError("published_at is missing")
    days = pd.DatetimeIndex(trading_days).normalize()
    if ts.tzinfo is not None:
        ts = ts.tz_convert(market_tz).tz_localize(None)
        date_only = False
    else:
        date_only = ts == ts.normalize()
    if date_only:
        pos = days.searchsorted(ts, side="right")
    else:
        ts = ts + pd.Timedelta(latency)
        day = ts.normalize()
        if ts >= pd.Timestamp(f"{day.date()} {market_close}"):
            day = day + pd.Timedelta(days=1)
        pos = days.searchsorted(day, side="left")
    return days[pos] if pos < len(days) else None


def align_items(items: pd.DataFrame, trading_days, **kwargs) -> pd.DataFrame:
    """`items` with a `visible_session` column; items beyond the calendar are
    dropped and counted in `attrs["dropped_after_calendar"]`."""
    if "published_at" not in items.columns:
        raise ValueError("items need a `published_at` column (publication time, not the story's date)")
    published = items["published_at"]
    missing = int(published.isna().sum())
    if missing:
        raise ValueError(f"{missing} item(s) without published_at: refusing to guess their visibility")
    out = items.copy()
    out["visible_session"] = [visible_session(p, trading_days, **kwargs) for p in published]
    dropped = int(out["visible_session"].isna().sum())
    out = out[out["visible_session"].notna()].copy()
    out["visible_session"] = pd.DatetimeIndex(out["visible_session"])
    out.attrs["dropped_after_calendar"] = dropped
    return out


def event_features(items: pd.DataFrame, trading_days, value_col: str | None = None,
                   windows=(1, 5, 20), prefix: str = "evt", **kwargs) -> pd.DataFrame:
    days = pd.DatetimeIndex(trading_days).normalize()
    aligned = align_items(items, days, **kwargs)
    grouped = aligned.groupby("visible_session")
    count = grouped.size().reindex(days, fill_value=0).astype(float)
    out: dict[str, pd.Series] = {}
    total = grouped[value_col].sum().reindex(days, fill_value=0.0) if value_col else None
    for w in windows:
        n_w = count.rolling(w, min_periods=1).sum()
        out[f"{prefix}_count_{w}d"] = n_w
        if total is not None:
            s_w = total.rolling(w, min_periods=1).sum()
            out[f"{prefix}_mean_{value_col}_{w}d"] = (s_w / n_w).where(n_w > 0)
    pos = pd.Series(np.arange(len(days), dtype=float), index=days)
    last = pos.where(count > 0).ffill()
    out[f"{prefix}_days_since"] = pos - last
    return pd.DataFrame(out, index=days)
