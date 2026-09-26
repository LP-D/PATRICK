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
date's feature row from the data snapshot that prediction was computed on
(`_load_snapshot_for_prediction`: the run's own snapshot, or for a later
`live` prediction the earliest stored snapshot covering its date) -- local
data lake only, never `ingest()` (which returns the LATEST snapshot, i.e.
possibly revised data the model never saw, and downloads on a cold lake).

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
from patrick.features.sanitize import finite_features, finite_scaled
from patrick.pipeline.engine import build_full_feature_pool
from patrick.tracking import db as trackdb
from patrick.validation import drift

# `features/target.py::build_target`'s class order (0..3), spelled out here
# once for display purposes -- that module fixes the mapping, this one only
# names it.
CLASS_NAMES = ["DOWN_FORT", "DOWN_FAIBLE", "UP_FAIBLE", "UP_FORT"]

# Same order-of-magnitude minimum sample as `tracking.history.LIVE_HIT_RATE_WINDOW`:
# below this many recent reconstructed rows, a PSI read is noise, not signal.
DRIFT_RECENT_WINDOW = 30


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


def _load_snapshot_for_prediction(store: DataStore, target: str, run_snapshot_id: str,
                                   ts: pd.Timestamp) -> pd.DataFrame | None:
    """Raw data the explained prediction was computed on -- local data lake
    only, never a network fetch.

    - The run's own snapshot (`run.snapshot_id`) when it covers `ts`: every
      test/holdout prediction was produced from it, and the exported model
      was trained on it.
    - Otherwise (a `live` prediction made after the run, by `predict_live`,
      which ingests with `force=True` and therefore saves a new snapshot
      ending on the prediction date): the EARLIEST stored snapshot whose
      last date covers `ts` -- the closest available state to what
      `predict_live` saw, rather than today's revised data.

    `None` when no local snapshot covers `ts`."""
    key = f"raw_{target}"
    try:
        run_raw = store.load(key, snapshot_id=run_snapshot_id)
    except FileNotFoundError:
        run_raw = None
    if run_raw is not None and ts in run_raw.index:
        return run_raw
    covering = [e for e in store.list_snapshots(key)
                if e.get("date_max") and pd.Timestamp(e["date_max"]) >= ts]
    if not covering:
        return None
    earliest = min(covering, key=lambda e: (pd.Timestamp(e["date_max"]), e.get("created_at", "")))
    raw = store.load(key, snapshot_id=earliest["snapshot_id"])
    return raw if ts in raw.index else None


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
        ts = pd.Timestamp(latest["ts"])
        # The snapshot the prediction was computed on (see
        # `_load_snapshot_for_prediction`) -- never `ingest()`, which returns
        # the latest stored snapshot (or downloads on a cold data lake).
        raw = _load_snapshot_for_prediction(store, target, run["snapshot_id"], ts)
        if raw is None:
            return None
        data_snapshot_id = raw.attrs.get("snapshot_id")

        full_pool = build_full_feature_pool(raw, config, target_col, interaction_formulas)

        missing = [c for c in feature_pool if c not in full_pool.columns]
        if missing:
            return None

        if ts not in full_pool.index:
            return None
        row = full_pool[feature_pool].loc[[ts]]

        X = finite_scaled(scaler.transform(finite_features(row.values, "explain")), "explain")
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
            "ts": str(ts.date()), "split": latest["split"], "data_snapshot_id": data_snapshot_id,
            "y_pred": pred_class, "y_pred_label": CLASS_NAMES[pred_class],
            "y_proba": latest["y_proba"],
            "base_value": base_value, "final_value": final_value,
            "contributions": contributions, "n_features_total": len(feature_names),
        }
    finally:
        conn.close()


def compute_drift_for_ticker_horizon(target: str, horizon: int, db_path: str | None = None,
                                      store: DataStore | None = None,
                                      recent_window: int = DRIFT_RECENT_WINDOW) -> dict | None:
    """On-demand data-drift (PSI) check for one (target, horizon) -- ONLY
    ever called for a single pair on an explicit user action (a
    `/predictions` card click, a `/targets/{ticker}` page load), never
    looped over the full ticker list: this rebuilds the ENTIRE feature
    pool from cached raw data, the same non-trivial cost
    `explain_last_prediction`'s own docstring measures at ~33s for a real
    universe -- an unconditional per-page-load loop over every ticker
    would multiply that by the universe size for no reason a single view
    ever needs.

    Reuses `_find_best_trial_for_horizon` and the EXACT SAME feature-
    reconstruction path as `explain_last_prediction` (`ingest(force=False)`
    + `build_base_feature_pool`/`build_parametric_pool`) -- no parallel
    data path. Compares the last `recent_window` reconstructed rows
    against the reference persisted at training time
    (`tracking.export.export_best_model`, via `tracking.db.save_drift_reference`
    -- migration 0018) for each of the model's SELECTED features, appends
    one `drift_psi_history` row per feature (`tracking.db.record_drift_psi`),
    and returns `{feature: {"psi": ..., "status": ...}}`.

    Returns `None` when there is no exported model, no persisted reference
    for ANY feature yet (never trained through the drift-aware export
    path), or fewer than `recent_window` usable reconstructed rows."""
    conn = trackdb.connect(db_path)
    try:
        best = _find_best_trial_for_horizon(conn, target, horizon)
        if best is None:
            return None

        bundle = joblib.load(best["artifact_path"])
        feature_names = bundle["feature_names"]
        interaction_formulas = bundle.get("interaction_formulas", [])
        target_col = bundle["target_col"]

        run = trackdb.get_run(conn, best["run_id"])
        config = RunConfig.model_validate_json(run["config_json"])
        store = store or DataStore()
        raw = ingest(config.objective, config.universe, store, data_quality=config.data_quality)

        full_pool = build_full_feature_pool(raw, config, target_col, interaction_formulas)

        missing = [c for c in feature_names if c not in full_pool.columns]
        if missing:
            return None

        recent = full_pool[feature_names].dropna()
        if len(recent) < recent_window:
            return None
        recent = recent.tail(recent_window)

        results = {}
        for feature in feature_names:
            reference = trackdb.get_drift_reference(conn, target, horizon, feature)
            if reference is None:
                continue
            psi = drift.psi_from_reference(reference, recent[feature].to_numpy())
            status = drift.data_drift_status(psi)
            trackdb.record_drift_psi(conn, target, horizon, feature, psi)
            results[feature] = {"psi": psi, "status": status}
        return results or None
    finally:
        conn.close()
