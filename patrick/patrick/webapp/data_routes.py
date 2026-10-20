"""Page `/donnees` (explorateur de données) et API `/api/donnees/*`. Lecture seule sur le data lake, sauf l'import d'une série personnelle
(clé `user_<nom>`, jamais une clé du pipeline) et les listes de suivi (table `watchlist`). Calculs dans `patrick/analysis/data_explorer.py`."""
from __future__ import annotations

import json
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from patrick.analysis import data_explorer as dx
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.tracking import watchlists as wl

_NOT_FOUND = {"unknown_key", "unknown_snapshot", "unknown_column"}
_SYMBOL = re.compile(r"^[A-Za-z0-9^=.\-_]{1,24}$")


def _json_body(raw: bytes) -> dict:
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_json")
    return body


def _data_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except dx.DataError as exc:
        raise HTTPException(status_code=404 if str(exc) in _NOT_FOUND else 422, detail=str(exc)) from exc


def _watchlist_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except wl.WatchlistError as exc:
        raise HTTPException(status_code=404 if str(exc) == "not_found" else 422, detail=str(exc)) from exc


def _with_conn(fn):
    conn = trackdb.connect()
    try:
        return fn(conn)
    finally:
        conn.close()


def register(app: FastAPI, templates, context) -> None:
    @app.get("/donnees")
    def data_page(request: Request):
        return templates.TemplateResponse(request, "donnees.html", context(request))

    @app.get("/api/donnees/lake")
    async def data_lake():
        return JSONResponse(await run_in_threadpool(lambda: dx.lake_index(DataStore())))

    @app.get("/api/donnees/frame")
    async def data_frame(key: str, snapshot: str | None = None, as_of: str | None = None):
        return JSONResponse(await run_in_threadpool(lambda: _data_call(dx.frame_detail, DataStore(), key, snapshot, as_of)))

    @app.get("/api/donnees/series")
    async def data_series(key: str, column: str, snapshot: str | None = None, as_of: str | None = None, compare: str | None = None):
        return JSONResponse(await run_in_threadpool(lambda: _data_call(dx.column_series, DataStore(), key, column, snapshot, as_of, compare)))

    @app.get("/api/donnees/revisions")
    async def data_revisions(key: str, a: str, b: str):
        return JSONResponse(await run_in_threadpool(lambda: _data_call(dx.snapshot_revisions, DataStore(), key, a, b)))

    @app.get("/api/donnees/calendar")
    async def data_calendar():
        return JSONResponse(await run_in_threadpool(lambda: dx.release_calendar(DataStore())))

    @app.get("/api/donnees/symbols")
    async def data_symbols():
        return JSONResponse(await run_in_threadpool(lambda: dx.lake_symbols(DataStore())))

    # ------------------------------------------------------------------------------------------- listes de suivi
    @app.get("/api/donnees/watchlists")
    async def watchlists_list():
        return JSONResponse(await run_in_threadpool(lambda: _with_conn(wl.list_all)))

    @app.post("/api/donnees/watchlists")
    async def watchlists_create(request: Request):
        b = _json_body(await request.body())
        wid = await run_in_threadpool(lambda: _with_conn(lambda c: _watchlist_call(wl.create, c, str(b.get("name") or ""), b.get("symbols"), b.get("tags"), str(b.get("note") or ""))))
        return JSONResponse({"watchlist_id": wid}, status_code=201)

    @app.patch("/api/donnees/watchlists/{watchlist_id}")
    async def watchlists_update(request: Request, watchlist_id: int):
        b = _json_body(await request.body())
        await run_in_threadpool(lambda: _with_conn(lambda c: _watchlist_call(wl.update, c, watchlist_id, name=b.get("name"), symbols=b.get("symbols"), tags=b.get("tags"), note=b.get("note"))))
        return JSONResponse({"ok": True})

    @app.delete("/api/donnees/watchlists/{watchlist_id}")
    async def watchlists_delete(watchlist_id: int):
        await run_in_threadpool(lambda: _with_conn(lambda c: _watchlist_call(wl.delete, c, watchlist_id)))
        return JSONResponse({"ok": True})

    @app.get("/api/donnees/watchlists/{watchlist_id}/overview")
    async def watchlists_overview(watchlist_id: int):
        def work():
            item = _with_conn(lambda c: wl.get(c, watchlist_id))
            if item is None:
                raise HTTPException(status_code=404, detail="not_found")
            return {**item, **dx.watchlist_overview(DataStore(), item["symbols"])}
        return JSONResponse(await run_in_threadpool(work))

    # ------------------------------------------------------------------------------------------------ import
    @app.post("/api/donnees/import")
    async def data_import(request: Request):
        """`{filename, csv | b64, date_column?, dayfirst?, name?, commit?}` → aperçu ; `commit: true` enregistre sous `user_<name>`."""
        b = _json_body(await request.body())

        def work():
            filename, data = _data_call(dx.decode_payload, b)
            dayfirst = b.get("dayfirst") if isinstance(b.get("dayfirst"), bool) else None
            frame = _data_call(dx.parse_upload, filename, data, b.get("date_column") or None, dayfirst)
            preview = dx.preview_import(frame)
            if b.get("commit"):
                if not preview["ok"]:
                    raise HTTPException(status_code=422, detail="too_short")
                return {**preview, "saved": _data_call(dx.commit_import, DataStore(), str(b.get("name") or ""), frame, filename)}
            return preview
        return JSONResponse(await run_in_threadpool(work))

    @app.post("/api/donnees/ticker-check")
    async def data_ticker_check(request: Request):
        """Vérifie en direct qu'un symbole Yahoo est servi (cotation récente, historique suffisant). Seul appel réseau de la page."""
        b = _json_body(await request.body())
        symbol = str(b.get("symbol") or "").strip()
        if not _SYMBOL.match(symbol):
            raise HTTPException(status_code=422, detail="bad_symbol")
        from patrick.data import ticker_check
        return JSONResponse(await run_in_threadpool(ticker_check.check_ticker, symbol))
