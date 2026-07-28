import numpy as np

from patrick.validation.metrics import metrics


def test_metrics_1d_arrays():
    y_true = np.array([0, 1, 2, 3, 0, 1, 2, 3, 0, 3, 3, 0])
    y_pred = np.array([0, 1, 2, 3, 1, 1, 2, 2, 0, 3, 0, 0])
    m = metrics(y_true, y_pred)
    assert 0.0 <= m["F1_dir"] <= 1.0
    assert 0.0 <= m["Acc_dir"] <= 1.0


def test_metrics_handles_2d_catboost_style_predict():
    """Régression : CatBoostClassifier.predict() renvoie un tableau (n,1), pas (n,)
    — sans le ravel() dans metrics(), ceci levait 'unhashable type: numpy.ndarray'."""
    y_true = np.array([0, 1, 2, 3, 0, 1, 2, 3])
    y_pred_2d = np.array([[0], [1], [2], [3], [1], [1], [2], [2]])
    m = metrics(y_true, y_pred_2d)
    assert 0.0 <= m["F1_dir"] <= 1.0

    y_pred_1d = y_pred_2d.ravel()
    m2 = metrics(y_true, y_pred_1d)
    assert m == m2


def test_metrics_nan_when_not_enough_up_or_down_samples():
    y_true = np.array([2, 2, 2])  # que des UP, pas de DOWN
    y_pred = np.array([2, 3, 2])
    m = metrics(y_true, y_pred)
    assert np.isnan(m["F1_DOWN_FORT"])
