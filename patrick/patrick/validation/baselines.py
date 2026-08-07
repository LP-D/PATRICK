"""Baselines systématiques (Phase 0.6) : classe majoritaire, persistance, HAR-RV —
calculées pour chaque (horizon, fold, régime) walk-forward et ajoutées au
leaderboard à côté des modèles réels. Sans ça, un F1_dir de 0.55 a l'air bon dans
l'absolu ; à côté d'une persistance à 0.53, il ne vaut presque rien.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.validation.metrics import metrics

BASELINE_NAMES = ("BASELINE_majority", "BASELINE_persistence", "BASELINE_har_rv",
                   "BASELINE_majority_by_regime", "BASELINE_momentum_20", "BASELINE_momentum_5",
                   "BASELINE_random_walk_no_drift", "BASELINE_random_walk_drift")


def majority_class_predictions(y_tr: np.ndarray, n: int) -> np.ndarray:
    """Prédit partout la classe la plus fréquente du train."""
    values, counts = np.unique(y_tr, return_counts=True)
    majority = values[np.argmax(counts)]
    return np.full(n, majority, dtype=int)


def majority_by_regime_predictions(y_tr: np.ndarray, tr_regimes: np.ndarray,
                                    te_regimes: np.ndarray) -> np.ndarray:
    """Classe majoritaire du train, calculée SÉPARÉMENT par régime (Phase X5)
    -- plus exigeante que la majorité globale quand le déséquilibre de classe
    varie selon le régime de marché. Repli sur la majorité globale du train
    si un régime de test n'a aucune observation de train correspondante."""
    global_majority = majority_class_predictions(y_tr, 1)[0]
    per_regime: dict[str, int] = {}
    for reg in np.unique(tr_regimes):
        mask = tr_regimes == reg
        if mask.any():
            values, counts = np.unique(y_tr[mask], return_counts=True)
            per_regime[reg] = int(values[np.argmax(counts)])
    return np.array([per_regime.get(reg, global_majority) for reg in te_regimes], dtype=int)


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


MOMENTUM_WINDOW_FUTURES = 20  # cf. Phase X5 -- momentum documenté sur cette classe
MOMENTUM_WINDOW_CRYPTO = 5    # régimes de volatilité extrêmes, fenêtre plus courte


def momentum_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                          te_mask: np.ndarray, window: int,
                          thr: dict, reg_r: pd.Series) -> np.ndarray:
    """Baseline momentum (Phase X5, futures/crypto) : classe le rendement
    glissant sur `window` jours via les MÊMES seuils causaux (`thr`, par
    régime) que `build_target` -- directement comparable aux classes réelles."""
    mom = price_series.pct_change(window).reindex(idx).values
    reg_al = reg_r.reindex(idx).fillna("GLOBAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        q25, q75 = thr.get(reg_al[i], thr.get("GLOBAL", (0, 0)))
        r = mom[i] if not np.isnan(mom[i]) else 0.0
        preds[i] = _classify_like_target(r, q25, q75)
    return preds[te_mask]


def random_walk_predictions(price_series: pd.Series, idx: pd.DatetimeIndex,
                             tr_mask: np.ndarray, te_mask: np.ndarray, drift: bool,
                             thr: dict, reg_r: pd.Series) -> np.ndarray:
    """Baseline marche aléatoire (Phase X5) : le meilleur prévisionniste pour
    une marche aléatoire SANS dérive (FX, résultat de référence établi en
    recherche FX à horizon court) est "pas de changement" (rendement prévu =
    0), classé via les seuils causaux comme une observation quelconque. AVEC
    dérive (séries macro, convention standard en macro-économétrie) : le
    rendement moyen du train est utilisé comme prévision constante au lieu de
    0. Prévision constante par construction (pas de dépendance à l'historique
    récent, contrairement à la persistance)."""
    if drift:
        ret = price_series.pct_change().reindex(idx)
        train_ret = ret.values[tr_mask]
        train_ret = train_ret[~np.isnan(train_ret)]
        r_hat = float(train_ret.mean()) if len(train_ret) else 0.0
    else:
        r_hat = 0.0
    reg_al = reg_r.reindex(idx).fillna("GLOBAL").values
    preds = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        q25, q75 = thr.get(reg_al[i], thr.get("GLOBAL", (0, 0)))
        preds[i] = _classify_like_target(r_hat, q25, q75)
    return preds[te_mask]


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
                       thr: dict, reg_r: pd.Series,
                       return_predictions: bool = False) -> dict[str, dict] | dict[str, np.ndarray]:
    """Retourne {nom_baseline: metrics(...)} pour toutes les baselines calculables
    sur ce fold (comportement historique, `return_predictions=False`). HAR-RV est
    absent du dict (pas de clé) si l'historique de train est trop court, plutôt
    que de polluer le leaderboard avec des NaN.

    `return_predictions=True` (Phase 2.5, Diebold-Mariano) : renvoie
    {nom_baseline: y_pred} à la place — les prédictions brutes, alignées sur
    `y_te`, nécessaires pour comparer la perte du modèle gagnant à celle d'une
    baseline observation par observation (une moyenne de métriques ne le permet
    pas). Un seul calcul sous-jacent dans les deux cas, pas de duplication."""
    reg_al = reg_r.reindex(idx).values
    preds: dict[str, np.ndarray] = {
        "BASELINE_majority": majority_class_predictions(y_tr, len(y_te)),
        "BASELINE_persistence": persistence_predictions(target_series, idx, te_mask, horizon),
        "BASELINE_majority_by_regime": majority_by_regime_predictions(
            y_tr, reg_al[tr_mask], reg_al[te_mask]),
        "BASELINE_momentum_20": momentum_predictions(
            price_series, idx, te_mask, MOMENTUM_WINDOW_FUTURES, thr, reg_r),
        "BASELINE_momentum_5": momentum_predictions(
            price_series, idx, te_mask, MOMENTUM_WINDOW_CRYPTO, thr, reg_r),
        "BASELINE_random_walk_no_drift": random_walk_predictions(
            price_series, idx, tr_mask, te_mask, drift=False, thr=thr, reg_r=reg_r),
        "BASELINE_random_walk_drift": random_walk_predictions(
            price_series, idx, tr_mask, te_mask, drift=True, thr=thr, reg_r=reg_r),
    }
    har_pred = har_rv_predictions(price_series, idx, tr_mask, te_mask, thr, reg_r)
    if har_pred is not None:
        preds["BASELINE_har_rv"] = har_pred
    if return_predictions:
        return preds
    return {name: metrics(y_te, pred) for name, pred in preds.items()}
