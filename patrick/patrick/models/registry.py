"""Registry of the 5 established ML algos (VIX_FINAL_ML_SCAN) -- default
hyperparameters identical to those validated in the project, refinable via
Optuna."""
from __future__ import annotations

from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from xgboost import XGBClassifier

ML_ALGOS = ("XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost")

# Coordination point (fix/tuning-n-jobs-oversubscription): scan and Optuna
# tuning are strictly sequential -- one config, one walk-forward fold, one
# Optuna trial at a time (tuning/optuna_runner.py::tune_config has no
# n_jobs>1, pipeline/engine.py has no joblib.Parallel) -- so there is never
# more than one classifier being fit at once from this codebase's own
# scheduling. `n_jobs=-1` on that single fit does not queue against other
# fits from here, but it still fans out across every logical core and races
# the OS scheduler against whatever else happens to be running; for
# RandomForest specifically, `-1` forks one joblib/loky worker PROCESS per
# core for every single fit, whose spawn/teardown cost is itself expensive
# and highly variable on Windows. Root-caused via 4 controlled measurements
# of the identical GSPC h1 tuning phase (same code, same config, same
# 6-core/no-hyperthreading hardware): 73s / 1648s / 722s / 2292s -- config
# drift, code drift, and external process contention were each ruled out in
# turn, leaving this thread/process fan-out as the only remaining
# explanation for the run-to-run variance. Single-threaded trades peak
# per-fit speed for determinism; nothing in this pipeline benefits from a
# multi-core fit since nothing else runs concurrently with it anyway.
MODEL_N_JOBS = 1


def get_classifier(algo: str, seed: int = 42, **overrides):
    if algo == "XGBoost":
        params = dict(n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8,
                      colsample_bytree=0.8, min_child_weight=3, eval_metric="mlogloss",
                      objective="multi:softprob", random_state=seed, n_jobs=MODEL_N_JOBS, verbosity=0)
        params.update(overrides)
        return XGBClassifier(**params)
    if algo == "LightGBM":
        params = dict(n_estimators=200, max_depth=5, learning_rate=0.05, num_leaves=31,
                      min_child_samples=10, subsample=0.8, class_weight="balanced",
                      random_state=seed, verbose=-1, n_jobs=MODEL_N_JOBS)
        params.update(overrides)
        return LGBMClassifier(**params)
    if algo == "RandomForest":
        params = dict(n_estimators=200, max_depth=6, min_samples_leaf=5,
                      class_weight="balanced", random_state=seed, n_jobs=MODEL_N_JOBS)
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
                      allow_writing_files=False, thread_count=MODEL_N_JOBS)
        params.update(overrides)
        return CatBoostClassifier(**params)
    raise ValueError(f"Unknown ML algo: '{algo}' (expected: {ML_ALGOS})")
