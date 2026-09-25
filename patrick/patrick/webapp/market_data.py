"""Lightweight market data for the web interface: mini history chart and
news on target change (the "what to predict?" panel), separate from the
`patrick.data.ingest` engine, which downloads/aligns/caches the whole
universe for a full run -- here we want a fast response for a single symbol.
"""
from __future__ import annotations

import datetime as dt

import pandas_datareader.data as web
import yfinance as yf

from patrick.clock import utc_today

PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "5y": 365 * 5, "max": None}
VALID_PERIODS = tuple(PERIOD_DAYS)


def price_history(symbol: str, source: str, period: str = "1y") -> dict:
    period = period if period in PERIOD_DAYS else "1y"

    if source == "fred":
        end = utc_today()
        days = PERIOD_DAYS[period]
        start = end - dt.timedelta(days=days) if days else dt.date(1970, 1, 1)
        try:
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

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in s.index],
        "closes": [round(float(v), 4) for v in s.values],
    }


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
            (c.get("canonicalUrl") or {}).get("url")
            or (c.get("clickThroughUrl") or {}).get("url")
            or ""
        )
        publisher = (c.get("provider") or {}).get("displayName", "")
        out.append({
            "title": title,
            "link": link,
            "publisher": publisher,
            "published": c.get("pubDate", ""),
        })
    return out
