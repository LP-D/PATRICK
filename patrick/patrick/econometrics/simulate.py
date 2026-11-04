"""Processus simulés à paramètres connus : sert aux tests (on vérifie que les méthodes retrouvent ce qu'on y a mis) et aux figures du cours.

Les séries sont indexées par des jours ouvrés. Les rendements GARCH sont en POURCENT (comme `arch` les attend)."""
from __future__ import annotations

import numpy as np
import pandas as pd

START = "2010-01-04"


def _index(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(START, periods=n)


def _shocks(rng: np.random.Generator, n: int, dist: str) -> np.ndarray:
    if dist == "normal":
        return rng.standard_normal(n)
    if dist == "t5":                                    # Student à 5 degrés de liberté, ramenée à variance 1
        return rng.standard_t(5, n) / np.sqrt(5 / 3)
    raise ValueError(f"loi inconnue : {dist}")


def garch11(n: int, omega: float, alpha: float, beta: float, *, gamma: float = 0.0, seed: int = 0, burn: int = 500,
            dist: str = "normal", return_variance: bool = False):
    """GARCH(1,1) (GJR si `gamma` > 0) : r_t = sigma_t z_t, sigma_t^2 = omega + (alpha + gamma 1[r_{t-1}<0]) r_{t-1}^2 + beta sigma_{t-1}^2.
    `return_variance=True` renvoie aussi la vraie variance conditionnelle sigma_t^2 (pour juger une prévision contre la vérité)."""
    persistence = alpha + beta + gamma / 2
    if persistence >= 1 or min(omega, alpha, beta, gamma) < 0:
        raise ValueError("paramètres hors du domaine stationnaire (alpha + beta + gamma/2 < 1, tous positifs)")
    rng = np.random.default_rng(seed)
    z = _shocks(rng, n + burn, dist)
    h = omega / (1 - persistence)
    out = np.empty(n + burn)
    var = np.empty(n + burn)
    prev = 0.0
    for t in range(n + burn):
        h = omega + (alpha + (gamma if prev < 0 else 0.0)) * prev * prev + beta * h if t else h
        prev = np.sqrt(h) * z[t]
        out[t], var[t] = prev, h
    r = pd.Series(out[burn:], index=_index(n), name="r")
    return (r, pd.Series(var[burn:], index=r.index, name="sigma2")) if return_variance else r


def arma(n: int, ar: tuple[float, ...] = (), ma: tuple[float, ...] = (), *, sigma: float = 1.0, const: float = 0.0, seed: int = 0,
         burn: int = 200) -> pd.Series:
    """ARMA(p,q) gaussien : x_t = const + sum phi_i x_{t-i} + e_t + sum theta_j e_{t-j}."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0, sigma, n + burn)
    x = np.zeros(n + burn)
    for t in range(n + burn):
        v = const + e[t]
        for i, phi in enumerate(ar, start=1):
            if t - i >= 0:
                v += phi * x[t - i]
        for j, theta in enumerate(ma, start=1):
            if t - j >= 0:
                v += theta * e[t - j]
        x[t] = v
    return pd.Series(x[burn:], index=_index(n), name="x")


def arfima(n: int, d: float, *, seed: int = 0, truncation: int = 2000) -> pd.Series:
    """ARFIMA(0,d,0) : x_t = (1 - L)^(-d) e_t = sum_k psi_k e_{t-k}, psi_0 = 1, psi_k = psi_{k-1}(k - 1 + d)/k (mémoire longue pour 0 < d < 0,5)."""
    rng = np.random.default_rng(seed)
    psi = np.ones(truncation)
    for k in range(1, truncation):
        psi[k] = psi[k - 1] * (k - 1 + d) / k
    e = rng.standard_normal(n + truncation)
    x = np.convolve(e, psi)[truncation:truncation + n]
    return pd.Series(x, index=_index(n), name="x")


def random_walk(n: int, *, sigma: float = 1.0, drift: float = 0.0, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(drift + rng.normal(0.0, sigma, n)), index=_index(n), name="x")
