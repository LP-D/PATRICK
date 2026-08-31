import numpy as np
import pytest

from patrick.config.defaults import ALL_ML_ALGOS, DEFAULT_ML_ALGOS
from patrick.models.registry import MODEL_N_JOBS, ML_ALGOS, get_classifier
from patrick.models.samplers import ALL_SAMPLERS, get_sampler
from patrick.selection.registry import SELECTION_METHODS, select_features


def test_get_classifier_known_algos():
    for algo in ML_ALGOS:
        clf = get_classifier(algo, seed=42)
        assert hasattr(clf, "fit") and hasattr(clf, "predict")


def test_classifiers_do_not_oversubscribe_cpu_threads():
    """Scan and Optuna tuning are strictly sequential (one config, one
    walk-forward fold, one Optuna trial at a time -- see
    tuning/optuna_runner.py::tune_config, no joblib.Parallel/n_jobs>1
    anywhere in pipeline/engine.py). `n_jobs=-1` on the single model being
    fit at any given instant does not queue up alongside other concurrent
    fits from this codebase, but it still races the OS scheduler against
    whatever else is running, and for RandomForest specifically each `-1`
    fit forks a fresh joblib/loky worker process per core -- expensive and
    highly variable process-spawn overhead on Windows, not just thread
    contention. Root-caused via 4 controlled measurements (73s / 1648s /
    722s / 2292s for the identical GSPC h1 tuning phase, same code, same
    config, same 6-core/no-hyperthreading hardware) that ruled out config
    drift, code drift, and external contention in turn -- see
    fix/tuning-n-jobs-oversubscription. `MODEL_N_JOBS` is the single
    coordination point: every classifier must honor it instead of hardcoding
    its own `-1`."""
    assert MODEL_N_JOBS == 1
    for algo in ML_ALGOS:
        clf = get_classifier(algo, seed=42)
        params = clf.get_params()
        if algo == "CatBoost":
            assert params.get("thread_count") == MODEL_N_JOBS, (
                f"{algo}: thread_count={params.get('thread_count')!r}, expected {MODEL_N_JOBS}"
            )
        elif algo == "GradientBoosting":
            assert "n_jobs" not in params, "sklearn's GradientBoostingClassifier has no n_jobs param"
        else:
            assert params.get("n_jobs") == MODEL_N_JOBS, (
                f"{algo}: n_jobs={params.get('n_jobs')!r}, expected {MODEL_N_JOBS}"
            )


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


def test_default_algos_exclude_gradient_boosting():
    assert "GradientBoosting" not in DEFAULT_ML_ALGOS
    assert "GradientBoosting" in ALL_ML_ALGOS


def test_gradient_boosting_still_usable():
    clf = get_classifier("GradientBoosting", seed=42)
    assert hasattr(clf, "fit") and hasattr(clf, "predict")
    rng = np.random.default_rng(0)
    X = rng.normal(size=(100, 5))
    y = rng.integers(0, 4, size=100)
    clf.fit(X, y)
    preds = clf.predict(X)
    assert len(preds) == 100


def test_all_ml_algos_superset_of_default():
    assert set(DEFAULT_ML_ALGOS).issubset(set(ALL_ML_ALGOS))


def test_selection_methods_constant_matches_config_literal():
    assert set(SELECTION_METHODS) == {"shap", "rfe", "lasso"}
