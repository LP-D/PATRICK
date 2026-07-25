import numpy as np
import pytest

from marketml.models.registry import ML_ALGOS, get_classifier
from marketml.models.samplers import ALL_SAMPLERS, get_sampler
from marketml.selection.registry import SELECTION_METHODS, select_features


def test_get_classifier_known_algos():
    for algo in ML_ALGOS:
        clf = get_classifier(algo, seed=42)
        assert hasattr(clf, "fit") and hasattr(clf, "predict")


def test_get_classifier_unknown_raises():
    with pytest.raises(ValueError):
        get_classifier("NotAnAlgo")


def test_get_sampler_known_names():
    for name in ALL_SAMPLERS:
        s = get_sampler(name, seed=42)
        assert hasattr(s, "fit_resample")


def test_get_sampler_unknown_raises():
    with pytest.raises(ValueError):
        get_sampler("NotASampler")


def test_select_features_shap_default():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 20))
    y = rng.integers(0, 4, size=300)
    cols = select_features("shap", X, y, top_n=5, prefilter=20, seed=42)
    assert len(cols) == 5
    assert len(set(cols)) == 5


def test_select_features_unknown_method_raises():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 5))
    y = rng.integers(0, 4, size=50)
    with pytest.raises(ValueError):
        select_features("not_a_method", X, y, top_n=3, prefilter=5)


def test_selection_methods_constant_matches_config_literal():
    assert set(SELECTION_METHODS) == {"shap", "rfe", "lasso"}
