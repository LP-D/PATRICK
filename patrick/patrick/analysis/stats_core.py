"""Briques statistiques pures de l'analyse des entraînements : des tableaux en entrée, des nombres ou des listes en sortie.

Rien ici ne lit une base, un fichier ou le réseau. Chaque fonction accepte un échantillon vide ou dégénéré et renvoie alors `None`
(ou une liste vide) plutôt que de lever : une section de page sans assez de données se dit « indisponible », elle ne casse pas la page.

Rappel des conventions de la cible (`features/target.py`) : 4 classes, 0 = baisse forte, 1 = baisse faible, 2 = hausse faible,
3 = hausse forte ; « hausse » = classes 2 et 3.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sps

UP_FROM = 2
N_CLASSES = 4
CLASS_KEYS = ("down_strong", "down_weak", "up_weak", "up_strong")


# --------------------------------------------------------------------------------------------------------------------- JSON
def clean(value):
    """Nombre sûr pour le JSON : `NaN` et `inf` deviennent `None`, les scalaires numpy des nombres Python."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    return value


def jsonable(obj):
    """Version récursive de `clean` : dictionnaires, listes, tableaux numpy, scalaires."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    return clean(obj)


def thin_indices(n: int, max_points: int) -> np.ndarray:
    """Au plus `max_points` indices régulièrement espacés dans `range(n)`, premier et dernier toujours conservés."""
    if n <= max_points or max_points < 2:
        return np.arange(n)
    idx = np.unique(np.round(np.linspace(0, n - 1, max_points)).astype(int))
    return idx


# ------------------------------------------------------------------------------------------------------------ proportions
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Intervalle de Wilson d'une proportion k/n (95 % par défaut) : correct même pour de petits n et des taux proches de 0 ou 1."""
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def binom_p_greater(k: int, n: int, p0: float) -> float | None:
    """p-value unilatérale : probabilité d'obtenir au moins k succès sur n si la vraie probabilité de succès est p0."""
    if n <= 0 or not 0.0 < p0 < 1.0:
        return None
    return float(sps.binomtest(int(k), int(n), p0, alternative="greater").pvalue)


# ------------------------------------------------------------------------------------------------------------ classification
def direction(classes) -> np.ndarray:
    """Classes 0..3 -> booléen « hausse »."""
    return np.asarray(classes, dtype=float) >= UP_FROM


def confusion_matrix(y_true, y_pred, n_classes: int = N_CLASSES) -> np.ndarray:
    """Matrice (ligne = classe réelle, colonne = classe prédite). Les valeurs hors 0..n-1 sont ignorées."""
    yt = np.asarray(y_true).astype(int)
    yp = np.asarray(y_pred).astype(int)
    ok = (yt >= 0) & (yt < n_classes) & (yp >= 0) & (yp < n_classes)
    m = np.zeros((n_classes, n_classes), dtype=int)
    np.add.at(m, (yt[ok], yp[ok]), 1)
    return m


def per_class_scores(cm: np.ndarray) -> list[dict]:
    """Précision, rappel, F1 et effectif réel de chaque classe d'une matrice de confusion (ligne = réel)."""
    out = []
    for c in range(cm.shape[0]):
        tp = int(cm[c, c])
        pred = int(cm[:, c].sum())
        real = int(cm[c, :].sum())
        prec = tp / pred if pred else None
        rec = tp / real if real else None
        f1 = (2 * prec * rec / (prec + rec)) if prec is not None and rec is not None and (prec + rec) > 0 else None
        out.append({"class": c, "precision": prec, "recall": rec, "f1": f1, "support": real, "predicted": pred})
    return out


def binary_scores(up_true, up_pred) -> dict:
    """Accuracy, précision, rappel, F1 (sur « hausse »), exactitude équilibrée, MCC et F1 moyen des deux directions (`F1_dir`)."""
    t = np.asarray(up_true, dtype=bool)
    p = np.asarray(up_pred, dtype=bool)
    n = len(t)
    if n == 0:
        return {"n": 0, "acc": None, "precision": None, "recall": None, "f1_up": None, "f1_dir": None, "bal_acc": None,
                "mcc": None, "tp": 0, "fp": 0, "tn": 0, "fn": 0}
    tp = int((t & p).sum())
    fp = int((~t & p).sum())
    tn = int((~t & ~p).sum())
    fn = int((t & ~p).sum())
    acc = (tp + tn) / n
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1_up = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None
    f1_dn = 2 * tn / (2 * tn + fn + fp) if (2 * tn + fn + fp) else None
    f1_dir = (f1_up + f1_dn) / 2 if f1_up is not None and f1_dn is not None else None
    tpr = tp / (tp + fn) if tp + fn else None
    tnr = tn / (tn + fp) if tn + fp else None
    bal = (tpr + tnr) / 2 if tpr is not None and tnr is not None else None
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn - fp * fn) / denom) if denom else None
    return {"n": n, "acc": acc, "precision": prec, "recall": rec, "f1_up": f1_up, "f1_dir": f1_dir, "bal_acc": bal, "mcc": mcc,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn}


# --------------------------------------------------------------------------------------------------------------- ROC / PR
def auc(y, score) -> float | None:
    """Aire sous la courbe ROC par les rangs (statistique de Mann-Whitney, ex æquo en rang moyen). `None` si une classe manque."""
    y = np.asarray(y, dtype=bool)
    s = np.asarray(score, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return None
    ranks = sps.rankdata(s)
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def roc_curve(y, score, max_points: int = 120) -> dict:
    """Points (taux de faux positifs, taux de vrais positifs) de la courbe ROC, amincis à `max_points`."""
    y = np.asarray(y, dtype=bool)
    s = np.asarray(score, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return {"fpr": [], "tpr": [], "auc": None}
    order = np.argsort(-s, kind="mergesort")
    ys = y[order]
    ss = s[order]
    tps = np.cumsum(ys)
    fps = np.cumsum(~ys)
    last = np.r_[np.flatnonzero(np.diff(ss)), len(ss) - 1]          # une valeur par seuil distinct
    tpr = np.r_[0.0, tps[last] / n1]
    fpr = np.r_[0.0, fps[last] / n0]
    keep = thin_indices(len(fpr), max_points)
    return {"fpr": fpr[keep], "tpr": tpr[keep], "auc": auc(y, s)}


def pr_curve(y, score, max_points: int = 120) -> dict:
    """Courbe précision-rappel (positif = hausse) et précision moyenne ; `base_rate` = proportion de hausses."""
    y = np.asarray(y, dtype=bool)
    s = np.asarray(score, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    n1 = int(y.sum())
    if n1 == 0 or n1 == len(y):
        return {"recall": [], "precision": [], "ap": None, "base_rate": (n1 / len(y)) if len(y) else None}
    order = np.argsort(-s, kind="mergesort")
    ys = y[order]
    ss = s[order]
    tps = np.cumsum(ys)
    last = np.r_[np.flatnonzero(np.diff(ss)), len(ss) - 1]
    tp = tps[last]
    pred_pos = last + 1
    precision = tp / pred_pos
    recall = tp / n1
    ap = float(np.sum(np.diff(np.r_[0.0, recall]) * precision))
    keep = thin_indices(len(recall), max_points)
    return {"recall": recall[keep], "precision": precision[keep], "ap": ap, "base_rate": n1 / len(y)}


# ------------------------------------------------------------------------------------------------------------- calibration
def reliability(p, y, n_bins: int = 10, strategy: str = "quantile") -> dict:
    """Diagramme de fiabilité de P(hausse) : par tranche de probabilité, probabilité moyenne annoncée contre fréquence observée.

    `strategy` : `quantile` (tranches de même effectif, par défaut : aucune tranche vide) ou `uniform` (largeurs égales).
    Renvoie aussi le Brier, l'ECE (écart moyen pondéré annoncé/observé) et la décomposition de Murphy du Brier :
    Brier ≈ fiabilité − résolution + incertitude (la variance à l'intérieur des tranches est négligée)."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    n = len(p)
    if n == 0:
        return {"bins": [], "brier": None, "ece": None, "n": 0, "base_rate": None, "reliability": None, "resolution": None,
                "uncertainty": None}
    if strategy == "uniform":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
    else:
        edges = np.unique(np.quantile(p, np.linspace(0.0, 1.0, n_bins + 1)))
        if len(edges) < 3:
            edges = np.linspace(float(p.min()), float(p.max()) + 1e-9, n_bins + 1) if p.max() > p.min() else np.array([0.0, 1.0])
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    base = float(y.mean())
    bins, ece, rel, res = [], 0.0, 0.0, 0.0
    for b in range(len(edges) - 1):
        sel = which == b
        nb = int(sel.sum())
        if nb == 0:
            continue
        pm = float(p[sel].mean())
        fq = float(y[sel].mean())
        lo, hi = wilson(int(y[sel].sum()), nb)
        bins.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "p_mean": pm, "freq": fq, "n": nb, "ci_lo": lo, "ci_hi": hi})
        w = nb / n
        ece += w * abs(fq - pm)
        rel += w * (pm - fq) ** 2
        res += w * (fq - base) ** 2
    return {"bins": bins, "brier": float(np.mean((p - y) ** 2)), "ece": float(ece), "n": n, "base_rate": base,
            "reliability": float(rel), "resolution": float(res), "uncertainty": base * (1 - base)}


def histogram(values, bins: int = 20, lo: float = 0.0, hi: float = 1.0) -> dict:
    """Effectifs par intervalle égal entre `lo` et `hi` (hors bornes ignoré)."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    counts, edges = np.histogram(v, bins=bins, range=(lo, hi))
    return {"edges": edges, "counts": counts, "n": len(v)}


# ---------------------------------------------------------------------------------------------------------------- séries
def rolling_mean(x, window: int) -> np.ndarray:
    """Moyenne glissante sur `window` valeurs ; NaN tant que la fenêtre n'est pas pleine. Les NaN d'entrée donnent un NaN de sortie."""
    a = np.asarray(x, dtype=float)
    n = len(a)
    out = np.full(n, np.nan)
    if window < 1 or n < window:
        return out
    c = np.cumsum(np.where(np.isfinite(a), a, 0.0))
    k = np.cumsum(np.isfinite(a).astype(int))
    c = np.r_[0.0, c]
    k = np.r_[0, k]
    cnt = k[window:] - k[:-window]
    out[window - 1:] = np.where(cnt == window, (c[window:] - c[:-window]) / window, np.nan)
    return out


def sharpe(returns, periods: int = 252) -> float | None:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return None
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(periods)) if sd > 1e-12 else None      # écart-type nul à l'arrondi près : pas de Sharpe


def sortino(returns, periods: int = 252) -> float | None:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return None
    down = np.minimum(r, 0.0)
    dd = math.sqrt(float(np.mean(down ** 2)))
    return float(r.mean() / dd * math.sqrt(periods)) if dd > 1e-12 else None


def equity_from_returns(returns) -> np.ndarray:
    """Courbe de valeur (départ à 1) par capitalisation des rendements périodiques."""
    r = np.nan_to_num(np.asarray(returns, dtype=float), nan=0.0)
    return np.cumprod(1.0 + r)


def drawdown_series(equity) -> np.ndarray:
    """Baisse en cours par rapport au plus haut précédent (valeurs ≤ 0)."""
    e = np.asarray(equity, dtype=float)
    if len(e) == 0:
        return e
    peak = np.maximum.accumulate(e)
    return e / peak - 1.0


def performance_summary(returns, periods: int = 252) -> dict:
    """Rendement total, annualisé, volatilité, Sharpe, Sortino, pire baisse (valeur absolue négative) et part de jours gagnants."""
    r = np.nan_to_num(np.asarray(returns, dtype=float), nan=0.0)
    n = len(r)
    if n == 0:
        return {"n": 0, "total": None, "cagr": None, "vol": None, "sharpe": None, "sortino": None, "max_dd": None, "win_rate": None}
    eq = equity_from_returns(r)
    total = float(eq[-1] - 1.0)
    years = n / periods
    cagr = float(eq[-1] ** (1 / years) - 1.0) if years > 0 and eq[-1] > 0 else None
    return {"n": n, "total": total, "cagr": cagr, "vol": float(r.std(ddof=1) * math.sqrt(periods)) if n > 1 else None,
            "sharpe": sharpe(r, periods), "sortino": sortino(r, periods), "max_dd": float(drawdown_series(eq).min()),
            "win_rate": float((r > 0).mean())}


# -------------------------------------------------------------------------------------------------------- rééchantillonnage
def _block_starts(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = math.ceil(n / block)
    return rng.integers(0, max(1, n - block + 1), size=n_blocks)


def block_bootstrap(stat, arrays: tuple, block: int = 10, n_boot: int = 300, seed: int = 0) -> dict:
    """Bootstrap par blocs glissants (conserve l'autocorrélation à l'intérieur d'un bloc) d'une statistique `stat(*arrays) -> float`.

    Renvoie l'estimation sur l'échantillon réel, l'écart-type et l'intervalle à 95 % (percentiles 2,5 et 97,5)."""
    arrays = tuple(np.asarray(a) for a in arrays)
    n = len(arrays[0]) if arrays else 0
    point = stat(*arrays) if n else None
    if n < max(10, block):
        return {"point": clean(point), "std": None, "lo": None, "hi": None, "n": n, "block": block, "n_boot": 0}
    rng = np.random.default_rng(seed)
    offs = np.arange(block)
    draws = []
    for _ in range(n_boot):
        starts = _block_starts(n, block, rng)
        idx = (starts[:, None] + offs[None, :]).ravel()[:n]
        v = stat(*(a[idx] for a in arrays))
        if v is not None and math.isfinite(v):
            draws.append(v)
    if len(draws) < 10:
        return {"point": clean(point), "std": None, "lo": None, "hi": None, "n": n, "block": block, "n_boot": len(draws)}
    d = np.asarray(draws)
    return {"point": clean(point), "std": float(d.std(ddof=1)), "lo": float(np.percentile(d, 2.5)),
            "hi": float(np.percentile(d, 97.5)), "n": n, "block": block, "n_boot": len(draws)}


def block_shuffle(values: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """Découpe en blocs consécutifs de `block` valeurs, mélange l'ordre des blocs, garde l'ordre à l'intérieur de chacun."""
    n = len(values)
    if block <= 1:
        return values[rng.permutation(n)]
    pieces = [values[i:i + block] for i in range(0, n, block)]
    order = rng.permutation(len(pieces))
    return np.concatenate([pieces[i] for i in order]) if pieces else values


def permutation_test(stat, truth, predicted, block: int = 1, n_perm: int = 500, seed: int = 0) -> dict:
    """Test de permutation par blocs : on casse le lien entre prédictions et réalité en mélangeant les blocs de la RÉALITÉ, puis on
    recalcule `stat(truth, predicted)`. p = (1 + nombre de tirages au moins aussi bons que l'observé) / (1 + tirages).

    Un bloc d'au moins la longueur de l'horizon respecte le chevauchement des étiquettes (deux dates voisines partagent des rendements).
    Renvoie aussi la distribution nulle résumée (moyenne, percentiles) pour la tracer."""
    truth = np.asarray(truth)
    predicted = np.asarray(predicted)
    n = len(truth)
    if n < 20:
        return {"observed": None, "p_value": None, "null_mean": None, "null_p05": None, "null_p95": None, "null_hist": None, "n": n,
                "block": block, "n_perm": 0}
    observed = stat(truth, predicted)
    rng = np.random.default_rng(seed)
    nulls = np.empty(n_perm)
    for i in range(n_perm):
        nulls[i] = stat(block_shuffle(truth, block, rng), predicted)
    nulls = nulls[np.isfinite(nulls)]
    if observed is None or len(nulls) == 0:
        return {"observed": clean(observed), "p_value": None, "null_mean": None, "null_p05": None, "null_p95": None, "null_hist": None,
                "n": n, "block": block, "n_perm": len(nulls)}
    p_value = float((1 + np.sum(nulls >= observed)) / (1 + len(nulls)))
    lo, hi = float(nulls.min()), float(nulls.max())
    hist = histogram(nulls, bins=24, lo=lo, hi=hi if hi > lo else lo + 1e-9)
    return {"observed": float(observed), "p_value": p_value, "null_mean": float(nulls.mean()), "null_p05": float(np.percentile(nulls, 5)),
            "null_p95": float(np.percentile(nulls, 95)), "null_hist": {"edges": hist["edges"], "counts": hist["counts"]}, "n": n,
            "block": block, "n_perm": len(nulls)}


def shift_curve(up_true, up_pred, max_lag: int = 10) -> list[dict]:
    """Exactitude de la direction quand on décale les prédictions de `lag` dates par rapport à la réalité (lag ∈ [-K, K]).

    Un signal réel est le plus exact à lag = 0 et décroît des deux côtés ; un pic à un décalage non nul, ou une courbe plate à haut niveau,
    signale un alignement douteux (fuite de date possible, ou simple persistance de la tendance)."""
    t = np.asarray(up_true, dtype=bool)
    p = np.asarray(up_pred, dtype=bool)
    n = len(t)
    out = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = t[: n - lag] if lag else t, p[lag:]
        else:
            a, b = t[-lag:], p[: n + lag]
        m = len(a)
        out.append({"lag": lag, "acc": float((a == b).mean()) if m else None, "n": int(m)})
    return out


def spearman(x, y) -> dict:
    """Corrélation de rang (information coefficient) et p-value bilatérale ; `None` si moins de 10 points ou une série constante."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 10 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return {"rho": None, "p": None, "n": len(a)}
    rho, p = sps.spearmanr(a, b)
    return {"rho": clean(rho), "p": clean(p), "n": len(a)}


def longest_runs(flags, top: int = 5) -> list[dict]:
    """Les `top` plus longues séries consécutives de `True` (ex. erreurs d'affilée) : début, fin (indices) et longueur."""
    f = np.asarray(flags, dtype=bool)
    runs, start = [], None
    for i, v in enumerate(f):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(f) - 1))
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    return [{"start": s, "end": e, "length": e - s + 1} for s, e in runs[:top]]
