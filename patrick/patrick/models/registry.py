"""Registre des 5 algos ML établis (VIX_FINAL_ML_SCAN) — hyperparamètres par
défaut identiques à ceux validés dans le projet, ré-affinables via Optuna."""
from __future__ import annotations

from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from xgboost import XGBClassifier

ML_ALGOS = ("XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost")


def get_classifier(algo: str, seed: int = 42, **overrides):
    if algo == "XGBoost":
        params = dict(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                      colsample_bytree=0.8, min_child_weight=3, eval_metric="mlogloss",
                      objective="multi:softprob", random_state=seed, n_jobs=-1, verbosity=0)
        params.update(overrides)
        return XGBClassifier(**params)
    if algo == "LightGBM":
        params = dict(n_estimators=200, max_depth=5, learning_rate=0.05, num_leaves=31,
                      min_child_samples=10, subsample=0.8, class_weight="balanced",
                      random_state=seed, verbose=-1, n_jobs=-1)
        params.update(overrides)
        return LGBMClassifier(**params)
    if algo == "RandomForest":
        params = dict(n_estimators=200, max_depth=6, min_samples_leaf=5,
                      class_weight="balanced", random_state=seed, n_jobs=-1)
        params.update(overrides)
        return RandomForestClassifier(**params)
    if algo == "GradientBoosting":
        params = dict(n_estimators=200, learning_rate=0.05, max_depth=4,
                      min_samples_leaf=10, subsample=0.8, random_state=seed)
        params.update(overrides)
        return GradientBoostingClassifier(**params)
    if algo == "CatBoost":
        params = dict(iterations=200, depth=6, learning_rate=0.05, loss_function="MultiClass",
                      auto_class_weights="Balanced", random_state=seed, verbose=False,
                      allow_writing_files=False)
        params.update(overrides)
        return CatBoostClassifier(**params)
    raise ValueError(f"Algo ML inconnu: '{algo}' (attendu: {ML_ALGOS})")
