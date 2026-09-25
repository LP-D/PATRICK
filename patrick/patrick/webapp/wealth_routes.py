"""Roadmap bloc 4 -- PATRIMOINE pages and JSON API.

Pages (nav_registry, category `patrimoine`):
- `/patrimoine`: accounts (real and fictive), consolidated real holdings,
  ex-ante risk; child route `/patrimoine/comptes/{account_id}`;
- `/mouvements`: every movement, drag-and-drop between accounts, CSV drop
  zone. (Flat URL on purpose: `/patrimoine/mouvements` would also light the
  `/patrimoine` entry, whose active state is prefix-based.)

API (`/api/wealth/*`): create/update/delete accounts, clone as fictive,
add/delete/transfer movements, CSV import with a mandatory preview step
(`commit=false` returns the parsed rows and per-line errors, `commit=true`
writes only the valid rows). Every write goes through `wealth.ledger`,
whose validation errors become 400s.

Prices: `price_provider()` (local data lake, then yfinance with a 7-day
cache) -- module-level so tests can replace it.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from patrick.numeric import is_nan
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb
from patrick.wealth import importer, ledger, service, signal_replay
from patrick.wealth import prices as wealth_prices


def price_provider():
    return wealth_prices.make_provider()


def _json_body(raw: bytes) -> dict:
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="corps JSON invalide") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="objet JSON attendu")
    return body


def _ledger_call(fn, *args, **kwargs):
    conn = trackdb.connect()
    try:
        return fn(conn, *args, **kwargs)
    except ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"contrainte violée : {exc}") from exc
    finally:
        conn.close()


def _fmt_number(value, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", "\u202f").replace(".", ",")


def fmt_eur(value, digits: int = 2) -> str:
    """French money format (narrow no-break space thousands, decimal comma)."""
    if value is None or is_nan(value):
        return "—"
    return _fmt_number(float(value), digits) + "\u00a0€"


def fmt_pct(value, digits: int = 1, signed: bool = False) -> str:
    if value is None or is_nan(value):
        return "—"
    v = float(value) * 100
    sign = "+" if signed and v > 0 else ""
    return sign + _fmt_number(v, digits) + "\u00a0%"


def fmt_qty(value) -> str:
    if value is None or is_nan(value):
        return "—"
    v = float(value)
    return _fmt_number(v, 0 if abs(v - round(v)) < 1e-9 else 4)


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = the app's i18n/glossary context builder."""
    templates.env.filters["eur"] = fmt_eur
    templates.env.filters["pct"] = fmt_pct
    templates.env.filters["qty"] = fmt_qty
    templates.env.filters["mvkind"] = lambda kind: ledger.MOVEMENT_LABELS_FR.get(kind, kind)

    @app.get("/patrimoine")
    def patrimoine_page(request: Request):
        conn = trackdb.connect()
        try:
            data = service.overview(conn, price_provider())
        finally:
            conn.close()
        return templates.TemplateResponse(request, "patrimoine.html",
                                          {"data": data, "kinds": ledger.ACCOUNT_KINDS, **context(request)})

    @app.get("/patrimoine/comptes/{account_id}")
    def patrimoine_account_page(request: Request, account_id: str):
        conn = trackdb.connect()
        try:
            detail = service.account_detail(conn, account_id, price_provider())
            accounts = ledger.list_accounts(conn)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        return templates.TemplateResponse(request, "patrimoine_account.html", {
            "detail": detail, "accounts": accounts, "chart": service.chart_payload(detail),
            "movement_kinds": ledger.MOVEMENT_KINDS, **context(request)})

    @app.get("/mouvements")
    def movements_page(request: Request):
        conn = trackdb.connect()
        try:
            accounts = ledger.list_accounts(conn)
            by_id = {a["account_id"]: a for a in accounts}
            movements = [m for m in ledger.list_movements(conn) if m["account_id"] in by_id]
        finally:
            conn.close()
        movements.sort(key=lambda m: (m["ts"], m["movement_id"]), reverse=True)
        return templates.TemplateResponse(request, "mouvements.html", {
            "accounts": accounts, "by_id": by_id, "movements": movements,
            "movement_kinds": ledger.MOVEMENT_KINDS, **context(request)})

    @app.get("/patrimoine-simulation")
    def patrimoine_simulation_page(request: Request):
        conn = trackdb.connect()
        try:
            accounts = ledger.list_accounts(conn)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "patrimoine_simulation.html",
                                          {"accounts": accounts, **context(request)})

    # ---------------------------------------------------------------- API

    @app.post("/api/wealth/accounts/{account_id}/replay")
    async def api_replay(request: Request, account_id: str):
        """Replays each modeled position's signals (one segment, holdout by
        default) and aggregates them at today's weights. Every per-asset
        simulation is logged (it counts in later deflated Sharpes)."""
        b = _json_body(await request.body())
        fields = set(sim_engine.SimParams.__dataclass_fields__)
        raw = {k: v for k, v in (b.get("params") or {}).items() if k in fields}
        try:
            params = sim_engine.SimParams(**raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if params.position_mode not in ("threshold", "proportional", "heuristic_leverage"):
            raise HTTPException(status_code=400, detail=f"position_mode inconnu : {params.position_mode}")
        segment = b.get("segment") or "holdout"
        if segment not in sim_engine.SEGMENTS:
            raise HTTPException(status_code=400, detail=f"segment inconnu : {segment}")
        conn = trackdb.connect()
        try:
            detail = service.account_detail(conn, account_id, price_provider())
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="Compte introuvable")
        return signal_replay.replay_account(detail["holdings"], params, segment=segment)

    @app.post("/api/wealth/accounts")
    async def api_create_account(request: Request):
        b = _json_body(await request.body())
        # Absent -> the wrapper's default benchmark; "" -> explicitly none.
        benchmark = (b.get("benchmark") or None) if "benchmark" in b else "__default__"
        account_id = _ledger_call(ledger.create_account, b.get("name"), b.get("kind"), b.get("mode", "real"),
                                  b.get("currency") or "EUR", benchmark, b.get("opened_on") or None)
        return {"account_id": account_id}

    @app.patch("/api/wealth/accounts/{account_id}")
    async def api_update_account(request: Request, account_id: str):
        b = _json_body(await request.body())
        _ledger_call(ledger.update_account, account_id, **b)
        return {"ok": True}

    @app.delete("/api/wealth/accounts/{account_id}")
    def api_delete_account(account_id: str):
        _ledger_call(ledger.delete_account, account_id)
        return {"ok": True}

    @app.post("/api/wealth/accounts/{account_id}/clone")
    async def api_clone_account(request: Request, account_id: str):
        b = _json_body(await request.body())
        return {"account_id": _ledger_call(ledger.clone_as_fictive, account_id, b.get("name") or None)}

    @app.post("/api/wealth/accounts/{account_id}/movements")
    async def api_add_movement(request: Request, account_id: str):
        b = _json_body(await request.body())
        return {"movement_id": _ledger_call(ledger.add_movement, account_id, b)}

    @app.delete("/api/wealth/movements/{movement_id}")
    def api_delete_movement(movement_id: int):
        _ledger_call(ledger.delete_movement, movement_id)
        return {"ok": True}

    @app.post("/api/wealth/movements/{movement_id}/transfer")
    async def api_transfer_movement(request: Request, movement_id: int):
        b = _json_body(await request.body())
        return _ledger_call(ledger.transfer_movement, movement_id, str(b.get("account_id") or ""))

    @app.post("/api/wealth/accounts/{account_id}/import")
    async def api_import(request: Request, account_id: str):
        """`{"csv": "<text>", "commit": false}` -> preview; `commit: true`
        writes the valid rows (the errors are returned again, never
        silently dropped)."""
        b = _json_body(await request.body())
        text = b.get("csv")
        if not isinstance(text, str):
            raise HTTPException(status_code=400, detail="champ csv (texte) manquant")
        try:
            parsed = importer.parse_csv(text.encode("utf-8"))
        except ledger.LedgerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        written: list[int] = []
        if b.get("commit"):
            conn = trackdb.connect()
            try:
                if ledger.get_account(conn, account_id) is None:
                    raise HTTPException(status_code=404, detail="Compte introuvable")
                written = [ledger.add_movement(conn, account_id, row) for row in parsed["rows"]]
            finally:
                conn.close()
        return JSONResponse({"rows": parsed["rows"], "errors": parsed["errors"], "columns": parsed["columns"],
                             "written": len(written)})
