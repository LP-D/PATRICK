"""Page `/placements` (simulation complète de placements à partir de VL importées) et API `/api/placements/*`.

Le serveur ne fait que ranger les fichiers importés (`patrick.placements.store`) et lancer l'analyse en tâche de fond
(`patrick.placements.jobs`) ; la page lit le résultat par `/api/placements/datasets/{id}/result`. Aucun calcul avant l'affichage de la page.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from patrick.core import paths
from patrick.placements import (
    envelopes,
    jobs,
    loader,
    optimize,
    scenarios,
    service,
    stats,
    store,
)
from patrick.tabular import detect, reader
from patrick.webapp.i18n import core as i18n
from patrick.webapp.i18n.placements import PLACEMENTS_JS_KEYS

MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_FILES = 80


class AnalyseBody(BaseModel):
    horizon_years: int = Field(5, ge=1, le=service.MAX_HORIZON)
    objectives: list[str] = list(optimize.DEFAULT_OBJECTIVES)
    caps: list[float] = [1.0, 0.4]
    methods: list[str] = list(scenarios.METHODS)
    n_sims: int = Field(scenarios.N_SIMS, ge=1000, le=100_000)
    windows: list[str] = []
    reopt_months: int = Field(12, ge=1, le=60)
    min_train: int = Field(60, ge=12, le=240)


class FundBody(BaseModel):
    label: str | None = None
    kind: str | None = None
    category: str | None = None
    role: str | None = None
    min: float | None = None
    max: float | None = None
    set_bounds: bool = False                     # distingue « ne pas toucher aux bornes » de « bornes effacées » (null)
    excluded: bool | None = None


class RatesBody(BaseModel):
    name: str = "Fonds en euros"
    text: str
    category: str = "euro"


class ProfileBody(BaseModel):
    envelope: dict | None = None
    contributions: dict | None = None
    holdings: dict[str, float | None] | None = None
    groups: list[dict] | None = None
    couple: bool | None = None


class SettingsBody(BaseModel):
    name: str | None = None
    amount: float | None = None
    rf_annual: float | None = None
    cash: str | None = None
    set_cash: bool = False                       # distingue « ne pas toucher » de « aucun fonds monétaire » (cash = null)
    excluded: dict[str, bool] | None = None


def _problem(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _guard(fn):
    """Convertit les erreurs métier en réponses lisibles ; un disque de données absent donne 503 (pas une erreur de code)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except paths.DataRootUnavailable as exc:
            raise _problem(exc, 503) from exc
        except store.StoreError as exc:
            raise _problem(exc, 404 if "introuvable" in str(exc) else 400) from exc
        except (loader.LoaderError, service.AnalysisError, envelopes.EnvelopeError, detect.DetectError, reader.TabularError) as exc:
            raise _problem(exc) from exc
    return wrapper


async def _read_files(files: list[UploadFile] | None) -> list[tuple[str, bytes]]:
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Importez entre 1 et {MAX_FILES} fichiers.")
    out = []
    for f in files:
        data = await f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} dépasse {MAX_FILE_BYTES // (1024 * 1024)} Mo.")
        out.append((f.filename or "fichier", data))
    return out


def _ingest(dataset_id: str, uploads: list[tuple[str, bytes]]) -> list[dict]:
    """Importe chaque fichier avec le lecteur universel (toutes les séries de toutes les feuilles) ; un fichier illisible n'arrête pas les
    autres : il est rapporté avec son erreur. Chaque série dit ce qui a été deviné (type, fréquence, nom) et avec quelle confiance."""
    report = []
    for name, data in uploads:
        try:
            found, remarks = detect.detect(name, data)
            series = []
            for f in found:
                key, entry = store.add_found(dataset_id, f, name)
                series.append({"key": key, "label": entry["label"], "kind": entry["kind"], "frequency": entry["frequency"], "points": entry["points"],
                               "start": entry["start"], "end": entry["end"], "notes": entry["notes"], "confidence": entry["confidence"],
                               "category": entry["category"], "check": entry["checks"][-1]})
            report.append({"file": name, "ok": True, "series": series, "remarks": remarks[:6]})
        except (detect.DetectError, loader.LoaderError, store.StoreError) as exc:
            report.append({"file": name, "ok": False, "error": str(exc)})
    return report


def dataset_view(dataset_id: str) -> dict:
    """Méta du jeu de données + fenêtres d'étude possibles (calculées sans lancer l'analyse)."""
    meta = store.get_meta(dataset_id)
    out = {**meta, "windows": [], "has_result": store.load_result(dataset_id) is not None}
    try:
        navs, _ = store.load_navs(dataset_id)
        navs, cash = service.with_cash(navs, meta.get("cash"), meta.get("rf_annual", store.DEFAULT_RF))
        risky = [c for c in navs.columns if c != cash]
        if len(risky) >= service.MIN_RISKY:
            last = min(navs[c].dropna().index.max() for c in risky)
            r_all = stats.monthly_navs(navs, last).pct_change(fill_method=None)
            out["windows"] = service.candidate_windows(r_all, cash)
            out["last_common"] = last.date().isoformat()
    except (store.StoreError, ValueError):
        pass
    return out


def register(app: FastAPI, templates: Jinja2Templates, i18n_ctx: Callable[[Request], dict]) -> None:
    @app.get("/placements")
    def placements_page(request: Request):
        """Cadre seul : la page charge ses jeux de données et son dernier résultat par l'API (aucune lecture avant l'affichage)."""
        t = i18n.translator(i18n.get_lang(request))
        return templates.TemplateResponse(request, "placements.html", {"pl_i18n": {k: t(k) for k in PLACEMENTS_JS_KEYS}, **i18n_ctx(request)})

    @app.get("/api/placements/datasets")
    @_guard
    def list_datasets():
        return store.list_datasets()

    @app.post("/api/placements/datasets")
    async def create_dataset(name: str = Form(""), files: Annotated[list[UploadFile] | None, File()] = None):
        uploads = await _read_files(files)

        @_guard
        def work():
            dataset_id = store.create_dataset(name or "Mes fonds")
            report = _ingest(dataset_id, uploads)
            if not any(r["ok"] for r in report):
                store.delete_dataset(dataset_id)
                raise loader.LoaderError("Aucun fichier exploitable : " + " ; ".join(r["error"] for r in report))
            return {"id": dataset_id, "report": report, "dataset": dataset_view(dataset_id)}
        return await run_in_threadpool(work)

    @app.post("/api/placements/datasets/{dataset_id}/files")
    async def add_files(dataset_id: str, files: Annotated[list[UploadFile] | None, File()] = None):
        uploads = await _read_files(files)

        @_guard
        def work():
            store.get_meta(dataset_id)
            return {"report": _ingest(dataset_id, uploads), "dataset": dataset_view(dataset_id)}
        return await run_in_threadpool(work)

    @app.get("/api/placements/datasets/{dataset_id}")
    @_guard
    def get_dataset(dataset_id: str):
        return dataset_view(dataset_id)

    @app.post("/api/placements/datasets/{dataset_id}/settings")
    @_guard
    def update_settings(dataset_id: str, body: SettingsBody):
        store.update_settings(dataset_id, name=body.name, amount=body.amount, rf_annual=body.rf_annual,
                              cash=(body.cash if body.set_cash else False), excluded=body.excluded)
        return dataset_view(dataset_id)

    @app.get("/api/placements/catalog")
    def catalog():
        """Enveloppes et leurs paramètres par défaut, catégories, rôles et types de valeurs reconnus (pour les formulaires de la page)."""
        return {"envelopes": envelopes.ENVELOPES, "bounds": envelopes.BOUNDS, "categories": list(envelopes.CATEGORIES), "roles": list(envelopes.ROLES),
                "kinds": list(detect.KINDS), "objectives": list(optimize.OBJECTIVES), "default_objectives": list(optimize.DEFAULT_OBJECTIVES),
                "max_horizon": service.MAX_HORIZON, "contrib_defaults": envelopes.CONTRIB_DEFAULTS}

    @app.post("/api/placements/datasets/{dataset_id}/funds/{key}")
    @_guard
    def update_fund(dataset_id: str, key: str, body: FundBody):
        store.update_fund(dataset_id, key, label=body.label, kind=body.kind, category=body.category, role=body.role,
                          min_w=body.min if body.set_bounds else False, max_w=body.max if body.set_bounds else False, excluded=body.excluded)
        return dataset_view(dataset_id)

    @app.post("/api/placements/datasets/{dataset_id}/rates")
    @_guard
    def add_rates(dataset_id: str, body: RatesBody):
        store.add_rates(dataset_id, body.name, body.text, body.category)
        return dataset_view(dataset_id)

    @app.post("/api/placements/datasets/{dataset_id}/profile")
    @_guard
    def update_profile(dataset_id: str, body: ProfileBody):
        store.update_profile(dataset_id, envelope=body.envelope, contributions=body.contributions, holdings=body.holdings, groups=body.groups,
                             couple=body.couple)
        return dataset_view(dataset_id)

    @app.delete("/api/placements/datasets/{dataset_id}/funds/{key}")
    @_guard
    def delete_fund(dataset_id: str, key: str):
        store.remove_fund(dataset_id, key)
        return dataset_view(dataset_id)

    @app.delete("/api/placements/datasets/{dataset_id}")
    @_guard
    def delete_dataset(dataset_id: str):
        store.delete_dataset(dataset_id)
        return {"deleted": dataset_id}

    @app.post("/api/placements/datasets/{dataset_id}/analyse")
    @_guard
    def analyse(dataset_id: str, body: AnalyseBody):
        store.get_meta(dataset_id)
        params = service.Params(horizon_years=body.horizon_years, objectives=tuple(body.objectives), caps=tuple(body.caps),
                                methods=tuple(body.methods), n_sims=body.n_sims, windows=tuple(body.windows),
                                reopt_months=body.reopt_months, min_train=body.min_train)
        params.validate()
        return jobs.snapshot(jobs.start(dataset_id, params))

    @app.get("/api/placements/jobs/{job_id}")
    def job_status(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Analyse inconnue (le serveur a redémarré ?).")
        return jobs.snapshot(job)

    @app.get("/api/placements/datasets/{dataset_id}/result")
    @_guard
    def get_result(dataset_id: str):
        store.get_meta(dataset_id)
        result = store.load_result(dataset_id)
        if result is None:
            return JSONResponse({"result": None})
        return JSONResponse({"result": result})
