"""DCC-GARCH (Engle 2002) : covariance du lendemain avec des corrélations qui évoluent dans le temps -- A2.

Deux étapes, comme l'estimateur original :
1. un GARCH(1,1) par actif (`arch`, rendements en %) donne la volatilité conditionnelle prévue pour le lendemain et les résidus standardisés ;
2. un DCC(1,1) sur ces résidus : Q_t = (1 - a - b) Q̄ + a z_{t-1} z_{t-1}' + b Q_{t-1}, R_t = Q_t normalisée ; (a, b) maximisent la
   vraisemblance gaussienne de la partie corrélation (a, b >= 0, a + b < 1).
Covariance prévue : H = D R D, D = volatilités prévues. Les corrélations d'une crise montent en quelques jours au lieu de se diluer dans un an
d'historique : c'est ce que Markowitz, la parité de risque et les fonds combinés gagnent à voir. Tout est causal (rien après la dernière date).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize


def _garch_step(r: pd.Series) -> tuple[np.ndarray, float]:
    """Résidus standardisés et volatilité prévue (en %) du lendemain d'un GARCH(1,1) à moyenne constante."""
    from arch import arch_model

    res = arch_model(r * 100, mean="Constant", vol="GARCH", p=1, q=1, dist="normal", rescale=False).fit(disp="off")
    z = (res.resid / res.conditional_volatility).to_numpy()
    sigma_next = float(np.sqrt(res.forecast(horizon=1, reindex=False).variance.to_numpy()[-1, 0]))
    return z, sigma_next


def _dcc_path(z: np.ndarray, a: float, b: float) -> tuple[float, np.ndarray]:
    """Log-vraisemblance (partie corrélation) et Q du lendemain."""
    T, _n = z.shape
    qbar = np.cov(z, rowvar=False)
    q = qbar.copy()
    ll = 0.0
    for t in range(T):
        d = np.sqrt(np.clip(np.diag(q), 1e-12, None))
        r = q / np.outer(d, d)
        sign, logdet = np.linalg.slogdet(r)
        if sign <= 0:
            return -1e12, q
        ll -= 0.5 * (logdet + z[t] @ np.linalg.solve(r, z[t]) - z[t] @ z[t])
        q = (1 - a - b) * qbar + a * np.outer(z[t], z[t]) + b * q
    return ll, q


def dcc_covariance(returns: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Covariance (rendements journaliers, pas en %) prévue pour la séance suivant la dernière ligne de `returns` (colonnes = actifs,
    lignes communes sans trou), et les paramètres `{a, b, persistence}`."""
    data = returns.dropna()
    if len(data) < 250 or data.shape[1] < 2:
        raise ValueError("DCC : au moins 250 dates communes et deux actifs.")
    zs, sig = [], []
    for col in data.columns:
        z, s = _garch_step(data[col])
        zs.append(z)
        sig.append(s / 100)
    z = np.column_stack(zs)
    z = z[np.isfinite(z).all(axis=1)]

    def neg(p):
        a, b = p
        if a < 0 or b < 0 or a + b >= 0.999:
            return 1e12
        return -_dcc_path(z, a, b)[0]

    best = optimize.minimize(neg, x0=[0.03, 0.94], method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-3, "maxiter": 200})
    a, b = (float(v) for v in best.x)
    _ll, q_next = _dcc_path(z, a, b)
    d = np.sqrt(np.diag(q_next))
    r_next = q_next / np.outer(d, d)
    D = np.diag(sig)
    cov = pd.DataFrame(D @ r_next @ D, index=data.columns, columns=data.columns)
    return cov, {"a": a, "b": b, "persistence": a + b, "n_obs": len(z)}
