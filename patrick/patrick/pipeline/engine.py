"""Orchestrator for the complete pipeline: ingestion -> feature construction ->
walk-forward (regime/horizon/fold) -> selection×sampler×N×algo grid -> best
model -> Optuna tuning on the top-K -> leaderboard + exported model.

Generalizes, into a single command, the manual sequence
VIX_FINAL_FEATURES -> VIX_FINAL_ML_SCAN -> VIX_FINAL_OPTUNA.

Phase 0 (correctness): the "parametric" features (EGARCH/Kalman/HMM/AR/MA/
ARMA/ARIMA from vol_models.py, particle filter from spike.py) estimate global
parameters before producing a causal recursive output — estimating them once
over the whole history (as before this fix) leaks information from one
fold's test into another fold's train, even though the point-by-point output
is itself causal (see `tests/test_leakage.py`, future-corruption test). The
feature pool is therefore split in two:
- `build_base_feature_pool`: technical/spike(excluding the particle
  filter)/macro — pure rolling windows, no global parameter, computed once.
- `build_parametric_pool`: parametric vol_models + particle filter, re-fit
  per fold via `fit_end_idx` (the fold's train only), cached per fold cut
  (independent of horizon, hence `n_wf_folds` variants, not
  `n_wf_folds × n_horizons`).
Interactions are discovered once on the pilot fold (as before) but their
FORMULAS (deterministic, algebraic) are reapplied to each fold's pool — no
leak: a formula applied to values already correctly recomputed per fold
reintroduces nothing.

Phase 1 (SQLite persistence): every evaluation (not just the winning one) is
written to `~/.patrick/patrick.db` — one `run` row per (target, horizon) of
the config (they share the same `snapshot_id`), one `trial` row per
(regime, N, sampler, algo) combination actually tested, one `fold_metric`
row per (trial, fold, metric), one `prediction` row per test observation.
The existing CSV/leaderboard is not replaced, only complemented: the
database serves Phase 2 (statistical validity), not a replacement of the
current export.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.session_calendar import classify_asset_class
from patrick.data.sources.yfinance_source import clean_symbol, download_ohlc
from patrick.data.store import DataStore
from patrick.features import macro as feat_macro
from patrick.features import spike, technical, vol_models
from patrick.features.interactions import INTERACTION_TYPES, apply_interaction, discover_interactions
from patrick.features.target import build_target
from patrick.models.calibration import calibrate_classifier, predict_with_threshold, search_threshold
from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.models.sequential_forest import SequentialBootstrapRandomForestClassifier
from patrick.models.uniqueness import average_uniqueness, build_indicator_matrix, effective_sample_size
from patrick.pipeline.leaderboard import Leaderboard
from patrick.selection.registry import select_features
from patrick.selection.stability import feature_selection_stability
from patrick.tracking import db as trackdb
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import stats as trackstats
from patrick.tracking.export import export_best_model
from patrick.tuning.optuna_runner import tune_config
from patrick.validation import cpcv as cpcv_module
from patrick.validation.baselines import compute_baselines
from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.embargo import embargo_mask
from patrick.validation.metrics import metrics
from patrick.validation.purge import purge_mask
from patrick.validation.walkforward import build_fold_cuts, describe_folds


def _finite_features(values: np.ndarray, where: str) -> np.ndarray:
    """Correction report, N2 -- replaces `np.nan_to_num(...)` at the three
    places where the feature matrix is built (walk-forward, holdout, CPCV).

    `np.nan_to_num` alone is NOT enough, and gave a false sense of safety: it
    maps ±inf to ±1.797e308 (the float64 maximum), a value that's finite at
    that instant but astronomical, which the `RobustScaler` applied right
    after divides by the column's IQR. As soon as this IQR is < 1 -- a
    common case among thousands of columns (returns, z-scores, bounded
    indicators) -- the division PRODUCES ±inf again, and XGBoost rejects the
    matrix ("Input data contains `inf` or a value too large, while `missing`
    is not set to `inf`"). Measured: a single infinite cell in a column with
    IQR 0.025 is enough to reproduce the error; since the scaler is fit on
    train only, an inf present only in TEST also goes through this path.

    An upstream ±inf always comes from a degenerate computation (division by
    a ~0 denominator in a ratio/interaction, log of a value <= 0): it carries
    no exploitable numeric information, so it is treated as a MISSING value
    -- exactly the same path as NaN, already converted to 0.0 here -- and
    never as "a very large number". Counted and reported, never silent (same
    discipline as the D3 guard on excluded folds)."""
    n_inf = int(np.isinf(values).sum())
    if n_inf:
        print(f"  [WARN] {where}: {n_inf} infinite value(s) in the feature pool "
              f"(degenerate computation: denominator ~0, log of a value <= 0) — "
              f"treated as missing.")
    return np.nan_to_num(np.where(np.isfinite(values), values, np.nan))


def _finite_scaled(scaled: np.ndarray, where: str) -> np.ndarray:
    """Correction report, N2 -- guarantees after scaling the invariant
    XGBoost needs (a fully finite matrix), which `_finite_features` alone
    cannot guarantee: an input value that is simply VERY LARGE but finite
    (never an inf, hence invisible upstream) can still overflow when divided
    by a tiny IQR. A safety net on the way out, not a replacement for the
    upstream cleanup -- both are necessary."""
    if not np.isfinite(scaled).all():
        n_bad = int((~np.isfinite(scaled)).sum())
        print(f"  [WARN] {where}: {n_bad} non-finite value(s) AFTER scaling "
              f"(overflow from an extreme value divided by a tiny IQR) — "
              f"reset to the median (0 after RobustScaler).")
        scaled = np.nan_to_num(np.where(np.isfinite(scaled), scaled, np.nan))
    return scaled


def build_base_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str) -> pd.DataFrame:
    """Features causal by construction (rolling windows/lags, no globally
    estimated parameter): technical, spike (excluding the particle filter),
    macro, + the target's OHLC vol estimators. Computed once, shared across
    all folds/horizons of a run — no leak risk (see module docstring)."""
    families = config.features.families
    parts: list[pd.DataFrame] = [raw]

    for col in raw.columns:
        s = raw[col]
        if "technical" in families:
            parts.append(technical.build_technical_features(s, prefix=col))
        if "spike" in families:
            parts.append(spike.build_spike_features_base(s, prefix=col))
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features_base(
                s, prefix=col, models=config.features.vol_models))

    if "macro" in families and config.universe.fred_series:
        macro_cols = list(config.universe.fred_series.keys())
        parts.append(feat_macro.build_macro_features(raw, macro_cols))

    if "technical" in families:
        ohlc = download_ohlc(config.objective.target_symbol, config.universe.start_date)
        if ohlc is not None:
            ohlc_aligned = ohlc.reindex(raw.index).ffill()
            parts.append(technical.ohlc_vol_features(ohlc_aligned, prefix=target_col))

    pool = pd.concat(parts, axis=1)
    pool = pool.loc[:, ~pool.columns.duplicated()]
    return pool


def build_parametric_pool(raw: pd.DataFrame, config: RunConfig,
                           fit_end_idx: int | None,
                           test_end_idx: int | None = None,
                           conn=None, snapshot_id: str | None = None) -> pd.DataFrame:
    """Parametric vol_models (EGARCH/Kalman/HMM/AR/MA/ARMA/ARIMA) + particle
    filter (spike) — re-estimated on `raw.iloc[:fit_end_idx]` only (the
    fold's train), applied causally over the whole history with no
    re-estimation. `fit_end_idx=None`: fit on the whole series (used for the
    final production model, which no longer has a test set to protect).

    `test_end_idx` (correction report, D2 -> N1): end of the current TEST
    fold. `raw` covers the whole dataset (not just this fold), so without
    this bound EGARCH would apply `.fix()` on a series extending well beyond
    the fold -- a `variance_bounds` leak channel measured as real but inert
    on realistic data (D2), closed here by construction at zero cost
    (measured free). Ignored by the other parametric models (causal
    recursions unaffected, see `vol_models._PARAMETRIC_MODELS` docstring).

    `conn`/`snapshot_id`: forwarded to `vol_models.build_vol_model_features_parametric`'s
    cache (migration 0015) when both are given -- this is the single
    production funnel that repeats identically per fold (walk-forward) or
    across separate runs of the same snapshot (CPCV, single fit). Does not
    cover `spike.build_spike_features_parametric` (particle filter) -- out
    of scope for this workstream (EGARCH/Kalman/HMM only, per the O1-O5
    scope decision)."""
    families = config.features.families
    parts: list[pd.DataFrame] = []

    for col in raw.columns:
        s = raw[col]
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features_parametric(
                s, prefix=col, models=config.features.vol_models,
                fit_end_idx=fit_end_idx, test_end_idx=test_end_idx,
                conn=conn, snapshot_id=snapshot_id))
        if "spike" in families:
            parts.append(spike.build_spike_features_parametric(s, prefix=col, fit_end_idx=fit_end_idx))

    if not parts:
        return pd.DataFrame(index=raw.index)
    pool = pd.concat(parts, axis=1)
    pool = pool.loc[:, ~pool.columns.duplicated()]
    return pool


def _discover_interaction_formulas(pool: pd.DataFrame, config: RunConfig,
                                     target_col: str, pilot_split_idx: int) -> list[str]:
    """Discovers the interaction formulas (VIX_FINAL_FEATURES) on the pilot
    fold (first fold's train) — returns the retained column names, which
    encode the feature pair + interaction type (see `INTERACTION_TYPES`),
    reusable as-is by `_apply_interaction_formulas` on the pool (base +
    parametric) of any fold."""
    pilot_horizon = config.objective.horizons[len(config.objective.horizons) // 2]
    pilot_target, _, _ = build_target(pool[target_col], pilot_horizon, pilot_split_idx,
                                       config.objective.flat_thr)
    pilot_idx = pilot_target.index
    pilot_cut_date = pool.index[pilot_split_idx]
    pilot_train_mask = np.asarray(pilot_idx < pilot_cut_date)
    y_pilot_tr = pilot_target.values[pilot_train_mask].astype(int)
    if len(y_pilot_tr) < 100:
        print("  [INTERACTIONS] not enough data on the pilot fold — step skipped.")
        return []

    feature_cols = [c for c in pool.columns if c != target_col]
    X_pilot_tr = pool.loc[pilot_idx[pilot_train_mask], feature_cols].fillna(0.0)

    inter_df = discover_interactions(
        X_pilot_tr, y_pilot_tr,
        top_base=config.features.interact_top_base,
        top_pairs=config.features.interact_top_pairs,
        final_n=config.features.interact_final_n,
        seed=config.output.seed,
    )
    return list(inter_df.columns)


def _apply_interaction_formulas(pool: pd.DataFrame, formula_names: list[str]) -> pd.DataFrame:
    """Applies already-discovered interaction formulas (column names encoding
    pair + type) to `pool`'s values — a deterministic algebraic/rolling-
    window operation, with no leak risk as long as `pool` itself is correct
    for the fold in question."""
    if not formula_names:
        return pd.DataFrame(index=pool.index)
    full_inter = pd.DataFrame(index=pool.index)
    for col_name in formula_names:
        for tname, fn in INTERACTION_TYPES.items():
            marker = f"__{tname}__"
            if marker in col_name:
                a_name, b_name = col_name.split(marker, 1)
                if a_name in pool.columns and b_name in pool.columns:
                    try:
                        # N2: `apply_interaction` (never `fn` directly) --
                        # carries the anti-inf guard, indispensable HERE: a
                        # formula sound on the pilot fold can see its
                        # denominator go to ~0 on another fold.
                        full_inter[col_name] = apply_interaction(fn, pool[a_name], pool[b_name])
                    except Exception:
                        pass
                break
    return full_inter


class _FoldPoolBuilder:
    """Builds and caches (per fold cut, independent of horizon) the full
    base+parametric+interactions pool of a fold."""

    def __init__(self, raw: pd.DataFrame, config: RunConfig, target_col: str,
                 base_pool: pd.DataFrame, fold_cuts: list[int],
                 conn=None, snapshot_id: str | None = None):
        self.raw = raw
        self.config = config
        self.target_col = target_col
        self.base_pool = base_pool
        self.fold_cuts = fold_cuts
        self.conn = conn
        self.snapshot_id = snapshot_id
        self._cache: dict[int, pd.DataFrame] = {}
        self.interaction_formulas: list[str] = []
        if "interactions" in config.features.families:
            self._init_interactions()

    def _merge_base_and_parametric(self, cut_idx: int) -> pd.DataFrame:
        # D2 -> N1: `cut_idx` is both the end of train and the start of test
        # for its fold (`fold_cuts[k]`) -- the end of THIS test fold is
        # therefore the next cut in the same list (`fold_cuts[k+1]`), or None
        # beyond the last known fold (no truncation, original behavior).
        pos = self.fold_cuts.index(cut_idx)
        test_end_idx = self.fold_cuts[pos + 1] if pos + 1 < len(self.fold_cuts) else None
        param_pool = build_parametric_pool(self.raw, self.config, fit_end_idx=cut_idx,
                                            test_end_idx=test_end_idx,
                                            conn=self.conn, snapshot_id=self.snapshot_id)
        merged = pd.concat([self.base_pool, param_pool], axis=1)
        return merged.loc[:, ~merged.columns.duplicated()]

    def _init_interactions(self) -> None:
        pilot_cut = self.fold_cuts[0]
        pilot_pool = self._merge_base_and_parametric(pilot_cut)
        self.interaction_formulas = _discover_interaction_formulas(
            pilot_pool, self.config, self.target_col, pilot_cut)
        print(f"  [INTERACTIONS] {len(self.interaction_formulas)} formulas discovered (pilot fold).")
        inter = _apply_interaction_formulas(pilot_pool, self.interaction_formulas)
        self._cache[pilot_cut] = pd.concat([pilot_pool, inter], axis=1)

    def get(self, cut_idx: int) -> pd.DataFrame:
        if cut_idx not in self._cache:
            merged = self._merge_base_and_parametric(cut_idx)
            if self.interaction_formulas:
                inter = _apply_interaction_formulas(merged, self.interaction_formulas)
                merged = pd.concat([merged, inter], axis=1)
            self._cache[cut_idx] = merged
        return self._cache[cut_idx]


@dataclass
class FoldData:
    """Output of `_FoldContext.prepare()` — a named object rather than a
    positional tuple: Phase 1 (persistence) needs `test_dates` (one date per
    test row, for the `prediction` table) in addition to what Phase 0 already
    used, and an 8th positional element was becoming unreadable/fragile to
    call."""
    X_tr: np.ndarray
    y_tr: np.ndarray
    X_te: np.ndarray
    y_te: np.ndarray
    test_start: str
    test_end: str
    test_dates: list[str]
    baselines: dict | None = None
    baseline_predictions: dict | None = None
    # Phase 6.2 (P6.2) -- uniqueness weights (one value per X_tr row, same
    # order) + observation x bar indicator matrix (for the sequential
    # bootstrap) + effective sample size (sum of uniquenesses, ALWAYS
    # computed -- a property of the labels, independent of the sampler).
    sample_weight: np.ndarray | None = None
    ind_matrix: np.ndarray | None = None
    effective_n: float | None = None


class _FoldContext:
    """Prepares X_tr/y_tr/X_te/y_te for a given (horizon, fold, regime) —
    used by both the main scan and the post-Optuna re-evaluation, to
    guarantee that both passes apply exactly the same logic (masks, purge,
    embargo, scaling)."""

    def __init__(self, pool_builder: _FoldPoolBuilder, target_col: str, feature_pool: list[str],
                 config: RunConfig, all_dates: pd.DatetimeIndex, fold_cuts: list[int]):
        self.pool_builder = pool_builder
        self.target_col = target_col
        self.feature_pool = feature_pool
        self.config = config
        self.all_dates = all_dates
        self.fold_cuts = fold_cuts

    def prepare(self, horizon: int, fold_idx: int, regime: str,
                want_baselines: bool = False) -> FoldData | None:
        cfg = self.config
        cut, nxt = self.fold_cuts[fold_idx], self.fold_cuts[fold_idx + 1]
        cut_date, nxt_date = self.all_dates[cut], self.all_dates[nxt - 1]
        pool = self.pool_builder.get(cut)

        target_series, reg_r, thr = build_target(
            pool[self.target_col], horizon, cut, cfg.objective.flat_thr)
        idx = target_series.index
        tr_mask = np.asarray(idx < cut_date)
        te_mask = np.asarray((idx >= cut_date) & (idx <= nxt_date))
        reg_al = reg_r.reindex(idx).fillna("NORMAL").values
        sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)
        tr_mask = tr_mask & sel
        te_mask = te_mask & sel

        if cfg.validation.purge:
            tr_mask = purge_mask(idx, tr_mask, self.all_dates, horizon, cut_date)
        if cfg.validation.embargo_enabled:
            e = cfg.validation.embargo_bars if cfg.validation.embargo_bars is not None else horizon
            te_mask = embargo_mask(idx, te_mask, cut_date, e)

        y_tr = target_series.values[tr_mask].astype(int)
        y_te = target_series.values[te_mask].astype(int)
        if (len(y_tr) < cfg.validation.min_train_rows
                or len(y_te) < cfg.validation.min_test_rows):
            # Correction report, D3: the guard already existed (min_train_rows/
            # min_test_rows) but excluded the fold SILENTLY -- the C3 debugging
            # incident (last walk-forward fold collapsed to 10-13 test rows,
            # `None` returned without a word) showed this forces manually
            # instrumenting the code to understand an incomplete Optuna/SCAN
            # budget. Explicit warning now systematic.
            print(f"  [WARN] fold {fold_idx + 1} excluded (h={horizon}d regime={regime}): "
                  f"train={len(y_tr)} (min {cfg.validation.min_train_rows}), "
                  f"test={len(y_te)} (min {cfg.validation.min_test_rows}).")
            return None

        X_pool_df = pool[self.feature_pool].reindex(idx)
        where = f"fold {fold_idx + 1} (h={horizon}d regime={regime})"
        sc = RobustScaler()
        X_tr = _finite_scaled(
            sc.fit_transform(_finite_features(X_pool_df.values[tr_mask], f"{where} train")), where)
        X_te = _finite_scaled(
            sc.transform(_finite_features(X_pool_df.values[te_mask], f"{where} test")), where)
        test_dates = [str(d.date()) for d in idx[te_mask]]

        # Phase 6.2 (P6.2): label spans [position, position+horizon] of the
        # TRAIN observations on the fold's bar grid (`self.all_dates`, not
        # `idx` -- `idx` has gaps, see `build_target`, "flat" rows and series
        # tail removed, whereas label overlap must be reasoned about on the
        # actual bar calendar). Local window (not the whole history): bounds
        # the indicator matrix size to the train block's actual size, not
        # thousands of days of history.
        train_dates = idx[tr_mask]
        start_positions_global = self.all_dates.get_indexer(train_dates)
        valid = start_positions_global >= 0
        if valid.all() and len(start_positions_global):
            min_pos = int(start_positions_global.min())
            n_bars_local = int(start_positions_global.max()) + horizon - min_pos + 1
            local_positions = start_positions_global - min_pos
            ind_matrix = build_indicator_matrix(local_positions, horizon, n_bars_local)
            avg_uniqueness = average_uniqueness(ind_matrix)
            effective_n = effective_sample_size(avg_uniqueness)
            sample_weight = avg_uniqueness
        else:
            ind_matrix, sample_weight, effective_n = None, None, float(len(y_tr))

        baselines = None
        baseline_predictions = None
        if want_baselines:
            # A single computation (return_predictions=True): the aggregated
            # metrics (leaderboard) AND the raw predictions (Diebold-Mariano,
            # Phase 2.5) come from the same pass, no redundant second call.
            baseline_predictions = compute_baselines(
                pool[self.target_col], target_series, idx, tr_mask, te_mask,
                y_tr, y_te, horizon, thr, reg_r, return_predictions=True)
            baselines = {name: metrics(y_te, pred) for name, pred in baseline_predictions.items()}

        return FoldData(X_tr, y_tr, X_te, y_te, str(cut_date.date()), str(nxt_date.date()),
                         test_dates, baselines, baseline_predictions,
                         sample_weight, ind_matrix, effective_n)


def _selector_config_hash(config: RunConfig, n_feat: int, seed: int) -> str:
    """S2: only the selector parameters that actually reach `select_features`/
    `shap_rank` -- method, the requested N, `shap_sample`, `pool_prefilter`,
    seed. Deliberately excludes `sampler`/`algo`/model hyperparameters and
    `selection.track_stability`: none of them are ever passed into
    `_select()`, confirmed by direct reading of every call site -- including
    one would make two selector configs that produce the SAME result look
    different (needless cache misses); omitting one that mattered would make
    two DIFFERENT results collide under the same key (silent corruption)."""
    payload = json.dumps({
        "method": config.selection.method, "n_feat": n_feat,
        "shap_sample": config.selection.shap_sample,
        "pool_prefilter": config.features.pool_prefilter, "seed": seed,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _xy_data_hash(X_tr: np.ndarray, y_tr: np.ndarray) -> str:
    """The correctness guarantee of the selection cache key (see migration
    0014): `target`/`horizon`/`snapshot_id` alone under-specify the actual
    training data -- the same snapshot produces different (X_tr, y_tr) per
    regime and per fold/CPCV-combo. Measured cost on a generously-sized
    array (4000x1000, 32MB): ~40ms full SHA-256 vs ~10s for a real SHAP
    computation of the same size (0.4%) -- negligible, no cheaper summary
    hash needed."""
    h = hashlib.sha256(np.ascontiguousarray(X_tr).tobytes())
    h.update(np.ascontiguousarray(y_tr).tobytes())
    return h.hexdigest()


def _select(conn, target: str, horizon: int, snapshot_id: str,
            config: RunConfig, X_tr: np.ndarray, y_tr: np.ndarray, n_feat: int, seed: int) -> list[int]:
    data_hash = _xy_data_hash(X_tr, y_tr)
    selector_hash = _selector_config_hash(config, n_feat, seed)
    cached = trackdb.get_cached_selection(conn, target, horizon, snapshot_id, data_hash, selector_hash)
    if cached is not None:
        return cached
    cols = [int(c) for c in select_features(config.selection.method, X_tr, y_tr, n_feat,
                                             config.features.pool_prefilter, seed=seed,
                                             shap_sample=config.selection.shap_sample)]
    trackdb.save_cached_selection(conn, target, horizon, snapshot_id, data_hash, selector_hash, cols)
    return cols


def _fit_eval(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, y_te: np.ndarray,
              sampler_name: str, algo: str, seed: int, calibration: bool = False,
              sample_weight: np.ndarray | None = None, ind_matrix: np.ndarray | None = None,
              uniqueness_weights_enabled: bool = True, **algo_overrides):
    """Returns (metrics_dict, y_pred, predicted_confidence) —
    `predicted_confidence` (probability of the predicted class, one value per
    test row) feeds `prediction.y_proba`, which has only one column (not a
    per-class vector).

    `sampler_name="none"` (Phase 5.3, `models/samplers.py::_NoResample`): no
    resampling, relies on `class_weight`/`auto_class_weights` already
    hardcoded for RandomForest/LightGBM/CatBoost (`models/registry.py`) --
    XGBoost/GradientBoosting have no native multiclass equivalent and
    therefore stay unweighted in this case.

    `calibration=True` (Phase 5.3, `config.models.calibration`): isotonic
    calibration + causal threshold search (`models/calibration.py`, not
    wired in until now) rather than a plain `argmax`. The threshold
    validation slice is the MOST RECENT 15% of the resampled train set (rows
    are already in chronological order at this stage) -- never the test set,
    consistent with the rest of the pipeline.

    `sample_weight`/`ind_matrix` (Phase 6.2, P6.2): uniqueness weights and
    observation x bar indicator matrix, computed on `X_tr`/`y_tr` BEFORE
    resampling. Applied only if `sampler_name=="none"` (`Xr` then stays
    unchanged X_tr, same row order/count -- SMOTE and the other oversamplers
    synthesize observations with no real span, an accepted limitation
    documented in `SamplingConfig`). For RandomForest: sequential bootstrap
    (`SequentialBootstrapRandomForestClassifier`) rather than sklearn's
    uniform bootstrap. For other algos that support it: `sample_weight`
    passed directly to `.fit()`. Combination with `calibration=True` not
    handled (out of scope for P6.2, documented limitation): the calibrated
    path stays unweighted even when weights are available."""
    apply_uniqueness = (uniqueness_weights_enabled and sampler_name == "none"
                         and sample_weight is not None)
    try:
        Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_tr, y_tr)
    except Exception:
        Xr, yr = X_tr, y_tr
    weight_applies = apply_uniqueness and len(Xr) == len(X_tr)
    clf = get_classifier(algo, seed=seed, **algo_overrides)

    n_val = max(int(len(Xr) * 0.15), 20)
    if calibration and n_val < len(Xr) - 20:
        X_fit, y_fit = Xr[:-n_val], yr[:-n_val]
        X_val, y_val = Xr[-n_val:], yr[-n_val:]
        cal_clf = calibrate_classifier(clf, X_fit, y_fit)
        threshold, _ = search_threshold(cal_clf, X_val, y_val)
        y_pred = predict_with_threshold(cal_clf, X_te, threshold)
        y_proba = cal_clf.predict_proba(X_te)
        classes = list(cal_clf.classes_)
        confidence = np.array([row[classes.index(p)] if p in classes else np.nan
                                for row, p in zip(y_proba, y_pred)])
    else:
        if weight_applies and algo == "RandomForest":
            clf = SequentialBootstrapRandomForestClassifier(seed=seed)
            clf.fit(Xr, yr, ind_matrix=ind_matrix, sample_weight=sample_weight)
        elif weight_applies:
            try:
                clf.fit(Xr, yr, sample_weight=sample_weight)
            except TypeError:
                clf.fit(Xr, yr)
        else:
            clf.fit(Xr, yr)
        y_pred = np.asarray(clf.predict(X_te)).ravel()
        y_proba = None
        confidence = None
        if hasattr(clf, "predict_proba"):
            try:
                y_proba = clf.predict_proba(X_te)
                confidence = y_proba[np.arange(len(y_pred)), y_pred.astype(int)]
            except Exception:
                y_proba = None
    met = metrics(y_te, y_pred, y_proba=y_proba)
    return met, y_pred, confidence


def _parse_params(raw_params) -> dict:
    if not raw_params:
        return {}
    if isinstance(raw_params, str):
        return ast.literal_eval(raw_params)
    return raw_params


def _walk_forward_span(all_dates: pd.DatetimeIndex, holdout_months: int, min_train_frac: float) -> int:
    """(Excluded) position where the walk-forward domain stops: the last
    `holdout_months` months of history are reserved (Phase 2.1), never seen
    by feature selection, tuning, or leaderboard ranking — only by a single
    final re-evaluation of the already-chosen config (`_evaluate_holdout`).
    Returns `len(all_dates)` (holdout disabled) if `holdout_months<=0` or if
    the history is too short to both train (`min_train_frac`) and keep a
    holdout of the requested length — the run continues without a holdout
    rather than crashing, with an explicit warning."""
    n = len(all_dates)
    if holdout_months <= 0 or n == 0:
        return n
    holdout_start_date = all_dates[-1] - pd.DateOffset(months=holdout_months)
    n_wf = int((all_dates < holdout_start_date).sum())
    if n_wf < max(int(n * min_train_frac) + 1, 100):
        print(f"  [WARN] history too short for a {holdout_months}-month holdout "
              f"on top of walk-forward training — holdout disabled for this run.")
        return n
    return n_wf


def _evaluate_holdout(conn, snapshot_id: str, pool_builder: "_FoldPoolBuilder", target_col: str,
                       feature_pool: list[str], config: RunConfig, all_dates_full: pd.DatetimeIndex,
                       n_wf: int, best_cfg: dict, seed: int) -> dict | None:
    """Re-evaluates the winning config (Phase 2.1) on the terminal holdout:
    the model is retrained ONLY on data prior to the holdout
    (`pool_builder.get(n_wf)` -> parametric fit on `raw.iloc[:n_wf]`, same
    causal mechanism as the walk-forward folds), then tested on the never-
    seen rows. A single config evaluated here — the one already chosen by
    the walk-forward scan — never used to choose among several (anti-pattern
    #1 of the original plan: never rank/select on the holdout)."""
    horizon = int(best_cfg["horizon"])
    regime = best_cfg["regime"]
    n_feat = int(best_cfg["N"])
    sampler_name, algo = best_cfg["sampler"], best_cfg["algo"]
    best_params = _parse_params(best_cfg.get("best_params"))

    pool = pool_builder.get(n_wf)
    target_series, reg_r, _thr = build_target(pool[target_col], horizon, n_wf, config.objective.flat_thr)
    idx = target_series.index
    holdout_start_date = all_dates_full[n_wf]
    tr_mask = np.asarray(idx < holdout_start_date)
    te_mask = np.asarray(idx >= holdout_start_date)
    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)
    tr_mask, te_mask = tr_mask & sel, te_mask & sel

    y_tr = target_series.values[tr_mask].astype(int)
    y_te = target_series.values[te_mask].astype(int)
    if len(y_tr) < config.validation.min_train_rows or len(y_te) < config.validation.min_test_rows:
        print(f"  [WARN] holdout excluded (h={horizon}d regime={regime}): "
              f"train={len(y_tr)} (min {config.validation.min_train_rows}), "
              f"test={len(y_te)} (min {config.validation.min_test_rows}).")
        return None

    X_pool_df = pool[feature_pool].reindex(idx)
    where = f"holdout (h={horizon}d regime={regime})"
    sc = RobustScaler()
    X_tr = _finite_scaled(
        sc.fit_transform(_finite_features(X_pool_df.values[tr_mask], f"{where} train")), where)
    X_te = _finite_scaled(
        sc.transform(_finite_features(X_pool_df.values[te_mask], f"{where} test")), where)
    cols = _select(conn, target_col, horizon, snapshot_id, config, X_tr, y_tr, n_feat, seed)
    met, y_pred, confidence = _fit_eval(X_tr[:, cols], y_tr, X_te[:, cols], y_te,
                                         sampler_name, algo, seed,
                                         calibration=config.models.calibration, **best_params)
    test_dates = [str(d.date()) for d in idx[te_mask]]
    return {"metrics": met, "y_pred": y_pred, "y_proba": confidence, "y_true": y_te,
            "test_dates": test_dates, "n_train": len(y_tr), "n_test": len(y_te)}


# Phase X5 -- kind exposed in config (validation.baseline_by_asset_class) ->
# internal key of `fd.baseline_predictions`/`fd.baselines` (`validation/baselines.py`).
_BASELINE_KIND_TO_KEY = {
    "persistence": "BASELINE_persistence",
    "majority": "BASELINE_majority",
    "majority_by_regime": "BASELINE_majority_by_regime",
    "har_rv": "BASELINE_har_rv",
    "momentum_20": "BASELINE_momentum_20",
    "momentum_5": "BASELINE_momentum_5",
    "random_walk_no_drift": "BASELINE_random_walk_no_drift",
    "random_walk_drift": "BASELINE_random_walk_drift",
}
# Fixed common reference (X5): allows comparing asset classes to each other
# on an equal footing, never configurable (unlike the class-specific
# baseline, see `baseline_by_asset_class`).
_COMMON_BASELINE_KEY = "BASELINE_persistence"


def _best_baseline_among(fd: "FoldData", candidate_keys: list[str]) -> tuple[str | None, np.ndarray | None]:
    """Among `candidate_keys` (`BASELINE_*` keys actually computed for this
    fold), keeps the one with the highest F1_dir -- same empirical selection
    logic as the historical behavior (a single "best on this fold"
    baseline), but restricted to the set relevant to the target's asset
    class rather than all baselines combined."""
    best_name, best_pred, best_f1 = None, None, -1.0
    for key in candidate_keys:
        pred = (fd.baseline_predictions or {}).get(key)
        if pred is None:
            continue
        f1 = (fd.baselines or {}).get(key, {}).get("F1_dir")
        if f1 is not None and f1 == f1 and f1 > best_f1:
            best_f1, best_name, best_pred = f1, key, pred
    return best_name, best_pred


def _evaluate_diebold_mariano(conn, snapshot_id: str, ctx: "_FoldContext", best_cfg: dict,
                               last_fold: int, seed: int) -> dict | None:
    """DM (Phase 2.5) between the winning config and TWO baselines (Phase
    X5), on the most recent walk-forward fold — the period closest to the
    current market regime, rather than an average over the whole history
    that would dilute a possible regime change:

    - `class_specific`: the best one (highest F1_dir on this fold) among the
      candidates configured for the target's asset class
      (`validation.baseline_by_asset_class`, see `classify_asset_class`);
    - `common`: class-agnostic persistence, ALWAYS computed in addition, as
      a fixed reference allowing asset classes to be compared to each other
      on an equal footing (never configurable).

    Returns `None` only if neither comparison could be computed (baselines
    unavailable on this fold, e.g. HAR-RV with too short a train) -- otherwise
    a dict with either key set to `None` depending on the case."""
    horizon, regime = int(best_cfg["horizon"]), best_cfg["regime"]
    n_feat, sampler_name, algo = int(best_cfg["N"]), best_cfg["sampler"], best_cfg["algo"]
    best_params = _parse_params(best_cfg.get("best_params"))

    fd = ctx.prepare(horizon, last_fold, regime, want_baselines=True)
    if fd is None or not fd.baseline_predictions:
        return None
    cols = _select(conn, ctx.target_col, horizon, snapshot_id, ctx.config, fd.X_tr, fd.y_tr, n_feat, seed)
    _, y_pred, _ = _fit_eval(fd.X_tr[:, cols], fd.y_tr, fd.X_te[:, cols], fd.y_te,
                              sampler_name, algo, seed,
                              calibration=ctx.config.models.calibration, **best_params)
    loss_model = (np.asarray(y_pred).ravel() != fd.y_te).astype(float)

    asset_class = classify_asset_class(ctx.config.objective.target_symbol,
                                        ctx.config.objective.target_source)
    candidate_kinds = ctx.config.validation.baseline_by_asset_class.get(asset_class, ["persistence"])
    candidate_keys = [_BASELINE_KIND_TO_KEY[k] for k in candidate_kinds if k in _BASELINE_KIND_TO_KEY]
    class_name, class_pred = _best_baseline_among(fd, candidate_keys)
    common_pred = (fd.baseline_predictions or {}).get(_COMMON_BASELINE_KEY)

    result: dict = {"asset_class": asset_class, "class_specific": None, "common": None}
    if class_pred is not None:
        loss_class = (np.asarray(class_pred).ravel() != fd.y_te).astype(float)
        dm_class = diebold_mariano(loss_model, loss_class, h=horizon)
        dm_class["baseline"] = class_name
        result["class_specific"] = dm_class
    if common_pred is not None:
        loss_common = (np.asarray(common_pred).ravel() != fd.y_te).astype(float)
        dm_common = diebold_mariano(loss_model, loss_common, h=horizon)
        dm_common["baseline"] = _COMMON_BASELINE_KEY
        result["common"] = dm_common

    if result["class_specific"] is None and result["common"] is None:
        return None
    return result


def _config_hash(config: RunConfig) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()[:16]


def _snapshot_context(raw: pd.DataFrame) -> tuple[str, str, int | None, int | None, str | None, list]:
    """Reads the snapshot context left by `ingest()` on `raw.attrs` (Phase
    1.6). As a fallback — `raw` comes from an `ingest` monkeypatched by a
    test, with no `.attrs` — computes an ad-hoc identifier from the content,
    so persistence stays functional/testable even without the real
    `ingest()`.

    `quality_issues` (Phase 6.5, P6.5): list of dicts (`[]` by default on a
    monkeypatched `ingest`, see `data/ingest.py::_attach_snapshot_context`)."""
    snapshot_id = raw.attrs.get("snapshot_id")
    data_hash = raw.attrs.get("data_hash")
    if not snapshot_id:
        data_hash = hashlib.sha256(
            pd.util.hash_pandas_object(raw, index=True).values.tobytes()).hexdigest()[:12]
        snapshot_id = f"adhoc__{data_hash}"
    return snapshot_id, data_hash or snapshot_id, raw.attrs.get("n_tickers"), \
        raw.attrs.get("n_fred_series"), raw.attrs.get("fred_source"), raw.attrs.get("quality_issues", [])


def _run_cpcv_scan(raw: pd.DataFrame, config: RunConfig, base_pool: pd.DataFrame, target_col: str,
                    conn, run_ids: dict[int, str], seed: int, snapshot_id: str
                    ) -> tuple[Leaderboard, dict, dict, pd.DataFrame, list[str], list[str]]:
    """Phase 6.1 (P6.1) -- CPCV scan, AS AN ALTERNATIVE to the walk-forward
    scan (`config.validation.scheme == "cpcv"`), never a replacement.

    Accepted, documented limitations (out of scope for P6.1, whose purpose
    is to make PBO satisfiable via more blocks -- not to close other
    channels):
    - Parametric features (EGARCH/Kalman/.../particle filter) are fit ONCE
      over the whole history (`fit_end_idx=None`, like the production
      model), not per combination -- re-fitting per combination would
      require a fit mechanism on a train SPLIT INTO NON-CONTIGUOUS SEGMENTS
      that `vol_models.py`/`spike.py` (designed for a simple `fit_end_idx`
      prefix) do not support today. Residual leak risk on THESE families
      only, in CPCV mode only.
    - No terminal holdout (Phase 2.1), no per-combination Optuna tuning, no
      Diebold-Mariano: these mechanisms rely on walk-forward's "single
      boundary, train=prefix" topology (`_FoldContext`/`ctx.prepare`), not
      directly transposable to the CPCV topology (train=complement of
      scattered groups) within this session's scope.
    - Purge and embargo are STRUCTURAL here (always applied at both
      boundaries of every test group, `validation/cpcv.py`), not governed by
      `validation.purge`/`embargo_enabled` (optional in walk-forward, where
      the measured effect was negligible on a SINGLE boundary) -- CPCV
      structurally exposes more boundaries, hence more potential leak
      surface to close by construction.

    Returns (board, trial_ids, n_trials_per_run, full_pool, feature_pool,
    interaction_formulas) -- the first three elements follow the same
    contract as the walk-forward scan (pluggable into the rest of
    `run_pipeline`: CSV export, `final_best`, etc.); the last three expose
    the full pool already built over the whole history (single fit, see
    limitation above) so that the final model-export block REUSES it as-is
    rather than rebuilding it a second time."""
    n_groups, k_test = config.validation.n_groups, config.validation.k_test_groups
    all_dates = raw.index
    n_bars = len(all_dates)
    groups = cpcv_module.build_groups(n_bars, n_groups)
    combos = cpcv_module.all_combinations(n_groups, k_test)
    paths = cpcv_module.path_assignment(n_groups, k_test)
    group_combo_to_path = {(g, ci): p for p, entries in paths.items() for g, ci in entries}
    group_of_date = np.empty(n_bars, dtype=int)
    for gi, (start, end) in enumerate(groups):
        group_of_date[start:end + 1] = gi
    group_of_date = pd.Series(group_of_date, index=all_dates)

    print(f"[CPCV] N={n_groups} groups, k={k_test} -> {len(combos)} combinations, "
          f"{len(paths)} reconstructed backtest paths.")

    param_pool = build_parametric_pool(raw, config, fit_end_idx=None, conn=conn, snapshot_id=snapshot_id)
    full_pool = pd.concat([base_pool, param_pool], axis=1)
    full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]

    interaction_formulas: list[str] = []
    if "interactions" in config.features.families:
        pilot_split_idx = groups[0][1] + 1
        interaction_formulas = _discover_interaction_formulas(full_pool, config, target_col, pilot_split_idx)
        print(f"  [INTERACTIONS] {len(interaction_formulas)} formulas discovered (pilot group).")
        inter = _apply_interaction_formulas(full_pool, interaction_formulas)
        full_pool = pd.concat([full_pool, inter], axis=1)

    feature_pool = [c for c in full_pool.columns if c != target_col]

    board = Leaderboard()
    trial_ids: dict[tuple, int] = {}
    n_trials_per_run: dict[str, int] = {h: 0 for h in run_ids.values()}

    for horizon in config.objective.horizons:
        run_id = run_ids[horizon]
        target_series, reg_r, _thr = build_target(full_pool[target_col], horizon,
                                                    groups[0][1] + 1, config.objective.flat_thr)
        idx = target_series.index
        date_group = group_of_date.reindex(idx)
        reg_al = reg_r.reindex(idx).fillna("NORMAL").values
        X_pool_df = full_pool[feature_pool].reindex(idx)
        X_all = _finite_features(X_pool_df.values, f"CPCV (h={horizon}d)")
        y_all = target_series.values.astype(int)

        for regime in config.objective.regimes:
            regime_sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)

            for n_feat in config.selection.n_features_grid:
                for sampler_name in config.sampler.candidates:
                    for algo in config.models.algos:
                        path_buf = {p: {"dates": [], "y_true": [], "y_pred": [], "y_proba": []}
                                    for p in paths}

                        for ci, combo in enumerate(combos):
                            split = cpcv_module.build_split(groups, combo, horizon,
                                                             embargo_bars=config.validation.embargo_bars)
                            train_dates = set(all_dates[split.train_mask])
                            test_dates = set(all_dates[split.test_mask])
                            tr_mask = np.asarray([d in train_dates for d in idx]) & regime_sel
                            te_mask = np.asarray([d in test_dates for d in idx]) & regime_sel

                            y_tr, y_te = y_all[tr_mask], y_all[te_mask]
                            if (len(y_tr) < config.validation.min_train_rows
                                    or len(y_te) < config.validation.min_test_rows):
                                print(f"  [WARN] CPCV combo {combo} excluded (h={horizon}d regime={regime}): "
                                      f"train={len(y_tr)} (min {config.validation.min_train_rows}), "
                                      f"test={len(y_te)} (min {config.validation.min_test_rows}).")
                                continue

                            where = f"CPCV combo {combo} (h={horizon}d regime={regime})"
                            sc = RobustScaler()
                            X_tr_full = _finite_scaled(sc.fit_transform(X_all[tr_mask]), where)
                            X_te_full = _finite_scaled(sc.transform(X_all[te_mask]), where)
                            cols = _select(conn, target_col, horizon, snapshot_id,
                                           config, X_tr_full, y_tr, n_feat, seed)
                            X_tr_n, X_te_n = X_tr_full[:, cols], X_te_full[:, cols]

                            met, y_pred, confidence = _fit_eval(
                                X_tr_n, y_tr, X_te_n, y_te, sampler_name, algo, seed,
                                calibration=config.models.calibration,
                                uniqueness_weights_enabled=False)  # P6.2: spans undefined on scattered train

                            test_idx_dates = idx[te_mask]
                            test_groups_of_rows = date_group.reindex(test_idx_dates).values
                            for gi in combo:
                                row_sel = test_groups_of_rows == gi
                                if not row_sel.any():
                                    continue
                                p = group_combo_to_path.get((gi, ci))
                                if p is None:
                                    continue
                                buf = path_buf[p]
                                buf["dates"].extend(str(d.date()) for d in test_idx_dates[row_sel])
                                buf["y_true"].extend(y_te[row_sel].tolist())
                                buf["y_pred"].extend(np.asarray(y_pred)[row_sel].tolist())
                                buf["y_proba"].extend(
                                    (confidence[row_sel].tolist() if confidence is not None
                                     else [None] * int(row_sel.sum())))

                            trial_key = (horizon, regime, n_feat, sampler_name, algo)
                            if trial_key not in trial_ids:
                                trial_ids[trial_key] = trackdb.create_trial(
                                    conn, run_id, regime, algo, sampler_name, n_feat,
                                    selector=config.selection.method)
                                n_trials_per_run[run_id] += 1
                            trial_id = trial_ids[trial_key]
                            trackdb.add_fold_metrics(conn, trial_id, fold_index=ci, split="test", metrics=met)

                        # Path reassembly (P6.1): one prediction row per path,
                        # performance metric PER PATH -- never a single point.
                        path_metric_values: dict[int, float] = {}
                        trial_id = trial_ids.get((horizon, regime, n_feat, sampler_name, algo))
                        for p, buf in path_buf.items():
                            if not buf["dates"] or trial_id is None:
                                continue
                            trackdb.add_predictions(
                                conn, trial_id, fold_index=p, split="test",
                                ts=buf["dates"], y_true=buf["y_true"], y_pred=buf["y_pred"],
                                y_proba=buf["y_proba"] if any(v is not None for v in buf["y_proba"]) else None,
                                path_id=p,
                            )
                            path_met = metrics(np.array(buf["y_true"]), np.array(buf["y_pred"]))
                            path_metric_values[p] = path_met.get("F1_dir", float("nan"))
                            # `split="test_path"` (never "test", already used per-combination
                            # above): allows `stats.pbo_for_target_cpcv` to rebuild a
                            # (trial x path) matrix without mixing with the per-combination
                            # metrics -- same mechanism as `pbo_for_target` (walk-forward),
                            # just a different `split`/`fold_index` (path, not fold).
                            trackdb.add_fold_metrics(conn, trial_id, fold_index=p,
                                                      split="test_path", metrics=path_met)

                        dist = cpcv_module.path_performance_distribution(path_metric_values)
                        board.add(horizon=horizon, regime=regime, N=n_feat, sampler=sampler_name, algo=algo,
                                  scheme="cpcv", n_paths=dist["n_paths"],
                                  F1_dir_median=dist["median"], F1_dir_q05=dist["q05"],
                                  F1_dir_q95=dist["q95"], F1_dir_std=dist["std"],
                                  # `F1_dir` (median) feeds the leaderboard's existing sort
                                  # (`board.best(metric="F1_dir")`) without duplicating this logic.
                                  F1_dir=dist["median"])

    return board, trial_ids, n_trials_per_run, full_pool, feature_pool, interaction_formulas


def run_pipeline(config: RunConfig, store: DataStore | None = None,
                  force_ingest: bool = False, db_path: str | None = None,
                  job_id: str | None = None) -> dict:
    store = store or DataStore()
    seed = config.output.seed
    t0 = time.time()

    # Phase timing (migration 0016): ingestion runs before any run_id
    # exists (trackdb.create_run() below is the first point one does),
    # so its start/end are captured here and written once run_ids are
    # known -- same duplication run.started_at itself already has across
    # a batch's horizons, see record_phase_timing()'s docstring.
    t_ingest_start = time.time()
    raw = ingest(config.objective, config.universe, store, force=force_ingest,
                 data_quality=config.data_quality)
    t_ingest_end = time.time()
    target_col = clean_symbol(config.objective.target_symbol)

    conn = trackdb.connect(db_path)
    snapshot_id, data_hash, n_tickers, n_fred_series, fred_src, quality_issues = _snapshot_context(raw)
    trackdb.upsert_snapshot(conn, snapshot_id, data_hash, n_tickers, n_fred_series, fred_src)
    trackdb.add_data_quality_issues(conn, snapshot_id, quality_issues)
    config_json = config.model_dump_json()
    config_hash = _config_hash(config)
    git_sha = trackdb.current_git_sha()

    run_ids: dict[int, str] = {}
    for horizon in config.objective.horizons:
        run_id = f"{config.name}_h{horizon}_{uuid.uuid4().hex[:8]}"
        trackdb.create_run(conn, run_id, target=config.objective.target_symbol, horizon=horizon,
                            snapshot_id=snapshot_id, config_json=config_json,
                            config_hash=config_hash, git_sha=git_sha, seed=seed, job_id=job_id)
        run_ids[horizon] = run_id

    for _run_id in run_ids.values():
        trackdb.record_phase_timing(conn, _run_id, "ingestion", t_ingest_start, t_ingest_end)

    all_dates_full = raw.index
    # Phase timing: base pool is shared by all folds/horizons, built once --
    # in walk-forward, only the FIRST fold's full pool (base+parametric+
    # interactions, built just below via pool_builder.get(fold_cuts[0]))
    # is cleanly attributable here; later folds' pools are built lazily
    # from inside the scan loop and land in the "scan" phase instead (see
    # migration 0016's "known limitation"). CPCV builds its pool entirely
    # inside _run_cpcv_scan(), entangled with its own scan loop -- not
    # separately timed here, see that branch below.
    t_pool_start = time.time()
    print("[FEATURES] building the base pool (causal, shared by all folds)...")
    base_pool = build_base_feature_pool(raw, config, target_col)
    print(f"[FEATURES] base pool: {base_pool.shape[1]} columns ({time.time()-t0:.1f}s)")
    assert (base_pool.index == all_dates_full).all(), "feature construction must not change the date index"

    baseline_rows: list[dict] = []
    baseline_accum: dict[tuple[str, str], list[dict]] = {}
    tuned_rows: list[dict] = []
    tuned_trial_ids: dict[tuple, int] = {}

    # Phase 6.1 (P6.1) -- CPCV as an ALTERNATIVE to walk-forward
    # (`validation.scheme`), never a replacement: the walk-forward branch
    # below is BIT-IDENTICAL to the pre-P6.1 behavior.
    cpcv_full_pool = None
    cpcv_interaction_formulas = None
    if config.validation.scheme == "cpcv":
        # Phase timing: _run_cpcv_scan() builds its pool AND runs its scan
        # loop internally, entangled (unlike walk-forward, where the first
        # fold's pool build is cleanly separable) -- not split further here
        # to avoid restructuring that function; recorded as "scan" only,
        # no "pool_construction" row for CPCV runs (see migration 0016).
        t_scan_start = time.time()
        board, trial_ids, n_trials_per_run, cpcv_full_pool, feature_pool, cpcv_interaction_formulas = (
            _run_cpcv_scan(raw, config, base_pool, target_col, conn, run_ids, seed, snapshot_id))
        t_scan_end = time.time()
        for _run_id in run_ids.values():
            trackdb.record_phase_timing(conn, _run_id, "scan", t_scan_start, t_scan_end)
        pool_builder = None
        ctx = None
        all_dates = all_dates_full
        n_wf = len(all_dates_full)  # CPCV: no terminal holdout (accepted limitation, see _run_cpcv_scan)
        last_fold = None
    else:
        n_wf = _walk_forward_span(all_dates_full, config.validation.holdout_months,
                                   config.validation.min_train_frac)
        all_dates = all_dates_full[:n_wf]
        fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds,
                                     config.validation.min_train_frac)
        describe_folds(all_dates, fold_cuts)
        if n_wf < len(all_dates_full):
            print(f"[HOLDOUT] {len(all_dates_full) - n_wf} rows reserved "
                  f"({all_dates_full[n_wf].date()} -> {all_dates_full[-1].date()}), "
                  "never seen by selection/tuning.")

        pool_builder = _FoldPoolBuilder(raw, config, target_col, base_pool, fold_cuts,
                                         conn=conn, snapshot_id=snapshot_id)
        feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
        t_pool_end = time.time()
        for _run_id in run_ids.values():
            trackdb.record_phase_timing(conn, _run_id, "pool_construction", t_pool_start, t_pool_end)
        print(f"[FEATURES] full pool (fold 1, base+parametric+interactions): {len(feature_pool)} columns")
        ctx = _FoldContext(pool_builder, target_col, feature_pool, config, all_dates, fold_cuts)

        board = Leaderboard()
        trial_ids: dict[tuple, int] = {}
        n_trials_per_run: dict[str, int] = {h: 0 for h in run_ids.values()}
        last_fold = config.validation.n_wf_folds - 1

        for horizon in config.objective.horizons:
            run_id = run_ids[horizon]
            t_scan_start = time.time()
            for k in range(config.validation.n_wf_folds):
                for regime in config.objective.regimes:
                    fd = ctx.prepare(horizon, k, regime, want_baselines=True)
                    if fd is None:
                        continue

                    for baseline_name, base_met in (fd.baselines or {}).items():
                        baseline_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                               "N": None, "sampler": None, "algo": baseline_name,
                                               "features": "", "n_train": len(fd.y_tr), "n_test": len(fd.y_te),
                                               "test_start": fd.test_start, "test_end": fd.test_end, **base_met})
                        baseline_accum.setdefault((run_id, baseline_name), []).append(base_met)

                    for n_feat in config.selection.n_features_grid:
                        cols = _select(conn, target_col, horizon, snapshot_id,
                                       config, fd.X_tr, fd.y_tr, n_feat, seed)
                        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
                        feat_names = [feature_pool[c] for c in cols]

                        for sampler_name in config.sampler.candidates:
                            for algo in config.models.algos:
                                met, y_pred, confidence = _fit_eval(
                                    X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed,
                                    calibration=config.models.calibration,
                                    sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                                    uniqueness_weights_enabled=config.sampling.uniqueness_weights)
                                board.add(horizon=horizon, fold=k + 1, regime=regime, N=n_feat,
                                          sampler=sampler_name, algo=algo,
                                          features="|".join(feat_names),
                                          n_train=len(fd.y_tr), n_test=len(fd.y_te),
                                          # Phase 6.2 (P6.2): effective sample size (sum of
                                          # uniquenesses) alongside n_train -- always computed.
                                          effective_n_train=fd.effective_n,
                                          test_start=fd.test_start, test_end=fd.test_end, **met)

                                trial_key = (horizon, regime, n_feat, sampler_name, algo)
                                if trial_key not in trial_ids:
                                    trial_ids[trial_key] = trackdb.create_trial(
                                        conn, run_id, regime, algo, sampler_name, n_feat,
                                        selector=config.selection.method)
                                    n_trials_per_run[run_id] += 1
                                trial_id = trial_ids[trial_key]
                                # Phase 6.2 (P6.2): n_eff stored as one more "metric" (generic
                                # trial/fold_index/split/metric/value schema, no dedicated
                                # column) -- read by the HTML report alongside F1_dir/etc.
                                met_with_n = dict(met)
                                met_with_n["n_train"] = float(len(fd.y_tr))
                                if fd.effective_n is not None:
                                    met_with_n["effective_n_train"] = fd.effective_n
                                trackdb.add_fold_metrics(conn, trial_id, fold_index=k + 1,
                                                          split="test", metrics=met_with_n)
                                trackdb.add_predictions(conn, trial_id, fold_index=k + 1, split="test",
                                                         ts=fd.test_dates, y_true=fd.y_te,
                                                         y_pred=y_pred, y_proba=confidence)

                print(f"  h={horizon:2d}d fold{k+1}: {len(board.rows)} cumulative rows "
                      f"[{time.time()-t0:.0f}s]")
            t_scan_end = time.time()
            trackdb.record_phase_timing(conn, run_id, "scan", t_scan_start, t_scan_end)

    print(f"\n[SCAN] {len(board.rows)} evaluations in {(time.time()-t0)/60:.1f}min")
    best = board.best(metric="F1_dir")
    if best:
        print(f"[BEST before Optuna] h={best['horizon']}d {best['regime']} N={best['N']} "
              f"{best['sampler']} {best['algo']} -> F1_dir={best['F1_dir']}")

    # Phase 6.3 (P6.3) -- feature selection stability, PER HORIZON (each
    # run_id is scoped to one horizon, see Phase 1.2 schema): for the
    # locally winning (regime, N) config of THIS horizon (F1_dir averaged
    # over its folds, independent of the global `final_best` choice below,
    # which keeps only ONE horizon), stability measured on the features
    # actually retained per fold (already captured in `board.rows[...]
    # ["features"]`, no re-selection). sampler/algo do not influence
    # selection (done before their loop): deduplicate them before Jaccard.
    # Not computed in CPCV mode (features selected per combination are not
    # captured in `board.rows` in the same shape -- accepted limitation,
    # out of scope for P6.1).
    if config.selection.track_stability and config.validation.scheme == "walkforward":
        for horizon in config.objective.horizons:
            board_h = Leaderboard()
            board_h.rows = [r for r in board.rows if r.get("horizon") == horizon and r.get("N") is not None]
            top_h = board_h.top_k(1, metric="F1_dir")
            if not top_h:
                continue
            winner = top_h[0]
            fold_feature_sets: dict[int, list[str]] = {}
            for r in board_h.rows:
                if r["regime"] == winner["regime"] and r["N"] == winner["N"]:
                    fold_feature_sets.setdefault(r["fold"], r["features"].split("|") if r["features"] else [])
            stability = feature_selection_stability(fold_feature_sets)
            trackdb.save_feature_stability(conn, run_ids[horizon], stability["mean_jaccard"],
                                            stability["n_folds"], stability["selection_freq"])
            if stability["warning"]:
                print(f"  [STABILITY] h={horizon}d: {stability['warning']}")

    # Audit report, C4 -- holdout diagnostic of the WHOLE SCAN grid (not just
    # the final winner), written to `holdout_diagnostic` (a table separate
    # from `fold_metric`, never read by selection/tuning): allows an
    # after-the-fact test/holdout rank correlation, without ever influencing
    # the winning config's choice. Not applicable in CPCV mode (no terminal
    # holdout, see _run_cpcv_scan).
    if config.validation.scheme == "walkforward" and n_wf < len(all_dates_full) and trial_ids:
        print(f"[HOLDOUT DIAGNOSTIC] evaluating {len(trial_ids)} trials on the holdout "
              "(read-only, chooses nothing)...")
        for (h, regime, n_feat, sampler_name, algo), tid in trial_ids.items():
            diag_cfg = {"horizon": h, "regime": regime, "N": n_feat,
                        "sampler": sampler_name, "algo": algo, "best_params": {}}
            diag_eval = _evaluate_holdout(conn, snapshot_id, pool_builder, target_col, feature_pool,
                                           config, all_dates_full, n_wf, diag_cfg, seed)
            if diag_eval is not None:
                trackholdout.write_holdout_diagnostic(conn, tid, diag_eval["metrics"])

    # Optuna tuning: walk-forward only (relies on `ctx.prepare`,
    # "train=prefix" topology -- not directly transposable to CPCV within
    # this scope, see _run_cpcv_scan).
    if config.validation.scheme == "walkforward" and config.tuning.enabled and len(board.rows):
        if config.tuning.optuna_select_top_k_per_horizon:
            # Audit report, C3: top_k selection PER horizon (not global) --
            # otherwise a horizon whose best SCAN trial dominates can capture
            # 100% of the Optuna budget, leaving other horizons zero trials.
            top_configs = []
            for horizon in config.objective.horizons:
                board_h = Leaderboard()
                board_h.rows = [r for r in board.rows if r.get("horizon") == horizon]
                top_configs.extend(board_h.top_k(config.tuning.top_k, metric="F1_dir"))
        else:
            top_configs = board.top_k(config.tuning.top_k, metric="F1_dir")
        print(f"\n[OPTUNA] tuning the {len(top_configs)} best configs "
              f"({config.tuning.n_trials} trials, CV={config.tuning.cv_splits}, "
              f"per_horizon={config.tuning.optuna_select_top_k_per_horizon})...")
        # Phase 3.2 (`patrick resume`): Optuna study persisted in a dedicated
        # SQLite file (never `patrick.db`), a deterministic `study_name` per
        # tested config -> a `patrick run`/`patrick resume` relaunched on the
        # same config (same config_hash, hence same study name) after an
        # interruption resumes the trials already done instead of starting
        # from zero (see `tune_config`, `optuna_runner.py`).
        os.makedirs(config.output.dir, exist_ok=True)
        optuna_storage_path = os.path.join(config.output.dir, "optuna.db")
        for cfg in top_configs:
            horizon, regime, n_feat = int(cfg["horizon"]), cfg["regime"], int(cfg["N"])
            sampler_name, algo = cfg["sampler"], cfg["algo"]
            run_id = run_ids[horizon]

            fd = ctx.prepare(horizon, last_fold, regime)
            if fd is None:
                continue
            if len(fd.y_tr) < config.validation.min_train_rows * 2:
                continue
            # Phase timing: one row per top-config (tune_config() itself,
            # here scoped to include the immediately-following per-fold
            # refit+write below -- both are unavoidable cost of tuning this
            # one config, not a separate concern). A run_id can legitimately
            # get more than one "tuning" row (see migration 0016).
            t_tune_start = time.time()
            cols = _select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, seed)
            X_tr_n = fd.X_tr[:, cols]

            study_name = f"{config.name}_{config_hash}_h{horizon}_{regime}_N{n_feat}_{sampler_name}_{algo}"
            best_params, best_cv = tune_config(X_tr_n, fd.y_tr, algo, sampler_name,
                                                n_trials=config.tuning.n_trials,
                                                cv_splits=config.tuning.cv_splits, seed=seed,
                                                storage_path=optuna_storage_path, study_name=study_name)
            print(f"  h={horizon}d {regime} N={n_feat} {sampler_name} {algo}: "
                  f"cv_F1_dir={best_cv:.4f} params={best_params}")

            tuned_key = (horizon, regime, n_feat, sampler_name, algo, json.dumps(best_params, sort_keys=True))
            tuned_trial_ids[tuned_key] = trackdb.create_trial(
                conn, run_id, regime, algo, sampler_name, n_feat,
                selector=config.selection.method, params_json=json.dumps(best_params))
            n_trials_per_run[run_id] += 1
            tuned_trial_id = tuned_trial_ids[tuned_key]

            for k in range(config.validation.n_wf_folds):
                fd = ctx.prepare(horizon, k, regime)
                if fd is None:
                    continue
                cols = _select(conn, target_col, horizon, snapshot_id,
                               config, fd.X_tr, fd.y_tr, n_feat, seed)
                X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
                met, y_pred, confidence = _fit_eval(
                    X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed,
                    calibration=config.models.calibration,
                    sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                    uniqueness_weights_enabled=config.sampling.uniqueness_weights, **best_params)
                tuned_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                    "N": n_feat, "sampler": sampler_name, "algo": algo,
                                    "best_params": str(best_params), "effective_n_train": fd.effective_n,
                                    "test_start": fd.test_start, "test_end": fd.test_end, **met})
                trackdb.add_fold_metrics(conn, tuned_trial_id, fold_index=k + 1, split="test", metrics=met)
                trackdb.add_predictions(conn, tuned_trial_id, fold_index=k + 1, split="test",
                                         ts=fd.test_dates, y_true=fd.y_te, y_pred=y_pred, y_proba=confidence)
            t_tune_end = time.time()
            trackdb.record_phase_timing(conn, run_id, "tuning", t_tune_start, t_tune_end)

    tuned_df = pd.DataFrame(tuned_rows)
    if baseline_rows:
        board.rows.extend(baseline_rows)
    csv_path = board.export(config.output.dir, config.name)
    if len(tuned_df):
        os.makedirs(config.output.dir, exist_ok=True)
        tuned_path = os.path.join(config.output.dir, f"{config.name}_tuned.csv")
        tuned_df.to_csv(tuned_path, index=False)
        print(f"[EXPORT] {tuned_path}")
    print(f"[EXPORT] {csv_path}")

    # baseline_metric has no fold_index column (Phase 1.2 schema): aggregated
    # (averaged) per run rather than written per fold — see phase report.
    for (run_id, baseline_name), fold_dicts in baseline_accum.items():
        agg = {}
        for m in {k for d in fold_dicts for k in d}:
            values = [v for v in (d.get(m) for d in fold_dicts) if v is not None and v == v]
            if values:
                agg[m] = float(np.mean(values))
        trackdb.add_baseline_metrics(conn, run_id, baseline_name, split="test", metrics=agg)

    final_best = dict(best) if best else None
    if len(tuned_df):
        group_cols = ["horizon", "regime", "N", "sampler", "algo"]
        tuned_agg = (tuned_df.groupby(group_cols + ["best_params"])["F1_dir"]
                     .mean().reset_index().sort_values("F1_dir", ascending=False))
        if len(tuned_agg) and (final_best is None or tuned_agg.iloc[0]["F1_dir"] > final_best["F1_dir"]):
            final_best = tuned_agg.iloc[0].to_dict()

    model_path = None
    holdout_result = None
    dm_result = None
    pbo_result = None
    cumulative_trials = 0
    holdout_diagnostic_result = None
    if final_best is not None:
        # CPCV (P6.1): `_run_cpcv_scan` already built this full pool (single
        # fit over the whole history, same interaction formulas) -- reused
        # as-is rather than rebuilt a second time.
        if config.validation.scheme == "cpcv":
            full_pool = cpcv_full_pool
            interaction_formulas = cpcv_interaction_formulas
        else:
            full_pool = pd.concat(
                [base_pool, build_parametric_pool(raw, config, fit_end_idx=None,
                                                   conn=conn, snapshot_id=snapshot_id)], axis=1)
            full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
            interaction_formulas = pool_builder.interaction_formulas
            if interaction_formulas:
                full_inter = _apply_interaction_formulas(full_pool, interaction_formulas)
                full_pool = pd.concat([full_pool, full_inter], axis=1)
        model_path = export_best_model(full_pool, target_col, feature_pool, config,
                                        final_best, config.output.dir, seed=seed,
                                        interaction_formulas=interaction_formulas)

        best_key = (int(final_best["horizon"]), final_best["regime"], int(final_best["N"]),
                    final_best["sampler"], final_best["algo"])
        best_trial_id = trial_ids.get(best_key)
        if best_trial_id is None and "best_params" in final_best:
            parsed_params = _parse_params(final_best["best_params"])
            tuned_key = best_key + (json.dumps(parsed_params, sort_keys=True),)
            best_trial_id = tuned_trial_ids.get(tuned_key)
        if best_trial_id is not None:
            trackdb.mark_best_trial(conn, best_trial_id, artifact_path=model_path)

        # Phase 2.1 — terminal holdout: a single re-evaluation of the already-
        # chosen config, never used to choose among several (see
        # _evaluate_holdout docstring).
        if n_wf < len(all_dates_full):
            holdout_eval = _evaluate_holdout(conn, snapshot_id, pool_builder, target_col, feature_pool,
                                              config, all_dates_full, n_wf, final_best, seed)
            if holdout_eval is not None:
                holdout_result = holdout_eval["metrics"]
                if best_trial_id is not None:
                    trackdb.add_fold_metrics(conn, best_trial_id, fold_index=0, split="holdout",
                                              metrics=holdout_result)
                    trackdb.add_predictions(conn, best_trial_id, fold_index=0, split="holdout",
                                             ts=holdout_eval["test_dates"], y_true=holdout_eval["y_true"],
                                             y_pred=holdout_eval["y_pred"], y_proba=holdout_eval["y_proba"])

        # Phase 2.5 — Diebold-Mariano vs. best baseline (last walk-forward fold).
        # Relies on `ctx.prepare` (train=prefix topology): not applicable in
        # CPCV (`ctx is None`), see limitations documented in `_run_cpcv_scan`.
        if config.validation.scheme == "walkforward":
            dm_result = _evaluate_diebold_mariano(conn, snapshot_id, ctx, final_best, last_fold, seed)
            if dm_result is not None:
                # Phase 6.4 (P6.4): persisted in a dedicated table (dm_result,
                # migration 0009), not just in job.result_json -- queryable
                # across the whole run history (including CLI, with no
                # associated web job), needed by `trackstats.fdr_across_targets`.
                # Phase X5: two rows per run (kind), class-specific AND common
                # (persistence).
                run_id_for_horizon = run_ids[int(final_best["horizon"])]
                if dm_result.get("class_specific") is not None:
                    trackdb.save_dm_result(conn, run_id_for_horizon, dm_result["class_specific"],
                                            kind="class_specific")
                if dm_result.get("common") is not None:
                    trackdb.save_dm_result(conn, run_id_for_horizon, dm_result["common"],
                                            kind="common")

        # Phase 2.2 — cumulative trials on this target/horizon, across the whole
        # run history (not just this run). Phase 2.4 — PBO on this same history
        # (P6.1: wired to CPCV paths rather than walk-forward blocks when this
        # scheme is active, see `stats.pbo_for_target_cpcv`).
        cumulative_trials = trackstats.count_cumulative_trials(
            conn, config.objective.target_symbol, int(final_best["horizon"]))
        if config.validation.scheme == "cpcv":
            pbo_result = trackstats.pbo_for_target_cpcv(
                conn, config.objective.target_symbol, int(final_best["horizon"]), final_best["regime"])
        else:
            pbo_result = trackstats.pbo_for_target(
                conn, config.objective.target_symbol, int(final_best["horizon"]), final_best["regime"])

        # Audit report, C4 -- diagnostic (READ ONLY, see holdout_diagnostic.py):
        # does the selection procedure generalize from test to holdout? Never
        # influences final_best, computed after the fact only. Not applicable
        # in CPCV (no terminal holdout, see `_run_cpcv_scan`).
        if config.validation.scheme == "walkforward":
            holdout_diagnostic_result = trackholdout.spearman_test_vs_holdout(
                conn, run_ids[int(final_best["horizon"])], metric="F1_dir")

    for run_id in run_ids.values():
        trackdb.finish_run(conn, run_id, status="done", n_trials=n_trials_per_run[run_id])
    conn.close()

    return {
        "leaderboard": board.as_df(),
        "tuned": tuned_df,
        "best_before_tuning": best,
        "final_best": final_best,
        "model_path": model_path,
        "elapsed_s": time.time() - t0,
        "holdout": holdout_result,
        "diebold_mariano": dm_result,
        "cumulative_trials": cumulative_trials,
        "pbo": pbo_result,
        "holdout_diagnostic": holdout_diagnostic_result,
    }
