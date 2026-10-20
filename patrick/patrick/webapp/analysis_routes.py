"""Pages d'analyse des entraînements : `/runs/{id}/analyse` (un run ML, DL ou RL en détail), `/analyses` (tous les entraînements) et leurs
API JSON. Le cadre des pages s'affiche tout de suite ; chaque section arrive après, par `/api/runs/{id}/analysis/{section}` (voir
`patrick/analysis/`). Tout est en lecture seule."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from patrick.analysis import compare as compare_mod
from patrick.analysis import (
    drift_monitor,
    exports,
    features_explorer,
    guardrails,
    hub,
    journal_view,
    model_registry,
    registry,
    rl_sections,
)
from patrick.tracking import db as trackdb
from patrick.tracking import journal as journal_mod
from patrick.tracking import research_notes
from patrick.webapp import i18n

STATIC = Path(__file__).resolve().parent / "static"
_ML_SCRIPTS = ("analysis_kit.js", "analysis_loader.js", "run_analysis.js", "run_analysis_more.js")
_RL_SCRIPTS = ("analysis_kit.js", "analysis_loader.js", "rl_analysis.js")

ML_SECTIONS = ("overview", "guide", "protocol", "timeline", "rolling", "scatter", "confusion", "calibration", "folds", "equity", "errors", "regimes",
               "features", "trials", "robustness", "holdout_live", "paths", "notes")
RL_SECTIONS = rl_sections.SECTIONS


class NoteBody(BaseModel):
    kind: str
    title: str
    body: str = ""
    tags: str | None = None
    target: str | None = None
    horizon: int | None = None
    run_id: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: str | None = None
    status: str | None = None


class PromoteBody(BaseModel):
    target: str
    horizon: int
    run_id: str


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value)[:80]


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

    @app.get("/api/runs/{run_id}/export/predictions.csv")
    async def export_predictions(run_id: str):
        def work():
            conn = trackdb.connect()
            try:
                return exports.predictions_csv(conn, run_id)
            finally:
                conn.close()
        body = await run_in_threadpool(work)
        if body is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="predictions_{_safe_name(run_id)}.csv"'})

    @app.get("/api/runs/{run_id}/export/equity.csv")
    async def export_equity(run_id: str, cost_bps: float = 5.0):
        def work():
            conn = trackdb.connect()
            try:
                return exports.equity_csv(conn, run_id, max(0.0, min(500.0, cost_bps)))
            finally:
                conn.close()
        body = await run_in_threadpool(work)
        if body is None:
            raise HTTPException(status_code=404, detail="Courbes indisponibles pour ce run")
        return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="equite_{_safe_name(run_id)}.csv"'})

    @app.get("/runs/{run_id}/analyse/export")
    async def analyse_export(request: Request, run_id: str):
        """Rapport autonome : un seul fichier HTML (styles, scripts et données de toutes les sections), lisible hors ligne et imprimable en PDF."""
        def work():
            conn = trackdb.connect()
            try:
                info = _describe_run(conn, run_id)
                if info is None:
                    return None, None
                if info["mode"] == "ml":
                    return info, exports.all_sections(conn, run_id, trackdb.default_db_path())
                data = {}
                for name in RL_SECTIONS:
                    data[name] = rl_sections.build(conn, run_id, name)
                return info, data
            finally:
                conn.close()
        info, data = await run_in_threadpool(work)
        if info is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        ctx = context(request)
        scripts = _ML_SCRIPTS if info["mode"] == "ml" else _RL_SCRIPTS
        js = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in scripts)
        css = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in ("patrick.css", "analysis.css"))
        embed = json.dumps(data or {}, ensure_ascii=False).replace("</", "<\\/")
        i18n_js = i18n.js_strings(ctx["lang"], f"/runs/{run_id}/analyse")
        page = templates.get_template("run_analysis_export.html").render(
            {"info": info, "t": ctx["t"], "lang": ctx["lang"], "css": css, "js": js.replace("</script", "<\\/script"), "embed_json": embed, "i18n_js": i18n_js,
             "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")})  # noqa: DTZ005 -- horodatage local voulu, comme les sauvegardes
        return HTMLResponse(page, headers={"Content-Disposition": f'attachment; filename="analyse_{_safe_name(run_id)}.html"'})

    @app.get("/analyses/comparer")
    def analyses_compare_page(request: Request, run_ids: Annotated[list[str] | None, Query()] = None):
        ids = list(dict.fromkeys(run_ids or []))
        if not 2 <= len(ids) <= compare_mod.MAX_RUNS:
            raise HTTPException(status_code=400, detail="Sélectionne entre 2 et 4 runs à comparer.")
        conn = trackdb.connect()
        try:
            known = [trackdb.get_run(conn, i) is not None for i in ids]
        finally:
            conn.close()
        if not all(known):
            raise HTTPException(status_code=404, detail="Un run sélectionné est introuvable (ou est un run RL : se comparent depuis l'Historique).")
        return templates.TemplateResponse(request, "analyses_compare.html", {"run_ids": ids, **context(request)})

    @app.get("/api/analyses/compare")
    async def analyses_compare_api(run_ids: Annotated[list[str] | None, Query()] = None, cost_bps: float = 5.0, window: int = 120):
        ids = list(dict.fromkeys(run_ids or []))
        if not 2 <= len(ids) <= compare_mod.MAX_RUNS:
            raise HTTPException(status_code=400, detail="Sélectionne entre 2 et 4 runs à comparer.")

        def work():
            conn = trackdb.connect()
            try:
                return compare_mod.compare(conn, ids, max(0.0, min(500.0, cost_bps)), max(10, min(2000, window)), trackdb.default_db_path())
            finally:
                conn.close()
        result = await run_in_threadpool(work)
        if result is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        return JSONResponse(result)

    @app.get("/garde-fous")
    def guardrails_page(request: Request):
        return templates.TemplateResponse(request, "garde_fous.html", context(request))

    @app.get("/api/garde-fous/summary")
    async def guardrails_summary():
        def work():
            conn = trackdb.connect()
            try:
                return guardrails.summary(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/carnet")
    def notebook_page(request: Request):
        return templates.TemplateResponse(request, "carnet.html", context(request))

    @app.get("/api/carnet/notes")
    async def notebook_list(q: str | None = None, kind: str | None = None, status: str | None = None, tag: str | None = None, archived: int = 0,
                            run_id: str | None = None, target: str | None = None, horizon: int | None = None):
        return JSONResponse({"notes": await _journal(lambda c: research_notes.list_notes(
            c, q=q, kind=kind, status=status, tag=tag, include_archived=bool(archived), run_id=run_id, target=target, horizon=horizon))})

    @app.get("/api/carnet/stats")
    async def notebook_stats():
        return JSONResponse(await _journal(research_notes.stats))

    @app.post("/api/carnet/notes")
    async def notebook_create(body: NoteBody):
        try:
            nid = await _journal(lambda c: research_notes.create(c, body.kind, body.title, body.body, body.tags, body.target, body.horizon, body.run_id))
        except research_notes.NoteError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"note_id": nid})

    @app.post("/api/carnet/notes/{note_id}")
    async def notebook_update(note_id: int, body: NoteUpdate):
        try:
            await _journal(lambda c: research_notes.update(c, note_id, title=body.title, body=body.body, tags=body.tags, status=body.status))
        except research_notes.NoteError as exc:
            raise HTTPException(status_code=400 if str(exc) != "not_found" else 404, detail=str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.get("/journal")
    def journal_page(request: Request):
        return templates.TemplateResponse(request, "journal.html", context(request))

    def _journal(fn):
        def work():
            conn = trackdb.connect()
            try:
                return fn(conn)
            finally:
                conn.close()
        return run_in_threadpool(work)

    @app.get("/api/journal/overview")
    async def journal_overview():
        return JSONResponse(await _journal(journal_view.overview))

    @app.get("/api/journal/entries")
    async def journal_entries(target: str | None = None, limit: int = 100, offset: int = 0):
        return JSONResponse(await _journal(lambda c: journal_view.entries(c, target, limit, offset)))

    @app.get("/api/journal/verify")
    async def journal_verify():
        return JSONResponse(await _journal(journal_view.verify))

    @app.get("/api/journal/export.csv")
    async def journal_export():
        body = await _journal(journal_view.export_csv)
        return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="journal_predictions.csv"'})

    @app.post("/api/journal/seal")
    async def journal_seal():
        return JSONResponse(await _journal(journal_mod.seal_existing))

    @app.get("/modeles")
    def models_page(request: Request):
        return templates.TemplateResponse(request, "modeles.html", {"card_mode": False, **context(request)})

    @app.get("/modeles/fiche")
    def model_card_page(request: Request, target: str, horizon: int):
        return templates.TemplateResponse(request, "modeles.html", {"card_mode": True, "target": target, "horizon": horizon, **context(request)})

    @app.get("/api/modeles/overview")
    async def models_overview():
        def work():
            conn = trackdb.connect()
            try:
                return model_registry.overview(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/api/modeles/card")
    async def models_card(target: str, horizon: int):
        def work():
            conn = trackdb.connect()
            try:
                return model_registry.model_card(conn, target, horizon, trackdb.default_db_path())
            finally:
                conn.close()
        card = await run_in_threadpool(work)
        if card is None:
            raise HTTPException(status_code=404, detail="Aucun modèle exporté pour ce couple")
        return JSONResponse(card)

    @app.post("/api/modeles/promote")
    async def models_promote(body: PromoteBody):
        def work():
            conn = trackdb.connect()
            try:
                return model_registry.promote_version(conn, body.target, body.horizon, body.run_id, "manual")
            finally:
                conn.close()
        try:
            return JSONResponse(await run_in_threadpool(work))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/derive")
    def drift_page(request: Request):
        return templates.TemplateResponse(request, "derive.html", context(request))

    @app.get("/api/derive/overview")
    async def drift_overview():
        def work():
            conn = trackdb.connect()
            try:
                return drift_monitor.overview(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/api/derive/detail")
    async def drift_detail(target: str, horizon: int):
        def work():
            conn = trackdb.connect()
            try:
                return drift_monitor.pair_detail(conn, target, horizon)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/variables")
    def variables_page(request: Request):
        return templates.TemplateResponse(request, "variables.html", context(request))

    @app.get("/api/variables/overview")
    async def variables_overview():
        def work():
            conn = trackdb.connect()
            try:
                return features_explorer.overview(conn)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

    @app.get("/api/variables/detail")
    async def variables_detail(feature: str):
        if not feature or len(feature) > 300:
            raise HTTPException(status_code=400, detail="Variable invalide")

        def work():
            conn = trackdb.connect()
            try:
                return features_explorer.feature_detail(conn, feature)
            finally:
                conn.close()
        return JSONResponse(await run_in_threadpool(work))

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
