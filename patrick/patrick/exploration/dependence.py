"""Dépendance NON linéaire entre séries (page Exploration) : corrélation de distance et information mutuelle.

La corrélation de Pearson ne voit que la part linéaire d'un lien : deux rendements peuvent avoir une corrélation nulle et pourtant
grossir ensemble (volatilité commune) ou se compenser en U. Deux mesures lèvent cet angle mort :

* la corrélation de distance (Székely, Rizzo, Bakirov 2007) vaut 0 si et seulement si les séries sont indépendantes, quelle que soit la
  forme du lien ; version corrigée du biais (U-centrage) pour que le bruit d'échantillon ne la gonfle pas ;
* l'information mutuelle (estimateur des k plus proches voisins de Kraskov, Stögbauer, Grassberger 2004), calculée sur les RANGS (scores normaux) : elle
  ne dépend alors plus des queues épaisses des rendements, et sa loi sous indépendance ne dépend plus que de n. Ramenée à l'échelle de
  Linfoot, sqrt(1 − exp(−2·IM)), elle vaut |ρ| pour un couple gaussien et se lit comme une corrélation.

Honnêteté statistique : sur des séries financières, les grappes de volatilité rendent le test d'indépendance « iid » trop optimiste. La
matrice utilise ce test (seul calculable pour des dizaines de couples) et le dit ; la vue d'un couple, elle, bâtit sa loi nulle par
DÉCALAGES CIRCULAIRES de l'un des deux rendements : chaque série garde sa propre dynamique (autocorrélation, grappes de volatilité),
seul le lien entre les deux est cassé. Le calcul est en O(n²) : au plus MATRIX_MAX_OBS (matrice) ou PAIR_MAX_OBS (couple) dernières
observations, ce que les résultats indiquent (`n_used`).
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import fft as sfft
from scipy import stats as sst
from scipy.spatial import cKDTree
from scipy.special import digamma

from patrick.exploration.studies import (
    ALPHA,
    MAX_PAIR_TESTS,
    _bh,
    aligned_lag,
    clean,
    cluster_order,
)

MATRIX_MAX_OBS = 2000
PAIR_MAX_OBS = 1500
MAX_LAG = 20
KSG_NEIGHBORS = 3
MI_NULL_DRAWS = 200            # tirages de la loi nulle de la matrice (loi normale ajustée ensuite)
MI_PAIR_NULL_DRAWS = 400       # tirages par décalage circulaire pour un couple (p-values empiriques)
MEASURES = ("dcor", "mi")
_SEED = 20261024


# --------------------------------------------------------------------------- information mutuelle


def normal_scores(x: np.ndarray) -> np.ndarray:
    """Rangs moyens passés à la loi normale (« scores normaux »). Invariance aux transformations monotones, et pas de bord dur comme sur
    des rangs uniformes, où l'estimateur des voisins sous-estime l'information."""
    return sst.norm.ppf((sst.rankdata(x, method="average") - 0.5) / len(x))


def _count_within(v: np.ndarray, eps: np.ndarray) -> np.ndarray:
    """Pour chaque i : nombre de j ≠ i avec |v_j − v_i| < eps_i (intervalle ouvert, en O(n log n))."""
    vs = np.sort(v)
    inside = np.searchsorted(vs, v + eps, side="left") - np.searchsorted(vs, v - eps, side="right")
    return np.maximum(inside - 1, 0)                     # le point lui-même est toujours à l'intérieur


def ksg_mutual_information(x: np.ndarray, y: np.ndarray, k: int = KSG_NEIGHBORS) -> float:
    """Information mutuelle (nats) par l'algorithme 1 de Kraskov-Stögbauer-Grassberger : distance du k-ième voisin en norme max dans le
    plan joint, puis comptage des voisins dans chaque marginale. Un bruit de 1e-7 (graine fixe) départage les ex æquo (rendements nuls)."""
    n = len(x)
    rng = np.random.default_rng(_SEED)
    pts = np.column_stack([x, y]) + rng.uniform(-1e-7, 1e-7, size=(n, 2))
    dist, _ = cKDTree(pts).query(pts, k=k + 1, p=np.inf)
    eps = dist[:, -1]
    nx = _count_within(pts[:, 0], eps)
    ny = _count_within(pts[:, 1], eps)
    return float(digamma(k) + digamma(n) - np.mean(digamma(nx + 1) + digamma(ny + 1)))


def linfoot(mi: float) -> float:
    """Coefficient d'information de Linfoot : sqrt(1 − exp(−2·IM)), l'équivalent d'une corrélation (|ρ| si le couple est gaussien)."""
    return math.sqrt(1.0 - math.exp(-2.0 * max(mi, 0.0)))


@lru_cache(maxsize=32)
def _mi_null_moments(n: int, draws: int = MI_NULL_DRAWS) -> tuple[float, float]:
    """Moyenne et écart-type de l'information mutuelle de deux séries indépendantes de n points. Sur des rangs, cette loi ne dépend que
    de n : un seul tirage (permutations aléatoires d'une grille) sert à tous les couples d'une matrice."""
    rng = np.random.default_rng(_SEED + n)
    grid = sst.norm.ppf((np.arange(n) + 0.5) / n)
    vals = np.array([ksg_mutual_information(grid, grid[rng.permutation(n)]) for _ in range(draws)])
    return float(vals.mean()), float(vals.std(ddof=1))


# --------------------------------------------------------------------------- corrélation de distance


def _row_sums_abs(x: np.ndarray) -> np.ndarray:
    """Σ_j |x_i − x_j| pour tout i, en O(n log n) grâce au tri."""
    n = len(x)
    order = np.argsort(x, kind="stable")
    xs = x[order]
    cs = np.cumsum(xs)
    sums_sorted = xs * (2 * np.arange(n) + 2 - n) + cs[-1] - 2.0 * cs
    out = np.empty(n)
    out[order] = sums_sorted
    return out


def ucenter(x: np.ndarray) -> np.ndarray:
    """Matrice des distances |x_i − x_j| « U-centrée » (Székely-Rizzo 2014) : diagonale nulle, le produit scalaire de deux telles
    matrices estime la covariance de distance SANS biais (positive ou négative selon le hasard, nulle en moyenne sous indépendance)."""
    n = len(x)
    d = np.abs(x[:, None] - x[None, :])
    r = _row_sums_abs(x)
    d -= (r[:, None] + r[None, :]) / (n - 2)
    d += r.sum() / ((n - 1) * (n - 2))
    np.fill_diagonal(d, 0.0)
    return d


def _r_star(a: np.ndarray, b: np.ndarray, n: int, vaa: float | None = None, vbb: float | None = None) -> float:
    """Corrélation de distance corrigée du biais, sur l'échelle au CARRÉ (R*, de -1 à 1). `vaa`/`vbb` : variances de distance déjà connues."""
    scale = n * (n - 3)
    vab = float(np.vdot(a, b)) / scale
    vaa = float(np.vdot(a, a)) / scale if vaa is None else vaa
    vbb = float(np.vdot(b, b)) / scale if vbb is None else vbb
    denom = math.sqrt(vaa * vbb) if vaa > 0 and vbb > 0 else 0.0
    return vab / denom if denom > 0 else float("nan")


def _dcor_value(r_star: float) -> float:
    """Échelle de la corrélation (comparable à |ρ|) : racine de R* ramené à zéro s'il est négatif (bruit)."""
    return math.sqrt(r_star) if r_star > 0 else 0.0


def dcor_ttest_p(r_star: float, n: int) -> float:
    """Test de Székely-Rizzo (2013) sur R* : T = √(v−1)·R*/√(1−R*²) suit une loi de Student à v−1 degrés (v = n(n−3)/2) sous indépendance
    de séries iid. Unilatéral : seule une dépendance positive est mesurable."""
    if not math.isfinite(r_star):
        return float("nan")
    v = n * (n - 3) / 2.0
    r = min(max(r_star, -0.999999), 0.999999)
    return float(sst.t.sf(math.sqrt(v - 1.0) * r / math.sqrt(1.0 - r * r), v - 1.0))


def _dcov_gram(x: np.ndarray, block: int = 64) -> np.ndarray:
    """Matrice (k×k) des covariances de distance corrigées V*[i, j] pour les k colonnes de `x` (n×k), par blocs de lignes : on ne
    garde jamais k matrices n×n en mémoire (40 actifs × 2 000 points = 1,3 Go sinon)."""
    n, k = x.shape
    rows = np.column_stack([_row_sums_abs(x[:, c]) for c in range(k)])
    tot = rows.sum(axis=0)
    gram = np.zeros((k, k))
    for r0 in range(0, n, block):
        r1 = min(n, r0 + block)
        b = r1 - r0
        stack = np.empty((k, b * n))
        for c in range(k):
            xc = x[:, c]
            u = np.abs(xc[r0:r1, None] - xc[None, :])
            u -= (rows[r0:r1, c][:, None] + rows[:, c][None, :]) / (n - 2)
            u += tot[c] / ((n - 1) * (n - 2))
            u[np.arange(b), np.arange(r0, r1)] = 0.0
            stack[c] = u.ravel()
        gram += stack @ stack.T
    return gram / (n * (n - 3))


# --------------------------------------------------------------------------- matrice


def _top_pairs(cols, dep, pearson, q, key, limit=5):
    out = []
    n = len(cols)
    for i in range(n):
        for j in range(i + 1, n):
            out.append({"a": cols[i], "b": cols[j], "value": float(dep[i, j]), "pearson": float(pearson[i, j]),
                        "gap": float(dep[i, j] - abs(pearson[i, j])), "p_adj": q.get((i, j))})
    if key == "gap":                                      # seulement les couples significatifs où la mesure dépasse |ρ|
        out = [r for r in out if r["gap"] > 0 and r["p_adj"] is not None and r["p_adj"] < ALPHA]
    out.sort(key=lambda r: -r[key])
    return out[:limit]


def dependence_matrix(returns: pd.DataFrame, measure: str = "dcor", cluster: bool = True) -> dict:
    """Matrice de dépendance (corrélation de distance ou coefficient d'information de Linfoot) de tous les couples, à côté de Pearson.
    `gap` = dépendance − |ρ| : ce que la corrélation linéaire ne voit pas (volatilité commune, liens en U...)."""
    if measure not in MEASURES:
        raise ValueError("mesure inconnue (dcor ou mi)")
    if returns.shape[1] < 2:
        raise ValueError("Choisis au moins deux actifs.")
    win = returns.iloc[-MATRIX_MAX_OBS:]
    n = len(win)
    cols = list(win.columns)
    k = len(cols)
    arr = win.to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        pearson = np.corrcoef(arr.T)
    raw: dict[tuple[int, int], float] = {}
    dep = np.zeros((k, k))
    if measure == "dcor":
        gram = _dcov_gram(arr)
        d = np.sqrt(np.diag(gram))
        with np.errstate(invalid="ignore", divide="ignore"):
            rstar = gram / np.outer(d, d)
        for i in range(k):
            for j in range(k):
                dep[i, j] = 1.0 if i == j else _dcor_value(float(rstar[i, j]))
        for i in range(k):
            for j in range(i + 1, k):
                raw[(i, j)] = dcor_ttest_p(float(rstar[i, j]), n)
    else:
        ranks = np.column_stack([normal_scores(arr[:, c]) for c in range(k)])
        mu, sd = _mi_null_moments(n)
        for i in range(k):
            dep[i, i] = 1.0
            for j in range(i + 1, k):
                mi = ksg_mutual_information(ranks[:, i], ranks[:, j])
                dep[i, j] = dep[j, i] = linfoot(mi)
                raw[(i, j)] = float(sst.norm.sf((mi - mu) / sd)) if sd > 0 else float("nan")
    keyed = {f"{i}|{j}": p for (i, j), p in raw.items()}
    adj = _bh(keyed) if len(keyed) <= MAX_PAIR_TESTS else {}
    q = {(i, j): adj.get(f"{i}|{j}") for (i, j) in raw}
    sig = [[None] * k for _ in range(k)]
    for (i, j), val in q.items():
        sig[i][j] = sig[j][i] = (None if val is None else bool(val < ALPHA))
    order = cluster_order(pd.DataFrame(dep, index=cols, columns=cols)) if cluster else cols
    pos = [cols.index(c) for c in order]
    take = np.ix_(pos, pos)
    out = {
        "measure": measure, "labels": order, "matrix": dep[take], "pearson": pearson[take],
        "significant": [[sig[i][j] for j in pos] for i in pos] if q and adj else None,
        "n_obs": len(returns), "n_used": n, "windowed": n < len(returns), "n_tests": len(raw),
        "mean_dependence": float(np.nanmean(dep[np.triu_indices(k, 1)])),
        "mean_abs_pearson": float(np.nanmean(np.abs(pearson[np.triu_indices(k, 1)]))),
        "strongest": _top_pairs(cols, dep, pearson, q, "value"),
        "hidden": _top_pairs(cols, dep, pearson, q, "gap"),
    }
    return clean(out)


# --------------------------------------------------------------------------- un couple, décalage par décalage


def _circular_dcor_null(a0: np.ndarray, b0: np.ndarray, smin: int) -> np.ndarray:
    """R* de (x, y décalé circulairement de s) pour TOUS les décalages s, en un seul produit de FFT 2D : le décalage circulaire de y
    permute simultanément lignes et colonnes de sa matrice U-centrée, donc R*(s) = Σ_ij A[i,j]·B[i+s, j+s] / normalisation, c'est-à-dire
    la diagonale de la corrélation croisée circulaire de A et B."""
    n = a0.shape[0]
    cross = sfft.irfft2(np.conj(sfft.rfft2(a0, workers=-1)) * sfft.rfft2(b0, workers=-1), s=a0.shape, workers=-1)
    diag = cross[np.arange(n), np.arange(n)] / (n * (n - 3))
    vaa = float(np.vdot(a0, a0)) / (n * (n - 3))
    vbb = float(np.vdot(b0, b0)) / (n * (n - 3))
    shifts = np.arange(smin, n - smin + 1)
    return diag[shifts] / math.sqrt(vaa * vbb)


def _perm_p(observed: float, null: np.ndarray) -> float:
    """p-value unilatérale d'une statistique contre sa loi nulle simulée : (1 + nb de tirages ≥ observé) / (1 + tirages). Si AUCUN tirage ne
    l'atteint, la fréquence ne dit que « p < 1/(1+tirages) » ; ce plancher interdirait à Benjamini-Hochberg de jamais rejeter parmi
    plusieurs décalages (le plus petit p admissible, 1/401, dépasse 0,05/21) : la queue est alors extrapolée par une loi normale ajustée
    sur le nul, sans jamais dépasser le plancher."""
    if not math.isfinite(observed):
        return float("nan")
    hits = int(np.sum(null >= observed))
    floor = 1.0 / (1 + len(null))
    if hits > 0:
        return (1 + hits) / (1 + len(null))
    sd = float(np.std(null, ddof=1))
    if sd <= 0:
        return floor
    return min(floor, max(float(sst.norm.sf((observed - float(np.mean(null))) / sd)), 1e-300))


def _pair_summary(a, b, measure, lags, values, p, n, null_n, band, pearson_by_lag, window_total, extra):
    q = _bh({str(k): v for k, v in zip(lags, p, strict=True)})
    sig = [bool(q[str(k)] < ALPHA) if q[str(k)] is not None else False for k in lags]
    zero = lags.index(0)
    others = [i for i, k in enumerate(lags) if k != 0]
    best = max(others, key=lambda i: values[i])
    return {
        "a": a, "b": b, "measure": measure, "n_obs": window_total, "n_used": n, "windowed": n < window_total,
        "lags": lags, "values": values, "p": p, "p_adj": [q[str(k)] for k in lags], "significant": sig, "band": band,
        "null_draws": null_n, "pearson_abs": pearson_by_lag, "contemporaneous": values[zero], "contemporaneous_p": p[zero],
        "contemporaneous_significant": sig[zero], "best_lag": lags[best], "best_value": values[best], "best_significant": sig[best],
        **extra,
    }


def dependence_pair(returns: pd.DataFrame, a: str, b: str, measure: str = "dcor", maxlag: int = 10) -> dict:
    """Dépendance de A(t) et B(t−k) pour k de −maxlag à +maxlag, avec p-values par décalages circulaires (loi nulle qui garde la
    dynamique propre de chaque série), corrigées de Benjamini-Hochberg sur l'ensemble des décalages."""
    if a == b:
        raise ValueError("Choisis deux actifs différents.")
    if measure not in MEASURES:
        raise ValueError("mesure inconnue (dcor ou mi)")
    win = returns[[a, b]].iloc[-PAIR_MAX_OBS:]
    n = len(win)
    if n < 60:
        raise ValueError("Pas assez d'observations pour la dépendance non linéaire (minimum 60).")
    maxlag = int(min(max(1, maxlag), MAX_LAG, n // 10))
    x, y = win[a].to_numpy(dtype=float), win[b].to_numpy(dtype=float)
    lags = list(range(-maxlag, maxlag + 1))
    smin = max(2 * maxlag + 1, n // 10)                       # on n'utilise que des décalages assez grands pour être sans lien avec le vrai
    with np.errstate(invalid="ignore", divide="ignore"):
        pearson_by_lag = [abs(float(np.corrcoef(*aligned_lag(x, y, k))[0, 1])) for k in lags]
    if measure == "dcor":
        a0, b0 = ucenter(x), ucenter(y)
        r_by_lag = []
        for k in lags:
            if k == 0:
                r_by_lag.append(_r_star(a0, b0, n))
            else:
                xa, ya = aligned_lag(x, y, k)
                r_by_lag.append(_r_star(ucenter(xa), ucenter(ya), len(xa)))
        null = _circular_dcor_null(a0, b0, smin)
        pv = [_perm_p(r, null) for r in r_by_lag]
        band = _dcor_value(float(np.quantile(null, 0.95)))
        out = _pair_summary(a, b, "dcor", lags, [_dcor_value(r) for r in r_by_lag], pv, n, len(null), band, pearson_by_lag,
                            len(returns), {"asymptotic_p_zero": dcor_ttest_p(r_by_lag[lags.index(0)], n)})
    else:
        rx, ry = normal_scores(x), normal_scores(y)
        mi_by_lag = []
        for k in lags:
            xa, ya = aligned_lag(x, y, k)
            mi_by_lag.append(ksg_mutual_information(normal_scores(xa), normal_scores(ya)))
        rng = np.random.default_rng(_SEED + n)
        shifts = rng.integers(smin, n - smin + 1, size=MI_PAIR_NULL_DRAWS)
        null = np.array([ksg_mutual_information(rx, np.roll(ry, int(s))) for s in shifts])
        pv = [_perm_p(m, null) for m in mi_by_lag]
        band = linfoot(float(np.quantile(null, 0.95)))
        out = _pair_summary(a, b, "mi", lags, [linfoot(m) for m in mi_by_lag], pv, n, len(null), band, pearson_by_lag, len(returns),
                            {"mi_nats": [max(m, 0.0) for m in mi_by_lag]})
    pearson_p = float(sst.pearsonr(x, y).pvalue)
    out["pearson_contemporaneous"] = float(np.corrcoef(x, y)[0, 1])
    out["pearson_p"] = pearson_p
    # le fait marquant : un lien présent alors que la corrélation linéaire n'y voit rien
    out["nonlinear_only"] = bool(out["contemporaneous_significant"] and pearson_p >= ALPHA)
    out["note"] = (f"Loi nulle : {out['null_draws']} décalages circulaires d'une série (la dynamique propre à chaque série est conservée). "
                   f"Seuil à 95 % : {out['band']:.3f}. {len(lags)} décalages testés, p-values corrigées (Benjamini-Hochberg).")
    return clean(out)
