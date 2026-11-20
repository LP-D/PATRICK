"""Scénarios à N ans d'un fonds ou d'un portefeuille (port de la section 3 du notebook PEE).

Cinq méthodes, une seule fonction chacune (même graine par défaut partout) :
- `bootstrap blocs 6 mois` : tirage de blocs de 6 mois consécutifs dans l'historique (garde l'autocorrélation) ;
- `bootstrap i.i.d.`       : tirage de mois indépendants ;
- `bootstrap stationnaire` : blocs de longueur aléatoire (moyenne 6 mois) ;
- `GARCH résidus`          : GARCH(1,1) ajusté sur l'historique, chocs tirés dans les résidus standardisés ;
- `Monte Carlo μ incertain`: rendements normaux dont la moyenne est elle-même incertaine (erreur-type sigma / racine de T).

Deux centrages : « historique » (la distribution telle quelle, qui hérite d'un marché haussier) et « prudent » (recentrée sur un rendement espéré
rétréci `E = 0,3 x CAGR historique + 0,7 x (taux sans risque + 0,3 x volatilité)`, pour ne pas supposer que le passé récent se répète).
Les fenêtres historiques glissantes sont très chevauchantes : ce qui compte est le nombre d'années INDÉPENDANTES (`blocs indép.`), pas de fenêtres.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from patrick.placements.stats import FREQ

N_SIMS = 20000
SHRINK_A = 0.3              # poids du CAGR historique dans le rendement espéré rétréci
SHRINK_S0 = 0.3             # prime de risque supposée (Sharpe a priori) du prior « taux sans risque + s0 x volatilité »
QUANTILES = (5, 25, 50, 75, 95)


def rf_trailing(R: pd.DataFrame, cash: str) -> float:
    """Taux sans risque : rendement composé du monétaire sur les 12 derniers mois."""
    return float((1 + R[cash].iloc[-12:]).prod() - 1)


def expected_returns(R: pd.DataFrame | pd.Series, rf: float, s0: float = SHRINK_S0, a: float = SHRINK_A):
    """Rendement espéré rétréci `a x CAGR + (1 - a) x (rf + s0 x vol)` (une valeur par colonne, ou un nombre pour une série)."""
    vol = R.std() * np.sqrt(FREQ)
    sample = (1 + R).prod() ** (FREQ / len(R)) - 1
    return a * sample + (1 - a) * (rf + s0 * vol)


def e_target(p: pd.Series, rf: float) -> float:
    return float(expected_returns(p, rf))


def hist_windows(p: pd.Series, cash: pd.Series, months: int) -> dict:
    """Fenêtres glissantes de `months` mois dans l'historique : pire, moyenne, meilleure (annualisées), part de fenêtres perdantes."""
    if months < 1 or len(p) < months:
        raise ValueError("L'historique doit contenir au moins `months` observations.")
    cum = (1 + p).rolling(months).apply(np.prod, raw=True).dropna() - 1
    cc = (1 + cash).rolling(months).apply(np.prod, raw=True).dropna() - 1
    ann = (1 + cum) ** (12 / months) - 1
    return {"fenetres": len(cum), "blocs_indep": round((len(cum) + months) / months, 1), "pire": float(ann.min()), "moyen": float(ann.mean()),
            "median": float(ann.median()), "meilleur": float(ann.max()), "part_negative": float((cum < 0).mean()),
            "part_sous_monetaire": float((cum < cc.reindex(cum.index)).mean())}


def _recentre(x: np.ndarray, target_cagr: float | None) -> np.ndarray:
    """Décale les rendements mensuels pour que leur rendement géométrique annualisé vaille `target_cagr` (sans changer la dispersion)."""
    if target_cagr is None:
        return x
    return x + (((1 + target_cagr) ** (1 / 12) - 1) - np.expm1(np.log1p(x).mean()))


def _annualised(out: np.ndarray, months: int) -> np.ndarray:
    cum = np.prod(1 + out, axis=1) - 1
    return (1 + cum) ** (12 / months) - 1


def block_bootstrap_paths(p: pd.Series, months: int, block: int = 6, n: int = N_SIMS, seed: int = 1, target_cagr: float | None = None) -> np.ndarray:
    """Matrice `(n, months)` de rendements mensuels simulés, par blocs de `block` mois consécutifs (circulaire)."""
    if len(p) == 0 or months < 1 or block < 1 or n < 1:
        raise ValueError("Paramètres de bootstrap invalides.")
    rng, x = np.random.default_rng(seed), _recentre(p.to_numpy(dtype=float).copy(), target_cagr)
    nb = int(np.ceil(months / block))
    idx = ((rng.integers(0, len(x), (n, nb))[:, :, None] + np.arange(block)) % len(x)).reshape(n, -1)[:, :months]
    return x[idx]


def method_boot_blocks(p, months, n=N_SIMS, seed=1, target_cagr=None):
    return _annualised(block_bootstrap_paths(p, months, 6, n, seed, target_cagr), months)


def method_boot_iid(p, months, n=N_SIMS, seed=2, target_cagr=None):
    return _annualised(block_bootstrap_paths(p, months, 1, n, seed, target_cagr), months)


def method_boot_stationary(p, months, n=N_SIMS, seed=11, target_cagr=None):
    """Bootstrap stationnaire (Politis-Romano) : à chaque mois, avec probabilité 1/6 on repart d'une date tirée au hasard, sinon on enchaîne."""
    if len(p) == 0 or months < 1 or n < 1:
        raise ValueError("Paramètres de bootstrap stationnaire invalides.")
    rng, x = np.random.default_rng(seed), _recentre(p.to_numpy(dtype=float), target_cagr)
    size = len(x)
    pos = rng.integers(size, size=n)
    restart = rng.random((n, months)) < 1 / 6
    fresh = rng.integers(size, size=(n, months))
    out = np.empty((n, months))
    out[:, 0] = x[pos]
    for j in range(1, months):
        pos = np.where(restart[:, j], fresh[:, j], (pos + 1) % size)
        out[:, j] = x[pos]
    return _annualised(out, months)


def garch_fit(x: np.ndarray) -> tuple:
    """GARCH(1,1) à moyenne constante par maximum de vraisemblance gaussienne : `(mu, omega, alpha, beta, résidus standardisés, variance finale)`."""
    mu, var = float(np.mean(x)), float(np.var(x, ddof=1))

    def objective(theta):
        omega, alpha, beta = np.exp(theta[0]), 1 / (1 + np.exp(-theta[1])), 1 / (1 + np.exp(-theta[2]))
        if alpha + beta >= 0.999:
            return 1e9 + (alpha + beta) * 1e6
        h = np.full(len(x), var)
        eps = x - mu
        for t in range(1, len(x)):
            h[t] = omega + alpha * eps[t - 1] ** 2 + beta * h[t - 1]
        return float(np.sum(np.log(h) + eps ** 2 / h))

    fit = minimize(objective, np.log([max(var * .05, 1e-8), 0.1, 0.8]), method="Nelder-Mead")
    omega, alpha, beta = np.exp(fit.x[0]), 1 / (1 + np.exp(-fit.x[1])), 1 / (1 + np.exp(-fit.x[2]))
    eps = x - mu
    h = np.full(len(x), var)
    for t in range(1, len(x)):
        h[t] = omega + alpha * eps[t - 1] ** 2 + beta * h[t - 1]
    return mu, omega, alpha, beta, eps / np.sqrt(h), h[-1]


def garch_diagnostic(fit: tuple) -> dict:
    """Le GARCH est jugé fiable si la volatilité a une vraie mémoire (beta >= 0,05), est stationnaire et peu persistante (alpha + beta <= 0,95)
    et si les résidus standardisés sont centrés-réduits (|moyenne| < 0,10, écart-type dans 0,85-1,15)."""
    _mu, _omega, alpha, beta, z, _h0 = fit
    persistence = alpha + beta
    z_mean, z_std = float(np.mean(z)), float(np.std(z, ddof=1))
    residuals_ok = abs(z_mean) < 0.10 and 0.85 < z_std < 1.15
    reasons = [m for m, bad in [("beta proche de 0", beta < 0.05), ("alpha+beta > 0,95", persistence > 0.95),
                                ("non stationnaire", persistence >= 1), ("résidus mal standardisés", not residuals_ok)] if bad]
    return {"alpha": float(alpha), "beta": float(beta), "persistance": float(persistence), "fiable": bool(not reasons),
            "motif": "; ".join(reasons) or "aucun"}


def method_garch(p, months, n=N_SIMS, seed=21, target_cagr=None, fit: tuple | None = None):
    mu, omega, alpha, beta, z, h0 = fit if fit is not None else garch_fit(p.to_numpy(dtype=float))
    if target_cagr is not None:
        mu = (1 + target_cagr) ** (1 / 12) - 1
    rng = np.random.default_rng(seed)
    out = np.empty((n, months))
    h = np.full(n, h0)
    for t in range(months):
        out[:, t] = mu + np.sqrt(h) * rng.choice(z, size=n)
        h = omega + alpha * (out[:, t] - mu) ** 2 + beta * h
    return _annualised(out, months)


def method_monte_carlo(p, months, n=N_SIMS, seed=31, target_cagr=None):
    rng, x = np.random.default_rng(seed), p.to_numpy(dtype=float)
    mu_hat = float(np.mean(x)) if target_cagr is None else (1 + target_cagr) ** (1 / 12) - 1
    sigma = float(np.std(x, ddof=1))
    mu = rng.normal(mu_hat, sigma / np.sqrt(len(x)), n)
    return _annualised(rng.normal(mu[:, None], sigma, (n, months)), months)


METHODS: dict[str, Callable] = {
    "bootstrap blocs 6 mois": method_boot_blocks,
    "bootstrap i.i.d.": method_boot_iid,
    "bootstrap stationnaire": method_boot_stationary,
    "GARCH résidus": method_garch,
    "Monte Carlo μ incertain": method_monte_carlo,
}


def summary(ann: np.ndarray, months: int) -> dict:
    """Quantiles (P5, P25, P50, P75, P95) du rendement annualisé et cumulé, et probabilité de perte à l'horizon."""
    ann = np.asarray(ann, dtype=float)
    cum = (1 + ann) ** (months / 12) - 1
    return {**{f"ann_p{q:02d}": float(np.percentile(ann, q)) for q in QUANTILES},
            **{f"cum_p{q:02d}": float(np.percentile(cum, q)) for q in QUANTILES},
            "proba_perte": float(np.mean(cum < 0)), "moyenne_ann": float(ann.mean())}


def fan(p: pd.Series, years: int, target_cagr: float | None, n: int = N_SIMS, seed: int = 1) -> dict:
    """Éventail de valeur cumulée année par année (bootstrap par blocs) : quantiles du rendement cumulé en fin de chaque année 1..`years`."""
    paths = block_bootstrap_paths(p, years * 12, 6, n, seed, target_cagr)
    growth = np.cumprod(1 + paths, axis=1) - 1
    marks = [12 * y - 1 for y in range(1, years + 1)]
    return {"annees": list(range(1, years + 1)),
            **{f"p{q:02d}": [float(np.percentile(growth[:, m], q)) for m in marks] for q in QUANTILES}}


def run_methods(p: pd.Series, months: int, target: float, methods: list[str], n: int = N_SIMS) -> tuple[dict, dict | None]:
    """Toutes les méthodes demandées, en centrage historique et prudent : `({méthode: {centrage: résumé}}, diagnostic GARCH ou None)`.

    Quand le GARCH n'est pas fiable (voir `garch_diagnostic`), ses résumés sont `None` : on préfère ne rien afficher qu'un chiffre trompeur."""
    out: dict[str, dict] = {}
    garch_info = None
    fit = None
    for name in methods:
        func = METHODS[name]
        if func is method_garch:
            fit = garch_fit(p.to_numpy(dtype=float))
            garch_info = garch_diagnostic(fit)
            if not garch_info["fiable"]:
                out[name] = {"historique": None, "prudent": None}
                continue
            out[name] = {"historique": summary(func(p, months, n=n, target_cagr=None, fit=fit), months),
                         "prudent": summary(func(p, months, n=n, target_cagr=target, fit=fit), months)}
        else:
            out[name] = {"historique": summary(func(p, months, n=n, target_cagr=None), months),
                         "prudent": summary(func(p, months, n=n, target_cagr=target), months)}
    return out, garch_info
