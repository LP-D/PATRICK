"""Tests de significativité d'un groupe d'événements. Un t-test naïf ne suffit pas.

Pourquoi : les annonces d'une même semaine partagent les mêmes chocs de marché (corrélation transversale) et la variance
d'un titre monte le jour de l'annonce (augmentation de variance liée à l'événement). Un t-test sur les CAR traite N événements
comme N expériences indépendantes à variance connue : ses t-stats sont gonflés. Tests fournis :

- `cross` : t-test naïf (référence seulement, à ne pas croire) ;
- `patell` : CAR standardisés par leur écart-type d'estimation (Patell 1976) ; sensible à l'augmentation de variance ;
- `bmp` (DÉFAUT) : Boehmer-Musumeci-Poulsen (1991), variance transversale des CAR standardisés : robuste à l'augmentation de variance ;
- `kp` : BMP corrigé de la corrélation moyenne entre événements (Kolari-Pynnönen 2010) ; r̄ estimé sur les résidus d'estimation
  alignés par jours ouvrés ;
- `corrado` : test de rangs (Corrado 1989, étendu aux fenêtres multi-jours par Campbell-Wasley 1993) ; sans hypothèse de loi ;
- `sign` : test des signes généralisé (Cowan 1992) : la part de CAR positifs est comparée à celle observée en estimation, pas à 0,5 ;
- `bootstrap` : rééchantillonnage par BLOCS DE DATES (semaines de calendrier de J0) ; garde la dépendance intra-semaine.

Défaut recommandé : BMP, avec bootstrap par blocs en contrôle. `abs_move_test` répond à une autre question : le titre bouge-t-il
PLUS que d'habitude, quel que soit le sens (la direction d'un résultat est inconnue ex ante, les hausses et baisses s'annulent
dans un CAAR).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings.engine import arr, car_variance, window_sum

MIN_EVENTS_TEST = 4


def week_key(day0: str) -> str:
    iso = pd.Timestamp(day0).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def window_table(rows: list[dict], a: int, b: int) -> pd.DataFrame:
    """Une ligne par événement exploitable sur la fenêtre [a, b] : car, variance, car standardisé, dof, semaine de J0."""
    recs = []
    for i, r in enumerate(rows):
        car = window_sum(arr(r, "ar"), a, b)
        var = car_variance(r, a, b)
        if not (np.isfinite(car) and np.isfinite(var) and var > 0):
            continue
        recs.append({"i": i, "symbol": r["symbol"], "day0": r["day0"], "week": week_key(r["day0"]), "car": car, "var": var,
                     "scar": car / np.sqrt(var), "dof": max(r["n_est"] - r["k"], 3)})
    return pd.DataFrame(recs, columns=["i", "symbol", "day0", "week", "car", "var", "scar", "dof"])


def _result(stat: float, p: float, **extra) -> dict:
    return {"stat": None if not np.isfinite(stat) else float(stat), "p": None if not np.isfinite(p) else float(p), **extra}


def cross_sectional(tab: pd.DataFrame) -> dict:
    n = len(tab)
    se = tab["car"].std(ddof=1) / np.sqrt(n)
    t = tab["car"].mean() / se if se > 0 else np.nan
    return _result(t, 2 * stats.t.sf(abs(t), n - 1) if np.isfinite(t) else np.nan)


def patell(tab: pd.DataFrame) -> dict:
    var_scar = (tab["dof"] / (tab["dof"] - 2)).sum()
    z = tab["scar"].sum() / np.sqrt(var_scar)
    return _result(z, 2 * stats.norm.sf(abs(z)))


def bmp(tab: pd.DataFrame) -> dict:
    n = len(tab)
    sd = tab["scar"].std(ddof=1)
    t = tab["scar"].mean() / (sd / np.sqrt(n)) if sd > 0 else np.nan
    return _result(t, 2 * stats.t.sf(abs(t), n - 1) if np.isfinite(t) else np.nan)


def kolari_pynnonen(tab: pd.DataFrame, rbar: float) -> dict:
    base = bmp(tab)
    n = len(tab)
    r = max(rbar, 0.0)
    if base["stat"] is None:
        return _result(np.nan, np.nan, rbar=rbar)
    t = base["stat"] * np.sqrt((1 - r) / (1 + (n - 1) * r))
    return _result(t, 2 * stats.t.sf(abs(t), n - 1), rbar=float(r))


def mean_pairwise_correlation(rows: list[dict], idx: list[int], max_events: int = 300) -> float:
    """Corrélation moyenne des résidus d'estimation STANDARDISÉS entre événements, alignés par jours ouvrés (deux annonces d'une
    même semaine partagent la majorité de leur fenêtre d'estimation). Calculé sur au plus `max_events` événements."""
    if len(idx) < 3:
        return 0.0
    rng = np.random.default_rng(0)
    pick = list(idx) if len(idx) <= max_events else list(rng.choice(idx, max_events, replace=False))
    base = min(pd.Timestamp(rows[i]["day0"]) for i in pick)
    shifts = [int(np.busday_count(base.date(), pd.Timestamp(rows[i]["day0"]).date())) for i in pick]
    width = max(len(rows[i]["resid_est"]) for i in pick)
    total = width + max(shifts) + 1
    mat = np.full((total, len(pick)), np.nan)
    for c, (i, s) in enumerate(zip(pick, shifts)):
        res = arr(rows[i], "resid_est") / max(rows[i]["sigma"], 1e-12)
        mat[s:s + len(res), c] = res
    corr = pd.DataFrame(mat).corr(min_periods=60).to_numpy()
    off = corr[~np.eye(len(pick), dtype=bool)]
    # Deux annonces éloignées de plus d'un an n'ont aucune fenêtre commune : leur corrélation (inconnue) vaut 0 dans la moyenne. Ne moyenner
    # que les paires qui se chevauchent surestimerait r̄ de l'inverse de leur part, et la correction de KP écraserait tout.
    return float(np.nansum(off) / off.size) if off.size else 0.0


def _rolling_sum(x: np.ndarray, length: int) -> np.ndarray:
    ok = np.isfinite(x)
    if length == 1:
        return x[ok]
    clean = np.where(ok, x, 0.0)
    csum = np.concatenate([[0.0], np.cumsum(clean)])
    cnt = np.concatenate([[0], np.cumsum(ok)])
    sums = csum[length:] - csum[:-length]
    full = (cnt[length:] - cnt[:-length]) == length
    return sums[full]


MAX_SIGN_WINDOW = 10


def generalized_sign(tab: pd.DataFrame, rows: list[dict], a: int, b: int) -> dict:
    length = b - a + 1
    if length > MAX_SIGN_WINDOW:
        # la fréquence de référence de CAR positifs se lit sur des fenêtres glissantes de l'estimation : au-delà de ~10 séances elles se
        # recouvrent presque toutes, trouent sur les autres annonces et donnent une fréquence instable (p absurdes constatés sur [+2, +60])
        return _result(np.nan, np.nan, note="fenêtre trop longue pour le test des signes")
    shares = []
    for i in tab["i"]:
        s = _rolling_sum(arr(rows[i], "resid_est"), length)
        if len(s) >= 30:
            shares.append(float((s > 0).mean()))
    p_hat = float(np.mean(shares)) if shares else 0.5
    n = len(tab)
    w = int((tab["car"] > 0).sum())
    denom = np.sqrt(n * p_hat * (1 - p_hat))
    z = (w - n * p_hat) / denom if denom > 0 else np.nan
    return _result(z, 2 * stats.norm.sf(abs(z)) if np.isfinite(z) else np.nan, p_expected=p_hat, n_positive=w)


def corrado(tab: pd.DataFrame, rows: list[dict], a: int, b: int) -> dict:
    """Test de rangs (Campbell-Wasley) : rang de chaque jour de la fenêtre parmi les résidus d'estimation du même événement,
    écart moyen à 0,5 rapporté à l'écart-type observé sur la fenêtre d'estimation (même agrégation sur L jours)."""
    length = b - a + 1
    sel = list(tab["i"])
    if len(sel) < MIN_EVENTS_TEST:
        return _result(np.nan, np.nan)
    width = max(len(rows[i]["resid_est"]) for i in sel)
    est = np.full((len(sel), width), np.nan)
    win = np.full((len(sel), length), np.nan)
    ar_lo = a - (-10)
    for r, i in enumerate(sel):
        res = arr(rows[i], "resid_est")
        est[r, :len(res)] = res
        win[r] = arr(rows[i], "ar")[ar_lo:ar_lo + length]
    comb = np.concatenate([est, win], axis=1)
    u = np.full_like(comb, np.nan)
    for r in range(comb.shape[0]):
        ok = np.isfinite(comb[r])
        if ok.sum() < 30:
            continue
        ranks = stats.rankdata(comb[r, ok])
        u[r, ok] = ranks / (ok.sum() + 1) - 0.5
    ubar = np.nanmean(u, axis=0)
    est_part = ubar[:width]
    if length > 1:
        kern = np.ones(length) / length
        valid = np.isfinite(est_part)
        roll = np.convolve(np.where(valid, est_part, 0.0), kern, mode="valid")
        cnt = np.convolve(valid.astype(float), kern, mode="valid")
        roll = roll[cnt > 0.999]
    else:
        roll = est_part[np.isfinite(est_part)]
    s = np.std(roll, ddof=1) if len(roll) > 10 else np.nan
    z = np.nanmean(ubar[width:]) / s if s and np.isfinite(s) and s > 0 else np.nan
    return _result(z, 2 * stats.norm.sf(abs(z)) if np.isfinite(z) else np.nan)


def block_bootstrap(tab: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Moyenne des CAR rééchantillonnée par SEMAINES de J0 (blocs), recentrée sous H0 : p bilatérale et intervalle à 95 %."""
    groups = [g["car"].to_numpy() for _, g in tab.groupby("week")]
    if len(groups) < 3:
        return _result(np.nan, np.nan, ci=[None, None], n_blocks=len(groups))
    rng = np.random.default_rng(seed)
    sums = np.array([g.sum() for g in groups])
    sizes = np.array([len(g) for g in groups])
    k = len(groups)
    obs = sums.sum() / sizes.sum()
    draws = rng.integers(0, k, size=(n_boot, k))
    boot = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    centered = boot - obs
    p = 2 * min((centered >= obs).mean(), (centered <= obs).mean())
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return _result(obs / boot.std(ddof=1) if boot.std() > 0 else np.nan, min(max(p, 1.0 / n_boot), 1.0),
                   ci=[float(lo), float(hi)], n_blocks=k)


def run_tests(rows: list[dict], a: int, b: int, n_boot: int = 2000, winsor: float = 0.0) -> dict:
    """Moyenne des CAR[a, b] et tous les tests, sur les événements exploitables. `winsor` rogne les CAR extrêmes (moyenne
    affichée seulement : les tests restent calculés sur les valeurs brutes)."""
    tab = window_table(rows, a, b)
    n = len(tab)
    out: dict = {"window": [a, b], "n": n, "n_total": len(rows)}
    if n < MIN_EVENTS_TEST:
        return {**out, "caar": float(tab["car"].mean()) if n else None, "tests": {}, "note": "N insuffisant pour tester"}
    cars = tab["car"].to_numpy()
    shown = cars
    if winsor > 0:
        lo, hi = np.quantile(cars, [winsor, 1 - winsor])
        shown = np.clip(cars, lo, hi)
    rbar = mean_pairwise_correlation(rows, list(tab["i"]))
    out.update({
        "caar": float(shown.mean()), "median_car": float(np.median(cars)), "sd_car": float(cars.std(ddof=1)),
        "share_positive": float((cars > 0).mean()), "rbar": rbar, "n_weeks": int(tab["week"].nunique()),
        "tests": {"cross": cross_sectional(tab), "patell": patell(tab), "bmp": bmp(tab),
                  "kp": kolari_pynnonen(tab, rbar), "corrado": corrado(tab, rows, a, b),
                  "sign": generalized_sign(tab, rows, a, b), "bootstrap": block_bootstrap(tab, n_boot)},
    })
    return out


def abs_move_test(rows: list[dict], a: int, b: int) -> dict:
    """Le titre bouge-t-il plus que d'habitude, quel que soit le sens ? Deux lectures : rang du |CAR| parmi les |sommes sur L
    jours| de ses propres résidus d'estimation (loi uniforme sous H0, sans hypothèse de queues), et variance du CAR standardisé
    (E[scar^2] = 1 sous H0 ; BMP-style, robuste à la variance transversale)."""
    tab = window_table(rows, a, b)
    length = b - a + 1
    pct = []
    for i, car in zip(tab["i"], tab["car"]):
        placebo = np.abs(_rolling_sum(arr(rows[i], "resid_est"), length))
        if len(placebo) >= 30:
            pct.append(float((placebo < abs(car)).mean() + 0.5 * (placebo == abs(car)).mean()))
    m = len(pct)
    out = {"window": [a, b], "n": len(tab), "mean_percentile": float(np.mean(pct)) if m else None, "p_rank": None, "mean_z2": None,
           "p_var": None}
    if m >= MIN_EVENTS_TEST:
        z = (np.mean(pct) - 0.5) / np.sqrt(1 / (12 * m))
        out["p_rank"] = float(stats.norm.sf(z))
    if len(tab) >= MIN_EVENTS_TEST:
        z2 = tab["scar"].to_numpy() ** 2
        sd = z2.std(ddof=1)
        out["mean_z2"] = float(z2.mean())
        if sd > 0:
            out["p_var"] = float(stats.t.sf((z2.mean() - 1) / (sd / np.sqrt(len(z2))), len(z2) - 1))
    return out
