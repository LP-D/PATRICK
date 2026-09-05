"""Optuna hyperparameter search (TPE + MedianPruner, TimeSeriesSplit CV) —
VIX_FINAL_OPTUNA methodology: on this project, fine tuning improved 1 config
out of 10 (average delta -0.0145) — most of the gain comes from model/
feature choice, not fine tuning, but the step remains occasionally useful.
"""
from __future__ import annotations

import numpy as np
import optuna
from sklearn.model_selection import TimeSeriesSplit

from patrick.config import defaults as D
from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.validation.metrics import metrics

optuna.logging.set_verbosity(optuna.logging.WARNING)


def suggest_params(trial: optuna.Trial, algo: str, bounds: dict | None = None) -> dict:
    """`bounds` (Phase 1, feature/hyperparams-ui): optional per-run override
    of the [low, high] search bounds, keyed `{algo: {param: [low, high]}}`
    (see `RunConfig.tuning.optuna_bounds`, `webapp/forms.py::
    _parse_optuna_bounds`). Any algo/param absent from `bounds` -- including
    `bounds=None` entirely, the default -- falls back to
    `D.DEFAULT_OPTUNA_BOUNDS`, IDENTICAL to the ranges historically hardcoded
    here: a run that does not customize the search space searches exactly
    the same one as before this parameter existed. The structure of the
    search itself (which params exist, int vs float, log-scale) is NOT
    overridable -- only its extent -- and stays declared in
    `D.OPTUNA_PARAM_SPECS`."""
    specs = D.OPTUNA_PARAM_SPECS.get(algo)
    if specs is None:
        raise ValueError(f"Unknown algo for Optuna: '{algo}'")
    algo_bounds = (bounds or {}).get(algo) or {}
    out = {}
    for name, spec in specs.items():
        lo, hi = algo_bounds.get(name) or D.DEFAULT_OPTUNA_BOUNDS[algo][name]
        if spec["type"] == "int":
            out[name] = trial.suggest_int(name, int(lo), int(hi))
        else:
            out[name] = trial.suggest_float(name, float(lo), float(hi), log=bool(spec.get("log", False)))
    return out


def tune_config(X: np.ndarray, y: np.ndarray, algo: str, sampler_name: str,
                 n_trials: int = 100, cv_splits: int = 3, seed: int = 42,
                 storage_path: str | None = None, study_name: str | None = None,
                 bounds: dict | None = None) -> tuple[dict, float]:
    """`storage_path`/`study_name` (Phase 3.2, `patrick resume`): persists
    the study in a dedicated SQLite file (`optuna.db`, never `patrick.db` —
    Optuna's internal schema changes between versions, must not be coupled
    to the business tables) instead of keeping it in memory.
    `load_if_exists=True` resumes a study already started under this name
    rather than recreating an empty one: an interrupted `patrick run`/
    `patrick resume` (worker killed, process/machine restarted) that
    relaunches the same run resumes the trials already done for this config
    instead of starting from zero. Default behavior (both None) unchanged:
    in-memory study, lost at the end of the call.

    `bounds` (Phase 1, feature/hyperparams-ui): forwarded as-is to
    `suggest_params` -- see its docstring. `None` (default) preserves the
    exact search space hardcoded before this parameter existed."""
    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, algo, bounds)
        tscv = TimeSeriesSplit(n_splits=cv_splits)
        scores = []
        for i, (tr_idx, va_idx) in enumerate(tscv.split(X)):
            X_tr, X_va = X[tr_idx], X[va_idx]
            y_tr, y_va = y[tr_idx], y[va_idx]
            try:
                Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_tr, y_tr)
            except Exception:
                Xr, yr = X_tr, y_tr
            clf = get_classifier(algo, seed=seed, **params)
            clf.fit(Xr, yr)
            met = metrics(y_va, clf.predict(X_va))
            scores.append(met["F1_dir"])
            trial.report(float(np.mean(scores)), i)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(scores))

    sampler = optuna.samplers.TPESampler(seed=seed)
    pruner = optuna.pruners.MedianPruner()
    if storage_path:
        if not study_name:
            raise ValueError("study_name required when storage_path is provided (identifies the study to resume).")
        study = optuna.create_study(
            direction="maximize", sampler=sampler, pruner=pruner,
            storage=f"sqlite:///{storage_path}", study_name=study_name, load_if_exists=True,
        )
        # Counts ALL trials already in the database (including pruned/failed)
        # for this study, not just this call's -> a resume only relaunches
        # the remaining balance rather than `n_trials` extra trials every time.
        n_remaining = max(n_trials - len(study.trials), 0)
        if n_remaining:
            study.optimize(objective, n_trials=n_remaining, show_progress_bar=False)
    else:
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params, study.best_value
