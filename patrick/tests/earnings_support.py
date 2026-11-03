"""Données synthétiques et faux fournisseur pour les tests des événements de résultats (aucun réseau).

`make_world` fabrique un marché jouet : un indice, N titres avec bêta, une annonce tous les 63 jours, un choc de réaction
proportionnel à la surprise de BPA (ce qui donne un ERC > 0) et un volume qui monte le jour de l'annonce. Tout est tiré d'une graine."""
from __future__ import annotations

import numpy as np
import pandas as pd

START = "2019-01-02"


def make_series(seed: int, n: int = 1500, beta: float = 1.0, idio: float = 0.012, shocks: dict[int, float] | None = None,
                market: np.ndarray | None = None, volume_event_days: list[int] | None = None, gap_share: float = 0.6,
                base: float = 50.0, common: np.ndarray | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(START, periods=n)
    rm = market if market is not None else rng.normal(0.0003, 0.009, n)
    ri = beta * rm + rng.normal(0, idio, n)
    if common is not None:
        ri = ri + common                      # choc sectoriel partagé entre titres, absent de l'indice
    for pos, shock in (shocks or {}).items():
        ri[pos] += shock
    close = base * np.cumprod(1 + ri)
    prev = np.r_[base, close[:-1]]
    open_ = prev * (1 + gap_share * ri + rng.normal(0, 0.002, n))
    top = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    bottom = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = np.exp(rng.normal(13, 0.3, n))
    for pos in volume_event_days or []:
        volume[pos] *= 3.0
    return pd.DataFrame({"Open": open_, "High": top, "Low": bottom, "Close": close, "Volume": volume,
                         "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)


def market_returns(seed: int = 1, n: int = 1500) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0003, 0.009, n)


def bench_frame(rm: np.ndarray) -> pd.DataFrame:
    idx = pd.bdate_range(START, periods=len(rm))
    close = 100 * np.cumprod(1 + rm)
    prev = np.r_[100.0, close[:-1]]
    return pd.DataFrame({"Open": prev * (1 + 0.6 * rm), "High": close * 1.003, "Low": close * 0.997, "Close": close,
                         "Volume": 0.0, "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)


class FakeProvider:
    """Même interface que `YahooProvider`, alimenté par des dictionnaires."""

    def __init__(self):
        self.series: dict[str, pd.DataFrame] = {}
        self.calendars: dict[str, pd.DataFrame] = {}
        self.infos: dict[str, dict] = {}
        self.searches: dict[str, list[dict]] = {}
        self.consensus_data: dict[str, dict] = {}
        self.upgrade_frames: dict[str, pd.DataFrame] = {}
        self.straddles: dict[str, dict] = {}
        self.factor_frames: dict[str, pd.DataFrame] = {}
        self.errors: list[str] = []
        self.calls: list[tuple] = []

    def ohlcv(self, symbol, start="2005-01-01", max_age_days=1):
        self.calls.append(("ohlcv", symbol))
        return self.series.get(symbol)

    def calendar(self, symbol, limit=100):
        self.calls.append(("calendar", symbol))
        return self.calendars.get(symbol, pd.DataFrame(columns=["ts", "eps_estimate", "eps_actual", "surprise_pct"]))

    def info(self, symbol):
        return dict(self.infos.get(symbol, {}))

    def search(self, query, n=8):
        self.calls.append(("search", query))
        return list(self.searches.get(query, []))

    def consensus(self, symbol):
        return self.consensus_data.get(symbol, {})

    def upgrades(self, symbol):
        return self.upgrade_frames.get(symbol, pd.DataFrame())

    def straddle(self, symbol, on_or_after):
        return self.straddles.get(symbol)

    def factors(self, region, max_age_days=7):
        return self.factor_frames.get(region)


def make_world(n_symbols: int = 12, events_per_symbol: int = 14, seed: int = 7, n: int = 1500, shock_scale: float = 0.004,
               sectors: tuple[str, ...] = ("Technology", "Energy", "Healthcare")) -> tuple[FakeProvider, list[str]]:
    """Titres S00..S{n-1} cotés aux États-Unis, indice `^GSPC`. Événements espacés de 63 séances à partir de la séance 300."""
    rm = market_returns(seed + 100, n)
    prov = FakeProvider()
    prov.series["^GSPC"] = bench_frame(rm)
    idx = pd.bdate_range(START, periods=n)
    rng = np.random.default_rng(seed)
    symbols = []
    for s in range(n_symbols):
        sym = f"S{s:02d}"
        symbols.append(sym)
        timing = "AMC" if s % 2 == 0 else "BMO"
        positions = [300 + 63 * j + 3 * (s % 5) for j in range(events_per_symbol)]
        surprise = rng.normal(3.0, 8.0, len(positions))
        shocks, vol_days, rows = {}, [], []
        for pos, sp in zip(positions, surprise):
            react = pos + (1 if timing == "AMC" else 0)
            shocks[react] = shock_scale * sp + rng.normal(0, 0.012)
            vol_days.append(react)
            ts = pd.Timestamp(f"{idx[pos].date()} {'16:00' if timing == 'AMC' else '07:00'}", tz="America/New_York")
            est = 1.0 + 0.1 * s
            rows.append({"ts": ts, "eps_estimate": est, "eps_actual": est * (1 + sp / 100), "surprise_pct": sp})
        prov.series[sym] = make_series(seed * 1000 + s, n=n, beta=0.8 + 0.1 * (s % 6), shocks=shocks, market=rm,
                                       volume_event_days=vol_days, base=40.0 + s)
        prov.calendars[sym] = pd.DataFrame(rows)
        prov.infos[sym] = {"sector": sectors[s % len(sectors)], "industry": "Test", "country": "United States", "currency": "USD",
                           "exchange": "NMS", "quoteType": "EQUITY", "longName": f"Société {sym}", "marketCap": 1e9 * (s + 1),
                           "firstTradeDateMilliseconds": int(pd.Timestamp("2005-01-03").timestamp() * 1000),
                           "lastFiscalYearEnd": int(pd.Timestamp("2025-12-31").timestamp()), "sharesOutstanding": 1e8}
    return prov, symbols
