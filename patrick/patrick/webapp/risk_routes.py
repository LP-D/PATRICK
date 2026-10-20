"""Page `/risque` (risque du portefeuille, simulation marche avant, écarts à une cible) et API `/api/risque/*`. Lecture seule : les cours
viennent du fournisseur de prix du patrimoine (`wealth.prices`), les positions du registre (`wealth.ledger`). Calculs dans
`patrick/analysis/portfolio_risk.py`."""
from __future__ import annotations

import threading
import time
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick.analysis import portfolio_risk as pr
from patrick.tracking import db as trackdb
from patrick.wealth import prices as wealth_prices

CACHE_TTL_S = 90.0
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def _cached(key: tuple, fn) -> dict:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    value = fn()
    with _lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = (time.monotonic(), value)
    return value


PROVIDER_TTL_S = 300.0
_provider: tuple[float, object] | None = None


def _shared_provider():
    """Un seul fournisseur de cours (donc une seule mémoire de séries) pour les trois appels que la page lance en parallèle, renouvelé toutes les 5 minutes :
    sans cela chaque appel téléchargerait les mêmes séries."""
    global _provider
    now = time.monotonic()
    with _lock:
        if _provider is None or now - _provider[0] > PROVIDER_TTL_S:
            _provider = (now, wealth_prices.make_provider())
        return _provider[1]


def _with_holdings(source: str, fn) -> dict:
    conn = trackdb.connect()
    try:
        provider = _shared_provider()
        holdings = pr.resolve_holdings(conn, provider, source)
        return fn(holdings, provider)
    finally:
        conn.close()


def register(app: FastAPI, templates, context) -> None:
    @app.get("/risque")
    def risk_page(request: Request):
        return templates.TemplateResponse(request, "risque.html", context(request))

    @app.get("/api/risque/sources")
    async def risk_sources():
        def work():
            conn = trackdb.connect()
            try:
                from patrick.wealth import ledger
                return [{"account_id": a["account_id"], "name": a["name"], "mode": a["mode"], "kind": a["kind"]} for a in ledger.list_accounts(conn)]
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/api/risque/report")
    async def risk_report(source: str = "real", lookback: Annotated[int, Query(ge=0, le=5000)] = 504):
        key = ("report", source, lookback)
        return JSONResponse(await run_in_threadpool(_cached, key, lambda: _with_holdings(source, lambda h, p: pr.risk_report(h, p, lookback or 100_000))))

    @app.get("/api/risque/backtest")
    async def risk_backtest(source: str = "real", lookback: Annotated[int, Query(ge=60, le=1000)] = 252, rebalance: Annotated[int, Query(ge=1, le=252)] = 21,
                            cost: Annotated[float, Query(ge=0, le=500)] = 10.0):
        key = ("bt", source, lookback, rebalance, cost)
        return JSONResponse(await run_in_threadpool(_cached, key, lambda: _with_holdings(source, lambda h, p: pr.backtest(h, p, lookback=lookback, rebalance_days=rebalance, cost_bps=cost))))

    @app.get("/api/risque/rebalance")
    async def risk_rebalance(source: str = "real", method: str = "hrp", tolerance: Annotated[float, Query(ge=0, le=0.5)] = 0.05,
                             cost: Annotated[float, Query(ge=0, le=500)] = 10.0):
        if method not in pr.METHODS:
            raise HTTPException(status_code=422, detail="Méthode inconnue")
        key = ("gaps", source, method, tolerance, cost)
        return JSONResponse(await run_in_threadpool(_cached, key, lambda: _with_holdings(source, lambda h, p: pr.rebalance_gaps(h, p, method, tolerance, cost))))
