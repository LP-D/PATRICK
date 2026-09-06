"""Phase 7 -- on-demand SHAP waterfall for the most recent RECORDED
prediction of a (target, horizon) pair (`/targets/{ticker}` page).

Feasibility (see `docs/`-less root-level note referenced from the phase
report, and the measurement script this module's numbers come from):
`shap.TreeExplainer` built fresh on a real exported model
(`~/.patrick/runs/mon_run/BTC_USD_1_best_model_h1.joblib`, LightGBM, N=15
selected features) + `shap_values` on ONE row measured at ~0.73s cold
end-to-end (joblib.load + TreeExplainer() + shap_values), ~5ms warm
(explainer reused). Both are well inside "on-demand page display" budget --
this module always rebuilds the explainer fresh (no cross-request caching):
even the cold cost is acceptable for a button-triggered, once-per-view
computation, and caching a `TreeExplainer` (which pins a reference to the
fitted model + background data) across requests is unnecessary complexity
for this traffic level (a local, single-user tool).

Deliberately NOT reusing `selection/shap_select.py`'s SHAP values: those are
computed on a throwaway "pilot" XGBoost (n_estimators=80, max_depth=4,
`shap_rank`) trained ONLY to rank/select features, discarded right after
(`shap_selection_cache`, migration 0014, persists `selected_columns` only --
never the SHAP values themselves). The actually EXPORTED model
(`tracking/export.py::export_best_model`) can be any of the 5
`models/registry.py::ML_ALGOS`, with tuned hyperparameters and resampled
training data -- a completely different fitted object. Explaining a real
prediction requires SHAP values from THAT model, computed here.

Deliberately NOT re-running live inference (`predict.py`'s job): this reads
the most recent row already written to the `prediction` table (whichever
split -- holdout/test/test_path/live) and rebuilds ONLY that historical
date's feature row from cached raw data (`ingest(..., force=False)` --
no network call), rather than forcing a fresh download of today's bar.

HONEST CAVEAT (found while smoke-testing against a real run, not part of
the original SHAP-cost question but worth recording): the SHAP call is
cheap, but `build_base_feature_pool` + `build_parametric_pool` (EGARCH /
Kalman / HMM / particle-filter re-estimation across the WHOLE universe,
`fit_end_idx=None`) are NOT -- measured end-to-end on the real
`BTC-USD`/h1 export (`~/.patrick/runs/mon_run`, cached raw data, no network
call): ~33.6s total, of which the SHAP step itself is a rounding error
(<1s). That reconstruction cost is pre-existing (`predict.py`'s live
inference pays the same price) and not something this module adds -- but it
means the "generate explanation" button on `/targets/{ticker}` is a genuine
wait, not an instant refresh; the page reflects that (`shap_loading`
message + disabled button while the request is in flight) rather than
implying it is free.
"""
from __future__ import annotations

import sqlite3

import joblib
import numpy as np
import pandas as pd
import shap

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import (
    _apply_interaction_formulas,
    build_base_feature_pool,
    build_parametric_pool,
)
from patrick.tracking import db as trackdb

# `features/target.py::build_target`'s class order (0..3), spelled out here
# once for display purposes -- that module fixes the mapping, this one only
# names it.
CLASS_NAMES = ["DOWN_FORT", "DOWN_FAIBLE", "UP_FAIBLE", "UP_FORT"]


def _find_best_trial_for_horizon(conn: sqlite3.Connection, target: str, horizon: int) -> dict | None:
    """Latest DONE run for (target, horizon) that has an exported best trial
    (`artifact_path` populated) -- same per-run lookup as `predict.py`'s
    `_find_best_trial`, generalized to "most recent run of this horizon"
    since the waterfall is addressed by (ticker, horizon), not by run_id."""
    run_rows = conn.execute(
        "SELECT run_id FROM run WHERE target = ? AND horizon = ? AND status = 'done' "
        "ORDER BY started_at DESC, rowid DESC",
        (target, horizon),
    ).fetchall()
    for (run_id,) in run_rows:
        trial = conn.execute(
            "SELECT trial_id, artifact_path FROM trial WHERE run_id = ? AND is_best = 1 "
            "ORDER BY trial_id DESC LIMIT 1", (run_id,),
        ).fetchone()
        if trial is not None and trial[1]:
            return {"run_id": run_id, "trial_id": trial[0], "artifact_path": trial[1]}
    return None


def explain_last_prediction(target: str, horizon: int, db_path: str | None = None,
                             store: DataStore | None = None) -> dict | None:
    """Returns per-feature SHAP contributions for the most recent recorded
    prediction of (target, horizon), ready for a waterfall display, or
    `None` when nothing can be explained (no exported model, no recorded
    prediction, or the training pool's columns have drifted since export --
    same "config changed since export" guard as `predict.py`).

    Returned dict:
      run_id, trial_id, ts, split, y_pred, y_pred_label, y_proba,
      base_value, final_value, contributions (list of {name, value, shap},
      sorted by |shap| descending), n_features_total.

    `base_value`/`final_value`/each `contributions[i]["shap"]` are in the
    model's RAW output space for the predicted class (TreeExplainer's
    default `model_output="raw"` -- margin/log-odds-like units, NOT a
    probability breakdown: for a multiclass tree ensemble, SHAP's additivity
    guarantee holds in this raw space, not after the softmax). Callers must
    label this accordingly rather than presenting it as a probability
    decomposition.
    """
    conn = trackdb.connect(db_path)
    try:
        best = _find_best_trial_for_horizon(conn, target, horizon)
        if best is None:
            return None

        latest = trackdb.latest_prediction_for_trial(conn, best["trial_id"])
        if latest is None:
            return None

        bundle = joblib.load(best["artifact_path"])
        model, scaler = bundle["model"], bundle["scaler"]
        feature_pool, feature_names = bundle["feature_pool"], bundle["feature_names"]
        interaction_formulas = bundle.get("interaction_formulas", [])
        target_col = bundle["target_col"]

        run = trackdb.get_run(conn, best["run_id"])
        config = RunConfig.model_validate_json(run["config_json"])
        store = store or DataStore()
        # `force=False` (default): the date being explained already happened,
        # so the locally cached raw series (no network call) is enough --
        # unlike `predict.py`'s live inference, this never needs today's bar.
        raw = ingest(config.objective, config.universe, store, data_quality=config.data_quality)

        base_pool = build_base_feature_pool(raw, config, target_col)
        full_pool = pd.concat([base_pool, build_parametric_pool(raw, config, fit_end_idx=None)], axis=1)
        full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
        if interaction_formulas:
            inter = _apply_interaction_formulas(full_pool, interaction_formulas)
            full_pool = pd.concat([full_pool, inter], axis=1)

        missing = [c for c in feature_pool if c not in full_pool.columns]
        if missing:
            return None

        ts = pd.Timestamp(latest["ts"])
        if ts not in full_pool.index:
            return None
        row = full_pool[feature_pool].loc[[ts]]

        X = scaler.transform(np.nan_to_num(row.values))
        sel_idx = [feature_pool.index(n) for n in feature_names]
        X_sel = X[:, sel_idx]

        pred_class = int(latest["y_pred"])

        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_sel)
        sv_arr = np.asarray(sv)
        nf = len(feature_names)
        # Same axis-by-size fix as `selection/shap_select.py` -- multiclass
        # `shap_values` output layout varies by shap version. Empirically
        # verified on the real exported model this module was benchmarked
        # against (LightGBM, N=15, 4 classes, 1 row): shape (1, 15, 4), i.e.
        # (n_obs, n_features, n_classes) -- `feat_axis` locates the features
        # axis by size rather than assuming that fixed order holds everywhere.
        if sv_arr.ndim == 3:
            feat_axis = next((ax for ax in (1, 2) if sv_arr.shape[ax] == nf), 1)
            contrib = sv_arr[0, :, pred_class] if feat_axis == 1 else sv_arr[pred_class, 0, :]
        elif sv_arr.ndim == 2:
            contrib = sv_arr[0]
        else:  # legacy multiclass API: list of length n_classes, each (n_obs, n_features)
            contrib = np.asarray(sv)[pred_class][0]

        expected = explainer.expected_value
        base_value = float(np.asarray(expected)[pred_class]) if np.ndim(expected) > 0 else float(expected)
        final_value = base_value + float(np.sum(contrib))

        raw_values = row[feature_names].iloc[0]
        contributions = sorted(
            (
                {"name": name, "value": float(raw_values[name]), "shap": float(contrib[i])}
                for i, name in enumerate(feature_names)
            ),
            key=lambda r: abs(r["shap"]), reverse=True,
        )

        return {
            "run_id": best["run_id"], "trial_id": best["trial_id"],
            "ts": str(ts.date()), "split": latest["split"],
            "y_pred": pred_class, "y_pred_label": CLASS_NAMES[pred_class],
            "y_proba": latest["y_proba"],
            "base_value": base_value, "final_value": final_value,
            "contributions": contributions, "n_features_total": len(feature_names),
        }
    finally:
        conn.close()
