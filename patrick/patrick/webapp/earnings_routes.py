"""Page /resultats et ses fragments : événements de résultats (newsletter -> confirmation -> vue semaine -> bibliothèque d'études).

Règle « la page s'ouvre tout de suite » : /resultats n'envoie que son cadre (comptages SQL). Tout le reste arrive par `/fragments/earn-*`
ou à la demande : une carte d'étude ne se calcule qu'au clic puis sort du cache. Le réseau (analyse de la newsletter, ingestion, instantanés)
tourne dans des fils d'arrière-plan, un par nature, suivis par `/api/earnings/status`.
`provider_factory` et `conn_factory` sont des fonctions de module : les tests les remplacent, aucun test ne touche le réseau.
"""
from __future__ import annotations

import re
import threading
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from patrick.clock import local_now
from patrick.earnings import consensus, parse, pipeline, schedule, service, store
from patrick.earnings.config import DEFAULT, RETURN_MODELS, TESTS, EarningsConfig
from patrick.earnings.panel import Scope, load_panel
from patrick.earnings.studies import (
    GROUP_TITLES,
    GROUPS,
    REGISTRY,
    Ctx,
    fdr_ledger,
    run_study,
)
from patrick.earnings.studies.runner import ledger_inputs
from patrick.tracking import db as trackdb
from patrick.webapp import earnings_render

WARN_FLAGS = ("introuvable", "nom différent", "ambigu", "symbole inconnu de Yahoo", "aucune action trouvée")
_SYMBOL = re.compile(r"^[A-Za-z0-9.^=\-_]{1,20}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT = 60_000
JOB_KINDS = ("parse", "process", "snapshot", "recompute")

_lock = threading.Lock()


def _blank() -> dict:
    return {"running": False, "done": 0, "total": 0, "label": "", "error": None, "result": None}


_jobs: dict[str, dict] = {k: _blank() for k in JOB_KINDS}


def provider_factory():
    from patrick.earnings.provider import YahooProvider
    return YahooProvider()


def conn_factory():
    return trackdb.connect()


def load_cfg(conn) -> EarningsConfig:
    try:
        return EarningsConfig.from_dict(store.get_state(conn, "config", {})).validate()
    except ValueError:
        return DEFAULT


def _check_symbol(symbol: str) -> str:
    if not _SYMBOL.match(symbol or ""):
        raise HTTPException(status_code=400, detail="symbole invalide")
    return symbol


def _scope(text: str | None) -> Scope:
    try:
        return Scope.parse(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _start(kind: str, target, *args) -> bool:
    """Lance `target(*args, progress)` dans un fil si aucun travail de cette nature ne tourne. `target` renvoie le résultat JSON."""
    with _lock:
        if _jobs[kind]["running"]:
            return False
        _jobs[kind] = {**_blank(), "running": True}

    def progress(done, total, label="", *_):
        with _lock:
            _jobs[kind].update(done=done, total=total, label=str(label))

    def run():
        try:
            result = target(*args, progress)
            outcome = {"result": result, "error": None}
        except Exception as exc:  # noqa: BLE001 -- fil d'arrière-plan : toute erreur est rapportée à la page, jamais perdue
            outcome = {"result": None, "error": str(exc) or type(exc).__name__}
        with _lock:
            _jobs[kind].update(running=False, **outcome)

    threading.Thread(target=run, name=f"earnings-{kind}", daemon=True).start()
    return True


def _ctx(conn, cfg: EarningsConfig, scope: Scope, batch_id: int | None = None) -> Ctx:
    full = load_panel(conn, cfg)
    symbols = [i["symbol"] for i in store.batch_items(conn, batch_id) if i["symbol"]] if (scope.kind == "batch" and batch_id) else []
    return Ctx(full.with_scope(scope, symbols), full, conn, provider_factory(), cfg, scope, batch_symbols=symbols)


def _study_params(request: Request, study) -> dict:
    return {p.key: request.query_params.get(f"p_{p.key}") for p in study.params if request.query_params.get(f"p_{p.key}") not in (None, "")}


def register(app: FastAPI, templates, i18n_context) -> None:
    templates.env.globals["earn_fmt"] = earnings_render.fmt
    templates.env.globals["earn_line"] = earnings_render.line_svg
    templates.env.globals["earn_bars"] = earnings_render.bars_svg
    templates.env.globals["earn_spark"] = earnings_render.spark

    @app.get("/resultats")
    def earnings_page(request: Request, batch: int | None = None, scope: str = "all"):
        scope_obj = _scope(scope)
        conn = conn_factory()
        try:
            store.ensure_schema(conn)
            cfg = load_cfg(conn)
            h = cfg.measure_hash()
            n_events, n_symbols = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM earn_result WHERE cfg_hash = ?", (h,)).fetchone()
            batches = store.list_batches(conn)
            current = store.get_batch(conn, batch) if batch else (store.get_batch(conn, batches[0]["batch_id"]) if batches else None)
            counts = store.snapshot_counts(conn)
            sectors = [r[0] for r in conn.execute("SELECT DISTINCT json_extract(payload_json, '$.sector') FROM earn_instrument").fetchall() if r[0]]
        finally:
            conn.close()
        ctx = {"summary": {"n_events": n_events, "n_symbols": n_symbols, "n_batches": len(batches), "n_snapshots": sum(counts.values())},
               "batches": batches, "batch": current, "anchor": parse.default_anchor_monday(local_now().date()).isoformat(), "cfg": cfg.to_dict(),
               "scope": scope_obj.key, "sectors": sorted(sectors), "models": RETURN_MODELS, "tests": TESTS, "groups": GROUPS,
               "group_titles": GROUP_TITLES, "default_cfg": DEFAULT.to_dict()}
        return templates.TemplateResponse(request, "earnings.html", {**ctx, **i18n_context(request)})

    # ------------------------------------------------------------------------------------------------------- API : travaux
    @app.post("/api/earnings/parse")
    async def api_parse(request: Request):
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise HTTPException(status_code=400, detail="texte vide ou trop long")
        anchor = body.get("anchor") or ""
        if anchor and not _DATE.match(anchor):
            raise HTTPException(status_code=400, detail="date invalide")
        anchor_date = date.fromisoformat(anchor) if anchor else None

        def work(progress):
            conn = conn_factory()
            try:
                batch_id, warnings = service.create_batch(conn, provider_factory(), text, anchor_date, progress)
                return {"batch_id": batch_id, "warnings": warnings}
            finally:
                conn.close()

        return {"started": _start("parse", work)}

    @app.post("/api/earnings/confirm")
    async def api_confirm(request: Request):
        body = await request.json()
        batch_id = int(body.get("batch_id", 0))
        edits = body.get("edits") or []
        for e in edits:
            for key in ("symbol", "adr_symbol"):
                if e.get(key):
                    _check_symbol(e[key].strip())
        conn = conn_factory()
        try:
            if store.get_batch(conn, batch_id) is None:
                raise HTTPException(status_code=404, detail="lot inconnu")
            outcome = service.confirm_batch(conn, batch_id, edits)
            cfg = load_cfg(conn)
        finally:
            conn.close()

        def work(progress):
            return {**outcome, "batch_id": batch_id, "ingest": _summarize(service.process_batch(conn_factory, provider_factory(), batch_id, cfg, progress))}

        return {"started": _start("process", work), **outcome}

    @app.post("/api/earnings/snapshot")
    def api_snapshot():
        conn = conn_factory()
        try:
            symbols = consensus.tracked_symbols(conn)
        finally:
            conn.close()

        def work(progress):
            c = conn_factory()
            try:
                return consensus.take_snapshots(c, provider_factory(), symbols, progress=progress)
            finally:
                c.close()

        return {"started": _start("snapshot", work), "symbols": len(symbols)}

    @app.post("/api/earnings/recompute")
    def api_recompute():
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM earn_calendar").fetchall()]
        finally:
            conn.close()

        def work(progress):
            return _summarize({"reports": pipeline.ingest_many(conn_factory, provider_factory(), symbols, cfg, progress, refresh_calendar=False)})

        return {"started": _start("recompute", work), "symbols": len(symbols)}

    @app.get("/api/earnings/status")
    def api_status():
        with _lock:
            return JSONResponse({k: dict(v) for k, v in _jobs.items()})

    @app.post("/api/earnings/config")
    async def api_config(request: Request):
        body = await request.json()
        try:
            cfg = EarningsConfig.from_dict(body).validate()
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn = conn_factory()
        try:
            store.put_state(conn, "config", cfg.to_dict())
            have = conn.execute("SELECT COUNT(*) FROM earn_result WHERE cfg_hash = ?", (cfg.measure_hash(),)).fetchone()[0]
            known = conn.execute("SELECT COUNT(DISTINCT symbol) FROM earn_calendar").fetchone()[0]
        finally:
            conn.close()
        return {"saved": True, "needs_recompute": have == 0 and known > 0}

    @app.post("/api/earnings/manual-dates")
    async def api_manual_dates(request: Request):
        body = await request.json()
        symbol = _check_symbol(body.get("symbol", ""))
        try:
            rows = schedule.parse_manual_dates(symbol, body.get("text", ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn = conn_factory()
        try:
            store.upsert_calendar(conn, rows, keep_user=False)
            cfg = load_cfg(conn)
            rep = pipeline.ingest_symbol(conn, provider_factory(), symbol, cfg, refresh_calendar=False)
        finally:
            conn.close()
        return {"added": len(rows), "events": rep.n_events, "errors": rep.errors}

    @app.get("/api/earnings/aliases")
    def api_aliases():
        conn = conn_factory()
        try:
            return {"aliases": store.list_aliases(conn)}
        finally:
            conn.close()

    @app.post("/api/earnings/alias/delete")
    async def api_alias_delete(request: Request):
        body = await request.json()
        conn = conn_factory()
        try:
            store.delete_alias(conn, str(body.get("alias", "")))
        finally:
            conn.close()
        return {"deleted": True}

    # ------------------------------------------------------------------------------------------------------------ fragments
    @app.get("/fragments/earn-confirm")
    def frag_confirm(request: Request, batch: int):
        conn = conn_factory()
        try:
            items = store.batch_items(conn, batch)
            meta = store.get_batch(conn, batch)
        finally:
            conn.close()
        if meta is None:
            raise HTTPException(status_code=404, detail="lot inconnu")
        for it in items:
            it["flag_view"] = [{"text": f, "warn": f in WARN_FLAGS} for f in it["flags"]]
            it["warn"] = any(f["warn"] for f in it["flag_view"])
        return templates.TemplateResponse(request, "_earn_confirm.html", {"items": items, "batch": meta, **i18n_context(request)})

    @app.get("/fragments/earn-week")
    def frag_week(request: Request, batch: int):
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            meta = store.get_batch(conn, batch)
            if meta is None:
                raise HTTPException(status_code=404, detail="lot inconnu")
            rows = service.week_rows(conn, batch, cfg)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_earn_week.html", {"rows": rows, "batch": meta, "cfg": cfg, **i18n_context(request)})

    @app.get("/fragments/earn-library")
    def frag_library(request: Request, scope: str = "all", batch: int | None = None):
        scope_obj = _scope(scope)
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            panel = load_panel(conn, cfg)
            n_scope = panel.with_scope(scope_obj, [i["symbol"] for i in store.batch_items(conn, batch) if i["symbol"]] if batch else []).n
            ctx = Ctx(panel, panel, conn, None, cfg, scope_obj)
            done = set()
            for sid, st in REGISTRY.items():
                from patrick.earnings.studies.runner import data_version
                if store.cached_study_rows(conn, scope_obj.key, {sid: data_version(ctx, st)}):
                    done.add(sid)
        finally:
            conn.close()
        by_group = {g: [s for s in REGISTRY.values() if s.group == g] for g in GROUPS}
        return templates.TemplateResponse(request, "_earn_library.html", {"by_group": by_group, "group_titles": GROUP_TITLES, "done": done,
                                                                         "scope": scope_obj.key, "n_scope": n_scope, "batch": batch, **i18n_context(request)})

    @app.get("/fragments/earn-study")
    def frag_study(request: Request, study: str, scope: str = "all", batch: int | None = None, force: int = 0):
        if study not in REGISTRY:
            raise HTTPException(status_code=404, detail="étude inconnue")
        scope_obj = _scope(scope)
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            ctx = _ctx(conn, cfg, scope_obj, batch)
            try:
                result = run_study(ctx, study, _study_params(request, REGISTRY[study]), force=bool(force))
            except (ValueError, KeyError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_earn_study.html", {"res": result, "study": REGISTRY[study], **i18n_context(request)})

    @app.get("/fragments/earn-ledger")
    def frag_ledger(request: Request, scope: str = "all", batch: int | None = None, alpha: float = 0.10):
        scope_obj = _scope(scope)
        if not 0.01 <= alpha <= 0.25:
            raise HTTPException(status_code=400, detail="alpha hors de [0.01, 0.25]")
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            ledger = fdr_ledger(ledger_inputs(_ctx(conn, cfg, scope_obj, batch)), alpha)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_earn_ledger.html", {"ledger": ledger, "scope": scope_obj.key, **i18n_context(request)})

    # --------------------------------------------------------------------------------------------------- fiche titre et détail
    @app.get("/resultats/titre/{symbol}")
    def title_page(request: Request, symbol: str):
        return templates.TemplateResponse(request, "earnings_title.html", {"symbol": _check_symbol(symbol), **i18n_context(request)})

    @app.get("/fragments/earn-title")
    def frag_title(request: Request, symbol: str):
        _check_symbol(symbol)
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            sheet = service.title_sheet(conn, symbol, cfg)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_earn_title.html", {"sheet": sheet, "cfg": cfg, **i18n_context(request)})

    @app.get("/resultats/evenement")
    def event_page(request: Request, symbol: str, day: str):
        if not _DATE.match(day):
            raise HTTPException(status_code=400, detail="date invalide")
        return templates.TemplateResponse(request, "earnings_event.html", {"symbol": _check_symbol(symbol), "day": day, **i18n_context(request)})

    @app.get("/fragments/earn-event")
    def frag_event(request: Request, symbol: str, day: str):
        _check_symbol(symbol)
        if not _DATE.match(day):
            raise HTTPException(status_code=400, detail="date invalide")
        conn = conn_factory()
        try:
            cfg = load_cfg(conn)
            detail = service.event_detail(conn, symbol, day, cfg)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "_earn_event.html", {"d": detail, "symbol": symbol, "day": day, "cfg": cfg, **i18n_context(request)})


def _summarize(outcome: dict) -> dict:
    reports = outcome.get("reports", [])
    return {"symbols": len(reports), "events": sum(r.n_events for r in reports), "upcoming": sum(r.n_upcoming for r in reports),
            "failed": [{"symbol": r.symbol, "errors": r.errors} for r in reports if r.errors], "snapshots": outcome.get("snapshots", {})}
