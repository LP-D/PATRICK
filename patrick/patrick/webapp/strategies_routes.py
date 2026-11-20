"""Page `/strategies` (laboratoire de stratégies autour d'événements) et API `/api/strategies/*`.

Le serveur valide les fichiers importés tout de suite (une erreur arrive en 400, pas après une minute de calcul) puis lance l'étude en tâche de fond
(`patrick.strategylab.jobs`) ; la page lit l'avancement et le dernier résultat. Les cours viennent d'abord du fichier importé, puis de Yahoo.
"""
from __future__ import annotations

import functools
import json
from collections.abc import Callable
from dataclasses import fields

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from patrick import paths
from patrick.strategylab import core, events, jobs, prices, service, straddle
from patrick.webapp import i18n
from patrick.webapp.i18n_strategies import STRATEGIES_JS_KEYS

MAX_FILE_BYTES = 40 * 1024 * 1024
SOURCES = ("file", "yahoo", "preset")


def _guard(fn):
    """Erreurs métier -> réponses lisibles (400) ; disque de données absent -> 503."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except paths.DataRootUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (core.StrategyError, events.EventsError, prices.PricesError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return wrapper


def _params(kind: str, raw: str):
    """Les paramètres JSON de la page -> `EventParams` ou `StraddleParams` (clés inconnues refusées, valeurs validées)."""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise core.StrategyError("Paramètres illisibles.") from exc
    cls = core.EventParams if kind == "event" else straddle.StraddleParams
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise core.StrategyError(f"Paramètre inconnu : {', '.join(unknown)}.")
    try:
        params = cls(**data)
    except TypeError as exc:
        raise core.StrategyError(f"Paramètres invalides : {exc}") from exc
    params.validate()
    return params


async def _read(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"{upload.filename} dépasse {MAX_FILE_BYTES // (1024 * 1024)} Mo.")
    return data


def prepare(kind: str, source: str, params_raw: str, tickers: str, preset: str, quarters: int, events_file: tuple[str, bytes] | None,
            prices_file: tuple[str, bytes] | None, fallback: bool = False) -> Callable[[Callable[[float, str], None]], dict]:
    """Valide toutes les entrées et retourne la fonction à exécuter en tâche de fond. Les résultats trimestriels Yahoo (réseau) sont chargés dans la tâche."""
    if kind not in jobs.KINDS:
        raise core.StrategyError("Type d'étude inconnu.")
    if source not in SOURCES:
        raise core.StrategyError("Source d'événements inconnue.")
    params = _params(kind, params_raw)
    ev = None
    symbols: list[str] = []
    if source == "file":
        if events_file is None:
            raise core.StrategyError("Importez un fichier d'événements.")
        ev = events.parse_events_csv(events_file[1], events_file[0])
        symbols = list(ev["symbol"].unique())
    elif source == "preset":
        if preset not in events.PRESETS:
            raise core.StrategyError("Préréglage inconnu.")
        ev = events.PRESETS[preset]()
        symbols = list(ev["symbol"].unique())
    else:
        symbols = events.parse_symbols(tickers)
        if not symbols:
            raise core.StrategyError("Indiquez au moins un symbole (ex. AAPL, MSFT).")
        if not 4 <= quarters <= 80:
            raise core.StrategyError("Le nombre de trimestres doit être compris entre 4 et 80.")
    price_source = prices.YahooPrices()
    if prices_file is not None:
        # Un fichier de cours importé est la seule source, sauf demande explicite : ses symboles absents (titres disparus d'une étude IPO) ne se téléchargent pas,
        # et il serait absurde d'en réclamer des milliers à Yahoo. Ils sont comptés dans les événements écartés.
        price_source = prices.UploadedPrices(prices_file[1], prices_file[0], fallback=price_source if fallback else None)
    needed = prices.downloads_needed(symbols, price_source)
    if len(needed) > events.MAX_SYMBOLS:
        raise core.StrategyError(f"{len(needed)} symboles à télécharger chez Yahoo, au plus {events.MAX_SYMBOLS} : importez un fichier de cours ou réduisez la liste.")

    def runner(progress: Callable[[float, str], None]) -> dict:
        nonlocal ev
        if ev is None:
            progress(0.02, "Résultats trimestriels")
            ev = events.yahoo_earnings_events(symbols, limit=quarters)
        if kind == "event":
            return service.run_event(ev, price_source, params, progress)
        return service.run_straddle(ev, price_source, params, progress)
    return runner


def register(app: FastAPI, templates: Jinja2Templates, i18n_ctx: Callable[[Request], dict]) -> None:
    @app.get("/strategies")
    def strategies_page(request: Request):
        """Cadre seul : formulaires et dernier résultat arrivent par l'API."""
        t = i18n.translator(i18n.get_lang(request))
        return templates.TemplateResponse(request, "strategies.html", {"st_i18n": {k: t(k) for k in STRATEGIES_JS_KEYS}, "presets": list(events.PRESETS), **i18n_ctx(request)})

    @app.post("/api/strategies/run")
    async def run(kind: str = Form(...), source: str = Form("file"), params: str = Form("{}"), tickers: str = Form(""), preset: str = Form(""),
                  quarters: int = Form(40), fallback: bool = Form(False), events_file: UploadFile | None = File(default=None),
                  prices_file: UploadFile | None = File(default=None)):
        events_data, prices_data = await _read(events_file), await _read(prices_file)

        @_guard
        def work():
            runner = prepare(kind, source, params, tickers, preset, quarters, (events_file.filename, events_data) if events_data else None,
                             (prices_file.filename, prices_data) if prices_data else None, fallback)
            return jobs.snapshot(jobs.start(kind, runner))
        return await run_in_threadpool(work)

    @app.get("/api/strategies/jobs/{job_id}")
    def job_status(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Étude inconnue (le serveur a redémarré ?).")
        return jobs.snapshot(job)

    @app.get("/api/strategies/last/{kind}")
    @_guard
    def last(kind: str):
        return JSONResponse({"result": jobs.load_last(kind)})
