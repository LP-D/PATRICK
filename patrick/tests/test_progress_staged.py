"""Progress of a run (`worker._estimate_total`) in staged screening.

Exhaustive: every candidate is fitted on every fold. Staged: every candidate
on fold 1, then only the finalists on the remaining folds -- the total the
progress bar and the ETA divide by must follow, otherwise the bar stops at a
fraction of its length."""
from __future__ import annotations

import pytest

from patrick import worker
from patrick.config.schema import RunConfig


def _config(mode: str, finalists: int = 8, horizons=(1, 5), regimes=("GLOBAL",), n_grid=11, algos=4,
            folds=5) -> RunConfig:
    return RunConfig.model_validate({
        "name": "t",
        "objective": {"target_symbol": "^TEST", "horizons": list(horizons), "regimes": list(regimes)},
        "selection": {"n_features_grid": list(range(5, 5 + n_grid)), "screening_mode": mode,
                      "screening_finalists_per_group": finalists},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["XGBoost", "LightGBM", "RandomForest", "CatBoost"][:algos]},
        "validation": {"n_wf_folds": folds},
    })


def test_exhaustive_total_is_the_full_grid_on_every_fold():
    assert worker._estimate_total(_config("exhaustive")) == 2 * 5 * 11 * 4          # 440


@pytest.mark.parametrize("finalists, per_horizon", [(1, 44 + 1 * 4), (8, 44 + 8 * 4), (3, 44 + 3 * 4)])
def test_staged_total_is_the_first_fold_grid_plus_finalists_on_later_folds(finalists, per_horizon):
    assert worker._estimate_total(_config("staged", finalists)) == 2 * per_horizon


def test_finalists_are_capped_by_the_number_of_candidates():
    # 100 finalists asked, only 44 candidates exist: same as exhaustive
    assert worker._estimate_total(_config("staged", 100)) == worker._estimate_total(_config("exhaustive"))


def test_staged_total_counts_each_regime_as_its_own_group():
    cfg = _config("staged", 1, horizons=(1,), regimes=("GLOBAL", "CALME"))
    assert worker._estimate_total(cfg) == 2 * (44 + 1 * 4)


# ---------------------------------------------------------------------------
# Total-window screening: ONE fit per candidate on the whole out-of-sample
# window, then the finalists on every walk-forward fold.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("finalists, per_horizon", [(1, 44 + 1 * 5), (3, 44 + 3 * 5)])
def test_total_window_total_is_one_fit_per_candidate_plus_finalists_on_every_fold(finalists, per_horizon):
    assert worker._estimate_total(_config("total_window", finalists)) == 2 * per_horizon


def test_total_window_finalists_are_capped_by_the_number_of_candidates():
    assert worker._estimate_total(_config("total_window", 100)) == 2 * (44 + 44 * 5)


def test_total_window_counts_each_regime_as_its_own_group():
    cfg = _config("total_window", 1, horizons=(1,), regimes=("GLOBAL", "CALME"))
    assert worker._estimate_total(cfg) == 2 * (44 + 1 * 5)
