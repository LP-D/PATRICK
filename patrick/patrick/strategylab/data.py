"""Cours du laboratoire : instruments négociés, instruments auxiliaires (filtres de régime, référence), paire synthétique, événements.

Sources : un fichier de cours importé (n'importe quelle mise en page lisible par `tabular.detect.detect_prices`) passe avant Yahoo ; Yahoo
passe par `data.sources.yfinance_source.download_ohlc` (cours ajustés des dividendes et divisions, mis en cache). L'historique est chargé
depuis le début : les indicateurs disposent ainsi de leur période de chauffe AVANT la date de début de l'étude, qui n'est pas amputée.

Calendrier : l'union des séances des instruments négociés ; un instrument sans cotation un jour donné (jour férié de sa place) garde son
dernier cours (au plus 5 séances) et ne bouge pas ce jour-là.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

import numpy as np
import pandas as pd

from patrick.strategylab import events as events_mod
from patrick.strategylab.indicators import Market

logger = logging.getLogger(__name__)

FIELDS = ("open", "high", "low", "close", "volume")
YAHOO_START = "1990-01-01"
MAX_TRADED = 60
MAX_AUX = 10
MAX_DOWNLOADS = 70
SYMBOL_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.=^_\-/ ]{0,40}$")


class DataError(ValueError):
    """Cours introuvables ou incohérents : message en français."""


def normalise(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.rename(columns={c: str(c).strip().lower().replace("adj close", "close") for c in df.columns})
    df = df.loc[:, ~df.columns.duplicated(keep="last")]
    if "close" not in df.columns:
        return None
    for c in ("open", "high", "low"):
        if c not in df.columns:
            df[c] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = np.nan
    df = df[list(FIELDS)].apply(pd.to_numeric, errors="coerce")
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    df = df[df["close"] > 0]
    for c in ("open", "high", "low"):
        df[c] = df[c].where(df[c] > 0).fillna(df["close"])
    return df if len(df) >= 2 else None


def yahoo(symbol: str) -> pd.DataFrame | None:
    from patrick.data.sources.yfinance_source import download_ohlc
    try:
        raw = download_ohlc(symbol, YAHOO_START)
    except Exception as exc:  # noqa: BLE001 -- fournisseur externe : un symbole en échec est écarté et signalé, pas fatal
        logger.info("fournisseur externe : un symbole en échec est écarté et signalé, pas fatal : %s: %s", type(exc).__name__, exc)
        return None
    return normalise(raw)


class PriceBook:
    """Cours importés d'abord, Yahoo ensuite (si permis). Retient ce qui a été trouvé où."""

    def __init__(self, uploaded: dict[str, pd.DataFrame] | None = None, allow_yahoo: bool = True, fetch: Callable[[str], pd.DataFrame | None] = yahoo):
        self.uploaded = {k.upper(): v for k, v in (uploaded or {}).items()}
        self.allow_yahoo = allow_yahoo
        self.fetch = fetch
        self.source: dict[str, str] = {}

    def downloads_needed(self, symbols: list[str]) -> list[str]:
        return [s for s in symbols if s.upper() not in self.uploaded] if self.allow_yahoo else []

    def get(self, symbol: str) -> pd.DataFrame | None:
        key = symbol.upper()
        if key in self.uploaded:
            self.source[symbol] = "fichier"
            return normalise(self.uploaded[key])
        if not self.allow_yahoo:
            return None
        df = self.fetch(symbol)
        if df is not None:
            self.source[symbol] = "Yahoo"
        return df


def parse_symbols(items) -> list[str]:
    seen: dict[str, None] = {}
    for token in items if isinstance(items, (list, tuple)) else re.split(r"[\s,;]+", str(items or "")):
        token = str(token).strip().upper()
        if token and SYMBOL_RE.match(token):
            seen.setdefault(token)
    return list(seen)


def build_market(traded: list[str], aux: list[str], book: PriceBook, end: pd.Timestamp | None = None, pair: bool = False,
                 benchmark: str | None = None, progress: Callable[[float, str], None] | None = None) -> tuple[Market, list[str], list[str]]:
    """`(marché, instruments écartés faute de cours, remarques)`."""
    say = progress or (lambda _f, _m: None)
    if not traded:
        raise DataError("Choisissez au moins un instrument.")
    if len(traded) > MAX_TRADED:
        raise DataError(f"Au plus {MAX_TRADED} instruments négociés.")
    if len(aux) > MAX_AUX:
        raise DataError(f"Au plus {MAX_AUX} instruments auxiliaires.")
    if pair and len(traded) != 2:
        raise DataError("Une stratégie de paire demande exactement deux instruments : le premier acheté, le second vendu.")
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    wanted = list(dict.fromkeys(traded + [a for a in aux if a not in traded]))
    for i, sym in enumerate(wanted):
        say(0.02 + 0.28 * i / max(len(wanted), 1), f"Cours {i + 1}/{len(wanted)} : {sym}")
        df = book.get(sym)
        if df is None:
            missing.append(sym)
        else:
            frames[sym] = df
    notes: list[str] = []
    live = [s for s in traded if s in frames]
    if not live:
        raise DataError(f"Aucun cours trouvé pour : {', '.join(traded)}.")
    if pair and len(live) != 2:
        raise DataError("Cours manquants pour l'un des deux instruments de la paire.")
    if pair:
        a, b = live
        both = pd.concat([frames[a]["close"].rename("a"), frames[b]["close"].rename("b")], axis=1).dropna()
        ratio = both["a"] / both["b"]
        ratio = 100 * ratio / ratio.iloc[0]
        name = f"{a}/{b}"
        frames[name] = pd.DataFrame({"open": ratio, "high": ratio, "low": ratio, "close": ratio, "volume": np.nan})
        live = [name]
        notes.append(f"paire traitée comme le ratio {a}/{b} : position longue {a} et courte {b} de même montant (ou l'inverse)")
    calendar = sorted(set().union(*[frames[s].index for s in live]))
    index = pd.DatetimeIndex(calendar)
    if end is not None:
        index = index[index <= pd.Timestamp(end)]
    if len(index) < 30:
        raise DataError("Trop peu de séances communes pour une étude.")
    cols = live + [s for s in frames if s not in live]
    data = {f: pd.DataFrame({s: frames[s][f].reindex(index) for s in cols}, index=index) for f in FIELDS}
    close = data["close"].ffill(limit=5)
    for s in cols:      # pas de cours prolongé avant la première ni après la dernière cotation
        own = frames[s]["close"]
        first, last = own.index[0], own.index[-1]
        close.loc[(close.index < first) | (close.index > last), s] = np.nan
    m = Market(close=close, open=data["open"].ffill(limit=5), high=data["high"].ffill(limit=5), low=data["low"].ffill(limit=5),
               volume=data["volume"], traded=live, aux=[s for s in cols if s not in live], benchmark=benchmark if benchmark in cols else None)
    return m, missing, notes


def attach_events(m: Market, source: str, symbols: list[str], file_events: pd.DataFrame | None = None, dates_text: str = "",
                  quarters: int = 40, fetch: Callable | None = None) -> list[str]:
    """Jours zéro des événements de chaque instrument négocié. `source` : `earnings` (résultats Yahoo), `file` (symbole + date), `dates` (mêmes
    dates pour tous les instruments : banque centrale, keynotes…)."""
    from patrick.research.event_study import event_day_zero
    notes = []
    if source == "earnings":
        ev = events_mod.yahoo_earnings_events([s for s in symbols if "/" not in s], limit=quarters, fetch=fetch)
        if ev.attrs.get("failed"):
            notes.append(f"résultats introuvables pour : {', '.join(ev.attrs['failed'])}")
    elif source == "file":
        if file_events is None or file_events.empty:
            raise DataError("Importez un fichier d'événements (symbole et date).")
        ev = file_events
    elif source == "dates":
        from patrick.tabular import parse
        tokens = [t for t in re.split(r"[\n;,]+", dates_text or "") if t.strip()]
        days, _ = parse.to_dates(tokens)
        days = [d for d in days.dropna()]
        if not days:
            raise DataError("Aucune date d'événement lisible.")
        ev = pd.DataFrame([{"symbol": s, "at": d} for s in m.traded for d in days])
    else:
        raise DataError("Source d'événements inconnue.")
    for sym in m.traded:
        stamps = ev.loc[ev["symbol"] == sym, "at"]
        zeros = [event_day_zero(ts, m.index) for ts in stamps]
        m.events[sym] = sorted({z for z in zeros if z is not None})
    n = sum(len(v) for v in m.events.values())
    if not n:
        raise DataError("Aucun événement ne tombe dans l'historique des cours.")
    notes.append(f"{n} événements placés sur le calendrier des séances")
    return notes
