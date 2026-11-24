"""Portefeuilles optimaux et validation walk-forward (port des sections 4 du notebook PEE).

Objectifs, chacun avec ou sans plafond par fonds (hors monétaire) :
- `max_return`  : maximise le rendement annualisé composé ;
- `max_sharpe`  : portefeuille tangent de Markowitz, 100 % investi en fonds risqués (Sharpe face au monétaire) ;
- `min_vol`     : minimise la volatilité (portefeuille de variance minimale de Markowitz) ;
- `max_sortino` : maximise le Sortino (volatilité à la baisse seulement) ;
- `risk_parity` : chaque support apporte la même part du risque ; `equal` : 1/N ;
- `mv_prudent` / `mv_balanced` / `mv_dynamic` : trois points de la frontière efficiente de Markowitz, monétaire compris -- le rendement
  espéré maximal sous une volatilité cible placée à 25 / 50 / 75 % du chemin entre le portefeuille de variance minimale et celui de
  rendement maximal. Une aversion au risque fixe (λ) donnait souvent deux profils identiques, collés au coin « rendement maximal » ; une
  volatilité cible les garde distincts quelles que soient les données. La covariance est rétrécie (Ledoit-Wolf) : sur une soixantaine de
  mois et une quinzaine de fonds, la matrice d'échantillon exagère les corrélations extrêmes et l'optimiseur s'y engouffre ;
- `max_diversification` : maximise le ratio de diversification (Choueifaty) Σ wᵢσᵢ / σ_portefeuille -- l'objectif qui exploite le plus
  directement les corrélations faibles entre supports.
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

OBJECTIVES = ("max_return", "max_sharpe", "min_vol", "max_sortino", "risk_parity", "equal",
              "mv_prudent", "mv_balanced", "mv_dynamic", "max_diversification")
DEFAULT_OBJECTIVES = ("max_return", "max_sharpe", "min_vol", "max_sortino", "risk_parity",
                      "mv_prudent", "mv_balanced", "mv_dynamic", "max_diversification")
RISK_LEVELS = {"mv_prudent": 0.25, "mv_balanced": 0.50, "mv_dynamic": 0.75}       # fraction du chemin volatilité min -> volatilité du rendement max
N_STARTS = 25
WEIGHT_TOLERANCE = 1e-8


def _multistart(fun: Callable, n: int, bounds: list[tuple[float, float]], k: int = N_STARTS, seed: int = 0, constraints: list | tuple = ()) -> np.ndarray:
    lower = np.asarray([b[0] for b in bounds], dtype=float)
    upper = np.asarray([b[1] for b in bounds], dtype=float)
    if n < 1 or upper.sum() < 1 - 1e-12:
        raise ValueError("Contraintes incompatibles : la somme des plafonds doit couvrir 100 %.")
    if lower.sum() > 1 + 1e-12:
        raise ValueError("Contraintes incompatibles : la somme des minimums dépasse 100 %.")
    rng, best = np.random.default_rng(seed), None
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}, *constraints]
    for i in range(k):
        room = upper - lower
        draw = rng.dirichlet(np.ones(n)) if i else np.full(n, 1 / n)
        x0 = lower + np.minimum(draw * (1 - lower.sum()), room)
        for _ in range(50):
            if x0.sum() >= 1 - 1e-12:
                break
            capacity = upper - x0
            if capacity.sum() <= 1e-15:
                break
            x0 = x0 + (1 - x0.sum()) * capacity / capacity.sum()
        if constraints:      # point de départ rendu admissible (contraintes de groupe) : SLSQP part mal d'un point qui les viole
            start = x0.copy()
            proj = minimize(lambda x, s0=start: float(((x - s0) ** 2).sum()), x0, bounds=bounds, method="SLSQP", constraints=cons,
                            options={"maxiter": 300, "ftol": 1e-12})
            if _feasible(proj.x, lower, upper, cons):
                x0 = proj.x
        res = minimize(fun, x0, bounds=bounds, method="SLSQP", constraints=cons, options={"maxiter": 1000, "ftol": 1e-14})
        ok = res.success or _feasible(res.x, lower, upper, cons)      # « limite d'itérations » sur un point admissible : on le garde
        if ok and np.isfinite(res.fun) and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        raise ValueError("L'optimiseur n'a trouvé aucune solution valide (contraintes trop serrées ?).")
    return best.x


def _feasible(x: np.ndarray, lower: np.ndarray, upper: np.ndarray, cons: list, tol: float = 1e-6) -> bool:
    if not np.all(np.isfinite(x)) or (x < lower - tol).any() or (x > upper + tol).any():
        return False
    for c in cons:
        v = c["fun"](x)
        if (c["type"] == "eq" and abs(v) > tol) or (c["type"] == "ineq" and v < -tol):
            return False
    return True


def _bounds(cols: list[str], cash: str, cap: float, bounds: dict | None, scale: float = 1.0) -> list[tuple[float, float]]:
    """Bornes par support : plafond général (le monétaire n'en a pas), puis bornes propres au support. `scale` : part du portefeuille
    optimisée quand une part minimale est imposée au monétaire (les bornes sont alors exprimées sur la part restante)."""
    out = []
    for c in cols:
        lo, hi = 0.0, (1.0 if c == cash else cap)
        if bounds and c in bounds:
            lo, hi = max(lo, float(bounds[c][0])), min(hi, float(bounds[c][1]))
        if scale < 1.0 and c != cash:
            lo, hi = lo / scale, min(1.0, hi / scale)
        if lo > hi + 1e-12:
            raise ValueError(f"Contraintes incompatibles pour {c} : minimum supérieur au maximum.")
        out.append((lo, hi))
    return out


def _groups(cols: list[str], groups: list | None, scale: float = 1.0, offset: dict | None = None) -> list[dict]:
    """Contraintes de groupe `(supports, minimum, maximum)` (« fonds en euros au moins 30 % », « actions au plus 60 % »)."""
    out = []
    for keys, lo, hi in groups or []:
        mask = np.array([c in keys for c in cols])
        extra = sum((offset or {}).get(k, 0.0) for k in keys)
        if not mask.any() and not extra:
            continue
        out.append({"type": "ineq", "fun": lambda w, mk=mask, lo=float(lo), e=extra: w[mk].sum() * scale + e - lo})
        out.append({"type": "ineq", "fun": lambda w, mk=mask, hi=float(hi), e=extra: hi - (w[mk].sum() * scale + e)})
    return out


def _risky_setup(R: pd.DataFrame, cash: str, cap: float, bounds: dict | None, groups: list | None):
    """Objectifs « 100 % risqués » (Sharpe, volatilité, Sortino) : une part minimale imposée au monétaire est mise de côté, le reste est optimisé."""
    risky = _risky(R, cash)
    floor = float(bounds[cash][0]) if bounds and cash in bounds else 0.0
    scale = 1.0 - floor
    if scale <= 0:
        raise ValueError("Contraintes incompatibles : le monétaire occupe tout le portefeuille.")
    bnds = _bounds(risky, cash, cap, bounds, scale)
    cons = _groups(risky, groups, scale, {cash: floor})
    return risky, floor, scale, bnds, cons


def _assemble(R: pd.DataFrame, risky: list[str], w: np.ndarray, cash: str, floor: float, scale: float) -> pd.Series:
    out = pd.Series(w * scale, index=risky).reindex(R.columns).fillna(0.0)
    out[cash] = out.get(cash, 0.0) + floor
    return out


def _risky(R: pd.DataFrame, cash: str) -> list[str]:
    return [c for c in R.columns if c != cash]


def opt_max_return(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    cols, X = list(R.columns), R.values
    w = _multistart(lambda w: -np.log1p(X @ w).mean() * FREQ, len(cols), _bounds(cols, cash, cap, bounds), k=k, constraints=_groups(cols, groups))
    return pd.Series(w, index=cols)


def opt_max_sharpe(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    risky, floor, scale, bnds, cons = _risky_setup(R, cash, cap, bounds, groups)
    ex = R[risky].sub(R[cash], axis=0)
    m_, C = ex.mean().values * FREQ, ex.cov().values * FREQ
    w = _multistart(lambda w: -(w @ m_) / np.sqrt(max(w @ C @ w, 1e-14)), len(risky), bnds, k=k, constraints=cons)
    return _assemble(R, risky, w, cash, floor, scale)


def opt_min_vol(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    risky, floor, scale, bnds, cons = _risky_setup(R, cash, cap, bounds, groups)
    C = R[risky].cov().values * FREQ
    w = _multistart(lambda w: w @ C @ w, len(risky), bnds, k=k, constraints=cons)
    return _assemble(R, risky, w, cash, floor, scale)


def opt_max_sortino(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    risky, floor, scale, bnds, cons = _risky_setup(R, cash, cap, bounds, groups)
    rf, X = R[cash].values, R[risky].values

    def objective(w):
        excess = X @ w - rf
        downside = np.minimum(excess, 0)
        return -(excess.mean() * FREQ) / max(np.sqrt(np.mean(downside ** 2) * FREQ), 1e-12)

    w = _multistart(objective, len(risky), bnds, k=k, constraints=cons)
    return _assemble(R, risky, w, cash, floor, scale)


def opt_risk_parity(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    """Parité de risque : chaque support risqué apporte la même part de la variance (contributions égales)."""
    risky, floor, scale, bnds, cons = _risky_setup(R, cash, cap, bounds, groups)
    C = R[risky].cov().values * FREQ

    def objective(w):
        var = max(w @ C @ w, 1e-14)
        rc = w * (C @ w) / var
        return float(((rc - 1 / len(w)) ** 2).sum())

    w = _multistart(objective, len(risky), bnds, k=min(k, 8), constraints=cons)
    return _assemble(R, risky, w, cash, floor, scale)


def shrunk_cov(X: pd.DataFrame) -> np.ndarray:
    """Covariance annualisée rétrécie vers une cible diagonale (Ledoit et Wolf, 2004) : moins de poids aux corrélations d'échantillon
    extrêmes, que l'optimiseur exploiterait comme des certitudes."""
    from sklearn.covariance import LedoitWolf

    values = X.to_numpy(dtype=float)
    if len(values) < 3:
        return np.cov(values, rowvar=False).reshape(values.shape[1], values.shape[1]) * FREQ
    return LedoitWolf().fit(values).covariance_ * FREQ


def _mean_variance(level: float) -> Callable[..., pd.Series]:
    def opt(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
        cols = list(R.columns)
        mu = R.mean().to_numpy() * FREQ
        C = shrunk_cov(R)
        bnds, cons = _bounds(cols, cash, cap, bounds), _groups(cols, groups)
        # Problèmes convexes (variance minimale, rendement maximal, rendement maximal sous plafond de variance) : deux départs suffisent.
        starts = min(k, 2)
        w_min = _multistart(lambda w: w @ C @ w, len(cols), bnds, k=starts, constraints=cons)
        w_max = _multistart(lambda w: -(w @ mu), len(cols), bnds, k=starts, constraints=cons)
        v_min, v_max = float(np.sqrt(max(w_min @ C @ w_min, 0))), float(np.sqrt(max(w_max @ C @ w_max, 0)))
        if v_max <= v_min + 1e-9:
            return pd.Series(w_min, index=cols)
        target = v_min + level * (v_max - v_min)
        cap_var = {"type": "ineq", "fun": lambda w, t=target: t * t - w @ C @ w}
        try:
            w = _multistart(lambda w: -(w @ mu), len(cols), bnds, k=starts, constraints=[*cons, cap_var])
        except ValueError:
            w = w_min + level * (w_max - w_min)          # repli : mélange des deux extrémités (admissible : contraintes linéaires)
        return pd.Series(w, index=cols)

    opt.__doc__ = f"Frontière efficiente de Markowitz : rendement maximal à {level:.0%} du chemin volatilité minimale -> maximale."
    return opt


def opt_max_diversification(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    """Diversification maximale (Choueifaty et Coignard, 2008) : maximise Σ wᵢσᵢ / σ_p sur les supports risqués."""
    risky, floor, scale, bnds, cons = _risky_setup(R, cash, cap, bounds, groups)
    C = shrunk_cov(R[risky])
    sig = np.sqrt(np.clip(np.diag(C), 1e-14, None))
    w = _multistart(lambda w: -(w @ sig) / np.sqrt(max(w @ C @ w, 1e-14)), len(risky), bnds, k=min(k, 8), constraints=cons)
    return _assemble(R, risky, w, cash, floor, scale)


def opt_equal(R: pd.DataFrame, cash: str, cap: float = 1.0, k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> pd.Series:
    """1/N sur les supports risqués (la référence naïve, souvent difficile à battre hors échantillon), part minimale du monétaire respectée."""
    risky = _risky(R, cash)
    floor = float(bounds[cash][0]) if bounds and cash in bounds else 0.0
    out = pd.Series(0.0, index=R.columns)
    out[risky] = (1 - floor) / len(risky)
    out[cash] = floor
    return out


OPTIMIZERS: dict[str, Callable[..., pd.Series]] = {
    "max_return": opt_max_return, "max_sharpe": opt_max_sharpe, "min_vol": opt_min_vol, "max_sortino": opt_max_sortino,
    "risk_parity": opt_risk_parity, "equal": opt_equal,
    **{name: _mean_variance(level) for name, level in RISK_LEVELS.items()},
    "max_diversification": opt_max_diversification,
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
    # Effet des corrélations : ratio de diversification (> 1 dès que les supports ne bougent pas ensemble) et nombre effectif de supports.
    sig = R[w.index].std().to_numpy()
    port_sd = float(p.std())
    div_ratio = float(w.to_numpy() @ sig / port_sd) if port_sd > 0 else float("nan")
    return {
        "div_ratio": div_ratio, "eff_n": float(1.0 / (w.to_numpy() ** 2).sum()),
        "skew": float(p.skew()), "kurt": float(p.kurt()),
        "cagr": cagr(p), "vol": float(p.std() * np.sqrt(FREQ)),
        "sharpe": float(e.mean() / max(e.std(), 1e-12) * np.sqrt(FREQ)),
        "sortino": float(e.mean() / max(np.sqrt(np.mean(downside ** 2)), 1e-12) * np.sqrt(FREQ)),
        "max_dd_daily": mdd_series(d) if len(d) else float("nan"), "max_dd_monthly": mdd_series(p),
        "worst_month": float(p.min()), "var5": float(q05), "cvar5": float(p[p <= q05].mean()),
        "worst_12m": float(roll12.min()), "best_12m": float(roll12.max()), "share_positive": float((p > 0).mean()),
    }


def walk_forward(R: pd.DataFrame, cash: str, fn: Callable[..., pd.Series], cap: float, freq: int = 12, min_train: int = 60,
                 k: int = N_STARTS, bounds: dict | None = None, groups: list | None = None) -> dict:
    """Réoptimisation tous les `freq` mois après `min_train` mois d'apprentissage, 1/N calculé sur les mêmes mois de test.

    Le rendement annualisé est celui du rendement BRUT (pas de l'excédent) ; le Sharpe est celui de l'excédent sur le monétaire (définition
    usuelle). Moins de 36 mois hors échantillon : « peu fiable »."""
    scores, benchmarks = [], []
    for end in range(min_train, len(R) - (freq - 1), freq):
        train, test = R.iloc[:end], R.iloc[end:end + freq]
        w = clean_weights(fn(train, cash, cap, k=k, bounds=bounds, groups=groups))
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
