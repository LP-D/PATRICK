"""Background refresh of the HMM market state (`tracking/market_state.py`) for
the synthesis page -- same pattern as `alerts.py`: one fit per market (a few
seconds on 25 years of data) is too slow for a page load, so it runs in a
daemon thread started with the app and the page reads the cache through
`/api/market-state`.
Status strings stay in French, like the rest of the interface.
"""
from __future__ import annotations

import threading
import time

from patrick.clock import local_now
from patrick.data.sources.yfinance_source import download_one
from patrick.tracking import market_state

REFRESH_SECONDS = 6 * 60 * 60
HISTORY_START = "2000-01-01"

_lock = threading.Lock()
_state: dict = {"rows": [], "updated_at": None, "error": None, "computing": False}
_started = False
_cache = market_state.MarketStateCache()


def get_cached() -> dict:
    with _lock:
        return dict(_state)


def _load(symbol: str):
    return download_one(symbol, HISTORY_START)


def compute_once() -> None:
    with _lock:
        _state["computing"] = True
    try:
        rows = _cache.overview(_load)
    except Exception as exc:  # noqa: BLE001 -- background thread boundary
        with _lock:
            _state.update(error=f"Calcul impossible : {str(exc)[:200]}", computing=False)
        return
    with _lock:
        _state.update(rows=rows, updated_at=local_now().strftime("%Y-%m-%d %H:%M"), error=None, computing=False)


def _loop() -> None:
    while True:
        compute_once()
        time.sleep(REFRESH_SECONDS)


def start_background_refresh() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True).start()
