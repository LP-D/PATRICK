"""Portefeuilles optimaux et validation walk-forward (port des sections 4 du notebook PEE).

Quatre objectifs, chacun avec ou sans plafond par fonds (hors monétaire) :
- `max_return`  : maximise le rendement annualisé composé ;
- `max_sharpe`  : portefeuille tangent, 100 % investi en fonds risqués (Sharpe face au monétaire) ;
- `min_vol`     : minimise la volatilité ;
- `max_sortino` : maximise le Sortino (volatilité à la baisse seulement).
L'optimisation est un SLSQP à départs multiples (25 départs : un seul départ s'arrête souvent dans un minimum local sur 15 fonds corrélés).

Un portefeuille optimisé sur tout l'historique est « trop beau » par construction. `walk_forward` le juge honnêtement : on réoptimise chaque
année sur le passé seul (au moins `min_train` mois), on applique les poids au mois suivant, et on compare au 1/N sur les mêmes mois. L'écart
de Sharpe n'est jugé significatif qu'à deux erreurs-types (Lo, 2002 : erreur-type du Sharpe ~ sqrt((1 + SR²/2) / années)).
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from patrick.placements.stats import FREQ

OBJECTIVES = ("max_return", "max_sharpe", "min_vol", "max_sortino")
N_STARTS = 25
WEIGHT_TOLERANCE = 1e-8


def _multistart(fun: Callable, n: int, bounds: list[tuple[float, float]], k: int = N_STARTS, seed: int = 0) -> np.ndarray:
    if n < 1 or sum(upper for _, upper in bounds) < 1 - 1e-12:
        raise ValueError("Contraintes incompatibles : la somme des plafonds doit couvrir 100 %.")
    upper = np.asarray([b[1] for b in bounds], dtype=float)
    rng, best = np.random.default_rng(seed), None
    for i in range(k):
        x0 = np.minimum(rng.dirichlet(np.ones(n)), upper) if i else np.minimum(np.full(n, 1 / n), upper)
        while x0.sum() < 1 - 1e-12:
            capacity = upper - x0
            x0 = x0 + (1 - x0.sum()) * capacity / capacity.sum()
        res = minimize(fun, x0, bounds=bounds, method="SLSQP", constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                       options={"maxiter": 1000, "ftol": 1e-14})
        if res.success and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        raise ValueError("L'optimiseur n'a trouvé aucune solution valide.")
    return best.x


def _risky(R: pd.DataFrame, cash: str) -> list[str]:
    return [c for c in R.columns if c != cash]


def opt_max_return(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS) -> pd.Series:
    cols, X = list(R.columns), R.values
    w = _multistart(lambda w: -np.log1p(X @ w).mean() * FREQ, len(cols), [(0, 1.0 if c == cash else cap) for c in cols], k=k)
    return pd.Series(w, index=cols)


def opt_max_sharpe(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS) -> pd.Series:
    risky = _risky(R, cash)
    ex = R[risky].sub(R[cash], axis=0)
    m_, C = ex.mean().values * FREQ, ex.cov().values * FREQ
    w = _multistart(lambda w: -(w @ m_) / np.sqrt(max(w @ C @ w, 1e-14)), len(risky), [(0, cap)] * len(risky), k=k)
    return pd.Series(w, index=risky).reindex(R.columns).fillna(0.0)


def opt_min_vol(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS) -> pd.Series:
    risky = _risky(R, cash)
    C = R[risky].cov().values * FREQ
    w = _multistart(lambda w: w @ C @ w, len(risky), [(0, cap)] * len(risky), k=k)
    return pd.Series(w, index=risky).reindex(R.columns).fillna(0.0)


def opt_max_sortino(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS) -> pd.Series:
    risky = _risky(R, cash)
    rf, X = R[cash].values, R[risky].values

    def objective(w):
        excess = X @ w - rf
        downside = np.minimum(excess, 0)
        return -(excess.mean() * FREQ) / max(np.sqrt(np.mean(downside ** 2) * FREQ), 1e-12)

    w = _multistart(objective, len(risky), [(0, cap)] * len(risky), k=k)
    return pd.Series(w, index=risky).reindex(R.columns).fillna(0.0)


OPTIMIZERS: dict[str, Callable[..., pd.Series]] = {
    "max_return": opt_max_return, "max_sharpe": opt_max_sharpe, "min_vol": opt_min_vol, "max_sortino": opt_max_sortino,
}


def clean_weights(w: pd.Series, tolerance: float = WEIGHT_TOLERANCE) -> pd.Series:
    w = w.copy().astype(float)
    w[w.abs() < tolerance] = 0.0
    total = w.sum()
    if total <= 0:
        raise ValueError("Allocation invalide : somme des poids nulle.")
    return w / total


def cagr(p: pd.Series) -> float:
    return float((1 + p).prod() ** (FREQ / len(p)) - 1)


def mdd_series(x: pd.Series) -> float:
    w = (1 + x).cumprod()
    return float((w / w.cummax() - 1).min())


def evaluate(w: pd.Series, R: pd.DataFrame, cash: str, daily: pd.DataFrame) -> dict:
    """Indicateurs d'un portefeuille à poids constants sur le panel mensuel `R` ; `daily` : rendements quotidiens des fonds (drawdown quotidien)."""
    w = w[w > 0]
    p = (R[w.index] * w).sum(axis=1)
    e = p - R[cash]
    d = (daily.loc[R.index[0] - pd.offsets.MonthEnd(1):, w.index].dropna() * w).sum(axis=1)
    roll12 = (1 + p).rolling(12).apply(np.prod, raw=True) - 1
    downside = np.minimum(e, 0)
    q05 = p.quantile(0.05)
    return {
        "cagr": cagr(p), "vol": float(p.std() * np.sqrt(FREQ)),
        "sharpe": float(e.mean() / max(e.std(), 1e-12) * np.sqrt(FREQ)),
        "sortino": float(e.mean() / max(np.sqrt(np.mean(downside ** 2)), 1e-12) * np.sqrt(FREQ)),
        "max_dd_daily": mdd_series(d) if len(d) else float("nan"), "max_dd_monthly": mdd_series(p),
        "worst_month": float(p.min()), "var5": float(q05), "cvar5": float(p[p <= q05].mean()),
        "worst_12m": float(roll12.min()), "best_12m": float(roll12.max()), "share_positive": float((p > 0).mean()),
    }


def walk_forward(R: pd.DataFrame, cash: str, fn: Callable[..., pd.Series], cap: float, freq: int = 12, min_train: int = 60,
                 k: int = N_STARTS) -> dict:
    """Réoptimisation tous les `freq` mois après `min_train` mois d'apprentissage, 1/N calculé sur les mêmes mois de test.

    Le rendement annualisé est celui du rendement BRUT (pas de l'excédent) ; le Sharpe est celui de l'excédent sur le monétaire (définition
    usuelle). Moins de 36 mois hors échantillon : « peu fiable »."""
    scores, benchmarks = [], []
    for end in range(min_train, len(R) - (freq - 1), freq):
        train, test = R.iloc[:end], R.iloc[end:end + freq]
        w = clean_weights(fn(train, cash, cap, k=k))
        p_raw = (test * w).sum(axis=1)
        p_excess = p_raw - test[cash]
        risky = _risky(test, cash)
        wb = pd.Series(0.0, index=test.columns)
        wb[risky] = 1 / len(risky)
        pb_raw = (test * wb).sum(axis=1)
        pb_excess = pb_raw - test[cash]
        scores.append((cagr(p_raw), p_excess.mean() / max(p_excess.std(), 1e-12) * np.sqrt(FREQ)))
        benchmarks.append((cagr(pb_raw), pb_excess.mean() / max(pb_excess.std(), 1e-12) * np.sqrt(FREQ)))
    n_oos = len(scores) * freq
    base = {"reoptimisation_mois": freq, "apprentissage_min_mois": min_train, "mois_hors_echantillon": n_oos, "peu_fiable": n_oos < 36}
    if not scores:
        return {**base, "rdt": None, "sharpe": None, "rdt_1n": None, "sharpe_1n": None, "se": None, "se_1n": None, "significatif": False}
    sr_wf = float(np.mean([x[1] for x in scores]))
    sr_1n = float(np.mean([x[1] for x in benchmarks]))
    years = n_oos / 12
    se = lambda sr: float(np.sqrt((1 + 0.5 * sr ** 2) / years))
    se_wf, se_1n = se(sr_wf), se(sr_1n)
    return {**base, "rdt": float(np.mean([x[0] for x in scores])), "sharpe": sr_wf,
            "rdt_1n": float(np.mean([x[0] for x in benchmarks])), "sharpe_1n": sr_1n, "se": se_wf, "se_1n": se_1n,
            "significatif": bool(abs(sr_wf - sr_1n) >= 2 * float(np.sqrt(se_wf ** 2 + se_1n ** 2)))}
