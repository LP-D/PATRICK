"""F03 -- the Deflated Sharpe Ratio's `n_trials` must count every
configuration ever evaluated for a target, across runs, and that count must
not be erasable.

Three measured under-counts before the fix:
1. An Optuna tuning of `n_trials=100` was recorded as ONE `trial` row --
   99 evaluated configurations vanished from the count.
2. `/simulate` deflated the strategy's Sharpe by the number of PAST
   SIMULATIONS on the target only (usually 0 -> n_trials=1: no deflation at
   all), ignoring every model configuration tried to produce the signal.
3. `count_cumulative_trials` joined `trial` to `run`; `trial.run_id` is
   `ON DELETE CASCADE`, so deleting a run (manual cleanup, e.g. the ad hoc
   `GSPC_1_detail_h*` one) silently erased its trials from the history.

Fix: `trial_registry` (migration 0021), append-only, no foreign key, one
event per evaluated configuration (scan trial, Optuna trial, simulation,
category comparison), backfilled from the existing history.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

from patrick.data.store import DataStore
from patrick.simulate import engine as sim
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats
from patrick.tuning.optuna_runner import tune_config


def _run(conn, run_id, target="^T", horizon=5, config_json="{}"):
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, None)
    trackdb.create_run(conn, run_id, target=target, horizon=horizon, snapshot_id="snap",
                        config_json=config_json, config_hash="c", git_sha="g", seed=42)


def test_deleting_a_run_does_not_erase_its_trials_from_the_count(conn):
    _run(conn, "r1")
    for n in (5, 8, 10):
        trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", n, "shap")
    assert trackstats.count_cumulative_trials(conn, "^T", 5) == 3
    with conn:
        conn.execute("DELETE FROM run WHERE run_id = 'r1'")
    assert trackstats.count_cumulative_trials(conn, "^T", 5) == 3


def test_every_optuna_trial_is_registered(conn):
    _run(conn, "r1")
    X, y = make_classification(n_samples=160, n_features=6, n_informative=4, n_classes=4,
                               n_clusters_per_class=1, random_state=0)
    tune_config(X, y, "RandomForest", "none", n_trials=4, cv_splits=2, seed=42,
                registry=trackdb.TrialRecorder(conn, "^T", 5, "r1"))
    assert trackstats.count_cumulative_trials(conn, "^T", 5) == 4
    sources = dict(conn.execute("SELECT source, SUM(n_trials) FROM trial_registry GROUP BY source"))
    assert sources == {"optuna": 4}


def test_registry_backfills_existing_history_on_migration(tmp_path):
    """A database created before migration 0021: its scan trials count 1
    each, its tuned trials (params_json != '{}') count the run's configured
    `tuning.n_trials`, its simulations count 1 each."""
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    conn = trackdb.connect(db_path)
    _run(conn, "r1", config_json='{"tuning": {"n_trials": 50}}')
    trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 5, "shap")
    trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 5, "shap", params_json='{"max_depth": 3}')
    with conn:
        conn.execute("DELETE FROM trial_registry")
        conn.execute("DELETE FROM schema_version WHERE version >= 21")
    conn.close()

    raw = sqlite3.connect(db_path)
    raw.execute("DROP TABLE trial_registry")
    raw.commit()
    raw.close()

    conn = trackdb.connect(db_path)
    assert trackstats.count_cumulative_trials(conn, "^T", 5) == 1 + 50


def _sim_fixture(tmp_path, n_model_trials: int):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    idx = pd.bdate_range("2020-01-01", periods=300)
    price = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 300))
    store = DataStore(root=str(tmp_path / "store"))
    snap = store.save("raw_^T", pd.DataFrame({"IDX_T": price}, index=idx))
    trackdb.upsert_snapshot(conn, snap, "x", 0, 0, "api")
    trackdb.create_run(conn, "r1", target="^T", horizon=5, snapshot_id=snap, config_json="{}",
                        config_hash="h", git_sha="s", seed=0)
    tids = [trackdb.create_trial(conn, "r1", "GLOBAL", "X", "none", k + 1, "shap")
            for k in range(n_model_trials)]
    ts = [str(d) for d in idx[20:290:5]]
    trackdb.add_predictions(conn, tids[0], fold_index=1, split="test", ts=ts,
                             y_true=[3] * len(ts), y_pred=[3, 0] * (len(ts) // 2) + [3] * (len(ts) % 2),
                             y_proba=[0.8] * len(ts))
    conn.close()
    return db_path, str(tmp_path / "store"), tids[0]


def test_simulate_deflates_by_every_model_trial_not_only_past_simulations(tmp_path, monkeypatch):
    db_path, store_root, trial_id = _sim_fixture(tmp_path, n_model_trials=40)
    seen = {}
    real = sim.deflated_sharpe_ratio

    def _spy(returns, n_trials, *a, **k):
        seen["n_trials"] = n_trials
        return real(returns, n_trials, *a, **k)

    monkeypatch.setattr(sim, "deflated_sharpe_ratio", _spy)
    result = sim.simulate(trial_id, sim.SimParams(), db_path=db_path, store_root=store_root)
    assert result["ok"]
    assert seen["n_trials"] == 40 + 1
    assert result["strategy"]["dsr_n_trials"] == 41


def test_saved_simulations_are_registered(tmp_path):
    db_path, store_root, trial_id = _sim_fixture(tmp_path, n_model_trials=2)
    result = sim.simulate(trial_id, sim.SimParams(), db_path=db_path, store_root=store_root)
    conn = trackdb.connect(db_path)
    sim.save_simulation(conn, trial_id, sim.SimParams(), result)
    assert trackstats.count_registered_trials(conn, "^T") == 2 + 1
    conn.close()


@pytest.mark.parametrize("bad", [-1])
def test_registry_rejects_negative_counts(conn, bad):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        trackdb.register_trials(conn, "^T", 5, "scan", bad)
