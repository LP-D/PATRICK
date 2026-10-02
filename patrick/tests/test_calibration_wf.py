"""Roadmap bloc 3 -- isotonic/Platt calibration in walk-forward, and a
calibrated P(up) per prediction (prerequisite of Black-Litterman v2, which
today uses the predicted class's confidence as a proxy).

Defects of the Phase 5.3 calibration path, proven here:
1. the isotonic map was fitted on the SMOTE-resampled train (balanced,
   partly synthetic classes), i.e. calibrated to the wrong class priors;
2. its "most recent 15% of the train" threshold slice was the TAIL OF THE
   RESAMPLED ARRAY -- imblearn appends the synthetic rows at the end, so
   the threshold was chosen on synthetic samples;
3. `CalibratedClassifierCV(cv=3)` splits stratified k-fold, not in time.
Now: fit rows | purge gap (label overlap) | calibration rows | threshold
rows, all REAL rows in chronological order; resampling touches the fit
rows only.
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.datasets import make_classification

from patrick.models import calibration as cal
from patrick.pipeline import engine


def _data(n=900, seed=0):
    X, y = make_classification(n_samples=n, n_features=10, n_informative=6, n_classes=4,
                               n_clusters_per_class=1, weights=[0.1, 0.4, 0.4, 0.1], random_state=seed)
    split = int(n * 0.75)
    return X[:split], y[:split], X[split:], y[split:]


def test_split_is_chronological_with_a_purge_gap():
    s = cal.calibration_split(1000, frac=0.2, gap=5)
    assert s.fit_end == 1000 - 200 - 5
    assert s.cal_start == 800 and s.thr_start == 900 and s.n == 1000
    assert cal.calibration_split(60, frac=0.2) is None  # too short: no calibration rather than a degenerate one


@pytest.mark.parametrize("sampler", ["SMOTE", "none"])
def test_calibration_and_threshold_see_real_chronological_rows_only(monkeypatch, sampler):
    X_tr, y_tr, X_te, y_te = _data()
    seen = {}
    real_fit = cal.fit_prefit_calibrator
    real_thr = cal.search_threshold

    def spy_fit(clf, X_cal, y_cal, method="isotonic"):
        seen["cal"] = X_cal.copy()
        return real_fit(clf, X_cal, y_cal, method)

    def spy_thr(cal_clf, X_val, y_val, *a, **k):
        seen["thr"] = X_val.copy()
        return real_thr(cal_clf, X_val, y_val, *a, **k)

    monkeypatch.setattr(cal, "fit_prefit_calibrator", spy_fit)
    monkeypatch.setattr(cal, "search_threshold", spy_thr)
    engine._fit_eval_full(X_tr, y_tr, X_te, y_te, sampler, "RandomForest", 42, calibration=True,
                          calibration_gap=5)
    s = cal.calibration_split(len(X_tr), gap=5)
    np.testing.assert_array_equal(seen["cal"], X_tr[s.cal_start:s.thr_start])
    np.testing.assert_array_equal(seen["thr"], X_tr[s.thr_start:])


@pytest.mark.parametrize("method", ["isotonic", "sigmoid"])
def test_calibrated_path_returns_a_probability_of_up(method):
    X_tr, y_tr, X_te, y_te = _data()
    met, _y_pred, _conf, p_up = engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "none", "RandomForest", 42,
                                                    calibration=True, calibration_method=method)
    assert p_up.shape == (len(y_te),) and np.all((p_up >= 0) & (p_up <= 1))
    assert "Brier_up" in met and "ECE_up" in met


def test_uncalibrated_path_also_reports_p_up_and_its_calibration_quality():
    X_tr, y_tr, X_te, y_te = _data()
    met, _y_pred, _conf, p_up = engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "SMOTE", "XGBoost", 42)
    y_up = (y_te >= 2).astype(float)
    assert met["Brier_up"] == pytest.approx(np.mean((p_up - y_up) ** 2))
    # the legacy 3-tuple API is unchanged
    assert len(engine._fit_eval(X_tr, y_tr, X_te, y_te, "SMOTE", "XGBoost", 42)) == 3


def test_p_up_brier_and_ece_on_hand_computable_inputs():
    proba = np.array([[0.1, 0.2, 0.3, 0.4], [0.5, 0.3, 0.1, 0.1]])
    np.testing.assert_allclose(cal.p_up_from_proba(proba, [0, 1, 2, 3]), [0.7, 0.2])
    np.testing.assert_allclose(cal.p_up_from_proba(proba[:, [0, 1, 3]], [0, 1, 3]), [0.4, 0.1])
    p = np.array([0.9, 0.9, 0.1, 0.1])
    y = np.array([1, 0, 0, 0])
    assert cal.brier_score(p, y) == pytest.approx((0.01 + 0.81 + 0.01 + 0.01) / 4)
    # two bins: {0.1, 0.1} -> mean 0.1 vs freq 0; {0.9, 0.9} -> mean 0.9 vs freq 0.5
    assert cal.expected_calibration_error(p, y, n_bins=2) == pytest.approx(0.5 * 0.1 + 0.5 * 0.4)


# ---------------------------------------------------------------------------
# A calibration slice that does not hold exactly the classes the model was
# fitted on (2026-10-02, HO.PA h=252: "IndexError: index 3 is out of bounds
# for axis 1 with size 3" after 3h of scan). `CalibratedClassifierCV` maps
# the classifier's probability columns to the classes of the calibration
# labels: when the calibration rows miss a class the model outputs, it
# crashes. (The reverse -- an extra class in the calibration rows -- works:
# the calibrator then covers that class too, with probability 0.) Like a
# train too short to be split, the fit falls back to the uncalibrated path
# instead of failing.
# ---------------------------------------------------------------------------

def _data_with_calibration_slice(drop_class_in_cal=None, drop_class_in_fit=None, n=400):
    X_tr, y_tr, X_te, y_te = _data(n=int(n / 0.75))
    s = cal.calibration_split(len(X_tr))
    y_tr = y_tr.copy()
    if drop_class_in_cal is not None:
        y_tr[s.cal_start:s.thr_start][y_tr[s.cal_start:s.thr_start] == drop_class_in_cal] = 2 if drop_class_in_cal != 2 else 1
    if drop_class_in_fit is not None:
        y_tr[:s.fit_end][y_tr[:s.fit_end] == drop_class_in_fit] = 1 if drop_class_in_fit != 1 else 2
    assert (drop_class_in_cal is None) or drop_class_in_cal not in set(y_tr[s.cal_start:s.thr_start])
    assert (drop_class_in_fit is None) or drop_class_in_fit not in set(y_tr[:s.fit_end])
    return X_tr, y_tr, X_te, y_te


def test_classes_match_helper():
    from sklearn.ensemble import RandomForestClassifier

    X, y = make_classification(n_samples=200, n_features=6, n_informative=4, n_classes=4,
                               n_clusters_per_class=1, random_state=0)
    clf = RandomForestClassifier(n_estimators=5, random_state=0).fit(X, y)
    assert cal.calibration_classes_match(clf, y[:60]) is True
    assert cal.calibration_classes_match(clf, y[y != 3][:60]) is False      # a model class missing from the slice
    clf3 = RandomForestClassifier(n_estimators=5, random_state=0).fit(X[y != 0], y[y != 0])
    assert cal.calibration_classes_match(clf3, y[:60]) is True              # extra class in the slice: fine


@pytest.mark.parametrize("method", ["isotonic", "sigmoid"])
def test_a_class_missing_from_the_calibration_rows_falls_back_to_the_uncalibrated_path(method, capsys, monkeypatch):
    monkeypatch.setattr(engine, "_CALIBRATION_SKIPS", 0)
    X_tr, y_tr, X_te, y_te = _data_with_calibration_slice(drop_class_in_cal=3)

    met, y_pred, _conf, p_up = engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "none", "RandomForest", 42,
                                                     calibration=True, calibration_method=method)

    assert len(y_pred) == len(y_te) and "F1_dir" in met
    assert p_up is not None and np.all((p_up >= 0) & (p_up <= 1))
    assert "calibration skipped" in capsys.readouterr().out


@pytest.mark.parametrize("method", ["isotonic", "sigmoid"])
def test_an_extra_class_in_the_calibration_rows_still_calibrates(method, capsys, monkeypatch):
    monkeypatch.setattr(engine, "_CALIBRATION_SKIPS", 0)
    X_tr, y_tr, X_te, y_te = _data_with_calibration_slice(drop_class_in_fit=0)

    _met, y_pred, _conf, p_up = engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "none", "RandomForest", 42,
                                                      calibration=True, calibration_method=method)

    assert len(y_pred) == len(y_te) and np.all((p_up >= 0) & (p_up <= 1))
    assert "calibration skipped" not in capsys.readouterr().out


def test_the_skip_warning_is_throttled(capsys, monkeypatch):
    monkeypatch.setattr(engine, "_CALIBRATION_SKIPS", 0)
    X_tr, y_tr, X_te, y_te = _data_with_calibration_slice(drop_class_in_cal=3)
    for _ in range(3):
        engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "none", "RandomForest", 42,
                              calibration=True, calibration_method="isotonic")
    assert capsys.readouterr().out.count("calibration skipped") == 1
    assert engine._CALIBRATION_SKIPS == 3


def test_matching_classes_still_calibrate(capsys, monkeypatch):
    monkeypatch.setattr(engine, "_CALIBRATION_SKIPS", 0)
    X_tr, y_tr, X_te, y_te = _data(n=900)
    engine._fit_eval_full(X_tr, y_tr, X_te, y_te, "none", "RandomForest", 42,
                          calibration=True, calibration_method="isotonic")
    assert "calibration skipped" not in capsys.readouterr().out


def test_end_of_scan_summary_counts_the_uncalibrated_fits(capsys, monkeypatch):
    monkeypatch.setattr(engine, "_CALIBRATION_SKIPS", 7)
    engine._report_calibration_skips(220)
    out = capsys.readouterr().out
    assert "7 of 220 scan fits ran UNCALIBRATED" in out

    engine._reset_calibration_skips()
    engine._report_calibration_skips(220)
    assert capsys.readouterr().out == ""   # nothing to report: silent
