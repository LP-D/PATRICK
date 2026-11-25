"""Détecteur de paires cointégrées (FO25 du 25/11) : parmi des actifs, les paires dont l'écart revient à sa moyenne.

Pour chaque paire (A, B) : test d'Engle-Granger sur les logarithmes des cours alignés (`statsmodels.tsa.stattools.coint`), coefficient de
couverture (régression de log A sur log B) et demi-vie du retour à la moyenne de l'écart (AR(1) : ln 2 / −ln φ). Avec n actifs on teste
n(n−1)/2 paires : sans correction, 5 % d'entre elles sortiraient « cointégrées » par hasard. Les p-values sont donc corrigées par
Benjamini-Hochberg (`q`), et seules les paires sous `q_max` avec une demi-vie raisonnable (5 à 120 séances) sont retenues.

Une paire retenue reste une hypothèse : la cointégration casse (fusions, changements de régime) ; elle se teste ensuite hors échantillon dans
le laboratoire de stratégies.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd


def _bh(p: list[float]) -> list[float]:
    n = len(p)
    order = np.argsort(p)
    q = np.empty(n)
    running = 1.0
    for rank, idx in enumerate(order[::-1]):
        k = n - rank
        running = min(running, p[idx] * n / k)
        q[idx] = running
    return q.tolist()


def half_life(spread: pd.Series) -> float | None:
    s = spread.dropna()
    if len(s) < 30:
        return None
    x, y = s.shift(1).dropna(), s.diff().dropna()
    x = x.loc[y.index]
    beta = float(np.polyfit(x.to_numpy(), y.to_numpy(), 1)[0])
    phi = 1.0 + beta
    if not 0 < phi < 1:
        return None
    return math.log(2) / -math.log(phi)


def scan(prices: dict[str, pd.Series], min_obs: int = 500, q_max: float = 0.10, half_life_range: tuple[float, float] = (5, 120)) -> list[dict]:
    """Paires retenues, des plus sûres aux moins sûres : `{a, b, hedge, p, q, half_life, n}`."""
    from statsmodels.tsa.stattools import coint

    logs = {s: np.log(v.dropna()[v.dropna() > 0]) for s, v in prices.items() if v is not None and len(v.dropna()) >= min_obs}
    rows = []
    for a, b in itertools.combinations(sorted(logs), 2):
        frame = pd.concat([logs[a], logs[b]], axis=1, join="inner").dropna()
        if len(frame) < min_obs:
            continue
        ya, yb = frame.iloc[:, 0], frame.iloc[:, 1]
        try:
            _stat, p, _crit = coint(ya, yb)
        except (ValueError, np.linalg.LinAlgError):
            continue
        hedge = float(np.polyfit(yb.to_numpy(), ya.to_numpy(), 1)[0])
        rows.append({"a": a, "b": b, "hedge": hedge, "p": float(p), "half_life": half_life(ya - hedge * yb), "n": len(frame)})
    if not rows:
        return []
    for row, q in zip(rows, _bh([r["p"] for r in rows]), strict=True):
        row["q"] = q
    lo, hi = half_life_range
    kept = [r for r in rows if r["q"] <= q_max and r["half_life"] is not None and lo <= r["half_life"] <= hi]
    return sorted(kept, key=lambda r: (r["q"], r["half_life"]))
