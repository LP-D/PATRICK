"""Pages d'analyse des entraînements : `/runs/{id}/analyse` (un run ML, DL ou RL en détail), `/analyses` (tous les entraînements) et leurs
API JSON. Le cadre des pages s'affiche tout de suite ; chaque section arrive après, par `/api/runs/{id}/analysis/{section}` (voir
`patrick/analysis/`). Tout est en lecture seule."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick.analysis import hub, registry, rl_sections
from patrick.tracking import db as trackdb

ML_SECTIONS = ("overview", "guide", "protocol", "timeline", "rolling", "scatter", "confusion", "calibration", "folds", "equity", "errors",
               "features", "trials", "robustness", "holdout_live", "paths")
RL_SECTIONS = rl_sections.SECTIONS


def ml_sections_for(is_cpcv: bool) -> list[str]:
    return [s for s in ML_SECTIONS if s != "paths" or is_cpcv]


def _describe_run(conn, run_id: str) -> dict | None:
    """Ce que le cadre de la page doit savoir d'un run, ML/DL (table `run`) ou RL (table `job`) ; `None` si l'identifiant est inconnu."""
    run = trackdb.get_run(conn, run_id)
    if run is not None:
        try:
            cfg = json.loads(run.get("config_json") or "{}")
        except ValueError:
            cfg = {}
        scheme = (cfg.get("validation") or {}).get("scheme", "walkforward")
        return {"kind": trackdb.run_family(cfg), "mode": "ml", "run_id": run_id, "name": cfg.get("name") or run_id, "target": run["target"],
                "horizon": run["horizon"], "status": run["status"], "started_at": run["started_at"], "finished_at": run.get("finished_at"),
                "scheme": scheme, "snapshot_id": run.get("snapshot_id"), "config_hash": run.get("config_hash"), "git_sha": run.get("git_sha"),
                "seed": run.get("seed"), "sections": ml_sections_for(scheme == "cpcv")}
    rl = rl_sections.load_run(conn, run_id)
    if rl is not None:
        res = rl.result or {}
        obj = rl.config.get("objective") or {}
        return {"kind": "rl", "mode": "rl", "run_id": run_id, "name": res.get("name") or rl.config.get("name") or run_id,
                "target": res.get("target") or obj.get("target_symbol"), "horizon": (obj.get("horizons") or [1])[0], "status": rl.row["status"],
                "started_at": rl.row["started_at"] or rl.row["created_at"], "finished_at": rl.row["finished_at"], "scheme": "walkforward",
                "algo": res.get("algo") or (rl.config.get("rl") or {}).get("algo"), "sections": list(RL_SECTIONS)}
    return None


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    @app.get("/runs/{run_id}/analyse")
    def analyse_page(request: Request, run_id: str):
        conn = trackdb.connect()
        try:
            info = _describe_run(conn, run_id)
        finally:
            conn.close()
        if info is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        return templates.TemplateResponse(request, "run_analysis.html", {"info": info, **context(request)})

    @app.get("/api/runs/{run_id}/analysis/{section}")
    async def analysis_api(request: Request, run_id: str, section: str):
        params = dict(request.query_params)

        def work():
            conn = trackdb.connect()
            try:
                if trackdb.get_run(conn, run_id) is not None:
                    if section not in registry.SECTIONS:
                        return "unknown"
                    return registry.build(conn, run_id, section, params, db_key=trackdb.default_db_path())
                if rl_sections.is_rl_job(conn, run_id):
                    if section not in RL_SECTIONS:
                        return "unknown"
                    return rl_sections.build(conn, run_id, section)
                return None
            finally:
                conn.close()

        result = await run_in_threadpool(work)
        if result is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        if result == "unknown":
            raise HTTPException(status_code=404, detail="Section inconnue")
        return JSONResponse(result)

    @app.get("/analyses")
    def analyses_page(request: Request):
        return templates.TemplateResponse(request, "analyses.html", context(request))

    @app.get("/api/analyses/index")
    async def analyses_index():
        def work():
            conn = trackdb.connect()
            try:
                return hub.training_index(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/api/analyses/maps")
    async def analyses_maps():
        def work():
            conn = trackdb.connect()
            try:
                return hub.maps(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))
