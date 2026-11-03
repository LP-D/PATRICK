"""Page /econometrie et API /api/econometrics/* : l'économétrie d'UNE série à la fois (calculs purs dans `patrick/econometrics/`).

Les séries viennent des mêmes sources que le reste de l'application (`exploration_routes.loader` : Yahoo via le cache local, FRED via
`market_data`) ; `loader` et `ohlc_loader` sont des fonctions de module pour que les tests les remplacent sans réseau.
Chaque résultat est mis en cache sur disque (`econometrics_cache`) sous une clé qui contient l'empreinte des données : la même demande ne se recalcule pas.

Les études s'appliquent à :
- la série TRANSFORMÉE choisie (log-rendement par défaut) : `unitroot`, `dependence`, `mean` ;
- les RENDEMENTS (log, ou différences si le niveau n'est pas toujours > 0) quelle que soit la transformation : `variance*`, `har`, `regimes`, `forecast`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick.econometrics import forecast_eval as F
from patrick.econometrics import mean_models as M
from patrick.econometrics import regimes as RG
from patrick.econometrics import serial as SE
from patrick.econometrics import transforms as T
from patrick.econometrics import unitroot as U
from patrick.econometrics import variance_models as V
from patrick.exploration import panel as P
from patrick.exploration import studies as S
from patrick.webapp import econometrics_cache as EC
from patrick.webapp import exploration_routes as E
from patrick.webapp import forms

log = logging.getLogger(__name__)

STUDIES = ("series", "unitroot", "dependence", "mean", "variance", "variance_grid", "har", "regimes", "forecast")
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4}
PROXIES = ("none", "r2", "parkinson", "garman_klass")
RANGE_PROXIES = ("parkinson", "garman_klass")
SEASONAL_ORDER = (1, 0, 0, 12)
MIN_LEVELS = 60
_inflight: dict[str, threading.Lock] = {}
_inflight_guard = threading.Lock()


def loader(symbol: str, source: str) -> pd.Series | None:
    return E.loader(symbol, source)


def ohlc_loader(symbol: str) -> pd.DataFrame | None:
    from patrick.data.sources import yfinance_source

    return yfinance_source.download_ohlc(symbol, P.LONG_START)


def clear_cache() -> None:
    with _inflight_guard:
        _inflight.clear()


# ---------------------------------------------------------------- paramètres
class Params:
    """Lecture validée des paramètres de requête : une valeur hors bornes est une erreur affichable (400), jamais une valeur silencieusement corrigée."""

    def __init__(self, q) -> None:
        self.q = q

    def int(self, name: str, default: int, lo: int, hi: int) -> int:
        raw = self.q.get(name)
        if raw in (None, ""):
            return default
        try:
            v = int(raw)
        except ValueError as exc:
            raise ValueError(f"« {name} » : entier attendu.") from exc
        if not lo <= v <= hi:
            raise ValueError(f"« {name} » : entre {lo} et {hi} attendu (reçu {v}).")
        return v

    def float(self, name: str, default: float, lo: float, hi: float) -> float:
        raw = self.q.get(name)
        if raw in (None, ""):
            return default
        try:
            v = float(raw)
        except ValueError as exc:
            raise ValueError(f"« {name} » : nombre attendu.") from exc
        if not lo <= v <= hi:
            raise ValueError(f"« {name} » : entre {lo} et {hi} attendu (reçu {v}).")
        return v

    def bool(self, name: str, default: bool = False) -> bool:
        raw = self.q.get(name)
        return default if raw in (None, "") else str(raw).lower() in ("1", "true", "yes", "on")

    def choice(self, name: str, default: str, valid) -> str:
        raw = self.q.get(name) or default
        if raw not in valid:
            raise ValueError(f"« {name} » : {raw} inconnu (attendu : {', '.join(valid)}).")
        return raw

    def csv(self, name: str, default: str, valid=None, maximum: int = 12) -> list[str]:
        items = [s.strip() for s in (self.q.get(name) or default).split(",") if s.strip()]
        if not items or len(items) > maximum:
            raise ValueError(f"« {name} » : entre 1 et {maximum} éléments attendus.")
        if valid is not None:
            bad = [i for i in items if i not in valid]
            if bad:
                raise ValueError(f"« {name} » : {', '.join(bad)} inconnu (attendu : {', '.join(valid)}).")
        return items


def _parse_date(raw: str | None, name: str) -> str | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"« {name} » : date AAAA-MM-JJ attendue.") from exc


# ---------------------------------------------------------------- données
@dataclass
class Prepared:
    symbol: str
    source: str
    periodicity: str
    levels: pd.Series
    ohlc: pd.DataFrame | None
    x: pd.Series                    # série transformée choisie
    info: dict
    returns: pd.Series              # rendements (log, ou différences si le niveau change de signe)

    @property
    def ppy(self) -> int:
        return PERIODS_PER_YEAR.get(self.periodicity, 252)

    @property
    def seasonal_period(self) -> int | None:
        return 12 if self.periodicity == "monthly" else None


def _norm_ohlc(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or len(df) == 0:
        return None
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    out = df.copy()
    out.index = idx.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def prepare(symbol: str, start: str | None, end: str | None, transform: str, d: float = 0.4, *, want_ohlc: bool = False) -> Prepared:
    source = forms.TARGET_SOURCE_BY_SYMBOL.get(symbol)
    if source is None:
        raise ValueError(f"Symbole inconnu : {symbol or '(aucun)'}")
    try:
        raw = loader(symbol, source)
    except Exception as exc:
        msg = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:120]
        raise ValueError(f"{symbol} n'a pas pu être chargé ({msg}).") from exc
    levels = P._clean_levels(raw)
    if levels is None:
        raise ValueError(f"Aucune donnée disponible pour {symbol}.")
    if start:
        levels = levels[levels.index >= pd.Timestamp(start)]
    if end:
        levels = levels[levels.index <= pd.Timestamp(end)]
    if len(levels) < MIN_LEVELS:
        raise ValueError(f"Seulement {len(levels)} observations sur la période demandée : minimum {MIN_LEVELS}.")
    periodicity = E.periodicity(symbol, source)
    ohlc = None
    if source == "yfinance" and (want_ohlc or transform in T.NEEDS_OHLC):
        try:
            ohlc = _norm_ohlc(ohlc_loader(symbol))
        except Exception as exc:
            raise ValueError(f"Les prix OHLC de {symbol} n'ont pas pu être chargés ({str(exc)[:100]}).") from exc
        if ohlc is not None:
            ohlc = ohlc[(ohlc.index >= levels.index.min()) & (ohlc.index <= levels.index.max())] if len(levels) else ohlc
    x, info = T.apply_transform(levels, transform, ohlc=ohlc, d=d)
    returns, _ = T.apply_transform(levels, "logret")
    return Prepared(symbol, source, periodicity, levels, ohlc, x, info, returns)


def proxy_variance(prep: Prepared, which: str) -> pd.Series | None:
    """Variance journalière de référence (décimale) : r^2, ou Parkinson / Garman-Klass depuis les prix OHLC."""
    if which == "none":
        return None
    if which == "r2":
        return prep.returns ** 2
    v, _ = T.apply_transform(prep.levels, which, ohlc=prep.ohlc)
    return v.reindex(prep.returns.index).dropna()


def meta_of(prep: Prepared) -> dict:
    x = prep.x
    return {"symbol": prep.symbol, "source": prep.source, "periodicity": prep.periodicity, "periods_per_year": prep.ppy, "n_obs": len(x),
            "n_levels": len(prep.levels), "start": x.index[0].strftime("%Y-%m-%d") if len(x) else None,
            "end": x.index[-1].strftime("%Y-%m-%d") if len(x) else None, "transform": prep.info, "seasonal_period": prep.seasonal_period,
            "ohlc_possible": prep.source == "yfinance"}


# ---------------------------------------------------------------- études
def _regressor(prep: Prepared, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
    other = prepare(symbol, start, end, "logret")
    if other.periodicity != prep.periodicity:
        raise ValueError("Le régresseur doit avoir la même fréquence que la série étudiée.")
    # retardé d'une période : la valeur de la veille explique celle d'aujourd'hui (jamais la valeur du jour, qui regarderait « à côté » de l'avenir)
    return other.returns.shift(1).rename(symbol).reindex(prep.x.index).to_frame()


def run_study(study: str, prep: Prepared, p: Params, start: str | None, end: str | None) -> dict:
    x, ret = prep.x, prep.returns
    if study == "series":
        return {"dates": [d.strftime("%Y-%m-%d") for d in x.index], "values": x.to_numpy(), "transform": prep.info}
    if study == "unitroot":
        trend = p.choice("trend", "c", ("c", "ct"))
        out = {"unit_root": U.unit_root_tests(x, trend=trend)}
        try:
            out["zivot_andrews"] = U.zivot_andrews(x, regression="c" if trend == "c" else "ct")
        except ValueError as exc:
            out["zivot_andrews"] = {"error": str(exc)}
        try:
            out["variance_ratio"] = S.variance_ratio(x)
        except ValueError as exc:
            out["variance_ratio"] = {"error": str(exc)}
        h = S.hurst_exponent(pd.Series(np.cumsum(x.to_numpy())))
        out["hurst"] = {"value": h, "label": S._hurst_label(h)}
        return S.clean(out)
    if study == "dependence":
        return SE.dependence_summary(x, p.int("nlags", 20, 5, 60))
    if study == "mean":
        max_p, max_q, d = p.int("max_p", 2, 0, 3), p.int("max_q", 2, 0, 3), p.int("d", 0, 0, 2)
        seasonal = p.bool("seasonal")
        if seasonal and prep.seasonal_period is None:
            raise ValueError("La composante saisonnière n'a de sens que sur une série mensuelle.")
        reg = p.q.get("regressor") or ""
        exog = _regressor(prep, reg, start, end) if reg else None
        res = M.fit_arma_grid(x, max_p=max_p, max_q=max_q, d=d, seasonal_order=SEASONAL_ORDER if seasonal else None, exog=exog)
        try:
            res["gph"] = M.gph_d(x)
        except ValueError as exc:
            res["gph"] = {"error": str(exc)}
        return res
    if study == "variance":
        model, dist = p.choice("model", "garch", V.MODELS), p.choice("dist", "normal", V.DISTS)
        proxy = proxy_variance(prep, p.choice("proxy", "none", PROXIES))
        return V.fit_variance_model(ret, model, dist, p.choice("mean", "constant", V.MEANS), periods_per_year=prep.ppy, proxy=proxy, with_bds=p.bool("bds"))
    if study == "variance_grid":
        return V.fit_variance_grid(ret, tuple(p.csv("models", "garch,gjr,egarch", V.MODELS)), tuple(p.csv("dists", "normal,t,skewt", V.DISTS)),
                                   p.choice("mean", "constant", V.MEANS))
    if study == "har":
        proxy = proxy_variance(prep, p.choice("proxy", "parkinson" if prep.ohlc is not None else "r2", PROXIES[1:]))
        return V.fit_har(proxy, log=p.bool("log"))
    if study == "regimes":
        if p.choice("method", "ms", ("ms", "hmm")) == "hmm":
            return RG.hmm_reading(ret, candidates=tuple(range(2, p.int("max_states", 3, 2, 4) + 1)))
        return RG.markov_switching(ret, k_regimes=p.int("k", 2, 2, 3), switching_mean=p.bool("switching_mean", True),
                                   switching_variance=p.bool("switching_variance", True))
    if study == "forecast":
        specs = p.csv("specs", "garch|normal,gjr|t,riskmetrics", maximum=8)
        which = p.choice("proxy", "r2", PROXIES[1:])
        proxy = proxy_variance(prep, which)
        window = p.int("window", 0, 0, 5000) or None
        return F.evaluate_forecasts(ret, proxy, specs, min_train=p.int("min_train", F.MIN_TRAIN, 250, 5000), refit_every=p.int("refit_every", F.REFIT_EVERY, 10, 500),
                                    window=window, benchmark=p.q.get("benchmark") or None, mcs_reps=p.int("reps", 500, 100, 2000), proxy_label=which)
    raise ValueError("étude inconnue")


def _wants_ohlc(study: str, q) -> bool:
    which = q.get("proxy") or ("parkinson" if study == "har" else "")
    return which in RANGE_PROXIES


def _cache_parts(study: str, prep: Prepared, q) -> dict:
    drop = {"symbol", "start", "end", "transform"}
    return {"study": study, "symbol": prep.symbol, "source": prep.source, "transform": prep.info.get("kind"), "d": prep.info.get("d"),
            "levels": EC.fingerprint(prep.levels), "ohlc": EC.fingerprint(prep.ohlc["High"] - prep.ohlc["Low"]) if prep.ohlc is not None else None,
            "q": sorted((k, v) for k, v in dict(q).items() if k not in drop and v not in (None, ""))}


def compute_cached(study: str, prep: Prepared, q, start: str | None, end: str | None) -> tuple[dict, bool]:
    key = EC.cache_key(**_cache_parts(study, prep, q))
    hit = EC.load(key)
    if hit is not None:
        return hit["result"], True
    with _inflight_guard:
        lock = _inflight.setdefault(key, threading.Lock())
    with lock:                                          # deux clics rapprochés sur « Calculer » : le second attend le premier, ne recalcule pas
        hit = EC.load(key)
        if hit is not None:
            return hit["result"], True
        result = S.clean(run_study(study, prep, Params(q), start, end))
        if study != "series":
            EC.save(key, {"study": study, "result": result})
    return result, False


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    @app.get("/econometrie")
    def econometrics_page(request: Request):
        ctx = context(request)
        return templates.TemplateResponse(request, "econometrics.html", {**ctx, "catalog": E.catalog(ctx["group_labels"]), "transforms": T.TRANSFORMS,
                                                                       "models": V.MODELS, "dists": V.DISTS})

    @app.get("/api/econometrics/{study}")
    async def econometrics_study(study: str, request: Request):
        if study not in STUDIES:
            raise HTTPException(status_code=404, detail="Étude inconnue")
        q = request.query_params
        start, end = _parse_date(q.get("start"), "start"), _parse_date(q.get("end"), "end")

        def work() -> dict:
            p = Params(q)
            transform = p.choice("transform", "logret", T.TRANSFORMS) if study in ("series", "unitroot", "dependence", "mean") else "logret"
            prep = prepare(q.get("symbol", ""), start, end, transform, p.float("d_frac", 0.4, 0.05, 0.95), want_ohlc=_wants_ohlc(study, q))
            result, cached = compute_cached(study, prep, q, start, end)
            return {"study": study, "meta": meta_of(prep), "result": result, "cached": cached}

        try:
            return await run_in_threadpool(work)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("econometrics %s", study)
            return JSONResponse({"error": f"Calcul impossible ({exc.__class__.__name__} : {str(exc)[:140]})"}, status_code=500)
