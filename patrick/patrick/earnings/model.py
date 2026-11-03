"""Modélisation prédictive en panel : amplitude de la réaction (cible primaire) et sens (secondaire).

La direction autour des résultats est proche de l'efficience ; l'amplitude est bien plus prévisible (volatilité passée, incertitude).
Règles :
- un modèle POOLÉ en panel (12 à 40 annonces par titre ne permettent aucun modèle par titre), variables normalisées par titre ou secteur ;
- walk-forward par date d'annonce, avec PURGE : un événement d'entraînement dont la fenêtre chevauche celle d'un événement de test (même
  semaine, forte corrélation) est retiré. Jamais de plis mélangés dans le temps ;
- cible d'amplitude : |CAR| / sigma quotidien du titre (z_abs), modélisée en log ;
- baselines obligatoires : moyenne passée du titre, moyenne passée du secteur (le mouvement implicite s'ajoute dès que les instantanés
  d'options existent) ; métriques MAE, QLIKE, corrélation de rang ; pour la direction AUC, taux de réussite, Brier, diagramme de calibration ;
- Diebold-Mariano (celui du projet) pour dire si un modèle bat sa baseline.
Toute variable est connue avant l'annonce ; les statistiques historiques d'un titre excluent l'événement testé (`panel._add_history`).
"""
from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd
from scipy import stats

from patrick.validation.diebold_mariano import diebold_mariano

AMP_FEATURES = ["f_hist", "f_sector", "f_vol", "f_size", "f_beta", "f_mom", "f_runup", "f_volpre", "f_unc", "f_annual", "f_evno", "f_stress"]
# La surprise de BPA de l'annonce testée (`surprise_pct`, `sue`) est publiée en même temps que la réaction : l'utiliser pour PRÉDIRE serait
# une fuite d'information (elle sert à EXPLIQUER la réaction, carte D). Seules les surprises des annonces PRÉCÉDENTES entrent ici.
DIR_FEATURES = ["f_prev_surprise", "f_streak", "f_prev", "f_runup_s", "f_mom_s", "f_stress", "f_beat_rate"]
FORBIDDEN_FEATURES = ("f_sue", "f_surprise")
OFFSET = 0.1
MIN_TRAIN = 40


def build_features(df: pd.DataFrame, regime: pd.Series | None = None) -> pd.DataFrame:
    """Matrice de variables, une ligne par événement (même index que `df`). Aucune imputation ici : elle se fait sur le train."""
    f = pd.DataFrame(index=df.index)
    f["f_hist"] = np.log(df["hist_mean_abs_z"] + OFFSET)
    f["f_sector"] = np.log(df["sector_hist_abs_z"] + OFFSET)
    f["f_vol"] = np.log(df["vol_est"].clip(lower=1e-4))
    f["f_size"] = np.log(df["dollar_vol"].clip(lower=1.0))
    f["f_beta"] = df["beta"]
    f["f_mom"] = df["mom_pre"].abs()
    f["f_runup"] = (df["run_up"].abs() / df["sigma"]).where(df["sigma"] > 0)
    f["f_volpre"] = np.log(df["vol_pre"].clip(lower=1e-3))
    f["f_unc"] = df["uncertain"].astype(float)
    f["f_annual"] = df["is_annual"].astype(float)
    f["f_evno"] = np.log(df["event_no"].clip(lower=1))
    f["f_stress"] = (regime.reindex(df.index) == "stress").astype(float) if regime is not None else 0.0
    f["f_prev_surprise"] = (df["prev_surprise"].clip(-50, 50) / 100.0)
    f["f_beat_rate"] = df["beat_rate_past"]
    f["f_runup_s"] = df["run_up"] / df["sigma"].where(df["sigma"] > 0)
    f["f_streak"] = df["beat_streak"].clip(upper=4)
    f["f_prev"] = np.sign(df["prev_car"])
    f["f_mom_s"] = df["mom_pre"]
    return f


def target_amplitude(df: pd.DataFrame) -> pd.Series:
    return np.log(df["z_abs"] + OFFSET)


def walk_forward_folds(day0: pd.Series, n_folds: int = 5, min_train_frac: float = 0.4, purge_days: int = 10) -> list[tuple[np.ndarray, np.ndarray]]:
    """Plis expansifs par date : test = bloc contigu de dates ; entraînement = événements antérieurs de plus de `purge_days` jours."""
    order = np.argsort(day0.to_numpy(), kind="stable")
    n = len(order)
    start = int(n * min_train_frac)
    if n - start < n_folds * 5:
        return []
    edges = np.linspace(start, n, n_folds + 1).astype(int)
    out = []
    dates = day0.to_numpy()
    for a, b in pairwise(edges):
        test = order[a:b]
        t0 = dates[test].min()
        cutoff = t0 - np.timedelta64(purge_days, "D")
        train = order[:a][dates[order[:a]] < cutoff]
        if len(train) >= MIN_TRAIN and len(test) >= 3:
            out.append((train, test))
    return out


def _impute(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    med = train.median(numeric_only=True).fillna(0.0)
    mu = train.fillna(med).mean()
    sd = train.fillna(med).std(ddof=0).replace(0, 1.0)
    return ((train.fillna(med) - mu) / sd).to_numpy(), ((test.fillna(med) - mu) / sd).to_numpy()


def _ridge(Xtr, ytr, Xte, alpha: float = 8.0):
    from sklearn.linear_model import Ridge
    m = Ridge(alpha=alpha).fit(Xtr, ytr)
    return m.predict(Xte), m


def _gbm(Xtr, ytr, Xte):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=120, learning_rate=0.05, min_samples_leaf=20, random_state=0).fit(Xtr, ytr)
    return m.predict(Xte), m


MODELS = {"ridge": _ridge, "gbm": _gbm}


def _qlike(z_true: np.ndarray, z_pred: np.ndarray) -> np.ndarray:
    """QLIKE sur des variances : variance prédite = (|z| attendu)² π/2 (loi demi-normale), variance réalisée = z²."""
    var_hat = np.maximum(z_pred, 0.05) ** 2 * np.pi / 2
    ratio = np.maximum(z_true, 1e-3) ** 2 / var_hat
    return ratio - np.log(ratio) - 1


def baseline_predictions(df: pd.DataFrame, train_idx: np.ndarray, test_idx: np.ndarray) -> dict[str, np.ndarray]:
    grand = float(df["z_abs"].iloc[train_idx].mean())
    sector = df["sector_hist_abs_z"].iloc[test_idx].fillna(grand).to_numpy()
    stock = df["hist_mean_abs_z"].iloc[test_idx].fillna(pd.Series(sector, index=df.index[test_idx])).to_numpy()
    return {"Moyenne passée du titre": stock, "Moyenne passée du secteur": sector}


def evaluate_amplitude(df: pd.DataFrame, feats: pd.DataFrame, model: str = "ridge", n_folds: int = 5, purge_days: int = 10,
                       columns: list[str] | None = None) -> dict:
    """Walk-forward purgé : prédictions hors échantillon de chaque modèle et baseline, pertes par événement, métriques, tests DM."""
    cols = columns or AMP_FEATURES
    y = target_amplitude(df)
    folds = walk_forward_folds(df["day0"], n_folds, purge_days=purge_days)
    if not folds:
        return {"status": "insufficient", "n": len(df)}
    preds: dict[str, list] = {model: [], **{k: [] for k in ("Moyenne passée du titre", "Moyenne passée du secteur")}}
    idx_all, z_all = [], []
    for train, test in folds:
        ok_tr = y.iloc[train].notna().to_numpy()
        tr = train[ok_tr]
        Xtr, Xte = _impute(feats.iloc[tr][cols], feats.iloc[test][cols])
        pred_log, _ = MODELS[model](Xtr, y.iloc[tr].to_numpy(), Xte)
        preds[model].append(np.maximum(np.exp(pred_log) - OFFSET, 0.05))
        for k, v in baseline_predictions(df, tr, test).items():
            preds[k].append(v)
        idx_all.append(test)
        z_all.append(df["z_abs"].iloc[test].to_numpy())
    idx = np.concatenate(idx_all)
    z = np.concatenate(z_all)
    keep = np.isfinite(z)
    out = {"status": "ok", "n": int(keep.sum()), "idx": idx[keep], "models": {}}
    losses = {}
    for name, chunks in preds.items():
        pr = np.concatenate(chunks)[keep]
        pr = np.where(np.isfinite(pr), pr, np.nanmean(pr))
        mae = np.abs(z[keep] - pr)
        ql = _qlike(z[keep], pr)
        losses[name] = mae
        rho = stats.spearmanr(pr, z[keep]).statistic if np.std(pr) > 0 else np.nan
        out["models"][name] = {"mae": float(mae.mean()), "qlike": float(ql.mean()), "rho": float(rho) if np.isfinite(rho) else np.nan, "pred": pr}
    base = "Moyenne passée du titre"
    for name in out["models"]:
        if name != base:
            dm = diebold_mariano(losses[name], losses[base], h=1)
            out["models"][name]["dm_vs_stock"] = {"stat": dm.get("dm_stat"), "p": dm.get("p_value")}
    out["z"] = z[keep]
    return out


def importance_ridge(df: pd.DataFrame, feats: pd.DataFrame, columns: list[str] | None = None) -> list[tuple[str, float]]:
    cols = columns or AMP_FEATURES
    y = target_amplitude(df)
    ok_ = y.notna().to_numpy()
    X, _ = _impute(feats[cols][ok_], feats[cols][ok_].iloc[:1])
    _, m = _ridge(X, y[ok_].to_numpy(), X[:1])
    return sorted(zip(cols, m.coef_.tolist()), key=lambda kv: -abs(kv[1]))


def evaluate_direction(df: pd.DataFrame, feats: pd.DataFrame, n_folds: int = 5, purge_days: int = 10) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    y = (df["car"] > 0).astype(int)
    folds = walk_forward_folds(df["day0"], n_folds, purge_days=purge_days)
    if not folds:
        return {"status": "insufficient", "n": len(df)}
    p_all, base_all, y_all = [], [], []
    for train, test in folds:
        Xtr, Xte = _impute(feats.iloc[train][DIR_FEATURES], feats.iloc[test][DIR_FEATURES])
        if y.iloc[train].nunique() < 2:
            continue
        clf = LogisticRegression(C=0.3, max_iter=500).fit(Xtr, y.iloc[train])
        p_all.append(clf.predict_proba(Xte)[:, 1])
        base_all.append(np.full(len(test), y.iloc[train].mean()))
        y_all.append(y.iloc[test].to_numpy())
    if not p_all:
        return {"status": "insufficient", "n": len(df)}
    p, b, t = np.concatenate(p_all), np.concatenate(base_all), np.concatenate(y_all)
    auc = float(roc_auc_score(t, p)) if len(set(t)) == 2 else np.nan
    brier_m, brier_b = (p - t) ** 2, (b - t) ** 2
    dm = diebold_mariano(brier_m, brier_b, h=1)
    bins = pd.qcut(pd.Series(p).rank(method="first"), min(10, max(len(p) // 15, 2)), labels=False)
    calib = [[float(p[bins == k].mean()), float(t[bins == k].mean()), int((bins == k).sum())] for k in sorted(set(bins))]
    return {"status": "ok", "n": len(t), "auc": auc, "hit": float(((p > 0.5) == t).mean()), "hit_base": float(((b > 0.5) == t).mean()),
            "brier": float(brier_m.mean()), "brier_base": float(brier_b.mean()), "dm_p": dm.get("p_value"), "dm_stat": dm.get("dm_stat"), "calibration": calib,
            "prior": float(t.mean())}
