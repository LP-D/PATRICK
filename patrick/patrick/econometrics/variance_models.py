"""Variance conditionnelle : ARCH, GARCH, GJR, EGARCH, APARCH, FIGARCH, IGARCH (RiskMetrics, lambda estimé) via `arch`, et HAR-RV (MCO, erreurs HAC).

Conventions :
- les fonctions publiques prennent des rendements DÉCIMAUX ; en interne ils sont multipliés par 100 (pourcent), échelle où l'optimiseur d'`arch`
  converge, et les paramètres sont rendus dans cette échelle (`scale = "percent"` : omega est en %², pas en décimal²) ;
- la volatilité conditionnelle est rendue en % ANNUALISÉS (`sigma_t x sqrt(periodes par an)`), comparable à une volatilité réalisée ;
- elle est FILTRÉE (sigma_t ne dépend que des rendements jusqu'à t-1) mais avec des paramètres estimés sur tout l'échantillon : c'est une
  lecture descriptive, pas une prévision (voir `forecast_eval` pour la réestimation sur le passé seulement) ;
- un ajustement qui échoue ou ne converge pas est renvoyé (`converged=False`, `error`/`message`), jamais omis.
"""
from __future__ import annotations

import itertools
import logging
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from patrick.exploration.studies import clean

log = logging.getLogger(__name__)

MODELS = ("arch", "garch", "gjr", "egarch", "aparch", "figarch", "igarch")
DISTS = ("normal", "t", "skewt", "ged")
MEANS = ("constant", "zero")
ARCH_ORDER = 5
MIN_OBS = 200
NIC_POINTS = 41
NIC_WIDTH = 4.0           # le choc va de -4 a +4 ecarts-types inconditionnels
LB_LAG = 10
ALPHA = 0.05
_E_ABS_NORMAL = float(np.sqrt(2 / np.pi))      # constante utilisee par `arch` dans l'equation de l'EGARCH


# ---------------------------------------------------------------- ajustement
def _check(model: str, dist: str, mean: str) -> None:
    if model not in MODELS:
        raise ValueError(f"modèle inconnu : {model} (attendu : {', '.join(MODELS)})")
    if dist not in DISTS:
        raise ValueError(f"loi inconnue : {dist} (attendue : {', '.join(DISTS)})")
    if mean not in MEANS:
        raise ValueError(f"moyenne inconnue : {mean}")


def _distribution(dist: str):
    from arch.univariate import GeneralizedError, Normal, SkewStudent, StudentsT

    return {"normal": Normal, "t": StudentsT, "skewt": SkewStudent, "ged": GeneralizedError}[dist]()


def build_model(y: pd.Series, model: str, dist: str, mean: str):
    """Modèle `arch` non ajusté sur `y` (en pourcent). Sert à l'ajustement et, avec `.fix(params)`, à filtrer sans réestimer."""
    from arch import arch_model
    from arch.univariate import ConstantMean, EWMAVariance, ZeroMean

    if model == "igarch":
        am = (ConstantMean if mean == "constant" else ZeroMean)(y)
        am.volatility = EWMAVariance(lam=None)               # IGARCH sans constante : sigma2_t = (1 - lam) r_{t-1}^2 + lam sigma2_{t-1}
        am.distribution = _distribution(dist)
    else:
        shape = {"arch": {"vol": "ARCH", "p": ARCH_ORDER}, "garch": {"vol": "GARCH", "p": 1, "q": 1}, "gjr": {"vol": "GARCH", "p": 1, "o": 1, "q": 1},
                 "egarch": {"vol": "EGARCH", "p": 1, "o": 1, "q": 1}, "aparch": {"vol": "APARCH", "p": 1, "o": 1, "q": 1},
                 "figarch": {"vol": "FIGARCH", "p": 1, "q": 1}}[model]
        am = arch_model(y, mean="Constant" if mean == "constant" else "Zero", dist=dist, rescale=False, **shape)
    return am


def _fit_one(y: pd.Series, model: str, dist: str, mean: str, maxiter: int | None, starting_values=None):
    """Ajuste un modèle de variance sur `y` (en pourcent). Retourne le résultat `arch`. `starting_values` : paramètres d'un ajustement voisin
    (réestimations successives d'une prévision hors échantillon : le départ à chaud réduit fortement le nombre d'itérations)."""
    options = {"maxiter": int(maxiter)} if maxiter else None
    am = build_model(y, model, dist, mean)
    if starting_values is not None:
        try:
            return am.fit(disp="off", options=options, show_warning=False, starting_values=np.asarray(starting_values, dtype=float))
        except Exception as exc:  # noqa: BLE001 -- un départ à chaud inadapté ne doit pas faire échouer l'ajustement : on repart des valeurs par défaut
            log.debug("départ à chaud refusé pour %s/%s : %s", model, dist, exc)
    return am.fit(disp="off", options=options, show_warning=False)


def _v(params: dict, key: str, default: float = 0.0) -> float:
    return float(params[key]["value"]) if key in params else default


def _persistence(model: str, params: dict, z: np.ndarray) -> float | None:
    if model == "arch":
        return sum(float(p["value"]) for k, p in params.items() if k.startswith("alpha["))
    if model == "garch":
        return _v(params, "alpha[1]") + _v(params, "beta[1]")
    if model == "gjr":
        return _v(params, "alpha[1]") + _v(params, "gamma[1]") / 2 + _v(params, "beta[1]")
    if model == "egarch":
        return _v(params, "beta[1]")
    if model == "aparch":
        delta, gamma = _v(params, "delta", 2.0), _v(params, "gamma[1]")
        moment = float(np.mean((np.abs(z) - gamma * z) ** delta)) if len(z) else 1.0
        return _v(params, "beta[1]") + _v(params, "alpha[1]") * moment
    if model == "igarch":
        return 1.0
    return None                                               # FIGARCH : mémoire longue, pas de persistance unique


def _half_life(persistence: float | None) -> float | None:
    return float(np.log(0.5) / np.log(persistence)) if persistence is not None and 0.0 < persistence < 1.0 else None


def _params(res) -> dict:
    se, pv = res.std_err, res.pvalues
    return {str(k): {"value": float(res.params[k]), "se": float(se[k]), "p": float(pv[k])} for k in res.params.index}


def _core(res, model: str, dist: str, mean: str) -> dict:
    """Résumé léger commun à la grille et au détail : critères, convergence, persistance."""
    params = _params(res)
    z = np.asarray(res.std_resid, dtype=float)
    z = z[np.isfinite(z)]
    pers = _persistence(model, params, z)
    opt = getattr(res, "optimization_result", None)
    message = str(getattr(opt, "message", "") or "").strip()
    flag = int(res.convergence_flag)
    converged = flag == 0 and bool(np.isfinite(res.loglikelihood))
    se_missing = any(not np.isfinite(p["se"]) for p in params.values())
    return {"model": model, "dist": dist, "mean": mean, "converged": converged, "convergence_flag": flag, "message": message, "error": None,
            "se_missing": se_missing, "aic": float(res.aic), "bic": float(res.bic), "loglik": float(res.loglikelihood), "k": len(params),
            "nobs": int(res.nobs), "persistence": pers, "half_life": _half_life(pers), "params": params,
            "near_integrated": bool(pers is not None and pers >= 0.9999), "scale": "percent"}


def _failed(model: str, dist: str, mean: str, exc: Exception) -> dict:
    msg = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:160]
    return {"model": model, "dist": dist, "mean": mean, "converged": False, "convergence_flag": None, "message": "", "error": msg,
            "se_missing": False, "aic": None, "bic": None, "loglik": None, "k": None, "nobs": None, "persistence": None, "half_life": None,
            "params": {}, "near_integrated": False, "scale": "percent"}


def _prepare(x: pd.Series) -> pd.Series:
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < MIN_OBS:
        raise ValueError(f"Pas assez d'observations pour un modèle de variance (minimum {MIN_OBS}, reçu {len(s)}).")
    return s * 100.0


# ---------------------------------------------------------------- diagnostics
def engle_ng(z: np.ndarray) -> dict:
    """Tests de signe d'Engle et Ng (1993) sur des résidus standardisés z : la variance de demain dépend-elle du signe (`sign_bias`) ou de la taille
    (`negative_size_bias`, `positive_size_bias`) du choc d'hier, ce que le modèle n'a pas capturé ? `joint` : test d'ensemble (LM = n R^2, chi2 à 3 ddl).
    Un rejet signifie que le modèle ignore un effet de levier ou d'asymétrie."""
    import statsmodels.api as sm

    z = np.asarray(z, dtype=float)
    z = z[np.isfinite(z)]
    y, prev = z[1:] ** 2, z[:-1]
    neg = (prev < 0).astype(float)
    cols = {"sign_bias": neg, "negative_size_bias": neg * prev, "positive_size_bias": (1.0 - neg) * prev}
    out = {}
    for name, col in cols.items():
        fit = sm.OLS(y, sm.add_constant(col)).fit()
        out[name] = {"stat": float(fit.tvalues[1]), "pvalue": float(fit.pvalues[1]), "coef": float(fit.params[1])}
    joint = sm.OLS(y, sm.add_constant(np.column_stack(list(cols.values())))).fit()
    lm = float(len(y) * joint.rsquared)
    out["joint"] = {"stat": lm, "pvalue": float(stats.chi2.sf(lm, 3)), "df": 3}
    return out


def _diagnostics(z: np.ndarray, with_bds: bool) -> dict:
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

    z = z[np.isfinite(z)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lb = acorr_ljungbox(z, lags=[LB_LAG], return_df=True)
        lb2 = acorr_ljungbox(z ** 2, lags=[LB_LAG], return_df=True)
        arch_lm = het_arch(z, nlags=5)
    jb = stats.jarque_bera(z)
    p = (np.arange(1, 42) - 0.5) / 41
    diag = {"ljung_box_p": float(lb["lb_pvalue"].iloc[0]), "ljung_box_squared_p": float(lb2["lb_pvalue"].iloc[0]), "arch_lm_p": float(arch_lm[1]),
            "jarque_bera_p": float(jb.pvalue), "skew": float(stats.skew(z)), "excess_kurtosis": float(stats.kurtosis(z)),
            "qq": {"theoretical": stats.norm.ppf(p), "sample": np.quantile(z, p)}}
    if with_bds:
        from patrick.econometrics.serial import bds_test

        try:
            b = bds_test(pd.Series(z))
            diag["bds"] = {"min_pvalue_adjusted": b["min_pvalue_adjusted"], "rejects_iid": b["rejects_iid"], "n_obs": b["n_obs"]}
        except ValueError as exc:
            diag["bds"] = {"error": str(exc)}
    return diag


def _news_impact(model: str, params: dict, y: np.ndarray) -> dict | None:
    """Courbe d'impact des nouvelles (Engle-Ng 1993) : variance de demain en fonction du choc d'aujourd'hui, la variance d'aujourd'hui étant
    sa valeur inconditionnelle. Unités : %^2 par jour."""
    pers = _persistence(model, params, np.array([]))
    omega = _v(params, "omega")
    if model == "egarch":
        s2 = float(np.exp(omega / (1 - _v(params, "beta[1]")))) if _v(params, "beta[1]") < 1 else float(np.var(y))
    elif model in ("arch", "garch", "gjr") and pers is not None and pers < 1:
        s2 = omega / (1 - pers)
    elif model == "aparch" or model == "igarch":
        s2 = float(np.var(y))
    else:
        return None
    s = np.sqrt(s2)
    eps = np.linspace(-NIC_WIDTH * s, NIC_WIDTH * s, NIC_POINTS)
    a, g, b = _v(params, "alpha[1]"), _v(params, "gamma[1]"), _v(params, "beta[1]")
    if model == "arch":
        rest = sum(float(p["value"]) for k, p in params.items() if k.startswith("alpha[") and k != "alpha[1]")
        var = omega + a * eps ** 2 + rest * s2
    elif model == "garch":
        var = omega + a * eps ** 2 + b * s2
    elif model == "gjr":
        var = omega + (a + g * (eps < 0)) * eps ** 2 + b * s2
    elif model == "egarch":
        e = eps / s
        var = np.exp(omega + a * (np.abs(e) - _E_ABS_NORMAL) + g * e + b * np.log(s2))
    elif model == "aparch":
        delta = _v(params, "delta", 2.0)
        var = (omega + a * (np.abs(eps) - g * eps) ** delta + b * s2 ** (delta / 2)) ** (2 / delta)
    else:                                                      # igarch / EWMA
        lam = _v(params, "lam")
        var = (1 - lam) * eps ** 2 + lam * s2
    return {"shock": eps, "variance": var, "reference_variance": s2, "unit": "pct2_daily"}


# ---------------------------------------------------------------- API
def fit_variance_model(x: pd.Series, model: str = "garch", dist: str = "normal", mean: str = "constant", *, periods_per_year: int = 252,
                       maxiter: int | None = None, proxy: pd.Series | None = None, with_bds: bool = False) -> dict:
    """Ajuste UN modèle de variance sur `x` (rendements décimaux) et renvoie le détail : paramètres, critères, convergence, persistance et
    demi-vie, volatilité conditionnelle filtrée (% annualisés), résidus standardisés (Ljung-Box, ARCH-LM, Jarque-Bera, Engle-Ng, QQ, BDS en option),
    courbe d'impact des nouvelles. `proxy` : variance réalisée journalière (décimale, ex. Parkinson) superposée à la volatilité conditionnelle."""
    _check(model, dist, mean)
    y = _prepare(x)
    res = _fit_one(y, model, dist, mean, maxiter)
    out = _core(res, model, dist, mean)
    z = np.asarray(res.std_resid, dtype=float)
    scale = float(np.sqrt(periods_per_year))
    cond = np.asarray(res.conditional_volatility, dtype=float) * scale
    out["diagnostics"] = _diagnostics(z, with_bds)
    out["engle_ng"] = engle_ng(z)
    out["news_impact"] = _news_impact(model, out["params"], y.to_numpy())
    s2 = None
    if out["persistence"] is not None and 0 <= out["persistence"] < 1 and model in ("arch", "garch", "gjr"):
        s2 = _v(out["params"], "omega") / (1 - out["persistence"])
    out["unconditional_vol_annual"] = float(np.sqrt(s2) * scale) if s2 and s2 > 0 else float(y.std(ddof=1) * scale)
    out["conditional_vol"] = {"dates": [d.strftime("%Y-%m-%d") for d in y.index], "values": cond, "unit": "pct_annualized"}
    out["n_obs"] = len(y)
    out["periods_per_year"] = periods_per_year
    if proxy is not None:
        rv = np.sqrt(proxy.reindex(y.index).clip(lower=0)) * 100.0 * scale
        out["realized_vol"] = {"values": rv.to_numpy(), "unit": "pct_annualized"}
        both = pd.concat([pd.Series(cond, index=y.index), rv], axis=1).dropna()
        out["corr_with_realized"] = float(both.corr().iloc[0, 1]) if len(both) > 30 else None
    return clean(out)


def fit_variance_grid(x: pd.Series, models: tuple[str, ...] = ("garch", "gjr", "egarch"), dists: tuple[str, ...] = ("normal", "t", "skewt"),
                      mean: str = "constant", *, maxiter: int | None = None) -> dict:
    """Ajuste chaque couple (modèle, loi) et les classe par BIC. Les échecs et non-convergences restent dans le tableau et sont comptés.
    BIC et AIC sont comparables entre ces lignes (mêmes données, mêmes rendements)."""
    for m, d in itertools.product(models, dists):
        _check(m, d, mean)
    y = _prepare(x)
    rows = []
    for m, d in itertools.product(models, dists):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = _fit_one(y, m, d, mean, maxiter)
                row = _core(res, m, d, mean)
                z = np.asarray(res.std_resid, dtype=float)
                diag = _diagnostics(z, with_bds=False)
                row.update({"ljung_box_squared_p": diag["ljung_box_squared_p"], "arch_lm_p": diag["arch_lm_p"],
                            "engle_ng_joint_p": engle_ng(z)["joint"]["pvalue"]})
        except Exception as exc:  # noqa: BLE001 -- un modèle qui échoue est une ligne du tableau
            row = _failed(m, d, mean, exc)
        row.pop("params", None)
        rows.append(row)
    ok = sorted((r for r in rows if r["bic"] is not None), key=lambda r: r["bic"])
    ordered = ok + [r for r in rows if r["bic"] is None]
    for i, r in enumerate(ordered, start=1):
        r["rank"] = i
    converged = [r for r in ok if r["converged"]]
    best = converged[0] if converged else (ok[0] if ok else None)
    base = next((r for r in ordered if (r["model"], r["dist"]) == ("garch", "normal") and r["bic"] is not None), None)
    return clean({"rows": ordered, "n_specs": len(rows), "n_failed": sum(1 for r in rows if r["error"]),
                  "n_not_converged": sum(1 for r in rows if not r["error"] and not r["converged"]), "best": best,
                  "delta_bic_vs_garch_normal": (best["bic"] - base["bic"]) if best and base else None, "n_obs": len(y)})


# ---------------------------------------------------------------- HAR-RV
def _har_design(rv: pd.Series, windows: tuple[int, int, int] = (1, 5, 22), log: bool = False) -> tuple[pd.DataFrame, pd.Series]:
    """Régresseurs de Corsi (2009) : variance de la veille, moyenne des 5 jours précédant la date, moyenne des 22 jours précédant la date.
    Tous sont décalés d'un jour : la variance de la date t ne figure jamais parmi ses propres régresseurs."""
    s = pd.Series(rv).astype(float)
    s = np.log(s.clip(lower=1e-12)) if log else s
    lag = s.shift(1)
    d, w, m = windows
    X = pd.DataFrame({"daily": lag.rolling(d).mean(), "weekly": lag.rolling(w).mean(), "monthly": lag.rolling(m).mean()})
    both = pd.concat([X, s.rename("y")], axis=1).dropna()
    return both[["daily", "weekly", "monthly"]], both["y"]


def fit_har(rv: pd.Series, *, log: bool = False, hac_lags: int = 5) -> dict:
    """HAR-RV : RV_t = c + b_d RV_{t-1} + b_w mean(RV_{t-5..t-1}) + b_m mean(RV_{t-22..t-1}) + e_t, estimé par MCO avec erreurs de Newey-West.
    `rv` = variance réalisée journalière (Parkinson, Garman-Klass) ou, à défaut, rendement au carré (bien plus bruité). `log=True` : HAR sur le log."""
    import statsmodels.api as sm

    clean_rv = pd.Series(rv).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean_rv) < 120:
        raise ValueError("Pas assez d'observations pour un HAR-RV (minimum 120).")
    X, y = _har_design(clean_rv, log=log)
    fit = sm.OLS(y, sm.add_constant(X)).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
    names = {"const": "const", "daily": "daily", "weekly": "weekly", "monthly": "monthly"}
    params = {names[k]: {"value": float(fit.params[k]), "se": float(fit.bse[k]), "t": float(fit.tvalues[k]), "p": float(fit.pvalues[k])} for k in fit.params.index}
    fitted = pd.Series(fit.fittedvalues, index=y.index)
    return clean({"params": params, "r2": float(fit.rsquared), "n_obs": int(fit.nobs), "log": log, "hac_lags": hac_lags,
                  "persistence": float(fit.params[["daily", "weekly", "monthly"]].sum()),
                  "fitted": {"dates": [d.strftime("%Y-%m-%d") for d in y.index], "values": fitted.to_numpy(), "actual": y.to_numpy()}})
