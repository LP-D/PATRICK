"""Indicateurs techniques et calendaires, calculés pour tous les instruments à la fois (`DataFrame` séances x instruments).

Tous sont CAUSAUX : la valeur d'une séance n'utilise que les cours de cette séance et des précédentes (les canaux de Donchian excluent même la
séance du jour, sinon « casser le plus haut de 20 jours » serait impossible). Le moteur décale ensuite les décisions d'au moins une séance avant
d'exécuter. Un opérande de règle est un dictionnaire : `{"ind": "sma", "n": 50}`, avec en option `symbol` (l'indicateur d'un autre
instrument, appliqué à tous : filtre de régime « VIX < 25 »), `mult` (« 1,02 x la moyenne ») et `shift` (valeur d'il y a k séances).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Catalogue affiché par la page : clé -> (paramètres et valeurs par défaut, bornes). L'ordre est celui des menus.
INDICATORS: dict[str, dict] = {
    "price": {"params": {}},
    "sma": {"params": {"n": 50}, "range": {"n": (2, 400)}},
    "ema": {"params": {"n": 50}, "range": {"n": (2, 400)}},
    "ret": {"params": {"n": 20}, "range": {"n": (1, 400)}},
    "mom": {"params": {"n": 252, "skip": 21}, "range": {"n": (2, 500), "skip": (0, 100)}},
    "vol": {"params": {"n": 20}, "range": {"n": (5, 400)}},
    "rsi": {"params": {"n": 14}, "range": {"n": (2, 100)}},
    "zscore": {"params": {"n": 20}, "range": {"n": (5, 400)}},
    "bb_up": {"params": {"n": 20, "k": 2.0}, "range": {"n": (5, 400), "k": (0.5, 4.0)}},
    "bb_low": {"params": {"n": 20, "k": 2.0}, "range": {"n": (5, 400), "k": (0.5, 4.0)}},
    "high": {"params": {"n": 20}, "range": {"n": (2, 400)}},
    "low": {"params": {"n": 20}, "range": {"n": (2, 400)}},
    "atr": {"params": {"n": 14}, "range": {"n": (2, 100)}},
    "dist_sma": {"params": {"n": 200}, "range": {"n": (2, 400)}},
    "drawdown": {"params": {"n": 0}, "range": {"n": (0, 2000)}},
    "rel_ret": {"params": {"n": 63}, "range": {"n": (1, 400)}},
    "volume_ratio": {"params": {"n": 20}, "range": {"n": (2, 200)}},
    "dom": {"params": {}},
    "dte": {"params": {}},
    "month": {"params": {}},
    "weekday": {"params": {}},
    "event": {"params": {}},
}
CALENDAR = ("dom", "dte", "month", "weekday")


class IndicatorError(ValueError):
    """Opérande mal formé : message en français."""


@dataclass
class Market:
    """Les cours alignés sur un calendrier commun : `close` (ajusté), `open`, `high`, `low`, `volume` ; colonnes = instruments.

    `traded` : instruments négociables ; `aux` : instruments lus seulement par les règles (VIX, indice de référence…). `events` : pour chaque
    instrument, les jours zéro de ses événements (index de séances)."""
    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    traded: list[str]
    aux: list[str] = field(default_factory=list)
    events: dict[str, list[pd.Timestamp]] = field(default_factory=dict)
    benchmark: str | None = None
    cache: dict = field(default_factory=dict)

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    def returns(self) -> pd.DataFrame:
        key = ("__returns__",)
        if key not in self.cache:
            self.cache[key] = self.close.pct_change(fill_method=None).fillna(0.0)
        return self.cache[key]


def _int(spec: dict, name: str, default: int) -> int:
    value = spec.get(name, default)
    try:
        value = round(float(value))
    except (TypeError, ValueError) as exc:
        raise IndicatorError(f"Paramètre {name} invalide pour {spec.get('ind')}.") from exc
    lo, hi = INDICATORS[spec["ind"]].get("range", {}).get(name, (0, 10_000))
    if not lo <= value <= hi:
        raise IndicatorError(f"{spec['ind']} : {name} doit être compris entre {lo} et {hi}.")
    return value


def _float(spec: dict, name: str, default: float) -> float:
    try:
        value = float(spec.get(name, default))
    except (TypeError, ValueError) as exc:
        raise IndicatorError(f"Paramètre {name} invalide pour {spec.get('ind')}.") from exc
    lo, hi = INDICATORS[spec["ind"]].get("range", {}).get(name, (-1e9, 1e9))
    if not lo <= value <= hi:
        raise IndicatorError(f"{spec['ind']} : {name} doit être compris entre {lo} et {hi}.")
    return value


def _rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / down.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(down != 0, 100.0).where(up.notna())


def _calendar(index: pd.DatetimeIndex, kind: str) -> pd.Series:
    if kind == "month":
        return pd.Series(index.month, index=index, dtype=float)
    if kind == "weekday":
        return pd.Series(index.weekday, index=index, dtype=float)
    period = index.to_period("M")
    s = pd.Series(1, index=index)
    if kind == "dom":           # 1 = première séance du mois
        return s.groupby(period).cumsum().astype(float)
    return (s.groupby(period).transform("sum") - s.groupby(period).cumsum()).astype(float)     # dte : 0 = dernière séance du mois


def _events(m: Market, window: int = 60) -> pd.DataFrame:
    """Distance signée, en séances, à l'événement le plus proche de chaque instrument (−3 = trois séances avant le jour zéro)."""
    out = pd.DataFrame(np.nan, index=m.index, columns=m.close.columns)
    pos = np.arange(len(m.index))
    for sym, days in m.events.items():
        if sym not in out.columns or not days:
            continue
        zero = np.unique(m.index.searchsorted(pd.DatetimeIndex(days)))
        zero = zero[zero < len(m.index)]
        if not len(zero):
            continue
        nxt = np.searchsorted(zero, pos, side="left")
        prev = nxt - 1
        d_next = np.where(nxt < len(zero), pos - zero[np.minimum(nxt, len(zero) - 1)], -np.inf)          # <= 0
        d_prev = np.where(prev >= 0, pos - zero[np.maximum(prev, 0)], np.inf)                             # >= 0
        dist = np.where(np.abs(d_next) <= np.abs(d_prev), d_next, d_prev).astype(float)
        dist[np.abs(dist) > window] = np.nan
        out[sym] = dist
    return out


def compute(m: Market, spec: dict) -> pd.DataFrame:
    """Valeurs d'un opérande pour tous les instruments (colonnes de `m.close`). Mis en cache dans `m.cache`."""
    if not isinstance(spec, dict) or spec.get("ind") not in INDICATORS:
        raise IndicatorError(f"Indicateur inconnu : {spec.get('ind') if isinstance(spec, dict) else spec}.")
    kind = spec["ind"]
    symbol = spec.get("symbol") or None
    key = (kind, tuple(sorted((k, str(v)) for k, v in spec.items() if k not in ("mult", "shift"))))
    if key in m.cache:
        base = m.cache[key]
    else:
        base = _compute(m, spec, kind, symbol)
        m.cache[key] = base
    out = base
    shift = int(spec.get("shift", 0) or 0)
    if shift:
        if not 0 <= shift <= 250:
            raise IndicatorError("Le décalage doit être compris entre 0 et 250 séances.")
        out = out.shift(shift)
    mult = spec.get("mult")
    if mult not in (None, "", 1, 1.0):
        out = out * float(mult)
    return out


def _compute(m: Market, spec: dict, kind: str, symbol: str | None) -> pd.DataFrame:
    close, cols = m.close, m.close.columns
    if symbol is not None:
        if symbol not in cols:
            raise IndicatorError(f"Instrument {symbol} absent des cours chargés.")
        single = dict(spec)
        single.pop("symbol")
        values = compute(m, single)[symbol]
        return pd.DataFrame(np.repeat(values.to_numpy()[:, None], len(cols), axis=1), index=m.index, columns=cols)
    if kind in CALENDAR:
        s = _calendar(m.index, kind)
        return pd.DataFrame(np.repeat(s.to_numpy()[:, None], len(cols), axis=1), index=m.index, columns=cols)
    if kind == "price":
        return close
    if kind == "event":
        return _events(m)
    if kind == "sma":
        n = _int(spec, "n", 50)
        return close.rolling(n, min_periods=n).mean()
    if kind == "ema":
        n = _int(spec, "n", 50)
        return close.ewm(span=n, adjust=False, min_periods=n).mean()
    if kind == "ret":
        n = _int(spec, "n", 20)
        return close / close.shift(n) - 1
    if kind == "mom":
        n, skip = _int(spec, "n", 252), _int(spec, "skip", 21)
        if skip >= n:
            raise IndicatorError("Momentum : le saut doit être plus court que la période.")
        return close.shift(skip) / close.shift(n) - 1
    if kind == "vol":
        n = _int(spec, "n", 20)
        return m.returns().rolling(n, min_periods=n).std() * np.sqrt(TRADING_DAYS)
    if kind == "rsi":
        return _rsi(close, _int(spec, "n", 14))
    if kind == "zscore":
        n = _int(spec, "n", 20)
        mean, std = close.rolling(n, min_periods=n).mean(), close.rolling(n, min_periods=n).std()
        return (close - mean) / std.replace(0, np.nan)
    if kind in ("bb_up", "bb_low"):
        n, k = _int(spec, "n", 20), _float(spec, "k", 2.0)
        mean, std = close.rolling(n, min_periods=n).mean(), close.rolling(n, min_periods=n).std()
        return mean + k * std if kind == "bb_up" else mean - k * std
    if kind == "high":
        n = _int(spec, "n", 20)
        return m.high.rolling(n, min_periods=n).max().shift(1)
    if kind == "low":
        n = _int(spec, "n", 20)
        return m.low.rolling(n, min_periods=n).min().shift(1)
    if kind == "atr":
        n = _int(spec, "n", 14)
        prev = close.shift(1)
        tr = pd.concat([(m.high - m.low), (m.high - prev).abs(), (m.low - prev).abs()]).groupby(level=0).max()
        return tr.reindex(m.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    if kind == "dist_sma":
        n = _int(spec, "n", 200)
        return close / close.rolling(n, min_periods=n).mean() - 1
    if kind == "drawdown":
        n = _int(spec, "n", 0)
        peak = close.cummax() if n == 0 else close.rolling(n, min_periods=1).max()
        return close / peak - 1
    if kind == "rel_ret":
        n = _int(spec, "n", 63)
        if not m.benchmark or m.benchmark not in cols:
            raise IndicatorError("Force relative : choisissez un indice de référence.")
        r = close / close.shift(n) - 1
        return r.sub(r[m.benchmark], axis=0)
    if kind == "volume_ratio":
        n = _int(spec, "n", 20)
        if m.volume.isna().all().all():
            raise IndicatorError("Volumes indisponibles pour ces cours.")
        return m.volume / m.volume.rolling(n, min_periods=n).mean()
    raise IndicatorError(f"Indicateur inconnu : {kind}.")
