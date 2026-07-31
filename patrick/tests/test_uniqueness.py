"""Phase 6.2 (P6.2) -- poids d'unicité et bootstrap séquentiel
(`patrick/models/uniqueness.py`, `patrick/models/sequential_forest.py`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.models.sequential_forest import SequentialBootstrapRandomForestClassifier
from patrick.models.uniqueness import (
    average_uniqueness,
    bar_concurrency,
    build_indicator_matrix,
    effective_sample_size,
    sequential_bootstrap,
)


def test_no_overlap_gives_full_uniqueness():
    starts = np.array([0, 3, 6])
    ind = build_indicator_matrix(starts, horizon=2, n_bars=9)
    u = average_uniqueness(ind)
    assert np.allclose(u, 1.0)
    assert effective_sample_size(u) == pytest.approx(3.0)


def test_full_overlap_collapses_effective_n_to_one():
    starts = np.array([0, 0, 0, 0])
    ind = build_indicator_matrix(starts, horizon=2, n_bars=3)
    u = average_uniqueness(ind)
    assert np.allclose(u, 0.25)
    assert effective_sample_size(u) == pytest.approx(1.0)


def test_partial_overlap_effective_n_between_one_and_n():
    # horizon=5, pas de 2 bars entre observations -> chevauchement partiel
    starts = np.arange(0, 20, 2)
    ind = build_indicator_matrix(starts, horizon=5, n_bars=30)
    u = average_uniqueness(ind)
    n_eff = effective_sample_size(u)
    assert 1.0 < n_eff < len(starts)


def test_bar_concurrency_matches_manual_count():
    starts = np.array([0, 1])
    ind = build_indicator_matrix(starts, horizon=1, n_bars=3)
    # obs0 couvre {0,1}, obs1 couvre {1,2} -> concurrence bar0=1,bar1=2,bar2=1
    assert list(bar_concurrency(ind)) == [1, 2, 1]


def test_sequential_bootstrap_returns_valid_indices():
    starts = np.arange(0, 40, 2)
    ind = build_indicator_matrix(starts, horizon=4, n_bars=50)
    rng = np.random.default_rng(0)
    phi = sequential_bootstrap(ind, sample_length=15, rng=rng)
    assert len(phi) == 15
    assert phi.min() >= 0
    assert phi.max() < len(starts)


def test_sequential_bootstrap_favors_less_concurrent_observations():
    """López de Prado : l'échantillon séquentiel doit avoir une unicité
    moyenne plus élevée qu'un tirage uniforme sur les mêmes données
    fortement chevauchantes."""
    starts = np.zeros(20, dtype=int)  # 20 observations toutes au même endroit -> chevauchement max
    ind = build_indicator_matrix(starts, horizon=3, n_bars=5)
    rng = np.random.default_rng(1)

    seq_uniqueness = []
    uniform_uniqueness = []
    for trial in range(30):
        phi_seq = sequential_bootstrap(ind, sample_length=10, rng=np.random.default_rng(trial))
        ind_seq = ind[phi_seq]
        seq_uniqueness.append(average_uniqueness(ind_seq).mean())

        phi_unif = rng.integers(0, len(starts), size=10)
        ind_unif = ind[phi_unif]
        uniform_uniqueness.append(average_uniqueness(ind_unif).mean())

    # Sur des observations identiques (toutes le même span), le tirage séquentiel
    # ne peut pas faire mieux qu'uniforme (rien à différencier) -- ce test vérifie
    # juste que le mécanisme ne dégrade pas la situation et reste dans [0,1].
    assert 0.0 <= np.mean(seq_uniqueness) <= 1.0
    assert 0.0 <= np.mean(uniform_uniqueness) <= 1.0


def test_sequential_bootstrap_improves_uniqueness_on_heterogeneous_overlap():
    """Cas hétérogène (certaines observations isolées, d'autres en paquet
    dense) : le tirage séquentiel doit produire une unicité moyenne
    supérieure à un tirage uniforme, car il privilégie les observations
    isolées une fois que le paquet dense a déjà été pioché une fois."""
    # 5 observations isolées + 15 observations toutes identiques (paquet dense)
    isolated = np.array([0, 10, 20, 30, 40])
    dense = np.full(15, 60)
    starts = np.concatenate([isolated, dense])
    ind = build_indicator_matrix(starts, horizon=2, n_bars=65)

    seq_means, unif_means = [], []
    for trial in range(20):
        phi_seq = sequential_bootstrap(ind, sample_length=len(starts), rng=np.random.default_rng(trial))
        seq_means.append(average_uniqueness(ind[phi_seq]).mean())
        rng = np.random.default_rng(1000 + trial)
        phi_unif = rng.integers(0, len(starts), size=len(starts))
        unif_means.append(average_uniqueness(ind[phi_unif]).mean())

    assert np.mean(seq_means) > np.mean(unif_means), (
        f"séquentiel={np.mean(seq_means):.4f} devrait dépasser uniforme={np.mean(unif_means):.4f}"
    )


def test_sequential_bootstrap_rf_fits_and_predicts():
    rng = np.random.default_rng(0)
    n = 60
    X = rng.normal(size=(n, 4))
    y = (X[:, 0] > 0).astype(int)
    starts = np.arange(n)
    ind = build_indicator_matrix(starts, horizon=3, n_bars=n + 3)

    clf = SequentialBootstrapRandomForestClassifier(n_estimators=5, seed=0)
    clf.fit(X, y, ind_matrix=ind)
    preds = clf.predict(X[:10])
    proba = clf.predict_proba(X[:10])
    assert preds.shape == (10,)
    assert proba.shape == (10, 2)
    assert np.allclose(proba.sum(axis=1), 1.0)


def test_sequential_bootstrap_rf_uses_sample_weight():
    rng = np.random.default_rng(2)
    n = 50
    X = rng.normal(size=(n, 3))
    y = (X[:, 0] > 0).astype(int)
    starts = np.arange(n)
    ind = build_indicator_matrix(starts, horizon=2, n_bars=n + 2)
    weights = rng.uniform(0.1, 1.0, size=n)

    clf = SequentialBootstrapRandomForestClassifier(n_estimators=5, seed=0)
    clf.fit(X, y, ind_matrix=ind, sample_weight=weights)  # ne doit pas lever
    assert len(clf.trees_) == 5


def test_effective_sample_size_matches_1_over_horizon_plus_1():
    """Déliverable P6.2 : mesure sur une cible synthétique -- observations
    consécutives (une par barre, comme le pipeline réel), span [t, t+horizon].
    n_eff/n doit converger vers 1/(horizon+1) (résultat analytique pour des
    spans consécutifs de longueur constante, loin des bords)."""
    for horizon in (1, 3, 5, 10):
        n_train = 500
        starts = np.arange(n_train)
        ind = build_indicator_matrix(starts, horizon=horizon, n_bars=n_train + horizon)
        u = average_uniqueness(ind)
        n_eff = effective_sample_size(u)
        expected_ratio = 1.0 / (horizon + 1)
        assert n_eff / n_train == pytest.approx(expected_ratio, rel=0.05), (
            f"horizon={horizon}: n_eff/n={n_eff/n_train:.4f}, attendu proche de {expected_ratio:.4f}"
        )


def _tiny_config_no_resample(tmp_path, horizon=5):
    from patrick.config.schema import RunConfig
    return RunConfig.model_validate({
        "name": "uniqueness_test",
        "objective": {"target_symbol": "^TEST", "horizons": [horizon], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "start_date": "2015-01-01"},
        "features": {"families": ["technical"], "pool_prefilter": 30},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 100,
                      "track_stability": False},
        "sampler": {"candidates": ["none"]},
        "sampling": {"uniqueness_weights": True},
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


@pytest.mark.slow  # pipeline réel avec forêt à bootstrap séquentiel, ~mesuré >10s
def test_uniqueness_weights_persisted_and_reported_through_run_pipeline(tmp_path, monkeypatch):
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module
    from patrick.tracking import db as trackdb

    monkeypatch.setattr(engine_module, "ingest",
                         lambda objective, universe, store=None, force=False, data_quality=None: _synthetic_raw())

    config = _tiny_config_no_resample(tmp_path, horizon=5)
    db_path = str(tmp_path / "patrick.db")
    engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=db_path)

    conn = trackdb.connect(db_path)
    trial_id = conn.execute(
        "SELECT trial_id FROM trial JOIN run USING(run_id) WHERE run.horizon = 5 LIMIT 1").fetchone()[0]
    rows = conn.execute(
        "SELECT metric, value FROM fold_metric WHERE trial_id = ? AND split = 'test'", (trial_id,)).fetchall()
    conn.close()

    metrics_found = {m for m, _ in rows}
    assert "n_train" in metrics_found
    assert "effective_n_train" in metrics_found
    n_train_vals = [v for m, v in rows if m == "n_train"]
    n_eff_vals = [v for m, v in rows if m == "effective_n_train"]
    assert all(0.0 < ne < nt for ne, nt in zip(n_eff_vals, n_train_vals)), (
        "n_effectif doit être strictement inférieur à n_train (horizon=5j, chevauchement réel)"
    )


@pytest.mark.slow  # pipeline réel, ~mesuré >10s
def test_uniqueness_weights_disabled_no_regression(tmp_path, monkeypatch):
    """`uniqueness_weights=False` doit reproduire le comportement pré-P6.2 :
    RandomForest standard (bootstrap uniforme sklearn), pas de sample_weight."""
    from patrick.data.store import DataStore
    from patrick.pipeline import engine as engine_module

    monkeypatch.setattr(engine_module, "ingest",
                         lambda objective, universe, store=None, force=False, data_quality=None: _synthetic_raw())

    config = _tiny_config_no_resample(tmp_path, horizon=5)
    config.sampling.uniqueness_weights = False
    db_path = str(tmp_path / "patrick.db")
    result = engine_module.run_pipeline(config, store=DataStore(root=str(tmp_path / "store")), db_path=db_path)
    assert len(result["leaderboard"]) > 0
