"""Optuna hyperparameter search (TPE + MedianPruner, purged/embargoed
time-series CV) — VIX_FINAL_OPTUNA methodology: on this project, fine tuning
improved 1 config out of 10 (average delta -0.0145) — most of the gain comes
from model/feature choice, not fine tuning, but the step remains
occasionally useful.

F02 -- the inner CV used `TimeSeriesSplit(n_splits)` with no gap: the last
training rows of each split carried labels (forward returns over `horizon`
bars) overlapping the validation rows' label windows, so hyperparameters
were chosen on a leaky score. Train and validation are now separated by the
same number of rows the outer walk-forward removes (`inner_cv_gap`).
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


def safe_resample(sampler_name: str, seed: int, X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Applies the configured sampler, falling back to the raw `(X, y)` when
    it cannot fit-resample this fold/split's data (e.g. a class too small for
    SMOTE's k-neighbors). Shared by the per-trial Optuna CV loop below
    (`tune_config`) and the main scan's `_fit_eval`
    (`pipeline/engine.py`) -- previously an identical try/except duplicated
    in both places."""
    try:
        return get_sampler(sampler_name, seed).fit_resample(X, y)
    except Exception:  # noqa: BLE001 -- imblearn samplers raise various errors on small classes; documented raw fallback
        return X, y


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


# Part of every persisted study name (`study_name_for`): `patrick resume`
# reloads a study by name, and trials scored under a different inner-CV
# protocol (the unpurged one before F02) are not comparable.
INNER_CV_VERSION = "cvpurged1"


def study_name_for(run_name: str, config_hash: str, horizon: int, regime: str, n_feat: int,
                   sampler_name: str, algo: str) -> str:
    return (f"{run_name}_{config_hash}_h{horizon}_{regime}_N{n_feat}_{sampler_name}_{algo}"
            f"_{INNER_CV_VERSION}")


def inner_cv_gap(horizon: int, embargo_bars: int | None = None, purge: bool = False,
                 embargo_enabled: bool = True) -> int:
    """Rows left out between each inner train block and its validation
    block -- mirrors the outer walk-forward (`_FoldContext.prepare`): purge
    (`horizon` rows, if enabled) + embargo (`embargo_bars`, `None` -> derived
    from the horizon, if enabled), never less than `horizon`: label windows
    of train and validation rows must never overlap, whatever the toggles."""
    h = max(int(horizon), 1)
    e = (h if embargo_bars is None else max(int(embargo_bars), 0)) if embargo_enabled else 0
    return max((h if purge else 0) + e, h)


class InnerCVInfeasible(ValueError):
    """Not enough rows for even a 2-split purged inner CV at this horizon."""


_MIN_INNER_TRAIN_ROWS = 20


def feasible_inner_splits(n_rows: int, cv_splits: int, gap: int) -> int:
    """Largest number of inner splits in [2, cv_splits] leaving at least
    `_MIN_INNER_TRAIN_ROWS` rows in the first train block once `gap` rows are
    removed (`TimeSeriesSplit` default test size: n // (splits + 1)). Long
    horizons (252/504/756 bars) can exhaust a short train set: fewer, longer
    splits are used before giving up (`InnerCVInfeasible`)."""
    for k in range(max(int(cv_splits), 2), 1, -1):
        if n_rows - gap - k * (n_rows // (k + 1)) >= _MIN_INNER_TRAIN_ROWS:
            return k
    raise InnerCVInfeasible(
        f"{n_rows} rows cannot hold a purged inner CV with a {gap}-row gap "
        f"(needs >= {_MIN_INNER_TRAIN_ROWS} rows in the first train block).")


def tune_config(X: np.ndarray, y: np.ndarray, algo: str, sampler_name: str,
                 n_trials: int = 100, cv_splits: int = 3, seed: int = 42,
                 storage_path: str | None = None, study_name: str | None = None,
                 bounds: dict | None = None, horizon: int = 1,
                 embargo_bars: int | None = None, purge: bool = False,
                 embargo_enabled: bool = True, registry=None) -> tuple[dict, float]:
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
    exact search space hardcoded before this parameter existed.

    `horizon`/`embargo_bars`/`purge`/`embargo_enabled` (F02): the rows of
    `X` are in chronological order; see `inner_cv_gap`. Rows removed
    upstream (flat labels, regime filter) only widen the real separation in
    bars.

    `registry` (F03): optional Optuna callback -- typically
    `tracking.db.TrialRecorder` -- called once per finished trial, so every
    evaluated configuration reaches the DSR's `n_trials`."""
    callbacks = [registry] if registry is not None else None
    gap = inner_cv_gap(horizon, embargo_bars, purge, embargo_enabled)
    n_splits = feasible_inner_splits(len(X), cv_splits, gap)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, algo, bounds)
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
        scores = []
        for i, (tr_idx, va_idx) in enumerate(tscv.split(X)):
            X_tr, X_va = X[tr_idx], X[va_idx]
            y_tr, y_va = y[tr_idx], y[va_idx]
            Xr, yr = safe_resample(sampler_name, seed, X_tr, y_tr)
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
            study.optimize(objective, n_trials=n_remaining, show_progress_bar=False, callbacks=callbacks)
    else:
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False, callbacks=callbacks)
    return study.best_params, study.best_value
