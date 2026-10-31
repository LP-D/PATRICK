"""Décision de direction à partir de P(hausse), et mesures qui n'en dépendent pas (AUC).

Pourquoi (analyse du 2026-10-31, 3 431 runs, holdout) : `F1_dir` vient de la CLASSE la plus probable parmi 4 (baisse forte / baisse / hausse /
hausse forte), ramenée à sa direction. Ce n'est pas la direction la plus probable : [0,34 ; 0,16 ; 0,26 ; 0,24] donne « baisse forte » donc
BAISSE alors que P(hausse) = 0,50, et sous SMOTE les probabilités sont décalées de leur centre. Sur le holdout, la direction tirée de
P(hausse) avec un seuil qui suit la médiane des prédictions RÉCENTES du modèle fait +0,009 de F1 (± 0,002) à +0,014 (seuil global, non
causal) contre l'argmax, et +0,03 aux horizons >= 5 jours. L'AUC de direction, elle, ne dépend d'aucun seuil : c'est le critère de
sélection par défaut depuis cette date (`SelectionConfig.criterion`) — le classement par AUC en validation croisée prédit mieux le holdout
(corrélation de rang +0,37) que celui par F1 (+0,11).

Tout est causal : la décision d'une ligne n'utilise que les P(hausse) des lignes qui la précèdent (jamais un étiquetage, jamais une ligne
future)."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import f1_score, roc_auc_score

TRAIL_WINDOW = 120       # prédictions récentes qui fixent le centre de la décision (un peu plus de cinq mois de séances)
MIN_HISTORY = 10         # en dessous, le centre est 0,5 : pas d'historique, pas de recentrage

METRIC_AUC = "AUC_dir"
METRIC_F1 = "F1_dir_p"
METRIC_ACC = "Acc_dir_p"


def trailing_median(p_up, window: int = TRAIL_WINDOW, min_history: int = MIN_HISTORY, fallback: float = 0.5) -> np.ndarray:
    """Pour chaque ligne i, la médiane des `window` valeurs qui la PRÉCÈDENT (`p_up[i-window:i]`) ; `fallback` tant qu'il y en a moins de
    `min_history`. La ligne i elle-même n'y est jamais."""
    p = np.asarray(p_up, dtype=float).ravel()
    n = len(p)
    out = np.full(n, float(fallback))
    for i in range(min_history, min(window, n)):          # début : fenêtre qui grandit
        out[i] = np.nanmedian(p[:i])
    if n > window:                                          # ensuite : fenêtre glissante, vectorisée
        windows = np.lib.stride_tricks.sliding_window_view(p, window)[:-1]    # windows[j] = p[j:j+window], sert la ligne j+window
        out[window:] = np.nanmedian(windows, axis=1)
    return out


def direction_from_p_up(p_up, window: int = TRAIL_WINDOW, min_history: int = MIN_HISTORY) -> np.ndarray:
    """Direction prédite (1 = hausse) : P(hausse) au-dessus de la médiane de ses prédécesseurs (0,5 sans historique)."""
    p = np.asarray(p_up, dtype=float).ravel()
    return (p > trailing_median(p, window, min_history)).astype(int)


def direction_metrics(y_up, p_up, window: int = TRAIL_WINDOW, min_history: int = MIN_HISTORY) -> dict[str, float]:
    """`{AUC_dir, F1_dir_p, Acc_dir_p}` pour une série chronologique de lignes de test.

    `y_up` : 1 si la classe réelle est une hausse (classes 2 et 3), 0 sinon. `p_up` : P(hausse) du modèle. `AUC_dir` : aire sous la courbe
    ROC de P(hausse) contre la direction réelle (0,5 = hasard, aucun seuil). `F1_dir_p` : F1 moyen des deux directions pour la décision
    `direction_from_p_up`. NaN quand une seule direction est présente ou que P(hausse) manque (une métrique absente vaut mieux qu'un 0)."""
    y = np.asarray(y_up, dtype=float).ravel()
    p = np.asarray(p_up, dtype=float).ravel()
    if len(y) != len(p) or not len(y) or not (np.isfinite(y) & np.isfinite(p)).any():
        return {METRIC_AUC: float("nan"), METRIC_F1: float("nan"), METRIC_ACC: float("nan")}
    keep = np.isfinite(y) & np.isfinite(p)
    y, p = y[keep].astype(int), p[keep]
    decided = direction_from_p_up(p, window, min_history)
    out = {METRIC_ACC: round(float((decided == y).mean()), 4)}
    if len(np.unique(y)) < 2:
        return {METRIC_AUC: float("nan"), METRIC_F1: float("nan"), **out}
    out[METRIC_AUC] = round(float(roc_auc_score(y, p)), 4)
    out[METRIC_F1] = round(float(f1_score(y, decided, average="macro", zero_division=0)), 4)
    return out
