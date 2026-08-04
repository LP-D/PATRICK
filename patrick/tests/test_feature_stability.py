"""Phase 6.3 (P6.3) -- stabilité de la sélection de features entre folds
(`patrick/selection/stability.py`), câblée dans `pipeline/engine.py` (table
`feature_stability` + `run_feature_stability`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.selection.registry import select_features
from patrick.selection.stability import MIN_MEAN_JACCARD_WARNING, feature_selection_stability, jaccard


def test_jaccard_identical_sets_is_one():
    assert jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial_overlap():
    assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(2 / 4)


def test_feature_selection_stability_perfectly_stable():
    folds = {1: ["a", "b", "c"], 2: ["a", "b", "c"], 3: ["a", "b", "c"]}
    result = feature_selection_stability(folds)
    assert result["mean_jaccard"] == 1.0
    assert result["warning"] is None
    assert result["selection_freq"] == {"a": 1.0, "b": 1.0, "c": 1.0}


def test_feature_selection_stability_fully_unstable_triggers_warning():
    folds = {1: ["a", "b"], 2: ["c", "d"], 3: ["e", "f"]}
    result = feature_selection_stability(folds)
    assert result["mean_jaccard"] == 0.0
    assert result["warning"] is not None
    assert "0.000" in result["warning"]


def test_feature_selection_stability_single_fold_not_computable():
    result = feature_selection_stability({1: ["a", "b"]})
    assert result["mean_jaccard"] != result["mean_jaccard"]  # NaN
    assert result["warning"] is None
    assert result["n_folds"] == 1


def test_feature_selection_stability_selection_freq_partial():
    folds = {1: ["a", "b"], 2: ["a", "c"], 3: ["a", "d"]}
    result = feature_selection_stability(folds)
    assert result["selection_freq"]["a"] == 1.0
    assert result["selection_freq"]["b"] == pytest.approx(1 / 3)


@pytest.mark.slow  # simulation SHAP réelle x plusieurs essais, ~mesuré >10s
def test_warning_threshold_is_measured_not_arbitrary():
    """Reproduit (à plus petite échelle) la mesure qui a fixé
    MIN_MEAN_JACCARD_WARNING=0.40 (cf. docstring `selection/stability.py`) :
    sur des données SANS lien réel entre X et y (cible pur bruit, features
    corrélées entre elles), la sélection SHAP RÉELLE produit déjà un Jaccard
    moyen substantiel par la seule structure de corrélation -- confirme que
    le seuil n'est pas juste au-dessus de 0."""
    rng = np.random.default_rng(7)
    n_samples, n_features, top_n = 300, 40, 6
    null_means = []
    for trial in range(6):
        base = rng.normal(size=(n_samples, 8))
        X = np.hstack([base + rng.normal(0, 0.3, size=(n_samples, 8)) for _ in range(n_features // 8)])
        y = rng.integers(0, 4, size=n_samples)
        fold_sets = {}
        for fold in range(3):
            idx = rng.choice(n_samples, size=int(n_samples * 0.8), replace=False)
            cols = select_features("shap", X[idx], y[idx], top_n, n_features,
                                    seed=trial * 10 + fold, shap_sample=150)
            fold_sets[fold] = [str(c) for c in cols]
        null_means.append(feature_selection_stability(fold_sets)["mean_jaccard"])
    null_means = np.array(null_means)
    assert null_means.mean() > 0.05, (
        "la sélection SHAP réelle sur du pur bruit corrélé devrait montrer une stabilité "
        "spurieuse non négligeable -- si ce n'est pas le cas, revoir la justification du seuil."
    )


def _tiny_config(tmp_path):
    from patrick.config.schema import RunConfig
    return RunConfig.model_validate({
        "name": "stability_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"},
        "features": {"families": ["technical"], "pool_prefilter": 30},
        "validation": {"n_wf_folds": 3, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 100,
                      "track_stability": True},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest"]},
        "tuning": {"enabled": False},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    })


def _synthetic_raw(n=1200, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    return df


@pytest.mark.slow  # pipeline réel (scan complet), ~mesuré >10s
def test_feature_stability_persisted_through_run_pipeline(tmp_path, monkeypatch):
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module
    from patrick.tracking import db as trackdb

    monkeypatch.setattr(engine_module, "ingest",
                         lambda objective, universe, store=None, force=False, data_quality=None: _synthetic_raw())

    config = _tiny_config(tmp_path)
    db_path = str(tmp_path / "patrick.db")
    engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=db_path)

    conn = trackdb.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = 5").fetchone()[0]
    stability = trackdb.get_feature_stability(conn, run_id)
    conn.close()

    assert stability is not None
    assert stability["n_folds"] >= 2
    assert 0.0 <= stability["mean_jaccard"] <= 1.0
    assert len(stability["selection_freq"]) > 0
    assert all(0.0 <= r["selection_freq"] <= 1.0 for r in stability["selection_freq"])


@pytest.mark.slow  # pipeline réel, ~mesuré >10s
def test_track_stability_disabled_skips_persistence(tmp_path, monkeypatch):
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module
    from patrick.tracking import db as trackdb

    monkeypatch.setattr(engine_module, "ingest",
                         lambda objective, universe, store=None, force=False, data_quality=None: _synthetic_raw())

    config = _tiny_config(tmp_path)
    config.selection.track_stability = False
    db_path = str(tmp_path / "patrick.db")
    engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=db_path)

    conn = trackdb.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = 5").fetchone()[0]
    stability = trackdb.get_feature_stability(conn, run_id)
    conn.close()
    assert stability is None
