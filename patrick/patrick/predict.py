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

from patrick.clock import utc_now
from patrick.config.schema import RunConfig
from patrick.data import alignment, session_calendar
from patrick.data.ingest import ingest
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.features import alpha_target
from patrick.features.sanitize import finite_features, finite_scaled
from patrick.features.target import classify_return, live_class_thresholds
from patrick.models import calibration as calibration_lib
from patrick.pipeline.engine import build_full_feature_pool
from patrick.selection.universe_reduction import restrict_to_required_series
from patrick.tracking import db as trackdb
from patrick.tracking.export import scale_selected

logger = logging.getLogger(__name__)

# Les signaux jugés depuis moins de 30 jours sont recalculés à chaque passage sur les données fraîches : un cours figé ou
# une dernière barre partielle d'une mauvaise journée de la source ne doit pas rester gravé dans le suivi.
RECHECK_DAYS = 30


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


def _alpha_forward_returns(raw: pd.DataFrame, config: RunConfig, target_col: str, horizon: int) -> pd.Series | None:
    """Rendement excédentaire réalisé à `horizon` barres, par date de signal (NaN tant que l'horizon n'est pas
    écoulé) pour une cible alpha ; `None` pour une cible brute (le prix suffit)."""
    obj = config.objective
    if obj.target_kind != "alpha":
        return None
    return alpha_target.alpha_labels(raw[target_col], raw[clean_symbol(obj.benchmark)], horizon,
                                     bench_lag=alpha_target.bench_lag(obj))


def _alpha_live_thresholds(raw: pd.DataFrame, config: RunConfig, target_col: str, t: pd.Timestamp,
                           horizon: int) -> tuple[float, float]:
    """Seuils (q25, q75) du rendement excédentaire au jour du signal *t*, ajustés sur ce qui est connu à *t*."""
    obj = config.objective
    asset_t = raw[target_col].loc[:t].dropna()
    bench_t = raw[clean_symbol(obj.benchmark)].loc[:t]
    ret = alpha_target.alpha_labels(asset_t, bench_t, horizon, bench_lag=alpha_target.bench_lag(obj))
    return live_class_thresholds(asset_t, horizon, obj.flat_thr, ret=ret)


def _realised_outcome(ret: float, row: dict) -> tuple[float, int | None] | None:
    """(`y_true` binaire, `y_class`) d'un rendement réalisé ; `None` si le cours n'a pas bougé du tout.

    Un rendement EXACTEMENT nul à l'horizon est le signe d'un cours figé (source en panne, dernière valeur recopiée par
    le forward-fill) bien plus qu'un vrai marché plat : il ne juge rien -- ni hausse ni baisse -- et le signal reste
    en attente plutôt que d'être compté « pas de hausse » dans un tableau et « hausse faible » dans l'autre."""
    if ret == 0:
        return None
    lo, hi = _finite_or_none(row.get("thr_lo")), _finite_or_none(row.get("thr_hi"))
    y_class = (classify_return(ret, "LIVE", {"LIVE": (lo, hi)}) if lo is not None and hi is not None else None)
    return (1.0 if ret > 0 else 0.0), y_class


def _update_live_outcomes(conn: sqlite3.Connection, trial_id: int, horizon: int,
                           raw: pd.DataFrame, target_col: str,
                           forward_returns: pd.Series | None = None,
                           verdicts: list[bool] | None = None,
                           recheck_since: str | None = None) -> int:
    """Juge les signaux dont l'horizon est écoulé ; renvoie le nombre de signaux NOUVELLEMENT jugés.

    `forward_returns` (cible alpha) : rendement excédentaire réalisé par date de signal ; sans lui, rendement
    brut du prix de la cible (comportement historique).

    `verdicts` (optionnel) : reçoit, pour chaque signal jugé pendant cet appel, `True` si le sens prédit (hausse /
    baisse) était le bon -- de quoi dire « combien de signaux jugés aujourd'hui, et combien justes ».

    `recheck_since` (date `YYYY-MM-DD`, optionnel) : les signaux déjà jugés depuis cette date sont recalculés sur les
    données fraîches et corrigés si le verdict diffère (cours corrigé par la source, dernière barre partielle, cours
    figé) ; un cours devenu inchangé les remet en attente. Ces corrections ne sont pas comptées dans le retour."""
    pending = trackdb.list_pending_live_predictions(conn, trial_id, recheck_since)
    if not pending:
        return 0
    series = raw[target_col]
    n_updated = n_corrected = 0
    for row in pending:
        ts = pd.Timestamp(row["ts"])
        pos = series.index.searchsorted(ts)
        if pos >= len(series.index) or series.index[pos] != ts:
            continue  # signal date not (yet) found as-is in the fresh history
        future_idx = pos + horizon
        if future_idx >= len(series.index):
            continue  # horizon not yet elapsed
        if forward_returns is not None:
            ret = forward_returns.get(ts, np.nan)
            if not np.isfinite(ret):
                continue  # excess return not yet defined (horizon not elapsed, or beta unknown)
        else:
            price_at_signal = series.iloc[pos]
            if price_at_signal == 0:
                logger.warning(
                    "_update_live_outcomes: zero price for %s at %s (trial %s) -- "
                    "return undefined, outcome left pending.", target_col, row["ts"], trial_id)
                continue  # degenerate price, cannot compute a return (would be ZeroDivisionError/inf)
            ret = series.iloc[future_idx] / price_at_signal - 1
        known = row.get("y_true") is not None
        outcome = _realised_outcome(ret, row)
        if outcome is None:
            if known:   # jugé à tort sur un cours figé : redevient en attente
                trackdb.clear_prediction_outcome(conn, trial_id, row["ts"])
                n_corrected += 1
            continue
        y_true_binary, y_class = outcome
        if known:
            if row["y_true"] != y_true_binary or row.get("y_class") != y_class:
                trackdb.update_prediction_outcome(conn, trial_id, row["ts"], y_true_binary, y_class)
                n_corrected += 1
            continue
        trackdb.update_prediction_outcome(conn, trial_id, row["ts"], y_true_binary, y_class)
        n_updated += 1
        if verdicts is not None and row.get("y_pred") is not None:
            verdicts.append((round(row["y_pred"]) >= 2) == bool(y_true_binary))
    if n_corrected:
        logger.info("_update_live_outcomes: %d verdict(s) of trial %s redone on fresh data.", n_corrected, trial_id)
    return n_updated


def _record_last_value(conn: sqlite3.Connection, target: str, series: pd.Series, asset_class: str,
                       store: DataStore, symbol: str) -> None:
    """Retient le dernier cours de l'actif (affiché dans /predictions avec sa date). La série du modèle est forward-fillée :
    la vraie date de dernière observation vient de l'index des séries du store, sinon de la dernière barre."""
    try:
        observed = series.dropna()
        if observed.empty:
            return
        session_ts = observed.index[-1]
        seen = store.series_observation(symbol)
        if seen and seen.get("date_max"):
            real = pd.Timestamp(seen["date_max"])
            if real in observed.index:
                session_ts = real
        now = utc_now()
        session = pd.Timestamp(session_ts).date()
        trackdb.upsert_asset_last_value(conn, target, session.isoformat(), float(observed.loc[session_ts]),
                                        session_calendar.bar_is_final(asset_class, session, now), now.isoformat())
    except Exception:
        logger.exception("last value not recorded for %s", target)


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

        # Same look-ahead alignment as at training time (`data/alignment.py`); empty for runs that predate it.
        raw = alignment.apply_spec(raw, config.objective.alignment)
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

        # Classe de marché de la cible : sert à dire, à l'instant du signal, si la barre du jour est la clôture ou un cours en séance.
        asset_class = session_calendar.classify_asset_class(config.objective.target_symbol, config.objective.target_source)
        sel_idx = [feature_pool.index(n) for n in feature_names]
        classes = list(getattr(model, "classes_", []))
        series = raw[target_col]
        alpha_forward = _alpha_forward_returns(raw, config, target_col, horizon)   # None pour une cible brute
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
            if getattr(model, "needs_history", False):
                # Réseau à fenêtre : il lit les `lookback` dernières lignes réelles, pas une ligne isolée. Les barres de rattrapage
                # (lignes reconstituées « à la date t ») n'ont pas d'historique reconstitué : elles sont sautées, jamais approximées.
                if is_backfill:
                    continue
                history = full_pool.loc[:t, feature_names].tail(model.window)
                if len(history) < model.window:
                    continue
                try:
                    X_hist = finite_scaled(scale_selected(scaler, finite_features(history.values, "live"), sel_idx), "live")
                except ValueError:
                    continue
                proba_row = model.predict_proba(X_hist, context="none")[-1]
                pred_class = int(model.classes_[int(np.argmax(proba_row))])
            else:
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
                if alpha_forward is not None:
                    lo, hi = _alpha_live_thresholds(raw, config, target_col, t, horizon)
                else:
                    lo, hi = live_class_thresholds(series.loc[:t].dropna(), horizon, config.objective.flat_thr)
            except Exception:
                logger.exception("live thresholds failed for %s at %s", target_col, t)
                lo = hi = None
            trackdb.set_live_signal_context(conn, best["trial_id"], str(t), _finite_or_none(lo),
                                            _finite_or_none(hi), is_backfill,
                                            bar_final=True if is_backfill else session_calendar.bar_is_final(
                                                asset_class, pd.Timestamp(t).date(), utc_now()),
                                            ref_price=_finite_or_none(series.get(t)))
            n_written += 1
            new_signal = new_signal or not is_backfill

        verdicts: list[bool] = []
        recheck_since = str((pd.Timestamp(last_ts) - pd.Timedelta(days=RECHECK_DAYS)).date())
        n_updated = _update_live_outcomes(conn, best["trial_id"], horizon, raw, target_col,
                                          forward_returns=alpha_forward, verdicts=verdicts,
                                          recheck_since=recheck_since)
        _record_last_value(conn, run["target"], series, asset_class, store, config.objective.target_symbol)
        row = conn.execute(
            "SELECT y_pred, y_proba, p_up FROM prediction "
            "WHERE trial_id = ? AND ts = ? AND split = 'live'", (best["trial_id"], str(last_ts))).fetchone()
        y_pred, y_proba, p_up_now = (int(row[0]), row[1], row[2]) if row else (None, None, None)
        return {"run_id": run_id, "trial_id": best["trial_id"], "ts": str(last_ts),
                "y_pred": y_pred, "y_proba": y_proba, "p_up": p_up_now,
                "n_outcomes_updated": n_updated, "n_outcomes_right": sum(verdicts),
                "n_written": n_written, "new_signal": new_signal}
    finally:
        conn.close()
