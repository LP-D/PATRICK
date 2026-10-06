"""Prédiction live d'un modèle d'alpha : seuils et classes réalisées sur le rendement excédentaire, jamais sur le prix."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest
from test_predict_live import HORIZON, TARGET_SYMBOL, _extend_raw, _synthetic_raw

from patrick import predict as predict_module
from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.features import alpha_target as at
from patrick.features.target import build_target, classify_return, live_class_thresholds
from patrick.pipeline import engine as engine_module
from patrick.tracking import db

N = 900


def _frames(drift_asset=0.003, drift_bench=0.002, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=N)
    rb = rng.normal(drift_bench, 0.01, N)
    ra = 1.5 * rb + rng.normal(drift_asset - 1.5 * drift_bench, 0.005, N)
    return (pd.Series(100 * np.cumprod(1 + ra), index=idx), pd.Series(100 * np.cumprod(1 + rb), index=idx))


def _config() -> RunConfig:
    return RunConfig.model_validate({
        "objective": {"target_symbol": "AAA", "horizons": [HORIZON], "target_kind": "alpha", "benchmark": "BBB"},
        "universe": {"yf_tickers": ["CCC"], "start_date": "2018-01-01"}})


def test_alpha_thresholds_straddle_zero_while_raw_thresholds_follow_the_market():
    # Mesuré sur 6 graines : le seuil haut brut vaut 3 à 6 fois celui de l'alpha (la dérive du marché le tire vers le haut).
    for seed in range(4):
        asset, bench = _frames(seed=seed)
        _, raw_hi = live_class_thresholds(asset, 10, 0.003)
        ret = at.alpha_labels(asset, bench, 10)
        a_lo, a_hi = live_class_thresholds(asset, 10, 0.003, ret=ret)

        assert a_lo < 0 < a_hi              # l'alpha a des deux signes
        assert raw_hi > 2 * a_hi            # le rendement brut, lui, suit le marché


def test_the_default_live_thresholds_are_unchanged():
    asset, _ = _frames()
    _, _, thr = build_target(asset, 10, len(asset), 0.003)
    lo, hi = live_class_thresholds(asset, 10, 0.003)
    assert (lo, hi) in [tuple(v) for v in thr.values()]


def test_alpha_live_thresholds_ignore_the_future():
    asset, bench = _frames()
    raw = pd.DataFrame({"AAA": asset, "BBB": bench})
    t = raw.index[600]
    before = predict_module._alpha_live_thresholds(raw, _config(), "AAA", t, HORIZON)
    corrupted = raw.copy()
    corrupted.iloc[601:] *= np.random.default_rng(1).uniform(0.3, 3.0, (N - 601, 2))

    assert predict_module._alpha_live_thresholds(corrupted, _config(), "AAA", t, HORIZON) == before


def test_alpha_forward_returns_are_none_for_a_raw_run_and_the_labels_for_alpha():
    asset, bench = _frames()
    raw = pd.DataFrame({"AAA": asset, "BBB": bench})
    raw_cfg = RunConfig.model_validate({"objective": {"target_symbol": "AAA", "horizons": [HORIZON]},
                                        "universe": {"yf_tickers": ["CCC"], "start_date": "2018-01-01"}})

    assert predict_module._alpha_forward_returns(raw, raw_cfg, "AAA", HORIZON) is None
    got = predict_module._alpha_forward_returns(raw, _config(), "AAA", HORIZON)
    pd.testing.assert_series_equal(got, at.alpha_labels(asset, bench, HORIZON), check_names=False)


def _trial(conn):
    db.upsert_snapshot(conn, "snap", "h", 0, 0, "api")
    db.create_run(conn, "r", target="AAA__alpha_BBB", horizon=HORIZON, snapshot_id="snap", config_json="{}",
                  config_hash="h", git_sha="s", seed=0)
    return db.create_trial(conn, "r", "GLOBAL", "X", "none", 1, "shap")


def test_live_outcome_is_judged_on_the_excess_return_not_on_the_price(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _trial(conn)
    asset, _ = _frames()
    pos = 300
    ts = str(asset.index[pos])
    db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])
    db.set_live_signal_context(conn, tid, ts, -0.02, 0.02, False)
    alpha = pd.Series(np.nan, index=asset.index)
    alpha.iloc[pos] = -0.035                  # l'actif monte peut-être, mais il fait moins bien que son benchmark

    n = predict_module._update_live_outcomes(conn, tid, HORIZON, pd.DataFrame({"AAA": asset}), "AAA",
                                             forward_returns=alpha)

    y_true, y_class = conn.execute("SELECT y_true, y_class FROM prediction WHERE ts = ?", (ts,)).fetchone()
    assert n == 1 and y_true == 0.0
    assert y_class == classify_return(-0.035, "L", {"L": (-0.02, 0.02)}) == 0


def test_live_outcome_stays_pending_while_the_alpha_horizon_has_not_elapsed(tmp_path):
    conn = db.connect(str(tmp_path / "p.db"))
    tid = _trial(conn)
    asset, bench = _frames()
    ts = str(asset.index[-3])
    db.add_predictions(conn, tid, 0, "live", [ts], [None], [3])
    alpha = at.alpha_labels(asset, bench, HORIZON)                              # NaN sur les HORIZON derniers points

    assert predict_module._update_live_outcomes(conn, tid, HORIZON, pd.DataFrame({"AAA": asset}), "AAA",
                                                forward_returns=alpha) == 0


def test_daily_prediction_now_includes_alpha_runs(conn, tmp_path):
    from patrick import live_refresh
    db.upsert_snapshot(conn, "snap", "h", 0, 0, "api")
    db.create_run(conn, "ra", target="AAA__alpha_BBB", horizon=HORIZON, snapshot_id="snap", config_json="{}",
                  config_hash="h", git_sha="s", seed=0)
    conn.execute("UPDATE run SET status = 'done', finished_at = datetime('now') WHERE run_id = 'ra'")
    tid = db.create_trial(conn, "ra", "GLOBAL", "X", "none", 1, "shap")
    model = tmp_path / "m.joblib"
    model.write_bytes(b"x")
    conn.execute("UPDATE trial SET is_best = 1, artifact_path = ? WHERE trial_id = ?", (str(model), tid))
    conn.commit()

    assert [c.target for c in live_refresh.find_predictable_candidates(conn)] == ["AAA__alpha_BBB"]


@pytest.mark.slow
def test_predict_live_end_to_end_on_an_alpha_run(tmp_path, monkeypatch):
    raw_v1 = _synthetic_raw()
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: raw_v1)
    cfg = RunConfig.model_validate({
        "name": "alpha_live",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [HORIZON], "regimes": ["GLOBAL"],
                      "target_kind": "alpha", "benchmark": "SPX_LIKE"},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
                     "start_date": "2015-01-01"},
        "features": {"families": ["technical", "interactions", "spike", "vol_models", "macro"],
                     "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6, "pool_prefilter": 60},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]}, "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42}})
    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    assert engine_module.run_pipeline(cfg, store=store, db_path=db_path)["model_path"] is not None
    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = ?", (HORIZON,)).fetchone()[0]
    conn.close()

    raw_v2 = _extend_raw(raw_v1, extra_days=10, seed=1)
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: raw_v2)
    live1 = predict_module.predict_live(run_id, db_path=db_path, store=store)
    assert live1["y_pred"] in (0, 1, 2, 3) and live1["n_outcomes_updated"] == 0
    conn = sqlite3.connect(db_path)
    thr_lo, thr_hi = conn.execute("SELECT live_thr_lo, live_thr_hi FROM prediction WHERE trial_id = ? AND ts = ?",
                                  (live1["trial_id"], live1["ts"])).fetchone()
    conn.close()
    assert thr_lo is not None and thr_hi is not None and thr_lo < thr_hi

    # Cas discriminant : le prix de la cible MONTE (+1 %/jour) alors que le rendement excédentaire est négatif.
    raw_v3 = _extend_raw(raw_v2, extra_days=10, seed=2)
    future = raw_v3.index > raw_v2.index[-1]
    raw_v3.loc[future, "IDX_TEST"] = raw_v2["IDX_TEST"].iloc[-1] * 1.01 ** np.arange(1, int(future.sum()) + 1)
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: raw_v3)
    monkeypatch.setattr(predict_module, "_alpha_forward_returns",
                        lambda raw, config, target_col, horizon: pd.Series(-0.5, index=raw.index))

    live2 = predict_module.predict_live(run_id, db_path=db_path, store=store)

    assert live2["n_outcomes_updated"] == 1
    conn = sqlite3.connect(db_path)
    y_true, y_class = conn.execute("SELECT y_true, y_class FROM prediction WHERE trial_id = ? AND ts = ?",
                                   (live1["trial_id"], live1["ts"])).fetchone()
    conn.close()
    assert raw_v3["IDX_TEST"].iloc[-1] > raw_v2["IDX_TEST"].iloc[-1]          # le prix a bien monté
    assert y_true == 0.0 and y_class == 0                                       # mais l'alpha est négatif : perdu
