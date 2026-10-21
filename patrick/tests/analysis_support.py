"""Run synthétique complet pour les tests d'analyse : prix en marche aléatoire dans un lac de données temporaire, classes réelles
dérivées des rendements futurs (comme `features/target.py`), prédictions à signal réglable, métriques de plis, baselines, stabilité."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.webapp.forms import default_config_dict

N_DAYS = 1600


def make_prices(n: int = N_DAYS, seed: int = 0, drift: float = 0.0004) -> pd.Series:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.011, n)
    idx = pd.bdate_range("2014-01-01", periods=n)
    return pd.Series(100.0 * np.exp(np.cumsum(r)), index=idx, name="TST")


def classes_from_returns(ret: pd.Series) -> pd.Series:
    lo, hi = ret.quantile(0.25), ret.quantile(0.75)
    return pd.Series(np.where(ret < lo, 0, np.where(ret < 0, 1, np.where(ret < hi, 2, 3))), index=ret.index)


def seed_run(tmp_path, monkeypatch, *, run_id: str = "run_an", target: str = "TST", horizon: int = 2, skill: float = 0.6,
             seed: int = 1, scheme: str = "walkforward", with_store: bool = True, n_wf: int = 3, live: int = 3,
             algo: str = "XGBoost", extra_trials: int = 2):
    """Crée la base temporaire, le lac de données et un run terminé avec son essai gagnant ; renvoie (conn, ctx_info).

    `skill` : probabilité que le signal copie la direction réalisée (0.5 = hasard)."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    prices = make_prices(seed=seed)
    snapshot_id = "none"
    if with_store:
        store = DataStore()
        frame = pd.DataFrame({"TST": prices, "OTHER": prices * 2.0})
        frame.index.name = "Date"
        snapshot_id = store.save(f"raw_{target}", frame)
    cfg = default_config_dict()
    cfg["name"] = f"{target}_test"
    cfg["objective"].update({"target_symbol": target, "horizons": [horizon], "regimes": ["GLOBAL"]})
    cfg["validation"].update({"scheme": scheme, "n_wf_folds": n_wf})
    trackdb.upsert_snapshot(conn, snapshot_id, "hash", None, None, None)
    trackdb.create_run(conn, run_id, target, horizon, snapshot_id, json.dumps(cfg), "cfghash", "sha", 42)
    trial_id = trackdb.create_trial(conn, run_id, "GLOBAL", algo, "SMOTE", 8, "shap")
    trackdb.mark_best_trial(conn, trial_id)
    for i in range(extra_trials):
        other = trackdb.create_trial(conn, run_id, "GLOBAL", "LightGBM", "SMOTE", 5 + i, "shap")
        trackdb.add_fold_metrics(conn, other, 1, "test", {"F1_dir": 0.50 + 0.01 * i, "Acc_dir": 0.51})
    fwd = prices.shift(-horizon) / prices - 1.0
    valid = fwd.dropna()
    valid = valid[valid.abs() >= 0.003]
    yt = classes_from_returns(valid)
    rng = np.random.default_rng(seed + 100)
    up_true = yt >= 2
    copy = rng.random(len(yt)) < skill
    up_pred = np.where(copy, up_true.to_numpy(), ~up_true.to_numpy())
    yp = np.where(up_pred, np.where(rng.random(len(yt)) < 0.5, 2, 3), np.where(rng.random(len(yt)) < 0.5, 0, 1))
    p_up = np.clip(np.where(up_pred, 0.5 + 0.25 * rng.random(len(yt)), 0.5 - 0.25 * rng.random(len(yt))), 0.02, 0.98)
    conf = np.clip(0.4 + 0.5 * rng.random(len(yt)), 0, 1)
    n = len(yt)
    hold_start = int(n * 0.85)
    test_end = hold_start
    first = int(n * 0.30)
    cuts = np.linspace(first, test_end, n_wf + 1).astype(int)
    dates = [d.strftime("%Y-%m-%d") for d in yt.index]
    if scheme == "walkforward":
        for k in range(n_wf):
            a, b = cuts[k], cuts[k + 1]
            trackdb.add_predictions(conn, trial_id, k + 1, "test", dates[a:b], yt.to_numpy()[a:b], yp[a:b], conf[a:b], p_up=p_up[a:b])
            ut, up = up_true.to_numpy()[a:b], up_pred[a:b]
            trackdb.add_fold_metrics(conn, trial_id, k + 1, "test", {
                "F1_dir": float((ut == up).mean()), "Acc_dir": float((ut == up).mean()), "n_train": float(a), "effective_n_train": float(a) / 2,
                "AUC_ovr_4cls": 0.5 + 0.1 * (skill - 0.5)})
    else:
        trackdb.add_predictions(conn, trial_id, 0, "test_path", dates[first:test_end], yt.to_numpy()[first:test_end], yp[first:test_end],
                                conf[first:test_end], path_id=0, p_up=p_up[first:test_end])
        trackdb.add_predictions(conn, trial_id, 1, "test_path", dates[first:test_end], yt.to_numpy()[first:test_end], yp[first:test_end],
                                conf[first:test_end], path_id=1, p_up=p_up[first:test_end])
        for path_id in (0, 1):
            trackdb.add_fold_metrics(conn, trial_id, path_id, "test_path", {"F1_dir": 0.5 + 0.02 * path_id})
    trackdb.add_predictions(conn, trial_id, 0, "holdout", dates[hold_start:], yt.to_numpy()[hold_start:], yp[hold_start:], conf[hold_start:],
                            p_up=p_up[hold_start:])
    ut_h, up_h = up_true.to_numpy()[hold_start:], up_pred[hold_start:]
    trackdb.add_fold_metrics(conn, trial_id, 0, "holdout", {"F1_dir": float((ut_h == up_h).mean()), "Acc_dir": float((ut_h == up_h).mean())})
    if live:
        live_ts = [(yt.index[-1] + pd.Timedelta(days=i + 1)).strftime("%Y-%m-%d 00:00:00") for i in range(live)]
        trackdb.add_predictions(conn, trial_id, 0, "live", live_ts, [None] * live, [2.0] * live, [0.6] * live, p_up=[0.6] * live)
    trackdb.add_baseline_metrics(conn, run_id, "majority", "test", {"F1_dir": 0.45, "Acc_dir": 0.54})
    trackdb.save_feature_stability(conn, run_id, 0.7, 3, {"CL_ret_1d": 1.0, "IDX_GSPC_zscore_10d": 0.66, "CPI_kalman_filtered": 0.33})
    trackdb.finish_run(conn, run_id, status="done", n_trials=1 + extra_trials)
    return conn, {"trial_id": trial_id, "prices": prices, "yt": yt, "up_true": up_true, "up_pred": up_pred, "horizon": horizon,
                  "hold_start": hold_start, "dates": dates, "snapshot_id": snapshot_id, "run_id": run_id}
