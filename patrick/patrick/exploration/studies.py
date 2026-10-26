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

import logging
import math
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as sst
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.ar_model import ar_select_order
from statsmodels.tsa.stattools import (
    acf,
    adfuller,
    coint,
    kpss,
    pacf,
)

from patrick.validation.fdr import benjamini_hochberg

ALPHA = 0.05
MAX_PAIR_TESTS = 800
_log = logging.getLogger(__name__)


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
    return _corr_payload(method, corr, len(returns),
                         lambda a, b: _pair_pvalue(returns[a].to_numpy(), returns[b].to_numpy(), method))


def partial_correlation(returns: pd.DataFrame, cluster: bool = True) -> dict:
    """Corrélation de chaque couple une fois retiré l'effet de TOUS les autres actifs de la sélection (inverse de la matrice de
    covariance). Deux actifs corrélés seulement parce qu'ils suivent un même troisième ont une corrélation partielle proche de zéro :
    ce qui reste est le lien direct."""
    k = returns.shape[1]
    n = len(returns)
    if k < 3:
        raise ValueError("La corrélation partielle demande au moins trois actifs (avec deux, c'est la corrélation simple).")
    if n <= k + 2:
        raise ValueError("Pas assez d'observations pour ce nombre d'actifs.")
    cov = np.cov(returns.to_numpy(dtype=float).T)
    prec = np.linalg.pinv(cov)                          # pseudo-inverse : survit à des actifs presque colinéaires
    d = np.sqrt(np.clip(np.diag(prec), 1e-300, None))
    pc = -prec / np.outer(d, d)
    np.fill_diagonal(pc, 1.0)
    pc = np.clip((pc + pc.T) / 2.0, -1.0, 1.0)
    frame = pd.DataFrame(pc, index=returns.columns, columns=returns.columns)
    order = cluster_order(frame) if cluster else list(frame.columns)
    frame = frame.loc[order, order]
    df = n - k

    def pvalue(a: str, b: str) -> float:
        r = min(max(float(frame.loc[a, b]), -0.999999), 0.999999)
        return float(2 * sst.t.sf(abs(r) * math.sqrt(df / (1.0 - r * r)), df))

    out = _corr_payload("partial", frame, n, pvalue)
    out["condition_number"] = float(np.linalg.cond(cov))
    return clean(out)


def _corr_payload(method: str, corr: pd.DataFrame, n_obs: int, pvalue) -> dict:
    """Charge utile commune des matrices de corrélation : cases significatives (p-values corrigées de Benjamini-Hochberg sur tous les
    couples) et couples les plus liés. `pvalue(a, b)` donne la p-value brute d'un couple."""
    cols = list(corr.columns)
    pairs = list(combinations(cols, 2))
    out: dict = {"method": method, "labels": cols, "matrix": corr.to_numpy(), "n_obs": n_obs}
    if 2 <= len(cols) and len(pairs) <= MAX_PAIR_TESTS:
        raw = {f"{a}|{b}": pvalue(a, b) for a, b in pairs}
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
        "a": a, "b": b, "window": window, "n_obs": len(returns),
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
            "symbol": col, "n": len(r), "transform": transforms.get(col),
            "mean_ann": float(r.mean() * periods_per_year), "vol_ann": float(r.std(ddof=1) * sq),
            "skew": float(sst.skew(r)), "excess_kurtosis": float(sst.kurtosis(r)),
            "jb_stat": float(jb.statistic), "jb_p": float(jb.pvalue), "normal_rejected": bool(jb.pvalue < ALPHA),
            "var95": q05, "es95": float(r[r <= q05].mean()), "var99": q01,
            "es99": float(r[r <= q01].mean()) if (r <= q01).any() else None,
            "worst": float(r.min()), "worst_date": r.idxmin(), "best": float(r.max()), "best_date": r.idxmax(),
            "pct_positive": float((r > 0).mean()), "autocorr_1": lag1,
            "max_drawdown": dd, "max_drawdown_date": dd_date,
        })
    return clean({"rows": rows, "n_obs": len(returns), "periods_per_year": periods_per_year})


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
        entry = {"symbol": col, "n": len(r)}
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
    return clean({"rows": rows, "n_obs": len(returns),
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


def variance_ratio(returns: pd.Series, horizons: tuple[int, ...] = (2, 4, 8, 16)) -> dict:
    """Ratio de variance de Lo-MacKinlay (1988) : si les rendements sont imprévisibles, la variance sur q périodes vaut q fois celle
    d'une période (ratio = 1). Ratio > 1 : les mouvements se prolongent (momentum) ; < 1 : ils se corrigent (retour à la moyenne).
    z* est robuste à l'hétéroscédasticité (variance qui change dans le temps), qui fausse la version classique sur des rendements.
    Test d'ensemble de Chow-Denning : le plus grand |z*| parmi les horizons, p-value de Šidák."""
    r = returns.dropna().to_numpy(dtype=float)
    n = len(r)
    if n < 60:
        raise ValueError("Pas assez d'observations pour le ratio de variance (minimum 60).")
    qs = [q for q in horizons if 2 <= q <= n // 5]
    if not qs:
        raise ValueError("Échantillon trop court pour les horizons demandés.")
    mu = float(r.mean())
    d = r - mu
    d2 = d**2
    var1 = float(d2.sum()) / (n - 1)
    cums = np.concatenate([[0.0], np.cumsum(r)])
    denom = float(d2.sum()) ** 2
    rows, raw = [], {}
    for q in qs:
        sums = cums[q:] - cums[:-q]                                      # sommes glissantes sur q périodes, n − q + 1 termes
        m = q * (n - q + 1) * (1.0 - q / n)
        vr = float(np.sum((sums - q * mu) ** 2) / m) / var1
        z = math.sqrt(n) * (vr - 1.0) / math.sqrt(2.0 * (2 * q - 1) * (q - 1) / (3.0 * q))
        theta = sum((2.0 * (q - j) / q) ** 2 * (n * float(np.sum(d2[j:] * d2[:-j])) / denom) for j in range(1, q))
        z_rob = math.sqrt(n) * (vr - 1.0) / math.sqrt(theta) if theta > 0 else float("nan")
        p_rob = float(2 * sst.norm.sf(abs(z_rob))) if math.isfinite(z_rob) else float("nan")
        raw[str(q)] = p_rob
        rows.append({"q": q, "vr": vr, "z": z, "p": float(2 * sst.norm.sf(abs(z))), "z_robust": z_rob, "p_robust": p_rob})
    adj = _bh(raw)
    finite_z = [abs(r_["z_robust"]) for r_ in rows if math.isfinite(r_["z_robust"])]
    joint = float(1.0 - (2 * sst.norm.cdf(max(finite_z)) - 1.0) ** len(finite_z)) if finite_z else None
    for row in rows:
        row["p_adj"] = adj.get(str(row["q"]))
        row["significant"] = _verdict(row["p_adj"])
    mean_vr = float(np.mean([row["vr"] for row in rows]))
    verdict = "random_walk" if joint is None or joint >= ALPHA else ("momentum" if mean_vr > 1 else "mean_reversion")
    return clean({"n_obs": n, "rows": rows, "joint_p": joint, "verdict": verdict,
                  "note": "Ratio = variance sur q périodes ÷ (q × variance sur 1 période). Le test d'ensemble (Chow-Denning) répond à « y a-t-il "
                          "un écart à la marche aléatoire à un horizon quelconque ? » sans compter plusieurs fois la même chance."})


# --------------------------------------------------------------------------- 4. liens entre deux actifs


CCF_BASES = ("returns", "diff", "abs")
CCF_METHODS = ("pearson", "spearman")
GRANGER_ON = ("returns", "abs")


def aligned_lag(x: np.ndarray, y: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Couples (x_t, y_{t−lag}) : lag > 0, y mène (le passé de y éclaire x) ; lag < 0, x mène."""
    if lag > 0:
        return x[lag:], y[:-lag]
    if lag < 0:
        return x[:lag], y[-lag:]
    return x, y


def ar_residuals(x: pd.Series, max_order: int = 20) -> tuple[pd.Series, int]:
    """Résidus d'un modèle AR(p), p choisi par AIC : retire l'autocorrélation PROPRE à la série. Sans ce « blanchiment », deux séries
    persistantes (volatilité, niveaux) affichent des corrélations croisées significatives sur des dizaines de décalages même sans lien
    (Box-Jenkins ; Haugh 1976). Renvoie les résidus et l'ordre retenu."""
    x = x.dropna()
    pmax = int(min(max_order, len(x) // 20))
    if pmax >= 1:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                sel = ar_select_order(x.to_numpy(dtype=float), maxlag=pmax, ic="aic", trend="c")
                lags = list(sel.ar_lags or [])
                if lags:
                    resid = np.asarray(sel.model.fit().resid, dtype=float)
                    return pd.Series(resid, index=x.index[len(x) - len(resid):]), max(lags)
            except Exception as exc:  # noqa: BLE001 -- série dégénérée (constante...) : repli sur la série centrée
                _log.debug("préblanchiment impossible : %s", exc)
    return x - x.mean(), 0


def _ccf_inputs(returns: pd.DataFrame, levels: pd.DataFrame | None, a: str, b: str, basis: str) -> tuple[pd.Series, pd.Series]:
    if basis == "returns":
        return returns[a], returns[b]
    if basis == "abs":
        return returns[a].abs(), returns[b].abs()
    if levels is None:
        raise ValueError("Les différences de niveau demandent les niveaux de la sélection.")
    d = levels[[a, b]].diff().reindex(returns.index).dropna()
    return d[a], d[b]


def cross_correlation(returns: pd.DataFrame, a: str, b: str, maxlag: int = 10, *, basis: str = "returns", prewhiten: bool = True,
                      method: str = "pearson", levels: pd.DataFrame | None = None) -> dict:
    """corr(a[t], b[t − k]) pour k de −maxlag à +maxlag. k > 0 : b mène (b d'il y a k périodes explique a d'aujourd'hui).

    `basis` : `returns` (la transformation de la sélection), `diff` (variation brute du niveau, pour des taux ou des écarts), `abs`
    (valeur absolue du rendement : proxy de volatilité, où se trouve l'essentiel des liens entre marchés). `prewhiten` retire
    l'autocorrélation propre à chaque série avant de croiser (voir `ar_residuals`). Les décalages sont jugés ensemble : p-values robustes à
    l'hétéroscédasticité et corrigées de Benjamini-Hochberg, test d'ensemble de Haugh-Pierce (Σ r_k² sur les décalages d'un sens), valable
    sur séries blanchies."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    if basis not in CCF_BASES:
        raise ValueError("série inconnue (rendements, différences ou rendements absolus)")
    if method not in CCF_METHODS:
        raise ValueError("méthode inconnue (pearson ou spearman)")
    x, y = _ccf_inputs(returns, levels, a, b, basis)
    orders: dict[str, int] = {}
    if prewhiten:
        x, ox = ar_residuals(x)
        y, oy = ar_residuals(y)
        x, y = x.align(y, join="inner")
        orders = {a: ox, b: oy}
    xv, yv = x.to_numpy(dtype=float), y.to_numpy(dtype=float)
    if method == "spearman":
        xv, yv = sst.rankdata(xv), sst.rankdata(yv)
    n = len(xv)
    maxlag = int(min(max(1, maxlag), max(1, n // 5), 40))
    lags = list(range(-maxlag, maxlag + 1))
    vals, zs, pvals = [], {}, {}
    for k in lags:
        xa, ya = aligned_lag(xv, yv, k)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = float(np.corrcoef(xa, ya)[0, 1])
        vals.append(r)
        # z robuste à l'hétéroscédasticité : Σ x·y / √Σ (x·y)². Sur des rendements à grappes de volatilité, la bande ±1,96/√n est trop
        # étroite (Cheung-Ng 1996) ; ce z, normalisé par les produits réellement observés, reste calibré et vaut le test classique sinon.
        prod = (xa - xa.mean()) * (ya - ya.mean())
        scale = math.sqrt(float(np.sum(prod**2)))
        zs[k] = float(np.sum(prod)) / scale if scale > 0 and len(xa) > 3 else float("nan")
        pvals[str(k)] = float(2 * sst.norm.sf(abs(zs[k]))) if math.isfinite(zs[k]) else float("nan")
    adj = _bh(pvals)
    band = 1.96 / math.sqrt(n)
    sig = [bool(adj[str(k)] is not None and adj[str(k)] < ALPHA) for k in lags]
    finite = [i for i, k in enumerate(lags) if k != 0 and math.isfinite(vals[i])]
    best = max(finite, key=lambda i: abs(vals[i])) if finite else lags.index(0)

    def haugh(sign: int) -> float | None:
        # Haugh-Pierce : n·Σ r_k² sur les décalages d'un sens, ici en version robuste (Σ z_k², même loi du χ² sous indépendance)
        z2 = [zs[k] ** 2 for k in lags if k * sign > 0]
        if not z2 or not all(math.isfinite(v) for v in z2):
            return None
        return float(sst.chi2.sf(sum(z2), len(z2)))

    return clean({"a": a, "b": b, "n_obs": n, "basis": basis, "method": method, "prewhitened": bool(prewhiten), "ar_orders": orders,
                  "lags": lags, "values": vals, "band": band, "p": [pvals[str(k)] for k in lags], "p_adj": [adj[str(k)] for k in lags],
                  "significant": sig, "significant_band": [abs(v) > band if math.isfinite(v) else False for v in vals],
                  "contemporaneous": vals[lags.index(0)], "best_lag": lags[best], "best_value": vals[best],
                  "b_leads_p": haugh(1), "a_leads_p": haugh(-1), "portmanteau_valid": bool(prewhiten),
                  "note": "Bande ±1,96/√n : hors bande = corrélation à ce décalage significative isolément. Les barres pleines "
                          f"sont celles qui résistent à la correction de Benjamini-Hochberg sur les {len(lags)} décalages testés."})


# --- Granger : régressions à la main (échantillon et ordre maîtrisés, covariance robuste) plutôt que `grangercausalitytests`


def _lag_block(v: np.ndarray, p: int) -> np.ndarray:
    """Colonnes v[t−1], …, v[t−p] pour t = p … n−1."""
    n = len(v)
    return np.column_stack([v[p - j: n - j] for j in range(1, p + 1)])


def var_order_bic(y: np.ndarray, x: np.ndarray, maxlag: int) -> int:
    """Ordre du VAR bivarié (y, x) minimisant le critère de Schwarz (BIC), tous les ordres étant comparés sur le MÊME échantillon. Choisi
    sans regarder si x « cause » y : l'ordre n'est donc pas un réglage pêché pour obtenir une p-value."""
    n = len(y)
    t = n - maxlag
    target = np.column_stack([y[maxlag:], x[maxlag:]])
    best, best_p = math.inf, 1
    for p in range(1, maxlag + 1):
        cols = [np.ones(t)]
        cols += [y[maxlag - j: n - j] for j in range(1, p + 1)] + [x[maxlag - j: n - j] for j in range(1, p + 1)]
        z = np.column_stack(cols)
        beta = np.linalg.lstsq(z, target, rcond=None)[0]
        res = target - z @ beta
        sign, logdet = np.linalg.slogdet(res.T @ res / t)
        bic = logdet + (4 * p + 2) * math.log(t) / t if sign > 0 else math.inf
        if bic < best:
            best, best_p = bic, p
    return best_p


def granger_test(effect: np.ndarray, cause: np.ndarray, order: int) -> dict:
    """Le passé de `cause` (order retards) améliore-t-il la prévision linéaire de `effect` au-delà de son propre passé ? Deux statistiques :
    F classique (suppose des erreurs de même variance, ce que les rendements ne font pas) et Wald à covariance HC3, robuste à
    l'hétéroscédasticité. `gain` = part de variance de `effect` expliquée en plus (R² partiel) : la taille de l'effet, que la p-value ne dit pas."""
    n = len(effect)
    t = n - order
    yv = effect[order:]
    restricted = np.column_stack([np.ones(t), _lag_block(effect, order)])
    full = np.column_stack([restricted, _lag_block(cause, order)])
    beta_r = np.linalg.lstsq(restricted, yv, rcond=None)[0]
    ssr_r = float(np.sum((yv - restricted @ beta_r) ** 2))
    beta = np.linalg.lstsq(full, yv, rcond=None)[0]
    res = yv - full @ beta
    ssr_u = float(np.sum(res**2))
    k = full.shape[1]
    f_stat = ((ssr_r - ssr_u) / order) / (ssr_u / (t - k)) if ssr_u > 0 and t > k else float("nan")
    p_f = float(sst.f.sf(f_stat, order, t - k)) if math.isfinite(f_stat) else float("nan")
    xtx_inv = np.linalg.pinv(full.T @ full)
    leverage = np.clip(np.einsum("ij,jk,ik->i", full, xtx_inv, full), 0.0, 1.0 - 1e-8)
    meat = (full * (res**2 / (1.0 - leverage) ** 2)[:, None]).T @ full
    cov = xtx_inv @ meat @ xtx_inv
    sel = slice(1 + order, 1 + 2 * order)
    bc, vc = beta[sel], cov[sel, sel]
    try:
        wald = float(bc @ np.linalg.solve(vc, bc))
        p_w = float(sst.chi2.sf(wald, order)) if wald >= 0 else float("nan")
    except np.linalg.LinAlgError:
        wald, p_w = float("nan"), float("nan")
    return {"order": order, "f": f_stat, "p_classic": p_f, "wald": wald, "p_robust": p_w, "gain": 1.0 - ssr_u / ssr_r if ssr_r > 0 else float("nan")}


def granger(returns: pd.DataFrame, a: str, b: str, maxlag: int = 5, on: str = "returns") -> dict:
    """Test de causalité de Granger dans les deux sens (le passé de x aide-t-il à prédire y au-delà du passé de y ?).
    Granger mesure un pouvoir prédictif linéaire, jamais une causalité économique.

    Verdict : test de Wald robuste à l'ordre BIC du VAR bivarié (un seul test, ordre non pêché). La p-value de Bonferroni sur tous les
    ordres 1…maxlag est donnée en contrôle de sensibilité. `on="abs"` teste la volatilité (|rendement|) au lieu du rendement."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    if on not in GRANGER_ON:
        raise ValueError("série inconnue (rendements ou rendements absolus)")
    data = (returns[[a, b]].abs() if on == "abs" else returns[[a, b]]).dropna()
    n = len(data)
    maxlag = int(min(max(1, maxlag), max(1, n // 20), 10))
    va, vb = data[a].to_numpy(dtype=float), data[b].to_numpy(dtype=float)
    order = var_order_bic(va, vb, maxlag)

    def one_way(cause: str, effect: str, cv: np.ndarray, ev: np.ndarray) -> dict:
        tests = [granger_test(ev, cv, p) for p in range(1, maxlag + 1)]
        robust = {t["order"]: t["p_robust"] for t in tests}
        finite = {k: v for k, v in robust.items() if math.isfinite(v)}
        at = tests[order - 1]
        best_k = min(finite, key=finite.get) if finite else order
        p_min = finite.get(best_k, float("nan"))
        return {"cause": cause, "effect": effect, "order": order, "p_by_lag": {t["order"]: t["p_classic"] for t in tests},
                "p_by_lag_robust": robust, "best_lag": int(best_k), "p_min": p_min, "p_bonferroni": min(1.0, p_min * maxlag),
                "p_order": at["p_robust"], "p_order_classic": at["p_classic"], "wald_order": at["wald"], "gain_order": at["gain"],
                "predictive": bool(math.isfinite(at["p_robust"]) and at["p_robust"] < ALPHA)}

    nonstationary = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, v in ((a, va), (b, vb)):
            try:
                if len(v) > 20 and adfuller(v, autolag="AIC")[1] >= ALPHA:
                    nonstationary.append(name)
            except Exception as exc:  # noqa: BLE001 -- série dégénérée : pas de verdict de stationnarité
                _log.debug("ADF impossible : %s", exc)
    return clean({"a": a, "b": b, "n_obs": n, "maxlag": maxlag, "on": on, "order": order, "nonstationary": nonstationary,
                  "a_to_b": one_way(a, b, va, vb), "b_to_a": one_way(b, a, vb, va)})


GRANGER_SCOPES = ("conditional", "pairwise")


def _var_design(arr: np.ndarray, p: int, rows_from: int) -> tuple[np.ndarray, np.ndarray]:
    """VAR(p) sur toutes les colonnes de `arr` (n×k) : cibles y[t] et régresseurs [1, y[t−1], …, y[t−p]] pour t = rows_from … n−1."""
    n = arr.shape[0]
    z = np.column_stack([np.ones(n - rows_from)] + [arr[rows_from - j: n - j] for j in range(1, p + 1)])
    return arr[rows_from:], z


def _granger_conditional(arr: np.ndarray, cols: list[str], maxlag: int) -> tuple[int, dict[tuple[int, int], dict]]:
    """Causalité de Granger CONDITIONNELLE : chaque effet est régressé sur les retards de TOUS les actifs, et chaque cause est jugée par
    un Wald robuste (HC3) sur l'ensemble de ses retards. Un lien indirect (A → B → C) n'apparaît plus comme A → C : ce qui reste est
    l'apport propre de chaque actif, les autres étant connus. Ordre du VAR complet choisi par BIC."""
    n, k = arr.shape
    t_full = n - maxlag
    best, order = math.inf, 1
    for p in range(1, maxlag + 1):
        target, z = _var_design(arr, p, maxlag)
        beta = np.linalg.lstsq(z, target, rcond=None)[0]
        res = target - z @ beta
        sign, logdet = np.linalg.slogdet(res.T @ res / t_full)
        bic = logdet + (k * k * p + k) * math.log(t_full) / t_full if sign > 0 else math.inf
        if bic < best:
            best, order = bic, p
    target, z = _var_design(arr, order, order)
    beta = np.linalg.lstsq(z, target, rcond=None)[0]
    res = target - z @ beta
    zz_inv = np.linalg.pinv(z.T @ z)
    leverage = np.clip(np.einsum("ij,jk,ik->i", z, zz_inv, z), 0.0, 1.0 - 1e-8)
    out: dict[tuple[int, int], dict] = {}
    for e in range(k):
        w = res[:, e] ** 2 / (1.0 - leverage) ** 2
        cov = zz_inv @ ((z * w[:, None]).T @ z) @ zz_inv
        for c in range(k):
            if c == e:
                continue
            cols_c = [1 + j * k + c for j in range(order)]
            bc, vc = beta[cols_c, e], cov[np.ix_(cols_c, cols_c)]
            try:
                wald = float(bc @ np.linalg.solve(vc, bc))
                p_w = float(sst.chi2.sf(wald, order)) if wald >= 0 else float("nan")
            except np.linalg.LinAlgError:
                wald, p_w = float("nan"), float("nan")
            out[(c, e)] = {"order": order, "wald": wald, "p_robust": p_w, "gain": None}
    return order, out


def _conditional_gain(arr: np.ndarray, cause: int, effect: int, order: int) -> float:
    """Part de variance de l'effet expliquée en plus par les retards de la cause, les autres actifs étant connus (R² partiel)."""
    target, z = _var_design(arr, order, order)
    y = target[:, effect]
    drop = {1 + j * arr.shape[1] + cause for j in range(order)}
    z_r = z[:, [i for i in range(z.shape[1]) if i not in drop]]
    ssr_u = float(np.sum((y - z @ np.linalg.lstsq(z, y, rcond=None)[0]) ** 2))
    ssr_r = float(np.sum((y - z_r @ np.linalg.lstsq(z_r, y, rcond=None)[0]) ** 2))
    return 1.0 - ssr_u / ssr_r if ssr_r > 0 else float("nan")


def granger_matrix(returns: pd.DataFrame, maxlag: int = 5, on: str = "returns", scope: str = "conditional") -> dict:
    """« Qui mène qui » : le test de Granger de chaque couple ordonné (cause → effet) de la sélection, p-values corrigées de
    Benjamini-Hochberg sur TOUS les sens testés (avec 10 actifs, 90 tests : des p brutes < 5 % y sont attendues par hasard).

    `scope="conditional"` (défaut) : chaque effet est expliqué par le passé de tous les actifs à la fois (liens directs seulement) ;
    `pairwise` : un couple à la fois, où une chaîne A → B → C se lit aussi A → C."""
    if on not in GRANGER_ON:
        raise ValueError("série inconnue (rendements ou rendements absolus)")
    if scope not in GRANGER_SCOPES:
        raise ValueError("portée inconnue (conditionnelle ou par couple)")
    cols = list(returns.columns)
    k = len(cols)
    if k < 2:
        raise ValueError("Choisis au moins deux actifs.")
    if k * (k - 1) > MAX_PAIR_TESTS:
        raise ValueError(f"Au plus {int((1 + math.sqrt(1 + 4 * MAX_PAIR_TESTS)) // 2)} actifs pour la matrice de causalité "
                         f"({k * (k - 1)} tests demandés, {MAX_PAIR_TESTS} au maximum).")
    data = (returns.abs() if on == "abs" else returns).dropna()
    n = len(data)
    maxlag = int(min(max(1, maxlag), max(1, n // 20), 10))
    arr = data.to_numpy(dtype=float)
    info: dict[tuple[int, int], dict] = {}
    if scope == "conditional":
        maxlag = int(max(1, min(maxlag, (n // 4 - 1) // k)))          # au plus un régresseur pour quatre observations
        if k * maxlag + 1 >= n // 3:
            raise ValueError("Pas assez d'observations pour ce nombre d'actifs : réduis la sélection ou allonge la période.")
        order, info = _granger_conditional(arr, cols, maxlag)
    else:
        for i in range(k):
            for j in range(i + 1, k):
                order_ij = var_order_bic(arr[:, i], arr[:, j], maxlag)
                for c, e in ((i, j), (j, i)):
                    info[(c, e)] = granger_test(arr[:, e], arr[:, c], order_ij)
        order = None
    raw = {f"{c}|{e}": t["p_robust"] for (c, e), t in info.items()}
    adj = _bh(raw)
    p_adj = [[None] * k for _ in range(k)]
    sig = [[None] * k for _ in range(k)]
    gain = [[None] * k for _ in range(k)]
    edges = []
    for (c, e), t in info.items():
        q = adj.get(f"{c}|{e}")
        p_adj[c][e] = q
        sig[c][e] = None if q is None else bool(q < ALPHA)
        if sig[c][e]:
            g = _conditional_gain(arr, c, e, t["order"]) if scope == "conditional" else t["gain"]
            gain[c][e] = g
            edges.append({"cause": cols[c], "effect": cols[e], "order": t["order"], "p": t["p_robust"], "p_adj": q, "gain": g})
    edges.sort(key=lambda r: (r["p_adj"], -(r["gain"] or 0.0)))
    leaders = []
    for c in range(k):
        out_n = sum(1 for e in range(k) if sig[c][e])
        in_n = sum(1 for e in range(k) if sig[e][c])
        leaders.append({"symbol": cols[c], "out": out_n, "in": in_n, "net": out_n - in_n})
    leaders.sort(key=lambda r: (-r["net"], -r["out"]))
    return clean({"labels": cols, "on": on, "scope": scope, "order": order, "maxlag": maxlag, "n_obs": n, "n_tests": len(raw),
                  "p_adj": p_adj, "significant": sig, "gain": gain, "edges": edges[:30], "n_edges": len(edges), "leaders": leaders,
                  "note": "Ligne = cause, colonne = effet. Décalage d'horloge : un marché qui clôture avant l'autre (Tokyo, New York) "
                          "« mène » mécaniquement d'un jour sans que ce soit une information exploitable."})


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
        "a": a, "b": b, "n_obs": len(levels), "test_stat": float(stat), "p_value": float(p),
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
    return clean({"n_obs": len(z), "n_assets": int(z.shape[1]), "explained": ratio[:max(nc, 10)], "cumulative": cum[:max(nc, 10)],
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
    return clean({"a": a, "b": b, "q": q, "n_obs": len(returns), "pearson": float(ra.corr(rb)),
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
    out: dict = {"n_obs": len(r), "mean_all": overall}
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
        rows.append({"key": key, "group": key.split(":", 1)[1], "kind": key.split(":", 1)[0], "n": len(g),
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
                              "n_turn": len(turn["turn"])} if turn is not None and len(turn["turn"]) > 5 else None)
    out["note"] = (f"{len(rows)} groupes testés, chacun contre tout le reste ; seule la p-value corrigée (Benjamini-Hochberg) "
                   "autorise à parler d'effet. Un groupe très atypique tire la moyenne du « reste » et fait paraître les autres "
                   "plus faibles : lire d'abord le test d'ensemble et le groupe le plus extrême.")
    return clean(out)
