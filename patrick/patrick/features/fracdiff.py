"""Différenciation fractionnaire (López de Prado, AFML ch. 5) : un module OPTIONNEL, désactivé par défaut et relié à aucun entraînement.

Un cours n'est pas stationnaire (sa moyenne dérive) ; le rendement l'est mais a perdu toute mémoire du niveau. La différenciation fractionnaire
d'ordre d entre 0 (le niveau) et 1 (le rendement) cherche le plus petit d qui rend la série stationnaire en gardant le plus de mémoire.

Version « fenêtre fixe » (FFD) : les poids w_0 = 1, w_k = -w_{k-1}(d - k + 1)/k sont coupés dès que leur valeur absolue passe sous `threshold`, et
chaque valeur ne dépend que des `width` observations précédentes, donc seulement du passé : aucune fuite. Les `width - 1` premières
valeurs sont indéfinies et absentes du résultat."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ffd_weights(d: float, threshold: float = 1e-4, max_width: int = 2000) -> np.ndarray:
    """Poids de la fenêtre fixe, du plus ancien (le dernier calculé) au plus récent (poids 1 en dernière position)."""
    if d < 0:
        raise ValueError("d doit être positif ou nul")
    w = [1.0]
    k = 1
    while k < max_width:
        nxt = -w[-1] * (d - k + 1) / k
        if abs(nxt) < threshold:
            break
        w.append(nxt)
        k += 1
    return np.array(w[::-1])


def frac_diff_ffd(series: pd.Series, d: float, threshold: float = 1e-4) -> pd.Series:
    """Série différenciée fractionnairement d'ordre `d` ; chaque valeur est la somme pondérée des `width` dernières observations (celle du jour incluse)."""
    s = series.dropna()
    w = ffd_weights(d, threshold)
    width = len(w)
    if len(s) < width:
        return pd.Series(dtype=float, name=series.name)
    x = s.to_numpy(dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(x, width)
    return pd.Series(windows @ w, index=s.index[width - 1:], name=series.name)


# Ordre et seuil du niveau fractionnaire de la méthode 3 (ADR 0011). d = 0,4 garde l'essentiel de la mémoire du niveau (corrélation de l'ordre de 0,9 avec lui sur
# un cours) tout en rendant stationnaires la plupart des séries de cours et de taux ; un seuil de 1e-3 coupe la fenêtre vers 140 observations (1e-4 : plus de 700,
# soit trois ans de lignes sans valeur au début de l'historique).
LEVEL_ORDER = 0.4
LEVEL_THRESHOLD = 1e-3


def fracdiff_level(series: pd.Series, d: float = LEVEL_ORDER, threshold: float = LEVEL_THRESHOLD) -> pd.Series:
    """Niveau de `series` différencié fractionnairement, sur l'index d'origine (NaN avant la première fenêtre pleine). Log du niveau quand la série est
    strictement positive (cours, indices) : la dérive d'un cours est multiplicative. Causal : chaque valeur ne dépend que des `width` dernières observations."""
    s = series.astype(float)
    known = s.dropna()
    base = np.log(s) if len(known) and bool((known > 0).all()) else s
    return frac_diff_ffd(base, d, threshold).reindex(series.index)


def _adf_pvalue(x: np.ndarray) -> float:
    from statsmodels.tsa.stattools import adfuller
    return float(adfuller(x, maxlag=1, regression="c", autolag=None)[1])


def min_stationary_d(series: pd.Series, grid=None, p_threshold: float = 0.05, threshold: float = 1e-4, log: bool = True,
                     min_obs: int = 200) -> dict:
    """Plus petit `d` de la grille pour lequel le test ADF (stationnarité) rejette la racine unitaire à `p_threshold`.

    Renvoie, pour chaque d essayé, la p-value et la corrélation avec la série d'origine (la mémoire conservée), puis le d retenu (`None` si aucun
    n'est stationnaire, y compris d = 1 sur une série dont même le rendement serait instable). `log=True` travaille sur le log du cours."""
    grid = list(np.round(np.arange(0.0, 1.01, 0.1), 2)) if grid is None else [float(g) for g in grid]
    base = np.log(series.dropna()) if log else series.dropna()
    tried = []
    chosen = None
    for d in grid:
        fd = frac_diff_ffd(base, d, threshold)
        if len(fd) < min_obs:
            tried.append({"d": d, "n": len(fd), "pvalue": None, "corr": None, "stationary": False})
            continue
        corr = float(np.corrcoef(base.loc[fd.index].to_numpy(), fd.to_numpy())[0, 1]) if fd.std() > 0 else None
        p = _adf_pvalue(fd.to_numpy())
        ok = p < p_threshold
        tried.append({"d": d, "n": len(fd), "pvalue": p, "corr": corr, "stationary": ok, "width": len(ffd_weights(d, threshold))})
        if ok and chosen is None:
            chosen = d
            break
    return {"d": chosen, "tried": tried, "p_threshold": p_threshold, "log": log}
