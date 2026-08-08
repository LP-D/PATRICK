"""`patrick predict --live` (Phase 4.6): scores a run's already-exported model
on the most recent data, writes the prediction to `prediction` with
`split='live'` BEFORE the outcome is known (paper trading), and backfills
`y_true` for past live predictions whose horizon has since elapsed.

Never retrains and never re-selects anything: loads the already-exported
model+scaler (`tracking.export.export_best_model`) and only rebuilds today's
feature vector, following the same recipe as at export time (`feature_pool`
+ interaction formulas persisted alongside the model).

`y_true` for `split='live'` is simplified to binary (1.0 if the realized
return over the horizon is positive, 0.0 otherwise) rather than reclassified
into the model's 4 classes DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT:
reproducing `features/target.py`'s per-quantile/regime thresholds at
inference time would require persisting them separately (not done here, out
of scope for Phase 4 -- see phase report). This simplified value is only used
for the "was the prediction right about direction?" display, never to
retrain or select a model.
"""
from __future__ import annotations

import sqlite3

import joblib
import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.pipeline.engine import (
    _apply_interaction_formulas,
    build_base_feature_pool,
    build_parametric_pool,
)
from patrick.tracking import db as trackdb


def _find_best_trial(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT trial_id, artifact_path FROM trial WHERE run_id = ? AND is_best = 1 "
        "ORDER BY trial_id DESC LIMIT 1", (run_id,),
    ).fetchone()
    if row is None or not row[1]:
        return None
    return {"trial_id": row[0], "artifact_path": row[1]}


def _update_live_outcomes(conn: sqlite3.Connection, trial_id: int, horizon: int,
                           raw: pd.DataFrame, target_col: str) -> int:
    pending = trackdb.list_pending_live_predictions(conn, trial_id)
    if not pending:
        return 0
    series = raw[target_col]
    n_updated = 0
    for row in pending:
        ts = pd.Timestamp(row["ts"])
        pos = series.index.searchsorted(ts)
        if pos >= len(series.index) or series.index[pos] != ts:
            continue  # signal date not (yet) found as-is in the fresh history
        future_idx = pos + horizon
        if future_idx >= len(series.index):
            continue  # horizon not yet elapsed
        ret = series.iloc[future_idx] / series.iloc[pos] - 1
        y_true_binary = 1.0 if ret > 0 else 0.0
        trackdb.update_prediction_outcome(conn, trial_id, row["ts"], y_true_binary)
        n_updated += 1
    return n_updated


def predict_live(run_id: str, db_path: str | None = None, store: DataStore | None = None) -> dict:
    conn = trackdb.connect(db_path)
    try:
        run = trackdb.get_run(conn, run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        best = _find_best_trial(conn, run_id)
        if best is None:
            raise ValueError(f"No exported model (winning trial) for run {run_id}.")

        bundle = joblib.load(best["artifact_path"])
        model, scaler = bundle["model"], bundle["scaler"]
        feature_pool, feature_names = bundle["feature_pool"], bundle["feature_names"]
        interaction_formulas = bundle.get("interaction_formulas", [])
        target_col = bundle["target_col"]

        config = RunConfig.model_validate_json(run["config_json"])
        store = store or DataStore()
        raw = ingest(config.objective, config.universe, store, force=True, data_quality=config.data_quality)

        base_pool = build_base_feature_pool(raw, config, target_col)
        full_pool = pd.concat([base_pool, build_parametric_pool(raw, config, fit_end_idx=None)], axis=1)
        full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
        if interaction_formulas:
            inter = _apply_interaction_formulas(full_pool, interaction_formulas)
            full_pool = pd.concat([full_pool, inter], axis=1)

        missing = [c for c in feature_pool if c not in full_pool.columns]
        if missing:
            raise ValueError(
                f"Training pool columns missing from the fresh data: {missing[:5]}"
                f"{'...' if len(missing) > 5 else ''} -- the config may have changed since export.")

        last_row = full_pool[feature_pool].iloc[[-1]]
        last_ts = full_pool.index[-1]
        X = scaler.transform(np.nan_to_num(last_row.values))
        sel_idx = [feature_pool.index(n) for n in feature_names]
        X_sel = X[:, sel_idx]

        pred_class = int(model.predict(X_sel)[0])
        proba_row = model.predict_proba(X_sel)[0]
        confidence = float(proba_row[pred_class])

        trackdb.add_predictions(conn, best["trial_id"], fold_index=0, split="live",
                                 ts=[str(last_ts)], y_true=[None], y_pred=[pred_class],
                                 y_proba=[confidence])

        n_updated = _update_live_outcomes(conn, best["trial_id"], run["horizon"], raw, target_col)

        return {"run_id": run_id, "trial_id": best["trial_id"], "ts": str(last_ts),
                "y_pred": pred_class, "y_proba": confidence, "n_outcomes_updated": n_updated}
    finally:
        conn.close()
