"""Critère de sortie Phase 4 (module simulation) : une simulation sur un run
existant produit une courbe, une comparaison vs buy-and-hold, un coût de
rentabilité, et un compteur de configs testées -- sans jamais ré-exécuter de
modèle (lecture seule de `prediction` + snapshot immuable).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore
from patrick.simulate import engine as sim
from patrick.tracking import db as trackdb

TARGET = "^TEST"


def _setup_run_with_predictions(tmp_path, seed=0, n=300, horizon=5, good_signal=True):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)

    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(seed)
    price = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({"IDX_TEST": price}, index=idx)

    store = DataStore(root=str(tmp_path / "store"))
    snapshot_id = store.save(f"raw_{TARGET}", df)

    trackdb.upsert_snapshot(conn, snapshot_id, data_hash="x", n_tickers=0, n_fred_series=0, fred_source="api")
    run_id = "run1"
    trackdb.create_run(conn, run_id, target=TARGET, horizon=horizon, snapshot_id=snapshot_id,
                        config_json="{}", config_hash="h", git_sha="s", seed=seed)
    trial_id = trackdb.create_trial(conn, run_id, regime="GLOBAL", algo="X", sampler="none",
                                     n_features=1, selector="shap")

    ts_list, y_pred_list, y_proba_list, y_true_list = [], [], [], []
    for i in range(20, n - horizon, horizon):
        d = idx[i]
        fut_ret = price[i + horizon] / price[i] - 1
        true_up = fut_ret > 0
        if good_signal:
            y_pred = 3 if true_up else 0
            y_proba = 0.85
        else:
            y_pred = int(rng.choice([0, 3]))
            y_proba = 0.55
        ts_list.append(str(d))
        y_pred_list.append(y_pred)
        y_proba_list.append(y_proba)
        y_true_list.append(3 if true_up else 0)

    trackdb.add_predictions(conn, trial_id, fold_index=1, split="test", ts=ts_list,
                             y_true=y_true_list, y_pred=y_pred_list, y_proba=y_proba_list)
    conn.close()
    return db_path, str(tmp_path / "store"), trial_id, run_id


def test_simulate_produces_curves_and_metrics(tmp_path):
    db_path, store_root, trial_id, _ = _setup_run_with_predictions(tmp_path, good_signal=True)
    params = sim.SimParams(position_mode="threshold", threshold=0.55)
    result = sim.simulate(trial_id, params, db_path=db_path, store_root=store_root)

    assert result["ok"] is True
    assert len(result["equity_curve"]) > 10
    assert len(result["drawdown_curve"]) == len(result["equity_curve"])
    assert len(result["buy_and_hold_curve"]) == len(result["equity_curve"])
    assert "break_even_cost_bps" in result["strategy"]
    assert "cagr" in result["buy_and_hold"]
    assert result["n_simulation_configs_on_target"] >= 1


def test_good_signal_outperforms_random_signal(tmp_path):
    """Critère indirect de correction : un signal parfaitement corrélé au
    rendement futur doit produire un CAGR net supérieur à un signal proche du
    hasard, sur les mêmes données de prix."""
    db_good, store_good, trial_good, _ = _setup_run_with_predictions(tmp_path / "good", good_signal=True)
    db_bad, store_bad, trial_bad, _ = _setup_run_with_predictions(tmp_path / "bad", good_signal=False, seed=0)

    params = sim.SimParams(position_mode="threshold", threshold=0.55)
    r_good = sim.simulate(trial_good, params, db_path=db_good, store_root=store_good)
    r_bad = sim.simulate(trial_bad, params, db_path=db_bad, store_root=store_bad)

    assert r_good["ok"] and r_bad["ok"]
    assert r_good["strategy"]["cagr"] > r_bad["strategy"]["cagr"]


def test_execution_lag_cannot_be_zero():
    """Anti-pattern #5 du plan (exécuter un signal sur la bougie qui l'a
    produit) doit être structurellement impossible, pas juste déconseillé."""
    with pytest.raises(ValueError):
        sim.SimParams(execution_lag_bars=0)


def test_kelly_disabled_without_good_calibration(tmp_path):
    db_path, store_root, trial_id, _ = _setup_run_with_predictions(tmp_path, good_signal=False, n=150)
    params = sim.SimParams(position_mode="kelly")
    result = sim.simulate(trial_id, params, db_path=db_path, store_root=store_root)
    assert result["ok"] is False
    assert "Kelly" in result["message"]


def test_kelly_enabled_with_strong_signal(tmp_path):
    db_path, store_root, trial_id, _ = _setup_run_with_predictions(tmp_path, good_signal=True)
    params = sim.SimParams(position_mode="kelly", kelly_fraction=0.5)
    result = sim.simulate(trial_id, params, db_path=db_path, store_root=store_root)
    assert result["ok"] is True


def test_asset_class_prefills_frictions():
    params = sim.SimParams(asset_class="us_large_cap")
    assert params.spread_bps == pytest.approx(1.5)
    assert params.commission_bps == pytest.approx(1.5)


def test_overlap_modes_produce_different_exposure(tmp_path):
    db_path, store_root, trial_id, _ = _setup_run_with_predictions(tmp_path, good_signal=True)
    tranches = sim.simulate(trial_id, sim.SimParams(overlap_mode="tranches"), db_path=db_path, store_root=store_root)
    renewed = sim.simulate(trial_id, sim.SimParams(overlap_mode="renewed"), db_path=db_path, store_root=store_root)
    assert tranches["ok"] and renewed["ok"]
    assert tranches["strategy"]["avg_exposure"] != renewed["strategy"]["avg_exposure"]


def test_save_simulation_increments_target_counter(tmp_path):
    db_path, store_root, trial_id, _ = _setup_run_with_predictions(tmp_path, good_signal=True)
    conn = trackdb.connect(db_path)
    assert sim.count_simulations_for_target(conn, TARGET) == 0

    params = sim.SimParams()
    result = sim.simulate(trial_id, params, db_path=db_path, store_root=store_root)
    sim.save_simulation(conn, trial_id, params, result)
    assert sim.count_simulations_for_target(conn, TARGET) == 1

    result2 = sim.simulate(trial_id, params, db_path=db_path, store_root=store_root)
    sim.save_simulation(conn, trial_id, params, result2)
    assert sim.count_simulations_for_target(conn, TARGET) == 2
    conn.close()


def test_simulate_never_touches_model_or_trains_anything(tmp_path):
    """Contrainte non négociable du plan : le simulateur ne doit lire QUE
    `prediction` + le snapshot immuable -- pas de modèle chargé/entraîné.
    Vérifié indirectement : `simulate()` fonctionne sans qu'aucun artefact
    modèle (joblib) n'existe nulle part sur le run de test."""
    db_path, store_root, trial_id, run_id = _setup_run_with_predictions(tmp_path)
    conn = trackdb.connect(db_path)
    artifact_path = conn.execute(
        "SELECT artifact_path FROM trial WHERE trial_id = ?", (trial_id,)).fetchone()[0]
    conn.close()
    assert artifact_path is None  # jamais renseigné dans ce test -> aucun modèle exporté

    result = sim.simulate(trial_id, sim.SimParams(), db_path=db_path, store_root=store_root)
    assert result["ok"] is True
