"""Panneau de séries alignées pour la page Exploration.

Règle de base : on ALIGNE LES NIVEAUX sur les dates communes à tous les actifs choisis, puis on calcule les rendements. Calculer
les rendements avant d'aligner mélangerait des intervalles différents (un week-end pour une action, une journée pour le bitcoin) et
fausserait toutes les corrélations. Aucune fonction de ce module ne regarde l'avenir : un rendement à la date t ne dépend que de
niveaux datés de t et avant.

Le chargement des niveaux est injecté (`loader`) : les études ne touchent jamais le réseau, les tests passent des séries synthétiques.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FREQUENCIES = ("D", "W", "M")
TRANSFORMS = ("auto", "log", "simple", "diff")
PERIODS_PER_YEAR = {"D": 252, "W": 52, "M": 12}
MIN_COMMON_OBS = 30
MAX_ASSETS = 40
LONG_START = "2000-01-01"          # même clé de cache que l'ingestion des runs (`yfinance_source.download_one`)

# Série -> niveaux (index de dates croissant, sans doublon). `None` ou série vide = indisponible.
Loader = Callable[[str, str], "pd.Series | None"]


class PanelError(ValueError):
    """Sélection inutilisable (trop peu d'actifs, pas assez de dates communes...). Message affichable tel quel."""


@dataclass
class Panel:
    levels: pd.DataFrame               # niveaux alignés sur les dates communes, à la fréquence demandée
    returns: pd.DataFrame              # transformation appliquée colonne par colonne (une ligne de moins que `levels`)
    freq: str
    transforms: dict[str, str]         # symbole -> "log" | "simple" | "diff" réellement appliqué
    warnings: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)   # symbole -> motif d'exclusion

    @property
    def periods_per_year(self) -> int:
        return PERIODS_PER_YEAR[self.freq]

    @property
    def n_obs(self) -> int:
        return len(self.returns)

    def meta(self) -> dict:
        idx = self.returns.index
        return {
            "n_obs": self.n_obs,
            "n_assets": int(self.returns.shape[1]),
            "start": idx[0].strftime("%Y-%m-%d") if len(idx) else None,
            "end": idx[-1].strftime("%Y-%m-%d") if len(idx) else None,
            "freq": self.freq,
            "periods_per_year": self.periods_per_year,
            "transforms": self.transforms,
            "dropped": self.dropped,
            "warnings": self.warnings,
        }


def _clean_levels(s: pd.Series | None) -> pd.Series | None:
    if s is None or len(s) == 0:
        return None
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    s = pd.Series(s.to_numpy(dtype=float), index=idx.normalize())
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.replace([np.inf, -np.inf], np.nan).dropna()


def _resample(s: pd.Series, freq: str) -> pd.Series:
    if freq == "D":
        return s
    rule = "W-FRI" if freq == "W" else "ME"
    return s.resample(rule).last().dropna()


def _median_gap_days(s: pd.Series) -> float:
    if len(s) < 3:
        return 0.0
    return float(np.median(np.diff(s.index.values).astype("timedelta64[D]").astype(float)))


def transform_returns(levels: pd.DataFrame, transform: str = "auto") -> tuple[pd.DataFrame, dict[str, str]]:
    """Rendements colonne par colonne. `auto` : logarithmique si le niveau est toujours > 0 (prix, indices), différence sinon
    (taux, écarts de crédit, séries pouvant changer de signe). Retourne aussi la transformation réellement appliquée."""
    if transform not in TRANSFORMS:
        raise PanelError(f"transformation inconnue : {transform}")
    out, used = {}, {}
    for col in levels.columns:
        s = levels[col]
        kind = transform
        if kind == "auto":
            kind = "log" if bool((s > 0).all()) else "diff"
        elif kind in ("log", "simple") and not bool((s > 0).all()):
            kind = "diff"                                   # un rendement n'a pas de sens sur un niveau <= 0 : repli signalé
        if kind == "log":
            r = np.log(s).diff()
        elif kind == "simple":
            r = s.pct_change()
        else:
            r = s.diff()
        out[col] = r
        used[col] = kind
    ret = pd.DataFrame(out, index=levels.index).iloc[1:]
    return ret.replace([np.inf, -np.inf], np.nan).dropna(how="any"), used


def build_panel(symbols: list[str], sources: dict[str, str], loader: Loader, *, start: str | None = None,
                end: str | None = None, freq: str = "D", transform: str = "auto",
                periodicity: Callable[[str, str], str] | None = None, max_workers: int = 8, retries: int = 1) -> Panel:
    """Charge, aligne et transforme. `sources` : symbole -> "yfinance" | "fred". `periodicity(symbol, source)` renvoie
    "daily" | "weekly" | "monthly" | "quarterly" (heuristique locale, voir `data/freshness.fred_periodicity`) ; une série plus lente
    que la fréquence demandée est exclue et signalée plutôt que gonflée par recopie (ce qui fabriquerait des corrélations)."""
    if freq not in FREQUENCIES:
        raise PanelError(f"fréquence inconnue : {freq}")
    symbols = list(dict.fromkeys(s for s in symbols if s))
    if len(symbols) < 1:
        raise PanelError("Choisis au moins un actif.")
    if len(symbols) > MAX_ASSETS:
        raise PanelError(f"Au plus {MAX_ASSETS} actifs à la fois (reçu : {len(symbols)}).")

    def fetch(sym: str):
        error = None
        for attempt in range(retries + 1):
            try:
                return sym, _clean_levels(loader(sym, sources.get(sym, "yfinance"))), None
            except Exception as exc:  # noqa: BLE001 -- frontière fournisseur : un actif en échec n'invalide pas les autres
                error = str(exc).strip().splitlines()[0][:120] if str(exc).strip() else exc.__class__.__name__
                if attempt < retries:
                    time.sleep(0.4)        # un fichier de cache en cours d'écriture par un run se relit une seconde plus tard
        return sym, None, error

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(symbols)))) as pool:
        fetched = list(pool.map(fetch, symbols))

    dropped: dict[str, str] = {}
    warnings: list[str] = []
    cols: dict[str, pd.Series] = {}
    slow_rank = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3}
    need_rank = {"D": 0, "W": 1, "M": 2}[freq]
    for sym, series, error in fetched:
        if series is None:
            dropped[sym] = error or "aucune donnée disponible"
            continue
        if periodicity is not None:
            slow = slow_rank.get(periodicity(sym, sources.get(sym, "yfinance")), 0)
            if slow > need_rank:
                dropped[sym] = "série publiée moins souvent que la fréquence demandée"
                continue
        cols[sym] = _resample(series, freq)

    if not cols:
        raise PanelError("Aucune série exploitable : " + "; ".join(f"{k} ({v})" for k, v in dropped.items()))
    levels = pd.concat(cols, axis=1, join="inner").dropna(how="any").sort_index()
    common_start = levels.index.min() if len(levels) else None
    if start:
        levels = levels[levels.index >= pd.Timestamp(start)]
    if end:
        levels = levels[levels.index <= pd.Timestamp(end)]
    if len(levels) < MIN_COMMON_OBS + 1:
        raise PanelError(f"Seulement {len(levels)} dates communes sur la période : il en faut au moins {MIN_COMMON_OBS + 1}.")

    returns, used = transform_returns(levels, transform)
    if len(returns) < MIN_COMMON_OBS:
        raise PanelError(f"Seulement {len(returns)} rendements exploitables : il en faut au moins {MIN_COMMON_OBS}.")
    if start and common_start is not None and common_start > pd.Timestamp(start) + pd.Timedelta(days=30):
        newest = max(cols, key=lambda k: cols[k].index.min())
        warnings.append(f"Période commune réduite : elle commence le {common_start:%Y-%m-%d}, date de la première cotation de {newest}.")
    if dropped:
        warnings.append("Exclus : " + ", ".join(sorted(dropped)))
    if len({k for k in used.values()}) > 1:
        warnings.append("Transformations mélangées (rendement logarithmique et différence) : les niveaux négatifs ou nuls sont "
                        "traités en différences.")
    return Panel(levels=levels, returns=returns, freq=freq, transforms=used, warnings=warnings, dropped=dropped)
