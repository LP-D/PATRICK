"""Sections « prédit contre réel » : frise temporelle, taux de réussite glissant, nuage P(hausse) / rendement réalisé, matrices de
confusion, ROC / précision-rappel, calibration. Toutes lisent le `Ctx` (frame de l'essai) et renvoient un dictionnaire JSON-isable."""
from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd

from patrick.analysis import stats_core as sc
from patrick.analysis.context import Ctx, iso

MAX_DAYS_MODE = 700          # au-delà, la frise agrège en tranches
N_BINS_MODE = 360
MAX_SCATTER = 1500
SPLITS = ("test", "holdout")


def _dir_arrays(d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return d["ut"].to_numpy(dtype=float) >= 0.5, d["up"].to_numpy(dtype=bool)


def _scores(d: pd.DataFrame) -> dict:
    """Scores directionnels d'un jeu de lignes + AUC de P(hausse) + Brier."""
    ut, up = _dir_arrays(d)
    out = sc.binary_scores(ut, up)
    p = d["p_up"].to_numpy(dtype=float)
    ok = np.isfinite(p)
    out["auc"] = sc.auc(ut[ok], p[ok]) if ok.sum() >= 10 else None
    out["brier"] = float(np.mean((p[ok] - ut[ok]) ** 2)) if ok.sum() else None
    out["base_up"] = float(ut.mean()) if len(ut) else None
    out["share_pred_up"] = float(up.mean()) if len(up) else None
    lo, hi = sc.wilson(round((out["acc"] or 0) * out["n"]), out["n"]) if out["n"] else (None, None)
    out["acc_lo"], out["acc_hi"] = lo, hi
    return out


# ------------------------------------------------------------------------------------------------------------ frise
def timeline(ctx: Ctx) -> dict:
    """Prédit contre réel dans le temps, pour une fenêtre de dates (`start`, `end`) : jours isolés si la fenêtre est courte,
    sinon tranches de même effectif (part de hausses prédite / réalisée, exactitude, prix en fin de tranche)."""
    fr = ctx.fr
    full = ctx.evaluated(("test", "holdout"))
    live = ctx.one_path(fr.df[(fr.df["split_name"] == "live") & fr.df["ut"].notna()])
    d = pd.concat([full, live]).sort_values("ts", kind="mergesort") if not live.empty else full
    if d.empty:
        return {"available": False, "reason": "no_predictions"}
    full_range = [iso(d["ts"].min()), iso(d["ts"].max())]
    start = pd.to_datetime(ctx.str_param("start"), errors="coerce")
    end = pd.to_datetime(ctx.str_param("end"), errors="coerce")
    w = d
    if pd.notna(start):
        w = w[w["ts"] >= start]
    if pd.notna(end):
        w = w[w["ts"] <= end]
    if w.empty:
        return {"available": False, "reason": "empty_window", "range": full_range}
    folds = []
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        folds.append({"fold": int(fold), "split": split, "start": iso(g["ts"].min()), "end": iso(g["ts"].max()), "n": len(g)})
    folds.sort(key=lambda f: f["start"])
    price = None
    if fr.levels is not None:
        lv = fr.levels.loc[w["ts"].min():w["ts"].max()].dropna()
        idx = sc.thin_indices(len(lv), 600)
        price = {"t": [iso(t) for t in lv.index[idx]], "v": [float(v) for v in lv.to_numpy()[idx]]}
    n = len(w)
    out = {"available": True, "range": full_range, "window": [iso(w["ts"].min()), iso(w["ts"].max())], "n": n, "folds": folds,
           "price": price, "is_alpha": fr.is_alpha, "horizon": fr.horizon}
    if n <= MAX_DAYS_MODE:
        pts = []
        for r in w.itertuples(index=False):
            pts.append({"t": iso(r.ts), "yt": None if pd.isna(r.yt) else int(r.yt), "yp": int(r.yp),
                        "ut": int(r.ut), "p": None if pd.isna(r.p_up) else round(float(r.p_up), 4),
                        "ok": bool((r.ut >= 0.5) == bool(r.up)), "ret": None if pd.isna(r.ret) else round(float(r.ret), 5),
                        "split": r.split_name, "fold": int(r.fold)})
        out["mode"], out["points"] = "days", pts
        return out
    edges = np.linspace(0, n, min(N_BINS_MODE, n) + 1).astype(int)
    ut, up = _dir_arrays(w)
    p = w["p_up"].to_numpy(dtype=float)
    ts = w["ts"].to_numpy()
    lv = fr.levels
    bins = []
    for a, b in pairwise(edges):
        if b <= a:
            continue
        t_end = pd.Timestamp(ts[b - 1])
        px = None
        if lv is not None:
            sel = lv.loc[:t_end]
            px = float(sel.iloc[-1]) if len(sel) else None
        bins.append({"t0": iso(ts[a]), "t1": iso(ts[b - 1]), "n": int(b - a), "up_pred": float(up[a:b].mean()),
                     "up_true": float(ut[a:b].mean()), "acc": float((ut[a:b] == up[a:b]).mean()),
                     "p": float(np.nanmean(p[a:b])) if np.isfinite(p[a:b]).any() else None, "px": px,
                     "fold": int(w["fold"].iloc[a])})
    out["mode"], out["points"] = "bins", bins
    return out


# ------------------------------------------------------------------------------------------------------------ glissant
def rolling(ctx: Ctx) -> dict:
    """Exactitude de la direction sur une fenêtre glissante (`window` prédictions), avec sa bande de Wilson, contre la base naïve
    « toujours le côté majoritaire de la fenêtre » ; et le gain cumulé d'appels justes par rapport au côté majoritaire global."""
    d = ctx.evaluated(("test", "holdout"))
    if len(d) < 30:
        return {"available": False, "reason": "not_enough"}
    w = ctx.int_param("window", 120, lo=10, hi=2000)
    w = min(w, max(10, len(d) // 2))
    ut, up = _dir_arrays(d)
    correct = (ut == up).astype(float)
    acc = sc.rolling_mean(correct, w)
    share_up = sc.rolling_mean(ut.astype(float), w)
    base = np.maximum(share_up, 1 - share_up)
    z = 1.96
    p = np.where(np.isfinite(acc), acc, 0.5)
    denom = 1 + z * z / w
    centre = (p + z * z / (2 * w)) / denom
    half = z * np.sqrt(p * (1 - p) / w + z * z / (4 * w * w)) / denom
    lo = np.where(np.isfinite(acc), np.clip(centre - half, 0, 1), np.nan)
    hi = np.where(np.isfinite(acc), np.clip(centre + half, 0, 1), np.nan)
    m_global = max(float(ut.mean()), 1 - float(ut.mean()))
    cum_edge = np.cumsum(correct - m_global)
    cum_flip = np.cumsum(correct - 0.5)
    idx = sc.thin_indices(len(d), 700)
    t = d["ts"].to_numpy()
    folds = []
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        folds.append({"fold": int(fold), "split": split, "start": iso(g["ts"].min()), "end": iso(g["ts"].max())})
    folds.sort(key=lambda f: f["start"])
    below = acc < 0.5
    return {"available": True, "window": w, "n": len(d), "t": [iso(t[i]) for i in idx], "acc": acc[idx], "lo": lo[idx], "hi": hi[idx],
            "base": base[idx], "cum_edge": cum_edge[idx], "cum_flip": cum_flip[idx], "majority_global": m_global,
            "share_below_half": float(np.nanmean(below[np.isfinite(acc)])) if np.isfinite(acc).any() else None,
            "worst": {"acc": float(np.nanmin(acc)) if np.isfinite(acc).any() else None,
                      "at": iso(t[int(np.nanargmin(np.where(np.isfinite(acc), acc, 9)))]) if np.isfinite(acc).any() else None},
            "best": {"acc": float(np.nanmax(acc)) if np.isfinite(acc).any() else None,
                     "at": iso(t[int(np.nanargmax(np.where(np.isfinite(acc), acc, -9)))]) if np.isfinite(acc).any() else None},
            "folds": folds}


# ------------------------------------------------------------------------------------------------------------ nuage
def scatter(ctx: Ctx) -> dict:
    """P(hausse) annoncée contre rendement réalisé à l'horizon : nuage échantillonné, déciles de P(hausse) (rendement moyen, part de
    hausses, effectif), corrélation de rang (information coefficient) globale et par échantillon."""
    fr = ctx.fr
    d = ctx.evaluated(("test", "holdout"))
    d = d[d["p_up"].notna() & d["ret"].notna()]
    if len(d) < 30:
        reason = "no_returns" if fr.levels is None else "not_enough"
        return {"available": False, "reason": reason}
    p = d["p_up"].to_numpy(dtype=float)
    r = d["ret"].to_numpy(dtype=float)
    rng = np.random.default_rng(0)
    pick = np.sort(rng.choice(len(d), size=min(MAX_SCATTER, len(d)), replace=False))
    edges = np.unique(np.quantile(p, np.linspace(0, 1, 11)))
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, max(0, len(edges) - 2))
    deciles = []
    for b in range(len(edges) - 1):
        sel = which == b
        if not sel.any():
            continue
        rr = r[sel]
        deciles.append({"p_lo": float(edges[b]), "p_hi": float(edges[b + 1]), "p_mean": float(p[sel].mean()), "n": int(sel.sum()),
                        "mean_ret": float(rr.mean()), "median_ret": float(np.median(rr)), "share_up": float((rr > 0).mean()),
                        "sem": float(rr.std(ddof=1) / np.sqrt(len(rr))) if len(rr) > 1 else None})
    spread = None
    if len(deciles) >= 4:
        spread = deciles[-1]["mean_ret"] - deciles[0]["mean_ret"]
    by_split = {name: sc.spearman(g["p_up"], g["ret"]) for name, g in d.groupby("split_name")}
    fold_ic = []
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        s = sc.spearman(g["p_up"], g["ret"])
        fold_ic.append({"fold": int(fold), "split": split, "rho": s["rho"], "n": s["n"]})
    lim = float(np.quantile(np.abs(r), 0.995)) if len(r) else 0.0
    return {"available": True, "n": len(d), "ic": sc.spearman(p, r), "ic_by_split": by_split, "ic_by_fold": fold_ic,
            "deciles": deciles, "spread_top_bottom": spread, "is_alpha": fr.is_alpha, "horizon": fr.horizon,
            "points": {"p": np.round(p[pick], 4), "ret": np.clip(np.round(r[pick], 5), -lim, lim),
                       "split": d["split_name"].to_numpy()[pick].tolist()},
            "clip": lim}


# ------------------------------------------------------------------------------------------------------------ confusion
def _confusion_block(d: pd.DataFrame) -> dict:
    cm = sc.confusion_matrix(d["yt"].to_numpy(dtype=float), d["yp"].to_numpy(dtype=float))
    row = cm.sum(axis=1, keepdims=True)
    col = cm.sum(axis=0, keepdims=True)
    ut, _up = _dir_arrays(d)
    bscores = _scores(d)
    p = d["p_up"].to_numpy(dtype=float)
    ok = np.isfinite(p)
    roc = sc.roc_curve(ut[ok], p[ok]) if ok.sum() >= 10 else {"fpr": [], "tpr": [], "auc": None}
    pr = sc.pr_curve(ut[ok], p[ok]) if ok.sum() >= 10 else {"recall": [], "precision": [], "ap": None, "base_rate": None}
    auc_ci = (sc.block_bootstrap(lambda a, b: sc.auc(a, b), (ut[ok], p[ok]), block=max(5, 1), n_boot=200, seed=1)
              if ok.sum() >= 60 else None)
    return {"n": len(d), "cm": cm, "cm_row": np.divide(cm, row, out=np.zeros(cm.shape), where=row > 0),
            "cm_col": np.divide(cm, col, out=np.zeros(cm.shape), where=col > 0), "classes": sc.per_class_scores(cm),
            "binary": bscores, "bin_cm": [[bscores["tn"], bscores["fp"]], [bscores["fn"], bscores["tp"]]],
            "roc": roc, "pr": pr, "auc_ci": auc_ci}


def confusion(ctx: Ctx) -> dict:
    """Matrices de confusion à 4 classes et haut/bas, par échantillon (test, holdout) et par pli ; précision / rappel / F1 de chaque
    classe ; courbes ROC et précision-rappel de P(hausse)."""
    d = ctx.evaluated(("test", "holdout"))
    d4 = d[d["yt"].notna()]
    if d4.empty:
        return {"available": False, "reason": "no_predictions"}
    out: dict = {"available": True, "splits": {}, "by_fold": []}
    for name in SPLITS:
        g = d4[d4["split_name"] == name]
        if len(g):
            out["splits"][name] = _confusion_block(g)
    folds = []
    for (split, fold), g in d4.groupby(["split_name", "fold"]):
        s = _scores(g)
        folds.append({"fold": int(fold), "split": split, "start": iso(g["ts"].min()), "end": iso(g["ts"].max()), **s})
    folds.sort(key=lambda f: f["start"])
    out["by_fold"] = folds
    return out


# ---------------------------------------------------------------------------------------------------------- calibration
def calibration(ctx: Ctx) -> dict:
    """Fiabilité de P(hausse) : diagramme par quantiles et par largeurs égales, histogrammes selon la direction réalisée, Brier et sa
    décomposition, ECE par pli, et la même lecture sur les prédictions live calibrées quand il y en a assez."""
    fr = ctx.fr
    d = ctx.evaluated(("test", "holdout"))
    d = d[d["p_up"].notna()]
    if len(d) < 30:
        return {"available": False, "reason": "no_probabilities" if d.empty else "not_enough"}
    out: dict = {"available": True, "splits": {}, "by_fold": []}
    for name in SPLITS:
        g = d[d["split_name"] == name]
        if len(g) < 20:
            continue
        p, y = g["p_up"].to_numpy(dtype=float), g["ut"].to_numpy(dtype=float)
        up_mask = y >= 0.5
        out["splits"][name] = {
            "quantile": sc.reliability(p, y, 10, "quantile"), "uniform": sc.reliability(p, y, 10, "uniform"),
            "hist_up": sc.histogram(p[up_mask], 20), "hist_down": sc.histogram(p[~up_mask], 20),
            "mean_p": float(p.mean()), "base_rate": float(y.mean())}
    for (split, fold), g in d.groupby(["split_name", "fold"]):
        if len(g) < 20:
            continue
        r = sc.reliability(g["p_up"].to_numpy(dtype=float), g["ut"].to_numpy(dtype=float), 5, "quantile")
        out["by_fold"].append({"fold": int(fold), "split": split, "n": len(g), "brier": r["brier"], "ece": r["ece"],
                               "mean_p": float(g["p_up"].mean()), "base_rate": r["base_rate"]})
    out["by_fold"].sort(key=lambda f: (f["split"] != "test", f["fold"]))
    live = ctx.one_path(fr.df[(fr.df["split_name"] == "live") & fr.df["ut"].notna() & fr.df["p_up"].notna()])
    if len(live) >= 20:
        p, y = live["p_up"].to_numpy(dtype=float), live["ut"].to_numpy(dtype=float)
        out["live"] = {"reliability": sc.reliability(p, y, 5, "quantile"), "n": len(live),
                       "share_calibrated": float(np.nanmean(live["p_cal"].to_numpy(dtype=float))) if live["p_cal"].notna().any() else None}
    return out
