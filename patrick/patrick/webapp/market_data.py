"""Lightweight market data for the web interface: mini history chart and
news on target change (the "what to predict?" panel), separate from the
`patrick.data.ingest` engine, which downloads/aligns/caches the whole
universe for a full run -- here we want a fast response for a single symbol.
"""
from __future__ import annotations

import datetime as dt
import os
import time

import pandas_datareader.data as web
import yfinance as yf

from patrick.clock import utc_today
from patrick.data.sources import fred_source
from patrick.data.sources.fred_source import FRED_API_KEY_ENV

PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "5y": 365 * 5, "max": None}
VALID_PERIODS = tuple(PERIOD_DAYS)


# /macro shows ~100 FRED series, each fetched on its own: a short-lived cache
# keeps a page reload from re-requesting them all (the FRED API is limited to
# 120 requests/minute). Successful answers only.
_FRED_CACHE_TTL_S = 1800
_fred_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def price_history(symbol: str, source: str, period: str = "1y") -> dict:
    period = period if period in PERIOD_DAYS else "1y"

    if source == "fred":
        cached = _fred_cache.get((symbol, period))
        if cached is not None and time.monotonic() - cached[0] < _FRED_CACHE_TTL_S:
            return cached[1]
        end = utc_today()
        days = PERIOD_DAYS[period]
        start = end - dt.timedelta(days=days) if days else dt.date(1970, 1, 1)
        try:
            if os.environ.get(FRED_API_KEY_ENV):
                # Official API when a key is set: the public CSV scrape is
                # the fragile path (see data/sources/fred_source.py).
                s = fred_source.download_series(symbol, symbol, start.isoformat())
                if s is None:
                    return {"dates": [], "closes": [], "error": f"FRED {symbol}: fetch failed"}
                s = s.dropna()
            else:
                s = web.DataReader(symbol, "fred", start, end).squeeze().dropna()
        except Exception as e:  # noqa: BLE001 -- provider boundary: the panel shows the error, the page stays up
            return {"dates": [], "closes": [], "error": str(e)[:200]}
    else:
        try:
            hist = yf.Ticker(symbol).history(period=period, interval="1d")
        except Exception as e:  # noqa: BLE001 -- provider boundary: the panel shows the error, the page stays up
            return {"dates": [], "closes": [], "error": str(e)[:200]}
        if hist is None or hist.empty:
            return {"dates": [], "closes": []}
        s = hist["Close"].dropna()

    out = {
        "dates": [d.strftime("%Y-%m-%d") for d in s.index],
        "closes": [round(float(v), 4) for v in s.values],
    }
    if source == "fred" and len(s):
        _fred_cache[(symbol, period)] = (time.monotonic(), out)
    return out


def _as_mapping(value):
    return value if isinstance(value, dict) else {}


def _url_from(candidate):
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        value = candidate.get("url") or ""
        return value if isinstance(value, str) else ""
    return ""


def _publisher_name(candidate):
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        value = candidate.get("displayName") or ""
        return value if isinstance(value, str) else ""
    return ""


def latest_news(symbol: str, limit: int = 6) -> list[dict]:
    try:
        items = yf.Ticker(symbol).news or []
    except Exception:  # noqa: BLE001 -- provider boundary: no news is a valid answer
        return []

    out = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        # Current payloads nest the article under `content`, legacy ones are
        # flat; `content` can also be null (seen live) -- never crash on it.
        c = item.get("content", item)
        if not isinstance(c, dict):
            continue
        title = c.get("title")
        if not title:
            continue
        link = (
            _url_from(c.get("canonicalUrl"))
            or _url_from(c.get("clickThroughUrl"))
            or ""
        )
        publisher = _publisher_name(c.get("provider"))
        out.append({
            "title": title,
            "link": link,
            "publisher": publisher,
            "published": c.get("pubDate", ""),
        })
    return out
