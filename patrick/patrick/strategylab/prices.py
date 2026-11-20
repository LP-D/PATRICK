"""Cours quotidiens des stratégies : `DataFrame[open, high, low, close]`, index = séances (dates sans heure).

Un fichier de cours importé (`symbol,date,open,high,low,close`) passe avant Yahoo : c'est la seule façon d'étudier des titres disparus ou des
cours post-IPO que Yahoo ne rend plus. Yahoo passe par `data.sources.yfinance_source.download_ohlc` (cours ajustés, mis en cache 7 jours).
"""
from __future__ import annotations

import io
from typing import Protocol

import pandas as pd

from patrick.placements import loader

OHLC = ("open", "high", "low", "close")


class PricesError(ValueError):
    """Fichier de cours illisible : message en français, montré tel quel."""


class PriceSource(Protocol):
    def ohlc(self, symbol: str, start: str) -> pd.DataFrame | None: ...


def _normalise(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    if not all(c in df.columns for c in ("open", "close")):
        return None
    for c in ("high", "low"):
        if c not in df.columns:
            df[c] = df["close"]
    df = df[list(OHLC)].apply(pd.to_numeric, errors="coerce")
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    df["open"] = df["open"].fillna(df["close"])
    return df if len(df) else None


class YahooPrices:
    """Cours Yahoo (réseau), un téléchargement par symbole ; un échec donne `None` (le titre est écarté et compté, pas fatal)."""

    def ohlc(self, symbol: str, start: str) -> pd.DataFrame | None:
        from patrick.data.sources.yfinance_source import download_ohlc
        raw = download_ohlc(symbol, start)
        return None if raw is None else _normalise(raw)


class UploadedPrices:
    """Cours d'un fichier importé (`symbol,date,open,high,low,close`), avec repli sur une autre source pour les symboles absents."""

    def __init__(self, data: bytes, source: str = "cours.csv", fallback: PriceSource | None = None):
        head = data[:4096].decode("utf-8", errors="replace").lstrip("﻿").splitlines()
        first_line = head[0] if head else ""
        sep = max((",", ";", "\t", "|"), key=first_line.count)
        if first_line.count(sep) == 0:
            raise PricesError(f"{source} : colonnes symbol, date, open, close attendues.")
        raw = pd.read_csv(io.BytesIO(data), sep=sep, encoding="utf-8-sig", encoding_errors="replace", dtype=str, on_bad_lines="skip")
        by_name = {str(c).strip().lower(): c for c in raw.columns}
        sym = next((by_name[n] for n in ("symbol", "ticker", "symbole") if n in by_name), None)
        day = next((by_name[n] for n in ("date", "day", "jour") if n in by_name), None)
        if sym is None or day is None or "close" not in by_name:
            raise PricesError(f"{source} : colonnes `symbol`, `date` et `close` (et idéalement `open`) introuvables.")
        frame = pd.DataFrame({"symbol": raw[sym].astype(str).str.strip().str.upper(), "date": loader.to_dates(raw[day])})
        for c in OHLC:
            frame[c] = loader.to_number(raw[by_name[c]]) if c in by_name else float("nan")
        frame = frame.dropna(subset=["date", "close"])
        if frame.empty:
            raise PricesError(f"{source} : aucun cours exploitable.")
        self._by_symbol = {s: g.set_index("date")[list(OHLC)] for s, g in frame.groupby("symbol")}
        self.fallback = fallback
        self.symbols = sorted(self._by_symbol)

    def ohlc(self, symbol: str, start: str) -> pd.DataFrame | None:
        if symbol in self._by_symbol:
            return _normalise(self._by_symbol[symbol])
        return self.fallback.ohlc(symbol, start) if self.fallback else None


def downloads_needed(symbols: list[str], source: PriceSource) -> list[str]:
    """Les symboles qu'il faudra télécharger chez Yahoo (ceux que les cours importés ne couvrent pas) : c'est ce nombre, pas celui des événements,
    qui est borné, car chaque téléchargement prend une demi-seconde et sollicite le fournisseur."""
    if isinstance(source, UploadedPrices):
        return [] if source.fallback is None else [s for s in symbols if s not in source.symbols]
    return list(symbols)
