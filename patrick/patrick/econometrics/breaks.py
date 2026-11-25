"""Ruptures structurelles multiples (Bai et Perron 1998, 2003) et mémoire longue par Whittle local (Robinson 1995) -- A18.

`bai_perron` : ruptures de MOYENNE d'une série (rendements, écarts, taux de variation), segmentation optimale au sens des moindres carrés par
programmation dynamique (exacte, pas une recherche gloutonne), segments d'au moins `min_frac` de l'échantillon, nombre de ruptures choisi au
BIC (Bai et Perron recommandent le BIC ou le LWZ ; le BIC est le plus courant). Zivot-Andrews, déjà dans l'étude, ne cherche qu'une rupture.

`local_whittle_d` : paramètre d'intégration fractionnaire d (ARFIMA(0, d, 0) autour des basses fréquences), estimateur semi-paramétrique de
Whittle local, plus efficace que la régression log-périodogramme (GPH, `mean_models.gph_d`) ; erreur-type asymptotique 1 / (2 racine(m)).
d = 0 : mémoire courte ; d < 0 : antipersistance ; 0 < d < 0,5 : mémoire longue stationnaire ; d >= 0,5 : non stationnaire.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
from scipy import optimize


def _segment_cost(cum: np.ndarray, cum2: np.ndarray, i: int, j: int) -> float:
    """Somme des carrés des écarts à la moyenne sur x[i:j] (sommes cumulées : O(1))."""
    n = j - i
    s = cum[j] - cum[i]
    return float(cum2[j] - cum2[i] - s * s / n)


def bai_perron(x: pd.Series, max_breaks: int = 5, min_frac: float = 0.15) -> dict:
    """Ruptures de moyenne : `{"n_breaks", "breaks": [dates], "segments": [{start, end, mean, n}], "bic": {m: bic}}`."""
    s = pd.Series(x).dropna().astype(float)
    y = s.to_numpy()
    n = len(y)
    h = max(math.ceil(min_frac * n), 5)
    if n < 2 * h:
        raise ValueError("Série trop courte pour chercher des ruptures (au moins deux segments minimaux).")
    max_breaks = max(0, min(max_breaks, n // h - 1))
    cum = np.concatenate([[0.0], np.cumsum(y)])
    cum2 = np.concatenate([[0.0], np.cumsum(y * y)])
    INF = float("inf")
    # best[m][j] : coût minimal de x[0:j] découpé en m+1 segments ; arg[m][j] : début du dernier segment
    best = np.full((max_breaks + 1, n + 1), INF)
    arg = np.zeros((max_breaks + 1, n + 1), dtype=int)
    for j in range(h, n + 1):
        best[0, j] = _segment_cost(cum, cum2, 0, j)
    for m in range(1, max_breaks + 1):
        for j in range((m + 1) * h, n + 1):
            costs = [(best[m - 1, i] + _segment_cost(cum, cum2, i, j), i) for i in range(m * h, j - h + 1) if best[m - 1, i] < INF]
            if costs:
                best[m, j], arg[m, j] = min(costs)
    bic = {}
    for m in range(max_breaks + 1):
        ssr = best[m, n]
        if not np.isfinite(ssr) or ssr <= 0:
            continue
        k = 2 * m + 1                                          # m dates de rupture + (m + 1) moyennes
        bic[m] = n * math.log(ssr / n) + k * math.log(n)
    m_star = min(bic, key=bic.get)
    cuts, j = [], n
    for m in range(m_star, 0, -1):
        i = int(arg[m, j])
        cuts.append(i)
        j = i
    cuts = sorted(cuts)
    bounds = [0, *cuts, n]
    segments = [{"start": s.index[a].strftime("%Y-%m-%d"), "end": s.index[b - 1].strftime("%Y-%m-%d"), "mean": float(y[a:b].mean()),
                 "n": int(b - a)} for a, b in itertools.pairwise(bounds)]
    return {"n_breaks": m_star, "breaks": [s.index[c].strftime("%Y-%m-%d") for c in cuts], "segments": segments,
            "bic": {int(m): float(v) for m, v in bic.items()}, "min_segment": h}


def local_whittle_d(x: pd.Series, m: int | None = None) -> dict:
    """d de Whittle local sur les `m` premières fréquences de Fourier (défaut n^0,65) ; `{"d", "se", "m", "label"}`."""
    y = pd.Series(x).dropna().astype(float).to_numpy()
    n = len(y)
    if n < 128:
        raise ValueError("Série trop courte pour Whittle local (au moins 128 observations).")
    m = int(m or n ** 0.65)
    m = max(10, min(m, n // 2 - 1))
    fft = np.fft.fft(y - y.mean())
    lam = 2 * np.pi * np.arange(1, m + 1) / n
    periodogram = (np.abs(fft[1:m + 1]) ** 2) / (2 * np.pi * n)

    def objective(d: float) -> float:
        g = np.mean(lam ** (2 * d) * periodogram)
        return math.log(g) - 2 * d * np.mean(np.log(lam))

    res = optimize.minimize_scalar(objective, bounds=(-0.49, 0.99), method="bounded")
    d = float(res.x)
    if abs(d) < 0.1:
        label = "mémoire courte"
    elif d < 0:
        label = "antipersistance (d < 0 : les écarts se corrigent)"
    elif d < 0.5:
        label = "mémoire longue stationnaire"
    else:
        label = "non stationnaire (d >= 0,5)"
    return {"d": d, "se": 1 / (2 * math.sqrt(m)), "m": m, "label": label}
