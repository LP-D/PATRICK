"""Liste d'alertes (plus fortes variations récentes) sur l'univers de tickers —
calculée en arrière-plan toutes les 30 minutes et mise en cache : la télécharger
à chaque chargement de la page serait trop lent sur ~300 tickers (cf. décision
utilisateur). Indépendant de `patrick.data.ingest` (qui, lui, cache un run
complet) : ici on veut juste un instantané rapide, régulièrement rafraîchi.
"""
from __future__ import annotations

import datetime as dt
import threading
import time

from patrick.config import defaults as D
from patrick.data.sources.yfinance_source import clean_symbol, download_batch

REFRESH_SECONDS = 30 * 60
LOOKBACK_DAYS = 5
TOP_N = 8

_lock = threading.Lock()
_cache: dict = {"gainers": [], "losers": [], "updated_at": None, "error": None}
_started = False


def get_cached() -> dict:
    with _lock:
        return dict(_cache)


def _label_for(symbol: str) -> str:
    for sym, label, src in D.DEFAULT_TARGET_CHOICES:
        if sym == symbol and src == "yfinance":
            return label
    return symbol


def _compute_once() -> None:
    tickers = list(D.DEFAULT_UNIVERSE_YF_TICKERS)
    reverse = {clean_symbol(t): t for t in tickers}
    start = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS * 3 + 5)).isoformat()

    try:
        df = download_batch(tickers, start)
    except Exception as e:
        with _lock:
            _cache["error"] = str(e)[:200]
        return

    if df is None or df.empty or len(df) < 2:
        with _lock:
            _cache["error"] = "Pas assez de données téléchargées."
        return

    # yfinance peut renvoyer une dernière ligne entièrement vide (jour en cours,
    # pas encore clôturé) — on la retire après avoir comblé les trous ponctuels
    # (jours fériés locaux différents selon la place) par un forward-fill.
    df = df.ffill().dropna(axis=0, how="all").dropna(axis=1, how="all")
    if len(df) < 2:
        with _lock:
            _cache["error"] = "Pas assez de données téléchargées."
        return
    last = df.iloc[-1]
    prior_idx = max(0, len(df) - 1 - LOOKBACK_DAYS)
    prior = df.iloc[prior_idx]
    pct = ((last - prior) / prior.replace(0, float("nan")) * 100).dropna()
    pct = pct[(pct != float("inf")) & (pct != float("-inf"))]
    ranked = pct.sort_values(ascending=False)

    def _rows(series) -> list[dict]:
        out = []
        for clean, val in series.items():
            sym = reverse.get(clean, clean)
            out.append({"symbol": sym, "label": _label_for(sym), "pct": round(float(val), 2)})
        return out

    with _lock:
        _cache["gainers"] = _rows(ranked.head(TOP_N))
        _cache["losers"] = _rows(ranked.tail(TOP_N)[::-1])
        _cache["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        _cache["error"] = None


def _loop() -> None:
    while True:
        _compute_once()
        time.sleep(REFRESH_SECONDS)


def start_background_refresh() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
