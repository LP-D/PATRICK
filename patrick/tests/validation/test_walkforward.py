import pandas as pd

from patrick.validation.walkforward import build_fold_cuts


def test_build_fold_cuts_shape_and_monotonic():
    dates = pd.bdate_range("2010-01-01", periods=5000)
    cuts = build_fold_cuts(dates, n_wf_folds=5, min_train_frac=0.40)
    assert len(cuts) == 6  # n_wf_folds + 1 bornes
    assert cuts[0] == int(len(dates) * 0.40)
    assert cuts[-1] == len(dates)
    assert all(cuts[i] < cuts[i + 1] for i in range(len(cuts) - 1))


def test_build_fold_cuts_respects_min_train_frac():
    dates = pd.bdate_range("2010-01-01", periods=1000)
    cuts = build_fold_cuts(dates, n_wf_folds=5, min_train_frac=0.6)
    assert cuts[0] == 600
