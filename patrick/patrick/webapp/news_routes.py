"""Page /news et ses fragments : flux de nouvelles point-in-time, sentiment par actif, ton des banques centrales, étude d'événement.

Règle « la page s'ouvre tout de suite » : /news n'envoie que son cadre (chiffres de tête = comptages SQL) ; les tableaux arrivent
par `/fragments/news-*` ; l'étude d'événement ne se calcule qu'au clic. La collecte (réseau) tourne dans un fil d'arrière-plan,
une seule à la fois ; `refresh_runner` et `price_loader` sont des fonctions de module pour que les tests les remplacent sans réseau.
Les prix de l'étude viennent du data lake local en LECTURE SEULE : l'étude ne télécharge ni n'écrit rien dans le cache."""
from __future__ import annotations

import re
import threading

import pandas as pd
from fastapi import FastAPI, HTTPException, Request

from patrick.text import aggregate, service
from patrick.tracking import db as trackdb

WINDOWS = (1, 7, 30)
DEFAULT_WINDOW = 7
FEED_LIMIT = 60
MIN_EVENTS = 10
WARN_EVENTS = 30
BENCHMARK = "^GSPC"
_SYMBOL = re.compile(r"^[A-Za-z0-9.^=\-_]{1,20}$")

_lock = threading.Lock()
_state: dict = {"running": False, "error": None, "result": None}


def refresh_runner() -> dict:
    """Collecte réelle : flux RSS/Atom par défaut (+ ceux des réglages) sur la base de suivi courante."""
    conn = trackdb.connect()
    try:
        return service.refresh(conn)
    finally:
        conn.close()


def price_loader(symbol: str) -> pd.Series | None:
    """Prix de clôture déjà présents dans le data lake local (`raw_<symbole>`), sans aucun téléchargement."""
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore

    store = DataStore()
    if not store.exists(f"raw_{symbol}"):
        return None
    df = store.load(f"raw_{symbol}")
    col = clean_symbol(symbol)
    if col not in df.columns:
        col = "Close" if "Close" in df.columns else df.columns[0]
    return df[col].dropna()


def _run_refresh() -> None:
    try:
        result = refresh_runner()
        outcome = {"result": result, "error": None}
    except Exception as exc:  # noqa: BLE001 -- fil d'arrière-plan : toute erreur est rapportée à la page, jamais perdue
        outcome = {"result": None, "error": str(exc) or type(exc).__name__}
    with _lock:
        _state.update(running=False, **outcome)


def _check_symbol(symbol: str | None) -> str | None:
    if symbol in (None, ""):
        return None
    if not _SYMBOL.match(symbol):
        raise HTTPException(status_code=400, detail="symbole invalide")
    return symbol


def _fmt_ts(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M") if value else ""


def register(app: FastAPI, templates, i18n_context) -> None:
    @app.get("/news")
    def news_page(request: Request, window: int = DEFAULT_WINDOW, symbol: str | None = None):
        if window not in WINDOWS:
            window = DEFAULT_WINDOW
        symbol = _check_symbol(symbol)
        conn = trackdb.connect()
        try:
            summary = service.summary(conn)
        finally:
            conn.close()
        summary["last_known_at"] = _fmt_ts(summary["last_known_at"])
        return templates.TemplateResponse(
            request, "news.html",
            {"summary": summary, "window": window, "windows": WINDOWS, "symbol": symbol, **i18n_context(request)})

    @app.get("/fragments/news-assets")
    def news_assets_fragment(request: Request, window: int = DEFAULT_WINDOW):
        if window not in WINDOWS:
            raise HTTPException(status_code=400, detail="fenêtre inconnue")
        conn = trackdb.connect()
        try:
            table = service.asset_overview(conn, since=pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=window))
        finally:
            conn.close()
        rows = table.astype(object).where(table.notna(), None).to_dict("records")
        for r in rows:
            r["last_known_at"] = _fmt_ts(r["last_known_at"])
        return templates.TemplateResponse(request, "_news_assets.html", {"rows": rows, "window": window, **i18n_context(request)})

    @app.get("/fragments/news-feed")
    def news_feed_fragment(request: Request, symbol: str | None = None):
        symbol = _check_symbol(symbol)
        conn = trackdb.connect()
        try:
            items = service.item_feed(conn, symbol=symbol, limit=FEED_LIMIT)
        finally:
            conn.close()
        for it in items:
            it["known_at_label"] = _fmt_ts(it["known_at"])
        return templates.TemplateResponse(request, "_news_feed.html", {"items": items, "symbol": symbol, **i18n_context(request)})

    @app.get("/fragments/news-central")
    def news_central_fragment(request: Request):
        conn = trackdb.connect()
        try:
            items = service.item_feed(conn, limit=FEED_LIMIT, kinds=["central_bank"])
        finally:
            conn.close()
        for it in items:
            it["known_at_label"] = _fmt_ts(it["known_at"])
        return templates.TemplateResponse(request, "_news_central.html", {"items": items, **i18n_context(request)})

    @app.get("/fragments/news-event-study")
    def news_event_study_fragment(request: Request, symbol: str | None = None):
        symbol = _check_symbol(symbol)
        ctx = {"symbol": symbol, "state": "need_symbol", "min_events": MIN_EVENTS, "warn_events": WARN_EVENTS,
               **i18n_context(request)}
        if symbol is None:
            return templates.TemplateResponse(request, "_news_event_study.html", ctx)
        prices = price_loader(symbol)
        if prices is None or prices.empty:
            return templates.TemplateResponse(request, "_news_event_study.html", {**ctx, "state": "no_prices"})
        conn = trackdb.connect()
        try:
            items = service.scored_items_for_symbol(conn, symbol)
        finally:
            conn.close()
        strong = aggregate.strong_events(items)
        if len(strong) < MIN_EVENTS:
            return templates.TemplateResponse(request, "_news_event_study.html", {**ctx, "state": "too_few", "n": len(strong)})
        try:
            benchmark = price_loader(BENCHMARK)
            studies = aggregate.textual_event_study(prices, items, benchmark=benchmark,
                                                    model="market" if benchmark is not None else "constant_mean",
                                                    event_window=(-5, 10))
        except ValueError:
            return templates.TemplateResponse(request, "_news_event_study.html", {**ctx, "state": "too_few", "n": len(strong)})
        groups = []
        for label, study in studies.items():
            tests = study.tests((0, 1))
            groups.append({"label": label, "n": study.n_events, "caar": tests.get("caar"), "p_bmp": tests.get("p_bmp"),
                           "overlaps": len(study.overlapping_events), "few": study.n_events < WARN_EVENTS})
        return templates.TemplateResponse(request, "_news_event_study.html",
                                          {**ctx, "state": "result" if groups else "too_few", "groups": groups,
                                           "n": len(strong)})

    @app.post("/api/newsflow/refresh")
    def news_refresh():
        with _lock:
            if _state["running"]:
                return {"started": False, **_state}
            _state.update(running=True, error=None, result=None)
        threading.Thread(target=_run_refresh, name="news-refresh", daemon=True).start()
        return {"started": True, "running": True}

    @app.get("/api/newsflow/status")
    def news_status():
        with _lock:
            return dict(_state)

