"""Données de marché légères pour l'interface web : mini-graphique d'historique
et actualités au changement de cible (fenêtre "que prédire ?"), séparées du
moteur `patrick.data.ingest` qui, lui, télécharge/aligne/cache tout l'univers
pour un run complet — ici on veut une réponse rapide pour un seul symbole.
"""
from __future__ import annotations

import datetime as dt

import pandas_datareader.data as web
import yfinance as yf

PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "5y": 365 * 5, "max": None}
VALID_PERIODS = tuple(PERIOD_DAYS)


def price_history(symbol: str, source: str, period: str = "1y") -> dict:
    period = period if period in PERIOD_DAYS else "1y"

    if source == "fred":
        end = dt.date.today()
        days = PERIOD_DAYS[period]
        start = end - dt.timedelta(days=days) if days else dt.date(1970, 1, 1)
        try:
            s = web.DataReader(symbol, "fred", start, end).squeeze().dropna()
        except Exception as e:
            return {"dates": [], "closes": [], "error": str(e)[:200]}
    else:
        try:
            hist = yf.Ticker(symbol).history(period=period, interval="1d")
        except Exception as e:
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
    except Exception:
        return []

    out = []
    for item in items[:limit]:
        c = item.get("content", item) if isinstance(item, dict) else {}
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
