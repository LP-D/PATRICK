"""F06 -- `/simulate` must never pool predictions of different statistical
status into one equity curve / one Sharpe:

- `test`: walk-forward test folds -- the scores the configuration was
  SELECTED on (in-sample with respect to model selection);
- `holdout`: terminal holdout -- evaluated once, after selection: the only
  honest out-of-sample segment;
- `live`: paper trading after the run.

Before the fix, `_load_predictions` read `split IN ('test','holdout','live')`
and simulated them as one continuous track record: the selection-biased test
segment inflated the "out-of-sample" performance and the DSR.

Second defect in the same window logic: the simulated calendar ran until the
end of the data snapshot, far past the last signal -- buy-and-hold was
measured over a longer period than the strategy was ever exposed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.data.store import DataStore
from patrick.simulate import engine as sim
from patrick.tracking import db as trackdb

TARGET = "^SEG"
H = 5


def _fixture(tmp_path, with_live=True):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    idx = pd.bdate_range("2020-01-01", periods=600)
    price = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 600))
    store = DataStore(root=str(tmp_path / "store"))
    snap = store.save(f"raw_{TARGET}", pd.DataFrame({"IDX_SEG": price}, index=idx))
    trackdb.upsert_snapshot(conn, snap, "x", 0, 0, "api")
    trackdb.create_run(conn, "r", target=TARGET, horizon=H, snapshot_id=snap, config_json="{}",
                        config_hash="h", git_sha="s", seed=0)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "X", "none", 1, "shap")

    def add(split, positions, fold):
        ts = [str(idx[i]) for i in positions]
        trackdb.add_predictions(conn, tid, fold_index=fold, split=split, ts=ts,
                                 y_true=[3] * len(ts), y_pred=[3, 0] * (len(ts) // 2) + [3] * (len(ts) % 2),
                                 y_proba=[0.8] * len(ts))

    add("test", range(20, 300, H), 1)
    add("holdout", range(320, 450, H), 0)
    if with_live:
        add("live", range(460, 520, H), 0)
    conn.close()
    return db_path, str(tmp_path / "store"), tid, idx


@pytest.mark.parametrize("segment, first, last", [("test", 20, 295), ("holdout", 320, 445), ("live", 460, 515)])
def test_each_segment_is_simulated_alone(tmp_path, segment, first, last):
    db_path, store_root, tid, idx = _fixture(tmp_path)
    result = sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root, segment=segment)
    assert result["ok"]
    assert result["segment"] == segment
    assert result["n_signals"] == len(range(first, last + 1, H))
    curve_dates = [p["t"] for p in result["equity_curve"]]
    assert curve_dates[0] == str(idx[first].date())


def test_default_segment_is_the_holdout_never_a_pool(tmp_path):
    db_path, store_root, tid, _ = _fixture(tmp_path)
    result = sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root)
    assert result["n_signals"] == 26, "test + holdout + live pooled into one track record"
    assert result["segment"] == "holdout"
    assert result["available_segments"] == {"test": 56, "holdout": 26, "live": 12}


def test_default_falls_back_to_test_with_an_explicit_selection_bias_warning(tmp_path):
    db_path, store_root, tid, _ = _fixture(tmp_path)
    conn = trackdb.connect(db_path)
    with conn:
        conn.execute("DELETE FROM prediction WHERE split IN ('holdout', 'live')")
    conn.close()
    result = sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root)
    assert result["segment"] == "test"
    assert result["segment_warning"]


def test_simulated_window_stops_once_the_last_signal_has_expired(tmp_path):
    db_path, store_root, tid, idx = _fixture(tmp_path)
    result = sim.simulate(tid, sim.SimParams(execution_lag_bars=1), db_path=db_path,
                          store_root=store_root, segment="test")
    last_date = result["equity_curve"][-1]["t"]
    assert last_date == str(idx[295 + 1 + H - 1].date())
    assert len(result["buy_and_hold_curve"]) == len(result["equity_curve"])


def test_unknown_segment_is_rejected(tmp_path):
    db_path, store_root, tid, _ = _fixture(tmp_path)
    with pytest.raises(ValueError):
        sim.simulate(tid, sim.SimParams(), db_path=db_path, store_root=store_root, segment="all")
