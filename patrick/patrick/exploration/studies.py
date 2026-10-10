"""Études statistiques de la page Exploration : fonctions pures sur des rendements (et niveaux) déjà alignés (`panel.Panel`).

Ce qui existe déjà ailleurs n'est PAS refait ici : rendements/z-score/moyennes mobiles/volatilité par actif (`webapp/asset_stats.py`),
covariance et HRP (`tracking/covariance.py`, `tracking/hrp.py`), qualité des données, dérive PSI, régime HMM
(`tracking/market_state.py`) et étude d'événements (`research/event_study.py`).

Honnêteté statistique : chaque étude renvoie `n_obs` et, quand plusieurs tests sont lancés d'un coup (paires, jours de semaine, mois),
les p-values corrigées de Benjamini-Hochberg (`validation/fdr.py`) à côté des brutes. Une p-value brute parmi des dizaines de tests
est un faux positif sur vingt en moyenne ; la colonne corrigée est celle qui compte.

Toutes les sorties sont des dict/listes JSON-compatibles (NaN et infinis deviennent `None`).
"""
from __future__ import annotations

import math
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as sst
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import acf, adfuller, coint, grangercausalitytests, kpss, pacf

from patrick.validation.fdr import benjamini_hochberg

ALPHA = 0.05
MAX_PAIR_TESTS = 800


# --------------------------------------------------------------------------- utilitaires


def clean(obj):
    """Convertit récursivement en types JSON natifs ; NaN/inf -> None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def _bh(pvals: dict[str, float], alpha: float = ALPHA) -> dict[str, float | None]:
    """p-values ajustées de Benjamini-Hochberg (mêmes clés). Un seul test : la p-value brute est rendue telle quelle."""
    items = {k: v for k, v in pvals.items() if v is not None and math.isfinite(v)}
    if len(items) < 2:
        return {k: items.get(k) for k in pvals}
    results = benjamini_hochberg(items, alpha=alpha)["results"]
    return {k: (float(results[k]["adjusted_p_value"]) if k in results else None) for k in pvals}


def _annual(periods: int) -> float:
    return math.sqrt(periods)


def _drawdown(levels_or_cum: pd.Series) -> tuple[float, pd.Timestamp | None]:
    peak = levels_or_cum.cummax()
    dd = levels_or_cum / peak - 1.0
    if dd.empty:
        return float("nan"), None
    return float(dd.min()), dd.idxmin()


def _verdict(p: float | None, alpha: float = ALPHA) -> bool | None:
    return None if p is None else bool(p < alpha)


# --------------------------------------------------------------------------- 1. corrélations


def cluster_order(corr: pd.DataFrame) -> list[str]:
    """Ordre des actifs qui range les corrélés côte à côte (classification hiérarchique à liaison moyenne sur la distance
    sqrt(0,5 · (1 − ρ)), celle de López de Prado)."""
    n = corr.shape[0]
    if n < 3:
        return list(corr.columns)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.fillna(0.0).to_numpy()), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2.0
    link = hierarchy.linkage(squareform(dist, checks=False), method="average")
    leaves = hierarchy.leaves_list(link)
    return [corr.columns[i] for i in leaves]


def _pair_pvalue(a: np.ndarray, b: np.ndarray, method: str) -> float:
    if method == "spearman":
        return float(sst.spearmanr(a, b).pvalue)
    if method == "kendall":
        return float(sst.kendalltau(a, b).pvalue)
    return float(sst.pearsonr(a, b).pvalue)


def correlation(returns: pd.DataFrame, method: str = "pearson", cluster: bool = True) -> dict:
    if method not in ("pearson", "spearman", "kendall"):
        raise ValueError("méthode inconnue (pearson, spearman ou kendall)")
    corr = returns.corr(method=method)
    order = cluster_order(corr) if cluster else list(corr.columns)
    corr = corr.loc[order, order]
    cols = list(corr.columns)
    pairs = list(combinations(cols, 2))
    out: dict = {"method": method, "labels": cols, "matrix": corr.to_numpy(), "n_obs": int(len(returns))}
    if 2 <= len(cols) and len(pairs) <= MAX_PAIR_TESTS:
        raw = {f"{a}|{b}": _pair_pvalue(returns[a].to_numpy(), returns[b].to_numpy(), method) for a, b in pairs}
        adj = _bh(raw)
        n = len(cols)
        sig = [[None] * n for _ in range(n)]
        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                if i == j:
                    continue
                key = f"{a}|{b}" if f"{a}|{b}" in adj else f"{b}|{a}"
                q = adj.get(key)
                sig[i][j] = None if q is None else bool(q < ALPHA)
        out["significant"] = sig
        out["n_tests"] = len(pairs)
        flat = [(a, b, float(corr.loc[a, b]), adj.get(f"{a}|{b}"), raw[f"{a}|{b}"]) for a, b in pairs]
    else:
        flat = [(a, b, float(corr.loc[a, b]), None, None) for a, b in pairs]
        out["significant"] = None
        out["n_tests"] = len(pairs)
    flat.sort(key=lambda r: r[2])
    out["most_negative"] = [{"a": a, "b": b, "rho": r, "p_adj": q} for a, b, r, q, _ in flat[:5] if r < 0]
    out["most_positive"] = [{"a": a, "b": b, "rho": r, "p_adj": q} for a, b, r, q, _ in reversed(flat[-5:]) if r > 0]
    if len(cols) >= 2:
        off = corr.to_numpy()[np.triu_indices(len(cols), k=1)]
        out["mean_abs_corr"] = float(np.nanmean(np.abs(off)))
    return clean(out)


def rolling_correlation(returns: pd.DataFrame, a: str, b: str, window: int = 60) -> dict:
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    if window < 10:
        raise ValueError("Fenêtre trop courte (minimum 10 observations).")
    if len(returns) < window + 5:
        raise ValueError(f"Fenêtre de {window} trop longue pour {len(returns)} observations.")
    roll = returns[a].rolling(window).corr(returns[b]).dropna()
    full = float(returns[a].corr(returns[b]))
    # écart-type attendu du seul hasard : une corrélation de fenêtre varie d'environ 1/sqrt(window) même si le vrai lien est fixe.
    noise = 1.0 / math.sqrt(window)
    half = len(roll) // 2
    return clean({
        "a": a, "b": b, "window": window, "n_obs": int(len(returns)),
        "dates": [d.strftime("%Y-%m-%d") for d in roll.index], "values": roll.to_numpy(),
        "full_sample": full, "min": float(roll.min()), "max": float(roll.max()), "last": float(roll.iloc[-1]),
        "std": float(roll.std()), "noise_band": noise,
        "first_half_mean": float(roll.iloc[:half].mean()) if half else None,
        "second_half_mean": float(roll.iloc[half:].mean()) if half else None,
    })


# --------------------------------------------------------------------------- 2. distribution


def describe(returns: pd.DataFrame, levels: pd.DataFrame, periods_per_year: int, transforms: dict[str, str] | None = None) -> dict:
    rows = []
    sq = _annual(periods_per_year)
    transforms = transforms or {}
    for col in returns.columns:
        r = returns[col].dropna()
        if len(r) < 8:
            continue
        jb = sst.jarque_bera(r.to_numpy())
        q05, q01 = float(np.quantile(r, 0.05)), float(np.quantile(r, 0.01))
        lv = levels[col].dropna() if col in levels else pd.Series(dtype=float)
        # perte maximale seulement pour un niveau strictement positif (prix, indice) ; pas pour un taux ou un écart de crédit.
        dd, dd_date = _drawdown(lv) if (len(lv) and bool((lv > 0).all()) and transforms.get(col) != "diff") else (None, None)
        lag1 = float(r.autocorr(lag=1)) if len(r) > 3 else float("nan")
        rows.append({
            "symbol": col, "n": int(len(r)), "transform": transforms.get(col),
            "mean_ann": float(r.mean() * periods_per_year), "vol_ann": float(r.std(ddof=1) * sq),
            "skew": float(sst.skew(r)), "excess_kurtosis": float(sst.kurtosis(r)),
            "jb_stat": float(jb.statistic), "jb_p": float(jb.pvalue), "normal_rejected": bool(jb.pvalue < ALPHA),
            "var95": q05, "es95": float(r[r <= q05].mean()), "var99": q01,
            "es99": float(r[r <= q01].mean()) if (r <= q01).any() else None,
            "worst": float(r.min()), "worst_date": r.idxmin(), "best": float(r.max()), "best_date": r.idxmax(),
            "pct_positive": float((r > 0).mean()), "autocorr_1": lag1,
            "max_drawdown": dd, "max_drawdown_date": dd_date,
        })
    return clean({"rows": rows, "n_obs": int(len(returns)), "periods_per_year": periods_per_year})


# --------------------------------------------------------------------------- 3. mémoire et stationnarité


def hurst_exponent(x: pd.Series, max_lag: int = 100) -> float | None:
    """Exposant de Hurst par la loi d'échelle des écarts : std(x[t+τ] − x[t]) ∝ τ^H, sur le LOG-niveau.
    H ≈ 0,5 : marche aléatoire ; < 0,5 : retour à la moyenne ; > 0,5 : tendance persistante."""
    v = np.asarray(x.dropna(), dtype=float)
    top = min(max_lag, len(v) // 4)
    if top < 10:
        return None
    lags = np.unique(np.round(np.logspace(math.log10(2), math.log10(top), 20)).astype(int))
    tau = []
    for lag in lags:
        d = v[lag:] - v[:-lag]
        s = float(np.std(d, ddof=1))
        tau.append(s if s > 0 else np.nan)
    tau = np.asarray(tau)
    ok = np.isfinite(tau)
    if ok.sum() < 5:
        return None
    slope = np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0]
    return float(slope)


def _hurst_label(h: float | None) -> str | None:
    if h is None:
        return None
    return "mean_reverting" if h < 0.45 else ("trending" if h > 0.55 else "random_walk")


def stationarity(levels: pd.DataFrame, returns: pd.DataFrame) -> dict:
    rows, adf_p, kpss_p = [], {}, {}
    for col in returns.columns:
        lv = levels[col].dropna()
        lv_log = np.log(lv) if bool((lv > 0).all()) else lv
        r = returns[col].dropna()
        entry = {"symbol": col, "n": int(len(r))}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                a_lv = adfuller(lv_log.to_numpy(), autolag="AIC")
                a_r = adfuller(r.to_numpy(), autolag="AIC")
                k_lv = kpss(lv_log.to_numpy(), regression="c", nlags="auto")
                k_r = kpss(r.to_numpy(), regression="c", nlags="auto")
            except Exception as exc:  # noqa: BLE001 -- une série dégénérée ne bloque pas les autres
                entry["error"] = str(exc)[:100]
                rows.append(entry)
                continue
        entry.update({
            "adf_level_p": float(a_lv[1]), "adf_return_p": float(a_r[1]),
            "kpss_level_p": float(k_lv[1]), "kpss_return_p": float(k_r[1]),
        })
        entry["level_stationary"] = bool(a_lv[1] < ALPHA and k_lv[1] > ALPHA)
        entry["level_unit_root"] = bool(a_lv[1] >= ALPHA and k_lv[1] <= ALPHA)
        entry["return_stationary"] = bool(a_r[1] < ALPHA and k_r[1] > ALPHA)
        h = hurst_exponent(lv_log)
        entry["hurst"], entry["hurst_label"] = h, _hurst_label(h)
        adf_p[col], kpss_p[col] = float(a_lv[1]), float(k_lv[1])
        rows.append(entry)
    return clean({"rows": rows, "n_obs": int(len(returns)),
                  "note": "ADF : H0 = racine unitaire (p < 5 % => stationnaire). KPSS : H0 = stationnaire (p < 5 % => non stationnaire)."})


def memory(returns: pd.Series, nlags: int = 20) -> dict:
    r = returns.dropna()
    n = len(r)
    nlags = int(min(max(2, nlags), n // 3, 60))
    if n < 30:
        raise ValueError("Pas assez d'observations pour l'autocorrélation (minimum 30).")
    ac = acf(r, nlags=nlags, fft=True)[1:]
    pc = pacf(r, nlags=nlags, method="ywm")[1:]
    ac2 = acf(r**2, nlags=nlags, fft=True)[1:]
    band = 1.96 / math.sqrt(n)
    lb_lags = [k for k in (5, 10, 20) if k <= nlags] or [nlags]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lb_r = acorr_ljungbox(r, lags=lb_lags, return_df=True)
        lb_sq = acorr_ljungbox(r**2, lags=lb_lags, return_df=True)
        arch_lm = het_arch(r.to_numpy(), nlags=min(5, nlags))
    lb_ret = {int(k): float(lb_r.loc[k, "lb_pvalue"]) for k in lb_r.index}
    lb_vol = {int(k): float(lb_sq.loc[k, "lb_pvalue"]) for k in lb_sq.index}
    return clean({
        "n_obs": n, "nlags": nlags, "lags": list(range(1, nlags + 1)), "acf": ac, "pacf": pc, "acf_squared": ac2, "band": band,
        "ljung_box_returns_p": lb_ret, "ljung_box_squared_p": lb_vol,
        "arch_lm_p": float(arch_lm[1]), "arch_lm_stat": float(arch_lm[0]),
        "returns_autocorrelated": bool(min(lb_ret.values()) < ALPHA),
        "volatility_clustering": bool(arch_lm[1] < ALPHA),
        "hurst": hurst_exponent(pd.Series(np.cumsum(r.to_numpy()))),
    })


# --------------------------------------------------------------------------- 4. liens entre deux actifs


def cross_correlation(returns: pd.DataFrame, a: str, b: str, maxlag: int = 10) -> dict:
    """corr(a[t], b[t − k]) pour k de −maxlag à +maxlag. k > 0 : b mène (b d'il y a k périodes explique a d'aujourd'hui)."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    ra, rb = returns[a], returns[b]
    n = len(returns)
    maxlag = int(min(max(1, maxlag), max(1, n // 5), 40))
    lags = list(range(-maxlag, maxlag + 1))
    vals = [float(ra.corr(rb.shift(k))) for k in lags]
    band = 1.96 / math.sqrt(n)
    sig = [abs(v) > band for v in vals]
    best = max(range(len(lags)), key=lambda i: abs(vals[i]) if lags[i] != 0 else -1)
    return clean({"a": a, "b": b, "n_obs": n, "lags": lags, "values": vals, "band": band, "significant": sig,
                  "contemporaneous": vals[lags.index(0)], "best_lag": lags[best], "best_value": vals[best],
                  "note": "Bande ±1,96/√n : hors bande = corrélation à ce décalage significative isolément (sans correction des "
                          f"{len(lags)} décalages testés)."})


def granger(returns: pd.DataFrame, a: str, b: str, maxlag: int = 5) -> dict:
    """Test de causalité de Granger dans les deux sens (le passé de x aide-t-il à prédire y au-delà du passé de y ?).
    Granger mesure un pouvoir prédictif linéaire, jamais une causalité économique."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    n = len(returns)
    maxlag = int(min(max(1, maxlag), max(1, n // 20), 10))

    def one_way(cause: str, effect: str) -> dict:
        data = returns[[effect, cause]].dropna()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = grangercausalitytests(data, maxlag=maxlag)
        pvals = {k: float(res[k][0]["ssr_ftest"][1]) for k in res}
        best_k = min(pvals, key=pvals.get)
        # p-value minimale sur `maxlag` décalages : correction de Bonferroni (prudente) pour ne pas chercher le meilleur décalage.
        bonf = min(1.0, pvals[best_k] * maxlag)
        return {"cause": cause, "effect": effect, "p_by_lag": pvals, "best_lag": int(best_k),
                "p_min": pvals[best_k], "p_bonferroni": bonf, "predictive": bool(bonf < ALPHA)}

    return clean({"a": a, "b": b, "n_obs": n, "maxlag": maxlag, "a_to_b": one_way(a, b), "b_to_a": one_way(b, a)})


def cointegration(levels: pd.DataFrame, a: str, b: str, zwindow: int = 60) -> dict:
    """Test d'Engle-Granger sur les log-niveaux, ratio de couverture par moindres carrés, écart (spread) et son z-score glissant,
    demi-vie du retour à la moyenne."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    la, lb = levels[a], levels[b]
    if not (bool((la > 0).all()) and bool((lb > 0).all())):
        raise ValueError("Cointégration calculée sur des log-niveaux : un des actifs a des niveaux ≤ 0.")
    ya, xb = np.log(la), np.log(lb)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, p, crit = coint(ya, xb, trend="c", autolag="aic")
    x = np.column_stack([np.ones(len(xb)), xb.to_numpy()])
    beta = np.linalg.lstsq(x, ya.to_numpy(), rcond=None)[0]
    spread = pd.Series(ya.to_numpy() - x @ beta, index=la.index)
    lag = spread.shift(1).dropna()
    d = spread.diff().dropna()
    phi = float(np.polyfit(lag.to_numpy(), d.to_numpy(), 1)[0])        # d[t] = phi * s[t-1] + e
    rho = 1.0 + phi                                                    # autocorrélation de l'écart d'une période à l'autre
    if phi >= 0:
        half_life = None                                               # pas de retour à la moyenne
    elif rho <= 0.0:
        half_life = 0.0                                                # l'écart se corrige en moins d'une période
    else:
        half_life = float(-math.log(2) / math.log(rho))
    zwindow = int(min(max(10, zwindow), len(spread) // 2))
    z = ((spread - spread.rolling(zwindow).mean()) / spread.rolling(zwindow).std()).dropna()
    return clean({
        "a": a, "b": b, "n_obs": int(len(levels)), "test_stat": float(stat), "p_value": float(p),
        "critical_values": {"1%": float(crit[0]), "5%": float(crit[1]), "10%": float(crit[2])},
        "cointegrated": bool(p < ALPHA), "hedge_ratio": float(beta[1]), "intercept": float(beta[0]),
        "half_life_periods": half_life, "zwindow": zwindow,
        "dates": [d_.strftime("%Y-%m-%d") for d_ in z.index], "zscore": z.to_numpy(), "last_zscore": float(z.iloc[-1]),
        "note": "p < 5 % : l'écart entre les deux log-prix revient vers sa moyenne (relation de long terme). Test sur un seul couple : "
                "pas de correction nécessaire, mais un lien trouvé en scrutant beaucoup de couples n'a pas la même valeur.",
    })


# --------------------------------------------------------------------------- 5. structure


def pca(returns: pd.DataFrame, n_components: int = 5) -> dict:
    k = returns.shape[1]
    if k < 2:
        raise ValueError("L'analyse en composantes principales demande au moins deux actifs.")
    z = (returns - returns.mean()) / returns.std(ddof=1).replace(0, np.nan)
    z = z.dropna(axis=1, how="any")
    cov = np.cov(z.to_numpy(), rowvar=False)
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    ratio = vals / vals.sum()
    nc = int(min(max(1, n_components), len(vals)))
    comps = []
    for i in range(nc):
        v = vecs[:, i]
        if v.sum() < 0:
            v = -v                                              # signe conventionnel : le facteur 1 est positif en moyenne
        loadings = sorted(zip(z.columns, v, strict=True), key=lambda t: -abs(t[1]))
        comps.append({"component": i + 1, "explained": float(ratio[i]),
                      "loadings": [{"symbol": s, "loading": float(w)} for s, w in loadings]})
    cum = np.cumsum(ratio)
    # nombre de facteurs à garder pour 80 % de la variance
    n80 = int(np.searchsorted(cum, 0.80) + 1)
    return clean({"n_obs": int(len(z)), "n_assets": int(z.shape[1]), "explained": ratio[:max(nc, 10)], "cumulative": cum[:max(nc, 10)],
                  "components": comps, "n_for_80pct": n80, "first_factor_share": float(ratio[0]),
                  "note": "Calculé sur les rendements centrés-réduits. Une première composante dominante = un facteur de marché commun "
                          "(les actifs bougent ensemble) : la diversification apparente est alors faible."})


def beta_alpha(returns: pd.DataFrame, asset: str, bench: str, window: int = 60, periods_per_year: int = 252) -> dict:
    if asset == bench:
        raise ValueError("L'actif et la référence doivent être différents.")
    y, x = returns[asset], returns[bench]
    xc = x - x.mean()
    beta = float((xc * (y - y.mean())).sum() / (xc**2).sum())
    alpha = float(y.mean() - beta * x.mean())
    resid = y - alpha - beta * x
    n = len(y)
    s2 = float((resid**2).sum() / (n - 2))
    se_beta = math.sqrt(s2 / float((xc**2).sum()))
    se_alpha = math.sqrt(s2 * (1.0 / n + float(x.mean()) ** 2 / float((xc**2).sum())))
    t_beta, t_alpha = beta / se_beta, alpha / se_alpha
    r2 = float(1.0 - (resid**2).sum() / ((y - y.mean()) ** 2).sum())
    window = int(min(max(20, window), n // 2))
    cov = y.rolling(window).cov(x)
    var = x.rolling(window).var()
    rb = (cov / var).dropna()
    return clean({
        "asset": asset, "bench": bench, "n_obs": n, "beta": beta, "beta_se": se_beta, "beta_t": t_beta,
        "beta_p": float(2 * (1 - sst.t.cdf(abs(t_beta), n - 2))),
        "alpha_per_period": alpha, "alpha_annualized": alpha * periods_per_year, "alpha_t": t_alpha,
        "alpha_p": float(2 * (1 - sst.t.cdf(abs(t_alpha), n - 2))), "r2": r2, "window": window,
        "dates": [d.strftime("%Y-%m-%d") for d in rb.index], "rolling_beta": rb.to_numpy(),
        "rolling_beta_min": float(rb.min()), "rolling_beta_max": float(rb.max()),
    })


def tail_dependence(returns: pd.DataFrame, a: str, b: str, q: float = 0.05) -> dict:
    """P(b dans sa queue | a dans sa queue), côté baisse et côté hausse. Sous indépendance, vaut q. Un rapport ≫ 1 : les deux actifs
    chutent (ou montent) ensemble bien plus souvent que ce que dit la corrélation moyenne."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    if not 0.01 <= q <= 0.2:
        raise ValueError("Quantile de queue entre 1 % et 20 %.")
    ra, rb = returns[a], returns[b]
    lo_a, lo_b = ra <= ra.quantile(q), rb <= rb.quantile(q)
    hi_a, hi_b = ra >= ra.quantile(1 - q), rb >= rb.quantile(1 - q)

    def cond(ca, cb):
        n = int(ca.sum())
        k = int((ca & cb).sum())
        return (k / n if n else None), k, n

    lower, kl, nl = cond(lo_a, lo_b)
    upper, ku, nu = cond(hi_a, hi_b)
    return clean({"a": a, "b": b, "q": q, "n_obs": int(len(returns)), "pearson": float(ra.corr(rb)),
                  "lower": lower, "lower_hits": kl, "lower_n": nl, "lower_ratio": (lower / q if lower is not None else None),
                  "upper": upper, "upper_hits": ku, "upper_n": nu, "upper_ratio": (upper / q if upper is not None else None),
                  "independence": q,
                  "note": f"Avec seulement {nl} observations dans la queue, ces fréquences sont très bruitées."})


# --------------------------------------------------------------------------- 6. saisonnalité


def seasonality(returns: pd.Series, freq: str = "D") -> dict:
    r = returns.dropna()
    if len(r) < 60:
        raise ValueError("Pas assez d'observations pour une saisonnalité (minimum 60).")
    overall = float(r.mean())
    groups: dict[str, pd.Series] = {}
    out: dict = {"n_obs": int(len(r)), "mean_all": overall}
    month_names = ["Janv", "Févr", "Mars", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"]
    weekday_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    if freq == "D":
        for wd in sorted(set(r.index.weekday)):
            groups[f"wd:{weekday_names[wd]}"] = r[r.index.weekday == wd]
    for mo in sorted(set(r.index.month)):
        groups[f"mo:{month_names[mo - 1]}"] = r[r.index.month == mo]
    turn = None
    if freq == "D":
        month_key = r.index.to_period("M")
        pos = r.groupby(month_key).cumcount()
        from_end = r.groupby(month_key).cumcount(ascending=False)
        is_turn = (from_end == 0) | (pos < 3)                    # dernier jour + 3 premiers jours de bourse du mois
        turn = {"turn": r[is_turn], "rest": r[~is_turn]}
        if len(turn["turn"]) > 5 and len(turn["rest"]) > 5:
            groups["tom:turn"] = turn["turn"]
    rows, raw_p = [], {}
    for key, g in groups.items():
        rest = r.drop(g.index)
        if len(g) < 5 or len(rest) < 5:
            continue
        t = sst.ttest_ind(g.to_numpy(), rest.to_numpy(), equal_var=False)          # le groupe contre TOUT le reste (Welch)
        raw_p[key] = float(t.pvalue)
        rows.append({"key": key, "group": key.split(":", 1)[1], "kind": key.split(":", 1)[0], "n": int(len(g)),
                     "mean": float(g.mean()), "excess": float(g.mean() - rest.mean()), "t": float(t.statistic),
                     "p": float(t.pvalue), "hit_rate": float((g > 0).mean())})
    adj = _bh(raw_p)
    for row in rows:
        row["p_adj"] = adj.get(row["key"])
        row["significant"] = _verdict(row["p_adj"])
    # Test d'ensemble (Kruskal-Wallis, sur les rangs) : « y a-t-il un effet quelque part dans cette famille ? »
    omnibus = {}
    for kind, label in (("wd", "weekday"), ("mo", "month")):
        parts = [g.to_numpy() for k, g in groups.items() if k.startswith(kind + ":") and len(g) >= 5]
        if len(parts) >= 3:
            omnibus[label] = float(sst.kruskal(*parts).pvalue)
    out["omnibus_p"] = omnibus
    out["rows"] = rows
    out["n_tests"] = len(rows)
    out["turn_of_month"] = ({"mean_turn": float(turn["turn"].mean()), "mean_rest": float(turn["rest"].mean()),
                              "n_turn": int(len(turn["turn"]))} if turn is not None and len(turn["turn"]) > 5 else None)
    out["note"] = (f"{len(rows)} groupes testés, chacun contre tout le reste ; seule la p-value corrigée (Benjamini-Hochberg) "
                   "autorise à parler d'effet. Un groupe très atypique tire la moyenne du « reste » et fait paraître les autres "
                   "plus faibles : lire d'abord le test d'ensemble et le groupe le plus extrême.")
    return clean(out)
