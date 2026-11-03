"""Transformations d'une série de niveaux avant l'étude : log-rendement, rendement², variance journalière (Parkinson, Garman-Klass),
différence, différenciation fractionnaire. Chaque valeur d'une série transformée à la date t ne dépend que de niveaux datés de t et avant."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features import fracdiff as FD

TRANSFORMS = ("logret", "sqret", "parkinson", "garman_klass", "diff", "fracdiff")
NEEDS_OHLC = ("parkinson", "garman_klass")
LN2 = float(np.log(2.0))


def parkinson_variance(high: pd.Series, low: pd.Series) -> pd.Series:
    """Variance journalière de Parkinson (1980) : (ln(H/L))^2 / (4 ln 2). Estimateur fondé sur l'amplitude haut-bas, bien moins bruité que r^2."""
    return np.log(high / low) ** 2 / (4 * LN2)


def garman_klass_variance(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Variance journalière de Garman-Klass (1980) : 0,5 (ln(H/L))^2 - (2 ln 2 - 1)(ln(C/O))^2."""
    return 0.5 * np.log(high / low) ** 2 - (2 * LN2 - 1) * np.log(close / open_) ** 2


def _positive(s: pd.Series) -> bool:
    return bool(len(s)) and bool((s > 0).all())


def _finite(s: pd.Series) -> pd.Series:
    return s.replace([np.inf, -np.inf], np.nan).dropna()


def apply_transform(levels: pd.Series, kind: str, *, ohlc: pd.DataFrame | None = None, d: float = 0.4) -> tuple[pd.Series, dict]:
    """Retourne `(série transformée, info)`. `info` : `kind` réellement appliqué, `fallback` (True si le log-rendement a dû devenir une
    différence parce que le niveau n'est pas toujours > 0), `label`, `needs_ohlc`."""
    if kind not in TRANSFORMS:
        raise ValueError(f"transformation inconnue : {kind}")
    levels = levels.astype(float).dropna()
    info = {"kind": kind, "fallback": False, "needs_ohlc": kind in NEEDS_OHLC}
    name = levels.name
    if kind in ("logret", "sqret"):
        if _positive(levels):
            r = np.log(levels).diff()
        else:
            r = levels.diff()
            info["fallback"] = True
            if kind == "logret":
                info["kind"] = "diff"
        out = r ** 2 if kind == "sqret" else r
    elif kind == "diff":
        out = levels.diff()
    elif kind == "fracdiff":
        info["d"] = float(d)
        out = FD.fracdiff_level(levels, d=d, threshold=FD.LEVEL_THRESHOLD)
    else:
        needed = {"Open", "High", "Low", "Close"} if kind == "garman_klass" else {"High", "Low"}
        if ohlc is None or not needed <= set(ohlc.columns):
            raise ValueError("Cette transformation demande les prix OHLC (ouverture, haut, bas, clôture), absents pour cette série.")
        px = ohlc.reindex(levels.index).dropna(subset=sorted(needed))
        px = px[(px[sorted(needed)] > 0).all(axis=1) & (px["High"] >= px["Low"])]
        out = (parkinson_variance(px["High"], px["Low"]) if kind == "parkinson"
               else garman_klass_variance(px["Open"], px["High"], px["Low"], px["Close"]))
    out = _finite(out)
    out.name = name
    return out, info
