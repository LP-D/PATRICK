"""Ingestion : pour chaque titre confirmé, calendrier d'annonces + fiche + prix -> mesures par événement, persistées une fois.

`ingest_symbol` fait tout ce qui touche le réseau (via le fournisseur injecté) pour UN titre, puis écrit dans `earn_calendar`,
`earn_instrument` et `earn_result`. Le calcul est idempotent : relancer recalcule les mesures du hash de configuration courant.
Une défaillance sur un titre est rapportée dans son `IngestReport` et n'arrête jamais les autres.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from patrick.earnings import engine, exchanges, schedule, store
from patrick.earnings.config import EarningsConfig

log = logging.getLogger(__name__)
INFO_MAX_AGE_DAYS = 30
CALENDAR_MAX_AGE_HOURS = 20
MIN_PRICE_ROWS = 300
MIN_PEERS = 3


@dataclass
class IngestReport:
    symbol: str
    n_calendar: int = 0
    n_events: int = 0
    n_upcoming: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    benchmark: str = ""
    model_used: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.n_events > 0


class SharedData:
    """Séries communes à plusieurs titres d'un même passage (indices, ETF sectoriels, facteurs) : chargées une fois."""

    def __init__(self, provider, cfg: EarningsConfig):
        self.provider, self.cfg = provider, cfg
        self._frames: dict[str, pd.DataFrame | None] = {}
        self.calendars: dict[str, pd.DataFrame] = {}      # préchargés en parallèle par `ingest_many`
        self.infos: dict[str, dict] = {}

    def frame(self, symbol: str) -> pd.DataFrame | None:
        if symbol not in self._frames:
            df = self.provider.ohlcv(symbol, self.cfg.start)
            self._frames[symbol] = df if df is not None and len(df) >= 30 else None
        return self._frames[symbol]

    def benchmark(self, symbol: str, index: pd.DatetimeIndex | None = None) -> tuple[str, pd.DataFrame | None]:
        """Indice local d'abord, replis ensuite. Avec `index` (séances du titre) : le premier candidat qui couvre au moins 70 % de l'historique,
        sinon celui qui en couvre le plus. Un indice national qui n'existe que depuis 2016 ne doit pas servir pour des annonces de 2010."""
        best: tuple[float, str, pd.DataFrame | None] = (-1.0, "", None)
        for cand in exchanges.benchmark_candidates(symbol):
            df = self.frame(cand)
            if df is None or len(df) < MIN_PRICE_ROWS:
                continue
            cover = 1.0 if index is None or not len(index) else float((pd.DatetimeIndex(index) >= df.index[0]).mean())
            if cover >= 0.7:
                return cand, df
            if cover > best[0]:
                best = (cover, cand, df)
        return best[1], best[2]


def sector_series(shared: SharedData, conn, symbol: str, info: dict) -> pd.Series | None:
    """Niveau d'un indice sectoriel : ETF SPDR pour une valeur américaine, sinon panier équipondéré des autres titres de même
    secteur et même région déjà connus de PATRICK (au moins `MIN_PEERS`)."""
    sector = info.get("sector")
    if not sector:
        return None
    if exchanges.is_us(symbol) and sector in exchanges.SECTOR_ETF_US:
        df = shared.frame(exchanges.SECTOR_ETF_US[sector])
        if df is not None:
            return df["Close"]
    region = exchanges.venue_for(symbol).region
    peers = [s for s, ins in store.all_instruments(conn).items()
             if s != symbol and ins.get("sector") == sector and exchanges.venue_for(s).region == region]
    rets = []
    for peer in peers[:25]:
        df = shared.frame(peer)
        if df is not None and len(df) >= MIN_PRICE_ROWS:
            rets.append(df["Close"].pct_change())
    if len(rets) < MIN_PEERS:
        return None
    basket = pd.concat(rets, axis=1).mean(axis=1, skipna=True).fillna(0.0)
    return (1 + basket).cumprod()


def _drop_stale_guesses(calendar: list[dict]) -> list[dict]:
    """Une date issue de la newsletter n'est qu'une supposition : dès que le calendrier Yahoo ou une saisie manuelle donne une annonce
    à moins de 7 jours, la supposition est ignorée (sinon une mauvaise date deviendrait un « événement » passé)."""
    solid = [pd.Timestamp(c["ann_date"]) for c in calendar if c["source"] != "newsletter"]
    return [c for c in calendar if c["source"] != "newsletter" or not any(abs((pd.Timestamp(c["ann_date"]) - d).days) <= 7 for d in solid)]


def ingest_symbol(conn, provider, symbol: str, cfg: EarningsConfig, shared: SharedData | None = None,
                  refresh_calendar: bool = True) -> IngestReport:
    cfg.validate()
    rep = IngestReport(symbol)
    shared = shared or SharedData(provider, cfg)
    stale = (store.calendar_fetched_at(conn, symbol) is None)
    if refresh_calendar or stale:
        raw = shared.calendars.pop(symbol, None)
        if raw is None:
            raw = provider.calendar(symbol)
        rep.n_calendar = store.upsert_calendar(conn, schedule.calendar_rows(symbol, raw)) if len(raw) else 0
    info = store.get_instrument(conn, symbol, INFO_MAX_AGE_DAYS)
    if info is None:
        info = shared.infos.pop(symbol, None) or provider.info(symbol)
        if info:
            store.put_instrument(conn, symbol, info)
    info = info or {}
    px = provider.ohlcv(symbol, cfg.start)
    if px is None or len(px) < MIN_PRICE_ROWS:
        rep.errors.append("pas assez de cours (" + str(0 if px is None else len(px)) + " séances)")
        return rep
    bench_symbol, bench = shared.benchmark(symbol, px.index)
    rep.benchmark = bench_symbol
    sector_close = sector_series(shared, conn, symbol, info) if cfg.model == "sector" else None
    factors = None
    if cfg.model == "factor":
        region = exchanges.venue_for(symbol).region
        factors = provider.factors(region) if region in ("US", "EU", "JP") else None
    sp = engine.SymbolPrices(px, bench["Close"] if bench is not None else None, bench["Open"] if bench is not None else None,
                             sector_close, factors)
    calendar = _drop_stale_guesses(store.calendar_for(conn, symbol))
    react_days = {}
    for row in calendar:
        d0 = exchanges.day_zero(row["ann_date"], row["timing"], sp.idx)
        react_days[row["ann_date"]] = d0
    h = cfg.measure_hash()
    store.delete_results(conn, symbol, h)
    seen_days: set[pd.Timestamp] = set()
    for row in calendar:
        d0 = react_days[row["ann_date"]]
        if d0 is None:
            rep.n_upcoming += 1
            continue
        if d0 in seen_days:
            rep.skipped.append((row["ann_date"], "même jour de réaction qu'une autre annonce"))
            continue
        seen_days.add(d0)
        others = [d for k, d in react_days.items() if k != row["ann_date"] and d is not None]
        payload, why = engine.compute_event(
            sp, symbol=symbol, ann_date=row["ann_date"], timing=row["timing"], uncertain=bool(row["uncertain"]), cfg=cfg,
            other_days=others, timing_source=row["timing_source"],
            eps={k: row.get(k) for k in ("eps_estimate", "eps_actual", "surprise_pct")})
        if payload is None:
            rep.skipped.append((row["ann_date"], why))
            continue
        store.put_result(conn, symbol, row["ann_date"], h, payload)
        rep.n_events += 1
        rep.model_used[payload["model_used"]] = rep.model_used.get(payload["model_used"], 0) + 1
    return rep


def ingest_many(conn_factory, provider, symbols: list[str], cfg: EarningsConfig, progress=None, workers: int = 4,
                refresh_calendar: bool = True) -> list[IngestReport]:
    """Plusieurs titres. Le réseau est parallélisé (préchargement des prix) ; l'écriture en base reste dans le fil appelant."""
    shared = SharedData(provider, cfg)
    unique = list(dict.fromkeys(symbols))
    conn = conn_factory()
    fresh_info = {s for s in unique if store.get_instrument(conn, s, INFO_MAX_AGE_DAYS) is not None}

    def warm(sym):
        try:
            provider.ohlcv(sym, cfg.start)
            if refresh_calendar:
                shared.calendars[sym] = provider.calendar(sym)
            if sym not in fresh_info:
                shared.infos[sym] = provider.info(sym)
        except Exception as exc:  # noqa: BLE001 -- préchargement opportuniste : l'erreur réelle sera rapportée par ingest_symbol
            log.debug("préchargement de %s en échec : %s", sym, exc)

    reports = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(warm, unique))
        for i, sym in enumerate(unique):
            t0 = time.time()
            try:
                reports.append(ingest_symbol(conn, provider, sym, cfg, shared, refresh_calendar))
            except Exception as exc:  # noqa: BLE001 -- un titre en échec ne doit pas arrêter les autres
                rep = IngestReport(sym)
                rep.errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                reports.append(rep)
            if progress:
                progress(i + 1, len(unique), sym, time.time() - t0)
    finally:
        conn.close()
    return reports


def stale_symbols(conn, symbols: list[str], cfg: EarningsConfig) -> list[str]:
    """Titres sans mesures pour la configuration courante (à ingérer)."""
    have = {r["symbol"] for r in store.load_results(conn, cfg.measure_hash(), symbols)}
    return [s for s in symbols if s not in have]


def nan_safe(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else x
