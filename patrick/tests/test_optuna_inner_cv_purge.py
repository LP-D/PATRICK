"""F02 -- Optuna's inner cross-validation must be purged and embargoed like
the outer walk-forward.

`tune_config` used `TimeSeriesSplit(n_splits)` with no gap: the last
training rows of each inner split carry labels (forward returns over
`horizon` bars) that overlap the validation rows' own label windows -- the
tuned hyperparameters were chosen on a leaky score. The outer loop already
separates train and test by `horizon` bars (embargo, or purge+embargo); the
inner loop now applies the same separation.
"""
from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest
from sklearn.model_selection import TimeSeriesSplit

from patrick.tuning import optuna_runner


class _RowSpy:
    """Stands in for a classifier: records the row ids (column 0) it is fit
    and evaluated on, predicts class 0."""

    fits: ClassVar[list[np.ndarray]] = []
    preds: ClassVar[list[np.ndarray]] = []

    def __init__(self, **kwargs):
        pass

    def fit(self, X, y, **kwargs):
        _RowSpy.fits.append(np.asarray(X[:, 0]).astype(int))
        return self

    def predict(self, X):
        _RowSpy.preds.append(np.asarray(X[:, 0]).astype(int))
        return np.zeros(len(X), dtype=int)


@pytest.fixture
def spy(monkeypatch):
    _RowSpy.fits, _RowSpy.preds = [], []
    monkeypatch.setattr(optuna_runner, "get_classifier", lambda algo, seed=42, **kw: _RowSpy())
    return _RowSpy


def _xy(n=300):
    X = np.c_[np.arange(n, dtype=float), np.random.default_rng(0).normal(size=(n, 3))]
    y = np.arange(n) % 4
    return X, y


def test_unpurged_time_series_split_puts_the_row_just_before_validation_in_train():
    """The defect, stated on sklearn's own splitter: no gap by default."""
    for tr, va in TimeSeriesSplit(n_splits=3).split(np.zeros((300, 1))):
        assert va.min() - tr.max() == 1


@pytest.mark.parametrize("horizon, embargo_bars, expected_gap", [(5, None, 5), (10, 3, 10), (1, None, 1)])
def test_inner_cv_separates_train_and_validation_by_the_label_horizon(spy, horizon, embargo_bars, expected_gap):
    X, y = _xy()
    optuna_runner.tune_config(X, y, "RandomForest", "none", n_trials=1, cv_splits=3,
                              horizon=horizon, embargo_bars=embargo_bars)
    assert len(spy.fits) == 3
    for train_rows, val_rows in zip(spy.fits, spy.preds):
        assert val_rows.min() - train_rows.max() - 1 >= expected_gap


def test_inner_cv_adds_the_purge_when_the_outer_loop_purges(spy):
    X, y = _xy()
    optuna_runner.tune_config(X, y, "RandomForest", "none", n_trials=1, cv_splits=3,
                              horizon=5, embargo_bars=5, purge=True)
    for train_rows, val_rows in zip(spy.fits, spy.preds):
        assert val_rows.min() - train_rows.max() - 1 >= 10


def test_inner_cv_version_is_part_of_the_persisted_study_identity():
    """A persisted study (`patrick resume`) is reloaded by name: trials
    scored under the leaky CV must not be resumed as if comparable."""
    assert optuna_runner.INNER_CV_VERSION
    assert optuna_runner.study_name_for("run", "abc", 5, "GLOBAL", 8, "SMOTE", "XGBoost").endswith(
        optuna_runner.INNER_CV_VERSION)


def test_long_horizon_reduces_the_number_of_inner_splits_before_giving_up(spy):
    X, y = _xy(900)
    optuna_runner.tune_config(X, y, "RandomForest", "none", n_trials=1, cv_splits=3, horizon=252)
    assert 1 <= len(spy.fits) < 3
    for train_rows, val_rows in zip(spy.fits, spy.preds):
        assert val_rows.min() - train_rows.max() - 1 >= 252


def test_infeasible_inner_cv_raises_a_dedicated_error(spy):
    X, y = _xy(300)
    with pytest.raises(optuna_runner.InnerCVInfeasible):
        optuna_runner.tune_config(X, y, "RandomForest", "none", n_trials=1, cv_splits=3, horizon=756)
