"""Moyenne conditionnelle : grille ARMA/ARIMA (SARIMA, ARIMAX en option), diagnostics des résidus, ordre d'intégration fractionnaire d (GPH).

Sur des rendements journaliers, la moyenne est presque toujours imprévisible : le résultat honnête est alors « aucun modèle ne bat la constante ».
La grille affiche donc toujours le modèle constant comme référence, compte les spécifications essayées et corrige les tests de rapport de
vraisemblance par Benjamini-Hochberg (`validation.fdr`). Un ajustement qui échoue ou ne converge pas est une ligne du tableau, jamais un trou."""
from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from patrick.exploration.studies import clean
from patrick.validation.fdr import benjamini_hochberg

MIN_OBS = 40
BIC_MARGIN = 2.0              # écart de BIC en dessous duquel on ne parle pas de « mieux » (Raftery : 2 = évidence faible)
ALPHA = 0.05
QQ_POINTS = 41


def _fit_arima(y: np.ndarray, order: tuple, seasonal_order: tuple | None, exog: np.ndarray | None, trend: str):
    from statsmodels.tsa.arima.model import ARIMA

    return ARIMA(y, order=order, seasonal_order=seasonal_order or (0, 0, 0, 0), exog=exog, trend=trend).fit()


def _qq(z: np.ndarray) -> dict:
    p = (np.arange(1, QQ_POINTS + 1) - 0.5) / QQ_POINTS
    return {"theoretical": stats.norm.ppf(p), "sample": np.quantile(z, p)}


def _diagnostics(resid: np.ndarray, n_params_arma: int) -> dict:
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

    z = resid[np.isfinite(resid)]
    sd = float(z.std(ddof=1)) or 1.0
    z = z / sd
    lag = int(min(10, max(n_params_arma + 1, len(z) // 5)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lb = acorr_ljungbox(z, lags=[lag], model_df=min(n_params_arma, lag - 1), return_df=True)
        lb_sq = acorr_ljungbox(z ** 2, lags=[lag], return_df=True)
        arch = het_arch(z, nlags=min(5, max(1, len(z) // 10)))
    jb = stats.jarque_bera(z)
    return {"ljung_box_p": float(lb["lb_pvalue"].iloc[0]), "ljung_box_squared_p": float(lb_sq["lb_pvalue"].iloc[0]),
            "arch_lm_p": float(arch[1]), "jarque_bera_p": float(jb.pvalue), "skew": float(stats.skew(z)),
            "excess_kurtosis": float(stats.kurtosis(z)), "ljung_box_lag": lag, "qq": _qq(z)}


def _params(res) -> dict:
    names = list(res.param_names) if hasattr(res, "param_names") else [f"p{i}" for i in range(len(res.params))]
    vals, bse, pv = np.asarray(res.params), np.asarray(res.bse), np.asarray(res.pvalues)
    return {n: {"value": float(v), "se": float(s), "p": float(p)} for n, v, s, p in zip(names, vals, bse, pv, strict=True)}


def _row(order: tuple, seasonal: tuple | None, y: np.ndarray, exog: np.ndarray | None, exog_names: list[str], trend: str, is_constant: bool) -> dict:
    row = {"order": list(order), "is_constant": is_constant, "converged": False, "error": None, "warnings": []}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            res = _fit_arima(y, order, seasonal, exog, trend)
        row["warnings"] = sorted({str(w.message).splitlines()[0][:140] for w in caught if "ConvergenceWarning" in w.category.__name__
                                  or "non-stationary" in str(w.message) or "non-invertible" in str(w.message)})
        retvals = getattr(res, "mle_retvals", None) or {}
        row["converged"] = bool(retvals.get("converged", True)) and bool(np.isfinite(res.llf))
        params = _params(res)
        # noms plus lisibles pour les régresseurs (statsmodels les appelle x1, x2...)
        for i, name in enumerate(exog_names, start=1):
            if f"x{i}" in params:
                params[name] = params.pop(f"x{i}")
        k_arma = order[0] + order[2] + (seasonal[0] + seasonal[2] if seasonal else 0)
        row.update({"aic": float(res.aic), "bic": float(res.bic), "llf": float(res.llf), "k": len(res.params), "params": params,
                    "diagnostics": _diagnostics(np.asarray(res.resid, dtype=float), k_arma)})
    except Exception as exc:  # noqa: BLE001 -- un ajustement qui échoue (matrice singulière, racines non inversibles...) est affiché
        row["error"] = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:160]
        row.update({"aic": None, "bic": None, "llf": None, "k": None, "params": {}, "diagnostics": None})
    return row


def fit_arma_grid(x: pd.Series, max_p: int = 2, max_q: int = 2, d: int = 0, *, seasonal_order: tuple | None = None,
                  exog: pd.DataFrame | None = None) -> dict:
    """Ajuste ARIMA(p,d,q) pour tout (p,q) de la grille (p = 0..max_p, q = 0..max_q), triés par BIC. (0,d,0) est le modèle constant (ou
    la simple différence) : la référence. `seasonal_order` = (P,D,Q,m) s'applique à tous les ajustements ; `exog` = régresseurs (ARIMAX)."""
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < MIN_OBS:
        raise ValueError(f"Pas assez d'observations pour ajuster un ARMA (minimum {MIN_OBS}, reçu {len(s)}).")
    y = s.to_numpy(dtype=float)
    exog_names: list[str] = []
    ex = None
    if exog is not None:
        e = exog.reindex(s.index)
        keep = e.notna().all(axis=1).to_numpy()
        if not keep.all():
            y, e = y[keep], e.loc[keep]
        exog_names, ex = [str(c) for c in e.columns], e.to_numpy(dtype=float)
    trend = "c" if d == 0 else "n"
    rows = [_row((p, d, q), seasonal_order, y, ex, exog_names, trend, is_constant=(p == 0 and q == 0))
            for p, q in itertools.product(range(max_p + 1), range(max_q + 1))]

    const = next(r for r in rows if r["is_constant"])
    lr_p: dict[str, float] = {}
    for r in rows:
        r["lr_p"] = r["lr_p_adj"] = None
        if r["is_constant"] or r["llf"] is None or const["llf"] is None:
            continue
        stat = max(0.0, 2.0 * (r["llf"] - const["llf"]))
        df = max(1, r["k"] - const["k"])
        r["lr_p"] = float(stats.chi2.sf(stat, df))
        lr_p[str(tuple(r["order"]))] = r["lr_p"]
    fdr = benjamini_hochberg(lr_p, alpha=ALPHA) if lr_p else {"n_tested": 0, "n_raw_significant": 0, "n_bh_significant": 0, "results": {}}
    for r in rows:
        hit = fdr["results"].get(str(tuple(r["order"])))
        if hit:
            r["lr_p_adj"] = float(hit["adjusted_p_value"])

    ok = sorted((r for r in rows if r["bic"] is not None), key=lambda r: r["bic"])
    failed = [r for r in rows if r["bic"] is None]
    ordered = ok + failed
    for i, r in enumerate(ordered, start=1):
        r["rank"] = i
    best = ok[0] if ok else None
    delta = (best["bic"] - const["bic"]) if best and const["bic"] is not None else None
    verdict = ("better_than_constant" if delta is not None and delta <= -BIC_MARGIN and not best["is_constant"] else "no_better_than_constant")
    return clean({"n_obs": len(y), "d": d, "seasonal": list(seasonal_order) if seasonal_order else None, "regressors": exog_names,
                  "rows": ordered, "n_specs": len(rows), "n_failed": sum(1 for r in rows if r["error"]),
                  "n_not_converged": sum(1 for r in rows if not r["error"] and not r["converged"]),
                  "best": best, "constant": const, "delta_bic": delta, "verdict": verdict, "fdr": {k: v for k, v in fdr.items() if k != "results"},
                  "bic_margin": BIC_MARGIN})


def gph_d(x: pd.Series, bandwidth: float = 0.5) -> dict:
    """Estimateur de Geweke et Porter-Hudak (1983) de l'ordre d'intégration fractionnaire d : régression du log-périodogramme sur
    ln(4 sin^2(lambda/2)) aux m = n^bandwidth premières fréquences. d = 0 : mémoire courte ; 0 < d < 0,5 : mémoire longue stationnaire ;
    d proche de 1 : racine unitaire. C'est une approximation d'ARFIMA, pas son estimation exacte."""
    v = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    n = len(v)
    if n < 100:
        raise ValueError("Pas assez d'observations pour l'estimateur GPH (minimum 100).")
    v = v - v.mean()
    m = max(4, int(n ** bandwidth))
    freqs = 2 * np.pi * np.arange(1, m + 1) / n
    periodogram = np.abs(np.fft.fft(v)[1:m + 1]) ** 2 / (2 * np.pi * n)
    g = np.log(4 * np.sin(freqs / 2) ** 2)
    yv = np.log(periodogram)
    gc = g - g.mean()
    slope = float((gc * (yv - yv.mean())).sum() / (gc ** 2).sum())
    se = float(np.sqrt((np.pi ** 2 / 6) / (gc ** 2).sum()))
    d = -slope
    return clean({"d": d, "se": se, "m": m, "z": d / se, "p": float(2 * stats.norm.sf(abs(d / se))), "n_obs": n})
