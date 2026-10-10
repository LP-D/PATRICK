"""Page /exploration et API /api/exploration/* : études statistiques entre actifs (voir `patrick/exploration/`).

Les séries viennent des mêmes sources que le reste de l'application (yfinance via le cache local de 7 jours de
`data/sources/yfinance_source.download_one`, FRED via `webapp/market_data`) ; `loader` est une fonction de module pour que les tests
la remplacent sans réseau. Les panneaux alignés sont gardés en mémoire quelques minutes : changer d'étude sur la même sélection ne
retélécharge ni ne réaligne rien."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick.data.freshness import fred_periodicity
from patrick.exploration import panel as P
from patrick.exploration import studies as S
from patrick.webapp import forms, market_data

STUDIES = ("correlation", "rolling", "describe", "stationarity", "memory", "leadlag", "granger", "cointegration",
           "pca", "beta", "tail", "seasonality")
PANEL_TTL_S = 900
PANEL_CACHE_MAX = 12
_cache: OrderedDict[tuple, tuple[float, P.Panel]] = OrderedDict()
_lock = threading.Lock()


def loader(symbol: str, source: str) -> pd.Series | None:
    """Niveaux d'un symbole : FRED par l'API publique de l'application, sinon yfinance (cache local de 7 jours)."""
    if source == "fred":
        data = market_data.price_history(symbol, "fred", "max")
        if not data.get("dates"):
            return None
        return pd.Series(data["closes"], index=pd.to_datetime(data["dates"]))
    from patrick.data.sources import yfinance_source
    return yfinance_source.download_one(symbol, P.LONG_START)


# Sélections de départ (symboles absents de l'application ignorés) : clé de libellé i18n -> symboles.
PRESETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exp_preset_indices", ("^GSPC", "^NDX", "^STOXX50E", "^GDAXI", "^FTSE", "^N225")),
    ("exp_preset_risk", ("^GSPC", "^VIX", "DX-Y.NYB", "GC=F", "CL=F", "TLT", "HYG", "BTC-USD")),
    ("exp_preset_sectors", ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB")),
    ("exp_preset_commodities", ("GC=F", "SI=F", "HG=F", "CL=F", "NG=F", "ZC=F", "ZS=F")),
    ("exp_preset_rates", ("^IRX", "^FVX", "^TNX", "^TYX")),
)


def presets() -> list[dict]:
    out = []
    for key, syms in PRESETS:
        known = [s for s in syms if s in forms.TARGET_SOURCE_BY_SYMBOL]
        if len(known) >= 2:
            out.append({"label_key": key, "symbols": known})
    return out


def periodicity(symbol: str, source: str) -> str:
    return fred_periodicity(symbol) if source == "fred" else "daily"


def catalog(group_labels: dict[str, str]) -> list[dict]:
    """Groupes de cibles du formulaire de lancement : {group, label, items: [{symbol, label, source, periodicity}]}."""
    out = []
    for group, items in forms.TARGET_GROUPS.items():
        out.append({"group": group, "label": group_labels.get(group, group), "items": [
            {"symbol": sym, "label": lab, "source": forms.TARGET_SOURCE_BY_SYMBOL.get(sym, "yfinance"),
             "periodicity": periodicity(sym, forms.TARGET_SOURCE_BY_SYMBOL.get(sym, "yfinance"))}
            for sym, lab in items]})
    return out


def _parse_date(raw: str | None, name: str) -> str | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"« {name} » : date AAAA-MM-JJ attendue.") from exc


def get_panel(symbols: list[str], start: str | None, end: str | None, freq: str, transform: str) -> P.Panel:
    key = (tuple(symbols), start, end, freq, transform)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < PANEL_TTL_S:
            _cache.move_to_end(key)
            return hit[1]
    sources = {s: forms.TARGET_SOURCE_BY_SYMBOL.get(s, "yfinance") for s in symbols}
    unknown = [s for s in symbols if s not in forms.TARGET_SOURCE_BY_SYMBOL]
    if unknown:
        raise P.PanelError("Symbole inconnu : " + ", ".join(unknown))
    pan = P.build_panel(symbols, sources, loader, start=start, end=end, freq=freq, transform=transform, periodicity=periodicity)
    with _lock:
        _cache[key] = (now, pan)
        while len(_cache) > PANEL_CACHE_MAX:
            _cache.popitem(last=False)
    return pan


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _pick(name: str, value: str | None, valid: list[str], dropped: dict[str, str] | None = None) -> str:
    if value and dropped and value in dropped:
        raise ValueError(f"« {name} » : {value} n'a pas pu être chargé ({dropped[value]}).")
    if not value or value not in valid:
        raise ValueError(f"« {name} » : choisis un actif de la sélection.")
    return value


def run_study(study: str, pan: P.Panel, params: dict) -> dict:
    cols = list(pan.returns.columns)
    ret, lev = pan.returns, pan.levels
    if study == "correlation":
        return S.correlation(ret, params.get("method", "pearson"))
    if study == "describe":
        return S.describe(ret, lev, pan.periods_per_year, pan.transforms)
    if study == "stationarity":
        return S.stationarity(lev, ret)
    if study == "pca":
        return S.pca(ret, int(params.get("n_components", 5)))
    a = _pick("a", params.get("a"), cols, pan.dropped)
    if study == "memory":
        return S.memory(ret[a], int(params.get("nlags", 20)))
    if study == "seasonality":
        return S.seasonality(ret[a], pan.freq)
    if study == "beta":
        bench = _pick("bench", params.get("b"), cols, pan.dropped)
        return S.beta_alpha(ret, a, bench, int(params.get("window", 60)), pan.periods_per_year)
    b = _pick("b", params.get("b"), cols, pan.dropped)
    if study == "rolling":
        return S.rolling_correlation(ret, a, b, int(params.get("window", 60)))
    if study == "leadlag":
        return S.cross_correlation(ret, a, b, int(params.get("maxlag", 10)))
    if study == "granger":
        return S.granger(ret, a, b, int(params.get("maxlag", 5)))
    if study == "cointegration":
        return S.cointegration(lev, a, b, int(params.get("zwindow", 60)))
    if study == "tail":
        return S.tail_dependence(ret, a, b, float(params.get("q", 0.05)))
    raise ValueError("étude inconnue")


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    @app.get("/exploration")
    def exploration_page(request: Request):
        ctx = context(request)
        return templates.TemplateResponse(request, "exploration.html", {**ctx, "catalog": catalog(ctx["group_labels"]), "presets": presets()})

    @app.get("/api/exploration/catalog")
    def exploration_catalog(request: Request):
        return {"groups": catalog(context(request)["group_labels"])}

    @app.get("/api/exploration/{study}")
    async def exploration_study(study: str, request: Request):
        if study not in STUDIES:
            raise HTTPException(status_code=404, detail="Étude inconnue")
        q = request.query_params
        symbols = [s for s in (q.get("symbols") or "").split(",") if s]
        freq = q.get("freq", "D")
        transform = q.get("transform", "auto")
        start, end = _parse_date(q.get("start"), "start"), _parse_date(q.get("end"), "end")

        def work() -> dict:
            pan = get_panel(symbols, start, end, freq, transform)
            result = run_study(study, pan, dict(q))
            return {"study": study, "meta": pan.meta(), "result": result}

        try:
            return await run_in_threadpool(work)
        except (P.PanelError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

