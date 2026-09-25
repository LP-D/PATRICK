"""Live verification of yfinance tickers before they enter the universe
(roadmap bloc 2: "39 new Yahoo tickers unverified"; bloc 4: "massively
enlarge the universe").

A ticker is accepted only if Yahoo actually serves it: a non-empty daily
history, fresh (last quote at most `max_stale_bdays` business days old),
deep enough (`min_obs` observations) for walk-forward folds plus a
12-month holdout. Everything else is reported with the reason -- never
silently dropped, never silently kept.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from patrick.clock import utc_today

MIN_OBS = 750           # ~3 years of sessions: >= 3 walk-forward folds + a 12-month holdout
MAX_STALE_BDAYS = 7

Fetcher = Callable[[str], "pd.Series | None"]


def default_fetcher(symbol: str) -> pd.Series | None:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=True)
    if hist is None or hist.empty or "Close" not in hist:
        return None
    s = hist["Close"]
    s.index = pd.DatetimeIndex(s.index).tz_localize(None) if s.index.tz is not None else pd.DatetimeIndex(s.index)
    return s


def check_ticker(symbol: str, fetch: Fetcher = default_fetcher, today=None,
                 min_obs: int = MIN_OBS, max_stale_bdays: int = MAX_STALE_BDAYS) -> dict:
    today = pd.Timestamp(today or utc_today()).normalize()
    out = {"symbol": symbol, "status": "error", "n_obs": 0, "first": None, "last": None,
           "stale_bdays": None, "reason": None}
    try:
        s = fetch(symbol)
    except Exception as exc:  # noqa: BLE001 -- provider boundary: the reason is the report's content
        out["reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out
    s = s.dropna() if s is not None else None
    if s is None or s.empty:
        out.update(status="empty", reason="aucune cotation servie par Yahoo")
        return out
    s = s[np.isfinite(s.to_numpy(dtype=float))]
    last = pd.Timestamp(s.index.max()).normalize()
    stale = max(int(np.busday_count(last.date(), today.date())) - 1, 0) if last < today else 0
    out.update(n_obs=len(s), first=s.index.min().date().isoformat(), last=last.date().isoformat(),
               stale_bdays=stale)
    if stale > max_stale_bdays:
        out.update(status="stale", reason=f"dernière cotation il y a {stale} séances")
    elif len(s) < min_obs:
        out.update(status="short", reason=f"{len(s)} séances < {min_obs} requises")
    else:
        out.update(status="ok")
    return out


def check_many(symbols: list[str], fetch: Fetcher = default_fetcher, workers: int = 8, **kwargs) -> list[dict]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda s: check_ticker(s, fetch, **kwargs), symbols))


def render_markdown(results: list[dict]) -> str:
    lines = ["| Ticker | Statut | Séances | Première | Dernière | Retard (séances) | Motif |",
             "|---|---|---:|---|---|---:|---|"]
    order = {"ok": 0, "short": 1, "stale": 2, "empty": 3, "error": 4}
    for r in sorted(results, key=lambda r: (order.get(r["status"], 9), r["symbol"])):
        lines.append(f"| {r['symbol']} | {r['status']} | {r['n_obs']} | {r['first'] or '—'} | {r['last'] or '—'} "
                     f"| {r['stale_bdays'] if r['stale_bdays'] is not None else '—'} | {r['reason'] or ''} |")
    n_ok = sum(r["status"] == "ok" for r in results)
    lines.append(f"\n{n_ok}/{len(results)} ticker(s) acceptés.")
    return "\n".join(lines)
