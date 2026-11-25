"""Reprise d'un run au niveau du scan (A14) : stockage des ajustements, et reprise réelle d'un mini-pipeline interrompu."""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.pipeline import scan_checkpoint as sc


def _result():
    return ({"F1_dir": 0.53, "AUC": float("nan"), "n": np.float64(12.0)}, np.array([0, 1, 1]), np.array([0.4, 0.7, 0.6]), None)


def test_save_then_load_only_when_resuming(tmp_path):
    ident = {"config_hash": "abc", "snapshot_id": "snap"}
    writer = sc.ScanCheckpoint(tmp_path, ident, read=False)
    key = writer.key(fold="d", N=5, algo="RandomForest")
    writer.save(key, _result())
    assert writer.load(key) is None and writer.writes == 1                      # un run neuf ne relit jamais
    reader = sc.ScanCheckpoint(tmp_path, ident, read=True)
    met, y_pred, conf, p_up = reader.load(key)
    assert met["F1_dir"] == 0.53 and np.isnan(met["AUC"]) and met["n"] == 12.0 and p_up is None
    np.testing.assert_array_equal(y_pred, [0, 1, 1]) and np.testing.assert_array_equal(conf, [0.4, 0.7, 0.6])
    assert reader.hits == 1
    other = sc.ScanCheckpoint(tmp_path, {**ident, "config_hash": "zzz"}, read=True)
    assert other.load(key) is None                                              # autre lancement : autre dossier


def test_corrupt_file_is_recomputed_and_clear_and_purge(tmp_path):
    ck = sc.ScanCheckpoint(tmp_path, {"a": 1}, read=True)
    key = ck.key(x=1)
    ck.save(key, _result())
    ck._path(key).write_bytes(b"pas un npz")
    assert ck.load(key) is None
    old = sc.ScanCheckpoint(tmp_path, {"a": 2}, read=False)
    old.save(old.key(x=1), _result())
    past = time.time() - 30 * 86400
    os.utime(old.dir, (past, past))
    assert ck.purge_old() == 1 and not old.dir.exists() and ck.dir.exists()
    ck.clear()
    assert not ck.dir.exists()


def test_digest_sees_every_bit():
    x = np.arange(12, dtype=float).reshape(3, 4)
    y = x.copy()
    y[2, 3] = np.nextafter(y[2, 3], 99)
    assert sc.digest(x, None) == sc.digest(x.copy(), None) != sc.digest(y, None)
    assert sc.digest(x.astype(np.float32)) != sc.digest(x)


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    df = pd.DataFrame({"IDX_TEST": 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    return df


def _config(out) -> RunConfig:
    return RunConfig.model_validate({
        "name": "ckpt_test", "objective": {"target_symbol": "^TEST", "horizons": [3], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}, "start_date": "2015-01-01"},
        "features": {"families": ["spike", "macro"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "lasso", "n_features_grid": [4, 8]},
        "sampler": {"candidates": ["none"]}, "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False}, "output": {"dir": str(out), "seed": 7},
    })


class _Stop(Exception):
    pass


@pytest.mark.slow
def test_an_interrupted_run_resumes_without_refitting_the_scan(tmp_path, monkeypatch):
    """Un lancement coupé juste après son scan, puis repris comme le font le worker et `patrick resume` (configuration ENREGISTRÉE du
    run, même instantané) : aucun ajustement du scan n'est refait et le classement est identique au bit près."""
    import json as _json
    import sqlite3

    monkeypatch.setenv("PATRICK_SCAN_JOBS", "1")
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _synthetic_raw(700))
    monkeypatch.setattr(engine_module, "load_snapshot", lambda *a, **k: _synthetic_raw(700))
    fits, boards = {"scan": 0}, []
    real_fit, real_scan = engine_module._fit_eval_full, engine_module._scan_walkforward
    in_scan = {"on": False}

    def counting_fit(*a, **k):
        if in_scan["on"]:
            fits["scan"] += 1
        return real_fit(*a, **k)

    def flagged_scan(st):
        in_scan["on"] = True
        try:
            real_scan(st)
        finally:
            in_scan["on"] = False
        boards.append(st.board.as_df())

    def stop_after_scan(st):
        raise _Stop
    monkeypatch.setattr(engine_module, "_fit_eval_full", counting_fit)
    monkeypatch.setattr(engine_module, "_scan_walkforward", flagged_scan)
    monkeypatch.setattr(engine_module, "_track_stability", stop_after_scan)
    store, out, db_path = DataStore(root=str(tmp_path / "store")), tmp_path / "runs", str(tmp_path / "t.db")

    with pytest.raises(_Stop):                                  # lancement interrompu : ses points de reprise restent sur disque
        engine_module.run_pipeline(_config(out), store=store, db_path=db_path)
    n_grid = fits["scan"]
    assert n_grid >= 4 and len(list((out / sc.DIRNAME).rglob("*.npz"))) == n_grid

    conn = sqlite3.connect(db_path)
    stored, snapshot_id = conn.execute("SELECT config_json, snapshot_id FROM run ORDER BY rowid DESC LIMIT 1").fetchone()
    conn.close()
    with pytest.raises(_Stop):
        engine_module.run_pipeline(RunConfig.from_stored_json(stored), store=store, db_path=db_path, snapshot_id=snapshot_id)
    assert fits["scan"] == n_grid                               # aucun ajustement refait
    cols = ["horizon", "fold", "regime", "N", "sampler", "algo", "F1_dir", "AUC"]
    cols = [c for c in cols if c in boards[0].columns]
    pd.testing.assert_frame_equal(boards[1][cols].reset_index(drop=True), boards[0][cols].reset_index(drop=True))
    assert _json.loads(stored)["objective"]["target_symbol"] == "^TEST"


def test_a_finished_run_clears_its_checkpoint(tmp_path):
    ck = sc.ScanCheckpoint(tmp_path, {"run": 1}, read=False)
    ck.save(ck.key(x=1), _result())
    assert any(ck.dir.rglob("*.npz"))
    ck.clear()
    assert not ck.dir.exists()
