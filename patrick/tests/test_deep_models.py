"""Réseaux de neurones (`models/deep.py`) : interface scikit-learn, apprentissage réel sur des signaux plantés, fenêtres sans regard
vers l'avenir, sérialisation, intégration au registre. Ignoré si PyTorch n'est pas installé (extra optionnel `deep`)."""
from __future__ import annotations

import io

import joblib
import numpy as np
import pytest

pytest.importorskip("torch")

from patrick.config import defaults as D  # noqa: E402
from patrick.models import registry  # noqa: E402
from patrick.models.deep import (  # noqa: E402
    DL_ALGOS,
    SEQUENCE_ALGOS,
    DeepClassifier,
    build_deep_classifier,
)

FAST = {"epochs": 12, "hidden_size": 16, "n_layers": 1, "batch_size": 64, "patience": 0, "lookback": 6, "n_heads": 2}


def _static_data(n=900, d=6, seed=0):
    """La classe dépend du signe de la ligne courante (x0 + x1) : un MLP suffit."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, d))
    y = np.where(X[:, 0] + X[:, 1] > 0.5, 3, np.where(X[:, 0] + X[:, 1] > 0, 2, np.where(X[:, 0] + X[:, 1] > -0.5, 1, 0)))
    return X, y


def _lagged_data(n=1400, d=4, lag=3, seed=1):
    """La classe dépend de x0 d'il y a `lag` lignes : seule une fenêtre peut la deviner (la ligne courante est du bruit)."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, d))
    y = (np.roll(X[:, 0], lag) > 0).astype(int)
    y[:lag] = 0
    return X, y


@pytest.mark.parametrize("arch", DL_ALGOS)
def test_every_architecture_follows_the_scikit_learn_contract(arch):
    X, y = _static_data(n=300)
    clf = build_deep_classifier(arch, seed=3, **FAST).fit(X[:240], y[:240])
    proba = clf.predict_proba(X[240:])
    assert proba.shape == (60, 4) and np.allclose(proba.sum(axis=1), 1.0, atol=1e-5) and (proba >= 0).all()
    assert list(clf.classes_) == [0, 1, 2, 3]
    pred = clf.predict(X[240:])
    assert set(pred) <= {0, 1, 2, 3} and pred.dtype.kind == "i"
    assert clf.get_params()["arch"] == arch and clf.is_deep is True
    assert clf.needs_history is (arch in SEQUENCE_ALGOS)


def test_an_mlp_learns_a_planted_rule():
    X, y = _static_data()
    clf = build_deep_classifier("MLP", seed=1, **{**FAST, "epochs": 40, "hidden_size": 32, "n_layers": 2}).fit(X[:700], y[:700])
    assert (clf.predict(X[700:]) == y[700:]).mean() > 0.6                       # le hasard donne ~0,25


def test_a_window_model_finds_what_only_the_past_explains_and_an_mlp_cannot():
    X, y = _lagged_data()
    cut = 1100
    seq = build_deep_classifier("GRU", seed=2, **{**FAST, "epochs": 40, "hidden_size": 24, "lookback": 6}).fit(X[:cut], y[:cut])
    mlp = build_deep_classifier("MLP", seed=2, **{**FAST, "epochs": 40, "hidden_size": 24}).fit(X[:cut], y[:cut])
    acc_seq = (seq.predict(X[cut:]) == y[cut:]).mean()
    acc_mlp = (mlp.predict(X[cut:]) == y[cut:]).mean()
    assert acc_seq > 0.8 and acc_mlp < 0.62


@pytest.mark.parametrize("arch", ["CNN1D", "Transformer", "LSTM"])
def test_the_other_window_models_also_use_the_past(arch):
    X, y = _lagged_data(n=1200)
    clf = build_deep_classifier(arch, seed=4, **{**FAST, "epochs": 50, "hidden_size": 24, "n_layers": 2, "lookback": 6}).fit(X[:950], y[:950])
    assert (clf.predict(X[950:]) == y[950:]).mean() > 0.72


def test_windows_never_look_at_the_future():
    """Changer une ligne FUTURE ne change pas la prédiction d'une ligne passée (aucune fuite par la fenêtre)."""
    X, y = _lagged_data(n=500)
    clf = build_deep_classifier("GRU", seed=5, **FAST).fit(X[:400], y[:400])
    base = clf.predict_proba(X[400:440])
    altered = X[400:440].copy()
    altered[30:] += 5.0                                         # on bouleverse les 10 dernières lignes
    after = clf.predict_proba(altered)
    assert np.allclose(base[:30], after[:30], atol=1e-6)
    assert not np.allclose(base[30:], after[30:], atol=1e-3)


def test_context_none_gives_the_same_last_row_as_the_training_context_when_the_window_is_complete():
    X, y = _lagged_data(n=500)
    clf = build_deep_classifier("GRU", seed=6, **FAST).fit(X[:400], y[:400])
    full = clf.predict_proba(X[400:420], context="train")
    own = clf.predict_proba(X[400:420], context="none")
    window = clf.window
    assert np.allclose(full[window - 1:], own[window - 1:], atol=1e-6)   # au-delà de la fenêtre, le contexte n'intervient plus
    last_only = clf.predict_proba(X[420 - window:420], context="none")[-1]
    assert np.allclose(last_only, own[-1], atol=1e-6)                    # la prédiction du jour : `lookback` lignes suffisent


def test_the_same_seed_gives_the_same_network_and_another_seed_a_different_one():
    X, y = _static_data(n=300)
    a = build_deep_classifier("MLP", seed=7, **FAST).fit(X, y).predict_proba(X[:20])
    b = build_deep_classifier("MLP", seed=7, **FAST).fit(X, y).predict_proba(X[:20])
    c = build_deep_classifier("MLP", seed=8, **FAST).fit(X, y).predict_proba(X[:20])
    assert np.allclose(a, b, atol=1e-6) and not np.allclose(a, c, atol=1e-3)


def test_a_model_survives_serialization_without_its_torch_modules():
    X, y = _static_data(n=300)
    clf = build_deep_classifier("GRU", seed=9, **FAST).fit(X[:240], y[:240])
    before = clf.predict_proba(X[240:])
    buffer = io.BytesIO()
    joblib.dump({"model": clf}, buffer)
    assert "_nets" not in clf.__getstate__()
    buffer.seek(0)
    restored = joblib.load(buffer)["model"]
    assert np.allclose(restored.predict_proba(X[240:]), before, atol=1e-6)


def test_a_missing_class_shrinks_the_probability_columns_like_the_other_classifiers():
    X, y = _static_data(n=300)
    y = np.where(y == 3, 2, y)                                  # plus de classe 3
    clf = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y)
    assert list(clf.classes_) == [0, 1, 2] and clf.predict_proba(X[:5]).shape == (5, 3)


def test_a_single_class_train_set_still_predicts():
    X, _ = _static_data(n=200)
    clf = build_deep_classifier("MLP", seed=1, **FAST).fit(X, np.ones(200, dtype=int))
    assert (clf.predict(X[:5]) == 1).all() and np.allclose(clf.predict_proba(X[:5]), 1.0)


def test_sample_weights_and_class_weights_are_accepted_and_change_the_fit():
    X, y = _static_data(n=400)
    w = np.where(y == 3, 10.0, 0.1)
    base = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y)
    weighted = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y, sample_weight=w)
    assert not np.allclose(base.predict_proba(X[:30]), weighted.predict_proba(X[:30]), atol=1e-3)
    flat = build_deep_classifier("MLP", seed=1, **{**FAST, "class_weight": "none"}).fit(X, y)
    assert not np.allclose(base.predict_proba(X[:30]), flat.predict_proba(X[:30]), atol=1e-3)


def test_early_stopping_stops_before_the_epoch_cap_and_keeps_the_best_weights():
    X, y = _static_data(n=600)
    noisy = y.copy()
    rng = np.random.default_rng(0)
    flip = rng.random(600) < 0.5
    noisy[flip] = rng.integers(0, 4, flip.sum())                 # moitié d'étiquettes aléatoires : le réseau surajuste vite
    clf = build_deep_classifier("MLP", seed=1, epochs=200, hidden_size=64, n_layers=2, batch_size=32, patience=3,
                                val_fraction=0.25).fit(X, noisy)
    assert clf.epochs_run_[0] < 200


def test_n_seeds_averages_several_networks():
    X, y = _static_data(n=300)
    one = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y)
    three = build_deep_classifier("MLP", seed=1, **{**FAST, "n_seeds": 3}).fit(X, y)
    assert len(one.state_) == 1 and len(three.state_) == 3
    assert not np.allclose(one.predict_proba(X[:20]), three.predict_proba(X[:20]), atol=1e-3)


def test_non_finite_inputs_never_crash_the_fit_or_the_prediction():
    X, y = _static_data(n=300)
    X = X.copy()
    X[5, 2], X[7, 1] = np.nan, np.inf
    clf = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y)
    out = clf.predict_proba(X)
    assert np.isfinite(out).all()


def test_wrong_column_count_and_unknown_settings_are_refused():
    X, y = _static_data(n=200)
    clf = build_deep_classifier("MLP", seed=1, **FAST).fit(X, y)
    with pytest.raises(ValueError, match="colonnes"):
        clf.predict_proba(X[:, :3])
    with pytest.raises(ValueError, match="inconnu"):
        build_deep_classifier("MLP", seed=1, bogus=1)
    with pytest.raises(ValueError, match="inconnu"):
        build_deep_classifier("ResNet", seed=1)


def test_proba_function_varies_only_the_last_row():
    X, y = _lagged_data(n=400)
    clf = build_deep_classifier("GRU", seed=2, **FAST).fit(X[:300], y[:300])
    history = X[300:306]
    fn = clf.proba_function(history, class_index=1)
    here = fn(history[-1:])
    moved = fn(history[-1:] + 3.0)
    assert here.shape == (1,) and 0 <= float(here[0]) <= 1 and float(here[0]) != float(moved[0])


# --------------------------------------------------------------------------- registre


def test_the_registry_builds_networks_and_still_refuses_unknown_algos():
    clf = registry.get_classifier("GRU", seed=11, hidden_size=12, deep={"epochs": 3})
    assert isinstance(clf, DeepClassifier) and clf.hidden_size == 12 and clf.epochs == 3 and clf.seed == 11
    with pytest.raises(ValueError, match="Unknown ML algo"):
        registry.get_classifier("NotAnAlgo")


def test_run_level_deep_settings_apply_to_every_later_classifier_and_explicit_ones_win():
    try:
        registry.set_deep_defaults({"epochs": 7, "dropout": 0.3})
        assert registry.get_classifier("MLP").epochs == 7
        assert registry.get_classifier("MLP", deep={"epochs": 9}).epochs == 9
        assert registry.get_classifier("MLP", epochs=4).epochs == 4                  # un réglage Optuna passe devant
    finally:
        registry.set_deep_defaults(None)
    assert registry.get_classifier("MLP").epochs == D.DEFAULT_DEEP["epochs"]


def test_tree_algorithms_ignore_the_deep_argument():
    clf = registry.get_classifier("RandomForest", seed=1, deep={"epochs": 3})
    assert type(clf).__name__ == "RandomForestClassifier"
