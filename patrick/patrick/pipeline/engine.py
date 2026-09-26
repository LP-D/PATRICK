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
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.session_calendar import classify_asset_class
from patrick.data.sources.yfinance_source import clean_symbol, download_ohlc
from patrick.data.store import DataStore
from patrick.features import (
    equity_fundamentals,
    guida,
    pool_cache,
    spike,
    technical,
    vol_models,
)
from patrick.features import macro as feat_macro
from patrick.features.interactions import (
    INTERACTION_TYPES,
    apply_interaction,
    discover_interactions,
)
from patrick.features.sanitize import finite_features, finite_scaled
from patrick.features.target import build_target
from patrick.models import calibration as calibration_lib
from patrick.models.registry import get_classifier
from patrick.models.sequential_forest import SequentialBootstrapRandomForestClassifier
from patrick.models.uniqueness import (
    average_uniqueness,
    build_indicator_matrix,
    effective_sample_size,
)
from patrick.numeric import is_nan
from patrick.pipeline.leaderboard import Leaderboard, rank_configs
from patrick.selection._common import RANKING_VERSION
from patrick.selection.registry import select_features
from patrick.selection.stability import feature_selection_stability
from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import phase_timing_log
from patrick.tracking import stats as trackstats
from patrick.tracking.export import export_best_model
from patrick.tuning.optuna_runner import (
    InnerCVInfeasible,
    safe_resample,
    study_name_for,
    tune_config,
)
from patrick.validation import cpcv as cpcv_module
from patrick.validation.baselines import compute_baselines
from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.embargo import embargo_mask
from patrick.validation.metrics import metrics
from patrick.validation.purge import purge_mask
from patrick.validation.walkforward import build_fold_cuts, describe_folds

logger = logging.getLogger(__name__)


_finite_features = finite_features
_finite_scaled = finite_scaled


def _sanitize_lookback_windows(windows: list[int], min_allowed: int, label: str) -> list[int]:
    """Phase 3 (feature/hyperparams-lookbacks) -- defensive floor applied
    right before `features/technical.py` is called, protecting the YAML/CLI
    path (`RunConfig` has no pydantic-level bounds, see
    `config/schema.py::TechnicalLookbacksConfig` docstring) the same way
    `webapp/forms.py::_parse_technical_lookbacks` already protects the
    web-form path. `min_allowed=1` (returns/zscore/ma_ratio/rolling_vol): a
    window<=0 either crashes (`rolling(w<0)`, pandas ValueError) or, worse,
    passes SILENTLY for `returns()` specifically -- `safe_pct_change(series,
    w<0)` never raises; pandas' `Series.pct_change(periods=negative)` shifts
    the OTHER direction and silently returns a forward-looking (look-ahead
    leak) value instead (measured, see tests/test_technical_lookbacks.py).
    `min_allowed=2` (ohlc_vol_windows): `yang_zhang_vol` divides by
    `(window - 1)`, so window=1 raises ZeroDivisionError deep in the
    pipeline. Same discipline as `_finite_features` above: invalid entries
    are dropped and reported, never silently kept, and never allowed to
    crash the whole run over one bad configured value."""
    kept = [w for w in windows if isinstance(w, int) and not isinstance(w, bool) and w >= min_allowed]
    dropped = [w for w in windows if w not in kept]
    if dropped:
        print(f"  [WARN] {label}: invalid lookback window(s) {dropped} ignored "
              f"(must be an integer >= {min_allowed}) — computed with {kept or 'no window'}.")
    return kept


def _features_payload(config: RunConfig) -> dict:
    return {"features": config.features.model_dump(mode="json"),
            "fred": sorted(config.universe.fred_series), "target": config.objective.target_symbol}


def build_base_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str) -> pd.DataFrame:
    """Features causal by construction (rolling windows/lags, no globally
    estimated parameter): technical, spike (excluding the particle filter),
    macro, + the target's OHLC vol estimators. Computed once, shared across
    all folds/horizons of a run — no leak risk (see module docstring).

    Cached on disk per (raw content, feature config, feature code) --
    `features/pool_cache.py`. The target's OHLC is fetched at build time
    (not part of the snapshot): the cached pool freezes it per vintage."""
    return pool_cache.cached("base", raw, {**_features_payload(config), "target_col": target_col},
                             lambda: _build_base_feature_pool(raw, config, target_col))


def _build_base_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str) -> pd.DataFrame:
    families = config.features.families
    guida_on = config.features.enable_guida_features
    guida_windows = list(D.GUIDA_LOOKBACKS) if guida_on else None
    parts: list[pd.DataFrame] = [raw]

    # Phase 3 (feature/hyperparams-lookbacks): sanitized once, outside the
    # per-column loop below (`_sanitize_lookback_windows` is pure/cheap, but
    # there is no reason to repeat the same filtering + [WARN] print once
    # per raw column).
    lb = config.features.technical_lookbacks
    returns_windows = _sanitize_lookback_windows(lb.returns_windows, 1, "returns_windows")
    zscore_windows = _sanitize_lookback_windows(lb.zscore_windows, 1, "zscore_windows")
    ma_ratio_windows = _sanitize_lookback_windows(lb.ma_ratio_windows, 1, "ma_ratio_windows")
    rolling_vol_windows = _sanitize_lookback_windows(lb.rolling_vol_windows, 1, "rolling_vol_windows")
    ohlc_vol_windows = _sanitize_lookback_windows(lb.ohlc_vol_windows, 2, "ohlc_vol_windows")

    for col in raw.columns:
        s = raw[col]
        if "technical" in families:
            parts.append(technical.build_technical_features(
                s, prefix=col, guida_windows=guida_windows,
                returns_windows=returns_windows, zscore_windows=zscore_windows,
                ma_ratio_windows=ma_ratio_windows, rolling_vol_windows=rolling_vol_windows))
        if "spike" in families:
            parts.append(spike.build_spike_features_base(s, prefix=col, guida_windows=guida_windows))
        if "vol_models" in families:
            parts.append(vol_models.build_vol_model_features_base(
                s, prefix=col, models=config.features.vol_models, guida_windows=guida_windows))

    if "macro" in families and config.universe.fred_series:
        macro_cols = list(config.universe.fred_series.keys())
        parts.append(feat_macro.build_macro_features(raw, macro_cols, guida_windows=guida_windows))

    if guida_on:
        parts.append(guida.build_guida_estimated_features(raw))

    # CHANTIER (feature/equity-asset-class): off by default
    # (`enable_fundamentals_features`), same short-circuit pattern as
    # `guida_on` above -- `build_equity_fundamentals_features` itself is a
    # no-op (empty DataFrame) for a non-equity target, but the flag check
    # here also skips the fundamentals fetch call entirely when off,
    # matching `enable_guida_features`'s "unchanged default pool" guarantee.
    if config.features.enable_fundamentals_features:
        parts.append(equity_fundamentals.build_equity_fundamentals_features(
            config.objective.target_symbol, raw.index))

    if "technical" in families:
        ohlc = download_ohlc(config.objective.target_symbol, config.universe.start_date)
        if ohlc is not None:
            ohlc_aligned = ohlc.reindex(raw.index).ffill()
            parts.append(technical.ohlc_vol_features(ohlc_aligned, prefix=target_col, windows=ohlc_vol_windows))

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
    scope decision).

    Cached on disk per (raw content, feature config, fit cut, feature code)
    -- `features/pool_cache.py` -- which also covers the particle filter the
    DB cache above does not."""
    payload = {**_features_payload(config), "fit_end_idx": fit_end_idx, "test_end_idx": test_end_idx}
    return pool_cache.cached(
        "parametric", raw, payload,
        lambda: _build_parametric_pool(raw, config, fit_end_idx, test_end_idx, conn, snapshot_id))


def _build_parametric_pool(raw: pd.DataFrame, config: RunConfig, fit_end_idx: int | None,
                           test_end_idx: int | None, conn, snapshot_id: str | None) -> pd.DataFrame:
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
                    except (TypeError, ValueError) as exc:
                        # Only the exceptions the underlying pandas/numpy
                        # elementwise arithmetic (INTERACTION_TYPES) can
                        # actually raise here (bad dtype, misaligned
                        # shapes) -- `apply_interaction` already neutralizes
                        # a ~0 denominator (±inf -> NaN), so this is not
                        # expected to fire in the common case. Logged
                        # (never silent) with the offending column name.
                        logger.warning(
                            "interaction %r skipped for fold pool: %s", col_name, exc)
                break
    return full_inter


def build_full_feature_pool(raw: pd.DataFrame, config: RunConfig, target_col: str,
                             interaction_formulas: list[str] | None = None) -> pd.DataFrame:
    """Base + parametric (single whole-history fit, `fit_end_idx=None`) +
    already-discovered interaction formulas, deduplicated -- the "rebuild the
    full pool matching an already-exported model bundle" recipe, shared by
    `predict.py::predict_live` and both entry points of `explain.py`
    (`explain_last_prediction`, `compute_drift_for_ticker_horizon`), which
    used to duplicate this exact sequence three times. Not the per-fold pool
    used during a scan (`_FoldPoolBuilder`/`build_parametric_pool(fit_end_idx=cut)`)
    -- this always fits parametric features on the whole history, matching
    what `tracking.export.export_best_model` trained the persisted model on."""
    base_pool = build_base_feature_pool(raw, config, target_col)
    full_pool = pd.concat([base_pool, build_parametric_pool(raw, config, fit_end_idx=None)], axis=1)
    full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
    if interaction_formulas:
        inter = _apply_interaction_formulas(full_pool, interaction_formulas)
        full_pool = pd.concat([full_pool, inter], axis=1)
    return full_pool


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
                want_baselines: bool = False,
                external_regime_series: pd.Series | None = None) -> FoldData | None:
        """`external_regime_series` (CHANTIER B, feature/model-categories-
        comparison): when provided, `regime` is matched against THIS series
        instead of the CALM/NORMAL/STRESS price-level classifier
        `build_target` computes internally (`reg_r` below) -- a DIFFERENT,
        pre-existing regime concept (quantiles of the price LEVEL, not the
        causal HMM volatility regime of `features/regime_detection.py`).
        `None` (every existing call site, unchanged) preserves the exact
        original behavior -- this parameter is purely additive. Rows where
        `external_regime_series` is NaN (e.g. not enough history yet for the
        HMM to have produced a label) are excluded from both train and test,
        never silently included in either."""
        cfg = self.config
        cut, nxt = self.fold_cuts[fold_idx], self.fold_cuts[fold_idx + 1]
        cut_date, nxt_date = self.all_dates[cut], self.all_dates[nxt - 1]
        pool = self.pool_builder.get(cut)

        target_series, reg_r, thr = build_target(
            pool[self.target_col], horizon, cut, cfg.objective.flat_thr)
        idx = target_series.index
        tr_mask = np.asarray(idx < cut_date)
        te_mask = np.asarray((idx >= cut_date) & (idx <= nxt_date))
        if external_regime_series is not None:
            reg_al = external_regime_series.reindex(idx).values
            # pd.notna guard first: comparing pd.NA/NaN == regime returns
            # pd.NA (not False), which would corrupt the boolean mask below.
            sel = np.asarray([bool(pd.notna(r)) and r == regime for r in reg_al])
        else:
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
    two DIFFERENT results collide under the same key (silent corruption).

    `ranking` (`selection._common.RANKING_VERSION`): the ranking rule itself
    -- a change to it (e.g. the switch to a CPU-independent tie-break)
    changes the result for identical inputs, so it must change the key."""
    payload = json.dumps({
        "method": config.selection.method, "n_feat": n_feat,
        "shap_sample": config.selection.shap_sample,
        "pool_prefilter": config.features.pool_prefilter, "seed": seed,
        "ranking": RANKING_VERSION,
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
    """Returns (metrics_dict, y_pred, predicted_confidence) -- the historical
    3-tuple API, see `_fit_eval_full` (which also returns P(up))."""
    met, y_pred, confidence, _p_up = _fit_eval_full(
        X_tr, y_tr, X_te, y_te, sampler_name, algo, seed, calibration=calibration,
        sample_weight=sample_weight, ind_matrix=ind_matrix,
        uniqueness_weights_enabled=uniqueness_weights_enabled, **algo_overrides)
    return met, y_pred, confidence


def _fit_eval_full(X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, y_te: np.ndarray,
                   sampler_name: str, algo: str, seed: int, calibration: bool = False,
                   sample_weight: np.ndarray | None = None, ind_matrix: np.ndarray | None = None,
                   uniqueness_weights_enabled: bool = True, calibration_method: str = "isotonic",
                   calibration_gap: int = 0, **algo_overrides):
    """Returns (metrics_dict, y_pred, predicted_confidence, p_up).
    `predicted_confidence` (probability of the predicted class, one value per
    test row) feeds `prediction.y_proba`; `p_up` (P(slight up) + P(strong
    up), roadmap bloc 3) feeds `prediction.p_up` and the `Brier_up` /
    `ECE_up` metrics -- `None` when the model has no `predict_proba`.

    `sampler_name="none"` (Phase 5.3, `models/samplers.py::_NoResample`): no
    resampling, relies on `class_weight`/`auto_class_weights` already
    hardcoded for RandomForest/LightGBM/CatBoost (`models/registry.py`) --
    XGBoost/GradientBoosting have no native multiclass equivalent and
    therefore stay unweighted in this case.

    `calibration=True` (`config.models.calibration`, method
    `config.models.calibration_method`): the train rows are split in time
    (`models/calibration.py::calibration_split`): fit | `calibration_gap`
    purged rows (label overlap, the horizon) | calibration | threshold. The
    classifier is fitted on the (resampled) fit rows only; the isotonic or
    Platt map on the REAL calibration rows; the threshold on the REAL
    threshold rows. (The Phase 5.3 path calibrated on the resampled array
    and chose the threshold on its tail -- SMOTE's synthetic rows.) Too
    short a train falls back to the uncalibrated path.

    `sample_weight`/`ind_matrix` (Phase 6.2, P6.2): uniqueness weights and
    observation x bar indicator matrix, computed on `X_tr`/`y_tr` BEFORE
    resampling. Applied only if `sampler_name=="none"` (`Xr` then stays
    unchanged X_tr, same row order/count -- SMOTE and the other oversamplers
    synthesize observations with no real span, an accepted limitation
    documented in `SamplingConfig`). For RandomForest: sequential bootstrap
    (`SequentialBootstrapRandomForestClassifier`) rather than sklearn's
    uniform bootstrap. For other algos that support it: `sample_weight`
    passed directly to `.fit()`. Combination with `calibration=True` not
    handled (documented limitation): the calibrated path stays unweighted
    even when weights are available."""
    apply_uniqueness = (uniqueness_weights_enabled and sampler_name == "none"
                         and sample_weight is not None)
    clf = get_classifier(algo, seed=seed, **algo_overrides)
    split = calibration_lib.calibration_split(len(X_tr), gap=calibration_gap) if calibration else None

    p_up = None
    if split is not None:
        Xf, yf = safe_resample(sampler_name, seed, X_tr[:split.fit_end], y_tr[:split.fit_end])
        clf.fit(Xf, yf)
        cal_clf = calibration_lib.fit_prefit_calibrator(
            clf, X_tr[split.cal_start:split.thr_start], y_tr[split.cal_start:split.thr_start],
            method=calibration_method)
        threshold, _ = calibration_lib.search_threshold(cal_clf, X_tr[split.thr_start:], y_tr[split.thr_start:])
        y_pred = calibration_lib.predict_with_threshold(cal_clf, X_te, threshold)
        y_proba = cal_clf.predict_proba(X_te)
        classes = list(cal_clf.classes_)
        confidence = np.array([row[classes.index(p)] if p in classes else np.nan
                                for row, p in zip(y_proba, y_pred)])
        p_up = calibration_lib.p_up_from_proba(y_proba, classes)
    else:
        Xr, yr = safe_resample(sampler_name, seed, X_tr, y_tr)
        weight_applies = apply_uniqueness and len(Xr) == len(X_tr)
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
            except (AttributeError, IndexError, ValueError):
                y_proba = None
            if y_proba is not None:
                classes = list(getattr(clf, "classes_", range(y_proba.shape[1])))
                p_up = calibration_lib.p_up_from_proba(y_proba, classes)
    met = metrics(y_te, y_pred, y_proba=y_proba)
    if p_up is not None and len(p_up) == len(y_te):
        y_up = np.isin(np.asarray(y_te), calibration_lib.UP_CLASSES).astype(float)
        met["Brier_up"] = calibration_lib.brier_score(p_up, y_up)
        met["ECE_up"] = calibration_lib.expected_calibration_error(p_up, y_up)
    return met, y_pred, confidence, p_up


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


def _evaluate_holdout(conn, snapshot_id: str, pool_builder: _FoldPoolBuilder, target_col: str,
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
    met, y_pred, confidence, p_up = _fit_eval_full(
        X_tr[:, cols], y_tr, X_te[:, cols], y_te, sampler_name, algo, seed,
        calibration=config.models.calibration, calibration_method=config.models.calibration_method,
        calibration_gap=horizon, **best_params)
    test_dates = [str(d.date()) for d in idx[te_mask]]
    # F08: the baselines predicted on the SAME holdout rows, so the final
    # Diebold-Mariano test runs on data that never took part in a choice.
    baseline_predictions = compute_baselines(
        pool[target_col], target_series, idx, tr_mask, te_mask, y_tr, y_te, horizon, _thr, reg_r,
        return_predictions=True)
    return {"metrics": met, "y_pred": y_pred, "y_proba": confidence, "y_true": y_te, "p_up": p_up,
            "test_dates": test_dates, "n_train": len(y_tr), "n_test": len(y_te),
            "baseline_predictions": baseline_predictions}


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


def _best_baseline_among(fd: FoldData, candidate_keys: list[str]) -> tuple[str | None, np.ndarray | None]:
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
        if f1 is not None and not is_nan(f1) and f1 > best_f1:
            best_f1, best_name, best_pred = f1, key, pred
    return best_name, best_pred


def _dm_against_baselines(y_true, y_pred, baseline_predictions: dict | None,
                          class_name: str | None, horizon: int) -> dict:
    """Diebold-Mariano (0/1 directional loss, HLN) of the model against the
    class-specific baseline `class_name` and the common persistence
    baseline, all predicted on the same rows. A baseline absent from
    `baseline_predictions` gives `None` for its kind."""
    y_true = np.asarray(y_true).ravel()
    loss_model = (np.asarray(y_pred).ravel() != y_true).astype(float)

    def against(name: str | None) -> dict | None:
        pred = (baseline_predictions or {}).get(name) if name else None
        if pred is None:
            return None
        dm = diebold_mariano(loss_model, (np.asarray(pred).ravel() != y_true).astype(float), h=horizon)
        dm["baseline"] = name
        return dm

    return {"class_specific": against(class_name), "common": against(_COMMON_BASELINE_KEY)}


def _evaluate_diebold_mariano(conn, snapshot_id: str, ctx: _FoldContext, best_cfg: dict,
                               last_fold: int, seed: int, holdout_eval: dict | None = None) -> dict | None:
    """DM (Phase 2.5) between the winning config and TWO baselines (Phase
    X5):

    - `class_specific`: the best one (highest F1_dir) among the candidates
      configured for the target's asset class
      (`validation.baseline_by_asset_class`, see `classify_asset_class`),
      CHOSEN ON THE LAST WALK-FORWARD FOLD (selection data);
    - `common`: class-agnostic persistence, ALWAYS computed in addition, as
      a fixed reference allowing asset classes to be compared on an equal
      footing (never configurable).

    Sample (F08): the test runs on the terminal holdout (`holdout_eval`,
    the chosen model retrained before the holdout, baselines predicted on
    the same rows) -- data that took no part in any choice. The last
    walk-forward fold is part of the selection criterion (mean F1_dir over
    all folds): testing there biased the p-value towards significance. It
    is only the fallback when no holdout evaluation exists, recorded as
    `sample = 'last_wf_fold'` and excluded from the cross-target BH family.

    Returns `None` only if neither comparison could be computed -- otherwise
    a dict with `sample`, `asset_class` and either kind possibly `None`."""
    horizon, regime = int(best_cfg["horizon"]), best_cfg["regime"]
    fd = ctx.prepare(horizon, last_fold, regime, want_baselines=True)
    if fd is None or not fd.baseline_predictions:
        return None
    asset_class = classify_asset_class(ctx.config.objective.target_symbol,
                                        ctx.config.objective.target_source)
    candidate_kinds = ctx.config.validation.baseline_by_asset_class.get(asset_class, ["persistence"])
    candidate_keys = [_BASELINE_KIND_TO_KEY[k] for k in candidate_kinds if k in _BASELINE_KIND_TO_KEY]
    class_name, _ = _best_baseline_among(fd, candidate_keys)

    if holdout_eval is not None and holdout_eval.get("baseline_predictions"):
        sample = "holdout"
        dms = _dm_against_baselines(holdout_eval["y_true"], holdout_eval["y_pred"],
                                    holdout_eval["baseline_predictions"], class_name, horizon)
    else:
        sample = "last_wf_fold"
        n_feat, sampler_name, algo = int(best_cfg["N"]), best_cfg["sampler"], best_cfg["algo"]
        best_params = _parse_params(best_cfg.get("best_params"))
        cols = _select(conn, ctx.target_col, horizon, snapshot_id, ctx.config, fd.X_tr, fd.y_tr, n_feat, seed)
        _, y_pred, _ = _fit_eval(fd.X_tr[:, cols], fd.y_tr, fd.X_te[:, cols], fd.y_te,
                                  sampler_name, algo, seed,
                                  calibration=ctx.config.models.calibration, **best_params)
        print("  [WARN] Diebold-Mariano on the last walk-forward fold (no holdout evaluation): "
              "selection-biased, excluded from the cross-target BH family.")
        dms = _dm_against_baselines(fd.y_te, y_pred, fd.baseline_predictions, class_name, horizon)

    if dms["class_specific"] is None and dms["common"] is None:
        return None
    return {"asset_class": asset_class, "sample": sample, **dms}


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
                                    confidence[row_sel].tolist() if confidence is not None
                                     else [None] * int(row_sel.sum()))

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


@dataclass
class _RunState:
    """Everything the phases of one `run_pipeline` call share. Before the
    golden-master refactor (`tests/test_run_pipeline_golden.py`) these were
    ~30 locals of a single 532-line function."""
    config: RunConfig
    conn: object
    raw: pd.DataFrame
    target_col: str
    seed: int
    t0: float
    snapshot_id: str
    config_hash: str
    run_ids: dict[int, str]
    base_pool: pd.DataFrame | None = None
    all_dates_full: pd.DatetimeIndex | None = None
    n_wf: int = 0
    pool_builder: _FoldPoolBuilder | None = None
    ctx: _FoldContext | None = None
    feature_pool: list[str] = field(default_factory=list)
    last_fold: int | None = None
    board: Leaderboard = field(default_factory=Leaderboard)
    trial_ids: dict[tuple, int] = field(default_factory=dict)
    n_trials_per_run: dict[str, int] = field(default_factory=dict)
    baseline_rows: list[dict] = field(default_factory=list)
    baseline_accum: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    tuned_rows: list[dict] = field(default_factory=list)
    tuned_trial_ids: dict[tuple, int] = field(default_factory=dict)
    cpcv_full_pool: pd.DataFrame | None = None
    cpcv_interaction_formulas: list[str] | None = None

    @property
    def is_walkforward(self) -> bool:
        return self.config.validation.scheme == "walkforward"

    @property
    def has_holdout(self) -> bool:
        return self.n_wf < len(self.all_dates_full)

    def record_phase_all_runs(self, phase: str, start: float, end: float) -> None:
        """Phases that mix every horizon (ingestion, pool, holdout
        diagnostic, CSV export): one identical start/end row per run_id,
        never a false per-horizon split of a genuinely mixed loop."""
        for run_id in self.run_ids.values():
            trackdb.record_phase_timing(self.conn, run_id, phase, start, end)


def _register_runs(conn, config: RunConfig, raw: pd.DataFrame, seed: int, job_id: str | None,
                   ) -> tuple[str, str, dict[int, str]]:
    """Snapshot context (Phase 1.6) + one `run` row per horizon, sharing the
    snapshot. Returns (snapshot_id, config_hash, run_ids)."""
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
    return snapshot_id, config_hash, run_ids


def _scan_cpcv(st: _RunState) -> None:
    """Phase 6.1 (P6.1) -- CPCV as an ALTERNATIVE to walk-forward. Its pool
    build and scan loop are entangled inside `_run_cpcv_scan`: recorded as
    "scan" only, no "pool_construction" row (see migration 0016)."""
    t_scan_start = time.time()
    (st.board, st.trial_ids, st.n_trials_per_run, st.cpcv_full_pool, st.feature_pool,
     st.cpcv_interaction_formulas) = _run_cpcv_scan(st.raw, st.config, st.base_pool, st.target_col, st.conn,
                                                    st.run_ids, st.seed, st.snapshot_id)
    st.record_phase_all_runs("scan", t_scan_start, time.time())
    st.n_wf = len(st.all_dates_full)  # CPCV: no terminal holdout (accepted limitation, see _run_cpcv_scan)


def _prepare_walkforward(st: _RunState, t_pool_start: float) -> None:
    """Terminal holdout span (Phase 2.1), fold cuts, first fold's full pool
    (base + parametric + interactions) -- the only pool build cleanly
    attributable to "pool_construction"; later folds' pools are built lazily
    inside the scan (migration 0016's known limitation)."""
    config = st.config
    st.n_wf = _walk_forward_span(st.all_dates_full, config.validation.holdout_months,
                                 config.validation.min_train_frac)
    all_dates = st.all_dates_full[:st.n_wf]
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    describe_folds(all_dates, fold_cuts)
    if st.has_holdout:
        print(f"[HOLDOUT] {len(st.all_dates_full) - st.n_wf} rows reserved "
              f"({st.all_dates_full[st.n_wf].date()} -> {st.all_dates_full[-1].date()}), "
              "never seen by selection/tuning.")
    st.pool_builder = _FoldPoolBuilder(st.raw, config, st.target_col, st.base_pool, fold_cuts,
                                       conn=st.conn, snapshot_id=st.snapshot_id)
    st.feature_pool = [c for c in st.pool_builder.get(fold_cuts[0]).columns if c != st.target_col]
    st.record_phase_all_runs("pool_construction", t_pool_start, time.time())
    print(f"[FEATURES] full pool (fold 1, base+parametric+interactions): {len(st.feature_pool)} columns")
    st.ctx = _FoldContext(st.pool_builder, st.target_col, st.feature_pool, config, all_dates, fold_cuts)
    st.n_trials_per_run = {h: 0 for h in st.run_ids.values()}
    st.last_fold = config.validation.n_wf_folds - 1


def _trial_id_for(st: _RunState, run_id: str, trial_key: tuple) -> int:
    """One `trial` row per (horizon, regime, N, sampler, algo), created on
    first evaluation (and registered in `trial_registry`, F03)."""
    if trial_key not in st.trial_ids:
        _horizon, regime, n_feat, sampler_name, algo = trial_key
        st.trial_ids[trial_key] = trackdb.create_trial(
            st.conn, run_id, regime, algo, sampler_name, n_feat, selector=st.config.selection.method)
        st.n_trials_per_run[run_id] += 1
    return st.trial_ids[trial_key]


def _scan_walkforward_fold(st: _RunState, horizon: int, run_id: str, k: int, regime: str) -> None:
    """Grid (N x sampler x algo) on one (horizon, fold, regime): leaderboard
    rows, fold metrics and test predictions of every trial."""
    config = st.config
    fd = st.ctx.prepare(horizon, k, regime, want_baselines=True)
    if fd is None:
        return
    for baseline_name, base_met in (fd.baselines or {}).items():
        st.baseline_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime,
                                 "N": None, "sampler": None, "algo": baseline_name,
                                 "features": "", "n_train": len(fd.y_tr), "n_test": len(fd.y_te),
                                 "test_start": fd.test_start, "test_end": fd.test_end, **base_met})
        st.baseline_accum.setdefault((run_id, baseline_name), []).append(base_met)

    for n_feat in config.selection.n_features_grid:
        cols = _select(st.conn, st.target_col, horizon, st.snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, st.seed)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
        feat_names = [st.feature_pool[c] for c in cols]
        for sampler_name in config.sampler.candidates:
            for algo in config.models.algos:
                met, y_pred, confidence, p_up = _fit_eval_full(
                    X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, st.seed,
                    calibration=config.models.calibration, calibration_method=config.models.calibration_method,
                    calibration_gap=horizon, sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                    uniqueness_weights_enabled=config.sampling.uniqueness_weights)
                # Phase 6.2 (P6.2): effective sample size (sum of uniquenesses)
                # alongside n_train -- always computed.
                st.board.add(horizon=horizon, fold=k + 1, regime=regime, N=n_feat,
                             sampler=sampler_name, algo=algo, features="|".join(feat_names),
                             n_train=len(fd.y_tr), n_test=len(fd.y_te), effective_n_train=fd.effective_n,
                             test_start=fd.test_start, test_end=fd.test_end, **met)
                trial_id = _trial_id_for(st, run_id, (horizon, regime, n_feat, sampler_name, algo))
                # n_eff stored as one more "metric" (generic trial/fold/split/metric
                # schema) -- read by the HTML report alongside F1_dir.
                met_with_n = dict(met)
                met_with_n["n_train"] = float(len(fd.y_tr))
                if fd.effective_n is not None:
                    met_with_n["effective_n_train"] = fd.effective_n
                trackdb.add_fold_metrics(st.conn, trial_id, fold_index=k + 1, split="test", metrics=met_with_n)
                trackdb.add_predictions(st.conn, trial_id, fold_index=k + 1, split="test",
                                        ts=fd.test_dates, y_true=fd.y_te, y_pred=y_pred, y_proba=confidence,
                                        p_up=p_up)


def _scan_walkforward(st: _RunState) -> None:
    config = st.config
    for horizon in config.objective.horizons:
        run_id = st.run_ids[horizon]
        t_scan_start = time.time()
        for k in range(config.validation.n_wf_folds):
            for regime in config.objective.regimes:
                _scan_walkforward_fold(st, horizon, run_id, k, regime)
            print(f"  h={horizon:2d}d fold{k+1}: {len(st.board.rows)} cumulative rows "
                  f"[{time.time()-st.t0:.0f}s]")
        trackdb.record_phase_timing(st.conn, run_id, "scan", t_scan_start, time.time())


def _board_for_horizon(board: Leaderboard, horizon: int, models_only: bool = True) -> Leaderboard:
    board_h = Leaderboard()
    board_h.rows = [r for r in board.rows
                    if r.get("horizon") == horizon and (not models_only or r.get("N") is not None)]
    return board_h


def _track_stability(st: _RunState) -> None:
    """Phase 6.3 (P6.3) -- feature selection stability PER HORIZON, for the
    locally winning (regime, N) config of that horizon (fold-averaged,
    independent of the global `final_best`), measured on the features each
    fold actually retained (`board.rows[...]["features"]`, no re-selection).
    Walk-forward only (CPCV rows do not carry per-fold features)."""
    if not (st.config.selection.track_stability and st.is_walkforward):
        return
    for horizon in st.config.objective.horizons:
        board_h = _board_for_horizon(st.board, horizon)
        top_h = board_h.top_k(1, metric="F1_dir")
        if not top_h:
            continue
        winner = top_h[0]
        t_start = time.time()
        fold_feature_sets: dict[int, list[str]] = {}
        for r in board_h.rows:
            if r["regime"] == winner["regime"] and r["N"] == winner["N"]:
                fold_feature_sets.setdefault(r["fold"], r["features"].split("|") if r["features"] else [])
        stability = feature_selection_stability(fold_feature_sets)
        trackdb.save_feature_stability(st.conn, st.run_ids[horizon], stability["mean_jaccard"],
                                       stability["n_folds"], stability["selection_freq"])
        if stability["warning"]:
            print(f"  [STABILITY] h={horizon}d: {stability['warning']}")
        trackdb.record_phase_timing(st.conn, st.run_ids[horizon], "stability", t_start, time.time())


def _holdout_diagnostic(st: _RunState) -> None:
    """Audit report, C4 -- holdout metrics of the WHOLE scan grid, written to
    `holdout_diagnostic` (never read by selection/tuning): a test/holdout
    rank correlation after the fact, never influencing the choice."""
    if not (st.is_walkforward and st.has_holdout and st.trial_ids):
        return
    print(f"[HOLDOUT DIAGNOSTIC] evaluating {len(st.trial_ids)} trials on the holdout "
          "(read-only, chooses nothing)...")
    t_start = time.time()
    for (h, regime, n_feat, sampler_name, algo), tid in st.trial_ids.items():
        diag_cfg = {"horizon": h, "regime": regime, "N": n_feat, "sampler": sampler_name, "algo": algo,
                    "best_params": {}}
        diag_eval = _evaluate_holdout(st.conn, st.snapshot_id, st.pool_builder, st.target_col, st.feature_pool,
                                      st.config, st.all_dates_full, st.n_wf, diag_cfg, st.seed)
        if diag_eval is not None:
            trackholdout.write_holdout_diagnostic(st.conn, tid, diag_eval["metrics"])
    st.record_phase_all_runs("holdout_diagnostic", t_start, time.time())


def _tuning_candidates(st: _RunState) -> list[dict]:
    """Audit report, C3: top_k PER horizon by default -- a horizon whose best
    scan trial dominates must not capture the whole Optuna budget."""
    config = st.config
    if not config.tuning.optuna_select_top_k_per_horizon:
        return st.board.top_k(config.tuning.top_k, metric="F1_dir")
    top_configs = []
    for horizon in config.objective.horizons:
        top_configs.extend(_board_for_horizon(st.board, horizon, models_only=False)
                           .top_k(config.tuning.top_k, metric="F1_dir"))
    return top_configs


def _tune_one(st: _RunState, cfg: dict, optuna_storage_path: str) -> None:
    """Optuna on the last fold's train (purged inner CV, F02; every trial
    registered, F03), then the tuned config re-evaluated on every fold."""
    config = st.config
    horizon, regime, n_feat = int(cfg["horizon"]), cfg["regime"], int(cfg["N"])
    sampler_name, algo = cfg["sampler"], cfg["algo"]
    run_id = st.run_ids[horizon]
    fd = st.ctx.prepare(horizon, st.last_fold, regime)
    if fd is None or len(fd.y_tr) < config.validation.min_train_rows * 2:
        return
    t_tune_start = time.time()
    cols = _select(st.conn, st.target_col, horizon, st.snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, st.seed)
    study_name = study_name_for(config.name, st.config_hash, horizon, regime, n_feat, sampler_name, algo)
    try:
        best_params, best_cv = tune_config(
            fd.X_tr[:, cols], fd.y_tr, algo, sampler_name, n_trials=config.tuning.n_trials,
            cv_splits=config.tuning.cv_splits, seed=st.seed, storage_path=optuna_storage_path,
            study_name=study_name, bounds=config.tuning.optuna_bounds, horizon=horizon,
            embargo_bars=config.validation.embargo_bars, purge=config.validation.purge,
            embargo_enabled=config.validation.embargo_enabled,
            registry=trackdb.TrialRecorder(st.conn, config.objective.target_symbol, horizon,
                                           run_id=run_id, detail=study_name))
    except InnerCVInfeasible as exc:
        print(f"  [WARN] h={horizon}d {regime} N={n_feat} {sampler_name} {algo}: Optuna skipped -- {exc}")
        return
    print(f"  h={horizon}d {regime} N={n_feat} {sampler_name} {algo}: "
          f"cv_F1_dir={best_cv:.4f} params={best_params}")

    tuned_key = (horizon, regime, n_feat, sampler_name, algo, json.dumps(best_params, sort_keys=True))
    st.tuned_trial_ids[tuned_key] = trackdb.create_trial(
        st.conn, run_id, regime, algo, sampler_name, n_feat,
        selector=config.selection.method, params_json=json.dumps(best_params))
    st.n_trials_per_run[run_id] += 1
    tuned_trial_id = st.tuned_trial_ids[tuned_key]

    for k in range(config.validation.n_wf_folds):
        fd = st.ctx.prepare(horizon, k, regime)
        if fd is None:
            continue
        cols = _select(st.conn, st.target_col, horizon, st.snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, st.seed)
        met, y_pred, confidence, p_up = _fit_eval_full(
            fd.X_tr[:, cols], fd.y_tr, fd.X_te[:, cols], fd.y_te, sampler_name, algo, st.seed,
            calibration=config.models.calibration, calibration_method=config.models.calibration_method,
            calibration_gap=horizon, sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
            uniqueness_weights_enabled=config.sampling.uniqueness_weights, **best_params)
        st.tuned_rows.append({"horizon": horizon, "fold": k + 1, "regime": regime, "N": n_feat,
                              "sampler": sampler_name, "algo": algo, "best_params": str(best_params),
                              "effective_n_train": fd.effective_n, "test_start": fd.test_start,
                              "test_end": fd.test_end, **met})
        trackdb.add_fold_metrics(st.conn, tuned_trial_id, fold_index=k + 1, split="test", metrics=met)
        trackdb.add_predictions(st.conn, tuned_trial_id, fold_index=k + 1, split="test",
                                ts=fd.test_dates, y_true=fd.y_te, y_pred=y_pred, y_proba=confidence, p_up=p_up)
    trackdb.record_phase_timing(st.conn, run_id, "tuning", t_tune_start, time.time())


def _tune(st: _RunState) -> None:
    """Walk-forward only (relies on `ctx.prepare`'s train=prefix topology).
    Phase 3.2 (`patrick resume`): studies persisted in `optuna.db` (never
    `patrick.db`) under a deterministic, versioned name."""
    config = st.config
    if not (st.is_walkforward and config.tuning.enabled and len(st.board.rows)):
        return
    top_configs = _tuning_candidates(st)
    print(f"\n[OPTUNA] tuning the {len(top_configs)} best configs "
          f"({config.tuning.n_trials} trials, CV={config.tuning.cv_splits}, "
          f"per_horizon={config.tuning.optuna_select_top_k_per_horizon})...")
    os.makedirs(config.output.dir, exist_ok=True)
    optuna_storage_path = os.path.join(config.output.dir, "optuna.db")
    for cfg in top_configs:
        _tune_one(st, cfg, optuna_storage_path)


def _export_tables(st: _RunState) -> pd.DataFrame:
    """Leaderboard (+ baselines) and tuned CSVs, then per-run averaged
    baseline metrics (`baseline_metric` has no fold column). Returns the
    tuned rows as a DataFrame."""
    config = st.config
    t_start = time.time()
    tuned_df = pd.DataFrame(st.tuned_rows)
    if st.baseline_rows:
        st.board.rows.extend(st.baseline_rows)
    csv_path = st.board.export(config.output.dir, config.name)
    if len(tuned_df):
        os.makedirs(config.output.dir, exist_ok=True)
        tuned_path = os.path.join(config.output.dir, f"{config.name}_tuned.csv")
        tuned_df.to_csv(tuned_path, index=False)
        print(f"[EXPORT] {tuned_path}")
    print(f"[EXPORT] {csv_path}")
    st.record_phase_all_runs("export", t_start, time.time())

    for (run_id, baseline_name), fold_dicts in st.baseline_accum.items():
        agg = {}
        for m in {k for d in fold_dicts for k in d}:
            values = [v for v in (d.get(m) for d in fold_dicts) if v is not None and not is_nan(v)]
            if values:
                agg[m] = float(np.mean(values))
        trackdb.add_baseline_metrics(st.conn, run_id, baseline_name, split="test", metrics=agg)
    return tuned_df


def _select_finals(st: _RunState, best: dict | None, tuned_df: pd.DataFrame) -> tuple[dict | None, dict[int, dict]]:
    """Global winner and one winner per horizon, each the better of the
    fold-averaged scan and the fold-averaged tuned configs (F07: never a
    single fold). Per-horizon export: `predict --live` needs an exported
    model for EVERY horizon's run_id, not only the global winner's."""
    group_cols = ["horizon", "regime", "N", "sampler", "algo"]
    final_best = dict(best) if best else None
    tuned_agg = None
    if len(tuned_df):
        tuned_agg = rank_configs(
            tuned_df.groupby(group_cols + ["best_params"])["F1_dir"].mean().reset_index(),
            "F1_dir", group_cols + ["best_params"])
        if len(tuned_agg) and (final_best is None or tuned_agg.iloc[0]["F1_dir"] > final_best["F1_dir"]):
            final_best = tuned_agg.iloc[0].to_dict()

    final_best_by_horizon: dict[int, dict] = {}
    for horizon in st.config.objective.horizons:
        best_h = _board_for_horizon(st.board, horizon).best(metric="F1_dir")
        if tuned_agg is not None:
            tuned_h = tuned_agg[tuned_agg["horizon"] == horizon]
            if len(tuned_h) and (best_h is None or tuned_h.iloc[0]["F1_dir"] > best_h["F1_dir"]):
                best_h = tuned_h.iloc[0].to_dict()
        if best_h is not None:
            final_best_by_horizon[horizon] = best_h
    return final_best, final_best_by_horizon


def _full_history_pool(st: _RunState) -> tuple[pd.DataFrame, list[str]]:
    """Pool of the final models (parametric fit on the whole history). CPCV
    already built it (single fit) -- reused as-is."""
    if not st.is_walkforward:
        return st.cpcv_full_pool, st.cpcv_interaction_formulas
    full_pool = pd.concat([st.base_pool, build_parametric_pool(st.raw, st.config, fit_end_idx=None,
                                                               conn=st.conn, snapshot_id=st.snapshot_id)], axis=1)
    full_pool = full_pool.loc[:, ~full_pool.columns.duplicated()]
    formulas = st.pool_builder.interaction_formulas
    if formulas:
        full_pool = pd.concat([full_pool, _apply_interaction_formulas(full_pool, formulas)], axis=1)
    return full_pool, formulas


def _export_models(st: _RunState, final_best_by_horizon: dict[int, dict]) -> tuple[dict[int, str], dict[int, int]]:
    """One exported model per horizon with a winner (joblib + meta + drift
    reference), its trial marked `is_best`. Returns (model_paths,
    trial_id_by_horizon)."""
    full_pool, interaction_formulas = _full_history_pool(st)
    model_paths: dict[int, str] = {}
    trial_id_by_horizon: dict[int, int] = {}
    for horizon, best_h in final_best_by_horizon.items():
        t_start = time.time()
        h_model_path = export_best_model(full_pool, st.target_col, st.feature_pool, st.config, best_h,
                                         st.config.output.dir, seed=st.seed,
                                         interaction_formulas=interaction_formulas,
                                         conn=st.conn, symbol=st.config.objective.target_symbol)
        trackdb.record_phase_timing(st.conn, st.run_ids[horizon], "export", t_start, time.time())
        model_paths[horizon] = h_model_path

        h_best_key = (int(best_h["horizon"]), best_h["regime"], int(best_h["N"]), best_h["sampler"], best_h["algo"])
        h_trial_id = st.trial_ids.get(h_best_key)
        if h_trial_id is None and "best_params" in best_h:
            h_parsed_params = _parse_params(best_h["best_params"])
            h_trial_id = st.tuned_trial_ids.get(h_best_key + (json.dumps(h_parsed_params, sort_keys=True),))
        if h_trial_id is not None:
            trackdb.mark_best_trial(st.conn, h_trial_id, artifact_path=h_model_path)
            trial_id_by_horizon[horizon] = h_trial_id
    return model_paths, trial_id_by_horizon


def _final_holdout(st: _RunState, final_best: dict, best_trial_id: int | None) -> dict | None:
    """Phase 2.1 -- a single re-evaluation of the already-chosen config on the
    terminal holdout, never used to choose among several. Returns the whole
    evaluation (metrics, predictions, baselines' holdout predictions -- the
    latter feed the final Diebold-Mariano test, F08)."""
    if not st.has_holdout:
        return None
    holdout_eval = _evaluate_holdout(st.conn, st.snapshot_id, st.pool_builder, st.target_col, st.feature_pool,
                                     st.config, st.all_dates_full, st.n_wf, final_best, st.seed)
    if holdout_eval is None:
        return None
    if best_trial_id is not None:
        trackdb.add_fold_metrics(st.conn, best_trial_id, fold_index=0, split="holdout",
                                 metrics=holdout_eval["metrics"])
        trackdb.add_predictions(st.conn, best_trial_id, fold_index=0, split="holdout",
                                ts=holdout_eval["test_dates"], y_true=holdout_eval["y_true"],
                                y_pred=holdout_eval["y_pred"], y_proba=holdout_eval["y_proba"],
                                p_up=holdout_eval.get("p_up"))
    return holdout_eval


def _final_diebold_mariano(st: _RunState, final_best: dict, holdout_eval: dict | None) -> dict | None:
    """Phase 2.5 -- DM vs the class-specific and the common baseline, on the
    terminal holdout (F08), persisted in `dm_result` with its sample (P6.4,
    X5). Walk-forward only."""
    if not st.is_walkforward:
        return None
    dm_result = _evaluate_diebold_mariano(st.conn, st.snapshot_id, st.ctx, final_best, st.last_fold, st.seed,
                                          holdout_eval=holdout_eval)
    if dm_result is not None:
        run_id = st.run_ids[int(final_best["horizon"])]
        for kind in ("class_specific", "common"):
            if dm_result.get(kind) is not None:
                trackdb.save_dm_result(st.conn, run_id, dm_result[kind], kind=kind, sample=dm_result["sample"])
    return dm_result


def _finish_runs(st: _RunState) -> None:
    """`finish_run` for every horizon, then the plain-text phase timing log
    (needs `run.finished_at` to compute totals, hence after)."""
    for run_id in st.run_ids.values():
        trackdb.finish_run(st.conn, run_id, status="done", n_trials=st.n_trials_per_run[run_id])
    for run_id in st.run_ids.values():
        breakdown = trackhistory.phase_breakdown_for_run(st.conn, run_id)
        timing_log_path = phase_timing_log.write_phase_timing_log(st.config.output.dir, run_id, breakdown)
        print(f"[EXPORT] phase timing log -> {timing_log_path}")


def run_pipeline(config: RunConfig, store: DataStore | None = None,
                  force_ingest: bool = False, db_path: str | None = None,
                  job_id: str | None = None) -> dict:
    """Ingestion -> run registration -> base pool -> scan (walk-forward or
    CPCV) -> stability -> holdout diagnostic -> Optuna -> CSV exports ->
    final selection -> per-horizon model export -> holdout / Diebold-Mariano
    / cumulative trials / PBO -> finish. Each phase is a function of
    `_RunState`; the sequence is pinned by `tests/test_run_pipeline_golden.py`."""
    store = store or DataStore()
    seed = config.output.seed
    t0 = time.time()

    # Ingestion runs before any run_id exists: timed here, written once the
    # run rows are created (same duplication as run.started_at).
    t_ingest_start = time.time()
    raw = ingest(config.objective, config.universe, store, force=force_ingest, data_quality=config.data_quality)
    t_ingest_end = time.time()

    conn = trackdb.connect(db_path)
    try:
        snapshot_id, config_hash, run_ids = _register_runs(conn, config, raw, seed, job_id)
        st = _RunState(config=config, conn=conn, raw=raw, target_col=clean_symbol(config.objective.target_symbol),
                       seed=seed, t0=t0, snapshot_id=snapshot_id, config_hash=config_hash, run_ids=run_ids,
                       all_dates_full=raw.index)
        st.record_phase_all_runs("ingestion", t_ingest_start, t_ingest_end)

        t_pool_start = time.time()
        print("[FEATURES] building the base pool (causal, shared by all folds)...")
        st.base_pool = build_base_feature_pool(raw, config, st.target_col)
        print(f"[FEATURES] base pool: {st.base_pool.shape[1]} columns ({time.time()-t0:.1f}s)")
        assert (st.base_pool.index == st.all_dates_full).all(), "feature construction must not change the date index"

        if st.is_walkforward:
            _prepare_walkforward(st, t_pool_start)
            _scan_walkforward(st)
        else:
            _scan_cpcv(st)

        print(f"\n[SCAN] {len(st.board.rows)} evaluations in {(time.time()-t0)/60:.1f}min")
        best = st.board.best(metric="F1_dir")
        if best:
            print(f"[BEST before Optuna] h={best['horizon']}d {best['regime']} N={best['N']} "
                  f"{best['sampler']} {best['algo']} -> F1_dir={best['F1_dir']}")

        _track_stability(st)
        _holdout_diagnostic(st)
        _tune(st)
        tuned_df = _export_tables(st)
        final_best, final_best_by_horizon = _select_finals(st, best, tuned_df)

        model_path, model_paths = None, {}
        holdout_result = dm_result = pbo_result = holdout_diagnostic_result = None
        cumulative_trials = 0
        if final_best is not None:
            final_horizon = int(final_best["horizon"])
            model_paths, trial_id_by_horizon = _export_models(st, final_best_by_horizon)
            model_path = model_paths.get(final_horizon)
            holdout_eval = _final_holdout(st, final_best, trial_id_by_horizon.get(final_horizon))
            holdout_result = holdout_eval["metrics"] if holdout_eval is not None else None
            dm_result = _final_diebold_mariano(st, final_best, holdout_eval)
            # Phase 2.2/2.4 -- cumulative trials (registry, F03) and PBO over
            # the whole history of this target/horizon (CPCV paths when that
            # scheme is active).
            target = config.objective.target_symbol
            cumulative_trials = trackstats.count_cumulative_trials(conn, target, final_horizon)
            pbo_fn = trackstats.pbo_for_target if st.is_walkforward else trackstats.pbo_for_target_cpcv
            pbo_result = pbo_fn(conn, target, final_horizon, final_best["regime"])
            if st.is_walkforward:
                holdout_diagnostic_result = trackholdout.spearman_test_vs_holdout(
                    conn, run_ids[final_horizon], metric="F1_dir")

        _finish_runs(st)
        return {
            "leaderboard": st.board.as_df(),
            "tuned": tuned_df,
            "best_before_tuning": best,
            "final_best": final_best,
            "model_path": model_path,
            "model_paths": model_paths,
            "elapsed_s": time.time() - t0,
            "holdout": holdout_result,
            "diebold_mariano": dm_result,
            "cumulative_trials": cumulative_trials,
            "pbo": pbo_result,
            "holdout_diagnostic": holdout_diagnostic_result,
        }
    finally:
        conn.close()
