"""Prévision de variance HORS ÉCHANTILLON et comparaison des modèles.

Une prévision à la date j n'utilise que des rendements datés de j-1 et avant, et des paramètres estimés AVANT le bloc qui contient j (fenêtre
expansive, ou glissante de `window` observations, réestimée tous les `refit_every` jours). Entre deux réestimations les paramètres sont figés
(`arch.fix`) et seul le filtre de variance avance. C'est la différence avec la volatilité conditionnelle de `variance_models`, estimée sur tout l'échantillon.

Pertes robustes à un proxy de variance bruité (Patton 2011) : QLIKE et erreur quadratique. Le proxy est r^2 (sans biais, très bruité) ou, si les prix OHLC
existent, la variance de Parkinson ou de Garman-Klass.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import xlogy

from patrick.econometrics import variance_models as V
from patrick.exploration.studies import clean
from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.fdr import benjamini_hochberg

MIN_TRAIN = 750
REFIT_EVERY = 60
LEVELS = (0.01, 0.05)
LAMBDA = 0.94                 # RiskMetrics (J.P. Morgan, 1996) pour des données journalières
ROLLING_WINDOW = 60
TINY = 1e-12


# ---------------------------------------------------------------- pertes
def qlike(proxy, forecast):
    """QLIKE = proxy/h - ln(proxy/h) - 1 (>= 0, nul seulement si h = proxy). Perte robuste : classe correctement les prévisions même avec un proxy bruité."""
    p = np.maximum(np.asarray(proxy, dtype=float), TINY)
    h = np.maximum(np.asarray(forecast, dtype=float), TINY)
    return p / h - np.log(p / h) - 1.0


def mse_var(proxy, forecast):
    """Erreur quadratique sur la variance : (proxy - h)^2. Robuste aussi, mais dominée par les journées extrêmes."""
    return (np.asarray(proxy, dtype=float) - np.asarray(forecast, dtype=float)) ** 2


def mincer_zarnowitz(proxy: pd.Series, forecast: pd.Series, hac_lags: int = 5) -> dict:
    """Régression proxy = a + b h + e (erreurs de Newey-West). Prévision sans biais : a = 0 et b = 1 (test conjoint de Wald). b < 1 : prévisions trop dispersées."""
    import statsmodels.api as sm

    both = pd.concat([pd.Series(proxy, name="y"), pd.Series(forecast, name="f")], axis=1, join="inner").dropna()
    if len(both) < 50:
        raise ValueError("Pas assez d'observations pour Mincer-Zarnowitz (minimum 50).")
    if float(both["f"].std()) <= 1e-9 * max(abs(float(both["f"].mean())), 1e-300):        # prévision constante : la pente n'est pas identifiable
        return {"intercept": None, "slope": None, "r2": None, "pvalue": None, "n_obs": len(both), "degenerate": True}
    fit = sm.OLS(both["y"], sm.add_constant(both[["f"]])).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
    wald = fit.wald_test((np.eye(2), np.array([0.0, 1.0])), use_f=True, scalar=True)        # H0 : intercept = 0 et pente = 1
    return {"intercept": float(fit.params["const"]), "slope": float(fit.params["f"]), "r2": float(fit.rsquared),
            "pvalue": float(wald.pvalue), "n_obs": int(fit.nobs)}


# ---------------------------------------------------------------- prévisions
def _frame(index, var, q01=None, q05=None) -> pd.DataFrame:
    out = pd.DataFrame({"var": np.asarray(var, dtype=float)}, index=index)
    if q01 is not None:
        out["q01"], out["q05"] = np.asarray(q01, dtype=float), np.asarray(q05, dtype=float)
    return out


def variance_forecasts(x: pd.Series, model: str, dist: str, *, mean: str = "constant", min_train: int = MIN_TRAIN, refit_every: int = REFIT_EVERY,
                       window: int | None = None, maxiter: int | None = None) -> pd.DataFrame:
    """Variance prévue (décimale) et quantiles de rendement à 1 % et 5 % pour chaque date après `min_train`.
    Quantiles : quantile empirique des résidus standardisés du bloc d'estimation, appliqué à la volatilité prévue (simulation historique filtrée)."""
    V._check(model, dist, mean)
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) <= min_train + 10:
        raise ValueError(f"Série trop courte pour une prévision hors échantillon ({len(s)} observations, apprentissage minimal {min_train}).")
    y = s * 100.0
    n = len(y)
    var = np.empty(n - min_train)
    q = np.empty((n - min_train, 2))
    prev = None
    info = {"n_refits": 0, "n_failed_refits": 0, "n_not_converged": 0}
    for start in range(min_train, n, refit_every):
        stop = min(start + refit_every, n)
        t0 = max(0, start - window) if window else 0
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = V._fit_one(y.iloc[t0:start], model, dist, mean, maxiter, starting_values=None if prev is None else prev.params.to_numpy())
            if res.convergence_flag != 0:
                info["n_not_converged"] += 1
            prev = res
        except Exception:
            info["n_failed_refits"] += 1
            if prev is None:
                raise
            res = prev
        info["n_refits"] += 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fixed = V.build_model(y.iloc[t0:stop], model, dist, mean).fix(res.params)
        sigma = np.asarray(fixed.conditional_volatility, dtype=float)[start - t0:stop - t0]
        z = np.asarray(res.std_resid, dtype=float)
        z = z[np.isfinite(z)]
        mu = float(res.params.get("mu", 0.0))
        i0, i1 = start - min_train, stop - min_train
        var[i0:i1] = (sigma / 100.0) ** 2
        q[i0:i1, 0] = mu / 100.0 + sigma / 100.0 * np.quantile(z, LEVELS[0])
        q[i0:i1, 1] = mu / 100.0 + sigma / 100.0 * np.quantile(z, LEVELS[1])
    out = _frame(s.index[min_train:], var, q[:, 0], q[:, 1])
    out.attrs.update(info)
    return out


def riskmetrics_forecasts(x: pd.Series, min_train: int = MIN_TRAIN, lam: float = LAMBDA) -> pd.DataFrame:
    """EWMA à lambda fixe (RiskMetrics) : h_t = lam h_{t-1} + (1 - lam) r_{t-1}^2. Aucun paramètre estimé : la référence la plus simple à battre."""
    r = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    n = len(r)
    h = np.empty(n)
    h[0] = float(np.var(r[:max(20, min(50, min_train))]))
    for t in range(1, n):
        h[t] = lam * h[t - 1] + (1 - lam) * r[t - 1] ** 2
    idx = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna().index[min_train:]
    z = stats.norm.ppf(LEVELS)
    sig = np.sqrt(h[min_train:])
    return _frame(idx, h[min_train:], z[0] * sig, z[1] * sig)


def rolling_forecasts(x: pd.Series, min_train: int = MIN_TRAIN, window: int = ROLLING_WINDOW) -> pd.DataFrame:
    """Variance historique des `window` derniers jours (r^2 moyen) : l'autre référence naïve."""
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    h = (s ** 2).rolling(window).mean().shift(1)
    z = stats.norm.ppf(LEVELS)
    h = h.iloc[min_train:]
    sig = np.sqrt(h)
    return _frame(h.index, h, z[0] * sig, z[1] * sig)


def har_forecasts(rv: pd.Series, min_train: int = MIN_TRAIN, refit_every: int = REFIT_EVERY, log: bool = False) -> pd.DataFrame:
    """HAR-RV prévu à un pas : coefficients estimés sur les dates antérieures au bloc, régresseurs retardés d'un jour. Prévoit la variance RÉALISÉE
    (échelle du proxy range-based, plus basse que la variance close-to-close : comparer sur le même proxy)."""
    import statsmodels.api as sm

    s = pd.Series(rv).replace([np.inf, -np.inf], np.nan).dropna()
    X, y = V._har_design(s, log=log)
    dates = s.index[min_train:]
    if len(dates) < 10:
        raise ValueError("Série trop courte pour un HAR-RV hors échantillon.")
    pred = pd.Series(np.nan, index=dates)
    for start in range(0, len(dates), refit_every):
        block = dates[start:start + refit_every]
        past = y.index < block[0]
        if past.sum() < 60:
            continue
        fit = sm.OLS(y[past], sm.add_constant(X[past])).fit()
        rows = X.reindex(block).dropna()
        yhat = fit.predict(sm.add_constant(rows, has_constant="add"))
        pred.loc[rows.index] = np.exp(yhat) if log else yhat
    pred = pred.dropna().clip(lower=TINY)
    return _frame(pred.index, pred.to_numpy())


# ---------------------------------------------------------------- comparaison
def compare_forecasts(proxy: pd.Series, forecasts: dict[str, pd.Series], benchmark: str, *, mcs_size: float = 0.10, seed: int = 0,
                      reps: int = 1000, block_size: int = 10, alpha: float = 0.05) -> dict:
    """Compare des prévisions de variance contre un proxy sur leurs dates communes : pertes moyennes (MSE, QLIKE), Mincer-Zarnowitz, Diebold-Mariano
    contre `benchmark` sur le QLIKE (corrigé de Benjamini-Hochberg sur l'ensemble des modèles essayés) et Model Confidence Set (Hansen, Lunde, Nason 2011)."""
    from arch.bootstrap import MCS

    names = list(forecasts)
    frame = pd.concat([pd.Series(proxy, name="__proxy__"), *[pd.Series(forecasts[k]).rename(k) for k in names]], axis=1, join="inner").dropna()
    if len(frame) < 50:
        raise ValueError("Pas assez de dates communes pour comparer les prévisions (minimum 50).")
    p = frame["__proxy__"]
    q_losses = pd.DataFrame({k: qlike(p, frame[k]) for k in names}, index=frame.index)
    rows = []
    for k in names:
        mz = mincer_zarnowitz(p, frame[k])
        rows.append({"name": k, "mean_qlike": float(q_losses[k].mean()), "mean_mse": float(mse_var(p, frame[k]).mean()), "mz_intercept": mz["intercept"],
                     "mz_slope": mz["slope"], "mz_r2": mz["r2"], "mz_p": mz["pvalue"], "mean_forecast": float(frame[k].mean()),
                     "dm_stat": None, "dm_p": None, "dm_p_adj": None, "dm_better": None, "in_mcs": None, "mcs_p": None})
    base = benchmark if benchmark in names else names[0]
    raw: dict[str, float] = {}
    for row in rows:
        if row["name"] == base:
            continue
        dm = diebold_mariano(q_losses[row["name"]].to_numpy(), q_losses[base].to_numpy(), h=1)
        row["dm_stat"], row["dm_p"] = dm["dm_stat"], dm["p_value"]
        if dm["p_value"] == dm["p_value"]:                                 # pas NaN
            raw[row["name"]] = dm["p_value"]
    fdr = benjamini_hochberg(raw, alpha=alpha) if raw else {"results": {}}
    for row in rows:
        hit = fdr["results"].get(row["name"])
        if hit:
            row["dm_p_adj"] = hit["adjusted_p_value"]
            row["dm_better"] = bool(hit["adjusted_p_value"] < alpha and row["dm_stat"] < 0)
    mcs_error = None
    if len(names) >= 2:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mcs = MCS(q_losses, size=mcs_size, reps=reps, block_size=block_size, method="R", seed=seed)
                mcs.compute()
            included = set(mcs.included)
            pv = mcs.pvalues["Pvalue"]
            for row in rows:
                row["in_mcs"], row["mcs_p"] = row["name"] in included, float(pv.get(row["name"], np.nan))
        except Exception as exc:  # noqa: BLE001 -- le MCS peut échouer (pertes dégénérées) : on l'affiche, on ne cache pas le reste
            mcs_error = str(exc)[:160]
    else:
        for row in rows:
            row["in_mcs"] = True
    rows.sort(key=lambda r: r["mean_qlike"])
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return clean({"rows": rows, "n_models": len(names), "n_obs": len(frame), "benchmark": base, "mcs_size": mcs_size, "mcs_error": mcs_error,
                  "n_dm_tests": len(raw), "loss": "qlike"})


# ---------------------------------------------------------------- VaR
def kupiec_pof(hits, p: float) -> dict:
    """Test de couverture inconditionnelle de Kupiec (1995) : le taux de dépassements vaut-il p ? LR ~ chi2(1) sous H0."""
    h = np.asarray(hits, dtype=bool)
    n, x = len(h), int(h.sum())
    pi = x / n if n else 0.0
    ll0 = xlogy(n - x, 1 - p) + xlogy(x, p)
    ll1 = xlogy(n - x, 1 - pi) + xlogy(x, pi)
    lr = float(max(0.0, -2.0 * (ll0 - ll1)))
    return {"lr": lr, "pvalue": float(stats.chi2.sf(lr, 1)), "n": n, "hits": x, "rate": pi, "expected_rate": p}


def christoffersen(hits, p: float) -> dict:
    """Christoffersen (1998) : couverture inconditionnelle (Kupiec), indépendance des dépassements (chaîne de Markov d'ordre 1) et test conjoint."""
    h = np.asarray(hits, dtype=bool).astype(int)
    uc = kupiec_pof(h, p)
    a, b = h[:-1], h[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    total = n00 + n01 + n10 + n11
    pi = (n01 + n11) / total if total else 0.0
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    ll0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    ll1 = xlogy(n00, 1 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1 - pi11) + xlogy(n11, pi11)
    lr_ind = float(max(0.0, -2.0 * (ll0 - ll1)))
    lr_cc = uc["lr"] + lr_ind
    return {"unconditional": uc,
            "independence": {"lr": lr_ind, "pvalue": float(stats.chi2.sf(lr_ind, 1)), "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11}},
            "conditional": {"lr": lr_cc, "pvalue": float(stats.chi2.sf(lr_cc, 2))}}


def var_backtest(r: pd.Series, forecast: pd.DataFrame) -> dict:
    """Dépassements de la VaR à 99 % et 95 % (rendement < quantile prévu) et tests de Kupiec et Christoffersen, sur les dates de `forecast`."""
    idx = forecast.index.intersection(r.index)
    out = {}
    for level, col in zip(LEVELS, ("q01", "q05"), strict=True):
        if col not in forecast:
            continue
        hits = (r.loc[idx] < forecast.loc[idx, col]).to_numpy()
        out[f"{level:g}"] = christoffersen(hits, level)
    return out


# ---------------------------------------------------------------- orchestration
def _spec_forecast(name: str, x: pd.Series, proxy: pd.Series | None, *, min_train: int, refit_every: int, window: int | None) -> pd.DataFrame:
    if name == "riskmetrics":
        return riskmetrics_forecasts(x, min_train)
    if name.startswith("rolling"):
        return rolling_forecasts(x, min_train, int(name[7:] or ROLLING_WINDOW))
    if name == "har":
        if proxy is None:
            raise ValueError("Le HAR-RV demande un proxy de variance réalisée (prix OHLC) : modèle inconnu pour cette série.")
        return har_forecasts(proxy, min_train, refit_every)
    model, _, dist = name.partition("|")
    V._check(model, dist or "normal", "constant")
    return variance_forecasts(x, model, dist or "normal", min_train=min_train, refit_every=refit_every, window=window)


def evaluate_forecasts(x: pd.Series, proxy: pd.Series | None, specs: list[str], *, min_train: int = MIN_TRAIN, refit_every: int = REFIT_EVERY,
                       window: int | None = None, benchmark: str | None = None, mcs_reps: int = 1000, seed: int = 0,
                       proxy_label: str | None = None) -> dict:
    """Prévoit la variance de chaque spécification de `specs` (« garch|normal », « gjr|t », « riskmetrics », « rolling60 », « har ») hors échantillon,
    puis compare. `proxy` : variance réalisée journalière décimale (Parkinson, Garman-Klass) ; absent, on utilise r^2."""
    s = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    for name in specs:
        if name not in ("riskmetrics", "har") and not name.startswith("rolling"):
            m, _, d = name.partition("|")
            V._check(m, d or "normal", "constant")
    forecasts, refit, backtests = {}, {}, {}
    for name in specs:
        f = _spec_forecast(name, s, proxy, min_train=min_train, refit_every=refit_every, window=window)
        forecasts[name] = f["var"]
        refit[name] = dict(f.attrs)
        if "q01" in f:
            backtests[name] = var_backtest(s, f)
    used_proxy = "squared_return"
    target = s ** 2
    if proxy is not None:
        target, used_proxy = pd.Series(proxy), "range_based"
    if proxy_label:                                                       # le proxy transmis peut n'être que r^2 (utile au HAR-RV) : l'étiquette dit la vérité
        used_proxy = "squared_return" if proxy_label == "r2" else proxy_label
    base = benchmark if benchmark in forecasts else ("riskmetrics" if "riskmetrics" in forecasts else specs[0])
    comp = compare_forecasts(target, forecasts, base, reps=mcs_reps, seed=seed)
    return clean({"comparison": comp, "var_backtest": backtests, "refit": refit, "proxy": used_proxy, "n_obs": comp["n_obs"],
                  "min_train": min_train, "refit_every": refit_every, "window": window})
