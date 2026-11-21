"""Page `/strategies` (laboratoire de stratégies général) et API `/api/strategies/*`.

Le serveur valide la description de l'étude et lit les fichiers importés tout de suite (une erreur arrive en 400, pas après une minute de
téléchargement), puis lance l'étude en tâche de fond (`patrick.strategylab.jobs`). Les études terminées restent dans un historique : la page les
rouvre, les renomme, les épingle et les superpose pour les comparer.
"""
from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from patrick import paths
from patrick.strategylab import (
    backtest,
    data,
    events,
    indicators,
    jobs,
    rules,
    service,
    templates,
)
from patrick.tabular import detect, reader
from patrick.webapp import i18n
from patrick.webapp.i18n_strategies import STRATEGIES_JS_KEYS

MAX_FILE_BYTES = reader.MAX_BYTES
COST_PRESETS = {
    "online": {"commission": 0.10, "min_fee": 1.0, "fixed": 0.0, "slippage": 5.0},
    "bank": {"commission": 0.50, "min_fee": 8.0, "fixed": 0.0, "slippage": 10.0},
    "etf_zero": {"commission": 0.0, "min_fee": 0.0, "fixed": 0.0, "slippage": 3.0},
    "institutional": {"commission": 0.02, "min_fee": 0.0, "fixed": 0.0, "slippage": 2.0},
    "none": {"commission": 0.0, "min_fee": 0.0, "fixed": 0.0, "slippage": 0.0},
}


def _guard(fn):
    """Erreurs métier -> réponses lisibles (400) ; disque de données absent -> 503."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except paths.DataRootUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (jobs.USER_ERRORS + (detect.DetectError, reader.TabularError)) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return wrapper


async def _read(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    data_ = await upload.read(MAX_FILE_BYTES + 1)
    if len(data_) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"{upload.filename} dépasse {MAX_FILE_BYTES // (1024 * 1024)} Mo.")
    return data_


def prepare(spec_raw: str, prices_file: tuple[str, bytes] | None, events_file: tuple[str, bytes] | None) -> Callable[[Callable[[float, str], None]], dict]:
    """Valide tout (description, fichiers, nombre de téléchargements) et retourne la fonction à exécuter en tâche de fond."""
    try:
        spec = json.loads(spec_raw or "{}")
    except json.JSONDecodeError as exc:
        raise service.StudyError("Description de l'étude illisible.") from exc
    if not isinstance(spec, dict):
        raise service.StudyError("Description de l'étude illisible.")
    s = service.normalise(spec)
    strat, readable = service.compile_strategy(s)
    uploaded = None
    if prices_file is not None:
        uploaded, _notes = detect.detect_prices(prices_file[0], prices_file[1])
    book = data.PriceBook(uploaded, allow_yahoo=s["allow_yahoo"])
    needed = book.downloads_needed(list(dict.fromkeys(s["symbols"] + service.aux_symbols(strat, s["benchmark"]))))
    if len(needed) > data.MAX_DOWNLOADS:
        raise service.StudyError(f"{len(needed)} instruments à télécharger chez Yahoo, au plus {data.MAX_DOWNLOADS}.")
    file_events = None
    if readable["events"] and s["events"]["source"] == "file":
        if events_file is None:
            raise service.StudyError("Importez un fichier d'événements (symbole et date).")
        file_events = events.parse_events_any(events_file[0], events_file[1])

    def runner(progress: Callable[[float, str], None]) -> dict:
        return service.run(spec, book, progress, file_events=file_events)
    return runner


def catalog(lang: str) -> dict:
    return {"templates": templates.catalog(), "families": list(templates.FAMILIES), "indicators": indicators.INDICATORS, "ops": list(rules.OPS),
            "cost_presets": COST_PRESETS, "cost_defaults": service.COST_DEFAULTS, "freqs": list(backtest.FREQS), "sizing": list(backtest.SIZING),
            "max_symbols": data.MAX_TRADED, "max_grid": service.MAX_GRID}


def register(app: FastAPI, templates_: Jinja2Templates, i18n_ctx: Callable[[Request], dict]) -> None:
    @app.get("/strategies")
    def strategies_page(request: Request):
        """Cadre seul : catalogue, formulaires et résultats arrivent par l'API."""
        t = i18n.translator(i18n.get_lang(request))
        return templates_.TemplateResponse(request, "strategies.html", {"st_i18n": {k: t(k) for k in STRATEGIES_JS_KEYS}, **i18n_ctx(request)})

    @app.get("/api/strategies/catalog")
    def catalog_api(request: Request):
        return JSONResponse(catalog(i18n.get_lang(request)), headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/strategies/compile")
    @_guard
    def compile_api(body: dict):
        """Les règles d'un modèle et de ses paramètres, pour les afficher et les modifier dans le constructeur."""
        built = templates.compile_template(str(body.get("template") or "custom"), body.get("params") or {})
        return {k: v for k, v in built.items() if k != "build"}

    @app.post("/api/strategies/inspect")
    async def inspect(prices_file: Annotated[UploadFile, File()]):
        """Ce que contient un fichier de cours (symboles, premières et dernières dates), avant de lancer l'étude."""
        raw = await _read(prices_file)

        @_guard
        def work():
            if raw is None:
                raise service.StudyError("Fichier vide.")
            found, notes = detect.detect_prices(prices_file.filename, raw)
            return {"symbols": [{"symbol": k, "first": v.index[0].date().isoformat(), "last": v.index[-1].date().isoformat(), "points": len(v)}
                                for k, v in list(found.items())[:500]], "count": len(found), "notes": notes[:6]}
        return await run_in_threadpool(work)

    @app.post("/api/strategies/run")
    async def run(spec: Annotated[str, Form()], prices_file: Annotated[UploadFile | None, File()] = None, events_file: Annotated[UploadFile | None, File()] = None):
        prices_data, events_data = await _read(prices_file), await _read(events_file)

        @_guard
        def work():
            runner = prepare(spec, (prices_file.filename, prices_data) if prices_data else None, (events_file.filename, events_data) if events_data else None)
            return jobs.snapshot(jobs.start(runner))
        return await run_in_threadpool(work)

    @app.get("/api/strategies/jobs/{job_id}")
    def job_status(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Étude inconnue (le serveur a redémarré ?).")
        return jobs.snapshot(job)

    @app.get("/api/strategies/runs")
    @_guard
    def runs():
        return jobs.list_runs()

    @app.get("/api/strategies/runs/{run_id}")
    @_guard
    def run_detail(run_id: str):
        result = jobs.load_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Étude introuvable.")
        return JSONResponse(result)

    @app.post("/api/strategies/runs/{run_id}")
    @_guard
    def run_update(run_id: str, body: dict):
        return jobs.update_run(run_id, name=body.get("name"), pinned=body.get("pinned"))

    @app.delete("/api/strategies/runs/{run_id}")
    @_guard
    def run_delete(run_id: str):
        jobs.delete_run(run_id)
        return {"ok": True}
