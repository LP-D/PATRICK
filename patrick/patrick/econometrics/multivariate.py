"""Multivarié : VAR (ordre par critère d'information, stabilité, réponses impulsionnelles orthogonalisées, décomposition de la variance de l'erreur
de prévision), cointégration de Johansen et VECM (statsmodels).

- VAR sur des RENDEMENTS (stationnaires) ; Johansen et VECM sur des NIVEAUX (log des prix) : la cointégration est une relation entre niveaux non stationnaires.
- Les réponses impulsionnelles orthogonalisées dépendent de l'ORDRE des variables (décomposition de Cholesky : la première ne réagit pas à l'instant 0 aux chocs
  des suivantes). Elles sont rendues avec cet ordre et doivent être lues avec lui.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from patrick.exploration.studies import clean

MIN_OBS = 60
IRF_REPLICATIONS = 200
IRF_SIGNIF = 0.10          # bandes à 90 %
MAX_VARS = 12              # limite de statsmodels pour Johansen


def _frame(df: pd.DataFrame, minimum_vars: int = 2) -> pd.DataFrame:
    d = pd.DataFrame(df).replace([np.inf, -np.inf], np.nan).dropna()
    if d.shape[1] < minimum_vars:
        raise ValueError(f"Il faut au moins {minimum_vars} séries (reçu {d.shape[1]}).")
    if d.shape[1] > MAX_VARS:
        raise ValueError(f"Au plus {MAX_VARS} séries pour une analyse multivariée (reçu {d.shape[1]}).")
    if len(d) < MIN_OBS:
        raise ValueError(f"Pas assez d'observations pour une analyse multivariée (minimum {MIN_OBS}, reçu {len(d)}).")
    return d


def _irf_bands(res, data: np.ndarray, order: int, periods: int, repl: int, signif: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Bandes de Monte-Carlo des réponses impulsionnelles orthogonalisées : on simule `repl` séries du VAR estimé (chocs gaussiens de covariance sigma_u, graine
    fixée), on réestime le VAR sur chacune, on prend les quantiles des réponses. (`statsmodels.irf_resim` repasse la MÊME graine à chaque réplication : avec une graine
    fixée les réplications sont identiques et la bande se réduit à un point ; on écrit donc la boucle.)"""
    from statsmodels.tsa.api import VAR

    coefs, intercept = np.asarray(res.coefs), np.asarray(res.intercept)
    chol = np.linalg.cholesky(np.asarray(res.sigma_u))
    k, n, burn = coefs.shape[1], len(data), 100
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(repl):
        shocks = rng.standard_normal((n + burn, k)) @ chol.T
        y = np.zeros((n + burn + order, k))
        for t in range(order, n + burn + order):
            y[t] = intercept + shocks[t - order] + sum(coefs[lag] @ y[t - 1 - lag] for lag in range(order))
        try:
            draws.append(np.asarray(VAR(y[-n:]).fit(order).irf(periods).orth_irfs))
        except (np.linalg.LinAlgError, ValueError):
            continue
    if len(draws) < repl // 2:
        raise ValueError("Bandes des réponses impulsionnelles impossibles à calculer (trop de réplications ont échoué).")
    lower, upper = np.percentile(np.array(draws), [100 * signif / 2, 100 * (1 - signif / 2)], axis=0)
    return lower, upper


def var_analysis(returns: pd.DataFrame, maxlag: int = 5, irf_periods: int = 10, ic: str = "bic", seed: int = 0) -> dict:
    """VAR(p) sur `returns`, p choisi par `ic` (bic, aic, hqic) entre 1 et `maxlag`. Renvoie les coefficients (coefficients[k][i][j] : effet de la variable j au retard k+1
    sur l'équation de i), la stabilité (module maximal des valeurs propres de la matrice compagnon < 1), les réponses impulsionnelles orthogonalisées avec bandes à 90 %
    (irf[h][i][j] : réponse de i, h périodes après un choc d'un écart-type sur j), et la décomposition de la variance (fevd[h][i][j])."""
    from statsmodels.tsa.api import VAR

    d = _frame(returns)
    names = [str(c) for c in d.columns]
    model = VAR(d.to_numpy(dtype=float))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sel = model.select_order(maxlags=min(maxlag, max(1, (len(d) - 1) // (d.shape[1] + 1) - 1)))
        order = max(1, int(sel.selected_orders[ic]))
        res = model.fit(order)
        irf_obj = res.irf(irf_periods)
        irf = np.asarray(irf_obj.orth_irfs)
        lower, upper = _irf_bands(res, d.to_numpy(dtype=float), order, irf_periods, IRF_REPLICATIONS, IRF_SIGNIF, seed)
        fevd = np.asarray(res.fevd(irf_periods + 1).decomp).transpose(1, 0, 2)          # (neqs, periods, neqs) -> (periods, neqs, neqs)
    k = d.shape[1]
    companion = np.zeros((k * order, k * order))
    companion[:k, :] = np.hstack(list(res.coefs))
    if order > 1:
        companion[k:, :-k] = np.eye(k * (order - 1))
    modulus = float(np.abs(np.linalg.eigvals(companion)).max())
    endog = d.to_numpy(dtype=float)[order:]
    resid = np.asarray(res.resid)
    r2 = 1.0 - (resid ** 2).sum(axis=0) / ((endog - endog.mean(axis=0)) ** 2).sum(axis=0)
    return clean({"names": names, "order": order, "ic": ic, "maxlag": maxlag, "n_obs": int(res.nobs),
                  "ic_table": {name: [float(v) for v in np.asarray(vals)] for name, vals in sel.ics.items()},
                  "coefficients": np.asarray(res.coefs), "intercept": np.asarray(res.intercept), "stable": bool(res.is_stable()), "max_root_modulus": modulus,
                  "r2": dict(zip(names, r2, strict=True)), "irf": irf, "irf_lower": np.asarray(lower), "irf_upper": np.asarray(upper), "irf_signif": IRF_SIGNIF,
                  "irf_order": names, "irf_periods": irf_periods, "fevd": fevd, "fevd_horizons": list(range(1, irf_periods + 2)),
                  "sigma": np.asarray(res.sigma_u)})


def johansen(levels: pd.DataFrame, det_order: int = 0, k_ar_diff: int = 1) -> dict:
    """Test de cointégration de Johansen (1991) sur des niveaux. `det_order` : -1 aucun terme déterministe, 0 constante, 1 tendance linéaire ; `k_ar_diff` : retards des
    différences du VECM. Rang r retenu par le test de la trace, de l'hypothèse « rang 0 » vers le haut, au seuil de 5 % : le premier rang non rejeté. Les vecteurs de
    cointégration sont normalisés sur la première variable."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    d = _frame(levels)
    if det_order not in (-1, 0, 1):
        raise ValueError("det_order : -1, 0 ou 1 attendu.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        j = coint_johansen(d.to_numpy(dtype=float), det_order, k_ar_diff)
    n = d.shape[1]
    rows = [{"null_rank": r, "eigenvalue": float(j.eig[r]), "trace": float(j.lr1[r]), "trace_crit_90": float(j.cvt[r, 0]), "trace_crit_95": float(j.cvt[r, 1]),
             "trace_crit_99": float(j.cvt[r, 2]), "max_eig": float(j.lr2[r]), "maxeig_crit_90": float(j.cvm[r, 0]), "maxeig_crit_95": float(j.cvm[r, 1]),
             "maxeig_crit_99": float(j.cvm[r, 2])} for r in range(n)]
    rank = n
    for r in range(n):
        if rows[r]["trace"] < rows[r]["trace_crit_95"]:
            rank = r
            break
    evec = np.asarray(j.evec, dtype=float)
    vectors = [[float(v) for v in evec[:, r] / evec[0, r]] for r in range(max(rank, 1))]
    return clean({"names": [str(c) for c in d.columns], "n_obs": len(d), "det_order": det_order, "k_ar_diff": k_ar_diff, "rows": rows, "rank": rank, "vectors": vectors})


def vecm(levels: pd.DataFrame, rank: int = 1, k_ar_diff: int = 1) -> dict:
    """VECM de rang `rank` : Δy_t = α β' y_{t-1} + Γ Δy_{t-1} + ... + const. β = relations de long terme (normalisées), α = vitesses d'ajustement. Pour un rang 1,
    `speed` = β'α est le coefficient de retour de l'écart ECT_t = β'y_t vers sa moyenne (entre -1 et 0 : l'écart se résorbe) ; demi-vie = ln 0,5 / ln(1 + speed)."""
    from statsmodels.tsa.vector_ar.vecm import VECM

    d = _frame(levels)
    n = d.shape[1]
    if not 1 <= rank < n:
        raise ValueError(f"Le rang de cointégration doit être entre 1 et {n - 1} (reçu {rank}).")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = VECM(d.to_numpy(dtype=float), k_ar_diff=k_ar_diff, coint_rank=rank, deterministic="co").fit()
    alpha, beta = np.asarray(res.alpha, dtype=float), np.asarray(res.beta, dtype=float)
    ect = d.to_numpy(dtype=float) @ beta[:, 0]
    ect = ect - ect.mean()
    speed = half_life = None
    if rank == 1:
        speed = float(beta[:, 0] @ alpha[:, 0])
        half_life = float(np.log(0.5) / np.log(1.0 + speed)) if -1.0 < speed < 0.0 else None
    pv = np.asarray(res.pvalues_alpha, dtype=float)
    return clean({"names": [str(c) for c in d.columns], "n_obs": len(d), "rank": rank, "k_ar_diff": k_ar_diff, "alpha": alpha, "alpha_p": pv, "beta": beta,
                  "speed": speed, "half_life": half_life, "ect": {"dates": [t.strftime("%Y-%m-%d") for t in d.index], "values": ect}})
