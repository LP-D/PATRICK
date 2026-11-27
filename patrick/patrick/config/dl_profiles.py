"""Profils d'entraînement du deep learning (page /dl) : même mécanique que `training_profiles` (un profil = un PATCH sur la vue du
formulaire, que l'utilisateur relit avant de lancer), appliqué à la configuration de départ du DL (`forms.default_config_dict("dl")`).

`cost` : durée relative d'un run typique (low ≈ 10-20 min, medium ≈ 30-90 min, high ≈ 2 h et plus) sur un processeur sans carte graphique ;
un réseau coûte nettement plus qu'un arbre, d'où des profils plus économes que ceux du machine learning ; `max` ≈ une nuit ou plus par cible.

Comme en machine learning, les profils `dl_value_*` préparent un réseau de valeur exacte (`task: value`, régression du rendement, ADR 0029 /
0032) et `dl_max` / `dl_value_max` la recherche la plus large que la page accepte.
"""
from __future__ import annotations

from patrick.config import defaults as D
from patrick.config.training_profiles import TrainingProfile, apply_patch

__all__ = ["BY_KEY", "PROFILES", "apply_patch", "get"]

_SEQ = ["GRU", "LSTM", "CNN1D"]
_VALUE = {"task": "value", "value_criterion": "IC", "calibration": False}
# Recherche la plus large (2026-11-27) : les cinq architectures, 60 essais Optuna sur 3 finalistes (4 plis de validation), 7 plis
# walk-forward, grille de 6 à 20 variables, réseaux plus profonds et plus longs à entraîner, 5 graines moyennées par modèle.
_MAX = {
    "algos": list(D.ALL_DL_ALGOS), "tuning_enabled": True, "n_trials": 60, "top_k": 3, "cv_splits": 4, "n_wf_folds": 7,
    "n_features_grid": "6,8,10,12,16,20", "dl_n_seeds": 5, "dl_epochs": 100, "dl_patience": 12, "dl_lookback": 60,
    "dl_hidden_size": 128, "dl_n_layers": 3, "dl_n_heads": 8, "dl_dropout": 0.3,
}

PROFILES: tuple[TrainingProfile, ...] = (
    TrainingProfile("dl_quick", "low", {
        "algos": ["MLP"], "tuning_enabled": False, "n_features_grid": "8", "n_wf_folds": 3,
        "dl_epochs": 15, "dl_hidden_size": 32, "dl_n_layers": 1, "dl_patience": 3}, icon="zap"),
    TrainingProfile("dl_standard", "medium", {}, icon="layers"),
    TrainingProfile("dl_sequence", "medium", {
        "algos": _SEQ, "dl_lookback": 30, "dl_epochs": 40, "dl_hidden_size": 64, "n_trials": 20}, icon="activity"),
    TrainingProfile("dl_attention", "high", {
        "algos": ["Transformer"], "dl_lookback": 40, "dl_n_heads": 4, "dl_hidden_size": 64, "dl_n_layers": 2, "dl_epochs": 40,
        "n_trials": 20}, icon="eye"),
    TrainingProfile("dl_sober", "low", {
        "algos": ["MLP", "GRU"], "dl_hidden_size": 16, "dl_dropout": 0.4, "dl_weight_decay": 0.001, "dl_epochs": 25, "dl_patience": 4,
        "n_features_grid": "6,8", "tuning_enabled": False}, icon="shield"),
    TrainingProfile("dl_ensemble", "high", {
        "algos": list(D.ALL_DL_ALGOS), "dl_n_seeds": 3, "dl_epochs": 40, "n_trials": 25, "top_k": 2, "calibration": True}, icon="layers"),
    TrainingProfile("dl_wide_search", "high", {
        "algos": ["MLP", "GRU", "LSTM"], "n_trials": 60, "top_k": 2, "cv_splits": 4, "n_features_grid": "6,8,10,12,16"}, icon="globe"),
    TrainingProfile("dl_long_memory", "high", {
        "algos": ["GRU", "LSTM"], "dl_lookback": 60, "dl_hidden_size": 96, "dl_n_layers": 2, "dl_epochs": 50, "dl_patience": 8,
        "n_trials": 15}, icon="clock"),
    TrainingProfile("dl_max", "max", {**_MAX, "calibration": True}, icon="zap"),
    # --- Valeur exacte. Les 84 premiers runs (27/11) étaient tous des MLP sans réglage à 8 variables, 6 horizons : IC médiane du holdout
    # nulle à 1 jour, +0,12 à 5 et 7 jours. D'où un profil rapide qui reprend ce cadre, un profil séquences et un profil horizons longs.
    TrainingProfile("dl_value_quick", "low", {
        **_VALUE, "algos": ["MLP"], "tuning_enabled": False, "n_features_grid": "8", "n_wf_folds": 3,
        "dl_epochs": 15, "dl_hidden_size": 32, "dl_n_layers": 1, "dl_patience": 3}, icon="zap", task="value"),
    TrainingProfile("dl_value_sequence", "medium", {
        **_VALUE, "algos": _SEQ, "dl_lookback": 30, "dl_epochs": 40, "dl_hidden_size": 64, "n_trials": 20}, icon="activity", task="value"),
    TrainingProfile("dl_value_swing", "medium", {
        **_VALUE, "algos": ["MLP", "GRU"], "horizons": [5, 7, 10, 20], "n_trials": 20}, icon="calendar", task="value"),
    TrainingProfile("dl_value_max", "max", {**_MAX, **_VALUE}, icon="zap", task="value"),
)

BY_KEY: dict[str, TrainingProfile] = {p.key: p for p in PROFILES}


def get(key: str) -> TrainingProfile | None:
    return BY_KEY.get(key)
