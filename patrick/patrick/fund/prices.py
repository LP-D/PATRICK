"""Cotations des stratégies : Yahoo Finance + persistance définitive dans
`fund_price` (spec §6). Yahoo retire les contrats expirés ; les cotations
utilisées restent donc stockées pour que la valeur d'une stratégie reste
calculable. Clôtures non ajustées des dividendes (le dividende est crédité
au cash par le moteur), ajustées des fractionnements.

`download_bars` est une fonction de module : les tests la remplacent."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from dataclasses import dataclass

import pandas as pd

from patrick.fund.engine import DEFAULT_REF_RATES, MarketData

HISTORY_START = "2000-01-01"
MAX_AGE_HOURS = 6.0
BAR_COLUMNS = ["open", "high", "low", "close", "volume", "dividend"]
PENCE = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ZAc": ("ZAR", 0.01), "ILA": ("ILS", 0.01)}
# Série FRED du taux court de chaque devise (si FRED_API_KEY est défini).
FRED_RATE_SERIES = {"USD": "SOFR", "EUR": "ECBESTRVOLWGTTRMDMNRT", "GBP": "IUDSOIA"}


def iso_currency(raw: str | None) -> tuple[str | None, float]:
    """(devise ISO, facteur d'échelle) : les cours en pence deviennent des livres."""
    if raw is None:
        return None, 1.0
    return PENCE.get(raw, (raw, 1.0))


def download_bars(symbol: str, start: str | None = None) -> tuple[pd.DataFrame | None, str | None]:
    """(barres, devise brute) depuis Yahoo, ou (None, None). Frontière fournisseur :
    un symbole en échec ne casse jamais une page."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        raw = ticker.history(start=start or HISTORY_START, auto_adjust=False, actions=True)
        if raw is None or raw.empty:
            return None, None
        currency = (ticker.history_metadata or {}).get("currency")
    except Exception as exc:  # noqa: BLE001 -- frontière fournisseur
        print(f"  [WARN] yfinance {symbol}: {str(exc)[:100]}")
        return None, None
    df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                             "Volume": "volume", "Dividends": "dividend"})
    for col in BAR_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    df = df[BAR_COLUMNS].dropna(subset=["close"])
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index(), currency


def save_bars(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, raw_currency: str | None,
              now: dt.datetime | None = None) -> None:
    currency, scale = iso_currency(raw_currency)
    rows = []
    for day, r in df.iterrows():
        px = [None if pd.isna(r[c]) else float(r[c]) * scale for c in ("open", "high", "low", "close")]
        rows.append((symbol, day.date().isoformat(), *px, float(r["volume"]) if not pd.isna(r["volume"]) else 0.0,
                     float(r["dividend"]) * scale if not pd.isna(r["dividend"]) else 0.0))
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.executemany(
            "INSERT INTO fund_price (symbol, day, open, high, low, close, volume, dividend) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol, day) DO UPDATE SET open = excluded.open, "
            "high = excluded.high, low = excluded.low, close = excluded.close, volume = excluded.volume, "
            "dividend = excluded.dividend", rows)
        conn.execute(
            "INSERT INTO fund_price_meta (symbol, currency, refreshed_at) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET currency = COALESCE(excluded.currency, fund_price_meta.currency), "
            "refreshed_at = excluded.refreshed_at", (symbol, currency, stamp))


def load_bars(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame | None:
    rows = conn.execute("SELECT day, open, high, low, close, volume, dividend FROM fund_price "
                        "WHERE symbol = ? ORDER BY day", (symbol,)).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["day", *BAR_COLUMNS])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("day")))
    return df


def get_meta(conn: sqlite3.Connection, symbol: str) -> dict | None:
    row = conn.execute("SELECT currency, refreshed_at FROM fund_price_meta WHERE symbol = ?", (symbol,)).fetchone()
    return {"currency": row[0], "refreshed_at": row[1]} if row else None


@dataclass
class BarsResult:
    df: pd.DataFrame | None
    currency: str | None
    status: str          # fresh | stored | missing


def ensure_bars(conn: sqlite3.Connection, symbol: str, *, max_age_hours: float = MAX_AGE_HOURS,
                now: dt.datetime | None = None) -> BarsResult:
    """Rafraîchit `symbol` si la dernière actualisation a plus de `max_age_hours`.
    Hors ligne ou symbole retiré : on sert ce qui est stocké."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stored, meta = load_bars(conn, symbol), get_meta(conn, symbol)
    if stored is not None and meta and meta["refreshed_at"]:
        age = now - dt.datetime.strptime(meta["refreshed_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if age < dt.timedelta(hours=max_age_hours):
            return BarsResult(stored, meta["currency"], "fresh")
    start = (stored.index[-1] - pd.Timedelta(days=7)).date().isoformat() if stored is not None else None
    fetched, raw_ccy = download_bars(symbol, start)
    if fetched is not None and not fetched.empty:
        save_bars(conn, symbol, fetched, raw_ccy, now)
        return BarsResult(load_bars(conn, symbol), get_meta(conn, symbol)["currency"], "fresh")
    if stored is not None:
        return BarsResult(stored, meta["currency"] if meta else None, "stored")
    return BarsResult(None, None, "missing")


def fx_symbol(base: str, currency: str) -> str:
    return f"{base}{currency}=X"


def fx_series(conn: sqlite3.Connection, base: str, currency: str) -> pd.Series | None:
    """Unités de `base` par unité de `currency` (inverse du cours Yahoo EURUSD=X)."""
    res = ensure_bars(conn, fx_symbol(base, currency))
    if res.df is None or res.df.empty:
        return None
    return (1.0 / res.df["close"]).rename(currency)


def reference_rates(currencies: set[str]) -> tuple[dict[str, float], list[str]]:
    """Taux court annuel par devise (FRED si FRED_API_KEY est défini, sinon constantes
    de `engine.DEFAULT_REF_RATES`) et avertissements à afficher."""
    rates: dict[str, float] = {}
    notes: list[str] = []
    for ccy in sorted(currencies):
        value = None
        if os.environ.get("FRED_API_KEY") and ccy in FRED_RATE_SERIES:
            from patrick.data.sources import fred_source
            s = fred_source.download_series(ccy, FRED_RATE_SERIES[ccy], "2024-01-01")
            if s is not None and len(s.dropna()):
                value = float(s.dropna().iloc[-1]) / 100.0
        if value is None:
            value = DEFAULT_REF_RATES.get(ccy, 0.03)
            notes.append(f"taux de référence {ccy} : constante {value:.2%} (FRED indisponible ou non configuré)")
        rates[ccy] = value
    return rates, notes


def build_market(conn: sqlite3.Connection, orders: list[dict], base: str = "EUR",
                 with_rates: bool = True) -> tuple[MarketData, list[str]]:
    """Données de marché pour rejouer `orders` : barres de chaque symbole, change de
    chaque devise étrangère, taux de référence des devises des CFD."""
    market = MarketData(base_currency=base)
    notes: list[str] = []
    currencies: set[str] = set()
    cfd_currencies: set[str] = set()
    for o in orders:
        sym = o["symbol"]
        if sym not in market.bars:
            res = ensure_bars(conn, sym)
            if res.df is None:
                notes.append(f"{sym} : aucune cotation disponible")
                continue
            market.bars[sym] = res.df
            if res.status == "stored":
                notes.append(f"{sym} : cotations hors ligne (dernière donnée stockée {res.df.index[-1].date()})")
        currencies.add(o["currency"])
        if o["instrument_kind"] == "cfd":
            cfd_currencies.add(o["currency"])
    for ccy in sorted(currencies - {base}):
        s = fx_series(conn, base, ccy)
        if s is None:
            notes.append(f"change {base}/{ccy} indisponible")
        else:
            market.fx[ccy] = s
    if with_rates and cfd_currencies:
        market.ref_rates, rate_notes = reference_rates(cfd_currencies)
        notes.extend(rate_notes)
    return market, notes
