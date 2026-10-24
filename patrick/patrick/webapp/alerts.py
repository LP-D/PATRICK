"""Bandeau des plus fortes variations : classement des variations sur 5 jours des symboles yfinance du PÉRIMÈTRE DU BANDEAU
(`_mover_pool`) parmi les cibles sélectionnables au lancement -- actions individuelles, devises, futures, VIX et grands indices
mondiaux. Calculé en arrière-plan toutes les 30 minutes et mis en cache : le télécharger à chaque chargement de page serait trop lent
sur autant de tickers (décision de l'utilisateur). Indépendant de `patrick.data.ingest` (qui met en cache un run complet) : on veut
seulement un instantané rapide et régulièrement rafraîchi. Les chaînes d'erreur/état de `_cache` sont affichées telles quelles et restent
en français, comme le reste de l'interface web.

Le périmètre est volontairement étroit (décision du 2026-10-24) : sans lui, le classement se remplissait d'indices de volatilité
(VIX3M, VVIX, MOVE...), d'ETF sectoriels très spécialisés, d'ETF de pays ou d'obligations, qui ne sont pas ce que l'on veut lire dans un
bandeau. Chaque symbole du bandeau reste cliquable comme cible : `n_ranked`/`n_requested` du cache exposent la couverture réelle, pour
qu'un trou du fournisseur reste visible dans l'interface.
"""
from __future__ import annotations

import datetime as dt
import threading
import time

from patrick.clock import local_now, utc_today
from patrick.config import defaults as D
from patrick.data.sources.yfinance_source import clean_symbol, download_batch
from patrick.tracking import db as trackdb
from patrick.webapp import forms

REFRESH_SECONDS = 30 * 60
LOOKBACK_DAYS = 5
TOP_N = 8

_lock = threading.Lock()
_cache: dict = {"gainers": [], "losers": [], "updated_at": None, "error": None,
                "n_ranked": 0, "n_requested": 0}
_started = False


def get_cached() -> dict:
    with _lock:
        return dict(_cache)


# Périmètre du bandeau. Actions et devises : par groupe du formulaire de lancement ; futures : symbole en « =F » ; volatilité : le VIX
# seul ; indices : une liste fermée des plus connus (pas les indices de niche : semi-conducteurs, transports, petits marchés).
MOVER_EQUITY_GROUP_PREFIX = "Actions"
MOVER_FX_GROUPS = frozenset({"Devises", "Devises (majeures)"})
MOVER_VOLATILITY_SYMBOLS = frozenset({"^VIX"})
MOVER_INDEX_SYMBOLS = frozenset({
    "^GSPC", "^DJI", "^IXIC", "^NDX", "^RUT",                    # États-Unis : S&P 500, Dow Jones, Nasdaq Composite et 100, Russell 2000
    "^FCHI", "^GDAXI", "^FTSE", "^STOXX50E",                     # Europe : CAC 40, DAX, FTSE 100, Euro Stoxx 50
    "^N225", "^HSI", "000001.SS",                                # Asie : Nikkei 225, Hang Seng, Shanghai Composite
})


def is_mover_symbol(symbol: str, group: str | None = None) -> bool:
    """Le symbole figure-t-il dans le périmètre du bandeau ? `group` : son groupe du formulaire de lancement, s'il en a un."""
    if symbol in MOVER_INDEX_SYMBOLS or symbol in MOVER_VOLATILITY_SYMBOLS:
        return True
    if symbol.endswith(("=F", "=X")):                           # futures ; paires de devises
        return True
    return group is not None and (group.startswith(MOVER_EQUITY_GROUP_PREFIX) or group in MOVER_FX_GROUPS)


def _mover_pool() -> list[str]:
    """Symboles yfinance du périmètre du bandeau, dans l'ordre d'affichage du formulaire, sans doublon, hors liste noire connue."""
    group_of: dict[str, str] = {}
    for group, items in forms.TARGET_GROUPS.items():
        for sym, _label in items:
            group_of.setdefault(sym, group)
    seen: dict[str, None] = {}
    for sym, _label, src in forms.TARGET_CHOICES:
        if src == "yfinance" and sym not in D.BAD_TICKERS and is_mover_symbol(sym, group_of.get(sym)):
            seen.setdefault(sym)
    return list(seen)


def _label_for(symbol: str) -> str:
    for sym, label, src in forms.TARGET_CHOICES:
        if sym == symbol and src == "yfinance":
            return label
    return symbol


def _active_tickers() -> list[str]:
    """Le périmètre du bandeau (`_mover_pool`) moins les symboles persistés comme confirmés indisponibles (M1, migration 0013) : un
    symbole qui échoue de la même façon à chaque démarrage (retiré de la cote, invalide) doit être exclu une fois, pas retenté
    indéfiniment à chaque rafraîchissement."""
    conn = trackdb.connect()
    try:
        excluded = {row["symbol"] for row in trackdb.list_excluded_symbols(conn)}
    finally:
        conn.close()
    return [t for t in _mover_pool() if t not in excluded]


def _compute_once() -> None:
    tickers = _active_tickers()
    reverse = {clean_symbol(t): t for t in tickers}
    start = (utc_today() - dt.timedelta(days=LOOKBACK_DAYS * 3 + 5)).isoformat()

    try:
        df = download_batch(tickers, start)
    except Exception as e:  # noqa: BLE001 -- background thread boundary: a provider failure must not kill the alerts loop
        with _lock:
            _cache["error"] = str(e)[:200]
        return

    if df is None or df.empty or len(df) < 2:
        with _lock:
            _cache["error"] = "Pas assez de données téléchargées."
        return

    # yfinance can return a fully empty last row (day still in progress, not
    # yet closed): it is dropped BEFORE the forward-fill (which would
    # otherwise copy the previous row into it and shorten the lookback), then
    # one-off gaps (local holidays differing by exchange) are filled.
    df = df.dropna(axis=0, how="all").ffill().dropna(axis=1, how="all")
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
        _cache["updated_at"] = local_now().strftime("%Y-%m-%d %H:%M")
        _cache["error"] = None
        _cache["n_ranked"] = len(ranked)
        _cache["n_requested"] = len(tickers)


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
