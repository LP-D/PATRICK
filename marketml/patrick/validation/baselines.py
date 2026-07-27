"""Baselines systématiques (Phase 0.6) : classe majoritaire, persistance, HAR-RV —
calculées pour chaque (horizon, fold, régime) walk-forward et ajoutées au
leaderboard à côté des modèles réels. Sans ça, un F1_dir de 0.55 a l'air bon dans
l'absolu ; à côté d'une persistance à 0.53, il ne vaut presque rien.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.validation.metrics import metrics

BASELINE_NAMES = ("BASELINE_majority", "BASELINE_persistence", "BASELINE_har_rv")


def majority_class_predictions(y_tr: np.ndarray, n: int) -> np.ndarray:
    """Prédit partout la classe la plus fréquente du train."""
    values, counts = np.unique(y_tr, return_counts=True)
    majority = values[np.argmax(counts)]
    return np.full(n, majority, dtype=int)


def persistence_predictions(target_series: pd.Series, idx: pd.DatetimeIndex,
                             te_mask: np.ndarray, horizon: int) -> np.ndarray:
    """Prédit, pour chaque date de test, la classe réalisée sur la fenêtre de
    `horizon` observations précédente dans `target_series` (déjà connue à la date
    de décision) — le baseline "rien ne change" classique en séries temporelles."""
    shifted = target_series.shift(horizon)
    persisted = shifted.reindex(idx).values[te_mask]
    fallback = target_series.mode().iloc[0] if len(target_series) else 0
    persisted = np.where(pd.isna(persisted), fallback, persisted).astype(int)
    return persisted


def _classify_like_target(r: float, q25: float, q75: float) -> int:
    if r < q25:
        return 0
    if r < 0:
        return 1
    if r < q75:
        return 2
    return 3


def har_rv_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                        tr_mask: np.ndarray, te_mask: np.ndarray,
                        thr: dict, reg_r: pd.Series) -> np.ndarray | None:
    """Baseline HAR-RV (Corsi) : régression linéaire (moindres carrés, ajustée sur
    le train uniquement) de la vol réalisée du lendemain sur ses moyennes
    glissantes 1j/5j/22j.

    Approximation documentée : HAR-RV prédit nativement une MAGNITUDE de
    volatilité, pas une direction — la cible de ce projet est direction+amplitude
    (4 classes). On combine donc : direction = signe du dernier rendement connu
    (persistance de signe, l'a-priori directionnel le plus neutre possible) ;
    amplitude = le niveau de RV prédit par HAR-RV, reclassé FORT/FAIBLE via les
    MÊMES seuils causaux (`thr`, par régime) que `build_target` — donc directement
    comparable aux classes réelles plutôt qu'une échelle inventée pour l'occasion.

    Retourne None si le train est trop court pour ajuster HAR-RV (baseline omise
    du leaderboard plutôt que polluée de NaN).
    """
    ret = price_series.pct_change()
    rv = ret.pow(2)
    feat = pd.DataFrame({
        "rv_1d": rv,
        "rv_5d": rv.rolling(5).mean(),
        "rv_22d": rv.rolling(22).mean(),
    })
    target_rv = rv.shift(-1)  # RV du jour suivant, à prédire à partir d'aujourd'hui
    data = pd.concat([feat, target_rv.rename("y")], axis=1).dropna()
    tr_dates = set(idx[tr_mask])
    fit_data = data.loc[data.index.isin(tr_dates)]
    if len(fit_data) < 60:
        return None

    X_fit = fit_data[["rv_1d", "rv_5d", "rv_22d"]].values
    y_fit = fit_data["y"].values
    X_fit_design = np.column_stack([np.ones(len(X_fit)), X_fit])
    coef, *_ = np.linalg.lstsq(X_fit_design, y_fit, rcond=None)

    feat_at_idx = feat.reindex(idx).values
    valid = ~np.isnan(feat_at_idx).any(axis=1)
    design = np.column_stack([np.ones(len(feat_at_idx)), np.nan_to_num(feat_at_idx)])
    rv_pred = np.where(valid, design @ coef, np.nan)

    sign_persist = np.sign(ret.reindex(idx).shift(1).values)
    sign_persist = np.where(sign_persist == 0, 1.0, sign_persist)

    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        reg = reg_al[i]
        q25, q75 = thr.get(reg, thr.get("GLOBAL", (0, 0)))
        rv_i = rv_pred[i]
        s = sign_persist[i] if not np.isnan(sign_persist[i]) else 1.0
        amplitude_proxy = s * np.sqrt(max(rv_i, 0.0)) if not np.isnan(rv_i) else 0.0
        preds[i] = _classify_like_target(amplitude_proxy, q25, q75)
    return preds[te_mask]


def compute_baselines(price_series: pd.Series, target_series: pd.Series,
                       idx: pd.DatetimeIndex, tr_mask: np.ndarray, te_mask: np.ndarray,
                       y_tr: np.ndarray, y_te: np.ndarray, horizon: int,
                       thr: dict, reg_r: pd.Series) -> dict[str, dict]:
    """Retourne {nom_baseline: metrics(...)} pour toutes les baselines calculables
    sur ce fold. HAR-RV est absent du dict (pas de clé) si l'historique de train
    est trop court, plutôt que de polluer le leaderboard avec des NaN."""
    out = {
        "BASELINE_majority": metrics(y_te, majority_class_predictions(y_tr, len(y_te))),
        "BASELINE_persistence": metrics(
            y_te, persistence_predictions(target_series, idx, te_mask, horizon)),
    }
    har_pred = har_rv_predictions(price_series, idx, tr_mask, te_mask, thr, reg_r)
    if har_pred is not None:
        out["BASELINE_har_rv"] = metrics(y_te, har_pred)
    return out
