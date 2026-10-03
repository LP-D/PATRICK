"""`patrick predict --live` (Phase 4.6): scores a run's already-exported model
on the most recent data, writes the prediction to `prediction` with
`split='live'` BEFORE the outcome is known (paper trading), and backfills
`y_true` for past live predictions whose horizon has since elapsed.

Never retrains and never re-selects anything: loads the already-exported
model+scaler (`tracking.export.export_best_model`) and only rebuilds today's
feature vector, following the same recipe as at export time (interaction
formulas persisted alongside the model) -- restricted to the model's
SELECTED features and the raw series they are computed from
(`selection.universe_reduction.restrict_to_required_series`; the scaler is
applied to those columns only, `tracking.export.scale_selected`), not the
whole universe.

`y_true` for `split='live'` stays BINARY (1.0 if the realized return over the
horizon is positive, 0.0 otherwise): it is the "was the prediction right about
direction?" value, never used to retrain or select a model. The realized
4-class index (DOWN_FORT/DOWN_FAIBLE/UP_FAIBLE/UP_FORT) is stored apart, in
`y_class` (migration 0028), judged with the causal thresholds memorized at
signal time (`features.target.live_class_thresholds`) -- so the live record can
say how often each of the four calls was right.

The signal is the latest bar of the target's OWN series: on a closed-market
day there is no new bar, so a second launch rewrites nothing; and the horizon
is counted in that series' own bars, so a market holiday never counts as an
elapsed day.
"""
from __future__ import annotations

import logging
import sqlite3

import joblib
import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.store import DataStore
from patrick.features.sanitize import finite_features, finite_scaled
from patrick.features.target import classify_return, live_class_thresholds
from patrick.models import calibration as calibration_lib
from patrick.pipeline.engine import build_full_feature_pool
from patrick.selection.universe_reduction import restrict_to_required_series
from patrick.tracking import db as trackdb
from patrick.tracking.export import scale_selected

logger = logging.getLogger(__name__)


def _find_best_trial(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT trial_id, artifact_path FROM trial WHERE run_id = ? AND is_best = 1 "
        "ORDER BY trial_id DESC LIMIT 1", (run_id,),
    ).fetchone()
    if row is None or not row[1]:
        return None
    return {"trial_id": row[0], "artifact_path": row[1]}


def _finite_or_none(v) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None


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
        price_at_signal = series.iloc[pos]
        if price_at_signal == 0:
            logger.warning(
                "_update_live_outcomes: zero price for %s at %s (trial %s) -- "
                "return undefined, outcome left pending.", target_col, row["ts"], trial_id)
            continue  # degenerate price, cannot compute a return (would be ZeroDivisionError/inf)
        ret = series.iloc[future_idx] / price_at_signal - 1
        y_true_binary = 1.0 if ret > 0 else 0.0
        lo, hi = _finite_or_none(row.get("thr_lo")), _finite_or_none(row.get("thr_hi"))
        y_class = (classify_return(ret, "LIVE", {"LIVE": (lo, hi)})
                   if lo is not None and hi is not None else None)
        trackdb.update_prediction_outcome(conn, trial_id, row["ts"], y_true_binary, y_class)
        n_updated += 1
    return n_updated


def _bars_to_record(full_pool: pd.DataFrame, already: set[str], model_date: pd.Timestamp | None,
                    max_backfill: int) -> list[tuple[pd.Timestamp, bool]]:
    """(bar, is_backfill): every bar strictly AFTER the model's training date
    that has no live row yet, plus the latest bar. Bars up to the training
    date were seen by the final fit -- scoring them would be in-sample."""
    last_ts = full_pool.index[-1]
    todo: list[tuple[pd.Timestamp, bool]] = []
    if model_date is not None:
        missing = [t for t in full_pool.index[:-1] if t > model_date and str(t) not in already]
        todo = [(t, True) for t in missing[-max_backfill:]]
    if str(last_ts) not in already:
        todo.append((last_ts, False))
    return todo


def _pool_as_of(model_raw: pd.DataFrame, config: RunConfig, target_col: str,
                interaction_formulas: list[str], t: pd.Timestamp) -> pd.DataFrame:
    """Feature pool exactly as it would have been computed ON bar `t`: the raw
    series are cut at `t` and EVERYTHING is rebuilt from that cut, parametric
    fits included (vol models are fitted on the whole history they are given,
    so a pool built on today's history is not the pool of an earlier day:
    measured, 4 of 12 features of a real model differ slightly). ~14 s per
    model and per bar -- the price of a backfill without data leakage."""
    return build_full_feature_pool(model_raw.loc[:t], config, target_col, interaction_formulas)


def predict_live(run_id: str, db_path: str | None = None, store: DataStore | None = None,
                 raw_cache: dict | None = None, max_backfill: int = 30) -> dict:
    """Records today's signal and every bar since the model's training date
    that was never recorded (`live_backfill=1`: app not opened that day).
    Idempotent per bar. Reconstituted bars are simulated AS OF their own date
    (`_pool_as_of`): no information posterior to the bar is used. At most
    `max_backfill` most recent missing bars per call (cost: ~14 s each).
    `raw_cache` (optional dict) shares one download between runs built on the
    same objective/universe."""
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
        cache_key = (config.objective.model_dump_json(exclude={"horizons"}),
                     config.universe.model_dump_json(), config.data_quality.model_dump_json())
        if raw_cache is not None and cache_key in raw_cache:
            raw = raw_cache[cache_key]
        else:
            raw = ingest(config.objective, config.universe, store, force=True, data_quality=config.data_quality)
            if raw_cache is not None:
                raw_cache[cache_key] = raw

        model_raw = restrict_to_required_series(raw, feature_names, target_col)
        full_pool = build_full_feature_pool(model_raw, config, target_col, interaction_formulas)

        missing = [c for c in feature_names if c not in full_pool.columns]
        if missing:
            raise ValueError(
                f"Training pool columns missing from the fresh data: {missing[:5]}"
                f"{'...' if len(missing) > 5 else ''} -- the config may have changed since export.")

        horizon = int(run["horizon"])
        last_ts = full_pool.index[-1]
        already = trackdb.live_prediction_timestamps(conn, best["trial_id"])
        model_date_raw = run.get("finished_at") or run.get("started_at")
        model_date = pd.Timestamp(model_date_raw).tz_localize(None).normalize() if model_date_raw else None

        sel_idx = [feature_pool.index(n) for n in feature_names]
        classes = list(getattr(model, "classes_", []))
        series = raw[target_col]
        n_written = 0
        new_signal = False
        for t, is_backfill in _bars_to_record(full_pool, already, model_date, max_backfill):
            if is_backfill:
                pool_t = _pool_as_of(model_raw, config, target_col, interaction_formulas, t)
                if t not in pool_t.index or any(c not in pool_t.columns for c in feature_names):
                    continue
                row_values = pool_t.loc[[t], feature_names].values
                if not np.isfinite(row_values).all():
                    continue  # reconstituted rows only from complete feature vectors
            else:
                row_values = full_pool.loc[[t], feature_names].values
            X_sel = finite_scaled(scale_selected(scaler, finite_features(row_values, "live"), sel_idx), "live")
            pred_class = int(model.predict(X_sel)[0])
            proba_row = model.predict_proba(X_sel)[0]
            # Column of the predicted class by `classes_`, not by its value: a
            # class absent from the final fit shifts the columns.
            cls_list = classes or list(range(len(proba_row)))
            confidence = float(proba_row[cls_list.index(pred_class)]) if pred_class in cls_list else float("nan")
            p_up = float(calibration_lib.p_up_from_proba(proba_row[None, :], cls_list)[0])
            trackdb.add_predictions(conn, best["trial_id"], fold_index=0, split="live",
                                     ts=[str(t)], y_true=[None], y_pred=[pred_class],
                                     y_proba=[confidence], p_up=[p_up])
            try:
                lo, hi = live_class_thresholds(series.loc[:t].dropna(), horizon, config.objective.flat_thr)
            except Exception:
                logger.exception("live thresholds failed for %s at %s", target_col, t)
                lo = hi = None
            trackdb.set_live_signal_context(conn, best["trial_id"], str(t), _finite_or_none(lo),
                                            _finite_or_none(hi), is_backfill)
            n_written += 1
            new_signal = new_signal or not is_backfill

        n_updated = _update_live_outcomes(conn, best["trial_id"], horizon, raw, target_col)
        row = conn.execute(
            "SELECT y_pred, y_proba, p_up FROM prediction "
            "WHERE trial_id = ? AND ts = ? AND split = 'live'", (best["trial_id"], str(last_ts))).fetchone()
        y_pred, y_proba, p_up_now = (int(row[0]), row[1], row[2]) if row else (None, None, None)
        return {"run_id": run_id, "trial_id": best["trial_id"], "ts": str(last_ts),
                "y_pred": y_pred, "y_proba": y_proba, "p_up": p_up_now,
                "n_outcomes_updated": n_updated, "n_written": n_written, "new_signal": new_signal}
    finally:
        conn.close()
